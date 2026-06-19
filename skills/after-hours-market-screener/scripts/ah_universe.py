#!/usr/bin/env python3
"""Build a broad US-equity symbol universe from free public sources.

Primary source: the Nasdaq Trader symbol directory (public, no API key):
    https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt
    https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt

These pipe-delimited files list every US-listed security. We keep common
stocks (drop test issues, and ETFs unless requested) so the after-hours
screener can scan the whole market instead of a fixed watchlist.

If the network fetch fails, callers fall back to the bundled
``assets/fallback_universe.txt`` list so the run still produces something.
"""

from __future__ import annotations

import sys
from pathlib import Path

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

FALLBACK_UNIVERSE = Path(__file__).resolve().parents[1] / "assets" / "fallback_universe.txt"


def _default_fetch_text(url: str) -> str:
    import requests

    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.text


def _clean_symbol(sym: str) -> str | None:
    """Normalize a ticker for Yahoo; reject warrants/units/preferreds."""
    sym = sym.strip().upper()
    if not sym:
        return None
    # Drop test/odd issues: '$' (preferreds), '.' suffixes other than class
    # shares, and anything with spaces. Yahoo uses '-' for class shares
    # (BRK.B -> BRK-B), so translate '.' to '-'.
    if "$" in sym or " " in sym:
        return None
    # Skip 5-letter symbols ending in a warrant/unit/rights code.
    if len(sym) == 5 and sym[-1] in {"W", "R", "U"}:
        return None
    return sym.replace(".", "-")


def _parse_nasdaq_listed(text: str, include_etfs: bool) -> list[str]:
    out: list[str] = []
    lines = text.splitlines()
    for line in lines[1:]:  # skip header
        if line.startswith("File Creation Time") or "|" not in line:
            continue
        f = line.split("|")
        if len(f) < 7:
            continue
        symbol, _name, _cat, test_issue, _fin, _lot, etf = f[0], f[1], f[2], f[3], f[4], f[5], f[6]
        if test_issue == "Y":
            continue
        if etf == "Y" and not include_etfs:
            continue
        sym = _clean_symbol(symbol)
        if sym:
            out.append(sym)
    return out


def _parse_other_listed(text: str, include_etfs: bool) -> list[str]:
    out: list[str] = []
    lines = text.splitlines()
    for line in lines[1:]:  # skip header
        if line.startswith("File Creation Time") or "|" not in line:
            continue
        f = line.split("|")
        # ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot|Test Issue|NASDAQ Symbol
        if len(f) < 7:
            continue
        symbol, etf, test_issue = f[0], f[4], f[6]
        if test_issue == "Y":
            continue
        if etf == "Y" and not include_etfs:
            continue
        sym = _clean_symbol(symbol)
        if sym:
            out.append(sym)
    return out


def fetch_us_equity_universe(
    include_etfs: bool = False,
    max_symbols: int = 0,
    fetch_text=_default_fetch_text,
) -> list[str]:
    """Return a de-duplicated, sorted list of US-listed symbols.

    Falls back to the bundled list on any fetch/parse failure. ``max_symbols``
    of 0 means no cap.
    """
    symbols: set[str] = set()
    try:
        symbols.update(_parse_nasdaq_listed(fetch_text(NASDAQ_LISTED_URL), include_etfs))
        symbols.update(_parse_other_listed(fetch_text(OTHER_LISTED_URL), include_etfs))
    except Exception as exc:  # network / parse failure -> bundled fallback
        print(f"WARN: universe fetch failed ({exc}); using bundled fallback", file=sys.stderr)
        symbols.update(load_fallback_universe())

    if not symbols:
        symbols.update(load_fallback_universe())

    out = sorted(symbols)
    if max_symbols and max_symbols > 0:
        out = out[:max_symbols]
    return out


def load_fallback_universe(path: Path = FALLBACK_UNIVERSE) -> list[str]:
    if not Path(path).is_file():
        return []
    out: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.upper())
    return out
