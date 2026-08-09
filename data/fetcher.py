"""
data/fetcher.py
────────────────
Pulls only SUMMARIZED time-series data from Azure SQL MI — never full
patient-level rows. Every query here is a GROUP BY count/sum; the only
exception is the collections query, which needs individual (amount, date)
pairs (no patient/customer identifiers) to statistically filter out fake
test payments before aggregating — still not "the entire data".

Every fetcher below accepts an optional freq ("month" or "week") so the
same query shape can aggregate at either grain — this is what backs the
frequency toggle in the Data Explorer. FETCHERS (month) keeps its original
signature so every existing caller (predict.py, validate.py, backend/app.py)
is unaffected; FETCHERS_WEEKLY is the new weekly-equivalent dict.
"""

import functools
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pymssql

from config.settings import get_connection_string
from config.settings import PATIENT_TABLE, PATIENT_DATE_COLUMN
from config.settings import ENCOUNTER_TABLE, ENCOUNTER_DATE_COLUMN
from config.settings import PAYMENT_TABLE, PAYMENT_DATE_COLUMN, PAYMENT_AMOUNT_COLUMN, PAYMENT_VOID_COLUMN
from config.settings import CL_ORDER_TABLE, CL_ORDER_DATE_COLUMN, CL_DETAIL_TABLE
from config.settings import MONTH_OUTLIER_MAD_THRESHOLD, WEEK_OUTLIER_MAD_THRESHOLD, DAY_OUTLIER_MAD_THRESHOLD, TXN_OUTLIER_MAD_THRESHOLD
from utils.outliers import clean_monthly_series, flag_anomalous_transactions
from data.cache import save_cache, load_cache, cache_age_str


def _with_local_cache(metric_key: str):
    """
    Wraps a get_X_monthly(start_year, freq) fetcher so the DB is always
    tried first, but a connection failure (VPN down, DB unreachable — the
    recurring failure mode this project has hit repeatedly) falls back to
    whatever was last successfully cached to data/cache/, instead of
    hard-failing the whole forecast/backtest run. Every successful live
    fetch refreshes the cache, so the fallback is always "the last time we
    could actually reach the DB," never stale-by-design.
    """
    def decorator(fetch_fn):
        @functools.wraps(fetch_fn)
        def wrapper(start_year: int, freq: str = "month"):
            try:
                data = fetch_fn(start_year, freq)
                save_cache(metric_key, freq, data)
                return data
            except Exception as e:
                cached = load_cache(metric_key, freq)
                if cached is None:
                    raise
                age = cache_age_str(cached["_cache_meta"])
                note = f"{metric_key}: DB unreachable ({e}) — using locally cached data from {age}"
                print(f"  ! {note}")
                cached = dict(cached)
                cached["notes"] = list(cached.get("notes", [])) + [note]
                cached.setdefault("current_month", pd.DataFrame(columns=["ds", "y"]))
                return cached
        return wrapper
    return decorator


def connect():
    return pymssql.connect(**get_connection_string())


def _period_start_expr(date_col_sql: str, freq: str) -> str:
    """SQL expression truncating a datetime column to the start of its
    period. Weekly uses SQL Server's standard DATEDIFF/DATEADD week-boundary
    idiom (consistent bucket edges are what matters for aggregation — exact
    day-of-week alignment doesn't change the shape of the resulting series).
    Daily just truncates to the calendar date itself."""
    if freq == "day":
        return f"CAST({date_col_sql} AS DATE)"
    if freq == "week":
        return f"DATEADD(week, DATEDIFF(week, 0, {date_col_sql}), 0)"
    return f"DATEFROMPARTS(YEAR({date_col_sql}), MONTH({date_col_sql}), 1)"


def _group_by_expr(date_col_sql: str, freq: str) -> str:
    if freq in ("week", "day"):
        return _period_start_expr(date_col_sql, freq)
    return f"YEAR({date_col_sql}), MONTH({date_col_sql})"


def _outlier_threshold(freq: str) -> float:
    if freq == "day":
        return DAY_OUTLIER_MAD_THRESHOLD
    return WEEK_OUTLIER_MAD_THRESHOLD if freq == "week" else MONTH_OUTLIER_MAD_THRESHOLD


def _period_label(freq: str) -> str:
    if freq == "day":
        return "days"
    return "weeks" if freq == "week" else "months"


def _current_period_start(freq: str) -> pd.Timestamp:
    now = pd.Timestamp.now().normalize()
    if freq == "day":
        return now
    if freq == "week":
        return now - pd.Timedelta(days=now.dayofweek)  # Monday of the current week
    return now.replace(day=1)


def _split_complete_and_current(df: pd.DataFrame, freq: str = "month") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a periodic (ds, y) frame into (complete periods, current partial period row)."""
    cur = _current_period_start(freq)
    complete = df[df["ds"] < cur].reset_index(drop=True)
    current = df[df["ds"] == cur].reset_index(drop=True)
    return complete, current


def _run_periodic_count(sql: str, label: str, freq: str = "month") -> pd.DataFrame:
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
    print(f"  {label}: {len(df)} {_period_label(freq)} ({df['ds'].min():%b %d, %Y} -> {df['ds'].max():%b %d, %Y})")
    return df


@_with_local_cache("patients")
def get_patients_monthly(start_year: int, freq: str = "month") -> dict:
    """New patient registrations, aggregated monthly or weekly. Returns
    dict with cleaned history, the current partial period, and any
    data-quality notes."""
    col = f"[{PATIENT_DATE_COLUMN}]"
    sql = f"""
        SELECT
            {_period_start_expr(col, freq)} AS ds,
            COUNT(*) AS y
        FROM dbo.{PATIENT_TABLE}
        WHERE {col} IS NOT NULL
          AND YEAR({col}) >= {start_year}
          AND {col} <= GETDATE()
        GROUP BY {_group_by_expr(col, freq)}
        ORDER BY 1
    """
    raw = _run_periodic_count(sql, "New patients", freq)
    complete, current = _split_complete_and_current(raw, freq)
    cleaned, notes = clean_monthly_series(complete, threshold=_outlier_threshold(freq), label="patients")
    return {"history": cleaned, "current_month": current, "notes": notes, "raw": raw, "raw_monthly": complete}


@_with_local_cache("encounters")
def get_encounters_monthly(start_year: int, freq: str = "month") -> dict:
    """Clinical encounter volume, aggregated monthly or weekly."""
    col = f"[{ENCOUNTER_DATE_COLUMN}]"
    sql = f"""
        SELECT
            {_period_start_expr(col, freq)} AS ds,
            COUNT(*) AS y
        FROM dbo.{ENCOUNTER_TABLE}
        WHERE {col} IS NOT NULL
          AND YEAR({col}) >= {start_year}
          AND {col} <= GETDATE()
        GROUP BY {_group_by_expr(col, freq)}
        ORDER BY 1
    """
    raw = _run_periodic_count(sql, "Encounters", freq)
    complete, current = _split_complete_and_current(raw, freq)
    cleaned, notes = clean_monthly_series(complete, threshold=_outlier_threshold(freq), label="encounters")
    return {"history": cleaned, "current_month": current, "notes": notes, "raw": raw, "raw_monthly": complete}


@_with_local_cache("contact_lenses")
def get_contact_lenses_monthly(start_year: int, freq: str = "month") -> dict:
    """
    Contact lens orders + quantity sold, aggregated monthly or weekly.

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
    system didn't track this yet" for "zero lenses were sold that period" —
    the latter would have quietly poisoned years of the training data with
    fake zeros.
    """
    sql = f"""
        SELECT
            {_period_start_expr('effective_date', freq)} AS ds,
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
          AND effective_date <= GETDATE()
          AND YEAR(effective_date) >= {start_year}
          AND (det.QUANTITY_TO_ORDER_OD IS NOT NULL OR det.QUANTITY_TO_ORDER_OS IS NOT NULL)
        GROUP BY {_group_by_expr('effective_date', freq)}
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
    print(f"  Contact lenses: {len(df)} {_period_label(freq)} ({df['ds'].min():%b %d, %Y} -> {df['ds'].max():%b %d, %Y})")

    complete, current = _split_complete_and_current(df[["ds", "y"]], freq)
    cleaned, notes = clean_monthly_series(complete, threshold=_outlier_threshold(freq), label="contact lenses")
    return {"history": cleaned, "current_month": current, "notes": notes, "raw": df, "raw_monthly": complete}


@_with_local_cache("collections")
def get_collections_monthly(start_year: int, freq: str = "month") -> dict:
    """
    Collections (money actually received), aggregated monthly or weekly.
    Pulls individual (date, amount) pairs — no patient/customer identifiers —
    filters out statistically anomalous single transactions (fake/test
    payments), then aggregates to the requested period.
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
          AND [{PAYMENT_DATE_COLUMN}] <= GETDATE()
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

    if freq == "day":
        txns["ds"] = txns["txn_date"].dt.normalize()
    elif freq == "week":
        txns["ds"] = txns["txn_date"].dt.to_period("W").dt.start_time
    else:
        txns["ds"] = txns["txn_date"].dt.to_period("M").dt.to_timestamp()
    period = txns.groupby("ds", as_index=False)["amount"].sum().rename(columns={"amount": "y"})
    period = period.sort_values("ds").reset_index(drop=True)
    print(f"  Collections: {len(period)} {_period_label(freq)} ({period['ds'].min():%b %d, %Y} -> {period['ds'].max():%b %d, %Y})")

    complete, current = _split_complete_and_current(period, freq)
    cleaned, period_notes = clean_monthly_series(complete, threshold=_outlier_threshold(freq), label="collections")
    notes.extend(period_notes)

    return {
        "history": cleaned, "current_month": current, "notes": notes,
        "raw_daily": txns[["ds", "txn_date", "amount"]], "raw_monthly": complete,
    }


def get_daily(metric: str, start_year: int) -> pd.DataFrame:
    """
    Day-level (ds=date, y=count/amount) series used only for day-of-month
    pacing curves — never returns patient/customer identifiers. Falls back
    to a local cache on DB failure, same as the main fetchers; an unknown
    metric still raises immediately since that's a programming error, not
    a connectivity one.
    """
    if metric not in ("patients", "encounters", "collections"):
        raise ValueError(f"No daily fetcher for metric '{metric}'")
    try:
        df = _get_daily_live(metric, start_year)
        save_cache(metric, "pacing_daily", {"history": df, "notes": []})
        return df
    except Exception as e:
        cached = load_cache(metric, "pacing_daily")
        if cached is None or "history" not in cached:
            raise
        age = cache_age_str(cached["_cache_meta"])
        print(f"  ! {metric}: daily pacing data unreachable ({e}) — using locally cached data from {age}")
        return cached["history"]


def _get_daily_live(metric: str, start_year: int) -> pd.DataFrame:
    if metric == "patients":
        sql = f"""
            SELECT CAST([{PATIENT_DATE_COLUMN}] AS DATE) AS ds, COUNT(*) AS y
            FROM dbo.{PATIENT_TABLE}
            WHERE [{PATIENT_DATE_COLUMN}] IS NOT NULL AND YEAR([{PATIENT_DATE_COLUMN}]) >= {start_year}
              AND [{PATIENT_DATE_COLUMN}] <= GETDATE()
            GROUP BY CAST([{PATIENT_DATE_COLUMN}] AS DATE)
            ORDER BY 1
        """
    elif metric == "encounters":
        sql = f"""
            SELECT CAST([{ENCOUNTER_DATE_COLUMN}] AS DATE) AS ds, COUNT(*) AS y
            FROM dbo.{ENCOUNTER_TABLE}
            WHERE [{ENCOUNTER_DATE_COLUMN}] IS NOT NULL AND YEAR([{ENCOUNTER_DATE_COLUMN}]) >= {start_year}
              AND [{ENCOUNTER_DATE_COLUMN}] <= GETDATE()
            GROUP BY CAST([{ENCOUNTER_DATE_COLUMN}] AS DATE)
            ORDER BY 1
        """
    elif metric == "collections":
        void_filter = f"AND ([{PAYMENT_VOID_COLUMN}] IS NULL OR [{PAYMENT_VOID_COLUMN}] = 0)" if PAYMENT_VOID_COLUMN else ""
        sql = f"""
            SELECT CAST([{PAYMENT_DATE_COLUMN}] AS DATE) AS ds, SUM([{PAYMENT_AMOUNT_COLUMN}]) AS y
            FROM dbo.{PAYMENT_TABLE}
            WHERE [{PAYMENT_DATE_COLUMN}] IS NOT NULL AND [{PAYMENT_AMOUNT_COLUMN}] > 0
              AND YEAR([{PAYMENT_DATE_COLUMN}]) >= {start_year} AND [{PAYMENT_DATE_COLUMN}] <= GETDATE() {void_filter}
            GROUP BY CAST([{PAYMENT_DATE_COLUMN}] AS DATE)
            ORDER BY 1
        """

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

# Same 4 metrics, same dict shape, aggregated weekly/daily instead — every
# existing caller of FETCHERS keeps working unmodified; this is purely additive.
FETCHERS_WEEKLY = {k: functools.partial(f, freq="week") for k, f in FETCHERS.items()}
FETCHERS_DAILY = {k: functools.partial(f, freq="day") for k, f in FETCHERS.items()}

FETCHERS_BY_FREQUENCY = {"month": FETCHERS, "week": FETCHERS_WEEKLY, "day": FETCHERS_DAILY}
