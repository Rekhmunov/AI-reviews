import os
import unittest

from review_processor.config import load_app_config


class AppConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            "APP_ENV": os.environ.get("APP_ENV"),
            "APP_DB_URL": os.environ.get("APP_DB_URL"),
            "APP_DB_PATH": os.environ.get("APP_DB_PATH"),
            "APP_SELF_REGISTRATION_ENABLED": os.environ.get("APP_SELF_REGISTRATION_ENABLED"),
        }

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_defaults(self) -> None:
        os.environ.pop("APP_ENV", None)
        os.environ.pop("APP_DB_URL", None)
        os.environ.pop("APP_DB_PATH", None)
        os.environ.pop("APP_SELF_REGISTRATION_ENABLED", None)
        cfg = load_app_config()
        self.assertEqual(cfg.app_env, "development")
        self.assertIsNone(cfg.db_url)
        self.assertEqual(cfg.db_path, "reviews.db")
        self.assertFalse(cfg.self_registration_enabled)
        self.assertFalse(cfg.is_production)

    def test_custom_values(self) -> None:
        os.environ["APP_ENV"] = "production"
        os.environ["APP_DB_URL"] = "postgresql://feedpilot:secret@localhost:5432/feedpilot"
        os.environ["APP_DB_PATH"] = "/var/lib/feedpilot/reviews.db"
        os.environ["APP_SELF_REGISTRATION_ENABLED"] = "true"
        cfg = load_app_config()
        self.assertEqual(cfg.app_env, "production")
        self.assertEqual(cfg.db_url, "postgresql://feedpilot:secret@localhost:5432/feedpilot")
        self.assertEqual(cfg.db_path, "/var/lib/feedpilot/reviews.db")
        self.assertTrue(cfg.self_registration_enabled)
        self.assertTrue(cfg.is_production)


if __name__ == "__main__":
    unittest.main()
