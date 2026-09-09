"""
database.py — SQLite database layer for user management, download tracking,
and subscription handling.

Tables:
    users        — registered users (id, username, joined_at, is_premium, premium_until)
    downloads    — per-user download log (user_id, downloaded_at)
    admin_notes  — optional notes admin can attach to users
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional

import config

logger = logging.getLogger(__name__)

DB_PATH = "bot_data.db"


# ──────────────────────────────────────────────────────────────────────────────
# Connection Helper
# ──────────────────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    """Context manager that yields a thread-safe SQLite connection."""
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrency
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Schema Initialisation
# ──────────────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                joined_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_premium    INTEGER  DEFAULT 0,
                premium_until TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                url           TEXT,
                filename      TEXT,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
    logger.info("Database initialised at %s", DB_PATH)


# ──────────────────────────────────────────────────────────────────────────────
# User Operations
# ──────────────────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
    """Register a new user or update their name info."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name
        """, (user_id, username, first_name))


def get_user(user_id: int) -> Optional[sqlite3.Row]:
    """Fetch a single user row, or None if not found."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()


def get_all_users() -> list:
    """Return all user rows (for admin stats / broadcast)."""
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users ORDER BY joined_at DESC").fetchall()


# ──────────────────────────────────────────────────────────────────────────────
# Premium / Subscription
# ──────────────────────────────────────────────────────────────────────────────

def set_premium(user_id: int, days: int = 30) -> None:
    """Grant premium access for `days` days."""
    until = datetime.utcnow() + timedelta(days=days)
    with get_conn() as conn:
        conn.execute("""
            UPDATE users SET is_premium = 1, premium_until = ?
            WHERE user_id = ?
        """, (until, user_id))
    logger.info("User %s granted premium until %s", user_id, until)


def revoke_premium(user_id: int) -> None:
    """Remove premium access from a user."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE users SET is_premium = 0, premium_until = NULL
            WHERE user_id = ?
        """, (user_id,))
    logger.info("User %s premium revoked", user_id)


def is_premium(user_id: int) -> bool:
    """
    Return True if the user has active premium.
    Auto-revokes expired premium on check.
    """
    # Admin is always premium
    if user_id == config.ADMIN_ID:
        return True

    user = get_user(user_id)
    if not user:
        return False

    if user["is_premium"]:
        # Check expiry
        if user["premium_until"]:
            until = user["premium_until"]
            # sqlite3 returns either datetime or string depending on version
            if isinstance(until, str):
                until = datetime.fromisoformat(until)
            if datetime.utcnow() > until:
                revoke_premium(user_id)
                return False
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Download Tracking
# ──────────────────────────────────────────────────────────────────────────────

def log_download(user_id: int, url: str, filename: str = "") -> None:
    """Record a completed download."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO downloads (user_id, url, filename) VALUES (?, ?, ?)",
            (user_id, url, filename)
        )


def downloads_today(user_id: int) -> int:
    """Count how many downloads this user has made in the last 24 hours."""
    since = datetime.utcnow() - timedelta(hours=24)
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as cnt FROM downloads
            WHERE user_id = ? AND downloaded_at >= ?
        """, (user_id, since)).fetchone()
    return row["cnt"] if row else 0


def can_download(user_id: int) -> tuple[bool, int]:
    """
    Check if a user is allowed to download right now.

    Returns:
        (allowed: bool, remaining: int)
        remaining is the number of free downloads left today (-1 = unlimited)
    """
    # Admin always allowed
    if user_id == config.ADMIN_ID:
        return True, -1

    # Premium users are unlimited
    if is_premium(user_id):
        return True, -1

    count = downloads_today(user_id)
    remaining = config.FREE_DAILY_LIMIT - count
    return remaining > 0, max(remaining, 0)


# ──────────────────────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    """Return global bot statistics for the admin."""
    with get_conn() as conn:
        total_users   = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        premium_users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_premium = 1"
        ).fetchone()[0]
        total_dl      = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        today_since   = datetime.utcnow() - timedelta(hours=24)
        today_dl      = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE downloaded_at >= ?", (today_since,)
        ).fetchone()[0]

    return {
        "total_users":   total_users,
        "premium_users": premium_users,
        "total_dl":      total_dl,
        "today_dl":      today_dl,
    }
