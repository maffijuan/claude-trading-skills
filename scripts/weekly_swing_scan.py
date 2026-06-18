#!/usr/bin/env python3
"""Weekly swing-trading scan workflow.

Replaces manual chart-screenshot reading with real OHLCV bars fetched via
yfinance, reconstructs weekly candles, and applies a numeric version of the
``technical-analyst`` framework (trend stage, moving-average structure, RSI,
ATR, liquidity, key levels). It then:

  1. Reads the market regime from ``uptrend-analyzer`` (public CSV, no API key).
  2. Classifies each watchlist ticker into a swing setup
     (BREAKOUT_WATCH / RE_BREAKOUT / PULLBACK_WAIT / EXTENDED / AVOID_ILLIQUID).
  3. Sizes the actionable candidates with ``position-sizer`` rules.
  4. Renders a Markdown + JSON report to ``reports/``.
  5. Optionally emails the report (SMTP via environment variables).

Designed to run unattended (e.g. every Monday 10:30 ET). All network access is
via yfinance (Yahoo Finance) and the uptrend-analyzer CSV; no FMP/FINVIZ/Alpaca
key is required.

Pure functions (``compute_indicators``, ``classify_setup``, ``suggest_levels``,
``rsi``, ``atr``) are import-safe and unit-tested offline with synthetic data.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import subprocess
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_WATCHLIST = ["AMAT", "INTC", "LIN", "MTLS", "ENB"]

# Liquidity floor for disciplined swing sizing: average weekly dollar volume.
MIN_WEEKLY_DOLLAR_VOLUME = 25_000_000.0


# --------------------------------------------------------------------------- #
# Pure technical functions (no I/O — unit tested offline)
# --------------------------------------------------------------------------- #
def sma(values: list[float], period: int) -> float | None:
    """Simple moving average of the last ``period`` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI of the closing-price series."""
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float | None:
    """Average True Range (Wilder) over the bar series."""
    n = len(closes)
    if n < period + 1:
        return None
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr_val = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
    return round(atr_val, 2)


def compute_indicators(bars: dict) -> dict:
    """Compute numeric indicators from reconstructed weekly OHLCV.

    ``bars`` keys: opens, highs, lows, closes, volumes (parallel lists,
    oldest-first). Returns a flat dict of indicator values.
    """
    closes = bars["closes"]
    highs = bars["highs"]
    lows = bars["lows"]
    volumes = bars["volumes"]
    last = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else last

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    high52 = max(highs[-52:]) if len(highs) >= 52 else max(highs)
    low52 = min(lows[-52:]) if len(lows) >= 52 else min(lows)

    recent_vol = volumes[-20:] if len(volumes) >= 20 else volumes
    recent_close = closes[-20:] if len(closes) >= 20 else closes
    avg_dollar_vol = sum(v * c for v, c in zip(recent_vol, recent_close)) / len(recent_vol)

    return {
        "last_close": round(last, 2),
        "weekly_change_pct": round((last / prev - 1) * 100, 2) if prev else 0.0,
        "sma20": round(sma20, 2) if sma20 else None,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "rsi14": rsi(closes, 14),
        "atr14": atr(highs, lows, closes, 14),
        "high_52w": round(high52, 2),
        "low_52w": round(low52, 2),
        "pct_from_52w_high": round((last / high52 - 1) * 100, 2),
        "ext_above_sma20_pct": round((last / sma20 - 1) * 100, 2) if sma20 else None,
        "avg_weekly_dollar_volume": round(avg_dollar_vol, 0),
        "n_bars": len(closes),
    }


def classify_setup(ind: dict) -> dict:
    """Rules-based swing classification from numeric indicators.

    Returns dict with: stage, momentum, setup, liquid (bool), rationale.
    """
    last = ind["last_close"]
    sma20, sma50, sma200 = ind["sma20"], ind["sma50"], ind["sma200"]
    rsi14 = ind["rsi14"] or 0
    ext = ind["ext_above_sma20_pct"]
    pct_high = ind["pct_from_52w_high"]
    liquid = ind["avg_weekly_dollar_volume"] >= MIN_WEEKLY_DOLLAR_VOLUME

    # Trend stage (Weinstein/Minervini-style)
    if sma50 and sma200 and last > sma50 > sma200:
        stage = "STAGE_2_UPTREND"
    elif sma50 and sma200 and last < sma50 < sma200:
        stage = "STAGE_4_DOWNTREND"
    else:
        stage = "TRANSITIONAL"

    # Momentum band
    if rsi14 >= 80:
        momentum = "CLIMACTIC"
    elif rsi14 >= 65:
        momentum = "STRONG"
    elif rsi14 >= 45:
        momentum = "NEUTRAL"
    else:
        momentum = "WEAK"

    # Setup
    if not liquid:
        setup = "AVOID_ILLIQUID"
    elif momentum == "CLIMACTIC" or (ext is not None and ext >= 25):
        setup = "EXTENDED"  # too far above the line — do not chase
    elif stage == "STAGE_2_UPTREND" and pct_high >= -6:
        setup = "BREAKOUT_WATCH"  # near highs, constructive
    elif stage == "STAGE_2_UPTREND" and sma20 and last < sma20:
        setup = "PULLBACK_WAIT"  # uptrend but below 20w — wait for support
    elif stage == "STAGE_2_UPTREND":
        setup = "RE_BREAKOUT"  # trending, mid-structure
    else:
        setup = "NO_SETUP"

    rationale = (
        f"{stage}, RSI {rsi14} ({momentum}), {pct_high:+.1f}% vs 52w-high, "
        f"ext {ext:+.1f}% vs 20w, "
        f"liquidity ${ind['avg_weekly_dollar_volume'] / 1e6:.1f}M/wk "
        f"({'OK' if liquid else 'TOO THIN'})"
    )
    return {
        "stage": stage,
        "momentum": momentum,
        "setup": setup,
        "liquid": liquid,
        "rationale": rationale,
    }


def suggest_levels(ind: dict, cls: dict) -> dict | None:
    """Suggest entry/stop/target for actionable setups; None if not actionable."""
    setup = cls["setup"]
    last = ind["last_close"]
    sma20 = ind["sma20"]
    sma50 = ind["sma50"]
    atr14 = ind["atr14"] or 0
    high52 = ind["high_52w"]

    if setup in ("AVOID_ILLIQUID", "EXTENDED", "NO_SETUP"):
        return None

    if setup == "BREAKOUT_WATCH":
        entry = round(max(high52, last) * 1.001, 2)  # just above prior high
        stop = round(max(sma20 or last * 0.95, entry - 2 * atr14), 2)
    elif setup == "PULLBACK_WAIT":
        entry = round(sma20 or last, 2)  # buy near 20w on the turn
        stop = round(min(sma50 or entry * 0.95, entry - 2 * atr14), 2)
    else:  # RE_BREAKOUT
        entry = round(last, 2)
        stop = round(max(sma50 or last * 0.9, entry - 2 * atr14), 2)

    if stop >= entry:  # guard
        stop = round(entry * 0.93, 2)
    risk_per_share = round(entry - stop, 2)
    target = round(entry + 2.5 * risk_per_share, 2)  # 2.5R objective
    return {
        "entry": entry,
        "stop": stop,
        "target_2_5R": target,
        "stop_pct": round((stop / entry - 1) * 100, 2),
    }


# --------------------------------------------------------------------------- #
# I/O: data fetch, regime, sizing, render, email
# --------------------------------------------------------------------------- #
def fetch_weekly_bars(ticker: str, years: int = 3) -> dict:
    """Fetch weekly OHLCV via yfinance and reconstruct parallel candle lists."""
    import yfinance as yf  # imported lazily so pure functions stay offline-testable

    df = yf.download(
        ticker,
        period=f"{years}y",
        interval="1wk",
        progress=False,
        auto_adjust=False,
    )
    if df is None or len(df) == 0:
        raise RuntimeError(f"no data returned for {ticker}")
    # yfinance may return MultiIndex columns for a single ticker
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    return {
        "opens": [float(x) for x in df["Open"]],
        "highs": [float(x) for x in df["High"]],
        "lows": [float(x) for x in df["Low"]],
        "closes": [float(x) for x in df["Close"]],
        "volumes": [float(x) for x in df["Volume"]],
        "dates": [str(d.date()) for d in df.index],
    }


def get_market_regime() -> dict:
    """Run uptrend-analyzer (no API key) and return its composite summary."""
    script = PROJECT_ROOT / "skills/uptrend-analyzer/scripts/uptrend_analyzer.py"
    out_dir = PROJECT_ROOT / "reports"
    try:
        subprocess.run(
            [sys.executable, str(script), "--output-dir", str(out_dir)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        latest = sorted(out_dir.glob("uptrend_analysis_*.json"))[-1]
        data = json.loads(latest.read_text())
        comp = data.get("composite", {})
        meta = data.get("metadata", {})
        return {
            "composite_score": comp.get("composite_score"),
            "zone": comp.get("zone"),
            "exposure_guidance": comp.get("exposure_guidance"),
            "as_of": meta.get("latest_data_date"),
        }
    except Exception as exc:  # best-effort; workflow continues without regime
        return {"error": f"regime unavailable: {exc}"}


def size_position(
    entry: float, stop: float, account: float, risk_pct: float, max_pos_pct: float, sector: str
) -> dict:
    """Call position-sizer and parse its JSON output."""
    script = PROJECT_ROOT / "skills/position-sizer/scripts/position_sizer.py"
    out_dir = PROJECT_ROOT / "reports"
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--entry",
            str(entry),
            "--stop",
            str(stop),
            "--account-size",
            str(account),
            "--risk-pct",
            str(risk_pct),
            "--max-position-pct",
            str(max_pos_pct),
            "--sector",
            sector,
            "--output-dir",
            str(out_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # newest by mtime (timestamps in name collide within the same second)
    latest = max(out_dir.glob("position_sizer_*.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(latest.read_text())


def analyze_ticker(ticker: str, account: float, risk_pct: float, max_pos_pct: float) -> dict:
    """Full per-ticker pipeline: fetch -> indicators -> classify -> levels -> size."""
    bars = fetch_weekly_bars(ticker)
    ind = compute_indicators(bars)
    cls = classify_setup(ind)
    levels = suggest_levels(ind, cls)
    sizing = None
    if levels:
        try:
            sized = size_position(
                levels["entry"], levels["stop"], account, risk_pct, max_pos_pct, sector="Unknown"
            )
            sizing = {
                "shares": sized.get("final_recommended_shares"),
                "position_value": sized.get("final_position_value"),
                "risk_dollars": sized.get("final_risk_dollars"),
                "risk_pct": sized.get("final_risk_pct"),
            }
        except Exception as exc:
            sizing = {"error": str(exc)}
    return {
        "ticker": ticker,
        "as_of": bars["dates"][-1],
        "indicators": ind,
        "classification": cls,
        "levels": levels,
        "sizing": sizing,
    }


SETUP_RANK = {
    "BREAKOUT_WATCH": 0,
    "RE_BREAKOUT": 1,
    "PULLBACK_WAIT": 2,
    "EXTENDED": 3,
    "AVOID_ILLIQUID": 4,
    "NO_SETUP": 5,
}


def render_markdown(
    results: list[dict], regime: dict, account: float, max_pos_pct: float, risk_pct: float
) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Weekly Swing Scan — {today}",
        "",
        "## Market Regime (uptrend-analyzer, no API key)",
    ]
    if "error" in regime:
        lines.append(f"- {regime['error']}")
    else:
        lines += [
            f"- **Composite:** {regime.get('composite_score')}/100 — **{regime.get('zone')}**",
            f"- **Exposure guidance:** {regime.get('exposure_guidance')}",
            f"- As of: {regime.get('as_of')}",
        ]
    lines += [
        "",
        f"## Candidates (account ${account:,.0f}, risk {risk_pct}% , max {max_pos_pct}%/position)",
        "",
        "| Ticker | Setup | Stage | RSI | Entry | Stop | Target(2.5R) | Shares | Position | Risk |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    ranked = sorted(results, key=lambda r: SETUP_RANK.get(r["classification"]["setup"], 9))
    for r in ranked:
        ind, cls, lv, sz = (r["indicators"], r["classification"], r["levels"], r["sizing"])
        if lv and sz and "error" not in (sz or {}):
            row = (
                f"| {r['ticker']} | {cls['setup']} | {cls['stage']} | "
                f"{ind['rsi14']} | {lv['entry']} | {lv['stop']} | "
                f"{lv['target_2_5R']} | {sz['shares']} | "
                f"${sz['position_value']:,.0f} | "
                f"${sz['risk_dollars']:,.0f} ({sz['risk_pct']}%) |"
            )
        else:
            row = (
                f"| {r['ticker']} | {cls['setup']} | {cls['stage']} | "
                f"{ind['rsi14']} | — | — | — | — | — | — |"
            )
        lines.append(row)
    lines += ["", "## Per-ticker rationale", ""]
    for r in ranked:
        lines.append(f"- **{r['ticker']}** ({r['as_of']}): {r['classification']['rationale']}")
    lines += [
        "",
        "---",
        "*Generated by weekly_swing_scan.py. Technical, chart-based only; "
        "not investment advice. Data via yfinance (Yahoo Finance).*",
    ]
    return "\n".join(lines)


def send_email(subject: str, body_md: str, to_addr: str) -> None:
    """Send the report via SMTP using environment variables.

    Required env: SMTP_HOST, SMTP_USER, SMTP_PASS. Optional: SMTP_PORT (587),
    EMAIL_FROM (defaults to SMTP_USER).
    """
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    if not all([host, user, password]):
        raise RuntimeError(
            "SMTP not configured: set SMTP_HOST, SMTP_USER, SMTP_PASS "
            "(and optionally SMTP_PORT, EMAIL_FROM)."
        )
    port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("EMAIL_FROM", user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body_md, "plain", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=ctx)
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Weekly swing-trading scan workflow")
    ap.add_argument("--tickers", nargs="*", default=DEFAULT_WATCHLIST)
    ap.add_argument("--account-size", type=float, default=300_000)
    ap.add_argument("--risk-pct", type=float, default=1.0)
    ap.add_argument("--max-position-pct", type=float, default=10.0)
    ap.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"))
    ap.add_argument(
        "--email-to", default=None, help="Send the report to this address (needs SMTP_* env)."
    )
    ap.add_argument("--no-regime", action="store_true")
    args = ap.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    regime = {} if args.no_regime else get_market_regime()

    results = []
    for tk in args.tickers:
        try:
            results.append(
                analyze_ticker(tk, args.account_size, args.risk_pct, args.max_position_pct)
            )
        except Exception as exc:
            print(f"[warn] {tk}: {exc}", file=sys.stderr)

    if not results:
        print(
            "No tickers analyzed (data fetch failed for all). "
            "Check network egress allowlist for query1/query2.finance.yahoo.com.",
            file=sys.stderr,
        )
        return 1

    md = render_markdown(results, regime, args.account_size, args.max_position_pct, args.risk_pct)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md_path = out_dir / f"weekly_swing_scan_{today}.md"
    json_path = out_dir / f"weekly_swing_scan_{today}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps({"regime": regime, "results": results}, indent=2), encoding="utf-8"
    )
    print(f"Report: {md_path}")
    print(f"JSON:   {json_path}")

    if args.email_to:
        try:
            send_email(f"Weekly Swing Scan — {today}", md, args.email_to)
            print(f"Emailed report to {args.email_to}")
        except Exception as exc:
            print(f"[warn] email failed: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
