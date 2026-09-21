"""Driver column on WB «В доставке» and Ozon «Доставляются», left of Склад."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
OZON_JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
WB = (ROOT / "review_processor" / "wb_fbs.py").read_text(encoding="utf-8")
OZ = (ROOT / "review_processor" / "ozon_fbs_supplies.py").read_text(encoding="utf-8")


def _slice(src: str, start: str, end: str) -> str:
    i = src.find(start)
    assert i >= 0, start
    j = src.find(end, i + len(start))
    assert j > i, end
    return src[i:j]


def test_cache_versions() -> None:
    assert "app.js?v=691" in HTML
    assert "ozon_fbs.js?v=190" in HTML
    assert "style.css?v=408" in HTML


def test_wb_delivery_column_only() -> None:
    assert 'if (wbFbsState.tab === "delivery") return 9;' in APP_JS
    assert 'if (wbFbsState.tab === "assembly") return 6;' in APP_JS
    sync = _slice(APP_JS, "function _wbFbsSyncTableMode", "function _wbFbsClearLookupMode")
    assembly, rest = sync.split("} else if (supplies)", 1)
    delivery, _orders = rest.split("} else {", 1)
    assert "Водитель" not in assembly
    assert 'data-col="4">Склад' in assembly
    assert delivery.index("Водитель") < delivery.index('data-col="6">Склад')
    render = _slice(APP_JS, "function renderWbFbsSuppliesTable", "function renderWbFbsOrdersTable")
    assert 'wbFbsState.tab === "delivery"' in render
    assert "wb-fbs-td-driver" in render
    assert "_wbFbsSupplyDriverLabel" in render
    assert 'return "не назначен"' in APP_JS
    assert "WB_FBS_DEFAULT_WIDTHS_SUPPLIES_DELIVERY = [18, 12, 12, 12, 12, 16, 18]" in APP_JS


def test_ozon_delivering_column_only() -> None:
    colspan = _slice(OZON_JS, "function colspan()", "async function loadSources")
    assert "isDeliveringSuppliesTab()) return 8;" in colspan
    assert "return 7;" in colspan
    sync = _slice(OZON_JS, "function syncTableMode", "function _ozonFbsRenameMenuIconHtml")
    assert 'const delivering = isDeliveringSuppliesTab();' in sync
    assert 'Водитель${rh}' in sync or '<th data-col="4">Водитель' in sync
    assert 'delivering ? "5" : "4"}">Склад' in sync
    render = _slice(OZON_JS, "function renderSuppliesTable", "function productCompositionHtml")
    assert "isDeliveringSuppliesTab()" in render
    assert "wb-fbs-td-driver" in render
    assert "_ozonFbsSupplyDriverLabel" in render
    assert 'return "не назначен"' in OZON_JS


def test_lists_batch_load_driver_only_on_delivery_tabs() -> None:
    wb_list = _slice(WB, "def _list_supplies_for_orders_tab", "def _persist_supply_boxes")
    assert "if tab_key == TAB_DELIVERY and items:" in wb_list
    assert "_attach_supply_drivers_to_items" in wb_list
    assert "wb_fbs_supply_driver" in WB
    oz_list = _slice(OZ, "def _list_supplies_tab_response", "def resolve_fbs_supply_row_tone")
    assert "oz.TAB_DELIVERING" in oz_list
    assert "_attach_supply_drivers_to_items" in oz_list
    assert "ozon_fbs_supply_driver" in OZ
    # Awaiting-deliver list must not grow its own driver query.
    awaiting = _slice(OZ, "def list_awaiting_deliver_supplies", "def list_delivering_supplies")
    assert "ozon_fbs_supply_driver" not in awaiting


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = tuple(params)
        return _Result(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Repo:
    def __init__(self, rows):
        self.conn = _Conn(rows)

    def _sql(self, text):
        return text

    def _connect(self):
        return self.conn

    def _row_to_dict(self, row):
        return dict(row)


def test_wb_attach_matches_source_and_supply() -> None:
    from review_processor.wb_fbs import _attach_supply_drivers_to_items

    items = [
        {"supply_id": "WB-1", "source_id": 7},
        {"supply_id": "WB-2", "source_id": 7},
        {"supply_id": "WB-1", "source_id": 8},
    ]
    repo = _Repo(
        [
            {
                "source_id": 7,
                "supply_id": "WB-1",
                "driver_id": 3,
                "driver_name": "Иванов",
                "vehicle_number": "А111АА77",
            },
            {
                "source_id": 8,
                "supply_id": "WB-1",
                "driver_id": 0,
                "driver_name": "",
                "vehicle_number": "",
            },
        ]
    )
    _attach_supply_drivers_to_items(repo, user_id=1, items=items)
    assert "wb_fbs_supply_driver" in repo.conn.sql
    assert items[0]["has_driver"] is True
    assert items[0]["driver_name"] == "Иванов"
    assert items[1]["has_driver"] is False
    assert items[1]["driver_name"] == ""
    assert items[2]["has_driver"] is False


def test_ozon_attach_only_named_driver() -> None:
    from review_processor.ozon_fbs_supplies import _attach_supply_drivers_to_items

    items = [
        {"supply_id": "OZ-1"},
        {"supply_id": "OZ-2"},
    ]
    repo = _Repo(
        [
            {
                "source_id": 4,
                "supply_id": "OZ-1",
                "driver_id": 9,
                "driver_name": "Петров",
                "vehicle_number": "В222ВВ99",
            }
        ]
    )
    _attach_supply_drivers_to_items(repo, user_id=2, source_id=4, items=items)
    assert "ozon_fbs_supply_driver" in repo.conn.sql
    assert repo.conn.params[0] == 2
    assert repo.conn.params[1] == 4
    assert items[0]["has_driver"] is True
    assert items[0]["driver_name"] == "Петров"
    assert items[1]["has_driver"] is False
    assert items[1]["driver_name"] == ""
    assert items[1]["source_id"] == 4
