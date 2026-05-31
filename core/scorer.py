"""
core/scorer.py — Motor de scoring SEO + GEO determinista.

Calcula scores a partir de señales objetivas extraídas del contenido y
los metadatos estructurales de la página. El score es siempre el mismo
para el mismo contenido — no interviene ningún modelo de lenguaje.

Luego el LLM recibe estos scores precalculados y se limita a generar
los campos cualitativos (title, meta, sugerencias, snippet, etc.).
"""
from __future__ import annotations

import re
from typing import Optional


# ── Helpers ───────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _contains_keyword(text: str, kw: str) -> bool:
    if not kw:
        return False
    return kw.lower() in text.lower()


def _keyword_density(text: str, kw: str) -> float:
    """Returns keyword frequency as percentage of total words."""
    if not kw or not text:
        return 0.0
    words = text.lower().split()
    kw_words = kw.lower().split()
    n = len(kw_words)
    if n == 0 or len(words) == 0:
        return 0.0
    matches = sum(
        1 for i in range(len(words) - n + 1)
        if words[i : i + n] == kw_words
    )
    return (matches / len(words)) * 100


def _has_faq_markers(text: str) -> bool:
    markers = [
        "faq", "preguntas frecuentes", "frequently asked",
        "¿qué", "¿cómo", "¿cuál", "¿por qué", "¿cuándo",
        "q:", "question:", "p:",
    ]
    t = text.lower()
    return any(m in t for m in markers)


def _has_list_markers(text: str) -> bool:
    return bool(re.search(r"(^|\n)(\s*[-•*]|\s*\d+\.) ", text))


def _count_proper_nouns(text: str) -> int:
    """Approximates named entities via capitalized word sequences."""
    # Match sequences of capitalized words (excluding sentence starts after '.')
    matches = re.findall(
        r"(?<!\.\s)(?<![.!?]\s)\b([A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)*)\b",
        text,
    )
    return len(set(matches))


def _count_numbers_and_stats(text: str) -> int:
    """Counts numeric data points (numbers, percentages, currencies)."""
    return len(re.findall(
        r"\b\d+(?:[.,]\d+)?(?:\s*(?:%|€|\$|USD|EUR|pts?|km|m²|mil|millones?))?\b",
        text,
    ))


def _count_years(text: str) -> int:
    return len(re.findall(r"\b(19|20)\d{2}\b", text))


def _has_authority_signals(text: str) -> bool:
    signals = [
        "según", "estudio de", "investigación de", "publicado en",
        "doctor", "dr.", "experto", "ceo", "fundador", "profesor",
        "years experience", "años de experiencia", "fuente:", "referencia",
        "according to", "research by",
    ]
    t = text.lower()
    return sum(1 for s in signals if s in t) >= 2


def _has_source_links(text: str) -> bool:
    return bool(re.search(r"https?://|www\.", text))


# ── SEO Scorer ─────────────────────────────────────────────────────────────────

def score_seo(
    text: str,
    metadata: dict,
    target_keyword: Optional[str] = None,
) -> dict:
    """
    Deterministic SEO scoring based on objective content signals.
    Returns: {seo_score, score_breakdown, word_count, signals}
    """
    kw = (target_keyword or "").strip().lower()
    h1s = metadata.get("h1", [])
    visible_h1 = [h for h in h1s if not h.get("hidden")]
    title = metadata.get("title", "") or ""
    meta_desc = metadata.get("meta_description", "") or ""
    h2s = metadata.get("h2", []) or []
    has_schema = metadata.get("has_schema", False)

    # ── [A] Título / H1 — 15 pts ──────────────────────────────────────────────
    a1 = 5 if visible_h1 else 0          # H1 visible existe
    a2 = 4 if 45 <= len(title) <= 65 else (2 if 35 <= len(title) <= 80 else 0)  # longitud
    a3_text = visible_h1[0]["text"] if visible_h1 else title
    a3 = 6 if kw and _contains_keyword(a3_text, kw) else 0
    title_h1 = a1 + a2 + a3

    # ── [B] Meta description — 10 pts ─────────────────────────────────────────
    b1 = 4 if meta_desc else 0
    b2 = 3 if 130 <= len(meta_desc) <= 165 else (1 if 80 <= len(meta_desc) <= 200 else 0)
    b3 = 3 if kw and _contains_keyword(meta_desc, kw) else 0
    meta_description = b1 + b2 + b3

    # ── [C] Estructura de contenido — 15 pts ──────────────────────────────────
    c1 = min(6, len(h2s) * 2)            # H2s (0→0, 1→2, 2→4, 3+→6)
    paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 40]
    c2 = 3 if len(paragraphs) >= 4 else (1 if len(paragraphs) >= 2 else 0)
    c3 = 3 if _has_list_markers(text) else 0
    c4 = 3 if paragraphs and len(paragraphs[0]) <= 400 else 0  # intro no genérica larga
    content_structure = c1 + c2 + c3 + c4

    # ── [D] Extensión y calidad — 20 pts ──────────────────────────────────────
    wc = _word_count(text)
    if wc >= 1500:   d1 = 17
    elif wc >= 1000: d1 = 15
    elif wc >= 600:  d1 = 10
    elif wc >= 300:  d1 = 5
    else:            d1 = 0

    # Legibilidad: avg sentence length
    sents = [s.strip() for s in re.split(r"[.!?]", text) if len(s.strip()) > 5]
    avg_sent = sum(len(s.split()) for s in sents) / max(len(sents), 1)
    d2 = 3 if avg_sent <= 18 else (1 if avg_sent <= 28 else 0)
    content_quality = d1 + d2

    # ── [E] Keywords — 20 pts ─────────────────────────────────────────────────
    if kw:
        first_words = " ".join(text.split()[:100]).lower()
        e1 = 5 if kw in first_words else 0

        density = _keyword_density(text, kw)
        e2 = 5 if 0.7 <= density <= 2.8 else (2 if 0.4 <= density <= 4.0 else 0)

        # LSI/semantic: related words present (simplified)
        kw_parts = kw.split()
        text_lower = text.lower()
        e3 = 5 if any(part in text_lower for part in kw_parts if len(part) > 3) else 2

        # Keyword in suggested slug (can't determine without seeing slug, give partial)
        e4 = 5 if kw and any(_contains_keyword(h["text"], kw) for h in visible_h1) else 2
        keywords = e1 + e2 + e3 + e4
    else:
        # No target keyword provided — give partial credit
        keywords = 10

    # ── [F] Schema y técnico — 20 pts ─────────────────────────────────────────
    f1 = 10 if has_schema else 0
    f2 = 5 if metadata.get("canonical") else 2   # canonical present
    f3 = min(5, 5 if _has_authority_signals(text) else 0)
    technical = f1 + f2 + f3

    # ── Total ──────────────────────────────────────────────────────────────────
    total = title_h1 + meta_description + content_structure + content_quality + keywords + technical

    return {
        "seo_score": min(100, max(0, total)),
        "score_breakdown": {
            "title_h1": title_h1,
            "meta_description": meta_description,
            "content_structure": content_structure,
            "content_quality": content_quality,
            "keywords": keywords,
            "technical": technical,
        },
        "word_count": wc,
    }


# ── GEO Scorer ─────────────────────────────────────────────────────────────────

def score_geo(
    text: str,
    metadata: dict,
) -> dict:
    """
    Deterministic GEO scoring based on signals that LLMs use to decide
    whether to cite content (answer format, facts, entities, structure...).
    Returns: {geo_score, score_breakdown, signals}
    """
    has_schema = metadata.get("has_schema", False)
    schema_count = metadata.get("schema_count", 0)
    h2s = metadata.get("h2", []) or []
    text_lower = text.lower()

    # ── [A] Respuesta directa — 20 pts ────────────────────────────────────────
    first_500 = text[:500]
    question_starters = [
        "qué es", "qué son", "cómo", "por qué", "cuál es", "cuándo",
        "what is", "how to", "why", "which is",
    ]
    a1 = 8 if any(q in first_500.lower() for q in question_starters) else 3
    # Extractable snippet: first paragraph short enough to be a snippet
    first_para = next((p.strip() for p in text.split("\n") if len(p.strip()) > 60), "")
    a2 = 10 if 80 <= len(first_para) <= 300 else (5 if len(first_para) <= 500 else 2)
    direct_answer = a1 + a2

    # ── [B] Densidad factual — 20 pts ─────────────────────────────────────────
    numbers = _count_numbers_and_stats(text)
    years = _count_years(text)
    b1 = min(10, numbers * 2)            # 5+ datos = 10 pts

    study_signals = ["estudio", "investigación", "según", "publicado", "research",
                     "dato", "cifra", "porcentaje", "informe de", "report"]
    b2_base = sum(1 for s in study_signals if s in text_lower)
    b2 = min(10, b2_base * 2 + years)   # fuentes + años = autoridad factual
    factual_density = min(20, b1 + b2)

    # ── [C] Cobertura de entidades — 20 pts ───────────────────────────────────
    unique_proper = _count_proper_nouns(text)
    if unique_proper >= 10:   c1 = 20
    elif unique_proper >= 6:  c1 = 15
    elif unique_proper >= 3:  c1 = 10
    elif unique_proper >= 1:  c1 = 5
    else:                     c1 = 0
    entity_coverage = c1

    # ── [D] Estructura para IA — 20 pts ───────────────────────────────────────
    d1 = 8 if _has_faq_markers(text) else 0
    d2 = 7 if _has_list_markers(text) else 0
    d3 = 5 if len(h2s) >= 2 else (2 if len(h2s) == 1 else 0)
    ai_structure = d1 + d2 + d3

    # ── [E] Autoridad E-E-A-T — 10 pts ───────────────────────────────────────
    e1 = 5 if _has_authority_signals(text) else (2 if _has_source_links(text) else 0)
    e2 = 5 if _has_source_links(text) else 0
    authority = min(10, e1 + e2)

    # ── [F] Schema para IA — 10 pts ───────────────────────────────────────────
    f1 = 6 if has_schema else 0
    f2 = min(4, (schema_count - 1) * 2) if schema_count > 1 else 0
    structured_data = f1 + f2

    # ── Total ──────────────────────────────────────────────────────────────────
    total = direct_answer + factual_density + entity_coverage + ai_structure + authority + structured_data

    # Citation likelihood from score
    if total >= 65:   citation = "alta"
    elif total >= 40: citation = "media"
    else:             citation = "baja"

    return {
        "geo_score": min(100, max(0, total)),
        "score_breakdown": {
            "direct_answer": direct_answer,
            "factual_density": factual_density,
            "entity_coverage": entity_coverage,
            "ai_structure": ai_structure,
            "authority": authority,
            "structured_data": structured_data,
        },
        "citation_likelihood_computed": citation,
    }


# ── Combined ───────────────────────────────────────────────────────────────────

def score_content(
    text: str,
    metadata: Optional[dict] = None,
    target_keyword: Optional[str] = None,
) -> dict:
    """
    Runs both scorers and returns combined results.
    metadata can be empty dict for text-only analysis.
    """
    md = metadata or {}
    seo = score_seo(text, md, target_keyword)
    geo = score_geo(text, md)
    return {"seo": seo, "geo": geo}
