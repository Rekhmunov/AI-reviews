/* WB FBS «Возвраты ПВЗ». Loaded after app.js. */

const wbFbsPvzState = {
  sources: [],
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

function _wbFbsPvzUpdateDateBtn() {
  const btn = document.getElementById("wbFbsPvzDateBtn");
  if (!btn) return;
  const start = _wbFbsPvzCal.startDate;
  const end = _wbFbsPvzCal.endDate;
  if (!start || !end) {
    btn.textContent = "📅";
    return;
  }
  const fmt = (d) => d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
  btn.textContent = start.getTime() === end.getTime()
    ? fmt(start)
    : `${fmt(start)}–${fmt(end)}`;
}

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
  void loadWbFbsPvzReturns();
}
window.onWbFbsPvzFilterChange = onWbFbsPvzFilterChange;

function _wbFbsPvzProductCell(item) {
  const photo = item.product_photo
    ? `<img class="wb-fbs-product-photo" src="${_wbFbsPvzEsc(item.product_photo)}" alt="" width="72" height="72" loading="lazy">`
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
  const items = Array.isArray(wbFbsPvzState.items) ? wbFbsPvzState.items : [];
  if (count) count.textContent = `В таблице: ${items.length}`;
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="wb-fbs-empty">Нет выданных возвратов за этот период. Нажмите «Синхронизировать».</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((item, index) => {
    const orderId = Number(item.order_id || 0);
    const sourceId = Number(item.source_id || 0);
    const menuKey = `pvz_${index}`;
    const canKiz = !!item.has_kiz && orderId > 0 && sourceId > 0;
    const printable = typeof _wbFbsReturnsPrintableBarcodes === "function"
      ? _wbFbsReturnsPrintableBarcodes(item.catalog_barcodes)
      : [];
    const canBarcode = printable.length > 0;
    return `<tr>
      <td class="wb-fbs-sd-td-product">${_wbFbsPvzProductCell(item)}</td>
      <td class="wb-fbs-pvz-num"><span class="wb-fbs-pvz-cell-label">Кол-во</span><span class="wb-fbs-pvz-cell-value">${Number(item.qty || 1)}</span></td>
      <td class="wb-fbs-pvz-issued"><span class="wb-fbs-pvz-cell-label">Выдан</span><span class="wb-fbs-pvz-cell-value">${_wbFbsPvzEsc(item.issued_label || "—")}</span></td>
      <td class="wb-fbs-sd-td-act">
        <div class="wb-fbs-row-menu-wrap">
          <button type="button" class="icon-btn secondary wb-fbs-row-menu-btn" title="Действия"
                  onclick="toggleWbFbsRowMenu(event, '${menuKey}')" aria-haspopup="menu">⋮</button>
          <div id="wbFbsRowMenu_${menuKey}" class="wb-fbs-row-menu wb-fbs-pvz-row-menu" data-order-id="${menuKey}" role="menu">
            <button type="button" class="wb-fbs-row-menu-item${canKiz ? "" : " is-disabled"}" role="menuitem"
                    ${canKiz ? `onclick="printWbFbsPvzKiz(${sourceId}, ${orderId})"` : "disabled"}
                    ${canKiz ? "" : 'title="Нет КИЗ для печати"'}>
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
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  if (sourceId && sourceId !== "0") params.set("source_id", sourceId);
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
    renderWbFbsPvzTable();
  } catch (err) {
    wbFbsPvzState.items = [];
    renderWbFbsPvzTable();
    _wbFbsPvzSetInfo(err?.message || String(err), "error");
  }
}

function _wbFbsPvzSetSyncing(on, label) {
  // Close the calendar before the syncing flag: the toggle ignores calls while syncing.
  if (on) toggleWbFbsPvzDatePanel(false);
  wbFbsPvzState.syncing = !!on;
  const btn = document.getElementById("wbFbsPvzSyncBtn");
  const gear = document.getElementById("wbFbsPvzSettingsBtn");
  const dateBtn = document.getElementById("wbFbsPvzDateBtn");
  const source = document.getElementById("wbFbsPvzSourceFilter");
  if (btn) {
    btn.disabled = !!on;
    btn.textContent = on ? (label || "Запуск…") : "Синхронизировать";
    btn.setAttribute("aria-busy", on ? "true" : "false");
  }
  if (gear) gear.disabled = !!on;
  if (dateBtn) dateBtn.disabled = !!on;
  if (source) source.disabled = !!on;
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
  _wbFbsPvzEnsureDates();
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
      body: JSON.stringify({
        date_from: document.getElementById("wbFbsPvzDateFrom")?.value || "",
        date_to: document.getElementById("wbFbsPvzDateTo")?.value || "",
      }),
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
  _wbFbsPvzEnsureDates();
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
  toggleWbFbsPvzDatePanel(false);
  document.getElementById("wbFbsPvzReturnsModal")?.classList.add("hidden");
}
window.closeWbFbsPvzReturnsModal = closeWbFbsPvzReturnsModal;

function printWbFbsPvzBarcode(index) {
  if (typeof _wbFbsCloseRowMenus === "function") _wbFbsCloseRowMenus();
  const item = (wbFbsPvzState.items || [])[Number(index)];
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
  const modal = document.getElementById("wbFbsPvzReturnsModal");
  if (modal && !modal.classList.contains("hidden")) closeWbFbsPvzReturnsModal();
});
