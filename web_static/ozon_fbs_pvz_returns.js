/* Ozon FBS «Возвраты ПВЗ». Loaded after app.js. */

const ozonFbsPvzState = {
  sources: [],
  categories: [],
  items: [],
  syncing: false,
  pollToken: 0,
};

const _ozonFbsPvzCal = {
  viewYear: new Date().getFullYear(),
  viewMonth: new Date().getMonth(),
  startDate: null,
  endDate: null,
  hoveredDate: null,
};

const OZON_FBS_PVZ_COL_WIDTHS_PREFIX = "ozon_fbs_pvz_col_widths_v1";
const OZON_FBS_PVZ_DEFAULT_WIDTHS = [22, 58, 20]; // issued, product, qty (act is fixed)
let _ozonFbsPvzColResizerInited = false;

function _ozonFbsPvzColWidthsKey() {
  const email = String(document.querySelector(".sidebar-user-email")?.textContent || "").trim().toLowerCase();
  return email ? `${OZON_FBS_PVZ_COL_WIDTHS_PREFIX}:${email}` : OZON_FBS_PVZ_COL_WIDTHS_PREFIX;
}

function _ozonFbsPvzResizableCols() {
  return Array.from(document.querySelectorAll("#ozonFbsPvzColgroup col")).filter((c) => !c.dataset.fixed);
}

function _applyOzonFbsPvzColWidths(widths) {
  _ozonFbsPvzResizableCols().forEach((col, i) => {
    if (widths[i] !== undefined) col.style.width = `${widths[i]}%`;
  });
}

function _getOzonFbsPvzColWidths() {
  return _ozonFbsPvzResizableCols().map((col, i) => parseFloat(col.style.width) || OZON_FBS_PVZ_DEFAULT_WIDTHS[i] || 10);
}

function _restoreOzonFbsPvzColWidths() {
  let widths = OZON_FBS_PVZ_DEFAULT_WIDTHS.slice();
  try {
    const saved = JSON.parse(localStorage.getItem(_ozonFbsPvzColWidthsKey()) || "null");
    if (Array.isArray(saved) && saved.length === widths.length) widths = saved;
    else if (Array.isArray(saved)) localStorage.removeItem(_ozonFbsPvzColWidthsKey());
  } catch (_) { /* ignore */ }
  _applyOzonFbsPvzColWidths(widths);
}

function initOzonFbsPvzColumnResizer() {
  const table = document.getElementById("ozonFbsPvzTable");
  if (!table) return;
  _restoreOzonFbsPvzColWidths();
  if (_ozonFbsPvzColResizerInited) return;
  _ozonFbsPvzColResizerInited = true;

  let startX = 0;
  let colIdx = 0;
  let startWidths = [];
  let activeHandle = null;

  function onMouseMove(e) {
    const tableEl = document.getElementById("ozonFbsPvzTable");
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
    _applyOzonFbsPvzColWidths(newWidths);
  }

  function onMouseUp() {
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    if (activeHandle) activeHandle.classList.remove("dragging");
    activeHandle = null;
    try {
      localStorage.setItem(_ozonFbsPvzColWidthsKey(), JSON.stringify(_getOzonFbsPvzColWidths()));
    } catch (_) { /* ignore */ }
  }

  table.addEventListener("mousedown", (e) => {
    const handle = e.target?.closest?.(".col-resize-handle");
    if (!handle) return;
    e.preventDefault();
    e.stopPropagation();
    const th = handle.parentElement;
    colIdx = parseInt(th.getAttribute("data-col") || "0", 10);
    startX = e.clientX;
    startWidths = _getOzonFbsPvzColWidths();
    activeHandle = handle;
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    handle.classList.add("dragging");
  });
}
window.initOzonFbsPvzColumnResizer = initOzonFbsPvzColumnResizer;

function _ozonFbsPvzEsc(value) {
  if (typeof _wbFbsEsc === "function") return _wbFbsEsc(value);
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _ozonFbsPvzApiError(res, payload, fallback) {
  if (typeof _wbFbsKizCircApiError === "function") {
    return _wbFbsKizCircApiError(res, payload, fallback);
  }
  const detail = payload && payload.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  return fallback;
}

function _ozonFbsPvzTodayIso() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function _ozonFbsPvzParseIso(iso) {
  const parts = String(iso || "").split("-").map((n) => Number(n));
  if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return null;
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  date.setHours(0, 0, 0, 0);
  return date;
}

function _ozonFbsPvzFmtIso(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function _ozonFbsPvzSpanDays(a, b) {
  const ms = Math.abs(b.getTime() - a.getTime());
  return Math.round(ms / 86400000) + 1;
}

function _ozonFbsPvzSetInfo(text, kind) {
  const el = document.getElementById("ozonFbsPvzInfo");
  if (!el) return;
  const msg = String(text || "").trim();
  el.textContent = msg;
  el.hidden = !msg;
  el.classList.toggle("is-error", kind === "error" || kind === "warn");
}

function _ozonFbsPvzHeaders() {
  const base = typeof jsonHeaders === "function" ? jsonHeaders() : {};
  return { ...base, "Content-Type": "application/json" };
}

function _ozonFbsPvzEnsureDates() {
  const from = document.getElementById("ozonFbsPvzDateFrom");
  const to = document.getElementById("ozonFbsPvzDateTo");
  if (from?.value && to?.value && _ozonFbsPvzCal.startDate && _ozonFbsPvzCal.endDate) {
    _ozonFbsPvzUpdateDateBtn();
    return;
  }
  const today = _ozonFbsPvzParseIso(_ozonFbsPvzTodayIso());
  _ozonFbsPvzCal.startDate = today;
  _ozonFbsPvzCal.endDate = today ? new Date(today.getTime()) : null;
  _ozonFbsPvzCal.viewYear = today ? today.getFullYear() : new Date().getFullYear();
  _ozonFbsPvzCal.viewMonth = today ? today.getMonth() : new Date().getMonth();
  if (from && today) from.value = _ozonFbsPvzFmtIso(today);
  if (to && today) to.value = _ozonFbsPvzFmtIso(today);
  _ozonFbsPvzUpdateDateBtn();
}

/** Apply issue-date bounds after sync (last 31 days). Does not reload the table. */
function _ozonFbsPvzSetIssueDates(fromIso, toIso) {
  const start = _ozonFbsPvzParseIso(fromIso);
  const end = _ozonFbsPvzParseIso(toIso);
  if (!start || !end) return false;
  let from = start;
  let to = end;
  if (to < from) {
    from = end;
    to = start;
  }
  _ozonFbsPvzCal.startDate = from;
  _ozonFbsPvzCal.endDate = new Date(to.getTime());
  _ozonFbsPvzCal.viewYear = to.getFullYear();
  _ozonFbsPvzCal.viewMonth = to.getMonth();
  const fromEl = document.getElementById("ozonFbsPvzDateFrom");
  const toEl = document.getElementById("ozonFbsPvzDateTo");
  if (fromEl) fromEl.value = _ozonFbsPvzFmtIso(from);
  if (toEl) toEl.value = _ozonFbsPvzFmtIso(to);
  _ozonFbsPvzUpdateDateBtn();
  return true;
}

function _ozonFbsPvzUpdateDateBtn() {
  const btn = document.getElementById("ozonFbsPvzDateBtn");
  if (!btn) return;
  // Icon only — selected range lives in the tooltip.
  btn.textContent = "📅";
  const start = _ozonFbsPvzCal.startDate;
  const end = _ozonFbsPvzCal.endDate;
  if (!start || !end) {
    btn.title = "Дата выдачи";
    btn.setAttribute("aria-label", "Дата выдачи");
    return;
  }
  const fmt = (d) => d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
  const range = start.getTime() === end.getTime()
    ? fmt(start)
    : `${fmt(start)}–${fmt(end)}`;
  btn.title = `Дата выдачи: ${range}`;
  btn.setAttribute("aria-label", `Дата выдачи: ${range}`);
}

function _ozonFbsPvzFiltersAreActive() {
  // Only filters that live in the filter panel (category) light up the icon.
  const category = String(document.getElementById("ozonFbsPvzCategoryFilter")?.value || "");
  return Boolean(category);
}

function _ozonFbsPvzSyncFilterBtnState() {
  const btn = document.getElementById("ozonFbsPvzFilterBtn");
  const panel = document.getElementById("ozonFbsPvzFilterPanel");
  if (!btn) return;
  const open = !!(panel && !panel.hidden);
  btn.classList.toggle("is-open", open);
  btn.classList.toggle("is-active", _ozonFbsPvzFiltersAreActive());
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}

function toggleOzonFbsPvzFilterPanel(show) {
  const panel = document.getElementById("ozonFbsPvzFilterPanel");
  const btn = document.getElementById("ozonFbsPvzFilterBtn");
  if (!panel || !btn || ozonFbsPvzState.syncing) return;
  const willOpen = show === undefined ? panel.hidden : Boolean(show);
  if (!willOpen) {
    toggleOzonFbsPvzDatePanel(false);
  }
  panel.hidden = !willOpen;
  _ozonFbsPvzSyncFilterBtnState();
  if (willOpen) {
    const category = document.getElementById("ozonFbsPvzCategoryFilter");
    if (category && typeof category.focus === "function") {
      setTimeout(() => category.focus(), 0);
    }
  }
}
window.toggleOzonFbsPvzFilterPanel = toggleOzonFbsPvzFilterPanel;

function _ozonFbsPvzCalRender() {
  const container = document.getElementById("ozonFbsPvzCalendar");
  if (!container) return;
  const months = (typeof _calMonths !== "undefined" && _calMonths) || [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
  ];
  const days = (typeof _calDays !== "undefined" && _calDays) || ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  const { viewYear: y, viewMonth: m, startDate: s, endDate: e, hoveredDate: h } = _ozonFbsPvzCal;
  const firstDay = new Date(y, m, 1);
  const lastDay = new Date(y, m + 1, 0);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const todayIso = _ozonFbsPvzTodayIso();
  const fmtDisp = (d) => (d
    ? `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`
    : "");
  let html = `<div class="cal-header" onclick="event.stopPropagation()">
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_ozonFbsPvzCalPrevMonth()">◄</button>
    <span class="cal-title">${months[m]} ${y}</span>
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_ozonFbsPvzCalNextMonth()">►</button>
  </div>
  <div class="cal-grid" onmouseleave="_ozonFbsPvzCalClearHover()">`;
  days.forEach((d) => { html += `<div class="cal-cell cal-dow">${d}</div>`; });
  for (let i = 0; i < startOffset; i += 1) html += `<div class="cal-cell cal-empty"></div>`;
  for (let d = 1; d <= lastDay.getDate(); d += 1) {
    const date = new Date(y, m, d);
    const iso = `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const isStart = s && date.getTime() === s.getTime();
    const isEnd = e && date.getTime() === e.getTime();
    const rangeEnd = e || h;
    const inRange = s && rangeEnd && date > (s < rangeEnd ? s : rangeEnd) && date < (s < rangeEnd ? rangeEnd : s);
    let cls = "cal-cell cal-day";
    if (isStart || isEnd) cls += " cal-selected";
    if (isStart) cls += " cal-range-start";
    if (isEnd) cls += " cal-range-end";
    if (inRange) cls += " cal-in-range";
    if (iso === todayIso) cls += " cal-today";
    html += `<div class="${cls}" data-date="${iso}" onclick="event.stopPropagation();_ozonFbsPvzCalPickDate(${y},${m},${d})" onmouseenter="_ozonFbsPvzCalHover(${y},${m},${d})">${d}</div>`;
  }
  html += `</div>`;
  if (s || e) {
    html += `<div class="cal-range-label" onclick="event.stopPropagation()">${fmtDisp(s) || "…"} — ${fmtDisp(e) || "…"}</div>`;
  }
  html += `<div class="cal-footer" onclick="event.stopPropagation()">
    <button type="button" class="secondary" onclick="event.stopPropagation();_ozonFbsPvzCalPickToday()">Сегодня</button>
  </div>`;
  container.innerHTML = html;
}

function _ozonFbsPvzApplyRange(start, end) {
  _ozonFbsPvzCal.startDate = start;
  _ozonFbsPvzCal.endDate = end;
  const from = document.getElementById("ozonFbsPvzDateFrom");
  const to = document.getElementById("ozonFbsPvzDateTo");
  if (from) from.value = _ozonFbsPvzFmtIso(start);
  if (to) to.value = _ozonFbsPvzFmtIso(end);
  _ozonFbsPvzUpdateDateBtn();
  _ozonFbsPvzSetInfo("");
  void loadOzonFbsPvzReturns();
}

function _ozonFbsPvzCalPickDate(y, m, d) {
  const date = new Date(y, m, d);
  date.setHours(0, 0, 0, 0);
  if (!_ozonFbsPvzCal.startDate || (_ozonFbsPvzCal.startDate && _ozonFbsPvzCal.endDate)) {
    _ozonFbsPvzCal.startDate = date;
    _ozonFbsPvzCal.endDate = null;
    _ozonFbsPvzCalRender();
    return;
  }
  let start = _ozonFbsPvzCal.startDate;
  let end = date;
  if (date < start) {
    end = start;
    start = date;
  }
  if (_ozonFbsPvzSpanDays(start, end) > 31) {
    _ozonFbsPvzSetInfo("Период не больше 31 дня", "warn");
    _ozonFbsPvzCalRender();
    return;
  }
  _ozonFbsPvzCal.endDate = end;
  _ozonFbsPvzCal.startDate = start;
  _ozonFbsPvzCalRender();
  _ozonFbsPvzApplyRange(start, new Date(end.getTime()));
  setTimeout(() => toggleOzonFbsPvzDatePanel(false), 300);
}

function _ozonFbsPvzCalPickToday() {
  const today = _ozonFbsPvzParseIso(_ozonFbsPvzTodayIso());
  if (!today) return;
  _ozonFbsPvzCal.viewYear = today.getFullYear();
  _ozonFbsPvzCal.viewMonth = today.getMonth();
  _ozonFbsPvzApplyRange(today, new Date(today.getTime()));
  toggleOzonFbsPvzDatePanel(false);
}

function _ozonFbsPvzCalHover(y, m, d) {
  if (!_ozonFbsPvzCal.startDate || _ozonFbsPvzCal.endDate) return;
  _ozonFbsPvzCal.hoveredDate = new Date(y, m, d);
  const s = _ozonFbsPvzCal.startDate;
  document.querySelectorAll("#ozonFbsPvzCalendar .cal-day[data-date]").forEach((el) => {
    const dt = new Date(`${el.dataset.date}T00:00:00`);
    const h2 = _ozonFbsPvzCal.hoveredDate;
    const inRange = s && h2 && dt > (s < h2 ? s : h2) && dt < (s < h2 ? h2 : s);
    el.classList.toggle("cal-in-range", inRange);
  });
}

function _ozonFbsPvzCalClearHover() {
  if (!_ozonFbsPvzCal.hoveredDate) return;
  _ozonFbsPvzCal.hoveredDate = null;
  document.querySelectorAll("#ozonFbsPvzCalendar .cal-day.cal-in-range").forEach((el) => {
    el.classList.remove("cal-in-range");
  });
}

function _ozonFbsPvzCalPrevMonth() {
  if (_ozonFbsPvzCal.viewMonth === 0) {
    _ozonFbsPvzCal.viewMonth = 11;
    _ozonFbsPvzCal.viewYear -= 1;
  } else {
    _ozonFbsPvzCal.viewMonth -= 1;
  }
  _ozonFbsPvzCalRender();
}

function _ozonFbsPvzCalNextMonth() {
  if (_ozonFbsPvzCal.viewMonth === 11) {
    _ozonFbsPvzCal.viewMonth = 0;
    _ozonFbsPvzCal.viewYear += 1;
  } else {
    _ozonFbsPvzCal.viewMonth += 1;
  }
  _ozonFbsPvzCalRender();
}

function toggleOzonFbsPvzDatePanel(show) {
  const panel = document.getElementById("ozonFbsPvzDatePanel");
  if (!panel || ozonFbsPvzState.syncing) return;
  const isVisible = panel.style.display === "flex";
  const shouldShow = show !== undefined ? Boolean(show) : !isVisible;
  panel.style.display = shouldShow ? "flex" : "none";
  if (shouldShow) _ozonFbsPvzCalRender();
}
window.toggleOzonFbsPvzDatePanel = toggleOzonFbsPvzDatePanel;

function _ozonFbsPvzFillSourceFilter() {
  const sel = document.getElementById("ozonFbsPvzSourceFilter");
  if (!sel) return;
  const prev = String(sel.value || "0");
  const selected = (ozonFbsPvzState.sources || []).filter((s) => s && s.selected);
  const options = [`<option value="0">Все источники</option>`];
  selected.forEach((s) => {
    const id = Number(s.id || 0);
    options.push(`<option value="${id}">${_ozonFbsPvzEsc(s.name || id)}</option>`);
  });
  sel.innerHTML = options.join("");
  const stillThere = Array.from(sel.options).some((opt) => opt.value === prev);
  sel.value = stillThere ? prev : "0";
}

function _ozonFbsPvzFillCategoryFilter() {
  const sel = document.getElementById("ozonFbsPvzCategoryFilter");
  if (!sel) return;
  const prev = String(sel.value || "");
  const options = [`<option value="">Все категории</option>`];
  (ozonFbsPvzState.categories || []).forEach((c) => {
    const name = String(c?.name || "").trim();
    if (!name) return;
    options.push(`<option value="${_ozonFbsPvzEsc(name)}">${_ozonFbsPvzEsc(name)}</option>`);
  });
  options.push(`<option value="__none__">Без категории</option>`);
  sel.innerHTML = options.join("");
  const stillThere = Array.from(sel.options).some((opt) => opt.value === prev);
  sel.value = stillThere ? prev : "";
}

async function loadOzonFbsPvzSettings() {
  const res = await fetch("/api/ozon-fbs/pvz-returns/settings", { headers: _ozonFbsPvzHeaders() });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(_ozonFbsPvzApiError(res, payload, "Не удалось загрузить источники"));
  }
  ozonFbsPvzState.sources = Array.isArray(payload.sources) ? payload.sources : [];
  _ozonFbsPvzFillSourceFilter();
  return payload;
}

function _ozonFbsPvzSelectedSources() {
  return (ozonFbsPvzState.sources || []).filter((s) => s && s.selected);
}

function onOzonFbsPvzFilterChange() {
  if (ozonFbsPvzState.syncing) return;
  _ozonFbsPvzSyncFilterBtnState();
  void loadOzonFbsPvzReturns();
}
window.onOzonFbsPvzFilterChange = onOzonFbsPvzFilterChange;

function onOzonFbsPvzSearchInput() {
  if (ozonFbsPvzState.syncing) return;
  _ozonFbsPvzSyncFilterBtnState();
  renderOzonFbsPvzTable();
}
window.onOzonFbsPvzSearchInput = onOzonFbsPvzSearchInput;

function _ozonFbsPvzRowMatchesSearch(item, query) {
  const q = String(query || "").trim().toLocaleLowerCase("en-US");
  if (!q) return true;
  const barcodes = [
    ...(Array.isArray(item?.catalog_barcodes) ? item.catalog_barcodes : []),
    ...(Array.isArray(item?.product_barcodes) ? item.product_barcodes : []),
  ];
  const hay = [
    item?.sticker_id,
    item?.sticker_scanit,
    item?.sticker_part_a,
    item?.sticker_part_b,
    item?.product_name,
    item?.article,
    item?.sku,
    item?.posting_number,
    item?.order_id,
    item?.order_number,
    ...barcodes,
  ]
    .map((x) => String(x || "").trim().toLocaleLowerCase("en-US"))
    .filter(Boolean);
  return hay.some((v) => v.includes(q));
}

function _ozonFbsPvzVisibleItems() {
  const items = Array.isArray(ozonFbsPvzState.items) ? ozonFbsPvzState.items : [];
  const q = document.getElementById("ozonFbsPvzSearchFilter")?.value || "";
  if (!String(q || "").trim()) return items;
  return items.filter((item) => _ozonFbsPvzRowMatchesSearch(item, q));
}

/** Return sticker under the issued date — same last-4 highlight as supply stickers. */
function _ozonFbsPvzStickerHtml(item) {
  const stickerId = String(item?.sticker_id || "").trim();
  const partA = String(item?.sticker_part_a || "").trim();
  const partB = String(item?.sticker_part_b || "").trim();
  const row = stickerId
    ? { sticker_number: stickerId }
    : { sticker_part_a: partA, sticker_part_b: partB };
  if (typeof _wbFbsKizStickerHtml === "function") {
    return _wbFbsKizStickerHtml(row);
  }
  const full = stickerId || (partA && partB ? `${partA}${partB}` : (partA || partB));
  if (!full) return `<div class="wb-fbs-kiz-sticker">—</div>`;
  if (full.length > 4) {
    const head = full.slice(0, -4);
    const tail = full.slice(-4);
    return `<div class="wb-fbs-kiz-sticker">` +
      `<span class="wb-fbs-kiz-sticker-head">${_ozonFbsPvzEsc(head)}</span>` +
      `<span class="wb-fbs-kiz-sticker-tail">${_ozonFbsPvzEsc(tail)}</span>` +
      `</div>`;
  }
  return `<div class="wb-fbs-kiz-sticker"><span class="wb-fbs-kiz-sticker-tail">${_ozonFbsPvzEsc(full)}</span></div>`;
}

function _ozonFbsPvzProductCell(item) {
  const photo = item.product_photo
    ? `<img class="wb-fbs-product-photo" src="${_ozonFbsPvzEsc(item.product_photo)}" alt="" width="144" height="144" loading="lazy">`
    : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
  const article = String(item.article || "").trim();
  const sku = String(item.sku || "").trim();
  const posting = String(item.posting_number || "").trim();
  const subParts = [];
  if (article) subParts.push(`Арт. ${article}`);
  if (sku) subParts.push(`SKU ${sku}`);
  if (posting) subParts.push(posting);
  const sub = subParts.length ? subParts.join(" · ") : "—";
  const barcodes = Array.isArray(item.catalog_barcodes) ? item.catalog_barcodes : [];
  const barcodeHtml = barcodes.length
    ? `<div class="wb-fbs-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
        `<div class="wb-fbs-barcode">${_ozonFbsPvzEsc(b)}</div>`
      ).join("")}</div>`
    : "";
  const name = String(item.product_name || article || "—");
  return `<div class="wb-fbs-product">
    ${photo}
    <div class="wb-fbs-product-text">
      <div class="wb-fbs-product-name" title="${_ozonFbsPvzEsc(name)}">${_ozonFbsPvzEsc(name)}</div>
      <div class="wb-fbs-product-sub">${_ozonFbsPvzEsc(sub)}</div>
      ${barcodeHtml}
    </div>
  </div>`;
}

function renderOzonFbsPvzTable() {
  const tbody = document.getElementById("ozonFbsPvzTbody");
  const count = document.getElementById("ozonFbsPvzCount");
  const allItems = Array.isArray(ozonFbsPvzState.items) ? ozonFbsPvzState.items : [];
  const items = _ozonFbsPvzVisibleItems();
  const searchQ = String(document.getElementById("ozonFbsPvzSearchFilter")?.value || "").trim();
  if (count) count.textContent = `В таблице: ${items.length}`;
  if (!tbody) return;
  if (!allItems.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Нет выданных возвратов за этот период. Нажмите «Синхронизировать».</td></tr>`;
    return;
  }
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">${
      searchQ ? "Нет строк по выбранному фильтру" : "Нет выданных возвратов за этот период. Нажмите «Синхронизировать»."
    }</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((item, index) => {
    const menuKey = `ozon_pvz_${index}`;
    const printable = typeof _wbFbsReturnsPrintableBarcodes === "function"
      ? _wbFbsReturnsPrintableBarcodes(item.catalog_barcodes)
      : [];
    const canBarcode = printable.length > 0;
    const stickerHtml = _ozonFbsPvzStickerHtml(item);
    return `<tr>
      <td class="wb-fbs-pvz-issued">
        <span class="wb-fbs-pvz-cell-label">Выдан</span>
        <span class="wb-fbs-pvz-cell-value">${_ozonFbsPvzEsc(item.issued_label || "—")}</span>
        <div class="wb-fbs-sd-sticker">${stickerHtml}</div>
      </td>
      <td class="wb-fbs-sd-td-product">${_ozonFbsPvzProductCell(item)}</td>
      <td class="wb-fbs-pvz-num"><span class="wb-fbs-pvz-cell-label">Кол-во</span><span class="wb-fbs-pvz-cell-value">${Number(item.qty || 1)}</span></td>
      <td class="wb-fbs-sd-td-act">
        <div class="wb-fbs-row-menu-wrap">
          <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
                  onclick="toggleWbFbsRowMenu(event, '${menuKey}')" aria-haspopup="menu">⋮</button>
          <div id="wbFbsRowMenu_${menuKey}" class="wb-fbs-row-menu wb-fbs-pvz-row-menu" data-order-id="${menuKey}" role="menu">
            <button type="button" class="wb-fbs-row-menu-item${canBarcode ? "" : " is-disabled"}" role="menuitem"
                    ${canBarcode ? `onclick="printOzonFbsPvzBarcode(${index})"` : "disabled"}
                    ${canBarcode ? "" : 'title="Нет ШК в каталоге товаров"'}>
              Распечатать ШК
            </button>
          </div>
        </div>
      </td>
    </tr>`;
  }).join("");
}

async function loadOzonFbsPvzReturns() {
  _ozonFbsPvzEnsureDates();
  const from = document.getElementById("ozonFbsPvzDateFrom")?.value || "";
  const to = document.getElementById("ozonFbsPvzDateTo")?.value || "";
  const sourceId = document.getElementById("ozonFbsPvzSourceFilter")?.value || "0";
  const category = document.getElementById("ozonFbsPvzCategoryFilter")?.value || "";
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (sourceId && sourceId !== "0") params.set("source_id", sourceId);
  if (category) params.set("category", category);
  const tbody = document.getElementById("ozonFbsPvzTbody");
  if (tbody && !ozonFbsPvzState.items.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Загрузка…</td></tr>`;
  }
  try {
    const res = await fetch(`/api/ozon-fbs/pvz-returns?${params.toString()}`, { headers: _ozonFbsPvzHeaders() });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_ozonFbsPvzApiError(res, payload, "Не удалось загрузить возвраты"));
    }
    ozonFbsPvzState.items = Array.isArray(payload.items) ? payload.items : [];
    if (Array.isArray(payload.categories)) {
      ozonFbsPvzState.categories = payload.categories;
      _ozonFbsPvzFillCategoryFilter();
    }
    _ozonFbsPvzSyncFilterBtnState();
    renderOzonFbsPvzTable();
  } catch (err) {
    ozonFbsPvzState.items = [];
    _ozonFbsPvzSyncFilterBtnState();
    renderOzonFbsPvzTable();
    _ozonFbsPvzSetInfo(err?.message || String(err), "error");
  }
}

function _ozonFbsPvzSetSyncing(on, label) {
  // Close panels before the syncing flag: toggles ignore calls while syncing.
  if (on) {
    toggleOzonFbsPvzFilterPanel(false);
    toggleOzonFbsPvzDatePanel(false);
  }
  ozonFbsPvzState.syncing = !!on;
  const btn = document.getElementById("ozonFbsPvzSyncBtn");
  const gear = document.getElementById("ozonFbsPvzSettingsBtn");
  const printBtn = document.getElementById("ozonFbsPvzPrintBtn");
  const qrBtn = document.getElementById("ozonFbsPvzQrBtn");
  const filterBtn = document.getElementById("ozonFbsPvzFilterBtn");
  const dateBtn = document.getElementById("ozonFbsPvzDateBtn");
  const search = document.getElementById("ozonFbsPvzSearchFilter");
  const source = document.getElementById("ozonFbsPvzSourceFilter");
  const category = document.getElementById("ozonFbsPvzCategoryFilter");
  if (btn) {
    btn.disabled = !!on;
    btn.textContent = on ? (label || "Запуск…") : "Синхронизировать";
    btn.setAttribute("aria-busy", on ? "true" : "false");
  }
  if (gear) gear.disabled = !!on;
  if (printBtn) printBtn.disabled = !!on;
  if (qrBtn) qrBtn.disabled = !!on;
  if (filterBtn) filterBtn.disabled = !!on;
  if (dateBtn) dateBtn.disabled = !!on;
  if (search) search.disabled = !!on;
  if (source) source.disabled = !!on;
  if (category) category.disabled = !!on;
}

/** QR → existing Ozon giveout modal «Получение возвратов». */
function openOzonFbsPvzGiveout() {
  if (ozonFbsPvzState.syncing) return;
  if (typeof openOzonReturnsModal === "function") {
    openOzonReturnsModal();
    return;
  }
  _ozonFbsPvzSetInfo("Модалка получения возвратов недоступна", "warn");
}
window.openOzonFbsPvzGiveout = openOzonFbsPvzGiveout;

async function _ozonFbsPvzPoll(token) {
  const started = Date.now();
  const maxWaitMs = 20 * 60 * 1000;
  while (ozonFbsPvzState.pollToken === token && Date.now() - started < maxWaitMs) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    if (ozonFbsPvzState.pollToken !== token) return null;
    const res = await fetch("/api/ozon-fbs/pvz-returns/sync/status", { headers: _ozonFbsPvzHeaders() });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_ozonFbsPvzApiError(res, payload, "Не удалось проверить статус синхронизации"));
    }
    const status = String(payload.status || "");
    const btn = document.getElementById("ozonFbsPvzSyncBtn");
    if (btn && status === "running" && payload.message) btn.textContent = String(payload.message);
    if (status === "running") continue;
    return payload;
  }
  if (Date.now() - started >= maxWaitMs) {
    throw new Error("Синхронизация затянулась. Подождите и откройте окно снова.");
  }
  return null;
}

async function syncOzonFbsPvzReturns() {
  if (ozonFbsPvzState.syncing) return;
  if (!_ozonFbsPvzSelectedSources().length) {
    alert("Выберите источники в настройках");
    openOzonFbsPvzSettings();
    return;
  }
  const token = ozonFbsPvzState.pollToken + 1;
  ozonFbsPvzState.pollToken = token;
  _ozonFbsPvzSetSyncing(true, "Запуск…");
  _ozonFbsPvzSetInfo("");
  try {
    const res = await fetch("/api/ozon-fbs/pvz-returns/sync", {
      method: "POST",
      headers: _ozonFbsPvzHeaders(),
      body: JSON.stringify({}),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_ozonFbsPvzApiError(res, payload, "Синхронизация не удалась"));
    }
    let result = payload;
    if (String(payload.status || "") === "running") {
      const btn = document.getElementById("ozonFbsPvzSyncBtn");
      if (btn && payload.message) btn.textContent = String(payload.message);
      result = await _ozonFbsPvzPoll(token);
    }
    if (!result || ozonFbsPvzState.pollToken !== token) return;
    const status = String(result.status || "");
    const errors = Array.isArray(result.errors) ? result.errors.filter(Boolean) : [];
    if (status === "error") {
      const extra = errors.length ? ` ${errors.join(" ")}` : "";
      _ozonFbsPvzSetInfo(`${result.message || "Синхронизация не удалась"}${extra}`, "error");
    } else if (errors.length) {
      _ozonFbsPvzSetInfo(errors.join(" "), "warn");
    } else {
      _ozonFbsPvzSetInfo("");
    }
    // Sync always covers the last 31 days — put that range in the filter and show it.
    _ozonFbsPvzSetIssueDates(result.date_from, result.date_to);
    await loadOzonFbsPvzReturns();
  } catch (err) {
    if (ozonFbsPvzState.pollToken === token) {
      _ozonFbsPvzSetInfo(err?.message || String(err), "error");
    }
  } finally {
    if (ozonFbsPvzState.pollToken === token) _ozonFbsPvzSetSyncing(false);
  }
}
window.syncOzonFbsPvzReturns = syncOzonFbsPvzReturns;

function _ozonFbsPvzRenderSettings(sources) {
  const list = document.getElementById("ozonFbsPvzSettingsList");
  if (!list) return;
  const rows = Array.isArray(sources) ? sources : [];
  if (!rows.length) {
    list.innerHTML = `<p class="wb-fbs-pvz-settings-empty">Нет источников Ozon FBS. Добавьте их в Поставки → Настройки → Источники.</p>`;
    return;
  }
  list.innerHTML = rows.map((s) => {
    const id = Number(s.id || 0);
    const checked = s.selected ? " checked" : "";
    return `<label class="wb-fbs-pvz-check" for="ozonFbsPvzSrc_${id}">
      <input type="checkbox" id="ozonFbsPvzSrc_${id}" value="${id}"${checked} />
      <span>${_ozonFbsPvzEsc(s.name || id)}</span>
    </label>`;
  }).join("");
}

function _ozonFbsPvzCanEditSettings() {
  return typeof isTenantOwner === "function" && isTenantOwner();
}

function _ozonFbsPvzSyncOwnerOnlySettingsBtn() {
  const btn = document.getElementById("ozonFbsPvzSettingsBtn");
  if (!btn) return;
  const can = _ozonFbsPvzCanEditSettings();
  btn.hidden = !can;
  btn.style.display = can ? "" : "none";
}
window._ozonFbsPvzSyncOwnerOnlySettingsBtn = _ozonFbsPvzSyncOwnerOnlySettingsBtn;

function openOzonFbsPvzSettings() {
  if (!_ozonFbsPvzCanEditSettings()) {
    _ozonFbsPvzSyncOwnerOnlySettingsBtn();
    _ozonFbsPvzSetInfo("Источники доступны только главному пользователю", "warn");
    return;
  }
  const modal = document.getElementById("ozonFbsPvzSettingsModal");
  const info = document.getElementById("ozonFbsPvzSettingsInfo");
  if (info) {
    info.hidden = true;
    info.textContent = "";
  }
  if (modal) modal.classList.remove("hidden");
  _ozonFbsPvzRenderSettings(ozonFbsPvzState.sources);
  void loadOzonFbsPvzSettings()
    .then((payload) => _ozonFbsPvzRenderSettings(payload.sources))
    .catch((err) => {
      if (!info) return;
      info.hidden = false;
      info.textContent = err?.message || String(err);
      info.classList.add("is-error");
    });
}
window.openOzonFbsPvzSettings = openOzonFbsPvzSettings;

function closeOzonFbsPvzSettings() {
  document.getElementById("ozonFbsPvzSettingsModal")?.classList.add("hidden");
}
window.closeOzonFbsPvzSettings = closeOzonFbsPvzSettings;

async function saveOzonFbsPvzSettings() {
  if (!_ozonFbsPvzCanEditSettings()) {
    _ozonFbsPvzSyncOwnerOnlySettingsBtn();
    closeOzonFbsPvzSettings();
    _ozonFbsPvzSetInfo("Источники доступны только главному пользователю", "warn");
    return;
  }
  const info = document.getElementById("ozonFbsPvzSettingsInfo");
  const btn = document.getElementById("ozonFbsPvzSettingsSaveBtn");
  const ids = Array.from(document.querySelectorAll("#ozonFbsPvzSettingsList input[type=checkbox]:checked"))
    .map((el) => Number(el.value))
    .filter((id) => id > 0);
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/ozon-fbs/pvz-returns/settings", {
      method: "POST",
      headers: _ozonFbsPvzHeaders(),
      body: JSON.stringify({ source_ids: ids }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_ozonFbsPvzApiError(res, payload, "Не удалось сохранить источники"));
    }
    ozonFbsPvzState.sources = Array.isArray(payload.sources) ? payload.sources : [];
    _ozonFbsPvzFillSourceFilter();
    closeOzonFbsPvzSettings();
    await loadOzonFbsPvzReturns();
  } catch (err) {
    if (info) {
      info.hidden = false;
      info.textContent = err?.message || String(err);
      info.classList.add("is-error");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.saveOzonFbsPvzSettings = saveOzonFbsPvzSettings;

async function openOzonFbsPvzReturnsModal() {
  const modal = document.getElementById("ozonFbsPvzReturnsModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  _ozonFbsPvzSyncOwnerOnlySettingsBtn();
  const search = document.getElementById("ozonFbsPvzSearchFilter");
  if (search) search.value = "";
  toggleOzonFbsPvzFilterPanel(false);
  _ozonFbsPvzEnsureDates();
  _ozonFbsPvzSyncFilterBtnState();
  initOzonFbsPvzColumnResizer();
  _ozonFbsPvzSetInfo("");
  try {
    await loadOzonFbsPvzSettings();
  } catch (err) {
    _ozonFbsPvzSetInfo(err?.message || String(err), "error");
  }
  await loadOzonFbsPvzReturns();
  if (!ozonFbsPvzState.syncing) {
    try {
      const res = await fetch("/api/ozon-fbs/pvz-returns/sync/status", { headers: _ozonFbsPvzHeaders() });
      const payload = await res.json().catch(() => ({}));
      if (res.ok && String(payload.status || "") === "running") {
        const token = ozonFbsPvzState.pollToken + 1;
        ozonFbsPvzState.pollToken = token;
        _ozonFbsPvzSetSyncing(true, payload.message || "Синхронизация…");
        const result = await _ozonFbsPvzPoll(token);
        if (result && ozonFbsPvzState.pollToken === token) {
          if (String(result.status || "") === "error") {
            _ozonFbsPvzSetInfo(result.message || "Синхронизация не удалась", "error");
          }
          _ozonFbsPvzSetIssueDates(result.date_from, result.date_to);
          await loadOzonFbsPvzReturns();
        }
        if (ozonFbsPvzState.pollToken === token) _ozonFbsPvzSetSyncing(false);
      }
    } catch (err) {
      _ozonFbsPvzSetInfo(err?.message || String(err), "error");
      _ozonFbsPvzSetSyncing(false);
    }
  }
}
window.openOzonFbsPvzReturnsModal = openOzonFbsPvzReturnsModal;

function closeOzonFbsPvzReturnsModal() {
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  toggleOzonFbsPvzFilterPanel(false);
  toggleOzonFbsPvzDatePanel(false);
  document.getElementById("ozonFbsPvzReturnsModal")?.classList.add("hidden");
}
window.closeOzonFbsPvzReturnsModal = closeOzonFbsPvzReturnsModal;

function _ozonFbsPvzMergeItems(items) {
  const merged = new Map();
  const order = [];
  (items || []).forEach((item) => {
    const name = String(item?.product_name || "").trim();
    const article = String(item?.article || "").trim();
    const key = name
      ? `name:${name.toLowerCase()}`
      : (article ? `article:${article.toLowerCase()}` : `id:${Number(item?.id || 0)}`);
    const qty = Math.max(1, Number(item?.qty || 1) || 1);
    if (!merged.has(key)) {
      merged.set(key, {
        product_name: name || article || "—",
        qty,
      });
      order.push(key);
      return;
    }
    merged.get(key).qty += qty;
  });
  return order.map((key) => merged.get(key));
}

function _ozonFbsPvzPrintDateLabel() {
  const start = _ozonFbsPvzCal.startDate;
  const end = _ozonFbsPvzCal.endDate;
  if (!start || !end) {
    const from = document.getElementById("ozonFbsPvzDateFrom")?.value || "";
    const to = document.getElementById("ozonFbsPvzDateTo")?.value || "";
    if (!from) return "";
    const fmtIso = (iso) => {
      const parts = String(iso || "").split("-");
      if (parts.length < 3) return String(iso || "");
      return `${parts[2]}.${parts[1]}.${parts[0]}`;
    };
    if (!to || to === from) return fmtIso(from);
    return `${fmtIso(from)}–${fmtIso(to)}`;
  }
  const fmt = (d) => d.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  if (start.getTime() === end.getTime()) return fmt(start);
  return `${fmt(start)}–${fmt(end)}`;
}

function _ozonFbsPvzPrintTitle(mode) {
  const dateLabel = _ozonFbsPvzPrintDateLabel();
  if (String(mode || "") === "merged") {
    return dateLabel ? `Возвраты ПВЗ (${dateLabel})` : "Возвраты ПВЗ";
  }
  return dateLabel
    ? `Возвраты ПВЗ (${dateLabel}) — весь список`
    : "Возвраты ПВЗ — весь список";
}

function _ozonFbsPvzPrintHtml(rows, title, mode) {
  const list = Array.isArray(rows) ? rows : [];
  const total = list.reduce((sum, row) => sum + Math.max(1, Number(row?.qty || 1) || 1), 0);
  const merged = String(mode || "") === "merged";
  const body = list.length
    ? list.map((row) => {
      const name = _ozonFbsPvzEsc(row.product_name || row.article || "—");
      const qty = Math.max(1, Number(row.qty || 1) || 1);
      if (merged) {
        return `<tr>` +
          `<td class="name">${name}</td>` +
          `<td class="qty">${qty}</td>` +
          `<td class="defect"></td>` +
          `</tr>`;
      }
      return `<tr><td class="name">${name}</td><td class="qty">${qty}</td></tr>`;
    }).join("")
    : (merged
      ? `<tr><td colspan="3" class="empty">Нет строк для печати</td></tr>`
      : `<tr><td colspan="2" class="empty">Нет строк для печати</td></tr>`);
  const head = merged
    ? `<tr><th class="name">Товар</th><th class="qty">Кол-во</th><th class="defect">Брак/утилизация</th></tr>`
    : `<tr><th>Товар</th><th class="qty">Кол-во</th></tr>`;
  const mergedCss = merged
    ? `
    th.name, td.name { width: 80%; }
    th.qty, td.qty { width: 10%; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
    th.defect, td.defect { width: 10%; text-align: left; }
    td.defect { min-height: 24px; }
    th, td { padding: 8px 10px; border: 1px solid #cbd5e1; }
    table { border: 1px solid #cbd5e1; border-collapse: collapse; }
    th { background: #f8fafc; }
    `
    : `
    th.qty, td.qty { text-align: right; white-space: nowrap; width: 72px; font-variant-numeric: tabular-nums; }
    th, td { padding: 8px 0; border-bottom: 1px solid #e2e8f0; }
    `;
  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>${_ozonFbsPvzEsc(title || "Возвраты ПВЗ")}</title>
  <style>
    @page { margin: 12mm; }
    body { font: 14px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #0f172a; margin: 0; }
    h1 { font-size: 18px; margin: 0 0 8px; font-weight: 700; }
    .meta { font-size: 13px; color: #475569; margin: 0 0 16px; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    th, td { vertical-align: top; }
    th { font-size: 12px; font-weight: 600; color: #64748b; text-align: left; }
    td.name { font-size: 15px; font-weight: 600; padding-right: 16px; word-wrap: break-word; }
    td.empty { color: #64748b; font-weight: 400; }
    ${mergedCss}
  </style>
</head>
<body>
  <h1>${_ozonFbsPvzEsc(title || "Возвраты ПВЗ")}</h1>
  <p class="meta">Строк: ${list.length} · Количество: ${total}</p>
  <table>
    <thead>${head}</thead>
    <tbody>${body}</tbody>
  </table>
  <script>window.addEventListener("load", function () { window.focus(); window.print(); });</script>
</body>
</html>`;
}

function printOzonFbsPvzList(mode) {
  if (ozonFbsPvzState.syncing) return;
  toggleOzonFbsPvzFilterPanel(false);
  toggleOzonFbsPvzDatePanel(false);
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  const items = _ozonFbsPvzVisibleItems();
  if (!items.length) {
    _ozonFbsPvzSetInfo("Нет строк для печати. Синхронизируйте или смените фильтр.", "warn");
    return;
  }
  // Print button opens merged pick-list; keep full mode for API/compat.
  const merged = String(mode || "") !== "full";
  const rows = merged
    ? _ozonFbsPvzMergeItems(items)
    : items.map((item) => ({
      product_name: String(item.product_name || item.article || "—"),
      qty: Math.max(1, Number(item.qty || 1) || 1),
    }));
  const title = _ozonFbsPvzPrintTitle(merged ? "merged" : "full");
  const win = window.open("", "_blank");
  if (!win) {
    _ozonFbsPvzSetInfo("Разрешите всплывающие окна для печати", "warn");
    return;
  }
  win.document.write(_ozonFbsPvzPrintHtml(rows, title, merged ? "merged" : "full"));
  win.document.close();
}
window.printOzonFbsPvzList = printOzonFbsPvzList;

function printOzonFbsPvzBarcode(index) {
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  const item = _ozonFbsPvzVisibleItems()[Number(index)];
  if (!item) return;
  const barcodes = typeof _wbFbsReturnsPrintableBarcodes === "function"
    ? _wbFbsReturnsPrintableBarcodes(item.catalog_barcodes)
    : [];
  if (!barcodes.length) {
    _ozonFbsPvzSetInfo("У товара нет ШК в каталоге (Настройки → Товары)", "warn");
    return;
  }
  const labelText = typeof _wbFbsReturnsBarcodeLabelText === "function"
    ? _wbFbsReturnsBarcodeLabelText(item)
    : String(item.product_name || "");
  if (barcodes.length === 1) {
    _wbFbsReturnsDoBarcodePrint(barcodes[0], labelText);
    return;
  }
  const preferred = typeof _wbFbsReturnsPreferredBarcode === "function"
    ? _wbFbsReturnsPreferredBarcode(barcodes, item)
    : barcodes[0];
  openWbFbsReturnsBarcodeModal(barcodes, labelText, preferred);
}
window.printOzonFbsPvzBarcode = printOzonFbsPvzBarcode;

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const settings = document.getElementById("ozonFbsPvzSettingsModal");
  if (settings && !settings.classList.contains("hidden")) {
    closeOzonFbsPvzSettings();
    return;
  }
  const datePanel = document.getElementById("ozonFbsPvzDatePanel");
  if (datePanel && datePanel.style.display === "flex") {
    toggleOzonFbsPvzDatePanel(false);
    return;
  }
  const filterPanel = document.getElementById("ozonFbsPvzFilterPanel");
  if (filterPanel && !filterPanel.hidden) {
    toggleOzonFbsPvzFilterPanel(false);
    return;
  }
  const modal = document.getElementById("ozonFbsPvzReturnsModal");
  if (modal && !modal.classList.contains("hidden")) closeOzonFbsPvzReturnsModal();
});

document.addEventListener("click", (event) => {
  const target = event.target;
  const filterWrap = document.querySelector("#ozonFbsPvzReturnsModal .wb-fbs-pvz-filter-wrap");
  const filterPanel = document.getElementById("ozonFbsPvzFilterPanel");
  if (filterWrap && filterPanel && !filterPanel.hidden && !filterWrap.contains(target)) {
    toggleOzonFbsPvzFilterPanel(false);
  }
  const dateWrap = document.querySelector("#ozonFbsPvzReturnsModal .wb-fbs-pvz-date-wrap");
  const datePanel = document.getElementById("ozonFbsPvzDatePanel");
  if (
    dateWrap &&
    datePanel &&
    datePanel.style.display === "flex" &&
    !dateWrap.contains(target)
  ) {
    toggleOzonFbsPvzDatePanel(false);
  }
});
