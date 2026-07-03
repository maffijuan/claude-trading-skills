# Fundamental Analyzer — dashboard

Interactive web UI over `../scripts/financial_analysis.py`. No terminal commands
per ticker: type a symbol (or a list, or a preset universe) and read the results.

Three ways to use it:

- **Live server** (`app.py`) — analyze any ticker on demand; needs Python + Flask.
- **Static report** (`build_static.py`) — a single self-contained `.html` file
  you can email to anyone. Opens with a double-click, **no install, no server**,
  works on any PC/Mac. Fully interactive (filter, sort, drill-down, CSV + Excel
  export); data is frozen at generation time.
- **Deployed URL** — host `app.py` on a free service so the whole team analyzes
  live with zero install. See [`DEPLOY.md`](DEPLOY.md) (Render one-click via
  `render.yaml`; optional password gate via the `DASH_PASSWORD` env var).

## Who needs to install what?

- **The people you share the report with (boss, team): nothing.** They just
  double-click the `.html`. It runs entirely in the browser — data and code are
  baked in. No Python, no terminal, works offline on any Windows PC or Mac.
- **You (the one generating the report): Python once.** Either run the command
  below, or **double-click `Generar_Reporte.bat`** (Windows) so you don't touch
  the terminal either. `Iniciar_Dashboard.bat` launches the live server the same
  way.

> A loose `.html` cannot fetch *new* live data (browsers can't call Yahoo
> cross-origin), so the report is a snapshot — regenerate for fresh numbers. For
> live arbitrary-ticker analysis by the whole team, deploy the server to a URL.

## Static report — share with anyone (zero install)

```bash
python analyses/dashboard/build_static.py AAPL MSFT PEP --method ttm
python analyses/dashboard/build_static.py --universe djia
python analyses/dashboard/build_static.py --universe dax  -o dax_report.html
python analyses/dashboard/build_static.py --universe sp500  # ~500 tickers, a few minutes
```

…or just double-click **`Generar_Reporte.bat`** and answer the prompt.

Writes to `analyses/reports/Analisis_<name>_<date>.html` (or `-o`). Send that one
file — the recipient double-clicks it, no Python needed. It contains the batch
table (click any ticker for its full statements + ratios) and **⬇ CSV** +
**⬇ Excel** export buttons (the XLSX is written client-side, no dependency).
Regenerate whenever you want fresh numbers.

Flags: `--universe {djia,sp500,nasdaq100,stoxx50,ftse100,dax}`, `--method {runrate,ttm,none}`,
`--years N`, `--peers A,B,C`, `--no-self-peer`, `--with-trefis`, `--title "..."`,
`--as-of YYYY-MM-DD`, `-o out.html`.

## Run

```bash
pip install flask            # only extra dependency (yfinance/openpyxl already used)
python analyses/dashboard/app.py --open      # opens http://127.0.0.1:5000
# options: --port 8000  --host 0.0.0.0  --debug
```

Then open `http://127.0.0.1:5000`.

## What it does

**One ticker → full detail.** Statements grouped by source (Income Statement /
Balance Sheet / Cash Flow / Market Data) for every fiscal year + the trailing
column, then the 17 valuation & quality ratios with the **Peer median** and a
**BUY / HOLD / SELL** badge each. A ⬇ button downloads the same analysis as the
live-formula Excel.

**Many tickers → batch view.** One compact row per ticker (no raw annual data —
that would be a wall of numbers), showing the last-period value of every ratio
tinted by its recommendation, a per-ticker **score** (BUY − SELL) and BUY/HOLD/
SELL tally. Rows sort by score. Click a ticker to drill into its full detail.

## Controls

| Control | Effect |
|---|---|
| Ticker(s) | one symbol = detail; comma / space / newline separated = batch |
| Período parcial | `runrate` (annualized YTD), `ttm` (last 4Q), `none` (full years) |
| Años | number of full fiscal years (1–6) |
| Peers | explicit peer set for the multiple medians (e.g. `GE, HON, EMR`) |
| Batch: comparar contra mediana del universo | when no explicit peers, judge each ticker's multiples against the **batch's own median** (relative value within the group) |
| Traer Trefis | best-effort fetch of the Trefis estimate (public feed, ~200 tickers); off by default → the row stays blank for manual entry |
| Índices | presets: DJIA, S&P 500, NASDAQ 100, STOXX 50, FTSE 100, DAX (constituents bundled in `indices.py`) |

## How recommendations are decided

Same rules as the Excel `Rec.` column (see `../scripts/README.md`):
valuation multiples are judged **relative to the peer / universe median**
(cheaper = BUY); growth, ROCE, TSR, dividend yield and leverage use absolute
thresholds; Trefis compares its estimate to the current price. `Modified ROCE`
and the two CapEx ratios are informational (no badge).

## Single-ticker view (semi-pro layout)

For one ticker the page leads with the **decision**, not the raw data:

1. **Valuation & Quality Ratios first** — the full ratio table with peer medians
   and BUY/HOLD/SELL up top.
2. **Charts** (inline SVG, no library, theme-aware):
   - Revenue vs Net income by year (grouped bars),
   - EBIT & Net margin trend (lines),
   - **Valuation vs peer median** — one bar per multiple, coloured by its
     recommendation, with the peer median as a dashed marker.
3. **Raw financial statements** are tucked into **collapsible** sections
   (Income Statement / Balance Sheet / Cash Flow / Market Data) — open on demand.

### Automatic sector peers (S&P GICS)

Leave the Peers box empty and the multiples are compared against **real sector
peers** from the S&P 500 (bundled GICS map in `sp500.py`): it picks names in the
same GICS **sub-industry** first, then fills from the sector. Toggle with the
"Peers automáticos (sector S&P)" checkbox, or type your own peers to override.
Static single-ticker reports (`build_static.py TICKER`) do the same automatically.

## Banks & financials

Banks/insurers (GS, JPM, AXP…) don't report EBITDA, EBIT or current liabilities,
so `ROCE`, `Acid ROCE`, `EV/EBITDA`, `EV/FCF` and the CapEx ratios are genuinely
N/A for them — those cells show a grey **"n/a"** (not a data error) and the
ticker is tagged 🏦. To value them fairly the table always includes **ROE**
(net income / equity) and **P/TBV** (price / tangible book = equity − goodwill −
intangibles), which do apply to banks. The flag is data-driven (financial sector
*and* EBITDA missing), so payment networks like Visa/Mastercard — which do report
EBITDA — are treated normally.

## Index universes & batched fetching

The preset buttons load full index constituents (bundled in `indices.py`, sourced
from Wikipedia GICS/ICB tables): **DJIA (30), S&P 500 (503), NASDAQ 100 (101),
STOXX 50 (50), FTSE 100 (100), DAX (40)**. On first load the dashboard shows the
**DJIA valuation** by default.

- European names use Yahoo suffixes (`.DE`, `.PA`, `.AS`, `.L`, `.SW`…) and are
  reported in their own currency (the single-ticker unit label shows €/£/CHF);
  ratios are currency-neutral so cross-index comparison still works.
- yfinance has no batch endpoint for financial statements, so large sweeps are
  fetched in **throttled chunks** (`map_tickers_chunked`: 40 per chunk, 6 workers,
  pause between chunks, one retry on failure) to avoid rate-limit errors.
- The live batch is capped at 520 tickers. A full **S&P 500** sweep works but
  takes a few minutes and can exceed a deployed host's request timeout — prefer
  the **static report generator** for the big indices.

## Notes
- Dividend yield is computed (`dividends / market cap`); Trefis and manual peer
  medians are the only fields you may still fill by hand.
- This is Flask's dev server — fine for local use, not for public deployment.
