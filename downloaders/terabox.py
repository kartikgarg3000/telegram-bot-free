"""
downloaders/terabox.py — Downloads videos from Terabox and all Terabox-clone services.

Strategy (in order of priority):
  1. teraboxvideo.com public API  — fast, no login required
  2. terabox.app share/list API   — requires cookies + tokens from the HTML page
  3. yt-dlp with cookies          — last resort generic extractor

Supported domains:
  terabox.com, 1024terabox.com, teraboxapp.com, teraboxlink.com,
  momerybox.com, tibibox.com, nephobox.com, 4funbox.co, mirrobox.com,
  myqcloud.com, gibibox.com, gomafiles.com, terabox.app
"""

import asyncio
import logging
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

import aiohttp
import aiofiles
from playwright.async_api import async_playwright

import config

logger = logging.getLogger(__name__)

TERABOX_DOMAINS = {
    "terabox.com", "1024terabox.com", "teraboxapp.com", "teraboxlink.com",
    "momerybox.com", "tibibox.com", "nephobox.com", "4funbox.co",
    "mirrobox.com", "myqcloud.com", "gibibox.com", "gomafiles.com", "terabox.app",
}

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def is_terabox_url(url: str) -> bool:
    return any(d in url for d in TERABOX_DOMAINS)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 1: public bypass API
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_public_api(session: aiohttp.ClientSession, url: str) -> Optional[dict]:
    """
    Try a public Terabox resolver API.
    Returns dict with 'dlink' and 'filename' on success, None on failure.
    """
    apis = [
        f"https://teraboxvideo.com/api/v1/fetch?url={url}",
        f"https://teraboxlink.com/api/fetch?link={url}",
    ]
    for api_url in apis:
        try:
            async with session.get(
                api_url,
                headers={"User-Agent": _UA},
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json(content_type=None)
                dlink = (
                    data.get("dlink") or
                    data.get("download_link") or
                    data.get("direct_link") or
                    (data.get("data") or {}).get("dlink")
                )
                if dlink and dlink.startswith("http"):
                    return {
                        "dlink":    dlink,
                        "filename": data.get("filename") or data.get("name") or f"terabox_{int(time.time())}.mp4",
                        "size":     int(data.get("size") or data.get("filesize") or 0),
                    }
        except Exception as exc:
            logger.debug("Public API %s failed: %s", api_url, exc)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 2: Playwright Headless Browser Extraction
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_playwright(url: str) -> Optional[dict]:
    """
    Launch a headless browser, authenticate with cookie, and intercept the dlink.
    """
    if not config.TERABOX_COOKIE or config.TERABOX_COOKIE == "PASTE_YOUR_NDUS_COOKIE_HERE":
        logger.warning("Terabox: Missing TERABOX_COOKIE")
        return None

    # Parse cookies for Playwright
    cookies = []
    for c in config.TERABOX_COOKIE.split(";"):
        if "=" in c:
            name, val = c.strip().split("=", 1)
            cookies.append({"name": name, "value": val, "domain": ".terabox.com", "path": "/"})
            cookies.append({"name": name, "value": val, "domain": ".1024terabox.com", "path": "/"})
            cookies.append({"name": name, "value": val, "domain": ".terabox.app", "path": "/"})

    dlink = None
    filename = f"terabox_{int(time.time())}.mp4"
    size = 0

    try:
        async with async_playwright() as p:
            logger.info("Terabox: Launching headless browser...")
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=_UA)
            if cookies:
                await context.add_cookies(cookies)

            page = await context.new_page()

            # Intercept network to find the dlink API response or video stream
            async def on_response(response):
                nonlocal dlink, filename, size
                if "share/list" in response.url or "filemetas" in response.url:
                    try:
                        data = await response.json()
                        if data and "list" in data and len(data["list"]) > 0:
                            f = data["list"][0]
                            dl = f.get("dlink")
                            if dl:
                                dlink = dl
                                filename = f.get("server_filename", filename)
                                size = int(f.get("size", size))
                                logger.info("Terabox: Intercepted dlink via network!")
                    except Exception:
                        pass
                elif "/share/streaming" in response.url and not dlink:
                    # Fallback: capture the M3U8/FLV stream URL which yt-dlp can download
                    dlink = response.url
                    logger.info("Terabox: Intercepted streaming URL!")

            page.on("response", on_response)

            logger.info("Terabox: Navigating to %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait a few seconds for background API calls to finish
            await page.wait_for_timeout(3000)

            # If network interception didn't get it, try clicking the download button
            if not dlink:
                logger.info("Terabox: Network empty, looking for download button...")
                try:
                    dl_btn = page.locator("text=Download").first
                    if await dl_btn.is_visible(timeout=2000):
                        await dl_btn.click()
                        await page.wait_for_timeout(3000)  # Wait for click to trigger API
                except Exception as e:
                    logger.debug("Terabox: Download button click failed: %s", e)

            await browser.close()
            
            if dlink:
                return {
                    "dlink": dlink,
                    "filename": filename,
                    "size": size,
                }
            else:
                logger.warning("Terabox: Playwright failed to intercept dlink.")
                return None
    except Exception as exc:
        logger.error("Terabox Playwright error: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Strategy 3: yt-dlp with cookies (last resort)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_ytdlp(url: str, dest_dir: str) -> Optional[str]:
    """Fall back to yt-dlp's generic extractor, passing Terabox cookies."""
    from downloaders.ytdlp import download as ytdlp_download
    logger.info("Terabox: falling back to yt-dlp generic extractor")
    return await ytdlp_download(url, dest_dir)


# ─────────────────────────────────────────────────────────────────────────────
# File downloader (shared by strategies 1 & 2)
# ─────────────────────────────────────────────────────────────────────────────

async def _stream_to_file(
    session: aiohttp.ClientSession,
    dlink: str,
    dest_dir: str,
    filename: str,
    size_bytes: int,
) -> Optional[str]:
    """Download a direct link to disk, enforcing the file size limit."""
    max_bytes = config.MAX_FILE_SIZE_MB * 1024 * 1024
    if size_bytes and size_bytes > max_bytes:
        return f"TOOLARGE:{dlink}"

    dest_path = os.path.join(dest_dir, filename)
    dl_headers = {
        "User-Agent": _UA,
        "Referer":    "https://www.terabox.com/",
        "Cookie":     config.TERABOX_COOKIE if config.TERABOX_COOKIE else "",
    }

    try:
        async with session.get(
            dlink, headers=dl_headers,
            timeout=aiohttp.ClientTimeout(total=300),
            allow_redirects=True
        ) as resp:
            if resp.status != 200:
                logger.error("Terabox stream HTTP %s for %s", resp.status, dlink[:60])
                return None

            content_length = int(resp.headers.get("Content-Length", 0))
            if content_length and content_length > max_bytes:
                return f"TOOLARGE:{dlink}"

            written = 0
            async with aiofiles.open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(512 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        logger.warning("Terabox: size limit exceeded mid-download")
                        return f"TOOLARGE:{dlink}"
                    await f.write(chunk)

        logger.info("Terabox download done: %s (%d bytes)", dest_path, written)
        return dest_path

    except asyncio.TimeoutError:
        logger.error("Terabox stream timed out")
    except Exception as exc:
        logger.error("Terabox stream error: %s", exc)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

async def download(url: str, dest_dir: str) -> Optional[str]:
    os.makedirs(dest_dir, exist_ok=True)

    async with aiohttp.ClientSession() as session:

        # ── Strategy 1: Public API ────────────────────────────────────────
        logger.info("Terabox: trying public API...")
        info = await _fetch_via_public_api(session, url)
        if info and info.get("dlink"):
            logger.info("Public API succeeded: %s", info["filename"])
            result = await _stream_to_file(
                session, info["dlink"], dest_dir, info["filename"], info["size"]
            )
            if result:
                return result

        # ── Strategy 2: Playwright Headless Browser ─────────────────────────
        logger.info("Terabox: trying Playwright Headless extraction...")
        info = await _fetch_via_playwright(url)
        if info and info.get("dlink"):
            logger.info("Playwright extraction succeeded: %s", info["filename"])
            if "/share/streaming" in info["dlink"]:
                from downloaders.ytdlp import download_video
                logger.info("Terabox: Routing stream URL to yt-dlp...")
                result = await download_video(info["dlink"], dest_dir)
                if result:
                    return result
            else:
                result = await _stream_to_file(
                    session, info["dlink"], dest_dir, info["filename"], info["size"]
                )
                if result:
                    return result

    # ── Strategy 3: yt-dlp fallback ──────────────────────────────────────
    return await _fetch_via_ytdlp(url, dest_dir)
