"""Cabinet identity for supply sources (WB cabinet id / Ozon Client-Id).

Data stays keyed by ``source_id``, but each source is bound to a stable
marketplace account so soft-delete + re-add can revive the same row
instead of creating a new id (and orphaning FBS data).

Channel (FBO/FBS) should be explicit. Name-based ``ФБС`` detection remains
only as a legacy fallback for older rows.
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

FULFILLMENT_FBO = "fbo"
FULFILLMENT_FBS = "fbs"
VALID_FULFILLMENTS = frozenset({FULFILLMENT_FBO, FULFILLMENT_FBS})


def normalize_client_id(client_id: object) -> str:
    """Trim cabinet / Client-Id. Keeps original characters (Ozon ids are not always digits)."""
    return str(client_id or "").strip()


def normalize_fulfillment(fulfillment: object) -> str | None:
    """Accept ``fbo``/``fbs`` (also russian synonyms)."""
    raw = str(fulfillment or "").strip().casefold()
    if not raw:
        return None
    if raw in ("fbo", "фбо", "fbw", "warehouse"):
        return FULFILLMENT_FBO
    if raw in ("fbs", "фбс", "dbw"):
        return FULFILLMENT_FBS
    return None


def normalize_channel(channel: object) -> str | None:
    key = str(channel or "").strip().lower()
    if key in VALID_CHANNELS:
        return key
    return None


def is_fbs_source_name(name: object) -> bool:
    text = str(name or "").casefold()
    return "фбс" in text or "fbs" in text


def resolve_supply_channel(
    *,
    marketplace: object,
    name: object = "",
    fulfillment: object = "",
    channel: object = "",
) -> str | None:
    """Resolve stable channel.

    Priority:
    1. explicit ``channel`` (wb_fbs / ozon_fbo / …)
    2. explicit ``fulfillment`` (fbo/fbs) + marketplace
    3. legacy: marketplace + FBS marker in name / ozon_fbs marketplace
    """
    explicit = normalize_channel(channel)
    if explicit:
        return explicit

    mp = str(marketplace or "").strip().lower() or "wb"
    mode = normalize_fulfillment(fulfillment)

    if mp == "ozon_fbs":
        return CHANNEL_OZON_FBS
    if mp in ("ozon", "ozon_fbo"):
        if mode == FULFILLMENT_FBS:
            return CHANNEL_OZON_FBS
        if mode == FULFILLMENT_FBO:
            return CHANNEL_OZON_FBO
        if is_fbs_source_name(name):
            return CHANNEL_OZON_FBS
        return CHANNEL_OZON_FBO
    if mp in ("wb", "wildberries"):
        if mode == FULFILLMENT_FBS:
            return CHANNEL_WB_FBS
        if mode == FULFILLMENT_FBO:
            return CHANNEL_WB_FBO
        if is_fbs_source_name(name):
            return CHANNEL_WB_FBS
        return CHANNEL_WB_FBO
    return None


def ensure_name_matches_fulfillment(*, name: str, channel: str | None) -> str:
    """Keep legacy name markers in sync with explicit channel (backward compatible).

    - FBS channel: append `` ФБС`` when name has no FBS marker (old code paths still
      scan names).
    - FBO channel: reject names that contain FBS marker to avoid dual signals.
    """
    clean = str(name or "").strip()
    ch = normalize_channel(channel) or ""
    if ch.endswith("_fbs"):
        if not is_fbs_source_name(clean):
            return f"{clean} ФБС".strip() if clean else "ФБС"
        return clean
    if ch.endswith("_fbo") and is_fbs_source_name(clean):
        raise ValueError(
            "Для типа FBO уберите «ФБС»/FBS из названия "
            "(или выберите тип FBS)."
        )
    return clean


def resolve_external_account_id(
    *,
    marketplace: object,
    api_key: object,
    client_id: object = "",
) -> str | None:
    """Stable cabinet id for binding.

    - Ozon: Client-Id (required for API and binding).
    - WB: manual cabinet id stored in ``client_id`` (preferred);
      JWT ``uid`` is only a fallback for legacy rows / auto-fill.
    """
    mp = str(marketplace or "").strip().lower() or "wb"
    explicit = normalize_client_id(client_id)
    if mp in ("ozon", "ozon_fbo", "ozon_fbs"):
        return explicit or None
    if mp in ("wb", "wildberries"):
        if explicit:
            return explicit
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


def fulfillment_of_channel(channel: object) -> str | None:
    ch = normalize_channel(channel) or str(channel or "").strip().lower()
    if ch.endswith("_fbs"):
        return FULFILLMENT_FBS
    if ch.endswith("_fbo"):
        return FULFILLMENT_FBO
    return None


def source_is_fbs(source: Mapping[str, Any] | None) -> bool:
    """Prefer stored ``channel``; fall back to marketplace/name heuristics."""
    if not source:
        return False
    ch = str(source.get("channel") or "").strip().lower()
    if ch in (CHANNEL_WB_FBS, CHANNEL_OZON_FBS) or ch.endswith("_fbs"):
        return True
    if ch in (CHANNEL_WB_FBO, CHANNEL_OZON_FBO) or ch.endswith("_fbo"):
        return False
    mp = str(source.get("marketplace") or "").strip().lower()
    if mp == "ozon_fbs":
        return True
    return is_fbs_source_name(source.get("name"))


def source_is_fbo(source: Mapping[str, Any] | None) -> bool:
    if not source:
        return False
    ch = str(source.get("channel") or "").strip().lower()
    if ch in (CHANNEL_WB_FBO, CHANNEL_OZON_FBO) or ch.endswith("_fbo"):
        return True
    if ch in (CHANNEL_WB_FBS, CHANNEL_OZON_FBS) or ch.endswith("_fbs"):
        return False
    mp = str(source.get("marketplace") or "").strip().lower()
    if mp == "ozon_fbs":
        return False
    if mp in ("ozon", "ozon_fbo", "wb", "wildberries"):
        return not is_fbs_source_name(source.get("name"))
    return False


def sibling_channel(channel: object) -> str | None:
    """Opposite FBO/FBS channel for the same marketplace family."""
    ch = normalize_channel(channel)
    if ch == CHANNEL_WB_FBO:
        return CHANNEL_WB_FBS
    if ch == CHANNEL_WB_FBS:
        return CHANNEL_WB_FBO
    if ch == CHANNEL_OZON_FBO:
        return CHANNEL_OZON_FBS
    if ch == CHANNEL_OZON_FBS:
        return CHANNEL_OZON_FBO
    return None


def public_identity_fields(source: Mapping[str, Any] | None) -> dict[str, Any]:
    """Safe fields for API/UI (no secrets)."""
    if not source:
        return {
            "channel": None,
            "external_account_id": None,
            "cabinet_label": "",
            "fulfillment": None,
        }
    channel = str(source.get("channel") or "").strip() or None
    ext = str(source.get("external_account_id") or "").strip() or None
    if not channel:
        channel = resolve_supply_channel(
            marketplace=source.get("marketplace"),
            name=source.get("name"),
        )
    if not ext:
        ext = normalize_client_id(source.get("client_id")) or None
    label = ""
    if ext:
        if channel and channel.startswith("wb"):
            label = f"ID кабинета {ext}"
        elif channel and channel.startswith("ozon"):
            label = f"Client-Id {ext}"
        else:
            mp = str(source.get("marketplace") or "").strip().lower()
            if mp.startswith("ozon"):
                label = f"Client-Id {ext}"
            elif mp in ("wb", "wildberries"):
                label = f"ID кабинета {ext}"
            else:
                label = ext
    return {
        "channel": channel,
        "external_account_id": ext,
        "cabinet_label": label,
        "fulfillment": fulfillment_of_channel(channel),
    }
