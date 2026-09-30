"""SQLite persistence for conversations, messages and feedback.

Conversations are scoped to an anonymous client id (a random UUID the browser
keeps in localStorage), so one visitor cannot list another's chats. Only the
PII-redacted user text is ever stored.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    title TEXT NOT NULL,
    lang TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_client ON conversations(client_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS feedback (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    comment TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._db.execute(sql, params)
            rows = cur.fetchall()
            self._db.commit()
            return rows

    # -- conversations -----------------------------------------------------------
    def create_conversation(self, client_id: str, title: str, lang: str) -> str:
        cid = uuid.uuid4().hex
        now = time.time()
        self._exec(
            "INSERT INTO conversations (id, client_id, title, lang, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (cid, client_id, title[:80] or "…", lang, now, now),
        )
        return cid

    def get_conversation(self, conversation_id: str, client_id: str) -> dict | None:
        rows = self._exec(
            "SELECT * FROM conversations WHERE id = ? AND client_id = ?", (conversation_id, client_id)
        )
        return dict(rows[0]) if rows else None

    def list_conversations(self, client_id: str, limit: int = 50) -> list[dict]:
        rows = self._exec(
            "SELECT id, title, lang, created_at, updated_at FROM conversations "
            "WHERE client_id = ? ORDER BY updated_at DESC LIMIT ?",
            (client_id, limit),
        )
        return [dict(r) for r in rows]

    def delete_conversation(self, conversation_id: str, client_id: str) -> bool:
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM conversations WHERE id = ? AND client_id = ?", (conversation_id, client_id)
            )
            self._db.commit()
            return cur.rowcount > 0

    # -- messages ------------------------------------------------------------------
    def add_message(self, conversation_id: str, role: str, content: str, meta: dict | None = None) -> str:
        mid = uuid.uuid4().hex
        now = time.time()
        self._exec(
            "INSERT INTO messages (id, conversation_id, role, content, meta, created_at) VALUES (?,?,?,?,?,?)",
            (mid, conversation_id, role, content, json.dumps(meta or {}, ensure_ascii=False), now),
        )
        self._exec("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return mid

    def messages(self, conversation_id: str) -> list[dict]:
        rows = self._exec(
            "SELECT m.id, m.role, m.content, m.meta, m.created_at, f.rating FROM messages m "
            "LEFT JOIN feedback f ON f.message_id = m.id "
            "WHERE m.conversation_id = ? ORDER BY m.created_at",
            (conversation_id,),
        )
        return [{**dict(r), "meta": json.loads(r["meta"])} for r in rows]

    def recent_turns(self, conversation_id: str, limit: int) -> list[dict]:
        """Last `limit` messages as {"role", "content"} for LLM context."""
        rows = self._exec(
            "SELECT role, content FROM (SELECT role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?) ORDER BY created_at",
            (conversation_id, limit),
        )
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    # -- feedback --------------------------------------------------------------------
    def set_feedback(self, message_id: str, client_id: str, rating: int, comment: str = "") -> bool:
        owner = self._exec(
            "SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.id = ? AND c.client_id = ? AND m.role = 'assistant'",
            (message_id, client_id),
        )
        if not owner:
            return False
        self._exec(
            "INSERT INTO feedback (message_id, rating, comment, created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(message_id) DO UPDATE SET rating = excluded.rating, comment = excluded.comment, "
            "created_at = excluded.created_at",
            (message_id, rating, comment[:1000], time.time()),
        )
        return True
