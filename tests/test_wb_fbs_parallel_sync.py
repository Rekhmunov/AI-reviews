"""Parallel WB FBS multi-source sync — per-cabinet progress rows."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import review_processor.wb_fbs as wb_fbs


def _reset_sync_state() -> None:
    with wb_fbs._wb_fbs_sync_lock:
        wb_fbs._wb_fbs_sync_state.update(
            {
                "in_progress": False,
                "synced": 0,
                "total": 0,
                "message": "",
                "errors": [],
                "cancel_requested": False,
                "source_id": None,
                "source_ids": [],
                "sources": [],
                "pallet_summary": [],
                "pallet_summary_error": "",
            }
        )


def test_parallel_sync_runs_sources_concurrently_and_exposes_rows():
    _reset_sync_state()
    started = []
    barrier = {"n": 0}

    def fake_sync(repo, *, user_id, source_id, api_key, stop_requested, progress, lookback_days):
        started.append(source_id)
        barrier["n"] += 1
        # Wait until both workers have entered (proves overlap).
        deadline = time.time() + 2.0
        while barrier["n"] < 2 and time.time() < deadline:
            time.sleep(0.01)
        progress(f"каб {source_id}", 10 + source_id)
        time.sleep(0.05)
        return {"orders": 10 + source_id, "supplies": 1, "errors": [], "stopped": False}

    repo = MagicMock()
    repo.get_wb_fbs_auto_sync_settings.return_value = {"lookback_days": 3}
    repo.mark_wb_fbs_synced = MagicMock()

    sources = [
        {"source_id": 1, "api_key": "k1", "name": "Кабинет А FBS"},
        {"source_id": 2, "api_key": "k2", "name": "Кабинет Б FBS"},
    ]

    with patch.object(wb_fbs, "sync_wb_fbs_source", side_effect=fake_sync), patch.object(
        wb_fbs, "compute_wb_fbs_pallet_summary", return_value=[]
    ):
        ok, msg = wb_fbs.start_sync_thread(repo=repo, user_id=7, sources=sources)
        assert ok is True
        assert "2" in msg

        deadline = time.time() + 3.0
        while time.time() < deadline:
            st = wb_fbs.get_sync_state()
            if not st.get("in_progress"):
                break
            # Mid-flight: both rows should exist
            rows = st.get("sources") or []
            assert len(rows) == 2
            time.sleep(0.02)

        st = wb_fbs.get_sync_state()
        assert st.get("in_progress") is False
        assert "Готово" in str(st.get("message") or "")
        rows = {int(r["source_id"]): r for r in (st.get("sources") or [])}
        assert set(rows) == {1, 2}
        assert rows[1]["status"] == "done"
        assert rows[2]["status"] == "done"
        assert "Кабинет А" in rows[1]["name"]
        assert rows[1]["orders"] == 11
        assert rows[2]["orders"] == 12
        assert set(started) == {1, 2}
        repo.mark_wb_fbs_synced.assert_called_once()


def test_sync_reports_pallet_summary_error_when_compute_fails():
    _reset_sync_state()
    repo = MagicMock()
    repo.get_wb_fbs_auto_sync_settings.return_value = {"lookback_days": 3}
    repo.mark_wb_fbs_synced = MagicMock()

    sources = [{"source_id": 1, "api_key": "k1", "name": "Кабинет А FBS"}]

    def fake_sync(repo, *, user_id, source_id, api_key, stop_requested, progress, lookback_days):
        return {"orders": 5, "supplies": 1, "errors": [], "stopped": False}

    with patch.object(wb_fbs, "sync_wb_fbs_source", side_effect=fake_sync), patch.object(
        wb_fbs, "compute_wb_fbs_pallet_summary", side_effect=RuntimeError("db locked")
    ):
        ok, _msg = wb_fbs.start_sync_thread(repo=repo, user_id=7, sources=sources)
        assert ok is True

        deadline = time.time() + 3.0
        while time.time() < deadline:
            st = wb_fbs.get_sync_state()
            if not st.get("in_progress"):
                break
            time.sleep(0.02)

    st = wb_fbs.get_sync_state()
    assert st.get("in_progress") is False
    assert "Не удалось рассчитать паллеты" in str(st.get("pallet_summary_error") or "")
    assert st.get("pallet_summary") == []


def test_get_sync_state_deep_copies_sources():
    _reset_sync_state()
    with wb_fbs._wb_fbs_sync_lock:
        wb_fbs._wb_fbs_sync_state["sources"] = [
            {"source_id": 9, "name": "X", "status": "running", "message": "a"}
        ]
    snap = wb_fbs.get_sync_state()
    snap["sources"][0]["message"] = "mutated"
    with wb_fbs._wb_fbs_sync_lock:
        assert wb_fbs._wb_fbs_sync_state["sources"][0]["message"] == "a"
