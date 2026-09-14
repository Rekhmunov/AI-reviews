"""Pin: after KIZ/pick scan, jump to row instantly (no smooth scroll)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _scroll_snippet(js: str, anchor: str) -> str:
    i = js.find(anchor)
    assert i >= 0, f"anchor not found: {anchor}"
    return js[i : i + 280]


def test_wb_and_ozon_kiz_pick_scroll_is_instant() -> None:
    app_js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    ozon_js = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")

    wb_kiz = _scroll_snippet(app_js, '#wbFbsKizTbody tr[data-order-id="${oid}"]')
    wb_pick = _scroll_snippet(app_js, '#wbFbsPickTbody tr[data-order-id="${oid}"]')
    oz_kiz = _scroll_snippet(ozon_js, '#ozonFbsKizTbody tr[data-posting="${pn}"]')
    oz_pick = _scroll_snippet(ozon_js, '#ozonFbsPickTbody tr[data-posting="${pn}"]')

    for name, snip in (
        ("wb_kiz", wb_kiz),
        ("wb_pick", wb_pick),
        ("oz_kiz", oz_kiz),
        ("oz_pick", oz_pick),
    ):
        assert "scrollIntoView({ block: \"nearest\" })" in snip, name
        assert "behavior" not in snip, name
        assert "smooth" not in snip, name

    assert "app.js?v=628" in html
    assert "ozon_fbs.js?v=157" in html
