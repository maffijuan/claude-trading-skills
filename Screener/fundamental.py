"""Sector-aware fundamental scoring.

Only run for tickers that already cleared the technical screen. The goal (per the
brief) is "solid fundamentals, but not extremely restrictive". So:

  - We pick the metrics that matter for the company's SECTOR (config.SECTOR_PROFILES).
  - Each metric is scored 0-100 against generic bands (config.GENERIC_BANDS).
  - The weighted blend is the fundamental score; pass threshold is moderate (45).

We read everything from yfinance's ``info`` dict. Missing metrics are simply
dropped from that ticker's weighting (so a name isn't punished for data Yahoo
doesn't expose) - the remaining weights are renormalised.
"""

from __future__ import annotations

import math

import config as C


def _g(info: dict, *keys, default=None):
    for k in keys:
        v = info.get(k)
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            return v
    return default


def _extract_metrics(info: dict) -> dict:
    """Normalize the yfinance info dict into the metric names our bands use."""
    fcf = _g(info, "freeCashflow")
    return {
        "profit_margin": _g(info, "profitMargins"),
        "roe": _g(info, "returnOnEquity"),
        "revenue_growth": _g(info, "revenueGrowth"),
        "earnings_growth": _g(info, "earningsGrowth", "earningsQuarterlyGrowth"),
        "debt_to_equity": _g(info, "debtToEquity"),
        "current_ratio": _g(info, "currentRatio"),
        "pe": _g(info, "trailingPE", "forwardPE"),
        "peg": _g(info, "pegRatio", "trailingPegRatio"),
        "price_to_book": _g(info, "priceToBook"),
        "fcf_positive": (1.0 if (fcf is not None and fcf > 0) else
                         (0.0 if fcf is not None else None)),
        "dividend_yield": _g(info, "dividendYield"),
    }


def _score_metric(name: str, value) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    good, floor, higher = C.GENERIC_BANDS[name]
    if higher:
        if value >= good:
            return 100.0
        if value <= floor:
            return 0.0
        return 100.0 * (value - floor) / (good - floor)
    else:
        if value <= good:
            return 100.0
        if value >= floor:
            return 0.0
        return 100.0 * (floor - value) / (floor - good)


def score_fundamentals(info: dict) -> dict:
    sector = _g(info, "sector", default="Default") or "Default"
    profile = C.SECTOR_PROFILES.get(sector, C.SECTOR_PROFILES["Default"])
    metrics = _extract_metrics(info)

    breakdown = {}
    weighted, weight_sum = 0.0, 0.0
    for metric, weight in profile.items():
        raw = metrics.get(metric)
        pts = _score_metric(metric, raw)
        if pts is None:
            breakdown[metric] = {"value": raw, "score": None, "weight": weight,
                                 "used": False}
            continue
        breakdown[metric] = {"value": _round(raw), "score": round(pts, 1),
                             "weight": weight, "used": True}
        weighted += pts * weight
        weight_sum += weight

    if weight_sum == 0:
        score = None  # no fundamental data at all
    else:
        score = round(weighted / weight_sum, 1)

    coverage = round(weight_sum / sum(profile.values()), 2) if profile else 0.0
    passed = (score is not None and score >= C.FUND_PASS_THRESHOLD)
    grade = ("strong" if (score is not None and score >= C.FUND_STRONG_THRESHOLD)
             else "ok" if passed
             else "weak" if score is not None
             else "unknown")

    return {
        "sector": sector,
        "industry": _g(info, "industry", default=None),
        "score": score,
        "passed": passed,
        "grade": grade,
        "coverage": coverage,   # fraction of profile weight with real data
        "market_cap": _g(info, "marketCap"),
        "name": _g(info, "shortName", "longName", default=None),
        "breakdown": breakdown,
    }


def _round(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 4)
    return v
