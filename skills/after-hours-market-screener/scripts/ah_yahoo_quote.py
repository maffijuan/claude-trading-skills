#!/usr/bin/env python3
"""Batched Yahoo Finance quote client for a broad after-hours market scan.

Yahoo's ``v7/finance/quote`` endpoint returns post-market fields
(``postMarketPrice`` / ``postMarketChangePercent``) for up to a few hundred
symbols per request, which lets the screener sweep the whole market universe
instead of a fixed watchlist — for free, without an API key.

The endpoint now requires a cookie + crumb (the same dance yfinance performs
internally). This client handles that, batches the symbol list, tolerates
partial failures (Yahoo sometimes rate-limits, especially from datacenter /
CI IPs), and returns raw mover records in the screener's normalized shape.

All HTTP is funneled through an injectable session/fetch so tests run offline.
"""

from __future__ import annotations

import sys
import time

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
COOKIE_URL = "https://fc.yahoo.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class YahooQuoteClient:
    """Cookie+crumb-authenticated, batched Yahoo quote fetcher."""

    def __init__(self, session=None, batch_size: int = 150, pause: float = 0.4):
        self.batch_size = batch_size
        self.pause = pause
        self._crumb: str | None = None
        if session is None:
            import requests

            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
        self.session = session

    def _ensure_crumb(self) -> str | None:
        if self._crumb:
            return self._crumb
        try:
            # Prime cookies, then fetch the crumb tied to them.
            self.session.get(COOKIE_URL, timeout=15)
            resp = self.session.get(CRUMB_URL, timeout=15)
            crumb = (resp.text or "").strip()
            if crumb and "<html" not in crumb.lower():
                self._crumb = crumb
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"WARN: Yahoo crumb fetch failed: {exc}", file=sys.stderr)
        return self._crumb

    def _fetch_batch(self, symbols: list[str]) -> list[dict]:
        crumb = self._ensure_crumb()
        params = {"symbols": ",".join(symbols)}
        if crumb:
            params["crumb"] = crumb
        try:
            resp = self.session.get(QUOTE_URL, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"WARN: Yahoo quote HTTP {resp.status_code}", file=sys.stderr)
                return []
            payload = resp.json()
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"WARN: Yahoo quote batch failed: {exc}", file=sys.stderr)
            return []
        return ((payload or {}).get("quoteResponse") or {}).get("result") or []

    def fetch_quotes(self, symbols: list[str]) -> list[dict]:
        """Return raw Yahoo quote dicts for all symbols (batched)."""
        out: list[dict] = []
        for i in range(0, len(symbols), self.batch_size):
            batch = symbols[i : i + self.batch_size]
            out.extend(self._fetch_batch(batch))
            if self.pause and i + self.batch_size < len(symbols):
                time.sleep(self.pause)
        return out


def quote_to_record(q: dict) -> dict | None:
    """Convert a Yahoo quote dict into a raw after-hours mover record.

    Returns None for names without a post-market print (i.e. not an
    after-hours mover).
    """
    if (q.get("quoteType") or "").upper() not in ("EQUITY", "ETF", ""):
        return None
    regular = q.get("regularMarketPrice")
    post = q.get("postMarketPrice")
    if regular is None or post is None:
        return None
    pct = q.get("postMarketChangePercent")
    try:
        if pct is None:
            pct = (float(post) - float(regular)) / float(regular) * 100.0
        pct = round(float(pct), 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None

    reg_vol = q.get("regularMarketVolume") or 0
    dollar_vol = None
    try:
        dollar_vol = float(reg_vol) * float(regular)
    except (TypeError, ValueError):
        dollar_vol = None

    return {
        "symbol": q.get("symbol"),
        "name": q.get("shortName") or q.get("longName") or q.get("symbol"),
        "regular_close": regular,
        "ah_price": post,
        "ah_change_pct": pct,
        "ah_volume": q.get("postMarketVolume") or reg_vol,
        "market_cap": q.get("marketCap"),
        "dollar_volume": dollar_vol,
        "has_earnings": False,  # no earnings calendar in the free quote feed
    }


def fetch_market_records(symbols: list[str], client: YahooQuoteClient | None = None) -> list[dict]:
    """Fetch post-market mover records for a broad symbol universe."""
    client = client or YahooQuoteClient()
    records: list[dict] = []
    for q in client.fetch_quotes(symbols):
        rec = quote_to_record(q)
        if rec and rec["symbol"]:
            records.append(rec)
    return records
