import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from review_processor.auth import create_session_token, hash_password, verify_password
from review_processor.repository import ReviewRepository


class AuthTests(unittest.TestCase):
    def test_hash_and_verify_password(self) -> None:
        password_hash = hash_password("super-secret-123")
        self.assertTrue(verify_password("super-secret-123", password_hash))
        self.assertFalse(verify_password("wrong-pass", password_hash))

    def test_session_creation_and_cleanup(self) -> None:
        temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = temp.name
        temp.close()
        self.addCleanup(lambda: os.path.exists(db_path) and os.unlink(db_path))

        repository = ReviewRepository(db_path=db_path)
        user = repository.create_user(email="u@example.com", password_hash="x", role="admin")
        token = create_session_token()
        expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        repository.create_session(token=token, user_id=int(user["id"]), expires_at=expires_at)
        self.assertIsNotNone(repository.get_session_user(token))

        repository.cleanup_expired_sessions((datetime.now(UTC) + timedelta(hours=2)).isoformat())
        self.assertIsNone(repository.get_session_user(token))


if __name__ == "__main__":
    unittest.main()
