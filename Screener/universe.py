"""Build / load the US stock universe (target: ~2000 tickers).

Source of truth is the public Nasdaq Trader symbol directory (no API key, no auth):
    https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
    https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt   (NYSE/AMEX/ARCA)

We filter to ordinary common shares (drop ETFs, test issues, warrants, units,
preferreds, rights, notes) using both the file flags and symbol-shape heuristics,
then cap to a configurable size (default 2000). The cap and ordering are the only
"US 2000" interpretation choices - the engine itself has no hard limit (use
``--limit 0`` to screen the full ~6000-name list).

If the download is blocked (offline / firewall), we fall back to a bundled seed
list of large/mid-cap US names so the project always runs.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
UNIVERSE_CSV = DATA_DIR / "universe.csv"

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# Symbols whose suffix/shape indicate non-common-stock instruments.
_BAD_SUFFIX_TOKENS = ("$", ".W", ".U", ".R", ".P", "-")
_ETF_NAME_HINTS = ("etf", "etn", " fund", "ishares", "spdr", "proshares",
                    "index", "trust units", "depositary")

# Minimal offline fallback (a representative liquid subset; not exhaustive).
FALLBACK_SEED = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "LLY", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "ABBV", "NFLX",
    "BAC", "KO", "CRM", "CVX", "MRK", "AMD", "PEP", "WMT", "ADBE", "TMO",
    "ACN", "MCD", "CSCO", "ABT", "LIN", "DHR", "INTC", "WFC", "TXN", "QCOM",
    "PM", "NKE", "ORCL", "UPS", "AMGN", "HON", "IBM", "GE", "CAT", "BA",
    "SBUX", "GS", "BLK", "INTU", "PLD", "NOW", "MS", "ELV", "DE", "GILD",
    "AXP", "BKNG", "ADI", "MDLZ", "TJX", "REGN", "VRTX", "C", "PGR", "LRCX",
    "MU", "PANW", "SNPS", "CDNS", "KLAC", "MELI", "ANET", "FTNT", "CRWD", "DDOG",
    "ZS", "NET", "SHOP", "ABNB", "UBER", "PYPL", "SQ", "ROKU", "SNAP", "PINS",
    "PLTR", "SOFI", "COIN", "MARA", "RIOT", "ENPH", "FSLR", "RUN", "PLUG", "CHPT",
]


def _download(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 screener"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _looks_like_common(symbol: str, name: str) -> bool:
    s = symbol.strip().upper()
    if not s or not s.isascii():
        return False
    if any(tok in s for tok in _BAD_SUFFIX_TOKENS):
        return False
    if len(s) > 5:  # ordinary US tickers are 1-5 chars
        return False
    low = name.lower()
    if any(h in low for h in _ETF_NAME_HINTS):
        return False
    if "warrant" in low or "right" in low or "unit" in low or "preferred" in low:
        return False
    return True


def _parse_nasdaq(text: str) -> list[tuple[str, str]]:
    out = []
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        sym = (row.get("Symbol") or "").strip()
        if sym == "" or sym == "Symbol":
            continue
        if (row.get("ETF") or "").strip() == "Y":
            continue
        if (row.get("Test Issue") or "").strip() == "Y":
            continue
        name = (row.get("Security Name") or "").strip()
        if _looks_like_common(sym, name):
            out.append((sym, name))
    return out


def _parse_other(text: str) -> list[tuple[str, str]]:
    out = []
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        sym = (row.get("ACT Symbol") or "").strip()
        if sym == "" or sym == "ACT Symbol":
            continue
        if (row.get("ETF") or "").strip() == "Y":
            continue
        if (row.get("Test Issue") or "").strip() == "Y":
            continue
        name = (row.get("Security Name") or "").strip()
        if _looks_like_common(sym, name):
            out.append((sym, name))
    return out


def build_universe(limit: int = 2000, refresh: bool = False) -> list[str]:
    """Return a list of ticker symbols. Caches to data/universe.csv.

    limit=0 means "no cap" (return the full filtered list).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if UNIVERSE_CSV.exists() and not refresh:
        symbols = _read_cache()
        if symbols:
            return symbols[:limit] if limit else symbols

    rows: list[tuple[str, str]] = []
    try:
        rows += _parse_nasdaq(_download(NASDAQ_URL))
        rows += _parse_other(_download(OTHER_URL))
    except Exception as exc:  # noqa: BLE001 - any network failure -> fallback
        print(f"[universe] download failed ({exc}); using bundled fallback seed",
              file=sys.stderr)
        rows = [(s, "") for s in FALLBACK_SEED]

    # De-duplicate, keep deterministic alphabetical order.
    seen: dict[str, str] = {}
    for sym, name in rows:
        seen.setdefault(sym.upper(), name)
    ordered = sorted(seen.items())

    _write_cache(ordered)
    symbols = [s for s, _ in ordered]
    return symbols[:limit] if limit else symbols


def _write_cache(rows: list[tuple[str, str]]) -> None:
    with UNIVERSE_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "name"])
        w.writerows(rows)


def _read_cache() -> list[str]:
    with UNIVERSE_CSV.open(newline="", encoding="utf-8") as fh:
        return [row["symbol"] for row in csv.DictReader(fh) if row.get("symbol")]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Build the US stock universe")
    ap.add_argument("--limit", type=int, default=2000, help="0 = no cap")
    ap.add_argument("--refresh", action="store_true", help="force re-download")
    args = ap.parse_args()

    syms = build_universe(limit=args.limit, refresh=args.refresh)
    print(f"Universe: {len(syms)} tickers -> {UNIVERSE_CSV}")
    print(", ".join(syms[:25]) + (" ..." if len(syms) > 25 else ""))
