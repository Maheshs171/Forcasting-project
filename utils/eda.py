"""
utils/eda.py
──────────────
Full exploratory-data-analysis report for a metric's time series, built
for the "Data Explorer" page — so a non-technical user can actually see
what the raw data looks like (distribution, outliers, gaps, seasonality,
noise) before/while models are trained on it, instead of trusting the
pipeline blindly. Works for both monthly and weekly data (freq param) so
the two can be visually compared side by side.

Reuses the same fetchers and outlier logic the real training pipeline
uses (data/fetcher.py, utils/outliers.py) so what's shown here is exactly
what the models see — never a separate/approximate view of the data.
"""

import numpy as np
import pandas as pd

from utils.outliers import _robust_z
from config.settings import MONTH_OUTLIER_MAD_THRESHOLD, WEEK_OUTLIER_MAD_THRESHOLD, DAY_OUTLIER_MAD_THRESHOLD, TXN_OUTLIER_MAD_THRESHOLD


def _f(x) -> float | None:
    """float() that turns NaN/inf/None into JSON-safe None."""
    if x is None:
        return None
    x = float(x)
    if np.isnan(x) or np.isinf(x):
        return None
    return x


def _outlier_threshold(freq: str) -> float:
    if freq == "day":
        return DAY_OUTLIER_MAD_THRESHOLD
    return WEEK_OUTLIER_MAD_THRESHOLD if freq == "week" else MONTH_OUTLIER_MAD_THRESHOLD


def _label_fmt(freq: str) -> str:
    # Weekly/daily periods need the day too — multiple weeks/days share a
    # "month year" label, which would collide/overlap on any chart x-axis
    # otherwise.
    return "%b %d, %Y" if freq in ("week", "day") else "%b %Y"


def _pandas_freq(freq: str) -> str:
    # "W-MON" generates timestamps ON Mondays (verified empirically — pandas'
    # plain "W"/"W-SUN" alias instead generates Sunday timestamps, which
    # silently produces an all-NaN reindex against our Monday-start weekly
    # data since none of the dates line up). Must match the Monday-start
    # convention data/fetcher.py produces both via SQL and via
    # .dt.to_period("W").dt.start_time for collections.
    if freq == "day":
        return "D"
    return "W-MON" if freq == "week" else "MS"


def _summary_stats(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return {}
    mean = float(values.mean())
    std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    return {
        "n": int(len(values)),
        "mean": _f(mean),
        "median": _f(np.median(values)),
        "std": _f(std),
        "min": _f(values.min()),
        "max": _f(values.max()),
        "coefficient_of_variation": _f(std / mean) if mean else None,
    }


def _find_gaps(dates: pd.Series, freq: str) -> list[str]:
    """Calendar periods between min/max that never appear in the series at all."""
    if len(dates) < 2:
        return []
    full_range = pd.date_range(dates.min(), dates.max(), freq=_pandas_freq(freq))
    present = set(dates)
    missing = [d for d in full_range if d not in present]
    return [d.strftime(_label_fmt(freq)) for d in missing]


def _histogram(values: np.ndarray, bins: int = 10) -> list[dict]:
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return []
    counts, edges = np.histogram(values, bins=min(bins, max(1, len(values))))
    return [
        {"range_low": _f(edges[i]), "range_high": _f(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]

def _month_of_year_seasonality(df: pd.DataFrame) -> list[dict]:
    """Average value per calendar month, indexed to 100 = overall average.
    >100 means that calendar month tends to run above average. Works
    unchanged for weekly data too — it just averages every week that falls
    in a given calendar month, still a meaningful comparison."""
    if df.empty:
        return []
    overall_mean = df["y"].mean()
    if not overall_mean:
        return []
    by_month = df.groupby(df["ds"].dt.month)["y"].mean()
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return [
        {"month": names[m - 1], "index": _f(100 * by_month.get(m, np.nan) / overall_mean)}
        for m in range(1, 13)
        if m in by_month.index
    ]


def _yoy_table(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    yearly = df.groupby(df["ds"].dt.year).agg(total=("y", "sum"), avg=("y", "mean"), months=("y", "count"))
    rows = []
    prev_total = None
    for year, r in yearly.iterrows():
        growth = _f(100 * (r["total"] - prev_total) / prev_total) if prev_total else None
        rows.append({
            "year": int(year), "total": _f(r["total"]), "avg_per_month": _f(r["avg"]),
            "months_present": int(r["months"]), "growth_pct_vs_prior_year": growth,
        })
        prev_total = r["total"]
    return rows


def _autocorrelation(values: np.ndarray, max_lag: int) -> list[dict]:
    s = pd.Series(values, dtype=float)
    n = len(s)
    max_lag = min(max_lag, n - 2)
    out = []
    for lag in range(1, max(max_lag, 0) + 1):
        try:
            corr = s.autocorr(lag=lag)
        except Exception:
            corr = None
        out.append({"lag": lag, "correlation": _f(corr)})
    return out


def _seasonal_decomposition(df: pd.DataFrame, freq: str) -> dict | None:
    """Additive trend/seasonal/residual split. Monthly needs >=24 points (2
    full 12-month cycles); weekly needs >=104 (2 full 52-week cycles) —
    much more history, since a "year" is a much longer stretch of weeks.
    Daily decomposes on a 7-day (day-of-week) cycle rather than the full
    ~365-day annual one — the same cheap-and-dominant-pattern tradeoff used
    for daily forecasting (see models/forecaster.py's _freq_params)."""
    period = 7 if freq == "day" else (52 if freq == "week" else 12)
    if len(df) < 2 * period:
        return None
    try:
        from statsmodels.tsa.seasonal import seasonal_decompose
        s = df.set_index("ds")["y"].asfreq(_pandas_freq(freq))
        s = s.interpolate(limit_direction="both")
        result = seasonal_decompose(s, model="additive", period=period, extrapolate_trend="freq")
        labels = [d.strftime(_label_fmt(freq)) for d in s.index]
        return {
            "labels": labels,
            "observed": [_f(v) for v in result.observed],
            "trend": [_f(v) for v in result.trend],
            "seasonal": [_f(v) for v in result.seasonal],
            "residual": [_f(v) for v in result.resid],
        }
    except Exception:
        return None


def _rolling_volatility(df: pd.DataFrame, freq: str, window: int = 3) -> list[dict]:
    if len(df) < window + 1:
        return []
    roll_mean = df["y"].rolling(window).mean()
    roll_std = df["y"].rolling(window).std()
    cv = (roll_std / roll_mean).replace([np.inf, -np.inf], np.nan)
    out = []
    for i in range(len(df)):
        if pd.isna(cv.iloc[i]):
            continue
        out.append({"month": df["ds"].iloc[i].strftime(_label_fmt(freq)), "coefficient_of_variation": _f(cv.iloc[i])})
    return out


def build_insights(metric: str, start_year: int, fetch_fn, freq: str = "month") -> dict:
    """
    fetch_fn: the FETCHERS[metric] (or FETCHERS_WEEKLY/FETCHERS_DAILY[metric])
    callable, injected so this stays decoupled from data/fetcher.py's import
    surface. freq: "month", "week", or "day" — must match what fetch_fn
    itself aggregates to.
    """
    data = fetch_fn(start_year)
    raw_monthly: pd.DataFrame = data["raw_monthly"]
    cleaned: pd.DataFrame = data["history"]
    notes: list[str] = data["notes"]

    if raw_monthly.empty:
        return {
            "metric": metric, "frequency": freq, "has_data": False, "notes": notes,
            "summary": {}, "gaps": [], "outliers": [], "histogram": [],
            "seasonality_index": [], "yoy": [], "autocorrelation": [],
            "decomposition": None, "volatility": [],
        }

    threshold = _outlier_threshold(freq)
    label_fmt = _label_fmt(freq)
    max_lag = 7 if freq == "day" else (52 if freq == "week" else 12)

    z = _robust_z(raw_monthly["y"].values)
    cleaned_months = set(cleaned["ds"]) if not cleaned.empty else set()
    outliers = []
    for i, row in raw_monthly.reset_index(drop=True).iterrows():
        is_excluded = row["ds"] not in cleaned_months
        outliers.append({
            "month": row["ds"].strftime(label_fmt),
            "value": _f(row["y"]),
            "robust_z_score": _f(z[i]),
            "excluded": bool(is_excluded),
            "flagged_severe": bool(abs(z[i]) > threshold),
        })

    report = {
        "metric": metric,
        "frequency": freq,
        "has_data": True,
        "notes": notes,
        "date_range": {
            "start": raw_monthly["ds"].min().strftime(label_fmt),
            "end": raw_monthly["ds"].max().strftime(label_fmt),
        },
        "summary_raw": _summary_stats(raw_monthly["y"].values),
        "summary_cleaned": _summary_stats(cleaned["y"].values) if not cleaned.empty else {},
        "gaps": _find_gaps(raw_monthly["ds"], freq),
        "outliers": outliers,
        "outlier_threshold": threshold,
        "histogram": _histogram(raw_monthly["y"].values),
        "seasonality_index": _month_of_year_seasonality(cleaned if not cleaned.empty else raw_monthly),
        "yoy": _yoy_table(cleaned if not cleaned.empty else raw_monthly),
        "autocorrelation": _autocorrelation((cleaned if not cleaned.empty else raw_monthly)["y"].values, max_lag),
        "decomposition": _seasonal_decomposition(cleaned if not cleaned.empty else raw_monthly, freq),
        "volatility": _rolling_volatility(cleaned if not cleaned.empty else raw_monthly, freq),
    }

    # Transaction-level detail only exists for collections (individual payments).
    if "raw_daily" in data and not data["raw_daily"].empty:
        txns = data["raw_daily"]
        amounts = txns["amount"].values
        from utils.outliers import flag_anomalous_transactions
        is_outlier = flag_anomalous_transactions(txns["amount"], threshold=TXN_OUTLIER_MAD_THRESHOLD)
        excluded = txns[is_outlier]
        report["transactions"] = {
            "total_count": int(len(txns)),
            "excluded_count": int(is_outlier.sum()),
            "excluded_total_amount": _f(excluded["amount"].sum()) if not excluded.empty else 0.0,
            "amount_histogram": _histogram(amounts),
            "top_excluded": [
                {"date": r["txn_date"].strftime("%b %d, %Y"), "amount": _f(r["amount"])}
                for _, r in excluded.sort_values("amount", ascending=False).head(10).iterrows()
            ],
            "outlier_threshold": TXN_OUTLIER_MAD_THRESHOLD,
        }

    return report
