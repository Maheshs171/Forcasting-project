"""
predict.py
───────────
Main entry point. Answers the three business questions directly:

  1. New patients / encounters — this month, and by end of this year
  2. Collections ($) — this month, next month, and by end of this year
  3. Contact lenses sold — till end of this year

Approach per metric:
  - Fetch summarized monthly history (SQL, aggregated only), with
    statistically anomalous months/transactions removed.
  - Fit EVERY applicable candidate model on the full history (not just the
    backtested winner) so every model's forecast, accuracy, and derived
    stats (this month/next month/EOY/rolling-12mo) are available side by
    side — the "recommended" one is just a pointer, not the only option
    computed, so a human can compare all of them and override.
  - The CURRENT (partial) calendar month is never fed to the point
    forecaster — it's estimated separately with a day-of-month pacing
    model (utils/pacing.py), since "this month" is fundamentally a
    different estimation problem from "a future month". This pacing
    figure is model-independent and shared across all models.
  - "By end of year" = actual completed months so far this year
                        + pacing estimate for the current month
                        + model forecast for remaining future months.

Usage:
  python predict.py                               # all 4 metrics, to Dec 31 this year
  python predict.py --metric collections
  python predict.py --end-date 2027-06-30
  python predict.py --model prophet                # force which model is "recommended"
"""

import sys, os, json, argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd

from config.settings import validate as validate_config, DEFAULT_START_YEAR, HOLIDAY_COUNTRY
from data.fetcher import FETCHERS, get_daily
from models.forecaster import ALL_FORECASTERS
from utils.pacing import project_month_end
from utils.chart import save_chart
from validate import select_best_model, is_flat_forecast

MONEY_METRICS = {"collections"}

METRIC_LABELS = {
    "patients":       "New patient registrations",
    "encounters":     "Clinical encounters",
    "collections":    "Collections ($)",
    "contact_lenses": "Contact lenses sold (units)",
}

MODEL_NAMES = {
    "naive": "Seasonal Naive", "ets": "ETS (Holt-Winters)", "sarima": "Auto-SARIMA",
    "prophet": "Prophet", "xgboost": "XGBoost (multi-feature)", "sarimax": "SARIMAX (multi-feature)",
}


def months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _derive_stats(result, history, pacing, now, year_start, end_of_year, current_month_start):
    """Everything downstream of a single model's raw forecast: next month,
    by-end-of-year, rolling-12-months, growth vs prior periods. Pacing (the
    current-month estimate) is shared across all models — it's computed
    once by the caller and passed in, not re-derived per model."""
    this_month_estimate = pacing["projected"]

    next_month_row = result.future[result.future["ds"] == current_month_start + pd.DateOffset(months=1)]
    next_month_estimate = float(next_month_row["yhat"].iloc[0]) if not next_month_row.empty else None

    actual_this_year_so_far = float(history[(history["ds"] >= year_start) & (history["ds"] < current_month_start)]["y"].sum())
    remaining_forecast = result.future[(result.future["ds"] > current_month_start) & (result.future["ds"] <= end_of_year)]
    remaining_sum = float(remaining_forecast["yhat"].sum())
    remaining_low = float(remaining_forecast["yhat_lower"].sum())
    remaining_high = float(remaining_forecast["yhat_upper"].sum())

    eoy_estimate = actual_this_year_so_far + this_month_estimate + remaining_sum
    eoy_low = actual_this_year_so_far + pacing["low"] + remaining_low
    eoy_high = actual_this_year_so_far + pacing["high"] + remaining_high

    next_11 = result.future[result.future["ds"] > current_month_start].head(11)
    rolling_12_total = this_month_estimate + float(next_11["yhat"].sum())
    rolling_12_low = pacing["low"] + float(next_11["yhat_lower"].sum())
    rolling_12_high = pacing["high"] + float(next_11["yhat_upper"].sum())
    rolling_12_months_covered = 1 + len(next_11)

    def _pct_change(new, old):
        if old is None or old == 0:
            return None
        return (new - old) / abs(old) * 100

    last_month_start = current_month_start - pd.DateOffset(months=1)
    last_month_row = history[history["ds"] == last_month_start]
    last_month_actual = float(last_month_row["y"].iloc[0]) if not last_month_row.empty else None
    mtd_growth_pct = _pct_change(this_month_estimate, last_month_actual)

    last_year_start = year_start - pd.DateOffset(years=1)
    same_period_last_year = history[(history["ds"] >= last_year_start) & (history["ds"] < last_year_start + (current_month_start - year_start) + pd.DateOffset(months=1))]
    same_period_last_year_total = float(same_period_last_year["y"].sum()) if not same_period_last_year.empty else None
    ytd_so_far = actual_this_year_so_far + this_month_estimate
    ytd_growth_pct = _pct_change(ytd_so_far, same_period_last_year_total)

    last_year_full = history[(history["ds"] >= last_year_start) & (history["ds"] < year_start)]
    last_year_total = float(last_year_full["y"].sum()) if not last_year_full.empty else None
    full_year_growth_pct = _pct_change(eoy_estimate, last_year_total)

    return {
        "next_month": {
            "month": (current_month_start + pd.DateOffset(months=1)).strftime("%Y-%m"),
            "projected_total": next_month_estimate,
        } if next_month_estimate is not None else None,
        "by_end_of_year": {
            "year": now.year,
            "actual_so_far": actual_this_year_so_far,
            "current_month_estimate": this_month_estimate,
            "remaining_months_forecast": remaining_sum,
            "total_estimate": eoy_estimate,
            "low": eoy_low, "high": eoy_high,
        },
        "next_12_months": {
            "months_covered": rolling_12_months_covered,
            "total_estimate": rolling_12_total,
            "low": rolling_12_low, "high": rolling_12_high,
        },
        "growth": {
            "last_month_actual": last_month_actual,
            "mtd_growth_pct": mtd_growth_pct,
            "same_period_last_year_total": same_period_last_year_total,
            "ytd_growth_pct": ytd_growth_pct,
            "last_year_total": last_year_total,
            "full_year_growth_pct": full_year_growth_pct,
        },
        "full_forecast": result.to_list(),
    }


def run_metric(metric: str, args, ts: str, all_data: dict = None) -> dict:
    print(f"\n{'='*70}\n  {METRIC_LABELS[metric]}\n{'='*70}")

    data = all_data[metric] if all_data else FETCHERS[metric](args.start_year)
    history = data["history"]
    current_month_row = data["current_month"]
    notes = data["notes"]
    for n in notes:
        print(f"  ! {n}")

    extra_signals = None
    if all_data:
        extra_signals = {k: d["history"] for k, d in all_data.items() if k != metric}

    if len(history) < 12:
        print(f"  Not enough clean history ({len(history)} months) to forecast — need 12+")
        return None

    is_money = metric in MONEY_METRICS
    now = pd.Timestamp.now()
    year_start = pd.Timestamp(year=now.year, month=1, day=1)
    end_of_year = pd.Timestamp(year=now.year, month=12, day=1)
    current_month_start = now.normalize().replace(day=1)
    historical_std = float(history["y"].std() or 0)

    # ── Horizon: enough months to reach --end-date / --months, and at least to Dec ──
    if args.end_date:
        target = pd.to_datetime(args.end_date).replace(day=1)
    else:
        target = max(end_of_year, current_month_start + pd.DateOffset(months=args.months))
    periods = max(months_between(history["ds"].max(), target), 1)

    def _fit(key):
        cls = ALL_FORECASTERS[key]
        needs_country = key in ("prophet", "xgboost", "sarimax")
        fc = cls(country=args.country) if needs_country else cls()
        return fc.fit_predict(history, periods=periods, metric=METRIC_LABELS[metric], extra_signals=extra_signals)

    # ── Backtest every candidate (real held-out accuracy per model) ──────
    print(f"  Backtesting candidate models...")
    backtest_report = select_best_model(history, metric, country=args.country, extra_signals=extra_signals)
    candidates = backtest_report["candidates"]

    # ── Current-month pacing (shared across every model) ─────────────────
    pacing = None
    try:
        daily = get_daily(metric, args.start_year) if metric != "contact_lenses" else None
        if daily is not None and not daily.empty:
            pacing = project_month_end(daily, current_month_start, as_of=now)
    except Exception as e:
        print(f"  Pacing unavailable: {e}")

    if pacing is None:
        mtd_actual = float(current_month_row["y"].iloc[0]) if not current_month_row.empty else 0.0
        days_in_month = pd.Period(current_month_start, freq="M").days_in_month
        frac = max(now.day / days_in_month, 0.05)
        projected = mtd_actual / frac
        pacing = {
            "mtd_actual": mtd_actual, "projected": projected,
            "low": projected * 0.85, "high": projected * 1.15,
            "fraction_elapsed": frac, "as_of_day": now.day, "history_months_used": 0,
        }

    # ── Fit every candidate that was actually scoreable, on the full history ──
    scoreable = [k for k, c in candidates.items() if "weighted_score" in c]
    models_out = {}
    fit_results = {}
    for key in scoreable:
        try:
            result = _fit(key)
        except Exception as e:
            print(f"  {key}: failed to fit on full history ({e})")
            continue
        flat = is_flat_forecast(result.future["yhat"].values, historical_std)
        fit_results[key] = result
        stats = _derive_stats(result, history, pacing, now, year_start, end_of_year, current_month_start)
        models_out[key] = {
            "model_key": key,
            "model_name": MODEL_NAMES.get(key, key),
            "is_flat": flat,
            "accuracy_pct": candidates[key].get("accuracy_pct"),
            "near_term_mape": candidates[key].get("near_term_mape"),
            "long_term_mape": candidates[key].get("long_term_mape"),
            **stats,
        }

    if not models_out:
        print(f"  No model could be fit for {metric} — skipping.")
        return None

    # ── Pick the recommended model: best backtest score, skipping ones ───
    # whose production fit (on the FULL history) turned out flat — a model
    # can pass backtesting on partial folds and still degenerate once
    # refit on everything, so this is checked again here rather than
    # trusting the backtest ranking blindly.
    if args.model and args.model in models_out:
        recommended = args.model
    else:
        ranked = sorted(scoreable, key=lambda k: candidates[k]["weighted_score"])
        recommended = next((k for k in ranked if k in models_out and not models_out[k]["is_flat"]), None)
        if recommended is None:
            recommended = next((k for k in ranked if k in models_out), list(models_out.keys())[0])

    for key in models_out:
        models_out[key]["is_recommended"] = key == recommended

    print(f"  Fitted models: {', '.join(models_out.keys())}")
    print(f"  Recommended: {recommended}"
          + (f" (flat production fit — shown for comparison only)" if models_out[recommended]["is_flat"] else ""))

    # ── Save outputs ────────────────────────────────────────────────────
    os.makedirs("outputs", exist_ok=True)
    fmt = (lambda v: f"${v:,.0f}") if is_money else (lambda v: f"{v:,.0f}")
    rec = models_out[recommended]

    summary = {
        "metric": metric,
        "label": METRIC_LABELS[metric],
        "model_used": recommended,       # kept for backward compatibility
        "best_model": recommended,
        "history_months": len(history),
        "horizon_months": periods,
        "data_quality_notes": notes,
        "this_month": {
            "month": current_month_start.strftime("%Y-%m"),
            "month_to_date_actual": pacing["mtd_actual"],
            "projected_total": pacing["projected"],
            "low": pacing["low"], "high": pacing["high"],
            "as_of_day": pacing["as_of_day"],
            "history_months_used": pacing.get("history_months_used", 0),
        },
        "models": models_out,
        # top-level convenience mirrors of the recommended model, so any
        # code/UI reading the old flat shape still works unmodified
        "next_month": rec["next_month"],
        "by_end_of_year": rec["by_end_of_year"],
        "next_12_months": rec["next_12_months"],
        "growth": rec["growth"],
        "full_forecast": rec["full_forecast"],
        "backtest": candidates,
    }

    json_path = f"outputs/{metric}_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    chart_path = f"outputs/{metric}_{ts}.html"
    save_chart(fit_results[recommended], chart_path, f"{METRIC_LABELS[metric]} forecast", is_money=is_money, pacing=pacing)

    this_month_estimate = pacing["projected"]
    print(f"\n  [{MODEL_NAMES.get(recommended, recommended)}] This month ({current_month_start:%b %Y}) so far: {fmt(pacing['mtd_actual'])}"
          f"  ->  projected full month: {fmt(this_month_estimate)}  ({fmt(pacing['low'])}-{fmt(pacing['high'])})")
    if rec["next_month"]:
        print(f"  Next month ({(current_month_start + pd.DateOffset(months=1)):%b %Y}) forecast: {fmt(rec['next_month']['projected_total'])}")
    eoy = rec["by_end_of_year"]
    print(f"  By end of {now.year}: {fmt(eoy['total_estimate'])}  ({fmt(eoy['low'])}-{fmt(eoy['high'])})")
    n12 = rec["next_12_months"]
    print(f"  Next 12 months (rolling from now): {fmt(n12['total_estimate'])}  ({fmt(n12['low'])}-{fmt(n12['high'])})")
    print(f"\n  JSON  -> {json_path}")
    print(f"  Chart -> {os.path.abspath(chart_path)}")

    return summary


def run(args, progress_cb=None):
    validate_config()
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    metrics = [args.metric] if args.metric else list(FETCHERS.keys())

    # Fetch every metric's data once — the multivariate models (XGBoost,
    # SARIMAX) use the OTHER metrics as cross-signal features, so all 4
    # are needed regardless of which one(s) are being forecast. This also
    # avoids re-fetching the same metric twice.
    all_data = {m: FETCHERS[m](args.start_year) for m in FETCHERS.keys()}

    all_summaries = {}
    for i, metric in enumerate(metrics):
        if progress_cb:
            progress_cb(i, len(metrics), metric)
        try:
            s = run_metric(metric, args, ts, all_data=all_data)
            if s:
                all_summaries[metric] = s
        except Exception as e:
            print(f"  ERROR forecasting {metric}: {e}")

    print(f"\n{'='*70}\n  SUMMARY\n{'='*70}")
    for metric, s in all_summaries.items():
        fmt = (lambda v: f"${v:,.0f}") if metric in MONEY_METRICS else (lambda v: f"{v:,.0f}")
        print(f"\n{s['label']}  (recommended: {s['model_used']}, {len(s['models'])} models available)")
        print(f"  This month:      {fmt(s['this_month']['projected_total'])}")
        if s["next_month"]:
            print(f"  Next month:      {fmt(s['next_month']['projected_total'])}")
        print(f"  By end of {s['by_end_of_year']['year']}: {fmt(s['by_end_of_year']['total_estimate'])}"
              f"  ({fmt(s['by_end_of_year']['low'])}-{fmt(s['by_end_of_year']['high'])})")

    with open(f"outputs/summary_{ts}.json", "w") as f:
        json.dump(all_summaries, f, indent=2, default=str)
    print(f"\nCombined summary -> outputs/summary_{ts}.json")

    if progress_cb:
        progress_cb(len(metrics), len(metrics), None)

    return {"ts": ts, "summaries": all_summaries}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Business forecasting: patients, encounters, collections, contact lenses")
    parser.add_argument("--metric", default=None, choices=list(FETCHERS.keys()))
    parser.add_argument("--model", default=None, choices=list(ALL_FORECASTERS.keys()),
                         help="Force which model is marked 'recommended' (all models are still computed)")
    parser.add_argument("--months", type=int, default=12, help="Minimum months to forecast beyond now")
    parser.add_argument("--end-date", default=None, help="Forecast until this date, e.g. 2027-12-31")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--country", default=HOLIDAY_COUNTRY)
    run(parser.parse_args())
