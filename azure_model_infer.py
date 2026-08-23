"""
azure_model_infer.py
─────────────────────
Standalone inference script for Azure AutoML forecasting models — run
under venv_azure/ (a separate Python 3.11 virtual environment with
azureml-training-tabular and its pinned dependency tree installed),
NOT the main backend's environment.

Why this exists as a separate process/venv: azureml-training-tabular
pins old, narrow dependency versions (numpy<=1.23.5, scikit-learn<=1.6,
scipy<1.11, etc.) to be able to unpickle Azure AutoML's trained model
objects. The main backend runs Prophet/XGBoost/SARIMAX with much newer
numpy/scikit-learn, and forcing those to match would break the local
pipeline. Running this one step in its own venv keeps both environments
independently correct — azure_automl.py calls this via subprocess and
only ever deals with the plain JSON it prints back.

Usage:
    venv_azure/Scripts/python.exe azure_model_infer.py <model_dir> <last_date YYYY-MM-DD> <horizon> <pandas_freq>

`pandas_freq` is a pandas date-offset alias matching the series' grain —
"MS" (month-start), "W-MON" (weekly), or "D" (daily) — same values
models/forecaster.py's _freq_params() produces for each of this
project's three supported frequencies.

Prints a JSON array of `horizon` predicted values (one per period,
starting the period after last_date) to stdout on success. On failure,
prints "ERROR: <message>" to stderr and exits non-zero — the caller
(azure_automl.py) treats that as "skip this model", not a hard failure.
"""

import sys
import json


def main():
    if len(sys.argv) != 5:
        print("Usage: azure_model_infer.py <model_dir> <last_date YYYY-MM-DD> <horizon> <pandas_freq>", file=sys.stderr)
        sys.exit(2)

    model_dir, last_date, horizon, pandas_freq = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]

    try:
        import numpy as np
        import pandas as pd
        import mlflow.sklearn

        model = mlflow.sklearn.load_model(model_dir)
        last_ds = pd.Timestamp(last_date)
        future_dates = pd.date_range(start=last_ds, periods=horizon + 1, freq=pandas_freq)[1:]
        X_pred = pd.DataFrame({"ds": future_dates})
        y_query = np.repeat(np.nan, len(X_pred))
        y_pred, _ = model.forecast(X_pred, y_query)
        y_pred = [float(v) for v in np.asarray(y_pred, dtype=float)]
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(y_pred))


if __name__ == "__main__":
    main()
