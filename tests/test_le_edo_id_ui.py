"""Юр.лица: поле «Идентификатор ЭДО» под ФИАС → shipper EDO в эТрН/заявке."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
ETRN = (ROOT / "review_processor" / "ozon_etrn.py").read_text(encoding="utf-8")
ZAKAZ = (ROOT / "review_processor" / "ozon_zakaz.py").read_text(encoding="utf-8")


def test_le_edo_id_form_under_fias() -> None:
    assert 'id="newLegalEdoId"' in HTML
    assert 'id="newContractorEdoId"' in HTML
    assert "Идентификатор ЭДО" in HTML
    fias_pos = HTML.find('id="newLegalAddrFias"')
    edo_pos = HTML.find('id="newLegalEdoId"')
    ctr_fias = HTML.find('id="newContractorAddrFias"')
    ctr_edo = HTML.find('id="newContractorEdoId"')
    assert fias_pos > 0 and edo_pos > fias_pos
    assert ctr_fias > 0 and ctr_edo > ctr_fias
    assert "newLegalEdoId" in JS
    assert "newContractorEdoId" in JS
    assert 'data-field="edo_id"' in JS
    assert "includeEdoId: true" in JS
    assert "{ includeEdoId = false }" in JS


def test_le_edo_id_persisted_in_api_and_repo() -> None:
    assert "edo_id: str = \"\"" in WEB
    assert "ADD COLUMN IF NOT EXISTS edo_id" in REPO
    assert '("edo_id", "TEXT NOT NULL DEFAULT \'\'")' in REPO
    assert "edo_id=payload.edo_id" in WEB


def test_shipper_edo_from_party_card_only() -> None:
    assert 'shipper_edo = str((le or {}).get("edo_id") or "").strip()' in ETRN
    assert 'shipper_edo = str((le or {}).get("edo_id") or "").strip()' in ZAKAZ
    assert "OZON_CONSIGNEE_EDO_GUID" not in ETRN
    assert "2BM-DRAFT-SHIPPER" not in ETRN
    assert "2BM-DRAFT-SHIPPER" not in ZAKAZ
    assert "app.js?v=713" in HTML
    assert "style.css?v=425" in HTML
