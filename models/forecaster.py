"""
models/forecaster.py
─────────────────────
Multiple candidate forecasters behind one interface. No single model is
assumed best — validate.py backtests all applicable candidates on each
metric's actual (cleaned) history and picks whichever wins on real
held-out accuracy. That winner is what predict.py uses in production.

Candidates:
  1. SeasonalNaiveForecaster — same-month-last-year baseline. Cheap,
     surprisingly hard to beat on stable seasonal data, and the sanity
     floor: if nothing else beats this, nothing else is adding value.
  2. ETSForecaster            — Holt-Winters exponential smoothing.
     Usually the strongest classical method on short (<5yr) monthly
     business series with trend + seasonality.
  3. SARIMAForecaster         — auto ARIMA/SARIMA. Statistical gold
     standard on longer, stable series (needs 24+ months).
  4. ProphetForecaster        — additive/multiplicative seasonality +
     holidays. Good when holiday effects matter and data has gaps.
  5. XGBoostForecaster        — multi-column: calendar features, the
     target's own lags/rolling averages, AND lagged values of the other
     3 metrics as cross-signal features. Only wins the backtest if those
     extra columns actually reduce real forecast error.
  6. SARIMAXForecaster        — SARIMA plus exogenous columns (holiday
     count + lagged cross-metric signals) instead of just the bare series.

Models 1-4 only ever see (ds, y). Models 5-6 are the multivariate
candidates — they accept an `extra_signals` dict of the other metrics'
history and decide, via the same backtest, whether that extra
information is actually worth anything.

All return a ForecastResult with the same shape.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

from dataclasses import dataclass, field


@dataclass
class ForecastResult:
    model_name: str
    metric:     str
    historical: pd.DataFrame
    future:     pd.DataFrame          # ds, yhat, yhat_lower, yhat_upper
    warnings:   list = field(default_factory=list)

    def to_list(self) -> list:
        return [
            {
                "month":     r["ds"].strftime("%Y-%m"),
                "label":     r["ds"].strftime("%b %Y"),
                "predicted": float(r["yhat"]),
                "low":       float(r["yhat_lower"]),
                "high":      float(r["yhat_upper"]),
            }
            for _, r in self.future.iterrows()
        ]


class SeasonalNaiveForecaster:
    name = "Seasonal naive (same month last year)"
    min_months = 12

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", **kwargs) -> ForecastResult:
        warns = []
        if len(df) < 12:
            warns.append(f"Only {len(df)} months — seasonal naive needs 12+")

        last_ds = df["ds"].max()
        future_dates = pd.date_range(start=last_ds + pd.DateOffset(months=1), periods=periods, freq="MS")

        yoy_changes = (df["y"] - df["y"].shift(12)).dropna()
        yoy_std = float(yoy_changes.std()) if len(yoy_changes) >= 2 else float(df["y"].std() or 0)
        yoy_std = 0.0 if pd.isna(yoy_std) else yoy_std

        yhats = []
        for target in future_dates:
            year_ago = target - pd.DateOffset(years=1)
            match = df[df["ds"] == year_ago]
            if not match.empty:
                yhats.append(float(match["y"].iloc[0]))
            else:
                yhats.append(float(df["y"].tail(3).mean()))

        yhats = np.array(yhats, dtype=float)
        return ForecastResult(
            model_name=self.name, metric=metric, historical=df,
            future=pd.DataFrame({
                "ds": future_dates,
                "yhat": yhats,
                "yhat_lower": np.clip(yhats - 1.96 * yoy_std, 0, None),
                "yhat_upper": yhats + 1.96 * yoy_std,
            }),
            warnings=warns,
        )


class ETSForecaster:
    name = "ETS (Holt-Winters)"
    min_months = 12

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", **kwargs) -> ForecastResult:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        warns = []
        if len(df) < 24:
            warns.append(f"Only {len(df)} months — seasonal ETS is more reliable with 24+")

        y = df["y"].values.astype(float)
        use_seasonal = len(df) >= 24
        # additive trend/season is safer than multiplicative when series can hit 0
        model = ExponentialSmoothing(
            y,
            trend="add",
            seasonal="add" if use_seasonal else None,
            seasonal_periods=12 if use_seasonal else None,
            initialization_method="estimated",
        )
        fit = model.fit(optimized=True)
        fc = fit.forecast(periods)

        resid_std = float(np.std(fit.resid)) if len(fit.resid) else float(y.std())
        last_ds = df["ds"].max()
        future_dates = pd.date_range(start=last_ds + pd.DateOffset(months=1), periods=periods, freq="MS")

        yhat = np.clip(fc, 0, None)
        return ForecastResult(
            model_name=self.name, metric=metric, historical=df,
            future=pd.DataFrame({
                "ds": future_dates,
                "yhat": yhat,
                "yhat_lower": np.clip(yhat - 1.96 * resid_std, 0, None),
                "yhat_upper": yhat + 1.96 * resid_std,
            }),
            warnings=warns,
        )


class SARIMAForecaster:
    name = "Auto-SARIMA"
    min_months = 24

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", **kwargs) -> ForecastResult:
        from pmdarima import auto_arima

        warns = []
        if len(df) < 24:
            warns.append(f"Only {len(df)} months — SARIMA needs 24+ for seasonal detection")

        seasonal = len(df) >= 24
        model = auto_arima(
            df["y"], seasonal=seasonal, m=12 if seasonal else 1,
            stepwise=True, suppress_warnings=True, error_action="ignore",
            information_criterion="aic",
        )
        fc, conf = model.predict(n_periods=periods, return_conf_int=True, alpha=0.05)

        last_ds = df["ds"].max()
        future_dates = pd.date_range(start=last_ds + pd.DateOffset(months=1), periods=periods, freq="MS")

        yhat = np.clip(np.asarray(fc), 0, None)
        return ForecastResult(
            model_name=self.name, metric=metric, historical=df,
            future=pd.DataFrame({
                "ds": future_dates,
                "yhat": yhat,
                "yhat_lower": np.clip(conf[:, 0], 0, None),
                "yhat_upper": conf[:, 1],
            }),
            warnings=warns,
        )


class ProphetForecaster:
    name = "Prophet"
    min_months = 12

    def __init__(self, country: str = "US"):
        self.country = country

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", **kwargs) -> ForecastResult:
        from prophet import Prophet

        warns = []
        if len(df) < 12:
            warns.append(f"Only {len(df)} months — Prophet needs 12+ for seasonality")

        yearly = len(df) >= 24
        model = Prophet(
            yearly_seasonality=yearly,
            weekly_seasonality=False,
            daily_seasonality=False,
            seasonality_mode="additive",
            interval_width=0.95,
        )
        try:
            model.add_country_holidays(country_name=self.country)
        except Exception as e:
            warns.append(f"Holidays not loaded: {e}")

        model.fit(df[["ds", "y"]])
        future = model.make_future_dataframe(periods=periods, freq="MS")
        forecast = model.predict(future)

        last = df["ds"].max()
        fut = forecast[forecast["ds"] > last][["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
        fut["yhat"] = fut["yhat"].clip(0)
        fut["yhat_lower"] = fut["yhat_lower"].clip(0)
        fut["yhat_upper"] = fut["yhat_upper"].clip(0)

        return ForecastResult(
            model_name=self.name, metric=metric, historical=df,
            future=fut.reset_index(drop=True), warnings=warns,
        )


class XGBoostForecaster:
    """
    Multi-column: calendar features, the target's own lags/rolling
    averages, and lagged values of the other 3 metrics as cross-signal
    features. is_multivariate=True tells validate.py/predict.py to build
    and pass the extra_signals dict.
    """
    name = "XGBoost (multi-feature)"
    min_months = 24
    is_multivariate = True

    def __init__(self, n_estimators=300, learning_rate=0.05, max_depth=4, country: str = "US"):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.country = country

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", extra_signals: dict = None, **kwargs) -> ForecastResult:
        from xgboost import XGBRegressor
        from utils.multifeatures import build_feature_matrix, get_feature_columns, build_future_row, get_holiday_dates

        extra_signals = extra_signals or {}
        warns = []
        if len(df) < 24:
            warns.append(f"Only {len(df)} months — XGBoost is more reliable with 24+")

        holiday_set = get_holiday_dates(self.country)
        df_full = build_feature_matrix(df, extra_signals, holiday_set)
        feat_cols = get_feature_columns(df_full)
        df_train = df_full.dropna(subset=feat_cols).copy()

        if len(df_train) < 6:
            raise ValueError("Not enough data after feature engineering for XGBoost (need 24+ months).")

        X = df_train[feat_cols].values
        y = df_train["y"].values

        model = XGBRegressor(
            n_estimators=self.n_estimators, learning_rate=self.learning_rate, max_depth=self.max_depth,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=3, random_state=42, verbosity=0,
        )
        model.fit(X, y)
        resid_std = float(np.std(y - model.predict(X)))

        history_y = list(df["y"])
        last_ds = df["ds"].max()
        year_min = int(df["ds"].dt.year.min())
        other_history = {name: list(sig["y"]) if not sig.empty else [0] for name, sig in extra_signals.items()}

        predictions = []
        for step in range(1, periods + 1):
            row = build_future_row(step, last_ds, history_y, other_history, holiday_set, year_min, feat_cols)
            pred = max(0.0, float(model.predict(row)[0]))
            predictions.append({
                "ds": last_ds + pd.DateOffset(months=step),
                "yhat": pred,
                "yhat_lower": max(0.0, pred - 1.96 * resid_std),
                "yhat_upper": pred + 1.96 * resid_std,
            })
            history_y.append(pred)
            for name in other_history:
                other_history[name].append(other_history[name][-1])

        return ForecastResult(
            model_name=self.name, metric=metric, historical=df,
            future=pd.DataFrame(predictions), warnings=warns,
        )


class SARIMAXForecaster:
    """
    SARIMA's own AR/seasonal structure plus exogenous columns (holiday
    count + lagged cross-metric signals) instead of just the bare series.
    """
    name = "SARIMAX (multi-feature)"
    min_months = 24
    is_multivariate = True

    def __init__(self, country: str = "US"):
        self.country = country

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", extra_signals: dict = None, **kwargs) -> ForecastResult:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        from utils.multifeatures import build_feature_matrix, get_holiday_dates

        extra_signals = extra_signals or {}
        warns = []
        if len(df) < 24:
            warns.append(f"Only {len(df)} months — SARIMAX is more reliable with 24+")

        holiday_set = get_holiday_dates(self.country)
        df_full = build_feature_matrix(df, extra_signals, holiday_set, include_self_lags=False)
        exog_cols = [c for c in df_full.columns if c not in {"ds", "y", "month", "quarter", "year", "year_idx"}]
        df_full = df_full.dropna(subset=exog_cols).reset_index(drop=True)

        if len(df_full) < 12:
            raise ValueError("Not enough data after feature engineering for SARIMAX (need 24+ months).")

        y = df_full["y"].values.astype(float)
        exog = df_full[exog_cols].values.astype(float)
        seasonal = len(df_full) >= 24

        model = SARIMAX(
            y, exog=exog,
            order=(1, 1, 1),
            seasonal_order=(1, 1, 0, 12) if seasonal else (0, 0, 0, 0),
            enforce_stationarity=False, enforce_invertibility=False,
        )
        fit = model.fit(disp=False)

        last_ds = df_full["ds"].max()
        future_dates = pd.date_range(start=last_ds + pd.DateOffset(months=1), periods=periods, freq="MS")

        # Future exogenous rows: same calendar/holiday logic, other signals held flat
        other_history = {name: list(sig["y"]) if not sig.empty else [0] for name, sig in extra_signals.items()}
        future_rows = []
        for i, fd in enumerate(future_dates, start=1):
            row = {}
            row["month_sin"] = np.sin(2 * np.pi * fd.month / 12)
            row["month_cos"] = np.cos(2 * np.pi * fd.month / 12)
            q = (fd.month - 1) // 3 + 1
            row["q_sin"] = np.sin(2 * np.pi * q / 4)
            row["q_cos"] = np.cos(2 * np.pi * q / 4)
            from utils.multifeatures import holidays_in_month
            row["holidays_count"] = holidays_in_month(fd.year, fd.month, holiday_set)
            row["is_january"] = int(fd.month == 1)
            row["is_december"] = int(fd.month == 12)
            row["is_summer"] = int(fd.month in [6, 7, 8])
            row["is_q4"] = int(q == 4)
            for name, vals in other_history.items():
                row[f"{name}_lag1"] = vals[-1] if vals else 0
                row[f"{name}_lag3"] = vals[-3] if len(vals) >= 3 else (vals[0] if vals else 0)
                row[f"{name}_roll3"] = np.mean(vals[-3:]) if vals else 0
            future_rows.append([row.get(c, 0) for c in exog_cols])

        future_exog = np.array(future_rows, dtype=float)
        fc = fit.get_forecast(steps=periods, exog=future_exog)
        mean = fc.predicted_mean
        ci = fc.conf_int(alpha=0.05)

        yhat = np.clip(np.asarray(mean), 0, None)
        return ForecastResult(
            model_name=self.name, metric=metric, historical=df,
            future=pd.DataFrame({
                "ds": future_dates,
                "yhat": yhat,
                "yhat_lower": np.clip(np.asarray(ci[:, 0]), 0, None),
                "yhat_upper": np.asarray(ci[:, 1]),
            }),
            warnings=warns,
        )


ALL_FORECASTERS = {
    "naive":   SeasonalNaiveForecaster,
    "ets":     ETSForecaster,
    "sarima":  SARIMAForecaster,
    "prophet": ProphetForecaster,
    "xgboost": XGBoostForecaster,
    "sarimax": SARIMAXForecaster,
}
