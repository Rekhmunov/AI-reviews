"""WB FBS owner-only tabs: finished / cancelled / archive."""

from review_processor.wb_fbs import (
    OWNER_ONLY_TABS,
    TAB_ARCHIVE,
    TAB_CANCELLED,
    TAB_FINISHED,
    TAB_NEW,
    is_owner_only_tab,
)


def test_owner_only_tabs_set():
    assert OWNER_ONLY_TABS == frozenset({TAB_FINISHED, TAB_CANCELLED, TAB_ARCHIVE})


def test_is_owner_only_tab():
    assert is_owner_only_tab("finished")
    assert is_owner_only_tab("CANCELLED")
    assert is_owner_only_tab(" archive ")
    assert not is_owner_only_tab(TAB_NEW)
    assert not is_owner_only_tab("assembly")
    assert not is_owner_only_tab("")
    assert not is_owner_only_tab(None)
