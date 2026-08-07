"""WB FBS cargo-place (trbx) create validation."""

import pytest

from review_processor.wb_fbs import WbFbsClient


def test_create_supply_boxes_rejects_bad_amount():
    client = WbFbsClient("dummy-key")
    with pytest.raises(ValueError, match="от 1 до 1000"):
        client.create_supply_boxes("WB-GI-1", 0)
    with pytest.raises(ValueError, match="от 1 до 1000"):
        client.create_supply_boxes("WB-GI-1", 1001)
    with pytest.raises(ValueError, match="ID поставки"):
        client.create_supply_boxes("", 1)


def test_ui_remaining_boxes_formula():
    # Mirror front-end: remaining = min(1000, max(1, orders+1) - existing)
    def remaining(orders: int, existing: int) -> int:
        max_total = max(1, orders + 1)
        return max(0, min(1000, max_total - existing))

    assert remaining(5, 0) == 6
    assert remaining(5, 2) == 4
    assert remaining(5, 6) == 0
    assert remaining(0, 0) == 1
