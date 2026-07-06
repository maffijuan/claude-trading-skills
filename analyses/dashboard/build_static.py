"""Generate a self-contained, shareable HTML report — no server, no install.

Bakes the analysis for a list of tickers (or a preset universe) into ONE .html
file with the data embedded. The recipient just double-clicks it: interactive
batch table, click-through to each ticker's full statements + ratios, CSV export,
light/dark theme. Data is frozen at generation time.

    python analyses/dashboard/build_static.py AAPL MSFT PEP -o report.html
    python analyses/dashboard/build_static.py --universe dow30 --method ttm
    python analyses/dashboard/build_static.py --universe staples --peers KO,CL,GIS
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import financial_analysis as fa  # noqa: E402
from indices import INDICES  # noqa: E402
from peers import sector_peers, sector_of  # noqa: E402


def _last_value(analysis: dict, key: str):
    last = len(analysis["periods"]) - 1
    for r in analysis["ratios"]:
        if r["key"] == key:
            return r["values"][last] if last < len(r["values"]) else None
    return None


def build_report(tickers, years, method, peers, self_peer, with_trefis, peer_source=""):
    tickers = list(dict.fromkeys(t.upper() for t in tickers))
    explicit_peers = [p.upper() for p in (peers or []) if p]
    self_peer = self_peer and not explicit_peers
    base_median = (fa.compute_peer_medians(explicit_peers, years, method)
                   if explicit_peers else {})

    # ---- throttle-resilient fetch (chunked + backoff + on-disk cache) -------
    def work(t):
        return fa.analyze_to_dict(t, years=years, partial_method=method,
                                  peer_median=base_median, with_trefis=with_trefis)

    analyses, errors = fa.map_tickers_chunked(tickers, work, label="fetch")

    # ---- universe self-median for valuation multiples -----------------------
    used_median = dict(base_median)
    if self_peer and analyses:
        for key in fa._MULT_KEYS:
            xs = [_last_value(d, key) for d in analyses.values()]
            xs = [x for x in xs if x is not None and x > 0]
            if xs:
                used_median[key] = median(xs)

    # ---- patch recommendations (both detail + batch use the same medians) ---
    for d in analyses.values():
        last = len(d["periods"]) - 1
        tally = {"BUY": 0, "HOLD": 0, "SELL": 0}
        for r in d["ratios"]:
            if r["key"] in fa._MULT_KEYS:
                r["peer"] = used_median.get(r["key"])
                r["rec"] = fa.recommend_ratio(r["key"], r["values"][last],
                                              peer=used_median.get(r["key"]))
            if r["rec"] in tally:
                tally[r["rec"]] += 1
        d["tally"] = tally
        d["peers"] = explicit_peers
        d["peer_source"] = peer_source

    # ---- batch summary derived from the analyses ----------------------------
    rows = []
    for t, d in analyses.items():
        last = len(d["periods"]) - 1
        cells, tally = {}, {"BUY": 0, "HOLD": 0, "SELL": 0}
        for key, _lbl, fmt, _peer in fa.RATIO_DISPLAY:
            val = _last_value(d, key)
            rec = next((r["rec"] for r in d["ratios"] if r["key"] == key), "")
            cells[key] = {"value": val, "rec": rec, "fmt": fmt}
            if rec in tally:
                tally[rec] += 1
        rows.append({"ticker": t, "price": d.get("price"), "cells": cells,
                     "tally": tally, "score": tally["BUY"] - tally["SELL"],
                     "period": d["periods"][last], "is_financial": d.get("is_financial", False),
                     "sector": d.get("sector", "")})
    rows.sort(key=lambda r: r["score"], reverse=True)

    batch = {
        "rows": rows, "errors": errors,
        "ratio_order": [k for k, *_ in fa.RATIO_DISPLAY],
        "ratio_labels": {k: lbl for k, lbl, *_ in fa.RATIO_DISPLAY},
        "bank_na_keys": fa.BANK_NA_KEYS,
        "peer_basis": ("explicit: " + ", ".join(explicit_peers)) if explicit_peers
        else ("universe self-median" if self_peer else "none"),
    }
    return fa.to_jsonable({"analyses": analyses, "batch": batch})


TEMPLATE = """<!DOCTYPE html>
<html lang="es" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<header>
  <h1>📊 __TITLE__</h1>
  <span class="sub">__SUBTITLE__</span>
  <div class="spacer"></div>
  <button class="ghost" id="theme">☾ Dark</button>
</header>
<div class="wrap">
  <div class="card">
    <div class="row" style="align-items:center">
      <div class="field grow"><label>Filtrar tickers</label>
        <input type="text" id="filter" placeholder="escribí para filtrar la tabla…"></div>
      <button class="ghost" id="allbtn">Ver tabla completa</button>
      <span class="legend" style="margin-left:auto">
        <span><span class="badge BUY">BUY</span></span>
        <span><span class="badge HOLD">HOLD</span></span>
        <span><span class="badge SELL">SELL</span></span>
      </span>
    </div>
    <div class="hint">__META__</div>
  </div>
  <div id="out"></div>
</div>
<script>__JS__</script>
<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const out = $('#out');
setupTheme('#theme');
let filterText = '';

function currentBatch(){
  if(!filterText) return DATA.batch;
  const rows = DATA.batch.rows.filter(r=>r.ticker.includes(filterText));
  return Object.assign({}, DATA.batch, {rows});
}
function showBatch(){
  out.innerHTML = batchHTML(currentBatch(), exportButtonsHTML());
  out.querySelectorAll('.tickcell').forEach(el=>el.onclick=()=>showDetail(el.dataset.t));
  wireExports(DATA.batch, DATA.file||'analysis');
}
function showDetail(t){
  const d = DATA.analyses[t]; if(!d){ showBatch(); return; }
  out.innerHTML = '<div style="margin-bottom:12px"><button class="ghost" id="back">← Volver a la tabla</button></div>' + singleHTML(d, null);
  $('#back').onclick=()=>{ showBatch(); window.scrollTo({top:0,behavior:'smooth'}); };
  window.scrollTo({top:0,behavior:'smooth'});
}
$('#filter').addEventListener('input', e=>{ filterText=e.target.value.trim().toUpperCase(); showBatch(); });
$('#allbtn').onclick=()=>{ filterText=''; $('#filter').value=''; showBatch(); };

const nT = Object.keys(DATA.analyses).length;
if(nT===1){ showDetail(Object.keys(DATA.analyses)[0]); } else { showBatch(); }
</script>
</body>
</html>
"""


def render_html(data: dict, title: str, meta: str, subtitle: str, file_stem: str) -> str:
    css = (HERE / "static" / "app.css").read_text(encoding="utf-8")
    js = (HERE / "static" / "app.js").read_text(encoding="utf-8")
    data["file"] = file_stem
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (TEMPLATE
            .replace("__TITLE__", title)
            .replace("__SUBTITLE__", subtitle)
            .replace("__META__", meta)
            .replace("__CSS__", css)
            .replace("__JS__", js)
            .replace("__DATA__", payload))


def main(argv=None):
    p = argparse.ArgumentParser(description="Build a self-contained HTML analysis report.")
    p.add_argument("tickers", nargs="*", help="Tickers, e.g. AAPL MSFT PEP")
    p.add_argument("--universe", choices=sorted(INDICES),
                   help="Use a preset index (djia, sp500, nasdaq100, stoxx50, ftse100, dax)")
    p.add_argument("--years", type=int, default=3)
    p.add_argument("--method", choices=["runrate", "ttm", "none"], default="runrate")
    p.add_argument("--peers", default=None, help="Explicit peers, e.g. KO,CL,GIS")
    p.add_argument("--no-self-peer", action="store_true",
                   help="Do not use the universe's own median for multiples")
    p.add_argument("--with-trefis", action="store_true")
    p.add_argument("--title", default="Fundamental Analysis Report")
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--as-of", default=None, help="Date stamp (YYYY-MM-DD); default today")
    p.add_argument("--no-cache", action="store_true", help="Ignore the on-disk fundamentals cache")
    p.add_argument("--refresh", action="store_true",
                   help="Force a fresh fetch (cache TTL = 0 for this run, then repopulate)")
    p.add_argument("--cache-ttl", type=float, default=6.0, help="Cache freshness in hours (default 6)")
    p.add_argument("--source", choices=["auto", "fmp", "yfinance"], default="auto",
                   help="Data source: auto (FMP if FMP_API_KEY set, else yfinance), fmp, yfinance.")
    args = p.parse_args(argv)

    fa.configure_cache(enabled=not args.no_cache,
                       ttl=0 if args.refresh else int(args.cache_ttl * 3600))
    fa.configure_source(args.source)
    print(f"Data source: {fa._resolve_source(args.source)}", file=sys.stderr)

    tickers = list(args.tickers)
    if args.universe:
        tickers += INDICES[args.universe]
    if not tickers:
        p.error("give tickers or --universe")

    peers = [x.strip() for x in args.peers.split(",")] if args.peers else None
    as_of = args.as_of or _dt.date.today().isoformat()

    # single ticker, no explicit peers, no universe -> auto sector peers (S&P)
    peer_source = ""
    uniq = list(dict.fromkeys(t.upper() for t in tickers))
    if len(uniq) == 1 and not peers and not args.universe:
        auto = sector_peers(uniq[0], n=8)
        if auto:
            peers = auto
            peer_source = f"sector S&P: {sector_of(uniq[0])}"

    print(f"Building report for {len(uniq)} tickers …", file=sys.stderr)
    data = build_report(tickers, args.years, args.method, peers,
                        not args.no_self_peer, args.with_trefis, peer_source=peer_source)
    data["generated"] = as_of

    out = args.output or (f"analyses/reports/Analisis_"
                          f"{args.universe or '_'.join(t.upper() for t in tickers)[:40]}_{as_of}.html")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n = len(data["analyses"])
    meta = (f"Generado: {as_of} · {n} tickers · período: {args.method} · "
            f"{args.years} años · múltiplos vs {data['batch']['peer_basis']} · "
            f"datos: Yahoo Finance (congelados a la fecha).")
    subtitle = f"{n} tickers · {as_of}"
    html = render_html(data, args.title, meta, subtitle, out_path.stem)
    out_path.write_text(html, encoding="utf-8")
    kb = out_path.stat().st_size / 1024
    print(f"Wrote {out_path}  ({kb:.0f} KB, {n} tickers, {len(data['batch']['errors'])} errors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
