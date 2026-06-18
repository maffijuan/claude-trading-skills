"""Offline unit tests for weekly_swing_scan pure functions (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weekly_swing_scan import (  # noqa: E402
    atr,
    classify_setup,
    compute_indicators,
    rsi,
    sma,
    suggest_levels,
)


def _synthetic_uptrend(n=120, start=100.0, step=1.0):
    """Steady uptrend with small weekly range and constant volume."""
    closes = [start + i * step for i in range(n)]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    opens = [c - 0.5 for c in closes]
    volumes = [1_000_000.0 for _ in closes]
    return {"opens": opens, "highs": highs, "lows": lows, "closes": closes, "volumes": volumes}


def test_sma_basic():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 5) is None


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 30)]
    assert rsi(closes, 14) == 100.0


def test_rsi_range_bounded():
    closes = [100, 101, 100, 102, 101, 103, 102, 104, 103, 105, 104, 106, 105, 107, 106, 108]
    val = rsi(closes, 14)
    assert val is not None and 0 <= val <= 100


def test_atr_positive():
    bars = _synthetic_uptrend(40)
    a = atr(bars["highs"], bars["lows"], bars["closes"], 14)
    assert a is not None and a > 0


def test_compute_indicators_shape():
    ind = compute_indicators(_synthetic_uptrend(220))
    for key in (
        "last_close",
        "sma20",
        "sma50",
        "sma200",
        "rsi14",
        "atr14",
        "high_52w",
        "avg_weekly_dollar_volume",
    ):
        assert key in ind
    # uptrend: price above all MAs
    assert ind["last_close"] > ind["sma50"] > ind["sma200"]


def test_classify_illiquid_flagged():
    bars = _synthetic_uptrend(120)
    bars["volumes"] = [1000.0 for _ in bars["closes"]]  # tiny -> illiquid
    bars["closes"] = [6.0 + 0.01 * i for i in range(120)]
    bars["highs"] = [c + 0.1 for c in bars["closes"]]
    bars["lows"] = [c - 0.1 for c in bars["closes"]]
    ind = compute_indicators(bars)
    cls = classify_setup(ind)
    assert cls["liquid"] is False
    assert cls["setup"] == "AVOID_ILLIQUID"
    assert suggest_levels(ind, cls) is None


def test_classify_climactic_is_extended():
    # Liquid, parabolic blow-off: last bars accelerate hard above the 20w.
    closes = [100 + i for i in range(100)] + [200 + i * 12 for i in range(20)]
    highs = [c + 2 for c in closes]
    lows = [c - 2 for c in closes]
    opens = [c - 1 for c in closes]
    volumes = [500_000.0 for _ in closes]  # * ~$300 = liquid
    ind = compute_indicators(
        {"opens": opens, "highs": highs, "lows": lows, "closes": closes, "volumes": volumes}
    )
    cls = classify_setup(ind)
    assert cls["momentum"] == "CLIMACTIC"
    assert cls["setup"] == "EXTENDED"
    assert suggest_levels(ind, cls) is None  # do not chase


def test_breakout_levels_make_sense():
    bars = _synthetic_uptrend(220, start=400.0, step=0.5)
    bars["volumes"] = [200_000.0 for _ in bars["closes"]]  # liquid at ~$500
    ind = compute_indicators(bars)
    cls = classify_setup(ind)
    lv = suggest_levels(ind, cls)
    if lv:  # actionable setup
        assert lv["stop"] < lv["entry"] < lv["target_2_5R"]
        assert lv["stop_pct"] < 0
