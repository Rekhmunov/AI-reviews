"""Ozon FBS: peer scans must update open-modal KIZ/ШК fill counters."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
BIND = (ROOT / "web_static" / "ozon_fbs_container_bind.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
MARK = (ROOT / "review_processor" / "ozon_fbs_marking.py").read_text(encoding="utf-8")
PICK = (ROOT / "review_processor" / "ozon_fbs_pick_verify.py").read_text(encoding="utf-8")


def test_marking_status_includes_saved_at_for_peer_sync() -> None:
    block = MARK[
        MARK.find("def check_supply_marking_status") : MARK.find(
            "def check_supply_marking_status"
        )
        + 4500
    ]
    assert '"kiz_saved_at"' in block or "'kiz_saved_at'" in block


def test_pick_status_includes_verified_at_for_peer_sync() -> None:
    block = PICK[
        PICK.find("def check_supply_pick_verify_status") : PICK.find(
            "def check_supply_pick_verify_status"
        )
        + 3500
    ]
    assert '"pick_verified_at"' in block or "'pick_verified_at'" in block


def test_kiz_modal_merges_remote_status_into_open_rows() -> None:
    assert "function _ozonFbsKizMergeRemoteIntoOpenModal" in JS
    refresh = JS[
        JS.find("async function refreshOzonFbsMarkingStatus") : JS.find(
            "async function refreshOzonFbsMarkingStatus"
        )
        + 2200
    ]
    assert "_ozonFbsKizMergeRemoteIntoOpenModal" in refresh
    merge = JS[
        JS.find("function _ozonFbsKizMergeRemoteIntoOpenModal") : JS.find(
            "function _ozonFbsKizStopModalStatusPoll"
        )
    ]
    assert "_ozonFbsKizUpdateScanCounter()" in merge
    assert "localAutosaveDirty" in merge
    assert "_ozonFbsKizBaselineEquals" in merge


def test_pick_modal_merges_remote_status_into_open_rows() -> None:
    assert "function _ozonFbsPickMergeRemoteIntoOpenModal" in JS
    refresh = JS[
        JS.find("async function refreshOzonFbsPickVerifyStatus") : JS.find(
            "async function refreshOzonFbsPickVerifyStatus"
        )
        + 1800
    ]
    assert "_ozonFbsPickMergeRemoteIntoOpenModal" in refresh
    merge = JS[
        JS.find("function _ozonFbsPickMergeRemoteIntoOpenModal") : JS.find(
            "function _ozonFbsPickStopModalStatusPoll"
        )
    ]
    assert "_ozonFbsPickUpdateScanCounter()" in merge
    assert "_ozonFbsPickBaselineEquals" in merge


def test_modal_status_poll_while_open() -> None:
    assert "const OZON_FBS_MODAL_STATUS_POLL_MS = 20000" in JS
    assert "const OZON_FBS_MODAL_STATUS_MIN_GAP_MS = 15000" in JS
    assert "function _ozonFbsPeerScanBusy" in JS
    assert "_ozonFbsPeerScanBusy()" in JS
    assert "function _ozonFbsKizStartModalStatusPoll" in JS
    assert "function _ozonFbsKizStopModalStatusPoll" in JS
    assert "function _ozonFbsPickStartModalStatusPoll" in JS
    assert "function _ozonFbsPickStopModalStatusPoll" in JS
    assert "_ozonFbsKizStartModalStatusPoll()" in JS
    assert "_ozonFbsKizStopModalStatusPoll()" in JS
    assert "_ozonFbsPickStartModalStatusPoll()" in JS
    assert "_ozonFbsPickStopModalStatusPoll()" in JS


def test_gm_reconcile_triggers_status_refresh_for_fill_counters() -> None:
    merge = BIND[
        BIND.find("function mergeReconcileBinds") : BIND.find(
            "async function reconcileContainers"
        )
    ]
    assert "scheduleSupplyStatusRefresh()" in merge


def test_peer_merge_defers_table_rebuild_while_scanning() -> None:
    merge = JS[
        JS.find("function _ozonFbsKizMergeRemoteIntoOpenModal") : JS.find(
            "function _ozonFbsKizStopModalStatusPoll"
        )
    ]
    assert "_ozonFbsPeerScanBusy()" in merge
    assert "peerDomRefreshPending = true" in merge
    assert "_ozonFbsPeerScheduleDomFlush()" in merge
    assert "_ozonFbsKizUpdateScanCounter()" in merge


def test_gm_status_refresh_skips_scan_busy_and_open_modals_only() -> None:
    assert "function runSupplyStatusRefreshForOpenModals" in BIND
    assert "isScanBusy()" in BIND[
        BIND.find("function scheduleSupplyStatusRefresh") : BIND.find(
            "function modalDomOpen"
        )
    ]
    assert "_ozonFbsContainerIsScanBusy" in BIND


def test_asset_cache_bumped_for_multiop_scan_counter() -> None:
    assert "ozon_fbs.js?v=176" in HTML
    assert "ozon_fbs_container_bind.js?v=34" in HTML
