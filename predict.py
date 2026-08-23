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
from data.fetcher import FETCHERS, FETCHERS_BY_FREQUENCY, get_daily
from models.forecaster import ALL_FORECASTERS, EnsembleForecaster, _freq_params, _step
from utils.pacing import project_period_end
from utils.chart import save_chart
from validate import select_best_model, is_flat_forecast

MONEY_METRICS = {"collections"}

METRIC_LABELS = {
    "patients":       "New patient registrations",
    "encounters":     "Clinical encounters",
    "collections":    "Collections ($)",
    "contact_lenses": "Contact lenses sold (units)",
}

FREQ_ADVERB = {"month": "monthly", "week": "weekly", "day": "daily"}

# Matches frontend/src/pages/MetricDashboard.tsx's ACCENT_COLOR so the
# standalone chart uses the same per-metric color as the in-app one.
ACCENT_COLOR = {
    "patients": "#4f46e5",
    "encounters": "#0891b2",
    "collections": "#059669",
    "contact_lenses": "#7c3aed",
}

MODEL_NAMES = {
    "naive": "Seasonal Naive", "ets": "ETS (Holt-Winters)", "sarima": "Auto-SARIMA",
    "prophet": "Prophet", "xgboost": "XGBoost (multi-feature)", "sarimax": "SARIMAX (multi-feature)",
    "random_forest": "Random Forest (multi-feature)", "extra_trees": "Extra Trees (multi-feature)",
    "mlforecast": "mlforecast (LightGBM)",
    "autots": "AutoTS",
}


def months_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def periods_between(a: pd.Timestamp, b: pd.Timestamp, freq: str) -> int:
    if freq == "day":
        return int((b - a).days)
    if freq == "week":
        return int((b - a).days // 7)
    return months_between(a, b)


def _current_period_start(now: pd.Timestamp, freq: str) -> pd.Timestamp:
    if freq == "day":
        return now.normalize()
    if freq == "week":
        return now.normalize() - pd.Timedelta(days=now.dayofweek)  # Monday of this week
    return now.normalize().replace(day=1)


def _derive_stats(result, history, pacing, now, year_start, end_of_year, current_period_start, freq="month"):
    """Everything downstream of a single model's raw forecast: next
    period, by-end-of-year, rolling-12-periods, growth vs prior periods.
    Pacing (the current-period estimate) is shared across all models —
    it's computed once by the caller and passed in, not re-derived per
    model. Field names stay "month"-shaped (next_month, months_covered,
    etc.) for API/frontend compatibility even when freq="week" — the
    frontend relabels them based on the frequency it requested."""
    fp = _freq_params(freq)
    this_period_estimate = pacing["projected"]

    next_period_row = result.future[result.future["ds"] == current_period_start + _step(fp, 1)]
    next_period_estimate = float(next_period_row["yhat"].iloc[0]) if not next_period_row.empty else None

    actual_this_year_so_far = float(history[(history["ds"] >= year_start) & (history["ds"] < current_period_start)]["y"].sum())
    remaining_forecast = result.future[(result.future["ds"] > current_period_start) & (result.future["ds"] <= end_of_year)]
    remaining_sum = float(remaining_forecast["yhat"].sum())
    remaining_low = float(remaining_forecast["yhat_lower"].sum())
    remaining_high = float(remaining_forecast["yhat_upper"].sum())

    eoy_estimate = actual_this_year_so_far + this_period_estimate + remaining_sum
    eoy_low = actual_this_year_so_far + pacing["low"] + remaining_low
    eoy_high = actual_this_year_so_far + pacing["high"] + remaining_high

    next_11 = result.future[result.future["ds"] > current_period_start].head(11)
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
        "full_forecast": result.to_list(freq=freq),
    }


def run_metric(metric: str, args, ts: str, all_data: dict = None) -> dict:
    freq = getattr(args, "freq", "month") or "month"
    fp = _freq_params(freq)
    print(f"\n{'='*70}\n  {METRIC_LABELS[metric]} ({FREQ_ADVERB.get(freq, freq)})\n{'='*70}")

    fetchers = FETCHERS_BY_FREQUENCY[freq]
    data = all_data[metric] if all_data else fetchers[metric](args.start_year)
    history = data["history"]
    current_month_row = data["current_month"]
    notes = data["notes"]
    for n in notes:
        print(f"  ! {n}")

    extra_signals = None
    if all_data:
        extra_signals = {k: d["history"] for k, d in all_data.items() if k != metric}

    min_floor = round(fp["periods_per_year"])  # at least ~1 calendar year of history before attempting a forecast
    if len(history) < min_floor:
        print(f"  Not enough clean history ({len(history)} {freq}s) to forecast — need {min_floor}+")
        return None

    is_money = metric in MONEY_METRICS
    now = pd.Timestamp.now()
    year_start = pd.Timestamp(year=now.year, month=1, day=1)
    end_of_year = pd.Timestamp(year=now.year, month=12, day=31)
    current_period_start = _current_period_start(now, freq)
    historical_std = float(history["y"].std() or 0)

    # ── Horizon: enough periods to reach --end-date / --months, and at least to Dec ──
    if args.end_date:
        target = pd.to_datetime(args.end_date)
        if freq == "month":
            target = target.replace(day=1)
    else:
        target = max(end_of_year, current_period_start + _step(fp, args.months))
    periods = max(periods_between(history["ds"].max(), target, freq), 1)

    # ── Backtest every candidate (real held-out accuracy per model) ──────
    print(f"  Backtesting candidate models...")
    backtest_report = select_best_model(history, metric, country=args.country, extra_signals=extra_signals, freq=freq)
    candidates = backtest_report["candidates"]

    def _fit(key):
        if key == "ensemble":
            comp = candidates["ensemble"]["components"]
            fc = EnsembleForecaster(comp["model_a"], comp["weight_a"], comp["model_b"], comp["weight_b"], country=args.country)
        else:
            cls = ALL_FORECASTERS[key]
            needs_country = key in ("prophet", "xgboost", "sarimax", "random_forest", "extra_trees")
            fc = cls(country=args.country) if needs_country else cls()
        return fc.fit_predict(history, periods=periods, metric=METRIC_LABELS[metric], extra_signals=extra_signals, freq=freq)

    # ── Current-period pacing (shared across every model) ─────────────────
    # Monthly uses a day-of-month pacing curve; weekly uses the analogous
    # day-of-week curve (both built from real day-level history — clinics
    # genuinely run lighter on Mondays than Fridays, payment batches land at
    # month-end, etc., so a naive linear elapsed-fraction is measurably
    # wrong for both). Daily has no equivalent: the DB only tracks
    # date-level counts, not intraday timestamps, so there's no sub-day
    # curve to build — it always uses the elapsed-fraction fallback below
    # (fraction of today's hours passed), same simplification-in-kind, just
    # with nothing finer available to build on.
    pacing = None
    if freq in ("month", "week"):
        try:
            daily = get_daily(metric, args.start_year) if metric != "contact_lenses" else None
            if daily is not None and not daily.empty:
                pacing = project_period_end(daily, current_period_start, freq=freq, as_of=now)
        except Exception as e:
            print(f"  Pacing unavailable: {e}")

    if pacing is None:
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
        stats = _derive_stats(result, history, pacing, now, year_start, end_of_year, current_period_start, freq=freq)
        models_out[key] = {
            "model_key": key,
            "model_name": MODEL_NAMES.get(key, result.model_name),
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

    # Trailing actual (cleaned) history — model-independent, shown alongside
    # the forecast so a user can see real recent movement rather than only
    # the projected future. 104 weeks ~= 24 months; daily uses ~6 months
    # (180 days) since a 24-month daily window would be too dense to read.
    trailing_window = 180 if freq == "day" else (104 if freq == "week" else 24)
    label_fmt = "%b %d, %Y" if freq in ("week", "day") else "%b %Y"
    month_fmt = "%Y-%m-%d" if freq in ("week", "day") else "%Y-%m"
    history_full = [
        {"month": r["ds"].strftime(month_fmt), "label": r["ds"].strftime(label_fmt), "value": float(r["y"])}
        for _, r in history.tail(trailing_window).iterrows()
    ]

    # Full multi-year history reshaped as (year, period) feeds the
    # year-over-year chart. Monthly buckets by calendar month (1-12);
    # weekly buckets by ISO week-of-year (1-53); daily buckets by
    # day-of-year (1-366, pandas' dayofyear — leap years naturally reach
    # 366, non-leap years top out at 365). Each grain avoids silently
    # collapsing multiple points into one shared bucket the way reusing a
    # coarser grain's shape would. The "month" key name is kept across all
    # three so the JSON shape (and frontend type) stays a single
    # YoyHistoryPoint — its meaning is just period-of-year, and the frontend
    # picks the right x-axis labels off `frequency`.
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
        "frequency": freq,
        "model_used": recommended,       # kept for backward compatibility
        "best_model": recommended,
        "history_months": len(history),
        "horizon_months": periods,
        "data_quality_notes": notes,
        "history_full": history_full,
        "yoy_history": yoy_history,
        "this_month": {
            "month": current_period_start.strftime(month_fmt),
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

    # Weekly outputs get a distinct filename (never "{metric}_{ts}.json")
    # so they can never collide with / be mistaken for a monthly run by
    # anything that globs "{metric}_*.json" expecting monthly shape.
    suffix = "" if freq == "month" else f"_{freq}"
    json_path = f"outputs/{metric}{suffix}_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    chart_path = f"outputs/{metric}{suffix}_{ts}.html"
    save_chart(
        fit_results[recommended], chart_path, f"{METRIC_LABELS[metric]} forecast", is_money=is_money, pacing=pacing,
        freq=freq, color=ACCENT_COLOR.get(metric, "#4f46e5"),
    )

    this_period_estimate = pacing["projected"]
    print(f"\n  [{MODEL_NAMES.get(recommended, recommended)}] This {freq} ({current_period_start:%b %d, %Y}) so far: {fmt(pacing['mtd_actual'])}"
          f"  ->  projected full {freq}: {fmt(this_period_estimate)}  ({fmt(pacing['low'])}-{fmt(pacing['high'])})")
    if rec["next_month"]:
        print(f"  Next {freq} ({(current_period_start + _step(fp, 1)):%b %d, %Y}) forecast: {fmt(rec['next_month']['projected_total'])}")
    eoy = rec["by_end_of_year"]
    print(f"  By end of {now.year}: {fmt(eoy['total_estimate'])}  ({fmt(eoy['low'])}-{fmt(eoy['high'])})")
    n12 = rec["next_12_months"]
    print(f"  Next 12 {freq}s (rolling from now): {fmt(n12['total_estimate'])}  ({fmt(n12['low'])}-{fmt(n12['high'])})")
    print(f"\n  JSON  -> {json_path}")
    print(f"  Chart -> {os.path.abspath(chart_path)}")

    return summary


def run(args, progress_cb=None):
    validate_config()
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    freq = getattr(args, "freq", "month") or "month"
    fetchers = FETCHERS_BY_FREQUENCY[freq]
    metrics = [args.metric] if args.metric else list(fetchers.keys())

    # Fetch every metric's data once — the multivariate models (XGBoost,
    # SARIMAX) use the OTHER metrics as cross-signal features, so all 4
    # are needed regardless of which one(s) are being forecast. This also
    # avoids re-fetching the same metric twice.
    all_data = {m: fetchers[m](args.start_year) for m in fetchers.keys()}

    # Optional history cutoff — separate from --end-date (which controls how
    # far the FORECAST extends). Use this when the most recent complete
    # period(s) are known-incomplete for an operational reason (e.g. a DB
    # backup/restore that missed recent transactions) rather than trusting
    # them as real data. Applied uniformly to every metric since a DB-wide
    # backup gap doesn't respect table boundaries, and the multivariate
    # models' cross-signals need every metric trimmed the same way to stay
    # leakage-free relative to each other.
    history_cutoff = getattr(args, "history_end_date", None)
    if history_cutoff:
        cutoff_raw = pd.to_datetime(history_cutoff)
        cutoff_ts = cutoff_raw.replace(day=1) if freq == "month" else cutoff_raw
        for m, data in all_data.items():
            before = len(data["history"])
            data["history"] = data["history"][data["history"]["ds"] <= cutoff_ts].reset_index(drop=True)
            dropped = before - len(data["history"])
            if dropped:
                note = f"history cutoff applied: excluded {dropped} {freq}(s) after {cutoff_ts:%b %d, %Y} (--history-end-date)"
                data["notes"] = list(data["notes"]) + [note]
                print(f"  ! [{m}] {note}")

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
    parser.add_argument("--model", default=None, choices=list(ALL_FORECASTERS.keys()) + ["ensemble"],
                         help="Force which model is marked 'recommended' (all models are still computed)")
    parser.add_argument("--freq", default="month", choices=["month", "week", "day"],
                         help="Forecast at monthly, weekly, or daily granularity")
    parser.add_argument("--months", type=int, default=12, help="Minimum periods to forecast beyond now (months, weeks, or days depending on --freq)")
    parser.add_argument("--end-date", default=None, help="Forecast until this date, e.g. 2027-12-31")
    parser.add_argument(
        "--history-end-date", default=None,
        help="Trim all metrics' training history to this month or earlier — use when the most "
             "recent month(s) are known-incomplete (e.g. right after a DB backup/restore), so "
             "they aren't mistaken for real zero-growth data. e.g. 2026-06-30",
    )
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--country", default=HOLIDAY_COUNTRY)
    from utils.logging_setup import install_stdio_tee
    install_stdio_tee("predict")
    run(parser.parse_args())
