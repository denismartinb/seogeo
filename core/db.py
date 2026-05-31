"""
core/db.py — Async SQLite persistence for analyses and improvements.

Local dev: file at DB_PATH (default /tmp/seogeo.db)
Vercel: /tmp is ephemeral per container; swap DB_PATH for a Postgres DSN
        and replace aiosqlite calls with asyncpg to persist across deploys.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Optional

import aiosqlite

DB_PATH = os.environ.get("DB_PATH", "/tmp/seogeo.db")


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS analyses (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,
                input_data  TEXT NOT NULL,
                result      TEXT NOT NULL,
                title       TEXT,
                seo_score   INTEGER,
                geo_score   INTEGER,
                session_id  TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS improvements (
                id              TEXT PRIMARY KEY,
                analysis_id     TEXT NOT NULL,
                improvements    TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS content_cache (
                content_hash    TEXT PRIMARY KEY,
                result          TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                hit_count       INTEGER DEFAULT 0,
                last_hit        TEXT
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_analyses_session ON analyses(session_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_improvements_analysis ON improvements(analysis_id)")
        await db.commit()


def _extract_title(type_: str, input_data: dict, result: dict) -> str:
    if type_ == "url":
        url = input_data.get("url", "")
        return url[:80] if url else "URL Analysis"
    if type_ == "keywords":
        return input_data.get("text", "Keyword Research")[:80]
    # text analysis: use generated title if available
    seo = result.get("seo", result)
    generated = seo.get("title") if isinstance(seo, dict) else None
    if generated:
        return generated[:80]
    raw = input_data.get("text", "")
    return (raw[:60] + "…") if len(raw) > 60 else raw


async def save_analysis(
    type_: str,
    input_data: dict,
    result: dict,
    session_id: Optional[str] = None,
) -> str:
    analysis_id = str(uuid.uuid4())
    title = _extract_title(type_, input_data, result)

    seo_block = result.get("seo", result) if isinstance(result, dict) else {}
    geo_block = result.get("geo", result) if isinstance(result, dict) else {}
    seo_score = seo_block.get("seo_score") if isinstance(seo_block, dict) else None
    geo_score = geo_block.get("geo_score") if isinstance(geo_block, dict) else None

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO analyses VALUES (?,?,?,?,?,?,?,?,?)",
            (
                analysis_id,
                type_,
                json.dumps(input_data, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                title,
                seo_score,
                geo_score,
                session_id,
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()
    return analysis_id


async def list_analyses(session_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if session_id:
            cur = await db.execute(
                "SELECT id, type, title, seo_score, geo_score, session_id, created_at "
                "FROM analyses WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            )
        else:
            cur = await db.execute(
                "SELECT id, type, title, seo_score, geo_score, session_id, created_at "
                "FROM analyses ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_analysis(analysis_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["input_data"] = json.loads(d["input_data"])
        d["result"] = json.loads(d["result"])
        return d


async def delete_analysis(analysis_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_content_cache(content_hash: str) -> Optional[dict]:
    """Returns cached analysis result for this content hash, or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT result FROM content_cache WHERE content_hash=?",
            (content_hash,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        # Update hit stats asynchronously
        await db.execute(
            "UPDATE content_cache SET hit_count=hit_count+1, last_hit=? WHERE content_hash=?",
            (datetime.utcnow().isoformat(), content_hash),
        )
        await db.commit()
        return json.loads(row["result"])


async def save_content_cache(content_hash: str, result: dict) -> None:
    """Saves analysis result keyed by content hash."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO content_cache(content_hash, result, created_at, hit_count) VALUES (?,?,?,0)",
            (content_hash, json.dumps(result, ensure_ascii=False), datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_cached_improvements(analysis_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT improvements FROM improvements WHERE analysis_id=? ORDER BY created_at DESC LIMIT 1",
            (analysis_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return json.loads(row["improvements"])


async def save_improvements(analysis_id: str, improvements: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO improvements VALUES (?,?,?,?)",
            (
                str(uuid.uuid4()),
                analysis_id,
                json.dumps(improvements, ensure_ascii=False),
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()
