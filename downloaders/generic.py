"""
downloaders/generic.py — Generic fallback downloader for direct .mp4 / video links.

Handles URLs that end in a video file extension and are directly accessible
without authentication (e.g. CDN-hosted mp4s, direct file links).
"""

import asyncio
import logging
import os
import time
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import aiofiles

import config

logger = logging.getLogger(__name__)

# Common video file extensions we consider "direct" links
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".m4v", ".3gp"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def is_direct_video_url(url: str) -> bool:
    """Return True if the URL path ends with a known video extension."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)


async def download(url: str, dest_dir: str) -> Optional[str]:
    """
    Stream-download a direct video URL to disk.

    Returns:
        Path to saved file, or None on failure.
        "TOOLARGE:<url>" if the content-length exceeds the size limit.
    """
    os.makedirs(dest_dir, exist_ok=True)

    # Derive a filename from the URL path, fall back to timestamp
    path_part = urlparse(url).path
    basename = os.path.basename(path_part) or f"video_{int(time.time())}.mp4"
    # Sanitise filename
    basename = "".join(c for c in basename if c.isalnum() or c in (".", "-", "_"))
    dest_path = os.path.join(dest_dir, basename)

    max_bytes = config.MAX_FILE_SIZE_MB * 1024 * 1024

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=_HEADERS,
                timeout=aiohttp.ClientTimeout(total=300),
                allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    logger.error("Generic download HTTP %s for %s", resp.status, url)
                    return None

                content_length = int(resp.headers.get("Content-Length", 0))
                if content_length and content_length > max_bytes:
                    return f"TOOLARGE:{url}"

                written = 0
                async with aiofiles.open(dest_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 512):
                        written += len(chunk)
                        if written > max_bytes:
                            logger.warning("File exceeded size limit mid-download, aborting")
                            return f"TOOLARGE:{url}"
                        await f.write(chunk)

        logger.info("Generic download complete: %s (%s bytes)", dest_path, written)
        return dest_path

    except asyncio.TimeoutError:
        logger.error("Generic download timed out: %s", url)
    except Exception as exc:
        logger.error("Generic download error for %s: %s", url, exc)

    return None
