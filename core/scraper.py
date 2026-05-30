"""
core/scraper.py — Extracción de texto limpio desde una URL.

Usa httpx (async) + BeautifulSoup para:
1. Descargar el HTML con User-Agent de navegador real
2. Eliminar scripts, estilos, nav, footer, aside
3. Extraer el texto visible del <main> o <body> como fallback
4. Truncar a 8000 chars para no exceder el contexto del LLM
"""
import asyncio
import re

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException

# ── Configuración ─────────────────────────────────────────────────────────────

MAX_CHARS = 8_000
TIMEOUT = 15.0  # segundos

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SEO-GEO-API/1.1; +https://rapidapi.com/seo-geo-api)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es,en;q=0.9",
}

# Tags a eliminar completamente antes de extraer texto
NOISE_TAGS = [
    "script", "style", "noscript", "nav", "footer",
    "aside", "header", "form", "button", "svg", "img",
    "iframe", "meta", "link",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_text(html: str) -> str:
    """Extrae el texto visible y limpio del HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Eliminar ruido
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    # Preferir <main> o <article> si existen
    container = soup.find("main") or soup.find("article") or soup.body or soup

    raw = container.get_text(separator="\n", strip=True)

    # Comprimir líneas vacías múltiples
    text = re.sub(r"\n{3,}", "\n\n", raw).strip()

    return text[:MAX_CHARS]


# ── API pública ───────────────────────────────────────────────────────────────

async def fetch_url_text(url: str) -> str:
    """
    Descarga una URL y devuelve el texto limpio extraído.
    Lanza HTTPException con código apropiado si falla.
    """
    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=f"Timeout al intentar acceder a {url} (>{TIMEOUT}s)"
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"La URL devolvió HTTP {e.response.status_code}"
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=422,
            detail=f"No se pudo conectar con la URL: {str(e)}"
        )

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type:
        raise HTTPException(
            status_code=422,
            detail=f"La URL no devuelve HTML (content-type: {content_type})"
        )

    text = _extract_text(response.text)

    if len(text) < 50:
        raise HTTPException(
            status_code=422,
            detail="No se pudo extraer texto suficiente de la URL. "
                   "Puede ser una SPA o página con contenido detrás de login."
        )

    return text
