"""
MacroFlow Terminal — v1.3
FRED-powered: regimes, yields, net liquidity, historical base rates, AI brief, lineage.

Files: streamlit_app.py + regime_engine.py + ai_brief.py + backtest_engine.py + requirements.txt
Secrets:  FRED_API_KEY = "..."   and (optional)  ANTHROPIC_API_KEY = "..."
Units: WALCL & WTREGEN are MILLIONS; RRPONTSYD is BILLIONS.
"""

from datetime import datetime, timezone

import altair as alt
import pandas as pd
import requests
import streamlit as st

from regime_engine import compute_regimes, active_regime_line
from ai_brief import generate_brief
from backtest_engine import backtest_regime

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

SERIES = {
    "DGS2": "2Y Treasury Yield", "DGS10": "10Y Treasury Yield", "DGS30": "30Y Treasury Yield",
    "WALCL": "Fed Total Assets", "WTREGEN": "Treasury General Account", "RRPONTSYD": "Overnight Reverse Repo",
    "T10Y2Y": "10y-2y Spread", "VIXCLS": "VIX", "CPIAUCSL": "CPI (All Urban)",
}


# --------------------------------------------------------------------------
# Data layer
# --------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def get_fred_series(series_id: str, api_key: str, observation_start: str = "2018-01-01") -> pd.Series:
    params = {"series_id": series_id, "api_key": api_key,
              "file_type": "json", "observation_start": observation_start}
    r = requests.get(FRED_URL, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    dates, values = [], []
    for o in obs:
        v = o.get("value", ".")
        if v in (".", "", None):
            continue
        dates.append(pd.to_datetime(o["date"]))
        values.append(float(v))
    s = pd.Series(values, index=pd.DatetimeIndex(dates), name=series_id).sort_index()
    s.attrs = {"source": "FRED", "series_id": series_id,
               "as_of": s.index[-1].strftime("%Y-%m-%d") if len(s) else "—",
               "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return s


def load_all(api_key: str) -> dict[str, pd.Series]:
    return {sid: get_fred_series(sid, api_key) for sid in SERIES}


# --------------------------------------------------------------------------
# Presentation helpers
# --------------------------------------------------------------------------

STATUS_COLOR = {"ACTIVE": "red", "HOT": "red", "RISK-OFF": "red",
                "COLD": "blue", "RISK-ON": "green",
                "NEUTRAL": "gray", "INACTIVE": "gray", "UNKNOWN": "gray"}

def regime_detail(f) -> str:
    c = f.computed
    if f.name == "Recession Watch":
        return f"Spread {c.get('spread_latest', 0):+.2f}%  ·  {c.get('days_inverted', 0)} days inverted"
    if f.name == "Liquidity Stress":
        rrp, tga = c.get("rrp_latest"), c.get("tga_30d_change")
        return "data unavailable" if rrp is None or tga is None else f"RRP {rrp:.1f}bn  ·  TGA 30d {tga:+.0f}bn"
    if f.name == "Inflation Regime":
        return f"3-mo annualized CPI {c.get('cpi_3m_annualized_pct', 0):.1f}%"
    if f.name == "Risk Regime":
        return f"VIX {c.get('vix_latest', 0):.1f}"
    return ""

def line_chart(s: pd.Series, y_title: str, days: int = 365):
    s = s.dropna()
    s = s[s.index >= s.index[-1] - pd.Timedelta(days=days)]
    df = s.reset_index(); df.columns = ["date", "value"]
    chart = (alt.Chart(df).mark_line(strokeWidth=2)
             .encode(x=alt.X("date:T", axis=alt.Axis(format="%b %y", title=None, tickCount=6)),
                     y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=False)))
             .properties(height=240))
    st.altair_chart(chart, use_container_width=True)


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

def latest(sid):
    s = data[sid].dropna()
    return float(s.iloc[-1]) if len(s) else None


# --- Regimes (engine wants TGA in billions; WTREGEN is millions) ---
engine_data = dict(data)
engine_data["WTREGEN"] = data["WTREGEN"] / 1000.0
flags = compute_regimes(engine_data)

st.markdown(f"#### {active_regime_line(flags)}")
cols = st.columns(len(flags))
for col, f in zip(cols, flags):
    with col, st.container(border=True):
        st.caption(f.name)
        st.markdown(f"### :{STATUS_COLOR.get(f.status, 'gray')}[{f.status}]")
        st.write(regime_detail(f))
        st.caption(f.rule)

st.divider()

# --- Yields ---
st.subheader("Treasury Yields")
y1, y2, y3 = st.columns(3)
for col, sid, label in [(y1, "DGS2", "2Y"), (y2, "DGS10", "10Y"), (y3, "DGS30", "30Y")]:
    v = latest(sid)
    col.metric(label, f"{v:.2f}%" if v is not None else "—")
line_chart(data["DGS10"], "10Y yield (%)")

st.divider()

# --- Net liquidity: WALCL(M) - WTREGEN(M) - RRPONTSYD(B->M) ---
st.subheader("Net Liquidity")
walcl = data["WALCL"].dropna()
tga_m = data["WTREGEN"].dropna()
rrp_m = data["RRPONTSYD"].dropna() * 1000
net = (walcl - tga_m.reindex(walcl.index, method="ffill")
             - rrp_m.reindex(walcl.index, method="ffill")).dropna()
latest_m = delta_b = None
if len(net):
    latest_m = net.iloc[-1]
    prior = net[net.index <= net.index[-1] - pd.Timedelta(days=30)]
    prior_m = prior.iloc[-1] if len(prior) else net.iloc[0]
    delta_b = (latest_m - prior_m) / 1000
    st.metric("Net Liquidity", f"${latest_m / 1e6:,.2f}T", f"{delta_b:+,.0f}B (30d)")
    line_chart(net / 1e6, "Net liquidity (USD trn)")

st.divider()

# --- Historical base rates (the honest probabilities) ---
st.subheader("Historical Base Rates")
st.caption("Computed from history, not predicted — what risk assets did in each inflation regime.")
base_rate_line = None
ndq_long = None
try:
    cpi_long = get_fred_series("CPIAUCSL", api_key, "1971-01-01")
    ndq_long = get_fred_series("NASDAQCOM", api_key, "1971-01-01")
    res = backtest_regime(cpi_long, ndq_long, horizon_months=3, lag_months=1)
    hot, notv, H = res["HOT"], res["NOT HOT"], res["horizon_months"]
    b1, b2 = st.columns(2)
    b1.metric(f"Inflation HOT → NASDAQ next {H}mo (avg)",
              f"{hot['mean_pct']}%" if hot['mean_pct'] is not None else "—")
    b1.caption(f"positive {hot['pct_positive']}% of the time · n={hot['n']} months")
    b2.metric(f"Not HOT → NASDAQ next {H}mo (avg)",
              f"{notv['mean_pct']}%" if notv['mean_pct'] is not None else "—")
    b2.caption(f"positive {notv['pct_positive']}% of the time · n={notv['n']} months")
    st.caption("Source: FRED CPIAUCSL (3-mo annualized, 1-mo publication lag) + NASDAQCOM, "
               "monthly since 1971. Revised data; ALFRED true-vintage is the v2 upgrade.")
    if hot["mean_pct"] is not None:
        base_rate_line = (f"Historical base rate: when inflation was HOT (n={hot['n']} months since 1971), "
                          f"NASDAQ's next-{H}mo return averaged {hot['mean_pct']}% "
                          f"(positive {hot['pct_positive']}%), vs {notv['mean_pct']}% "
                          f"(positive {notv['pct_positive']}%) when not HOT.")
except Exception as e:
    st.warning(f"Base rates unavailable: {e}")

st.divider()

# --- AI Brief (paid API; runs only on button click) ---
st.subheader("AI Brief")
anthropic_key = st.secrets.get("ANTHROPIC_API_KEY")
if not anthropic_key:
    st.info("Add ANTHROPIC_API_KEY in Settings → Secrets to enable the AI brief.")
elif st.button("Generate brief"):
    market_lines = []
    if all(latest(s) is not None for s in ("DGS2", "DGS10", "DGS30")):
        market_lines.append(
            f"Yields: 2Y {latest('DGS2'):.2f}%, 10Y {latest('DGS10'):.2f}%, 30Y {latest('DGS30'):.2f}%")
    if latest_m is not None:
        market_lines.append(f"Net liquidity: ${latest_m/1e6:,.2f}T (30d {delta_b:+,.0f}B)")
    if base_rate_line:
        market_lines.append(base_rate_line)
    with st.spinner("Narrating the facts…"):
        try:
            brief = generate_brief(anthropic_key, flags, market_lines)
            st.markdown(brief.replace("$", "\\$"))
        except Exception as e:
            st.error(f"Brief failed: {e}")

st.divider()

# --- Data lineage ---
st.subheader("Data Lineage")
rows = [{"Metric": label, "Source": data[sid].attrs.get("source", "—"),
         "Series ID": sid, "As Of": data[sid].attrs.get("as_of", "—"),
         "Fetched (UTC)": data[sid].attrs.get("fetched_at", "—")}
        for sid, label in SERIES.items()]
if ndq_long is not None:
    a = ndq_long.attrs
    rows.append({"Metric": "NASDAQ Composite (backtest)", "Source": a.get("source", "—"),
                 "Series ID": "NASDAQCOM", "As Of": a.get("as_of", "—"),
                 "Fetched (UTC)": a.get("fetched_at", "—")})
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
