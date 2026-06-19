import logging
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

from config import WATCHLIST, MARKET_OPEN, MARKET_CLOSE, TIMEZONE, ALLOW_WEEKEND_RUN, ALLOW_ANYTIME, DISCORD_WEBHOOK_URL
from fetcher import get_price
from alert_engine import check_alerts
from notifier import send_telegram, send_discord
from state import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone(TIMEZONE)

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

                alerts = check_alerts(df)
                if alerts:
                    for msg in alerts:
                        logger.info(f"Alert triggered for {symbol}")
                        logger.debug(msg)
                        if not send_telegram(msg):
                            logger.error(f"Telegram notification failed for {symbol}")
                        if not send_discord(msg):
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