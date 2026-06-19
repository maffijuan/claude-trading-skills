#!/usr/bin/env python3
"""After-Hours Market Screener — scan extended-session movers and route them.

Builds a ranked watchlist of after-hours movers (earnings reactions, news/flow
gaps, parabolic spikes), classifies each one, and routes it to the right
downstream skill in this repo.

Modes
-----
- ``--dry-run``           : bundled fixture (no key, fully offline).
- ``--fixture P``         : custom JSON fixture at path P.
- ``--source yfinance``   : FREE live source via yfinance (no API key). Scans a
                            watchlist (``--watchlist`` / ``--watchlist-file``, or
                            the bundled default) for post-market moves.
- ``--source fmp`` (def.) : pull today's AMC earnings + per-symbol after-hours
                            quotes from FMP (requires FMP_API_KEY).

Examples
--------
    # Offline demo
    python3 scan_after_hours.py --dry-run --output-dir reports/

    # FREE live scan (no key) over the default watchlist
    python3 scan_after_hours.py --source yfinance --output-dir reports/

    # FMP: today's AMC reporters, moves >= 5%, large/mid cap only
    python3 scan_after_hours.py --min-move 5 --min-cap 2e9 --output-dir reports/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

# Allow running both as a module and by file path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import classifier  # noqa: E402
import report_generator  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_after_hours.json"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_records(raw: list[dict]) -> list[dict]:
    """Coerce arbitrary mover dicts into the classifier's normalized shape.

    Computes ``ah_change_pct`` from prices when absent, fills defaults, and
    drops records without a usable symbol or price reference.
    """
    out: list[dict] = []
    for r in raw:
        symbol = (r.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        regular_close = _to_float(r.get("regular_close"))
        ah_price = _to_float(r.get("ah_price"))
        move = r.get("ah_change_pct")
        if move is None and regular_close and ah_price:
            move = (ah_price - regular_close) / regular_close * 100.0
        if move is None:
            continue
        out.append(
            {
                "symbol": symbol,
                "name": r.get("name") or symbol,
                "regular_close": regular_close,
                "ah_price": ah_price,
                "ah_change_pct": round(float(move), 2),
                "ah_volume": _to_int(r.get("ah_volume")),
                "market_cap": _to_float(r.get("market_cap")),
                "sector": r.get("sector"),
                "has_earnings": bool(r.get("has_earnings")),
                "earnings_time": r.get("earnings_time"),
                "eps": _to_float(r.get("eps")),
                "eps_estimate": _to_float(r.get("eps_estimate")),
                "revenue": _to_float(r.get("revenue")),
                "revenue_estimate": _to_float(r.get("revenue_estimate")),
                "headline": r.get("headline"),
            }
        )
    return out


def _to_float(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(float(v)) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Live data acquisition
# ---------------------------------------------------------------------------


def fetch_live_records(args) -> list[dict]:
    """Build raw mover records from FMP for today's AMC reporters + watchlist."""
    from ah_fmp_client import AHFMPClient

    client = AHFMPClient(api_key=args.api_key, max_api_calls=args.max_api_calls)
    today = args.date or date.today().isoformat()

    # Candidate universe: today's earnings reporters + explicit watchlist.
    earnings = {
        e.get("symbol"): e for e in client.get_earnings_calendar(today, today) if e.get("symbol")
    }
    symbols = set(earnings)
    if args.watchlist:
        symbols.update(s.strip().upper() for s in args.watchlist.split(",") if s.strip())

    raw: list[dict] = []
    for sym in sorted(symbols):
        ah = client.get_aftermarket_quote(sym)
        quote = client.get_quote(sym)
        if not quote:
            continue
        regular_close = quote.get("previousClose") or quote.get("price")
        ah_price = (ah or {}).get("price") if ah else quote.get("price")
        e = earnings.get(sym, {})
        raw.append(
            {
                "symbol": sym,
                "name": quote.get("name"),
                "regular_close": regular_close,
                "ah_price": ah_price,
                "ah_volume": (ah or {}).get("volume") if ah else None,
                "market_cap": quote.get("marketCap"),
                "has_earnings": sym in earnings,
                "earnings_time": e.get("time"),
                "eps": e.get("eps") or e.get("epsActual"),
                "eps_estimate": e.get("epsEstimated") or e.get("epsEstimate"),
                "revenue": e.get("revenue") or e.get("revenueActual"),
                "revenue_estimate": e.get("revenueEstimated") or e.get("revenueEstimate"),
            }
        )
    return raw


def load_fixture(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("movers", [])
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Filtering + orchestration
# ---------------------------------------------------------------------------


def apply_filters(records: list[dict], args) -> list[dict]:
    out = []
    for r in records:
        if args.min_cap and (r.get("market_cap") or 0) < args.min_cap:
            continue
        if args.min_price and (r.get("regular_close") or r.get("ah_price") or 0) < args.min_price:
            continue
        if args.earnings_only and not r.get("has_earnings"):
            continue
        out.append(r)
    return out


DEFAULT_WATCHLIST = Path(__file__).resolve().parents[1] / "assets" / "default_watchlist.txt"


def fetch_yf_live_records(args) -> list[dict]:
    """Build raw mover records from the free yfinance source (no API key)."""
    import ah_yf_source

    if args.watchlist_file:
        symbols = ah_yf_source.load_watchlist(args.watchlist_file)
    elif args.watchlist:
        symbols = [s.strip().upper() for s in args.watchlist.split(",") if s.strip()]
    else:
        symbols = ah_yf_source.load_watchlist(str(DEFAULT_WATCHLIST))
    as_of = args.date or date.today().isoformat()
    return ah_yf_source.fetch_yf_records(symbols, as_of=as_of)


def run(args) -> dict:
    if args.dry_run:
        raw = load_fixture(FIXTURE_PATH)
    elif args.fixture:
        raw = load_fixture(Path(args.fixture))
    elif args.source == "yfinance":
        raw = fetch_yf_live_records(args)
    else:
        raw = fetch_live_records(args)

    records = normalize_records(raw)
    records = apply_filters(records, args)
    classified = classifier.classify_all(
        records, move_threshold=args.min_move, include_quiet=args.include_quiet
    )
    if args.top:
        classified = classified[: args.top]
    summary = classifier.session_summary(classified)
    as_of = args.date or date.today().isoformat()
    params = {
        "min_move": args.min_move,
        "min_cap": args.min_cap,
        "min_price": args.min_price,
        "earnings_only": args.earnings_only,
        "top": args.top,
        "source": args.source,
        "mode": "dry-run"
        if args.dry_run
        else ("fixture" if args.fixture else f"live:{args.source}"),
    }
    return report_generator.build_report(classified, summary, as_of, params)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="After-Hours Market Screener")
    p.add_argument("--api-key", help="FMP API key (else uses FMP_API_KEY env var)")
    p.add_argument("--dry-run", action="store_true", help="Use bundled fixture, no network")
    p.add_argument("--fixture", help="Path to a custom JSON fixture")
    p.add_argument(
        "--source",
        choices=["fmp", "yfinance"],
        default="fmp",
        help="Live data source: 'fmp' (needs key) or 'yfinance' (free, no key)",
    )
    p.add_argument("--watchlist", help="Comma-separated symbols to scan")
    p.add_argument("--watchlist-file", help="Path to a watchlist file (one symbol per line)")
    p.add_argument("--date", help="As-of date YYYY-MM-DD (default: today)")
    p.add_argument(
        "--min-move",
        type=float,
        default=classifier.DEFAULT_MOVE_THRESHOLD,
        help="Minimum abs AH move %% to flag a direction (default: 5)",
    )
    p.add_argument("--min-cap", type=float, default=0.0, help="Minimum market cap filter")
    p.add_argument("--min-price", type=float, default=0.0, help="Minimum share price filter")
    p.add_argument("--earnings-only", action="store_true", help="Keep only earnings reporters")
    p.add_argument("--include-quiet", action="store_true", help="Keep sub-threshold names too")
    p.add_argument("--top", type=int, default=0, help="Limit to top N by score (0 = all)")
    p.add_argument("--max-api-calls", type=int, default=250, help="Live-mode API call budget")
    p.add_argument("--output-dir", default="reports/", help="Where to write reports")
    p.add_argument("--no-write", action="store_true", help="Print summary only, don't write files")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    s = report["summary"]
    print(
        f"After-hours screen ({report['parameters']['mode']}): {s['total_movers']} movers, "
        f"{s['gainers']}↑ / {s['losers']}↓, {s['high_urgency']} high-urgency — {s['tone']}",
        file=sys.stderr,
    )
    if args.no_write:
        print(json.dumps(report, indent=2))
        return 0

    json_path, md_path = report_generator.write_reports(
        report, args.output_dir, report["as_of_date"]
    )
    print(f"Wrote {json_path}", file=sys.stderr)
    print(f"Wrote {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
