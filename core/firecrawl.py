"""
core/firecrawl.py — Firecrawl API client.

Firecrawl renders JavaScript pages and returns:
  - markdown: clean structured text — exactly what LLMs (GPTBot, PerplexityBot) see
  - screenshot: full-page visual capture

One API call fetches both. If FIRECRAWL_API_KEY is not set, functions return None
so the caller can fall back to the BeautifulSoup scraper.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import HTTPException

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
TIMEOUT = 35.0


def _get_key() -> Optional[str]:
    return os.environ.get("FIRECRAWL_API_KEY", "").strip() or None


def _api_error(e: httpx.HTTPStatusError) -> HTTPException:
    body: dict = {}
    try:
        body = e.response.json()
    except Exception:
        pass
    return HTTPException(
        status_code=502,
        detail=f"Firecrawl error {e.response.status_code}: {body.get('error', str(e))}",
    )


async def scrape_page(url: str, want_screenshot: bool = False) -> dict:
    """
    Scrapes a URL with Firecrawl and returns a dict with:
      - markdown: str  — clean text as LLMs see it (always)
      - screenshot: str | None — full-page screenshot URL (if want_screenshot=True)
      - metadata: dict — title, description, og data extracted by Firecrawl

    Returns empty dict if FIRECRAWL_API_KEY is not set (caller falls back to BS4).
    Raises HTTPException on API errors.
    """
    key = _get_key()
    if not key:
        return {}  # caller will use fallback scraper

    formats = ["markdown"]
    if want_screenshot:
        formats.append("screenshot@fullPage")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "url": url,
                    "formats": formats,
                    "waitFor": 1500,
                    "onlyMainContent": True,   # strips nav/footer/ads — what LLMs see
                    "mobile": False,
                },
            )
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Firecrawl timeout al procesar la página.")
    except httpx.HTTPStatusError as e:
        raise _api_error(e)

    data = (resp.json().get("data") or {})
    return {
        "markdown": data.get("markdown", ""),
        "screenshot": data.get("screenshot"),
        "metadata": data.get("metadata") or {},
    }


async def get_screenshot(url: str) -> str:
    """
    Returns a full-page screenshot URL.
    Raises HTTPException 503 if key is missing.
    """
    if not _get_key():
        raise HTTPException(
            status_code=503,
            detail="FIRECRAWL_API_KEY not configured. Add it in Vercel → Settings → Environment Variables.",
        )
    result = await scrape_page(url, want_screenshot=True)
    if not result.get("screenshot"):
        raise HTTPException(status_code=502, detail="Firecrawl no devolvió screenshot.")
    return result["screenshot"]
