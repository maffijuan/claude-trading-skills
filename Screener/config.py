"""Central configuration for the Market Screener.

Everything tunable lives here: indicator periods, scoring weights, thresholds and
sector-aware fundamental profiles. No magic numbers are buried in the engine code.

Design note: every number below is a *heuristic* rule. The screener never calls an
LLM - all decisions are deterministic functions of yfinance data and these constants.
The defaults are calibrated from the repo's own skill knowledge bases
(technical-analyst, vcp-screener, canslim-screener, value-dividend-screener).
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Data fetching
# --------------------------------------------------------------------------- #
DAILY_PERIOD = "2y"      # need >=200 daily bars for SMA200; keep last 100 for analysis
WEEKLY_PERIOD = "5y"     # gives ~250 weekly bars; we keep the last 100
BARS_KEPT = 100          # "reconstruct the last 100 candles" per the brief
BENCHMARK = "SPY"        # relative-strength reference (S&P 500 ETF)

# Polite sequential fetching (one ticker at a time, as required by the brief)
FETCH_SLEEP_SECONDS = 0.6      # base delay between tickers to stay under rate limits
FETCH_MAX_RETRIES = 4          # retries on 429 / transient errors
FETCH_BACKOFF_BASE = 2.0       # exponential backoff base (seconds): base ** attempt
CACHE_TTL_HOURS = 18           # reuse on-disk cache within the same trading day

# --------------------------------------------------------------------------- #
# Indicator periods
# --------------------------------------------------------------------------- #
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ADX_PERIOD = 14
ATR_PERIOD = 14
SMA_FAST, SMA_MID, SMA_SLOW = 50, 150, 200       # daily trend-template MAs (Minervini)
EMA_FAST, EMA_MID = 21, 50                        # daily EMA stack
VOL_AVG_PERIOD = 50                               # average volume window
ACC_DIST_LOOKBACK = 60                            # up/down volume (Supply/Demand) window

# Weekly MAs (long-term trend). ~10/30/40 weeks ≈ 50/150/200 daily.
W_SMA_FAST, W_SMA_MID, W_SMA_SLOW = 10, 30, 40

# --------------------------------------------------------------------------- #
# Weekly trend gate
# --------------------------------------------------------------------------- #
# A ticker in a confirmed weekly downtrend is skipped UNLESS it shows a
# reversal setup (see technical.classify_weekly_trend).
WEEKLY_TREND_RISING_LOOKBACK = 8   # weeks used to measure MA slope

# --------------------------------------------------------------------------- #
# Daily technical scoring (0-100). Five integral pillars: structure, momentum,
# volume, relative strength, trend quality. Weights sum to 100.
# --------------------------------------------------------------------------- #
TECH_WEIGHTS = {
    "structure": 30,        # Stage-2 trend template, MA alignment, 52w-high proximity
    "momentum": 25,         # RSI zone, MACD, rate-of-change
    "volume": 20,           # accumulation (up/down vol), OBV slope, breakout volume
    "relative_strength": 15,  # multi-period RS vs SPY
    "trend_quality": 10,    # ADX strength + not-overextended
}
TECH_BUY_THRESHOLD = 62      # daily technical score needed to be a buy candidate
TECH_STRONG_THRESHOLD = 78   # "strong" technical setup

# Overextension guard (don't chase): price too far above SMA50 / SMA200.
MAX_EXT_OVER_SMA50 = 0.20    # >20% above SMA50 = extended
MAX_EXT_OVER_SMA200 = 0.60   # >60% above SMA200 = climax risk

# --------------------------------------------------------------------------- #
# Fundamentals (sector-aware). Only run for technical buy candidates.
# "Solid but not extremely restrictive" -> pass threshold is moderate.
# --------------------------------------------------------------------------- #
FUND_PASS_THRESHOLD = 45     # fundamental score (0-100) to confirm a buy
FUND_STRONG_THRESHOLD = 70

# Generic metric scoring bands used by the sector profiles below.
# Each entry: (metric, good_value, ok_value, higher_is_better)
# A value >= good -> full points; <= ok-floor -> 0; linear in between.
GENERIC_BANDS = {
    "profit_margin":   (0.15, 0.0,  True),    # net margin
    "roe":             (0.18, 0.0,  True),    # return on equity
    "revenue_growth":  (0.10, -0.05, True),   # YoY revenue growth
    "earnings_growth": (0.12, -0.10, True),   # YoY earnings growth
    "debt_to_equity":  (50.0, 250.0, False),  # yfinance reports D/E as a percent-ish number
    "current_ratio":   (1.5,  1.0,  True),
    "pe":              (18.0, 45.0, False),   # trailing P/E (lower better, capped)
    "peg":             (1.5,  3.5,  False),
    "price_to_book":   (3.0,  8.0,  False),
    "fcf_positive":    (1.0,  0.0,  True),    # 1 if free cash flow > 0 else 0
    "dividend_yield":  (0.03, 0.0,  True),
}

# Sector profiles: which metrics matter and their relative weights.
# Unknown sectors fall back to "Default". Weights are normalised at runtime.
SECTOR_PROFILES = {
    "Technology": {
        "revenue_growth": 25, "earnings_growth": 20, "profit_margin": 20,
        "roe": 15, "pe": 10, "fcf_positive": 10,
    },
    "Communication Services": {
        "revenue_growth": 22, "earnings_growth": 18, "profit_margin": 18,
        "roe": 15, "pe": 12, "fcf_positive": 15,
    },
    "Healthcare": {
        "revenue_growth": 20, "earnings_growth": 18, "profit_margin": 18,
        "roe": 14, "pe": 15, "fcf_positive": 15,
    },
    "Consumer Cyclical": {
        "revenue_growth": 20, "earnings_growth": 18, "profit_margin": 15,
        "roe": 15, "pe": 17, "current_ratio": 15,
    },
    "Consumer Defensive": {
        "profit_margin": 20, "roe": 18, "earnings_growth": 12,
        "pe": 15, "dividend_yield": 15, "current_ratio": 20,
    },
    "Industrials": {
        "revenue_growth": 18, "earnings_growth": 18, "profit_margin": 16,
        "roe": 16, "pe": 16, "debt_to_equity": 16,
    },
    "Energy": {
        "fcf_positive": 25, "profit_margin": 18, "roe": 17,
        "debt_to_equity": 20, "pe": 10, "dividend_yield": 10,
    },
    "Basic Materials": {
        "fcf_positive": 22, "profit_margin": 18, "roe": 17,
        "debt_to_equity": 20, "pe": 13, "revenue_growth": 10,
    },
    "Utilities": {
        "dividend_yield": 25, "debt_to_equity": 20, "roe": 18,
        "earnings_growth": 12, "pe": 15, "profit_margin": 10,
    },
    "Real Estate": {  # REITs: leverage is normal, judge yield / book / growth
        "dividend_yield": 28, "price_to_book": 22, "revenue_growth": 18,
        "debt_to_equity": 12, "fcf_positive": 20,
    },
    "Financial Services": {  # banks: D/E & margins not comparable -> use ROE / P/B / P/E
        "roe": 30, "price_to_book": 25, "pe": 20,
        "earnings_growth": 15, "dividend_yield": 10,
    },
    "Default": {
        "revenue_growth": 18, "earnings_growth": 18, "profit_margin": 18,
        "roe": 18, "pe": 14, "fcf_positive": 14,
    },
}

# --------------------------------------------------------------------------- #
# Final signal labels
# --------------------------------------------------------------------------- #
# Combined score blends technical (primary) and fundamental (confirmation).
COMBINED_TECH_WEIGHT = 0.65
COMBINED_FUND_WEIGHT = 0.35
SIGNAL_STRONG_BUY = 75
SIGNAL_BUY = 60
