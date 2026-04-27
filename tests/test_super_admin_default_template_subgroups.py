import os
import tempfile
import unittest

from review_processor.repository import ReviewRepository


class SuperAdminDefaultTemplateSubgroupsTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = temp.name
        temp.close()
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.unlink(self.db_path))
        self.repository = ReviewRepository(db_path=self.db_path)

    def test_can_add_and_delete_custom_default_template_subgroup(self) -> None:
        self.repository.add_default_template_subgroup(
            group_id="positive",
            subgroup="Новая группа тест",
        )
        listed = self.repository.list_default_template_subgroups(group_id="positive")
        names = [str(item.get("subgroup") or "") for item in listed]
        self.assertIn("Новая группа тест", names)

        deleted = self.repository.delete_default_template_subgroup(
            group_id="positive",
            subgroup="Новая группа тест",
        )
        self.assertTrue(deleted)
        listed_after = self.repository.list_default_template_subgroups(group_id="positive")
        names_after = [str(item.get("subgroup") or "") for item in listed_after]
        self.assertNotIn("Новая группа тест", names_after)


if __name__ == "__main__":
    unittest.main()
