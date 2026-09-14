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
    if (st === "acceptance_in_progress") return "is-sc";
    if (st === "formed") return "is-formed";
    return "";
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
        "</select>" +
        '<p class="ofd-hint">После выбора подгрузятся грузоместа со статусами «Сформировано» и «Принято на СЦ».</p>';
    }

    main.innerHTML =
      '<section class="ofd-panel">' +
      driverLine +
      vehicleBlock +
      "</section>" +
      '<section class="ofd-panel" id="ofdResults">' +
      '<div class="ofd-empty">Выберите номер машины</div>' +
      "</section>";

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
      box.innerHTML = '<div class="ofd-empty">Выберите номер машины</div>';
      return;
    }
    if (state.loadingItems) {
      box.innerHTML = '<div class="ofd-loading">Загрузка грузомест…</div>';
      return;
    }

    const errorsHtml = state.errors.length
      ? '<div class="ofd-errors">' +
        state.errors.map(esc).join("<br>") +
        "</div>"
      : "";

    if (!state.items.length) {
      box.innerHTML =
        '<div class="ofd-list-head">' +
        '<h2 class="ofd-list-title">Грузоместа</h2>' +
        '<div class="ofd-list-count">0</div>' +
        "</div>" +
        errorsHtml +
        '<div class="ofd-empty">Нет грузомест со статусом «Сформировано» или «Принято на СЦ» для этого номера.</div>';
      return;
    }

    const rows = state.items
      .map(function (item) {
        const num = Number(item.container_number || 0);
        const metaParts = [];
        if (item.supply_name) {
          metaParts.push(
            "<div><span>Поставка:</span> " + esc(item.supply_name) + "</div>"
          );
        }
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
        return (
          '<li class="ofd-item">' +
          '<div class="ofd-item-top">' +
          "<div>" +
          '<div class="ofd-item-num">ГМ № ' +
          esc(String(num || "—")) +
          "</div>" +
          '<div class="ofd-item-id">ID ' +
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
      '<ul class="ofd-items">' +
      rows +
      "</ul>";
  }

  async function loadCargo(value) {
    const plate = String(value || "").trim();
    state.vehicleNumber = plate;
    state.items = [];
    state.errors = [];
    renderResults();
    if (!plate) return;
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
      state.items = [];
      state.errors = [String(err.message || err)];
      toast(err.message || "Не удалось загрузить грузоместа");
    } finally {
      state.loadingItems = false;
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
