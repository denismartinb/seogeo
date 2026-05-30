"""
core/rate_limit.py — Rate limiting por API key con slowapi.

Planes:
  FREE  → 10 requests / day   (por defecto)
  PRO   → 500 requests / day  (si la key está en PRO_KEYS)

Variables de entorno:
  RATE_LIMIT_FREE   — límite plan Free  (default: "10/day")
  RATE_LIMIT_PRO    — límite plan Pro   (default: "500/day")
  PRO_KEYS          — API keys Pro separadas por comas
"""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

# Keys Pro (vacío en dev → todos son Free)
_PRO_KEYS: set[str] = {
    k.strip() for k in os.environ.get("PRO_KEYS", "").split(",") if k.strip()
}

RATE_FREE = os.environ.get("RATE_LIMIT_FREE", "10/day")
RATE_PRO = os.environ.get("RATE_LIMIT_PRO", "500/day")


def _key_func(request: Request) -> str:
    """
    Clave de rate limiting: usa la API key si está presente,
    o la IP como fallback (para el health check y rutas públicas).
    """
    key = request.headers.get("x-api-key") or get_remote_address(request)
    return key or "anonymous"


def _dynamic_limit(key: str) -> str:
    """Devuelve el límite correspondiente al plan de la API key (por clave)."""
    return RATE_PRO if key in _PRO_KEYS else RATE_FREE


limiter = Limiter(key_func=_key_func, default_limits=[RATE_FREE])


# Límite dinámico por plan: slowapi lo llama con la clave devuelta por key_func
def get_limit(key: str = "") -> str:
    """Callable para @limiter.limit() — recibe la key y devuelve el límite del plan."""
    return RATE_PRO if key in _PRO_KEYS else RATE_FREE
