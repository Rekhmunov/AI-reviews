"""TTN display titles: manual daily default + FBS supply-name uniquify."""

from pathlib import Path

from review_processor.ttn_title import (
    format_fbs_ttn_title_base,
    format_manual_ttn_title,
    resolve_ttn_title_for_create,
    suggest_fbs_ttn_title,
    title_for_blank_record,
    unique_ttn_title,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
OZ = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")
WB = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")


def test_manual_and_fbs_title_formatters() -> None:
    assert format_manual_ttn_title(n=1, ttn_date="17.09.2026") == "ТН 1 от 17.09.2026"
    assert format_fbs_ttn_title_base(supply_name="Поставка A от 17.09.2026") == (
        "ТН Поставка A от 17.09.2026"
    )
    assert format_fbs_ttn_title_base(supply_name="ТН Уже с префиксом") == "ТН Уже с префиксом"


def test_unique_ttn_title_suffix() -> None:
    existing = {"ТН Поставка X", "ТН Поставка X (2)"}
    assert unique_ttn_title("ТН Поставка X", existing) == "ТН Поставка X (3)"
    assert unique_ttn_title("ТН Поставка X", existing, exclude="ТН Поставка X") == (
        "ТН Поставка X"
    )


class _FakeRepo:
    def __init__(self, rows):
        self._rows = rows

    def list_supply_ttn_records(self, *, user_id: int):
        return list(self._rows)


def test_blank_record_title_uses_manual_or_fbs_template() -> None:
    existing = {"ТН 1 от 17.09.2026"}
    assert title_for_blank_record(
        doc_number="2",
        ttn_date="17.09.2026",
        existing=existing,
    ) == "ТН 2 от 17.09.2026"
    assert title_for_blank_record(
        doc_number="9",
        ttn_date="17.09.2026",
        supply_name="Поставка A от 17.09.2026",
        fbs_platform="wb",
        existing=set(),
    ) == "ТН Поставка A от 17.09.2026"
    assert title_for_blank_record(
        doc_number="1",
        ttn_date="17.09.2026",
        existing=existing,
    ) == "ТН 1 от 17.09.2026 (2)"
    repo = _FakeRepo([{"title": "ТН 1 от 17.09.2026"}])
    assert resolve_ttn_title_for_create(
        repo,
        user_id=1,
        title="",
        doc_number="2",
        ttn_date="17.09.2026",
    ) == "ТН 2 от 17.09.2026"
    assert resolve_ttn_title_for_create(
        repo,
        user_id=1,
        title="",
        doc_number="1",
        ttn_date="17.09.2026",
        supply_name="Поставка A от 17.09.2026",
        fbs_platform="ozon",
    ) == "ТН Поставка A от 17.09.2026"
    assert suggest_fbs_ttn_title(
        repo, user_id=1, supply_name="Поставка A от 17.09.2026", keep_title="Сохранённое"
    ) == "Сохранённое"


def test_backend_title_column_and_api_wired() -> None:
    assert 'ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT \'\'' in REPO
    assert "COALESCE(t.title, '') AS title" in REPO
    assert "title: str = \"\"" in WEB
    assert "supply_name: str = \"\"" in WEB
    assert "def _ttn_lookup_fbs_supply_name" in WEB
    assert "def peek_next_ttn_number" in REPO
    assert "def ensure_blank_ttn_titles" in REPO
    assert "next-manual-title" in WEB
    assert "resolve_ttn_title_for_create" in WEB
    assert "title=title," in WEB.split("def create_ttn_record", 1)[1].split(
        "def update_ttn_record", 1
    )[0]
    update = WEB.split("def update_ttn_record", 1)[1].split("\n    @app.delete", 1)[0]
    assert "title=title," in update
    assert "unique_ttn_title" in update


def test_fbs_prefill_sets_title() -> None:
    oz_prefill = OZ.split("def build_ttn_prefill", 1)[1].split(
        "\ndef list_supply_driver_options", 1
    )[0]
    wb_prefill = WB.split("def build_ttn_prefill", 1)[1].split(
        "\ndef persist_order_stickers_batch", 1
    )[0]
    assert "suggest_fbs_ttn_title" in oz_prefill
    assert "suggest_fbs_ttn_title" in wb_prefill
    assert '"title"' in oz_prefill
    assert '"title"' in wb_prefill
    assert '"supply_name": supply_name' in oz_prefill
    assert '"supply_name": supply_name' in wb_prefill


def test_ui_title_field_and_table_column() -> None:
    assert 'id="ttnCreateTitle"' in HTML
    assert "Название" in HTML.split('id="ttnTable"', 1)[1].split("tbody", 1)[0]
    assert 'id="ttnCreateTitle"' in HTML.split('id="createTtnModal"', 1)[1][:2500]
    assert "title: String(s.title || \"\").trim()" in JS or 'title: String(s.title || "").trim()' in JS
    assert "async function _ttnEnsureDefaultTitles" in JS
    assert "function _ttnFormatManualTitle" in JS
    assert "function _ttnFormatFbsTitle" in JS
    assert "/api/supply-ttn-records/next-manual-title" in JS
    open_modal = JS.split("async function _openTtnModal", 1)[1].split(
        "async function openCreateTtnModal", 1
    )[0]
    assert "_ttnEnsureDefaultTitles" in open_modal
    assert "(r.title || \"\").toLowerCase().includes(sq)" in JS or "(r.title || '').toLowerCase().includes(sq)" in JS
    assert 'colspan="7"' in JS.split("function renderTtnTable", 1)[1].split(
        "window.renderTtnTable", 1
    )[0]
    assert "logistics_ttn_col_widths_v2" in JS
    assert "app.js?v=686" in HTML
    assert "style.css?v=406" in HTML
    assert "ozon_fbs.js?v=188" in HTML
