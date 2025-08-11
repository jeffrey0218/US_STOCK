# Market Environment Report

Automated daily market environment analysis and email reporting. The script fetches the CNN Fear & Greed Index, VIX, and major ETF prices, computes technical indicators (e.g., RSI), classifies the current regime, renders a trend chart, and emails an HTML report on a daily schedule. [[13]]

> Disclaimer: This project is for informational and educational purposes only and does not constitute financial advice. Use at your own risk.

---

## Features
- Pulls the CNN Fear & Greed Index to gauge market sentiment [[13]]
- Retrieves VIX and ETF prices via yfinance [[13]]
- Computes technical indicators (e.g., RSI) for selected ETFs [[13]]
- Classifies the market environment (e.g., Panic ↔ Greed) and generates strategy-oriented output [[13]]
- Produces a trend chart and composes an HTML email report with the analysis [[13]]
- Supports daily scheduling via the `schedule` library [[13]]

---

## How it works (high level)
1. Fetch data:
   - Fear & Greed Index from CNN endpoints (non-official) [[13]]
   - VIX and selected ETFs via yfinance [[13]]
2. Analyze:
   - Calculate indicators (e.g., RSI) and classify the environment [[13]]
3. Visualize:
   - Generate a chart (`market_environment_trend.png`) with matplotlib [[13]]
4. Notify:
   - Send an HTML email with the chart attached via Gmail SMTP [[13]]

---

## Requirements

- Python 3.11+ (recommended for CI runners; example workflows use Python 3.11) [[14]]
- Dependencies:
  - yfinance, pandas, numpy, matplotlib, schedule, requests, python-dateutil [[13]]

Install via pip:
```bash
python -m pip install --upgrade pip
pip install yfinance pandas numpy matplotlib schedule requests python-dateutil
