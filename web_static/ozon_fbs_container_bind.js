/**
 * Ozon FBS: optional cargo-place (грузоместо) binding in Marking / Pick Verify.
 * No-op when the supply has no active containers or the operator never scans one.
 */
(function () {
  "use strict";

  /**
   * While KIZ/pick modal is open: rare poll of portal GM composition (not a webhook).
   * Expensive (Ozon API per container) — keep slow; never contend with scanning.
   */
  const RECONCILE_POLL_MS = 120000;
  /** Hard floor between reconcile network calls (poll + tab focus). */
  const RECONCILE_MIN_GAP_MS = 90000;
  /** Treat operator as busy this long after last scan keystroke. */
  const SCAN_BUSY_MS = 2500;

  const state = {
    hasContainers: false,
    /** Last containers list request succeeded (even when items=[]). */
    loadOk: false,
    loadError: "",
    containers: [],
    byId: new Map(),
    activeId: null,
    activeBarcode: "",
    usedInSession: false,
    loading: false,
    rebindResolver: null,
    rebindPayload: null,
    /** Shown once when cargo-place bind hits 401 (session expired). */
    authRequiredOpen: false,
    /** Supply id for which activeId is valid — clear on supply change. */
    boundSupplyId: "",
    /** Postings with in-session container edits — skip reconcile overwrite. */
    dirtyPostings: new Set(),
    /** Monotonic token to ignore stale reconcile responses. */
    reconcileGen: 0,
    /** Background poll while modal stays open (catch mid-scan GM drops). */
    reconcilePollTimer: null,
    reconcilePollMode: "",
    reconcileInFlight: false,
    reconcileVisibilityBound: false,
    /** Last reconcile request start (ms). */
    lastReconcileAt: 0,
    /** Last sticker/KIZ/pick scan keystroke (ms). */
    lastScanActivityAt: 0,
    scanActivityBound: false,
    scanIdleTimer: null,
    pendingDomMode: "",
    pendingDomPns: [],
    pendingStatusCheckPns: [],
  };

  function markContainerDirty(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (pn) state.dirtyPostings.add(pn);
  }

  function clearContainerDirty(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (pn) state.dirtyPostings.delete(pn);
  }

  function collectReconcileSkipPostings(mode) {
    const skip = new Set(state.dirtyPostings);
    const isKiz = mode === "kiz";
    if (isKiz && window.ozonFbsKizState?.localAutosaveDirty instanceof Set) {
      for (const pn of window.ozonFbsKizState.localAutosaveDirty) {
        if (pn) skip.add(String(pn));
      }
    }
    return [...skip];
  }

  function modalStillOpen(mode) {
    const id = mode === "kiz" ? "ozonFbsKizModal" : "ozonFbsPickVerifyModal";
    const modal = document.getElementById(id);
    return !!(modal && !modal.classList.contains("hidden"));
  }

  function noteScanActivity() {
    state.lastScanActivityAt = Date.now();
  }

  function isScanBusy() {
    return Date.now() - Number(state.lastScanActivityAt || 0) < SCAN_BUSY_MS;
  }

  function isScanInputEl(el) {
    if (!el || String(el.tagName || "").toUpperCase() !== "INPUT") return false;
    const id = String(el.id || "");
    if (id === "ozonFbsKizStickerScan" || id === "ozonFbsPickStickerScan") return true;
    const cls = el.classList;
    if (!cls) return false;
    return (
      cls.contains("wb-fbs-kiz-code-input")
      || cls.contains("wb-fbs-pick-code-input")
      || cls.contains("ozon-fbs-pick-barcode-input")
    );
  }

  function bindScanActivityWatch() {
    if (state.scanActivityBound || typeof document === "undefined") return;
    state.scanActivityBound = true;
    const mark = (ev) => {
      if (!isScanInputEl(ev && ev.target)) return;
      noteScanActivity();
    };
    // Capture phase: see scanner wedges before other handlers.
    document.addEventListener("keydown", mark, true);
    document.addEventListener("input", mark, true);
  }

  function queuePendingStatusChecks(pns) {
    const bag = state.pendingStatusCheckPns;
    for (const pn of pns || []) {
      const s = String(pn || "").trim();
      if (s && !bag.includes(s)) bag.push(s);
    }
  }

  function scheduleScanIdleFlush() {
    if (state.scanIdleTimer != null) clearTimeout(state.scanIdleTimer);
    state.scanIdleTimer = setTimeout(() => {
      state.scanIdleTimer = null;
      flushScanIdleWork();
    }, SCAN_BUSY_MS + 50);
  }

  function flushScanIdleWork() {
    if (isScanBusy()) {
      scheduleScanIdleFlush();
      return;
    }
    const mode = String(state.pendingDomMode || state.reconcilePollMode || "").trim();
    const pns = state.pendingDomPns.slice();
    state.pendingDomMode = "";
    state.pendingDomPns = [];
    if (mode && pns.length && modalStillOpen(mode)) {
      applyReconcileDom(mode, pns);
    }
    const statusPns = state.pendingStatusCheckPns.slice();
    state.pendingStatusCheckPns = [];
    for (const pn of statusPns) {
      if (typeof window._ozonFbsSilentRefreshPostingStatus === "function") {
        try { void window._ozonFbsSilentRefreshPostingStatus(pn); } catch (_e) { /* ignore */ }
      }
    }
    const cur = String(state.reconcilePollMode || "").trim();
    if (cur && modalStillOpen(cur) && gmUiVisible(cur) && rowsHaveContainerBinds(cur)) {
      void reconcileContainers(cur);
    }
  }

  function applyReconcileDom(mode, touchedPns) {
    if (!touchedPns || !touchedPns.length) return;
    // Never full-rebuild the table while the operator is mid-scan burst.
    if (isScanBusy()) {
      state.pendingDomMode = mode;
      const bag = state.pendingDomPns;
      for (const pn of touchedPns) {
        const s = String(pn || "").trim();
        if (s && !bag.includes(s)) bag.push(s);
      }
      scheduleScanIdleFlush();
      return;
    }
    if (completenessFilterActive(mode)) {
      rerenderMode(mode);
      return;
    }
    let allPatched = true;
    for (const pn of touchedPns) {
      if (!patchContainerCell(mode, pn)) {
        allPatched = false;
        break;
      }
    }
    if (!allPatched) rerenderMode(mode);
    else refreshFilterCounts(mode);
  }

  function mergeReconcileBinds(mode, binds, changes) {
    const rows = mode === "kiz"
      ? (window.ozonFbsKizState?.rows || [])
      : (window.ozonFbsPickState?.rows || []);
    if (!rows.length || !binds || typeof binds !== "object") return 0;
    let touched = 0;
    const touchedPns = [];
    const statusCheckPns = [];
    for (const row of rows) {
      const pn = String(row?.posting_number || "").trim();
      if (!pn || state.dirtyPostings.has(pn)) continue;
      // Do not wipe a local GM bind for cancelled rows (Ozon may have dropped them).
      const isCancelled = typeof window._ozonFbsRowIsCancelled === "function"
        ? window._ozonFbsRowIsCancelled(row)
        : !!String(row?.cancel_reason_label || "").trim();
      if (isCancelled) {
        const nextKeep = binds[pn];
        // Portal/reconcile cleared → keep local barcode/progress.
        if (!nextKeep || nextKeep.container_id == null || Number(nextKeep.container_id) <= 0) {
          continue;
        }
      }
      const next = binds[pn];
      if (!next) continue;
      const nextCid = next.container_id != null ? Number(next.container_id) : 0;
      const curCid = row.container_id != null ? Number(row.container_id) : 0;
      const nextBc = String(next.container_barcode || "").trim();
      const curBc = String(row.container_barcode || "").trim();
      const nextErr = String(next.container_sync_error || "").trim();
      const curErr = String(row.container_sync_error || "").trim();
      const nextSynced = !!next.container_synced;
      const curSynced = !!row.container_synced;
      if (
        nextCid === curCid
        && nextBc === curBc
        && nextErr === curErr
        && nextSynced === curSynced
      ) {
        continue;
      }
      // Cancelled + portal cleared → keep local progress.
      if (isCancelled && curCid > 0 && nextCid <= 0) continue;
      // Ozon kicked posting out of GM — after applying clear, silently check status.
      const gmClearedByPortal = curCid > 0 && nextCid <= 0 && !isCancelled;
      row.container_id = nextCid > 0 ? nextCid : null;
      row.container_barcode = nextBc;
      row.container_synced = nextSynced;
      row.container_sync_error = nextErr;
      touched += 1;
      touchedPns.push(pn);
      if (gmClearedByPortal) {
        statusCheckPns.push(pn);
      }
    }
    if (touched > 0) {
      updateContainerCounters();
      // Prefer cell patches; defer heavy DOM while operator is scanning.
      applyReconcileDom(mode, touchedPns);
      // Peer may have saved KIZ/ШК in the same burst as GM bind — pull fill
      // counters into the open modal (status is local-DB, cheap).
      scheduleSupplyStatusRefresh();
    }
    // Background: only the postings Ozon dropped from GM — no toasts, no modal.
    // Defer status lookups during an active scan burst so focus/DOM stay free.
    if (statusCheckPns.length) {
      if (isScanBusy()) {
        queuePendingStatusChecks(statusCheckPns);
        scheduleScanIdleFlush();
      } else {
        for (const pn of statusCheckPns) {
          if (typeof window._ozonFbsSilentRefreshPostingStatus === "function") {
            try { void window._ozonFbsSilentRefreshPostingStatus(pn); } catch (_e) { /* ignore */ }
          }
        }
      }
    }
    // No "Грузоместа синхронизированы…" banner — it distracts during scanning.
    return touched;
  }

  async function reconcileContainers(mode, opts) {
    const force = !!(opts && opts.force);
    const { sid, sourceId } = supplyIds();
    if (!sid || !sourceId || !gmUiVisible(mode)) return;
    if (!modalStillOpen(mode)) return;
    if (state.reconcileInFlight) return;

    if (!force) {
      // Hidden tab: do not burn Ozon/API quota in the background.
      if (typeof document !== "undefined" && document.hidden) return;
      // Operator is wedging stickers — skip network entirely this tick.
      if (isScanBusy()) {
        scheduleScanIdleFlush();
        return;
      }
      // No local GM binds → nothing mid-scan can drift; skip expensive portal sync.
      if (!rowsHaveContainerBinds(mode)) return;
      const now = Date.now();
      if (now - Number(state.lastReconcileAt || 0) < RECONCILE_MIN_GAP_MS) return;
    }

    state.reconcileInFlight = true;
    state.lastReconcileAt = Date.now();
    const gen = (state.reconcileGen = Number(state.reconcileGen || 0) + 1);
    const skip = collectReconcileSkipPostings(mode);
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/reconcile`,
        {
          method: "POST",
          headers: csrfHeaders(),
          body: JSON.stringify({
            source_id: sourceId,
            skip_postings: skip,
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Ошибка ${res.status}`);
      if (Number(state.reconcileGen) !== gen || !modalStillOpen(mode)) return;
      mergeReconcileBinds(mode, data.binds || {}, data.changes || []);
      if (Array.isArray(data.changes) && data.changes.length > 0) {
        state.usedInSession = true;
      }
    } catch (_e) {
      // Background reconcile — do not interrupt operator workflow.
    } finally {
      state.reconcileInFlight = false;
    }
  }

  function stopReconcilePolling() {
    if (state.reconcilePollTimer != null) {
      clearInterval(state.reconcilePollTimer);
      state.reconcilePollTimer = null;
    }
    state.reconcilePollMode = "";
    if (state.scanIdleTimer != null) {
      clearTimeout(state.scanIdleTimer);
      state.scanIdleTimer = null;
    }
    state.pendingDomMode = "";
    state.pendingDomPns = [];
    state.pendingStatusCheckPns = [];
  }

  function startReconcilePolling(mode) {
    const m = String(mode || "").trim();
    stopReconcilePolling();
    if (m !== "kiz" && m !== "pick") return;
    if (!gmUiVisible(m)) return;
    bindScanActivityWatch();
    state.reconcilePollMode = m;
    state.reconcilePollTimer = setInterval(() => {
      const cur = state.reconcilePollMode;
      if (!cur || !modalStillOpen(cur) || !gmUiVisible(cur)) {
        stopReconcilePolling();
        return;
      }
      void reconcileContainers(cur);
    }, RECONCILE_POLL_MS);
    if (!state.reconcileVisibilityBound && typeof document !== "undefined") {
      state.reconcileVisibilityBound = true;
      document.addEventListener("visibilitychange", () => {
        if (document.hidden) return;
        const cur = state.reconcilePollMode;
        if (!cur || !modalStillOpen(cur) || !gmUiVisible(cur)) return;
        void reconcileContainers(cur);
      });
    }
  }

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

  function rowsForMode(mode) {
    return mode === "kiz"
      ? (window.ozonFbsKizState?.rows || [])
      : (window.ozonFbsPickState?.rows || []);
  }

  function rowsHaveContainerBinds(mode) {
    return rowsForMode(mode).some((r) => String(r?.container_barcode || "").trim());
  }

  /** True when at least one cargo place already has orders bound on *this* supply. */
  function supplyHasFilledCargoPlace() {
    const containers = Array.isArray(state.containers) ? state.containers : [];
    // Warehouse list is shared — only count GMs bound to the open supply.
    if (containers.some((c) => c?.bound_to_open_supply === true && Number(c?.order_count || 0) > 0)) {
      return true;
    }
    // Local row binds (after unbind of active GM / stale container list).
    if (rowsHaveContainerBinds("kiz") || rowsHaveContainerBinds("pick")) return true;
    return false;
  }

  /**
   * When the supply already has ≥1 filled GM, order scans require an active cargo place.
   * Scanning cargo-place barcodes (container scan mode) is not gated here.
   * Returns true when the scan may proceed.
   */
  function guardOrderScanRequiresActiveGm(mode, inputEl) {
    if (!supplyHasFilledCargoPlace()) return true;
    if (state.activeId) return true;
    const msg = "Вы пытаетесь просканировать заказ без грузоместа.";
    const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
    if (typeof setInfo === "function") setInfo(msg, false);
    if (typeof window.showFbsScanAck === "function") {
      window.showFbsScanAck(msg, inputEl || null, { title: "Нет грузоместа" });
    } else if (typeof window.alert === "function") {
      window.alert(msg);
    }
    const input = inputEl || null;
    if (input) {
      try { input.select?.(); } catch (_e) { /* ignore */ }
    }
    return false;
  }

  /** Show GM scan/column/menu when containers exist or rows already have binds. */
  function gmUiVisible(mode) {
    if (state.hasContainers) return true;
    return rowsHaveContainerBinds(mode);
  }

  function gmUiVisibleAny() {
    if (state.hasContainers) return true;
    return rowsHaveContainerBinds("kiz") || rowsHaveContainerBinds("pick");
  }

  function notifyContainerLoadError(mode, message) {
    const msg = String(message || "").trim();
    if (!msg) return;
    const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
    if (typeof setInfo === "function") {
      setInfo(`Грузоместа: ${msg}`, false);
    }
  }

  function rerenderMode(mode) {
    if (mode === "kiz" && typeof window.renderOzonFbsKizTable === "function") {
      window.renderOzonFbsKizTable({ skipCollect: true });
    }
    if (mode === "pick" && typeof window.renderOzonFbsPickVerifyTable === "function") {
      window.renderOzonFbsPickVerifyTable();
    }
  }

  function escapePostingSelector(pn) {
    const raw = String(pn || "").trim();
    if (!raw) return "";
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
      return CSS.escape(raw);
    }
    return raw.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  /**
   * Update one cargo-place cell without rebuilding the whole KIZ/pick table.
   * Critical at ~hundreds of rows: maybeBind used to full-rerender on every scan.
   */
  function patchContainerCell(mode, postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return false;
    const tbodyId = mode === "pick" ? "ozonFbsPickTbody" : "ozonFbsKizTbody";
    const tbody = document.getElementById(tbodyId);
    if (!tbody || typeof tbody.querySelector !== "function") return false;
    const escPn = escapePostingSelector(pn);
    const tr = tbody.querySelector(`tr.wb-fbs-kiz-row[data-posting="${escPn}"]`);
    if (!tr || typeof tr.querySelector !== "function") return false;
    const td = tr.querySelector("td.wb-fbs-kiz-col-container");
    if (!td) return false;
    const row = findRow(mode, pn);
    if (!row) return false;
    td.innerHTML = containerCellHtml(row, mode);
    return true;
  }

  /** Filled/empty filters treat GM as part of "complete" — need a full rebuild to show/hide rows. */
  function completenessFilterActive(mode) {
    if (mode === "pick") {
      return !!(
        document.getElementById("ozonFbsPickFilterFilled")?.checked
        || document.getElementById("ozonFbsPickFilterEmpty")?.checked
      );
    }
    return !!(
      document.getElementById("ozonFbsKizFilterFilled")?.checked
      || document.getElementById("ozonFbsKizFilterEmpty")?.checked
    );
  }

  function refreshFilterCounts(mode) {
    if (mode === "pick") {
      if (typeof window._ozonFbsPickUpdateFilterCounts === "function") {
        window._ozonFbsPickUpdateFilterCounts();
      }
      return;
    }
    if (typeof window._ozonFbsKizUpdateFilterCounts === "function") {
      window._ozonFbsKizUpdateFilterCounts();
    }
  }

  /**
   * Prefer single-cell patch for scan speed.
   * Full table when: DOM row missing, OR filled/empty filter is on (GM changes completeness).
   */
  function refreshContainerRow(mode, postingNumber) {
    updateContainerCounters();
    if (completenessFilterActive(mode)) {
      rerenderMode(mode);
      return false;
    }
    if (postingNumber && patchContainerCell(mode, postingNumber)) {
      refreshFilterCounts(mode);
      return true;
    }
    rerenderMode(mode);
    return false;
  }

  let statusRefreshTimer = null;
  /** Coalesce supply-detail status polls while scanning many postings quickly. */
  function scheduleSupplyStatusRefresh() {
    if (statusRefreshTimer) return;
    statusRefreshTimer = setTimeout(() => {
      statusRefreshTimer = null;
      if (typeof window.refreshOzonFbsMarkingStatus === "function") {
        void window.refreshOzonFbsMarkingStatus(null, { silent: true });
      }
      if (typeof window.refreshOzonFbsPickVerifyStatus === "function") {
        void window.refreshOzonFbsPickVerifyStatus(null, { silent: true });
      }
    }, 400);
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
      const bc = normalizeScan(c.container_barcode || c.barcode || "");
      if (cid === key) return c;
      if (bc && bc === key) return c;
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
    const showRow = gmUiVisible(mode);
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
    const showRow = gmUiVisible(mode);
    const showCols = gmUiVisibleAny();
    if (els.row) els.row.hidden = !showRow;
    if (els.check && !showRow) els.check.checked = false;
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
    // Column is shared markup in both modals — never hide it for one mode only.
    setContainerColumnsVisible(showCols);
  }

  function updateContainerCounters() {
    // Re-apply after every table re-render: new <td> nodes would otherwise stay visible
    // even when the supply has no cargo places (regression for the no-container flow).
    setContainerColumnsVisible(gmUiVisibleAny());
    updateOneCounter(window.ozonFbsKizState?.rows || [], "ozonFbsKizContainerCount", "kiz");
    updateOneCounter(window.ozonFbsPickState?.rows || [], "ozonFbsPickContainerCount", "pick");
  }

  function updateOneCounter(rows, elId, mode) {
    const el = document.getElementById(elId);
    if (!el) return;
    const list = Array.isArray(rows) ? rows : [];
    const isCancelled = (r) => {
      if (typeof window._ozonFbsRowIsCancelled === "function") {
        return window._ozonFbsRowIsCancelled(r);
      }
      return !!String(r?.cancel_reason_label || "").trim();
    };
    const active = list.filter((r) => !isCancelled(r));
    const boundLocal = active.filter((r) => String(r?.container_barcode || "").trim()).length;
    // Green only for Ozon-confirmed binds (container_synced), like WB kiz_wb_synced.
    // Cancelled rows are excluded from both sides of N/M.
    const synced = active.filter((r) => {
      if (!String(r?.container_barcode || "").trim()) return false;
      if (String(r?.container_sync_error || "").trim()) return false;
      return !!r?.container_synced;
    }).length;
    const show = gmUiVisible(mode) && (state.usedInSession || boundLocal > 0);
    el.hidden = !show;
    if (!show) {
      el.textContent = "";
      el.classList.remove("is-complete");
      return;
    }
    const total = active.length || 0;
    el.textContent = `Прикреплено к грузоместам ${synced} из ${total}`;
    el.classList.toggle("is-complete", total > 0 && synced === total);
  }

  function containerCellHtml(row, mode) {
    const pn = String(row?.posting_number || "").trim();
    const barcode = String(row?.container_barcode || "").trim();
    const err = String(row?.container_sync_error || "").trim();
    const safePn = esc(pn);
    const modeAttr = esc(mode);
    if (!gmUiVisible(mode)) {
      return `<div class="ozon-fbs-container-cell is-empty" title="ШК грузоместа не указан">—</div>`;
    }
    // Always show × like the KIZ column: clears typed value and/or unbinds GM.
    const clearTitle = barcode ? "Снять грузоместо" : "Очистить поле";
    return `<div class="ozon-fbs-container-cell${err ? " is-error" : ""}">
      <div class="ozon-fbs-container-input-row">
        <input type="text" class="ozon-fbs-container-input${err ? " is-error" : ""}"
               data-posting="${safePn}" data-mode="${modeAttr}"
               value="${esc(barcode)}"
               placeholder="ШК грузоместа"
               title="${err ? esc(err) : "ШК грузоместа"}"
               onkeydown="onOzonFbsContainerCellKey(event, '${safePn}', '${modeAttr}')"
               onblur="onOzonFbsContainerCellBlur(event, '${safePn}', '${modeAttr}')" />
        <button type="button" class="wb-fbs-kiz-remove ozon-fbs-container-clear" title="${clearTitle}"
                aria-label="${clearTitle}"
                onclick="clearOzonFbsContainerBind('${safePn}', '${modeAttr}')">×</button>
      </div>
      ${err ? `<div class="ozon-fbs-container-err">${esc(err)}</div>` : ""}
    </div>`;
  }

  async function ensureContainersLoaded(force, mode) {
    const { sid, sourceId } = supplyIds();
    if (!sid || !sourceId) {
      state.hasContainers = false;
      state.loadOk = false;
      state.loadError = !sourceId ? "Не указан источник OZON ФБС" : "";
      state.containers = [];
      state.byId = new Map();
      return false;
    }
    if (!force && state.containers.length && !state.loading && state.loadOk) {
      return state.hasContainers;
    }
    state.loading = true;
    state.loadError = "";
    try {
      const params = new URLSearchParams({
        source_id: String(sourceId),
        include_sc_accepted: "1",
      });
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers?${params}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Ошибка ${res.status}`);
      const items = Array.isArray(data.items) ? data.items : [];
      state.loadOk = true;
      state.containers = items;
      state.byId = new Map();
      for (const c of items) {
        const cid = String(c.container_id || "").trim();
        if (cid) state.byId.set(cid, c);
      }
      state.hasContainers = items.length > 0;
      if (!state.hasContainers) {
        setActive(null);
        if (!rowsHaveContainerBinds(mode)) state.usedInSession = false;
      } else if (state.activeId) {
        const cur = state.byId.get(String(state.activeId));
        if (!cur || !containerAcceptsFill(cur)) setActive(null);
      }
      return state.hasContainers;
    } catch (e) {
      state.loadOk = false;
      state.loadError = String(e.message || e);
      state.hasContainers = false;
      state.containers = [];
      state.byId = new Map();
      if (mode) notifyContainerLoadError(mode, state.loadError);
      return false;
    } finally {
      state.loading = false;
      syncCheckboxUi("kiz");
      syncCheckboxUi("pick");
      updateContainerCounters();
      if (mode && gmUiVisible(mode)) {
        rerenderMode(mode);
      }
      if (typeof window._ozonFbsOnContainersLoaded === "function") {
        try {
          window._ozonFbsOnContainersLoaded();
        } catch (_e) { /* ignore */ }
      }
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
    if (!gmUiVisible(mode)) return false;
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
    await ensureContainersLoaded(false, mode);
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
    stopReconcilePolling();
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

  /** Sticker was resolved in the modal (lookup / persist), not posting number alone. */
  function rowHasKnownSticker(row) {
    if (!row) return false;
    if (String(row.sticker_barcode || "").trim()) return true;
    const partA = String(row.sticker_part_a || "").trim();
    const partB = String(row.sticker_part_b || "").trim();
    return !!(partA && partB);
  }

  /** KIZ or pick verify succeeded locally — no bind on failed / empty scan. */
  function rowScanSucceeded(mode, row) {
    if (!row) return false;
    const pn = String(row.posting_number || "").trim();
    if (mode === "kiz") {
      const err = String(window.ozonFbsKizState?.errors?.[pn] || "").trim();
      if (err) return false;
      const codes = Array.isArray(row.kiz_codes) ? row.kiz_codes : [];
      return codes.some((c) => String(c || "").trim());
    }
    if (mode === "pick") {
      const err = String(window.ozonFbsPickState?.errors?.[pn] || "").trim();
      if (err) return false;
      return !!row.pick_verified && !!String(row.pick_barcode || "").trim();
    }
    return false;
  }

  function applyBindResult(row, data) {
    if (!row || !data) return;
    row.container_id = data.container_id || null;
    row.container_barcode = String(data.container_barcode || "").trim();
    row.container_synced = !!data.container_synced || !!data.synced;
    row.container_sync_error = String(data.error || data.container_sync_error || "").trim();
    if (row.container_barcode) state.usedInSession = true;
    const pn = String(row.posting_number || "").trim();
    if (pn && row.container_synced && !row.container_sync_error) {
      clearContainerDirty(pn);
    }
    // Keep supply-detail green/neutral tone in sync with GM binds.
    syncSupplyDetailContainerBind(pn, row);
  }

  function syncSupplyDetailContainerBind(postingNumber, row) {
    const pn = String(postingNumber || "").trim();
    const supply = window.supplyDetailState?.supply;
    if (!pn || !supply || !Array.isArray(supply.orders)) return;
    const order = supply.orders.find((o) => String(o?.posting_number || "").trim() === pn);
    if (order) {
      order.container_id = row?.container_id || null;
      order.container_barcode = String(row?.container_barcode || "").trim();
      order.container_synced = !!row?.container_synced;
      order.container_sync_error = String(row?.container_sync_error || "").trim();
    }
    scheduleSupplyStatusRefresh();
  }

  function httpError(res, data) {
    const detail = data && data.detail;
    const msg = typeof detail === "string"
      ? detail
      : (detail != null ? String(detail) : `Ошибка ${res.status}`);
    const err = new Error(msg || `Ошибка ${res.status}`);
    err.status = Number(res.status) || 0;
    return err;
  }

  function isSessionExpiredError(err) {
    if (!err) return false;
    const status = Number(err.status) || 0;
    // Prefer HTTP status: bind endpoint maps Ozon failures to 400, session to 401.
    if (status === 401) return true;
    if (status > 0) return false;
    const msg = String(err.message || err || "").toLowerCase();
    return msg.includes("требуется авторизация") || msg.includes("требует авторизац");
  }

  function clearPostingScanForMode(mode, postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return;
    if (mode === "kiz") {
      if (typeof window.clearOzonFbsKizRow === "function") {
        window.clearOzonFbsKizRow(pn);
        return;
      }
    } else if (typeof window.clearOzonFbsPickVerify === "function") {
      window.clearOzonFbsPickVerify(pn);
      return;
    }
  }

  function clearOptimisticContainerBind(row, postingNumber) {
    if (!row) return;
    row.container_id = null;
    row.container_barcode = "";
    row.container_synced = false;
    row.container_sync_error = "";
    clearContainerDirty(postingNumber);
  }

  function openAuthRequiredModal() {
    state.authRequiredOpen = true;
    const modal = document.getElementById("ozonFbsContainerAuthModal");
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsContainerAuthModal", true);
    } else if (modal) {
      modal.classList.remove("hidden");
    }
  }

  function closeAuthRequiredModal() {
    state.authRequiredOpen = false;
    const modal = document.getElementById("ozonFbsContainerAuthModal");
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsContainerAuthModal", false);
    } else if (modal) {
      modal.classList.add("hidden");
    }
  }

  function goToLoginFromAuthModal() {
    closeAuthRequiredModal();
    window.location.href = "/login";
  }

  /**
   * Session expired on cargo-place bind: drop optimistic ГМ, clear scanned
   * KIZ (marking) or product barcode (pick verify), force re-login.
   */
  function handleBindSessionExpired(mode, postingNumber) {
    const row = findRow(mode, postingNumber);
    clearOptimisticContainerBind(row, postingNumber);
    clearPostingScanForMode(mode, postingNumber);
    updateContainerCounters();
    // clear* already re-renders tables; still refresh counters/column state.
    rerenderMode(mode);
    openAuthRequiredModal();
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
    if (!res.ok) throw httpError(res, data);
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
    if (!res.ok) throw httpError(res, data);
    return data;
  }

  async function runBindAndRefresh(mode, postingNumber, containerId, barcode, previousId) {
    const row = findRow(mode, postingNumber);
    if (!row) return;
    try {
      const data = await bindPosting(postingNumber, containerId, barcode, previousId);
      applyBindResult(row, data);
    } catch (e) {
      if (isSessionExpiredError(e)) {
        handleBindSessionExpired(mode, postingNumber);
        return;
      }
      // Optimistic local bind (TZ): keep UI bind even if our API/Ozon call fails.
      row.container_id = containerId;
      row.container_barcode = barcode;
      row.container_synced = false;
      row.container_sync_error = String(e.message || e);
      state.usedInSession = true;
      markContainerDirty(postingNumber);
    }
    // Same posting cell only — avoid second full-table rebuild when Ozon fill returns.
    refreshContainerRow(mode, postingNumber);
  }

  /**
   * After successful KIZ / pick verify, attach to active cargo place in background.
   * Requires resolved sticker + successful scan; does not run on sticker-only identify.
   * Does not block the scan prompt (only rebind confirm is awaited).
   * Returns false only when user cancelled rebind.
   */
  async function maybeBindAfterPostingIdentified(mode, postingNumber) {
    if (!state.hasContainers || !state.activeId) return true;
    const row = findRow(mode, postingNumber);
    if (!row) return true;
    if (!rowHasKnownSticker(row) || !rowScanSucceeded(mode, row)) return true;
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
    // Patch only this row's GM cell — full table rebuild at ~600 rows freezes mark scan.
    row.container_id = activeId;
    row.container_barcode = nextBarcode;
    row.container_synced = false;
    row.container_sync_error = "";
    state.usedInSession = true;
    markContainerDirty(postingNumber);
    refreshContainerRow(mode, postingNumber);
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
    const prevBc = String(row.container_barcode || "").trim();
    // Nothing bound yet — just drop whatever was typed in the input (KIZ-parity clear).
    if (!prevId && !prevBc) {
      row.container_sync_error = "";
      const tbodyId = mode === "pick" ? "ozonFbsPickTbody" : "ozonFbsKizTbody";
      const tbody = document.getElementById(tbodyId);
      const escPn =
        typeof CSS !== "undefined" && CSS.escape
          ? CSS.escape(String(postingNumber || "").trim())
          : String(postingNumber || "").trim().replace(/\\/g, "\\\\").replace(/"/g, '\\"');
      const input = tbody?.querySelector(
        `.ozon-fbs-container-input[data-posting="${escPn}"]`
      );
      if (input) input.value = "";
      return;
    }
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
    refreshContainerRow(mode, postingNumber);
  }

  let containerCellCommitLock = false;

  function containerCellAlreadyBound(row, raw) {
    if (!row || !raw) return false;
    const prevBc = normalizeScan(row.container_barcode || "");
    const prevId = String(Number(row.container_id || 0) || "");
    return prevBc === raw || (prevId && prevId === raw);
  }

  /**
   * Commit typed/scanned ШК грузоместа from a table cell.
   * Used by Enter, blur, and Save flush — Save/autosave of KIZ/pick do not
   * persist GM by themselves (bind is a separate API).
   */
  async function commitContainerCell(mode, postingNumber, input, opts) {
    const options = opts && typeof opts === "object" ? opts : {};
    if (containerCellCommitLock) return false;
    const raw = normalizeScan(input?.value);
    const row = findRow(mode, postingNumber);
    if (!row) return false;
    if (!raw) {
      // Empty blur must not unbind — only × / clearBind does that.
      return false;
    }
    if (containerCellAlreadyBound(row, raw) && !String(row.container_sync_error || "").trim()) {
      return true;
    }
    containerCellCommitLock = true;
    try {
      await ensureContainersLoaded(false, mode);
      const found = matchContainer(raw);
      if (!found) {
        const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
        if (typeof setInfo === "function") {
          setInfo(`Грузоместо «${raw}» не найдено в этой поставке`, false);
        }
        return false;
      }
      if (!containerAcceptsFill(found)) {
        const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
        if (typeof setInfo === "function") {
          setInfo(
            `Грузоместо ${found.container_id} уже подтверждено — в него нельзя добавить заказ`,
            false
          );
        }
        if (input) input.value = String(row.container_barcode || "");
        return false;
      }
      const prevId = Number(row.container_id || 0) || 0;
      const nextId = Number(found.container_id || 0) || 0;
      const nextBarcode = String(nextId);
      if (prevId && prevId !== nextId) {
        if (options.skipRebindConfirm) {
          if (input) input.value = String(row.container_barcode || "");
          return false;
        }
        const ok = await openRebindModal({
          postingNumber,
          oldBarcode: String(row.container_barcode || prevId),
          newBarcode: nextBarcode,
        });
        if (!ok) {
          if (input) input.value = String(row.container_barcode || "");
          return false;
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
        if (isSessionExpiredError(e)) {
          handleBindSessionExpired(mode, postingNumber);
          return false;
        }
        row.container_id = nextId;
        row.container_barcode = nextBarcode;
        row.container_synced = false;
        row.container_sync_error = String(e.message || e);
        markContainerDirty(postingNumber);
      }
      updateContainerCounters();
      if (!options.skipRerender) {
        if (completenessFilterActive(mode)) {
          rerenderMode(mode);
        } else if (!patchContainerCell(mode, postingNumber)) {
          rerenderMode(mode);
        } else {
          refreshFilterCounts(mode);
        }
      }
      return true;
    } finally {
      containerCellCommitLock = false;
    }
  }

  async function onContainerCellKey(event, postingNumber, mode) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    await commitContainerCell(mode, postingNumber, event.target, {});
  }

  async function onContainerCellBlur(event, postingNumber, mode) {
    const input = event?.target;
    if (!input || !input.classList?.contains("ozon-fbs-container-input")) return;
    // Ignore blur caused by removing the input during rerender.
    if (!input.isConnected) return;
    await commitContainerCell(mode, postingNumber, input, {});
  }

  async function flushPendingContainerCells(mode) {
    const tbodyId = mode === "pick" ? "ozonFbsPickTbody" : "ozonFbsKizTbody";
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const inputs = Array.from(tbody.querySelectorAll("input.ozon-fbs-container-input"));
    for (const input of inputs) {
      const pn = String(input.getAttribute("data-posting") || "").trim();
      const m = String(input.getAttribute("data-mode") || mode || "").trim() || mode;
      if (!pn) continue;
      const row = findRow(m, pn);
      const raw = normalizeScan(input.value);
      if (!raw) continue;
      if (row && containerCellAlreadyBound(row, raw) && !String(row.container_sync_error || "").trim()) {
        continue;
      }
      await commitContainerCell(m, pn, input, { skipRerender: true });
    }
    rerenderMode(mode);
  }

  function resetForModal(mode) {
    const els = activeContainerEls(mode);
    if (els.check) els.check.checked = false;
    if (!gmUiVisible(mode)) setActive(null);
    syncCheckboxUi(mode);
    updateContainerCounters();
    rerenderMode(mode);
  }

  async function prepareForModal(mode) {
    const { sid } = supplyIds();
    // Switching supply must not keep a previous active cargo place.
    if (sid && state.boundSupplyId && state.boundSupplyId !== sid) {
      setActive(null);
      state.usedInSession = false;
      state.dirtyPostings.clear();
    }
    if (sid) state.boundSupplyId = sid;
    state.usedInSession = false;
    // Hide cargo column until we know whether this supply has containers.
    setContainerColumnsVisible(false);
    await ensureContainersLoaded(true, mode);
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
    // One forced sync on open; later polls are soft (rare, scan-aware, binds-only).
    void reconcileContainers(mode, { force: true });
    startReconcilePolling(mode);
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
    const out = await ensureContainersLoaded(true);
    if (typeof window._ozonFbsOnContainersLoaded === "function") {
      try {
        window._ozonFbsOnContainersLoaded();
      } catch (_e) { /* ignore */ }
    }
    return out;
  }

  const moveState = {
    mode: "",
    postingNumber: "",
  };

  function fillableContainers(excludeId) {
    const ex = Number(excludeId || 0);
    return (state.containers || []).filter((c) => {
      if (!containerAcceptsFill(c)) return false;
      const cid = Number(c.container_id || 0);
      if (cid <= 0) return false;
      if (ex > 0 && cid === ex) return false;
      return true;
    });
  }

  function containerMoveLabel(c) {
    const cid = Number(c?.container_id || 0);
    const num = Number(c?.container_number || 0);
    if (num > 0) return `ГМ №${num} — ${cid}`;
    return `ГМ ${cid}`;
  }

  function closeMoveContainerModal() {
    moveState.mode = "";
    moveState.postingNumber = "";
    const modal = document.getElementById("ozonFbsContainerMoveModal");
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsContainerMoveModal", false);
    } else if (modal) {
      modal.classList.add("hidden");
    }
  }

  function renderMoveContainerList(containers, row) {
    const list = document.getElementById("ozonFbsContainerMoveList");
    const empty = document.getElementById("ozonFbsContainerMoveEmpty");
    const meta = document.getElementById("ozonFbsContainerMoveMeta");
    const pn = String(row?.posting_number || "").trim();
    const prevBc = String(row?.container_barcode || row?.container_id || "").trim();
    if (meta) {
      meta.textContent = prevBc
        ? `Отправление ${pn}. Сейчас в грузоместе ${prevBc}.`
        : `Отправление ${pn}.`;
    }
    if (!containers.length) {
      if (list) list.innerHTML = "";
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
    if (!list) return;
    list.innerHTML = containers.map((c) => {
      const cid = Number(c.container_id || 0);
      const label = esc(containerMoveLabel(c));
      const status = esc(String(c.status_label || c.status || "—"));
      const orders = Math.max(0, Number(c.order_count || 0));
      const ordersLabel = orders === 1 ? "1 заказ" : `${orders} заказов`;
      return `<button type="button" class="ozon-fbs-container-move-item"
                      onclick="selectOzonFbsMoveContainerTarget(${cid})">
        <span class="ozon-fbs-container-move-title">${label}</span>
        <span class="ozon-fbs-container-move-sub">${status} · ${ordersLabel}</span>
      </button>`;
    }).join("");
  }

  function openContainerManualEntry(mode, postingNumber) {
    if (typeof window.closeOzonFbsRowMenus === "function") {
      window.closeOzonFbsRowMenus();
    }
    const pn = String(postingNumber || "").trim();
    if (!pn || !gmUiVisible(mode)) return;
    const tbodyId = mode === "pick" ? "ozonFbsPickTbody" : "ozonFbsKizTbody";
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const escPn = typeof CSS !== "undefined" && CSS.escape
      ? CSS.escape(pn)
      : pn.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    const rowEl = tbody.querySelector(`tr[data-posting="${escPn}"]`);
    if (!rowEl) return;
    const input = rowEl.querySelector(".ozon-fbs-container-input");
    if (!input) return;
    rowEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
    input.focus();
    if (typeof input.select === "function") input.select();
  }

  async function openMoveContainerPicker(mode, postingNumber) {
    if (typeof window.closeOzonFbsRowMenus === "function") {
      window.closeOzonFbsRowMenus();
    }
    const pn = String(postingNumber || "").trim();
    const row = findRow(mode, pn);
    if (!row || !gmUiVisible(mode)) return;
    const prevId = Number(row.container_id || 0);
    const prevBc = String(row.container_barcode || "").trim();
    if (prevId <= 0 && !prevBc) return;

    await ensureContainersLoaded(false, mode);
    const targets = fillableContainers(prevId);
    moveState.mode = mode;
    moveState.postingNumber = pn;
    renderMoveContainerList(targets, row);
    const modal = document.getElementById("ozonFbsContainerMoveModal");
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsContainerMoveModal", true);
    } else if (modal) {
      modal.classList.remove("hidden");
    }
  }

  async function selectMoveContainerTarget(containerId) {
    const mode = moveState.mode;
    const pn = moveState.postingNumber;
    closeMoveContainerModal();
    if (!mode || !pn) return;
    const row = findRow(mode, pn);
    if (!row) return;
    const prevId = Number(row.container_id || 0);
    const cid = Number(containerId || 0);
    if (cid <= 0 || (prevId > 0 && prevId === cid)) return;
    const target = state.byId.get(String(cid)) || state.containers.find(
      (c) => Number(c.container_id) === cid
    );
    if (!target || !containerAcceptsFill(target)) {
      const setInfo = mode === "kiz" ? window._ozonFbsKizSetInfo : window._ozonFbsPickSetInfo;
      if (typeof setInfo === "function") {
        setInfo("Выбранное грузоместо недоступно для изменения", false);
      }
      return;
    }
    const barcode = String(cid);
    const oldBarcode = String(row.container_barcode || prevId || "").trim();
    const ok = await openRebindModal({
      postingNumber: pn,
      oldBarcode: oldBarcode || String(prevId),
      newBarcode: barcode,
    });
    if (!ok) return;
    row.container_id = cid;
    row.container_barcode = barcode;
    row.container_synced = false;
    row.container_sync_error = "";
    state.usedInSession = true;
    updateContainerCounters();
    rerenderMode(mode);
    void runBindAndRefresh(
      mode,
      pn,
      cid,
      barcode,
      prevId > 0 ? prevId : null
    );
  }

  function rowCanMoveContainer(row) {
    if (!row || !state.hasContainers) return false;
    const prevId = Number(row.container_id || 0);
    const prevBc = String(row.container_barcode || "").trim();
    return prevId > 0 || !!prevBc;
  }

  // ── exports (names must match ozon_fbs.js / app.html hooks) ───────────────
  window.ozonFbsContainerBindState = state;
  window._ozonFbsContainerCellHtml = containerCellHtml;
  window._ozonFbsContainerUpdateCounters = updateContainerCounters;
  window._ozonFbsContainerGmUiVisible = gmUiVisible;
  window._ozonFbsContainerGmUiVisibleAny = gmUiVisibleAny;
  window._ozonFbsContainerPrepareModal = prepareForModal;
  window._ozonFbsContainerSyncCheckboxUi = syncCheckboxUi;
  window._ozonFbsContainerIsScanMode = isContainerScanMode;
  window._ozonFbsContainerHandleScan = handleContainerScan;
  window._ozonFbsContainerMaybeBind = maybeBindAfterPostingIdentified;
  window._ozonFbsContainerSupplyHasFilledGm = supplyHasFilledCargoPlace;
  window._ozonFbsContainerGuardOrderScanRequiresActiveGm = guardOrderScanRequiresActiveGm;
  window._ozonFbsContainerErrorsTooltip = containerErrorsTooltip;
  window._ozonFbsContainerInvalidate = invalidateContainersCache;
  window._ozonFbsContainerReconcile = reconcileContainers;
  window.onOzonFbsContainerScanCheckChange = onContainerScanCheckChange;
  window.clearOzonFbsActiveContainer = clearActiveContainer;
  window._ozonFbsContainerClearOnModalClose = clearActiveContainerOnModalClose;
  window.clearOzonFbsContainerBind = clearBind;
  window.onOzonFbsContainerCellKey = onContainerCellKey;
  window.onOzonFbsContainerCellBlur = onContainerCellBlur;
  window._ozonFbsContainerFlushPendingCells = flushPendingContainerCells;
  window.closeOzonFbsContainerRebindModal = closeRebindModal;
  window.closeOzonFbsContainerAuthModal = closeAuthRequiredModal;
  window.goOzonFbsContainerAuthLogin = goToLoginFromAuthModal;
  window.openOzonFbsMoveContainerPicker = openMoveContainerPicker;
  window.openOzonFbsContainerManualEntry = openContainerManualEntry;
  window.closeOzonFbsMoveContainerModal = closeMoveContainerModal;
  window.selectOzonFbsMoveContainerTarget = selectMoveContainerTarget;
  window._ozonFbsContainerRowCanMove = rowCanMoveContainer;
  // Test hooks
  window._ozonFbsContainerRunBindAndRefresh = runBindAndRefresh;
  window._ozonFbsContainerIsSessionExpiredError = isSessionExpiredError;
  window._ozonFbsContainerPatchCell = patchContainerCell;
  window._ozonFbsContainerRefreshRow = refreshContainerRow;
})();
