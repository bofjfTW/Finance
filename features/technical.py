"""
Technical Feature Calculations (Pure functions, Point-in-time)
"""
import numpy as np
from typing import List, Dict, Tuple


def calculate_returns(closes: List[float], periods: int = 1) -> float:
    if len(closes) <= periods or closes[-periods - 1] <= 0:
        return 0.0
    return (closes[-1] - closes[-periods - 1]) / closes[-periods - 1]


def calculate_ema(closes: List[float], span: int) -> float:
    if not closes:
        return 0.0
    if len(closes) < span:
        return float(np.mean(closes))
    alpha = 2.0 / (span + 1.0)
    ema = closes[0]
    for p in closes[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return float(ema)


def calculate_ema_slope(closes: List[float], span: int = 9, lookback: int = 3) -> float:
    """Slope of EMA in percentage per bar"""
    if len(closes) < span + lookback:
        return 0.0
    ema_now = calculate_ema(closes, span)
    ema_prev = calculate_ema(closes[:-lookback], span)
    if ema_prev > 0:
        return (ema_now - ema_prev) / (ema_prev * lookback)
    return 0.0


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Average True Range"""
    n = min(len(highs), len(lows), len(closes))
    if n < 2:
        return 0.0
    tr_list = []
    for i in range(1, n):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)

    if not tr_list:
        return 0.0
    if len(tr_list) < period:
        return float(np.mean(tr_list))
    # Wilder's smoothing
    atr = np.mean(tr_list[:period])
    for tr in tr_list[period:]:
        atr = (atr * (period - 1) + tr) / period
    return float(atr)


def calculate_realized_volatility(closes: List[float], window: int = 20) -> float:
    if len(closes) < 3:
        return 0.0
    rets = np.diff(closes[-window:]) / closes[-window:-1]
    if len(rets) < 2:
        return 0.0
    return float(np.std(rets))


def calculate_volume_zscore(volumes: List[float], window: int = 20) -> float:
    if len(volumes) < 3:
        return 0.0
    v_slice = np.array(volumes[-window:])
    mean_v = np.mean(v_slice)
    std_v = np.std(v_slice)
    if std_v > 0:
        return float((volumes[-1] - mean_v) / std_v)
    return 0.0
