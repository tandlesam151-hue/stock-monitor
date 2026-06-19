import logging
import sys

from config import DISCORD_WEBHOOK_URL
from notifier import send_discord

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

webhook = DISCORD_WEBHOOK_URL or ""
if not webhook or "YOUR" in webhook:
    print("DISCORD_WEBHOOK_URL not configured or looks invalid.")
    sys.exit(2)

print("Webhook appears configured. Sending test message...")

ok = send_discord("🧪 Test Alert: This is a test message from your stock monitor")
print("send_discord returned:", ok)
sys.exit(0 if ok else 1)
