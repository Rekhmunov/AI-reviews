"""WB FBS «Товары без КИЗ» must be available to all users on assembly."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
APP_HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _fn(src: str, name: str) -> str:
    key = f"async function {name}("
    start = src.find(key)
    if start < 0:
        key = f"function {name}("
        start = src.find(key)
    assert start >= 0, name
    marker = f"\nwindow.{name} ="
    end = src.find(marker, start)
    if end < 0:
        end = start + 4000
    return src[start:end]


def test_pick_verify_open_not_owner_only() -> None:
    body = _fn(APP_JS, "openWbFbsPickVerifyModal")
    assert "isTenantOwner()" not in body
    assert "только главному пользователю" not in body
    assert "_wbFbsIsSupplyDetailReadOnly()" in body


def test_pick_verify_save_not_owner_only() -> None:
    body = _fn(APP_JS, "saveWbFbsPickVerifyModal")
    assert "isTenantOwner()" not in body
    assert "только главному пользователю" not in body


def test_kiz_open_not_owner_only() -> None:
    body = _fn(APP_JS, "openWbFbsKizModal")
    assert "isTenantOwner()" not in body
    assert "только главному пользователю" not in body


def test_cache_bump() -> None:
    assert "app.js?v=619" in APP_HTML
