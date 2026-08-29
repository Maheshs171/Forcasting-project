"""
azure_score_job.py
────────────────────
Runs AS an Azure ML job, on Azure's own compute, in Azure's own curated
AutoML environment ("ai-ml-automl" — the exact environment AutoML itself
trains with, so azureml-training-tabular and its whole pinned dependency
tree are already present and guaranteed version-compatible with the
models it produces). This replaces the old approach of downloading model
artifacts to a local machine and loading them in a separately-maintained
venv_azure/ virtual environment — that worked, but needed a hand-built
Python 3.11 environment with a long, fragile dependency chain. Running
this step on Azure's own compute instead sidesteps the whole problem:
the environment that trained the model is, by definition, able to load
it back.

This script is intentionally self-contained (no imports from the rest of
this project) — it's uploaded to Azure as its own small code snapshot,
so it only needs what's already in the curated environment (pandas,
numpy, mlflow) plus stdlib. The math here (pacing, next-period/by-end-
of-year/rolling-12/growth) is a deliberate line-for-line port of
predict.py's _derive_stats and models/forecaster.py's ForecastResult/
_freq_params — kept in sync by hand since duplicating a few dozen lines
here is simpler and more robust than making this script depend on the
rest of the repo (which would pull in Prophet/XGBoost/etc. this job
never needs).

Usage (submitted by azure_automl.py, not run directly):
    python azure_score_job.py --metric patients --freq month --horizon 12
        --top-n 5 --history-csv history.csv --current-month 46
        --notes-json notes.json --leaderboard-json leaderboard.json
        --output-dir outputs

Writes outputs/forecast_detail.json — the same MetricForecast-shaped dict
azure_automl.py's build_forecast_detail() used to compute locally.
"""

import argparse
import json
import os
import re
import sys

# The curated AutoML environment's site-wide setuptools doesn't ship
# pkg_resources (newer setuptools dropped it), but mlflow.sklearn.load_model
# still imports it — and that same environment's own `pip` is separately
# broken (its vendored copy of pkg_resources is inconsistent with its pip
# version), so there's no way to `pip install setuptools` to fix this from
# inside the job. Instead, run_scoring_job() bundles a known-good pure-Python
# copy of pkg_resources (from this project's venv_azure/, pinned to an older
# setuptools that still includes it) as "pkg_resources_vendor/" alongside
# this script in the job's code upload — add it to sys.path before anything
# else imports pkg_resources.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pkg_resources_vendor"))


def _freq_params(freq: str) -> dict:
    if freq == "day":
        return {"pandas_freq": "D", "offset_kwarg": "days", "seasonal_period": 7, "min_seasonal": 14, "periods_per_year": 365}
    if freq == "week":
        return {"pandas_freq": "W-MON", "offset_kwarg": "weeks", "seasonal_period": 52, "min_seasonal": 104, "periods_per_year": 52}
    return {"pandas_freq": "MS", "offset_kwarg": "months", "seasonal_period": 12, "min_seasonal": 24, "periods_per_year": 12}


def _step(fp, n):
    import pandas as pd
    return pd.DateOffset(**{fp["offset_kwarg"]: n})


def _current_period_start(now, freq):
    import pandas as pd
    if freq == "day":
        return now.normalize()
    if freq == "week":
        return now.normalize() - pd.Timedelta(days=now.dayofweek)
    return now.normalize().replace(day=1)


def _to_list(future_df, freq):
    month_fmt, label_fmt = ("%Y-%m-%d", "%b %d, %Y") if freq in ("week", "day") else ("%Y-%m", "%b %Y")
    return [
        {
            "month": r["ds"].strftime(month_fmt),
            "label": r["ds"].strftime(label_fmt),
            "predicted": float(r["yhat"]),
            "low": float(r["yhat_lower"]),
            "high": float(r["yhat_upper"]),
        }
        for _, r in future_df.iterrows()
    ]


def _derive_stats(future_df, history, pacing, now, year_start, end_of_year, current_period_start, freq):
    import pandas as pd
    fp = _freq_params(freq)
    this_period_estimate = pacing["projected"]

    next_period_row = future_df[future_df["ds"] == current_period_start + _step(fp, 1)]
    next_period_estimate = float(next_period_row["yhat"].iloc[0]) if not next_period_row.empty else None

    actual_this_year_so_far = float(history[(history["ds"] >= year_start) & (history["ds"] < current_period_start)]["y"].sum())
    remaining_forecast = future_df[(future_df["ds"] > current_period_start) & (future_df["ds"] <= end_of_year)]
    remaining_sum = float(remaining_forecast["yhat"].sum())
    remaining_low = float(remaining_forecast["yhat_lower"].sum())
    remaining_high = float(remaining_forecast["yhat_upper"].sum())

    eoy_estimate = actual_this_year_so_far + this_period_estimate + remaining_sum
    eoy_low = actual_this_year_so_far + pacing["low"] + remaining_low
    eoy_high = actual_this_year_so_far + pacing["high"] + remaining_high

    next_11 = future_df[future_df["ds"] > current_period_start].head(11)
    rolling_12_total = this_period_estimate + float(next_11["yhat"].sum())
    rolling_12_low = pacing["low"] + float(next_11["yhat_lower"].sum())
    rolling_12_high = pacing["high"] + float(next_11["yhat_upper"].sum())
    rolling_12_periods_covered = 1 + len(next_11)

    def _pct_change(new, old):
        if old is None or old == 0:
            return None
        return (new - old) / abs(old) * 100

    last_period_start = current_period_start - _step(fp, 1)
    last_period_row = history[history["ds"] == last_period_start]
    last_period_actual = float(last_period_row["y"].iloc[0]) if not last_period_row.empty else None
    mtd_growth_pct = _pct_change(this_period_estimate, last_period_actual)

    last_year_start = year_start - pd.DateOffset(years=1)
    same_period_last_year = history[(history["ds"] >= last_year_start) & (history["ds"] < last_year_start + (current_period_start - year_start) + _step(fp, 1))]
    same_period_last_year_total = float(same_period_last_year["y"].sum()) if not same_period_last_year.empty else None
    ytd_so_far = actual_this_year_so_far + this_period_estimate
    ytd_growth_pct = _pct_change(ytd_so_far, same_period_last_year_total)

    last_year_full = history[(history["ds"] >= last_year_start) & (history["ds"] < year_start)]
    last_year_total = float(last_year_full["y"].sum()) if not last_year_full.empty else None
    full_year_growth_pct = _pct_change(eoy_estimate, last_year_total)

    month_fmt = "%Y-%m-%d" if freq in ("week", "day") else "%Y-%m"
    return {
        "next_month": {
            "month": (current_period_start + _step(fp, 1)).strftime(month_fmt),
            "projected_total": next_period_estimate,
        } if next_period_estimate is not None else None,
        "by_end_of_year": {
            "year": now.year,
            "actual_so_far": actual_this_year_so_far,
            "current_month_estimate": this_period_estimate,
            "remaining_months_forecast": remaining_sum,
            "total_estimate": eoy_estimate,
            "low": eoy_low, "high": eoy_high,
        },
        "next_12_months": {
            "months_covered": rolling_12_periods_covered,
            "total_estimate": rolling_12_total,
            "low": rolling_12_low, "high": rolling_12_high,
        },
        "growth": {
            "last_month_actual": last_period_actual,
            "mtd_growth_pct": mtd_growth_pct,
            "same_period_last_year_total": same_period_last_year_total,
            "ytd_growth_pct": ytd_growth_pct,
            "last_year_total": last_year_total,
            "full_year_growth_pct": full_year_growth_pct,
        },
        "full_forecast": _to_list(future_df, freq),
    }


def _slugify_algorithm(name, used):
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


def _forecast_one_model(run_id, algorithm, metric, history, pacing, now, year_start, end_of_year,
                         current_period_start, horizon, freq, mape, accuracy_pct):
    import numpy as np
    import pandas as pd
    import mlflow.sklearn

    fp = _freq_params(freq)
    last_ds = history["ds"].max()
    future_dates = pd.date_range(start=last_ds + _step(fp, 1), periods=horizon, freq=fp["pandas_freq"])

    model = mlflow.sklearn.load_model(f"runs:/{run_id}/outputs/mlflow-model")

    # Azure AutoML forecasting models trained without an explicit grain
    # column key their internal `forecast_origin` dict by the plain dummy
    # grain string ("_automl_dummy_grain_col"). But ForecastingPipelineWrapper's
    # own forecast() groups the request data by [grain_column] — a
    # single-element LIST — and pandas 2.0 changed groupby(list-of-one-column)
    # to yield tuple keys (e.g. ("_automl_dummy_grain_col",)) instead of the
    # bare string it used to. That mismatch makes the model's own "is this a
    # known grain?" check fail on every request, even though the data is
    # completely valid — a real regression surfaced by this curated
    # environment's pandas 2.0, not anything wrong with our input. Aliasing
    # the dict under both key shapes fixes it without touching any AutoML
    # internals beyond this one plain dict.
    if hasattr(model, "forecast_origin") and isinstance(model.forecast_origin, dict):
        for key in list(model.forecast_origin.keys()):
            if not isinstance(key, tuple):
                model.forecast_origin.setdefault((key,), model.forecast_origin[key])

    X_pred = pd.DataFrame({"ds": future_dates})
    y_query = np.repeat(np.nan, len(X_pred))
    y_pred, _ = model.forecast(X_pred, y_query)
    y_pred = np.asarray(y_pred, dtype=float)

    future_df = pd.DataFrame({
        "ds": future_dates, "yhat": y_pred,
        "yhat_lower": y_pred * 0.85, "yhat_upper": y_pred * 1.15,
    })
    stats = _derive_stats(future_df, history, pacing, now, year_start, end_of_year, current_period_start, freq)

    return {
        "model_name": algorithm,
        "is_flat": False,
        "accuracy_pct": accuracy_pct,
        "near_term_mape": mape,
        "long_term_mape": mape,
        **stats,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metric", required=True)
    parser.add_argument("--label", default=None)
    parser.add_argument("--freq", default="month")
    parser.add_argument("--horizon", type=int, required=True)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--history-csv", required=True)
    parser.add_argument("--current-period-actual", type=float, required=True)
    parser.add_argument("--notes-json", required=True)
    parser.add_argument("--leaderboard-json", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    import pandas as pd

    history = pd.read_csv(args.history_csv, parse_dates=["ds"])
    with open(args.notes_json) as f:
        notes = json.load(f)
    with open(args.leaderboard_json) as f:
        leaderboard = json.load(f)

    freq = args.freq
    metric = args.metric
    horizon = args.horizon

    now = pd.Timestamp.now()
    year_start = pd.Timestamp(year=now.year, month=1, day=1)
    end_of_year = pd.Timestamp(year=now.year, month=12, day=31)
    current_period_start = _current_period_start(now, freq)

    mtd_actual = args.current_period_actual
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

    used_keys = set()
    models_out = {}
    for entry in leaderboard:
        if len(models_out) >= args.top_n:
            break
        key = _slugify_algorithm(entry["algorithm"], used_keys)
        try:
            model_entry = _forecast_one_model(
                entry["run_id"], entry["algorithm"], metric, history, pacing, now, year_start, end_of_year,
                current_period_start, horizon, freq, entry.get("mape"), entry.get("accuracy_pct_equivalent"),
            )
            model_entry["model_key"] = key
            models_out[key] = model_entry
            print(f"  [ok] {entry['algorithm']} ({key}) scored successfully")
        except Exception as e:
            print(f"  [skip] {entry['algorithm']} — could not load/forecast: {e}")

    if not models_out:
        raise RuntimeError("None of the leaderboard's top trials could be loaded as models")

    best_key = next(iter(models_out))
    for key, m in models_out.items():
        m["is_recommended"] = key == best_key
    recommended = models_out[best_key]

    backtest_used_keys = set()
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

    result = {
        "metric": metric,
        "label": args.label or metric,
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

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, "forecast_detail.json")
    with open(out_path, "w") as f:
        json.dump(result, f, default=str)
    print(f"Wrote {out_path} — {len(models_out)} model(s): {list(models_out.keys())}")


if __name__ == "__main__":
    main()
