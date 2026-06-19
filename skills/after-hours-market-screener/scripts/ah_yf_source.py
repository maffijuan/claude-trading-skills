#!/usr/bin/env python3
"""Free after-hours data source backed by yfinance (no API key required).

yfinance is already a project dependency. This adapter pulls per-symbol
post-market quotes for a watchlist and returns raw mover records in the same
shape ``scan_after_hours.normalize_records`` expects.

Limitations vs. the FMP path (documented honestly):
- Coverage is the supplied watchlist, not "every name that reported tonight".
- Earnings are *inferred* from ``earningsTimestamp`` (is today an earnings day?),
  not from a calendar with EPS estimates — so there is no EPS-surprise number.
- Yahoo occasionally blocks datacenter IPs (e.g. CI runners); per-symbol
  failures are skipped rather than aborting the whole run.
"""

from __future__ import annotations

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _default_ticker_factory(symbol: str):
    import yfinance as yf

    return yf.Ticker(symbol)


def _info_of(ticker) -> dict:
    """Return the .info dict for a Ticker across yfinance versions."""
    getter = getattr(ticker, "get_info", None)
    if callable(getter):
        return getter() or {}
    return getattr(ticker, "info", {}) or {}


def _is_earnings_today(info: dict, as_of: str) -> bool:
    """Infer whether the symbol's earnings date is the as-of date (ET)."""
    ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
    if not ts:
        return False
    try:
        d = datetime.fromtimestamp(int(ts), ET).date().isoformat()
    except (TypeError, ValueError, OSError):
        return False
    return d == as_of


def fetch_yf_records(
    symbols: list[str],
    as_of: str | None = None,
    ticker_factory=_default_ticker_factory,
) -> list[dict]:
    """Return raw after-hours mover records for ``symbols`` via yfinance.

    Only symbols with a post-market price are returned (that is what makes a
    name an after-hours mover). Per-symbol errors are logged and skipped.
    """
    as_of = as_of or datetime.now(ET).date().isoformat()
    records: list[dict] = []
    for sym in symbols:
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            info = _info_of(ticker_factory(sym))
        except Exception as exc:  # network / parse failure for one symbol
            print(f"WARN: yfinance failed for {sym}: {exc}", file=sys.stderr)
            continue

        regular = info.get("regularMarketPrice") or info.get("currentPrice")
        post = info.get("postMarketPrice")
        if regular is None or post is None:
            # No post-market print -> not an after-hours mover; skip.
            continue
        try:
            move = (float(post) - float(regular)) / float(regular) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            continue

        records.append(
            {
                "symbol": sym,
                "name": info.get("shortName") or info.get("longName") or sym,
                "regular_close": regular,
                "ah_price": post,
                "ah_change_pct": round(move, 2),
                "ah_volume": info.get("postMarketVolume") or info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector"),
                "has_earnings": _is_earnings_today(info, as_of),
                "earnings_time": "amc" if _is_earnings_today(info, as_of) else None,
            }
        )
    return records


def load_watchlist(path: str) -> list[str]:
    """Read a watchlist file: one symbol per line, '#' comments allowed."""
    out: list[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(line.upper())
    return out
