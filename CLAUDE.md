# SEO & GEO API — Contexto para Claude Code

## Qué es este proyecto
API REST para optimización SEO clásica + GEO (Generative Engine Optimization: aparecer en respuestas de ChatGPT, Gemini, Perplexity). Monetización vía RapidAPI y otros marketplaces de APIs.

**Stack:** FastAPI · google-genai ≥2.7 · slowapi · httpx · BeautifulSoup4 · Pydantic v2 · Vercel

## Estructura
```
seo-geo-api/
├── api/
│   └── index.py        # Entrypoint FastAPI + todos los endpoints
├── core/
│   ├── auth.py         # Auth dual: x-api-key propio + RapidAPI proxy secret
│   ├── llm.py          # Cliente Gemini async (ThreadPoolExecutor)
│   ├── models.py       # Schemas Pydantic request/response
│   ├── prompts.py      # System prompts centralizados
│   ├── rate_limit.py   # slowapi: Free=10/day, Pro=500/day
│   └── scraper.py      # httpx + BS4 para /analyze/url
├── tests/
│   └── test_api.py     # 10 tests pytest-asyncio, todos pasando
├── .env                # GEMINI_API_KEY, ENVIRONMENT, API_KEYS (no subir a git)
├── .env.example
├── requirements.txt
└── vercel.json
```

## Endpoints (v1.1.0)
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Health check público |
| POST | `/analyze/seo` | Title, meta, slug, keywords LSI, OG, schema.org, score SEO |
| POST | `/analyze/geo` | Score GEO, snippet para IA, entidades, citation_likelihood |
| POST | `/analyze/full` | SEO + GEO en paralelo (una sola llamada) |
| POST | `/analyze/url` | Scraping automático de URL + análisis full |
| POST | `/keywords` | Keyword research con intención + potencial GEO |
| POST | `/schema` | Generador JSON-LD / schema.org listo para `<head>` |

## Decisiones técnicas importantes
- **SDK Gemini:** usa `google-genai` (nuevo). El antiguo `google-generativeai` está deprecado.
- **Async real:** `_call_gemini_sync` corre en `ThreadPoolExecutor` via `run_in_executor`. El SDK es síncrono en su core.
- **Rate limiting:** `slowapi` con callable dinámico `get_limit(key: str)` — recibe la API key y devuelve el límite del plan. `_key_func(request)` debe tener `request` en su firma para que slowapi la use correctamente.
- **Auth en dev:** `ENVIRONMENT=dev` bypasea toda autenticación. En prod requiere `x-api-key` o `X-RapidAPI-Proxy-Secret`.
- **Scraper:** extrae `<main>` o `<article>`, trunca a 8000 chars, maneja timeouts y content-type no-HTML.

## Cómo correr localmente
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Copia .env.example a .env y añade tu GEMINI_API_KEY
ENVIRONMENT=dev uvicorn api.index:app --reload
# Swagger: http://localhost:8000/docs
```

## Tests
```bash
pytest tests/ -v -p no:cacheprovider
# 10/10 deben pasar. Usan mocks de Gemini, no necesitan GEMINI_API_KEY real.
```

## Variables de entorno
| Variable | Descripción | Obligatoria |
|----------|-------------|-------------|
| `GEMINI_API_KEY` | Google AI Studio (aistudio.google.com) | ✅ |
| `ENVIRONMENT` | `dev` (sin auth) \| `prod` | ✅ |
| `API_KEYS` | Keys propias separadas por comas | En prod |
| `RAPIDAPI_PROXY_SECRET` | Del dashboard de RapidAPI | Para RapidAPI |
| `PRO_KEYS` | Keys con límite Pro (500 req/día) | Opcional |
| `LLM_WORKERS` | Threads para llamadas a Gemini (default: 10) | Opcional |

## Roadmap pendiente
- [ ] Cache con Vercel KV (Redis) para respuestas repetidas
- [ ] Rate limiting persistente (actualmente en memoria, se resetea en cada deploy)
- [ ] MCP server wrapper para agentes de IA
- [ ] Chrome Extension que consume la API
- [ ] Publicación en RapidAPI con plan Free/Pro

## Deploy en Vercel
```bash
npm i -g vercel && vercel login
vercel
# En Vercel Dashboard → Settings → Environment Variables: añadir las de arriba
vercel --prod
```
