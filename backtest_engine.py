"""
backtest_engine.py
------------------
Historical base rates for MacroFlow Terminal.

This is where probabilities come from HONESTLY: instead of the AI guessing
"65% chance", we measure what actually happened. For each month in history we
label the inflation regime, then look at what a risk asset did over the next
H months, and aggregate.

Integrity note (the ALFRED point): a regime must be defined using data that
was KNOWN at the time, not later-revised numbers. v1 approximates this with a
publication lag (CPI for month M isn't public until ~M+1, so we shift the
signal forward by `lag_months`). Swapping in true ALFRED vintage data is the
v2 upgrade and drops into `monthly_regime` without touching the rest.

Pure functions, monthly frequency, testable with synthetic data.
"""

from __future__ import annotations

import pandas as pd


def monthly_regime(cpi: pd.Series, hot: float = 4.0) -> pd.Series:
    """Boolean 'inflation is HOT' per month, from 3-month annualized CPI."""
    cpi = cpi.dropna().sort_index()
    ann = ((cpi / cpi.shift(3)) ** 4 - 1) * 100
    return ann > hot


def forward_return(asset_m: pd.Series, horizon: int) -> pd.Series:
    """Forward % change of a month-end level series over `horizon` months."""
    return asset_m.shift(-horizon) / asset_m - 1.0


def _stats(returns: pd.Series) -> dict:
    if returns.empty:
        return {"n": 0, "mean_pct": None, "median_pct": None, "pct_positive": None}
    return {
        "n": int(returns.count()),
        "mean_pct": round(float(returns.mean() * 100), 2),
        "median_pct": round(float(returns.median() * 100), 2),
        "pct_positive": round(float((returns > 0).mean() * 100), 1),
    }


def backtest_regime(cpi: pd.Series, asset: pd.Series,
                    horizon_months: int = 3, lag_months: int = 1,
                    hot: float = 4.0) -> dict:
    """Forward-return base rates split by inflation regime.

    Returns {"HOT": {...stats...}, "NOT HOT": {...}, "horizon_months": H}.
    """
    cpi_m = cpi.dropna().resample("ME").last()
    asset_m = asset.dropna().resample("ME").last()

    is_hot_known = monthly_regime(cpi_m, hot).shift(lag_months)   # publication lag
    fwd = forward_return(asset_m, horizon_months)

    df = pd.DataFrame({"is_hot": is_hot_known, "fwd": fwd}).dropna()
    df["is_hot"] = df["is_hot"].astype(bool)
    return {
        "HOT":     _stats(df.fwd[df.is_hot]),
        "NOT HOT": _stats(df.fwd[~df.is_hot]),
        "horizon_months": horizon_months,
    }
