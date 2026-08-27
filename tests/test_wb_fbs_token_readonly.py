"""WB JWT read-only flag and MGT collect guard."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

from review_processor import wb_fbs as wb


def _fake_wb_jwt(*, uid: int = 1, scopes: int = wb.WB_SCOPE_MARKETPLACE, read_only: bool = False) -> str:
    mask = int(scopes)
    if read_only:
        mask |= wb.WB_TOKEN_READ_ONLY_BIT
    header = base64.urlsafe_b64encode(b'{"alg":"ES256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": uid, "s": mask}, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def test_wb_token_is_read_only_detects_flag() -> None:
    writable = _fake_wb_jwt(scopes=wb.WB_SCOPE_MARKETPLACE, read_only=False)
    readonly = _fake_wb_jwt(scopes=wb.WB_SCOPE_MARKETPLACE, read_only=True)
    assert not wb.wb_token_is_read_only(writable)
    assert wb.wb_token_is_read_only(readonly)


def test_wb_token_scope_labels_includes_read_only() -> None:
    token = _fake_wb_jwt(scopes=wb.WB_SCOPE_MARKETPLACE, read_only=True)
    labels = wb.wb_token_scope_labels(token)
    assert "Маркетплейс" in labels
    assert "Только чтение" in labels


def test_preview_collect_mgt_reports_read_only_token(monkeypatch) -> None:
    def fake_orders(repo, *, user_id, source_id):
        return [
            {
                "order_id": 10,
                "is_b2b": False,
                "warehouse_id": 1,
                "cross_border_type": None,
            }
        ]

    monkeypatch.setattr(wb, "_load_new_mgt_orders", fake_orders)
    monkeypatch.setattr(wb, "list_supplies", lambda *a, **k: [])
    monkeypatch.setattr(wb, "ensure_wb_fbs_tables", lambda repo: None)
    monkeypatch.setattr(
        wb, "_source_display_name", lambda repo, *, user_id, source_id: "Источник"
    )

    preview = wb.preview_collect_mgt(
        object(),
        user_id=1,
        source_id=2,
        api_key=_fake_wb_jwt(read_only=True),
    )
    assert preview["token_read_only"] is True
    assert preview["token_read_only_message"]


def test_execute_collect_mgt_rejects_read_only_token() -> None:
    result = wb.execute_collect_mgt(
        MagicMock(),
        user_id=1,
        source_id=2,
        api_key=_fake_wb_jwt(read_only=True),
        decisions=[],
    )
    assert result["ok"] is False
    assert result["token_read_only"] is True
    assert "только для чтения" in str(result["message"]).lower()


def test_auto_collect_skips_read_only_source(monkeypatch) -> None:
    repo = MagicMock()
    repo.get_wb_fbs_auto_sync_settings.return_value = {
        "collect_mgt_enabled": True,
        "collect_mgt_active_from": "00:00",
        "collect_mgt_active_to": "23:59",
        "collect_mgt_interval_minutes": 10,
        "collect_mgt_last_run_at": None,
    }
    readonly_key = _fake_wb_jwt(read_only=True)
    monkeypatch.setattr(
        wb,
        "list_fbs_sync_jobs",
        lambda repo, *, user_id: [
            {"source_id": 20, "api_key": readonly_key, "name": "ИП Тест"},
        ],
    )
    monkeypatch.setattr(
        wb,
        "_msk_time_in_active_window",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        wb,
        "_fbs_auto_sync_is_due",
        lambda **kwargs: True,
    )

    result = wb.run_auto_collect_mgt_for_owner(repo, user_id=1)
    assert result["ok"] is True
    assert result["ran"] is True
    detail = result["detail"]
    assert len(detail["sources"]) == 1
    row = detail["sources"][0]
    assert row["outcome"] == "skipped"
    assert row["reason_code"] == "read_only_token"
