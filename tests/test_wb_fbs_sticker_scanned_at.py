"""WB FBS: stamp sticker_scanned_at on operator sticker scan persist."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_processor import wb_fbs


def test_persist_order_stickers_batch_set_scanned_at_uses_now() -> None:
    repo = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.rowcount = 1
    conn.execute.return_value = cur
    repo._connect.return_value.__enter__.return_value = conn
    repo._connect.return_value.__exit__.return_value = False
    repo._sql = lambda q: q

    with patch.object(wb_fbs, "ensure_wb_fbs_tables"):
        updated = wb_fbs.persist_order_stickers_batch(
            repo,
            user_id=1,
            source_id=2,
            stickers={1001: {"sticker_barcode": "*Uabc"}},
            set_scanned_at=True,
        )
    assert updated == 1
    sql = str(conn.execute.call_args.args[0])
    assert "sticker_scanned_at = NOW()" in sql.replace("\n", " ")


def test_persist_order_stickers_batch_sync_keeps_scanned_at() -> None:
    repo = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    cur.rowcount = 1
    conn.execute.return_value = cur
    repo._connect.return_value.__enter__.return_value = conn
    repo._connect.return_value.__exit__.return_value = False
    repo._sql = lambda q: q

    with patch.object(wb_fbs, "ensure_wb_fbs_tables"):
        wb_fbs.persist_order_stickers_batch(
            repo,
            user_id=1,
            source_id=2,
            stickers={1001: {"sticker_barcode": "*Uabc"}},
            set_scanned_at=False,
        )
    sql = str(conn.execute.call_args.args[0])
    assert "sticker_scanned_at = sticker_scanned_at" in sql.replace("\n", " ")
    assert "NOW()" not in sql
