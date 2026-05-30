"""
core/auth.py — API key auth simple, lista para RapidAPI.

RapidAPI inyecta la cabecera X-RapidAPI-Proxy-Secret para verificar
que la llamada viene de su proxy. También soportamos x-api-key propio
para clientes directos.
"""
import os
from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

# Cabecera que usa RapidAPI para proteger tu endpoint
RAPIDAPI_SECRET_HEADER = APIKeyHeader(name="X-RapidAPI-Proxy-Secret", auto_error=False)

# Cabecera para clientes directos (tests, Chrome extension, etc.)
OWN_API_KEY_HEADER = APIKeyHeader(name="x-api-key", auto_error=False)


def verify_key(
    rapidapi_secret: str | None = Security(RAPIDAPI_SECRET_HEADER),
    own_key: str | None = Security(OWN_API_KEY_HEADER),
) -> str:
    """
    Valida que la request venga de RapidAPI o use una API key propia.
    En desarrollo (ENVIRONMENT=dev) bypasea la auth.
    """
    env = os.environ.get("ENVIRONMENT", "prod")
    if env == "dev":
        return "dev"

    # Verificación de RapidAPI
    expected_secret = os.environ.get("RAPIDAPI_PROXY_SECRET", "")
    if rapidapi_secret and expected_secret and rapidapi_secret == expected_secret:
        return "rapidapi"

    # Verificación de clave propia (comma-separated list en env var)
    valid_keys = os.environ.get("API_KEYS", "").split(",")
    if own_key and own_key.strip() in [k.strip() for k in valid_keys if k.strip()]:
        return "direct"

    raise HTTPException(status_code=401, detail="API key inválida o ausente.")
