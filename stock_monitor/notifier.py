import requests
import logging
import sys
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
        
        # Handle asyncio event loop properly across different platforms
        if sys.platform == 'win32':
            # Windows-specific handling for asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            
            if loop is None:
                asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text))
            else:
                # If there's already a running loop, create a task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    executor.submit(asyncio.run, bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text))
        else:
            asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text))
        
        logger.info(f"Telegram sent: {text[:50]}...")
        return True
    except ImportError:
        logger.error("python-telegram-bot not installed. Install with: pip install python-telegram-bot")
        return False
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
            logger.error(f"Discord error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Discord error: {e}")
        return False