"""Supply-detail search must match new Ozon ii… scanit labels (like KIZ/Pick)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"


def _fn_src(name: str, *, until: str) -> str:
    js = JS.read_text(encoding="utf-8")
    start = js.find(f"function {name}")
    end = js.find(f"function {until}", start + 1)
    assert start >= 0, name
    assert end > start, until
    return js[start:end]


def test_supply_detail_search_includes_scanit() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "function _ozonFbsSupplyDetailRowMatchesSearch" in js
    helper = _fn_src(
        "_ozonFbsSupplyDetailRowMatchesSearch",
        until="_ozonFbsResolvedStickerFields",
    )
    assert "fields.scanit" in helper
    assert "sticker_scanit" in helper or "fields.scanit" in helper
    assert "_ozonFbsSearchMatchesPostingOrSupply" in helper

    # Filter in renderSupplyDetail uses the shared matcher (not a local hay without scanit).
    render_start = js.find("const searchQ = String(document.getElementById(\"ozonFbsSupplyDetailSearchFilter\")")
    assert render_start >= 0
    render_chunk = js[render_start : render_start + 500]
    assert "_ozonFbsSupplyDetailRowMatchesSearch" in render_chunk
    assert "o.posting_number, o.offer_id, o.sku, o.product_name, o.warehouse_label" not in render_chunk


def test_kiz_and_pick_still_search_scanit() -> None:
    kiz = _fn_src("_ozonFbsKizRowMatchesSearch", until="_ozonFbsPickRowMatchesSearch")
    pick = _fn_src("_ozonFbsPickRowMatchesSearch", until="_ozonFbsKizUpdateFilterCounts")
    assert "sticker_scanit" in kiz
    assert "sticker_scanit" in pick
