/**
 * Regression: ШК грузоместа cell commits on Save flush / blur without Enter.
 * Run: node tests/test_ozon_fbs_container_cell_commit.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

async function main() {
  const src = fs.readFileSync(
    path.join(__dirname, "..", "web_static", "ozon_fbs_container_bind.js"),
    "utf8"
  );
  const rows = [{
    posting_number: "PN-CELL-1",
    container_id: null,
    container_barcode: "",
    container_synced: false,
    container_sync_error: "",
  }];
  const binds = [];
  const input = {
    value: "555001",
    classList: { contains: (c) => c === "ozon-fbs-container-input" },
    isConnected: true,
    getAttribute(name) {
      if (name === "data-posting") return "PN-CELL-1";
      if (name === "data-mode") return "kiz";
      return null;
    },
  };
  const tbody = {
    querySelectorAll(sel) {
      return String(sel).includes("ozon-fbs-container-input") ? [input] : [];
    },
  };
  const sandbox = {
    window: {
      supplyDetailState: { supplyId: "S1", sourceId: 1 },
      ozonFbsKizState: { rows },
      ozonFbsPickState: { rows: [] },
      renderOzonFbsKizTable() {},
      renderOzonFbsPickVerifyTable() {},
      _ozonFbsKizSetInfo() {},
      _ozonFbsPickSetInfo() {},
    },
    document: {
      getElementById(id) {
        return id === "ozonFbsKizTbody" ? tbody : null;
      },
      querySelectorAll() {
        return [];
      },
    },
    fetch: async (url, opts = {}) => {
      const u = String(url);
      if (u.includes("/containers/bind")) {
        const body = JSON.parse(opts.body);
        binds.push(body);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            container_id: body.container_id,
            container_barcode: String(body.container_barcode || body.container_id),
            container_synced: true,
            container_sync_error: "",
          }),
        };
      }
      if (u.includes("/containers")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            items: [{
              container_id: "555001",
              container_number: "1",
              status: "new",
              can_fill: true,
            }],
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    },
    setTimeout,
    clearTimeout,
    console,
    URLSearchParams,
  };
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);

  assert(
    typeof sandbox.window._ozonFbsContainerFlushPendingCells === "function",
    "flush helper exported"
  );
  assert(
    typeof sandbox.window.onOzonFbsContainerCellBlur === "function",
    "blur helper exported"
  );

  await sandbox.window._ozonFbsContainerFlushPendingCells("kiz");
  assert(binds.length === 1, "flush should bind typed cell barcode without Enter");
  assert(Number(rows[0].container_id) === 555001, "flush should update row container_id");

  binds.length = 0;
  rows[0].container_id = null;
  rows[0].container_barcode = "";
  rows[0].container_synced = false;
  rows[0].container_sync_error = "";
  input.value = "555001";
  await sandbox.window.onOzonFbsContainerCellBlur({ target: input }, "PN-CELL-1", "kiz");
  assert(binds.length === 1, "blur should bind typed cell barcode");

  console.log("test_ozon_fbs_container_cell_commit.js: ok");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
