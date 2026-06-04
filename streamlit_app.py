import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta

st.title("MacroFlow Terminal")
st.caption("Live economic data from FRED")

API_KEY = st.secrets["FRED_API_KEY"]
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

@st.cache_data(ttl=3600)   # remember each result for 1 hour
def get_series(series_id, start):
    params = {
        "series_id": series_id,
        "api_key": API_KEY,
        "file_type": "json",
        "observation_start": start,
    }
    data = requests.get(BASE_URL, params=params).json()
    df = pd.DataFrame(data["observations"])
    df = df[df["value"] != "."]
    df["value"] = df["value"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"]


one_year_ago = (date.today() - timedelta(days=365)).isoformat()
two_years_ago = (date.today() - timedelta(days=730)).isoformat()

# ---------------- Treasury yields ----------------
two_year = get_series("DGS2", one_year_ago)
ten_year = get_series("DGS10", one_year_ago)
thirty_year = get_series("DGS30", one_year_ago)

st.subheader("Treasury Yields")
c1, c2, c3 = st.columns(3)
c1.metric("2-Year", f"{two_year.iloc[-1]}%")
c2.metric("10-Year", f"{ten_year.iloc[-1]}%")
c3.metric("30-Year", f"{thirty_year.iloc[-1]}%")
st.line_chart(ten_year)

# ---------------- Net Liquidity (the heartbeat) ----------------
walcl = get_series("WALCL", two_years_ago)      # Fed balance sheet  (millions $)
tga   = get_series("WTREGEN", two_years_ago)    # Treasury account   (millions $)
rrp   = get_series("RRPONTSYD", two_years_ago)  # Reverse repo       (BILLIONS $ — different unit!)

# Combine three series into one table, lined up by date
liq = pd.DataFrame({"walcl": walcl, "tga": tga, "rrp": rrp})

# Weekly series have gaps on daily dates — carry the last value forward
liq = liq.ffill().dropna()

# Units differ! Convert RRP billions -> millions, then show everything in trillions
liq["net"] = (liq["walcl"] - liq["tga"] - liq["rrp"] * 1000) / 1_000_000

latest = liq["net"].iloc[-1]
change = latest - liq["net"].iloc[-21]   # vs ~1 month ago

st.subheader("Net Liquidity — the market's heartbeat")
st.metric("Net Liquidity", f"${latest:.2f}T", delta=f"{change:+.2f}T vs ~1mo ago")
st.caption("Fed balance sheet − Treasury account − Reverse repo")
st.line_chart(liq["net"])
