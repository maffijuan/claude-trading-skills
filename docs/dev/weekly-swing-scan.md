# Weekly Swing Scan

Automated swing-trading scan that replaces manual chart-screenshot reading with
real weekly OHLCV bars fetched via **yfinance** (no FMP/FINVIZ/Alpaca key
required). It applies a numeric version of the `technical-analyst` framework,
reads market regime from `uptrend-analyzer`, sizes actionable candidates with
`position-sizer`, and emails the report.

## What it does

1. **Regime** — runs `uptrend-analyzer` (public GitHub CSV) for a 0–100 breadth
   composite, zone, and exposure guidance.
2. **Per-ticker TA (numeric)** — fetches 3y of weekly bars, reconstructs OHLCV,
   and computes SMA20/50/200, Wilder RSI(14), ATR(14), 52-week high/low,
   extension above the 20-week, and average weekly dollar volume.
3. **Classification** — `STAGE_2_UPTREND` / `TRANSITIONAL` / `STAGE_4_DOWNTREND`
   plus a setup label: `BREAKOUT_WATCH`, `RE_BREAKOUT`, `PULLBACK_WAIT`,
   `EXTENDED` (climactic — do not chase), or `AVOID_ILLIQUID`
   (< $25M average weekly dollar volume).
4. **Levels + sizing** — suggests entry/stop/2.5R target for actionable setups
   and sizes them via `position-sizer` (default $300k account, 1% risk,
   10% max position).
5. **Report + email** — writes `reports/weekly_swing_scan_<date>.{md,json}` and,
   if `--email-to` is set, emails the Markdown via SMTP.

## Run manually

```bash
pip install -r scripts/requirements-swing-scan.txt

python3 scripts/weekly_swing_scan.py \
  --tickers AMAT INTC LIN MTLS ENB \
  --account-size 300000 --risk-pct 1.0 --max-position-pct 10 \
  --output-dir reports/
# add --email-to you@example.com to send (needs SMTP_* env, see below)
```

## Scheduled run (GitHub Actions)

`.github/workflows/weekly-swing-scan.yml` runs every **Monday 10:30 ET**.
GitHub cron is UTC with no DST handling, so the workflow triggers at both
14:30 and 15:30 UTC and a guard step proceeds only when it is actually 10:xx in
`America/New_York`. `workflow_dispatch` lets you run it on demand.

### Required repository secrets

Set these under **Settings → Secrets and variables → Actions** in
`maffijuan/claude-trading-skills`:

| Secret | Value (Gmail SMTP) |
|--------|--------------------|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | your full Gmail address |
| `SMTP_PASS` | a Google **App Password** (requires 2-Step Verification enabled) |
| `EMAIL_FROM` | your Gmail address (optional; defaults to `SMTP_USER`) |
| `EMAIL_TO` | `juanmartinmaffi@gmail.com` |

> **Gmail App Password:** Google Account → Security → 2-Step Verification → App
> passwords. Use the 16-character password as `SMTP_PASS` (not your normal
> account password). Regular-password SMTP login is disabled by Google.

## Notes & limitations

- `EXTENDED` and `AVOID_ILLIQUID` setups are reported but intentionally **not**
  given entry/stop/size (no low-risk entry / fails liquidity discipline).
- DST guard relies on the runner's `TZ` support (standard on `ubuntu-latest`).
- Pure functions (`rsi`, `atr`, `sma`, `compute_indicators`, `classify_setup`,
  `suggest_levels`) are unit-tested offline in
  `scripts/tests/test_weekly_swing_scan.py`.
- yfinance reaches Yahoo Finance directly; in network-restricted environments
  (e.g. an egress allowlist) add `query1.finance.yahoo.com` and
  `query2.finance.yahoo.com` to the allowlist. GitHub-hosted runners have open
  egress, so no change is needed there.
