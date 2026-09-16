"""Live KIZ scan must not add a second code when quantity slots are full."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    start = JS.find(f"function {name}")
    assert start > 0, name
    # Next top-level-ish function after this one (2-space indent).
    nxt = JS.find("\n  function ", start + 10)
    assert nxt > start
    return JS[start:nxt]


def test_mark_scan_blocks_when_quantity_slots_filled() -> None:
    body = _fn("processOzonFbsKizMarkScan")
    assert "_ozonFbsKizRowExistingCodes(row)" in body
    assert "existing.length >= qty" in body
    assert "Чтобы заменить — сначала очистите текущий" in body
    # Still places into empty slots / may push only when under qty.
    assert "row.kiz_codes.push(mark)" in body


def test_add_kiz_button_respects_quantity_cap() -> None:
    body = _fn("addOzonFbsKizCode")
    assert "row.kiz_codes.length >= qty" in body
    assert "больше добавлять нельзя" in body


def test_import_path_still_has_qty_guard() -> None:
    # Regression: paste/import already capped — keep both paths aligned.
    assert "if (filledN >= qty)" in JS


def test_filled_slot_reject_replace_guard() -> None:
    """Focused cell / COM must not silently overwrite a committed KIZ."""
    reject = _fn("_ozonFbsKizRejectReplaceFilledSlot")
    assert "dataset.committedMark" in reject
    assert "Чтобы заменить — сначала очистите текущий" in reject
    sync = _fn("_ozonFbsKizSyncCommittedMark")
    assert "committedMark" in sync
    blur = _fn("onOzonFbsKizCodeBlur")
    assert "_ozonFbsKizRejectReplaceFilledSlot" in blur
    key = _fn("onOzonFbsKizCodeKey")
    assert "_ozonFbsKizRejectReplaceFilledSlot" in key
    com = _fn("_ozonFbsComTryFillFocusedRowInput")
    assert "_ozonFbsKizRejectReplaceFilledSlot" in com
    # Clear (×) unlocks replace by resetting committed mark.
    on_input = _fn("onOzonFbsKizCodeInput")
    assert '_ozonFbsKizSyncCommittedMark(input, "")' in on_input


def test_cancelled_blocked_on_live_scan() -> None:
    sticker = _fn("processOzonFbsKizStickerScan")
    assert "_ozonFbsRowIsCancelled(found.row)" in sticker
    assert "КИЗ менять нельзя" in sticker
    mark = _fn("processOzonFbsKizMarkScan")
    assert "_ozonFbsRowIsCancelled(row)" in mark
    assert "КИЗ менять нельзя" in mark


def test_collect_keeps_committed_during_illegal_replace() -> None:
    body = _fn("_ozonFbsKizCollectFromDom")
    assert "dataset.committedMark" in body
    assert "next = committed" in body
    reject = _fn("_ozonFbsKizRejectReplaceFilledSlot")
    assert "_ozonFbsKizIndexClearMark(next)" in reject
    assert "_ozonFbsKizIndexSetMark(prev, pn)" in reject


def test_filters_do_not_scope_dup_checks() -> None:
    """Filters only slice for render; FindExistingMark / markIndex cover all rows."""
    find = _fn("_ozonFbsKizFindExistingMark")
    assert "ozonFbsKizState.markIndex" in find or "ozonFbsKizState.rows" in find
    render = _fn("renderOzonFbsKizTable")
    assert "ozonFbsKizState.rows =" not in render
    collect = _fn("_ozonFbsKizCollectFromDom")
    assert "row.kiz_codes[idx] = next" in collect


def test_cache_bump() -> None:
    assert "ozon_fbs.js?v=172" in HTML
