/**
 * Smoke tests for Ozon FBS TSD GM phases 0–3.
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
assert(src.includes("if (!isOzon())"), "isOzon gates present");
assert(!src.includes("ozon_fbs_container_bind.js"), "does not mount desktop bind module");
assert(html.includes("ozon_fbs_container_match.js"), "TSD loads match helper");
assert(html.includes("wb_fbs_tsd.js"), "TSD loads main script");

// Phase 0/1
const loadIdx = src.indexOf("async function loadGmContainers");
assert(loadIdx > 0, "loadGmContainers found");
assert(
  src.slice(loadIdx, loadIdx + 400).includes("if (!isOzon())"),
  "WB cannot load GM containers"
);

// Phase 2
assert(src.includes("loadGen"), "stale GM load generation guard");
assert(src.includes("closeGmRebind"), "rebind sheet close helper");
assert(src.includes("ensureActiveGmStillFillable"), "locked mid-shift check");
assert(src.includes("isLockedGmError"), "locked GM error detector");
assert(src.includes("Таймаут загрузки грузомест"), "containers list timeout");
assert(src.includes("hard GM reset on source change"), "source change hard reset");
assert(
  src.includes("container_sync_error") &&
    src.includes("prevId === activeId && !String(row.container_sync_error"),
  "retry bind when sync_error set"
);
assert(
  /if\s*\(\s*!isOzon\(\)\s*\|\|\s*!state\.gm\.activeId/.test(src),
  "silent no-op without activeId"
);

// Phase 3
assert(src.includes("В ГМ ${gmN}") || src.includes("В ГМ ${"), "stats GM counter");
assert(src.includes("tsdFilterNoGm") || html.includes("tsdFilterNoGm"), "filter без ГМ");
assert(src.includes("tsdGmRefresh"), "refresh GM list button");
assert(src.includes("tsdGmAdd"), "add GM plus icon");
assert(src.includes("tsd-gm-icon-add"), "green add GM class");
assert(!src.includes("Сканировать ГМ"), "old GM scan CTA removed");
assert(src.includes("scanFieldRowHtml"), "GM icons beside scan input");
assert(html.includes("Без ГМ"), "filter label in HTML");

assert(src.includes("keepOnFail"), "refresh keeps GM cache on transient fail");
assert(src.includes("Optimistic chrome"), "optimistic badge/counter refresh");
assert(src.includes("rowGmCode"), "GM full code helper");
assert(src.includes("tsd-scanned-gm-code"), "GM code class in scanned card");

assert(src.includes("return to sticker immediately"), "bind after UI reset per TZ");
assert(src.includes("Rebind sheet is modal"), "ignore scans while rebind open");

// Scanned card UX: Отправление + full GM code + one clear-all ×
assert(src.includes("formatOzonPostingHtml"), "posting highlight helper");
assert(src.includes("tsd-posting-hi"), "posting highlight class");
assert(src.includes("Отправление:"), "Отправление label in scanned card");
assert(src.includes("tsd-scanned-gm-code"), "full GM barcode in scanned card");
assert(src.includes(">ГМ:</span>"), "GM label before full code");
assert(src.includes("clearScannedOrderAll"), "one clear-all for scanned order");
assert(src.includes('data-action="clear-scanned-all"'), "clear-all action wired");
assert(src.includes("containers/unbind"), "unbind on clear-all");
assert(src.includes("tsd-scanned-item-ozon"), "ozon scanned card class");
assert(!src.includes("gmBadgeForRow"), "old GM № badge helper removed");

// Ozon scan chrome: no «Шаг 1»; GM refresh banner dismissible + clear on scan
assert(src.includes("clearOnScan"), "GM refresh banner clears on scan");
assert(src.includes("dismissible: true"), "GM refresh banner dismissible");
assert(src.includes("tsd-banner-dismiss") || src.includes("dismiss-banner"), "banner dismiss control");
assert(src.includes('isOzon()\n        ? ""') || src.includes("isOzon()\n        ? \"\""), "Шаг 1 hidden for Ozon");


// GM controls beside scan input: green + and refresh
assert(src.includes("tsd-gm-side"), "GM side icons beside scan field");
assert(src.includes("tsd-gm-icon-btn"), "square GM icon buttons");
assert(src.includes("tsdGmAdd"), "add GM control id");
assert(src.includes("startGmScan"), "shared startGmScan handler");
assert(src.includes('function renderGmBarHtml') || src.includes("renderGmBarHtml()"), "legacy GM bar hook kept empty");
assert(!src.includes("tsd-gm-bar-actions"), "old GM actions row removed");
assert(!src.includes("Грузоместо не выбрано"), "top idle GM block copy removed");

console.log("ok - ozon_fbs_tsd_gm_smoke");
