import json
import re
import uuid
from typing import Any, Dict, List

from .config import get_app_config


def _require_psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("缺少 PostgreSQL 驱动 psycopg，请先安装 `psycopg[binary]`。") from exc
    return psycopg


def _datasource() -> Dict[str, str]:
    config = get_app_config().get("datasource", {})
    url = str(config.get("url", "jdbc:postgresql://localhost:5432/ai_interview"))
    match = re.match(r"^jdbc:postgresql://([^:/]+)(?::(\d+))?/([^?]+)", url)
    if not match:
        raise ValueError(f"无法解析 PostgreSQL JDBC URL：{url}")
    host, port, database = match.groups()
    return {
        "host": host,
        "port": port or "5432",
        "dbname": database,
        "user": str(config.get("username", "postgres")),
        "password": str(config.get("password", "123456")),
    }


def _vector_literal(vector: List[float]) -> str:
    return "[" + ",".join(f"{float(item):.10g}" for item in vector) + "]"


def _to_ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return int(value.timestamp() * 1000)


def _connect():
    psycopg = _require_psycopg()
    return psycopg.connect(**_datasource())


def ensure_schema() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    object_uri TEXT NOT NULL,
                    storage_type TEXT NOT NULL,
                    object_key TEXT,
                    bucket TEXT,
                    endpoint TEXT,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunk (
                    id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    source_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_kb ON knowledge_chunk(knowledge_base_id)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    knowledge_base_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_message (
                    id BIGSERIAL PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_message_conversation
                ON conversation_message(conversation_id, created_at)
                """
            )


def save_knowledge_base(knowledge_base: Dict[str, Any], embeddings: List[List[float]]) -> None:
    chunks = knowledge_base.get("chunks", [])
    if len(chunks) != len(embeddings):
        raise ValueError("分块数量和向量数量不一致，无法写入 PostgreSQL。")

    ensure_schema()
    object_info = knowledge_base.get("object", {})
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    id, name, filename, object_uri, storage_type, object_key,
                    bucket, endpoint, chunk_count, metadata, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    filename = EXCLUDED.filename,
                    object_uri = EXCLUDED.object_uri,
                    storage_type = EXCLUDED.storage_type,
                    object_key = EXCLUDED.object_key,
                    bucket = EXCLUDED.bucket,
                    endpoint = EXCLUDED.endpoint,
                    chunk_count = EXCLUDED.chunk_count,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                (
                    knowledge_base["id"],
                    knowledge_base["name"],
                    knowledge_base["filename"],
                    object_info.get("uri", ""),
                    object_info.get("storage", ""),
                    object_info.get("object_key", ""),
                    object_info.get("bucket", ""),
                    object_info.get("endpoint", ""),
                    knowledge_base["chunk_count"],
                    json.dumps({"object": object_info}, ensure_ascii=False),
                ),
            )
            cur.execute("DELETE FROM knowledge_chunk WHERE knowledge_base_id = %s", (knowledge_base["id"],))
            for chunk, embedding in zip(chunks, embeddings):
                cur.execute(
                    """
                    INSERT INTO knowledge_chunk (
                        id, knowledge_base_id, chunk_index, source_name,
                        content, embedding, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s::jsonb)
                    """,
                    (
                        chunk["id"],
                        knowledge_base["id"],
                        chunk["index"],
                        chunk["source_name"],
                        chunk["text"],
                        _vector_literal(embedding),
                        json.dumps({"score_hint": 0}, ensure_ascii=False),
                    ),
                )


def search_chunks(knowledge_base_id: str, query_embedding: List[float], limit: int = 5) -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, knowledge_base_id, chunk_index, source_name, content, embedding <=> %s::vector AS distance
                FROM knowledge_chunk
                WHERE knowledge_base_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    _vector_literal(query_embedding),
                    knowledge_base_id,
                    _vector_literal(query_embedding),
                    limit,
                ),
            )
            rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "knowledge_base_id": row[1],
            "index": row[2],
            "source_name": row[3],
            "text": row[4],
            "score": round(float(1 / (1 + row[5])), 4),
        }
        for row in rows
    ]


def search_chunks_across_knowledge_bases(
        knowledge_base_ids: List[str],
        query_embedding: List[float],
        limit: int = 5,
) -> List[Dict[str, Any]]:
    if not knowledge_base_ids:
        return []
    ensure_schema()
    placeholders = ", ".join(["%s"] * len(knowledge_base_ids))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, knowledge_base_id, chunk_index, source_name, content, embedding <=> %s::vector AS distance
                FROM knowledge_chunk
                WHERE knowledge_base_id IN ({placeholders})
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    _vector_literal(query_embedding),
                    *knowledge_base_ids,
                    _vector_literal(query_embedding),
                    limit,
                ),
            )
            rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "knowledge_base_id": row[1],
            "index": row[2],
            "source_name": row[3],
            "text": row[4],
            "score": round(float(1 / (1 + row[5])), 4),
        }
        for row in rows
    ]


def list_conversations(conversation_type: str = "") -> List[Dict[str, Any]]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            if conversation_type:
                cur.execute(
                    """
                    SELECT c.id, c.type, c.title, c.knowledge_base_id, c.created_at, c.updated_at,
                           COUNT(m.id) AS message_count
                    FROM conversation c
                    LEFT JOIN conversation_message m ON m.conversation_id = c.id
                    WHERE c.type = %s
                    GROUP BY c.id
                    ORDER BY c.updated_at DESC
                    """,
                    (conversation_type,),
                )
            else:
                cur.execute(
                    """
                    SELECT c.id, c.type, c.title, c.knowledge_base_id, c.created_at, c.updated_at,
                           COUNT(m.id) AS message_count
                    FROM conversation c
                    LEFT JOIN conversation_message m ON m.conversation_id = c.id
                    GROUP BY c.id
                    ORDER BY c.updated_at DESC
                    """
                )
            rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "type": row[1],
            "title": row[2],
            "knowledge_base_id": row[3] or "",
            "created_at": _to_ms(row[4]),
            "updated_at": _to_ms(row[5]),
            "message_count": int(row[6] or 0),
        }
        for row in rows
    ]


def get_conversation(conversation_id: str) -> Dict[str, Any]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, type, title, knowledge_base_id, created_at, updated_at
                FROM conversation
                WHERE id = %s
                """,
                (conversation_id,),
            )
            conversation = cur.fetchone()
            if not conversation:
                raise ValueError("会话不存在。")

            cur.execute(
                """
                SELECT role, content, sources, created_at
                FROM conversation_message
                WHERE conversation_id = %s
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_id,),
            )
            messages = cur.fetchall()

    return {
        "id": conversation[0],
        "type": conversation[1],
        "title": conversation[2],
        "knowledge_base_id": conversation[3] or "",
        "created_at": _to_ms(conversation[4]),
        "updated_at": _to_ms(conversation[5]),
        "messages": [
            {
                "role": row[0],
                "content": row[1],
                "sources": row[2] or [],
                "created_at": _to_ms(row[3]),
            }
            for row in messages
        ],
    }


def delete_conversation(conversation_id: str) -> Dict[str, Any]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversation WHERE id = %s", (conversation_id,))
            deleted = cur.rowcount
    if not deleted:
        raise ValueError("会话不存在。")
    return {"deleted": True, "conversation_id": conversation_id}


def save_conversation_exchange(
        message: str,
        answer: str,
        conversation_id: str = "",
        conversation_type: str = "assistant",
        knowledge_base_id: str = "",
        sources: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    ensure_schema()
    conversation_id = conversation_id or uuid.uuid4().hex
    title = message[:40] or "新会话"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation (id, type, title, knowledge_base_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    type = EXCLUDED.type,
                    knowledge_base_id = EXCLUDED.knowledge_base_id,
                    updated_at = NOW()
                """,
                (conversation_id, conversation_type, title, knowledge_base_id or None),
            )
            cur.execute(
                """
                INSERT INTO conversation_message (conversation_id, role, content, sources)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (conversation_id, "user", message, json.dumps([], ensure_ascii=False)),
            )
            cur.execute(
                """
                INSERT INTO conversation_message (conversation_id, role, content, sources)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (
                    conversation_id,
                    "assistant",
                    answer,
                    json.dumps(sources or [], ensure_ascii=False),
                ),
            )
    return get_conversation(conversation_id)


def save_conversation_snapshot(conversation: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation (id, type, title, knowledge_base_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, to_timestamp(%s / 1000.0), to_timestamp(%s / 1000.0))
                ON CONFLICT (id) DO UPDATE SET
                    type = EXCLUDED.type,
                    title = EXCLUDED.title,
                    knowledge_base_id = EXCLUDED.knowledge_base_id,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    conversation["id"],
                    conversation.get("type", "assistant"),
                    conversation.get("title", "会话"),
                    conversation.get("knowledge_base_id") or None,
                    int(conversation.get("created_at") or 0),
                    int(conversation.get("updated_at") or 0),
                ),
            )
            cur.execute("DELETE FROM conversation_message WHERE conversation_id = %s", (conversation["id"],))
            for message in conversation.get("messages", []):
                cur.execute(
                    """
                    INSERT INTO conversation_message (conversation_id, role, content, sources, created_at)
                    VALUES (%s, %s, %s, %s::jsonb, to_timestamp(%s / 1000.0))
                    """,
                    (
                        conversation["id"],
                        message.get("role", "user"),
                        message.get("content", ""),
                        json.dumps(message.get("sources", []), ensure_ascii=False),
                        int(message.get("created_at") or conversation.get("updated_at") or 0),
                    ),
                )
    return get_conversation(conversation["id"])
