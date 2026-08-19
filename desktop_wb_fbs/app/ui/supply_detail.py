# -*- coding: utf-8 -*-
from __future__ import annotations

from functools import partial
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from app.db import Database
from app.services.kiz_pick import KizService, PickVerifyService
from app.services.orders import OrdersService
from app.services.trbx_stickers import StickersService, TrbxService
from app.ui.layout_utils import FlowLayout
from app.wb import cargo_type_label, supply_status_label


class SupplyDetailDialog(QDialog):
    def __init__(
        self,
        db: Database,
        orders: OrdersService,
        source: Dict[str, Any],
        supply_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super(SupplyDetailDialog, self).__init__(parent)
        self.db = db
        self.orders = orders
        self.source = source
        self.supply_id = supply_id
        self.source_id = int(source["id"])
        self.api_key = str(source["api_key"])
        self.trbx = TrbxService(db)
        self.stickers = StickersService(db)
        self.kiz = KizService(db)
        self.pick = PickVerifyService(db)

        self.setWindowTitle("Поставка {}".format(supply_id))
        # Natural landscape card (~16:10), not ultra-wide or short
        self.resize(1040, 720)
        self.setMinimumSize(880, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header block mirrors web .wb-fbs-sd-header
        header = QFrame()
        header.setObjectName("sdHeader")
        hv = QVBoxLayout(header)
        hv.setContentsMargins(24, 20, 24, 16)
        hv.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        self.header = QLabel("")
        self.header.setObjectName("sdTitle")
        self.header.setWordWrap(True)
        title_row.addWidget(self.header, 1)
        close_x = QPushButton("✕")
        close_x.setObjectName("iconBtn")
        close_x.setToolTip("Закрыть")
        close_x.clicked.connect(self.accept)
        title_row.addWidget(close_x, 0, Qt.AlignTop)
        hv.addLayout(title_row)

        self.warehouse = QLabel("")
        self.warehouse.setObjectName("sdMeta")
        hv.addWidget(self.warehouse)

        self.meta_chips = FlowLayout(h_spacing=8, v_spacing=8)
        hv.addLayout(self.meta_chips)
        # Keep legacy meta label for picking_list status append
        self.meta = QLabel("")
        self.meta.setObjectName("sdMeta")
        self.meta.setWordWrap(True)
        hv.addWidget(self.meta)

        # Wrapping action row — no horizontal squeeze / fixed-height scroll
        actions = FlowLayout(h_spacing=8, v_spacing=8)

        def _sec(btn):
            btn.setObjectName("secondary")
            return btn

        pick_btn = _sec(QPushButton("Лист подбора"))
        pick_btn.clicked.connect(partial(self.picking_list, "summary"))
        pick_caret = QToolButton()
        pick_caret.setObjectName("secondary")
        pick_caret.setText("▾")
        pick_caret.setPopupMode(QToolButton.InstantPopup)
        pick_menu = QMenu(pick_caret)
        pick_menu.addAction(
            "Расширенный лист подбора", partial(self.picking_list, "extended")
        )
        pick_caret.setMenu(pick_menu)
        actions.addWidget(pick_btn)
        actions.addWidget(pick_caret)

        st_btn = _sec(QPushButton("Стикеры"))
        st_btn.clicked.connect(self.print_stickers)
        st_caret = QToolButton()
        st_caret.setObjectName("secondary")
        st_caret.setText("▾")
        st_caret.setPopupMode(QToolButton.InstantPopup)
        st_menu = QMenu(st_caret)
        st_menu.addAction("Печать по категориям", self.stickers_by_category)
        st_caret.setMenu(st_menu)
        actions.addWidget(st_btn)
        actions.addWidget(st_caret)

        kiz_btn = _sec(QPushButton("Маркировка"))
        kiz_btn.clicked.connect(self.open_kiz)
        actions.addWidget(kiz_btn)
        kiz_ref = _sec(QPushButton("↻"))
        kiz_ref.setMinimumWidth(40)
        kiz_ref.setToolTip("Проверить статусы КИЗ на ВБ")
        kiz_ref.clicked.connect(self.refresh_kiz_status)
        actions.addWidget(kiz_ref)

        for text, slot in (
            ("Проверка ШК", self.open_pick),
            ("Грузоместа", self.manage_trbx),
            ("Отменённые заказы", self.show_cancelled),
            ("QR поставки", self.print_qr),
            ("Портал ВБ", self.open_portal),
        ):
            btn = _sec(QPushButton(text))
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        hv.addLayout(actions)
        root.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 20)
        body.setSpacing(12)
        self.table = QTableWidget(0, 6)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(
            ["Заказ", "Артикул", "Тип", "Цена", "КИЗ", "Проверка"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setShowGrid(False)
        body.addWidget(self.table, 1)
        root.addLayout(body, 1)

        self.reload()

    def _clear_chips(self) -> None:
        while self.meta_chips.count():
            item = self.meta_chips.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w:
                w.deleteLater()

    def _add_chip(self, text: str) -> None:
        lab = QLabel(text)
        lab.setObjectName("sdChip")
        lab.setMargin(0)
        self.meta_chips.addWidget(lab)

    def reload(self) -> None:
        supply = self.orders.get_supply(self.source_id, self.supply_id)
        if not supply:
            QMessageBox.warning(self, "Поставка", "Не найдена локально")
            return
        self.header.setText(str(supply.get("name") or self.supply_id))
        self._clear_chips()
        self._add_chip(cargo_type_label(supply.get("cargo_type")) or "—")
        self._add_chip("заказов {}".format(len(supply.get("order_ids") or [])))
        self._add_chip("коробов {}".format(len(supply.get("boxes") or [])))
        self._add_chip(
            supply_status_label(done=supply.get("done"), scan_dt=supply.get("scan_dt"))
        )
        self.meta.setText("ID {}".format(self.supply_id))
        rows = self.orders.orders_in_supply(
            self.source_id, self.supply_id, api_key=self.api_key
        )
        if rows:
            wh = str(
                rows[0].get("warehouse_label") or rows[0].get("warehouse_id") or ""
            )
            self.warehouse.setText(wh or "—")
        else:
            self.warehouse.setText("—")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            oid_item = QTableWidgetItem(str(r.get("order_id")))
            f = oid_item.font()
            f.setBold(True)
            oid_item.setFont(f)
            self.table.setItem(i, 0, oid_item)
            name = str(r.get("product_name") or r.get("article") or "")
            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(str(r.get("cargo_label") or "")))
            self.table.setItem(i, 3, QTableWidgetItem(str(r.get("price_label") or "")))
            codes = [c for c in (r.get("kiz_codes") or []) if str(c).strip(" \t\r\n")]
            self.table.setItem(i, 4, QTableWidgetItem(str(len(codes)) if codes else "—"))
            self.table.setItem(
                i, 5, QTableWidgetItem("да" if r.get("pick_verified") else "—")
            )

    def picking_list(self, variant: str = "summary") -> None:
        from app.services.print_docs import print_picking_list

        try:
            path = print_picking_list(
                self.db,
                self.orders,
                self.source_id,
                self.api_key,
                self.supply_id,
                variant=variant,
            )
            self.meta.setText(self.meta.text() + " · открыт {}".format(path.name))
        except Exception as exc:
            QMessageBox.critical(self, "Лист подбора", str(exc))

    def print_stickers(self) -> None:
        from app.services.print_docs import print_supply_stickers

        try:
            print_supply_stickers(
                self.db,
                self.orders,
                self.source_id,
                self.api_key,
                self.supply_id,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Стикеры", str(exc))

    def print_qr(self) -> None:
        from app.ui.dialogs_extra import show_supply_qr

        try:
            show_supply_qr(self.api_key, self.supply_id, self)
        except Exception as exc:
            QMessageBox.critical(self, "QR", str(exc))

    def open_portal(self) -> None:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        url = (
            "https://seller.wildberries.ru/marketplace-orders-fbs/supply-detail/packaging"
            "?supplyID={}".format(self.supply_id)
        )
        QDesktopServices.openUrl(QUrl(url))

    def show_cancelled(self) -> None:
        from app.services.cancelled import list_cancelled_in_supply

        try:
            data = list_cancelled_in_supply(
                self.db, self.source_id, self.api_key, self.supply_id
            )
        except Exception as exc:
            QMessageBox.critical(self, "Отменённые", str(exc))
            return
        rows = data.get("rows") or []
        dlg = QDialog(self)
        dlg.setWindowTitle("Отменённые заказы · {}".format(self.supply_id))
        dlg.resize(720, 520)
        dlg.setMinimumSize(560, 400)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        title = QLabel("Отменённые заказы")
        title.setObjectName("dialogTitle")
        lay.addWidget(title)
        lead = QLabel("Найдено отменённых в поставке: {}".format(len(rows)))
        lead.setObjectName("hint")
        lay.addWidget(lead)
        table = QTableWidget(len(rows), 3)
        table.setAlternatingRowColors(True)
        table.setHorizontalHeaderLabels(["Заказ", "Артикул", "Причина"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        for i, r in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(r.get("order_id"))))
            table.setItem(i, 1, QTableWidgetItem(str(r.get("article") or "")))
            table.setItem(i, 2, QTableWidgetItem(str(r.get("cancel_reason") or "")))
        lay.addWidget(table, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dlg.reject)
        lay.addWidget(close)
        dlg.exec_()
        self.reload()

    def stickers_by_category(self) -> None:
        from app.services.print_docs import (
            print_supply_stickers,
            sticker_groups_for_category_print,
        )

        try:
            groups = sticker_groups_for_category_print(
                self.db, self.orders, self.source_id, self.api_key, self.supply_id
            )
        except Exception as exc:
            QMessageBox.critical(self, "Стикеры", str(exc))
            return
        if not groups:
            QMessageBox.information(self, "Стикеры", "Нет товаров для печати")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Стикеры по категориям")
        dlg.resize(680, 560)
        dlg.setMinimumSize(560, 440)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        title = QLabel("Печать по категориям")
        title.setObjectName("dialogTitle")
        lay.addWidget(title)
        hint = QLabel("Отметьте группы товаров для печати стикеров.")
        hint.setObjectName("hint")
        lay.addWidget(hint)
        table = QTableWidget(len(groups), 4)
        table.setAlternatingRowColors(True)
        table.setHorizontalHeaderLabels(["", "Категория", "Товар", "Шт"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        for i, g in enumerate(groups):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            chk.setData(Qt.UserRole, list(g.get("order_ids") or []))
            table.setItem(i, 0, chk)
            table.setItem(i, 1, QTableWidgetItem(str(g.get("category") or "")))
            table.setItem(
                i,
                2,
                QTableWidgetItem(
                    "{} · {}".format(g.get("product_name") or "", g.get("article") or "")
                ),
            )
            table.setItem(i, 3, QTableWidgetItem(str(g.get("qty") or 0)))
        lay.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Печать выбранных")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("secondary")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec_() != QDialog.Accepted:
            return
        order_ids = []
        for i in range(table.rowCount()):
            item = table.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                order_ids.extend(item.data(Qt.UserRole) or [])
        if not order_ids:
            QMessageBox.information(self, "Стикеры", "Ничего не выбрано")
            return
        try:
            print_supply_stickers(
                self.db,
                self.orders,
                self.source_id,
                self.api_key,
                self.supply_id,
                order_ids=order_ids,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Стикеры", str(exc))

    def refresh_kiz_status(self) -> None:
        try:
            result = self.kiz.refresh_statuses(
                self.source_id, self.api_key, self.supply_id
            )
            QMessageBox.information(
                self,
                "Статусы",
                "Обновлено заказов: {} · отменённых: {}".format(
                    result.get("updated", 0), result.get("cancelled", 0)
                ),
            )
            self.reload()
        except Exception as exc:
            QMessageBox.critical(self, "Статусы", str(exc))

    def manage_trbx(self) -> None:
        dlg = TrbxDialog(self.trbx, self.source_id, self.api_key, self.supply_id, self)
        dlg.exec_()
        self.reload()

    def open_kiz(self) -> None:
        from app.ui.kiz_pick_dialogs import KizDialog

        dlg = KizDialog(
            self.kiz, self.source_id, self.api_key, self.supply_id, self
        )
        dlg.exec_()
        self.reload()

    def open_pick(self) -> None:
        from app.ui.kiz_pick_dialogs import PickDialog

        dlg = PickDialog(
            self.pick, self.source_id, self.api_key, self.supply_id, self
        )
        dlg.exec_()
        self.reload()


class TrbxDialog(QDialog):
    def __init__(
        self,
        trbx: TrbxService,
        source_id: int,
        api_key: str,
        supply_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super(TrbxDialog, self).__init__(parent)
        self.trbx = trbx
        self.source_id = source_id
        self.api_key = api_key
        self.supply_id = supply_id
        self.setWindowTitle("Грузоместа (TRBX)")
        self.resize(640, 520)
        self.setMinimumSize(520, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        title = QLabel("Грузоместа")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        bar = FlowLayout(h_spacing=8, v_spacing=8)
        self.amount = QSpinBox()
        self.amount.setRange(1, 100)
        self.amount.setValue(1)
        self.amount.setMinimumWidth(72)
        create = QPushButton("Создать")
        create.clicked.connect(self.create_boxes)
        refresh = QPushButton("Обновить")
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self.reload)
        delete = QPushButton("Удалить все")
        delete.setObjectName("danger")
        delete.clicked.connect(self.delete_all)
        stickers = QPushButton("Стикеры коробов")
        stickers.setObjectName("secondary")
        stickers.clicked.connect(self.print_stickers)
        qty_lab = QLabel("Кол-во")
        qty_lab.setObjectName("fieldLabel")
        bar.addWidget(qty_lab)
        bar.addWidget(self.amount)
        bar.addWidget(create)
        bar.addWidget(refresh)
        bar.addWidget(delete)
        bar.addWidget(stickers)
        root.addLayout(bar)
        self.list = QTableWidget(0, 1)
        self.list.setAlternatingRowColors(True)
        self.list.setHorizontalHeaderLabels(["ID грузоместа"])
        self.list.horizontalHeader().setStretchLastSection(True)
        self.list.verticalHeader().setVisible(False)
        self.list.verticalHeader().setDefaultSectionSize(40)
        root.addWidget(self.list, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        root.addWidget(close)
        self.reload()

    def reload(self) -> None:
        try:
            boxes = self.trbx.refresh(self.source_id, self.api_key, self.supply_id)
        except Exception:
            boxes = self.trbx.list_boxes(self.source_id, self.supply_id)
        self.list.setRowCount(len(boxes))
        for i, b in enumerate(boxes):
            if isinstance(b, dict):
                bid = str(b.get("id") or b.get("trbxId") or "")
            else:
                bid = str(b)
            self.list.setItem(i, 0, QTableWidgetItem(bid))

    def create_boxes(self) -> None:
        try:
            self.trbx.create(
                self.source_id, self.api_key, self.supply_id, int(self.amount.value())
            )
            self.reload()
        except Exception as exc:
            QMessageBox.critical(self, "TRBX", str(exc))

    def delete_all(self) -> None:
        if (
            QMessageBox.question(self, "TRBX", "Удалить все грузоместа?")
            != QMessageBox.Yes
        ):
            return
        try:
            self.trbx.delete_all(self.source_id, self.api_key, self.supply_id)
            self.reload()
        except Exception as exc:
            QMessageBox.critical(self, "TRBX", str(exc))

    def print_stickers(self) -> None:
        from app.ui.dialogs_extra import show_png_list

        boxes = self.trbx.list_boxes(self.source_id, self.supply_id)
        ids = []
        for b in boxes:
            if isinstance(b, dict):
                bid = str(b.get("id") or b.get("trbxId") or "").strip()
            else:
                bid = str(b or "").strip()
            if bid:
                ids.append(bid)
        if not ids:
            QMessageBox.information(self, "TRBX", "Нет грузомест")
            return
        try:
            pngs = self.trbx.stickers_png(self.api_key, self.supply_id, ids)
            show_png_list(pngs, "Стикеры коробов", self)
        except Exception as exc:
            QMessageBox.critical(self, "TRBX", str(exc))
