"""Cancelled Ozon FBS KIZ rows keep input chrome (readonly), not plain text."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _render_block() -> str:
    start = JS.find("const canRemoveRow = !isCancelled && codes.length > 1;")
    end = JS.find("return `<tr class=\"wb-fbs-kiz-row", start)
    assert start > 0 and end > start
    return JS[start:end]


def test_cancelled_kiz_uses_readonly_input_not_plain_text() -> None:
    block = _render_block()
    assert "kiz-code-readonly" not in block
    assert "is-readonly" not in block
    assert "readonly tabindex" in block
    assert 'class="wb-fbs-kiz-code-input' in block
    assert "removeDisabled" in block or "disabled" in block


def test_cancelled_kiz_edit_handlers_are_guarded() -> None:
    assert JS.count("_ozonFbsRowIsCancelled(_ozonFbsKizRowByPosting(pn))") >= 3
    assert "if (!row || _ozonFbsRowIsCancelled(row)) return;" in JS
    assert "if (!row || _ozonFbsRowIsCancelled(row) || !Number.isFinite(removeIdx)) return;" in JS


def test_readonly_kiz_input_styles_and_cache_bump() -> None:
    assert ".wb-fbs-kiz-code-input[readonly]" in CSS
    assert "ozon_fbs.js?v=181" in HTML
    assert "style.css?v=387" in HTML
