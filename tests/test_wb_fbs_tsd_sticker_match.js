/**
 * Regression: TSD findBySticker must not treat one row as ambiguous when
 * sticker_barcode === sticker_lower_barcode (Ozon upper/lower labels).
 * Run: node tests/test_wb_fbs_tsd_sticker_match.js
 */
"use strict";

const fs = require("fs");
const path = require("path");

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

const src = fs.readFileSync(
  path.join(__dirname, "..", "web_static", "wb_fbs_tsd.js"),
  "utf8"
);

assert(src.includes("function findBySticker"), "findBySticker present");
assert(
  src.includes("else if (bcLow && scanKey(bcLow) === rawKey)"),
  "upper else lower — exclusive barcode match"
);
assert(src.includes("seenBc"), "dedupe barcode hits by row id");
assert(src.includes("seenFuzzy"), "dedupe fuzzy hits by row id");

// Behavioral clone of the fixed barcode branch (keeps the bug from returning).
function scanKey(s) {
  return String(s || "")
    .trim()
    .toLocaleLowerCase("en-US");
}
function normalizeScan(raw) {
  return String(raw || "").replace(/\s+/g, "").trim();
}
function rowScanId(row) {
  return String(row.posting_number || row.order_id || "").trim();
}
function findByStickerBarcode(rows, raw) {
  const scan = normalizeScan(raw);
  if (!scan) return { row: null, ambiguous: false };
  const rawKey = scanKey(scan);
  const byBarcode = [];
  const seenBc = new Set();
  for (const row of rows || []) {
    const id = rowScanId(row);
    const bc = normalizeScan(row.sticker_barcode);
    const bcLow = normalizeScan(row.sticker_lower_barcode);
    let hit = false;
    if (bc && scanKey(bc) === rawKey) hit = true;
    else if (bcLow && scanKey(bcLow) === rawKey) hit = true;
    if (!hit) continue;
    if (id && seenBc.has(id)) continue;
    if (id) seenBc.add(id);
    byBarcode.push(row);
  }
  if (byBarcode.length === 1) return { row: byBarcode[0], ambiguous: false };
  if (byBarcode.length > 1) return { row: null, ambiguous: true, matches: byBarcode };
  return { row: null, ambiguous: false };
}

const sameUpperLower = {
  posting_number: "36172548-0600-2",
  sticker_barcode: "401959881048000",
  sticker_lower_barcode: "401959881048000",
};
const other = {
  posting_number: "36172548-0600-1",
  sticker_barcode: "401959881047000",
  sticker_lower_barcode: "401959881047000",
};

const hit = findByStickerBarcode([other, sameUpperLower], "401959881048000");
assert(hit.row && hit.row.posting_number === "36172548-0600-2", "unique hit");
assert(!hit.ambiguous, "same upper/lower must not be ambiguous");

const amb = findByStickerBarcode(
  [
    { posting_number: "A", sticker_barcode: "X", sticker_lower_barcode: "" },
    { posting_number: "B", sticker_barcode: "X", sticker_lower_barcode: "" },
  ],
  "X"
);
assert(amb.ambiguous, "two different postings with same barcode stay ambiguous");

console.log("ok - wb_fbs_tsd_sticker_match");
