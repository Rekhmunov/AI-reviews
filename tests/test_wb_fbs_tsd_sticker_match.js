/**
 * Regression: sticker match must not treat one row as ambiguous when
 * sticker_barcode === sticker_lower_barcode (Ozon upper/lower labels).
 * Covers TSD Ozon/WB for KIZ + unmarked, and desktop Ozon/WB modals.
 * Run: node tests/test_wb_fbs_tsd_sticker_match.js
 */
"use strict";

const fs = require("fs");
const path = require("path");

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

const tsdSrc = fs.readFileSync(
  path.join(__dirname, "..", "web_static", "wb_fbs_tsd.js"),
  "utf8"
);
const ozonSrc = fs.readFileSync(
  path.join(__dirname, "..", "web_static", "ozon_fbs.js"),
  "utf8"
);
const appSrc = fs.readFileSync(
  path.join(__dirname, "..", "web_static", "app.js"),
  "utf8"
);

assert(tsdSrc.includes("function findBySticker"), "TSD findBySticker present");
assert(
  tsdSrc.includes("else if (bcLow && scanKey(bcLow) === rawKey)"),
  "TSD upper else lower — exclusive barcode match"
);
assert(tsdSrc.includes("seenBc"), "TSD barcode matches deduped by row id");
assert(tsdSrc.includes("seenFuzzy"), "TSD fuzzy matches deduped by row id");

// Shared helper used for both KIZ and unmarked scan Enter handlers.
const stickerEnterIdx = tsdSrc.indexOf(
  'state.step === "sticker" || !state.pendingOrderId'
);
assert(stickerEnterIdx > 0, "sticker step enter handler");
const enterChunk = tsdSrc.slice(stickerEnterIdx, stickerEnterIdx + 500);
assert(enterChunk.includes("findBySticker(rows, raw)"), "scan Enter uses findBySticker");
assert(
  enterChunk.includes('mode === "kiz" ? state.kizRows : state.pickRows'),
  "KIZ and pick modes share findBySticker"
);

assert(
  ozonSrc.includes(
    "else if (fields.lower && _ozonFbsStickerScanKey(fields.lower) === rawKey)"
  ),
  "Ozon desktop modal upper else lower"
);
assert(ozonSrc.includes("const seenBc = new Set();"), "Ozon desktop barcode dedupe");
assert(
  ozonSrc.includes("function _ozonFbsKizFindBySticker"),
  "Ozon KIZ modal uses shared finder"
);
assert(
  ozonSrc.includes("function _ozonFbsPickFindBySticker"),
  "Ozon pick modal uses shared finder"
);

assert(appSrc.includes("function _wbFbsKizFindBySticker"), "WB KIZ modal finder");
assert(appSrc.includes("function _wbFbsPickFindBySticker"), "WB pick modal finder");
assert(
  appSrc
    .split("function _wbFbsKizFindBySticker")[1]
    .slice(0, 800)
    .includes("const seenBc = new Set();"),
  "WB KIZ barcode dedupe"
);
assert(
  appSrc
    .split("function _wbFbsPickFindBySticker")[1]
    .slice(0, 800)
    .includes("const seenBc = new Set();"),
  "WB pick barcode dedupe"
);

// Behavioral clone of the fixed TSD barcode branch.
function scanKey(s) {
  return String(s || "")
    .trim()
    .toLocaleLowerCase("en-US");
}
function normalizeScan(raw) {
  return String(raw || "").replace(/\s+/g, "").trim();
}
function rowScanId(row, isOzon) {
  if (isOzon) return String(row.posting_number || row.order_id || "").trim();
  const oid = Number(row.order_id);
  return Number.isFinite(oid) && oid > 0 ? String(oid) : "";
}
function findByStickerBarcode(rows, raw, isOzon) {
  const scan = normalizeScan(raw);
  if (!scan) return { row: null, ambiguous: false };
  const rawKey = scanKey(scan);
  const byBarcode = [];
  const seenBc = new Set();
  for (const row of rows || []) {
    const id = rowScanId(row, isOzon);
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

// Ozon unmarked / KIZ: upper === lower on one posting must resolve uniquely.
const ozonRows = [
  {
    posting_number: "36172548-0600-1",
    sticker_barcode: "401959881047000",
    sticker_lower_barcode: "401959881047000",
  },
  {
    posting_number: "36172548-0600-2",
    sticker_barcode: "401959881048000",
    sticker_lower_barcode: "401959881048000",
  },
];
const ozonHit = findByStickerBarcode(ozonRows, "401959881048000", true);
assert(ozonHit.row && ozonHit.row.posting_number === "36172548-0600-2", "Ozon unique hit");
assert(!ozonHit.ambiguous, "Ozon same upper/lower must not be ambiguous");

// WB TSD-style rows: order_id + sticker_barcode only (no lower).
const wbRows = [
  { order_id: 1001, sticker_barcode: "!uKEtQZVx", sticker_lower_barcode: "" },
  { order_id: 1002, sticker_barcode: "!uKEtQZVy", sticker_lower_barcode: "" },
  // Duplicate object for same order must not become ambiguous after dedupe.
  { order_id: 1002, sticker_barcode: "!uKEtQZVy", sticker_lower_barcode: "" },
];
const wbHit = findByStickerBarcode(wbRows, "!uKEtQZVy", false);
assert(wbHit.row && Number(wbHit.row.order_id) === 1002, "WB unique hit");
assert(!wbHit.ambiguous, "WB duplicate row objects deduped");

const amb = findByStickerBarcode(
  [
    { posting_number: "A", sticker_barcode: "X", sticker_lower_barcode: "" },
    { posting_number: "B", sticker_barcode: "X", sticker_lower_barcode: "" },
  ],
  "X",
  true
);
assert(amb.ambiguous, "two different postings with same barcode stay ambiguous");

console.log("ok - wb_fbs_tsd_sticker_match");
