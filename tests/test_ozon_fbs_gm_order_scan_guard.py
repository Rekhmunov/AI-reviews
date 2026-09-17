"""Ozon FBS: block order sticker scan without active GM when supply already has ≥1 filled GM."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OZON_JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
BIND = (ROOT / "web_static" / "ozon_fbs_container_bind.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_guard_helpers_exported() -> None:
    assert "function supplyHasFilledCargoPlace" in BIND
    assert "function guardOrderScanRequiresActiveGm" in BIND
    assert "bound_to_open_supply === true" in BIND
    assert 'order_count || 0) > 0' in BIND
    assert "rowsHaveContainerBinds" in BIND
    assert "Вы пытаетесь просканировать заказ без грузоместа." in BIND
    assert 'title: "Нет грузоместа"' in BIND
    assert "window._ozonFbsContainerSupplyHasFilledGm" in BIND
    assert "window._ozonFbsContainerGuardOrderScanRequiresActiveGm" in BIND


def test_sticker_processors_call_guard_after_container_divert() -> None:
    for fn, mode in (
        ("async function processOzonFbsKizStickerScan", "kiz"),
        ("async function processOzonFbsPickStickerScan", "pick"),
    ):
        start = OZON_JS.find(fn)
        assert start >= 0, fn
        # Next major sibling function boundary (rough window).
        chunk = OZON_JS[start : start + 2500]
        divert = chunk.find(f'_ozonFbsContainerIsScanMode("{mode}")')
        guard = chunk.find("_ozonFbsContainerGuardOrderScanRequiresActiveGm")
        assert divert >= 0, f"{mode}: container divert missing"
        assert guard >= 0, f"{mode}: GM guard missing"
        assert divert < guard, f"{mode}: guard must run after container-scan divert"


def test_mark_sku_not_gated_by_gm_guard() -> None:
    # Mark/SKU require pending posting; maybeBind already no-ops without activeId.
    mark = OZON_JS[
        OZON_JS.find("function processOzonFbsKizMarkScan") : OZON_JS.find(
            "function processOzonFbsKizMarkScan"
        )
        + 900
    ]
    sku = OZON_JS[
        OZON_JS.find("function processOzonFbsPickSkuScan") : OZON_JS.find(
            "function processOzonFbsPickSkuScan"
        )
        + 900
    ]
    assert "_ozonFbsContainerGuardOrderScanRequiresActiveGm" not in mark
    assert "_ozonFbsContainerGuardOrderScanRequiresActiveGm" not in sku


def test_ack_modal_no_scrollbar_css() -> None:
    assert "#fbsStickerNotFoundModal > .modal-card.wb-fbs-kiz-ru-layout-modal" in CSS
    assert "overflow: visible !important" in CSS
    assert "max-height: none !important" in CSS
    # Compact card itself opts out of global .modal-card scroll.
    block = CSS[
        CSS.find(".wb-fbs-kiz-ru-layout-modal {") : CSS.find(".wb-fbs-kiz-ru-layout-modal {") + 280
    ]
    assert "max-height: none" in block
    assert "overflow: visible" in block


def test_asset_cache_bumped() -> None:
    assert "ozon_fbs.js?v=182" in HTML
    assert "ozon_fbs_container_bind.js?v=36" in HTML
    assert "style.css?v=388" in HTML
