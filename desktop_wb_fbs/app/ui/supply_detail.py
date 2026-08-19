# -*- coding: utf-8 -*-
from __future__ import annotations

from functools import partial
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from app.db import Database
from app.services.kiz_pick import KizService, PickVerifyService
from app.services.orders import OrdersService
from app.services.trbx_stickers import StickersService, TrbxService
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
        self.resize(960, 640)

        root = QVBoxLayout(self)
        self.header = QLabel("")
        self.header.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(self.header)
        self.meta = QLabel("")
        self.meta.setStyleSheet("color:#64748b;")
        root.addWidget(self.meta)

        actions = QHBoxLayout()
        for text, slot, secondary in (
            ("Лист подбора", partial(self.picking_list, "summary"), True),
            ("Расширенный лист подбора", partial(self.picking_list, "extended"), True),
            ("Стикеры", self.print_stickers, False),
            ("Стикеры по категориям", self.stickers_by_category, True),
            ("Маркировка", self.open_kiz, False),
            ("Обновить статусы КИЗ", self.refresh_kiz_status, True),
            ("Проверка ШК", self.open_pick, False),
            ("Грузоместа", self.manage_trbx, True),
            ("Отменённые заказы", self.show_cancelled, True),
            ("QR поставки", self.print_qr, True),
            ("Портал ВБ", self.open_portal, True),
        ):
            btn = QPushButton(text)
            if secondary:
                btn.setStyleSheet(
                    "background:#fff;color:#1e293b;border:1px solid #cbd5e1;"
                )
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        actions.addStretch(1)
        # Wrap actions in a scroll-friendly row via nested layout if needed
        actions_wrap = QWidget()
        actions_wrap.setLayout(actions)
        root.addWidget(actions_wrap)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Заказ", "Артикул", "Тип", "Цена", "КИЗ", "Проверка"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.Close)
        if close_btn:
            close_btn.clicked.connect(self.accept)
        root.addWidget(buttons)

        self.reload()

    def reload(self) -> None:
        supply = self.orders.get_supply(self.source_id, self.supply_id)
        if not supply:
            QMessageBox.warning(self, "Поставка", "Не найдена локально")
            return
        self.header.setText(str(supply.get("name") or self.supply_id))
        self.meta.setText(
            "ID {} · {} · заказов {} · коробов {} · {}".format(
                self.supply_id,
                cargo_type_label(supply.get("cargo_type")) or "—",
                len(supply.get("order_ids") or []),
                len(supply.get("boxes") or []),
                supply_status_label(done=supply.get("done"), scan_dt=supply.get("scan_dt")),
            )
        )
        rows = self.orders.orders_in_supply(
            self.source_id, self.supply_id, api_key=self.api_key
        )
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("order_id"))))
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
        dlg.resize(640, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(
            QLabel("Найдено отменённых в поставке: {}".format(len(rows)))
        )
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Заказ", "Артикул", "Причина"])
        table.horizontalHeader().setStretchLastSection(True)
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
        dlg.resize(560, 480)
        lay = QVBoxLayout(dlg)
        table = QTableWidget(len(groups), 4)
        table.setHorizontalHeaderLabels(["", "Категория", "Товар", "Шт"])
        table.horizontalHeader().setStretchLastSection(True)
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
        self.resize(480, 400)
        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.amount = QSpinBox()
        self.amount.setRange(1, 100)
        self.amount.setValue(1)
        create = QPushButton("Создать")
        create.clicked.connect(self.create_boxes)
        refresh = QPushButton("Обновить")
        refresh.setStyleSheet("background:#fff;color:#1e293b;border:1px solid #cbd5e1;")
        refresh.clicked.connect(self.reload)
        delete = QPushButton("Удалить все")
        delete.setStyleSheet("background:#fff;color:#b91c1c;border:1px solid #fca5a5;")
        delete.clicked.connect(self.delete_all)
        stickers = QPushButton("Стикеры коробов")
        stickers.clicked.connect(self.print_stickers)
        bar.addWidget(QLabel("Кол-во"))
        bar.addWidget(self.amount)
        bar.addWidget(create)
        bar.addWidget(refresh)
        bar.addWidget(delete)
        bar.addWidget(stickers)
        root.addLayout(bar)
        self.list = QTableWidget(0, 1)
        self.list.setHorizontalHeaderLabels(["ID грузоместа"])
        self.list.horizontalHeader().setStretchLastSection(True)
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
