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
    viewMode: "orders", // orders | supplies
  };

  const collectState = {
    preview: null,
    sourceId: null,
    busy: false,
  };

  const supplyDetailState = {
    supplyId: null,
    sourceId: null,
    supply: null,
    selected: new Set(),
  };

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

  /** Ozon sticker: large 4 digits before «-0210-1» block (e.g. 2363 in 0101152363-0210-1). */
  function formatOzonPostingNumberHtml(postingNumber) {
    const s = String(postingNumber || "").trim();
    if (!s) return "—";
    const parts = s.split("-");
    const hi = (text) => `<span class="ozon-fbs-posting-tail">${esc(text)}</span>`;

    if (parts.length >= 2) {
      const head = String(parts[0] || "");
      const tail = parts.length > 1 ? `-${parts.slice(1).map((p) => esc(p)).join("-")}` : "";
      // Order + suffix glued in first segment (0101152363-0210-1 → 2363 on sticker).
      if (head.length > 8 && /^\d+$/.test(head)) {
        return `${esc(head.slice(0, -4))}${hi(head.slice(-4))}${tail}`;
      }
      // Explicit 4-digit segment after order (33720345-0046-1, 010115-2363-0210-1).
      if (/^\d{4}$/.test(parts[1])) {
        const after = parts.length > 2 ? `-${parts.slice(2).map((p) => esc(p)).join("-")}` : "";
        return `${esc(parts[0])}-${hi(parts[1])}${after}`;
      }
    }

    let seen = 0;
    let cut = -1;
    for (let i = s.length - 1; i >= 0; i -= 1) {
      if (/\d/.test(s[i])) {
        seen += 1;
        if (seen === 4) {
          cut = i;
          break;
        }
      }
    }
    if (cut >= 0) {
      return `${esc(s.slice(0, cut))}${hi(s.slice(cut))}`;
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
      return detail.map((x) => (typeof x === "string" ? x : (x?.msg || JSON.stringify(x)))).join("; ");
    }
    if (typeof detail === "object" && detail.msg) return String(detail.msg);
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

  function jsonHeaders() {
    const h = { "Content-Type": "application/json" };
    const csrf = typeof window.getCsrfToken === "function" ? window.getCsrfToken() : "";
    if (csrf) h["X-CSRF-Token"] = csrf;
    return h;
  }

  function isSuppliesTab() {
    return state.tab === "awaiting_deliver" || state.tab === "delivering";
  }

  function isDeliveringSuppliesTab() {
    return state.tab === "delivering";
  }

  function isSupplyDetailReadOnly() {
    return Boolean(supplyDetailState.supply?.read_only) || isDeliveringSuppliesTab();
  }

  function syncSupplyDetailReadOnlyMode(readOnly) {
    const modal = document.getElementById("ozonFbsSupplyDetailModal");
    const actions = modal?.querySelector(".wb-fbs-sd-actions");
    const checkTh = modal?.querySelector(".wb-fbs-sd-col-check");
    const actTh = modal?.querySelector(".wb-fbs-sd-col-act");
    if (modal) modal.classList.toggle("wb-fbs-sd--readonly", !!readOnly);
    if (actions) actions.hidden = !!readOnly;
    if (checkTh) checkTh.hidden = !!readOnly;
    if (actTh) actTh.hidden = !!readOnly;
    const info = document.getElementById("ozonFbsSupplyDetailInfo");
    if (info) {
      if (readOnly) {
        info.hidden = false;
        info.textContent = "Только просмотр — отправления уже в доставке.";
      } else {
        info.hidden = true;
        info.textContent = "";
      }
    }
  }

  function colspan() {
    return isSuppliesTab() ? 6 : 4;
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
    state.counts = counts || {};
    Object.keys(TAB_COUNT_IDS).forEach((tab) => {
      const el = document.getElementById(TAB_COUNT_IDS[tab]);
      if (el) el.textContent = String(state.counts[tab] || 0);
    });
    syncShipAllButton();
  }

  function syncShipAllButton() {
    const btn = document.getElementById("ozonFbsShipAllBtn");
    if (!btn) return;
    const n = Number(state.counts.awaiting_packaging || 0);
    btn.disabled = !state.sourceId || n <= 0 || Boolean(state.shipAllBusy) || Boolean(collectState.busy);
    btn.title = n > 0
      ? `Собрать все отправления в «Ожидают сборки» (${n}) и создать локальную поставку`
      : "Нет отправлений в «Ожидают сборки»";
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
    let word = "отправлений";
    if (!(abs > 10 && abs < 20)) {
      if (last === 1) word = "отправление";
      else if (last >= 2 && last <= 4) word = "отправления";
    }
    return `Выбрано ${n} ${word}`;
  }

  function updateBottomBar() {
    const bar = document.getElementById("ozonFbsBottomBar");
    const label = document.getElementById("ozonFbsSelectedLabel");
    const packActions = document.getElementById("ozonFbsBottomPackagingActions");
    const addBtn = document.getElementById("ozonFbsAddToSupplyBtn");
    const n = state.selected.size;
    const isPackaging = state.tab === "awaiting_packaging" && !isSuppliesTab();
    if (label) label.textContent = selectedCountLabel(n);
    if (packActions) packActions.classList.toggle("hidden", !isPackaging);
    if (addBtn) {
      const openSupplies = Number((state.counts && state.counts.open_supplies) || 0);
      addBtn.classList.toggle("hidden", !(isPackaging && n > 0 && openSupplies > 0));
    }
    if (bar) bar.classList.toggle("hidden", !(isPackaging && n > 0));
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
    const nextMode = supplies ? "supplies" : "orders";
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
        ? "Поиск по поставке, складу…"
        : "Поиск по отправлению, артикулу, ШК…";
    }
    if (!colgroup || !thead) return;
    if (!modeChanged && colgroup.children.length) return;
    if (supplies) {
      colgroup.innerHTML = `
        <col data-fixed="1" class="wb-fbs-col-check" style="width:40px" />
        <col data-col="0" class="wb-fbs-col-supply" style="width:28%" />
        <col data-col="1" class="wb-fbs-col-qr" style="width:18%" />
        <col data-col="2" class="wb-fbs-col-orders" style="width:14%" />
        <col data-col="3" class="wb-fbs-col-status" style="width:16%" />
        <col data-col="4" class="wb-fbs-col-wh" style="width:24%" />
      `;
      thead.innerHTML = `
        <th class="wb-fbs-th-check"><input type="checkbox" id="ozonFbsSelectAll" onchange="toggleSelectAllOzonFbs(this.checked)" title="Выбрать все на странице" /></th>
        <th data-col="0">Поставка</th>
        <th data-col="1">ID поставки</th>
        <th data-col="2">Заказы</th>
        <th data-col="3">Этап сборки</th>
        <th data-col="4">Склад</th>
      `;
    } else {
      colgroup.innerHTML = `
        <col data-fixed="1" class="wb-fbs-col-check" style="width:40px" />
        <col data-col="0" class="wb-fbs-col-order" />
        <col data-col="1" class="wb-fbs-col-product" />
        <col data-col="2" class="wb-fbs-col-wh" />
      `;
      thead.innerHTML = `
        <th class="wb-fbs-th-check"><input type="checkbox" id="ozonFbsSelectAll" onchange="toggleSelectAllOzonFbs(this.checked)" title="Выбрать все на странице" /></th>
        <th data-col="0">Отправление<span class="col-resize-handle"></span></th>
        <th data-col="1">Товар<span class="col-resize-handle"></span></th>
        <th data-col="2">Склад<span class="col-resize-handle"></span></th>
      `;
      initColumnResizer();
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
    tbody.innerHTML = state.items.map((s) => {
      const sid = String(s.supply_id || "").trim();
      const checked = state.selected.has(sid) ? "checked" : "";
      const created = s.created_at || "";
      const createdMeta = created
        ? `<div class="wb-fbs-order-meta">от ${esc(fmtDate(created))}</div>`
        : "";
      const ordersCount = Number(s.order_count || 0);
      const status = String(s.status_label || "Сборка заказов");
      return `<tr>
        <td><input type="checkbox" class="wb-fbs-row-cb" data-supply-id="${esc(sid)}" ${checked} onchange="onOzonFbsCheckboxChange()" /></td>
        <td>
          <div class="wb-fbs-supply-name is-link" role="button" tabindex="0"
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
      </tr>`;
    }).join("");
    syncSelectAll();
    updateBottomBar();
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
      const whLabel = row.warehouse_label || row.warehouse_name || "—";
      const whId = row.warehouse_id != null && String(row.warehouse_id).trim()
        ? String(row.warehouse_id).trim()
        : "";
      return `<tr data-posting="${pn}">
      <td><input type="checkbox" class="wb-fbs-row-cb" data-posting="${pn}" ${checked} onchange="onOzonFbsCheckboxChange()" /></td>
      <td>
        <div class="wb-fbs-order-id">${formatOzonPostingNumberHtml(pnRaw)}</div>
        <div class="wb-fbs-order-meta">от ${esc(fmtDate(created))}</div>
        ${badges.length ? `<div class="wb-fbs-badges">${badges.join("")}</div>` : ""}
        ${whLabel && whLabel !== "—" ? `<div class="ozon-fbs-mobile-wh">${esc(whLabel)}${whId ? " · ID " + esc(whId) : ""}</div>` : ""}
      </td>
      <td>
        <div class="wb-fbs-product">
          ${photo}
          <div class="wb-fbs-product-text">
            <div class="wb-fbs-product-name" title="${esc(productName)}">${esc(productName)}</div>
            <div class="wb-fbs-product-sub">Арт. ${esc(offer || "—")}${sku ? " · SKU " + esc(sku) : ""}</div>
            ${barcodeHtml}
          </div>
        </div>
      </td>
      <td>
        <div class="wb-fbs-wh-name" title="${esc(whLabel)}">${esc(whLabel)}</div>
        <div class="wb-fbs-order-meta">${whId ? "ID " + esc(whId) : ""}</div>
      </td>
    </tr>`;
    }).join("");
    syncSelectAll();
    updateBottomBar();
  }

  async function loadPostings(resetPage) {
    if (!canView()) return;
    if (resetPage) state.page = 1;
    syncTableMode();
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">Загрузка…</td></tr>`;
    if (!state.sourceId) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">Добавьте источник OZON ФБС в настройках</td></tr>`;
      return;
    }

    const suppliesMode = isSuppliesTab();
    const params = new URLSearchParams({
      source_id: String(state.sourceId),
      tab: state.tab,
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    if (state.search && !suppliesMode) params.set("search", state.search);

    try {
      const url = suppliesMode
        ? `/api/ozon-fbs/supplies?${params}`
        : `/api/ozon-fbs/postings?${params}`;
      const res = await fetch(url);
      const data = await res.json();
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

      state.total = suppliesMode ? items.length : Number(data.total || 0);
      updateTabCounts(data.counts || {});
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
      html += `<p class="wb-fbs-collect-mgt-result-err">Ошибки:</p><ul class="wb-fbs-collect-mgt-result-err">` +
        errors.map((e) => {
          if (typeof e === "string") return `<li>${esc(e)}</li>`;
          return `<li>${formatOzonPostingNumberHtml(e.posting_number || "")}: ${esc(e.error || "")}</li>`;
        }).join("") + "</ul>";
    }
    body.innerHTML = html;
    modal.classList.remove("hidden");
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
      lead.textContent = `Отправлений в «Ожидают сборки»: ${preview?.posting_count || preview?.mgt_count || 0}.`;
    }
    if (!body) return;
    body.innerHTML = groups.map((g, idx) => {
      const gkey = String(g.group_key || `g${idx}`);
      const mode = String(g.mode || "create");
      const label = String(g.label || "Склад");
      const count = Number(g.order_count || 0);
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
          <p class="wb-fbs-collect-mgt-group-meta">${count} отпр.</p>
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

  async function shipAll() {
    if (!state.sourceId || state.shipAllBusy || collectState.busy) return;
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
      if (!(preview.posting_count || preview.mgt_count)) {
        alert("Нет отправлений в «Ожидают сборки»");
        await loadPostings(false);
        return;
      }
      collectState.preview = preview;
      if (!preview.needs_modal) {
        if (btn) btn.textContent = "Сборка…";
        showSyncInfo("Сборка отправлений и создание поставок…");
        const decisions = (preview.groups || []).map((g) => ({
          group_key: String(g.group_key || ""),
          action: "add",
          supply_id: String(g.default_supply_id || ""),
        }));
        const data = await executeCollect(decisions, state.sourceId);
        collectState.busy = false;
        state.shipAllBusy = false;
        closeCollectModal();
        showCollectResult(data);
        showSyncInfo(data.message || "Готово");
        if (data.goto_awaiting_deliver) setTab("awaiting_deliver");
        else await loadPostings(true);
        return;
      }
      renderCollectModal(preview);
      document.getElementById("ozonFbsCollectModal")?.classList.remove("hidden");
      if (confirmBtn) confirmBtn.disabled = false;
    } catch (e) {
      collectState.sourceId = null;
      const err = e.message || String(e);
      showSyncInfo(err);
      alert(err);
    } finally {
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
    showSyncInfo("Сборка отправлений и создание поставок…");
    try {
      const data = await executeCollect(decisions, sourceId);
      closeCollectModal();
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
      collectState.busy = false;
      state.shipAllBusy = false;
      if (confirmBtn) confirmBtn.disabled = false;
      syncShipAllButton();
    }
  }

  /* ── Supply detail modal ── */

  function closeSupplyDetailModal() {
    closeOzonFbsRowMenus();
    document.getElementById("ozonFbsSupplyDetailModal")?.classList.add("hidden");
    syncSupplyDetailReadOnlyMode(false);
    closePickingMenu();
    closeStickersMenu();
    supplyDetailState.supplyId = null;
    supplyDetailState.sourceId = null;
    supplyDetailState.supply = null;
    supplyDetailState.selected = new Set();
  }

  function supplyDetailReady() {
    return Boolean(supplyDetailState.supplyId && supplyDetailState.sourceId);
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
    if (supplyDetailReady()) {
      openStickersPrint([pn]);
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
    if (wh) wh.textContent = String(supply.warehouse_label || "—").trim() || "—";
    if (meta) {
      meta.innerHTML = [
        `<span class="wb-fbs-sd-chip">Отправлений ${esc(supply.order_count || 0)}</span>`,
        sid ? `<span class="wb-fbs-sd-chip">ID ${esc(sid)}</span>` : "",
      ].filter(Boolean).join("");
    }
    const allOrders = Array.isArray(supply.orders) ? supply.orders : [];
    const kizSplit = document.getElementById("ozonFbsKizSplit");
    if (!readOnly) {
      if (kizSplit) {
        const needsKiz = allOrders.some((o) => o && o.kiz_required);
        kizSplit.hidden = !needsKiz;
        if (!needsKiz) _ozonFbsKizSplitSetTone("");
        else refreshOzonFbsMarkingStatus(true).catch(() => {});
      }
      _ozonFbsSyncPickVerifyBtn(allOrders);
    } else if (kizSplit) {
      kizSplit.hidden = true;
    }
    const searchQ = String(document.getElementById("ozonFbsSupplyDetailSearchFilter")?.value || "").trim().toLowerCase();
    const orders = searchQ
      ? allOrders.filter((o) => {
          const hay = [
            o.posting_number, o.offer_id, o.sku, o.product_name, o.warehouse_label,
            ...(Array.isArray(o.barcodes) ? o.barcodes : []),
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

  async function openSupplyDetailModal(supplyId) {
    const sid = String(supplyId || "").trim();
    if (!sid || !state.sourceId) return;
    supplyDetailState.supplyId = sid;
    supplyDetailState.sourceId = state.sourceId;
    supplyDetailState.selected = new Set();
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
    try {
      const tabParam = readOnly ? "&posting_tab=delivering" : "";
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/detail?source_id=${state.sourceId}${tabParam}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Не найдено");
      renderSupplyDetail(data);
    } catch (e) {
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
      const params = new URLSearchParams({ source_id: String(sourceId) });
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/cancelled?${params}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      }
      if (ozonFbsCancelledState.refreshGen !== refreshGen) return;
      ozonFbsCancelledState.lastError = "";
      ozonFbsCancelledState.rows = Array.isArray(data.rows) ? data.rows : [];
      renderOzonFbsCancelledOrdersTable();
      _ozonFbsCancelledMergeIntoDetail(ozonFbsCancelledState.rows);
      const warnings = Array.isArray(data.warnings) ? data.warnings : [];
      if (warnings.length) {
        _ozonFbsCancelledSetInfo(
          `Часть отправлений проверена по локальным данным (${warnings.length})`,
          "ok"
        );
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
    if (!sid || !sourceId) return;
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
    const missingCount = Number(res.headers.get("X-Feedpilot-Stickers-Missing-Count") || 0);
    if (missingCount > 0) {
      const expected = res.headers.get("X-Feedpilot-Stickers-Expected") || "?";
      const loaded = res.headers.get("X-Feedpilot-Stickers-Loaded") || "?";
      const missingRaw = String(res.headers.get("X-Feedpilot-Stickers-Missing") || "").trim();
      const preview = missingRaw
        ? missingRaw.split(",").slice(0, 5).join(", ")
        : "";
      const suffix = missingCount > 5 ? ` … (+${missingCount - 5})` : "";
      alert(
        `Загружено ${loaded} из ${expected} этикеток.\n`
        + `Не загружено: ${missingCount}. Повторите печать стикеров через 1–2 мин.\n`
        + (preview ? `Отправления: ${preview}${suffix}` : "")
      );
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
    if (!supplyDetailReady()) return;
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
    if (!sid || !sourceId || !supplyDetailReady()) return;
    closePickingMenu();
    const btn = document.getElementById("ozonFbsSupplyDetailPickingBtn");
    const caret = document.getElementById("ozonFbsSupplyDetailPickingMenuBtn");
    if (btn) btn.disabled = true;
    if (caret) caret.disabled = true;
    const url =
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/picking-list` +
      `?source_id=${sourceId}`;
    openPrintHtml(url, "Разрешите всплывающие окна для листа подбора")
      .catch((e) => alert(String(e.message || e)))
      .finally(() => {
        if (!supplyDetailReady()) return;
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
    if (!supplyDetailReady()) return;
    closePickingMenu();
    const menu = document.getElementById("ozonFbsStickersMenu");
    const caret = document.getElementById("ozonFbsSupplyDetailStickersMenuBtn");
    if (!menu || !caret) return;
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    caret.setAttribute("aria-expanded", willOpen ? "true" : "false");
  }

  function openStickersPrint(postingNumbers) {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !supplyDetailReady()) return;
    closeStickersMenu();
    const btn = document.getElementById("ozonFbsSupplyDetailStickersBtn");
    const caret = document.getElementById("ozonFbsSupplyDetailStickersMenuBtn");
    if (btn) btn.disabled = true;
    if (caret) caret.disabled = true;
    const ids = Array.isArray(postingNumbers)
      ? postingNumbers.map((x) => String(x || "").trim()).filter(Boolean)
      : [];
    let url =
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/stickers-print` +
      `?source_id=${sourceId}`;
    if (ids.length) url += `&order_ids=${encodeURIComponent(ids.join(","))}`;
    openPrintHtml(url, "Разрешите всплывающие окна для стикеров")
      .catch((e) => alert(String(e.message || e)))
      .finally(() => {
        if (!supplyDetailReady()) return;
        if (btn) btn.disabled = false;
        if (caret) caret.disabled = false;
      });
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
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/sticker-groups?source_id=${sourceId}`
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
    openStickersPrint(nums);
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
    syncTableMode();
    initColumnResizer();
    await loadSources();
    await loadPostings(true);
    syncShipAllButton();
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
    if (textEl) textEl.textContent = "";
    if (palletsEl) {
      palletsEl.innerHTML = "";
      palletsEl.hidden = true;
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
  ) {
    const info = document.getElementById("ozonFbsSyncInfo");
    if (!info) return;
    const msg = String(text || "").trim();
    const textEl = document.getElementById("ozonFbsSyncInfoText");
    const palletsEl = document.getElementById("ozonFbsSyncInfoPallets");
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

    info.hidden = !(msg || rowsSrc.length || (palletErr && canShowPallets));
    info.classList.toggle("is-error", kind === "error");
    info.classList.toggle("is-ok", kind === "ok");
    info.style.color = "";
  }

  function setSyncUi(running) {
    const stopBtn = document.getElementById("ozonFbsStopBtn");
    const syncBtn = document.getElementById("ozonFbsSyncBtn");
    if (stopBtn) stopBtn.classList.toggle("hidden", !running);
    if (syncBtn) syncBtn.disabled = running;
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
      const sourceRows = syncSourceRows(st, msg);
      if (running && sourceRows) showSyncInfo(text, kind, null, sourceRows);
      else showSyncInfo(text, kind, pallets, sourceRows, palletErr);
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
    if (lead) {
      lead.textContent =
        `Отправления будут собраны на Ozon и попадут в новую локальную поставку на «Ожидают отгрузки» (${count} шт.).`;
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
    if (lead) {
      lead.textContent = supplies.length
        ? `Выберите открытую поставку для ${count} отпр. Показаны совместимые по складу.`
        : `Для ${count} отпр. нет совместимых открытых поставок.`;
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

  function renderShipmentsBarcode(data) {
    const barcode = data?.barcode || null;
    const whName = esc(data?.warehouse_name || "склада");
    const text = String(barcode?.barcode_text || "").trim();
    const b64 = String(barcode?.barcode_image_base64 || "").trim();
    const ctype = String(barcode?.content_type || "image/png").trim() || "image/png";
    const hasImg = Boolean(b64);
    const canPrint = Boolean(hasImg || text);
    const visual = hasImg
      ? `<img id="ozonFbsShipmentsBarcodeImg" src="data:${esc(ctype)};base64,${b64}" alt="Штрихкод поставки" />`
      : (text
        ? `<div class="ozon-fbs-shipments-barcode-empty">ШК: ${esc(text)}</div>`
        : `<div class="ozon-fbs-shipments-barcode-empty">Штрихкод появится после формирования отгрузки</div>`);
    const textHtml = text
      ? `<div class="ozon-fbs-shipments-barcode-text">${esc(text)}</div>`
      : "";
    return `
      <section class="ozon-fbs-shipments-barcode-card">
        <div class="ozon-fbs-shipments-barcode-head">
          <h4 class="ozon-fbs-shipments-barcode-title">Штрихкод для склада ${whName}</h4>
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
        </div>
        <div class="ozon-fbs-shipments-barcode-grid">
          <div class="ozon-fbs-shipments-barcode-visual">
            ${visual}
            ${textHtml}
          </div>
        </div>
      </section>`;
  }

  function renderShipmentsBlocks(data) {
    const blocks = Array.isArray(data?.blocks) ? data.blocks : [];
    if (!blocks.length) {
      return `<div class="ozon-fbs-shipments-loading">Нет данных отгрузки на выбранную дату</div>`;
    }
    return blocks.map((block, bi) => {
      const carriages = Array.isArray(block.carriages) ? block.carriages : [];
      const carriageHtml = carriages.map((c) => {
        const formed = Boolean(c.is_formed);
        const statusCls = formed ? " is-formed" : "";
        const count = Number(c.postings_count || 0);
        const canForm = Boolean(c.can_form) && !shipmentsState.forming;
        const formBtn = formed
          ? ""
          : `<button type="button" class="ozon-fbs-shipments-form-btn"
                     ${canForm ? "" : "disabled"}
                     onclick="ozonFbsShipmentsForm()">Сформировать</button>`;
        const picking = block.assembly_list_availability !== false
          ? `<button type="button" class="ozon-fbs-shipments-link"
                     onclick="ozonFbsOpenPickingList()">Лист подбора</button>`
          : "";
        return `
          <div class="ozon-fbs-shipments-carriage">
            <span class="ozon-fbs-shipments-carriage-title">${esc(c.label || "Отгрузка")}</span>
            <span class="ozon-fbs-shipments-carriage-count">${count} отправлений</span>
            <span class="ozon-fbs-shipments-status${statusCls}">${esc(c.status_label || "Не сформирована")}</span>
            <div class="ozon-fbs-shipments-carriage-actions">
              ${formBtn}
              ${picking}
            </div>
          </div>`;
      }).join("");
      return `
        <section class="ozon-fbs-shipments-block">
          <h4 class="ozon-fbs-shipments-block-title">${esc(block.day_label || "Ozon")}</h4>
          <div class="ozon-fbs-shipments-meta">
            <div class="ozon-fbs-shipments-meta-item">
              <span class="ozon-fbs-shipments-meta-label">Склад</span>
              <span class="ozon-fbs-shipments-meta-value">${esc(block.warehouse_name || data.warehouse_name || "—")}</span>
            </div>
            <div class="ozon-fbs-shipments-meta-item">
              <span class="ozon-fbs-shipments-meta-label">Пункт</span>
              <span class="ozon-fbs-shipments-meta-value">${esc(block.dropoff_point_type_label || "СЦ")}</span>
            </div>
            <div class="ozon-fbs-shipments-meta-item">
              <span class="ozon-fbs-shipments-meta-label">Способ отгрузки</span>
              <span class="ozon-fbs-shipments-meta-value">${esc(block.dropoff_point_type_label || "В пункт приема")}</span>
            </div>
            <div class="ozon-fbs-shipments-meta-item">
              <span class="ozon-fbs-shipments-meta-label">Адрес</span>
              <span class="ozon-fbs-shipments-meta-value">${esc(block.dropoff_address || "—")}</span>
            </div>
            <div class="ozon-fbs-shipments-meta-item">
              <span class="ozon-fbs-shipments-meta-label">Собрано заказов</span>
              <span class="ozon-fbs-shipments-meta-value">${esc(block.collected_label || "—")}</span>
            </div>
            <div class="ozon-fbs-shipments-meta-item">
              <span class="ozon-fbs-shipments-meta-label">Приём отправлений</span>
              <span class="ozon-fbs-shipments-meta-value">${esc(block.acceptance_label || "—")}</span>
            </div>
          </div>
          ${carriageHtml}
          <div class="ozon-fbs-shipments-hint">
            <span class="ozon-fbs-shipments-hint-ico" aria-hidden="true">✓</span>
            <span>${esc(block.hint || "")}</span>
          </div>
        </section>`;
    }).join("");
  }

  function renderShipmentsView(data) {
    const body = document.getElementById("ozonFbsShipmentsBody");
    if (!body) return;
    if (!data) {
      body.innerHTML = `<div class="ozon-fbs-shipments-loading">Нет данных</div>`;
      return;
    }
    if (data.ok === false && data.message) {
      body.innerHTML = `<div class="ozon-fbs-shipments-error">${esc(data.message)}</div>`;
      return;
    }
    body.innerHTML = `${renderShipmentsBarcode(data)}${renderShipmentsBlocks(data)}`;
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
    if (!sid || !sourceId) {
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

  function shipmentsPrintBarcode() {
    const sid = shipmentsState.supplyId;
    const sourceId = shipmentsState.sourceId;
    if (!sid || !sourceId) return;
    const dateEl = document.getElementById("ozonFbsShipmentsDate");
    const methodEl = document.getElementById("ozonFbsShipmentsMethod");
    const day = String(dateEl?.value || todayIsoDate());
    const methodId = String(methodEl?.value || shipmentsState.data?.selected_delivery_method_id || "").trim();
    const barcode = shipmentsState.data?.barcode || {};
    const carriageId = String(barcode.carriage_id || "").trim();
    const qs = new URLSearchParams({
      source_id: String(sourceId),
      departure_date: day,
    });
    if (methodId) qs.set("delivery_method_id", methodId);
    if (carriageId) qs.set("carriage_id", carriageId);
    const url =
      `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/shipments/barcode-print?${qs.toString()}`;
    openPrintHtml(url, "Разрешите всплывающие окна для печати штрихкода")
      .catch((e) => alert(String(e.message || e)));
  }

  function shipmentsDownloadBarcode() {
    const barcode = shipmentsState.data?.barcode || {};
    const b64 = String(barcode.barcode_image_base64 || "").trim();
    const text = String(barcode.barcode_text || "").trim();
    if (b64) {
      const ctype = String(barcode.content_type || "image/png");
      const a = document.createElement("a");
      a.href = `data:${ctype};base64,${b64}`;
      a.download = `ozon-shipment-barcode-${text || "label"}.png`;
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
    }
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
    statusRefreshing: false,
    statusRefreshGen: 0,
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
  };

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

  /**
   * Ozon FBS sticker match — parity with WB `_wbFbsKizFindBySticker` / backend lookup.
   * Ozon API ``FbsPostingBarcodes``: upper/lower штрихкоды этикетки + posting_number.
   */
  function _ozonFbsFindByStickerInRows(scan, rows) {
    const raw = _ozonFbsNormalizeScan(scan);
    if (!raw) return { row: null, ambiguous: false };
    const rawKey = _ozonFbsStickerScanKey(raw);
    const rawLower = raw.toLowerCase();
    const list = Array.isArray(rows) ? rows : [];

    const byBarcode = [];
    for (const row of list) {
      const bc = _ozonFbsNormalizeScan(row?.sticker_barcode);
      const bcLow = _ozonFbsNormalizeScan(row?.sticker_lower_barcode);
      if (bc && _ozonFbsStickerScanKey(bc) === rawKey) byBarcode.push(row);
      else if (bcLow && _ozonFbsStickerScanKey(bcLow) === rawKey) byBarcode.push(row);
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
      const pn = String(row?.posting_number || "").trim();
      const pnLower = pn.toLowerCase();
      if (pnLower && (pnLower === rawLower || rawLower.includes(pnLower) || pnLower.includes(rawLower))) {
        matches.push(row);
        continue;
      }
      const full = _ozonFbsStickerNumberFromRow(row);
      const partA = _ozonFbsNormalizeScan(row?.sticker_part_a);
      const partB = _ozonFbsNormalizeScan(row?.sticker_part_b);
      if (
        (full && (_ozonFbsStickerScanKey(full) === rawKey || digits === full.replace(/\D+/g, ""))) ||
        (partA && partB && digits === `${partA}${partB}`.replace(/\D+/g, "")) ||
        (
          partB
          && (_ozonFbsStickerScanKey(partB) === rawKey || digits === partB.replace(/\D+/g, ""))
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
    if (typeof _wbFbsKizNormalizeMark === "function") {
      return _wbFbsKizNormalizeMark(value);
    }
    return String(value || "")
      .replace(/\u2194/g, "\u001D")
      .replace(/\r?\n/g, "")
      .replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, "");
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
    return !!(supplyDetailState.supplyId && (supplyDetailState.sourceId || state.sourceId));
  }

  function _ozonFbsSyncPickVerifyBtn(orders) {
    const btn = document.getElementById("ozonFbsSupplyDetailPickVerifyBtn");
    if (!btn) return;
    const list = Array.isArray(orders) ? orders : [];
    const hasPlain = list.some((o) => o && !o.kiz_required && !o.cancelled);
    const can = typeof isTenantOwner === "function" && isTenantOwner()
      && _ozonFbsSupplyActionsReady() && hasPlain;
    btn.hidden = !can;
    btn.style.display = can ? "" : "none";
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

  function _ozonFbsKizSplitSetTone(tone) {
    const split = document.getElementById("ozonFbsKizSplit");
    if (!split) return;
    split.classList.remove("is-ok", "is-error");
    const t = String(tone || "").trim().toLowerCase();
    if (t === "ok") split.classList.add("is-ok");
    else if (t === "error") split.classList.add("is-error");
  }

  function _ozonFbsKizSetFiltersReady(ready) {
    ozonFbsKizState.rowsReady = !!ready;
    const sticker = document.getElementById("ozonFbsKizStickerScan");
    if (sticker) {
      sticker.readOnly = !ready;
      sticker.disabled = !ready;
    }
  }

  function _ozonFbsPickSetFiltersReady(ready) {
    ozonFbsPickState.rowsReady = !!ready;
    const sticker = document.getElementById("ozonFbsPickStickerScan");
    if (sticker) {
      sticker.readOnly = !ready;
      sticker.disabled = !ready;
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
      const codes = Array.isArray(row?.kiz_codes) && row.kiz_codes.length ? row.kiz_codes : [""];
      total += codes.length;
      for (const code of codes) {
        if (String(code || "").trim()) filled += 1;
      }
    }
    el.textContent = `Просканировано ${filled} из ${total} КИЗ`;
  }

  function _ozonFbsKizCollectFromDom() {
    document.querySelectorAll("#ozonFbsKizTbody .wb-fbs-kiz-code-input").forEach((input) => {
      const pn = String(input.dataset.posting || "");
      const idx = Number(input.dataset.idx);
      const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
      if (!row || !Number.isFinite(idx)) return;
      if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [];
      row.kiz_codes[idx] = _ozonFbsNormalizeMark(input.value);
    });
  }

  function _ozonFbsKizCaptureBaseline() {
    const map = {};
    for (const r of ozonFbsKizState.rows) {
      const pn = String(r.posting_number || "").trim();
      if (!pn) continue;
      map[pn] = _ozonFbsKizNormalizeCodesList(r.kiz_codes);
    }
    ozonFbsKizState.baselineByPosting = map;
  }

  function _ozonFbsKizFindBySticker(scan) {
    return _ozonFbsFindByStickerInRows(scan, ozonFbsKizState.rows);
  }

  function _ozonFbsKizFindByPosting(scan) {
    return _ozonFbsFindByStickerInRows(scan, ozonFbsKizState.rows);
  }

  function _ozonFbsKizFindExistingMark(mark) {
    const key = _ozonFbsNormalizeMark(mark);
    if (!key) return null;
    for (const row of ozonFbsKizState.rows) {
      for (const c of row.kiz_codes || []) {
        if (_ozonFbsNormalizeMark(c) === key) return row;
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
    const showErrors = !!document.getElementById("ozonFbsKizFilterErrors")?.checked;
    const showCancelled = !!document.getElementById("ozonFbsKizFilterCancelled")?.checked;
    const pending = String(ozonFbsKizState.pendingPosting || "").trim();
    const rows = (ozonFbsKizState.rows || []).filter((r) => {
      if (showFilled && _ozonFbsKizRowIsEmpty(r)) return false;
      if (showEmpty && !_ozonFbsKizRowIsEmpty(r)) return false;
      if (showErrors && !_ozonFbsKizRowHasError(r)) return false;
      if (showCancelled && !String(r?.cancel_reason_label || "").trim()) return false;
      if (!q) return true;
      const hay = [
        r.posting_number, r.offer_id, r.product_name, r.sku,
        r.sticker_barcode, r.sticker_part_a, r.sticker_part_b,
        ...(Array.isArray(r.barcodes) ? r.barcodes : []),
      ].map((x) => String(x || "").toLowerCase()).join(" ");
      return hay.includes(q);
    });
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">${
        ozonFbsKizState.rows?.length ? "Нет строк по выбранным фильтрам" : "Нет отправлений с маркировкой"
      }</td></tr>`;
      _ozonFbsKizUpdateScanCounter();
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const pn = String(r.posting_number || "");
      const safePn = esc(pn);
      const menuKey = _ozonFbsPostingMenuKey(pn);
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
      const canRemoveRow = codes.length > 1;
      const codeHtml = codes.map((code, idx) => {
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
      const stickerHtml = _ozonFbsKizStickerHtml(r);
      const menuIcon = typeof _wbFbsQrMenuIconHtml === "function" ? _wbFbsQrMenuIconHtml() : "";
      return `<tr class="wb-fbs-kiz-row${pending === pn ? " is-active" : ""}" data-posting="${safePn}">
        <td>
          <div class="wb-fbs-kiz-order-id">${formatOzonPostingNumberHtml(pn)}</div>
          <div class="wb-fbs-kiz-order-sticker">${stickerHtml}</div>
          ${Number(r.quantity) > 1 ? `<div class="wb-fbs-order-meta">${esc(r.quantity)} шт.</div>` : ""}
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
          <button type="button" class="wb-fbs-kiz-add" onclick="addOzonFbsKizCode('${safePn}')">+ Добавить КИЗ</button>
        </td>
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
      const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
      if (!row || !Number.isFinite(idx)) return;
      const rowCodes = Array.isArray(row.kiz_codes) ? row.kiz_codes : [];
      input.value = String(rowCodes[idx] ?? "");
    });
    _ozonFbsKizUpdateScanCounter();
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
        const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
        if (row && Array.isArray(row.kiz_codes) && Number.isFinite(idx) && idx >= 0) {
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
    const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
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
    const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
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
    const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
    if (!row || !Number.isFinite(removeIdx)) return;
    if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [""];
    if (row.kiz_codes.length <= 1) {
      row.kiz_codes = [""];
    } else {
      row.kiz_codes.splice(removeIdx, 1);
      if (!row.kiz_codes.length) row.kiz_codes = [""];
    }
    delete ozonFbsKizState.errors[pn];
    if (!_ozonFbsKizNormalizeCodesList(row.kiz_codes).length) {
      row.kiz_status = "empty";
    }
    renderOzonFbsKizTable({ skipCollect: true });
    _ozonFbsKizScheduleLocalAutosave(pn, !_ozonFbsKizNormalizeCodesList(row.kiz_codes).length);
  }

  function clearOzonFbsKizRow(postingNumber) {
    const pn = String(postingNumber || "");
    const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
    if (!row) return;
    const req = Math.max(Number(row.quantity) || 1, 1);
    row.kiz_codes = Array.from({ length: req }, () => "");
    row.kiz_status = "empty";
    delete ozonFbsKizState.errors[pn];
    renderOzonFbsKizTable();
    _ozonFbsKizScheduleLocalAutosave(pn, true);
  }

  function _ozonFbsKizScheduleLocalAutosave(postingNumber, clear) {
    const pn = String(postingNumber || "").trim();
    if (!pn) return;
    if (!ozonFbsKizState.localAutosaveSeqByPosting) ozonFbsKizState.localAutosaveSeqByPosting = {};
    const seq = (Number(ozonFbsKizState.localAutosaveSeqByPosting[pn]) || 0) + 1;
    ozonFbsKizState.localAutosaveSeqByPosting[pn] = seq;
    const run = () => _ozonFbsKizFlushLocalAutosave(pn, seq, !!clear);
    ozonFbsKizState.localAutosaveChain = (ozonFbsKizState.localAutosaveChain || Promise.resolve())
      .then(run, run)
      .catch(() => {});
  }

  async function _ozonFbsKizFlushLocalAutosave(postingNumber, seq, clear) {
    const pn = String(postingNumber || "").trim();
    if ((Number(ozonFbsKizState.localAutosaveSeqByPosting?.[pn]) || 0) !== seq) return;
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId) return;
    const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
    if (!row) return;
    const codes = (row.kiz_codes || []).map((c) => _ozonFbsNormalizeMark(c)).filter(Boolean);
    const item = {
      posting_number: pn,
      kiz_codes: codes,
      expected_saved_at: row.kiz_saved_at || "",
      force: !!(ozonFbsKizState.forceSaveByPosting && ozonFbsKizState.forceSaveByPosting[pn]),
      clear: !!clear && !codes.length,
    };
    ozonFbsKizState.localAutosaveInflight = (Number(ozonFbsKizState.localAutosaveInflight) || 0) + 1;
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking?source_id=${sourceId}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...jsonHeaders() },
          body: JSON.stringify({ items: [item] }),
          keepalive: true,
        }
      );
      if ((Number(ozonFbsKizState.localAutosaveSeqByPosting?.[pn]) || 0) !== seq) return;
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      const result = (data.results || []).find((r) => String(r.posting_number) === pn);
      if (!result || !result.ok) {
        if (result?.conflict) {
          row.kiz_saved_at = String(result.kiz_saved_at || row.kiz_saved_at || "");
          if (!ozonFbsKizState.forceSaveByPosting) ozonFbsKizState.forceSaveByPosting = {};
          ozonFbsKizState.forceSaveByPosting[pn] = true;
        }
        return;
      }
      row.kiz_saved_at = String(result.kiz_saved_at || row.kiz_saved_at || "");
      if (!ozonFbsKizState.baselineByPosting) ozonFbsKizState.baselineByPosting = {};
      ozonFbsKizState.baselineByPosting[pn] = codes.slice();
      delete ozonFbsKizState.forceSaveByPosting[pn];
      delete ozonFbsKizState.errors[pn];
    } finally {
      ozonFbsKizState.localAutosaveInflight = Math.max(
        0,
        (Number(ozonFbsKizState.localAutosaveInflight) || 1) - 1
      );
    }
  }

  function onOzonFbsKizStickerScanKey(event) {
    if (!event || event.key !== "Enter") return;
    event.preventDefault();
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) return;
    const input = event.target;
    if (input?.disabled || input?.readOnly || !ozonFbsKizState.rowsReady) return;
    const rawTyped = String(input?.value || "").replace(/\s+/g, "").trim();
    if (!rawTyped) return;
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(rawTyped)) {
      if (typeof _wbFbsKizBlockRuLayout === "function") _wbFbsKizBlockRuLayout(input);
      return;
    }
    _ozonFbsKizCollectFromDom();
    const found = _ozonFbsKizFindBySticker(rawTyped);
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
    if (typeof _wbFbsKizRuLayoutModalOpen === "function" && _wbFbsKizRuLayoutModalOpen()) return;
    const pn = String(ozonFbsKizState.pendingPosting || "");
    const input = event.target;
    const rawTyped = String(input?.value || "");
    if (!pn || !String(rawTyped || "").replace(/\s+/g, "")) return;
    if (typeof _wbFbsKizHasCyrillic === "function" && _wbFbsKizHasCyrillic(rawTyped)) {
      if (typeof _wbFbsKizBlockRuLayout === "function") _wbFbsKizBlockRuLayout(input);
      return;
    }
    const mark = _ozonFbsNormalizeMark(rawTyped);
    if (!mark) return;
    _ozonFbsKizCollectFromDom();
    const row = ozonFbsKizState.rows.find((r) => String(r.posting_number) === pn);
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
    const emptyFilter = document.getElementById("ozonFbsKizFilterEmpty");
    const emptyFilterWasOn = !!emptyFilter?.checked;
    if (emptyFilter) emptyFilter.checked = false;
    cancelOzonFbsKizMarkScan();
    const domKey = _ozonFbsPostingMenuKey(pn);
    if (emptyFilterWasOn || addedSlot) {
      renderOzonFbsKizTable({ skipCollect: true });
    } else {
      const codeInput = document.getElementById(`ozonFbsKizCode_${domKey}_${placedIdx}`);
      if (codeInput) codeInput.value = mark;
      _ozonFbsKizUpdateScanCounter();
    }
    _ozonFbsKizSetInfo(`КИЗ сохранён локально для ${pn}`, true);
    _ozonFbsKizScheduleLocalAutosave(pn, false);
    const rowEl = document.querySelector(`#ozonFbsKizTbody tr[data-posting="${pn}"]`);
    if (rowEl) rowEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function openOzonFbsKizModal() {
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady()) return;
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsKizModal", true);
    else document.getElementById("ozonFbsKizModal")?.classList.remove("hidden");
    ozonFbsKizState.rows = [];
    ozonFbsKizState.errors = {};
    ozonFbsKizState.pendingPosting = null;
    ozonFbsKizState.baselineByPosting = {};
    ozonFbsKizState.forceSaveByPosting = {};
    _ozonFbsKizSetFiltersReady(false);
    _ozonFbsKizSetInfo("");
    const tbody = document.getElementById("ozonFbsKizTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Загрузка…</td></tr>`;
    const saveBtn = document.getElementById("ozonFbsKizSaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    const scan = document.getElementById("ozonFbsKizStickerScan");
    if (scan) scan.value = "";
    let loadOk = false;
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking?${params}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      ozonFbsKizState.rows = (Array.isArray(data.rows) ? data.rows : []).map((r) => ({
        ...r,
        kiz_codes: Array.isArray(r.kiz_codes) && r.kiz_codes.length ? r.kiz_codes.slice() : [""],
      }));
      _ozonFbsKizCaptureBaseline();
      renderOzonFbsKizTable();
      if (!ozonFbsKizState.rows.length) {
        _ozonFbsKizSetInfo("В поставке нет отправлений, требующих маркировки");
      }
      loadOk = true;
    } catch (e) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
      }
      _ozonFbsKizSetInfo(String(e.message || e));
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      _ozonFbsKizSetFiltersReady(true);
      if (loadOk && scan) setTimeout(() => scan.focus(), 50);
    }
  }

  function closeOzonFbsKizModal() {
    if (typeof setModalVisibility === "function") setModalVisibility("ozonFbsKizModal", false);
    else document.getElementById("ozonFbsKizModal")?.classList.add("hidden");
    cancelOzonFbsKizMarkScan();
    ozonFbsKizState.rows = [];
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
      await ozonFbsKizState.localAutosaveChain;
      const items = (ozonFbsKizState.rows || []).map((r) => ({
        posting_number: r.posting_number,
        kiz_codes: (r.kiz_codes || []).map((c) => _ozonFbsNormalizeMark(c)).filter(Boolean),
        expected_saved_at: r.kiz_saved_at || "",
        force: !!(ozonFbsKizState.forceSaveByPosting && ozonFbsKizState.forceSaveByPosting[r.posting_number]),
      })).filter((it) => it.posting_number);
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking?source_id=${sourceId}`,
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
          if (e.posting_number) ozonFbsKizState.errors[e.posting_number] = e.error || "ошибка";
        });
        renderOzonFbsKizTable();
        _ozonFbsKizSetInfo(`Сохранено частично (${data.saved || 0}).`);
      } else {
        _ozonFbsKizSetInfo(`Сохранено локально: ${data.saved || 0} отправлений`, true);
      }
      const reload = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/marking?source_id=${sourceId}`
      );
      const reloadData = await reload.json().catch(() => ({}));
      if (reload.ok) {
        ozonFbsKizState.rows = (Array.isArray(reloadData.rows) ? reloadData.rows : []).map((r) => ({
          ...r,
          kiz_codes: Array.isArray(r.kiz_codes) && r.kiz_codes.length ? r.kiz_codes.slice() : [""],
        }));
        _ozonFbsKizCaptureBaseline();
        renderOzonFbsKizTable();
      }
      await refreshOzonFbsMarkingStatus(true);
      if (supplyDetailState.supplyId) {
        const dres = await fetch(
          `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/detail?source_id=${sourceId}`
        );
        const detail = await dres.json().catch(() => ({}));
        if (dres.ok) renderSupplyDetail(detail);
      }
    } catch (e) {
      _ozonFbsKizSetInfo(String(e.message || e));
    } finally {
      ozonFbsKizState.saving = false;
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async function refreshOzonFbsMarkingStatus(eventOrSilent) {
    const silent = eventOrSilent === true;
    if (eventOrSilent && eventOrSilent !== true) {
      eventOrSilent.preventDefault();
      eventOrSilent.stopPropagation();
    }
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId || !_ozonFbsSupplyActionsReady() || ozonFbsKizState.statusRefreshing) {
      return;
    }
    const refreshBtn = document.getElementById("ozonFbsSupplyDetailKizRefreshBtn");
    const kizBtn = document.getElementById("ozonFbsSupplyDetailKizBtn");
    const refreshGen = Number(ozonFbsKizState.statusRefreshGen || 0) + 1;
    ozonFbsKizState.statusRefreshGen = refreshGen;
    ozonFbsKizState.statusRefreshing = true;
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.classList.add("is-spinning");
    }
    if (kizBtn) kizBtn.disabled = true;
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
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
      const info = document.getElementById("ozonFbsSupplyDetailInfo");
      if (info) {
        info.hidden = true;
        info.textContent = "";
      }
      if (supplyDetailState.supply) renderSupplyDetail();
      _ozonFbsKizSplitSetTone(data.status || "");
    } catch (e) {
      if (
        supplyDetailState.supplyId === sid
        && ozonFbsKizState.statusRefreshGen === refreshGen
      ) {
        if (!silent) _ozonFbsKizSetInfo(String(e.message || e));
        const info = document.getElementById("ozonFbsSupplyDetailInfo");
        if (info && !silent) {
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
        if (kizBtn) kizBtn.disabled = false;
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

  function _ozonFbsPickFindByPosting(scan) {
    return _ozonFbsPickFindBySticker(scan);
  }

  function _ozonFbsPickUpdateScanCounter() {
    const el = document.getElementById("ozonFbsPickScanCount");
    if (!el) return;
    let filled = 0;
    const total = ozonFbsPickState.rows.length;
    for (const row of ozonFbsPickState.rows) {
      if (row.pick_verified && String(row.pick_barcode || "").trim()) filled += 1;
    }
    el.textContent = `Проверено ${filled} из ${total}`;
  }

  function _ozonFbsPickStatusHtml(row) {
    const pn = String(row.posting_number || "");
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
        ...(Array.isArray(r.barcodes) ? r.barcodes : []),
      ].map((x) => String(x || "").toLowerCase()).join(" ");
      return hay.includes(q);
    });
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="3" class="wb-fbs-empty">${
        ozonFbsPickState.rows?.length ? "Нет строк по фильтру" : "Нет отправлений без маркировки"
      }</td></tr>`;
      _ozonFbsPickUpdateScanCounter();
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const pn = String(r.posting_number || "");
      const safePn = esc(pn);
      const stickerHtml = _ozonFbsKizStickerHtml(r);
      const photo = r.product_photo
        ? `<img class="wb-fbs-product-photo" src="${esc(r.product_photo)}" alt="" width="56" height="56" loading="lazy">`
        : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
      const barcodes = Array.isArray(r.barcodes) ? r.barcodes : [];
      const barcodeHtml = barcodes.length
        ? `<div class="wb-fbs-kiz-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
            `<div class="wb-fbs-kiz-barcode">${esc(b)}</div>`
          ).join("")}</div>`
        : "";
      return `<tr class="wb-fbs-kiz-row${pending === pn ? " is-active" : ""}" data-posting="${safePn}">
        <td>
          <div class="wb-fbs-kiz-order-id">${formatOzonPostingNumberHtml(pn)}</div>
          <div class="wb-fbs-kiz-order-sticker">${stickerHtml}</div>
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
      </tr>`;
    }).join("");
    _ozonFbsPickUpdateScanCounter();
  }

  function clearOzonFbsPickVerify(postingNumber) {
    const pn = String(postingNumber || "");
    const row = ozonFbsPickState.rows.find((r) => String(r.posting_number) === pn);
    if (!row) return;
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
    if (!row) return;
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

  function onOzonFbsPickStickerScanKey(event) {
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
    const scan = _ozonFbsNormalizeScan(rawTyped);
    if (!scan) return;
    const found = _ozonFbsPickFindBySticker(scan);
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
    ozonFbsPickState.rows = [];
    ozonFbsPickState.errors = {};
    ozonFbsPickState.pendingPosting = null;
    _ozonFbsPickSetFiltersReady(false);
    _ozonFbsPickSetInfo("");
    const tbody = document.getElementById("ozonFbsPickTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="3" class="wb-fbs-empty">Загрузка…</td></tr>`;
    const saveBtn = document.getElementById("ozonFbsPickVerifySaveBtn");
    if (saveBtn) saveBtn.disabled = true;
    const scan = document.getElementById("ozonFbsPickStickerScan");
    if (scan) scan.value = "";
    let loadOk = false;
    try {
      const params = new URLSearchParams({ source_id: String(sourceId) });
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/pick-verify?${params}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || `Ошибка ${res.status}`);
      ozonFbsPickState.rows = Array.isArray(data.rows) ? data.rows.map((r) => ({ ...r })) : [];
      renderOzonFbsPickVerifyTable();
      if (!ozonFbsPickState.rows.length) {
        _ozonFbsPickSetInfo("В поставке нет отправлений без маркировки", true);
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
      const items = (ozonFbsPickState.rows || []).map((r) => {
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
  window.closeOzonFbsSyncInfo = closeSyncInfo;
  window.openOzonFbsDetail = openDetail;
  window.closeOzonFbsDetailModal = closeDetailModal;
  window.ozonFbsShipCurrent = shipCurrent;
  window.ozonFbsShipAll = shipAll;
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
  window.confirmOzonFbsCollect = confirmCollect;
  window.ozonFbsCollectNameInput = collectNameInput;

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
  window.ozonFbsShipmentsPrintBarcode = shipmentsPrintBarcode;
  window.ozonFbsShipmentsDownloadBarcode = shipmentsDownloadBarcode;
  window.toggleOzonFbsRowMenu = toggleOzonFbsRowMenu;
  window.closeOzonFbsRowMenus = closeOzonFbsRowMenus;
  window.ozonFbsPrintOnePostingStickerFromDetail = printOnePostingStickerFromDetail;
  window.openOzonFbsCancelledOrdersModal = openOzonFbsCancelledOrdersModal;
  window.closeOzonFbsCancelledOrdersModal = closeOzonFbsCancelledOrdersModal;
  window.refreshOzonFbsCancelledOrders = refreshOzonFbsCancelledOrders;
  window.openOzonFbsKizModal = openOzonFbsKizModal;
  window.closeOzonFbsKizModal = closeOzonFbsKizModal;
  window.saveOzonFbsKizModal = saveOzonFbsKizModal;
  window.renderOzonFbsKizTable = renderOzonFbsKizTable;
  window.onOzonFbsKizCodeInput = onOzonFbsKizCodeInput;
  window.onOzonFbsKizCodeBlur = onOzonFbsKizCodeBlur;
  window.onOzonFbsKizCodeKey = onOzonFbsKizCodeKey;
  window.addOzonFbsKizCode = addOzonFbsKizCode;
  window.removeOzonFbsKizCode = removeOzonFbsKizCode;
  window.onOzonFbsKizFilterFilledChange = onOzonFbsKizFilterFilledChange;
  window.onOzonFbsKizFilterEmptyChange = onOzonFbsKizFilterEmptyChange;
  window.onOzonFbsKizStickerScanKey = onOzonFbsKizStickerScanKey;
  window.onOzonFbsKizMarkScanKey = onOzonFbsKizMarkScanKey;
  window.cancelOzonFbsKizMarkScan = cancelOzonFbsKizMarkScan;
  window.clearOzonFbsKizRow = clearOzonFbsKizRow;
  window.refreshOzonFbsMarkingStatus = refreshOzonFbsMarkingStatus;
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
