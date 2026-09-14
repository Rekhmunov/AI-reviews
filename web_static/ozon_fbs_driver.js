/* Ozon FBS standalone driver page */
(function () {
  "use strict";

  const boot = window.OFD_BOOT || {};
  const main = document.getElementById("ofdMain");
  const toastEl = document.getElementById("ofdToast");
  let toastTimer = 0;

  const state = {
    plates: [],
    vehicleNumber: "",
    items: [],
    supplies: [],
    errors: [],
    loadingPlates: false,
    loadingItems: false,
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

  async function api(path) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (res.status === 401) {
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

  function renderShell() {
    const disabled = state.loadingPlates ? "disabled" : "";
    const placeholder = state.loadingPlates
      ? "Загрузка…"
      : "Выберите гос. номер";
    main.innerHTML =
      '<section class="ofd-panel">' +
      '<label class="ofd-label" for="ofdVehicleSelect">Номер машины</label>' +
      '<select id="ofdVehicleSelect" class="ofd-select" ' +
      disabled +
      ">" +
      '<option value="">' +
      placeholder +
      "</option>" +
      "</select>" +
      '<p class="ofd-hint">После выбора подгрузятся грузоместа со статусами «Сформировано» и «Принято на СЦ».</p>' +
      "</section>" +
      '<section class="ofd-panel" id="ofdResults">' +
      '<div class="ofd-empty">Выберите номер машины</div>' +
      "</section>";

    const select = document.getElementById("ofdVehicleSelect");
    if (!select) return;
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

  async function onVehicleChange(event) {
    const value = String(event.target.value || "").trim();
    state.vehicleNumber = value;
    state.items = [];
    state.errors = [];
    renderResults();
    if (!value) return;
    state.loadingItems = true;
    renderResults();
    try {
      const params = new URLSearchParams({ vehicle_number: value });
      const data = await api("/api/ozon-fbs/driver/cargo-places?" + params);
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
    }
  }

  function init() {
    if (!main) return;
    if (!boot.can_view) {
      renderDenied();
      return;
    }
    loadPlates();
  }

  init();
})();
