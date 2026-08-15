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
    loadSeq: 0,
  };

  const LS_SOURCE = "wb_fbs_tsd_source_id";

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

  function setBanner(text, kind) {
    state.banner = text ? { text: String(text), kind: kind || "info" } : null;
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

  function hasCyrillic(s) {
    return /[А-Яа-яЁё]/.test(String(s || ""));
  }

  function scanKey(s) {
    return normalizeScan(s).toLowerCase();
  }

  function digitsOnly(s) {
    return String(s || "").replace(/\D+/g, "");
  }

  function findBySticker(rows, raw) {
    const scan = normalizeScan(raw);
    if (!scan) return { row: null, ambiguous: false };
    const key = scanKey(scan);
    const dig = digitsOnly(scan);
    const matches = (rows || []).filter((r) => {
      const full = normalizeScan(r.sticker_number || r.sticker || "");
      if (!full) return false;
      if (scanKey(full) === key) return true;
      const fd = digitsOnly(full);
      return dig && fd && (fd === dig || fd.endsWith(dig) || dig.endsWith(fd));
    });
    if (matches.length === 1) return { row: matches[0], ambiguous: false };
    if (matches.length > 1) {
      const exact = matches.find((r) => scanKey(r.sticker_number) === key);
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
    const s = normalizeScan(mark);
    // AI 01 + GTIN-14
    const m = s.match(/^01(\d{14})/);
    return m ? m[1] : "";
  }

  function barcodeCandidates(row) {
    const list = [];
    const barcodes = Array.isArray(row.barcodes) ? row.barcodes : [];
    const skus = Array.isArray(row.skus) ? row.skus : [];
    for (const x of barcodes.concat(skus)) {
      const d = digitsOnly(x);
      if (d) list.push(d);
    }
    return list;
  }

  function markMatchesOrder(mark, row) {
    const gtin = gtinFromMark(mark);
    if (!gtin) {
      // Accept full CIS without strict GTIN if order has no barcodes to compare.
      if (!barcodeCandidates(row).length && normalizeScan(mark).length >= 20) return { ok: true };
      return { ok: false, error: "Не похоже на КИЗ (ожидается код маркировки)" };
    }
    const cands = barcodeCandidates(row);
    if (!cands.length) return { ok: true };
    const gtinTrim = gtin.replace(/^0+/, "") || gtin;
    const ok = cands.some((b) => {
      const bb = b.replace(/^0+/, "") || b;
      return b === gtin || bb === gtinTrim || gtin.endsWith(b) || b.endsWith(gtinTrim);
    });
    if (!ok) return { ok: false, error: "КИЗ не совпадает со штрихкодом товара в заказе" };
    return { ok: true };
  }

  function eanMatchesOrder(raw, row) {
    const dig = digitsOnly(raw);
    if (!(dig.length === 8 || dig.length === 12 || dig.length === 13 || dig.length === 14)) {
      return { ok: false, error: "Ожидается штрихкод EAN (8/13 цифр)" };
    }
    const cands = barcodeCandidates(row);
    if (!cands.length) return { ok: true };
    const ok = cands.some((b) => b === dig || b.endsWith(dig) || dig.endsWith(b));
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
              `<option value="${esc(s.id)}">${esc(s.name || "Источник " + s.id)}</option>`
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
    const data = await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(supplyId)}/kiz?${params}`
    );
    state.kizRows = Array.isArray(data.rows) ? data.rows.map((r) => ({ ...r })) : [];
  }

  async function loadPick(supplyId) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const data = await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(supplyId)}/pick-verify?${params}`
    );
    state.pickRows = Array.isArray(data.rows) ? data.rows.map((r) => ({ ...r })) : [];
  }

  async function saveKizLocal(row) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const codes = (Array.isArray(row.kiz_codes) ? row.kiz_codes : [])
      .map((c) => String(c || "").trim())
      .filter(Boolean);
    await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/kiz?${params}`,
      {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({
          items: [
            {
              order_id: Number(row.order_id),
              kiz_codes: codes,
              clear: !codes.length,
              local_only: true,
              expected_saved_at: String(row.kiz_saved_at || ""),
            },
          ],
        }),
        keepalive: true,
      }
    );
  }

  async function savePickLocal(row) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/pick-verify?${params}`,
      {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({
          items: [
            {
              order_id: Number(row.order_id),
              pick_verified: !!row.pick_verified,
              pick_barcode: String(row.pick_barcode || "").trim(),
              local_only: true,
            },
          ],
        }),
        keepalive: true,
      }
    );
  }

  function renderDenied() {
    const main = document.getElementById("tsdMain");
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
    if (prog) prog.hidden = true;
    if (back) {
      back.hidden = false;
      back.href = "/app";
      back.onclick = null;
      back.textContent = "←";
    }
    title.textContent = "ТСД · На сборке";

    if (!state.sources.length) {
      main.innerHTML = `<div class="tsd-empty">Нет доступных кабинетов ВБ ФБС для ТСД</div>`;
      return;
    }
    if (!state.supplies.length) {
      main.innerHTML = `
        <input class="tsd-search" id="tsdSearch" type="search" placeholder="Поиск поставки…" value="${esc(state.search)}" />
        <div class="tsd-empty">Нет поставок на сборке</div>`;
      wireSearch();
      return;
    }
    main.innerHTML = `
      <input class="tsd-search" id="tsdSearch" type="search" placeholder="Поиск поставки…" value="${esc(state.search)}" />
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
    wireSearch();
    main.querySelectorAll("[data-open-supply]").forEach((btn) => {
      btn.addEventListener("click", () => {
        navigate(`#/s/${btn.getAttribute("data-open-supply")}`);
      });
    });
  }

  function wireSearch() {
    const input = document.getElementById("tsdSearch");
    if (!input) return;
    let t = null;
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        state.search = String(input.value || "").trim();
        try {
          await loadSupplies();
          renderList();
          const again = document.getElementById("tsdSearch");
          if (again) {
            again.focus();
            const v = again.value;
            again.setSelectionRange(v.length, v.length);
          }
        } catch (e) {
          toast(e.message || e);
        }
      }, 280);
    });
  }

  function renderHub() {
    const s = state.supply || {};
    const sid = String(s.supply_id || state.route.supplyId || "");
    const main = document.getElementById("tsdMain");
    const back = document.getElementById("tsdBackBtn");
    const title = document.getElementById("tsdTitle");
    const prog = document.getElementById("tsdProgressBar");
    if (prog) prog.hidden = true;
    if (back) {
      back.hidden = false;
      back.href = "#/";
      back.onclick = (ev) => {
        ev.preventDefault();
        navigate("#/");
      };
      back.textContent = "←";
    }
    title.textContent = "Поставка";

    const kiz = s.kiz || { done: 0, total: 0 };
    const pick = s.pick || { done: 0, total: 0 };
    const kizDisabled = !kiz.total;
    const pickDisabled = !pick.total;

    main.innerHTML = `
      <h1 class="tsd-hub-name">${esc(s.name || sid)}</h1>
      <div class="tsd-hub-meta">
        <div>QR: <strong>${esc(sid)}</strong></div>
        <div>${esc(ordersBoxesText(s))}</div>
        <div>Склад: <strong>${esc(s.warehouse_label || "—")}</strong></div>
      </div>
      <div class="tsd-tiles">
        <button type="button" class="tsd-tile" id="tsdTileKiz" ${kizDisabled ? "disabled" : ""}>
          <span class="tsd-tile-kicker">Маркировка</span>
          <span class="tsd-tile-title">КИЗ</span>
          <span class="tsd-tile-prog">${kizDisabled ? "Нет заказов с КИЗ" : `${kiz.done} / ${kiz.total}`}</span>
        </button>
        <button type="button" class="tsd-tile" id="tsdTilePick" ${pickDisabled ? "disabled" : ""}>
          <span class="tsd-tile-kicker">Проверка</span>
          <span class="tsd-tile-title">ШК</span>
          <span class="tsd-tile-prog">${pickDisabled ? "Нет заказов без КИЗ" : `${pick.done} / ${pick.total}`}</span>
        </button>
      </div>`;

    const kizBtn = document.getElementById("tsdTileKiz");
    const pickBtn = document.getElementById("tsdTilePick");
    if (kizBtn && !kizDisabled) {
      kizBtn.addEventListener("click", () => navigate(`#/s/${sid}/kiz`));
    }
    if (pickBtn && !pickDisabled) {
      pickBtn.addEventListener("click", () => navigate(`#/s/${sid}/pick`));
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
    prog.hidden = total <= 0;
    fill.style.width = total ? `${Math.round((100 * done) / total)}%` : "0%";
  }

  function renderScan() {
    const mode = state.route.mode;
    const sid = state.route.supplyId;
    const main = document.getElementById("tsdMain");
    const back = document.getElementById("tsdBackBtn");
    const title = document.getElementById("tsdTitle");
    if (back) {
      back.hidden = false;
      back.href = `#/s/${sid}`;
      back.onclick = (ev) => {
        ev.preventDefault();
        state.pendingOrderId = null;
        state.step = "sticker";
        setBanner(null);
        navigate(`#/s/${sid}`);
      };
      back.textContent = "←";
    }
    title.textContent = mode === "kiz" ? "Маркировка" : "Проверка ШК";
    updateProgressBar(mode);

    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const fn = mode === "kiz" ? rowKizFilled : rowPickFilled;
    const { total, done, left } = countProgress(rows, fn);
    const pending = rows.find((r) => Number(r.order_id) === Number(state.pendingOrderId));
    const step = state.step;
    const banner = state.banner;

    let body = "";
    if (!total) {
      body = `<div class="tsd-empty">Нет заказов в этом режиме</div>`;
    } else if (step === "sticker" || !pending) {
      body = `
        <div class="tsd-scan-card">
          <div class="tsd-scan-step">Шаг 1</div>
          <p class="tsd-scan-prompt">Сканируйте стикер заказа</p>
          <input class="tsd-scan-input" id="tsdScanInput" type="text" autocomplete="off" inputmode="none" />
        </div>`;
    } else {
      const photo = pending.product_photo
        ? `<img src="${esc(pending.product_photo)}" alt="" width="64" height="64" />`
        : "";
      const prompt =
        mode === "kiz" ? "Сканируйте КИЗ" : "Сканируйте штрихкод товара";
      body = `
        <div class="tsd-scan-card">
          <div class="tsd-scan-step">Шаг 2</div>
          <p class="tsd-scan-prompt">${prompt}</p>
          <div class="tsd-scan-context">Заказ ${esc(pending.order_id)} · стикер ${esc(pending.sticker_number || "—")}</div>
          <input class="tsd-scan-input" id="tsdScanInput" type="text" autocomplete="off" inputmode="none" />
          <div class="tsd-product">${photo}<div>
            <div class="tsd-product-name">${esc(pending.product_name || pending.article || "—")}</div>
            <div class="tsd-product-sub">${esc([pending.brand, pending.article].filter(Boolean).join(" · "))}</div>
          </div></div>
          <div class="tsd-scan-actions">
            <button type="button" class="tsd-btn tsd-btn-ghost tsd-btn-block" id="tsdCancelStep">Отмена шага</button>
          </div>
        </div>`;
    }

    main.innerHTML = `
      <div class="tsd-scan-shell">
        <div class="tsd-stats">
          <span>Готово ${done} / ${total}</span>
          <span>Осталось ${left}</span>
        </div>
        ${
          banner
            ? `<div class="tsd-banner is-${esc(banner.kind)}">${esc(banner.text)}</div>`
            : ""
        }
        ${body}
      </div>`;

    const input = document.getElementById("tsdScanInput");
    if (input) {
      setTimeout(() => input.focus(), 40);
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          onScanEnter(input);
        }
      });
      input.addEventListener("input", () => {
        if (hasCyrillic(input.value)) {
          setBanner("Русская раскладка — переключите на EN", "warn");
          renderScan();
        }
      });
    }
    const cancel = document.getElementById("tsdCancelStep");
    if (cancel) {
      cancel.addEventListener("click", () => {
        state.pendingOrderId = null;
        state.step = "sticker";
        setBanner(null);
        renderScan();
      });
    }
  }

  async function onScanEnter(input) {
    const mode = state.route.mode;
    const raw = String(input.value || "");
    if (!normalizeScan(raw)) return;
    if (hasCyrillic(raw)) {
      setBanner("Русская раскладка — переключите на EN", "warn");
      beep(false);
      input.select();
      renderScan();
      return;
    }

    if (state.step === "sticker" || !state.pendingOrderId) {
      const rows = mode === "kiz" ? state.kizRows : state.pickRows;
      const found = findBySticker(rows, raw);
      if (found.ambiguous) {
        setBanner("Стикер совпал у нескольких заказов — сканируйте QR ещё раз", "err");
        beep(false);
        input.select();
        renderScan();
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
        renderScan();
        return;
      }
      state.pendingOrderId = Number(found.row.order_id);
      state.step = mode === "kiz" ? "mark" : "sku";
      setBanner(null);
      beep(true);
      renderScan();
      return;
    }

    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const row = rows.find((r) => Number(r.order_id) === Number(state.pendingOrderId));
    if (!row) {
      state.pendingOrderId = null;
      state.step = "sticker";
      renderScan();
      return;
    }

    try {
      if (mode === "kiz") {
        const mark = normalizeScan(raw);
        const check = markMatchesOrder(mark, row);
        if (!check.ok) {
          setBanner(check.error || "КИЗ не подходит", "err");
          beep(false);
          input.select();
          renderScan();
          return;
        }
        const dup = state.kizRows.find((r) =>
          (Array.isArray(r.kiz_codes) ? r.kiz_codes : []).some(
            (c) => normalizeScan(c) === mark
          )
        );
        if (dup) {
          setBanner(`Этот КИЗ уже в заказе ${dup.order_id}`, "err");
          beep(false);
          input.select();
          renderScan();
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
        await saveKizLocal(row);
        setBanner(`КИЗ записан · заказ ${row.order_id}`, "ok");
      } else {
        const check = eanMatchesOrder(raw, row);
        if (!check.ok) {
          setBanner(check.error || "ШК не подходит", "err");
          beep(false);
          input.select();
          renderScan();
          return;
        }
        row.pick_verified = true;
        row.pick_barcode = digitsOnly(raw);
        await savePickLocal(row);
        setBanner(`ШК подтверждён · заказ ${row.order_id}`, "ok");
      }
      beep(true);
      state.pendingOrderId = null;
      state.step = "sticker";
      renderScan();
    } catch (e) {
      setBanner(e.message || String(e), "err");
      beep(false);
      renderScan();
    }
  }

  async function onRoute() {
    if (!boot.can_view_wb_fbs_tsd) {
      renderDenied();
      return;
    }
    state.route = parseHash();
    const seq = ++state.loadSeq;
    const main = document.getElementById("tsdMain");
    main.innerHTML = `<div class="tsd-loading">Загрузка…</div>`;
    try {
      if (!state.sources.length) await loadSources();
      if (seq !== state.loadSeq) return;

      if (state.route.view === "list") {
        state.pendingOrderId = null;
        state.step = "sticker";
        state.banner = null;
        await loadSupplies();
        if (seq !== state.loadSeq) return;
        renderList();
        return;
      }

      if (!state.sourceId) {
        main.innerHTML = `<div class="tsd-empty">Выберите кабинет</div>`;
        return;
      }

      if (state.route.view === "hub") {
        state.pendingOrderId = null;
        state.step = "sticker";
        state.banner = null;
        await loadSummary(state.route.supplyId);
        if (seq !== state.loadSeq) return;
        renderHub();
        return;
      }

      if (state.route.view === "scan") {
        if (state.route.mode === "kiz") await loadKiz(state.route.supplyId);
        else await loadPick(state.route.supplyId);
        if (seq !== state.loadSeq) return;
        if (!state.step) state.step = "sticker";
        renderScan();
      }
    } catch (e) {
      if (seq !== state.loadSeq) return;
      main.innerHTML = `<div class="tsd-empty" style="color:#b91c1c">${esc(e.message || e)}</div>`;
    }
  }

  function bindChrome() {
    const sel = document.getElementById("tsdSourceSelect");
    if (sel) {
      sel.addEventListener("change", async () => {
        state.sourceId = sel.value ? Number(sel.value) : null;
        if (state.sourceId) localStorage.setItem(LS_SOURCE, String(state.sourceId));
        if (state.route.view !== "list") navigate("#/");
        else {
          try {
            await loadSupplies();
            renderList();
          } catch (e) {
            toast(e.message || e);
          }
        }
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
