# -*- coding: utf-8 -*-
from __future__ import annotations

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import APP_NAME, __version__
from app.db import Database
from app.services import SourceService
from app.services.catalog import CategoryService, ProductService
from app.services.orders import OrdersService
from app.ui.fbs_page import FbsPage
from app.ui.settings_page import SettingsPage
from app.ui.styles import APP_QSS


class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        super(MainWindow, self).__init__()
        self.db = db
        self.sources = SourceService(db)
        self.products = ProductService(db)
        self.categories = CategoryService(db)
        self.orders = OrdersService(db)

        self.setWindowTitle("{} — Поставки ВБ ФБС".format(APP_NAME))
        self.resize(1200, 760)
        self.setMinimumSize(960, 600)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav = QFrame()
        nav.setObjectName("navPanel")
        nav_l = QVBoxLayout(nav)
        nav_l.setContentsMargins(0, 0, 0, 0)
        nav_l.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brandTitle")
        sub = QLabel("Локально · WB API · v{}".format(__version__))
        sub.setObjectName("brandSub")
        nav_l.addWidget(brand)
        nav_l.addWidget(sub)

        self.btn_fbs = QPushButton("Поставки ВБ ФБС")
        self.btn_fbs.setCheckable(True)
        self.btn_fbs.setProperty("class", "navBtn")
        self.btn_fbs.setObjectName("navBtn")
        self.btn_fbs.setStyleSheet(
            "QPushButton { text-align: left; padding: 12px 16px; border: none;"
            " background: transparent; color: #cbd5e1; }"
            "QPushButton:checked { background: #1d4ed8; color: white; }"
            "QPushButton:hover { background: #1e293b; color: white; }"
        )
        self.btn_settings = QPushButton("Настройки")
        self.btn_settings.setCheckable(True)
        self.btn_settings.setStyleSheet(self.btn_fbs.styleSheet())
        nav_l.addWidget(self.btn_fbs)
        nav_l.addWidget(self.btn_settings)
        nav_l.addStretch(1)
        layout.addWidget(nav)

        self.stack = QStackedWidget()
        self.fbs_page = FbsPage(db, self.sources, self.orders)
        self.settings_page = SettingsPage(
            db, self.sources, self.products, self.categories
        )
        self.stack.addWidget(self.fbs_page)
        self.stack.addWidget(self.settings_page)
        layout.addWidget(self.stack, 1)

        self.btn_fbs.clicked.connect(lambda: self._show(0))
        self.btn_settings.clicked.connect(lambda: self._show(1))
        self.settings_page.sources_changed.connect(self.fbs_page.reload_sources)
        self._show(0)
        self.statusBar().showMessage("Готово · данные локально · только API Wildberries")

    def _show(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.btn_fbs.setChecked(index == 0)
        self.btn_settings.setChecked(index == 1)
        if index == 0:
            self.fbs_page.reload_sources()


def run() -> int:
    # High-DPI friendly on Win10+, harmless on Win7
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)

    db = Database()
    db.init_schema()

    win = MainWindow(db)
    win.show()
    return app.exec_()
