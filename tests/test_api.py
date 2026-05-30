"""
tests/test_api.py — Tests de integración para todos los endpoints.

Usa mocks para Gemini (no hace llamadas reales).
Ejecutar: pytest tests/ -v
"""
import json
import pytest
from unittest.mock import AsyncMock, patch

# ── Fixtures de respuestas mock ───────────────────────────────────────────────

SEO_MOCK = {
    "title": "Guía SEO 2025",
    "meta_description": "Aprende SEO moderno en 2025 con esta guía completa.",
    "slug": "guia-seo-2025",
    "focus_keyword": "SEO 2025",
    "secondary_keywords": ["posicionamiento web", "Google ranking"],
    "schema_faq": None,
    "schema_article": {"@type": "Article", "headline": "Guía SEO 2025"},
    "og_title": "Guía SEO 2025",
    "og_description": "Aprende SEO moderno.",
    "readability_score": "medio",
    "seo_score": 78,
    "issues": ["Falta H1"],
    "suggestions": ["Añadir H1 con keyword principal"],
}

GEO_MOCK = {
    "geo_score": 65,
    "ai_snippet": "El SEO en 2025 se centra en intención de búsqueda y GEO.",
    "answer_ready_summary": "El SEO moderno combina optimización técnica con GEO.",
    "entity_coverage": ["Google", "SEO"],
    "missing_entities": ["E-E-A-T", "schema.org"],
    "citation_likelihood": "media",
    "structured_data_recommended": ["Article", "FAQPage"],
    "ai_friendliness_issues": ["Sin definición directa al inicio"],
    "geo_suggestions": ["Añadir párrafo definitorio al inicio"],
    "llm_query_matches": ["¿Qué es SEO en 2025?"],
}

KEYWORD_MOCK = {
    "seed_keyword": "marketing digital",
    "language": "es",
    "keywords": [
        {
            "keyword": "marketing digital 2025",
            "intent": "informacional",
            "difficulty": "media",
            "geo_potential": "alto",
            "content_angle": "Guía actualizada de tendencias",
        }
    ],
    "content_gap_opportunities": ["Marketing automation con IA"],
    "geo_first_keywords": ["qué es el marketing digital"],
}

SCHEMA_MOCK = {
    "schema_type": "Article",
    "json_ld": {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": "Guía SEO 2025",
    },
    "implementation_tip": "Insertar en <head> dentro de <script type='application/ld+json'>",
}

SAMPLE_TEXT = "El SEO en 2025 es fundamental para cualquier estrategia digital. " * 5


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── Auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_required_in_prod(client, monkeypatch):
    """En prod, sin API key debe devolver 401."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("API_KEYS", "valid-key-123")
    # Re-importar para que tome el nuevo env
    import importlib, core.auth
    importlib.reload(core.auth)

    r = await client.post("/analyze/seo", json={"text": SAMPLE_TEXT})
    assert r.status_code == 401


# ── SEO ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_seo(client):
    with patch("api.index.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = json.dumps(SEO_MOCK)
        r = await client.post("/analyze/seo", json={"text": SAMPLE_TEXT})

    assert r.status_code == 200
    data = r.json()
    assert data["seo_score"] == 78
    assert data["slug"] == "guia-seo-2025"


@pytest.mark.asyncio
async def test_analyze_seo_invalid_input(client):
    """Texto demasiado corto debe dar 422."""
    r = await client.post("/analyze/seo", json={"text": "corto"})
    assert r.status_code == 422


# ── GEO ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_geo(client):
    with patch("api.index.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = json.dumps(GEO_MOCK)
        r = await client.post("/analyze/geo", json={"text": SAMPLE_TEXT})

    assert r.status_code == 200
    data = r.json()
    assert data["geo_score"] == 65
    assert data["citation_likelihood"] == "media"


# ── FULL ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_full(client):
    with patch("api.index.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.side_effect = [json.dumps(SEO_MOCK), json.dumps(GEO_MOCK)]
        r = await client.post("/analyze/full", json={"text": SAMPLE_TEXT})

    assert r.status_code == 200
    data = r.json()
    assert "seo" in data and "geo" in data
    assert data["seo"]["seo_score"] == 78
    assert data["geo"]["geo_score"] == 65


# ── URL ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_url(client):
    with (
        patch("api.index.fetch_url_text", new_callable=AsyncMock) as mock_fetch,
        patch("api.index.generate", new_callable=AsyncMock) as mock_gen,
    ):
        mock_fetch.return_value = SAMPLE_TEXT
        mock_gen.side_effect = [json.dumps(SEO_MOCK), json.dumps(GEO_MOCK)]
        r = await client.post(
            "/analyze/url",
            json={"url": "https://example.com", "language": "es"},
        )

    assert r.status_code == 200
    data = r.json()
    assert "seo" in data and "geo" in data


# ── KEYWORDS ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keywords(client):
    with patch("api.index.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = json.dumps(KEYWORD_MOCK)
        r = await client.post("/keywords", json={"text": "marketing digital"})

    assert r.status_code == 200
    data = r.json()
    assert len(data["keywords"]) >= 1
    assert data["seed_keyword"] == "marketing digital"


# ── SCHEMA ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schema(client):
    with patch("api.index.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = json.dumps(SCHEMA_MOCK)
        r = await client.post("/schema", json={"text": SAMPLE_TEXT})

    assert r.status_code == 200
    data = r.json()
    assert data["schema_type"] == "Article"
    assert "@type" in data["json_ld"]


# ── LLM error handling ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bad_llm_response_returns_502(client):
    """Si el LLM devuelve basura, debe dar 502."""
    with patch("api.index.generate", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = "esto no es json"
        r = await client.post("/analyze/seo", json={"text": SAMPLE_TEXT})

    assert r.status_code == 502
