"""
utils/multifeatures.py
────────────────────────
Feature engineering for the multivariate candidates (XGBoost, SARIMAX).
Turns the plain (ds, y) monthly series into a feature matrix using:
  - Calendar features (month/quarter, cyclical encoding, holiday count)
  - The target's own lag/rolling history
  - Other metrics' history as cross-signals (lagged only — never the
    same or future month — so nothing here can leak future information
    into a backtest fold)

This only exists for the two models that can actually use multiple
columns. The univariate models (Naive/ETS/SARIMA/Prophet) never touch
this file — they only ever see (ds, y).
"""

import numpy as np
import pandas as pd


def get_holiday_dates(country: str = "US") -> set:
    try:
        import holidays as hol
        years = range(2016, 2030)
        return set(hol.country_holidays(country, years=years).keys())
    except Exception:
        return set()


def holidays_in_month(year: int, month: int, holiday_set: set) -> int:
    return sum(1 for h in holiday_set if getattr(h, "year", None) == year and getattr(h, "month", None) == month)


def build_feature_matrix(
    df_target: pd.DataFrame,
    other_series: dict[str, pd.DataFrame],
    holiday_set: set,
    include_self_lags: bool = True,
) -> pd.DataFrame:
    """
    df_target: (ds, y) — the metric being forecast
    other_series: {metric_name: (ds, y) df} — the other metrics, used only
                  as lagged/rolling cross-signals (never same-month values)
    """
    df = df_target.copy().sort_values("ds").reset_index(drop=True)

    df["month"] = df["ds"].dt.month
    df["quarter"] = df["ds"].dt.quarter
    df["year"] = df["ds"].dt.year
    df["year_idx"] = df["year"] - df["year"].min()
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["q_sin"] = np.sin(2 * np.pi * df["quarter"] / 4)
    df["q_cos"] = np.cos(2 * np.pi * df["quarter"] / 4)
    df["holidays_count"] = df.apply(lambda r: holidays_in_month(int(r["year"]), int(r["month"]), holiday_set), axis=1)
    df["is_january"] = (df["month"] == 1).astype(int)
    df["is_december"] = (df["month"] == 12).astype(int)
    df["is_summer"] = df["month"].isin([6, 7, 8]).astype(int)
    df["is_q4"] = (df["quarter"] == 4).astype(int)
    # Day-of-week cyclical features — the dominant signal for daily data
    # (e.g. clinic volume Mon vs. Sun). Harmless no-signal constants for
    # monthly/weekly data (every row lands on the 1st / a fixed weekday), so
    # left unconditional rather than threaded through as a freq branch.
    dow = df["ds"].dt.dayofweek
    df["dow"] = dow
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    df["is_weekend"] = dow.isin([5, 6]).astype(int)

    if include_self_lags:
        for lag in [1, 2, 3, 6, 12]:
            df[f"self_lag_{lag}"] = df["y"].shift(lag)
        df["self_roll_3"] = df["y"].shift(1).rolling(3, min_periods=1).mean()
        df["self_roll_6"] = df["y"].shift(1).rolling(6, min_periods=1).mean()
        df["self_roll_12"] = df["y"].shift(1).rolling(12, min_periods=1).mean()
        df["self_mom_pct"] = df["y"].pct_change(1).fillna(0).clip(-1, 2)
        df["self_yoy"] = df["y"].shift(12)

    for name, sig_df in other_series.items():
        if sig_df is None or sig_df.empty:
            continue
        sig = sig_df[["ds", "y"]].rename(columns={"y": name})
        df = df.merge(sig, on="ds", how="left")
        df[name] = df[name].fillna(0)
        # Only lagged/rolling values of other signals — never the same-month
        # value, since that wouldn't be known yet when forecasting the future.
        df[f"{name}_lag1"] = df[name].shift(1).fillna(0)
        df[f"{name}_lag3"] = df[name].shift(3).fillna(0)
        df[f"{name}_roll3"] = df[name].shift(1).rolling(3, min_periods=1).mean()
        df = df.drop(columns=[name])

    return df


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in {"ds", "y"}]


def build_future_row(
    step: int,
    last_ds: pd.Timestamp,
    history_y: list,
    other_history: dict[str, list],
    holiday_set: set,
    year_min: int,
    feature_cols: list[str],
    include_self_lags: bool = True,
    offset_kwarg: str = "months",
) -> pd.DataFrame:
    """
    Builds one future feature row for iterative forecasting. Other metrics'
    future values aren't known, so their lag features are carried forward
    from the last known actual (held flat) — a standard, leakage-free
    simplification for exogenous inputs in iterative forecasting.

    offset_kwarg: "months" or "weeks" — steps last_ds forward by the right
    unit for the series' frequency. The self-lag windows below ([1,2,3,6,12])
    keep the same numbers either way — for weekly data they're no longer
    literally "a year ago", just shorter-horizon lagged predictors, which the
    backtest is free to reward or reject on their own merit.
    """
    next_ds = last_ds + pd.DateOffset(**{offset_kwarg: step})
    month, year = next_ds.month, next_ds.year
    quarter = (month - 1) // 3 + 1

    dow = next_ds.dayofweek
    row = {
        "month": month, "quarter": quarter, "year": year, "year_idx": year - year_min,
        "month_sin": np.sin(2 * np.pi * month / 12), "month_cos": np.cos(2 * np.pi * month / 12),
        "q_sin": np.sin(2 * np.pi * quarter / 4), "q_cos": np.cos(2 * np.pi * quarter / 4),
        "holidays_count": holidays_in_month(year, month, holiday_set),
        "is_january": int(month == 1), "is_december": int(month == 12),
        "is_summer": int(month in [6, 7, 8]), "is_q4": int(quarter == 4),
        "dow": dow, "dow_sin": np.sin(2 * np.pi * dow / 7), "dow_cos": np.cos(2 * np.pi * dow / 7),
        "is_weekend": int(dow in (5, 6)),
    }

    if include_self_lags:
        n = len(history_y)
        for lag in [1, 2, 3, 6, 12]:
            row[f"self_lag_{lag}"] = history_y[-lag] if n >= lag else history_y[0]
        row["self_roll_3"] = np.mean(history_y[-3:])
        row["self_roll_6"] = np.mean(history_y[-6:])
        row["self_roll_12"] = np.mean(history_y[-12:])
        row["self_mom_pct"] = (history_y[-1] - history_y[-2]) / max(abs(history_y[-2]), 1) if n >= 2 else 0
        row["self_yoy"] = history_y[-12] if n >= 12 else history_y[0]

    for name, vals in other_history.items():
        ns = len(vals)
        last_val = vals[-1] if ns >= 1 else 0
        row[f"{name}_lag1"] = last_val
        row[f"{name}_lag3"] = vals[-3] if ns >= 3 else (vals[0] if ns else 0)
        row[f"{name}_roll3"] = np.mean(vals[-3:]) if ns >= 1 else 0

    return pd.DataFrame([{k: row.get(k, 0) for k in feature_cols}])
