"""Market Screener orchestrator.

Iterates the universe ONE TICKER AT A TIME and runs the pipeline:

    yfinance fetch  ->  weekly trend gate  ->  daily technical score
                    ->  (if buy candidate) sector-aware fundamentals
                    ->  combined signal + final label

Writes results to output/results.json and output/results.csv, and (by default)
regenerates output/dashboard.html.

Robustness (the brief: "even if it takes time, the screener must work; the number
of tickers must not be a limitation"):
  - sequential fetch + backoff + on-disk cache (see data.py)
  - resumable: --resume reuses a previous results.json and skips done tickers
  - partial results are flushed to disk every --flush-every tickers, so a long run
    never loses work.

No LLM calls. Only yfinance for data.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config as C
import data as datalayer
import fundamental as fund
import technical as tech
from universe import build_universe

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
RESULTS_JSON = OUTPUT_DIR / "results.json"
RESULTS_CSV = OUTPUT_DIR / "results.csv"


def combined_signal(tscore: float, fscore: float | None, fund_passed: bool) -> dict:
    """Blend technical (primary) + fundamental (confirmation) into a final label."""
    if fscore is None:
        # No fundamentals available: lean on technicals but cap the upside.
        combined = tscore * 0.9
    else:
        combined = (C.COMBINED_TECH_WEIGHT * tscore +
                    C.COMBINED_FUND_WEIGHT * fscore)

    if combined >= C.SIGNAL_STRONG_BUY and fund_passed:
        label = "STRONG BUY"
    elif combined >= C.SIGNAL_BUY and (fund_passed or fscore is None):
        label = "BUY"
    elif tscore >= C.TECH_BUY_THRESHOLD:
        label = "WATCH"
    else:
        label = "NEUTRAL"
    return {"combined_score": round(combined, 1), "label": label}


def screen_one(symbol: str, bench) -> dict | None:
    """Run the full pipeline for one ticker. Returns a result dict or None on data error."""
    td = datalayer.fetch_ticker(symbol)
    if not td.ok:
        return {"symbol": symbol, "status": "data_error", "error": td.error}

    try:
        tv = tech.technical_verdict(td.weekly, td.daily, bench)
    except Exception as exc:  # noqa: BLE001 - one bad ticker shouldn't kill the run
        return {"symbol": symbol, "status": "tech_error", "error": str(exc)}

    last_close = float(td.daily["Close"].iloc[-1])
    result = {
        "symbol": symbol,
        "status": "ok",
        "last_close": round(last_close, 2),
        "weekly_trend": tv["weekly"]["trend"],
        "weekly_reversal": tv["weekly"]["reversal"],
        "passed_weekly_gate": tv["passed_weekly_gate"],
        "setup": tv["setup"],
        "technical_score": tv["technical_score"],
        "is_buy_candidate": tv["is_buy_candidate"],
        "technical_detail": tv.get("daily"),
        "weekly_detail": tv["weekly"]["detail"],
    }

    if not tv["is_buy_candidate"]:
        result["label"] = "NEUTRAL" if tv["passed_weekly_gate"] else "REJECTED"
        result["combined_score"] = tv["technical_score"]
        result["fundamental"] = None
        return result

    # Fundamentals only for technical candidates.
    f = fund.score_fundamentals(td.info)
    sig = combined_signal(tv["technical_score"], f["score"], f["passed"])
    result["fundamental"] = f
    result["sector"] = f["sector"]
    result["company"] = f["name"]
    result["market_cap"] = f["market_cap"]
    result["combined_score"] = sig["combined_score"]
    result["label"] = sig["label"]
    result["strength"] = tv["strength"]
    return result


def _flush(results: list[dict], meta: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "results": results}
    RESULTS_JSON.write_text(json.dumps(payload, indent=2, default=str),
                            encoding="utf-8")
    _write_csv(results)


def _write_csv(results: list[dict]):
    cols = ["symbol", "company", "sector", "label", "combined_score",
            "technical_score", "weekly_trend", "setup", "is_buy_candidate",
            "last_close", "market_cap", "status"]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            row = dict(r)
            f = r.get("fundamental")
            if isinstance(f, dict):
                row.setdefault("sector", f.get("sector"))
                row.setdefault("company", f.get("name"))
            w.writerow(row)


def run(symbols: list[str], resume: bool, flush_every: int,
        regen_dashboard: bool, progress_cb=None) -> dict:
    """Screen a list of symbols.

    progress_cb(done:int, total:int, symbol:str, result:dict|None) is called after
    each ticker (used by the web UI to report live progress). Optional.
    """
    started = datetime.now(timezone.utc)
    bench = datalayer.fetch_benchmark()
    if bench is None or bench.empty:
        print("[warn] benchmark (SPY) unavailable -> relative strength neutralized",
              file=sys.stderr)

    done: dict[str, dict] = {}
    if resume and RESULTS_JSON.exists():
        try:
            prev = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
            for r in prev.get("results", []):
                if r.get("status") == "ok":
                    done[r["symbol"]] = r
            print(f"[resume] {len(done)} tickers already done")
        except Exception:  # noqa: BLE001
            pass

    results: list[dict] = list(done.values())
    total = len(symbols)
    t0 = time.time()
    processed = 0

    for i, sym in enumerate(symbols, 1):
        if sym in done:
            continue
        res = screen_one(sym, bench)
        if res is not None:
            results.append(res)
        processed += 1

        label = (res or {}).get("label", "-")
        score = (res or {}).get("combined_score", "-")
        print(f"[{i}/{total}] {sym:<6} -> {label:<10} score={score}")

        if progress_cb is not None:
            try:
                progress_cb(i, total, sym, res)
            except Exception:  # noqa: BLE001 - never let the UI callback kill a run
                pass

        if processed % flush_every == 0:
            _flush(results, _meta(started, symbols, results, partial=True))

        time.sleep(C.FETCH_SLEEP_SECONDS)

    meta = _meta(started, symbols, results, partial=False)
    meta["elapsed_seconds"] = round(time.time() - t0, 1)
    _flush(results, meta)

    if regen_dashboard:
        try:
            import dashboard
            dashboard.build(RESULTS_JSON, OUTPUT_DIR / "dashboard.html")
            print(f"[dashboard] -> {OUTPUT_DIR / 'dashboard.html'}")
        except Exception as exc:  # noqa: BLE001
            print(f"[dashboard] skipped: {exc}", file=sys.stderr)

    _print_summary(results, meta)
    return meta


def _meta(started, symbols, results, partial: bool) -> dict:
    ok = [r for r in results if r.get("status") == "ok"]
    buys = [r for r in ok if r.get("label") in ("BUY", "STRONG BUY")]
    return {
        "generated_at": started.isoformat(),
        "universe_size": len(symbols),
        "analyzed": len(ok),
        "buy_signals": len(buys),
        "strong_buys": len([r for r in ok if r.get("label") == "STRONG BUY"]),
        "watch": len([r for r in ok if r.get("label") == "WATCH"]),
        "partial": partial,
        "config": {
            "tech_buy_threshold": C.TECH_BUY_THRESHOLD,
            "fund_pass_threshold": C.FUND_PASS_THRESHOLD,
            "weights": C.TECH_WEIGHTS,
        },
    }


def _print_summary(results, meta):
    ok = [r for r in results if r.get("status") == "ok"]
    buys = sorted([r for r in ok if r.get("label") in ("BUY", "STRONG BUY")],
                  key=lambda r: r.get("combined_score", 0), reverse=True)
    print("\n" + "=" * 60)
    print(f"Analyzed {meta['analyzed']} / {meta['universe_size']} tickers")
    print(f"BUY signals: {meta['buy_signals']} "
          f"(STRONG BUY: {meta['strong_buys']}, WATCH: {meta['watch']})")
    print("-" * 60)
    for r in buys[:20]:
        print(f"  {r['symbol']:<6} {r.get('label'):<10} "
              f"combined={r.get('combined_score'):<5} "
              f"tech={r.get('technical_score'):<5} "
              f"{r.get('sector','')}")
    print("=" * 60)


def main(argv=None):
    ap = argparse.ArgumentParser(description="US Market Screener (yfinance, heuristic)")
    ap.add_argument("--limit", type=int, default=2000,
                    help="universe size cap (0 = no cap / full list)")
    ap.add_argument("--tickers", type=str, default=None,
                    help="comma-separated tickers to screen instead of the universe")
    ap.add_argument("--refresh-universe", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="reuse output/results.json and skip already-done tickers")
    ap.add_argument("--flush-every", type=int, default=10)
    ap.add_argument("--no-dashboard", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        symbols = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        symbols = build_universe(limit=args.limit, refresh=args.refresh_universe)

    print(f"Screening {len(symbols)} tickers...\n")
    run(symbols, resume=args.resume, flush_every=args.flush_every,
        regen_dashboard=not args.no_dashboard)


if __name__ == "__main__":
    main()
