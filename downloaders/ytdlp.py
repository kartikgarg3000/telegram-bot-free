"""
downloaders/ytdlp.py — Downloads videos using yt-dlp.

Works WITH or WITHOUT ffmpeg (auto-detected).
Supports YouTube, TikTok, Instagram, Twitter/X, Reddit, Facebook,
Vimeo, Dailymotion, and 1700+ more sites.
"""

import asyncio
import logging
import os
import glob
import time
import shutil
from typing import Optional

import yt_dlp

import config

logger = logging.getLogger(__name__)


def _find_ffmpeg() -> Optional[str]:
    """
    Find ffmpeg binary. Checks PATH first, then common install locations.
    Returns the directory containing ffmpeg.exe, or None if not found.
    """
    # Check if it's on PATH
    if shutil.which("ffmpeg"):
        return None  # None means yt-dlp will find it on PATH automatically

    # Common locations where users extract ffmpeg zips
    search_dirs = [
        r"D:\telegram bot\ffmpeg_bin",                           # our auto-downloaded binary
        r"D:\telegram bot\ffmpeg_bin\ffmpeg-master-latest-win64-gpl\bin",
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
        r"D:\ffmpeg\bin",
        r"D:\ffmpeg-9.0.1\bin",
        r"D:\ffmpeg-release-essentials\bin",
        r"C:\Users\91904\Downloads\ffmpeg\bin",
        r"C:\Users\91904\ffmpeg\bin",
    ]

    # Also search Downloads folder
    downloads = os.path.expanduser(r"~\Downloads")
    for entry in os.scandir(downloads) if os.path.exists(downloads) else []:
        if entry.is_dir() and "ffmpeg" in entry.name.lower():
            candidate = os.path.join(entry.path, "bin")
            search_dirs.append(candidate)
            search_dirs.append(entry.path)  # some zips have ffmpeg.exe at root

    for d in search_dirs:
        if os.path.exists(os.path.join(d, "ffmpeg.exe")):
            logger.info("Found ffmpeg at: %s", d)
            return d

    logger.warning("ffmpeg not found — downloading pre-merged formats only")
    return None


def _make_ydl_opts(dest_dir: str, ts: int) -> dict:
    """Build yt-dlp options with or without ffmpeg."""
    ffmpeg_dir = _find_ffmpeg()
    has_ffmpeg = (shutil.which("ffmpeg") is not None) or (ffmpeg_dir is not None)

    outtmpl = os.path.join(dest_dir, f"ytdlp_{ts}.%(ext)s")

    if has_ffmpeg:
        fmt = (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
            "/bestvideo[height<=720]+bestaudio"
            "/best[height<=720][ext=mp4]"
            "/best[ext=mp4]/best"
        )
    else:
        # No ffmpeg: only pre-merged single-file formats
        fmt = (
            "best[height<=720][ext=mp4]"
            "/best[height<=720]"
            "/best[ext=mp4]"
            "/best"
        )

    opts = {
        "format":          fmt,
        "outtmpl":         outtmpl,
        "quiet":           False,
        "no_warnings":     False,
        "noplaylist":      True,
        "max_filesize":    config.MAX_FILE_SIZE_MB * 1024 * 1024,
        "socket_timeout":  30,
        "retries":         3,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    }

    # Point yt-dlp at ffmpeg if found outside PATH
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir

    if has_ffmpeg:
        opts["merge_output_format"] = "mp4"

    return opts


async def download(url: str, dest_dir: str) -> Optional[str]:
    """
    Download a video using yt-dlp.

    Returns:
        - Absolute path to downloaded file on success
        - "TOOLARGE:<url>" if file exceeds Telegram's 50 MB limit
        - None on failure
    """
    os.makedirs(dest_dir, exist_ok=True)
    ts = int(time.time())
    opts = _make_ydl_opts(dest_dir, ts)

    def _do_download():
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                logger.info("yt-dlp: starting download → %s", url)
                info = ydl.extract_info(url, download=True)

                if info is None:
                    logger.error("yt-dlp: extract_info returned None for %s", url)
                    return None

                logger.info("yt-dlp: download complete, locating file…")

                # Strategy 1: prepare_filename
                try:
                    path = ydl.prepare_filename(info)
                    base = os.path.splitext(path)[0]
                    for ext in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mp3"):
                        if os.path.exists(base + ext):
                            logger.info("yt-dlp: file found (prepare_filename): %s", base + ext)
                            return base + ext
                except Exception as e:
                    logger.warning("yt-dlp: prepare_filename failed: %s", e)

                # Strategy 2: glob by timestamp prefix
                pattern = os.path.join(dest_dir, f"ytdlp_{ts}.*")
                matches = glob.glob(pattern)
                if matches:
                    best = max(matches, key=os.path.getsize)
                    logger.info("yt-dlp: file found (glob): %s", best)
                    return best

                # Strategy 3: newest file in dest_dir
                all_files = [
                    os.path.join(dest_dir, f)
                    for f in os.listdir(dest_dir)
                    if os.path.isfile(os.path.join(dest_dir, f))
                ]
                if all_files:
                    newest = max(all_files, key=os.path.getmtime)
                    logger.info("yt-dlp: file found (newest): %s", newest)
                    return newest

                logger.error("yt-dlp: no file found after download in %s", dest_dir)
                return None

        except yt_dlp.utils.MaxDownloadsReached:
            return "TOOLARGE"
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            if "file is larger than" in msg or "max_filesize" in msg:
                return "TOOLARGE"
            logger.error("yt-dlp DownloadError: %s", exc)
            return None
        except Exception as exc:
            logger.exception("yt-dlp unexpected error for %s: %s", url, exc)
            return None

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _do_download)

    if result == "TOOLARGE":
        return f"TOOLARGE:{url}"

    return result
