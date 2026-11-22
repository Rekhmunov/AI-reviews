"""Certificate IK stack: one due line, matching expiry font markers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web_static" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "web_templates" / "app.html").read_text(encoding="utf-8")


def _extract_certs_ik_helpers() -> str:
    """Slice pure helpers from app.js for Node evaluation."""
    start = JS.find("function _certsIsCertificateDoc")
    end = JS.find("function _certsExpiryIsRed")
    assert start > 0 and end > start
    return JS[start:end]


def test_ik_stack_shows_only_latest_due(tmp_path: Path) -> None:
    import json
    import shutil
    import subprocess

    if not shutil.which("node"):
        # Fallback: assert algorithm markers in source.
        assert "latestDue" in JS
        assert "dueStartYear" in JS
        assert "Math.min(expiryYear, todayYear) - 1" in JS
        assert "at most one due planned IK line" in JS
        return

    helpers = _extract_certs_ik_helpers()
    script = tmp_path / "ik_stack_check.js"
    script.write_text(
        helpers
        + """
const cert = {
  doc_type: "Сертификат соответствия",
  expiry_date: "2030-12-09",
  ik_dates: [{ year: 2026, date: "2026-11-19" }],
};
const stack = _certsIkStack(cert, "2026-11-22");
const dues = stack.filter((x) => x.kind === "due");
const dones = stack.filter((x) => x.kind === "done");
if (dues.length !== 0) {
  // 2026 completed — no due for 2026; 2027 planned is 2027-09-09 (future)
  console.error(JSON.stringify(stack));
  process.exit(2);
}
if (dones.length !== 1 || dones[0].date !== "2026-11-19") {
  console.error(JSON.stringify(stack));
  process.exit(3);
}

const openCert = {
  doc_type: "Сертификат соответствия",
  expiry_date: "2030-12-09",
  ik_dates: [],
};
const openStack = _certsIkStack(openCert, "2026-11-22");
const openDues = openStack.filter((x) => x.kind === "due");
if (openDues.length !== 1 || openDues[0].date !== "2026-09-09" || openDues[0].year !== 2026) {
  console.error("expected single 2026-09-09 due, got", JSON.stringify(openStack));
  process.exit(4);
}
console.log(JSON.stringify({ ok: true, openDues, dones }));
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True


def test_ik_label_shares_expiry_font() -> None:
    assert 'class="certs-ik-date"' in JS
    assert 'class="certs-ik-label"' in JS
    assert ".certs-ik-line .certs-ik-label" in CSS
    assert "font-size: inherit" in CSS
    # Due line must not force a smaller 13px face than expiry.
    block = CSS[CSS.find(".certs-ik-line {"): CSS.find("button.certs-ik-line.is-due")]
    assert "font-size: 13px" not in block
    assert "font-size: inherit" in block
    assert "app.js?v=724" in HTML
    assert "style.css?v=445" in HTML


def test_ui_helpers_mention_one_due() -> None:
    assert "latestDue" in JS
    assert "dueStartYear" in JS
