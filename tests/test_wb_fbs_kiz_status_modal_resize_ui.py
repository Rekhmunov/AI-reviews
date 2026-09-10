"""WB FBS KIZ/pick: status modal in WB section + resizable remembered columns."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web_templates" / "app.html"
JS = ROOT / "web_static" / "app.js"
CSS = ROOT / "web_static" / "style.css"


def _section_bounds(html: str, section_id: str) -> tuple[int, int]:
    start = html.find(f'id="{section_id}"')
    assert start > 0
    start = html.rfind("<section", 0, start)
    pos = start
    depth = 0
    while True:
        open_at = html.find("<section", pos)
        close_at = html.find("</section>", pos)
        assert close_at > 0
        if open_at >= 0 and open_at < close_at:
            depth += 1
            pos = open_at + 8
        else:
            depth -= 1
            pos = close_at + 10
            if depth == 0:
                return start, pos


def test_wb_fbs_order_status_modal_lives_in_wb_section() -> None:
    html = HTML.read_text(encoding="utf-8")
    wb = _section_bounds(html, "section-supplies-wb-fbs")
    oz = _section_bounds(html, "section-supplies-ozon-fbs")
    pos = html.find('id="wbFbsOrderStatusModal"')
    assert pos > 0
    assert wb[0] <= pos < wb[1]
    assert not (oz[0] <= pos < oz[1])
    assert "closeWbFbsOrderStatusModal()" in html
    assert "refreshWbFbsModalOrderStatus" in JS.read_text(encoding="utf-8")


def test_wb_fbs_kiz_pick_column_resize_wired() -> None:
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert 'id="wbFbsKizTable"' in html
    assert 'id="wbFbsKizColgroup"' in html
    assert 'id="wbFbsPickTable"' in html
    assert 'id="wbFbsPickColgroup"' in html
    assert html.count("col-resize-handle") >= 6
    assert "const wbFbsKizColResizer = createWbFbsModalColResizer" in js
    assert "const wbFbsPickColResizer = createWbFbsModalColResizer" in js
    assert 'storagePrefix: "wb_fbs_kiz_col_widths_v1"' in js
    assert 'storagePrefix: "wb_fbs_pick_col_widths_v1"' in js
    assert "wbFbsKizColResizer.init()" in js
    assert "wbFbsPickColResizer.init()" in js
    assert "app.js?v=583" in html
    assert "style.css?v=333" in html
