"""
utils/pacing.py
─────────────────
"How much will we collect THIS month" is a different problem from
"how much will we collect in a full future month". The current month
is only partially observed, and Prophet/ARIMA/ETS all treat monthly
data as complete points — feeding them a partial month either corrupts
training (if included) or leaves the current month unestimated (if
excluded).

This builds a day-of-month pacing curve from history: on average, what
fraction of a month's eventual total is typically in by day N? Then
projects the current month's actual-so-far total forward using that
curve, instead of a naive linear day-fraction (which is wrong whenever
activity isn't uniform across the month — e.g. insurance payment
batches landing at month-end).
"""

import numpy as np
import pandas as pd


def build_pacing_curve(daily: pd.DataFrame, n_months_lookback: int = 24) -> pd.Series:
    """
    From a (ds=date, y=value) daily DataFrame, build the median cumulative
    fraction of a month's total reached by each day-of-month (1..31),
    using up to n_months_lookback recently completed months.
    Returns a Series indexed by day-of-month (1..31) -> fraction in [0,1].
    """
    if daily.empty:
        return pd.Series(dtype=float)

    daily = daily.copy()
    daily["month"] = daily["ds"].dt.to_period("M")
    daily["day"] = daily["ds"].dt.day

    current_period = pd.Timestamp.now().to_period("M")
    months = sorted(m for m in daily["month"].unique() if m < current_period)
    months = months[-n_months_lookback:] if len(months) > n_months_lookback else months
    if not months:
        return pd.Series(dtype=float)

    curves = []
    for m in months:
        month_df = daily[daily["month"] == m].sort_values("day")
        total = month_df["y"].sum()
        if total <= 0:
            continue
        days_in_month = m.days_in_month
        full_days = pd.DataFrame({"day": range(1, days_in_month + 1)})
        merged = full_days.merge(month_df[["day", "y"]], on="day", how="left").fillna(0)
        merged["cum_frac"] = merged["y"].cumsum() / total
        curves.append(merged.set_index("day")["cum_frac"])

    if not curves:
        return pd.Series(dtype=float)

    combined = pd.concat(curves, axis=1)
    return combined.median(axis=1)


def project_month_end(
    daily: pd.DataFrame,
    month_start: pd.Timestamp,
    as_of: pd.Timestamp = None,
) -> dict:
    """
    Projects the full-month total for `month_start` given data observed
    through `as_of` (defaults to now), using the historical day-of-month
    pacing curve. Returns dict with mtd_actual, projected, low, high,
    fraction_elapsed, and the number of historical months the curve is
    based on.
    """
    as_of = as_of or pd.Timestamp.now()
    curve = build_pacing_curve(daily)

    month_mask = (daily["ds"] >= month_start) & (daily["ds"] <= as_of)
    mtd_actual = float(daily.loc[month_mask, "y"].sum())

    day_n = as_of.day
    if curve.empty or day_n not in curve.index or curve.loc[day_n] <= 0:
        # Not enough history for a pacing curve — fall back to linear day-fraction
        days_in_month = pd.Period(month_start, freq="M").days_in_month
        frac = day_n / days_in_month
        n_hist = 0
    else:
        frac = float(curve.loc[day_n])
        n_hist = curve.name if hasattr(curve, "name") else None
        n_hist = None

    frac = max(frac, 0.02)  # guard against div-by-near-zero on day 1
    projected = mtd_actual / frac

    # Uncertainty band from spread of historical month-end/day-N ratios
    spread = 0.15 if curve.empty else _pacing_uncertainty(daily, month_start, as_of, curve)
    low = projected * (1 - spread)
    high = projected * (1 + spread)

    return {
        "mtd_actual": mtd_actual,
        "projected": max(projected, mtd_actual),
        "low": max(low, mtd_actual),
        "high": max(high, projected),
        "fraction_elapsed": frac,
        "as_of_day": day_n,
        "history_months_used": _n_months_in_curve(daily),
    }


def _n_months_in_curve(daily: pd.DataFrame, n_months_lookback: int = 24) -> int:
    if daily.empty:
        return 0
    current_period = pd.Timestamp.now().to_period("M")
    months = daily["ds"].dt.to_period("M").unique()
    months = [m for m in months if m < current_period]
    return min(len(months), n_months_lookback)


def _pacing_uncertainty(daily, month_start, as_of, curve, n_months_lookback=24) -> float:
    """Historical relative error of the pacing projection at this day-of-month,
    measured by replaying the same projection logic on past completed months."""
    daily = daily.copy()
    daily["month"] = daily["ds"].dt.to_period("M")
    daily["day"] = daily["ds"].dt.day
    day_n = as_of.day

    current_period = pd.Timestamp.now().to_period("M")
    months = sorted(m for m in daily["month"].unique() if m < current_period)
    months = months[-n_months_lookback:]

    errors = []
    for m in months:
        month_df = daily[daily["month"] == m]
        total = month_df["y"].sum()
        if total <= 0:
            continue
        mtd = month_df.loc[month_df["day"] <= day_n, "y"].sum()
        frac = curve.loc[day_n] if day_n in curve.index and curve.loc[day_n] > 0 else day_n / m.days_in_month
        est = mtd / max(frac, 0.02)
        if total > 0:
            errors.append(abs(est - total) / total)

    if not errors:
        return 0.15
    return float(np.clip(np.median(errors), 0.03, 0.5))
