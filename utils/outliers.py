"""
utils/outliers.py
──────────────────
Generalized, non-hardcoded anomaly detection using robust statistics
(median absolute deviation). Works for two shapes of problem:

  1. An entire MONTH in a monthly series is anomalous
     (e.g. a system migration/go-live dumping thousands of records
     into a single month that otherwise sees dozens).

  2. A single TRANSACTION amount is anomalous within a large set of
     individual values (e.g. fake/test payments like 1111111.00 mixed
     in with real payments of a few hundred dollars).

Nothing here is specific to any one dataset or date — thresholds are
config-driven (config/settings.py) so the same code keeps working as
new anomalies of the same *kind* show up in future data.
"""

import numpy as np
import pandas as pd

MAD_SCALE = 1.4826  # scales MAD to be consistent with std-dev for normal data


def _robust_z(values: np.ndarray) -> np.ndarray:
    """Robust z-scores using median absolute deviation. Works even when
    the series is skewed (money, counts) by scoring on log1p first."""
    values = np.asarray(values, dtype=float)
    x = np.log1p(np.clip(values, 0, None))
    med = np.median(x)
    mad = np.median(np.abs(x - med))
    if mad == 0:
        # Fall back to plain std if MAD collapses (e.g. mostly-constant series)
        std = x.std()
        if std == 0:
            return np.zeros_like(x)
        return (x - med) / std
    return (x - med) * MAD_SCALE / mad


def flag_anomalous_months(
    df: pd.DataFrame,
    value_col: str = "y",
    threshold: float = 6.0,
) -> pd.DataFrame:
    """
    Flags rows in a monthly (ds, value_col) DataFrame whose value is a
    robust-z outlier vs. the rest of the series. Returns the df with an
    added boolean 'is_anomaly' column — caller decides what to do with it
    (this function never silently drops data).
    """
    df = df.copy()
    if len(df) < 6:
        df["is_anomaly"] = False
        return df

    z = _robust_z(df[value_col].values)
    df["is_anomaly"] = np.abs(z) > threshold
    return df


def flag_anomalous_transactions(
    amounts: pd.Series,
    threshold: float = 8.0,
) -> pd.Series:
    """
    Flags individual transaction amounts that are robust-z outliers
    within the full set of transactions. Returns a boolean Series aligned
    to the input index. Threshold is higher than the month-level default
    because individual transactions are naturally noisier than monthly
    aggregates, and round/duplicated extreme values (test data) tend to
    sit far out in the tail regardless.
    """
    if len(amounts) < 30:
        return pd.Series(False, index=amounts.index)

    z = _robust_z(amounts.values)
    return pd.Series(np.abs(z) > threshold, index=amounts.index)


def clean_monthly_series(
    df: pd.DataFrame,
    value_col: str = "y",
    threshold: float = 6.0,
    label: str = "",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Detects anomalous months and removes them (rather than imputing),
    since an anomalous month is usually a data artifact with no real
    signal to recover. Returns (cleaned_df, list of human-readable notes).
    """
    flagged = flag_anomalous_months(df, value_col, threshold)
    notes = []
    anomalies = flagged[flagged["is_anomaly"]]
    for _, r in anomalies.iterrows():
        notes.append(
            f"{label + ': ' if label else ''}excluded {r['ds']:%b %Y} "
            f"({r[value_col]:,.0f}) as a data anomaly (robust z-score outlier, "
            f"likely a migration/import artifact rather than real activity)"
        )
    cleaned = flagged[~flagged["is_anomaly"]].drop(columns=["is_anomaly"]).reset_index(drop=True)
    return cleaned, notes
