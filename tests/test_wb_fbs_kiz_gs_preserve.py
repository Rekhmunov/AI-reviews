"""КИЗ GS preserve: ↔ still maps to GS; edges strip must not eat \\u001D."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web_static" / "app.js"
TSD_JS = ROOT / "web_static" / "wb_fbs_tsd.js"


def test_app_js_has_gs_preserve_helpers() -> None:
    js = APP_JS.read_text(encoding="utf-8")
    assert "_wbFbsKizPreserveGsKeydown" in js
    assert "_wbFbsKizInsertGsIntoInput" in js
    assert "_wbFbsKizStripMarkEdges" in js
    assert "_wbFbsKizIsGsKeyEvent" in js
    # Arrow path must remain.
    assert ".replace(/\\u2194/g, \"\\u001D\")" in js or ".replace(/\\u2194/g, '\\u001D')" in js
    # Delegated capture listener (cheap when not a KIZ field).
    assert 'document.addEventListener("keydown", _wbFbsKizPreserveGsKeydown, true)' in js
    # Mark scan + row inputs only — not sticker / pick SKU.
    assert 'el.id === "wbFbsKizMarkScan"' in js
    assert "wb-fbs-kiz-code-input" in js


def test_tsd_js_has_gs_preserve_on_mark_step() -> None:
    js = TSD_JS.read_text(encoding="utf-8")
    assert "isGsKeyEvent" in js
    assert "insertGsIntoInput" in js
    assert "stripKizMarkEdges" in js
    assert 'state.step === "mark"' in js
    assert ".replace(/\\u2194/g, \"\\u001D\")" in js or ".replace(/\\u2194/g, '\\u001D')" in js


def test_normalize_mark_contract_via_node() -> None:
    """Mirror the JS contract in Node: arrow→GS, edges safe, \\s not used on mark."""
    import subprocess
    import textwrap

    script = textwrap.dedent(
        r"""
        function stripKizMarkEdges(value) {
          return String(value || "").replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
        }
        function normalizeKizMark(value) {
          return stripKizMarkEdges(
            String(value || "")
              .replace(/\u2194/g, "\u001D")
              .replace(/\r?\n/g, "")
          );
        }
        const arrow = "01gtin\u2194serial\u2194tail";
        const real = "01gtin\u001Dserial\u001Dtail";
        const padded = "  " + real + "\n";
        const outArrow = normalizeKizMark(arrow);
        const outReal = normalizeKizMark(real);
        const outPad = normalizeKizMark(padded);
        if (!outArrow.includes("\u001D")) throw new Error("arrow not mapped");
        if (outArrow.includes("\u2194")) throw new Error("arrow left behind");
        if (outReal !== real) throw new Error("real GS damaged: " + JSON.stringify(outReal));
        if (outPad !== real) throw new Error("pad strip failed: " + JSON.stringify(outPad));
        // Lone / edge GS must survive (Python str.strip would wipe a lone GS).
        if (normalizeKizMark("\u001D") !== "\u001D") throw new Error("lone GS lost");
        if (normalizeKizMark("\u001Dabc\u001D") !== "\u001Dabc\u001D") throw new Error("edge GS lost");
        console.log("ok");
        """
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ok" in proc.stdout


def test_gs_key_detection_contract_via_node() -> None:
    import subprocess
    import textwrap

    script = textwrap.dedent(
        r"""
        function isGsKeyEvent(event) {
          if (!event) return false;
          if (event.key === "\u001D" || event.keyCode === 29 || event.which === 29) return true;
          if (event.ctrlKey && !event.altKey && !event.metaKey) {
            if (event.key === "]" || event.code === "BracketRight" || event.keyCode === 221) {
              return true;
            }
          }
          return false;
        }
        const cases = [
          [{ key: "\u001D" }, true],
          [{ keyCode: 29 }, true],
          [{ which: 29 }, true],
          [{ ctrlKey: true, key: "]" }, true],
          [{ ctrlKey: true, code: "BracketRight" }, true],
          [{ key: "Enter" }, false],
          [{ key: "\u2194" }, false],
          [{ key: "a" }, false],
          [{ ctrlKey: true, key: "c" }, false],
        ];
        for (const [ev, expect] of cases) {
          const got = isGsKeyEvent(ev);
          if (got !== expect) {
            throw new Error(JSON.stringify(ev) + " => " + got + " expected " + expect);
          }
        }
        console.log("ok");
        """
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ok" in proc.stdout
