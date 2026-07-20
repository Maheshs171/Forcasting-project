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
from data.fetcher import FETCHERS
from models.forecaster import ALL_FORECASTERS


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
            fc = forecaster_factory().fit_predict(train, periods=len(test), metric="backtest", extra_signals=fold_signals)
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


def select_best_model(
    df: pd.DataFrame,
    metric_name: str,
    horizon: int = 12,
    country: str = "US",
    extra_signals: dict = None,
) -> dict:
    """
    Backtests every candidate whose min-data requirement is met, scores
    each with 60% weight on near-term (1-3mo) MAPE and 40% on longer-term
    (4-12mo) MAPE — near-term matters most for "this month / next month"
    business questions, but full-year accuracy still counts.
    Returns the backtest report for all candidates + the winner's name.

    extra_signals: the other metrics' full history, only used by the
    multivariate candidates (XGBoost, SARIMAX) — see rolling_backtest for
    how it's kept leakage-free per fold.
    """
    needs_country = {"prophet", "xgboost", "sarimax"}
    results = {}
    for key, cls in ALL_FORECASTERS.items():
        if len(df) < cls.min_months + 6:  # need room for at least one backtest fold
            results[key] = {"skipped": f"needs {cls.min_months}+ months, have {len(df)}"}
            continue

        is_multivariate = getattr(cls, "is_multivariate", False)

        def factory(cls=cls, key=key):
            return cls(country=country) if key in needs_country else cls()

        try:
            report = rolling_backtest(
                df, factory, horizon=min(horizon, 12),
                extra_signals=extra_signals if is_multivariate else None,
            )
        except Exception as e:
            results[key] = {"skipped": f"error during backtest: {e}"}
            continue

        if report["n_folds"] == 0:
            results[key] = {"skipped": "no valid backtest folds"}
            continue

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
        historical_std = float(df["y"].std() or 0)
        flatness_ratio = (report["avg_forecast_std"] / historical_std) if historical_std > 0 else 1.0
        report["flatness_ratio"] = flatness_ratio
        if flatness_ratio < 0.15:
            score *= 4.0
            report["flat_forecast_penalty_applied"] = True

        report["weighted_score"] = score
        results[key] = report

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
        print(f"{key:<14}{r['n_folds']:>7}{acc:>11}{near:>18}{longt:>18}{score:>10}{marker}{flat}")
    print("-" * 70)
    print(f"  Winner: {report['best_model']}\n")


def run(args, progress_cb=None):
    validate_config()
    metrics = [args.metric] if args.metric else list(FETCHERS.keys())

    # Fetch every metric's history once — the multivariate candidates
    # (XGBoost, SARIMAX) use the OTHER metrics as cross-signal features,
    # so all 4 need to be loaded regardless of which one is being scored.
    print("Loading all metrics (needed for cross-metric features)...")
    all_history = {}
    for m in FETCHERS.keys():
        data = FETCHERS[m](args.start_year)
        all_history[m] = data["history"]
        if m in metrics:
            for n in data["notes"]:
                print(f"  ! {n}")

    all_reports = {}
    for i, metric in enumerate(metrics):
        if progress_cb:
            progress_cb(i, len(metrics), metric)
        df = all_history[metric]
        if len(df) < 18:
            print(f"  Not enough clean history ({len(df)} months) to backtest {metric} — need 18+")
            continue

        extra_signals = {k: v for k, v in all_history.items() if k != metric}
        report = select_best_model(df, metric, country=args.country, extra_signals=extra_signals)
        print_report(report)
        all_reports[metric] = report

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/backtest_report.json", "w") as f:
        json.dump(all_reports, f, indent=2, default=str)
    print("Saved outputs/backtest_report.json")

    if progress_cb:
        progress_cb(len(metrics), len(metrics), None)

    return all_reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest all candidate forecasters per metric")
    parser.add_argument("--metric", default=None, choices=list(FETCHERS.keys()))
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--country", default=HOLIDAY_COUNTRY)
    run(parser.parse_args())
