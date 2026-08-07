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
