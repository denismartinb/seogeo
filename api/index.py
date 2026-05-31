"""
api/index.py — SEO & GEO API  (Python 3.10+ required)
Entrypoint para Vercel.

Endpoints:
  POST /analyze/seo  · POST /analyze/geo  · POST /analyze/full
  POST /analyze/url  · POST /keywords     · POST /schema
  POST /v2/analyze   · GET  /v2/analyses  · GET  /v2/analyses/{id}
  DELETE /v2/analyses/{id}  · POST /v2/analyses/{id}/improvements
  GET  /app          · GET  /health
"""
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from core.auth import verify_key
from core.llm import generate, GeminiUnavailableError
from core.rate_limit import limiter, get_limit
from core.scraper import fetch_url_text, fetch_url_content, _build_structure_context
from core.scorer import score_content
from core.models import (
    TextInput, UrlInput, TextInputBody, UrlInputBody,
    SeoMetadata, GeoAnalysis, FullAnalysis,
    KeywordResearchOutput, SchemaOutput,
    ImproveBody, ImproveOutput,
    ErrorResponse,
    V2AnalyzeBody, V2AnalysisResponse, AnalysisSummary, AnalysisDetail,
    ImprovementsOutput, ImprovementItem,
    GenerateBlockBody, GenerateBlockOutput,
)
from core.prompts import SEO_SYSTEM, GEO_SYSTEM, KEYWORD_SYSTEM, SCHEMA_SYSTEM, IMPROVEMENTS_SYSTEM
from core.db import init_db, save_analysis, list_analyses, get_analysis, delete_analysis, get_cached_improvements, save_improvements

IMPROVE_SYSTEM = """Eres un experto en SEO y GEO (Generative Engine Optimization). Mejoras textos aplicando instrucciones específicas para optimizarlos tanto para Google como para aparecer en respuestas de ChatGPT, Gemini y Perplexity. Mantienes siempre el tono, estilo y longitud similar al original."""


def _merge_text_input(
    body: TextInputBody | None,
    text: str | None,
    url: str | None,
    language: str | None,
    target_keyword: str | None,
) -> TextInput:
    """Fusiona query params con body JSON. Query params tienen prioridad."""
    merged_text = text or (body.text if body else None) or (body.content if body else None)
    merged_url = url or (body.url if body else None)
    merged_lang = language or (body.language if body else None) or "es"
    merged_kw = target_keyword or (body.target_keyword if body else None)

    if not merged_text:
        raise HTTPException(status_code=422, detail="Se requiere 'text' como query param o en el body JSON.")
    return TextInput(text=merged_text, url=merged_url, language=merged_lang, target_keyword=merged_kw)


def _merge_url_input(
    body: UrlInputBody | None,
    url: str | None,
    language: str | None,
    target_keyword: str | None,
) -> UrlInput:
    """Fusiona query params con body JSON para endpoints de URL."""
    merged_url = url or (body.url if body else None)
    merged_lang = language or (body.language if body else None) or "es"
    merged_kw = target_keyword or (body.target_keyword if body else None)

    if not merged_url:
        raise HTTPException(status_code=422, detail="Se requiere 'url' como query param o en el body JSON.")
    return UrlInput(url=merged_url, language=merged_lang, target_keyword=merged_kw)

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
    allow_headers=["*", "x-api-key", "X-RapidAPI-Proxy-Secret", "Content-Type", "Authorization"],
    expose_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    await init_db()


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

@app.post("/debug-body", include_in_schema=False)
async def debug_body(request: Request):
    """Temporal: muestra el body raw que recibe FastAPI."""
    body_bytes = await request.body()
    headers = dict(request.headers)
    try:
        body_json = await request.json()
    except Exception as e:
        body_json = {"parse_error": str(e)}
    return {"raw": body_bytes.decode("utf-8", errors="replace"), "json": body_json, "content_type": headers.get("content-type")}


@app.get("/debug-keys", include_in_schema=False)
async def debug_keys():
    """Temporal: muestra las keys configuradas en Vercel."""
    raw = os.environ.get("API_KEYS", "VACÍO")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return {"raw_length": len(raw), "num_keys": len(keys), "keys_preview": [k[:8]+"…" for k in keys]}


@app.post(
    "/improve",
    response_model=ImproveOutput,
    tags=["Tools"],
    summary="Mejora el texto aplicando sugerencias SEO/GEO seleccionadas",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def improve_content(
    request: Request,
    body: ImproveBody | None = None,
    _key: str = Depends(verify_key),
):
    """
    Reescribe el texto original aplicando las mejoras SEO/GEO seleccionadas.
    Recibe el texto y una lista de instrucciones de mejora; devuelve el texto mejorado
    y la lista de cambios realizados.
    """
    text_val = (body.text or body.content) if body else None
    improvements_val = (body.improvements or []) if body else []
    language_val = (body.language if body else None) or "es"

    if not text_val:
        raise HTTPException(status_code=422, detail="Se requiere 'text' en el body JSON.")
    if not improvements_val:
        raise HTTPException(status_code=422, detail="Se requiere al menos una mejora en 'improvements'.")

    improvements_str = "\n".join(f"- {i}" for i in improvements_val)
    prompt = f"""Texto original:
---
{text_val}
---

Mejoras a aplicar (aplícalas TODAS):
{improvements_str}

Idioma: {language_val}

Instrucciones:
1. Reescribe el texto completo aplicando todas las mejoras listadas
2. Mantén el tono, estilo y extensión similar al original
3. Solo añade información nueva cuando la mejora lo pida explícitamente
4. Si se pide añadir un snippet, ponlo como primer párrafo
5. Si se pide incorporar entidades, menciónalas de forma natural con una frase de contexto
6. Si se pide integrar keywords, hazlo de forma fluida sin forzarlas

Devuelve ÚNICAMENTE un JSON válido con:
- improved_text: string con el texto completo mejorado
- changes_made: array de strings describiendo brevemente cada cambio realizado"""

    raw = await generate(IMPROVE_SYSTEM, prompt)
    return _parse_json(raw, ImproveOutput)


@app.get("/playground", response_class=HTMLResponse, include_in_schema=False)
async def playground():
    """Playground UI para probar la API."""
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playground.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


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
    body: TextInputBody | None = None,
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
    body: TextInputBody | None = None,
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
    body: TextInputBody | None = None,
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
    body: UrlInputBody | None = None,
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
    body: TextInputBody | None = None,
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
    body: TextInputBody | None = None,
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


# ── App UI ────────────────────────────────────────────────────────────────────

@app.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def serve_app():
    """SEO & GEO Optimizer — aplicación web.

    Inyecta la primera API_KEY del servidor como token de la app,
    de modo que el frontend funciona sin configuración adicional.
    En modo dev (ENVIRONMENT=dev) la auth está desactivada y la key queda vacía.
    """
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Inject app token: first API key in list, or empty string in dev
    app_key = ""
    if os.environ.get("ENVIRONMENT", "prod") != "dev":
        raw_keys = os.environ.get("API_KEYS", "")
        keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        if keys:
            app_key = keys[0]

    html = html.replace("'__APP_API_KEY__'", f"'{app_key}'")
    return HTMLResponse(content=html)


# ── V2 API ────────────────────────────────────────────────────────────────────

async def _run_full_analysis(type_: str, input_data: dict) -> dict:
    """Runs SEO+GEO (or keywords) analysis and returns a serializable dict."""
    import asyncio

    if type_ == "keywords":
        text = input_data.get("text", "")
        language = input_data.get("language", "es")
        prompt = f"Tema/keyword semilla: {text}\nIdioma: {language}"
        raw = await generate(KEYWORD_SYSTEM, prompt)
        result = _parse_json(raw, KeywordResearchOutput)
        return result.model_dump()

    page_metadata: dict = {}

    if type_ == "url":
        url_str = input_data.get("url", "")
        fetched_text, page_metadata = await fetch_url_content(url_str)
        structure_ctx = _build_structure_context(page_metadata)
        text_body = TextInput(
            text=fetched_text,
            url=url_str,
            language=input_data.get("language", "es"),
            target_keyword=input_data.get("target_keyword"),
        )
    else:
        fetched_text = input_data.get("text", "")
        structure_ctx = ""
        text_body = TextInput(
            text=fetched_text,
            url=input_data.get("url"),
            language=input_data.get("language", "es"),
            target_keyword=input_data.get("target_keyword"),
        )

    # ── 1. Deterministic scoring (always consistent) ──────────────────────────
    scores = score_content(
        text=fetched_text,
        metadata=page_metadata,
        target_keyword=input_data.get("target_keyword"),
    )
    seo_computed = scores["seo"]
    geo_computed = scores["geo"]

    # ── 2. Build LLM prompt with pre-computed scores injected ─────────────────
    prompt = _build_content_prompt(text_body)

    score_ctx = f"""SCORES PRECALCULADOS (usa estos valores exactos en el JSON, no los recalcules):
SEO_SCORE: {seo_computed['seo_score']}
SEO_BREAKDOWN: {seo_computed['score_breakdown']}
GEO_SCORE: {geo_computed['geo_score']}
GEO_BREAKDOWN: {geo_computed['score_breakdown']}
CITATION_LIKELIHOOD: {geo_computed['citation_likelihood_computed']}
WORD_COUNT: {seo_computed['word_count']}

"""
    if structure_ctx:
        score_ctx += f"ESTRUCTURA ACTUAL DE LA PÁGINA:\n{structure_ctx}\n\n"

    score_ctx += "IMPORTANTE: Tu respuesta debe ser SOLO el JSON solicitado, sin texto previo.\n\n"
    prompt = score_ctx + prompt

    # ── 3. LLM generates qualitative fields only ──────────────────────────────
    seo_raw, geo_raw = await asyncio.gather(
        generate(SEO_SYSTEM, prompt),
        generate(GEO_SYSTEM, prompt),
    )
    seo = _parse_json(seo_raw, SeoMetadata)
    geo = _parse_json(geo_raw, GeoAnalysis)

    # ── 4. Override qualitative scores with deterministic ones ─────────────────
    # The LLM might still return a different number despite instructions —
    # we always enforce the computed score.
    seo_dict = seo.model_dump()
    seo_dict["seo_score"] = seo_computed["seo_score"]
    seo_dict["score_breakdown"] = seo_computed["score_breakdown"]

    geo_dict = geo.model_dump()
    geo_dict["geo_score"] = geo_computed["geo_score"]
    geo_dict["score_breakdown"] = geo_computed["score_breakdown"]
    geo_dict["citation_likelihood"] = geo_computed["citation_likelihood_computed"]

    result = {
        "seo": seo_dict,
        "geo": geo_dict,
    }
    result["_original_text"] = fetched_text[:8000] if fetched_text else ""
    result["_page_metadata"] = page_metadata
    return result


@app.post(
    "/v2/analyze",
    response_model=V2AnalysisResponse,
    tags=["V2"],
    summary="Analiza y persiste (URL, texto o keywords)",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def v2_analyze(
    request: Request,
    body: V2AnalyzeBody | None = None,
    _key: str = Depends(verify_key),
):
    """
    Ejecuta un análisis SEO+GEO (o keyword research) y lo persiste en la base de datos.

    - **type=url** — scraping automático + análisis completo
    - **type=text** — análisis de texto pegado directamente
    - **type=keywords** — keyword research con potencial GEO
    """
    if not body:
        raise HTTPException(status_code=422, detail="Se requiere body JSON con 'type', 'url'/'text' según el tipo.")

    input_data = body.model_dump(exclude={"session_id"})
    result = await _run_full_analysis(body.type, input_data)

    analysis_id = await save_analysis(
        type_=body.type,
        input_data=input_data,
        result=result,
        session_id=body.session_id,
    )

    seo_score = None
    geo_score = None
    if body.type != "keywords":
        seo_score = result.get("seo", {}).get("seo_score")
        geo_score = result.get("geo", {}).get("geo_score")

    from core.db import _extract_title
    title = _extract_title(body.type, input_data, result)

    from datetime import datetime
    return V2AnalysisResponse(
        analysis_id=analysis_id,
        type=body.type,
        title=title,
        result=result,
        seo_score=seo_score,
        geo_score=geo_score,
        created_at=datetime.utcnow().isoformat(),
    )


@app.get(
    "/v2/analyses",
    response_model=list[AnalysisSummary],
    tags=["V2"],
    summary="Lista análisis recientes",
)
async def v2_list_analyses(
    session_id: str | None = Query(None, description="Filtra por sesión de navegador"),
    limit: int = Query(20, ge=1, le=100),
):
    rows = await list_analyses(session_id=session_id, limit=limit)
    return rows


@app.get(
    "/v2/analyses/{analysis_id}",
    response_model=AnalysisDetail,
    tags=["V2"],
    summary="Obtiene un análisis completo",
    responses={404: {"model": ErrorResponse}},
)
async def v2_get_analysis(analysis_id: str):
    row = await get_analysis(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")
    return row


@app.delete(
    "/v2/analyses/{analysis_id}",
    tags=["V2"],
    summary="Elimina un análisis",
    responses={404: {"model": ErrorResponse}},
)
async def v2_delete_analysis(analysis_id: str, _key: str = Depends(verify_key)):
    deleted = await delete_analysis(analysis_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")
    return {"deleted": True}


@app.post(
    "/v2/analyses/{analysis_id}/improvements",
    response_model=ImprovementsOutput,
    tags=["V2"],
    summary="Genera mejoras priorizadas con estimación de impacto en score",
    responses={404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def v2_get_improvements(
    request: Request,
    analysis_id: str,
    _key: str = Depends(verify_key),
):
    """
    Genera una lista de mejoras concretas y priorizadas para el análisis indicado.

    Cada mejora incluye:
    - Elemento específico a mejorar (title_tag, meta_description, ai_snippet, etc.)
    - Problema actual y acción recomendada con ejemplo
    - Estimación de puntos SEO y GEO ganados
    - Esfuerzo estimado: quick (<1h), medium (1-4h), involved (>4h)

    Los resultados se cachean en base de datos para evitar llamadas repetidas.
    """
    cached = await get_cached_improvements(analysis_id)
    if cached:
        return ImprovementsOutput(analysis_id=analysis_id, **cached)

    row = await get_analysis(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")

    result = row["result"]
    input_data = row["input_data"]
    type_ = row["type"]

    prompt_parts = [f"Tipo de análisis: {type_}"]
    if type_ == "url":
        prompt_parts.append(f"URL analizada: {input_data.get('url', '')}")
    elif type_ == "text":
        text_preview = (input_data.get("text", "")[:400] + "…") if len(input_data.get("text", "")) > 400 else input_data.get("text", "")
        prompt_parts.append(f"Texto analizado (extracto):\n{text_preview}")
    else:
        prompt_parts.append(f"Keyword semilla: {input_data.get('text', '')}")

    if type_ != "keywords":
        seo = result.get("seo", {})
        geo = result.get("geo", {})
        prompt_parts.append(f"""
Scores actuales: SEO={seo.get('seo_score', '?')}/100, GEO={geo.get('geo_score', '?')}/100

SEO — Issues detectados: {seo.get('issues', [])}
SEO — Sugerencias actuales: {seo.get('suggestions', [])}
SEO — Title actual: "{seo.get('title', '')}"
SEO — Meta actual: "{seo.get('meta_description', '')}"
SEO — Focus keyword: "{seo.get('focus_keyword', '')}"
SEO — Legibilidad: {seo.get('readability_score', '')}

GEO — AI Snippet: "{geo.get('ai_snippet', '')}"
GEO — Citation likelihood: {geo.get('citation_likelihood', '')}
GEO — Issues GEO: {geo.get('ai_friendliness_issues', [])}
GEO — Entidades faltantes: {geo.get('missing_entities', [])}
GEO — Sugerencias GEO: {geo.get('geo_suggestions', [])}
""")
    else:
        prompt_parts.append(f"""
Keywords generadas: {[k.get('keyword') for k in result.get('keywords', [])[:10]]}
Oportunidades de contenido: {result.get('content_gap_opportunities', [])}
Keywords GEO-first: {result.get('geo_first_keywords', [])}
""")

    raw = await generate(IMPROVEMENTS_SYSTEM, "\n".join(prompt_parts))

    parsed = _parse_json(raw, ImprovementsOutput)
    parsed.analysis_id = analysis_id

    improvements_dict = {
        "improvements": [i.model_dump() for i in parsed.improvements],
        "total_potential_seo_gain": parsed.total_potential_seo_gain,
        "total_potential_geo_gain": parsed.total_potential_geo_gain,
    }
    await save_improvements(analysis_id, improvements_dict)

    return parsed


_BLOCK_SYSTEM = """Eres un experto en SEO y GEO. Generas bloques de contenido específicos para mejorar páginas web.
El contenido debe ser:
- Optimizado para búsqueda (keywords naturales, sin forzar)
- Fácil de citar por IA generativa (respuestas directas, datos concretos, entidades nombradas)
- Natural y fluido, no robótico
Devuelve SOLO el contenido del bloque, sin explicaciones ni marcadores de cabecera (##)."""


@app.post(
    "/v2/generate-block",
    response_model=GenerateBlockOutput,
    tags=["V2"],
    summary="Genera contenido específico para una mejora con IA",
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
@limiter.limit(get_limit)
async def v2_generate_block(
    request: Request,
    body: GenerateBlockBody | None = None,
    _key: str = Depends(verify_key),
):
    """
    Genera el texto exacto de un bloque de contenido para aplicar una mejora concreta.

    - **paragraph / section** — párrafo o sección nueva (150-400 palabras)
    - **answer** — respuesta directa citeable por IA (2-4 frases, ≤280 chars)
    - **faq** — preguntas frecuentes en formato «Pregunta 1 · Pregunta 2 · Pregunta 3»
    """
    if not body or not body.instruction:
        raise HTTPException(status_code=422, detail="Se requiere 'instruction'.")

    block_guides = {
        "answer": "Escribe un párrafo de 2-4 frases directas y factuales (<280 chars). Debe responder la pregunta inmediatamente.",
        "faq":    "Escribe 3-5 preguntas frecuentes separadas por ' · '. Solo las preguntas, sin respuestas.",
        "section":"Escribe una sección completa de 200-400 palabras con entidades nombradas y datos concretos.",
        "paragraph": "Escribe un párrafo de 100-200 palabras fluido y optimizado para búsqueda.",
    }
    guide = block_guides.get(body.block_type or "paragraph", block_guides["paragraph"])

    ctx = (body.original_text or "")[:3000]
    prompt = f"""Contenido original de la página:
---
{ctx if ctx else "(sin contexto)"}
---

Mejora a aplicar:
{body.instruction}

Tipo de bloque: {body.block_type or "paragraph"}
Idioma: {body.language or "es"}

{guide}
No incluyas marcadores markdown de cabecera. Solo el texto del bloque."""

    raw = await generate(_BLOCK_SYSTEM, prompt)
    return GenerateBlockOutput(generated_text=raw.strip())


# ── Dev server ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.index:app", host="0.0.0.0", port=8000, reload=True)
