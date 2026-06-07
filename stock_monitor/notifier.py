import requests
import logging
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

def send_telegram(text: str) -> bool:
    """Send message to Telegram (requires python-telegram-bot)."""
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_BOT_TOKEN":
        logger.warning("Telegram token not configured")
        return False
    try:
        from telegram import Bot
        import asyncio
        bot = Bot(token=TELEGRAM_TOKEN)
        asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text))
        logger.info(f"Telegram sent: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def send_discord(text: str) -> bool:
    """Send message to Discord webhook."""
    if not DISCORD_WEBHOOK_URL or "YOUR" in DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook not configured")
        return False
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=5)
        if response.status_code == 204:
            logger.info(f"Discord sent: {text[:50]}...")
            return True
        else:
            logger.error(f"Discord error: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Discord error: {e}")
        return False