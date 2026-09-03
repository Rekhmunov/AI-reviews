/**
 * Smoke tests for Ozon FBS TSD GM gates (phase 1).
 * Run: node tests/test_ozon_fbs_tsd_gm_smoke.js
 */
"use strict";

const fs = require("fs");
const path = require("path");

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

const tsdPath = path.join(__dirname, "..", "web_static", "wb_fbs_tsd.js");
const htmlPath = path.join(__dirname, "..", "web_templates", "wb_fbs_tsd.html");
const src = fs.readFileSync(tsdPath, "utf8");
const html = fs.readFileSync(htmlPath, "utf8");

assert(src.includes("state.gm"), "gm state present");
assert(src.includes("function gmUiVisible"), "gmUiVisible present");
assert(src.includes("function loadGmContainers"), "loadGmContainers present");
assert(src.includes("function maybeBindGmAfterSuccess"), "bind after success present");
assert(src.includes("function handleGmScan"), "handleGmScan present");
assert(src.includes("awaitingScan"), "awaitingScan mode present");
assert(src.includes("/api/ozon-fbs/supplies/"), "uses ozon containers API");
assert(src.includes("containers/bind"), "uses bind endpoint");
assert(
  /if\s*\(\s*!isOzon\(\)\s*\)\s*\{[\s\S]*?resetGmState/.test(src) ||
    src.includes("if (!isOzon()) {\n      resetGmState"),
  "loadGmContainers gated by isOzon"
);
assert(src.includes("if (!isOzon()) return false;\n    if (state.route.view !== \"scan\")"), "gmUiVisible ozon+scan gate");
assert(!src.includes("ozon_fbs_container_bind.js"), "does not mount desktop bind module");
assert(html.includes("ozon_fbs_container_match.js"), "TSD loads match helper");
assert(html.includes("wb_fbs_tsd.js"), "TSD loads main script");

// WB path must not fetch containers unless isOzon — loadGmContainers starts with isOzon guard.
const loadIdx = src.indexOf("async function loadGmContainers");
assert(loadIdx > 0, "loadGmContainers found");
const loadSlice = src.slice(loadIdx, loadIdx + 400);
assert(loadSlice.includes("if (!isOzon())"), "WB cannot load GM containers");

assert(src.includes("loadGen"), "stale GM load generation guard");
assert(src.includes("closeGmRebind"), "rebind sheet close helper");
assert(src.includes("Keep active GM within the same supply"), "active GM kept across kiz/pick via hub");

console.log("ok - ozon_fbs_tsd_gm_smoke");
