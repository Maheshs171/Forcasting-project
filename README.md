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
