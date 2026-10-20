"""PVZ returns settings gear — owner only (UI + POST)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")
PVZ_JS = (ROOT / "web_static" / "wb_fbs_pvz_returns.js").read_text(encoding="utf-8")
WEB_PY = (ROOT / "review_processor" / "web.py").read_text(encoding="utf-8")


def test_settings_btn_hidden_by_default() -> None:
    btn = HTML.split('id="wbFbsPvzSettingsBtn"', 1)[1].split("</button>", 1)[0]
    assert "hidden" in btn
    assert "openWbFbsPvzSettings" in btn


def test_client_owner_gate() -> None:
    assert "function _wbFbsPvzSyncOwnerOnlySettingsBtn" in PVZ_JS
    assert "_wbFbsPvzSyncOwnerOnlySettingsBtn()" in PVZ_JS
    open_fn = PVZ_JS.split("function openWbFbsPvzSettings", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "_wbFbsPvzCanEditSettings" in open_fn
    save_fn = PVZ_JS.split("async function saveWbFbsPvzSettings", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "_wbFbsPvzCanEditSettings" in save_fn


def test_post_settings_requires_owner() -> None:
    chunk = WEB_PY.split(
        "async def wb_fbs_pvz_returns_settings_save", 1
    )[1].split("@app.post", 1)[0]
    assert "_is_wb_fbs_tenant_owner" in chunk
    assert "только главному пользователю" in chunk
