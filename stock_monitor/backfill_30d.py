"""One-off backfill: load the last 30 days of 5-min OHLCV bars for every
WATCHLIST symbol into the TimescaleDB `ohlcv` hypertable.

Reuses the app's tested persistence layer (db.insert_ohlcv) and normalizes the
yfinance frame exactly like fetcher.get_price does. Idempotent: the ohlcv
upsert (ON CONFLICT (symbol, ts)) means re-running just refreshes rows.
"""

import logging
from datetime import datetime, timedelta

import yfinance as yf

import config
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("backfill")

DAYS = 30
INTERVAL = "5m"


def fetch_30d(symbol: str):
    """Fetch ~30 days of 5-min bars, normalized to Open/High/Low/Close/Volume."""
    end = datetime.now()
    start = end - timedelta(days=DAYS)
    hist = yf.Ticker(symbol).history(start=start, end=end, interval=INTERVAL)
    if hist is None or hist.empty:
        return None
    hist = hist.rename(columns={c: c.capitalize() for c in hist.columns})
    hist = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
    return hist


def main():
    db.init_schema()
    total = 0
    for symbol in config.WATCHLIST:
        try:
            df = fetch_30d(symbol)
            if df is None or df.empty:
                logger.warning(f"{symbol}: no data returned")
                continue
            written = db.insert_ohlcv(symbol, df)
            total += written
            logger.info(
                f"{symbol}: fetched {len(df)} bars "
                f"({df.index.min()} -> {df.index.max()}), wrote {written}"
            )
        except Exception as e:
            logger.error(f"{symbol}: backfill failed: {e}")
    logger.info(f"Backfill complete: {total} rows upserted across {len(config.WATCHLIST)} symbols")
    db.close_pool()


if __name__ == "__main__":
    main()
