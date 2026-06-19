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

    sym = df.attrs.get('symbol') or 'UNKNOWN'
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

    # Build detailed formatted message
    symbol_text = sym.replace('.NS', '') if isinstance(sym, str) else 'UNKNOWN'
    price = float(last['Close'])
    open_price = float(data.iloc[0]['Open'])
    change_pct = (price - open_price) / open_price * 100 if open_price != 0 else 0.0

    # RSI description
    rsi_val = last.get('rsi')
    if pd.notna(rsi_val):
        if rsi_val >= 70:
            rsi_desc = f"{rsi_val:.1f} (Overbought)"
        elif rsi_val <= 30:
            rsi_desc = f"{rsi_val:.1f} (Oversold)"
        else:
            rsi_desc = f"{rsi_val:.1f}"
    else:
        rsi_desc = "N/A"

    # Bollinger position
    bb_pos = 'Neutral'
    if pd.notna(last.get('bb_lower')) and pd.notna(last.get('bb_upper')):
        if last['Close'] < last['bb_lower']:
            bb_pos = 'Price at Lower Band'
        elif last['Close'] > last['bb_upper']:
            bb_pos = 'Price at Upper Band'
        else:
            bb_pos = 'Within Bands'

    # MACD description
    macd_desc = 'Neutral'
    if pd.notna(prev.get('macd')) and pd.notna(prev.get('macd_signal')):
        if prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']:
            macd_desc = 'Bullish Crossover'
        elif prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']:
            macd_desc = 'Bearish Crossover'

    # VWAP
    vwap_desc = 'N/A'
    if pd.notna(last.get('vwap')):
        vwap_desc = 'Price above VWAP' if last['Close'] > last['vwap'] else 'Price below VWAP'

    # Volume ratio
    vol_ratio = last.get('volume_ratio')
    vol_desc = f"{vol_ratio:.2f}x avg" if pd.notna(vol_ratio) else 'N/A'

    # ATR-based levels
    atr_val = last.get('atr')
    levels_text = ''
    if pd.notna(atr_val) and atr_val > 0:
        if direction == 'BULL':
            stop = price - 1.5 * atr_val
            t1 = price + 2 * atr_val
            t2 = price + 3 * atr_val
        else:
            stop = price + 1.5 * atr_val
            t1 = price - 2 * atr_val
            t2 = price - 3 * atr_val

        levels_text = (
            f"Stop Loss : ₹{stop:.2f} (1.5× ATR)\n"
            f"Target 1  : ₹{t1:.2f} (2× ATR)\n"
            f"Target 2  : ₹{t2:.2f} (3× ATR)\n"
        )
    else:
        levels_text = "Levels not available (ATR N/A)\n"

    # Confidence scaled to 100
    total_possible = 90.0
    conf = min(100, int((score / total_possible) * 100))

    header_emoji = '🔥 STRONG SIGNAL' if level == 'STRONG' else '⚠ SIGNAL'
    dir_text = 'BULLISH' if direction == 'BULL' else 'BEARISH'

    msg_lines = [
        f"{header_emoji} | {symbol_text} | {dir_text}",
        "━━━━━━━━━━━━━━━━━━━",
        f"Price   : ₹{price:.2f}",
        f"Change  : {change_pct:+.2f}% from open",
        "",
        "📊 Indicators",
        f"RSI     : {rsi_desc}",
        f"BB      : {bb_pos}",
        f"MACD    : {macd_desc}",
        f"VWAP    : {vwap_desc}",
        f"Volume  : {vol_desc}",
        "",
        "🎯 Levels (ATR-based)",
        levels_text.rstrip(),
        "",
        f"Confidence: {conf}/100",
    ]

    messages.append("\n".join(msg_lines))
    record_alert(sym, atype)
    logger.info(f"Indicator alert for {sym}: {direction} score={score} conf={conf}")

    return messages