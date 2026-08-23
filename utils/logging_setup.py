"""
utils/logging_setup.py
────────────────────────
Central application logging. One pair of daily-rotating log files per
component under logs/:

    logs/<component>.log             everything at INFO and above
    logs/<component>.log.YYYY-MM-DD  yesterday's (and earlier) rotated files
    logs/<component>_errors.log      WARNING and above only (errors/tracebacks)
    logs/<component>_errors.log.YYYY-MM-DD

Rotation happens automatically at midnight (TimedRotatingFileHandler) —
each day's activity ends up in its own file, kept for 30 days, so a
specific day's run can be pulled up for debugging without wading through
the whole history.

Most of this project's pipeline code (predict.py, validate.py,
azure_automl.py, data/fetcher.py) reports progress via plain print()
rather than the logging module — that's also what streams live into the
dashboard's run console (see backend/jobs.py's _LineCapture). Re-plumbing
every print() call into logger.info() would be a large, risky change for
no real benefit, so install_stdio_tee() instead mirrors stdout/stderr
into a component's log file at the process level: every print() keeps
working exactly as before (console + UI log stream), and now also lands
in that day's log file, with no call sites touched.
"""

import logging
import logging.handlers
import os
import sys

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(component: str) -> logging.Logger:
    """Idempotent — safe to call repeatedly (e.g. once per job) for the
    same component; only attaches handlers the first time."""
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(f"app.{component}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    info_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(LOG_DIR, f"{component}.log"),
        when="midnight", backupCount=30, encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    info_handler.suffix = "%Y-%m-%d"

    error_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(LOG_DIR, f"{component}_errors.log"),
        when="midnight", backupCount=30, encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)
    error_handler.suffix = "%Y-%m-%d"

    logger.addHandler(info_handler)
    logger.addHandler(error_handler)
    return logger


class _TeeStream:
    """Mirrors every write to the real stream AND a logger, buffering
    until a full line is available (print() writes the trailing "\\n" as
    a separate call, so line-splitting here — not per-write logging —
    keeps each log entry matching one printed line)."""

    def __init__(self, real_stream, logger: logging.Logger, level: int):
        self.real_stream = real_stream
        self.logger = logger
        self.level = level
        self._buf = ""

    def write(self, s: str) -> int:
        self.real_stream.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line)
        return len(s)

    def flush(self):
        self.real_stream.flush()

    def isatty(self):
        return False


def install_stdio_tee(component: str) -> logging.Logger:
    """
    Process-wide: mirrors stdout (INFO) and stderr (ERROR — this is where
    uncaught tracebacks land) into that component's daily log file, on
    top of whatever's already consuming sys.stdout (a terminal, or
    backend/jobs.py's per-job _LineCapture, which wraps whatever
    sys.stdout already is and restores it afterward — so this composes
    correctly whichever order things start in).

    Call once per process: backend/app.py at import time (component
    "backend", covering the whole API + anything invoked through it that
    doesn't go through JobManager, e.g. direct DB-unreachable warnings
    from data-quality/data-insights endpoints), and each pipeline
    script's __main__ block for standalone CLI runs.
    """
    logger = setup_logging(component)
    if not isinstance(sys.stdout, _TeeStream):
        sys.stdout = _TeeStream(sys.stdout, logger, logging.INFO)
    if not isinstance(sys.stderr, _TeeStream):
        sys.stderr = _TeeStream(sys.stderr, logger, logging.ERROR)
    return logger
