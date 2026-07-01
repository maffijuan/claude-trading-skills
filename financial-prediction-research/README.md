# Financial Prediction Research — Which Datum Best Predicts Annual Return?

A QuantConnect **Research** notebook (`feature_importance_research.ipynb`) that runs a
cross-sectional feature-importance study to answer one question:

> Out of dozens of financial data points — valuation, quality, growth, size, leverage,
> yield, momentum — **which single one carries the most weight when predicting a stock's
> next-12-month return?**

It's built to plug straight into QuantConnect Cloud or the LEAN CLI research environment
and testing right away.

---

## What it does

1. **Builds a point-in-time universe** of the ~250 most liquid US equities at eight annual
   snapshots (2016→2023) using QuantConnect's Fundamental universe — which *includes*
   later-delisted names, so the study is **survivorship-bias free**.
2. **Extracts ~14 features** per stock as of each snapshot (earnings yield, FCF yield,
   P/E, P/B, P/S, dividend yield, ROE, ROA, gross/net margin, revenue growth, EPS growth,
   debt/equity, log market cap) plus **12-1 price momentum** as a technical control.
3. **Measures the forward 12-month return** as the prediction target — strictly *after*
   the snapshot date, so there is **no look-ahead bias**.
4. **Ranks the features** by predictive power through three independent lenses:
   - **Univariate Information Coefficient (IC)** — per-year Spearman rank correlation,
     with mean IC, Information Ratio (stability), t-stat, **Bonferroni-corrected** p-value,
     and sign-consistency. *This is the headline answer.*
   - **Standardized OLS regression** — marginal contribution when features compete.
   - **Random Forest importance** — non-linear / interaction effects.
5. **Reports a consensus verdict** — the feature that ranks highly across all three lenses.

## Bias controls (from the repo's `backtest-expert` methodology)

| Bias | Control in this notebook |
|---|---|
| Survivorship | Universe rebuilt point-in-time each year; delisted names included |
| Look-ahead | Features read at date `t`; target measured over `t → t+1y` only |
| Regime / single-year luck | Features & returns rank-transformed **within each year** before pooling |
| Data mining | Bonferroni p-value correction + sign-consistency requirement across years |
| Outliers / bad ticks | Forward returns winsorized at 1/99 pct; rank-based (Spearman) statistics |

---

## How to run it on QuantConnect

### Option A — QuantConnect Cloud (easiest)
1. Log in at [quantconnect.com](https://www.quantconnect.com) → **Research** → create a new
   project (or open an existing one).
2. Upload `feature_importance_research.ipynb` (drag it into the project's file list, or
   create a notebook and paste the cells).
3. Open the notebook and **Run All**. The free tier includes the US Equity + Fundamental
   datasets this notebook uses.

### Option B — LEAN CLI (local)
```bash
pip install lean
lean login                        # once, with your QC credentials
lean init                         # if you don't already have a workspace
# copy the notebook into a project folder, then:
lean research <project-name>      # launches the Jupyter research container
```
Then open `feature_importance_research.ipynb` and Run All.

### Runtime
Eight annual snapshots × (universe history + two price-history pulls) takes a few minutes
on QC Cloud. Reduce `UNIVERSE_SIZE` or the number of `SNAPSHOT_YEARS` in the Config cell
for a faster first pass.

---

## Reading the output

- **Section 8 (IC table)** is the primary result. Look for the feature with the largest
  `abs_IC` that is **Bonferroni-significant** (`p_bonferroni < 0.05`) *and* sign-consistent
  (`sign_consistency` near 1.0). A high `IC_IR` means the edge showed up year after year,
  not just once.
- **Section 11 (verdict)** cross-checks that winner against the linear and Random-Forest
  rankings and prints the single most predictive datum.
- Results are saved to `reports/feature_ic_*.csv` and `reports/feature_consensus_*.csv`.

### A note on magnitudes
Fundamental predictive power is genuinely weak and unstable. A mean |IC| of **0.02–0.06**
is typical and can still be economically meaningful across hundreds of names. Do not expect
a large R². The value here is the *relative ranking* of which datum matters most, computed
without the biases that make naive studies look better than they are.

---

## If a feature shows `*** NOT FOUND ***`

Cell 5 prints the exact fundamental column names in your QC version and confirms each
feature resolved. QuantConnect occasionally renames flattened fields. If one prints
`NOT FOUND`, copy the real column name from the printed list into the matching
`candidates` list in `FUNDAMENTAL_FEATURES` (Section 3) and re-run — the resolver does
loose substring matching, so a partial name usually already works.

---

## Extending the study

- **More features:** add rows to `FUNDAMENTAL_FEATURES`; any Morningstar field works.
- **Different horizon:** change `HOLD_DAYS` (63 = quarterly, 21 = monthly) and add more
  snapshots for a bigger sample.
- **Sector-neutral:** rank within (year, sector) to strip out sector bets.
- **Confirm economically:** promote the winning datum to a long/short decile backtest as a
  `QCAlgorithm` — see [`../lean-backtests/`](../lean-backtests/) for a template. IC is
  necessary but not sufficient; turnover and friction can erase a paper signal.

> Educational research only. Not investment advice.
