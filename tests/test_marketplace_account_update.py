"""Edit feedback marketplace account credentials without deleting the cabinet."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from review_processor.repository import ReviewRepository

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def test_account_update_wired_in_api_and_ui() -> None:
    assert "class AccountUpdateRequest" in WEB_PY
    assert '@app.patch("/api/accounts/{account_id}")' in WEB_PY
    assert "def update_account(" in WEB_PY
    assert "def update_marketplace_account(" in REPO_PY
    assert "editAccountModal" in APP_HTML
    assert "openEditAccountModal" in APP_JS
    assert "saveEditAccount" in APP_JS
    assert "method: \"PATCH\"" in APP_JS
    assert "/api/accounts/${_editAccountId}" in APP_JS
    assert "Оставьте пустым, чтобы не менять текущий ключ" in APP_HTML
    assert "История вопросов и отзывов не удаляется" in APP_HTML
    assert "app.js?v=714" in APP_HTML


@pytest.mark.skipif(not os.environ.get("APP_DB_URL"), reason="APP_DB_URL required")
def test_update_api_key_keeps_account_id_and_encrypts() -> None:
    repo = ReviewRepository(os.environ["APP_DB_URL"])
    user = repo.create_user(
        email=f"acct-edit-{os.getpid()}@example.com",
        password_hash="h",
        role="user",
    )
    user_id = int(user["id"])
    account = repo.create_marketplace_account(
        user_id=user_id,
        marketplace="ozon",
        account_name="Ozon main",
        api_url="https://api-seller.ozon.ru",
        api_key="old-secret-token",
        extra={"client_id": "664575"},
    )
    account_id = int(account["id"])
    try:
        updated = repo.update_marketplace_account(
            user_id=user_id,
            account_id=account_id,
            api_key="new-secret-token",
            account_name="Ozon renamed",
            client_id="664575",
        )
        assert updated is not None
        assert int(updated["id"]) == account_id
        assert updated["account_name"] == "Ozon renamed"
        assert (updated.get("extra") or {}).get("client_id") == "664575"

        with_secret = repo.get_marketplace_account(
            user_id=user_id,
            account_id=account_id,
            include_secrets=True,
        )
        assert with_secret is not None
        assert with_secret["api_key"] == "new-secret-token"

        kept = repo.update_marketplace_account(
            user_id=user_id,
            account_id=account_id,
            account_name="Ozon renamed again",
            api_key=None,
        )
        assert kept is not None
        again = repo.get_marketplace_account(
            user_id=user_id, account_id=account_id, include_secrets=True
        )
        assert again is not None
        assert again["api_key"] == "new-secret-token"
        assert again["account_name"] == "Ozon renamed again"
    finally:
        repo.delete_marketplace_account(user_id=user_id, account_id=account_id)
