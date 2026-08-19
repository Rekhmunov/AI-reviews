# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QHeaderView,
    QSpinBox,
)

from app.db import Database
from app.services import SourceService
from app.services.orders import OrdersService
from app.wb.sync import sync_source


class SyncWorker(QThread):
    progress = pyqtSignal(str, int)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(
        self,
        db: Database,
        source_id: int,
        api_key: str,
        lookback_days: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super(SyncWorker, self).__init__(parent)
        self.db = db
        self.source_id = source_id
        self.api_key = api_key
        self.lookback_days = lookback_days
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            result = sync_source(
                self.db,
                self.source_id,
                self.api_key,
                lookback_days=self.lookback_days,
                stop_requested=lambda: self._stop,
                progress=lambda m, n: self.progress.emit(m, n),
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class FbsPage(QWidget):
    def __init__(
        self, db: Database, sources: SourceService, orders: OrdersService
    ) -> None:
        super(FbsPage, self).__init__()
        self.db = db
        self.sources = sources
        self.orders = orders
        self._tab = "new"
        self._page = 0
        self._page_size = 50
        self._worker = None  # type: Optional[SyncWorker]
        self._selected_order_ids = set()  # type: set

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("Поставки — ВБ ФБС")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(220)
        self.source_combo.currentIndexChanged.connect(self.on_source_change)
        title_row.addWidget(QLabel("Источник"))
        title_row.addWidget(self.source_combo)
        root.addLayout(title_row)

        toolbar = QHBoxLayout()
        self.sync_btn = QPushButton("Синхронизировать")
        self.sync_btn.clicked.connect(self.start_sync)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setProperty("class", "danger")
        self.stop_btn.setStyleSheet(
            "background:#fff;color:#b91c1c;border:1px solid #fca5a5;"
        )
        self.stop_btn.clicked.connect(self.stop_sync)
        self.stop_btn.setEnabled(False)
        self.auto_btn = QPushButton("Автоматика")
        self.auto_btn.setProperty("class", "secondary")
        self.auto_btn.setStyleSheet(
            "background:#fff;color:#1e293b;border:1px solid #cbd5e1;"
        )
        self.auto_btn.clicked.connect(self.open_auto_settings)
        toolbar.addWidget(self.sync_btn)
        toolbar.addWidget(self.stop_btn)
        toolbar.addWidget(self.auto_btn)
        toolbar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: заказ, артикул, поставка…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(260)
        self.search.returnPressed.connect(self.reload_table)
        self.search.textChanged.connect(self._on_search_debounce)
        toolbar.addWidget(self.search)
        root.addLayout(toolbar)

        self.sync_info = QLabel("")
        self.sync_info.setWordWrap(True)
        self.sync_info.setStyleSheet(
            "background:#eff6ff;border:1px solid #bfdbfe;padding:8px;border-radius:4px;"
        )
        self.sync_info.hide()
        root.addWidget(self.sync_info)

        tabs_row = QHBoxLayout()
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "Новые")
        self.tabs.addTab(QWidget(), "На сборке")
        self.tabs.addTab(QWidget(), "В доставке")
        self.tabs.currentChanged.connect(self.on_tab_change)
        # Use custom count labels via tab text updates
        tabs_row.addWidget(self.tabs, 1)
        self.collect_mgt_btn = QPushButton("Собрать все МГТ")
        self.collect_mgt_btn.clicked.connect(self.collect_mgt)
        tabs_row.addWidget(self.collect_mgt_btn)
        root.addLayout(tabs_row)

        self.table = QTableWidget(0, 0)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.doubleClicked.connect(self.on_row_double_click)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.sel_label = QLabel("Выбрано: 0")
        bottom.addWidget(self.sel_label)
        self.btn_new_supply = QPushButton("Новая поставка")
        self.btn_new_supply.clicked.connect(self.create_supply)
        self.btn_add_supply = QPushButton("Добавить к существующей")
        self.btn_add_supply.setStyleSheet(
            "background:#fff;color:#1e293b;border:1px solid #cbd5e1;"
        )
        self.btn_add_supply.clicked.connect(self.add_to_supply)
        self.btn_open_supply = QPushButton("Открыть поставку")
        self.btn_open_supply.clicked.connect(self.open_selected_supply)
        self.btn_print_stickers = QPushButton("Стикеры")
        self.btn_print_stickers.clicked.connect(self.print_stickers)
        self.btn_supply_qr = QPushButton("QR поставки")
        self.btn_supply_qr.clicked.connect(self.print_supply_qr)
        bottom.addWidget(self.btn_new_supply)
        bottom.addWidget(self.btn_add_supply)
        bottom.addWidget(self.btn_open_supply)
        bottom.addWidget(self.btn_print_stickers)
        bottom.addWidget(self.btn_supply_qr)
        bottom.addStretch(1)
        bottom.addWidget(QLabel("На стр."))
        self.page_size = QSpinBox()
        self.page_size.setRange(30, 100)
        self.page_size.setSingleStep(10)
        self.page_size.setValue(50)
        self.page_size.valueChanged.connect(self.reload_table)
        bottom.addWidget(self.page_size)
        self.prev_btn = QPushButton("←")
        self.prev_btn.setFixedWidth(40)
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn = QPushButton("→")
        self.next_btn.setFixedWidth(40)
        self.next_btn.clicked.connect(self.next_page)
        self.page_label = QLabel("1")
        bottom.addWidget(self.prev_btn)
        bottom.addWidget(self.page_label)
        bottom.addWidget(self.next_btn)
        root.addLayout(bottom)

        self._search_timer_ticks = 0
        self.reload_sources()

    def current_source(self) -> Optional[Dict[str, Any]]:
        idx = self.source_combo.currentIndex()
        if idx < 0:
            return None
        data = self.source_combo.itemData(idx)
        return data if isinstance(data, dict) else None

    def reload_sources(self) -> None:
        current_id = None
        cur = self.current_source()
        if cur:
            current_id = int(cur["id"])
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for s in self.sources.list_fbs_enabled():
            self.source_combo.addItem(str(s.get("name") or ""), s)
        self.source_combo.blockSignals(False)
        if self.source_combo.count() == 0:
            self.sync_info.setText(
                "Нет источников FBS. Откройте Настройки → Источники "
                "и добавьте кабинет с «ФБС» в названии и ключом Marketplace."
            )
            self.sync_info.show()
            self.table.setRowCount(0)
            return
        if current_id is not None:
            for i in range(self.source_combo.count()):
                d = self.source_combo.itemData(i)
                if isinstance(d, dict) and int(d["id"]) == current_id:
                    self.source_combo.setCurrentIndex(i)
                    break
        self.reload_table()

    def on_source_change(self) -> None:
        self._page = 0
        self.reload_table()

    def on_tab_change(self, index: int) -> None:
        self._tab = {0: "new", 1: "assembly", 2: "delivery"}.get(index, "new")
        self._page = 0
        self._selected_order_ids.clear()
        self.reload_table()

    def _on_search_debounce(self, _text: str) -> None:
        # Simple: reload on Enter only; also allow delayed via timer-less immediate for short
        pass

    def update_bottom_visibility(self) -> None:
        is_new = self._tab == "new"
        is_asm = self._tab == "assembly"
        is_del = self._tab == "delivery"
        self.collect_mgt_btn.setVisible(is_new)
        self.btn_new_supply.setVisible(is_new)
        self.btn_add_supply.setVisible(is_new)
        self.btn_open_supply.setVisible(is_asm or is_del)
        self.btn_print_stickers.setVisible(is_asm or is_new)
        self.btn_supply_qr.setVisible(is_del)

    def reload_table(self) -> None:
        self.update_bottom_visibility()
        src = self.current_source()
        if not src:
            return
        sid = int(src["id"])
        counts = self.orders.tab_counts(sid)
        self.tabs.setTabText(0, "Новые ({})".format(counts.get("new", 0)))
        self.tabs.setTabText(1, "На сборке ({})".format(counts.get("assembly", 0)))
        self.tabs.setTabText(2, "В доставке ({})".format(counts.get("delivery", 0)))

        limit = int(self.page_size.value())
        offset = self._page * limit
        search = self.search.text().strip()

        if self._tab == "new":
            rows, total = self.orders.list_orders(
                sid, tab="new", search=search, limit=limit, offset=offset
            )
            self._fill_orders_table(rows)
        elif self._tab == "assembly":
            rows, total = self.orders.list_supplies(
                sid, done=False, search=search, limit=limit, offset=offset
            )
            self._fill_supplies_table(rows)
        else:
            rows, total = self.orders.list_supplies(
                sid, done=True, search=search, limit=limit, offset=offset
            )
            self._fill_supplies_table(rows)

        pages = max(1, (total + limit - 1) // limit)
        if self._page >= pages:
            self._page = pages - 1
        self.page_label.setText("{}/{} · {}".format(self._page + 1, pages, total))
        self.sel_label.setText("Выбрано: {}".format(len(self._selected_order_ids)))

    def _fill_orders_table(self, rows: List[Dict[str, Any]]) -> None:
        try:
            self.table.itemChanged.disconnect(self._on_check_change)
        except Exception:
            pass
        cols = ["", "Заказ", "Артикул", "Склад", "Тип", "Цена", "B2B", "ШК"]
        self.table.blockSignals(True)
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            oid = int(row["order_id"])
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(
                Qt.Checked if oid in self._selected_order_ids else Qt.Unchecked
            )
            chk.setData(Qt.UserRole, oid)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(str(oid)))
            self.table.setItem(r, 2, QTableWidgetItem(str(row.get("article") or "")))
            self.table.setItem(
                r, 3, QTableWidgetItem(str(row.get("warehouse_id") or ""))
            )
            self.table.setItem(r, 4, QTableWidgetItem(str(row.get("cargo_label") or "")))
            self.table.setItem(r, 5, QTableWidgetItem(str(row.get("price_label") or "")))
            self.table.setItem(
                r, 6, QTableWidgetItem("да" if row.get("is_b2b") else "")
            )
            skus = row.get("skus") or []
            self.table.setItem(
                r, 7, QTableWidgetItem(", ".join(str(s) for s in skus[:3]))
            )
        self.table.blockSignals(False)
        self.table.itemChanged.connect(self._on_check_change)

    def _on_check_change(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        oid = item.data(Qt.UserRole)
        if oid is None:
            return
        if item.checkState() == Qt.Checked:
            self._selected_order_ids.add(int(oid))
        else:
            self._selected_order_ids.discard(int(oid))
        self.sel_label.setText("Выбрано: {}".format(len(self._selected_order_ids)))

    def _fill_supplies_table(self, rows: List[Dict[str, Any]]) -> None:
        try:
            self.table.itemChanged.disconnect(self._on_check_change)
        except Exception:
            pass
        cols = ["Поставка", "Название", "Заказов", "Коробов", "Тип", "Статус", "B2B"]
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            sid = str(row.get("supply_id") or "")
            item0 = QTableWidgetItem(sid)
            item0.setData(Qt.UserRole, sid)
            self.table.setItem(r, 0, item0)
            self.table.setItem(r, 1, QTableWidgetItem(str(row.get("name") or "")))
            self.table.setItem(r, 2, QTableWidgetItem(str(row.get("order_count") or 0)))
            self.table.setItem(r, 3, QTableWidgetItem(str(row.get("boxes_count") or 0)))
            self.table.setItem(r, 4, QTableWidgetItem(str(row.get("cargo_label") or "")))
            self.table.setItem(
                r, 5, QTableWidgetItem(str(row.get("status_label") or ""))
            )
            self.table.setItem(
                r, 6, QTableWidgetItem("да" if row.get("is_b2b") else "")
            )

    def prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self.reload_table()

    def next_page(self) -> None:
        self._page += 1
        self.reload_table()

    def start_sync(self) -> None:
        src = self.current_source()
        if not src:
            QMessageBox.warning(self, "Синхронизация", "Выберите источник")
            return
        if self._worker and self._worker.isRunning():
            return
        lookback = int(self.db.get_setting("sync_lookback_days", "3") or 3)
        self.sync_info.setText("Синхронизация…")
        self.sync_info.show()
        self.sync_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker = SyncWorker(
            self.db, int(src["id"]), str(src["api_key"]), lookback, self
        )
        self._worker.progress.connect(self._on_sync_progress)
        self._worker.finished_ok.connect(self._on_sync_done)
        self._worker.failed.connect(self._on_sync_fail)
        self._worker.start()

    def stop_sync(self) -> None:
        if self._worker:
            self._worker.request_stop()

    def _on_sync_progress(self, msg: str, n: int) -> None:
        self.sync_info.setText("{} · заказов: {}".format(msg, n))
        self.sync_info.show()

    def _on_sync_done(self, result: dict) -> None:
        self.sync_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        src = self.current_source()
        if src:
            self.sources.touch_synced(int(src["id"]))
        if result.get("scope_error"):
            self.sync_info.setText(str(result.get("message") or "Ошибка scope"))
            return
        err = result.get("errors") or []
        msg = "Готово: заказов {}, поставок {}".format(
            result.get("orders", 0), result.get("supplies", 0)
        )
        if result.get("stopped"):
            msg += " (остановлено)"
        if err:
            msg += " · ошибки: " + "; ".join(str(e) for e in err[:3])
        self.sync_info.setText(msg)
        self.reload_table()

    def _on_sync_fail(self, err: str) -> None:
        self.sync_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.sync_info.setText("Ошибка: {}".format(err))
        QMessageBox.critical(self, "Синхронизация", err)

    def open_auto_settings(self) -> None:
        from app.ui.dialogs_extra import AutoSyncDialog

        dlg = AutoSyncDialog(self.db, self)
        dlg.exec_()

    def collect_mgt(self) -> None:
        from app.ui.dialogs_extra import CollectMgtDialog

        src = self.current_source()
        if not src:
            return
        dlg = CollectMgtDialog(self.db, self.orders, src, self)
        if dlg.exec_():
            self.reload_table()

    def create_supply(self) -> None:
        from app.ui.dialogs_extra import SelectionSupplyDialog

        src = self.current_source()
        if not src or not self._selected_order_ids:
            QMessageBox.information(self, "Поставка", "Выберите заказы")
            return
        dlg = SelectionSupplyDialog(
            self.orders, src, sorted(self._selected_order_ids), mode="create", parent=self
        )
        if dlg.exec_():
            self._selected_order_ids.clear()
            self.reload_table()

    def add_to_supply(self) -> None:
        from app.ui.dialogs_extra import SelectionSupplyDialog

        src = self.current_source()
        if not src or not self._selected_order_ids:
            QMessageBox.information(self, "Поставка", "Выберите заказы")
            return
        dlg = SelectionSupplyDialog(
            self.orders, src, sorted(self._selected_order_ids), mode="add", parent=self
        )
        if dlg.exec_():
            self._selected_order_ids.clear()
            self.reload_table()

    def _selected_supply_id(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return str(item.data(Qt.UserRole) or item.text() or "")

    def open_selected_supply(self) -> None:
        from app.ui.supply_detail import SupplyDetailDialog

        src = self.current_source()
        sid = self._selected_supply_id()
        if not src or not sid:
            QMessageBox.information(self, "Поставка", "Выберите поставку")
            return
        dlg = SupplyDetailDialog(self.db, self.orders, src, sid, self)
        dlg.exec_()
        self.reload_table()

    def on_row_double_click(self) -> None:
        if self._tab in ("assembly", "delivery"):
            self.open_selected_supply()

    def print_stickers(self) -> None:
        from app.ui.dialogs_extra import show_order_stickers

        src = self.current_source()
        if not src:
            return
        ids = sorted(self._selected_order_ids)
        if self._tab != "new":
            sid = self._selected_supply_id()
            if sid:
                orders = self.orders.orders_in_supply(int(src["id"]), sid)
                ids = [int(o["order_id"]) for o in orders]
        if not ids:
            QMessageBox.information(self, "Стикеры", "Нет заказов для печати")
            return
        try:
            show_order_stickers(str(src["api_key"]), ids, self)
        except Exception as exc:
            QMessageBox.critical(self, "Стикеры", str(exc))

    def print_supply_qr(self) -> None:
        from app.ui.dialogs_extra import show_supply_qr

        src = self.current_source()
        sid = self._selected_supply_id()
        if not src or not sid:
            QMessageBox.information(self, "QR", "Выберите поставку")
            return
        try:
            show_supply_qr(str(src["api_key"]), sid, self)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "QR поставки",
                "{}\n\nQR доступен после передачи поставки в доставку на портале WB.".format(
                    exc
                ),
            )
