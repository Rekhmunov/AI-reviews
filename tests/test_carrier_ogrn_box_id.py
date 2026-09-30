"""carrier_ogrn / carrier_box_id in Водители → Перевозчик catalog."""

from pathlib import Path

from review_processor.repository import ReviewRepository

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")


def test_normalize_carrier_ogrn_and_box_id():
    cf = ReviewRepository._normalize_carrier_fields(
        carrier_ogrn="318 3702 00012345",
        carrier_box_id="  a1b2c3d4-e5f6-7890-abcd-ef1234567890  ",
        carrier_fns_id="2BM-test",
    )
    assert cf["carrier_ogrn"] == "318370200012345"
    assert cf["carrier_box_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert cf["carrier_fns_id"] == "2BM-test"


def test_normalize_carrier_ogrn_box_empty_stays_empty():
    cf = ReviewRepository._normalize_carrier_fields()
    assert cf["carrier_ogrn"] == ""
    assert cf["carrier_box_id"] == ""


def test_ui_has_carrier_ogrn_and_box_id_fields():
    assert 'id="newDriverCarrierOgrn"' in HTML
    assert 'id="newDriverCarrierBoxId"' in HTML
    assert "ОГРН / ОГРНИП" in HTML
    assert "ID ящика Diadoc" in HTML
    assert '["carrier_ogrn", "ОГРН / ОГРНИП"]' in APP_JS
    assert '["carrier_box_id", "ID ящика Diadoc"]' in APP_JS
    assert "newDriverCarrierOgrn" in APP_JS
    assert "newDriverCarrierBoxId" in APP_JS
    assert "app.js?v=704" in HTML


def test_web_models_accept_carrier_ogrn_box_id():
    web = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
    create = web.split("class CreateSupplyDriverRequest", 1)[1].split("class CreateSupplyWarehouseRequest", 1)[0]
    update = web.split("class UpdateSupplyDriverRequest", 1)[1].split("class ManagerSuppliesAccessRequest", 1)[0]
    assert "carrier_ogrn: str = \"\"" in create
    assert "carrier_box_id: str = \"\"" in create
    assert "carrier_ogrn: str = \"\"" in update
    assert "carrier_box_id: str = \"\"" in update
    assert "_resolve_diadoc_to_box_id" in web
    assert "carrier_box_id" in web
