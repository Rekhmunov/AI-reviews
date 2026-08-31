"""Final marking save must skip redundant Ozon pushes after autosave."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor.ozon_fbs_marking import save_marking


def test_save_marking_local_only_skips_ozon_push_even_when_gtd() -> None:
    codes = ["010460123456789021ABC"]
    gtd = "10000000/010126/1234567"
    with (
        patch(
            "review_processor.ozon_fbs_marking._load_posting_cancelled_map",
            return_value={},
        ),
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={
                "P-1": {
                    "codes": [],
                    "saved_at": "",
                    "ozon_synced": False,
                    "gtd_number": "",
                }
            },
        ),
        patch(
            "review_processor.ozon_fbs_marking._load_posting_row",
            return_value={
                "posting_number": "P-1",
                "marking_gtd_number": gtd,
                "raw_json": "{}",
            },
        ),
        patch(
            "review_processor.ozon_fbs_marking.oz.posting_requires_pre_ship_gtd",
            return_value=True,
        ),
        patch(
            "review_processor.ozon_fbs_marking.update_posting_marking_codes",
            return_value={
                "ok": True,
                "codes": codes,
                "saved_at": "2026-08-31T10:00:00+00:00",
            },
        ) as upd,
        patch(
            "review_processor.ozon_fbs_marking.push_marking_to_ozon"
        ) as push,
        patch("review_processor.ozon_fbs_marking.oz.OzonFbsClient") as client_cls,
    ):
        out = save_marking(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "kiz_codes": codes,
                    "gtd_number": gtd,
                }
            ],
            allowed_posting_numbers={"P-1"},
            client_id="cid",
            api_key="key",
            skip_ozon_push=True,
        )
    assert out["ok"] is True
    assert out["results"][0]["local_only"] is True
    assert out["results"][0]["kiz_ozon_synced"] is False
    upd.assert_called_once()
    assert upd.call_args.kwargs.get("ozon_synced") is False
    push.assert_not_called()
    client_cls.assert_not_called()


def test_save_marking_skips_ozon_push_when_already_synced() -> None:
    codes = ["010460123456789021ABC"]
    with (
        patch(
            "review_processor.ozon_fbs_marking._load_posting_cancelled_map",
            return_value={},
        ),
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={
                "P-1": {
                    "codes": codes,
                    "saved_at": "2026-08-31T10:00:00+00:00",
                    "ozon_synced": True,
                    "gtd_number": "10000000/010126/1234567",
                }
            },
        ),
        patch(
            "review_processor.ozon_fbs_marking._load_posting_row",
            return_value={
                "posting_number": "P-1",
                "marking_gtd_number": "10000000/010126/1234567",
                "raw_json": "{}",
            },
        ),
        patch(
            "review_processor.ozon_fbs_marking.oz.posting_requires_pre_ship_gtd",
            return_value=True,
        ),
        patch(
            "review_processor.ozon_fbs_marking.update_posting_marking_codes"
        ) as upd,
        patch(
            "review_processor.ozon_fbs_marking.push_marking_to_ozon"
        ) as push,
        patch("review_processor.ozon_fbs_marking.oz.OzonFbsClient"),
    ):
        out = save_marking(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "kiz_codes": codes,
                    "gtd_number": "10000000/010126/1234567",
                }
            ],
            allowed_posting_numbers={"P-1"},
            client_id="cid",
            api_key="key",
        )
    assert out["ok"] is True
    assert out["saved"] == 1
    assert out["results"][0]["unchanged"] is True
    assert out["results"][0]["kiz_ozon_synced"] is True
    upd.assert_not_called()
    push.assert_not_called()


def test_save_marking_skips_local_rewrite_when_unchanged_non_gtd() -> None:
    codes = ["010460123456789021ABC"]
    with (
        patch(
            "review_processor.ozon_fbs_marking._load_posting_cancelled_map",
            return_value={},
        ),
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={
                "P-1": {
                    "codes": codes,
                    "saved_at": "2026-08-31T10:00:00+00:00",
                    "ozon_synced": False,
                    "gtd_number": "",
                }
            },
        ),
        patch(
            "review_processor.ozon_fbs_marking._load_posting_row",
            return_value={"posting_number": "P-1", "raw_json": "{}"},
        ),
        patch(
            "review_processor.ozon_fbs_marking.oz.posting_requires_pre_ship_gtd",
            return_value=False,
        ),
        patch(
            "review_processor.ozon_fbs_marking.update_posting_marking_codes"
        ) as upd,
        patch(
            "review_processor.ozon_fbs_marking.push_marking_to_ozon"
        ) as push,
    ):
        out = save_marking(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[{"posting_number": "P-1", "kiz_codes": codes}],
            allowed_posting_numbers={"P-1"},
        )
    assert out["ok"] is True
    assert out["results"][0]["unchanged"] is True
    upd.assert_not_called()
    push.assert_not_called()


def test_save_marking_push_only_when_local_same_but_not_synced() -> None:
    codes = ["010460123456789021ABC"]
    gtd = "10000000/010126/1234567"
    with (
        patch(
            "review_processor.ozon_fbs_marking._load_posting_cancelled_map",
            return_value={},
        ),
        patch(
            "review_processor.ozon_fbs_marking.load_marking_map",
            return_value={
                "P-1": {
                    "codes": codes,
                    "saved_at": "2026-08-31T10:00:00+00:00",
                    "ozon_synced": False,
                    "gtd_number": gtd,
                }
            },
        ),
        patch(
            "review_processor.ozon_fbs_marking._load_posting_row",
            return_value={
                "posting_number": "P-1",
                "marking_gtd_number": gtd,
                "raw_json": "{}",
            },
        ),
        patch(
            "review_processor.ozon_fbs_marking.oz.posting_requires_pre_ship_gtd",
            return_value=True,
        ),
        patch(
            "review_processor.ozon_fbs_marking.oz._posting_payload_from_row",
            return_value={"posting_number": "P-1"},
        ),
        patch(
            "review_processor.ozon_fbs_marking.update_posting_marking_codes",
            return_value={
                "ok": True,
                "codes": codes,
                "saved_at": "2026-08-31T10:01:00+00:00",
            },
        ) as upd,
        patch(
            "review_processor.ozon_fbs_marking.push_marking_to_ozon"
        ) as push,
        patch("review_processor.ozon_fbs_marking.oz.OzonFbsClient"),
    ):
        out = save_marking(
            MagicMock(),
            user_id=1,
            source_id=2,
            items=[
                {
                    "posting_number": "P-1",
                    "kiz_codes": codes,
                    "gtd_number": gtd,
                }
            ],
            allowed_posting_numbers={"P-1"},
            client_id="cid",
            api_key="key",
        )
    assert out["ok"] is True
    assert out["results"][0]["kiz_ozon_synced"] is True
    push.assert_called_once()
    # Only the post-push synced=True write — no pre-push wipe.
    assert upd.call_count == 1
    assert upd.call_args.kwargs.get("ozon_synced") is True
