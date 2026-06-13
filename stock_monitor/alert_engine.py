import logging
from typing import List

import pandas as pd

from config import ALERT_THRESHOLDS
from state import can_alert, record_alert
from indicators import compute_all

logger = logging.getLogger(__name__)


def check_alerts(df: pd.DataFrame) -> List[str]:
    """Compute multi-indicator confidence score and return alert messages.

    Expects a 5-min OHLCV dataframe for the day with at least 30 rows.
    """
    messages: List[str] = []
    if df is None or df.empty or len(df) < 30:
        return messages

    sym = getattr(df, 'symbol', None) or df.attrs.get('symbol') or 'UNKNOWN'
    cool = ALERT_THRESHOLDS.get('cooldown_mins', 30)

    # Compute indicators and work on the augmented DataFrame
    data = compute_all(df)
    last = data.iloc[-1]
    prev = data.iloc[-2]

    bullish = 0
    bearish = 0

    # RSI: >=70 bearish
    if pd.notna(last.get('rsi')) and last['rsi'] >= 70:
        bearish += 20

    # Bollinger Bands
    if pd.notna(last.get('bb_lower')) and pd.notna(last.get('bb_upper')):
        if last['Close'] < last['bb_lower']:
            bullish += 20
        elif last['Close'] > last['bb_upper']:
            bearish += 20

    # MACD crossover
    if pd.notna(prev.get('macd')) and pd.notna(prev.get('macd_signal')):
        if prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']:
            bullish += 15
        elif prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']:
            bearish += 15

    # EMA crossover (9 / 21)
    if pd.notna(prev.get('ema9')) and pd.notna(prev.get('ema21')):
        if prev['ema9'] < prev['ema21'] and last['ema9'] > last['ema21']:
            bullish += 15
        elif prev['ema9'] > prev['ema21'] and last['ema9'] < last['ema21']:
            bearish += 15

    # VWAP cross
    if pd.notna(prev.get('vwap')) and pd.notna(last.get('vwap')):
        if prev['Close'] < prev['vwap'] and last['Close'] > last['vwap']:
            bullish += 10
        elif prev['Close'] > prev['vwap'] and last['Close'] < last['vwap']:
            bearish += 10

    # Volume ratio > 2x applies to dominant direction
    if pd.notna(last.get('volume_ratio')) and last['volume_ratio'] > 2:
        if bullish > bearish:
            bullish += 10
        elif bearish > bullish:
            bearish += 10

    # Determine dominant direction (must be aligned)
    if bullish == bearish or (bullish == 0 and bearish == 0):
        logger.debug(f"Signals mixed or none for {sym}: bullish={bullish} bearish={bearish}")
        return messages

    direction = 'BULL' if bullish > bearish else 'BEAR'
    score = bullish if bullish > bearish else bearish

    if score < 50:
        logger.debug(f"Score below threshold for {sym}: {score}")
        return messages

    level = 'STRONG' if score >= 75 else 'NORMAL'
    atype = f"ind_{direction.lower()}_{level.lower()}"

    if not can_alert(sym, atype, cool):
        logger.info(f"In cooldown for {sym} alert type {atype}")
        return messages

    # Build message
    emoji = '🚀 BUY' if direction == 'BULL' else '🔻 SELL'
    symbol_text = sym.replace('.NS', '') if isinstance(sym, str) else 'UNKNOWN'

    msg = (
        f"{emoji} | {symbol_text} — {level} ({score})"
        f"\nPrice: ₹{last['Close']:.2f}  |  Change from open: TBD"
        f"\nIndicators: RSI={last.get('rsi'):.1f}, MACD={last.get('macd'):.4f}, EMA9={last.get('ema9'):.2f}, EMA21={last.get('ema21'):.2f}"
    )

    messages.append(msg)
    record_alert(sym, atype)
    logger.info(f"Indicator alert for {sym}: {direction} score={score}")

    return messages