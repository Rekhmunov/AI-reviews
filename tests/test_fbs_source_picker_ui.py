"""FBS source picker opens flush under the button (no native select gap)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fbs_source_picker_markup_and_flush_menu() -> None:
    html = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    css = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
    js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert 'id="wbFbsSourcePicker"' in html
    assert 'id="ozonFbsSourcePicker"' in html
    assert "toggleFbsSourcePicker('wbFbsSource'" in html
    assert "toggleFbsSourcePicker('ozonFbsSource'" in html
    assert 'id="wbFbsSourceSelect"' in html
    assert 'id="ozonFbsSourceSelect"' in html

    menu_css = css[css.index(".fbs-source-picker-menu") : css.index(".fbs-source-picker-menu") + 400]
    assert "top: 100%" in menu_css
    assert "position: absolute" in menu_css
    # No intentional air gap under the trigger.
    assert "calc(100%" not in menu_css

    assert "function toggleFbsSourcePicker" in js
    assert 'syncFbsSourcePicker("wbFbsSource")' in js
    oz = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
    assert 'syncFbsSourcePicker("ozonFbsSource")' in oz
