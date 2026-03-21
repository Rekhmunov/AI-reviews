function esc(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

const templateStore = {};
const categoryLabels = {
  negative_delivery: "Негатив: доставка",
  negative_product: "Негатив: товар",
  negative_other: "Негатив: прочее",
  positive_quality: "Позитив: качество",
  positive_product: "Позитив: товар",
  neutral_other: "Нейтральный: прочее",
};
const priorityLabels = {
  high: "Высокий",
  medium: "Средний",
  low: "Низкий",
};
const reviewStatusLabels = {
  queued_for_operator: "Ждет обработки",
  answered_auto: "Обработан автоматически",
  answered_manual: "Обработан оператором",
  ignored: "Игнор",
};
const conversationKindLabels = {
  question: "Вопрос",
  chat: "Чат",
};
const conversationStatusLabels = {
  open: "Открыт",
  waiting: "Ожидает",
  closed: "Закрыт",
};
const modeLabels = {
  auto: "Авто",
  manual: "Вручную",
  ignore: "Игнор",
};
const marketplaceLabels = {
  wb: "WB",
  ozon: "OZON",
  mock: "Тестовый",
};

function labelFromMap(map, value) {
  const key = String(value || "");
  return map[key] || key || "-";
}

function getPermissions() {
  const defaults = { can_view_analytics: true, can_view_settings: true };
  const fromWindow = window.APP_PERMISSIONS || {};
  return {
    can_view_analytics: Boolean(
      fromWindow.can_view_analytics !== undefined
        ? fromWindow.can_view_analytics
        : defaults.can_view_analytics,
    ),
    can_view_settings: Boolean(
      fromWindow.can_view_settings !== undefined
        ? fromWindow.can_view_settings
        : defaults.can_view_settings,
    ),
  };
}

function canViewSection(section) {
  const permissions = getPermissions();
  if (section === "analytics") return permissions.can_view_analytics;
  if (section === "settings") return permissions.can_view_settings;
  return true;
}

function showSection(section) {
  if (!canViewSection(section)) return;
  const ids = ["reviews", "conversations", "analytics", "settings", "profile"];
  for (const id of ids) {
    const sectionEl = document.getElementById("section-" + id);
    const navEl = document.getElementById("nav-" + id);
    if (sectionEl) sectionEl.classList.add("hidden");
    if (navEl) navEl.classList.remove("active");
  }
  const targetSection = document.getElementById("section-" + section);
  const targetNav = document.getElementById("nav-" + section);
  if (targetSection) targetSection.classList.remove("hidden");
  if (targetNav) targetNav.classList.add("active");
  if (section === "profile") {
    loadProfile();
  }
}

function showSettingsTab(tab) {
  const tabs = ["sources", "rules", "templates"];
  for (const name of tabs) {
    const tabBtn = document.getElementById("settings-tab-" + name);
    const pane = document.getElementById("settings-pane-" + name);
    if (tabBtn) tabBtn.classList.remove("active");
    if (pane) pane.classList.add("hidden");
  }
  document.getElementById("settings-tab-" + tab).classList.add("active");
  document.getElementById("settings-pane-" + tab).classList.remove("hidden");
}

function toggleAddSourceForm(show) {
  const form = document.getElementById("addSourceForm");
  if (!form) return;
  if (show) {
    form.classList.remove("hidden");
    onSourceMarketplaceChange();
  } else {
    form.classList.add("hidden");
  }
}

function onSourceMarketplaceChange() {
  const marketplace = document.getElementById("newSourceMarketplace")?.value || "wb";
  const ozonField = document.getElementById("ozonClientField");
  if (!ozonField) return;
  if (marketplace === "ozon") {
    ozonField.classList.remove("hidden");
  } else {
    ozonField.classList.add("hidden");
  }
}

function syncRuleFormFromStore() {
  const category = document.getElementById("ruleCategory")?.value;
  if (!category) return;
  const tpl = templateStore[category];
  if (tpl && tpl.mode) {
    document.getElementById("ruleMode").value = tpl.mode;
  }
}

function syncTemplateFormFromStore() {
  const category = document.getElementById("tplCategory")?.value;
  if (!category) return;
  const tpl = templateStore[category];
  document.getElementById("tplText").value = tpl ? (tpl.template_text || "") : "";
}

async function syncAll() {
  const payload = { all_accounts: true, account_id: null };
  const res = await fetch("/api/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("syncInfo").textContent = "Ошибка: " + (data.detail || "синхронизация не выполнена");
    return;
  }
  const failed = data.failed_accounts || 0;
  let text = `Кабинетов: ${data.accounts}, отзывов: ${data.loaded}, вопросов/чатов: ${data.loaded_conversations || 0}`;
  if (failed > 0) text += `, ошибок: ${failed}`;
  document.getElementById("syncInfo").textContent = text;
  const tasks = [loadReviews(), loadConversations()];
  if (canViewSection("analytics")) tasks.push(loadAnalytics());
  await Promise.all(tasks);
}

async function loadReviews() {
  const priority = document.getElementById("priorityFilter").value;
  const status = document.getElementById("statusFilter").value;
  const category = document.getElementById("categoryFilter").value;
  const query = new URLSearchParams();
  if (priority) query.set("priority", priority);
  if (status) query.set("status", status);
  if (category) query.set("category", category);

  const res = await fetch("/api/reviews?" + query.toString());
  const data = await res.json();
  const tbody = document.getElementById("reviewsTbody");
  tbody.innerHTML = "";
  for (const review of data.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(review.source)}</td>
      <td>
        <div>${esc(review.text)}</div>
        <div class="small">автор: ${esc(review.author || "-")} | оценка: ${esc(review.rating ?? "-")} | категория: ${esc(labelFromMap(categoryLabels, review.category))}</div>
      </td>
      <td>
        <div class="small">автоответ: ${esc(review.auto_reply || "-")}</div>
        <div class="small">ответ оператора: ${esc(review.manual_reply || "-")}</div>
      </td>
      <td><span class="pill ${esc(review.priority)}">${esc(labelFromMap(priorityLabels, review.priority))}</span></td>
      <td>${esc(labelFromMap(reviewStatusLabels, review.status))}</td>
      <td>
        <button onclick="autoReply('${esc(review.review_uid)}')">Автоответ</button>
        <button class="secondary" onclick="queueManual('${esc(review.review_uid)}')">Вручную</button>
        <button class="secondary" onclick="manualReply('${esc(review.review_uid)}')">Ответ оператора</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

async function loadConversations() {
  const kind = document.getElementById("conversationKindFilter").value;
  const status = document.getElementById("conversationStatusFilter").value;
  const query = new URLSearchParams();
  if (kind) query.set("kind", kind);
  if (status) query.set("status", status);
  const res = await fetch("/api/conversations?" + query.toString());
  const data = await res.json();
  const tbody = document.getElementById("conversationsTbody");
  tbody.innerHTML = "";
  for (const item of data.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(labelFromMap(conversationKindLabels, item.kind))}</td>
      <td>${esc(item.source)}</td>
      <td>${esc(item.customer_name || "-")}</td>
      <td>${esc(item.message_text || "-")}</td>
      <td>${esc(item.unread_count ?? 0)}</td>
      <td>${esc(labelFromMap(conversationStatusLabels, item.status))}</td>
      <td>
        <button class="secondary" onclick="setConversationStatus('${esc(item.conversation_uid)}', 'waiting')">В ожидании</button>
        <button class="secondary" onclick="setConversationStatus('${esc(item.conversation_uid)}', 'closed')">Закрыть</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

async function setConversationStatus(conversationUid, status) {
  const payload = { status: status };
  const res = await fetch(`/api/conversations/${encodeURIComponent(conversationUid)}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Ошибка обновления статуса");
    return;
  }
  await loadConversations();
}

async function loadAnalytics() {
  const res = await fetch("/api/analytics");
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("analyticsInfo").textContent = data.detail || "Ошибка загрузки аналитики";
    return;
  }
  document.getElementById("anTotal").textContent = String(data.total_reviews || 0);
  document.getElementById("anProcessed").textContent = String(data.processed_reviews || 0);
  document.getElementById("anPositive").textContent = String(data.positive_percent || 0) + "%";
  document.getElementById("anNegative").textContent = String(data.negative_percent || 0) + "%";
  document.getElementById("anQuestions").textContent = String(data.questions_count || 0);
  document.getElementById("anChats").textContent = String(data.chats_count || 0);
  document.getElementById("analyticsInfo").textContent =
    `Позитивных: ${data.positive_count || 0}, негативных: ${data.negative_count || 0}, всего диалогов: ${data.conversation_total || 0}`;
}

async function loadAccounts() {
  const res = await fetch("/api/accounts");
  const data = await res.json();
  const tbody = document.getElementById("accountsTbody");
  tbody.innerHTML = "";
  for (const account of data.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(account.id)}</td>
      <td>${esc(labelFromMap(marketplaceLabels, account.marketplace))}</td>
      <td>${esc(account.account_name)}</td>
      <td>${esc(account.api_url)}</td>
      <td>${esc((account.extra || {}).client_id || "-")}</td>
      <td>${esc(account.api_key_preview || "-")}</td>
      <td>${esc(account.is_active ? "Да" : "Нет")}</td>
      <td>
        <button class="secondary" onclick="toggleAccount(${account.id}, ${account.is_active ? "false" : "true"})">
          ${account.is_active ? "Отключить" : "Включить"}
        </button>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

async function createAccount() {
  const marketplace = document.getElementById("newSourceMarketplace").value;
  const accountName = document.getElementById("newSourceName").value.trim();
  const apiToken = document.getElementById("newSourceApiToken").value.trim();
  const clientId = document.getElementById("newSourceClientId").value.trim();

  if (!accountName) {
    document.getElementById("accountsInfo").textContent = "Ошибка: укажите название кабинета";
    return;
  }
  if (!apiToken) {
    document.getElementById("accountsInfo").textContent = "Ошибка: укажите токен доступа";
    return;
  }
  if (marketplace === "ozon" && !clientId) {
    document.getElementById("accountsInfo").textContent = "Ошибка: укажите идентификатор клиента для OZON";
    return;
  }

  const payload = {
    marketplace: marketplace,
    account_name: accountName,
    client_id: marketplace === "ozon" ? clientId : null,
    api_key: apiToken,
    integration: null,
  };
  const res = await fetch("/api/accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("accountsInfo").textContent = "Ошибка: " + (data.detail || "не удалось сохранить");
    return;
  }
  document.getElementById("accountsInfo").textContent = "Кабинет добавлен.";
  document.getElementById("newSourceName").value = "";
  document.getElementById("newSourceClientId").value = "";
  document.getElementById("newSourceApiToken").value = "";
  toggleAddSourceForm(false);
  await loadAccounts();
}

async function toggleAccount(accountId, active) {
  const payload = { is_active: active };
  await fetch(`/api/accounts/${accountId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await loadAccounts();
}

async function loadTemplates() {
  const res = await fetch("/api/templates");
  const data = await res.json();
  for (const key of Object.keys(templateStore)) delete templateStore[key];

  const tbody = document.getElementById("templatesTbody");
  const rulesBody = document.getElementById("rulesTbody");
  tbody.innerHTML = "";
  if (rulesBody) rulesBody.innerHTML = "";

  for (const tpl of data.items || []) {
    templateStore[tpl.category] = tpl;

    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(labelFromMap(categoryLabels, tpl.category))}</td><td>${esc(labelFromMap(modeLabels, tpl.mode))}</td><td>${esc(tpl.template_text)}</td>`;
    tbody.appendChild(tr);

    if (rulesBody) {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${esc(labelFromMap(categoryLabels, tpl.category))}</td><td>${esc(labelFromMap(modeLabels, tpl.mode))}</td>`;
      rulesBody.appendChild(row);
    }
  }
  syncRuleFormFromStore();
  syncTemplateFormFromStore();
}

async function saveRuleOnly() {
  const category = document.getElementById("ruleCategory").value;
  const mode = document.getElementById("ruleMode").value;
  const existingTemplate = templateStore[category]?.template_text || "";

  const payload = {
    category: category,
    mode: mode,
    template_text: existingTemplate,
  };
  const res = await fetch("/api/templates", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("rulesInfo").textContent = "Ошибка: " + (data.detail || "не удалось сохранить");
    return;
  }
  document.getElementById("rulesInfo").textContent = "Правило сохранено.";
  await loadTemplates();
}

async function saveTemplateText() {
  const category = document.getElementById("tplCategory").value;
  const existingMode = templateStore[category]?.mode || "manual";
  const payload = {
    category: category,
    mode: existingMode,
    template_text: document.getElementById("tplText").value,
  };
  const res = await fetch("/api/templates", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("templatesInfo").textContent = "Ошибка: " + (data.detail || "не удалось сохранить");
    return;
  }
  document.getElementById("templatesInfo").textContent = "Шаблон сохранен.";
  await loadTemplates();
}

async function queueManual(reviewId) {
  await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/queue-manual`, { method: "POST" });
  await loadReviews();
}

async function autoReply(reviewId) {
  const res = await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/auto-reply`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Ошибка автоответа");
    return;
  }
  alert("Автоответ: " + data.reply);
  await loadReviews();
}

async function manualReply(reviewId) {
  const operator = prompt("Имя оператора:");
  if (!operator) return;
  const text = prompt("Текст ручного ответа:");
  if (!text) return;
  const payload = { operator_name: operator, response_text: text };
  const res = await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/manual-reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Ошибка ручного ответа");
    return;
  }
  await loadReviews();
}

async function loadProfile() {
  const res = await fetch("/api/profile");
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("profileInfo").textContent = data.detail || "Ошибка загрузки профиля";
    return;
  }
  document.getElementById("profileFullName").value = data.full_name || "";
  document.getElementById("profileEmail").value = data.email || "";
  document.getElementById("profileCurrentPassword").value = "";
  document.getElementById("profileNewPassword").value = "";
  document.getElementById("profileNewPasswordRepeat").value = "";
  setPasswordFieldsVisible(false);
  document.getElementById("profileInfo").textContent = "";
}

function setPasswordFieldsVisible(visible) {
  const fields = document.getElementById("profilePasswordFields");
  const toggleLink = document.getElementById("profilePasswordToggle");
  if (!fields || !toggleLink) return;
  if (visible) {
    fields.classList.remove("hidden");
    toggleLink.textContent = "Скрыть смену пароля";
    return;
  }
  fields.classList.add("hidden");
  toggleLink.textContent = "Изменить пароль";
  document.getElementById("profileCurrentPassword").value = "";
  document.getElementById("profileNewPassword").value = "";
  document.getElementById("profileNewPasswordRepeat").value = "";
}

function togglePasswordFields(event) {
  if (event) event.preventDefault();
  const fields = document.getElementById("profilePasswordFields");
  const isHidden = fields?.classList.contains("hidden") ?? true;
  setPasswordFieldsVisible(isHidden);
}

async function saveProfile() {
  const payload = {
    full_name: document.getElementById("profileFullName").value.trim() || null,
    email: document.getElementById("profileEmail").value.trim() || null,
    current_password: document.getElementById("profileCurrentPassword").value || null,
    new_password: document.getElementById("profileNewPassword").value || null,
    new_password_repeat: document.getElementById("profileNewPasswordRepeat").value || null,
  };
  const res = await fetch("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("profileInfo").textContent = "Ошибка: " + (data.detail || "не удалось обновить профиль");
    return;
  }
  document.getElementById("profileInfo").textContent = "Изменения сохранены";
  await loadProfile();
}

document.addEventListener("DOMContentLoaded", () => {
  const permissions = getPermissions();
  if (!permissions.can_view_analytics) {
    document.getElementById("section-analytics")?.classList.add("hidden");
  }
  if (!permissions.can_view_settings) {
    document.getElementById("section-settings")?.classList.add("hidden");
  } else {
    showSettingsTab("sources");
  }
  onSourceMarketplaceChange();
  setPasswordFieldsVisible(false);
  document.getElementById("ruleCategory")?.addEventListener("change", syncRuleFormFromStore);
  document.getElementById("tplCategory")?.addEventListener("change", syncTemplateFormFromStore);
  loadReviews();
  loadConversations();
  if (permissions.can_view_analytics) {
    loadAnalytics();
  }
  if (permissions.can_view_settings) {
    loadAccounts();
    loadTemplates();
  }
});
