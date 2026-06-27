import logging
import time

import pandas as pd
import yfinance as yf

import config
import db

logger = logging.getLogger(__name__)

# yfinance's intraday ``period="1d"`` request is unreliable: around and outside
# the live session it frequently returns an empty frame ("possibly delisted; no
# price data found"), even for liquid, actively-traded symbols. We instead fetch
# a short multi-day window at the 5-min interval and slice to the most recent
# trading day. That reliably yields the current/last session's bars.
#
# Keeping the result scoped to a single session is also required for
# correctness: VWAP resets each day and ``change_pct`` is measured from the
# session open, so feeding multi-day data downstream would corrupt both.
LOOKBACK_PERIOD = "5d"
INTERVAL = "5m"
MIN_CANDLES = 30


def _fetch_history(symbol: str, *, period: str, interval: str, kind: str) -> "pd.DataFrame | None":
    """Fetch OHLCV history via yfinance with retry + exponential backoff.

    yfinance intermittently raises or returns an empty frame for valid symbols.
    Both are treated as retryable: we re-request up to config.FETCH_MAX_ATTEMPTS
    times, sleeping ``FETCH_BACKOFF_BASE * 2**(attempt-1)`` seconds (capped at
    FETCH_BACKOFF_MAX) between tries. Returns the raw history frame on the first
    non-empty result, or None if every attempt fails/empties out.
    """
    attempts = max(1, config.FETCH_MAX_ATTEMPTS)
    last_reason = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            hist = yf.Ticker(symbol).history(period=period, interval=interval)
            if hist is not None and not hist.empty:
                if attempt > 1:
                    logger.info(f"{kind} fetch for {symbol} succeeded on attempt {attempt}")
                return hist
            last_reason = "empty frame"
        except Exception as e:  # network blips, JSON decode errors, rate limits
            last_reason = repr(e)

        if attempt < attempts:
            backoff = min(
                config.FETCH_BACKOFF_BASE * (2 ** (attempt - 1)),
                config.FETCH_BACKOFF_MAX,
            )
            logger.warning(
                f"{kind} fetch for {symbol} failed (attempt {attempt}/{attempts}, "
                f"{last_reason}); retrying in {backoff:.1f}s"
            )
            time.sleep(backoff)

    logger.warning(
        f"{kind} fetch for {symbol} gave up after {attempts} attempts ({last_reason})"
    )
    return None


def _normalize(hist: pd.DataFrame) -> pd.DataFrame:
    """Standardize column names/types and drop incomplete rows."""
    hist = hist.rename(columns={c: c.capitalize() for c in hist.columns})
    hist = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
    return hist


def _latest_session(hist: pd.DataFrame) -> pd.DataFrame:
    """Return only the rows belonging to the most recent trading day.

    The yfinance index is tz-aware in the exchange timezone, so comparing on
    ``.date()`` cleanly isolates the latest session regardless of server tz.
    """
    if hist.empty:
        return hist
    last_date = hist.index[-1].date()
    return hist[[ts.date() == last_date for ts in hist.index]]


def get_price(symbol: str) -> "pd.DataFrame | None":
    """Fetch the most recent session's 5-min OHLCV dataframe via yfinance.

    Returns None if no data or fewer than ``MIN_CANDLES`` candles (insufficient
    for indicator warmup). When config.PERSIST_OHLCV is enabled, the fetched
    bars are also written to the TimescaleDB ohlcv hypertable (best-effort;
    never blocks the scan).
    """
    try:
        hist = _fetch_history(symbol, period=LOOKBACK_PERIOD, interval=INTERVAL, kind="Intraday")
        if hist is None or hist.empty:
            logger.warning(f"No data retrieved for {symbol}")
            return None

        hist = _normalize(hist)
        session = _latest_session(hist)

        if len(session) < MIN_CANDLES:
            logger.info(
                f"Insufficient candles for {symbol}: latest session has "
                f"{len(session)} (need >={MIN_CANDLES})"
            )
            return None

        if config.PERSIST_OHLCV:
            try:
                written = db.insert_ohlcv(symbol, session)
                logger.debug(f"Persisted {written} OHLCV bars for {symbol}")
            except Exception as e:
                logger.error(f"OHLCV persistence failed for {symbol}: {e}")

        return session
    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return None


def get_daily(symbol: str, period: "str | None" = None) -> "pd.DataFrame | None":
    """Fetch daily OHLCV bars for the higher-timeframe context layer.

    Unlike the 5-min intraday fetch, daily data has no ~60-day Yahoo cap, so we
    pull several months (config.CONTEXT_DAILY_PERIOD) to support a valid 50-day
    EMA and multi-day support/resistance. Returns normalized Open/High/Low/
    Close/Volume bars, or None on error / empty result.
    """
    period = period or getattr(config, "CONTEXT_DAILY_PERIOD", "3mo")
    try:
        hist = _fetch_history(symbol, period=period, interval="1d", kind="Daily")
        if hist is None or hist.empty:
            logger.warning(f"No daily data retrieved for {symbol}")
            return None
        return _normalize(hist)
    except Exception as e:
        logger.error(f"Error fetching daily data for {symbol}: {e}")
        return None
