# Business Forecasting System

Forecasts, from summarized/aggregated data only (never row-level patient
records):

1. **New patients / encounters** — this month, and by end of this year
2. **Collections ($)** — this month, next month, and by end of this year
3. **Contact lenses sold (units)** — till end of this year

---

## Why this isn't "just run Prophet"

- **Model selection is backtested, not assumed.** `validate.py` rolling-
  backtests four candidate models (Seasonal Naive, ETS/Holt-Winters,
  Auto-SARIMA, Prophet) on each metric's own history and scores them on
  real held-out error (MAPE), weighted 60% near-term (1-3mo ahead) / 40%
  longer-term (4-12mo ahead) since "this month / next month" questions
  matter most. `predict.py` uses whichever model actually wins for that
  metric — it differs by metric and by how much history you have.

- **The current (partial) month is never fed to the point forecaster.**
  A forecasting model treats a month as a completed data point; feeding
  it a half-finished month corrupts training. Instead, `utils/pacing.py`
  builds a day-of-month cumulative curve from history (what fraction of
  a typical month's total is normally in by day N) and projects the
  current month's actual-to-date forward through that curve — this is
  what answers "how much will we collect **this month**".

- **Data-quality anomalies are filtered statistically, not hardcoded.**
  `utils/outliers.py` uses a robust (MAD-based) z-score to flag whole
  months or individual transactions that are extreme outliers vs. the
  rest of the series — e.g. a system migration/go-live dumping thousands
  of patient records into one month, or an obviously fake test payment
  like `$1,111,111.00`. Genuine but unusual low-activity months (a slow
  COVID month, a holiday-heavy month) are *not* touched — thresholds
  were tuned against this dataset so only multi-order-of-magnitude
  artifacts get excluded (see "Data quality findings" below).

---

## Project structure

```
predict.py                Main entry point — answers the 3 business questions
validate.py                Backtests all candidate models, reports real accuracy
config/settings.py         DB connection + table/column config (reads .env)
data/fetcher.py            Summarized SQL queries only (counts/sums, no PII)
utils/outliers.py          Statistical anomaly detection (months + transactions)
utils/pacing.py            Day-of-month pacing model for current-month estimates
models/forecaster.py       SeasonalNaive / ETS / SARIMA / Prophet, one interface
utils/chart.py             Self-contained HTML chart output
outputs/                   JSON + HTML forecasts, backtest report
```

---

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env
notepad .env    # fill in DB credentials
```

Currently configured against the **QA** database
(`maximeyes-qa-centralus...`). To point at production, just change the
`SQL_SERVER` / `SQL_DATABASE` / credentials in `.env` — no code changes
needed. **Re-run `validate.py` after switching** — the best model per
metric depends on the actual data and will likely differ from QA.

---

## Predictions storage (MySQL) — required for Render / any ephemeral filesystem

By default, forecast reports are written to `outputs/*.json` on local disk.
That's fine on a machine you run yourself, but breaks on a platform whose
filesystem resets on every redeploy (Render, most container platforms) —
the dashboard would come up empty after every deploy. Setting the
`PREDICTIONS_DB_*` vars in `.env` switches report storage to a real MySQL
database instead, so results survive restarts/redeploys.

```
PREDICTIONS_DB_HOST=your-mysql-server.mysql.database.azure.com
PREDICTIONS_DB_PORT=3306
PREDICTIONS_DB_NAME=predictions_db
PREDICTIONS_DB_USER=your_mysql_user
PREDICTIONS_DB_PASSWORD=your_mysql_password
```

This is **separate** from `SQL_SERVER`/`SQL_DATABASE` above — those are the
SOURCE business data (patients/encounters/payments) the pipeline reads
FROM; `PREDICTIONS_DB_*` is the DESTINATION for computed forecast results,
and can be (and normally is) a completely different server/engine.

What's covered: `predict.py`'s per-metric summary and `azure_automl.py`'s
per-metric result (leaderboard + `forecast_detail`) — the exact JSON
`backend/app.py` already served from local files. The table
(`forecast_reports`, auto-created on first use — see
`db/predictions_store.py`) keeps only the latest report per
(source, metric, frequency), same "always shows the newest run" behavior
the file-glob lookup already had.

What's **not** covered: the downloaded Azure model binaries
(`models/azure_downloads/*.pkl` etc.) — those are multi-megabyte files
better suited to object storage than a MySQL TEXT column, and are
committed to this repo directly instead (see "Run forecast from
downloaded models" above) so they're present in any fresh deploy from git
without needing separate infrastructure.

Leaving `PREDICTIONS_DB_*` unset keeps the exact previous behavior (local
files only) — nothing about local dev changes if you don't set these.

---

## Azure AutoML setup

`azure_automl.py` submits AutoML forecasting jobs to Azure ML and — once
a job finishes — needs to load its top trials back as real models to
generate a full multi-model forecast report (same shape as the local
dashboard: model cards, donuts, comparison table, backtest table).

That model-loading step needs `azureml-training-tabular`, which pins
old, narrow-range dependency versions (numpy<=1.23.5, scikit-learn<=1.6)
that would conflict with this project's own newer Prophet/XGBoost stack
if installed locally. **The fix: that step now runs as its own Azure ML
job, on Azure's own compute, in Azure's own curated `ai-ml-automl`
environment** — see `run_scoring_job()` in `azure_automl.py` and its
job script `azure_score_job.py`. That environment is, by construction,
already able to load the models it just trained, so nothing needs
installing anywhere — not on this machine, not on Render, nowhere. The
main app process only ever submits the job, waits, and downloads back
a small JSON result.

Two real bugs surfaced building this, both worth knowing about if
`run_scoring_job()` ever needs touching again:
- The curated environment's own `pip` is broken for any install (a
  version mismatch in its vendored `pkg_resources` shim) — so nothing
  can be `pip install`ed from inside the job. `pkg_resources` itself
  (needed by `mlflow.sklearn.load_model`) is instead vendored directly
  into the job's code upload from `azure_score_vendor/` (a pure-Python
  copy pulled from an older setuptools that still ships it).
- Azure's own `ForecastingPipelineWrapper.forecast()` internally checks
  a request's grain against a `forecast_origin` dict keyed by a plain
  string — but pandas 2.0 changed `groupby([single_column])` to yield
  tuple keys instead of scalar ones, so that internal check now always
  fails for single-series models trained without an explicit grain
  column (a real regression in Azure's own runtime under newer pandas,
  not anything about this project's data). `_forecast_one_model()`
  works around it by aliasing `forecast_origin`'s keys under both
  shapes before calling `.forecast()`.

**`venv_azure/`** (Python 3.11 + a hand-pinned `azureml-training-tabular`
environment) still exists for one narrower purpose: the **"Run forecast
from downloaded models"** feature (`build_forecast_detail()` /
`run_from_downloads()`), which regenerates a report purely from
already-downloaded local model artifacts with **no Azure connection at
all** — for someone who was handed a `models/azure_downloads/` folder
without their own Azure ML access. If you only care about the live
"Train on Azure" flow (the common case, and what Render uses), you
don't need to set this up. If you do want the offline fallback too,
one-time setup (needs **Python 3.11** specifically):

```powershell
py -3.11 -m venv venv_azure
venv_azure\Scripts\python.exe -m pip install -r venv_azure_requirements.txt
```

If `py -3.11` isn't found, install it first: `winget install --id Python.Python.3.11`
(this adds Python 3.11 alongside whatever version you already use — it
doesn't replace anything). Two known gaps in this offline path's model
coverage (both fail gracefully — that model is skipped and the rest of
the top trials still populate the report): **VotingEnsemble** trials
embedding a Prophet sub-model fail to unpickle (a `cmdstanpy` version
mismatch), and anything needing MSVC Build Tools to compile from source.

---

## Run it

```powershell
# Check which model wins per metric, with real backtested accuracy numbers
python validate.py

# Generate all 4 forecasts (auto-selects best backtested model per metric)
python predict.py

# Just one metric
python predict.py --metric collections

# Force a specific model instead of auto-selection
python predict.py --metric patients --model sarima

# Forecast further out
python predict.py --end-date 2027-12-31
```

Each run prints, per metric:
- **This month**: month-to-date actual + pacing-projected full-month total
- **Next month**: model forecast
- **By end of year**: actual-so-far + this-month estimate + forecast for
  remaining months, with a 95% range

Outputs land in `outputs/`:
- `<metric>_<timestamp>.json` — full forecast + backtest detail
- `<metric>_<timestamp>.html` — interactive chart, open in any browser
- `summary_<timestamp>.json` — the combined answer to all 3 questions
- `backtest_report.json` — from `validate.py`, per-metric model comparison

---

## Data quality findings (from the QA database)

These were found and handled automatically, but are worth knowing about:

1. **Patients**: Aug 2023 shows 4,749 new patients vs. a normal ~40-85/month
   — almost certainly a system go-live/migration dump, not real patient
   acquisition. Excluded from training (per your direction).
2. **Collections**: a handful of payments in May 2026 use suspicious
   round/sequential amounts (`$5,645,678.00`, `$1,111,111.00`,
   `$2,345,678.00`...) against a normal transaction size of tens to a few
   thousand dollars — flagged as fake/test entries and excluded.
3. **The QA database contains future-dated rows** (encounter/patient dates
   several months ahead of the actual current date) — almost certainly
   test fixtures. These are excluded from both training and "current
   month" — only data through the real current month is used.
4. **This is a QA/test environment, not production** (`maximeyes-qa-*`
   server). Treat these forecasts as a validated *pipeline*, not final
   business numbers, until pointed at the production database.

Outlier sensitivity is configurable via `MONTH_OUTLIER_MAD_THRESHOLD` and
`TXN_OUTLIER_MAD_THRESHOLD` in `.env` if a future dataset needs different
tuning — check `outputs/*_notes` after a run to see exactly what got
excluded and why.

---

## Accuracy — read the backtest, not the point forecast

`validate.py` output tells you the real expected error per metric (e.g.
"±12% at 1 month ahead, ±20% at 12 months ahead") — use the low/high
range in every JSON output as the actual planning range, not the single
point number. If backtested MAPE is high for a metric, that's the data
telling you the honest limit of predictability — not a bug to hide.
