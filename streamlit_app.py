import streamlit as st
import requests

st.title("MacroFlow Terminal")
st.caption("Live economic data from FRED")

API_KEY = st.secrets["FRED_API_KEY"]

url = "https://api.stlouisfed.org/fred/series/observations"
params = {
    "series_id": "DGS10",   # 10-Year Treasury yield
    "api_key": API_KEY,
    "file_type": "json",
    "sort_order": "desc",
    "limit": 10,
}
data = requests.get(url, params=params).json()

# Grab the most recent day that has an actual number
latest = next(o for o in data["observations"] if o["value"] != ".")

st.metric(label="10-Year Treasury Yield", value=f'{latest["value"]}%')
st.write(f'As of {latest["date"]}')
