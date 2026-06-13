import logging
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

from config import WATCHLIST, MARKET_OPEN, MARKET_CLOSE, TIMEZONE, POST_ALL_STOCKS_TO_DISCORD, ALLOW_WEEKEND_RUN, ALLOW_ANYTIME
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


def format_stock_message(data: dict) -> str:
    symbol = data.get('symbol', 'UNKNOWN').replace('.NS', '')
    current = f"₹{data.get('current', 'N/A'):.2f}" if isinstance(data.get('current'), (int, float)) else f"₹{data.get('current', 'N/A')}"
    open_price = f"₹{data.get('open', 'N/A'):.2f}" if isinstance(data.get('open'), (int, float)) else f"₹{data.get('open', 'N/A')}"
    high = f"₹{data.get('high', 'N/A'):.2f}" if isinstance(data.get('high'), (int, float)) else f"₹{data.get('high', 'N/A')}"
    low = f"₹{data.get('low', 'N/A'):.2f}" if isinstance(data.get('low'), (int, float)) else f"₹{data.get('low', 'N/A')}"
    pct = f"{data.get('pct_chg', 0):+.2f}%"

    return (
        f"📊 {symbol}\n"
        "```\n"
        f"Current | Open     | High     | Low      | Change\n"
        f"{current:<8} | {open_price:<8} | {high:<8} | {low:<8} | {pct}\n"
        "```"
    )


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

                if POST_ALL_STOCKS_TO_DISCORD:
                    snapshot_msg = format_stock_message(data)
                    print(f"\nPosting snapshot for {symbol}:\n{snapshot_msg}\n")
                    send_discord(snapshot_msg)
                
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
    scheduler.add_job(scan, "interval", minutes=5, next_run_time=datetime.now(IST))
    logger.info("Stock monitor started, scanning every 5 minutes (first run now)...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Monitor stopped")