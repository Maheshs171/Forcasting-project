"""
azure_automl.py
────────────────
Pushes this project's already-cleaned monthly history (the exact same
(ds, y) series your local models train on — future-dated rows filtered,
migration/outlier months already excluded via utils/outliers.py) to an
Azure Machine Learning workspace and runs an AutoML *forecasting* job
against it, so Azure's algorithm search can be compared side-by-side with
this project's own backtested pick.

What this does NOT do: it does not replace the local pipeline, does not
touch the SQL database directly (it reuses data/fetcher.py, which already
did that), and does not send any patient-identifying data — only the
monthly (date, value) series, same as everything else in this project.

Usage:
    python azure_automl.py --metric encounters --horizon 12
    python azure_automl.py --metric all --horizon 12

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
import json
import os
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
from data.fetcher import FETCHERS
from predict import METRIC_LABELS

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


def submit_automl_job(metric: str, df: pd.DataFrame, horizon: int, ml_client, limits: dict) -> str:
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
        frequency="MS",  # month-start, matches this project's monthly series
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


def wait_and_report(ml_client, job_name: str, metric: str) -> dict:
    """Streams the job to completion, then pulls the leaderboard (every
    trial Azure tried, ranked by score) so you can see ALL algorithms it
    compared, not just the winner."""
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
        all_runs = mlflow_client.search_runs(experiment_ids=[experiment_id], max_results=500)
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

    result = {
        "metric": metric, "job_name": job_name, "status": job.status,
        "studio_url": getattr(job, "studio_url", None),
        "leaderboard": leaderboard,
    }
    return result


def compare_with_local(metric: str, azure_result: dict) -> None:
    """Prints the local backtested winner next to Azure's best trial, if
    a local forecast has already been generated for this metric."""
    files = sorted(
        (f for f in os.listdir(OUTPUTS_DIR) if f.startswith(f"{metric}_") and f.endswith(".json")),
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


def submit_only(metric: str, start_year: int, horizon: int, ml_client, limits: dict) -> str | None:
    """Fetches + uploads + submits ONE job and returns immediately with just
    the job name — does not wait for training to finish. This is what makes
    a "submit everything, then close the laptop" workflow possible."""
    print(f"\nFetching cleaned history for '{metric}'...")
    data = FETCHERS[metric](start_year)
    df = data["history"]
    if df.empty or len(df) < 12:
        print(f"  Skipping '{metric}' — not enough cleaned history ({len(df)} months, need 12+).")
        return None

    print(f"  {len(df)} cleaned months ({df['ds'].min():%b %Y} -> {df['ds'].max():%b %Y})")
    return submit_automl_job(metric, df, horizon, ml_client, limits)


def run_metric(metric: str, start_year: int, horizon: int, ml_client, limits: dict) -> dict:
    """Submit-and-wait in one call — used when NOT running with --no-wait."""
    job_name = submit_only(metric, start_year, horizon, ml_client, limits)
    if job_name is None:
        return {"metric": metric, "skipped": "insufficient history"}
    result = wait_and_report(ml_client, job_name, metric)
    compare_with_local(metric, result)
    return result


def main():
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
            result = wait_and_report(ml_client, job_name, m)
            compare_with_local(m, result)
            results[m] = result
        out_path = os.path.join(OUTPUTS_DIR, f"azure_automl_{datetime.now():%Y%m%d_%H%M}.json")
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
            job_name = submit_only(m, args.start_year, args.horizon, ml_client, limits)
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
        results[m] = run_metric(m, args.start_year, args.horizon, ml_client, limits)

    out_path = os.path.join(OUTPUTS_DIR, f"azure_automl_{datetime.now():%Y%m%d_%H%M}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull report saved to {out_path}")


if __name__ == "__main__":
    main()
