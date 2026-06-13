import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

WATCHLIST = ["JUBLFOOD.NS", "HDFCBANK.NS", "IEX.NS", "CIPLA.NS", "SUNPHARMA.NS", "ITC.NS", "VEDANTA.NS"]

ALERT_THRESHOLDS = {
    "pct_move"      : 1.5,   # alert if price moves ±1.5% from day open
    "candle_pct"    : 1.0,   # alert if 5-min candle body is ≥1%
    "cooldown_mins" : 30,    # don't repeat same alert within 30 min
}

MARKET_OPEN  = "09:15"
MARKET_CLOSE = "15:30"
TIMEZONE     = os.getenv("TIMEZONE", "Asia/Kolkata")
POST_ALL_STOCKS_TO_DISCORD = True  # enabled for testing
ALLOW_WEEKEND_RUN = True          # enabled for testing
ALLOW_ANYTIME = True              # enabled for testing

# Read credentials from environment variables (safer for different environments)
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "YOUR_WEBHOOK_URL")