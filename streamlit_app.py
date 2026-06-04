import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta

st.title("MacroFlow Terminal")
st.caption("Live economic data from FRED")

API_KEY = st.secrets["FRED_API_KEY"]

# Fetch the last 12 months of the 10-Year Treasury yield
one_year_ago = (date.today() - timedelta(days=365)).isoformat()

url = "https://api.stlouisfed.org/fred/series/observations"
params = {
    "series_id": "DGS10",
    "api_key": API_KEY,
    "file_type": "json",
    "observation_start": one_year_ago,
}
data = requests.get(url, params=params).json()

# Turn the raw data into a clean table: drop missing days, make values numbers
df = pd.DataFrame(data["observations"])
df = df[df["value"] != "."]
df["value"] = df["value"].astype(float)
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date")

# Headline number = the most recent value
latest_value = df["value"].iloc[-1]
latest_date = df.index[-1].date()

st.metric(label="10-Year Treasury Yield", value=f"{latest_value}%")
st.caption(f"As of {latest_date}")

st.subheader("Past 12 months")
st.line_chart(df["value"])
