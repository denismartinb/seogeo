"""
tests/conftest.py — Fixtures compartidas para todos los tests.
"""
import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Forzar entorno dev (sin auth real, sin Gemini real)
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("GEMINI_API_KEY", "test-key")


@pytest_asyncio.fixture
async def client():
    """Cliente HTTP async apuntando a la app FastAPI."""
    from api.index import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
