# After-Hours Monitoring Playbook

Reference for interpreting extended-session (post-4:00pm ET) activity and
deciding what to do with it. The after-hours session is thin, headline-driven,
and prone to overshoot — treat every signal as provisional until confirmed in
the next regular session.

## Why the after-hours session matters

- **Earnings reactions print here first.** Most large-cap reports land AMC
  (after market close). The initial AH gap sets the tone but frequently fades
  or reverses by the next open.
- **News and guidance drop after the bell.** Buybacks, M&A, FDA decisions,
  guidance cuts, and 8-K disclosures move stocks before the regular session can
  react.
- **Liquidity is low.** A few thousand shares can move a thin name 5-10%. AH
  moves on tiny volume are noise; AH moves on heavy volume are signal.

## What to watch

| Behavior | Interpretation | Confirmation needed |
|----------|----------------|---------------------|
| Earnings beat + AH gap up on heavy volume | Genuine positive surprise | Holds gap into next open, no fade |
| Earnings beat + AH gap **down** | Guidance/quality concern ("sell the news") | Check guidance, margins, conference call tone |
| Earnings miss + AH gap down | Negative surprise | Magnitude vs. how much was priced in |
| Parabolic AH spike (+20% or more) | Momentum / squeeze / speculative | Likely overshoot — fade candidate, not chase |
| News gap, no earnings | Catalyst-driven (M&A, FDA, legal) | Identify and assess the headline |
| Big move on tiny AH volume | Noise / mispricing | Ignore until regular-session volume confirms |

## Decision framework

1. **Is there a catalyst?** Earnings vs. news vs. unexplained. Unexplained
   moves on low volume are usually noise.
2. **Is the move confirmed by volume?** Heavy AH volume = institutional
   participation. Thin volume = retail/algorithmic overshoot.
3. **Which direction relative to the prior trend?** A gap up in an uptrend is
   continuation; a gap up in a downtrend may be a bounce to fade.
4. **How extended is it?** A +25% AH spike rarely holds — plan for a fade, not
   a chase. A +6% gap on a quality beat is more durable.
5. **Does it threaten existing holdings?** An AH gap down on a name you own is
   a risk-management event, not just an opportunity scan.

## The "overnight gap fade" caution

After-hours and pre-market prices routinely give back a large fraction of the
initial reaction by the next regular open. Never size a position off the AH
print alone. Use the screener to build the **watchlist and the thesis**, then:

- Wait for the regular-session open and the first 30-60 minutes of price action.
- Confirm the gap holds (for longs) or fails (for fades).
- Size with `position-sizer` against a real stop, never against the AH high/low.

## Pre-open routing

Each after-hours category maps to a downstream skill that does the deep work.
See `classification_rules.md` for the exact mapping. The screener is a triage
layer: it tells you *which* names deserve attention and *which* skill to point
at them — it does not replace the per-name analysis those skills perform.
