"""
api/index.py — SEO & GEO API
Punto de entrada para Vercel (detecta automáticamente este archivo).

Endpoints:
  POST /analyze/seo        → Metadata SEO completa
  POST /analyze/geo        → Análisis GEO para LLMs
  POST /analyze/full       → SEO + GEO combinado
  POST /keywords           → Keyword research con intención + potencial GEO
  POST /schema             → Generador de JSON-LD / structured data
  POST /analyze/url        → Scraping + análisis SEO+GEO desde URL
  GET  /health             → Health check (sin auth, para RapidAPI)
"""
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from core.auth import verify_key
from core.llm import generate, GeminiUnavailableError
from core.rate_limit import limiter, get_limit
from core.scraper import fetch_url_text
from core.models import (
    TextInput, UrlInput,
    SeoMetadata, GeoAnalysis, FullAnalysis,
    KeywordResearchOutput, SchemaOutput,
    ErrorResponse,
)
from core.prompts import SEO_SYSTEM, GEO_SYSTEM, KEYWORD_SYSTEM, SCHEMA_SYSTEM


def _merge_text_input(
    body: TextInput | None,
    text: str | None,
    url: str | None,
    language: str | None,
    target_keyword: str | None,
) -> TextInput:
    """Fusiona query params con body JSON. Query params tienen prioridad."""
    if body is None:
        if not text:
            raise HTTPException(status_code=422, detail="Se requiere 'text' como query param o en el body JSON.")
        body = TextInput(text=text, url=url, language=language or "es", target_keyword=target_keyword)
    else:
        if text: body.text = text
        if url: body.url = url
        if language: body.language = language
        if target_keyword: body.target_keyword = target_keyword
    return body


def _merge_url_input(
    body: UrlInput | None,
    url: str | None,
    language: str | None,
    target_keyword: str | None,
) -> UrlInput:
    """Fusiona query params con body JSON para endpoints de URL."""
    if body is None:
        if not url:
            raise HTTPException(status_code=422, detail="Se requiere 'url' como query param o en el body JSON.")
        body = UrlInput(url=url, language=language or "es", target_keyword=target_keyword)
    else:
        if url: body.url = url
        if language: body.language = language
        if target_keyword: body.target_keyword = target_keyword
    return body

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("seo-geo-api")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SEO & GEO API",
    description="""
## SEO & GEO API — Optimización para buscadores tradicionales y motores de IA

Genera metadata SEO completa y analiza tu contenido para aparecer en las respuestas
de ChatGPT, Gemini, Perplexity y otros LLMs.

### Endpoints principales
- **POST /analyze/seo** — Title, meta description, slug, schema.org, puntuación SEO
- **POST /analyze/geo** — Snippet para IA, score GEO, entidades, sugerencias
- **POST /analyze/full** — SEO + GEO en una sola llamada
- **POST /analyze/url** — Scraping + análisis completo desde URL
- **POST /keywords** — Keyword research con intención + potencial GEO
- **POST /schema** — Generador de JSON-LD (Article, FAQ, HowTo, Product...)

### Autenticación
Incluye tu API key en la cabecera `x-api-key`.
    """,
    version="1.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

@app.exception_handler(GeminiUnavailableError)
async def gemini_unavailable_handler(request: Request, exc: GeminiUnavailableError):
    return JSONResponse(
        status_code=503,
        content={
            "warning": str(exc),
            "detail": "AI enrichment temporarily unavailable due to upstream provider issue.",
        },
    )

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Middleware de logging ──────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000)
    key = request.headers.get("x-api-key", "")
    key_hint = f"{key[:4]}…" if len(key) > 4 else "none"
    log.info(
        f"method={request.method} path={request.url.path} "
        f"status={response.status_code} duration_ms={duration_ms} key={key_hint}"
    )
    return response


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_content_prompt(data: TextInput | UrlInput) -> str:
    """Construye el prompt de usuario con toda la info disponible."""
    parts = []
    if hasattr(data, "url") and data.url:
        parts.append(f"URL: {data.url}")
    if hasattr(data, "text"):
        parts.append(f"CONTENIDO:\n{data.text}")
    if data.language:
        parts.append(f"IDIOMA OBJETIVO: {data.language}")
    if data.target_keyword:
        parts.append(f"KEYWORD PRINCIPAL: {data.target_keyword}")
    return "\n\n".join(parts)


def _parse_json(raw: str, model_class):
    """Parsea JSON de Gemini y valida con Pydantic."""
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
        return model_class(**data)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error parseando respuesta del modelo: {str(e)}. Raw: {raw[:200]}"
        )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    tags=["Status"],
    summary="Health check",
    response_description="API operativa",
)
async def health():
    """Endpoint público para verificar que la API está activa. Sin autenticación."""
    return {"status": "ok", "version": "1.1.0"}


# ── SEO ───────────────────────────────────────────────────────────────────────

@app.post(
    "/analyze/seo",
    response_model=SeoMetadata,
    tags=["SEO"],
    summary="Análisis SEO completo",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def analyze_seo(
    request: Request,
    body: TextInput | None = None,
    text: str | None = Query(None, description="Texto o contenido a analizar (mín. 10 chars)"),
    url: str | None = Query(None, description="URL de origen (opcional, mejora el contexto)"),
    language: str | None = Query(None, description="Idioma objetivo: es, en, fr, de, pt..."),
    target_keyword: str | None = Query(None, description="Keyword principal a optimizar"),
    _key: str = Depends(verify_key),
):
    """
    Genera metadata SEO completa a partir de un texto o contenido.

    Acepta parámetros como **query params** (`?text=...&target_keyword=...`) o como **JSON body**.

    **Devuelve:**
    - Title tag y meta description optimizados
    - Slug limpio
    - Keywords principal y secundarias (LSI)
    - Schema.org (Article, FAQ si aplica)
    - Open Graph tags
    - Puntuación SEO 0-100
    - Problemas detectados y sugerencias de mejora
    """
    data = _merge_text_input(body, text, url, language, target_keyword)
    prompt = _build_content_prompt(data)
    raw = await generate(SEO_SYSTEM, prompt)
    return _parse_json(raw, SeoMetadata)


# ── GEO ───────────────────────────────────────────────────────────────────────

@app.post(
    "/analyze/geo",
    response_model=GeoAnalysis,
    tags=["GEO"],
    summary="Análisis GEO — optimización para respuestas de IA",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def analyze_geo(
    request: Request,
    body: TextInput | None = None,
    text: str | None = Query(None, description="Texto o contenido a analizar"),
    url: str | None = Query(None, description="URL de origen (opcional)"),
    language: str | None = Query(None, description="Idioma objetivo: es, en, fr, de, pt..."),
    target_keyword: str | None = Query(None, description="Keyword principal"),
    _key: str = Depends(verify_key),
):
    """
    Analiza tu contenido para maximizar su visibilidad en ChatGPT, Gemini y Perplexity.

    Acepta parámetros como **query params** (`?text=...`) o como **JSON body**.

    **GEO (Generative Engine Optimization)** es la práctica de optimizar contenido
    para aparecer como fuente en las respuestas generadas por IA.

    **Devuelve:**
    - Score GEO 0-100
    - Snippet optimizado para ser citado por IA (<280 chars)
    - Resumen estructurado "answer-ready"
    - Entidades presentes y faltantes
    - Probabilidad de citación: baja | media | alta
    - Tipos de schema.org recomendados para GEO
    - Preguntas reales que tu contenido podría responder en ChatGPT/Perplexity
    """
    data = _merge_text_input(body, text, url, language, target_keyword)
    prompt = _build_content_prompt(data)
    raw = await generate(GEO_SYSTEM, prompt)
    return _parse_json(raw, GeoAnalysis)


# ── FULL ──────────────────────────────────────────────────────────────────────

@app.post(
    "/analyze/full",
    response_model=FullAnalysis,
    tags=["SEO", "GEO"],
    summary="Análisis SEO + GEO combinado",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def analyze_full(
    request: Request,
    body: TextInput | None = None,
    text: str | None = Query(None, description="Texto o contenido a analizar"),
    url: str | None = Query(None, description="URL de origen (opcional)"),
    language: str | None = Query(None, description="Idioma objetivo: es, en, fr, de, pt..."),
    target_keyword: str | None = Query(None, description="Keyword principal a optimizar"),
    _key: str = Depends(verify_key),
):
    """
    Ejecuta el análisis SEO y GEO en paralelo y devuelve ambos resultados.

    Acepta parámetros como **query params** (`?text=...&target_keyword=...`) o como **JSON body**.

    Equivale a llamar a `/analyze/seo` y `/analyze/geo` en una sola request.
    Ideal para integraciones donde necesitas la imagen completa del contenido.
    """
    import asyncio
    data = _merge_text_input(body, text, url, language, target_keyword)
    prompt = _build_content_prompt(data)

    seo_raw, geo_raw = await asyncio.gather(
        generate(SEO_SYSTEM, prompt),
        generate(GEO_SYSTEM, prompt),
    )

    seo = _parse_json(seo_raw, SeoMetadata)
    geo = _parse_json(geo_raw, GeoAnalysis)

    return FullAnalysis(seo=seo, geo=geo)


# ── URL ───────────────────────────────────────────────────────────────────────

@app.post(
    "/analyze/url",
    response_model=FullAnalysis,
    tags=["SEO", "GEO"],
    summary="Análisis SEO + GEO desde URL (scraping automático)",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def analyze_url(
    request: Request,
    body: UrlInput | None = None,
    url: str | None = Query(None, description="URL completa a analizar (https://...)"),
    language: str | None = Query(None, description="Idioma objetivo: es, en, fr, de, pt..."),
    target_keyword: str | None = Query(None, description="Keyword principal"),
    _key: str = Depends(verify_key),
):
    """
    Extrae el texto de una URL y ejecuta análisis SEO + GEO completo.

    Acepta la URL como **query param** (`?url=https://...`) o como **JSON body**.

    Útil cuando no quieres copiar el contenido manualmente: basta con la URL.
    El scraper extrae el texto visible, ignora navegación/footer y limpia el HTML.

    **Nota:** páginas que requieren JavaScript o login pueden devolver contenido parcial.
    """
    import asyncio
    data = _merge_url_input(body, url, language, target_keyword)
    fetched_text = await fetch_url_text(str(data.url))

    text_body = TextInput(
        text=fetched_text,
        url=str(data.url),
        language=data.language,
        target_keyword=data.target_keyword,
    )
    prompt = _build_content_prompt(text_body)

    seo_raw, geo_raw = await asyncio.gather(
        generate(SEO_SYSTEM, prompt),
        generate(GEO_SYSTEM, prompt),
    )

    return FullAnalysis(
        seo=_parse_json(seo_raw, SeoMetadata),
        geo=_parse_json(geo_raw, GeoAnalysis),
    )


# ── KEYWORDS ──────────────────────────────────────────────────────────────────

@app.post(
    "/keywords",
    response_model=KeywordResearchOutput,
    tags=["SEO", "GEO"],
    summary="Keyword research con intención y potencial GEO",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def keyword_research(
    request: Request,
    body: TextInput | None = None,
    text: str | None = Query(None, description="Tema o keyword semilla (ej: 'fibra óptica', 'vuelos baratos')"),
    language: str | None = Query(None, description="Idioma objetivo: es, en, fr, de, pt..."),
    target_keyword: str | None = Query(None, description="Keyword principal (opcional)"),
    _key: str = Depends(verify_key),
):
    """
    Genera ideas de keywords a partir de un tema o keyword semilla.

    Acepta parámetros como **query params** (`?text=fibra+óptica&language=es`) o como **JSON body**.

    **Exclusivo de esta API:**
    - Clasifica keywords por intención (informacional, transaccional...)
    - Estima potencial GEO: qué keywords tienen más probabilidad de generar
      respuestas de IA donde tu contenido sea citado
    - Identifica "GEO-first keywords": búsquedas donde vale más optimizar
      para LLMs que para Google
    - Sugiere ángulos de contenido concretos para cada keyword
    """
    data = _merge_text_input(body, text, None, language, target_keyword)
    prompt = f"Tema/keyword semilla: {data.text}\nIdioma: {data.language or 'es'}"
    raw = await generate(KEYWORD_SYSTEM, prompt)
    return _parse_json(raw, KeywordResearchOutput)


# ── SCHEMA ────────────────────────────────────────────────────────────────────

@app.post(
    "/schema",
    response_model=SchemaOutput,
    tags=["SEO"],
    summary="Generador de JSON-LD / structured data",
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def generate_schema(
    request: Request,
    body: TextInput | None = None,
    text: str | None = Query(None, description="Texto o contenido del que generar el schema.org"),
    url: str | None = Query(None, description="URL de origen (opcional)"),
    language: str | None = Query(None, description="Idioma objetivo: es, en, fr, de, pt..."),
    target_keyword: str | None = Query(None, description="Keyword principal (opcional)"),
    _key: str = Depends(verify_key),
):
    """
    Genera el JSON-LD de schema.org más adecuado para tu contenido.

    Acepta parámetros como **query params** (`?text=...`) o como **JSON body**.

    Detecta automáticamente el tipo más apropiado:
    Article, FAQPage, HowTo, Product, LocalBusiness, BreadcrumbList, etc.

    El JSON-LD devuelto está listo para insertar dentro de una etiqueta
    `<script type="application/ld+json">` en el `<head>` de tu página.
    """
    data = _merge_text_input(body, text, url, language, target_keyword)
    prompt = _build_content_prompt(data)
    raw = await generate(SCHEMA_SYSTEM, prompt)
    return _parse_json(raw, SchemaOutput)


# ── Dev server ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.index:app", host="0.0.0.0", port=8000, reload=True)
