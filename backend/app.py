"""
backend/app.py
────────────────
Thin FastAPI layer over the existing forecasting pipeline (data/fetcher.py,
models/forecaster.py, validate.py, predict.py). Serves the latest
forecast/backtest outputs to the dashboard, and lets the frontend trigger
new predict/validate runs (executed in-process via jobs.JobManager) with
live progress.

Run:
  uvicorn backend.app:app --reload --port 8000
(from the v1/ project root, so `predict`/`validate`/`config` import cleanly)
"""

import sys, os, json, glob, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.settings import (
    DEFAULT_START_YEAR, DEFAULT_FORECAST_MONTHS, HOLIDAY_COUNTRY,
    SQL_SERVER, SQL_DATABASE,
)
from config import connections as conn_registry
from data.fetcher import FETCHERS
from models.forecaster import ALL_FORECASTERS
from predict import METRIC_LABELS, MONEY_METRICS
from backend.jobs import manager
from utils.eda import build_insights

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")

app = FastAPI(title="Clinical Forecasting API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir(OUTPUTS_DIR):
    app.mount("/charts", StaticFiles(directory=OUTPUTS_DIR), name="charts")


# ── Helpers ──────────────────────────────────────────────────────────────

def _latest_file(pattern: str) -> Optional[str]:
    files = glob.glob(os.path.join(OUTPUTS_DIR, pattern))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _load_json(path: Optional[str]):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _job_public(job, include_logs=True):
    d = {
        "id": job.id, "kind": job.kind, "params": job.params, "status": job.status,
        "progress": job.progress, "created_at": job.created_at,
        "started_at": job.started_at, "finished_at": job.finished_at,
        "error": job.error,
    }
    if include_logs:
        d["logs"] = job.logs
    else:
        d["log_count"] = len(job.logs)
    return d


# ── Static metadata ──────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat()}


@app.get("/api/env")
def env_info():
    active = conn_registry.get_active()
    server = (active["server"] if active else SQL_SERVER) or ""
    database = active["database"] if active else SQL_DATABASE
    return {
        "server": server,
        "database": database,
        "is_qa": "qa" in server.lower() or "test" in server.lower(),
        "connection_name": conn_registry.get_active_name(),
    }


# ── DB connections (Settings page) ───────────────────────────────────────

class ConnectionIn(BaseModel):
    name: str
    server: str
    database: str
    username: str
    password: str
    port: int = 3342
    make_active: bool = True


class TestConnectionIn(BaseModel):
    server: str
    database: str
    username: str
    password: str
    port: int = 3342


@app.get("/api/connections")
def list_connections():
    return conn_registry.list_connections()


@app.post("/api/connections")
def add_connection(body: ConnectionIn):
    ok, msg = conn_registry.test_connection(body.server, body.database, body.username, body.password, body.port)
    conn_registry.add_connection(
        body.name, body.server, body.database, body.username, body.password, body.port, body.make_active
    )
    return {"saved": True, "test_ok": ok, "test_message": msg}


@app.post("/api/connections/test")
def test_connection_endpoint(body: TestConnectionIn):
    ok, msg = conn_registry.test_connection(body.server, body.database, body.username, body.password, body.port)
    return {"ok": ok, "message": msg}


@app.post("/api/connections/{name}/activate")
def activate_connection(name: str):
    try:
        conn_registry.set_active(name)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"active": name}


@app.delete("/api/connections/{name}")
def delete_connection(name: str):
    try:
        conn_registry.delete_connection(name)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"deleted": name}


@app.get("/api/metrics")
def metrics():
    return [
        {"key": k, "label": METRIC_LABELS[k], "is_money": k in MONEY_METRICS}
        for k in FETCHERS.keys()
    ]


@app.get("/api/models")
def models():
    return [
        {"key": k, "name": cls.__name__ if not hasattr(cls, "name") else cls.name, "min_months": cls.min_months}
        for k, cls in ALL_FORECASTERS.items()
    ]


@app.get("/api/config/defaults")
def config_defaults():
    return {
        "start_year": DEFAULT_START_YEAR,
        "months": DEFAULT_FORECAST_MONTHS,
        "country": HOLIDAY_COUNTRY,
    }


# ── Latest outputs ────────────────────────────────────────────────────────

@app.get("/api/forecast/{metric}")
def latest_forecast(metric: str):
    if metric not in FETCHERS:
        raise HTTPException(404, f"Unknown metric '{metric}'")
    path = _latest_file(f"{metric}_*.json")
    data = _load_json(path)
    if data is None:
        raise HTTPException(404, f"No forecast output yet for '{metric}'. Run a prediction first.")
    data["_source_file"] = os.path.basename(path)
    data["_generated_at"] = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
    chart = _latest_file(f"{metric}_*.html")
    data["_chart_url"] = f"/charts/{os.path.basename(chart)}" if chart else None
    return data


@app.get("/api/forecast")
def all_latest_forecasts():
    out = {}
    for metric in FETCHERS.keys():
        try:
            out[metric] = latest_forecast(metric)
        except HTTPException:
            out[metric] = None
    return out


@app.get("/api/summary/latest")
def latest_summary():
    path = _latest_file("summary_*.json")
    data = _load_json(path)
    if data is None:
        raise HTTPException(404, "No combined summary yet. Run a prediction first.")
    return {"data": data, "generated_at": datetime.fromtimestamp(os.path.getmtime(path)).isoformat()}


@app.get("/api/backtest")
def backtest_report():
    """
    Built from each metric's latest forecast file (predict.py already backtests
    every candidate and stores it there) rather than the standalone
    outputs/backtest_report.json, which is only written by validate.py and
    would otherwise go stale as soon as someone runs a forecast without also
    running a separate backtest. Falls back to that file for any metric with
    no forecast yet.
    """
    combined = {}
    newest_mtime = 0.0
    for m in FETCHERS.keys():
        path = _latest_file(f"{m}_*.json")
        data = _load_json(path)
        if data and "backtest" in data:
            combined[m] = {"candidates": data["backtest"], "best_model": data.get("best_model", data.get("model_used"))}
            newest_mtime = max(newest_mtime, os.path.getmtime(path))

    fallback_path = os.path.join(OUTPUTS_DIR, "backtest_report.json")
    fallback = _load_json(fallback_path)
    if fallback:
        for m, report in fallback.items():
            if m not in combined:
                combined[m] = report
        newest_mtime = max(newest_mtime, os.path.getmtime(fallback_path)) if os.path.exists(fallback_path) else newest_mtime

    if not combined:
        raise HTTPException(404, "No backtest data yet. Run a forecast or backtest first.")
    return {"data": combined, "generated_at": datetime.fromtimestamp(newest_mtime).isoformat() if newest_mtime else None}


@app.get("/api/data-quality/{metric}")
def data_quality(metric: str, start_year: int = DEFAULT_START_YEAR):
    """
    Raw (pre-cleaning) vs cleaned monthly series, for the training page's
    before/after preprocessing visualization. Hits the DB live.
    """
    if metric not in FETCHERS:
        raise HTTPException(404, f"Unknown metric '{metric}'")

    try:
        data = FETCHERS[metric](start_year)
    except Exception as e:
        raise HTTPException(503, f"Database unreachable: {e}")
    raw = data["raw_monthly"]
    cleaned = data["history"]

    def to_points(df):
        return [{"month": r["ds"].strftime("%Y-%m"), "label": r["ds"].strftime("%b %Y"), "value": float(r["y"])} for _, r in df.iterrows()]

    cleaned_months = set(cleaned["ds"]) if not cleaned.empty else set()
    excluded = raw[~raw["ds"].isin(cleaned_months)] if not raw.empty else raw

    return {
        "metric": metric,
        "label": METRIC_LABELS[metric],
        "raw_monthly": to_points(raw),
        "cleaned": to_points(cleaned),
        "excluded": to_points(excluded),
        "notes": data["notes"],
        "raw_count": len(raw),
        "cleaned_count": len(cleaned),
        "excluded_count": len(excluded),
    }


@app.get("/api/data-insights/{metric}")
def data_insights(metric: str, start_year: int = DEFAULT_START_YEAR):
    """
    Full exploratory-data-analysis report for the Data Explorer page:
    distribution, outliers (with z-scores, not just excluded/kept), gaps in
    the calendar, month-of-year seasonality, year-over-year growth,
    autocorrelation, and (for collections) transaction-level outlier detail.
    Hits the DB live — same fetchers the training pipeline itself uses.
    """
    if metric not in FETCHERS:
        raise HTTPException(404, f"Unknown metric '{metric}'")
    try:
        return build_insights(metric, start_year, FETCHERS[metric])
    except Exception as e:
        raise HTTPException(503, f"Database unreachable: {e}")


@app.get("/api/outputs")
def list_outputs():
    if not os.path.isdir(OUTPUTS_DIR):
        return []
    items = []
    for path in sorted(glob.glob(os.path.join(OUTPUTS_DIR, "*")), key=os.path.getmtime, reverse=True):
        name = os.path.basename(path)
        m = re.match(r"([a-z_]+)_(\d{8}_\d{4})\.(json|html)$", name)
        items.append({
            "name": name,
            "metric": m.group(1) if m else None,
            "timestamp": m.group(2) if m else None,
            "ext": name.rsplit(".", 1)[-1],
            "size": os.path.getsize(path),
            "modified": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
            "url": f"/charts/{name}" if name.endswith(".html") else None,
        })
    return items


# ── Jobs (run predict.py / validate.py from the frontend) ───────────────

class RunPredictRequest(BaseModel):
    metric: Optional[str] = None
    model: Optional[str] = None
    months: int = DEFAULT_FORECAST_MONTHS
    end_date: Optional[str] = None
    start_year: int = DEFAULT_START_YEAR
    country: str = HOLIDAY_COUNTRY


class RunValidateRequest(BaseModel):
    metric: Optional[str] = None
    start_year: int = DEFAULT_START_YEAR
    country: str = HOLIDAY_COUNTRY


@app.post("/api/jobs/predict")
def run_predict(req: RunPredictRequest):
    if req.metric and req.metric not in FETCHERS:
        raise HTTPException(400, f"Unknown metric '{req.metric}'")
    if req.model and req.model not in ALL_FORECASTERS:
        raise HTTPException(400, f"Unknown model '{req.model}'")
    job = manager.submit("predict", req.model_dump())
    return _job_public(job)


@app.post("/api/jobs/validate")
def run_validate(req: RunValidateRequest):
    if req.metric and req.metric not in FETCHERS:
        raise HTTPException(400, f"Unknown metric '{req.metric}'")
    job = manager.submit("validate", req.model_dump())
    return _job_public(job)


@app.get("/api/jobs")
def list_jobs():
    return [_job_public(j, include_logs=False) for j in manager.list()]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_public(job)


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: str, since: int = 0):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "status": job.status,
        "progress": job.progress,
        "logs": job.logs[since:],
        "next": len(job.logs),
        "error": job.error,
    }
