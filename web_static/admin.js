function esc(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

const roleLabels = {
  user: "user",
  feedback_manager: "менеджер обратной связи",
  admin: "admin",
};

function buildRoleOptions(selectedRole) {
  const availableRoles = ["user", "feedback_manager", "admin"];
  return availableRoles
    .map((role) => {
      const selected = role === selectedRole ? " selected" : "";
      return `<option value="${role}"${selected}>${esc(roleLabels[role] || role)}</option>`;
    })
    .join("");
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
  document.getElementById("aiInfo").textContent = data.has_yandex_api_key
    ? "Текущий API key: " + (data.yandex_api_key_preview || "***")
    : "API key пока не задан";
}

async function saveAiSettings() {
  const payload = {
    provider: document.getElementById("provider").value,
    yandex_api_key: document.getElementById("apiKey").value.trim() || null,
    yandex_folder_id: document.getElementById("folderId").value.trim() || null,
    yandex_model_uri: document.getElementById("modelUri").value.trim() || null,
  };
  const res = await fetch("/api/admin/ai-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("aiInfo").textContent = "Ошибка: " + (data.detail || "save failed");
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
  for (const user of data.items || []) {
    const tr = document.createElement("tr");
    const roleSelectId = `role-select-${user.id}`;
    tr.innerHTML = `
      <td>${esc(user.id)}</td>
      <td>${esc(user.email)}</td>
      <td>${esc(roleLabels[user.role] || user.role)}</td>
      <td>
        <select id="${roleSelectId}">
          ${buildRoleOptions(user.role)}
        </select>
        <button onclick="setRole(${user.id}, document.getElementById('${roleSelectId}').value)">Применить</button>
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
    alert(data.detail || "Ошибка смены роли");
    return;
  }
  await loadUsers();
}

async function loadMetrics() {
  const res = await fetch("/api/admin/metrics");
  const data = await res.json();
  if (!res.ok) return;
  document.getElementById("mTotal").textContent = String(data.total_reviews || 0);
  document.getElementById("mAvg").textContent = String(data.avg_first_response_minutes || 0);
  document.getElementById("mOverdue").textContent = String(data.overdue_manual_queue_24h || 0);
  const statuses = data.status_counts || {};
  const parts = Object.entries(statuses).map(([k, v]) => `${k}: ${v}`);
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
      <td>${esc(item.action_type)}</td>
      <td>${esc(JSON.stringify(item.details || {}))}</td>
    `;
    tbody.appendChild(tr);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadAiSettings();
  loadUsers();
  loadMetrics();
  loadActions();
});
