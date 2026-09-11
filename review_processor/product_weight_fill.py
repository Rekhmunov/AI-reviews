"""Fill catalog product ``weight_kg`` from WB Content / Ozon Product APIs."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_log = logging.getLogger(__name__)

WB_CONTENT_API = "https://content-api.wildberries.ru"


def _as_positive_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        num = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    return round(num, 3)


def weight_kg_from_wb_card(card: dict[str, Any] | None) -> float | None:
    """Gross weight in kg from a WB content card."""
    if not isinstance(card, dict):
        return None
    dims = card.get("dimensions")
    if isinstance(dims, dict):
        for key in ("weightBrutto", "weightGross", "weight"):
            weight = _as_positive_float(dims.get(key))
            if weight is not None:
                return weight
    for key in ("weightBrutto", "weightGross", "weight"):
        weight = _as_positive_float(card.get(key))
        if weight is not None:
            return weight
    return None


def weight_kg_from_ozon_item(item: dict[str, Any] | None) -> float | None:
    """Packaged weight in kg from Ozon ``/v4/product/info/attributes`` item."""
    if not isinstance(item, dict):
        return None
    raw = _as_positive_float(item.get("weight"))
    if raw is None:
        return None
    unit = str(item.get("weight_unit") or item.get("weightUnit") or "g").strip().lower()
    if unit in {"kg", "кг", "kilogram", "kilograms"}:
        return round(raw, 3)
    if unit in {"lb", "lbs", "pound", "pounds"}:
        return round(raw * 0.45359237, 3)
    # Default Ozon attributes unit is grams.
    if unit in {"g", "gr", "gram", "grams", "гр", "г", ""}:
        return round(raw / 1000.0, 3)
    if raw >= 50:
        return round(raw / 1000.0, 3)
    return round(raw, 3)


def _wb_content_post(api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8")
    req = Request(
        f"{WB_CONTENT_API}/content/v2/get/cards/list",
        data=payload,
        method="POST",
        headers={
            "Authorization": str(api_key or "").strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FeedPilot-ProductWeights/1.0",
        },
    )
    try:
        with urlopen(req, timeout=45) as resp:
            raw = resp.read()
    except HTTPError as exc:
        err = ""
        try:
            err = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"WB Content HTTP {exc.code}: {err or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"WB Content network error: {exc.reason}") from exc
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("WB Content returned non-JSON") from exc
    return data if isinstance(data, dict) else {}


def _cards_from_wb_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    cards = data.get("cards")
    if isinstance(cards, list):
        return [c for c in cards if isinstance(c, dict)]
    nested = data.get("data")
    if isinstance(nested, dict) and isinstance(nested.get("cards"), list):
        return [c for c in nested["cards"] if isinstance(c, dict)]
    return []


def fetch_wb_weight_map(
    api_key: str,
    *,
    nm_ids: set[int],
    articles: set[str],
    max_pages: int = 200,
) -> dict[str, float]:
    """Map ``nm:<id>`` / ``article:<vendorCode>`` → weight_kg."""
    out: dict[str, float] = {}
    if not str(api_key or "").strip():
        return out
    need_nm = {int(x) for x in nm_ids if int(x) > 0}
    need_art = {str(a).strip() for a in articles if str(a).strip()}
    need_art_cf = {a.casefold() for a in need_art}
    if not need_nm and not need_art:
        return out

    def _ingest(card: dict[str, Any]) -> None:
        weight = weight_kg_from_wb_card(card)
        if weight is None:
            return
        try:
            nm = int(card.get("nmID") or card.get("nmId") or 0)
        except (TypeError, ValueError):
            nm = 0
        if nm > 0:
            out[f"nm:{nm}"] = weight
            need_nm.discard(nm)
        vendor = str(card.get("vendorCode") or card.get("vendor_code") or "").strip()
        if vendor:
            out[f"article:{vendor}"] = weight
            out[f"article:{vendor.casefold()}"] = weight
            need_art.discard(vendor)
            need_art_cf.discard(vendor.casefold())

    for nm in sorted(need_nm):
        try:
            data = _wb_content_post(
                api_key,
                {
                    "settings": {
                        "cursor": {"limit": 1},
                        "filter": {"withPhoto": -1, "nmID": int(nm)},
                    }
                },
            )
            for card in _cards_from_wb_response(data):
                _ingest(card)
        except Exception as exc:
            _log.warning("WB weight nm=%s failed: %s", nm, exc)
        time.sleep(0.21)

    if not need_art_cf:
        return out

    cursor: dict[str, Any] = {"limit": 100}
    for _page in range(max_pages):
        try:
            data = _wb_content_post(
                api_key,
                {
                    "settings": {
                        "cursor": cursor,
                        "filter": {"withPhoto": -1},
                    }
                },
            )
        except Exception as exc:
            _log.warning("WB weight catalog page failed: %s", exc)
            break
        cards = _cards_from_wb_response(data)
        if not cards:
            break
        for card in cards:
            _ingest(card)
        next_cursor = data.get("cursor") if isinstance(data.get("cursor"), dict) else {}
        updated_at = next_cursor.get("updatedAt")
        nm_cursor = next_cursor.get("nmID")
        if not updated_at or nm_cursor in (None, ""):
            break
        cursor = {"limit": 100, "updatedAt": updated_at, "nmID": nm_cursor}
        time.sleep(0.22)
        if not need_nm and not need_art_cf:
            break
    return out


def fetch_ozon_weight_map(
    client_id: str,
    api_key: str,
    *,
    offer_ids: set[str],
    skus: set[str],
    max_pages: int = 200,
) -> dict[str, float]:
    """Map ``offer:<id>`` / ``sku:<sku>`` → weight_kg."""
    out: dict[str, float] = {}
    cid = str(client_id or "").strip()
    key = str(api_key or "").strip()
    if not cid or not key:
        return out
    need_offers = {str(x).strip() for x in offer_ids if str(x).strip()}
    need_offers_cf = {x.casefold() for x in need_offers}
    need_skus = {str(x).strip() for x in skus if str(x).strip()}
    if not need_offers and not need_skus:
        return out

    from . import ozon_fbs as ozon_fbs_mod

    client = ozon_fbs_mod.OzonFbsClient(client_id=cid, api_key=key)

    def _ingest(item: dict[str, Any]) -> None:
        weight = weight_kg_from_ozon_item(item)
        if weight is None:
            return
        offer = str(item.get("offer_id") or "").strip()
        if offer:
            out[f"offer:{offer}"] = weight
            out[f"offer:{offer.casefold()}"] = weight
            need_offers.discard(offer)
            need_offers_cf.discard(offer.casefold())
        sku = str(item.get("sku") or "").strip()
        if sku:
            out[f"sku:{sku}"] = weight
            need_skus.discard(sku)

    pending_offers = sorted(need_offers)
    for i in range(0, len(pending_offers), 100):
        chunk = pending_offers[i : i + 100]
        try:
            data = client.post_json(
                "/v4/product/info/attributes",
                {
                    "filter": {"offer_id": chunk, "visibility": "ALL"},
                    "limit": 100,
                    "sort_dir": "ASC",
                },
            )
        except Exception as exc:
            _log.warning("Ozon weight offer chunk failed: %s", exc)
            continue
        result = data.get("result")
        if not isinstance(result, list):
            result = data.get("items") if isinstance(data.get("items"), list) else []
        for item in result:
            if isinstance(item, dict):
                _ingest(item)

    if not need_offers_cf and not need_skus:
        return out

    last_id = ""
    for _page in range(max_pages):
        body: dict[str, Any] = {
            "filter": {"visibility": "ALL"},
            "limit": 100,
            "sort_dir": "ASC",
        }
        if last_id:
            body["last_id"] = last_id
        try:
            data = client.post_json("/v4/product/info/attributes", body)
        except Exception as exc:
            _log.warning("Ozon weight attributes page failed: %s", exc)
            break
        result = data.get("result")
        if not isinstance(result, list):
            result = data.get("items") if isinstance(data.get("items"), list) else []
        if not result:
            break
        for item in result:
            if isinstance(item, dict):
                _ingest(item)
        last_id = str(data.get("last_id") or "").strip()
        if not last_id or (not need_offers_cf and not need_skus):
            break
    return out


def collect_marketplace_weights(*, repository: Any, user_id: int) -> dict[int, dict[str, Any]]:
    """Fetch weights from enabled WB/Ozon FBS sources."""
    from . import ozon_fbs as ozon_fbs_mod
    from . import wb_fbs as wb_fbs_mod

    products = repository.list_product_photos(user_id=user_id)
    nm_ids: set[int] = set()
    articles: set[str] = set()
    offer_ids: set[str] = set()
    skus: set[str] = set()
    for p in products:
        wb = str(p.get("wb_nmid") or "").strip()
        if wb.isdigit():
            nm_ids.add(int(wb))
        art = str(p.get("supplier_article") or "").strip()
        if art:
            articles.add(art)
            offer_ids.add(art)
        oz = str(p.get("ozon_sku") or "").strip()
        if oz:
            skus.add(oz)
            offer_ids.add(oz)

    found: dict[int, list[dict[str, Any]]] = {}

    for job in wb_fbs_mod.list_fbs_sync_jobs(repository, user_id=user_id):
        api_key = str(job.get("api_key") or "").strip()
        name = str(job.get("name") or "WB")
        if not api_key:
            continue
        try:
            weights = fetch_wb_weight_map(api_key, nm_ids=nm_ids, articles=articles)
        except Exception as exc:
            _log.warning("WB weights source %s: %s", name, exc)
            continue
        for p in products:
            pid = int(p.get("id") or 0)
            if pid <= 0:
                continue
            weight = None
            wb = str(p.get("wb_nmid") or "").strip()
            if wb.isdigit():
                weight = weights.get(f"nm:{int(wb)}")
            if weight is None:
                art = str(p.get("supplier_article") or "").strip()
                if art:
                    weight = weights.get(f"article:{art}") or weights.get(
                        f"article:{art.casefold()}"
                    )
            if weight is None:
                continue
            found.setdefault(pid, []).append(
                {"platform": "wb", "weight_kg": weight, "source_name": name}
            )

    for job in ozon_fbs_mod.list_fbs_sync_jobs(repository, user_id=user_id):
        client_id = str(job.get("client_id") or "").strip()
        api_key = str(job.get("api_key") or "").strip()
        name = str(job.get("name") or "Ozon")
        if not client_id or not api_key:
            continue
        try:
            weights = fetch_ozon_weight_map(
                client_id, api_key, offer_ids=offer_ids, skus=skus
            )
        except Exception as exc:
            _log.warning("Ozon weights source %s: %s", name, exc)
            continue
        for p in products:
            pid = int(p.get("id") or 0)
            if pid <= 0:
                continue
            weight = None
            art = str(p.get("supplier_article") or "").strip()
            if art:
                weight = weights.get(f"offer:{art}") or weights.get(
                    f"offer:{art.casefold()}"
                )
            if weight is None:
                oz = str(p.get("ozon_sku") or "").strip()
                if oz:
                    weight = (
                        weights.get(f"sku:{oz}")
                        or weights.get(f"offer:{oz}")
                        or weights.get(f"offer:{oz.casefold()}")
                    )
            if weight is None:
                continue
            found.setdefault(pid, []).append(
                {"platform": "ozon", "weight_kg": weight, "source_name": name}
            )

    out: dict[int, dict[str, Any]] = {}
    for pid, sources in found.items():
        preferred = None
        for platform in ("wb", "ozon"):
            hit = next((s for s in sources if s.get("platform") == platform), None)
            if hit:
                preferred = hit
                break
        if not preferred:
            preferred = sources[0]
        out[pid] = {
            "weight_kg": preferred["weight_kg"],
            "platform": preferred["platform"],
            "source_name": preferred.get("source_name") or "",
            "sources": sources,
        }
    return out


def build_weight_fill_preview(*, repository: Any, user_id: int) -> list[dict[str, Any]]:
    products = repository.list_product_photos(user_id=user_id)
    market = collect_marketplace_weights(repository=repository, user_id=user_id)
    out: list[dict[str, Any]] = []
    for p in products:
        pid = int(p.get("id") or 0)
        if pid <= 0:
            continue
        current = _as_positive_float(p.get("weight_kg"))
        hit = market.get(pid) or {}
        proposed = _as_positive_float(hit.get("weight_kg"))
        has_market = proposed is not None
        can_fill = has_market and current is None
        sources = list(hit.get("sources") or [])
        conflict = False
        if len(sources) >= 2:
            vals = {
                round(float(s["weight_kg"]), 3)
                for s in sources
                if s.get("weight_kg") is not None
            }
            conflict = len(vals) > 1
        out.append(
            {
                "id": pid,
                "name": str(p.get("name") or ""),
                "supplier_article": str(p.get("supplier_article") or ""),
                "wb_nmid": str(p.get("wb_nmid") or ""),
                "ozon_sku": str(p.get("ozon_sku") or ""),
                "current_weight_kg": current,
                "proposed_weight_kg": proposed if can_fill else None,
                "market_weight_kg": proposed,
                "platform": str(hit.get("platform") or "") if has_market else "",
                "source_name": str(hit.get("source_name") or "") if has_market else "",
                "sources": sources,
                "has_market": has_market,
                "has_new": can_fill,
                "conflict": conflict,
            }
        )
    return out


def fill_product_weights_from_marketplace(
    *,
    repository: Any,
    user_id: int,
    product_ids: list[int],
) -> dict[str, Any]:
    wanted = {int(x) for x in product_ids if int(x) > 0}
    if not wanted:
        return {"updated": 0, "items": []}
    preview = {
        int(item["id"]): item
        for item in build_weight_fill_preview(repository=repository, user_id=user_id)
    }
    updated_items: list[dict[str, Any]] = []
    for pid in sorted(wanted):
        item = preview.get(pid)
        if not item or not item.get("has_new"):
            continue
        weight = _as_positive_float(item.get("proposed_weight_kg"))
        if weight is None:
            continue
        if repository.set_product_weight_kg(
            user_id=user_id, product_id=pid, weight_kg=weight
        ):
            updated_items.append(
                {
                    "id": pid,
                    "name": item.get("name") or "",
                    "weight_kg": weight,
                    "platform": item.get("platform") or "",
                }
            )
    return {"updated": len(updated_items), "items": updated_items}
