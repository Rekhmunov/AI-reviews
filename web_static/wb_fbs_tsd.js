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
    loadSeq: 0,
    forceSaveByOrder: {},
    sessionScannedIds: [],
    saving: false,
    clearing: false,
    loadUi: {
      token: 0,
      hintTimer: null,
      elapsedTimer: null,
      rotateTimer: null,
      startedAt: 0,
    },
  };

  const LS_SOURCE = "wb_fbs_tsd_source_id";

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

  /** Parity with desktop `_wbFbsKizNormalizeMark` (WB push / Save). */
  function normalizeKizMark(value) {
    // Scanners often emit ↔ instead of GS (\\u001D). Do not use \\s strip —
    // it must not destroy GS separators in Honest Sign / sgtin payloads.
    return fixRuKeyboardLayout(
      String(value || "")
        .replace(/\u2194/g, "\u001D")
        .replace(/\r?\n/g, "")
    ).trim();
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
    // Parity with desktop: primary sticker_barcode (QR/1D), then partA+partB / number.
    const scan = normalizeScan(raw);
    if (!scan) return { row: null, ambiguous: false };
    const rawKey = scanKey(scan);
    const byBarcode = [];
    for (const row of rows || []) {
      const bc = normalizeScan(row.sticker_barcode);
      if (bc && scanKey(bc) === rawKey) byBarcode.push(row);
    }
    if (byBarcode.length === 1) return { row: byBarcode[0], ambiguous: false };
    if (byBarcode.length > 1) {
      return { row: null, ambiguous: true, matches: byBarcode };
    }

    const digits = digitsOnly(scan);
    const matches = [];
    for (const row of rows || []) {
      const full = normalizeScan(row.sticker_number || row.sticker || "");
      const partA = normalizeScan(row.sticker_part_a);
      const partB = normalizeScan(row.sticker_part_b);
      if (
        (full && (rawKey === scanKey(full) || (digits && digits === digitsOnly(full)))) ||
        (partA && partB && digits && digits === digitsOnly(`${partA}${partB}`)) ||
        (partB && (rawKey === scanKey(partB) || (digits && digits === digitsOnly(partB))))
      ) {
        matches.push(row);
      }
    }
    if (matches.length === 1) return { row: matches[0], ambiguous: false };
    if (matches.length > 1) {
      const exact = matches.find((r) => {
        const full = normalizeScan(r.sticker_number);
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

  async function saveKizLocal(row, opts) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const oid = Number(row.order_id);
    const codes = normalizeKizCodesList(row.kiz_codes);
    row.kiz_codes = codes.length ? codes.slice() : [""];
    const retrying = !!(opts && opts._retry);
    const data = await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/kiz?${params}`,
      {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({
          items: [
            {
              order_id: oid,
              kiz_codes: codes,
              clear: !codes.length,
              local_only: true,
              expected_saved_at: String(row.kiz_saved_at || ""),
              force: !!state.forceSaveByOrder[oid] || retrying,
            },
          ],
        }),
        keepalive: true,
      }
    );
    const result = (data.results || []).find((r) => Number(r.order_id) === oid) || null;
    if (!result) throw new Error("Сервер не вернул результат сохранения КИЗ");
    if (result.conflict) {
      row.kiz_saved_at = String(result.kiz_saved_at || row.kiz_saved_at || "");
      state.forceSaveByOrder[oid] = true;
      // Keep scanned codes and retry once — same operator / timezone false conflicts.
      row.kiz_codes = codes.length ? codes.slice() : [""];
      if (!retrying) return saveKizLocal(row, { _retry: true });
      throw new Error(
        result.error ||
          "Заказ уже сохранён другим оператором — проверьте КИЗ и повторите"
      );
    }
    if (!result.ok && !result.local_ok) {
      throw new Error(result.error || "Не удалось сохранить КИЗ локально");
    }
    if (result.kiz_saved_at) row.kiz_saved_at = String(result.kiz_saved_at);
    delete state.forceSaveByOrder[oid];
    return result;
  }

  async function savePickLocal(row, opts) {
    const params = new URLSearchParams({ source_id: String(state.sourceId) });
    const oid = Number(row.order_id);
    const retrying = !!(opts && opts._retry);
    const intendedVerified = !!row.pick_verified;
    const intendedBarcode = String(row.pick_barcode || "").trim();
    const data = await api(
      `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/pick-verify?${params}`,
      {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify({
          items: [
            {
              order_id: oid,
              pick_verified: intendedVerified,
              pick_barcode: intendedBarcode,
              local_only: true,
              expected_verified_at: String(row.pick_verified_at || ""),
              force: !!state.forceSaveByOrder[`pick:${oid}`] || retrying,
            },
          ],
        }),
        keepalive: true,
      }
    );
    const result = (data.results || []).find((r) => Number(r.order_id) === oid) || null;
    if (!result) throw new Error("Сервер не вернул результат сохранения ШК");
    if (result.conflict) {
      row.pick_verified_at = String(result.pick_verified_at || row.pick_verified_at || "");
      state.forceSaveByOrder[`pick:${oid}`] = true;
      row.pick_verified = intendedVerified;
      row.pick_barcode = intendedBarcode;
      if (!retrying) return savePickLocal(row, { _retry: true });
      throw new Error(
        result.error ||
          "Заказ уже сохранён другим оператором — проверьте ШК и повторите"
      );
    }
    if (!result.ok) {
      throw new Error(result.error || "Не удалось сохранить проверку ШК");
    }
    if (result.pick_verified_at) row.pick_verified_at = String(result.pick_verified_at);
    delete state.forceSaveByOrder[`pick:${oid}`];
    return result;
  }

  /** Explicit «Сохранить»: local + push КИЗ to Wildberries (like desktop modal). */
  async function saveKizPushAll() {
    if (state.saving) return;
    const rows = state.kizRows || [];
    const items = [];
    for (const row of rows) {
      const oid = Number(row.order_id);
      if (!Number.isFinite(oid)) continue;
      const codes = normalizeKizCodesList(row.kiz_codes);
      if (!codes.length) continue;
      row.kiz_codes = codes.slice();
      items.push({
        order_id: oid,
        kiz_codes: codes,
        clear: false,
        expected_saved_at: String(row.kiz_saved_at || ""),
        force: !!state.forceSaveByOrder[oid],
      });
    }
    if (!items.length) {
      setBanner("Нет КИЗ для отправки в WB", "warn");
      renderScan();
      return;
    }
    state.saving = true;
    setBanner(`Сохранение ${items.length} в WB…`, "info");
    renderScan();
    try {
      const params = new URLSearchParams({ source_id: String(state.sourceId) });
      const data = await api(
        `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/kiz?${params}`,
        {
          method: "PUT",
          headers: jsonHeaders(),
          body: JSON.stringify({ items }),
        }
      );
      let okN = 0;
      let errN = 0;
      let conflictN = 0;
      for (const r of data.results || []) {
        const oid = Number(r.order_id);
        const row = rows.find((x) => Number(x.order_id) === oid);
        if (!row) continue;
        if (r.conflict) {
          conflictN += 1;
          row.kiz_saved_at = String(r.kiz_saved_at || row.kiz_saved_at || "");
          if (Array.isArray(r.kiz_codes)) row.kiz_codes = r.kiz_codes.slice();
          state.forceSaveByOrder[oid] = true;
          continue;
        }
        if (r.kiz_saved_at) row.kiz_saved_at = String(r.kiz_saved_at);
        if (r.kiz_wb_synced != null) row.kiz_wb_synced = !!r.kiz_wb_synced;
        if (r.ok || r.wb_ok) {
          okN += 1;
          delete state.forceSaveByOrder[oid];
        } else if (r.local_ok) {
          errN += 1;
        } else {
          errN += 1;
        }
      }
      if (conflictN) {
        setBanner(
          `Конфликт у ${conflictN} заказ(ов) — проверьте и сохраните ещё раз`,
          "err"
        );
      } else if (errN && okN) {
        setBanner(`Отправлено ${okN}, ошибок ${errN} — повторите «Сохранить»`, "warn");
      } else if (errN) {
        setBanner(`Не удалось отправить в WB (${errN})`, "err");
      } else {
        setBanner(`Сохранено в WB: ${okN}`, "ok");
      }
    } catch (e) {
      setBanner(e.message || String(e), "err");
    } finally {
      state.saving = false;
      renderScan();
    }
  }

  /** Explicit «Сохранить» for pick: local-only batch (like desktop modal). */
  async function savePickLocalAll() {
    if (state.saving) return;
    const rows = state.pickRows || [];
    const items = [];
    for (const row of rows) {
      const oid = Number(row.order_id);
      if (!Number.isFinite(oid)) continue;
      if (!rowPickFilled(row)) continue;
      items.push({
        order_id: oid,
        pick_verified: true,
        pick_barcode: String(row.pick_barcode || "").trim(),
        expected_verified_at: String(row.pick_verified_at || ""),
        force: !!state.forceSaveByOrder[`pick:${oid}`],
      });
    }
    if (!items.length) {
      setBanner("Нет подтверждённых ШК для сохранения", "warn");
      renderScan();
      return;
    }
    state.saving = true;
    setBanner(`Сохранение ${items.length}…`, "info");
    renderScan();
    try {
      const params = new URLSearchParams({ source_id: String(state.sourceId) });
      const data = await api(
        `/api/wb-fbs/tsd/supplies/${encodeURIComponent(state.route.supplyId)}/pick-verify?${params}`,
        {
          method: "PUT",
          headers: jsonHeaders(),
          body: JSON.stringify({ items }),
        }
      );
      let okN = 0;
      let errN = 0;
      let conflictN = 0;
      for (const r of data.results || []) {
        const oid = Number(r.order_id);
        const row = rows.find((x) => Number(x.order_id) === oid);
        if (!row) continue;
        if (r.conflict) {
          conflictN += 1;
          row.pick_verified_at = String(r.pick_verified_at || row.pick_verified_at || "");
          state.forceSaveByOrder[`pick:${oid}`] = true;
          continue;
        }
        if (r.ok) {
          okN += 1;
          if (r.pick_verified_at) row.pick_verified_at = String(r.pick_verified_at);
          delete state.forceSaveByOrder[`pick:${oid}`];
        } else {
          errN += 1;
        }
      }
      if (conflictN) {
        setBanner(`Конфликт у ${conflictN} заказ(ов)`, "err");
      } else if (errN) {
        setBanner(`Сохранено ${okN}, ошибок ${errN}`, "warn");
      } else {
        setBanner(`Сохранено локально: ${okN}`, "ok");
      }
    } catch (e) {
      setBanner(e.message || String(e), "err");
    } finally {
      state.saving = false;
      renderScan();
    }
  }

  function noteSessionScanned(orderId) {
    const oid = Number(orderId);
    if (!Number.isFinite(oid) || oid <= 0) return;
    state.sessionScannedIds = (state.sessionScannedIds || []).filter(
      (x) => Number(x) !== oid
    );
    state.sessionScannedIds.push(oid);
  }

  function orderedScannedRows(mode) {
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const fn = mode === "kiz" ? rowKizFilled : rowPickFilled;
    const filled = (rows || []).filter(fn);
    const byId = new Map(filled.map((r) => [Number(r.order_id), r]));
    const out = [];
    const seen = new Set();
    for (let i = (state.sessionScannedIds || []).length - 1; i >= 0; i -= 1) {
      const id = Number(state.sessionScannedIds[i]);
      const row = byId.get(id);
      if (row && !seen.has(id)) {
        out.push(row);
        seen.add(id);
      }
    }
    for (const row of filled) {
      const id = Number(row.order_id);
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
        const photo = r.product_photo
          ? `<img src="${esc(r.product_photo)}" alt="" width="48" height="48" />`
          : `<span class="tsd-scanned-ph" aria-hidden="true"></span>`;
        const oid = esc(String(r.order_id));
        const stickerHtml = formatBoldLastDigits(r.sticker_number || "—", 4);
        const barcodes = orderBarcodesLabel(r);
        const barcodesHtml = barcodes
          ? `<div class="tsd-scanned-kv">
              <span class="tsd-scanned-label">ШК:</span>
              <span class="tsd-scanned-kv-val">${esc(barcodes)}</span>
            </div>`
          : "";
        let detailHtml;
        let clearBtn = "";
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
          clearBtn = `
            <button type="button" class="tsd-scanned-clear"
              data-action="clear-kiz-all" data-order-id="${oid}"
              aria-label="Очистить КИЗ" title="Очистить КИЗ">×</button>`;
        } else {
          const verified = String(r.pick_barcode || "").trim();
          detailHtml =
            !barcodes && verified
              ? `<div class="tsd-scanned-kv">
                  <span class="tsd-scanned-label">ШК:</span>
                  <span class="tsd-scanned-kv-val">${esc(verified)}</span>
                </div>`
              : "";
        }
        return `
          <div class="tsd-scanned-item">
            <div class="tsd-scanned-top">
              ${photo}
              <div class="tsd-scanned-text">
                <div class="tsd-scanned-order">Заказ ${oid} · ${stickerHtml}</div>
                <div class="tsd-scanned-name">${esc(r.product_name || r.article || "—")}</div>
              </div>
              ${clearBtn}
            </div>
            ${
              barcodesHtml || detailHtml
                ? `<div class="tsd-scanned-details">${barcodesHtml}${detailHtml}</div>`
                : ""
            }
          </div>`;
      })
      .join("");
    return `
      <section class="tsd-scanned" aria-label="Просканированные заказы">
        <h2 class="tsd-scanned-title">Просканировано · ${scanned.length}</h2>
        <div class="tsd-scanned-list" id="tsdScannedList">${items}</div>
      </section>`;
  }

  async function clearKizCodes(orderId) {
    if (state.saving || state.clearing) return;
    const oid = Number(orderId);
    const row = (state.kizRows || []).find((r) => Number(r.order_id) === oid);
    if (!row) return;
    if (!Array.isArray(row.kiz_codes)) row.kiz_codes = [""];
    state.clearing = true;
    try {
      row.kiz_codes = [""];
      await saveKizLocal(row);
      setBanner(`КИЗ очищен · заказ ${oid}`, "ok");
    } catch (e) {
      setBanner(e.message || String(e), "err");
    } finally {
      state.clearing = false;
      renderScan();
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
    const onScan = !!boot.can_view_wb_fbs_tsd && state.route.view === "scan";
    if (btn) {
      btn.hidden = !onScan;
      btn.setAttribute("aria-expanded", state.searchOpen && onScan ? "true" : "false");
    }
    if (!onScan) {
      state.searchOpen = false;
      state.orderSearch = "";
      if (panel) panel.hidden = true;
      if (input) input.value = "";
      return;
    }
    if (panel) panel.hidden = !state.searchOpen;
    if (input && state.searchOpen && String(input.value || "") !== String(state.orderSearch || "")) {
      input.value = state.orderSearch || "";
    }
  }

  function openOrderSearch() {
    if (state.route.view !== "scan") return;
    state.searchOpen = true;
    syncSearchChrome();
    const input = document.getElementById("tsdOrderSearch");
    if (input) {
      setTimeout(() => {
        input.focus();
        input.select();
      }, 40);
    }
    renderScan({ keepSearchFocus: true });
  }

  function closeOrderSearch() {
    state.searchOpen = false;
    state.orderSearch = "";
    syncSearchChrome();
    const input = document.getElementById("tsdOrderSearch");
    if (input) input.value = "";
    if (state.route.view === "scan") renderScan();
  }

  function orderSearchHaystack(row) {
    const parts = [
      row.order_id,
      row.sticker_number,
      row.sticker_barcode,
      row.sticker_part_a,
      row.sticker_part_b,
      row.product_name,
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

  function renderSearchResultsHtml(mode) {
    if (!state.searchOpen) return "";
    const q = String(state.orderSearch || "").trim();
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    if (!q) {
      return `
        <section class="tsd-search-results" aria-label="Поиск заказов">
          <h2 class="tsd-search-results-title">Поиск</h2>
          <div class="tsd-search-empty">Введите или отсканируйте стикер, номер заказа, ШК, артикул или название</div>
        </section>`;
    }
    const matched = filterOrdersBySearch(rows, q);
    if (!matched.length) {
      return `
        <section class="tsd-search-results" aria-label="Поиск заказов">
          <h2 class="tsd-search-results-title">Найдено 0</h2>
          <div class="tsd-search-empty">Ничего не найдено</div>
        </section>`;
    }
    const items = matched
      .slice(0, 80)
      .map((r) => {
        const photo = r.product_photo
          ? `<img src="${esc(r.product_photo)}" alt="" width="48" height="48" />`
          : `<span class="tsd-scanned-ph" aria-hidden="true"></span>`;
        const barcodes = orderBarcodesLabel(r);
        const status =
          mode === "kiz"
            ? rowKizFilled(r)
              ? "КИЗ есть"
              : "Нет КИЗ"
            : rowPickFilled(r)
              ? "ШК проверен"
              : "Не проверен";
        return `
          <button type="button" class="tsd-search-item" data-action="pick-search-order"
            data-order-id="${esc(String(r.order_id))}">
            ${photo}
            <div class="tsd-scanned-text">
              <div class="tsd-scanned-order">Заказ ${esc(r.order_id)} · ${esc(r.sticker_number || "—")}</div>
              <div class="tsd-scanned-name">${esc(r.product_name || r.article || "—")}</div>
              ${
                barcodes
                  ? `<div class="tsd-scanned-barcodes">${esc(barcodes)}</div>`
                  : ""
              }
              <div class="tsd-scanned-meta">${esc(status)}</div>
            </div>
          </button>`;
      })
      .join("");
    return `
      <section class="tsd-search-results" aria-label="Поиск заказов">
        <h2 class="tsd-search-results-title">Найдено · ${matched.length}${
          matched.length > 80 ? " (показаны 80)" : ""
        }</h2>
        <div class="tsd-search-list" id="tsdSearchList">${items}</div>
      </section>`;
  }

  function refreshSearchResultsOnly() {
    if (state.route.view !== "scan") return;
    const mode = state.route.mode;
    const shell = document.querySelector(".tsd-scan-shell");
    if (!shell) {
      renderScan({ keepSearchFocus: true });
      return;
    }
    const html = renderSearchResultsHtml(mode).trim();
    const current = shell.querySelector(".tsd-search-results");
    if (!html) {
      if (current) current.remove();
      return;
    }
    const wrap = document.createElement("div");
    wrap.innerHTML = html;
    const next = wrap.firstElementChild;
    if (!next) return;
    if (current) current.replaceWith(next);
    else {
      const banner = shell.querySelector(".tsd-banner");
      const stats = shell.querySelector(".tsd-stats");
      const after = banner || stats;
      if (after && after.nextSibling) shell.insertBefore(next, after.nextSibling);
      else shell.insertBefore(next, shell.firstChild);
    }
    const searchList = document.getElementById("tsdSearchList");
    if (searchList) {
      searchList.addEventListener("click", (ev) => {
        const btn = ev.target && ev.target.closest
          ? ev.target.closest("[data-action='pick-search-order']")
          : null;
        if (!btn) return;
        ev.preventDefault();
        selectOrderFromSearch(btn.getAttribute("data-order-id"));
      });
    }
  }

  function selectOrderFromSearch(orderId) {
    const mode = state.route.mode;
    const rows = mode === "kiz" ? state.kizRows : state.pickRows;
    const row = (rows || []).find((r) => Number(r.order_id) === Number(orderId));
    if (!row) {
      setBanner("Заказ не найден", "err");
      return;
    }
    state.pendingOrderId = Number(row.order_id);
    state.step = mode === "kiz" ? "mark" : "sku";
    state.searchOpen = false;
    state.orderSearch = "";
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
      selectOrderFromSearch(found.row.order_id);
      return;
    }
    const matched = filterOrdersBySearch(rows, raw);
    if (matched.length === 1) {
      selectOrderFromSearch(matched[0].order_id);
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
    syncSourceSelectVisibility();
    syncSearchChrome();
    syncScrollTopFab();
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
        <button type="button" class="tsd-tile" id="tsdTileKiz" ${kizDisabled ? "disabled" : ""}>
          <span class="tsd-tile-title">Товары с маркировкой</span>
          <span class="tsd-tile-prog">${
            kizError
              ? "Ошибка загрузки"
              : kizDisabled
                ? "Нет заказов"
                : `${kiz.done} / ${kiz.total}`
          }</span>
        </button>
        <button type="button" class="tsd-tile" id="tsdTilePick" ${pickDisabled ? "disabled" : ""}>
          <span class="tsd-tile-title">Товары без маркировки</span>
          <span class="tsd-tile-prog">${
            pickError
              ? "Ошибка загрузки"
              : pickDisabled
                ? "Нет заказов"
                : `${pick.done} / ${pick.total}`
          }</span>
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
        state.pendingOrderId = null;
        state.step = "sticker";
        state.searchOpen = false;
        state.orderSearch = "";
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
        <div class="tsd-scan-card" id="tsdScanCard">
          <div class="tsd-scan-step">Шаг 1</div>
          <p class="tsd-scan-prompt">Сканируйте стикер заказа</p>
          <div class="tsd-scan-field">
            <input class="tsd-scan-input" id="tsdScanInput" type="text" autocomplete="off" inputmode="none" />
            <button type="button" class="tsd-scan-clear" id="tsdScanClear" hidden
              aria-label="Очистить поле" title="Очистить">×</button>
          </div>
        </div>`;
    } else {
      const photo = pending.product_photo
        ? `<img src="${esc(pending.product_photo)}" alt="" width="64" height="64" />`
        : "";
      const existingKizN =
        mode === "kiz" ? filledKizEntries(pending).length : 0;
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
      body = `
        <div class="tsd-scan-card" id="tsdScanCard">
          <div class="tsd-scan-step">Шаг 2</div>
          <p class="tsd-scan-prompt">${prompt}</p>
          ${multiHint}
          <div class="tsd-scan-context">Заказ ${esc(pending.order_id)} · стикер ${esc(pending.sticker_number || "—")}</div>
          <div class="tsd-scan-field">
            <input class="tsd-scan-input" id="tsdScanInput" type="text" autocomplete="off" inputmode="none" />
            <button type="button" class="tsd-scan-clear" id="tsdScanClear" hidden
              aria-label="Очистить поле" title="Очистить">×</button>
          </div>
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

    const saveLabel = "Сохранить";
    const saveDisabled = state.saving || state.clearing || !orderedScannedRows(mode).length;

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
        ${renderSearchResultsHtml(mode)}
        ${body}
        <div class="tsd-scan-footer">
          <button type="button" class="tsd-btn tsd-btn-primary tsd-btn-block" id="tsdSaveBtn"
            ${saveDisabled ? "disabled" : ""}>${esc(
              state.saving ? "Сохранение…" : saveLabel
            )}</button>
        </div>
        ${renderScannedListHtml(mode)}
      </div>`;

    const input = document.getElementById("tsdScanInput");
    const clearBtn = document.getElementById("tsdScanClear");
    const syncScanClearBtn = () => {
      if (!clearBtn || !input) return;
      clearBtn.hidden = !String(input.value || "").length;
    };
    if (input && !keepSearchFocus && !state.searchOpen) {
      setTimeout(() => input.focus(), 40);
    }
    if (input) {
      syncScanClearBtn();
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          onScanEnter(input);
        }
      });
      // Do not remount on Cyrillic mid-scan — only banner hint; Enter applies layout map.
      input.addEventListener("input", () => {
        syncScanClearBtn();
        if (hasCyrillic(input.value)) {
          const el = document.querySelector(".tsd-banner");
          if (!el) {
            const shell = document.querySelector(".tsd-scan-shell");
            if (shell) {
              const ban = document.createElement("div");
              ban.className = "tsd-banner is-warn";
              ban.textContent = "Русская раскладка — переключите на EN (или сканируйте ещё раз)";
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
        renderScan();
      });
    }
    const saveBtn = document.getElementById("tsdSaveBtn");
    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        if (mode === "kiz") saveKizPushAll();
        else savePickLocalAll();
      });
    }
    const scannedList = document.getElementById("tsdScannedList");
    if (scannedList && mode === "kiz") {
      scannedList.addEventListener("click", (ev) => {
        const btn = ev.target && ev.target.closest
          ? ev.target.closest("[data-action]")
          : null;
        if (!btn) return;
        const action = btn.getAttribute("data-action");
        const oid = btn.getAttribute("data-order-id");
        if (action === "clear-kiz-all") {
          ev.preventDefault();
          clearKizCodes(oid);
        }
      });
    }
    const searchList = document.getElementById("tsdSearchList");
    if (searchList) {
      searchList.addEventListener("click", (ev) => {
        const btn = ev.target && ev.target.closest
          ? ev.target.closest("[data-action='pick-search-order']")
          : null;
        if (!btn) return;
        ev.preventDefault();
        selectOrderFromSearch(btn.getAttribute("data-order-id"));
      });
    }
    syncScrollTopFab();
  }

  async function onScanEnter(input) {
    const mode = state.route.mode;
    let raw = String(input.value || "");
    if (!normalizeScan(raw)) return;
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
        const mark = normalizeKizMark(raw);
        const check = markMatchesOrder(mark, row);
        if (!check.ok) {
          setBanner(check.error || "КИЗ не подходит", "err");
          beep(false);
          input.select();
          renderScan();
          return;
        }
        const ownDup = (Array.isArray(row.kiz_codes) ? row.kiz_codes : []).some(
          (c) => normalizeKizMark(c) === mark
        );
        if (ownDup) {
          setBanner("Этот КИЗ уже в этом заказе", "err");
          beep(false);
          input.select();
          renderScan();
          return;
        }
        const dup = state.kizRows.find((r) =>
          Number(r.order_id) !== Number(row.order_id) &&
          (Array.isArray(r.kiz_codes) ? r.kiz_codes : []).some(
            (c) => normalizeKizMark(c) === mark
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
        noteSessionScanned(row.order_id);
        const kizN = filledKizEntries(row).length;
        setBanner(
          kizN <= 1
            ? `КИЗ записан · заказ ${row.order_id}. Для 2-го КИЗ снова сканируйте стикер`
            : `КИЗ ${kizN} записан · заказ ${row.order_id}`,
          "ok"
        );
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
        noteSessionScanned(row.order_id);
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
        const sid = state.route.supplyId;
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
        if (state.route.mode === "kiz") {
          await loadKiz(state.route.supplyId);
        } else {
          await loadPick(state.route.supplyId);
        }
        if (seq !== state.loadSeq) return;
        stopLoadingUi();
        if (!state.step) state.step = "sticker";
        renderScan();
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
        if (state.searchOpen) closeOrderSearch();
        else openOrderSearch();
      });
    }
    const searchClose = document.getElementById("tsdSearchClose");
    if (searchClose) {
      searchClose.addEventListener("click", () => closeOrderSearch());
    }
    const orderSearch = document.getElementById("tsdOrderSearch");
    if (orderSearch) {
      orderSearch.addEventListener("input", () => {
        state.orderSearch = String(orderSearch.value || "");
        refreshSearchResultsOnly();
      });
      orderSearch.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") {
          ev.preventDefault();
          closeOrderSearch();
          return;
        }
        if (ev.key === "Enter") {
          ev.preventDefault();
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
      },
      { passive: true }
    );
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
