"""Generate a self-contained, semi-professional HTML dashboard from results.json.

The output is a single file with the data inlined as JSON, so it opens by simply
double-clicking it (file://) - no server, no CDN, fully offline.

When the same page is served by app.py (Flask), it auto-detects the backend and the
two action buttons become live:
  - "Screen all market"  -> runs the full universe
  - "Screen tickers"     -> runs a specific ticker / comma-separated list
Over file:// (no backend) the buttons explain how to start the server.

JS is intentionally conservative (no optional chaining / nullish coalescing) and the
whole render is wrapped in try/catch that surfaces any error in a visible banner.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build(results_json: Path, out_html: Path) -> Path:
    payload = _load(results_json)
    html = _render(payload)
    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    return out_html


def _load(results_json) -> dict:
    p = Path(results_json)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"meta": {}, "results": []}


def _render(payload: dict) -> str:
    # allow_nan=False guarantees strictly valid JSON (no bare NaN/Infinity tokens).
    data_js = json.dumps(payload, default=str, allow_nan=False)
    return _TEMPLATE.replace("/*__DATA__*/", data_js)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>US Market Screener - Bullish Signals</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2330; --border:#2b333f;
    --txt:#e6edf3; --muted:#8b949e; --accent:#2f81f7;
    --green:#3fb950; --green2:#196c2e; --amber:#d29922; --red:#f85149;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  header{padding:22px 32px;border-bottom:1px solid var(--border);
         display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px}
  h1{margin:0;font-size:22px;letter-spacing:.3px}
  .sub{color:var(--muted);font-size:13px;margin-top:4px}
  .wrap{padding:22px 32px;max-width:1400px;margin:0 auto}

  /* control bar */
  .toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;
           background:var(--panel);border:1px solid var(--border);border-radius:10px;
           padding:14px 16px;margin-bottom:20px}
  .toolbar .grp{display:flex;gap:8px;align-items:center}
  .btn{background:var(--accent);color:#fff;border:none;border-radius:8px;
       padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer}
  .btn:hover{filter:brightness(1.1)}
  .btn.secondary{background:var(--panel2);border:1px solid var(--border);color:var(--txt)}
  .btn:disabled{opacity:.5;cursor:not-allowed}
  .toolbar input[type=text]{background:var(--panel2);border:1px solid var(--border);
       color:var(--txt);padding:9px 11px;border-radius:8px;font-size:13px;min-width:240px}
  .toolbar .status{margin-left:auto;font-size:13px;color:var(--muted)}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
  .dot.on{background:var(--green)} .dot.off{background:#6e7681}
  .progress{height:6px;background:#21262d;border-radius:4px;overflow:hidden;flex:1;min-width:160px;display:none}
  .progress > i{display:block;height:100%;width:0;background:var(--accent);transition:width .3s}

  .banner{background:#3a1d1f;border:1px solid var(--red);color:#f7c0bc;border-radius:8px;
          padding:12px 14px;margin-bottom:16px;font-size:13px;display:none;white-space:pre-wrap}
  .note{background:#15263d;border:1px solid #1f4b7a;color:#a9cdf5;border-radius:8px;
        padding:10px 14px;margin-bottom:16px;font-size:13px;display:none}

  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:14px;margin-bottom:22px}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px 18px}
  .card .k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.6px}
  .card .v{font-size:28px;font-weight:600;margin-top:6px}
  .card .v.green{color:var(--green)} .card .v.amber{color:var(--amber)}
  .grid2{display:grid;grid-template-columns:1.4fr 1fr;gap:22px;margin-bottom:22px}
  @media(max-width:980px){.grid2{grid-template-columns:1fr}}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:18px}
  .panel h2{margin:0 0 14px;font-size:15px;font-weight:600}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
  th{color:var(--muted);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--panel)}
  th:hover{color:var(--txt)}
  tr:hover td{background:var(--panel2)}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:700}
  .STRONGBUY{background:var(--green2);color:#d4f7d4;border:1px solid var(--green)}
  .BUY{background:#14361f;color:#7ee090;border:1px solid #2ea043}
  .WATCH{background:#3a2d09;color:#f0cf7a;border:1px solid var(--amber)}
  .NEUTRAL{background:#21262d;color:var(--muted);border:1px solid var(--border)}
  .REJECTED{background:#2a1416;color:#f3a39c;border:1px solid #6e2b27}
  .scorebar{position:relative;height:7px;background:#21262d;border-radius:4px;overflow:hidden;min-width:90px}
  .scorebar > i{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:linear-gradient(90deg,#196c2e,#3fb950)}
  .controls{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
  input[type=text],select{background:var(--panel2);border:1px solid var(--border);color:var(--txt);
       padding:8px 11px;border-radius:8px;font-size:13px}
  .legend{color:var(--muted);font-size:12px;margin-top:10px;line-height:1.6}
  .bar{display:flex;align-items:center;gap:10px;margin:7px 0}
  .bar .lbl{width:150px;font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis}
  .bar .track{flex:1;height:14px;background:#21262d;border-radius:4px;overflow:hidden}
  .bar .track > i{display:block;height:100%;background:var(--accent)}
  .muted{color:var(--muted)} .mono{font-variant-numeric:tabular-nums}
  footer{padding:20px 32px;color:var(--muted);font-size:12px;border-top:1px solid var(--border);margin-top:20px}
</style>
</head>
<body>
<header>
  <div>
    <h1>US Market Screener - Bullish / Buy Signals</h1>
    <div class="sub" id="subtitle">loading...</div>
  </div>
  <div class="sub" id="genstamp"></div>
</header>

<div class="wrap">
  <!-- ACTION TOOLBAR -->
  <div class="toolbar">
    <div class="grp">
      <button class="btn" id="btnAll">Screen all market</button>
    </div>
    <div class="grp">
      <input type="text" id="tickInput" placeholder="Tickers e.g. AAPL, MSFT, NVDA"/>
      <button class="btn secondary" id="btnTick">Screen tickers</button>
    </div>
    <div class="progress" id="prog"><i id="progBar"></i></div>
    <div class="status" id="backend"><span class="dot off"></span>checking backend...</div>
  </div>

  <div class="banner" id="errBanner"></div>
  <div class="note" id="noteBox"></div>

  <div class="cards" id="cards"></div>

  <div class="grid2">
    <div class="panel">
      <h2>Top Buy Candidates</h2>
      <div id="topwrap"></div>
    </div>
    <div class="panel">
      <h2>Buy Signals by Sector</h2>
      <div id="sectors"></div>
      <div class="legend">Sector mix of every BUY / STRONG BUY result.</div>
    </div>
  </div>

  <div class="panel">
    <h2>All Analyzed Tickers</h2>
    <div class="controls">
      <input type="text" id="search" placeholder="Filter ticker / company / sector..."/>
      <select id="labelFilter">
        <option value="">All signals</option>
        <option value="STRONG BUY">STRONG BUY</option>
        <option value="BUY">BUY</option>
        <option value="WATCH">WATCH</option>
        <option value="NEUTRAL">NEUTRAL</option>
        <option value="REJECTED">REJECTED (weekly downtrend)</option>
      </select>
      <span class="muted" id="rowcount"></span>
    </div>
    <div style="max-height:560px;overflow:auto">
      <table id="tbl">
        <thead><tr>
          <th data-k="symbol">Ticker</th>
          <th data-k="company">Company</th>
          <th data-k="sector">Sector</th>
          <th data-k="label">Signal</th>
          <th class="num" data-k="combined_score">Combined</th>
          <th class="num" data-k="technical_score">Technical</th>
          <th data-k="weekly_trend">Weekly</th>
          <th data-k="setup">Setup</th>
          <th class="num" data-k="last_close">Close</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="legend">
      Click any column header to sort. Combined = 0.65*technical + 0.35*fundamental
      (fundamentals only computed for technical buy candidates).
      Setup: trend_continuation (weekly uptrend), reversal (downtrend with a turn-up
      setup), base_building (sideways).
    </div>
  </div>
</div>

<footer>
  Heuristic screener - yfinance data only, no LLM/AI calls at runtime.
  Educational use; not investment advice.
</footer>

<script>
"use strict";
var PAYLOAD = /*__DATA__*/;

// ---------- helpers (ES5-safe) ----------
function $(id){ return document.getElementById(id); }
function g(v){ return (v===null || v===undefined) ? '' : v; }
function cls(label){ return String(label || 'NEUTRAL').replace(/\s+/g,''); }
function pill(label){ return '<span class="pill '+cls(label)+'">'+(g(label)||'-')+'</span>'; }
function bar(score){ var s=Math.max(0,Math.min(100, Number(score)||0));
  return '<div class="scorebar"><i style="width:'+s+'%"></i></div>'; }
function showError(msg){ var b=$('errBanner'); b.style.display='block';
  b.textContent='Dashboard error: '+msg; }

// ---------- render ----------
function render(payload){
  var meta = payload.meta || {};
  var rows = (payload.results || []).filter(function(r){ return r.status==='ok'; });

  $('subtitle').textContent =
    'Universe: ' + g(meta.universe_size || rows.length) +
    '  -  Analyzed: ' + g(meta.analyzed || rows.length) +
    (meta.partial ? '  -  (partial run)' : '');
  $('genstamp').textContent =
    (meta.generated_at ? 'Generated: ' + meta.generated_at : '') +
    (meta.elapsed_seconds ? '  -  ' + meta.elapsed_seconds + 's' : '');

  // cards
  var strong = rows.filter(function(r){return r.label==='STRONG BUY';}).length;
  var buys = rows.filter(function(r){return r.label==='BUY'||r.label==='STRONG BUY';}).length;
  var watch = rows.filter(function(r){return r.label==='WATCH';}).length;
  var rej = rows.filter(function(r){return r.label==='REJECTED';}).length;
  var cards = [
    {k:'Analyzed', v:rows.length, c:''},
    {k:'Buy Signals', v:buys, c:'green'},
    {k:'Strong Buys', v:strong, c:'green'},
    {k:'Watchlist', v:watch, c:'amber'},
    {k:'Rejected (downtrend)', v:rej, c:''}
  ];
  $('cards').innerHTML = cards.map(function(c){
    return '<div class="card"><div class="k">'+c.k+'</div><div class="v '+c.c+'">'+c.v+'</div></div>';
  }).join('');

  // top candidates
  var top = rows.filter(function(r){return r.label==='BUY'||r.label==='STRONG BUY';})
    .sort(function(a,b){return (b.combined_score||0)-(a.combined_score||0);}).slice(0,12);
  if(top.length){
    var html = '<table><thead><tr><th>Ticker</th><th>Signal</th>'+
      '<th class="num">Combined</th><th>Score</th><th>Sector</th></tr></thead><tbody>';
    html += top.map(function(r){
      return '<tr><td><b>'+r.symbol+'</b><div class="muted" style="font-size:11px">'+
        g(r.company)+'</div></td><td>'+pill(r.label)+'</td>'+
        '<td class="num mono">'+g(r.combined_score)+'</td>'+
        '<td style="width:130px">'+bar(r.combined_score)+'</td>'+
        '<td class="muted">'+g(r.sector)+'</td></tr>';
    }).join('');
    html += '</tbody></table>';
    $('topwrap').innerHTML = html;
  } else {
    $('topwrap').innerHTML = '<div class="muted">No buy signals in this run.</div>';
  }

  // sectors
  var sec = {};
  rows.filter(function(r){return r.label==='BUY'||r.label==='STRONG BUY';})
    .forEach(function(r){ var s=r.sector||'Unknown'; sec[s]=(sec[s]||0)+1; });
  var arr = Object.keys(sec).map(function(k){return [k,sec[k]];})
    .sort(function(a,b){return b[1]-a[1];});
  var mx = Math.max.apply(null, arr.map(function(x){return x[1];}).concat([1]));
  $('sectors').innerHTML = arr.length ? arr.map(function(p){
    return '<div class="bar"><div class="lbl" title="'+p[0]+'">'+p[0]+'</div>'+
      '<div class="track"><i style="width:'+(100*p[1]/mx)+'%"></i></div>'+
      '<div class="cnt muted">'+p[1]+'</div></div>';
  }).join('') : '<div class="muted">-</div>';

  // table (sortable / filterable)
  window.__rows = rows;
  renderTable();
}

var sortK='combined_score', sortDir=-1;
function renderTable(){
  var rows = window.__rows || [];
  var q = $('search').value.toLowerCase().trim();
  var lf = $('labelFilter').value;
  var out = rows.filter(function(r){
    if(lf && r.label!==lf) return false;
    if(!q) return true;
    return [r.symbol, r.company, r.sector].some(function(x){
      return String(g(x)).toLowerCase().indexOf(q) >= 0; });
  });
  var strCols = {symbol:1,sector:1,company:1,setup:1,label:1,weekly_trend:1};
  out.sort(function(a,b){
    var x=a[sortK], y=b[sortK];
    if(strCols[sortK]) return sortDir*String(g(x)).localeCompare(String(g(y)));
    return sortDir*(((x==null?-1:x))-((y==null?-1:y)));
  });
  $('rowcount').textContent = out.length + ' rows';
  $('tbl').getElementsByTagName('tbody')[0].innerHTML = out.map(function(r){
    return '<tr><td><b>'+r.symbol+'</b></td>'+
      '<td class="muted">'+g(r.company)+'</td>'+
      '<td class="muted">'+g(r.sector)+'</td>'+
      '<td>'+pill(r.label)+'</td>'+
      '<td class="num mono">'+g(r.combined_score)+'</td>'+
      '<td class="num mono">'+g(r.technical_score)+'</td>'+
      '<td class="muted">'+g(r.weekly_trend)+(r.weekly_reversal?' (rev)':'')+'</td>'+
      '<td class="muted">'+g(r.setup)+'</td>'+
      '<td class="num mono">'+g(r.last_close)+'</td></tr>';
  }).join('');
}

// ---------- backend wiring (works when served by app.py) ----------
var BACKEND = false;
function setBackend(on, txt){
  BACKEND = on;
  $('backend').innerHTML = '<span class="dot '+(on?'on':'off')+'"></span>'+txt;
}
function showNote(msg){ var n=$('noteBox'); n.style.display='block'; n.textContent=msg; }

function startScreen(body){
  if(!BACKEND){
    showNote('Live screening needs the local server. Stop here, run:  python app.py'+
      '  then open  http://127.0.0.1:5000  and the buttons will work. '+
      '(This standalone file shows the last saved run only.)');
    return;
  }
  $('btnAll').disabled = true; $('btnTick').disabled = true;
  $('prog').style.display='block';
  fetch('/api/screen', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)})
    .then(function(r){return r.json();})
    .then(function(){ poll(); })
    .catch(function(e){ showError(String(e)); resetButtons(); });
}
function resetButtons(){ $('btnAll').disabled=false; $('btnTick').disabled=false; }
function poll(){
  fetch('/api/status').then(function(r){return r.json();}).then(function(st){
    if(st.total){ $('progBar').style.width = (100*st.processed/st.total)+'%'; }
    $('backend').innerHTML='<span class="dot on"></span>'+
      (st.running ? ('screening '+st.processed+'/'+st.total+'  '+g(st.current))
                  : 'backend connected');
    if(st.running){ setTimeout(poll, 1200); }
    else { $('prog').style.display='none'; resetButtons();
      fetch('/api/results').then(function(r){return r.json();})
        .then(function(p){ try{ render(p); }catch(e){ showError(String(e)); } }); }
  }).catch(function(e){ showError(String(e)); resetButtons(); });
}

function wire(){
  $('search').addEventListener('input', renderTable);
  $('labelFilter').addEventListener('change', renderTable);
  var ths = $('tbl').getElementsByTagName('th');
  for(var i=0;i<ths.length;i++){ (function(th){
    th.addEventListener('click', function(){
      var k=th.getAttribute('data-k'); if(!k) return;
      if(sortK===k){ sortDir*=-1; }
      else { sortK=k; sortDir = /symbol|sector|company|setup|label|weekly_trend/.test(k)?1:-1; }
      renderTable();
    });
  })(ths[i]); }

  $('btnAll').addEventListener('click', function(){
    if(BACKEND && !confirm('Screen the full US universe (~2000 tickers). '+
      'This runs one-by-one and can take a long time. Continue?')) return;
    startScreen({mode:'all'});
  });
  $('btnTick').addEventListener('click', function(){
    var raw=$('tickInput').value.trim();
    if(!raw){ $('tickInput').focus(); return; }
    var tickers = raw.split(/[\s,;]+/).filter(Boolean);
    startScreen({mode:'tickers', tickers:tickers});
  });

  // detect backend
  fetch('/api/status').then(function(r){
    if(!r.ok) throw new Error('no backend');
    return r.json();
  }).then(function(st){
    setBackend(true, 'backend connected');
    if(st.running){ $('prog').style.display='block'; poll(); }
  }).catch(function(){
    setBackend(false, 'standalone (no live runs)');
  });
}

// ---------- boot ----------
try {
  render(PAYLOAD);
  wire();
} catch(e){
  showError((e && e.message) ? e.message : String(e));
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Render dashboard from results.json")
    ap.add_argument("--results", default=str(ROOT / "output" / "results.json"))
    ap.add_argument("--out", default=str(ROOT / "output" / "dashboard.html"))
    args = ap.parse_args()
    out = build(Path(args.results), Path(args.out))
    print(f"Dashboard written -> {out}")
