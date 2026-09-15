"""WB FBS «Товары с КИЗ»: qty cap + no silent overwrite of filled slot."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    start = JS.find(f"function {name}")
    assert start > 0, name
    nxt = JS.find("\nfunction ", start + 10)
    assert nxt > start
    return JS[start:nxt]


def test_mark_scan_blocks_when_quantity_slots_filled() -> None:
    body = _fn("processWbFbsKizMarkScan")
    assert "_wbFbsKizNormalizeCodesList(row.kiz_codes)" in body
    assert "_wbFbsKizRowQty(row)" in body
    assert "existing.length >= qty" in body
    assert "Чтобы заменить — сначала очистите текущий" in body
    # Still places into empty slots / may push only when under qty.
    assert "row.kiz_codes.push(mark)" in body


def test_add_kiz_button_respects_quantity_cap() -> None:
    body = _fn("addWbFbsKizCode")
    assert "row.kiz_codes.length >= qty" in body
    assert "больше добавлять нельзя" in body


def test_wb_row_qty_defaults_to_one() -> None:
    """WB FBS: one order ≈ one unit when quantity is absent."""
    body = _fn("_wbFbsKizRowQty")
    assert "Number(row?.quantity)" in body
    assert "Math.max(1" in body


def test_filled_slot_reject_replace_guard() -> None:
    reject = _fn("_wbFbsKizRejectReplaceFilledSlot")
    assert "dataset.committedMark" in reject
    assert "Чтобы заменить — сначала очистите текущий" in reject
    assert "У заказа" in reject
    sync = _fn("_wbFbsKizSyncCommittedMark")
    assert "committedMark" in sync
    blur = _fn("onWbFbsKizCodeBlur")
    assert "_wbFbsKizRejectReplaceFilledSlot" in blur
    key = _fn("onWbFbsKizCodeKey")
    assert "_wbFbsKizRejectReplaceFilledSlot" in key
    com = _fn("_wbFbsComTryFillFocusedKizCodeInput")
    assert "_wbFbsKizRejectReplaceFilledSlot" in com
    on_input = _fn("onWbFbsKizCodeInput")
    assert '_wbFbsKizSyncCommittedMark(input, "")' in on_input


def test_cache_bump() -> None:
    assert "app.js?v=636" in HTML
