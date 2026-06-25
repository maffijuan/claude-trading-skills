# Top 10 Market-Cap, Equal-Weight, Quarterly Rebalance (LEAN / QuantConnect)

A minimal, fully systematic LEAN algorithm that holds the **10 largest US-listed
companies by market capitalization**, **equal-weighted**, and **rebalanced every
quarter**.

| | |
|---|---|
| **Universe** | All US equities with point-in-time fundamental data |
| **Selection** | Top 10 by `market_cap` (price > $5 filter) |
| **Weighting** | Equal weight (10% each) |
| **Rebalance** | Quarterly (first selection of each calendar quarter) |
| **In-sample** | 2010-01-01 → 2020-12-31 |
| **Out-of-sample** | 2021-01-01 → 2025-12-31 |
| **Benchmark** | SPY |
| **Starting cash** | $100,000 |

## Files

- `main.py` — the algorithm (`Top10MarketCapEqualWeight`)
- `config.json` — LEAN CLI config with the `mode` parameter

## How to run

### QuantConnect web IDE (easiest)

1. Create a new Python algorithm and paste the contents of `main.py`.
2. **Run the in-sample test** — default `mode` is `is`, just hit *Backtest*.
3. **Run the out-of-sample test** — in *Project → Parameters*, add a parameter
   `mode = oos` (or `full`), then *Backtest* again.
   - Alternatively, change the default in `_period_for` / the `get_parameter`
     fallback, but using the parameter keeps one code path.

### LEAN CLI (local)

```bash
# in-sample (default)
lean backtest "top10-mcap-equalweight"

# out-of-sample
lean backtest "top10-mcap-equalweight" --parameter mode oos

# full 2010-2025
lean backtest "top10-mcap-equalweight" --parameter mode full
```

> Local runs need the US Equity **fundamental + price** data subscription
> (the QuantConnect data library provides this; it is survivorship-bias-free).

## Why it is built this way (backtest-expert methodology)

This repo's `skills/backtest-expert` skill drove the design choices:

- **No survivorship bias.** QuantConnect's `Fundamental` universe is
  *point-in-time*: at each quarterly selection it ranks the companies that were
  genuinely the largest *on that date*, including names later delisted, merged or
  bankrupted. We do **not** rank today's survivors back through history.
- **No look-ahead bias.** `market_cap` is read as of `self.time`, and the
  portfolio is rebalanced the **next morning (09:31)** after a new selection,
  never on the same bar that produced the ranking.
- **Zero discretion.** Ranking, weighting and cadence are 100% rule-based — no
  manual picks, no overrides.
- **Realistic friction.** Fees and slippage come from LEAN's default brokerage
  model. (Mega-cap slippage is tiny but still modeled, and IB-style commissions
  are charged on every rebalance.)
- **In-sample / out-of-sample split.** 2010–2020 develop, 2021–2025 validate.
  Compare the two: if OOS Sharpe / CAGR is well under 50% of in-sample, treat the
  edge as fragile.

## Interpreting results

After running both periods, score the validation gap and other dimensions with
the repo's evaluation script:

```bash
python3 skills/backtest-expert/scripts/evaluate_backtest.py \
  --total-trades <trades> --win-rate <pct> \
  --avg-win-pct <pct> --avg-loss-pct <pct> \
  --max-drawdown-pct <pct> --years-tested 11 \
  --num-parameters 2 --slippage-tested \
  --output-dir reports/
```

This strategy has only **2 real parameters** (`NUM_HOLDINGS=10`, `MIN_PRICE=$5`),
so it is well clear of the over-optimization flag. For robustness, re-run with
`NUM_HOLDINGS` at 5 / 15 / 20 and confirm performance is a *plateau*, not a spike.

## Caveats

- It is essentially a concentrated mega-cap momentum/size tilt; expect high
  correlation to SPY and tech-heavy concentration in the 2020s.
- Equal weight + quarterly rebalance means meaningful turnover when the ranking
  reshuffles — friction matters, which is why fees/slippage are modeled.
- No risk overlay, stop-loss or regime filter — by design, this is a baseline to
  beat, not a finished strategy.
