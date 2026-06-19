import requests
import logging
import asyncio
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)


def _run_async(coro) -> None:
    """Run an async coroutine to completion regardless of loop state.

    Uses asyncio.run when no loop is active. If called from within an existing
    event loop, runs the coroutine in a dedicated thread so we still block until
    it finishes (and any exception propagates).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread: the simple, common case.
        asyncio.run(coro)
        return

    # A loop is already running (e.g. called from async code): offload to a
    # separate thread with its own loop and wait for the result.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, coro).result()


def send_telegram(text: str) -> bool:
    """Send a message to Telegram. Returns True on success, False otherwise."""
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "YOUR_BOT_TOKEN":
        logger.warning("Telegram token not configured")
        return False
    try:
        from telegram import Bot

        bot = Bot(token=TELEGRAM_TOKEN)
        _run_async(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text))

        logger.info(f"Telegram sent: {text[:50]}...")
        return True
    except ImportError:
        logger.error("python-telegram-bot not installed. Install with: pip install python-telegram-bot")
        return False
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False


def _normalize_webhook(url: str) -> str:
    """Normalize webhook URL by trimming whitespace and surrounding quotes."""
    if not url:
        return ""
    normalized = url.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in ('"', "'"):
        normalized = normalized[1:-1].strip()
    return normalized


def send_discord(text: str) -> bool:
    """Send message to Discord webhook."""
    webhook = _normalize_webhook(DISCORD_WEBHOOK_URL)
    valid_prefixes = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")
    if not webhook or "YOUR" in webhook or not webhook.startswith(valid_prefixes):
        logger.warning("Discord webhook not configured or invalid")
        return False
    try:
        response = requests.post(webhook, json={"content": text}, timeout=5)
        if response.status_code == 204:
            logger.info(f"Discord sent: {text[:50]}...")
            return True
        else:
            logger.error(f"Discord error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Discord error: {e}")
        return False