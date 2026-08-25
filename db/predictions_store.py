"""
db/predictions_store.py
─────────────────────────
Persists forecast/prediction reports (both the local pipeline's and Azure
AutoML's) to a MySQL database instead of local outputs/*.json files.

Why: this project previously only wrote results to the local filesystem
(outputs/*.json, models/azure_downloads/). That's fine for a machine you
run yourself, but breaks on a platform like Render whose filesystem is
ephemeral — anything written to disk disappears on every redeploy/restart,
so the dashboard would come up empty after every deploy. Writing reports
to a real database instead makes them durable across restarts/redeploys,
same as any other production app's data.

Scope: this covers the JSON *reports* (predict.py's per-metric summary,
azure_automl.py's per-metric result) — the actual downloaded Azure model
BINARY artifacts (models/azure_downloads/*/*.pkl) are NOT moved here.
Those are multi-megabyte binary files better suited to object storage
(S3/Azure Blob) than a MySQL TEXT column; moving them is a separate,
larger change than what was asked for here (report data, not model
binaries) and is not attempted by this module.

Table layout: one row per (source, metric, frequency), upserted on every
save — mirrors the exact behavior the file-glob-based "latest file" lookup
already had (only the most recent report per combination is ever shown),
without needing an ever-growing history table nobody currently reads.
"""

import json
import threading
import time
from typing import Optional

from config.settings import (
    PREDICTIONS_DB_HOST, PREDICTIONS_DB_PORT, PREDICTIONS_DB_NAME,
    PREDICTIONS_DB_USER, PREDICTIONS_DB_PASSWORD,
)

_INIT_LOCK = threading.Lock()
_initialized = False

# Circuit breaker: a request handler calls several of this module's
# functions per page load (one per metric), each of which would otherwise
# attempt its own fresh connection. When the DB is genuinely unreachable
# (VPN down, firewall not yet allowlisted, server hiccup), that turns one
# slow failure into N of them stacked in series — a single page load could
# take N * CONNECT_TIMEOUT seconds instead of one. After a failure, skip
# reconnecting for COOLDOWN_SECONDS and raise immediately instead, so
# callers' existing file-fallback logic kicks in fast rather than hanging.
CONNECT_TIMEOUT = 4
COOLDOWN_SECONDS = 30
_breaker_lock = threading.Lock()
_last_failure_at: Optional[float] = None


def is_configured() -> bool:
    return bool(PREDICTIONS_DB_HOST and PREDICTIONS_DB_NAME and PREDICTIONS_DB_USER)


def _connect():
    global _last_failure_at
    with _breaker_lock:
        if _last_failure_at is not None and time.monotonic() - _last_failure_at < COOLDOWN_SECONDS:
            raise ConnectionError(
                f"predictions DB skipped — last connection attempt failed "
                f"{time.monotonic() - _last_failure_at:.0f}s ago (retrying after {COOLDOWN_SECONDS}s cooldown)"
            )
    import pymysql
    try:
        conn = pymysql.connect(
            host=PREDICTIONS_DB_HOST,
            port=PREDICTIONS_DB_PORT,
            user=PREDICTIONS_DB_USER,
            password=PREDICTIONS_DB_PASSWORD,
            database=PREDICTIONS_DB_NAME,
            connect_timeout=CONNECT_TIMEOUT,
            ssl={"ssl": {}},  # Azure Database for MySQL requires TLS
            autocommit=True,
        )
    except Exception:
        with _breaker_lock:
            _last_failure_at = time.monotonic()
        raise
    with _breaker_lock:
        _last_failure_at = None
    return conn


def init_schema():
    """Creates the forecast_reports table if it doesn't exist yet. Safe to
    call on every app startup — CREATE TABLE IF NOT EXISTS is a no-op once
    the table's there. Called lazily (on first save/load), not at import
    time, so importing this module never requires DB connectivity."""
    global _initialized
    with _INIT_LOCK:
        if _initialized:
            return
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS forecast_reports (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        source VARCHAR(20) NOT NULL,
                        metric VARCHAR(50) NOT NULL,
                        frequency VARCHAR(10) NOT NULL,
                        generated_at DATETIME NOT NULL,
                        payload LONGTEXT NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_report (source, metric, frequency)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
        finally:
            conn.close()
        _initialized = True


def save_report(source: str, metric: str, frequency: str, generated_at: str, payload: dict):
    """source: 'local' or 'azure'. payload is JSON-serialized (default=str,
    same as the existing json.dump calls, so pandas Timestamps etc. that
    sneak into a report still serialize the same way they already did)."""
    init_schema()
    body = json.dumps(payload, default=str)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO forecast_reports (source, metric, frequency, generated_at, payload)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE generated_at = VALUES(generated_at), payload = VALUES(payload)
                """,
                (source, metric, frequency, generated_at, body),
            )
    finally:
        conn.close()


def load_report(source: str, metric: str, frequency: str) -> Optional[dict]:
    init_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload, generated_at, updated_at FROM forecast_reports "
                "WHERE source = %s AND metric = %s AND frequency = %s",
                (source, metric, frequency),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = json.loads(row[0])
            payload["_generated_at"] = str(row[1])
            payload["_source"] = "db"
            return payload
    finally:
        conn.close()


def load_all_reports(source: str, frequency: str) -> dict:
    """{metric: payload} for every metric currently stored at this
    source/frequency — used by the "all metrics" endpoints."""
    init_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT metric, payload, generated_at FROM forecast_reports "
                "WHERE source = %s AND frequency = %s",
                (source, frequency),
            )
            out = {}
            for metric, payload, generated_at in cur.fetchall():
                data = json.loads(payload)
                data["_generated_at"] = str(generated_at)
                data["_source"] = "db"
                out[metric] = data
            return out
    finally:
        conn.close()


def latest_generated_at(source: str, frequency: str) -> Optional[str]:
    """Newest updated_at across every metric at this source/frequency —
    used for the "report generated N ago" timestamp the frontend shows."""
    init_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(updated_at) FROM forecast_reports WHERE source = %s AND frequency = %s",
                (source, frequency),
            )
            row = cur.fetchone()
            return str(row[0]) if row and row[0] else None
    finally:
        conn.close()
