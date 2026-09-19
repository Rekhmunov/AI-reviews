"""FBS supply row tones: pale-red (GM formed) / green (accepted + TTN)."""

from __future__ import annotations

from pathlib import Path

from review_processor.ozon_fbs_supplies import resolve_fbs_supply_row_tone

ROOT = Path(__file__).resolve().parents[1]
OZ = ROOT / "review_processor" / "ozon_fbs_supplies.py"
WB = ROOT / "review_processor" / "wb_fbs.py"
WEB = ROOT / "review_processor" / "web.py"
OZ_JS = ROOT / "web_static" / "ozon_fbs.js"
APP_JS = ROOT / "web_static" / "app.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"


def test_resolve_row_tone_priority() -> None:
    assert resolve_fbs_supply_row_tone(gm_statuses=["formed"], ttn_id=0) == "warn"
    assert resolve_fbs_supply_row_tone(gm_statuses=["formed"], ttn_id=9) == "warn"
    assert (
        resolve_fbs_supply_row_tone(
            gm_statuses=["formed", "acceptance_in_progress"], ttn_id=9
        )
        == "warn"
    )
    assert (
        resolve_fbs_supply_row_tone(
            gm_statuses=["acceptance_in_progress"], ttn_id=0
        )
        == ""
    )
    assert (
        resolve_fbs_supply_row_tone(gm_statuses=["finished"], ttn_id=0) == ""
    )
    assert (
        resolve_fbs_supply_row_tone(
            gm_statuses=["acceptance_in_progress", "finished"], ttn_id=5
        )
        == "ok"
    )
    assert resolve_fbs_supply_row_tone(gm_statuses=[], ttn_id=5) == ""


def test_ozon_enrich_skips_unknown_gm_as_formed() -> None:
    """Missing live GM status must not invent «formed» (false pale-red)."""
    oz = OZ.read_text(encoding="utf-8")
    enrich = oz.split("def enrich_ozon_supply_items_row_tones", 1)[1].split(
        "\ndef list_awaiting_deliver_supplies", 1
    )[0]
    assert "treat as formed" not in enrich
    assert "gm_statuses.append(\"formed\")" not in enrich
    assert "Only known live statuses" in enrich
    assert "if st:" in enrich
    assert "gm_statuses.append(st)" in enrich


def test_ozon_backend_enriches_tones() -> None:
    oz = OZ.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    assert "def resolve_fbs_supply_row_tone" in oz
    assert "def enrich_ozon_supply_items_row_tones" in oz
    assert "enrich_ozon_supply_items_row_tones" in oz.split(
        "def _list_supplies_tab_response", 1
    )[1].split("def resolve_fbs_supply_row_tone", 1)[0]
    assert 'tab in {oz.TAB_AWAITING_DELIVER, oz.TAB_DELIVERING}' in oz
    api = web.split("def ozon_fbs_list_supplies", 1)[1].split("\n    @app.", 1)[0]
    assert "OzonFbsClient" in api
    assert "client=client" in api


def test_wb_delivery_row_tone_from_boxes_and_scan() -> None:
    wb = WB.read_text(encoding="utf-8")
    block = wb.split("if tab_key == TAB_DELIVERY and items:", 1)[1].split(
        "\n    return {", 1
    )[0]
    assert "resolve_fbs_supply_row_tone" in block
    assert "boxes_count" in block
    assert "scan_dt" in block
    assert 'row_tone' in block


def test_ui_row_classes_and_cache_bump() -> None:
    oz_js = OZ_JS.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    assert "fbs-supply-row-warn" in oz_js
    assert "fbs-supply-row-ok" in oz_js
    assert "row_tone" in oz_js
    assert "fbs-supply-row-warn" in app_js
    assert "fbs-supply-row-ok" in app_js
    assert ".fbs-supply-row-warn" in css
    assert ".fbs-supply-row-ok" in css
    assert "#fff1f2" in css
    assert "#f0fdf4" in css
    assert "ozon_fbs.js?v=186" in html
    assert "app.js?v=678" in html
    assert "style.css?v=402" in html
