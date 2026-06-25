"""yfinance data access layer.

Per the brief we fetch tickers ONE BY ONE (never batch) to stay friendly with
Yahoo's rate limits, with exponential backoff on 429/transient failures and an
on-disk cache so re-runs within the same trading day are instant and don't re-hit
the API.

Returns a normalized ``TickerData`` object holding:
  - daily OHLCV (last ~2y)
  - weekly OHLCV (last ~5y)
  - the ``info`` dict (sector + fundamentals)

The only network dependency in the whole project lives here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

import config

CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"


@dataclass
class TickerData:
    symbol: str
    daily: pd.DataFrame
    weekly: pd.DataFrame
    info: dict
    ok: bool = True
    error: str = ""
    meta: dict = field(default_factory=dict)


def _cache_paths(symbol: str) -> tuple[Path, Path, Path]:
    base = CACHE_DIR / symbol.upper()
    return (base.with_suffix(".daily.parquet"),
            base.with_suffix(".weekly.parquet"),
            base.with_suffix(".info.json"))


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc)
    return age < timedelta(hours=config.CACHE_TTL_HOURS)


def _load_cache(symbol: str):
    dp, wp, ip = _cache_paths(symbol)
    if not (_cache_fresh(dp) and _cache_fresh(wp) and _cache_fresh(ip)):
        return None
    try:
        daily = pd.read_parquet(dp)
        weekly = pd.read_parquet(wp)
        info = json.loads(ip.read_text(encoding="utf-8"))
        return daily, weekly, info
    except Exception:  # noqa: BLE001 - corrupt cache -> refetch
        return None


def _save_cache(symbol: str, daily: pd.DataFrame, weekly: pd.DataFrame, info: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dp, wp, ip = _cache_paths(symbol)
    try:
        daily.to_parquet(dp)
        weekly.to_parquet(wp)
        ip.write_text(json.dumps(info, default=str), encoding="utf-8")
    except Exception:  # noqa: BLE001 - parquet engine missing etc.; cache is best-effort
        try:
            daily.to_pickle(dp.with_suffix(".pkl"))
            weekly.to_pickle(wp.with_suffix(".pkl"))
        except Exception:
            pass


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate" in msg


def _fetch_history(tk: yf.Ticker, period: str, interval: str) -> pd.DataFrame:
    for attempt in range(config.FETCH_MAX_RETRIES):
        try:
            df = tk.history(period=period, interval=interval, auto_adjust=True)
            if df is not None and not df.empty:
                return df
            # empty -> brief pause then retry once or twice
            time.sleep(config.FETCH_BACKOFF_BASE ** attempt)
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit(exc) and attempt < config.FETCH_MAX_RETRIES - 1:
                time.sleep(config.FETCH_BACKOFF_BASE ** (attempt + 1))
                continue
            if attempt < config.FETCH_MAX_RETRIES - 1:
                time.sleep(config.FETCH_BACKOFF_BASE ** attempt)
                continue
            raise
    return pd.DataFrame()


def fetch_ticker(symbol: str, use_cache: bool = True,
                 need_info: bool = True) -> TickerData:
    """Fetch one ticker's daily + weekly history and (optionally) fundamentals."""
    symbol = symbol.upper().strip()

    if use_cache:
        cached = _load_cache(symbol)
        if cached is not None:
            daily, weekly, info = cached
            return TickerData(symbol, daily, weekly, info, meta={"source": "cache"})

    tk = yf.Ticker(symbol)
    try:
        daily = _fetch_history(tk, config.DAILY_PERIOD, "1d")
        time.sleep(config.FETCH_SLEEP_SECONDS / 2)
        weekly = _fetch_history(tk, config.WEEKLY_PERIOD, "1wk")
    except Exception as exc:  # noqa: BLE001
        return TickerData(symbol, pd.DataFrame(), pd.DataFrame(), {},
                          ok=False, error=f"history: {exc}")

    if daily.empty or weekly.empty:
        return TickerData(symbol, daily, weekly, {}, ok=False,
                          error="no price history")

    info: dict = {}
    if need_info:
        try:
            info = tk.info or {}
        except Exception as exc:  # noqa: BLE001 - fundamentals are optional
            info = {"_info_error": str(exc)}

    _save_cache(symbol, daily, weekly, info)
    return TickerData(symbol, daily, weekly, info, meta={"source": "yfinance"})


def fetch_benchmark(use_cache: bool = True) -> pd.DataFrame:
    """Daily history for the relative-strength benchmark (SPY)."""
    td = fetch_ticker(config.BENCHMARK, use_cache=use_cache, need_info=False)
    return td.daily if td.ok else pd.DataFrame()
