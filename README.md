# Simple Options Strategy Explorer

This is a minimal finance web app that lets you enter stock symbols, fetch raw data using `yfinance`, and analyzes a simple option strategy (bull put spread). It returns ROI, probability of success, and timeline.

Quick start

1. Create a virtualenv and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the app:

```bash
export FLASK_APP=app.py
flask run --port 5000
```

3. Open `http://127.0.0.1:5000` in your browser.

Notes
- The app uses `yfinance` to fetch option chains. If implied volatility is missing, a simple historical-vol fallback is used.
- The strategy analysis is a basic example (bull put spread). Use results as educational, not trading advice.
