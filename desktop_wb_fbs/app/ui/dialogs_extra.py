# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from app.db import Database
from app.services.orders import OrdersService
from app.services.trbx_stickers import StickersService
from app.wb import default_mgt_supply_name


def show_png_list(
    pngs: List[bytes], title: str, parent: Optional[QWidget] = None
) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(520, 640)
    root = QVBoxLayout(dlg)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    wrap = QWidget()
    lay = QVBoxLayout(wrap)
    for raw in pngs:
        lab = QLabel()
        pix = QPixmap()
        pix.loadFromData(raw)
        lab.setPixmap(pix.scaledToWidth(400, Qt.SmoothTransformation))
        lay.addWidget(lab)
    lay.addStretch(1)
    scroll.setWidget(wrap)
    root.addWidget(scroll)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dlg.reject)
    root.addWidget(buttons)
    dlg.exec_()


def show_order_stickers(
    api_key: str, order_ids: List[int], parent: Optional[QWidget] = None
) -> None:
    svc = StickersService(Database())  # stickers don't need DB
    items = svc.order_stickers_png(api_key, order_ids)
    pngs = [it["png"] for it in items if it.get("png")]
    if not pngs:
        raise RuntimeError("WB не вернул стикеры")
    show_png_list(pngs, "Стикеры заказов ({})".format(len(pngs)), parent)


def show_supply_qr(
    api_key: str, supply_id: str, parent: Optional[QWidget] = None
) -> None:
    svc = StickersService(Database())
    png = svc.supply_qr_png(api_key, supply_id)
    show_png_list([png], "QR поставки {}".format(supply_id), parent)


class AutoSyncDialog(QDialog):
    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super(AutoSyncDialog, self).__init__(parent)
        self.db = db
        self.setWindowTitle("Автоматика WB FBS")
        form = QFormLayout(self)
        self.lookback = QSpinBox()
        self.lookback.setRange(1, 30)
        self.lookback.setValue(int(db.get_setting("sync_lookback_days", "3") or 3))
        self.auto_sync = QCheckBox("Автосинхронизация")
        self.auto_sync.setChecked(db.get_setting("auto_sync_enabled") == "1")
        self.sync_interval = QSpinBox()
        self.sync_interval.setRange(15, 24 * 60)
        self.sync_interval.setValue(
            int(db.get_setting("auto_sync_interval_minutes", "60") or 60)
        )
        self.sync_from = QLineEdit(db.get_setting("auto_sync_active_from", "09:00"))
        self.sync_to = QLineEdit(db.get_setting("auto_sync_active_to", "21:00"))
        self.auto_mgt = QCheckBox("Автосбор МГТ")
        self.auto_mgt.setChecked(db.get_setting("auto_collect_mgt_enabled") == "1")
        self.mgt_interval = QSpinBox()
        self.mgt_interval.setRange(15, 24 * 60)
        self.mgt_interval.setValue(
            int(db.get_setting("auto_collect_mgt_interval_minutes", "60") or 60)
        )
        self.mgt_from = QLineEdit(db.get_setting("auto_collect_mgt_active_from", "09:00"))
        self.mgt_to = QLineEdit(db.get_setting("auto_collect_mgt_active_to", "21:00"))
        form.addRow("Глубина sync (дней)", self.lookback)
        form.addRow(self.auto_sync)
        form.addRow("Интервал sync (мин)", self.sync_interval)
        form.addRow("Окно MSK с", self.sync_from)
        form.addRow("Окно MSK по", self.sync_to)
        form.addRow(self.auto_mgt)
        form.addRow("Интервал МГТ (мин)", self.mgt_interval)
        form.addRow("МГТ MSK с", self.mgt_from)
        form.addRow("МГТ MSK по", self.mgt_to)
        note = QLabel(
            "Планировщик автоматики в этой версии сохраняет настройки; "
            "фоновый таймер можно включить в следующих итерациях."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b;")
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def save(self) -> None:
        self.db.set_setting("sync_lookback_days", str(self.lookback.value()))
        self.db.set_setting(
            "auto_sync_enabled", "1" if self.auto_sync.isChecked() else "0"
        )
        self.db.set_setting(
            "auto_sync_interval_minutes", str(self.sync_interval.value())
        )
        self.db.set_setting("auto_sync_active_from", self.sync_from.text().strip())
        self.db.set_setting("auto_sync_active_to", self.sync_to.text().strip())
        self.db.set_setting(
            "auto_collect_mgt_enabled", "1" if self.auto_mgt.isChecked() else "0"
        )
        self.db.set_setting(
            "auto_collect_mgt_interval_minutes", str(self.mgt_interval.value())
        )
        self.db.set_setting(
            "auto_collect_mgt_active_from", self.mgt_from.text().strip()
        )
        self.db.set_setting("auto_collect_mgt_active_to", self.mgt_to.text().strip())
        self.accept()


class CollectMgtDialog(QDialog):
    def __init__(
        self,
        db: Database,
        orders: OrdersService,
        source: Dict[str, Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        super(CollectMgtDialog, self).__init__(parent)
        self.db = db
        self.orders = orders
        self.source = source
        self.setWindowTitle("Собрать все МГТ")
        self.resize(520, 400)
        root = QVBoxLayout(self)
        self.lead = QLabel("Группы МГТ-заказов (склад × B2B):")
        root.addWidget(self.lead)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        root.addWidget(self.body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Собрать")
        buttons.accepted.connect(self.do_collect)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.groups = self._plan()
        lines = []
        for g in self.groups:
            lines.append(
                "· склад {} · {} · заказов {}".format(
                    g["warehouse_id"],
                    "B2B" if g["is_b2b"] else "retail",
                    len(g["order_ids"]),
                )
            )
        self.body.setText("\n".join(lines) if lines else "Нет МГТ в «Новых»")
        if not lines:
            buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    def _plan(self) -> List[Dict[str, Any]]:
        rows = self.orders.new_mgt_orders(int(self.source["id"]))
        buckets = defaultdict(list)  # type: Dict[Any, List[int]]
        meta = {}  # type: Dict[Any, Dict[str, Any]]
        for r in rows:
            key = (r.get("warehouse_id"), bool(int(r.get("is_b2b") or 0)))
            buckets[key].append(int(r["order_id"]))
            meta[key] = {
                "warehouse_id": r.get("warehouse_id"),
                "is_b2b": bool(int(r.get("is_b2b") or 0)),
                "cargo_type": 1,
            }
        out = []
        for key, oids in buckets.items():
            m = meta[key]
            out.append(
                {
                    "warehouse_id": m["warehouse_id"],
                    "is_b2b": m["is_b2b"],
                    "cargo_type": 1,
                    "order_ids": oids,
                    "name": default_mgt_supply_name(is_b2b=m["is_b2b"]),
                }
            )
        return out

    def do_collect(self) -> None:
        try:
            for g in self.groups:
                self.orders.create_supply_from_orders(
                    int(self.source["id"]),
                    str(self.source["api_key"]),
                    g["order_ids"],
                    g["name"],
                )
            QMessageBox.information(
                self, "МГТ", "Создано поставок: {}".format(len(self.groups))
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "МГТ", str(exc))


class SelectionSupplyDialog(QDialog):
    def __init__(
        self,
        orders: OrdersService,
        source: Dict[str, Any],
        order_ids: List[int],
        mode: str = "create",
        parent: Optional[QWidget] = None,
    ) -> None:
        super(SelectionSupplyDialog, self).__init__(parent)
        self.orders = orders
        self.source = source
        self.order_ids = order_ids
        self.mode = mode
        self.setWindowTitle(
            "Новая поставка" if mode == "create" else "Добавить к поставке"
        )
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Заказов: {}".format(len(order_ids))))

        # Load order traits
        sid = int(source["id"])
        with orders.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM wb_fbs_orders
                WHERE source_id = ? AND order_id IN ({})
                """.format(
                    ",".join("?" for _ in order_ids)
                ),
                [sid] + list(order_ids),
            ).fetchall()
        items = [dict(r) for r in rows]
        cargos = {int(r.get("cargo_type") or 0) for r in items}
        b2bs = {bool(int(r.get("is_b2b") or 0)) for r in items}
        whs = {r.get("warehouse_id") for r in items}
        errors = []
        if len(cargos) > 1:
            errors.append("Нельзя смешивать типы груза (МГТ/СГТ/КГТ+)")
        if len(b2bs) > 1:
            errors.append("Нельзя смешивать B2B и розницу")
        if len(whs) > 1:
            errors.append("Нельзя смешивать склады")
        self.err = QLabel("\n".join(errors))
        self.err.setStyleSheet("color:#b91c1c;")
        root.addWidget(self.err)

        self.name_edit = QLineEdit(
            default_mgt_supply_name(is_b2b=bool(next(iter(b2bs), False)))
        )
        self.supply_combo = QComboBox()
        if mode == "create":
            root.addWidget(QLabel("Название поставки"))
            root.addWidget(self.name_edit)
        else:
            root.addWidget(QLabel("Открытая совместимая поставка"))
            root.addWidget(self.supply_combo)
            cargo = next(iter(cargos), 0)
            is_b2b = bool(next(iter(b2bs), False))
            wh = next(iter(whs), None)
            for s in orders.open_compatible_supplies(sid, cargo, is_b2b, wh):
                self.supply_combo.addItem(
                    "{} · {} зак.".format(s.get("name") or s.get("supply_id"), s.get("order_count")),
                    str(s.get("supply_id")),
                )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.do_ok)
        buttons.rejected.connect(self.reject)
        if errors:
            buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        if mode == "add" and self.supply_combo.count() == 0:
            buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            self.err.setText((self.err.text() + "\nНет совместимых открытых поставок").strip())
        root.addWidget(buttons)

    def do_ok(self) -> None:
        try:
            sid = int(self.source["id"])
            key = str(self.source["api_key"])
            if self.mode == "create":
                self.orders.create_supply_from_orders(
                    sid, key, self.order_ids, self.name_edit.text().strip()
                )
            else:
                supply_id = str(self.supply_combo.currentData() or "")
                if not supply_id:
                    raise ValueError("Выберите поставку")
                self.orders.add_orders_to_existing_supply(
                    sid, key, supply_id, self.order_ids
                )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Поставка", str(exc))
