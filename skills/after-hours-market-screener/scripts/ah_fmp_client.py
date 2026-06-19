#!/usr/bin/env python3
"""Minimal FMP client for the After-Hours Market Screener.

Provides just the endpoints this skill needs:
- Today's earnings calendar (to flag AMC reporters)
- Per-symbol after-hours (extended-session) quote
- Per-symbol regular quote (for prior close / market cap fallback)

Design notes
------------
- Stable-first endpoints with a v3 legacy fallback for older API keys.
- The live path is intentionally thin: the screener's tested contract is the
  normalized-record path (see ``scan_after_hours.normalize_records``), so the
  network code stays small and is bypassed entirely in ``--fixture`` /
  ``--dry-run`` mode.
- No key is required to import this module; the key is only checked when a
  live request is actually made. This keeps the offline test suite runnable
  with no ``FMP_API_KEY`` set.
"""

from __future__ import annotations

import os
import sys
import time

try:
    import requests
except ImportError:  # pragma: no cover - exercised only in live mode
    requests = None


STABLE = "https://financialmodelingprep.com/stable"
V3 = "https://financialmodelingprep.com/api/v3"


class AHFMPClient:
    """Thin rate-limited FMP client (stable-first, v3 fallback)."""

    RATE_LIMIT_DELAY = 0.25  # seconds between calls

    def __init__(self, api_key: str | None = None, max_api_calls: int = 250):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        self.max_api_calls = max_api_calls
        self.api_calls_made = 0
        self._last_call = 0.0
        self.cache: dict[str, object] = {}
        self._session = None

    # -- internals ---------------------------------------------------------

    def _require_ready(self) -> None:
        if requests is None:
            raise RuntimeError("requests library not installed; live mode unavailable")
        if not self.api_key:
            raise ValueError(
                "FMP API key required for live mode. Set FMP_API_KEY or pass --api-key, "
                "or run with --dry-run / --fixture for offline use."
            )
        if self._session is None:
            self._session = requests.Session()

    def _get(self, url: str, params: dict) -> object | None:
        if self.api_calls_made >= self.max_api_calls:
            print("WARN: API call budget exhausted", file=sys.stderr)
            return None
        self._require_ready()
        elapsed = time.time() - self._last_call
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        q = dict(params)
        q["apikey"] = self.api_key
        try:
            resp = self._session.get(url, params=q, timeout=30)
            self._last_call = time.time()
            self.api_calls_made += 1
            if resp.status_code == 200:
                return resp.json()
            print(f"WARN: {url} -> HTTP {resp.status_code}", file=sys.stderr)
            return None
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"WARN: request failed for {url}: {exc}", file=sys.stderr)
            return None

    # -- public API --------------------------------------------------------

    def get_earnings_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """Return earnings events between two ISO dates (inclusive)."""
        key = f"earn_{from_date}_{to_date}"
        if key in self.cache:
            return self.cache[key]  # type: ignore[return-value]
        data = self._get(f"{STABLE}/earnings-calendar", {"from": from_date, "to": to_date})
        if not data:
            data = self._get(f"{V3}/earning_calendar", {"from": from_date, "to": to_date})
        result = data if isinstance(data, list) else []
        self.cache[key] = result
        return result

    def get_aftermarket_quote(self, symbol: str) -> dict | None:
        """Return the extended-session quote for a symbol, or None."""
        data = self._get(f"{STABLE}/aftermarket-quote", {"symbol": symbol})
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return None

    def get_quote(self, symbol: str) -> dict | None:
        """Return the regular full quote for a symbol, or None."""
        data = self._get(f"{STABLE}/quote", {"symbol": symbol})
        if not data:
            data = self._get(f"{V3}/quote/{symbol}", {})
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return None
