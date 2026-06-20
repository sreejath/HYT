import os
from flask import Flask, jsonify, render_template
import yfinance as yf
import requests
from datetime import datetime

app = Flask(__name__)

START_DATE = "1990-01-01"
END_DATE = datetime.today().strftime("%Y-%m-%d")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")


def fetch_equity(ticker):
    df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    if df.empty:
        return []
    series = df["Close"].dropna().resample("ME").last()
    return [{"date": str(d.date()), "value": round(float(v), 2)} for d, v in series.items()]


def fetch_hy_spread():
    if not FRED_API_KEY:
        return {"error": "Set the FRED_API_KEY environment variable. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"}
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        "?series_id=BAMLH0A0HYM2"
        f"&observation_start={START_DATE}"
        f"&observation_end={END_DATE}"
        "&frequency=m"
        "&aggregation_method=eop"
        "&file_type=json"
        f"&api_key={FRED_API_KEY}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        return [{"date": o["date"], "value": round(float(o["value"]), 2)} for o in obs if o["value"] != "."]
    except Exception as e:
        return {"error": str(e)}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    sp500 = fetch_equity("^GSPC")
    tsx = fetch_equity("^GSPTSE")
    hy_spread = fetch_hy_spread()
    return jsonify({"sp500": sp500, "tsx": tsx, "hy_spread": hy_spread})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
