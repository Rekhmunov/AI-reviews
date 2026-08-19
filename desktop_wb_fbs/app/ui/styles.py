# -*- coding: utf-8 -*-
"""App stylesheet — restrained, Win7-friendly (no fancy effects)."""

APP_QSS = """
QWidget {
    font-family: "Segoe UI", "Tahoma", sans-serif;
    font-size: 13px;
    color: #1e293b;
}
QMainWindow, QDialog {
    background: #f1f5f9;
}
QFrame#navPanel {
    background: #0f172a;
    min-width: 200px;
    max-width: 220px;
}
QPushButton.navBtn {
    background: transparent;
    color: #cbd5e1;
    border: none;
    text-align: left;
    padding: 12px 16px;
    font-size: 14px;
}
QPushButton.navBtn:hover {
    background: #1e293b;
    color: #f8fafc;
}
QPushButton.navBtn:checked {
    background: #1d4ed8;
    color: #ffffff;
}
QLabel#brandTitle {
    color: #f8fafc;
    font-size: 16px;
    font-weight: 600;
    padding: 20px 16px 8px 16px;
}
QLabel#brandSub {
    color: #94a3b8;
    font-size: 12px;
    padding: 0 16px 16px 16px;
}
QPushButton {
    background: #2563eb;
    color: white;
    border: 1px solid #1d4ed8;
    border-radius: 4px;
    padding: 8px 14px;
    min-height: 28px;
}
QPushButton:hover {
    background: #1d4ed8;
}
QPushButton:pressed {
    background: #1e40af;
}
QPushButton:disabled {
    background: #94a3b8;
    border-color: #94a3b8;
    color: #e2e8f0;
}
QPushButton.secondary {
    background: #ffffff;
    color: #1e293b;
    border: 1px solid #cbd5e1;
}
QPushButton.secondary:hover {
    background: #f8fafc;
}
QPushButton.danger {
    background: #ffffff;
    color: #b91c1c;
    border: 1px solid #fca5a5;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 6px 8px;
    min-height: 28px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #2563eb;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    gridline-color: #e2e8f0;
    selection-background-color: #dbeafe;
    selection-color: #0f172a;
}
QHeaderView::section {
    background: #f8fafc;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    border-right: 1px solid #e2e8f0;
    padding: 8px;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    background: #ffffff;
}
QTabBar::tab {
    background: #e2e8f0;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background: #ffffff;
    border-bottom: 2px solid #2563eb;
}
QGroupBox {
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 12px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QStatusBar {
    background: #e2e8f0;
}
QLabel.hint {
    color: #64748b;
    font-size: 12px;
}
"""
