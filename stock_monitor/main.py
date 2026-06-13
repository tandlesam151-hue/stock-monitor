import logging
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

from config import WATCHLIST, MARKET_OPEN, MARKET_CLOSE, TIMEZONE
from fetcher import get_price
from alert_engine import check_alerts
from notifier import send_telegram, send_discord
from state import init_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

IST = pytz.timezone(TIMEZONE)

def is_market_open() -> bool:
    now = datetime.now(IST)
    # Weekday: Monday=0, Sunday=6
    if now.weekday() >= 5:
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
                data = get_price(symbol)
                if not data:
                    logger.warning(f"No data for {symbol}")
                    continue
                
                alerts = check_alerts(data)
                for msg in alerts:
                    print(f"\n{msg}\n")
                    send_telegram(msg)
                    send_discord(msg)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue
    except Exception as e:
        logger.error(f"Scan error: {e}")

if __name__ == "__main__":
    init_db()
    scheduler = BlockingScheduler(timezone=IST)
    scheduler.add_job(scan, "interval", minutes=5)
    logger.info("Stock monitor started, scanning every 5 minutes...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Monitor stopped")