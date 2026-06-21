import logging
import yfinance as yf
import pandas as pd

import config
import db

logger = logging.getLogger(__name__)


def get_price(symbol: str) -> "pd.DataFrame | None":
    """Fetch full 5-min OHLCV dataframe for the current day using yfinance.

    Returns None if no data or fewer than 30 candles (insufficient for indicators).
    When config.PERSIST_OHLCV is enabled, the fetched bars are also written to
    the TimescaleDB ohlcv hypertable (best-effort; never blocks the scan).
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="5m")
        if hist is None or hist.empty:
            logger.warning(f"No data retrieved for {symbol}")
            return None

        # Ensure standard column names and integer Volume
        hist = hist.rename(columns={c: c.capitalize() for c in hist.columns})
        hist = hist[['Open', 'High', 'Low', 'Close', 'Volume']].copy()

        if len(hist) < 30:
            logger.info(f"Insufficient candles for {symbol}: {len(hist)} (need >=30)")
            return None

        if config.PERSIST_OHLCV:
            try:
                written = db.insert_ohlcv(symbol, hist)
                logger.debug(f"Persisted {written} OHLCV bars for {symbol}")
            except Exception as e:
                logger.error(f"OHLCV persistence failed for {symbol}: {e}")

        return hist
    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return None