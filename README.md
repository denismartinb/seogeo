# SEO & GEO API

Optimización de contenido para buscadores tradicionales **y** motores de IA generativa (ChatGPT, Gemini, Perplexity).

Construida con FastAPI + Gemini 2.5 Flash. Desplegable en Vercel gratis en menos de 5 minutos.

---

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Health check (sin auth) |
| POST | `/analyze/seo` | Metadata SEO completa |
| POST | `/analyze/geo` | Análisis GEO para LLMs |
| POST | `/analyze/full` | SEO + GEO combinado |
| POST | `/keywords` | Keyword research + potencial GEO |
| POST | `/schema` | Generador JSON-LD / schema.org |

Documentación interactiva disponible en `/docs` (Swagger) y `/redoc`.

---

## Quickstart local

```bash
# 1. Clona y entra
git clone https://github.com/TU_USUARIO/seo-geo-api.git
cd seo-geo-api

# 2. Entorno virtual
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Dependencias
pip install -r requirements.txt

# 4. Variables de entorno
cp .env.example .env
# Edita .env y añade tu GEMINI_API_KEY

# 5. Arranca (con ENVIRONMENT=dev no necesitas API key propia)
ENVIRONMENT=dev uvicorn api.index:app --reload

# 6. Abre http://localhost:8000/docs
```

---

## Uso de la API

### Autenticación

Incluye tu API key en el header `x-api-key`:

```bash
curl -X POST https://tu-api.vercel.app/analyze/seo \
  -H "Content-Type: application/json" \
  -H "x-api-key: tu_clave" \
  -d '{
    "text": "Guía completa sobre marketing digital en 2025...",
    "language": "es",
    "target_keyword": "marketing digital"
  }'
```

### Ejemplo: análisis GEO

```bash
curl -X POST https://tu-api.vercel.app/analyze/geo \
  -H "Content-Type: application/json" \
  -H "x-api-key: tu_clave" \
  -d '{
    "text": "El SEO semántico consiste en...",
    "url": "https://tuweb.com/seo-semantico",
    "language": "es"
  }'
```

**Respuesta:**
```json
{
  "geo_score": 72,
  "ai_snippet": "El SEO semántico optimiza el contenido para que los motores de búsqueda comprendan el significado...",
  "answer_ready_summary": "...",
  "entity_coverage": ["SEO", "Google", "búsqueda semántica"],
  "missing_entities": ["E-E-A-T", "schema.org", "Knowledge Graph"],
  "citation_likelihood": "media",
  "structured_data_recommended": ["Article", "FAQPage"],
  "ai_friendliness_issues": ["Falta definición directa en primer párrafo"],
  "geo_suggestions": ["Añadir pregunta-respuesta directa al inicio"],
  "llm_query_matches": ["¿Qué es el SEO semántico?", "Cómo optimizar para búsqueda semántica"]
}
```

---

## Despliegue en Vercel

### Opción A — Un clic (recomendado)

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/TU_USUARIO/seo-geo-api)

### Opción B — Manual

```bash
# 1. Instala Vercel CLI
npm i -g vercel

# 2. Login
vercel login

# 3. Despliega (primera vez)
vercel

# 4. Añade variables de entorno en Vercel Dashboard:
#    Settings → Environment Variables
#    - GEMINI_API_KEY
#    - ENVIRONMENT = prod
#    - API_KEYS = clave1,clave2
#    - RAPIDAPI_PROXY_SECRET (lo obtienes en RapidAPI después)

# 5. Re-despliega con las variables
vercel --prod
```

---

## Publicación en RapidAPI

1. Crea cuenta en [rapidapi.com](https://rapidapi.com) → "Add New API"
2. En **General**:
   - Name: `SEO & GEO API`
   - Category: `Data / Text Analysis`
3. En **Endpoints**: añade cada ruta (`/analyze/seo`, `/analyze/geo`, etc.)
4. En **Security**:
   - Activa `Proxy Secret`
   - Copia el secret y pégalo en tu variable `RAPIDAPI_PROXY_SECRET` en Vercel
5. En **Pricing**: crea un plan Free (10 req/día) y un plan Pro ($9.99/mes, 500 req)
6. Publica → tu API aparece en el marketplace

**Tip:** En la descripción de cada endpoint en RapidAPI, menciona el ángulo GEO explícitamente — es el diferencial que otros no tienen.

---

## Estructura del proyecto

```
seo-geo-api/
├── api/
│   └── index.py          # Entrypoint FastAPI (Vercel lo detecta aquí)
├── core/
│   ├── auth.py           # Autenticación (API key + RapidAPI proxy secret)
│   ├── llm.py            # Cliente Gemini con fallback automático
│   ├── models.py         # Schemas Pydantic (request/response)
│   └── prompts.py        # System prompts centralizados
├── .env.example          # Variables de entorno de ejemplo
├── .gitignore
├── requirements.txt
├── vercel.json           # Configuración de despliegue
└── README.md
```

---

## Variables de entorno

| Variable | Descripción | Obligatoria |
|----------|-------------|-------------|
| `GEMINI_API_KEY` | API key de Google AI Studio | ✅ |
| `ENVIRONMENT` | `dev` (sin auth) o `prod` | ✅ |
| `API_KEYS` | Keys propias separadas por comas | En prod |
| `RAPIDAPI_PROXY_SECRET` | Secret de RapidAPI (en su dashboard) | Para RapidAPI |

---

## Roadmap

- [ ] Endpoint `/analyze/url` — scraping + análisis automático desde URL
- [ ] Rate limiting por API key
- [ ] Cache de resultados (Redis / Vercel KV)
- [ ] MCP server wrapper para agentes de IA
- [ ] Chrome Extension que llama a esta API

---

## Licencia

MIT
