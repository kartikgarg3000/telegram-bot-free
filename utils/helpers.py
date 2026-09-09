"""
utils/helpers.py — Shared utility functions for the bot.
"""

import os
import logging
import re
from typing import Optional

from downloaders import terabox, ytdlp, generic

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# URL Utilities
# ──────────────────────────────────────────────────────────────────────────────

# Regex that matches a URL anywhere in a text message
_URL_RE = re.compile(
    r'https?://[^\s<>"\']+',
    re.IGNORECASE
)


def extract_url(text: str) -> Optional[str]:
    """Extract the first URL from a text string. Returns None if none found."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def is_valid_url(url: str) -> bool:
    return bool(_URL_RE.match(url))


# ──────────────────────────────────────────────────────────────────────────────
# Platform Router
# ──────────────────────────────────────────────────────────────────────────────

async def route_download(url: str, dest_dir: str) -> Optional[str]:
    """
    Detect the platform and route to the correct downloader.

    Priority:
      1. Terabox / Terabox-clone domains
      2. Direct video file URLs (ends in .mp4 etc.)
      3. yt-dlp (1700+ sites)

    Returns:
        - Path to downloaded file on success
        - "TOOLARGE:<url>" string if file is too large for Telegram
        - None on failure
    """
    url = url.strip().rstrip("/")

    if terabox.is_terabox_url(url):
        logger.info("Routing to Terabox downloader")
        return await terabox.download(url, dest_dir)

    if generic.is_direct_video_url(url):
        logger.info("Routing to generic (direct URL) downloader")
        result = await generic.download(url, dest_dir)
        if result:
            return result
        # If generic fails, try yt-dlp as a fallback
        logger.info("Generic failed, falling back to yt-dlp")

    logger.info("Routing to yt-dlp downloader")
    return await ytdlp.download(url, dest_dir)


# ──────────────────────────────────────────────────────────────────────────────
# File Utilities
# ──────────────────────────────────────────────────────────────────────────────

def cleanup(path: str) -> None:
    """Silently delete a file if it exists."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
            logger.debug("Cleaned up: %s", path)
    except Exception as exc:
        logger.warning("Cleanup failed for %s: %s", path, exc)


def human_size(num_bytes: int) -> str:
    """Convert bytes to a human-readable string like '12.4 MB'."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def get_file_size(path: str) -> int:
    """Return file size in bytes, or 0 if file doesn't exist."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
