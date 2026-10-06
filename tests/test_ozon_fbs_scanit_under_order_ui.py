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
    assert "ozon-fbs-scanit-line" in js
    assert "ozon-fbs-posting-tail" in js[js.find("function formatOzonScanitHtml") :]

    sd = js[
        js.find('<td class="wb-fbs-sd-td-order">') : js.find(
            '<td class="wb-fbs-sd-td-product">'
        )
    ]
    assert "formatOzonPostingNumberHtml(pn)" in sd
    assert "_ozonFbsScanitUnderOrderHtml(o)" in sd
    assert sd.find("formatOzonPostingNumberHtml(pn)") < sd.find(
        "_ozonFbsScanitUnderOrderHtml(o)"
    )

    col = _fn_src("_ozonFbsModalPostingColHtml", until="_ozonFbsKizRowIsEmpty")
    assert "_ozonFbsScanitUnderOrderHtml(row)" in col
    assert col.find("formatOzonPostingNumberHtml(pn)") < col.find(
        "_ozonFbsScanitUnderOrderHtml(row)"
    )

    helper = _fn_src("_ozonFbsScanitUnderOrderHtml", until="detailText")
    assert "row?.sticker_scanit" in helper
    assert "ozon-fbs-scanit-line" in helper
    assert "—" not in helper

    cancelled = _fn_src(
        "renderOzonFbsCancelledOrdersTable", until="refreshOzonFbsCancelledOrders"
    )
    assert "_ozonFbsScanitUnderOrderHtml" not in cancelled

    lookup = js[
        js.find("function renderTable(") : js.find("async function loadPostings(")
    ]
    assert "_ozonFbsScanitUnderOrderHtml" not in lookup

    # Existing 22px tail already covers scanit via .wb-fbs-sd-order-id
    assert ".wb-fbs-sd-order-id .ozon-fbs-posting-tail" in css
    assert "ozon_fbs.js?v=210" in html


def test_format_ozon_scanit_html_last_four() -> None:
    js = JS.read_text(encoding="utf-8")
    start = js.find("function formatOzonScanitHtml")
    end = js.find("function _ozonFbsScanitUnderOrderHtml")
    assert start >= 0 and end > start
    fn = js[start:end]
    script = f"""
function esc(s) {{ return String(s ?? ""); }}
{fn}
const out = formatOzonScanitHtml("ii50127379391");
if (out !== 'ii5012737<span class="ozon-fbs-posting-tail">9391</span>') {{
  console.error("unexpected:", out);
  process.exit(1);
}}
if (formatOzonScanitHtml("") !== "") process.exit(2);
if (formatOzonScanitHtml("   ") !== "") process.exit(3);
if (formatOzonScanitHtml("9391") !== '<span class="ozon-fbs-posting-tail">9391</span>') process.exit(4);
"""
    subprocess.run(["node", "-e", script], check=True)
