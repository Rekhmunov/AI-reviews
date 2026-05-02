import os
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from review_processor.repository import ReviewRepository
from review_processor.service import ReviewAutomationService


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")


class ServiceAiConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = temp.name
        temp.close()
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.unlink(self.db_path))

        self.repository = ReviewRepository(db_path=self.db_path)
        self.service = ReviewAutomationService(repository=self.repository)
    def test_check_yandex_connection_success(self) -> None:
        with mock.patch("review_processor.service.urlopen", return_value=_FakeResponse({"result": {"alternatives": []}})):
            result = self.service.check_yandex_connection(
                api_key="abMYSECRETKEYzz",
                folder_id="folder-abc",
            )

        self.assertTrue(result["ok"])
        self.assertIn("message", result)
        self.assertIn("model_uri", result)

    def test_check_yandex_connection_auth_error(self) -> None:
        err = HTTPError(
            url="https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )
        err.read = lambda: b'{"message":"unauthorized"}'  # type: ignore[assignment]
        with mock.patch("review_processor.service.urlopen", side_effect=err):
            with self.assertRaisesRegex(Exception, "401"):
                self.service.check_yandex_connection(
                    api_key="abMYSECRETKEYzz",
                    folder_id="folder-abc",
                )


if __name__ == "__main__":
    unittest.main()
