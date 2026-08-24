"""Tests for Ozon FBS tab mapping and marketplace detection."""
from __future__ import annotations

import unittest

from review_processor.ozon_fbs import (
    compute_tab,
    is_ozon_fbs_marketplace,
    TAB_ARBITRATION,
    TAB_AWAITING_PACKAGING,
    TAB_CANCELLED,
    TAB_DELIVERED,
    TAB_DELIVERING,
)


class OzonFbsMappingTests(unittest.TestCase):
    def test_marketplace_detector(self) -> None:
        self.assertTrue(is_ozon_fbs_marketplace("ozon_fbs"))
        self.assertTrue(is_ozon_fbs_marketplace("OZON_FBS"))
        self.assertFalse(is_ozon_fbs_marketplace("ozon"))
        self.assertFalse(is_ozon_fbs_marketplace("wb"))

    def test_compute_tab(self) -> None:
        self.assertEqual(compute_tab("awaiting_packaging"), TAB_AWAITING_PACKAGING)
        self.assertEqual(compute_tab("delivering"), TAB_DELIVERING)
        self.assertEqual(compute_tab("delivered"), TAB_DELIVERED)
        self.assertEqual(compute_tab("cancelled"), TAB_CANCELLED)
        self.assertEqual(compute_tab("arbitration"), TAB_ARBITRATION)
        self.assertEqual(compute_tab("client_arbitration"), TAB_ARBITRATION)


if __name__ == "__main__":
    unittest.main()
