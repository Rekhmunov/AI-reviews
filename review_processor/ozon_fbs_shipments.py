"""Ozon FBS «Отгрузки» (carriage / act) — Seller API wrappers for the supply modal.

Key Seller API methods (docs.ozon.ru):
- ``POST /v2/delivery-method/list`` — методы доставки склада (``filter.warehouse_ids``, cursor)
- ``POST /v2/carriage/delivery/list`` — карточка отгрузки на дату + метод (``filter`` + cursor)
- ``POST /v2/posting/fbs/act/create`` — кнопка «Сформировать»
- ``POST /v2/posting/fbs/act/check-status`` — статус формирования документов
- ``POST /v2/posting/fbs/act/get-barcode`` — изображение ШК поставки
- ``POST /v2/posting/fbs/act/get-barcode/text`` — текст ШК поставки
- ``POST /v1/carriage/get`` — актуальный статус отгрузки
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
    if (
        "there_are_incomplete_carriages" in low
        or "незакрыт" in low
        or "incomplete_carriage" in low
    ):
        return RuntimeError(
            "По этому методу доставки есть незакрытые отгрузки. "
            "Подтвердите или закройте текущую отгрузку, "
            "иначе новую сформировать нельзя."
        )
    return RuntimeError(text)


def _delivery_method_rows(data: dict[str, Any]) -> tuple[list[dict[str, Any]], bool, str]:
    """Normalize v2 delivery-method/list payloads → (rows, has_next, cursor)."""
    top = data.get("delivery_methods")
    if isinstance(top, list):
        rows = [x for x in top if isinstance(x, dict)]
        return rows, bool(data.get("has_next")), str(data.get("cursor") or "")
    result = data.get("result")
    if isinstance(result, list):
        rows = [x for x in result if isinstance(x, dict)]
        return rows, bool(data.get("has_next")), str(data.get("cursor") or "")
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
            cursor = str(result.get("cursor") or data.get("cursor") or "")
            return rows, has_next, cursor
    return [], False, ""


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

# Carriage statuses that mean documents exist (no «Сформировать»).
_OPEN_CARRIAGE_STATUSES = frozenset(
    {
        "new",
        "formed",
        "confirmed",
        "ready",
        "sended",
        "sent",
        "shipped",
        "closed",
        "received",
        "completed",
        "formed_partially",
        "ожидает подтверждения",
        "сформирована",
        "подтверждена",
    }
)

_OPEN_CARRIAGE_BLOCK_HINT = (
    "По этому методу есть незакрытые отгрузки. "
    "Закройте их перед формированием на другую дату."
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
    cursor: str | None = None
    for _ in range(20):
        try:
            data = client.delivery_method_list(
                warehouse_id=warehouse_id,
                status="ACTIVE",
                limit=50,
                cursor=cursor,
            )
        except RuntimeError as exc:
            raise _friendly_ozon_api_error(exc) from exc
        batch, has_next, next_cursor = _delivery_method_rows(data)
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
        cursor = next_cursor.strip() or None
        if not cursor:
            break
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
    """Portal-aligned labels for carriage lifecycle."""
    st = str(status or "").strip()
    if not st:
        return "Не сформирована"
    low = st.casefold()
    if "не" in low and "форм" in low:
        return "Не сформирована"
    if low in {"new", "created", "pending"} or "ожидает подтвержд" in low:
        return "Ожидает подтверждения"
    if low in {"formed", "formed_partially"} or ("форм" in low and "не" not in low):
        return "Сформирована"
    if low in {"confirmed", "ready"} or "подтвержд" in low:
        return "Подтверждена"
    if low in {"sended", "sent", "shipped", "closed", "received", "completed"}:
        return "Закрыта"
    return st


def _carriage_is_open(status: object, *, carriage_id: int | None) -> bool:
    """True when an act/carriage already exists (Form must stay hidden)."""
    if carriage_id is not None and carriage_id > 0:
        st = str(status or "").strip().casefold()
        if not st or st in _OPEN_CARRIAGE_STATUSES or "форм" in st or "подтвержд" in st:
            return True
        if st not in {"cancelled", "canceled", "error", "deleted"}:
            return True
    low = str(status or "").strip().casefold()
    return low in _OPEN_CARRIAGE_STATUSES


def _is_formed(status: object, *, carriage_id: int | None = None) -> bool:
    """Documents exist / barcode available (not a blank draft)."""
    return _carriage_is_open(status, carriage_id=carriage_id) and _carriage_status_label(
        status
    ) != "Не сформирована"


def _dropoff_point_label(raw: object) -> str:
    """«Пункт» field — SortCenter → Сортировочный центр."""
    t = str(raw or "").strip()
    low = t.casefold().replace(" ", "").replace("_", "")
    mapping = {
        "pvz": "Пункт выдачи",
        "sc": "Сортировочный центр",
        "sortcenter": "Сортировочный центр",
        "sortingcenter": "Сортировочный центр",
        "sorting_center": "Сортировочный центр",
        "dropoff": "Пункт приема",
    }
    if low in mapping:
        return mapping[low]
    if "sort" in low and "centr" in low:
        return "Сортировочный центр"
    if t:
        return t
    return "Сортировочный центр"


def _shipment_method_label(block: dict[str, Any]) -> str:
    """«Способ отгрузки» — always portal wording for drop-off warehouses."""
    first_mile = str(block.get("first_mile_type") or "").strip().casefold()
    if first_mile in {"pickup", "pick_up"}:
        return "Самовывоз Ozon"
    if first_mile in {"courier"}:
        return "Курьер"
    return "В пункт приема"


def _acceptance_label(block: dict[str, Any]) -> str:
    """Portal «Приём отправлений» uses timeslot_to (e.g. 21:00), not recommended_time_local."""
    city = str(block.get("warehouse_city") or "").strip()
    local = str(block.get("timeslot_to") or "").strip()
    if not local:
        # cutoff_at is usually timeslot end minus 1 minute (20:59) → show HH:00 next minute? Portal 21:00.
        cutoff = str(block.get("cutoff_at") or "").strip()
        if cutoff:
            try:
                dt = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
                # Round up :59 → next hour for portal parity (20:59 → 21:00).
                if dt.minute >= 59:
                    hour = (dt.hour + 1) % 24
                    local = f"{hour:02d}:00"
                else:
                    local = dt.strftime("%H:%M")
            except ValueError:
                local = ""
    if not local:
        local = str(block.get("recommended_time_local") or "").strip()
    if local and city:
        return f"до {local} ({city})"
    if local:
        return f"до {local}"
    return "—"


def _as_nonneg_int(value: object) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _draft_postings_count(block: dict[str, Any]) -> int:
    """Postings in draft/unformed slots (carriage id missing or ≤0)."""
    carriages = block.get("carriages") if isinstance(block.get("carriages"), list) else []
    total = 0
    for c in carriages:
        if not isinstance(c, dict):
            continue
        cid = c.get("id") if c.get("id") is not None else c.get("carriage_id")
        try:
            carriage_id = int(cid) if cid is not None and str(cid).strip() != "" else 0
        except (TypeError, ValueError):
            carriage_id = 0
        if carriage_id > 0:
            continue
        total += _as_nonneg_int(c.get("postings_count"))
    return total


def _collected_label(block: dict[str, Any]) -> str:
    """Seller-style «Собрано заказов: X из Y».

    Ozon v2 ``/v2/carriage/delivery/list`` splits progress into mandatory and
    optional pools:

    - ``mandatory_packaged_count`` / ``mandatory_postings_count``
    - ``optional_packaged_count``
    - ``postings_for_another_carriage_count`` (optional pool total), else draft
      carriages (id ≤ 0), else ``carriage_postings_count`` when mandatory is empty
    """
    mand_pack = _as_nonneg_int(block.get("mandatory_packaged_count"))
    mand_total = _as_nonneg_int(block.get("mandatory_postings_count"))
    opt_pack = _as_nonneg_int(block.get("optional_packaged_count"))
    for_next = _as_nonneg_int(block.get("postings_for_another_carriage_count"))
    carriage_n = _as_nonneg_int(block.get("carriage_postings_count"))
    draft_n = _draft_postings_count(block)

    packaged = mand_pack + opt_pack
    optional_pool = draft_n or for_next
    total = mand_total + optional_pool
    # Optional-only days: progress lives in formed/new carriages, not mandatory_*.
    if total <= 0 and carriage_n > 0:
        total = carriage_n
    if total <= 0 and packaged > 0:
        total = packaged
    if total > 0:
        return f"{packaged} из {total}"
    return "—"


def fetch_warehouse_barcode(
    client: oz.OzonFbsClient, *, warehouse_id: int
) -> dict[str, Any]:
    """Permanent «Штрихкод для склада» — always the same for a given FBS warehouse.

    Ozon Seller API uses the same ``/v2/posting/fbs/act/get-barcode`` endpoints with
    ``warehouse_id`` as ``id`` (portal label «Штрихкод для склада …»). The text value
    equals ``warehouse_id`` (e.g. 1020005028015630).
    """
    wid = int(warehouse_id)
    if wid <= 0:
        return {}
    fetched = fetch_carriage_barcode(client, carriage_id=wid)
    text = str(fetched.get("barcode_text") or "").strip() or str(wid)
    fetched["barcode_text"] = text
    fetched["warehouse_id"] = wid
    fetched["kind"] = "warehouse"
    if fetched.get("barcode_image_base64") and not fetched.get("barcode_label_base64"):
        composed = compose_shipment_barcode_label_png(
            barcode_image_base64=str(fetched.get("barcode_image_base64") or ""),
            barcode_text=text,
        )
        if composed:
            fetched["barcode_label_base64"] = base64.b64encode(composed).decode("ascii")
    return ensure_shipment_barcode_assets(fetched)


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
    label_b64 = ""
    if image_b64 and text:
        composed = compose_shipment_barcode_label_png(
            barcode_image_base64=image_b64, barcode_text=text
        )
        if composed:
            label_b64 = base64.b64encode(composed).decode("ascii")
    return ensure_shipment_barcode_assets(
        {
            "carriage_id": int(carriage_id),
            "barcode_text": text,
            "barcode_image_base64": image_b64,
            "barcode_label_base64": label_b64,
            "content_type": content_type,
        }
    )


def render_code128_barcode_png(barcode_text: str, *, for_print: bool = False) -> bytes | None:
    """Render Code128 bars only (no HRI) for warehouse / act stickers."""
    text = str(barcode_text or "").strip()
    if not text:
        return None
    try:
        import barcode
        from barcode.writer import ImageWriter
        from io import BytesIO

        cls = barcode.get_barcode_class("code128")
        bc = cls(text, writer=ImageWriter())
        buf = BytesIO()
        bc.write(
            buf,
            options={
                "write_text": False,
                "module_height": 16 if for_print else 14,
                "module_width": 0.38 if for_print else 0.28,
                "quiet_zone": 2 if for_print else 3,
            },
        )
        return buf.getvalue()
    except Exception as exc:
        _log.warning(
            "code128 render failed %s: %s (install python-barcode if missing)",
            text[:24],
            exc,
        )
        return None


def ensure_shipment_barcode_assets(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure barcode image + composed label (bars + digits) exist when text is known."""
    out = dict(data or {})
    text = str(out.get("barcode_text") or "").strip()
    if not text:
        return out
    b64 = str(out.get("barcode_image_base64") or "").strip()
    label_b64 = str(out.get("barcode_label_base64") or "").strip()
    if not b64:
        generated = render_code128_barcode_png(text)
        if generated:
            b64 = base64.b64encode(generated).decode("ascii")
            out["barcode_image_base64"] = b64
            out.setdefault("content_type", "image/png")
    if not label_b64 and b64:
        composed = compose_shipment_barcode_label_png(
            barcode_image_base64=b64, barcode_text=text
        )
        if composed:
            out["barcode_label_base64"] = base64.b64encode(composed).decode("ascii")
    return out


def _enrich_carriage_from_get(
    client: oz.OzonFbsClient | None, carriage_id: int, status: object
) -> str:
    """Prefer /v1/carriage/get status — delivery/list can still report «new»."""
    if client is None or carriage_id <= 0:
        return str(status or "")
    try:
        got = client.carriage_get(carriage_id=carriage_id)
    except Exception as exc:
        _log.warning("ozon carriage/get id=%s: %s", carriage_id, exc)
        return str(status or "")
    remote = str(got.get("status") or "").strip()
    return remote or str(status or "")


def _normalize_carriage(
    c: dict[str, Any],
    *,
    idx: int,
    client: oz.OzonFbsClient | None = None,
    force_no_form: bool = False,
) -> dict[str, Any]:
    cid = c.get("id") if c.get("id") is not None else c.get("carriage_id")
    try:
        carriage_id = int(cid) if cid is not None and str(cid).strip() != "" else None
        if carriage_id is not None and carriage_id <= 0:
            carriage_id = None
    except (TypeError, ValueError):
        carriage_id = None
    status = c.get("status")
    if carriage_id is not None:
        status = _enrich_carriage_from_get(client, carriage_id, status)
    try:
        postings_count = int(c.get("postings_count") or 0)
    except (TypeError, ValueError):
        postings_count = 0
    open_act = _carriage_is_open(status, carriage_id=carriage_id)
    status_label = _carriage_status_label(status) if open_act or status else "Не сформирована"
    if carriage_id is not None and status_label == "Не сформирована":
        # Act exists but list status was empty/unknown — treat as formed draft on portal.
        status_label = "Сформирована"
        open_act = True
    label = f"Отгрузка {carriage_id}" if carriage_id is not None else f"Отгрузка {idx}"
    available = c.get("available_actions") if isinstance(c.get("available_actions"), list) else []
    available_norm = {str(a).strip().casefold() for a in available if str(a).strip()}
    return {
        "carriage_id": carriage_id,
        "index": idx,
        "label": label,
        "postings_count": postings_count,
        "status": str(status or ""),
        "status_label": status_label,
        "is_formed": open_act,
        "can_form": (not open_act) and (not force_no_form),
        "has_assembly_list": "get_assembly_list" in available_norm or not available_norm,
    }


def _normalize_block(
    block: dict[str, Any],
    *,
    client: oz.OzonFbsClient | None = None,
    force_no_form: bool = False,
) -> dict[str, Any]:
    carriages_raw = block.get("carriages") if isinstance(block.get("carriages"), list) else []
    carriages: list[dict[str, Any]] = []
    for idx, c in enumerate(carriages_raw):
        if not isinstance(c, dict):
            continue
        carriages.append(
            _normalize_carriage(
                c, idx=idx + 1, client=client, force_no_form=force_no_form
            )
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
                "can_form": not force_no_form,
                "has_assembly_list": True,
            }
        )

    departure = str(block.get("departure_date") or "").strip()
    day_label = ""
    if departure:
        try:
            if "T" in departure:
                d = datetime.fromisoformat(departure.replace("Z", "+00:00"))
            else:
                d = datetime.fromisoformat(departure[:10])
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

    # v2 has no assembly_list_availability — infer from carriage available_actions.
    if "assembly_list_availability" in block:
        assembly_ok = bool(block.get("assembly_list_availability"))
    else:
        assembly_ok = any(bool(c.get("has_assembly_list", True)) for c in carriages)

    return {
        "delivery_method_id": block.get("delivery_method_id"),
        "delivery_method_name": str(block.get("delivery_method_name") or "").strip(),
        "warehouse_id": block.get("warehouse_id"),
        "warehouse_name": str(block.get("warehouse_name") or "").strip(),
        "warehouse_city": str(block.get("warehouse_city") or "").strip(),
        "dropoff_address": str(block.get("dropoff_address") or "").strip(),
        "dropoff_point_type": str(block.get("dropoff_point_type") or "").strip(),
        "dropoff_point_type_label": _dropoff_point_label(block.get("dropoff_point_type")),
        "shipment_method_label": _shipment_method_label(block),
        "dropoff_point_id": block.get("dropoff_point_id"),
        "acceptance_label": _acceptance_label(block),
        "collected_label": _collected_label(block),
        "mandatory_packaged_count": block.get("mandatory_packaged_count"),
        "mandatory_postings_count": block.get("mandatory_postings_count"),
        "assembly_list_availability": assembly_ok,
        "can_create_another_carriage": bool(block.get("can_create_another_carriage")),
        "has_entrusted_acceptance": bool(block.get("has_entrusted_acceptance")),
        "departure_date": departure,
        "day_label": day_label or "Ozon",
        "tpl_provider_name": str(block.get("tpl_provider_name") or "").strip(),
        "carriages": carriages,
        "hint": "",
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

    raw_blocks = _carriage_delivery_blocks(raw)
    matched = [b for b in raw_blocks if _block_matches_departure(b, departure)]
    other_day = [b for b in raw_blocks if not _block_matches_departure(b, departure)]
    blocking = False
    force_no_form = False

    # Ozon often keeps returning the open carriage day even when another date is
    # requested. Surfacing those blocks prevents a fake «Сформировать» that then
    # fails with there_are_incomplete_carriages.
    if not matched and other_day:
        force_no_form = True
        blocking = True
        blocks = [
            _normalize_block(b, client=client, force_no_form=True) for b in other_day
        ]
    else:
        blocks = [
            _normalize_block(b, client=client, force_no_form=False) for b in matched
        ]
        if other_day:
            # Same method still has open acts on another day — disable form.
            force_no_form = True
            blocking = True
            for block in blocks:
                for c in block.get("carriages") or []:
                    c["can_form"] = False

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
                    "first_mile_type": "dropoff",
                    "dropoff_point_type": "SortCenter",
                    "carriages": [],
                    "carriage_postings_count": 0,
                    "mandatory_packaged_count": 0,
                    "mandatory_postings_count": 0,
                },
                client=client,
                force_no_form=force_no_form,
            )
        ]

    barcode = None
    for block in blocks:
        for c in block.get("carriages") or []:
            if not c.get("is_formed") or not c.get("carriage_id"):
                continue
            try:
                fetched = fetch_carriage_barcode(
                    client, carriage_id=int(c["carriage_id"])
                )
            except Exception as exc:
                _log.warning("barcode fetch skipped: %s", exc)
                fetched = None
            if not fetched or not (
                fetched.get("barcode_text") or fetched.get("barcode_image_base64")
            ):
                continue
            # One ШК per carriage_id (Seller API get-barcode takes a single act id).
            c["barcode"] = fetched
            if barcode is None:
                barcode = fetched

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
        # Convenience default = first formed carriage barcode (UI may switch).
        "barcode": barcode,
        "has_open_carriages_blocking": bool(blocking),
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
    warehouse_barcode: dict[str, Any] | None = None
    if warehouse_id is not None and int(warehouse_id) > 0:
        try:
            warehouse_barcode = fetch_warehouse_barcode(
                client, warehouse_id=int(warehouse_id)
            )
        except Exception as exc:
            _log.warning("warehouse barcode fetch wh=%s: %s", warehouse_id, exc)
        if not warehouse_barcode or not str(
            warehouse_barcode.get("barcode_text") or ""
        ).strip():
            warehouse_barcode = {
                "warehouse_id": int(warehouse_id),
                "barcode_text": str(int(warehouse_id)),
                "kind": "warehouse",
            }
    if warehouse_barcode:
        warehouse_barcode = ensure_shipment_barcode_assets(warehouse_barcode)
    view["warehouse_barcode"] = warehouse_barcode
    # Default sticker in UI/print = permanent warehouse barcode (not act/carriage).
    if warehouse_barcode and (
        warehouse_barcode.get("barcode_text")
        or warehouse_barcode.get("barcode_image_base64")
    ):
        view["barcode"] = warehouse_barcode
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
    if view.get("has_open_carriages_blocking"):
        raise RuntimeError(_OPEN_CARRIAGE_BLOCK_HINT)
    any_can_form = any(
        bool(c.get("can_form"))
        for block in (view.get("blocks") or [])
        for c in (block.get("carriages") or [])
    )
    if not any_can_form:
        raise RuntimeError(
            "Отгрузка уже сформирована. "
            "Повторно нажимать «Сформировать» не нужно — используйте штрихкод поставки."
        )
    dep_iso = str(view.get("departure_date_api") or _departure_iso(day))
    cc = None
    if containers_count is not None and str(containers_count).strip() != "":
        try:
            cc = int(containers_count)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Некорректное число грузомест") from exc

    try:
        created = client.fbs_act_create(
            delivery_method_id=int(mid),
            departure_date=dep_iso,
            containers_count=cc,
        )
    except Exception as exc:
        raise _friendly_ozon_api_error(exc) from exc
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
    # Prefer barcode for the act we just created; attach to that carriage row too.
    try:
        barcode = fetch_carriage_barcode(client, carriage_id=act_id)
        if barcode.get("barcode_text") or barcode.get("barcode_image_base64"):
            refreshed["barcode"] = barcode
            for block in refreshed.get("blocks") or []:
                for c in block.get("carriages") or []:
                    try:
                        cid = int(c.get("carriage_id") or 0)
                    except (TypeError, ValueError):
                        cid = 0
                    if cid == int(act_id):
                        c["barcode"] = barcode
                        break
    except Exception:
        pass
    refreshed["formed_act_id"] = act_id
    refreshed["selected_carriage_id"] = int(act_id)
    refreshed["form_status"] = status or "in_process"
    refreshed["message"] = (
        "Отгрузка сформирована"
        if status == "ready"
        else ("Документы ещё формируются — обновите через несколько секунд" if status == "in_process" else "Запрос на формирование отправлен")
    )
    refreshed["ok"] = True
    return refreshed


def compose_shipment_barcode_label_png(
    *,
    barcode_image_base64: str,
    barcode_text: str,
    for_print: bool = False,
) -> bytes | None:
    """Build a PNG with Code128 bars + human-readable digits underneath."""
    b64 = str(barcode_image_base64 or "").strip()
    text = str(barcode_text or "").strip()
    if not b64 or not text:
        return None
    try:
        from io import BytesIO

        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        _log.warning("barcode compose: Pillow unavailable: %s", exc)
        return None
    try:
        raw = base64.b64decode(b64, validate=False)
        bars = Image.open(BytesIO(raw)).convert("RGB")
    except Exception as exc:
        _log.debug("barcode compose: bad image: %s", exc)
        return None

    # Target label proportions close to Ozon seller sticker (wide bars + HRI).
    target_w = max(int(bars.width), 520 if for_print else 420)
    # Scale bars to nearly full width while keeping a readable bar height.
    bar_h = max(
        88 if for_print else 72,
        min(156 if for_print else 140, int(round(target_w * (0.24 if for_print else 0.22)))),
    )
    scaled = bars.resize((target_w, bar_h), Image.Resampling.NEAREST)

    pad_x = 4 if for_print else 12
    pad_top = 8 if for_print else 10
    pad_bottom = 8 if for_print else 10
    gap = 6 if for_print else 8
    text_h = 26 if for_print else 28
    out_w = target_w + pad_x * 2
    out_h = pad_top + bar_h + gap + text_h + pad_bottom
    canvas = Image.new("RGB", (out_w, out_h), (255, 255, 255))
    canvas.paste(scaled, (pad_x, pad_top))

    draw = ImageDraw.Draw(canvas)
    font = None
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            font = ImageFont.truetype(path, 22)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    text_y = pad_top + bar_h + gap
    draw.text(
        (out_w / 2, text_y + text_h / 2),
        text,
        fill=(15, 23, 42),
        font=font,
        anchor="mm",
    )
    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


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
    ensured = ensure_shipment_barcode_assets(
        {
            "barcode_text": barcode_text,
            "barcode_image_base64": barcode_image_base64,
            "content_type": content_type,
        }
    )
    text_raw = str(ensured.get("barcode_text") or "").strip()
    text = _esc(text_raw)
    label_b64 = str(ensured.get("barcode_label_base64") or "").strip()
    b64 = str(ensured.get("barcode_image_base64") or "").strip()
    print_label = compose_shipment_barcode_label_png(
        barcode_image_base64=b64,
        barcode_text=text_raw,
        for_print=True,
    )
    if print_label:
        label_b64 = base64.b64encode(print_label).decode("ascii")
    ctype = "image/png"
    if label_b64:
        body = f"""
        <section class="label barcode">
          <img src="data:{ctype};base64,{label_b64}" alt="ШК поставки {text}" />
        </section>"""
    elif b64:
        ctype = _esc(content_type or "image/png")
        text_block = f'<div class="code">{text}</div>' if text else ""
        body = f"""
        <section class="label barcode">
          <img src="data:{ctype};base64,{b64}" alt="ШК поставки" />
          {text_block}
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
    padding: 1mm 0.5mm;
    gap: 1mm;
  }}
  .label.barcode img {{
    width: 57mm; height: auto; max-height: 38mm;
    object-fit: contain; object-position: center;
  }}
  .label.barcode .code {{
    font-family: "DejaVu Sans Mono", "Courier New", monospace;
    font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-align: center;
    line-height: 1.1; color: #0f172a;
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


def _resolve_shipments_barcode(
    view: dict[str, Any],
    client: oz.OzonFbsClient,
    *,
    carriage_id: object = None,
) -> dict[str, Any]:
    barcode = view.get("warehouse_barcode")
    if not isinstance(barcode, dict):
        barcode = view.get("barcode") if isinstance(view.get("barcode"), dict) else None
    cid = None
    if carriage_id is not None and str(carriage_id).strip() != "":
        try:
            cid = int(carriage_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Некорректный carriage_id") from exc
    wh_id = view.get("warehouse_id")
    try:
        wh_int = int(wh_id) if wh_id is not None else 0
    except (TypeError, ValueError):
        wh_int = 0
    if cid and cid > 0 and cid != wh_int:
        try:
            fetched = fetch_carriage_barcode(client, carriage_id=cid)
            if fetched.get("barcode_text") or fetched.get("barcode_image_base64"):
                barcode = fetched
        except Exception as exc:
            _log.warning("barcode fetch id=%s: %s", cid, exc)
    if not barcode or not (
        barcode.get("barcode_text") or barcode.get("barcode_image_base64")
    ):
        raise RuntimeError("Не удалось получить штрихкод склада")
    return ensure_shipment_barcode_assets(barcode)


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
    barcode = _resolve_shipments_barcode(view, client, carriage_id=carriage_id)
    return render_shipment_barcode_print_html(
        supply_name=str(view.get("supply_name") or supply_id),
        warehouse_name=str(view.get("warehouse_name") or ""),
        barcode_text=str(barcode.get("barcode_text") or ""),
        barcode_image_base64=str(barcode.get("barcode_image_base64") or ""),
        content_type=str(barcode.get("content_type") or "image/png"),
    )


def build_shipment_barcode_label_png(
    repo: ReviewRepository,
    *,
    user_id: int,
    source_id: int,
    supply_id: str,
    client: oz.OzonFbsClient,
    departure_date: object = None,
    delivery_method_id: object = None,
    carriage_id: object = None,
) -> bytes:
    view = get_supply_shipments(
        repo,
        user_id=user_id,
        source_id=source_id,
        supply_id=supply_id,
        client=client,
        departure_date=departure_date,
        delivery_method_id=delivery_method_id,
    )
    barcode = _resolve_shipments_barcode(view, client, carriage_id=carriage_id)
    label_b64 = str(barcode.get("barcode_label_base64") or "").strip()
    if not label_b64:
        raise RuntimeError("Не удалось сформировать PNG штрихкода")
    try:
        return base64.b64decode(label_b64, validate=False)
    except Exception as exc:
        raise RuntimeError("Не удалось декодировать PNG штрихкода") from exc
