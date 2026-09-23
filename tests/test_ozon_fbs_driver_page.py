"""Ozon FBS standalone «Для водителя» page."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from review_processor.ozon_fbs_supplies import (
    DRIVER_PAGE_CONTAINER_STATUSES,
    list_driver_page_cargo_places,
    list_driver_page_vehicle_plates,
    list_supplies_for_driver_vehicle,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_static"
TEMPLATES = ROOT / "web_templates"
WEB = ROOT / "review_processor" / "web.py"
APP_HTML = TEMPLATES / "app.html"


def test_driver_page_assets_exist() -> None:
    assert (STATIC / "ozon_fbs_driver.css").is_file()
    assert (STATIC / "ozon_fbs_driver.js").is_file()
    assert (TEMPLATES / "ozon_fbs_driver.html").is_file()


def test_driver_page_html_boot_and_assets() -> None:
    html = (TEMPLATES / "ozon_fbs_driver.html").read_text(encoding="utf-8")
    assert "Для водителя" in html
    assert "OFD_BOOT" in html
    assert "CAN_VIEW_OZON_FBS_DRIVER" in html
    assert "/static/ozon_fbs_driver.js?v=11" in html
    assert "/static/ozon_fbs_driver.css?v=8" in html
    assert "PAGE_MODE" in html
    assert "PAGE_TOKEN" in html
    assert "page_mode" in html
    assert "page_token" in html


def test_driver_button_next_to_tsd() -> None:
    html = APP_HTML.read_text(encoding="utf-8")
    tsd = html.index('id="ozonFbsTsdBtn"')
    driver = html.index('id="ozonFbsDriverPageBtn"')
    assert tsd < driver
    assert "Для водителя" in html
    assert "openOzonFbsDriverPage()" in html
    assert "ozon_fbs.js?v=197" in html
    assert "app.js?v=697" in html


def test_web_routes_and_builder() -> None:
    src = WEB.read_text(encoding="utf-8")
    assert "def build_ozon_fbs_driver_html" in src
    assert '"/ozon-fbs/driver"' in src
    assert '"/api/ozon-fbs/driver/vehicles"' in src
    assert '"/api/ozon-fbs/driver/cargo-places"' in src
    assert "list_driver_page_vehicle_plates" in src
    assert "list_driver_page_cargo_places" in src
    assert "/ozon-fbs/driver/p/{page_token}" in src
    assert "/api/ozon-fbs/driver/p/{page_token}/unlock" in src
    assert "/api/ozon-fbs/driver/public-link" in src


def test_driver_page_js_calls_apis() -> None:
    js = (STATIC / "ozon_fbs_driver.js").read_text(encoding="utf-8")
    assert "/api/ozon-fbs/driver/vehicles" in js
    assert "/api/ozon-fbs/driver/cargo-places" in js
    assert "ofdVehicleSelect" in js
    assert "page_mode" in js
    assert "isPinMode" in js
    assert "/unlock" in js
    assert "acceptance_in_progress" in js
    assert "formed" in js
    assert "finished" in js
    assert "ofdStatusBanner" in js
    assert "palletBannerKind" in js
    assert "ofd-banner-warn" in js
    assert "ofd-banner-ok" in js
    assert "ofdRefreshBtn" in js
    assert "Ваши паллеты приняты на СЦ, все хорошо" in js
    assert "обратитесь на склад" in js
    assert "для повторного сканирования" in js
    assert "После выбора подгрузятся грузоместа" not in js
    assert "Нет грузомест Ozon" not in js
    assert "box.hidden = true" in js
    assert "sortCargoItems" in js
    assert "STATUS_SORT_ORDER" in js
    assert "groupItemsBySupply" in js
    assert "supplyTone" in js
    assert "supplyDateMs" in js
    assert "supply_created_at" in js
    assert "ofd-supply" in js
    assert "ofd-supplies" in js
    assert "expandedSupplies" in js
    assert "Поставки" in js
    assert "is-ok" in js
    assert "is-warn" in js
    assert "db - da" in js
    assert "!list.length) return \"ok\"" in js or "if (!list.length) return \"ok\"" in js
    assert "softRefresh" in js
    assert "Обновление…" in js
    assert "ofd-spinner" in js
    assert "{ soft: true }" in js or "soft: true" in js
    css = (STATIC / "ozon_fbs_driver.css").read_text(encoding="utf-8")
    assert "ofd-banner-warn" in css
    assert "ofd-banner-ok" in css
    assert "ofd-btn-refresh" in css
    assert "ofd-spinner" in css
    assert "ofd-spin" in css
    assert "ofd-supply" in css
    assert "ofd-supply.is-ok" in css
    assert "ofd-supply.is-warn" in css
    assert "#f0fdf4" in css
    assert "#fff1f2" in css
    assert "is-refreshing" in css
    assert "#fee2e2" in css


def test_driver_page_statuses_include_finished() -> None:
    from review_processor.ozon_fbs_supplies import (
        DRIVER_PAGE_STATUS_SORT_ORDER,
        driver_page_status_sort_key,
    )

    assert DRIVER_PAGE_CONTAINER_STATUSES == frozenset(
        {"formed", "acceptance_in_progress", "finished"}
    )
    assert "finished" in DRIVER_PAGE_CONTAINER_STATUSES
    assert DRIVER_PAGE_STATUS_SORT_ORDER["formed"] < DRIVER_PAGE_STATUS_SORT_ORDER[
        "acceptance_in_progress"
    ]
    assert (
        DRIVER_PAGE_STATUS_SORT_ORDER["acceptance_in_progress"]
        < DRIVER_PAGE_STATUS_SORT_ORDER["finished"]
    )
    assert driver_page_status_sort_key("formed") == 0
    assert driver_page_status_sort_key("acceptance_in_progress") == 1
    assert driver_page_status_sort_key("finished") == 2
    supplies_src = (
        ROOT / "review_processor" / "ozon_fbs_supplies.py"
    ).read_text(encoding="utf-8")
    assert "_list_containers_cached" in supplies_src
    assert "include_sc_accepted=True" in supplies_src


def test_list_driver_page_vehicle_plates_unique() -> None:
    repo = MagicMock()
    repo.list_supply_drivers.return_value = [
        {
            "id": 1,
            "full_name": "Иванов",
            "vehicles_json": '[{"number":"А123ВС777"},{"number":"В849ВО37"}]',
        },
        {
            "id": 2,
            "full_name": "Петров",
            "vehicles_json": '[{"number":"а123вс777"},{"number":"С456ОР199"}]',
        },
    ]
    plates = list_driver_page_vehicle_plates(repo, user_id=1)
    norms = {p["number"].casefold().replace(" ", "") for p in plates}
    assert "а123вс777" in norms
    assert len([p for p in plates if p["number"].casefold().replace(" ", "") == "а123вс777"]) == 1
    assert any(p["number"] == "В849ВО37" for p in plates)
    assert any(p["number"] == "С456ОР199" for p in plates)


def test_list_supplies_for_driver_vehicle_filters_plate(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.ensure_ozon_fbs_supply_schema",
        lambda repo: None,
    )

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return self

        def fetchall(self):
            return [
                {
                    "source_id": 10,
                    "supply_id": "OZ-1",
                    "driver_id": 1,
                    "driver_name": "Иванов",
                    "vehicle_number": "А123ВС777",
                },
                {
                    "source_id": 10,
                    "supply_id": "OZ-2",
                    "driver_id": 1,
                    "driver_name": "Иванов",
                    "vehicle_number": "В849ВО37",
                },
            ]

    repo = MagicMock()
    repo._connect.return_value = _Conn()
    repo._sql.side_effect = lambda s: s
    repo._row_to_dict.side_effect = lambda row: row
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.get_supply",
        lambda repo, user_id, source_id, supply_id: {
            "name": f"Supply {supply_id}",
            "warehouse_name": "WH",
        },
    )
    rows = list_supplies_for_driver_vehicle(
        repo, user_id=1, vehicle_number="а 123 вс 777"
    )
    assert len(rows) == 1
    assert rows[0]["supply_id"] == "OZ-1"


def test_list_driver_page_cargo_places_filters_statuses(monkeypatch) -> None:
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.list_supplies_for_driver_vehicle",
        lambda *a, **k: [
            {
                "source_id": 5,
                "supply_id": "OZ-1",
                "supply_name": "Поставка 1",
                "warehouse_name": "Склад",
                "driver_name": "Иванов",
                "vehicle_number": "А123ВС777",
            }
        ],
    )

    listed = {
        "ok": True,
        "items": [
            {
                "container_id": 13,
                "container_number": 3,
                "status": "finished",
                "status_label": "Завершено на СЦ",
                "order_count": 2,
            },
            {
                "container_id": 12,
                "container_number": 2,
                "status": "acceptance_in_progress",
                "status_label": "Принято на СЦ",
                "cargo_type_label": "Короб",
                "sort_type_label": "Сортируемое",
                "order_count": 1,
            },
            {
                "container_id": 11,
                "container_number": 1,
                "status": "formed",
                "status_label": "Сформировано",
                "cargo_type_label": "Паллета",
                "sort_type_label": "Сортируемое",
                "order_count": 3,
            },
            {
                "container_id": 14,
                "container_number": 4,
                "status": "new",
                "status_label": "Новое",
                "order_count": 0,
            },
        ],
    }

    import review_processor.ozon_fbs_containers as oz_ct

    def _resolve(*a, **k):
        return 99, "Склад"

    seen_lookback: list[int] = []

    def _list(*a, **k):
        assert k.get("include_sc_accepted") is True
        seen_lookback.append(int(k.get("lookback_days") or 0))
        return listed

    def _enrich(*a, **k):
        assert k.get("only_this_supply") is True
        items = [x for x in listed["items"] if x["container_id"] != 14]
        return {"ok": True, "items": items}

    monkeypatch.setattr(oz_ct, "resolve_supply_warehouse_id", _resolve)
    monkeypatch.setattr(oz_ct, "list_containers", _list)
    monkeypatch.setattr(oz_ct, "enrich_containers_for_supply_modal", _enrich)
    monkeypatch.setattr(oz_ct, "status_label", lambda st: st)

    repo = MagicMock()
    repo.get_ozon_fbs_sync_settings.return_value = {"lookback_days": 2}
    out = list_driver_page_cargo_places(
        repo,
        user_id=1,
        vehicle_number="А123ВС777",
        client_for_source=lambda sid: object(),
    )
    ids = [x["container_id"] for x in out["items"]]
    # Sort: formed → acceptance_in_progress → finished
    assert ids == [11, 12, 13]
    assert [x["status"] for x in out["items"]] == [
        "formed",
        "acceptance_in_progress",
        "finished",
    ]
    assert out["total"] == 3
    assert out["lookback_days"] == 2
    assert seen_lookback == [2]
    assert all(x.get("supply_created_at") == "" or "supply_created_at" in x for x in out["items"])
    assert all(x["status"] in DRIVER_PAGE_CONTAINER_STATUSES for x in out["items"])
    assert "new" not in {x["status"] for x in out["items"]}


def test_driver_page_cargo_places_sort_by_supply_date(monkeypatch) -> None:
    """Nearest supply dates first; inside supply: formed → SC → finished."""
    monkeypatch.setattr(
        "review_processor.ozon_fbs_supplies.list_supplies_for_driver_vehicle",
        lambda *a, **k: [
            {
                "source_id": 5,
                "supply_id": "OZ-OLD",
                "supply_name": "Старая",
                "warehouse_name": "Склад",
                "supply_created_at": "2026-09-10T10:00:00+00:00",
                "driver_name": "Иванов",
                "vehicle_number": "А123ВС777",
            },
            {
                "source_id": 5,
                "supply_id": "OZ-NEW",
                "supply_name": "Ближняя",
                "warehouse_name": "Склад",
                "supply_created_at": "2026-09-17T08:00:00+00:00",
                "driver_name": "Иванов",
                "vehicle_number": "А123ВС777",
            },
        ],
    )

    import review_processor.ozon_fbs_containers as oz_ct

    def _resolve(*a, **k):
        return 99, "Склад"

    def _list(*a, **k):
        return {"ok": True, "items": []}

    def _enrich(repo, *, user_id, source_id, supply_id, listed, only_this_supply):
        if supply_id == "OZ-OLD":
            return {
                "ok": True,
                "items": [
                    {
                        "container_id": 21,
                        "container_number": 1,
                        "status": "finished",
                        "status_label": "Завершено",
                        "order_count": 1,
                    },
                    {
                        "container_id": 22,
                        "container_number": 2,
                        "status": "formed",
                        "status_label": "Сформировано",
                        "order_count": 1,
                    },
                ],
            }
        return {
            "ok": True,
            "items": [
                {
                    "container_id": 11,
                    "container_number": 1,
                    "status": "acceptance_in_progress",
                    "status_label": "Принято на СЦ",
                    "order_count": 1,
                },
                {
                    "container_id": 12,
                    "container_number": 2,
                    "status": "formed",
                    "status_label": "Сформировано",
                    "order_count": 1,
                },
            ],
        }

    monkeypatch.setattr(oz_ct, "resolve_supply_warehouse_id", _resolve)
    monkeypatch.setattr(oz_ct, "list_containers", _list)
    monkeypatch.setattr(oz_ct, "enrich_containers_for_supply_modal", _enrich)
    monkeypatch.setattr(oz_ct, "status_label", lambda st: st)

    repo = MagicMock()
    repo.get_ozon_fbs_sync_settings.return_value = {"lookback_days": 2}
    out = list_driver_page_cargo_places(
        repo,
        user_id=1,
        vehicle_number="А123ВС777",
        client_for_source=lambda sid: object(),
    )
    # Flat list: nearest supply first, then status order inside.
    assert [x["supply_id"] for x in out["items"]] == [
        "OZ-NEW",
        "OZ-NEW",
        "OZ-OLD",
        "OZ-OLD",
    ]
    assert [x["status"] for x in out["items"] if x["supply_id"] == "OZ-NEW"] == [
        "formed",
        "acceptance_in_progress",
    ]
    assert [x["status"] for x in out["items"] if x["supply_id"] == "OZ-OLD"] == [
        "formed",
        "finished",
    ]
    assert out["supplies"][0]["supply_id"] == "OZ-NEW"
    assert out["items"][0]["supply_created_at"].startswith("2026-09-17")


def test_driver_page_uses_sync_settings_lookback() -> None:
    from review_processor.ozon_fbs_supplies import _driver_page_container_lookback_days

    src = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")
    block = src[
        src.find("def list_driver_page_cargo_places") : src.find(
            "def list_driver_page_cargo_places"
        )
        + 3500
    ]
    assert "lookback_days=lookback_days" in block
    assert "_driver_page_container_lookback_days" in block

    repo = MagicMock()
    repo.get_ozon_fbs_sync_settings.return_value = {"lookback_days": 2}
    assert _driver_page_container_lookback_days(repo, user_id=1) == 2
    repo.get_ozon_fbs_sync_settings.side_effect = RuntimeError("missing")
    assert _driver_page_container_lookback_days(repo, user_id=1) == 3
