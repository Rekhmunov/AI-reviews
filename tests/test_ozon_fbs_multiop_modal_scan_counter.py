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
    assert "const OZON_FBS_MODAL_STATUS_FIRST_MS = 3000" in JS
    assert "function _ozonFbsPeerScanBurstBusy" in JS
    assert "function _ozonFbsPeerDomBusy" in JS
    assert "_ozonFbsPeerScanBurstBusy()" in JS
    assert "function _ozonFbsKizStartModalStatusPoll" in JS
    assert "function _ozonFbsKizStopModalStatusPoll" in JS
    assert "function _ozonFbsPickStartModalStatusPoll" in JS
    assert "function _ozonFbsPickStopModalStatusPoll" in JS
    assert "_ozonFbsKizStartModalStatusPoll()" in JS
    assert "_ozonFbsKizStopModalStatusPoll()" in JS
    assert "_ozonFbsPickStartModalStatusPoll()" in JS
    assert "_ozonFbsPickStopModalStatusPoll()" in JS
    # Poll must not treat resting sticker focus as busy.
    start = JS[
        JS.find("function _ozonFbsKizStartModalStatusPoll") : JS.find(
            "function _ozonFbsKizStickerIndexAdd"
        )
    ]
    assert "_ozonFbsPeerScanBurstBusy()" in start
    assert "_ozonFbsPeerDomBusy()" not in start
    assert "modalStatusBurstRetry" in start
    # Resting focus on top sticker/mark fields must not block tbody rebuild.
    dom_busy = JS[
        JS.find("function _ozonFbsPeerDomBusy") : JS.find(
            "function _ozonFbsPeerScanBusy"
        )
    ]
    assert 'id === "ozonFbsKizStickerScan"' in dom_busy
    assert 'id === "ozonFbsPickStickerScan"' in dom_busy


def test_pick_clear_keeps_verified_at_token() -> None:
    """Backend clear must bump pick_verified_at (not NULL) for peer unverify."""
    fn = PICK[
        PICK.find("def update_posting_pick_verify") : PICK.find(
            "def load_posting_barcodes_map"
        )
    ]
    assert "Always bump token" in fn or "always bump" in fn.lower()
    assert "saved_at if new_verified else None" not in fn
    merge = JS[
        JS.find("function _ozonFbsPickMergeRemoteIntoOpenModal") : JS.find(
            "function _ozonFbsPickStopModalStatusPoll"
        )
    ]
    assert "row.pick_verified_at = nextAt" in merge
    assert 'row.pick_verified_at = ""' not in merge


def test_peer_merge_requires_newer_saved_at() -> None:
    assert "function _ozonFbsPeerRemoteIsNewer" in JS
    merge = JS[
        JS.find("function _ozonFbsKizMergeRemoteIntoOpenModal") : JS.find(
            "function _ozonFbsKizStopModalStatusPoll"
        )
    ]
    assert "_ozonFbsPeerRemoteIsNewer" in merge
    pick = JS[
        JS.find("function _ozonFbsPickMergeRemoteIntoOpenModal") : JS.find(
            "function _ozonFbsPickStopModalStatusPoll"
        )
    ]
    assert "_ozonFbsPeerRemoteIsNewer" in pick


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
    assert "_ozonFbsPeerDomBusy()" in merge
    assert "peerDomRefreshPending = true" in merge
    assert "_ozonFbsPeerScheduleDomFlush()" in merge
    assert "_ozonFbsKizUpdateScanCounter()" in merge
    assert "_ozonFbsPeerFocusedPosting()" in merge
    assert "focusedPn" in merge


def test_com_scan_marks_peer_busy() -> None:
    deliver = JS[
        JS.find("function deliverOzonFbsComScan") : JS.find(
            "function _ozonFbsScanComFlushBuffer"
        )
    ]
    assert "_ozonFbsPeerNoteScanActivity()" in deliver
    assert "_ozonFbsContainerNoteScanActivity" in JS
    assert "ozonFbsKizImportText" in JS[
        JS.find("function _ozonFbsPeerIsScanInput") : JS.find(
            "const OZON_FBS_PEER_SCAN_BUSY_MS"
        )
    ]


def test_modal_status_poll_only_while_open() -> None:
    assert "_ozonFbsKizStartModalStatusPoll()" in JS
    assert "_ozonFbsKizStopModalStatusPoll()" in JS
    start = JS[
        JS.find("function _ozonFbsKizStartModalStatusPoll") : JS.find(
            "function _ozonFbsKizStickerIndexAdd"
        )
    ]
    assert "!_ozonFbsKizModalIsOpen()" in start
    assert "_ozonFbsKizStopModalStatusPoll()" in start
    close = JS[
        JS.find("async function closeOzonFbsKizModal") : JS.find(
            "async function closeOzonFbsKizModal"
        )
        + 400
    ]
    assert "_ozonFbsKizStopModalStatusPoll()" in close


def test_gm_status_refresh_skips_scan_busy_and_open_modals_only() -> None:
    assert "function runSupplyStatusRefreshForOpenModals" in BIND
    sched = BIND[
        BIND.find("function scheduleSupplyStatusRefresh") : BIND.find(
            "function modalDomOpen"
        )
    ]
    assert "isScanBusy()" in sched
    assert "scheduleSupplyStatusRefresh()" in sched  # re-arm until idle
    assert "_ozonFbsContainerIsScanBusy" in BIND
    assert "_ozonFbsContainerNoteScanActivity" in BIND
    scan_el = BIND[
        BIND.find("function isScanInputEl") : BIND.find("function bindScanActivityWatch")
    ]
    assert "ozonFbsKizMarkScan" in scan_el
    assert "ozon-fbs-container-input" in scan_el


def test_asset_cache_bumped_for_multiop_scan_counter() -> None:
    assert "ozon_fbs.js?v=191" in HTML
    assert "ozon_fbs_container_bind.js?v=37" in HTML
