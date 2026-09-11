"""UI/API contracts: product weight_kg + warehouse FBS sources + TN picker."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")


def test_product_weight_field_and_api() -> None:
    assert 'id="productFormWeightKg"' in HTML
    assert "Вес, кг" in HTML
    assert "productFormWeightKg" in JS
    assert 'append("weight_kg"' in JS
    assert "weight_kg DOUBLE PRECISION" in REPO
    assert "def _parse_product_weight_kg" in WEB
    assert "weight_kg: str = Form" in WEB


def test_warehouse_fbs_sources_binding() -> None:
    assert 'id="newWarehouseFbsSources"' in HTML
    assert "fbs_sources_json" in REPO
    assert "def _normalize_warehouse_fbs_sources" in REPO
    assert "fbs_sources:" in WEB
    assert "_renderWarehouseFbsSourcesChecklist" in JS
    assert "fbs_sources:" in JS


def test_ttn_fbs_supply_picker_and_endpoints() -> None:
    assert 'id="ttnFbsSupplyField"' in HTML
    assert "ttnCreateFbsSupplyWrap" in HTML
    assert "_ttnRefreshFbsSupplyField" in JS
    assert "/api/supply-ttn/fbs-supplies" in WEB
    assert "/api/supply-ttn/fbs-cargo" in WEB
    assert "fbs_platform" in REPO
    assert "fbs_source_id" in REPO
    assert "fbs_supply_id" in REPO
    assert "app.js?v=607" in HTML
    assert "style.css?v=353" in HTML
