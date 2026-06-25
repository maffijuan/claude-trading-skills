"""Technical engine: weekly trend gate + integral daily scoring.

Pipeline (per the brief):
  1. Reconstruct the last 100 weekly + 100 daily candles.
  2. Classify the long-term (weekly) trend. If it is a confirmed downtrend AND there
     is no reversal setup -> reject the ticker early.
  3. Score the daily timeframe across five integral pillars (structure, momentum,
     volume, relative strength, trend quality) -> 0-100 technical score.
  4. Apply an overextension guard (don't chase climaxes).

All thresholds come from config.py. No LLM calls anywhere.
"""

from __future__ import annotations

import math

import pandas as pd

import config as C
import indicators as ind


def _clip(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _linear_score(value: float, good: float, floor: float,
                  higher_is_better: bool) -> float:
    """Map a value to 0-100 linearly between `floor` (0) and `good` (100)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    if higher_is_better:
        if value >= good:
            return 100.0
        if value <= floor:
            return 0.0
        return 100.0 * (value - floor) / (good - floor)
    else:
        if value <= good:
            return 100.0
        if value >= floor:
            return 0.0
        return 100.0 * (floor - value) / (floor - good)


# --------------------------------------------------------------------------- #
# Weekly trend gate
# --------------------------------------------------------------------------- #
def classify_weekly_trend(weekly: pd.DataFrame) -> dict:
    """Return {trend, reversal, score, detail}.

    trend in {"up", "sideways", "down"}.
    reversal True if a down/sideways trend shows a credible turn-up setup.
    """
    close = weekly["Close"]
    high = weekly["High"]
    low = weekly["Low"]
    vol = weekly["Volume"]
    n = len(close)
    if n < C.W_SMA_SLOW + 5:
        # Not enough weekly history -> treat as sideways (don't reject outright)
        return {"trend": "sideways", "reversal": False, "score": 50.0,
                "detail": {"reason": "insufficient weekly history"}}

    f = ind.sma(close, C.W_SMA_FAST)
    m = ind.sma(close, C.W_SMA_MID)
    s = ind.sma(close, C.W_SMA_SLOW)
    price = float(close.iloc[-1])
    wf, wm, ws = float(f.iloc[-1]), float(m.iloc[-1]), float(s.iloc[-1])

    mid_rising = ind.rising(m, C.WEEKLY_TREND_RISING_LOOKBACK)
    slow_rising = ind.rising(s, C.WEEKLY_TREND_RISING_LOOKBACK)

    up = (price > wm) and (wf > wm) and (wm > ws) and mid_rising
    down = (price < wm) and (wf < wm) and (not slow_rising)

    if up:
        trend = "up"
    elif down:
        trend = "down"
    else:
        trend = "sideways"

    # Reversal hint: bullish RSI divergence OR reclaim of fast MA from below
    # with rising momentum + supportive volume. Lets oversold names back in.
    wrsi = ind.rsi(close, C.RSI_PERIOD)
    macd_line, signal_line, hist = ind.macd(close)
    div = ind.bullish_rsi_divergence(close, wrsi, lookback=30)
    reclaim = (price > wf) and (float(close.iloc[-2]) <= float(f.iloc[-2]))
    macd_turn = float(hist.iloc[-1]) > float(hist.iloc[-2]) and float(hist.iloc[-1]) > 0
    vol_support = ind.volume_ratio_latest(vol, 20) >= 1.2
    rsi_recovering = float(wrsi.iloc[-1]) > 40 and float(wrsi.iloc[-1]) > float(wrsi.iloc[-5])

    reversal = bool((div or reclaim) and (macd_turn or rsi_recovering) and
                    (trend != "up"))
    if vol_support and reversal:
        reversal = True

    # A crude weekly score for reporting / tie-breaks.
    wscore = 50.0
    wscore += 18 if price > wm else -18
    wscore += 12 if wf > wm else -12
    wscore += 12 if wm > ws else -12
    wscore += 8 if mid_rising else -8
    wscore = _clip(wscore)

    detail = {
        "price": round(price, 2),
        "sma_fast": round(wf, 2), "sma_mid": round(wm, 2), "sma_slow": round(ws, 2),
        "mid_rising": mid_rising, "slow_rising": slow_rising,
        "rsi": round(float(wrsi.iloc[-1]), 1),
        "div": div, "reclaim": reclaim, "macd_turn": macd_turn,
    }
    return {"trend": trend, "reversal": reversal, "score": round(wscore, 1),
            "detail": detail}


# --------------------------------------------------------------------------- #
# Daily integral scoring
# --------------------------------------------------------------------------- #
def _structure_score(daily: pd.DataFrame) -> tuple[float, dict]:
    """Minervini-style Stage-2 trend template + MA alignment + 52w-high proximity."""
    close = daily["Close"]
    price = float(close.iloc[-1])
    sma50 = ind.sma(close, C.SMA_FAST)
    sma150 = ind.sma(close, C.SMA_MID)
    sma200 = ind.sma(close, C.SMA_SLOW)
    ema21 = ind.ema(close, C.EMA_FAST)

    s50 = float(sma50.iloc[-1]) if not pd.isna(sma50.iloc[-1]) else math.nan
    s150 = float(sma150.iloc[-1]) if not pd.isna(sma150.iloc[-1]) else math.nan
    s200 = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else math.nan
    e21 = float(ema21.iloc[-1]) if not pd.isna(ema21.iloc[-1]) else math.nan

    from_high = ind.pct_from_high(close, 252)
    above_low = ind.pct_above_low(close, 252)
    sma200_rising = ind.rising(sma200, 22)

    checks = {
        "price>sma150&200": (not math.isnan(s150) and not math.isnan(s200)
                             and price > s150 and price > s200),
        "sma150>sma200": (not math.isnan(s150) and not math.isnan(s200) and s150 > s200),
        "sma200_rising": sma200_rising,
        "price>sma50": (not math.isnan(s50) and price > s50),
        ">25%_above_low": (not math.isnan(above_low) and above_low >= 0.25),
        "within25%_of_high": (not math.isnan(from_high) and from_high >= -0.25),
        "ema21_stacked": (not math.isnan(e21) and not math.isnan(s50) and e21 > s50),
    }
    passed = sum(1 for v in checks.values() if v)
    # 7 checks -> 0..100
    base = 100.0 * passed / len(checks)
    # bonus for being close to 52w high (newness)
    if not math.isnan(from_high):
        if from_high >= -0.05:
            base = min(100.0, base + 8)
        elif from_high >= -0.15:
            base = min(100.0, base + 4)
    detail = {"checks_passed": f"{passed}/{len(checks)}",
              "from_52w_high_pct": round(from_high * 100, 1) if not math.isnan(from_high) else None,
              **{k: bool(v) for k, v in checks.items()}}
    return _clip(base), detail


def _momentum_score(daily: pd.DataFrame) -> tuple[float, dict]:
    close = daily["Close"]
    rsi = ind.rsi(close, C.RSI_PERIOD)
    macd_line, signal_line, hist = ind.macd(close)
    r = float(rsi.iloc[-1])

    # RSI: bullish sweet spot ~55-70; penalize overbought >80 and weak <45.
    if 55 <= r <= 70:
        rsi_pts = 100.0
    elif 50 <= r < 55:
        rsi_pts = 80.0
    elif 70 < r <= 80:
        rsi_pts = 70.0
    elif 45 <= r < 50:
        rsi_pts = 55.0
    elif r > 80:
        rsi_pts = 45.0
    elif 40 <= r < 45:
        rsi_pts = 35.0
    else:
        rsi_pts = 15.0

    # MACD: line above signal and > 0, histogram expanding = strong.
    ml, sl = float(macd_line.iloc[-1]), float(signal_line.iloc[-1])
    h_now, h_prev = float(hist.iloc[-1]), float(hist.iloc[-2])
    macd_pts = 0.0
    if ml > sl:
        macd_pts += 50
    if ml > 0:
        macd_pts += 25
    if h_now > h_prev:
        macd_pts += 25
    macd_pts = _clip(macd_pts)

    # Rate of change (20d) as a momentum tilt.
    roc = ind.slope_pct(close, 20)
    roc_pts = _linear_score(roc, good=0.10, floor=-0.05, higher_is_better=True)

    score = 0.5 * rsi_pts + 0.35 * macd_pts + 0.15 * roc_pts
    detail = {"rsi": round(r, 1), "macd>signal": ml > sl, "macd>0": ml > 0,
              "hist_expanding": h_now > h_prev,
              "roc20_pct": round(roc * 100, 1) if roc == roc else None}
    return _clip(score), detail


def _volume_score(daily: pd.DataFrame) -> tuple[float, dict]:
    close = daily["Close"]
    vol = daily["Volume"]
    ud = ind.up_down_volume_ratio(close, vol, C.ACC_DIST_LOOKBACK)
    obv = ind.obv(close, vol)
    obv_slope = ind.slope_pct(obv, 30)
    vr = ind.volume_ratio_latest(vol, C.VOL_AVG_PERIOD)

    # Up/down volume ratio (accumulation): >=2 great, ~1 neutral, <0.7 distribution.
    ud_pts = _linear_score(ud, good=2.0, floor=0.7, higher_is_better=True)
    # OBV slope positive = accumulation.
    obv_pts = _linear_score(obv_slope, good=0.15, floor=-0.05, higher_is_better=True)
    # Recent volume expansion (confirmation), capped so quiet names aren't punished hard.
    vr_pts = _linear_score(vr, good=1.6, floor=0.6, higher_is_better=True)

    score = 0.45 * ud_pts + 0.35 * obv_pts + 0.20 * vr_pts
    detail = {"up_down_vol": round(ud, 2),
              "obv_slope_pct": round(obv_slope * 100, 1) if obv_slope == obv_slope else None,
              "vol_vs_avg": round(vr, 2) if vr == vr else None}
    return _clip(score), detail


def _relative_strength_score(daily: pd.DataFrame, bench: pd.DataFrame) -> tuple[float, dict]:
    if bench is None or bench.empty:
        return 50.0, {"note": "no benchmark"}
    close = daily["Close"]
    b = bench["Close"].reindex(close.index).ffill()
    # Multi-period weighting like CANSLIM L: 40% 3m, 30% 6m, 30% 12m.
    rs3 = ind.relative_strength(close, b, 63)
    rs6 = ind.relative_strength(close, b, 126)
    rs12 = ind.relative_strength(close, b, 252)

    def rs_pts(x):
        return _linear_score(x, good=0.20, floor=-0.20, higher_is_better=True)

    parts, weights = [], []
    for val, w in ((rs3, 0.40), (rs6, 0.30), (rs12, 0.30)):
        if val == val:  # not NaN
            parts.append(rs_pts(val) * w)
            weights.append(w)
    score = (sum(parts) / sum(weights)) if weights else 50.0
    detail = {"rs_3m_pct": round(rs3 * 100, 1) if rs3 == rs3 else None,
              "rs_6m_pct": round(rs6 * 100, 1) if rs6 == rs6 else None,
              "rs_12m_pct": round(rs12 * 100, 1) if rs12 == rs12 else None}
    return _clip(score), detail


def _trend_quality_score(daily: pd.DataFrame) -> tuple[float, dict]:
    high, low, close = daily["High"], daily["Low"], daily["Close"]
    adx_, plus_di, minus_di = ind.adx(high, low, close, C.ADX_PERIOD)
    a = float(adx_.iloc[-1]) if not pd.isna(adx_.iloc[-1]) else math.nan
    pdi = float(plus_di.iloc[-1]) if not pd.isna(plus_di.iloc[-1]) else math.nan
    mdi = float(minus_di.iloc[-1]) if not pd.isna(minus_di.iloc[-1]) else math.nan

    # ADX 25-50 with +DI>-DI = clean trend.
    adx_pts = _linear_score(a, good=30.0, floor=12.0, higher_is_better=True)
    if pdi == pdi and mdi == mdi and pdi <= mdi:
        adx_pts *= 0.4  # trend exists but pointed down

    # Overextension penalty (don't chase).
    sma50 = ind.sma(close, C.SMA_FAST)
    sma200 = ind.sma(close, C.SMA_SLOW)
    price = float(close.iloc[-1])
    ext50 = (price / float(sma50.iloc[-1]) - 1) if not pd.isna(sma50.iloc[-1]) else 0.0
    ext200 = (price / float(sma200.iloc[-1]) - 1) if not pd.isna(sma200.iloc[-1]) else 0.0
    ext_pen = 0.0
    if ext50 > C.MAX_EXT_OVER_SMA50:
        ext_pen += 30
    if ext200 > C.MAX_EXT_OVER_SMA200:
        ext_pen += 30
    score = _clip(adx_pts - ext_pen)
    detail = {"adx": round(a, 1) if a == a else None,
              "+di>-di": (pdi > mdi) if (pdi == pdi and mdi == mdi) else None,
              "ext_over_sma50_pct": round(ext50 * 100, 1),
              "ext_over_sma200_pct": round(ext200 * 100, 1)}
    return score, detail


def analyze_daily(daily: pd.DataFrame, bench: pd.DataFrame) -> dict:
    """Compute the integral daily technical score (0-100) + pillar breakdown."""
    pillars = {}
    s_struct, d_struct = _structure_score(daily)
    s_mom, d_mom = _momentum_score(daily)
    s_vol, d_vol = _volume_score(daily)
    s_rs, d_rs = _relative_strength_score(daily, bench)
    s_tq, d_tq = _trend_quality_score(daily)

    pillars = {
        "structure": {"score": round(s_struct, 1), "detail": d_struct},
        "momentum": {"score": round(s_mom, 1), "detail": d_mom},
        "volume": {"score": round(s_vol, 1), "detail": d_vol},
        "relative_strength": {"score": round(s_rs, 1), "detail": d_rs},
        "trend_quality": {"score": round(s_tq, 1), "detail": d_tq},
    }
    w = C.TECH_WEIGHTS
    total = (s_struct * w["structure"] + s_mom * w["momentum"] +
             s_vol * w["volume"] + s_rs * w["relative_strength"] +
             s_tq * w["trend_quality"]) / sum(w.values())

    return {"score": round(_clip(total), 1), "pillars": pillars}


def technical_verdict(weekly: pd.DataFrame, daily: pd.DataFrame,
                      bench: pd.DataFrame) -> dict:
    """Full technical pass: weekly gate -> daily score -> buy/skip decision."""
    # Keep last 100 candles per the brief (indicators already use full history
    # where needed; trimming the *view* keeps reports honest about what we judge).
    daily = daily.tail(max(C.BARS_KEPT, C.SMA_SLOW + 5)).copy()
    weekly = weekly.tail(max(C.BARS_KEPT, C.W_SMA_SLOW + 5)).copy()

    wk = classify_weekly_trend(weekly)
    gate_pass = (wk["trend"] in ("up", "sideways")) or wk["reversal"]

    if not gate_pass:
        return {
            "passed_weekly_gate": False,
            "weekly": wk,
            "daily": None,
            "technical_score": 0.0,
            "is_buy_candidate": False,
            "setup": "weekly_downtrend",
        }

    daily_res = analyze_daily(daily, bench)
    tscore = daily_res["score"]
    is_candidate = tscore >= C.TECH_BUY_THRESHOLD

    if wk["reversal"] and wk["trend"] != "up":
        setup = "reversal"
    elif wk["trend"] == "up":
        setup = "trend_continuation"
    else:
        setup = "base_building"

    strength = ("strong" if tscore >= C.TECH_STRONG_THRESHOLD
                else "moderate" if is_candidate else "weak")

    return {
        "passed_weekly_gate": True,
        "weekly": wk,
        "daily": daily_res,
        "technical_score": tscore,
        "is_buy_candidate": is_candidate,
        "setup": setup,
        "strength": strength,
    }
