"""Ozon FBS sync pallet summary error reporting."""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from review_processor import ozon_fbs as oz


class OzonFbsSyncPalletErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        with oz._ozon_fbs_sync_lock:
            oz._ozon_fbs_sync_state.update(
                {
                    "in_progress": False,
                    "synced": 0,
                    "total": 0,
                    "message": "",
                    "errors": [],
                    "sources": [],
                    "pallet_summary": [],
                    "pallet_summary_error": "",
                    "cancel_requested": False,
                }
            )

    def test_sync_reports_pallet_summary_error_when_compute_fails(self) -> None:
        repo = MagicMock()

        sources = [
            {
                "source_id": 9,
                "name": "Ozon FBS",
                "client_id": "c",
                "api_key": "k",
            }
        ]

        with patch.object(
            oz,
            "sync_ozon_fbs_source",
            return_value={"postings": 3, "errors": [], "stopped": False},
        ), patch.object(
            oz, "compute_ozon_fbs_pallet_summary", side_effect=RuntimeError("db locked")
        ):
            ok, _msg = oz.start_sync_thread(repo=repo, user_id=1, sources=sources)
            self.assertTrue(ok)

            deadline = time.time() + 3.0
            while time.time() < deadline:
                st = oz.get_sync_state()
                if not st.get("in_progress"):
                    break
                time.sleep(0.02)

        st = oz.get_sync_state()
        self.assertFalse(st.get("in_progress"))
        self.assertIn("Не удалось рассчитать паллеты", str(st.get("pallet_summary_error") or ""))
        self.assertEqual(st.get("pallet_summary"), [])


if __name__ == "__main__":
    unittest.main()
