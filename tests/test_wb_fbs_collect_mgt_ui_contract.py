"""UI contract: WB FBS collect-MGT modal offers existing vs create-new (like Ozon)."""

from __future__ import annotations

from pathlib import Path

_APP_JS = Path(__file__).resolve().parents[1] / "web_static" / "app.js"


def test_wb_collect_mgt_choose_has_create_new_option() -> None:
    text = _APP_JS.read_text(encoding="utf-8")
    # Scope to collect-MGT helpers so we don't match unrelated __new__ (drivers, etc.).
    start = text.index("function _wbFbsCollectMgtRenderModal")
    end = text.index("async function openWbFbsCollectMgt")
    chunk = text[start:end]
    assert 'value="__new__"' in chunk
    assert "Создать новую поставку" in chunk
    assert "wbFbsCollectMgtTargetChanged" in chunk
    assert "wbFbsCollectMgtNewWrap_" in chunk
    assert 'supplyId === "__new__"' in chunk
    assert 'action: "create"' in chunk
    assert 'action: "choose"' in chunk
    # Silent auto-add only when needs_modal is false (create-only / legacy).
    open_fn = text[text.index("async function openWbFbsCollectMgt") : text.index("window.openWbFbsCollectMgt")]
    assert "needs_modal" in open_fn
