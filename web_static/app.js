function esc(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function showSection(section) {
  const ids = ["reviews", "conversations", "analytics", "settings"];
  for (const id of ids) {
    const sectionEl = document.getElementById("section-" + id);
    const navEl = document.getElementById("nav-" + id);
    if (sectionEl) sectionEl.classList.add("hidden");
    if (navEl) navEl.classList.remove("active");
  }
  document.getElementById("section-" + section).classList.remove("hidden");
  document.getElementById("nav-" + section).classList.add("active");
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
    document.getElementById("syncInfo").textContent = "Ошибка: " + (data.detail || "sync failed");
    return;
  }
  const failed = data.failed_accounts || 0;
  let text = `Кабинетов: ${data.accounts}, отзывов: ${data.loaded}, вопросов/чатов: ${data.loaded_conversations || 0}`;
  if (failed > 0) text += `, ошибок: ${failed}`;
  document.getElementById("syncInfo").textContent = text;
  await Promise.all([loadReviews(), loadConversations(), loadAnalytics()]);
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
        <div class="small">author: ${esc(review.author || "-")} | rating: ${esc(review.rating ?? "-")} | category: ${esc(review.category)}</div>
      </td>
      <td>
        <div class="small">auto: ${esc(review.auto_reply || "-")}</div>
        <div class="small">manual: ${esc(review.manual_reply || "-")}</div>
      </td>
      <td><span class="pill ${esc(review.priority)}">${esc(review.priority)}</span></td>
      <td>${esc(review.status)}</td>
      <td>
        <button onclick="autoReply('${esc(review.review_uid)}')">Автоответ</button>
        <button class="secondary" onclick="queueManual('${esc(review.review_uid)}')">В ручную</button>
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
      <td>${esc(item.kind)}</td>
      <td>${esc(item.source)}</td>
      <td>${esc(item.customer_name || "-")}</td>
      <td>${esc(item.message_text || "-")}</td>
      <td>${esc(item.unread_count ?? 0)}</td>
      <td>${esc(item.status)}</td>
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
      <td>${esc(account.marketplace)}</td>
      <td>${esc(account.account_name)}</td>
      <td>${esc(account.api_url)}</td>
      <td>${esc((account.extra || {}).client_id || "-")}</td>
      <td>${esc(account.api_key_preview || "-")}</td>
      <td>${esc(account.is_active ? "yes" : "no")}</td>
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
  let integration = null;
  const integrationRaw = document.getElementById("accIntegration").value.trim();
  if (integrationRaw) {
    try {
      integration = JSON.parse(integrationRaw);
    } catch (_) {
      document.getElementById("accountsInfo").textContent = "Ошибка: integration JSON некорректный";
      return;
    }
  }
  const payload = {
    marketplace: document.getElementById("accMarketplace").value,
    account_name: document.getElementById("accName").value.trim(),
    api_url: document.getElementById("accApiUrl").value.trim(),
    client_id: document.getElementById("accClientId").value.trim() || null,
    api_key: document.getElementById("accApiKey").value.trim() || null,
    integration: integration,
  };
  const res = await fetch("/api/accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("accountsInfo").textContent = "Ошибка: " + (data.detail || "save failed");
    return;
  }
  document.getElementById("accountsInfo").textContent = "Кабинет добавлен.";
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
  const tbody = document.getElementById("templatesTbody");
  tbody.innerHTML = "";
  for (const tpl of data.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(tpl.category)}</td><td>${esc(tpl.mode)}</td><td>${esc(tpl.template_text)}</td>`;
    tbody.appendChild(tr);
  }
}

async function saveTemplate() {
  const payload = {
    category: document.getElementById("tplCategory").value,
    mode: document.getElementById("tplMode").value,
    template_text: document.getElementById("tplText").value,
  };
  const res = await fetch("/api/templates", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById("templatesInfo").textContent = "Ошибка: " + (data.detail || "save failed");
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

document.addEventListener("DOMContentLoaded", () => {
  loadReviews();
  loadConversations();
  loadAnalytics();
  loadAccounts();
  loadTemplates();
});
