"""
regime_engine.py
----------------
Deterministic macro-regime detection for MacroFlow Terminal.

Design principle: COMPUTE in code, then let the AI SYNTHESIZE.
The LLM never decides whether the curve is inverted or how long it's been
inverted -- this module does, deterministically, and hands the AI a fact.

Every regime flag carries its own provenance (which series, as-of date,
fetch time, and the exact rule applied), so a *derived* metric is just as
traceable as a raw FRED series.

The compute functions take plain pandas Series as input. They know nothing
about FRED or the network, which is what makes them unit-testable with
synthetic data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd


# --------------------------------------------------------------------------
# Provenance + flag containers
# --------------------------------------------------------------------------

@dataclass
class Provenance:
    """Where a single input value came from."""
    series_id: str
    source: str
    as_of: str          # date of the latest observation used (YYYY-MM-DD)
    fetched_at: str     # ISO timestamp the data was pulled


@dataclass
class RegimeFlag:
    """A single computed regime decision, fully traceable."""
    name: str
    status: str                       # ACTIVE / INACTIVE / HOT / COLD / NEUTRAL / RISK-ON / RISK-OFF / UNKNOWN
    rule: str                         # human-readable rule
    computed: dict = field(default_factory=dict)   # the actual numbers behind the call
    inputs: list[Provenance] = field(default_factory=list)

    def is_active(self) -> bool:
        return self.status not in ("INACTIVE", "NEUTRAL", "UNKNOWN")


# --------------------------------------------------------------------------
# Small numeric helpers (pure, testable)
# --------------------------------------------------------------------------

def _clean(s: pd.Series) -> pd.Series:
    return s.dropna().sort_index()


def _days_inverted(spread: pd.Series) -> int:
    """Consecutive days the spread has been < 0, ending at the latest reading.
    Returns 0 if the latest reading is not inverted."""
    spread = _clean(spread)
    if spread.empty or spread.iloc[-1] >= 0:
        return 0
    nonneg = spread[spread >= 0]
    if nonneg.empty:                      # inverted across the whole sample
        return int((spread.index[-1] - spread.index[0]).days)
    last_nonneg = nonneg.index[-1]
    return int((spread.index[-1] - last_nonneg).days)


def _change_over_days(s: pd.Series, days: int) -> Optional[float]:
    """Latest value minus the value ~`days` ago (as-of, handles weekly data)."""
    s = _clean(s)
    if len(s) < 2:
        return None
    target = s.index[-1] - pd.Timedelta(days=days)
    prior = s[s.index <= target]
    prior_val = prior.iloc[-1] if not prior.empty else s.iloc[0]
    return float(s.iloc[-1] - prior_val)


def _cpi_3m_annualized(cpi: pd.Series) -> Optional[float]:
    """3-month annualized % change of a monthly CPI index."""
    cpi = _clean(cpi)
    if len(cpi) < 4:
        return None
    latest, three_ago = cpi.iloc[-1], cpi.iloc[-4]
    return ((latest / three_ago) ** 4 - 1) * 100


def _as_of(s: pd.Series) -> str:
    s = _clean(s)
    return "" if s.empty else s.index[-1].strftime("%Y-%m-%d")


def _prov(series_id: str, s: pd.Series, fetched_at: str, source: str = "FRED") -> Provenance:
    return Provenance(series_id=series_id, source=source, as_of=_as_of(s), fetched_at=fetched_at)


# --------------------------------------------------------------------------
# Regime computations (one function each)
# --------------------------------------------------------------------------

def recession_watch(t10y2y: pd.Series, fetched_at: str, threshold_days: int = 182) -> RegimeFlag:
    """ACTIVE when the 10y-2y spread has been inverted longer than threshold_days."""
    rule = f"10y-2y inverted continuously for > {threshold_days} days"
    if _clean(t10y2y).empty:
        return RegimeFlag("Recession Watch", "UNKNOWN", rule, inputs=[_prov("T10Y2Y", t10y2y, fetched_at)])
    days = _days_inverted(t10y2y)
    latest = float(_clean(t10y2y).iloc[-1])
    status = "ACTIVE" if days > threshold_days else "INACTIVE"
    return RegimeFlag(
        "Recession Watch", status, rule,
        computed={"spread_latest": round(latest, 3), "days_inverted": days},
        inputs=[_prov("T10Y2Y", t10y2y, fetched_at)],
    )


def liquidity_stress(rrp: pd.Series, tga: pd.Series, fetched_at: str,
                     rrp_floor: float = 200.0, tga_rise: float = 100.0) -> RegimeFlag:
    """ACTIVE when RRP < floor AND TGA has risen > tga_rise over ~30 days.
    Inputs expected in $ billions (RRPONTSYD, WTREGEN)."""
    rule = f"RRP < {rrp_floor:.0f}bn AND TGA up > {tga_rise:.0f}bn in 30d"
    if _clean(rrp).empty or _clean(tga).empty:
        return RegimeFlag("Liquidity Stress", "UNKNOWN", rule,
                          inputs=[_prov("RRPONTSYD", rrp, fetched_at), _prov("WTREGEN", tga, fetched_at)])
    rrp_latest = float(_clean(rrp).iloc[-1])
    tga_30d = _change_over_days(tga, 30)
    active = (rrp_latest < rrp_floor) and (tga_30d is not None and tga_30d > tga_rise)
    return RegimeFlag(
        "Liquidity Stress", "ACTIVE" if active else "INACTIVE", rule,
        computed={"rrp_latest": round(rrp_latest, 1),
                  "tga_30d_change": None if tga_30d is None else round(tga_30d, 1)},
        inputs=[_prov("RRPONTSYD", rrp, fetched_at), _prov("WTREGEN", tga, fetched_at)],
    )


def inflation_regime(cpi: pd.Series, fetched_at: str, hot: float = 4.0, cold: float = 2.0) -> RegimeFlag:
    """HOT / COLD / NEUTRAL on 3-month annualized CPI (CPIAUCSL)."""
    rule = f"3m annualized CPI > {hot}% = HOT; < {cold}% = COLD"
    ann = _cpi_3m_annualized(cpi)
    if ann is None:
        return RegimeFlag("Inflation Regime", "UNKNOWN", rule, inputs=[_prov("CPIAUCSL", cpi, fetched_at)])
    status = "HOT" if ann > hot else "COLD" if ann < cold else "NEUTRAL"
    return RegimeFlag(
        "Inflation Regime", status, rule,
        computed={"cpi_3m_annualized_pct": round(float(ann), 2)},
        inputs=[_prov("CPIAUCSL", cpi, fetched_at)],
    )


def risk_regime(vix: pd.Series, fetched_at: str, off: float = 25.0, on: float = 15.0) -> RegimeFlag:
    """RISK-OFF / RISK-ON / NEUTRAL on the VIX (VIXCLS)."""
    rule = f"VIX > {off} = RISK-OFF; VIX < {on} = RISK-ON"
    if _clean(vix).empty:
        return RegimeFlag("Risk Regime", "UNKNOWN", rule, inputs=[_prov("VIXCLS", vix, fetched_at)])
    latest = float(_clean(vix).iloc[-1])
    status = "RISK-OFF" if latest > off else "RISK-ON" if latest < on else "NEUTRAL"
    return RegimeFlag(
        "Risk Regime", status, rule,
        computed={"vix_latest": round(latest, 2)},
        inputs=[_prov("VIXCLS", vix, fetched_at)],
    )


# --------------------------------------------------------------------------
# Orchestrator + output formatting
# --------------------------------------------------------------------------

# series each regime needs -> drives your fetch layer
REQUIRED_SERIES = ["T10Y2Y", "RRPONTSYD", "WTREGEN", "CPIAUCSL", "VIXCLS"]


def compute_regimes(data: dict[str, pd.Series], fetched_at: Optional[str] = None) -> list[RegimeFlag]:
    """`data` maps series_id -> pandas Series (date index). Missing series -> UNKNOWN flag."""
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    g = lambda sid: data.get(sid, pd.Series(dtype="float64"))
    return [
        recession_watch(g("T10Y2Y"), fetched_at),
        liquidity_stress(g("RRPONTSYD"), g("WTREGEN"), fetched_at),
        inflation_regime(g("CPIAUCSL"), fetched_at),
        risk_regime(g("VIXCLS"), fetched_at),
    ]


def active_regime_line(flags: list[RegimeFlag]) -> str:
    """The 'Current regime(s):' header line for the brief.
    NOTE: no probabilities here. Numbers only appear once the backtester earns them."""
    active = [f"{f.name} [{f.status}]" for f in flags if f.is_active()]
    return "Current regime(s): " + (", ".join(active) if active else "none active")


if __name__ == "__main__":
    # quick smoke print with empty data
    for f in compute_regimes({}):
        print(f.name, "->", f.status)
