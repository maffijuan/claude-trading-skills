/* Shared UI helpers for the live dashboard AND the static report.
   These functions are pure: they take a data object and return an HTML string.
   Each page supplies its own controller (fetch-based vs embedded DATA). */

// ---------- theme ----------
function setupTheme(btnSel){
  const btn = document.querySelector(btnSel);
  const apply = t => {document.documentElement.dataset.theme=t; localStorage.faTheme=t;
    if(btn) btn.textContent = t==='dark' ? '☀ Light':'☾ Dark';};
  apply(localStorage.faTheme || 'light');
  if(btn) btn.onclick = ()=>apply(document.documentElement.dataset.theme==='dark'?'light':'dark');
}

// ---------- formatting ----------
const _nf0 = new Intl.NumberFormat('en-US',{maximumFractionDigits:0});
const _nf2 = new Intl.NumberFormat('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
function fmt(v, kind){
  if(v===null||v===undefined) return '<span class="muted">—</span>';
  if(kind==='pct')  return (v*100).toFixed(1)+'%';
  if(kind==='pct2') return (v*100).toFixed(2)+'%';
  if(kind==='mult') return v.toFixed(1)+'x';
  if(kind==='price')return _nf2.format(v);
  return _nf0.format(v);
}
const badge = r => r ? `<span class="badge ${r}">${r}</span>` : '';
const SHORT = {dRev:'ΔRev',dNI:'ΔNI',pe_ttm:'P/E',fwd_pe:'FwdP/E',roce:'ROCE',roe:'ROE',mod_roce:'aROCE',
  ev_ebitda:'EV/EBITDA',pb:'P/B',ptbv:'P/TBV',ps:'P/S',ev_fcf:'EV/FCF',DY:'DY',tsr:'TSR',capex_ebitda:'Cx/EB',
  capex_da:'Cx/D&A',debt_assets:'Debt/A',debt_book:'ND/A',debt_mkt:'ND/Mcap'};

// blank cell: plain "—", or "n/a" (grey, tooltip) when structurally N/A for a bank
// ratios where a null = "not meaningful" (negative/invalid denominator, e.g. P/B
// with negative equity, P/E with losses) rather than genuinely missing data.
const NM_KEYS = ['pe_ttm','fwd_pe','roce','roe','mod_roce','ev_ebitda','pb','ptbv',
  'ev_fcf','capex_ebitda'];
function cellText(v, kind, key, isFin, bankNa){
  if(v===null||v===undefined){
    if(isFin && bankNa && bankNa.indexOf(key)>=0)
      return '<span class="muted" title="No aplica a bancos / financieras">n/a</span>';
    if(NM_KEYS.indexOf(key)>=0)
      return '<span class="muted" title="No significativo (denominador negativo: p.ej. equity o ganancias < 0)">n/m</span>';
    return '<span class="muted">—</span>';
  }
  return fmt(v, kind);
}

// ===== SVG charts (self-contained, no library) =====
function _statVals(d, group, inc){
  const rows=d.statements[group]||[]; const r=rows.find(x=>x.label.indexOf(inc)>=0);
  return r?r.values:null;
}
function _compact(v){
  if(v===null||v===undefined) return '';
  const a=Math.abs(v);
  if(a>=1000) return (v/1000).toFixed(a>=10000?0:1)+'B';   // $M -> $B
  return v.toFixed(0);
}
function _lg(items){ return items.map(i=>`<span><i style="background:${i.c}"></i>${i.n}</span>`).join(''); }
function chartCard(title, legend, svg){ return `<div class="chart"><h4>${title}</h4><div class="lg">${legend}</div>${svg}</div>`; }

function svgGroupedBars(cats, series){
  const W=520,H=250,L=52,R=14,T=12,B=40, pw=W-L-R, ph=H-T-B;
  const vals=[]; series.forEach(s=>s.values.forEach(v=>{ if(v!=null) vals.push(v); }));
  const mx=Math.max(0,...vals), mn=Math.min(0,...vals), span=(mx-mn)||1;
  const y=v=>T+ph-((v-mn)/span)*ph, y0=y(0);
  const n=cats.length, gw=pw/n, ns=series.length, bw=Math.min(28,(gw-12)/ns);
  let g='';
  [mn,mx].forEach(gv=>{ const yy=y(gv);
    g+=`<line class="gridline" x1="${L}" x2="${W-R}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"/>`+
       `<text class="axlbl" x="${L-6}" y="${(yy+3).toFixed(1)}" text-anchor="end">${_compact(gv)}</text>`; });
  cats.forEach((c,i)=>{ const gx=L+i*gw+gw/2;
    series.forEach((s,si)=>{ const v=s.values[i]; if(v==null) return;
      const bx=gx-(ns*bw)/2+si*bw+1, top=Math.min(y(v),y0), h=Math.max(1,Math.abs(y(v)-y0));
      g+=`<rect x="${bx.toFixed(1)}" y="${top.toFixed(1)}" width="${(bw-2).toFixed(1)}" height="${h.toFixed(1)}" rx="2.5" fill="${s.color}"><title>${s.name} ${c}: ${_compact(v)}</title></rect>`; });
    g+=`<text class="axlbl" x="${gx.toFixed(1)}" y="${H-B+15}" text-anchor="middle">${c}</text>`; });
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}

function svgLines(cats, series, yfmt){
  const W=520,H=250,L=48,R=14,T=12,B=40, pw=W-L-R, ph=H-T-B;
  const vals=[]; series.forEach(s=>s.values.forEach(v=>{ if(v!=null) vals.push(v); }));
  const mx=Math.max(0,...vals), mn=Math.min(0,...vals), span=(mx-mn)||1;
  const y=v=>T+ph-((v-mn)/span)*ph, n=cats.length, x=i=> n>1? L+(i/(n-1))*pw : L+pw/2;
  let g='';
  [mn,(mn+mx)/2,mx].forEach(gv=>{ const yy=y(gv);
    g+=`<line class="gridline" x1="${L}" x2="${W-R}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"/>`+
       `<text class="axlbl" x="${L-6}" y="${(yy+3).toFixed(1)}" text-anchor="end">${yfmt(gv)}</text>`; });
  cats.forEach((c,i)=> g+=`<text class="axlbl" x="${x(i).toFixed(1)}" y="${H-B+15}" text-anchor="middle">${c}</text>`);
  series.forEach(s=>{ const pts=[];
    s.values.forEach((v,i)=>{ if(v!=null) pts.push([x(i),y(v)]); });
    if(pts.length) g+=`<polyline fill="none" stroke="${s.color}" stroke-width="2" points="${pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}"/>`;
    s.values.forEach((v,i)=>{ if(v!=null) g+=`<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3.2" fill="${s.color}"><title>${s.name} ${cats[i]}: ${yfmt(v)}</title></circle>`; });
  });
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}

function svgValuation(rows){
  const W=520,rowH=36,H=rows.length*rowH+12,L=92,R=58, pw=W-L-R;
  let g='';
  rows.forEach((r,i)=>{ const cy=8+i*rowH+rowH/2;
    const mx=(Math.max(r.value, r.peer||0)*1.25)||1, bw=(r.value/mx)*pw;
    const col = r.rec==='BUY'?'var(--buy)':r.rec==='SELL'?'var(--sell)':r.rec==='HOLD'?'var(--hold)':'var(--series-1)';
    g+=`<text class="axlbl" x="${L-8}" y="${(cy+4).toFixed(1)}" text-anchor="end">${r.label}</text>`;
    g+=`<rect x="${L}" y="${(cy-9).toFixed(1)}" width="${Math.max(2,bw).toFixed(1)}" height="18" rx="3" fill="${col}" opacity="0.85"><title>${r.label}: ${fmt(r.value,r.fmt)} (${r.rec||'n/a'})</title></rect>`;
    g+=`<text class="val" x="${(L+bw+6).toFixed(1)}" y="${(cy+4).toFixed(1)}">${fmt(r.value,r.fmt)}</text>`;
    if(r.peer!=null){ const px=L+(r.peer/mx)*pw;
      g+=`<line x1="${px.toFixed(1)}" x2="${px.toFixed(1)}" y1="${(cy-13).toFixed(1)}" y2="${(cy+13).toFixed(1)}" stroke="var(--ink-2)" stroke-width="2" stroke-dasharray="2 2"><title>peer median: ${fmt(r.peer,r.fmt)}</title></line>`; }
  });
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
}

function chartsHTML(d){
  const cats=d.periods;
  const rev=_statVals(d,'Income Statement','Revenue');
  const ni=_statVals(d,'Income Statement','Net income');
  const ebit=_statVals(d,'Income Statement','EBIT');
  let cards='';
  if(rev) cards+=chartCard('Revenue vs Net income ('+d.unit_label+')',
    _lg([{n:'Revenue',c:'var(--series-1)'},{n:'Net income',c:'var(--series-2)'}]),
    svgGroupedBars(cats,[{name:'Revenue',color:'var(--series-1)',values:rev},
                         {name:'Net income',color:'var(--series-2)',values:ni||[]}]));
  if(rev&&ebit&&ni){
    const em=rev.map((r,i)=> (r&&ebit[i]!=null)? ebit[i]/r : null);
    const nm=rev.map((r,i)=> (r&&ni[i]!=null)? ni[i]/r : null);
    cards+=chartCard('Márgenes (EBIT / Net)',
      _lg([{n:'EBIT margin',c:'var(--series-1)'},{n:'Net margin',c:'var(--series-2)'}]),
      svgLines(cats,[{name:'EBIT margin',color:'var(--series-1)',values:em},
                     {name:'Net margin',color:'var(--series-2)',values:nm}], v=>(v*100).toFixed(0)+'%'));
  }
  const rmap={}; d.ratios.forEach(r=>rmap[r.key]=r); const last=cats.length-1;
  const vrows=[];
  [['pe_ttm','P/E'],['ev_ebitda','EV/EBITDA'],['pb','P/B'],['ptbv','P/TBV'],['ps','P/S']].forEach(([k,lbl])=>{
    const r=rmap[k]; if(r&&r.values[last]!=null&&r.peer!=null)
      vrows.push({label:lbl,value:r.values[last],peer:r.peer,rec:r.rec,fmt:r.fmt}); });
  if(vrows.length) cards+=chartCard('Valuación vs mediana de peers',
    '<span>barra = ticker · <span style="border-left:2px dashed var(--ink-2);padding-left:4px">línea = peer</span> · color = recomendación</span>',
    svgValuation(vrows));
  return cards ? `<div class="sec-title">Gráficos</div><div class="charts">${cards}</div>` : '';
}

// ---------- single-ticker detail (valuation first, raw data collapsible) ----------
function singleHTML(d, excelHref){
  const per = d.periods, isFin = d.is_financial, bankNa = d.bank_na_keys;
  const dl = excelHref ? `<a class="dl" href="${excelHref}">⬇ Descargar Excel</a>` : '';
  const secTag = d.sector ? `<span class="chip" style="font-weight:500">${d.sector}${isFin?' 🏦':''}</span>` : '';
  const peerLine = (d.peers&&d.peers.length)
    ? `${d.peers.join(', ')}${d.peer_source?` (${d.peer_source})`:''}` : '—';
  let html = `<div class="card">
    <div class="toolbar">
      <h2 class="tk">${d.ticker}</h2>${secTag}
      <span class="chip"><span class="dot" style="background:var(--buy)"></span>${d.tally.BUY} BUY</span>
      <span class="chip"><span class="dot" style="background:var(--hold)"></span>${d.tally.HOLD} HOLD</span>
      <span class="chip"><span class="dot" style="background:var(--sell)"></span>${d.tally.SELL} SELL</span>
      <div class="spacer"></div>${dl}
    </div>
    <div class="hint">Unidades: ${d.unit_label} (excepto precio y ratios). Peers: ${peerLine}</div>`;
  if(isFin) html += `<div class="hint" style="color:var(--accent)">Financiera: EBITDA / EBIT / ROCE / EV no aplican (marcados “n/a”). Usá ROE y P/TBV para valuar.</div>`;

  // 1) Valuation & recommendations FIRST
  html += `<div class="sec-title">Valuation &amp; Quality Ratios</div><div class="scroll"><table><thead><tr><th>Ratio</th>`;
  per.forEach(p=>html+=`<th>${p}</th>`); html+='<th>Peer med.</th><th>Rec.</th></tr></thead><tbody>';
  d.ratios.forEach(r=>{ html+=`<tr><td>${r.label}</td>`;
    r.values.forEach(v=>html+=`<td class="num">${cellText(v,r.fmt,r.key,isFin,bankNa)}</td>`);
    html+=`<td class="peerv">${r.peer!=null?fmt(r.peer,r.fmt):'—'}</td>`;
    html+=`<td>${badge(r.rec)}</td></tr>`; });
  html+='</tbody></table></div>';

  // 2) Charts
  try{ html += chartsHTML(d); }
  catch(e){ html += '<div class="hint err">No se pudieron generar los gráficos.</div>'; }

  // 3) Raw data (collapsible)
  html += `<div class="sec-title">Datos financieros (raw)</div>`;
  for(const grp of Object.keys(d.statements)){
    html += `<details class="raw"><summary>${grp}</summary><div class="scroll"><table><thead><tr><th>Línea</th>`;
    per.forEach(p=>html+=`<th>${p}</th>`); html+='</tr></thead><tbody>';
    d.statements[grp].forEach(row=>{ html+=`<tr><td>${row.label}</td>`;
      row.values.forEach(v=>html+=`<td class="num">${fmt(v,row.fmt)}</td>`); html+='</tr>'; });
    html+='</tbody></table></div></details>';
  }

  if(d.notes&&d.notes.length){ html+='<div class="hint" style="margin-top:12px">'+d.notes.map(n=>'• '+n).join('<br>')+'</div>'; }
  html+=`<div class="hint">${d.source_note||''}</div></div>`;
  return html;
}

// ---------- batch table ----------
function batchHTML(d, extraToolbar){
  const order = d.ratio_order, labels = d.ratio_labels;
  let html = `<div class="card">
    <div class="toolbar"><strong>${d.rows.length} tickers</strong>
      <span class="hint">ordenados por score (BUY − SELL). Base de múltiplos: ${d.peer_basis}. Click en el ticker para el detalle.</span>
      <div class="spacer"></div>${extraToolbar||''}</div>
    <div class="scroll"><table><thead><tr>
      <th>Ticker</th><th>Precio</th><th>Score</th>`;
  order.forEach(k=>html+=`<th title="${labels[k]}">${SHORT[k]||k}</th>`);
  html+='</tr></thead><tbody>';
  const bankNa = d.bank_na_keys;
  d.rows.forEach(r=>{
    const finTag = r.is_financial ? ' 🏦' : '';
    html+=`<tr><td class="tickcell" data-t="${r.ticker}" title="${r.sector||''}">${r.ticker}${finTag}</td>`;
    html+=`<td class="num">${fmt(r.price,'price')}</td>`;
    const sc=r.score, col = sc>0?'var(--buy)':sc<0?'var(--sell)':'var(--muted)';
    html+=`<td class="score" style="color:${col}">${sc>0?'+':''}${sc}</td>`;
    order.forEach(k=>{ const c=r.cells[k];
      html+=`<td class="num cell-${c.rec}" title="${labels[k]} — ${c.rec||'n/a'}">${cellText(c.value,c.fmt,k,r.is_financial,bankNa)}</td>`; });
    html+='</tr>';
  });
  html+='</tbody></table></div>';
  if(d.errors&&d.errors.length){ html+='<div class="hint err" style="margin-top:10px">No se pudieron cargar: '+
    d.errors.map(e=>e.ticker||e).join(', ')+'</div>'; }
  html+='<div class="legend" style="margin-top:12px">Columnas = ratios (hover para nombre completo). Color de celda = recomendación.</div></div>';
  return html;
}

// ---------- CSV export of a batch ----------
function batchToCSV(d){
  const order = d.ratio_order, labels = d.ratio_labels;
  const head = ['Ticker','Price','Score', ...order.map(k=>labels[k])];
  const lines = [head.join(',')];
  d.rows.forEach(r=>{
    const row = [r.ticker, r.price!=null?r.price.toFixed(2):'', r.score,
      ...order.map(k=>{ const v=r.cells[k].value; return v!=null? (Math.round(v*10000)/10000):''; })];
    lines.push(row.join(','));
  });
  return lines.join('\n');
}
function downloadCSV(text, name){
  downloadBlob(new Blob([text],{type:'text/csv;charset=utf-8'}), name);
}
function downloadBlob(blob, name){
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 1000);
}

// ---------- minimal, dependency-free XLSX writer (store-only ZIP) ----------
const _CRC = (()=>{ const t=new Uint32Array(256);
  for(let n=0;n<256;n++){ let c=n; for(let k=0;k<8;k++) c=(c&1)?(0xEDB88320^(c>>>1)):(c>>>1); t[n]=c>>>0; }
  return t; })();
function crc32(bytes){ let c=0xFFFFFFFF;
  for(let i=0;i<bytes.length;i++) c=_CRC[(c^bytes[i])&0xFF]^(c>>>8);
  return (c^0xFFFFFFFF)>>>0; }
const _enc = s => new TextEncoder().encode(s);
const _xmlEsc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function _colName(i){ let s=''; i++; while(i>0){ const m=(i-1)%26; s=String.fromCharCode(65+m)+s; i=(i-(m+1))/26|0; } return s; }

// aoa: array of rows; each cell is a number, a string, or null (blank).
function buildXLSX(sheetName, aoa){
  let sd='';
  aoa.forEach((row,r)=>{ sd+=`<row r="${r+1}">`;
    row.forEach((v,c)=>{ if(v===null||v===undefined||v==='') return;
      const ref=_colName(c)+(r+1);
      if(typeof v==='number' && isFinite(v)) sd+=`<c r="${ref}"><v>${v}</v></c>`;
      else sd+=`<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${_xmlEsc(v)}</t></is></c>`;
    });
    sd+='</row>';
  });
  const files={
    '[Content_Types].xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>`,
    '_rels/.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
    'xl/workbook.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${_xmlEsc(sheetName).slice(0,31)}" sheetId="1" r:id="rId1"/></sheets></workbook>`,
    'xl/_rels/workbook.xml.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>`,
    'xl/worksheets/sheet1.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${sd}</sheetData></worksheet>`,
  };
  return _zipStore(files);
}

function _zipStore(files){
  const chunks=[], central=[]; let offset=0;
  const u16=n=>[n&255,(n>>8)&255], u32=n=>[n&255,(n>>8)&255,(n>>16)&255,(n>>>24)&255];
  for(const name in files){
    const nameB=_enc(name), data=_enc(files[name]), crc=crc32(data);
    const lh=[].concat([0x50,0x4b,0x03,0x04],u16(20),u16(0),u16(0),u16(0),u16(0),
      u32(crc),u32(data.length),u32(data.length),u16(nameB.length),u16(0));
    chunks.push(new Uint8Array(lh), nameB, data);
    const ch=[].concat([0x50,0x4b,0x01,0x02],u16(20),u16(20),u16(0),u16(0),u16(0),u16(0),
      u32(crc),u32(data.length),u32(data.length),u16(nameB.length),u16(0),u16(0),u16(0),u16(0),u32(0),u32(offset));
    central.push(new Uint8Array(ch), nameB);
    offset += lh.length + nameB.length + data.length;
  }
  let cdSize=0; central.forEach(c=>cdSize+=c.length);
  const cdOffset=offset;
  const eocd=[].concat([0x50,0x4b,0x05,0x06],u16(0),u16(0),u16(Object.keys(files).length),
    u16(Object.keys(files).length),u32(cdSize),u32(cdOffset),u16(0));
  const parts=[...chunks,...central,new Uint8Array(eocd)];
  let total=0; parts.forEach(p=>total+=p.length);
  const out=new Uint8Array(total); let pos=0;
  parts.forEach(p=>{ out.set(p,pos); pos+=p.length; });
  return out;
}

// batch -> array-of-arrays (Ticker, Price, Score, then each ratio value)
function batchToAOA(d){
  const order=d.ratio_order, labels=d.ratio_labels;
  const rows=[['Ticker','Price','Score',...order.map(k=>labels[k])]];
  d.rows.forEach(r=>{
    rows.push([r.ticker, r.price!=null?r.price:null, r.score,
      ...order.map(k=>{ const v=r.cells[k].value; return v!=null?v:null; })]);
  });
  return rows;
}

// ---------- shared export buttons ----------
function exportButtonsHTML(){
  return '<button class="ghost" id="csv">⬇ CSV</button><button class="ghost" id="xlsx">⬇ Excel</button>';
}
function wireExports(batch, stem){
  const c=document.querySelector('#csv'), x=document.querySelector('#xlsx');
  if(c) c.onclick=()=>downloadCSV(batchToCSV(batch), (stem||'analysis')+'.csv');
  if(x) x.onclick=()=>downloadBlob(new Blob([buildXLSX('Batch', batchToAOA(batch))],
    {type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}), (stem||'analysis')+'.xlsx');
}
