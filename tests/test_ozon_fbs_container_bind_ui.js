/**
 * Lightweight regression checks for ozon_fbs_container_bind.js active-container UI.
 * Run: node tests/test_ozon_fbs_container_bind_ui.js
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

function makeDom() {
  const nodes = new Map();
  let idCounter = 0;
  function el(id, tag = "div") {
    if (!nodes.has(id)) {
      nodes.set(id, {
        id,
        tag,
        hidden: false,
        checked: false,
        textContent: "",
        title: "",
        placeholder: "",
        value: "",
        focus() {},
        select() {},
      });
    }
    return nodes.get(id);
  }
  const ids = [
    "ozonFbsKizContainerScanRow",
    "ozonFbsKizContainerScanCheck",
    "ozonFbsKizContainerActive",
    "ozonFbsKizContainerActiveNum",
    "ozonFbsPickContainerScanRow",
    "ozonFbsPickContainerScanCheck",
    "ozonFbsPickContainerActive",
    "ozonFbsPickContainerActiveNum",
    "ozonFbsKizStickerScan",
    "ozonFbsPickStickerScan",
  ];
  ids.forEach((id) => el(id, id.includes("Check") ? "input" : "div"));

  return {
    nodes,
    document: {
      getElementById(id) {
        return nodes.get(id) || null;
      },
      querySelectorAll() {
        return [];
      },
    },
  };
}

function loadBindModule(dom) {
  const srcPath = path.join(__dirname, "..", "web_static", "ozon_fbs_container_bind.js");
  const src = fs.readFileSync(srcPath, "utf8");
  const sandbox = {
    window: {
      supplyDetailState: { supplyId: "S1", sourceId: 1 },
      ozonFbsKizState: { rows: [] },
      ozonFbsPickState: { rows: [] },
      esc: (s) => String(s || ""),
      _ozonFbsKizSetInfo() {},
      _ozonFbsPickSetInfo() {},
    },
    document: dom.document,
    URLSearchParams: global.URLSearchParams,
    fetch: async () => ({
      ok: true,
      json: async () => ({
        items: [
          {
            container_id: 202174459906000,
            container_number: 1,
            status: "new",
            can_fill: true,
            available_actions: ["fill", "approve"],
          },
          {
            container_id: 99,
            container_number: 2,
            status: "approved",
            can_fill: false,
            available_actions: ["get_label_container"],
          },
        ],
      }),
    }),
    setTimeout(fn) {
      fn();
    },
    console,
  };
  sandbox.window.window = sandbox.window;
  vm.runInNewContext(src, sandbox, { filename: "ozon_fbs_container_bind.js" });
  return sandbox.window;
}

async function run() {
  const dom = makeDom();
  const win = loadBindModule(dom);
  const state = win.ozonFbsContainerBindState;

  await win._ozonFbsContainerPrepareModal("kiz");
  assert(dom.nodes.get("ozonFbsKizContainerScanRow").hidden === false, "row visible when containers exist");
  assert(dom.nodes.get("ozonFbsKizContainerActive").hidden === true, "active hidden initially");

  await win._ozonFbsContainerHandleScan("kiz", "202174459906000");
  assert(state.activeId === 202174459906000, "active id set after scan");
  assert(dom.nodes.get("ozonFbsKizContainerActive").hidden === false, "active badge visible");
  assert(
    dom.nodes.get("ozonFbsKizContainerActiveNum").textContent === "202174459906000",
    "active number shown"
  );

  win.clearOzonFbsActiveContainer("kiz");
  assert(state.activeId === null, "active cleared by X");
  assert(dom.nodes.get("ozonFbsKizContainerActive").hidden === true, "active badge hidden after clear");

  await win._ozonFbsContainerHandleScan("kiz", "202174459906000");
  assert(state.activeId === 202174459906000, "active restored after rescan");

  win._ozonFbsContainerClearOnModalClose();
  assert(state.activeId === null, "active cleared on modal close");
  assert(dom.nodes.get("ozonFbsKizContainerScanCheck").checked === false, "checkbox unchecked on close");
  assert(dom.nodes.get("ozonFbsPickContainerScanCheck").checked === false, "pick checkbox unchecked on close");

  // Locked container rejected
  const locked = await win._ozonFbsContainerHandleScan("kiz", "99");
  assert(locked === false, "approved container scan rejected");
  assert(state.activeId === null, "active stays null after locked scan");

  // maybeBind skips when no active
  state.activeId = null;
  const bindOk = await win._ozonFbsContainerMaybeBind("kiz", "P-1");
  assert(bindOk === true, "maybeBind no-op without active");

  console.log("test_ozon_fbs_container_bind_ui.js: all checks passed");
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
