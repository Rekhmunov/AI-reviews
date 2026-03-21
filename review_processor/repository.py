from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ProcessedReview, ReviewInput


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ReviewRepository:
    """SQLite repository for storing processed marketplace reviews."""

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
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
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
                    status TEXT NOT NULL,
                    auto_reply TEXT,
                    manual_reply TEXT,
                    operator_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert_processed_review(
        self,
        source: str,
        review: ReviewInput,
        processed: ProcessedReview,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reviews (
                    review_id, source, text, author, rating, metadata_json,
                    normalized_text, sentiment_score, sentiment_label, is_spam, is_toxic,
                    priority, tags_json, recommended_action, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    source=excluded.source,
                    text=excluded.text,
                    author=excluded.author,
                    rating=excluded.rating,
                    metadata_json=excluded.metadata_json,
                    normalized_text=excluded.normalized_text,
                    sentiment_score=excluded.sentiment_score,
                    sentiment_label=excluded.sentiment_label,
                    is_spam=excluded.is_spam,
                    is_toxic=excluded.is_toxic,
                    priority=excluded.priority,
                    tags_json=excluded.tags_json,
                    recommended_action=excluded.recommended_action,
                    updated_at=excluded.updated_at
                """,
                (
                    review.review_id,
                    source,
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
                    "new",
                    now,
                    now,
                ),
            )

    def list_reviews(
        self,
        *,
        priority: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if status:
            clauses.append("status = ?")
            params.append(status)

        query = "SELECT * FROM reviews"
        if clauses:
            query += f" WHERE {' AND '.join(clauses)}"
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reviews WHERE review_id = ?", (review_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def mark_manual_queue(self, review_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE reviews
                SET status = 'queued_for_operator', updated_at = ?
                WHERE review_id = ?
                """,
                (_utc_now(), review_id),
            )
            return result.rowcount > 0

    def mark_auto_replied(self, review_id: str, response_text: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE reviews
                SET status = 'answered_auto', auto_reply = ?, updated_at = ?
                WHERE review_id = ?
                """,
                (response_text, _utc_now(), review_id),
            )
            return result.rowcount > 0

    def mark_manual_replied(self, review_id: str, operator_name: str, response_text: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE reviews
                SET status = 'answered_manual', manual_reply = ?, operator_name = ?, updated_at = ?
                WHERE review_id = ?
                """,
                (response_text, operator_name, _utc_now(), review_id),
            )
            return result.rowcount > 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["is_spam"] = bool(data["is_spam"])
        data["is_toxic"] = bool(data["is_toxic"])
        data["tags"] = json.loads(data.pop("tags_json"))
        data["metadata"] = json.loads(data.pop("metadata_json"))
        return data
