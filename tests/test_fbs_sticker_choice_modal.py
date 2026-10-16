"""WB FBS KIZ + pick: ambiguous sticker QR → order choice modal (partA+partB)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _fn_slice(src: str, name: str, end_names: tuple[str, ...]) -> str:
    start = src.find(f"function {name}")
    assert start >= 0, name
    end = len(src)
    for other in end_names:
        at = src.find(f"function {other}", start + 1)
        if at >= 0:
            end = min(end, at)
    return src[start:end]


def test_choice_modal_markup() -> None:
    assert 'id="fbsStickerChoiceModal"' in HTML
    assert 'id="fbsStickerChoiceList"' in HTML
    assert "Несколько заказов с одним стикером" in HTML
    assert "Выберите заказ по номеру стикера на этикетке" in HTML
    assert 'onclick="dismissFbsStickerChoice()"' in HTML
    assert ">Отмена<" in HTML
    block = HTML[
        HTML.find("fbsStickerChoiceModal") : HTML.find("fbsStickerChoiceModal") + 1200
    ]
    # No Esc / overlay dismiss — same discipline as scan-ack.
    assert "if(event.target===this)" not in block


def test_choice_helpers_and_gates() -> None:
    assert "function showFbsStickerChoice" in APP_JS
    assert "function dismissFbsStickerChoice" in APP_JS
    assert "function confirmFbsStickerChoice" in APP_JS
    assert "function _fbsStickerChoiceModalOpen" in APP_JS
    assert "_fbsStickerChoiceSwallowKeys" in APP_JS
    # COM blocked while choice is open.
    com = _fn_slice(APP_JS, "deliverWbFbsComScan", ("_wbFbsScanComFlushBuffer",))
    assert "_fbsStickerChoiceModalOpen()" in com
    # Processors bail while open and open choice on ambiguous.
    for fn, mode in (
        ("processWbFbsKizStickerScan", '"kiz"'),
        ("processWbFbsPickStickerScan", '"pick"'),
    ):
        body = _fn_slice(
            APP_JS,
            fn,
            (
                "onWbFbsKizStickerScanKey",
                "onWbFbsPickStickerScanKey",
                "beginWbFbsKizMarkScan",
                "beginWbFbsPickSkuScan",
            ),
        )
        assert "_fbsStickerChoiceModalOpen()) return" in body
        assert "showFbsStickerChoice(matches, scan," in body
        assert mode in body
        assert "Выберите заказ по номеру стикера на этикетке" in body
        # Prefer choice over the old ack text on the happy ambiguous path.
        choice_at = body.find("showFbsStickerChoice(matches, scan,")
        ack_at = body.find("Отсканируйте QR стикера ещё раз")
        assert choice_at >= 0
        assert ack_at > choice_at


def test_confirm_continues_happy_path() -> None:
    confirm = _fn_slice(
        APP_JS,
        "confirmFbsStickerChoice",
        ("clearWbFbsKizScanField", "dismissFbsStickerChoice"),
    )
    assert "_wbFbsKizPersistStickerForOrder" in confirm
    assert "beginWbFbsKizMarkScan" in confirm
    assert "beginWbFbsPickSkuScan" in confirm
    # Close without refocusing sticker field before opening SKU/mark prompt.
    assert "refocus: false" in confirm
    show = _fn_slice(
        APP_JS,
        "showFbsStickerChoice",
        ("dismissFbsStickerChoice", "confirmFbsStickerChoice"),
    )
    assert "fbs-sticker-choice-item" in show
    assert "fbs-sticker-choice-order" in show
    assert "_wbFbsKizStickerHtml" in show
    assert "tabindex=\"-1\"" in show or "tabindex='-1'" in show


def test_styles_and_cache_bumps() -> None:
    assert ".fbs-sticker-choice-modal" in CSS
    assert ".fbs-sticker-choice-item" in CSS
    assert "#fbsStickerChoiceModal" in CSS
    assert "app.js?v=713" in HTML
    assert "style.css?v=425" in HTML
