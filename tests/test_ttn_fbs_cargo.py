"""TN FBS cargo autofill helpers."""

from __future__ import annotations

import unittest

from review_processor.ttn_fbs_cargo import (
    format_cargo_place_row_label,
    format_places,
    local_ozon_container_ids,
    local_ozon_cargo_place_rows,
    normalize_packing_type,
    parse_cargo_places_detail,
    places_from_ozon_containers,
    places_from_wb_trbx,
    product_weight_index,
    serialize_cargo_places_detail,
    sum_weight_for_lines,
    totals_from_cargo_places_detail,
    weight_lines_from_ozon_orders,
    weight_lines_from_wb_orders,
)


class TtnFbsCargoTests(unittest.TestCase):
    def test_product_weight_index_keys(self) -> None:
        idx = product_weight_index(
            [
                {
                    "supplier_article": "Art-1",
                    "wb_nmid": "111",
                    "ozon_sku": "222",
                    "weight_kg": 0.5,
                }
            ]
        )
        self.assertEqual(idx["Art-1"], 0.5)
        self.assertEqual(idx["art-1"], 0.5)
        self.assertEqual(idx["111"], 0.5)
        self.assertEqual(idx["222"], 0.5)

    def test_sum_weight_wb_orders(self) -> None:
        idx = product_weight_index(
            [{"supplier_article": "A", "wb_nmid": "9", "weight_kg": 1.25}]
        )
        lines = weight_lines_from_wb_orders(
            [
                {"article": "A", "nm_id": "9"},
                {"article": "A", "nm_id": "9"},
                {"article": "B", "nm_id": "1"},
            ]
        )
        out = sum_weight_for_lines(idx, lines)
        self.assertEqual(out["weight_kg"], 2.5)
        self.assertEqual(out["weight"], "2.5")
        self.assertEqual(out["missing_articles"], ["B"])

    def test_places_wb_and_ozon(self) -> None:
        self.assertEqual(places_from_wb_trbx({"boxes_count": 3, "boxes": []}), 3)
        self.assertEqual(places_from_wb_trbx({"boxes": [{"id": "1"}, {"id": "2"}]}), 2)
        self.assertEqual(
            places_from_ozon_containers(
                {
                    "containers": [
                        {"id": 1, "bound_to_this_supply": True},
                        {"id": 2, "bound_to_this_supply": False},
                        {"id": 3, "supply_id": "S1"},
                    ]
                },
                supply_id="S1",
            ),
            2,
        )
        self.assertEqual(format_places(4), "4")
        self.assertEqual(format_places(None), "")

    def test_places_honors_bound_to_open_supply(self) -> None:
        """enrich_containers_for_supply_modal sets bound_to_open_supply."""
        self.assertEqual(
            places_from_ozon_containers(
                {
                    "items": [
                        {
                            "container_id": 11,
                            "bound_supply_id": "S1",
                            "bound_to_open_supply": True,
                        },
                        {
                            "container_id": 12,
                            "bound_supply_id": "S2",
                            "bound_to_open_supply": False,
                        },
                        {
                            "container_id": 13,
                            "bound_supply_id": "S1",
                            "bound_to_open_supply": True,
                        },
                    ]
                },
                supply_id="S1",
            ),
            2,
        )

    def test_normalize_packing_type(self) -> None:
        self.assertEqual(normalize_packing_type("паллеты"), "Паллеты")
        self.assertEqual(normalize_packing_type("Короба"), "Короба")
        self.assertEqual(normalize_packing_type("Рулоны"), "Рулоны")
        self.assertEqual(normalize_packing_type(""), "")
        self.assertEqual(normalize_packing_type("другое"), "")

    def test_ozon_qty_lines(self) -> None:
        lines = weight_lines_from_ozon_orders(
            [
                {"offer_id": "o1", "sku": "s1", "quantity": 3},
                {"offer_id": "o1", "sku": "s1", "quantity": 2},
                {"offer_id": "x", "sku": "y", "cancelled": True, "quantity": 9},
            ]
        )
        self.assertEqual(lines, [(["o1", "s1"], 5)])

    def test_local_ozon_container_ids_distinct_sorted(self) -> None:
        class _Repo:
            def _connect(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def _sql(self, q):
                return q

            def execute(self, sql, params=()):
                self.params = params
                return self

            def fetchall(self):
                return [{"cid": 20}, {"cid": 10}, {"cid": 20}]

        ids = local_ozon_container_ids(
            _Repo(), user_id=1, source_id=2, supply_id="OZ-1"
        )
        # DISTINCT in SQL + local dedupe; mock returns unsorted duplicates.
        self.assertEqual(ids, ["20", "10"])

    def test_parse_serialize_cargo_places_detail(self) -> None:
        rows = parse_cargo_places_detail(
            [
                {"container_id": "101", "container_number": 1, "weight": "12.5"},
                {"container_id": "101", "container_number": 9, "weight": "1"},  # dup
                {"container_id": "202", "weight_kg": 3},
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["container_id"], "101")
        self.assertEqual(rows[0]["weight"], "12.5")
        self.assertEqual(rows[1]["container_id"], "202")
        self.assertEqual(rows[1]["weight"], "3")
        self.assertEqual(rows[1]["container_number"], 2)
        raw = serialize_cargo_places_detail(rows)
        again = parse_cargo_places_detail(raw)
        self.assertEqual(again[0]["container_id"], "101")
        self.assertEqual(format_cargo_place_row_label(rows[0]), "№1 · 101")
        totals = totals_from_cargo_places_detail(rows)
        self.assertEqual(totals["places"], 2)
        self.assertEqual(totals["places_text"], "2")
        self.assertEqual(totals["weight_kg"], 15.5)
        self.assertEqual(totals["weight"], "15.5")

    def test_local_ozon_cargo_place_rows_weights(self) -> None:
        class _Repo:
            def _connect(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def _sql(self, q):
                return q

            def execute(self, sql, params=()):
                self.last_sql = sql
                self.params = params
                return self

            def fetchall(self):
                if "DISTINCT" in str(self.last_sql):
                    return [{"cid": 10}, {"cid": 20}]
                return [
                    {
                        "container_id": 10,
                        "offer_id": "A",
                        "sku": "1",
                        "quantity": 2,
                        "status": "delivering",
                        "tab": "delivering",
                        "posting_number": "p1",
                    },
                    {
                        "container_id": 20,
                        "offer_id": "B",
                        "sku": "2",
                        "quantity": 1,
                        "status": "delivering",
                        "tab": "delivering",
                        "posting_number": "p2",
                    },
                ]

            def _row_to_dict(self, row):
                return dict(row)

        idx = product_weight_index(
            [
                {"supplier_article": "A", "weight_kg": 1.5},
                {"supplier_article": "B", "weight_kg": 4},
            ]
        )
        rows = local_ozon_cargo_place_rows(
            _Repo(),
            user_id=1,
            source_id=2,
            supply_id="S1",
            weight_index=idx,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["container_id"], "10")
        self.assertEqual(rows[0]["container_number"], 1)
        self.assertEqual(rows[0]["weight_kg"], 3.0)
        self.assertEqual(rows[1]["container_id"], "20")
        self.assertEqual(rows[1]["weight_kg"], 4.0)


if __name__ == "__main__":
    unittest.main()
