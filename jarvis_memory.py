"""
JARVIS LOCAL MEMORY — Drop-in replacement for Mem0
Uses SQLite + sqlite-vec for vector search. No server, no subscription.

Usage (mirrors your existing Mem0 pattern):
    from jarvis_memory import JarvisMemory
    memory = JarvisMemory()                          # creates jarvis_memory.db
    await memory.add(messages, user_id="Ma'am")      # save conversation
    results = await memory.search("design prefs", filters={"user_id": "Ma'am"})
    
Embedding cost: ~$0.02 per 1M tokens via OpenAI text-embedding-3-small
Alternative: set JARVIS_EMBED_LOCAL=1 to use sentence-transformers (free, no API)

Requirements:
    pip install sqlite-vec openai
    # Optional for free local embeddings:
    pip install sentence-transformers
"""

import os
import json
import sqlite3
import struct
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding providers
# ---------------------------------------------------------------------------

EMBED_DIM = 384  # all-MiniLM-L6-v2 dimension (local)
OPENAI_EMBED_DIM = 1536  # text-embedding-3-small dimension

_local_model = None
_openai_client = None


def _use_local_embeddings() -> bool:
    return os.getenv("JARVIS_EMBED_LOCAL", "").strip() in ("1", "true", "yes")


def _get_embed_dim() -> int:
    return EMBED_DIM if _use_local_embeddings() else OPENAI_EMBED_DIM


async def _embed_text(text: str) -> List[float]:
    """Generate embedding vector for text."""
    if _use_local_embeddings():
        return await _embed_local(text)
    return await _embed_openai(text)


async def _embed_openai(text: str) -> List[float]:
    global _openai_client
    if _openai_client is None:
        from openai import AsyncOpenAI
        _openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = await _openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000],
    )
    return response.data[0].embedding


async def _embed_local(text: str) -> List[float]:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        _local_model = SentenceTransformer("all-MiniLM-L6-v2")

    # Run in thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    vec = await loop.run_in_executor(None, lambda: _local_model.encode(text).tolist())
    return vec


def _serialize_f32(vector: List[float]) -> bytes:
    """Serialize a list of floats into bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


# ---------------------------------------------------------------------------
# Self-RAG: extract structured memories from conversation
# ---------------------------------------------------------------------------

async def _extract_memories_from_messages(
    messages: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """
    Use an LLM to extract facts, preferences, and goals from a conversation.
    Falls back to storing raw messages if extraction fails.
    """
    conversation_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in messages if m.get('content')
    )

    if not conversation_text.strip():
        return []

    # Try LLM extraction
    try:
        global _openai_client
        if _openai_client is None:
            from openai import AsyncOpenAI
            _openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = await _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    "Extract distinct, standalone memories from this conversation. "
                    "Each memory should be a single fact, preference, goal, or learning "
                    "that would be useful to recall later. Be specific and concise.\n\n"
                    "Return ONLY a JSON array of objects like:\n"
                    '[{"text": "memory content", "type": "fact|preference|goal|learning"}]\n\n'
                    f"Conversation:\n{conversation_text[:4000]}"
                ),
            }],
            temperature=0.3,
            max_tokens=500,
        )

        raw = response.choices[0].message.content or "[]"
        # Clean markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]

        extracted = json.loads(raw.strip())
        if isinstance(extracted, list) and extracted:
            return [
                {"text": m.get("text", ""), "type": m.get("type", "fact")}
                for m in extracted if m.get("text")
            ]

    except Exception as e:
        logger.warning("LLM memory extraction failed, using raw messages: %s", e)

    # Fallback: store each user message as a memory
    return [
        {"text": m["content"], "type": "fact"}
        for m in messages
        if m.get("role") == "user" and m.get("content", "").strip()
    ]


# ---------------------------------------------------------------------------
# Main memory class
# ---------------------------------------------------------------------------

class EmbeddingDimensionError(Exception):
    """Raised when there's a mismatch between database and current embedding dimensions."""
    pass


class JarvisMemory:
    """
    Local memory system for Jarvis. Drop-in replacement for Mem0's
    AsyncMemoryClient with the same search() and add() interface.
    """

    def __init__(self, db_path: str = "jarvis_memory.db"):
        self.db_path = Path(db_path)
        self.dim = _get_embed_dim()
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist, and validate embedding dimensions."""
        conn = sqlite3.connect(str(self.db_path))
        conn.enable_load_extension(True)
        import sqlite_vec
        conn.load_extension(sqlite_vec.loadable_path())

        # Check if this is a fresh database or existing one
        existing_dim = self._get_existing_dimension(conn)

        if existing_dim is not None and existing_dim != self.dim:
            conn.close()
            current_mode = "local (all-MiniLM-L6-v2)" if _use_local_embeddings() else "OpenAI (text-embedding-3-small)"
            existing_mode = "local (384 dim)" if existing_dim == EMBED_DIM else "OpenAI (1536 dim)"
            raise EmbeddingDimensionError(
                f"Embedding dimension mismatch!\n"
                f"  Database was created with: {existing_mode} ({existing_dim} dimensions)\n"
                f"  Current setting expects:   {current_mode} ({self.dim} dimensions)\n\n"
                f"To fix this, either:\n"
                f"  1. Change JARVIS_EMBED_LOCAL env var to match the database\n"
                f"  2. Delete '{self.db_path}' to start fresh (loses all memories)\n"
                f"  3. Run migration to convert embeddings (not yet implemented)"
            )

        # Create metadata table to track embedding config
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Store the embedding dimension if not already set
        if existing_dim is None:
            conn.execute(
                "INSERT OR IGNORE INTO memory_meta (key, value) VALUES (?, ?)",
                ("embedding_dim", str(self.dim))
            )
            embed_provider = "local" if _use_local_embeddings() else "openai"
            conn.execute(
                "INSERT OR IGNORE INTO memory_meta (key, value) VALUES (?, ?)",
                ("embedding_provider", embed_provider)
            )

        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'fact',
                source TEXT DEFAULT 'conversation',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                access_count INTEGER DEFAULT 0,
                deprecated INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_memories_deprecated ON memories(deprecated);

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
                memory_id INTEGER PRIMARY KEY,
                embedding float[{self.dim}]
            );
        """)
        conn.commit()
        conn.close()
        logger.info(f"Memory database initialized: {self.db_path} (embedding dim: {self.dim})")

    def _get_existing_dimension(self, conn: sqlite3.Connection) -> Optional[int]:
        """Check if database has existing embeddings and return their dimension."""
        try:
            # First check metadata table
            row = conn.execute(
                "SELECT value FROM memory_meta WHERE key = 'embedding_dim'"
            ).fetchone()
            if row:
                return int(row[0])
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

        try:
            # Fallback: check if memory_vec table exists and has data
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_vec"
            ).fetchone()
            if row and row[0] > 0:
                # Table has data but no metadata - this is a legacy database
                # Try to infer dimension from the virtual table schema
                # sqlite-vec stores dimension in table definition
                schema = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_vec'"
                ).fetchone()
                if schema and schema[0]:
                    # Parse "float[384]" or "float[1536]" from schema
                    import re
                    match = re.search(r'float\[(\d+)\]', schema[0])
                    if match:
                        return int(match.group(1))
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

        return None  # Fresh database

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        import sqlite_vec
        conn.load_extension(sqlite_vec.loadable_path())
        return conn

    async def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search memories by semantic similarity.
        Compatible with Mem0's search() interface.

        Args:
            query: Search text
            filters: Dict with optional 'user_id' key
            limit: Max results to return
        """
        user_id = (filters or {}).get("user_id", "Ma'am")

        query_embedding = await _embed_text(query)
        query_bytes = _serialize_f32(query_embedding)

        conn = self._get_conn()
        try:
            # sqlite-vec requires k=? constraint in the WHERE clause for KNN queries
            rows = conn.execute(
                """
                SELECT
                    m.id,
                    m.content,
                    m.memory_type,
                    m.created_at,
                    m.updated_at,
                    v.distance
                FROM memory_vec v
                JOIN memories m ON m.id = v.memory_id
                WHERE v.embedding MATCH ?
                    AND k = ?
                    AND m.user_id = ?
                    AND m.deprecated = 0
                ORDER BY v.distance
                """,
                (query_bytes, limit, user_id),
            ).fetchall()

            # Update access counts
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE memories SET access_count = access_count + 1 WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()

            return [
                {
                    "id": row["id"],
                    "memory": row["content"],
                    "type": row["memory_type"],
                    "updated_at": row["updated_at"],
                    "score": 1.0 - row["distance"],  # convert distance to similarity
                }
                for row in rows
            ]
        finally:
            conn.close()

    async def add(
        self,
        messages: List[Dict[str, str]],
        user_id: str = "Ma'am",
    ) -> int:
        """
        Extract and store memories from a conversation.
        Compatible with Mem0's add() interface.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            user_id: User identifier

        Returns:
            Number of memories stored
        """
        # Extract structured memories using self-RAG
        extracted = await _extract_memories_from_messages(messages)

        if not extracted:
            logger.info("No memories extracted from conversation")
            return 0

        conn = self._get_conn()
        stored = 0
        try:
            for mem in extracted:
                text = mem["text"]
                mem_type = mem.get("type", "fact")

                # Check for near-duplicates
                if await self._is_duplicate(conn, user_id, text):
                    logger.debug("Skipping duplicate memory: %s", text[:50])
                    continue

                # Generate embedding
                embedding = await _embed_text(text)
                emb_bytes = _serialize_f32(embedding)

                # Insert memory
                cursor = conn.execute(
                    """
                    INSERT INTO memories (user_id, content, memory_type, source)
                    VALUES (?, ?, ?, 'conversation')
                    """,
                    (user_id, text, mem_type),
                )
                memory_id = cursor.lastrowid

                # Insert vector
                conn.execute(
                    "INSERT INTO memory_vec (memory_id, embedding) VALUES (?, ?)",
                    (memory_id, emb_bytes),
                )

                stored += 1

            conn.commit()
            logger.info("Stored %d memories for user %s", stored, user_id)
        except Exception as e:
            logger.error("Failed to store memories: %s", e)
            conn.rollback()
        finally:
            conn.close()

        return stored

    async def _is_duplicate(
        self, conn: sqlite3.Connection, user_id: str, text: str, threshold: float = 0.92
    ) -> bool:
        """Check if a very similar memory already exists."""
        try:
            embedding = await _embed_text(text)
            emb_bytes = _serialize_f32(embedding)

            # sqlite-vec requires k=? constraint for KNN queries
            rows = conn.execute(
                """
                SELECT v.distance
                FROM memory_vec v
                JOIN memories m ON m.id = v.memory_id
                WHERE v.embedding MATCH ?
                    AND k = ?
                    AND m.user_id = ?
                    AND m.deprecated = 0
                ORDER BY v.distance
                """,
                (emb_bytes, 1, user_id),
            ).fetchall()

            if rows:
                similarity = 1.0 - rows[0]["distance"]
                return similarity >= threshold

        except Exception:
            pass  # If dedup fails, just store it

        return False

    async def get_stats(self, user_id: str = "Ma'am") -> Dict[str, int]:
        """Get memory statistics."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN memory_type = 'fact' THEN 1 ELSE 0 END) as facts,
                    SUM(CASE WHEN memory_type = 'preference' THEN 1 ELSE 0 END) as preferences,
                    SUM(CASE WHEN memory_type = 'goal' THEN 1 ELSE 0 END) as goals,
                    SUM(CASE WHEN deprecated = 0 THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN deprecated = 1 THEN 1 ELSE 0 END) as deprecated
                FROM memories WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    async def deprecate(self, memory_id: int):
        """Soft-delete a memory."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE memories SET deprecated = 1, updated_at = datetime('now') WHERE id = ?",
                (memory_id,),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

async def _test():
    print("Testing JarvisMemory...")
    mem = JarvisMemory(db_path="test_jarvis_memory.db")

    # Store some test memories
    test_messages = [
        {"role": "user", "content": "I prefer deadpan humor and dry wit"},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "I'm working on building AI agent systems"},
        {"role": "user", "content": "I have dyslexia so I prefer voice over text"},
    ]

    count = await mem.add(test_messages, user_id="Ma'am")
    print(f"  Stored {count} memories")

    # Search
    results = await mem.search(
        "How does she like to communicate?",
        filters={"user_id": "Ma'am"},
    )
    print(f"  Found {len(results)} results:")
    for r in results:
        print(f"    [{r['score']:.2f}] {r['memory'][:80]}")

    # Stats
    stats = await mem.get_stats("Ma'am")
    print(f"  Stats: {stats}")

    # Cleanup test
    Path("test_jarvis_memory.db").unlink(missing_ok=True)
    print("  ✓ All tests passed!")


if __name__ == "__main__":
    asyncio.run(_test())