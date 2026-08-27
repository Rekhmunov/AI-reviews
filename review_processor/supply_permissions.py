from __future__ import annotations

from typing import Any

from . import ozon_fbs as ozon_fbs_mod
from . import wb_fbs as wb_fbs_mod
from .repository import ReviewRepository


def default_supply_source_permissions() -> dict[str, bool]:
    return {
        "wb": False,
        "wb_fbs": False,
        "wb_fbs_tsd": False,
        "ozon": False,
        "ozon_fbs": False,
    }


def supply_sources_has_any_permission(
    *,
    can_supplies: bool = False,
    can_supply_settings: bool = False,
    can_supply_poa: bool = False,
    can_supply_certs: bool = False,
    can_supply_planning: bool = False,
    can_supply_stock: bool = False,
    sources: dict[str, Any] | None = None,
) -> bool:
    if (
        can_supplies
        or can_supply_settings
        or can_supply_poa
        or can_supply_certs
        or can_supply_planning
        or can_supply_stock
    ):
        return True
    for value in (sources or {}).values():
        if not isinstance(value, dict):
            continue
        if (
            value.get("wb")
            or value.get("wb_fbs")
            or value.get("wb_fbs_tsd")
            or value.get("ozon")
            or value.get("ozon_fbs")
        ):
            return True
    return False


def heal_orphaned_fbs_supply_permissions(
    repository: ReviewRepository,
    *,
    owner_id: int,
    sources: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, dict[str, bool]]:
    """Carry FBS grants onto current sources when permissions still reference deleted source ids."""
    existing_sources = {
        str(k): dict(v)
        for k, v in (existing or {}).items()
        if isinstance(v, dict)
    }
    healed: dict[str, dict[str, bool]] = {
        str(k): {**default_supply_source_permissions(), **dict(v)}
        for k, v in (sources or {}).items()
        if isinstance(v, dict)
    }
    current_sources = repository.list_supply_sources(user_id=owner_id)
    current_ids = {str(s["id"]) for s in current_sources}

    def _orphan_had(flag: str) -> bool:
        return any(
            bool(v.get(flag))
            for sid, v in existing_sources.items()
            if str(sid) not in current_ids
        )

    def _current_has(flag: str) -> bool:
        return any(
            bool(v.get(flag))
            for sid, v in healed.items()
            if str(sid) in current_ids
        )

    def _apply_flag(flag: str, matcher) -> None:
        if not _orphan_had(flag) or _current_has(flag):
            return
        for src in current_sources:
            if not matcher(src):
                continue
            sid = str(src["id"])
            entry = healed.setdefault(sid, default_supply_source_permissions())
            entry[flag] = True

    _apply_flag("ozon_fbs", ozon_fbs_mod.is_ozon_fbs_source)
    _apply_flag(
        "wb_fbs",
        lambda s: (
            str(s.get("marketplace") or "wb").lower() == "wb"
            and wb_fbs_mod.is_fbs_source_name(s.get("name"))
        ),
    )
    return healed
