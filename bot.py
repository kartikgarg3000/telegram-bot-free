"""
bot.py — Main entry point for the Telegram Video Downloader Bot.

Commands:
  /start           — Welcome message
  /help            — Usage guide & supported platforms
  /status          — User's subscription status & downloads used today
  /subscribe       — Show payment info to upgrade to Premium
  /addpremium <id> [days]  — (Admin) Grant premium to a user
  /removepremium <id>      — (Admin) Revoke premium from a user
  /stats                   — (Admin) Global bot statistics
  /broadcast <msg>         — (Admin) Send a message to all users
  /listusers               — (Admin) List all users with their status

Any message containing a URL → the bot will try to download it.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import TelegramError

import config
import database as db
from utils.helpers import extract_url, route_download, cleanup, human_size, get_file_size

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Silence overly verbose libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


# ──────────────────────────────────────────────────────────────────────────────
# Decorators / Guards
# ──────────────────────────────────────────────────────────────────────────────

def admin_only(func):
    """Decorator: restrict a handler to the configured ADMIN_ID."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user.id != config.ADMIN_ID:
            await update.message.reply_text(
                "⛔ This command is for the bot admin only."
            )
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ──────────────────────────────────────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.first_name)

    premium = db.is_premium(user.id)
    status_line = (
        "⭐ **Premium Member** — Unlimited downloads!"
        if premium else
        f"🆓 Free Plan — {config.FREE_DAILY_LIMIT} downloads per 24 hours"
    )

    welcome = (
        f"👋 Hello, **{user.first_name}**!\n\n"
        "🎬 *Video Downloader Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Send me any video link and I'll deliver the video directly in chat — "
        "**no ads, no redirects, no waiting.**\n\n"
        f"📊 Your status: {status_line}\n\n"
        "📌 **Supported platforms:**\n"
        "• Terabox & all clones\n"
        "• YouTube, TikTok, Instagram\n"
        "• Twitter/X, Reddit, Facebook\n"
        "• Vimeo, Dailymotion, Streamtape\n"
        "• 1700+ other sites via yt-dlp\n"
        "• Any direct `.mp4` link\n\n"
        "Just paste a link and I'll handle the rest! 🚀"
    )

    keyboard = [
        [
            InlineKeyboardButton("📖 How to Use", callback_data="help"),
            InlineKeyboardButton("⭐ Go Premium", callback_data="subscribe"),
        ],
        [InlineKeyboardButton("📊 My Status", callback_data="status")],
    ]

    await update.message.reply_text(
        welcome,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ──────────────────────────────────────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *How to use this bot:*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Copy any video link\n"
        "2️⃣ Paste it here and send\n"
        "3️⃣ Wait a few seconds — your video arrives!\n\n"
        "⚙️ *Commands:*\n"
        "`/start`     — Main menu\n"
        "`/help`      — This message\n"
        "`/status`    — Your download quota\n"
        "`/subscribe` — Upgrade to Premium\n\n"
        "⚠️ *File size limit:*\n"
        f"Files larger than {config.MAX_FILE_SIZE_MB} MB cannot be uploaded directly. "
        "The bot will send you a direct download link instead.\n\n"
        "🌐 *Supported platforms include:*\n"
        "Terabox, YouTube, TikTok, Instagram, Twitter/X, "
        "Reddit, Facebook, Vimeo, Dailymotion, Streamtape, "
        "Bilibili, Twitch clips, SoundCloud + 1700 more."
    )
    await (update.message or update.callback_query.message).reply_text(
        text, parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────────────────────────────
# /status
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.first_name)

    is_admin = user.id == config.ADMIN_ID
    premium  = db.is_premium(user.id)
    used     = db.downloads_today(user.id)
    row      = db.get_user(user.id)

    if is_admin:
        plan_line = "👑 **Admin** — Unlimited & Free Forever"
    elif premium:
        until = row["premium_until"]
        if isinstance(until, str):
            until = datetime.fromisoformat(until)
        plan_line = f"⭐ **Premium** — Expires {until.strftime('%d %b %Y')}"
    else:
        remaining = max(config.FREE_DAILY_LIMIT - used, 0)
        plan_line = f"🆓 **Free Plan** — {remaining}/{config.FREE_DAILY_LIMIT} downloads left today"

    text = (
        f"📊 *Your Account Status*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Name: {user.first_name}\n"
        f"🆔 ID: `{user.id}`\n"
        f"📅 Downloads today: **{used}**\n"
        f"📋 Plan: {plan_line}\n"
    )

    keyboard = []
    if not premium and not is_admin:
        keyboard = [[InlineKeyboardButton("⭐ Upgrade to Premium", callback_data="subscribe")]]

    msg = update.message or update.callback_query.message
    await msg.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# /subscribe — Payment Info
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    if db.is_premium(user.id):
        await (update.message or update.callback_query.message).reply_text(
            "✅ You're already a **Premium** member! Enjoy unlimited downloads.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    text = (
        "⭐ *Upgrade to Premium*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Price: **{config.PREMIUM_PRICE}**\n\n"
        "✅ Benefits:\n"
        "• Unlimited video downloads\n"
        "• No daily quota restrictions\n"
        "• Priority processing\n\n"
        "💳 *How to pay:*\n"
        f"`{config.PAYMENT_UPI}`\n\n"
        f"📝 {config.PAYMENT_NOTE}\n\n"
        "After payment, send the screenshot to the bot admin and "
        "your account will be upgraded within a few minutes."
    )

    await (update.message or update.callback_query.message).reply_text(
        text, parse_mode=ParseMode.MARKDOWN
    )


# ──────────────────────────────────────────────────────────────────────────────
# Admin: /addpremium <user_id> [days]
# ──────────────────────────────────────────────────────────────────────────────

@admin_only
async def cmd_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/addpremium <user_id> [days]`\nDefault days = 30",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        target_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else 30
    except ValueError:
        await update.message.reply_text("❌ Invalid user_id or days. Both must be numbers.")
        return

    # Ensure user exists in DB
    if not db.get_user(target_id):
        db.upsert_user(target_id, None, f"User_{target_id}")

    db.set_premium(target_id, days)

    # Notify the target user
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 *Congratulations!* Your account has been upgraded to *Premium*!\n\n"
                f"⭐ You now have **unlimited downloads** for {days} days.\n"
                "Enjoy! 🚀"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError:
        pass  # User may not have started the bot yet

    await update.message.reply_text(
        f"✅ Premium granted to `{target_id}` for **{days} days**.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Admin: /removepremium <user_id>
# ──────────────────────────────────────────────────────────────────────────────

@admin_only
async def cmd_removepremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Usage: `/removepremium <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user_id.")
        return

    db.revoke_premium(target_id)

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="ℹ️ Your Premium subscription has ended. You're now on the Free plan.",
        )
    except TelegramError:
        pass

    await update.message.reply_text(f"✅ Premium revoked for `{target_id}`.", parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────────────────────
# Admin: /stats
# ──────────────────────────────────────────────────────────────────────────────

@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = db.get_stats()
    text = (
        "📈 *Bot Statistics*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total users:    **{s['total_users']}**\n"
        f"⭐ Premium users:  **{s['premium_users']}**\n"
        f"📥 Total downloads: **{s['total_dl']}**\n"
        f"📅 Downloads today: **{s['today_dl']}**\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────────────────────
# Admin: /listusers
# ──────────────────────────────────────────────────────────────────────────────

@admin_only
async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("No users yet.")
        return

    lines = ["👥 *All Users:*\n"]
    for u in users[:50]:  # cap at 50 to avoid message too long
        badge = "⭐" if u["is_premium"] else "🆓"
        name = u["first_name"] or u["username"] or "Unknown"
        lines.append(f"{badge} `{u['user_id']}` — {name}")

    if len(users) > 50:
        lines.append(f"\n...and {len(users) - 50} more.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ──────────────────────────────────────────────────────────────────────────────
# Admin: /broadcast <message>
# ──────────────────────────────────────────────────────────────────────────────

@admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: `/broadcast Your message here`\n"
            "Supports Markdown formatting.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    message = " ".join(context.args)
    users   = db.get_all_users()
    sent = failed = 0

    status_msg = await update.message.reply_text(
        f"📢 Broadcasting to {len(users)} users..."
    )

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user["user_id"],
                text=f"📢 *Broadcast Message:*\n\n{message}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent += 1
        except TelegramError:
            failed += 1
        await asyncio.sleep(0.05)  # respect Telegram rate limits

    await status_msg.edit_text(
        f"✅ Broadcast complete!\n✔️ Sent: {sent}\n❌ Failed: {failed}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Inline Button Callbacks
# ──────────────────────────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "help":
        await cmd_help(update, context)
    elif query.data == "subscribe":
        await cmd_subscribe(update, context)
    elif query.data == "status":
        await cmd_status(update, context)


# ──────────────────────────────────────────────────────────────────────────────
# Core: URL Download Handler
# ──────────────────────────────────────────────────────────────────────────────

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any message that contains a URL — the heart of the bot."""
    user = update.effective_user
    text = update.message.text or ""

    # Register/update user
    db.upsert_user(user.id, user.username, user.first_name)

    # Extract URL from message
    url = extract_url(text)
    if not url:
        await update.message.reply_text(
            "❓ I couldn't find a valid URL in your message.\n"
            "Please send a video link (e.g. a Terabox, YouTube or TikTok link)."
        )
        return

    # ── Subscription check ────────────────────────────────────────────────
    allowed, remaining = db.can_download(user.id)

    if not allowed:
        keyboard = [[InlineKeyboardButton("⭐ Get Premium", callback_data="subscribe")]]
        await update.message.reply_text(
            f"⛔ *Daily limit reached!*\n\n"
            f"You've used all **{config.FREE_DAILY_LIMIT}** free downloads for today.\n"
            f"Your quota resets in 24 hours.\n\n"
            f"⭐ Upgrade to **Premium** for *unlimited* downloads!\n"
            f"Price: {config.PREMIUM_PRICE}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # Show remaining quota (only for free users)
    is_admin  = user.id == config.ADMIN_ID
    is_prem   = db.is_premium(user.id)
    quota_note = ""
    if not is_admin and not is_prem and remaining > 0:
        quota_note = f"\n_(Free: {remaining - 1} download(s) left after this)_"

    # ── Start downloading ─────────────────────────────────────────────────
    processing_msg = await update.message.reply_text(
        f"⏳ *Processing your link...*{quota_note}\n`{url[:60]}{'...' if len(url) > 60 else ''}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)

    temp_dir = os.path.join(config.TEMP_DIR, str(user.id))

    try:
        await processing_msg.edit_text("🔍 *Fetching video info...*", parse_mode=ParseMode.MARKDOWN)
        result = await route_download(url, temp_dir)

        # ── Result handling ───────────────────────────────────────────────
        if result is None:
            await processing_msg.edit_text(
                "❌ *Download failed.*\n\n"
                "Possible reasons:\n"
                "• The link has expired or is private\n"
                "• The platform is not supported\n"
                "• Network issue (try again)\n\n"
                "If this keeps happening, contact the admin.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if result.startswith("TOOLARGE:"):
            direct_link = result[len("TOOLARGE:"):]
            await processing_msg.edit_text(
                f"⚠️ *File too large to send via Telegram* (>{config.MAX_FILE_SIZE_MB} MB)\n\n"
                f"📥 [Click here to download directly]({direct_link})\n\n"
                "_This is a Telegram limitation — files over 50 MB cannot be uploaded by bots._",
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            # Still count this as a download used
            db.log_download(user.id, url, "TOOLARGE")
            return

        # We have a real file
        file_size = get_file_size(result)
        size_str  = human_size(file_size)
        filename  = os.path.basename(result)

        await processing_msg.edit_text(
            f"📤 *Uploading* `{filename}` ({size_str})...",
            parse_mode=ParseMode.MARKDOWN,
        )
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_VIDEO)

        try:
            with open(result, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=(
                        f"✅ Here's your video!\n"
                        f"📁 `{filename}` · {size_str}\n"
                        f"🔗 Source: {url[:50]}{'...' if len(url) > 50 else ''}"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )
        except TelegramError as te:
            # Video send failed — try as document
            logger.warning("Video send failed, trying as document: %s", te)
            with open(result, "rb") as doc_file:
                await update.message.reply_document(
                    document=doc_file,
                    caption=(
                        f"✅ Here's your file!\n"
                        f"📁 `{filename}` · {size_str}"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                    read_timeout=120,
                    write_timeout=120,
                )

        # Log the download
        db.log_download(user.id, url, filename)

        # Delete the processing message
        try:
            await processing_msg.delete()
        except TelegramError:
            pass

        logger.info("Successfully delivered %s to user %s", filename, user.id)

    except Exception as exc:
        logger.exception("Unexpected error in handle_url for user %s: %s", user.id, exc)
        try:
            await processing_msg.edit_text(
                "💥 An unexpected error occurred. Please try again or contact the admin."
            )
        except TelegramError:
            pass

    finally:
        # Always clean up temp file
        if result and not result.startswith("TOOLARGE:"):
            cleanup(result)


# ──────────────────────────────────────────────────────────────────────────────
# Non-URL message handler
# ──────────────────────────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages that aren't URLs."""
    await update.message.reply_text(
        "📎 Please send me a video link!\n"
        "Type /help to see what I support.",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Application Setup
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Validate config first
    config.validate()

    # Initialise database
    db.init_db()

    # Create temp directory
    os.makedirs(config.TEMP_DIR, exist_ok=True)

    logger.info("Starting bot... Admin ID: %s", config.ADMIN_ID)

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .read_timeout(120)
        .write_timeout(120)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # ── Command handlers ──────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_help))
    app.add_handler(CommandHandler("status",        cmd_status))
    app.add_handler(CommandHandler("subscribe",     cmd_subscribe))

    # Admin commands
    app.add_handler(CommandHandler("addpremium",    cmd_addpremium))
    app.add_handler(CommandHandler("removepremium", cmd_removepremium))
    app.add_handler(CommandHandler("stats",         cmd_stats))
    app.add_handler(CommandHandler("listusers",     cmd_listusers))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))

    # ── Inline button callbacks ───────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(button_callback))

    # ── Message handlers ──────────────────────────────────────────────────
    # ALL non-command text messages go to handle_url first.
    # handle_url extracts the URL itself and falls back to handle_text if none found.
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_url
    ))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
