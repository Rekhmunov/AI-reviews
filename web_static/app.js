function esc(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

const templateStore = {};
const reviewsState = {
  page: 1,
  page_size: 30,
  pages: 1,
  bucket: "new",
  sort: "newest",
  date_from: null,
  date_to: null,
};
const templateGroupsState = {
  items: [],
  currentGroupId: null,
  currentGroupTitle: "",
  currentSubgroup: "",
  currentTemplates: [],
};
const processingRulesState = {
  items: [],
};
let syncInProgress = false;

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
  const defaults = { can_view_analytics: true, can_view_settings: true, is_admin: false };
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
    is_admin: Boolean(
      fromWindow.is_admin !== undefined
        ? fromWindow.is_admin
        : defaults.is_admin,
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

function setReviewBucket(bucket) {
  reviewsState.bucket = bucket;
  reviewsState.page = 1;
  document.getElementById("reviews-tab-new")?.classList.toggle("active", bucket === "new");
  document.getElementById("reviews-tab-processed")?.classList.toggle("active", bucket === "processed");
  loadReviews();
}

function onReviewPageSizeChange() {
  const raw = Number(document.getElementById("reviewsPageSize")?.value || 30);
  if (![10, 30, 50, 100].includes(raw)) return;
  reviewsState.page_size = raw;
  reviewsState.page = 1;
  loadReviews();
}

function changeReviewsPage(delta) {
  const next = reviewsState.page + delta;
  if (next < 1 || next > reviewsState.pages) return;
  reviewsState.page = next;
  loadReviews();
}

function dateToInputValue(dateValue) {
  const y = String(dateValue.getFullYear());
  const m = String(dateValue.getMonth() + 1).padStart(2, "0");
  const d = String(dateValue.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function inputValueToRuDate(value) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const year = value.slice(2, 4);
  const month = value.slice(5, 7);
  const day = value.slice(8, 10);
  return `${day}.${month}.${year}`;
}

function updateReviewsDateFilterButton() {
  const btn = document.getElementById("reviewsDateFilterBtn");
  if (!btn) return;
  const from = reviewsState.date_from;
  const to = reviewsState.date_to;
  if (from && to) {
    btn.textContent = `${inputValueToRuDate(from)} - ${inputValueToRuDate(to)}`;
    return;
  }
  if (from) {
    btn.textContent = `С ${inputValueToRuDate(from)}`;
    return;
  }
  if (to) {
    btn.textContent = `До ${inputValueToRuDate(to)}`;
    return;
  }
  btn.textContent = "Период: все даты";
}

function toggleReviewsDateFilterPanel(forceOpen) {
  const panel = document.getElementById("reviewsDateFilterPanel");
  if (!panel) return;
  if (forceOpen === false) {
    panel.classList.add("hidden");
    return;
  }
  const shouldOpen = forceOpen === true ? true : panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !shouldOpen);
  if (!shouldOpen) return;
  const fromInput = document.getElementById("reviewsDateFrom");
  const toInput = document.getElementById("reviewsDateTo");
  if (fromInput) fromInput.value = reviewsState.date_from || "";
  if (toInput) toInput.value = reviewsState.date_to || "";
}

function applyReviewsDateFilter() {
  const fromInput = document.getElementById("reviewsDateFrom");
  const toInput = document.getElementById("reviewsDateTo");
  const from = String(fromInput?.value || "").trim();
  const to = String(toInput?.value || "").trim();
  if (from && to && from > to) {
    alert("Дата начала не может быть позже даты окончания");
    return;
  }
  reviewsState.date_from = from || null;
  reviewsState.date_to = to || null;
  reviewsState.page = 1;
  updateReviewsDateFilterButton();
  toggleReviewsDateFilterPanel(false);
  loadReviews();
}

function clearReviewsDateFilter() {
  reviewsState.date_from = null;
  reviewsState.date_to = null;
  const fromInput = document.getElementById("reviewsDateFrom");
  const toInput = document.getElementById("reviewsDateTo");
  if (fromInput) fromInput.value = "";
  if (toInput) toInput.value = "";
  reviewsState.page = 1;
  updateReviewsDateFilterButton();
  loadReviews();
}

function setReviewsDatePreset(preset) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let fromDate = null;
  let toDate = new Date(today);

  if (preset === "today") {
    fromDate = new Date(today);
  } else if (preset === "yesterday") {
    fromDate = new Date(today);
    fromDate.setDate(fromDate.getDate() - 1);
    toDate = new Date(fromDate);
  } else if (preset === "last_week") {
    const currentDay = today.getDay();
    const diffFromMonday = (currentDay + 6) % 7;
    const currentWeekMonday = new Date(today);
    currentWeekMonday.setDate(currentWeekMonday.getDate() - diffFromMonday);
    fromDate = new Date(currentWeekMonday);
    fromDate.setDate(fromDate.getDate() - 7);
    toDate = new Date(currentWeekMonday);
    toDate.setDate(toDate.getDate() - 1);
  } else if (preset === "last_7_days") {
    fromDate = new Date(today);
    fromDate.setDate(fromDate.getDate() - 6);
  } else if (preset === "last_30_days") {
    fromDate = new Date(today);
    fromDate.setDate(fromDate.getDate() - 29);
  } else if (preset === "last_month") {
    const currentMonthFirstDay = new Date(today.getFullYear(), today.getMonth(), 1);
    fromDate = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    toDate = new Date(currentMonthFirstDay);
    toDate.setDate(0);
  } else if (preset === "last_3_months") {
    fromDate = new Date(today);
    fromDate.setMonth(fromDate.getMonth() - 3);
    fromDate.setDate(fromDate.getDate() + 1);
  } else if (preset === "last_year") {
    fromDate = new Date(today);
    fromDate.setFullYear(fromDate.getFullYear() - 1);
    fromDate.setDate(fromDate.getDate() + 1);
  } else {
    return;
  }

  const fromValue = fromDate ? dateToInputValue(fromDate) : "";
  const toValue = toDate ? dateToInputValue(toDate) : "";
  const fromInput = document.getElementById("reviewsDateFrom");
  const toInput = document.getElementById("reviewsDateTo");
  if (fromInput) fromInput.value = fromValue;
  if (toInput) toInput.value = toValue;
}

function onReviewsSortChange() {
  const sortValue = String(document.getElementById("reviewsSortFilter")?.value || "newest");
  reviewsState.sort = sortValue;
  reviewsState.page = 1;
  loadReviews();
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

async function loadProcessingRules() {
  const res = await fetch("/api/processing-rules");
  const data = await res.json();
  const info = document.getElementById("processingRulesInfo");
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось загрузить правила");
    return;
  }
  processingRulesState.items = (data.items || []).map((item) => ({
    group_id: String(item.group_id || ""),
    title: String(item.title || item.group_id || ""),
    action_mode: String(item.action_mode || "manual"),
    auto_send: Boolean(item.auto_send),
  }));
  renderProcessingRules();
}

function renderProcessingRules() {
  const container = document.getElementById("processingRulesContainer");
  if (!container) return;
  container.innerHTML = "";
  for (const item of processingRulesState.items) {
    const card = document.createElement("div");
    card.className = "processing-rule-card";
    card.innerHTML = `
      <div class="processing-rule-title">${esc(item.title)}</div>
      <select class="processing-rule-select" data-group-id="${esc(item.group_id)}" onchange="onRuleModeChange(this)">
        <option value="ai" ${item.action_mode === "ai" ? "selected" : ""}>Искусственный интеллект</option>
        <option value="template" ${item.action_mode === "template" ? "selected" : ""}>Ответ по шаблону</option>
        <option value="manual" ${item.action_mode === "manual" ? "selected" : ""}>Ручной ответ</option>
        <option value="ignore" ${item.action_mode === "ignore" ? "selected" : ""}>Игнорировать</option>
      </select>
      <div class="row processing-rule-toggle-row">
        <span>Автоотправка</span>
        <label class="switch">
          <input type="checkbox" data-group-id="${esc(item.group_id)}" ${item.auto_send ? "checked" : ""} onchange="onRuleAutoSendChange(this)" />
          <span class="slider"></span>
        </label>
      </div>
    `;
    container.appendChild(card);
  }
}

function onRuleModeChange(selectElement) {
  const groupId = selectElement.getAttribute("data-group-id") || "";
  const mode = String(selectElement.value || "manual");
  const item = processingRulesState.items.find((rule) => rule.group_id === groupId);
  if (!item) return;
  item.action_mode = mode;
}

function onRuleAutoSendChange(inputElement) {
  const groupId = inputElement.getAttribute("data-group-id") || "";
  const item = processingRulesState.items.find((rule) => rule.group_id === groupId);
  if (!item) return;
  item.auto_send = Boolean(inputElement.checked);
}

async function applyProcessingRules() {
  const info = document.getElementById("processingRulesInfo");
  const applyBtn = document.getElementById("processingRulesApplyBtn");
  const confirmed = confirm("Вы точно хотите применить эти настройки?");
  if (!confirmed) return;
  if (applyBtn) applyBtn.disabled = true;
  if (info) info.textContent = "Применяем правила...";
  const payload = {
    rules: processingRulesState.items.map((item) => ({
      group_id: item.group_id,
      action_mode: item.action_mode,
      auto_send: Boolean(item.auto_send),
    })),
  };
  try {
    const res = await fetch("/api/processing-rules/apply", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось применить правила");
      return;
    }
    const stats = data.updated_reviews || {};
    if (info) {
      info.textContent = `Настройки применены. Обновлено отзывов: ${stats.updated || 0}, авто: ${stats.auto_sent || 0}, вручную: ${stats.queued || 0}, игнор: ${stats.ignored || 0}.`;
    }
    await loadReviews();
  } finally {
    if (applyBtn) applyBtn.disabled = false;
  }
}

function syncTemplateFormFromStore() {
  const category = document.getElementById("tplCategory")?.value;
  if (!category) return;
  const tpl = templateStore[category];
  document.getElementById("tplText").value = tpl ? (tpl.template_text || "") : "";
}

function renderRatingStars(value) {
  if (value === null || value === undefined || value === "") return "<span class='small'>без оценки</span>";
  const numeric = Math.max(0, Math.min(5, Number(value) || 0));
  const rounded = Math.round(numeric);
  const full = "★".repeat(rounded);
  const empty = "☆".repeat(Math.max(5 - rounded, 0));
  return `<span class="rating-stars" title="${rounded}/5">${full}${empty}</span>`;
}

async function syncAll() {
  if (syncInProgress) return;
  const syncButton = document.getElementById("syncAllBtn");
  const syncInfo = document.getElementById("syncInfo");
  syncInProgress = true;
  if (syncButton) {
    syncButton.disabled = true;
    syncButton.textContent = "Идет синхронизация...";
  }
  if (syncInfo) syncInfo.textContent = "Загрузка отзывов началась, пожалуйста подождите...";
  try {
    const payload = { all_accounts: true, account_id: null };
    const res = await fetch("/api/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      if (syncInfo) syncInfo.textContent = "Ошибка: " + (data.detail || "синхронизация не выполнена");
      return;
    }
    const failed = data.failed_accounts || 0;
    let text = `Кабинетов: ${data.accounts}, отзывов: ${data.loaded}, вопросов/чатов: ${data.loaded_conversations || 0}`;
    if (failed > 0) text += `, ошибок: ${failed}`;
    if (data.cancelled) text += ", синхронизация остановлена администратором";
    if (syncInfo) syncInfo.textContent = text;
    const tasks = [loadReviews(), loadConversations()];
    if (canViewSection("analytics")) tasks.push(loadAnalytics());
    await Promise.all(tasks);
  } finally {
    syncInProgress = false;
    if (syncButton) {
      syncButton.disabled = false;
      syncButton.textContent = "Синхронизировать все активные кабинеты";
    }
  }
}

async function stopSyncAll() {
  const res = await fetch("/api/admin/sync-stop", { method: "POST" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось остановить синхронизацию");
    return;
  }
  const syncInfo = document.getElementById("syncInfo");
  if (syncInfo) syncInfo.textContent = "Отправлена команда остановки. Подождите завершения текущей операции.";
}

async function clearAllReviews() {
  if (!confirm("Удалить все отзывы из текущего кабинета?")) return;
  const res = await fetch("/api/admin/reviews-clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось очистить отзывы");
    return;
  }
  const syncInfo = document.getElementById("syncInfo");
  if (syncInfo) syncInfo.textContent = `Удалено отзывов: ${data.deleted || 0}`;
  await loadReviews();
}

async function loadReviews() {
  const priority = document.getElementById("priorityFilter").value;
  const status = document.getElementById("statusFilter").value;
  const category = document.getElementById("categoryFilter").value;
  const sort = String(document.getElementById("reviewsSortFilter")?.value || reviewsState.sort || "newest");
  reviewsState.sort = sort;
  const query = new URLSearchParams();
  if (priority) query.set("priority", priority);
  if (status) query.set("status", status);
  if (category) query.set("category", category);
  if (reviewsState.date_from) query.set("date_from", reviewsState.date_from);
  if (reviewsState.date_to) query.set("date_to", reviewsState.date_to);
  query.set("sort", reviewsState.sort);
  query.set("bucket", reviewsState.bucket);
  query.set("page", String(reviewsState.page));
  query.set("page_size", String(reviewsState.page_size));

  const res = await fetch("/api/reviews?" + query.toString());
  const data = await res.json();
  const tbody = document.getElementById("reviewsTbody");
  tbody.innerHTML = "";
  if (!res.ok) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="6" class="small">Ошибка: ${esc(data.detail || "не удалось загрузить отзывы")}</td>`;
    tbody.appendChild(tr);
    return;
  }
  for (const review of data.items || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(review.source)}</td>
      <td>
        <div>${esc(review.text)}</div>
        <div class="small">автор: ${esc(review.author || "-")} | рейтинг: ${renderRatingStars(review.rating)} | категория: ${esc(labelFromMap(categoryLabels, review.category))}</div>
      </td>
      <td>
        <div class="small">автоответ: ${esc(review.auto_reply || "-")}</div>
        <div class="small">ответ оператора: ${esc(review.manual_reply || "-")}</div>
      </td>
      <td><span class="pill ${esc(review.priority)}">${esc(labelFromMap(priorityLabels, review.priority))}</span></td>
      <td>${esc(labelFromMap(reviewStatusLabels, review.status))}</td>
      <td>
        <div class="actions-col">
          <button onclick="autoReply('${esc(review.review_uid)}')">Автоответ</button>
          <button class="secondary" onclick="queueManual('${esc(review.review_uid)}')">Вручную</button>
          <button class="secondary" onclick="manualReply('${esc(review.review_uid)}')">Ответ оператора</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }

  const newCount = Number(data.new_count || 0);
  const processedCount = Number(data.processed_count || 0);
  document.getElementById("reviews-tab-new").textContent = `Новые отзывы (${newCount})`;
  document.getElementById("reviews-tab-processed").textContent = `Обработанные отзывы (${processedCount})`;

  reviewsState.page = Number(data.page || 1);
  reviewsState.pages = Number(data.pages || 1);
  reviewsState.sort = String(data.sort || reviewsState.sort || "newest");
  reviewsState.date_from = data.date_from || reviewsState.date_from || null;
  reviewsState.date_to = data.date_to || reviewsState.date_to || null;
  const sortFilter = document.getElementById("reviewsSortFilter");
  if (sortFilter) sortFilter.value = reviewsState.sort;
  updateReviewsDateFilterButton();
  document.getElementById("reviewsPageInfo").textContent = `Страница ${reviewsState.page} из ${reviewsState.pages}`;
  document.getElementById("reviewsPrevPageBtn").disabled = reviewsState.page <= 1;
  document.getElementById("reviewsNextPageBtn").disabled = reviewsState.page >= reviewsState.pages;
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
        <div class="row">
          <button class="secondary" onclick="toggleAccount(${account.id}, ${account.is_active ? "false" : "true"})">
            ${account.is_active ? "Отключить" : "Включить"}
          </button>
          <button class="icon-btn danger" title="Удалить источник" onclick="deleteAccount(${account.id})">🗑</button>
        </div>
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

async function deleteAccount(accountId) {
  if (!confirm("Удалить источник данных?")) return;
  const res = await fetch(`/api/accounts/${accountId}`, { method: "DELETE" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось удалить источник");
    return;
  }
  await loadAccounts();
}

async function loadTemplates() {
  const res = await fetch("/api/templates");
  const data = await res.json();
  for (const key of Object.keys(templateStore)) delete templateStore[key];

  const rulesBody = document.getElementById("rulesTbody");
  if (rulesBody) rulesBody.innerHTML = "";

  for (const tpl of data.items || []) {
    templateStore[tpl.category] = tpl;

    if (rulesBody) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${esc(labelFromMap(categoryLabels, tpl.category))}</td>
        <td>${esc(labelFromMap(modeLabels, tpl.mode))}</td>
        <td>
          <label class="switch">
            <input type="checkbox" ${tpl.is_enabled ? "checked" : ""} onchange="toggleRuleEnabled('${esc(tpl.category)}', this.checked)" />
            <span class="slider"></span>
          </label>
        </td>
        <td>
          <button class="icon-btn danger" title="Удалить правило" onclick="deleteRule('${esc(tpl.category)}')">🗑</button>
        </td>
      `;
      rulesBody.appendChild(row);
    }
  }
  syncRuleFormFromStore();
  await loadTemplateGroups();
}

async function toggleRuleEnabled(category, enabled) {
  const current = templateStore[category] || { mode: "manual", template_text: "" };
  const payload = {
    category: category,
    mode: current.mode || "manual",
    template_text: current.template_text || "",
    is_enabled: Boolean(enabled),
  };
  const res = await fetch("/api/templates", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось изменить состояние правила");
    await loadTemplates();
    return;
  }
  await loadTemplates();
}

async function deleteRule(category) {
  if (!confirm("Удалить правило обработки?")) return;
  const res = await fetch(`/api/templates/${encodeURIComponent(category)}`, { method: "DELETE" });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось удалить правило");
    return;
  }
  await loadTemplates();
}

async function saveRuleOnly() {
  const category = document.getElementById("ruleCategory").value;
  const mode = document.getElementById("ruleMode").value;
  const existingTemplate = templateStore[category]?.template_text || "";
  const isEnabled = Boolean(templateStore[category]?.is_enabled);

  const payload = {
    category: category,
    mode: mode,
    template_text: existingTemplate,
    is_enabled: isEnabled,
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

async function loadTemplateGroups() {
  const res = await fetch("/api/template-groups");
  const data = await res.json();
  if (!res.ok) {
    const info = document.getElementById("templatesInfo");
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось загрузить группы шаблонов");
    return;
  }
  templateGroupsState.items = data.items || [];
  renderTemplateGroups();
}

function renderTemplateGroups() {
  const container = document.getElementById("templateGroupsAccordion");
  if (!container) return;
  container.innerHTML = "";

  for (const group of templateGroupsState.items) {
    const details = document.createElement("details");
    details.className = "template-group";
    details.open = true;

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
        openTemplateSubgroup(String(group.id || ""), String(subgroup.name || ""), String(group.title || ""));
      });
      content.appendChild(row);
    }
    details.appendChild(content);
    container.appendChild(details);
  }
}

async function openTemplateSubgroup(groupId, subgroup, groupTitle) {
  const query = new URLSearchParams({ group_id: groupId, subgroup: subgroup });
  const res = await fetch("/api/template-subgroup?" + query.toString());
  const data = await res.json();
  const info = document.getElementById("templatesInfo");
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось загрузить шаблоны");
    return;
  }

  templateGroupsState.currentGroupId = groupId;
  templateGroupsState.currentGroupTitle = groupTitle;
  templateGroupsState.currentSubgroup = subgroup;
  templateGroupsState.currentTemplates = (data.items || []).map((item) => ({
    id: item.id || null,
    text: String(item.template_text || ""),
  }));

  document.getElementById("templateGroupsView")?.classList.add("hidden");
  document.getElementById("templateEditorView")?.classList.remove("hidden");
  const title = document.getElementById("templateEditorTitle");
  if (title) title.textContent = `${groupTitle} / ${subgroup}`;
  if (info) info.textContent = "";
  renderTemplateEditorRows();
}

function closeTemplateEditor() {
  document.getElementById("templateEditorView")?.classList.add("hidden");
  document.getElementById("templateGroupsView")?.classList.remove("hidden");
  templateGroupsState.currentGroupId = null;
  templateGroupsState.currentGroupTitle = "";
  templateGroupsState.currentSubgroup = "";
  templateGroupsState.currentTemplates = [];
}

function renderTemplateEditorRows() {
  const container = document.getElementById("templateEditorList");
  if (!container) return;
  container.innerHTML = "";
  if (!templateGroupsState.currentTemplates.length) {
    const empty = document.createElement("div");
    empty.className = "small";
    empty.textContent = "В этой подгруппе пока нет шаблонов.";
    container.appendChild(empty);
    return;
  }

  templateGroupsState.currentTemplates.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "template-editor-row";

    const textarea = document.createElement("textarea");
    textarea.className = "template-editor-input";
    textarea.value = item.text;
    textarea.placeholder = "Введите текст шаблона ответа";
    textarea.addEventListener("input", () => {
      templateGroupsState.currentTemplates[index].text = textarea.value;
    });

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "icon-btn danger";
    delBtn.title = "Удалить шаблон";
    delBtn.textContent = "🗑";
    delBtn.addEventListener("click", async () => {
      const itemId = templateGroupsState.currentTemplates[index]?.id;
      if (itemId) {
        await fetch(`/api/template-subgroup/item/${itemId}`, { method: "DELETE" });
      }
      templateGroupsState.currentTemplates.splice(index, 1);
      renderTemplateEditorRows();
    });

    row.appendChild(textarea);
    row.appendChild(delBtn);
    container.appendChild(row);
  });
}

function addTemplateEditorRow() {
  templateGroupsState.currentTemplates.push({ id: null, text: "" });
  renderTemplateEditorRows();
}

async function saveTemplateSubgroup() {
  if (!templateGroupsState.currentGroupId || !templateGroupsState.currentSubgroup) return;
  const payload = {
    templates: templateGroupsState.currentTemplates.map((item) => String(item.text || "")),
  };
  const query = new URLSearchParams({
    group_id: templateGroupsState.currentGroupId,
    subgroup: templateGroupsState.currentSubgroup,
  });
  const res = await fetch("/api/template-subgroup?" + query.toString(), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  const info = document.getElementById("templatesInfo");
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось сохранить шаблоны");
    return;
  }
  if (info) info.textContent = "Шаблоны сохранены.";
  await loadTemplateGroups();
  await openTemplateSubgroup(
    templateGroupsState.currentGroupId,
    templateGroupsState.currentSubgroup,
    templateGroupsState.currentGroupTitle,
  );
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
  if (permissions.is_admin) {
    document.getElementById("adminStopSyncBtn")?.classList.remove("hidden");
    document.getElementById("adminClearReviewsBtn")?.classList.remove("hidden");
  }
  document.getElementById("reviewsPageSize").value = String(reviewsState.page_size);
  const sortFilter = document.getElementById("reviewsSortFilter");
  if (sortFilter) {
    sortFilter.value = reviewsState.sort;
    sortFilter.addEventListener("change", onReviewsSortChange);
  }
  updateReviewsDateFilterButton();
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
    loadProcessingRules();
    loadTemplates();
  }
});
