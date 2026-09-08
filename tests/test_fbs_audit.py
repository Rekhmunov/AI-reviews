"""Unit tests for structured FBS operator audit helper."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from review_processor import fbs_audit


class FbsAuditTests(unittest.TestCase):
    def test_mask_code_keeps_tail_and_length(self) -> None:
        masked = fbs_audit.mask_code("1234567890ABCDEF", keep_tail=4)
        self.assertIn("…CDEF", masked)
        self.assertIn("len=16", masked)
        self.assertNotIn("1234567890AB", masked)

    def test_codes_summary_empty_and_multi(self) -> None:
        self.assertEqual(fbs_audit.codes_summary([]), "n=0")
        one = fbs_audit.codes_summary(["abcdefghij"])
        self.assertTrue(one.startswith("n=1:"))
        multi = fbs_audit.codes_summary(["aaaabbbbcccc", "ddddeeeeffff"])
        self.assertTrue(multi.startswith("n=2:"))

    def test_audit_never_raises_and_emits_line(self) -> None:
        with self.assertLogs("review_processor.fbs_audit", level=logging.INFO) as cm:
            fbs_audit.audit(
                marketplace="ozon",
                action="container_bind",
                result="ok",
                user_id=7,
                source_id=18,
                posting_number="123-1",
                container_id=99,
            )
        self.assertTrue(any("mp=ozon" in x for x in cm.output))
        self.assertTrue(any("action=container_bind" in x for x in cm.output))
        self.assertTrue(any("posting=123-1" in x for x in cm.output))

    def test_audit_fail_uses_error_level(self) -> None:
        with self.assertLogs("review_processor.fbs_audit", level=logging.ERROR) as cm:
            fbs_audit.audit(
                marketplace="wb",
                action="marking_save",
                result="fail",
                order_id=42,
                error="WB timeout",
            )
        self.assertTrue(any("mp=wb" in x for x in cm.output))
        self.assertTrue(any("result=fail" in x for x in cm.output))

    def test_audit_swallows_logger_errors(self) -> None:
        with patch.object(fbs_audit._log, "info", side_effect=RuntimeError("boom")):
            fbs_audit.audit(marketplace="ozon", action="scan", result="ok")


if __name__ == "__main__":
    unittest.main()
