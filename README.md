# 🌿 GreenWallet — ESG Portfolio Impact Scorer

A Python-based FinTech desktop application that helps investors align their portfolios with their values by calculating a weighted sustainability score using real-time ESG data.

## Features
- **Portfolio Management (CRUD)** — Add, view, update, and delete stock holdings
- **Live ESG Fetching** — 3-tier API integration (Alpha Vantage → Yahoo Finance → Finnhub)
- **Weighted Green Score** — Calculates a portfolio-wide sustainability score based on capital allocation
- **Historical Tracking** — Stores and charts portfolio ESG scores over time
- **Risk Alerts** — Flags stocks that fall below a minimum ethical threshold
- **7-Day Cache** — Saves ESG scores locally to avoid exceeding API rate limits

## Tech Stack
- **GUI**: PyQt5
- **Database**: SQLite3
- **APIs**: Alpha Vantage, Yahoo Finance (yfinance), Finnhub
- **Charts**: Matplotlib
- **Data**: Pandas, NumPy

## How to Run

1. Install dependencies:
2. Run the app:

That's it. API keys are pre-configured and the SQLite database is created automatically on first run.

## Database Schema
| Table | Purpose |
|-------|---------|
| users | Stores username and portfolio number |
| holdings | Tracks stock tickers and share quantities |
| esg_cache | Caches ESG scores for 7 days to save API calls |
| analytics | Records historical Green Scores over time |

## Module: CST4160 — FinTech Coursework
