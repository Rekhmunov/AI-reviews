"""Edit / soft-delete feedback marketplace accounts by stable cabinet id."""

from __future__ import annotations

from pathlib import Path

from review_processor.feedback_account_identity import (
    cabinet_id_label,
    marketplace_requires_cabinet_id,
    resolve_external_account_id,
)

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")
REPO_PY = (ROOT / "review_processor" / "repository.py").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
IDENTITY_PY = (
    ROOT / "review_processor" / "feedback_account_identity.py"
).read_text(encoding="utf-8")


def test_account_update_and_revive_wired() -> None:
    assert "class AccountUpdateRequest" in WEB_PY
    assert '@app.patch("/api/accounts/{account_id}")' in WEB_PY
    assert "def update_marketplace_account(" in REPO_PY
    assert "def _ensure_marketplace_account_identity(" in REPO_PY
    assert "external_account_id" in REPO_PY
    assert "deleted_at" in REPO_PY
    assert "revived" in REPO_PY
    assert "soft_deleted" in WEB_PY
    assert "editAccountModal" in APP_HTML
    assert "cabinetIdField" in APP_HTML
    assert "openEditAccountModal" in APP_JS
    assert "saveEditAccount" in APP_JS
    assert "Кабинет восстановлен" in APP_JS
    assert "Для WB требуется ID кабинета" in WEB_PY or "ID кабинета для WB" in APP_JS
    assert "app.js?v=715" in APP_HTML
    assert "resolve_external_account_id" in IDENTITY_PY


def test_resolve_cabinet_ids() -> None:
    assert resolve_external_account_id(marketplace="ozon", client_id=" 664575 ") == "664575"
    assert resolve_external_account_id(marketplace="wb", client_id="cab-1") == "cab-1"
    assert resolve_external_account_id(marketplace="yandex", business_id="biz-9") == "biz-9"
    assert resolve_external_account_id(marketplace="ozon", client_id="") is None
    assert marketplace_requires_cabinet_id("ozon")
    assert marketplace_requires_cabinet_id("wb")
    assert marketplace_requires_cabinet_id("yandex")
    assert cabinet_id_label("ozon") == "Client-Id"
    assert "WB" in cabinet_id_label("wb")
