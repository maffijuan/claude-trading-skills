#!/usr/bin/env python3
"""JSON + Markdown report generation for the After-Hours Market Screener."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"

# Human-friendly labels for categories used in the markdown report.
CATEGORY_LABELS = {
    "EARNINGS_GAP_UP": "📈 Earnings Gap Up",
    "EARNINGS_GAP_DOWN": "📉 Earnings Gap Down",
    "EARNINGS_INLINE": "➖ Earnings In-Line",
    "NEWS_GAP_UP": "🟢 News/Flow Gap Up",
    "NEWS_GAP_DOWN": "🔴 News/Flow Gap Down",
    "QUIET": "· Quiet",
}


def build_report(classified: list[dict], summary: dict, as_of: str, params: dict) -> dict:
    """Assemble the structured report object (serialized to JSON)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "skill": "after-hours-market-screener",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": as_of,
        "parameters": params,
        "summary": summary,
        "movers": classified,
    }


def _fmt_pct(v) -> str:
    try:
        return f"{float(v):+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_cap(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/a"
    if v >= 1e12:
        return f"${v / 1e12:.1f}T"
    if v >= 1e9:
        return f"${v / 1e9:.1f}B"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M"
    return f"${v:.0f}"


def generate_markdown(report: dict) -> str:
    s = report["summary"]
    lines: list[str] = []
    lines.append("# After-Hours Market Screener")
    lines.append("")
    lines.append(f"**As of:** {report['as_of_date']} (after-hours session)")
    lines.append(f"**Generated:** {report['generated_at']}")
    lines.append("")
    lines.append("## Session Summary")
    lines.append("")
    lines.append(f"- **Movers tracked:** {s['total_movers']}")
    lines.append(f"- **AH gainers / losers:** {s['gainers']} / {s['losers']}")
    lines.append(f"- **Earnings-driven:** {s['earnings_driven']}")
    lines.append(f"- **High-urgency:** {s['high_urgency']}")
    lines.append(f"- **Net breadth:** {s['net_breadth']:+d} — {s['tone']}")
    lines.append("")

    if s.get("by_category"):
        lines.append(
            "**By category:** "
            + ", ".join(
                f"{CATEGORY_LABELS.get(k, k)}: {v}" for k, v in sorted(s["by_category"].items())
            )
        )
        lines.append("")

    movers = report["movers"]
    if not movers:
        lines.append("_No qualifying after-hours movers for the given thresholds._")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Ranked Movers")
    lines.append("")
    lines.append("| # | Ticker | AH Move | Score | Urgency | Category | Cap | Route to |")
    lines.append("|---|--------|---------|-------|---------|----------|-----|----------|")
    for i, r in enumerate(movers, 1):
        routes = ", ".join(r.get("routes", [])) or "—"
        lines.append(
            f"| {i} | **{r['symbol']}** | {_fmt_pct(r.get('ah_change_pct'))} | "
            f"{r['score']} | {r['urgency']} | {CATEGORY_LABELS.get(r['category'], r['category'])} | "
            f"{_fmt_cap(r.get('market_cap'))} | {routes} |"
        )
    lines.append("")

    # Detail cards for the top HIGH/MEDIUM urgency names.
    highlights = [r for r in movers if r["urgency"] in ("HIGH", "MEDIUM")][:10]
    if highlights:
        lines.append("## Highlights")
        lines.append("")
        for r in highlights:
            name = r.get("name") or r["symbol"]
            lines.append(f"### {r['symbol']} — {name}  ({r['urgency']}, score {r['score']})")
            lines.append("")
            lines.append(
                f"- **After-hours move:** {_fmt_pct(r.get('ah_change_pct'))} "
                f"(close {r.get('regular_close', 'n/a')} → AH {r.get('ah_price', 'n/a')})"
            )
            if r.get("earnings_surprise_pct") is not None:
                lines.append(f"- **EPS surprise:** {_fmt_pct(r['earnings_surprise_pct'])}")
            if r.get("sector"):
                lines.append(f"- **Sector:** {r['sector']}")
            if r.get("headline"):
                lines.append(f"- **Headline:** {r['headline']}")
            for note in r.get("notes", []):
                lines.append(f"- {note}")
            if r.get("routes"):
                lines.append(f"- **Next step →** {', '.join(r['routes'])}")
            lines.append("")

    lines.append("---")
    lines.append(
        "_Routing targets are sibling skills in this repo. Feed Grade-A names into the "
        "linked skill (e.g. earnings-trade-analyzer for scoring, scenario-analyzer for "
        "headline impact, parabolic-short-trade-planner for exhaustion fades). Pair with "
        "the `market-regime-daily` workflow + exposure-coach before sizing any entry._"
    )
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict, output_dir: str, as_of: str) -> tuple[str, str]:
    """Write JSON + Markdown reports; return (json_path, md_path)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S")
    base = f"after_hours_screener_{as_of}_{stamp}"
    json_path = out / f"{base}.json"
    md_path = out / f"{base}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(generate_markdown(report), encoding="utf-8")
    return str(json_path), str(md_path)
