/**
 * Unit tests for ozon_fbs_container_match.js (+ phase-0 regression gates).
 * Run: node tests/test_ozon_fbs_container_match.js
 *
 * Phase 0 regression checklist (automated here / manual on device):
 * 1. WB TSD kiz/pick — GM UI must not mount (isOzon gate).
 * 2. Ozon TSD without fillable containers — GM bar hidden.
 * 3. Ozon TSD with fillable containers — GM bar available.
 * 4. awaitingScan matches only GM QR, never order stickers.
 * 5. Existing KIZ/SKU scan flow unchanged when GM inactive.
 */
"use strict";

const path = require("path");
const match = require(path.join(
  __dirname,
  "..",
  "web_static",
  "ozon_fbs_container_match.js"
));

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

function assertEq(a, b, msg) {
  if (a !== b) throw new Error(msg || `expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
}

/** Same gate TSD uses: Ozon only + at least one fillable GM. */
function gmUiShouldShow(isOzonMp, containers) {
  if (!isOzonMp) return false;
  const list = Array.isArray(containers) ? containers : [];
  return list.some((c) => match.containerAcceptsFill(c));
}

function run() {
  assertEq(match.normalizeContainerScan(" 202174459906000 "), "202174459906000");
  assertEq(match.normalizeContainerScan("GM-99"), "99");
  assertEq(match.normalizeContainerScan("abc"), "abc");
  assertEq(match.normalizeContainerScan(""), "");

  const rows = [
    {
      container_id: 202174459906000,
      container_number: 1,
      status: "new",
      can_fill: true,
    },
    {
      container_id: 99,
      container_number: 2,
      container_barcode: "990011",
      status: "approved",
      can_fill: false,
    },
    {
      container_id: 55,
      container_number: 1234567,
      status: "new",
      can_fill: true,
    },
  ];

  assertEq(
    match.matchContainerByScan(rows, "202174459906000").container_id,
    202174459906000,
    "match by container_id"
  );
  assertEq(
    match.matchContainerByScan(rows, " 202174459906000 ").container_id,
    202174459906000,
    "match trimmed"
  );
  assertEq(
    match.matchContainerByScan(rows, "990011").container_id,
    99,
    "match by barcode"
  );
  assertEq(
    match.matchContainerByScan(rows, "1234567").container_id,
    55,
    "match by long container_number"
  );
  assertEq(match.matchContainerByScan(rows, "2"), null, "short number must not match");
  assertEq(match.matchContainerByScan(rows, "999"), null, "miss");
  assertEq(match.matchContainerByScan([], "1"), null, "empty list");

  assert(match.containerAcceptsFill(rows[0]), "can_fill true");
  assert(!match.containerAcceptsFill(rows[1]), "can_fill false / approved");
  assert(
    !match.containerAcceptsFill({ container_id: 1, status: "shipped" }),
    "shipped locked"
  );
  assert(
    match.containerAcceptsFill({ container_id: 1, status: "new" }),
    "new without can_fill still open"
  );

  // Phase 0 gates
  assert(!gmUiShouldShow(false, rows), "WB marketplace: hide GM");
  assert(!gmUiShouldShow(true, []), "Ozon, no containers: hide GM");
  assert(
    !gmUiShouldShow(true, [rows[1]]),
    "Ozon, only non-fillable: hide GM"
  );
  assert(gmUiShouldShow(true, rows), "Ozon with fillable: show GM");

  console.log("ok - ozon_fbs_container_match");
}

run();
