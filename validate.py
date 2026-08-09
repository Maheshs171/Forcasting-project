"""
validate.py
────────────
Rolling-origin backtesting: for each candidate model, repeatedly train on
data up to some cutoff and score its forecast against what actually
happened after that cutoff. This is the only honest way to claim
"accuracy" — a single in-sample fit tells you nothing about forecast
error. The model with the best backtested MAPE per metric is what
predict.py uses.

Usage:
  python validate.py                        # backtest all metrics
  python validate.py --metric collections
"""

import sys, os, argparse, json
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))

from config.settings import validate as validate_config, DEFAULT_START_YEAR, HOLIDAY_COUNTRY
from data.fetcher import FETCHERS, FETCHERS_BY_FREQUENCY
from models.forecaster import ALL_FORECASTERS, EnsembleForecaster, _freq_params

FREQ_ADVERB = {"month": "monthly", "week": "weekly", "day": "daily"}


def is_flat_forecast(future_yhat: np.ndarray, historical_std: float, threshold: float = 0.15) -> bool:
    """
    True if a forecast is (near-)constant relative to how much the metric
    actually varies historically — the same degenerate-model problem
    select_best_model() screens for during backtesting, checked again here
    against the actual production forecast, since a model refit on the
    full history can land on different (sometimes flatter) parameters than
    whatever won the backtest on partial-history folds.
    """
    if historical_std <= 0:
        return False
    return float(np.std(future_yhat)) / historical_std < threshold


def _mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    denom = np.where(np.abs(actual) < 1e-9, 1.0, np.abs(actual))
    return float(np.mean(np.abs(actual - predicted) / denom) * 100)


def rolling_backtest(
    df: pd.DataFrame,
    forecaster_factory,
    horizon: int = 12,
    min_train: int = 18,
    step: int = 3,
    extra_signals: dict = None,
    freq: str = "month",
) -> dict:
    """
    Expanding-window backtest. Returns per-step-ahead MAPE (1..horizon)
    averaged across all folds, plus overall MAPE and fold count.

    extra_signals (for multivariate candidates only): the OTHER metrics'
    FULL history. Sliced per-fold to each fold's own train cutoff before
    use, so a fold is never handed another metric's future actuals —
    the same constraint the model would face in real production.
    """
    n = len(df)
    per_step_errors = {h: [] for h in range(1, horizon + 1)}
    fold_forecast_stds = []
    n_folds = 0

    cutoff = min_train
    while cutoff + 1 <= n:
        train = df.iloc[:cutoff].reset_index(drop=True)
        test = df.iloc[cutoff:cutoff + horizon].reset_index(drop=True)
        if test.empty:
            break

        fold_signals = None
        if extra_signals:
            cutoff_ds = train["ds"].max()
            fold_signals = {name: s[s["ds"] <= cutoff_ds].reset_index(drop=True) for name, s in extra_signals.items()}

        try:
            fc = forecaster_factory().fit_predict(train, periods=len(test), metric="backtest", extra_signals=fold_signals, freq=freq)
        except Exception:
            cutoff += step
            continue

        pred = fc.future.reset_index(drop=True)
        for h in range(1, len(test) + 1):
            actual_v = test["y"].iloc[h - 1]
            pred_v = pred["yhat"].iloc[h - 1]
            per_step_errors[h].append(abs(actual_v - pred_v) / max(abs(actual_v), 1.0) * 100)

        if len(pred) >= 3:
            fold_forecast_stds.append(float(pred["yhat"].std()))

        n_folds += 1
        cutoff += step

    per_step_mape = {h: (float(np.mean(v)) if v else None) for h, v in per_step_errors.items()}
    near_term = [v for h, v in per_step_mape.items() if h <= 3 and v is not None]
    long_term = [v for h, v in per_step_mape.items() if h > 3 and v is not None]
    overall = [v for v in per_step_mape.values() if v is not None]

    return {
        "n_folds": n_folds,
        "per_step_mape": per_step_mape,
        "near_term_mape": float(np.mean(near_term)) if near_term else None,
        "long_term_mape": float(np.mean(long_term)) if long_term else None,
        "overall_mape": float(np.mean(overall)) if overall else None,
        "avg_forecast_std": float(np.mean(fold_forecast_stds)) if fold_forecast_stds else 0.0,
    }


def _finalize_score(report: dict, historical_std: float) -> None:
    """
    Shared scoring math for any backtest report (base candidate or
    ensemble): near/long-term blended score, plain-language accuracy %,
    and the flat-forecast penalty. Mutates `report` in place.
    """
    near = report["near_term_mape"] if report["near_term_mape"] is not None else report["overall_mape"]
    longt = report["long_term_mape"] if report["long_term_mape"] is not None else report["overall_mape"]
    score = 0.6 * (near or 0) + 0.4 * (longt or 0)

    # Plain-language accuracy for non-technical readers: 100% minus the
    # (unpenalized) error rate, floored at 0. Not a substitute for MAPE in
    # the selection math below, just a friendlier way to display it.
    report["accuracy_pct"] = float(np.clip(100 - score, 0, 100))

    # A model that forecasts (near-)constant values every month has failed to
    # capture the data's actual month-to-month pattern, even if that flatness
    # happens to score well on MAPE against noisy data (e.g. auto-ARIMA
    # collapsing to "just predict the mean" once AIC penalizes real dynamics
    # as overfitting on a short series). A flat line is unusable for monthly
    # business planning, so it's disqualified here rather than silently
    # shipped just because it "won" a narrow accuracy metric.
    flatness_ratio = (report["avg_forecast_std"] / historical_std) if historical_std > 0 else 1.0
    report["flatness_ratio"] = flatness_ratio
    if flatness_ratio < 0.15:
        score *= 4.0
        report["flat_forecast_penalty_applied"] = True

    report["weighted_score"] = score


def select_best_model(
    df: pd.DataFrame,
    metric_name: str,
    horizon: int = 12,
    country: str = "US",
    extra_signals: dict = None,
    freq: str = "month",
) -> dict:
    """
    Backtests every candidate whose min-data requirement is met, scores
    each with 60% weight on near-term MAPE and 40% on longer-term MAPE —
    near-term matters most for "this period / next period" business
    questions, but full-year accuracy still counts.
    Returns the backtest report for all candidates + the winner's name.

    extra_signals: the other metrics' full history, only used by the
    multivariate candidates (XGBoost, SARIMAX) — see rolling_backtest for
    how it's kept leakage-free per fold.

    An "ensemble" candidate (blend of the top 2 non-flat base models,
    inverse-error weighted) is added after the base candidates and
    backtested the exact same way — it only wins if it demonstrably beats
    its own components on real held-out accuracy, not by assumption.

    freq: "month", "week", or "day" — every candidate's min-data floor is
    scaled to the equivalent number of periods (e.g. a 24-month floor
    becomes ~104 weeks, or ~730 days) so weekly/daily data isn't held to a
    monthly-sized bar. Scaled by periods_per_year (calendar-time equivalence),
    not seasonal_period (the model's own cyclical fitting length) — those
    two diverge for daily, where the cheap-to-fit seasonal cycle is only 7
    days but a trustworthy floor still needs real calendar years of data.
    """
    needs_country = {"prophet", "xgboost", "sarimax", "random_forest", "extra_trees"}
    historical_std = float(df["y"].std() or 0)
    fp = _freq_params(freq)
    period_scale = fp["periods_per_year"] / 12  # 1.0 for month, ~4.33 for week, ~30.4 for day
    # rolling_backtest's own min_train/step defaults (18, 3) are sized for
    # monthly data. Left unscaled, weekly/daily data — with far more raw
    # periods per unit of calendar time — silently explode into hundreds of
    # backtest folds (many trained on almost no history) instead of a
    # comparable number to monthly. Harmless-but-slow for weekly (a live
    # daily backtest with this bug took over an hour and had to be killed).
    step = max(round(3 * period_scale), 1)
    results = {}
    for key, cls in ALL_FORECASTERS.items():
        min_periods = round(cls.min_months * period_scale)
        if len(df) < min_periods + 6:  # need room for at least one backtest fold
            results[key] = {"skipped": f"needs {min_periods}+ {freq}s, have {len(df)}"}
            continue

        is_multivariate = getattr(cls, "is_multivariate", False)

        def factory(cls=cls, key=key):
            return cls(country=country) if key in needs_country else cls()

        try:
            report = rolling_backtest(
                df, factory, horizon=min(horizon, 12), min_train=min_periods, step=step,
                extra_signals=extra_signals if is_multivariate else None,
                freq=freq,
            )
        except Exception as e:
            results[key] = {"skipped": f"error during backtest: {e}"}
            continue

        if report["n_folds"] == 0:
            results[key] = {"skipped": "no valid backtest folds"}
            continue

        _finalize_score(report, historical_std)
        results[key] = report

    # ── Ensemble: top 2 non-flat base models, inverse-error weighted ──────
    eligible = [
        k for k, r in results.items()
        if "weighted_score" in r and not r.get("flat_forecast_penalty_applied")
    ]
    if len(eligible) >= 2:
        top2 = sorted(eligible, key=lambda k: results[k]["weighted_score"])[:2]
        key_a, key_b = top2
        score_a = max(results[key_a]["weighted_score"], 0.01)
        score_b = max(results[key_b]["weighted_score"], 0.01)
        inv_a, inv_b = 1.0 / score_a, 1.0 / score_b
        weight_a = inv_a / (inv_a + inv_b)
        weight_b = 1.0 - weight_a

        def ensemble_factory(key_a=key_a, key_b=key_b, weight_a=weight_a, weight_b=weight_b):
            return EnsembleForecaster(key_a, weight_a, key_b, weight_b, country=country)

        try:
            ens_report = rolling_backtest(
                df, ensemble_factory, horizon=min(horizon, 12), min_train=round(18 * period_scale), step=step,
                extra_signals=extra_signals, freq=freq,
            )
            if ens_report["n_folds"] > 0:
                _finalize_score(ens_report, historical_std)
                ens_report["components"] = {
                    "model_a": key_a, "weight_a": round(weight_a, 4),
                    "model_b": key_b, "weight_b": round(weight_b, 4),
                }
                results["ensemble"] = ens_report
            else:
                results["ensemble"] = {"skipped": "no valid backtest folds"}
        except Exception as e:
            results["ensemble"] = {"skipped": f"error during backtest: {e}"}
    else:
        results["ensemble"] = {"skipped": "fewer than 2 non-flat base models available to blend"}

    scored = {k: v for k, v in results.items() if "weighted_score" in v}
    best_key = min(scored, key=lambda k: scored[k]["weighted_score"]) if scored else "naive"

    return {"metric": metric_name, "candidates": results, "best_model": best_key}


def print_report(report: dict):
    print(f"\n{'='*70}")
    print(f"  BACKTEST — {report['metric']}")
    print(f"{'='*70}")
    print(f"{'Model':<14}{'Folds':>7}{'Accuracy':>11}{'Near-term MAPE':>18}{'Long-term MAPE':>18}{'Score':>10}")
    print("-" * 70)
    for key, r in report["candidates"].items():
        if "skipped" in r:
            print(f"{key:<14}{'--':>7}  {r['skipped']}")
            continue
        near = f"{r['near_term_mape']:.1f}%" if r["near_term_mape"] is not None else "n/a"
        longt = f"{r['long_term_mape']:.1f}%" if r["long_term_mape"] is not None else "n/a"
        acc = f"{r['accuracy_pct']:.0f}%"
        score = f"{r['weighted_score']:.1f}"
        flat = "  [flat forecast, penalized]" if r.get("flat_forecast_penalty_applied") else ""
        marker = "  <-- selected" if key == report["best_model"] else ""
        comp = ""
        if r.get("components"):
            c = r["components"]
            comp = f"  ({c['model_a']} x{c['weight_a']} + {c['model_b']} x{c['weight_b']})"
        print(f"{key:<14}{r['n_folds']:>7}{acc:>11}{near:>18}{longt:>18}{score:>10}{marker}{flat}{comp}")
    print("-" * 70)
    print(f"  Winner: {report['best_model']}\n")


def run(args, progress_cb=None):
    validate_config()
    freq = getattr(args, "freq", "month") or "month"
    fetchers = FETCHERS_BY_FREQUENCY[freq]
    metrics = [args.metric] if args.metric else list(fetchers.keys())

    # Fetch every metric's history once — the multivariate candidates
    # (XGBoost, SARIMAX) use the OTHER metrics as cross-signal features,
    # so all 4 need to be loaded regardless of which one is being scored.
    print(f"Loading all metrics ({FREQ_ADVERB.get(freq, freq)}, needed for cross-metric features)...")
    all_history = {}
    for m in fetchers.keys():
        data = fetchers[m](args.start_year)
        all_history[m] = data["history"]
        if m in metrics:
            for n in data["notes"]:
                print(f"  ! {n}")

    min_floor = round(18 * _freq_params(freq)["periods_per_year"] / 12)
    all_reports = {}
    for i, metric in enumerate(metrics):
        if progress_cb:
            progress_cb(i, len(metrics), metric)
        df = all_history[metric]
        if len(df) < min_floor:
            print(f"  Not enough clean history ({len(df)} {freq}s) to backtest {metric} — need {min_floor}+")
            continue

        extra_signals = {k: v for k, v in all_history.items() if k != metric}
        report = select_best_model(df, metric, country=args.country, extra_signals=extra_signals, freq=freq)
        print_report(report)
        all_reports[metric] = report

    os.makedirs("outputs", exist_ok=True)
    suffix = "" if freq == "month" else f"_{freq}"
    with open(f"outputs/backtest_report{suffix}.json", "w") as f:
        json.dump(all_reports, f, indent=2, default=str)
    print(f"Saved outputs/backtest_report{suffix}.json")

    if progress_cb:
        progress_cb(len(metrics), len(metrics), None)

    return all_reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest all candidate forecasters per metric")
    parser.add_argument("--metric", default=None, choices=list(FETCHERS.keys()))
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--country", default=HOLIDAY_COUNTRY)
    parser.add_argument("--freq", default="month", choices=["month", "week", "day"])
    run(parser.parse_args())
