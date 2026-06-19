#!/usr/bin/env python3
"""Classification and scoring for after-hours movers.

Pure functions, no I/O. This is the tested contract of the skill: a list of
normalized mover records goes in, an enriched/scored/routed list comes out.

A "normalized record" is a dict with at least:
    symbol, name, regular_close, ah_price, ah_change_pct
and optionally:
    ah_volume, market_cap, sector, has_earnings, earnings_time,
    eps, eps_estimate, revenue, revenue_estimate, headline
"""

from __future__ import annotations

# Default movement thresholds (percent of regular-session close).
DEFAULT_MOVE_THRESHOLD = 5.0
BIG_MOVE = 10.0
PARABOLIC_MOVE = 20.0

# Routing: category -> downstream skills that should pick the name up.
ROUTES: dict[str, list[str]] = {
    "EARNINGS_GAP_UP": [
        "earnings-trade-analyzer",
        "pead-screener",
        "us-stock-analysis",
        "trader-memory-core",
    ],
    "EARNINGS_GAP_DOWN": [
        "scenario-analyzer",
        "us-stock-analysis",
        "parabolic-short-trade-planner",
    ],
    "EARNINGS_INLINE": ["earnings-trade-analyzer"],
    "NEWS_GAP_UP": ["market-news-analyst", "scenario-analyzer", "theme-detector"],
    "NEWS_GAP_DOWN": ["market-news-analyst", "scenario-analyzer"],
    "QUIET": [],
}


def earnings_surprise_pct(rec: dict) -> float | None:
    """Return EPS surprise % vs estimate, or None when not computable."""
    eps = rec.get("eps")
    est = rec.get("eps_estimate")
    if eps is None or est is None:
        return None
    try:
        if est == 0:
            return None
        return round((eps - est) / abs(est) * 100.0, 1)
    except (TypeError, ZeroDivisionError):
        return None


def _direction(move: float, threshold: float) -> str:
    if move >= threshold:
        return "up"
    if move <= -threshold:
        return "down"
    return "flat"


def classify_record(rec: dict, move_threshold: float = DEFAULT_MOVE_THRESHOLD) -> dict:
    """Return a new dict = record + classification fields.

    Added fields: category, direction, earnings_surprise_pct, score,
    urgency, routes, notes.
    """
    move = float(rec.get("ah_change_pct") or 0.0)
    has_earnings = bool(rec.get("has_earnings"))
    direction = _direction(move, move_threshold)
    surprise = earnings_surprise_pct(rec)
    notes: list[str] = []

    if has_earnings:
        if direction == "up":
            category = "EARNINGS_GAP_UP"
        elif direction == "down":
            category = "EARNINGS_GAP_DOWN"
        else:
            category = "EARNINGS_INLINE"
        et = (rec.get("earnings_time") or "").lower()
        when = "after the close" if et in ("amc", "aftermarket") else "this session"
        notes.append(f"Reported earnings {when}.")
        if surprise is not None:
            verb = "beat" if surprise >= 0 else "missed"
            notes.append(f"EPS {verb} estimate by {abs(surprise):.1f}%.")
    else:
        if direction == "up":
            category = "NEWS_GAP_UP"
        elif direction == "down":
            category = "NEWS_GAP_DOWN"
        else:
            category = "QUIET"
        if direction != "flat":
            notes.append("No scheduled earnings — likely headline/flow driven.")

    routes = list(ROUTES.get(category, []))

    # Parabolic overlay: an outsized up-move is a short-fade watch candidate.
    if move >= PARABOLIC_MOVE:
        notes.append(f"Parabolic extended-session spike (+{move:.1f}%).")
        if "parabolic-short-trade-planner" not in routes:
            routes.append("parabolic-short-trade-planner")

    score = score_record(rec, move)
    urgency = _urgency(score, move)

    enriched = dict(rec)
    enriched.update(
        {
            "category": category,
            "direction": direction,
            "earnings_surprise_pct": surprise,
            "score": score,
            "urgency": urgency,
            "routes": routes,
            "notes": notes,
        }
    )
    return enriched


def score_record(rec: dict, move: float | None = None) -> int:
    """Composite 0-100 conviction score for an after-hours mover."""
    if move is None:
        move = float(rec.get("ah_change_pct") or 0.0)
    amag = abs(move)

    # Magnitude (0-40): saturates at the parabolic threshold.
    magnitude = min(amag / PARABOLIC_MOVE, 1.0) * 40.0

    # After-hours volume (0-20): more participation = more real.
    vol = rec.get("ah_volume") or 0
    if vol >= 1_000_000:
        volume = 20.0
    elif vol >= 500_000:
        volume = 14.0
    elif vol >= 100_000:
        volume = 8.0
    elif vol > 0:
        volume = 4.0
    else:
        volume = 0.0

    # Liquidity / market cap (0-20): microcaps are noisy, penalize them.
    mcap = rec.get("market_cap") or 0
    if mcap >= 10_000_000_000:
        liquidity = 20.0
    elif mcap >= 2_000_000_000:
        liquidity = 16.0
    elif mcap >= 300_000_000:
        liquidity = 10.0
    elif mcap > 0:
        liquidity = 4.0
    else:
        liquidity = 8.0  # unknown cap: neutral-ish, don't over-penalize

    # Catalyst (0-20): earnings with a surprise scores highest.
    if rec.get("has_earnings"):
        surprise = earnings_surprise_pct(rec)
        if surprise is not None:
            catalyst = 12.0 + min(abs(surprise) / 25.0, 1.0) * 8.0
        else:
            catalyst = 12.0
    elif amag > 0:
        catalyst = 10.0  # news/flow catalyst implied by the move itself
    else:
        catalyst = 0.0

    total = magnitude + volume + liquidity + catalyst
    return int(round(max(0.0, min(100.0, total))))


def _urgency(score: int, move: float) -> str:
    if score >= 70 or abs(move) >= PARABOLIC_MOVE:
        return "HIGH"
    if score >= 45:
        return "MEDIUM"
    return "LOW"


def classify_all(
    records: list[dict],
    move_threshold: float = DEFAULT_MOVE_THRESHOLD,
    include_quiet: bool = False,
) -> list[dict]:
    """Classify, optionally drop QUIET names, and sort by score desc."""
    out = [classify_record(r, move_threshold) for r in records]
    if not include_quiet:
        out = [r for r in out if r["category"] != "QUIET"]
    out.sort(key=lambda r: (r["score"], abs(float(r.get("ah_change_pct") or 0.0))), reverse=True)
    return out


def session_summary(classified: list[dict]) -> dict:
    """Aggregate breadth / posture stats over the classified movers."""
    gainers = [r for r in classified if r["direction"] == "up"]
    losers = [r for r in classified if r["direction"] == "down"]
    earnings = [r for r in classified if r.get("has_earnings")]
    high = [r for r in classified if r["urgency"] == "HIGH"]
    by_category: dict[str, int] = {}
    for r in classified:
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1

    net = len(gainers) - len(losers)
    if net >= 3:
        tone = "risk-on (AH gainers dominate)"
    elif net <= -3:
        tone = "risk-off (AH losers dominate)"
    else:
        tone = "mixed / two-sided"

    return {
        "total_movers": len(classified),
        "gainers": len(gainers),
        "losers": len(losers),
        "earnings_driven": len(earnings),
        "high_urgency": len(high),
        "net_breadth": net,
        "tone": tone,
        "by_category": by_category,
    }
