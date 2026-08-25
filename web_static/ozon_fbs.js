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

  /** Ozon sticker: middle 4 digits in ORDER-XXXX-PKG are largest on the label. */
  function formatOzonPostingNumberHtml(postingNumber) {
    const s = String(postingNumber || "").trim();
    if (!s) return "—";
    const parts = s.split("-");
    if (parts.length >= 3 && /^\d{4}$/.test(parts[1])) {
      const head = `${esc(parts[0])}-`;
      const tail = `-${parts.slice(2).map((p) => esc(p)).join("-")}`;
      return `${head}<span class="ozon-fbs-posting-tail">${esc(parts[1])}</span>${tail}`;
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
      return `${esc(s.slice(0, cut))}<span class="ozon-fbs-posting-tail">${esc(s.slice(cut))}</span>`;
    }
    if (s.length > 4) {
      return `${esc(s.slice(0, -4))}<span class="ozon-fbs-posting-tail">${esc(s.slice(-4))}</span>`;
    }
    return `<span class="ozon-fbs-posting-tail">${esc(s)}</span>`;
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
    return state.tab === "awaiting_deliver";
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
      tbody.innerHTML = `<tr><td colspan="${colspan()}" class="wb-fbs-empty">Нет локальных поставок. Соберите заказы синей кнопкой на вкладке «Ожидают сборки».</td></tr>`;
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
          showSyncInfo(
            names.length
              ? `Оформлено ${adopted} отпр. без поставки → ${names.join(", ")}`
              : `Оформлено ${adopted} отправлений без поставки в локальные поставки`
          );
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

  function printOnePostingStickerFromDetail(postingNumber) {
    closeOzonFbsRowMenus();
    const pn = String(postingNumber || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!pn || !sourceId) return;
    const url =
      `/api/ozon-fbs/postings/stickers-print?source_id=${sourceId}` +
      `&posting_numbers=${encodeURIComponent(pn)}`;
    const win = window.open(url, "_blank");
    if (!win) alert("Разрешите всплывающие окна для стикера");
  }

  function renderSupplyDetail(data) {
    const supply = data || supplyDetailState.supply;
    if (!supply) return;
    if (data) supplyDetailState.supply = data;
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
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">В поставке нет отправлений</td></tr>`;
      return;
    }
    if (!orders.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Нет отправлений по выбранному фильтру</td></tr>`;
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
      const menuKey = _ozonFbsPostingMenuKey(pn);
      return `<tr class="wb-fbs-sd-click-row">
        <td><input type="checkbox" class="wb-fbs-sd-cb" data-posting="${esc(pn)}" ${checked}
                   onchange="onOzonFbsSupplyDetailCheckboxChange()" /></td>
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
            </div>
          </div>
        </td>
        <td class="wb-fbs-sd-col-act">
          <div class="wb-fbs-row-menu-wrap" id="ozonFbsRowMenuWrap_${menuKey}">
            <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
                    onclick="toggleOzonFbsRowMenu(event, '${menuKey}')" aria-haspopup="menu">⋮</button>
            <div id="ozonFbsRowMenu_${menuKey}" class="wb-fbs-row-menu" data-posting="${esc(pn)}" role="menu">
              <button type="button" class="wb-fbs-row-menu-item" role="menuitem"
                      onclick="ozonFbsPrintOnePostingStickerFromDetail(${JSON.stringify(pn)})">
                Напечатать стикер
              </button>
            </div>
          </div>
        </td>
      </tr>`;
    }).join("");
    syncSupplyDetailSelectAll();
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
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Загрузка…</td></tr>`;
    if (modal) modal.classList.remove("hidden");
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/detail?source_id=${state.sourceId}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Не найдено");
      renderSupplyDetail(data);
    } catch (e) {
      if (title) title.textContent = "Ошибка";
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
      }
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

  function closeStickersByCategoryModal() {
    document.getElementById("ozonFbsStickersCategoryModal")?.classList.add("hidden");
    stickersCategoryState.groups = [];
    stickersCategoryState.selected = new Set();
    stickersCategoryState.loading = false;
  }

  function renderStickersByCategory() {
    const body = document.getElementById("ozonFbsStickersCategoryBody");
    if (!body) return;
    const groups = stickersCategoryState.groups || [];
    if (stickersCategoryState.loading) {
      body.innerHTML = `<div class="wb-fbs-empty">Загрузка…</div>`;
      return;
    }
    if (!groups.length) {
      body.innerHTML = `<div class="wb-fbs-empty">Нет товаров для печати</div>`;
      return;
    }
    body.innerHTML = groups.map((g, idx) => {
      const key = String(g.group_key || "");
      const checked = stickersCategoryState.selected.has(key) ? "checked" : "";
      const name = String(g.product_name || g.article || "—");
      const qty = Number(g.qty || 0);
      return `<label class="wb-fbs-collect-mgt-supply" style="display:flex;gap:12px;align-items:flex-start;padding:8px 0">
        <input type="checkbox" data-group-key="${esc(key)}" ${checked}
               onchange="onOzonFbsStickersCategoryToggle('${esc(key)}', this.checked)" />
        <span>
          <span class="wb-fbs-collect-mgt-supply-name">${esc(name)} — ${esc(qty)} шт.</span>
          <span class="wb-fbs-collect-mgt-supply-meta">Арт. ${esc(g.article || "—")}</span>
        </span>
      </label>`;
    }).join("");
  }

  function onStickersCategoryToggle(key, checked) {
    const k = String(key || "");
    if (!k) return;
    if (checked) stickersCategoryState.selected.add(k);
    else stickersCategoryState.selected.delete(k);
  }

  async function openStickersByCategoryModal() {
    closeStickersMenu();
    const sid = String(supplyDetailState.supplyId || "").trim();
    const sourceId = supplyDetailState.sourceId || state.sourceId;
    if (!sid || !sourceId) return;
    stickersCategoryState.loading = true;
    stickersCategoryState.groups = [];
    stickersCategoryState.selected = new Set();
    document.getElementById("ozonFbsStickersCategoryModal")?.classList.remove("hidden");
    renderStickersByCategory();
    try {
      const res = await fetch(
        `/api/ozon-fbs/supplies/${encodeURIComponent(sid)}/sticker-groups?source_id=${sourceId}`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detailText(data.detail) || "Ошибка");
      stickersCategoryState.groups = Array.isArray(data.groups) ? data.groups : [];
      stickersCategoryState.selected = new Set(
        stickersCategoryState.groups.map((g) => String(g.group_key || "")).filter(Boolean)
      );
    } catch (e) {
      alert(e.message || String(e));
      closeStickersByCategoryModal();
      return;
    } finally {
      stickersCategoryState.loading = false;
      renderStickersByCategory();
    }
  }

  function confirmStickersByCategory() {
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
    if (!nums.length) {
      alert("Выберите хотя бы одну категорию");
      return;
    }
    closeStickersByCategoryModal();
    openStickersPrint(nums);
  }

  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    if (!t.closest("#ozonFbsPickingSplit")) closePickingMenu();
    if (!t.closest("#ozonFbsStickersSplit")) closeStickersMenu();
    if (!t.closest(".wb-fbs-row-menu-wrap") && !t.closest("[id^='ozonFbsRowMenu_'].wb-fbs-row-menu")) {
      closeOzonFbsRowMenus();
    }
  });

  async function initSection() {
    if (!canView()) return;
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
  function showSyncInfo(text, kind = "", palletSummary = null, sourceRows = null) {
    const info = document.getElementById("ozonFbsSyncInfo");
    if (!info) return;
    const msg = String(text || "").trim();
    const textEl = document.getElementById("ozonFbsSyncInfoText");
    const palletsEl = document.getElementById("ozonFbsSyncInfoPallets");
    const rowsSrc = Array.isArray(sourceRows) ? sourceRows : [];

    if (textEl) {
      if (rowsSrc.length) {
        textEl.innerHTML = rowsSrc.map((row) => {
          const name = esc(row?.name || `Источник ${row?.source_id || ""}`);
          const line = esc(row?.message || "");
          const st = String(row?.status || "");
          let cls = "wb-fbs-sync-info-source-row";
          if (st === "error") cls += " is-error";
          else if (st === "done") cls += " is-ok";
          else if (st === "stopped") cls += " is-stopped";
          return `<div class="${cls}"><span class="wb-fbs-sync-info-source-name">${name}</span>: ${line}</div>`;
        }).join("");
      } else {
        textEl.textContent = msg;
      }
    }

    const rows = Array.isArray(palletSummary) ? palletSummary : [];
    if (palletsEl) {
      if (rows.length && (kind === "ok" || /готово/i.test(msg))) {
        palletsEl.innerHTML = rows.map((row) => {
          const name = esc(row?.name || `Источник ${row?.source_id || ""}`);
          const label = esc(
            row?.pallets_label
            || `${Number(row?.pallets || 0).toFixed(2).replace(".", ",")} паллета`
          );
          return `<div class="wb-fbs-sync-info-pallet-row">${name} — ${label}</div>`;
        }).join("");
        palletsEl.hidden = false;
      } else {
        palletsEl.innerHTML = "";
        palletsEl.hidden = true;
      }
    }

    info.hidden = !(msg || rowsSrc.length);
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
      const sourceRows = (running && Array.isArray(st.sources) && st.sources.length)
        ? st.sources
        : null;
      if (sourceRows) showSyncInfo(text, kind, null, sourceRows);
      else if (text) showSyncInfo(text, kind, pallets);
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

  function fillShipmentsMethods(methods, selectedId) {
    const sel = document.getElementById("ozonFbsShipmentsMethod");
    if (!sel) return;
    const list = Array.isArray(methods) ? methods : [];
    if (!list.length) {
      sel.innerHTML = `<option value="">Нет активных методов</option>`;
      return;
    }
    sel.innerHTML = list.map((m) => {
      const id = String(m.id ?? "");
      const name = esc(m.name || `Метод ${id}`);
      const selected = String(selectedId ?? "") === id ? " selected" : "";
      return `<option value="${esc(id)}"${selected}>${name}</option>`;
    }).join("");
  }

  function renderShipmentsBarcode(data) {
    const barcode = data?.barcode || null;
    const whName = esc(data?.warehouse_name || "склада");
    const help = esc(data?.barcode_help || "");
    const text = String(barcode?.barcode_text || "").trim();
    const b64 = String(barcode?.barcode_image_base64 || "").trim();
    const ctype = String(barcode?.content_type || "image/png").trim() || "image/png";
    const hasImg = Boolean(b64);
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
            <button type="button" class="ozon-fbs-shipments-icon-btn" ${hasImg ? "" : "disabled"}
                    onclick="ozonFbsShipmentsZoomBarcode()" title="Открыть" aria-label="Открыть штрихкод">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2"/>
                <path d="M20 20l-3.5-3.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                <path d="M11 8v6M8 11h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
              </svg>
            </button>
            <button type="button" class="ozon-fbs-shipments-icon-btn" ${hasImg || text ? "" : "disabled"}
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
          <p class="ozon-fbs-shipments-barcode-help">${help}</p>
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
      fillShipmentsMethods(data.delivery_methods, data.selected_delivery_method_id);
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
      fillShipmentsMethods(data.delivery_methods, data.selected_delivery_method_id);
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

  function shipmentsZoomBarcode() {
    const img = document.getElementById("ozonFbsShipmentsBarcodeImg");
    if (!img?.src) return;
    window.open(img.src, "_blank", "noopener,noreferrer");
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
  window.confirmOzonFbsStickersByCategory = confirmStickersByCategory;
  window.onOzonFbsStickersCategoryToggle = onStickersCategoryToggle;
  window.openOzonFbsShipmentsModal = openShipmentsModal;
  window.closeOzonFbsShipmentsModal = closeShipmentsModal;
  window.reloadOzonFbsShipments = loadShipments;
  window.ozonFbsShipmentsForm = formShipmentsCarriage;
  window.ozonFbsShipmentsZoomBarcode = shipmentsZoomBarcode;
  window.ozonFbsShipmentsDownloadBarcode = shipmentsDownloadBarcode;
  window.toggleOzonFbsRowMenu = toggleOzonFbsRowMenu;
  window.closeOzonFbsRowMenus = closeOzonFbsRowMenus;
  window.ozonFbsPrintOnePostingStickerFromDetail = printOnePostingStickerFromDetail;
})();
