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
    search: "",
    searchTimer: null,
    syncPollTimer: null,
    detailPosting: null,
    detailPayload: null,
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
  }

  function renderTable(items) {
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (!tbody) return;
    if (!items || !items.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Нет отправлений в этой вкладке</td></tr>`;
      return;
    }
    tbody.innerHTML = items.map((row) => {
      const pn = esc(row.posting_number || "");
      const product = esc(row.product_name_display || row.product_name || "—");
      const wh = esc(row.warehouse_label || row.warehouse_name || "—");
      const price = esc(row.price_display || "—");
      const photo = row.product_photo
        ? `<img class="wb-fbs-product-thumb" src="${esc(row.product_photo)}" alt="" />`
        : `<span class="wb-fbs-product-thumb wb-fbs-product-thumb--empty"></span>`;
      return `
        <tr class="wb-fbs-order-row" data-posting="${pn}" onclick="openOzonFbsDetail('${pn}')">
          <td><div class="wb-fbs-order-cell"><strong>${pn}</strong><div class="small" style="color:#64748b">${esc(row.order_number || "")}</div></div></td>
          <td><div class="wb-fbs-product-cell">${photo}<div><div>${product}</div><div class="small" style="color:#64748b">${esc(row.offer_id || "")} · ${price}</div></div></div></td>
          <td>${wh}</td>
          <td class="wb-fbs-th-act"><button type="button" class="icon-btn secondary" title="Открыть" onclick="event.stopPropagation();openOzonFbsDetail('${pn}')">⋯</button></td>
        </tr>`;
    }).join("");
  }

  async function loadPostings(resetPage) {
    if (!canView()) return;
    if (resetPage) state.page = 1;
    const tbody = document.getElementById("ozonFbsOrdersTbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Загрузка…</td></tr>`;
    if (!state.sourceId) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Добавьте источник OZON ФБС в настройках</td></tr>`;
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
      const maxPage = Math.max(1, Math.ceil(state.total / state.pageSize));
      if (pageInfo) pageInfo.textContent = `Стр. ${state.page} / ${maxPage}`;
      const prev = document.getElementById("ozonFbsPrevBtn");
      const next = document.getElementById("ozonFbsNextBtn");
      if (prev) prev.disabled = state.page <= 1;
      if (next) next.disabled = state.page >= maxPage;
    } catch (e) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty" style="color:#b91c1c">${esc(e.message)}</td></tr>`;
    }
  }

  async function initSection() {
    if (!canView()) return;
    await loadSources();
    await loadPostings(true);
  }

  function setTab(tab) {
    state.tab = String(tab || "awaiting_packaging");
    document.querySelectorAll("#ozonFbsTabs .wb-fbs-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === state.tab);
    });
    loadPostings(true);
  }

  function onSourceChange() {
    const sel = document.getElementById("ozonFbsSourceSelect");
    state.sourceId = sel?.value ? Number(sel.value) : null;
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
  window.ozonFbsPrintCurrentSticker = printCurrentSticker;
})();
