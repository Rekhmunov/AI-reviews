"""Product flag requires_kiz — Ozon FBS Marking catalog gate."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class RequiresKizMapTests(unittest.TestCase):
    @patch("review_processor.repository.ReviewRepository._connect")
    def test_map_keys_article_and_ozon_sku(self, _connect_mock):
        from review_processor.repository import ReviewRepository

        repo = ReviewRepository.__new__(ReviewRepository)
        repo.list_product_photos = MagicMock(
            return_value=[
                {
                    "supplier_article": "white27",
                    "ozon_sku": "752039906",
                    "requires_kiz": True,
                },
                {
                    "supplier_article": "whitebort",
                    "ozon_sku": "752967971",
                    "requires_kiz": False,
                },
            ]
        )
        m = ReviewRepository.get_product_requires_kiz_map(repo, user_id=1)
        self.assertTrue(m.get("white27"))
        self.assertTrue(m.get("white27".casefold()))
        self.assertTrue(m.get("752039906"))
        self.assertNotIn("whitebort", m)
        self.assertNotIn("752967971", m)

    @patch("review_processor.repository.ReviewRepository._connect")
    def test_add_product_photo_persists_flag(self, connect_mock):
        from review_processor.repository import ReviewRepository

        conn = MagicMock()
        connect_mock.return_value.__enter__.return_value = conn
        connect_mock.return_value.__exit__.return_value = False

        repo = ReviewRepository.__new__(ReviewRepository)
        repo._sql = lambda sql: sql
        repo._row_to_dict = lambda row: dict(row) if row else {}
        repo._insert_and_get_id = MagicMock(return_value=7)

        class _Row(dict):
            pass

        conn.execute.return_value.fetchone.return_value = _Row(
            id=7,
            name="Товар",
            requires_kiz=1,
            skip_kiz_gtin_check=0,
        )

        item = ReviewRepository.add_product_photo(
            repo,
            user_id=1,
            name="Товар",
            supplier_article="A1",
            wb_nmid="1",
            ozon_sku="99",
            photo_path=None,
            requires_kiz=True,
        )
        self.assertTrue(item.get("requires_kiz"))
        insert_sql = repo._insert_and_get_id.call_args[0][1]
        self.assertIn("requires_kiz", insert_sql)
        params = repo._insert_and_get_id.call_args[0][2]
        self.assertEqual(params[9], 1)


if __name__ == "__main__":
    unittest.main()
