"""Pure-python technical indicators (pandas / numpy only).

No TA-Lib, no external service. Every function takes price/volume Series and
returns Series/scalars. These are the building blocks the technical engine scores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(100.0)  # zero losses -> RSI 100


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(high, low, close, period: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(high, low, close, period: int = 14):
    """Average Directional Index (+ DI / -DI). Returns (adx, plus_di, minus_di)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    tr = true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False,
                                min_periods=period).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False,
                                  min_periods=period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_ = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx_, plus_di, minus_di


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).fillna(0.0).cumsum()


def slope_pct(series: pd.Series, lookback: int) -> float:
    """Percent change of a series over `lookback` bars (e.g., MA slope)."""
    s = series.dropna()
    if len(s) <= lookback:
        return float("nan")
    past = s.iloc[-lookback - 1]
    now = s.iloc[-1]
    if past == 0 or pd.isna(past) or pd.isna(now):
        return float("nan")
    return float((now - past) / abs(past))


def rising(series: pd.Series, lookback: int) -> bool:
    sp = slope_pct(series, lookback)
    return bool(sp == sp and sp > 0)  # sp==sp filters NaN


def pct_from_high(close: pd.Series, lookback: int = 252) -> float:
    """Negative number: how far below the rolling high (e.g., -0.08 = 8% below)."""
    window = close.tail(lookback)
    hi = window.max()
    if hi == 0 or pd.isna(hi):
        return float("nan")
    return float((close.iloc[-1] - hi) / hi)


def pct_above_low(close: pd.Series, lookback: int = 252) -> float:
    window = close.tail(lookback)
    lo = window.min()
    if lo == 0 or pd.isna(lo):
        return float("nan")
    return float((close.iloc[-1] - lo) / lo)


def up_down_volume_ratio(close: pd.Series, volume: pd.Series, lookback: int = 60) -> float:
    """Sum(volume on up days) / Sum(volume on down days) over lookback. >1 = accumulation."""
    chg = close.diff()
    vol = volume.copy()
    window = slice(-lookback, None)
    up = vol[chg > 0].iloc[window].sum() if (chg > 0).any() else 0.0
    dn = vol[chg < 0].iloc[window].sum() if (chg < 0).any() else 0.0
    # restrict to lookback window properly
    chg_w = chg.tail(lookback)
    vol_w = vol.tail(lookback)
    up = float(vol_w[chg_w > 0].sum())
    dn = float(vol_w[chg_w < 0].sum())
    if dn <= 0:
        return 3.0 if up > 0 else 1.0
    return up / dn


def volume_ratio_latest(volume: pd.Series, avg_period: int = 50) -> float:
    """Most recent bar volume vs its average. >1.5 on a breakout = institutional."""
    avg = volume.tail(avg_period).mean()
    if avg <= 0 or pd.isna(avg):
        return float("nan")
    return float(volume.iloc[-1] / avg)


def relative_strength(close: pd.Series, bench: pd.Series, lookback: int) -> float:
    """Outperformance vs benchmark over `lookback` bars (decimal, e.g. 0.12 = +12%)."""
    if len(close) <= lookback or len(bench) <= lookback:
        return float("nan")
    c0, c1 = close.iloc[-lookback - 1], close.iloc[-1]
    b0, b1 = bench.iloc[-lookback - 1], bench.iloc[-1]
    if c0 == 0 or b0 == 0:
        return float("nan")
    return float((c1 / c0) - (b1 / b0))


def bullish_rsi_divergence(close: pd.Series, rsi_series: pd.Series,
                           lookback: int = 40) -> bool:
    """Price makes a lower low while RSI makes a higher low -> reversal hint."""
    c = close.tail(lookback).reset_index(drop=True)
    r = rsi_series.tail(lookback).reset_index(drop=True)
    if len(c) < 10:
        return False
    half = len(c) // 2
    p1_idx = c.iloc[:half].idxmin()
    p2_idx = c.iloc[half:].idxmin()
    if pd.isna(p1_idx) or pd.isna(p2_idx):
        return False
    price_lower_low = c[p2_idx] < c[p1_idx]
    rsi_higher_low = r[p2_idx] > r[p1_idx]
    return bool(price_lower_low and rsi_higher_low)
