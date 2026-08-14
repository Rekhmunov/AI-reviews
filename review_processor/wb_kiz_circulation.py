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
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (user_id, source_id)
            )
            """
        )
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
    """Move withdraw-without-fiscal from error → skipped (do not block CHZ queue)."""
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
                    SET status = ?, skip_reason = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """
                ),
                (STATUS_SKIPPED, SKIP_NO_FISCAL, now, int(d["id"]), user_id),
            )
            fixed += 1
    return fixed


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
        withdraw_skipped = repair_unhealable_withdraw_errors(
            repo, user_id=user_id, source_id=source_id
        )
    except Exception as exc:
        logger.exception("repair_unhealable_withdraw_errors failed: %s", exc)
        withdraw_skipped = 0
    return {"returns_fixed": returns_fixed, "withdraw_skipped": withdraw_skipped}


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
    """Withdraw needs fiscal for LK_RECEIPT; returns may omit fiscal (WB: «если есть»).

    Missing-fiscal withdraw is ``skipped`` (not ``error``) so it cannot poison
    the CHZ prepare queue ahead of processable events.
    """
    op = int(norm.get("operation_type") or 0)
    has_fiscal = bool(norm.get("fiscal_doc_number") and norm.get("fiscal_dt"))
    if op == OP_WITHDRAW and not has_fiscal:
        return STATUS_SKIPPED, SKIP_NO_FISCAL
    return STATUS_PENDING, ""


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
            f"выводы без чека → skipped (не блокируют очередь): {repaired['withdraw_skipped']}",
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
    withdraw_n = 0
    return_n = 0
    insert_errors = 0
    last_key = ""
    last_fiscal = ""

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
                                WHEN EXCLUDED.status = 'pending' THEN ''
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
    _attach_order_ids_to_events(repo, user_id=user_id, source_id=source_id, events=out)
    return out


def _attach_order_ids_to_events(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    events: list[dict[str, Any]],
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


def list_events_for_chz(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    limit: int = PREPARE_EVENT_LIMIT,
) -> list[dict[str, Any]]:
    """Events eligible for CHZ submit: pending + recoverable error + failed submitted.

    Excludes ``skipped`` and unhealable withdraw-without-fiscal errors so they
    cannot starve the oldest-first queue.
    """
    ensure_kiz_circulation_tables(repo)
    lim = max(1, min(int(limit or PREPARE_EVENT_LIMIT), 5000))
    fail_list = sorted(CHZ_STATUS_FAILED)
    fail_placeholders = ", ".join(["?"] * len(fail_list)) if fail_list else "NULL"
    params: list[Any] = [user_id, source_id, SKIP_NO_FISCAL, *fail_list, lim]
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
                      status = 'submitted'
                      AND UPPER(COALESCE(chz_status, '')) IN ({fail_placeholders})
                    )
                  )
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


def reconcile_submitted_with_chz(
    repo: ReviewRepository,
    client: ChzTrueApiClient,
    *,
    user_id: int,
    source_id: int,
    limit: int = 100,
) -> dict[str, int]:
    """Poll CHZ for in-flight submitted docs and update local statuses."""
    ensure_kiz_circulation_tables(repo)
    lim = max(1, min(int(limit or 100), 500))
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


def _price_for_chz(ev: dict[str, Any]) -> float | None:
    """Only RUB (or unknown/empty currency) goes into product_cost."""
    if ev.get("price") is None:
        return None
    cur = str(ev.get("currency_name") or "").strip().upper()
    if cur and cur not in {"RUB", "RUR", "₽", "РУБ"}:
        return None
    try:
        return float(ev["price"])
    except (TypeError, ValueError):
        return None


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    n = max(1, int(size))
    return [items[i : i + n] for i in range(0, len(items), n)]


def prepare_chz_batches(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    limit: int = PREPARE_EVENT_LIMIT,
) -> dict[str, Any]:
    """Build unsigned CHZ document payloads grouped by operation + receipt."""
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
    lim = max(1, min(int(limit or PREPARE_EVENT_LIMIT), 5000))
    events = list_events_for_chz(
        repo, user_id=user_id, source_id=source_id, limit=lim
    )

    withdraw_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    return_items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for ev in events:
        op = int(ev.get("operation_type") or 0)
        fiscal_no = str(ev.get("fiscal_doc_number") or "").strip()
        fiscal_dt = str(ev.get("fiscal_dt") or "").strip()
        cis = str(ev.get("excise_short") or "").strip()
        if not cis:
            skipped.append({**ev, "skip_reason": "пустой КИЗ"})
            continue
        if op == OP_WITHDRAW:
            if not fiscal_no or not fiscal_dt:
                skipped.append({**ev, "skip_reason": "нет чека"})
                continue
            withdraw_groups.setdefault((fiscal_no, fiscal_dt), []).append(ev)
        elif op == OP_RETURN:
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
    # Soft-skip withdraw if DISTANCE place incomplete — still process returns.
    if withdraw_groups and (not kpp or not fias_id):
        warnings.append(
            "Вывод DISTANCE пропущен: укажите КПП и ФИАС у юр. лица с этим ИНН "
            "(Поставки → Настройки → Юр. лица)"
        )
        for group in withdraw_groups.values():
            for ev in group:
                skipped.append({**ev, "skip_reason": "нет КПП/ФИАС у юр. лица"})
        withdraw_groups = {}

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

    withdraw_n = sum(len(g) for g in withdraw_groups.values())
    return {
        "ok": True,
        "settings": {
            "api_base": settings.get("api_base"),
            "api_base_url": settings.get("api_base_url"),
            "participant_inn": inn,
            "product_group": pg,
            "cert_thumbprint": settings.get("cert_thumbprint") or "",
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
            "withdraw_events": withdraw_n,
            "return_events": len(return_items),
            "skipped": len(skipped),
            "eligible_loaded": len(events),
        },
        "has_more": len(events) >= lim,
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
) -> str:
    """Update events from CHZ document_info. Returns final local status class."""
    ensure_kiz_circulation_tables(repo)
    now = datetime.now(timezone.utc).isoformat()
    st = str(chz_status or "").strip()
    final = classify_chz_doc_status(st)
    keys = [str(k) for k in event_keys if str(k).strip()]
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
                        f"ЧЗ: {st}"[:2000],
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
    "repair_circulation_queue",
    "reconcile_submitted_with_chz",
    "chz_client_from_settings",
    "mask_secret",
    "encrypt_secret",
    "decrypt_secret",
]
