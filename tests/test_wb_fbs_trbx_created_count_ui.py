"""WB FBS cargo-places modal: title without ПВЗ + created count."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")


def _between(src: str, start: str, end: str) -> str:
    a = src.find(start)
    assert a >= 0, start
    b = src.find(end, a + len(start))
    assert b > a, end
    return src[a:b]


def test_trbx_title_without_pvz() -> None:
    block = _between(HTML, 'id="wbFbsCreateTrbxTitle"', "</h3>")
    assert "Создайте грузоместа для поставки" in block
    assert "ПВЗ" not in block
    assert 'Создать грузоместа для поставки' in JS
    assert "для ПВЗ" not in JS or JS.count("для ПВЗ") == JS.count("Отказ на ПВЗ")  # unrelated chips OK
    assert "Создать грузоместа (короба) для ПВЗ" not in JS
    btn = _between(HTML, 'id="wbFbsSupplyDetailTrbxBtn"', "</button>")
    assert "ПВЗ" not in btn


def test_trbx_created_count_above_info() -> None:
    body = _between(HTML, 'id="wbFbsCreateTrbxModal"', 'id="wbFbsTrbxDeleteAllConfirmModal"')
    created_i = body.find('id="wbFbsCreateTrbxCreated"')
    info_i = body.find('id="wbFbsCreateTrbxInfo"')
    assert created_i > 0 and info_i > created_i
    assert "function _wbFbsTrbxUpdateCreatedCount" in JS
    assert "Создано грузомест:" in JS
    assert "_wbFbsTrbxUpdateCreatedCount(boxesCount)" in JS
    assert ".wb-fbs-create-trbx-created" in CSS


def test_cache_bump() -> None:
    assert "app.js?v=658" in HTML
    assert "style.css?v=385" in HTML
