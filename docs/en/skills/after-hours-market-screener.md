---
layout: default
title: "After Hours Market Screener"
grand_parent: English
parent: Skill Guides
nav_order: 11
lang_peer: /ja/skills/after-hours-market-screener/
permalink: /en/skills/after-hours-market-screener/
generated: true
---

# After Hours Market Screener
{: .no_toc }

Screen and monitor the US after-hours (extended) session for news, behavior, and opportunities — earnings reactions, news/flow gaps, and parabolic spikes. Classifies each mover (earnings gap up/down, news gap, parabolic), scores it 0-100, assigns urgency, and routes it to the right downstream skill. Use when the user asks to monitor after-hours/extended-session/post-market activity, screen overnight movers, track earnings reactions after the close, or build a pre-open watchlist.
{: .fs-6 .fw-300 }

<span class="badge badge-free">No API</span> <span class="badge badge-optional">FMP Optional</span>

[Download Skill Package (.skill)](https://github.com/tradermonty/claude-trading-skills/raw/main/skill-packages/after-hours-market-screener.skill){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 }
[View Source on GitHub](https://github.com/tradermonty/claude-trading-skills/tree/main/skills/after-hours-market-screener){: .btn .fs-5 .mb-4 .mb-md-0 }

<details open markdown="block">
  <summary>Table of Contents</summary>
  {: .text-delta }
- TOC
{:toc}
</details>

---

## 1. Overview

# After-Hours Market Screener

---

## 2. When to Use

- User asks to monitor or screen the after-hours / extended / post-market session
- User wants to track earnings reactions after the close
- User asks "what's moving after hours?" or wants a pre-open watchlist
- User wants overnight news/behavior/opportunities triaged and routed

---

## 3. Prerequisites

- **Offline / demo:** none — run with `--dry-run` to use the bundled fixture.
- **Free live mode (`--source yfinance`):** no API key. Scans a watchlist for
  post-market moves via yfinance (already a project dependency). Coverage is the
  watchlist, and earnings are inferred from the earnings timestamp (no EPS
  surprise). Best for an unattended daily run.
- **FMP live mode (`--source fmp`, default):** FMP API key (`FMP_API_KEY` or
  `--api-key`). Adds today's earnings calendar with EPS estimates. Free tier
  (250 calls/day) is enough for a focused scan.

---

## 4. Quick Start

```bash
# Offline demo (bundled fixture, no API key)
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --dry-run --output-dir reports/

# FREE live scan (no key) over the bundled default watchlist
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --source yfinance --min-move 3 --top 40 --output-dir reports/

# FREE live scan with a custom watchlist
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --source yfinance --watchlist AAPL,NVDA,TSLA,AMD --output-dir reports/

# FMP: today's AMC reporters, moves >= 5%, mid/large cap only
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --source fmp --min-move 5 --min-cap 2e9 --output-dir reports/
```

---

## 5. Workflow

### Step 1: Run the screener

```bash
# Offline demo (bundled fixture, no API key)
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --dry-run --output-dir reports/

# FREE live scan (no key) over the bundled default watchlist
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --source yfinance --min-move 3 --top 40 --output-dir reports/

# FREE live scan with a custom watchlist
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --source yfinance --watchlist AAPL,NVDA,TSLA,AMD --output-dir reports/

# FMP: today's AMC reporters, moves >= 5%, mid/large cap only
python3 skills/after-hours-market-screener/scripts/scan_after_hours.py \
  --source fmp --min-move 5 --min-cap 2e9 --output-dir reports/
```

Key flags: `--source {yfinance,fmp}`, `--watchlist` / `--watchlist-file`,
`--min-move` (direction threshold %, default 5), `--min-cap`, `--min-price`,
`--earnings-only`, `--include-quiet`, `--top N`, `--date`, `--no-write`.

### Automated daily run (GitHub Actions → Google Drive)

`.github/workflows/after-hours-screener.yml` runs the screener on US trading
days (`--source yfinance`, no key), uploads the report as a build artifact, and
— if `GDRIVE_SERVICE_ACCOUNT_JSON` + `GDRIVE_FOLDER_ID` repo secrets are set —
pushes it to a Google Drive folder via `scripts/upload_to_drive.py`. See the
workflow header for the one-time Drive service-account setup.

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

---

## 6. Resources

**References:**

- `skills/after-hours-market-screener/references/after_hours_playbook.md`
- `skills/after-hours-market-screener/references/classification_rules.md`

**Scripts:**

- `skills/after-hours-market-screener/scripts/ah_fmp_client.py`
- `skills/after-hours-market-screener/scripts/ah_yf_source.py`
- `skills/after-hours-market-screener/scripts/classifier.py`
- `skills/after-hours-market-screener/scripts/report_generator.py`
- `skills/after-hours-market-screener/scripts/scan_after_hours.py`
