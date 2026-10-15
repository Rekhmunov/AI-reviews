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
    assert "Идентификатор ЭДО" in HTML
    # Immediately after FIAS in the create form.
    fias_pos = HTML.find('id="newLegalAddrFias"')
    edo_pos = HTML.find('id="newLegalEdoId"')
    assert fias_pos > 0 and edo_pos > fias_pos
    assert "newLegalEdoId" in JS
    assert 'data-field="edo_id"' in JS
    assert "includeEdoId: isLe" in JS
    assert "includeEdoId: true" in JS
    # Contractors must not get the LE-only EDI field by default.
    assert '{ includeEdoId = false }' in JS


def test_le_edo_id_persisted_in_api_and_repo() -> None:
    assert "edo_id: str = \"\"" in WEB
    assert "ADD COLUMN IF NOT EXISTS edo_id" in REPO
    assert "edo_id=payload.edo_id" in WEB
    assert "edo_id," in REPO or "edo_id =" in REPO


def test_shipper_edo_from_le_only_no_draft_fallback() -> None:
    assert 'shipper_edo = str((le or {}).get("edo_id") or "").strip()' in ETRN
    assert 'shipper_edo = str((le or {}).get("edo_id") or "").strip()' in ZAKAZ
    assert "2BM-DRAFT-SHIPPER" not in ETRN
    assert "2BM-DRAFT-SHIPPER" not in ZAKAZ
    assert "-DRAFT" not in ETRN.split("shipper_edo", 1)[1].split("\n", 3)[0]
    assert "app.js?v=712" in HTML
    assert "style.css?v=425" in HTML
