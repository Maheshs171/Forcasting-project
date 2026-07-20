"""
backend/jobs.py
─────────────────
In-process job runner for predict.py / validate.py. Jobs run one at a
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


@dataclass
class Job:
    id: str
    kind: str                      # "predict" | "validate"
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
    """Redirects writes to both the real stdout and a job's log list."""

    def __init__(self, job: "Job", real_stdout):
        self.job = job
        self.real_stdout = real_stdout
        self._buf = ""

    def write(self, s):
        self.real_stdout.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.job.logs.append(line)
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
        real_stdout = sys.stdout
        sys.stdout = _LineCapture(job, real_stdout)

        def progress_cb(current, total, label):
            job.progress = {"current": current, "total": total, "label": label}

        try:
            args = SimpleNamespace(**job.params)
            if job.kind == "predict":
                result = predict.run(args, progress_cb=progress_cb)
            elif job.kind == "validate":
                result = validate_mod.run(args, progress_cb=progress_cb)
            else:
                raise ValueError(f"Unknown job kind: {job.kind}")
            job.result = result
            job.status = "completed"
        except Exception as e:
            job.error = f"{e}\n{traceback.format_exc()}"
            job.logs.append(f"ERROR: {e}")
            job.status = "failed"
        finally:
            sys.stdout = real_stdout
            job.finished_at = datetime.now().isoformat()


manager = JobManager()
