"""Lightweight structured FBS operator audit (journal only).

Use for the full operator chain (sync → print → scan → GM/KIZ → save → marketplace).
Never raises and never touches the DB — safe on the scan hot path.

Owner UI journals (`ozon_fbs_ops_log` / `wb_fbs_ops_log`) stay for coarse milestones;
this logger is the greppable source of truth for “what did the operator do?”.
"""
from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger("review_processor.fbs_audit")

_SAFE_KEY = re.compile(r"^[A-Za-z0-9_]{1,40}$")


def mask_code(value: object, *, keep_tail: int = 4) -> str:
    """Mask marking / barcode payloads for logs (keep length + short tail)."""
    s = str(value or "").strip()
    if not s:
        return ""
    if len(s) <= keep_tail + 2:
        return f"*(len={len(s)})"
    return f"…{s[-keep_tail:]}(len={len(s)})"


def codes_summary(codes: list[Any] | tuple[Any, ...] | None) -> str:
    items = [str(c).strip() for c in (codes or []) if str(c or "").strip()]
    if not items:
        return "n=0"
    if len(items) == 1:
        return f"n=1:{mask_code(items[0])}"
    return f"n={len(items)}:[{mask_code(items[0])}…{mask_code(items[-1])}]"


def _kv(key: str, value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raw = "1" if value else "0"
    elif isinstance(value, (int, float)):
        raw = str(value)
    else:
        raw = str(value).strip()
        if not raw:
            return None
        # Keep journal lines single-token friendly.
        raw = raw.replace("\n", " ").replace("\r", " ").replace(" ", "_")
        if len(raw) > 160:
            raw = raw[:157] + "…"
    return f"{key}={raw}"


def audit(
    *,
    marketplace: str,
    action: str,
    result: str = "ok",
    user_id: int | None = None,
    actor_user_id: int | None = None,
    actor_name: str = "",
    source_id: int | None = None,
    supply_id: str = "",
    posting_number: str = "",
    order_id: str | int = "",
    error: str = "",
    **fields: Any,
) -> None:
    """Emit one structured audit line. Never raises."""
    try:
        parts: list[str] = [
            f"mp={str(marketplace or '-').strip().lower()[:16] or '-'}",
            f"action={str(action or '-').strip()[:64] or '-'}",
            f"result={str(result or 'ok').strip().lower()[:24] or 'ok'}",
        ]
        for key, value in (
            ("user_id", user_id),
            ("actor_id", actor_user_id),
            ("actor", actor_name),
            ("source_id", source_id),
            ("supply_id", supply_id),
            ("posting", posting_number),
            ("order_id", order_id),
        ):
            piece = _kv(key, value)
            if piece:
                parts.append(piece)
        for key, value in fields.items():
            k = str(key or "").strip()
            if not _SAFE_KEY.match(k):
                continue
            piece = _kv(k, value)
            if piece:
                parts.append(piece)
        err = str(error or "").strip()
        if err:
            parts.append(_kv("error", err.replace(" ", "_")[:200]) or f"error={err[:200]}")

        msg = " ".join(parts)
        res = str(result or "ok").strip().lower()
        if res in {"fail", "error", "failed"}:
            _log.error("%s", msg)
        elif res in {"warn", "warning", "partial"}:
            _log.warning("%s", msg)
        else:
            _log.info("%s", msg)
    except Exception:
        # Audit must never affect operators.
        return
