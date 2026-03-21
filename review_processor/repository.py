from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ProcessedReview, ReviewInput


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ReviewRepository:
    """SQLite repository for auth, settings, and marketplace reviews."""

    def __init__(self, db_path: str = "reviews.db") -> None:
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_schema()

    def _ensure_db_dir(self) -> None:
        db_file = Path(self.db_path)
        if db_file.parent != Path("."):
            db_file.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    provider TEXT NOT NULL,
                    yandex_api_key TEXT,
                    yandex_folder_id TEXT,
                    yandex_model_uri TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO ai_settings (id, provider, yandex_api_key, yandex_folder_id, yandex_model_uri, updated_at)
                VALUES (1, 'rules', NULL, NULL, NULL, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (_utc_now(),),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marketplace_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    marketplace TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    api_url TEXT NOT NULL,
                    api_key TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS response_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    template_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, category),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_items (
                    review_uid TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    external_review_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    account_id INTEGER,
                    text TEXT NOT NULL,
                    author TEXT,
                    rating INTEGER,
                    metadata_json TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    sentiment_score INTEGER NOT NULL,
                    sentiment_label TEXT NOT NULL,
                    is_spam INTEGER NOT NULL,
                    is_toxic INTEGER NOT NULL,
                    priority TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    category TEXT NOT NULL,
                    processing_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    auto_reply TEXT,
                    manual_reply TEXT,
                    operator_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (account_id) REFERENCES marketplace_accounts(id) ON DELETE SET NULL
                )
                """
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        if "is_spam" in data:
            data["is_spam"] = bool(data["is_spam"])
        if "is_toxic" in data:
            data["is_toxic"] = bool(data["is_toxic"])
        if "is_active" in data:
            data["is_active"] = bool(data["is_active"])
        if "tags_json" in data:
            data["tags"] = json.loads(data.pop("tags_json"))
        if "metadata_json" in data:
            data["metadata"] = json.loads(data.pop("metadata_json"))
        return data

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"]) if row else 0

    def create_user(self, email: str, password_hash: str, role: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (email, password_hash, role, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email.lower(), password_hash, role, now),
            )
            user_id = int(cursor.lastrowid)
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("User creation failed")
        return user

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, email, role, created_at FROM users ORDER BY id ASC").fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_user_role(self, user_id: int, role: str) -> bool:
        with self._connect() as conn:
            result = conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        return result.rowcount > 0

    def create_session(self, token: str, user_id: int, expires_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token, user_id, expires_at, _utc_now()),
            )

    def get_session_user(self, token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT users.*
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ?
                """,
                (token,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def cleanup_expired_sessions(self, now_iso: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso,))

    def get_ai_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("AI settings row is missing")
        return self._row_to_dict(row)

    def update_ai_settings(
        self,
        *,
        provider: str,
        yandex_api_key: str | None,
        yandex_folder_id: str | None,
        yandex_model_uri: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_settings
                SET provider = ?, yandex_api_key = ?, yandex_folder_id = ?, yandex_model_uri = ?, updated_at = ?
                WHERE id = 1
                """,
                (provider, yandex_api_key, yandex_folder_id, yandex_model_uri, _utc_now()),
            )

    def create_marketplace_account(
        self,
        *,
        user_id: int,
        marketplace: str,
        account_name: str,
        api_url: str,
        api_key: str | None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO marketplace_accounts (
                    user_id, marketplace, account_name, api_url, api_key, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, marketplace, account_name, api_url, api_key, int(is_active), now, now),
            )
            account_id = int(cursor.lastrowid)
        account = self.get_marketplace_account(user_id=user_id, account_id=account_id)
        if account is None:
            raise RuntimeError("Marketplace account creation failed")
        return account

    def list_marketplace_accounts(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM marketplace_accounts
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_marketplace_account(self, *, user_id: int, account_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM marketplace_accounts
                WHERE user_id = ? AND id = ?
                """,
                (user_id, account_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def update_marketplace_account_status(self, *, user_id: int, account_id: int, is_active: bool) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE marketplace_accounts
                SET is_active = ?, updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (int(is_active), _utc_now(), user_id, account_id),
            )
        return result.rowcount > 0

    def upsert_template(self, *, user_id: int, category: str, mode: str, template_text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO response_templates (user_id, category, mode, template_text, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, category) DO UPDATE SET
                    mode = excluded.mode,
                    template_text = excluded.template_text,
                    updated_at = excluded.updated_at
                """,
                (user_id, category, mode, template_text, _utc_now()),
            )

    def list_templates(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM response_templates
                WHERE user_id = ?
                ORDER BY category ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_template(self, *, user_id: int, category: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM response_templates
                WHERE user_id = ? AND category = ?
                """,
                (user_id, category),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    @staticmethod
    def make_review_uid(user_id: int, source: str, account_id: int | None, external_review_id: str) -> str:
        account_part = str(account_id) if account_id is not None else "na"
        return f"{user_id}:{source}:{account_part}:{external_review_id}"

    def upsert_processed_review(
        self,
        *,
        user_id: int,
        source: str,
        account_id: int | None,
        review: ReviewInput,
        processed: ProcessedReview,
        category: str,
        processing_mode: str,
        status: str,
        auto_reply: str | None = None,
    ) -> None:
        review_uid = self.make_review_uid(user_id, source, account_id, review.review_id)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_items (
                    review_uid, user_id, external_review_id, source, account_id, text, author, rating, metadata_json,
                    normalized_text, sentiment_score, sentiment_label, is_spam, is_toxic,
                    priority, tags_json, recommended_action, category, processing_mode, status, auto_reply,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_uid) DO UPDATE SET
                    text = excluded.text,
                    author = excluded.author,
                    rating = excluded.rating,
                    metadata_json = excluded.metadata_json,
                    normalized_text = excluded.normalized_text,
                    sentiment_score = excluded.sentiment_score,
                    sentiment_label = excluded.sentiment_label,
                    is_spam = excluded.is_spam,
                    is_toxic = excluded.is_toxic,
                    priority = excluded.priority,
                    tags_json = excluded.tags_json,
                    recommended_action = excluded.recommended_action,
                    category = excluded.category,
                    processing_mode = excluded.processing_mode,
                    status = CASE
                        WHEN review_items.status = 'answered_manual' THEN review_items.status
                        ELSE excluded.status
                    END,
                    auto_reply = CASE
                        WHEN review_items.status = 'answered_manual' THEN review_items.auto_reply
                        WHEN review_items.status = 'answered_auto' AND excluded.status != 'answered_auto' THEN review_items.auto_reply
                        ELSE excluded.auto_reply
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    review_uid,
                    user_id,
                    review.review_id,
                    source,
                    account_id,
                    review.text,
                    review.author,
                    review.rating,
                    json.dumps(review.metadata, ensure_ascii=False),
                    processed.normalized_text,
                    processed.sentiment_score,
                    processed.sentiment_label,
                    int(processed.is_spam),
                    int(processed.is_toxic),
                    processed.priority,
                    json.dumps(processed.tags, ensure_ascii=False),
                    processed.recommended_action,
                    category,
                    processing_mode,
                    status,
                    auto_reply,
                    now,
                    now,
                ),
            )

    def list_reviews(
        self,
        *,
        user_id: int,
        priority: str | None = None,
        status: str | None = None,
        category: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = ["user_id = ?"]
        params: list[Any] = [user_id]
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if category:
            clauses.append("category = ?")
            params.append(category)

        query = "SELECT * FROM review_items"
        if clauses:
            query += f" WHERE {' AND '.join(clauses)}"
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_review(self, *, user_id: int, review_uid: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM review_items
                WHERE user_id = ? AND review_uid = ?
                """,
                (user_id, review_uid),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_manual_queue(self, *, user_id: int, review_uid: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE review_items
                SET status = 'queued_for_operator', updated_at = ?
                WHERE user_id = ? AND review_uid = ?
                """,
                (_utc_now(), user_id, review_uid),
            )
            return result.rowcount > 0

    def mark_auto_replied(self, *, user_id: int, review_uid: str, response_text: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE review_items
                SET status = 'answered_auto', auto_reply = ?, updated_at = ?
                WHERE user_id = ? AND review_uid = ?
                """,
                (response_text, _utc_now(), user_id, review_uid),
            )
            return result.rowcount > 0

    def mark_manual_replied(self, *, user_id: int, review_uid: str, operator_name: str, response_text: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE review_items
                SET status = 'answered_manual', manual_reply = ?, operator_name = ?, updated_at = ?
                WHERE user_id = ? AND review_uid = ?
                """,
                (response_text, operator_name, _utc_now(), user_id, review_uid),
            )
            return result.rowcount > 0

    def raw_fetch(self, query: str, params: tuple[Any, ...] = ()) -> list[Mapping[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]
