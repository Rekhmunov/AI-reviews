"""TTN display titles for logistics catalog and FBS form flows."""

from __future__ import annotations


def format_manual_ttn_title(*, n: int, ttn_date: str) -> str:
    """``ТН 1 от 17.09.2026`` — daily counter comes from ``doc_number``."""
    num = max(1, int(n or 1))
    date = str(ttn_date or "").strip() or "—"
    return f"ТН {num} от {date}"


def format_fbs_ttn_title_base(*, supply_name: str) -> str:
    """``ТН {supply_name}`` — supply already looks like ``Поставка … от ДД.ММ.ГГГГ``."""
    name = str(supply_name or "").strip() or "Поставка"
    if name.upper().startswith("ТН "):
        return name
    return f"ТН {name}"


def unique_ttn_title(base: str, existing: set[str], *, exclude: str = "") -> str:
    """Ensure uniqueness: base, then ``base (2)``, ``base (3)``, …"""
    name = str(base or "").strip() or "ТН"
    skip = {str(exclude or "").strip()} if exclude else set()
    taken = {str(x or "").strip() for x in (existing or set()) if str(x or "").strip()}
    taken -= skip
    if name not in taken:
        return name
    for i in range(2, 200):
        candidate = f"{name} ({i})"
        if candidate not in taken:
            return candidate
    return f"{name} · {name.__hash__() & 0xFFFF}"


def list_existing_ttn_titles(repo, *, user_id: int) -> set[str]:
    rows = repo.list_supply_ttn_records(user_id=user_id) or []
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if title:
            out.add(title)
    return out


def resolve_ttn_title_for_create(
    repo,
    *,
    user_id: int,
    title: str,
    doc_number: str,
    ttn_date: str,
    supply_name: str = "",
    fbs_platform: str = "",
) -> str:
    """Pick title for a new TTN row when the client left it blank or sent a base."""
    raw = str(title or "").strip()
    existing = list_existing_ttn_titles(repo, user_id=user_id)
    if raw:
        return unique_ttn_title(raw, existing)
    plat = str(fbs_platform or "").strip().lower()
    sname = str(supply_name or "").strip()
    if plat and sname:
        base = format_fbs_ttn_title_base(supply_name=sname)
        return unique_ttn_title(base, existing)
    try:
        n = int(str(doc_number or "").strip() or "1")
    except ValueError:
        n = 1
    return format_manual_ttn_title(n=n, ttn_date=ttn_date)


def suggest_fbs_ttn_title(repo, *, user_id: int, supply_name: str, keep_title: str = "") -> str:
    """Prefill title for FBS form; keep existing title when editing."""
    keep = str(keep_title or "").strip()
    if keep:
        return keep
    base = format_fbs_ttn_title_base(supply_name=supply_name)
    existing = list_existing_ttn_titles(repo, user_id=user_id)
    return unique_ttn_title(base, existing)
