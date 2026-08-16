"""Smoke tests for WB FBS ТСД page assets (no DB / web app boot required)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_static"
TEMPLATES = ROOT / "web_templates"
WEB_PY = ROOT / "review_processor" / "web.py"


def test_tsd_static_assets_exist() -> None:
    assert (STATIC / "wb_fbs_tsd.css").is_file()
    assert (STATIC / "wb_fbs_tsd.js").is_file()
    assert (TEMPLATES / "wb_fbs_tsd.html").is_file()


def test_tsd_template_boot_placeholders() -> None:
    html = (TEMPLATES / "wb_fbs_tsd.html").read_text(encoding="utf-8")
    assert "{{CAN_VIEW_WB_FBS_TSD}}" in html
    assert "{{IS_TENANT_OWNER}}" in html
    assert "{{SAFE_EMAIL}}" in html
    assert "/static/wb_fbs_tsd.js" in html
    assert "/static/wb_fbs_tsd.css" in html


def test_app_html_has_tsd_button_and_permission() -> None:
    app_html = (TEMPLATES / "app.html").read_text(encoding="utf-8")
    assert 'id="wbFbsTsdBtn"' in app_html
    assert "can_view_wb_fbs_tsd: {{CAN_VIEW_WB_FBS_TSD}}" in app_html
    assert "<th>ТСД</th>" in app_html
    # Button sits next to Вывод КИЗ
    kiz = app_html.find("wbFbsKizCirculationBtn")
    tsd = app_html.find("wbFbsTsdBtn")
    assert kiz > 0 and tsd > kiz


def test_app_js_collects_wb_fbs_tsd_permission() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'data-col="wb_fbs_tsd"' in script
    assert "can_view_wb_fbs_tsd" in script
    assert "wb_fbs_tsd: false" in script or "wb_fbs_tsd: false," in script
    assert "s.wb_fbs_tsd" in script


def test_web_py_has_tsd_routes_and_builder() -> None:
    src = WEB_PY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "build_wb_fbs_tsd_html" in names
    assert '/wb-fbs/tsd' in src
    assert "/api/wb-fbs/tsd/sources" in src
    assert "/api/wb-fbs/tsd/supplies/{supply_id}/kiz" in src
    assert "/api/wb-fbs/tsd/supplies/{supply_id}/pick-verify" in src
    assert "/api/wb-fbs/tsd/supplies/{supply_id}/summary" in src
    assert "def _can_view_wb_fbs_tsd" in src
    assert re.search(r'CAN_VIEW_WB_FBS_TSD["\']:\s*"true" if can_view_wb_fbs_tsd', src)


def test_tsd_js_uses_dedicated_api_prefix() -> None:
    js = (STATIC / "wb_fbs_tsd.js").read_text(encoding="utf-8")
    assert "/api/wb-fbs/tsd/" in js
    assert "local_only: true" in js
    assert "sticker_barcode" in js
    assert "sticker_part_a" in js
    assert "expected_saved_at" in js
    assert "expected_verified_at" in js
    assert "forceSaveByOrder" in js
    assert "RU_LAYOUT_TO_EN" in js
    assert "fixRuKeyboardLayout" in js
    assert "syncSourceSelectVisibility" in js
    assert 'state.route.view === "list"' in js


def test_web_py_tsd_summary_is_local_only() -> None:
    src = WEB_PY.read_text(encoding="utf-8")
    # Isolate the TSD summary handler body between its decorator and next TSD kiz route.
    start = src.find("def wb_fbs_tsd_supply_summary(")
    end = src.find("def wb_fbs_tsd_kiz_list(")
    assert start > 0 and end > start
    body = src[start:end]
    assert "build_tsd_hub_progress_from_local" in body
    assert "wb_detail.build_kiz_marking_payload" not in body
    assert "wb_detail.build_pick_verify_payload" not in body


def test_web_py_tsd_kiz_forces_local_only() -> None:
    src = WEB_PY.read_text(encoding="utf-8")
    # TSD KIZ save must force local_only (no WB push for warehouse role).
    assert 'row["local_only"] = True' in src or "row['local_only'] = True" in src
    assert "nav-wb-fbs-tsd" in src
    assert "build_tsd_hub_progress_from_local" in src
