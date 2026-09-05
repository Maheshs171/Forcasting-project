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

import sys, os, json, glob, re, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from utils.logging_setup import install_stdio_tee, setup_logging

# Installed before any pipeline module runs, so every print() anywhere in
# the app (predict.py/validate.py/azure_automl.py print progress; data/
# fetcher.py prints DB-unreachable warnings even when called directly from
# an endpoint, not through a job) also lands in logs/backend.log —
# per-pipeline jobs additionally get their own daily log (backend/jobs.py).
logger = install_stdio_tee("backend")

from config.settings import (
    DEFAULT_START_YEAR, DEFAULT_FORECAST_MONTHS, HOLIDAY_COUNTRY,
    SQL_SERVER, SQL_DATABASE,
    AML_SUBSCRIPTION_ID, AML_RESOURCE_GROUP, AML_WORKSPACE_NAME, AML_COMPUTE_NAME,
)
from config import connections as conn_registry
from data.fetcher import FETCHERS, FETCHERS_BY_FREQUENCY
from models.forecaster import ALL_FORECASTERS
from predict import METRIC_LABELS, MONEY_METRICS
from backend.jobs import manager
from utils.eda import build_insights

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")

app = FastAPI(title="Clinical Forecasting API")

# Hardcoding the dev-server origin here (as this used to) only works when
# the frontend is served from exactly http://localhost:5173 — it silently
# breaks on every real deployment (Render, a VM behind IIS/nginx, a
# different port, https instead of http, ...), each needing its own
# origin added by hand. This app has no cookie-based auth (nothing sets
# withCredentials on the frontend's axios client), so there's no CSRF
# surface a wildcard origin would expose — allowing any origin is safe
# here and never needs touching again as deployments change.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Process-level access log — every request, its status code, and how
    long it took, into logs/backend.log (4xx/5xx also mirrored to
    logs/backend_errors.log since that handler filters on level)."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    level = logger.warning if response.status_code >= 500 else logger.info
    level(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.0f}ms)")
    return response


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception):
    """Any exception that isn't an intentional HTTPException would
    otherwise just be a stack trace on someone's terminal — this makes
    sure it's captured in logs/backend_errors.log with the full
    traceback, since that's exactly what you need later to debug an
    issue you only heard about after the fact."""
    logger.error(f"Unhandled exception on {request.method} {request.url.path}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


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
#
# Every lookup below tries the predictions DB first (see db/predictions_store.py)
# when it's configured, and falls back to the local outputs/*.json glob
# otherwise — this is what lets the same code run unchanged whether it's on
# a machine with a persistent filesystem (local dev) or a platform with an
# ephemeral one (Render), and lets local dev keep working with zero DB setup.

def _db_report(source: str, metric: str, frequency: str) -> Optional[dict]:
    try:
        from db import predictions_store
        if not predictions_store.is_configured():
            return None
        return predictions_store.load_report(source, metric, frequency)
    except Exception as e:
        logger.warning(f"predictions DB read failed for {source}/{metric}/{frequency}: {e}")
        return None


@app.get("/api/forecast/{metric}")
def latest_forecast(metric: str, frequency: str = "month"):
    if metric not in FETCHERS:
        raise HTTPException(404, f"Unknown metric '{metric}'")
    if frequency not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{frequency}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")

    data = _db_report("local", metric, frequency)
    if data is not None:
        return data

    # "month" files are "{metric}_{ts}.json" (timestamp starts with a digit);
    # "week" files are "{metric}_week_{ts}.json" — the digit-anchored glob
    # keeps a monthly lookup from matching a weekly file whose ts substring
    # happens to satisfy a bare "{metric}_*.json" wildcard, and vice versa.
    stem = f"{metric}_[0-9]*" if frequency == "month" else f"{metric}_{frequency}_*"
    path = _latest_file(f"{stem}.json")
    data = _load_json(path)
    if data is None:
        adverb = {"month": "monthly", "week": "weekly", "day": "daily"}.get(frequency, frequency)
        raise HTTPException(404, f"No {adverb} forecast output yet for '{metric}'. Run a prediction first.")
    data["_source_file"] = os.path.basename(path)
    data["_generated_at"] = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
    chart = _latest_file(f"{stem}.html")
    data["_chart_url"] = f"/charts/{os.path.basename(chart)}" if chart else None
    return data


@app.get("/api/forecast")
def all_latest_forecasts(frequency: str = "month"):
    out = {}
    for metric in FETCHERS.keys():
        try:
            out[metric] = latest_forecast(metric, frequency=frequency)
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
def backtest_report(frequency: str = "month"):
    """
    Built from each metric's latest forecast file (predict.py already backtests
    every candidate and stores it there) rather than the standalone
    outputs/backtest_report.json, which is only written by validate.py and
    would otherwise go stale as soon as someone runs a forecast without also
    running a separate backtest. Falls back to that file for any metric with
    no forecast yet.
    """
    if frequency not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{frequency}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")
    stem_for = lambda m: f"{m}_[0-9]*" if frequency == "month" else f"{m}_{frequency}_*"
    combined = {}
    newest_mtime = 0.0
    for m in FETCHERS.keys():
        data = _db_report("local", m, frequency)
        path = None
        if data is None:
            path = _latest_file(f"{stem_for(m)}.json")
            data = _load_json(path)
        if data and "backtest" in data:
            combined[m] = {"candidates": data["backtest"], "best_model": data.get("best_model", data.get("model_used"))}
            newest_mtime = max(newest_mtime, os.path.getmtime(path) if path else time.time())

    fallback_path = os.path.join(OUTPUTS_DIR, "backtest_report.json" if frequency == "month" else f"backtest_report_{frequency}.json")
    fallback = _load_json(fallback_path)
    if fallback:
        for m, report in fallback.items():
            if m not in combined:
                combined[m] = report
        newest_mtime = max(newest_mtime, os.path.getmtime(fallback_path)) if os.path.exists(fallback_path) else newest_mtime

    if not combined:
        raise HTTPException(404, "No backtest data yet. Run a forecast or backtest first.")
    return {"data": combined, "generated_at": datetime.fromtimestamp(newest_mtime).isoformat() if newest_mtime else None}


@app.get("/api/azure/status")
def azure_status():
    """
    Whether Azure ML is configured (.env has the workspace settings) —
    lets the frontend disable/explain the "Train on Azure" button instead
    of letting the job fail on submit. Does not open a network connection
    (that only happens once a training job actually runs), so this is
    always fast.
    """
    missing = [
        name for name, val in [
            ("AML_SUBSCRIPTION_ID", AML_SUBSCRIPTION_ID),
            ("AML_RESOURCE_GROUP", AML_RESOURCE_GROUP),
            ("AML_WORKSPACE_NAME", AML_WORKSPACE_NAME),
        ] if not val
    ]
    return {
        "configured": not missing,
        "missing": missing,
        "workspace_name": AML_WORKSPACE_NAME,
        "resource_group": AML_RESOURCE_GROUP,
        "compute_name": AML_COMPUTE_NAME,
    }


@app.get("/api/azure/latest")
def azure_automl_latest(frequency: str = "month"):
    """
    Latest Azure AutoML comparison report (written by azure_automl.py to
    outputs/azure_automl[_<freq>]_<timestamp>.json — one leaderboard per
    metric, every algorithm Azure tried, ranked by normalized RMSE).
    Enriches each metric with the locally-backtested winner at the SAME
    frequency (from that metric's latest predict.py output) so the
    frontend can render local-vs-Azure side by side without a second
    round trip.
    """
    if frequency not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{frequency}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")

    generated_at = None
    try:
        from db import predictions_store
        data = predictions_store.load_all_reports("azure", frequency) if predictions_store.is_configured() else {}
        if data:
            generated_at = predictions_store.latest_generated_at("azure", frequency)
    except Exception as e:
        logger.warning(f"predictions DB read failed for azure/{frequency}: {e}")
        data = {}

    path = None
    if not data:
        stem = "azure_automl_[0-9]*" if frequency == "month" else f"azure_automl_{frequency}_*"
        path = _latest_file(f"{stem}.json")
        data = _load_json(path)
    if not data:
        adverb = {"month": "monthly", "week": "weekly", "day": "daily"}.get(frequency, frequency)
        raise HTTPException(404, f"No {adverb} Azure AutoML report yet. Run azure_automl.py first.")
    if generated_at is None and path:
        generated_at = datetime.fromtimestamp(os.path.getmtime(path)).isoformat()

    local_stem = lambda m: f"{m}_[0-9]*" if frequency == "month" else f"{m}_{frequency}_*"
    enriched = {}
    for metric, result in data.items():
        local = _db_report("local", metric, frequency)
        if local is None:
            local_path = _latest_file(f"{local_stem(metric)}.json")
            local = _load_json(local_path)
        local_model = local.get("model_used") if local else None
        local_accuracy = local.get("models", {}).get(local_model, {}).get("accuracy_pct") if local else None

        leaderboard = result.get("leaderboard", [])
        best = leaderboard[0] if leaderboard else None

        enriched[metric] = {
            "metric": metric,
            "label": METRIC_LABELS.get(metric, metric),
            "frequency": result.get("frequency", frequency),
            "job_name": result.get("job_name"),
            "status": result.get("status"),
            "studio_url": result.get("studio_url"),
            "leaderboard": leaderboard,
            "best_azure": best,
            "local_model": local_model,
            "local_accuracy_pct": local_accuracy,
            # Full this-month/next-month/by-end-of-year/YTD forecast generated
            # from Azure's winning model (azure_automl.py's build_forecast_detail)
            # — same MetricForecast shape the local dashboard uses, so the
            # frontend can render it with the same chart components. Absent on
            # older report files, or if that model couldn't be loaded for
            # inference (e.g. azureml-training-tabular isn't installed).
            "forecast_detail": result.get("forecast_detail"),
            # Top N trials downloaded to local disk (azure_automl.py's
            # download_top_models) — each with its local filesystem path.
            # Empty on older report files, or if downloads failed.
            "downloaded_models": result.get("downloaded_models", []),
        }

    return {"data": enriched, "generated_at": generated_at}


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
        logger.error(f"DB unreachable for metric '{metric}': {e}", exc_info=True)
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
def data_insights(metric: str, start_year: int = DEFAULT_START_YEAR, frequency: str = "month"):
    """
    Full exploratory-data-analysis report for the Data Explorer page:
    distribution, outliers (with z-scores, not just excluded/kept), gaps in
    the calendar, seasonality, year-over-year growth, autocorrelation, and
    (for collections) transaction-level outlier detail. Hits the DB live —
    same fetchers the training pipeline itself uses.

    frequency: "month" (default), "week", or "day" — lets the same data be
    compared at either grain, so you can see which one actually suits the
    business better before committing to it for forecasting.
    """
    if frequency not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{frequency}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")
    fetchers = FETCHERS_BY_FREQUENCY[frequency]
    if metric not in fetchers:
        raise HTTPException(404, f"Unknown metric '{metric}'")
    try:
        return build_insights(metric, start_year, fetchers[metric], freq=frequency)
    except Exception as e:
        logger.error(f"DB unreachable for metric '{metric}': {e}", exc_info=True)
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
    freq: str = "month"
    months: int = DEFAULT_FORECAST_MONTHS
    end_date: Optional[str] = None
    history_end_date: Optional[str] = None
    start_year: int = DEFAULT_START_YEAR
    country: str = HOLIDAY_COUNTRY


class RunValidateRequest(BaseModel):
    metric: Optional[str] = None
    freq: str = "month"
    start_year: int = DEFAULT_START_YEAR
    country: str = HOLIDAY_COUNTRY


class RunAzureTrainRequest(BaseModel):
    metric: Optional[str] = None  # "all" (default), a single metric key, or a comma-separated list
    freq: str = "month"
    start_year: int = DEFAULT_START_YEAR
    horizon: int = DEFAULT_FORECAST_MONTHS
    max_trials: int = 25
    max_concurrent_trials: int = 1
    timeout_minutes: int = 90
    trial_timeout_minutes: int = 20


@app.post("/api/jobs/predict")
def run_predict(req: RunPredictRequest):
    if req.metric and req.metric not in FETCHERS:
        raise HTTPException(400, f"Unknown metric '{req.metric}'")
    if req.model and req.model not in ALL_FORECASTERS:
        raise HTTPException(400, f"Unknown model '{req.model}'")
    if req.freq not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{req.freq}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")
    job = manager.submit("predict", req.model_dump())
    return _job_public(job)


@app.post("/api/jobs/validate")
def run_validate(req: RunValidateRequest):
    if req.metric and req.metric not in FETCHERS:
        raise HTTPException(400, f"Unknown metric '{req.metric}'")
    if req.freq not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{req.freq}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")
    job = manager.submit("validate", req.model_dump())
    return _job_public(job)


class RunAzureFromDownloadsRequest(BaseModel):
    metric: Optional[str] = None  # "all" (default), a single metric key, or a comma-separated list
    freq: str = "month"
    start_year: int = DEFAULT_START_YEAR
    horizon: int = DEFAULT_FORECAST_MONTHS


@app.post("/api/jobs/azure-forecast-from-downloads")
def run_azure_forecast_from_downloads(req: RunAzureFromDownloadsRequest):
    """
    Regenerates the Azure forecast report purely from ALREADY-DOWNLOADED
    local model artifacts (models/azure_downloads/ + a previous training
    run's saved leaderboard in outputs/) — no Azure connection, no
    credentials, no new training job. This is what lets someone who was
    handed a copy of models/azure_downloads/ + outputs/ + data/cache/
    (e.g. a teammate without Azure access) regenerate the dashboard from
    already fine-tuned models on their own machine, typically in seconds
    rather than the 20-90+ minutes a real training run takes.
    """
    if req.freq not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{req.freq}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")
    metric_arg = req.metric or "all"
    if metric_arg != "all":
        unknown = [m.strip() for m in metric_arg.split(",") if m.strip() not in FETCHERS]
        if unknown:
            raise HTTPException(400, f"Unknown metric(s): {unknown}. Valid: {list(FETCHERS.keys())}")
    job = manager.submit("azure_forecast_from_downloads", req.model_dump())
    return _job_public(job)


@app.post("/api/jobs/azure-train")
def run_azure_train(req: RunAzureTrainRequest):
    """
    Kicks off the full Azure AutoML pipeline as a background job: fetch
    each requested metric's cleaned history from the DB (reusing the exact
    same fetchers/outlier-filtering as the local pipeline), upload it as
    an MLTable, auto-start the configured compute if it's stopped, submit
    an AutoML forecasting job per metric, wait for training, and pull back
    the full leaderboard — same flow as `python azure_automl.py`, just
    triggered from the dashboard with live progress/logs instead of a
    terminal. Long-running (each metric can take 20-90+ minutes), so this
    only returns the job handle; poll /api/jobs/{id} for progress and
    GET /api/azure/latest once it completes.
    """
    missing = [
        name for name, val in [
            ("AML_SUBSCRIPTION_ID", AML_SUBSCRIPTION_ID),
            ("AML_RESOURCE_GROUP", AML_RESOURCE_GROUP),
            ("AML_WORKSPACE_NAME", AML_WORKSPACE_NAME),
        ] if not val
    ]
    if missing:
        raise HTTPException(400, f"Azure ML is not configured in .env — missing: {missing}")
    if req.freq not in FETCHERS_BY_FREQUENCY:
        raise HTTPException(400, f"Unknown frequency '{req.freq}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")
    metric_arg = req.metric or "all"
    if metric_arg != "all":
        unknown = [m.strip() for m in metric_arg.split(",") if m.strip() not in FETCHERS]
        if unknown:
            raise HTTPException(400, f"Unknown metric(s): {unknown}. Valid: {list(FETCHERS.keys())}")
    job = manager.submit("azure_train", req.model_dump())
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


# ── Serve the built frontend (production only) ──────────────────────────
#
# Local dev runs two servers (Vite on 5173 proxying /api to this one on
# 8000 — see frontend/vite.config.ts); a single Render web service needs
# one process serving both, so this mounts frontend/dist's built assets
# and falls back to index.html for any route React Router owns client-side
# (e.g. /forecast/patients). Registered LAST so it never shadows an /api
# or /charts route above — FastAPI matches routes in registration order,
# and this is a catch-all. A no-op locally: frontend/dist only exists
# after `npm run build`, which local dev never runs.
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_FRONTEND_DIST, "assets")), name="frontend-assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        candidate = os.path.join(_FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))
