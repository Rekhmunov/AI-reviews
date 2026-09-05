"""UI: Supplies section + modals mobile sheet polish."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_supply_mobile_css_block_exists() -> None:
    assert "Supplies (Поставки): mobile shell + modals" in STYLE
    assert "@media (max-width: 720px)" in STYLE
    assert "100dvh" in STYLE
    assert "env(safe-area-inset-bottom)" in STYLE
    assert "#section-supplies-wb-fbs #wbFbsOrdersTable" in STYLE
    assert "#wbFbsSupplyDetailModal" in STYLE
    assert "#wbFbsCollectMgtModal" in STYLE
    assert "#supplyDetailsModal" in STYLE
    assert "#supplyStockReceiptModal" in STYLE
    assert "min-height: 44px" in STYLE


def test_receipt_scan_autofocus_skips_touch() -> None:
    assert '(hover: hover) and (pointer: fine)' in APP_JS
    assert "setTimeout(() => scanEl?.focus(), 40)" in APP_JS


def test_style_cache_bump() -> None:
    assert "style.css?v=304" in APP_HTML
    assert "app.js?v=548" in APP_HTML
