"""Certificate IK stack: one due line, plain red text, editable done dates."""

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


def test_ik_stack_after_confirm_waits_for_next_year(tmp_path: Path) -> None:
    import json
    import shutil
    import subprocess

    if not shutil.which("node"):
        assert "maxCompletedYear + 1" in JS
        assert "year <= maxCompletedYear" in JS
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
  // 2026 completed — must NOT keep 2026-09-09 due; 2027-09-09 is still future
  console.error(JSON.stringify(stack));
  process.exit(2);
}
if (dones.length !== 1 || dones[0].date !== "2026-11-19" || dones[0].year !== 2026) {
  console.error(JSON.stringify(stack));
  process.exit(3);
}

// On/after 2027-09-09 the next due appears for 2027.
const next = _certsIkStack(cert, "2027-09-10");
const nextDues = next.filter((x) => x.kind === "due");
if (nextDues.length !== 1 || nextDues[0].year !== 2027 || nextDues[0].date !== "2027-09-09") {
  console.error("expected 2027-09-09 due", JSON.stringify(next));
  process.exit(4);
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
  process.exit(5);
}
console.log(JSON.stringify({ ok: true, nextDues, dones }));
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


def test_ik_plain_text_not_button_chrome() -> None:
    assert "background: none !important" in CSS
    assert "border: 0 !important" in CSS
    assert "box-shadow: none !important" in CSS
    assert "min-height: 0" in CSS
    # Gap separates date and (ИК); label has no leading space in markup.
    assert "gap: 4px" in CSS
    assert 'class="certs-ik-label">(ИК)</span>' in JS or "certs-ik-label\">(ИК)<" in JS
    assert "is-done" in JS
    assert "Изменить дату проведения ИК" in JS


def test_ik_label_shares_expiry_font() -> None:
    assert 'class="certs-ik-date"' in JS
    assert 'class="certs-ik-label"' in JS
    assert ".certs-ik-line .certs-ik-label" in CSS
    assert "font-size: inherit" in CSS
    assert "app.js?v=727" in HTML
    assert "style.css?v=448" in HTML


def test_ui_helpers_mention_next_cycle() -> None:
    assert "latestDue" in JS
    assert "dueStartYear" in JS
    assert "maxCompletedYear + 1" in JS
