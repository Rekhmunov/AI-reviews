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
const actionsState = {
  page: 1,
  pageSize: 50,
  hasMore: false,
};

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

  const scopeBadge = document.getElementById("adminScopeBadge");
  const scopeTitle = document.getElementById("adminScopeTitle");
  const scopeText = document.getElementById("adminScopeText");
  const superAiPanel = document.getElementById("superAdminAiPanel");
  const superSaasPanel = document.getElementById("superAdminSaasPanel");
  if (isSuperAdmin()) {
    if (scopeBadge) scopeBadge.classList.remove("hidden");
    if (scopeTitle) scopeTitle.textContent = "Режим: супер-администратор платформы";
    if (scopeText) {
      scopeText.textContent =
        "Управление ИИ, тарифами, оплатами и клиентскими кабинетами. Доступ ко всем данным платформы.";
    }
    if (superAiPanel) superAiPanel.classList.remove("hidden");
    if (superSaasPanel) superSaasPanel.classList.remove("hidden");
    document.getElementById("superAdminDefaultTemplatesPanel")?.classList.remove("hidden");
  } else {
    if (scopeBadge) scopeBadge.classList.remove("hidden");
    if (scopeTitle) scopeTitle.textContent = "Режим: владелец клиентского кабинета";
    if (scopeText) {
      scopeText.textContent =
        "Управление только своей командой и рабочими метриками своего кабинета.";
    }
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
  document.getElementById("brandName").value = data.brand_name || "VarFabric";
  renderGroupProcessors(data.group_processors || {});
  document.getElementById("useSyncStartDate").checked = Boolean(data.use_sync_start_date);
  document.getElementById("syncStartDate").value = data.sync_start_date || "";
  syncDateToggle();
  const keyText = data.has_yandex_api_key
    ? "Текущий ключ доступа: " + (data.yandex_api_key_preview || "***")
    : "Ключ доступа пока не задан";
  const brandText = `Бренд для %BRAND%: ${data.brand_name || "VarFabric"}`;
  document.getElementById("aiInfo").textContent = `${keyText}. ${brandText}`;
}

function syncDateToggle() {
  const enabled = Boolean(document.getElementById("useSyncStartDate")?.checked);
  const input = document.getElementById("syncStartDate");
  if (!input) return;
  input.disabled = !enabled;
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
    brand_name: document.getElementById("brandName").value.trim() || "VarFabric",
    group_processors: groupProcessors,
    use_sync_start_date: Boolean(document.getElementById("useSyncStartDate").checked),
    sync_start_date: document.getElementById("syncStartDate").value || null,
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

async function loadUsers() {
  const res = await fetch("/api/admin/users");
  const data = await res.json();
  const tbody = document.getElementById("usersTbody");
  tbody.innerHTML = "";
  if (!res.ok) {
    setUsersInfo(data.detail || "Не удалось загрузить пользователей", true);
    return;
  }
  for (const user of data.items || []) {
    const tr = document.createElement("tr");
    const roleSelectId = `role-select-${user.id}`;
    const passwordInputId = `password-input-${user.id}`;
    const blocked = Boolean(user.is_blocked);
    const blockButtonLabel = blocked ? "Разблокировать" : "Заблокировать";
    const roleLabel = roleLabels[user.role] || user.role || "-";
    const blockedCell = blocked
      ? `<span class="small status-badge status-blocked">заблокирован</span>`
      : `<span class="small status-badge status-active">активен</span>`;
    tr.innerHTML = `
      <td>${esc(user.id)}</td>
      <td>${esc(user.email)}</td>
      <td>
        <input id="${passwordInputId}" type="password" placeholder="Новый пароль" />
      </td>
      <td>
        <select id="${roleSelectId}">
          ${buildRoleOptions(user.role)}
        </select>
        <div class="small">${esc(roleLabel)}</div>
      </td>
      <td>
        ${blockedCell}
        <div class="row">
          <button onclick="setRole(${user.id}, document.getElementById('${roleSelectId}').value)">Сохранить роль</button>
          <button class="secondary" onclick="setUserPassword(${user.id}, document.getElementById('${passwordInputId}').value)">Сменить пароль</button>
          <button class="secondary" onclick="toggleUserBlock(${user.id}, ${blocked ? "false" : "true"})">${blockButtonLabel}</button>
          <button class="secondary danger" onclick="deleteUser(${user.id})">Удалить</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }
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

function renderTariffs(items) {
  const tbody = document.getElementById("tariffsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const item of items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(item.code)}</td>
      <td>${esc(item.title)}</td>
      <td>${esc(item.monthly_price)}</td>
      <td>${esc(JSON.stringify(item.limits || {}, null, 0))}</td>
      <td>${item.is_active ? "да" : "нет"}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderTenants(items) {
  const tbody = document.getElementById("tenantsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const item of items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(item.id)}</td>
      <td>${esc(item.email)}</td>
      <td>${esc(item.plan_code || "starter")}</td>
      <td>${esc(item.members_count || 0)}</td>
      <td>${esc(item.reviews_count || 0)}</td>
      <td>${item.is_blocked ? "заблокирован" : "активен"}</td>
    `;
    tbody.appendChild(tr);
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
  const [tariffsRes, tenantsRes, paymentsRes] = await Promise.all([
    fetch("/api/super-admin/tariffs"),
    fetch("/api/super-admin/tenants"),
    fetch("/api/super-admin/payments?limit=100"),
  ]);
  const tariffsData = await tariffsRes.json();
  const tenantsData = await tenantsRes.json();
  const paymentsData = await paymentsRes.json();
  if (!tariffsRes.ok || !tenantsRes.ok || !paymentsRes.ok) {
    setSuperAdminInfo(
      tariffsData.detail || tenantsData.detail || paymentsData.detail || "Ошибка загрузки данных супер-админа",
      true,
    );
    return;
  }
  renderTariffs(tariffsData.items || []);
  renderTenants(tenantsData.items || []);
  renderPayments(paymentsData.items || []);
  await loadDefaultTemplateGroups();
}

async function saveTariffPlan() {
  if (!isSuperAdmin()) return;
  const code = String(document.getElementById("tariffCode")?.value || "").trim().toLowerCase();
  const title = String(document.getElementById("tariffTitle")?.value || "").trim();
  const monthlyPrice = Number(document.getElementById("tariffPrice")?.value || "0");
  const limitsRaw = String(document.getElementById("tariffLimits")?.value || "{}").trim() || "{}";
  let limits = {};
  try {
    limits = JSON.parse(limitsRaw);
  } catch (_err) {
    setSuperAdminInfo("Поле лимитов должно быть корректным JSON.", true);
    return;
  }
  if (!code || !title) {
    setSuperAdminInfo("Заполните код и название тарифа.", true);
    return;
  }
  const payload = {
    code,
    title,
    monthly_price: monthlyPrice,
    limits,
    is_active: true,
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
  setSuperAdminInfo("Тариф сохранен.");
  await loadSuperAdminSection();
}

async function assignTenantPlan() {
  if (!isSuperAdmin()) return;
  const ownerUserId = Number(document.getElementById("tenantOwnerId")?.value || "0");
  const planCode = String(document.getElementById("tenantPlanCode")?.value || "").trim().toLowerCase();
  const overrideRaw = String(document.getElementById("tenantPlanOverride")?.value || "{}").trim() || "{}";
  let limitsOverride = {};
  try {
    limitsOverride = JSON.parse(overrideRaw);
  } catch (_err) {
    setSuperAdminInfo("Поле override должно быть корректным JSON.", true);
    return;
  }
  if (!ownerUserId || !planCode) {
    setSuperAdminInfo("Укажите ID владельца и код тарифа.", true);
    return;
  }
  const res = await fetch("/api/super-admin/tenant-plan", {
    method: "POST",
    headers: csrfHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      owner_user_id: ownerUserId,
      plan_code: planCode,
      limits_override: limitsOverride,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    setSuperAdminInfo(data.detail || "Ошибка назначения тарифа", true);
    return;
  }
  setSuperAdminInfo("Тариф назначен пользователю.");
  await loadSuperAdminSection();
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
  document.getElementById("useSyncStartDate")?.addEventListener("change", syncDateToggle);
  loadAdminContext().then((ok) => {
    if (!ok) return;
    loadAiSettings();
    loadUsers();
    loadMetrics();
    loadActions();
    loadSuperAdminSection();
  });
});
