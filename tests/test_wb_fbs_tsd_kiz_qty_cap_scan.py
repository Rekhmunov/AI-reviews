"""TSD KIZ scan must not add a second code when quantity slots are full (WB + Ozon)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "wb_fbs_tsd.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "wb_fbs_tsd.html").read_text(encoding="utf-8")


def test_row_kiz_qty_defaults_to_one() -> None:
    assert "function rowKizQty(" in JS
    assert "Math.max(1, Number(row?.quantity) || 1)" in JS


def test_scan_blocks_when_quantity_slots_filled() -> None:
    assert "existing.length >= qty" in JS
    assert "Чтобы заменить — сначала очистите текущий" in JS
    # Still may push when under qty (empty slot fill path kept).
    assert "row.kiz_codes.push(mark)" in JS


def test_scan_ui_does_not_invite_extra_kiz_when_full() -> None:
    assert "КИЗ уже записан" in JS
    assert "чтобы заменить, сначала очистите текущий" in JS
    # Old inviting copy must be gone.
    assert "новый код добавится к заказу" not in JS


def test_dup_check_uses_full_kiz_rows_not_filtered_slice() -> None:
    """Filters only affect display; cross-order dup walks state.kizRows."""
    assert "state.kizRows.find(" in JS
    assert "function applyOrderFilters(" in JS
    assert "state.kizRows = applyOrderFilters" not in JS


def test_cache_bump() -> None:
    assert "wb_fbs_tsd.js?v=96" in HTML
