# Stock Monitor Setup Guide

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure credentials using environment variables:**
   - **Option A: Using .env file (Recommended for local development)**
     ```bash
     cp .env.example .env
     ```
     Then edit `.env` and fill in your credentials:
     - **Discord Webhook:** Get from Discord Developer Portal
     - **Telegram Bot:** Get token from BotFather, get chat ID from bot
   
   - **Option B: Using system environment variables (For production/Docker)**
     ```bash
     export TELEGRAM_TOKEN="your_bot_token"
     export TELEGRAM_CHAT_ID="your_chat_id"
     export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
     ```

3. **Run the monitor:**
   ```bash
   python main.py
   ```

   Or from anywhere in the system (works from any directory):
   ```bash
   cd /path/to/stock_monitor && python main.py
   ```

## Features

- **Real-time Stock Monitoring:** Tracks NSE stocks with 5-minute candles
- **Price Alerts:** Triggers on 1.5% price movement or 1% candle body
- **Cooldown System:** Prevents alert spam (30-minute default cooldown)
- **Discord Integration:** Sends alerts to Discord webhook
- **Telegram Integration:** Optional - sends alerts to Telegram bot
- **Market Hours Check:** Only runs during market hours (09:15 - 15:30 IST)
- **Logging:** Full logging for debugging
- **Cross-Environment Support:** Works on Windows, macOS, and Linux

## Configuration

Edit `config.py` to customize:
- `WATCHLIST`: Add/remove stock symbols (NSE format: `SYMBOL.NS`)
- `ALERT_THRESHOLDS`: Adjust thresholds and cooldown
- `MARKET_OPEN/MARKET_CLOSE`: Change trading hours
- `TIMEZONE`: Change timezone (defaults to Asia/Kolkata)

Credentials are now read from environment variables:
- `TELEGRAM_TOKEN`: Your Telegram bot token
- `TELEGRAM_CHAT_ID`: Your Telegram chat ID
- `DISCORD_WEBHOOK_URL`: Your Discord webhook URL
- `TIMEZONE`: Optional timezone override (defaults to Asia/Kolkata)

## Database

- Stores alert history in `monitor.db` (stored in stock_monitor directory)
- Tracks last alert time for each symbol/type to enforce cooldowns
- Automatically created on first run
- Works correctly regardless of where the script is run from

## Validation & Testing

Run syntax validation:
```bash
python validate_syntax.py
```

Run comprehensive tests:
```bash
python test_all.py
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No module named 'yfinance'` | Run `pip install -r requirements.txt` |
| `Credentials not found` | Check `.env` file exists or set environment variables |
| `No module named 'dotenv'` | Run `pip install python-dotenv` |
| `Database errors` | Delete `monitor.db` and restart (will recreate) |

## Cross-Environment Deployment

This application now works consistently across different environments:

✓ **Works from any directory** - Database path is absolute
✓ **Credentials from env vars** - Supports .env files and system variables
✓ **Cross-platform asyncio** - Fixed Windows event loop issues
✓ **Portable validation scripts** - validate_syntax.py works from anywhere
| Discord alerts not working | Verify webhook URL is valid in config.py |
| Telegram alerts not working | Update token and chat ID in config.py |
| No alerts triggering | Check market hours and price movement thresholds |
| Database locked | Stop the monitor and try again |

## Files

- `main.py` - Main scheduler and scanner
- `config.py` - Configuration (tokens, symbols, thresholds)
- `fetcher.py` - Fetch stock prices via yfinance
- `alert_engine.py` - Check price thresholds and generate alerts
- `notifier.py` - Send alerts to Discord/Telegram
- `state.py` - SQLite state management
- `monitor.db` - Alert history database (auto-created)

---

**Last Updated:** June 7, 2026
