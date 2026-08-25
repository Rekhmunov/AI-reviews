/**
 * OZON FBS section — isolated from WB FBS and Ozon FBO.
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
  };

  const COLSPAN = 4;

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
    btn.disabled = !state.sourceId || n <= 0 || Boolean(state.shipAllBusy);
    btn.title = n > 0
      ? `Собрать все отправления в «Ожидают сборки» (${n}) через Ozon /v4/posting/fbs/ship`
      : "Нет отправлений в «Ожидают сборки»";
  }

  function syncSelectAll() {
    const selAll = document.getElementById("ozonFbsSelectAll");
    if (!selAll) return;
    const ids = state.items.map((x) => String(x.posting_number || "").trim()).filter(Boolean);
    const allOnPage = ids.length > 0 && ids.every((id) => state.selected.has(id));
    const someOnPage = ids.some((id) => state.selected.has(id));
    selAll.checked = allOnPage;
    selAll.indeterminate = !allOnPage && someOnPage;
  }

  function onCheckboxChange() {
    document.querySelectorAll("#ozonFbsOrdersTable .wb-fbs-row-cb").forEach((cb) => {
      const pn = String(cb.dataset.posting || "").trim();
      if (!pn) return;
      if (cb.checked) state.selected.add(pn);
      else state.selected.delete(pn);
    });
    syncSelectAll();
  }

  function toggleSelectAll(checked) {
    document.querySelectorAll("#ozonFbsOrdersTable .wb-fbs-row-cb").forEach((cb) => {
      cb.checked = !!checked;
      const pn = String(cb.dataset.posting || "").trim();
      if (!pn) return;
      if (checked) state.selected.add(pn);
      else state.selected.delete(pn);
    });
    const selAll = document.getElementById("ozonFbsSelectAll");
    if (selAll) selAll.indeterminate = false;
  }

  function renderTable(items) {
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (!tbody) return;
    state.items = Array.isArray(items) ? items : [];
    if (!state.items.length) {
      tbody.innerHTML = `<tr><td colspan="${COLSPAN}" class="wb-fbs-empty">Нет отправлений в этой вкладке</td></tr>`;
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
        <div class="wb-fbs-order-id">${pn}</div>
        <div class="wb-fbs-order-meta">от ${esc(fmtDate(created))}</div>
        ${badges.length ? `<div class="wb-fbs-badges">${badges.join("")}</div>` : ""}
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
  }

  async function loadPostings(resetPage) {
    if (!canView()) return;
    if (resetPage) state.page = 1;
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="${COLSPAN}" class="wb-fbs-empty">Загрузка…</td></tr>`;
    if (!state.sourceId) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="${COLSPAN}" class="wb-fbs-empty">Добавьте источник OZON ФБС в настройках</td></tr>`;
      return;
    }
    const params = new URLSearchParams({
      source_id: String(state.sourceId),
      tab: state.tab,
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    if (state.search) params.set("search", state.search);
    try {
      const res = await fetch(`/api/ozon-fbs/postings?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Ошибка загрузки");
      state.total = Number(data.total || 0);
      updateTabCounts(data.counts || {});
      renderTable(data.items || []);
      const info = document.getElementById("ozonFbsInfo");
      if (info) info.textContent = `Всего: ${state.total}`;
      const pageInfo = document.getElementById("ozonFbsPageInfo");
      const maxPage = Math.max(1, Math.ceil(state.total / state.pageSize) || 1);
      if (pageInfo) pageInfo.textContent = `Стр. ${state.page} / ${maxPage}`;
      const prev = document.getElementById("ozonFbsPrevBtn");
      const next = document.getElementById("ozonFbsNextBtn");
      if (prev) prev.disabled = state.page <= 1;
      if (next) next.disabled = state.page >= maxPage;
    } catch (e) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="${COLSPAN}" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
      }
    }
  }

  const COL_WIDTHS_PREFIX = "ozon_fbs_col_widths_v2";
  const DEFAULT_WIDTHS = [24, 56, 20]; // order, product, warehouse — same as WB FBS
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
    if (!table) return;

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

  async function shipAll() {
    if (!state.sourceId || state.shipAllBusy) return;
    const n = Number(state.counts.awaiting_packaging || 0);
    if (n <= 0) {
      alert("Нет отправлений в «Ожидают сборки»");
      return;
    }
    const okConfirm = window.confirm(
      `Собрать все заказы (${n})?\n\nКаждое отправление будет собрано через Ozon API /v4/posting/fbs/ship и перейдёт во вкладку «Ожидают отгрузки».`
    );
    if (!okConfirm) return;
    state.shipAllBusy = true;
    syncShipAllButton();
    const btn = document.getElementById("ozonFbsShipAllBtn");
    if (btn) btn.textContent = "Сборка…";
    showSyncInfo("Сборка отправлений…");
    try {
      const res = await fetch(`/api/ozon-fbs/ship-all?source_id=${state.sourceId}`, {
        method: "POST",
        headers: jsonHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Ошибка сборки");
      const msg = String(data.message || "Готово");
      showSyncInfo(msg);
      if (data.failed && Array.isArray(data.errors) && data.errors.length) {
        const lines = data.errors
          .slice(0, 12)
          .map((e) => `${e.posting_number}: ${e.error}`)
          .join("\n");
        alert(`${msg}\n\n${lines}${data.errors.length > 12 ? "\n…" : ""}`);
      } else {
        alert(msg);
      }
      await loadPostings(false);
    } catch (e) {
      const err = e.message || "Ошибка";
      showSyncInfo(err);
      alert(err);
    } finally {
      state.shipAllBusy = false;
      if (btn) btn.textContent = "Собрать все заказы";
      syncShipAllButton();
    }
  }

  async function initSection() {
    if (!canView()) return;
    initColumnResizer();
    await loadSources();
    await loadPostings(true);
    syncShipAllButton();
  }

  function setTab(tab) {
    state.tab = String(tab || "awaiting_packaging");
    state.selected.clear();
    document.querySelectorAll("#ozonFbsTabs .wb-fbs-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === state.tab);
    });
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
    if (box) box.hidden = true;
  }

  function showSyncInfo(text) {
    const box = document.getElementById("ozonFbsSyncInfo");
    const txt = document.getElementById("ozonFbsSyncInfoText");
    if (txt) txt.textContent = text || "";
    if (box) box.hidden = !text;
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
      const data = await res.json();
      const running = Boolean(data.in_progress);
      setSyncUi(running);
      if (data.message) showSyncInfo(String(data.message));
      if (running) {
        state.syncPollTimer = setTimeout(pollSyncStatus, 1500);
      } else {
        clearTimeout(state.syncPollTimer);
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
        showSyncInfo(data.message || data.detail || "Ошибка синхронизации");
        setSyncUi(false);
        return;
      }
      showSyncInfo(data.message || "Синхронизация запущена");
      pollSyncStatus();
    } catch (e) {
      showSyncInfo("Ошибка сети");
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
    if (title) title.textContent = `Отправление ${postingNumber}`;
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
})();
