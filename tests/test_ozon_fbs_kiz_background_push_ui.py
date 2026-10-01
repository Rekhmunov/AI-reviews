"""UI contract: KIZ scan stays local_only; Ozon push is fire-and-forget."""

from __future__ import annotations

from pathlib import Path

OZON_JS = Path(__file__).resolve().parents[1] / "web_static" / "ozon_fbs.js"


def test_kiz_scan_autosave_stays_local_only() -> None:
    text = OZON_JS.read_text(encoding="utf-8")
    assert "local_only: true" in text
    assert "function _ozonFbsKizScheduleLocalAutosave" in text
    assert "Persists to FeedPilot only" in text
    assert "never waits on Ozon API" in text


def test_background_ozon_push_after_local_autosave() -> None:
    text = OZON_JS.read_text(encoding="utf-8")
    assert "function _ozonFbsKizScheduleBackgroundOzonPush" in text
    assert "_ozonFbsKizScheduleBackgroundOzonPush(pn)" in text
    assert "row.gtd_required" in text
    # Must not block the scan path on Ozon.
    assert "Do not await from the scan path" in text
    assert "local_only: false" in text
    # Serialize per posting so an older in-flight push cannot overwrite newer codes.
    assert "bgOzonPushChainByPosting" in text
    assert "bgOzonPushSeqByPosting" in text
