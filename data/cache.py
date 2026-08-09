"""
data/cache.py
──────────────
Local disk cache for every DB fetcher in data/fetcher.py. Every successful
live fetch is saved here; if the DB/VPN is unreachable, fetchers fall back
to whatever was last cached instead of hard-failing the whole forecast run.

This is a fallback, not a replacement — every fetch still tries the live DB
first, so cached data is only ever used when the DB genuinely can't be
reached, and the caller is always told (via a note in the returned dict)
that it's looking at a snapshot rather than fresh data.

Stored as one directory per (metric, freq) under data/cache/, each
DataFrame as CSV (no parquet engine is installed in this project, and CSV
needs nothing extra) plus a small JSON sidecar for notes and the cache
timestamp.
"""

import os
import json
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

# Every key a fetcher's return dict might contain that's a DataFrame worth
# persisting. Not every fetcher populates every key (e.g. only collections
# has raw_daily) — save/load just skip whatever's absent.
_DF_KEYS = ("history", "current_month", "raw", "raw_monthly", "raw_daily")


def _dir_for(metric: str, freq: str) -> str:
    return os.path.join(CACHE_DIR, f"{metric}_{freq}")


def save_cache(metric: str, freq: str, data: dict) -> None:
    """Persists a fetcher's return dict to disk. Best-effort — a cache
    write failure should never break a live fetch that otherwise succeeded,
    so errors here are swallowed (with a printed warning) rather than raised."""
    try:
        d = _dir_for(metric, freq)
        os.makedirs(d, exist_ok=True)
        for key in _DF_KEYS:
            df = data.get(key)
            if df is None or not hasattr(df, "to_csv"):
                continue
            df.to_csv(os.path.join(d, f"{key}.csv"), index=False)
        meta = {
            "notes": list(data.get("notes", [])),
            "cached_at": pd.Timestamp.now().isoformat(),
        }
        with open(os.path.join(d, "meta.json"), "w") as f:
            json.dump(meta, f)
    except Exception as e:
        print(f"  ! cache write failed for {metric}/{freq}: {e}")


def load_cache(metric: str, freq: str) -> dict | None:
    """Returns the last cached fetcher dict for (metric, freq), or None if
    nothing's been cached yet. Every DataFrame's date-like columns are
    restored to datetime (parquet round-trips these natively; the CSV
    fallback needs an explicit parse)."""
    d = _dir_for(metric, freq)
    meta_path = os.path.join(d, "meta.json")
    if not os.path.exists(meta_path):
        return None

    with open(meta_path) as f:
        meta = json.load(f)

    out = {"notes": list(meta.get("notes", []))}
    for key in _DF_KEYS:
        csv_path = os.path.join(d, f"{key}.csv")
        if not os.path.exists(csv_path):
            continue
        df = pd.read_csv(csv_path)
        for col in ("ds", "txn_date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
        out[key] = df
    out["_cache_meta"] = meta
    return out


def cache_age_str(meta: dict) -> str:
    """Human-readable age of a cache entry, e.g. '2 hours ago'."""
    try:
        cached_at = pd.Timestamp(meta["cached_at"])
    except Exception:
        return "an unknown time ago"
    delta = pd.Timestamp.now() - cached_at
    seconds = delta.total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)} minute(s) ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hour(s) ago"
    return f"{int(seconds // 86400)} day(s) ago"
