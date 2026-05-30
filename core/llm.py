"""
core/llm.py — Cliente Gemini centralizado con fallback y ejecución async real.

Usa el nuevo SDK google-genai (el antiguo google-generativeai está deprecado).
El SDK sigue siendo síncrono en su core, así que cada llamada se delega a un
ThreadPoolExecutor via asyncio.run_in_executor para no bloquear el event loop.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from google import genai
from google.genai import types

# ── Configuración ────────────────────────────────────────────────────────────

GEMINI_MODEL = "gemini-2.5-flash"           # modelo principal
GEMINI_MODEL_FALLBACK = "gemini-1.5-flash"  # fallback con límites más altos

# Pool compartido para todas las llamadas síncronas al SDK
_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("LLM_WORKERS", "10")))


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    """Cliente Gemini cacheado (una instancia por proceso)."""
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))


def _call_gemini_sync(model_name: str, prompt: str, json_mode: bool) -> str:
    """Llamada síncrona a Gemini — se ejecuta en el ThreadPoolExecutor."""
    client = _get_client()
    config = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )
    return response.text


# ── API pública ───────────────────────────────────────────────────────────────

async def generate(system_prompt: str, user_prompt: str, json_mode: bool = True) -> str:
    """
    Llama a Gemini de forma no bloqueante.
    Intenta con el modelo principal; si falla por rate limit, usa el fallback.
    """
    prompt = system_prompt + "\n\n" + user_prompt
    loop = asyncio.get_event_loop()

    for model_name in [GEMINI_MODEL, GEMINI_MODEL_FALLBACK]:
        try:
            return await loop.run_in_executor(
                _executor,
                _call_gemini_sync,
                model_name,
                prompt,
                json_mode,
            )
        except Exception as e:
            err = str(e).lower()
            if "quota" in err or "429" in err or "rate" in err:
                continue
            raise

    raise RuntimeError("Gemini rate limit alcanzado en todos los modelos. Inténtalo en unos minutos.")
