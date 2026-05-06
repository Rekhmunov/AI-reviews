from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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

TEMPLATE_VARIABLE_KEY_RE = re.compile(r"^%[A-Z0-9_]{2,50}%$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_subgroup_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _build_subgroup_id(group_id: str, subgroup: str) -> str:
    clean_group = str(group_id or "").strip().lower().replace(" ", "_").replace("-", "_")
    normalized_subgroup = _normalize_subgroup_name(subgroup)
    digest = hashlib.sha1(f"{clean_group}|{normalized_subgroup}".encode("utf-8")).hexdigest()[:12]
    return f"{clean_group}__{digest}"


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


def _date_from_created_at_with_lookback(created_at: object, lookback_days: int) -> str:
    lookback = max(int(lookback_days), 0)
    if isinstance(created_at, datetime):
        dt = created_at
    else:
        raw = str(created_at or "").strip()
        if not raw:
            dt = datetime.now(UTC)
        else:
            normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            try:
                dt = datetime.fromisoformat(normalized)
            except ValueError:
                dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    base_date = dt.astimezone(UTC).date()
    return (base_date - timedelta(days=lookback)).isoformat()


def _parse_datetime_utc(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


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
        normalized_query = _replace_qmark_placeholders(query)
        # Pass query without params when there are none: this avoids psycopg
        # placeholder parsing for SQL literals like '%BRAND%' in seed scripts.
        if params:
            cur.execute(normalized_query, params)
        else:
            cur.execute(normalized_query)
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

    def _bool_true_literal(self) -> str:
        return "TRUE" if self.is_postgres else "1"

    def _json_param(self, value: object) -> object:
        return json.dumps(value, ensure_ascii=False)

    def _default_sync_lookback_days(self) -> int:
        return 7

    def _coerce_lookback_days(self, value: object | None) -> int:
        try:
            parsed = int(value) if value is not None else self._default_sync_lookback_days()
        except (TypeError, ValueError):
            parsed = self._default_sync_lookback_days()
        return min(max(parsed, 0), 365)

    @staticmethod
    def _is_effective_paid_status(status: object) -> bool:
        normalized = str(status or "").strip().lower()
        return normalized in {"paid", "succeeded", "success", "completed"}

    def _init_schema(self) -> None:
        if self.is_postgres:
            sql_path = Path(__file__).resolve().parent.parent / "deploy" / "postgres" / "schema_v1.sql"
            if not sql_path.exists():
                raise RuntimeError(f"PostgreSQL schema file not found: {sql_path}")
            schema_sql = sql_path.read_text(encoding="utf-8")
            # psycopg interprets "%" markers in query text as placeholders even
            # when executing raw SQL scripts. Escape percent literals such as
            # %BRAND%/%NAME% used in seed data to keep bootstrap stable.
            schema_sql = schema_sql.replace("%", "%%")
            with self._connect() as conn:
                conn.execute(schema_sql)
                self._migrate_schema(conn)
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
                    owner_user_id INTEGER,
                    is_super_admin INTEGER NOT NULL DEFAULT 0,
                    is_blocked INTEGER NOT NULL DEFAULT 0,
                    blocked_reason TEXT,
                    blocked_at TEXT,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT,
                    plan_code TEXT NOT NULL DEFAULT 'starter',
                    limits_override_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL
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
                CREATE TABLE IF NOT EXISTS manager_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    manager_user_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    can_reviews INTEGER NOT NULL DEFAULT 0,
                    can_questions INTEGER NOT NULL DEFAULT 0,
                    can_chats INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(manager_user_id, account_id),
                    FOREIGN KEY (manager_user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (account_id) REFERENCES marketplace_accounts(id) ON DELETE CASCADE
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
                CREATE TABLE IF NOT EXISTS default_template_variants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    subgroup TEXT NOT NULL,
                    template_text TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(group_id, subgroup, template_text)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS default_template_subgroups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    subgroup TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(group_id, subgroup)
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
                    send_error_code TEXT,
                    send_error_message TEXT,
                    send_attempts INTEGER NOT NULL DEFAULT 0,
                    last_send_attempt_at TEXT,
                    last_sent_at TEXT,
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
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_uid TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    operator_name TEXT,
                    send_status TEXT NOT NULL DEFAULT 'sent',
                    send_error_code TEXT,
                    send_error_message TEXT,
                    idempotency_key TEXT,
                    external_message_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, conversation_uid, idempotency_key),
                    FOREIGN KEY (conversation_uid) REFERENCES conversation_items(conversation_uid) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_quick_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    template_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payment_provider TEXT NOT NULL DEFAULT 'manual',
                    payment_api_key_encrypted TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tariff_plans (
                    code TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    monthly_price REAL NOT NULL DEFAULT 0,
                    limits_json TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'RUB',
                    status TEXT NOT NULL,
                    external_payment_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    paid_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS template_variables (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    var_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT,
                    is_user_editable INTEGER NOT NULL DEFAULT 0,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_path TEXT,
                    default_value TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_template_variable_values (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    variable_id INTEGER NOT NULL,
                    value TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, variable_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (variable_id) REFERENCES template_variables(id) ON DELETE CASCADE
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
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
                ON conversation_messages(conversation_uid, created_at ASC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_quick_templates_user
                ON chat_quick_templates(user_id, updated_at DESC)
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
                CREATE INDEX IF NOT EXISTS idx_default_template_variants_group_sub
                ON default_template_variants(group_id, subgroup, is_active)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_default_template_subgroups_group_sub
                ON default_template_subgroups(group_id, subgroup)
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
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_template_variables_active
                ON template_variables(is_active, var_key)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_template_values_user
                ON user_template_variable_values(user_id, variable_id)
                """
            )
            self._migrate_schema(conn)
            conn.execute(
                """
                INSERT INTO ai_settings (
                    id, provider, yandex_api_key_encrypted, yandex_folder_id, yandex_model_uri,
                    group_processors_json, use_sync_start_date, sync_start_date, updated_at
                )
                VALUES (1, 'rules', NULL, NULL, NULL, ?, 0, NULL, ?)
                ON CONFLICT (id) DO NOTHING
                """,
                (self._json_param(DEFAULT_GROUP_PROCESSORS), _utc_now()),
            )
            conn.execute(
                """
                INSERT INTO platform_settings (id, payment_provider, payment_api_key_encrypted, updated_at)
                VALUES (1, 'manual', NULL, ?)
                ON CONFLICT (id) DO NOTHING
                """,
                (_utc_now(),),
            )
            # Tariffs are fully managed by super-admin in UI/API.
            # Do not auto-seed built-in plans here: deleted plans must stay deleted.
        # Template variables are fully managed by super-admin (no hardcoded defaults).

    def _migrate_schema(self, conn) -> None:
        if self.is_postgres:
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS blocked_reason TEXT
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS plan_code TEXT NOT NULL DEFAULT 'starter'
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS limits_override_json JSONB NOT NULL DEFAULT '{}'::jsonb
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS use_sync_start_date BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS sync_start_date DATE
                """
            )
            conn.execute(
                """
                UPDATE users
                SET owner_user_id = id
                WHERE owner_user_id IS NULL
                """
            )
            super_admin_row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_super_admin = TRUE").fetchone()
            has_super_admin = int(super_admin_row["c"]) > 0 if super_admin_row else False
            if not has_super_admin:
                candidate = conn.execute(
                    "SELECT id FROM users WHERE role = 'admin' AND is_deleted = FALSE ORDER BY id ASC LIMIT 1"
                ).fetchone()
                if candidate is not None:
                    conn.execute(
                        "UPDATE users SET is_super_admin = TRUE WHERE id = ?",
                        (int(candidate["id"]),),
                    )

            conn.execute(
                """
                ALTER TABLE ai_settings
                ADD COLUMN IF NOT EXISTS group_processors_json JSONB NOT NULL DEFAULT '{}'::jsonb
                """
            )
            conn.execute(
                """
                ALTER TABLE ai_settings
                ADD COLUMN IF NOT EXISTS use_sync_start_date BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            conn.execute(
                """
                ALTER TABLE ai_settings
                ADD COLUMN IF NOT EXISTS sync_start_date DATE
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_settings (
                    id SMALLINT PRIMARY KEY CHECK (id = 1),
                    payment_provider TEXT NOT NULL DEFAULT 'manual',
                    payment_api_key_encrypted TEXT,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                ALTER TABLE platform_settings
                ADD COLUMN IF NOT EXISTS default_sync_lookback_days INTEGER NOT NULL DEFAULT 7
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tariff_plans (
                    code TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    monthly_price NUMERIC(14,2) NOT NULL DEFAULT 0,
                    limits_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_records (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    owner_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    amount NUMERIC(14,2) NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'RUB',
                    status TEXT NOT NULL,
                    external_payment_id TEXT,
                    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    paid_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenant_subscriptions (
                    owner_user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'inactive',
                    active_from TIMESTAMPTZ,
                    paid_until TIMESTAMPTZ,
                    grace_until TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manager_permissions (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    manager_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    account_id BIGINT NOT NULL REFERENCES marketplace_accounts(id) ON DELETE CASCADE,
                    can_reviews BOOLEAN NOT NULL DEFAULT FALSE,
                    can_questions BOOLEAN NOT NULL DEFAULT FALSE,
                    can_chats BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(manager_user_id, account_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_manager_permissions_manager
                ON manager_permissions(manager_user_id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS default_template_variants (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    subgroup TEXT NOT NULL,
                    template_text TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(group_id, subgroup, template_text)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS default_template_subgroups (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    subgroup_id TEXT,
                    subgroup TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(group_id, subgroup)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_default_template_variants_group_sub
                ON default_template_variants(group_id, subgroup, is_active)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_default_template_subgroups_group_sub
                ON default_template_subgroups(group_id, subgroup)
                """
            )
            subgroup_columns = self._table_columns(conn, "default_template_subgroups")
            if "subgroup_id" not in subgroup_columns:
                conn.execute("ALTER TABLE default_template_subgroups ADD COLUMN subgroup_id TEXT")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_default_template_subgroups_subgroup_id
                ON default_template_subgroups(subgroup_id)
                WHERE subgroup_id IS NOT NULL
                """
            )
            conn.execute(
                """
                INSERT INTO default_template_subgroups (group_id, subgroup, created_at, updated_at)
                SELECT DISTINCT group_id, subgroup, NOW(), NOW()
                FROM default_template_variants
                WHERE TRIM(group_id) <> '' AND TRIM(subgroup) <> ''
                ON CONFLICT (group_id, subgroup) DO NOTHING
                """
            )
            rows = conn.execute(
                """
                SELECT group_id, subgroup
                FROM default_template_subgroups
                WHERE subgroup_id IS NULL OR TRIM(subgroup_id) = ''
                ORDER BY group_id ASC, subgroup ASC
                """
            ).fetchall()
            for row in rows:
                subgroup_id = _build_subgroup_id(str(row["group_id"] or ""), str(row["subgroup"] or ""))
                conn.execute(
                    """
                    UPDATE default_template_subgroups
                    SET subgroup_id = ?, updated_at = NOW()
                    WHERE group_id = ? AND subgroup = ?
                    """,
                    (subgroup_id, str(row["group_id"] or ""), str(row["subgroup"] or "")),
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS template_variables (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    var_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT,
                    is_user_editable BOOLEAN NOT NULL DEFAULT FALSE,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_path TEXT,
                    default_value TEXT,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_template_variable_values (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    variable_id BIGINT NOT NULL REFERENCES template_variables(id) ON DELETE CASCADE,
                    value TEXT,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(user_id, variable_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_template_variables_active
                ON template_variables(is_active, var_key)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_template_values_user
                ON user_template_variable_values(user_id, variable_id)
                """
            )
            conn.execute(
                """
                INSERT INTO platform_settings (id, payment_provider, payment_api_key_encrypted, updated_at)
                VALUES (1, 'manual', NULL, NOW())
                ON CONFLICT (id) DO NOTHING
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS use_sync_start_date BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS sync_start_date DATE
                """
            )
            conn.execute(
                """
                UPDATE users
                SET use_sync_start_date = TRUE
                WHERE use_sync_start_date IS DISTINCT FROM TRUE
                """
            )
            conn.execute(
                """
                UPDATE users
                SET sync_start_date = ((created_at AT TIME ZONE 'UTC')::date - COALESCE((SELECT default_sync_lookback_days FROM platform_settings WHERE id = 1), 7))
                WHERE sync_start_date IS NULL
                """
            )
            conn.execute(
                """
                UPDATE platform_settings
                SET default_sync_lookback_days = COALESCE(default_sync_lookback_days, 7)
                WHERE id = 1
                """
            )
            conn.execute(
                """
                INSERT INTO tenant_subscriptions (owner_user_id, status, active_from, paid_until, grace_until, updated_at)
                SELECT u.id, 'active', u.created_at, NULL, NULL, NOW()
                FROM users u
                WHERE u.owner_user_id = u.id
                  AND u.is_super_admin = FALSE
                  AND u.is_deleted = FALSE
                ON CONFLICT (owner_user_id) DO NOTHING
                """
            )
            conn.execute(
                """
                ALTER TABLE conversation_items
                ADD COLUMN IF NOT EXISTS send_error_code TEXT
                """
            )
            conn.execute(
                """
                ALTER TABLE conversation_items
                ADD COLUMN IF NOT EXISTS send_error_message TEXT
                """
            )
            conn.execute(
                """
                ALTER TABLE conversation_items
                ADD COLUMN IF NOT EXISTS send_attempts INTEGER NOT NULL DEFAULT 0
                """
            )
            conn.execute(
                """
                ALTER TABLE conversation_items
                ADD COLUMN IF NOT EXISTS last_send_attempt_at TIMESTAMPTZ
                """
            )
            conn.execute(
                """
                ALTER TABLE conversation_items
                ADD COLUMN IF NOT EXISTS last_sent_at TIMESTAMPTZ
                """
            )
            # Convert last_sent_at and last_send_attempt_at from TIMESTAMPTZ to
            # TEXT so they are stored as ISO-8601 strings, consistent with
            # last_message_at and all other timestamp columns.  This makes
            # lexicographic comparisons correct and removes implicit type
            # coercion surprises.
            conn.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'conversation_items'
                          AND column_name = 'last_sent_at'
                          AND data_type = 'timestamp with time zone'
                    ) THEN
                        ALTER TABLE conversation_items
                            ALTER COLUMN last_sent_at TYPE TEXT
                            USING CASE
                                WHEN last_sent_at IS NULL THEN NULL
                                ELSE to_char(last_sent_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"')
                            END;
                    END IF;
                END;
                $$
                """
            )
            conn.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'conversation_items'
                          AND column_name = 'last_send_attempt_at'
                          AND data_type = 'timestamp with time zone'
                    ) THEN
                        ALTER TABLE conversation_items
                            ALTER COLUMN last_send_attempt_at TYPE TEXT
                            USING CASE
                                WHEN last_send_attempt_at IS NULL THEN NULL
                                ELSE to_char(last_send_attempt_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"')
                            END;
                    END IF;
                END;
                $$
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    conversation_uid TEXT NOT NULL REFERENCES conversation_items(conversation_uid) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    direction TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    operator_name TEXT,
                    send_status TEXT NOT NULL DEFAULT 'sent',
                    send_error_code TEXT,
                    send_error_message TEXT,
                    idempotency_key TEXT,
                    external_message_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (user_id, conversation_uid, idempotency_key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_quick_templates (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    template_text TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
                ON conversation_messages(conversation_uid, created_at ASC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_quick_templates_user
                ON chat_quick_templates(user_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                ALTER TABLE chat_quick_templates
                ADD COLUMN IF NOT EXISTS template_name TEXT NOT NULL DEFAULT ''
                """
            )
            # Migrate textless_ratings subgroups
            self._migrate_textless_subgroups(conn)
            # Tariff plans are not auto-created by migration to avoid restoring
            # plans that were intentionally removed by super-admin.
            return

        user_columns = self._table_columns(conn, "users")
        if "owner_user_id" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN owner_user_id INTEGER")
        if "is_super_admin" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_super_admin INTEGER NOT NULL DEFAULT 0")
        if "is_blocked" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0")
        if "blocked_reason" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN blocked_reason TEXT")
        if "blocked_at" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN blocked_at TEXT")
        if "is_deleted" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
        if "deleted_at" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")
        if "plan_code" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN plan_code TEXT NOT NULL DEFAULT 'starter'")
        if "limits_override_json" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN limits_override_json TEXT NOT NULL DEFAULT '{}'")
        if "use_sync_start_date" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN use_sync_start_date INTEGER NOT NULL DEFAULT 0")
        if "sync_start_date" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN sync_start_date TEXT")
        conn.execute("UPDATE users SET owner_user_id = id WHERE owner_user_id IS NULL")
        super_admin_row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_super_admin = TRUE").fetchone()
        has_super_admin = int(super_admin_row["c"]) > 0 if super_admin_row else False
        if not has_super_admin:
            candidate = conn.execute(
                "SELECT id FROM users WHERE role = 'admin' AND is_deleted = FALSE ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if candidate is not None:
                conn.execute(
                    "UPDATE users SET is_super_admin = TRUE WHERE id = ?",
                    (int(candidate["id"]),),
                )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payment_provider TEXT NOT NULL DEFAULT 'manual',
                payment_api_key_encrypted TEXT,
                default_sync_lookback_days INTEGER NOT NULL DEFAULT 7,
                updated_at TEXT NOT NULL
            )
            """
        )
        platform_columns = self._table_columns(conn, "platform_settings")
        if "default_sync_lookback_days" not in platform_columns:
            conn.execute("ALTER TABLE platform_settings ADD COLUMN default_sync_lookback_days INTEGER NOT NULL DEFAULT 7")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tariff_plans (
                code TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                monthly_price REAL NOT NULL DEFAULT 0,
                limits_json TEXT NOT NULL DEFAULT '{}',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'RUB',
                status TEXT NOT NULL,
                external_payment_id TEXT,
                details_json TEXT NOT NULL DEFAULT '{}',
                paid_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_subscriptions (
                owner_user_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'inactive',
                active_from TEXT,
                paid_until TEXT,
                grace_until TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manager_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manager_user_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                can_reviews INTEGER NOT NULL DEFAULT 0,
                can_questions INTEGER NOT NULL DEFAULT 0,
                can_chats INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(manager_user_id, account_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_manager_permissions_manager
            ON manager_permissions(manager_user_id)
            """
        )
        conn.execute(
            """
            INSERT INTO tenant_subscriptions (owner_user_id, status, active_from, paid_until, grace_until, updated_at)
            SELECT u.id, 'active', u.created_at, NULL, NULL, ?
            FROM users u
            WHERE u.owner_user_id = u.id
              AND u.is_super_admin = FALSE
              AND u.is_deleted = FALSE
            ON CONFLICT (owner_user_id) DO NOTHING
            """,
            (_utc_now(),),
        )
        conversation_columns = self._table_columns(conn, "conversation_items")
        if "send_error_code" not in conversation_columns:
            conn.execute("ALTER TABLE conversation_items ADD COLUMN send_error_code TEXT")
        if "send_error_message" not in conversation_columns:
            conn.execute("ALTER TABLE conversation_items ADD COLUMN send_error_message TEXT")
        if "send_attempts" not in conversation_columns:
            conn.execute("ALTER TABLE conversation_items ADD COLUMN send_attempts INTEGER NOT NULL DEFAULT 0")
        if "last_send_attempt_at" not in conversation_columns:
            conn.execute("ALTER TABLE conversation_items ADD COLUMN last_send_attempt_at TEXT")
        if "last_sent_at" not in conversation_columns:
            conn.execute("ALTER TABLE conversation_items ADD COLUMN last_sent_at TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_uid TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                message_text TEXT NOT NULL,
                operator_name TEXT,
                send_status TEXT NOT NULL DEFAULT 'sent',
                send_error_code TEXT,
                send_error_message TEXT,
                idempotency_key TEXT,
                external_message_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, conversation_uid, idempotency_key),
                FOREIGN KEY (conversation_uid) REFERENCES conversation_items(conversation_uid) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_quick_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                template_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_created
            ON conversation_messages(conversation_uid, created_at ASC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_quick_templates_user
            ON chat_quick_templates(user_id, updated_at DESC)
            """
        )
        tpl_columns = self._table_columns(conn, "chat_quick_templates")
        if "template_name" not in tpl_columns:
            conn.execute(
                "ALTER TABLE chat_quick_templates ADD COLUMN template_name TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS default_template_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                subgroup TEXT NOT NULL,
                template_text TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(group_id, subgroup, template_text)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS default_template_subgroups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                subgroup_id TEXT,
                subgroup TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(group_id, subgroup)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_default_template_variants_group_sub
            ON default_template_variants(group_id, subgroup, is_active)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_default_template_subgroups_group_sub
            ON default_template_subgroups(group_id, subgroup)
            """
        )
        subgroup_columns = self._table_columns(conn, "default_template_subgroups")
        if "subgroup_id" not in subgroup_columns:
            conn.execute("ALTER TABLE default_template_subgroups ADD COLUMN subgroup_id TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_default_template_subgroups_subgroup_id
            ON default_template_subgroups(subgroup_id)
            WHERE subgroup_id IS NOT NULL
            """
        )
        conn.execute(
            """
            INSERT INTO default_template_subgroups (group_id, subgroup, created_at, updated_at)
            SELECT DISTINCT group_id, subgroup, ?, ?
            FROM default_template_variants
            WHERE TRIM(group_id) <> '' AND TRIM(subgroup) <> ''
            ON CONFLICT (group_id, subgroup) DO NOTHING
            """,
            (_utc_now(), _utc_now()),
        )
        rows = conn.execute(
            """
            SELECT group_id, subgroup
            FROM default_template_subgroups
            WHERE subgroup_id IS NULL OR TRIM(subgroup_id) = ''
            ORDER BY group_id ASC, subgroup ASC
            """
        ).fetchall()
        now = _utc_now()
        for row in rows:
            subgroup_id = _build_subgroup_id(str(row["group_id"] or ""), str(row["subgroup"] or ""))
            conn.execute(
                """
                UPDATE default_template_subgroups
                SET subgroup_id = ?, updated_at = ?
                WHERE group_id = ? AND subgroup = ?
                """,
                (subgroup_id, now, str(row["group_id"] or ""), str(row["subgroup"] or "")),
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS template_variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                var_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT,
                is_user_editable INTEGER NOT NULL DEFAULT 0,
                source_type TEXT NOT NULL DEFAULT 'manual',
                source_path TEXT,
                default_value TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_template_variable_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                variable_id INTEGER NOT NULL,
                value TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, variable_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (variable_id) REFERENCES template_variables(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_template_variables_active
            ON template_variables(is_active, var_key)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_user_template_values_user
            ON user_template_variable_values(user_id, variable_id)
            """
        )
        conn.execute(
            """
            INSERT INTO platform_settings (id, payment_provider, payment_api_key_encrypted, default_sync_lookback_days, updated_at)
            VALUES (1, 'manual', NULL, 7, ?)
            ON CONFLICT (id) DO NOTHING
            """,
            (_utc_now(),),
        )
        conn.execute(
            """
            UPDATE platform_settings
            SET default_sync_lookback_days = COALESCE(default_sync_lookback_days, 7)
            WHERE id = 1
            """
        )
        conn.execute(
            """
            UPDATE users
            SET use_sync_start_date = 1
            WHERE use_sync_start_date IS NULL OR use_sync_start_date = 0
            """
        )
        conn.execute(
            """
            UPDATE users
            SET sync_start_date = date(substr(created_at, 1, 10), '-' || COALESCE((SELECT default_sync_lookback_days FROM platform_settings WHERE id = 1), 7) || ' days')
            WHERE sync_start_date IS NULL
            """
        )

        # Tariff plans are managed exclusively by super-admin and should not be
        # reseeded automatically during SQLite migrations.

        # Migrate textless_ratings subgroups from old 2-band structure to 5 per-star.
        self._migrate_textless_subgroups(conn)

    def _migrate_textless_subgroups(self, conn) -> None:
        """Replace legacy '1-3 звезды' / '4-5 звезд' subgroups with 5 per-star subgroups.

        Safe to run multiple times — checks for old subgroup existence first.
        Moves any templates from old subgroups to the appropriate new ones.
        """
        now = _utc_now()
        old_low = "1-3 звезды"
        old_high = "4-5 звезд"
        group_id = "textless_ratings"
        new_subgroups = ["1 звезда", "2 звезды", "3 звезды", "4 звезды", "5 звезд"]

        # Check if migration is needed (old subgroups still exist)
        old_rows = conn.execute(
            "SELECT subgroup FROM default_template_subgroups WHERE group_id = ? AND subgroup IN (?, ?)",
            (group_id, old_low, old_high),
        ).fetchall()
        if not old_rows:
            # Already migrated — just ensure new subgroups exist (upsert safely)
            for sg in new_subgroups:
                sg_id = _build_subgroup_id(group_id, sg)
                existing = conn.execute(
                    self._sql("SELECT id FROM default_template_subgroups WHERE group_id = ? AND subgroup = ?"),
                    (group_id, sg),
                ).fetchone()
                if not existing:
                    conn.execute(
                        self._sql("""
                        INSERT INTO default_template_subgroups (group_id, subgroup_id, subgroup, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """),
                        (group_id, sg_id, sg, now, now),
                    )
            return

        # Migrate templates from old low band (1-3) to stars 1, 2, 3
        low_templates = conn.execute(
            "SELECT template_text, is_active FROM default_template_variants WHERE group_id = ? AND subgroup = ?",
            (group_id, old_low),
        ).fetchall()
        # Migrate templates from old high band (4-5) to stars 4, 5
        high_templates = conn.execute(
            "SELECT template_text, is_active FROM default_template_variants WHERE group_id = ? AND subgroup = ?",
            (group_id, old_high),
        ).fetchall()

        # Create new subgroups and copy templates
        star_to_templates = {
            "1 звезда": low_templates,
            "2 звезды": low_templates,
            "3 звезды": low_templates,
            "4 звезды": high_templates,
            "5 звезд": high_templates,
        }
        for sg, templates in star_to_templates.items():
            sg_id = _build_subgroup_id(group_id, sg)
            # Delete first to avoid conflicts on both (group_id,subgroup) and subgroup_id indexes
            conn.execute(
                self._sql("DELETE FROM default_template_subgroups WHERE group_id = ? AND subgroup = ?"),
                (group_id, sg),
            )
            conn.execute(
                self._sql("DELETE FROM default_template_subgroups WHERE subgroup_id = ?"),
                (sg_id,),
            )
            conn.execute(
                self._sql("""
                INSERT INTO default_template_subgroups (group_id, subgroup_id, subgroup, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """),
                (group_id, sg_id, sg, now, now),
            )
            for tmpl_row in templates:
                text = str(tmpl_row["template_text"] if hasattr(tmpl_row, "__getitem__") else tmpl_row[0])
                is_active_val = self._bool_db(True)
                conn.execute(
                    self._sql("""
                    INSERT INTO default_template_variants (group_id, subgroup, template_text, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (group_id, subgroup, template_text) DO NOTHING
                    """),
                    (group_id, sg, text, is_active_val, now, now),
                )

        # Remove old subgroups and their templates
        for old_sg in (old_low, old_high):
            conn.execute(
                "DELETE FROM default_template_variants WHERE group_id = ? AND subgroup = ?",
                (group_id, old_sg),
            )
            conn.execute(
                "DELETE FROM default_template_subgroups WHERE group_id = ? AND subgroup = ?",
                (group_id, old_sg),
            )

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
        if "id" in data:
            try:
                data["id"] = int(data["id"])
            except (TypeError, ValueError):
                pass
        if "owner_user_id" in data and data["owner_user_id"] is not None:
            try:
                data["owner_user_id"] = int(data["owner_user_id"])
            except (TypeError, ValueError):
                pass
        if "subscription_owner_user_id" in data and data["subscription_owner_user_id"] is not None:
            try:
                data["subscription_owner_user_id"] = int(data["subscription_owner_user_id"])
            except (TypeError, ValueError):
                pass
        if "is_spam" in data:
            data["is_spam"] = bool(data["is_spam"])
        if "is_toxic" in data:
            data["is_toxic"] = bool(data["is_toxic"])
        if "is_active" in data:
            data["is_active"] = bool(data["is_active"])
        if "is_enabled" in data:
            data["is_enabled"] = bool(data["is_enabled"])
        if "is_user_editable" in data:
            data["is_user_editable"] = bool(data["is_user_editable"])
        if "use_sync_start_date" in data:
            data["use_sync_start_date"] = bool(data["use_sync_start_date"])
        if "can_reviews" in data:
            data["can_reviews"] = bool(data["can_reviews"])
        if "can_questions" in data:
            data["can_questions"] = bool(data["can_questions"])
        if "can_chats" in data:
            data["can_chats"] = bool(data["can_chats"])
        if "auto_send" in data:
            data["auto_send"] = bool(data["auto_send"])
        if "is_super_admin" in data:
            data["is_super_admin"] = bool(data["is_super_admin"])
        if "is_blocked" in data:
            data["is_blocked"] = bool(data["is_blocked"])
        if "is_deleted" in data:
            data["is_deleted"] = bool(data["is_deleted"])
        if "tags_json" in data:
            data["tags"] = _json_load(data.pop("tags_json"), [])
        if "metadata_json" in data:
            data["metadata"] = _json_load(data.pop("metadata_json"), {})
        if "extra_json" in data:
            raw = data.pop("extra_json")
            data["extra"] = _json_load(raw, {})
        if "limits_override_json" in data:
            data["limits_override"] = _json_load(data.pop("limits_override_json"), {})
        if "limits_json" in data:
            data["limits"] = _json_load(data.pop("limits_json"), {})
        if "details_json" in data:
            data["details"] = _json_load(data.pop("details_json"), {})
        if "group_processors_json" in data:
            data["group_processors"] = _json_load(data.pop("group_processors_json"), {})
        return data

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"]) if row else 0

    def count_super_admins(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_super_admin = TRUE AND is_deleted = FALSE").fetchone()
        return int(row["c"]) if row else 0

    def create_user(
        self,
        email: str,
        password_hash: str,
        role: str,
        full_name: str | None = None,
        *,
        owner_user_id: int | None = None,
        is_super_admin: bool = False,
        plan_code: str = "starter",
        limits_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        normalized_email = email.lower()
        owner_value = owner_user_id
        if owner_value is None and role in {"admin", "user", "feedback_manager"} and not is_super_admin:
            # Backward-compatible default: existing single-user flow owns itself.
            owner_value = None
        with self._connect() as conn:
            # If a legacy soft-deleted user still has this email, free the unique key.
            deleted_row = conn.execute(
                "SELECT id FROM users WHERE email = ? AND is_deleted = TRUE ORDER BY id DESC LIMIT 1",
                (normalized_email,),
            ).fetchone()
            if deleted_row is not None:
                deleted_user_id = int(deleted_row["id"])
                conn.execute(
                    "UPDATE users SET email = ? WHERE id = ?",
                    (f"deleted-user-{deleted_user_id}@deleted.local", deleted_user_id),
                )
            user_id = self._insert_and_get_id(
                conn,
                """
                INSERT INTO users (
                    email, full_name, password_hash, role, owner_user_id, is_super_admin,
                    is_blocked, blocked_reason, blocked_at, is_deleted, deleted_at,
                    plan_code, limits_override_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, FALSE, NULL, NULL, FALSE, NULL, ?, ?, ?)
                """,
                (
                    normalized_email,
                    full_name,
                    password_hash,
                    role,
                    owner_value,
                    self._bool_db(is_super_admin),
                    plan_code,
                    self._json_param(limits_override or {}),
                    now,
                ),
            )
            if owner_value is None and not is_super_admin:
                # For owner accounts created via old flows, self-own to isolate tenant data.
                conn.execute("UPDATE users SET owner_user_id = ? WHERE id = ?", (user_id, user_id))
        if not is_super_admin:
            self.ensure_tenant_subscription(owner_user_id=int(owner_value or user_id))
        if not is_super_admin:
            self.copy_default_templates_to_user(user_id=user_id, only_if_empty=True)
            self.get_user_sync_settings(user_id=user_id)
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("User creation failed")
        return user

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? AND is_deleted = FALSE",
                (email.lower(),),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ? AND is_deleted = FALSE", (user_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def update_user_role(self, *, user_id: int, role: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET role = ?
                WHERE id = ? AND is_deleted = FALSE
                """,
                (role, user_id),
            )
        return result.rowcount > 0

    def update_user_password(self, *, user_id: int, password_hash: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET password_hash = ?
                WHERE id = ? AND is_deleted = FALSE
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
        normalized_email = email.strip().lower()
        if password_hash is None:
            with self._connect() as conn:
                result = conn.execute(
                    """
                    UPDATE users
                    SET email = ?, full_name = ?
                    WHERE id = ? AND is_deleted = FALSE
                    """,
                    (normalized_email, full_name, user_id),
                )
            return result.rowcount > 0
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET email = ?, full_name = ?, password_hash = ?
                WHERE id = ? AND is_deleted = FALSE
                """,
                (normalized_email, full_name, password_hash, user_id),
            )
        return result.rowcount > 0

    def create_session(self, *, token: str, user_id: int, expires_at: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (token, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    user_id = excluded.user_id,
                    expires_at = excluded.expires_at,
                    created_at = excluded.created_at
                """,
                (token, user_id, _coerce_iso_for_storage(expires_at), now),
            )

    def get_session_user(self, token: str) -> dict[str, Any] | None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.*
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token = ?
                  AND s.expires_at > ?
                  AND u.is_deleted = FALSE
                  AND u.is_blocked = FALSE
                LIMIT 1
                """,
                (token, _coerce_iso_for_storage(now)),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def cleanup_expired_sessions(self, now_iso: str) -> int:
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (_coerce_iso_for_storage(now_iso),),
            )
        return int(result.rowcount)

    def get_ai_settings(self, *, include_secrets: bool = False) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM ai_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("AI settings row is missing")
        data = self._row_to_dict(row)
        provider = str(data.get("provider") or "rules").strip().lower() or "rules"
        encrypted_key = str(data.get("yandex_api_key_encrypted") or "")
        yandex_api_key = decrypt_secret(encrypted_key) if encrypted_key else None
        raw_group_processors = data.get("group_processors")
        if not isinstance(raw_group_processors, dict):
            raw_group_processors = {}
        group_processors = dict(DEFAULT_GROUP_PROCESSORS)
        for key, value in raw_group_processors.items():
            group_id = str(key or "").strip()
            mode = str(value or "").strip().lower()
            if not group_id:
                continue
            if mode not in {"yandex", "program"}:
                continue
            group_processors[group_id] = mode
        result: dict[str, Any] = {
            "provider": provider,
            "yandex_folder_id": str(data.get("yandex_folder_id") or "") or None,
            "yandex_model_uri": str(data.get("yandex_model_uri") or "") or None,
            "group_processors": group_processors,
            "use_sync_start_date": bool(data.get("use_sync_start_date")),
            "sync_start_date": str(data.get("sync_start_date") or "") or None,
            "has_yandex_api_key": bool(yandex_api_key),
            "yandex_api_key_preview": mask_secret(yandex_api_key),
        }
        if include_secrets:
            result["yandex_api_key"] = yandex_api_key
        return result

    def update_ai_settings(
        self,
        *,
        provider: str,
        yandex_api_key: str | None,
        yandex_folder_id: str | None,
        yandex_model_uri: str | None,
        group_processors: dict[str, str] | None = None,
        use_sync_start_date: bool = False,
        sync_start_date: str | None = None,
    ) -> None:
        normalized_provider = provider.strip().lower() or "rules"
        normalized_folder = (yandex_folder_id or "").strip() or None
        normalized_model = (yandex_model_uri or "").strip() or None
        normalized_sync_date = _coerce_iso_for_storage(sync_start_date, as_date=True) if use_sync_start_date else None

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT yandex_api_key_encrypted, group_processors_json FROM ai_settings WHERE id = 1"
            ).fetchone()
            current_key_encrypted = (
                str(existing["yandex_api_key_encrypted"] or "")
                if existing is not None and "yandex_api_key_encrypted" in existing
                else ""
            )
            current_group_processors = _json_load(
                existing["group_processors_json"] if existing is not None and "group_processors_json" in existing else {},
                {},
            )

            encrypted_value: str | None
            if yandex_api_key is None:
                encrypted_value = current_key_encrypted or None
            else:
                clean_key = yandex_api_key.strip()
                encrypted_value = encrypt_secret(clean_key) if clean_key else None

            normalized_groups = dict(DEFAULT_GROUP_PROCESSORS)
            if isinstance(current_group_processors, dict):
                for key, value in current_group_processors.items():
                    group_id = str(key or "").strip()
                    mode = str(value or "").strip().lower()
                    if not group_id or mode not in {"yandex", "program"}:
                        continue
                    normalized_groups[group_id] = mode
            if isinstance(group_processors, dict):
                for key, value in group_processors.items():
                    group_id = str(key or "").strip()
                    mode = str(value or "").strip().lower()
                    if not group_id or mode not in {"yandex", "program"}:
                        continue
                    normalized_groups[group_id] = mode

            conn.execute(
                """
                UPDATE ai_settings
                SET provider = ?,
                    yandex_api_key_encrypted = ?,
                    yandex_folder_id = ?,
                    yandex_model_uri = ?,
                    group_processors_json = ?,
                    use_sync_start_date = ?,
                    sync_start_date = ?,
                    updated_at = ?
                WHERE id = 1
                """,
                (
                    normalized_provider,
                    encrypted_value,
                    normalized_folder,
                    normalized_model,
                    self._json_param(normalized_groups),
                    self._bool_db(use_sync_start_date),
                    normalized_sync_date,
                    _utc_now(),
                ),
            )

    def list_users(
        self,
        *,
        super_admin_only: bool = False,
        owner_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["u.is_deleted = FALSE"]
        if super_admin_only:
            clauses.append("u.is_super_admin = TRUE")
        if owner_only:
            # Include both tenant owners AND super-admins who have their own
            # marketplace accounts.  Super-admins are self-owned (owner_user_id
            # = id) so the owner_user_id check is enough.
            clauses.append("u.owner_user_id = u.id")
        where_sql = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    u.id,
                    u.email,
                    u.role,
                    u.owner_user_id,
                    u.is_super_admin,
                    u.is_blocked,
                    u.blocked_reason,
                    u.blocked_at,
                    u.plan_code,
                    u.limits_override_json,
                    u.created_at,
                    s.status AS subscription_status,
                    s.active_from AS subscription_active_from,
                    s.paid_until AS subscription_paid_until,
                    s.grace_until AS subscription_grace_until
                FROM users u
                LEFT JOIN tenant_subscriptions s ON s.owner_user_id = u.owner_user_id
                WHERE {where_sql}
                ORDER BY u.id ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_tenant_users(self, *, owner_user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    u.id,
                    u.email,
                    u.full_name,
                    u.role,
                    u.owner_user_id,
                    u.is_blocked,
                    u.blocked_reason,
                    u.blocked_at,
                    u.plan_code,
                    u.created_at,
                    s.status AS subscription_status,
                    s.active_from AS subscription_active_from,
                    s.paid_until AS subscription_paid_until,
                    s.grace_until AS subscription_grace_until
                FROM users u
                LEFT JOIN tenant_subscriptions s ON s.owner_user_id = u.owner_user_id
                WHERE u.owner_user_id = ? AND u.is_deleted = FALSE AND u.is_super_admin = FALSE
                ORDER BY u.id ASC
                """,
                (owner_user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_manager_permissions(self, *, manager_user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, manager_user_id, account_id, can_reviews, can_questions, can_chats, created_at, updated_at
                FROM manager_permissions
                WHERE manager_user_id = ?
                ORDER BY account_id ASC
                """,
                (manager_user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def replace_manager_permissions(
        self,
        *,
        manager_user_id: int,
        permissions: list[dict[str, Any]],
    ) -> int:
        now = _utc_now()
        normalized_rows: list[dict[str, Any]] = []
        seen_accounts: set[int] = set()
        for raw in permissions:
            try:
                account_id = int(raw.get("account_id"))
            except (TypeError, ValueError):
                continue
            if account_id <= 0 or account_id in seen_accounts:
                continue
            seen_accounts.add(account_id)
            can_reviews = bool(raw.get("can_reviews"))
            can_questions = bool(raw.get("can_questions"))
            can_chats = bool(raw.get("can_chats"))
            if not (can_reviews or can_questions or can_chats):
                continue
            normalized_rows.append(
                {
                    "account_id": account_id,
                    "can_reviews": can_reviews,
                    "can_questions": can_questions,
                    "can_chats": can_chats,
                }
            )

        with self._connect() as conn:
            conn.execute("DELETE FROM manager_permissions WHERE manager_user_id = ?", (manager_user_id,))
            for row in normalized_rows:
                conn.execute(
                    """
                    INSERT INTO manager_permissions (
                        manager_user_id, account_id, can_reviews, can_questions, can_chats, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        manager_user_id,
                        int(row["account_id"]),
                        self._bool_db(bool(row["can_reviews"])),
                        self._bool_db(bool(row["can_questions"])),
                        self._bool_db(bool(row["can_chats"])),
                        now,
                        now,
                    ),
                )
        return len(normalized_rows)

    @staticmethod
    def _add_days_iso(base_iso: str, *, days: int) -> str:
        raw = str(base_iso or "").strip()
        if not raw:
            base_dt = datetime.now(UTC)
        else:
            normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            try:
                base_dt = datetime.fromisoformat(normalized)
            except ValueError:
                base_dt = datetime.now(UTC)
        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=UTC)
        return (base_dt.astimezone(UTC) + timedelta(days=max(int(days), 0))).isoformat()

    def get_tenant_subscription(self, *, owner_user_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT owner_user_id, status, active_from, paid_until, grace_until, updated_at
                FROM tenant_subscriptions
                WHERE owner_user_id = ?
                """,
                (owner_user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def ensure_tenant_subscription(self, *, owner_user_id: int) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_subscriptions (owner_user_id, status, active_from, paid_until, grace_until, updated_at)
                VALUES (?, 'inactive', ?, NULL, NULL, ?)
                ON CONFLICT (owner_user_id) DO NOTHING
                """,
                (owner_user_id, now, now),
            )
        subscription = self.get_tenant_subscription(owner_user_id=owner_user_id)
        if subscription is None:
            raise RuntimeError("Subscription initialization failed")
        return subscription

    def extend_tenant_subscription_after_payment(
        self,
        *,
        owner_user_id: int,
        months: int = 1,
        grace_days: int = 3,
    ) -> dict[str, Any]:
        subscription = self.ensure_tenant_subscription(owner_user_id=owner_user_id)
        now_iso = _utc_now()
        now_dt = _parse_datetime_utc(now_iso) or datetime.now(UTC)
        paid_until_current = _parse_datetime_utc(subscription.get("paid_until"))
        base_dt = paid_until_current if paid_until_current and paid_until_current > now_dt else now_dt
        next_paid_until = (base_dt + timedelta(days=max(int(months), 1) * 30)).isoformat()
        grace_until = self._add_days_iso(next_paid_until, days=max(int(grace_days), 0))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tenant_subscriptions
                SET status = 'active', paid_until = ?, grace_until = ?, updated_at = ?
                WHERE owner_user_id = ?
                """,
                (next_paid_until, grace_until, now_iso, owner_user_id),
            )
        updated = self.get_tenant_subscription(owner_user_id=owner_user_id)
        if updated is None:
            raise RuntimeError("Subscription extension failed")
        return updated

    def create_tenant_user(
        self,
        *,
        owner_user_id: int,
        email: str,
        password_hash: str,
        role: str,
        full_name: str | None = None,
    ) -> dict[str, Any]:
        return self.create_user(
            email=email,
            password_hash=password_hash,
            role=role,
            full_name=full_name,
            owner_user_id=owner_user_id,
            is_super_admin=False,
        )

    def set_user_blocked(
        self,
        *,
        user_id: int,
        blocked: bool,
        reason: str | None = None,
    ) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET is_blocked = ?, blocked_reason = ?, blocked_at = ?
                WHERE id = ? AND is_deleted = FALSE
                """,
                (
                    self._bool_db(blocked),
                    (reason or "").strip() or None if blocked else None,
                    _utc_now() if blocked else None,
                    user_id,
                ),
            )
        return result.rowcount > 0

    def soft_delete_user(self, *, user_id: int) -> bool:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT email FROM users WHERE id = ? AND is_deleted = FALSE",
                (user_id,),
            ).fetchone()
            if existing is None:
                return False
            # Keep unique constraint on users.email reusable for future accounts.
            deleted_email = f"deleted-user-{int(user_id)}@deleted.local"
            result = conn.execute(
                """
                UPDATE users
                SET email = ?, is_deleted = TRUE, deleted_at = ?, is_blocked = TRUE
                WHERE id = ? AND is_deleted = FALSE
                """,
                (deleted_email, _utc_now(), user_id),
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return result.rowcount > 0

    def list_tariff_plans(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT code, title, monthly_price, limits_json, is_active, created_at, updated_at
                FROM tariff_plans
                ORDER BY monthly_price ASC, code ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_tariff_plan(
        self,
        *,
        code: str,
        title: str,
        monthly_price: float,
        limits: dict[str, Any],
        is_active: bool = True,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tariff_plans (code, title, monthly_price, limits_json, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (code) DO UPDATE SET
                    title = excluded.title,
                    monthly_price = excluded.monthly_price,
                    limits_json = excluded.limits_json,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    code,
                    title,
                    monthly_price,
                    self._json_param(limits),
                    self._bool_db(is_active),
                    now,
                    now,
                ),
            )

    def delete_tariff_plan(self, *, code: str) -> tuple[bool, int]:
        normalized_code = (code or "").strip().lower()
        if not normalized_code:
            return False, 0
        with self._connect() as conn:
            in_use_row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM users
                WHERE plan_code = ?
                  AND is_deleted = FALSE
                  AND is_super_admin = FALSE
                """,
                (normalized_code,),
            ).fetchone()
            in_use_count = int(in_use_row["c"]) if in_use_row else 0
            if in_use_count > 0:
                return False, in_use_count
            result = conn.execute("DELETE FROM tariff_plans WHERE code = ?", (normalized_code,))
        return result.rowcount > 0, 0

    def set_tenant_plan(
        self,
        *,
        owner_user_id: int,
        plan_code: str,
        limits_override: dict[str, Any] | None = None,
    ) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET plan_code = ?, limits_override_json = ?
                WHERE id = ? AND is_deleted = FALSE AND is_super_admin = FALSE
                """,
                (plan_code, self._json_param(limits_override or {}), owner_user_id),
            )
        return result.rowcount > 0

    def get_super_admin_settings(self) -> dict[str, Any]:
        ai = self.get_ai_settings()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM platform_settings WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("platform_settings row is missing")
        data = self._row_to_dict(row)
        encrypted_key = str(data.get("payment_api_key_encrypted") or "")
        payment_key = decrypt_secret(encrypted_key) if encrypted_key else None
        data["has_payment_api_key"] = bool(payment_key)
        data["payment_api_key_preview"] = mask_secret(payment_key)
        data["ai"] = ai
        data["default_sync_lookback_days"] = self._coerce_lookback_days(data.get("default_sync_lookback_days"))
        return data

    def get_default_sync_lookback_days(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT default_sync_lookback_days FROM platform_settings WHERE id = 1").fetchone()
        if row is None:
            return self._default_sync_lookback_days()
        return self._coerce_lookback_days(row["default_sync_lookback_days"])

    def set_default_sync_lookback_days(self, *, days: int) -> None:
        normalized_days = self._coerce_lookback_days(days)
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO platform_settings (id, payment_provider, payment_api_key_encrypted, default_sync_lookback_days, updated_at)
                VALUES (1, 'manual', NULL, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    default_sync_lookback_days = excluded.default_sync_lookback_days,
                    updated_at = excluded.updated_at
                """,
                (normalized_days, now),
            )

    def save_super_admin_settings(
        self,
        *,
        payment_provider: str,
        payment_api_key: str | None,
        ai_provider: str,
        yandex_api_key: str | None,
        yandex_folder_id: str | None,
        yandex_model_uri: str | None,
        group_processors: dict[str, str] | None = None,
        use_sync_start_date: bool = False,
        sync_start_date: str | None = None,
        default_sync_lookback_days: int | None = None,
    ) -> None:
        self.update_ai_settings(
            provider=ai_provider,
            yandex_api_key=yandex_api_key,
            yandex_folder_id=yandex_folder_id,
            yandex_model_uri=yandex_model_uri,
            group_processors=group_processors,
            use_sync_start_date=use_sync_start_date,
            sync_start_date=sync_start_date,
        )
        now = _utc_now()
        lookback_days = self._coerce_lookback_days(default_sync_lookback_days)
        with self._connect() as conn:
            if payment_api_key is None:
                current = conn.execute(
                    "SELECT payment_api_key_encrypted FROM platform_settings WHERE id = 1"
                ).fetchone()
                encrypted_payment = (
                    str(current["payment_api_key_encrypted"] or "") if current else ""
                )
                encrypted_value = encrypted_payment or None
            else:
                encrypted_value = encrypt_secret(payment_api_key.strip())
            conn.execute(
                """
                UPDATE platform_settings
                SET payment_provider = ?, payment_api_key_encrypted = ?, default_sync_lookback_days = ?, updated_at = ?
                WHERE id = 1
                """,
                (payment_provider, encrypted_value, lookback_days, now),
            )

    def get_user_sync_settings(self, *, user_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT use_sync_start_date, sync_start_date, created_at
                FROM users
                WHERE id = ? AND is_deleted = ?
                """,
                (user_id, self._bool_db(False)),
            ).fetchone()
            if row is None:
                raise RuntimeError("User not found")
            lookback_row = conn.execute(
                "SELECT default_sync_lookback_days FROM platform_settings WHERE id = 1"
            ).fetchone()
        lookback_days = self._coerce_lookback_days(lookback_row["default_sync_lookback_days"] if lookback_row else None)
        use_sync_start_date = bool(row["use_sync_start_date"])
        sync_start_date = _coerce_iso_for_storage(str(row["sync_start_date"] or ""), as_date=True)
        if not sync_start_date:
            created_at = _coerce_iso_for_storage(str(row["created_at"] or ""))
            base = datetime.now(UTC)
            if created_at:
                try:
                    base = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    base = datetime.now(UTC)
            sync_start_date = (base - timedelta(days=lookback_days)).date().isoformat()
            use_sync_start_date = True
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET use_sync_start_date = ?, sync_start_date = ?
                    WHERE id = ? AND is_deleted = ?
                    """,
                    (self._bool_db(True), sync_start_date, user_id, self._bool_db(False)),
                )
        return {
            "use_sync_start_date": use_sync_start_date,
            "sync_start_date": sync_start_date,
            "default_sync_lookback_days": lookback_days,
        }

    def save_user_sync_settings(
        self,
        *,
        user_id: int,
        use_sync_start_date: bool,
        sync_start_date: str | None,
    ) -> bool:
        normalized_date = _coerce_iso_for_storage(sync_start_date, as_date=True) if use_sync_start_date else None
        if use_sync_start_date and not normalized_date:
            settings = self.get_user_sync_settings(user_id=user_id)
            normalized_date = str(settings.get("sync_start_date") or "")
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE users
                SET use_sync_start_date = ?, sync_start_date = ?
                WHERE id = ? AND is_deleted = FALSE
                """,
                (self._bool_db(use_sync_start_date), normalized_date, user_id),
            )
        return result.rowcount > 0

    def save_payment_record(
        self,
        *,
        owner_user_id: int,
        amount: float,
        currency: str = "RUB",
        status: str = "pending",
        external_payment_id: str | None = None,
        details: dict[str, Any] | None = None,
        paid_at: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            payment_id = self._insert_and_get_id(
                conn,
                """
                INSERT INTO payment_records (
                    owner_user_id, amount, currency, status, external_payment_id, details_json, paid_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_user_id,
                    float(amount),
                    currency,
                    status,
                    external_payment_id,
                    self._json_param(details or {}),
                    paid_at,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM payment_records WHERE id = ?", (payment_id,)).fetchone()
        if row is None:
            raise RuntimeError("Payment record creation failed")
        return self._row_to_dict(row)

    def save_payment_record_with_subscription_update(
        self,
        *,
        owner_user_id: int,
        amount: float,
        currency: str = "RUB",
        status: str = "pending",
        external_payment_id: str | None = None,
        details: dict[str, Any] | None = None,
        paid_at: str | None = None,
        months: int = 1,
        grace_days: int = 3,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_status = str(status or "").strip().lower() or "pending"
        payment = self.save_payment_record(
            owner_user_id=owner_user_id,
            amount=amount,
            currency=currency,
            status=normalized_status,
            external_payment_id=external_payment_id,
            details=details,
            paid_at=paid_at,
        )
        subscription = self.ensure_tenant_subscription(owner_user_id=owner_user_id)
        if self._is_effective_paid_status(normalized_status):
            subscription = self.extend_tenant_subscription_after_payment(
                owner_user_id=owner_user_id,
                months=months,
                grace_days=grace_days,
            )
        return payment, subscription

    def list_billing_records(self, *, owner_user_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_user_id is not None:
            clauses.append("owner_user_id = ?")
            params.append(owner_user_id)
        query = "SELECT * FROM payment_records"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete_payment_record(self, *, payment_id: int) -> bool:
        with self._connect() as conn:
            result = conn.execute("DELETE FROM payment_records WHERE id = ?", (payment_id,))
        return result.rowcount > 0

    def list_tenants_overview(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    u.id,
                    u.email,
                    u.full_name,
                    u.plan_code,
                    u.is_blocked,
                    u.created_at,
                    COALESCE(stats.reviews_count, 0) AS reviews_count,
                    COALESCE(stats.members_count, 0) AS members_count
                FROM users u
                LEFT JOIN (
                    SELECT
                        owner.id AS owner_id,
                        COUNT(DISTINCT ri.review_uid) AS reviews_count,
                        COUNT(DISTINCT member.id) AS members_count
                    FROM users owner
                    LEFT JOIN users member ON member.owner_user_id = owner.id AND member.is_deleted = FALSE
                    LEFT JOIN review_items ri ON ri.user_id = member.id
                    WHERE owner.owner_user_id = owner.id
                      AND owner.is_deleted = FALSE
                      AND owner.is_super_admin = FALSE
                    GROUP BY owner.id
                ) stats ON stats.owner_id = u.id
                WHERE u.owner_user_id = u.id
                  AND u.is_deleted = FALSE
                  AND u.is_super_admin = FALSE
                ORDER BY u.created_at DESC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]


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

    def update_marketplace_account_extra_field(
        self,
        *,
        user_id: int,
        account_id: int,
        key: str,
        value: Any,
    ) -> bool:
        """Update a single key inside the extra_json field of a marketplace account.

        Used to persist lightweight per-account sync state (e.g. last events
        cursor) without a full account update.
        """
        account = self.get_marketplace_account(
            user_id=user_id, account_id=account_id, include_secrets=False
        )
        if account is None:
            return False
        extra = dict(account.get("extra") or {})
        extra[str(key)] = value
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE marketplace_accounts
                SET extra_json = ?, updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (self._json_param(extra), _utc_now(), user_id, account_id),
            )
        return result.rowcount > 0

    def update_marketplace_account_status(self, *, user_id: int, account_id: int, is_active: bool) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE marketplace_accounts
                SET is_active = ?, updated_at = ?
                WHERE user_id = ? AND id = ?
                """,
                (self._bool_db(is_active), _utc_now(), user_id, account_id),
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
                (user_id, category, mode, self._bool_db(bool(is_enabled)), template_text, _utc_now()),
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

    def count_default_template_variants(self, *, include_inactive: bool = False) -> int:
        query = "SELECT COUNT(*) AS c FROM default_template_variants"
        if not include_inactive:
            query += f" WHERE is_active = {self._bool_true_literal()}"
        with self._connect() as conn:
            row = conn.execute(query).fetchone()
        return int(row["c"]) if row else 0

    def count_default_template_subgroups(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM default_template_subgroups").fetchone()
        return int(row["c"]) if row else 0

    def list_default_template_subgroups(self, *, group_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if group_id:
            clauses.append("group_id = ?")
            params.append(group_id)
        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)
        query = f"""
            SELECT *
            FROM default_template_subgroups
            {where}
            ORDER BY group_id ASC, created_at ASC, subgroup ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_default_template_subgroup(self, *, group_id: str, subgroup: str) -> dict[str, Any] | None:
        clean_group = str(group_id or "").strip()
        clean_subgroup = str(subgroup or "").strip()
        if not clean_group or not clean_subgroup:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM default_template_subgroups
                WHERE group_id = ? AND subgroup = ?
                """,
                (clean_group, clean_subgroup),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def rename_default_template_subgroup(self, *, group_id: str, subgroup: str, new_subgroup: str) -> bool:
        clean_group = str(group_id or "").strip()
        clean_subgroup = str(subgroup or "").strip()
        clean_new_subgroup = str(new_subgroup or "").strip()
        if not clean_group or not clean_subgroup or not clean_new_subgroup:
            return False
        if clean_subgroup == clean_new_subgroup:
            return True
        now = _utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id
                FROM default_template_subgroups
                WHERE group_id = ? AND subgroup = ?
                """,
                (clean_group, clean_new_subgroup),
            ).fetchone()
            if existing is not None:
                return False
            subgroup_row = conn.execute(
                """
                SELECT subgroup_id
                FROM default_template_subgroups
                WHERE group_id = ? AND subgroup = ?
                """,
                (clean_group, clean_subgroup),
            ).fetchone()
            if subgroup_row is None:
                return False
            subgroup_id = str(subgroup_row.get("subgroup_id") or "").strip() if isinstance(subgroup_row, Mapping) else ""
            if not subgroup_id:
                subgroup_id = _build_subgroup_id(clean_group, clean_subgroup)
            updated_subgroups = conn.execute(
                """
                UPDATE default_template_subgroups
                SET subgroup = ?, subgroup_id = ?, updated_at = ?
                WHERE group_id = ? AND subgroup = ?
                """,
                (clean_new_subgroup, subgroup_id, now, clean_group, clean_subgroup),
            )
            if int(updated_subgroups.rowcount or 0) <= 0:
                return False
            conn.execute(
                """
                UPDATE default_template_variants
                SET subgroup = ?, updated_at = ?
                WHERE group_id = ? AND subgroup = ?
                """,
                (clean_new_subgroup, now, clean_group, clean_subgroup),
            )
            conn.execute(
                """
                UPDATE response_template_variants
                SET subgroup = ?, updated_at = ?
                WHERE group_id = ? AND subgroup = ?
                """,
                (clean_new_subgroup, now, clean_group, clean_subgroup),
            )
        return True

    def ensure_default_template_subgroups(self, rows: list[dict[str, str]]) -> int:
        now = _utc_now()
        touched = 0
        with self._connect() as conn:
            for item in rows:
                group_id = str(item.get("group_id") or "").strip()
                subgroup = str(item.get("subgroup") or "").strip()
                if not group_id or not subgroup:
                    continue
                subgroup_id = _build_subgroup_id(group_id, subgroup)
                result = conn.execute(
                    """
                    INSERT INTO default_template_subgroups (group_id, subgroup_id, subgroup, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(group_id, subgroup) DO UPDATE SET
                        subgroup_id = COALESCE(default_template_subgroups.subgroup_id, excluded.subgroup_id),
                        updated_at = excluded.updated_at
                    """,
                    (group_id, subgroup_id, subgroup, now, now),
                )
                touched += int(result.rowcount or 0)
        return touched

    def sync_default_template_subgroups_from_variants(self) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT group_id, subgroup
                FROM default_template_variants
                WHERE TRIM(group_id) <> '' AND TRIM(subgroup) <> ''
                """
            ).fetchall()
        payload = [
            {
                "group_id": str(row["group_id"] or "").strip(),
                "subgroup": str(row["subgroup"] or "").strip(),
            }
            for row in rows
        ]
        return self.ensure_default_template_subgroups(payload)

    def add_default_template_subgroup(self, *, group_id: str, subgroup: str) -> dict[str, Any]:
        group_id = group_id.strip()
        subgroup = subgroup.strip()
        if not group_id or not subgroup:
            raise ValueError("group_id and subgroup are required")
        now = _utc_now()
        subgroup_id = _build_subgroup_id(group_id, subgroup)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO default_template_subgroups (group_id, subgroup_id, subgroup, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_id, subgroup) DO UPDATE SET
                    subgroup_id = COALESCE(default_template_subgroups.subgroup_id, excluded.subgroup_id),
                    updated_at = excluded.updated_at
                """,
                (group_id, subgroup_id, subgroup, now, now),
            )
            row = conn.execute(
                """
                SELECT *
                FROM default_template_subgroups
                WHERE group_id = ? AND subgroup = ?
                """,
                (group_id, subgroup),
            ).fetchone()
        if row is None:
            raise RuntimeError("Default template subgroup creation failed")
        return self._row_to_dict(row)

    def delete_default_template_subgroup(self, *, group_id: str, subgroup: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM default_template_variants
                WHERE group_id = ? AND subgroup = ?
                """,
                (group_id, subgroup),
            )
            result = conn.execute(
                """
                DELETE FROM default_template_subgroups
                WHERE group_id = ? AND subgroup = ?
                """,
                (group_id, subgroup),
            )
        return result.rowcount > 0

    def seed_default_templates_from_user_templates(self) -> int:
        with self._connect() as conn:
            source = conn.execute(
                """
                SELECT user_id, COUNT(*) AS c
                FROM response_template_variants
                GROUP BY user_id
                ORDER BY c DESC, user_id ASC
                LIMIT 1
                """
            ).fetchone()
            if source is None:
                return 0
            rows = conn.execute(
                """
                SELECT group_id, subgroup, template_text
                FROM response_template_variants
                WHERE user_id = ? AND is_active = ?
                ORDER BY group_id ASC, subgroup ASC, id ASC
                """,
                (int(source["user_id"]), self._bool_db(True)),
            ).fetchall()
            inserted = 0
            now = _utc_now()
            for row in rows:
                result = conn.execute(
                    """
                    INSERT INTO default_template_variants (
                        group_id, subgroup, template_text, is_active, created_at, updated_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM default_template_variants
                        WHERE group_id = ? AND subgroup = ? AND template_text = ?
                    )
                    """,
                    (
                        str(row["group_id"] or ""),
                        str(row["subgroup"] or ""),
                        str(row["template_text"] or ""),
                        self._bool_db(True),
                        now,
                        now,
                        str(row["group_id"] or ""),
                        str(row["subgroup"] or ""),
                        str(row["template_text"] or ""),
                    ),
                )
                inserted += int(result.rowcount or 0)
        return inserted

    def seed_default_template_variants(self, rows: list[dict[str, str]]) -> int:
        now = _utc_now()
        inserted = 0
        with self._connect() as conn:
            for item in rows:
                group_id = str(item.get("group_id") or "").strip()
                subgroup = str(item.get("subgroup") or "").strip()
                text = str(item.get("template_text") or "").strip()
                if not group_id or not subgroup or not text:
                    continue
                result = conn.execute(
                    """
                    INSERT INTO default_template_variants (
                        group_id, subgroup, template_text, is_active, created_at, updated_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM default_template_variants
                        WHERE group_id = ? AND subgroup = ? AND template_text = ?
                    )
                    """,
                    (
                        group_id,
                        subgroup,
                        text,
                        self._bool_db(True),
                        now,
                        now,
                        group_id,
                        subgroup,
                        text,
                    ),
                )
                inserted += int(result.rowcount or 0)
        return inserted

    def list_default_template_variants(
        self,
        *,
        group_id: str | None = None,
        subgroup: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if group_id:
            clauses.append("group_id = ?")
            params.append(group_id)
        if subgroup:
            clauses.append("subgroup = ?")
            params.append(subgroup)
        if not include_inactive:
            clauses.append(f"is_active = {self._bool_true_literal()}")
        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)
        query = f"""
            SELECT *
            FROM default_template_variants
            {where}
            ORDER BY group_id ASC, subgroup ASC, id ASC
        """
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def replace_default_subgroup_templates(self, *, group_id: str, subgroup: str, templates: list[str]) -> None:
        clean = [item.strip() for item in templates if item and item.strip()]
        now = _utc_now()
        self.ensure_default_template_subgroups([{"group_id": group_id, "subgroup": subgroup}])
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM default_template_variants
                WHERE group_id = ? AND subgroup = ?
                """,
                (group_id, subgroup),
            )
            for text in clean:
                conn.execute(
                    """
                    INSERT INTO default_template_variants (
                        group_id, subgroup, template_text, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (group_id, subgroup, text, self._bool_db(True), now, now),
                )

    def add_default_template_variant(self, *, group_id: str, subgroup: str, template_text: str) -> dict[str, Any]:
        now = _utc_now()
        self.ensure_default_template_subgroups([{"group_id": group_id, "subgroup": subgroup}])
        with self._connect() as conn:
            row_id = self._insert_and_get_id(
                conn,
                """
                INSERT INTO default_template_variants (
                    group_id, subgroup, template_text, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (group_id, subgroup, template_text.strip(), self._bool_db(True), now, now),
            )
            row = conn.execute(
                "SELECT * FROM default_template_variants WHERE id = ?",
                (row_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Default template variant creation failed")
        return self._row_to_dict(row)

    def add_default_template_variants_bulk(self, *, group_id: str, subgroup: str, templates: list[str]) -> int:
        clean_unique: list[str] = []
        seen: set[str] = set()
        for item in templates:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            clean_unique.append(text)
        if not clean_unique:
            return 0
        now = _utc_now()
        inserted = 0
        self.ensure_default_template_subgroups([{"group_id": group_id, "subgroup": subgroup}])
        with self._connect() as conn:
            for text in clean_unique:
                result = conn.execute(
                    """
                    INSERT INTO default_template_variants (
                        group_id, subgroup, template_text, is_active, created_at, updated_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM default_template_variants
                        WHERE group_id = ? AND subgroup = ? AND template_text = ?
                    )
                    """,
                    (
                        group_id,
                        subgroup,
                        text,
                        self._bool_db(True),
                        now,
                        now,
                        group_id,
                        subgroup,
                        text,
                    ),
                )
                inserted += int(result.rowcount or 0)
        return inserted

    def delete_default_template_variant(self, *, template_id: int) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM default_template_variants
                WHERE id = ?
                """,
                (template_id,),
            )
        return result.rowcount > 0

    def copy_default_templates_to_user(self, *, user_id: int, only_if_empty: bool = True) -> int:
        with self._connect() as conn:
            if only_if_empty:
                existing = conn.execute(
                    "SELECT COUNT(*) AS c FROM response_template_variants WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if existing and int(existing["c"]) > 0:
                    return 0

            defaults = conn.execute(
                f"""
                SELECT group_id, subgroup, template_text
                FROM default_template_variants
                WHERE is_active = {self._bool_true_literal()}
                ORDER BY group_id ASC, subgroup ASC, id ASC
                """
            ).fetchall()
            if not defaults:
                return 0

            now = _utc_now()
            inserted = 0
            for row in defaults:
                result = conn.execute(
                    """
                    INSERT INTO response_template_variants (
                        user_id, group_id, subgroup, template_text, is_active, created_at, updated_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM response_template_variants
                        WHERE user_id = ? AND group_id = ? AND subgroup = ? AND template_text = ?
                    )
                    """,
                    (
                        user_id,
                        str(row["group_id"] or ""),
                        str(row["subgroup"] or ""),
                        str(row["template_text"] or ""),
                        self._bool_db(True),
                        now,
                        now,
                        user_id,
                        str(row["group_id"] or ""),
                        str(row["subgroup"] or ""),
                        str(row["template_text"] or ""),
                    ),
                )
                inserted += int(result.rowcount or 0)
        return inserted

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
            clauses.append(f"is_active = {self._bool_true_literal()}")
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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, group_id, subgroup, text, self._bool_db(True), now, now),
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, group_id, subgroup, template_text.strip(), self._bool_db(True), now, now),
            )
            row = conn.execute(
                "SELECT * FROM response_template_variants WHERE id = ?",
                (row_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Template variant creation failed")
        return self._row_to_dict(row)

    def get_template_variant_by_id(self, *, user_id: int, template_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM response_template_variants WHERE user_id = ? AND id = ?",
                (user_id, template_id),
            ).fetchone()
        return self._row_to_dict(row) if row else None

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
        clauses = ["user_id = ?", "group_id = ?", f"is_active = {self._bool_true_literal()}"]
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
                (user_id, group_id, action_mode, self._bool_db(auto_send), _utc_now()),
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
                        self._bool_db(bool(item.get("auto_send"))),
                        now,
                    ),
                )

    def list_recommendations(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_article, target_article
                FROM product_recommendations
                WHERE user_id = ? AND is_active = ?
                ORDER BY source_article ASC, target_article ASC
                """,
                (user_id, self._bool_db(True)),
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
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (user_id, source_raw, target, self._bool_db(True), now, now),
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
                WHERE user_id = ? AND source_article = ? AND is_active = ?
                ORDER BY RANDOM()
                LIMIT 1
                """,
                (user_id, source, self._bool_db(True)),
            ).fetchone()
        if row is None:
            return None
        target = str(row["target_article"] or "").strip()
        return target or None

    def ensure_default_template_variables(self) -> int:
        # Backward-compatible no-op: template variables are not auto-seeded.
        return 0

    def list_template_variables(self, *, only_active: bool = False) -> list[dict[str, Any]]:
        clauses: list[str] = []
        if only_active:
            clauses.append(f"is_active = {self._bool_true_literal()}")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM template_variables
                {where}
                ORDER BY var_key ASC
                """
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def upsert_template_variable(
        self,
        *,
        var_key: str,
        title: str,
        description: str | None = None,
        is_user_editable: bool,
        source_type: str,
        source_path: str | None = None,
        default_value: str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        normalized_key = var_key.strip().upper()
        if not normalized_key:
            raise ValueError("var_key is required")
        if not TEMPLATE_VARIABLE_KEY_RE.fullmatch(normalized_key):
            raise ValueError("var_key must match ^%[A-Z0-9_]{2,50}%$")
        normalized_source_type = (source_type or "").strip().lower() or "manual"
        if normalized_source_type not in {"manual", "review_field", "system"}:
            raise ValueError("source_type must be one of: manual, review_field, system")
        normalized_source_path = str(source_path or "").strip()
        if normalized_source_type in {"review_field", "system"} and not normalized_source_path:
            raise ValueError("source_path is required for review_field/system")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO template_variables (
                    var_key, title, description, is_user_editable, source_type, source_path, default_value, is_active,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (var_key) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    is_user_editable = excluded.is_user_editable,
                    source_type = excluded.source_type,
                    source_path = excluded.source_path,
                    default_value = excluded.default_value,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_key,
                    title.strip() or normalized_key,
                    str(description or ""),
                    self._bool_db(is_user_editable),
                    normalized_source_type,
                    normalized_source_path,
                    str(default_value or ""),
                    self._bool_db(is_active),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM template_variables
                WHERE var_key = ?
                LIMIT 1
                """,
                (normalized_key,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Template variable upsert failed")
        return self._row_to_dict(row)

    def delete_template_variable(self, *, var_key: str) -> bool:
        normalized_key = var_key.strip().upper()
        if not normalized_key:
            return False
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM template_variables
                WHERE var_key = ?
                """,
                (normalized_key,),
            )
        return result.rowcount > 0

    def list_user_template_variable_values(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    v.id AS variable_id,
                    v.var_key,
                    v.title,
                    v.description,
                    v.is_user_editable,
                    v.source_type,
                    v.source_path,
                    v.default_value,
                    v.is_active,
                    uv.value,
                    uv.updated_at AS value_updated_at
                FROM template_variables v
                LEFT JOIN user_template_variable_values uv
                  ON uv.variable_id = v.id
                 AND uv.user_id = ?
                WHERE v.is_active = {self._bool_true_literal()}
                ORDER BY v.var_key ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def save_user_template_variable_values(self, *, user_id: int, values: dict[str, str]) -> int:
        updates = 0
        now = _utc_now()
        normalized_values: dict[str, str] = {}
        for key, value in values.items():
            normalized_key = str(key or "").strip().upper()
            if not normalized_key:
                continue
            normalized_values[normalized_key] = str(value or "").strip()
        if not normalized_values:
            return 0
        with self._connect() as conn:
            variable_rows = conn.execute(
                """
                SELECT id, var_key, is_user_editable
                FROM template_variables
                WHERE var_key IN ({})
                """.format(",".join("?" for _ in normalized_values)),
                tuple(normalized_values.keys()),
            ).fetchall()
            for row in variable_rows:
                if not bool(row["is_user_editable"]):
                    continue
                var_key = str(row["var_key"] or "").strip().upper()
                if var_key not in normalized_values:
                    continue
                conn.execute(
                    """
                    INSERT INTO user_template_variable_values (user_id, variable_id, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (user_id, variable_id) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, int(row["id"]), normalized_values[var_key], now),
                )
                updates += 1
        return updates

    def build_template_variables_context(
        self,
        *,
        user_id: int | None,
        review_author: str | None,
        review_rating: int | str | None,
        review_category: str | None,
        review_sentiment: str | None,
        review_tags: str | list[str] | None,
        review_metadata: dict[str, Any] | None,
    ) -> dict[str, str]:
        metadata = review_metadata if isinstance(review_metadata, dict) else {}
        tags_text = ", ".join(review_tags) if isinstance(review_tags, list) else str(review_tags or "")
        # Backward-compatible defaults for historic placeholders used in templates/tests.
        default_brand = "VarFabric"
        default_name = str(review_author or "").strip()
        context: dict[str, str] = {
            "%AUTHOR%": str(review_author or "").strip() or "клиент",
            "%RATING%": str(review_rating if review_rating is not None else ""),
            "%CATEGORY%": str(review_category or ""),
            "%SENTIMENT%": str(review_sentiment or ""),
            "%TAGS%": tags_text.strip(),
            "%BRAND%": default_brand,
            "%NAME%": default_name,
        }
        if metadata:
            for key, value in metadata.items():
                key_name = str(key or "").strip().upper()
                if not key_name:
                    continue
                context[f"%META_{key_name}%"] = str(value or "").strip()

        variables = self.list_template_variables(only_active=True)
        user_values_map: dict[str, str] = {}
        if user_id is not None:
            for row in self.list_user_template_variable_values(user_id=user_id):
                value = str(row.get("value") or "").strip()
                if value:
                    user_values_map[str(row.get("var_key") or "").strip().upper()] = value

        for item in variables:
            key = str(item.get("var_key") or "").strip().upper()
            if not key:
                continue
            source_type = str(item.get("source_type") or "manual").strip().lower()
            # Backward compatibility for older rows saved as "review".
            if source_type == "review":
                source_type = "review_field"
            source_path = str(item.get("source_path") or "").strip()
            default_value = str(item.get("default_value") or "").strip()
            resolved = ""
            if source_type == "review_field":
                if source_path in {"author", "name", "author_name"}:
                    resolved = str(review_author or "").strip()
                elif source_path in {"rating"}:
                    resolved = str(review_rating if review_rating is not None else "").strip()
                elif source_path in {"category"}:
                    resolved = str(review_category or "").strip()
                elif source_path in {"sentiment"}:
                    resolved = str(review_sentiment or "").strip()
                elif source_path in {"tags"}:
                    resolved = tags_text.strip()
                elif source_path.startswith("metadata."):
                    meta_key = source_path.split(".", 1)[1].strip()
                    resolved = str(metadata.get(meta_key) or "").strip()
            elif source_type == "system":
                if source_path in {"author_name", "review_author"}:
                    resolved = str(review_author or "").strip()
                elif source_path == "review_rating":
                    resolved = str(review_rating if review_rating is not None else "").strip()
                elif source_path == "review_category":
                    resolved = str(review_category or "").strip()
                elif source_path == "review_sentiment":
                    resolved = str(review_sentiment or "").strip()
                elif source_path == "review_tags":
                    resolved = tags_text.strip()
                elif source_path.startswith("metadata."):
                    meta_key = source_path.split(".", 1)[1].strip()
                    resolved = str(metadata.get(meta_key) or "").strip()
            if source_type == "manual":
                resolved = user_values_map.get(key) or default_value
            if not resolved:
                resolved = user_values_map.get(key) or default_value
            context[key] = str(resolved or "")
        return context

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
        account_ids: list[int] | None = None,
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
            account_ids=account_ids,
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
        account_ids: list[int] | None = None,
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
        normalized_account_ids = sorted(
            {
                int(value)
                for value in (account_ids or [])
                if isinstance(value, int) or (isinstance(value, str) and str(value).strip().isdigit())
            }
        )
        if normalized_account_ids:
            placeholders = ", ".join("?" for _ in normalized_account_ids)
            base_clauses.append(f"account_id IN ({placeholders})")
            base_params.extend(normalized_account_ids)
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
        seller_replied_at: str | None = None,
        buyer_has_unread: bool = False,
    ) -> str:
        """Upsert a conversation record.

        ``seller_replied_at`` should be set to the timestamp of the seller's
        last message (from the WB events endpoint).  When provided it is written
        to ``last_sent_at``, which drives the "answered" / "needs reply" bucket
        logic:  processed_by_operator = last_sent_at IS NOT NULL AND
        last_sent_at >= last_message_at.
        Only update last_sent_at when the incoming value is newer than the
        stored one so that a manual reply from our app is never overwritten.

        ``buyer_has_unread=True`` signals that the marketplace confirmed the
        buyer has written new messages the seller has not replied to yet.
        In this case last_sent_at is cleared so the chat moves to the "New"
        bucket immediately, regardless of stored timestamps.
        """
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
                    send_error_code, send_error_message, send_attempts, last_send_attempt_at, last_sent_at,
                    last_message_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0, NULL, ?, ?, ?, ?)
                ON CONFLICT(conversation_uid) DO UPDATE SET
                    customer_name = excluded.customer_name,
                    message_text = excluded.message_text,
                    status = excluded.status,
                    unread_count = excluded.unread_count,
                    metadata_json = excluded.metadata_json,
                    send_error_code = CASE
                        WHEN excluded.last_message_at <> conversation_items.last_message_at THEN NULL
                        ELSE conversation_items.send_error_code
                    END,
                    send_error_message = CASE
                        WHEN excluded.last_message_at <> conversation_items.last_message_at THEN NULL
                        ELSE conversation_items.send_error_message
                    END,
                    send_attempts = CASE
                        WHEN excluded.last_message_at <> conversation_items.last_message_at THEN 0
                        ELSE conversation_items.send_attempts
                    END,
                    last_send_attempt_at = CASE
                        WHEN excluded.last_message_at <> conversation_items.last_message_at THEN NULL
                        ELSE conversation_items.last_send_attempt_at
                    END,
                    last_message_at = excluded.last_message_at,
                    last_sent_at = CASE
                        WHEN excluded.last_sent_at IS NULL THEN conversation_items.last_sent_at
                        WHEN conversation_items.last_sent_at IS NULL THEN excluded.last_sent_at
                        WHEN excluded.last_sent_at > conversation_items.last_sent_at THEN excluded.last_sent_at
                        ELSE conversation_items.last_sent_at
                    END,
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
                    seller_replied_at or None,
                    last_message_ts,
                    now,
                    now,
                ),
            )
            # When the marketplace confirms the buyer has unread messages
            # (newMessages > 0), force the chat to the "New" bucket by clearing
            # last_sent_at.  This is the most reliable signal — no timestamp
            # comparison needed.
            if buyer_has_unread:
                conn.execute(
                    """
                    UPDATE conversation_items
                    SET last_sent_at = NULL, updated_at = ?
                    WHERE user_id = ? AND conversation_uid = ?
                    """,
                    (now, user_id, conversation_uid),
                )
        return conversation_uid

    def list_conversations(
        self,
        *,
        user_id: int,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 200,
        account_permissions: dict[str, list[int]] | None = None,
    ) -> list[dict[str, Any]]:
        page_data = self.list_conversations_paginated(
            user_id=user_id,
            source=None,
            kind=kind,
            status=status,
            statuses=None,
            sort="newest",
            page=1,
            page_size=limit,
            bucket="all",
            account_permissions=account_permissions,
        )
        return list(page_data["items"])

    def list_conversations_paginated(
        self,
        *,
        user_id: int,
        source: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        statuses: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 30,
        bucket: str = "all",
        search: str | None = None,
        account_permissions: dict[str, list[int]] | None = None,
    ) -> dict[str, Any]:
        base_clauses: list[str] = ["user_id = ?"]
        base_params: list[Any] = [user_id]
        if source:
            base_clauses.append("source = ?")
            base_params.append(source)
        if kind:
            base_clauses.append("kind = ?")
            base_params.append(kind)
        if search:
            # Search by customer name (case-insensitive LIKE)
            base_clauses.append("LOWER(COALESCE(customer_name, '')) LIKE ?")
            base_params.append(f"%{search.strip().lower()}%")
        # Exclude completely empty chats with no activity at all.
        # WB buyer-chat list returns empty text for some chats; Ozon v3/chat/list
        # never returns message text — so we must not filter on text alone.
        # A chat is shown if it has any text OR has unread messages OR has been
        # replied to (last_sent_at IS NOT NULL = seller replied at some point).
        if kind == "chat":
            base_clauses.append(
                "(TRIM(COALESCE(message_text, '')) != '' OR unread_count > 0 OR last_sent_at IS NOT NULL)"
            )
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
        # Both last_sent_at and last_message_at are stored as ISO-8601 TEXT.
        # ISO-8601 strings with timezone sort correctly lexicographically, so
        # a plain TEXT comparison works on both SQLite and PostgreSQL.
        # We cast explicitly to TEXT in PostgreSQL to avoid implicit type
        # coercion (the column was altered to TIMESTAMPTZ in some migrations
        # but data is inserted as TEXT strings).
        if self.is_postgres:
            processed_by_operator_clause = (
                "last_sent_at IS NOT NULL "
                "AND (last_message_at IS NULL OR last_sent_at::text >= last_message_at::text)"
            )
        else:
            processed_by_operator_clause = (
                "last_sent_at IS NOT NULL "
                "AND (last_message_at IS NULL OR last_sent_at >= last_message_at)"
            )

        if account_permissions:
            permission_clauses: list[str] = []
            permission_params: list[Any] = []
            for conversation_kind in ("question", "chat"):
                ids = account_permissions.get(conversation_kind) if isinstance(account_permissions, Mapping) else None
                normalized_ids = sorted(
                    {
                        int(value)
                        for value in (ids or [])
                        if isinstance(value, int) or (isinstance(value, str) and str(value).strip().isdigit())
                    }
                )
                if not normalized_ids:
                    continue
                placeholders = ", ".join("?" for _ in normalized_ids)
                permission_clauses.append(f"(kind = ? AND account_id IN ({placeholders}))")
                permission_params.append(conversation_kind)
                permission_params.extend(normalized_ids)
            if permission_clauses:
                base_clauses.append("(" + " OR ".join(permission_clauses) + ")")
                base_params.extend(permission_params)
            else:
                base_clauses.append("1 = 0")

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
            view_clauses.append(f"NOT ({processed_by_operator_clause})")
        elif bucket == "processed":
            view_clauses.append(processed_by_operator_clause)

        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 2000)
        where_base = " AND ".join(base_clauses)
        where_view = " AND ".join(view_clauses)
        order_by_map = {
            # Sort by the actual last message timestamp from WB, not sync time.
            # COALESCE falls back to updated_at if last_message_at is NULL.
            "newest": "COALESCE(last_message_at, updated_at) DESC",
            "oldest": "COALESCE(last_message_at, updated_at) ASC",
        }
        order_by = order_by_map.get(sort.strip().lower(), order_by_map["newest"])

        with self._connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS c FROM conversation_items WHERE {where_view}",
                tuple(view_params),
            ).fetchone()
            total = int(total_row["c"]) if total_row else 0
            pages = max((total + safe_page_size - 1) // safe_page_size, 1)
            safe_page = min(safe_page, pages)
            offset = (safe_page - 1) * safe_page_size
            new_row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM conversation_items
                WHERE {where_base}
                  AND NOT ({processed_by_operator_clause})
                """,
                tuple(base_params),
            ).fetchone()
            processed_row = conn.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM conversation_items
                WHERE {where_base}
                  AND {processed_by_operator_clause}
                """,
                tuple(base_params),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT *
                FROM conversation_items
                WHERE {where_view}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                tuple([*view_params, safe_page_size, offset]),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            raw = data.pop("metadata_json", "{}")
            data["metadata"] = _json_load(raw, {})
            items.append(data)
        return {
            "items": items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "pages": pages,
            "new_count": int(new_row["c"]) if new_row else 0,
            "processed_count": int(processed_row["c"]) if processed_row else 0,
        }

    def list_conversation_sources(self, *, user_id: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT source
                FROM conversation_items
                WHERE user_id = ?
                ORDER BY source ASC
                """,
                (user_id,),
            ).fetchall()
        return [str(row["source"]) for row in rows if row["source"] is not None and str(row["source"]).strip()]

    def delete_conversations_before_date(
        self,
        *,
        user_id: int,
        account_id: int | None = None,
        kind: str | None = None,
        before_date: str,
    ) -> int:
        """Remove conversations whose last_message_at is before ``before_date``.

        Used to enforce the sync-start-date for WB chats: the WB chats list
        endpoint has no date filter, so we sync everything and then prune rows
        that are older than the configured cutoff.
        """
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(int(account_id))
        if kind:
            clauses.append("kind = ?")
            params.append(str(kind).strip().lower())
        # Compare ISO strings lexicographically - works correctly for both
        # full ISO datetimes and YYYY-MM-DD date strings.
        clauses.append("last_message_at IS NOT NULL")
        clauses.append("last_message_at < ?")
        params.append(str(before_date))
        where = " AND ".join(clauses)
        with self._connect() as conn:
            result = conn.execute(
                f"DELETE FROM conversation_items WHERE {where}", tuple(params)
            )
        return int(result.rowcount or 0)

    def clear_conversations(self, *, user_id: int, kind: str | None = None) -> int:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind in {"question", "chat"}:
            clauses.append("kind = ?")
            params.append(normalized_kind)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            result = conn.execute(f"DELETE FROM conversation_items WHERE {where}", tuple(params))
        return int(result.rowcount or 0)

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

    def move_conversation_to_new(self, *, user_id: int, conversation_uid: str) -> bool:
        """Clear last_sent_at so the chat moves to the 'New' bucket.

        Used when the operator manually moves an answered chat back to New.
        """
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE conversation_items
                SET last_sent_at = NULL, updated_at = ?
                WHERE user_id = ? AND conversation_uid = ?
                """,
                (_utc_now(), user_id, conversation_uid),
            )
        return result.rowcount > 0

    def repair_chat_answered_status(self, *, user_id: int) -> int:
        """Fix chats where metadata says last_sender=seller but last_sent_at is NULL.

        This happens when phase-2 events enrichment was interrupted.  We can
        recover without re-fetching events by reading the last_sender field
        already stored in metadata_json.
        """
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE conversation_items
                SET last_sent_at = COALESCE(last_message_at, updated_at),
                    updated_at   = updated_at
                WHERE user_id = ?
                  AND kind = 'chat'
                  AND last_sent_at IS NULL
                  AND (
                      metadata_json LIKE '%"last_sender": "seller"%'
                      OR metadata_json LIKE '%''last_sender'': ''seller''%'
                  )
                """,
                (user_id,),
            )
        return int(result.rowcount or 0)

    def update_conversation_customer_name(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        customer_name: str,
    ) -> bool:
        """Update customer_name for a conversation (used when API enriches name later)."""
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE conversation_items
                SET customer_name = ?, updated_at = ?
                WHERE user_id = ? AND conversation_uid = ?
                  AND (customer_name IS NULL OR TRIM(customer_name) = '')
                """,
                (customer_name, _utc_now(), user_id, conversation_uid),
            )
        return result.rowcount > 0

    def mark_conversation_answered(self, *, user_id: int, conversation_uid: str) -> bool:
        """Set last_sent_at = now so the chat moves to the 'answered' bucket.

        Used for ad/promo chats where the seller does not need to reply but
        wants to remove them from the 'needs reply' queue.
        """
        now = _utc_now()
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE conversation_items
                SET last_sent_at = ?, updated_at = ?
                WHERE user_id = ? AND conversation_uid = ?
                """,
                (now, now, user_id, conversation_uid),
            )
        return result.rowcount > 0

    def list_chat_quick_templates(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, template_name, template_text, created_at, updated_at
                FROM chat_quick_templates
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def add_chat_quick_template(
        self, *, user_id: int, template_text: str, template_name: str
    ) -> dict[str, Any]:
        clean_text = str(template_text or "").strip()
        clean_name = str(template_name or "").strip()
        if not clean_text:
            raise ValueError("template_text is required")
        if not clean_name:
            raise ValueError("template_name is required")
        now = _utc_now()
        with self._connect() as conn:
            template_id = self._insert_and_get_id(
                conn,
                """
                INSERT INTO chat_quick_templates (user_id, template_name, template_text, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, clean_name, clean_text, now, now),
            )
            row = conn.execute(
                """
                SELECT id, user_id, template_name, template_text, created_at, updated_at
                FROM chat_quick_templates
                WHERE id = ? AND user_id = ?
                """,
                (template_id, user_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("Chat quick template creation failed")
        return self._row_to_dict(row)

    def update_chat_quick_template(
        self,
        *,
        user_id: int,
        template_id: int,
        template_name: str,
        template_text: str,
    ) -> dict[str, Any] | None:
        clean_text = str(template_text or "").strip()
        clean_name = str(template_name or "").strip()
        if not clean_text:
            raise ValueError("template_text is required")
        if not clean_name:
            raise ValueError("template_name is required")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE chat_quick_templates
                SET template_name = ?, template_text = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (clean_name, clean_text, now, template_id, user_id),
            )
            row = conn.execute(
                """
                SELECT id, user_id, template_name, template_text, created_at, updated_at
                FROM chat_quick_templates
                WHERE id = ? AND user_id = ?
                """,
                (template_id, user_id),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def delete_chat_quick_template(self, *, user_id: int, template_id: int) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM chat_quick_templates
                WHERE id = ? AND user_id = ?
                """,
                (template_id, user_id),
            )
        return result.rowcount > 0

    def list_conversation_messages(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 1000)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM conversation_messages
                WHERE user_id = ? AND conversation_uid = ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (user_id, conversation_uid, safe_limit),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def update_conversation_message_idempotency_key(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        old_key: str,
        new_key: str,
    ) -> bool:
        """Replace a temporary idempotency key with the WB eventID-based key.

        Used after sending a message to link our DB record to the WB event so
        that when we later download events the ON CONFLICT DO NOTHING prevents
        a duplicate entry.
        """
        clean_old = str(old_key or "").strip()
        clean_new = str(new_key or "").strip()
        if not clean_old or not clean_new or clean_old == clean_new:
            return False
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE conversation_messages
                SET idempotency_key = ?
                WHERE user_id = ? AND conversation_uid = ? AND idempotency_key = ?
                """,
                (clean_new, user_id, conversation_uid, clean_old),
            )
        return result.rowcount > 0

    def get_conversation_message_by_idempotency(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        clean_key = str(idempotency_key or "").strip()
        if not clean_key:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM conversation_messages
                WHERE user_id = ? AND conversation_uid = ? AND idempotency_key = ?
                """,
                (user_id, conversation_uid, clean_key),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def fix_wb_internal_photo_urls(self, *, user_id: int, conversation_uid: str) -> int:
        """Convert WB internal K8s image URLs to wb-download:id tokens.

        Old format: [img:http://sellers-chat-inner.chat.k8s.cc-xs/internal/v1/file/{uuid}]
        New format: [img:wb-download:{uuid}]

        Returns number of rows updated.
        """
        if self.is_postgres:
            sql = """
                UPDATE conversation_messages
                SET message_text = regexp_replace(
                    message_text,
                    '\\[img:http://sellers-chat-inner[^/]*/internal/v1/file/([^\\]]+)\\]',
                    '[img:wb-download:\\1]',
                    'g'
                )
                WHERE user_id = %s AND conversation_uid = %s
                  AND message_text LIKE '%sellers-chat-inner%'
            """
        else:
            # SQLite doesn't support regexp_replace — skip migration (rare case)
            return 0
        with self._connect() as conn:
            result = conn.execute(self._sql(sql), (user_id, conversation_uid))
        return int(result.rowcount or 0)

    def fix_ozon_photo_messages(self, *, user_id: int, conversation_uid: str) -> int:
        """Convert legacy Ozon photo messages stored as Markdown to [img:url] tokens.

        Old format (before fix): ``![](https://api-seller.ozon.ru/...)``
        New format: ``[img:https://api-seller.ozon.ru/...]``

        Returns number of rows updated.
        """
        if self.is_postgres:
            # Markdown: ![](url) — skip first 4 chars '![](' and last 1 char ')'
            # Also fix previously broken '[img:(http...]' entries (from=4 bug)
            sql = """
                UPDATE conversation_messages
                SET message_text =
                    CASE
                        WHEN message_text LIKE '![](%%)' THEN
                            '[img:' || substring(message_text from 5 for length(message_text)-5) || ']'
                        WHEN message_text LIKE '%%[img:(http%%' THEN
                            regexp_replace(message_text, '\\[img:\\(([^)]+)\\)', '[img:\\1]', 'g')
                        ELSE message_text
                    END
                WHERE user_id = %s AND conversation_uid = %s
                  AND (message_text LIKE '![](%%)' OR message_text LIKE '%%[img:(http%%')
            """
        else:
            sql = """
                UPDATE conversation_messages
                SET message_text = '[img:' || substr(message_text, 5, length(message_text)-5) || ']'
                WHERE user_id = ? AND conversation_uid = ?
                  AND message_text LIKE '![](%)'
            """
        with self._connect() as conn:
            result = conn.execute(self._sql(sql), (user_id, conversation_uid))
        return int(result.rowcount or 0)

    def bulk_insert_chat_history_messages(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        messages: list[dict[str, Any]],
    ) -> int:
        """Insert historical messages from WB events into conversation_messages.

        Each item in ``messages`` must have:
          - direction: 'inbound' | 'outbound'
          - message_text: str
          - idempotency_key: str  (event_id from WB)
          - created_at: str (ISO timestamp of the WB event)
          - operator_name: str | None (clientName or 'Продавец')

        Rows with duplicate idempotency_key are silently skipped.
        Returns the number of newly inserted rows.
        """
        if not messages:
            return 0
        # Build the parameter list, skipping invalid rows
        params: list[tuple] = []
        for msg in messages:
            direction = str(msg.get("direction") or "inbound").strip()
            text = str(msg.get("message_text") or "").strip()
            idem_key = str(msg.get("idempotency_key") or "").strip()
            created = str(msg.get("created_at") or _utc_now()).strip()
            op_name = str(msg.get("operator_name") or "").strip() or None
            if not idem_key or not text:
                continue
            params.append((conversation_uid, user_id, direction, text, op_name, idem_key, created))
        if not params:
            return 0
        sql = self._sql("""
            INSERT INTO conversation_messages (
                conversation_uid, user_id, direction, message_text,
                operator_name, send_status, idempotency_key, created_at
            )
            VALUES (?, ?, ?, ?, ?, 'sent', ?, ?)
            ON CONFLICT(user_id, conversation_uid, idempotency_key) DO NOTHING
        """)
        # All rows in one transaction — the main performance gain vs separate transactions
        inserted = 0
        with self._connect() as conn:
            for row_params in params:
                result = conn.execute(sql, row_params)
                inserted += int(result.rowcount or 0)
        return inserted

    def upsert_conversation_outbound_message(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        message_text: str,
        operator_name: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        now = _utc_now()
        clean_text = str(message_text or "").strip()
        clean_operator = str(operator_name or "").strip()
        clean_key = str(idempotency_key or "").strip()
        if not clean_text:
            raise ValueError("message_text is required")
        if not clean_key:
            raise ValueError("idempotency_key is required")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages (
                    conversation_uid, user_id, direction, message_text, operator_name,
                    send_status, idempotency_key, created_at
                )
                VALUES (?, ?, 'outbound', ?, ?, 'pending', ?, ?)
                ON CONFLICT(user_id, conversation_uid, idempotency_key) DO NOTHING
                """,
                (conversation_uid, user_id, clean_text, clean_operator, clean_key, now),
            )
            row = conn.execute(
                """
                SELECT *
                FROM conversation_messages
                WHERE user_id = ? AND conversation_uid = ? AND idempotency_key = ?
                """,
                (user_id, conversation_uid, clean_key),
            ).fetchone()
        if row is None:
            raise RuntimeError("Conversation message upsert failed")
        return self._row_to_dict(row)

    def mark_conversation_message_send_success(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        idempotency_key: str,
        external_message_id: str | None = None,
    ) -> bool:
        now = _utc_now()
        clean_key = str(idempotency_key or "").strip()
        if not clean_key:
            return False
        with self._connect() as conn:
            message_result = conn.execute(
                """
                UPDATE conversation_messages
                SET send_status = 'sent',
                    send_error_code = NULL,
                    send_error_message = NULL,
                    external_message_id = COALESCE(?, external_message_id)
                WHERE user_id = ? AND conversation_uid = ? AND idempotency_key = ?
                """,
                (external_message_id, user_id, conversation_uid, clean_key),
            )
            conn.execute(
                """
                UPDATE conversation_items
                SET status = 'waiting',
                    unread_count = 0,
                    send_error_code = NULL,
                    send_error_message = NULL,
                    send_attempts = 0,
                    last_send_attempt_at = NULL,
                    last_sent_at = ?,
                    last_message_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND conversation_uid = ?
                """,
                (now, now, now, user_id, conversation_uid),
            )
        return bool(message_result.rowcount)

    def mark_conversation_message_send_failure(
        self,
        *,
        user_id: int,
        conversation_uid: str,
        idempotency_key: str,
        error_code: str | None,
        error_message: str | None,
    ) -> bool:
        now = _utc_now()
        clean_key = str(idempotency_key or "").strip()
        if not clean_key:
            return False
        code = str(error_code or "").strip() or None
        message = str(error_message or "").strip() or None
        with self._connect() as conn:
            message_result = conn.execute(
                """
                UPDATE conversation_messages
                SET send_status = 'failed',
                    send_error_code = ?,
                    send_error_message = ?
                WHERE user_id = ? AND conversation_uid = ? AND idempotency_key = ?
                """,
                (code, message, user_id, conversation_uid, clean_key),
            )
            conn.execute(
                """
                UPDATE conversation_items
                SET status = 'open',
                    send_error_code = ?,
                    send_error_message = ?,
                    send_attempts = COALESCE(send_attempts, 0) + 1,
                    last_send_attempt_at = ?,
                    updated_at = ?
                WHERE user_id = ? AND conversation_uid = ?
                """,
                (code, message, now, now, user_id, conversation_uid),
            )
        return bool(message_result.rowcount)

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

    def get_conversation(self, *, user_id: int, conversation_uid: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM conversation_items
                WHERE user_id = ? AND conversation_uid = ?
                """,
                (user_id, conversation_uid),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        raw = data.pop("metadata_json", "{}")
        data["metadata"] = _json_load(raw, {})
        return data

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

    def count_recent_actions(self, *, user_id: int | None = None) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        query = "SELECT COUNT(*) AS c FROM review_actions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return int(row["c"]) if row else 0

    def list_recent_actions(
        self,
        *,
        user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
        action_type: str | None = None,
        actor: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        filter_params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            filter_params.append(user_id)
        normalized_action_type = str(action_type or "").strip()
        if normalized_action_type:
            clauses.append("action_type = ?")
            filter_params.append(normalized_action_type)
        normalized_actor = str(actor or "").strip()
        if normalized_actor:
            clauses.append("LOWER(actor) LIKE ?")
            filter_params.append(f"%{normalized_actor.lower()}%")
        if date_from:
            if self.is_postgres:
                clauses.append("created_at::date >= ?::date")
            else:
                clauses.append("substr(created_at, 1, 10) >= ?")
            filter_params.append(date_from)
        if date_to:
            if self.is_postgres:
                clauses.append("created_at::date <= ?::date")
            else:
                clauses.append("substr(created_at, 1, 10) <= ?")
            filter_params.append(date_to)
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            details_expr = "COALESCE(details_json::text, '')" if self.is_postgres else "COALESCE(details_json, '')"
            clauses.append(
                f"""(
                    LOWER(COALESCE(actor, '')) LIKE ?
                    OR LOWER(COALESCE(review_uid, '')) LIKE ?
                    OR LOWER(COALESCE(action_type, '')) LIKE ?
                    OR LOWER({details_expr}) LIKE ?
                )"""
            )
            search_value = f"%{normalized_search}%"
            filter_params.extend([search_value, search_value, search_value, search_value])
        query = "SELECT * FROM review_actions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        query_params = [*filter_params, max(limit, 1), max(offset, 0)]

        with self._connect() as conn:
            count_query = "SELECT COUNT(*) AS c FROM review_actions"
            if clauses:
                count_query += " WHERE " + " AND ".join(clauses)
            total_row = conn.execute(count_query, tuple(filter_params)).fetchone()
            rows = conn.execute(query, tuple(query_params)).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            data = self._row_to_dict(row)
            raw = data.pop("details_json", "{}")
            data["details"] = _json_load(raw, {})
            items.append(data)
        total = int(total_row["c"]) if total_row else 0
        return items, total

    def list_action_filter_options(self, *, user_id: int | None = None) -> dict[str, list[str]]:
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        where_sql = ""
        if clauses:
            where_sql = " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            action_type_rows = conn.execute(
                f"""
                SELECT DISTINCT action_type
                FROM review_actions
                {where_sql}
                ORDER BY action_type ASC
                """,
                tuple(params),
            ).fetchall()
            actor_rows = conn.execute(
                f"""
                SELECT DISTINCT actor
                FROM review_actions
                {where_sql}
                ORDER BY actor ASC
                """,
                tuple(params),
            ).fetchall()
        return {
            "action_types": [
                str(row["action_type"])
                for row in action_type_rows
                if row["action_type"] is not None and str(row["action_type"]).strip()
            ],
            "actors": [str(row["actor"]) for row in actor_rows if row["actor"] is not None and str(row["actor"]).strip()],
        }

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
