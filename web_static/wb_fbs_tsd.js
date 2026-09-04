/* WB FBS TSD — standalone warehouse page (does not depend on app.js) */
(function () {
  "use strict";

  const boot = window.TSD_BOOT || {};
  const state = {
    sourceId: null,
    sources: [],
    supplies: [],
    supply: null,
    route: { view: "list", supplyId: "", mode: "" },
    kizRows: [],
    pickRows: [],
    pendingOrderId: null,
    step: "sticker", // sticker | mark | sku
    banner: null,
    search: "",
    orderSearch: "",
    searchOpen: false,
    filterOpen: false,
    browseOpen: false,
    browseLimit: 40,
    filters: {
      filled: false,
      empty: false,
      errors: false,
      cancelled: false,
      noGm: false,
    },
    rowErrors: {},
    pendingKizClear: {},
    kizHubTone: "",
    kizHubToneSupplyId: "",
    kizStatusRefreshing: false,
    pickHubTone: "",
    pickHubToneSupplyId: "",
    pickStatusRefreshing: false,
    loadSeq: 0,
    forceSaveByOrder: {},
    sessionScannedIds: [],
    localAutosaveSeqByOrder: {},
    localAutosaveChain: null,
    localAutosaveInflight: 0,
    baselineKizByOrder: {},
    baselinePickByOrder: {},
    saving: false,
    clearing: false,
    loadUi: {
      token: 0,
      hintTimer: null,
      elapsedTimer: null,
      rotateTimer: null,
      startedAt: 0,
    },
    /**
     * Ozon FBS only — cargo-place (ГМ) bind on kiz/pick scan screens.
     * Never used for WB; gated by isOzon() everywhere.
     */
    gm: {
      containers: [],
      hasFillable: false,
      loadOk: false,
      loadError: "",
      activeId: null,
      activeBarcode: "",
      awaitingScan: false,
      boundSupplyId: "",
      loading: false,
      loadGen: 0,
      rebindResolver: null,
    },
  };

  const LS_SOURCE = "wb_fbs_tsd_source_id";

  function currentSource() {
    return (
      (state.sources || []).find((s) => Number(s.id) === Number(state.sourceId)) || {}
    );
  }

  function isOzon() {
    return String(currentSource().marketplace || "wb").toLowerCase() === "ozon";
  }

  function gmMatchApi() {
    return window.OzonFbsContainerMatch || null;
  }

  function normalizeContainerScan(value) {
    const api = gmMatchApi();
    if (api && typeof api.normalizeContainerScan === "function") {
      return api.normalizeContainerScan(value);
    }
    const raw = String(value || "").trim();
    if (!raw) return "";
    const digits = raw.replace(/\D+/g, "");
    return digits || raw;
  }

  function containerAcceptsFill(c) {
    const api = gmMatchApi();
    if (api && typeof api.containerAcceptsFill === "function") {
      return api.containerAcceptsFill(c);
    }
    if (!c || typeof c !== "object") return false;
    if (c.can_fill === false) return false;
    if (c.can_fill === true) return true;
    const st = String(c.status || "").trim().toLowerCase();
    return ![
      "approved",
      "formed",
      "ready",
      "shipped",
      "closed",
      "cancelled",
      "canceled",
      "deleted",
    ].includes(st);
  }

  function matchContainerByScan(containers, scan) {
    const api = gmMatchApi();
    if (api && typeof api.matchContainerByScan === "function") {
      return api.matchContainerByScan(containers, scan);
    }
    const key = normalizeContainerScan(scan);
    if (!key) return null;
    for (const row of containers || []) {
      if (!row || typeof row !== "object") continue;
      if (String(row.container_id || "").trim() === key) return row;
    }
    return null;
  }

  function resetGmState(opts) {
    const clearActive = !(opts && opts.keepActive);
    state.gm.awaitingScan = false;
    state.gm.loadError = "";
    if (clearActive) {
      state.gm.activeId = null;
      state.gm.activeBarcode = "";
    }
    if (opts && opts.clearList) {
      state.gm.loadGen = Number(state.gm.loadGen || 0) + 1;
      state.gm.containers = [];
      state.gm.hasFillable = false;
      state.gm.loadOk = false;
      state.gm.boundSupplyId = "";
      state.gm.loading = false;
    }
  }

  /** Phase 1+: show GM bar only on Ozon kiz/pick when fillable containers exist. */
  function gmUiVisible() {
    if (!isOzon()) return false;
    if (state.route.view !== "scan") return false;
    const mode = state.route.mode;
    if (mode !== "kiz" && mode !== "pick") return false;
    return !!state.gm.hasFillable;
  }

  function gmFilterAvailable() {
    if (!isOzon() || state.route.view !== "scan") return false;
    if (state.gm.hasFillable) return true;
    const rows =
      state.route.mode === "kiz" ? state.kizRows : state.pickRows;
    return (rows || []).some((r) => Number(r?.container_id || 0) > 0);
  }

  function gmBoundCount(mode) {
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    return (rows || []).filter((r) => Number(r?.container_id || 0) > 0).length;
  }

  function rowGmCode(row) {
    const barcode = String(row?.container_barcode || "").trim();
    if (barcode) return barcode;
    const cid = Number(row?.container_id || 0) || 0;
    return cid > 0 ? String(cid) : "";
  }

  function isLockedGmError(message) {
    const msg = String(message || "").toLowerCase();
    return (
      msg.includes("подтвержд") ||
      msg.includes("уже подтверждено") ||
      msg.includes("нельзя добавить") ||
      msg.includes("нельзя сканировать")
    );
  }

  /**
   * Phase 2: re-check active GM; clear if locked mid-shift.
   * Uses cache first; force-refreshes only when cache says locked/missing.
   * Returns false when active was cleared.
   */
  async function ensureActiveGmStillFillable() {
    if (!isOzon() || !state.gm.activeId) return false;
    const wasId = state.gm.activeId;
    let cur = activeGmContainer();
    if (cur && containerAcceptsFill(cur)) return true;
    await loadGmContainers(true);
    cur = activeGmContainer();
    if (state.gm.activeId && cur && containerAcceptsFill(cur)) return true;
    if (!state.gm.activeId) {
      // Cleared inside loadGmContainers (locked list / empty / hard error).
      if (state.gm.loadError) {
        setBanner(`Грузоместа: ${state.gm.loadError}`, "warn");
      } else {
        setBanner(
          `Грузоместо ${wasId} уже подтверждено — выберите другое`,
          "err"
        );
      }
      refreshGmBar();
      refreshScanBanner();
      return false;
    }
    setActiveGm(null);
    state.gm.awaitingScan = false;
    setBanner(
      `Грузоместо ${wasId} уже подтверждено — выберите другое`,
      "err"
    );
    refreshGmBar();
    refreshScanBanner();
    return false;
  }

  function activeGmContainer() {
    if (!state.gm.activeId) return null;
    const id = String(state.gm.activeId);
    return (
      (state.gm.containers || []).find(
        (c) => String(c.container_id || "") === id
      ) || null
    );
  }

  function activeGmLabel() {
    const cur = activeGmContainer();
    const id = state.gm.activeBarcode || String(state.gm.activeId || "");
    if (!cur) return id ? `ГМ ${id}` : "";
    const num = Number(cur.container_number || 0);
    if (num > 0) return `ГМ №${num} · ${id}`;
    return `ГМ ${id}`;
  }

  async function loadGmContainers(force) {
    if (!isOzon()) {
      resetGmState({ clearList: true });
      return false;
    }
    const sid = String(state.route.supplyId || "").trim();
    const sourceId = Number(state.sourceId || 0) || 0;
    if (!sid || !sourceId) {
      resetGmState({ clearList: true });
      return false;
    }
    if (
      !force &&
      state.gm.loadOk &&
      state.gm.boundSupplyId === sid &&
      !state.gm.loading
    ) {
      return state.gm.hasFillable;
    }
    const gen = (state.gm.loadGen = Number(state.gm.loadGen || 0) + 1);
    const keepOnFail =
      !!force &&
      state.gm.boundSupplyId === sid &&
      Array.isArray(state.gm.containers) &&
      state.gm.containers.length > 0;
    state.gm.loading = true;
    state.gm.loadError = "";
    const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timeoutMs = 20000;
    const timer = ctrl
      ? setTimeout(() => {
          try {
            ctrl.abort();
          } catch (_e) {
            /* ignore */
          }
        }, timeoutMs)
      : null;
    try {
      const params = new URLSearchParams({
        source_id: String(sourceId),
        include_sc_accepted: "1",
      });
      const data = await api(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers?${params}`,
        ctrl ? { signal: ctrl.signal } : undefined
      );
      // Ignore stale responses after supply/route change.
      if (gen !== state.gm.loadGen) return state.gm.hasFillable;
      if (String(state.route.supplyId || "") !== sid) return state.gm.hasFillable;
      const items = Array.isArray(data.items) ? data.items : [];
      state.gm.containers = items;
      state.gm.loadOk = true;
      state.gm.loadError = "";
      state.gm.boundSupplyId = sid;
      state.gm.hasFillable = items.some((c) => containerAcceptsFill(c));
      if (!state.gm.hasFillable) {
        state.gm.activeId = null;
        state.gm.activeBarcode = "";
        state.gm.awaitingScan = false;
      } else if (state.gm.activeId) {
        const cur = activeGmContainer();
        if (!cur || !containerAcceptsFill(cur)) {
          state.gm.activeId = null;
          state.gm.activeBarcode = "";
        }
      }
      return state.gm.hasFillable;
    } catch (e) {
      if (gen !== state.gm.loadGen) return state.gm.hasFillable;
      if (String(state.route.supplyId || "") !== sid) return state.gm.hasFillable;
      const aborted =
        (e && (e.name === "AbortError" || e.code === 20)) ||
        /abort/i.test(String(e && e.message));
      const errMsg = aborted
        ? "Таймаут загрузки грузомест"
        : String(e.message || e);
      state.gm.loadError = errMsg;
      if (keepOnFail) {
        // Phase 2/3: transient refresh failure must not wipe an in-session GM list.
        state.gm.loadOk = true;
        return state.gm.hasFillable;
      }
      state.gm.loadOk = false;
      state.gm.containers = [];
      state.gm.hasFillable = false;
      state.gm.activeId = null;
      state.gm.activeBarcode = "";
      state.gm.awaitingScan = false;
      return false;
    } finally {
      if (timer) clearTimeout(timer);
      if (gen === state.gm.loadGen) state.gm.loading = false;
    }
  }

  function setActiveGm(container) {
    if (!container) {
      state.gm.activeId = null;
      state.gm.activeBarcode = "";
      return;
    }
    const cid = Number(container.container_id || 0) || 0;
    state.gm.activeId = cid > 0 ? cid : null;
    state.gm.activeBarcode = cid > 0 ? String(cid) : "";
  }

  function gmIconSvg(kind) {
    if (kind === "refresh") {
      return `<svg class="tsd-gm-icon-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path fill="currentColor" d="M17.65 6.35A7.95 7.95 0 0 0 12 4V1L7 6l5 5V7a5 5 0 1 1-4.9 6.1H5.04A7 7 0 1 0 17.65 6.35z"/>
      </svg>`;
    }
    if (kind === "cancel" || kind === "reset") {
      return `<svg class="tsd-gm-icon-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path fill="currentColor" d="M18.3 5.71 12 12l6.3 6.29-1.41 1.42L10.59 13.4 4.3 19.71 2.89 18.3 9.17 12 2.89 5.71 4.3 4.29 10.59 10.6l6.3-6.31z"/>
      </svg>`;
    }
    if (kind === "plus") {
      return `<svg class="tsd-gm-icon-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path fill="currentColor" d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6V5z"/>
      </svg>`;
    }
    // Cargo / GM box
    return `<svg class="tsd-gm-icon-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path fill="currentColor" d="M21 8.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8.5l9-4.5 9 4.5zm-9 1.2L6.2 12 12 14.9 17.8 12 12 9.7zM5 14.2v4.8h6v-3.5L5 14.2zm8 1.3V19h6v-4.8l-6 1.3z"/>
    </svg>`;
  }

  function gmIconBtn(id, label, kind, extraClass) {
    const cls = ["tsd-gm-icon-btn", extraClass].filter(Boolean).join(" ");
    return `<button type="button" class="${cls}" id="${id}" title="${esc(label)}" aria-label="${esc(
      label
    )}">${gmIconSvg(kind)}</button>`;
  }

  /** Icons to the right of the main scan input (no separate GM block above). */
  function renderGmSideIconsHtml() {
    if (!gmUiVisible()) return "";
    const refreshBtn = gmIconBtn(
      "tsdGmRefresh",
      "Обновить список ГМ",
      "refresh",
      "tsd-gm-refresh"
    );
    if (state.gm.awaitingScan) {
      return `${gmIconBtn(
        "tsdGmCancelScan",
        "Отмена выбора ГМ",
        "cancel",
        "tsd-gm-icon-cancel"
      )}${refreshBtn}`;
    }
    if (state.gm.activeId) {
      return `${gmIconBtn(
        "tsdGmChange",
        `Сменить ГМ · ${activeGmLabel()}`,
        "plus",
        "tsd-gm-icon-add is-active"
      )}${refreshBtn}`;
    }
    return `${gmIconBtn(
      "tsdGmAdd",
      "Добавить грузоместо",
      "plus",
      "tsd-gm-icon-add"
    )}${refreshBtn}`;
  }

  function activeGmHintText() {
    const cur = activeGmContainer();
    const id = state.gm.activeBarcode || String(state.gm.activeId || "");
    if (!id) return "";
    const num = Number(cur && cur.container_number) || 0;
    if (num > 0) return `ГМ №${num}: ${id}`;
    return `ГМ: ${id}`;
  }

  function renderGmActiveHintHtml() {
    if (!gmUiVisible() || !state.gm.activeId || state.gm.awaitingScan) return "";
    const label = activeGmHintText();
    return `<div class="tsd-gm-active-hint" id="tsdGmActiveHint">
      <span class="tsd-gm-active-hint-text" title="${esc(label)}">${esc(label)}</span>
      <button type="button" class="tsd-gm-active-hint-reset" id="tsdGmReset"
        title="Сбросить грузоместо" aria-label="Сбросить грузоместо">×</button>
    </div>`;
  }

  function scanFieldRowHtml() {
    const gmIcons = renderGmSideIconsHtml();
    const withGm = !!gmIcons;
    return `
      <div class="tsd-scan-row${withGm ? " has-gm-actions" : ""}">
        <div class="tsd-scan-field">
          <input class="tsd-scan-input" id="tsdScanInput" type="text" autocomplete="off" inputmode="none" />
          <button type="button" class="tsd-scan-clear" id="tsdScanClear" hidden
            aria-label="Очистить поле" title="Очистить">×</button>
        </div>
        ${withGm ? `<div class="tsd-gm-side" id="tsdGmSide">${gmIcons}</div>` : ""}
      </div>
      ${renderGmActiveHintHtml()}`;
  }

  /** Kept for call-sites: no top GM bar — icons live beside the scan input. */
  function renderGmBarHtml() {
    return "";
  }

  function refreshGmBar() {
    const side = document.getElementById("tsdGmSide");
    const card = document.getElementById("tsdScanCard");
    if (!gmUiVisible()) {
      if (side) side.remove();
      const hint = document.getElementById("tsdGmActiveHint");
      if (hint) hint.remove();
      const row = document.querySelector(".tsd-scan-row");
      if (row) row.classList.remove("has-gm-actions");
      return;
    }
    if (!card) {
      // Scan card not mounted yet — full render will place icons.
      return;
    }
    const icons = renderGmSideIconsHtml();
    let row = card.querySelector(".tsd-scan-row");
    if (!row) {
      // Legacy field without row wrapper — rebuild card.
      if (!patchScanCard(state.route.mode)) renderScan();
      else wireGmBar();
      return;
    }
    row.classList.toggle("has-gm-actions", !!icons);
    if (icons) {
      if (side) side.innerHTML = icons;
      else {
        const wrap = document.createElement("div");
        wrap.className = "tsd-gm-side";
        wrap.id = "tsdGmSide";
        wrap.innerHTML = icons;
        row.appendChild(wrap);
      }
    } else if (side) {
      side.remove();
    }
    const hintHtml = renderGmActiveHintHtml().trim();
    let hint = document.getElementById("tsdGmActiveHint");
    if (hintHtml) {
      const wrap = document.createElement("div");
      wrap.innerHTML = hintHtml;
      const next = wrap.firstElementChild;
      if (hint) hint.replaceWith(next);
      else row.insertAdjacentElement("afterend", next);
    } else if (hint) {
      hint.remove();
    }
    wireGmBar();
  }

  function wireGmBar() {
    if (!isOzon()) return;
    const refresh = document.getElementById("tsdGmRefresh");
    if (refresh) {
      refresh.addEventListener("click", async () => {
        refresh.disabled = true;
        try {
          clearBanner({ silent: true });
          const hadActive = !!state.gm.activeId;
          await loadGmContainers(true);
          if (hadActive && !state.gm.activeId) {
            setBanner("Активное грузоместо больше недоступно — выберите другое", "warn");
          } else if (!state.gm.hasFillable) {
            setBanner(
              state.gm.loadError
                ? `Грузоместа: ${state.gm.loadError}`
                : "Нет доступных грузомест для заполнения",
              "warn"
            );
          } else if (state.gm.loadError) {
            setBanner(`Грузоместа: ${state.gm.loadError}`, "warn");
          } else {
            setBanner("Список грузомест обновлён", "ok");
          }
        } finally {
          if (!patchScanCard(state.route.mode)) renderScan();
          else {
            refreshGmBar();
            refreshScanBanner();
            refreshScanStats(state.route.mode);
          }
        }
      });
    }
    const startGmScan = async () => {
      await loadGmContainers(true);
      if (!state.gm.hasFillable) {
        setBanner(
          state.gm.loadError
            ? `Грузоместа: ${state.gm.loadError}`
            : "Нет доступных грузомест для заполнения",
          "warn"
        );
        refreshGmBar();
        refreshScanBanner();
        return;
      }
      state.gm.awaitingScan = true;
      // Prompt above the input is enough — no blue info banner.
      setBanner(null);
      if (!patchScanCard(state.route.mode)) renderScan();
      else {
        refreshGmBar();
        refreshScanBanner();
      }
    };
    const addBtn = document.getElementById("tsdGmAdd");
    if (addBtn) addBtn.addEventListener("click", () => startGmScan());
    const change = document.getElementById("tsdGmChange");
    if (change) change.addEventListener("click", () => startGmScan());
    const cancel = document.getElementById("tsdGmCancelScan");
    if (cancel) {
      cancel.addEventListener("click", () => {
        state.gm.awaitingScan = false;
        setBanner(null);
        if (!patchScanCard(state.route.mode)) renderScan();
        else {
          refreshGmBar();
          refreshScanBanner();
        }
      });
    }
    const reset = document.getElementById("tsdGmReset");
    if (reset) {
      reset.addEventListener("click", () => {
        setActiveGm(null);
        state.gm.awaitingScan = false;
        setBanner("Сканирование в грузоместо остановлено", "info");
        refreshGmBar();
        refreshScanBanner();
      });
    }
  }

  function ensureGmRebindSheet() {
    let sheet = document.getElementById("tsdGmRebindSheet");
    if (sheet) return sheet;
    sheet = document.createElement("div");
    sheet.id = "tsdGmRebindSheet";
    sheet.className = "tsd-gm-rebind";
    sheet.hidden = true;
    sheet.innerHTML = `
      <div class="tsd-gm-rebind-backdrop" data-gm-rebind="no"></div>
      <div class="tsd-gm-rebind-card" role="dialog" aria-modal="true" aria-labelledby="tsdGmRebindText">
        <p class="tsd-gm-rebind-text" id="tsdGmRebindText"></p>
        <div class="tsd-gm-rebind-actions">
          <button type="button" class="tsd-btn tsd-btn-ghost tsd-btn-block" data-gm-rebind="no">Отмена</button>
          <button type="button" class="tsd-btn tsd-btn-primary tsd-btn-block" data-gm-rebind="yes">Привязать</button>
        </div>
      </div>`;
    sheet.addEventListener("click", (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-gm-rebind]") : null;
      if (!btn) return;
      const yes = btn.getAttribute("data-gm-rebind") === "yes";
      closeGmRebind(yes);
    });
    (document.getElementById("tsdApp") || document.body).appendChild(sheet);
    return sheet;
  }

  function openGmRebind({ postingNumber, oldBarcode, newBarcode }) {
    return new Promise((resolve) => {
      // Resolve any previous pending confirm so awaiters cannot hang.
      if (typeof state.gm.rebindResolver === "function") {
        const prev = state.gm.rebindResolver;
        state.gm.rebindResolver = null;
        prev(false);
      }
      state.gm.rebindResolver = resolve;
      const sheet = ensureGmRebindSheet();
      const text = document.getElementById("tsdGmRebindText");
      if (text) {
        text.textContent =
          `Отправление ${postingNumber} числится в грузоместе ${oldBarcode}. ` +
          `Привязать к грузоместу ${newBarcode}?`;
      }
      sheet.hidden = false;
      const scanInput = document.getElementById("tsdScanInput");
      if (scanInput) {
        try {
          scanInput.blur();
        } catch (_e) {
          /* ignore */
        }
      }
    });
  }

  function closeGmRebind(yes) {
    const sheet = document.getElementById("tsdGmRebindSheet");
    if (sheet) sheet.hidden = true;
    const resolve = state.gm.rebindResolver;
    state.gm.rebindResolver = null;
    if (typeof resolve === "function") resolve(!!yes);
    const scanInput = document.getElementById("tsdScanInput");
    if (
      scanInput &&
      state.route.view === "scan" &&
      !state.searchOpen &&
      !shouldShowBrowseSheet()
    ) {
      setTimeout(() => scanInput.focus(), 40);
    }
  }

  async function handleGmScan(rawScan) {
    await loadGmContainers(false);
    const found = matchContainerByScan(state.gm.containers, rawScan);
    if (!found) {
      setBanner(`Грузоместо «${normalizeContainerScan(rawScan) || rawScan}» не найдено`, "err");
      beep(false);
      return false;
    }
    if (!containerAcceptsFill(found)) {
      setBanner(
        `Грузоместо ${found.container_id} уже подтверждено — в него нельзя сканировать`,
        "err"
      );
      beep(false);
      return false;
    }
    setActiveGm(found);
    state.gm.awaitingScan = false;
    setBanner(`Грузоместо ${activeGmLabel()} выбрано. Сканируйте заказы.`, "ok");
    beep(true);
    return true;
  }

  async function bindGmPosting(postingNumber, containerId, containerBarcode, previousId) {
    const sid = String(state.route.supplyId || "").trim();
    const sourceId = Number(state.sourceId || 0) || 0;
    if (!sid || !sourceId) return null;
    return api(
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/bind`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          source_id: sourceId,
          posting_number: postingNumber,
          container_id: containerId,
          container_barcode: containerBarcode || String(containerId),
          previous_container_id: previousId || null,
        }),
      }
    );
  }

  function applyGmBindResult(row, data) {
    if (!row || !data) return;
    row.container_id = data.container_id || null;
    row.container_barcode = String(data.container_barcode || "").trim();
    row.container_synced = !!data.container_synced || !!data.synced;
    row.container_sync_error = String(
      data.error || data.container_sync_error || ""
    ).trim();
  }

  /**
   * After successful KIZ / product barcode — bind to active GM (Ozon only).
   * Optimistic like web; rebind confirm is awaited.
   * Phase 2: silent no-op without activeId; retry when sync_error; clear locked GM.
   */
  async function maybeBindGmAfterSuccess(row) {
    // Quiet when no active GM — KIZ/SKU flow must not show GM errors.
    if (!isOzon() || !state.gm.activeId || !row) return true;
    if (!gmUiVisible()) return true;
    const postingNumber = String(row.posting_number || rowScanId(row) || "").trim();
    if (!postingNumber) return true;
    const stillOk = await ensureActiveGmStillFillable();
    if (!stillOk) return true;
    const prevId = Number(row.container_id || 0) || 0;
    const prevBarcode = String(row.container_barcode || "").trim();
    const nextBarcode = state.gm.activeBarcode || String(state.gm.activeId);
    const activeId = state.gm.activeId;
    // Already on this GM without error — no-op (retry only when sync_error set).
    if (prevId === activeId && !String(row.container_sync_error || "").trim()) {
      return true;
    }
    if (prevId && prevId !== activeId) {
      const ok = await openGmRebind({
        postingNumber,
        oldBarcode: prevBarcode || String(prevId),
        newBarcode: nextBarcode,
      });
      if (!ok) return false;
    }
    row.container_id = activeId;
    row.container_barcode = nextBarcode;
    row.container_synced = false;
    row.container_sync_error = "";
    const modeAtBind = state.route.mode;
    const labelAtBind = activeGmLabel();
    // Optimistic chrome: badge/counter update before API returns.
    if (state.route.view === "scan" && state.route.mode === modeAtBind) {
      refreshScannedListSection(modeAtBind);
      refreshScanStats(modeAtBind);
    }
    void (async () => {
      try {
        const data = await bindGmPosting(
          postingNumber,
          activeId,
          nextBarcode,
          prevId && prevId !== activeId ? prevId : null
        );
        applyGmBindResult(row, data);
        if (row.container_sync_error) {
          setBanner(`В ГМ локально, Ozon: ${row.container_sync_error}`, "warn");
          refreshScanBanner();
        } else {
          toast(`В ${labelAtBind}`);
        }
      } catch (e) {
        const msg = String(e.message || e);
        row.container_id = activeId;
        row.container_barcode = nextBarcode;
        row.container_synced = false;
        row.container_sync_error = msg;
        if (isLockedGmError(msg)) {
          setActiveGm(null);
          state.gm.awaitingScan = false;
          void loadGmContainers(true).then(() => {
            refreshGmBar();
          });
          setBanner(
            `Грузоместо ${activeId} уже подтверждено — выберите другое`,
            "err"
          );
        } else {
          setBanner(`В ГМ локально, Ozon: ${msg}`, "warn");
        }
        refreshScanBanner();
        refreshGmBar();
      }
      if (state.route.view === "scan" && state.route.mode === modeAtBind) {
        refreshScannedListSection(modeAtBind);
        refreshScanStats(modeAtBind);
      }
    })();
    return true;
  }

  function rowScanId(row) {
    if (!row) return "";
    if (isOzon()) return String(row.posting_number || row.order_id || "").trim();
    const oid = Number(row.order_id);
    return Number.isFinite(oid) && oid > 0 ? String(oid) : "";
  }

  function rowDisplayLabel(row) {
    if (isOzon()) {
      return String(row.posting_number || row.order_number || "—");
    }
    return String(row.order_id || "—");
  }

  function rowMatchesScanId(row, id) {
    return rowScanId(row) === String(id || "").trim();
  }

  function findRowByScanId(rows, id) {
    const key = String(id || "").trim();
    if (!key) return null;
    return (rows || []).find((r) => rowScanId(r) === key) || null;
  }

  function forceSaveKey(row, mode) {
    const id = rowScanId(row);
    return mode === "pick" ? `pick:${id}` : id;
  }

  function sourceOptionLabel(s) {
    const name = String(s.name || `Источник ${s.id}`);
    const mp = String(s.marketplace || "wb").toLowerCase();
    if (mp === "ozon") return `Ozon · ${name}`;
    if (mp === "wb") return `WB · ${name}`;
    return name;
  }

  // Wedge scanners type as keyboard; RU layout turns Latin sticker barcodes into Cyrillic.
  const RU_LAYOUT_TO_EN = {
    й: "q", ц: "w", у: "e", к: "r", е: "t", н: "y", г: "u", ш: "i",
    щ: "o", з: "p", х: "[", ъ: "]",
    ф: "a", ы: "s", в: "d", а: "f", п: "g", р: "h", о: "j", л: "k",
    д: "l", ж: ";", э: "'",
    я: "z", ч: "x", с: "c", м: "v", и: "b", т: "n", ь: "m", б: ",",
    ю: ".", ё: "`",
    Й: "Q", Ц: "W", У: "E", К: "R", Е: "T", Н: "Y", Г: "U", Ш: "I",
    Щ: "O", З: "P", Х: "{", Ъ: "}",
    Ф: "A", Ы: "S", В: "D", А: "F", П: "G", Р: "H", О: "J", Л: "K",
    Д: "L", Ж: ":", Э: '"',
    Я: "Z", Ч: "X", С: "C", М: "V", И: "B", Т: "N", Ь: "M", Б: "<",
    Ю: ">", Ё: "~",
    // Same physical keys as EN / and ? when OS layout is Russian (ЧЗ crypto is base64).
    ".": "/", ",": "?",
  };

  function esc(v) {
    return String(v || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function getCsrfToken() {
    const key = "csrf_token=";
    for (const part of String(document.cookie || "").split(";")) {
      const value = part.trim();
      if (value.startsWith(key)) return decodeURIComponent(value.slice(key.length));
    }
    return "";
  }

  function jsonHeaders() {
    const headers = { "Content-Type": "application/json", Accept: "application/json" };
    const csrf = getCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
    return headers;
  }

  async function api(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : `Ошибка ${res.status}`);
    }
    return data;
  }

  function boxesLabel(n) {
    const c = Number(n || 0);
    if (c === 1) return "1 грузоместо";
    if (c > 1 && c < 5) return `${c} грузоместа`;
    return `${c} грузомест`;
  }

  function ordersBoxesText(s) {
    const orders = Number(s.order_count || 0);
    if (isOzon()) return `${orders} отпр.`;
    const boxes = Number(s.boxes_count || 0);
    return `${orders} заказ. · ${boxesLabel(boxes)}`;
  }

  function beep(ok) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "sine";
      o.frequency.value = ok ? 880 : 220;
      g.gain.value = 0.04;
      o.connect(g);
      g.connect(ctx.destination);
      o.start();
      setTimeout(() => {
        o.stop();
        ctx.close();
      }, ok ? 90 : 220);
    } catch (_e) {
      /* ignore */
    }
  }

  function toast(msg) {
    const el = document.getElementById("tsdToast");
    if (!el) return;
    el.textContent = String(msg || "");
    el.hidden = !msg;
    if (!msg) return;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      el.hidden = true;
    }, 2400);
  }

  function stopLoadingUi() {
    const ui = state.loadUi;
    if (ui.hintTimer) clearTimeout(ui.hintTimer);
    if (ui.elapsedTimer) clearInterval(ui.elapsedTimer);
    if (ui.rotateTimer) clearInterval(ui.rotateTimer);
    ui.hintTimer = null;
    ui.elapsedTimer = null;
    ui.rotateTimer = null;
    ui.token += 1;
  }

  function supplyNameHint(supplyId) {
    const sid = String(supplyId || "");
    if (state.supply && String(state.supply.supply_id || "") === sid) {
      const n = String(state.supply.name || "").trim();
      if (n) return n;
    }
    const fromList = (state.supplies || []).find((s) => String(s.supply_id || "") === sid);
    if (fromList) {
      const n = String(fromList.name || "").trim();
      if (n) return n;
    }
    return sid || "поставку";
  }

  function setLoadingStatus(text, stageIdx) {
    const statusEl = document.getElementById("tsdLoadStatus");
    if (statusEl) statusEl.textContent = String(text || "");
    if (stageIdx === undefined || stageIdx === null) return;
    const stages = document.querySelectorAll("#tsdLoadStages .tsd-load-stage");
    stages.forEach((el, i) => {
      el.classList.toggle("is-done", i < stageIdx);
      el.classList.toggle("is-active", i === stageIdx);
      el.classList.toggle("is-todo", i > stageIdx);
    });
  }

  function showLoadingScreen(opts) {
    stopLoadingUi();
    const token = state.loadUi.token;
    const title = String((opts && opts.title) || "Загрузка");
    const simple = !!(opts && opts.simple);
    const status = simple ? "" : String((opts && opts.status) || "Подождите…");
    const stages = simple ? [] : Array.isArray(opts && opts.stages) ? opts.stages : [];
    const main = document.getElementById("tsdMain");
    if (!main) return token;
    const stagesHtml = stages.length
      ? `<ol class="tsd-load-stages" id="tsdLoadStages" aria-hidden="true">
          ${stages
            .map(
              (label, i) =>
                `<li class="tsd-load-stage ${i === 0 ? "is-active" : "is-todo"}">${esc(label)}</li>`
            )
            .join("")}
        </ol>`
      : "";
    const detailsHtml = simple
      ? ""
      : `<div class="tsd-load-status" id="tsdLoadStatus">${esc(status)}</div>
        ${stagesHtml}
        <div class="tsd-load-elapsed" id="tsdLoadElapsed" hidden></div>
        <div class="tsd-load-hint" id="tsdLoadHint" hidden>Ещё загружаем, не уходите</div>`;
    main.innerHTML = `
      <div class="tsd-loading-screen${simple ? " is-simple" : ""}" role="status" aria-live="polite">
        <div class="tsd-load-spinner" aria-hidden="true"></div>
        <div class="tsd-load-title">${esc(title)}</div>
        ${detailsHtml}
      </div>`;
    if (simple) return token;
    state.loadUi.startedAt = Date.now();
    state.loadUi.hintTimer = setTimeout(() => {
      if (token !== state.loadUi.token) return;
      const hint = document.getElementById("tsdLoadHint");
      if (hint) hint.hidden = false;
    }, 9000);
    state.loadUi.elapsedTimer = setInterval(() => {
      if (token !== state.loadUi.token) return;
      const el = document.getElementById("tsdLoadElapsed");
      if (!el) return;
      const sec = Math.floor((Date.now() - state.loadUi.startedAt) / 1000);
      if (sec < 3) return;
      el.hidden = false;
      el.textContent = `Уже ${sec} сек`;
    }, 1000);
    return token;
  }

  function startLoadingRotate(steps, intervalMs) {
    const list = Array.isArray(steps) ? steps.filter(Boolean) : [];
    if (!list.length) return () => {};
    const token = state.loadUi.token;
    let idx = 0;
    const first = list[0];
    setLoadingStatus(first.status || first, first.stage);
    if (list.length === 1) return () => {};
    const ms = Math.max(1200, Number(intervalMs) || 2200);
    state.loadUi.rotateTimer = setInterval(() => {
      if (token !== state.loadUi.token) {
        clearInterval(state.loadUi.rotateTimer);
        state.loadUi.rotateTimer = null;
        return;
      }
      idx = (idx + 1) % list.length;
      const step = list[idx];
      setLoadingStatus(step.status || step, step.stage);
    }, ms);
    return () => {
      if (state.loadUi.rotateTimer) {
        clearInterval(state.loadUi.rotateTimer);
        state.loadUi.rotateTimer = null;
      }
    };
  }

  function setBanner(text, kind, opts) {
    if (!text) {
      state.banner = null;
      return;
    }
    const o = opts || {};
    state.banner = {
      text: String(text),
      kind: kind || "info",
      // Always closable (green/ok and errors) unless explicitly locked.
      dismissible: o.dismissible !== false,
      // Drop on next scan / save / refresh / search / filter unless locked.
      clearOnScan: o.clearOnScan !== false,
    };
  }

  function clearBanner(opts) {
    if (!state.banner) return;
    state.banner = null;
    if (!(opts && opts.silent) && state.route.view === "scan") {
      refreshScanBanner();
    }
  }

  function bannerHtml(banner) {
    if (!banner) return "";
    const dismissible = banner.dismissible !== false;
    const dismiss = dismissible
      ? `<button type="button" class="tsd-banner-dismiss" data-action="dismiss-banner" aria-label="Закрыть" title="Закрыть">×</button>`
      : "";
    return `<div class="tsd-banner is-${esc(banner.kind || "info")}${
      dismissible ? " is-dismissible" : ""
    }"><span class="tsd-banner-text">${esc(banner.text)}</span>${dismiss}</div>`;
  }

  function wireBannerDismiss(root) {
    const scope = root || document;
    const btn = scope.querySelector('[data-action="dismiss-banner"]');
    if (!btn) return;
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      clearBanner();
    });
  }

  function parseHash() {
    const raw = String(location.hash || "").replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean);
    if (!parts.length) return { view: "list", supplyId: "", mode: "" };
    if (parts[0] === "s" && parts[1]) {
      const mode = parts[2] === "kiz" || parts[2] === "pick" ? parts[2] : "";
      return { view: mode ? "scan" : "hub", supplyId: parts[1], mode };
    }
    return { view: "list", supplyId: "", mode: "" };
  }

  function navigate(hash) {
    const next = String(hash || "#/");
    if (location.hash === next) {
      onRoute();
      return;
    }
    location.hash = next;
  }

  function normalizeScan(raw) {
    return String(raw || "").replace(/\s+/g, "").trim();
  }

  /** Trim only space/tab/CR/LF — never GS (\\u001D). */
  function stripKizMarkEdges(value) {
    return String(value || "").replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
  }

  /**
   * Browsers drop real GS (\\u001D) from <input> typing. Capture keydown and
   * insert via value property. Arrow (↔) scanners keep the printable path.
   */
  function isGsKeyEvent(event) {
    if (!event) return false;
    if (event.key === "\u001D" || event.keyCode === 29 || event.which === 29) return true;
    if (event.ctrlKey && !event.altKey && !event.metaKey) {
      if (event.key === "]" || event.code === "BracketRight" || event.keyCode === 221) {
        return true;
      }
    }
    return false;
  }

  function insertGsIntoInput(input) {
    if (!input || input.disabled || input.readOnly) return false;
    const start = Number.isInteger(input.selectionStart)
      ? input.selectionStart
      : String(input.value || "").length;
    const end = Number.isInteger(input.selectionEnd)
      ? input.selectionEnd
      : String(input.value || "").length;
    const before = String(input.value || "").slice(0, start);
    const after = String(input.value || "").slice(end);
    input.value = `${before}\u001D${after}`;
    const pos = start + 1;
    try {
      input.setSelectionRange(pos, pos);
    } catch (_e) {
      /* ignore */
    }
    try {
      input.dispatchEvent(new Event("input", { bubbles: true }));
    } catch (_e) {
      /* ignore */
    }
    return true;
  }

  /**
   * Insert missing GS before AI 91/92 (scanner dropped \\u001D).
   * Idempotent — does not double-insert when GS / ↔→GS already present.
   */
  function ensureKizGsSeparators(value) {
    let text = String(value || "");
    if (!text) return "";
    text = text.replace(/(91[0-9A-Za-z+/]{4})(?!\u001D)(92)/, "$1\u001D$2");
    text = text.replace(/(?<!\u001D)(91[0-9A-Za-z+/]{4}\u001D92)/, "\u001D$1");
    return text;
  }

  /** Parity with desktop `_wbFbsKizNormalizeMark` (WB push / Save). */
  function normalizeKizMark(value) {
    // Scanners often emit ↔ instead of GS (\\u001D). Do not use \\s strip —
    // it must not destroy GS separators in Honest Sign / sgtin payloads.
    // Real GS is inserted on keydown (see tsdScanInput wiring).
    // If the wedge drops GS entirely, restore separators before AI 91/92.
    return ensureKizGsSeparators(
      stripKizMarkEdges(
        fixRuKeyboardLayout(
          String(value || "")
            .replace(/\u2194/g, "\u001D")
            .replace(/\r?\n/g, "")
        )
      )
    );
  }

  /** Parity with desktop `_wbFbsKizNormalizeCodesList`. */
  function normalizeKizCodesList(codes) {
    const seen = new Set();
    const out = [];
    for (const c of Array.isArray(codes) ? codes : []) {
      const n = normalizeKizMark(c);
      if (!n || seen.has(n)) continue;
      seen.add(n);
      out.push(n);
    }
    return out;
  }

  function hasCyrillic(s) {
    return /[А-Яа-яЁё]/.test(String(s || ""));
  }

  function fixRuKeyboardLayout(value) {
    const text = String(value || "");
    if (!/[а-яёА-ЯЁ]/.test(text)) return text;
    let out = "";
    for (const ch of text) {
      out += Object.prototype.hasOwnProperty.call(RU_LAYOUT_TO_EN, ch)
        ? RU_LAYOUT_TO_EN[ch]
        : ch;
    }
    return out;
  }

  function scanKey(s) {
    return normalizeScan(s).toLocaleLowerCase("en-US");
  }

  function digitsOnly(s) {
    return String(s || "").replace(/\D+/g, "");
  }

  function findBySticker(rows, raw) {
    // Parity with desktop Ozon/WB: primary sticker_barcode (QR/1D), then partA+partB / number.
    // One row must only match once (upper else lower) — duplicate pushes caused false «ambiguous».
    const scan = normalizeScan(raw);
    if (!scan) return { row: null, ambiguous: false };
    const rawKey = scanKey(scan);
    const byBarcode = [];
    const seenBc = new Set();
    for (const row of rows || []) {
      const id = rowScanId(row);
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
    if (byBarcode.length > 1) {
      return { row: null, ambiguous: true, matches: byBarcode };
    }

    const digits = digitsOnly(scan);
    const matches = [];
    const seenFuzzy = new Set();
    for (const row of rows || []) {
      const full = normalizeScan(
        row.sticker_number || row.sticker || row.posting_number || ""
      );
      const partA = normalizeScan(row.sticker_part_a);
      const partB = normalizeScan(row.sticker_part_b);
      if (
        (full && (rawKey === scanKey(full) || (digits && digits === digitsOnly(full)))) ||
        (partA && partB && digits && digits === digitsOnly(`${partA}${partB}`)) ||
        (partB && (rawKey === scanKey(partB) || (digits && digits === digitsOnly(partB))))
      ) {
        const id = rowScanId(row);
        if (id && seenFuzzy.has(id)) continue;
        if (id) seenFuzzy.add(id);
        matches.push(row);
      }
    }
    if (matches.length === 1) return { row: matches[0], ambiguous: false };
    if (matches.length > 1) {
      const exact = matches.find((r) => {
        const full = normalizeScan(r.sticker_number || r.posting_number || "");
        return scanKey(full) === rawKey || digitsOnly(full) === digits;
      });
      if (exact) return { row: exact, ambiguous: false };
      return { row: null, ambiguous: true, matches };
    }
    return { row: null, ambiguous: false };
  }

  function rowKizFilled(r) {
    const codes = Array.isArray(r.kiz_codes) ? r.kiz_codes : [];
    return codes.some((c) => String(c || "").trim());
  }

  function rowPickFilled(r) {
    return !!(r.pick_verified && String(r.pick_barcode || "").trim());
  }

  function gtinFromMark(mark) {
    // Parity with desktop `_wbFbsKizExtractGtin14`.
    const raw = normalizeKizMark(mark);
    if (!raw) return "";
    const m = raw.match(/^01(\d{14})/);
    if (m) return m[1];
    const m2 = raw.match(/(?:^|[\u001D])01(\d{14})/);
    return m2 ? m2[1] : "";
  }

  function orderSkuSet(row) {
    const set = new Set();
    const barcodes = Array.isArray(row.barcodes) ? row.barcodes : [];
    const skus = Array.isArray(row.skus) ? row.skus : [];
    for (const x of barcodes.concat(skus)) {
      const raw = String(x || "").trim();
      if (raw) set.add(raw);
      const d = digitsOnly(raw);
      if (d) set.add(d);
    }
    return set;
  }

  function markMatchesOrder(mark, row) {
    const gtin = gtinFromMark(mark);
    if (!gtin) {
      return {
        ok: false,
        error: "Не удалось выделить GTIN из кода маркировки (ожидается префикс 01 и 14 цифр).",
      };
    }
    // Product catalog flag: skip GTIN↔ШК match only (still require a parseable GTIN).
    if (row && row.skip_kiz_gtin_check) {
      return { ok: true };
    }
    const candidates = [gtin];
    if (gtin.startsWith("0")) candidates.push(gtin.slice(1));
    const orderSkus = orderSkuSet(row);
    if (!orderSkus.size) {
      return {
        ok: false,
        error: "У заказа нет штрихкодов товара — нельзя сверить GTIN маркировки.",
      };
    }
    if (!candidates.some((c) => orderSkus.has(c))) {
      const shown = gtin.startsWith("0") ? gtin.slice(1) : gtin;
      return { ok: false, error: `GTIN ${shown} не совпадает ни с одним ШК товара в заказе` };
    }
    return { ok: true };
  }

  function eanMatchesOrder(raw, row) {
    const dig = digitsOnly(raw);
    if (!(dig.length === 8 || dig.length === 12 || dig.length === 13 || dig.length === 14)) {
      return { ok: false, error: "Ожидается штрихкод EAN (8/13 цифр)" };
    }
    const orderSkus = orderSkuSet(row);
    if (!orderSkus.size) {
      return { ok: false, error: "У заказа нет штрихкодов товара — нельзя сверить ШК" };
    }
    const ok =
      orderSkus.has(dig) ||
      [...orderSkus].some((b) => digitsOnly(b) === dig || String(b).endsWith(dig) || dig.endsWith(digitsOnly(b)));
    if (!ok) return { ok: false, error: "ШК не подходит к товару в заказе" };
    return { ok: true };
  }

  function countProgress(rows, filledFn) {
    const total = (rows || []).length;
    const done = (rows || []).filter(filledFn).length;
    return { total, done, left: Math.max(0, total - done) };
  }

  async function loadSources() {
    const data = await api("/api/wb-fbs/tsd/sources");
    state.sources = Array.isArray(data) ? data : [];
    const sel = document.getElementById("tsdSourceSelect");
    if (!sel) return;
    const prev = localStorage.getItem(LS_SOURCE) || state.sourceId;
    sel.innerHTML = state.sources.length
      ? state.sources
          .map(
            (s) =>
              `<option value="${esc(s.id)}" data-marketplace="${esc(
                s.marketplace || "wb"
              )}">${esc(sourceOptionLabel(s))}</option>`
          )
          .join("")
      : `<option value="">Нет кабинетов</option>`;
    if (prev && state.sources.some((s) => String(s.id) === String(prev))) {
      sel.value = String(prev);
      state.sourceId = Number(prev);
    } else if (state.sources.length) {
      state.sourceId = Number(state.sources[0].id);
      sel.value = String(state.sourceId);
    } else {
      state.sourceId = null;
    }
  }

  async function loadSupplies() {
    if (!state.sourceId) {
      state.supplies = [];
      return;
    }
    const params = new URLSearchParams({
      source_id: String(state.sourceId),
      page: "1",
      page_size: "100",
    });
    if (state.search) params.set("search", state.search);
    const data = await api(`/api/wb-fbs/tsd/supplies?${params}`);
    state.supplies = Array.isArray(data.items) ? data.items : [];
  }

  async function loadSummary(supplyId) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const data = await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(supplyId)}/summary?${params}`
    );
    state.supply = data;
    return data;
  }

  async function loadKiz(supplyId) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const path = `/api/wb-fbs/tsd/supplies/${encodeURIComponent(supplyId)}/kiz?${params}`;
    let data = await api(path);
    if (isOzon()) {
      let remaining = Number(data?.marking_resolve?.remaining || 0);
      let guard = 0;
      while (remaining > 0 && guard < 200) {
        guard += 1;
        data = await api(path);
        const checked = Number(data?.marking_resolve?.checked || 0);
        remaining = Number(data?.marking_resolve?.remaining || 0);
        if (remaining > 0 && checked <= 0) remaining = 0;
      }
    }
    state.kizRows = Array.isArray(data.rows) ? data.rows.map((r) => ({ ...r })) : [];
    state.pendingKizClear = {};
    state.rowErrors = {};
  }

  async function loadPick(supplyId) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const path = `/api/wb-fbs/tsd/supplies/${encodeURIComponent(supplyId)}/pick-verify?${params}`;
    let data = await api(path);
    if (isOzon()) {
      let remaining = Number(data?.marking_resolve?.remaining || 0);
      let guard = 0;
      while (remaining > 0 && guard < 200) {
        guard += 1;
        data = await api(path);
        const checked = Number(data?.marking_resolve?.checked || 0);
        remaining = Number(data?.marking_resolve?.remaining || 0);
        if (remaining > 0 && checked <= 0) remaining = 0;
      }
    }
    state.pickRows = Array.isArray(data.rows) ? data.rows.map((r) => ({ ...r })) : [];
  }

  async function saveKizLocal(row, opts) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const scanId = rowScanId(row);
    const codes = normalizeKizCodesList(row.kiz_codes);
    row.kiz_codes = codes.length ? codes.slice() : [""];
    const item = isOzon()
      ? {
          posting_number: scanId,
          kiz_codes: codes,
          clear: !codes.length,
          expected_saved_at: String(row.kiz_saved_at || ""),
          force: !!state.forceSaveByOrder[scanId],
        }
      : {
          order_id: Number(row.order_id),
          kiz_codes: codes,
          clear: !codes.length,
          local_only: true,
          expected_saved_at: String(row.kiz_saved_at || ""),
          force: !!state.forceSaveByOrder[scanId],
        };
    const data = await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/kiz?${params}`,
      {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({ items: [item] }),
        keepalive: true,
      }
    );
    const result =
      (data.results || []).find((r) =>
        isOzon()
          ? String(r.posting_number || "") === scanId
          : Number(r.order_id) === Number(row.order_id)
      ) || null;
    if (!result) throw new Error("Сервер не вернул результат сохранения КИЗ");
    if (result.conflict) {
      // Another device/operator won — adopt server codes. Do NOT force-overwrite
      // with stale TSD memory (that used to wipe PC saves on autosave retry).
      row.kiz_saved_at = String(result.kiz_saved_at || row.kiz_saved_at || "");
      if (Array.isArray(result.kiz_codes)) {
        const serverCodes = normalizeKizCodesList(result.kiz_codes);
        row.kiz_codes = serverCodes.length ? serverCodes.slice() : [""];
        state.baselineKizByOrder[scanId] = serverCodes.slice();
      }
      delete state.forceSaveByOrder[scanId];
      const err = new Error(
        result.error ||
          "Заказ уже сохранён другим оператором — проверьте КИЗ и повторите"
      );
      err.conflict = true;
      throw err;
    }
    if (!result.ok && !result.local_ok) {
      throw new Error(result.error || "Не удалось сохранить КИЗ локально");
    }
    if (result.kiz_saved_at) row.kiz_saved_at = String(result.kiz_saved_at);
    delete state.forceSaveByOrder[scanId];
    return result;
  }

  async function savePickLocal(row, opts) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const scanId = rowScanId(row);
    const intendedVerified = !!row.pick_verified;
    const intendedBarcode = String(row.pick_barcode || "").trim();
    // Mirror KIZ: empty/unverified must send clear:true, otherwise the server
    // skips the item with no results[] entry and TSD shows
    // «Сервер не вернул результат сохранения ШК» after × clear.
    const clearPick = !intendedVerified && !intendedBarcode;
    const pickKey = forceSaveKey(row, "pick");
    const item = isOzon()
      ? {
          posting_number: scanId,
          pick_verified: intendedVerified,
          pick_barcode: intendedBarcode,
          clear: clearPick,
          expected_verified_at: String(row.pick_verified_at || ""),
          force: !!state.forceSaveByOrder[pickKey],
        }
      : {
          order_id: Number(row.order_id),
          pick_verified: intendedVerified,
          pick_barcode: intendedBarcode,
          clear: clearPick,
          local_only: true,
          expected_verified_at: String(row.pick_verified_at || ""),
          force: !!state.forceSaveByOrder[pickKey],
        };
    const data = await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/pick-verify?${params}`,
      {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({ items: [item] }),
        keepalive: true,
      }
    );
    const result =
      (data.results || []).find((r) =>
        isOzon()
          ? String(r.posting_number || "") === scanId
          : Number(r.order_id) === Number(row.order_id)
      ) || null;
    if (!result) throw new Error("Сервер не вернул результат сохранения ШК");
    if (result.conflict) {
      // Adopt server pick state — do not force-overwrite another device's save.
      row.pick_verified_at = String(result.pick_verified_at || row.pick_verified_at || "");
      if (result.pick_verified != null) row.pick_verified = !!result.pick_verified;
      if (result.pick_barcode != null) {
        row.pick_barcode = String(result.pick_barcode || "").trim();
      } else if (result.barcode != null) {
        row.pick_barcode = String(result.barcode || "").trim();
      }
      if (row.pick_verified && row.pick_barcode) {
        state.baselinePickByOrder[scanId] = {
          verified: true,
          barcode: String(row.pick_barcode || "").trim(),
        };
      }
      delete state.forceSaveByOrder[pickKey];
      const err = new Error(
        result.error ||
          "Заказ уже сохранён другим оператором — проверьте ШК и повторите"
      );
      err.conflict = true;
      throw err;
    }
    if (!result.ok) {
      throw new Error(result.error || "Не удалось сохранить проверку ШК");
    }
    if (result.pick_verified_at) row.pick_verified_at = String(result.pick_verified_at);
    delete state.forceSaveByOrder[pickKey];
    return result;
  }

  function captureScanBaselines(mode) {
    if (mode === "kiz") {
      state.baselineKizByOrder = {};
      for (const row of state.kizRows || []) {
        const id = rowScanId(row);
        if (!id) continue;
        state.baselineKizByOrder[id] = normalizeKizCodesList(row.kiz_codes);
      }
      return;
    }
    state.baselinePickByOrder = {};
    for (const row of state.pickRows || []) {
      const id = rowScanId(row);
      if (!id) continue;
      state.baselinePickByOrder[id] = {
        verified: !!row.pick_verified,
        barcode: String(row.pick_barcode || "").trim(),
      };
    }
  }

  function kizBaselineEquals(orderId, codes) {
    const id = String(orderId);
    const base = state.baselineKizByOrder[id];
    if (!Array.isArray(base)) return false;
    const cur = normalizeKizCodesList(codes);
    if (base.length !== cur.length) return false;
    for (let i = 0; i < base.length; i += 1) {
      if (base[i] !== cur[i]) return false;
    }
    return true;
  }

  function pickBaselineEquals(orderId, row) {
    const id = String(orderId);
    const base = state.baselinePickByOrder[id];
    if (!base) return false;
    return (
      base.verified === !!row.pick_verified &&
      base.barcode === String(row.pick_barcode || "").trim()
    );
  }

  /** Queue silent local-only save — scan path never awaits (parity with desktop modal). */
  function scheduleKizLocalAutosave(orderId) {
    const id = String(orderId || "").trim();
    if (!id) return;
    const seq = (Number(state.localAutosaveSeqByOrder[id]) || 0) + 1;
    state.localAutosaveSeqByOrder[id] = seq;
    const run = () => flushKizLocalAutosave(id, seq);
    state.localAutosaveChain = (state.localAutosaveChain || Promise.resolve())
      .then(run, run)
      .catch(() => {});
  }

  function schedulePickLocalAutosave(orderId) {
    const id = String(orderId || "").trim();
    if (!id) return;
    const key = `pick:${id}`;
    const seq = (Number(state.localAutosaveSeqByOrder[key]) || 0) + 1;
    state.localAutosaveSeqByOrder[key] = seq;
    const run = () => flushPickLocalAutosave(id, seq);
    state.localAutosaveChain = (state.localAutosaveChain || Promise.resolve())
      .then(run, run)
      .catch(() => {});
  }

  async function awaitLocalAutosaves() {
    for (let i = 0; i < 40; i += 1) {
      const tip = state.localAutosaveChain || Promise.resolve();
      try {
        await tip;
      } catch (_e) {
        /* ignore autosave faults — explicit Save still covers */
      }
      const latest = state.localAutosaveChain || tip;
      const inflight = Number(state.localAutosaveInflight) || 0;
      if (tip === latest && inflight <= 0) return;
    }
  }

  async function flushKizLocalAutosave(orderId, seq, attempt = 0) {
    const id = String(orderId || "").trim();
    if (!id) return;
    if ((Number(state.localAutosaveSeqByOrder[id]) || 0) !== seq) return;
    if (state.route.view !== "scan" || state.route.mode !== "kiz") return;
    const row = findRowByScanId(state.kizRows, id);
    if (!row) return;
    const codes = normalizeKizCodesList(row.kiz_codes);
    const wasBound = !!row.kiz_bound;
    const hadLocal = !!row.kiz_local;
    const clear =
      !codes.length &&
      (wasBound || hadLocal || !!state.pendingKizClear[id]);
    if (!codes.length && !clear) return;
    if (kizBaselineEquals(id, codes) && !clear) return;

    state.localAutosaveInflight = (Number(state.localAutosaveInflight) || 0) + 1;
    try {
      await saveKizLocal(row);
      if ((Number(state.localAutosaveSeqByOrder[id]) || 0) !== seq) return;
      row.kiz_local = true;
      state.baselineKizByOrder[id] = codes.slice();
    } catch (e) {
      if ((Number(state.localAutosaveSeqByOrder[id]) || 0) !== seq) return;
      // Conflict already adopted server codes — never force-retry (would wipe PC).
      // Still refresh UI: otherwise DOM keeps stale local counts after adopt.
      if (e && e.conflict) {
        setBanner(e.message || String(e), "err");
        if (!patchScanCard("kiz")) renderScan();
        else refreshScanChrome("kiz");
        return;
      }
      if (attempt < 1) {
        await new Promise((r) => setTimeout(r, 120));
        if ((Number(state.localAutosaveSeqByOrder[id]) || 0) !== seq) return;
        return flushKizLocalAutosave(id, seq, attempt + 1);
      }
      setBanner(e.message || String(e), "err");
      refreshScanChrome("kiz");
    } finally {
      state.localAutosaveInflight = Math.max(
        0,
        (Number(state.localAutosaveInflight) || 0) - 1
      );
    }
  }

  async function flushPickLocalAutosave(orderId, seq, attempt = 0) {
    const id = String(orderId || "").trim();
    const key = `pick:${id}`;
    if (!id) return;
    if ((Number(state.localAutosaveSeqByOrder[key]) || 0) !== seq) return;
    if (state.route.view !== "scan" || state.route.mode !== "pick") return;
    const row = findRowByScanId(state.pickRows, id);
    if (!row) return;
    if (pickBaselineEquals(id, row)) return;

    state.localAutosaveInflight = (Number(state.localAutosaveInflight) || 0) + 1;
    try {
      await savePickLocal(row);
      if ((Number(state.localAutosaveSeqByOrder[key]) || 0) !== seq) return;
      state.baselinePickByOrder[id] = {
        verified: !!row.pick_verified,
        barcode: String(row.pick_barcode || "").trim(),
      };
    } catch (e) {
      if ((Number(state.localAutosaveSeqByOrder[key]) || 0) !== seq) return;
      // Conflict already adopted server pick — do not retry with local ШК.
      if (e && e.conflict) {
        setBanner(e.message || String(e), "err");
        if (!patchScanCard("pick")) renderScan();
        else refreshScanChrome("pick");
        return;
      }
      if (attempt < 1) {
        await new Promise((r) => setTimeout(r, 120));
        if ((Number(state.localAutosaveSeqByOrder[key]) || 0) !== seq) return;
        return flushPickLocalAutosave(id, seq, attempt + 1);
      }
      setBanner(e.message || String(e), "err");
      refreshScanChrome("pick");
    } finally {
      state.localAutosaveInflight = Math.max(
        0,
        (Number(state.localAutosaveInflight) || 0) - 1
      );
    }
  }

  /** Explicit «Сохранить»: WB pushes to API; Ozon saves locally only. */
  async function saveKizPushAll(opts) {
    const silent = !!(opts && opts.silent);
    if (state.saving) return { status: "busy" };
    clearBanner({ silent: true });
    await awaitLocalAutosaves();
    const rows = state.kizRows || [];
    const items = [];
    for (const row of rows) {
      const id = rowScanId(row);
      if (!id) continue;
      const codes = normalizeKizCodesList(row.kiz_codes);
      if (isOzon()) {
        const changed =
          !kizBaselineEquals(id, codes) || !!state.pendingKizClear[id];
        if (!changed) continue;
        items.push({
          posting_number: id,
          kiz_codes: codes,
          clear: !codes.length,
          expected_saved_at: String(row.kiz_saved_at || ""),
          force: !!state.forceSaveByOrder[id],
        });
        continue;
      }
      const oid = Number(row.order_id);
      if (!Number.isFinite(oid)) continue;
      if (!codes.length) {
        if (!rowNeedsKizWbClear(row)) continue;
        items.push({
          order_id: oid,
          kiz_codes: [],
          clear: true,
          expected_saved_at: String(row.kiz_saved_at || ""),
          force: !!state.forceSaveByOrder[id],
        });
        continue;
      }
      row.kiz_codes = codes.slice();
      items.push({
        order_id: oid,
        kiz_codes: codes,
        clear: false,
        expected_saved_at: String(row.kiz_saved_at || ""),
        force: !!state.forceSaveByOrder[id],
      });
    }
    if (!items.length) {
      if (!silent) {
        setBanner(
          isOzon() ? "Нет изменений КИЗ для сохранения" : "Нет КИЗ для отправки в WB",
          "warn"
        );
        renderScan();
      }
      return { status: "empty" };
    }
    state.saving = true;
    setBanner(
      isOzon()
        ? `Сохранение ${items.length}…`
        : `Сохранение ${items.length} в WB…`,
      "info"
    );
    renderScan();
    let status = "ok";
    try {
      const params = new URLSearchParams({ source_id: String(state.sourceId) });
      const url = `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/kiz?${params}`;
      // Chunk like desktop marking — one huge PUT can hit nginx/proxy 504.
      const CHUNK = isOzon() ? 15 : 20;
      const allResults = [];
      for (let i = 0; i < items.length; i += CHUNK) {
        const chunk = items.slice(i, i + CHUNK);
        if (items.length > CHUNK) {
          setBanner(
            isOzon()
              ? `Сохранение… ${Math.min(i + CHUNK, items.length)}/${items.length}`
              : `Сохранение в WB… ${Math.min(i + CHUNK, items.length)}/${items.length}`,
            "info"
          );
        }
        const data = await api(url, {
          method: "PUT",
          headers: jsonHeaders(),
          body: JSON.stringify({ items: chunk }),
        });
        allResults.push(...(data.results || []));
      }
      let okN = 0;
      let errN = 0;
      let conflictN = 0;
      for (const r of allResults) {
        const id = isOzon()
          ? String(r.posting_number || "")
          : String(Number(r.order_id));
        const row = findRowByScanId(rows, id);
        if (!row) continue;
        if (r.conflict) {
          conflictN += 1;
          // PC/other TSD won — show their codes; do not arm force (would wipe them).
          row.kiz_saved_at = String(r.kiz_saved_at || row.kiz_saved_at || "");
          if (Array.isArray(r.kiz_codes)) {
            const serverCodes = normalizeKizCodesList(r.kiz_codes);
            row.kiz_codes = serverCodes.length ? serverCodes.slice() : [""];
            state.baselineKizByOrder[id] = serverCodes.slice();
          }
          delete state.forceSaveByOrder[id];
          delete state.pendingKizClear[id];
          continue;
        }
        if (r.kiz_saved_at) row.kiz_saved_at = String(r.kiz_saved_at);
        if (isOzon()) {
          if (r.ok) {
            okN += 1;
            delete state.forceSaveByOrder[id];
            delete state.rowErrors[id];
            delete state.pendingKizClear[id];
            row.kiz_local = true;
            state.baselineKizByOrder[id] = normalizeKizCodesList(row.kiz_codes);
          } else {
            errN += 1;
            if (r.error) state.rowErrors[id] = String(r.error);
          }
          continue;
        }
        if (r.kiz_wb_synced != null) row.kiz_wb_synced = !!r.kiz_wb_synced;
        if (r.ok || r.wb_ok) {
          okN += 1;
          delete state.forceSaveByOrder[id];
          delete state.rowErrors[id];
          const pushedCodes = normalizeKizCodesList(
            Array.isArray(r.kiz_codes) ? r.kiz_codes : row.kiz_codes
          );
          if (!pushedCodes.length) {
            delete state.pendingKizClear[id];
            row.kiz_bound = false;
            row.kiz_local = false;
            row.kiz_wb_synced = true;
            row.kiz_status = "empty";
            row.kiz_codes = [""];
            state.sessionScannedIds = (state.sessionScannedIds || []).filter(
              (x) => String(x) !== id
            );
          } else {
            delete state.pendingKizClear[id];
            row.kiz_bound = true;
            row.kiz_local = true;
            row.kiz_codes = pushedCodes.slice();
            if (row.kiz_status === "empty") row.kiz_status = "pending";
          }
        } else if (r.local_ok) {
          errN += 1;
          if (r.error) state.rowErrors[id] = String(r.error);
        } else {
          errN += 1;
          if (r.error) state.rowErrors[id] = String(r.error);
        }
      }
      if (conflictN) {
        status = "conflict";
        setBanner(
          `На сервере уже другое сохранение (ПК/др. ТСД) у ${conflictN} ${isOzon() ? "отпр." : "заказ(ов)"} — показаны актуальные данные`,
          "err"
        );
      } else if (errN && okN) {
        status = "error";
        setBanner(
          isOzon()
            ? `Сохранено ${okN}, ошибок ${errN}`
            : `Отправлено ${okN}, ошибок ${errN} — повторите «Сохранить»`,
          "warn"
        );
      } else if (errN) {
        status = "error";
        setBanner(
          isOzon() ? `Не удалось сохранить (${errN})` : `Не удалось отправить в WB (${errN})`,
          "err"
        );
      } else {
        setBanner(
          isOzon() ? `Сохранено локально: ${okN}` : `Сохранено в WB: ${okN}`,
          "ok"
        );
      }
    } catch (e) {
      status = "error";
      setBanner(e.message || String(e), "err");
    } finally {
      state.saving = false;
      renderScan();
    }
    return { status };
  }

  /** Explicit «Сохранить» for pick: local-only batch (like desktop modal). */
  async function savePickLocalAll(opts) {
    const silent = !!(opts && opts.silent);
    if (state.saving) return { status: "busy" };
    clearBanner({ silent: true });
    await awaitLocalAutosaves();
    const rows = state.pickRows || [];
    const items = [];
    for (const row of rows) {
      const id = rowScanId(row);
      if (!id) continue;
      if (!rowPickFilled(row)) continue;
      items.push(
        isOzon()
          ? {
              posting_number: id,
              pick_verified: true,
              pick_barcode: String(row.pick_barcode || "").trim(),
              expected_verified_at: String(row.pick_verified_at || ""),
              force: !!state.forceSaveByOrder[`pick:${id}`],
            }
          : {
              order_id: Number(row.order_id),
              pick_verified: true,
              pick_barcode: String(row.pick_barcode || "").trim(),
              expected_verified_at: String(row.pick_verified_at || ""),
              force: !!state.forceSaveByOrder[`pick:${id}`],
            }
      );
    }
    if (!items.length) {
      if (!silent) {
        setBanner("Нет подтверждённых ШК для сохранения", "warn");
        renderScan();
      }
      return { status: "empty" };
    }
    state.saving = true;
    setBanner(`Сохранение ${items.length}…`, "info");
    renderScan();
    let status = "ok";
    try {
      const params = new URLSearchParams({ source_id: String(state.sourceId) });
      const url = `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/pick-verify?${params}`;
      const CHUNK = 40;
      const allResults = [];
      for (let i = 0; i < items.length; i += CHUNK) {
        const chunk = items.slice(i, i + CHUNK);
        if (items.length > CHUNK) {
          setBanner(
            `Сохранение… ${Math.min(i + CHUNK, items.length)}/${items.length}`,
            "info"
          );
        }
        const data = await api(url, {
          method: "PUT",
          headers: jsonHeaders(),
          body: JSON.stringify({ items: chunk }),
        });
        allResults.push(...(data.results || []));
      }
      let okN = 0;
      let errN = 0;
      let conflictN = 0;
      for (const r of allResults) {
        const id = isOzon()
          ? String(r.posting_number || "")
          : String(Number(r.order_id));
        const row = findRowByScanId(rows, id);
        if (!row) continue;
        const pickKey = `pick:${id}`;
        if (r.conflict) {
          conflictN += 1;
          // Adopt server pick — do not arm force (would wipe PC/other TSD).
          row.pick_verified_at = String(r.pick_verified_at || row.pick_verified_at || "");
          if (r.pick_verified != null) row.pick_verified = !!r.pick_verified;
          if (r.pick_barcode != null) {
            row.pick_barcode = String(r.pick_barcode || "").trim();
          } else if (r.barcode != null) {
            row.pick_barcode = String(r.barcode || "").trim();
          }
          if (row.pick_verified && row.pick_barcode) {
            state.baselinePickByOrder[id] = {
              verified: true,
              barcode: String(row.pick_barcode || "").trim(),
            };
          }
          delete state.forceSaveByOrder[pickKey];
          continue;
        }
        if (r.ok) {
          okN += 1;
          if (r.pick_verified_at) row.pick_verified_at = String(r.pick_verified_at);
          delete state.forceSaveByOrder[pickKey];
        } else {
          errN += 1;
        }
      }
      if (conflictN) {
        status = "conflict";
        setBanner(
          `На сервере уже другое сохранение (ПК/др. ТСД) у ${conflictN} заказ(ов) — показаны актуальные данные`,
          "err"
        );
      } else if (errN) {
        status = "error";
        setBanner(`Сохранено ${okN}, ошибок ${errN}`, "warn");
      } else {
        setBanner(`Сохранено локально: ${okN}`, "ok");
      }
    } catch (e) {
      status = "error";
      setBanner(e.message || String(e), "err");
    } finally {
      state.saving = false;
      renderScan();
    }
    return { status };
  }

  function noteSessionScanned(orderId) {
    const id = String(orderId || "").trim();
    if (!id) return;
    state.sessionScannedIds = (state.sessionScannedIds || []).filter(
      (x) => String(x) !== id
    );
    state.sessionScannedIds.push(id);
  }

  function rowNeedsKizWbClear(row) {
    if (isOzon()) return false;
    const id = rowScanId(row);
    if (!id) return false;
    if (rowKizFilled(row)) return false;
    if (state.pendingKizClear[id]) return true;
    if (row.kiz_bound) return true;
    if (row.kiz_local && row.kiz_wb_synced === false) return true;
    return false;
  }

  function hasPendingKizPush() {
    if (isOzon()) {
      return (state.kizRows || []).some((row) => {
        const id = rowScanId(row);
        if (!id) return false;
        const codes = normalizeKizCodesList(row.kiz_codes);
        return !kizBaselineEquals(id, codes) || !!state.pendingKizClear[id];
      });
    }
    return (state.kizRows || []).some((row) => {
      const id = rowScanId(row);
      if (!id) return false;
      if (rowNeedsKizWbClear(row)) return true;
      return rowKizFilled(row);
    });
  }

  function removeSessionScanned(orderId) {
    const id = String(orderId || "").trim();
    if (!id) return;
    state.sessionScannedIds = (state.sessionScannedIds || []).filter(
      (x) => String(x) !== id
    );
  }

  function orderedScannedRows(mode) {
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const fn =
      mode === "kiz"
        ? (r) => {
            if (rowKizFilled(r)) return true;
            const id = rowScanId(r);
            return (
              !!state.pendingKizClear[id] &&
              (state.sessionScannedIds || []).some((x) => String(x) === id)
            );
          }
        : rowPickFilled;
    const filled = (rows || []).filter(fn);
    const byId = new Map(filled.map((r) => [rowScanId(r), r]));
    const out = [];
    const seen = new Set();
    for (let i = (state.sessionScannedIds || []).length - 1; i >= 0; i -= 1) {
      const id = String(state.sessionScannedIds[i]);
      const row = byId.get(id);
      if (row && !seen.has(id)) {
        out.push(row);
        seen.add(id);
      }
    }
    for (const row of filled) {
      const id = rowScanId(row);
      if (!seen.has(id)) {
        out.push(row);
        seen.add(id);
      }
    }
    return out;
  }

  function shortKizDisplay(code) {
    const c = String(code || "").trim();
    // Keep most of the mark visible on a full TSD row before ellipsis.
    if (c.length > 56) return `${c.slice(0, 40)}…${c.slice(-12)}`;
    return c;
  }

  function formatBoldLastDigits(text, n) {
    const s = String(text || "").trim();
    const count = Math.max(1, Number(n) || 4);
    if (!s || s === "—") return esc(s || "—");
    let seen = 0;
    let cut = -1;
    for (let i = s.length - 1; i >= 0; i -= 1) {
      if (/\d/.test(s[i])) {
        seen += 1;
        if (seen === count) {
          cut = i;
          break;
        }
      }
    }
    if (cut < 0) {
      if (s.length <= count) {
        return `<strong class="tsd-sticker-tail">${esc(s)}</strong>`;
      }
      return `${esc(s.slice(0, -count))}<strong class="tsd-sticker-tail">${esc(
        s.slice(-count)
      )}</strong>`;
    }
    return `${esc(s.slice(0, cut))}<strong class="tsd-sticker-tail">${esc(
      s.slice(cut)
    )}</strong>`;
  }

  /** Ozon posting: highlight 4 chars immediately left of the first «-» (same as web). */
  function formatOzonPostingHtml(postingNumber) {
    const s = String(postingNumber || "").trim();
    if (!s) return "—";
    const hi = (text) => `<span class="tsd-posting-hi">${esc(text)}</span>`;
    const dash = s.indexOf("-");
    if (dash > 0) {
      const head = s.slice(0, dash);
      const tail = s.slice(dash);
      if (head.length >= 4) {
        return `${esc(head.slice(0, -4))}${hi(head.slice(-4))}${esc(tail)}`;
      }
      return `${hi(head)}${esc(tail)}`;
    }
    if (s.length > 4) return `${esc(s.slice(0, -4))}${hi(s.slice(-4))}`;
    return hi(s);
  }

  function filledKizEntries(row) {
    return (Array.isArray(row.kiz_codes) ? row.kiz_codes : [])
      .map((c, idx) => ({ code: String(c || "").trim(), idx }))
      .filter((x) => x.code);
  }

  function orderBarcodesLabel(row) {
    const seen = new Set();
    const out = [];
    const lists = [row && row.barcodes, row && row.skus];
    for (const list of lists) {
      if (!Array.isArray(list)) continue;
      for (const raw of list) {
        const b = String(raw || "").trim();
        if (!b || seen.has(b)) continue;
        seen.add(b);
        out.push(b);
      }
    }
    return out.join(", ");
  }

  function rowPhotoHtml(row, size) {
    const wh = Number(size) > 0 ? Number(size) : 48;
    return row && row.product_photo
      ? `<img src="${esc(row.product_photo)}" alt="" width="${wh}" height="${wh}" />`
      : `<span class="tsd-scanned-ph" aria-hidden="true"></span>`;
  }

  /** Shared Ozon card details under the divider: Отправление → Стикер → ГМ → ШК/КИЗ. */
  function renderOzonOrderDetailsHtml(row, mode) {
    const posting = String(row.posting_number || rowScanId(row) || "").trim();
    const sticker = String(
      row.sticker_barcode || row.sticker_lower_barcode || ""
    ).trim();
    const gmCode = rowGmCode(row);
    const gmErr = String(row.container_sync_error || "").trim();
    const barcodes = orderBarcodesLabel(row);
    let markOrSkuHtml = "";
    if (mode === "kiz") {
      const entries = filledKizEntries(row);
      markOrSkuHtml = entries.length
        ? `<div class="tsd-scanned-kizs">${entries
            .map(
              (e) => `
              <div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">КИЗ:</span>
                <span class="tsd-scanned-kv-val">${esc(shortKizDisplay(e.code))}</span>
              </div>`
            )
            .join("")}</div>`
        : `<div class="tsd-scanned-kv"><span class="tsd-scanned-label">КИЗ:</span><span class="tsd-scanned-kv-val">—</span></div>`;
    } else {
      const verified = String(row.pick_barcode || "").trim();
      const showBc = verified || barcodes;
      markOrSkuHtml = showBc
        ? `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">ШК:</span>
                <span class="tsd-scanned-kv-val">${esc(verified || barcodes)}</span>
              </div>`
        : "";
    }
    const postingHtml = `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">Отправление:</span>
                <span class="tsd-scanned-kv-val tsd-scanned-posting">${formatOzonPostingHtml(
                  posting
                )}</span>
              </div>`;
    const stickerHtml = sticker
      ? `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">Стикер:</span>
                <span class="tsd-scanned-kv-val tsd-scanned-sticker">${esc(
                  sticker
                )}</span>
              </div>`
      : "";
    const gmHtml = gmCode
      ? `<div class="tsd-scanned-kv${gmErr ? " is-gm-err" : ""}">
                <span class="tsd-scanned-label">ГМ:</span>
                <span class="tsd-scanned-kv-val tsd-scanned-gm-code" title="${esc(
                  gmErr || gmCode
                )}">${esc(gmCode)}</span>
              </div>`
      : "";
    return `${postingHtml}${stickerHtml}${gmHtml}${markOrSkuHtml}`;
  }

  /** Ozon card body: photo + name on top, details under the gray line. */
  function renderOzonOrderCardBodyHtml(row, mode) {
    return `
            <div class="tsd-scanned-top">
              ${rowPhotoHtml(row, 48)}
              <div class="tsd-scanned-text">
                <div class="tsd-scanned-name">${esc(
                  row.product_name || row.article || "—"
                )}</div>
              </div>
            </div>
            <div class="tsd-scanned-details">${renderOzonOrderDetailsHtml(
              row,
              mode
            )}</div>`;
  }

  /** Full Ozon order card — same markup for scanned list, search and filters. */
  function renderOzonOrderCardHtml(row, mode, opts) {
    const oid = esc(rowScanId(row));
    const selectable = !!(opts && opts.selectable);
    const pickAttrs = selectable
      ? ` data-action="pick-search-order" data-order-id="${oid}" role="button" tabindex="0"`
      : "";
    return `
          <div class="tsd-scanned-item tsd-scanned-item-ozon${
            selectable ? " is-selectable" : ""
          }"${pickAttrs}>
            <button type="button" class="tsd-scanned-clear"
              data-action="clear-scanned-all" data-order-id="${oid}"
              aria-label="Очистить заказ" title="Очистить КИЗ/ШК и снять с ГМ">×</button>
            ${renderOzonOrderCardBodyHtml(row, mode)}
          </div>`;
  }

  /** WB card details under the divider: Заказ → Стикер → ШК → КИЗ. */
  function renderWbOrderDetailsHtml(row, mode) {
    const orderId = String(row.order_id || rowScanId(row) || "").trim() || "—";
    const sticker = String(
      row.sticker_number ||
        row.sticker_barcode ||
        row.sticker_lower_barcode ||
        ""
    ).trim();
    const barcodes = orderBarcodesLabel(row);
    const verified = String(row.pick_barcode || "").trim();
    const orderHtml = `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">Заказ:</span>
                <span class="tsd-scanned-kv-val tsd-scanned-order-id">${esc(
                  orderId
                )}</span>
              </div>`;
    const stickerHtml = `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">Стикер:</span>
                <span class="tsd-scanned-kv-val tsd-scanned-sticker">${formatBoldLastDigits(
                  sticker || "—",
                  4
                )}</span>
              </div>`;
    const skuHtml = `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">ШК:</span>
                <span class="tsd-scanned-kv-val">${esc(
                  verified || barcodes || "—"
                )}</span>
              </div>`;
    let kizHtml = "";
    if (mode === "kiz") {
      const entries = filledKizEntries(row);
      kizHtml = entries.length
        ? `<div class="tsd-scanned-kizs">${entries
            .map(
              (e) => `
              <div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">КИЗ:</span>
                <span class="tsd-scanned-kv-val">${esc(shortKizDisplay(e.code))}</span>
              </div>`
            )
            .join("")}</div>`
        : `<div class="tsd-scanned-kv"><span class="tsd-scanned-label">КИЗ:</span><span class="tsd-scanned-kv-val">—</span></div>`;
    }
    return `${orderHtml}${stickerHtml}${skuHtml}${kizHtml}`;
  }

  /** WB card body: photo + name on top, details under the gray line. */
  function renderWbOrderCardBodyHtml(row, mode) {
    return `
            <div class="tsd-scanned-top">
              ${rowPhotoHtml(row, 48)}
              <div class="tsd-scanned-text">
                <div class="tsd-scanned-name">${esc(
                  row.product_name || row.article || "—"
                )}</div>
              </div>
            </div>
            <div class="tsd-scanned-details">${renderWbOrderDetailsHtml(
              row,
              mode
            )}</div>`;
  }

  /** Full WB order card — same markup for scanned list, search and filters. */
  function renderWbOrderCardHtml(row, mode, opts) {
    const oid = esc(rowScanId(row));
    const selectable = !!(opts && opts.selectable);
    const pickAttrs = selectable
      ? ` data-action="pick-search-order" data-order-id="${oid}" role="button" tabindex="0"`
      : "";
    const clearTitle =
      mode === "kiz" ? "Очистить КИЗ" : "Очистить проверку ШК";
    return `
          <div class="tsd-scanned-item tsd-scanned-item-wb${
            selectable ? " is-selectable" : ""
          }"${pickAttrs}>
            <button type="button" class="tsd-scanned-clear"
              data-action="clear-scanned-all" data-order-id="${oid}"
              aria-label="Очистить заказ" title="${clearTitle}">×</button>
            ${renderWbOrderCardBodyHtml(row, mode)}
          </div>`;
  }


  function renderScannedListHtml(mode) {
    const scanned = orderedScannedRows(mode);
    if (!scanned.length) {
      return `
        <section class="tsd-scanned" aria-label="Просканированные заказы">
          <h2 class="tsd-scanned-title">Просканировано</h2>
          <div class="tsd-scanned-empty">Пока пусто — сканируйте стикер и ${
            mode === "kiz" ? "КИЗ" : "ШК"
          }</div>
        </section>`;
    }
    const items = scanned
      .map((r) => {
        const oid = esc(rowScanId(r));
        const barcodes = orderBarcodesLabel(r);
        let detailHtml = "";
        if (mode === "kiz") {
          const entries = filledKizEntries(r);
          detailHtml = entries.length
            ? `<div class="tsd-scanned-kizs">${entries
                .map(
                  (e) => `
              <div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">КИЗ:</span>
                <span class="tsd-scanned-kv-val">${esc(shortKizDisplay(e.code))}</span>
              </div>`
                )
                .join("")}</div>`
            : `<div class="tsd-scanned-kv"><span class="tsd-scanned-label">КИЗ:</span><span class="tsd-scanned-kv-val">—</span></div>`;
        } else {
          const verified = String(r.pick_barcode || "").trim();
          if (isOzon()) {
            const showBc = verified || barcodes;
            detailHtml = showBc
              ? `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">ШК:</span>
                <span class="tsd-scanned-kv-val">${esc(verified || barcodes)}</span>
              </div>`
              : "";
          } else {
            detailHtml =
              !barcodes && verified
                ? `<div class="tsd-scanned-kv">
                <span class="tsd-scanned-label">ШК:</span>
                <span class="tsd-scanned-kv-val">${esc(verified)}</span>
              </div>`
                : "";
          }
        }

        if (isOzon()) {
          return renderOzonOrderCardHtml(r, mode, { selectable: false });
        }
        return renderWbOrderCardHtml(r, mode, { selectable: false });
      })
      .join("");
    return `
      <section class="tsd-scanned" aria-label="Просканированные заказы">
        <h2 class="tsd-scanned-title">Просканировано · ${scanned.length}</h2>
        <div class="tsd-scanned-list" id="tsdScannedList">${items}</div>
      </section>`;
  }

  async function unbindGmPosting(postingNumber, containerId) {
    const sid = String(state.route.supplyId || "").trim();
    const sourceId = Number(state.sourceId || 0) || 0;
    if (!sid || !sourceId) return null;
    return api(
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/unbind`,
      {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({
          source_id: sourceId,
          posting_number: postingNumber,
          container_id: containerId || null,
        }),
      }
    );
  }

  function clearRowGmLocal(row) {
    if (!row) return;
    row.container_id = null;
    row.container_barcode = "";
    row.container_synced = false;
    row.container_sync_error = "";
  }

  /**
   * Ozon TSD: one × clears KIZ or product barcode AND cargo-place bind,
   * then removes the order from the scanned list.
   */
  async function clearScannedOrderAll(mode, orderId) {
    if (state.saving || state.clearing) return;
    const id = String(orderId || "").trim();
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const row = findRowByScanId(rows, id);
    if (!row) return;
    const label = rowDisplayLabel(row);

    // WB: clear KIZ / pick locally (and queue WB clear when needed); no cargo place.
    if (!isOzon()) {
      if (mode === "kiz") {
        await clearKizCodes(id);
        return;
      }
      state.clearing = true;
      refreshSaveButton(mode);
      try {
        row.pick_verified = false;
        row.pick_barcode = "";
        removeSessionScanned(id);
        schedulePickLocalAutosave(id);
        setBanner(`Очищено · ${label} убран из просканированных`, "ok");
      } catch (e) {
        setBanner(e.message || String(e), "err");
      } finally {
        state.clearing = false;
        refreshScanChrome(mode);
      }
      return;
    }

    const postingNumber = String(row.posting_number || id).trim();
    const prevCid = Number(row.container_id || 0) || 0;
    const hadGm =
      prevCid > 0 || !!String(row.container_barcode || "").trim();

    state.clearing = true;
    refreshSaveButton(mode);
    try {
      if (mode === "kiz") {
        if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [""];
        row.kiz_codes = [""];
        row.kiz_local = true;
        delete state.pendingKizClear[id];
        if (state.rowErrors[id]) delete state.rowErrors[id];
        if (String(row.kiz_status || "") === "error") row.kiz_status = "empty";
        scheduleKizLocalAutosave(id);
      } else {
        row.pick_verified = false;
        row.pick_barcode = "";
        schedulePickLocalAutosave(id);
      }

      if (hadGm) {
        try {
          await unbindGmPosting(postingNumber, prevCid || null);
          clearRowGmLocal(row);
        } catch (e) {
          row.container_sync_error = String(e.message || e);
          setBanner(
            `Данные очищены · ГМ снять не удалось: ${row.container_sync_error}`,
            "warn"
          );
          removeSessionScanned(id);
          refreshScanChrome(mode);
          return;
        }
      }

      removeSessionScanned(id);
      setBanner(`Очищено · ${label} убран из просканированных`, "ok");
    } catch (e) {
      setBanner(e.message || String(e), "err");
    } finally {
      state.clearing = false;
      refreshScanChrome(mode);
    }
  }

  async function clearKizCodes(orderId) {
    if (state.saving || state.clearing) return;
    const id = String(orderId || "").trim();
    const row = findRowByScanId(state.kizRows, id);
    if (!row) return;
    if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [""];
    const hadCodes = rowKizFilled(row);
    const wasBound = !!row.kiz_bound;
    const hadLocal = !!row.kiz_local || hadCodes;
    const needsWbClear =
      !isOzon() &&
      (wasBound || (hadLocal && row.kiz_wb_synced === false) || !!state.pendingKizClear[id]);
    const label = rowDisplayLabel(row);

    if (!hadCodes) {
      removeSessionScanned(id);
      if (needsWbClear) {
        state.pendingKizClear[id] = true;
        row.kiz_bound = wasBound || !!row.kiz_bound;
        row.kiz_local = hadLocal || !!row.kiz_local;
        setBanner(
          `${label} убран из списка — нажмите «Сохранить», чтобы очистить КИЗ на WB`,
          "ok"
        );
      } else {
        delete state.pendingKizClear[id];
        setBanner(`${label} убран из просканированных`, "ok");
      }
      refreshScanChrome("kiz");
      return;
    }

    state.clearing = true;
    refreshSaveButton("kiz");
    try {
      row.kiz_codes = [""];
      if (wasBound || hadLocal || needsWbClear) {
        state.pendingKizClear[id] = true;
        row.kiz_bound = wasBound;
        row.kiz_local = hadLocal;
      } else {
        delete state.pendingKizClear[id];
      }
      removeSessionScanned(id);
      scheduleKizLocalAutosave(id);
      if (state.rowErrors[id]) delete state.rowErrors[id];
      if (String(row.kiz_status || "") === "error") row.kiz_status = "empty";
      setBanner(
        state.pendingKizClear[id]
          ? `КИЗ очищен · ${label} убран из списка — нажмите «Сохранить», чтобы очистить на WB`
          : `КИЗ очищен · ${label}`,
        "ok"
      );
    } catch (e) {
      setBanner(e.message || String(e), "err");
    } finally {
      state.clearing = false;
      refreshScanChrome("kiz");
    }
  }

  function syncSourceSelectVisibility() {
    const sel = document.getElementById("tsdSourceSelect");
    if (!sel) return;
    // Source picker only on the assembly supplies list — not inside a supply / scan.
    const show = !!boot.can_view_wb_fbs_tsd && state.route.view === "list";
    sel.hidden = !show;
    sel.setAttribute("aria-hidden", show ? "false" : "true");
  }

  function syncSearchChrome() {
    const btn = document.getElementById("tsdSearchBtn");
    const panel = document.getElementById("tsdSearchPanel");
    const input = document.getElementById("tsdOrderSearch");
    const filterWrap = document.getElementById("tsdFilterWrap");
    const filterBtn = document.getElementById("tsdFilterBtn");
    const filterMenu = document.getElementById("tsdFilterMenu");
    const errorsLabel = document.getElementById("tsdFilterErrorsLabel");
    const view = state.route.view;
    const onList = !!boot.can_view_wb_fbs_tsd && view === "list";
    const onScan = !!boot.can_view_wb_fbs_tsd && view === "scan";
    const searchOk = onList || onScan;
    const mode = state.route.mode;

    // Standalone search icon only on supply list; on scan search lives in Filters.
    if (btn) {
      btn.hidden = !onList;
      btn.setAttribute("aria-expanded", state.searchOpen && onList ? "true" : "false");
      btn.classList.toggle("is-active", !!(state.searchOpen && onList));
      btn.setAttribute("aria-label", "Поиск поставок");
      btn.title = "Поиск поставок";
    }
    if (filterWrap) filterWrap.hidden = !onScan;

    wireSaveButton();

    const saveBtn = document.getElementById("tsdSaveBtn");
    if (saveBtn) saveBtn.hidden = !onScan;
    if (onScan) refreshSaveButton(mode);
    else if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.classList.remove("is-busy");
    }

    if (!searchOk) {
      state.searchOpen = false;
      if (panel) panel.hidden = true;
    } else if (panel) {
      panel.hidden = !state.searchOpen;
    }

    if (!onScan) {
      state.filterOpen = false;
      state.orderSearch = "";
      state.filters = { filled: false, empty: false, errors: false, cancelled: false };
      state.browseOpen = false;
      state.browseLimit = BROWSE_PAGE_SIZE;
      const sheet = document.getElementById("tsdBrowseSheet");
      if (sheet) sheet.remove();
      if (filterMenu) filterMenu.hidden = true;
      if (filterBtn) {
        filterBtn.setAttribute("aria-expanded", "false");
        filterBtn.classList.remove("is-active");
      }
      syncFilterInputsFromState();
    }

    if (!onList) {
      state.search = "";
    }

    if (input) {
      if (onList) {
        input.placeholder = "Поиск поставки…";
        if (state.searchOpen) {
          const want = state.search || "";
          if (String(input.value || "") !== want) input.value = want;
        } else {
          input.value = "";
        }
      } else if (onScan) {
        input.placeholder = "Стикер, заказ, ШК, артикул, название…";
        if (state.searchOpen) {
          const want = state.orderSearch || "";
          if (String(input.value || "") !== want) input.value = want;
        } else {
          input.value = "";
        }
      } else {
        input.value = "";
      }
    }

    // Full-screen browse sheet has its own search field — hide header search panel.
    if (panel && onScan && state.searchOpen && shouldShowBrowseSheet()) {
      panel.hidden = true;
    }

    if (onScan) {
      if (errorsLabel) errorsLabel.hidden = mode !== "kiz";
      if (mode !== "kiz" && state.filters.errors) state.filters.errors = false;
      const noGmLabel = document.getElementById("tsdFilterNoGmLabel");
      const showNoGm = gmFilterAvailable();
      if (noGmLabel) noGmLabel.hidden = !showNoGm;
      if (!showNoGm && state.filters.noGm) state.filters.noGm = false;
      if (filterBtn) {
        filterBtn.setAttribute("aria-expanded", state.filterOpen ? "true" : "false");
        filterBtn.classList.toggle(
          "is-active",
          state.filterOpen || hasActiveFilters() || !!state.searchOpen
        );
      }
      if (filterMenu) filterMenu.hidden = !state.filterOpen;
      syncFilterInputsFromState();
    }

    const app = document.getElementById("tsdApp");
    if (app) {
      app.classList.toggle("is-scan", onScan);
      app.classList.toggle("is-filter-menu-open", !!(onScan && state.filterOpen));
      app.classList.toggle("is-browse-open", !!(onScan && shouldShowBrowseSheet()));
    }
  }

  function syncFilterInputsFromState() {
    const filled = document.getElementById("tsdFilterFilled");
    const empty = document.getElementById("tsdFilterEmpty");
    const errors = document.getElementById("tsdFilterErrors");
    const cancelled = document.getElementById("tsdFilterCancelled");
    const noGm = document.getElementById("tsdFilterNoGm");
    if (filled) filled.checked = !!state.filters.filled;
    if (empty) empty.checked = !!state.filters.empty;
    if (errors) errors.checked = !!state.filters.errors;
    if (cancelled) cancelled.checked = !!state.filters.cancelled;
    if (noGm) noGm.checked = !!state.filters.noGm;
  }

  const BROWSE_PAGE_SIZE = 40;

  function hasActiveFilters() {
    const f = state.filters || {};
    return !!(f.filled || f.empty || f.errors || f.cancelled || f.noGm);
  }

  function shouldShowBrowseSheet() {
    if (state.route.view !== "scan") return false;
    if (!state.browseOpen) return false;
    return hasActiveFilters() || state.searchOpen;
  }

  function openBrowseSheet(opts) {
    const resetLimit = !(opts && opts.keepLimit);
    if (resetLimit) state.browseLimit = BROWSE_PAGE_SIZE;
    state.browseOpen = true;
  }

  function closeBrowseSheet() {
    state.browseOpen = false;
  }

  function clearScanFiltersAndBrowse() {
    state.filters = {
      filled: false,
      empty: false,
      errors: false,
      cancelled: false,
      noGm: false,
    };
    state.filterOpen = false;
    closeBrowseSheet();
    syncSearchChrome();
  }

  function matchedBrowseRows(mode) {
    const q = String(state.orderSearch || "").trim();
    const filtersOn = hasActiveFilters();
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    let matched = rows || [];
    if (q) matched = filterOrdersBySearch(matched, q);
    else if (!filtersOn) matched = [];
    matched = applyOrderFilters(matched, mode);
    return matched;
  }

  function filterSummaryLabel() {
    const f = state.filters || {};
    const parts = [];
    if (f.filled) parts.push("заполненные");
    if (f.empty) parts.push("незаполненные");
    if (f.errors) parts.push("с ошибками");
    if (f.cancelled) parts.push("отменённые");
    if (f.noGm) parts.push("без ГМ");
    return parts.join(", ");
  }

  function renderBrowseSheetHtml(mode) {
    if (!shouldShowBrowseSheet()) return "";
    const q = String(state.orderSearch || "").trim();
    const filtersOn = hasActiveFilters();
    const matched = matchedBrowseRows(mode);
    const limit = Math.max(BROWSE_PAGE_SIZE, Number(state.browseLimit) || BROWSE_PAGE_SIZE);
    const shown = matched.slice(0, limit);
    const hasMore = matched.length > shown.length;
    const title = q
      ? `Найдено · ${matched.length}`
      : filtersOn
        ? `Фильтр · ${matched.length}`
        : "Поиск";
    const sub = filtersOn && !q ? filterSummaryLabel() : "";
    let body;
    if (!q && !filtersOn) {
      body = `<div class="tsd-search-empty">Введите или отсканируйте стикер, номер заказа, ШК, артикул или название</div>`;
    } else if (!matched.length) {
      body = `<div class="tsd-search-empty">${
        filtersOn && !q ? "Нет заказов по выбранным фильтрам" : "Ничего не найдено"
      }</div>`;
    } else {
      const items = shown
        .map((r) => {
          const oid = esc(rowScanId(r));
          if (isOzon()) {
            // Exact same card as «Просканировано» (incl. clear ×); tap selects order.
            return renderOzonOrderCardHtml(r, mode, { selectable: true });
          }
          // Exact same card as scanned list for WB FBS.
          return renderWbOrderCardHtml(r, mode, { selectable: true });
        })
        .join("");
      body = `
        <div class="tsd-search-list tsd-scanned-list" id="tsdSearchList">${items}</div>
        ${
          hasMore
            ? `<button type="button" class="tsd-btn tsd-btn-secondary tsd-btn-block" id="tsdBrowseMore">
                Показать ещё · ${shown.length} из ${matched.length}
              </button>`
            : matched.length > BROWSE_PAGE_SIZE
              ? `<div class="tsd-browse-end">Показаны все ${matched.length}</div>`
              : ""
        }`;
    }
    return `
      <div class="tsd-browse-sheet" id="tsdBrowseSheet" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="tsd-browse-head">
          <div class="tsd-browse-head-text">
            <div class="tsd-browse-title">${esc(title)}</div>
            ${sub ? `<div class="tsd-browse-sub">${esc(sub)}</div>` : ""}
          </div>
          <div class="tsd-browse-actions">
            <button type="button" class="tsd-icon-btn tsd-browse-close" id="tsdBrowseClose"
              aria-label="Закрыть" title="Закрыть">×</button>
          </div>
        </div>
        ${
          state.searchOpen
            ? `<div class="tsd-browse-search">
                <div class="tsd-browse-search-row">
                  <input class="tsd-search-input" id="tsdBrowseSearchInput" type="search"
                    placeholder="Стикер, заказ, ШК, артикул, название…"
                    autocomplete="off" enterkeyhint="search"
                    value="${esc(String(state.orderSearch || ""))}" />
                  <button type="button" class="tsd-icon-btn tsd-browse-search-clear" id="tsdBrowseSearchClear"
                    aria-label="Очистить поиск" title="Очистить">×</button>
                </div>
              </div>`
            : ""
        }
        <div class="tsd-browse-body">${body}</div>
      </div>`;
  }

  function syncBrowseSheetPosition() {
    const sheet = document.getElementById("tsdBrowseSheet");
    if (!sheet) return;
    // Full-viewport overlay — flush to the top edge over «Маркировка».
    sheet.style.top = "0px";
    sheet.style.bottom = "0px";
  }

  function scheduleBrowseSheetPositionSync() {
    syncBrowseSheetPosition();
    requestAnimationFrame(() => {
      syncBrowseSheetPosition();
      requestAnimationFrame(syncBrowseSheetPosition);
    });
  }

  function dismissBrowseSheetToScan() {
    // × replaces «Сбросить» — clear filters and close the overlay.
    state.filters = { filled: false, empty: false, errors: false, cancelled: false };
    state.filterOpen = false;
    closeBrowseSheet();
    if (state.searchOpen) {
      state.searchOpen = false;
      state.orderSearch = "";
      const input = document.getElementById("tsdOrderSearch");
      if (input) input.value = "";
    }
    syncSearchChrome();
    renderScan();
  }

  function wireBrowseSheet() {
    const sheet = document.getElementById("tsdBrowseSheet");
    if (!sheet) return;
    scheduleBrowseSheetPositionSync();
    const closeBtn = document.getElementById("tsdBrowseClose");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => dismissBrowseSheetToScan());
    }
    const more = document.getElementById("tsdBrowseMore");
    if (more) {
      more.addEventListener("click", () => {
        state.browseLimit = (Number(state.browseLimit) || BROWSE_PAGE_SIZE) + BROWSE_PAGE_SIZE;
        openBrowseSheet({ keepLimit: true });
        renderScan({ keepSearchFocus: true });
      });
    }
    const searchList = document.getElementById("tsdSearchList");
    if (searchList) {
      const pickFromTarget = (target) => {
        const clearBtn =
          target && target.closest
            ? target.closest("[data-action='clear-scanned-all']")
            : null;
        if (clearBtn) return { clearBtn };
        const btn =
          target && target.closest
            ? target.closest("[data-action='pick-search-order']")
            : null;
        return btn ? { pickBtn: btn } : null;
      };
      searchList.addEventListener("click", (ev) => {
        const hit = pickFromTarget(ev.target);
        if (!hit) return;
        if (hit.clearBtn) {
          ev.preventDefault();
          ev.stopPropagation();
          const mode = state.route.mode;
          clearScannedOrderAll(mode, hit.clearBtn.getAttribute("data-order-id"));
          return;
        }
        ev.preventDefault();
        selectOrderFromSearch(hit.pickBtn.getAttribute("data-order-id"));
      });
      searchList.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        const card =
          ev.target && ev.target.closest
            ? ev.target.closest(".tsd-scanned-item.is-selectable[data-action='pick-search-order']")
            : null;
        if (!card || card !== ev.target) return;
        ev.preventDefault();
        selectOrderFromSearch(card.getAttribute("data-order-id"));
      });
    }
    const browseSearch = document.getElementById("tsdBrowseSearchInput");
    const browseSearchClear = document.getElementById("tsdBrowseSearchClear");
    if (browseSearchClear) {
      browseSearchClear.addEventListener("click", (ev) => {
        ev.preventDefault();
        state.orderSearch = "";
        if (browseSearch) browseSearch.value = "";
        const headerInput = document.getElementById("tsdOrderSearch");
        if (headerInput) headerInput.value = "";
        refreshSearchResultsOnly();
        if (browseSearch) {
          setTimeout(() => browseSearch.focus(), 20);
        }
      });
    }
    if (browseSearch) {
      browseSearch.addEventListener("input", () => {
        state.orderSearch = String(browseSearch.value || "");
        const headerInput = document.getElementById("tsdOrderSearch");
        if (headerInput && String(headerInput.value || "") !== state.orderSearch) {
          headerInput.value = state.orderSearch;
        }
        refreshSearchResultsOnly();
      });
      browseSearch.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") {
          ev.preventDefault();
          dismissBrowseSheetToScan();
          return;
        }
        if (ev.key === "Enter") {
          ev.preventDefault();
          applyOrderSearchEnter();
        }
      });
      if (state.searchOpen) {
        setTimeout(() => {
          const el = document.getElementById("tsdBrowseSearchInput");
          if (el) {
            el.focus();
            el.select();
          }
        }, 40);
      }
    }
  }

  function renderSearchResultsHtml(_mode) {
    // Results live in the fixed browse sheet — never inline above the scan field.
    return "";
  }

  function refreshSearchResultsOnly() {
    if (state.route.view !== "scan") return;
    if (state.searchOpen || hasActiveFilters()) openBrowseSheet({ keepLimit: true });
    renderScan({ keepSearchFocus: true });
  }

  function rowHasKizError(row) {
    const oid = Number(row && row.order_id);
    if (oid && state.rowErrors[oid]) return true;
    return String((row && row.kiz_status) || "") === "error";
  }

  function rowIsCancelled(row) {
    return !!String((row && row.cancel_reason_label) || "").trim();
  }

  function applyOrderFilters(rows, mode) {
    let out = Array.isArray(rows) ? rows.slice() : [];
    const f = state.filters || {};
    if (f.filled) {
      out = out.filter((r) => (mode === "kiz" ? rowKizFilled(r) : rowPickFilled(r)));
    }
    if (f.empty) {
      out = out.filter((r) => (mode === "kiz" ? !rowKizFilled(r) : !rowPickFilled(r)));
    }
    if (f.errors && mode === "kiz") {
      out = out.filter((r) => rowHasKizError(r));
    }
    if (f.cancelled) {
      out = out.filter((r) => rowIsCancelled(r));
    }
    if (f.noGm && isOzon()) {
      out = out.filter((r) => !(Number(r?.container_id || 0) > 0));
    }
    return out;
  }

  function resetScanFilters() {
    state.filterOpen = false;
    state.filters = {
      filled: false,
      empty: false,
      errors: false,
      cancelled: false,
      noGm: false,
    };
    closeBrowseSheet();
  }

  function openHeaderSearch() {
    const view = state.route.view;
    if (view !== "list" && view !== "scan") return;
    if (view === "scan") clearBanner();
    state.searchOpen = true;
    if (view === "scan") openBrowseSheet();
    syncSearchChrome();
    if (view === "list") {
      const input = document.getElementById("tsdOrderSearch");
      if (input) {
        setTimeout(() => {
          input.focus();
          input.select();
        }, 40);
      }
    }
    if (view === "scan") {
      renderScan({ keepSearchFocus: true });
      scheduleBrowseSheetPositionSync();
    }
  }

  function closeHeaderSearch() {
    const view = state.route.view;
    const hadListSearch = view === "list" && !!String(state.search || "").trim();
    state.searchOpen = false;
    if (view === "list") state.search = "";
    if (view === "scan") {
      state.orderSearch = "";
      if (!hasActiveFilters()) closeBrowseSheet();
    }
    syncSearchChrome();
    const input = document.getElementById("tsdOrderSearch");
    if (input) input.value = "";
    if (view === "scan") {
      renderScan();
      return;
    }
    if (view === "list" && hadListSearch) {
      loadSupplies()
        .then(() => renderList())
        .catch((e) => toast(e.message || e));
    }
  }

  function openOrderSearch() {
    openHeaderSearch();
  }

  function closeOrderSearch() {
    closeHeaderSearch();
  }

  function closeFilterMenu() {
    if (!state.filterOpen) return;
    state.filterOpen = false;
    syncSearchChrome();
  }

  function toggleFilterMenu() {
    if (state.route.view !== "scan") return;
    // If filters already active and sheet closed — reopen results (not the dropdown).
    if (hasActiveFilters() && !state.browseOpen && !state.filterOpen) {
      openBrowseSheet();
      state.filterOpen = false;
      syncSearchChrome();
      renderScan({ keepSearchFocus: true });
      scheduleBrowseSheetPositionSync();
      return;
    }
    state.filterOpen = !state.filterOpen;
    syncSearchChrome();
    scheduleBrowseSheetPositionSync();
  }

  function onFilterChange(kind) {
    if (state.route.view === "scan") clearBanner();
    const filled = document.getElementById("tsdFilterFilled");
    const empty = document.getElementById("tsdFilterEmpty");
    const errors = document.getElementById("tsdFilterErrors");
    const cancelled = document.getElementById("tsdFilterCancelled");
    const noGm = document.getElementById("tsdFilterNoGm");
    if (kind === "filled" && filled?.checked && empty) empty.checked = false;
    if (kind === "empty" && empty?.checked && filled) filled.checked = false;
    state.filters = {
      filled: !!filled?.checked,
      empty: !!empty?.checked,
      errors: state.route.mode === "kiz" ? !!errors?.checked : false,
      cancelled: !!cancelled?.checked,
      noGm: isOzon() && gmFilterAvailable() ? !!noGm?.checked : false,
    };
    if (hasActiveFilters()) {
      openBrowseSheet();
      // Close dropdown so the full-screen filter sheet is not trapped under the header.
      state.filterOpen = false;
    } else if (!state.searchOpen) {
      closeBrowseSheet();
    }
    syncSearchChrome();
    if (state.route.view === "scan") {
      renderScan({ keepSearchFocus: true });
      scheduleBrowseSheetPositionSync();
    }
  }

  function orderSearchHaystack(row) {
    const parts = [
      row.order_id,
      row.posting_number,
      row.order_number,
      row.sticker_number,
      row.sticker_barcode,
      row.sticker_lower_barcode,
      row.sticker_part_a,
      row.sticker_part_b,
      row.product_name,
      row.offer_id,
      row.article,
      row.brand,
      row.pick_barcode,
      row.nm_id,
    ];
    const barcodes = Array.isArray(row.barcodes) ? row.barcodes : [];
    const skus = Array.isArray(row.skus) ? row.skus : [];
    const kiz = Array.isArray(row.kiz_codes) ? row.kiz_codes : [];
    for (const x of barcodes.concat(skus).concat(kiz)) parts.push(x);
    return parts
      .map((x) => String(x || "").trim().toLocaleLowerCase("ru-RU"))
      .filter(Boolean)
      .join("\n");
  }

  function filterOrdersBySearch(rows, query) {
    let q = String(query || "").trim();
    if (!q) return Array.isArray(rows) ? rows.slice() : [];
    if (hasCyrillic(q)) {
      const mapped = fixRuKeyboardLayout(q);
      if (!hasCyrillic(mapped)) q = mapped;
    }
    const needle = q.toLocaleLowerCase("ru-RU");
    const digits = digitsOnly(q);
    return (rows || []).filter((row) => {
      const hay = orderSearchHaystack(row);
      if (hay.includes(needle)) return true;
      if (digits && digits.length >= 3) {
        if (String(row.order_id || "").includes(digits)) return true;
        if (hay.replace(/\D+/g, "").includes(digits)) return true;
      }
      return false;
    });
  }

  function selectOrderFromSearch(orderId) {
    const mode = state.route.mode;
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const row = findRowByScanId(rows, orderId);
    if (!row) {
      setBanner(isOzon() ? "Отправление не найдено" : "Заказ не найден", "err");
      return;
    }
    state.pendingOrderId = rowScanId(row);
    state.step = mode === "kiz" ? "mark" : "sku";
    state.searchOpen = false;
    state.orderSearch = "";
    closeBrowseSheet();
    closeFilterMenu();
    syncSearchChrome();
    const input = document.getElementById("tsdOrderSearch");
    if (input) input.value = "";
    setBanner(null);
    beep(true);
    renderScan();
    scrollToScanInput();
  }

  function applyOrderSearchEnter() {
    if (state.route.view !== "scan" || !state.searchOpen) return;
    const mode = state.route.mode;
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    let raw = String(state.orderSearch || "").trim();
    if (!raw) return;
    if (hasCyrillic(raw)) {
      const mapped = fixRuKeyboardLayout(raw);
      if (hasCyrillic(mapped)) {
        setBanner("Русская раскладка — переключите на EN", "warn");
        beep(false);
        return;
      }
      raw = mapped;
      state.orderSearch = mapped;
      const input = document.getElementById("tsdOrderSearch");
      if (input) input.value = mapped;
    }
    const found = findBySticker(rows, raw);
    if (found.ambiguous) {
      setBanner("Стикер совпал у нескольких заказов — уточните поиск", "err");
      beep(false);
      refreshSearchResultsOnly();
      return;
    }
    if (found.row) {
      selectOrderFromSearch(rowScanId(found.row));
      return;
    }
    const matched = filterOrdersBySearch(rows, raw);
    if (matched.length === 1) {
      selectOrderFromSearch(rowScanId(matched[0]));
      return;
    }
    if (!matched.length) {
      setBanner("Ничего не найдено", "err");
      beep(false);
      refreshSearchResultsOnly();
      return;
    }
    // Several matches — keep the list for a tap.
    setBanner(`Найдено ${matched.length} — выберите заказ`, "info");
    beep(true);
    refreshSearchResultsOnly();
  }

  function scrollToScanInput() {
    const target =
      document.getElementById("tsdScanInput") ||
      document.querySelector(".tsd-scan-card") ||
      document.getElementById("tsdMain");
    if (!target) {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const top = Math.max(0, target.getBoundingClientRect().top + window.scrollY - 72);
    window.scrollTo({ top, behavior: "smooth" });
    const input = document.getElementById("tsdScanInput");
    if (input) setTimeout(() => input.focus(), 280);
  }

  function syncScrollTopFab() {
    const fab = document.getElementById("tsdScrollTop");
    if (!fab) return;
    const onScan = state.route.view === "scan";
    const show = onScan && window.scrollY > 160;
    fab.hidden = !show;
  }

  function renderDenied() {
    const main = document.getElementById("tsdMain");
    syncSourceSelectVisibility();
    syncSearchChrome();
    syncScrollTopFab();
    const back = document.getElementById("tsdBackBtn");
    if (back) {
      back.hidden = false;
      back.href = "/app";
      back.textContent = "←";
    }
    document.getElementById("tsdTitle").textContent = "ТСД";
    main.innerHTML = `
      <div class="tsd-denied">
        <h1>Нет доступа</h1>
        <p>Раздел ТСД не разрешён для вашей учётной записи. Попросите владельца включить право «ТСД» в Команде.</p>
        <a class="tsd-btn tsd-btn-primary" href="/app">В кабинет</a>
      </div>`;
  }

  function renderList() {
    const main = document.getElementById("tsdMain");
    const back = document.getElementById("tsdBackBtn");
    const title = document.getElementById("tsdTitle");
    const prog = document.getElementById("tsdProgressBar");
    syncSourceSelectVisibility();
    syncSearchChrome();
    syncScrollTopFab();
    if (prog) prog.hidden = true;
    // Start screen is the TSD entry point — no back to web /app.
    if (back) {
      back.hidden = true;
      back.onclick = null;
      back.removeAttribute("href");
    }
    title.textContent = "ТСД";

    if (!state.sources.length) {
      main.innerHTML = `<div class="tsd-empty">Нет доступных кабинетов FBS для ТСД</div>`;
      return;
    }
    if (!state.supplies.length) {
      main.innerHTML = `<div class="tsd-empty">${
        state.search
          ? "Ничего не найдено"
          : isOzon()
            ? "Нет поставок «Ожидают отгрузки»"
            : "Нет поставок на сборке"
      }</div>`;
      return;
    }
    main.innerHTML = `
      <div class="tsd-list">
        ${state.supplies
          .map((s) => {
            const sid = String(s.supply_id || "");
            return `
            <button type="button" class="tsd-card" data-open-supply="${esc(sid)}">
              <div class="tsd-card-name">${esc(s.name || sid)}</div>
              <div class="tsd-card-meta">
                <div>QR: <strong>${esc(sid)}</strong></div>
                <div>${esc(ordersBoxesText(s))}</div>
                <div>Склад: <strong>${esc(s.warehouse_label || "—")}</strong></div>
              </div>
            </button>`;
          })
          .join("")}
      </div>`;
    main.querySelectorAll("[data-open-supply]").forEach((btn) => {
      btn.addEventListener("click", () => {
        navigate(`#/s/${btn.getAttribute("data-open-supply")}`);
      });
    });
  }

  let listSearchTimer = null;

  async function applyListSearchFromHeader() {
    if (state.route.view !== "list") return;
    try {
      await loadSupplies();
      if (state.route.view !== "list") return;
      renderList();
      const input = document.getElementById("tsdOrderSearch");
      if (input && state.searchOpen) {
        input.focus();
        const v = input.value;
        input.setSelectionRange(v.length, v.length);
      }
    } catch (e) {
      toast(e.message || e);
    }
  }

  function setKizHubTone(tone) {
    const t = String(tone || "").trim().toLowerCase();
    state.kizHubTone = t === "ok" || t === "error" ? t : "";
    const split = document.getElementById("tsdKizSplit");
    if (!split) return;
    split.classList.remove("is-ok", "is-error");
    if (state.kizHubTone === "ok") split.classList.add("is-ok");
    else if (state.kizHubTone === "error") split.classList.add("is-error");
  }

  function setPickHubTone(tone) {
    const t = String(tone || "").trim().toLowerCase();
    // Pick refresh: green only — never red (unlike КИЗ tile).
    state.pickHubTone = t === "ok" ? "ok" : "";
    const split = document.getElementById("tsdPickSplit");
    if (!split) return;
    split.classList.remove("is-ok", "is-error");
    if (state.pickHubTone === "ok") split.classList.add("is-ok");
  }

  async function refreshHubPickStatus(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    const sid = String(state.route.supplyId || (state.supply && state.supply.supply_id) || "").trim();
    if (!sid || !state.sourceId || state.pickStatusRefreshing) return;
    const refreshBtn = document.getElementById("tsdPickRefreshBtn");
    const pickBtn = document.getElementById("tsdTilePick");
    state.pickStatusRefreshing = true;
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.classList.add("is-spinning");
    }
    if (pickBtn) pickBtn.disabled = true;
    try {
      const params = new URLSearchParams({ source_id: String(state.sourceId) });
      const data = await api(
        `/api/wb-fbs/tsd/supplies/${encodeURIComponent(sid)}/pick-verify/status?${params}`
      );
      if (String(state.route.supplyId || "") !== sid || state.route.view !== "hub") return;
      state.pickHubToneSupplyId = sid;
      const st = String(data.status || "").trim().toLowerCase();
      if (st === "ok") {
        setPickHubTone("ok");
      } else {
        setPickHubTone("");
      }
    } catch (e) {
      if (String(state.route.supplyId || "") === sid && state.route.view === "hub") {
        toast(e.message || String(e));
      }
    } finally {
      state.pickStatusRefreshing = false;
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.classList.remove("is-spinning");
      }
      if (pickBtn) {
        const s = state.supply || {};
        const pick = s.pick || { total: 0 };
        const pickError = String(s.pick_error || "").trim();
        const pickDisabled = !pick.total && !pickError;
        pickBtn.disabled = pickDisabled || state.pickStatusRefreshing;
      }
    }
  }

  async function refreshHubKizStatus(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    const sid = String(state.route.supplyId || (state.supply && state.supply.supply_id) || "").trim();
    if (!sid || !state.sourceId || state.kizStatusRefreshing) return;
    const refreshBtn = document.getElementById("tsdKizRefreshBtn");
    const kizBtn = document.getElementById("tsdTileKiz");
    state.kizStatusRefreshing = true;
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.classList.add("is-spinning");
    }
    if (kizBtn) kizBtn.disabled = true;
    try {
      const params = new URLSearchParams({ source_id: String(state.sourceId) });
      const data = await api(
        `/api/wb-fbs/tsd/supplies/${encodeURIComponent(sid)}/kiz/status?${params}`
      );
      if (String(state.route.supplyId || "") !== sid || state.route.view !== "hub") return;
      state.kizHubToneSupplyId = sid;
      setKizHubTone(data.status);
    } catch (e) {
      if (String(state.route.supplyId || "") === sid && state.route.view === "hub") {
        toast(e.message || String(e));
      }
    } finally {
      state.kizStatusRefreshing = false;
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.classList.remove("is-spinning");
      }
      if (kizBtn) {
        const s = state.supply || {};
        const kiz = s.kiz || { total: 0 };
        const kizError = String(s.kiz_error || "").trim();
        const kizDisabled = !kiz.total && !kizError;
        kizBtn.disabled = kizDisabled || state.kizStatusRefreshing;
      }
    }
  }

  function renderHub() {
    const s = state.supply || {};
    const sid = String(s.supply_id || state.route.supplyId || "");
    const main = document.getElementById("tsdMain");
    const back = document.getElementById("tsdBackBtn");
    const title = document.getElementById("tsdTitle");
    const prog = document.getElementById("tsdProgressBar");
    syncSourceSelectVisibility();
    syncSearchChrome();
    syncScrollTopFab();
    if (prog) prog.hidden = true;
    if (back) {
      back.hidden = false;
      back.href = "#/";
      back.onclick = (ev) => {
        ev.preventDefault();
        state.kizHubTone = "";
        state.kizHubToneSupplyId = "";
        state.pickHubTone = "";
        state.pickHubToneSupplyId = "";
        navigate("#/");
      };
      back.textContent = "←";
    }
    title.textContent = "Поставка";

    const kiz = s.kiz || { done: 0, total: 0 };
    const pick = s.pick || { done: 0, total: 0 };
    const kizError = String(s.kiz_error || "").trim();
    const pickError = String(s.pick_error || "").trim();
    const kizDisabled = !kiz.total && !kizError;
    const pickDisabled = !pick.total && !pickError;

    main.innerHTML = `
      <h1 class="tsd-hub-name">${esc(s.name || sid)}</h1>
      <div class="tsd-hub-meta">
        <div>QR: <strong>${esc(sid)}</strong></div>
        <div>${esc(ordersBoxesText(s))}</div>
        <div>Склад: <strong>${esc(s.warehouse_label || "—")}</strong></div>
      </div>
      ${
        kizError || pickError
          ? `<div class="tsd-banner is-err">${esc(
              [kizError && `КИЗ: ${kizError}`, pickError && `ШК: ${pickError}`]
                .filter(Boolean)
                .join(" · ")
            )}</div>`
          : ""
      }
      <div class="tsd-tiles">
        <div class="tsd-tile-split" id="tsdKizSplit">
          <button type="button" class="tsd-tile tsd-tile-main" id="tsdTileKiz" ${
            kizDisabled ? "disabled" : ""
          }>
            <span class="tsd-tile-title">Товары с маркировкой</span>
            <span class="tsd-tile-prog">${
              kizError
                ? "Ошибка загрузки"
                : kizDisabled
                  ? "Нет заказов"
                  : `${kiz.done} / ${kiz.total}`
            }</span>
          </button>
          <button type="button" class="tsd-tile-refresh" id="tsdKizRefreshBtn"
            ${kizDisabled ? "disabled" : ""}
            aria-label="Проверить статусы КИЗ на Wildberries"
            title="Проверить статусы КИЗ на ВБ">
            <svg class="tsd-tile-refresh-ico" width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M3 3v5h5"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M16 16h5v5"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
        <div class="tsd-tile-split" id="tsdPickSplit">
          <button type="button" class="tsd-tile tsd-tile-main" id="tsdTilePick" ${
            pickDisabled ? "disabled" : ""
          }>
            <span class="tsd-tile-title">Товары без маркировки</span>
            <span class="tsd-tile-prog">${
              pickError
                ? "Ошибка загрузки"
                : pickDisabled
                  ? "Нет заказов"
                  : `${pick.done} / ${pick.total}`
            }</span>
          </button>
          <button type="button" class="tsd-tile-refresh" id="tsdPickRefreshBtn"
            ${pickDisabled ? "disabled" : ""}
            aria-label="Обновить статусы проверки ШК"
            title="Обновить статусы проверки ШК">
            <svg class="tsd-tile-refresh-ico" width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M3 3v5h5"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M16 16h5v5"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </div>
      </div>`;

    setKizHubTone(state.kizHubTone);
    setPickHubTone(state.pickHubTone);

    const kizBtn = document.getElementById("tsdTileKiz");
    const pickBtn = document.getElementById("tsdTilePick");
    const kizRefreshBtn = document.getElementById("tsdKizRefreshBtn");
    const pickRefreshBtn = document.getElementById("tsdPickRefreshBtn");
    if (kizBtn && !kizDisabled) {
      kizBtn.addEventListener("click", () => navigate(`#/s/${sid}/kiz`));
    }
    if (pickBtn && !pickDisabled) {
      pickBtn.addEventListener("click", () => navigate(`#/s/${sid}/pick`));
    }
    if (kizRefreshBtn && !kizDisabled) {
      kizRefreshBtn.addEventListener("click", (ev) => refreshHubKizStatus(ev));
    }
    if (pickRefreshBtn && !pickDisabled) {
      pickRefreshBtn.addEventListener("click", (ev) => refreshHubPickStatus(ev));
    }
  }

  function remainingRows(mode) {
    if (mode === "kiz") return state.kizRows.filter((r) => !rowKizFilled(r));
    return state.pickRows.filter((r) => !rowPickFilled(r));
  }

  function updateProgressBar(mode) {
    const prog = document.getElementById("tsdProgressBar");
    const fill = document.getElementById("tsdProgressFill");
    if (!prog || !fill) return;
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const fn = mode === "kiz" ? rowKizFilled : rowPickFilled;
    const { total, done } = countProgress(rows, fn);
    // Keep hidden: the 4px --tsd-line track looked like a leftover divider above
    // Готово/Осталось. Progress is already shown in .tsd-stats.
    prog.hidden = true;
    fill.style.width = total ? `${Math.round((100 * done) / total)}%` : "0%";
  }

  function hasUnsavedScanWork(mode) {
    const m = mode || state.route.mode;
    // Mid-scan step (sticker matched, waiting for КИЗ/ШК).
    if (state.pendingOrderId) return true;
    const session = state.sessionScannedIds || [];
    if (!session.length) {
      if (m === "kiz" && Object.keys(state.pendingKizClear || {}).length) return true;
      return false;
    }
    const sessionSet = new Set(session.map((x) => String(x)));
    if (m === "kiz") {
      return (state.kizRows || []).some((row) => {
        const id = rowScanId(row);
        if (!sessionSet.has(id)) return false;
        if (isOzon()) {
          const codes = normalizeKizCodesList(row.kiz_codes);
          return rowKizFilled(row) || !kizBaselineEquals(id, codes);
        }
        return rowNeedsKizWbClear(row) || rowKizFilled(row);
      });
    }
    return (state.pickRows || []).some(
      (row) => sessionSet.has(rowScanId(row)) && rowPickFilled(row)
    );
  }

  /** Back arrow: always save (no confirm), then leave. Stay on error/conflict. */
  async function leaveScanScreen() {
    if (state.route.view !== "scan") return;
    const sid = state.route.supplyId;
    const mode = state.route.mode;
    const shouldSave =
      mode === "kiz"
        ? hasPendingKizPush()
        : orderedScannedRows(mode).length > 0;
    if (shouldSave) {
      const result =
        mode === "kiz"
          ? await saveKizPushAll({ silent: true })
          : await savePickLocalAll({ silent: true });
      // conflict/error: stay — server (PC) data already adopted into the UI.
      if (
        result &&
        (result.status === "error" ||
          result.status === "conflict" ||
          result.status === "busy")
      ) {
        return;
      }
    } else {
      await awaitLocalAutosaves();
    }
    if (state.route.view !== "scan") return;
    state.pendingOrderId = null;
    state.step = "sticker";
    state.searchOpen = false;
    state.orderSearch = "";
    state.sessionScannedIds = [];
    resetScanFilters();
    // Keep active GM within the same supply (kiz ↔ hub ↔ pick). Clear awaiting only.
    closeGmRebind(false);
    state.gm.awaitingScan = false;
    setBanner(null);
    navigate(`#/s/${sid}`);
  }

  function scanProgress(mode) {
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const fn = mode === "kiz" ? rowKizFilled : rowPickFilled;
    return countProgress(rows, fn);
  }

  function buildScanCardHtml(mode) {
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const pending = findRowByScanId(rows, state.pendingOrderId);
    const step = state.step;
    if (!rows.length) {
      return `<div class="tsd-empty">Нет заказов в этом режиме</div>`;
    }
    if (isOzon() && state.gm.awaitingScan && gmUiVisible()) {
      return `
        <div class="tsd-scan-card" id="tsdScanCard">
          <div class="tsd-scan-step">Грузоместо</div>
          <p class="tsd-scan-prompt">Сканируйте QR грузоместа</p>
          ${scanFieldRowHtml()}
        </div>`;
    }
    if (step === "sticker" || !pending) {
      return `
        <div class="tsd-scan-card" id="tsdScanCard">
          <p class="tsd-scan-prompt">Сканируйте стикер заказа</p>
          ${scanFieldRowHtml()}
        </div>`;
    }
    const photo = pending.product_photo
      ? `<img src="${esc(pending.product_photo)}" alt="" width="64" height="64" />`
      : "";
    const existingKizN = mode === "kiz" ? filledKizEntries(pending).length : 0;
    const prompt =
      mode === "kiz"
        ? existingKizN
          ? `Сканируйте КИЗ ${existingKizN + 1}`
          : "Сканируйте КИЗ"
        : "Сканируйте штрихкод товара";
    const multiHint =
      mode === "kiz" && existingKizN
        ? `<p class="tsd-scan-subhint">У заказа уже ${existingKizN} КИЗ — новый код добавится к заказу</p>`
        : "";
    const pendingBarcodes = orderBarcodesLabel(pending);
    const pendingBarcodesHtml = pendingBarcodes
      ? `<div class="tsd-product-barcodes">${esc(pendingBarcodes)}</div>`
      : "";
    return `
        <div class="tsd-scan-card" id="tsdScanCard">
          <p class="tsd-scan-prompt">${prompt}</p>
          ${multiHint}
          <div class="tsd-scan-context">${isOzon() ? "Отпр." : "Заказ"} ${esc(rowDisplayLabel(pending))} · стикер ${esc(pending.sticker_number || pending.posting_number || "—")}</div>
          ${scanFieldRowHtml()}
          <div class="tsd-product">${photo}<div>
            <div class="tsd-product-name">${esc(pending.product_name || pending.article || "—")}</div>
            <div class="tsd-product-sub">${esc([pending.brand, pending.article].filter(Boolean).join(" · "))}</div>
            ${pendingBarcodesHtml}
          </div></div>
          <div class="tsd-scan-actions">
            <button type="button" class="tsd-btn tsd-btn-ghost tsd-btn-block" id="tsdCancelStep">Отмена шага</button>
          </div>
        </div>`;
  }

  function refreshScanBanner() {
    const shell = document.querySelector(".tsd-scan-shell");
    if (!shell) return;
    const banner = state.banner;
    let ban = shell.querySelector(".tsd-banner:not(.tsd-gm-load-err)");
    if (!banner) {
      if (ban) ban.remove();
      return;
    }
    if (!ban) {
      ban = document.createElement("div");
      const gmBar = document.getElementById("tsdGmBar");
      const stats = shell.querySelector(".tsd-stats");
      const anchor = gmBar || stats;
      if (anchor && anchor.nextSibling) shell.insertBefore(ban, anchor.nextSibling);
      else shell.insertBefore(ban, shell.children[1] || null);
    }
    const wrap = document.createElement("div");
    wrap.innerHTML = bannerHtml(banner);
    const next = wrap.firstElementChild;
    if (!next) return;
    ban.replaceWith(next);
    wireBannerDismiss(next);
  }

  function refreshScanStats(mode) {
    const shell = document.querySelector(".tsd-scan-shell");
    if (!shell) return false;
    const stats = shell.querySelector(".tsd-stats");
    if (!stats) return false;
    const { total, done, left } = scanProgress(mode);
    const gmN = isOzon() ? gmBoundCount(mode) : 0;
    const showGm = isOzon() && (gmUiVisible() || gmN > 0);
    stats.innerHTML = `
      <span>Готово ${done} / ${total}${
        showGm ? ` · В ГМ ${gmN}` : ""
      }</span>
      <span>Осталось ${left}</span>`;
    updateProgressBar(mode);
    return true;
  }

  function refreshScannedListSection(mode) {
    const shell = document.querySelector(".tsd-scan-shell");
    if (!shell) return false;
    const old = shell.querySelector(".tsd-scanned");
    const wrap = document.createElement("div");
    wrap.innerHTML = renderScannedListHtml(mode).trim();
    const next = wrap.firstElementChild;
    if (!next) return false;
    if (old) old.replaceWith(next);
    else shell.appendChild(next);
    wireScannedList(mode);
    return true;
  }

  function refreshSaveButton(mode) {
    const btn = document.getElementById("tsdSaveBtn");
    if (!btn) return;
    const onScan = state.route.view === "scan";
    btn.hidden = !onScan;
    const saveDisabled =
      !onScan ||
      state.saving ||
      state.clearing ||
      (mode === "kiz" ? !hasPendingKizPush() : !orderedScannedRows(mode).length);
    btn.disabled = saveDisabled;
    btn.classList.toggle("is-busy", !!state.saving);
    const label = state.saving ? "Сохранение…" : "Сохранить";
    btn.setAttribute("aria-label", label);
    btn.title = label;
  }

  function refreshScanChrome(mode) {
    refreshScanStats(mode);
    refreshGmBar();
    refreshScanBanner();
    refreshScannedListSection(mode);
    refreshSaveButton(mode);
    syncScrollTopFab();
    // Keep filter/search sheet in sync after clear × on browse cards.
    if (state.route.view === "scan" && shouldShowBrowseSheet()) {
      openBrowseSheet({ keepLimit: true });
    }
  }

  function wireScannedList(mode) {
    const scannedList = document.getElementById("tsdScannedList");
    if (!scannedList) return;
    scannedList.addEventListener("click", (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-action]") : null;
      if (!btn) return;
      const action = btn.getAttribute("data-action");
      const oid = btn.getAttribute("data-order-id");
      if (action === "clear-scanned-all") {
        ev.preventDefault();
        clearScannedOrderAll(mode, oid);
      }
    });
  }

  function wireScanInput(mode, opts) {
    const keepSearchFocus = !!(opts && opts.keepSearchFocus);
    const input = document.getElementById("tsdScanInput");
    const clearBtn = document.getElementById("tsdScanClear");
    const syncScanClearBtn = () => {
      if (!clearBtn || !input) return;
      clearBtn.hidden = !String(input.value || "").length;
    };
    if (input && !keepSearchFocus && !state.searchOpen && !shouldShowBrowseSheet()) {
      setTimeout(() => input.focus(), 40);
    }
    if (input) {
      syncScanClearBtn();
      input.addEventListener("keydown", (ev) => {
        if (state.step === "mark" && mode === "kiz" && isGsKeyEvent(ev)) {
          ev.preventDefault();
          insertGsIntoInput(input);
          return;
        }
        if (ev.key === "Enter") {
          ev.preventDefault();
          onScanEnter(input);
        }
      });
      input.addEventListener("input", () => {
        syncScanClearBtn();
        if (hasCyrillic(input.value)) {
          const el = document.querySelector(".tsd-banner");
          if (!el) {
            const shell = document.querySelector(".tsd-scan-shell");
            if (shell) {
              const ban = document.createElement("div");
              ban.className = "tsd-banner is-warn";
              ban.textContent =
                "Русская раскладка — переключите на EN (или сканируйте ещё раз)";
              shell.insertBefore(ban, shell.children[1] || null);
            }
          }
        }
      });
    }
    if (clearBtn && input) {
      clearBtn.addEventListener("click", () => {
        input.value = "";
        syncScanClearBtn();
        input.focus();
      });
    }
    const cancel = document.getElementById("tsdCancelStep");
    if (cancel) {
      cancel.addEventListener("click", () => {
        state.pendingOrderId = null;
        state.step = "sticker";
        setBanner(null);
        if (!patchScanCard(mode)) renderScan();
        else refreshScanChrome(mode);
      });
    }
  }

  function wireScanFooter(mode) {
    wireScannedList(mode);
  }

  function wireSaveButton() {
    const saveBtn = document.getElementById("tsdSaveBtn");
    if (!saveBtn || saveBtn.dataset.wired === "1") return;
    saveBtn.dataset.wired = "1";
    saveBtn.addEventListener("click", () => {
      if (state.route.view !== "scan") return;
      const mode = state.route.mode;
      if (mode === "kiz") saveKizPushAll();
      else savePickLocalAll();
    });
  }

  function patchScanCard(mode) {
    const shell = document.querySelector(".tsd-scan-shell");
    if (!shell) return false;
    const html = buildScanCardHtml(mode);
    const card = document.getElementById("tsdScanCard");
    const empty = shell.querySelector(".tsd-empty");
    if (card) {
      card.outerHTML = html;
    } else if (empty) {
      empty.outerHTML = html;
    } else {
      const scanned = shell.querySelector(".tsd-scanned");
      if (scanned) scanned.insertAdjacentHTML("beforebegin", html);
      else shell.insertAdjacentHTML("beforeend", html);
    }
    wireScanInput(mode);
    return true;
  }

  function patchScanAfterSuccess(mode, input) {
    if (!patchScanCard(mode)) {
      renderScan();
      return;
    }
    refreshScanChrome(mode);
    const field = input || document.getElementById("tsdScanInput");
    if (field) {
      field.value = "";
      if (!state.searchOpen && !shouldShowBrowseSheet()) {
        setTimeout(() => field.focus(), 0);
      }
    }
  }

  function patchScanAfterStickerMatch(mode) {
    if (!patchScanCard(mode)) {
      renderScan();
      return;
    }
    refreshScanChrome(mode);
    const input = document.getElementById("tsdScanInput");
    if (input && !state.searchOpen && !shouldShowBrowseSheet()) {
      setTimeout(() => input.focus(), 40);
    }
  }

  function renderScan(opts) {
    const keepSearchFocus = !!(opts && opts.keepSearchFocus);
    const mode = state.route.mode;
    const sid = state.route.supplyId;
    const main = document.getElementById("tsdMain");
    const back = document.getElementById("tsdBackBtn");
    const title = document.getElementById("tsdTitle");
    syncSourceSelectVisibility();
    syncSearchChrome();
    if (back) {
      back.hidden = false;
      back.href = `#/s/${sid}`;
      back.onclick = (ev) => {
        ev.preventDefault();
        leaveScanScreen();
      };
      back.textContent = "←";
    }
    title.textContent = mode === "kiz" ? "С маркировкой" : "Без маркировки";
    updateProgressBar(mode);

    const { total, done, left } = scanProgress(mode);
    const banner = state.banner;
    const body = buildScanCardHtml(mode);

    const loadErr =
      isOzon() && state.gm.loadError && !state.gm.hasFillable
        ? `<div class="tsd-banner is-warn tsd-gm-load-err">Грузоместа: ${esc(state.gm.loadError)}</div>`
        : "";
    const gmN = isOzon() ? gmBoundCount(mode) : 0;
    const showGmStat = isOzon() && (gmUiVisible() || gmN > 0);

    main.innerHTML = `
      <div class="tsd-scan-shell">
        <div class="tsd-stats">
          <span>Готово ${done} / ${total}${
            showGmStat ? ` · В ГМ ${gmN}` : ""
          }</span>
          <span>Осталось ${left}</span>
        </div>
        ${loadErr}
        ${bannerHtml(banner)}
        ${body}
        ${renderScannedListHtml(mode)}
      </div>`;

    // Fixed sheet under header — does not push the scan field down.
    const existingSheet = document.getElementById("tsdBrowseSheet");
    if (existingSheet) existingSheet.remove();
    const browseHtml = renderBrowseSheetHtml(mode).trim();
    if (browseHtml) {
      const app = document.getElementById("tsdApp") || document.body;
      const wrap = document.createElement("div");
      wrap.innerHTML = browseHtml;
      const sheet = wrap.firstElementChild;
      if (sheet) {
        const scrollTop = document.getElementById("tsdScrollTop");
        if (scrollTop && scrollTop.parentNode === app) app.insertBefore(sheet, scrollTop);
        else app.appendChild(sheet);
      }
      wireBrowseSheet();
    }

    wireGmBar();
    wireBannerDismiss(main);
    wireScanInput(mode, { keepSearchFocus });
    wireScanFooter(mode);
    syncScrollTopFab();
  }

  async function onScanEnter(input) {
    const mode = state.route.mode;
    // Rebind sheet is modal — ignore wedge input until operator answers.
    if (isOzon() && state.gm.rebindResolver) return;
    let raw = String(input.value || "");
    if (!normalizeScan(raw)) return;
    if (state.banner && state.banner.clearOnScan !== false) {
      clearBanner();
    }
    if (hasCyrillic(raw)) {
      const mapped = fixRuKeyboardLayout(raw);
      if (hasCyrillic(mapped)) {
        setBanner("Русская раскладка — переключите на EN", "warn");
        beep(false);
        input.value = "";
        input.focus();
        return;
      }
      raw = mapped;
      input.value = mapped;
    }

    // Ozon GM select mode: Enter matches only cargo QR (never order sticker).
    if (isOzon() && state.gm.awaitingScan && gmUiVisible()) {
      const ok = await handleGmScan(raw);
      input.value = "";
      if (ok) {
        if (!patchScanCard(mode)) renderScan();
        else {
          refreshGmBar();
          refreshScanBanner();
        }
        const field = document.getElementById("tsdScanInput");
        if (field && !state.searchOpen && !shouldShowBrowseSheet()) {
          setTimeout(() => field.focus(), 0);
        }
      } else {
        input.select();
        refreshScanBanner();
      }
      return;
    }

    if (state.step === "sticker" || !state.pendingOrderId) {
      const rows = mode === "kiz" ? state.kizRows : state.pickRows;
      const found = findBySticker(rows, raw);
      if (found.ambiguous) {
        setBanner("Стикер совпал у нескольких заказов — сканируйте QR ещё раз", "err");
        beep(false);
        input.select();
        refreshScanBanner();
        return;
      }
      if (!found.row) {
        setBanner(
          mode === "kiz"
            ? "Стикер не найден среди заказов с КИЗ"
            : "Стикер не найден среди заказов без КИЗ",
          "err"
        );
        beep(false);
        input.select();
        refreshScanBanner();
        return;
      }
      state.pendingOrderId = rowScanId(found.row);
      state.step = mode === "kiz" ? "mark" : "sku";
      setBanner(null);
      beep(true);
      patchScanAfterStickerMatch(mode);
      return;
    }

    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const row = findRowByScanId(rows, state.pendingOrderId);
    if (!row) {
      state.pendingOrderId = null;
      state.step = "sticker";
      patchScanAfterSuccess(mode, input);
      return;
    }

    const rowId = rowScanId(row);
    try {
      if (mode === "kiz") {
        const mark = normalizeKizMark(raw);
        const check = markMatchesOrder(mark, row);
        if (!check.ok) {
          setBanner(check.error || "КИЗ не подходит", "err");
          state.rowErrors[rowId] = check.error || "КИЗ не подходит";
          beep(false);
          input.select();
          refreshScanBanner();
          return;
        }
        delete state.rowErrors[rowId];
        delete state.pendingKizClear[rowId];
        const ownDup = (Array.isArray(row.kiz_codes) ? row.kiz_codes : []).some(
          (c) => normalizeKizMark(c) === mark
        );
        if (ownDup) {
          setBanner("Этот КИЗ уже в этом заказе", "err");
          beep(false);
          input.select();
          refreshScanBanner();
          return;
        }
        const dup = state.kizRows.find((r) =>
          rowScanId(r) !== rowId &&
          (Array.isArray(r.kiz_codes) ? r.kiz_codes : []).some(
            (c) => normalizeKizMark(c) === mark
          )
        );
        if (dup) {
          setBanner(`Этот КИЗ уже в ${isOzon() ? "отпр." : "заказе"} ${rowDisplayLabel(dup)}`, "err");
          beep(false);
          input.select();
          refreshScanBanner();
          return;
        }
        if (!Array.isArray(row.kiz_codes) || !row.kiz_codes.length) row.kiz_codes = [""];
        let placed = false;
        for (let i = 0; i < row.kiz_codes.length; i += 1) {
          if (!String(row.kiz_codes[i] || "").trim()) {
            row.kiz_codes[i] = mark;
            placed = true;
            break;
          }
        }
        if (!placed) row.kiz_codes.push(mark);
        row.kiz_local = true;
        noteSessionScanned(rowId);
        scheduleKizLocalAutosave(rowId);
        const kizN = filledKizEntries(row).length;
        const label = rowDisplayLabel(row);
        setBanner(
          kizN <= 1
            ? `КИЗ записан · ${label}. Для 2-го КИЗ снова сканируйте стикер`
            : `КИЗ ${kizN} записан · ${label}`,
          "ok"
        );
      } else {
        const check = eanMatchesOrder(raw, row);
        if (!check.ok) {
          setBanner(check.error || "ШК не подходит", "err");
          beep(false);
          input.select();
          refreshScanBanner();
          return;
        }
        row.pick_verified = true;
        row.pick_barcode = digitsOnly(raw);
        noteSessionScanned(rowId);
        schedulePickLocalAutosave(rowId);
        setBanner(`ШК подтверждён · ${rowDisplayLabel(row)}`, "ok");
      }
      // TZ: return to sticker immediately; bind is background except rebind confirm.
      beep(true);
      state.pendingOrderId = null;
      state.step = "sticker";
      patchScanAfterSuccess(mode, input);
      await maybeBindGmAfterSuccess(row);
    } catch (e) {
      setBanner(e.message || String(e), "err");
      beep(false);
      refreshScanBanner();
      input.select();
    }
  }

  async function onRoute() {
    if (!boot.can_view_wb_fbs_tsd) {
      renderDenied();
      return;
    }
    state.route = parseHash();
    syncSourceSelectVisibility();
    const seq = ++state.loadSeq;
    stopLoadingUi();

    // Show destination loader immediately so the previous screen never lingers.
    if (state.route.view === "hub") {
      showLoadingScreen({
        title: `Открываем ${supplyNameHint(state.route.supplyId)}`,
        status: "Ищем поставку…",
        stages: ["Открытие", "С маркировкой", "Без маркировки"],
      });
    } else if (state.route.view === "scan") {
      // Switch chrome immediately so the hub title/strip never lingers under load.
      syncSourceSelectVisibility();
      syncSearchChrome();
      const titleEl = document.getElementById("tsdTitle");
      if (titleEl) {
        titleEl.textContent =
          state.route.mode === "kiz" ? "С маркировкой" : "Без маркировки";
      }
      const backEl = document.getElementById("tsdBackBtn");
      if (backEl) {
        backEl.hidden = false;
        backEl.href = `#/s/${state.route.supplyId}`;
        backEl.textContent = "←";
        backEl.onclick = (ev) => {
          ev.preventDefault();
          leaveScanScreen();
        };
      }
      if (state.route.mode === "kiz") {
        showLoadingScreen({
          title: "Товары с маркировкой",
          simple: true,
        });
      } else {
        showLoadingScreen({
          title: "Товары без маркировки",
          simple: true,
        });
      }
    } else {
      showLoadingScreen({
        title: "Поставки на сборке",
        status: "Загружаем список поставок…",
        stages: ["Список поставок"],
      });
    }

    try {
      if (!state.sources.length) {
        setLoadingStatus("Загружаем кабинеты…", 0);
        await loadSources();
        if (seq !== state.loadSeq) return;
        if (state.route.view === "list") {
          setLoadingStatus("Загружаем список поставок…", 0);
        } else if (state.route.view === "hub") {
          setLoadingStatus("Ищем поставку…", 0);
        }
      }

      if (state.route.view === "list") {
        state.pendingOrderId = null;
        state.step = "sticker";
        state.banner = null;
        closeGmRebind(false);
        resetGmState({ clearList: true });
        setLoadingStatus("Загружаем список поставок…", 0);
        await loadSupplies();
        if (seq !== state.loadSeq) return;
        stopLoadingUi();
        renderList();
        return;
      }

      if (!state.sourceId) {
        stopLoadingUi();
        const main = document.getElementById("tsdMain");
        if (main) main.innerHTML = `<div class="tsd-empty">Выберите кабинет</div>`;
        return;
      }

      if (state.route.view === "hub") {
        state.pendingOrderId = null;
        state.step = "sticker";
        state.banner = null;
        closeGmRebind(false);
        state.gm.awaitingScan = false;
        const sid = state.route.supplyId;
        const hubSid = String(sid || "");
        if (state.gm.boundSupplyId && hubSid && state.gm.boundSupplyId !== hubSid) {
          resetGmState({ clearList: true });
        }
        if (String(state.kizHubToneSupplyId || "") !== String(sid || "")) {
          state.kizHubTone = "";
          state.kizHubToneSupplyId = String(sid || "");
        }
        if (String(state.pickHubToneSupplyId || "") !== String(sid || "")) {
          state.pickHubTone = "";
          state.pickHubToneSupplyId = String(sid || "");
        }
        const stopRotate = startLoadingRotate(
          [
            { status: "Открываем поставку…", stage: 0 },
            { status: "Считаем прогресс…", stage: 1 },
          ],
          1800
        );
        try {
          await loadSummary(sid);
        } finally {
          stopRotate();
        }
        if (seq !== state.loadSeq) return;
        stopLoadingUi();
        renderHub();
        return;
      }

      if (state.route.view === "scan") {
        state.pendingOrderId = null;
        state.step = "sticker";
        state.sessionScannedIds = [];
        state.searchOpen = false;
        state.orderSearch = "";
        resetScanFilters();
        closeGmRebind(false);
        state.gm.awaitingScan = false;
        if (state.route.mode === "kiz") {
          await loadKiz(state.route.supplyId);
        } else {
          await loadPick(state.route.supplyId);
        }
        if (seq !== state.loadSeq) return;
        if (isOzon()) {
          const sidNow = String(state.route.supplyId || "");
          // Drop active GM when switching to another supply.
          if (state.gm.boundSupplyId && state.gm.boundSupplyId !== sidNow) {
            setActiveGm(null);
          }
          await loadGmContainers(state.gm.boundSupplyId !== sidNow);
          if (seq !== state.loadSeq) return;
        } else {
          closeGmRebind(false);
          resetGmState({ clearList: true });
        }
        captureScanBaselines(state.route.mode);
        stopLoadingUi();
        if (!state.step) state.step = "sticker";
        renderScan();
      } else {
        closeGmRebind(false);
        state.gm.awaitingScan = false;
      }
    } catch (e) {
      if (seq !== state.loadSeq) return;
      stopLoadingUi();
      const main = document.getElementById("tsdMain");
      if (main) {
        main.innerHTML = `<div class="tsd-empty" style="color:#b91c1c">${esc(e.message || e)}</div>`;
      }
    }
  }

  function bindChrome() {
    const sel = document.getElementById("tsdSourceSelect");
    if (sel) {
      sel.addEventListener("change", async () => {
        // Phase 2: hard GM reset on source change (before navigation).
        closeGmRebind(false);
        resetGmState({ clearList: true });
        state.sourceId = sel.value ? Number(sel.value) : null;
        if (state.sourceId) localStorage.setItem(LS_SOURCE, String(state.sourceId));
        if (state.route.view !== "list") navigate("#/");
        else {
          const seq = ++state.loadSeq;
          try {
            showLoadingScreen({
              title: "Поставки на сборке",
              status: "Обновляем список для кабинета…",
              stages: ["Список поставок"],
            });
            await loadSupplies();
            if (seq !== state.loadSeq) return;
            stopLoadingUi();
            renderList();
          } catch (e) {
            if (seq !== state.loadSeq) return;
            stopLoadingUi();
            toast(e.message || e);
            try {
              renderList();
            } catch (_err) {
              /* ignore */
            }
          }
        }
      });
    }
    const searchBtn = document.getElementById("tsdSearchBtn");
    if (searchBtn) {
      searchBtn.addEventListener("click", () => {
        if (state.searchOpen) closeHeaderSearch();
        else openHeaderSearch();
      });
    }
    const filterBtn = document.getElementById("tsdFilterBtn");
    if (filterBtn) {
      filterBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        toggleFilterMenu();
      });
    }
    const filterSearchBtn = document.getElementById("tsdFilterSearchBtn");
    if (filterSearchBtn) {
      filterSearchBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        state.filterOpen = false;
        openHeaderSearch();
      });
    }
    const filterFilled = document.getElementById("tsdFilterFilled");
    const filterEmpty = document.getElementById("tsdFilterEmpty");
    const filterErrors = document.getElementById("tsdFilterErrors");
    const filterCancelled = document.getElementById("tsdFilterCancelled");
    const filterNoGm = document.getElementById("tsdFilterNoGm");
    if (filterFilled) {
      filterFilled.addEventListener("change", () => onFilterChange("filled"));
    }
    if (filterEmpty) {
      filterEmpty.addEventListener("change", () => onFilterChange("empty"));
    }
    if (filterErrors) {
      filterErrors.addEventListener("change", () => onFilterChange("errors"));
    }
    if (filterCancelled) {
      filterCancelled.addEventListener("change", () => onFilterChange("cancelled"));
    }
    if (filterNoGm) {
      filterNoGm.addEventListener("change", () => onFilterChange("noGm"));
    }
    document.addEventListener("click", (ev) => {
      if (!state.filterOpen) return;
      const wrap = document.getElementById("tsdFilterWrap");
      if (wrap && wrap.contains(ev.target)) return;
      closeFilterMenu();
    });
    const searchClose = document.getElementById("tsdSearchClose");
    if (searchClose) {
      searchClose.addEventListener("click", () => {
        const input = document.getElementById("tsdOrderSearch");
        const view = state.route.view;
        const cur =
          view === "list"
            ? String(state.search || "")
            : String(state.orderSearch || (input && input.value) || "");
        // × next to the field clears the query; only closes when already empty.
        if (String(cur || "").trim()) {
          if (view === "list") {
            state.search = "";
            if (input) input.value = "";
            syncSearchChrome();
            clearTimeout(listSearchTimer);
            loadSupplies()
              .then(() => renderList())
              .catch((e) => toast(e.message || e));
            if (input) setTimeout(() => input.focus(), 20);
            return;
          }
          state.orderSearch = "";
          if (input) input.value = "";
          const browseSearch = document.getElementById("tsdBrowseSearchInput");
          if (browseSearch) browseSearch.value = "";
          syncSearchChrome();
          refreshSearchResultsOnly();
          const focusEl =
            document.getElementById("tsdBrowseSearchInput") || input;
          if (focusEl) setTimeout(() => focusEl.focus(), 20);
          return;
        }
        closeHeaderSearch();
      });
    }
    const orderSearch = document.getElementById("tsdOrderSearch");
    if (orderSearch) {
      orderSearch.addEventListener("input", () => {
        if (state.route.view === "list") {
          state.search = String(orderSearch.value || "").trim();
          clearTimeout(listSearchTimer);
          listSearchTimer = setTimeout(() => applyListSearchFromHeader(), 280);
          return;
        }
        state.orderSearch = String(orderSearch.value || "");
        refreshSearchResultsOnly();
      });
      orderSearch.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") {
          ev.preventDefault();
          closeHeaderSearch();
          return;
        }
        if (ev.key === "Enter") {
          ev.preventDefault();
          if (state.route.view === "list") {
            clearTimeout(listSearchTimer);
            state.search = String(orderSearch.value || "").trim();
            applyListSearchFromHeader();
            return;
          }
          applyOrderSearchEnter();
        }
      });
    }
    const scrollTop = document.getElementById("tsdScrollTop");
    if (scrollTop) {
      scrollTop.addEventListener("click", () => scrollToScanInput());
    }
    window.addEventListener(
      "scroll",
      () => {
        syncScrollTopFab();
        if (document.getElementById("tsdBrowseSheet")) syncBrowseSheetPosition();
      },
      { passive: true }
    );
    window.addEventListener("resize", () => {
      if (document.getElementById("tsdBrowseSheet")) scheduleBrowseSheetPositionSync();
    });
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", () => {
        if (document.getElementById("tsdBrowseSheet")) scheduleBrowseSheetPositionSync();
      });
    }
    window.addEventListener("hashchange", onRoute);
  }

  async function bootApp() {
    bindChrome();
    if (!boot.can_view_wb_fbs_tsd) {
      renderDenied();
      return;
    }
    await onRoute();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootApp);
  } else {
    bootApp();
  }
})();
