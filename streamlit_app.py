"""
MacroFlow Terminal — v1
Single-file Streamlit app: FRED data -> yield panel, net liquidity,
regime detection (deterministic), and a data-lineage panel.

Deploy:
  1. Put streamlit_app.py + regime_engine.py + requirements.txt in your repo.
  2. In Streamlit Cloud -> app Settings -> Secrets, add:
         FRED_API_KEY = "your_key_here"
  3. Push to GitHub. Streamlit redeploys automatically.
"""

from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

from regime_engine import compute_regimes, active_regime_line

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

# Every series the terminal touches -> drives both fetch and the lineage panel.
SERIES = {
    "DGS2":      "2Y Treasury Yield",
    "DGS10":     "10Y Treasury Yield",
    "DGS30":     "30Y Treasury Yield",
    "WALCL":     "Fed Total Assets",          # millions
    "WTREGEN":   "Treasury General Account",  # billions
    "RRPONTSYD": "Overnight Reverse Repo",    # billions
    "T10Y2Y":    "10y-2y Spread",
    "VIXCLS":    "VIX",
    "CPIAUCSL":  "CPI (All Urban)",
}


# --------------------------------------------------------------------------
# Data layer
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_fred_series(series_id: str, api_key: str) -> pd.Series:
    """Fetch one FRED series as a float Series indexed by date.
    Carries provenance in .attrs (source, series_id, as_of, fetched_at)."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": "2018-01-01",
    }
    r = requests.get(FRED_URL, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])

    dates, values = [], []
    for o in obs:
        v = o.get("value", ".")
        if v in (".", "", None):          # FRED uses "." for missing
            continue
        dates.append(pd.to_datetime(o["date"]))
        values.append(float(v))

    s = pd.Series(values, index=pd.DatetimeIndex(dates), name=series_id).sort_index()
    s.attrs = {
        "source": "FRED",
        "series_id": series_id,
        "as_of": s.index[-1].strftime("%Y-%m-%d") if len(s) else "—",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return s


def load_all(api_key: str) -> dict[str, pd.Series]:
    return {sid: get_fred_series(sid, api_key) for sid in SERIES}


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

st.set_page_config(page_title="MacroFlow Terminal", layout="wide")
st.title("MacroFlow Terminal")

api_key = st.secrets.get("FRED_API_KEY")
if not api_key:
    st.error("No FRED_API_KEY found. Add it under app Settings → Secrets, then rerun.")
    st.stop()

try:
    data = load_all(api_key)
except Exception as e:
    st.error(f"Data fetch failed: {e}")
    st.stop()


def latest(sid: str) -> float | None:
    s = data[sid].dropna()
    return float(s.iloc[-1]) if len(s) else None


# --- Regimes at the top (per Output Mandate) ---
flags = compute_regimes(data)
st.subheader(active_regime_line(flags))
reg_cols = st.columns(len(flags))
for col, f in zip(reg_cols, flags):
    with col:
        st.metric(f.name, f.status)
        st.caption(f"{f.rule}  \n`{f.computed}`")

st.divider()

# --- Yield panel ---
st.subheader("Treasury Yields")
y1, y2, y3 = st.columns(3)
y1.metric("2Y", f"{latest('DGS2'):.2f}%" if latest("DGS2") is not None else "—")
y2.metric("10Y", f"{latest('DGS10'):.2f}%" if latest("DGS10") is not None else "—")
y3.metric("30Y", f"{latest('DGS30'):.2f}%" if latest("DGS30") is not None else "—")

dgs10 = data["DGS10"].dropna()
st.line_chart(dgs10[dgs10.index >= dgs10.index[-1] - pd.Timedelta(days=365)])

st.divider()

# --- Net liquidity heartbeat ---
# WALCL is millions; WTREGEN and RRPONTSYD are billions -> convert to millions.
st.subheader("Net Liquidity")
walcl   = data["WALCL"].dropna()
tga_m   = data["WTREGEN"].dropna() * 1000          # billions -> millions
rrp_m   = data["RRPONTSYD"].dropna() * 1000        # billions -> millions
net_liq = (walcl - tga_m.reindex(walcl.index, method="ffill")
                 - rrp_m.reindex(walcl.index, method="ffill")).dropna()
if len(net_liq):
    st.metric("Net Liquidity ($M)", f"{net_liq.iloc[-1]:,.0f}")
    st.line_chart(net_liq[net_liq.index >= net_liq.index[-1] - pd.Timedelta(days=365)])

st.divider()

# --- Data lineage ---
st.subheader("Data Lineage")
rows = []
for sid, label in SERIES.items():
    a = data[sid].attrs
    rows.append({
        "Metric": label,
        "Source": a.get("source", "—"),
        "Series ID": sid,
        "As Of": a.get("as_of", "—"),
        "Fetched (UTC)": a.get("fetched_at", "—"),
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
