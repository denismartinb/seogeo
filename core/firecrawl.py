"""
core/firecrawl.py — Firecrawl API client for real page screenshots.

Firecrawl renders JavaScript-heavy pages and returns a full-page screenshot.
Requires FIRECRAWL_API_KEY env var (get one free at firecrawl.dev).
"""
from __future__ import annotations

import os
import asyncio
from functools import lru_cache
from typing import Optional

import httpx
from fastapi import HTTPException

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
TIMEOUT = 30.0


def _get_key() -> Optional[str]:
    return os.environ.get("FIRECRAWL_API_KEY", "").strip() or None


async def get_screenshot(url: str) -> str:
    """
    Takes a full-page screenshot of the given URL via Firecrawl.
    Returns the screenshot URL (hosted by Firecrawl CDN).
    Raises HTTPException if the API call fails or key is missing.
    """
    key = _get_key()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="FIRECRAWL_API_KEY not configured. Add it in Vercel → Settings → Environment Variables.",
        )

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "formats": ["screenshot@fullPage"],
                    "waitFor": 1500,          # ms to wait for JS rendering
                    "mobile": False,
                    "skipTlsVerification": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Firecrawl timeout al capturar la página.")
    except httpx.HTTPStatusError as e:
        body = {}
        try:
            body = e.response.json()
        except Exception:
            pass
        raise HTTPException(
            status_code=502,
            detail=f"Firecrawl error {e.response.status_code}: {body.get('error', str(e))}",
        )

    screenshot_url = (data.get("data") or {}).get("screenshot")
    if not screenshot_url:
        raise HTTPException(status_code=502, detail="Firecrawl no devolvió screenshot.")

    return screenshot_url
