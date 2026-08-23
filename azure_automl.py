"""
azure_automl.py
────────────────
Pushes this project's already-cleaned history at the requested grain —
monthly (default), weekly, or daily, the exact same (ds, y) series your
local models train on — future-dated rows filtered, migration/outlier
periods already excluded via utils/outliers.py) to an Azure Machine
Learning workspace and runs an AutoML *forecasting* job against it, so
Azure's algorithm search can be compared side-by-side with this
project's own backtested pick, at whichever frequency you're training.

What this does NOT do: it does not replace the local pipeline, does not
touch the SQL database directly (it reuses data/fetcher.py, which already
did that), and does not send any patient-identifying data — only the
(date, value) series, same as everything else in this project.

Usage:
    python azure_automl.py --metric encounters --horizon 12
    python azure_automl.py --metric all --horizon 12
    python azure_automl.py --metric patients --freq week --horizon 8

Also auto-starts AML_COMPUTE_NAME if it's a stopped Compute Instance (a
single-VM dev box, e.g. "dhirajt1") — no need to click Start in the portal
first. Defaults assume that single-node case (max_concurrent_trials=1); if
AML_COMPUTE_NAME instead points at a multi-node Compute Cluster, raise
--max-concurrent-trials to run several trials in parallel.

Requires (see README section "Azure AutoML setup" for the one-time Azure
setup steps):
    pip install azure-ai-ml azure-identity mltable mlflow
    .env filled in with AML_SUBSCRIPTION_ID / AML_RESOURCE_GROUP /
    AML_WORKSPACE_NAME / AML_COMPUTE_NAME
"""

import argparse
import glob
import json
import os
import re
import sys
import tempfile
from datetime import datetime

# Windows terminals often default stdout to cp1252, which can't encode some
# characters the Azure SDK prints (or that we print). Force UTF-8 so nothing
# crashes mid-run over a display character.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from config.settings import (
    AML_SUBSCRIPTION_ID, AML_RESOURCE_GROUP, AML_WORKSPACE_NAME, AML_COMPUTE_NAME,
    DEFAULT_START_YEAR, DEFAULT_FORECAST_MONTHS,
)
from data.fetcher import FETCHERS, FETCHERS_BY_FREQUENCY
from predict import METRIC_LABELS
from models.forecaster import _freq_params

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")


def _require_azure_config():
    missing = [
        name for name, val in [
            ("AML_SUBSCRIPTION_ID", AML_SUBSCRIPTION_ID),
            ("AML_RESOURCE_GROUP", AML_RESOURCE_GROUP),
            ("AML_WORKSPACE_NAME", AML_WORKSPACE_NAME),
        ] if not val
    ]
    if missing:
        raise SystemExit(
            f"Missing Azure ML settings in .env: {missing}\n"
            f"See README's 'Azure AutoML setup' section for how to get these values."
        )


def get_ml_client():
    """Connects to the Azure ML workspace using whatever credential is
    available in the environment (az CLI login, managed identity, or a
    service principal via env vars) — never hardcodes a secret here."""
    from azure.ai.ml import MLClient
    from azure.identity import DefaultAzureCredential

    _require_azure_config()
    credential = DefaultAzureCredential()
    return MLClient(
        credential=credential,
        subscription_id=AML_SUBSCRIPTION_ID,
        resource_group_name=AML_RESOURCE_GROUP,
        workspace_name=AML_WORKSPACE_NAME,
    )


def ensure_compute_running(ml_client) -> None:
    """
    Starts the configured compute target if it's a stopped Compute Instance
    (a Compute Cluster is always "available", it just scales nodes up on
    demand, so this only matters for the single-VM instance case). Blocks
    until it's running so the job submission right after doesn't fail.
    """
    try:
        target = ml_client.compute.get(AML_COMPUTE_NAME)
    except Exception as e:
        raise SystemExit(
            f"Could not find compute target '{AML_COMPUTE_NAME}' in this workspace: {e}\n"
            f"Check AML_COMPUTE_NAME in .env matches a Compute Instance or Compute Cluster "
            f"name shown in Azure ML Studio -> Compute."
        )

    state = getattr(target, "state", None)  # Compute Clusters don't expose .state the same way
    if state and state.lower() == "stopped":
        print(f"  Compute instance '{AML_COMPUTE_NAME}' is stopped — starting it now "
              f"(this can take 2-4 minutes)...")
        ml_client.compute.begin_start(AML_COMPUTE_NAME).result()
        print(f"  '{AML_COMPUTE_NAME}' is now running.")
    elif state:
        print(f"  Compute '{AML_COMPUTE_NAME}' is already {state.lower()}.")


def build_mltable_dir(df: pd.DataFrame, metric: str) -> str:
    """
    AutoML forecasting jobs require an MLTable input (not a bare CSV) so
    Azure knows the schema. Writes the cleaned series + an MLTable
    definition into a temp directory and returns its path.
    """
    import mltable

    out_dir = tempfile.mkdtemp(prefix=f"aml_{metric}_")
    csv_path = os.path.join(out_dir, "data.csv")

    export = df[["ds", "y"]].copy()
    export["ds"] = pd.to_datetime(export["ds"]).dt.strftime("%Y-%m-%d")
    export.to_csv(csv_path, index=False)

    table = mltable.from_delimited_files(paths=[{"file": csv_path}])
    table = table.convert_column_types({"ds": mltable.DataType.to_datetime("%Y-%m-%d")})
    table.save(out_dir)
    return out_dir


def submit_automl_job(metric: str, df: pd.DataFrame, horizon: int, ml_client, limits: dict, freq: str = "month") -> str:
    """Builds and submits the AutoML forecasting job; returns the job name."""
    from azure.ai.ml import automl, Input
    from azure.ai.ml.constants import AssetTypes

    mltable_dir = build_mltable_dir(df, metric)
    training_data = Input(type=AssetTypes.MLTABLE, path=mltable_dir)

    job = automl.forecasting(
        compute=AML_COMPUTE_NAME,
        experiment_name=f"forecast-{metric}",
        training_data=training_data,
        target_column_name="y",
        primary_metric="normalized_root_mean_squared_error",
        n_cross_validations=5,
        enable_model_explainability=True,
    )
    job.set_forecast_settings(
        time_column_name="ds",
        forecast_horizon=horizon,
        frequency=_freq_params(freq)["pandas_freq"],  # "MS"/"W-MON"/"D" — matches this project's series grain
        target_lags="auto",
        target_rolling_window_size="auto",
    )
    job.set_training(
        blocked_training_algorithms=None,  # let Azure try everything applicable
        enable_onnx_compatible_models=False,
    )
    job.set_limits(
        timeout_minutes=limits["timeout_minutes"],
        trial_timeout_minutes=limits["trial_timeout_minutes"],
        max_trials=limits["max_trials"],
        max_concurrent_trials=limits["max_concurrent_trials"],
        enable_early_termination=True,
    )

    returned_job = ml_client.jobs.create_or_update(job)
    print(f"  Submitted job '{returned_job.name}' for {metric} — "
          f"track live at: {returned_job.studio_url}")
    return returned_job.name


def wait_and_report(ml_client, job_name: str, metric: str, data: dict = None, horizon: int = DEFAULT_FORECAST_MONTHS, freq: str = "month") -> dict:
    """Streams the job to completion, then pulls the leaderboard (every
    trial Azure tried, ranked by score) so you can see ALL algorithms it
    compared, not just the winner. If `data` (the fetcher dict used to
    train) is given, also loads the winning trial as a real model and
    generates an actual future forecast — same this-month/next-month/
    by-end-of-year/YTD-growth breakdown as the local dashboard, just from
    Azure's model instead of the local pipeline's."""
    print(f"  Waiting for '{job_name}' to finish (this can take 20-90+ minutes)...")
    ml_client.jobs.stream(job_name)

    job = ml_client.jobs.get(job_name)
    print(f"  Status: {job.status}")

    leaderboard = []
    try:
        from mlflow.tracking import MlflowClient
        import mlflow

        mlflow.set_tracking_uri(ml_client.workspaces.get(ml_client.workspace_name).mlflow_tracking_uri)
        mlflow_client = MlflowClient()
        parent_run = mlflow_client.get_run(job_name)
        experiment_id = parent_run.info.experiment_id

        # AutoML stores each trial's algorithm NAME only on the parent run's
        # tags, packed as a semicolon-separated list keyed by iteration index
        # (child runs themselves don't carry a "run_algorithm" tag) — e.g.
        # tags["run_algorithm_000"] = "Naive;SeasonalNaive;...;VotingEnsemble"
        # and each child run's run_id ends in "_<iteration>" (e.g. "..._0",
        # "..._24"), which indexes into that list. The "_setup" child has no
        # numeric suffix and isn't a real trial, so it's skipped below.
        algo_tag_key = next(
            (k for k in parent_run.data.tags if k.startswith("run_algorithm_")), None
        )
        algorithms_by_iteration = (
            parent_run.data.tags[algo_tag_key].split(";") if algo_tag_key else []
        )

        # Querying with filter_string="tags.mlflow.parentRunId = '...'" is unreliable against
        # the AzureML MLflow plugin (silently returns 0 rows on some calls) — listing every run
        # in the experiment and filtering client-side by run_id prefix (child runs are always
        # named "{job_name}_<iteration>") is what actually works consistently.
        # The AzureML plugin caps each page at ~100 runs regardless of max_results, so an
        # experiment with more accumulated jobs than that (this project reuses one experiment
        # per metric, "forecast-<metric>", across every run ever submitted) silently loses older
        # OR — since search order isn't guaranteed to be newest-first — even the CURRENT job's own
        # trials off page one. Paginating through every page via page_token is required, not
        # optional, once an experiment has run more than one page's worth of jobs.
        all_runs = []
        page_token = None
        while True:
            page = mlflow_client.search_runs(experiment_ids=[experiment_id], max_results=1000, page_token=page_token)
            all_runs.extend(page)
            page_token = page.token
            if not page_token:
                break
        children = [r for r in all_runs if r.info.run_id.startswith(f"{job_name}_")]
        for run in children:
            suffix = run.info.run_id.rsplit("_", 1)[-1]
            if not suffix.isdigit():
                continue  # skips the "_setup" bookkeeping child, not a real trial
            iteration = int(suffix)
            algorithm = (
                algorithms_by_iteration[iteration]
                if 0 <= iteration < len(algorithms_by_iteration)
                else run.info.run_name
            )
            rmse = run.data.metrics.get("normalized_root_mean_squared_error")
            if rmse is None:
                continue  # trial didn't produce a scored result (e.g. errored/pruned)
            mape = run.data.metrics.get("mean_absolute_percentage_error")
            leaderboard.append({
                "algorithm": algorithm,
                "iteration": iteration,
                "normalized_rmse": rmse,
                "r2_score": run.data.metrics.get("r2_score"),
                "mape": mape,
                # Same "100 - error%" framing as this project's own accuracy_pct, so the two
                # numbers are directly comparable at a glance (still not a perfectly identical
                # formula — see compare_with_local()'s printed caveat).
                "accuracy_pct_equivalent": max(0.0, 100.0 - mape) if mape is not None else None,
                "run_id": run.info.run_id,
            })
        leaderboard.sort(key=lambda r: r["normalized_rmse"])
    except Exception as e:
        print(f"  (Could not pull the full leaderboard via MLflow: {e})")

    downloaded_models = []
    if leaderboard:
        try:
            downloaded_models = download_top_models(ml_client, leaderboard, metric, job_name)
        except Exception as e:
            print(f"  (Could not download models locally: {e})")

    # Forecast detail is built from the LOCAL copies just downloaded above,
    # not a live Azure connection — see build_forecast_detail's docstring
    # for why (keeps this step working even without azureml-training-tabular
    # installed in this process, via a subprocess in an isolated venv).
    forecast_detail = None
    if downloaded_models and data is not None:
        try:
            forecast_detail = build_forecast_detail(leaderboard, downloaded_models, metric, data, horizon, freq=freq)
        except Exception as e:
            print(f"  (Could not generate a future forecast from Azure's models: {e})")

    result = {
        "metric": metric, "job_name": job_name, "status": job.status,
        "studio_url": getattr(job, "studio_url", None),
        "frequency": freq,
        "leaderboard": leaderboard,
        "forecast_detail": forecast_detail,
        "downloaded_models": downloaded_models,
    }
    return result


MODEL_DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "models", "azure_downloads")
TOP_N_MODELS_TO_DOWNLOAD = 7


def download_top_models(ml_client, leaderboard: list, metric: str, job_name: str, top_n: int = TOP_N_MODELS_TO_DOWNLOAD) -> list:
    """
    Downloads the top N trials' (by normalized RMSE — the leaderboard is
    already sorted that way) full MLflow model directories (MLmodel,
    conda.yaml/requirements, the actual serialized model) to
    models/azure_downloads/<metric>_<job_name>/rank01_<algorithm>/ etc —
    so they're all on disk for later use (reloading offline via
    mlflow.sklearn.load_model(path), inspecting, comparing, or archiving)
    without needing to reconnect to Azure or keep the run around.
    Best-effort per model: one failing download (e.g. a trial whose
    artifacts expired or errored) doesn't stop the rest from downloading.
    Overwrites if that metric/job was already downloaded before
    (re-running training regenerates the folder).
    """
    import re
    import shutil
    import mlflow

    mlflow.set_tracking_uri(ml_client.workspaces.get(ml_client.workspace_name).mlflow_tracking_uri)

    job_dir = os.path.join(MODEL_DOWNLOAD_DIR, f"{metric}_{job_name}")
    if os.path.isdir(job_dir):
        shutil.rmtree(job_dir)
    os.makedirs(job_dir, exist_ok=True)

    downloaded = []
    for rank, entry in enumerate(leaderboard[:top_n], start=1):
        safe_algo = re.sub(r"[^A-Za-z0-9_-]", "", entry["algorithm"])
        dest = os.path.join(job_dir, f"rank{rank:02d}_{safe_algo}")
        try:
            downloaded_path = mlflow.artifacts.download_artifacts(
                artifact_uri=f"runs:/{entry['run_id']}/outputs/mlflow-model", dst_path=job_dir,
            )
            if os.path.abspath(downloaded_path) != os.path.abspath(dest):
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                shutil.move(downloaded_path, dest)
            print(f"  [{rank}/{min(top_n, len(leaderboard))}] {entry['algorithm']} downloaded to {dest}")
            downloaded.append({
                "rank": rank, "algorithm": entry["algorithm"], "run_id": entry["run_id"],
                "normalized_rmse": entry["normalized_rmse"], "local_path": dest,
            })
        except Exception as e:
            print(f"  [{rank}/{min(top_n, len(leaderboard))}] {entry['algorithm']}: download failed ({e})")

    return downloaded


TOP_N_MODELS_FOR_DETAIL = 5


def _slugify_algorithm(name: str, used: set) -> str:
    """Turns an Azure algorithm name (e.g. "VotingEnsemble") into a stable,
    unique dict key (e.g. "voting_ensemble") — unique because the same
    algorithm can appear more than once in a leaderboard with different
    hyperparameters, and dict keys double as the "model_key" used for
    color-coding and selection in the frontend."""
    import re
    # Standard acronym-aware camelCase -> snake_case (avoids splitting runs of
    # capitals like "XGBoost" into "x_g_boost") — split before a capital that
    # starts a new word (preceded by lowercase/digit, or itself followed by
    # a lowercase letter after a run of capitals).
    base = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    base = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", base).lower()
    base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_") or "model"
    key = base
    i = 2
    while key in used:
        key = f"{base}_{i}"
        i += 1
    used.add(key)
    return key


VENV_AZURE_PYTHON = os.path.join(os.path.dirname(__file__), "venv_azure", "Scripts", "python.exe")
MODEL_INFER_SCRIPT = os.path.join(os.path.dirname(__file__), "azure_model_infer.py")


def _infer_future_values(local_model_path: str, last_ds: pd.Timestamp, horizon: int, pandas_freq: str) -> "list[float]":
    """Runs azure_model_infer.py in the isolated venv_azure/ virtual
    environment (which has azureml-training-tabular and its pinned old
    numpy/scikit-learn/scipy installed) as a subprocess, so this
    process's own numpy/scikit-learn versions — whatever the local
    Prophet/XGBoost pipeline needs — never have to match what Azure's
    pickled model objects were built with. Raises if venv_azure/ hasn't
    been set up yet, or if the subprocess itself fails (unpicklable
    model, missing dependency for that specific algorithm, etc.)."""
    import subprocess

    if not os.path.exists(VENV_AZURE_PYTHON):
        raise RuntimeError(
            f"venv_azure/ isn't set up (expected {VENV_AZURE_PYTHON}) — see README's "
            f"'Azure AutoML setup' section for how to create the isolated inference environment."
        )

    proc = subprocess.run(
        [VENV_AZURE_PYTHON, MODEL_INFER_SCRIPT, local_model_path, last_ds.strftime("%Y-%m-%d"), str(horizon), pandas_freq],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # azureml's own Win32Helper.__del__ prints a harmless "Exception ignored
        # in..." line to stderr on interpreter shutdown regardless of the real
        # failure, so pick out our own "ERROR: ..." line rather than assuming
        # the actual error is last.
        error_lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("ERROR:")]
        raise RuntimeError(error_lines[-1] if error_lines else (proc.stderr.strip() or "inference subprocess failed"))
    return json.loads(proc.stdout)


def _forecast_one_azure_model(local_model_path: str, entry: dict, metric: str, history: pd.DataFrame,
                               pacing: dict, now, year_start, end_of_year, current_period_start,
                               horizon: int, freq: str = "month") -> dict:
    """Generates real future predictions from one downloaded Azure AutoML
    trial (via the isolated venv_azure/ subprocess) and runs them through
    predict.py's own _derive_stats — the exact same per-model stats block
    the local pipeline computes for every one of its candidates — so this
    trial's entry is structurally identical to a local ModelForecast."""
    import numpy as np
    from models.forecaster import ForecastResult, _step
    from predict import _derive_stats

    fp = _freq_params(freq)
    last_ds = history["ds"].max()
    future_dates = pd.date_range(start=last_ds + _step(fp, 1), periods=horizon, freq=fp["pandas_freq"])
    y_pred = np.asarray(_infer_future_values(local_model_path, last_ds, horizon, fp["pandas_freq"]), dtype=float)

    # AutoML wasn't configured with quantile forecasting (set_forecast_settings
    # didn't request it — see submit_automl_job), so there's no fitted
    # prediction interval to use here. ±15% mirrors the same approximation
    # this project's own pacing fallback uses elsewhere (predict.py) when a
    # model doesn't provide one — clearly an approximation, not a
    # statistically fitted interval, and labeled as such in the UI.
    future = pd.DataFrame({
        "ds": future_dates, "yhat": y_pred,
        "yhat_lower": y_pred * 0.85, "yhat_upper": y_pred * 1.15,
    })
    result = ForecastResult(model_name=entry["algorithm"], metric=metric, historical=history, future=future)
    stats = _derive_stats(result, history, pacing, now, year_start, end_of_year, current_period_start, freq=freq)

    return {
        "model_name": entry["algorithm"],
        "is_flat": False,
        "accuracy_pct": entry.get("accuracy_pct_equivalent"),
        "near_term_mape": entry.get("mape"),
        "long_term_mape": entry.get("mape"),
        **stats,
    }


def build_forecast_detail(leaderboard: list, downloaded_models: list, metric: str, data: dict, horizon: int,
                           top_n: int = TOP_N_MODELS_FOR_DETAIL, freq: str = "month") -> dict:
    """
    Generates real future predictions for the top N trials Azure AutoML
    tried (ranked by normalized RMSE, same order as the leaderboard) from
    their already-downloaded local copies (see download_top_models —
    this must run after that, not before), so the result is a full
    MetricForecast-shaped summary with a genuine multi-model comparison:
    `models` has one entry per successfully-loaded trial (same shape as
    the local pipeline's per-model entries) and `backtest` is synthesized
    from every leaderboard row's MAPE/accuracy so the "Model Accuracy
    Comparison" donut and backtest table work unmodified. This is what
    lets the Azure Ops tab render the same rich dashboard — model cards,
    side-by-side table, accuracy donut, backtest table — as a local
    forecast, just sourced from Azure's own algorithm search.

    Each trial's model is loaded and run in a SEPARATE process, using the
    isolated venv_azure/ virtual environment (see _infer_future_values) —
    azureml-training-tabular needs old, narrow-pinned numpy/scikit-learn/
    scipy versions to unpickle Azure's model objects, incompatible with
    the newer versions this project's own Prophet/XGBoost pipeline needs
    in this process. A failure loading one trial (missing local download,
    an algorithm azureml-training-tabular can't unpickle in this venv,
    etc.) is skipped rather than aborting the rest — if every trial fails,
    this raises and the caller just logs a warning; the leaderboard
    itself is unaffected either way.
    """
    from predict import _current_period_start

    history = data["history"]
    current_month_row = data["current_month"]
    notes = data.get("notes", [])

    downloaded_by_run_id = {m["run_id"]: m for m in downloaded_models}

    now = pd.Timestamp.now()
    year_start = pd.Timestamp(year=now.year, month=1, day=1)
    end_of_year = pd.Timestamp(year=now.year, month=12, day=31)
    current_period_start = _current_period_start(now, freq)

    # ── Current-period pacing — identical approach to predict.py's own
    # fallback path (elapsed-fraction, per-frequency), shared across every
    # model, using the same current_month row the local pipeline would've
    # used ─────────────────────────────────────────────────────────────
    mtd_actual = float(current_month_row["y"].iloc[0]) if not current_month_row.empty else 0.0
    if freq == "day":
        frac = max((now.hour + 1) / 24, 0.05)
    elif freq == "week":
        frac = max((now.dayofweek + 1) / 7, 0.05)
    else:
        days_in_month = pd.Period(current_period_start, freq="M").days_in_month
        frac = max(now.day / days_in_month, 0.05)
    projected = mtd_actual / frac
    pacing = {
        "mtd_actual": mtd_actual, "projected": projected,
        "low": projected * 0.85, "high": projected * 1.15,
        "fraction_elapsed": frac, "as_of_day": now.day, "history_months_used": 0,
    }

    # Walk the FULL leaderboard (not just its first top_n rows) so a run of
    # early failures — e.g. every Prophet-based trial in the top 5 hitting
    # the same cmdstanpy incompatibility — doesn't starve the report down to
    # 1-2 models when perfectly loadable candidates exist further down
    # (still bounded to however many were actually downloaded locally, see
    # download_top_models / TOP_N_MODELS_TO_DOWNLOAD). Stops once `top_n`
    # models have actually loaded successfully, not merely been attempted.
    used_keys: set = set()
    models_out = {}
    for entry in leaderboard:
        if len(models_out) >= top_n:
            break
        downloaded = downloaded_by_run_id.get(entry["run_id"])
        if downloaded is None:
            continue
        key = _slugify_algorithm(entry["algorithm"], used_keys)
        try:
            model_entry = _forecast_one_azure_model(
                downloaded["local_path"], entry, metric, history, pacing, now, year_start, end_of_year, current_period_start, horizon, freq=freq,
            )
            model_entry["model_key"] = key
            models_out[key] = model_entry
        except Exception as e:
            print(f"  (Skipping '{entry['algorithm']}' — could not load/forecast: {e})")

    if not models_out:
        raise RuntimeError("None of the top Azure trials could be loaded as models")

    # Rank order (leaderboard is already sorted by RMSE) determines which
    # successfully-loaded model is "recommended" — mirrors predict.py's
    # own best-of-scoreable-candidates selection.
    best_key = next(iter(models_out))
    for key, m in models_out.items():
        m["is_recommended"] = key == best_key
    recommended = models_out[best_key]

    # Synthesize a backtest-shaped dict from EVERY leaderboard row (not just
    # the ones that loaded successfully) so the accuracy donut and backtest
    # table reflect Azure's full algorithm search, same as predict.py's
    # `summary["backtest"]` reflects every backtested local candidate.
    # Azure's MLflow leaderboard only reports one overall MAPE per trial
    # (no near-term/long-term split like this project's own backtest), so
    # both fields fall back to that same overall number — an approximation,
    # not a granular per-horizon-step breakdown.
    backtest_used_keys: set = set()
    backtest = {}
    for entry in leaderboard:
        key = _slugify_algorithm(entry["algorithm"], backtest_used_keys)
        mape = entry.get("mape")
        backtest[key] = {
            "accuracy_pct": entry.get("accuracy_pct_equivalent"),
            "weighted_score": mape if mape and mape > 0 else None,
            "near_term_mape": mape,
            "long_term_mape": mape,
        }

    # Same per-frequency labeling/bucketing predict.py uses for these two
    # fields (see predict.py's run_metric) — kept identical so the frontend's
    # existing frequency-aware rendering works unmodified for Azure reports.
    trailing_window = 180 if freq == "day" else (104 if freq == "week" else 24)
    label_fmt = "%b %d, %Y" if freq in ("week", "day") else "%b %Y"
    period_fmt = "%Y-%m-%d" if freq in ("week", "day") else "%Y-%m"
    history_full = [
        {"month": r["ds"].strftime(period_fmt), "label": r["ds"].strftime(label_fmt), "value": float(r["y"])}
        for _, r in history.tail(trailing_window).iterrows()
    ]
    if freq == "week":
        yoy_history = [
            {"year": int(r["ds"].isocalendar()[0]), "month": int(r["ds"].isocalendar()[1]), "value": float(r["y"])}
            for _, r in history.iterrows()
        ]
    elif freq == "day":
        yoy_history = [
            {"year": int(r["ds"].year), "month": int(r["ds"].dayofyear), "value": float(r["y"])}
            for _, r in history.iterrows()
        ]
    else:
        yoy_history = [
            {"year": int(r["ds"].year), "month": int(r["ds"].month), "value": float(r["y"])}
            for _, r in history.iterrows()
        ]

    return {
        "metric": metric,
        "label": METRIC_LABELS.get(metric, metric),
        "frequency": freq,
        "model_used": best_key,
        "best_model": best_key,
        "history_months": len(history),
        "horizon_months": horizon,
        "data_quality_notes": notes,
        "history_full": history_full,
        "yoy_history": yoy_history,
        "this_month": {
            "month": current_period_start.strftime(period_fmt),
            "month_to_date_actual": pacing["mtd_actual"],
            "projected_total": pacing["projected"],
            "low": pacing["low"], "high": pacing["high"],
            "as_of_day": pacing["as_of_day"],
            "history_months_used": 0,
        },
        "models": models_out,
        "next_month": recommended["next_month"],
        "by_end_of_year": recommended["by_end_of_year"],
        "next_12_months": recommended["next_12_months"],
        "growth": recommended["growth"],
        "full_forecast": recommended["full_forecast"],
        "backtest": backtest,
    }


def compare_with_local(metric: str, azure_result: dict, freq: str = "month") -> None:
    """Prints the local backtested winner next to Azure's best trial, if
    a local forecast has already been generated for this metric (at the
    same frequency — a weekly Azure run is compared against the local
    pipeline's weekly output, not its monthly one)."""
    # Month files are "{metric}_{ts}.json"; week/day files are
    # "{metric}_{freq}_{ts}.json" — a plain "{metric}_" prefix would also
    # match those, so month explicitly excludes them.
    if freq == "month":
        files = sorted(
            (f for f in os.listdir(OUTPUTS_DIR) if f.startswith(f"{metric}_") and f.endswith(".json")
             and not f.startswith(f"{metric}_week_") and not f.startswith(f"{metric}_day_")),
            reverse=True,
        ) if os.path.isdir(OUTPUTS_DIR) else []
    else:
        files = sorted(
            (f for f in os.listdir(OUTPUTS_DIR) if f.startswith(f"{metric}_{freq}_") and f.endswith(".json")),
            reverse=True,
        ) if os.path.isdir(OUTPUTS_DIR) else []
    if not files:
        print(f"  (No local forecast found for '{metric}' yet — run predict.py first to compare.)")
        return

    with open(os.path.join(OUTPUTS_DIR, files[0])) as f:
        local = json.load(f)
    local_model = local.get("model_used")
    local_acc = local.get("models", {}).get(local_model, {}).get("accuracy_pct")

    print(f"\n  -- {METRIC_LABELS.get(metric, metric)}: local vs Azure AutoML --")
    print(f"  Local winner:  {local_model}  (backtested accuracy: {local_acc:.1f}%)" if local_acc else f"  Local winner:  {local_model}")
    if azure_result["leaderboard"]:
        best = azure_result["leaderboard"][0]
        acc = best.get("accuracy_pct_equivalent")
        acc_str = f", ~{acc:.1f}% accuracy-equivalent" if acc is not None else ""
        print(f"  Azure winner:  {best['algorithm']}  (normalized RMSE: {best['normalized_rmse']}{acc_str})")
        print(f"  Azure tried {len(azure_result['leaderboard'])} algorithm(s) total — see full list in the saved report.")
        print(f"  Note: Azure's \"accuracy-equivalent\" is 100 - MAPE%, the same framing as this "
              f"project's own accuracy_pct, but it's not an identical formula (this project also "
              f"weights near-term vs long-term error and penalizes flat forecasts) — treat this as "
              f"directionally comparable, not an exact apples-to-apples number.")
    else:
        print(f"  Azure status: {azure_result['status']} — leaderboard not available yet (check studio_url).")


def submit_only(metric: str, start_year: int, horizon: int, ml_client, limits: dict, freq: str = "month") -> str | None:
    """Fetches + uploads + submits ONE job and returns immediately with just
    the job name — does not wait for training to finish. This is what makes
    a "submit everything, then close the laptop" workflow possible.

    Returns (job_name, fetcher_data) — fetcher_data (history + current_month
    + notes, same dict shape data/fetcher.py returns everywhere else) is
    threaded through to wait_and_report() so it can later generate a real
    future forecast from the winning Azure model using the exact same
    history, instead of needing a second DB round-trip."""
    print(f"\nFetching cleaned history for '{metric}' ({freq})...")
    data = FETCHERS_BY_FREQUENCY[freq][metric](start_year)
    df = data["history"]
    min_floor = round(_freq_params(freq)["periods_per_year"])  # at least ~1 calendar year of history, per grain
    if df.empty or len(df) < min_floor:
        print(f"  Skipping '{metric}' — not enough cleaned history ({len(df)} {freq}s, need {min_floor}+).")
        return None, None

    print(f"  {len(df)} cleaned {freq}s ({df['ds'].min():%b %d, %Y} -> {df['ds'].max():%b %d, %Y})")
    job_name = submit_automl_job(metric, df, horizon, ml_client, limits, freq=freq)
    return job_name, data


def run_metric(metric: str, start_year: int, horizon: int, ml_client, limits: dict, freq: str = "month") -> dict:
    """Submit-and-wait in one call — used when NOT running with --no-wait."""
    job_name, data = submit_only(metric, start_year, horizon, ml_client, limits, freq=freq)
    if job_name is None:
        return {"metric": metric, "skipped": "insufficient history"}
    result = wait_and_report(ml_client, job_name, metric, data=data, horizon=horizon, freq=freq)
    compare_with_local(metric, result, freq=freq)
    return result


def run(args, progress_cb=None) -> dict:
    """
    Submit-and-wait-and-compare for one or more metrics, callable
    in-process (not just from the CLI) — this is what backend/jobs.py
    drives so the dashboard's "Train on Azure" button gets the exact same
    fetch -> clean -> upload -> submit -> auto-start-compute -> wait ->
    leaderboard behavior as running this file directly, with live progress
    instead of just a final result.

    args needs: metric ("all", a single key, or a comma-separated list —
    same as the CLI --metric), start_year, horizon, max_trials,
    max_concurrent_trials, timeout_minutes, trial_timeout_minutes, freq
    ("month"/"week"/"day" — defaults to "month").
    """
    _require_azure_config()
    ml_client = get_ml_client()
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    freq = getattr(args, "freq", None) or "month"
    if freq not in FETCHERS_BY_FREQUENCY:
        raise ValueError(f"Unknown frequency '{freq}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")

    metric_arg = getattr(args, "metric", None) or "all"
    if metric_arg == "all":
        metrics = list(FETCHERS.keys())
    else:
        metrics = [m.strip() for m in metric_arg.split(",") if m.strip()]
        unknown = [m for m in metrics if m not in FETCHERS]
        if unknown:
            raise ValueError(f"Unknown metric(s): {unknown}. Valid: {list(FETCHERS.keys())}")

    limits = {
        "max_trials": getattr(args, "max_trials", 25),
        "max_concurrent_trials": getattr(args, "max_concurrent_trials", 1),
        "timeout_minutes": getattr(args, "timeout_minutes", 90),
        "trial_timeout_minutes": getattr(args, "trial_timeout_minutes", 20),
    }
    start_year = getattr(args, "start_year", DEFAULT_START_YEAR)
    horizon = getattr(args, "horizon", DEFAULT_FORECAST_MONTHS)

    print(f"Connected to Azure ML workspace '{AML_WORKSPACE_NAME}'.")
    ensure_compute_running(ml_client)

    results = {}
    for i, m in enumerate(metrics):
        if progress_cb:
            progress_cb(i, len(metrics), m)
        results[m] = run_metric(m, start_year, horizon, ml_client, limits, freq=freq)

    if progress_cb:
        progress_cb(len(metrics), len(metrics), None)

    # Weekly/daily outputs get a distinct filename — never "azure_automl_{ts}.json"
    # — so they can't collide with / be mistaken for a monthly run, mirroring
    # predict.py's own output-naming convention.
    suffix = "" if freq == "month" else f"_{freq}"
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(OUTPUTS_DIR, f"azure_automl{suffix}_{ts}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull report saved to {out_path}")

    return {"ts": ts, "results": results, "output_path": out_path}


def build_forecast_from_downloads(metric: str, freq: str, horizon: int, start_year: int) -> dict:
    """
    Regenerates a full multi-model forecast report PURELY from artifacts
    already on disk — a previous training run's saved leaderboard/
    downloaded-models list (in outputs/azure_automl[_<freq>]_*.json) and
    the actual model files download_top_models() saved locally under
    models/azure_downloads/ — with NO live Azure connection at all: no
    ml_client, no Azure ML SDK import, no credentials, no .env Azure
    settings needed. This is what lets someone who was handed a copy of
    models/azure_downloads/ + outputs/ + data/cache/ (e.g. a teammate
    without Azure access) regenerate the same dashboard report on their
    own machine from already fine-tuned models, without ever training
    again or touching Azure.

    Recomputes each model's local_path fresh from THIS machine's project
    root rather than trusting the path stored in the saved JSON — that
    path was written by download_top_models() on whatever machine
    originally ran the training, which is very unlikely to be the same
    absolute path here.
    """
    stem = "azure_automl_[0-9]*" if freq == "month" else f"azure_automl_{freq}_*"
    files = sorted(glob.glob(os.path.join(OUTPUTS_DIR, f"{stem}.json")), key=os.path.getmtime, reverse=True)
    if not files:
        raise RuntimeError(
            f"No saved Azure report found for frequency '{freq}' in {OUTPUTS_DIR} — train on Azure at least "
            f"once first, or copy over an outputs/azure_automl*.json + models/azure_downloads/ from someone who has."
        )

    with open(files[0]) as f:
        all_results = json.load(f)
    saved = all_results.get(metric)
    if not saved:
        raise RuntimeError(f"No saved Azure result for metric '{metric}' in {os.path.basename(files[0])}.")

    leaderboard = saved.get("leaderboard") or []
    saved_downloads = saved.get("downloaded_models") or []
    job_name = saved.get("job_name")
    if not leaderboard or not saved_downloads or not job_name:
        raise RuntimeError(f"Saved result for '{metric}' has no leaderboard/downloaded models to rebuild from.")

    downloaded_models = []
    for d in saved_downloads:
        safe_algo = re.sub(r"[^A-Za-z0-9_-]", "", d["algorithm"])
        local_path = os.path.join(MODEL_DOWNLOAD_DIR, f"{metric}_{job_name}", f"rank{d['rank']:02d}_{safe_algo}")
        if os.path.isdir(local_path):
            downloaded_models.append({**d, "local_path": local_path})
    if not downloaded_models:
        raise RuntimeError(
            f"No downloaded model folders found on this machine for '{metric}' job '{job_name}' — expected under "
            f"models/azure_downloads/{metric}_{job_name}/. Copy that folder over from the machine that trained it first."
        )

    data = FETCHERS_BY_FREQUENCY[freq][metric](start_year)
    return build_forecast_detail(leaderboard, downloaded_models, metric, data, horizon, freq=freq)


def run_from_downloads(args, progress_cb=None) -> dict:
    """
    In-process entrypoint (same shape as run(), so backend/jobs.py drives
    it identically) for regenerating forecast_detail purely from already-
    downloaded local model artifacts — no Azure connection, no
    credentials, no new training job, typically finishes in seconds per
    metric. Updates the existing saved report file's forecast_detail for
    each requested metric in place; every other field (leaderboard,
    job_name, downloaded_models list) is left untouched.

    args needs: metric ("all", a single key, or a comma-separated list),
    freq, start_year, horizon.
    """
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    freq = getattr(args, "freq", None) or "month"
    if freq not in FETCHERS_BY_FREQUENCY:
        raise ValueError(f"Unknown frequency '{freq}'. Valid: {list(FETCHERS_BY_FREQUENCY.keys())}")

    metric_arg = getattr(args, "metric", None) or "all"
    metrics = list(FETCHERS.keys()) if metric_arg == "all" else [m.strip() for m in metric_arg.split(",") if m.strip()]
    unknown = [m for m in metrics if m not in FETCHERS]
    if unknown:
        raise ValueError(f"Unknown metric(s): {unknown}. Valid: {list(FETCHERS.keys())}")

    start_year = getattr(args, "start_year", DEFAULT_START_YEAR)
    horizon = getattr(args, "horizon", DEFAULT_FORECAST_MONTHS)

    stem = "azure_automl_[0-9]*" if freq == "month" else f"azure_automl_{freq}_*"
    files = sorted(glob.glob(os.path.join(OUTPUTS_DIR, f"{stem}.json")), key=os.path.getmtime, reverse=True)
    if not files:
        raise RuntimeError(f"No saved Azure report found for frequency '{freq}'. Train on Azure at least once first.")
    out_path = files[0]
    with open(out_path) as f:
        all_results = json.load(f)

    rebuilt = {}
    for i, m in enumerate(metrics):
        if progress_cb:
            progress_cb(i, len(metrics), m)
        try:
            forecast_detail = build_forecast_from_downloads(m, freq, horizon, start_year)
            if m in all_results:
                all_results[m]["forecast_detail"] = forecast_detail
            rebuilt[m] = f"ok — {len(forecast_detail['models'])} model(s)"
            print(f"  '{m}': rebuilt forecast from {len(forecast_detail['models'])} downloaded model(s).")
        except Exception as e:
            rebuilt[m] = f"skipped: {e}"
            print(f"  '{m}': {e}")

    if progress_cb:
        progress_cb(len(metrics), len(metrics), None)

    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nUpdated {out_path}")

    return {"output_path": out_path, "rebuilt": rebuilt}


def main():
    from utils.logging_setup import install_stdio_tee
    install_stdio_tee("azure")
    parser = argparse.ArgumentParser(description="Run Azure AutoML forecasting on cleaned pipeline data")
    parser.add_argument(
        "--metric", default="all",
        help="One metric (e.g. 'encounters'), 'all' for every metric, or a comma-separated "
             "list (e.g. 'patients,collections,contact_lenses') to run a subset — handy for "
             "skipping metrics you've already submitted a job for. "
             f"Valid names: {', '.join(FETCHERS.keys())}",
    )
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--horizon", type=int, default=DEFAULT_FORECAST_MONTHS)
    parser.add_argument("--freq", default="month", choices=list(FETCHERS_BY_FREQUENCY.keys()),
                         help="Series grain to train on — same three the local pipeline supports")
    parser.add_argument("--max-trials", type=int, default=25,
                         help="How many algorithm/config combinations Azure tries per metric")
    parser.add_argument("--max-concurrent-trials", type=int, default=1,
                         help="1 for a single Compute Instance (the default here); raise this "
                              "only if AML_COMPUTE_NAME points at a multi-node Compute Cluster")
    parser.add_argument("--timeout-minutes", type=int, default=90,
                         help="Hard ceiling for the whole job, across all trials")
    parser.add_argument("--trial-timeout-minutes", type=int, default=20,
                         help="Hard ceiling per individual trial")
    parser.add_argument(
        "--no-wait", action="store_true",
        help="Submit all jobs and exit immediately — do NOT wait/stream for them to finish. "
             "Use this when you want to submit everything and close your laptop; the jobs keep "
             "running on Azure regardless. Saves a job-map file you can later pass to --resume "
             "to fetch results once they're done.",
    )
    parser.add_argument(
        "--resume", metavar="JOB_MAP_JSON",
        help="Path to a job-map file saved by a previous --no-wait run (e.g. "
             "outputs/azure_jobs_20260730_1400.json). Reconnects to those already-submitted "
             "jobs, waits for any still running, and prints/saves the full leaderboard + "
             "comparison for each — this is how you check results the next day.",
    )
    args = parser.parse_args()

    limits = {
        "max_trials": args.max_trials,
        "max_concurrent_trials": args.max_concurrent_trials,
        "timeout_minutes": args.timeout_minutes,
        "trial_timeout_minutes": args.trial_timeout_minutes,
    }

    ml_client = get_ml_client()
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

    # ── Resume mode: no data fetch, no new jobs — just pull results for jobs already submitted ──
    if args.resume:
        with open(args.resume) as f:
            job_map = json.load(f)  # {metric: job_name}
        results = {}
        for m, job_name in job_map.items():
            print(f"\nChecking '{m}' -> job '{job_name}'...")
            result = wait_and_report(ml_client, job_name, m, freq=args.freq)
            compare_with_local(m, result, freq=args.freq)
            results[m] = result
        suffix = "" if args.freq == "month" else f"_{args.freq}"
        out_path = os.path.join(OUTPUTS_DIR, f"azure_automl{suffix}_{datetime.now():%Y%m%d_%H%M}.json")
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nFull report saved to {out_path}")
        return

    if args.metric == "all":
        metrics = list(FETCHERS.keys())
    else:
        metrics = [m.strip() for m in args.metric.split(",") if m.strip()]
        unknown = [m for m in metrics if m not in FETCHERS]
        if unknown:
            raise SystemExit(f"Unknown metric(s): {unknown}. Valid: {list(FETCHERS.keys())}")

    ensure_compute_running(ml_client)

    # ── Submit-only mode: fetch+upload+submit everything, then exit — safe to close the laptop ──
    if args.no_wait:
        job_map = {}
        for m in metrics:
            job_name, _ = submit_only(m, args.start_year, args.horizon, ml_client, limits, freq=args.freq)
            if job_name:
                job_map[m] = job_name
        map_path = os.path.join(OUTPUTS_DIR, f"azure_jobs_{datetime.now():%Y%m%d_%H%M}.json")
        with open(map_path, "w") as f:
            json.dump(job_map, f, indent=2)
        print(f"\nAll {len(job_map)} job(s) submitted and running on Azure — safe to close your "
              f"laptop now. Job map saved to {map_path}.")
        print(f"To check results later (even tomorrow, from anywhere):")
        print(f"  python azure_automl.py --resume {map_path}")
        return

    # ── Default mode: submit-and-wait-and-compare, one metric at a time (original behavior) ──
    results = {}
    for m in metrics:
        results[m] = run_metric(m, args.start_year, args.horizon, ml_client, limits, freq=args.freq)

    suffix = "" if args.freq == "month" else f"_{args.freq}"
    out_path = os.path.join(OUTPUTS_DIR, f"azure_automl{suffix}_{datetime.now():%Y%m%d_%H%M}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull report saved to {out_path}")


if __name__ == "__main__":
    main()
