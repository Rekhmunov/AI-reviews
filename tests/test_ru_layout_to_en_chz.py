"""RU keyboard layout → EN for Chestny Znak crypto (base64 needs / not .).

Mirrors web `_WB_FBS_RU_LAYOUT_TO_EN` / desktop `_RU_LAYOUT_TO_EN` without importing PyQt5.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep in sync with web_static/app.js `_WB_FBS_RU_LAYOUT_TO_EN`
RU_LAYOUT_TO_EN = {
    "й": "q", "ц": "w", "у": "e", "к": "r", "е": "t", "н": "y", "г": "u", "ш": "i",
    "щ": "o", "з": "p", "х": "[", "ъ": "]",
    "ф": "a", "ы": "s", "в": "d", "а": "f", "п": "g", "р": "h", "о": "j", "л": "k",
    "д": "l", "ж": ";", "э": "'",
    "я": "z", "ч": "x", "с": "c", "м": "v", "и": "b", "т": "n", "ь": "m", "б": ",",
    "ю": ".", "ё": "`",
    "Й": "Q", "Ц": "W", "У": "E", "К": "R", "Е": "T", "Н": "Y", "Г": "U", "Ш": "I",
    "Щ": "O", "З": "P", "Х": "{", "Ъ": "}",
    "Ф": "A", "Ы": "S", "В": "D", "А": "F", "П": "G", "Р": "H", "О": "J", "Л": "K",
    "Д": "L", "Ж": ":", "Э": '"',
    "Я": "Z", "Ч": "X", "С": "C", "М": "V", "И": "B", "Т": "N", "Ь": "M", "Б": "<",
    "Ю": ">", "Ё": "~",
    ".": "/", ",": "?",
}


def fix_ru_keyboard_layout(value: str) -> str:
    text = str(value or "")
    if not re.search(r"[а-яёА-ЯЁ]", text):
        return text
    return "".join(RU_LAYOUT_TO_EN.get(ch, ch) for ch in text)


def test_ru_layout_maps_cyrillic_letters() -> None:
    assert fix_ru_keyboard_layout("91УУ12") == "91EE12"
    assert fix_ru_keyboard_layout("цЛД26Й") == "wKL26Q"


def test_ru_layout_slash_key_becomes_base64_slash() -> None:
    raw = (
        "0104670172422472215цЛД26Й!ЛНЬЕР91УУ1292ТЫЯЩВЬЦЬВЙИАЗЯФЬШЛМУТ.8ЬНТКПФ81ПМ"
    )
    out = fix_ru_keyboard_layout(raw)
    assert "УУ" not in out
    assert "ц" not in out
    assert "/8" in out
    assert ".8" not in out


def test_yu_still_maps_to_period() -> None:
    assert fix_ru_keyboard_layout("ю") == "."
    assert fix_ru_keyboard_layout("б") == ","


def test_en_only_mark_keeps_literal_dot() -> None:
    en = "0104670172422472215abc.de91EE12"
    assert fix_ru_keyboard_layout(en) == en


def test_web_and_desktop_maps_include_slash_keys() -> None:
    app_js = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    assert '".": "/"' in app_js or '".": "/"' in app_js
    assert '",": "?"' in app_js or '","' in app_js and '"?"' in app_js
    helpers = (ROOT / "desktop_wb_fbs" / "app" / "ui" / "format_helpers.py").read_text(
        encoding="utf-8"
    )
    assert '".": "/"' in helpers
    assert '",": "?"' in helpers
    tsd = (ROOT / "web_static" / "wb_fbs_tsd.js").read_text(encoding="utf-8")
    assert '".": "/"' in tsd
    assert '",": "?"' in tsd
