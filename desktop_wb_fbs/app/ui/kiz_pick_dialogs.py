# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from app.services.kiz_pick import KizService, PickVerifyService
from app.services.trbx_stickers import StickersService


class KizDialog(QDialog):
    """Маркировка: скан стикера → скан КИЗ → сохранение в WB meta/sgtin."""

    def __init__(
        self,
        kiz: KizService,
        source_id: int,
        api_key: str,
        supply_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super(KizDialog, self).__init__(parent)
        self.kiz = kiz
        self.source_id = source_id
        self.api_key = api_key
        self.supply_id = supply_id
        self.rows = []  # type: List[Dict[str, Any]]
        self.current = None  # type: Optional[Dict[str, Any]]
        self._sticker_map = {}  # type: Dict[str, Dict[str, Any]]

        self.setWindowTitle("Маркировка · {}".format(supply_id))
        self.resize(960, 680)
        self.setMinimumSize(800, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Маркировка")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        scan_row = QHBoxLayout()
        scan_row.setSpacing(12)
        sticker_lab = QLabel("Стикер")
        sticker_lab.setObjectName("fieldLabel")
        self.sticker_input = QLineEdit()
        self.sticker_input.setPlaceholderText("Сканирование стикера…")
        self.sticker_input.returnPressed.connect(self.on_sticker)
        mark_lab = QLabel("КИЗ")
        mark_lab.setObjectName("fieldLabel")
        self.mark_input = QLineEdit()
        self.mark_input.setPlaceholderText("Сканирование КИЗ (Data Matrix)…")
        self.mark_input.returnPressed.connect(self.on_mark)
        self.mark_input.setEnabled(False)
        scan_row.addWidget(sticker_lab)
        scan_row.addWidget(self.sticker_input, 1)
        scan_row.addWidget(mark_lab)
        scan_row.addWidget(self.mark_input, 2)
        root.addLayout(scan_row)

        self.info = QLabel("Загрузка…")
        self.info.setWordWrap(True)
        self.info.setObjectName("hint")
        root.addWidget(self.info)

        self.table = QTableWidget(0, 4)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(["Заказ", "Артикул", "Кодов", "Статус"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.itemSelectionChanged.connect(self.on_select_row)
        root.addWidget(self.table, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        save = QPushButton("Сохранить в WB")
        save.clicked.connect(self.save_current)
        save_all = QPushButton("Сохранить все локальные → WB")
        save_all.setObjectName("secondary")
        save_all.clicked.connect(self.save_all)
        bar.addWidget(save)
        bar.addWidget(save_all)
        bar.addStretch(1)
        root.addLayout(bar)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.load_rows()
        self.sticker_input.setFocus()

    def load_rows(self) -> None:
        try:
            self.rows = self.kiz.marking_rows(
                self.source_id, self.supply_id, self.api_key
            )
        except Exception as exc:
            self.info.setText("Ошибка загрузки: {}".format(exc))
            self.rows = []
            return
        # Enrich sticker numbers from WB stickers API
        try:
            stickers = StickersService(self.kiz.db).order_stickers_png(
                self.api_key, [int(r["order_id"]) for r in self.rows]
            )
            by_oid = {}
            for st in stickers:
                try:
                    oid = int(st.get("order_id"))
                except (TypeError, ValueError):
                    continue
                part_a = str(st.get("partA") or "")
                part_b = str(st.get("partB") or "")
                full = (part_a + part_b) if (part_a or part_b) else str(st.get("barcode") or "")
                by_oid[oid] = full
                if full:
                    self._sticker_map[full] = next(
                        (r for r in self.rows if int(r["order_id"]) == oid), None
                    )
                    if part_b:
                        self._sticker_map[part_b] = self._sticker_map[full]
            for r in self.rows:
                r["sticker_number"] = by_oid.get(int(r["order_id"]), "")
        except Exception:
            pass

        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            codes = [c for c in (r.get("kiz_codes") or []) if str(c).strip(" \t\r\n")]
            self.table.setItem(i, 0, QTableWidgetItem(str(r["order_id"])))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("article") or "")))
            self.table.setItem(i, 2, QTableWidgetItem(str(len(codes))))
            status = "WB" if r.get("kiz_wb_synced") else ("локально" if codes else "пусто")
            self.table.setItem(i, 3, QTableWidgetItem(status))
        self.info.setText(
            "Заказов с маркировкой: {}. Сканируйте стикер, затем КИЗ.".format(
                len(self.rows)
            )
        )
        if not self.rows:
            self.info.setText("В поставке нет заказов, требующих маркировки КИЗ")

    def on_select_row(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.rows):
            return
        self.current = self.rows[row]
        self.mark_input.setEnabled(True)
        self.mark_input.setFocus()

    def on_sticker(self) -> None:
        raw = self.sticker_input.text().replace(" ", "").strip()
        self.sticker_input.clear()
        if not raw:
            return
        found = self._sticker_map.get(raw)
        if not found:
            # try last 4 digits
            tail = raw[-4:] if len(raw) >= 4 else raw
            matches = [
                r
                for r in self.rows
                if str(r.get("sticker_number") or "").endswith(tail)
            ]
            if len(matches) == 1:
                found = matches[0]
            elif len(matches) > 1:
                self.info.setText("Несколько заказов с хвостом {} — отсканируйте полный стикер".format(tail))
                return
        if not found:
            self.info.setText("Стикер не найден: {}".format(raw))
            return
        self.current = found
        for i, r in enumerate(self.rows):
            if int(r["order_id"]) == int(found["order_id"]):
                self.table.selectRow(i)
                break
        self.info.setText(
            "Заказ {} · {} · сканируйте КИЗ".format(
                found["order_id"], found.get("article") or ""
            )
        )
        self.mark_input.setEnabled(True)
        self.mark_input.setFocus()

    def on_mark(self) -> None:
        if not self.current:
            self.info.setText("Сначала отсканируйте стикер")
            return
        code = self.mark_input.text()
        self.mark_input.clear()
        ok, err = self.kiz.validate_mark(
            code,
            self.current.get("skus") or [],
            bool(self.current.get("skip_kiz_gtin_check")),
        )
        if not ok:
            self.info.setText(err)
            return
        codes = [c for c in (self.current.get("kiz_codes") or []) if str(c).strip(" \t\r\n")]
        cleaned = code.strip(" \t\r\n").replace("\u2194", "\u001d")
        if cleaned in codes:
            self.info.setText("Этот КИЗ уже добавлен")
            return
        codes.append(cleaned)
        self.current["kiz_codes"] = codes
        self.kiz.save_local(
            self.source_id, int(self.current["order_id"]), codes, wb_synced=False
        )
        self.info.setText(
            "КИЗ сохранён локально для заказа {} ({} шт.)".format(
                self.current["order_id"], len(codes)
            )
        )
        self.load_rows()
        self.sticker_input.setFocus()

    def save_current(self) -> None:
        if not self.current:
            return
        try:
            self.kiz.save_to_wb(
                self.source_id,
                self.api_key,
                int(self.current["order_id"]),
                self.current.get("kiz_codes") or [],
            )
            self.info.setText("Сохранено в WB: заказ {}".format(self.current["order_id"]))
            self.load_rows()
        except Exception as exc:
            QMessageBox.critical(self, "Маркировка", str(exc))

    def save_all(self) -> None:
        errors = []
        for r in self.rows:
            codes = [c for c in (r.get("kiz_codes") or []) if str(c).strip(" \t\r\n")]
            if not codes:
                continue
            try:
                self.kiz.save_to_wb(
                    self.source_id, self.api_key, int(r["order_id"]), codes
                )
            except Exception as exc:
                errors.append("{}: {}".format(r["order_id"], exc))
        self.load_rows()
        if errors:
            QMessageBox.warning(self, "Маркировка", "\n".join(errors[:8]))
        else:
            self.info.setText("Все локальные коды отправлены в WB")


class PickDialog(QDialog):
    def __init__(
        self,
        pick: PickVerifyService,
        source_id: int,
        api_key: str,
        supply_id: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super(PickDialog, self).__init__(parent)
        self.pick = pick
        self.source_id = source_id
        self.api_key = api_key
        self.supply_id = supply_id
        self.rows = []  # type: List[Dict[str, Any]]
        self.current = None  # type: Optional[Dict[str, Any]]
        self._sticker_map = {}  # type: Dict[str, Dict[str, Any]]

        self.setWindowTitle("Проверка ШК · {}".format(supply_id))
        self.resize(960, 680)
        self.setMinimumSize(800, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("Проверка ШК")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        scan_row = QHBoxLayout()
        scan_row.setSpacing(12)
        sticker_lab = QLabel("Стикер")
        sticker_lab.setObjectName("fieldLabel")
        self.sticker_input = QLineEdit()
        self.sticker_input.setPlaceholderText("Сканирование стикера…")
        self.sticker_input.returnPressed.connect(self.on_sticker)
        sku_lab = QLabel("ШК")
        sku_lab.setObjectName("fieldLabel")
        self.sku_input = QLineEdit()
        self.sku_input.setPlaceholderText("Сканирование ШК товара…")
        self.sku_input.returnPressed.connect(self.on_sku)
        self.sku_input.setEnabled(False)
        scan_row.addWidget(sticker_lab)
        scan_row.addWidget(self.sticker_input, 1)
        scan_row.addWidget(sku_lab)
        scan_row.addWidget(self.sku_input, 1)
        root.addLayout(scan_row)

        self.info = QLabel("Загрузка…")
        self.info.setWordWrap(True)
        self.info.setObjectName("hint")
        root.addWidget(self.info)

        self.table = QTableWidget(0, 4)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels(["Заказ", "Артикул", "ШК заказа", "Проверен"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.load_rows()
        self.sticker_input.setFocus()

    def load_rows(self) -> None:
        try:
            self.rows = self.pick.rows(self.source_id, self.supply_id, self.api_key)
        except Exception as exc:
            self.info.setText("Ошибка: {}".format(exc))
            return
        try:
            stickers = StickersService(self.pick.db).order_stickers_png(
                self.api_key, [int(r["order_id"]) for r in self.rows]
            )
            for st in stickers:
                try:
                    oid = int(st.get("order_id"))
                except (TypeError, ValueError):
                    continue
                row = next((r for r in self.rows if int(r["order_id"]) == oid), None)
                if not row:
                    continue
                part_a = str(st.get("partA") or "")
                part_b = str(st.get("partB") or "")
                full = part_a + part_b
                row["sticker_number"] = full
                if full:
                    self._sticker_map[full] = row
                if part_b:
                    self._sticker_map[part_b] = row
        except Exception:
            pass
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(r["order_id"])))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("article") or "")))
            self.table.setItem(
                i, 2, QTableWidgetItem(", ".join(str(s) for s in (r.get("skus") or [])[:4]))
            )
            self.table.setItem(
                i, 3, QTableWidgetItem("да" if r.get("pick_verified") else "—")
            )
        self.info.setText(
            "Заказов без КИЗ: {}. Сканируйте стикер, затем ШК.".format(len(self.rows))
        )
        if not self.rows:
            self.info.setText("Нет заказов для проверки ШК")

    def on_sticker(self) -> None:
        raw = self.sticker_input.text().replace(" ", "").strip()
        self.sticker_input.clear()
        found = self._sticker_map.get(raw)
        if not found and len(raw) >= 4:
            tail = raw[-4:]
            matches = [
                r
                for r in self.rows
                if str(r.get("sticker_number") or "").endswith(tail)
            ]
            if len(matches) == 1:
                found = matches[0]
        if not found:
            self.info.setText("Стикер не найден")
            return
        self.current = found
        for i, r in enumerate(self.rows):
            if int(r["order_id"]) == int(found["order_id"]):
                self.table.selectRow(i)
                break
        self.info.setText(
            "Заказ {} · сканируйте ШК товара".format(found["order_id"])
        )
        self.sku_input.setEnabled(True)
        self.sku_input.setFocus()

    def on_sku(self) -> None:
        if not self.current:
            return
        code = self.sku_input.text().strip()
        self.sku_input.clear()
        ok, err = self.pick.validate_barcode(code, self.current.get("skus") or [])
        if not ok:
            self.info.setText(err)
            return
        self.pick.save(
            self.source_id, int(self.current["order_id"]), True, code
        )
        self.info.setText("Проверено: заказ {}".format(self.current["order_id"]))
        self.load_rows()
        self.sticker_input.setFocus()
