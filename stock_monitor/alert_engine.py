import logging
from datetime import datetime, timezone
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

# Daily-context (multi-timeframe) confidence adjustments.
ALIGN_BONUS = 15          # confidence added when intraday agrees with the daily trend
CONTRADICT_FACTOR = 0.5   # confidence multiplier when it fights the daily trend

# Pivot (structural support/resistance) confidence nudge. Kept small and
# additive on purpose: it is a secondary modifier layered on top of the trend
# adjustment, so TOTAL_MAX and the STRONG/NORMAL/WEAK bands stay untouched.
PIVOT_NUDGE = 5           # confidence +/- when a signal aligns/fights a pivot level
PIVOT_TOL_ATR = 0.25      # "at a level" tolerance, as a fraction of daily ATR
PIVOT_STOP_BUFFER_ATR = 0.1  # how far beyond a pivot to place a structural stop


def _level_from_confidence(confidence: int) -> str:
    """Map a 0-100 confidence score to a STRONG / NORMAL / WEAK band."""
    if confidence >= 70:
        return 'STRONG'
    if confidence >= 45:
        return 'NORMAL'
    return 'WEAK'


def analyze(df: pd.DataFrame, context: Optional[dict] = None) -> Optional[dict]:
    """Evaluate every signal and return a structured breakdown.

    Returns None if there is insufficient data. Otherwise returns a dict with
    direction, scores, confidence, ATR-based levels and the full list of
    signals (each tagged with the direction it favours and its points).
    This runs independent of the alert threshold/cooldown so callers can
    inspect conviction even when no alert is emitted.

    When a daily ``context`` dict (see context.compute_context) is supplied, the
    result is enriched with higher-timeframe regime/levels and the confidence is
    adjusted: boosted when the intraday direction agrees with the daily trend,
    cut when it fights it (the multi-timeframe filter).
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
    level = _level_from_confidence(confidence)

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

    res = {
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
        # Structural (pivot-based) levels and position, populated by _apply_pivots.
        'sr_levels': None,
        'pivot_position': None,
        'pivot_nudge': 0,
        # Multi-timeframe context fields (populated by _apply_context).
        'regime': None,
        'aligned': None,
        'gap_pct': None,
        'rel_volume': None,
        'context': None,
    }

    if context:
        _apply_context(res, context, data)

    return res


def _apply_context(res: dict, context: dict, data: pd.DataFrame) -> None:
    """Enrich an analysis result with daily context and adjust confidence.

    Mutates ``res`` in place: attaches the daily regime, session gap, relative
    volume and an ``aligned`` flag, then boosts confidence when the intraday
    direction agrees with the daily trend and cuts it when they conflict. The
    level band is recomputed from the adjusted confidence.
    """
    regime = context.get('regime')
    direction = res['direction']

    # Session-derived context metrics.
    prev_close = context.get('prev_close')
    session_open = float(data.iloc[0]['Open'])
    gap_pct = ((session_open - prev_close) / prev_close * 100) if prev_close else None

    avg_volume = context.get('avg_volume') or 0
    session_volume = float(data['Volume'].sum())
    rel_volume = (session_volume / avg_volume) if avg_volume > 0 else None

    # Alignment between the intraday call and the daily trend.
    if direction == 'NEUTRAL' or regime in (None, 'RANGE'):
        aligned = None
    elif (direction == 'BULL' and regime == 'UP') or (direction == 'BEAR' and regime == 'DOWN'):
        aligned = True
    else:
        aligned = False

    base_conf = res['confidence']
    if aligned is True:
        adj_conf = min(100, base_conf + ALIGN_BONUS)
    elif aligned is False:
        adj_conf = round(base_conf * CONTRADICT_FACTOR)
    else:
        adj_conf = base_conf

    res['confidence_base'] = base_conf
    res['confidence'] = adj_conf
    res['level'] = _level_from_confidence(adj_conf)
    res['regime'] = regime
    res['aligned'] = aligned
    res['gap_pct'] = gap_pct
    res['rel_volume'] = rel_volume
    res['context'] = context

    # Layer the structural-pivot logic on top of the trend adjustment.
    _apply_pivots(res, context)


def _apply_pivots(res: dict, context: dict) -> None:
    """Use daily pivot levels for structure-based targets/stops and a small
    confidence nudge, all in place on ``res``.

    Two behaviours, both gated on a per-stock tolerance of
    ``PIVOT_TOL_ATR * daily_atr`` so "at a level" adapts to each name's volatility:

    * **Structural levels** (``sr_levels``): for a BULL, target the nearest
      resistance above price and stop just beyond the nearest support below it;
      mirror for a BEAR. Emitted only when price sits between a support and a
      resistance.
    * **Confidence nudge** (``pivot_nudge``): boost a signal that has room to run
      (BULL bouncing at support / BEAR rejected at resistance), dampen one that
      is fighting an adjacent level (BULL stalling under resistance / BEAR
      propped on support). Suppressed when the breakout detector is already
      firing, to avoid double-counting the same level interaction.
    """
    direction = res['direction']
    if direction == 'NEUTRAL':
        return

    keys = ('s2', 's1', 'pivot', 'r1', 'r2')
    if any(context.get(k) is None for k in keys):
        return  # no pivots available (e.g. partial context) -> leave untouched

    atr_val = context.get('daily_atr')
    if not atr_val or atr_val <= 0:
        return

    tol = PIVOT_TOL_ATR * atr_val
    price = res['price']

    levels = sorted(
        [('S2', context['s2']), ('S1', context['s1']), ('P', context['pivot']),
         ('R1', context['r1']), ('R2', context['r2'])],
        key=lambda nv: nv[1],
    )
    supports = [nv for nv in levels if nv[1] < price]
    resistances = [nv for nv in levels if nv[1] > price]
    nearest_support = supports[-1] if supports else None
    nearest_resistance = resistances[0] if resistances else None

    # Structure-based stop / target (only when price is bracketed by levels).
    buf = PIVOT_STOP_BUFFER_ATR * atr_val
    sr = None
    if nearest_support and nearest_resistance:
        if direction == 'BULL':
            t2 = resistances[1][1] if len(resistances) > 1 else nearest_resistance[1] + atr_val
            sr = {
                'stop': nearest_support[1] - buf, 'stop_ref': nearest_support[0],
                't1': nearest_resistance[1], 't1_ref': nearest_resistance[0],
                't2': t2,
            }
        else:
            t2 = supports[-2][1] if len(supports) > 1 else nearest_support[1] - atr_val
            sr = {
                'stop': nearest_resistance[1] + buf, 'stop_ref': nearest_resistance[0],
                't1': nearest_support[1], 't1_ref': nearest_support[0],
                't2': t2,
            }
    res['sr_levels'] = sr

    near_support = bool(nearest_support) and abs(price - nearest_support[1]) <= tol
    near_resistance = bool(nearest_resistance) and abs(price - nearest_resistance[1]) <= tol

    # Don't reward/penalize a level interaction the breakout signal already scored.
    breakout_firing = any(s['name'] == 'Chart Pattern' for s in res.get('passed', []))

    nudge = 0
    position = None
    if breakout_firing and (near_support or near_resistance):
        position = 'breakout near pivot (nudge suppressed)'
    elif direction == 'BULL':
        if near_resistance:
            nudge, position = -PIVOT_NUDGE, f'under {nearest_resistance[0]} (overhead resistance)'
        elif near_support:
            nudge, position = PIVOT_NUDGE, f'at {nearest_support[0]} (support, room to run)'
    else:  # BEAR
        if near_support:
            nudge, position = -PIVOT_NUDGE, f'above {nearest_support[0]} (support below)'
        elif near_resistance:
            nudge, position = PIVOT_NUDGE, f'at {nearest_resistance[0]} (resistance, room to fall)'

    res['pivot_position'] = position
    res['pivot_nudge'] = nudge
    if nudge:
        adj = max(0, min(100, res['confidence'] + nudge))
        res['confidence'] = adj
        res['level'] = _level_from_confidence(adj)


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

    sr = res.get('sr_levels')
    if sr:
        lines.append("")
        lines.append("📐 Levels (Structure / pivots)")
        lines.append(f"Stop Loss : ₹{sr['stop']:.2f} (beyond {sr['stop_ref']})")
        lines.append(f"Target 1  : ₹{sr['t1']:.2f} ({sr['t1_ref']})")
        lines.append(f"Target 2  : ₹{sr['t2']:.2f}")

    if res.get('regime'):
        align_txt = {True: 'aligned ✅', False: 'against trend ⚠', None: 'neutral'}.get(res.get('aligned'), 'neutral')
        lines.append("")
        lines.append(f"🧭 Daily Trend: {res['regime']} ({align_txt})")
        if res.get('pivot_position'):
            lines.append(f"Pivot     : {res['pivot_position']}")
        if res.get('gap_pct') is not None:
            lines.append(f"Gap       : {res['gap_pct']:+.2f}% vs prev close")
        if res.get('rel_volume') is not None:
            lines.append(f"Rel Volume: {res['rel_volume']:.2f}x avg day")

    lines.append("")
    conf_text = f"Confidence: {res['confidence']}/100  ({res['level']})"
    if res.get('confidence_base') is not None and res['confidence_base'] != res['confidence']:
        conf_text += f"  [base {res['confidence_base']}, context-adjusted]"
    lines.append(conf_text)
    return "\n".join(lines)


# Embed accent colors (Discord integer RGB). Weak conviction is amber
# regardless of direction so a low-confidence card never looks like a
# strong call.
_COLOR_BULL = 0x2ECC71   # green
_COLOR_BEAR = 0xE74C3C   # red
_COLOR_WEAK = 0xF1C40F   # amber


def _confidence_bar(confidence: int, slots: int = 10) -> str:
    """Render a 0-100 confidence value as a block-character progress bar."""
    filled = int(round(confidence / 100 * slots))
    filled = max(0, min(slots, filled))
    return "█" * filled + "░" * (slots - filled)


def _risk_reward(res: dict) -> Optional[float]:
    """Compute the reward:risk ratio from the ATR-based levels, if available."""
    levels = res.get("levels")
    if not levels:
        return None
    price = res["price"]
    stop = levels["stop"]
    t1 = levels["t1"]
    risk = abs(price - stop)
    reward = abs(t1 - price)
    if risk <= 0:
        return None
    return reward / risk


def _tradingview_url(symbol: str) -> Optional[str]:
    """Map an NSE yfinance symbol (e.g. HDFCBANK.NS) to a TradingView chart URL."""
    if not isinstance(symbol, str):
        return None
    if symbol.endswith(".NS"):
        base = symbol[:-3]
        return f"https://www.tradingview.com/symbols/NSE-{base}/"
    return None


def _build_embed(res: dict) -> dict:
    """Build a rich Discord embed from an analysis result.

    Surfaces direction, price/change, a confidence bar, the bull-vs-bear
    conviction split, risk/reward, the firing signals and the ATR levels —
    color-coded by direction (amber when conviction is WEAK).
    """
    sym = res["symbol"]
    symbol_text = sym.replace(".NS", "") if isinstance(sym, str) else "UNKNOWN"
    is_bull = res["direction"] == "BULL"
    dir_text = "BULLISH" if is_bull else "BEARISH"
    dir_emoji = "🐂" if is_bull else "🐻"

    if res["level"] == "WEAK":
        color = _COLOR_WEAK
    else:
        color = _COLOR_BULL if is_bull else _COLOR_BEAR

    change = res["change_pct"]
    change_arrow = "🔺" if change >= 0 else "🔻"

    fields = [
        {"name": "Price", "value": f"₹{res['price']:.2f}", "inline": True},
        {"name": "Change", "value": f"{change_arrow} {change:+.2f}%", "inline": True},
        {
            "name": "Confidence",
            "value": f"`{_confidence_bar(res['confidence'])}` {res['confidence']}/100",
            "inline": True,
        },
        {
            "name": "Conviction",
            "value": f"🐂 {res['bull_score']}  ⚔️  🐻 {res['bear_score']}",
            "inline": True,
        },
    ]

    rr = _risk_reward(res)
    if rr is not None:
        fields.append({"name": "Risk / Reward", "value": f"1 : {rr:.2f}", "inline": True})

    # Higher-timeframe (daily) context.
    if res.get("regime"):
        align_txt = {True: "aligned ✅", False: "against trend ⚠️", None: "neutral"}.get(res.get("aligned"), "neutral")
        ctx_lines = [f"Trend: **{res['regime']}** ({align_txt})"]
        if res.get("pivot_position"):
            ctx_lines.append(f"Pivot: {res['pivot_position']}")
        if res.get("gap_pct") is not None:
            ctx_lines.append(f"Gap: {res['gap_pct']:+.2f}%")
        if res.get("rel_volume") is not None:
            ctx_lines.append(f"Rel vol: {res['rel_volume']:.2f}x")
        if res.get("confidence_base") is not None and res["confidence_base"] != res["confidence"]:
            ctx_lines.append(f"Confidence {res['confidence_base']} → {res['confidence']} (context-adjusted)")
        fields.append({"name": "🧭 Daily Context", "value": " · ".join(ctx_lines), "inline": False})

    # Firing signals (the ones backing the dominant direction).
    passed = res.get("passed") or []
    if passed:
        firing = "\n".join(f"• {s['name']} — {s['detail']} (+{s['points']})" for s in passed)
    else:
        firing = "_None_"
    fields.append({"name": f"✅ Signals Firing ({len(passed)})", "value": firing, "inline": False})

    # Opposing signals give context for the conviction split.
    opp_dir = "BEAR" if is_bull else "BULL"
    opposing = [s for s in res.get("signals", []) if s["direction"] == opp_dir]
    if opposing:
        opp_text = "\n".join(f"• {s['name']} — {s['detail']} (-{s['points']})" for s in opposing)
        fields.append({"name": f"⚠️ Opposing ({len(opposing)})", "value": opp_text, "inline": False})

    levels = res.get("levels")
    if levels:
        lvl_text = (
            f"Stop ₹{levels['stop']:.2f} · "
            f"T1 ₹{levels['t1']:.2f} · "
            f"T2 ₹{levels['t2']:.2f}"
        )
    else:
        lvl_text = "Not available (ATR N/A)"
    fields.append({"name": "🎯 Levels (ATR-based)", "value": lvl_text, "inline": False})

    sr = res.get("sr_levels")
    if sr:
        sr_text = (
            f"Stop ₹{sr['stop']:.2f} (beyond {sr['stop_ref']}) · "
            f"T1 ₹{sr['t1']:.2f} ({sr['t1_ref']}) · "
            f"T2 ₹{sr['t2']:.2f}"
        )
        fields.append({"name": "📐 Levels (Structure)", "value": sr_text, "inline": False})

    embed = {
        "title": f"{dir_emoji} {symbol_text} — {dir_text} ({res['level']})",
        "color": color,
        "fields": fields,
        "footer": {"text": "Stock Monitor • 5m scan"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    url = _tradingview_url(sym)
    if url:
        embed["url"] = url
    return embed


def check_alerts(df: pd.DataFrame, context: Optional[dict] = None) -> List[dict]:
    """Return alert payloads when a decisive, high-conviction signal fires.

    Each payload is a dict with a ``text`` rendering (for Telegram / fallback)
    and a Discord ``embed`` dict. Expects a 5-min OHLCV dataframe for the day
    with at least 30 rows. When a daily ``context`` is supplied, intraday
    signals that contradict the daily trend are suppressed (the multi-timeframe
    filter).
    """
    messages: List[dict] = []
    res = analyze(df, context=context)
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

    # Multi-timeframe filter: never fire a signal that fights the daily trend.
    if res.get('aligned') is False:
        logger.info(
            f"Suppressed {sym} {res['direction']} signal: contradicts daily "
            f"{res.get('regime')} trend"
        )
        return messages

    cool = ALERT_THRESHOLDS.get('cooldown_mins', 30)
    atype = f"ind_{res['direction'].lower()}_{res['level'].lower()}"
    if not can_alert(sym, atype, cool):
        logger.info(f"In cooldown for {sym} alert type {atype}")
        return messages

    messages.append({"text": _format_message(res), "embed": _build_embed(res)})
    record_alert(sym, atype)
    logger.info(
        f"Alert for {sym}: {res['direction']} score={res['score']} "
        f"conf={res['confidence']} regime={res.get('regime')} aligned={res.get('aligned')}"
    )
    return messages
