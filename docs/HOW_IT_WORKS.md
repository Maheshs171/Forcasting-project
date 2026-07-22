# How this forecasting system works

## 1. What data feeds it

Four business numbers, one per month, pulled straight from the database (never row-level
patient data):

| What we predict | Where it comes from |
|---|---|
| New patients | Count of new patient records per month |
| Encounters | Count of clinical visits per month |
| Collections | Sum of money actually received per month |
| Contact lenses sold | Sum of lens units ordered per month |

Before any of this touches a model, it gets cleaned:
- Months that are statistical freaks (like a one-time system migration dumping thousands of
  fake records into one month) get automatically detected and removed.
- Individual fake/test transactions (like a $1,111,111 test payment) get filtered out before
  they're even summed into a month.

## 2. How it decides which model to trust

There isn't one fixed model. Six different forecasting methods are tested against each other
for every business number:

1. **Seasonal Naive** — "assume this month looks like the same month last year" (simple baseline)
2. **ETS** — classic trend + seasonality smoothing
3. **SARIMA** — statistical time-series model
4. **Prophet** — Facebook's seasonality/holiday-aware model
5. **XGBoost** — machine learning model that can use extra columns (calendar, holidays,
   other business numbers as clues)
6. **SARIMAX** — SARIMA's cousin, also allowed to use those extra columns

**Training/testing process ("backtesting"):** each model is given only *past* data, asked to
predict months it hasn't seen yet, and its guesses are checked against what *actually*
happened. This repeats over many rolling time windows. Whichever model is most often right,
on real held-out months, wins — nothing is chosen by assumption.

Two safety checks run on top of that:
- **Flat-forecast detection** — if a model's "prediction" turns out to just be a flat,
  unchanging number every month (a sign it gave up on finding a real pattern), it's
  disqualified even if its raw accuracy score looked good.
- **Accuracy is shown as a plain %** — not a technical error metric, so it's usable by a
  business, not just an analyst.

## 3. How the final number actually gets built

Three pieces are combined into every headline forecast:
- **Actual so far this year** — real, already-happened numbers.
- **This month (in progress)** — estimated from a day-by-day pacing pattern learned from
  history (e.g. "by day 15, a typical month is usually 45% done"), not guessed from the
  whole-month model.
- **Future months** — the winning model's forecast for months that haven't started yet.

Add those three together and you get "by end of year." The same forecast also gives "next
month" and a rolling "next 12 months" on its own.

## 4. What columns actually feed the models

Every model starts from the same base: one row per month, with just a date and a value
(e.g. `2026-06-01, 62 patients`). The four univariate models (Naive, ETS, SARIMA, Prophet)
never see anything beyond that — by design, since that's what those methods are built to
work with.

XGBoost and SARIMAX get extra engineered columns:
- **Calendar**: month/quarter encoded as sine/cosine (so December and January read as
  "close together," not 11 apart), a US holiday count per month, and flags for
  January/December/summer/Q4.
- **Self-history**: the metric's own values 1/2/3/6/12 months ago, rolling 3/6/12-month
  averages, month-over-month % change, year-over-year value.
- **Cross-metric signals**: the *other* three metrics' values from 1 and 3 months ago (never
  the same month, since that would leak information you wouldn't actually have yet).

None of this was kept on intuition alone — it's only useful if it actually improves the
backtested accuracy for that specific metric, which is checked the same way as everything
else in step 2.

## 5. What you can see and compare in the app

- Every metric has its own dashboard: this month, next month, by year-end, growth vs. last
  year, and a full monthly chart.
- **Every model's forecast is computed and saved** — not just the winner — so you can pick
  any of the 6, compare them side-by-side in a table, or overlay them all on one chart.
- A separate "Training Pipeline" page lets you re-run the fetch → clean → train → evaluate
  process on demand and watch it happen live.
- A Settings page lets you point the whole system at a different database without touching
  code.

## In one sentence

The system doesn't guess which model is "smart" — it makes six candidates prove themselves
against real historical outcomes every time, picks whichever one actually got the closest,
and builds the headline number from real year-to-date numbers plus that model's forecast for
what hasn't happened yet.
