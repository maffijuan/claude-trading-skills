# Fundamental analysis workbook builder

Systematizes the MSFT / GOOGL / PEP analysis: given a **ticker**, it produces
an Excel with the data grouped by financial statement and 11 valuation /
quality ratios computed as live formulas.

## Files

| File | Purpose |
|------|---------|
| `financial_analysis.py` | Shared writer + Yahoo Finance fetcher + CLI (`ticker -> Excel`). |
| `reorganize_existing.py` | Rebuilds the original 3-ticker workbook grouped by statement. |

Requires `openpyxl`, `pandas`, `yfinance` (all already installed). No API key.

## Generate the analysis for any ticker

```bash
# One ticker -> analyses/Analisis_AAPL.xlsx
python analyses/scripts/financial_analysis.py AAPL

# Several tickers in one workbook (one sheet each)
python analyses/scripts/financial_analysis.py MSFT GOOGL PEP -o analyses/tech.xlsx

# Choose how the trailing (incomplete-year) column is built
python analyses/scripts/financial_analysis.py PEP  --partial-method ttm
python analyses/scripts/financial_analysis.py MSFT --partial-method runrate   # default
python analyses/scripts/financial_analysis.py KO   --partial-method none      # full years only

# Sector peer medians -> drives the BUY/HOLD/SELL column
python analyses/scripts/financial_analysis.py MMM --peers GE,HON,EMR,ITW,DOV
python analyses/scripts/financial_analysis.py PEP --peers KO,CL,GIS,KHC --partial-method ttm
```

### Trailing column: run-rate vs TTM

The last column annualizes the most recent, still-incomplete fiscal year.

- **`runrate`** (default) — annualizes the fiscal-year-to-date flows
  (`flows x 4 / quarters_reported`; balance-sheet items = latest quarter).
  Reproduces the original **MSFT** column (June fiscal year, 9 months -> x12/9).
  ⚠️ Distorts **seasonal** companies (Dec fiscal year-end, consumer/retail) when
  only 1-2 weak quarters have been reported — cash-flow lines can go negative.
  The script prints a warning and adds it to the sheet in that case.
- **`ttm`** — sums the last 4 reported quarters (seasonally complete). Reproduces
  the original **PEP** column exactly. Prefer this for consumer/staples names.
- **`none`** — omit the trailing column; show full fiscal years only.

## Layout

Each sheet groups line items by source statement, then the ratios:

- **Income Statement** — Revenue, EBITDA, EBIT, Net income, D&A
- **Balance Sheet** — Total assets, Cash & marketable sec., Non-marketable sec.,
  Current liabilities, Capital employed*, Equity, Total liabilities,
  Total debt, Net debt
- **Cash Flow** — Operating CF, Cash dividend paid, Repurchase of capital stock,
  CapEx, Free cash flow
- **Market data** — Shares, Price, Market cap.*
- **Ratios** — (1) ΔRevenue, (2) ΔNet income, (3) P/E trailing + Forward P/E,
  (4) ROCE / Mod. ROCE, (5) EV/EBITDA, (6) P/B, (7) P/S, (8) EV/FCF,
  (9) Dividend yield, (10) Total shareholder return, (11) CapEx/EBITDA,
  (12) CapEx/D&A, (13) Ratio de endeudamiento, (14) Deuda financiera neta /
  activos (libros), (15) Deuda financiera neta / market cap,
  (16) Price estimate (Trefis)

`*` = live Excel formula. All ratios are formulas too, so editing an input
recomputes everything.

### Recommendation column (BUY / HOLD / SELL)

The ratios block has two extra columns:

- **Peer median** — the sector median for each ratio, auto-computed from
  `--peers` (or type it in by hand). Blank without peers.
- **Rec.** — a live Excel formula that reads the latest period and returns
  `BUY` / `HOLD` / `SELL` (green / amber / red via conditional formatting).

Decision rules (all thresholds are editable directly in the formulas):

| Ratio(s) | Basis | BUY | SELL |
|----------|-------|-----|------|
| P/E, Fwd P/E, EV/EBITDA, P/B, P/S, EV/FCF | vs **peer median** | < 0.9× median | > 1.1× median |
| Δ Revenue, Δ Net income | absolute | ≥ +10% | < 0% |
| ROCE | absolute | ≥ 15% | < 8% |
| Total shareholder return | absolute | ≥ 5% | < 2% |
| Dividend yield | absolute | ≥ 3% | < 1% |
| Ratio de endeudamiento (debt/assets) | absolute (low good) | ≤ 30% | > 60% |
| Deuda neta / activos (libros) | absolute (low good) | ≤ 20% | > 40% |
| Deuda neta / market cap | absolute (low good) | ≤ 15% | > 40% |
| Price estimate (Trefis) | vs current price | > +10% | < −10% |

Valuation multiples stay blank until a peer median exists (relative call only).
`Modified ROCE`, `CapEx/EBITDA`, `CapEx/D&A` are informational — peer median is
shown but no recommendation is emitted.

### Manual columns / rows (filled by hand, blank on generation)

- **Peer median** — auto-filled with `--peers`; otherwise type it in.
- **Price estimate (Trefis)** row — external analyst target (feeds its Rec.).
- **Dividend yield** — best-effort from Yahoo; verify or overwrite.

### Handling of negative-earnings years

`Δ Net income (YoY)` returns `"n.m."` (not meaningful) when the prior year's net
income was ≤ 0, since a percentage change off a negative base is meaningless.
Forward P/E then falls back to trailing P/E for that column (via `ISNUMBER`),
so no formula errors propagate.

## Notes / caveats

- Data comes from Yahoo Finance; figures for the three original tickers match the
  hand-entered workbook to the dollar for full fiscal years.
- **Non-marketable securities** and **dividend yield** are best-effort: Yahoo's
  balance-sheet labels don't always match a custom cash / equity-stake split.
  Review those two rows before relying on EV-based ratios.
- Historical prices are the monthly close nearest each fiscal year-end; the
  trailing column uses the current price.
- `EV/EBITDA` is standardized to EBITDA for every year (the original workbook
  used EBIT for the 2023 column only — a bug that is fixed here).
