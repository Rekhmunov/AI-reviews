/* Ozon FBS standalone driver page */
(function () {
  "use strict";

  const boot = window.OFD_BOOT || {};
  const main = document.getElementById("ofdMain");
  const toastEl = document.getElementById("ofdToast");
  let toastTimer = 0;

  const pageMode = String(boot.page_mode || "owner");
  const pageToken = String(boot.page_token || "").trim();
  const isPinMode = pageMode === "pin";

  const state = {
    plates: [],
    vehicleNumber: "",
    items: [],
    supplies: [],
    errors: [],
    loadingPlates: false,
    loadingItems: false,
    softRefresh: false,
    accessToken: "",
    driverName: "",
    unlocking: false,
    pinError: "",
  };

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(message) {
    if (!toastEl) return;
    toastEl.textContent = String(message || "");
    toastEl.hidden = !message;
    if (toastTimer) window.clearTimeout(toastTimer);
    if (message) {
      toastTimer = window.setTimeout(function () {
        toastEl.hidden = true;
      }, 3200);
    }
  }

  async function api(path, options) {
    const opts = options || {};
    const headers = Object.assign(
      { Accept: "application/json" },
      opts.headers || {}
    );
    if (state.accessToken) {
      headers["X-Driver-Access-Token"] = state.accessToken;
    }
    // Public PIN page must not send the cabinet session cookie: CSRF would
    // block unlock for a logged-in owner testing the public link, and the
    // page is intentionally account-free.
    const res = await fetch(path, {
      credentials: isPinMode ? "omit" : "same-origin",
      method: opts.method || "GET",
      headers: headers,
      body: opts.body || undefined,
    });
    if (res.status === 401) {
      if (isPinMode) {
        state.accessToken = "";
        state.plates = [];
        state.vehicleNumber = "";
        state.items = [];
        renderPinForm("Сессия истекла. Введите ПИН снова.");
        throw new Error("Введите ПИН заново");
      }
      window.location.href = "/login";
      throw new Error("Требуется вход");
    }
    const data = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) {
      const detail = data && (data.detail || data.message || data.error);
      throw new Error(String(detail || "Ошибка " + res.status));
    }
    return data;
  }

  function badgeClass(status) {
    const st = String(status || "").toLowerCase();
    if (st === "acceptance_in_progress" || st === "finished") return "is-sc";
    if (st === "formed") return "is-formed";
    return "";
  }

  /** Ozon GMs only — WB TRBX use a placeholder status and must not drive the banner. */
  function ozonPalletItems(items) {
    return (items || []).filter(function (item) {
      const mp = String(item.marketplace || "").toLowerCase();
      const kind = String(item.item_kind || "").toLowerCase();
      if (mp === "wb" || kind === "trbx") return false;
      return true;
    });
  }

  /** ``warn`` = any «Сформировано»; ``ok`` = none / all at SC / finished. */
  function palletBannerKind(items) {
    const list = items || [];
    // No cargo places at all → same green as fully accepted at SC.
    if (!list.length) return "ok";
    const ozon = ozonPalletItems(list);
    if (!ozon.length) return null;
    let hasFormed = false;
    let allAccepted = true;
    for (let i = 0; i < ozon.length; i++) {
      const st = String(ozon[i].status || "").toLowerCase();
      if (st === "formed") hasFormed = true;
      if (st !== "acceptance_in_progress" && st !== "finished") {
        allAccepted = false;
      }
    }
    if (hasFormed) return "warn";
    if (allAccepted) return "ok";
    return null;
  }

  const STATUS_SORT_ORDER = {
    formed: 0,
    acceptance_in_progress: 1,
    finished: 2,
  };

  function statusSortKey(status) {
    const st = String(status || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(STATUS_SORT_ORDER, st)
      ? STATUS_SORT_ORDER[st]
      : 99;
  }

  function sortCargoItems(items) {
    return (items || []).slice().sort(function (a, b) {
      const sa = statusSortKey(a && a.status);
      const sb = statusSortKey(b && b.status);
      if (sa !== sb) return sa - sb;
      const supplyA = String((a && a.supply_name) || "");
      const supplyB = String((b && b.supply_name) || "");
      if (supplyA < supplyB) return -1;
      if (supplyA > supplyB) return 1;
      const numA = Number((a && a.container_number) || 0);
      const numB = Number((b && b.container_number) || 0);
      if (numA !== numB) return numA - numB;
      return String((a && a.container_id) || "").localeCompare(
        String((b && b.container_id) || "")
      );
    });
  }

  function renderStatusBanner() {
    const host = document.getElementById("ofdStatusBanner");
    if (!host) return;
    if (!state.vehicleNumber) {
      host.innerHTML = "";
      host.hidden = true;
      return;
    }
    // First load: hide banner until data arrives. Soft refresh keeps it.
    if (state.loadingItems && !state.softRefresh) {
      host.innerHTML = "";
      host.hidden = true;
      return;
    }
    const kind = palletBannerKind(state.items);
    if (!kind) {
      host.innerHTML = "";
      host.hidden = true;
      return;
    }
    host.hidden = false;
    if (kind === "ok") {
      host.innerHTML =
        '<div class="ofd-banner ofd-banner-ok" role="status">' +
        "Ваши паллеты приняты на СЦ, все хорошо" +
        "</div>";
      return;
    }
    const refreshing = state.loadingItems && state.softRefresh;
    host.innerHTML =
      '<div class="ofd-banner ofd-banner-warn" role="status">' +
      "<p class=\"ofd-banner-text\">" +
      "Часть ваших паллет в статусе «Сформировано» — нужно дождаться, " +
      "пока статусы станут «Принято на СЦ» или «Завершено». " +
      "Нажмите «Обновить», чтобы проверить ещё раз. " +
      "Если не помогает в течение нескольких минут, то обратитесь на склад " +
      "для повторного сканирования." +
      "</p>" +
      '<button type="button" id="ofdRefreshBtn" class="ofd-btn ofd-btn-refresh' +
      (refreshing ? " is-loading" : "") +
      '"' +
      (refreshing ? " disabled" : "") +
      ">" +
      (refreshing
        ? '<span class="ofd-spinner" aria-hidden="true"></span><span>Обновление…</span>'
        : "Обновить") +
      "</button>" +
      "</div>";
    const btn = document.getElementById("ofdRefreshBtn");
    if (btn && !refreshing) {
      btn.addEventListener("click", function () {
        if (state.loadingItems) return;
        loadCargo(state.vehicleNumber, { soft: true });
      });
    }
  }

  function renderDenied() {
    main.innerHTML =
      '<div class="ofd-denied">Нет доступа к странице водителя Ozon FBS.</div>';
  }

  function renderPinForm(errorMessage) {
    const err = String(errorMessage || state.pinError || "");
    main.innerHTML =
      '<section class="ofd-panel ofd-pin-panel">' +
      '<h2 class="ofd-pin-title">Вход по ПИН</h2>' +
      '<p class="ofd-hint">Введите ПИН из настроек «Водители». После закрытия страницы потребуется ввести его снова.</p>' +
      '<label class="ofd-label" for="ofdPinInput">ПИН</label>' +
      '<input id="ofdPinInput" class="ofd-input" type="password" inputmode="numeric" ' +
      'autocomplete="one-time-code" maxlength="8" placeholder="••••" />' +
      (err ? '<p class="ofd-pin-error" role="alert">' + esc(err) + "</p>" : "") +
      '<button type="button" id="ofdPinSubmit" class="ofd-btn"' +
      (state.unlocking ? " disabled" : "") +
      ">" +
      (state.unlocking ? "Проверка…" : "Открыть") +
      "</button>" +
      "</section>";

    const input = document.getElementById("ofdPinInput");
    const btn = document.getElementById("ofdPinSubmit");
    if (input) {
      input.focus();
      input.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") {
          ev.preventDefault();
          submitPin();
        }
      });
    }
    if (btn) btn.addEventListener("click", submitPin);
  }

  async function submitPin() {
    if (state.unlocking) return;
    const input = document.getElementById("ofdPinInput");
    const pin = String((input && input.value) || "").trim();
    state.pinError = "";
    if (!pin) {
      renderPinForm("Введите ПИН");
      return;
    }
    state.unlocking = true;
    renderPinForm("");
    try {
      const data = await api(
        "/api/ozon-fbs/driver/p/" + encodeURIComponent(pageToken) + "/unlock",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin: pin }),
        }
      );
      state.accessToken = String(data.access_token || "");
      state.driverName = String(data.driver_name || "").trim();
      state.plates = Array.isArray(data.items) ? data.items : [];
      state.vehicleNumber = "";
      state.items = [];
      state.errors = [];
      state.loadingPlates = false;
      renderShell();
      renderResults();
      maybeAutoloadSinglePlate();
    } catch (err) {
      state.accessToken = "";
      state.pinError = String(err.message || err);
      state.unlocking = false;
      renderPinForm(state.pinError);
      return;
    }
    state.unlocking = false;
  }

  function renderShell() {
    const multi = state.plates.length > 1;
    const single = state.plates.length === 1;
    const disabled = state.loadingPlates ? "disabled" : "";
    const placeholder = state.loadingPlates
      ? "Загрузка…"
      : multi
        ? "Выберите гос. номер"
        : "Нет машин";

    const driverLine =
      isPinMode && state.driverName
        ? '<p class="ofd-driver-name">' + esc(state.driverName) + "</p>"
        : "";

    let vehicleBlock;
    if (!state.loadingPlates && !multi) {
      const number = single
        ? String(state.plates[0].number || "").trim()
        : "";
      const line = single
        ? String(state.plates[0].line || number).trim() || number
        : "Нет машин в карточке водителя";
      vehicleBlock =
        '<div class="ofd-label">Номер машины</div>' +
        '<div class="ofd-plate-value">' +
        esc(line || "—") +
        "</div>" +
        (single
          ? ""
          : '<p class="ofd-hint">Добавьте автомобиль в настройках «Водители».</p>');
      if (single && number) state.vehicleNumber = number;
    } else {
      vehicleBlock =
        '<label class="ofd-label" for="ofdVehicleSelect">Номер машины</label>' +
        '<select id="ofdVehicleSelect" class="ofd-select" ' +
        disabled +
        ">" +
        '<option value="">' +
        placeholder +
        "</option>" +
        "</select>";
    }

    main.innerHTML =
      '<section class="ofd-panel">' +
      driverLine +
      vehicleBlock +
      '<div id="ofdStatusBanner" class="ofd-status-banner" hidden></div>' +
      "</section>" +
      '<section class="ofd-panel" id="ofdResults">' +
      '<div class="ofd-empty">Выберите номер машины</div>' +
      "</section>";
    renderStatusBanner();

    const select = document.getElementById("ofdVehicleSelect");
    if (select) {
      state.plates.forEach(function (plate) {
        const number = String(plate.number || "").trim();
        if (!number) return;
        const opt = document.createElement("option");
        opt.value = number;
        opt.textContent = String(plate.line || number).trim() || number;
        if (number === state.vehicleNumber) opt.selected = true;
        select.appendChild(opt);
      });
      select.addEventListener("change", onVehicleChange);
    }
  }

  function renderResults() {
    const box = document.getElementById("ofdResults");
    if (!box) return;

    if (!state.vehicleNumber) {
      box.hidden = false;
      box.innerHTML = '<div class="ofd-empty">Выберите номер машины</div>';
      renderStatusBanner();
      return;
    }
    if (state.loadingItems && !state.softRefresh) {
      box.hidden = false;
      box.innerHTML = '<div class="ofd-loading">Загрузка грузомест…</div>';
      renderStatusBanner();
      return;
    }

    const errorsHtml = state.errors.length
      ? '<div class="ofd-errors">' +
        state.errors.map(esc).join("<br>") +
        "</div>"
      : "";

    // No cargo in the tracked statuses → only the green banner, no empty list block.
    if (!state.items.length) {
      if (errorsHtml) {
        box.hidden = false;
        box.innerHTML = errorsHtml;
      } else {
        box.innerHTML = "";
        box.hidden = true;
      }
      renderStatusBanner();
      return;
    }

    box.hidden = false;

    const listClass =
      state.loadingItems && state.softRefresh
        ? "ofd-items is-refreshing"
        : "ofd-items";

    const rows = sortCargoItems(state.items)
      .map(function (item) {
        const isWb = String(item.marketplace || item.item_kind || "")
          .toLowerCase()
          .indexOf("wb") >= 0 || String(item.item_kind || "") === "trbx";
        const num = Number(item.container_number || 0);
        const metaParts = [];
        if (item.supply_name) {
          metaParts.push(
            "<div><span>Поставка:</span> " + esc(item.supply_name) + "</div>"
          );
        }
        metaParts.push(
          "<div><span>Маркетплейс:</span> " +
            esc(isWb ? "Wildberries" : "Ozon") +
            "</div>"
        );
        if (item.warehouse_name) {
          metaParts.push(
            "<div><span>Склад:</span> " + esc(item.warehouse_name) + "</div>"
          );
        }
        const typeBits = [item.cargo_type_label, item.sort_type_label]
          .filter(Boolean)
          .join(" · ");
        if (typeBits) {
          metaParts.push("<div><span>Тип:</span> " + esc(typeBits) + "</div>");
        }
        metaParts.push(
          "<div><span>Заказов:</span> " +
            esc(String(item.order_count ?? 0)) +
            "</div>"
        );
        const title = isWb
          ? "Грузоместо " + esc(String(num || "—"))
          : "ГМ № " + esc(String(num || "—"));
        const idLabel = isWb ? "TRBX " : "ID ";
        return (
          '<li class="ofd-item">' +
          '<div class="ofd-item-top">' +
          "<div>" +
          '<div class="ofd-item-num">' +
          title +
          "</div>" +
          '<div class="ofd-item-id">' +
          idLabel +
          esc(String(item.container_id || "")) +
          "</div>" +
          "</div>" +
          '<span class="ofd-badge ' +
          badgeClass(item.status) +
          '">' +
          esc(item.status_label || item.status || "—") +
          "</span>" +
          "</div>" +
          '<div class="ofd-item-meta">' +
          metaParts.join("") +
          "</div>" +
          "</li>"
        );
      })
      .join("");

    box.innerHTML =
      '<div class="ofd-list-head">' +
      '<h2 class="ofd-list-title">Грузоместа</h2>' +
      '<div class="ofd-list-count">' +
      state.items.length +
      "</div>" +
      "</div>" +
      errorsHtml +
      '<ul class="' +
      listClass +
      '">' +
      rows +
      "</ul>";
    renderStatusBanner();
  }

  async function loadCargo(value, opts) {
    const soft = !!(opts && opts.soft);
    const plate = String(value || "").trim();
    state.vehicleNumber = plate;
    state.softRefresh = soft;
    if (!soft) {
      state.items = [];
      state.errors = [];
    }
    renderResults();
    if (!plate) {
      state.softRefresh = false;
      return;
    }
    state.loadingItems = true;
    renderResults();
    try {
      const params = new URLSearchParams({ vehicle_number: plate });
      let path;
      if (isPinMode) {
        path =
          "/api/ozon-fbs/driver/p/" +
          encodeURIComponent(pageToken) +
          "/cargo-places?" +
          params.toString();
      } else {
        path = "/api/ozon-fbs/driver/cargo-places?" + params.toString();
      }
      const data = await api(path);
      state.items = Array.isArray(data.items) ? data.items : [];
      state.supplies = Array.isArray(data.supplies) ? data.supplies : [];
      state.errors = Array.isArray(data.errors) ? data.errors : [];
    } catch (err) {
      if (!soft) state.items = [];
      state.errors = [String(err.message || err)];
      toast(err.message || "Не удалось загрузить грузоместа");
    } finally {
      state.loadingItems = false;
      state.softRefresh = false;
      renderResults();
    }
  }

  async function onVehicleChange(event) {
    await loadCargo(event.target.value);
  }

  function maybeAutoloadSinglePlate() {
    if (state.plates.length === 1) {
      const number = String(state.plates[0].number || "").trim();
      if (number) loadCargo(number);
    }
  }

  async function loadPlates() {
    state.loadingPlates = true;
    renderShell();
    try {
      const data = await api("/api/ozon-fbs/driver/vehicles");
      state.plates = Array.isArray(data.items) ? data.items : [];
    } catch (err) {
      state.plates = [];
      toast(err.message || "Не удалось загрузить номера");
    } finally {
      state.loadingPlates = false;
      renderShell();
      renderResults();
      maybeAutoloadSinglePlate();
    }
  }

  function init() {
    if (!main) return;
    if (isPinMode) {
      if (!pageToken) {
        renderDenied();
        return;
      }
      renderPinForm("");
      return;
    }
    if (!boot.can_view) {
      renderDenied();
      return;
    }
    loadPlates();
  }

  init();
})();
