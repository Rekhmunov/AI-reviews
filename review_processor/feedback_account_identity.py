"""Stable cabinet identity for feedback marketplace accounts.

Reviews/questions stay keyed by internal ``account_id``. Each account also
stores ``external_account_id`` (Ozon Client-Id / WB cabinet id / YM Business ID)
so soft-delete + re-add can revive the same row instead of orphaning history.
"""

from __future__ import annotations

from typing import Any, Mapping


def normalize_cabinet_id(value: object) -> str:
    return str(value or "").strip()


def resolve_external_account_id(
    *,
    marketplace: object,
    client_id: object = "",
    business_id: object = "",
    extra: Mapping[str, Any] | None = None,
) -> str | None:
    """Return stable cabinet id for binding, or None when missing."""
    mp = str(marketplace or "").strip().lower()
    extra = extra or {}
    if mp == "ozon":
        value = normalize_cabinet_id(client_id) or normalize_cabinet_id(
            extra.get("client_id")
        )
        return value or None
    if mp in ("wb", "wildberries"):
        value = normalize_cabinet_id(client_id) or normalize_cabinet_id(
            extra.get("client_id")
        )
        return value or None
    if mp == "yandex":
        value = normalize_cabinet_id(business_id) or normalize_cabinet_id(
            extra.get("business_id")
        )
        return value or None
    return None


def marketplace_requires_cabinet_id(marketplace: object) -> bool:
    mp = str(marketplace or "").strip().lower()
    return mp in {"wb", "wildberries", "ozon", "yandex"}


def cabinet_id_label(marketplace: object) -> str:
    mp = str(marketplace or "").strip().lower()
    if mp == "ozon":
        return "Client-Id"
    if mp == "yandex":
        return "Business ID"
    if mp in ("wb", "wildberries"):
        return "ID кабинета WB"
    return "ID кабинета"
