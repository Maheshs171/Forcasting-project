"""
data/fetcher.py
────────────────
Pulls only SUMMARIZED time-series data from Azure SQL MI — never full
patient-level rows. Every query here is a GROUP BY count/sum; the only
exception is the collections query, which needs individual (amount, date)
pairs (no patient/customer identifiers) to statistically filter out fake
test payments before aggregating — still not "the entire data".
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pymssql

from config.settings import get_connection_string
from config.settings import PATIENT_TABLE, PATIENT_DATE_COLUMN
from config.settings import ENCOUNTER_TABLE, ENCOUNTER_DATE_COLUMN
from config.settings import PAYMENT_TABLE, PAYMENT_DATE_COLUMN, PAYMENT_AMOUNT_COLUMN, PAYMENT_VOID_COLUMN
from config.settings import CL_ORDER_TABLE, CL_ORDER_DATE_COLUMN, CL_DETAIL_TABLE
from config.settings import MONTH_OUTLIER_MAD_THRESHOLD, TXN_OUTLIER_MAD_THRESHOLD
from utils.outliers import clean_monthly_series, flag_anomalous_transactions


def connect():
    return pymssql.connect(**get_connection_string())


def _current_month_start() -> pd.Timestamp:
    return pd.Timestamp.now().normalize().replace(day=1)


def _split_complete_and_current(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a monthly (ds, y) frame into (complete months, current partial month row)."""
    cur = _current_month_start()
    complete = df[df["ds"] < cur].reset_index(drop=True)
    current = df[df["ds"] == cur].reset_index(drop=True)
    return complete, current


def _run_monthly_count(sql: str, label: str) -> pd.DataFrame:
    conn = connect()
    try:
        df = pd.read_sql(sql, conn)
    finally:
        conn.close()

    if df.empty:
        print(f"  WARNING: No data returned for {label}")
        return pd.DataFrame(columns=["ds", "y"])

    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = pd.to_numeric(df["y"], errors="coerce").fillna(0)
    df = df.sort_values("ds").reset_index(drop=True)
    print(f"  {label}: {len(df)} months ({df['ds'].min():%b %Y} -> {df['ds'].max():%b %Y})")
    return df


def get_patients_monthly(start_year: int) -> dict:
    """Monthly new patient registrations. Returns dict with cleaned history,
    the current partial month, and any data-quality notes."""
    sql = f"""
        SELECT
            DATEFROMPARTS(YEAR([{PATIENT_DATE_COLUMN}]), MONTH([{PATIENT_DATE_COLUMN}]), 1) AS ds,
            COUNT(*) AS y
        FROM dbo.{PATIENT_TABLE}
        WHERE [{PATIENT_DATE_COLUMN}] IS NOT NULL
          AND YEAR([{PATIENT_DATE_COLUMN}]) >= {start_year}
        GROUP BY YEAR([{PATIENT_DATE_COLUMN}]), MONTH([{PATIENT_DATE_COLUMN}])
        ORDER BY 1
    """
    raw = _run_monthly_count(sql, "New patients")
    complete, current = _split_complete_and_current(raw)
    cleaned, notes = clean_monthly_series(complete, threshold=MONTH_OUTLIER_MAD_THRESHOLD, label="patients")
    return {"history": cleaned, "current_month": current, "notes": notes, "raw": raw, "raw_monthly": complete}


def get_encounters_monthly(start_year: int) -> dict:
    """Monthly clinical encounter volume."""
    sql = f"""
        SELECT
            DATEFROMPARTS(YEAR([{ENCOUNTER_DATE_COLUMN}]), MONTH([{ENCOUNTER_DATE_COLUMN}]), 1) AS ds,
            COUNT(*) AS y
        FROM dbo.{ENCOUNTER_TABLE}
        WHERE [{ENCOUNTER_DATE_COLUMN}] IS NOT NULL
          AND YEAR([{ENCOUNTER_DATE_COLUMN}]) >= {start_year}
        GROUP BY YEAR([{ENCOUNTER_DATE_COLUMN}]), MONTH([{ENCOUNTER_DATE_COLUMN}])
        ORDER BY 1
    """
    raw = _run_monthly_count(sql, "Encounters")
    complete, current = _split_complete_and_current(raw)
    cleaned, notes = clean_monthly_series(complete, threshold=MONTH_OUTLIER_MAD_THRESHOLD, label="encounters")
    return {"history": cleaned, "current_month": current, "notes": notes, "raw": raw, "raw_monthly": complete}


def get_contact_lenses_monthly(start_year: int) -> dict:
    """
    Monthly contact lens orders + quantity sold.

    ORDER_DATE is a placeholder default (1900-01-01) on ~48% of rows —
    those orders were never actually missing, just recorded through a path
    that didn't populate that column. CREATE_DATE holds the real date for
    99.8% of those rows, so it's used as a fallback whenever ORDER_DATE is
    the sentinel value.

    Separately (and this matters more): QUANTITY_TO_ORDER_OD/OS — the
    actual "units sold" number this metric forecasts — was never captured
    by the source system before ~2023, for every row regardless of which
    date column is used. Rows with no quantity captured are excluded
    entirely (not counted as zero) so the model never mistakes "the
    system didn't track this yet" for "zero lenses were sold that month" —
    the latter would have quietly poisoned years of the training data with
    fake zeros.
    """
    sql = f"""
        SELECT
            DATEFROMPARTS(YEAR(effective_date), MONTH(effective_date), 1) AS ds,
            COUNT(DISTINCT ord.ORDER_ID) AS orders,
            SUM(COALESCE(det.QUANTITY_TO_ORDER_OD, 0) + COALESCE(det.QUANTITY_TO_ORDER_OS, 0)) AS y
        FROM dbo.{CL_DETAIL_TABLE} det
        INNER JOIN dbo.{CL_ORDER_TABLE} ord ON det.ORDER_ID = ord.ORDER_ID
        CROSS APPLY (
            SELECT CASE
                WHEN ord.[{CL_ORDER_DATE_COLUMN}] IS NULL OR ord.[{CL_ORDER_DATE_COLUMN}] < '1950-01-01'
                THEN ord.CREATE_DATE
                ELSE ord.[{CL_ORDER_DATE_COLUMN}]
            END AS effective_date
        ) eff
        WHERE effective_date IS NOT NULL
          AND effective_date >= '1950-01-01'
          AND YEAR(effective_date) >= {start_year}
          AND (det.QUANTITY_TO_ORDER_OD IS NOT NULL OR det.QUANTITY_TO_ORDER_OS IS NOT NULL)
        GROUP BY YEAR(effective_date), MONTH(effective_date)
        ORDER BY 1
    """
    conn = connect()
    try:
        df = pd.read_sql(sql, conn)
    finally:
        conn.close()

    if df.empty:
        print("  WARNING: No data returned for contact lenses")
        empty = pd.DataFrame(columns=["ds", "y"])
        return {"history": empty, "current_month": empty, "notes": [], "raw": empty, "raw_monthly": empty}

    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = pd.to_numeric(df["y"], errors="coerce").fillna(0)
    df = df.sort_values("ds").reset_index(drop=True)
    print(f"  Contact lenses: {len(df)} months ({df['ds'].min():%b %Y} -> {df['ds'].max():%b %Y})")

    complete, current = _split_complete_and_current(df[["ds", "y"]])
    cleaned, notes = clean_monthly_series(complete, threshold=MONTH_OUTLIER_MAD_THRESHOLD, label="contact lenses")
    return {"history": cleaned, "current_month": current, "notes": notes, "raw": df, "raw_monthly": complete}


def get_collections_monthly(start_year: int) -> dict:
    """
    Monthly collections (money actually received).
    Pulls individual (date, amount) pairs — no patient/customer identifiers —
    filters out statistically anomalous single transactions (fake/test
    payments), then aggregates to monthly totals.
    """
    void_filter = f"AND ([{PAYMENT_VOID_COLUMN}] IS NULL OR [{PAYMENT_VOID_COLUMN}] = 0)" if PAYMENT_VOID_COLUMN else ""
    sql = f"""
        SELECT
            [{PAYMENT_DATE_COLUMN}] AS txn_date,
            [{PAYMENT_AMOUNT_COLUMN}] AS amount
        FROM dbo.{PAYMENT_TABLE}
        WHERE [{PAYMENT_DATE_COLUMN}] IS NOT NULL
          AND [{PAYMENT_AMOUNT_COLUMN}] IS NOT NULL
          AND [{PAYMENT_AMOUNT_COLUMN}] > 0
          AND YEAR([{PAYMENT_DATE_COLUMN}]) >= {start_year}
          {void_filter}
    """
    conn = connect()
    try:
        txns = pd.read_sql(sql, conn)
    finally:
        conn.close()

    if txns.empty:
        print("  WARNING: No data returned for collections")
        empty = pd.DataFrame(columns=["ds", "y"])
        return {"history": empty, "current_month": empty, "notes": [], "raw_daily": empty, "raw_monthly": empty}

    txns["txn_date"] = pd.to_datetime(txns["txn_date"])
    txns["amount"] = pd.to_numeric(txns["amount"], errors="coerce").fillna(0)

    is_outlier = flag_anomalous_transactions(txns["amount"], threshold=TXN_OUTLIER_MAD_THRESHOLD)
    notes = []
    if is_outlier.any():
        excluded = txns[is_outlier]
        notes.append(
            f"collections: excluded {int(is_outlier.sum())} transaction(s) totalling "
            f"${excluded['amount'].sum():,.2f} as statistical outliers "
            f"(likely test/fake payment entries, e.g. amounts like "
            f"{', '.join(f'${a:,.0f}' for a in excluded['amount'].head(3))})"
        )
    txns = txns[~is_outlier].copy()

    txns["ds"] = txns["txn_date"].dt.to_period("M").dt.to_timestamp()
    monthly = txns.groupby("ds", as_index=False)["amount"].sum().rename(columns={"amount": "y"})
    monthly = monthly.sort_values("ds").reset_index(drop=True)
    print(f"  Collections: {len(monthly)} months ({monthly['ds'].min():%b %Y} -> {monthly['ds'].max():%b %Y})")

    complete, current = _split_complete_and_current(monthly)
    cleaned, month_notes = clean_monthly_series(complete, threshold=MONTH_OUTLIER_MAD_THRESHOLD, label="collections")
    notes.extend(month_notes)

    return {
        "history": cleaned, "current_month": current, "notes": notes,
        "raw_daily": txns[["ds", "txn_date", "amount"]], "raw_monthly": complete,
    }


def get_daily(metric: str, start_year: int) -> pd.DataFrame:
    """
    Day-level (ds=date, y=count/amount) series used only for day-of-month
    pacing curves — never returns patient/customer identifiers.
    """
    if metric == "patients":
        sql = f"""
            SELECT CAST([{PATIENT_DATE_COLUMN}] AS DATE) AS ds, COUNT(*) AS y
            FROM dbo.{PATIENT_TABLE}
            WHERE [{PATIENT_DATE_COLUMN}] IS NOT NULL AND YEAR([{PATIENT_DATE_COLUMN}]) >= {start_year}
            GROUP BY CAST([{PATIENT_DATE_COLUMN}] AS DATE)
            ORDER BY 1
        """
    elif metric == "encounters":
        sql = f"""
            SELECT CAST([{ENCOUNTER_DATE_COLUMN}] AS DATE) AS ds, COUNT(*) AS y
            FROM dbo.{ENCOUNTER_TABLE}
            WHERE [{ENCOUNTER_DATE_COLUMN}] IS NOT NULL AND YEAR([{ENCOUNTER_DATE_COLUMN}]) >= {start_year}
            GROUP BY CAST([{ENCOUNTER_DATE_COLUMN}] AS DATE)
            ORDER BY 1
        """
    elif metric == "collections":
        void_filter = f"AND ([{PAYMENT_VOID_COLUMN}] IS NULL OR [{PAYMENT_VOID_COLUMN}] = 0)" if PAYMENT_VOID_COLUMN else ""
        sql = f"""
            SELECT CAST([{PAYMENT_DATE_COLUMN}] AS DATE) AS ds, SUM([{PAYMENT_AMOUNT_COLUMN}]) AS y
            FROM dbo.{PAYMENT_TABLE}
            WHERE [{PAYMENT_DATE_COLUMN}] IS NOT NULL AND [{PAYMENT_AMOUNT_COLUMN}] > 0
              AND YEAR([{PAYMENT_DATE_COLUMN}]) >= {start_year} {void_filter}
            GROUP BY CAST([{PAYMENT_DATE_COLUMN}] AS DATE)
            ORDER BY 1
        """
    else:
        raise ValueError(f"No daily fetcher for metric '{metric}'")

    conn = connect()
    try:
        df = pd.read_sql(sql, conn)
    finally:
        conn.close()

    if df.empty:
        return pd.DataFrame(columns=["ds", "y"])
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = pd.to_numeric(df["y"], errors="coerce").fillna(0)
    return df.sort_values("ds").reset_index(drop=True)


FETCHERS = {
    "patients":     get_patients_monthly,
    "encounters":   get_encounters_monthly,
    "collections":  get_collections_monthly,
    "contact_lenses": get_contact_lenses_monthly,
}
