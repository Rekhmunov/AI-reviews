"""FBS TTN prefill: load/unload dates default to supply created date (date only)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OZ = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")
WB = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")
APP = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")


def test_ttn_date_from_created_strips_time() -> None:
    from review_processor.ozon_fbs_supplies import _ttn_date_from_created as oz_fn
    from review_processor.wb_fbs import _ttn_date_from_created as wb_fn

    for fn in (oz_fn, wb_fn):
        assert fn("2026-09-15T14:30:00") == "2026-09-15"
        assert fn("2026-09-15 14:30:00") == "2026-09-15"
        assert fn("15.09.2026") == "2026-09-15"
        assert fn("15.09.2026 14:30") == "2026-09-15"
        assert fn("") == ""


def test_ozon_and_wb_prefill_default_load_unload_dates() -> None:
    for src, label in ((OZ, "ozon"), (WB, "wb")):
        prefill = src.split("def build_ttn_prefill", 1)[1].split("\ndef ", 1)[0]
        assert '"loading_datetime": ttn_date' in prefill, label
        assert '"unloading_datetime": ttn_date' in prefill, label
        assert "ttn_date = _ttn_date_from_created(created_at)" in prefill, label
        # Saved user edits still win when reopening an existing TTN.
        assert '"loading_datetime"' in prefill
        merge = prefill[prefill.find("if existing_record:") :]
        assert '"loading_datetime"' in merge, label
        assert '"unloading_datetime"' in merge, label


def test_modal_uses_date_only_inputs() -> None:
    # UI already date-only; converters must ignore time if present.
    assert "function _ttnDatetimeToInputValue" in APP
    assert "Time is ignored" in APP or "time is ignored" in APP.lower() or "THH:MM" in APP
    assert 'type="date"' in (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="ttnCreateLoadingDatetime"' in (ROOT / "web_templates" / "app.html").read_text(
        encoding="utf-8"
    )
    assert 'id="ttnCreateUnloadingDatetime"' in (ROOT / "web_templates" / "app.html").read_text(
        encoding="utf-8"
    )
