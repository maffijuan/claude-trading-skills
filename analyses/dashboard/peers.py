"""Pick sector peers for a ticker from the bundled S&P 500 GICS map.

Prefers same GICS sub-industry, then fills from the broader GICS sector.
"""

from sp500 import SP500


def sector_peers(ticker: str, n: int = 8) -> list[str]:
    ticker = ticker.upper()
    info = SP500.get(ticker)
    if not info:
        return []
    sector, sub = info
    same_sub = [t for t, (s, su) in SP500.items() if t != ticker and su == sub]
    same_sec = [t for t, (s, su) in SP500.items()
                if t != ticker and s == sector and su != sub]
    return (same_sub + same_sec)[:n]


def sector_of(ticker: str) -> str:
    info = SP500.get(ticker.upper())
    return info[0] if info else ""
