import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta

st.title("MacroFlow Terminal")
st.caption("Live economic data from FRED")

API_KEY = st.secrets["FRED_API_KEY"]
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


# A reusable function: hand it a FRED series ID, get back a clean table.
# Write the fetching logic ONCE, use it as many times as we like.
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

# Same function, three times. That repetition-free reuse is the whole point.
two_year = get_series("DGS2", one_year_ago)
ten_year = get_series("DGS10", one_year_ago)
thirty_year = get_series("DGS30", one_year_ago)

# Show them side by side in three columns
col1, col2, col3 = st.columns(3)
col1.metric("2-Year", f"{two_year.iloc[-1]}%")
col2.metric("10-Year", f"{ten_year.iloc[-1]}%")
col3.metric("30-Year", f"{thirty_year.iloc[-1]}%")

st.caption(f"As of {ten_year.index[-1].date()}")

st.subheader("10-Year Treasury Yield — past 12 months")
st.line_chart(ten_year)
