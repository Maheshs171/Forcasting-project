"""
backend/jobs.py
─────────────────
In-process job runner for predict.py / validate.py / azure_automl.py. Jobs run one at a
time on a dedicated worker thread (SARIMA/Prophet fits are CPU-bound and
this is a single-analyst tool, so serializing is simpler and safer than
worrying about concurrent SQL connections / concurrent stdout capture).

Each job's stdout is captured live into job.logs so the frontend can
poll/stream progress instead of waiting for the whole run to finish.
"""

import sys
import io
import threading
import queue
import uuid
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Optional, Any

sys.path.insert(0, "..")

import predict
import validate as validate_mod
import azure_automl
from utils.logging_setup import setup_logging

# One daily log file per pipeline (logs/<name>.log + logs/<name>_errors.log) —
# lets a specific day's predict/validate/Azure run be pulled up independently.
_LOG_COMPONENT = {
    "predict": "predict", "validate": "validate", "azure_train": "azure",
    "azure_forecast_from_downloads": "azure",
}


@dataclass
class Job:
    id: str
    kind: str                      # "predict" | "validate" | "azure_train" | "azure_forecast_from_downloads"
    params: dict
    status: str = "queued"         # queued | running | completed | failed
    logs: list = field(default_factory=list)
    result: Optional[Any] = None
    error: Optional[str] = None
    progress: dict = field(default_factory=lambda: {"current": 0, "total": 0, "label": None})
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class _LineCapture(io.TextIOBase):
    """Redirects writes to the real stdout, a job's log list (for the
    dashboard's live run console), and that pipeline's daily log file."""

    def __init__(self, job: "Job", real_stdout, logger=None):
        self.job = job
        self.real_stdout = real_stdout
        self.logger = logger
        self._buf = ""

    def write(self, s):
        self.real_stdout.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.job.logs.append(line)
            if self.logger and line.strip():
                self.logger.info(line)
        return len(s)

    def flush(self):
        self.real_stdout.flush()


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()

    def submit(self, kind: str, params: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, params=params)
        with self._lock:
            self.jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    def _run_loop(self):
        while True:
            job_id = self._queue.get()
            job = self.jobs[job_id]
            self._execute(job)

    def _execute(self, job: Job):
        job.status = "running"
        job.started_at = datetime.now().isoformat()
        logger = setup_logging(_LOG_COMPONENT.get(job.kind, job.kind))
        logger.info(f"job {job.id} started — kind={job.kind} params={job.params}")
        real_stdout = sys.stdout
        sys.stdout = _LineCapture(job, real_stdout, logger=logger)

        def progress_cb(current, total, label):
            job.progress = {"current": current, "total": total, "label": label}

        try:
            args = SimpleNamespace(**job.params)
            if job.kind == "predict":
                result = predict.run(args, progress_cb=progress_cb)
            elif job.kind == "validate":
                result = validate_mod.run(args, progress_cb=progress_cb)
            elif job.kind == "azure_train":
                result = azure_automl.run(args, progress_cb=progress_cb)
            elif job.kind == "azure_forecast_from_downloads":
                result = azure_automl.run_from_downloads(args, progress_cb=progress_cb)
            else:
                raise ValueError(f"Unknown job kind: {job.kind}")
            job.result = result
            job.status = "completed"
            logger.info(f"job {job.id} completed")
        except Exception as e:
            job.error = f"{e}\n{traceback.format_exc()}"
            job.logs.append(f"ERROR: {e}")
            job.status = "failed"
            logger.error(f"job {job.id} failed: {e}", exc_info=True)
        finally:
            sys.stdout = real_stdout
            job.finished_at = datetime.now().isoformat()


manager = JobManager()
