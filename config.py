"""
config.py — Central configuration loader for the Telegram Video Downloader Bot.
Reads values from the .env file using python-dotenv.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
try:
    ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID: int = 0

# ── Terabox ───────────────────────────────────────────
TERABOX_COOKIE: str = os.getenv("TERABOX_COOKIE", "").strip()

# ── Payment / Subscription ────────────────────────────
PAYMENT_UPI: str = os.getenv("PAYMENT_UPI", "")
PAYMENT_NOTE: str = os.getenv("PAYMENT_NOTE", "Contact admin to subscribe.")
PREMIUM_PRICE: str = os.getenv("PREMIUM_PRICE", "₹49/month")

# ── Rate Limits ───────────────────────────────────────
FREE_DAILY_LIMIT: int = 2          # downloads per 24 hours for free users
MAX_FILE_SIZE_MB: int = 49         # Telegram bot API file upload limit
TEMP_DIR: str = "temp_downloads"   # temporary download folder

# ── Sanity check ──────────────────────────────────────
def validate():
    """Call at bot startup to ensure required env vars are set."""
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise EnvironmentError(
            "BOT_TOKEN is not configured!\n"
            "Edit your .env file and set BOT_TOKEN to the token from @BotFather."
        )
    if not ADMIN_ID or ADMIN_ID == 0:
        raise EnvironmentError(
            "ADMIN_ID is not configured!\n"
            "Edit your .env file and set ADMIN_ID to your Telegram user ID.\n"
            "(Get your ID by messaging @userinfobot on Telegram)"
        )
