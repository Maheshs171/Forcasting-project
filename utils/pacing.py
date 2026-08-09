"""
utils/pacing.py
─────────────────
"How much will we collect THIS period" is a different problem from
"how much will we collect in a full future period". The current period
is only partially observed, and Prophet/ARIMA/ETS all treat the series
as complete points — feeding them a partial period either corrupts
training (if included) or leaves the current period unestimated (if
excluded).

This builds a within-period pacing curve from day-level history: on
average, what fraction of a period's eventual total is typically in by
day N (day-of-month for monthly, day-of-week for weekly)? Then projects
the current period's actual-so-far total forward using that curve,
instead of a naive linear day-fraction (which is wrong whenever activity
isn't uniform across the period — e.g. insurance payment batches landing
at month-end, or clinics running lighter on Mondays than Fridays).

Daily has no equivalent here: the smallest unit tracked is already a full
day (data/fetcher.py never pulls intraday timestamps), so there's no
sub-day curve to build from — a "day" period has no internal shape to
learn. predict.py's caller only invokes this for freq in ("month", "week")
and falls back to a simple elapsed-fraction estimate for daily and for
any period unresolvable here (e.g. too little history).
"""

import numpy as np
import pandas as pd


def _period_key(ds: pd.Series, freq: str) -> pd.Series:
    """Groups timestamps into their containing period: calendar month for
    monthly, Monday-anchored week for weekly — same convention as
    data/fetcher.py's SQL week bucketing."""
    if freq == "week":
        return ds - pd.to_timedelta(ds.dt.dayofweek, unit="D")
    return ds.dt.to_period("M")


def _day_index(ds: pd.Series, freq: str) -> pd.Series:
    """Position within the period: day-of-month (1..31) for monthly,
    day-of-week (1=Monday..7=Sunday) for weekly."""
    if freq == "week":
        return ds.dt.dayofweek + 1
    return ds.dt.day


def _days_in_period(period_key, freq: str) -> int:
    if freq == "week":
        return 7
    return period_key.days_in_month


def _period_start_ts(period_key, freq: str) -> pd.Timestamp:
    if freq == "week":
        return pd.Timestamp(period_key)
    return period_key.to_timestamp()


def build_pacing_curve(daily: pd.DataFrame, freq: str = "month", n_periods_lookback: int = 24) -> pd.Series:
    """
    From a (ds=date, y=value) daily DataFrame, build the median cumulative
    fraction of a period's total reached by each day-index, using up to
    n_periods_lookback recently completed periods.
    Returns a Series indexed by day-index -> fraction in [0,1].
    """
    if daily.empty:
        return pd.Series(dtype=float)

    daily = daily.copy()
    daily["period"] = _period_key(daily["ds"], freq)
    daily["day"] = _day_index(daily["ds"], freq)

    current_period = _period_key(pd.Series([pd.Timestamp.now()]), freq).iloc[0]
    periods = sorted(p for p in daily["period"].unique() if p < current_period)
    periods = periods[-n_periods_lookback:] if len(periods) > n_periods_lookback else periods
    if not periods:
        return pd.Series(dtype=float)

    curves = []
    for p in periods:
        period_df = daily[daily["period"] == p].sort_values("day")
        total = period_df["y"].sum()
        if total <= 0:
            continue
        n_days = _days_in_period(p, freq)
        full_days = pd.DataFrame({"day": range(1, n_days + 1)})
        merged = full_days.merge(period_df[["day", "y"]], on="day", how="left").fillna(0)
        merged["cum_frac"] = merged["y"].cumsum() / total
        curves.append(merged.set_index("day")["cum_frac"])

    if not curves:
        return pd.Series(dtype=float)

    combined = pd.concat(curves, axis=1)
    return combined.median(axis=1)


def project_period_end(
    daily: pd.DataFrame,
    period_start: pd.Timestamp,
    freq: str = "month",
    as_of: pd.Timestamp = None,
) -> dict:
    """
    Projects the full-period total for `period_start` given data observed
    through `as_of` (defaults to now), using the historical within-period
    pacing curve (day-of-month for monthly, day-of-week for weekly).
    Returns dict with mtd_actual, projected, low, high, fraction_elapsed,
    and the number of historical periods the curve is based on.
    """
    as_of = as_of or pd.Timestamp.now()
    curve = build_pacing_curve(daily, freq)

    period_mask = (daily["ds"] >= period_start) & (daily["ds"] <= as_of)
    mtd_actual = float(daily.loc[period_mask, "y"].sum())

    day_n = _day_index(pd.Series([as_of]), freq).iloc[0]
    if curve.empty or day_n not in curve.index or curve.loc[day_n] <= 0:
        # Not enough history for a pacing curve — fall back to linear day-fraction
        n_days = 7 if freq == "week" else pd.Period(period_start, freq="M").days_in_month
        frac = day_n / n_days
    else:
        frac = float(curve.loc[day_n])

    frac = max(frac, 0.02)  # guard against div-by-near-zero on day 1
    projected = mtd_actual / frac

    # Uncertainty band from spread of historical month-end/day-N ratios
    spread = 0.15 if curve.empty else _pacing_uncertainty(daily, period_start, as_of, curve, freq)
    low = projected * (1 - spread)
    high = projected * (1 + spread)

    return {
        "mtd_actual": mtd_actual,
        "projected": max(projected, mtd_actual),
        "low": max(low, mtd_actual),
        "high": max(high, projected),
        "fraction_elapsed": frac,
        "as_of_day": int(day_n),
        "history_months_used": _n_periods_in_curve(daily, freq),
    }


# Backward-compatible monthly-only wrapper — existing callers keep working
# unmodified with the exact same behavior as before.
def project_month_end(daily: pd.DataFrame, month_start: pd.Timestamp, as_of: pd.Timestamp = None) -> dict:
    return project_period_end(daily, month_start, freq="month", as_of=as_of)


def _n_periods_in_curve(daily: pd.DataFrame, freq: str = "month", n_periods_lookback: int = 24) -> int:
    if daily.empty:
        return 0
    current_period = _period_key(pd.Series([pd.Timestamp.now()]), freq).iloc[0]
    periods = daily["ds"].pipe(lambda s: _period_key(s, freq)).unique()
    periods = [p for p in periods if p < current_period]
    return min(len(periods), n_periods_lookback)


def _pacing_uncertainty(daily, period_start, as_of, curve, freq: str = "month", n_periods_lookback: int = 24) -> float:
    """Historical relative error of the pacing projection at this day-index,
    measured by replaying the same projection logic on past completed periods."""
    daily = daily.copy()
    daily["period"] = _period_key(daily["ds"], freq)
    daily["day"] = _day_index(daily["ds"], freq)
    day_n = _day_index(pd.Series([as_of]), freq).iloc[0]

    current_period = _period_key(pd.Series([pd.Timestamp.now()]), freq).iloc[0]
    periods = sorted(p for p in daily["period"].unique() if p < current_period)
    periods = periods[-n_periods_lookback:]

    errors = []
    for p in periods:
        period_df = daily[daily["period"] == p]
        total = period_df["y"].sum()
        if total <= 0:
            continue
        n_days = _days_in_period(p, freq)
        mtd = period_df.loc[period_df["day"] <= day_n, "y"].sum()
        frac = curve.loc[day_n] if day_n in curve.index and curve.loc[day_n] > 0 else day_n / n_days
        est = mtd / max(frac, 0.02)
        if total > 0:
            errors.append(abs(est - total) / total)

    if not errors:
        return 0.15
    return float(np.clip(np.median(errors), 0.03, 0.5))
