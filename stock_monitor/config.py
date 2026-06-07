WATCHLIST = ["JUBLFOOD.NS", "HDFCBANK.NS", "IEX.NS", "CIPLA.NS", "SUNPHARMA.NS", "ITC.NS", "VEDANTA.NS"]

ALERT_THRESHOLDS = {
    "pct_move"      : 1.5,   # alert if price moves ±1.5% from day open
    "candle_pct"    : 1.0,   # alert if 5-min candle body is ≥1%
    "cooldown_mins" : 30,    # don't repeat same alert within 30 min
}

MARKET_OPEN  = "09:15"
MARKET_CLOSE = "15:30"
TIMEZONE     = "Asia/Kolkata"

TELEGRAM_TOKEN   = "YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1513239567665467492/pzTV40eYbrC6INyjdKkb2s1dxZVLk9MPJpBW-cGAzhLqGkGlQI5tPPPhF2kxLuvSE0gd"