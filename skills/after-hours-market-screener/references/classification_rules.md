# Classification & Routing Rules

How the screener categorizes each after-hours mover and which sibling skill it
routes to. Mirrors the logic in `scripts/classifier.py`.

## Movement thresholds

- `min_move` (default **5%**): minimum absolute AH move vs. the regular-session
  close to be assigned a direction (`up` / `down`). Sub-threshold names are
  `flat`.
- `BIG_MOVE` = 10%: notable move.
- `PARABOLIC_MOVE` = 20%: triggers the parabolic short-fade overlay.

## Categories

| Category | Condition | Meaning |
|----------|-----------|---------|
| `EARNINGS_GAP_UP` | reported earnings + move ≥ `min_move` | Positive earnings reaction |
| `EARNINGS_GAP_DOWN` | reported earnings + move ≤ −`min_move` | Negative earnings reaction |
| `EARNINGS_INLINE` | reported earnings + |move| < `min_move` | Muted / priced-in |
| `NEWS_GAP_UP` | no earnings + move ≥ `min_move` | Headline/flow-driven pop |
| `NEWS_GAP_DOWN` | no earnings + move ≤ −`min_move` | Headline/flow-driven drop |
| `QUIET` | no earnings + |move| < `min_move` | Noise (filtered out by default) |

**Parabolic overlay:** any move ≥ `PARABOLIC_MOVE` (+20%) also appends
`parabolic-short-trade-planner` to the route list and forces `HIGH` urgency,
flagging the name as an exhaustion / fade candidate rather than a chase.

## Routing map

| Category | Routes to |
|----------|-----------|
| `EARNINGS_GAP_UP` | earnings-trade-analyzer, pead-screener, us-stock-analysis, trader-memory-core |
| `EARNINGS_GAP_DOWN` | scenario-analyzer, us-stock-analysis, parabolic-short-trade-planner |
| `EARNINGS_INLINE` | earnings-trade-analyzer |
| `NEWS_GAP_UP` | market-news-analyst, scenario-analyzer, theme-detector |
| `NEWS_GAP_DOWN` | market-news-analyst, scenario-analyzer |

## Scoring (0-100)

Composite of four components:

| Component | Max | Logic |
|-----------|-----|-------|
| Magnitude | 40 | `min(|move| / 20%, 1) × 40` — saturates at the parabolic threshold |
| AH volume | 20 | ≥1M → 20; ≥500k → 14; ≥100k → 8; >0 → 4; none → 0 |
| Liquidity (market cap) | 20 | ≥$10B → 20; ≥$2B → 16; ≥$300M → 10; >0 → 4; unknown → 8 |
| Catalyst | 20 | earnings w/ surprise: `12 + min(|surprise%|/25, 1)×8`; earnings only: 12; news move: 10 |

**Urgency:** `HIGH` if score ≥ 70 or |move| ≥ 20%; `MEDIUM` if score ≥ 45;
else `LOW`.

**EPS surprise %:** `(eps − eps_estimate) / |eps_estimate| × 100`; `None` when
the estimate is missing or zero.

## Session breadth / tone

`session_summary()` aggregates the classified list:

- `net_breadth` = (# AH gainers) − (# AH losers)
- `tone`: ≥ +3 → "risk-on"; ≤ −3 → "risk-off"; otherwise "mixed / two-sided"

Use the tone as a coarse read on overnight sentiment, then confirm against the
`market-regime-daily` workflow (market-breadth-analyzer, uptrend-analyzer,
exposure-coach) before adjusting net exposure.
