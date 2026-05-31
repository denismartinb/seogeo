"""
core/scraper.py — Extracción de texto limpio + metadatos estructurales desde una URL.

Usa httpx (async) + BeautifulSoup para:
1. Descargar el HTML con User-Agent de navegador real
2. Eliminar scripts, estilos, nav, footer, aside
3. Extraer el texto visible del <main> o <body> como fallback
4. Truncar a 8000 chars para no exceder el contexto del LLM
5. Extraer metadatos estructurales (h1, h2, title, meta, visibilidad)
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


# Clases CSS comunes que ocultan visualmente un elemento
_HIDDEN_CLASSES = {
    "visuallyhidden", "visually-hidden", "sr-only", "screen-reader-only",
    "hidden", "hide", "invisible", "offscreen", "off-screen", "a11y-hidden",
}


def _is_visually_hidden(tag) -> bool:
    """Detecta si un elemento está visualmente oculto con CSS."""
    classes = set((tag.get("class") or []))
    if classes & _HIDDEN_CLASSES:
        return True
    style = tag.get("style", "")
    if any(s in style.replace(" ", "") for s in [
        "display:none", "visibility:hidden", "opacity:0",
        "width:0", "height:0", "clip:", "position:absolute;left:-",
    ]):
        return True
    return False


def _extract_metadata(html: str) -> dict:
    """
    Extrae metadatos estructurales del HTML:
    - title: <title> tag
    - meta_description: <meta name="description">
    - h1: lista de {text, hidden} para cada <h1>
    - h2: lista de textos de <h2>
    - canonical: URL canónica si existe
    """
    soup = BeautifulSoup(html, "html.parser")

    # <title>
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # <meta name="description">
    meta_desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_description = meta_desc_tag.get("content", "") if meta_desc_tag else ""

    # <link rel="canonical">
    canonical_tag = soup.find("link", attrs={"rel": re.compile(r"^canonical$", re.I)})
    canonical = canonical_tag.get("href", "") if canonical_tag else ""

    # <h1> tags — incluye visibilidad
    h1_tags = []
    for h1 in soup.find_all("h1"):
        text = h1.get_text(strip=True)
        if text:
            h1_tags.append({
                "text": text,
                "hidden": _is_visually_hidden(h1),
                "classes": " ".join(h1.get("class") or []),
            })

    # <h2> tags (primeros 6)
    h2_tags = [h2.get_text(strip=True) for h2 in soup.find_all("h2")[:6] if h2.get_text(strip=True)]

    # Structured data presence
    schemas = [s.get("type", "") for s in soup.find_all("script", attrs={"type": "application/ld+json"})]

    return {
        "title": title,
        "meta_description": meta_description,
        "canonical": canonical,
        "h1": h1_tags,
        "h2": h2_tags,
        "has_schema": len(schemas) > 0,
        "schema_count": len(schemas),
    }


def _build_structure_context(metadata: dict) -> str:
    """Formatea los metadatos como contexto legible para el LLM."""
    lines = []

    lines.append(f"TÍTULO DE PÁGINA: {metadata.get('title', '(no detectado)') or '(no detectado)'}")
    lines.append(f"META DESCRIPTION: {metadata.get('meta_description', '(no existe)') or '(no existe)'}")

    h1s = metadata.get("h1", [])
    if not h1s:
        lines.append("H1: (no existe ningún H1 en la página)")
    else:
        for i, h in enumerate(h1s):
            hidden_note = " ⚠ OCULTO VISUALMENTE (clase: " + h.get("classes", "") + ")" if h.get("hidden") else ""
            lines.append(f"H1[{i+1}]: \"{h['text']}\"{hidden_note}")

    if metadata.get("h2"):
        lines.append("H2s detectados: " + " | ".join(metadata["h2"][:4]))

    if metadata.get("canonical"):
        lines.append(f"CANONICAL: {metadata['canonical']}")

    lines.append(f"STRUCTURED DATA: {'Sí (' + str(metadata['schema_count']) + ' schemas)' if metadata.get('has_schema') else 'No tiene schema.org'}")

    return "\n".join(lines)


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


async def fetch_url_content(url: str, want_screenshot: bool = False) -> tuple:
    """
    Descarga una URL y devuelve (texto_limpio, metadatos_estructurales).

    Estrategia:
      1. Si FIRECRAWL_API_KEY está configurada → usa Firecrawl (markdown limpio,
         exactamente lo que los LLMs ven; maneja JS y SPAs correctamente).
      2. Fallback → BeautifulSoup sobre el HTML crudo.

    Los metadatos siempre incluyen h1, h2, title, meta_description, schema, canonical.
    Lanza HTTPException si falla.
    """
    # ── Firecrawl path (preferred) ────────────────────────────────────────────
    try:
        from core.firecrawl import scrape_page, _get_key
        if _get_key():
            fc = await scrape_page(url, want_screenshot=want_screenshot)
            if fc and fc.get("markdown") and len(fc["markdown"]) > 50:
                # Firecrawl already strips nav/footer/ads — this is what LLMs see
                text = fc["markdown"][:MAX_CHARS]
                # Extract structural metadata from Firecrawl's metadata field
                fc_meta = fc.get("metadata") or {}
                # Still scrape the raw HTML for structural metadata (h1 hidden detection, etc.)
                raw_metadata = {}
                try:
                    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
                        resp = await client.get(url)
                        if "html" in resp.headers.get("content-type", ""):
                            raw_metadata = _extract_metadata(resp.text)
                except Exception:
                    pass
                # Merge: prefer Firecrawl metadata for title/description, raw for h1 hidden detection
                metadata = {
                    **raw_metadata,
                    "title": fc_meta.get("title") or raw_metadata.get("title", ""),
                    "meta_description": fc_meta.get("description") or raw_metadata.get("meta_description", ""),
                    "_source": "firecrawl",
                    "_screenshot": fc.get("screenshot"),
                }
                return text, metadata
    except Exception:
        pass  # fall through to BS4

    # ── BeautifulSoup fallback ────────────────────────────────────────────────
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
        raise HTTPException(status_code=504, detail=f"Timeout al intentar acceder a {url} (>{TIMEOUT}s)")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"La URL devolvió HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=422, detail=f"No se pudo conectar con la URL: {str(e)}")

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type:
        raise HTTPException(status_code=422, detail=f"La URL no devuelve HTML (content-type: {content_type})")

    html = response.text
    text = _extract_text(html)
    if len(text) < 50:
        raise HTTPException(
            status_code=422,
            detail="No se pudo extraer texto suficiente de la URL. Puede ser una SPA o página con login."
        )

    metadata = _extract_metadata(html)
    metadata["_source"] = "beautifulsoup"
    return text, metadata
