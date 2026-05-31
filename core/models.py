"""
core/models.py — Schemas de entrada/salida de todos los endpoints.
"""
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


# ── Inputs ───────────────────────────────────────────────────────────────────

class TextInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000, description="Texto o contenido a analizar")
    url: Optional[str] = Field(None, description="URL de origen (opcional, mejora el contexto)")
    language: Optional[str] = Field("es", description="Idioma objetivo: es, en, fr, de, pt...")
    target_keyword: Optional[str] = Field(None, description="Keyword principal a optimizar")


class UrlInput(BaseModel):
    url: str = Field(..., description="URL completa a analizar (https://...)")
    language: Optional[str] = Field("es", description="Idioma objetivo")
    target_keyword: Optional[str] = Field(None, description="Keyword principal")


# Modelos permisivos para recibir body de RapidAPI (todos los campos opcionales,
# sin validación estricta — _merge_text_input/_merge_url_input hacen la validación real)
class TextInputBody(BaseModel):
    text: Optional[str] = Field(None, description="Texto o contenido a analizar")
    content: Optional[str] = Field(None, description="Alias de 'text' (retrocompatibilidad)")
    url: Optional[str] = Field(None, description="URL de origen (opcional)")
    language: Optional[str] = Field(None, description="Idioma objetivo: es, en, fr, de, pt...")
    target_keyword: Optional[str] = Field(None, description="Keyword principal a optimizar")


class UrlInputBody(BaseModel):
    url: Optional[str] = Field(None, description="URL completa a analizar (https://...)")
    language: Optional[str] = Field(None, description="Idioma objetivo")
    target_keyword: Optional[str] = Field(None, description="Keyword principal")


# ── SEO Outputs ───────────────────────────────────────────────────────────────

class SeoMetadata(BaseModel):
    title: str = Field(..., description="Title tag optimizado (<60 chars)")
    meta_description: str = Field(..., description="Meta description (<160 chars)")
    slug: str = Field(..., description="URL slug limpio")
    focus_keyword: str = Field(..., description="Keyword principal detectada o sugerida")
    secondary_keywords: list[str] = Field(..., description="Keywords secundarias (LSI)")
    schema_faq: Optional[list[dict]] = Field(None, description="FAQ schema.org si aplica")
    schema_article: Optional[dict] = Field(None, description="Article schema.org")
    og_title: str = Field(..., description="Open Graph title")
    og_description: str = Field(..., description="Open Graph description")
    readability_score: str = Field(..., description="Legibilidad estimada: básico | medio | avanzado")
    seo_score: int = Field(..., ge=0, le=100, description="Puntuación SEO estimada 0-100")
    issues: list[str] = Field(..., description="Problemas SEO detectados")
    suggestions: list[str] = Field(..., description="Mejoras recomendadas")


# ── GEO Outputs ───────────────────────────────────────────────────────────────

class GeoAnalysis(BaseModel):
    geo_score: int = Field(..., ge=0, le=100, description="Puntuación GEO 0-100")
    ai_snippet: str = Field(..., description="Snippet optimizado para respuestas de IA (<280 chars)")
    answer_ready_summary: str = Field(..., description="Resumen estructurado listo para ser citado por IA")
    entity_coverage: list[str] = Field(..., description="Entidades nombradas detectadas (personas, lugares, marcas)")
    missing_entities: list[str] = Field(..., description="Entidades que debería mencionar para más autoridad")
    citation_likelihood: str = Field(..., description="Probabilidad de ser citado: baja | media | alta")
    structured_data_recommended: list[str] = Field(..., description="Tipos de schema.org recomendados para GEO")
    ai_friendliness_issues: list[str] = Field(..., description="Problemas que reducen visibilidad en IA")
    geo_suggestions: list[str] = Field(..., description="Acciones concretas para mejorar GEO")
    llm_query_matches: list[str] = Field(..., description="Preguntas de usuario que este contenido podría responder en ChatGPT/Gemini/Perplexity")


# ── Combined Output ───────────────────────────────────────────────────────────

class FullAnalysis(BaseModel):
    seo: SeoMetadata
    geo: GeoAnalysis


# ── Keyword Research ──────────────────────────────────────────────────────────

class KeywordIdea(BaseModel):
    keyword: str
    intent: str = Field(..., description="informacional | navegacional | transaccional | comercial")
    difficulty: str = Field(..., description="baja | media | alta")
    geo_potential: str = Field(..., description="Potencial de aparecer en respuestas de IA: bajo | medio | alto")
    content_angle: str = Field(..., description="Ángulo de contenido recomendado")


class KeywordResearchOutput(BaseModel):
    seed_keyword: str
    language: str
    keywords: list[KeywordIdea]
    content_gap_opportunities: list[str]
    geo_first_keywords: list[str] = Field(..., description="Keywords donde GEO > SEO tradicional")


# ── Schema Generator ──────────────────────────────────────────────────────────

class SchemaOutput(BaseModel):
    schema_type: str
    json_ld: dict = Field(..., description="JSON-LD listo para insertar en <head>")
    implementation_tip: str


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
