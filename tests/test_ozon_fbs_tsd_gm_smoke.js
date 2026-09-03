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
assert(src.includes("Стикер:"), "Стикер label in scanned card details");
assert(src.includes("renderOzonOrderCardBodyHtml"), "shared Ozon card body for search+scanned");
assert(src.includes("renderOzonOrderCardHtml"), "shared Ozon full card for search+filters+scanned");
assert(src.includes("selectable: true"), "Ozon browse/filter cards are selectable scanned cards");
assert(!src.includes("tsd-search-item-ozon"), "Ozon browse no longer uses separate search-item-ozon wrapper");
assert(
  src.includes("${postingHtml}${stickerHtml}${gmHtml}${markOrSkuHtml}"),
  "Ozon details order: posting → sticker → GM → barcode/kiz"
);
assert(src.includes("tsd-scanned-gm-code"), "full GM barcode in scanned card");
assert(src.includes(">ГМ:</span>"), "GM label before full code");
assert(src.includes("clearScannedOrderAll"), "one clear-all for scanned order");
assert(src.includes('data-action="clear-scanned-all"'), "clear-all action wired");
assert(src.includes("containers/unbind"), "unbind on clear-all");
assert(src.includes("tsd-scanned-item-ozon"), "ozon scanned card class");
assert(!src.includes("gmBadgeForRow"), "old GM № badge helper removed");

// Ozon scan chrome: no «Шаг 1»; banners dismissible + GM refresh clears on scan
assert(src.includes("clearOnScan"), "GM refresh banner clears on scan");
assert(src.includes("o.dismissible !== false"), "banners dismissible by default");
assert(src.includes("o.clearOnScan !== false"), "banners clear on next action by default");
assert(src.includes("function clearBanner"), "clearBanner helper");
assert(src.includes("tsd-banner-dismiss") || src.includes("dismiss-banner"), "banner dismiss control");
assert(!src.includes("Шаг 1"), "Шаг 1 removed from TSD scan chrome");


// GM controls beside scan input: green + and refresh
assert(src.includes("tsd-gm-side"), "GM side icons beside scan field");
assert(src.includes("tsd-gm-icon-btn"), "square GM icon buttons");
assert(src.includes("tsdGmAdd"), "add GM control id");
assert(src.includes("startGmScan"), "shared startGmScan handler");
assert(
  src.includes("else if (bcLow && scanKey(bcLow) === rawKey)"),
  "sticker upper/lower exclusive match (false ambiguous fix)"
);
assert(src.includes("seenBc"), "sticker barcode matches deduped");
assert(src.includes("Сканируйте QR грузоместа"), "awaiting-scan prompt above input");
assert(!src.includes("Отсканируйте QR грузоместа"), "no blue banner for GM scan prompt");
assert(!src.includes("Отсканируйте QR другого грузоместа"), "no blue banner for GM change prompt");
assert(src.includes('function renderGmBarHtml') || src.includes("renderGmBarHtml()"), "legacy GM bar hook kept empty");
assert(!src.includes("tsd-gm-bar-actions"), "old GM actions row removed");
assert(!src.includes("Грузоместо не выбрано"), "top idle GM block copy removed");

// WB FBS: same detailed card as Ozon for scanned / search / filters
assert(src.includes("renderWbOrderCardHtml"), "WB shared order card helper");
assert(src.includes("Заказ:"), "WB card shows Заказ label");
assert(src.includes("formatBoldLastDigits"), "WB sticker last-4 highlight");
assert(src.includes("tsd-scanned-item-wb"), "WB scanned card class");
assert(!src.includes("Шаг 2"), "Шаг 2 removed from scan chrome");

console.log("ok - ozon_fbs_tsd_gm_smoke");
