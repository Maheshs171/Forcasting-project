"""
config/settings.py
───────────────────
Central configuration. Reads from .env file.
All modules import from here — never hardcode credentials.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ───────────────────────────────────────────────────────────────
SQL_SERVER   = os.getenv("SQL_SERVER")
SQL_DATABASE = os.getenv("SQL_DATABASE")
SQL_USERNAME = os.getenv("SQL_USERNAME")
SQL_PASSWORD = os.getenv("SQL_PASSWORD")
SQL_PORT     = int(os.getenv("SQL_PORT", "3342"))

# ── Table configuration ────────────────────────────────────────────────────
PATIENT_TABLE          = os.getenv("PATIENT_TABLE",          "Customers")
PATIENT_DATE_COLUMN    = os.getenv("PATIENT_DATE_COLUMN",    "CREATE_DATE")

ENCOUNTER_TABLE         = os.getenv("ENCOUNTER_TABLE",        "PATIENT_ENCOUNTERS")
ENCOUNTER_DATE_COLUMN   = os.getenv("ENCOUNTER_DATE_COLUMN",  "ENCOUNTER_DATE")

# Collections (money actually received). PMS_LEDGER also holds PAYMENT_AMOUNT
# but mixes charges/adjustments; PMS_PAYMENTS is the clean payments table.
PAYMENT_TABLE           = os.getenv("PAYMENT_TABLE",          "PMS_PAYMENTS")
PAYMENT_DATE_COLUMN     = os.getenv("PAYMENT_DATE_COLUMN",    "PAYMENT_RECEIVED_DATE")
PAYMENT_AMOUNT_COLUMN   = os.getenv("PAYMENT_AMOUNT_COLUMN",  "PAYMENT_AMOUNT")
PAYMENT_VOID_COLUMN     = os.getenv("PAYMENT_VOID_COLUMN",    "IS_VOID")

# Contact lens sales
CL_ORDER_TABLE          = os.getenv("CL_ORDER_TABLE",         "PMS_OPTICAL_ORDERS")
CL_ORDER_DATE_COLUMN    = os.getenv("CL_ORDER_DATE_COLUMN",   "ORDER_DATE")
CL_DETAIL_TABLE         = os.getenv("CL_DETAIL_TABLE",        "PMS_OPTICAL_ORDER_CONTACT_LENS_DETAILS")

# ── Forecast settings ──────────────────────────────────────────────────────
HOLIDAY_COUNTRY          = os.getenv("HOLIDAY_COUNTRY",          "US")
DEFAULT_FORECAST_MONTHS  = int(os.getenv("DEFAULT_FORECAST_MONTHS", "12"))
DEFAULT_START_YEAR       = int(os.getenv("DEFAULT_START_YEAR",      "2019"))

# ── Outlier / data-quality controls ────────────────────────────────────────
# Robust z-score threshold (median absolute deviation based) for flagging
# anomalous months in a monthly series (e.g. a migration/go-live spike).
MONTH_OUTLIER_MAD_THRESHOLD = float(os.getenv("MONTH_OUTLIER_MAD_THRESHOLD", "20.0"))

# Robust z-score threshold for flagging individual transaction amounts
# (e.g. fake/test payment entries) before they get aggregated into a month.
TXN_OUTLIER_MAD_THRESHOLD   = float(os.getenv("TXN_OUTLIER_MAD_THRESHOLD", "18.0"))

# Same idea as MONTH_OUTLIER_MAD_THRESHOLD but for weekly aggregates, which
# are naturally noisier per-bucket than monthly totals. Starts equal to the
# monthly threshold since there's no real weekly data yet to calibrate
# against — expect this to need tuning once weekly history accumulates.
WEEK_OUTLIER_MAD_THRESHOLD  = float(os.getenv("WEEK_OUTLIER_MAD_THRESHOLD", "20.0"))

# Same idea again but for daily aggregates. Calibrated empirically against
# real encounters daily history (2,131 days): at the monthly-inherited
# threshold of 20, every single "anomaly" it flagged (85 of 2131 days) was a
# real holiday or weekend with genuinely low-but-real activity (July 4th,
# Thanksgiving, Memorial Day, ordinary Saturdays/Sundays) — none were data
# artifacts. The z-score distribution's low tail caps at ~20.3 for this
# metric's minimum observed value, with a clean gap above it (0 exclusions
# at threshold 25+), so 30 comfortably clears every real-but-quiet day while
# still catching genuine spikes (a migration/import dump would produce a far
# larger value, and therefore a far larger z-score, than a quiet holiday).
DAY_OUTLIER_MAD_THRESHOLD   = float(os.getenv("DAY_OUTLIER_MAD_THRESHOLD", "30.0"))

# ── Predictions storage (MySQL) ────────────────────────────────────────────
# Where forecast/prediction REPORTS get written instead of outputs/*.json —
# see db/predictions_store.py for why (Render's filesystem is ephemeral;
# a real DB survives restarts/redeploys). Does not replace SQL_SERVER above
# — that's still the SOURCE business data (patients/encounters/payments);
# this is the DESTINATION for computed forecast results.
PREDICTIONS_DB_HOST     = os.getenv("PREDICTIONS_DB_HOST")
PREDICTIONS_DB_PORT     = int(os.getenv("PREDICTIONS_DB_PORT", "3306"))
PREDICTIONS_DB_NAME     = os.getenv("PREDICTIONS_DB_NAME")
PREDICTIONS_DB_USER     = os.getenv("PREDICTIONS_DB_USER")
PREDICTIONS_DB_PASSWORD = os.getenv("PREDICTIONS_DB_PASSWORD")

# ── Azure ML (AutoML forecasting comparison) ───────────────────────────────
# Only needed if you run azure_automl.py — the local pipeline never requires these.
AML_SUBSCRIPTION_ID = os.getenv("AML_SUBSCRIPTION_ID")
AML_RESOURCE_GROUP  = os.getenv("AML_RESOURCE_GROUP")
AML_WORKSPACE_NAME  = os.getenv("AML_WORKSPACE_NAME")
AML_COMPUTE_NAME    = os.getenv("AML_COMPUTE_NAME", "cpu-cluster")


def get_connection_string() -> dict:
    """
    Uses whichever connection is currently active in config/connections.py's
    registry (switchable at runtime from the Settings page). Falls back to
    the static .env values if no registry entry exists yet.
    """
    from config import connections
    active = connections.get_active()
    if active:
        return {
            "server":   active["server"],
            "port":     active.get("port", 3342),
            "database": active["database"],
            "user":     active.get("username"),
            "password": active.get("password"),
        }
    return {
        "server":   SQL_SERVER,
        "port":     SQL_PORT,
        "database": SQL_DATABASE,
        "user":     SQL_USERNAME,
        "password": SQL_PASSWORD,
    }


def validate():
    """Check a usable connection is configured (active registry entry or .env)."""
    from config import connections
    if connections.get_active():
        return
    missing = []
    for var in ["SQL_SERVER", "SQL_DATABASE", "SQL_USERNAME", "SQL_PASSWORD"]:
        if not os.getenv(var):
            missing.append(var)
    if missing:
        raise ValueError(
            f"Missing required settings: {missing}\n"
            f"Copy .env.example to .env and fill in your values, or add a "
            f"connection from the Settings page."
        )
