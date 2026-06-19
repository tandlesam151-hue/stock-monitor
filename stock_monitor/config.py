import os
from dotenv import load_dotenv

# Load environment variables from both the workspace root and package directory if present
load_dotenv(os.path.join(os.getcwd(), ".env"), override=False)
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)


def _get_env(name: str, default: str = "") -> str:
    """Read an environment variable and normalize quotes/whitespace."""
    value = os.getenv(name, default)
    if value is None:
        return ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


WATCHLIST = ["JUBLFOOD.NS", "HDFCBANK.NS", "IEX.NS", "CIPLA.NS", "SUNPHARMA.NS", "ITC.NS", "VEDL.NS"]

ALERT_THRESHOLDS = {
    "pct_move"      : 1.5,   # alert if price moves ±1.5% from day open
    "candle_pct"    : 1.0,   # alert if 5-min candle body is ≥1%
    "cooldown_mins" : 30,    # don't repeat same alert within 30 min
}

MARKET_OPEN  = "09:15"
MARKET_CLOSE = "15:30"
TIMEZONE     = _get_env("TIMEZONE", "Asia/Kolkata")
ALLOW_WEEKEND_RUN = True          # enabled for testing
ALLOW_ANYTIME = True              # enabled for testing

# Read credentials from environment variables (safer for different environments)
TELEGRAM_TOKEN   = _get_env("TELEGRAM_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get_env("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID")
DISCORD_WEBHOOK_URL = _get_env("DISCORD_WEBHOOK_URL", "YOUR_WEBHOOK_URL")