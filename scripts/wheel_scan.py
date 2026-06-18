#!/usr/bin/env python3
"""
Wheel-strategy candidate scanner.

- Pulls daily OHLCV from yfinance (no FMP needed), reconstructs weekly candles.
- Computes technical-analyst-framework metrics: trend vs 20/50/200 SMA, RSI(14),
  ATR(14), 52-week position, swing-low support, annualized HV (IV proxy).
- Scores "wheel suitability" (want to own it, uptrend/neutral, not overextended,
  decent premium, liquid).
- Uses the repo's Black-Scholes engine to pick a ~30-delta 1-month CSP strike,
  cross-checked against technical support; estimates premium + annualized yield.
- Flags earnings inside the 30-day window (binary risk for premium sellers).
"""
import sys, json, warnings, math
from datetime import datetime, timedelta
warnings.filterwarnings("ignore")
sys.path.insert(0, "skills/options-strategy-advisor/scripts")
from black_scholes import OptionPricer  # repo's engine

import numpy as np
import pandas as pd
import yfinance as yf

RISK_FREE = 0.043  # ~3M T-bill mid-2026
DTE = 30
TARGET_DELTA = 0.20  # ~20-delta CSP: conservative wheel entry

UNIVERSE = [
    # Mega-cap tech
    "AAPL","MSFT","GOOGL","AMZN","META","NVDA",
    # Semis
    "AMD","AVGO","MU","QCOM","TSM","INTC",
    # Software
    "CRM","ORCL","ADBE","NOW","PANW",
    # Consumer
    "COST","WMT","HD","MCD","SBUX","NKE","DIS","TGT",
    # Financials
    "JPM","BAC","GS","V","MA","SCHW",
    # Healthcare
    "UNH","JNJ","ABBV","LLY","MRK","PFE",
    # Industrials / energy
    "CAT","GE","XOM","CVX","BA",
    # Staples / telecom
    "KO","PEP","PG","T",
    # High-vol / momentum
    "TSLA","PLTR","UBER","F","BABA",
    # ETF underlyings (excellent wheel vehicles)
    "SPY","QQQ","IWM",
]

def rsi(series, n=14):
    d = series.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100/(1+rs)

def atr(df, n=14):
    h,l,c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def annualized_hv(close, window=30):
    r = np.log(close/close.shift(1))
    return float(r.tail(window).std() * np.sqrt(252))

def analyze(tkr, df):
    df = df.dropna()
    if len(df) < 210:
        return None
    c = df["Close"]
    price = float(c.iloc[-1])
    sma20 = float(c.rolling(20).mean().iloc[-1])
    sma50 = float(c.rolling(50).mean().iloc[-1])
    sma200 = float(c.rolling(200).mean().iloc[-1])
    rsi14 = float(rsi(c).iloc[-1])
    atr14 = float(atr(df).iloc[-1])
    hv30 = annualized_hv(c, 30)
    hv60 = annualized_hv(c, 60)
    hi52 = float(c.tail(252).max()); lo52 = float(c.tail(252).min())
    pos52 = (price-lo52)/(hi52-lo52) if hi52>lo52 else 0.5
    # recent swing-low support: lowest low of last ~30 sessions
    swing_low = float(df["Low"].tail(30).min())
    swing_low_60 = float(df["Low"].tail(60).min())
    advol = float((c*df["Volume"]).tail(20).mean())  # avg $ volume
    ret3m = price/float(c.iloc[-63]) - 1 if len(c) > 63 else 0.0

    # trend label
    above = sum([price>sma20, price>sma50, price>sma200])
    aligned_bull = sma20>sma50>sma200
    if price>sma200 and above>=2 and sma50>sma200:
        trend = "Uptrend" if aligned_bull else "Uptrend (mild)"
    elif price<sma200 and price<sma50:
        trend = "Downtrend"
    else:
        trend = "Sideways/Transition"

    return dict(ticker=tkr, price=price, sma20=sma20, sma50=sma50, sma200=sma200,
                rsi14=rsi14, atr14=atr14, hv30=hv30, hv60=hv60, pos52=pos52,
                hi52=hi52, lo52=lo52, swing_low=swing_low, swing_low_60=swing_low_60,
                advol=advol, ret3m=ret3m, trend=trend, above=above)

def wheel_score(m):
    """Higher = better wheel candidate. Want: own-able quality in uptrend/neutral,
    not overextended, decent premium, liquid, support not far below."""
    s = 0.0; notes = []
    # Trend: reward being above 200 (don't sell puts into a falling knife)
    if m["price"] > m["sma200"]:
        s += 25;
    else:
        s -= 20; notes.append("below 200SMA")
    if m["price"] > m["sma50"]:
        s += 10
    if m["trend"].startswith("Uptrend"):
        s += 15
    elif m["trend"] == "Downtrend":
        s -= 25
    # RSI: sweet spot 40-65 (pullback/neutral). Penalize overbought >72 and weak <35
    r = m["rsi14"]
    if 40 <= r <= 65: s += 15
    elif r > 72: s -= 12; notes.append(f"overbought RSI {r:.0f}")
    elif r < 35: s -= 8; notes.append(f"weak RSI {r:.0f}")
    else: s += 6
    # 52w position: avoid blow-off top (>0.95) and broken names (<0.25)
    p = m["pos52"]
    if 0.45 <= p <= 0.85: s += 12
    elif p > 0.95: s -= 8; notes.append("at 52w high")
    elif p < 0.25: s -= 10; notes.append("near 52w low")
    # Volatility / premium: annualized HV. Sweet spot 0.25-0.55
    v = m["hv30"]
    if 0.25 <= v <= 0.55: s += 18
    elif 0.18 <= v < 0.25: s += 10
    elif v > 0.75: s -= 10; notes.append(f"very high vol {v:.0%}")
    elif v < 0.15: s += 2; notes.append("low premium")
    else: s += 8
    # Liquidity
    if m["advol"] > 5e8: s += 10
    elif m["advol"] > 1e8: s += 6
    else: s -= 8; notes.append("thin")
    # Extension above 50SMA (don't sell puts when stretched)
    ext = (m["price"]-m["sma50"])/m["sma50"]
    if ext > 0.18: s -= 8; notes.append(f"+{ext:.0%} vs 50SMA")
    m["score"] = round(s,1); m["flags"] = notes
    return m

def strike_for_delta(S, sigma, target_delta, q=0.0):
    """Find put strike whose |delta| ~= target_delta at DTE via search."""
    T = DTE/365
    best=None
    K = S
    # scan strikes from 0.70*S to 1.0*S
    for K in np.linspace(0.70*S, 0.99*S, 120):
        try:
            p = OptionPricer(S=S, K=float(K), T=T, r=RISK_FREE, sigma=sigma, q=q)
            d = abs(p.put_delta())
        except Exception:
            continue
        if best is None or abs(d-target_delta) < best[0]:
            best=(abs(d-target_delta), float(K), d, p.put_price())
    return best  # (err, strike, delta, premium)

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    print("Downloading 1y daily data for", len(UNIVERSE), "tickers...", file=sys.stderr)
    data = yf.download(UNIVERSE, period="1y", interval="1d",
                       group_by="ticker", auto_adjust=True, progress=False, threads=True)
    rows=[]
    for t in UNIVERSE:
        try:
            df = data[t].copy() if isinstance(data.columns, pd.MultiIndex) else data.copy()
        except Exception:
            continue
        m = analyze(t, df)
        if m: rows.append(wheel_score(m))
    rows.sort(key=lambda x: x["score"], reverse=True)

    # Market regime via SPY/QQQ already in universe + ^VIX
    try:
        vix = yf.download("^VIX", period="1mo", interval="1d", progress=False, auto_adjust=True)
        vix_last = float(vix["Close"].iloc[-1])
    except Exception:
        vix_last = float("nan")

    top = rows[:14]
    # earnings dates for top candidates
    print("Fetching earnings dates for top candidates...", file=sys.stderr)
    today = datetime.utcnow().date()
    for m in top:
        ed = None
        try:
            tk = yf.Ticker(m["ticker"])
            cal = tk.get_earnings_dates(limit=8)
            if cal is not None and len(cal):
                future = [d.date() for d in cal.index if d.date() >= today]
                if future: ed = min(future)
        except Exception:
            ed = None
        m["next_earnings"] = ed.isoformat() if ed else None
        m["earnings_in_window"] = bool(ed and (ed - today).days <= DTE+2)
        # strike selection
        sigma = max(m["hv30"], 0.12)
        b = strike_for_delta(m["price"], sigma, TARGET_DELTA)
        if b:
            _, K, dlt, prem = b
            chosen = round(K, 2)
            # nearest technical support below price (30d / 60d swing low, 50SMA)
            supports = [s for s in (m["swing_low"], m["swing_low_60"], m["sma50"], m["sma200"])
                        if s < m["price"]]
            nearest_supp = max(supports) if supports else None
            # confluence: is the 30Δ strike within ~3% of a real support?
            confluence = nearest_supp is not None and abs(chosen-nearest_supp)/chosen <= 0.03
            m["csp_strike"] = chosen
            m["csp_basis"] = "~30Δ" + (" + support confluence" if confluence else "")
            m["csp_delta"] = round(dlt,3)
            m["csp_premium"] = round(prem,2)
            m["csp_pct_otm"] = round((m["price"]-chosen)/m["price"]*100,1)
            m["nearest_support"] = round(nearest_supp,2) if nearest_supp else None
            m["strike_vs_support"] = ("at/below support" if nearest_supp and chosen <= nearest_supp
                                      else "above support" if nearest_supp else "n/a")
            m["ann_yield"] = round(prem/chosen*(365/DTE)*100,1)
            m["static_yield"] = round(prem/chosen*100,2)
            m["breakeven"] = round(chosen-prem,2)

    out = dict(as_of=today.isoformat(), vix=vix_last, dte=DTE,
               risk_free=RISK_FREE, ranked=rows, top=top)
    with open("reports/wheel_scan_data.json","w") as f:
        json.dump(out, f, indent=2, default=str)

    # console summary
    print(f"\n=== MARKET REGIME ===  VIX={vix_last:.1f}")
    spy = next((r for r in rows if r["ticker"]=="SPY"), None)
    qqq = next((r for r in rows if r["ticker"]=="QQQ"), None)
    for x,lab in [(spy,"SPY"),(qqq,"QQQ")]:
        if x: print(f"  {lab}: {x['trend']}, px {x['price']:.2f}, vs200SMA {(x['price']/x['sma200']-1)*100:+.1f}%, RSI {x['rsi14']:.0f}, HV {x['hv30']:.0%}")
    print(f"\n=== TOP 14 WHEEL CANDIDATES (1mo CSP) ===")
    hdr = f"{'#':>2} {'TKR':<5} {'SCORE':>5} {'PRICE':>8} {'TREND':<18} {'RSI':>4} {'HV':>5} {'52w%':>5} {'STRIKE':>8} {'Δ':>5} {'%OTM':>5} {'PREM':>6} {'ANN%':>6} {'ERN':>4}"
    print(hdr); print("-"*len(hdr))
    for i,m in enumerate(top,1):
        ern = "⚠" if m.get("earnings_in_window") else "ok"
        print(f"{i:>2} {m['ticker']:<5} {m['score']:>5.0f} {m['price']:>8.2f} {m['trend']:<18} "
              f"{m['rsi14']:>4.0f} {m['hv30']:>5.0%} {m['pos52']*100:>4.0f}% "
              f"{m.get('csp_strike',0):>8.2f} {m.get('csp_delta',0):>5.2f} {m.get('csp_pct_otm',0):>4.1f}% "
              f"{m.get('csp_premium',0):>6.2f} {m.get('ann_yield',0):>5.1f}% {ern:>4}")
    print("\nFlags:")
    for m in top:
        if m["flags"] or m.get("earnings_in_window"):
            ef = ["earnings in window"] if m.get("earnings_in_window") else []
            print(f"  {m['ticker']}: {', '.join(m['flags']+ef)}")

if __name__=="__main__":
    main()
