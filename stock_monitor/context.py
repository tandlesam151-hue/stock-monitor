"""Higher-timeframe (daily) context for multi-timeframe analysis.

A discretionary trader reads the daily chart for *bias and levels* before
timing an entry on the intraday chart. This module distills a daily OHLCV
series into that context:

* ``regime``      - UP / DOWN / RANGE from the 20/50-day EMA stack,
* prior-day high/low/close (intraday reference levels),
* 20-day swing high/low (multi-day support/resistance),
* floor-trader pivots (``pivot``/R1/R2/S1/S2) - structural price references,
* ``daily_atr``   - daily volatility for stop/target/position sizing,
* ``avg_volume``  - 20-day average volume, for relative-volume checks.

Computed with **no lookahead**: when a session date is supplied, only daily
bars strictly *before* that date are used, so the context is exactly what was
known at the session open.
"""

import logging
from typing import Optional

import pandas as pd

from indicators import atr, ema

logger = logging.getLogger(__name__)

REGIME_EMA_FAST = 20
REGIME_EMA_SLOW = 50
SWING_LOOKBACK = 20
ATR_PERIOD = 14
VOL_LOOKBACK = 20
# Minimum completed daily bars before a regime call is meaningful (fast EMA +
# a little settling). Below this we report RANGE / partial context.
MIN_DAILY_BARS = REGIME_EMA_FAST + 2


def _regime(last_close: float, ema_fast: Optional[float], ema_slow: Optional[float]) -> str:
    """Classify the daily trend from price and the EMA stack.

    Prefers the full 20/50 stack; degrades to price-vs-fast-EMA when there is
    not enough history for the slow EMA (e.g. a 1-month context window).
    """
    if ema_fast is None or pd.isna(ema_fast):
        return "RANGE"
    if ema_slow is None or pd.isna(ema_slow):
        # Not enough history for the slow EMA: use price vs the fast EMA only.
        if last_close > ema_fast:
            return "UP"
        if last_close < ema_fast:
            return "DOWN"
        return "RANGE"
    if last_close > ema_fast and ema_fast >= ema_slow:
        return "UP"
    if last_close < ema_fast and ema_fast <= ema_slow:
        return "DOWN"
    return "RANGE"


def compute_context(daily: pd.DataFrame, session_date=None) -> Optional[dict]:
    """Build the daily-context dict from a daily OHLCV frame.

    ``session_date`` (a ``datetime.date``) anchors the no-lookahead cutoff: only
    daily bars before it are used. If omitted, all supplied bars are used (the
    last bar is treated as the most recent completed day).
    Returns None if there is not enough data to say anything useful.
    """
    if daily is None or daily.empty:
        return None

    d = daily.sort_index()
    if session_date is not None:
        d = d[[ts.date() < session_date for ts in d.index]]

    if len(d) < 2:
        return None

    close = d["Close"]
    last_close = float(close.iloc[-1])

    ema_fast = ema(d, REGIME_EMA_FAST).iloc[-1] if len(d) >= REGIME_EMA_FAST else float("nan")
    ema_slow = ema(d, REGIME_EMA_SLOW).iloc[-1] if len(d) >= REGIME_EMA_SLOW else float("nan")

    ema_fast_v = None if pd.isna(ema_fast) else float(ema_fast)
    ema_slow_v = None if pd.isna(ema_slow) else float(ema_slow)

    regime = _regime(last_close, ema_fast_v, ema_slow_v) if len(d) >= MIN_DAILY_BARS else "RANGE"

    prior = d.iloc[-1]
    swing = d.tail(SWING_LOOKBACK)

    daily_atr = atr(d, ATR_PERIOD).iloc[-1] if len(d) >= ATR_PERIOD else float("nan")
    avg_volume = float(d["Volume"].tail(VOL_LOOKBACK).mean())

    # Classic floor-trader pivots from the prior daily bar. These are pure
    # arithmetic on data already known before the session, so they inherit the
    # no-lookahead guarantee for free. They give structural price references
    # (R1/R2/S1/S2) to complement the fixed-ATR stop/target levels.
    ph, pl, pc = float(prior["High"]), float(prior["Low"]), float(prior["Close"])
    pivot = (ph + pl + pc) / 3.0
    r1 = 2 * pivot - pl
    s1 = 2 * pivot - ph
    r2 = pivot + (ph - pl)
    s2 = pivot - (ph - pl)

    return {
        "regime": regime,
        "ema_fast": ema_fast_v,
        "ema_slow": ema_slow_v,
        "prev_close": float(prior["Close"]),
        "prev_high": float(prior["High"]),
        "prev_low": float(prior["Low"]),
        "swing_high": float(swing["High"].max()),
        "swing_low": float(swing["Low"].min()),
        "daily_atr": None if pd.isna(daily_atr) else float(daily_atr),
        "avg_volume": avg_volume,
        "daily_bars": int(len(d)),
        # Floor-trader pivots (structural support/resistance).
        "pivot": pivot,
        "r1": r1,
        "r2": r2,
        "s1": s1,
        "s2": s2,
    }
