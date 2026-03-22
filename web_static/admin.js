function esc(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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
  const availableRoles = ["user", "feedback_manager", "admin"];
  return availableRoles
    .map((role) => {
      const selected = role === selectedRole ? " selected" : "";
      return `<option value="${role}"${selected}>${esc(roleLabels[role] || role)}</option>`;
    })
    .join("");
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
    headers: { "Content-Type": "application/json" },
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
      </td>
      <td>
        <div class="row">
          <button onclick="setRole(${user.id}, document.getElementById('${roleSelectId}').value)">Сохранить роль</button>
          <button class="secondary" onclick="setUserPassword(${user.id}, document.getElementById('${passwordInputId}').value)">Сменить пароль</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

async function setRole(userId, role) {
  const res = await fetch(`/api/admin/users/${userId}/role`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
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
  const res = await fetch("/api/admin/actions?limit=50");
  const data = await res.json();
  const tbody = document.getElementById("actionsTbody");
  tbody.innerHTML = "";
  for (const item of data.items || []) {
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
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("useSyncStartDate")?.addEventListener("change", syncDateToggle);
  loadAiSettings();
  loadUsers();
  loadMetrics();
  loadActions();
});
