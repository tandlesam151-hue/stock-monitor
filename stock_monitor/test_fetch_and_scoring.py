"""Deterministic tests for the fetch + scoring path.

Unlike test_all.py (which feeds a random walk and asserts nothing about the
result), this suite pins down concrete, repeatable behaviour:

* fetcher session-slicing and normalization (no network),
* pattern detectors on hand-built candles with a known answer,
* indicator computation produces finite, populated columns,
* the analyze() scoring invariants and a forced-BULL scenario,
* check_alerts() gating (neutral data -> no alert), with DB persistence
  disabled so the test needs no database,
* a live fetch smoke test (skipped gracefully if the network/data is absent).

Run:  python test_fetch_and_scoring.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import config
import fetcher
from fetcher import _latest_session, _normalize, get_price, get_daily
from indicators import compute_all
from patterns import detect_breakout, detect_candlestick
from alert_engine import analyze, check_alerts, MIN_SCORE, _apply_pivots, PIVOT_NUDGE, _apply_pivots, PIVOT_NUDGE
from context import compute_context, _regime


def _idx(n, start="2026-06-25 09:15", tz="Asia/Kolkata"):
    return pd.date_range(start=start, periods=n, freq="5min", tz=tz)


def _frame(opens, highs, lows, closes, vols, start="2026-06-25 09:15"):
    idx = _idx(len(closes), start=start)
    df = pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )
    df.attrs["symbol"] = "TEST.NS"
    return df


def _forced_bull_df():
    """A 30-bar intraday session whose final candle both breaks the 20-bar high
    and prints a bullish marubozu -> a decisive BULL intraday read."""
    n = 30
    base_close = [100.0 + (0.05 if i % 2 else -0.05) for i in range(n - 1)]
    closes = base_close + [112.0]
    opens = [c for c in base_close] + [101.0]
    highs = [c + 0.2 for c in base_close] + [112.3]
    lows = [c - 0.2 for c in base_close] + [100.8]
    vols = [1000] * (n - 1) + [8000]
    return _frame(opens, highs, lows, closes, vols)


def _daily(n, slope, start="2026-03-02"):
    """Synthetic daily OHLCV with a constant slope over `n` business days."""
    idx = pd.date_range(start=start, periods=n, freq="B", tz="Asia/Kolkata")
    base = 100.0 + slope * np.arange(n)
    df = pd.DataFrame(
        {"Open": base, "High": base + 1.0, "Low": base - 1.0, "Close": base,
         "Volume": [100000] * n},
        index=idx,
    )
    return df


_CTX_UP = {"regime": "UP", "prev_close": 100.0, "prev_high": 101.0, "prev_low": 99.0,
           "swing_high": 105.0, "swing_low": 95.0, "daily_atr": 2.0,
           "avg_volume": 1000.0, "daily_bars": 60}
_CTX_DOWN = dict(_CTX_UP, regime="DOWN")


# --- fetcher helpers (no network) ------------------------------------------

def test_latest_session_slice():
    # Two distinct trading days at 5-min cadence; expect only the last day back.
    day1 = _idx(75, start="2026-06-24 09:15")
    day2 = _idx(75, start="2026-06-25 09:15")
    idx = day1.append(day2)
    df = pd.DataFrame(
        {c: np.arange(len(idx), dtype=float) for c in ["Open", "High", "Low", "Close", "Volume"]},
        index=idx,
    )
    out = _latest_session(df)
    assert len(out) == 75, f"expected 75 rows for latest session, got {len(out)}"
    assert {ts.date() for ts in out.index} == {pd.Timestamp("2026-06-25").date()}
    return "latest-session slice keeps only the most recent trading day"


def test_normalize_drops_nan_and_capitalizes():
    idx = _idx(3)
    raw = pd.DataFrame(
        {"open": [1.0, 2.0, np.nan], "high": [1, 2, 3], "low": [1, 2, 3],
         "close": [1, 2, 3], "volume": [10, 20, 30], "dividends": [0, 0, 0]},
        index=idx,
    )
    out = _normalize(raw)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(out) == 2, f"row with NaN Open should be dropped, got {len(out)} rows"
    return "normalize capitalizes columns and drops incomplete rows"


# --- pattern detectors (known answers) -------------------------------------

def test_breakout_bull_and_bear():
    base = [100.0] * 22
    # Bull: final close blasts above the prior 20-bar high.
    df_bull = _frame(base, [100.5] * 21 + [110.2], [99.5] * 22, base[:-1] + [110.0], [1000] * 22)
    assert detect_breakout(df_bull, lookback=20)[0] == "BULL"
    # Bear: final close breaks below the prior 20-bar low.
    df_bear = _frame(base, [100.5] * 22, [99.5] * 21 + [88.0], base[:-1] + [90.0], [1000] * 22)
    assert detect_breakout(df_bear, lookback=20)[0] == "BEAR"
    return "breakout detector flags BULL above range and BEAR below range"


def test_candlestick_bull_marubozu():
    # Long full-bodied green candle with negligible shadows -> bullish marubozu.
    o = [100.0, 100.0, 100.0]
    c = [100.5, 100.5, 110.0]
    h = [100.6, 100.6, 110.2]
    l = [99.9, 99.9, 99.9]
    df = _frame(o, h, l, c, [1000, 1000, 5000])
    direction, name = detect_candlestick(df)
    assert direction == "BULL", f"expected BULL marubozu, got {(direction, name)}"
    return f"candlestick detector identifies '{name}'"


# --- indicators ------------------------------------------------------------

def test_indicators_populated():
    n = 40
    closes = list(100 + np.linspace(0, 5, n))
    df = _frame(closes, [c + 0.5 for c in closes], [c - 0.5 for c in closes], closes, [1000] * n)
    out = compute_all(df)
    for col in ["rsi", "bb_upper", "bb_lower", "macd", "macd_signal", "ema9", "ema21", "atr", "vwap", "volume_ratio"]:
        assert col in out.columns, f"missing indicator column {col}"
        assert pd.notna(out[col].iloc[-1]), f"indicator {col} is NaN at last bar"
    return "compute_all populates all indicator columns with finite tail values"


# --- scoring / alert engine ------------------------------------------------

def test_analyze_none_when_too_few_candles():
    df = _frame([100] * 10, [101] * 10, [99] * 10, [100] * 10, [1000] * 10)
    assert analyze(df) is None
    return "analyze() returns None below 30 candles"


def test_analyze_direction_invariant():
    n = 40
    rng = np.random.default_rng(42)
    closes = list(100 + np.cumsum(rng.normal(0, 0.3, n)))
    highs = [c + 0.4 for c in closes]
    lows = [c - 0.4 for c in closes]
    df = _frame(closes, highs, lows, closes, list(rng.integers(1000, 5000, n)))
    res = analyze(df)
    assert res is not None
    assert 0 <= res["confidence"] <= 100
    assert res["level"] in {"STRONG", "NORMAL", "WEAK"}
    # The dominant direction must agree with the score split.
    if res["bull_score"] > res["bear_score"]:
        assert res["direction"] == "BULL"
    elif res["bear_score"] > res["bull_score"]:
        assert res["direction"] == "BEAR"
    else:
        assert res["direction"] == "NEUTRAL"
    return "analyze() direction is consistent with the bull/bear score split"


def test_analyze_forced_bull():
    # Calm base (keeps RSI mid-range) then a decisive final candle that both
    # breaks the 20-bar high and prints a bullish marubozu.
    df = _forced_bull_df()
    res = analyze(df)
    assert res is not None
    assert res["direction"] == "BULL", (
        f"expected BULL, got {res['direction']} "
        f"(bull={res['bull_score']} bear={res['bear_score']})"
    )
    assert res["bull_score"] >= res["bear_score"]
    return f"forced-bull scenario scores BULL (bull={res['bull_score']}, conf={res['confidence']})"


# --- daily context layer ---------------------------------------------------

def test_context_regime_up_and_down():
    up = compute_context(_daily(60, slope=0.5))
    down = compute_context(_daily(60, slope=-0.5))
    assert up is not None and down is not None
    assert up["regime"] == "UP", f"expected UP, got {up['regime']}"
    assert down["regime"] == "DOWN", f"expected DOWN, got {down['regime']}"
    assert up["daily_atr"] is not None
    return "daily regime detects UP and DOWN trends from the EMA stack"


def test_context_no_lookahead():
    d = _daily(60, slope=0.5)
    session_date = d.index[-1].date()  # cut off the final bar
    ctx = compute_context(d, session_date=session_date)
    assert ctx is not None
    assert ctx["daily_bars"] == 59, f"expected 59 bars before session, got {ctx['daily_bars']}"
    # prev_close must equal the close of the day *before* the session date.
    assert abs(ctx["prev_close"] - float(d["Close"].iloc[-2])) < 1e-9
    return "compute_context honors the no-lookahead session cutoff"


def test_context_regime_degrades_with_short_history():
    # Only ~25 bars: not enough for a 50-day EMA, should still classify via the
    # fast EMA rather than crashing.
    ctx = compute_context(_daily(25, slope=0.5))
    assert ctx is not None
    assert ctx["regime"] in {"UP", "DOWN", "RANGE"}
    assert ctx["ema_slow"] is None, "50-day EMA should be unavailable with 25 bars"
    return "context degrades gracefully when history is too short for the slow EMA"


def test_context_alignment_boosts_confidence():
    df = _forced_bull_df()
    base = analyze(df)["confidence"]
    res = analyze(df, context=_CTX_UP)
    assert res["aligned"] is True, f"BULL under UP regime should align, got {res['aligned']}"
    assert res["regime"] == "UP"
    assert res["confidence"] > base, f"aligned confidence {res['confidence']} should exceed base {base}"
    assert res["confidence_base"] == base
    return f"aligned signal boosts confidence {base} -> {res['confidence']}"


def test_context_contradiction_penalizes_confidence():
    df = _forced_bull_df()
    base = analyze(df)["confidence"]
    res = analyze(df, context=_CTX_DOWN)
    assert res["aligned"] is False, "BULL under DOWN regime should contradict"
    assert res["confidence"] < base, f"contradicting confidence {res['confidence']} should be below base {base}"
    return f"contradicting signal cuts confidence {base} -> {res['confidence']}"


def test_context_filter_suppresses_contradicting_alert():
    saved = (config.PERSIST_OHLCV, config.PERSIST_SIGNALS)
    config.PERSIST_OHLCV = False
    config.PERSIST_SIGNALS = False
    try:
        df = _forced_bull_df()
        # Sanity: this scenario clears the score gate, so only the trend filter
        # can suppress it.
        assert analyze(df)["score"] >= MIN_SCORE
        alerts = check_alerts(df, context=_CTX_DOWN)
        assert alerts == [], f"signal fighting the daily trend must be suppressed, got {len(alerts)}"
    finally:
        config.PERSIST_OHLCV, config.PERSIST_SIGNALS = saved
    return "trend filter suppresses an intraday signal that fights the daily trend"


def test_live_daily_context_smoke():
    sym = config.WATCHLIST[0] if config.WATCHLIST else "HDFCBANK.NS"
    daily = get_daily(sym)
    if daily is None or daily.empty:
        return ("SKIP", f"no live daily data for {sym}")
    ctx = compute_context(daily)
    assert ctx is not None
    assert ctx["regime"] in {"UP", "DOWN", "RANGE"}
    assert ctx["daily_bars"] > 0
    return f"live daily context for {sym}: regime={ctx['regime']} ({ctx['daily_bars']} bars)"


def test_check_alerts_neutral_no_alert():
    # Disable DB persistence so this test needs no database connection.
    saved = (config.PERSIST_OHLCV, config.PERSIST_SIGNALS)
    config.PERSIST_OHLCV = False
    config.PERSIST_SIGNALS = False
    try:
        n = 40
        flat = [100.0] * n
        df = _frame(flat, [100.2] * n, [99.8] * n, flat, [1000] * n)
        alerts = check_alerts(df)
        assert alerts == [], f"flat market should produce no alert, got {len(alerts)}"
    finally:
        config.PERSIST_OHLCV, config.PERSIST_SIGNALS = saved
    return "check_alerts() emits nothing on neutral/low-conviction data"


def test_min_score_constant():
    assert isinstance(MIN_SCORE, int) and MIN_SCORE > 0
    return f"MIN_SCORE alert gate is set ({MIN_SCORE})"


# --- live fetch smoke test (network; skipped if unavailable) ---------------

def test_live_fetch_smoke():
    sym = config.WATCHLIST[0] if config.WATCHLIST else "HDFCBANK.NS"
    saved = config.PERSIST_OHLCV
    config.PERSIST_OHLCV = False  # don't write during a test
    try:
        df = get_price(sym)
    finally:
        config.PERSIST_OHLCV = saved
    if df is None:
        return ("SKIP", f"no live data for {sym} (offline or no recent session)")
    assert len(df) >= fetcher.MIN_CANDLES, f"{sym}: only {len(df)} bars"
    assert len({ts.date() for ts in df.index}) == 1, "fetch must return a single session"
    return f"live fetch of {sym} returned {len(df)} single-session bars"


# --- pivots / structural support-resistance --------------------------------

# A pivot-bearing context: S2 98 < S1 100 < P 101 < R1 103 < R2 105, ATR 2.0
# so the "at a level" tolerance is 0.25 * 2.0 = 0.5.
_CTX_PIVOTS = {"regime": "UP", "prev_close": 101.0, "prev_high": 102.0, "prev_low": 99.0,
               "swing_high": 105.0, "swing_low": 95.0, "daily_atr": 2.0,
               "avg_volume": 1000.0, "daily_bars": 60,
               "pivot": 101.0, "r1": 103.0, "r2": 105.0, "s1": 100.0, "s2": 98.0}


def _res(direction, price, confidence=60, passed=None):
    """Minimal analysis-result stub for exercising _apply_pivots directly."""
    return {"direction": direction, "price": price, "confidence": confidence,
            "level": "NORMAL", "passed": passed or [], "sr_levels": None,
            "pivot_position": None, "pivot_nudge": 0}


def test_context_includes_pivots():
    ctx = compute_context(_daily(60, slope=0.5))
    assert ctx is not None
    for k in ("pivot", "r1", "r2", "s1", "s2"):
        assert k in ctx and ctx[k] is not None, f"missing pivot key {k}"
    # Floor-pivot identities and monotonic ordering S2 < S1 < P < R1 < R2.
    ph, pl, pc = ctx["prev_high"], ctx["prev_low"], ctx["prev_close"]
    assert abs(ctx["pivot"] - (ph + pl + pc) / 3) < 1e-9
    assert abs(ctx["r1"] - (2 * ctx["pivot"] - pl)) < 1e-9
    assert abs(ctx["s1"] - (2 * ctx["pivot"] - ph)) < 1e-9
    assert ctx["s2"] < ctx["s1"] < ctx["pivot"] < ctx["r1"] < ctx["r2"]
    return "compute_context emits floor pivots with correct math and ordering"


def test_pivots_inherit_no_lookahead():
    d = _daily(60, slope=0.5)
    session_date = d.index[-1].date()  # exclude the final bar
    ctx = compute_context(d, session_date=session_date)
    # Pivots must come from the bar *before* the session, not the excluded one.
    prior = d.iloc[-2]
    expected_pivot = (float(prior["High"]) + float(prior["Low"]) + float(prior["Close"])) / 3
    assert abs(ctx["pivot"] - expected_pivot) < 1e-9
    return "pivots are computed from the pre-session bar (no lookahead)"


def test_pivot_nudge_boosts_bull_at_support():
    res = _res("BULL", price=100.2)  # within 0.5 of S1 (100.0)
    _apply_pivots(res, _CTX_PIVOTS)
    assert res["pivot_nudge"] == PIVOT_NUDGE, res["pivot_nudge"]
    assert res["confidence"] == 65
    assert "S1" in res["pivot_position"] and "support" in res["pivot_position"]
    return f"BULL bouncing at support is boosted (+{PIVOT_NUDGE})"


def test_pivot_nudge_dampens_bull_under_resistance():
    res = _res("BULL", price=102.8)  # within 0.5 of R1 (103.0)
    _apply_pivots(res, _CTX_PIVOTS)
    assert res["pivot_nudge"] == -PIVOT_NUDGE
    assert res["confidence"] == 55
    assert "R1" in res["pivot_position"] and "resistance" in res["pivot_position"]
    return f"BULL stalling under resistance is dampened (-{PIVOT_NUDGE})"


def test_pivot_nudge_boosts_bear_at_resistance():
    res = _res("BEAR", price=102.8)  # within 0.5 of R1 (103.0)
    _apply_pivots(res, _CTX_PIVOTS)
    assert res["pivot_nudge"] == PIVOT_NUDGE
    assert res["confidence"] == 65
    return "BEAR rejected at resistance is boosted"


def test_pivot_nudge_dampens_bear_at_support():
    res = _res("BEAR", price=100.2)  # within 0.5 of S1 (100.0)
    _apply_pivots(res, _CTX_PIVOTS)
    assert res["pivot_nudge"] == -PIVOT_NUDGE
    assert res["confidence"] == 55
    return "BEAR propped on support is dampened"


def test_pivot_no_nudge_in_mid_range():
    res = _res("BULL", price=101.6)  # >0.5 from both S1(100) and R1(103); near P but P isn't nearest
    _apply_pivots(res, _CTX_PIVOTS)
    assert res["pivot_nudge"] == 0
    assert res["confidence"] == 60
    return "no nudge when price sits clear of the nearest levels"


def test_pivot_breakout_suppresses_nudge():
    # A breakout firing near the same level must not be double-counted.
    passed = [{"name": "Chart Pattern", "direction": "BULL",
               "detail": "Breakout above 20-bar high", "points": 15}]
    res = _res("BULL", price=100.2, passed=passed)  # would otherwise boost at S1
    _apply_pivots(res, _CTX_PIVOTS)
    assert res["pivot_nudge"] == 0, "breakout should suppress the S/R nudge"
    assert res["confidence"] == 60
    assert "suppressed" in res["pivot_position"]
    return "breakout near a pivot suppresses the S/R nudge (no double count)"


def test_pivot_structure_levels_bull():
    res = _res("BULL", price=101.6)  # bracketed by S/R
    _apply_pivots(res, _CTX_PIVOTS)
    sr = res["sr_levels"]
    assert sr is not None
    # Target is the nearest resistance above price; stop sits beyond nearest support.
    assert sr["t1_ref"] == "R1" and abs(sr["t1"] - 103.0) < 1e-9
    assert sr["stop_ref"] == "P" and sr["stop"] < 101.0  # buffer beyond support
    assert sr["t2"] > sr["t1"]
    return "structure levels target next resistance, stop beyond nearest support"


def test_pivot_tolerance_scales_with_atr():
    # Same price/levels, but a tiny ATR shrinks the tolerance so "near" fails.
    tight = dict(_CTX_PIVOTS, daily_atr=0.4)  # tol = 0.1
    res = _res("BULL", price=100.2)  # 0.2 from S1 -> outside 0.1 tolerance now
    _apply_pivots(res, tight)
    assert res["pivot_nudge"] == 0, "0.2 away should be outside a 0.1 ATR tolerance"
    return "the 'at a level' tolerance scales with daily ATR"


def test_pivot_noop_without_levels():
    # Context lacking pivot keys (e.g. the plain _CTX_UP fixture) must be inert:
    # this preserves the untouched TOTAL_MAX / band calibration promise.
    res = _res("BULL", price=100.2, confidence=72)
    _apply_pivots(res, _CTX_UP)
    assert res["pivot_nudge"] == 0 and res["sr_levels"] is None
    assert res["confidence"] == 72
    return "no pivots in context -> _apply_pivots is a no-op"


def test_analyze_wires_pivot_fields():
    # End-to-end: a context carrying pivots flows pivot fields onto the result.
    df = _forced_bull_df()  # decisive BULL, also fires the breakout detector
    ctx = dict(_CTX_PIVOTS, pivot=111.0, r1=112.2, r2=114.0, s1=110.0, s2=109.0)
    res = analyze(df, context=ctx)
    assert res["direction"] == "BULL"
    assert "sr_levels" in res and "pivot_nudge" in res
    # Price ~112 is within 0.5 of R1 (112.2) and a breakout is firing -> suppressed.
    assert res["pivot_nudge"] == 0
    assert res["pivot_position"] and "suppressed" in res["pivot_position"]
    return "analyze() wires pivot fields and honours breakout de-dup end-to-end"


TESTS = [
    test_latest_session_slice,
    test_normalize_drops_nan_and_capitalizes,
    test_breakout_bull_and_bear,
    test_candlestick_bull_marubozu,
    test_indicators_populated,
    test_analyze_none_when_too_few_candles,
    test_analyze_direction_invariant,
    test_analyze_forced_bull,
    test_context_regime_up_and_down,
    test_context_no_lookahead,
    test_context_regime_degrades_with_short_history,
    test_context_alignment_boosts_confidence,
    test_context_contradiction_penalizes_confidence,
    test_context_filter_suppresses_contradicting_alert,
    test_context_includes_pivots,
    test_pivots_inherit_no_lookahead,
    test_pivot_nudge_boosts_bull_at_support,
    test_pivot_nudge_dampens_bull_under_resistance,
    test_pivot_nudge_boosts_bear_at_resistance,
    test_pivot_nudge_dampens_bear_at_support,
    test_pivot_no_nudge_in_mid_range,
    test_pivot_breakout_suppresses_nudge,
    test_pivot_structure_levels_bull,
    test_pivot_tolerance_scales_with_atr,
    test_pivot_noop_without_levels,
    test_analyze_wires_pivot_fields,
    test_check_alerts_neutral_no_alert,
    test_min_score_constant,
    test_live_fetch_smoke,
    test_live_daily_context_smoke,
]


def main():
    print("Running fetch + scoring tests\n" + "=" * 60)
    passed = failed = skipped = 0
    for t in TESTS:
        try:
            result = t()
            if isinstance(result, tuple) and result[0] == "SKIP":
                print(f"~ SKIP {t.__name__}: {result[1]}")
                skipped += 1
            else:
                print(f"✓ PASS {t.__name__}: {result}")
                passed += 1
        except AssertionError as e:
            print(f"✗ FAIL {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print("=" * 60)
    print(f"Result: {passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
