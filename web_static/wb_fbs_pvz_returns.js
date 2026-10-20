/* WB FBS «Возвраты ПВЗ». Loaded after app.js. */

const wbFbsPvzState = {
  sources: [],
  categories: [],
  items: [],
  syncing: false,
  pollToken: 0,
};

const _wbFbsPvzCal = {
  viewYear: new Date().getFullYear(),
  viewMonth: new Date().getMonth(),
  startDate: null,
  endDate: null,
  hoveredDate: null,
};

const WB_FBS_PVZ_COL_WIDTHS_PREFIX = "wb_fbs_pvz_col_widths_v1";
const WB_FBS_PVZ_DEFAULT_WIDTHS = [22, 58, 20]; // issued, product, qty (act is fixed)
let _wbFbsPvzColResizerInited = false;

function _wbFbsPvzColWidthsKey() {
  const email = String(document.querySelector(".sidebar-user-email")?.textContent || "").trim().toLowerCase();
  return email ? `${WB_FBS_PVZ_COL_WIDTHS_PREFIX}:${email}` : WB_FBS_PVZ_COL_WIDTHS_PREFIX;
}

function _wbFbsPvzResizableCols() {
  return Array.from(document.querySelectorAll("#wbFbsPvzColgroup col")).filter((c) => !c.dataset.fixed);
}

function _applyWbFbsPvzColWidths(widths) {
  _wbFbsPvzResizableCols().forEach((col, i) => {
    if (widths[i] !== undefined) col.style.width = `${widths[i]}%`;
  });
}

function _getWbFbsPvzColWidths() {
  return _wbFbsPvzResizableCols().map((col, i) => parseFloat(col.style.width) || WB_FBS_PVZ_DEFAULT_WIDTHS[i] || 10);
}

function _restoreWbFbsPvzColWidths() {
  let widths = WB_FBS_PVZ_DEFAULT_WIDTHS.slice();
  try {
    const saved = JSON.parse(localStorage.getItem(_wbFbsPvzColWidthsKey()) || "null");
    if (Array.isArray(saved) && saved.length === widths.length) widths = saved;
    else if (Array.isArray(saved)) localStorage.removeItem(_wbFbsPvzColWidthsKey());
  } catch (_) { /* ignore */ }
  _applyWbFbsPvzColWidths(widths);
}

function initWbFbsPvzColumnResizer() {
  const table = document.getElementById("wbFbsPvzTable");
  if (!table) return;
  _restoreWbFbsPvzColWidths();
  if (_wbFbsPvzColResizerInited) return;
  _wbFbsPvzColResizerInited = true;

  let startX = 0;
  let colIdx = 0;
  let startWidths = [];
  let activeHandle = null;

  function onMouseMove(e) {
    const tableEl = document.getElementById("wbFbsPvzTable");
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
    _applyWbFbsPvzColWidths(newWidths);
  }

  function onMouseUp() {
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    if (activeHandle) activeHandle.classList.remove("dragging");
    activeHandle = null;
    try {
      localStorage.setItem(_wbFbsPvzColWidthsKey(), JSON.stringify(_getWbFbsPvzColWidths()));
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
    startWidths = _getWbFbsPvzColWidths();
    activeHandle = handle;
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    handle.classList.add("dragging");
  });
}
window.initWbFbsPvzColumnResizer = initWbFbsPvzColumnResizer;

function _wbFbsPvzEsc(value) {
  if (typeof _wbFbsEsc === "function") return _wbFbsEsc(value);
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _wbFbsPvzApiError(res, payload, fallback) {
  if (typeof _wbFbsKizCircApiError === "function") {
    return _wbFbsKizCircApiError(res, payload, fallback);
  }
  const detail = payload && payload.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  return fallback;
}

function _wbFbsPvzTodayIso() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Moscow",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function _wbFbsPvzParseIso(iso) {
  const parts = String(iso || "").split("-").map((n) => Number(n));
  if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return null;
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  date.setHours(0, 0, 0, 0);
  return date;
}

function _wbFbsPvzFmtIso(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function _wbFbsPvzSpanDays(a, b) {
  const ms = Math.abs(b.getTime() - a.getTime());
  return Math.round(ms / 86400000) + 1;
}

function _wbFbsPvzSetInfo(text, kind) {
  const el = document.getElementById("wbFbsPvzInfo");
  if (!el) return;
  const msg = String(text || "").trim();
  el.textContent = msg;
  el.hidden = !msg;
  el.classList.toggle("is-error", kind === "error" || kind === "warn");
}

function _wbFbsPvzHeaders() {
  const base = typeof jsonHeaders === "function" ? jsonHeaders() : {};
  return { ...base, "Content-Type": "application/json" };
}

function _wbFbsPvzEnsureDates() {
  const from = document.getElementById("wbFbsPvzDateFrom");
  const to = document.getElementById("wbFbsPvzDateTo");
  if (from?.value && to?.value && _wbFbsPvzCal.startDate && _wbFbsPvzCal.endDate) {
    _wbFbsPvzUpdateDateBtn();
    return;
  }
  const today = _wbFbsPvzParseIso(_wbFbsPvzTodayIso());
  _wbFbsPvzCal.startDate = today;
  _wbFbsPvzCal.endDate = today ? new Date(today.getTime()) : null;
  _wbFbsPvzCal.viewYear = today ? today.getFullYear() : new Date().getFullYear();
  _wbFbsPvzCal.viewMonth = today ? today.getMonth() : new Date().getMonth();
  if (from && today) from.value = _wbFbsPvzFmtIso(today);
  if (to && today) to.value = _wbFbsPvzFmtIso(today);
  _wbFbsPvzUpdateDateBtn();
}

/** Apply issue-date bounds after sync (last 31 days). Does not reload the table. */
function _wbFbsPvzSetIssueDates(fromIso, toIso) {
  const start = _wbFbsPvzParseIso(fromIso);
  const end = _wbFbsPvzParseIso(toIso);
  if (!start || !end) return false;
  let from = start;
  let to = end;
  if (to < from) {
    from = end;
    to = start;
  }
  _wbFbsPvzCal.startDate = from;
  _wbFbsPvzCal.endDate = new Date(to.getTime());
  _wbFbsPvzCal.viewYear = to.getFullYear();
  _wbFbsPvzCal.viewMonth = to.getMonth();
  const fromEl = document.getElementById("wbFbsPvzDateFrom");
  const toEl = document.getElementById("wbFbsPvzDateTo");
  if (fromEl) fromEl.value = _wbFbsPvzFmtIso(from);
  if (toEl) toEl.value = _wbFbsPvzFmtIso(to);
  _wbFbsPvzUpdateDateBtn();
  return true;
}

function _wbFbsPvzUpdateDateBtn() {
  const btn = document.getElementById("wbFbsPvzDateBtn");
  if (!btn) return;
  // Icon only — selected range lives in the tooltip.
  btn.textContent = "📅";
  const start = _wbFbsPvzCal.startDate;
  const end = _wbFbsPvzCal.endDate;
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

function _wbFbsPvzFiltersAreActive() {
  const search = String(document.getElementById("wbFbsPvzSearchFilter")?.value || "").trim();
  const source = String(document.getElementById("wbFbsPvzSourceFilter")?.value || "0");
  const category = String(document.getElementById("wbFbsPvzCategoryFilter")?.value || "");
  return Boolean(search || (source && source !== "0") || category);
}

function _wbFbsPvzSyncFilterBtnState() {
  const btn = document.getElementById("wbFbsPvzFilterBtn");
  const panel = document.getElementById("wbFbsPvzFilterPanel");
  if (!btn) return;
  const open = !!(panel && !panel.hidden);
  btn.classList.toggle("is-open", open);
  btn.classList.toggle("is-active", _wbFbsPvzFiltersAreActive());
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}

function toggleWbFbsPvzFilterPanel(show) {
  const panel = document.getElementById("wbFbsPvzFilterPanel");
  const btn = document.getElementById("wbFbsPvzFilterBtn");
  if (!panel || !btn || wbFbsPvzState.syncing) return;
  const willOpen = show === undefined ? panel.hidden : Boolean(show);
  if (willOpen) {
    toggleWbFbsPvzPrintMenu(false);
  } else {
    toggleWbFbsPvzDatePanel(false);
  }
  panel.hidden = !willOpen;
  _wbFbsPvzSyncFilterBtnState();
  if (willOpen) {
    const source = document.getElementById("wbFbsPvzSourceFilter");
    if (source && typeof source.focus === "function") {
      setTimeout(() => source.focus(), 0);
    }
  }
}
window.toggleWbFbsPvzFilterPanel = toggleWbFbsPvzFilterPanel;

function _wbFbsPvzCalRender() {
  const container = document.getElementById("wbFbsPvzCalendar");
  if (!container) return;
  const months = (typeof _calMonths !== "undefined" && _calMonths) || [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
  ];
  const days = (typeof _calDays !== "undefined" && _calDays) || ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
  const { viewYear: y, viewMonth: m, startDate: s, endDate: e, hoveredDate: h } = _wbFbsPvzCal;
  const firstDay = new Date(y, m, 1);
  const lastDay = new Date(y, m + 1, 0);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const todayIso = _wbFbsPvzTodayIso();
  const fmtDisp = (d) => (d
    ? `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`
    : "");
  let html = `<div class="cal-header" onclick="event.stopPropagation()">
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_wbFbsPvzCalPrevMonth()">◄</button>
    <span class="cal-title">${months[m]} ${y}</span>
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_wbFbsPvzCalNextMonth()">►</button>
  </div>
  <div class="cal-grid" onmouseleave="_wbFbsPvzCalClearHover()">`;
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
    html += `<div class="${cls}" data-date="${iso}" onclick="event.stopPropagation();_wbFbsPvzCalPickDate(${y},${m},${d})" onmouseenter="_wbFbsPvzCalHover(${y},${m},${d})">${d}</div>`;
  }
  html += `</div>`;
  if (s || e) {
    html += `<div class="cal-range-label" onclick="event.stopPropagation()">${fmtDisp(s) || "…"} — ${fmtDisp(e) || "…"}</div>`;
  }
  html += `<div class="cal-footer" onclick="event.stopPropagation()">
    <button type="button" class="secondary" onclick="event.stopPropagation();_wbFbsPvzCalPickToday()">Сегодня</button>
  </div>`;
  container.innerHTML = html;
}

function _wbFbsPvzApplyRange(start, end) {
  _wbFbsPvzCal.startDate = start;
  _wbFbsPvzCal.endDate = end;
  const from = document.getElementById("wbFbsPvzDateFrom");
  const to = document.getElementById("wbFbsPvzDateTo");
  if (from) from.value = _wbFbsPvzFmtIso(start);
  if (to) to.value = _wbFbsPvzFmtIso(end);
  _wbFbsPvzUpdateDateBtn();
  _wbFbsPvzSetInfo("");
  void loadWbFbsPvzReturns();
}

function _wbFbsPvzCalPickDate(y, m, d) {
  const date = new Date(y, m, d);
  date.setHours(0, 0, 0, 0);
  if (!_wbFbsPvzCal.startDate || (_wbFbsPvzCal.startDate && _wbFbsPvzCal.endDate)) {
    _wbFbsPvzCal.startDate = date;
    _wbFbsPvzCal.endDate = null;
    _wbFbsPvzCalRender();
    return;
  }
  let start = _wbFbsPvzCal.startDate;
  let end = date;
  if (date < start) {
    end = start;
    start = date;
  }
  if (_wbFbsPvzSpanDays(start, end) > 31) {
    _wbFbsPvzSetInfo("Период не больше 31 дня", "warn");
    _wbFbsPvzCalRender();
    return;
  }
  _wbFbsPvzCal.endDate = end;
  _wbFbsPvzCal.startDate = start;
  _wbFbsPvzCalRender();
  _wbFbsPvzApplyRange(start, new Date(end.getTime()));
  setTimeout(() => toggleWbFbsPvzDatePanel(false), 300);
}

function _wbFbsPvzCalPickToday() {
  const today = _wbFbsPvzParseIso(_wbFbsPvzTodayIso());
  if (!today) return;
  _wbFbsPvzCal.viewYear = today.getFullYear();
  _wbFbsPvzCal.viewMonth = today.getMonth();
  _wbFbsPvzApplyRange(today, new Date(today.getTime()));
  toggleWbFbsPvzDatePanel(false);
}

function _wbFbsPvzCalHover(y, m, d) {
  if (!_wbFbsPvzCal.startDate || _wbFbsPvzCal.endDate) return;
  _wbFbsPvzCal.hoveredDate = new Date(y, m, d);
  const s = _wbFbsPvzCal.startDate;
  document.querySelectorAll("#wbFbsPvzCalendar .cal-day[data-date]").forEach((el) => {
    const dt = new Date(`${el.dataset.date}T00:00:00`);
    const h2 = _wbFbsPvzCal.hoveredDate;
    const inRange = s && h2 && dt > (s < h2 ? s : h2) && dt < (s < h2 ? h2 : s);
    el.classList.toggle("cal-in-range", inRange);
  });
}

function _wbFbsPvzCalClearHover() {
  if (!_wbFbsPvzCal.hoveredDate) return;
  _wbFbsPvzCal.hoveredDate = null;
  document.querySelectorAll("#wbFbsPvzCalendar .cal-day.cal-in-range").forEach((el) => {
    el.classList.remove("cal-in-range");
  });
}

function _wbFbsPvzCalPrevMonth() {
  if (_wbFbsPvzCal.viewMonth === 0) {
    _wbFbsPvzCal.viewMonth = 11;
    _wbFbsPvzCal.viewYear -= 1;
  } else {
    _wbFbsPvzCal.viewMonth -= 1;
  }
  _wbFbsPvzCalRender();
}

function _wbFbsPvzCalNextMonth() {
  if (_wbFbsPvzCal.viewMonth === 11) {
    _wbFbsPvzCal.viewMonth = 0;
    _wbFbsPvzCal.viewYear += 1;
  } else {
    _wbFbsPvzCal.viewMonth += 1;
  }
  _wbFbsPvzCalRender();
}

function toggleWbFbsPvzDatePanel(show) {
  const panel = document.getElementById("wbFbsPvzDatePanel");
  if (!panel || wbFbsPvzState.syncing) return;
  const isVisible = panel.style.display === "flex";
  const shouldShow = show !== undefined ? Boolean(show) : !isVisible;
  panel.style.display = shouldShow ? "flex" : "none";
  if (shouldShow) _wbFbsPvzCalRender();
}
window.toggleWbFbsPvzDatePanel = toggleWbFbsPvzDatePanel;

function _wbFbsPvzFillSourceFilter() {
  const sel = document.getElementById("wbFbsPvzSourceFilter");
  if (!sel) return;
  const prev = String(sel.value || "0");
  const selected = (wbFbsPvzState.sources || []).filter((s) => s && s.selected);
  const options = [`<option value="0">Все источники</option>`];
  selected.forEach((s) => {
    const id = Number(s.id || 0);
    options.push(`<option value="${id}">${_wbFbsPvzEsc(s.name || id)}</option>`);
  });
  sel.innerHTML = options.join("");
  const stillThere = Array.from(sel.options).some((opt) => opt.value === prev);
  sel.value = stillThere ? prev : "0";
}

function _wbFbsPvzFillCategoryFilter() {
  const sel = document.getElementById("wbFbsPvzCategoryFilter");
  if (!sel) return;
  const prev = String(sel.value || "");
  const options = [`<option value="">Все категории</option>`];
  (wbFbsPvzState.categories || []).forEach((c) => {
    const name = String(c?.name || "").trim();
    if (!name) return;
    options.push(`<option value="${_wbFbsPvzEsc(name)}">${_wbFbsPvzEsc(name)}</option>`);
  });
  options.push(`<option value="__none__">Без категории</option>`);
  sel.innerHTML = options.join("");
  const stillThere = Array.from(sel.options).some((opt) => opt.value === prev);
  sel.value = stillThere ? prev : "";
}

async function loadWbFbsPvzSettings() {
  const res = await fetch("/api/wb-fbs/pvz-returns/settings", { headers: _wbFbsPvzHeaders() });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(_wbFbsPvzApiError(res, payload, "Не удалось загрузить источники"));
  }
  wbFbsPvzState.sources = Array.isArray(payload.sources) ? payload.sources : [];
  _wbFbsPvzFillSourceFilter();
  return payload;
}

function _wbFbsPvzSelectedSources() {
  return (wbFbsPvzState.sources || []).filter((s) => s && s.selected);
}

function onWbFbsPvzFilterChange() {
  if (wbFbsPvzState.syncing) return;
  _wbFbsPvzSyncFilterBtnState();
  void loadWbFbsPvzReturns();
}
window.onWbFbsPvzFilterChange = onWbFbsPvzFilterChange;

function onWbFbsPvzSearchInput() {
  if (wbFbsPvzState.syncing) return;
  _wbFbsPvzSyncFilterBtnState();
  renderWbFbsPvzTable();
}
window.onWbFbsPvzSearchInput = onWbFbsPvzSearchInput;

function _wbFbsPvzRowMatchesSearch(item, query) {
  const q = String(query || "").trim().toLocaleLowerCase("en-US");
  if (!q) return true;
  const barcodes = [
    ...(Array.isArray(item?.catalog_barcodes) ? item.catalog_barcodes : []),
    ...(Array.isArray(item?.product_barcodes) ? item.product_barcodes : []),
  ];
  const hay = [
    item?.sticker_id,
    item?.sticker_part_a,
    item?.sticker_part_b,
    item?.product_name,
    item?.article,
    item?.nm_id,
    item?.srid,
    item?.order_id,
    ...barcodes,
  ]
    .map((x) => String(x || "").trim().toLocaleLowerCase("en-US"))
    .filter(Boolean);
  return hay.some((v) => v.includes(q));
}

function _wbFbsPvzVisibleItems() {
  const items = Array.isArray(wbFbsPvzState.items) ? wbFbsPvzState.items : [];
  const q = document.getElementById("wbFbsPvzSearchFilter")?.value || "";
  if (!String(q || "").trim()) return items;
  return items.filter((item) => _wbFbsPvzRowMatchesSearch(item, q));
}

/** Return sticker under the issued date — same last-4 highlight as supply stickers. */
function _wbFbsPvzStickerHtml(item) {
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
      `<span class="wb-fbs-kiz-sticker-head">${_wbFbsPvzEsc(head)}</span>` +
      `<span class="wb-fbs-kiz-sticker-tail">${_wbFbsPvzEsc(tail)}</span>` +
      `</div>`;
  }
  return `<div class="wb-fbs-kiz-sticker"><span class="wb-fbs-kiz-sticker-tail">${_wbFbsPvzEsc(full)}</span></div>`;
}

function _wbFbsPvzProductCell(item) {
  const photo = item.product_photo
    ? `<img class="wb-fbs-product-photo" src="${_wbFbsPvzEsc(item.product_photo)}" alt="" width="144" height="144" loading="lazy">`
    : `<span class="wb-fbs-product-ph" aria-hidden="true"></span>`;
  const article = String(item.article || "").trim();
  const nm = String(item.nm_id || "").trim();
  const sub = article
    ? `Арт. ${article}${nm ? ` · nmId ${nm}` : ""}`
    : (nm ? `nmId ${nm}` : "—");
  const barcodes = Array.isArray(item.catalog_barcodes) ? item.catalog_barcodes : [];
  const barcodeHtml = barcodes.length
    ? `<div class="wb-fbs-barcodes" title="Штрихкод товара">${barcodes.map((b) =>
        `<div class="wb-fbs-barcode">${_wbFbsPvzEsc(b)}</div>`
      ).join("")}</div>`
    : "";
  const name = String(item.product_name || article || "—");
  return `<div class="wb-fbs-product">
    ${photo}
    <div class="wb-fbs-product-text">
      <div class="wb-fbs-product-name" title="${_wbFbsPvzEsc(name)}">${_wbFbsPvzEsc(name)}</div>
      <div class="wb-fbs-product-sub">${_wbFbsPvzEsc(sub)}</div>
      ${barcodeHtml}
    </div>
  </div>`;
}

function renderWbFbsPvzTable() {
  const tbody = document.getElementById("wbFbsPvzTbody");
  const count = document.getElementById("wbFbsPvzCount");
  const allItems = Array.isArray(wbFbsPvzState.items) ? wbFbsPvzState.items : [];
  const items = _wbFbsPvzVisibleItems();
  const searchQ = String(document.getElementById("wbFbsPvzSearchFilter")?.value || "").trim();
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
    const orderId = Number(item.order_id || 0);
    // Print against the FBS cabinet where the order (and КИЗ) lives — may differ
    // from the goods-return source used for sync.
    const printSourceId = Number(item.order_source_id || item.source_id || 0);
    const orderLinked = !!item.order_linked;
    const menuKey = `pvz_${index}`;
    // Enable when the return is linked to a local FBS order; print loads КИЗ
    // from marking / «Вывод КИЗ» / WB meta (same as модалка «Возвраты»).
    const canKiz = orderLinked && orderId > 0 && printSourceId > 0;
    let kizTitle = "";
    if (!orderId) kizTitle = "В возврате нет номера заказа (orderId)";
    else if (!orderLinked) kizTitle = "Заказ не найден в базе FBS";
    else if (!item.has_kiz) kizTitle = "КИЗ подтянется при печати";
    const printable = typeof _wbFbsReturnsPrintableBarcodes === "function"
      ? _wbFbsReturnsPrintableBarcodes(item.catalog_barcodes)
      : [];
    const canBarcode = printable.length > 0;
    const stickerHtml = _wbFbsPvzStickerHtml(item);
    return `<tr>
      <td class="wb-fbs-pvz-issued">
        <span class="wb-fbs-pvz-cell-label">Выдан</span>
        <span class="wb-fbs-pvz-cell-value">${_wbFbsPvzEsc(item.issued_label || "—")}</span>
        <div class="wb-fbs-sd-sticker">${stickerHtml}</div>
      </td>
      <td class="wb-fbs-sd-td-product">${_wbFbsPvzProductCell(item)}</td>
      <td class="wb-fbs-pvz-num"><span class="wb-fbs-pvz-cell-label">Кол-во</span><span class="wb-fbs-pvz-cell-value">${Number(item.qty || 1)}</span></td>
      <td class="wb-fbs-sd-td-act">
        <div class="wb-fbs-row-menu-wrap">
          <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
                  onclick="toggleWbFbsRowMenu(event, '${menuKey}')" aria-haspopup="menu">⋮</button>
          <div id="wbFbsRowMenu_${menuKey}" class="wb-fbs-row-menu wb-fbs-pvz-row-menu" data-order-id="${menuKey}" role="menu">
            <button type="button" class="wb-fbs-row-menu-item${canKiz ? "" : " is-disabled"}" role="menuitem"
                    ${canKiz ? `onclick="printWbFbsPvzKiz(${printSourceId}, ${orderId})"` : "disabled"}
                    ${canKiz ? "" : `title="${_wbFbsPvzEsc(kizTitle || "Нет КИЗ для печати")}"`}>
              Распечатать маркировку
            </button>
            <button type="button" class="wb-fbs-row-menu-item${canBarcode ? "" : " is-disabled"}" role="menuitem"
                    ${canBarcode ? `onclick="printWbFbsPvzBarcode(${index})"` : "disabled"}
                    ${canBarcode ? "" : 'title="Нет ШК в каталоге товаров"'}>
              Распечатать ШК
            </button>
          </div>
        </div>
      </td>
    </tr>`;
  }).join("");
}

async function loadWbFbsPvzReturns() {
  _wbFbsPvzEnsureDates();
  const from = document.getElementById("wbFbsPvzDateFrom")?.value || "";
  const to = document.getElementById("wbFbsPvzDateTo")?.value || "";
  const sourceId = document.getElementById("wbFbsPvzSourceFilter")?.value || "0";
  const category = document.getElementById("wbFbsPvzCategoryFilter")?.value || "";
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (sourceId && sourceId !== "0") params.set("source_id", sourceId);
  if (category) params.set("category", category);
  const tbody = document.getElementById("wbFbsPvzTbody");
  if (tbody && !wbFbsPvzState.items.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Загрузка…</td></tr>`;
  }
  try {
    const res = await fetch(`/api/wb-fbs/pvz-returns?${params.toString()}`, { headers: _wbFbsPvzHeaders() });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_wbFbsPvzApiError(res, payload, "Не удалось загрузить возвраты"));
    }
    wbFbsPvzState.items = Array.isArray(payload.items) ? payload.items : [];
    if (Array.isArray(payload.categories)) {
      wbFbsPvzState.categories = payload.categories;
      _wbFbsPvzFillCategoryFilter();
    }
    _wbFbsPvzSyncFilterBtnState();
    renderWbFbsPvzTable();
  } catch (err) {
    wbFbsPvzState.items = [];
    _wbFbsPvzSyncFilterBtnState();
    renderWbFbsPvzTable();
    _wbFbsPvzSetInfo(err?.message || String(err), "error");
  }
}

function _wbFbsPvzSetSyncing(on, label) {
  // Close panels before the syncing flag: toggles ignore calls while syncing.
  if (on) {
    toggleWbFbsPvzFilterPanel(false);
    toggleWbFbsPvzDatePanel(false);
    toggleWbFbsPvzPrintMenu(false);
  }
  wbFbsPvzState.syncing = !!on;
  const btn = document.getElementById("wbFbsPvzSyncBtn");
  const gear = document.getElementById("wbFbsPvzSettingsBtn");
  const printBtn = document.getElementById("wbFbsPvzPrintBtn");
  const filterBtn = document.getElementById("wbFbsPvzFilterBtn");
  const qrBtn = document.getElementById("wbFbsPvzQrBtn");
  const dateBtn = document.getElementById("wbFbsPvzDateBtn");
  const search = document.getElementById("wbFbsPvzSearchFilter");
  const source = document.getElementById("wbFbsPvzSourceFilter");
  const category = document.getElementById("wbFbsPvzCategoryFilter");
  if (btn) {
    btn.disabled = !!on;
    btn.textContent = on ? (label || "Запуск…") : "Синхронизировать";
    btn.setAttribute("aria-busy", on ? "true" : "false");
  }
  if (gear) gear.disabled = !!on;
  if (printBtn) printBtn.disabled = !!on;
  if (filterBtn) filterBtn.disabled = !!on;
  if (qrBtn) qrBtn.disabled = !!on;
  if (dateBtn) dateBtn.disabled = !!on;
  if (search) search.disabled = !!on;
  if (source) source.disabled = !!on;
  if (category) category.disabled = !!on;
}

async function _wbFbsPvzPoll(token) {
  const started = Date.now();
  const maxWaitMs = 20 * 60 * 1000;
  while (wbFbsPvzState.pollToken === token && Date.now() - started < maxWaitMs) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    if (wbFbsPvzState.pollToken !== token) return null;
    const res = await fetch("/api/wb-fbs/pvz-returns/sync/status", { headers: _wbFbsPvzHeaders() });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_wbFbsPvzApiError(res, payload, "Не удалось проверить статус синхронизации"));
    }
    const status = String(payload.status || "");
    const btn = document.getElementById("wbFbsPvzSyncBtn");
    if (btn && status === "running" && payload.message) btn.textContent = String(payload.message);
    if (status === "running") continue;
    return payload;
  }
  if (Date.now() - started >= maxWaitMs) {
    throw new Error("Синхронизация затянулась. Подождите и откройте окно снова.");
  }
  return null;
}

async function syncWbFbsPvzReturns() {
  if (wbFbsPvzState.syncing) return;
  if (!_wbFbsPvzSelectedSources().length) {
    alert("Выберите источники в настройках");
    openWbFbsPvzSettings();
    return;
  }
  const token = wbFbsPvzState.pollToken + 1;
  wbFbsPvzState.pollToken = token;
  _wbFbsPvzSetSyncing(true, "Запуск…");
  _wbFbsPvzSetInfo("");
  try {
    const res = await fetch("/api/wb-fbs/pvz-returns/sync", {
      method: "POST",
      headers: _wbFbsPvzHeaders(),
      body: JSON.stringify({}),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_wbFbsPvzApiError(res, payload, "Синхронизация не удалась"));
    }
    let result = payload;
    if (String(payload.status || "") === "running") {
      const btn = document.getElementById("wbFbsPvzSyncBtn");
      if (btn && payload.message) btn.textContent = String(payload.message);
      result = await _wbFbsPvzPoll(token);
    }
    if (!result || wbFbsPvzState.pollToken !== token) return;
    const status = String(result.status || "");
    const errors = Array.isArray(result.errors) ? result.errors.filter(Boolean) : [];
    if (status === "error") {
      const extra = errors.length ? ` ${errors.join(" ")}` : "";
      _wbFbsPvzSetInfo(`${result.message || "Синхронизация не удалась"}${extra}`, "error");
    } else if (errors.length) {
      _wbFbsPvzSetInfo(errors.join(" "), "warn");
    } else {
      _wbFbsPvzSetInfo("");
    }
    // Sync always covers the last 31 days — put that range in the filter and show it.
    _wbFbsPvzSetIssueDates(result.date_from, result.date_to);
    await loadWbFbsPvzReturns();
  } catch (err) {
    if (wbFbsPvzState.pollToken === token) {
      _wbFbsPvzSetInfo(err?.message || String(err), "error");
    }
  } finally {
    if (wbFbsPvzState.pollToken === token) _wbFbsPvzSetSyncing(false);
  }
}
window.syncWbFbsPvzReturns = syncWbFbsPvzReturns;

function _wbFbsPvzRenderSettings(sources) {
  const list = document.getElementById("wbFbsPvzSettingsList");
  if (!list) return;
  const rows = Array.isArray(sources) ? sources : [];
  if (!rows.length) {
    list.innerHTML = `<p class="wb-fbs-pvz-settings-empty">Нет источников WB. Добавьте их в Поставки → Настройки → Источники.</p>`;
    return;
  }
  list.innerHTML = rows.map((s) => {
    const id = Number(s.id || 0);
    const checked = s.selected ? " checked" : "";
    return `<label class="wb-fbs-pvz-check" for="wbFbsPvzSrc_${id}">
      <input type="checkbox" id="wbFbsPvzSrc_${id}" value="${id}"${checked} />
      <span>${_wbFbsPvzEsc(s.name || id)}</span>
    </label>`;
  }).join("");
}

function openWbFbsPvzSettings() {
  const modal = document.getElementById("wbFbsPvzSettingsModal");
  const info = document.getElementById("wbFbsPvzSettingsInfo");
  if (info) {
    info.hidden = true;
    info.textContent = "";
  }
  if (modal) modal.classList.remove("hidden");
  _wbFbsPvzRenderSettings(wbFbsPvzState.sources);
  void loadWbFbsPvzSettings()
    .then((payload) => _wbFbsPvzRenderSettings(payload.sources))
    .catch((err) => {
      if (!info) return;
      info.hidden = false;
      info.textContent = err?.message || String(err);
      info.classList.add("is-error");
    });
}
window.openWbFbsPvzSettings = openWbFbsPvzSettings;

function closeWbFbsPvzSettings() {
  document.getElementById("wbFbsPvzSettingsModal")?.classList.add("hidden");
}
window.closeWbFbsPvzSettings = closeWbFbsPvzSettings;

async function saveWbFbsPvzSettings() {
  const info = document.getElementById("wbFbsPvzSettingsInfo");
  const btn = document.getElementById("wbFbsPvzSettingsSaveBtn");
  const ids = Array.from(document.querySelectorAll("#wbFbsPvzSettingsList input[type=checkbox]:checked"))
    .map((el) => Number(el.value))
    .filter((id) => id > 0);
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/wb-fbs/pvz-returns/settings", {
      method: "POST",
      headers: _wbFbsPvzHeaders(),
      body: JSON.stringify({ source_ids: ids }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_wbFbsPvzApiError(res, payload, "Не удалось сохранить источники"));
    }
    wbFbsPvzState.sources = Array.isArray(payload.sources) ? payload.sources : [];
    _wbFbsPvzFillSourceFilter();
    closeWbFbsPvzSettings();
    await loadWbFbsPvzReturns();
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
window.saveWbFbsPvzSettings = saveWbFbsPvzSettings;

async function openWbFbsPvzReturnsModal() {
  const modal = document.getElementById("wbFbsPvzReturnsModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  const search = document.getElementById("wbFbsPvzSearchFilter");
  if (search) search.value = "";
  toggleWbFbsPvzFilterPanel(false);
  _wbFbsPvzEnsureDates();
  _wbFbsPvzSyncFilterBtnState();
  initWbFbsPvzColumnResizer();
  _wbFbsPvzSetInfo("");
  try {
    await loadWbFbsPvzSettings();
  } catch (err) {
    _wbFbsPvzSetInfo(err?.message || String(err), "error");
  }
  await loadWbFbsPvzReturns();
  if (!wbFbsPvzState.syncing) {
    try {
      const res = await fetch("/api/wb-fbs/pvz-returns/sync/status", { headers: _wbFbsPvzHeaders() });
      const payload = await res.json().catch(() => ({}));
      if (res.ok && String(payload.status || "") === "running") {
        const token = wbFbsPvzState.pollToken + 1;
        wbFbsPvzState.pollToken = token;
        _wbFbsPvzSetSyncing(true, payload.message || "Синхронизация…");
        const result = await _wbFbsPvzPoll(token);
        if (result && wbFbsPvzState.pollToken === token) {
          if (String(result.status || "") === "error") {
            _wbFbsPvzSetInfo(result.message || "Синхронизация не удалась", "error");
          }
          _wbFbsPvzSetIssueDates(result.date_from, result.date_to);
          await loadWbFbsPvzReturns();
        }
        if (wbFbsPvzState.pollToken === token) _wbFbsPvzSetSyncing(false);
      }
    } catch (err) {
      _wbFbsPvzSetInfo(err?.message || String(err), "error");
      _wbFbsPvzSetSyncing(false);
    }
  }
}
window.openWbFbsPvzReturnsModal = openWbFbsPvzReturnsModal;

function closeWbFbsPvzReturnsModal() {
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  toggleWbFbsPvzFilterPanel(false);
  toggleWbFbsPvzDatePanel(false);
  toggleWbFbsPvzPrintMenu(false);
  document.getElementById("wbFbsPvzReturnsModal")?.classList.add("hidden");
}
window.closeWbFbsPvzReturnsModal = closeWbFbsPvzReturnsModal;

function toggleWbFbsPvzPrintMenu(show) {
  const menu = document.getElementById("wbFbsPvzPrintMenu");
  const btn = document.getElementById("wbFbsPvzPrintBtn");
  if (!menu || !btn || wbFbsPvzState.syncing) return;
  const willOpen = show === undefined ? menu.hidden : Boolean(show);
  if (willOpen) {
    toggleWbFbsPvzDatePanel(false);
    toggleWbFbsPvzFilterPanel(false);
  }
  menu.hidden = !willOpen;
  btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
}
window.toggleWbFbsPvzPrintMenu = toggleWbFbsPvzPrintMenu;

function _wbFbsPvzMergeItems(items) {
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

function _wbFbsPvzPrintDateLabel() {
  const start = _wbFbsPvzCal.startDate;
  const end = _wbFbsPvzCal.endDate;
  if (!start || !end) {
    const from = document.getElementById("wbFbsPvzDateFrom")?.value || "";
    const to = document.getElementById("wbFbsPvzDateTo")?.value || "";
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

function _wbFbsPvzPrintTitle(mode) {
  const dateLabel = _wbFbsPvzPrintDateLabel();
  if (String(mode || "") === "merged") {
    return dateLabel ? `Возвраты ПВЗ (${dateLabel})` : "Возвраты ПВЗ";
  }
  return dateLabel
    ? `Возвраты ПВЗ (${dateLabel}) — весь список`
    : "Возвраты ПВЗ — весь список";
}

function _wbFbsPvzPrintHtml(rows, title, mode) {
  const list = Array.isArray(rows) ? rows : [];
  const total = list.reduce((sum, row) => sum + Math.max(1, Number(row?.qty || 1) || 1), 0);
  const merged = String(mode || "") === "merged";
  const body = list.length
    ? list.map((row) => {
      const name = _wbFbsPvzEsc(row.product_name || row.article || "—");
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
    th.name, td.name { width: 70%; }
    th.qty, td.qty { width: 15%; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
    th.defect, td.defect { width: 15%; text-align: left; }
    td.defect { min-height: 24px; }
    th, td { padding: 8px 10px; border-bottom: 1px solid #cbd5e1; }
    table { border: 1px solid #cbd5e1; }
    th { background: #f8fafc; border-bottom: 1px solid #cbd5e1; }
    `
    : `
    th.qty, td.qty { text-align: right; white-space: nowrap; width: 72px; font-variant-numeric: tabular-nums; }
    th, td { padding: 8px 0; border-bottom: 1px solid #e2e8f0; }
    `;
  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>${_wbFbsPvzEsc(title || "Возвраты ПВЗ")}</title>
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
  <h1>${_wbFbsPvzEsc(title || "Возвраты ПВЗ")}</h1>
  <p class="meta">Строк: ${list.length} · Количество: ${total}</p>
  <table>
    <thead>${head}</thead>
    <tbody>${body}</tbody>
  </table>
  <script>window.addEventListener("load", function () { window.focus(); window.print(); });</script>
</body>
</html>`;
}

function printWbFbsPvzList(mode) {
  toggleWbFbsPvzPrintMenu(false);
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  const items = _wbFbsPvzVisibleItems();
  if (!items.length) {
    _wbFbsPvzSetInfo("Нет строк для печати. Синхронизируйте или смените фильтр.", "warn");
    return;
  }
  // Menu only offers the merged pick-list layout; keep full mode for API/compat.
  const merged = String(mode || "") !== "full";
  const rows = merged
    ? _wbFbsPvzMergeItems(items)
    : items.map((item) => ({
      product_name: String(item.product_name || item.article || "—"),
      qty: Math.max(1, Number(item.qty || 1) || 1),
    }));
  const title = _wbFbsPvzPrintTitle(merged ? "merged" : "full");
  const win = window.open("", "_blank");
  if (!win) {
    _wbFbsPvzSetInfo("Разрешите всплывающие окна для печати", "warn");
    return;
  }
  win.document.write(_wbFbsPvzPrintHtml(rows, title, merged ? "merged" : "full"));
  win.document.close();
}
window.printWbFbsPvzList = printWbFbsPvzList;

function _wbFbsPvzQrMakeDataUrl(text) {
  if (typeof _wbFbsMakeQrDataUrl === "function") {
    return _wbFbsMakeQrDataUrl(text, 512);
  }
  return Promise.reject(new Error("Библиотека QR ещё загружается. Попробуйте снова."));
}

function _wbFbsPvzReturnQrLabels(items) {
  const favicon = (typeof _fpPrintFaviconLink === "string" && _fpPrintFaviconLink)
    ? _fpPrintFaviconLink
    : "";
  const sheets = (items || []).map((item) => {
    const sticker = _wbFbsPvzEsc(item.sticker_id);
    const source = _wbFbsPvzEsc(item.source_name || item.source_id || "");
    const product = _wbFbsPvzEsc(String(item.product_name || item.article || "").trim());
    const qr = String(item.qr_data_url || "");
    return `<section class="sheet">
  <div class="rail"><div class="rail-inner">${sticker}</div></div>
  <div class="qr-wrap"><img class="qr" alt="QR ${sticker}" src="${qr}" /></div>
  <div class="rail"><div class="rail-inner">${source || "возврат"}</div></div>
  ${product ? `<div class="caption">${product}</div>` : ""}
</section>`;
  }).join("\n");
  return `<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<title>QR возвратов ПВЗ</title>
${favicon}
<style>
@page { size: 58mm 40mm; margin: 0; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { margin: 0; padding: 0; background: #fff; color: #000;
  font-family: Arial, Helvetica, sans-serif; }
.toolbar { padding: 8px 12px; }
.toolbar button {
  font: 14px/1.2 Arial, Helvetica, sans-serif; padding: 6px 12px; cursor: pointer;
}
.toolbar span { margin-left: 8px; color: #64748b; font-size: 13px; }
.sheet {
  position: relative;
  width: 58mm; height: 40mm; overflow: hidden;
  display: grid;
  grid-template-columns: 11mm 1fr 11mm;
  align-items: center;
  column-gap: 1.5mm;
  padding: 2mm 1.5mm;
  page-break-after: always;
}
.sheet:last-child { page-break-after: auto; }
.rail {
  height: 36mm; width: 11mm;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden;
}
.rail-inner {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  transform: rotate(-90deg);
  white-space: nowrap;
  font-weight: 700; font-size: 3mm; line-height: 1.1;
  letter-spacing: 0.02em; text-align: center;
  max-width: 34mm;
  overflow: hidden;
  text-overflow: ellipsis;
}
.qr-wrap {
  height: 30mm;
  display: flex; align-items: center; justify-content: center;
}
.qr {
  width: 26mm; height: 26mm;
  object-fit: contain;
  display: block;
}
.caption {
  position: absolute;
  left: 12mm; right: 12mm; bottom: 1.2mm;
  font-size: 2.2mm; line-height: 1.15; font-weight: 600;
  text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
@media print {
  .toolbar { display: none !important; }
  html, body { width: 58mm; background: #fff; }
}
</style></head><body>
<div class="toolbar">
  <button type="button" onclick="window.print()">Печать</button>
  <span>QR возвратов · ${(items || []).length} шт. · 58×40 мм</span>
</div>
${sheets}
<script>window.addEventListener("load", function () { window.focus(); window.print(); });</script>
</body></html>`;
}

async function printWbFbsPvzReturnQrs() {
  if (wbFbsPvzState.syncing) return;
  toggleWbFbsPvzPrintMenu(false);
  toggleWbFbsPvzFilterPanel(false);
  toggleWbFbsPvzDatePanel(false);
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();

  const selected = _wbFbsPvzSelectedSources();
  if (!selected.length) {
    alert("Выберите источники в настройках");
    openWbFbsPvzSettings();
    return;
  }
  const selectedIds = new Set(selected.map((s) => Number(s.id || 0)).filter((id) => id > 0));
  const seen = new Set();
  const candidates = [];
  (wbFbsPvzState.items || []).forEach((item) => {
    const sourceId = Number(item?.source_id || 0);
    const sticker = String(item?.sticker_id || "").trim();
    if (!sticker || !selectedIds.has(sourceId) || seen.has(sticker)) return;
    seen.add(sticker);
    candidates.push({
      sticker_id: sticker,
      source_id: sourceId,
      source_name: String(item.source_name || "").trim(),
      product_name: String(item.product_name || item.article || "").trim(),
      article: String(item.article || "").trim(),
    });
  });
  if (!candidates.length) {
    _wbFbsPvzSetInfo(
      "Нет stickerId для печати QR. Синхронизируйте возвраты за выбранные даты.",
      "warn",
    );
    return;
  }

  const qrBtn = document.getElementById("wbFbsPvzQrBtn");
  if (qrBtn) {
    qrBtn.disabled = true;
    qrBtn.setAttribute("aria-busy", "true");
  }
  _wbFbsPvzSetInfo(`Готовим QR: ${candidates.length}…`);
  try {
    const withQr = [];
    for (let i = 0; i < candidates.length; i += 1) {
      const row = candidates[i];
      const qr_data_url = await _wbFbsPvzQrMakeDataUrl(row.sticker_id);
      withQr.push({ ...row, qr_data_url });
      if (qrBtn && (i + 1) % 5 === 0) {
        _wbFbsPvzSetInfo(`Готовим QR: ${i + 1}/${candidates.length}…`);
      }
    }
    const win = window.open("", "_blank");
    if (!win) {
      _wbFbsPvzSetInfo("Разрешите всплывающие окна для печати", "warn");
      return;
    }
    win.document.write(_wbFbsPvzReturnQrLabels(withQr));
    win.document.close();
    _wbFbsPvzSetInfo("");
  } catch (err) {
    _wbFbsPvzSetInfo(err?.message || String(err), "error");
  } finally {
    if (qrBtn) {
      qrBtn.disabled = !!wbFbsPvzState.syncing;
      qrBtn.setAttribute("aria-busy", "false");
    }
  }
}
window.printWbFbsPvzReturnQrs = printWbFbsPvzReturnQrs;

function printWbFbsPvzBarcode(index) {
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  const item = _wbFbsPvzVisibleItems()[Number(index)];
  if (!item) return;
  const barcodes = typeof _wbFbsReturnsPrintableBarcodes === "function"
    ? _wbFbsReturnsPrintableBarcodes(item.catalog_barcodes)
    : [];
  if (!barcodes.length) {
    _wbFbsPvzSetInfo("У товара нет ШК в каталоге (Настройки → Товары)", "warn");
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
window.printWbFbsPvzBarcode = printWbFbsPvzBarcode;

async function printWbFbsPvzKiz(sourceId, orderId) {
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  const sid = Number(sourceId || 0);
  const oid = Number(orderId || 0);
  if (!sid || !oid) return;
  try {
    const params = new URLSearchParams({ source_id: String(sid), order_id: String(oid) });
    const res = await fetch(`/api/wb-fbs/returns/print?${params.toString()}`);
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(_wbFbsPvzApiError(res, payload, "Не удалось подготовить печать"));
    }
    const dm = String(payload.datamatrix_png || "").trim();
    if (!dm) throw new Error("Сервер не вернул Data Matrix");
    const win = window.open("", "_blank");
    if (!win) {
      _wbFbsPvzSetInfo("Разрешите всплывающие окна для печати КИЗ", "warn");
      return;
    }
    const dmUrl = `data:image/png;base64,${dm}`;
    win.document.write(_wbFbsReturnsPrintHtml({
      productName: String(payload.product_name || ""),
      stickerNumber: String(payload.assembly_sticker_number || ""),
      gtin14: String(payload.gtin14 || ""),
      serial: String(payload.kiz_serial || ""),
    }, dmUrl));
    win.document.close();
  } catch (err) {
    _wbFbsPvzSetInfo(err?.message || String(err), "error");
  }
}
window.printWbFbsPvzKiz = printWbFbsPvzKiz;

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const settings = document.getElementById("wbFbsPvzSettingsModal");
  if (settings && !settings.classList.contains("hidden")) {
    closeWbFbsPvzSettings();
    return;
  }
  const datePanel = document.getElementById("wbFbsPvzDatePanel");
  if (datePanel && datePanel.style.display === "flex") {
    toggleWbFbsPvzDatePanel(false);
    return;
  }
  const filterPanel = document.getElementById("wbFbsPvzFilterPanel");
  if (filterPanel && !filterPanel.hidden) {
    toggleWbFbsPvzFilterPanel(false);
    return;
  }
  const printMenu = document.getElementById("wbFbsPvzPrintMenu");
  if (printMenu && !printMenu.hidden) {
    toggleWbFbsPvzPrintMenu(false);
    return;
  }
  const modal = document.getElementById("wbFbsPvzReturnsModal");
  if (modal && !modal.classList.contains("hidden")) closeWbFbsPvzReturnsModal();
});

document.addEventListener("click", (event) => {
  const target = event.target;
  const printWrap = document.querySelector("#wbFbsPvzReturnsModal .wb-fbs-pvz-print-wrap");
  const printMenu = document.getElementById("wbFbsPvzPrintMenu");
  if (printWrap && printMenu && !printMenu.hidden && !printWrap.contains(target)) {
    toggleWbFbsPvzPrintMenu(false);
  }
  const filterWrap = document.querySelector("#wbFbsPvzReturnsModal .wb-fbs-pvz-filter-wrap");
  const filterPanel = document.getElementById("wbFbsPvzFilterPanel");
  if (filterWrap && filterPanel && !filterPanel.hidden && !filterWrap.contains(target)) {
    toggleWbFbsPvzFilterPanel(false);
  }
  const dateWrap = document.querySelector("#wbFbsPvzReturnsModal .wb-fbs-pvz-date-wrap");
  const datePanel = document.getElementById("wbFbsPvzDatePanel");
  if (
    dateWrap &&
    datePanel &&
    datePanel.style.display === "flex" &&
    !dateWrap.contains(target)
  ) {
    toggleWbFbsPvzDatePanel(false);
  }
});
