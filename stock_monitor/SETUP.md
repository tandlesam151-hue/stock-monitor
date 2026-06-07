# Stock Monitor Setup Guide

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure credentials in `config.py`:**
   - **Discord Webhook:** Already configured ✓
   - **Telegram Bot (Optional):** 
     - Get token from BotFather on Telegram
     - Get your chat ID
     - Update `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` in config.py

3. **Run the monitor:**
   ```bash
   python main.py
   ```

## Features

- **Real-time Stock Monitoring:** Tracks NSE stocks with 5-minute candles
- **Price Alerts:** Triggers on 1.5% price movement or 1% candle body
- **Cooldown System:** Prevents alert spam (30-minute default cooldown)
- **Discord Integration:** Sends alerts to Discord webhook
- **Telegram Integration:** Optional - sends alerts to Telegram bot
- **Market Hours Check:** Only runs during market hours (09:15 - 15:30 IST)
- **Logging:** Full logging for debugging

## Configuration

Edit `config.py` to customize:
- `WATCHLIST`: Add/remove stock symbols (NSE format: `SYMBOL.NS`)
- `ALERT_THRESHOLDS`: Adjust thresholds and cooldown
- `MARKET_OPEN/MARKET_CLOSE`: Change trading hours
- Credentials: Update Discord/Telegram details

## Database

- Stores alert history in `monitor.db`
- Tracks last alert time for each symbol/type to enforce cooldowns
- Automatically created on first run

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No module named 'yfinance'` | Run `pip install -r requirements.txt` |
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
