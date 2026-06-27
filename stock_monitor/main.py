import logging
import time
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

import config
from config import WATCHLIST, MARKET_OPEN, MARKET_CLOSE, TIMEZONE, ALLOW_WEEKEND_RUN, ALLOW_ANYTIME, DISCORD_WEBHOOK_URL
from fetcher import get_price, get_daily
from context import compute_context
from alert_engine import check_alerts
from notifier import send_telegram, send_discord, telegram_configured
from state import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone(TIMEZONE)

# Per-symbol daily-context cache: symbol -> (epoch_fetched, context_or_None).
# Daily bars barely change intraday, so we refresh only every
# config.CONTEXT_TTL_SECONDS instead of pulling months of data every scan.
_context_cache = {}


def _get_daily_context(symbol: str, session_date):
    """Return cached daily context for a symbol, refreshing past the TTL."""
    if not config.USE_DAILY_CONTEXT:
        return None
    now = time.time()
    cached = _context_cache.get(symbol)
    if cached and (now - cached[0]) < config.CONTEXT_TTL_SECONDS:
        return cached[1]
    daily = get_daily(symbol)
    ctx = compute_context(daily, session_date=session_date) if daily is not None else None
    _context_cache[symbol] = (now, ctx)
    if ctx:
        logger.info(
            f"Daily context {symbol}: regime={ctx['regime']} "
            f"({ctx['daily_bars']} daily bars, atr={ctx['daily_atr']})"
        )
    else:
        logger.warning(f"No daily context available for {symbol}")
    return ctx

def is_market_open() -> bool:
    if ALLOW_ANYTIME:
        return True

    now = datetime.now(IST)
    # Weekday: Monday=0, Sunday=6
    if now.weekday() >= 5 and not ALLOW_WEEKEND_RUN:
        return False

    current_time = now.time()
    market_open = datetime.strptime(MARKET_OPEN, "%H:%M").time()
    market_close = datetime.strptime(MARKET_CLOSE, "%H:%M").time()
    return market_open <= current_time <= market_close


def scan():
    try:
        if not is_market_open():
            logger.info("Market closed, skipping scan")
            return
        
        for symbol in WATCHLIST:
            try:
                df = get_price(symbol)
                if df is None or df.empty:
                    logger.warning(f"No data for {symbol}")
                    continue

                # attach symbol metadata for downstream use
                df.attrs['symbol'] = symbol

                # Higher-timeframe daily context for the session being analyzed.
                session_date = df.index[-1].date()
                ctx = _get_daily_context(symbol, session_date)

                alerts = check_alerts(df, context=ctx)
                if alerts:
                    for payload in alerts:
                        logger.info(f"Alert triggered for {symbol}")
                        text = payload["text"]
                        embed = payload.get("embed")
                        logger.debug(text)
                        if telegram_configured():
                            if not send_telegram(text):
                                logger.error(f"Telegram notification failed for {symbol}")
                        else:
                            logger.debug(f"Telegram not configured; skipping for {symbol}")
                        if not send_discord(text, embed=embed):
                            logger.error(f"Discord notification failed for {symbol}")
                else:
                    logger.info(f"No alert triggered for {symbol}")
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue
    except Exception as e:
        logger.error(f"Scan error: {e}")

if __name__ == "__main__":
    init_db()
    if DISCORD_WEBHOOK_URL and "YOUR" not in DISCORD_WEBHOOK_URL:
        logger.info("Discord webhook appears configured")
    else:
        logger.warning("Discord webhook is not configured or looks invalid")
    scheduler = BlockingScheduler(timezone=IST)
    scheduler.add_job(scan, "interval", minutes=5, next_run_time=datetime.now(IST))
    logger.info("Stock monitor started, scanning every 5 minutes (first run now)...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Monitor stopped")