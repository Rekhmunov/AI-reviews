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
        dataset: {},
        classList: {
          _set: new Set(),
          add(cls) { this._set.add(cls); },
          remove(cls) { this._set.delete(cls); },
        },
        setAttribute(name, val) {
          if (name === "title") this.title = val;
        },
        getAttribute(name) {
          if (name === "title") return this.title;
          return null;
        },
        removeAttribute(name) {
          if (name === "title") this.title = "";
        },
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
    "ozonFbsContainerAuthModal",
    "ozonFbsContainerRebindModal",
  ];
  ids.forEach((id) => el(id, id.includes("Check") ? "input" : "div"));
  el("ozonFbsContainerAuthModal").classList = {
    _set: new Set(["hidden"]),
    add(cls) { this._set.add(cls); },
    remove(cls) { this._set.delete(cls); },
    contains(cls) { return this._set.has(cls); },
  };

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

function loadBindModule(dom, opts = {}) {
  const srcPath = path.join(__dirname, "..", "web_static", "ozon_fbs_container_bind.js");
  const src = fs.readFileSync(srcPath, "utf8");
  const bindResponse = opts.bindResponse || null;
  const cleared = { kiz: [], pick: [] };
  const sandbox = {
    window: {
      supplyDetailState: { supplyId: "S1", sourceId: 1 },
      ozonFbsKizState: { rows: [] },
      ozonFbsPickState: { rows: [] },
      esc: (s) => String(s || ""),
      _ozonFbsKizSetInfo() {},
      _ozonFbsPickSetInfo() {},
      clearOzonFbsKizRow(pn) {
        cleared.kiz.push(String(pn));
        const row = (sandbox.window.ozonFbsKizState.rows || []).find(
          (r) => String(r.posting_number) === String(pn)
        );
        if (row) {
          row.kiz_codes = [""];
          row.kiz_status = "empty";
        }
      },
      clearOzonFbsPickVerify(pn) {
        cleared.pick.push(String(pn));
        const row = (sandbox.window.ozonFbsPickState.rows || []).find(
          (r) => String(r.posting_number) === String(pn)
        );
        if (row) {
          row.pick_verified = false;
          row.pick_barcode = "";
        }
      },
      renderOzonFbsKizTable() {},
      renderOzonFbsPickVerifyTable() {},
    },
    document: dom.document,
    URLSearchParams: global.URLSearchParams,
    fetch: async (url) => {
      if (String(url).includes("/containers/reconcile")) {
        return { ok: true, status: 200, json: async () => ({ binds: {}, changes: [] }) };
      }
      if (String(url).includes("/containers/bind")) {
        if (bindResponse) {
          return {
            ok: !!bindResponse.ok,
            status: Number(bindResponse.status) || (bindResponse.ok ? 200 : 500),
            json: async () => bindResponse.body || {},
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            container_id: 202174459906000,
            container_barcode: "202174459906000",
            container_synced: true,
          }),
        };
      }
      return {
        ok: true,
        status: 200,
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
      };
    },
    setTimeout(fn) {
      fn();
    },
    console,
  };
  sandbox.window.window = sandbox.window;
  sandbox.cleared = cleared;
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

  // maybeBind skips until sticker + successful KIZ scan
  state.activeId = 202174459906000;
  state.activeBarcode = "202174459906000";
  win.ozonFbsKizState.rows = [{ posting_number: "P-1", kiz_codes: [""] }];
  const bindBeforeScan = await win._ozonFbsContainerMaybeBind("kiz", "P-1");
  assert(bindBeforeScan === true, "maybeBind no-op before successful scan");
  assert(!win.ozonFbsKizState.rows[0].container_id, "no container bind before KIZ");

  win.ozonFbsKizState.rows[0].sticker_barcode = "123";
  win.ozonFbsKizState.rows[0].kiz_codes = ["01abc"];
  await win._ozonFbsContainerMaybeBind("kiz", "P-1");
  assert(
    win.ozonFbsKizState.rows[0].container_id === 202174459906000,
    "container bind after successful KIZ"
  );

  // 401 on bind: drop optimistic ГМ + clear KIZ, show auth modal
  {
    const dom401 = makeDom();
    const win401 = loadBindModule(dom401, {
      bindResponse: {
        ok: false,
        status: 401,
        body: { detail: "Требуется авторизация" },
      },
    });
    win401.ozonFbsContainerBindState.hasContainers = true;
    win401.ozonFbsContainerBindState.activeId = 202174459906000;
    win401.ozonFbsContainerBindState.activeBarcode = "202174459906000";
    win401.ozonFbsContainerBindState.byId.set("202174459906000", {
      container_id: 202174459906000,
      can_fill: true,
      available_actions: ["fill"],
    });
    win401.ozonFbsKizState.rows = [{
      posting_number: "P-AUTH",
      sticker_barcode: "ST1",
      kiz_codes: ["01mark"],
      kiz_status: "ok",
      container_id: 202174459906000,
      container_barcode: "202174459906000",
      container_synced: false,
      container_sync_error: "",
    }];
    await win401._ozonFbsContainerRunBindAndRefresh(
      "kiz",
      "P-AUTH",
      202174459906000,
      "202174459906000",
      null
    );
    const row = win401.ozonFbsKizState.rows[0];
    assert(!row.container_id, "401 clears optimistic container_id (kiz)");
    assert(!row.container_barcode, "401 clears optimistic container_barcode (kiz)");
    assert(row.kiz_codes[0] === "", "401 clears scanned KIZ");
    assert(
      !dom401.nodes.get("ozonFbsContainerAuthModal").classList.contains("hidden"),
      "401 opens auth modal"
    );
  }

  // 401 on bind for pick: clear scanned product barcode (no KIZ)
  {
    const domPick = makeDom();
    const winPick = loadBindModule(domPick, {
      bindResponse: {
        ok: false,
        status: 401,
        body: { detail: "Требуется авторизация" },
      },
    });
    winPick.ozonFbsPickState.rows = [{
      posting_number: "P-PICK",
      sticker_barcode: "ST2",
      pick_verified: true,
      pick_barcode: "4601234567890",
      container_id: 202174459906000,
      container_barcode: "202174459906000",
      container_synced: false,
      container_sync_error: "",
    }];
    await winPick._ozonFbsContainerRunBindAndRefresh(
      "pick",
      "P-PICK",
      202174459906000,
      "202174459906000",
      null
    );
    const row = winPick.ozonFbsPickState.rows[0];
    assert(!row.container_id, "401 clears optimistic container_id (pick)");
    assert(!row.pick_verified, "401 clears pick_verified");
    assert(row.pick_barcode === "", "401 clears scanned product barcode");
    assert(
      !domPick.nodes.get("ozonFbsContainerAuthModal").classList.contains("hidden"),
      "401 opens auth modal for pick"
    );
  }

  // Non-401 bind error still keeps optimistic bind
  {
    const domFail = makeDom();
    const winFail = loadBindModule(domFail, {
      bindResponse: {
        ok: false,
        status: 502,
        body: { detail: "Ozon temporarily unavailable" },
      },
    });
    winFail.ozonFbsKizState.rows = [{
      posting_number: "P-502",
      sticker_barcode: "ST3",
      kiz_codes: ["01keep"],
      container_id: null,
      container_barcode: "",
    }];
    await winFail._ozonFbsContainerRunBindAndRefresh(
      "kiz",
      "P-502",
      202174459906000,
      "202174459906000",
      null
    );
    const row = winFail.ozonFbsKizState.rows[0];
    assert(row.container_id === 202174459906000, "non-401 keeps optimistic bind");
    assert(row.kiz_codes[0] === "01keep", "non-401 does not clear KIZ");
    assert(
      domFail.nodes.get("ozonFbsContainerAuthModal").classList.contains("hidden"),
      "non-401 does not open auth modal"
    );
  }

  // Session detector must not treat non-401 statuses as auth loss
  {
    const winDet = loadBindModule(makeDom());
    const e400 = new Error("Требуется авторизация");
    e400.status = 400;
    assert(
      winDet._ozonFbsContainerIsSessionExpiredError(e400) === false,
      "400 with auth-like text is not session expiry"
    );
    const e401 = new Error("nope");
    e401.status = 401;
    assert(
      winDet._ozonFbsContainerIsSessionExpiredError(e401) === true,
      "401 status is session expiry"
    );
  }

  console.log("test_ozon_fbs_container_bind_ui.js: all checks passed");
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
