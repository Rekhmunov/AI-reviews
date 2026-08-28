"""Ozon FBS marking import: normalize pasted sticker/KIZ for Chestny Znak."""

from __future__ import annotations

from review_processor.ozon_fbs_marking import _normalize_mark_code


def test_normalize_mark_code_replaces_smiley_and_inserts_gs() -> None:
    raw = (
        "0104678434671088215fc8TNao-bax("
        "\u263b"  # ☻ instead of GS
        "91EE11"
        "92IqAfwCPTJ49taiRITuziMhIrk4za9JMV7rC3tJ0UDwk="
    )
    out = _normalize_mark_code(raw)
    assert "\u001d91EE11\u001d92" in out
    assert "\u263b" not in out
    assert out.startswith("0104678434671088215fc8TNao-bax(")


def test_normalize_mark_code_arrow_and_literal_gs_token() -> None:
    raw = (
        "0104670172422472215-1g7.rkkE_jW"
        "91EE12"
        "\u2194"  # ↔ before 92
        "92ZHmD3mzOD8mYNee+9OZhh9fAgfm76x/n3LimpKqL5qw="
    )
    out = _normalize_mark_code(raw)
    assert "\u001d91EE12\u001d92" in out
    assert "\u2194" not in out


def test_normalize_mark_code_visible_gs_placeholder() -> None:
    raw = (
        "0104678434671088215Kd<)9zb=mys/"
        "<GS>91ee11<GS>92zuvzjqks7r0/eh21rdj3lnbd"
    )
    out = _normalize_mark_code(raw)
    assert out == (
        "0104678434671088215Kd<)9zb=mys/"
        "\u001d91ee11\u001d92zuvzjqks7r0/eh21rdj3lnbd"
    )
