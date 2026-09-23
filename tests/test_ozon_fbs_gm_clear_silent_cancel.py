"""Ozon FBS: after portal clears GM, silently refresh that posting status."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "ozon_fbs.js").read_text(encoding="utf-8")
BIND = (ROOT / "web_static" / "ozon_fbs_container_bind.js").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_gm_clear_triggers_silent_status_only() -> None:
    assert "statusCheckPns" in BIND
    assert "gmClearedByPortal" in BIND
    assert "_ozonFbsSilentRefreshPostingStatus" in BIND
    # No sync banner during background reconcile (distracts scanning).
    assert "Грузоместа синхронизированы с порталом Ozon" not in BIND


def test_silent_cancel_bumps_cancelled_without_modal() -> None:
    assert "function _ozonFbsApplyCancelledQuiet" in JS
    assert "window._ozonFbsSilentRefreshPostingStatus" in JS
    quiet = JS[JS.find("function _ozonFbsApplyCancelledQuiet") : JS.find("function _ozonFbsPatchCancelledRowDom")]
    assert "_ozonFbsPostingStatusRender" not in quiet
    assert "setInfo" not in quiet
    refresh = JS[
        JS.find("async function refreshOzonFbsModalPostingStatus") : JS.find(
            "function renderOzonFbsCancelledOrdersTable"
        )
    ]
    assert "opts.silent" in refresh or "opts && opts.silent" in refresh
    assert "_ozonFbsApplyCancelledQuiet" in refresh


def test_row_is_cancelled_checks_status_tab() -> None:
    block = JS[JS.find("function _ozonFbsRowIsCancelled") : JS.find("function _ozonFbsActiveModalRows")]
    assert 'tab === "cancelled"' in block
    assert 'status === "cancelled"' in block


def test_asset_cache_bumped() -> None:
    assert "ozon_fbs.js?v=195" in HTML
    assert "ozon_fbs_container_bind.js?v=37" in HTML


def test_reconcile_polls_while_modal_open() -> None:
    assert "const RECONCILE_POLL_MS = 120000" in BIND
    assert "const RECONCILE_MIN_GAP_MS" in BIND
    assert "function isScanBusy" in BIND
    assert "rowsHaveContainerBinds" in BIND
    assert "force: true" in BIND
    assert "function startReconcilePolling" in BIND
    assert "function stopReconcilePolling" in BIND
    assert "startReconcilePolling(mode)" in BIND
    # Stop on modal close so polling does not continue in background.
    close_fn = BIND[
        BIND.find("function clearActiveContainerOnModalClose") : BIND.find("function clearActiveContainerOnModalClose") + 200
    ]
    assert "stopReconcilePolling()" in close_fn
