import logging
from typing import List, Optional

import pandas as pd

import config
import db
from config import ALERT_THRESHOLDS
from state import can_alert, record_alert
from indicators import compute_all
from patterns import detect_candlestick, detect_breakout

logger = logging.getLogger(__name__)

# Maximum points each signal category can contribute. The confidence score is
# the dominant-direction points expressed as a percentage of this total, so the
# denominator must stay in sync with the weights used in analyze().
SIGNAL_WEIGHTS = {
    'RSI': 15,
    'Bollinger Bands': 15,
    'MACD': 15,
    'EMA 9/21': 15,
    'Candlestick': 15,
    'Chart Pattern': 15,
    'VWAP': 10,
    'Volume': 10,
}
TOTAL_MAX = float(sum(SIGNAL_WEIGHTS.values()))  # 110

# Minimum raw points (dominant side) before a signal is worth alerting on.
MIN_SCORE = 50


def analyze(df: pd.DataFrame) -> Optional[dict]:
    """Evaluate every signal and return a structured breakdown.

    Returns None if there is insufficient data. Otherwise returns a dict with
    direction, scores, confidence, ATR-based levels and the full list of
    signals (each tagged with the direction it favours and its points).
    This runs independent of the alert threshold/cooldown so callers can
    inspect conviction even when no alert is emitted.
    """
    if df is None or df.empty or len(df) < 30:
        return None

    sym = df.attrs.get('symbol') or 'UNKNOWN'
    data = compute_all(df)
    last = data.iloc[-1]
    prev = data.iloc[-2]

    signals: List[dict] = []

    def add(name: str, direction: str, detail: str, points: Optional[int] = None):
        signals.append({
            'name': name,
            'direction': direction,
            'points': SIGNAL_WEIGHTS[name] if points is None else points,
            'detail': detail,
        })

    # RSI (symmetric: oversold is bullish, overbought is bearish)
    rsi_val = last.get('rsi')
    if pd.notna(rsi_val):
        if rsi_val >= 70:
            add('RSI', 'BEAR', f'Overbought ({rsi_val:.1f})')
        elif rsi_val <= 30:
            add('RSI', 'BULL', f'Oversold ({rsi_val:.1f})')

    # Bollinger Bands: close outside a band signals mean-reversion pressure
    if pd.notna(last.get('bb_lower')) and pd.notna(last.get('bb_upper')):
        if last['Close'] < last['bb_lower']:
            add('Bollinger Bands', 'BULL', 'Close below lower band')
        elif last['Close'] > last['bb_upper']:
            add('Bollinger Bands', 'BEAR', 'Close above upper band')

    # MACD crossover
    if pd.notna(prev.get('macd')) and pd.notna(prev.get('macd_signal')):
        if prev['macd'] < prev['macd_signal'] and last['macd'] > last['macd_signal']:
            add('MACD', 'BULL', 'Bullish crossover')
        elif prev['macd'] > prev['macd_signal'] and last['macd'] < last['macd_signal']:
            add('MACD', 'BEAR', 'Bearish crossover')

    # EMA 9/21 crossover (trend)
    if pd.notna(prev.get('ema9')) and pd.notna(prev.get('ema21')):
        if prev['ema9'] < prev['ema21'] and last['ema9'] > last['ema21']:
            add('EMA 9/21', 'BULL', 'Golden cross (9>21)')
        elif prev['ema9'] > prev['ema21'] and last['ema9'] < last['ema21']:
            add('EMA 9/21', 'BEAR', 'Death cross (9<21)')

    # Candlestick price-action pattern
    c_dir, c_name = detect_candlestick(df)
    if c_dir:
        add('Candlestick', c_dir, c_name)

    # Chart pattern: intraday range breakout / breakdown
    b_dir, b_name = detect_breakout(df, lookback=20)
    if b_dir:
        add('Chart Pattern', b_dir, b_name)

    # VWAP: a fresh cross is a strong intraday signal; otherwise the side of
    # VWAP price is sitting on is a standing bias (weaker).
    if pd.notna(prev.get('vwap')) and pd.notna(last.get('vwap')):
        if prev['Close'] < prev['vwap'] and last['Close'] > last['vwap']:
            add('VWAP', 'BULL', 'Crossed above VWAP')
        elif prev['Close'] > prev['vwap'] and last['Close'] < last['vwap']:
            add('VWAP', 'BEAR', 'Crossed below VWAP')
        elif last['Close'] > last['vwap']:
            add('VWAP', 'BULL', 'Holding above VWAP', points=5)
        elif last['Close'] < last['vwap']:
            add('VWAP', 'BEAR', 'Holding below VWAP', points=5)

    # Volume surge confirms whichever side is already dominant
    vol_ratio = last.get('volume_ratio')
    if pd.notna(vol_ratio) and vol_ratio > 2:
        bull_pre = sum(s['points'] for s in signals if s['direction'] == 'BULL')
        bear_pre = sum(s['points'] for s in signals if s['direction'] == 'BEAR')
        if bull_pre > bear_pre:
            add('Volume', 'BULL', f'{vol_ratio:.2f}x avg surge')
        elif bear_pre > bull_pre:
            add('Volume', 'BEAR', f'{vol_ratio:.2f}x avg surge')

    bull_score = sum(s['points'] for s in signals if s['direction'] == 'BULL')
    bear_score = sum(s['points'] for s in signals if s['direction'] == 'BEAR')

    if bull_score > bear_score:
        direction, score = 'BULL', bull_score
    elif bear_score > bull_score:
        direction, score = 'BEAR', bear_score
    else:
        direction, score = 'NEUTRAL', max(bull_score, bear_score)

    confidence = min(100, round(score / TOTAL_MAX * 100)) if TOTAL_MAX else 0
    if confidence >= 70:
        level = 'STRONG'
    elif confidence >= 45:
        level = 'NORMAL'
    else:
        level = 'WEAK'

    price = float(last['Close'])
    open_price = float(data.iloc[0]['Open'])
    change_pct = (price - open_price) / open_price * 100 if open_price != 0 else 0.0

    # ATR-based stop / targets aligned to the dominant direction
    atr_val = last.get('atr')
    levels = None
    if pd.notna(atr_val) and atr_val > 0 and direction != 'NEUTRAL':
        if direction == 'BULL':
            levels = {
                'stop': price - 1.5 * atr_val,
                't1': price + 2 * atr_val,
                't2': price + 3 * atr_val,
            }
        else:
            levels = {
                'stop': price + 1.5 * atr_val,
                't1': price - 2 * atr_val,
                't2': price - 3 * atr_val,
            }

    passed = [s for s in signals if s['direction'] == direction] if direction != 'NEUTRAL' else []

    return {
        'symbol': sym,
        'price': price,
        'change_pct': change_pct,
        'direction': direction,
        'score': score,
        'bull_score': bull_score,
        'bear_score': bear_score,
        'confidence': confidence,
        'level': level,
        'signals': signals,
        'passed': passed,
        'levels': levels,
    }


def _format_message(res: dict) -> str:
    """Render an analysis result as a Discord/Telegram-friendly alert."""
    sym = res['symbol']
    symbol_text = sym.replace('.NS', '') if isinstance(sym, str) else 'UNKNOWN'
    dir_text = 'BULLISH' if res['direction'] == 'BULL' else 'BEARISH'
    header = '🔥 STRONG SIGNAL' if res['level'] == 'STRONG' else '⚠ SIGNAL'

    lines = [
        f"{header} | {symbol_text} | {dir_text}",
        "━━━━━━━━━━━━━━━━━━━",
        f"Price   : ₹{res['price']:.2f}",
        f"Change  : {res['change_pct']:+.2f}% from open",
        "",
        f"✅ Signals Passed ({len(res['passed'])})",
    ]
    for s in res['passed']:
        lines.append(f"• {s['name']} — {s['detail']} (+{s['points']})")

    levels = res['levels']
    lines.append("")
    lines.append("🎯 Levels (ATR-based)")
    if levels:
        lines.append(f"Stop Loss : ₹{levels['stop']:.2f} (1.5× ATR)")
        lines.append(f"Target 1  : ₹{levels['t1']:.2f} (2× ATR)")
        lines.append(f"Target 2  : ₹{levels['t2']:.2f} (3× ATR)")
    else:
        lines.append("Not available (ATR N/A)")

    lines.append("")
    lines.append(f"Confidence: {res['confidence']}/100  ({res['level']})")
    return "\n".join(lines)


def check_alerts(df: pd.DataFrame) -> List[str]:
    """Return alert messages when a decisive, high-conviction signal fires.

    Expects a 5-min OHLCV dataframe for the day with at least 30 rows.
    """
    messages: List[str] = []
    res = analyze(df)
    if res is None:
        return messages

    sym = res['symbol']

    # Persist the full analysis snapshot for every scan (independent of whether
    # an alert fires) so we build a signals history for later analysis.
    if config.PERSIST_SIGNALS:
        try:
            ts = df.index[-1]
            ts = ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts
            db.insert_signal(sym, ts, res)
        except Exception as e:
            logger.error(f"Signal persistence failed for {sym}: {e}")

    if res['direction'] == 'NEUTRAL' or res['score'] < MIN_SCORE:
        logger.debug(
            f"No decisive signal for {sym}: dir={res['direction']} score={res['score']}"
        )
        return messages

    cool = ALERT_THRESHOLDS.get('cooldown_mins', 30)
    atype = f"ind_{res['direction'].lower()}_{res['level'].lower()}"
    if not can_alert(sym, atype, cool):
        logger.info(f"In cooldown for {sym} alert type {atype}")
        return messages

    messages.append(_format_message(res))
    record_alert(sym, atype)
    logger.info(
        f"Alert for {sym}: {res['direction']} score={res['score']} conf={res['confidence']}"
    )
    return messages
