"""Ozon FBS «Отгрузки» (carriage / act) — Seller API wrappers for the supply modal.

Key Seller API methods (docs.ozon.ru):
- ``POST /v2/delivery-method/list`` (fallback ``/v1/…``) — методы доставки склада
- ``POST /v2/carriage/delivery/list`` (fallback ``/v1/…``) — карточка отгрузки на дату + метод
- ``POST /v2/posting/fbs/act/create`` — кнопка «Сформировать»
- ``POST /v2/posting/fbs/act/check-status`` — статус формирования документов
- ``POST /v2/posting/fbs/act/get-barcode`` — изображение ШК поставки
- ``POST /v2/posting/fbs/act/get-barcode/text`` — текст ШК поставки
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import UTC, date, datetime
from typing import Any

from . import ozon_fbs as oz
from . import ozon_fbs_supplies as oz_sup
from .repository import ReviewRepository

_log = logging.getLogger(__name__)

_OZON_ROLE_HINT = (
    "Проверьте API-ключ Ozon: в личном кабинете Seller → Настройки → "
    "Seller API → ключ должен иметь права на FBS-отгрузки (Posting / Delivery). "
    "При необходимости создайте новый ключ с полными правами Admin."
)


def _friendly_ozon_api_error(exc: Exception) -> RuntimeError:
    text = str(exc or "")
    low = text.casefold()
    if "403" in low or "required role" in low:
        return RuntimeError(f"{_OZON_ROLE_HINT} ({text})")
    return RuntimeError(text)


def _delivery_method_rows(data: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Normalize v2 delivery-method/list payloads."""
    top = data.get("delivery_methods")
    if isinstance(top, list):
        rows = [x for x in top if isinstance(x, dict)]
        return rows, bool(data.get("has_next"))
    result = data.get("result")
    if isinstance(result, list):
        rows = [x for x in result if isinstance(x, dict)]
        return rows, bool(data.get("has_next"))
    if isinstance(result, dict):
        nested = (
            result.get("delivery_methods")
            or result.get("methods")
            or result.get("items")
            or []
        )
        if isinstance(nested, list):
            rows = [x for x in nested if isinstance(x, dict)]
            has_next = bool(result.get("has_next") or data.get("has_next"))
            return rows, has_next
    return [], False


def _parse_delivery_method_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        mid = int(raw.get("id") or raw.get("delivery_method_id") or 0)
    except (TypeError, ValueError):
        return None
    if mid <= 0:
        return None
    name = str(
        raw.get("name")
        or raw.get("delivery_method_name")
        or raw.get("method_name")
        or ""
    ).strip()
    status = str(raw.get("status") or "").strip().upper()
    if status == "DISABLED":
        return None
    return {
        "id": mid,
        "name": name or f"Метод {mid}",
        "warehouse_id": raw.get("warehouse_id"),
        "status": status,
        "cutoff": str(raw.get("cutoff") or ""),
    }


def _merge_delivery_methods(
    methods: list[dict[str, Any]], extra: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if not extra:
        return methods
    try:
        mid = int(extra.get("id") or 0)
    except (TypeError, ValueError):
        return methods
    if mid <= 0:
        return methods
    for m in methods:
        try:
            if int(m.get("id") or 0) == mid:
                if not str(m.get("name") or "").strip() and extra.get("name"):
                    m["name"] = str(extra.get("name") or "")
                return methods
        except (TypeError, ValueError):
            continue
    methods.append(
        {
            "id": mid,
            "name": str(extra.get("name") or f"Метод {mid}"),
            "warehouse_id": extra.get("warehouse_id"),
            "status": str(extra.get("status") or ""),
            "cutoff": str(extra.get("cutoff") or ""),
        }
    )
    methods.sort(
        key=lambda m: (-_method_score(str(m.get("name") or "")), str(m.get("name") or ""))
    )
    return methods


def _carriage_delivery_blocks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize v2 carriage/delivery/list payloads into v1-like blocks."""
    top = data.get("methods")
    if isinstance(top, list):
        return [b for b in top if isinstance(b, dict)]
    result = data.get("result")
    if isinstance(result, list):
        return [b for b in result if isinstance(b, dict)]
    if isinstance(result, dict):
        blocks: list[dict[str, Any]] = []
        nested = result.get("delivery_methods")
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    blocks.append(item)
        if blocks:
            return blocks
        if isinstance(result.get("carriages"), list):
            return [result]
    return []


def _block_departure_date(block: dict[str, Any]) -> date | None:
    dep = str(block.get("departure_date") or "").strip()
    if not dep:
        return None
    try:
        if "T" in dep:
            return datetime.fromisoformat(dep.replace("Z", "+00:00")).date()
        return date.fromisoformat(dep[:10])
    except ValueError:
        return None


def _block_matches_departure(block: dict[str, Any], departure: date) -> bool:
    block_day = _block_departure_date(block)
    if block_day is None:
        return True
    return block_day == departure


def _carriage_departure_date(day: date) -> str:
    """Date-only filter for ``POST /v2/carriage/delivery/list``."""
    return day.isoformat()


PREFERRED_METHOD_HINTS = (
    "доставка ozon самостоятельно",
    "доставка на ozon самостоятельно",
    "доставка на озон самостоятельно",
    "на ozon самостоятельно",
    "самостоятельно",
)

# Carriage statuses that mean «Сформирована» in Seller UI terms.
_FORMED_STATUSES = frozenset(
    {
        "formed",
        "confirmed",
        "ready",
        "sended",
        "sent",
        "shipped",
        "closed",
        "received",
        "completed",
        "сформирована",
        "formed_partially",
    }
)


def _departure_iso(day: date) -> str:
    """Midnight UTC for the selected calendar day (Ozon date-time filter)."""
    dt = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_departure_date(raw: object) -> date:
    text = str(raw or "").strip()
    if not text:
        return datetime.now(UTC).date()
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise RuntimeError("Некорректная дата отгрузки") from exc


def _method_score(name: str) -> int:
    n = str(name or "").strip().casefold()
    if not n:
        return 0
    for i, hint in enumerate(PREFERRED_METHOD_HINTS):
        if hint in n:
            return 100 - i
    return 1


def list_delivery_methods(
    client: oz.OzonFbsClient, *, warehouse_id: int | None
) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    seen: set[int] = set()
    offset = 0
    for _ in range(20):
        try:
            data = client.delivery_method_list(
                warehouse_id=warehouse_id, status="ACTIVE", limit=50, offset=offset
            )
        except RuntimeError as exc:
            raise _friendly_ozon_api_error(exc) from exc
        batch, has_next = _delivery_method_rows(data)
        for raw in batch:
            parsed = _parse_delivery_method_row(raw)
            if not parsed:
                continue
            mid = int(parsed["id"])
            if mid in seen:
                continue
            seen.add(mid)
            methods.append(parsed)
        if not has_next or not batch:
            break
        offset += len(batch)
    methods.sort(
        key=lambda m: (-_method_score(str(m.get("name") or "")), str(m.get("name") or ""))
    )
    return methods


def list_delivery_methods_for_warehouse(
    client: oz.OzonFbsClient, *, warehouse_id: int | None
) -> list[dict[str, Any]]:
    """Merge methods for warehouse-specific and global lists."""
    methods = list_delivery_methods(client, warehouse_id=warehouse_id)
    if warehouse_id is not None:
        global_methods = list_delivery_methods(client, warehouse_id=None)
        for m in global_methods:
            methods = _merge_delivery_methods(methods, m)
    return methods


def pick_default_delivery_method(
    methods: list[dict[str, Any]], preferred_id: int | None = None
) -> dict[str, Any] | None:
    if preferred_id is not None:
        for m in methods:
            try:
                if int(m.get("id")) == int(preferred_id):
                    return m
            except (TypeError, ValueError):
                continue
    if not methods:
        return None
    ranked = sorted(
        methods,
        key=lambda m: (
            -_method_score(str(m.get("name") or "")),
            str(m.get("name") or ""),
        ),
    )
    return ranked[0]


def _carriage_status_label(status: object) -> str:
    st = str(status or "").strip()
    if not st:
        return "Не сформирована"
    low = st.casefold()
    if low in _FORMED_STATUSES or "форм" in low:
        if "не" in low and "форм" in low:
            return "Не сформирована"
        return "Сформирована"
    if low in {"new", "created", "pending", "assembly", "forming"}:
        return "Не сформирована"
    return st


def _is_formed(status: object) -> bool:
    return _carriage_status_label(status) == "Сформирована"


def _dropoff_type_label(raw: object) -> str:
    t = str(raw or "").strip()
    low = t.casefold()
    mapping = {
        "pvz": "В пункт приема",
        "sc": "В пункт приема",
        "sorting_center": "В пункт приема",
        "dropoff": "В пункт приема",
        "pickup": "Самовывоз Ozon",
        "courier": "Курьер",
    }
    if low in mapping:
        return mapping[low]
    if t:
        return t
    return "В пункт приема"


def _acceptance_label(block: dict[str, Any]) -> str:
    local = str(block.get("recommended_time_local") or "").strip()
    city = str(block.get("warehouse_city") or "").strip()
    if local and city:
        return f"до {local} ({city})"
    if local:
        return f"до {local}"
    cutoff = str(block.get("cutoff_at") or "").strip()
    if cutoff:
        try:
            dt = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            return f"до {dt.strftime('%H:%M')}"
        except ValueError:
            return cutoff
    return "—"


def _collected_label(block: dict[str, Any]) -> str:
    packaged = block.get("mandatory_packaged_count")
    total = block.get("mandatory_postings_count")
    try:
        p = int(packaged) if packaged is not None else None
        t = int(total) if total is not None else None
    except (TypeError, ValueError):
        p, t = None, None
    if p is not None and t is not None:
        return f"{p} из {t}"
    if t is not None:
        return f"0 из {t}"
    try:
        return str(int(block.get("carriage_postings_count") or 0))
    except (TypeError, ValueError):
        return "—"


def fetch_carriage_barcode(
    client: oz.OzonFbsClient, *, carriage_id: int
) -> dict[str, Any]:
    text = ""
    image_b64 = ""
    content_type = "image/png"
    try:
        text_resp = client.fbs_act_get_barcode_text(carriage_id=carriage_id)
        text = str(text_resp.get("result") or text_resp.get("barcode_text") or "").strip()
    except Exception as exc:
        _log.warning("ozon fbs barcode text failed id=%s: %s", carriage_id, exc)
    try:
        img_resp = client.fbs_act_get_barcode(carriage_id=carriage_id)
        raw = (
            img_resp.get("file_content")
            or img_resp.get("barcode")
            or img_resp.get("content")
            or ""
        )
        content_type = str(img_resp.get("content_type") or "image/png").strip() or "image/png"
        if isinstance(raw, (bytes, bytearray)):
            image_b64 = base64.b64encode(bytes(raw)).decode("ascii")
        else:
            text_raw = str(raw or "").strip()
            if text_raw:
                # Already base64 or binary-as-latin1 from JSON string
                try:
                    base64.b64decode(text_raw, validate=True)
                    image_b64 = text_raw
                except Exception:
                    image_b64 = base64.b64encode(text_raw.encode("latin-1")).decode("ascii")
    except Exception as exc:
        _log.warning("ozon fbs barcode image failed id=%s: %s", carriage_id, exc)
    return {
        "carriage_id": int(carriage_id),
        "barcode_text": text,
        "barcode_image_base64": image_b64,
        "content_type": content_type,
    }


def _normalize_block(block: dict[str, Any]) -> dict[str, Any]:
    carriages_raw = block.get("carriages") if isinstance(block.get("carriages"), list) else []
    carriages: list[dict[str, Any]] = []
    for idx, c in enumerate(carriages_raw):
        if not isinstance(c, dict):
            continue
        cid = c.get("id") if c.get("id") is not None else c.get("carriage_id")
        try:
            carriage_id = int(cid) if cid is not None and str(cid).strip() != "" else None
            if carriage_id is not None and carriage_id <= 0:
                carriage_id = None
        except (TypeError, ValueError):
            carriage_id = None
        status = c.get("status")
        try:
            postings_count = int(c.get("postings_count") or 0)
        except (TypeError, ValueError):
            postings_count = 0
        formed = _is_formed(status)
        carriages.append(
            {
                "carriage_id": carriage_id,
                "index": idx + 1,
                "label": f"Отгрузка {idx + 1}",
                "postings_count": postings_count,
                "status": str(status or ""),
                "status_label": _carriage_status_label(status),
                "is_formed": formed,
                "can_form": not formed,
            }
        )
    if not carriages:
        try:
            draft_count = int(block.get("carriage_postings_count") or 0)
        except (TypeError, ValueError):
            draft_count = 0
        carriages.append(
            {
                "carriage_id": None,
                "index": 1,
                "label": "Отгрузка 1",
                "postings_count": draft_count,
                "status": "",
                "status_label": "Не сформирована",
                "is_formed": False,
                "can_form": True,
            }
        )

    departure = str(block.get("departure_date") or "").strip()
    day_label = ""
    if departure:
        try:
            d = datetime.fromisoformat(departure.replace("Z", "+00:00"))
            months = (
                "",
                "января",
                "февраля",
                "марта",
                "апреля",
                "мая",
                "июня",
                "июля",
                "августа",
                "сентября",
                "октября",
                "ноября",
                "декабря",
            )
            day_label = f"Ozon, {d.day} {months[d.month]}"
        except (ValueError, IndexError):
            day_label = departure

    return {
        "delivery_method_id": block.get("delivery_method_id"),
        "delivery_method_name": str(block.get("delivery_method_name") or "").strip(),
        "warehouse_id": block.get("warehouse_id"),
        "warehouse_name": str(block.get("warehouse_name") or "").strip(),
        "warehouse_city": str(block.get("warehouse_city") or "").strip(),
        "dropoff_address": str(block.get("dropoff_address") or "").strip(),
        "dropoff_point_type": str(block.get("dropoff_point_type") or "").strip(),
        "dropoff_point_type_label": _dropoff_type_label(block.get("dropoff_point_type")),
        "dropoff_point_id": block.get("dropoff_point_id"),
        "acceptance_label": _acceptance_label(block),
        "collected_label": _collected_label(block),
        "mandatory_packaged_count": block.get("mandatory_packaged_count"),
        "mandatory_postings_count": block.get("mandatory_postings_count"),
        "assembly_list_availability": bool(block.get("assembly_list_availability")),
        "can_create_another_carriage": bool(block.get("can_create_another_carriage")),
        "has_entrusted_acceptance": bool(block.get("has_entrusted_acceptance")),
        "departure_date": departure,
        "day_label": day_label or "Ozon",
        "tpl_provider_name": str(block.get("tpl_provider_name") or "").strip(),
        "carriages": carriages,
        "hint": (
            "Формировать отгрузку нужно, только если хотите изменить её состав "
            "или оформить пропуск"
        ),
    }


def build_shipments_view(
    *,
    client: oz.OzonFbsClient,
    warehouse_id: int | None,
    warehouse_name: str,
    departure: date,
    delivery_method_id: int | None = None,
    fallback_delivery_method: dict[str, Any] | None = None,
) -> dict[str, Any]:
    methods = list_delivery_methods_for_warehouse(client, warehouse_id=warehouse_id)
    methods = _merge_delivery_methods(methods, fallback_delivery_method)
    preferred = delivery_method_id
    if preferred is None and fallback_delivery_method:
        try:
            preferred = int(fallback_delivery_method.get("id") or 0) or None
        except (TypeError, ValueError):
            preferred = None
    selected = pick_default_delivery_method(methods, preferred_id=preferred)
    if not selected and preferred is not None:
        try:
            pref_id = int(preferred)
        except (TypeError, ValueError):
            pref_id = 0
        if pref_id > 0:
            fb_name = ""
            if isinstance(fallback_delivery_method, dict):
                fb_name = str(fallback_delivery_method.get("name") or "").strip()
            selected = {"id": pref_id, "name": fb_name or f"Метод доставки {pref_id}"}
            methods = _merge_delivery_methods(methods, selected)
    if not selected:
        return {
            "ok": False,
            "message": "Не найден активный метод доставки Ozon для склада поставки",
            "departure_date": departure.isoformat(),
            "delivery_methods": methods,
            "selected_delivery_method_id": None,
            "blocks": [],
            "barcode": None,
        }

    dep_iso = _departure_iso(departure)
    dep_carriage = _carriage_departure_date(departure)
    mid = int(selected["id"])
    try:
        raw = client.carriage_delivery_list(
            delivery_method_id=mid, departure_date=dep_carriage
        )
    except Exception as exc:
        raise _friendly_ozon_api_error(exc) from exc

    raw_blocks = [
        b
        for b in _carriage_delivery_blocks(raw)
        if _block_matches_departure(b, departure)
    ]
    blocks = [_normalize_block(b) for b in raw_blocks]
    if blocks:
        block_method = {
            "id": blocks[0].get("delivery_method_id") or mid,
            "name": blocks[0].get("delivery_method_name") or selected.get("name"),
        }
        methods = _merge_delivery_methods(methods, block_method)
        selected = pick_default_delivery_method(methods, preferred_id=mid) or selected
        mid = int(selected["id"])
    if not blocks:
        blocks = [
            _normalize_block(
                {
                    "delivery_method_id": mid,
                    "delivery_method_name": selected.get("name"),
                    "warehouse_id": warehouse_id,
                    "warehouse_name": warehouse_name,
                    "departure_date": dep_carriage,
                    "carriages": [],
                    "carriage_postings_count": 0,
                    "mandatory_packaged_count": 0,
                    "mandatory_postings_count": 0,
                }
            )
        ]

    barcode = None
    for block in blocks:
        for c in block.get("carriages") or []:
            if not c.get("is_formed") or not c.get("carriage_id"):
                continue
            try:
                barcode = fetch_carriage_barcode(
                    client, carriage_id=int(c["carriage_id"])
                )
            except Exception as exc:
                _log.warning("barcode fetch skipped: %s", exc)
                barcode = None
            if barcode and (
                barcode.get("barcode_text") or barcode.get("barcode_image_base64")
            ):
                break
        if barcode and (barcode.get("barcode_text") or barcode.get("barcode_image_base64")):
            break

    return {
        "ok": True,
        "message": "",
        "departure_date": departure.isoformat(),
        "departure_date_api": dep_iso,
        "delivery_methods": methods,
        "selected_delivery_method_id": mid,
        "selected_delivery_method_name": str(selected.get("name") or ""),
        "warehouse_id": warehouse_id,
        "warehouse_name": warehouse_name or "",
        "blocks": blocks,
        "barcode": barcode,
    }


def get_supply_shipments(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client: oz.OzonFbsClient,
    departure_date: object = None,
    delivery_method_id: object = None,
) -> dict[str, Any]:
    supply = oz_sup.get_supply(
        repo, user_id=user_id, source_id=source_id, supply_id=supply_id
    )
    if not supply:
        raise RuntimeError("Поставка не найдена")
    wh_id = supply.get("warehouse_id")
    try:
        warehouse_id = int(wh_id) if wh_id is not None else None
    except (TypeError, ValueError):
        warehouse_id = None
    warehouse_name = str(supply.get("warehouse_name") or "").strip()
    day = parse_departure_date(departure_date)
    pref = None
    if delivery_method_id is not None and str(delivery_method_id).strip() != "":
        try:
            pref = int(delivery_method_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Некорректный delivery_method_id") from exc
    view = build_shipments_view(
        client=client,
        warehouse_id=warehouse_id,
        warehouse_name=warehouse_name,
        departure=day,
        delivery_method_id=pref,
        fallback_delivery_method=oz_sup.delivery_method_for_supply(
            repo,
            user_id=user_id,
            source_id=source_id,
            supply_id=str(supply_id),
        ),
    )
    view["supply_id"] = supply.get("supply_id")
    view["supply_name"] = supply.get("name") or supply.get("supply_id")
    return view


def form_shipment(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client: oz.OzonFbsClient,
    departure_date: object = None,
    delivery_method_id: object = None,
    containers_count: object = None,
    wait_seconds: float = 12.0,
) -> dict[str, Any]:
    """«Сформировать» → POST /v2/posting/fbs/act/create (+ poll check-status)."""
    day = parse_departure_date(departure_date)
    view = get_supply_shipments(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        client=client,
        departure_date=day.isoformat(),
        delivery_method_id=delivery_method_id,
    )
    mid = view.get("selected_delivery_method_id")
    if mid is None:
        raise RuntimeError(view.get("message") or "Нет метода доставки")
    dep_iso = str(view.get("departure_date_api") or _departure_iso(day))
    cc = None
    if containers_count is not None and str(containers_count).strip() != "":
        try:
            cc = int(containers_count)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Некорректное число грузомест") from exc

    created = client.fbs_act_create(
        delivery_method_id=int(mid),
        departure_date=dep_iso,
        containers_count=cc,
    )
    result = created.get("result") if isinstance(created.get("result"), dict) else created
    try:
        act_id = int(result.get("id") if isinstance(result, dict) else created.get("id"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError(f"Ozon act/create: неожиданный ответ {created!r}") from exc

    status = ""
    deadline = time.monotonic() + max(float(wait_seconds), 0.0)
    while True:
        try:
            st = client.fbs_act_check_status(act_id=act_id)
        except Exception as exc:
            _log.warning("act check-status failed id=%s: %s", act_id, exc)
            break
        body = st.get("result") if isinstance(st.get("result"), dict) else st
        status = str((body or {}).get("status") or "").strip()
        if status in {"ready", "error", "cancelled"} or status.startswith("The next"):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(1.2)

    if status == "error":
        raise RuntimeError("Ozon не смог сформировать документы отгрузки (status=error)")
    if status == "cancelled":
        raise RuntimeError("Формирование документов отгрузки отменено Ozon")

    refreshed = get_supply_shipments(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        client=client,
        departure_date=day.isoformat(),
        delivery_method_id=int(mid),
    )
    # Prefer barcode for the act we just created.
    try:
        barcode = fetch_carriage_barcode(client, carriage_id=act_id)
        if barcode.get("barcode_text") or barcode.get("barcode_image_base64"):
            refreshed["barcode"] = barcode
    except Exception:
        pass
    refreshed["formed_act_id"] = act_id
    refreshed["form_status"] = status or "in_process"
    refreshed["message"] = (
        "Отгрузка сформирована"
        if status == "ready"
        else ("Документы ещё формируются — обновите через несколько секунд" if status == "in_process" else "Запрос на формирование отправлен")
    )
    refreshed["ok"] = True
    return refreshed


def render_shipment_barcode_print_html(
    *,
    supply_name: str,
    warehouse_name: str,
    barcode_text: str,
    barcode_image_base64: str,
    content_type: str = "image/png",
) -> str:
    from .ozon_fbs_supplies import _esc

    title = _esc(supply_name or "Поставка")
    wh = _esc(warehouse_name or "")
    text = _esc(barcode_text or "")
    b64 = str(barcode_image_base64 or "").strip()
    ctype = _esc(content_type or "image/png")
    if b64:
        body = f"""
        <section class="label barcode">
          <img src="data:{ctype};base64,{b64}" alt="ШК поставки" />
        </section>"""
    elif text:
        body = f"""
        <section class="label barcode text-only">
          <div class="code">{text}</div>
        </section>"""
    else:
        body = '<p style="padding:12px">Нет штрихкода для печати.</p>'
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"/>
<title>ШК поставки {title}</title>
<style>
  @page {{ size: 58mm 40mm; margin: 0; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; color: #0f172a; }}
  .label {{
    width: 58mm; height: 40mm; page-break-after: always;
    overflow: hidden; position: relative;
  }}
  .label.barcode {{
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 2mm;
  }}
  .label.barcode img {{
    width: 56mm; max-height: 34mm; object-fit: contain;
  }}
  .label.barcode.text-only .code {{
    font-size: 14px; font-weight: 800; letter-spacing: 0.04em; text-align: center;
    word-break: break-all; padding: 2mm;
  }}
  .toolbar {{ padding: 8px 12px; }}
  @media print {{ .toolbar {{ display: none !important; }} }}
</style></head><body>
  <div class="toolbar"><button onclick="window.print()">Печать</button>
    <span style="margin-left:8px;color:#64748b;font-size:13px">58×40 · ШК поставки Ozon{f" · {wh}" if wh else ""}</span>
  </div>
  {body}
  <script>window.addEventListener('load',function(){{ setTimeout(function(){{ window.print(); }}, 300); }});</script>
</body></html>"""


def build_shipment_barcode_print(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client: oz.OzonFbsClient,
    departure_date: object = None,
    delivery_method_id: object = None,
    carriage_id: object = None,
) -> str:
    view = get_supply_shipments(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        client=client,
        departure_date=departure_date,
        delivery_method_id=delivery_method_id,
    )
    barcode = view.get("barcode") if isinstance(view.get("barcode"), dict) else None
    cid = None
    if carriage_id is not None and str(carriage_id).strip() != "":
        try:
            cid = int(carriage_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Некорректный carriage_id") from exc
    if cid and cid > 0:
        try:
            fetched = fetch_carriage_barcode(client, carriage_id=cid)
            if fetched.get("barcode_text") or fetched.get("barcode_image_base64"):
                barcode = fetched
        except Exception as exc:
            _log.warning("barcode print fetch id=%s: %s", cid, exc)
    if not barcode or not (
        barcode.get("barcode_text") or barcode.get("barcode_image_base64")
    ):
        raise RuntimeError("Штрихкод появится после формирования отгрузки")
    return render_shipment_barcode_print_html(
        supply_name=str(view.get("supply_name") or supply_id),
        warehouse_name=str(view.get("warehouse_name") or ""),
        barcode_text=str(barcode.get("barcode_text") or ""),
        barcode_image_base64=str(barcode.get("barcode_image_base64") or ""),
        content_type=str(barcode.get("content_type") or "image/png"),
    )
