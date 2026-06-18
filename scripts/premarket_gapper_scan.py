#!/usr/bin/env python3
"""
Premarket Gapper Screener — daily list of tickers likely to move big at the open.

Three layers (day-trading gapper methodology + repo news framework):
  1) GAP   — premarket % change vs prior close (preMarketChangePercent, fallback intraday)
  2) RVOL  — relative volume vs 3-month average (conviction behind the gap)
  3) CATALYST — news/earnings classification (earnings, M&A, FDA, guidance, legal,
                offering, analyst...) with impact weight from corporate_news_impact.md

Discovery is market-wide via Yahoo's predefined screeners (no fixed universe needed):
  day_gainers, day_losers, most_actives, small_cap_gainers, aggressive_small_caps,
  most_shorted_stocks, growth_technology_stocks  -> union of symbols.

Best run 07:00-09:15 ET (premarket). Outside premarket it falls back to the latest
session change as a proxy and labels the report accordingly.

Usage:
  python3 scripts/premarket_gapper_scan.py [--min-gap 4] [--max-names 40] [--news-top 30]
"""
import sys, json, argparse, math, re
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None
import yfinance as yf

SCREENERS = ["day_gainers","day_losers","most_actives","small_cap_gainers",
             "aggressive_small_caps","most_shorted_stocks","growth_technology_stocks"]

# Always-watch high-beta / index names (checked even if not in a Yahoo screener)
WATCH = ["SPY","QQQ","IWM","NVDA","TSLA","AMD","AAPL","META","AMZN","MSFT","GOOGL",
         "COIN","MSTR","SMCI","PLTR","NET","MARA","NFLX","AVGO","MU","ARM"]

# Catalyst keyword -> (label, impact_weight 0-25, default_direction)
CATALYSTS = [
    ("M&A",        25, ["to acquire","acquires","acquisition of","merger","buyout","takeover bid","agrees to buy","to be acquired","tender offer","go private","all-cash deal"]),
    ("FDA/Clinical",22, ["fda","approval","phase 3","phase 2","clinical trial","topline","met primary endpoint","therapy","breakthrough designation","emergency use"]),
    ("Legal/Reg",  19, ["lawsuit","sued","sec charges","sec probe","probe","investigation into","recall","fraud","subpoena","antitrust","doj","settlement"]),
    ("Earnings",   18, ["earnings beat","earnings miss","beats estimates","misses estimates","q1 results","q2 results","q3 results","q4 results","quarterly results","tops estimates","reports q"]),
    ("Guidance",   17, ["raises guidance","cuts guidance","lowers guidance","raises outlook","cuts forecast","profit warning","warns on","preliminary results","pre-announce"]),
    ("Offering",   15, ["stock offering","share offering","priced at","convertible notes","registered direct","secondary offering","atm offering","public offering","senior notes offering"]),
    ("Contract/Deal",13,["awarded contract","wins contract","partnership with","collaboration with","selects","secures order","supply agreement"]),
    ("Analyst",     9, ["upgrades","downgrades","raises price target","cuts price target","initiates coverage","double upgrade","overweight","underweight"]),
    ("Mgmt",        8, ["ceo","cfo","resign","steps down","appoint","names new"]),
    ("Bankruptcy", 23, ["bankruptcy","chapter 11","going concern","default","delisting"]),
]

def now_et():
    if ET: return datetime.now(ET)
    return datetime.now(timezone.utc) - timedelta(hours=4)

def session_label(t):
    wd, hm = t.weekday(), t.hour*60 + t.minute
    if wd >= 5: return "WEEKEND/CLOSED"
    if 4*60 <= hm < 9*60+30: return "PREMARKET"
    if 9*60+30 <= hm < 16*60: return "REGULAR"
    if 16*60 <= hm < 20*60: return "AFTER-HOURS"
    return "CLOSED"

def pull_universe(count=50):
    quotes = {}
    for s in SCREENERS:
        try:
            r = yf.screen(s, count=count)
            for q in (r.get("quotes") or []):
                sym = q.get("symbol")
                if sym and q.get("quoteType","EQUITY") == "EQUITY":
                    q["_src"] = s
                    quotes[sym] = q
        except Exception as e:
            print(f"  screener {s} failed: {e}", file=sys.stderr)
    # add watchlist quotes
    try:
        tk = yf.Tickers(" ".join(WATCH))
        for sym in WATCH:
            if sym in quotes: continue
            try:
                fi = tk.tickers[sym].fast_info
                pc = float(fi["previousClose"]); last = float(fi["lastPrice"])
                quotes[sym] = {"symbol":sym,"regularMarketPrice":last,
                    "regularMarketPreviousClose":pc,
                    "regularMarketChangePercent":(last/pc-1)*100 if pc else None,
                    "regularMarketVolume":fi.get("lastVolume"),
                    "averageDailyVolume3Month":fi.get("threeMonthAverageVolume"),
                    "marketCap":fi.get("marketCap"),"shortName":sym,"_src":"watchlist"}
            except Exception:
                pass
    except Exception:
        pass
    return list(quotes.values())

def classify_news(items, today):
    """Return (label, weight, headline, age_h) for the strongest recent catalyst."""
    best = (None, 0, None, None)
    for it in items or []:
        c = it.get("content", it) if isinstance(it, dict) else {}
        title = (c.get("title") or it.get("title") or "")
        if not title: continue
        # pub date
        pd = c.get("pubDate") or c.get("displayTime") or it.get("providerPublishTime")
        age_h = None
        try:
            if isinstance(pd, str):
                dt = datetime.fromisoformat(pd.replace("Z","+00:00"))
            elif isinstance(pd, (int,float)):
                dt = datetime.fromtimestamp(pd, timezone.utc)
            else: dt = None
            if dt: age_h = (datetime.now(timezone.utc) - dt).total_seconds()/3600
        except Exception:
            age_h = None
        if age_h is not None and age_h > 48:   # only fresh catalysts
            continue
        tl = title.lower()
        for label, weight, kws in CATALYSTS:
            if any(k in tl for k in kws):
                if weight > best[1]:
                    best = (label, weight, title, age_h)
                break
    return best

def gap_bias(gap, rvol, catalyst, price):
    """Continuation (gap & go) vs fade heuristic — probabilistic, not certain."""
    strong_cat = catalyst in ("Earnings","M&A","FDA/Clinical","Guidance","Contract/Deal","Bankruptcy")
    if gap is None: return "n/a"
    a = abs(gap)
    if a >= 25 and not strong_cat:
        return "FADE risk (extended, weak catalyst)"
    if strong_cat and (rvol or 0) >= 2 and a < 25:
        return "Continuation likely (catalyst + RVOL)"
    if not catalyst and a >= 8:
        return "Fade/fill watch (no clear catalyst)"
    if strong_cat:
        return "Catalyst-driven (confirm at open)"
    return "Neutral / news-driven (confirm)"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-gap", type=float, default=4.0, help="min abs gap %% to include")
    ap.add_argument("--max-names", type=int, default=40)
    ap.add_argument("--news-top", type=int, default=30, help="fetch news for top N by prelim score")
    ap.add_argument("--count", type=int, default=50, help="quotes per Yahoo screener")
    ap.add_argument("--min-price", type=float, default=1.5)
    ap.add_argument("--output-dir", default="reports")
    a = ap.parse_args()
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    t = now_et(); sess = session_label(t)
    is_pre = sess == "PREMARKET"
    print(f"Session (ET {t:%Y-%m-%d %H:%M}): {sess}", file=sys.stderr)

    quotes = pull_universe(a.count)
    print(f"Universe pulled: {len(quotes)} symbols", file=sys.stderr)

    rows = []
    for q in quotes:
        sym = q.get("symbol")
        pc = q.get("regularMarketPreviousClose")
        pre_chg = q.get("preMarketChangePercent")
        reg_chg = q.get("regularMarketChangePercent")
        gap = pre_chg if pre_chg not in (None, 0) else reg_chg
        price = q.get("preMarketPrice") or q.get("regularMarketPrice")
        if gap is None or price is None: continue
        if price < a.min_price: continue
        if abs(gap) < a.min_gap: continue
        vol = q.get("regularMarketVolume") or 0
        avol = q.get("averageDailyVolume3Month") or 0
        rvol = (vol/avol) if avol else None
        mcap = q.get("marketCap")
        # preliminary score (pre-news)
        score = min(abs(gap),40)
        if rvol: score += min(rvol,10)*3
        if avol and avol > 2_000_000 and price > 5: score += 6
        elif avol and avol < 300_000: score -= 8
        rows.append(dict(symbol=sym, name=(q.get("shortName") or sym)[:24],
            gap=round(gap,2), price=round(float(price),2),
            prev_close=round(float(pc),2) if pc else None,
            rvol=round(rvol,1) if rvol else None, mktcap=mcap,
            vol=vol, avol=avol, src=q.get("_src"), prelim=round(score,1)))
    rows.sort(key=lambda x: x["prelim"], reverse=True)

    # catalyst enrichment for top N
    today = t.date()
    for m in rows[:a.news_top]:
        try:
            items = yf.Ticker(m["symbol"]).news
        except Exception:
            items = []
        label, weight, headline, age_h = classify_news(items, today)
        # earnings flag
        ern = None
        try:
            ed = yf.Ticker(m["symbol"]).get_earnings_dates(limit=6)
            if ed is not None and len(ed):
                for d in ed.index:
                    if abs((d.date()-today).days) <= 1:
                        ern = d.date().isoformat(); break
        except Exception:
            pass
        if ern and weight < 18:
            label, weight = "Earnings", 18
        m["catalyst"] = label or ("Earnings" if ern else None)
        m["cat_weight"] = weight
        m["headline"] = headline
        m["news_age_h"] = round(age_h,1) if age_h is not None else None
        m["earnings_dt"] = ern
        m["score"] = round(m["prelim"] + weight, 1)
        m["dir"] = "UP" if m["gap"] > 0 else "DOWN"
        m["bias"] = gap_bias(m["gap"], m["rvol"], m["catalyst"], m["price"])
    for m in rows[a.news_top:]:
        m["score"] = m["prelim"]; m["dir"] = "UP" if m["gap"]>0 else "DOWN"
        m["catalyst"]=None; m["bias"]=gap_bias(m["gap"],m["rvol"],None,m["price"])
    rows.sort(key=lambda x: x["score"], reverse=True)
    out = rows[:a.max_names]

    payload = dict(as_of_et=t.isoformat(), session=sess, is_premarket=is_pre,
                   min_gap=a.min_gap, count=len(rows), gappers=out)
    import os; os.makedirs(a.output_dir, exist_ok=True)
    jp = os.path.join(a.output_dir, f"premarket_gappers_{today}.json")
    json.dump(payload, open(jp,"w"), indent=2, default=str)

    def fmtcap(c):
        if not c: return "  -"
        for d,u in ((1e12,"T"),(1e9,"B"),(1e6,"M")):
            if c>=d: return f"{c/d:.1f}{u}"
        return str(c)
    src_note = "PREMARKET gaps" if is_pre else f"{sess} — using latest-session change as gap proxy (run 07:00-09:15 ET for true premarket)"
    print(f"\n=== PREMARKET GAPPER SCREEN === {t:%Y-%m-%d %H:%M ET} [{src_note}]")
    print(f"Filters: |gap| >= {a.min_gap}%, price >= ${a.min_price}, {len(out)} names\n")
    hdr=f"{'#':>2} {'DIR':<4} {'TKR':<6} {'GAP%':>7} {'PRICE':>9} {'PREVCL':>9} {'RVOL':>5} {'MCAP':>6} {'CATALYST':<13} {'BIAS':<34}"
    print(hdr); print("-"*len(hdr))
    for i,m in enumerate(out,1):
        arrow = "UP  " if m["dir"]=="UP" else "DOWN"
        print(f"{i:>2} {arrow:<4} {m['symbol']:<6} {m['gap']:>+6.1f}% {m['price']:>9.2f} "
              f"{(m['prev_close'] or 0):>9.2f} {(str(m['rvol']) if m['rvol'] else '-'):>5} "
              f"{fmtcap(m['mktcap']):>6} {(m['catalyst'] or '-'):<13} {m['bias']:<34}")
    print(f"\nTop headlines:")
    for m in out[:15]:
        if m.get("headline"):
            ageh = f"{m['news_age_h']}h" if m.get("news_age_h") is not None else "?"
            print(f"  {m['symbol']:<6} [{m['catalyst']}/{ageh}] {m['headline'][:90]}")
    print(f"\nJSON -> {jp}")

if __name__=="__main__":
    main()
