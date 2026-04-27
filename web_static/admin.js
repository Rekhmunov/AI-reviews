function esc(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function readCookie(name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

function csrfHeaders(extra = {}) {
  const token = readCookie("csrf_token");
  if (token) return { ...extra, "X-CSRF-Token": token };
  return { ...extra };
}

const roleLabels = {
  user: "пользователь",
  feedback_manager: "менеджер обратной связи",
  admin: "администратор",
};
const reviewStatusLabels = {
  queued_for_operator: "Ждет обработки",
  answered_auto: "Обработан автоматически",
  answered_manual: "Обработан оператором",
  ignored: "Игнор",
};
const actionTypeLabels = {
  sync_error: "Ошибка синхронизации",
  sync_review: "Синхронизация отзыва",
  sync_conversation: "Синхронизация диалога",
  queue_manual: "Перевод в ручную обработку",
  auto_reply: "Автоответ",
  manual_reply: "Ручной ответ",
  conversation_status: "Смена статуса диалога",
};
const detailKeyLabels = {
  category: "категория",
  status: "статус",
  source: "источник",
  account_id: "идентификатор кабинета",
  error: "ошибка",
  scope: "область",
  kind: "тип",
  reply: "ответ",
  marketplace: "маркетплейс",
};
const categoryLabels = {
  positive: "Позитив",
  product_dissatisfaction: "Недовольство товаром",
  delivery_problems: "Проблемы при доставке",
  wrong_size: "Неправильный размер",
  tagged_reviews: "Отзывы с тегами",
  textless_ratings: "Оценки без текста",
  negative_delivery: "Негатив: доставка",
  negative_product: "Негатив: товар",
  negative_other: "Негатив: прочее",
  positive_quality: "Позитив: качество",
  positive_product: "Позитив: товар",
  neutral_other: "Нейтральный: прочее",
};
const conversationKindLabels = {
  question: "вопрос",
  chat: "чат",
};
const conversationStatusLabels = {
  open: "открыт",
  waiting: "ожидает",
  closed: "закрыт",
};
const groupTitles = {
  positive: "Позитив",
  product_dissatisfaction: "Недовольство товаром",
  delivery_problems: "Проблемы при доставке",
  wrong_size: "Неправильный размер",
  tagged_reviews: "Отзывы с тегами",
  textless_ratings: "Оценки без текста",
};
const processorLabels = {
  yandex: "Яндекс",
  program: "Программа",
};
const tenantRoleLabels = {
  admin: "администратор кабинета",
  feedback_manager: "менеджер обратной связи",
};
const ALL_ROLE_VALUES = ["user", "feedback_manager", "admin"];
const TENANT_ROLE_VALUES = ["feedback_manager", "admin"];

const adminState = {
  context: null,
};
const defaultTemplatesState = {
  items: [],
  currentGroupId: null,
  currentGroupTitle: "",
  currentSubgroup: "",
  currentTemplates: [],
};
const templateVariablesState = {
  items: [],
  editKey: null,
};
const actionsState = {
  page: 1,
  pageSize: 50,
  hasMore: false,
};
const usersState = {
  items: [],
  search: "",
  page: 1,
  pageSize: 10,
};
const tariffEditorState = {
  mode: "create",
  originalCode: null,
};

function normalizeNumber(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return parsed;
}

function tariffLimitsFromFields() {
  return {
    reviews_per_month: Math.max(0, Math.floor(normalizeNumber(document.getElementById("tariffLimitReviews")?.value, 0))),
    managers: Math.max(0, Math.floor(normalizeNumber(document.getElementById("tariffLimitManagers")?.value, 0))),
    sources: Math.max(0, Math.floor(normalizeNumber(document.getElementById("tariffLimitSources")?.value, 0))),
    ai_units: Math.max(0, Math.floor(normalizeNumber(document.getElementById("tariffLimitAiUnits")?.value, 0))),
  };
}

function openTariffForm(mode = "create", item = null) {
  const form = document.getElementById("tariffFormPanel");
  if (!form) return;
  const isEdit = mode === "edit" && item;
  tariffEditorState.mode = isEdit ? "edit" : "create";
  tariffEditorState.originalCode = isEdit ? String(item.code || "").trim().toLowerCase() : null;

  const title = document.getElementById("tariffFormTitle");
  const saveBtn = document.getElementById("tariffSaveButton");
  const cancelBtn = document.getElementById("tariffCancelButton");
  const codeInput = document.getElementById("tariffCode");
  const nameInput = document.getElementById("tariffTitle");
  const priceInput = document.getElementById("tariffPrice");
  const reviewsInput = document.getElementById("tariffLimitReviews");
  const managersInput = document.getElementById("tariffLimitManagers");
  const sourcesInput = document.getElementById("tariffLimitSources");
  const aiUnitsInput = document.getElementById("tariffLimitAiUnits");
  const activeInput = document.getElementById("tariffIsActive");

  if (title) title.textContent = isEdit ? "Изменить тариф" : "Добавить тариф";
  if (saveBtn) saveBtn.textContent = isEdit ? "Сохранить изменения" : "Создать тариф";
  if (cancelBtn) cancelBtn.classList.toggle("hidden", !isEdit);

  const limits = (item && item.limits) || {};
  if (codeInput) codeInput.value = isEdit ? String(item.code || "") : "";
  if (nameInput) nameInput.value = isEdit ? String(item.title || "") : "";
  if (priceInput) priceInput.value = isEdit ? String(item.monthly_price ?? 0) : "";
  if (reviewsInput) reviewsInput.value = isEdit ? String(limits.reviews_per_month ?? 0) : "";
  if (managersInput) managersInput.value = isEdit ? String(limits.managers ?? 0) : "";
  if (sourcesInput) sourcesInput.value = isEdit ? String(limits.sources ?? 0) : "";
  if (aiUnitsInput) aiUnitsInput.value = isEdit ? String(limits.ai_units ?? 0) : "";
  if (activeInput) activeInput.checked = isEdit ? Boolean(item.is_active) : true;

  form.classList.remove("hidden");
}

function openCreateTariffForm() {
  openTariffForm("create");
}

function closeTariffForm() {
  const form = document.getElementById("tariffFormPanel");
  if (!form) return;
  tariffEditorState.mode = "create";
  tariffEditorState.originalCode = null;
  form.classList.add("hidden");
}

function isSuperAdmin() {
  return Boolean(adminState.context && adminState.context.is_super_admin);
}

function isTenantOwner() {
  return Boolean(adminState.context && adminState.context.is_tenant_owner);
}

function labelFromMap(map, value) {
  const key = String(value || "");
  return map[key] || key || "-";
}

function formatActionDetails(details) {
  if (!details || typeof details !== "object") return "-";
  const parts = [];
  for (const [key, rawValue] of Object.entries(details)) {
    let value = rawValue;
    if (key === "category") value = labelFromMap(categoryLabels, rawValue);
    if (key === "status") {
      value = labelFromMap(reviewStatusLabels, rawValue);
      if (value === String(rawValue)) value = labelFromMap(conversationStatusLabels, rawValue);
    }
    if (key === "kind") value = labelFromMap(conversationKindLabels, rawValue);
    const label = detailKeyLabels[key] || "параметр";
    parts.push(`${label}: ${value}`);
  }
  return parts.join("; ");
}

function buildRoleOptions(selectedRole) {
  const availableRoles = isSuperAdmin() ? ALL_ROLE_VALUES : TENANT_ROLE_VALUES;
  return availableRoles
    .map((role) => {
      const selected = role === selectedRole ? " selected" : "";
      return `<option value="${role}"${selected}>${esc(roleLabels[role] || role)}</option>`;
    })
    .join("");
}

async function loadAdminContext() {
  const res = await fetch("/api/admin/context");
  const data = await res.json();
  if (!res.ok) {
    setUsersInfo(data.detail || "Не удалось определить контекст администратора", true);
    adminState.context = null;
    return false;
  }
  adminState.context = data;

  const roleSelect = document.getElementById("newUserRole");
  if (roleSelect) {
    const allowedRoles = isSuperAdmin() ? ALL_ROLE_VALUES : TENANT_ROLE_VALUES;
    roleSelect.innerHTML = "";
    for (const role of allowedRoles) {
      const option = document.createElement("option");
      option.value = role;
      option.textContent = roleLabels[role] || role;
      roleSelect.appendChild(option);
    }
    roleSelect.value = allowedRoles.includes("feedback_manager") ? "feedback_manager" : allowedRoles[0];
  }

  const superAiPanel = document.getElementById("superAdminAiPanel");
  const superSaasPanel = document.getElementById("superAdminSaasPanel");
  if (isSuperAdmin()) {
    if (superAiPanel) superAiPanel.classList.remove("hidden");
    if (superSaasPanel) superSaasPanel.classList.remove("hidden");
    document.getElementById("superAdminDefaultTemplatesPanel")?.classList.remove("hidden");
  } else {
    if (superAiPanel) superAiPanel.classList.add("hidden");
    if (superSaasPanel) superSaasPanel.classList.add("hidden");
    document.getElementById("superAdminDefaultTemplatesPanel")?.classList.add("hidden");
  }
  return true;
}

function setUsersInfo(message, isError = false) {
  const info = document.getElementById("usersInfo");
  if (!info) return;
  info.textContent = message || "";
  info.style.color = isError ? "#b91c1c" : "";
}

function renderGroupProcessors(modes) {
  const tbody = document.getElementById("groupProcessorsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const entries = Object.entries(groupTitles);
  for (const [groupId, title] of entries) {
    const selectedMode = String((modes || {})[groupId] || (groupId === "tagged_reviews" || groupId === "textless_ratings" ? "program" : "yandex"));
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(title)}</td>
      <td>
        <select data-group-id="${esc(groupId)}" class="group-processor-select">
          <option value="yandex" ${selectedMode === "yandex" ? "selected" : ""}>${esc(processorLabels.yandex)}</option>
          <option value="program" ${selectedMode === "program" ? "selected" : ""}>${esc(processorLabels.program)}</option>
        </select>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

async function loadAiSettings() {
  const res = await fetch("/api/admin/ai-settings");
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("aiInfo").textContent = data.detail || "Ошибка";
    return;
  }
  document.getElementById("provider").value = data.provider || "rules";
  document.getElementById("apiKey").value = "";
  document.getElementById("folderId").value = data.yandex_folder_id || "";
  document.getElementById("modelUri").value = data.yandex_model_uri || "";
  renderGroupProcessors(data.group_processors || {});
  const lookbackInput = document.getElementById("defaultSyncLookbackDays");
  if (lookbackInput) {
    const lookback = Number(data.default_sync_lookback_days || 7);
    lookbackInput.value = String(Number.isFinite(lookback) ? lookback : 7);
  }
  document.getElementById("aiInfo").textContent = "";
}

function syncDateToggle() {
  return;
}

async function saveAiSettings() {
  const groupProcessors = {};
  document.querySelectorAll(".group-processor-select").forEach((element) => {
    const groupId = String(element.getAttribute("data-group-id") || "").trim();
    const mode = String(element.value || "").trim().toLowerCase();
    if (!groupId) return;
    if (!["yandex", "program"].includes(mode)) return;
    groupProcessors[groupId] = mode;
  });
  const payload = {
    provider: document.getElementById("provider").value,
    yandex_api_key: document.getElementById("apiKey").value.trim() || null,
    yandex_folder_id: document.getElementById("folderId").value.trim() || null,
    yandex_model_uri: document.getElementById("modelUri").value.trim() || null,
    group_processors: groupProcessors,
    use_sync_start_date: false,
    sync_start_date: null,
    default_sync_lookback_days: Number(document.getElementById("defaultSyncLookbackDays")?.value || "7"),
  };
  const res = await fetch("/api/admin/ai-settings", {
    method: "PUT",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("aiInfo").textContent = "Ошибка: " + (data.detail || "не удалось сохранить");
    return;
  }
  document.getElementById("aiInfo").textContent = "Настройки сохранены";
  await loadAiSettings();
}

function getFilteredUsers() {
  const query = usersState.search.trim().toLowerCase();
  const source = Array.isArray(usersState.items) ? usersState.items : [];
  if (!query) return source;
  return source.filter((user) => String(user.email || "").toLowerCase().includes(query));
}

function renderUsers() {
  const tbody = document.getElementById("usersTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const filtered = getFilteredUsers();
  const total = filtered.length;
  const pageSize = Math.max(1, Number(usersState.pageSize || 10));
  const pages = Math.max(1, Math.ceil(total / pageSize));
  usersState.page = Math.min(Math.max(1, usersState.page), pages);
  const start = (usersState.page - 1) * pageSize;
  const pageItems = filtered.slice(start, start + pageSize);
  const tariffOptions = (window.__AVAILABLE_PLANS__ || [])
    .map((plan) => {
      const code = String(plan.code || "");
      const title = String(plan.title || code);
      return `<option value="${esc(code)}">${esc(title)} (${esc(code)})</option>`;
    })
    .join("");
  if (!pageItems.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="9">Пользователи не найдены</td>`;
    tbody.appendChild(tr);
  }
  for (const user of pageItems) {
    const tr = document.createElement("tr");
    const roleSelectId = `role-select-${user.id}`;
    const passwordInputId = `password-input-${user.id}`;
    const planSelectId = `plan-select-${user.id}`;
    const blocked = Boolean(user.is_blocked);
    const blockButtonLabel = blocked ? "Разблокировать" : "Заблокировать";
    const roleLabel = roleLabels[user.role] || user.role || "-";
    const blockedCell = blocked
      ? `<span class="small status-badge status-blocked">заблокирован</span>`
      : `<span class="small status-badge status-active">активен</span>`;
    const subscriptionStatus = String(user.subscription_status || "inactive").toLowerCase();
    const subscriptionLabelMap = {
      active: "Активна",
      grace: "Льготный период",
      suspended: "Приостановлена",
      cancelled: "Отключена",
      inactive: "Не активирована",
    };
    const paidUntilRaw = String(user.subscription_paid_until || "").trim();
    const paidUntil = paidUntilRaw ? paidUntilRaw.slice(0, 10) : "-";
    tr.innerHTML = `
      <td>${esc(user.id)}</td>
      <td>${esc(user.email)}</td>
      <td>
        <select id="${planSelectId}">
          ${tariffOptions}
        </select>
      </td>
      <td>${esc(subscriptionLabelMap[subscriptionStatus] || subscriptionStatus || "Не активирована")}</td>
      <td>${esc(paidUntil)}</td>
      <td>
        <input id="${passwordInputId}" type="password" placeholder="Новый пароль" />
      </td>
      <td>
        <select id="${roleSelectId}">
          ${buildRoleOptions(user.role)}
        </select>
        <div class="small">${esc(roleLabel)}</div>
      </td>
      <td>${blockedCell}</td>
      <td>
        <div class="row">
          <button onclick="setRole(${user.id}, document.getElementById('${roleSelectId}').value)">Сохранить роль</button>
          <button class="secondary" onclick="setUserPlan(${user.id}, document.getElementById('${planSelectId}').value)">Сменить тариф</button>
          <button class="secondary" onclick="setUserPassword(${user.id}, document.getElementById('${passwordInputId}').value)">Сменить пароль</button>
          <button class="secondary" onclick="toggleUserBlock(${user.id}, ${blocked ? "false" : "true"})">${blockButtonLabel}</button>
          <button class="secondary danger" onclick="deleteUser(${user.id})">Удалить</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
    const planSelect = document.getElementById(planSelectId);
    if (planSelect) {
      planSelect.value = String(user.plan_code || "");
      if (!planSelect.value) {
        planSelect.value = "starter";
      }
    }
  }
  const pageInfo = document.getElementById("usersPaginationInfo");
  if (pageInfo) {
    pageInfo.textContent = `Страница ${usersState.page} из ${pages}. Всего клиентов: ${total}`;
  }
  const prevBtn = document.getElementById("usersPrevPageButton");
  if (prevBtn) prevBtn.disabled = usersState.page <= 1;
  const nextBtn = document.getElementById("usersNextPageButton");
  if (nextBtn) nextBtn.disabled = usersState.page >= pages;
}

async function loadUsers() {
  const usersRes = await fetch("/api/admin/users");
  const usersData = await usersRes.json();
  if (!usersRes.ok) {
    setUsersInfo(usersData.detail || "Не удалось загрузить пользователей", true);
    return;
  }
  let tariffs = [];
  if (isSuperAdmin()) {
    const tariffsRes = await fetch("/api/super-admin/tariffs");
    const tariffsData = await tariffsRes.json();
    if (!tariffsRes.ok) {
      setUsersInfo(tariffsData.detail || "Не удалось загрузить тарифы для пользователей", true);
      return;
    }
    tariffs = tariffsData.items || [];
  }
  usersState.items = usersData.items || [];
  window.__AVAILABLE_PLANS__ = tariffs;
  renderUsers();
}

function onUsersSearchInput(value) {
  usersState.search = String(value || "");
  usersState.page = 1;
  renderUsers();
}

async function prevUsersPage() {
  if (usersState.page <= 1) return;
  usersState.page -= 1;
  renderUsers();
}

async function nextUsersPage() {
  const total = getFilteredUsers().length;
  const pages = Math.max(1, Math.ceil(total / usersState.pageSize));
  if (usersState.page >= pages) return;
  usersState.page += 1;
  renderUsers();
}

async function setRole(userId, role) {
  const res = await fetch(`/api/admin/users/${userId}/role`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ role }),
  });
  const data = await res.json();
  if (!res.ok) {
    setUsersInfo(data.detail || "Ошибка смены роли", true);
    return;
  }
  setUsersInfo("Роль пользователя обновлена.");
  await loadUsers();
}

async function setUserPlan(userId, planCode) {
  const normalized = String(planCode || "").trim().toLowerCase();
  if (!normalized) {
    setUsersInfo("Выберите тарифный план.", true);
    return;
  }
  const res = await fetch(`/api/admin/users/${userId}/plan`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ plan_code: normalized }),
  });
  const data = await res.json();
  if (!res.ok) {
    setUsersInfo(data.detail || "Ошибка смены тарифа пользователя", true);
    return;
  }
  setUsersInfo("Тариф пользователя обновлен.");
  await loadUsers();
}

async function toggleUserBlock(userId, blocked) {
  const reason = blocked ? prompt("Причина блокировки (необязательно):", "") : "";
  const payload = {
    blocked: Boolean(blocked),
    reason: blocked ? (reason || "").trim() : null,
  };
  const res = await fetch(`/api/admin/users/${userId}/block`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setUsersInfo(data.detail || "Ошибка изменения статуса блокировки", true);
    return;
  }
  setUsersInfo(payload.blocked ? "Пользователь заблокирован." : "Пользователь разблокирован.");
  await loadUsers();
}

async function deleteUser(userId) {
  const confirmed = window.confirm("Удалить пользователя? Действие необратимо.");
  if (!confirmed) return;
  const res = await fetch(`/api/admin/users/${userId}/delete`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ confirm: true }),
  });
  const data = await res.json();
  if (!res.ok) {
    setUsersInfo(data.detail || "Ошибка удаления пользователя", true);
    return;
  }
  setUsersInfo("Пользователь удален.");
  await loadUsers();
}

async function createUser() {
  const emailInput = document.getElementById("newUserEmail");
  const passwordInput = document.getElementById("newUserPassword");
  const roleInput = document.getElementById("newUserRole");
  const payload = {
    email: String(emailInput?.value || "").trim(),
    password: String(passwordInput?.value || ""),
    role: String(roleInput?.value || "user"),
  };
  if (!payload.email || !payload.password) {
    setUsersInfo("Заполните эл. почту и пароль нового пользователя.", true);
    return;
  }
  const res = await fetch("/api/admin/users", {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setUsersInfo(data.detail || "Ошибка создания пользователя", true);
    return;
  }
  if (emailInput) emailInput.value = "";
  if (passwordInput) passwordInput.value = "";
  if (roleInput) roleInput.value = "user";
  setUsersInfo("Пользователь создан.");
  await loadUsers();
}

async function setUserPassword(userId, password) {
  const cleanPassword = String(password || "");
  if (!cleanPassword) {
    setUsersInfo("Введите новый пароль для выбранного пользователя.", true);
    return;
  }
  const res = await fetch(`/api/admin/users/${userId}/password`, {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ password: cleanPassword }),
  });
  const data = await res.json();
  if (!res.ok) {
    setUsersInfo(data.detail || "Ошибка смены пароля", true);
    return;
  }
  const input = document.getElementById(`password-input-${userId}`);
  if (input) input.value = "";
  setUsersInfo("Пароль пользователя обновлен.");
}

function setSuperAdminInfo(message, isError = false) {
  const info = document.getElementById("saasInfo");
  if (!info) return;
  info.textContent = message || "";
  info.style.color = isError ? "#b91c1c" : "";
}

function setDefaultTemplatesInfo(message, isError = false) {
  const info = document.getElementById("defaultTemplatesInfo");
  if (!info) return;
  info.textContent = message || "";
  info.style.color = isError ? "#b91c1c" : "";
}

function setTemplateVariablesInfo(message, isError = false) {
  const info = document.getElementById("templateVariablesInfo");
  if (!info) return;
  info.textContent = message || "";
  info.style.color = isError ? "#b91c1c" : "";
}

function normalizeTemplateVariableKey(value) {
  const raw = String(value || "").trim().toUpperCase();
  if (!raw) return "";
  if (/^%[A-Z0-9_]{2,50}%$/.test(raw)) return raw;
  return "";
}

function fillTemplateVariableForm(item = null) {
  const payload = item && typeof item === "object" ? item : {};
  const varKeyInput = document.getElementById("templateVarKey");
  if (varKeyInput) varKeyInput.value = String(payload.var_key || "");
  const titleInput = document.getElementById("templateVarTitle");
  if (titleInput) titleInput.value = String(payload.title || "");
  const descriptionInput = document.getElementById("templateVarDescription");
  if (descriptionInput) descriptionInput.value = String(payload.description || "");
  const sourceTypeInput = document.getElementById("templateVarSourceType");
  if (sourceTypeInput) sourceTypeInput.value = String(payload.source_type || "manual");
  const sourcePathInput = document.getElementById("templateVarSourcePath");
  if (sourcePathInput) sourcePathInput.value = String(payload.source_path || "");
  const defaultValueInput = document.getElementById("templateVarDefaultValue");
  if (defaultValueInput) defaultValueInput.value = String(payload.default_value || "");
  const userEditableInput = document.getElementById("templateVarUserEditable");
  if (userEditableInput) userEditableInput.checked = Boolean(payload.is_user_editable);
  const activeInput = document.getElementById("templateVarIsActive");
  if (activeInput) activeInput.checked = payload.is_active !== false;
  templateVariablesState.editKey = payload.var_key ? String(payload.var_key).toUpperCase() : null;
}

function resetTemplateVariableForm() {
  fillTemplateVariableForm(null);
}

function renderTemplateVariablesList() {
  const tbody = document.getElementById("templateVariablesTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const items = Array.isArray(templateVariablesState.items) ? templateVariablesState.items : [];
  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="8" class="small">Переменные пока не настроены</td>`;
    tbody.appendChild(tr);
    return;
  }
  for (const item of items) {
    const varKey = String(item.var_key || "");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(varKey)}</td>
      <td>${esc(item.title || "")}</td>
      <td>${esc(item.source_type || "manual")}</td>
      <td>${esc(item.source_path || "-")}</td>
      <td>${item.is_user_editable ? "да" : "нет"}</td>
      <td>${item.is_active ? "да" : "нет"}</td>
      <td>${esc(item.default_value || "")}</td>
      <td>
        <div class="row">
          <button class="secondary" type="button" onclick="editTemplateVariableByKey('${esc(varKey)}')">Изменить</button>
          <button class="secondary danger" type="button" onclick="deleteTemplateVariable('${esc(varKey)}')">Удалить</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

function editTemplateVariableByKey(varKey) {
  const key = String(varKey || "").trim().toUpperCase();
  if (!key) return;
  const item = (templateVariablesState.items || []).find(
    (row) => String(row.var_key || "").trim().toUpperCase() === key,
  );
  if (!item) return;
  fillTemplateVariableForm(item);
  setTemplateVariablesInfo("");
}

async function loadTemplateVariables() {
  if (!isSuperAdmin()) return;
  const res = await fetch("/api/super-admin/template-variables");
  const data = await res.json();
  if (!res.ok) {
    setTemplateVariablesInfo(data.detail || "Не удалось загрузить переменные шаблонов", true);
    return;
  }
  templateVariablesState.items = data.items || [];
  renderTemplateVariablesList();
  setTemplateVariablesInfo("");
}

async function saveTemplateVariable() {
  if (!isSuperAdmin()) return;
  const sourceTypeValue = String(document.getElementById("templateVarSourceType")?.value || "manual")
    .trim()
    .toLowerCase();
  const sourcePathInput = document.getElementById("templateVarSourcePath");
  const sourcePathValue = String(sourcePathInput?.value || "").trim();
  const keyValue = normalizeTemplateVariableKey(document.getElementById("templateVarKey")?.value || "");
  const payload = {
    var_key: keyValue,
    title: String(document.getElementById("templateVarTitle")?.value || "").trim(),
    description: String(document.getElementById("templateVarDescription")?.value || "").trim() || null,
    is_user_editable: Boolean(document.getElementById("templateVarUserEditable")?.checked),
    source_type: sourceTypeValue,
    source_path: sourcePathValue || null,
    default_value: String(document.getElementById("templateVarDefaultValue")?.value || "").trim() || null,
    is_active: Boolean(document.getElementById("templateVarIsActive")?.checked ?? true),
  };
  if (!payload.var_key) {
    setTemplateVariablesInfo("Ключ должен быть в формате %KEY% (только A-Z, 0-9, _; длина 2-50).", true);
    return;
  }
  if (!payload.title) {
    setTemplateVariablesInfo("Заполните название переменной.", true);
    return;
  }
  if (payload.source_type === "review_field" && !payload.source_path) {
    setTemplateVariablesInfo("Для источника «из отзыва» укажите поле source_path.", true);
    return;
  }
  if (payload.source_type === "system" && !payload.source_path) {
    setTemplateVariablesInfo("Для системного источника укажите source_path.", true);
    return;
  }
  const res = await fetch("/api/super-admin/template-variables", {
    method: "PUT",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setTemplateVariablesInfo(data.detail || "Не удалось сохранить переменную", true);
    return;
  }
  setTemplateVariablesInfo("Переменная сохранена.");
  resetTemplateVariableForm();
  await loadTemplateVariables();
}

async function deleteTemplateVariable(varKey) {
  if (!isSuperAdmin()) return;
  const normalizedKey = String(varKey || "").trim().toUpperCase();
  if (!normalizedKey) return;
  if (!confirm(`Удалить переменную ${normalizedKey}?`)) return;
  const res = await fetch("/api/super-admin/template-variables", {
    method: "DELETE",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ var_key: normalizedKey }),
  });
  const data = await res.json();
  if (!res.ok) {
    setTemplateVariablesInfo(data.detail || "Не удалось удалить переменную", true);
    return;
  }
  setTemplateVariablesInfo("Переменная удалена.");
  await loadTemplateVariables();
}

function renderDefaultTemplateGroups() {
  const container = document.getElementById("defaultTemplateGroupsAccordion");
  if (!container) return;
  container.innerHTML = "";
  for (const group of defaultTemplatesState.items || []) {
    const details = document.createElement("details");
    details.className = "template-group";
    details.open = false;
    const summary = document.createElement("summary");
    summary.textContent = String(group.title || "");
    details.appendChild(summary);
    const content = document.createElement("div");
    content.className = "template-subgroups-list";
    for (const subgroup of group.subgroups || []) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "template-subgroup-row";
      const nameSpan = document.createElement("span");
      nameSpan.textContent = String(subgroup.name || "");
      const countSpan = document.createElement("span");
      countSpan.className = "template-count-badge";
      countSpan.textContent = String(subgroup.count || 0);
      row.appendChild(nameSpan);
      row.appendChild(countSpan);
      row.addEventListener("click", () => {
        openDefaultTemplateSubgroup(String(group.id || ""), String(subgroup.name || ""), String(group.title || ""));
      });
      content.appendChild(row);
    }
    details.appendChild(content);
    container.appendChild(details);
  }
}

function renderDefaultTemplateEditorRows() {
  const container = document.getElementById("defaultTemplateEditorList");
  if (!container) return;
  container.innerHTML = "";
  if (!defaultTemplatesState.currentTemplates.length) {
    const empty = document.createElement("div");
    empty.className = "small";
    empty.textContent = "В этой подгруппе пока нет шаблонов.";
    container.appendChild(empty);
    return;
  }
  defaultTemplatesState.currentTemplates.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "template-editor-row";
    const textarea = document.createElement("textarea");
    textarea.className = "template-editor-input";
    textarea.value = item.text;
    textarea.placeholder = "Введите текст шаблона ответа";
    textarea.addEventListener("input", () => {
      defaultTemplatesState.currentTemplates[index].text = textarea.value;
    });
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "icon-btn danger";
    delBtn.title = "Удалить шаблон";
    delBtn.textContent = "🗑";
    delBtn.addEventListener("click", async () => {
      const itemId = defaultTemplatesState.currentTemplates[index]?.id;
      if (itemId) {
        await fetch(`/api/super-admin/default-template-subgroup/item/${itemId}`, {
          method: "DELETE",
          headers: csrfHeaders(),
        });
      }
      defaultTemplatesState.currentTemplates.splice(index, 1);
      renderDefaultTemplateEditorRows();
    });
    row.appendChild(textarea);
    row.appendChild(delBtn);
    container.appendChild(row);
  });
}

function closeDefaultTemplateEditor() {
  document.getElementById("defaultTemplateEditorView")?.classList.add("hidden");
  document.getElementById("defaultTemplateGroupsView")?.classList.remove("hidden");
  defaultTemplatesState.currentGroupId = null;
  defaultTemplatesState.currentGroupTitle = "";
  defaultTemplatesState.currentSubgroup = "";
  defaultTemplatesState.currentTemplates = [];
}

function addDefaultTemplateEditorRow() {
  defaultTemplatesState.currentTemplates.push({ id: null, text: "" });
  renderDefaultTemplateEditorRows();
}

async function loadDefaultTemplateGroups() {
  if (!isSuperAdmin()) return;
  const res = await fetch("/api/super-admin/default-template-groups");
  const data = await res.json();
  if (!res.ok) {
    setDefaultTemplatesInfo(data.detail || "Не удалось загрузить шаблоны по умолчанию", true);
    return;
  }
  defaultTemplatesState.items = data.items || [];
  renderDefaultTemplateGroups();
}

async function loadSuperAdminDefaultTemplateGroups() {
  closeDefaultTemplateEditor();
  await loadDefaultTemplateGroups();
}

async function openDefaultTemplateSubgroup(groupId, subgroup, groupTitle) {
  const query = new URLSearchParams({ group_id: groupId, subgroup });
  const res = await fetch("/api/super-admin/default-template-subgroup?" + query.toString());
  const data = await res.json();
  if (!res.ok) {
    setDefaultTemplatesInfo(data.detail || "Не удалось загрузить шаблоны подгруппы", true);
    return;
  }
  defaultTemplatesState.currentGroupId = groupId;
  defaultTemplatesState.currentGroupTitle = groupTitle;
  defaultTemplatesState.currentSubgroup = subgroup;
  defaultTemplatesState.currentTemplates = (data.items || []).map((item) => ({
    id: item.id || null,
    text: String(item.template_text || ""),
  }));
  document.getElementById("defaultTemplateGroupsView")?.classList.add("hidden");
  document.getElementById("defaultTemplateEditorView")?.classList.remove("hidden");
  const title = document.getElementById("defaultTemplateEditorTitle");
  if (title) title.textContent = `${groupTitle} / ${subgroup}`;
  setDefaultTemplatesInfo("");
  renderDefaultTemplateEditorRows();
}

async function saveDefaultTemplateSubgroup() {
  if (!defaultTemplatesState.currentGroupId || !defaultTemplatesState.currentSubgroup) return;
  const payload = {
    templates: defaultTemplatesState.currentTemplates.map((item) => String(item.text || "")),
  };
  const query = new URLSearchParams({
    group_id: defaultTemplatesState.currentGroupId,
    subgroup: defaultTemplatesState.currentSubgroup,
  });
  const res = await fetch("/api/super-admin/default-template-subgroup?" + query.toString(), {
    method: "PUT",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setDefaultTemplatesInfo(data.detail || "Не удалось сохранить шаблоны по умолчанию", true);
    return;
  }
  setDefaultTemplatesInfo("Шаблоны по умолчанию сохранены.");
  await loadDefaultTemplateGroups();
  await openDefaultTemplateSubgroup(
    defaultTemplatesState.currentGroupId,
    defaultTemplatesState.currentSubgroup,
    defaultTemplatesState.currentGroupTitle,
  );
}

function formatTariffLimits(limits) {
  const normalized = limits && typeof limits === "object" ? limits : {};
  return [
    `Отзывы/мес: ${Number(normalized.reviews_per_month || 0)}`,
    `Менеджеры: ${Number(normalized.managers || 0)}`,
    `Источники: ${Number(normalized.sources || 0)}`,
    `AI-единицы: ${Number(normalized.ai_units || 0)}`,
  ].join(" · ");
}

function renderTariffs(items) {
  const list = document.getElementById("tariffsList");
  if (!list) return;
  list.innerHTML = "";
  const normalizedItems = Array.isArray(items) ? items : [];
  if (!normalizedItems.length) {
    const row = document.createElement("div");
    row.className = "tariff-item";
    row.innerHTML = `<div class="small">Тарифы пока не добавлены</div>`;
    list.appendChild(row);
    return;
  }
  for (const item of normalizedItems) {
    const row = document.createElement("div");
    row.className = "tariff-item";
    const main = document.createElement("div");
    main.className = "tariff-item-main";
    main.innerHTML = `
      <div class="tariff-item-title">${esc(item.title)} <span class="small">(${esc(item.code)})</span></div>
      <div class="small">Цена в месяц: ${esc(item.monthly_price)} ₽</div>
      <div class="small">${esc(formatTariffLimits(item.limits || {}))}</div>
      <div class="small">Статус: ${item.is_active ? "активен" : "неактивен"}</div>
    `;
    const actions = document.createElement("div");
    actions.className = "tariff-item-actions";
    const editButton = document.createElement("button");
    editButton.className = "secondary";
    editButton.type = "button";
    editButton.textContent = "Изменить";
    editButton.addEventListener("click", () => openTariffForm("edit", item));
    const deleteButton = document.createElement("button");
    deleteButton.className = "secondary danger";
    deleteButton.type = "button";
    deleteButton.textContent = "Удалить";
    deleteButton.addEventListener("click", () => deleteTariffPlan(String(item.code || "")));
    actions.appendChild(editButton);
    actions.appendChild(deleteButton);
    row.appendChild(main);
    row.appendChild(actions);
    list.appendChild(row);
  }
}

function renderPayments(items) {
  const tbody = document.getElementById("paymentsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const item of items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(item.id)}</td>
      <td>${esc(item.owner_user_id)}</td>
      <td>${esc(item.amount)} ${esc(item.currency || "RUB")}</td>
      <td>${esc(item.status)}</td>
      <td>${esc(item.created_at || "")}</td>
    `;
    tbody.appendChild(tr);
  }
}

async function loadSuperAdminSection() {
  if (!isSuperAdmin()) return;
  const [tariffsRes, paymentsRes, variablesRes] = await Promise.all([
    fetch("/api/super-admin/tariffs"),
    fetch("/api/super-admin/payments?limit=100"),
    fetch("/api/super-admin/template-variables"),
  ]);
  const tariffsData = await tariffsRes.json();
  const paymentsData = await paymentsRes.json();
  const variablesData = await variablesRes.json();
  if (!tariffsRes.ok || !paymentsRes.ok || !variablesRes.ok) {
    setSuperAdminInfo(
      tariffsData.detail || paymentsData.detail || variablesData.detail || "Ошибка загрузки данных супер-админа",
      true,
    );
    return;
  }
  renderTariffs(tariffsData.items || []);
  renderPayments(paymentsData.items || []);
  templateVariablesState.items = variablesData.items || [];
  renderTemplateVariablesList();
  setTemplateVariablesInfo("");
  await loadDefaultTemplateGroups();
}

async function saveTariffPlan() {
  if (!isSuperAdmin()) return;
  const code = String(document.getElementById("tariffCode")?.value || "").trim().toLowerCase();
  const title = String(document.getElementById("tariffTitle")?.value || "").trim();
  const monthlyPrice = Number(document.getElementById("tariffPrice")?.value || "0");
  const limits = tariffLimitsFromFields();
  if (!code || !title) {
    setSuperAdminInfo("Заполните код и название тарифа.", true);
    return;
  }
  if (!Number.isFinite(monthlyPrice) || monthlyPrice < 0) {
    setSuperAdminInfo("Цена в месяц должна быть числом не меньше 0.", true);
    return;
  }
  const originalCode = tariffEditorState.originalCode;
  if (tariffEditorState.mode === "edit" && originalCode && originalCode !== code) {
    const deleted = await deleteTariffPlan(originalCode, false);
    if (!deleted) {
      setSuperAdminInfo("Не удалось изменить код тарифа: старый тариф не удален.", true);
      return;
    }
  }
  const payload = {
    code,
    title,
    monthly_price: monthlyPrice,
    limits,
    is_active: Boolean(document.getElementById("tariffIsActive")?.checked ?? true),
  };
  const res = await fetch("/api/super-admin/tariffs", {
    method: "PUT",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setSuperAdminInfo(data.detail || "Ошибка сохранения тарифа", true);
    return;
  }
  setSuperAdminInfo(tariffEditorState.mode === "edit" ? "Тариф изменен." : "Тариф создан.");
  closeTariffForm();
  await loadSuperAdminSection();
}

async function deleteTariffPlan(code, showMessage = true) {
  if (!isSuperAdmin()) return;
  const normalizedCode = String(code || "").trim().toLowerCase();
  if (!normalizedCode) return false;
  if (showMessage) {
    const confirmed = confirm(`Удалить тариф "${normalizedCode}"?`);
    if (!confirmed) return false;
  }
  const res = await fetch("/api/super-admin/tariffs", {
    method: "DELETE",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ code: normalizedCode }),
  });
  const data = await res.json();
  if (!res.ok) {
    if (showMessage) setSuperAdminInfo(data.detail || "Не удалось удалить тариф", true);
    return false;
  }
  if (showMessage) setSuperAdminInfo("Тариф удален.");
  await loadSuperAdminSection();
  return true;
}

function loadTariffs() {
  if (!isSuperAdmin()) return;
  openCreateTariffForm();
  document.getElementById("tariffsBlock")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function loadPayments() {
  document.getElementById("paymentsBlock")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function addPaymentRecord() {
  if (!isSuperAdmin()) return;
  const ownerUserId = Number(document.getElementById("paymentOwnerId")?.value || "0");
  const amount = Number(document.getElementById("paymentAmount")?.value || "0");
  const status = String(document.getElementById("paymentStatus")?.value || "paid").trim().toLowerCase();
  if (!ownerUserId || !amount) {
    setSuperAdminInfo("Укажите ID владельца и сумму.", true);
    return;
  }
  const res = await fetch("/api/super-admin/payments", {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      owner_user_id: ownerUserId,
      amount,
      currency: "RUB",
      status,
      details: {},
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    setSuperAdminInfo(data.detail || "Ошибка добавления оплаты", true);
    return;
  }
  setSuperAdminInfo("Платеж добавлен.");
  await loadSuperAdminSection();
}

async function loadMetrics() {
  const res = await fetch("/api/admin/metrics");
  const data = await res.json();
  if (!res.ok) return;
  document.getElementById("mTotal").textContent = String(data.total_reviews || 0);
  document.getElementById("mAvg").textContent = String(data.avg_first_response_minutes || 0);
  document.getElementById("mOverdue").textContent = String(data.overdue_manual_queue_24h || 0);
  const statuses = data.status_counts || {};
  const parts = Object.entries(statuses).map(([k, v]) => `${labelFromMap(reviewStatusLabels, k)}: ${v}`);
  document.getElementById("mStatuses").textContent = parts.join(" | ");
}

async function loadActions() {
  const page = Number(actionsState.page || 1);
  const pageSize = Number(actionsState.pageSize || 50);
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  const res = await fetch("/api/admin/actions?" + query.toString());
  const data = await res.json();
  const tbody = document.getElementById("actionsTbody");
  tbody.innerHTML = "";
  if (!res.ok) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="5">${esc(data.detail || "Не удалось загрузить ленту действий")}</td>`;
    tbody.appendChild(tr);
    return;
  }
  const items = data.items || [];
  for (const item of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(item.created_at)}</td>
      <td>${esc(item.actor)}</td>
      <td>${esc(item.review_uid || "-")}</td>
      <td>${esc(labelFromMap(actionTypeLabels, item.action_type))}</td>
      <td>${esc(formatActionDetails(item.details || {}))}</td>
    `;
    tbody.appendChild(tr);
  }
  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="5">Действий пока нет</td>`;
    tbody.appendChild(tr);
  }
  actionsState.hasMore = Boolean(data.has_more);
  const pageInfo = document.getElementById("actionsPaginationInfo");
  if (pageInfo) pageInfo.textContent = `Страница ${page}${actionsState.hasMore ? " (есть следующая)" : ""}`;
  const prevBtn = document.getElementById("actionsPrevButton");
  if (prevBtn) prevBtn.disabled = page <= 1;
  const nextBtn = document.getElementById("actionsNextButton");
  if (nextBtn) nextBtn.disabled = !actionsState.hasMore;
}

async function changeActionsPage(delta) {
  const nextPage = Math.max(1, Number(actionsState.page || 1) + Number(delta || 0));
  if (nextPage === actionsState.page) return;
  actionsState.page = nextPage;
  await loadActions();
}

async function updateActionsPageSize() {
  const value = document.getElementById("actionsPageSize")?.value || "50";
  const size = Number(value || 50);
  if (!Number.isFinite(size) || size < 10 || size > 200) return;
  actionsState.pageSize = size;
  actionsState.page = 1;
  await loadActions();
}

async function prevActionsPage() {
  await changeActionsPage(-1);
}

async function nextActionsPage() {
  await changeActionsPage(1);
}


document.addEventListener("DOMContentLoaded", () => {
  loadAdminContext().then((ok) => {
    if (!ok) return;
    loadAiSettings();
    loadUsers();
    loadMetrics();
    loadActions();
    loadSuperAdminSection();
  });
});
