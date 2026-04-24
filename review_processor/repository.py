from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:  # pragma: no cover - imported lazily in most tests
    import psycopg  # type: ignore
    from psycopg import rows as psycopg_rows  # type: ignore
except Exception:  # pragma: no cover - optional dependency in some environments
    psycopg = None
    psycopg_rows = None

from .models import ProcessedReview, ReviewInput
from .security import decrypt_secret, encrypt_secret, mask_secret

DEFAULT_GROUP_PROCESSORS: dict[str, str] = {
    "positive": "yandex",
    "product_dissatisfaction": "yandex",
    "delivery_problems": "yandex",
    "wrong_size": "yandex",
    "tagged_reviews": "program",
    "textless_ratings": "program",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _replace_qmark_placeholders(query: str) -> str:
    # Convert sqlite-style placeholders to psycopg placeholders.
    result: list[str] = []
    in_single_quote = False
    i = 0
    while i < len(query):
        ch = query[i]
        if ch == "'":
            if in_single_quote and i + 1 < len(query) and query[i + 1] == "'":
                result.append("''")
                i += 2
                continue
            in_single_quote = not in_single_quote
            result.append(ch)
            i += 1
            continue
        if ch == "?" and not in_single_quote:
            result.append("%s")
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _json_load(raw: object, default):
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _coerce_iso_for_storage(value: str | None, *, as_date: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if as_date and len(text) >= 10:
        return text[:10]
    if text.endswith("Z"):
        return text[:-1] + "+00:00"
    return text


class _PgCompatConnection:
    def __init__(self, conn) -> None:
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        self._conn.close()

    def execute(self, query: str, params: tuple[Any, ...] = ()):
        cur = self._conn.cursor(row_factory=psycopg_rows.dict_row)  # type: ignore[union-attr]
        cur.execute(_replace_qmark_placeholders(query), params)
        return cur


class ReviewRepository:
    """Repository for auth, settings, and marketplace reviews."""

    def __init__(self, db_url: str | None = None, db_path: str = "reviews.db") -> None:
        self.db_url = str(db_url or "").strip() or None
        self.is_postgres = bool(self.db_url and self.db_url.startswith("postgres"))
        if self.db_url and not self.is_postgres:
            raise RuntimeError("APP_DB_URL must be a PostgreSQL DSN (postgresql://...)")
        self.db_path = db_path
        if self.is_postgres:
            if psycopg is None or psycopg_rows is None:
                raise RuntimeError("psycopg[binary] is required when APP_DB_URL points to PostgreSQL")
        else:
            self._ensure_db_dir()
        self._init_schema()

    def _ensure_db_dir(self) -> None:
        db_file = Path(self.db_path)
        if db_file.parent != Path("."):
            db_file.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        if self.is_postgres:
            assert psycopg is not None and psycopg_rows is not None
            conn = psycopg.connect(self.db_url, row_factory=psycopg_rows.dict_row, autocommit=True)
            return _PgCompatConnection(conn)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _sql(self, query: str) -> str:
        if self.is_postgres:
            return _replace_qmark_placeholders(query)
        return query

    def _bool_db(self, value: bool | None) -> bool | int | None:
        if value is None:
            return None
        return bool(value) if self.is_postgres else int(bool(value))

    def _json_param(self, value: object) -> object:
        if self.is_postgres:
            return value
        return json.dumps(value, ensure_ascii=False)

    def _init_schema(self) -> None:
        if self.is_postgres:
            sql_path = Path(__file__).resolve().parent.parent / "deploy" / "postgres" / "schema_v1.sql"
            if not sql_path.exists():
                raise RuntimeError(f"PostgreSQL schema file not found: {sql_path}")
            schema_sql = sql_path.read_text(encoding="utf-8")
            with self._connect() as conn:
                conn.execute(schema_sql)
            return

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    full_name TEXT,
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
                    yandex_api_key_encrypted TEXT,
                    yandex_folder_id TEXT,
                    yandex_model_uri TEXT,
                    brand_name TEXT NOT NULL DEFAULT 'VarFabric',
                    group_processors_json TEXT NOT NULL DEFAULT '{}',
                    use_sync_start_date INTEGER NOT NULL DEFAULT 0,
                    sync_start_date TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS marketplace_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    marketplace TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    api_url TEXT NOT NULL,
                    api_key_encrypted TEXT,
                    extra_json TEXT NOT NULL DEFAULT '{}',
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
                    is_enabled INTEGER NOT NULL DEFAULT 0,
                    template_text TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, category),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS response_template_variants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    group_id TEXT NOT NULL,
                    subgroup TEXT NOT NULL,
                    template_text TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processing_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    group_id TEXT NOT NULL,
                    action_mode TEXT NOT NULL,
                    auto_send INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, group_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS product_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    source_article TEXT NOT NULL,
                    target_article TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, source_article, target_article),
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    review_uid TEXT,
                    action_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_items (
                    conversation_uid TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    account_id INTEGER,
                    external_conversation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    customer_name TEXT,
                    message_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    unread_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL,
                    last_message_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (account_id) REFERENCES marketplace_accounts(id) ON DELETE SET NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_review_actions_user_created
                ON review_actions(user_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_user_updated
                ON conversation_items(user_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_template_variants_user_group_sub
                ON response_template_variants(user_id, group_id, subgroup, is_active)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processing_rules_user_group
                ON processing_rules(user_id, group_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_recommendations_user_source
                ON product_recommendations(user_id, source_article, is_active)
                """
            )
            self._migrate_schema(conn)
            conn.execute(
                """
                INSERT INTO ai_settings (
                    id, provider, yandex_api_key_encrypted, yandex_folder_id, yandex_model_uri,
                    brand_name, group_processors_json, use_sync_start_date, sync_start_date, updated_at
                )
                VALUES (1, 'rules', NULL, NULL, NULL, 'VarFabric', ?, 0, NULL, ?)
                ON CONFLICT (id) DO NOTHING
                """,
                (self._json_param(DEFAULT_GROUP_PROCESSORS), _utc_now()),
            )

    def _migrate_schema(self, conn) -> None:
        # PostgreSQL-only runtime: schema migration is handled by schema_v1.sql.
        # Keep method for compatibility with initialization flow.
        _ = conn
        return

    def _table_columns(self, conn, table: str) -> set[str]:
        if self.is_postgres:
            rows = conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ?
                """,
                (table,),
            ).fetchall()
            result: set[str] = set()
            for row in rows:
                if isinstance(row, Mapping):
                    result.add(str(row.get("column_name") or ""))
                else:
                    result.add(str(row["column_name"]))
            return {item for item in result if item}
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row["name"]) for row in rows}

    def _insert_and_get_id(self, conn, query: str, params: tuple[Any, ...]) -> int:
        if self.is_postgres:
            row = conn.execute(self._sql(query + " RETURNING id"), params).fetchone()
            if row is None:
                raise RuntimeError("Insert did not return id")
            return int(row["id"]) if isinstance(row, Mapping) else int(row[0])
        cursor = conn.execute(self._sql(query), params)
        return int(cursor.lastrowid)

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        data = dict(row)
        if "is_spam" in data:
            data["is_spam"] = bool(data["is_spam"])
        if "is_toxic" in data:
            data["is_toxic"] = bool(data["is_toxic"])
        if "is_active" in data:
            data["is_active"] = bool(data["is_active"])
        if "is_enabled" in data:
            data["is_enabled"] = bool(data["is_enabled"])
        if "use_sync_start_date" in data:
            data["use_sync_start_date"] = bool(data["use_sync_start_date"])
        if "auto_send" in data:
            data["auto_send"] = bool(data["auto_send"])
        if "tags_json" in data:
            data["tags"] = _json_load(data.pop("tags_json"), [])
        if "metadata_json" in data:
            data["metadata"] = _json_load(data.pop("metadata_json"), {})
        if "extra_json" in data:
            raw = data.pop("extra_json")
            data["extra"] = _json_load(raw, {})
        return data

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"]) if row else 0

    def create_user(
        self,
        email: str,
        password_hash: str,
        role: str,
        full_name: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            user_id = self._insert_and_get_id(
                conn,
                """
                INSERT INTO users (email, full_name, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (email.lower(), full_name, password_hash, role, now),
            )
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

    def update_user_password(self, *, user_id: int, password_hash: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET password_hash = ?
                WHERE id = ?
                """,
                (password_hash, user_id),
            )
        return result.rowcount > 0

    def update_user_profile(
        self,
        *,
        user_id: int,
        email: str,
        full_name: str | None,
        password_hash: str | None = None,
    ) -> bool:
        if password_hash is None:
            with self._connect() as conn:
                result = conn.execute(
                    """
                    UPDATE users
                    SET email = ?, full_name = ?
                    WHERE id = ?
                    """,
                    (email.lower(), full_name, user_id),
                )
            return result.rowcount > 0

        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET email = ?, full_name = ?, password_hash = ?
                WHERE id = ?
                """,
                (email.lower(), full_name, password_hash, user_id),
            )
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

    def get_ai_settings(self, *, include_secrets: bool = False) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("AI settings row is missing")
        data = self._row_to_dict(row)
        data["brand_name"] = str(data.get("brand_name") or "VarFabric").strip() or "VarFabric"
        raw_modes = str(data.pop("group_processors_json", "{}") or "{}")
        parsed_modes = _json_load(raw_modes, {})
        modes: dict[str, str] = dict(DEFAULT_GROUP_PROCESSORS)
        if isinstance(parsed_modes, dict):
            for key, value in parsed_modes.items():
                group_id = str(key or "").strip()
                mode = str(value or "").strip().lower()
                if not group_id:
                    continue
                if mode not in {"yandex", "program"}:
                    continue
                modes[group_id] = mode
        data["group_processors"] = modes
        encrypted_key = str(data.pop("yandex_api_key_encrypted") or "") if "yandex_api_key_encrypted" in data else ""
        key_value = decrypt_secret(encrypted_key) if encrypted_key else None
        data["has_yandex_api_key"] = bool(key_value)
        data["yandex_api_key_preview"] = mask_secret(key_value)
        if include_secrets:
            data["yandex_api_key"] = key_value
        return data

    def update_ai_settings(
        self,
        *,
        provider: str,
        yandex_api_key: str | None,
        yandex_folder_id: str | None,
        yandex_model_uri: str | None,
        brand_name: str | None = None,
        group_processors: dict[str, str] | None = None,
        use_sync_start_date: bool = False,
        sync_start_date: str | None = None,
    ) -> None:
        current = self.get_ai_settings(include_secrets=True)
        normalized_brand = str(brand_name if brand_name is not None else current.get("brand_name") or "VarFabric").strip()
        if not normalized_brand:
            normalized_brand = "VarFabric"
        normalized_modes: dict[str, str] = dict(DEFAULT_GROUP_PROCESSORS)
        source_modes = group_processors if isinstance(group_processors, dict) else current.get("group_processors")
        if isinstance(source_modes, dict):
            for key, value in source_modes.items():
                group_id = str(key or "").strip()
                mode = str(value or "").strip().lower()
                if not group_id or mode not in {"yandex", "program"}:
                    continue
                normalized_modes[group_id] = mode
        if yandex_api_key is None:
            encrypted_key = encrypt_secret(str(current.get("yandex_api_key") or "")) if current.get("yandex_api_key") else None
        else:
            encrypted_key = encrypt_secret(yandex_api_key.strip())

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_settings
                SET provider = ?, yandex_api_key_encrypted = ?, yandex_folder_id = ?, yandex_model_uri = ?,
                    brand_name = ?, group_processors_json = ?, use_sync_start_date = ?, sync_start_date = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    provider,
                    encrypted_key,
                    yandex_folder_id,
                    yandex_model_uri,
                    normalized_brand,
                    self._json_param(normalized_modes),
                    int(use_sync_start_date),
                    sync_start_date,
                    _utc_now(),
                ),
            )

    def create_marketplace_account(
        self,
        *,
        user_id: int,
        marketplace: str,
        account_name: str,
        api_url: str,
        api_key: str | None,
        extra: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        now = _utc_now()
        encrypted_api_key = encrypt_secret(api_key)
        with self._connect() as conn:
            account_id = self._insert_and_get_id(
                conn,
                """
                INSERT INTO marketplace_accounts (
                    user_id, marketplace, account_name, api_url, api_key_encrypted, extra_json, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    marketplace,
                    account_name,
                    api_url,
                    encrypted_api_key,
                    self._json_param(extra or {}),
                    self._bool_db(is_active),
                    now,
                    now,
                ),
            )
        account = self.get_marketplace_account(user_id=user_id, account_id=account_id, include_secrets=False)
        if account is None:
            raise RuntimeError("Marketplace account creation failed")
        return account

    def list_marketplace_accounts(self, user_id: int, *, include_secrets: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM marketplace_accounts
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._account_row_to_dict(row, include_secrets=include_secrets) for row in rows]

    def get_marketplace_account(
        self,
        *,
        user_id: int,
        account_id: int,
        include_secrets: bool = False,
    ) -> dict[str, Any] | None:
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
        return self._account_row_to_dict(row, include_secrets=include_secrets)

    def _account_row_to_dict(self, row, *, include_secrets: bool) -> dict[str, Any]:
        data = self._row_to_dict(row)
        encrypted = str(data.pop("api_key_encrypted") or "") if "api_key_encrypted" in data else ""
        api_key = decrypt_secret(encrypted) if encrypted else None
        data["has_api_key"] = bool(api_key)
        data["api_key_preview"] = mask_secret(api_key)
        if include_secrets:
            data["api_key"] = api_key
        return data

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

    def delete_marketplace_account(self, *, user_id: int, account_id: int) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM marketplace_accounts
                WHERE user_id = ? AND id = ?
                """,
                (user_id, account_id),
            )
        return result.rowcount > 0

    def upsert_template(
        self,
        *,
        user_id: int,
        category: str,
        mode: str,
        template_text: str,
        is_enabled: bool | None = None,
    ) -> None:
        if is_enabled is None:
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
            return

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO response_templates (user_id, category, mode, is_enabled, template_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, category) DO UPDATE SET
                    mode = excluded.mode,
                    is_enabled = excluded.is_enabled,
                    template_text = excluded.template_text,
                    updated_at = excluded.updated_at
                """,
                (user_id, category, mode, int(is_enabled), template_text, _utc_now()),
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

    def delete_template(self, *, user_id: int, category: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM response_templates
                WHERE user_id = ? AND category = ?
                """,
                (user_id, category),
            )
        return result.rowcount > 0

    def list_template_variants(
        self,
        *,
        user_id: int,
        group_id: str | None = None,
        subgroup: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if group_id:
            clauses.append("group_id = ?")
            params.append(group_id)
        if subgroup:
            clauses.append("subgroup = ?")
            params.append(subgroup)
        if not include_inactive:
            clauses.append("is_active = 1")
        query = f"""
            SELECT *
            FROM response_template_variants
            WHERE {' AND '.join(clauses)}
            ORDER BY subgroup ASC, id ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def replace_subgroup_templates(
        self,
        *,
        user_id: int,
        group_id: str,
        subgroup: str,
        templates: list[str],
    ) -> None:
        clean = [item.strip() for item in templates if item and item.strip()]
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM response_template_variants
                WHERE user_id = ? AND group_id = ? AND subgroup = ?
                """,
                (user_id, group_id, subgroup),
            )
            for text in clean:
                conn.execute(
                    """
                    INSERT INTO response_template_variants (
                        user_id, group_id, subgroup, template_text, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (user_id, group_id, subgroup, text, now, now),
                )

    def add_template_variant(
        self,
        *,
        user_id: int,
        group_id: str,
        subgroup: str,
        template_text: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            row_id = self._insert_and_get_id(
                conn,
                """
                INSERT INTO response_template_variants (
                    user_id, group_id, subgroup, template_text, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (user_id, group_id, subgroup, template_text.strip(), now, now),
            )
            row = conn.execute(
                "SELECT * FROM response_template_variants WHERE id = ?",
                (row_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Template variant creation failed")
        return self._row_to_dict(row)

    def delete_template_variant(self, *, user_id: int, template_id: int) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM response_template_variants
                WHERE user_id = ? AND id = ?
                """,
                (user_id, template_id),
            )
        return result.rowcount > 0

    def get_random_template_variant(
        self,
        *,
        user_id: int,
        group_id: str,
        subgroup: str | None = None,
    ) -> dict[str, Any] | None:
        clauses = ["user_id = ?", "group_id = ?", "is_active = 1"]
        params: list[Any] = [user_id, group_id]
        if subgroup:
            clauses.append("subgroup = ?")
            params.append(subgroup)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM response_template_variants
                WHERE {where}
                ORDER BY RANDOM()
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def upsert_processing_rule(
        self,
        *,
        user_id: int,
        group_id: str,
        action_mode: str,
        auto_send: bool,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO processing_rules (user_id, group_id, action_mode, auto_send, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET
                    action_mode = excluded.action_mode,
                    auto_send = excluded.auto_send,
                    updated_at = excluded.updated_at
                """,
                (user_id, group_id, action_mode, int(auto_send), _utc_now()),
            )

    def list_processing_rules(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM processing_rules
                WHERE user_id = ?
                ORDER BY group_id ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_processing_rule(self, *, user_id: int, group_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM processing_rules
                WHERE user_id = ? AND group_id = ?
                """,
                (user_id, group_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def replace_processing_rules(self, *, user_id: int, rules: list[dict[str, Any]]) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("DELETE FROM processing_rules WHERE user_id = ?", (user_id,))
            for item in rules:
                conn.execute(
                    """
                    INSERT INTO processing_rules (user_id, group_id, action_mode, auto_send, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        str(item.get("group_id") or ""),
                        str(item.get("action_mode") or "manual"),
                        int(bool(item.get("auto_send"))),
                        now,
                    ),
                )

    def list_recommendations(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_article, target_article
                FROM product_recommendations
                WHERE user_id = ? AND is_active = 1
                ORDER BY source_article ASC, target_article ASC
                """,
                (user_id,),
            ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            source = str(row["source_article"] or "").strip()
            target = str(row["target_article"] or "").strip()
            if not source or not target:
                continue
            grouped.setdefault(source, []).append(target)
        items: list[dict[str, Any]] = []
        for source, targets in grouped.items():
            items.append(
                {
                    "source_article": source,
                    "target_articles": targets,
                    "targets_csv": ", ".join(targets),
                }
            )
        return items

    def replace_all_recommendations(self, *, user_id: int, rows: list[dict[str, Any]]) -> int:
        now = _utc_now()
        inserted = 0
        with self._connect() as conn:
            conn.execute("DELETE FROM product_recommendations WHERE user_id = ?", (user_id,))
            for row in rows:
                source_raw = str(row.get("source_article") or "").strip()
                if not source_raw:
                    continue
                targets_raw = row.get("target_articles")
                if not isinstance(targets_raw, list):
                    continue
                seen_targets: set[str] = set()
                for target_value in targets_raw:
                    target = str(target_value or "").strip()
                    if not target or target in seen_targets:
                        continue
                    seen_targets.add(target)
                    conn.execute(
                        """
                        INSERT INTO product_recommendations (
                            user_id, source_article, target_article, is_active, created_at, updated_at
                        ) VALUES (?, ?, ?, 1, ?, ?)
                        """,
                        (user_id, source_raw, target, now, now),
                    )
                    inserted += 1
        return inserted

    def get_random_recommendation(self, *, user_id: int, source_article: str) -> str | None:
        source = source_article.strip()
        if not source:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT target_article
                FROM product_recommendations
                WHERE user_id = ? AND source_article = ? AND is_active = 1
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (user_id, source),
            ).fetchone()
        if row is None:
            return None
        target = str(row["target_article"] or "").strip()
        return target or None

    @staticmethod
    def make_review_uid(user_id: int, source: str, account_id: int | None, external_review_id: str) -> str:
        account_part = str(account_id) if account_id is not None else "na"
        return f"{user_id}:{source}:{account_part}:{external_review_id}"

    @staticmethod
    def make_conversation_uid(
        user_id: int,
        source: str,
        account_id: int | None,
        kind: str,
        external_conversation_id: str,
    ) -> str:
        account_part = str(account_id) if account_id is not None else "na"
        return f"{user_id}:{source}:{account_part}:{kind}:{external_conversation_id}"

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
                    self._json_param(review.metadata),
                    processed.normalized_text,
                    processed.sentiment_score,
                    processed.sentiment_label,
                    int(processed.is_spam),
                    int(processed.is_toxic),
                    processed.priority,
                    self._json_param(processed.tags),
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
        source: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "newest",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        page_data = self.list_reviews_paginated(
            user_id=user_id,
            source=source,
            priority=priority,
            status=status,
            statuses=statuses,
            category=category,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            page=1,
            page_size=limit,
            bucket="all",
        )
        return list(page_data["items"])

    def list_reviews_paginated(
        self,
        *,
        user_id: int,
        source: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 30,
        bucket: str = "all",
    ) -> dict[str, Any]:
        base_clauses: list[str] = ["user_id = ?"]
        base_params: list[Any] = [user_id]
        if source:
            base_clauses.append("source = ?")
            base_params.append(source)
        if priority:
            base_clauses.append("priority = ?")
            base_params.append(priority)
        if category:
            base_clauses.append("category = ?")
            base_params.append(category)
        if date_from:
            if self.is_postgres:
                base_clauses.append("updated_at::date >= ?::date")
            else:
                base_clauses.append("substr(updated_at, 1, 10) >= ?")
            base_params.append(date_from)
        if date_to:
            if self.is_postgres:
                base_clauses.append("updated_at::date <= ?::date")
            else:
                base_clauses.append("substr(updated_at, 1, 10) <= ?")
            base_params.append(date_to)

        view_clauses = list(base_clauses)
        view_params = list(base_params)
        status_values = [str(item).strip() for item in (statuses or []) if str(item).strip()]
        if status_values:
            placeholders = ", ".join("?" for _ in status_values)
            view_clauses.append(f"status IN ({placeholders})")
            view_params.extend(status_values)
        elif status:
            view_clauses.append("status = ?")
            view_params.append(status)
        elif bucket == "new":
            view_clauses.append("status NOT IN ('answered_auto', 'answered_manual', 'ignored')")
        elif bucket == "processed":
            view_clauses.append("status IN ('answered_auto', 'answered_manual', 'ignored')")

        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 500)

        where_base = " AND ".join(base_clauses)
        where_view = " AND ".join(view_clauses)
        sort_key = sort.strip().lower()
        order_by_map = {
            "newest": "updated_at DESC",
            "oldest": "updated_at ASC",
            "rating_asc": "COALESCE(rating, 0) ASC, updated_at DESC",
            "rating_desc": "COALESCE(rating, 0) DESC, updated_at DESC",
            "category": "category ASC, updated_at DESC",
        }
        order_by = order_by_map.get(sort_key, order_by_map["newest"])

        with self._connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM review_items WHERE {where_view}",
                tuple(view_params),
            ).fetchone()
            total = int(total_row["c"]) if total_row else 0
            pages = max((total + safe_page_size - 1) // safe_page_size, 1)
            safe_page = min(safe_page, pages)
            offset = (safe_page - 1) * safe_page_size
            new_row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM review_items
                WHERE {where_base}
                  AND status NOT IN ('answered_auto', 'answered_manual', 'ignored')
                """,
                tuple(base_params),
            ).fetchone()
            processed_row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM review_items
                WHERE {where_base}
                  AND status IN ('answered_auto', 'answered_manual', 'ignored')
                """,
                tuple(base_params),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT *
                FROM review_items
                WHERE {where_view}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                tuple([*view_params, safe_page_size, offset]),
            ).fetchall()
            items = [self._row_to_dict(row) for row in rows]
            review_uids = [str(item.get("review_uid") or "") for item in items if item.get("review_uid")]
            error_map: dict[str, str] = {}
            if review_uids:
                placeholders = ", ".join("?" for _ in review_uids)
                action_rows = conn.execute(
                    f"""
                    SELECT review_uid, details_json
                    FROM review_actions
                    WHERE user_id = ?
                      AND action_type = 'send_reply_error'
                      AND review_uid IN ({placeholders})
                    ORDER BY created_at DESC
                    """,
                    tuple([user_id, *review_uids]),
                ).fetchall()
                for action_row in action_rows:
                    uid = str(action_row["review_uid"] or "")
                    if not uid or uid in error_map:
                        continue
                    details_raw = str(action_row["details_json"] or "{}")
                    details = _json_load(details_raw, {})
                    reason = str(details.get("error") or "").strip()
                    if reason:
                        error_map[uid] = reason
            for item in items:
                uid = str(item.get("review_uid") or "")
                if not uid:
                    continue
                item["send_error_message"] = error_map.get(uid)

        return {
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "pages": pages,
            "new_count": int(new_row["c"]) if new_row else 0,
            "processed_count": int(processed_row["c"]) if processed_row else 0,
        }

    def list_review_sources(self, *, user_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT source
                FROM review_items
                WHERE user_id = ?
                ORDER BY source ASC
                """,
                (user_id,),
            ).fetchall()
        return [str(row["source"]) for row in rows if row["source"] is not None and str(row["source"]).strip()]

    def clear_reviews(self, *, user_id: int) -> int:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM review_items WHERE user_id = ?", (user_id,))
        return int(result.rowcount or 0)

    def list_unprocessed_reviews(self, *, user_id: int, limit: int = 5000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM review_items
                WHERE user_id = ? AND status NOT IN ('answered_auto', 'answered_manual', 'ignored')
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_review_processing_result(
        self,
        *,
        user_id: int,
        review_uid: str,
        status: str,
        auto_reply: str | None = None,
    ) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE review_items
                SET status = ?, auto_reply = ?, updated_at = ?
                WHERE user_id = ? AND review_uid = ?
                """,
                (status, auto_reply, _utc_now(), user_id, review_uid),
            )
        return result.rowcount > 0

    def upsert_conversation(
        self,
        *,
        user_id: int,
        source: str,
        account_id: int | None,
        external_conversation_id: str,
        kind: str,
        customer_name: str | None,
        message_text: str,
        status: str,
        unread_count: int,
        metadata: dict[str, Any] | None = None,
        last_message_at: str | None = None,
    ) -> str:
        conversation_uid = self.make_conversation_uid(
            user_id=user_id,
            source=source,
            account_id=account_id,
            kind=kind,
            external_conversation_id=external_conversation_id,
        )
        now = _utc_now()
        last_message_ts = last_message_at or now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_items (
                    conversation_uid, user_id, source, account_id, external_conversation_id,
                    kind, customer_name, message_text, status, unread_count, metadata_json,
                    last_message_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_uid) DO UPDATE SET
                    customer_name = excluded.customer_name,
                    message_text = excluded.message_text,
                    status = excluded.status,
                    unread_count = excluded.unread_count,
                    metadata_json = excluded.metadata_json,
                    last_message_at = excluded.last_message_at,
                    updated_at = excluded.updated_at
                """,
                (
                    conversation_uid,
                    user_id,
                    source,
                    account_id,
                    external_conversation_id,
                    kind,
                    customer_name,
                    message_text,
                    status,
                    max(unread_count, 0),
                    self._json_param(metadata or {}),
                    last_message_ts,
                    now,
                    now,
                ),
            )
        return conversation_uid

    def list_conversations(
        self,
        *,
        user_id: int,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if status:
            clauses.append("status = ?")
            params.append(status)

        query = f"SELECT * FROM conversation_items WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            raw = data.pop("metadata_json", "{}")
            data["metadata"] = _json_load(raw, {})
            result.append(data)
        return result

    def update_conversation_status(self, *, user_id: int, conversation_uid: str, status: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE conversation_items
                SET status = ?, unread_count = CASE WHEN ? = 'closed' THEN 0 ELSE unread_count END, updated_at = ?
                WHERE user_id = ? AND conversation_uid = ?
                """,
                (status, status, _utc_now(), user_id, conversation_uid),
            )
        return result.rowcount > 0

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

    def log_review_action(
        self,
        *,
        user_id: int,
        review_uid: str | None,
        action_type: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_actions (user_id, review_uid, action_type, actor, details_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, review_uid, action_type, actor, self._json_param(details or {}), _utc_now()),
            )

    def list_recent_actions(self, *, user_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        query = "SELECT * FROM review_actions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            data = self._row_to_dict(row)
            raw = data.pop("details_json", "{}")
            data["details"] = _json_load(raw, {})
            items.append(data)
        return items

    def get_sla_metrics(self, *, user_id: int | None = None) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        where_and = f"{where} AND" if where else "WHERE"
        avg_expr = (
            "AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 60.0)"
            if self.is_postgres
            else "AVG((julianday(updated_at) - julianday(created_at)) * 24.0 * 60.0)"
        )
        overdue_expr = (
            "EXTRACT(EPOCH FROM (NOW() - updated_at)) / 3600.0 > 24"
            if self.is_postgres
            else "(julianday('now') - julianday(updated_at)) * 24.0 > 24"
        )

        with self._connect() as conn:
            total_row = conn.execute(f"SELECT COUNT(*) AS c FROM review_items {where}", tuple(params)).fetchone()
            statuses = conn.execute(
                f"""
                SELECT status, COUNT(*) AS c
                FROM review_items
                {where}
                GROUP BY status
                """,
                tuple(params),
            ).fetchall()
            avg_row = conn.execute(
                f"""
                SELECT {avg_expr} AS avg_minutes
                FROM review_items
                {where_and} status IN ('answered_auto', 'answered_manual')
                """,
                tuple(params),
            ).fetchone()
            overdue_row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM review_items
                {where_and}
                    status = 'queued_for_operator'
                    AND {overdue_expr}
                """,
                tuple(params),
            ).fetchone()

        status_map = {str(row["status"]): int(row["c"]) for row in statuses}
        avg_minutes = float(avg_row["avg_minutes"]) if avg_row and avg_row["avg_minutes"] is not None else 0.0
        return {
            "total_reviews": int(total_row["c"]) if total_row else 0,
            "status_counts": status_map,
            "avg_first_response_minutes": round(avg_minutes, 2),
            "overdue_manual_queue_24h": int(overdue_row["c"]) if overdue_row else 0,
        }

    def get_user_analytics(self, *, user_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status IN ('answered_auto', 'answered_manual', 'ignored') THEN 1 ELSE 0 END) AS processed,
                    SUM(CASE WHEN sentiment_label = 'positive' THEN 1 ELSE 0 END) AS positive_count,
                    SUM(CASE WHEN sentiment_label = 'negative' THEN 1 ELSE 0 END) AS negative_count
                FROM review_items
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            conversation_totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_items,
                    SUM(CASE WHEN kind = 'question' THEN 1 ELSE 0 END) AS questions_count,
                    SUM(CASE WHEN kind = 'chat' THEN 1 ELSE 0 END) AS chats_count
                FROM conversation_items
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        total_reviews = int(totals["total"] or 0) if totals else 0
        processed_reviews = int(totals["processed"] or 0) if totals else 0
        positive_count = int(totals["positive_count"] or 0) if totals else 0
        negative_count = int(totals["negative_count"] or 0) if totals else 0

        positive_percent = round((positive_count / total_reviews) * 100, 2) if total_reviews else 0.0
        negative_percent = round((negative_count / total_reviews) * 100, 2) if total_reviews else 0.0

        return {
            "total_reviews": total_reviews,
            "processed_reviews": processed_reviews,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "positive_percent": positive_percent,
            "negative_percent": negative_percent,
            "conversation_total": int(conversation_totals["total_items"] or 0) if conversation_totals else 0,
            "questions_count": int(conversation_totals["questions_count"] or 0) if conversation_totals else 0,
            "chats_count": int(conversation_totals["chats_count"] or 0) if conversation_totals else 0,
        }

    def raw_fetch(self, query: str, params: tuple[Any, ...] = ()) -> list[Mapping[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]
