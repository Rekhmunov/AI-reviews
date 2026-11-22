"""Owner-only split menu: move to delivery without stock (Ozon + WB)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
OZ_JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
WB_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_ozon_split_menu_markup_and_owner_only() -> None:
    assert 'id="ozonFbsMoveDeliveringSplit"' in HTML
    assert 'id="ozonFbsMoveDeliveringMenuBtn"' in HTML
    assert 'id="ozonFbsMoveDeliveringMenu"' in HTML
    assert "moveOzonFbsSupplyToDeliveringNoStock()" in HTML
    assert "Перенести в доставляются без списания" in HTML
    assert "function _ozonFbsSyncMoveDeliveringOwnerMenu" in OZ_JS
    assert "function toggleOzonFbsMoveDeliveringMenu" in OZ_JS
    assert "function moveOzonFbsSupplyToDeliveringNoStock" in OZ_JS
    assert "_ozonFbsIsTenantOwner()" in OZ_JS
    assert "deduct_stock=${deductStock ? \"true\" : \"false\"}" in OZ_JS
    assert "Перенос без списания доступен только основному оператору" in OZ_JS


def test_wb_split_menu_markup_and_owner_only() -> None:
    assert 'id="wbFbsMoveDeliverySplit"' in HTML
    assert 'id="wbFbsMoveDeliveryMenuBtn"' in HTML
    assert 'id="wbFbsMoveDeliveryMenu"' in HTML
    assert "moveWbFbsSupplyToDeliveryNoStock()" in HTML
    assert "function _wbFbsSyncMoveDeliveryOwnerMenu" in WB_JS
    assert "function toggleWbFbsMoveDeliveryMenu" in WB_JS
    assert "function moveWbFbsSupplyToDeliveryNoStock" in WB_JS
    assert "isTenantOwner()" in WB_JS[
        WB_JS.index("function _wbFbsSyncMoveDeliveryOwnerMenu") :
        WB_JS.index("function _wbFbsSyncMoveDeliveryOwnerMenu") + 600
    ]
    assert "deduct_stock=${deductStock ? \"true\" : \"false\"}" in WB_JS
    assert "Перенос без списания доступен только основному оператору" in WB_JS


def test_api_owner_gate_for_deduct_stock_false() -> None:
    oz = WEB[
        WEB.index('@app.post("/api/ozon-fbs/supplies/{supply_id}/move-to-delivering")') :
        WEB.index('@app.post("/api/ozon-fbs/supplies/{supply_id}/move-to-awaiting-deliver")')
    ]
    wb = WEB[
        WEB.index('@app.post("/api/wb-fbs/supplies/{supply_id}/move-to-delivery")') :
        WEB.index('@app.get("/api/wb-fbs/supplies/{supply_id}/driver")')
    ]
    for block in (oz, wb):
        assert "deduct_stock: bool = True" in block
        assert "if not do_stock and not _is_wb_fbs_tenant_owner(user)" in block
        assert "Перенос без списания доступен только основному оператору" in block
        assert "deduct_stock=do_stock" in block


def test_split_styles_and_cache_bump() -> None:
    assert ".fbs-move-delivery-split" in CSS
    assert ".fbs-move-delivery-main" in CSS
    assert ".fbs-move-delivery-caret" in CSS
    assert "caret.style.display = show ? \"\" : \"none\"" in OZ_JS
    assert "caret.style.display = show ? \"\" : \"none\"" in WB_JS
    assert "ozonFbsMoveDeliveringMenuBtn" in OZ_JS[
        OZ_JS.index("const _OZON_FBS_DETAIL_ACTION_IDS") :
        OZ_JS.index("const _OZON_FBS_DETAIL_ACTION_IDS") + 800
    ]
    assert "ozon_fbs.js?v=230" in HTML
    assert "app.js?v=728" in HTML
    assert "style.css?v=448" in HTML
