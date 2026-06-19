---
name: after-hours-market-screener
description: Screen and monitor the US after-hours (extended) session for news, behavior, and opportunities — earnings reactions, news/flow gaps, and parabolic spikes. Classifies each mover (earnings gap up/down, news gap, parabolic), scores it 0-100, assigns urgency, and routes it to the right downstream skill. Use when the user asks to monitor after-hours/extended-session/post-market activity, screen overnight movers, track earnings reactions after the close, or build a pre-open watchlist.
---

# After-Hours Market Screener

Triage the US after-hours session (post-4:00pm ET): find the names that are
moving on earnings, news, and flow; classify and score them; and route each one
to the sibling skill that does the deep analysis. This is the monitoring /
opportunity-discovery layer that feeds the rest of the toolkit before the next
open.

## When to Use

- User asks to monitor or screen the after-hours / extended / post-market session
- User wants to track earnings reactions after the close
- User asks "what's moving after hours?" or wants a pre-open watchlist
- User wants overnight news/behavior/opportunities triaged and routed

## Prerequisites

- **Offline / demo:** none — run with `--dry-run` to use the bundled fixture.
- **Live mode:** FMP API key (`FMP_API_KEY` env var or `--api-key`). Free tier
  (250 calls/day) covers a focused scan of today's reporters plus a watchlist.

## Workflow

### Step 1: Run the screener

```bash
# Offline demo (bundled fixture, no API key)
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --dry-run --output-dir reports/

# Live: today's AMC reporters, moves >= 5%, mid/large cap only
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --min-move 5 --min-cap 2e9 --output-dir reports/

# Live with an extra watchlist of names to check
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --watchlist AAPL,NVDA,TSLA,AMD --output-dir reports/

# Earnings reactions only
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --earnings-only --top 15 --output-dir reports/
```

Key flags: `--min-move` (direction threshold %, default 5), `--min-cap`,
`--min-price`, `--earnings-only`, `--include-quiet`, `--top N`, `--date`,
`--no-write` (print JSON to stdout instead of writing files).

### Step 2: Read the report and load references

1. Read the generated Markdown + JSON in `reports/`.
2. Load `references/after_hours_playbook.md` for interpretation context
   (overnight gap-fade caution, volume confirmation, catalyst classification).
3. Load `references/classification_rules.md` for category, scoring, and
   routing details.

### Step 3: Present the triage

Lead with the session summary (movers, gainers/losers, net breadth, tone), then
walk the ranked movers. For each high/medium-urgency name present:

- Ticker, after-hours move %, score (0-100), urgency
- Category (earnings gap up/down, news gap, parabolic) and EPS surprise if any
- The catalyst (earnings beat/miss, headline) and the routing target

### Step 4: Route to downstream skills

The screener does triage, not deep analysis. Hand each name to its route:

- **Earnings gap up** → `earnings-trade-analyzer` (5-factor score), then
  `pead-screener` for drift setups; `us-stock-analysis` for the thesis;
  `trader-memory-core` to register it.
- **Earnings gap down** → `scenario-analyzer` (headline impact),
  `us-stock-analysis`; `parabolic-short-trade-planner` if it's a fade.
- **News/flow gap** → `market-news-analyst` to source and score the headline;
  `scenario-analyzer` for forward impact; `theme-detector` if it's thematic.
- **Parabolic spike (+20%+)** → `parabolic-short-trade-planner` for an
  exhaustion fade plan (do not chase).

### Step 5: Confirm before acting

After-hours prints overshoot and fade. Never size off the AH print:

1. Cross-check overnight tone against the `market-regime-daily` workflow
   (`market-breadth-analyzer`, `uptrend-analyzer`, `exposure-coach`).
2. Wait for the regular open; confirm the gap holds (longs) or fails (fades).
3. Size with `position-sizer` against a real stop.

## Output

- `after_hours_screener_YYYY-MM-DD_HHMMSS.json` — structured results
  (`schema_version` 1.0): session summary + ranked, classified, routed movers.
- `after_hours_screener_YYYY-MM-DD_HHMMSS.md` — human-readable report with the
  session summary, a ranked movers table, and highlight cards.

## Resources

- `references/after_hours_playbook.md` — interpretation framework, gap-fade
  caution, volume/catalyst rules.
- `references/classification_rules.md` — categories, thresholds, scoring,
  routing map.
- `scripts/scan_after_hours.py` — orchestrator (fixture + live FMP modes).
- `scripts/classifier.py` — classification, scoring, routing, session summary.
- `scripts/ah_fmp_client.py` — minimal FMP client (earnings calendar + AH quotes).
