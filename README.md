# Market Tracker

Tracks **S&P 500**, **TSX Composite**, and **US High Yield Spread** over the past 35 years.

## Setup

```bash
pip install -r requirements.txt
```

For the High Yield Spread, get a free FRED API key at https://fred.stlouisfed.org/docs/api/api_key.html and export it:

```bash
export FRED_API_KEY=your_key_here
```

## Run

```bash
python app.py
```

Open http://localhost:5000

## Features

- Monthly close prices for S&P 500 (^GSPC) and TSX Composite (^GSPTSE) via Yahoo Finance
- US High Yield Option-Adjusted Spread (BAMLH0A0HYM2) via FRED
- Time range selector: 5Y / 10Y / 20Y / 35Y
- Scroll to zoom, drag to pan on each chart
- Live stats: current value, total return, all-time high/low
