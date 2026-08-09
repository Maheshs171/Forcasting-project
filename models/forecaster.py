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


def _freq_params(freq: str) -> dict:
    """
    Single source of truth mapping a frequency key ("month"/"week"/"day" —
    same convention as data/fetcher.py's FETCHERS_BY_FREQUENCY) to
    everything a model needs to generalize: the pandas frequency alias, the
    DateOffset kwarg for stepping one period, the seasonal cycle length used
    for the model's own cyclical fitting (12 months, 52 weeks — or for
    daily, 7 days: day-of-week is the dominant, cheaply-modelable daily
    cycle, not the full ~365-day annual one, which would need far more
    history and a much slower seasonal search), how much history two full
    cycles of THAT requires, and periods_per_year — a separate constant used
    only to scale "N months of calendar time" floors to an equivalent period
    count at this frequency (365 for day, NOT the same as seasonal_period).
    """
    if freq == "day":
        return {"pandas_freq": "D", "offset_kwarg": "days", "seasonal_period": 7, "min_seasonal": 14, "periods_per_year": 365}
    if freq == "week":
        return {"pandas_freq": "W-MON", "offset_kwarg": "weeks", "seasonal_period": 52, "min_seasonal": 104, "periods_per_year": 52}
    return {"pandas_freq": "MS", "offset_kwarg": "months", "seasonal_period": 12, "min_seasonal": 24, "periods_per_year": 12}


def _step(fp: dict, n: int) -> pd.DateOffset:
    return pd.DateOffset(**{fp["offset_kwarg"]: n})


@dataclass
class ForecastResult:
    model_name: str
    metric:     str
    historical: pd.DataFrame
    future:     pd.DataFrame          # ds, yhat, yhat_lower, yhat_upper
    warnings:   list = field(default_factory=list)

    def to_list(self, freq: str = "month") -> list:
        # Weekly/daily labels need the day (multiple weeks/days share a
        # "month year" label, which would collide on any chart x-axis) —
        # monthly keeps its original format exactly, so existing displays
        # are unaffected.
        month_fmt, label_fmt = ("%Y-%m-%d", "%b %d, %Y") if freq in ("week", "day") else ("%Y-%m", "%b %Y")
        return [
            {
                "month":     r["ds"].strftime(month_fmt),
                "label":     r["ds"].strftime(label_fmt),
                "predicted": float(r["yhat"]),
                "low":       float(r["yhat_lower"]),
                "high":      float(r["yhat_upper"]),
            }
            for _, r in self.future.iterrows()
        ]


class SeasonalNaiveForecaster:
    name = "Seasonal naive (same period last year)"
    min_months = 12

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", **kwargs) -> ForecastResult:
        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        warns = []
        if len(df) < fp["seasonal_period"]:
            warns.append(f"Only {len(df)} {freq}s — seasonal naive needs {fp['seasonal_period']}+")

        last_ds = df["ds"].max()
        future_dates = pd.date_range(start=last_ds + _step(fp, 1), periods=periods, freq=fp["pandas_freq"])

        lookback = _step(fp, fp["seasonal_period"])
        yoy_changes = (df["y"] - df["y"].shift(fp["seasonal_period"])).dropna()
        yoy_std = float(yoy_changes.std()) if len(yoy_changes) >= 2 else float(df["y"].std() or 0)
        yoy_std = 0.0 if pd.isna(yoy_std) else yoy_std

        yhats = []
        for target in future_dates:
            year_ago = target - lookback
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

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — seasonal ETS is more reliable with {fp['min_seasonal']}+")

        y = df["y"].values.astype(float)
        use_seasonal = len(df) >= fp["min_seasonal"]
        # additive trend/season is safer than multiplicative when series can hit 0
        model = ExponentialSmoothing(
            y,
            trend="add",
            seasonal="add" if use_seasonal else None,
            seasonal_periods=fp["seasonal_period"] if use_seasonal else None,
            initialization_method="estimated",
        )
        fit = model.fit(optimized=True)
        fc = fit.forecast(periods)

        resid_std = float(np.std(fit.resid)) if len(fit.resid) else float(y.std())
        last_ds = df["ds"].max()
        future_dates = pd.date_range(start=last_ds + _step(fp, 1), periods=periods, freq=fp["pandas_freq"])

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

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — SARIMA needs {fp['min_seasonal']}+ for seasonal detection")

        # Seasonal search is impractically slow for auto_arima's stepwise
        # search on both weekly (m=52) AND daily data — empirically, daily's
        # smaller m=7 didn't save it: the real cost driver is the raw number
        # of observations per fit (hundreds of daily points x many backtest
        # folds), not just the seasonal period length. A live test hung for
        # ~1hr and had to be killed. Seasonal SARIMA is disabled for both,
        # same as weekly; non-seasonal ARIMA still runs and competes on the
        # same backtest.
        seasonal = freq == "month" and len(df) >= fp["min_seasonal"]
        model = auto_arima(
            df["y"], seasonal=seasonal, m=fp["seasonal_period"] if seasonal else 1,
            stepwise=True, suppress_warnings=True, error_action="ignore",
            information_criterion="aic",
        )
        fc, conf = model.predict(n_periods=periods, return_conf_int=True, alpha=0.05)

        last_ds = df["ds"].max()
        future_dates = pd.date_range(start=last_ds + _step(fp, 1), periods=periods, freq=fp["pandas_freq"])

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

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        warns = []
        if len(df) < 12:
            warns.append(f"Only {len(df)} {freq}s — Prophet needs 12+ for seasonality")

        # Yearly seasonality needs ~2 years of real calendar time regardless
        # of frequency, so it's gated on periods_per_year (365/52/12), not
        # min_seasonal (which for daily is only 2 weeks — enough to trust a
        # day-of-week pattern, nowhere near enough for an annual one).
        yearly = len(df) >= 2 * fp["periods_per_year"]
        weekly = freq == "day"  # day-of-week is the dominant daily pattern; Prophet fits it natively
        model = Prophet(
            yearly_seasonality=yearly,
            weekly_seasonality=weekly,
            daily_seasonality=False,
            seasonality_mode="additive",
            interval_width=0.95,
        )
        try:
            model.add_country_holidays(country_name=self.country)
        except Exception as e:
            warns.append(f"Holidays not loaded: {e}")

        model.fit(df[["ds", "y"]])
        future = model.make_future_dataframe(periods=periods, freq=fp["pandas_freq"])
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

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        extra_signals = extra_signals or {}
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — XGBoost is more reliable with {fp['min_seasonal']}+")

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
            row = build_future_row(step, last_ds, history_y, other_history, holiday_set, year_min, feat_cols, offset_kwarg=fp["offset_kwarg"])
            pred = max(0.0, float(model.predict(row)[0]))
            predictions.append({
                "ds": last_ds + _step(fp, step),
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


class RandomForestForecaster:
    """
    Same feature matrix as XGBoost (calendar + self-lags + cross-metric
    lags), but a scikit-learn RandomForestRegressor instead of gradient
    boosting — a different bias/variance tradeoff (averages many
    de-correlated trees rather than boosting residuals), worth backtesting
    as its own candidate rather than assumed to behave like XGBoost.
    """
    name = "Random Forest (multi-feature)"
    min_months = 24
    is_multivariate = True

    def __init__(self, n_estimators=300, max_depth=6, country: str = "US"):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.country = country

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", extra_signals: dict = None, **kwargs) -> ForecastResult:
        from sklearn.ensemble import RandomForestRegressor
        from utils.multifeatures import build_feature_matrix, get_feature_columns, build_future_row, get_holiday_dates

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        extra_signals = extra_signals or {}
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — Random Forest is more reliable with {fp['min_seasonal']}+")

        holiday_set = get_holiday_dates(self.country)
        df_full = build_feature_matrix(df, extra_signals, holiday_set)
        feat_cols = get_feature_columns(df_full)
        df_train = df_full.dropna(subset=feat_cols).copy()

        if len(df_train) < 6:
            raise ValueError("Not enough data after feature engineering for Random Forest (need 24+ months).")

        X = df_train[feat_cols].values
        y = df_train["y"].values

        model = RandomForestRegressor(
            n_estimators=self.n_estimators, max_depth=self.max_depth,
            min_samples_leaf=2, random_state=42, n_jobs=-1,
        )
        model.fit(X, y)
        resid_std = float(np.std(y - model.predict(X)))

        history_y = list(df["y"])
        last_ds = df["ds"].max()
        year_min = int(df["ds"].dt.year.min())
        other_history = {name: list(sig["y"]) if not sig.empty else [0] for name, sig in extra_signals.items()}

        predictions = []
        for step in range(1, periods + 1):
            row = build_future_row(step, last_ds, history_y, other_history, holiday_set, year_min, feat_cols, offset_kwarg=fp["offset_kwarg"])
            pred = max(0.0, float(model.predict(row)[0]))
            predictions.append({
                "ds": last_ds + _step(fp, step),
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


class ExtraTreesForecaster:
    """
    Same feature matrix again, but scikit-learn's ExtraTreesRegressor
    (Extremely Randomized Trees) — splits are chosen more randomly than
    Random Forest, which often reduces variance further on small/noisy
    tabular data like a few dozen monthly rows.
    """
    name = "Extra Trees (multi-feature)"
    min_months = 24
    is_multivariate = True

    def __init__(self, n_estimators=300, max_depth=6, country: str = "US"):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.country = country

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", extra_signals: dict = None, **kwargs) -> ForecastResult:
        from sklearn.ensemble import ExtraTreesRegressor
        from utils.multifeatures import build_feature_matrix, get_feature_columns, build_future_row, get_holiday_dates

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        extra_signals = extra_signals or {}
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — Extra Trees is more reliable with {fp['min_seasonal']}+")

        holiday_set = get_holiday_dates(self.country)
        df_full = build_feature_matrix(df, extra_signals, holiday_set)
        feat_cols = get_feature_columns(df_full)
        df_train = df_full.dropna(subset=feat_cols).copy()

        if len(df_train) < 6:
            raise ValueError("Not enough data after feature engineering for Extra Trees (need 24+ months).")

        X = df_train[feat_cols].values
        y = df_train["y"].values

        model = ExtraTreesRegressor(
            n_estimators=self.n_estimators, max_depth=self.max_depth,
            min_samples_leaf=2, random_state=42, n_jobs=-1,
        )
        model.fit(X, y)
        resid_std = float(np.std(y - model.predict(X)))

        history_y = list(df["y"])
        last_ds = df["ds"].max()
        year_min = int(df["ds"].dt.year.min())
        other_history = {name: list(sig["y"]) if not sig.empty else [0] for name, sig in extra_signals.items()}

        predictions = []
        for step in range(1, periods + 1):
            row = build_future_row(step, last_ds, history_y, other_history, holiday_set, year_min, feat_cols, offset_kwarg=fp["offset_kwarg"])
            pred = max(0.0, float(model.predict(row)[0]))
            predictions.append({
                "ds": last_ds + _step(fp, step),
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


class MLForecastForecaster:
    """
    Wraps Nixtla's mlforecast (LightGBM under the hood) — a different
    lag-feature/gradient-boosting implementation than this project's own
    XGBoostForecaster, with its own automatic lag/rolling-window feature
    generation rather than the hand-built utils/multifeatures.py pipeline.
    Backtested as an independent candidate, not assumed to behave like
    XGBoost just because both are gradient-boosted trees.
    """
    name = "mlforecast (LightGBM)"
    min_months = 24

    def __init__(self, country: str = "US"):
        self.country = country  # accepted for interface consistency; unused here

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", **kwargs) -> ForecastResult:
        from mlforecast import MLForecast
        from mlforecast.lag_transforms import RollingMean
        import lightgbm as lgb

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — mlforecast is more reliable with {fp['min_seasonal']}+")

        # mlforecast requires a fully regular index — fill any calendar gaps
        # via interpolation rather than erroring out, same defensive
        # handling the seasonal-decomposition diagnostic uses.
        clean = df[["ds", "y"]].copy().sort_values("ds")
        full_range = pd.date_range(clean["ds"].min(), clean["ds"].max(), freq=fp["pandas_freq"])
        if len(full_range) != len(clean):
            warns.append(f"filled calendar gap(s) via interpolation for mlforecast's regular-index requirement")
        clean = clean.set_index("ds").reindex(full_range).rename_axis("ds").reset_index()
        clean["y"] = clean["y"].interpolate(limit_direction="both")
        clean["unique_id"] = "series"

        if freq == "day":
            lags, roll_window = [1, 2, 3, 7, 14, 28], 7
        elif freq == "week":
            lags, roll_window = [1, 2, 3, 4, 8, 52], 4
        else:
            lags, roll_window = [1, 2, 3, 6, 12], 3
        date_features = ["dayofweek", "month", "quarter"] if freq == "day" else ["month", "quarter"]
        model = MLForecast(
            models=[lgb.LGBMRegressor(n_estimators=200, verbosity=-1, min_child_samples=5, random_state=42)],
            freq=fp["pandas_freq"],
            lags=lags,
            lag_transforms={1: [RollingMean(window_size=roll_window)]},
            date_features=date_features,
        )
        model.fit(clean[["unique_id", "ds", "y"]], fitted=True)

        # Real in-sample residual std (actual - fitted), same interval
        # convention (1.96 * std) as every other model here.
        fitted_vals = model.forecast_fitted_values()
        model_col = [c for c in fitted_vals.columns if c not in ("unique_id", "ds", "y", "h")][0]
        resid_std = float((fitted_vals["y"] - fitted_vals[model_col]).std() or 0)

        preds = model.predict(h=periods)
        col = [c for c in preds.columns if c not in ("unique_id", "ds")][0]
        yhat = np.clip(preds[col].values, 0, None)

        return ForecastResult(
            model_name=self.name, metric=metric, historical=df,
            future=pd.DataFrame({
                "ds": preds["ds"].values,
                "yhat": yhat,
                "yhat_lower": np.clip(yhat - 1.96 * resid_std, 0, None),
                "yhat_upper": yhat + 1.96 * resid_std,
            }),
            warnings=warns,
        )


class AutoTSForecaster:
    """
    Wraps the AutoTS library — its own internal AutoML search across dozens
    of classical + light ML model templates (naive baselines, statistical
    smoothing, motif/pattern-matching, linear models), each with its own
    hyperparameter search, picked by AutoTS's own internal validation.
    Philosophically similar to what this whole project already does
    (backtest many candidates, trust nothing by default) but using AutoTS's
    own model library rather than the 9 candidates already built here.
    Kept intentionally fast (small model list, few generations) since this
    gets called once per rolling-backtest fold — a slow inner AutoML search
    multiplied across ~20+ outer backtest folds would be impractical.
    """
    name = "AutoTS"
    min_months = 18

    def __init__(self, country: str = "US"):
        self.country = country  # accepted for interface consistency; unused here

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", **kwargs) -> ForecastResult:
        from autots import AutoTS

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — AutoTS is more reliable with {fp['min_seasonal']}+")

        clean = df[["ds", "y"]].copy().sort_values("ds").reset_index(drop=True)

        model = AutoTS(
            forecast_length=periods,
            frequency=fp["pandas_freq"],
            ensemble=None,
            model_list="superfast",
            max_generations=1,
            num_validations=1,
            no_negatives=True,
            verbose=-1,
        )
        model = model.fit(clean, date_col="ds", value_col="y")
        prediction = model.predict()

        yhat = prediction.forecast["y"].values
        lower = prediction.lower_forecast["y"].values
        upper = prediction.upper_forecast["y"].values

        return ForecastResult(
            model_name=f"{self.name} ({model.best_model_name})", metric=metric, historical=df,
            future=pd.DataFrame({
                "ds": prediction.forecast.index,
                "yhat": np.clip(yhat, 0, None),
                "yhat_lower": np.clip(lower, 0, None),
                "yhat_upper": np.clip(upper, 0, None),
            }).reset_index(drop=True),
            warnings=warns,
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
        from pmdarima import auto_arima
        from utils.multifeatures import build_feature_matrix, get_holiday_dates

        freq = kwargs.get("freq", "month")
        fp = _freq_params(freq)
        extra_signals = extra_signals or {}
        warns = []
        if len(df) < fp["min_seasonal"]:
            warns.append(f"Only {len(df)} {freq}s — SARIMAX is more reliable with {fp['min_seasonal']}+")

        holiday_set = get_holiday_dates(self.country)
        df_full = build_feature_matrix(df, extra_signals, holiday_set, include_self_lags=False)
        exog_cols = [c for c in df_full.columns if c not in {"ds", "y", "month", "quarter", "year", "year_idx"}]
        df_full = df_full.dropna(subset=exog_cols).reset_index(drop=True)

        if len(df_full) < 12:
            raise ValueError(f"Not enough data after feature engineering for SARIMAX (need {fp['min_seasonal']}+ {freq}s).")

        y = df_full["y"].values.astype(float)
        exog = df_full[exog_cols].values.astype(float)
        # Seasonal order is impractically slow/unstable for the state-space
        # fit on both weekly and daily data — same reasoning and same
        # empirical finding (a live daily test hung) as SARIMAForecaster
        # above. Disabled for both; non-seasonal search still runs.
        seasonal = freq == "month" and len(df_full) >= fp["min_seasonal"]

        # auto_arima's own (p,d,q) search with the exogenous matrix passed as
        # X — same AIC-driven search SARIMAForecaster uses, just with the
        # calendar/cross-metric columns along for the ride. A fixed
        # order=(1,1,1) here (the previous approach) never explored
        # alternatives and was the most likely reason SARIMAX consistently
        # underperformed every other candidate across every metric.
        fit = auto_arima(
            y, X=exog, seasonal=seasonal, m=fp["seasonal_period"] if seasonal else 1,
            stepwise=True, suppress_warnings=True, error_action="ignore",
            information_criterion="aic",
        )

        last_ds = df_full["ds"].max()
        future_dates = pd.date_range(start=last_ds + _step(fp, 1), periods=periods, freq=fp["pandas_freq"])

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
            dow = fd.dayofweek
            row["dow"] = dow
            row["dow_sin"] = np.sin(2 * np.pi * dow / 7)
            row["dow_cos"] = np.cos(2 * np.pi * dow / 7)
            row["is_weekend"] = int(dow in (5, 6))
            for name, vals in other_history.items():
                row[f"{name}_lag1"] = vals[-1] if vals else 0
                row[f"{name}_lag3"] = vals[-3] if len(vals) >= 3 else (vals[0] if vals else 0)
                row[f"{name}_roll3"] = np.mean(vals[-3:]) if vals else 0
            future_rows.append([row.get(c, 0) for c in exog_cols])

        future_exog = np.array(future_rows, dtype=float)
        fc, conf = fit.predict(n_periods=periods, X=future_exog, return_conf_int=True, alpha=0.05)

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


ALL_FORECASTERS = {
    "naive":   SeasonalNaiveForecaster,
    "ets":     ETSForecaster,
    "sarima":  SARIMAForecaster,
    "prophet": ProphetForecaster,
    "xgboost": XGBoostForecaster,
    "sarimax": SARIMAXForecaster,
    "random_forest": RandomForestForecaster,
    "extra_trees":   ExtraTreesForecaster,
    "mlforecast":    MLForecastForecaster,
    "autots":        AutoTSForecaster,
}


class EnsembleForecaster:
    """
    Blends two other candidates' forecasts with fixed inverse-error weights
    (more accurate model gets more weight) — not "average everything," just
    the two that actually proved themselves.

    Not registered in ALL_FORECASTERS: which two models to blend is decided
    dynamically per metric, only after the base 6 have already been
    backtested (see validate.py's select_best_model). This class is then
    constructed with that specific pair and run through the exact same
    rolling backtest as everything else — an ensemble is only trusted here
    if it demonstrably beats its own components on real held-out accuracy,
    never assumed to help just because "combining models" sounds safer.
    """

    def __init__(self, model_a_key: str, weight_a: float, model_b_key: str, weight_b: float, country: str = "US"):
        self.model_a_key = model_a_key
        self.model_b_key = model_b_key
        self.weight_a = weight_a
        self.weight_b = weight_b
        self.country = country
        self.name = f"Ensemble ({MODEL_SHORT_NAMES.get(model_a_key, model_a_key)} + {MODEL_SHORT_NAMES.get(model_b_key, model_b_key)})"

    def _build(self, key: str):
        cls = ALL_FORECASTERS[key]
        needs_country = key in ("prophet", "xgboost", "sarimax", "random_forest", "extra_trees")
        return cls(country=self.country) if needs_country else cls()

    def fit_predict(self, df: pd.DataFrame, periods: int, metric: str = "", extra_signals: dict = None, **kwargs) -> ForecastResult:
        result_a = self._build(self.model_a_key).fit_predict(df, periods=periods, metric=metric, extra_signals=extra_signals, **kwargs)
        result_b = self._build(self.model_b_key).fit_predict(df, periods=periods, metric=metric, extra_signals=extra_signals, **kwargs)

        fut_a = result_a.future.set_index("ds")
        fut_b = result_b.future.set_index("ds")
        common = fut_a.index.intersection(fut_b.index)
        fut_a, fut_b = fut_a.loc[common], fut_b.loc[common]

        yhat = self.weight_a * fut_a["yhat"].values + self.weight_b * fut_b["yhat"].values
        lower = self.weight_a * fut_a["yhat_lower"].values + self.weight_b * fut_b["yhat_lower"].values
        upper = self.weight_a * fut_a["yhat_upper"].values + self.weight_b * fut_b["yhat_upper"].values

        blended = pd.DataFrame({
            "ds": common,
            "yhat": np.clip(yhat, 0, None),
            "yhat_lower": np.clip(lower, 0, None),
            "yhat_upper": np.clip(upper, 0, None),
        }).reset_index(drop=True)

        warns = list(result_a.warnings) + list(result_b.warnings)
        return ForecastResult(model_name=self.name, metric=metric, historical=df, future=blended, warnings=warns)


MODEL_SHORT_NAMES = {
    "naive": "Naive", "ets": "ETS", "sarima": "SARIMA",
    "prophet": "Prophet", "xgboost": "XGBoost", "sarimax": "SARIMAX",
    "random_forest": "RandomForest", "extra_trees": "ExtraTrees", "mlforecast": "mlforecast",
    "autots": "AutoTS",
}
