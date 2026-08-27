import unittest
from unittest.mock import Mock

from review_processor.supply_permissions import (
    heal_orphaned_fbs_supply_permissions,
    supply_sources_has_any_permission,
)


class SupplySourcesHasAnyPermissionTests(unittest.TestCase):
    def test_counts_ozon_fbs_only(self) -> None:
        self.assertTrue(
            supply_sources_has_any_permission(
                sources={"12": {"ozon_fbs": True}},
            )
        )
        self.assertFalse(
            supply_sources_has_any_permission(
                sources={"12": {"ozon_fbs": False, "wb_fbs": False}},
            )
        )

    def test_ozon_fbs_only_without_can_supplies_flag(self) -> None:
        self.assertTrue(
            supply_sources_has_any_permission(
                can_supplies=False,
                sources={"12": {"ozon_fbs": True}},
            )
        )


class HealOrphanedFbsPermissionsTests(unittest.TestCase):
    def test_heal_orphaned_ozon_fbs_permission_after_source_recreate(self) -> None:
        repo = Mock()
        repo.list_supply_sources.return_value = [
            {"id": 2, "marketplace": "ozon", "name": "Ozon ФБС новый"},
        ]
        existing = {
            "1": {
                "wb": False,
                "wb_fbs": False,
                "wb_fbs_tsd": False,
                "ozon": False,
                "ozon_fbs": True,
            }
        }
        healed = heal_orphaned_fbs_supply_permissions(
            repo,
            owner_id=99,
            sources={"2": {"ozon_fbs": False}},
            existing=existing,
        )
        self.assertTrue(healed["2"]["ozon_fbs"])
        self.assertNotIn("1", healed)

    def test_does_not_regrant_when_current_source_already_has_flag(self) -> None:
        repo = Mock()
        repo.list_supply_sources.return_value = [
            {"id": 2, "marketplace": "ozon", "name": "Ozon ФБС"},
        ]
        existing = {
            "1": {"ozon_fbs": True},
            "2": {"ozon_fbs": True},
        }
        healed = heal_orphaned_fbs_supply_permissions(
            repo,
            owner_id=99,
            sources={"2": {"ozon_fbs": True}},
            existing=existing,
        )
        self.assertTrue(healed["2"]["ozon_fbs"])

    def test_does_not_regrant_after_intentional_removal(self) -> None:
        repo = Mock()
        repo.list_supply_sources.return_value = [
            {"id": 2, "marketplace": "ozon", "name": "Ozon ФБС"},
        ]
        existing = {"2": {"ozon_fbs": False}}
        healed = heal_orphaned_fbs_supply_permissions(
            repo,
            owner_id=99,
            sources={"2": {"ozon_fbs": False}},
            existing=existing,
        )
        self.assertFalse(healed["2"]["ozon_fbs"])


if __name__ == "__main__":
    unittest.main()
