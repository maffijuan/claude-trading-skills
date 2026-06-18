#!/usr/bin/env python3
"""
Wheel-strategy scanner — HIGH-VOLATILITY / CASHFLOW profile.

Same engine/framework as wheel_scan.py but:
  - universe = liquid, optionable HIGH-IV names (and a few leveraged ETFs)
  - target delta 0.30 (income-oriented; richer premium, higher assignment odds)
  - scoring REWARDS high HV (premium) while still demanding an intact trend
    (above 200-SMA) and real liquidity — no selling puts into falling knives.
Reuses analyze() / strike_for_delta() / OptionPricer from wheel_scan.py.
"""
import sys, json, warnings
from datetime import datetime
warnings.filterwarnings("ignore")
sys.path.insert(0, "scripts")
sys.path.insert(0, "skills/options-strategy-advisor/scripts")
import numpy as np, pandas as pd, yfinance as yf
from black_scholes import OptionPricer
from wheel_scan import analyze, strike_for_delta, RISK_FREE, DTE

TARGET_DELTA = 0.30

UNIVERSE = [
    # AI / semis momentum (high beta)
    "NVDA","AMD","MU","MRVL","ARM","SMCI","ON","MPWR","LRCX","AVGO",
    # Crypto-levered
    "COIN","MSTR","MARA","RIOT","CLSK","HOOD",
    # EV / auto
    "TSLA","RIVN","LCID","NIO",
    # China ADRs
    "BABA","PDD","JD",
    # High-beta software
    "PLTR","NET","SNOW","CRWD","DDOG","SHOP","RBLX","U","DASH","ABNB","SNAP","ROKU","AFRM","SOFI","UPST",
    # Consumer / retail high-vol
    "CVNA","DKNG","CHWY","ETSY",
    # Biotech
    "MRNA","BNTX",
    # Energy / solar
    "ENPH","FSLR","RUN","CCJ",
    # Streaming / media
    "NFLX","UBER",
    # Leveraged ETFs (very high premium — decay risk noted)
    "TQQQ","SOXL",
]

def wheel_score_cashflow(m):
    """Reward premium (HV) but keep trend & liquidity guardrails."""
    s = 0.0; notes = []
    # Trend guardrail — selling puts on high-vol names into a downtrend is the
    # fastest way to blow up a wheel. Hard reward for above 200-SMA.
    if m["price"] > m["sma200"]: s += 22
    else: s -= 30; notes.append("below 200SMA")
    if m["price"] > m["sma50"]: s += 8
    if m["trend"].startswith("Uptrend"): s += 14
    elif m["trend"] == "Downtrend": s -= 28
    # RSI: neutral best; punish blow-off (>78) and broken (<32)
    r = m["rsi14"]
    if 42 <= r <= 68: s += 12
    elif r > 78: s -= 14; notes.append(f"overbought RSI {r:.0f}")
    elif r < 32: s -= 12; notes.append(f"weak RSI {r:.0f}")
    else: s += 5
    # 52w position: avoid blow-off top and broken names
    p = m["pos52"]
    if 0.40 <= p <= 0.88: s += 10
    elif p > 0.96: s -= 6; notes.append("at 52w high")
    elif p < 0.22: s -= 14; notes.append("near 52w low")
    # VOLATILITY = the point here. Reward HV up to a sane ceiling.
    v = m["hv30"]
    if 0.45 <= v <= 0.85: s += 26          # sweet spot for cashflow
    elif 0.35 <= v < 0.45: s += 18
    elif 0.85 < v <= 1.10: s += 16; notes.append(f"very high vol {v:.0%}")
    elif v > 1.10: s += 4; notes.append(f"extreme vol {v:.0%}")
    elif 0.28 <= v < 0.35: s += 8
    else: s -= 4; notes.append("low premium for this bucket")
    # Liquidity — mandatory for high-vol options
    if m["advol"] > 8e8: s += 12
    elif m["advol"] > 2e8: s += 7
    elif m["advol"] > 5e7: s += 2
    else: s -= 14; notes.append("thin")
    # Extension above 50SMA
    ext = (m["price"]-m["sma50"])/m["sma50"]
    if ext > 0.25: s -= 8; notes.append(f"+{ext:.0%} vs 50SMA")
    m["score"] = round(s,1); m["flags"] = notes
    return m

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    print("Downloading 1y daily data for", len(UNIVERSE), "high-vol tickers...", file=sys.stderr)
    data = yf.download(UNIVERSE, period="1y", interval="1d", group_by="ticker",
                       auto_adjust=True, progress=False, threads=True)
    rows=[]
    for t in UNIVERSE:
        try: df = data[t].copy()
        except Exception: continue
        m = analyze(t, df)
        if m: rows.append(wheel_score_cashflow(m))
    rows.sort(key=lambda x: x["score"], reverse=True)

    try:
        vix = yf.download("^VIX", period="5d", interval="1d", progress=False, auto_adjust=True)
        vix_last = float(vix["Close"].iloc[-1])
    except Exception: vix_last = float("nan")

    today = datetime.utcnow().date()
    top = rows[:14]
    print("Fetching earnings dates...", file=sys.stderr)
    for m in top:
        ed=None
        try:
            cal = yf.Ticker(m["ticker"]).get_earnings_dates(limit=8)
            if cal is not None and len(cal):
                fut=[d.date() for d in cal.index if d.date()>=today]
                if fut: ed=min(fut)
        except Exception: ed=None
        m["next_earnings"]=ed.isoformat() if ed else None
        m["earnings_in_window"]=bool(ed and (ed-today).days <= DTE+2)
        b = strike_for_delta(m["price"], max(m["hv30"],0.15), TARGET_DELTA)
        if b:
            _,K,dlt,prem=b; chosen=round(K,2)
            supports=[x for x in (m["swing_low"],m["swing_low_60"],m["sma50"],m["sma200"]) if x<m["price"]]
            ns=max(supports) if supports else None
            m["csp_strike"]=chosen; m["csp_delta"]=round(dlt,3); m["csp_premium"]=round(prem,2)
            m["csp_pct_otm"]=round((m["price"]-chosen)/m["price"]*100,1)
            m["nearest_support"]=round(ns,2) if ns else None
            m["ann_yield"]=round(prem/chosen*(365/DTE)*100,1)
            m["breakeven"]=round(chosen-prem,2)
            m["cash_per_ct"]=round(chosen*100,0)

    out=dict(as_of=today.isoformat(), vix=vix_last, dte=DTE, profile="cashflow/high-vol",
             target_delta=TARGET_DELTA, ranked=rows, top=top)
    json.dump(out, open("reports/wheel_scan_volatile_data.json","w"), indent=2, default=str)

    print(f"\n=== HIGH-VOL / CASHFLOW WHEEL (1mo CSP, ~0.30Δ) ===  VIX={vix_last:.1f}")
    hdr=f"{'#':>2} {'TKR':<5} {'SCR':>4} {'PRICE':>8} {'TREND':<16} {'RSI':>3} {'HV':>5} {'52w':>4} {'STRIKE':>9} {'Δ':>4} {'%OTM':>5} {'PREM':>6} {'ANN%':>6} {'$/ct':>8} {'ERN':>3}"
    print(hdr); print("-"*len(hdr))
    for i,m in enumerate(top,1):
        ern="!" if m.get("earnings_in_window") else "ok"
        print(f"{i:>2} {m['ticker']:<5} {m['score']:>4.0f} {m['price']:>8.2f} {m['trend']:<16} "
              f"{m['rsi14']:>3.0f} {m['hv30']:>5.0%} {m['pos52']*100:>3.0f}% {m.get('csp_strike',0):>9.2f} "
              f"{m.get('csp_delta',0):>4.2f} {m.get('csp_pct_otm',0):>4.1f}% {m.get('csp_premium',0):>6.2f} "
              f"{m.get('ann_yield',0):>5.1f}% {m.get('cash_per_ct',0):>8,.0f} {ern:>3}")
    print("\nFlags:")
    for m in top:
        ef=["EARNINGS in window"] if m.get("earnings_in_window") else []
        if m["flags"] or ef: print(f"  {m['ticker']}: {', '.join(m['flags']+ef)}")

if __name__=="__main__":
    main()
