"""Price-action pattern detection: candlestick and chart patterns.

These functions encode classic discretionary read of the tape into rules a
machine can evaluate. They operate directly on an OHLCV DataFrame (columns:
Open, High, Low, Close, Volume) and return a (direction, name) tuple where
direction is 'BULL', 'BEAR' or None.

Implemented without TA-Lib on purpose: the rules are explicit and auditable,
which matters more than raw breadth for an automated assistant.
"""

from typing import Optional, Tuple

import pandas as pd

Signal = Tuple[Optional[str], Optional[str]]


def _parts(o: float, h: float, l: float, c: float):
    """Decompose a candle into body, range and the two shadows."""
    body = abs(c - o)
    rng = h - l
    upper = h - max(o, c)
    lower = min(o, c) - l
    return body, rng, upper, lower


def detect_candlestick(df: pd.DataFrame) -> Signal:
    """Return (direction, name) for the strongest candlestick pattern on the
    last completed candle, else (None, None).

    Priority order reflects conviction: Marubozu > Engulfing > Star >
    Hammer/Shooting Star. Doji is treated as indecision (no direction).
    """
    if df is None or len(df) < 3:
        return None, None

    o, h, l, c = df['Open'], df['High'], df['Low'], df['Close']
    o1, h1, l1, c1 = float(o.iloc[-1]), float(h.iloc[-1]), float(l.iloc[-1]), float(c.iloc[-1])
    o2, h2, l2, c2 = float(o.iloc[-2]), float(h.iloc[-2]), float(l.iloc[-2]), float(c.iloc[-2])
    o3, c3 = float(o.iloc[-3]), float(c.iloc[-3])

    body1, rng1, up1, lo1 = _parts(o1, h1, l1, c1)
    body2, rng2, _, _ = _parts(o2, h2, l2, c2)
    if rng1 <= 0:
        return None, None

    bull1 = c1 > o1
    bear1 = c1 < o1

    # Marubozu: full-bodied candle, almost no shadow -> strong conviction
    if body1 >= 0.9 * rng1:
        return ('BULL', 'Bullish Marubozu') if bull1 else ('BEAR', 'Bearish Marubozu')

    # Engulfing: current real body fully engulfs the prior opposite body
    if bull1 and c2 < o2 and c1 >= o2 and o1 <= c2 and body1 > body2:
        return 'BULL', 'Bullish Engulfing'
    if bear1 and c2 > o2 and o1 >= c2 and c1 <= o2 and body1 > body2:
        return 'BEAR', 'Bearish Engulfing'

    # Morning / Evening Star: 3-candle reversal around a small-bodied star
    if rng2 > 0 and body2 <= 0.3 * rng2:
        mid_first = (o3 + c3) / 2.0
        if c3 < o3 and bull1 and c1 > mid_first:
            return 'BULL', 'Morning Star'
        if c3 > o3 and bear1 and c1 < mid_first:
            return 'BEAR', 'Evening Star'

    # Hammer / Shooting Star: small body with one dominant shadow
    if body1 <= 0.35 * rng1:
        if lo1 >= 2 * body1 and up1 <= 0.3 * rng1:
            return 'BULL', 'Hammer'
        if up1 >= 2 * body1 and lo1 <= 0.3 * rng1:
            return 'BEAR', 'Shooting Star'

    return None, None


def detect_breakout(df: pd.DataFrame, lookback: int = 20) -> Signal:
    """Return (direction, name) when the last close breaks the recent range.

    A close above the highest high of the prior `lookback` candles is a
    breakout (bullish); a close below the prior lowest low is a breakdown.
    """
    if df is None or len(df) < lookback + 1:
        return None, None

    prior = df.iloc[-(lookback + 1):-1]
    last_close = float(df['Close'].iloc[-1])
    hi = float(prior['High'].max())
    lo = float(prior['Low'].min())

    if last_close > hi:
        return 'BULL', f'Breakout above {lookback}-bar high'
    if last_close < lo:
        return 'BEAR', f'Breakdown below {lookback}-bar low'
    return None, None
