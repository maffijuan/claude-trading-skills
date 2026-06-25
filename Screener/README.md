# US Market Screener

A heuristic **market screener** that scans the US equity universe and flags stocks
that are **bullish / showing a buy signal**. It combines multi-timeframe technical
analysis (weekly trend gate + integral daily scoring) with **sector-aware**
fundamental confirmation, and renders the conclusions in a self-contained,
semi-professional web dashboard.

> Built end-to-end from the brief in *Proyecto Market Screener.docx*. Every design
> decision below was made autonomously; this README documents **what** was built and
> **why**. Educational use only — **not investment advice**.

---

## TL;DR — run it

```bash
cd Screener
pip install -r requirements.txt

# RECOMMENDED: interactive web UI with launch buttons
python app.py                 # -> open http://127.0.0.1:5000
#   • "Screen all market"  button -> runs the full US ~2000 universe
#   • ticker box + "Screen tickers" -> runs a specific name or list (e.g. AAPL, MSFT)
#   • live progress bar; the dashboard refreshes itself when the run finishes

# OR drive it from the command line:
python screener.py --tickers AAPL,MSFT,NVDA,JPM,LLY,CAT --flush-every 5   # quick demo
python screener.py --limit 2000                                          # full universe

# Standalone (no server): double-click Screener/output/dashboard.html
#   shows the LAST saved run. The launch buttons need the server (python app.py).
```

### One-click desktop launch (Windows)

Double-click **`Start Market Screener.bat`** (in this folder) — or the **"Market
Screener"** shortcut on your Desktop — to boot the server and open the UI in your
browser automatically. Close the console window to stop it.

To (re)create the desktop shortcut yourself:

```powershell
$proj = "<path>\Screener"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) "Market Screener.lnk"))
$sc.TargetPath = Join-Path $proj "Start Market Screener.bat"
$sc.WorkingDirectory = $proj
$sc.IconLocation = (Join-Path $proj "assets\icon.ico") + ",0"
$sc.Save()
```

> Want a true single-file `.exe`? `pip install pyinstaller` then
> `pyinstaller --onefile --name MarketScreener launch.py` — but the `.bat` +
> shortcut above is lighter and needs no build step.

Outputs land in `Screener/output/`: `results.json`, `results.csv`, `dashboard.html`.

A **sample run of ~40 diverse tickers is already committed** so the dashboard shows
data out of the box.

---

## How it maps to the brief

| Requirement (from the .docx) | How it's implemented |
|---|---|
| Save everything in a `Screener/` folder | ✅ this folder |
| Determine which stocks are bullish / buy signal | `screener.py` → labels `STRONG BUY / BUY / WATCH / NEUTRAL / REJECTED` |
| Universe: **US 2000** | `universe.py` pulls ~5,400 US common stocks from the public Nasdaq directory and caps to 2,000 (configurable) |
| Time is OK; ticker count must not be a limit | Sequential engine, on-disk cache, **resumable** runs, periodic flush; `--limit 0` removes the cap |
| Data from yfinance, **one by one** (rate-limit safe) | `data.py` fetches each ticker individually with sleep + exponential backoff on HTTP 429 |
| Reconstruct **last 100 candles** of two timeframes (weekly = long term, daily = medium term) | `technical.py` fetches weekly + daily and analyzes the last 100 bars of each |
| Decide general trend on **weekly**; skip downtrends unless reversal possible | Weekly **trend gate** (`classify_weekly_trend`) — downtrends are rejected unless a reversal setup is detected |
| Apply integral TA on **daily**: momentum + structure + volume, 4–5 strongest indicators, heuristic buy/no-buy | 5-pillar daily score (structure, momentum, volume, relative strength, trend quality) |
| Add **sector-aware fundamentals** for buy candidates; solid but not over-restrictive | `fundamental.py` scores only the metrics relevant per GICS sector, moderate pass threshold |
| **Never call an LLM** — pure algorithmic heuristics, only yfinance for data | No AI/LLM calls anywhere at runtime. Only network dependency is yfinance |
| Semi-professional visualization of the key conclusions | `dashboard.py` → single self-contained HTML (KPI cards, top picks, sector mix, sortable/filterable table) |

---

## Key decisions I made (and why)

1. **Language / stack: Python.** yfinance is Python-native. Indicators are
   implemented from scratch in pandas/numpy (`indicators.py`) — no TA-Lib, so the
   project installs cleanly anywhere.

2. **"US 2000" → the 2,000-name cap over the live US common-stock list.** There is no
   free, authless feed of exact Russell-2000 membership, so I build the universe from
   the **public Nasdaq Trader symbol directory** (`nasdaqlisted.txt` +
   `otherlisted.txt`), filter to ordinary common shares (drop ETFs, warrants, units,
   preferreds, test issues), and take the first 2,000 alphabetically. The ordering and
   cap are the only interpretive choices — **the engine has no hard limit** (`--limit 0`
   screens all ~5,400). An offline fallback seed list guarantees it always runs.

3. **Two timeframes, 100 bars each, exactly as asked.** Weekly = long-term trend;
   daily = the analysis timeframe. The weekly call uses a 5y window (≈250 bars) and the
   daily a 2y window (so SMA-200 is fully formed); both are trimmed to the last 100 for
   the verdict.

4. **Weekly trend gate before any daily work** (cheap rejection, saves API calls):
   - **Up**: price > SMA30w, SMA10w > SMA30w > SMA40w, mid-MA rising.
   - **Down**: price < SMA30w, MAs stacked down, slow MA not rising → **skip**…
   - **…unless a reversal setup exists**: bullish RSI divergence *or* a reclaim of the
     fast MA, plus momentum turning up (MACD histogram / RSI recovering) — these names
     are kept and tagged `setup = reversal`.

5. **The 5 "strongest" daily indicators, grouped into integral pillars** (weights in
   `config.py`, sum to 100):

   | Pillar | Weight | Indicators / rule |
   |---|---:|---|
   | **Structure** | 30 | Minervini Stage-2 trend template (price vs SMA50/150/200, MA alignment, 200-rising, ≥25% above 52w-low, within 25% of 52w-high) + EMA21 stack |
   | **Momentum** | 25 | RSI(14) sweet-spot zoning + MACD(12,26,9) cross/sign/expansion + 20-day ROC |
   | **Volume** | 20 | Up/down-volume (accumulation) ratio + OBV slope + breakout volume vs 50-day avg |
   | **Relative strength** | 15 | Outperformance vs SPY, weighted 40/30/30 across 3m/6m/12m (CANSLIM "L") |
   | **Trend quality** | 10 | ADX(14) with +DI/−DI, minus an **overextension penalty** (don't chase climaxes) |

   These thresholds are calibrated from this repo's own skill knowledge bases
   (`technical-analyst`, `vcp-screener`, `canslim-screener`). The **buy heuristic** is
   simply: passed the weekly gate **and** daily score ≥ 62 (≥ 78 = "strong").

6. **Sector-aware fundamentals, "solid but not restrictive."** Run **only** for
   technical candidates. Each GICS sector (`config.SECTOR_PROFILES`) weights the metrics
   that actually matter for it — e.g. **banks** are judged on ROE / P-B / P-E (D/E and
   margins are meaningless for them), **utilities** on yield / leverage / ROE, **tech**
   on growth + margins. Missing data is dropped and weights renormalized, so a stock is
   never punished for a field Yahoo doesn't expose. Pass threshold is a moderate 45/100.

7. **Final signal = blend, technical-led.** `combined = 0.65·technical + 0.35·fundamental`.
   `STRONG BUY` ≥ 75 (and fundamentals pass), `BUY` ≥ 60, else `WATCH` (technical-only)
   or `NEUTRAL`.

8. **Robustness over speed (per the brief).** Sequential one-by-one fetch, 0.6s base
   spacing, exponential backoff on 429, an 18h on-disk parquet cache (re-runs are
   instant), `--resume` to continue an interrupted scan, and periodic flushing so a
   multi-hour run never loses work.

9. **Dashboard with launch buttons + self-contained fallback.** Served via `app.py`
   the dashboard has two action buttons — **Screen all market** and **Screen tickers**
   (free-text ticker/list box) — that kick off a background run with a live progress
   bar and auto-refresh on completion (`POST /api/screen`, `GET /api/status`). The same
   page also works as a **standalone file** (data inlined, opens by double-click, no
   server/internet) — there the buttons detect the missing backend and tell you to run
   `python app.py`. The render is wrapped in a try/catch that surfaces any error in a
   visible banner, and the JS is kept to widely-supported syntax (validated with an AST
   parser in the build).

---

## What the sample run produced

The committed run screened 40 diverse large-caps. Representative output:

- **STRONG BUY**: CSCO, JPM, CAT, LLY, GE, AMD — spanning Tech, Financials,
  Industrials, Healthcare.
- **BUY**: AAPL, UNH.
- **REJECTED** (weekly downtrend, never reached daily scoring): MSFT, META, HD, NKE,
  DIS, CRM, ADBE, PYPL, T.
- **NEUTRAL**: passed the weekly gate but daily score below the buy threshold.

This demonstrates each branch of the logic working (gate rejection, technical-only
WATCH/NEUTRAL, full buy with sector fundamentals).

> ⚠️ **Why a sample, not the full 2,000?** Yahoo aggressively rate-limits
> (`HTTP 429`) and a polite one-by-one scan of 2,000 names takes well over an hour
> (≈2,000 × ~2s). The engine is built to do exactly that — run
> `python screener.py --limit 2000` (ideally overnight, use `--resume` if it stops).
> I ran a representative cross-sector sample so the deliverable is demonstrably
> working without hammering the API.

---

## Project layout

```
Screener/
├── README.md           ← this file
├── requirements.txt
├── config.py           ← all tunable thresholds, weights, sector profiles
├── universe.py         ← build/cache the US ~2000 ticker list (public source)
├── data.py             ← yfinance fetch: one-by-one, backoff, parquet cache
├── indicators.py       ← pure-python TA (RSI, MACD, ADX, OBV, ATR, RS, …)
├── technical.py        ← weekly trend gate + 5-pillar daily scoring
├── fundamental.py      ← sector-aware fundamental scoring
├── screener.py         ← orchestrator (CLI, results.json/.csv, summary)
├── dashboard.py        ← self-contained HTML dashboard generator
├── app.py              ← optional Flask server
├── data/
│   ├── universe.csv    ← cached symbol list
│   └── cache/          ← per-ticker parquet/json cache (gitignored)
└── output/
    ├── results.json    ← full results + run metadata
    ├── results.csv     ← flat table
    └── dashboard.html  ← open this
```

## CLI reference

```bash
# Universe
python universe.py --limit 2000 [--refresh]        # rebuild the symbol list

# Screening
python screener.py --tickers AAPL,MSFT,...         # explicit list
python screener.py --limit 500                     # first 500 of the universe
python screener.py --limit 0                        # entire ~5,400-name universe
python screener.py --resume                         # continue an interrupted scan
python screener.py --no-dashboard                   # skip HTML regeneration

# Dashboard
python dashboard.py                                 # rebuild HTML from results.json
python app.py                                       # web UI + launch buttons @ :5000
```

### Web API (when running `app.py`)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | dashboard (buttons wired live) |
| GET | `/api/results` | current `results.json` |
| GET | `/api/status` | live run status `{running, processed, total, current}` |
| POST | `/api/screen` | start a run: `{"mode":"all"}` or `{"mode":"tickers","tickers":[...]}` |

## Tuning

Everything lives in `config.py`: indicator periods, the five pillar weights, the buy
thresholds (`TECH_BUY_THRESHOLD`, `FUND_PASS_THRESHOLD`), the overextension guards, the
technical/fundamental blend, and the per-sector fundamental profiles. No magic numbers
are buried in the engine.

## Constraints honored

- **No LLM / AI calls at runtime** — 100% deterministic heuristics.
- **Only yfinance** for data (the single network dependency, isolated in `data.py`).
- **No paid API keys** required (FMP/FINVIZ/Alpaca are *not* used).
