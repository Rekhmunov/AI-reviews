"""Scanit instance label under posting number in Ozon FBS supply / KIZ / pick first columns."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web_static" / "ozon_fbs.js"
CSS = ROOT / "web_static" / "style.css"
HTML = ROOT / "web_templates" / "app.html"


def _fn_src(name: str, *, until: str) -> str:
    js = JS.read_text(encoding="utf-8")
    start = js.find(f"function {name}")
    end = js.find(f"function {until}")
    assert start >= 0, name
    assert end > start, until
    return js[start:end]


def test_scanit_under_order_wired() -> None:
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    assert "function formatOzonScanitHtml" in js
    assert "function _ozonFbsScanitUnderOrderHtml" in js
    assert "function _ozonFbsCopyIconBtnHtml" in js
    assert "function _ozonFbsPostingCopyBtnHtml" in js
    assert "function _ozonFbsScanitCopyBtnHtml" in js
    assert "ozon-fbs-scanit-line" in js
    assert "ozon-fbs-scanit-copy" in js
    assert "ozon-fbs-posting-tail" in js[js.find("function formatOzonScanitHtml") :]

    sd = js[
        js.find('<td class="wb-fbs-sd-td-order">') : js.find(
            '<td class="wb-fbs-sd-td-product">'
        )
    ]
    # Uniform posting font in supply modal — no enlarged left-of-hyphen tail.
    assert "formatOzonPostingNumberHtml(pn)" not in sd
    assert "esc(pn)" in sd
    assert "_ozonFbsPostingCopyBtnHtml(pn)" in sd
    assert "_ozonFbsScanitUnderOrderHtml(o)" in sd
    assert sd.find("esc(pn)") < sd.find("_ozonFbsPostingCopyBtnHtml(pn)")
    assert sd.find("_ozonFbsPostingCopyBtnHtml(pn)") < sd.find(
        "_ozonFbsScanitUnderOrderHtml(o)"
    )
    assert "ozon-fbs-modal-posting-id" in sd

    col = _fn_src("_ozonFbsModalPostingColHtml", until="_ozonFbsKizRowIsEmpty")
    assert "formatOzonPostingNumberHtml(pn)" not in col
    assert "esc(pn)" in col
    assert "_ozonFbsScanitUnderOrderHtml(row)" in col
    assert col.find("esc(pn)") < col.find("_ozonFbsScanitUnderOrderHtml(row)")

    helper = _fn_src("_ozonFbsScanitUnderOrderHtml", until="detailText")
    assert "sticker_scanit" in helper
    assert "ozon-fbs-scanit-line" in helper
    assert "_ozonFbsScanitCopyBtnHtml" in helper
    assert "—" not in helper

    posting_copy = _fn_src("_ozonFbsPostingCopyBtnHtml", until="_ozonFbsScanitCopyBtnHtml")
    assert "Скопировать стикер" in posting_copy
    assert "_ozonFbsCopyIconBtnHtml" in posting_copy

    scanit_copy = _fn_src("_ozonFbsScanitCopyBtnHtml", until="_ozonFbsScanitUnderOrderHtml")
    assert "Скопировать этикетку" in scanit_copy
    assert "ozon-fbs-scanit-copy" in scanit_copy

    shared = _fn_src("_ozonFbsCopyIconBtnHtml", until="_ozonFbsPostingCopyBtnHtml")
    assert "copyOzonFbsModalPostingNumber" in shared

    copy_fn = _fn_src("copyOzonFbsModalPostingNumber", until="_ozonFbsApplyCancelledQuiet")
    assert "ozon-fbs-scanit-copy" in copy_fn
    assert "Скопировать этикетку" in copy_fn

    cancelled = _fn_src(
        "renderOzonFbsCancelledOrdersTable", until="refreshOzonFbsCancelledOrders"
    )
    assert "_ozonFbsScanitUnderOrderHtml" not in cancelled

    lookup = js[
        js.find("function renderTable(") : js.find("async function loadPostings(")
    ]
    assert "_ozonFbsScanitUnderOrderHtml" not in lookup
    # Main orders table still uses enlarged posting tail.
    assert "formatOzonPostingNumberHtml(pnRaw)" in lookup

    assert ".wb-fbs-sd-order-id .ozon-fbs-posting-tail" in css
    assert "ozon_fbs.js?v=218" in html


def test_format_ozon_scanit_html_last_four() -> None:
    js = JS.read_text(encoding="utf-8")
    start = js.find("function formatOzonScanitHtml")
    end = js.find("function _ozonFbsCopyIconBtnHtml")
    assert start >= 0 and end > start
    fn = js[start:end]
    script = f"""
function esc(s) {{ return String(s ?? ""); }}
{fn}
const out = formatOzonScanitHtml("ii50127383677");
if (out !== 'ii5012738<span class="ozon-fbs-posting-tail">3677</span>') {{
  console.error("unexpected:", out);
  process.exit(1);
}}
if (formatOzonScanitHtml("") !== "") process.exit(2);
if (formatOzonScanitHtml("   ") !== "") process.exit(3);
if (formatOzonScanitHtml("3677") !== '<span class="ozon-fbs-posting-tail">3677</span>') process.exit(4);
"""
    subprocess.run(["node", "-e", script], check=True)
