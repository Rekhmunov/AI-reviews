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


def test_cache_bump() -> None:
    assert "ozon_fbs.js?v=165" in HTML
