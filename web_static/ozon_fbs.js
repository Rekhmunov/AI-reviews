/**
 * OZON FBS section — isolated from WB FBS and Ozon FBO.
 * Local supplies on «Ожидают отгрузки» mirror WB FBS collect rules (Feedpilot-only).
 */
(function () {
  "use strict";

  const TAB_COUNT_IDS = {
    awaiting_packaging: "ozonFbsCountAwaitingPackaging",
    awaiting_deliver: "ozonFbsCountAwaitingDeliver",
    delivering: "ozonFbsCountDelivering",
    arbitration: "ozonFbsCountArbitration",
    delivered: "ozonFbsCountDelivered",
    cancelled: "ozonFbsCountCancelled",
  };

  /** Hidden in UI for now (sync still tracks counts). */
  const OZON_FBS_HIDDEN_TABS = new Set(["arbitration", "delivered", "cancelled"]);

  const OZON_FBS_TAB_LABELS = {
    awaiting_packaging: "Ожидают сборки",
    awaiting_deliver: "Ожидают отгрузки",
    delivering: "Доставляются",
    arbitration: "Спорные",
    delivered: "Доставлены",
    cancelled: "Отменены",
  };

  const state = {
    sources: [],
    sourceId: null,
    tab: "awaiting_packaging",
    page: 1,
    pageSize: 50,
    total: 0,
    counts: {},
    items: [],
    selected: new Set(),
    search: "",
    searchTimer: null,
    syncPollTimer: null,
    detailPosting: null,
    detailPayload: null,
    shipAllBusy: false,
    syncBusy: false,
    viewMode: "orders", // orders | supplies
    /** Exact posting-number hit across tabs (WB-like toolbar escape hatch). */
    lookupMode: false,
    lookupMeta: null,
    /** Guards stale async search/lookup results. */
    loadSeq: 0,
  };

  const collectState = {
    preview: null,
    sourceId: null,
    busy: false,
    pollTimer: null,
  };

  const splitState = {
    busy: false,
    pollTimer: null,
    progressText: "",
    lastOk: false,
    lastSingleAfter: 0,
  };

  const supplyDetailState = {
    supplyId: null,
    sourceId: null,
    supply: null,
    selected: new Set(),
    /** Tab scope for this open (awaiting_deliver / delivering); filters orders/print. */
    postingTab: null,
    /** False until supply detail (orders) finished loading. */
    ordersReady: false,
  };

  const _OZON_FBS_DETAIL_ACTION_IDS = [
    "ozonFbsSupplyDetailPickingBtn",
    "ozonFbsSupplyDetailPickingMenuBtn",
    "ozonFbsSupplyDetailStickersBtn",
    "ozonFbsSupplyDetailStickersMenuBtn",
    "ozonFbsSupplyDetailTrbxBtn",
    "ozonFbsSupplyDetailKizBtn",
    "ozonFbsSupplyDetailKizRefreshBtn",
    "ozonFbsSupplyDetailPickVerifyBtn",
    "ozonFbsSupplyDetailPickRefreshBtn",
    "ozonFbsSupplyDetailCancelledBtn",
    "ozonFbsSupplyDetailShipmentsBtn",
    "ozonFbsSupplyDetailMoveDeliveringBtn",
  ];

  const ozonFbsCancelledState = {
    rows: [],
    loading: false,
    lastError: "",
    refreshGen: 0,
  };

  const stickersCategoryState = {
    groups: [],
    selected: new Set(),
    loading: false,
  };

  const shipmentsState = {
    supplyId: null,
    sourceId: null,
    data: null,
    loading: false,
    forming: false,
    /** @type {number|null} selected formed carriage for ШК preview/print */
    selectedCarriageId: null,
  };

  const containersState = {
    supplyId: null,
    sourceId: null,
    warehouseId: null,
    items: [],
    loading: false,
    busy: false,
  };

  function permissions() {
    return window.APP_PERMISSIONS || {};
  }

  function canView() {
    const p = permissions();
    return p.can_view_ozon_fbs_supplies || (p.can_view_supplies && p.is_tenant_owner);
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = String(s ?? "");
    return d.innerHTML;
  }

  /** Ozon sticker: always highlight 4 chars immediately left of the first «-». */
  function formatOzonPostingNumberHtml(postingNumber) {
    const s = String(postingNumber || "").trim();
    if (!s) return "—";
    const hi = (text) => `<span class="ozon-fbs-posting-tail">${esc(text)}</span>`;
    const dash = s.indexOf("-");
    if (dash > 0) {
      const head = s.slice(0, dash);
      const tail = s.slice(dash); // includes leading «-…»
      if (head.length >= 4) {
        return `${esc(head.slice(0, -4))}${hi(head.slice(-4))}${esc(tail)}`;
      }
      return `${hi(head)}${esc(tail)}`;
    }
    if (s.length > 4) {
      return `${esc(s.slice(0, -4))}${hi(s.slice(-4))}`;
    }
    return hi(s);
  }

  function detailText(detail) {
    if (detail == null) return "";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((x) => (typeof x === "string" ? x : (x?.msg || x?.message || JSON.stringify(x)))).join("; ");
    }
    if (typeof detail === "object") {
      if (detail.message) return String(detail.message);
      if (detail.msg) return String(detail.msg);
    }
    try { return JSON.stringify(detail); } catch (_) { return String(detail); }
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
  }

  function agoLabel(iso) {
    if (!iso) return "";
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return "";
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 60) return `${sec} сек назад`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min} мин назад`;
    const h = Math.floor(min / 60);
    const rem = min % 60;
    if (h < 48) return rem ? `${h} ч ${rem} мин назад` : `${h} ч назад`;
    const days = Math.floor(h / 24);
    return `${days} дн назад`;
  }

  /** Order time for supply-detail modal only (oldest → newest). */
  function _ozonFbsOrderTimeMs(row) {
    const raw = String(row?.created_at_ozon || row?.in_process_at || "").trim();
    if (!raw) return Number.POSITIVE_INFINITY;
    const t = Date.parse(raw);
    return Number.isFinite(t) ? t : Number.POSITIVE_INFINITY;
  }

  /**
   * Sort postings oldest-first for the supply detail modal table.
   * Does not mutate the source array; picking lists / stickers use other APIs.
   */
  function sortSupplyDetailOrdersOldestFirst(rows) {
    return (rows || []).slice().sort((a, b) => {
      const da = _ozonFbsOrderTimeMs(a);
      const db = _ozonFbsOrderTimeMs(b);
      if (da !== db) return da - db;
      return String(a?.posting_number || "").localeCompare(
        String(b?.posting_number || ""),
        "ru"
      );
    });
  }

  function jsonHeaders() {
    const h = { "Content-Type": "application/json" };
    const csrf = typeof window.getCsrfToken === "function" ? window.getCsrfToken() : "";
    if (csrf) h["X-CSRF-Token"] = csrf;
    return h;
  }

  function isSuppliesTab() {
    // Exact posting lookup always renders a single order row, even on supply tabs.
    if (state.lookupMode) return false;
    return state.tab === "awaiting_deliver" || state.tab === "delivering";
  }

  function parsePostingNumberQuery(search) {
    const q = String(search || "").trim().replace(/\s+/g, "");
    if (/^\d{6,}-\d{3,}-\d{1,4}$/.test(q)) return q;
    return "";
  }

  function clearLookupMode() {
    state.lookupMode = false;
    state.lookupMeta = null;
  }

  async function lookupPostingByNumber(postingNumber, { seq, refresh = true } = {}) {
    const params = new URLSearchParams({
      source_id: String(state.sourceId),
      posting_number: String(postingNumber),
    });
    if (!refresh) params.set("refresh", "0");
    const res = await fetch(`/api/ozon-fbs/postings/find?${params}`);
    const data = await res.json().catch(() => ({}));
    if (seq != null && seq !== state.loadSeq) return null;
    if (!res.ok) {
      throw new Error(detailText(data.detail) || "Не удалось найти отправление");
    }
    return data;
  }

  function applyLookupResult(data, postingNumber) {
    const item = data && data.item;
    if (!data?.found || !item) {
      clearLookupMode();
      return false;
    }
    const tab = String(data.tab || item.tab || "").trim();
    const supplyId = String(item.supply_id || "").trim();
    state.lookupMode = true;
    state.lookupMeta = {
      posting_number: String(data.posting_number || postingNumber),
      tab,
      source: String(data.source || ""),
      message: String(data.message || ""),
      supply_id: supplyId,
    };
    state.items = [item];
    state.total = 1;
    state.page = 1;
    state.selected.clear();
    if (data.counts) updateTabCounts(data.counts);
    // Keep operator on a visible tab button; do not open hidden tabs.
    if (tab && !OZON_FBS_HIDDEN_TABS.has(tab) && state.tab !== tab) {
      state.tab = tab;
      document.querySelectorAll("#ozonFbsTabs .wb-fbs-tab").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tab === tab);
      });
    }
    syncTableMode();
    renderTable([item]);
    syncPackagingActionButtons();
    const info = document.getElementById("ozonFbsInfo");
    if (info) {
      const tabLabel = OZON_FBS_TAB_LABELS[tab] || tab || "—";
      const supplyBit = supplyId ? ` · поставка ${supplyId}` : "";
      const via = data.status_refreshed || data.source === "local+api"
        ? "статус из Ozon"
        : (data.message && String(data.message).startsWith("Статус из базы")
          ? "статус из базы (API недоступен)"
          : "найдено в базе");
      info.textContent = `Отправление ${postingNumber}: ${tabLabel}${supplyBit} · ${via}`;
    }
    const pageInfo = document.getElementById("ozonFbsPageInfo");
    if (pageInfo) pageInfo.textContent = "1 / 1";
    const pager = document.querySelector("#section-ozon-fbs .supplies-pagination");
    if (pager) pager.style.display = "";
    const prev = document.getElementById("ozonFbsPrevBtn");
    const next = document.getElementById("ozonFbsNextBtn");
    if (prev) prev.disabled = true;
    if (next) next.disabled = true;
    return true;
  }

  function isDeliveringSuppliesTab() {
    return state.tab === "delivering";
  }

  /**
   * Composition lock for «Доставляются»: нельзя менять состав/название,
   * но Маркировка и Проверка ШК остаются доступны (локальная БД).
   */
  function isSupplyDetailReadOnly() {
    return Boolean(supplyDetailState.supply?.read_only) || isDeliveringSuppliesTab();
  }

  function syncSupplyDetailReadOnlyMode(readOnly) {
    const modal = document.getElementById("ozonFbsSupplyDetailModal");
    const actions = modal?.querySelector(".wb-fbs-sd-actions");
    const checkTh = modal?.querySelector("th.wb-fbs-sd-col-check");
    const actTh = modal?.querySelector("th.wb-fbs-sd-col-act");
    if (modal) modal.classList.toggle("wb-fbs-sd--readonly", !!readOnly);
    // Keep action bar visible so Marking / Pick-verify stay reachable on delivering.
    if (actions) actions.hidden = false;
    if (checkTh) checkTh.hidden = !!readOnly;
    if (actTh) actTh.hidden = !!readOnly;
    document.querySelectorAll("#ozonFbsSupplyDetailColgroup col[data-fixed]").forEach((col) => {
      col.style.display = readOnly ? "none" : "";
    });
    const moveBtn = document.getElementById("ozonFbsSupplyDetailMoveDeliveringBtn");
    // Local «Перенести в доставку» only from «Ожидают отгрузки».
    if (moveBtn) moveBtn.hidden = !!readOnly || isDeliveringSuppliesTab();
    const info = document.getElementById("ozonFbsSupplyDetailInfo");
    if (info) {
      if (readOnly) {
        info.hidden = false;
        info.textContent =
          "Состав поставки изменению не подлежит — отправления уже в доставке. "
          + "Маркировку и проверку ШК можно заносить локально.";
      } else {
        info.hidden = true;
        info.textContent = "";
      }
    }
  }

  function colspan() {
    if (!isSuppliesTab()) return state.lookupMode ? 5 : 4;
    return isDeliveringSuppliesTab() ? 6 : 7;
  }

  async function loadSources() {
    const sel = document.getElementById("ozonFbsSourceSelect");
    if (!sel) return;
    try {
      const res = await fetch("/api/ozon-fbs/sources");
      const data = await res.json();
      state.sources = Array.isArray(data) ? data : [];
      const prev = state.sourceId;
      sel.innerHTML = state.sources.length
        ? state.sources.map((s) =>
            `<option value="${esc(s.id)}">${esc(s.name || ("Источник " + s.id))}</option>`
          ).join("")
        : '<option value="">Нет активных источников OZON ФБС</option>';
      if (prev && state.sources.some((s) => Number(s.id) === Number(prev))) {
        sel.value = String(prev);
        state.sourceId = Number(prev);
      } else if (state.sources.length) {
        state.sourceId = Number(state.sources[0].id);
        sel.value = String(state.sourceId);
      } else {
        state.sourceId = null;
      }
    } catch (e) {
      sel.innerHTML = '<option value="">Ошибка загрузки источников</option>';
      state.sourceId = null;
    }
  }

  function updateTabCounts(counts) {
    const next = counts && typeof counts === "object" ? { ...counts } : {};
    // Keep last known multi if a response omitted it (older payloads / supplies).
    if (
      next.awaiting_packaging_multi == null &&
      state.counts &&
      state.counts.awaiting_packaging_multi != null
    ) {
      next.awaiting_packaging_multi = state.counts.awaiting_packaging_multi;
      if (
        next.awaiting_packaging_multi_extra == null &&
        state.counts.awaiting_packaging_multi_extra != null
      ) {
        next.awaiting_packaging_multi_extra = state.counts.awaiting_packaging_multi_extra;
      }
    }
    // Keep open supplies count — find/supplies payloads often omit it, and wiping
    // it hides «Добавить к существующей» on the selection bottom bar.
    if (
      next.open_supplies == null &&
      state.counts &&
      state.counts.open_supplies != null
    ) {
      next.open_supplies = state.counts.open_supplies;
    }
    state.counts = next;
    Object.keys(TAB_COUNT_IDS).forEach((tab) => {
      const el = document.getElementById(TAB_COUNT_IDS[tab]);
      if (el) el.textContent = String(state.counts[tab] || 0);
    });
    syncPackagingActionButtons();
    updateBottomBar();
  }

  function multiAwaitingCount() {
    const fromCounts = Math.max(0, Number(state.counts.awaiting_packaging_multi || 0) || 0);
    if (fromCounts > 0) return fromCounts;
    // Fallback: current packaging page rows (same for owner and managers).
    if (state.tab === "awaiting_packaging" && !isSuppliesTab() && Array.isArray(state.items)) {
      const fromItems = state.items.filter((row) => {
        if (!row || row.supply_id) return false;
        if (row.is_multi_unit === true) return true;
        return Math.max(0, Number(row.unit_count || 0) || 0) > 1;
      }).length;
      if (fromItems > 0) return fromItems;
    }
    return 0;
  }

  function isSupplyOpenBlocked() {
    // Block opening local supplies during sync/split/collect/ship-all.
    return Boolean(
      state.syncBusy || collectState.busy || splitState.busy || state.shipAllBusy
    );
  }

  function supplyOpenBlockedTitle() {
    if (state.syncBusy) return "Дождитесь окончания синхронизации";
    if (splitState.busy) return "Дождитесь окончания разделения мультизаказов";
    if (collectState.busy || state.shipAllBusy) return "Дождитесь окончания сборки заказов";
    return "Дождитесь окончания операции";
  }

  function syncSupplyOpenLinks() {
    const blocked = isSupplyOpenBlocked();
    const tip = blocked ? supplyOpenBlockedTitle() : "";
    document.querySelectorAll("#ozonFbsOrdersTbody .wb-fbs-supply-name[data-supply-open]").forEach((el) => {
      el.classList.toggle("is-disabled", blocked);
      if (blocked) {
        el.setAttribute("aria-disabled", "true");
        el.setAttribute("title", tip);
        el.removeAttribute("tabindex");
        el.removeAttribute("role");
      } else {
        el.removeAttribute("aria-disabled");
        el.removeAttribute("title");
        el.setAttribute("tabindex", "0");
        el.setAttribute("role", "button");
      }
    });
  }

  function syncPackagingActionButtons() {
    const splitBtn = document.getElementById("ozonFbsSplitMultiBtn");
    const shipBtn = document.getElementById("ozonFbsShipAllBtn");
    const n = Number(state.counts.awaiting_packaging || 0);
    const multi = multiAwaitingCount();
    const syncBusy = Boolean(state.syncBusy);
    const busy =
      syncBusy ||
      Boolean(state.shipAllBusy) ||
      Boolean(collectState.busy) ||
      Boolean(splitState.busy);
    // Visible on the three operational tabs when multi remain (same for all roles).
    const onMainTabs =
      state.tab === "awaiting_packaging" ||
      state.tab === "awaiting_deliver" ||
      state.tab === "delivering";
    const syncTitle = "Идёт синхронизация, подождите";
    if (splitBtn) {
      const showSplit = onMainTabs && multi > 0;
      splitBtn.hidden = !showSplit;
      splitBtn.style.display = showSplit ? "" : "none";
      splitBtn.disabled = !state.sourceId || !showSplit || busy;
      if (syncBusy && showSplit) {
        splitBtn.title = syncTitle;
      } else if (showSplit) {
        splitBtn.title = `Разделить мультизаказы (${multi}) на одинарные без сборки`;
      } else {
        splitBtn.title = "Нет мультизаказов в «Ожидают сборки»";
      }
      splitBtn.textContent = splitState.busy
        ? (splitState.progressText || "Разделение…")
        : "Разделить мультизаказы";
    }
    if (shipBtn) {
      const blockedByMulti = multi > 0;
      shipBtn.disabled = !state.sourceId || n <= 0 || busy || blockedByMulti;
      if (syncBusy) {
        shipBtn.title = syncTitle;
      } else if (blockedByMulti) {
        shipBtn.title = "Сначала нужно разделить мультизаказы";
      } else if (n > 0) {
        shipBtn.title =
          `Собрать все отправления в «Ожидают сборки» (${n}) и создать локальную поставку`;
      } else {
        shipBtn.title = "Нет отправлений в «Ожидают сборки»";
      }
    }
    syncSupplyOpenLinks();
  }

  function syncShipAllButton() {
    syncPackagingActionButtons();
  }

  function syncSelectAll() {
    const selAll = document.getElementById("ozonFbsSelectAll");
    if (!selAll) return;
    const key = isSuppliesTab() ? "supply_id" : "posting_number";
    const ids = state.items.map((x) => String(x[key] || "").trim()).filter(Boolean);
    const allOnPage = ids.length > 0 && ids.every((id) => state.selected.has(id));
    const someOnPage = ids.some((id) => state.selected.has(id));
    selAll.checked = allOnPage;
    selAll.indeterminate = !allOnPage && someOnPage;
  }

  function onCheckboxChange() {
    document.querySelectorAll("#ozonFbsOrdersTable .wb-fbs-row-cb").forEach((cb) => {
      const id = String(cb.dataset.supplyId || cb.dataset.posting || "").trim();
      if (!id) return;
      if (cb.checked) state.selected.add(id);
      else state.selected.delete(id);
    });
    syncSelectAll();
    updateBottomBar();
  }

  function toggleSelectAll(checked) {
    document.querySelectorAll("#ozonFbsOrdersTable .wb-fbs-row-cb").forEach((cb) => {
      cb.checked = !!checked;
      const id = String(cb.dataset.supplyId || cb.dataset.posting || "").trim();
      if (!id) return;
      if (checked) state.selected.add(id);
      else state.selected.delete(id);
    });
    const selAll = document.getElementById("ozonFbsSelectAll");
    if (selAll) selAll.indeterminate = false;
    updateBottomBar();
  }

  function selectedCountLabel(n) {
    const abs = Math.abs(Number(n) || 0) % 100;
    const last = abs % 10;
    let word;
    if (isSuppliesTab()) {
      word = "поставок";
      if (!(abs > 10 && abs < 20)) {
        if (last === 1) word = "поставка";
        else if (last >= 2 && last <= 4) word = "поставки";
      }
    } else {
      word = "отправлений";
      if (!(abs > 10 && abs < 20)) {
        if (last === 1) word = "отправление";
        else if (last >= 2 && last <= 4) word = "отправления";
      }
    }
    return `Выбрано ${n} ${word}`;
  }

  function updateBottomBar() {
    const bar = document.getElementById("ozonFbsBottomBar");
    const label = document.getElementById("ozonFbsSelectedLabel");
    const packActions = document.getElementById("ozonFbsBottomPackagingActions");
    const deliverActions = document.getElementById("ozonFbsBottomDeliveringActions");
    const addBtn = document.getElementById("ozonFbsAddToSupplyBtn");
    const n = state.selected.size;
    // Packaging postings: new / add-to-existing supply.
    // Delivering supplies: move selected supplies back to awaiting_deliver.
    const isPackaging = state.tab === "awaiting_packaging" && !isSuppliesTab();
    const isDeliveringSupplies = isDeliveringSuppliesTab();
    const showBar = n > 0 && (isPackaging || isDeliveringSupplies);
    if (label) label.textContent = selectedCountLabel(n);
    if (packActions) packActions.classList.toggle("hidden", !isPackaging);
    if (deliverActions) deliverActions.classList.toggle("hidden", !isDeliveringSupplies);
    if (addBtn) {
      const openSupplies = Number((state.counts && state.counts.open_supplies) || 0);
      addBtn.classList.toggle("hidden", !(isPackaging && n > 0 && openSupplies > 0));
    }
    if (bar) bar.classList.toggle("hidden", !showBar);
  }

  function clearSelection() {
    state.selected.clear();
    document.querySelectorAll("#ozonFbsOrdersTable .wb-fbs-row-cb").forEach((cb) => {
      cb.checked = false;
    });
    syncSelectAll();
    updateBottomBar();
  }

  function syncTableMode() {
    const supplies = isSuppliesTab();
    const nextMode = supplies
      ? (isDeliveringSuppliesTab() ? "supplies-delivering" : "supplies-awaiting")
      : (state.lookupMode ? "orders-lookup" : "orders");
    const modeChanged = state.viewMode !== nextMode;
    state.viewMode = nextMode;
    const table = document.getElementById("ozonFbsOrdersTable");
    const colgroup = document.getElementById("ozonFbsColgroup");
    const thead = table?.querySelector("thead tr");
    const search = document.getElementById("ozonFbsSearchFilter");
    if (table) {
      table.classList.toggle("wb-fbs-table--supplies", supplies);
      table.classList.toggle("wb-fbs-table--assembly", supplies);
    }
    if (search) {
      search.placeholder = supplies
        ? "Поиск по поставке, складу или номеру отправления…"
        : "Поиск по отправлению, артикулу, ШК…";
    }
    if (!colgroup || !thead) return;
    if (!modeChanged && colgroup.children.length) return;
    if (supplies) {
      const canRename = !isDeliveringSuppliesTab();
      colgroup.innerHTML = `
        <col data-fixed="1" class="wb-fbs-col-check" style="width:40px" />
        <col data-col="0" class="wb-fbs-col-supply" style="width:${canRename ? "26%" : "28%"}" />
        <col data-col="1" class="wb-fbs-col-qr" style="width:16%" />
        <col data-col="2" class="wb-fbs-col-orders" style="width:14%" />
        <col data-col="3" class="wb-fbs-col-status" style="width:16%" />
        <col data-col="4" class="wb-fbs-col-wh" style="width:${canRename ? "22%" : "24%"}" />
        ${canRename ? '<col data-fixed="1" class="wb-fbs-col-act" style="width:48px" />' : ""}
      `;
      thead.innerHTML = `
        <th class="wb-fbs-th-check"><input type="checkbox" id="ozonFbsSelectAll" onchange="toggleSelectAllOzonFbs(this.checked)" title="Выбрать все на странице" /></th>
        <th data-col="0">Поставка</th>
        <th data-col="1">ID поставки</th>
        <th data-col="2">Заказы</th>
        <th data-col="3">Этап сборки</th>
        <th data-col="4">Склад</th>
        ${canRename ? '<th class="wb-fbs-th-act"></th>' : ""}
      `;
    } else {
      const showAct = !!state.lookupMode;
      colgroup.innerHTML = `
        <col data-fixed="1" class="wb-fbs-col-check" style="width:40px" />
        <col data-col="0" class="wb-fbs-col-order" />
        <col data-col="1" class="wb-fbs-col-product" />
        <col data-col="2" class="wb-fbs-col-wh" />
        ${showAct ? '<col data-fixed="1" class="wb-fbs-col-act" style="width:48px" />' : ""}
      `;
      thead.innerHTML = `
        <th class="wb-fbs-th-check"><input type="checkbox" id="ozonFbsSelectAll" onchange="toggleSelectAllOzonFbs(this.checked)" title="Выбрать все на странице" /></th>
        <th data-col="0">Отправление<span class="col-resize-handle"></span></th>
        <th data-col="1">Товар<span class="col-resize-handle"></span></th>
        <th data-col="2">Склад<span class="col-resize-handle"></span></th>
        ${showAct ? '<th class="wb-fbs-th-act"></th>' : ""}
      `;
      initColumnResizer();
    }
  }

  function _ozonFbsRenameMenuIconHtml() {
    return `<span class="wb-fbs-menu-ico" aria-hidden="true">
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M11.5 3.5l3 3L6.75 14.25H3.75v-3L11.5 3.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" fill="none"/>
        <path d="M10.25 4.75l3 3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
      </svg>
    </span>`;
  }

  function _ozonFbsSupplyRowActionsHtml(supplyId) {
    const sid = String(supplyId || "").trim();
    if (!sid || isDeliveringSuppliesTab()) return "";
    const safeKey = _ozonFbsPostingMenuKey(`s_${sid}`);
    return `<div class="wb-fbs-row-menu-wrap" id="ozonFbsRowMenuWrap_${safeKey}">
      <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
              onclick="toggleOzonFbsRowMenu(event, '${esc(safeKey)}')" aria-haspopup="menu">⋮</button>
      <div id="ozonFbsRowMenu_${safeKey}" class="wb-fbs-row-menu" data-supply-id="${esc(sid)}" role="menu">
        <button type="button" class="wb-fbs-row-menu-item" role="menuitem"
                onclick="openOzonFbsRenameSupplyModal('${esc(sid)}')">
          ${_ozonFbsRenameMenuIconHtml()}
          Переименовать поставку
        </button>
      </div>
    </div>`;
  }

  function openOzonFbsRenameSupplyModal(supplyId) {
    closeOzonFbsRowMenus();
    const sid = String(supplyId || "").trim();
    if (!sid || !state.sourceId || isDeliveringSuppliesTab()) return;
    const row = state.items.find((x) => String(x.supply_id || "").trim() === sid);
    const detailName = (
      supplyDetailState.supply && String(supplyDetailState.supply.supply_id || "") === sid
    )
      ? String(supplyDetailState.supply.name || "").trim()
      : "";
    const input = document.getElementById("ozonFbsRenameSupplyInput");
    const err = document.getElementById("ozonFbsRenameSupplyError");
    const saveBtn = document.getElementById("ozonFbsRenameSupplySaveBtn");
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
    if (saveBtn) saveBtn.disabled = false;
    if (input) {
      input.value = detailName || String(row?.name || "").trim();
      input.dataset.supplyId = sid;
      input.onkeydown = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          submitOzonFbsRenameSupply();
        } else if (ev.key === "Escape") {
          ev.preventDefault();
          closeOzonFbsRenameSupplyModal();
        }
      };
    }
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsRenameSupplyModal", true);
    } else {
      document.getElementById("ozonFbsRenameSupplyModal")?.classList.remove("hidden");
    }
    setTimeout(() => {
      input?.focus();
      input?.select();
    }, 0);
  }

  function closeOzonFbsRenameSupplyModal() {
    const input = document.getElementById("ozonFbsRenameSupplyInput");
    if (input) input.dataset.supplyId = "";
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsRenameSupplyModal", false);
    } else {
      document.getElementById("ozonFbsRenameSupplyModal")?.classList.add("hidden");
    }
  }

  async function submitOzonFbsRenameSupply() {
    const input = document.getElementById("ozonFbsRenameSupplyInput");
    const err = document.getElementById("ozonFbsRenameSupplyError");
    const saveBtn = document.getElementById("ozonFbsRenameSupplySaveBtn");
    const sid = String(input?.dataset.supplyId || "").trim();
    const name = String(input?.value || "").trim();
    if (!sid || !state.sourceId) return;
    if (!name) {
      if (err) {
        err.hidden = false;
        err.textContent = "Укажите название поставки";
      }
      input?.focus();
      return;
    }
    if (name.length > 128) {
      if (err) {
        err.hidden = false;
        err.textContent = "Название не длиннее 128 символов";
      }
      return;
    }
    if (saveBtn) saveBtn.disabled = true;
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
    try {
      const res = await fetch(`/api/ozon-fbs/supplies/${encodeURIComponent(sid)}`, {
        method: "PATCH",
        headers: jsonHeaders(),
        body: JSON.stringify({ source_id: state.sourceId, name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      const newName = String(data.name || name).trim();
      const row = state.items.find((x) => String(x.supply_id || "").trim() === sid);
      if (row) row.name = newName;
      if (supplyDetailState.supply && String(supplyDetailState.supply.supply_id || "") === sid) {
        supplyDetailState.supply.name = newName;
        const title = document.getElementById("ozonFbsSupplyDetailTitle");
        if (title) title.textContent = newName;
      }
      closeOzonFbsRenameSupplyModal();
      if (isSuppliesTab()) renderSuppliesTable(state.items);
      if (data.split) {
        const kept = String(data.delivering_name || "").trim();
        const n = Number(data.delivering_count || 0);
        showSyncInfo(
          kept
            ? `Поставка переименована: ${newName}. В «Доставляются» осталось «${kept}» (${n} отпр.)`
            : `Поставка переименована: ${newName}. Отправления в доставке сохранены под старым названием`
        );
      } else {
        showSyncInfo(`Поставка переименована: ${newName}`);
      }
    } catch (e) {
      if (err) {
        err.hidden = false;
        err.textContent = String(e.message || e);
      } else {
        alert(String(e.message || e));
      }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function renderSuppliesTable(items) {
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (!tbody) return;
    state.items = Array.isArray(items) ? items : [];
    if (!state.items.length) {
      const emptyMsg = isDeliveringSuppliesTab()
        ? "Нет отправлений в доставке."
        : "Нет локальных поставок. Соберите заказы синей кнопкой на вкладке «Ожидают сборки».";
      tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">${esc(emptyMsg)}</td></tr>`;
      syncSelectAll();
      return;
    }
    const canRename = !isDeliveringSuppliesTab();
    const openBlocked = isSupplyOpenBlocked();
    const openTip = openBlocked ? supplyOpenBlockedTitle() : "";
    tbody.innerHTML = state.items.map((s) => {
      const sid = String(s.supply_id || "").trim();
      const checked = state.selected.has(sid) ? "checked" : "";
      const created = s.created_at || "";
      const createdMeta = created
        ? `<div class="wb-fbs-order-meta">от ${esc(fmtDate(created))}</div>`
        : "";
      const ordersCount = Number(s.order_count || 0);
      const status = String(s.status_label || "Сборка заказов");
      const actionsTd = canRename
        ? `<td class="wb-fbs-td-act">${_ozonFbsSupplyRowActionsHtml(sid)}</td>`
        : "";
      const nameCls = openBlocked
        ? "wb-fbs-supply-name is-link is-disabled"
        : "wb-fbs-supply-name is-link";
      const nameTitle = openBlocked ? ` title="${esc(openTip)}"` : "";
      const nameTab = openBlocked ? "" : ' tabindex="0"';
      const nameAria = openBlocked ? ' aria-disabled="true"' : ' role="button"';
      return `<tr>
        <td><input type="checkbox" class="wb-fbs-row-cb" data-supply-id="${esc(sid)}" ${checked} onchange="onOzonFbsCheckboxChange()" /></td>
        <td>
          <div class="${nameCls}" data-supply-open="1"${nameAria}${nameTab}${nameTitle}
               onclick="openOzonFbsSupplyDetailModal('${esc(sid)}')"
               onkeydown="if(event.key==='Enter')openOzonFbsSupplyDetailModal('${esc(sid)}')">${esc(s.name || ("Поставка " + sid))}</div>
          ${createdMeta}
          <div class="ozon-fbs-mobile-supply-id" title="ID поставки">${esc(sid)}</div>
          <div class="ozon-fbs-mobile-meta">${esc(s.warehouse_label || "—")}</div>
        </td>
        <td><div class="wb-fbs-supply-qr" title="${esc(sid)}">${esc(sid || "—")}</div></td>
        <td>
          <div class="wb-fbs-supply-orders">${esc(ordersCount)}</div>
          <div class="wb-fbs-order-meta">отправлений</div>
        </td>
        <td><span class="wb-fbs-supply-status is-assembly">${esc(status)}</span></td>
        <td>
          <div class="wb-fbs-wh-name" title="${esc(s.warehouse_label || "")}">${esc(s.warehouse_label || "—")}</div>
        </td>
        ${actionsTd}
      </tr>`;
    }).join("");
    syncSelectAll();
    updateBottomBar();
  }

  function productCompositionHtml(row) {
    const units = Math.max(0, Number(row?.unit_count || row?.quantity || 0) || 0);
    const lines = Array.isArray(row?.products_brief) ? row.products_brief : [];
    const lineCount = Math.max(
      Number(row?.line_count || 0) || 0,
      lines.length
    );
    const badges = [];
    if (units > 1) {
      badges.push(
        `<span class="wb-fbs-badge qty" title="Единиц в отправлении">${esc(String(units))} шт.</span>`
      );
    }
    if (lineCount > 1) {
      badges.push(
        `<span class="wb-fbs-badge cargo" title="Разных товарных позиций">${esc(String(lineCount))} поз.</span>`
      );
    }
    const badgeHtml = badges.length
      ? `<div class="wb-fbs-badges wb-fbs-product-qty">${badges.join("")}</div>`
      : "";
    let extraHtml = "";
    if (lines.length > 1) {
      extraHtml =
        `<div class="wb-fbs-product-extra">` +
        lines
          .slice(1)
          .map((p) => {
            const offer = String(p.offer_id || "").trim();
            const sku = String(p.sku || "").trim();
            const art = offer || sku || "—";
            const q = Math.max(1, Number(p.quantity) || 1);
            const nm = String(p.name || art || "—").trim() || "—";
            const qtyBit = q > 1 ? ` ×${q}` : "";
            return `<div class="wb-fbs-product-extra-line" title="${esc(nm)}">+ ${esc(nm)}${esc(qtyBit)} <span class="wb-fbs-order-meta">Арт. ${esc(art)}</span></div>`;
          })
          .join("") +
        `</div>`;
    }
    return badgeHtml + extraHtml;
  }

  function _ozonFbsLookupRowActionsHtml(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn || !state.lookupMode) return "";
    const menuKey = _ozonFbsPostingMenuKey(`lookup_${pn}`);
    return `<td class="wb-fbs-sd-col-act">
      <div class="wb-fbs-row-menu-wrap" id="ozonFbsRowMenuWrap_${menuKey}">
        <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
                onclick="toggleOzonFbsRowMenu(event, '${menuKey}')" aria-haspopup="menu">⋮</button>
        <div id="ozonFbsRowMenu_${menuKey}" class="wb-fbs-row-menu" data-posting="${esc(pn)}" role="menu">
          <button type="button" class="wb-fbs-row-menu-item" role="menuitem"
                  onclick="openOzonFbsMovePostingModal('${esc(pn)}')">
            Переместить в поставку
          </button>
          <button type="button" class="wb-fbs-row-menu-item" role="menuitem"
                  data-ozon-action="print-sticker" data-posting="${esc(pn)}">
            Напечатать стикер
          </button>
        </div>
      </div>
    </td>`;
  }

  function renderTable(items) {
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (!tbody) return;
    state.items = Array.isArray(items) ? items : [];
    if (!state.items.length) {
      tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">Нет отправлений в этой вкладке</td></tr>`;
      syncSelectAll();
      return;
    }
    tbody.innerHTML = state.items.map((row) => {
      const pnRaw = String(row.posting_number || "").trim();
      const pn = esc(pnRaw);
      const checked = state.selected.has(pnRaw) ? "checked" : "";
      const created = row.created_at_ozon || row.in_process_at || "";
      const ago = agoLabel(created);
      const badges = [];
      if (ago) badges.push(`<span class="wb-fbs-badge time">${esc(ago)}</span>`);
      if (row.order_number) {
        badges.push(`<span class="wb-fbs-badge" title="Заказ">${esc(row.order_number)}</span>`);
      }
      const photo = row.product_photo
        ? `<img class="wb-fbs-product-photo" src="${esc(row.product_photo)}" alt="" width="144" height="144" loading="lazy">`
        : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
      const barcodes = Array.isArray(row.barcodes) ? row.barcodes : [];
      const barcodeHtml = barcodes.length
        ? `<div class="wb-fbs-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
            `<div class="wb-fbs-barcode">${esc(b)}</div>`
          ).join("")}</div>`
        : "";
      const offer = String(row.offer_id || "").trim();
      const sku = String(row.sku || "").trim();
      const productName = row.product_name_display || row.product_name || offer || "—";
      const composition = productCompositionHtml(row);
      const whLabel = row.warehouse_label || row.warehouse_name || "—";
      const whId = row.warehouse_id != null && String(row.warehouse_id).trim()
        ? String(row.warehouse_id).trim()
        : "";
      const actCell = _ozonFbsLookupRowActionsHtml(pnRaw);
      let exemplarBadge = "";
      if (state.tab === "awaiting_packaging" && !isSuppliesTab()) {
        const badge = String(row.pre_ship_exemplar_badge || "");
        if (badge === "needed") {
          exemplarBadge =
            `<button type="button" class="wb-fbs-badge ozon-exemplar-needed"`
            + ` onclick="openOzonFbsPackagingExemplarModal('${pn}')"`
            + ` title="Нужны КИЗ и ГТД до сборки (юрлицо)">⚠ Маркировка не добавлена</button>`;
        } else if (badge === "ok") {
          exemplarBadge =
            `<button type="button" class="wb-fbs-badge ozon-exemplar-ok"`
            + ` onclick="openOzonFbsPackagingExemplarModal('${pn}')"`
            + ` title="КИЗ и ГТД переданы в Ozon">Маркировка добавлена</button>`;
        }
      }
      return `<tr data-posting="${pn}">
      <td><input type="checkbox" class="wb-fbs-row-cb" data-posting="${pn}" ${checked} onchange="onOzonFbsCheckboxChange()" /></td>
      <td>
        <div class="wb-fbs-order-id">${formatOzonPostingNumberHtml(pnRaw)}</div>
        <div class="wb-fbs-order-meta">от ${esc(fmtDate(created))}</div>
        ${exemplarBadge}
        ${badges.length ? `<div class="wb-fbs-badges">${badges.join("")}</div>` : ""}
        ${whLabel && whLabel !== "—" ? `<div class="ozon-fbs-mobile-wh">${esc(whLabel)}${whId ? " · ID " + esc(whId) : ""}</div>` : ""}
      </td>
      <td>
        <div class="wb-fbs-product">
          ${photo}
          <div class="wb-fbs-product-text">
            <div class="wb-fbs-product-name" title="${esc(productName)}">${esc(productName)}</div>
            <div class="wb-fbs-product-sub">Арт. ${esc(offer || "—")}${sku ? " · SKU " + esc(sku) : ""}</div>
            ${composition}
            ${barcodeHtml}
          </div>
        </div>
      </td>
      <td>
        <div class="wb-fbs-wh-name" title="${esc(whLabel)}">${esc(whLabel)}</div>
        <div class="wb-fbs-order-meta">${whId ? "ID " + esc(whId) : ""}</div>
      </td>
      ${actCell}
    </tr>`;
    }).join("");
    syncSelectAll();
    updateBottomBar();
  }

  async function loadPostings(resetPage) {
    if (!canView()) return;
    if (resetPage) state.page = 1;
    clearLookupMode();
    syncTableMode();
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">Загрузка…</td></tr>`;
    if (!state.sourceId) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">Добавьте источник OZON ФБС в настройках</td></tr>`;
      return;
    }

    const suppliesMode = isSuppliesTab();
    const pnQuery = parsePostingNumberQuery(state.search);
    const params = new URLSearchParams({
      source_id: String(state.sourceId),
      tab: state.tab,
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    if (state.search && !suppliesMode && !pnQuery) params.set("search", state.search);
    const seq = ++state.loadSeq;

    try {
      // Full posting number → always /find (cross-tab + status refresh from Ozon).
      // Skipping the tab list avoids stale status when the row is already on this tab.
      if (pnQuery) {
        if (tbody) {
          tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">Ищем отправление ${esc(pnQuery)}…</td></tr>`;
        }
        const infoPending = document.getElementById("ozonFbsInfo");
        if (infoPending) infoPending.textContent = `Поиск отправления ${pnQuery}…`;
        const lookup = await lookupPostingByNumber(pnQuery, { seq });
        if (seq !== state.loadSeq) return;
        if (lookup && applyLookupResult(lookup, pnQuery)) return;
        state.items = [];
        state.total = 0;
        if (lookup?.counts) updateTabCounts(lookup.counts);
        syncTableMode();
        if (suppliesMode) renderSuppliesTable([]);
        else renderTable([]);
        syncPackagingActionButtons();
        const infoMiss = document.getElementById("ozonFbsInfo");
        if (infoMiss) {
          infoMiss.textContent = lookup?.message
            || `Отправление ${pnQuery} не найдено в локальной базе`;
        }
        const pageInfoMiss = document.getElementById("ozonFbsPageInfo");
        if (pageInfoMiss) pageInfoMiss.textContent = "1 / 1";
        const prevMiss = document.getElementById("ozonFbsPrevBtn");
        const nextMiss = document.getElementById("ozonFbsNextBtn");
        if (prevMiss) prevMiss.disabled = true;
        if (nextMiss) nextMiss.disabled = true;
        return;
      }

      const url = suppliesMode
        ? `/api/ozon-fbs/supplies?${params}`
        : `/api/ozon-fbs/postings?${params}`;
      const res = await fetch(url);
      const data = await res.json();
      if (seq !== state.loadSeq) return;
      if (!res.ok) throw new Error(detailText(data.detail) || "Ошибка загрузки");

      let items = data.items || [];
      if (suppliesMode && state.search) {
        const q = state.search.toLowerCase();
        items = items.filter((s) => {
          const hay = [
            s.name, s.supply_id, s.warehouse_label,
            ...(Array.isArray(s.posting_numbers) ? s.posting_numbers : []),
          ].map((x) => String(x || "").toLowerCase()).join(" ");
          return hay.includes(q);
        });
      }

      updateTabCounts(data.counts || {});

      state.total = suppliesMode ? items.length : Number(data.total || 0);
      if (suppliesMode) {
        const adopted = Number(data.adopted_orphans || 0);
        if (adopted > 0) {
          const created = Array.isArray(data.adopt_created_supplies)
            ? data.adopt_created_supplies
            : [];
          const names = created.map((s) => s.name || s.supply_id).filter(Boolean);
          const adoptMsg = isDeliveringSuppliesTab()
            ? (names.length
              ? `Оформлено ${adopted} отпр. без поставки → «${names.join("», «")}»`
              : `Оформлено ${adopted} отправлений без поставки в «Без локальной поставки»`)
            : (names.length
              ? `Оформлено ${adopted} отпр. без поставки → ${names.join(", ")}`
              : `Оформлено ${adopted} отправлений без поставки в локальные поставки`);
          showSyncInfo(adoptMsg);
        }
        renderSuppliesTable(items);
      } else {
        renderTable(items);
      }
      syncPackagingActionButtons();

      const info = document.getElementById("ozonFbsInfo");
      if (info) {
        info.textContent = suppliesMode
          ? `Поставок: ${state.total}`
          : `Всего: ${state.total}`;
      }
      const pageInfo = document.getElementById("ozonFbsPageInfo");
      const pager = document.querySelector("#section-ozon-fbs .supplies-pagination");
      if (suppliesMode) {
        if (pageInfo) pageInfo.textContent = "";
        if (pager) pager.style.display = "none";
      } else {
        if (pager) pager.style.display = "";
        const maxPage = Math.max(1, Math.ceil(state.total / state.pageSize) || 1);
        if (pageInfo) pageInfo.textContent = `Стр. ${state.page} / ${maxPage}`;
        const prev = document.getElementById("ozonFbsPrevBtn");
        const next = document.getElementById("ozonFbsNextBtn");
        if (prev) prev.disabled = state.page <= 1;
        if (next) next.disabled = state.page >= maxPage;
      }
    } catch (e) {
      if (seq !== state.loadSeq) return;
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
      }
    }
  }

  const COL_WIDTHS_PREFIX = "ozon_fbs_col_widths_v2";
  const DEFAULT_WIDTHS = [24, 56, 20];
  let colResizerInited = false;

  function colWidthsKey() {
    const email = String(document.querySelector(".sidebar-user-email")?.textContent || "")
      .trim()
      .toLowerCase();
    return email ? `${COL_WIDTHS_PREFIX}:${email}` : COL_WIDTHS_PREFIX;
  }

  function applyColWidths(widths) {
    const cols = Array.from(document.querySelectorAll("#ozonFbsColgroup col")).filter(
      (c) => !c.dataset.fixed
    );
    cols.forEach((col, i) => {
      if (widths[i] !== undefined) col.style.width = `${widths[i]}%`;
    });
  }

  function getColWidths() {
    const cols = Array.from(document.querySelectorAll("#ozonFbsColgroup col")).filter(
      (c) => !c.dataset.fixed
    );
    return cols.map((col, i) => parseFloat(col.style.width) || DEFAULT_WIDTHS[i] || 10);
  }

  function initColumnResizer() {
    const table = document.getElementById("ozonFbsOrdersTable");
    if (!table || isSuppliesTab()) return;

    let widths = DEFAULT_WIDTHS.slice();
    try {
      const saved = JSON.parse(localStorage.getItem(colWidthsKey()) || "null");
      if (Array.isArray(saved) && saved.length === widths.length) widths = saved;
      else if (Array.isArray(saved)) localStorage.removeItem(colWidthsKey());
    } catch (_) {
      /* ignore */
    }
    applyColWidths(widths);

    if (colResizerInited) return;
    colResizerInited = true;

    let startX = 0;
    let colIdx = 0;
    let startWidths = [];
    let activeHandle = null;

    function onMouseMove(e) {
      const tableEl = document.getElementById("ozonFbsOrdersTable");
      if (!tableEl || isSuppliesTab()) return;
      const tableW = tableEl.offsetWidth || 1;
      const deltaPct = ((e.clientX - startX) / tableW) * 100;
      const newWidths = startWidths.slice();
      const minPct = 8;
      const nextIdx = colIdx < newWidths.length - 1 ? colIdx + 1 : colIdx - 1;
      let newCur = Math.max(minPct, startWidths[colIdx] + deltaPct);
      let newNext = Math.max(minPct, startWidths[nextIdx] - deltaPct);
      if (newNext < minPct) {
        newCur = startWidths[colIdx] + (startWidths[nextIdx] - minPct);
        newNext = minPct;
      }
      newWidths[colIdx] = Math.round(newCur * 10) / 10;
      newWidths[nextIdx] = Math.round(newNext * 10) / 10;
      applyColWidths(newWidths);
    }

    function onMouseUp() {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      if (activeHandle) activeHandle.classList.remove("dragging");
      activeHandle = null;
      try {
        localStorage.setItem(colWidthsKey(), JSON.stringify(getColWidths()));
      } catch (_) {
        /* ignore */
      }
    }

    table.addEventListener("mousedown", (e) => {
      if (isSuppliesTab()) return;
      const handle = e.target?.closest?.(".col-resize-handle");
      if (!handle) return;
      e.preventDefault();
      e.stopPropagation();
      const th = handle.parentElement;
      colIdx = parseInt(th.getAttribute("data-col") || "0", 10);
      startX = e.clientX;
      startWidths = getColWidths();
      activeHandle = handle;
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      handle.classList.add("dragging");
    });
  }

  /** Generic % column resizer with per-user localStorage (modal tables). */
  function createOzonFbsModalColResizer({
    tableId,
    colgroupId,
    storagePrefix,
    defaultWidths,
  }) {
    let inited = false;
    const defaults = Array.isArray(defaultWidths) ? defaultWidths.slice() : [];

    function storageKey() {
      const email = String(document.querySelector(".sidebar-user-email")?.textContent || "")
        .trim()
        .toLowerCase();
      return email ? `${storagePrefix}:${email}` : storagePrefix;
    }

    function resizableCols() {
      return Array.from(
        document.querySelectorAll(`#${colgroupId} col`)
      ).filter((c) => !c.dataset.fixed);
    }

    function apply(widths) {
      resizableCols().forEach((col, i) => {
        if (widths[i] !== undefined) col.style.width = `${widths[i]}%`;
      });
    }

    function get() {
      return resizableCols().map(
        (col, i) => parseFloat(col.style.width) || defaults[i] || 10
      );
    }

    function restore() {
      let widths = defaults.slice();
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey()) || "null");
        if (Array.isArray(saved) && saved.length === widths.length) widths = saved;
        else if (Array.isArray(saved)) localStorage.removeItem(storageKey());
      } catch (_) {
        /* ignore */
      }
      apply(widths);
    }

    function init() {
      const table = document.getElementById(tableId);
      if (!table) return;
      restore();
      if (inited) return;
      inited = true;

      let startX = 0;
      let colIdx = 0;
      let startWidths = [];
      let activeHandle = null;

      function onMouseMove(e) {
        const tableEl = document.getElementById(tableId);
        if (!tableEl) return;
        const tableW = tableEl.offsetWidth || 1;
        const deltaPct = ((e.clientX - startX) / tableW) * 100;
        const newWidths = startWidths.slice();
        const minPct = 8;
        const nextIdx = colIdx < newWidths.length - 1 ? colIdx + 1 : colIdx - 1;
        let newCur = Math.max(minPct, startWidths[colIdx] + deltaPct);
        let newNext = Math.max(minPct, startWidths[nextIdx] - deltaPct);
        if (newNext < minPct) {
          newCur = startWidths[colIdx] + (startWidths[nextIdx] - minPct);
          newNext = minPct;
        }
        newWidths[colIdx] = Math.round(newCur * 10) / 10;
        newWidths[nextIdx] = Math.round(newNext * 10) / 10;
        apply(newWidths);
      }

      function onMouseUp() {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        if (activeHandle) activeHandle.classList.remove("dragging");
        activeHandle = null;
        try {
          localStorage.setItem(storageKey(), JSON.stringify(get()));
        } catch (_) {
          /* ignore */
        }
      }

      table.addEventListener("mousedown", (e) => {
        const handle = e.target?.closest?.(".col-resize-handle");
        if (!handle || !table.contains(handle)) return;
        e.preventDefault();
        e.stopPropagation();
        const th = handle.parentElement;
        colIdx = parseInt(th.getAttribute("data-col") || "0", 10);
        startX = e.clientX;
        startWidths = get();
        activeHandle = handle;
        document.addEventListener("mousemove", onMouseMove);
        document.addEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        handle.classList.add("dragging");
      });
    }

    return { init, restore };
  }

  const ozonFbsSupplyDetailColResizer = createOzonFbsModalColResizer({
    tableId: "ozonFbsSupplyDetailTable",
    colgroupId: "ozonFbsSupplyDetailColgroup",
    storagePrefix: "ozon_fbs_sd_col_widths_v1",
    defaultWidths: [32, 60],
  });
  const ozonFbsKizColResizer = createOzonFbsModalColResizer({
    tableId: "ozonFbsKizTable",
    colgroupId: "ozonFbsKizColgroup",
    storagePrefix: "ozon_fbs_kiz_col_widths_v1",
    defaultWidths: [22, 38, 34],
  });
  const ozonFbsPickColResizer = createOzonFbsModalColResizer({
    tableId: "ozonFbsPickTable",
    colgroupId: "ozonFbsPickColgroup",
    storagePrefix: "ozon_fbs_pick_col_widths_v1",
    defaultWidths: [24, 40, 36],
  });

  /* ── Split multi (without assemble) ── */

  function closeSplitResultModal() {
    document.getElementById("ozonFbsSplitResultModal")?.classList.add("hidden");
    const shouldRefresh = !!splitState.lastOk || Number(splitState.lastSingleAfter || 0) > 0;
    splitState.lastOk = false;
    splitState.lastSingleAfter = 0;
    if (shouldRefresh) {
      // Local refresh of awaiting_packaging only — no full Ozon sync.
      if (state.tab !== "awaiting_packaging") setTab("awaiting_packaging");
      else loadPostings(true);
    }
  }

  function showSplitResult(data) {
    const modal = document.getElementById("ozonFbsSplitResultModal");
    const title = document.getElementById("ozonFbsSplitResultTitle");
    const body = document.getElementById("ozonFbsSplitResultBody");
    if (!modal || !body) {
      alert(data?.message || "Готово");
      return;
    }
    const ok = !!data?.ok;
    const singleAfter = Number(data?.single_after || 0);
    splitState.lastOk = ok && !(data?.errors || []).length;
    splitState.lastSingleAfter = singleAfter;
    if (title) title.textContent = ok ? "Разделение завершено" : "Есть проблемы";
    const details = Array.isArray(data?.details) ? data.details : [];
    const errors = Array.isArray(data?.errors) ? data.errors : [];
    let html = `<p class="${ok ? "wb-fbs-collect-mgt-result-ok" : "wb-fbs-collect-mgt-result-err"}">${esc(data?.message || "")}</p>`;
    html += `<p>Было мультизаказов: ${esc(String(data?.multi_before ?? details.length))} · стало одинарных: ${esc(String(singleAfter))}</p>`;
    if (details.length) {
      html += "<ul>" + details.map((d) => {
        const from = d.posting_number || "";
        const to = Array.isArray(d.posting_numbers) ? d.posting_numbers : [];
        return `<li>${formatOzonPostingNumberHtml(from)} → ${to.map((x) => formatOzonPostingNumberHtml(x)).join(", ")}</li>`;
      }).join("") + "</ul>";
    }
    if (errors.length) {
      html += `<p class="wb-fbs-collect-mgt-result-err">Ошибки:</p><ul class="wb-fbs-collect-mgt-result-err">` +
        errors.map((e) => {
          if (typeof e === "string") return `<li>${esc(e)}</li>`;
          return `<li>${formatOzonPostingNumberHtml(e.posting_number || "")}: ${esc(e.error || "")}</li>`;
        }).join("") + "</ul>";
    }
    body.innerHTML = html;
    modal.classList.remove("hidden");
  }

  async function pollSplitStatus() {
    try {
      const res = await fetch("/api/ozon-fbs/split-multi/status");
      const st = await res.json().catch(() => ({}));
      const running = Boolean(st.in_progress);
      const done = Number(st.done || 0);
      const total = Number(st.total || 0);
      splitState.progressText =
        total > 0 ? `Разделение ${done}/${total}` : (st.message || "Разделение…");
      showSyncInfo(running ? splitState.progressText : String(st.message || ""));
      if (running) {
        splitState.busy = true;
        syncPackagingActionButtons();
        splitState.pollTimer = setTimeout(pollSplitStatus, 1000);
        return;
      }
      clearTimeout(splitState.pollTimer);
      splitState.pollTimer = null;
      splitState.busy = false;
      splitState.progressText = "";
      syncPackagingActionButtons();
      showSplitResult({
        ok: !!st?.ok && !(st?.errors || []).length,
        message: String(st?.message || ""),
        errors: Array.isArray(st?.errors) ? st.errors : [],
        details: Array.isArray(st?.details) ? st.details : [],
        multi_before: Number(st?.multi_before || 0),
        single_after: Number(st?.single_after || 0),
      });
    } catch (_e) {
      splitState.pollTimer = setTimeout(pollSplitStatus, 1500);
    }
  }

  async function splitMulti() {
    if (
      !state.sourceId ||
      state.syncBusy ||
      splitState.busy ||
      collectState.busy ||
      state.shipAllBusy
    ) {
      return;
    }
    if (multiAwaitingCount() <= 0) {
      alert("Нет мультизаказов в «Ожидают сборки»");
      return;
    }
    splitState.busy = true;
    splitState.progressText = "Подготовка…";
    syncPackagingActionButtons();
    showSyncInfo("Запуск разделения мультизаказов…");
    try {
      const res = await fetch("/api/ozon-fbs/split-multi/execute", {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ source_id: Number(state.sourceId) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Не удалось запустить разделение");
      showSyncInfo("Разделение запущено…");
      pollSplitStatus();
    } catch (e) {
      splitState.busy = false;
      splitState.progressText = "";
      syncPackagingActionButtons();
      const err = e.message || String(e);
      showSyncInfo(err, "error");
      alert(err);
    }
  }

  /* ── Packaging exemplar (КИЗ+ГТД before ship, юрлица) ── */

  const packagingExemplarState = {
    postingNumber: "",
    payload: null,
    busy: false,
    gtdManual: false,
    gtdLookupHint: "",
  };

  function closeOzonFbsPackagingExemplarModal() {
    if (packagingExemplarState.busy) return;
    document.getElementById("ozonFbsPackagingExemplarModal")?.classList.add("hidden");
    packagingExemplarState.postingNumber = "";
    packagingExemplarState.payload = null;
    packagingExemplarState.gtdManual = false;
    packagingExemplarState.gtdLookupHint = "";
  }

  function _packagingExemplarSetInfo(text, tone) {
    const el = document.getElementById("ozonFbsPackagingExemplarInfo");
    if (!el) return;
    const msg = String(text || "").trim();
    el.hidden = !msg;
    el.textContent = msg;
    el.classList.toggle("is-ok", tone === "ok");
    el.classList.toggle("is-error", tone === "error");
  }

  function _packagingExemplarRenderBody(data) {
    const body = document.getElementById("ozonFbsPackagingExemplarBody");
    const meta = document.getElementById("ozonFbsPackagingExemplarMeta");
    if (meta) {
      const pn = String(data.posting_number || "");
      const name = String(data.product_name || "");
      meta.innerHTML =
        `<div class="pn">${formatOzonPostingNumberHtml(pn)}</div>`
        + (name ? `<div class="name">${esc(name)}</div>` : "");
    }
    if (!body) return;
    const qty = Math.max(Number(data.quantity || 1) || 1, 1);
    const codes = Array.isArray(data.kiz_codes) ? data.kiz_codes.slice() : [];
    while (codes.length < qty) codes.push("");
    packagingExemplarState.payload = { ...data, kiz_codes: codes };
    const gtd = String(data.gtd_number || "");
    const readonly = packagingExemplarState.gtdManual ? "" : "readonly";
    let kizHtml = "";
    for (let i = 0; i < qty; i += 1) {
      kizHtml += `<div class="ozon-fbs-packaging-exemplar-kiz-row">
        <span class="idx">${i + 1}</span>
        <input type="text" id="ozonFbsPackagingKiz_${i}" autocomplete="off"
               value="${esc(codes[i] || "")}"
               placeholder="Сканируйте КИЗ"
               oninput="onOzonFbsPackagingExemplarKizInput(${i})" />
      </div>`;
    }
    const hint = packagingExemplarState.gtdLookupHint
      ? `<p class="ozon-fbs-packaging-exemplar-hint ${packagingExemplarState.gtdLookupHintTone || ""}">${esc(packagingExemplarState.gtdLookupHint)}</p>`
      : `<p class="ozon-fbs-packaging-exemplar-hint">ГТД подставится из базы по короткому КИ после скана. Если не найдена — включите ручной ввод.</p>`;
    body.innerHTML = `
      <div class="ozon-fbs-packaging-exemplar-field">
        <label>КИЗ (${qty})</label>
        <div class="ozon-fbs-packaging-exemplar-kiz-list">${kizHtml}</div>
      </div>
      <div class="ozon-fbs-packaging-exemplar-field">
        <label for="ozonFbsPackagingGtd">ГТД</label>
        <input type="text" id="ozonFbsPackagingGtd" autocomplete="off"
               value="${esc(gtd)}" ${readonly}
               placeholder="Номер ГТД" />
        <label class="ozon-fbs-packaging-exemplar-manual">
          <input type="checkbox" id="ozonFbsPackagingGtdManual"
                 ${packagingExemplarState.gtdManual ? "checked" : ""}
                 onchange="onOzonFbsPackagingExemplarManualGtd(this)" />
          Ввести ГТД вручную
        </label>
        ${hint}
      </div>`;
  }

  async function _packagingExemplarLookupGtd(fromIdx) {
    if (packagingExemplarState.gtdManual) return;
    const input = document.getElementById(`ozonFbsPackagingKiz_${fromIdx}`);
    const raw = String(input?.value || "").trim();
    if (!raw || raw.length < 16) return;
    try {
      const res = await fetch(
        `/api/supply-gtd/lookup?kiz=${encodeURIComponent(raw)}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      const gtdInput = document.getElementById("ozonFbsPackagingGtd");
      if (data.found && data.item && data.item.gtd_number) {
        const num = String(data.item.gtd_number || "");
        if (gtdInput) gtdInput.value = num;
        if (packagingExemplarState.payload) {
          packagingExemplarState.payload.gtd_number = num;
        }
        packagingExemplarState.gtdLookupHint = `Найдена ГТД ${num}`;
        packagingExemplarState.gtdLookupHintTone = "is-ok";
      } else {
        packagingExemplarState.gtdLookupHint =
          String(data.message || "КИЗ не найден в базе ГТД — включите ручной ввод");
        packagingExemplarState.gtdLookupHintTone = "is-warn";
      }
      const hintEl = document.querySelector(
        "#ozonFbsPackagingExemplarBody .ozon-fbs-packaging-exemplar-hint"
      );
      if (hintEl) {
        hintEl.textContent = packagingExemplarState.gtdLookupHint;
        hintEl.classList.toggle("is-ok", packagingExemplarState.gtdLookupHintTone === "is-ok");
        hintEl.classList.toggle("is-warn", packagingExemplarState.gtdLookupHintTone === "is-warn");
      }
    } catch (_e) {
      /* ignore lookup errors */
    }
  }

  function onOzonFbsPackagingExemplarKizInput(idx) {
    const input = document.getElementById(`ozonFbsPackagingKiz_${idx}`);
    if (!input || !packagingExemplarState.payload) return;
    const codes = Array.isArray(packagingExemplarState.payload.kiz_codes)
      ? packagingExemplarState.payload.kiz_codes
      : [];
    codes[idx] = String(input.value || "");
    packagingExemplarState.payload.kiz_codes = codes;
    // Debounced lookup on longer scans.
    clearTimeout(onOzonFbsPackagingExemplarKizInput._t);
    onOzonFbsPackagingExemplarKizInput._t = setTimeout(() => {
      _packagingExemplarLookupGtd(idx);
    }, 280);
  }

  function onOzonFbsPackagingExemplarManualGtd(el) {
    packagingExemplarState.gtdManual = !!(el && el.checked);
    const gtdInput = document.getElementById("ozonFbsPackagingGtd");
    if (gtdInput) {
      if (packagingExemplarState.gtdManual) {
        gtdInput.removeAttribute("readonly");
        gtdInput.focus();
      } else {
        gtdInput.setAttribute("readonly", "readonly");
      }
    }
  }

  async function openOzonFbsPackagingExemplarModal(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn || !state.sourceId) return;
    const modal = document.getElementById("ozonFbsPackagingExemplarModal");
    if (!modal) return;
    packagingExemplarState.postingNumber = pn;
    packagingExemplarState.gtdManual = false;
    packagingExemplarState.gtdLookupHint = "";
    packagingExemplarState.payload = null;
    _packagingExemplarSetInfo("Загрузка…");
    const body = document.getElementById("ozonFbsPackagingExemplarBody");
    if (body) body.innerHTML = "";
    const meta = document.getElementById("ozonFbsPackagingExemplarMeta");
    if (meta) meta.innerHTML = "";
    modal.classList.remove("hidden");
    const saveBtn = document.getElementById("ozonFbsPackagingExemplarSaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    try {
      const res = await fetch(
        `/api/ozon-fbs/postings/${encodeURIComponent(pn)}/packaging-exemplar`
        + `?source_id=${encodeURIComponent(state.sourceId)}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(detailText(data.detail) || "Не удалось открыть маркировку");
      }
      packagingExemplarState.gtdManual = false;
      _packagingExemplarRenderBody(data);
      _packagingExemplarSetInfo("");
      if (saveBtn) saveBtn.disabled = false;
      const first = document.getElementById("ozonFbsPackagingKiz_0");
      if (first) first.focus();
    } catch (e) {
      _packagingExemplarSetInfo(e.message || String(e), "error");
      if (saveBtn) saveBtn.disabled = true;
    }
  }

  async function saveOzonFbsPackagingExemplar() {
    const pn = packagingExemplarState.postingNumber;
    if (!pn || !state.sourceId || packagingExemplarState.busy) return;
    const qty = Math.max(
      Number(packagingExemplarState.payload?.quantity || 1) || 1,
      1
    );
    const codes = [];
    for (let i = 0; i < qty; i += 1) {
      const el = document.getElementById(`ozonFbsPackagingKiz_${i}`);
      const v = String(el?.value || "").trim();
      if (v) codes.push(v);
    }
    if (codes.length < qty) {
      _packagingExemplarSetInfo(`Заполните все поля КИЗ (${qty})`, "error");
      return;
    }
    const gtd = String(
      document.getElementById("ozonFbsPackagingGtd")?.value || ""
    ).trim();
    if (!gtd) {
      _packagingExemplarSetInfo(
        "Укажите ГТД (из базы по КИЗ или вручную)",
        "error"
      );
      return;
    }
    const saveBtn = document.getElementById("ozonFbsPackagingExemplarSaveBtn");
    packagingExemplarState.busy = true;
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "Сохранение…";
    }
    _packagingExemplarSetInfo("Передаём в Ozon…");
    try {
      const res = await fetch(
        `/api/ozon-fbs/postings/${encodeURIComponent(pn)}/packaging-exemplar`
        + `?source_id=${encodeURIComponent(state.sourceId)}`,
        {
          method: "PUT",
          headers: jsonHeaders(),
          body: JSON.stringify({ kiz_codes: codes, gtd_number: gtd }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(detailText(data.detail) || "Ошибка сохранения");
      }
      _packagingExemplarSetInfo(data.message || "Сохранено", "ok");
      // Update row badge in current list without full reload when possible.
      const row = (state.items || []).find(
        (r) => String(r.posting_number || "") === pn
      );
      if (row) {
        row.pre_ship_exemplar_badge = "ok";
        row.marking_ozon_synced = true;
        row.marking_gtd_number = gtd;
        row.pre_ship_gtd_required = true;
        renderTable(state.items);
      } else {
        await loadPostings(false);
      }
      setTimeout(() => {
        packagingExemplarState.busy = false;
        closeOzonFbsPackagingExemplarModal();
      }, 600);
    } catch (e) {
      _packagingExemplarSetInfo(e.message || String(e), "error");
      packagingExemplarState.busy = false;
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = "Сохранить";
      }
    }
  }

  /* ── Collect (ship-all + local supplies) ── */

  function closeCollectModal() {
    if (collectState.busy) return;
    document.getElementById("ozonFbsCollectModal")?.classList.add("hidden");
    collectState.preview = null;
    collectState.sourceId = null;
    const err = document.getElementById("ozonFbsCollectErr");
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
  }

  function closeCollectResultModal() {
    document.getElementById("ozonFbsCollectResultModal")?.classList.add("hidden");
  }

  /** Ozon /v4/posting/fbs/ship common errors → operator text + what to do. */
  const OZON_SHIP_ERROR_HINTS = {
    EXEMPLAR_INFO_NOT_FILLED_COMPLETELY: {
      text: "Не заполнены данные экземпляров: нужен КИЗ («Честный ЗНАК») и/или ГТД.",
      action:
        "На вкладке «Ожидают сборки» нажмите «⚠ Маркировка не добавлена» у заказа, внесите КИЗ и ГТД, сохраните — затем повторите «Собрать все заказы».",
    },
    PRE_SHIP_EXEMPLAR_REQUIRED: {
      text: "Заказ юрлица пропущен: КИЗ/ГТД ещё не переданы в Ozon.",
      action:
        "Откройте бейдж «⚠ Маркировка не добавлена» у отправления, сохраните КИЗ и ГТД, затем соберите снова.",
    },
    EXEMPLAR_INFO_ALREADY_DEFINED: {
      text: "Данные экземпляров по этому заказу уже переданы в Ozon.",
      action: "Повторно вводить КИЗ не нужно. Обновите список (синхронизация) и при необходимости соберите снова.",
    },
    MANDATORY_MARK_REDUNDANT: {
      text: "Для этого товара код маркировки передавать не нужно.",
      action: "Уберите лишний КИЗ у отправления и повторите сборку.",
    },
    GTD_MUST_BE_SPECIFIED_FOR_PRODUCT_COUNTRY: {
      text: "Не указан номер ГТД для товара.",
      action: "В модалке маркировки на сборке укажите ГТД. Если декларации нет в базе — включите ручной ввод.",
    },
    GTD_IS_REQUIRED_ONLY_FOR_LEGAL_CUSTOMER: {
      text: "ГТД для этого заказа передавать не нужно (покупатель не юрлицо).",
      action: "Уберите ГТД у отправления и повторите сборку.",
    },
    POSTING_NOT_FOUND: {
      text: "Отправления нет в кабинете Ozon.",
      action: "Запустите синхронизацию. Если заказ исчез — он отменён или удалён в Ozon.",
    },
    POSTING_ALREADY_CANCELLED: {
      text: "Заказ уже отменён в Ozon.",
      action: "Собирать его не нужно. Обновите список синхронизацией.",
    },
    POSTING_ALREADY_SHIPPED: {
      text: "Заказ уже собран в Ozon.",
      action: "Синхронизируйте раздел — отправление должно появиться в «Ожидают отгрузки».",
    },
    HAS_INCORRECT_STATUS: {
      text: "У заказа неподходящий статус для сборки.",
      action: "Синхронизируйте раздел и соберите только отправления из «Ожидают сборки».",
    },
    HAS_INCORRECT_PRODUCT_QUANTITY: {
      text: "Неверное количество товара или SKU в запросе сборки.",
      action: "Синхронизируйте заказ и повторите сборку. Если ошибка останется — проверьте состав заказа в кабинете Ozon.",
    },
    UNKNOWN_PRODUCT_DEFINED: {
      text: "Указан неверный идентификатор товара (SKU Ozon).",
      action: "Синхронизируйте заказы. Если ошибка повторяется — проверьте карточку товара в кабинете Ozon.",
    },
    UNKNOW_PRODUCT: {
      text: "Указан неверный идентификатор товара (SKU Ozon).",
      action: "Синхронизируйте заказы. Если ошибка повторяется — проверьте карточку товара в кабинете Ozon.",
    },
    SHIP_FBP_POSTINGS_IS_FORBIDDEN: {
      text: "Это отправление FBP — сборка FBS для него не нужна.",
      action: "Пропустите этот заказ. При необходимости обновите список синхронизацией.",
    },
    TRANSITION_IS_NOT_POSSIBLE: {
      text: "Нельзя перевести заказ в следующий статус (неверный порядок статусов).",
      action: "Синхронизируйте раздел и проверьте статус заказа в кабинете Ozon.",
    },
    HAS_INCORRECT_TPL_INTEGRATION_TYPE: {
      text: "Нельзя менять статус: доставка через интегрированную службу (rFBS).",
      action: "С этим заказом работайте по правилам rFBS в кабинете Ozon.",
    },
    SHIP_NOT_AVAILABLE: {
      text: "Сборка недоступна: Ozon ещё не принял данные экземпляров.",
      action: "Проверьте маркировку (КИЗ/ГТД) на сборке, подождите немного и повторите «Собрать все заказы».",
    },
  };

  function extractOzonApiErrorCode(raw) {
    const s = String(raw || "");
    if (!s) return "";
    const fromJson = s.match(/"message"\s*:\s*"([^"]+)"/i);
    if (fromJson) {
      let code = String(fromJson[1] || "").trim().toUpperCase().replace(/\s+/g, "_");
      if (code === "UNKNOWN_PRODUCT" || code === "UNKNOW_PRODUCT") {
        return "UNKNOWN_PRODUCT_DEFINED";
      }
      if (OZON_SHIP_ERROR_HINTS[code]) return code;
      const keys = Object.keys(OZON_SHIP_ERROR_HINTS).sort((a, b) => b.length - a.length);
      for (const k of keys) {
        if (code.includes(k)) return k;
      }
    }
    const upper = s.toUpperCase();
    const keys = Object.keys(OZON_SHIP_ERROR_HINTS).sort((a, b) => b.length - a.length);
    for (const k of keys) {
      if (upper.includes(k)) return k;
    }
    if (/UNKNOWN_PRODUCT|UNKNOW_PRODUCT/.test(upper)) return "UNKNOWN_PRODUCT_DEFINED";
    if (/SHIP_NOT_AVAILABLE|SHIP-NOT-AVAILABLE/.test(upper)) return "SHIP_NOT_AVAILABLE";
    return "";
  }

  function humanizeOzonCollectError(raw) {
    const textRaw = String(raw || "").trim();
    const code = extractOzonApiErrorCode(textRaw);
    const hint = code ? OZON_SHIP_ERROR_HINTS[code] : null;
    if (hint) {
      return { code, text: hint.text, action: hint.action, raw: textRaw };
    }
    const httpMatch = textRaw.match(/^Ozon HTTP\s+(\d+):\s*([\s\S]+)$/i);
    if (httpMatch) {
      let body = String(httpMatch[2] || "").trim();
      try {
        const parsed = JSON.parse(body);
        if (parsed && typeof parsed === "object" && parsed.message != null) {
          body = String(parsed.message);
        }
      } catch (_e) {
        /* keep body */
      }
      return {
        code: "",
        text: `Ошибка Ozon (HTTP ${httpMatch[1]}): ${body}`,
        action:
          "Проверьте статус отправления в кабинете Ozon, синхронизируйте раздел и повторите сборку.",
        raw: textRaw,
      };
    }
    if (/^ozon network error/i.test(textRaw)) {
      return {
        code: "",
        text: "Нет связи с Ozon при сборке.",
        action: "Проверьте интернет и повторите «Собрать все заказы».",
        raw: textRaw,
      };
    }
    return {
      code: "",
      text: textRaw || "Неизвестная ошибка",
      action: textRaw ? "" : "Повторите сборку или обратитесь в поддержку.",
      raw: textRaw,
    };
  }

  function formatCollectErrorItemHtml(err) {
    let posting = "";
    let raw = "";
    let forcedCode = "";
    if (typeof err === "string") {
      raw = err;
      const m = err.match(/^(\S+):\s*([\s\S]+)$/);
      if (m && /[-\d]/.test(m[1]) && /ozon|exemplar|posting|http|ошиб|пропущ/i.test(m[2])) {
        posting = m[1];
        raw = m[2];
      }
    } else if (err && typeof err === "object") {
      posting = String(err.posting_number || "").trim();
      raw = String(err.error || err.message || "").trim();
      forcedCode = String(err.code || "").trim().toUpperCase();
    }
    const h = forcedCode && OZON_SHIP_ERROR_HINTS[forcedCode]
      ? {
          code: forcedCode,
          text: OZON_SHIP_ERROR_HINTS[forcedCode].text,
          action: OZON_SHIP_ERROR_HINTS[forcedCode].action,
          raw,
        }
      : humanizeOzonCollectError(raw);
    const pnHtml = posting && posting !== "—" && posting !== "?"
      ? `${formatOzonPostingNumberHtml(posting)}: `
      : "";
    const tip = h.raw && h.raw !== h.text ? ` title="${esc(h.raw)}"` : "";
    let html = `<li class="ozon-fbs-collect-err-item"${tip}>`;
    html += `<div class="ozon-fbs-collect-err-main">${pnHtml}${esc(h.text)}</div>`;
    if (h.action) {
      html += `<div class="ozon-fbs-collect-err-action">Что сделать: ${esc(h.action)}</div>`;
    }
    html += "</li>";
    return html;
  }

  function showCollectResult(data) {
    const modal = document.getElementById("ozonFbsCollectResultModal");
    const title = document.getElementById("ozonFbsCollectResultTitle");
    const body = document.getElementById("ozonFbsCollectResultBody");
    if (!modal || !body) {
      alert(data?.message || "Готово");
      return;
    }
    const ok = !!data?.ok;
    if (title) title.textContent = ok ? "Готово" : "Есть проблемы";
    const errors = Array.isArray(data?.errors) ? data.errors : [];
    const groupLines = Array.isArray(data?.group_lines) ? data.group_lines : [];
    const created = Array.isArray(data?.created_supplies) ? data.created_supplies : [];
    let html = `<p class="${ok ? "wb-fbs-collect-mgt-result-ok" : "wb-fbs-collect-mgt-result-err"}">${esc(data?.message || "")}</p>`;
    if (groupLines.length) {
      html += "<ul>" + groupLines.map((g) => `<li>${esc(g)}</li>`).join("") + "</ul>";
    }
    if (created.length) {
      html += "<p>Созданы поставки:</p><ul>" + created.map((s) =>
        `<li>${esc(s.name || s.supply_id || "")}</li>`
      ).join("") + "</ul>";
    }
    if (errors.length) {
      html += `<p class="wb-fbs-collect-mgt-result-err">Ошибки:</p><ul class="wb-fbs-collect-mgt-result-err ozon-fbs-collect-err-list">` +
        errors.map((e) => formatCollectErrorItemHtml(e)).join("") + "</ul>";
    }
    body.innerHTML = html;
    modal.classList.remove("hidden");
  }

  function shipSplitPreviewNote(preview) {
    // Collect no longer splits on ship — multi must be split beforehand.
    const multi = Number(preview?.multi_posting_count || 0);
    if (multi <= 0 && !preview?.block_collect) return "";
    if (multi > 0 || preview?.block_collect) {
      return `Есть мультизаказы (${multi || "—"}) — сначала нажмите «Разделить мультизаказы».`;
    }
    return "";
  }

  function renderCollectModal(preview) {
    const body = document.getElementById("ozonFbsCollectBody");
    const lead = document.getElementById("ozonFbsCollectLead");
    const err = document.getElementById("ozonFbsCollectErr");
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
    const groups = Array.isArray(preview?.groups) ? preview.groups : [];
    const existing = new Set(
      (Array.isArray(preview?.existing_names) ? preview.existing_names : [])
        .map((x) => String(x || "").trim()).filter(Boolean)
    );
    if (lead) {
      const base = `Отправлений в «Ожидают сборки»: ${preview?.posting_count || preview?.mgt_count || 0}.`;
      const splitNote = shipSplitPreviewNote(preview);
      lead.textContent = splitNote ? `${base} ${splitNote}` : base;
    }
    if (!body) return;
    body.innerHTML = groups.map((g, idx) => {
      const gkey = String(g.group_key || `g${idx}`);
      const mode = String(g.mode || "create");
      const label = String(g.label || "Склад");
      const count = Number(g.order_count || 0);
      const metaParts = [`${count} отпр.`];
      let inner = "";
      if (mode === "create") {
        const name = String(g.suggested_name || "");
        const conflict = existing.has(name.trim());
        inner = `
          <div class="wb-fbs-collect-mgt-field">
            <label for="ozonFbsCollectName_${esc(gkey)}">Название новой поставки</label>
            <input type="text" id="ozonFbsCollectName_${esc(gkey)}" data-group-key="${esc(gkey)}"
                   value="${esc(name)}" autocomplete="off"
                   oninput="ozonFbsCollectNameInput(this)" />
            <p class="wb-fbs-collect-mgt-warn" id="ozonFbsCollectWarn_${esc(gkey)}" ${conflict ? "" : "hidden"}>
              Поставка с таким названием уже есть — измените название.
            </p>
          </div>`;
      } else if (mode === "choose") {
        const supplies = Array.isArray(g.compatible_supplies) ? g.compatible_supplies : [];
        inner = `
          <div class="wb-fbs-collect-mgt-field">
            <label>Выберите поставку</label>
            <div class="wb-fbs-collect-mgt-supplies">
              ${supplies.map((s, si) => {
                const sid = String(s.supply_id || "");
                const sname = String(s.name || sid);
                const meta = [
                  s.is_empty ? "пустая" : "открытая",
                  `${Number(s.orders_count || 0)} отпр.`,
                ].filter(Boolean).join(" · ");
                return `
                  <label class="wb-fbs-collect-mgt-supply">
                    <input type="radio" name="ozonFbsCollectSupply_${esc(gkey)}" value="${esc(sid)}" ${si === 0 ? "checked" : ""} />
                    <span>
                      <span class="wb-fbs-collect-mgt-supply-name">${esc(sname)}</span>
                      <span class="wb-fbs-collect-mgt-supply-meta">${esc(meta)}</span>
                    </span>
                  </label>`;
              }).join("")}
            </div>
          </div>`;
      } else {
        const sid = String(g.default_supply_id || "");
        const match = (Array.isArray(g.compatible_supplies) ? g.compatible_supplies : [])
          .find((s) => String(s.supply_id || "") === sid);
        const sname = match ? String(match.name || sid) : sid;
        inner = `<div class="wb-fbs-collect-mgt-auto">Будет добавлено в поставку «${esc(sname)}».</div>`;
      }
      return `
        <section class="wb-fbs-collect-mgt-group" data-group-key="${esc(gkey)}" data-mode="${esc(mode)}">
          <h4 class="wb-fbs-collect-mgt-group-title">${esc(label)}</h4>
          <p class="wb-fbs-collect-mgt-group-meta">${esc(metaParts.join(" · "))}</p>
          ${inner}
        </section>`;
    }).join("");
  }

  function collectNameInput(input) {
    if (!input) return;
    const preview = collectState.preview;
    const existing = new Set(
      (Array.isArray(preview?.existing_names) ? preview.existing_names : [])
        .map((x) => String(x || "").trim()).filter(Boolean)
    );
    const gkey = String(input.dataset.groupKey || input.id.replace(/^ozonFbsCollectName_/, ""));
    const warn = document.getElementById(`ozonFbsCollectWarn_${gkey}`);
    if (!warn) return;
    const name = String(input.value || "").trim();
    warn.hidden = !(name && existing.has(name));
  }

  function collectDecisions() {
    const preview = collectState.preview;
    const groups = Array.isArray(preview?.groups) ? preview.groups : [];
    const decisions = [];
    const errors = [];
    const existing = new Set(
      (Array.isArray(preview?.existing_names) ? preview.existing_names : [])
        .map((x) => String(x || "").trim()).filter(Boolean)
    );
    const usedNames = new Set();
    for (const g of groups) {
      const gkey = String(g.group_key || "");
      const mode = String(g.mode || "create");
      const label = g.label || "Склад";
      if (mode === "create") {
        const input = document.getElementById(`ozonFbsCollectName_${gkey}`);
        const name = String(input?.value || g.suggested_name || "").trim();
        if (!name) {
          errors.push(`${label}: укажите название поставки`);
          continue;
        }
        if (existing.has(name) || usedNames.has(name)) {
          errors.push(`${label}: поставка «${name}» уже есть — измените название`);
          continue;
        }
        usedNames.add(name);
        decisions.push({ group_key: gkey, action: "create", name });
      } else if (mode === "choose") {
        const checked = document.querySelector(`input[name="ozonFbsCollectSupply_${gkey}"]:checked`);
        const supplyId = String(checked?.value || "").trim();
        if (!supplyId) {
          errors.push(`${label}: выберите поставку`);
          continue;
        }
        decisions.push({ group_key: gkey, action: "choose", supply_id: supplyId });
      } else {
        decisions.push({
          group_key: gkey,
          action: "add",
          supply_id: String(g.default_supply_id || ""),
        });
      }
    }
    return { decisions, errors };
  }

  async function executeCollect(decisions, sourceId) {
    const sid = Number(sourceId || collectState.sourceId || state.sourceId || 0);
    if (!sid) throw new Error("Выберите источник");
    const res = await fetch("/api/ozon-fbs/ship-all/execute", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ source_id: sid, decisions }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(detailText(data.detail) || "Ошибка сборки");
    return data;
  }

  function _collectResultFromStatus(st) {
    return {
      ok: !!st?.ok && !(st?.errors || []).length,
      message: String(st?.message || ""),
      errors: Array.isArray(st?.errors) ? st.errors : [],
      group_lines: Array.isArray(st?.group_lines) ? st.group_lines : [],
      created_supplies: Array.isArray(st?.created_supplies) ? st.created_supplies : [],
      shipped: Number(st?.shipped || 0),
      failed: Number(st?.failed || 0),
      total: Number(st?.total || 0),
      goto_awaiting_deliver: !!st?.goto_awaiting_deliver,
    };
  }

  async function pollCollectStatus() {
    try {
      const res = await fetch("/api/ozon-fbs/ship-all/status");
      const st = await res.json().catch(() => ({}));
      const running = Boolean(st.in_progress);
      const done = Number(st.done || 0);
      const total = Number(st.total || 0);
      const msg = String(st.message || "");
      const progress =
        total > 0 ? `Сборка… ${done} из ${total}` : (msg || "Сборка…");
      showSyncInfo(running ? progress : msg);
      const btn = document.getElementById("ozonFbsShipAllBtn");
      if (btn && running) btn.textContent = total > 0 ? `Сборка ${done}/${total}` : "Сборка…";
      if (running) {
        collectState.busy = true;
        state.shipAllBusy = true;
        syncShipAllButton();
        collectState.pollTimer = setTimeout(pollCollectStatus, 1000);
        return;
      }
      clearTimeout(collectState.pollTimer);
      collectState.pollTimer = null;
      collectState.busy = false;
      state.shipAllBusy = false;
      syncShipAllButton();
      if (btn) btn.textContent = "Собрать все заказы";
      const data = _collectResultFromStatus(st);
      closeCollectModal();
      showCollectResult(data);
      if (data.goto_awaiting_deliver) setTab("awaiting_deliver");
      else await loadPostings(true);
    } catch (_e) {
      collectState.pollTimer = setTimeout(pollCollectStatus, 1500);
    }
  }

  async function shipAll() {
    if (
      !state.sourceId ||
      state.syncBusy ||
      state.shipAllBusy ||
      collectState.busy ||
      splitState.busy
    ) {
      return;
    }
    if (multiAwaitingCount() > 0) {
      alert("Сначала нужно разделить мультизаказы");
      return;
    }
    const n = Number(state.counts.awaiting_packaging || 0);
    if (n <= 0) {
      alert("Нет отправлений в «Ожидают сборки»");
      return;
    }
    const btn = document.getElementById("ozonFbsShipAllBtn");
    const confirmBtn = document.getElementById("ozonFbsCollectConfirmBtn");
    collectState.busy = true;
    state.shipAllBusy = true;
    collectState.sourceId = state.sourceId;
    syncShipAllButton();
    if (btn) btn.textContent = "Подготовка…";
    try {
      const res = await fetch(`/api/ozon-fbs/ship-all/preview?source_id=${encodeURIComponent(state.sourceId)}`);
      const preview = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(preview.detail) || "Не удалось подготовить сборку");
      if (preview.block_collect || preview.ok === false) {
        const msg = preview.message || "Сначала нужно разделить мультизаказы";
        alert(msg);
        await loadPostings(false);
        return;
      }
      if (!(preview.posting_count || preview.mgt_count)) {
        alert("Нет отправлений в «Ожидают сборки»");
        await loadPostings(false);
        return;
      }
      collectState.preview = preview;
      if (!preview.needs_modal) {
        if (btn) btn.textContent = "Сборка…";
        showSyncInfo("Запуск сборки…");
        const decisions = (preview.groups || []).map((g) => ({
          group_key: String(g.group_key || ""),
          action: "add",
          supply_id: String(g.default_supply_id || ""),
        }));
        await executeCollect(decisions, state.sourceId);
        showSyncInfo("Сборка запущена…");
        pollCollectStatus();
        return;
      }
      renderCollectModal(preview);
      document.getElementById("ozonFbsCollectModal")?.classList.remove("hidden");
      if (confirmBtn) confirmBtn.disabled = false;
      collectState.busy = false;
      state.shipAllBusy = false;
      if (btn) btn.textContent = "Собрать все заказы";
      syncShipAllButton();
    } catch (e) {
      collectState.sourceId = null;
      const err = e.message || String(e);
      showSyncInfo(err);
      alert(err);
      collectState.busy = false;
      state.shipAllBusy = false;
      if (btn) btn.textContent = "Собрать все заказы";
      syncShipAllButton();
    }
  }

  async function confirmCollect() {
    if (collectState.busy) return;
    if (!collectState.preview) return;
    const errEl = document.getElementById("ozonFbsCollectErr");
    const confirmBtn = document.getElementById("ozonFbsCollectConfirmBtn");
    const sourceId = collectState.sourceId || state.sourceId;
    const { decisions, errors } = collectDecisions();
    if (errors.length) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = errors.join("\n");
      }
      return;
    }
    collectState.busy = true;
    state.shipAllBusy = true;
    if (confirmBtn) confirmBtn.disabled = true;
    syncShipAllButton();
    showSyncInfo("Запуск сборки…");
    try {
      await executeCollect(decisions, sourceId);
      document.getElementById("ozonFbsCollectModal")?.classList.add("hidden");
      showSyncInfo("Сборка запущена…");
      pollCollectStatus();
    } catch (e) {
      const msg = e.message || String(e);
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = msg;
      } else {
        alert(msg);
      }
      collectState.busy = false;
      state.shipAllBusy = false;
      if (confirmBtn) confirmBtn.disabled = false;
      syncShipAllButton();
    }
  }

  /* ── Supply detail modal ── */

  function _ozonFbsClearRuLayoutGuard() {
    // Document-level key swallow — must clear even if marking UI was bypassed.
    try {
      if (typeof _wbFbsKizRuLayoutSwallowKeys === "function") {
        document.removeEventListener("keydown", _wbFbsKizRuLayoutSwallowKeys, true);
      }
    } catch (_e) {
      /* ignore */
    }
    if (typeof setModalVisibility === "function") {
      setModalVisibility("wbFbsKizRuLayoutModal", false);
    } else {
      document.getElementById("wbFbsKizRuLayoutModal")?.classList.add("hidden");
    }
    if (typeof wbFbsKizState === "object" && wbFbsKizState) {
      wbFbsKizState.ruLayoutFocusId = null;
      wbFbsKizState.ruLayoutPreserveValue = false;
      wbFbsKizState.ruLayoutOpenedAt = 0;
    }
  }

  function _ozonFbsPickModalIsOpen() {
    const modal = document.getElementById("ozonFbsPickVerifyModal");
    return !!(modal && !modal.classList.contains("hidden"));
  }

  function closeSupplyDetailModal() {
    // Nested marking first (async autosave) — same pattern as WB supply close.
    // Closing supply alone used to leave RU-layout swallow active → wedge "dead".
    if (typeof _ozonFbsKizModalIsOpen === "function" && _ozonFbsKizModalIsOpen()) {
      return Promise.resolve(closeOzonFbsKizModal()).then(() => closeSupplyDetailModal());
    }
    if (_ozonFbsPickModalIsOpen()) {
      closeOzonFbsPickVerifyModal();
    }
    _ozonFbsClearRuLayoutGuard();
    closeOzonFbsRowMenus();
    document.getElementById("ozonFbsSupplyDetailModal")?.classList.add("hidden");
    syncSupplyDetailReadOnlyMode(false);
    closePickingMenu();
    closeStickersMenu();
    supplyDetailState.supplyId = null;
    supplyDetailState.sourceId = null;
    supplyDetailState.supply = null;
    supplyDetailState.selected = new Set();
    supplyDetailState.postingTab = null;
    _ozonFbsSupplyDetailSetActionsReady(false);
  }

  function supplyDetailReady() {
    return Boolean(supplyDetailState.supplyId && supplyDetailState.sourceId);
  }

  /**
   * Disable supply-detail action buttons until orders are loaded.
   * Uses aria-disabled (not native disabled) so the hover tooltip still works.
   */
  function _ozonFbsSupplyDetailSetActionsReady(ready) {
    supplyDetailState.ordersReady = !!ready;
    const tip = "Дождитесь загрузки заказов";
    _OZON_FBS_DETAIL_ACTION_IDS.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (!ready) {
        if (el.dataset.waitTitleSaved === undefined) {
          el.dataset.waitTitleSaved = el.getAttribute("title") || "";
        }
        el.setAttribute("aria-disabled", "true");
        el.classList.add("is-wait-orders");
        el.setAttribute("title", tip);
        el.tabIndex = -1;
      } else {
        el.removeAttribute("aria-disabled");
        el.classList.remove("is-wait-orders");
        el.removeAttribute("tabindex");
        const saved = el.dataset.waitTitleSaved;
        if (saved !== undefined) {
          if (saved) el.setAttribute("title", saved);
          else el.removeAttribute("title");
          delete el.dataset.waitTitleSaved;
        }
      }
    });
    if (!ready) {
      closePickingMenu();
      closeStickersMenu();
    }
    _ozonFbsSyncPickVerifyBtn(supplyDetailState.supply?.orders || []);
  }

  function onSupplyDetailCheckboxChange() {
    document.querySelectorAll("#ozonFbsSupplyDetailTbody .wb-fbs-sd-cb").forEach((cb) => {
      const pn = String(cb.dataset.posting || "").trim();
      if (!pn) return;
      if (cb.checked) supplyDetailState.selected.add(pn);
      else supplyDetailState.selected.delete(pn);
    });
    syncSupplyDetailSelectAll();
  }

  function syncSupplyDetailSelectAll() {
    const selAll = document.getElementById("ozonFbsSupplyDetailSelectAll");
    if (!selAll) return;
    const ids = Array.from(
      document.querySelectorAll("#ozonFbsSupplyDetailTbody .wb-fbs-sd-cb")
    ).map((cb) => String(cb.dataset.posting || "").trim()).filter(Boolean);
    const allOn = ids.length > 0 && ids.every((id) => supplyDetailState.selected.has(id));
    const someOn = ids.some((id) => supplyDetailState.selected.has(id));
    selAll.checked = allOn;
    selAll.indeterminate = !allOn && someOn;
  }

  function toggleSelectAllSupplyDetail(checked) {
    document.querySelectorAll("#ozonFbsSupplyDetailTbody .wb-fbs-sd-cb").forEach((cb) => {
      cb.checked = !!checked;
      const pn = String(cb.dataset.posting || "").trim();
      if (!pn) return;
      if (checked) supplyDetailState.selected.add(pn);
      else supplyDetailState.selected.delete(pn);
    });
    const selAll = document.getElementById("ozonFbsSupplyDetailSelectAll");
    if (selAll) selAll.indeterminate = false;
  }

  function _ozonFbsPostingMenuKey(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return "x";
    return pn.replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function _ozonFbsRestoreRowMenu(menu) {
    if (!menu) return;
    menu.classList.remove("open");
    menu.style.top = "";
    menu.style.left = "";
    const wrapId = menu.dataset.wrapId;
    const wrap = wrapId ? document.getElementById(wrapId) : null;
    if (wrap && menu.parentElement !== wrap) wrap.appendChild(menu);
  }

  function closeOzonFbsRowMenus(exceptKey = null) {
    document.querySelectorAll(
      ".wb-fbs-row-menu.open[id^='ozonFbsRowMenu_'], "
      + ".wb-fbs-row-menu[data-ported='1'][id^='ozonFbsRowMenu_']"
    ).forEach((menu) => {
      const key = String(menu.id || "").replace(/^ozonFbsRowMenu_/, "");
      if (exceptKey != null && key === String(exceptKey) && menu.classList.contains("open")) {
        return;
      }
      menu.dataset.ported = "";
      _ozonFbsRestoreRowMenu(menu);
    });
  }

  function _ozonFbsPositionRowMenu(menu, anchorEl) {
    const rect = anchorEl.getBoundingClientRect();
    const menuW = Math.max(menu.offsetWidth || 220, 220);
    const menuH = menu.offsetHeight || 96;
    let left = rect.right - menuW;
    if (left < 8) left = 8;
    if (left + menuW > window.innerWidth - 8) left = Math.max(8, window.innerWidth - menuW - 8);
    let top = rect.bottom + 4;
    if (top + menuH > window.innerHeight - 8) {
      top = Math.max(8, rect.top - menuH - 4);
    }
    menu.style.top = `${Math.round(top)}px`;
    menu.style.left = `${Math.round(left)}px`;
  }

  function toggleOzonFbsRowMenu(event, menuKey) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    const key = String(menuKey || "").trim();
    const btn = event?.currentTarget || event?.target?.closest?.(".wb-fbs-row-menu-btn");
    const menu = document.getElementById(`ozonFbsRowMenu_${key}`);
    if (!menu || !btn) return;
    const willOpen = !menu.classList.contains("open");
    closeOzonFbsRowMenus(willOpen ? key : null);
    if (!willOpen) {
      menu.dataset.ported = "";
      _ozonFbsRestoreRowMenu(menu);
      return;
    }
    const wrap = menu.closest(".wb-fbs-row-menu-wrap") || menu.parentElement;
    if (wrap) {
      if (!wrap.id) wrap.id = `ozonFbsRowMenuWrap_${key}`;
      menu.dataset.wrapId = wrap.id;
    }
    document.body.appendChild(menu);
    menu.dataset.ported = "1";
    menu.classList.add("open");
    _ozonFbsPositionRowMenu(menu, btn);
    requestAnimationFrame(() => _ozonFbsPositionRowMenu(menu, btn));
  }

  async function openPrintPdf(url, popupBlockedMsg) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) {
      let detail = "";
      try {
        const data = await res.json();
        detail = detailText(data.detail);
      } catch (_) {
        detail = await res.text().catch(() => "");
      }
      throw new Error(detail || `Ошибка печати (${res.status})`);
    }
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const win = window.open(blobUrl, "_blank");
    if (!win) {
      URL.revokeObjectURL(blobUrl);
      throw new Error(popupBlockedMsg || "Разрешите всплывающие окна");
    }
    setTimeout(() => URL.revokeObjectURL(blobUrl), 120000);
  }

  function _ozonFbsLookupSupplyIdForPosting(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return "";
    if (
      state.lookupMode
      && state.lookupMeta
      && String(state.lookupMeta.posting_number || "").trim() === pn
    ) {
      const fromMeta = String(state.lookupMeta.supply_id || "").trim();
      if (fromMeta) return fromMeta;
    }
    const row = (state.items || []).find(
      (x) => String(x?.posting_number || "").trim() === pn
    );
    return String(row?.supply_id || "").trim();
  }

  function printOnePostingStickerFromDetail(event, postingNumber) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    closeOzonFbsRowMenus();
    const pn = String(postingNumber || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!pn || !sourceId) {
      alert("Не удалось определить отправление или источник OZON ФБС");
      return;
    }
    // Same HTML print flow as the supply «Стикеры» button (reliable in browsers).
    if (supplyDetailReady() && _ozonFbsSupplyActionsReady()) {
      openStickersPrint([pn]);
      return;
    }
    // Search/lookup kebab: if posting is already in a local supply, use the same
    // supply HTML stickers endpoint (soft-fail + missing headers) instead of the
    // raw PDF path that surfaces Ozon INVALID_ARGUMENT as a browser alert.
    const lookupSupplyId = _ozonFbsLookupSupplyIdForPosting(pn);
    if (lookupSupplyId) {
      const url =
        `/api/ozon-fbs/supplies/${encodeURIComponent(lookupSupplyId)}/stickers-print` +
        `?source_id=${sourceId}&order_ids=${encodeURIComponent(pn)}`;
      openPrintHtml(url, "Разрешите всплывающие окна для стикера")
        .catch((e) => alert(String(e.message || e)));
      return;
    }
    const url =
      `/api/ozon-fbs/postings/stickers-print?source_id=${sourceId}` +
      `&posting_numbers=${encodeURIComponent(pn)}`;
    openPrintPdf(url, "Разрешите всплывающие окна для стикера")
      .catch((e) => alert(String(e.message || e)));
  }

  function cancelBadgeHtml(row) {
    const label = String(row?.cancel_reason_label || "").trim();
    if (!label) return "";
    return `<div class="wb-fbs-cancel-reason" title="${esc(label)}">${esc(label)}</div>`;
  }

  function _ozonFbsRowIsCancelled(row) {
    if (!row) return false;
    if (row.cancelled) return true;
    return !!String(row.cancel_reason_label || "").trim();
  }

  function _ozonFbsActiveModalRows(rows) {
    return (rows || []).filter((r) => !_ozonFbsRowIsCancelled(r));
  }

  function renderSupplyDetail(data) {
    closeOzonFbsRowMenus();
    const supply = data || supplyDetailState.supply;
    if (!supply) return;
    if (data) supplyDetailState.supply = data;
    const readOnly = isSupplyDetailReadOnly();
    syncSupplyDetailReadOnlyMode(readOnly);
    const detailColspan = readOnly ? 2 : 4;
    const title = document.getElementById("ozonFbsSupplyDetailTitle");
    const wh = document.getElementById("ozonFbsSupplyDetailWarehouse");
    const meta = document.getElementById("ozonFbsSupplyDetailMeta");
    const tbody = document.getElementById("ozonFbsSupplyDetailTbody");
    const sid = String(supply.supply_id || "").trim();
    if (title) title.textContent = supply.name || (`Поставка ${sid}`);
    const renameBtn = document.getElementById("ozonFbsSupplyDetailRenameBtn");
    if (renameBtn) renameBtn.hidden = !!readOnly;
    if (wh) wh.textContent = String(supply.warehouse_label || "—").trim() || "—";
    if (meta) {
      meta.innerHTML = [
        `<span class="wb-fbs-sd-chip">Отправлений ${esc(supply.order_count || 0)}</span>`,
        sid ? `<span class="wb-fbs-sd-chip">ID ${esc(sid)}</span>` : "",
      ].filter(Boolean).join("");
    }
    const allOrdersRaw = Array.isArray(supply.orders) ? supply.orders : [];
    // Modal-only: oldest orders on top. Print endpoints keep their own order.
    const allOrders = sortSupplyDetailOrdersOldestFirst(allOrdersRaw);
    const kizSplit = document.getElementById("ozonFbsKizSplit");
    const kizBtn = document.getElementById("ozonFbsSupplyDetailKizBtn");
    const kizRefreshBtn = document.getElementById("ozonFbsSupplyDetailKizRefreshBtn");
    // Marking + Pick-verify stay available even when composition is locked (delivering).
    const needsKiz = allOrders.some((o) => o && o.kiz_required && !_ozonFbsRowIsCancelled(o));
    if (kizSplit) kizSplit.hidden = !allOrders.length;
    if (kizBtn) kizBtn.hidden = !allOrders.length;
    if (kizRefreshBtn) kizRefreshBtn.hidden = !needsKiz;
    if (!needsKiz) _ozonFbsKizSplitSetTone("");
    else _ozonFbsKizSplitSetTone(_ozonFbsKizToneFromSupply(supply));
    _ozonFbsSyncPickVerifyBtn(allOrders);
    const searchQ = String(document.getElementById("ozonFbsSupplyDetailSearchFilter")?.value || "").trim().toLowerCase();
    const orders = searchQ
      ? allOrders.filter((o) => {
          const hay = [
            o.posting_number, o.offer_id, o.sku, o.product_name, o.warehouse_label,
            ...(Array.isArray(o.barcodes) ? o.barcodes : []),
            ...(Array.isArray(o.products_brief)
              ? o.products_brief.flatMap((p) => [p.offer_id, p.sku, p.name])
              : []),
          ].map((x) => String(x || "").toLowerCase()).join(" ");
          return hay.includes(searchQ);
        })
      : allOrders;
    if (!tbody) return;
    if (!allOrders.length) {
      tbody.innerHTML = `<tr><td colspan="${detailColspan}" class="wb-fbs-empty">В поставке нет отправлений</td></tr>`;
      return;
    }
    if (!orders.length) {
      tbody.innerHTML = `<tr><td colspan="${detailColspan}" class="wb-fbs-empty">Нет отправлений по выбранному фильтру</td></tr>`;
      const selAllEmpty = document.getElementById("ozonFbsSupplyDetailSelectAll");
      if (selAllEmpty) {
        selAllEmpty.checked = false;
        selAllEmpty.indeterminate = false;
      }
      return;
    }
    tbody.innerHTML = orders.map((o) => {
      const pn = String(o.posting_number || "").trim();
      const checked = supplyDetailState.selected.has(pn) ? "checked" : "";
      const photo = o.product_photo
        ? `<img class="wb-fbs-product-photo" src="${esc(o.product_photo)}" alt="" width="72" height="72" loading="lazy">`
        : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
      const barcodes = Array.isArray(o.barcodes) ? o.barcodes : [];
      const barcodeHtml = barcodes.length
        ? `<div class="wb-fbs-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
            `<div class="wb-fbs-barcode">${esc(b)}</div>`
          ).join("")}</div>`
        : "";
      const offer = String(o.offer_id || "").trim();
      const sku = String(o.sku || "").trim();
      const pname = o.product_name || offer || "—";
      const composition = productCompositionHtml(o);
      const created = o.created_at_ozon || o.in_process_at || "";
      const ago = agoLabel(created);
      const badges = [];
      if (ago) badges.push(`<span class="wb-fbs-badge time">${esc(ago)}</span>`);
      const cancelLabel = String(o.cancel_reason_label || "").trim();
      const rowCls = cancelLabel ? "wb-fbs-sd-click-row is-cancelled" : "wb-fbs-sd-click-row";
      const menuKey = _ozonFbsPostingMenuKey(pn);
      const checkCell = readOnly
        ? ""
        : `<td><input type="checkbox" class="wb-fbs-sd-cb" data-posting="${esc(pn)}" ${checked}
                   onchange="onOzonFbsSupplyDetailCheckboxChange()" /></td>`;
      const actCell = readOnly
        ? ""
        : `<td class="wb-fbs-sd-col-act">
          <div class="wb-fbs-row-menu-wrap" id="ozonFbsRowMenuWrap_${menuKey}">
            <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
                    onclick="toggleOzonFbsRowMenu(event, '${menuKey}')" aria-haspopup="menu">⋮</button>
            <div id="ozonFbsRowMenu_${menuKey}" class="wb-fbs-row-menu" data-posting="${esc(pn)}" role="menu">
              <button type="button" class="wb-fbs-row-menu-item" role="menuitem"
                      data-ozon-action="print-sticker" data-posting="${esc(pn)}">
                Напечатать стикер
              </button>
            </div>
          </div>
        </td>`;
      return `<tr class="${rowCls}">
        ${checkCell}
        <td>
          <div class="wb-fbs-sd-order-id">${formatOzonPostingNumberHtml(pn)}</div>
          <div class="wb-fbs-order-meta">от ${esc(fmtDate(created))}</div>
          ${badges.length ? `<div class="wb-fbs-badges">${badges.join("")}</div>` : ""}
        </td>
        <td>
          <div class="wb-fbs-product">
            ${photo}
            <div class="wb-fbs-product-text">
              <div class="wb-fbs-product-name" title="${esc(pname)}">${esc(pname)}</div>
              <div class="wb-fbs-product-sub">Арт. ${esc(offer || "—")}${sku ? " · SKU " + esc(sku) : ""}</div>
              ${composition}
              ${barcodeHtml}
              ${cancelBadgeHtml(o)}
              ${kizBadgeHtml(o)}
            </div>
          </div>
        </td>
        ${actCell}
      </tr>`;
    }).join("");
    if (!readOnly) syncSupplyDetailSelectAll();
  }

  function _ozonFbsSupplyPostingTabParam() {
    const tab = String(supplyDetailState.postingTab || "").trim();
    return tab ? `&posting_tab=${encodeURIComponent(tab)}` : "";
  }

  function _ozonFbsAppendPostingTab(params) {
    const tab = String(supplyDetailState.postingTab || "").trim();
    if (tab && params && typeof params.set === "function") {
      params.set("posting_tab", tab);
    }
    return params;
  }

  async function openSupplyDetailModal(supplyId) {
    const sid = String(supplyId || "").trim();
    if (!sid || !state.sourceId) return;
    if (isSupplyOpenBlocked()) {
      alert(supplyOpenBlockedTitle());
      return;
    }
    supplyDetailState.supplyId = sid;
    supplyDetailState.sourceId = state.sourceId;
    supplyDetailState.selected = new Set();
    supplyDetailState.postingTab = isSuppliesTab() ? String(state.tab || "").trim() : null;
    _ozonFbsSupplyDetailSetActionsReady(false);
    _ozonFbsKizSplitSetTone("");
    const kizSplitOpen = document.getElementById("ozonFbsKizSplit");
    if (kizSplitOpen) kizSplitOpen.hidden = true;
    const modal = document.getElementById("ozonFbsSupplyDetailModal");
    const title = document.getElementById("ozonFbsSupplyDetailTitle");
    const tbody = document.getElementById("ozonFbsSupplyDetailTbody");
    const search = document.getElementById("ozonFbsSupplyDetailSearchFilter");
    if (search) search.value = "";
    if (title) title.textContent = "Загрузка…";
    const readOnly = isDeliveringSuppliesTab();
    syncSupplyDetailReadOnlyMode(readOnly);
    const detailColspan = readOnly ? 2 : 4;
    if (tbody) tbody.innerHTML = `<tr><td colspan="${detailColspan}" class="wb-fbs-empty">Загрузка…</td></tr>`;
    if (modal) modal.classList.remove("hidden");
    ozonFbsSupplyDetailColResizer.init();
    try {
      const tabParam = _ozonFbsSupplyPostingTabParam();
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/detail?source_id=${state.sourceId}${tabParam}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Не найдено");
      renderSupplyDetail(data);
      _ozonFbsSupplyDetailSetActionsReady(true);
    } catch (e) {
      _ozonFbsSupplyDetailSetActionsReady(false);
      if (title) title.textContent = "Ошибка";
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="${detailColspan}" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
      }
    }
  }

  function _ozonFbsCancelledSetInfo(text, kind) {
    const el = document.getElementById("ozonFbsCancelledOrdersInfo");
    if (!el) return;
    const msg = String(text || "").trim();
    el.hidden = !msg;
    el.textContent = msg;
    el.classList.toggle("is-ok", !!msg && kind === "ok");
  }

  function _ozonFbsCancelledMergeIntoDetail(rows) {
    const supply = supplyDetailState.supply;
    if (!supply || !Array.isArray(supply.orders) || !Array.isArray(rows)) return;
    const byPn = new Map();
    rows.forEach((row) => {
      const pn = String(row?.posting_number || "").trim();
      if (pn) byPn.set(pn, row);
    });
    if (!byPn.size) return;
    let changed = false;
    supply.orders.forEach((o) => {
      const pn = String(o?.posting_number || "").trim();
      const upd = byPn.get(pn);
      if (!upd) return;
      const label = String(upd.cancel_reason_label || "").trim();
      if (label) {
        o.cancel_reason_label = label;
        o.cancelled = true;
        changed = true;
      }
      if (upd.status) o.status = String(upd.status);
      if (upd.tab) o.tab = String(upd.tab);
    });
    if (changed) renderSupplyDetail(supply);
  }

  function renderOzonFbsCancelledOrdersTable() {
    const tbody = document.getElementById("ozonFbsCancelledOrdersTbody");
    if (!tbody) return;
    const rows = Array.isArray(ozonFbsCancelledState.rows) ? ozonFbsCancelledState.rows : [];
    if (!rows.length) {
      let emptyMsg = "Отменённых отправлений в поставке нет";
      if (ozonFbsCancelledState.loading) emptyMsg = "Проверяем статусы на Ozon…";
      else if (ozonFbsCancelledState.lastError) emptyMsg = "Не удалось проверить статусы";
      tbody.innerHTML = `<tr><td colspan="2" class="wb-fbs-empty">${esc(emptyMsg)}</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const pn = String(r.posting_number || "").trim();
      const photo = r.product_photo
        ? `<img class="wb-fbs-product-photo" src="${esc(r.product_photo)}" alt="" width="56" height="56" loading="lazy">`
        : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
      const offerArt = [r.offer_id ? `Арт. ${r.offer_id}` : "", r.sku ? `SKU ${r.sku}` : ""]
        .filter(Boolean)
        .join(" · ");
      const barcodes = Array.isArray(r.barcodes) ? r.barcodes : [];
      const barcodeHtml = barcodes.length
        ? `<div class="wb-fbs-kiz-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
            `<div class="wb-fbs-kiz-barcode">${esc(b)}</div>`
          ).join("")}</div>`
        : "";
      return `<tr class="wb-fbs-kiz-row" data-posting="${esc(pn)}">
        <td>
          <div class="wb-fbs-kiz-order-id">${formatOzonPostingNumberHtml(pn)}</div>
          <div class="wb-fbs-kiz-order-date">от ${esc(r.created_date || "—")}</div>
        </td>
        <td>
          <div class="wb-fbs-product">
            ${photo}
            <div class="wb-fbs-product-text">
              <div class="wb-fbs-product-name" title="${esc(r.product_name || r.offer_id || "")}">${esc(r.product_name || r.offer_id || "—")}</div>
              <div class="wb-fbs-product-sub">${esc(offerArt || "—")}</div>
              ${productCompositionHtml(r)}
              ${barcodeHtml}
              ${cancelBadgeHtml(r)}
            </div>
          </div>
        </td>
      </tr>`;
    }).join("");
  }

  async function refreshOzonFbsCancelledOrders() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || ozonFbsCancelledState.loading) return;
    const refreshGen = Number(ozonFbsCancelledState.refreshGen || 0) + 1;
    ozonFbsCancelledState.refreshGen = refreshGen;
    ozonFbsCancelledState.loading = true;
    ozonFbsCancelledState.lastError = "";
    const btn = document.getElementById("ozonFbsCancelledOrdersRefreshBtn");
    if (btn) btn.disabled = true;
    _ozonFbsCancelledSetInfo("");
    if (!ozonFbsCancelledState.rows.length) {
      renderOzonFbsCancelledOrdersTable();
    }
    try {
      const merged = [];
      const seen = new Set();
      let offset = 0;
      let done = false;
      let postingCount = 0;
      let checkedTotal = 0;
      const allWarnings = [];
      while (!done) {
        if (ozonFbsCancelledState.refreshGen !== refreshGen) return;
        const params = new URLSearchParams({
          source_id: String(sourceId),
          check_offset: String(offset),
        });
        _ozonFbsAppendPostingTab(params);
        if (checkedTotal > 0 || offset > 0) {
          _ozonFbsCancelledSetInfo(
            `Проверка отменённых на Ozon… ${checkedTotal}/${postingCount || "?"}`,
            "ok"
          );
        }
        const res = await fetch(
          `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/cancelled?${params}`
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
          throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
        }
        if (ozonFbsCancelledState.refreshGen !== refreshGen) return;
        postingCount = Number(data.posting_count || postingCount || 0);
        checkedTotal += Number(data.checked || 0);
        const chunkRows = Array.isArray(data.rows) ? data.rows : [];
        for (const row of chunkRows) {
          const pn = String(row?.posting_number || "").trim();
          if (!pn || seen.has(pn)) continue;
          seen.add(pn);
          merged.push(row);
        }
        const warnings = Array.isArray(data.warnings) ? data.warnings : [];
        allWarnings.push(...warnings);
        done = data.done === true || Number(data.remaining || 0) <= 0;
        offset = Number(data.next_offset != null ? data.next_offset : offset + Number(data.checked || 0));
        if (!done && Number(data.checked || 0) <= 0) {
          done = true;
        }
        ozonFbsCancelledState.rows = merged.slice();
        renderOzonFbsCancelledOrdersTable();
        if (!done) {
          _ozonFbsCancelledSetInfo(
            `Проверка отменённых на Ozon… ${checkedTotal}/${postingCount}`,
            "ok"
          );
        }
      }
      if (ozonFbsCancelledState.refreshGen !== refreshGen) return;
      ozonFbsCancelledState.lastError = "";
      ozonFbsCancelledState.rows = merged;
      renderOzonFbsCancelledOrdersTable();
      _ozonFbsCancelledMergeIntoDetail(ozonFbsCancelledState.rows);
      if (allWarnings.length) {
        _ozonFbsCancelledSetInfo(
          `Часть отправлений проверена по локальным данным (${allWarnings.length})`,
          "ok"
        );
      } else {
        _ozonFbsCancelledSetInfo("");
      }
    } catch (e) {
      if (ozonFbsCancelledState.refreshGen !== refreshGen) return;
      const msg = String(e.message || e);
      ozonFbsCancelledState.lastError = msg;
      if (!ozonFbsCancelledState.rows.length) renderOzonFbsCancelledOrdersTable();
      _ozonFbsCancelledSetInfo(msg);
    } finally {
      if (ozonFbsCancelledState.refreshGen === refreshGen) {
        ozonFbsCancelledState.loading = false;
        if (btn) btn.disabled = false;
        if (!ozonFbsCancelledState.rows.length) renderOzonFbsCancelledOrdersTable();
      }
    }
  }

  function openOzonFbsCancelledOrdersModal() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) return;
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsCancelledOrdersModal", true);
    } else {
      document.getElementById("ozonFbsCancelledOrdersModal")?.classList.remove("hidden");
    }
    ozonFbsCancelledState.rows = [];
    ozonFbsCancelledState.lastError = "";
    ozonFbsCancelledState.loading = true;
    _ozonFbsCancelledSetInfo("");
    renderOzonFbsCancelledOrdersTable();
    ozonFbsCancelledState.loading = false;
    refreshOzonFbsCancelledOrders().catch(() => {});
  }

  function closeOzonFbsCancelledOrdersModal() {
    ozonFbsCancelledState.refreshGen = Number(ozonFbsCancelledState.refreshGen || 0) + 1;
    ozonFbsCancelledState.loading = false;
    ozonFbsCancelledState.lastError = "";
    ozonFbsCancelledState.rows = [];
    const btn = document.getElementById("ozonFbsCancelledOrdersRefreshBtn");
    if (btn) btn.disabled = false;
    _ozonFbsCancelledSetInfo("");
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsCancelledOrdersModal", false);
    } else {
      document.getElementById("ozonFbsCancelledOrdersModal")?.classList.add("hidden");
    }
  }

  async function openPrintHtml(url, popupBlockedMsg) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) {
      let detail = "";
      try {
        const data = await res.json();
        detail = detailText(data.detail);
      } catch (_) {
        detail = await res.text().catch(() => "");
      }
      throw new Error(detail || `Ошибка печати (${res.status})`);
    }
    const html = await res.text();
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const blobUrl = URL.createObjectURL(blob);
    const win = window.open(blobUrl, "_blank");
    if (!win) {
      URL.revokeObjectURL(blobUrl);
      throw new Error(popupBlockedMsg || "Разрешите всплывающие окна");
    }
    setTimeout(() => URL.revokeObjectURL(blobUrl), 120000);
    try { win.focus(); } catch (_e) { /* ignore */ }
    const missingCount = Number(res.headers.get("X-Feedpilot-Stickers-Missing-Count") || 0);
    if (missingCount > 0) {
      const expected = res.headers.get("X-Feedpilot-Stickers-Expected") || "?";
      const loaded = res.headers.get("X-Feedpilot-Stickers-Loaded") || "?";
      const missingRaw = String(res.headers.get("X-Feedpilot-Stickers-Missing") || "").trim();
      const reason = String(res.headers.get("X-Feedpilot-Stickers-Missing-Reason") || "").trim();
      const preview = missingRaw
        ? missingRaw.split(",").slice(0, 5).join(", ")
        : "";
      const suffix = missingCount > 5 ? ` … (+${missingCount - 5})` : "";
      const info = document.getElementById("ozonFbsSupplyDetailInfo");
      if (info) {
        const msg = Number(loaded) === 0
          ? (
            `Не удалось загрузить этикетки Ozon (${expected}). `
            + `Печать открыта в соседней вкладке.`
            + (preview ? ` Отправления: ${preview}${suffix}.` : "")
            + (reason ? ` ${reason}` : "")
          )
          : (
            `Стикеры: загружено ${loaded} из ${expected}. `
            + `Пропущено ${missingCount}`
            + (preview ? ` (${preview}${suffix})` : "")
            + `. Печать открыта в соседней вкладке.`
            + (reason ? ` ${reason}` : "")
          );
        info.hidden = false;
        info.textContent = msg;
        info.classList.toggle("is-ok", false);
        info.classList.toggle("is-warn", true);
      }
    }
  }

  function closePickingMenu() {
    const menu = document.getElementById("ozonFbsPickingMenu");
    const caret = document.getElementById("ozonFbsSupplyDetailPickingMenuBtn");
    if (menu) menu.hidden = true;
    if (caret) caret.setAttribute("aria-expanded", "false");
  }

  function togglePickingMenu(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (!_ozonFbsSupplyActionsReady()) return;
    closeStickersMenu();
    const menu = document.getElementById("ozonFbsPickingMenu");
    const caret = document.getElementById("ozonFbsSupplyDetailPickingMenuBtn");
    if (!menu || !caret) return;
    // Empty menu for now (no links) — still toggle for parity with WB caret UX.
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    caret.setAttribute("aria-expanded", willOpen ? "true" : "false");
  }

  function openPickingList() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) return;
    closePickingMenu();
    const btn = document.getElementById("ozonFbsSupplyDetailPickingBtn");
    const caret = document.getElementById("ozonFbsSupplyDetailPickingMenuBtn");
    if (btn) btn.disabled = true;
    if (caret) caret.disabled = true;
    const url =
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/picking-list` +
      `?source_id=${sourceId}${_ozonFbsSupplyPostingTabParam()}`;
    openPrintHtml(url, "Разрешите всплывающие окна для листа подбора")
      .catch((e) => alert(String(e.message || e)))
      .finally(() => {
        if (!_ozonFbsSupplyActionsReady()) return;
        if (btn) btn.disabled = false;
        if (caret) caret.disabled = false;
      });
  }

  function closeStickersMenu() {
    const menu = document.getElementById("ozonFbsStickersMenu");
    const caret = document.getElementById("ozonFbsSupplyDetailStickersMenuBtn");
    if (menu) menu.hidden = true;
    if (caret) caret.setAttribute("aria-expanded", "false");
  }

  function toggleStickersMenu(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (!_ozonFbsSupplyActionsReady()) return;
    closePickingMenu();
    const menu = document.getElementById("ozonFbsStickersMenu");
    const caret = document.getElementById("ozonFbsSupplyDetailStickersMenuBtn");
    if (!menu || !caret) return;
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    caret.setAttribute("aria-expanded", willOpen ? "true" : "false");
  }

  function openStickersPrint(postingNumbers, options) {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) return;
    closeStickersMenu();
    const btn = document.getElementById("ozonFbsSupplyDetailStickersBtn");
    const caret = document.getElementById("ozonFbsSupplyDetailStickersMenuBtn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Стикеры…";
    }
    if (caret) caret.disabled = true;
    const ids = Array.isArray(postingNumbers)
      ? postingNumbers.map((x) => String(x || "").trim()).filter(Boolean)
      : [];
    const opts = options && typeof options === "object" ? options : {};
    // Full print (no filter) → cover+separators.
    // Category print passes includeCoverAndSeparators: true.
    // Row «⋮» single sticker keeps labels-only (default when filtered).
    const includeCover =
      typeof opts.includeCoverAndSeparators === "boolean"
        ? opts.includeCoverAndSeparators
        : ids.length === 0;
    const tab = String(supplyDetailState.postingTab || "").trim();
    const body = {
      source_id: Number(sourceId),
      order_ids: ids,
      include_cover_and_separators: includeCover,
    };
    if (tab) body.posting_tab = tab;

    // Open print tab immediately (same user gesture) so the operator sees
    // progress there — not a blank tab after a blocking alert on the modal.
    const printWin = window.open("about:blank", "_blank");
    if (!printWin) {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Стикеры";
      }
      if (caret) caret.disabled = false;
      alert("Разрешите всплывающие окна для стикеров");
      return;
    }
    try {
      printWin.document.open();
      printWin.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
<title>Стикеры — загрузка</title>
<style>
  body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f8fafc;color:#0f172a}
  .box{max-width:520px;margin:48px auto;padding:24px;background:#fff;border:1px solid #e2e8f0;border-radius:12px}
  h1{margin:0 0 8px;font-size:20px} p{margin:0 0 8px;line-height:1.45;color:#334155}
  #st{font-size:18px;font-weight:700;color:#1d4ed8}
  .hint{color:#64748b;font-size:14px}
</style></head><body><div class="box">
  <h1>Подготовка стикеров</h1>
  <p id="st">Загрузка…</p>
  <p class="hint">Не закрывайте эту вкладку. Диалог печати откроется здесь автоматически.</p>
</div></body></html>`);
      printWin.document.close();
    } catch (_e) { /* cross-window write may fail in rare cases */ }

    const setPrintStatus = (text) => {
      try {
        if (!printWin || printWin.closed) return;
        const el = printWin.document.getElementById("st");
        if (el) el.textContent = String(text || "");
      } catch (_e) { /* ignore */ }
    };

    const setModalNotice = (text, kind) => {
      const info = document.getElementById("ozonFbsSupplyDetailInfo");
      if (!info) return;
      const msg = String(text || "").trim();
      if (!msg) {
        if (!isSupplyDetailReadOnly()) {
          info.hidden = true;
          info.textContent = "";
          info.classList.remove("is-ok", "is-warn");
        }
        return;
      }
      info.hidden = false;
      info.textContent = msg;
      // ok → green, warn → amber, error → default red (.wb-fbs-sd-info)
      info.classList.toggle("is-ok", kind === "ok");
      info.classList.toggle("is-warn", kind === "warn");
    };

    const restoreBtn = () => {
      if (!_ozonFbsSupplyActionsReady()) return;
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Стикеры";
      }
      if (caret) caret.disabled = false;
    };

    const writePrintHtml = (html) => {
      if (!printWin || printWin.closed) {
        throw new Error("Вкладка печати была закрыта до готовности стикеров");
      }
      printWin.document.open();
      printWin.document.write(html);
      printWin.document.close();
      try { printWin.focus(); } catch (_e) { /* ignore */ }
    };

    const openResultHtml = async (statusMeta) => {
      const res = await fetch("/api/ozon-fbs/stickers-print/result", {
        credentials: "same-origin",
      });
      if (!res.ok) {
        let detail = "";
        try {
          const data = await res.json();
          detail = detailText(data.detail);
        } catch (_) {
          detail = await res.text().catch(() => "");
        }
        throw new Error(detail || `Ошибка печати (${res.status})`);
      }
      setPrintStatus("Формируем страницы печати…");
      const html = await res.text();
      writePrintHtml(html);

      const missingCount = Number(
        res.headers.get("X-Feedpilot-Stickers-Missing-Count")
        || statusMeta?.missing_count
        || 0
      );
      if (missingCount > 0) {
        const expected = Number(
          res.headers.get("X-Feedpilot-Stickers-Expected")
          || statusMeta?.expected
          || 0
        ) || "?";
        const loaded = Number(
          res.headers.get("X-Feedpilot-Stickers-Loaded")
          || statusMeta?.loaded
          || 0
        ) || "?";
        const missingRaw = String(
          res.headers.get("X-Feedpilot-Stickers-Missing")
          || (statusMeta?.missing || []).join(",")
          || ""
        ).trim();
        const reasons = Array.isArray(statusMeta?.reasons) ? statusMeta.reasons : [];
        const preview = missingRaw
          ? missingRaw.split(",").slice(0, 5).join(", ")
          : "";
        const reasonShort = reasons[0] ? ` ${reasons[0]}` : "";
        setModalNotice(
          `Стикеры: загружено ${loaded} из ${expected}. `
          + `Пропущено ${missingCount}`
          + (preview ? ` (${preview})` : "")
          + `. Печать открыта в соседней вкладке.`
          + reasonShort,
          Number(loaded) > 0 ? "warn" : "error"
        );
      } else {
        setModalNotice(
          "Стикеры готовы — диалог печати открыт в соседней вкладке.",
          "ok"
        );
      }
    };

    const poll = async () => {
      for (let i = 0; i < 7200; i += 1) {
        await new Promise((r) => setTimeout(r, i === 0 ? 400 : 1000));
        const res = await fetch("/api/ozon-fbs/stickers-print/status", {
          credentials: "same-origin",
        });
        const st = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(detailText(st.detail) || `Ошибка ${res.status}`);
        const done = Number(st.done || 0);
        const total = Number(st.total || 0);
        const msg = String(st.message || "Стикеры…");
        const progressText =
          total > 0
            ? `Стикеры ${Math.min(done, total)}/${total}`
            : (msg.length > 28 ? `${msg.slice(0, 26)}…` : msg);
        if (btn) btn.textContent = progressText;
        setPrintStatus(
          total > 0
            ? `Загружено ${Math.min(done, total)} из ${total}…`
            : (msg || "Загрузка…")
        );
        if (st.in_progress) continue;
        if (st.ok) {
          await openResultHtml({
            expected: st.expected_count,
            loaded: st.loaded_count,
            missing_count: Array.isArray(st.missing_posting_numbers)
              ? st.missing_posting_numbers.length
              : 0,
            missing: st.missing_posting_numbers,
            reasons: st.missing_reasons,
          });
          return;
        }
        throw new Error(String(st.error || st.message || "Не удалось загрузить стикеры"));
      }
      throw new Error("Таймаут загрузки стикеров");
    };

    (async () => {
      try {
        const res = await fetch(
          `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/stickers-print/start`,
          {
            method: "POST",
            headers: jsonHeaders(),
            body: JSON.stringify(body),
          }
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(detailText(data.detail) || "Не удалось начать загрузку стикеров");
        setPrintStatus("Скачивание этикеток с Ozon…");
        await poll();
      } catch (e) {
        const err = String(e.message || e);
        setModalNotice(err, "error");
        setPrintStatus(err);
        try {
          if (printWin && !printWin.closed) {
            printWin.document.open();
            printWin.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
<title>Ошибка печати</title></head><body style="font-family:system-ui;padding:32px">
<h1>Не удалось подготовить стикеры</h1>
<p>${String(err).replace(/[<>&]/g, (c) => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]))}</p>
<p>Можно закрыть эту вкладку и повторить на странице поставки.</p>
</body></html>`);
            printWin.document.close();
          }
        } catch (_e) { /* ignore */ }
      } finally {
        restoreBtn();
      }
    })();
  }

  function _ozonFbsStickersCategorySetInfo(text, kind) {
    const el = document.getElementById("ozonFbsStickersCategoryInfo");
    if (!el) return;
    const msg = String(text || "").trim();
    if (!msg) {
      el.hidden = true;
      el.textContent = "";
      el.classList.remove("is-error", "is-ok");
      return;
    }
    el.hidden = false;
    el.textContent = msg;
    el.classList.toggle("is-error", kind === "error");
    el.classList.toggle("is-ok", kind === "ok");
  }

  function _ozonFbsStickersCategoryWord(n) {
    const abs = Math.abs(Number(n) || 0) % 100;
    const last = abs % 10;
    if (abs > 10 && abs < 20) return "категорий";
    if (last === 1) return "категория";
    if (last >= 2 && last <= 4) return "категории";
    return "категорий";
  }

  function _ozonFbsStickersCategorySyncUi() {
    const selected = stickersCategoryState.selected;
    const selectedCount = selected.size;
    let postingsTotal = 0;
    for (const g of stickersCategoryState.groups || []) {
      if (!selected.has(String(g.group_key || ""))) continue;
      const fromPostings = Array.isArray(g.posting_numbers)
        ? g.posting_numbers.length
        : (Array.isArray(g.order_ids) ? g.order_ids.length : 0);
      const qty = Number(g.qty);
      postingsTotal += Number.isFinite(qty) && qty > 0 ? qty : fromPostings;
    }
    const selEl = document.getElementById("ozonFbsStickersCategorySelected");
    if (selEl) {
      selEl.textContent =
        `Выбрано: ${selectedCount} ${_ozonFbsStickersCategoryWord(selectedCount)}, ` +
        `Отправлений: ${postingsTotal} шт.`;
    }
    const printBtn = document.getElementById("ozonFbsStickersCategoryPrintBtn");
    if (printBtn) printBtn.disabled = selectedCount <= 0 || stickersCategoryState.loading;
    document.querySelectorAll("#ozonFbsStickersCategoryList .wb-fbs-stickers-cat-row").forEach((row) => {
      const key = String(row.dataset.groupKey || "");
      const checked = selected.has(key);
      row.classList.toggle("is-checked", checked);
      const cb = row.querySelector('input[type="checkbox"]');
      if (cb) cb.checked = checked;
      const fillBtn = row.querySelector(".wb-fbs-stickers-cat-fill");
      if (fillBtn) fillBtn.hidden = !checked;
    });
  }

  function _ozonFbsStickersCategoryRender() {
    const box = document.getElementById("ozonFbsStickersCategoryList");
    if (!box) return;
    const groups = stickersCategoryState.groups || [];
    if (!groups.length) {
      box.innerHTML = `<div class="wb-fbs-empty">${stickersCategoryState.loading ? "Загрузка…" : "Нет товаров для печати"}</div>`;
      _ozonFbsStickersCategorySyncUi();
      return;
    }
    box.innerHTML = groups.map((g, idx) => {
      const key = esc(String(g.group_key || ""));
      const name = esc(String(g.product_name || "—"));
      const qty = Number(g.qty || 0);
      return `<div class="wb-fbs-stickers-cat-row" data-group-key="${key}" data-index="${idx}">
        <input type="checkbox" id="ozonFbsStickersCatCb_${idx}"
               onchange="onOzonFbsStickersCategoryToggleAt(${idx}, this.checked)" />
        <label for="ozonFbsStickersCatCb_${idx}">
          <span class="wb-fbs-stickers-cat-name">${name} — ${qty} шт.</span>
        </label>
        <button type="button" class="wb-fbs-stickers-cat-fill" hidden
                title="Выделить все ниже"
                aria-label="Выделить все ниже"
                onclick="ozonFbsStickersCategoryFillDownAt(${idx})">
          <svg width="14" height="14" viewBox="0 0 12 8" fill="none" aria-hidden="true">
            <path d="M1 1.5L6 6.5L11 1.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>`;
    }).join("");
    _ozonFbsStickersCategorySyncUi();
  }

  function onOzonFbsStickersCategoryToggleAt(index, checked) {
    const g = (stickersCategoryState.groups || [])[Number(index)];
    const key = String((g && g.group_key) || "");
    if (!key) return;
    if (checked) stickersCategoryState.selected.add(key);
    else stickersCategoryState.selected.delete(key);
    _ozonFbsStickersCategorySyncUi();
  }

  function ozonFbsStickersCategorySelectAll() {
    stickersCategoryState.selected = new Set(
      (stickersCategoryState.groups || []).map((g) => String(g.group_key || "")).filter(Boolean)
    );
    _ozonFbsStickersCategorySyncUi();
  }

  function ozonFbsStickersCategoryClearAll() {
    stickersCategoryState.selected.clear();
    _ozonFbsStickersCategorySyncUi();
  }

  function ozonFbsStickersCategoryFillDownAt(index) {
    const groups = stickersCategoryState.groups || [];
    const start = Number(index);
    if (!Number.isFinite(start) || start < 0 || start >= groups.length) return;
    for (let i = start; i < groups.length; i += 1) {
      const gk = String(groups[i].group_key || "");
      if (gk) stickersCategoryState.selected.add(gk);
    }
    _ozonFbsStickersCategorySyncUi();
  }

  function closeStickersByCategoryModal() {
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsStickersCategoryModal", false);
    } else {
      document.getElementById("ozonFbsStickersCategoryModal")?.classList.add("hidden");
    }
    stickersCategoryState.groups = [];
    stickersCategoryState.selected = new Set();
    stickersCategoryState.loading = false;
    _ozonFbsStickersCategorySetInfo("");
    const box = document.getElementById("ozonFbsStickersCategoryList");
    if (box) box.innerHTML = "";
    const printBtn = document.getElementById("ozonFbsStickersCategoryPrintBtn");
    if (printBtn) printBtn.disabled = true;
  }

  async function openStickersByCategoryModal() {
    closeStickersMenu();
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId) return;
    if (!document.getElementById("ozonFbsStickersCategoryModal")) return;
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsStickersCategoryModal", true);
    } else {
      document.getElementById("ozonFbsStickersCategoryModal")?.classList.remove("hidden");
    }
    stickersCategoryState.groups = [];
    stickersCategoryState.selected = new Set();
    stickersCategoryState.loading = true;
    _ozonFbsStickersCategorySetInfo("");
    _ozonFbsStickersCategoryRender();
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/sticker-groups?source_id=${sourceId}${_ozonFbsSupplyPostingTabParam()}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      stickersCategoryState.groups = Array.isArray(data.groups) ? data.groups : [];
      if (!stickersCategoryState.groups.length) {
        _ozonFbsStickersCategorySetInfo("В поставке нет товаров для печати", "error");
      } else {
        _ozonFbsStickersCategorySetInfo("");
      }
    } catch (e) {
      _ozonFbsStickersCategorySetInfo(String(e.message || e), "error");
    } finally {
      stickersCategoryState.loading = false;
      _ozonFbsStickersCategoryRender();
    }
  }

  function ozonFbsPrintStickersByCategory() {
    if (stickersCategoryState.loading) return;
    const selected = stickersCategoryState.selected;
    const nums = [];
    for (const g of stickersCategoryState.groups || []) {
      if (!selected.has(String(g.group_key || ""))) continue;
      const ids = Array.isArray(g.posting_numbers)
        ? g.posting_numbers
        : (Array.isArray(g.order_ids) ? g.order_ids : []);
      for (const id of ids) {
        const pn = String(id || "").trim();
        if (pn) nums.push(pn);
      }
    }
    if (!nums.length) return;
    closeStickersByCategoryModal();
    openStickersPrint(nums, { includeCoverAndSeparators: true });
  }

  document.addEventListener(
    "click",
    (e) => {
      const t = e.target;
      if (!(t instanceof Element)) return;
      const stickerBtn = t.closest("[data-ozon-action='print-sticker']");
      if (stickerBtn && stickerBtn.closest("[id^='ozonFbsRowMenu_']")) {
        const pn =
          String(stickerBtn.getAttribute("data-posting") || "").trim() ||
          String(stickerBtn.closest("[data-posting]")?.getAttribute("data-posting") || "").trim();
        if (pn) printOnePostingStickerFromDetail(e, pn);
        return;
      }
    },
    true
  );

  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    if (!t.closest("#ozonFbsPickingSplit")) closePickingMenu();
    if (!t.closest("#ozonFbsStickersSplit")) closeStickersMenu();
    if (
      !t.closest(".wb-fbs-row-menu-wrap") &&
      !t.closest(".wb-fbs-row-menu[id^='ozonFbsRowMenu_']")
    ) {
      closeOzonFbsRowMenus();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const stickersCat = document.getElementById("ozonFbsStickersCategoryModal");
    if (stickersCat && !stickersCat.classList.contains("hidden")) {
      closeStickersByCategoryModal();
    }
  });

  async function initSection() {
    if (!canView()) return;
    const tsdBtn = document.getElementById("ozonFbsTsdBtn");
    if (tsdBtn) {
      const p = permissions();
      tsdBtn.style.display =
        p.can_view_wb_fbs_tsd || p.is_tenant_owner ? "" : "none";
    }
    _ozonFbsSyncOwnerOnlyGear();
    syncTableMode();
    initColumnResizer();
    ozonFbsSupplyDetailColResizer.init();
    ozonFbsKizColResizer.init();
    ozonFbsPickColResizer.init();
    await loadSources();
    await loadPostings(true);
    syncShipAllButton();
    // Resume sync UI if a sync is already running (reload / re-enter section).
    try {
      const res = await fetch("/api/ozon-fbs/sync/status");
      const st = await res.json();
      if (st?.in_progress) {
        setSyncUi(true);
        showSyncInfo(String(st.message || "Синхронизация…"));
        pollSyncStatus();
      }
    } catch (_e) {
      /* ignore */
    }
    // Resume split/collect busy UI so supply links stay blocked after reload.
    try {
      const res = await fetch("/api/ozon-fbs/split-multi/status");
      const st = await res.json().catch(() => ({}));
      if (st?.in_progress) {
        splitState.busy = true;
        splitState.progressText = String(st.message || "Разделение…");
        showSyncInfo(splitState.progressText);
        syncPackagingActionButtons();
        pollSplitStatus();
      }
    } catch (_e) {
      /* ignore */
    }
    try {
      const res = await fetch("/api/ozon-fbs/ship-all/status");
      const st = await res.json().catch(() => ({}));
      if (st?.in_progress) {
        collectState.busy = true;
        state.shipAllBusy = true;
        showSyncInfo(String(st.message || "Сборка…"));
        syncShipAllButton();
        pollCollectStatus();
      }
    } catch (_e) {
      /* ignore */
    }
  }

  function _ozonFbsSyncOwnerOnlyGear() {
    const btn = document.getElementById("ozonFbsSyncSettingsBtn");
    if (btn) {
      const can = typeof isTenantOwner === "function" && isTenantOwner();
      btn.hidden = !can;
      btn.style.display = can ? "" : "none";
    }
    if (typeof _ozonFbsKizSyncImportBtn === "function") {
      _ozonFbsKizSyncImportBtn();
    }
  }

  function _ozonFbsSyncSettingsSetInfo(text, kind) {
    const el = document.getElementById("ozonFbsSyncSettingsInfo");
    if (!el) return;
    const msg = String(text || "").trim();
    el.hidden = !msg;
    el.textContent = msg;
    el.classList.toggle("is-error", !!msg && kind === "error");
    el.classList.toggle("is-ok", !!msg && kind === "ok");
  }

  const opsLogState = {
    timer: null,
    lastId: 0,
    retentionDays: 3,
    stickToTop: true,
  };

  function _opsLogFormatTime(iso) {
    const raw = String(iso || "").trim();
    if (!raw) return "—";
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) {
      const m = raw.match(/T(\d{2}:\d{2})/);
      return m ? m[1] : raw.slice(11, 16) || raw;
    }
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    return `${hh}:${mm}:${ss}`;
  }

  function _opsLogEscape(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function _opsLogRenderRow(item) {
    const level = String(item.level || "info");
    const actor = String(item.actor_name || "").trim();
    const msg = String(item.message || "").trim();
    const actorHtml = actor
      ? ` <span class="ozon-fbs-ops-log-actor">· ${_opsLogEscape(actor)}</span>`
      : "";
    return (
      `<div class="ozon-fbs-ops-log-row${level === "error" ? " is-error" : level === "warn" ? " is-warn" : ""}" data-id="${_opsLogEscape(item.id)}">` +
      `<span class="ozon-fbs-ops-log-time">${_opsLogEscape(_opsLogFormatTime(item.created_at))}</span>` +
      `<span class="ozon-fbs-ops-log-msg">${_opsLogEscape(msg)}${actorHtml}</span>` +
      `</div>`
    );
  }

  function _opsLogSetMeta(text) {
    const el = document.getElementById("ozonFbsOpsLogMeta");
    if (el) el.textContent = String(text || "");
  }

  function _stopOpsLogPoll() {
    if (opsLogState.timer) {
      clearTimeout(opsLogState.timer);
      opsLogState.timer = null;
    }
  }

  function _scheduleOpsLogPoll(delayMs) {
    _stopOpsLogPoll();
    const modal = document.getElementById("ozonFbsSyncSettingsModal");
    if (!modal || modal.classList.contains("hidden")) return;
    opsLogState.timer = setTimeout(() => {
      pollOzonFbsOpsLog().catch(() => {});
    }, Math.max(500, Number(delayMs) || 2000));
  }

  async function pollOzonFbsOpsLog(reset) {
    const modal = document.getElementById("ozonFbsSyncSettingsModal");
    const list = document.getElementById("ozonFbsOpsLogList");
    if (!modal || modal.classList.contains("hidden") || !list) {
      _stopOpsLogPoll();
      return;
    }
    if (reset) {
      opsLogState.lastId = 0;
      opsLogState.stickToTop = true;
      list.innerHTML = `<div class="ozon-fbs-ops-log-empty">Загрузка журнала…</div>`;
    }
    try {
      const after = reset ? 0 : opsLogState.lastId;
      const res = await fetch(
        `/api/ozon-fbs/ops-log?after_id=${encodeURIComponent(after)}&limit=${after ? 100 : 200}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      const items = Array.isArray(data.items) ? data.items : [];
      const retention = Number(data.retention_days || data.lookback_days) || opsLogState.retentionDays;
      opsLogState.retentionDays = retention;
      _opsLogSetMeta(`хранение ${retention} дн.`);

      if (reset || after === 0) {
        if (!items.length) {
          list.innerHTML = `<div class="ozon-fbs-ops-log-empty">Пока нет записей</div>`;
        } else {
          // API returns newest-first for initial load.
          list.innerHTML = items.map(_opsLogRenderRow).join("");
        }
      } else if (items.length) {
        const empty = list.querySelector(".ozon-fbs-ops-log-empty");
        if (empty) empty.remove();
        const nearTop = list.scrollTop < 48;
        // Incremental batch is ASC; reverse so newest lands at the top.
        const html = items
          .slice()
          .reverse()
          .map(_opsLogRenderRow)
          .join("");
        list.insertAdjacentHTML("afterbegin", html);
        // Cap DOM rows to avoid unbounded growth while modal stays open.
        const rows = list.querySelectorAll(".ozon-fbs-ops-log-row");
        const maxRows = 500;
        if (rows.length > maxRows) {
          for (let i = maxRows; i < rows.length; i += 1) {
            rows[i].remove();
          }
        }
        if (nearTop || opsLogState.stickToTop) {
          list.scrollTop = 0;
        }
      }
      if (items.length) {
        let maxId = opsLogState.lastId;
        for (const it of items) {
          const lid = Number(it?.id) || 0;
          if (lid > maxId) maxId = lid;
        }
        opsLogState.lastId = maxId;
      } else if (typeof data.last_id === "number" && data.last_id > opsLogState.lastId) {
        opsLogState.lastId = data.last_id;
      }
      if (reset && items.length) {
        list.scrollTop = 0;
      }
    } catch (e) {
      if (reset) {
        list.innerHTML = `<div class="ozon-fbs-ops-log-empty">${_opsLogEscape(String(e.message || e))}</div>`;
      }
      _opsLogSetMeta("ошибка обновления");
    }
    _scheduleOpsLogPoll(2000);
  }

  async function openOzonFbsSyncSettings() {
    if (typeof isTenantOwner === "function" && !isTenantOwner()) {
      alert("Настройки синхронизации доступны только главному пользователю");
      return;
    }
    const modal = document.getElementById("ozonFbsSyncSettingsModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    _ozonFbsSyncSettingsSetInfo("");
    const saveBtn = document.getElementById("ozonFbsSyncSettingsSaveBtn");
    const lookbackEl = document.getElementById("ozonFbsSyncLookback");
    if (saveBtn) saveBtn.disabled = true;
    pollOzonFbsOpsLog(true).catch(() => {});
    try {
      const res = await fetch("/api/ozon-fbs/sync-settings");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      if (lookbackEl) {
        const minD = Number(data.lookback_days_min) || 1;
        const maxD = Number(data.lookback_days_max) || 30;
        lookbackEl.min = String(minD);
        lookbackEl.max = String(maxD);
        let days = Number(data.lookback_days);
        if (!Number.isFinite(days)) days = 3;
        lookbackEl.value = String(Math.min(maxD, Math.max(minD, Math.round(days))));
        lookbackEl.disabled = data.can_edit === false;
        opsLogState.retentionDays = Math.min(maxD, Math.max(minD, Math.round(days)));
        _opsLogSetMeta(`хранение ${opsLogState.retentionDays} дн.`);
      }
      if (saveBtn) {
        saveBtn.disabled = data.can_edit === false;
        saveBtn.title = data.can_edit === false
          ? "Недостаточно прав для изменения настроек"
          : "";
      }
    } catch (e) {
      _ozonFbsSyncSettingsSetInfo(String(e.message || e), "error");
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function closeOzonFbsSyncSettings() {
    _stopOpsLogPoll();
    const modal = document.getElementById("ozonFbsSyncSettingsModal");
    if (modal) modal.classList.add("hidden");
  }

  async function saveOzonFbsSyncSettings() {
    if (typeof isTenantOwner === "function" && !isTenantOwner()) {
      alert("Настройки синхронизации доступны только главному пользователю");
      return;
    }
    const lookbackRaw = Number(document.getElementById("ozonFbsSyncLookback")?.value);
    const lookbackDays = Number.isFinite(lookbackRaw) ? Math.round(lookbackRaw) : 3;
    if (lookbackDays < 1 || lookbackDays > 30) {
      _ozonFbsSyncSettingsSetInfo("Укажите глубину от 1 до 30 дней", "error");
      return;
    }
    const saveBtn = document.getElementById("ozonFbsSyncSettingsSaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    _ozonFbsSyncSettingsSetInfo("Сохранение…");
    try {
      const res = await fetch("/api/ozon-fbs/sync-settings", {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({ lookback_days: lookbackDays }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      opsLogState.retentionDays = lookbackDays;
      _opsLogSetMeta(`хранение ${lookbackDays} дн.`);
      _ozonFbsSyncSettingsSetInfo(
        `Сохранено. Журнал хранится ${lookbackDays} дн.`,
        "ok"
      );
      pollOzonFbsOpsLog(true).catch(() => {});
    } catch (e) {
      _ozonFbsSyncSettingsSetInfo(String(e.message || e), "error");
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function setTab(tab) {
    const next = String(tab || "awaiting_packaging");
    state.tab = OZON_FBS_HIDDEN_TABS.has(next) ? "awaiting_packaging" : next;
    state.selected.clear();
    document.querySelectorAll("#ozonFbsTabs .wb-fbs-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === state.tab);
    });
    updateBottomBar();
    loadPostings(true);
  }

  function onSourceChange() {
    const sel = document.getElementById("ozonFbsSourceSelect");
    state.sourceId = sel?.value ? Number(sel.value) : null;
    state.selected.clear();
    loadPostings(true);
  }

  function onSearchInput() {
    const el = document.getElementById("ozonFbsSearchFilter");
    state.search = (el?.value || "").trim();
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => loadPostings(true), 300);
  }

  function changePage(delta) {
    state.page = Math.max(1, state.page + Number(delta || 0));
    loadPostings(false);
  }

  function changePageSize(val) {
    state.pageSize = Number(val) || 50;
    loadPostings(true);
  }

  function closeSyncInfo() {
    const box = document.getElementById("ozonFbsSyncInfo");
    if (!box) return;
    box.hidden = true;
    box.classList.remove("is-ok", "is-error");
    const textEl = document.getElementById("ozonFbsSyncInfoText");
    const palletsEl = document.getElementById("ozonFbsSyncInfoPallets");
    const multiEl = document.getElementById("ozonFbsSyncInfoMulti");
    if (textEl) textEl.textContent = "";
    if (palletsEl) {
      palletsEl.innerHTML = "";
      palletsEl.hidden = true;
    }
    if (multiEl) {
      multiEl.innerHTML = "";
      multiEl.hidden = true;
    }
  }

  /** Mirror WB FBS sync banner: green/red + per-source rows + pallet/box lines. */
  function syncSourceRows(st, msg) {
    const sources = Array.isArray(st?.sources) ? st.sources : [];
    if (!sources.length) return null;
    if (st?.in_progress) return sources;
    const hasIssues = (st?.errors || []).length || /ошибк/i.test(String(msg || ""));
    if (!hasIssues) return null;
    const bad = sources.filter((row) => {
      const status = String(row?.status || "");
      return status === "error" || status === "stopped";
    });
    return bad.length ? bad : null;
  }

  function showSyncInfo(
    text,
    kind = "",
    palletSummary = null,
    sourceRows = null,
    palletSummaryError = "",
    multiSummary = null,
  ) {
    const info = document.getElementById("ozonFbsSyncInfo");
    if (!info) return;
    const msg = String(text || "").trim();
    const textEl = document.getElementById("ozonFbsSyncInfoText");
    const palletsEl = document.getElementById("ozonFbsSyncInfoPallets");
    const multiEl = document.getElementById("ozonFbsSyncInfoMulti");
    const rowsSrc = Array.isArray(sourceRows) ? sourceRows : [];

    if (textEl) {
      if (rowsSrc.length) {
        const rowsHtml = rowsSrc.map((row) => {
          const name = esc(row?.name || `Источник ${row?.source_id || ""}`);
          const line = esc(row?.message || "");
          const st = String(row?.status || "");
          let cls = "wb-fbs-sync-info-source-row";
          if (st === "error") cls += " is-error";
          else if (st === "done") cls += " is-ok";
          else if (st === "stopped") cls += " is-stopped";
          return `<div class="${cls}"><span class="wb-fbs-sync-info-source-name">${name}</span>: ${line}</div>`;
        }).join("");
        const showSummary = msg && /готово|остановлено/i.test(msg);
        if (showSummary) {
          textEl.innerHTML = `<div class="wb-fbs-sync-info-summary">${esc(msg)}</div>${rowsHtml}`;
        } else {
          textEl.innerHTML = rowsHtml;
        }
      } else {
        textEl.textContent = msg;
      }
    }

    const rows = Array.isArray(palletSummary) ? palletSummary : [];
    const palletErr = String(palletSummaryError || "").trim();
    const canShowPallets = kind === "ok" || /готово/i.test(msg) || /остановлено/i.test(msg);
    if (palletsEl) {
      const parts = [];
      if (palletErr && canShowPallets) {
        parts.push(
          `<div class="wb-fbs-sync-info-pallet-error" role="alert">${esc(palletErr)}</div>`
        );
      }
      if (rows.length && canShowPallets) {
        parts.push(
          ...rows.map((row) => {
            const name = esc(row?.name || `Источник ${row?.source_id || ""}`);
            const label = esc(
              row?.pallets_label
              || `${Number(row?.pallets || 0).toFixed(2).replace(".", ",")} паллета`
            );
            return `<div class="wb-fbs-sync-info-pallet-row">${name} — ${label}</div>`;
          })
        );
      }
      if (parts.length) {
        palletsEl.innerHTML = parts.join("");
        palletsEl.hidden = false;
      } else {
        palletsEl.innerHTML = "";
        palletsEl.hidden = true;
      }
    }

    if (multiEl) {
      const multiRows = Array.isArray(multiSummary) ? multiSummary : [];
      const canShowMulti = kind === "ok" || /готово/i.test(msg);
      const visible = multiRows.filter((row) => Number(row?.multi_count || 0) > 0);
      if (canShowMulti && visible.length) {
        multiEl.innerHTML = visible.map((row) => {
          const name = esc(row?.name || `Источник ${row?.source_id || ""}`);
          const n = Number(row.multi_count || 0);
          return `<div class="wb-fbs-sync-info-multi-row">${name} — мультизаказов: ${esc(String(n))}</div>`;
        }).join("");
        multiEl.hidden = false;
      } else if (canShowMulti && state.sourceId && multiAwaitingCount() > 0) {
        multiEl.innerHTML =
          `<div class="wb-fbs-sync-info-multi-row">Мультизаказов: ${esc(String(multiAwaitingCount()))}</div>`;
        multiEl.hidden = false;
      } else {
        multiEl.innerHTML = "";
        multiEl.hidden = true;
      }
    }

    info.hidden = !(
      msg ||
      rowsSrc.length ||
      (palletErr && canShowPallets) ||
      (multiEl && !multiEl.hidden)
    );
    info.classList.toggle("is-error", kind === "error");
    info.classList.toggle("is-ok", kind === "ok");
    info.style.color = "";
  }

  function setSyncUi(running) {
    const stopBtn = document.getElementById("ozonFbsStopBtn");
    const syncBtn = document.getElementById("ozonFbsSyncBtn");
    if (stopBtn) stopBtn.classList.toggle("hidden", !running);
    if (syncBtn) syncBtn.disabled = running;
    state.syncBusy = Boolean(running);
    syncPackagingActionButtons();
  }

  async function pollSyncStatus() {
    try {
      const res = await fetch("/api/ozon-fbs/sync/status");
      const st = await res.json();
      const running = Boolean(st.in_progress);
      setSyncUi(running);
      const msg = String(st.message || "");
      const errs = (st.errors || [])
        .map((e) => String(e || "").trim())
        .filter((e) => e)
        .slice(0, 2)
        .join("; ");
      const text = `${msg}${errs ? " · " + errs : ""}`.trim();
      let kind = "";
      if (!running) {
        if ((st.errors || []).length || /ошибк/i.test(msg)) kind = "error";
        else if (/готово/i.test(msg) || /остановлено/i.test(msg)) kind = "ok";
      }
      const pallets = (!running && Array.isArray(st.pallet_summary))
        ? st.pallet_summary
        : null;
      const palletErr = !running ? String(st.pallet_summary_error || "").trim() : "";
      const multiSummary = (!running && Array.isArray(st.multi_summary))
        ? st.multi_summary
        : null;
      const sourceRows = syncSourceRows(st, msg);
      if (running && sourceRows) showSyncInfo(text, kind, null, sourceRows);
      else showSyncInfo(text, kind, pallets, sourceRows, palletErr, multiSummary);
      if (running) {
        state.syncPollTimer = setTimeout(pollSyncStatus, 1500);
      } else {
        clearTimeout(state.syncPollTimer);
        state.syncPollTimer = null;
        await loadPostings(false);
      }
    } catch (e) {
      setSyncUi(false);
    }
  }

  async function syncOzonFbs() {
    setSyncUi(true);
    showSyncInfo("Запуск синхронизации…");
    try {
      const res = await fetch("/api/ozon-fbs/sync", {
        method: "POST",
        headers: jsonHeaders(),
        body: "{}",
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        showSyncInfo(data.message || data.detail || "Ошибка синхронизации", "error");
        setSyncUi(false);
        return;
      }
      showSyncInfo(data.message || "Синхронизация запущена");
      pollSyncStatus();
    } catch (e) {
      showSyncInfo("Ошибка сети", "error");
      setSyncUi(false);
    }
  }

  async function stopOzonFbsSync() {
    try {
      await fetch("/api/ozon-fbs/sync/stop", { method: "POST", headers: jsonHeaders() });
      showSyncInfo("Остановка…");
    } catch (e) {
      /* noop */
    }
  }

  async function openDetail(postingNumber) {
    if (!state.sourceId || !postingNumber) return;
    state.detailPosting = String(postingNumber);
    const modal = document.getElementById("ozonFbsDetailModal");
    const title = document.getElementById("ozonFbsDetailTitle");
    const meta = document.getElementById("ozonFbsDetailMeta");
    const body = document.getElementById("ozonFbsDetailBody");
    if (title) title.innerHTML = `Отправление ${formatOzonPostingNumberHtml(postingNumber)}`;
    if (meta) meta.textContent = "Загрузка…";
    if (body) body.textContent = "";
    if (modal) modal.classList.remove("hidden");
    try {
      const res = await fetch(
        `/api/ozon-fbs/postings/${encodeURIComponent(postingNumber)}/detail?source_id=${state.sourceId}`
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Не найдено");
      state.detailPayload = data;
      if (meta) {
        meta.textContent = `${data.tab_label || data.tab || ""} · ${data.status || ""} · ${data.warehouse_label || ""}`;
      }
      const products = Array.isArray(data.products) ? data.products : [];
      const lines = products.map((p) => {
        const name = esc(p.name || p.offer_id || "Товар");
        const qty = esc(p.quantity || 1);
        return `<div style="margin-bottom:8px"><strong>${name}</strong> — ${qty} шт.</div>`;
      });
      if (body) {
        body.innerHTML = lines.join("") || "<div>Нет данных о товарах</div>";
      }
      const shipBtn = document.getElementById("ozonFbsDetailShipBtn");
      const stickerBtn = document.getElementById("ozonFbsDetailStickerBtn");
      if (shipBtn) shipBtn.hidden = !data.can_ship;
      if (stickerBtn) stickerBtn.hidden = !data.can_print_label;
    } catch (e) {
      if (meta) meta.textContent = e.message || "Ошибка";
    }
  }

  function closeDetailModal() {
    const modal = document.getElementById("ozonFbsDetailModal");
    if (modal) modal.classList.add("hidden");
    state.detailPosting = null;
    state.detailPayload = null;
  }

  async function shipCurrent() {
    if (!state.sourceId || !state.detailPosting) return;
    const btn = document.getElementById("ozonFbsDetailShipBtn");
    if (btn) btn.disabled = true;
    try {
      const res = await fetch(
        `/api/ozon-fbs/postings/${encodeURIComponent(state.detailPosting)}/ship?source_id=${state.sourceId}`,
        { method: "POST", headers: jsonHeaders() }
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Ошибка сборки");
      const resultPns = Array.isArray(data.posting_numbers) ? data.posting_numbers : [];
      if (resultPns.length > 1) {
        alert(`Собрано с разбиением: ${resultPns.length} отправлений`);
      }
      closeDetailModal();
      await loadPostings(false);
    } catch (e) {
      alert(e.message || "Ошибка");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function printCurrentSticker() {
    if (!state.sourceId || !state.detailPosting) return;
    const url = `/api/ozon-fbs/postings/stickers-print?source_id=${state.sourceId}&posting_numbers=${encodeURIComponent(state.detailPosting)}`;
    window.open(url, "_blank");
  }

  /* ── Selection → new / existing local supply ── */

  const selectionState = {
    mode: "", // create | add
    preview: null,
    postingNumbers: [],
    sourceId: null,
    busy: false,
  };

  function closeSelectionSupplyModal() {
    if (selectionState.busy) return;
    document.getElementById("ozonFbsSelectionSupplyModal")?.classList.add("hidden");
    selectionState.mode = "";
    selectionState.preview = null;
    selectionState.postingNumbers = [];
    selectionState.sourceId = null;
    const err = document.getElementById("ozonFbsSelectionSupplyErr");
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
  }

  function selectedPostingNumbers() {
    if (isSuppliesTab() || state.tab !== "awaiting_packaging") return [];
    return [...state.selected].map((x) => String(x || "").trim()).filter(Boolean);
  }

  async function selectionPreview(sourceId, postingNumbers) {
    const res = await fetch("/api/ozon-fbs/selection/preview", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ source_id: sourceId, posting_numbers: postingNumbers }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(detailText(data.detail) || "Не удалось проверить выбор");
    return data;
  }

  function selectionTraitsHtml(traits) {
    const t = traits || {};
    const chips = [];
    if (t.warehouse_name) chips.push(t.warehouse_name);
    else if (t.warehouse_id != null) chips.push(`Склад ${t.warehouse_id}`);
    if (!chips.length) return "";
    return `<div class="wb-fbs-selection-traits">${chips.map((c) =>
      `<span class="wb-fbs-selection-trait">${esc(c)}</span>`
    ).join("")}</div>`;
  }

  function renderSelectionCreateModal(preview) {
    const title = document.getElementById("ozonFbsSelectionSupplyTitle");
    const lead = document.getElementById("ozonFbsSelectionSupplyLead");
    const body = document.getElementById("ozonFbsSelectionSupplyBody");
    const confirmBtn = document.getElementById("ozonFbsSelectionSupplyConfirmBtn");
    if (title) title.textContent = "Новая поставка";
    if (confirmBtn) {
      confirmBtn.textContent = "Создать";
      confirmBtn.disabled = false;
    }
    const count = Number(preview.order_count || 0);
    const splitNote = shipSplitPreviewNote(preview);
    if (lead) {
      lead.textContent =
        `Отправления будут собраны на Ozon и попадут в новую локальную поставку на «Ожидают отгрузки» (${count} шт.).`
        + (splitNote ? ` ${splitNote}` : "");
    }
    const name = String(preview.suggested_name || "");
    const existing = new Set(
      (Array.isArray(preview.existing_names) ? preview.existing_names : [])
        .map((x) => String(x || "").trim()).filter(Boolean)
    );
    const conflict = existing.has(name.trim());
    if (body) {
      body.innerHTML = `
        ${selectionTraitsHtml(preview.traits)}
        <div class="wb-fbs-collect-mgt-field">
          <label for="ozonFbsSelectionSupplyName">Название поставки</label>
          <input type="text" id="ozonFbsSelectionSupplyName" value="${esc(name)}"
                 autocomplete="off" oninput="ozonFbsSelectionSupplyNameInput(this)" />
          <p class="wb-fbs-collect-mgt-warn" id="ozonFbsSelectionSupplyNameWarn" ${conflict ? "" : "hidden"}>
            Поставка с таким названием уже есть — измените название.
          </p>
        </div>`;
    }
  }

  function renderSelectionAddModal(preview) {
    const title = document.getElementById("ozonFbsSelectionSupplyTitle");
    const lead = document.getElementById("ozonFbsSelectionSupplyLead");
    const body = document.getElementById("ozonFbsSelectionSupplyBody");
    const confirmBtn = document.getElementById("ozonFbsSelectionSupplyConfirmBtn");
    if (title) title.textContent = "Добавить к существующей";
    if (confirmBtn) confirmBtn.textContent = "Добавить";
    const count = Number(preview.order_count || 0);
    const supplies = Array.isArray(preview.compatible_supplies) ? preview.compatible_supplies : [];
    const splitNote = shipSplitPreviewNote(preview);
    if (lead) {
      const base = supplies.length
        ? `Выберите открытую поставку для ${count} отпр. Показаны совместимые по складу.`
        : `Для ${count} отпр. нет совместимых открытых поставок.`;
      lead.textContent = splitNote ? `${base} ${splitNote}` : base;
    }
    if (!body) return;
    if (!supplies.length) {
      body.innerHTML = `
        ${selectionTraitsHtml(preview.traits)}
        <div class="wb-fbs-collect-mgt-auto">
          Нет открытых поставок с тем же складом. Создайте новую поставку или выберите другой набор.
        </div>`;
      if (confirmBtn) confirmBtn.disabled = true;
      return;
    }
    if (confirmBtn) confirmBtn.disabled = false;
    body.innerHTML = `
      ${selectionTraitsHtml(preview.traits)}
      <div class="wb-fbs-collect-mgt-field">
        <label>Поставка</label>
        <div class="wb-fbs-collect-mgt-supplies">
          ${supplies.map((s, si) => {
            const sid = String(s.supply_id || "");
            const sname = String(s.name || sid);
            const meta = [
              s.is_empty ? "пустая" : "открытая",
              `${Number(s.orders_count || 0)} отпр.`,
              s.warehouse_name || (s.warehouse_id != null ? `склад ${s.warehouse_id}` : null),
            ].filter(Boolean).join(" · ");
            return `
              <label class="wb-fbs-collect-mgt-supply">
                <input type="radio" name="ozonFbsSelectionSupplyPick" value="${esc(sid)}" ${si === 0 ? "checked" : ""} />
                <span>
                  <span class="wb-fbs-collect-mgt-supply-name">${esc(sname)}</span>
                  <span class="wb-fbs-collect-mgt-supply-meta">${esc(meta)}</span>
                </span>
              </label>`;
          }).join("")}
        </div>
      </div>`;
  }

  function selectionSupplyNameInput(input) {
    const preview = selectionState.preview;
    const existing = new Set(
      (Array.isArray(preview?.existing_names) ? preview.existing_names : [])
        .map((x) => String(x || "").trim()).filter(Boolean)
    );
    const warn = document.getElementById("ozonFbsSelectionSupplyNameWarn");
    if (!warn) return;
    const name = String(input?.value || "").trim();
    warn.hidden = !(name && existing.has(name));
  }

  function showSelectionErrors(errors, mode) {
    const list = Array.isArray(errors) ? errors.filter(Boolean) : [];
    showCollectResult({
      ok: false,
      message: mode === "create"
        ? "Нельзя создать поставку из выбранных отправлений."
        : "Нельзя добавить выбранные отправления в одну поставку.",
      errors: list,
    });
  }

  async function openNewSupplyFromSelection() {
    if (selectionState.busy) return;
    if (state.tab !== "awaiting_packaging") return;
    const nums = selectedPostingNumbers();
    if (!nums.length) {
      alert("Выберите отправления во вкладке «Ожидают сборки»");
      return;
    }
    const sourceId = state.sourceId;
    if (!sourceId) {
      alert("Выберите источник OZON ФБС");
      return;
    }
    selectionState.busy = true;
    selectionState.sourceId = sourceId;
    const errEl = document.getElementById("ozonFbsSelectionSupplyErr");
    if (errEl) { errEl.hidden = true; errEl.textContent = ""; }
    try {
      const preview = await selectionPreview(sourceId, nums);
      if (state.sourceId !== sourceId) return;
      if (!preview.ok) {
        showSelectionErrors(preview.errors, "create");
        return;
      }
      selectionState.mode = "create";
      selectionState.preview = preview;
      selectionState.postingNumbers = Array.isArray(preview.posting_numbers)
        ? preview.posting_numbers
        : nums;
      renderSelectionCreateModal(preview);
      document.getElementById("ozonFbsSelectionSupplyModal")?.classList.remove("hidden");
    } catch (e) {
      selectionState.sourceId = null;
      alert(e.message || String(e));
    } finally {
      selectionState.busy = false;
    }
  }

  async function openAddToExistingSupply() {
    if (selectionState.busy) return;
    if (state.tab !== "awaiting_packaging") return;
    const nums = selectedPostingNumbers();
    if (!nums.length) {
      alert("Выберите отправления во вкладке «Ожидают сборки»");
      return;
    }
    const sourceId = state.sourceId;
    if (!sourceId) {
      alert("Выберите источник OZON ФБС");
      return;
    }
    selectionState.busy = true;
    selectionState.sourceId = sourceId;
    const errEl = document.getElementById("ozonFbsSelectionSupplyErr");
    if (errEl) { errEl.hidden = true; errEl.textContent = ""; }
    try {
      const preview = await selectionPreview(sourceId, nums);
      if (state.sourceId !== sourceId) return;
      if (!preview.ok) {
        showSelectionErrors(preview.errors, "add");
        return;
      }
      if (!preview.has_open_supplies) {
        alert("Нет открытых поставок. Создайте новую поставку.");
        return;
      }
      selectionState.mode = "add";
      selectionState.preview = preview;
      selectionState.postingNumbers = Array.isArray(preview.posting_numbers)
        ? preview.posting_numbers
        : nums;
      renderSelectionAddModal(preview);
      document.getElementById("ozonFbsSelectionSupplyModal")?.classList.remove("hidden");
    } catch (e) {
      selectionState.sourceId = null;
      alert(e.message || String(e));
    } finally {
      selectionState.busy = false;
    }
  }

  async function confirmSelectionSupply() {
    if (selectionState.busy) return;
    if (!selectionState.preview) return;
    if (state.tab !== "awaiting_packaging") {
      alert("Действие доступно только на вкладке «Ожидают сборки»");
      return;
    }
    const mode = selectionState.mode;
    const errEl = document.getElementById("ozonFbsSelectionSupplyErr");
    const confirmBtn = document.getElementById("ozonFbsSelectionSupplyConfirmBtn");
    const sourceId = selectionState.sourceId;
    const postingNumbers = selectionState.postingNumbers || [];
    if (!sourceId || !postingNumbers.length) return;

    let payload = { source_id: sourceId, posting_numbers: postingNumbers };
    let url = "";
    if (mode === "create") {
      const name = String(document.getElementById("ozonFbsSelectionSupplyName")?.value || "").trim();
      const existing = new Set(
        (selectionState.preview.existing_names || [])
          .map((x) => String(x || "").trim()).filter(Boolean)
      );
      if (!name) {
        if (errEl) { errEl.hidden = false; errEl.textContent = "Укажите название поставки"; }
        return;
      }
      if (existing.has(name)) {
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = `Поставка «${name}» уже есть — измените название`;
        }
        return;
      }
      payload.name = name;
      url = "/api/ozon-fbs/selection/create-supply";
    } else if (mode === "add") {
      const checked = document.querySelector('input[name="ozonFbsSelectionSupplyPick"]:checked');
      const supplyId = String(checked?.value || "").trim();
      if (!supplyId) {
        if (errEl) { errEl.hidden = false; errEl.textContent = "Выберите поставку"; }
        return;
      }
      payload.supply_id = supplyId;
      url = "/api/ozon-fbs/selection/add-to-supply";
    } else {
      return;
    }

    selectionState.busy = true;
    if (confirmBtn) confirmBtn.disabled = true;
    if (errEl) { errEl.hidden = true; errEl.textContent = ""; }
    showSyncInfo("Сборка выбранных отправлений…");
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Ошибка операции");
      if (!data.ok && !(Number(data.added || 0) > 0)) {
        const errs = Array.isArray(data.errors) ? data.errors : [];
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = errs.length ? errs.join("\n") : (data.message || "Операция не выполнена");
        }
        return;
      }
      selectionState.busy = false;
      closeSelectionSupplyModal();
      clearSelection();
      showCollectResult(data);
      showSyncInfo(data.message || "Готово");
      if (data.goto_awaiting_deliver) setTab("awaiting_deliver");
      else await loadPostings(true);
    } catch (e) {
      const msg = e.message || String(e);
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = msg;
      } else {
        alert(msg);
      }
    } finally {
      selectionState.busy = false;
      if (confirmBtn) confirmBtn.disabled = false;
    }
  }

  function todayIsoDate() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function closeShipmentsModal() {
    document.getElementById("ozonFbsShipmentsModal")?.classList.add("hidden");
    shipmentsState.forming = false;
  }

  function _ozonFbsContainersModalOpen() {
    const modal = document.getElementById("ozonFbsContainersModal");
    return Boolean(modal && !modal.classList.contains("hidden"));
  }

  function _ozonFbsContainersSetVisible(show) {
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsContainersModal", !!show);
      return;
    }
    const modal = document.getElementById("ozonFbsContainersModal");
    if (modal) modal.classList.toggle("hidden", !show);
  }

  function _ozonFbsContainersSetInfo(text, kind) {
    const el = document.getElementById("ozonFbsContainersInfo");
    if (!el) return;
    const msg = String(text || "").trim();
    if (!msg) {
      el.hidden = true;
      el.textContent = "";
      el.classList.remove("is-ok", "is-error");
      return;
    }
    el.hidden = false;
    el.textContent = msg;
    el.classList.toggle("is-ok", kind === "ok");
    el.classList.toggle("is-error", kind === "error");
  }

  function _ozonFbsContainersAmountValue() {
    const input = document.getElementById("ozonFbsContainersAmount");
    let n = Number(input?.value || 1);
    if (!Number.isFinite(n)) n = 1;
    n = Math.max(1, Math.min(100, Math.round(n)));
    if (input) input.value = String(n);
    return n;
  }

  function ozonFbsContainersStep(delta) {
    if (containersState.busy) return;
    const input = document.getElementById("ozonFbsContainersAmount");
    if (!input) return;
    const next = _ozonFbsContainersAmountValue() + Number(delta || 0);
    input.value = String(Math.max(1, Math.min(100, next)));
  }

  function _ozonFbsContainersSyncBusyUi() {
    const busy = !!containersState.busy || !!containersState.loading;
    const createBtn = document.getElementById("ozonFbsContainersCreateBtn");
    const refreshBtn = document.getElementById("ozonFbsContainersRefreshBtn");
    const amount = document.getElementById("ozonFbsContainersAmount");
    const sortSel = document.getElementById("ozonFbsContainersSortType");
    if (createBtn) {
      createBtn.disabled = busy;
      createBtn.textContent = containersState.busy ? "Создание…" : "Создать";
    }
    if (refreshBtn) {
      refreshBtn.disabled = busy;
      refreshBtn.textContent = containersState.loading ? "Обновление…" : "Обновить";
    }
    if (amount) amount.disabled = busy;
    if (sortSel) sortSel.disabled = busy;
    document.querySelectorAll("#ozonFbsContainersModal .wb-fbs-trbx-stepper-btn").forEach((btn) => {
      btn.disabled = busy;
    });
  }

  function renderOzonFbsContainersTable(items) {
    const tbody = document.getElementById("ozonFbsContainersTbody");
    if (!tbody) return;
    const rows = Array.isArray(items) ? items : [];
    containersState.items = rows;
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-trbx-boxes-empty">Нет активных грузомест</td></tr>`;
      return;
    }
    const busy = containersState.busy ? "disabled" : "";
    tbody.innerHTML = rows.map((c) => {
      const cid = String(c.container_id || "").trim();
      const num = Number(c.container_number || 0);
      const orders = Number(c.order_count || 0);
      const status = esc(c.status_label || c.status || "—");
      const sortLabel = esc(c.sort_type_label || "");
      const cargoLabel = esc(c.cargo_type_label || "");
      const meta = [sortLabel, cargoLabel].filter(Boolean).join(" · ");
      const canDelete = c.can_delete === true;
      const canPrint = c.can_print !== false;
      const canApprove = c.can_approve === true;
      const safeJs = JSON.stringify(cid);
      return `<tr>
        <td>
          <div class="ozon-fbs-containers-id">${esc(cid)}</div>
          <div class="ozon-fbs-containers-sub">№ ${esc(String(num || "—"))}${meta ? ` · ${meta}` : ""}</div>
        </td>
        <td class="ozon-fbs-containers-col-orders">${esc(String(orders))}</td>
        <td class="ozon-fbs-containers-col-meta">${status}</td>
        <td class="wb-fbs-trbx-boxes-col-act">
          <div class="wb-fbs-trbx-box-actions">
            <button type="button" class="wb-fbs-trbx-box-approve" title="Подтвердить состав грузоместа"
                    aria-label="Подтвердить ${esc(cid)}" ${(busy || !canApprove) ? "disabled" : ""}
                    onclick='approveOzonFbsContainer(${safeJs})'>✓</button>
            <button type="button" class="wb-fbs-trbx-box-print" title="Печать этикетки"
                    aria-label="Печать ${esc(cid)}" ${(busy || !canPrint) ? "disabled" : ""}
                    onclick='printOzonFbsContainerLabel(${safeJs})'>⎙</button>
            <button type="button" class="wb-fbs-trbx-box-delete" title="Удалить грузоместо"
                    aria-label="Удалить ${esc(cid)}" ${(busy || !canDelete) ? "disabled" : ""}
                    onclick='deleteOzonFbsContainer(${safeJs})'>✕</button>
          </div>
        </td>
      </tr>`;
    }).join("");
  }

  async function loadOzonFbsContainers({ keepInfo = false } = {}) {
    const sid = String(containersState.supplyId || supplyDetailState.supplyId || "").trim();
    const sourceId = containersState.sourceId || supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId) return null;
    containersState.loading = true;
    _ozonFbsContainersSyncBusyUi();
    if (!keepInfo) _ozonFbsContainersSetInfo("Загружаем грузоместа из Ozon…");
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers?${params}`,
        { headers: jsonHeaders() }
      );
      const data = await res.json().catch(() => ({}));
      if (!_ozonFbsContainersModalOpen() || String(containersState.supplyId || "") !== sid) {
        return null;
      }
      if (!res.ok || data.ok === false) {
        throw new Error(detailText(data.detail) || data.message || `Ошибка ${res.status}`);
      }
      containersState.warehouseId = data.warehouse_id || null;
      renderOzonFbsContainersTable(data.items || []);
      const total = Number(data.total || (data.items || []).length || 0);
      const wh = String(data.warehouse_name || "").trim();
      if (!keepInfo) {
        _ozonFbsContainersSetInfo(
          total
            ? `Активных грузомест: ${total}${wh ? ` · ${wh}` : ""}`
            : `Нет активных грузомест${wh ? ` · ${wh}` : ""}`,
          "ok"
        );
      }
      return data;
    } catch (e) {
      if (_ozonFbsContainersModalOpen()) {
        _ozonFbsContainersSetInfo(e.message || String(e), "error");
        if (!containersState.items.length) {
          renderOzonFbsContainersTable([]);
        }
      }
      return null;
    } finally {
      containersState.loading = false;
      _ozonFbsContainersSyncBusyUi();
    }
  }

  function openOzonFbsContainersModal() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId) {
      alert("Откройте поставку");
      return;
    }
    containersState.supplyId = sid;
    containersState.sourceId = sourceId;
    containersState.items = [];
    containersState.busy = false;
    const amount = document.getElementById("ozonFbsContainersAmount");
    if (amount) amount.value = "1";
    const sortSel = document.getElementById("ozonFbsContainersSortType");
    if (sortSel) sortSel.value = "sort";
    renderOzonFbsContainersTable([]);
    _ozonFbsContainersSetInfo("");
    _ozonFbsContainersSetVisible(true);
    _ozonFbsContainersSyncBusyUi();
    loadOzonFbsContainers();
  }

  function closeOzonFbsContainersModal() {
    if (containersState.busy) return;
    _ozonFbsContainersSetVisible(false);
    containersState.supplyId = null;
    containersState.items = [];
    _ozonFbsContainersSetInfo("");
  }

  function refreshOzonFbsContainers() {
    if (containersState.busy || containersState.loading) return;
    loadOzonFbsContainers();
  }

  async function createOzonFbsContainers() {
    const sid = String(containersState.supplyId || "").trim();
    const sourceId = containersState.sourceId;
    if (!sid || !sourceId || containersState.busy) return;
    const amount = _ozonFbsContainersAmountValue();
    const sortType = String(document.getElementById("ozonFbsContainersSortType")?.value || "sort");
    containersState.busy = true;
    _ozonFbsContainersSyncBusyUi();
    _ozonFbsContainersSetInfo("Создаём грузоместа в Ozon…");
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({
            source_id: sourceId,
            containers_count: amount,
            sort_type: sortType,
            cargo_type: "pallet",
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(detailText(data.detail) || data.message || `Ошибка ${res.status}`);
      }
      renderOzonFbsContainersTable(data.items || []);
      _ozonFbsContainersSetInfo(
        String(data.message || `Создано: ${data.created || amount}`),
        "ok"
      );
    } catch (e) {
      _ozonFbsContainersSetInfo(e.message || String(e), "error");
    } finally {
      containersState.busy = false;
      _ozonFbsContainersSyncBusyUi();
    }
  }

  async function deleteOzonFbsContainer(containerId) {
    const sid = String(containersState.supplyId || "").trim();
    const sourceId = containersState.sourceId;
    const cid = String(containerId || "").trim();
    if (!sid || !sourceId || !cid || containersState.busy) return;
    if (!window.confirm(`Удалить грузоместо ${cid}?`)) return;
    containersState.busy = true;
    _ozonFbsContainersSyncBusyUi();
    renderOzonFbsContainersTable(containersState.items);
    _ozonFbsContainersSetInfo("Удаляем грузоместо…");
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/delete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({
            source_id: sourceId,
            container_ids: [Number(cid) || cid],
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        const errs = Array.isArray(data.errors) ? data.errors : [];
        const errLine = errs.map((e) => e.error || e).filter(Boolean).join("; ");
        throw new Error(detailText(data.detail) || errLine || data.message || `Ошибка ${res.status}`);
      }
      renderOzonFbsContainersTable(data.items || []);
      _ozonFbsContainersSetInfo(String(data.message || "Удалено"), "ok");
      if (typeof window._ozonFbsContainerInvalidate === "function") {
        void window._ozonFbsContainerInvalidate();
      }
    } catch (e) {
      _ozonFbsContainersSetInfo(e.message || String(e), "error");
      await loadOzonFbsContainers({ keepInfo: true });
    } finally {
      containersState.busy = false;
      _ozonFbsContainersSyncBusyUi();
      renderOzonFbsContainersTable(containersState.items);
    }
  }

  async function approveOzonFbsContainer(containerId) {
    const sid = String(containersState.supplyId || "").trim();
    const sourceId = containersState.sourceId;
    const cid = String(containerId || "").trim();
    if (!sid || !sourceId || !cid || containersState.busy) return;

    let precheck = null;
    try {
      const params = new URLSearchParams({
        source_id: String(sourceId),
        container_id: String(cid),
      });
      const preRes = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/approve-precheck?${params}`,
        { headers: jsonHeaders() }
      );
      const preData = await preRes.json().catch(() => ({}));
      if (preRes.ok && preData && preData.ok !== false) {
        precheck = preData;
      }
    } catch (_e) {
      // Soft-fail: still allow confirm if precheck unavailable.
      precheck = null;
    }

    const syncCount = Number(precheck?.sync_error_count || 0) || 0;
    const unbound = Number(precheck?.unbound || 0) || 0;
    const total = Number(precheck?.total_orders || 0) || 0;
    const boundHere = Number(precheck?.bound_to_container || 0) || 0;
    const hasSyncErrors = !!precheck?.has_sync_errors || syncCount > 0;
    const hasUnbound = !!precheck?.has_unbound || unbound > 0;

    let msg =
      `Подтвердить грузоместо ${cid}?\n\n`
      + `После подтверждения в него больше нельзя будет сканировать заказы.`;
    if (boundHere > 0 || total > 0) {
      msg += `\n\nВ этом грузоместе (локально): ${boundHere}`;
      if (total > 0) msg += ` · заказов в поставке: ${total}`;
    }
    if (hasUnbound) {
      msg +=
        `\n\nВнимание: ${unbound} из ${total || "?"} заказов поставки ещё не привязаны `
        + `ни к одному грузоместу.`;
    }
    if (hasSyncErrors) {
      const samples = Array.isArray(precheck?.sync_errors) ? precheck.sync_errors : [];
      const sampleLine = samples
        .slice(0, 3)
        .map((e) => `${e.posting_number || "?"}: ${e.error || "ошибка"}`)
        .filter(Boolean)
        .join("\n");
      msg +=
        `\n\nЕсть ошибки синхронизации с Ozon (${syncCount}). `
        + `Состав на портале может отличаться.`;
      if (sampleLine) msg += `\n${sampleLine}`;
      msg += `\n\nПодтвердить всё равно?`;
      if (!window.confirm(msg)) return;
    } else {
      if (!window.confirm(msg)) return;
    }

    containersState.busy = true;
    _ozonFbsContainersSyncBusyUi();
    renderOzonFbsContainersTable(containersState.items);
    _ozonFbsContainersSetInfo("Подтверждаем грузоместо…");
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/approve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({
            source_id: sourceId,
            container_ids: [Number(cid) || cid],
            force: !!hasSyncErrors,
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        // Backend may still require force if precheck was stale/unavailable.
        const detail = data.detail;
        const needsForce =
          res.status === 409
          && detail
          && typeof detail === "object"
          && (detail.code === "container_sync_errors" || detail.precheck?.requires_force);
        if (needsForce && !hasSyncErrors) {
          const forceMsg =
            String(detail.message || "Есть ошибки синхронизации с Ozon.")
            + "\n\nПодтвердить всё равно?";
          if (!window.confirm(forceMsg)) {
            throw new Error(String(detail.message || "Подтверждение отменено"));
          }
          const res2 = await fetch(
            `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/approve`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json", ...jsonHeaders() },
              body: JSON.stringify({
                source_id: sourceId,
                container_ids: [Number(cid) || cid],
                force: true,
              }),
            }
          );
          const data2 = await res2.json().catch(() => ({}));
          if (!res2.ok || data2.ok === false) {
            const errs2 = Array.isArray(data2.errors) ? data2.errors : [];
            const errLine2 = errs2.map((e) => e.error || e).filter(Boolean).join("; ");
            throw new Error(
              detailText(data2.detail) || errLine2 || data2.message || `Ошибка ${res2.status}`
            );
          }
          renderOzonFbsContainersTable(data2.items || []);
          _ozonFbsContainersSetInfo(String(data2.message || "Подтверждено"), "ok");
          if (typeof window._ozonFbsContainerInvalidate === "function") {
            void window._ozonFbsContainerInvalidate();
          }
          return;
        }
        const errs = Array.isArray(data.errors) ? data.errors : [];
        const errLine = errs.map((e) => e.error || e).filter(Boolean).join("; ");
        throw new Error(detailText(data.detail) || errLine || data.message || `Ошибка ${res.status}`);
      }
      renderOzonFbsContainersTable(data.items || []);
      _ozonFbsContainersSetInfo(String(data.message || "Подтверждено"), "ok");
      if (typeof window._ozonFbsContainerInvalidate === "function") {
        void window._ozonFbsContainerInvalidate();
      }
    } catch (e) {
      _ozonFbsContainersSetInfo(e.message || String(e), "error");
      await loadOzonFbsContainers({ keepInfo: true });
    } finally {
      containersState.busy = false;
      _ozonFbsContainersSyncBusyUi();
      renderOzonFbsContainersTable(containersState.items);
    }
  }

  async function printOzonFbsContainerLabel(containerId) {
    const sid = String(containersState.supplyId || "").trim();
    const sourceId = containersState.sourceId;
    const cid = String(containerId || "").trim();
    if (!sid || !sourceId || !cid || containersState.busy) return;
    containersState.busy = true;
    _ozonFbsContainersSyncBusyUi();
    renderOzonFbsContainersTable(containersState.items);
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/containers/labels`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({
            source_id: sourceId,
            container_ids: [Number(cid) || cid],
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(detailText(data.detail) || data.message || `Ошибка ${res.status}`);
      }
      const b64 = String(data.file_content || "").trim();
      if (!b64) throw new Error("Ozon не вернул PDF этикетки");
      const byteChars = atob(b64);
      const bytes = new Uint8Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i += 1) bytes[i] = byteChars.charCodeAt(i);
      const blob = new Blob([bytes], { type: String(data.content_type || "application/pdf") });
      const url = URL.createObjectURL(blob);
      const win = window.open(url, "_blank");
      if (!win) {
        const a = document.createElement("a");
        a.href = url;
        a.download = `ozon-container-${cid}.pdf`;
        a.click();
      }
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      _ozonFbsContainersSetInfo(`Этикетка ${cid} готова`, "ok");
    } catch (e) {
      _ozonFbsContainersSetInfo(e.message || String(e), "error");
    } finally {
      containersState.busy = false;
      _ozonFbsContainersSyncBusyUi();
      renderOzonFbsContainersTable(containersState.items);
    }
  }

  function fillShipmentsMethods(methods, selectedId, selectedName) {
    const sel = document.getElementById("ozonFbsShipmentsMethod");
    if (!sel) return;
    let list = Array.isArray(methods) ? methods.slice() : [];
    if (!list.length && selectedId) {
      list = [{
        id: selectedId,
        name: String(selectedName || `Метод ${selectedId}`),
      }];
    }
    if (!list.length) {
      sel.innerHTML = `<option value="">Нет активных методов</option>`;
      return;
    }
    const selectedKey = String(selectedId ?? "");
    sel.innerHTML = list.map((m) => {
      const id = String(m.id ?? "");
      const name = esc(m.name || `Метод ${id}`);
      const selected = selectedKey === id ? " selected" : "";
      return `<option value="${esc(id)}"${selected}>${name}</option>`;
    }).join("");
  }

  function listShipmentsFormedCarriages(data) {
    const out = [];
    const blocks = Array.isArray(data?.blocks) ? data.blocks : [];
    for (const block of blocks) {
      const carriages = Array.isArray(block?.carriages) ? block.carriages : [];
      for (const c of carriages) {
        if (!c?.is_formed || !c?.carriage_id) continue;
        const barcode = c.barcode && typeof c.barcode === "object" ? c.barcode : null;
        out.push({ carriage: c, barcode, block });
      }
    }
    return out;
  }

  function resolveShipmentsBarcode(data, carriageId) {
    const formed = listShipmentsFormedCarriages(data);
    const want = carriageId != null && String(carriageId).trim() !== ""
      ? Number(carriageId)
      : null;
    if (want && Number.isFinite(want) && want > 0) {
      const hit = formed.find((x) => Number(x.carriage.carriage_id) === want);
      // Never fall back to another carriage's ШК — API is per carriage_id.
      if (hit) return hit.barcode || null;
    }
    const withBc = formed.find((x) => x.barcode);
    if (withBc?.barcode) return withBc.barcode;
    return data?.barcode || null;
  }

  function ensureShipmentsSelectedCarriage(data) {
    const formed = listShipmentsFormedCarriages(data);
    if (!formed.length) {
      shipmentsState.selectedCarriageId = null;
      return null;
    }
    const preferred = Number(
      data?.selected_carriage_id
      || data?.formed_act_id
      || shipmentsState.selectedCarriageId
      || 0
    );
    if (preferred > 0 && formed.some((x) => Number(x.carriage.carriage_id) === preferred)) {
      shipmentsState.selectedCarriageId = preferred;
      return preferred;
    }
    const first = formed.find((x) => x.barcode) || formed[0];
    const id = Number(first.carriage.carriage_id);
    shipmentsState.selectedCarriageId = id > 0 ? id : null;
    return shipmentsState.selectedCarriageId;
  }

  function renderShipmentsBarcodePanel(data) {
    const selectedId = ensureShipmentsSelectedCarriage(data);
    const barcode = resolveShipmentsBarcode(data, selectedId);
    const text = String(barcode?.barcode_text || "").trim();
    const labelB64 = String(barcode?.barcode_label_base64 || "").trim();
    const b64 = String(barcode?.barcode_image_base64 || "").trim();
    const ctype = String(barcode?.content_type || "image/png").trim() || "image/png";
    const hasLabel = Boolean(labelB64);
    const hasImg = Boolean(b64);
    const canPrint = Boolean(hasLabel || hasImg || text);
    const formed = listShipmentsFormedCarriages(data);
    const selectedLabel = formed.find((x) => Number(x.carriage.carriage_id) === Number(selectedId));
    const caption = selectedLabel
      ? esc(selectedLabel.carriage.label || `Отгрузка ${selectedId}`)
      : "";
    const visual = hasLabel
      ? `<img id="ozonFbsShipmentsBarcodeImg" src="data:image/png;base64,${labelB64}" alt="Штрихкод поставки ${esc(text)}" />`
      : (hasImg
        ? `<img id="ozonFbsShipmentsBarcodeImg" src="data:${esc(ctype)};base64,${b64}" alt="Штрихкод поставки" />`
        : (text
          ? `<div class="ozon-fbs-shipments-barcode-empty">ШК: ${esc(text)}</div>`
          : `<div class="ozon-fbs-shipments-barcode-empty">Штрихкод появится после формирования отгрузки</div>`));
    const textHtml = (!hasLabel && text)
      ? `<div class="ozon-fbs-shipments-barcode-text">${esc(text)}</div>`
      : "";
    const captionHtml = caption
      ? `<div class="ozon-fbs-shipments-barcode-caption">${caption}</div>`
      : "";
    return `
      <div class="ozon-fbs-shipments-barcode-main">
        ${captionHtml}
        <div class="ozon-fbs-shipments-barcode-visual">
          ${visual}
          ${textHtml}
        </div>
        <div class="ozon-fbs-shipments-barcode-actions">
          <button type="button" class="ozon-fbs-shipments-icon-btn" ${canPrint ? "" : "disabled"}
                  onclick="ozonFbsShipmentsPrintBarcode()" title="Печать" aria-label="Печать штрихкода">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M7 9V4h10v5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M7 17H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <rect x="7" y="13" width="10" height="7" rx="1" stroke="currentColor" stroke-width="2"/>
            </svg>
          </button>
          <button type="button" class="ozon-fbs-shipments-icon-btn" ${canPrint ? "" : "disabled"}
                  onclick="ozonFbsShipmentsDownloadBarcode()" title="Скачать" aria-label="Скачать штрихкод">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 4v10M8 10l4 4 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M5 19h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            </svg>
          </button>
        </div>
      </div>`;
  }

  function renderShipmentsMetaColumn(block, data) {
    if (!block) {
      return `<div class="ozon-fbs-shipments-meta-col"><div class="ozon-fbs-shipments-meta-empty">Нет данных отгрузки</div></div>`;
    }
    const rows = [
      ["Склад", block.warehouse_name || data?.warehouse_name || "—"],
      ["Пункт", block.dropoff_point_type_label || "Сортировочный центр"],
      ["Способ отгрузки", block.shipment_method_label || "В пункт приема"],
      ["Адрес", block.dropoff_address || "—"],
      ["Собрано заказов", block.collected_label || "—"],
      ["Приём отправлений", block.acceptance_label || "—"],
    ];
    const rowsHtml = rows.map(([label, value]) => `
      <div class="ozon-fbs-shipments-meta-item">
        <span class="ozon-fbs-shipments-meta-label">${esc(label)}</span>
        <span class="ozon-fbs-shipments-meta-value">${esc(value)}</span>
      </div>`).join("");
    return `
      <div class="ozon-fbs-shipments-meta-col">
        <h4 class="ozon-fbs-shipments-block-title">${esc(block.day_label || "Ozon")}</h4>
        ${rowsHtml}
      </div>`;
  }

  function renderShipmentsCarriages(blocks) {
    const list = Array.isArray(blocks) ? blocks : [];
    if (!list.length) {
      return `<div class="ozon-fbs-shipments-loading">Нет данных отгрузки на выбранную дату</div>`;
    }
    const selectedId = Number(shipmentsState.selectedCarriageId || 0);
    return list.map((block) => {
      const carriages = Array.isArray(block.carriages) ? block.carriages : [];
      return carriages.map((c) => {
        const formed = Boolean(c.is_formed);
        const statusLabel = String(c.status_label || "Не сформирована");
        const awaiting = statusLabel.toLowerCase().includes("ожидает");
        const statusCls = formed
          ? (awaiting ? " is-awaiting" : " is-formed")
          : "";
        const count = Number(c.postings_count || 0);
        const cid = Number(c.carriage_id || 0);
        const canForm = Boolean(c.can_form) && !shipmentsState.forming;
        const hasBarcode = Boolean(
          c.barcode?.barcode_text
          || c.barcode?.barcode_image_base64
          || c.barcode?.barcode_label_base64
        );
        const isSelected = formed && cid > 0 && cid === selectedId;
        const formBtn = formed
          ? ""
          : `<button type="button" class="ozon-fbs-shipments-form-btn"
                     ${canForm ? "" : "disabled"}
                     onclick="event.stopPropagation(); ozonFbsShipmentsForm()">Сформировать</button>`;
        const picking = block.assembly_list_availability !== false
          ? `<button type="button" class="ozon-fbs-shipments-link"
                     onclick="event.stopPropagation(); ozonFbsOpenPickingList()">Лист подбора</button>`
          : "";
        const bcBtns = (formed && cid > 0)
          ? `<button type="button" class="ozon-fbs-shipments-icon-btn" ${hasBarcode ? "" : "disabled"}
                     onclick="event.stopPropagation(); ozonFbsShipmentsPrintBarcode(${cid})"
                     title="Печать ШК отгрузки" aria-label="Печать ШК отгрузки">
               <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                 <path d="M7 9V4h10v5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                 <path d="M7 17H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                 <rect x="7" y="13" width="10" height="7" rx="1" stroke="currentColor" stroke-width="2"/>
               </svg>
             </button>
             <button type="button" class="ozon-fbs-shipments-icon-btn" ${hasBarcode ? "" : "disabled"}
                     onclick="event.stopPropagation(); ozonFbsShipmentsDownloadBarcode(${cid})"
                     title="Скачать ШК отгрузки" aria-label="Скачать ШК отгрузки">
               <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                 <path d="M12 4v10M8 10l4 4 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                 <path d="M5 19h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
               </svg>
             </button>`
          : "";
        const selectAttr = (formed && cid > 0)
          ? `role="button" tabindex="0" data-carriage-id="${cid}"
             onclick="ozonFbsShipmentsSelectCarriage(${cid})"
             onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();ozonFbsShipmentsSelectCarriage(${cid});}"`
          : "";
        return `
          <div class="ozon-fbs-shipments-carriage${isSelected ? " is-selected" : ""}${formed && cid > 0 ? " is-selectable" : ""}"
               ${selectAttr}>
            <span class="ozon-fbs-shipments-carriage-title">${esc(c.label || "Отгрузка")}</span>
            <span class="ozon-fbs-shipments-carriage-count">${count} отправлений</span>
            <span class="ozon-fbs-shipments-status${statusCls}">${esc(statusLabel)}</span>
            <div class="ozon-fbs-shipments-carriage-actions">
              ${bcBtns}
              ${formBtn}
              ${picking}
            </div>
          </div>`;
      }).join("");
    }).join("");
  }

  function renderShipmentsView(data) {
    const body = document.getElementById("ozonFbsShipmentsBody");
    if (!body) return;
    if (!data) {
      body.innerHTML = `<div class="ozon-fbs-shipments-loading">Нет данных</div>`;
      return;
    }
    if (data.ok === false && data.message && !(Array.isArray(data.blocks) && data.blocks.length)) {
      body.innerHTML = `<div class="ozon-fbs-shipments-error">${esc(data.message)}</div>`;
      return;
    }
    const blocks = Array.isArray(data.blocks) ? data.blocks : [];
    const primary = blocks[0] || null;
    ensureShipmentsSelectedCarriage(data);
    body.innerHTML = `
      <section class="ozon-fbs-shipments-card">
        <div class="ozon-fbs-shipments-top">
          ${renderShipmentsBarcodePanel(data)}
          ${renderShipmentsMetaColumn(primary, data)}
        </div>
        <div class="ozon-fbs-shipments-carriages">
          ${renderShipmentsCarriages(blocks)}
        </div>
      </section>`;
  }

  function selectShipmentsCarriage(carriageId) {
    const id = Number(carriageId || 0);
    if (!id) return;
    shipmentsState.selectedCarriageId = id;
    renderShipmentsView(shipmentsState.data);
  }

  async function loadShipments() {
    const sid = shipmentsState.supplyId;
    const sourceId = shipmentsState.sourceId;
    const body = document.getElementById("ozonFbsShipmentsBody");
    if (!sid || !sourceId) return;
    const dateEl = document.getElementById("ozonFbsShipmentsDate");
    const methodEl = document.getElementById("ozonFbsShipmentsMethod");
    const day = String(dateEl?.value || todayIsoDate());
    const methodId = String(methodEl?.value || "").trim();
    shipmentsState.loading = true;
    if (body) body.innerHTML = `<div class="ozon-fbs-shipments-loading">Загрузка отгрузок…</div>`;
    try {
      const qs = new URLSearchParams({
        source_id: String(sourceId),
        departure_date: day,
      });
      if (methodId) qs.set("delivery_method_id", methodId);
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/shipments?${qs.toString()}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Не удалось загрузить отгрузки");
      shipmentsState.data = data;
      fillShipmentsMethods(
        data.delivery_methods,
        data.selected_delivery_method_id,
        data.selected_delivery_method_name
      );
      if (dateEl && data.departure_date) dateEl.value = String(data.departure_date).slice(0, 10);
      renderShipmentsView(data);
    } catch (e) {
      if (body) {
        body.innerHTML = `<div class="ozon-fbs-shipments-error">${esc(e.message || e)}</div>`;
      }
    } finally {
      shipmentsState.loading = false;
    }
  }

  async function openShipmentsModal() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) {
      alert("Откройте поставку");
      return;
    }
    shipmentsState.supplyId = sid;
    shipmentsState.sourceId = sourceId;
    shipmentsState.data = null;
    const modal = document.getElementById("ozonFbsShipmentsModal");
    const dateEl = document.getElementById("ozonFbsShipmentsDate");
    const methodEl = document.getElementById("ozonFbsShipmentsMethod");
    if (dateEl && !dateEl.value) dateEl.value = todayIsoDate();
    if (methodEl) methodEl.innerHTML = `<option value="">Загрузка…</option>`;
    if (modal) modal.classList.remove("hidden");
    await loadShipments();
  }

  /**
   * Local only: move supply awaiting_deliver → delivering and deduct Остатки.
   * Does not call Ozon. Uses in-app confirm/notice modals (not browser dialogs).
   */
  const moveDeliveringModalState = { mode: "confirm", busy: false };

  function _ozonFbsMoveDeliveringSetVisible(show) {
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsMoveDeliveringModal", !!show);
      return;
    }
    const modal = document.getElementById("ozonFbsMoveDeliveringModal");
    if (!modal) return;
    modal.classList.toggle("hidden", !show);
  }

  function closeOzonFbsMoveDeliveringModal() {
    if (moveDeliveringModalState.busy) return;
    moveDeliveringModalState.mode = "confirm";
    _ozonFbsMoveDeliveringSetVisible(false);
  }

  function _ozonFbsMoveDeliveringRender(mode, { title, html, kind } = {}) {
    moveDeliveringModalState.mode = mode;
    const titleEl = document.getElementById("ozonFbsMoveDeliveringTitle");
    const body = document.getElementById("ozonFbsMoveDeliveringBody");
    const cancelBtn = document.getElementById("ozonFbsMoveDeliveringCancelBtn");
    const confirmBtn = document.getElementById("ozonFbsMoveDeliveringConfirmBtn");
    const okBtn = document.getElementById("ozonFbsMoveDeliveringOkBtn");
    const card = document.querySelector("#ozonFbsMoveDeliveringModal .ozon-fbs-move-delivering-modal");
    if (titleEl) titleEl.textContent = title || "Перенести в доставку";
    if (body) body.innerHTML = html || "";
    if (card) {
      card.classList.toggle("is-error", kind === "error");
      card.classList.toggle("is-ok", kind === "ok");
    }
    const isConfirm = mode === "confirm";
    if (cancelBtn) cancelBtn.hidden = !isConfirm;
    if (confirmBtn) {
      confirmBtn.hidden = !isConfirm;
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Перенести";
    }
    if (okBtn) okBtn.hidden = isConfirm;
    _ozonFbsMoveDeliveringSetVisible(true);
  }

  function _ozonFbsMoveDeliveringNotice(message, { title, kind } = {}) {
    const msg = String(message || "").trim() || "Готово";
    const lines = msg.split("\n").map((l) => l.trim()).filter(Boolean);
    const html = lines.map((l) => `<p class="ozon-fbs-move-delivering-text">${esc(l)}</p>`).join("");
    _ozonFbsMoveDeliveringRender("notice", {
      title: title || (kind === "error" ? "Не удалось перенести" : "Поставка перенесена"),
      html,
      kind: kind || "ok",
    });
  }

  function moveOzonFbsSupplyToDelivering() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) {
      _ozonFbsMoveDeliveringNotice(
        "Откройте поставку и дождитесь загрузки заказов",
        { title: "Перенести в доставку", kind: "error" }
      );
      return;
    }
    if (isDeliveringSuppliesTab() || isSupplyDetailReadOnly()) {
      _ozonFbsMoveDeliveringNotice(
        "Поставка уже в «Доставляются»",
        { title: "Перенести в доставку", kind: "error" }
      );
      return;
    }
    const name = String(supplyDetailState.supply?.name || sid).trim();
    const orderN = Number(supplyDetailState.supply?.order_count || 0);
    const orderLabel = orderN > 0 ? String(orderN) : "Все";
    _ozonFbsMoveDeliveringRender("confirm", {
      title: "Перенести в доставку",
      html: `
        <p class="ozon-fbs-move-delivering-lead">
          Перенести поставку «${esc(name)}» в «Доставляются»?
        </p>
        <ul class="ozon-fbs-move-delivering-list">
          <li>На Ozon ничего не отправится</li>
          <li>${esc(orderLabel)} отправлений уйдут из «Ожидают отгрузки»</li>
          <li>Продукция спишется с Остатки прямо сейчас</li>
          <li>При следующей сборке заказов создастся новая поставка</li>
        </ul>
      `,
    });
  }

  async function confirmOzonFbsMoveDelivering() {
    if (moveDeliveringModalState.mode !== "confirm" || moveDeliveringModalState.busy) return;
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    const btn = document.getElementById("ozonFbsSupplyDetailMoveDeliveringBtn");
    const confirmBtn = document.getElementById("ozonFbsMoveDeliveringConfirmBtn");
    if (!sid || !sourceId) {
      _ozonFbsMoveDeliveringNotice(
        "Откройте поставку и дождитесь загрузки заказов",
        { title: "Перенести в доставку", kind: "error" }
      );
      return;
    }
    moveDeliveringModalState.busy = true;
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Перенос…";
    }
    if (btn) {
      btn.setAttribute("aria-disabled", "true");
      btn.classList.add("is-wait-orders");
    }
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/move-to-delivering`
          + `?source_id=${encodeURIComponent(sourceId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      closeSupplyDetailModal();
      setTab("delivering");
      const moved = Number(data.moved || 0);
      const shipped = Number(data.stock?.shipped || 0);
      const base = String(data.message || "Поставка перенесена в «Доставляются»");
      const stockNote = moved > 0
        ? (shipped > 0
          ? `Списание с Остатки: записей ${shipped}`
          : "Списание с Остатки: будет при следующей синхронизации / нет производства")
        : "";
      moveDeliveringModalState.busy = false;
      _ozonFbsMoveDeliveringNotice(
        stockNote ? `${base}\n${stockNote}` : base,
        { title: "Поставка перенесена", kind: "ok" }
      );
      showSyncInfo(base, "ok");
    } catch (e) {
      moveDeliveringModalState.busy = false;
      _ozonFbsMoveDeliveringNotice(e.message || String(e), {
        title: "Не удалось перенести",
        kind: "error",
      });
    } finally {
      moveDeliveringModalState.busy = false;
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Перенести";
      }
      if (btn) {
        btn.removeAttribute("aria-disabled");
        btn.classList.remove("is-wait-orders");
      }
    }
  }

  /**
   * Local only: move selected delivering supplies → awaiting_deliver and restore Остатки.
   * Does not call Ozon. Selection bottom bar on «Доставляются».
   */
  const moveAwaitingModalState = { mode: "confirm", busy: false, supplyIds: [] };

  function _ozonFbsMoveAwaitingSetVisible(show) {
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsMoveAwaitingModal", !!show);
      return;
    }
    const modal = document.getElementById("ozonFbsMoveAwaitingModal");
    if (!modal) return;
    modal.classList.toggle("hidden", !show);
  }

  function closeOzonFbsMoveAwaitingModal() {
    if (moveAwaitingModalState.busy) return;
    moveAwaitingModalState.mode = "confirm";
    moveAwaitingModalState.supplyIds = [];
    _ozonFbsMoveAwaitingSetVisible(false);
  }

  function _ozonFbsMoveAwaitingRender(mode, { title, html, kind } = {}) {
    moveAwaitingModalState.mode = mode;
    const titleEl = document.getElementById("ozonFbsMoveAwaitingTitle");
    const body = document.getElementById("ozonFbsMoveAwaitingBody");
    const cancelBtn = document.getElementById("ozonFbsMoveAwaitingCancelBtn");
    const confirmBtn = document.getElementById("ozonFbsMoveAwaitingConfirmBtn");
    const okBtn = document.getElementById("ozonFbsMoveAwaitingOkBtn");
    const card = document.querySelector("#ozonFbsMoveAwaitingModal .ozon-fbs-move-delivering-modal");
    if (titleEl) titleEl.textContent = title || "В «Ожидают отгрузки»";
    if (body) body.innerHTML = html || "";
    if (card) {
      card.classList.toggle("is-error", kind === "error");
      card.classList.toggle("is-ok", kind === "ok");
    }
    const isConfirm = mode === "confirm";
    if (cancelBtn) cancelBtn.hidden = !isConfirm;
    if (confirmBtn) {
      confirmBtn.hidden = !isConfirm;
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Перенести";
    }
    if (okBtn) okBtn.hidden = isConfirm;
    _ozonFbsMoveAwaitingSetVisible(true);
  }

  function _ozonFbsMoveAwaitingNotice(message, { title, kind } = {}) {
    const text = String(message || "").trim() || "Готово";
    const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
    const html = lines.map((l) => `<p class="ozon-fbs-move-delivering-text">${esc(l)}</p>`).join("");
    _ozonFbsMoveAwaitingRender("notice", {
      title: title || "Готово",
      html,
      kind: kind || "ok",
    });
  }

  function _ozonFbsSelectedSupplyLabel(n) {
    const abs = Math.abs(Number(n) || 0) % 100;
    const last = abs % 10;
    let word = "поставок";
    if (!(abs > 10 && abs < 20)) {
      if (last === 1) word = "поставку";
      else if (last >= 2 && last <= 4) word = "поставки";
    }
    return `${n} ${word}`;
  }

  function openOzonFbsMoveSelectedToAwaitingDeliver() {
    if (!isDeliveringSuppliesTab()) {
      _ozonFbsMoveAwaitingNotice(
        "Выберите поставки на вкладке «Доставляются»",
        { title: "В «Ожидают отгрузки»", kind: "error" }
      );
      return;
    }
    const sourceId = state.sourceId;
    if (!sourceId) {
      _ozonFbsMoveAwaitingNotice(
        "Сначала выберите источник Ozon FBS",
        { title: "В «Ожидают отгрузки»", kind: "error" }
      );
      return;
    }
    const ids = [...state.selected]
      .map((x) => String(x || "").trim())
      .filter(Boolean);
    if (!ids.length) {
      _ozonFbsMoveAwaitingNotice(
        "Отметьте одну или несколько поставок",
        { title: "В «Ожидают отгрузки»", kind: "error" }
      );
      return;
    }
    moveAwaitingModalState.supplyIds = ids;
    const orderTotal = ids.reduce((sum, sid) => {
      const row = (state.items || []).find(
        (s) => String(s.supply_id || "").trim() === sid
      );
      return sum + Number(row?.order_count || 0);
    }, 0);
    const names = ids.slice(0, 3).map((sid) => {
      const row = (state.items || []).find(
        (s) => String(s.supply_id || "").trim() === sid
      );
      return String(row?.name || sid).trim() || sid;
    });
    const namesNote = names.length
      ? `<li>${esc(names.join(", "))}${ids.length > 3 ? "…" : ""}</li>`
      : "";
    const orderLine = orderTotal > 0
      ? `<li>${esc(String(orderTotal))} отправлений вернутся в «Ожидают отгрузки»</li>`
      : "<li>Отправления поставки вернутся в «Ожидают отгрузки»</li>";
    _ozonFbsMoveAwaitingRender("confirm", {
      title: "В «Ожидают отгрузки»",
      html: `
        <p class="ozon-fbs-move-delivering-lead">
          Вернуть ${_ozonFbsSelectedSupplyLabel(ids.length)} в «Ожидают отгрузки»?
        </p>
        <ul class="ozon-fbs-move-delivering-list">
          ${namesNote}
          <li>На Ozon ничего не отправится</li>
          ${orderLine}
          <li>Количество вернётся на Остатки</li>
          <li>Можно снова добавлять заказы через «Собрать все» или «Добавить к существующей»</li>
          <li>Если в Ozon уже «Доставляются», синхронизация может снова перенести поставку</li>
        </ul>
      `,
    });
  }

  async function confirmOzonFbsMoveAwaiting() {
    if (moveAwaitingModalState.mode !== "confirm" || moveAwaitingModalState.busy) return;
    const sourceId = state.sourceId;
    const ids = (moveAwaitingModalState.supplyIds || [])
      .map((x) => String(x || "").trim())
      .filter(Boolean);
    const confirmBtn = document.getElementById("ozonFbsMoveAwaitingConfirmBtn");
    if (!sourceId || !ids.length) {
      _ozonFbsMoveAwaitingNotice(
        "Выберите поставки на вкладке «Доставляются»",
        { title: "В «Ожидают отгрузки»", kind: "error" }
      );
      return;
    }
    moveAwaitingModalState.busy = true;
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Перенос…";
    }
    let movedTotal = 0;
    let reversedTotal = 0;
    const errors = [];
    try {
      for (const sid of ids) {
        try {
          const res = await fetch(
            `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/move-to-awaiting-deliver`
              + `?source_id=${encodeURIComponent(sourceId)}`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json", ...jsonHeaders() },
            }
          );
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
          }
          movedTotal += Number(data.moved || 0);
          reversedTotal += Number(data.stock?.reversed || 0);
        } catch (e) {
          errors.push(`${sid}: ${e.message || e}`);
        }
      }
      const okN = ids.length - errors.length;
      // Only leave «Доставляются» when at least one supply actually moved.
      if (okN > 0) {
        clearSelection();
        setTab("awaiting_deliver");
      }
      const base = errors.length
        ? `Перенесено поставок: ${okN} из ${ids.length}`
        : `Перенесено в «Ожидают отгрузки»: ${_ozonFbsSelectedSupplyLabel(okN)}`;
      const detailParts = [];
      if (movedTotal > 0) detailParts.push(`отправлений ${movedTotal}`);
      if (reversedTotal > 0) detailParts.push(`возврат на Остатки: записей ${reversedTotal}`);
      else if (movedTotal > 0) {
        detailParts.push("возврат на Остатки: будет при следующей синхронизации / нет производства");
      }
      const stockNote = detailParts.join("; ");
      const errNote = errors.length
        ? `\nОшибки:\n${errors.slice(0, 5).join("\n")}${errors.length > 5 ? "\n…" : ""}`
        : "";
      moveAwaitingModalState.busy = false;
      _ozonFbsMoveAwaitingNotice(
        (stockNote ? `${base}\n${stockNote}` : base) + errNote,
        {
          title: okN === 0
            ? "Не удалось перенести"
            : (errors.length ? "Перенос с ошибками" : "Поставки перенесены"),
          kind: okN === 0 ? "error" : (errors.length ? "error" : "ok"),
        }
      );
      showSyncInfo(base, okN === 0 ? "error" : (errors.length ? "warn" : "ok"));
    } catch (e) {
      moveAwaitingModalState.busy = false;
      _ozonFbsMoveAwaitingNotice(e.message || String(e), {
        title: "Не удалось перенести",
        kind: "error",
      });
    } finally {
      moveAwaitingModalState.busy = false;
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = "Перенести";
      }
    }
  }

  const movePostingState = {
    postingNumber: "",
    selectedSupplyId: "",
    selectedTab: "",
    items: [],
  };

  function closeOzonFbsMovePostingModal() {
    movePostingState.postingNumber = "";
    movePostingState.selectedSupplyId = "";
    movePostingState.selectedTab = "";
    movePostingState.items = [];
    const err = document.getElementById("ozonFbsMovePostingErr");
    if (err) {
      err.hidden = true;
      err.textContent = "";
    }
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsMovePostingModal", false);
    } else {
      document.getElementById("ozonFbsMovePostingModal")?.classList.add("hidden");
    }
  }

  function _ozonFbsMovePostingSetErr(text) {
    const err = document.getElementById("ozonFbsMovePostingErr");
    if (!err) return;
    const msg = String(text || "").trim();
    err.hidden = !msg;
    err.textContent = msg;
  }

  function _ozonFbsMovePostingSelect(supplyId, tab) {
    movePostingState.selectedSupplyId = String(supplyId || "").trim();
    movePostingState.selectedTab = String(tab || "").trim();
    const body = document.getElementById("ozonFbsMovePostingBody");
    if (body) {
      body.querySelectorAll(".ozon-fbs-move-supply-row").forEach((row) => {
        const sid = String(row.getAttribute("data-supply-id") || "");
        const t = String(row.getAttribute("data-tab") || "");
        const on =
          sid === movePostingState.selectedSupplyId &&
          t === movePostingState.selectedTab;
        row.classList.toggle("is-selected", on);
        const inp = row.querySelector('input[type="radio"]');
        if (inp) inp.checked = on;
      });
    }
    const btn = document.getElementById("ozonFbsMovePostingConfirmBtn");
    if (btn) btn.disabled = !movePostingState.selectedSupplyId;
    _ozonFbsMovePostingSetErr("");
  }

  function _ozonFbsMovePostingRenderList(groups) {
    const body = document.getElementById("ozonFbsMovePostingBody");
    if (!body) return;
    const sections = [
      { key: "awaiting_deliver", title: "Ожидают отгрузки", items: groups.awaiting_deliver || [] },
      { key: "delivering", title: "Доставляются", items: groups.delivering || [] },
    ];
    const flat = [];
    let html = "";
    for (const sec of sections) {
      if (!sec.items.length) continue;
      html += `<div class="ozon-fbs-move-section">`;
      html += `<h4 class="ozon-fbs-move-section-title">${esc(sec.title)}</h4>`;
      html += sec.items.map((s) => {
        flat.push(s);
        const sid = String(s.supply_id || "").trim();
        const tab = String(s.tab || sec.key).trim();
        const name = String(s.name || sid).trim() || sid;
        const count = Number(s.order_count || 0) || 0;
        const wh = String(s.warehouse_name || "").trim();
        const id = `ozonFbsMoveSupply_${esc(tab)}_${esc(sid)}`;
        return `<label class="ozon-fbs-move-supply-row" data-supply-id="${esc(sid)}" data-tab="${esc(tab)}" for="${id}">
          <input type="radio" name="ozonFbsMoveSupply" id="${id}"
                 onchange="selectOzonFbsMovePostingTarget('${esc(sid)}', '${esc(tab)}')" />
          <span class="ozon-fbs-move-supply-main">
            <span class="ozon-fbs-move-supply-name">${esc(name)}</span>
            <span class="ozon-fbs-move-supply-meta">${esc(sid)} · ${esc(count)} отпр.${wh ? " · " + esc(wh) : ""}</span>
          </span>
        </label>`;
      }).join("");
      html += `</div>`;
    }
    movePostingState.items = flat;
    if (!html) {
      body.innerHTML = `<div class="wb-fbs-empty">Нет локальных поставок в «Ожидают отгрузки» и «Доставляются»</div>`;
    } else {
      body.innerHTML = html;
    }
    const btn = document.getElementById("ozonFbsMovePostingConfirmBtn");
    if (btn) btn.disabled = true;
  }

  async function openOzonFbsMovePostingModal(postingNumber) {
    closeOzonFbsRowMenus();
    const pn = String(postingNumber || "").trim();
    if (!pn || !state.sourceId) {
      alert("Не удалось определить отправление или источник");
      return;
    }
    movePostingState.postingNumber = pn;
    movePostingState.selectedSupplyId = "";
    movePostingState.selectedTab = "";
    _ozonFbsMovePostingSetErr("");
    const lead = document.getElementById("ozonFbsMovePostingLead");
    if (lead) {
      lead.textContent =
        `Отправление ${pn}: выберите локальную поставку. В Ozon ничего не отправляется.`;
    }
    const body = document.getElementById("ozonFbsMovePostingBody");
    if (body) body.innerHTML = `<div class="wb-fbs-empty">Загрузка поставок…</div>`;
    const confirmBtn = document.getElementById("ozonFbsMovePostingConfirmBtn");
    if (confirmBtn) confirmBtn.disabled = true;
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsMovePostingModal", true);
    } else {
      document.getElementById("ozonFbsMovePostingModal")?.classList.remove("hidden");
    }
    try {
      const res = await fetch(
        `/api/ozon-fbs/postings/move-targets?source_id=${encodeURIComponent(state.sourceId)}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      _ozonFbsMovePostingRenderList(data);
    } catch (e) {
      if (body) {
        body.innerHTML = `<div class="wb-fbs-empty" style="color:#b91c1c">${esc(String(e.message || e))}</div>`;
      }
    }
  }

  function selectOzonFbsMovePostingTarget(supplyId, tab) {
    _ozonFbsMovePostingSelect(supplyId, tab);
  }

  async function confirmOzonFbsMovePosting() {
    const pn = String(movePostingState.postingNumber || "").trim();
    const sid = String(movePostingState.selectedSupplyId || "").trim();
    const tab = String(movePostingState.selectedTab || "").trim();
    if (!pn || !sid || !state.sourceId) {
      _ozonFbsMovePostingSetErr("Выберите поставку");
      return;
    }
    const btn = document.getElementById("ozonFbsMovePostingConfirmBtn");
    if (btn) btn.disabled = true;
    _ozonFbsMovePostingSetErr("");
    try {
      const res = await fetch(
        `/api/ozon-fbs/postings/${encodeURIComponent(pn)}/move-to-supply`,
        {
          method: "POST",
          headers: jsonHeaders(),
          body: JSON.stringify({
            source_id: state.sourceId,
            supply_id: sid,
            target_tab: tab || undefined,
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      closeOzonFbsMovePostingModal();
      const msg = String(data.message || "Перенесено локально");
      showSyncInfo(msg);
      if (state.lookupMode && parsePostingNumberQuery(state.search) === pn) {
        try {
          // Local-only reload: remote status refresh would overwrite the tab
          // we just set for reprint / re-ship workflow.
          const lookup = await lookupPostingByNumber(pn, { refresh: false });
          if (lookup) applyLookupResult(lookup, pn);
        } catch (_e) {
          /* ignore — move already succeeded */
        }
      } else {
        await loadPostings(false);
      }
      alert(msg);
    } catch (e) {
      _ozonFbsMovePostingSetErr(String(e.message || e));
      if (btn) btn.disabled = false;
    }
  }

  async function formShipmentsCarriage() {
    const sid = shipmentsState.supplyId;
    const sourceId = shipmentsState.sourceId;
    if (!sid || !sourceId || shipmentsState.forming) return;
    const dateEl = document.getElementById("ozonFbsShipmentsDate");
    const methodEl = document.getElementById("ozonFbsShipmentsMethod");
    const day = String(dateEl?.value || todayIsoDate());
    const methodId = String(methodEl?.value || "").trim();
    if (!methodId) {
      alert("Выберите метод доставки");
      return;
    }
    shipmentsState.forming = true;
    renderShipmentsView(shipmentsState.data);
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/shipments/form`,
        {
          method: "POST",
          headers: jsonHeaders(),
          body: JSON.stringify({
            source_id: Number(sourceId),
            departure_date: day,
            delivery_method_id: Number(methodId),
          }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Ошибка формирования");
      shipmentsState.data = data;
      fillShipmentsMethods(
        data.delivery_methods,
        data.selected_delivery_method_id,
        data.selected_delivery_method_name
      );
      renderShipmentsView(data);
      if (data.message) showSyncInfo(String(data.message));
    } catch (e) {
      alert(e.message || String(e));
      renderShipmentsView(shipmentsState.data);
    } finally {
      shipmentsState.forming = false;
      renderShipmentsView(shipmentsState.data);
    }
  }

  function shipmentsPrintBarcode(carriageId) {
    const sid = shipmentsState.supplyId;
    const sourceId = shipmentsState.sourceId;
    if (!sid || !sourceId) return;
    const dateEl = document.getElementById("ozonFbsShipmentsDate");
    const methodEl = document.getElementById("ozonFbsShipmentsMethod");
    const day = String(dateEl?.value || todayIsoDate());
    const methodId = String(methodEl?.value || shipmentsState.data?.selected_delivery_method_id || "").trim();
    const cid = Number(carriageId || shipmentsState.selectedCarriageId || 0);
    if (cid > 0 && cid !== Number(shipmentsState.selectedCarriageId || 0)) {
      shipmentsState.selectedCarriageId = cid;
      renderShipmentsView(shipmentsState.data);
    } else if (cid > 0) {
      shipmentsState.selectedCarriageId = cid;
    }
    const barcode = resolveShipmentsBarcode(shipmentsState.data, cid || shipmentsState.selectedCarriageId);
    const barcodeCarriageId = String(
      cid || (barcode && barcode.carriage_id) || shipmentsState.selectedCarriageId || ""
    ).trim();
    if (!barcodeCarriageId) {
      alert("Выберите сформированную отгрузку со штрихкодом");
      return;
    }
    const qs = new URLSearchParams({
      source_id: String(sourceId),
      departure_date: day,
      carriage_id: barcodeCarriageId,
    });
    if (methodId) qs.set("delivery_method_id", methodId);
    const url =
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/shipments/barcode-print?${qs.toString()}`;
    openPrintHtml(url, "Разрешите всплывающие окна для печати штрихкода")
      .catch((e) => alert(String(e.message || e)));
  }

  function shipmentsDownloadBarcode(carriageId) {
    const cid = Number(carriageId || shipmentsState.selectedCarriageId || 0);
    if (cid > 0 && cid !== Number(shipmentsState.selectedCarriageId || 0)) {
      shipmentsState.selectedCarriageId = cid;
      renderShipmentsView(shipmentsState.data);
    } else if (cid > 0) {
      shipmentsState.selectedCarriageId = cid;
    }
    const barcode = resolveShipmentsBarcode(shipmentsState.data, cid || shipmentsState.selectedCarriageId) || {};
    const labelB64 = String(barcode.barcode_label_base64 || "").trim();
    const b64 = String(barcode.barcode_image_base64 || "").trim();
    const text = String(barcode.barcode_text || "").trim();
    const suffix = text || (cid > 0 ? String(cid) : "label");
    const payload = labelB64 || b64;
    if (payload) {
      const a = document.createElement("a");
      a.href = `data:image/png;base64,${payload}`;
      a.download = `ozon-shipment-barcode-${suffix}.png`;
      a.click();
      return;
    }
    if (text) {
      const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ozon-shipment-barcode-${text}.txt`;
      a.click();
      URL.revokeObjectURL(url);
      return;
    }
    alert("Штрихкод для этой отгрузки ещё недоступен");
  }

  const ozonFbsKizState = {
    rows: [],
    errors: {},
    pendingPosting: null,
    saving: false,
    rowsReady: false,
    baselineByPosting: {},
    forceSaveByPosting: {},
    localAutosaveChain: Promise.resolve(),
    localAutosaveSeqByPosting: {},
    localAutosaveInflight: 0,
    /** @type {Set<string>} postings waiting for coalesced silent save */
    localAutosaveDirty: new Set(),
    localAutosaveClearByPosting: {},
    localAutosaveFlushQueued: false,
    /** @type {Map<string, object>} posting_number → row */
    rowsByPosting: new Map(),
    /** @type {Map<string, string>} normalized mark → posting_number */
    markIndex: new Map(),
    /** @type {Map<string, string[]>} sticker scan key → posting_number[] */
    stickerIndex: new Map(),
    statusRefreshing: false,
    statusRefreshGen: 0,
    /** Bumped to abort in-flight marking resolve when modal closes / reopens. */
    loadGen: 0,
    /** @type {Array<object>} conflicts from last import (sticker has other KIZ) */
    importConflicts: [],
    /** Rate-limit bucket for anomaly-only scan diagnostics (not on happy path). */
    diagWindowMs: 0,
    diagWindowCount: 0,
  };

  const ozonFbsPickState = {
    rows: [],
    errors: {},
    pendingPosting: null,
    saving: false,
    rowsReady: false,
    baselineByPosting: {},
    forceSaveByPosting: {},
    localAutosaveChain: Promise.resolve(),
    localAutosaveSeqByPosting: {},
    localAutosaveInflight: 0,
    statusRefreshing: false,
    statusRefreshGen: 0,
  };

  /**
   * Anomaly-only scan diagnostics → journal via tiny POST.
   * Never called on successful sticker/КИЗ scan. Rate-limited; fire-and-forget.
   */
  function _ozonFbsKizScanDiag(reason, detail) {
    const now = Date.now();
    if (!ozonFbsKizState.diagWindowMs || now - ozonFbsKizState.diagWindowMs > 60000) {
      ozonFbsKizState.diagWindowMs = now;
      ozonFbsKizState.diagWindowCount = 0;
    }
    if (ozonFbsKizState.diagWindowCount >= 12) return;
    ozonFbsKizState.diagWindowCount += 1;
    const reasonKey = String(reason || "unknown").slice(0, 64);
    const detailText = String(detail || "").slice(0, 360);
    try {
      console.warn("[ozon-fbs-scan]", reasonKey, detailText);
    } catch (_e) {
      /* ignore */
    }
    try {
      const body = JSON.stringify({
        area: "ozon_fbs_marking_scan",
        reason: reasonKey,
        detail: detailText,
        supply_id: String(supplyDetailState.supplyId || ""),
        source_id: Number(supplyDetailState.sourceId || state.sourceId || 0) || 0,
      });
      // keepalive + no await: must not slow or block the scan path.
      void fetch("/api/ozon-fbs/client-diag", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => {});
    } catch (_e) {
      /* ignore */
    }
  }
  window._ozonFbsKizScanDiag = _ozonFbsKizScanDiag;

  function _ozonFbsKizScanDiagSnapshot(input) {
    const ruOpen =
      typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen();
    const prompt = document.getElementById("ozonFbsKizScanPrompt");
    const promptOpen = !!(prompt && !prompt.classList.contains("hidden"));
    const activeId = document.activeElement?.id || "";
    return [
      `ru=${ruOpen ? 1 : 0}`,
      `ready=${ozonFbsKizState.rowsReady ? 1 : 0}`,
      `ro=${input?.readOnly ? 1 : 0}`,
      `dis=${input?.disabled ? 1 : 0}`,
      `prompt=${promptOpen ? 1 : 0}`,
      `pending=${String(ozonFbsKizState.pendingPosting || "")}`,
      `focus=${activeId}`,
      `valLen=${String(input?.value || "").length}`,
      `rows=${(ozonFbsKizState.rows || []).length}`,
    ].join(" ");
  }

  function _ozonFbsNormalizeScan(value) {
    if (typeof _wbFbsKizNormalizeScan === "function") {
      return _wbFbsKizNormalizeScan(value);
    }
    return String(value || "").replace(/\s+/g, "").trim();
  }

  function _ozonFbsStickerScanKey(value) {
    if (typeof _wbFbsKizScanKey === "function") {
      return _wbFbsKizScanKey(value);
    }
    return _ozonFbsNormalizeScan(value).toLocaleLowerCase("en-US");
  }

  function _ozonFbsStickerPartsFromPostingNumber(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return { part_a: "", part_b: "" };
    const idx = pn.indexOf("-");
    if (idx < 0) return { part_a: pn, part_b: "" };
    return {
      part_a: pn.slice(0, idx).trim(),
      part_b: pn.slice(idx + 1).trim(),
    };
  }

  function _ozonFbsStickerNumberFromRow(row) {
    const partA = _ozonFbsNormalizeScan(row?.sticker_part_a);
    const partB = _ozonFbsNormalizeScan(row?.sticker_part_b);
    if (partA && partB) return `${partA}${partB}`;
    if (partA || partB) return partA || partB;
    return _ozonFbsNormalizeScan(row?.posting_number);
  }

  function _ozonFbsResolvedStickerFields(row) {
    let upper = _ozonFbsNormalizeScan(row?.sticker_barcode);
    let lower = _ozonFbsNormalizeScan(row?.sticker_lower_barcode);
    let partA = _ozonFbsNormalizeScan(row?.sticker_part_a);
    let partB = _ozonFbsNormalizeScan(row?.sticker_part_b);
    const pn = String(row?.posting_number || "").trim();
    if ((!partA || !partB) && pn) {
      const parts = _ozonFbsStickerPartsFromPostingNumber(pn);
      if (!partA) partA = _ozonFbsNormalizeScan(parts.part_a);
      if (!partB) partB = _ozonFbsNormalizeScan(parts.part_b);
    }
    return { upper, lower, partA, partB, pn };
  }

  /**
   * Ozon FBS sticker match — parity with WB `_wbFbsKizFindBySticker` / backend lookup.
   * Ozon API ``FbsPostingBarcodes``: upper/lower штрихкоды этикетки + posting_number.
   */
  function _ozonFbsFindByStickerInRows(scan, rows, opts) {
    const raw = _ozonFbsNormalizeScan(scan);
    if (!raw) return { row: null, ambiguous: false };
    const rawKey = _ozonFbsStickerScanKey(raw);
    const rawLower = raw.toLowerCase();
    const includeCancelled = !!(opts && opts.includeCancelled);
    const list = includeCancelled
      ? (Array.isArray(rows) ? rows : [])
      : _ozonFbsActiveModalRows(Array.isArray(rows) ? rows : []);

    const byBarcode = [];
    for (const row of list) {
      const fields = _ozonFbsResolvedStickerFields(row);
      if (fields.upper && _ozonFbsStickerScanKey(fields.upper) === rawKey) byBarcode.push(row);
      else if (fields.lower && _ozonFbsStickerScanKey(fields.lower) === rawKey) byBarcode.push(row);
    }
    if (byBarcode.length === 1) return { row: byBarcode[0], ambiguous: false };
    if (byBarcode.length > 1) return { row: null, ambiguous: true, matches: byBarcode };

    const byPnExact = [];
    for (const row of list) {
      const pn = String(row?.posting_number || "").trim();
      if (pn && pn.toLowerCase() === rawLower) byPnExact.push(row);
    }
    if (byPnExact.length === 1) return { row: byPnExact[0], ambiguous: false };
    if (byPnExact.length > 1) return { row: null, ambiguous: true, matches: byPnExact };

    const digits = raw.replace(/\D+/g, "");
    const matches = [];
    for (const row of list) {
      const fields = _ozonFbsResolvedStickerFields(row);
      const pn = fields.pn;
      const pnLower = pn.toLowerCase();
      if (pnLower && (pnLower === rawLower || rawLower.includes(pnLower) || pnLower.includes(rawLower))) {
        matches.push(row);
        continue;
      }
      const full = fields.partA && fields.partB
        ? `${fields.partA}${fields.partB}`
        : (fields.partA || fields.partB || pn);
      if (
        (full && (_ozonFbsStickerScanKey(full) === rawKey || digits === full.replace(/\D+/g, ""))) ||
        (fields.partA && fields.partB && digits === `${fields.partA}${fields.partB}`.replace(/\D+/g, "")) ||
        (
          fields.partB
          && (_ozonFbsStickerScanKey(fields.partB) === rawKey || digits === fields.partB.replace(/\D+/g, ""))
        ) ||
        (pn && digits.length >= 4 && pn.replace(/\D+/g, "").endsWith(digits.slice(-4)))
      ) {
        matches.push(row);
      }
    }
    if (matches.length === 1) return { row: matches[0], ambiguous: false };
    if (matches.length > 1) {
      const exact = matches.find((r) => {
        const pn = String(r?.posting_number || "").trim().toLowerCase();
        return pn && (pn === rawLower || pn.includes(rawLower) || rawLower.includes(pn));
      });
      if (exact) return { row: exact, ambiguous: false };
      return { row: null, ambiguous: true, matches };
    }
    return { row: null, ambiguous: false };
  }

  function _ozonFbsApplyStickerScanToRow(row, scanRaw) {
    if (!row) return;
    const raw = _ozonFbsNormalizeScan(scanRaw);
    if (!raw) return;
    const pn = String(row.posting_number || "").trim();
    const rawKey = _ozonFbsStickerScanKey(raw);
    const rawLower = raw.toLowerCase();
    const pnLower = pn.toLowerCase();
    let partA = String(row.sticker_part_a || "").trim();
    let partB = String(row.sticker_part_b || "").trim();
    if (!partA && !partB && pn) {
      const parts = _ozonFbsStickerPartsFromPostingNumber(pn);
      partA = parts.part_a;
      partB = parts.part_b;
    }
    const knownUpper = _ozonFbsNormalizeScan(row.sticker_barcode);
    const knownLower = _ozonFbsNormalizeScan(row.sticker_lower_barcode);
    if (knownLower && _ozonFbsStickerScanKey(knownLower) === rawKey) {
      row.sticker_lower_barcode = raw;
    } else if (knownUpper && _ozonFbsStickerScanKey(knownUpper) === rawKey) {
      row.sticker_barcode = raw;
    } else if (rawLower === pnLower || (pnLower && rawLower.includes(pnLower))) {
      if (!row.sticker_barcode) row.sticker_barcode = raw;
    } else {
      // Новый скан с этикетки — по умолчанию upper; Ozon API разделяет upper/lower.
      row.sticker_barcode = raw;
    }
    if (partA) row.sticker_part_a = partA;
    if (partB) row.sticker_part_b = partB;
  }

  async function _ozonFbsPersistStickerForRow(row, scanRaw) {
    const pn = String(row?.posting_number || "").trim();
    const raw = _ozonFbsNormalizeScan(scanRaw);
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!pn || !raw || !sourceId) return;
    _ozonFbsApplyStickerScanToRow(row, raw);
    if (ozonFbsKizState.rowsByPosting?.has(pn)) {
      _ozonFbsKizRebuildIndexes();
    }
    try {
      await fetch("/api/ozon-fbs/postings/persist-sticker", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...jsonHeaders() },
        body: JSON.stringify({
          source_id: sourceId,
          posting_number: pn,
          sticker_barcode: String(row.sticker_barcode || "").trim(),
          sticker_lower_barcode: String(row.sticker_lower_barcode || "").trim(),
          sticker_part_a: String(row.sticker_part_a || "").trim(),
          sticker_part_b: String(row.sticker_part_b || "").trim(),
          supply_id: String(supplyDetailState.supplyId || "").trim() || undefined,
        }),
      });
    } catch (_) {
      /* local bind is best-effort */
    }
  }

  async function _ozonFbsPersistStickerScan(postingNumber, scanRaw) {
    const pn = String(postingNumber || "").trim();
    const row =
      ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn)
      || ozonFbsPickState.rows.find((r) => String(r.posting_number) === pn)
      || { posting_number: pn };
    await _ozonFbsPersistStickerForRow(row, scanRaw);
  }

  function _ozonFbsNormalizeMark(value) {
    let text;
    if (typeof _wbFbsKizNormalizeMark === "function") {
      text = _wbFbsKizNormalizeMark(value);
    } else {
      text = String(value || "")
        .replace(/\u2194/g, "\u001D")
        .replace(/\r?\n/g, "")
        .replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
    }
    // Ozon-only: scanners/pastes sometimes use ☻/☺ instead of GS; also
    // accept visible "<GS>" / "\\u001D" from normalized copy-paste lists.
    text = String(text || "")
      .replace(/\u263b/g, "\u001D") // ☻
      .replace(/\u263a/g, "\u001D") // ☺
      .replace(/\\u001[dD]/g, "\u001D")
      .replace(/<GS>/gi, "\u001D")
      .replace(/\r?\n/g, "");
    // ЧЗ: GS before AI 91 (4-char key) and before AI 92 crypto.
    text = text.replace(/(91[0-9A-Za-z+/]{4})(?!\u001D)(92)/, "$1\u001D$2");
    text = text.replace(/(?<!\u001D)(91[0-9A-Za-z+/]{4}\u001D92)/, "\u001D$1");
    return text;
  }

  function _ozonFbsKizMarkLooksComplete(mark) {
    const raw = _ozonFbsNormalizeMark(mark);
    if (!raw || !/^01\d{14}21/.test(raw)) return false;
    return /\u001D91.{4}\u001D92.{20,}/.test(raw) || /91.{4}\u001D92.{20,}/.test(raw);
  }

  function _ozonFbsKizCanImport() {
    // Available to all roles while Marking modal is open and rows are loaded.
    return _ozonFbsKizModalIsOpen() && !!ozonFbsKizState.rowsReady;
  }

  function _ozonFbsKizSyncImportBtn() {
    const btn = document.getElementById("ozonFbsKizImportBtn");
    if (!btn) return;
    const can = !!ozonFbsKizState.rowsReady && _ozonFbsKizModalIsOpen();
    btn.hidden = !can;
    btn.style.display = can ? "" : "none";
    if (!can) closeOzonFbsKizImportModal();
  }

  function _ozonFbsKizImportModalIsOpen() {
    const modal = document.getElementById("ozonFbsKizImportModal");
    return !!(modal && !modal.classList.contains("hidden"));
  }

  function openOzonFbsKizImportModal() {
    if (!_ozonFbsKizModalIsOpen() || !ozonFbsKizState.rowsReady) {
      alert("Сначала откройте модалку «Маркировка» и дождитесь загрузки");
      return;
    }
    _ozonFbsKizSyncImportBtn();
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsKizImportModal", true);
    else document.getElementById("ozonFbsKizImportModal")?.classList.remove("hidden");
    const ta = document.getElementById("ozonFbsKizImportText");
    if (ta) {
      // Scanner-first: keep focus in the paste/scan field; wedge ends with Enter → newline.
      setTimeout(() => {
        ta.focus();
        try {
          const len = String(ta.value || "").length;
          ta.setSelectionRange(len, len);
        } catch (_e) {
          /* ignore */
        }
      }, 40);
    }
  }

  function closeOzonFbsKizImportModal() {
    // Unlock keyboard if RU warning was open for this textarea (do not wipe text).
    try {
      if (
        typeof _wbFbsKizRuLayoutModalOpen === "function"
        && _wbFbsKizRuLayoutModalOpen()
        && typeof wbFbsKizState !== "undefined"
        && wbFbsKizState.ruLayoutFocusId === "ozonFbsKizImportText"
      ) {
        document.removeEventListener("keydown", _wbFbsKizRuLayoutSwallowKeys, true);
        if (typeof setModalVisibility === "function") {
          setModalVisibility("wbFbsKizRuLayoutModal", false);
        }
        wbFbsKizState.ruLayoutFocusId = null;
        wbFbsKizState.ruLayoutPreserveValue = false;
        wbFbsKizState.ruLayoutOpenedAt = 0;
      }
    } catch (_e) {
      /* ignore */
    }
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsKizImportModal", false);
    else document.getElementById("ozonFbsKizImportModal")?.classList.add("hidden");
  }

  /** Open the shared «Русская раскладка» modal; never wipe the import textarea. */
  function _ozonFbsKizImportWarnRuLayout(inputEl) {
    if (typeof _wbFbsKizBlockRuLayout !== "function") return;
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
      return;
    }
    _wbFbsKizBlockRuLayout(inputEl, { preserveValue: true });
  }

  /**
   * Pre-input RU check (beforeinput): block Cyrillic before it lands in the field,
   * show the same modal as Marking, keep existing text intact.
   */
  function onOzonFbsKizImportTextBeforeInput(event) {
    if (!event) return;
    const input = event.target;
    if (!input) return;
    const inputType = String(event.inputType || "");
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
      // While warning is open: block new inserts, allow Backspace/Delete to fix leftovers.
      if (inputType.startsWith("insert")) {
        event.preventDefault();
      }
      return;
    }
    // Paste is handled in onpaste (clipboardData is reliable there).
    if (inputType === "insertFromPaste" || inputType === "insertFromDrop") return;
    const data = String(event.data || "");
    if (!data) return;
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(data)) {
      event.preventDefault();
      _ozonFbsKizImportWarnRuLayout(input);
    }
  }

  /** Paste path: reject clipboard with Cyrillic before it enters the textarea. */
  function onOzonFbsKizImportTextPaste(event) {
    if (!event) return;
    const input = event.target;
    if (!input) return;
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
      event.preventDefault();
      return;
    }
    const text = String(event.clipboardData?.getData("text") || "");
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(text)) {
      event.preventDefault();
      _ozonFbsKizImportWarnRuLayout(input);
    }
  }

  /**
   * Safety net if Cyrillic somehow got into the field (e.g. old buffer).
   * Same modal as Marking; never wipe the textarea; no sticky bottom error.
   */
  function onOzonFbsKizImportTextInput(event) {
    const input = event?.target;
    if (!input) return;
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
      return;
    }
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(input.value)) {
      _ozonFbsKizImportWarnRuLayout(input);
    }
  }

  /**
   * Scanner-friendly Enter: after sticker+КИЗ pair lands (wedge sends Enter),
   * apply the latest complete pair immediately. Ctrl/Cmd+Enter runs full import.
   */
  function onOzonFbsKizImportTextKey(event) {
    if (!event) return;
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
      // Swallow scanner tail while warning is open; do not wipe the field.
      // Allow Backspace/Delete so leftover Cyrillic can be removed.
      const key = String(event.key || "");
      if (key === "Enter" || key === "Tab" || key.length === 1) {
        event.preventDefault();
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      void runOzonFbsKizImport();
      return;
    }
    if (event.key !== "Enter" || event.ctrlKey || event.metaKey || event.altKey) return;
    // Allow newline for sticker / KIZ separation, then try live apply.
    window.setTimeout(() => {
      void _ozonFbsKizImportApplyLatestScanPair();
    }, 0);
  }

  async function _ozonFbsKizImportApplyLatestScanPair() {
    if (!_ozonFbsKizImportModalIsOpen() || !_ozonFbsKizCanImport()) return;
    const ta = document.getElementById("ozonFbsKizImportText");
    if (!ta) return;
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(ta.value)) {
      return;
    }
    const snapshot = String(ta.value || "");
    const pairs = _ozonFbsKizParseImportText(snapshot);
    if (!pairs.length) return;
    // Batch paste: operator uses «Импортировать». Live wedge usually has 1 pair in flight.
    if (pairs.length > 2) return;
    const last = pairs[pairs.length - 1];
    const mark = _ozonFbsNormalizeMark(last.kiz);
    // Wait until the wedge finished a Data Matrix (not only the sticker line).
    if (!/^01\d{14}21/.test(mark)) return;
    // Do not accept truncated scans (typical cut right at GS before AI 91, ~31 chars).
    if (!_ozonFbsKizMarkLooksComplete(mark)) {
      _ozonFbsKizImportSetInfo(
        `КИЗ обрезан / неполный (${mark.length} симв.) — пересканируйте маркировку целиком`
      );
      const info = document.getElementById("ozonFbsKizImportInfo");
      if (info) {
        info.classList.remove("is-ok");
        info.classList.add("is-warn");
      }
      return;
    }
    const remaining = pairs.slice(0, -1);
    ta.value = `${last.sticker}\t${last.kiz}`;
    let result = null;
    try {
      result = await runOzonFbsKizImport({ liveScan: true });
    } finally {
      // Only drop the applied pair on success; keep buffer on skip/error for rescan.
      if (result && Number(result.okN || 0) > 0) {
        ta.value = remaining.map((p) => `${p.sticker}\t${p.kiz}`).join("\n");
      } else {
        ta.value = snapshot;
      }
      ta.focus();
      try {
        const len = String(ta.value || "").length;
        ta.setSelectionRange(len, len);
      } catch (_e) {
        /* ignore */
      }
    }
  }

  /** @deprecated use openOzonFbsKizImportModal / closeOzonFbsKizImportModal */
  function toggleOzonFbsKizImportPanel(forceOpen) {
    if (forceOpen === false) {
      closeOzonFbsKizImportModal();
      return;
    }
    if (forceOpen === true || !_ozonFbsKizImportModalIsOpen()) openOzonFbsKizImportModal();
    else closeOzonFbsKizImportModal();
  }

  function _ozonFbsKizImportSetInfo(text, ok) {
    const el = document.getElementById("ozonFbsKizImportInfo");
    if (!el) {
      _ozonFbsKizSetInfo(text, ok);
      return;
    }
    const msg = String(text || "").trim();
    el.hidden = !msg;
    el.textContent = msg;
    el.classList.remove("is-warn");
    el.classList.toggle("is-ok", !!msg && !!ok);
  }

  function _ozonFbsKizParseImportText(text) {
    // Notepad-like: blank lines between pairs are fine; same-line "sticker KIZ" too.
    const rawLines = String(text || "")
      .replace(/\u00a0/g, " ")
      .split(/\r?\n/);
    const lines = [];
    for (const line of rawLines) {
      const trimmed = line.trim();
      if (!trimmed) continue; // 1–N empty lines between pairs
      if (/^стикер\b/i.test(trimmed) && /\bкиз\b/i.test(trimmed)) continue;
      lines.push(trimmed);
    }

    const pairs = [];
    let pendingSticker = "";

    const pushPair = (sticker, kiz) => {
      const s = String(sticker || "").trim();
      const k = String(kiz || "").trim();
      if (s && k) pairs.push({ sticker: s, kiz: k });
    };

    const isStickerToken = (s) => /^\d{10,20}$/.test(String(s || "").trim());
    const isKizStart = (s) => /^01\d{14}21/.test(String(s || "").trim());

    for (let i = 0; i < lines.length; i += 1) {
      const trimmed = lines[i];

      // Same-line: sticker \t KIZ
      if (trimmed.includes("\t")) {
        pendingSticker = "";
        const parts = trimmed.split("\t");
        pushPair(parts[0], parts.slice(1).join("\t"));
        continue;
      }
      // Same-line: sticker | KIZ
      if (trimmed.includes("|") && /^\d{10,20}\s*\|/.test(trimmed)) {
        pendingSticker = "";
        const idx = trimmed.indexOf("|");
        pushPair(trimmed.slice(0, idx), trimmed.slice(idx + 1));
        continue;
      }
      // Same-line: sticker + spaces + 01…KIZ (Notepad / paste from Excel)
      const inline = trimmed.match(/^(\d{10,20})[ \t]+(01\d{14}21[\s\S]+)$/);
      if (inline) {
        pendingSticker = "";
        pushPair(inline[1], inline[2]);
        continue;
      }

      // Alternating lines: sticker, then KIZ (optionally wrapped after GS → newline).
      if (isStickerToken(trimmed)) {
        pendingSticker = trimmed;
        continue;
      }
      if (pendingSticker && isKizStart(trimmed)) {
        let kiz = trimmed;
        while (i + 1 < lines.length) {
          const nxt = lines[i + 1];
          if (isStickerToken(nxt)) break;
          if (isKizStart(nxt)) break;
          if (nxt.includes("\t") || /^\d{10,20}\s*\|/.test(nxt)) break;
          if (/^\d{10,20}[ \t]+01\d{14}21/.test(nxt)) break;
          // Continuation of crypto / AI91 after GS was turned into a line break.
          kiz += nxt;
          i += 1;
        }
        pushPair(pendingSticker, kiz);
        pendingSticker = "";
        continue;
      }
      // Lone KIZ / junk without sticker — ignore, reset pending.
      pendingSticker = "";
    }
    return pairs;
  }

  function _ozonFbsKizImportSetLog(lines) {
    const el = document.getElementById("ozonFbsKizImportLog");
    if (!el) return;
    const text = (Array.isArray(lines) ? lines : []).join("\n");
    el.hidden = !text;
    el.textContent = text;
  }

  function _ozonFbsKizMarkPreview(mark) {
    const raw = _ozonFbsNormalizeMark(mark);
    if (!raw) return "—";
    if (raw.length <= 28) return raw;
    return `${raw.slice(0, 14)}…${raw.slice(-10)}`;
  }

  function _ozonFbsKizRowExistingCodes(row) {
    return _ozonFbsKizNormalizeCodesList(row?.kiz_codes);
  }

  function _ozonFbsKizClearImportConflicts() {
    ozonFbsKizState.importConflicts = [];
    const wrap = document.getElementById("ozonFbsKizImportConflicts");
    const list = document.getElementById("ozonFbsKizImportConflictsList");
    if (wrap) wrap.hidden = true;
    if (list) list.innerHTML = "";
  }

  function _ozonFbsKizRenderImportConflicts() {
    const wrap = document.getElementById("ozonFbsKizImportConflicts");
    const list = document.getElementById("ozonFbsKizImportConflictsList");
    if (!wrap || !list) return;
    const items = Array.isArray(ozonFbsKizState.importConflicts)
      ? ozonFbsKizState.importConflicts
      : [];
    if (!items.length) {
      wrap.hidden = true;
      list.innerHTML = "";
      return;
    }
    wrap.hidden = false;
    list.innerHTML = items.map((c, idx) => {
      const id = `ozonFbsKizImportConflict_${idx}`;
      const had = (c.existing || []).map(_ozonFbsKizMarkPreview).join("; ");
      const incoming = _ozonFbsKizMarkPreview(c.mark);
      const incompleteNote = c.incomplete ? " · неполный КИЗ" : "";
      return (
        `<label class="ozon-fbs-kiz-import-conflict" for="${id}">` +
          `<input type="checkbox" id="${id}" data-conflict-idx="${idx}" checked />` +
          `<span class="ozon-fbs-kiz-import-conflict-meta">` +
            `<strong>${esc(c.sticker)} → ${esc(c.posting_number)}</strong>` +
            `<span class="ozon-fbs-kiz-import-conflict-codes">сейчас: ${esc(had)}</span>` +
            `<span class="ozon-fbs-kiz-import-conflict-codes">импорт: ${esc(incoming)}${esc(incompleteNote)}</span>` +
          `</span>` +
        `</label>`
      );
    }).join("");
  }

  function selectAllOzonFbsKizImportConflicts(selected) {
    const list = document.getElementById("ozonFbsKizImportConflictsList");
    if (!list) return;
    list.querySelectorAll('input[type="checkbox"][data-conflict-idx]').forEach((el) => {
      el.checked = !!selected;
    });
  }

  function dismissOzonFbsKizImportConflicts() {
    _ozonFbsKizClearImportConflicts();
    _ozonFbsKizImportSetInfo("Конфликты оставлены без замены", true);
  }

  async function applyOzonFbsKizImportConflicts() {
    if (!_ozonFbsKizCanImport()) return;
    if (!ozonFbsKizState.rowsReady || !_ozonFbsKizModalIsOpen()) return;
    const items = Array.isArray(ozonFbsKizState.importConflicts)
      ? ozonFbsKizState.importConflicts
      : [];
    if (!items.length) return;

    const list = document.getElementById("ozonFbsKizImportConflictsList");
    const replaceBtn = document.getElementById("ozonFbsKizImportReplaceBtn");
    const selectedIdx = new Set();
    list?.querySelectorAll('input[type="checkbox"][data-conflict-idx]:checked').forEach((el) => {
      const idx = Number(el.getAttribute("data-conflict-idx"));
      if (Number.isFinite(idx)) selectedIdx.add(idx);
    });
    if (!selectedIdx.size) {
      _ozonFbsKizImportSetInfo("Не выбрано ни одной строки для замены");
      return;
    }

    if (replaceBtn) replaceBtn.disabled = true;
    const log = [];
    let okN = 0;
    let skipN = 0;
    const touched = new Set();
    const remaining = [];

    try {
      for (let idx = 0; idx < items.length; idx += 1) {
        const c = items[idx];
        if (!selectedIdx.has(idx)) {
          remaining.push(c);
          continue;
        }
        const pn = String(c.posting_number || "").trim();
        const mark = _ozonFbsNormalizeMark(c.mark);
        const stickerKey = _ozonFbsNormalizeScan(c.sticker);
        const row = _ozonFbsKizRowByPosting(pn);
        if (!row || !mark || !pn) {
          skipN += 1;
          log.push(`${stickerKey || "—"} → ${pn || "—"} — не удалось заменить`);
          remaining.push(c);
          continue;
        }
        if (_ozonFbsRowIsCancelled(row)) {
          skipN += 1;
          log.push(`${stickerKey} → ${pn} — отправление отменено`);
          remaining.push(c);
          continue;
        }
        const check = _ozonFbsKizValidateMarkForOrder(mark, row);
        if (!check.ok) {
          skipN += 1;
          log.push(`${stickerKey} → ${pn} — ${check.error || "КИЗ не совпадает с ШК"}`);
          remaining.push(c);
          continue;
        }
        const dup = _ozonFbsKizFindExistingMark(mark);
        if (dup && String(dup.posting_number || "").trim() !== pn) {
          skipN += 1;
          log.push(
            `${stickerKey} → ${pn} — КИЗ уже в отправлении ${dup.posting_number}`
          );
          remaining.push(c);
          continue;
        }

        for (const old of _ozonFbsKizRowExistingCodes(row)) {
          if (old && old !== mark) _ozonFbsKizIndexClearMark(old);
        }
        row.kiz_codes = [mark];
        row.kiz_status = "pending";
        delete ozonFbsKizState.errors[pn];
        _ozonFbsKizIndexSetMark(mark, pn);
        touched.add(pn);
        void _ozonFbsPersistStickerForRow(row, stickerKey);
        _ozonFbsKizScheduleLocalAutosave(pn, false);
        okN += 1;
        log.push(`${stickerKey} → ${pn} — заменён на ${_ozonFbsKizMarkPreview(mark)}`);
      }

      if (touched.size) {
        renderOzonFbsKizTable({ skipCollect: true });
        await _ozonFbsKizAwaitLocalAutosaves();
      }

      ozonFbsKizState.importConflicts = remaining;
      _ozonFbsKizRenderImportConflicts();

      const prevLog = document.getElementById("ozonFbsKizImportLog");
      const prevText = prevLog && !prevLog.hidden ? String(prevLog.textContent || "") : "";
      const extra = ["", "— Замена конфликтов —", ...log, "", `Заменено ${okN}, пропущено ${skipN}`];
      _ozonFbsKizImportSetLog(
        prevText ? prevText.split("\n").concat(extra) : extra
      );
      _ozonFbsKizImportSetInfo(`Замена: ${okN} ок, ${skipN} пропущено`, okN > 0 && skipN === 0);
      if (okN > 0 && skipN > 0) {
        const info = document.getElementById("ozonFbsKizImportInfo");
        if (info) {
          info.classList.remove("is-ok");
          info.classList.add("is-warn");
        }
      }
    } finally {
      if (replaceBtn) replaceBtn.disabled = false;
    }
  }

  async function runOzonFbsKizImport(opts) {
    const liveScan = !!(opts && opts.liveScan);
    const emptyResult = { okN: 0, skipN: 0, conflicts: 0 };
    if (!_ozonFbsKizCanImport()) {
      if (!liveScan) {
        _ozonFbsKizImportSetInfo("Сначала откройте модалку маркировки и дождитесь загрузки");
      }
      return emptyResult;
    }
    if (!ozonFbsKizState.rowsReady || !_ozonFbsKizModalIsOpen()) {
      _ozonFbsKizImportSetInfo("Сначала откройте модалку маркировки и дождитесь загрузки");
      return emptyResult;
    }
    const ta = document.getElementById("ozonFbsKizImportText");
    const runBtn = document.getElementById("ozonFbsKizImportRunBtn");
    const rawText = String(ta?.value || "");
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(rawText)) {
      if (!liveScan && ta) {
        _ozonFbsKizImportWarnRuLayout(ta);
      }
      return emptyResult;
    }
    const pairs = _ozonFbsKizParseImportText(rawText);
    if (!pairs.length) {
      if (!liveScan) {
        _ozonFbsKizImportSetLog([
          "Нет пар стикер+КИЗ. Допустимо:",
          "• стикер и КИЗ в одной строке через пробел или таб",
          "• стикер, затем КИЗ на следующей строке (пустые строки между ними ок)",
        ]);
        _ozonFbsKizImportSetInfo("Импорт: пустой список");
        _ozonFbsKizClearImportConflicts();
      }
      return emptyResult;
    }

    if (runBtn) runBtn.disabled = true;
    _ozonFbsKizSyncActiveCodeInput();
    _ozonFbsKizClearImportConflicts();
    const log = [];
    let okN = 0;
    let skipN = 0;
    const touched = new Set();
    /** Marks accepted earlier in this same paste — avoid double-add in one run. */
    const importedMarks = new Set();
    /** @type {Map<string, object>} posting_number → conflict (last wins) */
    const conflictsByPn = new Map();

    try {
      for (let i = 0; i < pairs.length; i += 1) {
        const { sticker, kiz } = pairs[i];
        const n = i + 1;
        const stickerKey = _ozonFbsNormalizeScan(sticker);
        const mark = _ozonFbsNormalizeMark(kiz);
        if (!stickerKey || !mark) {
          skipN += 1;
          log.push(`${n}. пропуск — пустой стикер или КИЗ`);
          continue;
        }
        const incomplete = !_ozonFbsKizMarkLooksComplete(mark);

        const found = _ozonFbsKizFindBySticker(stickerKey);
        if (found.ambiguous) {
          skipN += 1;
          const ids = (found.matches || []).map((r) => r.posting_number).slice(0, 4).join(", ");
          log.push(`${n}. ${stickerKey} — стикер неоднозначен (${ids || "несколько отправлений"})`);
          continue;
        }
        if (!found.row) {
          skipN += 1;
          log.push(`${n}. ${stickerKey} — стикер не найден в этой поставке`);
          continue;
        }
        const row = found.row;
        const pn = String(row.posting_number || "").trim();
        if (!pn) {
          skipN += 1;
          log.push(`${n}. ${stickerKey} — нет номера отправления`);
          continue;
        }
        if (_ozonFbsRowIsCancelled(row)) {
          skipN += 1;
          log.push(`${n}. ${stickerKey} → ${pn} — отправление отменено`);
          continue;
        }

        const check = _ozonFbsKizValidateMarkForOrder(mark, row);
        if (!check.ok) {
          skipN += 1;
          log.push(`${n}. ${stickerKey} → ${pn} — ${check.error || "КИЗ не совпадает с ШК"}`);
          ozonFbsKizState.errors[pn] = check.error || "КИЗ не совпадает с ШК";
          continue;
        }

        const existing = _ozonFbsKizRowExistingCodes(row);
        // Same sticker + same KIZ already scanned (or already in this paste).
        if (existing.includes(mark) || importedMarks.has(mark)) {
          skipN += 1;
          log.push(
            `${n}. ${stickerKey} → ${pn} — дубль: стикер и КИЗ уже просканированы ` +
              `(${_ozonFbsKizMarkPreview(mark)})`
          );
          continue;
        }

        const dup = _ozonFbsKizFindExistingMark(mark);
        if (dup) {
          const dupPn = String(dup.posting_number || "").trim();
          skipN += 1;
          log.push(
            dupPn === pn
              ? `${n}. ${stickerKey} → ${pn} — дубль: этот КИЗ уже есть в отправлении (${_ozonFbsKizMarkPreview(mark)})`
              : `${n}. ${stickerKey} → ${pn} — дубль: КИЗ уже в отправлении ${dupPn} (${_ozonFbsKizMarkPreview(mark)})`
          );
          continue;
        }

        if (!Array.isArray(row.kiz_codes) || !row.kiz_codes.length) row.kiz_codes = [""];
        const qty = Math.max(1, Number(row.quantity) || 1);
        const filledN = existing.length;
        if (filledN >= qty) {
          skipN += 1;
          const had = existing.map(_ozonFbsKizMarkPreview).join("; ");
          log.push(
            `${n}. ${stickerKey} → ${pn} — конфликт: у стикера уже другой КИЗ ` +
              `[${had}], импорт [${_ozonFbsKizMarkPreview(mark)}] — см. список ниже`
          );
          conflictsByPn.set(pn, {
            sticker: stickerKey,
            posting_number: pn,
            mark,
            existing: existing.slice(),
            incomplete: !!incomplete,
            line: n,
          });
          continue;
        }

        let placedIdx = -1;
        for (let j = 0; j < row.kiz_codes.length; j += 1) {
          if (!String(row.kiz_codes[j] || "").trim()) {
            row.kiz_codes[j] = mark;
            placedIdx = j;
            break;
          }
        }
        if (placedIdx < 0) {
          row.kiz_codes.push(mark);
          placedIdx = row.kiz_codes.length - 1;
        }
        row.kiz_status = "pending";
        delete ozonFbsKizState.errors[pn];
        _ozonFbsKizIndexSetMark(mark, pn);
        importedMarks.add(mark);
        touched.add(pn);
        void _ozonFbsPersistStickerForRow(row, stickerKey);
        _ozonFbsKizScheduleLocalAutosave(pn, false);
        okN += 1;
        log.push(
          incomplete
            ? `${n}. ${stickerKey} → ${pn} — добавлен (неполный КИЗ, без 91/92 — можно восстановить позже)`
            : `${n}. ${stickerKey} → ${pn} — добавлен`
        );
      }

      if (touched.size) {
        const emptyFilter = document.getElementById("ozonFbsKizFilterEmpty");
        if (emptyFilter) emptyFilter.checked = false;
        renderOzonFbsKizTable({ skipCollect: true });
        await _ozonFbsKizAwaitLocalAutosaves();
      }

      const conflicts = Array.from(conflictsByPn.values());
      ozonFbsKizState.importConflicts = conflicts;
      _ozonFbsKizRenderImportConflicts();

      log.push("");
      log.push(`Итого: добавлено ${okN}, пропущено ${skipN}, строк ${pairs.length}`);
      if (conflicts.length) {
        log.push(`Конфликтов (другой КИЗ на стикере): ${conflicts.length} — отметьте и замените ниже, если нужно`);
      }
      _ozonFbsKizImportSetLog(log);
      const summary = conflicts.length
        ? `Импорт: добавлено ${okN}, пропущено ${skipN}, конфликтов ${conflicts.length}`
        : `Импорт: добавлено ${okN}, пропущено ${skipN}`;
      _ozonFbsKizImportSetInfo(summary, okN > 0 && skipN === 0 && !conflicts.length);
      if ((okN > 0 && skipN > 0) || conflicts.length) {
        const info = document.getElementById("ozonFbsKizImportInfo");
        if (info) {
          info.classList.remove("is-ok");
          info.classList.add("is-warn");
        }
      }
      // Mirror short status into Marking modal too.
      _ozonFbsKizSetInfo(summary, okN > 0 && skipN === 0 && !conflicts.length);
      if ((okN > 0 && skipN > 0) || conflicts.length) {
        const info = document.getElementById("ozonFbsKizInfo");
        if (info) {
          info.classList.remove("is-ok");
          info.classList.add("is-warn");
        }
      }
      return { okN, skipN, conflicts: conflicts.length };
    } finally {
      if (runBtn) runBtn.disabled = false;
    }
  }

  function _ozonFbsKizNormalizeCodesList(codes) {
    const seen = new Set();
    const out = [];
    for (const c of Array.isArray(codes) ? codes : []) {
      const n = _ozonFbsNormalizeMark(c);
      if (!n || seen.has(n)) continue;
      seen.add(n);
      out.push(n);
    }
    return out;
  }

  function _ozonFbsKizModalIsOpen() {
    const modal = document.getElementById("ozonFbsKizModal");
    return !!(modal && !modal.classList.contains("hidden"));
  }

  function _ozonFbsKizStickerHtml(row) {
    const partA = String(row?.sticker_part_a || "").trim();
    const partB = String(row?.sticker_part_b || "").trim();
    const bc = String(row?.sticker_barcode || "").trim();
    let head = partA;
    let tail = partB;
    if ((!head || !tail) && bc) {
      if (bc.length > 4) {
        head = bc.slice(0, -4);
        tail = bc.slice(-4);
      } else {
        head = "";
        tail = bc;
      }
    }
    if (!head && !tail) {
      return `<div class="wb-fbs-kiz-sticker">—</div>`;
    }
    if (!tail) {
      return `<div class="wb-fbs-kiz-sticker">${esc(head)}</div>`;
    }
    return `<div class="wb-fbs-kiz-sticker">` +
      (head ? `<span class="wb-fbs-kiz-sticker-head">${esc(head)}</span>` : "") +
      `<span class="wb-fbs-kiz-sticker-tail">${esc(tail)}</span>` +
      `</div>`;
  }

  /** First column like supply detail: posting number + date (no duplicate sticker line). */
  function _ozonFbsModalPostingColHtml(row, { quantity } = {}) {
    const pn = String(row?.posting_number || "").trim();
    const created = row?.created_at_ozon || row?.in_process_at || row?.created_date || "";
    const ago = agoLabel(created);
    const badges = [];
    if (ago) badges.push(`<span class="wb-fbs-badge time">${esc(ago)}</span>`);
    const qty = Number(quantity != null ? quantity : row?.quantity || 0);
    const qtyHtml =
      qty > 1 ? `<div class="wb-fbs-order-meta">${esc(qty)} шт.</div>` : "";
    return (
      `<div class="wb-fbs-sd-order-id">${formatOzonPostingNumberHtml(pn)}</div>` +
      `<div class="wb-fbs-order-meta">от ${esc(fmtDate(created))}</div>` +
      (badges.length ? `<div class="wb-fbs-badges">${badges.join("")}</div>` : "") +
      qtyHtml
    );
  }

  function _ozonFbsKizRowIsEmpty(row) {
    const codes = Array.isArray(row?.kiz_codes) ? row.kiz_codes : [];
    return !codes.some((c) => String(c || "").trim());
  }

  function _ozonFbsKizValidateMarkForOrder(mark, row) {
    if (typeof _wbFbsKizValidateMarkForOrder === "function") {
      return _wbFbsKizValidateMarkForOrder(mark, row);
    }
    const raw = _ozonFbsNormalizeMark(mark);
    if (!raw) return { ok: false, error: "Пустой код маркировки" };
    return { ok: true };
  }

  function _ozonFbsKizMergeOrderFlagsIntoDetail(flags) {
    const supply = supplyDetailState.supply;
    if (!supply || !Array.isArray(supply.orders) || !Array.isArray(flags)) return;
    const byPn = new Map();
    flags.forEach((row) => {
      const pn = String(row?.posting_number || "").trim();
      if (pn) byPn.set(pn, row);
    });
    supply.orders.forEach((o) => {
      const pn = String(o?.posting_number || "").trim();
      const upd = byPn.get(pn);
      if (!upd) return;
      o.kiz_required = !!upd.kiz_required;
      if (upd.kiz_status) o.kiz_status = String(upd.kiz_status);
      if (upd.cancel_reason_label) {
        o.cancel_reason_label = String(upd.cancel_reason_label || "").trim();
      }
      if (upd.cancelled) o.cancelled = true;
    });
  }

  function _ozonFbsKizMergeStatusIntoDetail(orders) {
    const supply = supplyDetailState.supply;
    if (!supply || !Array.isArray(supply.orders) || !Array.isArray(orders)) return;
    const byPn = new Map();
    orders.forEach((row) => {
      const pn = String(row?.posting_number || "").trim();
      if (pn) byPn.set(pn, row);
    });
    supply.orders.forEach((o) => {
      const pn = String(o?.posting_number || "").trim();
      const upd = byPn.get(pn);
      if (!upd) return;
      o.kiz_required = !!upd.kiz_required;
      if (Array.isArray(upd.kiz_codes)) o.kiz_codes = upd.kiz_codes.slice();
      o.kiz_status = String(upd.kiz_status || o.kiz_status || "empty");
      if (upd.cancel_reason_label) {
        o.cancel_reason_label = String(upd.cancel_reason_label || "").trim();
      }
      if (upd.cancelled) o.cancelled = true;
    });
  }

  function _ozonFbsSupplyActionsReady() {
    return !!supplyDetailState.ordersReady;
  }

  function _ozonFbsSyncPickVerifyBtn(orders) {
    const btn = document.getElementById("ozonFbsSupplyDetailPickVerifyBtn");
    const split = document.getElementById("ozonFbsPickSplit");
    if (!btn && !split) return;
    const list = Array.isArray(orders) ? orders : [];
    const hasPlain = list.some((o) => o && !o.kiz_required && !_ozonFbsRowIsCancelled(o));
    const can = typeof isTenantOwner === "function" && isTenantOwner()
      && _ozonFbsSupplyActionsReady() && hasPlain;
    if (split) {
      split.hidden = !can;
      split.style.display = can ? "" : "none";
    }
    if (btn) {
      btn.hidden = !can;
      btn.style.display = can ? "" : "none";
    }
  }

  function _ozonFbsPickSplitSetTone(tone) {
    const split = document.getElementById("ozonFbsPickSplit");
    if (!split) return;
    split.classList.remove("is-ok", "is-error");
    const t = String(tone || "").trim().toLowerCase();
    if (t === "ok") split.classList.add("is-ok");
    else if (t === "error") split.classList.add("is-error");
    const refreshBtn = document.getElementById("ozonFbsSupplyDetailPickRefreshBtn");
    if (refreshBtn) {
      if (t === "error") {
        const tip = split.dataset.containerErrorTip || "Ошибка привязки к грузоместу";
        refreshBtn.title = tip;
        split.title = tip;
      } else {
        refreshBtn.title = "Обновить статусы проверки ШК";
        split.removeAttribute("title");
        delete split.dataset.containerErrorTip;
      }
    }
  }

  function kizBadgeHtml(order) {
    if (!order?.kiz_required) return "";
    const status = String(order?.kiz_status || "empty");
    let cls = "is-empty";
    let label = "КИЗ";
    let title = "Требуется маркировка — код не указан";
    if (status === "pending") {
      cls = "is-pending";
      label = "Частично";
      title = "Маркировка сохранена локально, не все коды заполнены";
    } else if (status === "ok") {
      cls = "is-ok";
      title = "Маркировка сохранена локально";
    }
    return `<div class="wb-fbs-kiz ${cls}" title="${esc(title)}">${esc(label)}</div>`;
  }

  function _ozonFbsKizSetInfo(text, ok) {
    const el = document.getElementById("ozonFbsKizInfo");
    if (!el) return;
    const msg = String(text || "").trim();
    el.hidden = !msg;
    el.textContent = msg;
    el.classList.remove("is-warn");
    el.classList.toggle("is-ok", !!msg && !!ok);
  }

  function _ozonFbsPickSetInfo(text, ok) {
    const el = document.getElementById("ozonFbsPickInfo");
    if (!el) return;
    const msg = String(text || "").trim();
    el.hidden = !msg;
    el.textContent = msg;
    el.classList.toggle("is-ok", !!msg && !!ok);
  }

  /**
   * Load marking / pick-verify payloads in chunks until catalog КИЗ resolve is done.
   * Prevents nginx 504 on large supplies.
   */
  async function _ozonFbsFetchResolvedChunks(url, { onProgress, onChunk, shouldAbort } = {}) {
    let data = null;
    let remaining = 1;
    let checkedTotal = 0;
    let guard = 0;
    while (remaining > 0 && guard < 200) {
      if (typeof shouldAbort === "function" && shouldAbort()) {
        return data || {};
      }
      guard += 1;
      const res = await fetch(url);
      if (typeof shouldAbort === "function" && shouldAbort()) {
        return data || {};
      }
      data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      }
      const mr =
        data.marking_resolve && typeof data.marking_resolve === "object"
          ? data.marking_resolve
          : {};
      const checked = Number(mr.checked || 0);
      checkedTotal += checked;
      remaining = Number(mr.remaining || 0);
      if (remaining > 0 && checked <= 0) remaining = 0;
      if (typeof onChunk === "function") {
        onChunk(data, {
          checkedTotal,
          remaining,
          round: guard,
          done: remaining <= 0,
        });
      }
      if (typeof onProgress === "function") {
        onProgress({
          checkedTotal,
          remaining: checkedTotal ? remaining : null,
          round: guard,
          done: remaining <= 0,
        });
      }
    }
    return data || {};
  }

  function _ozonFbsResolveProgressText(progress) {
    const checked = Number(progress?.checkedTotal || 0);
    const remaining = Number(progress?.remaining);
    if (checked && Number.isFinite(remaining) && remaining > 0) {
      const total = checked + remaining;
      return `Определение маркировки… проверено ${checked} из ${total}`;
    }
    if (checked) {
      return `Определение маркировки… проверено ${checked}`;
    }
    return "Определение маркировки…";
  }

  function _ozonFbsKizSplitSetTone(tone) {
    const split = document.getElementById("ozonFbsKizSplit");
    if (!split) return;
    split.classList.remove("is-ok", "is-error");
    const t = String(tone || "").trim().toLowerCase();
    if (t === "ok") split.classList.add("is-ok");
    else if (t === "error") split.classList.add("is-error");
    const refreshBtn = document.getElementById("ozonFbsSupplyDetailKizRefreshBtn");
    if (refreshBtn && t === "error") {
      const tip = split.dataset.containerErrorTip || refreshBtn.title || "Ошибка привязки к грузоместу";
      refreshBtn.title = tip;
    }
  }

  function _ozonFbsKizToneFromSupply(supply) {
    const orders = Array.isArray(supply?.orders) ? supply.orders : [];
    const required = orders.filter((o) => o && o.kiz_required && !_ozonFbsRowIsCancelled(o));
    if (!required.length) return "";
    return required.every((o) => String(o.kiz_status || "") === "ok") ? "ok" : "";
  }

  function _ozonFbsKizStatusFromRow(row) {
    const codes = (Array.isArray(row?.kiz_codes) ? row.kiz_codes : [])
      .map((c) => String(c || "").trim())
      .filter(Boolean);
    const req = Math.max(Number(row?.quantity) || 1, 1);
    if (!codes.length) return "empty";
    if (codes.length >= req) return "ok";
    return "pending";
  }

  function _ozonFbsKizRefreshDetailBadgesFromRows(rows) {
    const supply = supplyDetailState.supply;
    if (!supply || !Array.isArray(supply.orders) || !Array.isArray(rows)) return false;
    const byPn = new Map();
    rows.forEach((row) => {
      const pn = String(row?.posting_number || "").trim();
      if (pn) byPn.set(pn, row);
    });
    let changed = false;
    supply.orders.forEach((o) => {
      const pn = String(o?.posting_number || "").trim();
      const row = byPn.get(pn);
      if (!row || !o.kiz_required) return;
      const st = _ozonFbsKizStatusFromRow(row);
      const codes = (row.kiz_codes || []).map((c) => String(c || "").trim()).filter(Boolean);
      if (String(o.kiz_status || "") !== st) {
        o.kiz_status = st;
        changed = true;
      }
      const prev = JSON.stringify(Array.isArray(o.kiz_codes) ? o.kiz_codes : []);
      const next = JSON.stringify(codes);
      if (prev !== next) {
        o.kiz_codes = codes;
        changed = true;
      }
    });
    return changed;
  }

  function _ozonFbsKizSetFiltersReady(ready) {
    ozonFbsKizState.rowsReady = !!ready;
    const tip = "Дождитесь загрузки заказов";
    const filled = document.getElementById("ozonFbsKizFilterFilled");
    const empty = document.getElementById("ozonFbsKizFilterEmpty");
    const legal = document.getElementById("ozonFbsKizFilterLegal");
    const errors = document.getElementById("ozonFbsKizFilterErrors");
    const cancelled = document.getElementById("ozonFbsKizFilterCancelled");
    const filledLabel = document.getElementById("ozonFbsKizFilterFilledLabel")
      || (filled && filled.closest("label"));
    const emptyLabel = document.getElementById("ozonFbsKizFilterEmptyLabel")
      || (empty && empty.closest("label"));
    const legalLabel = document.getElementById("ozonFbsKizFilterLegalLabel")
      || (legal && legal.closest("label"));
    const errorsLabel = document.getElementById("ozonFbsKizFilterErrorsLabel")
      || (errors && errors.closest("label"));
    const cancelledLabel = document.getElementById("ozonFbsKizFilterCancelledLabel")
      || (cancelled && cancelled.closest("label"));
    const search = document.getElementById("ozonFbsKizSearchFilter");
    const sticker = document.getElementById("ozonFbsKizStickerScan");
    const containerCheck = document.getElementById("ozonFbsKizContainerScanCheck");
    const containerLabel = document.getElementById("ozonFbsKizContainerScanLabel")
      || (containerCheck && containerCheck.closest("label"));

    const setLabelWait = (label, on) => {
      if (!label) return;
      if (on) {
        if (label.dataset.waitTitleSaved === undefined) {
          label.dataset.waitTitleSaved = label.getAttribute("title") || "";
        }
        label.classList.add("is-wait-rows");
        label.setAttribute("title", tip);
      } else {
        label.classList.remove("is-wait-rows");
        const saved = label.dataset.waitTitleSaved;
        if (saved !== undefined) {
          if (saved) label.setAttribute("title", saved);
          else label.removeAttribute("title");
          delete label.dataset.waitTitleSaved;
        }
      }
    };

    const setInputWait = (input, on) => {
      if (!input) return;
      if (on) {
        if (input.dataset.waitTitleSaved === undefined) {
          input.dataset.waitTitleSaved = input.getAttribute("title") || "";
        }
        input.readOnly = true;
        input.setAttribute("aria-disabled", "true");
        input.classList.add("is-wait-rows");
        input.setAttribute("title", tip);
        input.tabIndex = -1;
        if (document.activeElement === input) {
          try { input.blur(); } catch (_) {}
        }
      } else {
        input.readOnly = false;
        input.removeAttribute("aria-disabled");
        input.classList.remove("is-wait-rows");
        input.removeAttribute("tabindex");
        const saved = input.dataset.waitTitleSaved;
        if (saved !== undefined) {
          if (saved) input.setAttribute("title", saved);
          else input.removeAttribute("title");
          delete input.dataset.waitTitleSaved;
        }
      }
    };

    if (filled) filled.disabled = !ready;
    if (empty) empty.disabled = !ready;
    if (legal) legal.disabled = !ready;
    if (errors) errors.disabled = !ready;
    if (cancelled) cancelled.disabled = !ready;
    if (containerCheck) {
      containerCheck.disabled = !ready;
      if (!ready) containerCheck.checked = false;
    }
    setLabelWait(filledLabel, !ready);
    setLabelWait(emptyLabel, !ready);
    setLabelWait(legalLabel, !ready);
    setLabelWait(errorsLabel, !ready);
    setLabelWait(cancelledLabel, !ready);
    setLabelWait(containerLabel, !ready);
    setInputWait(search, !ready);
    setInputWait(sticker, !ready);
    if (typeof window._ozonFbsContainerSyncCheckboxUi === "function") {
      window._ozonFbsContainerSyncCheckboxUi("kiz");
    }
  }

  function _ozonFbsPickSetFiltersReady(ready) {
    ozonFbsPickState.rowsReady = !!ready;
    const tip = "Дождитесь загрузки заказов";
    const filled = document.getElementById("ozonFbsPickFilterFilled");
    const empty = document.getElementById("ozonFbsPickFilterEmpty");
    const errors = document.getElementById("ozonFbsPickFilterErrors");
    const filledLabel = document.getElementById("ozonFbsPickFilterFilledLabel")
      || (filled && filled.closest("label"));
    const emptyLabel = document.getElementById("ozonFbsPickFilterEmptyLabel")
      || (empty && empty.closest("label"));
    const errorsLabel = document.getElementById("ozonFbsPickFilterErrorsLabel")
      || (errors && errors.closest("label"));
    const search = document.getElementById("ozonFbsPickSearchFilter");
    const sticker = document.getElementById("ozonFbsPickStickerScan");
    const containerCheck = document.getElementById("ozonFbsPickContainerScanCheck");
    const containerLabel = document.getElementById("ozonFbsPickContainerScanLabel")
      || (containerCheck && containerCheck.closest("label"));

    const setLabelWait = (label, on) => {
      if (!label) return;
      if (on) {
        if (label.dataset.waitTitleSaved === undefined) {
          label.dataset.waitTitleSaved = label.getAttribute("title") || "";
        }
        label.classList.add("is-wait-rows");
        label.setAttribute("title", tip);
      } else {
        label.classList.remove("is-wait-rows");
        const saved = label.dataset.waitTitleSaved;
        if (saved !== undefined) {
          if (saved) label.setAttribute("title", saved);
          else label.removeAttribute("title");
          delete label.dataset.waitTitleSaved;
        }
      }
    };

    const setInputWait = (input, on) => {
      if (!input) return;
      if (on) {
        if (input.dataset.waitTitleSaved === undefined) {
          input.dataset.waitTitleSaved = input.getAttribute("title") || "";
        }
        input.readOnly = true;
        input.setAttribute("aria-disabled", "true");
        input.classList.add("is-wait-rows");
        input.setAttribute("title", tip);
        input.tabIndex = -1;
        if (document.activeElement === input) {
          try { input.blur(); } catch (_) {}
        }
      } else {
        input.readOnly = false;
        input.removeAttribute("aria-disabled");
        input.classList.remove("is-wait-rows");
        input.removeAttribute("tabindex");
        const saved = input.dataset.waitTitleSaved;
        if (saved !== undefined) {
          if (saved) input.setAttribute("title", saved);
          else input.removeAttribute("title");
          delete input.dataset.waitTitleSaved;
        }
      }
    };

    if (filled) filled.disabled = !ready;
    if (empty) empty.disabled = !ready;
    if (errors) errors.disabled = !ready;
    if (containerCheck) {
      containerCheck.disabled = !ready;
      if (!ready) containerCheck.checked = false;
    }
    setLabelWait(filledLabel, !ready);
    setLabelWait(emptyLabel, !ready);
    setLabelWait(errorsLabel, !ready);
    setLabelWait(containerLabel, !ready);
    setInputWait(search, !ready);
    setInputWait(sticker, !ready);
    if (typeof window._ozonFbsContainerSyncCheckboxUi === "function") {
      window._ozonFbsContainerSyncCheckboxUi("pick");
    }
  }

  function _ozonFbsKizRowFilled(row) {
    const codes = Array.isArray(row?.kiz_codes) ? row.kiz_codes : [];
    const req = Math.max(Number(row?.quantity) || 1, 1);
    const filled = codes.filter((c) => String(c || "").trim()).length;
    return filled >= req;
  }

  function _ozonFbsKizRowHasError(row) {
    const pn = String(row?.posting_number || "");
    return !!String(ozonFbsKizState.errors[pn] || "").trim();
  }

  function _ozonFbsKizUpdateScanCounter() {
    const el = document.getElementById("ozonFbsKizScanCount");
    if (!el) return;
    let filled = 0;
    let total = 0;
    for (const row of ozonFbsKizState.rows) {
      if (_ozonFbsRowIsCancelled(row)) continue;
      const codes = Array.isArray(row?.kiz_codes) && row.kiz_codes.length ? row.kiz_codes : [""];
      total += codes.length;
      for (const code of codes) {
        if (String(code || "").trim()) filled += 1;
      }
    }
    el.textContent = `Просканировано ${filled} из ${total} КИЗ`;
  }

  function _ozonFbsKizStickerIndexAdd(map, key, pn) {
    const k = String(key || "").trim();
    const posting = String(pn || "").trim();
    if (!k || !posting) return;
    const list = map.get(k);
    if (!list) {
      map.set(k, [posting]);
      return;
    }
    if (!list.includes(posting)) list.push(posting);
  }

  /** Rebuild O(1) maps used by high-frequency Marking scans (~hundreds of rows). */
  function _ozonFbsKizRebuildIndexes() {
    const rowsByPosting = new Map();
    const markIndex = new Map();
    const stickerIndex = new Map();
    for (const row of ozonFbsKizState.rows || []) {
      const pn = String(row?.posting_number || "").trim();
      if (!pn) continue;
      rowsByPosting.set(pn, row);
      for (const c of row.kiz_codes || []) {
        const mark = _ozonFbsNormalizeMark(c);
        if (mark) markIndex.set(mark, pn);
      }
      const fields = _ozonFbsResolvedStickerFields(row);
      if (fields.upper) _ozonFbsKizStickerIndexAdd(stickerIndex, _ozonFbsStickerScanKey(fields.upper), pn);
      if (fields.lower) _ozonFbsKizStickerIndexAdd(stickerIndex, _ozonFbsStickerScanKey(fields.lower), pn);
      if (pn) _ozonFbsKizStickerIndexAdd(stickerIndex, pn.toLowerCase(), pn);
    }
    ozonFbsKizState.rowsByPosting = rowsByPosting;
    ozonFbsKizState.markIndex = markIndex;
    ozonFbsKizState.stickerIndex = stickerIndex;
  }

  function _ozonFbsKizRowByPosting(postingNumber) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return null;
    const cached = ozonFbsKizState.rowsByPosting?.get(pn);
    if (cached) return cached;
    return (ozonFbsKizState.rows || []).find((r) => String(r.posting_number) === pn) || null;
  }

  function _ozonFbsKizIndexSetMark(mark, postingNumber) {
    const key = _ozonFbsNormalizeMark(mark);
    const pn = String(postingNumber || "").trim();
    if (!key || !pn) return;
    if (!ozonFbsKizState.markIndex) ozonFbsKizState.markIndex = new Map();
    ozonFbsKizState.markIndex.set(key, pn);
  }

  function _ozonFbsKizIndexClearMark(mark) {
    const key = _ozonFbsNormalizeMark(mark);
    if (!key || !ozonFbsKizState.markIndex) return;
    ozonFbsKizState.markIndex.delete(key);
  }

  function _ozonFbsKizCollectFromDom() {
    const byPn = ozonFbsKizState.rowsByPosting;
    document.querySelectorAll("#ozonFbsKizTbody .wb-fbs-kiz-code-input").forEach((input) => {
      const pn = String(input.dataset.posting || "");
      const idx = Number(input.dataset.idx);
      const row = (byPn && byPn.get(pn)) || ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
      if (!row || !Number.isFinite(idx)) return;
      if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [];
      const prev = _ozonFbsNormalizeMark(row.kiz_codes[idx]);
      const next = _ozonFbsNormalizeMark(input.value);
      row.kiz_codes[idx] = next;
      if (prev && prev !== next) _ozonFbsKizIndexClearMark(prev);
      if (next) _ozonFbsKizIndexSetMark(next, pn);
    });
  }

  function _ozonFbsKizCaptureBaseline() {
    const map = {};
    const gtdMap = {};
    for (const r of ozonFbsKizState.rows) {
      const pn = String(r.posting_number || "").trim();
      if (!pn) continue;
      map[pn] = _ozonFbsKizNormalizeCodesList(r.kiz_codes);
      gtdMap[pn] = String(r.gtd_number || "").trim();
    }
    ozonFbsKizState.baselineByPosting = map;
    ozonFbsKizState.baselineGtdByPosting = gtdMap;
  }

  function _ozonFbsKizBaselineEquals(postingNumber, codes) {
    const pn = String(postingNumber || "").trim();
    const base = ozonFbsKizState.baselineByPosting?.[pn];
    if (!Array.isArray(base)) return false;
    const cur = _ozonFbsKizNormalizeCodesList(codes);
    if (base.length !== cur.length) return false;
    for (let i = 0; i < base.length; i += 1) {
      if (base[i] !== cur[i]) return false;
    }
    return true;
  }

  function _ozonFbsKizFindBySticker(scan) {
    const raw = _ozonFbsNormalizeScan(scan);
    if (!raw) return { row: null, ambiguous: false };
    const index = ozonFbsKizState.stickerIndex;
    if (index && index.size) {
      const rawKey = _ozonFbsStickerScanKey(raw);
      const rawLower = raw.toLowerCase();
      for (const key of [rawKey, rawLower]) {
        const pns = index.get(key);
        if (!pns || !pns.length) continue;
        const rows = pns.map((pn) => _ozonFbsKizRowByPosting(pn)).filter(Boolean);
        if (rows.length === 1) return { row: rows[0], ambiguous: false };
        if (rows.length > 1) return { row: null, ambiguous: true, matches: rows };
      }
    }
    return _ozonFbsFindByStickerInRows(scan, ozonFbsKizState.rows, { includeCancelled: true });
  }

  async function _ozonFbsKizFindByStickerWithLookup(scan) {
    const local = _ozonFbsKizFindBySticker(scan);
    if (local.row || local.ambiguous) return local;
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    const raw = _ozonFbsNormalizeScan(scan);
    if (!sourceId || !raw) return local;
    try {
      const params = new URLSearchParams({ source_id: String(sourceId), scan: raw });
      const res = await fetch(`/api/ozon-fbs/postings/lookup?${params}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.found || !data.posting) return local;
      const pn = String(data.posting.posting_number || "").trim();
      if (!pn) return local;
      const row = _ozonFbsKizRowByPosting(pn);
      if (!row) return local;
      row.sticker_barcode = String(data.posting.sticker_barcode || row.sticker_barcode || "").trim();
      row.sticker_lower_barcode = String(
        data.posting.sticker_lower_barcode || row.sticker_lower_barcode || ""
      ).trim();
      row.sticker_part_a = String(data.posting.sticker_part_a || row.sticker_part_a || "").trim();
      row.sticker_part_b = String(data.posting.sticker_part_b || row.sticker_part_b || "").trim();
      _ozonFbsKizRebuildIndexes();
      return { row, ambiguous: false };
    } catch (_) {
      return local;
    }
  }

  function _ozonFbsKizFindByPosting(scan) {
    return _ozonFbsFindByStickerInRows(scan, ozonFbsKizState.rows);
  }

  function _ozonFbsKizFindExistingMark(mark) {
    const key = _ozonFbsNormalizeMark(mark);
    if (!key) return null;
    const indexedPn = ozonFbsKizState.markIndex?.get(key);
    if (indexedPn) {
      const row = _ozonFbsKizRowByPosting(indexedPn);
      if (row) return row;
    }
    for (const row of ozonFbsKizState.rows) {
      for (const c of row.kiz_codes || []) {
        if (_ozonFbsNormalizeMark(c) === key) {
          _ozonFbsKizIndexSetMark(key, row.posting_number);
          return row;
        }
      }
    }
    return null;
  }

  function onOzonFbsKizFilterFilledChange() {
    const filled = document.getElementById("ozonFbsKizFilterFilled");
    const empty = document.getElementById("ozonFbsKizFilterEmpty");
    if (filled?.checked && empty) empty.checked = false;
    renderOzonFbsKizTable();
  }

  function onOzonFbsKizFilterEmptyChange() {
    const filled = document.getElementById("ozonFbsKizFilterFilled");
    const empty = document.getElementById("ozonFbsKizFilterEmpty");
    if (empty?.checked && filled) filled.checked = false;
    renderOzonFbsKizTable();
  }

  function renderOzonFbsKizTable(opts) {
    if (!opts?.skipCollect) _ozonFbsKizCollectFromDom();
    const tbody = document.getElementById("ozonFbsKizTbody");
    if (!tbody) return;
    const q = String(document.getElementById("ozonFbsKizSearchFilter")?.value || "")
      .trim()
      .toLowerCase();
    const showFilled = !!document.getElementById("ozonFbsKizFilterFilled")?.checked;
    const showEmpty = !!document.getElementById("ozonFbsKizFilterEmpty")?.checked;
    const showLegal = !!document.getElementById("ozonFbsKizFilterLegal")?.checked;
    const showErrors = !!document.getElementById("ozonFbsKizFilterErrors")?.checked;
    const showCancelled = !!document.getElementById("ozonFbsKizFilterCancelled")?.checked;
    const pending = String(ozonFbsKizState.pendingPosting || "").trim();
    const rows = (ozonFbsKizState.rows || []).filter((r) => {
      if (showFilled && _ozonFbsKizRowIsEmpty(r)) return false;
      if (showEmpty && !_ozonFbsKizRowIsEmpty(r)) return false;
      // Ozon юрлицо: requirements.products_requiring_gtd → gtd_required.
      if (showLegal && !r?.gtd_required) return false;
      if (showErrors && !_ozonFbsKizRowHasError(r)) return false;
      if (showCancelled && !String(r?.cancel_reason_label || "").trim()) return false;
      if (!q) return true;
      const hay = [
        r.posting_number, r.offer_id, r.product_name, r.sku,
        r.sticker_barcode, r.sticker_part_a, r.sticker_part_b,
        r.container_barcode, r.container_id,
        ...(Array.isArray(r.barcodes) ? r.barcodes : []),
      ].map((x) => String(x || "").toLowerCase()).join(" ");
      return hay.includes(q);
    });
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="wb-fbs-empty">${
        ozonFbsKizState.rows?.length ? "Нет строк по выбранным фильтрам" : "Нет отправлений с маркировкой"
      }</td></tr>`;
      _ozonFbsKizRebuildIndexes();
      _ozonFbsKizUpdateScanCounter();
      if (typeof _ozonFbsContainerUpdateCounters === "function") _ozonFbsContainerUpdateCounters();
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const pn = String(r.posting_number || "");
      const safePn = esc(pn);
      const menuKey = _ozonFbsPostingMenuKey(pn);
      const isCancelled = _ozonFbsRowIsCancelled(r);
      const codes = Array.isArray(r.kiz_codes) && r.kiz_codes.length ? r.kiz_codes : [""];
      const err = String(ozonFbsKizState.errors[pn] || "").trim();
      const photo = r.product_photo
        ? `<img class="wb-fbs-product-photo" src="${esc(r.product_photo)}" alt="" width="56" height="56" loading="lazy">`
        : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
      const barcodes = Array.isArray(r.barcodes) ? r.barcodes : [];
      const barcodeHtml = barcodes.length
        ? `<div class="wb-fbs-kiz-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
            `<div class="wb-fbs-kiz-barcode">${esc(b)}</div>`
          ).join("")}</div>`
        : "";
      const canRemoveRow = !isCancelled && codes.length > 1;
      const codeHtml = isCancelled
        ? codes
            .map((code, idx) => {
              const val = String(code || "").trim();
              return `<div class="wb-fbs-kiz-code-block is-readonly">
                <div class="wb-fbs-kiz-code-row">
                  <span class="wb-fbs-kiz-code-idx">${idx + 1}</span>
                  <span class="wb-fbs-kiz-code-readonly">${val ? esc(val) : "—"}</span>
                </div>
              </div>`;
            })
            .join("")
        : codes.map((code, idx) => {
        const clearTitle = canRemoveRow ? "Удалить строку КИЗ" : "Очистить маркировку";
        return `
        <div class="wb-fbs-kiz-code-block">
          <div class="wb-fbs-kiz-code-row">
            <span class="wb-fbs-kiz-code-idx">${idx + 1}</span>
            <input id="ozonFbsKizCode_${menuKey}_${idx}"
                   class="wb-fbs-kiz-code-input${err && String(code || "").trim() ? " is-error" : ""}" type="text"
                   data-posting="${safePn}" data-idx="${idx}"
                   autocomplete="off"
                   oninput="onOzonFbsKizCodeInput('${safePn}', event)"
                   onblur="onOzonFbsKizCodeBlur('${safePn}', event)"
                   onkeydown="onOzonFbsKizCodeKey('${safePn}', event)" />
            <button type="button" class="wb-fbs-kiz-remove" title="${clearTitle}"
                    aria-label="${clearTitle}"
                    onclick="removeOzonFbsKizCode('${safePn}', ${idx})">×</button>
          </div>
          ${err && String(code || "").trim() ? `<div class="wb-fbs-kiz-code-status is-error">${esc(err)}</div>` : ""}
        </div>`;
      }).join("");
      const menuIcon = typeof _wbFbsQrMenuIconHtml === "function" ? _wbFbsQrMenuIconHtml() : "";
      return `<tr class="wb-fbs-kiz-row${pending === pn ? " is-active" : ""}${isCancelled ? " is-cancelled" : ""}" data-posting="${safePn}">
        <td>
          ${_ozonFbsModalPostingColHtml(r)}
        </td>
        <td>
          <div class="wb-fbs-product">
            ${photo}
            <div class="wb-fbs-product-text">
              <div class="wb-fbs-product-name" title="${esc(r.product_name || r.offer_id || "")}">${esc(r.product_name || r.offer_id || "—")}</div>
              <div class="wb-fbs-product-sub">Арт. ${esc(r.offer_id || "—")}</div>
              ${barcodeHtml}
              ${cancelBadgeHtml(r)}
            </div>
          </div>
        </td>
        <td>
          <div class="wb-fbs-kiz-codes">${codeHtml}</div>
          ${
            isCancelled
              ? ""
              : `<button type="button" class="wb-fbs-kiz-add" onclick="addOzonFbsKizCode('${safePn}')">+ Добавить КИЗ</button>`
          }
          ${
            !isCancelled && r.gtd_required
              ? `<div class="ozon-fbs-packaging-exemplar-field" style="margin-top:12px">
                   <label for="ozonFbsKizGtd_${safePn}">ГТД (юрлицо)</label>
                   <input id="ozonFbsKizGtd_${safePn}" type="text" class="ozon-fbs-kiz-gtd-input"
                          data-posting="${safePn}" autocomplete="off"
                          value="${esc(r.gtd_number || "")}"
                          placeholder="Номер ГТД"
                          oninput="onOzonFbsKizGtdInput('${safePn}', event)" />
                 </div>`
              : (r.gtd_number
                  ? `<div class="wb-fbs-order-meta" style="margin-top:8px">ГТД: ${esc(r.gtd_number)}</div>`
                  : "")
          }
        </td>
        <td class="wb-fbs-kiz-col-container">${
          typeof _ozonFbsContainerCellHtml === "function"
            ? _ozonFbsContainerCellHtml(r, "kiz")
            : "—"
        }</td>
        <td>
          <div class="wb-fbs-row-menu-wrap">
            <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
                    onclick="toggleOzonFbsRowMenu(event, '${menuKey}')" aria-haspopup="menu">⋮</button>
            <div id="ozonFbsRowMenu_${menuKey}" class="wb-fbs-row-menu" data-order-id="${menuKey}" role="menu">
              <button type="button" class="wb-fbs-row-menu-item" role="menuitem"
                      onclick="ozonFbsPrintOnePostingStickerFromDetail(event, '${safePn}')">
                ${menuIcon}
                Напечатать стикер
              </button>
            </div>
          </div>
        </td>
      </tr>`;
    }).join("");
    tbody.querySelectorAll(".wb-fbs-kiz-code-input").forEach((input) => {
      const pn = String(input.dataset.posting || "");
      const idx = Number(input.dataset.idx);
      const row = _ozonFbsKizRowByPosting(pn);
      if (!row || !Number.isFinite(idx)) return;
      const rowCodes = Array.isArray(row.kiz_codes) ? row.kiz_codes : [];
      input.value = String(rowCodes[idx] ?? "");
    });
    _ozonFbsKizRebuildIndexes();
    _ozonFbsKizUpdateScanCounter();
    if (typeof _ozonFbsContainerUpdateCounters === "function") _ozonFbsContainerUpdateCounters();
  }

  /**
   * Patch one existing KIZ input after a wedge scan (no full table rebuild).
   * Returns false when DOM cannot represent the new state → caller should full-render.
   */
  function _ozonFbsKizPatchScannedCode(postingNumber, codeIdx, mark) {
    const pn = String(postingNumber || "").trim();
    const idx = Number(codeIdx);
    if (!pn || !Number.isFinite(idx) || idx < 0) return false;
    const tr = document.querySelector(`#ozonFbsKizTbody tr.wb-fbs-kiz-row[data-posting="${pn}"]`);
    if (!tr) return false;
    const input = tr.querySelector(`.wb-fbs-kiz-code-input[data-posting="${pn}"][data-idx="${idx}"]`);
    if (!input) return false;
    input.value = String(mark || "");
    input.classList.remove("is-error");
    const block = input.closest(".wb-fbs-kiz-code-block");
    if (block) block.querySelectorAll(".wb-fbs-kiz-code-status").forEach((node) => node.remove());
    _ozonFbsKizUpdateScanCounter();
    return true;
  }

  /** Append a new KIZ slot into an existing row without rebuilding the whole table. */
  function _ozonFbsKizAppendScannedCodeSlot(postingNumber, codeIdx, mark) {
    const pn = String(postingNumber || "").trim();
    const idx = Number(codeIdx);
    if (!pn || !Number.isFinite(idx) || idx < 0) return false;
    const tr = document.querySelector(`#ozonFbsKizTbody tr.wb-fbs-kiz-row[data-posting="${pn}"]`);
    if (!tr) return false;
    const codesWrap = tr.querySelector(".wb-fbs-kiz-codes");
    if (!codesWrap) return false;
    const safePn = esc(pn);
    const menuKey = _ozonFbsPostingMenuKey(pn);
    const clearTitle = "Удалить строку КИЗ";
    codesWrap.insertAdjacentHTML(
      "beforeend",
      `<div class="wb-fbs-kiz-code-block">
          <div class="wb-fbs-kiz-code-row">
            <span class="wb-fbs-kiz-code-idx">${idx + 1}</span>
            <input id="ozonFbsKizCode_${menuKey}_${idx}"
                   class="wb-fbs-kiz-code-input" type="text"
                   data-posting="${safePn}" data-idx="${idx}"
                   autocomplete="off"
                   oninput="onOzonFbsKizCodeInput('${safePn}', event)"
                   onblur="onOzonFbsKizCodeBlur('${safePn}', event)"
                   onkeydown="onOzonFbsKizCodeKey('${safePn}', event)" />
            <button type="button" class="wb-fbs-kiz-remove" title="${clearTitle}"
                    aria-label="${clearTitle}"
                    onclick="removeOzonFbsKizCode('${safePn}', ${idx})">×</button>
          </div>
        </div>`
    );
    const input = document.getElementById(`ozonFbsKizCode_${menuKey}_${idx}`);
    if (input) input.value = String(mark || "");
    tr.querySelectorAll(".wb-fbs-kiz-remove").forEach((btn) => {
      btn.title = clearTitle;
      btn.setAttribute("aria-label", clearTitle);
    });
    _ozonFbsKizUpdateScanCounter();
    return true;
  }

  function onOzonFbsKizGtdInput(postingNumber, event) {
    const pn = String(postingNumber || "").trim();
    const row = _ozonFbsKizRowByPosting(pn);
    if (!row) return;
    row.gtd_number = String(event?.target?.value || "").trim();
    // Keep GTD in local autosave so it is not lost before «Сохранить».
    _ozonFbsKizScheduleLocalAutosave(pn, false);
  }

  function onOzonFbsKizCodeInput(postingNumber, event) {
    const pn = String(postingNumber || "");
    const input = event?.target;
    if (input && typeof _wbFbsKizHasCyrillic === "function") {
      if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
        input.value = "";
        return;
      }
      if (_wbFbsKizHasCyrillic(input.value)) {
        const idx = Number(input.dataset.idx);
        const row = _ozonFbsKizRowByPosting(pn);
        if (row && Array.isArray(row.kiz_codes) && Number.isFinite(idx) && idx >= 0) {
          const prev = _ozonFbsNormalizeMark(row.kiz_codes[idx]);
          if (prev) _ozonFbsKizIndexClearMark(prev);
          row.kiz_codes[idx] = "";
        }
        if (ozonFbsKizState.errors[pn]) delete ozonFbsKizState.errors[pn];
        if (typeof _wbFbsKizBlockRuLayout === "function") _wbFbsKizBlockRuLayout(input);
        _ozonFbsKizUpdateScanCounter();
        return;
      }
    }
    if (ozonFbsKizState.errors[pn]) delete ozonFbsKizState.errors[pn];
    _ozonFbsKizCollectFromDom();
    const row = _ozonFbsKizRowByPosting(pn);
    if (row) {
      const codes = _ozonFbsKizNormalizeCodesList(row.kiz_codes);
      if (!codes.length) {
        delete ozonFbsKizState.errors[pn];
        if (String(row.kiz_status || "") === "error") row.kiz_status = "empty";
      } else {
        row.kiz_status = "pending";
      }
    }
    _ozonFbsKizUpdateScanCounter();
  }

  function onOzonFbsKizCodeBlur(postingNumber, _event) {
    const pn = String(postingNumber || "").trim();
    if (!pn || !_ozonFbsKizModalIsOpen()) return;
    _ozonFbsKizCollectFromDom();
    _ozonFbsKizScheduleLocalAutosave(pn, false);
  }

  function onOzonFbsKizCodeKey(postingNumber, event) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    const pn = String(postingNumber || "").trim();
    if (!pn) return;
    _ozonFbsKizCollectFromDom();
    _ozonFbsKizScheduleLocalAutosave(pn, false);
    const sticker = document.getElementById("ozonFbsKizStickerScan");
    if (sticker) {
      sticker.focus();
      sticker.select?.();
    }
  }

  function addOzonFbsKizCode(postingNumber) {
    _ozonFbsKizCollectFromDom();
    const pn = String(postingNumber || "");
    const row = _ozonFbsKizRowByPosting(pn);
    if (!row) return;
    if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [""];
    row.kiz_codes.push("");
    renderOzonFbsKizTable({ skipCollect: true });
    const inputs = document.querySelectorAll(`.wb-fbs-kiz-code-input[data-posting="${pn}"]`);
    const last = inputs[inputs.length - 1];
    if (last) last.focus();
  }

  function removeOzonFbsKizCode(postingNumber, idx) {
    _ozonFbsKizCollectFromDom();
    const pn = String(postingNumber || "");
    const removeIdx = Number(idx);
    const row = _ozonFbsKizRowByPosting(pn);
    if (!row || !Number.isFinite(removeIdx)) return;
    if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [""];
    const removedMark = _ozonFbsNormalizeMark(row.kiz_codes[removeIdx]);
    if (row.kiz_codes.length <= 1) {
      row.kiz_codes = [""];
    } else {
      row.kiz_codes.splice(removeIdx, 1);
      if (!row.kiz_codes.length) row.kiz_codes = [""];
    }
    if (removedMark) _ozonFbsKizIndexClearMark(removedMark);
    delete ozonFbsKizState.errors[pn];
    if (!_ozonFbsKizNormalizeCodesList(row.kiz_codes).length) {
      row.kiz_status = "empty";
    }
    renderOzonFbsKizTable({ skipCollect: true });
    _ozonFbsKizScheduleLocalAutosave(pn, !_ozonFbsKizNormalizeCodesList(row.kiz_codes).length);
  }

  function clearOzonFbsKizRow(postingNumber) {
    const pn = String(postingNumber || "");
    const row = _ozonFbsKizRowByPosting(pn);
    if (!row) return;
    for (const c of row.kiz_codes || []) {
      const mark = _ozonFbsNormalizeMark(c);
      if (mark) _ozonFbsKizIndexClearMark(mark);
    }
    row.kiz_codes = [""];
    row.kiz_status = "empty";
    delete ozonFbsKizState.errors[pn];
    renderOzonFbsKizTable();
    _ozonFbsKizScheduleLocalAutosave(pn, true);
  }

  /**
   * Silent local save after each scan (WB FBS parity).
   * - Persists to FeedPilot only (`local_only`) — never waits on Ozon API.
   * - Per-posting seq coalesces rapid re-scans of the same posting.
   * - Microtask batches different postings touched in the same turn into one PUT.
   * - Scan path never awaits; UI stays responsive under hundreds of marks.
   * - Always adopt server kiz_saved_at on ok (even if a newer scan is pending)
   *   so the next PUT does not false-conflict on stale expected_saved_at.
   */
  function _ozonFbsKizScheduleLocalAutosave(postingNumber, clear) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return;
    if (!ozonFbsKizState.localAutosaveSeqByPosting) ozonFbsKizState.localAutosaveSeqByPosting = {};
    if (!ozonFbsKizState.localAutosaveDirty) ozonFbsKizState.localAutosaveDirty = new Set();
    if (!ozonFbsKizState.localAutosaveClearByPosting) ozonFbsKizState.localAutosaveClearByPosting = {};
    const seq = (Number(ozonFbsKizState.localAutosaveSeqByPosting[pn]) || 0) + 1;
    ozonFbsKizState.localAutosaveSeqByPosting[pn] = seq;
    ozonFbsKizState.localAutosaveDirty.add(pn);
    if (clear) ozonFbsKizState.localAutosaveClearByPosting[pn] = true;
    else delete ozonFbsKizState.localAutosaveClearByPosting[pn];
    if (ozonFbsKizState.localAutosaveFlushQueued) return;
    ozonFbsKizState.localAutosaveFlushQueued = true;
    queueMicrotask(() => {
      ozonFbsKizState.localAutosaveFlushQueued = false;
      _ozonFbsKizQueueDirtyAutosaveFlush();
    });
  }

  function _ozonFbsKizQueueDirtyAutosaveFlush() {
    const dirty = ozonFbsKizState.localAutosaveDirty;
    if (!dirty || !dirty.size) return;
    const postings = Array.from(dirty);
    dirty.clear();
    const clearFlags = { ...(ozonFbsKizState.localAutosaveClearByPosting || {}) };
    for (const pn of postings) {
      delete ozonFbsKizState.localAutosaveClearByPosting?.[pn];
    }
    const seqSnapshot = {};
    for (const pn of postings) {
      seqSnapshot[pn] = Number(ozonFbsKizState.localAutosaveSeqByPosting?.[pn]) || 0;
    }
    const run = () => _ozonFbsKizFlushLocalAutosaveBatch(postings, clearFlags, seqSnapshot);
    ozonFbsKizState.localAutosaveChain = (ozonFbsKizState.localAutosaveChain || Promise.resolve())
      .then(run, run)
      .catch(() => {});
  }

  function _ozonFbsKizAwaitLocalAutosaves() {
    return (async () => {
      if (ozonFbsKizState.localAutosaveFlushQueued) {
        ozonFbsKizState.localAutosaveFlushQueued = false;
        _ozonFbsKizQueueDirtyAutosaveFlush();
      }
      for (let i = 0; i < 40; i += 1) {
        if (ozonFbsKizState.localAutosaveFlushQueued) {
          ozonFbsKizState.localAutosaveFlushQueued = false;
          _ozonFbsKizQueueDirtyAutosaveFlush();
        }
        const tip = ozonFbsKizState.localAutosaveChain || Promise.resolve();
        try {
          await tip;
        } catch (_e) {
          /* ignore — Save still covers drafts */
        }
        const latest = ozonFbsKizState.localAutosaveChain || tip;
        const inflight = Number(ozonFbsKizState.localAutosaveInflight) || 0;
        const dirtyLeft = ozonFbsKizState.localAutosaveDirty?.size || 0;
        if (tip === latest && inflight <= 0 && dirtyLeft <= 0 && !ozonFbsKizState.localAutosaveFlushQueued) {
          return;
        }
      }
    })();
  }

  async function _ozonFbsKizFlushLocalAutosaveBatch(postings, clearFlags, seqSnapshot, attempt = 0) {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsKizModalIsOpen()) return;

    const items = [];
    const codesByPosting = {};
    for (const pn of postings || []) {
      const seq = Number(seqSnapshot?.[pn]) || 0;
      // Newer scan already superseded this snapshot — skip obsolete write.
      if ((Number(ozonFbsKizState.localAutosaveSeqByPosting?.[pn]) || 0) !== seq) continue;
      const row = _ozonFbsKizRowByPosting(pn);
      if (!row || _ozonFbsRowIsCancelled(row)) continue;
      const codes = _ozonFbsKizNormalizeCodesList(row.kiz_codes);
      const wantClear = !!(clearFlags && clearFlags[pn]) && !codes.length;
      const gtdNow = String(row.gtd_number || "").trim();
      const gtdBase = String(ozonFbsKizState.baselineGtdByPosting?.[pn] || "").trim();
      const gtdDirty = gtdNow !== gtdBase;
      if (!codes.length && !wantClear && !gtdDirty) continue;
      if (!wantClear && _ozonFbsKizBaselineEquals(pn, codes) && !gtdDirty) continue;
      codesByPosting[pn] = codes.slice();
      items.push({
        posting_number: pn,
        kiz_codes: codes,
        gtd_number: gtdNow,
        expected_saved_at: String(row.kiz_saved_at || ""),
        force: !!(ozonFbsKizState.forceSaveByPosting && ozonFbsKizState.forceSaveByPosting[pn]),
        clear: wantClear,
      });
    }
    if (!items.length) return;

    ozonFbsKizState.localAutosaveInflight = (Number(ozonFbsKizState.localAutosaveInflight) || 0) + 1;
    let retryPostings = null;
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking?source_id=${sourceId}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({ items, local_only: true }),
          keepalive: true,
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (attempt < 1) retryPostings = postings.slice();
        return;
      }
      for (const result of data.results || []) {
        const pn = String(result?.posting_number || "").trim();
        if (!pn) continue;
        const row = _ozonFbsKizRowByPosting(pn);
        if (!row) continue;
        const seq = Number(seqSnapshot?.[pn]) || 0;
        const seqCurrent = (Number(ozonFbsKizState.localAutosaveSeqByPosting?.[pn]) || 0) === seq;
        const stillDirty = !!ozonFbsKizState.localAutosaveDirty?.has(pn);

        if (result.conflict) {
          // Adopt server clock so the next write (often force) is consistent.
          row.kiz_saved_at = String(result.kiz_saved_at || row.kiz_saved_at || "");
          if (!ozonFbsKizState.forceSaveByPosting) ozonFbsKizState.forceSaveByPosting = {};
          ozonFbsKizState.forceSaveByPosting[pn] = true;
          if (seqCurrent && !stillDirty) {
            _ozonFbsKizSetInfo(
              result.error
                || "Коды изменены другим оператором — проверьте КИЗ и сохраните снова"
            );
          }
          continue;
        }
        if (!result.ok) {
          if (attempt < 1 && seqCurrent) {
            if (!retryPostings) retryPostings = [];
            if (!retryPostings.includes(pn)) retryPostings.push(pn);
          }
          continue;
        }

        // Server write succeeded — always refresh optimistic token (even if a
        // newer scan is already queued). Prevents self false-conflicts.
        if (result.kiz_saved_at) {
          row.kiz_saved_at = String(result.kiz_saved_at);
        }
        if (seqCurrent && !stillDirty) {
          if (!ozonFbsKizState.baselineByPosting) ozonFbsKizState.baselineByPosting = {};
          ozonFbsKizState.baselineByPosting[pn] = (codesByPosting[pn] || []).slice();
          if (!ozonFbsKizState.baselineGtdByPosting) ozonFbsKizState.baselineGtdByPosting = {};
          ozonFbsKizState.baselineGtdByPosting[pn] = String(row.gtd_number || "").trim();
          if (typeof result.kiz_ozon_synced === "boolean") {
            row.kiz_ozon_synced = !!result.kiz_ozon_synced;
          }
          delete ozonFbsKizState.forceSaveByPosting?.[pn];
          delete ozonFbsKizState.errors[pn];
        }
      }
    } catch (_e) {
      if (attempt < 1) retryPostings = (postings || []).slice();
    } finally {
      ozonFbsKizState.localAutosaveInflight = Math.max(
        0,
        (Number(ozonFbsKizState.localAutosaveInflight) || 1) - 1
      );
    }
    if (retryPostings && retryPostings.length) {
      await new Promise((r) => setTimeout(r, 120));
      const still = retryPostings.filter((pn) => {
        const seq = Number(seqSnapshot?.[pn]) || 0;
        return (Number(ozonFbsKizState.localAutosaveSeqByPosting?.[pn]) || 0) === seq;
      });
      if (still.length) {
        return _ozonFbsKizFlushLocalAutosaveBatch(still, clearFlags, seqSnapshot, attempt + 1);
      }
    }
  }

  function _ozonFbsKizSyncActiveCodeInput() {
    const active = document.activeElement;
    if (!active || !active.classList?.contains("wb-fbs-kiz-code-input")) return;
    if (!active.closest?.("#ozonFbsKizTbody")) return;
    const pn = String(active.dataset.posting || "").trim();
    const idx = Number(active.dataset.idx);
    const row = _ozonFbsKizRowByPosting(pn);
    if (!row || !Number.isFinite(idx) || idx < 0) return;
    if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [];
    const prev = _ozonFbsNormalizeMark(row.kiz_codes[idx]);
    const next = _ozonFbsNormalizeMark(active.value);
    row.kiz_codes[idx] = next;
    if (prev && prev !== next) _ozonFbsKizIndexClearMark(prev);
    if (next) _ozonFbsKizIndexSetMark(next, pn);
  }

  async function onOzonFbsKizStickerScanKey(event) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    const input = event.target;
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
      _ozonFbsKizScanDiag("sticker_enter_ru_modal", _ozonFbsKizScanDiagSnapshot(input));
      return;
    }
    if (input?.disabled || input?.readOnly || !ozonFbsKizState.rowsReady) {
      _ozonFbsKizScanDiag(
        "sticker_enter_blocked",
        _ozonFbsKizScanDiagSnapshot(input)
      );
      return;
    }
    const rawTyped = String(input?.value || "").replace(/\s+/g, "").trim();
    if (!rawTyped) {
      // Digits never reached the field (swallow/readonly) or scanner sent bare Enter.
      _ozonFbsKizScanDiag("sticker_enter_empty", _ozonFbsKizScanDiagSnapshot(input));
      return;
    }
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(rawTyped)) {
      _ozonFbsKizScanDiag(
        "sticker_enter_cyrillic",
        `${_ozonFbsKizScanDiagSnapshot(input)} sampleLen=${rawTyped.length}`
      );
      if (typeof _wbFbsKizBlockRuLayout === "function") _wbFbsKizBlockRuLayout(input);
      return;
    }
    if (typeof _ozonFbsContainerIsScanMode === "function" && _ozonFbsContainerIsScanMode("kiz")) {
      await _ozonFbsContainerHandleScan("kiz", rawTyped);
      return;
    }
    // Sync only the focused cell (if any) — avoid walking hundreds of inputs.
    _ozonFbsKizSyncActiveCodeInput();
    const found = await _ozonFbsKizFindByStickerWithLookup(rawTyped);
    if (found.ambiguous) {
      const ids = (found.matches || []).map((r) => r.posting_number).slice(0, 5).join(", ");
      _ozonFbsKizSetInfo(
        `Код этикетки совпадает у нескольких отправлений (${ids}${
          (found.matches || []).length > 5 ? "…" : ""
        }). Отсканируйте QR ещё раз.`
      );
      if (input) input.select();
      return;
    }
    if (!found.row) {
      _ozonFbsKizSetInfo(
        `Отправление «${rawTyped}» не найдено среди товаров с маркировкой.`
      );
      if (input) input.select();
      return;
    }
    ozonFbsKizState.pendingPosting = String(found.row.posting_number || "");
    void _ozonFbsPersistStickerForRow(found.row, rawTyped);
    if (typeof _ozonFbsContainerMaybeBind === "function") {
      const okBind = await _ozonFbsContainerMaybeBind("kiz", ozonFbsKizState.pendingPosting);
      if (!okBind) {
        ozonFbsKizState.pendingPosting = null;
        if (input) input.select();
        return;
      }
    }
    _ozonFbsKizSetInfo("");
    if (input) input.value = "";
    const meta = document.getElementById("ozonFbsKizScanPromptMeta");
    if (meta) meta.textContent = `Отправление ${ozonFbsKizState.pendingPosting}`;
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsKizScanPrompt", true);
    else document.getElementById("ozonFbsKizScanPrompt")?.classList.remove("hidden");
    const mark = document.getElementById("ozonFbsKizMarkScan");
    if (mark) {
      mark.value = "";
      setTimeout(() => mark.focus(), 40);
    }
  }

  function cancelOzonFbsKizMarkScan() {
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsKizScanPrompt", false);
    else document.getElementById("ozonFbsKizScanPrompt")?.classList.add("hidden");
    ozonFbsKizState.pendingPosting = null;
    const sticker = document.getElementById("ozonFbsKizStickerScan");
    if (sticker) setTimeout(() => sticker.focus(), 40);
  }

  function onOzonFbsKizMarkScanKey(event) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    const input = event.target;
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) {
      _ozonFbsKizScanDiag("mark_enter_ru_modal", _ozonFbsKizScanDiagSnapshot(input));
      return;
    }
    const pn = String(ozonFbsKizState.pendingPosting || "");
    const rawTyped = String(input?.value || "");
    if (!pn || !String(rawTyped || "").replace(/\s+/g, "")) {
      _ozonFbsKizScanDiag(
        "mark_enter_empty",
        `${_ozonFbsKizScanDiagSnapshot(input)} pn=${pn || "-"}`
      );
      return;
    }
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(rawTyped)) {
      _ozonFbsKizScanDiag(
        "mark_enter_cyrillic",
        `${_ozonFbsKizScanDiagSnapshot(input)} pn=${pn}`
      );
      if (typeof _wbFbsKizBlockRuLayout === "function") _wbFbsKizBlockRuLayout(input);
      return;
    }
    const mark = _ozonFbsNormalizeMark(rawTyped);
    if (!mark) return;
    _ozonFbsKizSyncActiveCodeInput();
    const row = _ozonFbsKizRowByPosting(pn);
    if (!row) {
      cancelOzonFbsKizMarkScan();
      return;
    }
    const check = _ozonFbsKizValidateMarkForOrder(mark, row);
    if (!check.ok) {
      _ozonFbsKizSetInfo(check.error || "Маркировка не подходит к ШК товара в отправлении");
      if (input) input.select();
      return;
    }
    const dup = _ozonFbsKizFindExistingMark(mark);
    if (dup) {
      const dupPn = String(dup.posting_number || "");
      _ozonFbsKizSetInfo(
        dupPn === pn
          ? `Этот КИЗ уже просканирован в отправление ${pn} — повторно не добавляем`
          : `Этот КИЗ уже просканирован в отправление ${dupPn} — в ${pn} не добавляем`
      );
      if (input) input.select();
      return;
    }
    if (!Array.isArray(row.kiz_codes) || !row.kiz_codes.length) row.kiz_codes = [""];
    let placedIdx = -1;
    for (let i = 0; i < row.kiz_codes.length; i += 1) {
      if (!String(row.kiz_codes[i] || "").trim()) {
        row.kiz_codes[i] = mark;
        placedIdx = i;
        break;
      }
    }
    const addedSlot = placedIdx < 0;
    if (addedSlot) {
      row.kiz_codes.push(mark);
      placedIdx = row.kiz_codes.length - 1;
    }
    row.kiz_status = "pending";
    delete ozonFbsKizState.errors[pn];
    _ozonFbsKizIndexSetMark(mark, pn);
    const emptyFilter = document.getElementById("ozonFbsKizFilterEmpty");
    const emptyFilterWasOn = !!emptyFilter?.checked;
    if (emptyFilter) emptyFilter.checked = false;
    cancelOzonFbsKizMarkScan();
    if (
      emptyFilterWasOn
      || (addedSlot
        ? !_ozonFbsKizAppendScannedCodeSlot(pn, placedIdx, mark)
        : !_ozonFbsKizPatchScannedCode(pn, placedIdx, mark))
    ) {
      renderOzonFbsKizTable({ skipCollect: true });
    }
    _ozonFbsKizSetInfo(`КИЗ сохранён локально для ${pn}`, true);
    _ozonFbsKizScheduleLocalAutosave(pn, false);
    const rowEl = document.querySelector(`#ozonFbsKizTbody tr[data-posting="${pn}"]`);
    if (rowEl) rowEl.scrollIntoView({ block: "nearest" });
  }

  function _ozonFbsKizApplySaveResults(results) {
    (results || []).forEach((r) => {
      if (!r || !r.ok) return;
      const pn = String(r.posting_number || "").trim();
      if (!pn) return;
      const row = _ozonFbsKizRowByPosting(pn);
      if (!row) return;
      if (Array.isArray(r.kiz_codes)) {
        row.kiz_codes = r.kiz_codes.length ? r.kiz_codes.slice() : [""];
      }
      if (r.kiz_saved_at) row.kiz_saved_at = String(r.kiz_saved_at);
      if (typeof r.kiz_ozon_synced === "boolean") {
        row.kiz_ozon_synced = !!r.kiz_ozon_synced;
      }
      if (r.gtd_number != null) row.gtd_number = String(r.gtd_number || "").trim();
      row.kiz_status = _ozonFbsKizStatusFromRow(row);
    });
    _ozonFbsKizCaptureBaseline();
    renderOzonFbsKizTable();
    _ozonFbsKizRefreshDetailBadgesFromRows(ozonFbsKizState.rows);
    if (supplyDetailState.supply) {
      renderSupplyDetail();
      _ozonFbsKizSplitSetTone(_ozonFbsKizToneFromSupply(supplyDetailState.supply));
    }
  }

  function _ozonFbsKizApplyLoadedPayload(
    data,
    { unlockScan = false, focusScan = false, preserveFocus = false, resolveMsg = "" } = {}
  ) {
    const tbody = document.getElementById("ozonFbsKizTbody");
    const saveBtn = document.getElementById("ozonFbsKizSaveBtn");
    const scan = document.getElementById("ozonFbsKizStickerScan");
    const dirty = ozonFbsKizState.localAutosaveDirty instanceof Set
      ? ozonFbsKizState.localAutosaveDirty
      : new Set();
    const prevByPn = ozonFbsKizState.rowsByPosting instanceof Map
      ? ozonFbsKizState.rowsByPosting
      : new Map();
    const active = preserveFocus ? document.activeElement : null;
    const activeId = active && active.id ? String(active.id) : "";
    const activePosting = active?.dataset?.posting
      ? String(active.dataset.posting)
      : "";
    const activeIdx = active?.dataset?.idx != null ? String(active.dataset.idx) : "";
    const activeWasScan = !!(scan && active === scan);
    const activeScanValue = activeWasScan ? String(scan.value || "") : "";

    const incoming = (Array.isArray(data?.rows) ? data.rows : []).map((r) => {
      const pn = String(r?.posting_number || "").trim();
      const prev = pn ? prevByPn.get(pn) : null;
      // Keep in-progress local scans while background resolve continues.
      if (prev && (dirty.has(pn) || ozonFbsKizState.pendingPosting === pn)) {
        return {
          ...r,
          kiz_codes: Array.isArray(prev.kiz_codes) ? prev.kiz_codes.slice() : [""],
          kiz_status: prev.kiz_status,
          kiz_saved_at: prev.kiz_saved_at,
        };
      }
      const raw = Array.isArray(r.kiz_codes) ? r.kiz_codes : [];
      const filled = raw.map((c) => String(c || "").trim()).filter(Boolean);
      return {
        ...r,
        kiz_codes: filled.length ? filled.slice() : [""],
      };
    });

    ozonFbsKizState.rows = incoming;
    _ozonFbsKizMergeOrderFlagsIntoDetail(data?.order_kiz_flags || []);
    if (!Object.keys(ozonFbsKizState.baselineByPosting || {}).length) {
      _ozonFbsKizCaptureBaseline();
    }
    _ozonFbsKizRebuildIndexes();
    renderOzonFbsKizTable();
    if (supplyDetailState.supply) {
      renderSupplyDetail();
      _ozonFbsKizSplitSetTone(_ozonFbsKizToneFromSupply(supplyDetailState.supply));
    }
    if (saveBtn) saveBtn.disabled = false;
    if (unlockScan) {
      _ozonFbsKizSetFiltersReady(true);
      _ozonFbsKizSyncImportBtn();
    }
    if (preserveFocus && _ozonFbsKizModalIsOpen()) {
      setTimeout(() => {
        if (!_ozonFbsKizModalIsOpen()) return;
        if (activeWasScan) {
          const s = document.getElementById("ozonFbsKizStickerScan");
          if (s) {
            if (activeScanValue && !s.value) s.value = activeScanValue;
            s.focus();
          }
          return;
        }
        if (activeId) {
          const byId = document.getElementById(activeId);
          if (byId) {
            byId.focus();
            return;
          }
        }
        if (activePosting) {
          const sel = activeIdx !== ""
            ? `.wb-fbs-kiz-code-input[data-posting="${activePosting}"][data-idx="${activeIdx}"]`
            : `.wb-fbs-kiz-code-input[data-posting="${activePosting}"]`;
          const el = document.querySelector(sel);
          if (el) el.focus();
        }
      }, 0);
    } else if (focusScan && scan && document.activeElement !== scan) {
      setTimeout(() => {
        if (_ozonFbsKizModalIsOpen()) scan.focus();
      }, 40);
    }
    if (resolveMsg) {
      _ozonFbsKizSetInfo(resolveMsg, true);
    } else if (!ozonFbsKizState.rows.length) {
      _ozonFbsKizSetInfo("В поставке нет отправлений, требующих маркировки");
    } else {
      _ozonFbsKizSetInfo("");
    }
    if (tbody && !ozonFbsKizState.rows.length && resolveMsg) {
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">${esc(resolveMsg)}</td></tr>`;
    }
  }

  async function openOzonFbsKizModal() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) return;
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsKizModal", true);
    else document.getElementById("ozonFbsKizModal")?.classList.remove("hidden");
    if (typeof _ozonFbsContainerPrepareModal === "function") {
      void _ozonFbsContainerPrepareModal("kiz");
    }
    ozonFbsKizColResizer.init();
    const loadGen = (ozonFbsKizState.loadGen = Number(ozonFbsKizState.loadGen || 0) + 1);
    ozonFbsKizState.rows = [];
    ozonFbsKizState.errors = {};
    ozonFbsKizState.pendingPosting = null;
    ozonFbsKizState.baselineByPosting = {};
    ozonFbsKizState.forceSaveByPosting = {};
    ozonFbsKizState.localAutosaveDirty = new Set();
    ozonFbsKizState.localAutosaveClearByPosting = {};
    ozonFbsKizState.localAutosaveFlushQueued = false;
    ozonFbsKizState.localAutosaveSeqByPosting = {};
    ozonFbsKizState.rowsByPosting = new Map();
    ozonFbsKizState.markIndex = new Map();
    ozonFbsKizState.stickerIndex = new Map();
    _ozonFbsKizSetFiltersReady(false);
    _ozonFbsKizSetInfo("");
    _ozonFbsKizSyncImportBtn();
    closeOzonFbsKizImportModal();
    const importText = document.getElementById("ozonFbsKizImportText");
    if (importText) importText.value = "";
    _ozonFbsKizImportSetLog([]);
    _ozonFbsKizImportSetInfo("");
    _ozonFbsKizClearImportConflicts();
    const tbody = document.getElementById("ozonFbsKizTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="wb-fbs-empty">Загрузка…</td></tr>`;
    const saveBtn = document.getElementById("ozonFbsKizSaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    const scan = document.getElementById("ozonFbsKizStickerScan");
    if (scan) scan.value = "";
    let loadOk = false;
    let applied = false;
    const stillThisLoad = () =>
      Number(ozonFbsKizState.loadGen) === loadGen && _ozonFbsKizModalIsOpen();
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      _ozonFbsAppendPostingTab(params);
      await _ozonFbsFetchResolvedChunks(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking?${params}`,
        {
          shouldAbort: () => !stillThisLoad(),
          onChunk: (data, meta) => {
            if (!stillThisLoad()) return;
            const resolving = !meta?.done && Number(meta?.remaining || 0) > 0;
            const resolveMsg = resolving ? _ozonFbsResolveProgressText(meta) : "";
            if (!applied) {
              // Keep filters / scan / cargo-checkbox locked until the whole load finishes.
              _ozonFbsKizApplyLoadedPayload(data, {
                unlockScan: false,
                resolveMsg,
              });
              applied = true;
              loadOk = true;
              return;
            }
            // Later chunks can add newly-resolved kiz_required rows. Merge them,
            // keep controls locked, preserve in-progress local edits.
            const prevKeys = new Set(
              (ozonFbsKizState.rows || [])
                .map((r) => String(r?.posting_number || "").trim())
                .filter(Boolean)
            );
            const nextKeys = new Set(
              (Array.isArray(data?.rows) ? data.rows : [])
                .map((r) => String(r?.posting_number || "").trim())
                .filter(Boolean)
            );
            let rowsChanged = prevKeys.size !== nextKeys.size;
            if (!rowsChanged) {
              for (const k of nextKeys) {
                if (!prevKeys.has(k)) {
                  rowsChanged = true;
                  break;
                }
              }
            }
            if (rowsChanged || meta?.done) {
              _ozonFbsKizApplyLoadedPayload(data, {
                unlockScan: false,
                resolveMsg,
              });
              return;
            }
            _ozonFbsKizMergeOrderFlagsIntoDetail(data?.order_kiz_flags || []);
            if (supplyDetailState.supply) {
              renderSupplyDetail();
              _ozonFbsKizSplitSetTone(_ozonFbsKizToneFromSupply(supplyDetailState.supply));
            }
            if (resolveMsg) _ozonFbsKizSetInfo(resolveMsg, true);
            else if (ozonFbsKizState.rows.length) _ozonFbsKizSetInfo("");
          },
        }
      );
      if (!stillThisLoad()) return;
      if (!applied) {
        _ozonFbsKizApplyLoadedPayload({}, { unlockScan: false });
      } else {
        _ozonFbsKizSetInfo(
          ozonFbsKizState.rows.length
            ? ""
            : "В поставке нет отправлений, требующих маркировки"
        );
      }
    } catch (e) {
      if (!stillThisLoad()) return;
      if (tbody && !applied) {
        tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
      }
      _ozonFbsKizSetInfo(String(e.message || e));
    } finally {
      if (!stillThisLoad()) return;
      if (saveBtn) saveBtn.disabled = false;
      _ozonFbsKizSetFiltersReady(true);
      _ozonFbsKizSyncImportBtn();
      if (loadOk && scan) setTimeout(() => {
        if (stillThisLoad()) scan.focus();
      }, 50);
    }
  }

  async function closeOzonFbsKizModal() {
    ozonFbsKizState.loadGen = Number(ozonFbsKizState.loadGen || 0) + 1;
    try {
      await _ozonFbsKizAwaitLocalAutosaves();
    } catch (_e) {
      /* keep closing */
    }
    // Same cleanup as WB marking: drop RU-layout swallow so wedge scan works again.
    _ozonFbsClearRuLayoutGuard();
    if (typeof setModalVisibility === "function") {
      setModalVisibility("ozonFbsKizScanPrompt", false);
      setModalVisibility("ozonFbsKizModal", false);
    } else {
      document.getElementById("ozonFbsKizScanPrompt")?.classList.add("hidden");
      document.getElementById("ozonFbsKizModal")?.classList.add("hidden");
    }
    cancelOzonFbsKizMarkScan();
    closeOzonFbsKizImportModal();
    ozonFbsKizState.rows = [];
    ozonFbsKizState.rowsByPosting = new Map();
    ozonFbsKizState.markIndex = new Map();
    ozonFbsKizState.stickerIndex = new Map();
    ozonFbsKizState.localAutosaveDirty = new Set();
    _ozonFbsKizSetFiltersReady(false);
    _ozonFbsKizSetInfo("");
  }

  async function saveOzonFbsKizModal() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || ozonFbsKizState.saving) return;
    _ozonFbsKizCollectFromDom();
    const saveBtn = document.getElementById("ozonFbsKizSaveBtn");
    ozonFbsKizState.saving = true;
    if (saveBtn) saveBtn.disabled = true;
    _ozonFbsKizSetInfo("Сохранение…");
    try {
      await _ozonFbsKizAwaitLocalAutosaves();
      _ozonFbsKizCollectFromDom();
      const items = [];
      for (const r of ozonFbsKizState.rows || []) {
        if (_ozonFbsRowIsCancelled(r)) continue;
        const pn = String(r.posting_number || "").trim();
        if (!pn) continue;
        const codes = (r.kiz_codes || []).map((c) => _ozonFbsNormalizeMark(c)).filter(Boolean);
        const gtdNow = String(r.gtd_number || "").trim();
        const gtdRequired = !!r.gtd_required;
        const gtdBase = String(ozonFbsKizState.baselineGtdByPosting?.[pn] || "").trim();
        const gtdDirty = gtdNow !== gtdBase;
        const force = !!(ozonFbsKizState.forceSaveByPosting && ozonFbsKizState.forceSaveByPosting[pn]);
        const baseCodes = Array.isArray(ozonFbsKizState.baselineByPosting?.[pn])
          ? ozonFbsKizState.baselineByPosting[pn]
          : null;
        const baseHadCodes = Array.isArray(baseCodes) && baseCodes.length > 0;
        // Empty rows are fine — skip. Only clear when codes existed and were removed.
        const wantClear = !codes.length && baseHadCodes;
        const codesDirty = !_ozonFbsKizBaselineEquals(pn, codes);
        const needsOzonPush = gtdRequired && codes.length > 0 && !!gtdNow && !r.kiz_ozon_synced;
        if (!force && !codesDirty && !gtdDirty && !needsOzonPush && !wantClear) continue;
        if (!codes.length && !wantClear && !gtdDirty && !force) continue;
        if (ozonFbsKizState.errors[pn]) delete ozonFbsKizState.errors[pn];
        items.push({
          posting_number: pn,
          kiz_codes: codes,
          gtd_number: gtdNow,
          expected_saved_at: r.kiz_saved_at || "",
          force,
          clear: wantClear,
        });
      }
      if (!items.length) {
        _ozonFbsKizSetInfo("Готово", true);
        return;
      }
      // Chunk Ozon pushes so nginx 60s default cannot 504 a bulk юрлицо save.
      const CHUNK = 15;
      const allResults = [];
      let savedTotal = 0;
      for (let i = 0; i < items.length; i += CHUNK) {
        const chunk = items.slice(i, i + CHUNK);
        if (items.length > CHUNK) {
          _ozonFbsKizSetInfo(
            `Сохранение… ${Math.min(i + CHUNK, items.length)}/${items.length}`
          );
        }
        const res = await fetch(
          `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking?source_id=${sourceId}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json", ...jsonHeaders() },
            body: JSON.stringify({ items: chunk }),
          }
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
        allResults.push(...(data.results || []));
        savedTotal += Number(data.saved) || 0;
      }
      const errs = allResults.filter((r) => r && !r.ok);
      if (errs.length) {
        errs.forEach((e) => {
          if (e.posting_number) ozonFbsKizState.errors[e.posting_number] = e.error || "ошибка";
        });
        renderOzonFbsKizTable();
        const parts = [];
        if (savedTotal) parts.push(`сохранено ${savedTotal}`);
        parts.push(`ошибок ${errs.length}`);
        _ozonFbsKizSetInfo(`Сохранено частично (${parts.join(", ")}).`);
      } else {
        _ozonFbsKizSetInfo(
          savedTotal ? `Сохранено: ${savedTotal}` : "Готово",
          true
        );
      }
      _ozonFbsKizApplySaveResults(allResults);
    } catch (e) {
      _ozonFbsKizSetInfo(String(e.message || e));
    } finally {
      ozonFbsKizState.saving = false;
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async function refreshOzonFbsMarkingStatus(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady() || ozonFbsKizState.statusRefreshing) {
      return;
    }
    const refreshBtn = document.getElementById("ozonFbsSupplyDetailKizRefreshBtn");
    const refreshGen = Number(ozonFbsKizState.statusRefreshGen || 0) + 1;
    ozonFbsKizState.statusRefreshGen = refreshGen;
    ozonFbsKizState.statusRefreshing = true;
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.classList.add("is-spinning");
    }
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      _ozonFbsAppendPostingTab(params);
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking/status?${params}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      }
      if (supplyDetailState.supplyId !== sid) return;
      if (ozonFbsKizState.statusRefreshGen !== refreshGen) return;
      _ozonFbsKizMergeStatusIntoDetail(data.orders || []);
      if (supplyDetailState.supply) renderSupplyDetail();
      const st = String(data.status || "");
      const split = document.getElementById("ozonFbsKizSplit");
      const refreshBtn = document.getElementById("ozonFbsSupplyDetailKizRefreshBtn");
      if (st === "error") {
        const tip = typeof _ozonFbsContainerErrorsTooltip === "function"
          ? _ozonFbsContainerErrorsTooltip(data.container_errors || [])
          : "Ошибка привязки к грузоместу";
        if (split) {
          split.dataset.containerErrorTip = tip || "Ошибка привязки к грузоместу";
          split.title = tip || "Ошибка привязки к грузоместу";
        }
        if (refreshBtn) refreshBtn.title = tip || "Ошибка привязки к грузоместу";
        _ozonFbsKizSplitSetTone("error");
      } else if (st === "ok") {
        if (split) {
          split.removeAttribute("title");
          delete split.dataset.containerErrorTip;
        }
        if (refreshBtn) refreshBtn.title = "Обновить статусы маркировки";
        _ozonFbsKizSplitSetTone("ok");
      } else {
        if (split) {
          split.removeAttribute("title");
          delete split.dataset.containerErrorTip;
        }
        if (refreshBtn) refreshBtn.title = "Обновить статусы маркировки";
        _ozonFbsKizSplitSetTone("");
      }
    } catch (e) {
      if (
        supplyDetailState.supplyId === sid
        && ozonFbsKizState.statusRefreshGen === refreshGen
      ) {
        const info = document.getElementById("ozonFbsSupplyDetailInfo");
        if (info) {
          info.hidden = false;
          info.textContent = String(e.message || e);
        }
      }
    } finally {
      if (ozonFbsKizState.statusRefreshGen === refreshGen) {
        ozonFbsKizState.statusRefreshing = false;
        if (refreshBtn) {
          refreshBtn.disabled = false;
          refreshBtn.classList.remove("is-spinning");
        }
      }
    }
  }

  function _ozonFbsPickBarcodeKeys(value) {
    const raw = _ozonFbsNormalizeScan(value);
    const digits = raw.replace(/\D/g, "");
    const set = new Set();
    if (raw) set.add(raw);
    if (digits) {
      set.add(digits);
      if (digits.length === 14 && digits.startsWith("0")) set.add(digits.slice(1));
      if (digits.length === 13) set.add(`0${digits}`);
    }
    return set;
  }

  function _ozonFbsPickOrderSkuSet(row) {
    const set = new Set();
    for (const b of row?.barcodes || []) {
      for (const k of _ozonFbsPickBarcodeKeys(b)) set.add(k);
    }
    return set;
  }

  function _ozonFbsPickValidateEanForOrder(scan, row) {
    const raw = _ozonFbsNormalizeScan(scan);
    const digits = raw.replace(/\D/g, "");
    if (!digits) return { ok: false, error: "Отсканируйте штрихкод товара (EAN-13)" };
    if (![8, 12, 13, 14].includes(digits.length)) {
      return { ok: false, error: `Ожидается EAN/GTIN (8–14 цифр), получено ${digits.length}` };
    }
    const orderSkus = _ozonFbsPickOrderSkuSet(row);
    if (!orderSkus.size) {
      return { ok: false, error: "У отправления нет штрихкодов товара — нельзя сверить ШК" };
    }
    const candidates = _ozonFbsPickBarcodeKeys(scan);
    let matched = false;
    for (const c of candidates) {
      if (orderSkus.has(c)) {
        matched = true;
        break;
      }
    }
    if (!matched) {
      return { ok: false, error: "ШК не совпадает ни с одним ШК товара в отправлении" };
    }
    const normalized = digits.length === 14 && digits.startsWith("0") ? digits.slice(1) : digits;
    return { ok: true, barcode: normalized };
  }

  function _ozonFbsPickFindBySticker(scan) {
    return _ozonFbsFindByStickerInRows(scan, ozonFbsPickState.rows);
  }

  async function _ozonFbsPickFindByStickerWithLookup(scan) {
    const local = _ozonFbsPickFindBySticker(scan);
    if (local.row || local.ambiguous) return local;
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    const raw = _ozonFbsNormalizeScan(scan);
    if (!sourceId || !raw) return local;
    try {
      const params = new URLSearchParams({ source_id: String(sourceId), scan: raw });
      const res = await fetch(`/api/ozon-fbs/postings/lookup?${params}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.found || !data.posting) return local;
      const pn = String(data.posting.posting_number || "").trim();
      if (!pn) return local;
      const row = (ozonFbsPickState.rows || []).find((r) => String(r.posting_number || "").trim() === pn);
      if (!row) return local;
      row.sticker_barcode = String(data.posting.sticker_barcode || row.sticker_barcode || "").trim();
      row.sticker_lower_barcode = String(
        data.posting.sticker_lower_barcode || row.sticker_lower_barcode || ""
      ).trim();
      row.sticker_part_a = String(data.posting.sticker_part_a || row.sticker_part_a || "").trim();
      row.sticker_part_b = String(data.posting.sticker_part_b || row.sticker_part_b || "").trim();
      return { row, ambiguous: false };
    } catch (_) {
      return local;
    }
  }

  function _ozonFbsPickFindByPosting(scan) {
    return _ozonFbsPickFindBySticker(scan);
  }

  function _ozonFbsPickUpdateScanCounter() {
    const el = document.getElementById("ozonFbsPickScanCount");
    if (!el) return;
    let filled = 0;
    const active = _ozonFbsActiveModalRows(ozonFbsPickState.rows);
    const total = active.length;
    for (const row of active) {
      if (row.pick_verified && String(row.pick_barcode || "").trim()) filled += 1;
    }
    el.textContent = `Проверено ${filled} из ${total}`;
  }

  function _ozonFbsPickStatusHtml(row) {
    const pn = String(row.posting_number || "");
    if (_ozonFbsRowIsCancelled(row)) {
      const label = String(row.cancel_reason_label || "Отменено").trim();
      return `<div class="wb-fbs-pick-status is-muted">${esc(label)}</div>`;
    }
    const err = String(ozonFbsPickState.errors[pn] || "").trim();
    const verified = !!row.pick_verified && !!String(row.pick_barcode || "").trim();
    let body = "";
    if (err) {
      body = `<div class="wb-fbs-pick-status is-error">${esc(err)}</div>`;
    } else if (verified) {
      body = `<div class="wb-fbs-pick-status is-ok">✓ ${esc(row.pick_barcode)}</div>`;
    } else {
      body = `<div class="wb-fbs-pick-status is-empty">Не проверено</div>`;
    }
    const clearBtn = verified || err
      ? `<button type="button" class="wb-fbs-kiz-remove" title="Сбросить"
                 onclick="clearOzonFbsPickVerify('${esc(pn)}')">×</button>`
      : "";
    return `<div class="wb-fbs-pick-status-row">${body}${clearBtn}</div>`;
  }

  function onOzonFbsPickFilterFilledChange() {
    const filled = document.getElementById("ozonFbsPickFilterFilled");
    const empty = document.getElementById("ozonFbsPickFilterEmpty");
    if (filled?.checked && empty) empty.checked = false;
    renderOzonFbsPickVerifyTable();
  }

  function onOzonFbsPickFilterEmptyChange() {
    const filled = document.getElementById("ozonFbsPickFilterFilled");
    const empty = document.getElementById("ozonFbsPickFilterEmpty");
    if (empty?.checked && filled) filled.checked = false;
    renderOzonFbsPickVerifyTable();
  }

  function renderOzonFbsPickVerifyTable() {
    const tbody = document.getElementById("ozonFbsPickTbody");
    if (!tbody) return;
    const q = String(document.getElementById("ozonFbsPickSearchFilter")?.value || "")
      .trim()
      .toLowerCase();
    const showFilled = !!document.getElementById("ozonFbsPickFilterFilled")?.checked;
    const showEmpty = !!document.getElementById("ozonFbsPickFilterEmpty")?.checked;
    const showErrors = !!document.getElementById("ozonFbsPickFilterErrors")?.checked;
    const pending = String(ozonFbsPickState.pendingPosting || "").trim();
    const rows = (ozonFbsPickState.rows || []).filter((r) => {
      const verified = !!r.pick_verified && !!String(r.pick_barcode || "").trim();
      const pn = String(r.posting_number || "");
      const hasErr = !!String(ozonFbsPickState.errors[pn] || "").trim();
      if (showFilled && !verified) return false;
      if (showEmpty && verified) return false;
      if (showErrors && !hasErr) return false;
      if (!q) return true;
      const hay = [
        r.posting_number, r.offer_id, r.product_name, r.sku, r.pick_barcode,
        r.container_barcode, r.container_id,
        ...(Array.isArray(r.barcodes) ? r.barcodes : []),
      ].map((x) => String(x || "").toLowerCase()).join(" ");
      return hay.includes(q);
    });
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">${
        ozonFbsPickState.rows?.length ? "Нет строк по фильтру" : "Нет отправлений без маркировки"
      }</td></tr>`;
      _ozonFbsPickUpdateScanCounter();
      if (typeof _ozonFbsContainerUpdateCounters === "function") _ozonFbsContainerUpdateCounters();
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const pn = String(r.posting_number || "");
      const safePn = esc(pn);
      const photo = r.product_photo
        ? `<img class="wb-fbs-product-photo" src="${esc(r.product_photo)}" alt="" width="56" height="56" loading="lazy">`
        : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
      const barcodes = Array.isArray(r.barcodes) ? r.barcodes : [];
      const barcodeHtml = barcodes.length
        ? `<div class="wb-fbs-kiz-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
            `<div class="wb-fbs-kiz-barcode">${esc(b)}</div>`
          ).join("")}</div>`
        : "";
      return `<tr class="wb-fbs-kiz-row${pending === pn ? " is-active" : ""}${_ozonFbsRowIsCancelled(r) ? " is-cancelled" : ""}" data-posting="${safePn}">
        <td>
          ${_ozonFbsModalPostingColHtml(r)}
        </td>
        <td>
          <div class="wb-fbs-product">
            ${photo}
            <div class="wb-fbs-product-text">
              <div class="wb-fbs-product-name" title="${esc(r.product_name || r.offer_id || "")}">${esc(r.product_name || r.offer_id || "—")}</div>
              <div class="wb-fbs-product-sub">Арт. ${esc(r.offer_id || "—")}</div>
              ${barcodeHtml}
              ${cancelBadgeHtml(r)}
            </div>
          </div>
        </td>
        <td class="wb-fbs-kiz-col-kiz">${_ozonFbsPickStatusHtml(r)}</td>
        <td class="wb-fbs-kiz-col-container">${
          typeof _ozonFbsContainerCellHtml === "function"
            ? _ozonFbsContainerCellHtml(r, "pick")
            : "—"
        }</td>
      </tr>`;
    }).join("");
    _ozonFbsPickUpdateScanCounter();
    if (typeof _ozonFbsContainerUpdateCounters === "function") _ozonFbsContainerUpdateCounters();
  }

  function clearOzonFbsPickVerify(postingNumber) {
    const pn = String(postingNumber || "");
    const row = ozonFbsPickState.rows.find((r) => String(r.posting_number) === pn);
    if (!row || _ozonFbsRowIsCancelled(row)) return;
    row.pick_verified = false;
    row.pick_barcode = "";
    delete ozonFbsPickState.errors[pn];
    renderOzonFbsPickVerifyTable();
    _ozonFbsPickScheduleLocalAutosave(pn, true);
  }

  function _ozonFbsPickScheduleLocalAutosave(postingNumber, clear) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return;
    if (!ozonFbsPickState.localAutosaveSeqByPosting) ozonFbsPickState.localAutosaveSeqByPosting = {};
    const seq = (Number(ozonFbsPickState.localAutosaveSeqByPosting[pn]) || 0) + 1;
    ozonFbsPickState.localAutosaveSeqByPosting[pn] = seq;
    const run = () => _ozonFbsPickFlushLocalAutosave(pn, seq, !!clear);
    ozonFbsPickState.localAutosaveChain = (ozonFbsPickState.localAutosaveChain || Promise.resolve())
      .then(run, run)
      .catch(() => {});
  }

  async function _ozonFbsPickFlushLocalAutosave(postingNumber, seq, clear) {
    const pn = String(postingNumber || "").trim();
    if ((Number(ozonFbsPickState.localAutosaveSeqByPosting?.[pn]) || 0) !== seq) return;
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId) return;
    const row = ozonFbsPickState.rows.find((r) => String(r.posting_number) === pn);
    if (!row || _ozonFbsRowIsCancelled(row)) return;
    const verified = !!row.pick_verified && !!String(row.pick_barcode || "").trim();
    let item;
    if (verified) {
      item = {
        posting_number: pn,
        pick_verified: true,
        pick_barcode: row.pick_barcode,
        expected_verified_at: row.pick_verified_at || "",
        force: !!(ozonFbsPickState.forceSaveByPosting && ozonFbsPickState.forceSaveByPosting[pn]),
      };
    } else {
      item = {
        posting_number: pn,
        pick_verified: false,
        pick_barcode: "",
        clear: !!clear,
        expected_verified_at: row.pick_verified_at || "",
        force: !!(ozonFbsPickState.forceSaveByPosting && ozonFbsPickState.forceSaveByPosting[pn]),
      };
    }
    ozonFbsPickState.localAutosaveInflight = (Number(ozonFbsPickState.localAutosaveInflight) || 0) + 1;
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/pick-verify?source_id=${sourceId}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({ items: [item] }),
          keepalive: true,
        }
      );
      if ((Number(ozonFbsPickState.localAutosaveSeqByPosting?.[pn]) || 0) !== seq) return;
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      const result = (data.results || []).find((r) => String(r.posting_number) === pn);
      if (!result?.ok) {
        if (result?.conflict) {
          row.pick_verified_at = String(result.pick_verified_at || row.pick_verified_at || "");
          if (!ozonFbsPickState.forceSaveByPosting) ozonFbsPickState.forceSaveByPosting = {};
          ozonFbsPickState.forceSaveByPosting[pn] = true;
        }
        return;
      }
      row.pick_verified = !!result.pick_verified;
      row.pick_barcode = String(result.pick_barcode || "").trim();
      if (result.pick_verified_at) row.pick_verified_at = String(result.pick_verified_at);
      delete ozonFbsPickState.errors[pn];
    } finally {
      ozonFbsPickState.localAutosaveInflight = Math.max(
        0,
        (Number(ozonFbsPickState.localAutosaveInflight) || 1) - 1
      );
    }
  }

  async function onOzonFbsPickStickerScanKey(event) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) return;
    const input = event.target;
    if (input?.disabled || input?.readOnly || !ozonFbsPickState.rowsReady) return;
    const rawTyped = String(input?.value || "").replace(/\s+/g, "").trim();
    if (!rawTyped) return;
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(rawTyped)) {
      if (typeof _wbFbsKizBlockRuLayout === "function") _wbFbsKizBlockRuLayout(input);
      return;
    }
    if (typeof _ozonFbsContainerIsScanMode === "function" && _ozonFbsContainerIsScanMode("pick")) {
      await _ozonFbsContainerHandleScan("pick", rawTyped);
      return;
    }
    const scan = _ozonFbsNormalizeScan(rawTyped);
    if (!scan) return;
    const found = await _ozonFbsPickFindByStickerWithLookup(scan);
    if (found.ambiguous) {
      const ids = (found.matches || []).map((r) => r.posting_number).slice(0, 5).join(", ");
      _ozonFbsPickSetInfo(
        `Код стикера совпадает у нескольких отправлений (${ids}${
          (found.matches || []).length > 5 ? "…" : ""
        }). Отсканируйте QR ещё раз.`
      );
      if (input) input.select();
      return;
    }
    if (!found.row) {
      _ozonFbsPickSetInfo(
        `Отправление «${scan}» не найдено среди товаров без маркировки. Возможно, это товар с КИЗ.`
      );
      if (input) input.select();
      return;
    }
    ozonFbsPickState.pendingPosting = String(found.row.posting_number || "");
    _ozonFbsPersistStickerForRow(found.row, scan);
    if (typeof _ozonFbsContainerMaybeBind === "function") {
      const okBind = await _ozonFbsContainerMaybeBind("pick", ozonFbsPickState.pendingPosting);
      if (!okBind) {
        ozonFbsPickState.pendingPosting = null;
        if (input) input.select();
        return;
      }
    }
    _ozonFbsPickSetInfo("");
    if (input) input.value = "";
    const meta = document.getElementById("ozonFbsPickScanPromptMeta");
    if (meta) meta.textContent = `Отправление ${ozonFbsPickState.pendingPosting}`;
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsPickScanPrompt", true);
    else document.getElementById("ozonFbsPickScanPrompt")?.classList.remove("hidden");
    const sku = document.getElementById("ozonFbsPickSkuScan");
    if (sku) {
      sku.value = "";
      setTimeout(() => sku.focus(), 40);
    }
  }

  function cancelOzonFbsPickSkuScan() {
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsPickScanPrompt", false);
    else document.getElementById("ozonFbsPickScanPrompt")?.classList.add("hidden");
    ozonFbsPickState.pendingPosting = null;
    const sticker = document.getElementById("ozonFbsPickStickerScan");
    if (sticker) setTimeout(() => sticker.focus(), 40);
  }

  function onOzonFbsPickSkuScanKey(event) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) return;
    const pn = String(ozonFbsPickState.pendingPosting || "");
    const input = event.target;
    const rawTyped = String(input?.value || "");
    if (!pn || !String(rawTyped || "").replace(/\s+/g, "")) return;
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(rawTyped)) {
      if (typeof _wbFbsKizBlockRuLayout === "function") _wbFbsKizBlockRuLayout(input);
      return;
    }
    const raw = _ozonFbsNormalizeScan(rawTyped);
    if (!raw) return;
    const row = ozonFbsPickState.rows.find((r) => String(r.posting_number) === pn);
    if (!row) {
      cancelOzonFbsPickSkuScan();
      return;
    }
    const check = _ozonFbsPickValidateEanForOrder(raw, row);
    if (!check.ok) {
      ozonFbsPickState.errors[pn] = check.error || "Ошибка проверки ШК";
      cancelOzonFbsPickSkuScan();
      renderOzonFbsPickVerifyTable();
      _ozonFbsPickSetInfo(check.error || "Ошибка проверки ШК");
      if (input) input.select();
      return;
    }
    row.pick_verified = true;
    row.pick_barcode = check.barcode;
    delete ozonFbsPickState.errors[pn];
    const emptyFilter = document.getElementById("ozonFbsPickFilterEmpty");
    if (emptyFilter) emptyFilter.checked = false;
    cancelOzonFbsPickSkuScan();
    renderOzonFbsPickVerifyTable();
    _ozonFbsPickScheduleLocalAutosave(pn, false);
    _ozonFbsPickSetInfo(`ШК проверен локально для ${pn}`, true);
    const rowEl = document.querySelector(`#ozonFbsPickTbody tr[data-posting="${pn}"]`);
    if (rowEl) rowEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function refreshOzonFbsPickVerifyStatus(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady() || ozonFbsPickState.statusRefreshing) {
      return;
    }
    const refreshBtn = document.getElementById("ozonFbsSupplyDetailPickRefreshBtn");
    const refreshGen = (Number(ozonFbsPickState.statusRefreshGen) || 0) + 1;
    ozonFbsPickState.statusRefreshGen = refreshGen;
    ozonFbsPickState.statusRefreshing = true;
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.classList.add("is-spinning");
    }
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      _ozonFbsAppendPostingTab(params);
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/pick-verify/status?${params}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      }
      if (supplyDetailState.supplyId !== sid) return;
      if (ozonFbsPickState.statusRefreshGen !== refreshGen) return;
      const st = String(data.status || "");
      if (st === "error") {
        const tip = typeof _ozonFbsContainerErrorsTooltip === "function"
          ? _ozonFbsContainerErrorsTooltip(data.container_errors || [])
          : "Ошибка привязки к грузоместу";
        const split = document.getElementById("ozonFbsPickSplit");
        if (split) split.dataset.containerErrorTip = tip || "Ошибка привязки к грузоместу";
        _ozonFbsPickSplitSetTone("error");
      } else if (st === "ok") {
        _ozonFbsPickSplitSetTone("ok");
      } else {
        _ozonFbsPickSplitSetTone("");
      }
    } catch (e) {
      if (
        supplyDetailState.supplyId === sid
        && ozonFbsPickState.statusRefreshGen === refreshGen
      ) {
        const info = document.getElementById("ozonFbsSupplyDetailInfo");
        if (info) {
          info.hidden = false;
          info.textContent = String(e.message || e);
        }
      }
    } finally {
      if (ozonFbsPickState.statusRefreshGen === refreshGen) {
        ozonFbsPickState.statusRefreshing = false;
        if (refreshBtn) {
          refreshBtn.disabled = false;
          refreshBtn.classList.remove("is-spinning");
        }
      }
    }
  }

  async function openOzonFbsPickVerifyModal() {
    if (typeof isTenantOwner === "function" && !isTenantOwner()) {
      alert("Проверка ШК доступна только главному пользователю");
      return;
    }
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) return;
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsPickVerifyModal", true);
    else document.getElementById("ozonFbsPickVerifyModal")?.classList.remove("hidden");
    if (typeof _ozonFbsContainerPrepareModal === "function") {
      void _ozonFbsContainerPrepareModal("pick");
    }
    ozonFbsPickColResizer.init();
    ozonFbsPickState.rows = [];
    ozonFbsPickState.errors = {};
    ozonFbsPickState.pendingPosting = null;
    _ozonFbsPickSetFiltersReady(false);
    _ozonFbsPickSetInfo("");
    const tbody = document.getElementById("ozonFbsPickTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Загрузка…</td></tr>`;
    const saveBtn = document.getElementById("ozonFbsPickVerifySaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    const scan = document.getElementById("ozonFbsPickStickerScan");
    if (scan) scan.value = "";
    let loadOk = false;
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      _ozonFbsAppendPostingTab(params);
      const data = await _ozonFbsFetchResolvedChunks(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/pick-verify?${params}`,
        {
          onProgress: (p) => {
            const msg = _ozonFbsResolveProgressText(p);
            if (tbody) {
              tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">${esc(msg)}</td></tr>`;
            }
            _ozonFbsPickSetInfo(msg, true);
          },
        }
      );
      ozonFbsPickState.rows = Array.isArray(data.rows) ? data.rows.map((r) => ({ ...r })) : [];
      _ozonFbsKizMergeOrderFlagsIntoDetail(data.order_kiz_flags || []);
      renderOzonFbsPickVerifyTable();
      if (supplyDetailState.supply) {
        renderSupplyDetail();
        _ozonFbsKizSplitSetTone(_ozonFbsKizToneFromSupply(supplyDetailState.supply));
      }
      if (!ozonFbsPickState.rows.length) {
        _ozonFbsPickSetInfo("В поставке нет отправлений без маркировки", true);
      } else {
        _ozonFbsPickSetInfo("");
      }
      loadOk = true;
    } catch (e) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="3" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
      }
      _ozonFbsPickSetInfo(String(e.message || e));
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      _ozonFbsPickSetFiltersReady(true);
      if (loadOk && scan) setTimeout(() => scan.focus(), 50);
    }
  }

  function closeOzonFbsPickVerifyModal() {
    _ozonFbsClearRuLayoutGuard();
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsPickVerifyModal", false);
    else document.getElementById("ozonFbsPickVerifyModal")?.classList.add("hidden");
    cancelOzonFbsPickSkuScan();
    ozonFbsPickState.rows = [];
    _ozonFbsPickSetInfo("");
  }

  async function saveOzonFbsPickVerifyModal() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || ozonFbsPickState.saving) return;
    const saveBtn = document.getElementById("ozonFbsPickVerifySaveBtn");
    ozonFbsPickState.saving = true;
    if (saveBtn) saveBtn.disabled = true;
    _ozonFbsPickSetInfo("Сохранение…");
    try {
      await ozonFbsPickState.localAutosaveChain;
      const items = (ozonFbsPickState.rows || [])
        .filter((r) => !_ozonFbsRowIsCancelled(r))
        .map((r) => {
        const pn = String(r.posting_number || "");
        const verified = !!r.pick_verified && !!String(r.pick_barcode || "").trim();
        return {
          posting_number: pn,
          pick_verified: verified,
          pick_barcode: verified ? r.pick_barcode : "",
          expected_verified_at: r.pick_verified_at || "",
          force: !!(ozonFbsPickState.forceSaveByPosting && ozonFbsPickState.forceSaveByPosting[pn]),
        };
      }).filter((it) => it.posting_number);
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/pick-verify?source_id=${sourceId}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({ items }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      const errs = (data.results || []).filter((r) => r && !r.ok);
      if (errs.length) {
        errs.forEach((e) => {
          if (e.posting_number) ozonFbsPickState.errors[e.posting_number] = e.error || "ошибка";
        });
        renderOzonFbsPickVerifyTable();
        _ozonFbsPickSetInfo(`Сохранено частично (${data.saved || 0}).`);
      } else {
        _ozonFbsPickSetInfo(`Сохранено локально: ${data.saved || 0} отправлений`, true);
      }
    } catch (e) {
      _ozonFbsPickSetInfo(String(e.message || e));
    } finally {
      ozonFbsPickState.saving = false;
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  window.initOzonFbsSection = initSection;
  window.setOzonFbsTab = setTab;
  window.onOzonFbsSourceChange = onSourceChange;
  window.onOzonFbsSearchInput = onSearchInput;
  window.ozonFbsChangePage = changePage;
  window.changeOzonFbsPageSize = changePageSize;
  window.syncOzonFbs = syncOzonFbs;
  window.stopOzonFbsSync = stopOzonFbsSync;
  window.openOzonFbsSyncSettings = openOzonFbsSyncSettings;
  window.closeOzonFbsSyncSettings = closeOzonFbsSyncSettings;
  window.saveOzonFbsSyncSettings = saveOzonFbsSyncSettings;
  window.closeOzonFbsSyncInfo = closeSyncInfo;
  window.openOzonFbsDetail = openDetail;
  window.closeOzonFbsDetailModal = closeDetailModal;
  window.ozonFbsShipCurrent = shipCurrent;
  window.ozonFbsShipAll = shipAll;
  window.ozonFbsSplitMulti = splitMulti;
  window.ozonFbsCloseSplitResultModal = closeSplitResultModal;
  window.ozonFbsPrintCurrentSticker = printCurrentSticker;
  window.onOzonFbsCheckboxChange = onCheckboxChange;
  window.toggleSelectAllOzonFbs = toggleSelectAll;
  window.clearOzonFbsSelection = clearSelection;
  window.openOzonFbsNewSupplyFromSelection = openNewSupplyFromSelection;
  window.openOzonFbsAddToExistingSupply = openAddToExistingSupply;
  window.confirmOzonFbsSelectionSupply = confirmSelectionSupply;
  window.closeOzonFbsSelectionSupplyModal = closeSelectionSupplyModal;
  window.ozonFbsSelectionSupplyNameInput = selectionSupplyNameInput;

  async function loadOzonFbsPostingScansJournal() {
    const tbody = document.getElementById("ozonFbsStickerLookupJournalTbody");
    const sourceId = state.sourceId;
    if (!tbody || !sourceId) return;
    try {
      const res = await fetch(
        `/api/ozon-fbs/postings/scans?source_id=${encodeURIComponent(sourceId)}&limit=80`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      const items = Array.isArray(data.items) ? data.items : [];
      if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Журнал пуст</td></tr>`;
        return;
      }
      const typeLabel = (t) => {
        const k = String(t || "").trim();
        if (k === "assembly_sticker") return "Стикер";
        if (k === "kiz") return "КИЗ";
        if (k === "pick_barcode") return "ШК";
        if (k === "lookup") return "Поиск";
        return k || "—";
      };
      tbody.innerHTML = items.map((it) => {
        const at = String(it.scanned_at || "").replace("T", " ").slice(0, 19);
        const pn = String(it.posting_number || "—");
        const raw = String(it.scan_raw || it.sticker_barcode || it.kiz_code || it.pick_barcode || "—");
        return `<tr>
          <td class="small">${esc(at)}</td>
          <td>${esc(typeLabel(it.scan_type))}</td>
          <td>${formatOzonPostingNumberHtml(pn)}</td>
          <td class="small">${esc(raw.length > 48 ? `${raw.slice(0, 48)}…` : raw)}</td>
        </tr>`;
      }).join("");
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
    }
  }

  function _ozonFbsStickerLookupSetInfo(text, ok) {
    const el = document.getElementById("ozonFbsStickerLookupInfo");
    if (!el) return;
    el.textContent = String(text || "");
    el.classList.remove("is-ok", "is-error");
    if (text && ok) el.classList.add("is-ok");
    if (text && !ok) el.classList.add("is-error");
  }

  function _ozonFbsRenderStickerLookupResult(posting) {
    const box = document.getElementById("ozonFbsStickerLookupResult");
    if (!box) return;
    if (!posting) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    const pn = String(posting.posting_number || "");
    const kiz = Array.isArray(posting.kiz_codes) ? posting.kiz_codes.filter(Boolean) : [];
    const pickOk = posting.pick_verified && posting.pick_barcode;
    box.hidden = false;
    box.innerHTML = `
      <div class="wb-fbs-product" style="margin-bottom:12px">
        <div class="wb-fbs-product-text">
          <div class="wb-fbs-kiz-order-id">${formatOzonPostingNumberHtml(pn)}</div>
          <div class="wb-fbs-product-name">${esc(posting.product_name || posting.offer_id || "—")}</div>
          <div class="wb-fbs-product-sub">Арт. ${esc(posting.offer_id || "—")} · заказ ${esc(posting.order_number || posting.order_id || "—")}</div>
        </div>
      </div>
      <div class="small"><strong>Стикер:</strong> ${esc(posting.sticker_barcode || "—")}</div>
      <div class="small"><strong>КИЗ:</strong> ${kiz.length ? esc(kiz.join(", ")) : "не сохранён"}</div>
      <div class="small"><strong>ШК:</strong> ${pickOk ? esc(posting.pick_barcode) : "не проверен"}</div>
      ${posting.supply_id ? `<div class="small"><strong>Поставка:</strong> ${esc(posting.supply_id)}</div>` : ""}
    `;
  }

  async function runOzonFbsStickerLookup(scanRaw) {
    const sourceId = state.sourceId;
    const raw = _ozonFbsNormalizeScan(scanRaw);
    if (!sourceId || !raw) return;
    _ozonFbsStickerLookupSetInfo("Поиск…");
    _ozonFbsRenderStickerLookupResult(null);
    try {
      const params = new URLSearchParams({ source_id: String(sourceId), scan: raw });
      const res = await fetch(`/api/ozon-fbs/postings/lookup?${params}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      if (data.ambiguous) {
        const cnt = Array.isArray(data.matches) ? data.matches.length : 0;
        _ozonFbsStickerLookupSetInfo(
          `Найдено несколько отправлений (${cnt}). Уточните скан.`,
          false
        );
        return;
      }
      if (!data.found || !data.posting) {
        _ozonFbsStickerLookupSetInfo(`Отправление не найдено: «${raw}»`, false);
        await loadOzonFbsPostingScansJournal();
        return;
      }
      _ozonFbsRenderStickerLookupResult(data.posting);
      _ozonFbsStickerLookupSetInfo("Найдено", true);
      await loadOzonFbsPostingScansJournal();
    } catch (e) {
      _ozonFbsStickerLookupSetInfo(String(e.message || e), false);
    }
  }

  function onOzonFbsStickerLookupScanKey(event) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    const raw = String(event.target?.value || "").trim();
    if (!raw) return;
    runOzonFbsStickerLookup(raw);
    if (event.target) event.target.select();
  }

  function openOzonFbsStickerLookupModal() {
    if (!state.sourceId) {
      alert("Выберите источник Ozon FBS");
      return;
    }
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsStickerLookupModal", true);
    else document.getElementById("ozonFbsStickerLookupModal")?.classList.remove("hidden");
    _ozonFbsStickerLookupSetInfo("");
    _ozonFbsRenderStickerLookupResult(null);
    loadOzonFbsPostingScansJournal();
    const scan = document.getElementById("ozonFbsStickerLookupScan");
    if (scan) {
      scan.value = "";
      setTimeout(() => scan.focus(), 40);
    }
  }

  function closeOzonFbsStickerLookupModal() {
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsStickerLookupModal", false);
    else document.getElementById("ozonFbsStickerLookupModal")?.classList.add("hidden");
  }

  window.openOzonFbsStickerLookupModal = openOzonFbsStickerLookupModal;
  window.closeOzonFbsStickerLookupModal = closeOzonFbsStickerLookupModal;
  window.onOzonFbsStickerLookupScanKey = onOzonFbsStickerLookupScanKey;

  window.closeOzonFbsCollectModal = closeCollectModal;
  window.closeOzonFbsCollectResultModal = closeCollectResultModal;
  window.openOzonFbsPackagingExemplarModal = openOzonFbsPackagingExemplarModal;
  window.closeOzonFbsPackagingExemplarModal = closeOzonFbsPackagingExemplarModal;
  window.saveOzonFbsPackagingExemplar = saveOzonFbsPackagingExemplar;
  window.onOzonFbsPackagingExemplarKizInput = onOzonFbsPackagingExemplarKizInput;
  window.onOzonFbsPackagingExemplarManualGtd = onOzonFbsPackagingExemplarManualGtd;
  window.confirmOzonFbsCollect = confirmCollect;
  window.ozonFbsCollectNameInput = collectNameInput;

  window.openOzonFbsRenameSupplyModal = openOzonFbsRenameSupplyModal;
  window.closeOzonFbsRenameSupplyModal = closeOzonFbsRenameSupplyModal;
  window.submitOzonFbsRenameSupply = submitOzonFbsRenameSupply;
  window.ozonFbsSupplyDetailId = () => String(supplyDetailState.supplyId || "");
  window.openOzonFbsSupplyDetailModal = openSupplyDetailModal;
  window.closeOzonFbsSupplyDetailModal = closeSupplyDetailModal;
  window.renderOzonFbsSupplyDetail = () => renderSupplyDetail();
  window.onOzonFbsSupplyDetailCheckboxChange = onSupplyDetailCheckboxChange;
  window.toggleSelectAllOzonFbsSupplyDetail = toggleSelectAllSupplyDetail;
  window.ozonFbsOpenPickingList = openPickingList;
  window.toggleOzonFbsPickingMenu = togglePickingMenu;
  window.ozonFbsOpenStickersPrint = () => openStickersPrint();
  window.toggleOzonFbsStickersMenu = toggleStickersMenu;
  window.openOzonFbsStickersByCategoryModal = openStickersByCategoryModal;
  window.closeOzonFbsStickersByCategoryModal = closeStickersByCategoryModal;
  window.ozonFbsPrintStickersByCategory = ozonFbsPrintStickersByCategory;
  window.onOzonFbsStickersCategoryToggleAt = onOzonFbsStickersCategoryToggleAt;
  window.ozonFbsStickersCategorySelectAll = ozonFbsStickersCategorySelectAll;
  window.ozonFbsStickersCategoryClearAll = ozonFbsStickersCategoryClearAll;
  window.ozonFbsStickersCategoryFillDownAt = ozonFbsStickersCategoryFillDownAt;
  window.openOzonFbsShipmentsModal = openShipmentsModal;
  window.closeOzonFbsShipmentsModal = closeShipmentsModal;
  window.reloadOzonFbsShipments = loadShipments;
  window.ozonFbsShipmentsForm = formShipmentsCarriage;
  window.ozonFbsShipmentsSelectCarriage = selectShipmentsCarriage;
  window.ozonFbsShipmentsPrintBarcode = shipmentsPrintBarcode;
  window.ozonFbsShipmentsDownloadBarcode = shipmentsDownloadBarcode;
  window.openOzonFbsContainersModal = openOzonFbsContainersModal;
  window.closeOzonFbsContainersModal = closeOzonFbsContainersModal;
  window.refreshOzonFbsContainers = refreshOzonFbsContainers;
  window.createOzonFbsContainers = createOzonFbsContainers;
  window.deleteOzonFbsContainer = deleteOzonFbsContainer;
  window.approveOzonFbsContainer = approveOzonFbsContainer;
  window.printOzonFbsContainerLabel = printOzonFbsContainerLabel;
  window.ozonFbsContainersStep = ozonFbsContainersStep;
  window.moveOzonFbsSupplyToDelivering = moveOzonFbsSupplyToDelivering;
  window.closeOzonFbsMoveDeliveringModal = closeOzonFbsMoveDeliveringModal;
  window.confirmOzonFbsMoveDelivering = confirmOzonFbsMoveDelivering;
  window.openOzonFbsMoveSelectedToAwaitingDeliver = openOzonFbsMoveSelectedToAwaitingDeliver;
  window.closeOzonFbsMoveAwaitingModal = closeOzonFbsMoveAwaitingModal;
  window.confirmOzonFbsMoveAwaiting = confirmOzonFbsMoveAwaiting;
  window.toggleOzonFbsRowMenu = toggleOzonFbsRowMenu;
  window.closeOzonFbsRowMenus = closeOzonFbsRowMenus;
  window.ozonFbsPrintOnePostingStickerFromDetail = printOnePostingStickerFromDetail;
  window.openOzonFbsMovePostingModal = openOzonFbsMovePostingModal;
  window.closeOzonFbsMovePostingModal = closeOzonFbsMovePostingModal;
  window.selectOzonFbsMovePostingTarget = selectOzonFbsMovePostingTarget;
  window.confirmOzonFbsMovePosting = confirmOzonFbsMovePosting;
  window.openOzonFbsCancelledOrdersModal = openOzonFbsCancelledOrdersModal;
  window.closeOzonFbsCancelledOrdersModal = closeOzonFbsCancelledOrdersModal;
  window.refreshOzonFbsCancelledOrders = refreshOzonFbsCancelledOrders;
  window.ozonFbsKizState = ozonFbsKizState;
  window.ozonFbsPickState = ozonFbsPickState;
  window.supplyDetailState = supplyDetailState;
  window._ozonFbsKizSetInfo = _ozonFbsKizSetInfo;
  window._ozonFbsPickSetInfo = _ozonFbsPickSetInfo;
  window.openOzonFbsKizModal = openOzonFbsKizModal;
  window.closeOzonFbsKizModal = closeOzonFbsKizModal;
  window.saveOzonFbsKizModal = saveOzonFbsKizModal;
  window.renderOzonFbsKizTable = renderOzonFbsKizTable;
  window.onOzonFbsKizCodeInput = onOzonFbsKizCodeInput;
  window.onOzonFbsKizCodeBlur = onOzonFbsKizCodeBlur;
  window.onOzonFbsKizCodeKey = onOzonFbsKizCodeKey;
  window.onOzonFbsKizGtdInput = onOzonFbsKizGtdInput;
  window.addOzonFbsKizCode = addOzonFbsKizCode;
  window.removeOzonFbsKizCode = removeOzonFbsKizCode;
  window.onOzonFbsKizFilterFilledChange = onOzonFbsKizFilterFilledChange;
  window.onOzonFbsKizFilterEmptyChange = onOzonFbsKizFilterEmptyChange;
  window.onOzonFbsKizStickerScanKey = onOzonFbsKizStickerScanKey;
  window.onOzonFbsKizMarkScanKey = onOzonFbsKizMarkScanKey;
  window.cancelOzonFbsKizMarkScan = cancelOzonFbsKizMarkScan;
  window.clearOzonFbsKizRow = clearOzonFbsKizRow;
  window.openOzonFbsKizImportModal = openOzonFbsKizImportModal;
  window.closeOzonFbsKizImportModal = closeOzonFbsKizImportModal;
  window.toggleOzonFbsKizImportPanel = toggleOzonFbsKizImportPanel;
  window.onOzonFbsKizImportTextInput = onOzonFbsKizImportTextInput;
  window.onOzonFbsKizImportTextBeforeInput = onOzonFbsKizImportTextBeforeInput;
  window.onOzonFbsKizImportTextPaste = onOzonFbsKizImportTextPaste;
  window.onOzonFbsKizImportTextKey = onOzonFbsKizImportTextKey;
  window.runOzonFbsKizImport = runOzonFbsKizImport;
  window.applyOzonFbsKizImportConflicts = applyOzonFbsKizImportConflicts;
  window.dismissOzonFbsKizImportConflicts = dismissOzonFbsKizImportConflicts;
  window.selectAllOzonFbsKizImportConflicts = selectAllOzonFbsKizImportConflicts;
  window.refreshOzonFbsMarkingStatus = refreshOzonFbsMarkingStatus;
  window.refreshOzonFbsPickVerifyStatus = refreshOzonFbsPickVerifyStatus;
  window.openOzonFbsPickVerifyModal = openOzonFbsPickVerifyModal;
  window.closeOzonFbsPickVerifyModal = closeOzonFbsPickVerifyModal;
  window.saveOzonFbsPickVerifyModal = saveOzonFbsPickVerifyModal;
  window.renderOzonFbsPickVerifyTable = renderOzonFbsPickVerifyTable;
  window.onOzonFbsPickFilterFilledChange = onOzonFbsPickFilterFilledChange;
  window.onOzonFbsPickFilterEmptyChange = onOzonFbsPickFilterEmptyChange;
  window.onOzonFbsPickStickerScanKey = onOzonFbsPickStickerScanKey;
  window.onOzonFbsPickSkuScanKey = onOzonFbsPickSkuScanKey;
  window.cancelOzonFbsPickSkuScan = cancelOzonFbsPickSkuScan;
  window.clearOzonFbsPickVerify = clearOzonFbsPickVerify;
})();
