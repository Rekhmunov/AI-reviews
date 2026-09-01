/**
 * Ozon FBS: optional cargo-place (грузоместо) binding in Marking / Pick Verify.
 * No-op when the supply has no active containers or the operator never scans one.
 */
(function () {
  "use strict";

  const state = {
    hasContainers: false,
    containers: [],
    byId: new Map(),
    activeId: null,
    activeBarcode: "",
    usedInSession: false,
    loading: false,
    rebindResolver: null,
    rebindPayload: null,
    /** Supply id for which activeId is valid — clear on supply change. */
    boundSupplyId: "",
  };

  function esc(s) {
    return typeof window.esc === "function"
      ? window.esc(s)
      : String(s || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
  }

  function normalizeScan(value) {
    const raw = String(value || "").trim();
    if (!raw) return "";
    const digits = raw.replace(/\D+/g, "");
    return digits || raw;
  }

  function csrfHeaders() {
    const h = { "Content-Type": "application/json" };
    if (typeof window.withCsrfHeaders === "function") {
      return window.withCsrfHeaders(h);
    }
    const csrf =
      (typeof window.getCsrfToken === "function" && window.getCsrfToken())
      || (typeof getCsrfToken === "function" && getCsrfToken())
      || "";
    if (csrf) h["X-CSRF-Token"] = csrf;
    return h;
  }

  function supplyIds() {
    const sid = String(window.supplyDetailState?.supplyId || "").trim();
    const sourceId = Number(window.supplyDetailState?.sourceId || window.state?.sourceId || 0) || 0;
    return { sid, sourceId };
  }

  function rerenderMode(mode) {
    if (mode === "kiz" && typeof window.renderOzonFbsKizTable === "function") {
      window.renderOzonFbsKizTable({ skipCollect: true });
    }
    if (mode === "pick" && typeof window.renderOzonFbsPickVerifyTable === "function") {
      window.renderOzonFbsPickVerifyTable();
    }
  }

  function setContainerColumnsVisible(show) {
    document.querySelectorAll(
      "#ozonFbsKizTable .wb-fbs-kiz-col-container, #ozonFbsPickTable .wb-fbs-kiz-col-container"
    ).forEach((el) => {
      el.hidden = !show;
      el.style.display = show ? "" : "none";
    });
  }

  function containerAcceptsFill(c) {
    if (!c || typeof c !== "object") return false;
    if (c.can_fill === false) return false;
    if (c.can_fill === true) return true;
    const st = String(c.status || "").trim().toLowerCase();
    if (["approved", "formed", "ready", "shipped", "closed", "cancelled", "canceled", "deleted"].includes(st)) {
      return false;
    }
    return true;
  }

  function matchContainer(scan) {
    const key = normalizeScan(scan);
    if (!key) return null;
    if (state.byId.has(key)) return state.byId.get(key);
    for (const c of state.containers) {
      const cid = String(c.container_id || "").trim();
      const num = String(c.container_number || "").trim();
      if (cid === key) return c;
      if (num && num === key && key.length >= 6) return c;
    }
    return null;
  }

  function setActive(container) {
    if (!container) {
      state.activeId = null;
      state.activeBarcode = "";
      refreshActiveContainerUi();
      return;
    }
    const cid = Number(container.container_id || 0) || 0;
    state.activeId = cid > 0 ? cid : null;
    state.activeBarcode = String(cid || "").trim();
    if (cid > 0) state.usedInSession = true;
    refreshActiveContainerUi();
  }

  function activeContainerEls(mode) {
    const isKiz = mode === "kiz";
    return {
      row: document.getElementById(isKiz ? "ozonFbsKizContainerScanRow" : "ozonFbsPickContainerScanRow"),
      check: document.getElementById(isKiz ? "ozonFbsKizContainerScanCheck" : "ozonFbsPickContainerScanCheck"),
      active: document.getElementById(isKiz ? "ozonFbsKizContainerActive" : "ozonFbsPickContainerActive"),
      num: document.getElementById(isKiz ? "ozonFbsKizContainerActiveNum" : "ozonFbsPickContainerActiveNum"),
    };
  }

  function activeContainerDisplayText() {
    if (!state.activeId) return "";
    return state.activeBarcode || String(state.activeId);
  }

  function activeContainerTitle() {
    const cur = state.byId.get(String(state.activeId || ""));
    if (!cur) return "Активное грузоместо для сканирования заказов";
    const parts = ["Активное грузоместо для сканирования заказов"];
    const num = Number(cur.container_number || 0);
    if (num > 0) parts.push(`№ ${num}`);
    const st = String(cur.status_label || cur.status || "").trim();
    if (st) parts.push(st);
    return parts.join(" · ");
  }

  function updateActiveContainerUi(mode) {
    const els = activeContainerEls(mode);
    const showRow = !!state.hasContainers;
    if (els.row) els.row.hidden = !showRow;
    const hasActive = showRow && !!state.activeId;
    if (els.active) els.active.hidden = !hasActive;
    if (els.num) {
      els.num.textContent = hasActive ? activeContainerDisplayText() : "";
      els.num.title = hasActive ? activeContainerTitle() : "";
    }
  }

  function refreshActiveContainerUi() {
    updateActiveContainerUi("kiz");
    updateActiveContainerUi("pick");
  }

  function syncCheckboxUi(mode) {
    const els = activeContainerEls(mode);
    const isKiz = mode === "kiz";
    const show = !!state.hasContainers;
    if (els.row) els.row.hidden = !show;
    if (els.check && !show) els.check.checked = false;
    // Mirror Marking / Pick Verify wait lock while rows are still loading.
    const rowsReady = isKiz
      ? !!window.ozonFbsKizState?.rowsReady
      : !!window.ozonFbsPickState?.rowsReady;
    if (els.check) {
      els.check.disabled = !rowsReady;
      if (!rowsReady) els.check.checked = false;
    }
    if (els.row) {
      const tip = "Дождитесь загрузки заказов";
      if (!rowsReady) {
        if (els.row.dataset.waitTitleSaved === undefined) {
          els.row.dataset.waitTitleSaved = els.row.getAttribute("title") || "";
        }
        els.row.classList.add("is-wait-rows");
        els.row.setAttribute("title", tip);
      } else {
        els.row.classList.remove("is-wait-rows");
        const saved = els.row.dataset.waitTitleSaved;
        if (saved !== undefined) {
          if (saved) els.row.setAttribute("title", saved);
          else els.row.removeAttribute("title");
          delete els.row.dataset.waitTitleSaved;
        }
      }
    }
    updateActiveContainerUi(mode);
    setContainerColumnsVisible(show);
  }

  function updateContainerCounters() {
    // Re-apply after every table re-render: new <td> nodes would otherwise stay visible
    // even when the supply has no cargo places (regression for the no-container flow).
    setContainerColumnsVisible(!!state.hasContainers);
    updateOneCounter(window.ozonFbsKizState?.rows || [], "ozonFbsKizContainerCount");
    updateOneCounter(window.ozonFbsPickState?.rows || [], "ozonFbsPickContainerCount");
  }

  function updateOneCounter(rows, elId) {
    const el = document.getElementById(elId);
    if (!el) return;
    const list = Array.isArray(rows) ? rows : [];
    const bound = list.filter((r) => String(r?.container_barcode || "").trim()).length;
    const show = state.hasContainers && (state.usedInSession || bound > 0);
    el.hidden = !show;
    if (!show) {
      el.textContent = "";
      return;
    }
    const total =
      list.filter((r) => !String(r?.cancel_reason_label || "").trim()).length || list.length;
    el.textContent = `Прикреплено к грузоместам ${bound} из ${total}`;
  }

  function containerCellHtml(row, mode) {
    const pn = String(row?.posting_number || "").trim();
    const barcode = String(row?.container_barcode || "").trim();
    const err = String(row?.container_sync_error || "").trim();
    const safePn = esc(pn);
    const modeAttr = esc(mode);
    if (!barcode) {
      return `<div class="ozon-fbs-container-cell is-empty" title="ШК грузоместа не указан">—</div>`;
    }
    return `<div class="ozon-fbs-container-cell${err ? " is-error" : ""}">
      <input type="text" class="ozon-fbs-container-input${err ? " is-error" : ""}"
             data-posting="${safePn}" data-mode="${modeAttr}"
             value="${esc(barcode)}"
             title="${err ? esc(err) : "ШК грузоместа"}"
             onkeydown="onOzonFbsContainerCellKey(event, '${safePn}', '${modeAttr}')" />
      <button type="button" class="ozon-fbs-container-clear" title="Снять грузоместо"
              aria-label="Снять грузоместо"
              onclick="clearOzonFbsContainerBind('${safePn}', '${modeAttr}')">×</button>
      ${err ? `<div class="ozon-fbs-container-err">${esc(err)}</div>` : ""}
    </div>`;
  }

  async function ensureContainersLoaded(force) {
    const { sid, sourceId } = supplyIds();
    if (!sid || !sourceId) {
      state.hasContainers = false;
      state.containers = [];
      state.byId = new Map();
      return false;
    }
    if (!force && state.containers.length && !state.loading) {
      return state.hasContainers;
    }
    state.loading = true;
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers?${params}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Ошибка ${res.status}`);
      const items = Array.isArray(data.items) ? data.items : [];
      state.containers = items;
      state.byId = new Map();
      for (const c of items) {
        const cid = String(c.container_id || "").trim();
        if (cid) state.byId.set(cid, c);
      }
      state.hasContainers = items.length > 0;
      if (!state.hasContainers) {
        setActive(null);
        state.usedInSession = false;
      } else if (state.activeId) {
        const cur = state.byId.get(String(state.activeId));
        if (!cur || !containerAcceptsFill(cur)) setActive(null);
      }
      return state.hasContainers;
    } catch (_e) {
      // Soft-fail: keep marking/pick usable without cargo places.
      state.hasContainers = false;
      state.containers = [];
      state.byId = new Map();
      return false;
    } finally {
      state.loading = false;
      syncCheckboxUi("kiz");
      syncCheckboxUi("pick");
      updateContainerCounters();
    }
  }

  function onContainerScanCheckChange(mode) {
    const isKiz = mode === "kiz";
    const rowsReady = isKiz
      ? !!window.ozonFbsKizState?.rowsReady
      : !!window.ozonFbsPickState?.rowsReady;
    const check = document.getElementById(
      isKiz ? "ozonFbsKizContainerScanCheck" : "ozonFbsPickContainerScanCheck"
    );
    if (!rowsReady) {
      if (check) check.checked = false;
      return;
    }
    const input = document.getElementById(
      isKiz ? "ozonFbsKizStickerScan" : "ozonFbsPickStickerScan"
    );
    if (check?.checked) {
      if (input) {
        input.placeholder = "Сканируйте QR грузоместа";
        setTimeout(() => input.focus(), 30);
      }
      const setInfo = isKiz ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
      if (typeof setInfo === "function") {
        setInfo(
          state.activeId
            ? `Активное грузоместо ${activeContainerDisplayText()}. Отсканируйте QR следующего или снимите галку.`
            : "Отсканируйте QR грузоместа",
          true
        );
      }
    } else if (input) {
      input.placeholder = "Сканируйте QR этикетки Ozon или номер отправления";
    }
  }

  function isContainerScanMode(mode) {
    if (!state.hasContainers) return false;
    const isKiz = mode === "kiz";
    const check = document.getElementById(
      isKiz ? "ozonFbsKizContainerScanCheck" : "ozonFbsPickContainerScanCheck"
    );
    return !!check?.checked;
  }

  async function handleContainerScan(mode, rawScan) {
    const isKiz = mode === "kiz";
    const setInfo = isKiz ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
    const check = document.getElementById(
      isKiz ? "ozonFbsKizContainerScanCheck" : "ozonFbsPickContainerScanCheck"
    );
    const input = document.getElementById(
      isKiz ? "ozonFbsKizStickerScan" : "ozonFbsPickStickerScan"
    );
    await ensureContainersLoaded(false);
    const found = matchContainer(rawScan);
    if (!found) {
      if (typeof setInfo === "function") {
        setInfo(`Грузоместо «${rawScan}» не найдено в этой поставке`, false);
      }
      if (input) input.select();
      return false;
    }
    if (!containerAcceptsFill(found)) {
      if (typeof setInfo === "function") {
        setInfo(
          `Грузоместо ${found.container_id} уже подтверждено — в него нельзя сканировать заказы`,
          false
        );
      }
      if (input) input.select();
      return false;
    }
    setActive(found);
    if (check) check.checked = false;
    if (input) {
      input.value = "";
      input.placeholder = "Сканируйте QR этикетки Ozon или номер отправления";
      setTimeout(() => input.focus(), 40);
    }
    if (typeof setInfo === "function") {
      setInfo(
        `Грузоместо ${activeContainerDisplayText()} выбрано. Сканируйте заказы для него.`,
        true
      );
    }
    updateContainerCounters();
    return true;
  }

  function clearActiveContainer(mode) {
    if (!state.activeId) return;
    setActive(null);
    const isKiz = mode === "kiz";
    const check = document.getElementById(
      isKiz ? "ozonFbsKizContainerScanCheck" : "ozonFbsPickContainerScanCheck"
    );
    const input = document.getElementById(
      isKiz ? "ozonFbsKizStickerScan" : "ozonFbsPickStickerScan"
    );
    if (check?.checked) {
      check.checked = false;
      if (input) {
        input.placeholder = "Сканируйте QR этикетки Ozon или номер отправления";
      }
    }
    const setInfo = isKiz ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
    if (typeof setInfo === "function") {
      setInfo(
        "Сканирование в грузоместо остановлено. Заказы больше не привязываются автоматически.",
        true
      );
    }
  }

  function clearActiveContainerOnModalClose() {
    const hadActive = !!state.activeId;
    setActive(null);
    ["kiz", "pick"].forEach((mode) => {
      const els = activeContainerEls(mode);
      if (els.check) els.check.checked = false;
      const input = document.getElementById(
        mode === "kiz" ? "ozonFbsKizStickerScan" : "ozonFbsPickStickerScan"
      );
      if (input) {
        input.placeholder = "Сканируйте QR этикетки Ozon или номер отправления";
      }
    });
    if (hadActive) refreshActiveContainerUi();
  }

  function openRebindModal({ postingNumber, oldBarcode, newBarcode }) {
    return new Promise((resolve) => {
      state.rebindResolver = resolve;
      state.rebindPayload = { postingNumber, oldBarcode, newBarcode };
      const body = document.getElementById("ozonFbsContainerRebindBody");
      if (body) {
        body.textContent =
          `Заказ ${postingNumber} числится в грузоместе ${oldBarcode}. `
          + `Вы уверены, что хотите привязать его к грузоместу ${newBarcode}?`;
      }
      const modal = document.getElementById("ozonFbsContainerRebindModal");
      if (typeof setModalVisibility === "function") {
        setModalVisibility("ozonFbsContainerRebindModal", true);
      } else if (modal) {
        modal.classList.remove("hidden");
      }
    });
  }

  function closeRebindModal(yes) {
    const modal = document.getElementById("ozonFbsContainerRebindModal");
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsContainerRebindModal", false);
    } else if (modal) {
      modal.classList.add("hidden");
    }
    const resolve = state.rebindResolver;
    state.rebindResolver = null;
    state.rebindPayload = null;
    if (typeof resolve === "function") resolve(!!yes);
  }

  function findRow(mode, postingNumber) {
    const pn = String(postingNumber || "").trim();
    const rows = mode === "kiz"
      ? (window.ozonFbsKizState?.rows || [])
      : (window.ozonFbsPickState?.rows || []);
    return rows.find((r) => String(r.posting_number || "") === pn) || null;
  }

  function applyBindResult(row, data) {
    if (!row || !data) return;
    row.container_id = data.container_id || null;
    row.container_barcode = String(data.container_barcode || "").trim();
    row.container_synced = !!data.container_synced || !!data.synced;
    row.container_sync_error = String(data.error || data.container_sync_error || "").trim();
    if (row.container_barcode) state.usedInSession = true;
  }

  async function bindPosting(postingNumber, containerId, containerBarcode, previousId) {
    const { sid, sourceId } = supplyIds();
    if (!sid || !sourceId) return null;
    const res = await fetch(
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/bind`,
      {
        method: "POST",
        headers: csrfHeaders(),
        body: JSON.stringify({
          source_id: sourceId,
          posting_number: postingNumber,
          container_id: containerId,
          container_barcode: containerBarcode || String(containerId),
          previous_container_id: previousId || null,
        }),
      }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Ошибка ${res.status}`);
    return data;
  }

  async function unbindPosting(postingNumber, containerId) {
    const { sid, sourceId } = supplyIds();
    if (!sid || !sourceId) return null;
    const res = await fetch(
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/unbind`,
      {
        method: "POST",
        headers: csrfHeaders(),
        body: JSON.stringify({
          source_id: sourceId,
          posting_number: postingNumber,
          container_id: containerId || null,
        }),
      }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Ошибка ${res.status}`);
    return data;
  }

  async function runBindAndRefresh(mode, postingNumber, containerId, barcode, previousId) {
    const row = findRow(mode, postingNumber);
    if (!row) return;
    try {
      const data = await bindPosting(postingNumber, containerId, barcode, previousId);
      applyBindResult(row, data);
    } catch (e) {
      // Optimistic local bind (TZ): keep UI bind even if our API/Ozon call fails.
      row.container_id = containerId;
      row.container_barcode = barcode;
      row.container_synced = false;
      row.container_sync_error = String(e.message || e);
      state.usedInSession = true;
    }
    updateContainerCounters();
    rerenderMode(mode);
  }

  /**
   * After sticker identifies a posting, attach to active cargo place in background.
   * Does not block the KIZ/SKU scan prompt (only rebind confirm is awaited).
   * Returns false only when user cancelled rebind.
   */
  async function maybeBindAfterPostingIdentified(mode, postingNumber) {
    if (!state.hasContainers || !state.activeId) return true;
    const active = state.byId.get(String(state.activeId));
    if (active && !containerAcceptsFill(active)) {
      setActive(null);
      const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
      if (typeof setInfo === "function") {
        setInfo(
          `Грузоместо ${active.container_id} уже подтверждено — выберите другое`,
          false
        );
      }
      return true;
    }
    const row = findRow(mode, postingNumber);
    if (!row) return true;
    const prevId = Number(row.container_id || 0) || 0;
    const prevBarcode = String(row.container_barcode || "").trim();
    const nextBarcode = state.activeBarcode || String(state.activeId);
    const activeId = state.activeId;
    if (prevId && prevId !== activeId) {
      const ok = await openRebindModal({
        postingNumber,
        oldBarcode: prevBarcode || String(prevId),
        newBarcode: nextBarcode,
      });
      if (!ok) return false;
    } else if (prevId === activeId && !String(row.container_sync_error || "").trim()) {
      return true;
    }
    // Optimistic UI immediately, then sync in background (fast sticker flow).
    row.container_id = activeId;
    row.container_barcode = nextBarcode;
    row.container_synced = false;
    row.container_sync_error = "";
    state.usedInSession = true;
    updateContainerCounters();
    rerenderMode(mode);
    void runBindAndRefresh(
      mode,
      postingNumber,
      activeId,
      nextBarcode,
      prevId && prevId !== activeId ? prevId : null
    );
    return true;
  }

  async function clearBind(postingNumber, mode) {
    const row = findRow(mode, postingNumber);
    if (!row) return;
    const prevId = Number(row.container_id || 0) || 0;
    try {
      const data = await unbindPosting(postingNumber, prevId || null);
      applyBindResult(row, {
        container_id: null,
        container_barcode: "",
        container_synced: false,
        container_sync_error: data?.error || "",
      });
    } catch (e) {
      row.container_sync_error = String(e.message || e);
    }
    updateContainerCounters();
    rerenderMode(mode);
  }

  async function onContainerCellKey(event, postingNumber, mode) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    const input = event.target;
    const raw = normalizeScan(input?.value);
    if (!raw) return;
    await ensureContainersLoaded(false);
    const found = matchContainer(raw);
    if (!found) {
      const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
      if (typeof setInfo === "function") {
        setInfo(`Грузоместо «${raw}» не найдено в этой поставке`, false);
      }
      return;
    }
    if (!containerAcceptsFill(found)) {
      const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
      if (typeof setInfo === "function") {
        setInfo(
          `Грузоместо ${found.container_id} уже подтверждено — в него нельзя добавить заказ`,
          false
        );
      }
      input.value = String(findRow(mode, postingNumber)?.container_barcode || "");
      return;
    }
    const row = findRow(mode, postingNumber);
    if (!row) return;
    const prevId = Number(row.container_id || 0) || 0;
    const nextId = Number(found.container_id || 0) || 0;
    const nextBarcode = String(nextId);
    if (prevId && prevId !== nextId) {
      const ok = await openRebindModal({
        postingNumber,
        oldBarcode: String(row.container_barcode || prevId),
        newBarcode: nextBarcode,
      });
      if (!ok) {
        input.value = String(row.container_barcode || "");
        return;
      }
    }
    try {
      const data = await bindPosting(
        postingNumber,
        nextId,
        nextBarcode,
        prevId && prevId !== nextId ? prevId : null
      );
      applyBindResult(row, data);
    } catch (e) {
      row.container_id = nextId;
      row.container_barcode = nextBarcode;
      row.container_synced = false;
      row.container_sync_error = String(e.message || e);
    }
    updateContainerCounters();
    rerenderMode(mode);
  }

  function resetForModal(mode) {
    const els = activeContainerEls(mode);
    if (els.check) els.check.checked = false;
    if (!state.hasContainers) setActive(null);
    syncCheckboxUi(mode);
    updateContainerCounters();
  }

  async function prepareForModal(mode) {
    const { sid } = supplyIds();
    // Switching supply must not keep a previous active cargo place.
    if (sid && state.boundSupplyId && state.boundSupplyId !== sid) {
      setActive(null);
      state.usedInSession = false;
    }
    if (sid) state.boundSupplyId = sid;
    state.usedInSession = false;
    // Hide cargo column until we know whether this supply has containers.
    setContainerColumnsVisible(false);
    await ensureContainersLoaded(true);
    // Preserve usedInSession if rows already have binds from DB.
    const rows = mode === "kiz"
      ? (window.ozonFbsKizState?.rows || [])
      : (window.ozonFbsPickState?.rows || []);
    if (rows.some((r) => String(r?.container_barcode || "").trim())) {
      state.usedInSession = true;
    }
    // Active cargo place must still belong to this supply's container list.
    if (state.activeId && !state.byId.has(String(state.activeId))) {
      setActive(null);
    } else if (state.activeId) {
      const cur = state.byId.get(String(state.activeId));
      if (!cur || !containerAcceptsFill(cur)) setActive(null);
    }
    resetForModal(mode);
  }

  function containerErrorsTooltip(errors) {
    const list = Array.isArray(errors) ? errors : [];
    if (!list.length) return "";
    return list
      .slice(0, 8)
      .map((e) => {
        const pn = e.posting_number || "?";
        const err = e.error || "ошибка привязки";
        const bc = e.container_barcode ? ` (${e.container_barcode})` : "";
        return `${pn}${bc}: ${err}`;
      })
      .join("\n");
  }

  async function invalidateContainersCache() {
    return ensureContainersLoaded(true);
  }

  // ── exports (names must match ozon_fbs.js / app.html hooks) ───────────────
  window.ozonFbsContainerBindState = state;
  window._ozonFbsContainerCellHtml = containerCellHtml;
  window._ozonFbsContainerUpdateCounters = updateContainerCounters;
  window._ozonFbsContainerPrepareModal = prepareForModal;
  window._ozonFbsContainerSyncCheckboxUi = syncCheckboxUi;
  window._ozonFbsContainerIsScanMode = isContainerScanMode;
  window._ozonFbsContainerHandleScan = handleContainerScan;
  window._ozonFbsContainerMaybeBind = maybeBindAfterPostingIdentified;
  window._ozonFbsContainerErrorsTooltip = containerErrorsTooltip;
  window._ozonFbsContainerInvalidate = invalidateContainersCache;
  window.onOzonFbsContainerScanCheckChange = onContainerScanCheckChange;
  window.clearOzonFbsActiveContainer = clearActiveContainer;
  window._ozonFbsContainerClearOnModalClose = clearActiveContainerOnModalClose;
  window.clearOzonFbsContainerBind = clearBind;
  window.onOzonFbsContainerCellKey = onContainerCellKey;
  window.closeOzonFbsContainerRebindModal = closeRebindModal;
})();
