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
    assert "ozon_fbs_mod.is_ozon_fbs_source" in src
    assert "build_ozon_tsd_hub_progress" in src
    assert re.search(r'CAN_VIEW_WB_FBS_TSD["\']:\s*"true" if can_view_wb_fbs_tsd', src)


def test_tsd_js_uses_dedicated_api_prefix() -> None:
    js = (STATIC / "wb_fbs_tsd.js").read_text(encoding="utf-8")
    assert "/api/wb-fbs/tsd/" in js
    assert "local_only: true" in js
    assert "isOzon()" in js
    assert "posting_number" in js
    assert "sourceOptionLabel" in js
    assert "sticker_barcode" in js
    assert "sticker_lower_barcode" in js
    assert "else if (bcLow && scanKey(bcLow) === rawKey)" in js
    assert "seenBc" in js
    assert "sticker_part_a" in js
    assert "expected_saved_at" in js
    assert "expected_verified_at" in js
    assert "forceSaveByOrder" in js
    assert "RU_LAYOUT_TO_EN" in js
    assert "fixRuKeyboardLayout" in js
    assert "syncSourceSelectVisibility" in js
    assert 'state.route.view === "list"' in js
    assert "Сохранить" in js
    assert "saveKizPushAll" in js
    assert "wireSaveButton" in js
    assert "tsd-save-btn" in (TEMPLATES / "wb_fbs_tsd.html").read_text(encoding="utf-8")
    assert "savePickLocalAll" in js
    assert "clearPick" in js
    assert "clear: clearPick" in js
    assert "noteSessionScanned" in js
    assert "renderScannedListHtml" in js
    assert "clearKizCodes" in js
    assert 'data-action="clear-scanned-all"' in js
    assert "clearKizCodes" in js
    assert 'data-action="clear-kiz-code"' not in js
    assert "orderBarcodesLabel" in js
    assert "tsd-product-barcodes" in js
    assert "formatBoldLastDigits" in js
    assert "tsd-sticker-tail" in js
    assert "КИЗ:" in js
    assert ">ШК:</span>" in js or "ШК:</span>" in js
    assert "Заказ:" in js
    assert "tsd-scanned-kv" in js
    assert "tsd-scanned-top" in js
    assert "tsd-scanned-details" in js
    assert "formatOzonPostingHtml" in js
    assert "tsd-posting-hi" in js
    assert "Отправление:" in js
    assert "Стикер:" in js
    assert "tsd-scanned-sticker" in js
    assert "clearScannedOrderAll" in js
    assert 'data-action="clear-scanned-all"' in js
    assert "tsd-scanned-item-ozon" in js
    assert "tsd-scanned-item-wb" in js
    assert "tsd-scanned-gm-code" in js
    assert ">ГМ:</span>" in js
    assert "containers/unbind" in js
    assert "Скан пишет КИЗ локально" not in js
    assert "Скан пишет ШК локально" not in js
    assert "Для 2-го КИЗ снова сканируйте стикер" in js
    assert "Этот КИЗ уже в этом заказе" in js
    assert "simple: true" in js
    assert 'title: "Товары с маркировкой"' in js
    assert 'title: "Товары без маркировки"' in js
    assert "Готовим сканирование…" not in js
    assert "Готово к сканированию" not in js
    # Concurrent PC save: adopt server on conflict — do not force-retry overwrite.
    assert "err.conflict = true" in js
    assert "opts._retry" not in js and "_retry: true" not in js
    assert "pendingKizClear" in js
    assert "hasPendingKizPush" in js
    assert "rowNeedsKizWbClear" in js
    assert "removeSessionScanned" in js
    assert "убран из списка" in js
    assert "kizHubToneSupplyId" in js
    # First × on a filled KIZ must dismiss the row (not leave «—» via noteSessionScanned).
    clear_body = js.split("async function clearKizCodes", 1)[1].split("function syncSourceSelectVisibility", 1)[0]
    assert "removeSessionScanned(id)" in clear_body
    assert "noteSessionScanned(oid)" not in clear_body
    assert "clear: true" in js
    assert "refreshHubKizStatus" in js
    assert "/kiz/status" in js
    assert "tsdKizRefreshBtn" in js
    assert "setKizHubTone" in js
    assert "tsdFilterBtn" in js
    assert "applyOrderFilters" in js
    assert "Заполненные" in (TEMPLATES / "wb_fbs_tsd.html").read_text(encoding="utf-8")
    html = (TEMPLATES / "wb_fbs_tsd.html").read_text(encoding="utf-8")
    assert 'id="tsdSearchBtn"' in html
    assert 'id="tsdFilterBtn"' in html
    assert 'id="tsdFilterSearchBtn"' in html
    assert 'id="tsdCloseBtn"' not in html
    assert 'id="tsdFilterErrors"' in html
    assert 'id="tsdOrderSearch"' in html
    assert 'id="tsdScrollTop"' in html
    assert "tsdFilterSearchBtn" in js
    assert "Standalone search icon only on supply list" in js
    assert "openOrderSearch" in js
    assert "openHeaderSearch" in js
    assert "applyListSearchFromHeader" in js
    assert "renderBrowseSheetHtml" in js
    assert "tsdBrowseSheet" in js
    assert "BROWSE_PAGE_SIZE" in js
    assert "Показать ещё" in js
    assert 'id="tsdSearch"' not in js
    assert "Поиск поставки…" in js
    assert 'view === "list"' in js or "view === \"list\"" in js
    assert "filterOrdersBySearch" in js
    assert "scrollToScanInput" in js
    assert "syncScrollTopFab" in js
    assert "renderOzonOrderCardBodyHtml" in js
    assert "renderOzonOrderCardHtml" in js
    assert "renderWbOrderCardHtml" in js
    # List (start) screen hides back-to-/app; hub/scan keep ←.
    assert "Start screen is the TSD entry point" in js
    css = (ROOT / "web_static" / "wb_fbs_tsd.css").read_text(encoding="utf-8")
    assert ".tsd-back[hidden]" in css
    html = (TEMPLATES / "wb_fbs_tsd.html").read_text(encoding="utf-8")
    assert 'id="tsdBackBtn"' in html
    assert 'href="/app"' not in html.split('id="tsdBackBtn"', 1)[1].split("</a>", 1)[0]
    chrome = js.split("function refreshScanChrome", 1)[1].split("function wireScannedList", 1)[0]
    assert "shouldShowBrowseSheet()" in chrome
    assert "openBrowseSheet({ keepLimit: true })" in chrome
    assert 'data-action="clear-kiz-all"' not in js
    list_body = js.split("function renderList", 1)[1].split("function renderHub", 1)[0]
    assert 'back.hidden = true' in list_body
    assert 'back.href = "/app"' not in list_body
    assert "tsd-scanned-item-wb" in js
    assert "Шаг 1" not in js
    assert "Шаг 2" not in js
    assert "selectable: true" in js
    assert "tsd-search-item-ozon" not in js
    assert "pick-search-order" in js
    assert "orderSearch" in js
    assert "applyOrderSearchEnter" in js
    assert 'id="tsdScanClear"' in js
    assert "tsd-scan-clear" in js
    assert "normalizeKizMark" in js
    assert "normalizeKizCodesList" in js
    assert "\\u2194" in js
    assert "\\u001D" in js


def test_web_py_has_tsd_kiz_status_route() -> None:
    src = WEB_PY.read_text(encoding="utf-8")
    assert "/api/wb-fbs/tsd/supplies/{supply_id}/kiz/status" in src
    assert "def wb_fbs_tsd_kiz_status(" in src
    assert "check_supply_kiz_status" in src


def test_web_py_has_tsd_pick_verify_status_route() -> None:
    src = WEB_PY.read_text(encoding="utf-8")
    assert "/api/wb-fbs/tsd/supplies/{supply_id}/pick-verify/status" in src
    assert "def wb_fbs_tsd_pick_verify_status(" in src
    assert "check_supply_pick_verify_status" in src


def test_tsd_js_has_pick_hub_refresh() -> None:
    js = (STATIC / "wb_fbs_tsd.js").read_text(encoding="utf-8")
    assert 'id="tsdPickSplit"' in js
    assert 'id="tsdPickRefreshBtn"' in js
    assert "refreshHubPickStatus" in js
    assert "setPickHubTone" in js
    assert "pick-verify/status" in js


def test_web_py_tsd_summary_matches_scan_without_full_payloads() -> None:
    src = WEB_PY.read_text(encoding="utf-8")
    # Isolate the TSD summary handler body between its decorator and next TSD kiz route.
    start = src.find("def wb_fbs_tsd_supply_summary(")
    end = src.find("def wb_fbs_tsd_kiz_list(")
    assert start > 0 and end > start
    body = src[start:end]
    assert "build_tsd_hub_progress" in body
    assert "wb_detail.build_kiz_marking_payload" not in body
    assert "wb_detail.build_pick_verify_payload" not in body
    # Must not regress to raw_json-only local counter.
    assert "build_tsd_hub_progress_from_local" not in body


def test_web_py_tsd_kiz_save_supports_local_and_wb() -> None:
    src = WEB_PY.read_text(encoding="utf-8")
    start = src.find("async def wb_fbs_tsd_kiz_save(")
    end = src.find("def wb_fbs_tsd_pick_verify_list(")
    assert start > 0 and end > start
    body = src[start:end]
    # Autosave keeps local_only from client; explicit Save can push to WB.
    assert 'row["local_only"] = bool(row.get("local_only"))' in body
    assert "only_local" in body
    assert "invalidate_supply_detail_cache" in body
    assert "nav-wb-fbs-tsd" in src
    assert "build_tsd_hub_progress" in src


def test_tsd_phone_camera_scan_button() -> None:
    """Phone camera control sits left of scan input; feeds onScanEnter."""
    js = (STATIC / "wb_fbs_tsd.js").read_text(encoding="utf-8")
    css = (STATIC / "wb_fbs_tsd.css").read_text(encoding="utf-8")
    html = (TEMPLATES / "wb_fbs_tsd.html").read_text(encoding="utf-8")
    assert "tsdScanCamBtn" in js
    assert "tsd-scan-cam-btn" in js
    assert "function openPhoneCamScan" in js
    assert "function closePhoneCamScan" in js
    assert "BarcodeDetector" in js
    assert "BrowserMultiFormatReader" in js
    # Real ZXing 0.21 API on an already-playing video element.
    assert "reader.decodeOnce(video" in js
    assert "stopAsyncDecode" in js
    assert "onScanEnter(input)" in js
    assert "getUserMedia" in js
    assert "isSecureContext" in js
    assert ".tsd-cam-overlay" in css
    assert "flex: 0 0 56px" in css
    assert "wb_fbs_tsd.js?v=73" in html
    # Self-hosted ZXing (CSP blocks CDN script-src on iPhone Safari).
    assert (STATIC / "zxing.min.js").is_file()
    assert "/static/zxing.min.js" in js
    assert "cdn.jsdelivr.net" not in js
    assert "function outboxSoftStatus" in js
    assert "outboxCache" in js
    # Scan path: UI/focus first, then outbox+network (speed).
    enter = js[js.find("async function onScanEnter") : js.find("async function onRoute")]
    marker = "After UI/focus: durable outbox"
    assert marker in enter
    assert enter.find("patchScanAfterSuccess(mode, input)") < enter.find(marker)
    assert enter.find(marker) < enter.find('if (mode === "kiz") scheduleKizLocalAutosave(rowId)')
    assert "await saveKizLocal" not in enter
    assert "await outbox" not in enter
    assert "outboxRescheduleCurrent" in js
    # visibility reconnect is debounced so focus blips do not stall scanning
    assert "outboxRescheduleTimer" in js
    # Ozon GM bind/unbind must also be durable offline.
    assert "function outboxRememberGmBind" in js
    assert "function outboxRememberGmUnbind" in js
    assert "function outboxApplyGmToLoadedRows" in js
    assert "function outboxFlushGmPending" in js
    assert "outboxRememberGmBind(row" in js
    assert 'outboxRemove("gm"' in js
    assert "wb_fbs_tsd.css?v=40" in html
    # Camera button rendered before scan field in the same row.
    row_fn = js[js.find("function scanFieldRowHtml") : js.find("function scanFieldRowHtml") + 900]
    assert "tsdScanCamBtn" in row_fn
    assert row_fn.find("tsdScanCamBtn") < row_fn.find("tsdScanInput")
    # Same control class/size as GM side icons.
    assert "tsd-gm-icon-btn" in row_fn


def test_tsd_durable_outbox_survives_offline() -> None:
    """Pending KIZ/pick scans must be stored in localStorage and flushed on online."""
    js = (STATIC / "wb_fbs_tsd.js").read_text(encoding="utf-8")
    html = (TEMPLATES / "wb_fbs_tsd.html").read_text(encoding="utf-8")
    assert 'LS_OUTBOX = "wb_fbs_tsd_outbox_v1"' in js
    for name in (
        "outboxRememberKiz",
        "outboxRememberPick",
        "outboxApplyToLoadedRows",
        "outboxRescheduleCurrent",
        "wireOutboxReconnect",
        "outboxRemove",
        "outboxHasPending",
    ):
        assert f"function {name}" in js
    assert 'addEventListener("online"' in js
    assert "outboxRememberKiz(row)" in js
    assert "outboxRememberPick(row)" in js
    assert 'outboxRemove("kiz"' in js
    assert 'outboxRemove("pick"' in js
    assert "outboxApplyToLoadedRows(state.route.mode)" in js
    assert "wireOutboxReconnect()" in js
    assert "Нет связи — скан сохранён на устройстве" in js
    assert "wb_fbs_tsd.js?v=73" in html
    assert "function outboxSoftStatus" in js
    assert "outboxCache" in js
    # Scan path: UI/focus first, then outbox+network (speed).
    enter = js[js.find("async function onScanEnter") : js.find("async function onRoute")]
    marker = "After UI/focus: durable outbox"
    assert marker in enter
    assert enter.find("patchScanAfterSuccess(mode, input)") < enter.find(marker)
    assert enter.find(marker) < enter.find('if (mode === "kiz") scheduleKizLocalAutosave(rowId)')
    assert "await saveKizLocal" not in enter
    assert "await outbox" not in enter
    assert "outboxRescheduleCurrent" in js
    # visibility reconnect is debounced so focus blips do not stall scanning
    assert "outboxRescheduleTimer" in js
    # Ozon GM bind/unbind must also be durable offline.
    assert "function outboxRememberGmBind" in js
    assert "function outboxRememberGmUnbind" in js
    assert "function outboxApplyGmToLoadedRows" in js
    assert "function outboxFlushGmPending" in js
    assert "outboxRememberGmBind(row" in js
    assert 'outboxRemove("gm"' in js
