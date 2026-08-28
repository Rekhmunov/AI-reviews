"""Parse sticker+KIZ import text the same way as web `_ozonFbsKizParseImportText`."""

from __future__ import annotations

import re


def parse_import_text(text: str) -> list[tuple[str, str]]:
    raw_lines = str(text or "").replace("\u00a0", " ").splitlines()
    lines: list[str] = []
    for line in raw_lines:
        trimmed = line.strip()
        if not trimmed:
            continue
        if re.match(r"^стикер\b", trimmed, re.I) and re.search(r"\bкиз\b", trimmed, re.I):
            continue
        lines.append(trimmed)

    pairs: list[tuple[str, str]] = []
    pending = ""

    def push(sticker: str, kiz: str) -> None:
        s = sticker.strip()
        k = kiz.strip()
        if s and k:
            pairs.append((s, k))

    def is_sticker(s: str) -> bool:
        return bool(re.fullmatch(r"\d{10,20}", s.strip()))

    def is_kiz_start(s: str) -> bool:
        return bool(re.match(r"^01\d{14}21", s.strip()))

    i = 0
    while i < len(lines):
        trimmed = lines[i]
        if "\t" in trimmed:
            pending = ""
            parts = trimmed.split("\t")
            push(parts[0], "\t".join(parts[1:]))
            i += 1
            continue
        if "|" in trimmed and re.match(r"^\d{10,20}\s*\|", trimmed):
            pending = ""
            idx = trimmed.index("|")
            push(trimmed[:idx], trimmed[idx + 1 :])
            i += 1
            continue
        inline = re.match(r"^(\d{10,20})[ \t]+(01\d{14}21[\s\S]+)$", trimmed)
        if inline:
            pending = ""
            push(inline.group(1), inline.group(2))
            i += 1
            continue
        if is_sticker(trimmed):
            pending = trimmed
            i += 1
            continue
        if pending and is_kiz_start(trimmed):
            kiz = trimmed
            while i + 1 < len(lines):
                nxt = lines[i + 1]
                if is_sticker(nxt) or is_kiz_start(nxt):
                    break
                if "\t" in nxt or re.match(r"^\d{10,20}\s*\|", nxt):
                    break
                if re.match(r"^\d{10,20}[ \t]+01\d{14}21", nxt):
                    break
                kiz += nxt
                i += 1
            push(pending, kiz)
            pending = ""
            i += 1
            continue
        pending = ""
        i += 1
    return pairs


def test_parse_same_line_space() -> None:
    pairs = parse_import_text(
        "301945805894000 0104670172422472215wKL26Q!KYMTH\x1d91EE12\x1d92ABC"
    )
    assert len(pairs) == 1
    assert pairs[0][0] == "301945805894000"
    assert pairs[0][1].startswith("0104670172422472215")


def test_parse_blank_lines_between_pairs() -> None:
    text = (
        "301945805894000\n"
        "\n"
        "\n"
        "0104670172422472215abc\x1d91EE12\x1d92xxxxxxxxxxxxxxxxxxxx\n"
        "\n"
        "701941191415000\n"
        "\n"
        "0104670172422472215def\x1d91EE12\x1d92yyyyyyyyyyyyyyyyyyyy\n"
    )
    pairs = parse_import_text(text)
    assert len(pairs) == 2
    assert pairs[0][0] == "301945805894000"
    assert pairs[1][0] == "701941191415000"


def test_parse_kiz_wrapped_after_gs_newline() -> None:
    text = (
        "301945805894000\n"
        "0104670172422472215wKL26Q!KYMTH\n"
        "91EE12\n"
        "92NSZODMWMDQBFPZAMIKVEN/8MYNRGA81GV\n"
    )
    pairs = parse_import_text(text)
    assert len(pairs) == 1
    assert "91EE12" in pairs[0][1]
    assert "92NSZ" in pairs[0][1]


def test_parse_tab_and_one_blank() -> None:
    text = "111111111111111\t0104670172422472215abc\x1d91EE12\x1d92zzzzzzzzzzzzzzzzzzzz\n"
    assert len(parse_import_text(text)) == 1
