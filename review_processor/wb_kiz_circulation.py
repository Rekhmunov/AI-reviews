"""WB FBS → Chestny Znak circulation (вывод / возврат КИЗ).

New block: daily sync of analytics/excise-report + CHZ document prepare/submit.
Does not touch existing KIZ modal / meta/sgtin flow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .chz_true_api import (
    DEMO_BASE,
    PROD_BASE,
    ChzTrueApiClient,
    ChzTrueApiError,
    build_lk_receipt_document,
    build_lp_return_document,
)
from .repository import ReviewRepository
from .security import decrypt_secret, encrypt_secret, mask_secret

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
WB_ANALYTICS_API = "https://seller-analytics-api.wildberries.ru"

OP_WITHDRAW = 1
OP_RETURN = 2

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_SKIPPED = "skipped"
STATUS_ACCEPTED = "accepted"
STATUS_ERROR = "error"
STATUS_SUBMITTED = "submitted"

# ASCII codes only in SQL — Cyrillic in ILIKE caused UnicodeDecodeError on PG.
SKIP_NO_FISCAL = "no_fiscal"
# Primary document when WB excise-report has no fiscal receipt (True API OTHER).
NO_FISCAL_PRIMARY_DOC_TYPE = "OTHER"
NO_FISCAL_PRIMARY_DOC_NAME = "Без документа основания"


def _is_no_fiscal_reason(reason: str) -> bool:
    raw = str(reason or "").strip().lower()
    if not raw:
        return False
    if raw == SKIP_NO_FISCAL or raw.startswith(f"{SKIP_NO_FISCAL}:"):
        return True
    # Legacy Russian reasons written before the ASCII-code fix.
    return ("нет номера" in raw) or ("нет чека" in raw) or ("нет чек" in raw)

# Oldest-first prepare batch; chunk products so CHZ docs stay within size limits.
PREPARE_EVENT_LIMIT = 2000
CHZ_PRODUCTS_PER_DOC = 100
# UKЭP signs one detached CAdES per document in the browser — keep rounds small.
# 1110 docs in one prepare made "Отправить в ЧЗ" unusable (hours of signing, no submit).
CHZ_DOCUMENTS_PER_PREPARE = 40
# Full event rows (UI/history) — ~6 months. Slim sent-CIS registry is kept forever.
EVENT_RETENTION_DAYS = 180
PURGE_BATCH_SIZE = 1000
# Storage GC is not free — skip if ran recently (prepare can loop many rounds).
STORAGE_MAINTAIN_MIN_INTERVAL_HOURS = 12

CHZ_STATUS_SUCCESS = frozenset(
    {"ACCEPTED", "CHECKED_OK", "SUCCESS", "OK", "PROCESSED"}
)
CHZ_STATUS_FAILED = frozenset(
    {
        "CHECKED_NOT_OK",
        "REJECTED",
        "ERROR",
        "FAILED",
        "CANCELLED",
        "CANCELED",
        "NOT_ACCEPTED",
        "PARSE_ERROR",
    }
)


def _moscow_today() -> str:
    return datetime.now(MSK).date().isoformat()


def _parse_date(s: str, *, default: str = "") -> str:
    raw = str(s or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return default or _moscow_today()


def resolve_excise_period(
    *,
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    """Exact [date_from, date_to] from the modal — no watermark, no ceiling.

    Raises ValueError if either date is missing/invalid.
    """
    raw_from = str(date_from or "").strip()
    raw_to = str(date_to or "").strip()
    if not raw_from or not raw_to:
        raise ValueError("Укажите даты «С» и «По» в модалке «Вывод КИЗ»")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_from):
        raise ValueError(f"Некорректная дата «С»: {raw_from}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_to):
        raise ValueError(f"Некорректная дата «По»: {raw_to}")
    from_d = date.fromisoformat(raw_from)
    to_d = date.fromisoformat(raw_to)
    if from_d > to_d:
        from_d, to_d = to_d, from_d
    return {
        "date_from": from_d.isoformat(),
        "date_to": to_d.isoformat(),
        "days": (to_d - from_d).days + 1,
    }


def _event_key(
    *,
    srid: str,
    excise_short: str,
    operation_type: int,
    fiscal_doc_number: str,
    fiscal_dt: str,
) -> str:
    blob = "|".join(
        [
            str(srid or "").strip(),
            str(excise_short or "").strip(),
            str(int(operation_type or 0)),
            str(fiscal_doc_number or "").strip(),
            str(fiscal_dt or "").strip(),
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:40]


def _cis_identity(
    *,
    srid: str = "",
    rid: str = "",
    excise_short: str = "",
    operation_type: int = 0,
) -> tuple[str, str, int]:
    """Stable КИЗ identity ignoring fiscal receipt (srid/rid + cis + op)."""
    srid_s = str(srid or "").strip()
    rid_s = str(rid or "").strip()
    anchor = srid_s or rid_s
    return (anchor, str(excise_short or "").strip(), int(operation_type or 0))


def _event_has_fiscal(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return bool(
        str(row.get("fiscal_doc_number") or "").strip()
        and str(row.get("fiscal_dt") or "").strip()
    )


def _fiscal_doc_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def ensure_kiz_circulation_tables(repo: ReviewRepository) -> None:
    with repo._connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS supply_chz_settings (
                user_id BIGINT PRIMARY KEY,
                is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                api_base TEXT NOT NULL DEFAULT '',
                participant_inn TEXT NOT NULL DEFAULT '',
                product_group TEXT NOT NULL DEFAULT '',
                kpp TEXT NOT NULL DEFAULT '',
                fias_id TEXT NOT NULL DEFAULT '',
                return_type TEXT NOT NULL DEFAULT 'REMOTE_SALE_RETURN',
                cert_thumbprint TEXT NOT NULL DEFAULT '',
                wb_analytics_api_key_encrypted TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        try:
            conn.execute(
                "ALTER TABLE supply_chz_settings "
                "ADD COLUMN IF NOT EXISTS wb_analytics_api_key_encrypted "
                "TEXT NOT NULL DEFAULT ''"
            )
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_kiz_circulation_cursor (
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                last_date_to TEXT NOT NULL DEFAULT '',
                last_event_key TEXT NOT NULL DEFAULT '',
                last_fiscal_dt TEXT NOT NULL DEFAULT '',
                last_run_at TEXT NOT NULL DEFAULT '',
                last_run_id BIGINT,
                last_storage_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, source_id)
            )
            """
        )
        try:
            conn.execute(
                "ALTER TABLE wb_kiz_circulation_cursor "
                "ADD COLUMN IF NOT EXISTS last_storage_at TEXT NOT NULL DEFAULT ''"
            )
        except Exception:
            pass
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_kiz_circulation_runs (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                date_from TEXT NOT NULL DEFAULT '',
                date_to TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                fetched INTEGER NOT NULL DEFAULT 0,
                inserted INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0,
                withdraw_count INTEGER NOT NULL DEFAULT 0,
                return_count INTEGER NOT NULL DEFAULT 0,
                error_text TEXT NOT NULL DEFAULT '',
                log_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_wb_kiz_circ_runs_user "
                "ON wb_kiz_circulation_runs(user_id, created_at DESC)"
            )
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_kiz_circulation_events (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                event_key TEXT NOT NULL,
                operation_type INTEGER NOT NULL DEFAULT 0,
                srid TEXT NOT NULL DEFAULT '',
                rid TEXT NOT NULL DEFAULT '',
                nm_id BIGINT,
                barcode TEXT NOT NULL DEFAULT '',
                excise_short TEXT NOT NULL DEFAULT '',
                fiscal_doc_number TEXT NOT NULL DEFAULT '',
                fiscal_dt TEXT NOT NULL DEFAULT '',
                fiscal_drive_number TEXT NOT NULL DEFAULT '',
                price DOUBLE PRECISION,
                currency_name TEXT NOT NULL DEFAULT '',
                country_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                skip_reason TEXT NOT NULL DEFAULT '',
                chz_doc_id TEXT NOT NULL DEFAULT '',
                chz_status TEXT NOT NULL DEFAULT '',
                error_text TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                run_id BIGINT,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                UNIQUE (user_id, source_id, event_key)
            )
            """
        )
        try:
            conn.execute(
                "ALTER TABLE wb_kiz_circulation_events "
                "ADD COLUMN IF NOT EXISTS currency_name TEXT NOT NULL DEFAULT ''"
            )
        except Exception:
            pass
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_wb_kiz_circ_events_user_src "
                "ON wb_kiz_circulation_events(user_id, source_id, fiscal_dt ASC, id ASC)"
            )
        )
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_wb_kiz_circ_events_status "
                "ON wb_kiz_circulation_events(user_id, source_id, status, operation_type)"
            )
        )
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_wb_kiz_circ_events_purge "
                "ON wb_kiz_circulation_events(user_id, source_id, status, updated_at)"
            )
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_kiz_chz_documents (
                id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                run_id BIGINT,
                doc_type TEXT NOT NULL DEFAULT '',
                chz_doc_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                event_keys_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # Forever-kept compact anti-dupe + support trail (CIS → chz_doc_id).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wb_kiz_sent_cis (
                user_id BIGINT NOT NULL,
                source_id BIGINT NOT NULL,
                operation_type INTEGER NOT NULL DEFAULT 0,
                excise_short TEXT NOT NULL,
                anchor TEXT NOT NULL DEFAULT '',
                chz_doc_id TEXT NOT NULL DEFAULT '',
                event_key TEXT NOT NULL DEFAULT '',
                fiscal_doc_number TEXT NOT NULL DEFAULT '',
                fiscal_dt TEXT NOT NULL DEFAULT '',
                accepted_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, source_id, operation_type, excise_short, anchor)
            )
            """
        )
        conn.execute(
            repo._sql(
                "CREATE INDEX IF NOT EXISTS idx_wb_kiz_sent_cis_user_src "
                "ON wb_kiz_sent_cis(user_id, source_id, accepted_at DESC)"
            )
        )


def repair_stuck_return_events(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> int:
    """Re-queue returns that were wrongly marked error for missing fiscal."""
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    fixed = 0
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT id, skip_reason FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND operation_type = ? AND status = ?
                """
            ),
            (user_id, source_id, OP_RETURN, STATUS_ERROR),
        ).fetchall()
        for row in rows:
            d = repo._row_to_dict(row)
            if not _is_no_fiscal_reason(str(d.get("skip_reason") or "")):
                continue
            conn.execute(
                repo._sql(
                    """
                    UPDATE wb_kiz_circulation_events
                    SET status = ?, skip_reason = '', error_text = '', updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (STATUS_PENDING, now, int(d["id"]), user_id),
            )
            fixed += 1
    return fixed


def repair_unhealable_withdraw_errors(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> int:
    """Move withdraw-without-fiscal from error → pending (OTHER primary doc path)."""
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    fixed = 0
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT id, skip_reason FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND operation_type = ? AND status = ?
                """
            ),
            (user_id, source_id, OP_WITHDRAW, STATUS_ERROR),
        ).fetchall()
        for row in rows:
            d = repo._row_to_dict(row)
            if not _is_no_fiscal_reason(str(d.get("skip_reason") or "")):
                continue
            conn.execute(
                repo._sql(
                    """
                    UPDATE wb_kiz_circulation_events
                    SET status = ?, skip_reason = ?, error_text = '', updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (STATUS_PENDING, SKIP_NO_FISCAL, now, int(d["id"]), user_id),
            )
            fixed += 1
    return fixed


def repair_nofiscal_withdraw_to_pending(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> int:
    """Re-queue historical withdraw-without-fiscal from skipped → pending."""
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    fixed = 0
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT id, skip_reason FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND operation_type = ? AND status = ?
                """
            ),
            (user_id, source_id, OP_WITHDRAW, STATUS_SKIPPED),
        ).fetchall()
        for row in rows:
            d = repo._row_to_dict(row)
            if not _is_no_fiscal_reason(str(d.get("skip_reason") or "")):
                continue
            conn.execute(
                repo._sql(
                    """
                    UPDATE wb_kiz_circulation_events
                    SET status = ?, skip_reason = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (STATUS_PENDING, SKIP_NO_FISCAL, now, int(d["id"]), user_id),
            )
            fixed += 1
    return fixed


def repair_orphan_submitted_events(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> int:
    """Re-queue submitted rows that never got a CHZ document id (local fault)."""
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    with repo._connect() as conn:
        cur = conn.execute(
            repo._sql(
                """
                UPDATE wb_kiz_circulation_events
                SET status = ?, chz_status = '', error_text = ?, updated_at = ?
                WHERE user_id = ? AND source_id = ?
                  AND status = ?
                  AND COALESCE(chz_doc_id, '') = ''
                """
            ),
            (
                STATUS_PENDING,
                "восстановлено: submitted без chz_doc_id",
                now,
                user_id,
                source_id,
                STATUS_SUBMITTED,
            ),
        )
        return int(getattr(cur, "rowcount", 0) or 0)


# Skips that must stay closed (dedupe / already sent) — never auto-requeue.
_TERMINAL_SKIP_REASONS = frozenset(
    {
        "already_sent",
        "duplicate",
        "duplicate_nofiscal",
        "пустой КИЗ",
    }
)


def repair_legacy_skipped_with_cis(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> int:
    """Re-queue legacy skipped rows that still have a CIS (do not lose codes).

    Does not reopen terminal dedupe skips (already_sent / duplicate*).
    """
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    terminal = sorted(_TERMINAL_SKIP_REASONS)
    ph = ", ".join("?" for _ in terminal)
    with repo._connect() as conn:
        cur = conn.execute(
            repo._sql(
                f"""
                UPDATE wb_kiz_circulation_events
                SET status = ?,
                    skip_reason = CASE
                      WHEN operation_type = 1
                        AND COALESCE(fiscal_doc_number, '') = ''
                        AND COALESCE(fiscal_dt, '') = ''
                      THEN ?
                      ELSE ''
                    END,
                    updated_at = ?
                WHERE user_id = ? AND source_id = ?
                  AND status = ?
                  AND COALESCE(excise_short, '') <> ''
                  AND COALESCE(skip_reason, '') NOT IN ({ph})
                """
            ),
            (
                STATUS_PENDING,
                SKIP_NO_FISCAL,
                now,
                user_id,
                source_id,
                STATUS_SKIPPED,
                *terminal,
            ),
        )
        return int(getattr(cur, "rowcount", 0) or 0)


def _retention_cutoff_iso(*, days: int = EVENT_RETENTION_DAYS) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()


def _cis_anchor(*, srid: str = "", rid: str = "") -> str:
    return str(srid or "").strip() or str(rid or "").strip()


def upsert_sent_cis_rows(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    rows: list[dict[str, Any]],
    accepted_at: str = "",
) -> int:
    """Upsert compact forever registry rows (anti-dupe after event purge)."""
    if not rows:
        return 0
    ensure_kiz_circulation_tables(repo)
    now = accepted_at or datetime.now(timezone.utc).isoformat()
    written = 0
    with repo._connect() as conn:
        for row in rows:
            cis = str(row.get("excise_short") or "").strip()
            op = int(row.get("operation_type") or 0)
            if not cis or op not in {OP_WITHDRAW, OP_RETURN}:
                continue
            anchor = _cis_anchor(
                srid=str(row.get("srid") or ""),
                rid=str(row.get("rid") or ""),
            )
            conn.execute(
                repo._sql(
                    """
                    INSERT INTO wb_kiz_sent_cis (
                        user_id, source_id, operation_type, excise_short, anchor,
                        chz_doc_id, event_key, fiscal_doc_number, fiscal_dt, accepted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (user_id, source_id, operation_type, excise_short, anchor)
                    DO UPDATE SET
                        chz_doc_id = CASE
                            WHEN EXCLUDED.chz_doc_id <> '' THEN EXCLUDED.chz_doc_id
                            ELSE wb_kiz_sent_cis.chz_doc_id
                        END,
                        event_key = CASE
                            WHEN EXCLUDED.event_key <> '' THEN EXCLUDED.event_key
                            ELSE wb_kiz_sent_cis.event_key
                        END,
                        fiscal_doc_number = CASE
                            WHEN EXCLUDED.fiscal_doc_number <> '' THEN EXCLUDED.fiscal_doc_number
                            ELSE wb_kiz_sent_cis.fiscal_doc_number
                        END,
                        fiscal_dt = CASE
                            WHEN EXCLUDED.fiscal_dt <> '' THEN EXCLUDED.fiscal_dt
                            ELSE wb_kiz_sent_cis.fiscal_dt
                        END,
                        accepted_at = CASE
                            WHEN wb_kiz_sent_cis.accepted_at = ''
                              OR EXCLUDED.accepted_at > wb_kiz_sent_cis.accepted_at
                            THEN EXCLUDED.accepted_at
                            ELSE wb_kiz_sent_cis.accepted_at
                        END
                    """
                ),
                (
                    user_id,
                    source_id,
                    op,
                    cis,
                    anchor,
                    str(row.get("chz_doc_id") or "").strip(),
                    str(row.get("event_key") or "").strip(),
                    str(row.get("fiscal_doc_number") or "").strip(),
                    str(row.get("fiscal_dt") or "").strip(),
                    now,
                ),
            )
            written += 1
    return written


def register_sent_cis_for_event_keys(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    event_keys: list[str],
    accepted_at: str = "",
) -> int:
    keys = [str(k).strip() for k in event_keys if str(k).strip()]
    if not keys:
        return 0
    ensure_kiz_circulation_tables(repo)
    rows: list[dict[str, Any]] = []
    with repo._connect() as conn:
        for chunk in _chunked(keys, 200):
            ph = ", ".join("?" for _ in chunk)
            found = conn.execute(
                repo._sql(
                    f"""
                    SELECT srid, rid, excise_short, operation_type, chz_doc_id,
                           event_key, fiscal_doc_number, fiscal_dt
                    FROM wb_kiz_circulation_events
                    WHERE user_id = ? AND source_id = ?
                      AND event_key IN ({ph})
                    """
                ),
                (user_id, source_id, *chunk),
            ).fetchall()
            rows.extend(repo._row_to_dict(r) for r in found)
    return upsert_sent_cis_rows(
        repo,
        user_id=user_id,
        source_id=source_id,
        rows=rows,
        accepted_at=accepted_at,
    )


def clear_accepted_raw_json(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> int:
    """Drop bulky WB payload once CHZ accepted — registry keeps the trail."""
    ensure_kiz_circulation_tables(repo)
    cleared = 0
    for _ in range(20):
        with repo._connect() as conn:
            cur = conn.execute(
                repo._sql(
                    """
                    UPDATE wb_kiz_circulation_events
                    SET raw_json = '{}'
                    WHERE id IN (
                      SELECT id FROM wb_kiz_circulation_events
                      WHERE user_id = ? AND source_id = ?
                        AND status = ?
                        AND COALESCE(raw_json, '') <> ''
                        AND raw_json <> '{}'
                      ORDER BY id ASC
                      LIMIT ?
                    )
                    """
                ),
                (user_id, source_id, STATUS_ACCEPTED, PURGE_BATCH_SIZE),
            )
            n = int(getattr(cur, "rowcount", 0) or 0)
        cleared += n
        if n < PURGE_BATCH_SIZE:
            break
    return cleared


def _mark_storage_maintained(
    repo: ReviewRepository, *, user_id: int, source_id: int, when: str = ""
) -> None:
    ensure_kiz_circulation_tables(repo)
    now = when or datetime.now(timezone.utc).isoformat()
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                """
                INSERT INTO wb_kiz_circulation_cursor (
                    user_id, source_id, last_storage_at, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, source_id) DO UPDATE SET
                    last_storage_at = EXCLUDED.last_storage_at,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            (user_id, source_id, now, now),
        )


def maintain_kiz_circulation_storage(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    force: bool = False,
    min_interval_hours: int = STORAGE_MAINTAIN_MIN_INTERVAL_HOURS,
) -> dict[str, int]:
    """Clear bulky payloads + purge old terminal history; keep slim sent registry.

    Throttled by default so CHZ prepare multi-round loops do not re-scan the table.
    """
    empty = {
        "raw_json_cleared": 0,
        "events_purged": 0,
        "runs_purged": 0,
        "docs_purged": 0,
        "skipped": 0,
    }
    if not force and min_interval_hours > 0:
        try:
            cur = get_cursor(repo, user_id=user_id, source_id=source_id)
            last = str(cur.get("last_storage_at") or "").strip()
            if last:
                threshold = (
                    datetime.now(timezone.utc)
                    - timedelta(hours=max(1, int(min_interval_hours)))
                ).isoformat()
                if last >= threshold:
                    empty["skipped"] = 1
                    return empty
        except Exception as exc:
            logger.exception("storage maintain throttle check failed: %s", exc)

    cleared = 0
    purged_events = 0
    meta = {"runs": 0, "docs": 0}
    try:
        cleared = clear_accepted_raw_json(repo, user_id=user_id, source_id=source_id)
    except Exception as exc:
        logger.exception("clear_accepted_raw_json failed: %s", exc)
    try:
        purged_events = purge_old_kiz_circulation_events(
            repo, user_id=user_id, source_id=source_id
        )
    except Exception as exc:
        logger.exception("purge_old_kiz_circulation_events failed: %s", exc)
    try:
        meta = purge_old_kiz_runs_and_docs(repo, user_id=user_id, source_id=source_id)
    except Exception as exc:
        logger.exception("purge_old_kiz_runs_and_docs failed: %s", exc)
    try:
        _mark_storage_maintained(repo, user_id=user_id, source_id=source_id)
    except Exception as exc:
        logger.exception("mark storage maintained failed: %s", exc)
    return {
        "raw_json_cleared": cleared,
        "events_purged": purged_events,
        "runs_purged": int(meta.get("runs") or 0),
        "docs_purged": int(meta.get("docs") or 0),
        "skipped": 0,
    }


def repair_circulation_queue(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> dict[str, int]:
    try:
        returns_fixed = repair_stuck_return_events(
            repo, user_id=user_id, source_id=source_id
        )
    except Exception as exc:
        logger.exception("repair_stuck_return_events failed: %s", exc)
        returns_fixed = 0
    try:
        withdraw_from_error = repair_unhealable_withdraw_errors(
            repo, user_id=user_id, source_id=source_id
        )
    except Exception as exc:
        logger.exception("repair_unhealable_withdraw_errors failed: %s", exc)
        withdraw_from_error = 0
    try:
        withdraw_requeued = repair_nofiscal_withdraw_to_pending(
            repo, user_id=user_id, source_id=source_id
        )
    except Exception as exc:
        logger.exception("repair_nofiscal_withdraw_to_pending failed: %s", exc)
        withdraw_requeued = 0
    try:
        orphan_submitted = repair_orphan_submitted_events(
            repo, user_id=user_id, source_id=source_id
        )
    except Exception as exc:
        logger.exception("repair_orphan_submitted_events failed: %s", exc)
        orphan_submitted = 0
    try:
        legacy_skipped = repair_legacy_skipped_with_cis(
            repo, user_id=user_id, source_id=source_id
        )
    except Exception as exc:
        logger.exception("repair_legacy_skipped_with_cis failed: %s", exc)
        legacy_skipped = 0
    return {
        "returns_fixed": returns_fixed,
        "withdraw_skipped": withdraw_from_error,
        "withdraw_requeued": withdraw_requeued,
        "orphan_submitted": orphan_submitted,
        "legacy_skipped": legacy_skipped,
    }


def purge_old_kiz_circulation_events(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    retention_days: int = EVENT_RETENTION_DAYS,
) -> int:
    """Delete terminal event rows older than retention; register accepted first.

    Never touches pending/ready/error/submitted (open queue / in-flight CHZ).
    """
    ensure_kiz_circulation_tables(repo)
    cutoff = _retention_cutoff_iso(days=retention_days)
    terminal = sorted(_TERMINAL_SKIP_REASONS)
    skip_ph = ", ".join("?" for _ in terminal)
    deleted = 0
    for _ in range(50):
        with repo._connect() as conn:
            accepted = conn.execute(
                repo._sql(
                    f"""
                    SELECT id, srid, rid, excise_short, operation_type, chz_doc_id,
                           event_key, fiscal_doc_number, fiscal_dt
                    FROM wb_kiz_circulation_events
                    WHERE user_id = ? AND source_id = ?
                      AND status = ?
                      AND updated_at < ?
                    ORDER BY id ASC
                    LIMIT ?
                    """
                ),
                (
                    user_id,
                    source_id,
                    STATUS_ACCEPTED,
                    cutoff,
                    PURGE_BATCH_SIZE,
                ),
            ).fetchall()
            accepted_rows = [repo._row_to_dict(r) for r in accepted]
        if accepted_rows:
            upsert_sent_cis_rows(
                repo,
                user_id=user_id,
                source_id=source_id,
                rows=accepted_rows,
            )
            ids = [int(r["id"]) for r in accepted_rows if int(r.get("id") or 0) > 0]
            with repo._connect() as conn:
                for chunk in _chunked(ids, 200):
                    ph = ", ".join("?" for _ in chunk)
                    cur = conn.execute(
                        repo._sql(
                            f"""
                            DELETE FROM wb_kiz_circulation_events
                            WHERE user_id = ? AND source_id = ?
                              AND id IN ({ph})
                            """
                        ),
                        (user_id, source_id, *chunk),
                    )
                    deleted += int(getattr(cur, "rowcount", 0) or 0)

        with repo._connect() as conn:
            cur = conn.execute(
                repo._sql(
                    f"""
                    DELETE FROM wb_kiz_circulation_events
                    WHERE id IN (
                      SELECT id FROM wb_kiz_circulation_events
                      WHERE user_id = ? AND source_id = ?
                        AND status = ?
                        AND COALESCE(skip_reason, '') IN ({skip_ph})
                        AND updated_at < ?
                      ORDER BY id ASC
                      LIMIT ?
                    )
                    """
                ),
                (
                    user_id,
                    source_id,
                    STATUS_SKIPPED,
                    *terminal,
                    cutoff,
                    PURGE_BATCH_SIZE,
                ),
            )
            n_skip = int(getattr(cur, "rowcount", 0) or 0)
            deleted += n_skip
        if not accepted_rows and n_skip == 0:
            break
    return deleted


def purge_old_kiz_runs_and_docs(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    retention_days: int = EVENT_RETENTION_DAYS,
) -> dict[str, int]:
    ensure_kiz_circulation_tables(repo)
    cutoff = _retention_cutoff_iso(days=retention_days)
    with repo._connect() as conn:
        cur_runs = conn.execute(
            repo._sql(
                """
                DELETE FROM wb_kiz_circulation_runs
                WHERE user_id = ? AND source_id = ?
                  AND COALESCE(finished_at, created_at, '') < ?
                  AND COALESCE(finished_at, created_at, '') <> ''
                """
            ),
            (user_id, source_id, cutoff),
        )
        cur_docs = conn.execute(
            repo._sql(
                """
                DELETE FROM wb_kiz_chz_documents
                WHERE user_id = ? AND source_id = ?
                  AND COALESCE(created_at, '') < ?
                  AND COALESCE(created_at, '') <> ''
                """
            ),
            (user_id, source_id, cutoff),
        )
    return {
        "runs": int(getattr(cur_runs, "rowcount", 0) or 0),
        "docs": int(getattr(cur_docs, "rowcount", 0) or 0),
    }


def _decrypt_wb_analytics_key(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    enc = str(row.get("wb_analytics_api_key_encrypted") or "").strip()
    if not enc:
        return ""
    return str(decrypt_secret(enc) or "").strip()


def get_wb_analytics_api_key(repo: ReviewRepository, *, user_id: int) -> str:
    """WB token for seller-analytics excise-report (not Marketplace FBS)."""
    ensure_kiz_circulation_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql("SELECT wb_analytics_api_key_encrypted FROM supply_chz_settings WHERE user_id = ?"),
            (user_id,),
        ).fetchone()
    if not row:
        return ""
    return _decrypt_wb_analytics_key(repo._row_to_dict(row))


def get_chz_settings(
    repo: ReviewRepository, *, user_id: int, include_secrets: bool = False
) -> dict[str, Any]:
    ensure_kiz_circulation_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql("SELECT * FROM supply_chz_settings WHERE user_id = ?"),
            (user_id,),
        ).fetchone()
    if not row:
        out = {
            "user_id": user_id,
            "is_enabled": False,
            "api_base": "prod",
            "api_base_url": PROD_BASE,
            "participant_inn": "",
            "product_group": "",
            "kpp": "",
            "fias_id": "",
            "return_type": "REMOTE_SALE_RETURN",
            "cert_thumbprint": "",
            "has_wb_analytics_api_key": False,
            "wb_analytics_api_key_preview": "",
        }
        if include_secrets:
            out["wb_analytics_api_key"] = ""
        return out
    d = repo._row_to_dict(row)
    api_base = str(d.get("api_base") or "prod").strip() or "prod"
    wb_key = _decrypt_wb_analytics_key(d)
    out = {
        "user_id": user_id,
        "is_enabled": bool(d.get("is_enabled")),
        "api_base": api_base if api_base in {"prod", "demo"} else "prod",
        "api_base_url": DEMO_BASE if api_base == "demo" else PROD_BASE,
        "participant_inn": str(d.get("participant_inn") or ""),
        "product_group": str(d.get("product_group") or ""),
        "kpp": str(d.get("kpp") or ""),
        "fias_id": str(d.get("fias_id") or ""),
        "return_type": str(d.get("return_type") or "REMOTE_SALE_RETURN"),
        "cert_thumbprint": str(d.get("cert_thumbprint") or ""),
        "has_wb_analytics_api_key": bool(wb_key),
        "wb_analytics_api_key_preview": mask_secret(wb_key) if wb_key else "",
        "updated_at": str(d.get("updated_at") or ""),
    }
    if include_secrets:
        out["wb_analytics_api_key"] = wb_key
    return out


def upsert_chz_settings(
    repo: ReviewRepository,
    *,
    user_id: int,
    is_enabled: bool = False,
    participant_inn: str = "",
    product_group: str = "",
    api_base: str | None = None,
    kpp: str | None = None,
    fias_id: str | None = None,
    return_type: str | None = None,
    cert_thumbprint: str | None = None,
    wb_analytics_api_key: str | None = None,
) -> dict[str, Any]:
    """Save minimal connection fields; omitted optional args keep previous values."""
    ensure_kiz_circulation_tables(repo)
    prev = get_chz_settings(repo, user_id=user_id, include_secrets=True)
    now = datetime.now(timezone.utc).isoformat()
    if api_base is None:
        base = "demo" if str(prev.get("api_base") or "") == "demo" else "prod"
    else:
        base = "demo" if str(api_base or "").strip().lower() == "demo" else "prod"
    pg = str(product_group or "").strip()
    # Reject pure-numeric placeholders that are not True API pg codes.
    if pg.isdigit():
        raise ValueError(
            "Товарная группа — код True API (например lp, shoes, clothes), не число"
        )
    kpp_s = str(prev.get("kpp") or "") if kpp is None else str(kpp or "").strip()
    fias_s = str(prev.get("fias_id") or "") if fias_id is None else str(fias_id or "").strip()
    ret_s = (
        str(prev.get("return_type") or "REMOTE_SALE_RETURN")
        if return_type is None
        else (str(return_type or "").strip() or "REMOTE_SALE_RETURN")
    )
    cert_s = (
        str(prev.get("cert_thumbprint") or "")
        if cert_thumbprint is None
        else str(cert_thumbprint or "").strip()
    )
    if wb_analytics_api_key is None:
        wb_enc = ""
        with repo._connect() as conn:
            row = conn.execute(
                repo._sql(
                    "SELECT wb_analytics_api_key_encrypted FROM supply_chz_settings "
                    "WHERE user_id = ?"
                ),
                (user_id,),
            ).fetchone()
            if row:
                wb_enc = str(repo._row_to_dict(row).get("wb_analytics_api_key_encrypted") or "")
    else:
        clean = str(wb_analytics_api_key or "").strip()
        wb_enc = encrypt_secret(clean) if clean else ""
        wb_enc = str(wb_enc or "")
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                """
                INSERT INTO supply_chz_settings (
                    user_id, is_enabled, api_base, participant_inn, product_group,
                    kpp, fias_id, return_type, cert_thumbprint,
                    wb_analytics_api_key_encrypted, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE SET
                    is_enabled = EXCLUDED.is_enabled,
                    api_base = EXCLUDED.api_base,
                    participant_inn = EXCLUDED.participant_inn,
                    product_group = EXCLUDED.product_group,
                    kpp = EXCLUDED.kpp,
                    fias_id = EXCLUDED.fias_id,
                    return_type = EXCLUDED.return_type,
                    cert_thumbprint = EXCLUDED.cert_thumbprint,
                    wb_analytics_api_key_encrypted = EXCLUDED.wb_analytics_api_key_encrypted,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            (
                user_id,
                bool(is_enabled),
                base,
                str(participant_inn or "").strip(),
                pg,
                kpp_s,
                fias_s,
                ret_s,
                cert_s,
                wb_enc,
                now,
            ),
        )
    return get_chz_settings(repo, user_id=user_id)


def _parse_inn_kpp_from_text(text: str) -> tuple[str, str]:
    raw = str(text or "")
    inn_m = re.search(r"ИНН\s*[:№]?\s*(\d{10}|\d{12})", raw, flags=re.IGNORECASE)
    kpp_m = re.search(r"КПП\s*[:№]?\s*(\d{9})", raw, flags=re.IGNORECASE)
    inn = inn_m.group(1) if inn_m else ""
    kpp = kpp_m.group(1) if kpp_m else ""
    if not inn:
        digits = re.findall(r"\b(\d{10}|\d{12})\b", raw)
        if digits:
            inn = digits[0]
    return inn, kpp


def resolve_chz_place_details(
    repo: ReviewRepository, *, user_id: int, participant_inn: str
) -> dict[str, str]:
    """Resolve KPP/FIAS for DISTANCE from legal entities matching participant INN."""
    inn = re.sub(r"\D", "", str(participant_inn or ""))
    out = {"kpp": "", "fias_id": ""}
    if not inn:
        return out
    try:
        entities = repo.list_supply_legal_entities(user_id=user_id)
    except Exception:
        return out
    for le in entities or []:
        if not isinstance(le, dict):
            continue
        req = str(le.get("requisites") or "")
        le_inn, le_kpp = _parse_inn_kpp_from_text(req)
        if le_inn and le_inn != inn:
            continue
        if not le_inn and inn not in re.sub(r"\D", "", req + str(le.get("short_name") or "")):
            # No INN in requisites — still allow if only one entity and FIAS present
            if len(entities) != 1:
                continue
        fias = str(le.get("addr_fias") or "").strip()
        if le_kpp and not out["kpp"]:
            out["kpp"] = le_kpp
        if fias and not out["fias_id"]:
            out["fias_id"] = fias
        if out["kpp"] and out["fias_id"]:
            break
    return out


def get_cursor(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> dict[str, Any]:
    ensure_kiz_circulation_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                "SELECT * FROM wb_kiz_circulation_cursor WHERE user_id = ? AND source_id = ?"
            ),
            (user_id, source_id),
        ).fetchone()
    if not row:
        return {
            "user_id": user_id,
            "source_id": source_id,
            "last_date_to": "",
            "last_event_key": "",
            "last_fiscal_dt": "",
            "last_run_at": "",
            "last_run_id": None,
            "last_storage_at": "",
        }
    return repo._row_to_dict(row)


def _append_log(parts: list[str], line: str) -> None:
    ts = datetime.now(MSK).strftime("%H:%M:%S")
    parts.append(f"[{ts}] {line}")


def _header_get(headers: Any, *names: str) -> str:
    if headers is None:
        return ""
    for name in names:
        try:
            val = headers.get(name)
        except Exception:
            val = None
        if val is None and hasattr(headers, "get"):
            try:
                # email.message.Message is case-insensitive; dict may need lower.
                val = headers.get(name.lower())
            except Exception:
                val = None
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def format_wb_excise_http_error(
    *, code: int, body: str = "", retry_after: str = "", reason: str = ""
) -> RuntimeError:
    """Human-readable WB Analytics excise-report errors (esp. 429 rate limit)."""
    if int(code) == 429:
        msg = (
            "Лимит WB на отчёт по маркировке: не больше 10 запросов за 5 часов "
            "(пауза между запросами около 30 минут). "
            "Не нажимайте «Ежедневный вывод» повторно — каждый клик тратит лимит. "
            "Один токен Аналитики общий для всех FBS-источников."
        )
        retry = str(retry_after or "").strip()
        if retry.isdigit():
            secs = int(retry)
            if secs >= 60:
                msg += f" Повторите примерно через {(secs + 59) // 60} мин."
            elif secs > 0:
                msg += f" Повторите примерно через {secs} сек."
        elif retry:
            msg += f" Повторите после: {retry}."
        return RuntimeError(msg)
    detail = (body or reason or "").strip()
    if detail:
        return RuntimeError(f"WB excise-report HTTP {code}: {detail[:500]}")
    return RuntimeError(f"WB excise-report HTTP {code}")


def fetch_wb_excise_report(
    *,
    api_key: str,
    date_from: str,
    date_to: str,
    countries: list[str] | None = None,
    timeout: int = 60,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    params = urlencode({"dateFrom": date_from, "dateTo": date_to})
    url = f"{WB_ANALYTICS_API}/api/v1/analytics/excise-report?{params}"
    body_obj: dict[str, object] = {}
    if countries:
        body_obj["countries"] = countries
    data = json.dumps(body_obj).encode("utf-8")
    last_exc: Exception | None = None
    parsed: Any = None
    for attempt in range(max(1, int(max_retries))):
        req = urllib.request.Request(
            url,
            method="POST",
            data=data,
            headers={
                "Authorization": str(api_key or "").strip(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "FeedPilot-KizCirculation/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
                if not payload:
                    return []
                parsed = json.loads(payload.decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            err = ""
            try:
                err = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            retry_after = _header_get(
                getattr(exc, "headers", None),
                "X-RateLimit-Retry",
                "x-ratelimit-retry",
                "Retry-After",
                "retry-after",
            )
            last_exc = format_wb_excise_http_error(
                code=int(exc.code),
                body=err,
                retry_after=retry_after,
                reason=str(exc.reason or ""),
            )
            # 429 must NOT be retried: each attempt burns the 10/5h quota.
            if int(exc.code) == 429:
                raise last_exc from exc
            if attempt + 1 < max_retries and int(exc.code) in {500, 502, 503, 504}:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_exc from exc
        except urllib.error.URLError as exc:
            last_exc = RuntimeError(f"WB excise-report сеть: {exc.reason}")
            if attempt + 1 < max_retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise last_exc from exc
    else:
        if last_exc:
            raise last_exc
        return []

    rows: list[Any] = []
    if isinstance(parsed, dict):
        response = parsed.get("response")
        if isinstance(response, dict) and isinstance(response.get("data"), list):
            rows = response["data"]
        elif isinstance(parsed.get("data"), list):
            rows = parsed["data"]
    elif isinstance(parsed, list):
        rows = parsed
    return [r for r in rows if isinstance(r, dict)]


def _normalize_row(row: dict[str, Any]) -> dict[str, Any] | None:
    op_raw = row.get("operation_type_id")
    if op_raw is None:
        op_raw = row.get("operationTypeId")
    try:
        op = int(op_raw or 0)
    except (TypeError, ValueError):
        op = 0
    if op not in {OP_WITHDRAW, OP_RETURN}:
        return None
    excise = str(
        row.get("excise_short") or row.get("exciseShort") or row.get("kiz") or ""
    ).strip()
    if not excise:
        return None
    srid = str(row.get("srid") or "").strip()
    fiscal_no = _fiscal_doc_str(
        row.get("fiscal_doc_number")
        if row.get("fiscal_doc_number") is not None
        else row.get("fiscalDocNumber")
    )
    fiscal_dt = str(row.get("fiscal_dt") or row.get("fiscalDt") or "").strip()
    if fiscal_dt and "T" in fiscal_dt:
        fiscal_dt = fiscal_dt.split("T", 1)[0]
    rid = str(row.get("rid") or "").strip()
    nm_raw = row.get("nm_id") if row.get("nm_id") is not None else row.get("nmId")
    try:
        nm_id = int(nm_raw) if nm_raw is not None and str(nm_raw).strip() != "" else None
    except (TypeError, ValueError):
        nm_id = None
    price_raw = row.get("price")
    try:
        price = float(price_raw) if price_raw is not None else None
    except (TypeError, ValueError):
        price = None
    currency = str(
        row.get("currency_name_short")
        or row.get("currencyNameShort")
        or row.get("currency")
        or ""
    ).strip().upper()
    key = _event_key(
        srid=srid,
        excise_short=excise,
        operation_type=op,
        fiscal_doc_number=fiscal_no,
        fiscal_dt=fiscal_dt,
    )
    return {
        "event_key": key,
        "operation_type": op,
        "srid": srid,
        "rid": rid,
        "nm_id": nm_id,
        "barcode": str(row.get("barcode") or "").strip(),
        "excise_short": excise,
        "fiscal_doc_number": fiscal_no,
        "fiscal_dt": fiscal_dt,
        "fiscal_drive_number": str(
            row.get("fiscal_drive_number") or row.get("fiscalDriveNumber") or ""
        ).strip(),
        "price": price,
        "currency_name": currency,
        "country_name": str(row.get("name") or row.get("countryName") or "").strip(),
        "raw_json": json.dumps(row, ensure_ascii=False),
    }


def _initial_status(norm: dict[str, Any]) -> tuple[str, str]:
    """Queue withdraw without fiscal for CHZ via OTHER primary document.

    Returns may omit fiscal (WB: «если есть»). Keep ``no_fiscal`` reason so
    prepare uses document_type=OTHER instead of RECEIPT.
    """
    op = int(norm.get("operation_type") or 0)
    has_fiscal = bool(norm.get("fiscal_doc_number") and norm.get("fiscal_dt"))
    if op == OP_WITHDRAW and not has_fiscal:
        return STATUS_PENDING, SKIP_NO_FISCAL
    return STATUS_PENDING, ""


def _find_related_events(
    conn: Any,
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    norm: dict[str, Any],
) -> list[dict[str, Any]]:
    """Find local events for the same CIS identity (any fiscal variant)."""
    excise = str(norm.get("excise_short") or "").strip()
    op = int(norm.get("operation_type") or 0)
    if not excise or op not in {OP_WITHDRAW, OP_RETURN}:
        return []
    srid = str(norm.get("srid") or "").strip()
    rid = str(norm.get("rid") or "").strip()
    anchors = sorted({a for a in (srid, rid) if a})
    if anchors:
        ph = ", ".join("?" for _ in anchors)
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT * FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND operation_type = ? AND excise_short = ?
                  AND (
                    (COALESCE(srid, '') <> '' AND srid IN ({ph}))
                    OR (COALESCE(rid, '') <> '' AND rid IN ({ph}))
                  )
                """
            ),
            (user_id, source_id, op, excise, *anchors, *anchors),
        ).fetchall()
    else:
        rows = conn.execute(
            repo._sql(
                """
                SELECT * FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND operation_type = ? AND excise_short = ?
                  AND COALESCE(srid, '') = '' AND COALESCE(rid, '') = ''
                """
            ),
            (user_id, source_id, op, excise),
        ).fetchall()
    return [repo._row_to_dict(r) for r in rows]


def _upgrade_event_fiscal(
    conn: Any,
    repo: ReviewRepository,
    *,
    target: dict[str, Any],
    norm: dict[str, Any],
    now: str,
) -> None:
    """Attach late fiscal (or refresh) onto an existing open event — keep event_key."""
    oid = int(target.get("id") or 0)
    if oid <= 0:
        return
    fiscal_no = str(norm.get("fiscal_doc_number") or "").strip() or str(
        target.get("fiscal_doc_number") or ""
    ).strip()
    fiscal_dt = str(norm.get("fiscal_dt") or "").strip() or str(
        target.get("fiscal_dt") or ""
    ).strip()
    drive = str(norm.get("fiscal_drive_number") or "").strip() or str(
        target.get("fiscal_drive_number") or ""
    ).strip()
    has_fiscal = bool(fiscal_no and fiscal_dt)
    skip = (
        SKIP_NO_FISCAL
        if int(norm.get("operation_type") or 0) == OP_WITHDRAW and not has_fiscal
        else ""
    )
    st = str(target.get("status") or "")
    new_status = (
        STATUS_PENDING
        if st in {STATUS_SKIPPED, STATUS_ERROR, STATUS_READY, STATUS_PENDING}
        else st
    )
    conn.execute(
        repo._sql(
            """
            UPDATE wb_kiz_circulation_events
            SET fiscal_doc_number = ?,
                fiscal_dt = ?,
                fiscal_drive_number = ?,
                price = COALESCE(?, price),
                currency_name = CASE
                    WHEN COALESCE(?, '') <> '' THEN ? ELSE currency_name END,
                country_name = CASE
                    WHEN COALESCE(?, '') <> '' THEN ? ELSE country_name END,
                raw_json = ?,
                status = ?,
                skip_reason = ?,
                error_text = CASE WHEN ? = ? THEN '' ELSE error_text END,
                updated_at = ?
            WHERE id = ?
            """
        ),
        (
            fiscal_no,
            fiscal_dt,
            drive,
            norm.get("price"),
            str(norm.get("currency_name") or ""),
            str(norm.get("currency_name") or ""),
            str(norm.get("country_name") or ""),
            str(norm.get("country_name") or ""),
            str(norm.get("raw_json") or target.get("raw_json") or ""),
            new_status,
            skip,
            new_status,
            STATUS_PENDING,
            now,
            oid,
        ),
    )


def _resolve_sync_action(
    related: list[dict[str, Any]],
    *,
    norm: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Decide insert / upsert / upgrade / suppress for a normalized WB row.

    Returns ``(action, target_row)`` where action is one of:
    insert | upsert | upgrade | suppress
    """
    key = str(norm.get("event_key") or "")
    same_key = next((r for r in related if str(r.get("event_key") or "") == key), None)
    if same_key:
        return "upsert", same_key

    new_has_fiscal = _event_has_fiscal(norm)
    terminal = [
        r
        for r in related
        if str(r.get("status") or "") in {STATUS_SUBMITTED, STATUS_ACCEPTED}
    ]
    if terminal:
        # Already sent under another fiscal variant — do not create a duplicate.
        return "suppress", terminal[0]

    open_rows = [
        r
        for r in related
        if str(r.get("status") or "")
        in {STATUS_PENDING, STATUS_READY, STATUS_ERROR, STATUS_SKIPPED}
    ]
    if new_has_fiscal:
        # Prefer upgrading an open no-fiscal sibling instead of a second event_key.
        nofiscal_open = [r for r in open_rows if not _event_has_fiscal(r)]
        if nofiscal_open:
            return "upgrade", nofiscal_open[0]
        if open_rows:
            # Same CIS already queued under another fiscal key — keep one row.
            return "upgrade", open_rows[0]
    else:
        # Incoming no-fiscal while a fiscal open row already exists — keep fiscal one.
        fiscal_open = [r for r in open_rows if _event_has_fiscal(r)]
        if fiscal_open:
            return "suppress", fiscal_open[0]
        if open_rows:
            # Another no-fiscal open row with different key (legacy) — upgrade first.
            return "upgrade", open_rows[0]

    return "insert", None


def sync_excise_report(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    api_key: str,
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    ensure_kiz_circulation_tables(repo)
    repaired = repair_circulation_queue(repo, user_id=user_id, source_id=source_id)
    try:
        storage = maintain_kiz_circulation_storage(
            repo, user_id=user_id, source_id=source_id, force=True
        )
        repaired.update(storage)
    except Exception as exc:
        logger.exception("maintain_kiz_circulation_storage failed: %s", exc)
    period = resolve_excise_period(date_from=date_from, date_to=date_to)
    date_from_s = str(period["date_from"])
    date_to_s = str(period["date_to"])

    now = datetime.now(timezone.utc).isoformat()
    log: list[str] = []
    _append_log(
        log,
        f"WB: выгрузка за выбранные даты {date_from_s}…{date_to_s} "
        f"({period['days']} дн., один запрос)",
    )
    if repaired.get("returns_fixed"):
        _append_log(log, f"восстановлено возвратов без чека: {repaired['returns_fixed']}")
    if repaired.get("withdraw_skipped"):
        _append_log(
            log,
            f"выводы без чека из error → очередь OTHER: {repaired['withdraw_skipped']}",
        )
    if repaired.get("withdraw_requeued"):
        _append_log(
            log,
            f"выводы без чека из skipped → очередь OTHER: {repaired['withdraw_requeued']}",
        )
    if repaired.get("orphan_submitted"):
        _append_log(
            log,
            f"восстановлено submitted без chz_doc_id: {repaired['orphan_submitted']}",
        )
    if repaired.get("legacy_skipped"):
        _append_log(
            log,
            f"возвращено из skipped в очередь: {repaired['legacy_skipped']}",
        )
    if repaired.get("raw_json_cleared") or repaired.get("events_purged"):
        _append_log(
            log,
            "очистка хранения: "
            f"raw_json={repaired.get('raw_json_cleared') or 0}, "
            f"событий>{EVENT_RETENTION_DAYS}д={repaired.get('events_purged') or 0}, "
            f"runs={repaired.get('runs_purged') or 0}, "
            f"docs={repaired.get('docs_purged') or 0}",
        )

    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                """
                INSERT INTO wb_kiz_circulation_runs (
                    user_id, source_id, date_from, date_to, stage, status,
                    created_at, log_text
                ) VALUES (?, ?, ?, ?, 'wb_sync', 'running', ?, ?)
                RETURNING id
                """
            ),
            (user_id, source_id, date_from_s, date_to_s, now, ""),
        ).fetchone()
        run_id = int(repo._row_to_dict(row).get("id") or 0) if row else 0

    try:
        rows = fetch_wb_excise_report(
            api_key=api_key, date_from=date_from_s, date_to=date_to_s
        )
    except Exception as exc:
        _append_log(log, f"Ошибка WB: {exc}")
        _finish_run(
            repo,
            run_id=run_id,
            status="error",
            log=log,
            error_text=str(exc),
        )
        raise

    _append_log(log, f"получено {len(rows)} строк")
    inserted = 0
    updated = 0
    skipped = 0
    suppressed = 0
    withdraw_n = 0
    return_n = 0
    insert_errors = 0
    last_key = ""
    last_fiscal = ""
    sent_identities = _load_sent_cis_identities(
        repo, user_id=user_id, source_id=source_id
    )

    with repo._connect() as conn:
        for raw in rows:
            norm = _normalize_row(raw)
            if not norm:
                skipped += 1
                continue
            status, skip_reason = _initial_status(norm)
            if int(norm["operation_type"]) == OP_WITHDRAW:
                withdraw_n += 1
            else:
                return_n += 1
            try:
                related = _find_related_events(
                    conn,
                    repo,
                    user_id=user_id,
                    source_id=source_id,
                    norm=norm,
                )
                action, target = _resolve_sync_action(related, norm=norm)
                if action == "insert":
                    ident = _cis_identity(
                        srid=str(norm.get("srid") or ""),
                        rid=str(norm.get("rid") or ""),
                        excise_short=str(norm.get("excise_short") or ""),
                        operation_type=int(norm.get("operation_type") or 0),
                    )
                    if ident[1] and ident in sent_identities:
                        action = "suppress"
                        target = None
                if action == "suppress":
                    suppressed += 1
                    skipped += 1
                    continue
                if action == "upgrade" and target:
                    _upgrade_event_fiscal(
                        conn, repo, target=target, norm=norm, now=now
                    )
                    updated += 1
                    last_key = str(target.get("event_key") or norm["event_key"])
                    last_fiscal = (
                        str(norm.get("fiscal_dt") or target.get("fiscal_dt") or "")
                        or last_fiscal
                    )
                    continue

                cur = conn.execute(
                    repo._sql(
                        """
                        INSERT INTO wb_kiz_circulation_events (
                            user_id, source_id, event_key, operation_type, srid, rid,
                            nm_id, barcode, excise_short, fiscal_doc_number, fiscal_dt,
                            fiscal_drive_number, price, currency_name, country_name,
                            status, skip_reason, raw_json, run_id, created_at, updated_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        ON CONFLICT (user_id, source_id, event_key) DO UPDATE SET
                            price = COALESCE(EXCLUDED.price, wb_kiz_circulation_events.price),
                            currency_name = CASE
                                WHEN EXCLUDED.currency_name <> '' THEN EXCLUDED.currency_name
                                ELSE wb_kiz_circulation_events.currency_name
                            END,
                            country_name = CASE
                                WHEN EXCLUDED.country_name <> '' THEN EXCLUDED.country_name
                                ELSE wb_kiz_circulation_events.country_name
                            END,
                            fiscal_doc_number = CASE
                                WHEN EXCLUDED.fiscal_doc_number <> '' THEN EXCLUDED.fiscal_doc_number
                                ELSE wb_kiz_circulation_events.fiscal_doc_number
                            END,
                            fiscal_dt = CASE
                                WHEN EXCLUDED.fiscal_dt <> '' THEN EXCLUDED.fiscal_dt
                                ELSE wb_kiz_circulation_events.fiscal_dt
                            END,
                            fiscal_drive_number = CASE
                                WHEN EXCLUDED.fiscal_drive_number <> '' THEN EXCLUDED.fiscal_drive_number
                                ELSE wb_kiz_circulation_events.fiscal_drive_number
                            END,
                            raw_json = EXCLUDED.raw_json,
                            updated_at = EXCLUDED.updated_at,
                            status = CASE
                                WHEN wb_kiz_circulation_events.status IN ('submitted', 'accepted')
                                    THEN wb_kiz_circulation_events.status
                                WHEN EXCLUDED.status = 'pending' THEN 'pending'
                                ELSE wb_kiz_circulation_events.status
                            END,
                            skip_reason = CASE
                                WHEN wb_kiz_circulation_events.status IN ('submitted', 'accepted')
                                    THEN wb_kiz_circulation_events.skip_reason
                                WHEN EXCLUDED.status = 'pending' THEN EXCLUDED.skip_reason
                                ELSE wb_kiz_circulation_events.skip_reason
                            END,
                            error_text = CASE
                                WHEN wb_kiz_circulation_events.status IN ('submitted', 'accepted')
                                    THEN wb_kiz_circulation_events.error_text
                                WHEN EXCLUDED.status = 'pending' THEN ''
                                ELSE wb_kiz_circulation_events.error_text
                            END
                        """
                    ),
                    (
                        user_id,
                        source_id,
                        norm["event_key"],
                        int(norm["operation_type"]),
                        norm["srid"],
                        norm["rid"],
                        norm["nm_id"],
                        norm["barcode"],
                        norm["excise_short"],
                        norm["fiscal_doc_number"],
                        norm["fiscal_dt"],
                        norm["fiscal_drive_number"],
                        norm["price"],
                        norm["currency_name"],
                        norm["country_name"],
                        status,
                        skip_reason,
                        norm["raw_json"],
                        run_id,
                        now,
                        now,
                    ),
                )
                rc = int(getattr(cur, "rowcount", 0) or 0)
                if rc > 0:
                    # Distinguish insert vs update by comparing created_at/updated_at.
                    chk = conn.execute(
                        repo._sql(
                            "SELECT created_at, updated_at FROM wb_kiz_circulation_events "
                            "WHERE user_id = ? AND source_id = ? AND event_key = ?"
                        ),
                        (user_id, source_id, norm["event_key"]),
                    ).fetchone()
                    if chk:
                        cd = repo._row_to_dict(chk)
                        if str(cd.get("created_at") or "") == str(cd.get("updated_at") or ""):
                            inserted += 1
                        else:
                            updated += 1
                    else:
                        inserted += 1
                    last_key = norm["event_key"]
                    last_fiscal = norm["fiscal_dt"] or last_fiscal
                else:
                    skipped += 1
            except Exception as exc:
                insert_errors += 1
                skipped += 1
                logger.exception(
                    "wb_kiz_circulation insert failed key=%s: %s",
                    norm.get("event_key"),
                    exc,
                )
                _append_log(log, f"ошибка INSERT {norm.get('event_key', '')[:12]}…: {exc}")

        conn.execute(
            repo._sql(
                """
                INSERT INTO wb_kiz_circulation_cursor (
                    user_id, source_id, last_date_to, last_event_key, last_fiscal_dt,
                    last_run_at, last_run_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id, source_id) DO UPDATE SET
                    last_date_to = EXCLUDED.last_date_to,
                    last_event_key = COALESCE(NULLIF(EXCLUDED.last_event_key, ''), wb_kiz_circulation_cursor.last_event_key),
                    last_fiscal_dt = COALESCE(NULLIF(EXCLUDED.last_fiscal_dt, ''), wb_kiz_circulation_cursor.last_fiscal_dt),
                    last_run_at = EXCLUDED.last_run_at,
                    last_run_id = EXCLUDED.last_run_id,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            (
                user_id,
                source_id,
                date_to_s,
                last_key,
                last_fiscal,
                now,
                run_id,
                now,
            ),
        )

    _append_log(
        log,
        f"новых: {inserted}, обновлено: {updated}, пропуск: {skipped}"
        + (f", без дублей: {suppressed}" if suppressed else "")
        + (f", ошибок INSERT: {insert_errors}" if insert_errors else "")
        + f", вывод: {withdraw_n}, возврат: {return_n}",
    )
    _append_log(
        log,
        f"период сохранён → {date_to_s}"
        + (f" / {last_key[:12]}…" if last_key else ""),
    )
    _finish_run(
        repo,
        run_id=run_id,
        status="ok",
        log=log,
        fetched=len(rows),
        inserted=inserted,
        skipped=skipped,
        withdraw_count=withdraw_n,
        return_count=return_n,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "date_from": date_from_s,
        "date_to": date_to_s,
        "fetched": len(rows),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "insert_errors": insert_errors,
        "withdraw_count": withdraw_n,
        "return_count": return_n,
        "log": "\n".join(log),
        "cursor": get_cursor(repo, user_id=user_id, source_id=source_id),
    }


def _finish_run(
    repo: ReviewRepository,
    *,
    run_id: int,
    status: str,
    log: list[str],
    fetched: int = 0,
    inserted: int = 0,
    skipped: int = 0,
    withdraw_count: int = 0,
    return_count: int = 0,
    error_text: str = "",
) -> None:
    if run_id <= 0:
        return
    now = datetime.now(timezone.utc).isoformat()
    with repo._connect() as conn:
        conn.execute(
            repo._sql(
                """
                UPDATE wb_kiz_circulation_runs SET
                    status = ?, fetched = ?, inserted = ?, skipped = ?,
                    withdraw_count = ?, return_count = ?, error_text = ?,
                    log_text = ?, finished_at = ?
                WHERE id = ?
                """
            ),
            (
                status,
                fetched,
                inserted,
                skipped,
                withdraw_count,
                return_count,
                str(error_text or "")[:2000],
                "\n".join(log)[:50000],
                now,
                run_id,
            ),
        )


def list_events(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    status: str = "",
    operation_type: int | None = None,
    limit: int = 200,
    order: str = "desc",
    api_key: str = "",
    hydrate_orders: bool = False,
) -> list[dict[str, Any]]:
    ensure_kiz_circulation_tables(repo)
    lim = max(1, min(int(limit or 200), 5000))
    clauses = ["user_id = ?", "source_id = ?"]
    params: list[Any] = [user_id, source_id]
    if status:
        clauses.append("status = ?")
        params.append(str(status))
    if operation_type in {OP_WITHDRAW, OP_RETURN}:
        clauses.append("operation_type = ?")
        params.append(int(operation_type))
    params.append(lim)
    order_sql = (
        "ORDER BY fiscal_dt ASC NULLS FIRST, id ASC"
        if str(order or "").lower() == "asc"
        else "ORDER BY fiscal_dt DESC NULLS LAST, id DESC"
    )
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"SELECT * FROM wb_kiz_circulation_events WHERE {' AND '.join(clauses)} "
                f"{order_sql} LIMIT ?"
            ),
            tuple(params),
        ).fetchall()
    out = []
    for r in rows:
        d = repo._row_to_dict(r)
        d.pop("raw_json", None)
        out.append(d)
    _attach_order_ids_to_events(
        repo,
        user_id=user_id,
        source_id=source_id,
        events=out,
        api_key=api_key,
        hydrate=bool(hydrate_orders and api_key),
    )
    return out


def _attach_order_ids_to_events(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    events: list[dict[str, Any]],
    api_key: str = "",
    hydrate: bool = False,
) -> None:
    """Attach numeric FBS ``order_id`` + Marketplace status via srid/rid join."""
    if not events:
        return
    from . import wb_fbs as wb_fbs_mod

    keys: list[str] = []
    for ev in events:
        srid = str(ev.get("srid") or "").strip()
        rid = str(ev.get("rid") or "").strip()
        if srid:
            keys.append(srid)
        if rid and rid != srid:
            keys.append(rid)

    if hydrate and api_key and keys:
        try:
            wb_fbs_mod.hydrate_orders_for_kiz_srids(
                repo,
                user_id=user_id,
                source_id=source_id,
                srids=keys,
                api_key=api_key,
            )
        except Exception as exc:
            logger.warning("hydrate_orders_for_kiz_srids failed: %s", exc)

    by_srid = wb_fbs_mod.order_ids_by_srids(
        repo, user_id=user_id, source_id=source_id, srids=keys
    )
    order_ids: list[int] = []
    for ev in events:
        srid = str(ev.get("srid") or "").strip()
        rid = str(ev.get("rid") or "").strip()
        oid = by_srid.get(srid) or by_srid.get(rid) or None
        if oid:
            try:
                oid_i = int(oid)
            except (TypeError, ValueError):
                oid_i = 0
            ev["order_id"] = oid_i if oid_i > 0 else None
            if oid_i > 0:
                order_ids.append(oid_i)
        else:
            ev["order_id"] = None
        ev["order_status_label"] = ""
        ev["order_wb_status"] = ""
        ev["order_supplier_status"] = ""
        ev["order_cancel_reason"] = ""

    status_map = wb_fbs_mod.load_order_status_map(
        repo, user_id=user_id, source_id=source_id, order_ids=order_ids
    )
    for ev in events:
        oid = ev.get("order_id")
        if not oid:
            continue
        st = status_map.get(int(oid)) or {}
        ev["order_status_label"] = str(st.get("order_status_label") or "").strip()
        ev["order_wb_status"] = str(st.get("wb_status") or "").strip()
        ev["order_supplier_status"] = str(st.get("supplier_status") or "").strip()
        ev["order_cancel_reason"] = str(st.get("cancel_reason_label") or "").strip()


def _event_is_sold_for_chz(ev: dict[str, Any]) -> bool:
    """Withdraw to CHZ only when Marketplace wbStatus is sold («выкуплен»)."""
    return str(ev.get("order_wb_status") or "").strip().lower() == "sold"


def _event_is_cancelled_for_chz(ev: dict[str, Any]) -> bool:
    """Return-to-circulation only for отказные / cancelled Marketplace statuses."""
    from . import wb_fbs as wb_fbs_mod

    return bool(
        wb_fbs_mod._is_cancelled_status(
            supplier_status=ev.get("order_supplier_status") or "",
            wb_status=ev.get("order_wb_status") or "",
        )
    )


def _withdraw_not_sold_reason(ev: dict[str, Any]) -> str:
    """Empty if withdraw is allowed; otherwise human skip reason (fail closed)."""
    if int(ev.get("operation_type") or 0) != OP_WITHDRAW:
        return ""
    oid = ev.get("order_id")
    try:
        oid_i = int(oid) if oid is not None else 0
    except (TypeError, ValueError):
        oid_i = 0
    if oid_i <= 0:
        return "нет связи с заказом FBS"
    if _event_is_sold_for_chz(ev):
        return ""
    label = (
        str(ev.get("order_status_label") or "").strip()
        or str(ev.get("order_wb_status") or "").strip()
        or "неизвестно"
    )
    return f"заказ не выкуплен ({label})"


def _return_not_cancelled_reason(ev: dict[str, Any]) -> str:
    """Empty if return-to-circulation is allowed; otherwise skip reason (fail closed)."""
    if int(ev.get("operation_type") or 0) != OP_RETURN:
        return ""
    oid = ev.get("order_id")
    try:
        oid_i = int(oid) if oid is not None else 0
    except (TypeError, ValueError):
        oid_i = 0
    if oid_i <= 0:
        return "нет связи с заказом FBS"
    if _event_is_cancelled_for_chz(ev):
        return ""
    label = (
        str(ev.get("order_status_label") or "").strip()
        or str(ev.get("order_wb_status") or "").strip()
        or "неизвестно"
    )
    return f"заказ не отказной ({label})"


def list_events_for_chz(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    limit: int = PREPARE_EVENT_LIMIT,
    event_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Events eligible for CHZ submit: pending + recoverable error + failed submitted.

    Includes withdraw-without-fiscal (``no_fiscal``) as pending/skipped-legacy —
    they go out as LK_RECEIPT with primary document OTHER.

    When ``event_keys`` is set, only those keys are considered (still must be eligible).
    """
    ensure_kiz_circulation_tables(repo)
    key_filter = [
        str(k).strip()
        for k in (event_keys or [])
        if str(k or "").strip()
    ]
    # Cap IN-list size; UI selection is practical well below this.
    if key_filter:
        key_filter = key_filter[:5000]
    lim = max(1, min(int(limit or PREPARE_EVENT_LIMIT), 5000))
    if key_filter:
        lim = min(max(lim, len(key_filter)), 5000)
    fail_list = sorted(CHZ_STATUS_FAILED)
    fail_placeholders = ", ".join(["?"] * len(fail_list)) if fail_list else "NULL"
    params: list[Any] = [
        user_id,
        source_id,
        SKIP_NO_FISCAL,
        STATUS_SKIPPED,
        OP_WITHDRAW,
        SKIP_NO_FISCAL,
        STATUS_SUBMITTED,
        *fail_list,
    ]
    key_sql = ""
    if key_filter:
        key_placeholders = ", ".join(["?"] * len(key_filter))
        key_sql = f" AND event_key IN ({key_placeholders}) "
        params.extend(key_filter)
    params.append(lim)
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                f"""
                SELECT * FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND (
                    status IN ('pending', 'ready')
                    OR (
                      status = 'error'
                      AND NOT (operation_type = 1 AND skip_reason = ?)
                    )
                    OR (
                      status = ?
                      AND operation_type = ?
                      AND skip_reason = ?
                    )
                    OR (
                      status = ?
                      AND COALESCE(chz_doc_id, '') = ''
                    )
                    OR (
                      status = 'submitted'
                      AND UPPER(COALESCE(chz_status, '')) IN ({fail_placeholders})
                    )
                  )
                  {key_sql}
                ORDER BY
                  CASE WHEN fiscal_dt IS NULL OR fiscal_dt = '' THEN 1 ELSE 0 END,
                  fiscal_dt ASC,
                  id ASC
                LIMIT ?
                """
            ),
            tuple(params),
        ).fetchall()
    out = []
    for r in rows:
        d = repo._row_to_dict(r)
        d.pop("raw_json", None)
        # Drop legacy Russian no-fiscal withdraw errors (not matched by ASCII code).
        if (
            int(d.get("operation_type") or 0) == OP_WITHDRAW
            and str(d.get("status") or "") == STATUS_ERROR
            and _is_no_fiscal_reason(str(d.get("skip_reason") or ""))
        ):
            continue
        out.append(d)
    return out


def _load_sent_cis_identities(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> set[tuple[str, str, int]]:
    """Identities already in CHZ — must not be sent again.

    Sources:
    - live events: accepted, or submitted with ``chz_doc_id``
    - forever slim registry (survives 6-month event purge)
    """
    ensure_kiz_circulation_tables(repo)
    out: set[tuple[str, str, int]] = set()
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT srid, rid, excise_short, operation_type
                FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND COALESCE(excise_short, '') <> ''
                  AND (
                    status = ?
                    OR (
                      status = ?
                      AND COALESCE(chz_doc_id, '') <> ''
                    )
                  )
                """
            ),
            (user_id, source_id, STATUS_ACCEPTED, STATUS_SUBMITTED),
        ).fetchall()
        for r in rows:
            d = repo._row_to_dict(r)
            out.add(
                _cis_identity(
                    srid=str(d.get("srid") or ""),
                    rid=str(d.get("rid") or ""),
                    excise_short=str(d.get("excise_short") or ""),
                    operation_type=int(d.get("operation_type") or 0),
                )
            )
        reg = conn.execute(
            repo._sql(
                """
                SELECT anchor, excise_short, operation_type
                FROM wb_kiz_sent_cis
                WHERE user_id = ? AND source_id = ?
                  AND COALESCE(excise_short, '') <> ''
                """
            ),
            (user_id, source_id),
        ).fetchall()
        for r in reg:
            d = repo._row_to_dict(r)
            anchor = str(d.get("anchor") or "").strip()
            out.add(
                (
                    anchor,
                    str(d.get("excise_short") or "").strip(),
                    int(d.get("operation_type") or 0),
                )
            )
    return out


def _close_deduped_prepare_events(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    skipped: list[dict[str, Any]],
) -> int:
    """Persist prepare-time dedupe skips so the queue does not clog."""
    by_reason: dict[str, list[str]] = {}
    for row in skipped:
        reason = str(row.get("skip_reason") or "").strip()
        if reason not in _TERMINAL_SKIP_REASONS:
            continue
        key = str(row.get("event_key") or "").strip()
        if not key:
            continue
        by_reason.setdefault(reason, []).append(key)
    if not by_reason:
        return 0
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    closed = 0
    with repo._connect() as conn:
        for reason, keys in by_reason.items():
            uniq = sorted(set(keys))
            for chunk in _chunked(uniq, 200):
                ph = ", ".join("?" for _ in chunk)
                cur = conn.execute(
                    repo._sql(
                        f"""
                        UPDATE wb_kiz_circulation_events
                        SET status = ?, skip_reason = ?, updated_at = ?
                        WHERE user_id = ? AND source_id = ?
                          AND event_key IN ({ph})
                          AND status NOT IN (?, ?)
                        """
                    ),
                    (
                        STATUS_SKIPPED,
                        reason,
                        now,
                        user_id,
                        source_id,
                        *chunk,
                        STATUS_SUBMITTED,
                        STATUS_ACCEPTED,
                    ),
                )
                closed += int(getattr(cur, "rowcount", 0) or 0)
    return closed


def _dedupe_events_for_prepare(
    events: list[dict[str, Any]],
    *,
    sent_identities: set[tuple[str, str, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop already-sent CIS and collapse fiscal/no-fiscal duplicates in one batch."""
    kept: dict[tuple[str, str, int], dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for ev in events:
        ident = _cis_identity(
            srid=str(ev.get("srid") or ""),
            rid=str(ev.get("rid") or ""),
            excise_short=str(ev.get("excise_short") or ""),
            operation_type=int(ev.get("operation_type") or 0),
        )
        if not ident[1]:
            skipped.append({**ev, "skip_reason": "пустой КИЗ"})
            continue
        if ident in sent_identities:
            skipped.append({**ev, "skip_reason": "already_sent"})
            continue
        prev = kept.get(ident)
        if prev is None:
            kept[ident] = ev
            continue
        # Prefer the variant with fiscal receipt.
        if _event_has_fiscal(ev) and not _event_has_fiscal(prev):
            skipped.append({**prev, "skip_reason": "duplicate_nofiscal"})
            kept[ident] = ev
        else:
            skipped.append({**ev, "skip_reason": "duplicate"})
    return list(kept.values()), skipped


def reconcile_submitted_with_chz(
    repo: ReviewRepository,
    client: ChzTrueApiClient,
    *,
    user_id: int,
    source_id: int,
    limit: int = 500,
) -> dict[str, int]:
    """Poll CHZ for in-flight submitted docs and update local statuses."""
    ensure_kiz_circulation_tables(repo)
    lim = max(1, min(int(limit or 500), 2000))
    with repo._connect() as conn:
        rows = conn.execute(
            repo._sql(
                """
                SELECT event_key, chz_doc_id, chz_status
                FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                  AND status = ?
                  AND COALESCE(chz_doc_id, '') <> ''
                ORDER BY updated_at ASC NULLS FIRST, id ASC
                LIMIT ?
                """
            ),
            (user_id, source_id, STATUS_SUBMITTED, lim),
        ).fetchall()
    by_doc: dict[str, list[str]] = {}
    for r in rows:
        d = repo._row_to_dict(r)
        doc_id = str(d.get("chz_doc_id") or "").strip()
        key = str(d.get("event_key") or "").strip()
        if not doc_id or not key:
            continue
        # Skip already-classified terminal failures (handled by prepare retry).
        st = str(d.get("chz_status") or "").strip().upper()
        if st in CHZ_STATUS_FAILED or st in CHZ_STATUS_SUCCESS:
            continue
        by_doc.setdefault(doc_id, []).append(key)

    checked = 0
    accepted = 0
    failed = 0
    for doc_id, keys in by_doc.items():
        checked += 1
        try:
            info = client.document_info(doc_id)
            chz_status = str(
                info.get("status")
                or info.get("docStatus")
                or info.get("state")
                or ""
            )
            final = apply_chz_doc_status(
                repo,
                user_id=user_id,
                source_id=source_id,
                event_keys=keys,
                chz_doc_id=doc_id,
                chz_status=chz_status or "submitted",
                error_text=extract_chz_doc_errors(info),
            )
            if final == STATUS_ACCEPTED:
                accepted += 1
            elif final == STATUS_ERROR:
                failed += 1
        except Exception as exc:
            logger.warning("CHZ reconcile doc %s failed: %s", doc_id, exc)
    return {
        "docs_checked": checked,
        "accepted": accepted,
        "failed": failed,
        "events": sum(len(v) for v in by_doc.values()),
    }


def get_overview(
    repo: ReviewRepository, *, user_id: int, source_id: int
) -> dict[str, Any]:
    ensure_kiz_circulation_tables(repo)
    cursor = get_cursor(repo, user_id=user_id, source_id=source_id)
    with repo._connect() as conn:
        counts = conn.execute(
            repo._sql(
                """
                SELECT status, operation_type, COUNT(*) AS cnt
                FROM wb_kiz_circulation_events
                WHERE user_id = ? AND source_id = ?
                GROUP BY status, operation_type
                """
            ),
            (user_id, source_id),
        ).fetchall()
        last_run = conn.execute(
            repo._sql(
                "SELECT * FROM wb_kiz_circulation_runs WHERE user_id = ? AND source_id = ? "
                "ORDER BY id DESC LIMIT 1"
            ),
            (user_id, source_id),
        ).fetchone()
    by_status: dict[str, int] = {}
    pending_withdraw = 0
    pending_return = 0
    for r in counts:
        d = repo._row_to_dict(r)
        st = str(d.get("status") or "")
        op = int(d.get("operation_type") or 0)
        cnt = int(d.get("cnt") or 0)
        by_status[st] = by_status.get(st, 0) + cnt
        if st in {STATUS_PENDING, STATUS_READY, STATUS_ERROR} and op == OP_WITHDRAW:
            pending_withdraw += cnt
        if st in {STATUS_PENDING, STATUS_READY, STATUS_ERROR} and op == OP_RETURN:
            pending_return += cnt
    run = repo._row_to_dict(last_run) if last_run else None
    return {
        "cursor": cursor,
        "counts": by_status,
        "pending_withdraw": pending_withdraw,
        "pending_return": pending_return,
        "last_run": run,
        "chz": get_chz_settings(repo, user_id=user_id),
    }


def get_run(repo: ReviewRepository, *, user_id: int, run_id: int) -> dict[str, Any] | None:
    ensure_kiz_circulation_tables(repo)
    with repo._connect() as conn:
        row = conn.execute(
            repo._sql(
                "SELECT * FROM wb_kiz_circulation_runs WHERE id = ? AND user_id = ?"
            ),
            (run_id, user_id),
        ).fetchone()
    return repo._row_to_dict(row) if row else None


def _price_for_chz(ev: dict[str, Any]) -> int | None:
    """True API ``product_cost`` is in kopecks (incl. VAT when applicable).

    WB Analytics excise-report ``price`` is in major currency units (rubles).
    """
    if ev.get("price") is None:
        return None
    cur = str(ev.get("currency_name") or "").strip().upper()
    if cur and cur not in {"RUB", "RUR", "₽", "РУБ"}:
        return None
    try:
        rub = float(ev["price"])
    except (TypeError, ValueError):
        return None
    if rub < 0:
        return None
    return int(round(rub * 100))


def _normalize_cis_for_chz(raw: str) -> str:
    """Strip GS1 separators / control chars from a Data Matrix CIS string."""
    s = str(raw or "").strip()
    if not s:
        return ""
    # FNC1 / group separators often appear as \\x1d or are pasted as commas.
    s = s.replace("\x1d", "").replace("\x1e", "").replace("\x1f", "").replace("\x1c", "")
    s = s.replace("\u001d", "").replace("\u001e", "")
    # Keep printable ASCII only (CIS alphabet).
    s = "".join(ch for ch in s if 32 <= ord(ch) <= 126)
    return s.strip()


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    n = max(1, int(size))
    return [items[i : i + n] for i in range(0, len(items), n)]


def extract_chz_doc_errors(info: dict[str, Any] | None) -> str:
    """Best-effort human text from True API document_info payload."""
    if not isinstance(info, dict):
        return ""
    chunks: list[str] = []
    for key in (
        "errors",
        "commonErrors",
        "common_errors",
        "error_messages",
        "errorMessages",
        "rejectionReason",
        "rejection_reason",
    ):
        val = info.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    msg = (
                        item.get("message")
                        or item.get("error")
                        or item.get("description")
                        or item.get("text")
                        or ""
                    )
                    code = item.get("code") or item.get("errorCode") or ""
                    line = " ".join(str(x) for x in (code, msg) if x).strip()
                    if line:
                        chunks.append(line)
                elif item:
                    chunks.append(str(item))
        elif isinstance(val, str) and val.strip():
            chunks.append(val.strip())
        elif isinstance(val, dict):
            msg = val.get("message") or val.get("description") or ""
            if msg:
                chunks.append(str(msg))
    for key in ("description", "error", "error_message", "body"):
        val = info.get(key)
        if isinstance(val, str) and val.strip() and val.strip() not in chunks:
            chunks.append(val.strip())
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return "; ".join(out)[:1800]


def prepare_chz_batches(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    limit: int = PREPARE_EVENT_LIMIT,
    event_keys: list[str] | None = None,
    api_key: str = "",
) -> dict[str, Any]:
    """Build unsigned CHZ document payloads grouped by operation + receipt.

    Withdraw (вывод) is allowed only when Marketplace ``wbStatus=sold``.
    ``api_key`` is the FBS Marketplace token (hydrate sold/archive for srid join).
    """
    settings = get_chz_settings(repo, user_id=user_id)
    if not settings.get("is_enabled"):
        raise ValueError("ЧЗ выключен в Настройки → ЧЗ")
    inn = str(settings.get("participant_inn") or "").strip()
    if not inn:
        raise ValueError("Укажите ИНН участника в Настройки → ЧЗ")
    pg = str(settings.get("product_group") or "").strip()
    if not pg:
        raise ValueError("Укажите товарную группу (pg) в Настройки → ЧЗ")
    if pg.isdigit():
        raise ValueError(
            "Товарная группа (pg) — код True API (например lp, shoes), не число"
        )

    queue_repair = repair_circulation_queue(
        repo, user_id=user_id, source_id=source_id
    )
    try:
        storage = maintain_kiz_circulation_storage(
            repo, user_id=user_id, source_id=source_id
        )
        queue_repair.update(storage)
    except Exception as exc:
        logger.exception("maintain_kiz_circulation_storage failed: %s", exc)
    lim = max(1, min(int(limit or PREPARE_EVENT_LIMIT), 5000))
    wanted_keys = [
        str(k).strip()
        for k in (event_keys or [])
        if str(k or "").strip()
    ] or None
    events_raw = list_events_for_chz(
        repo,
        user_id=user_id,
        source_id=source_id,
        limit=lim,
        event_keys=wanted_keys,
    )
    # Join Marketplace order + status (hydrate archive/sold when key present).
    _attach_order_ids_to_events(
        repo,
        user_id=user_id,
        source_id=source_id,
        events=events_raw,
        api_key=api_key,
        hydrate=bool(str(api_key or "").strip()),
    )
    sent_identities = _load_sent_cis_identities(
        repo, user_id=user_id, source_id=source_id
    )
    events, pre_skipped = _dedupe_events_for_prepare(
        events_raw, sent_identities=sent_identities
    )
    try:
        _close_deduped_prepare_events(
            repo, user_id=user_id, source_id=source_id, skipped=pre_skipped
        )
    except Exception as exc:
        logger.exception("close deduped prepare events failed: %s", exc)

    withdraw_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    # Withdraw without fiscal → OTHER primary document (DISTANCE), grouped by date.
    withdraw_other_groups: dict[str, list[dict[str, Any]]] = {}
    return_items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = list(pre_skipped)
    warnings: list[str] = []
    other_doc_date = _moscow_today()
    not_sold_n = 0
    not_cancelled_n = 0

    for ev in events:
        op = int(ev.get("operation_type") or 0)
        fiscal_no = str(ev.get("fiscal_doc_number") or "").strip()
        fiscal_dt = str(ev.get("fiscal_dt") or "").strip()
        cis = _normalize_cis_for_chz(str(ev.get("excise_short") or ""))
        if not cis:
            skipped.append({**ev, "skip_reason": "пустой КИЗ"})
            continue
        ev = {**ev, "excise_short": cis}
        if op == OP_WITHDRAW:
            not_sold = _withdraw_not_sold_reason(ev)
            if not_sold:
                not_sold_n += 1
                skipped.append({**ev, "skip_reason": not_sold})
                continue
            if fiscal_no and fiscal_dt:
                withdraw_groups.setdefault((fiscal_no, fiscal_dt), []).append(ev)
            else:
                # Official True API path: DISTANCE + document_type=OTHER when no receipt.
                day = fiscal_dt or other_doc_date
                withdraw_other_groups.setdefault(day, []).append(ev)
        elif op == OP_RETURN:
            not_cancelled = _return_not_cancelled_reason(ev)
            if not_cancelled:
                not_cancelled_n += 1
                skipped.append({**ev, "skip_reason": not_cancelled})
                continue
            return_items.append(ev)
        else:
            skipped.append({**ev, "skip_reason": "неизвестный тип"})

    kpp = str(settings.get("kpp") or "").strip()
    fias_id = str(settings.get("fias_id") or "").strip()
    if not kpp or not fias_id:
        place = resolve_chz_place_details(
            repo, user_id=user_id, participant_inn=inn
        )
        if not kpp:
            kpp = str(place.get("kpp") or "").strip()
        if not fias_id:
            fias_id = str(place.get("fias_id") or "").strip()
    # ИП (12 цифр): КПП в LK_RECEIPT не передаётся.
    if len(re.sub(r"\D", "", inn)) == 12:
        kpp = ""
    # Soft-skip withdraw if DISTANCE place incomplete — still process returns.
    if (withdraw_groups or withdraw_other_groups) and (not fias_id or (len(re.sub(r"\D", "", inn)) == 10 and not kpp)):
        warnings.append(
            "Вывод DISTANCE пропущен: укажите КПП (для ООО) и ФИАС МОД в Настройки → ЧЗ "
            "— те же, что в профиле Честного знака (вкладка МОД), "
            "либо у юр. лица с этим ИНН"
        )
        for group in withdraw_groups.values():
            for ev in group:
                skipped.append({**ev, "skip_reason": "нет КПП/ФИАС у юр. лица"})
        for group in withdraw_other_groups.values():
            for ev in group:
                skipped.append({**ev, "skip_reason": "нет КПП/ФИАС у юр. лица"})
        withdraw_groups = {}
        withdraw_other_groups = {}
    elif withdraw_groups or withdraw_other_groups:
        mod_parts = [f"ИНН {inn}"]
        if kpp:
            mod_parts.append(f"КПП {kpp}")
        mod_parts.append(f"ФИАС {fias_id}")
        warnings.append(
            "МОД в документах: "
            + ", ".join(mod_parts)
            + " — должен совпадать с действующим МОД в профиле ЧЗ"
        )
    if not_sold_n:
        warnings.append(
            f"Пропущено выводов без статуса «выкуплен»: {not_sold_n} "
            "(в ЧЗ уходят только заказы с wbStatus=sold; "
            "на сборке / в доставке — нельзя)"
        )
    if not_cancelled_n:
        warnings.append(
            f"Пропущено возвратов без статуса отказа: {not_cancelled_n} "
            "(в оборот возвращаются только отказные / отменённые)"
        )

    documents: list[dict[str, Any]] = []
    for (fiscal_no, fiscal_dt), group in withdraw_groups.items():
        for part_idx, part in enumerate(_chunked(group, CHZ_PRODUCTS_PER_DOC), start=1):
            products = []
            for ev in part:
                product: dict[str, Any] = {"cis": ev["excise_short"]}
                cost = _price_for_chz(ev)
                if cost is not None:
                    product["product_cost"] = cost
                products.append(product)
            doc_body = build_lk_receipt_document(
                inn=inn,
                document_number=fiscal_no,
                document_date=fiscal_dt,
                products=products,
                kpp=kpp,
                fias_id=fias_id,
            )
            suffix = f" · часть {part_idx}" if len(group) > CHZ_PRODUCTS_PER_DOC else ""
            documents.append(
                {
                    "doc_type": "LK_RECEIPT",
                    "product_group": pg,
                    "title": f"Вывод · чек {fiscal_no} · {fiscal_dt}{suffix}",
                    "event_keys": [e["event_key"] for e in part],
                    "product_document": doc_body,
                    "sign_payload_b64": _b64_json(doc_body),
                }
            )

    for doc_date, group in withdraw_other_groups.items():
        for part_idx, part in enumerate(_chunked(group, CHZ_PRODUCTS_PER_DOC), start=1):
            products = []
            for ev in part:
                product: dict[str, Any] = {"cis": ev["excise_short"]}
                cost = _price_for_chz(ev)
                if cost is not None:
                    product["product_cost"] = cost
                products.append(product)
            doc_number = f"WB-NOFISCAL-{doc_date}"
            if len(group) > CHZ_PRODUCTS_PER_DOC:
                doc_number = f"{doc_number}-{part_idx}"
            doc_body = build_lk_receipt_document(
                inn=inn,
                document_number=doc_number,
                document_date=doc_date,
                primary_document_type=NO_FISCAL_PRIMARY_DOC_TYPE,
                primary_document_custom_name=NO_FISCAL_PRIMARY_DOC_NAME,
                products=products,
                kpp=kpp,
                fias_id=fias_id,
            )
            suffix = f" · часть {part_idx}" if len(group) > CHZ_PRODUCTS_PER_DOC else ""
            documents.append(
                {
                    "doc_type": "LK_RECEIPT",
                    "product_group": pg,
                    "title": (
                        f"Вывод · без чека (OTHER) · {doc_date}{suffix}"
                    ),
                    "event_keys": [e["event_key"] for e in part],
                    "product_document": doc_body,
                    "sign_payload_b64": _b64_json(doc_body),
                }
            )

    for part_idx, part in enumerate(
        _chunked(return_items, CHZ_PRODUCTS_PER_DOC), start=1
    ):
        if not part:
            continue
        products = [{"cis": e["excise_short"]} for e in part]
        doc_body = build_lp_return_document(
            inn=inn,
            return_type=str(settings.get("return_type") or "REMOTE_SALE_RETURN"),
            products=products,
        )
        suffix = f" · часть {part_idx}" if len(return_items) > CHZ_PRODUCTS_PER_DOC else ""
        documents.append(
            {
                "doc_type": "LP_RETURN",
                "product_group": pg,
                "title": f"Возврат в оборот · {len(part)} КИЗ{suffix}",
                "event_keys": [e["event_key"] for e in part],
                "product_document": doc_body,
                "sign_payload_b64": _b64_json(doc_body),
            }
        )

    doc_cap = max(1, int(CHZ_DOCUMENTS_PER_PREPARE))
    docs_built = len(documents)
    truncated_by_docs = docs_built > doc_cap
    if truncated_by_docs:
        documents = documents[:doc_cap]

    withdraw_n = sum(
        1
        for d in documents
        if d.get("doc_type") == "LK_RECEIPT"
        for _ in (d.get("event_keys") or [])
    )
    return_n = sum(
        1
        for d in documents
        if d.get("doc_type") == "LP_RETURN"
        for _ in (d.get("event_keys") or [])
    )
    hit_event_limit = len(events_raw) >= lim
    has_more = truncated_by_docs or hit_event_limit
    return {
        "ok": True,
        "settings": {
            "api_base": settings.get("api_base"),
            "api_base_url": settings.get("api_base_url"),
            "participant_inn": inn,
            "product_group": pg,
            "cert_thumbprint": settings.get("cert_thumbprint") or "",
            "kpp": kpp,
            "fias_id": fias_id,
        },
        "documents": documents,
        "warnings": warnings,
        "queue_repair": queue_repair,
        "skipped": [
            {
                "event_key": s.get("event_key"),
                "excise_short": s.get("excise_short"),
                "skip_reason": s.get("skip_reason"),
            }
            for s in skipped
        ],
        "counts": {
            "documents": len(documents),
            "documents_built": docs_built,
            "documents_cap": doc_cap,
            "withdraw_events": withdraw_n,
            "return_events": return_n,
            "skipped": len(skipped),
            "withdraw_not_sold": not_sold_n,
            "return_not_cancelled": not_cancelled_n,
            "eligible_loaded": len(events_raw),
            "eligible_after_dedupe": len(events),
        },
        "has_more": has_more,
    }


def _b64_json(obj: dict[str, Any]) -> str:
    import base64

    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def classify_chz_doc_status(chz_status: str) -> str:
    """Return accepted | error | submitted for a True API document status."""
    st = str(chz_status or "").strip().upper()
    if not st:
        return STATUS_SUBMITTED
    if st in CHZ_STATUS_SUCCESS:
        return STATUS_ACCEPTED
    if st in CHZ_STATUS_FAILED:
        return STATUS_ERROR
    return STATUS_SUBMITTED


def mark_events_submitted(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    event_keys: list[str],
    chz_doc_id: str,
    doc_type: str,
    run_id: int | None = None,
) -> None:
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    keys = [str(k) for k in event_keys if str(k).strip()]
    if not keys:
        return
    with repo._connect() as conn:
        for key in keys:
            conn.execute(
                repo._sql(
                    """
                    UPDATE wb_kiz_circulation_events
                    SET status = ?, chz_doc_id = ?, chz_status = 'submitted',
                        updated_at = ?, error_text = ''
                    WHERE user_id = ? AND source_id = ? AND event_key = ?
                    """
                ),
                (
                    STATUS_SUBMITTED,
                    str(chz_doc_id or ""),
                    now,
                    user_id,
                    source_id,
                    key,
                ),
            )
        conn.execute(
            repo._sql(
                """
                INSERT INTO wb_kiz_chz_documents (
                    user_id, source_id, run_id, doc_type, chz_doc_id, status,
                    event_keys_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'submitted', ?, ?, ?)
                """
            ),
            (
                user_id,
                source_id,
                run_id,
                str(doc_type or ""),
                str(chz_doc_id or ""),
                json.dumps(keys, ensure_ascii=False),
                now,
                now,
            ),
        )


def apply_chz_doc_status(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    event_keys: list[str],
    chz_doc_id: str,
    chz_status: str,
    error_text: str = "",
) -> str:
    """Update events from CHZ document_info. Returns final local status class."""
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    st = str(chz_status or "").strip()
    final = classify_chz_doc_status(st)
    keys = [str(k) for k in event_keys if str(k).strip()]
    err = str(error_text or "").strip()
    if final == STATUS_ERROR and not err:
        err = f"ЧЗ: {st}"
    with repo._connect() as conn:
        for key in keys:
            if final == STATUS_ERROR:
                conn.execute(
                    repo._sql(
                        """
                        UPDATE wb_kiz_circulation_events
                        SET status = ?, chz_doc_id = ?, chz_status = ?,
                            error_text = ?, updated_at = ?
                        WHERE user_id = ? AND source_id = ? AND event_key = ?
                        """
                    ),
                    (
                        STATUS_ERROR,
                        str(chz_doc_id or ""),
                        st,
                        err[:2000],
                        now,
                        user_id,
                        source_id,
                        key,
                    ),
                )
            elif final == STATUS_ACCEPTED:
                conn.execute(
                    repo._sql(
                        """
                        UPDATE wb_kiz_circulation_events
                        SET status = ?, chz_doc_id = ?, chz_status = ?,
                            raw_json = '{}', updated_at = ?
                        WHERE user_id = ? AND source_id = ? AND event_key = ?
                        """
                    ),
                    (
                        STATUS_ACCEPTED,
                        str(chz_doc_id or ""),
                        st or final,
                        now,
                        user_id,
                        source_id,
                        key,
                    ),
                )
            else:
                conn.execute(
                    repo._sql(
                        """
                        UPDATE wb_kiz_circulation_events
                        SET status = ?, chz_doc_id = ?, chz_status = ?, updated_at = ?
                        WHERE user_id = ? AND source_id = ? AND event_key = ?
                        """
                    ),
                    (
                        final,
                        str(chz_doc_id or ""),
                        st or final,
                        now,
                        user_id,
                        source_id,
                        key,
                    ),
                )
    if final == STATUS_ACCEPTED and keys:
        try:
            register_sent_cis_for_event_keys(
                repo,
                user_id=user_id,
                source_id=source_id,
                event_keys=keys,
                accepted_at=now,
            )
        except Exception as exc:
            logger.exception("register_sent_cis_for_event_keys failed: %s", exc)
    return final


def mark_events_accepted(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    event_keys: list[str],
    chz_doc_id: str,
    chz_status: str,
) -> None:
    """Backward-compatible wrapper — uses classify_chz_doc_status."""
    apply_chz_doc_status(
        repo,
        user_id=user_id,
        source_id=source_id,
        event_keys=event_keys,
        chz_doc_id=chz_doc_id,
        chz_status=chz_status,
    )


def mark_events_error(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    event_keys: list[str],
    error_text: str,
) -> None:
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    with repo._connect() as conn:
        for key in event_keys:
            conn.execute(
                repo._sql(
                    """
                    UPDATE wb_kiz_circulation_events
                    SET status = ?, error_text = ?, updated_at = ?
                    WHERE user_id = ? AND source_id = ? AND event_key = ?
                    """
                ),
                (
                    STATUS_ERROR,
                    str(error_text or "")[:2000],
                    now,
                    user_id,
                    source_id,
                    key,
                ),
            )


def chz_client_from_settings(settings: dict[str, Any]) -> ChzTrueApiClient:
    return ChzTrueApiClient(base_url=str(settings.get("api_base_url") or PROD_BASE))


# Re-export for web layer convenience
__all__ = [
    "ChzTrueApiClient",
    "ChzTrueApiError",
    "ensure_kiz_circulation_tables",
    "get_chz_settings",
    "get_wb_analytics_api_key",
    "upsert_chz_settings",
    "get_cursor",
    "get_overview",
    "get_run",
    "list_events",
    "list_events_for_chz",
    "resolve_excise_period",
    "sync_excise_report",
    "prepare_chz_batches",
    "mark_events_submitted",
    "mark_events_accepted",
    "apply_chz_doc_status",
    "classify_chz_doc_status",
    "mark_events_error",
    "repair_stuck_return_events",
    "repair_unhealable_withdraw_errors",
    "repair_nofiscal_withdraw_to_pending",
    "repair_orphan_submitted_events",
    "repair_legacy_skipped_with_cis",
    "repair_circulation_queue",
    "maintain_kiz_circulation_storage",
    "upsert_sent_cis_rows",
    "reconcile_submitted_with_chz",
    "chz_client_from_settings",
    "mask_secret",
    "encrypt_secret",
    "decrypt_secret",
]
