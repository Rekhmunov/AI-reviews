"""Cabinet identity for supply sources (WB JWT uid / Ozon Client-Id).

Data stays keyed by ``source_id``, but each source is bound to a stable
marketplace account so soft-delete + re-add can revive the same row
instead of creating a new id (and orphaning FBS data).
"""

from __future__ import annotations

from typing import Any, Mapping

CHANNEL_WB_FBO = "wb_fbo"
CHANNEL_WB_FBS = "wb_fbs"
CHANNEL_OZON_FBO = "ozon_fbo"
CHANNEL_OZON_FBS = "ozon_fbs"

VALID_CHANNELS = frozenset(
    {CHANNEL_WB_FBO, CHANNEL_WB_FBS, CHANNEL_OZON_FBO, CHANNEL_OZON_FBS}
)


def normalize_client_id(client_id: object) -> str:
    return str(client_id or "").strip()


def _is_fbs_source_name(name: object) -> bool:
    text = str(name or "").casefold()
    return "фбс" in text or "fbs" in text


def resolve_supply_channel(*, marketplace: object, name: object) -> str | None:
    """Derive stable channel from marketplace + FBS naming convention."""
    mp = str(marketplace or "").strip().lower() or "wb"
    if mp == "ozon_fbs":
        return CHANNEL_OZON_FBS
    if mp in ("ozon", "ozon_fbo"):
        if _is_fbs_source_name(name):
            return CHANNEL_OZON_FBS
        return CHANNEL_OZON_FBO
    if mp in ("wb", "wildberries"):
        if _is_fbs_source_name(name):
            return CHANNEL_WB_FBS
        return CHANNEL_WB_FBO
    return None


def resolve_external_account_id(
    *,
    marketplace: object,
    api_key: object,
    client_id: object = "",
) -> str | None:
    """WB: JWT ``uid``; Ozon: Client-Id. Returns None when unavailable."""
    mp = str(marketplace or "").strip().lower() or "wb"
    if mp in ("ozon", "ozon_fbo", "ozon_fbs"):
        cid = normalize_client_id(client_id)
        return cid or None
    if mp in ("wb", "wildberries"):
        # Lazy import avoids circular dependency with repository ↔ wb_fbs.
        from .wb_fbs import wb_jwt_uid

        uid = wb_jwt_uid(str(api_key or ""))
        return str(uid) if uid else None
    return None


def channel_label(channel: object) -> str:
    mapping = {
        CHANNEL_WB_FBO: "ВБ FBO",
        CHANNEL_WB_FBS: "ВБ FBS",
        CHANNEL_OZON_FBO: "ОЗОН FBO",
        CHANNEL_OZON_FBS: "ОЗОН FBS",
    }
    key = str(channel or "").strip().lower()
    return mapping.get(key, key or "—")


def public_identity_fields(source: Mapping[str, Any] | None) -> dict[str, Any]:
    """Safe fields for API/UI (no secrets)."""
    if not source:
        return {
            "channel": None,
            "external_account_id": None,
            "cabinet_label": "",
        }
    channel = str(source.get("channel") or "").strip() or None
    ext = str(source.get("external_account_id") or "").strip() or None
    if not channel:
        channel = resolve_supply_channel(
            marketplace=source.get("marketplace"),
            name=source.get("name"),
        )
    if not ext:
        mp = str(source.get("marketplace") or "").strip().lower()
        if mp.startswith("ozon"):
            ext = normalize_client_id(source.get("client_id")) or None
    label = ""
    if ext:
        if channel and channel.startswith("wb"):
            label = f"uid {ext}"
        elif channel and channel.startswith("ozon"):
            label = f"Client-Id {ext}"
        else:
            label = ext
    return {
        "channel": channel,
        "external_account_id": ext,
        "cabinet_label": label,
    }
