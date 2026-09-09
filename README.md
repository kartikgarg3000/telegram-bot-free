# 🎬 Telegram Video Downloader Bot

A Telegram bot that downloads videos from **Terabox, YouTube, TikTok, Instagram, Twitter/X, Reddit, and 1700+ other sites** — delivering them directly in chat with **no ads and no redirects**.

Includes a **subscription system**: free users get 2 downloads/day, Premium users get unlimited access.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🎬 Multi-platform | Terabox + 1700 sites via yt-dlp |
| 🆓 Free tier | 2 downloads per 24 hours |
| ⭐ Premium | Unlimited downloads |
| 👑 Admin bypass | Admin always gets unlimited |
| 📊 Admin panel | Stats, user management, broadcast |
| 💾 SQLite DB | Persistent user & quota tracking |
| 🔔 Progress messages | Live status while downloading |

---

## 🚀 Setup

### 1. Prerequisites

- Python 3.10+
- `ffmpeg` installed and in your PATH ([download here](https://ffmpeg.org/download.html))

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure secrets

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=your_telegram_bot_token     # From @BotFather
ADMIN_ID=your_telegram_user_id        # From @userinfobot
TERABOX_COOKIE=your_ndus_cookie_value # From browser DevTools

PAYMENT_UPI=yourname@upi
PAYMENT_NOTE=Pay and DM me a screenshot
PREMIUM_PRICE=₹49/month
```

#### How to get your Terabox cookie:
1. Open [terabox.com](https://terabox.com) and log in
2. Press **F12** → **Application** tab → **Cookies** → `terabox.com`
3. Copy the value of the **`ndus`** cookie

#### How to get your Telegram user ID:
- Message [@userinfobot](https://t.me/userinfobot) on Telegram

### 4. Run the bot

```bash
python bot.py
```

---

## 📋 Commands

### User Commands
| Command | Description |
|---|---|
| `/start` | Welcome message & main menu |
| `/help` | Usage guide & supported platforms |
| `/status` | Your subscription status & downloads left |
| `/subscribe` | Payment info to upgrade to Premium |

### Admin Commands (admin only)
| Command | Description |
|---|---|
| `/addpremium <id> [days]` | Grant premium to a user (default: 30 days) |
| `/removepremium <id>` | Revoke a user's premium |
| `/stats` | Global bot statistics |
| `/listusers` | List all users with their plan |
| `/broadcast <message>` | Send a message to all users |

---

## 💳 Subscription Model

| Plan | Downloads/day | Price |
|---|---|---|
| 🆓 Free | 2 per 24 hours | Free |
| ⭐ Premium | Unlimited | Configurable in `.env` |
| 👑 Admin | Unlimited | Free forever |

When a free user hits their limit, they see a payment prompt. After payment:
1. User sends you a screenshot
2. You run `/addpremium <their_user_id>` in the bot
3. Their account is instantly upgraded

---

## ⚠️ Notes

- **Telegram file limit:** Files over 50 MB cannot be sent by bots. The bot sends a direct download link instead.
- **ffmpeg required** for yt-dlp to merge video+audio streams. Install it from [ffmpeg.org](https://ffmpeg.org).
- **Terabox cookies expire.** If Terabox downloads stop working, log in again and update `TERABOX_COOKIE` in `.env`.

---

## 📁 Project Structure

```
telegram bot/
├── bot.py              # Main bot entry point
├── config.py           # Environment variable loader
├── database.py         # SQLite DB — users, downloads, subscriptions
├── downloaders/
│   ├── terabox.py      # Terabox & clones
│   ├── ytdlp.py        # yt-dlp wrapper (1700+ sites)
│   └── generic.py      # Direct .mp4 URL downloader
├── utils/
│   └── helpers.py      # URL routing, file utils
├── requirements.txt
├── .env.example
└── README.md
```
