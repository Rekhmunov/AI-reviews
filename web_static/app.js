function esc(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function getCsrfToken() {
  const key = "csrf_token=";
  const parts = String(document.cookie || "").split(";");
  for (const part of parts) {
    const value = part.trim();
    if (value.startsWith(key)) {
      return decodeURIComponent(value.slice(key.length));
    }
  }
  return "";
}

function jsonHeaders() {
  const headers = { "Content-Type": "application/json" };
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return headers;
}

function withCsrfHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  const csrf = getCsrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return headers;
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
  source: "all",
  status: "all",
  priority: "",
  category: "",
};
const questionsState = {
  page: 1,
  page_size: 30,
  pages: 1,
  bucket: "new",
  sort: "newest",
  date_from: null,
  date_to: null,
  source: "all",
  status: "all",
};
const chatsState = {
  bucket: "new",
  sort: "newest",
  date_from: null,
  date_to: null,
  source: "all",
  status: "all",
  items: [],
  activeConversationUid: "",
  loadingMessages: false,
};
const chatQuickTemplatesState = {
  items: [],
  loading: false,
};
const CHAT_EMOJI_PRESET = ["🙂", "😊", "😉", "😌", "😍", "😎", "🤝", "👍", "👌", "🙏", "🎉", "💙", "✨", "🔥", "🤗", "😅", "😇", "🤔", "🙌", "👀"];
const templateGroupsState = {
  items: [],
  currentGroupId: null,
  currentGroupTitle: "",
  currentSubgroup: "",
  currentTemplates: [],
};
const userTemplateVariablesState = {
  items: [],
};
const processingRulesState = {
  items: [],
};
const recommendationsState = {
  rows: [],
};
const teamState = {
  items: [],
  accounts: [],
  managerModalUserId: null,
  pendingCreate: null,
  pendingPermissions: [],
};
let syncInProgress = false;
let syncStopStatusTimer = null;
let syncCapabilityCheckInProgress = false;
const ACTIVE_SECTION_STORAGE_KEY = "feedpilot_active_section";
const ACTIVE_SETTINGS_TAB_STORAGE_KEY = "feedpilot_active_settings_tab";
const SECTION_IDS = ["reviews", "conversations", "chats", "analytics", "settings", "profile"];
const SETTINGS_TAB_IDS = ["sources", "rules", "templates", "recommendations", "team", "template-variables"];
const APP_BOOT_HIDE_CLASS = "app-boot-hidden";
const MOBILE_NAV_BREAKPOINT_PX = 900;

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
  waiting_send: "Ждет отправки",
  processed_outside_spix: "Обработан вне Спикс",
  rejected: "Отклонен",
  answered: "Отвечен",
  waiting_processing: "Ждет обработки",
  generating_answer: "Генерация ответа",
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
const roleLabels = {
  user: "пользователь",
  feedback_manager: "менеджер обратной связи",
  admin: "администратор",
};

function labelFromMap(map, value) {
  const key = String(value || "");
  return map[key] || key || "-";
}

function smartMaskSecret(value) {
  const clean = String(value || "");
  if (!clean) return "";
  if (clean.length <= 4) return "*".repeat(clean.length);
  const start = clean.slice(0, 2);
  const endLength = clean.length > 8 ? 3 : 1;
  const end = clean.slice(-endLength);
  const stars = "*".repeat(Math.max(clean.length - start.length - end.length, 1));
  return `${start}${stars}${end}`;
}

async function copyAccountApiKey(rawKey) {
  const clean = String(rawKey || "").trim();
  if (!clean) return false;
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(clean);
      return true;
    }
  } catch (_error) {
    // Fallback below for hardened browser environments.
  }
  const textarea = document.createElement("textarea");
  textarea.value = clean;
  textarea.setAttribute("readonly", "readonly");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let copied = false;
  try {
    copied = Boolean(document.execCommand("copy"));
  } catch (_error) {
    copied = false;
  }
  document.body.removeChild(textarea);
  return copied;
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

function isTenantOwner() {
  const fromWindow = window.APP_PERMISSIONS || {};
  return Boolean(fromWindow.is_tenant_owner || fromWindow.is_super_admin);
}

function canViewSection(section) {
  const permissions = getPermissions();
  if (section === "analytics") return permissions.can_view_analytics;
  if (section === "settings") return permissions.can_view_settings;
  return true;
}

function readStoredUiState(key) {
  try {
    return String(window.localStorage.getItem(key) || "");
  } catch (_error) {
    return "";
  }
}

function writeStoredUiState(key, value) {
  try {
    window.localStorage.setItem(key, String(value || ""));
  } catch (_error) {
    // noop: localStorage may be unavailable in hardened browser modes.
  }
}

function showSection(section, options = {}) {
  if (!canViewSection(section)) return;
  const persist = options.persist !== false;
  toggleChatEmojiPicker(false);
  closeChatQuickTemplatesModal();
  for (const id of SECTION_IDS) {
    const sectionEl = document.getElementById("section-" + id);
    const navEl = document.getElementById("nav-" + id);
    if (sectionEl) sectionEl.classList.add("hidden");
    if (navEl) navEl.classList.remove("active");
  }
  const targetSection = document.getElementById("section-" + section);
  const targetNav = document.getElementById("nav-" + section);
  if (targetSection) targetSection.classList.remove("hidden");
  if (targetNav) targetNav.classList.add("active");
  updateMobileCurrentSectionLabel(section);
  closeMobileNavMenu();
  if (persist) writeStoredUiState(ACTIVE_SECTION_STORAGE_KEY, section);
  if (section === "profile") {
    loadProfile();
  }
}

function showSettingsTab(tab, options = {}) {
  const persist = options.persist !== false;
  for (const name of SETTINGS_TAB_IDS) {
    const tabBtn = document.getElementById("settings-tab-" + name);
    const pane = document.getElementById("settings-pane-" + name);
    if (tabBtn) tabBtn.classList.remove("active");
    if (pane) pane.classList.add("hidden");
  }
  if (!SETTINGS_TAB_IDS.includes(tab)) tab = "sources";
  document.getElementById("settings-tab-" + tab)?.classList.add("active");
  document.getElementById("settings-pane-" + tab)?.classList.remove("hidden");
  updateMobileSettingsTabSelect(tab);
  if (persist) writeStoredUiState(ACTIVE_SETTINGS_TAB_STORAGE_KEY, tab);
  if (tab === "recommendations") {
    loadRecommendations();
  }
  if (tab === "team") {
    loadTeam();
  }
  if (tab === "template-variables") {
    loadUserTemplateVariables();
  }
}

function isMobileViewport() {
  return window.matchMedia(`(max-width: ${MOBILE_NAV_BREAKPOINT_PX}px)`).matches;
}

function sectionLabel(section) {
  const labels = {
    reviews: "Отзывы",
    conversations: "Вопросы",
    chats: "Чаты",
    analytics: "Аналитика",
    settings: "Настройки",
    profile: "Мой профиль",
  };
  return labels[String(section || "")] || "Раздел";
}

function updateMobileCurrentSectionLabel(section) {
  const title = document.getElementById("mobileCurrentSectionTitle");
  if (!title) return;
  title.textContent = sectionLabel(section);
}

function openMobileNavMenu() {
  const menu = document.getElementById("mobileNavMenu");
  const overlay = document.getElementById("mobileNavOverlay");
  const button = document.getElementById("mobileNavToggleBtn");
  if (!menu || !overlay || !button) return;
  menu.classList.add("open");
  overlay.classList.add("open");
  button.setAttribute("aria-expanded", "true");
}

function closeMobileNavMenu() {
  const menu = document.getElementById("mobileNavMenu");
  const overlay = document.getElementById("mobileNavOverlay");
  const button = document.getElementById("mobileNavToggleBtn");
  if (!menu || !overlay || !button) return;
  menu.classList.remove("open");
  overlay.classList.remove("open");
  button.setAttribute("aria-expanded", "false");
}

function toggleMobileNavMenu() {
  const menu = document.getElementById("mobileNavMenu");
  if (!menu) return;
  if (menu.classList.contains("open")) {
    closeMobileNavMenu();
    return;
  }
  openMobileNavMenu();
}

function updateMobileSettingsTabSelect(tab) {
  const select = document.getElementById("mobileSettingsTabSelect");
  if (!select) return;
  if (!SETTINGS_TAB_IDS.includes(tab)) return;
  select.value = tab;
}

function onMobileSettingsTabChange(value) {
  const tab = String(value || "").trim();
  if (!SETTINGS_TAB_IDS.includes(tab)) return;
  showSettingsTab(tab);
}

function setupMobileSettingsTabSelect() {
  const select = document.getElementById("mobileSettingsTabSelect");
  const teamOption = document.getElementById("mobile-settings-option-team");
  if (!select) return;
  const showTeam = isTenantOwner();
  if (teamOption) {
    teamOption.hidden = !showTeam;
    teamOption.disabled = !showTeam;
  }
  const activeButton = document.querySelector("#section-settings .settings-tab-btn.active");
  const activeId = String(activeButton?.id || "").replace("settings-tab-", "");
  const initial = SETTINGS_TAB_IDS.includes(activeId) ? activeId : "sources";
  updateMobileSettingsTabSelect(initial);
}

function closeMobileNavIfDesktop() {
  if (isMobileViewport()) return;
  closeMobileNavMenu();
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

function setQuestionBucket(bucket) {
  questionsState.bucket = bucket;
  questionsState.page = 1;
  document.getElementById("questions-tab-new")?.classList.toggle("active", bucket === "new");
  document.getElementById("questions-tab-processed")?.classList.toggle("active", bucket === "processed");
  loadQuestions();
}

function onQuestionsPageSizeChange() {
  const raw = Number(document.getElementById("questionsPageSize")?.value || 30);
  if (![10, 30, 50, 100].includes(raw)) return;
  questionsState.page_size = raw;
  questionsState.page = 1;
  loadQuestions();
}

function changeQuestionsPage(delta) {
  const next = questionsState.page + delta;
  if (next < 1 || next > questionsState.pages) return;
  questionsState.page = next;
  loadQuestions();
}

function setChatBucket(bucket) {
  chatsState.bucket = bucket;
  document.getElementById("chats-tab-new")?.classList.toggle("active", bucket === "new");
  document.getElementById("chats-tab-processed")?.classList.toggle("active", bucket === "processed");
  loadChats();
}

function dateToInputValue(dateValue) {
  const y = String(dateValue.getFullYear());
  const m = String(dateValue.getMonth() + 1).padStart(2, "0");
  const d = String(dateValue.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function setDefaultReviewsDateRange(force) {
  if (!force && reviewsState.date_from && reviewsState.date_to) return;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const monthAgo = new Date(today);
  monthAgo.setMonth(monthAgo.getMonth() - 1);
  reviewsState.date_from = dateToInputValue(monthAgo);
  reviewsState.date_to = dateToInputValue(today);
  const fromInput = document.getElementById("reviewsDateFrom");
  const toInput = document.getElementById("reviewsDateTo");
  if (fromInput) fromInput.value = reviewsState.date_from;
  if (toInput) toInput.value = reviewsState.date_to;
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

function setSourceFilterOptions(options) {
  const select = document.getElementById("sourceFilter");
  if (!select) return;
  const current = String(reviewsState.source || "all");
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "all";
  defaultOption.textContent = "Источник отзывов: Выбрать все";
  select.appendChild(defaultOption);
  for (const item of options || []) {
    const value = String(item || "").trim();
    if (!value) continue;
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = `Источник: ${value.toUpperCase()}`;
    select.appendChild(opt);
  }
  select.value = current;
  if (!Array.from(select.options).some((item) => item.value === current)) {
    select.value = "all";
    reviewsState.source = "all";
  }
}

function setQuestionSourceFilterOptions(options) {
  const select = document.getElementById("questionPanelSourceFilter");
  if (!select) return;
  const current = String(questionsState.source || "all");
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "all";
  defaultOption.textContent = "Источник: все";
  select.appendChild(defaultOption);
  for (const item of options || []) {
    const value = String(item || "").trim();
    if (!value) continue;
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = `Источник: ${value.toUpperCase()}`;
    select.appendChild(opt);
  }
  select.value = current;
  if (!Array.from(select.options).some((item) => item.value === current)) {
    select.value = "all";
    questionsState.source = "all";
  }
}

function setChatSourceFilterOptions(options) {
  const select = document.getElementById("chatPanelSourceFilter");
  if (!select) return;
  const current = String(chatsState.source || "all");
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "all";
  defaultOption.textContent = "Источник: все";
  select.appendChild(defaultOption);
  for (const item of options || []) {
    const value = String(item || "").trim();
    if (!value) continue;
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = `Источник: ${value.toUpperCase()}`;
    select.appendChild(opt);
  }
  select.value = current;
  if (!Array.from(select.options).some((item) => item.value === current)) {
    select.value = "all";
    chatsState.source = "all";
  }
}

function toggleReviewsFiltersPanel(forceOpen) {
  const panel = document.getElementById("reviewsFiltersPanel");
  if (!panel) return;
  if (forceOpen === false) {
    panel.classList.add("hidden");
    return;
  }
  const shouldOpen = forceOpen === true ? true : panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !shouldOpen);
  if (!shouldOpen) return;
  toggleReviewsDateFilterPanel(false);
  const sourceSelect = document.getElementById("sourceFilter");
  const statusSelect = document.getElementById("statusFilter");
  const prioritySelect = document.getElementById("priorityFilter");
  const categorySelect = document.getElementById("categoryFilter");
  if (sourceSelect) sourceSelect.value = reviewsState.source || "all";
  if (statusSelect) statusSelect.value = reviewsState.status || "all";
  if (prioritySelect) prioritySelect.value = reviewsState.priority || "";
  if (categorySelect) categorySelect.value = reviewsState.category || "";
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
  toggleReviewsFiltersPanel(false);
  const fromInput = document.getElementById("reviewsDateFrom");
  const toInput = document.getElementById("reviewsDateTo");
  if (fromInput) fromInput.value = reviewsState.date_from || "";
  if (toInput) toInput.value = reviewsState.date_to || "";
}

function applyReviewsFilters() {
  const sourceSelect = document.getElementById("sourceFilter");
  const statusSelect = document.getElementById("statusFilter");
  const prioritySelect = document.getElementById("priorityFilter");
  const categorySelect = document.getElementById("categoryFilter");
  reviewsState.source = String(sourceSelect?.value || "all");
  reviewsState.status = String(statusSelect?.value || "all");
  reviewsState.priority = String(prioritySelect?.value || "");
  reviewsState.category = String(categorySelect?.value || "");
  reviewsState.page = 1;
  toggleReviewsFiltersPanel(false);
  loadReviews();
}

function resetReviewsFilters() {
  reviewsState.source = "all";
  reviewsState.status = "all";
  reviewsState.priority = "";
  reviewsState.category = "";
  const sourceSelect = document.getElementById("sourceFilter");
  const statusSelect = document.getElementById("statusFilter");
  const prioritySelect = document.getElementById("priorityFilter");
  const categorySelect = document.getElementById("categoryFilter");
  if (sourceSelect) sourceSelect.value = "all";
  if (statusSelect) statusSelect.value = "all";
  if (prioritySelect) prioritySelect.value = "";
  if (categorySelect) categorySelect.value = "";
  reviewsState.page = 1;
  loadReviews();
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

function onReviewsDateInputChange() {
  const panel = document.getElementById("reviewsDateFilterPanel");
  if (!panel || panel.classList.contains("hidden")) return;
  applyReviewsDateFilter();
}

function clearReviewsDateFilter() {
  setDefaultReviewsDateRange(true);
  const fromInput = document.getElementById("reviewsDateFrom");
  const toInput = document.getElementById("reviewsDateTo");
  if (fromInput) fromInput.value = reviewsState.date_from || "";
  if (toInput) toInput.value = reviewsState.date_to || "";
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

function setDefaultQuestionsDateRange(force) {
  if (!force && questionsState.date_from && questionsState.date_to) return;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const monthAgo = new Date(today);
  monthAgo.setMonth(monthAgo.getMonth() - 1);
  questionsState.date_from = dateToInputValue(monthAgo);
  questionsState.date_to = dateToInputValue(today);
  const fromInput = document.getElementById("questionsDateFrom");
  const toInput = document.getElementById("questionsDateTo");
  if (fromInput) fromInput.value = questionsState.date_from;
  if (toInput) toInput.value = questionsState.date_to;
}

function updateQuestionsDateFilterButton() {
  const btn = document.getElementById("questionsDateFilterBtn");
  if (!btn) return;
  const from = questionsState.date_from;
  const to = questionsState.date_to;
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

function toggleQuestionsDateFilterPanel(forceOpen) {
  const panel = document.getElementById("questionsDateFilterPanel");
  if (!panel) return;
  if (forceOpen === false) {
    panel.classList.add("hidden");
    return;
  }
  const shouldOpen = forceOpen === true ? true : panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !shouldOpen);
  if (!shouldOpen) return;
  toggleQuestionsFiltersPanel(false);
  const fromInput = document.getElementById("questionsDateFrom");
  const toInput = document.getElementById("questionsDateTo");
  if (fromInput) fromInput.value = questionsState.date_from || "";
  if (toInput) toInput.value = questionsState.date_to || "";
}

function applyQuestionsDateFilter() {
  const fromInput = document.getElementById("questionsDateFrom");
  const toInput = document.getElementById("questionsDateTo");
  const from = String(fromInput?.value || "").trim();
  const to = String(toInput?.value || "").trim();
  if (from && to && from > to) {
    alert("Дата начала не может быть позже даты окончания");
    return;
  }
  questionsState.date_from = from || null;
  questionsState.date_to = to || null;
  questionsState.page = 1;
  updateQuestionsDateFilterButton();
  toggleQuestionsDateFilterPanel(false);
  loadQuestions();
}

function onQuestionsDateInputChange() {
  const panel = document.getElementById("questionsDateFilterPanel");
  if (!panel || panel.classList.contains("hidden")) return;
  applyQuestionsDateFilter();
}

function clearQuestionsDateFilter() {
  setDefaultQuestionsDateRange(true);
  const fromInput = document.getElementById("questionsDateFrom");
  const toInput = document.getElementById("questionsDateTo");
  if (fromInput) fromInput.value = questionsState.date_from || "";
  if (toInput) toInput.value = questionsState.date_to || "";
  questionsState.page = 1;
  updateQuestionsDateFilterButton();
  loadQuestions();
}

function setQuestionsDatePreset(preset) {
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
  const fromInput = document.getElementById("questionsDateFrom");
  const toInput = document.getElementById("questionsDateTo");
  if (fromInput) fromInput.value = fromValue;
  if (toInput) toInput.value = toValue;
}

function onQuestionsSortChange() {
  const sortValue = String(document.getElementById("questionSortFilter")?.value || "newest");
  questionsState.sort = sortValue;
  questionsState.page = 1;
  loadQuestions();
}

function setDefaultChatsDateRange(force) {
  if (!force && chatsState.date_from && chatsState.date_to) return;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const monthAgo = new Date(today);
  monthAgo.setMonth(monthAgo.getMonth() - 1);
  chatsState.date_from = dateToInputValue(monthAgo);
  chatsState.date_to = dateToInputValue(today);
  const fromInput = document.getElementById("chatsDateFrom");
  const toInput = document.getElementById("chatsDateTo");
  if (fromInput) fromInput.value = chatsState.date_from;
  if (toInput) toInput.value = chatsState.date_to;
}

function updateChatsDateFilterButton() {
  const btn = document.getElementById("chatsDateFilterBtn");
  if (!btn) return;
  const from = chatsState.date_from;
  const to = chatsState.date_to;
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

function toggleChatsDateFilterPanel(forceOpen) {
  const panel = document.getElementById("chatsDateFilterPanel");
  if (!panel) return;
  if (forceOpen === false) {
    panel.classList.add("hidden");
    return;
  }
  const shouldOpen = forceOpen === true ? true : panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !shouldOpen);
  if (!shouldOpen) return;
  toggleChatsFiltersPanel(false);
  const fromInput = document.getElementById("chatsDateFrom");
  const toInput = document.getElementById("chatsDateTo");
  if (fromInput) fromInput.value = chatsState.date_from || "";
  if (toInput) toInput.value = chatsState.date_to || "";
}

function applyChatsDateFilter() {
  const fromInput = document.getElementById("chatsDateFrom");
  const toInput = document.getElementById("chatsDateTo");
  const from = String(fromInput?.value || "").trim();
  const to = String(toInput?.value || "").trim();
  if (from && to && from > to) {
    alert("Дата начала не может быть позже даты окончания");
    return;
  }
  chatsState.date_from = from || null;
  chatsState.date_to = to || null;
  chatsState.activeConversationUid = "";
  updateChatsDateFilterButton();
  toggleChatsDateFilterPanel(false);
  loadChats();
}

function onChatsDateInputChange() {
  const panel = document.getElementById("chatsDateFilterPanel");
  if (!panel || panel.classList.contains("hidden")) return;
  applyChatsDateFilter();
}

function clearChatsDateFilter() {
  setDefaultChatsDateRange(true);
  const fromInput = document.getElementById("chatsDateFrom");
  const toInput = document.getElementById("chatsDateTo");
  if (fromInput) fromInput.value = chatsState.date_from || "";
  if (toInput) toInput.value = chatsState.date_to || "";
  chatsState.activeConversationUid = "";
  updateChatsDateFilterButton();
  loadChats();
}

function setChatsDatePreset(preset) {
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
  const fromInput = document.getElementById("chatsDateFrom");
  const toInput = document.getElementById("chatsDateTo");
  if (fromInput) fromInput.value = fromValue;
  if (toInput) toInput.value = toValue;
}

function onChatsSortChange() {
  const sortValue = String(document.getElementById("chatsSortFilter")?.value || "newest");
  chatsState.sort = sortValue;
  loadChats();
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
  processingRulesState.items = (data.items || []).map((item) => {
    const rawMode = String(item.action_mode || "manual");
    const normalizedMode = rawMode === "template" ? "template" : "manual";
    return {
    group_id: String(item.group_id || ""),
    title: String(item.title || item.group_id || ""),
    action_mode: normalizedMode,
    auto_send: Boolean(item.auto_send),
    };
  });
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
        <option value="template" ${item.action_mode === "template" ? "selected" : ""}>Ответ по шаблону</option>
        <option value="manual" ${item.action_mode === "manual" ? "selected" : ""}>Ручной ответ</option>
      </select>
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
      auto_send: item.action_mode === "template",
    })),
  };
  try {
    const res = await fetch("/api/processing-rules/apply", {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось применить правила");
      return;
    }
    const stats = data.updated_reviews || {};
    if (info) {
      info.textContent = `Настройки применены. Обновлено отзывов: ${stats.updated || 0}, авто: ${stats.auto_sent || 0}, вручную: ${stats.queued || 0}.`;
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
  if (syncInProgress || syncCapabilityCheckInProgress) return;
  syncCapabilityCheckInProgress = true;
  const syncInfo = document.getElementById("syncInfo");
  try {
    if (syncInfo) syncInfo.textContent = "Проверяем доступные каналы по подключенным кабинетам...";
    const capabilitiesRes = await fetch("/api/sync/capabilities");
    const capabilitiesData = await capabilitiesRes.json();
    if (!capabilitiesRes.ok) {
      if (syncInfo) syncInfo.textContent = "Ошибка: " + (capabilitiesData.detail || "не удалось проверить доступы каналов");
      return;
    }
    const capabilityItems = Array.isArray(capabilitiesData.items) ? capabilitiesData.items : [];
    if (!capabilityItems.length) {
      if (syncInfo) syncInfo.textContent = "Нет активных кабинетов для синхронизации.";
      return;
    }
    const summaryLines = capabilityItems.map((item) => {
      const accountName = String(item.account_name || `Кабинет #${item.account_id || "-"}`).trim();
      const summary = String(item.summary || "").trim();
      return `• ${accountName}: ${summary}`;
    });
    const confirmMessage =
      "Проверка доступов по каналам:\n\n" +
      summaryLines.join("\n") +
      "\n\nПродолжить синхронизацию доступных каналов?";
    if (!window.confirm(confirmMessage)) {
      if (syncInfo) syncInfo.textContent = "Синхронизация отменена пользователем.";
      return;
    }
  } catch (_error) {
    if (syncInfo) syncInfo.textContent = "Не удалось проверить доступные каналы перед синхронизацией.";
    return;
  } finally {
    syncCapabilityCheckInProgress = false;
  }

  if (syncInProgress) return;
  const syncButton = document.getElementById("syncAllBtn");
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
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      if (syncInfo) syncInfo.textContent = "Ошибка: " + (data.detail || "синхронизация не выполнена");
      return;
    }
    const failed = data.failed_accounts || 0;
    let text = `Кабинетов: ${data.accounts}, отзывов: ${data.loaded_reviews ?? data.loaded ?? 0}, вопросов: ${data.loaded_questions || 0}, чатов: ${data.loaded_chats || 0}`;
    if (failed > 0) {
      text += `, ошибок: ${failed}`;
      const firstError = Array.isArray(data.errors) && data.errors.length ? data.errors[0] : null;
      const reason = firstError && firstError.error ? String(firstError.error) : "";
      if (reason) text += `. Причина: ${reason}`;
    }
    if (Array.isArray(data.account_channel_stats) && data.account_channel_stats.length) {
      const perAccountLines = data.account_channel_stats.map((item) => {
        const reviewsOk = Boolean(item?.reviews?.ok);
        const questionsOk = Boolean(item?.questions?.ok);
        const chatsOk = Boolean(item?.chats?.ok);
        const accountId = item?.account_id ?? "-";
        return `#${accountId} [Отзывы ${reviewsOk ? "✅" : "❌"}, Вопросы ${questionsOk ? "✅" : "❌"}, Чаты ${chatsOk ? "✅" : "❌"}]`;
      });
      text += `. ${perAccountLines.join("; ")}`;
    }
    if (data.cancelled) text += ", синхронизация остановлена администратором";
    if (syncInfo) syncInfo.textContent = text;
    const tasks = [loadReviews(), loadQuestions(), loadChats()];
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

function stopSyncStatusPolling() {
  if (syncStopStatusTimer !== null) {
    window.clearTimeout(syncStopStatusTimer);
    syncStopStatusTimer = null;
  }
}

function scheduleSyncStatusPolling() {
  stopSyncStatusPolling();
  syncStopStatusTimer = window.setTimeout(() => {
    pollSyncStatusUntilStopped();
  }, 1200);
}

async function pollSyncStatusUntilStopped() {
  const syncInfo = document.getElementById("syncInfo");
  const stopButton = document.getElementById("adminStopSyncBtn");
  try {
    const res = await fetch("/api/admin/sync-status");
    const data = await res.json();
    if (!res.ok) {
      if (syncInfo) syncInfo.textContent = data.detail || "Не удалось получить статус синхронизации";
      if (stopButton) stopButton.disabled = false;
      stopSyncStatusPolling();
      return;
    }
    const inProgress = Boolean(data.in_progress);
    const cancelRequested = Boolean(data.cancel_requested);
    if (cancelRequested && inProgress) {
      if (syncInfo) syncInfo.textContent = "Остановка синхронизации выполняется... Подождите.";
      scheduleSyncStatusPolling();
      return;
    }
    if (cancelRequested && !inProgress) {
      if (syncInfo) syncInfo.textContent = "Синхронизация остановлена.";
      if (stopButton) stopButton.disabled = false;
      syncInProgress = false;
      const syncButton = document.getElementById("syncAllBtn");
      if (syncButton) {
        syncButton.disabled = false;
        syncButton.textContent = "Синхронизировать все активные кабинеты";
      }
      const tasks = [loadReviews(), loadQuestions(), loadChats()];
      if (canViewSection("analytics")) tasks.push(loadAnalytics());
      await Promise.all(tasks);
      stopSyncStatusPolling();
      return;
    }
    if (!inProgress) {
      if (syncInfo) syncInfo.textContent = "Синхронизация не запущена.";
      if (stopButton) stopButton.disabled = false;
      stopSyncStatusPolling();
      return;
    }
    if (syncInfo) syncInfo.textContent = "Синхронизация выполняется. Ожидаем остановку...";
    scheduleSyncStatusPolling();
  } catch (_error) {
    if (syncInfo) syncInfo.textContent = "Не удалось проверить статус синхронизации";
    if (stopButton) stopButton.disabled = false;
    stopSyncStatusPolling();
  }
}

async function stopSyncAll() {
  const stopButton = document.getElementById("adminStopSyncBtn");
  if (stopButton) stopButton.disabled = true;
  const res = await fetch("/api/admin/sync-stop", {
    method: "POST",
    headers: withCsrfHeaders(),
  });
  const data = await res.json();
  if (!res.ok) {
    if (stopButton) stopButton.disabled = false;
    alert(data.detail || "Не удалось остановить синхронизацию");
    return;
  }
  const syncInfo = document.getElementById("syncInfo");
  const wasRunning = Boolean(data.was_running);
  if (!wasRunning) {
    if (syncInfo) syncInfo.textContent = "Синхронизация не была запущена.";
    if (stopButton) stopButton.disabled = false;
    stopSyncStatusPolling();
    return;
  }
  if (syncInfo) syncInfo.textContent = "Отправлена команда остановки. Проверяем статус...";
  scheduleSyncStatusPolling();
}

async function clearAllReviews() {
  if (!confirm("Удалить все отзывы из текущего кабинета?")) return;
  const res = await fetch("/api/admin/reviews-clear", {
    method: "POST",
    headers: jsonHeaders(),
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
  const priority = String(document.getElementById("priorityFilter")?.value || reviewsState.priority || "");
  const status = String(document.getElementById("statusFilter")?.value || reviewsState.status || "all");
  const category = String(document.getElementById("categoryFilter")?.value || reviewsState.category || "");
  const source = String(document.getElementById("sourceFilter")?.value || reviewsState.source || "all");
  reviewsState.priority = priority;
  reviewsState.status = status;
  reviewsState.category = category;
  reviewsState.source = source;
  const sort = String(document.getElementById("reviewsSortFilter")?.value || reviewsState.sort || "newest");
  reviewsState.sort = sort;
  const query = new URLSearchParams();
  if (source && source !== "all") query.set("source", source);
  if (priority) query.set("priority", priority);
  if (status && status !== "all") query.set("status", status);
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
    const sendErrorMessage = String(review.send_error_message || "").trim();
    const hasSendError = review.status === "queued_for_operator" && Boolean(sendErrorMessage);
    if (hasSendError) tr.classList.add("review-row-send-error");
    const sendErrorIcon = hasSendError
      ? `<span class="send-error-indicator" title="${esc(sendErrorMessage)}">❗</span>`
      : "";
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
          ${sendErrorIcon}
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
  reviewsState.source = String(data.source || reviewsState.source || "all");
  reviewsState.status = String(data.status || reviewsState.status || "all");
  reviewsState.date_from = data.date_from || reviewsState.date_from || null;
  reviewsState.date_to = data.date_to || reviewsState.date_to || null;
  setSourceFilterOptions(data.source_options || []);
  const sortFilter = document.getElementById("reviewsSortFilter");
  if (sortFilter) sortFilter.value = reviewsState.sort;
  const sourceFilter = document.getElementById("sourceFilter");
  if (sourceFilter) sourceFilter.value = reviewsState.source;
  const statusFilter = document.getElementById("statusFilter");
  if (statusFilter) statusFilter.value = reviewsState.status || "all";
  const priorityFilter = document.getElementById("priorityFilter");
  if (priorityFilter) priorityFilter.value = reviewsState.priority || "";
  const categoryFilter = document.getElementById("categoryFilter");
  if (categoryFilter) categoryFilter.value = reviewsState.category || "";
  updateReviewsDateFilterButton();
  document.getElementById("reviewsPageInfo").textContent = `Страница ${reviewsState.page} из ${reviewsState.pages}`;
  document.getElementById("reviewsPrevPageBtn").disabled = reviewsState.page <= 1;
  document.getElementById("reviewsNextPageBtn").disabled = reviewsState.page >= reviewsState.pages;
}

async function sendConversationReply(conversationUid, responseText, idempotencyKey = null) {
  const payload = {
    response_text: String(responseText || "").trim(),
    idempotency_key: idempotencyKey,
  };
  const res = await fetch(`/api/conversations/${encodeURIComponent(conversationUid)}/reply`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(String(data.detail || "Не удалось отправить ответ"));
  }
  return data;
}

function conversationErrorInfo(item) {
  const errorMessage = String(item.send_error_message || "").trim();
  const sendAttempts = Number(item.send_attempts || 0);
  const lastAttemptAt = String(item.last_send_attempt_at || "").trim();
  return {
    hasError: Boolean(errorMessage),
    errorMessage,
    sendAttempts,
    lastAttemptAt,
  };
}

function buildConversationErrorTitle(meta) {
  if (!meta.hasError) return "";
  const pieces = [meta.errorMessage];
  if (meta.sendAttempts > 0) pieces.push(`попыток: ${meta.sendAttempts}`);
  if (meta.lastAttemptAt) pieces.push(`последняя: ${meta.lastAttemptAt}`);
  return pieces.join(" | ");
}

async function replyToQuestion(conversationUid) {
  const text = window.prompt("Введите ответ на вопрос:");
  if (text === null) return;
  const cleanText = String(text || "").trim();
  if (!cleanText) {
    alert("Текст ответа не может быть пустым");
    return;
  }
  try {
    await sendConversationReply(conversationUid, cleanText, `${conversationUid}:${Date.now()}`);
    await loadQuestions();
  } catch (error) {
    alert(error instanceof Error ? error.message : "Не удалось отправить ответ");
  }
}

async function loadQuestions() {
  const source = String(
    document.getElementById("questionPanelSourceFilter")?.value || questionsState.source || "all",
  );
  const status = String(
    document.getElementById("questionPanelStatusFilter")?.value || questionsState.status || "all",
  );
  questionsState.source = source;
  questionsState.status = status;
  const sort = String(document.getElementById("questionSortFilter")?.value || questionsState.sort || "newest");
  questionsState.sort = sort;

  const query = new URLSearchParams();
  query.set("kind", "question");
  if (source && source !== "all") query.set("source", source);
  if (status && status !== "all") query.set("status", status);
  if (questionsState.date_from) query.set("date_from", questionsState.date_from);
  if (questionsState.date_to) query.set("date_to", questionsState.date_to);
  query.set("bucket", questionsState.bucket || "new");
  query.set("sort", sort);
  query.set("page", String(questionsState.page || 1));
  query.set("page_size", String(questionsState.page_size || 30));

  const res = await fetch("/api/conversations?" + query.toString());
  const data = await res.json();
  const tbody = document.getElementById("questionsTbody");
  const info = document.getElementById("questionsInfo");
  if (tbody) tbody.innerHTML = "";
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось загрузить вопросы");
    return;
  }
  if (info) info.textContent = "";

  for (const item of data.items || []) {
    const tr = document.createElement("tr");
    const errorMeta = conversationErrorInfo(item);
    if (errorMeta.hasError) tr.classList.add("review-row-send-error");
    const errorIcon = errorMeta.hasError
      ? `<span class="send-error-indicator" title="${esc(buildConversationErrorTitle(errorMeta))}">❗</span>`
      : "";
    tr.innerHTML = `
      <td>${esc(item.source)}</td>
      <td>${esc(item.customer_name || "-")}</td>
      <td>${esc(item.message_text || "-")}</td>
      <td>${esc(item.unread_count ?? 0)}</td>
      <td>${esc(labelFromMap(conversationStatusLabels, item.status))}</td>
      <td>
        <div class="actions-col">
          <button onclick="replyToQuestion('${esc(item.conversation_uid)}')">Ответить</button>
          <button class="secondary" onclick="setConversationStatus('${esc(item.conversation_uid)}', 'waiting', 'question')">В ожидании</button>
          <button class="secondary" onclick="setConversationStatus('${esc(item.conversation_uid)}', 'closed', 'question')">Закрыть</button>
          ${errorIcon}
        </div>
      </td>
    `;
    tbody?.appendChild(tr);
  }

  const newCount = Number(data.new_count || 0);
  const processedCount = Number(data.processed_count || 0);
  document.getElementById("questions-tab-new").textContent = `Новые вопросы (${newCount})`;
  document.getElementById("questions-tab-processed").textContent = `Обработанные вопросы (${processedCount})`;

  questionsState.page = Number(data.page || 1);
  questionsState.pages = Number(data.pages || 1);
  questionsState.sort = String(data.sort || questionsState.sort || "newest");
  questionsState.date_from = data.date_from || questionsState.date_from || null;
  questionsState.date_to = data.date_to || questionsState.date_to || null;
  questionsState.source = String(data.source || questionsState.source || "all");
  questionsState.status = String(data.status || questionsState.status || "all");
  setQuestionSourceFilterOptions(data.source_options || []);

  const sortFilter = document.getElementById("questionSortFilter");
  if (sortFilter) sortFilter.value = questionsState.sort || "newest";
  const panelSourceFilter = document.getElementById("questionPanelSourceFilter");
  if (panelSourceFilter) panelSourceFilter.value = questionsState.source || "all";
  const panelStatusFilter = document.getElementById("questionPanelStatusFilter");
  if (panelStatusFilter) panelStatusFilter.value = questionsState.status || "all";
  updateQuestionsDateFilterButton();

  document.getElementById("questionsPageInfo").textContent = `Страница ${questionsState.page} из ${questionsState.pages}`;
  document.getElementById("questionsPrevPageBtn").disabled = questionsState.page <= 1;
  document.getElementById("questionsNextPageBtn").disabled = questionsState.page >= questionsState.pages;
}

function renderChatListGroup(containerId, items, emptyText) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!Array.isArray(items) || !items.length) {
    const empty = document.createElement("div");
    empty.className = "small";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-list-item" + (item.conversation_uid === chatsState.activeConversationUid ? " active" : "");
    const preview = String(item.message_text || "").trim();
    const unread = Number(item.unread_count || 0);
    button.innerHTML = `
      <div class="chat-list-head">
        <span>${esc(item.customer_name || item.external_conversation_id || "Диалог")}</span>
        <span class="small">${esc((item.source || "").toUpperCase())}</span>
      </div>
      <div class="small">${esc(preview || "-")}</div>
      <div class="small">Статус: ${esc(labelFromMap(conversationStatusLabels, item.status))}${unread > 0 ? ` · непрочитано: ${unread}` : ""}</div>
    `;
    button.addEventListener("click", () => {
      selectChatConversation(item.conversation_uid);
    });
    container.appendChild(button);
  }
}

function renderChatsList() {
  const all = Array.isArray(chatsState.items) ? chatsState.items : [];
  const list = Array.isArray(all) ? all : [];
  const emptyText = chatsState.bucket === "processed"
    ? "Нет обработанных чатов"
    : "Нет чатов, требующих ответа";
  renderChatListGroup("chatsList", list, emptyText);
}

function findActiveChatConversation() {
  const uid = String(chatsState.activeConversationUid || "");
  if (!uid) return null;
  return (Array.isArray(chatsState.items) ? chatsState.items : []).find((item) => item.conversation_uid === uid) || null;
}

function renderChatsThreadPlaceholder(message) {
  const thread = document.getElementById("chatMessages");
  if (!thread) return;
  thread.innerHTML = `<div class="small">${esc(message)}</div>`;
}

function setChatQuickTemplatesInfo(message, isError = false) {
  const info = document.getElementById("chatQuickTemplatesInfo");
  if (!info) return;
  info.textContent = String(message || "");
  info.style.color = isError ? "#b91c1c" : "";
}

function appendTextToChatInput(text) {
  const input = document.getElementById("chatReplyInput");
  if (!(input instanceof HTMLTextAreaElement)) return;
  const insertion = String(text || "");
  if (!insertion) return;
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
  const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : input.value.length;
  const before = input.value.slice(0, start);
  const after = input.value.slice(end);
  input.value = `${before}${insertion}${after}`;
  const nextPos = start + insertion.length;
  input.focus();
  input.setSelectionRange(nextPos, nextPos);
}

function buildChatEmojiPicker() {
  const picker = document.getElementById("chatEmojiPicker");
  if (!picker) return;
  picker.innerHTML = "";
  for (const emoji of CHAT_EMOJI_PRESET) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary chat-emoji-item";
    btn.textContent = String(emoji);
    btn.title = `Вставить ${emoji}`;
    btn.addEventListener("click", () => {
      appendTextToChatInput(`${emoji} `);
      toggleChatEmojiPicker(false);
    });
    picker.appendChild(btn);
  }
}

function toggleChatEmojiPicker(forceVisible) {
  const picker = document.getElementById("chatEmojiPicker");
  if (!picker) return;
  const nextVisible = forceVisible === undefined ? picker.classList.contains("hidden") : Boolean(forceVisible);
  picker.classList.toggle("hidden", !nextVisible);
  picker.setAttribute("aria-hidden", nextVisible ? "false" : "true");
}

function hideChatEmojiPickerIfOutside(target) {
  const picker = document.getElementById("chatEmojiPicker");
  const btn = document.getElementById("chatEmojiBtn");
  if (!picker || picker.classList.contains("hidden")) return;
  if (target && (picker.contains(target) || (btn && btn.contains(target)))) return;
  toggleChatEmojiPicker(false);
}

function renderChatQuickTemplatesList() {
  const container = document.getElementById("chatQuickTemplatesList");
  if (!container) return;
  container.innerHTML = "";
  const items = Array.isArray(chatQuickTemplatesState.items) ? chatQuickTemplatesState.items : [];
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "small";
    empty.textContent = "Шаблонов пока нет";
    container.appendChild(empty);
    return;
  }
  for (const item of items) {
    const templateId = Number(item.id || 0);
    const text = String(item.template_text || "").trim();
    if (!templateId || !text) continue;
    const row = document.createElement("div");
    row.className = "chat-quick-template-item";
    row.innerHTML = `
      <div class="chat-quick-template-text">${esc(text)}</div>
      <div class="row">
        <button type="button" class="secondary">Подставить</button>
        <button type="button" class="secondary danger">Удалить</button>
      </div>
    `;
    const [applyBtn, deleteBtn] = row.querySelectorAll("button");
    applyBtn?.addEventListener("click", () => {
      appendTextToChatInput(text);
      setChatQuickTemplatesInfo("Шаблон подставлен в поле ответа.");
      closeChatQuickTemplatesModal();
    });
    deleteBtn?.addEventListener("click", async () => {
      await deleteChatQuickTemplate(templateId);
    });
    container.appendChild(row);
  }
}

async function loadChatQuickTemplates() {
  chatQuickTemplatesState.loading = true;
  try {
    const res = await fetch("/api/chat-quick-templates");
    const data = await res.json();
    if (!res.ok) {
      setChatQuickTemplatesInfo(data.detail || "Не удалось загрузить шаблоны", true);
      return;
    }
    chatQuickTemplatesState.items = Array.isArray(data.items) ? data.items : [];
    renderChatQuickTemplatesList();
  } catch (_error) {
    setChatQuickTemplatesInfo("Не удалось загрузить шаблоны", true);
  } finally {
    chatQuickTemplatesState.loading = false;
  }
}

function openChatQuickTemplatesModal() {
  setModalVisibility("chatQuickTemplatesModal", true);
  setChatQuickTemplatesInfo("");
  toggleChatEmojiPicker(false);
  loadChatQuickTemplates();
}

function closeChatQuickTemplatesModal() {
  setModalVisibility("chatQuickTemplatesModal", false);
  const input = document.getElementById("chatQuickTemplateInput");
  if (input instanceof HTMLTextAreaElement) input.value = "";
  setChatQuickTemplatesInfo("");
}

async function createChatQuickTemplate() {
  const input = document.getElementById("chatQuickTemplateInput");
  const text = String(input?.value || "").trim();
  if (!text) {
    setChatQuickTemplatesInfo("Введите текст шаблона", true);
    return;
  }
  const res = await fetch("/api/chat-quick-templates", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ template_text: text }),
  });
  const data = await res.json();
  if (!res.ok) {
    setChatQuickTemplatesInfo(data.detail || "Не удалось добавить шаблон", true);
    return;
  }
  if (input) input.value = "";
  setChatQuickTemplatesInfo("Шаблон добавлен.");
  await loadChatQuickTemplates();
}

async function deleteChatQuickTemplate(templateId) {
  const cleanId = Number(templateId || 0);
  if (!cleanId) return;
  const res = await fetch(`/api/chat-quick-templates/${cleanId}`, {
    method: "DELETE",
    headers: withCsrfHeaders(),
  });
  const data = await res.json();
  if (!res.ok) {
    setChatQuickTemplatesInfo(data.detail || "Не удалось удалить шаблон", true);
    return;
  }
  setChatQuickTemplatesInfo("Шаблон удален.");
  await loadChatQuickTemplates();
}

function renderChatMessages(messages) {
  const thread = document.getElementById("chatMessages");
  if (!thread) return;
  thread.innerHTML = "";
  if (!Array.isArray(messages) || !messages.length) {
    renderChatsThreadPlaceholder("Сообщений пока нет");
    return;
  }
  for (const message of messages) {
    const direction = String(message.direction || "inbound").toLowerCase();
    const outbound = direction === "outbound";
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${outbound ? "outbound" : "inbound"}`;
    const status = String(message.send_status || "").toLowerCase();
    const errorHint = status === "failed" ? String(message.send_error_message || "Ошибка отправки") : "";
    if (status === "failed") bubble.classList.add("failed");
    bubble.innerHTML = `
      <div>${esc(message.message_text || "")}</div>
      <div class="small">${esc(outbound ? (message.operator_name || "Оператор") : "Покупатель")}${errorHint ? ` · ${esc(errorHint)}` : ""}</div>
    `;
    thread.appendChild(bubble);
  }
  thread.scrollTop = thread.scrollHeight;
}

async function loadChatMessages(conversationUid) {
  const uid = String(conversationUid || "").trim();
  if (!uid) {
    renderChatsThreadPlaceholder("Выберите чат слева");
    return;
  }
  const title = document.getElementById("chatThreadHeader");
  const activeConversation = findActiveChatConversation();
  if (title) {
    title.textContent = activeConversation
      ? `${activeConversation.customer_name || "Чат"} · ${String(activeConversation.source || "").toUpperCase()} · ${labelFromMap(conversationStatusLabels, activeConversation.status)}`
      : "Чат";
  }
  renderChatsThreadPlaceholder("Загрузка переписки...");
  const res = await fetch(`/api/conversations/${encodeURIComponent(uid)}/messages?limit=200`);
  const data = await res.json();
  if (!res.ok) {
    renderChatsThreadPlaceholder(String(data.detail || "Не удалось загрузить переписку"));
    return;
  }
  const merged = [];
  const sourceText = String(data.conversation?.message_text || activeConversation?.message_text || "").trim();
  if (sourceText) {
    merged.push({
      direction: "inbound",
      message_text: sourceText,
      operator_name: null,
      send_status: "sent",
    });
  }
  for (const row of data.messages || []) {
    merged.push(row);
  }
  renderChatMessages(merged);
}

function selectChatConversation(conversationUid) {
  chatsState.activeConversationUid = String(conversationUid || "");
  renderChatsList();
  loadChatMessages(chatsState.activeConversationUid);
}

async function loadChats() {
  const source = String(document.getElementById("chatPanelSourceFilter")?.value || chatsState.source || "all");
  const status = String(document.getElementById("chatPanelStatusFilter")?.value || chatsState.status || "all");
  chatsState.source = source;
  chatsState.status = status;
  const sort = String(document.getElementById("chatsSortFilter")?.value || chatsState.sort || "newest");
  chatsState.sort = sort;

  const query = new URLSearchParams();
  query.set("kind", "chat");
  if (source && source !== "all") query.set("source", source);
  if (status && status !== "all") query.set("status", status);
  if (chatsState.date_from) query.set("date_from", chatsState.date_from);
  if (chatsState.date_to) query.set("date_to", chatsState.date_to);
  query.set("bucket", chatsState.bucket || "all");
  query.set("sort", sort);
  query.set("page", "1");
  query.set("page_size", "100");

  const res = await fetch("/api/conversations?" + query.toString());
  const data = await res.json();
  const info = document.getElementById("chatsInfo");
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось загрузить чаты");
    chatsState.items = [];
    chatsState.activeConversationUid = "";
    renderChatsList();
    renderChatsThreadPlaceholder("Не удалось загрузить чаты");
    return;
  }
  if (info) info.textContent = "";

  chatsState.items = Array.isArray(data.items) ? data.items : [];
  const newCount = Number(data.new_count || 0);
  const processedCount = Number(data.processed_count || 0);
  const chatsTabNew = document.getElementById("chats-tab-new");
  if (chatsTabNew) chatsTabNew.textContent = `Нужно ответить (${newCount})`;
  const chatsTabProcessed = document.getElementById("chats-tab-processed");
  if (chatsTabProcessed) chatsTabProcessed.textContent = `Отвеченные (${processedCount})`;

  chatsState.date_from = data.date_from || chatsState.date_from || null;
  chatsState.date_to = data.date_to || chatsState.date_to || null;
  chatsState.source = String(data.source || chatsState.source || "all");
  chatsState.status = String(data.status || chatsState.status || "all");
  setChatSourceFilterOptions(data.source_options || []);

  const sortFilter = document.getElementById("chatsSortFilter");
  if (sortFilter) sortFilter.value = chatsState.sort || "newest";
  const panelSourceFilter = document.getElementById("chatPanelSourceFilter");
  if (panelSourceFilter) panelSourceFilter.value = chatsState.source || "all";
  const panelStatusFilter = document.getElementById("chatPanelStatusFilter");
  if (panelStatusFilter) panelStatusFilter.value = chatsState.status || "all";
  updateChatsDateFilterButton();

  const hasActive = chatsState.items.some((item) => item.conversation_uid === chatsState.activeConversationUid);
  if (!hasActive) {
    chatsState.activeConversationUid = chatsState.items.length ? String(chatsState.items[0].conversation_uid || "") : "";
  }
  renderChatsList();
  if (chatsState.activeConversationUid) {
    await loadChatMessages(chatsState.activeConversationUid);
  } else {
    renderChatsThreadPlaceholder("Выберите чат слева");
    const title = document.getElementById("chatThreadHeader");
    if (title) title.textContent = "Чат не выбран";
  }
}

async function sendChatReply() {
  const conversationUid = String(chatsState.activeConversationUid || "").trim();
  if (!conversationUid) {
    alert("Сначала выберите чат");
    return;
  }
  const input = document.getElementById("chatReplyInput");
  const sendBtn = document.getElementById("chatReplySendBtn");
  const info = document.getElementById("chatsInfo");
  const text = String(input?.value || "").trim();
  if (!text) return;
  if (sendBtn) sendBtn.disabled = true;
  try {
    await sendConversationReply(conversationUid, text, `${conversationUid}:${Date.now()}`);
    if (input) input.value = "";
    if (info) info.textContent = "Ответ отправлен";
    await Promise.all([loadChats(), loadQuestions()]);
  } catch (error) {
    if (info) info.textContent = error instanceof Error ? error.message : "Не удалось отправить ответ";
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}

async function setConversationStatus(conversationUid, status, scope = "question") {
  const payload = { status: status };
  const res = await fetch(`/api/conversations/${encodeURIComponent(conversationUid)}/status`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Ошибка обновления статуса");
    return;
  }
  if (scope === "chat") {
    await loadChats();
    return;
  }
  await loadQuestions();
}

function toggleQuestionsFiltersPanel(forceOpen) {
  const panel = document.getElementById("questionsFiltersPanel");
  if (!panel) return;
  if (forceOpen === false) {
    panel.classList.add("hidden");
    return;
  }
  const shouldOpen = forceOpen === true ? true : panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !shouldOpen);
  if (!shouldOpen) return;
  toggleQuestionsDateFilterPanel(false);
  const sourceSelect = document.getElementById("questionPanelSourceFilter");
  const statusSelect = document.getElementById("questionPanelStatusFilter");
  if (sourceSelect) sourceSelect.value = questionsState.source || "all";
  if (statusSelect) statusSelect.value = questionsState.status || "all";
}

function applyQuestionFiltersFromPanel() {
  const source = String(document.getElementById("questionPanelSourceFilter")?.value || "all");
  const status = String(document.getElementById("questionPanelStatusFilter")?.value || "all");
  questionsState.source = source;
  questionsState.status = status;
  questionsState.page = 1;
  toggleQuestionsFiltersPanel(false);
  loadQuestions();
}

function resetQuestionFilters() {
  questionsState.source = "all";
  questionsState.status = "all";
  const panelSource = document.getElementById("questionPanelSourceFilter");
  const panelStatus = document.getElementById("questionPanelStatusFilter");
  if (panelSource) panelSource.value = "all";
  if (panelStatus) panelStatus.value = "all";
  questionsState.page = 1;
  toggleQuestionsFiltersPanel(false);
  loadQuestions();
}

function toggleChatsFiltersPanel(forceOpen) {
  const panel = document.getElementById("chatsFiltersPanel");
  if (!panel) return;
  if (forceOpen === false) {
    panel.classList.add("hidden");
    return;
  }
  const shouldOpen = forceOpen === true ? true : panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !shouldOpen);
  if (!shouldOpen) return;
  toggleChatsDateFilterPanel(false);
  const sourceSelect = document.getElementById("chatPanelSourceFilter");
  const statusSelect = document.getElementById("chatPanelStatusFilter");
  if (sourceSelect) sourceSelect.value = chatsState.source || "all";
  if (statusSelect) statusSelect.value = chatsState.status || "all";
}

function applyChatFiltersFromPanel() {
  const source = String(document.getElementById("chatPanelSourceFilter")?.value || "all");
  const status = String(document.getElementById("chatPanelStatusFilter")?.value || "all");
  chatsState.source = source;
  chatsState.status = status;
  toggleChatsFiltersPanel(false);
  loadChats();
}

function resetChatFilters() {
  chatsState.source = "all";
  chatsState.status = "all";
  const panelSource = document.getElementById("chatPanelSourceFilter");
  const panelStatus = document.getElementById("chatPanelStatusFilter");
  if (panelSource) panelSource.value = "all";
  if (panelStatus) panelStatus.value = "all";
  toggleChatsFiltersPanel(false);
  loadChats();
}

async function clearAllConversations(scope = "all") {
  const label = scope === "questions" ? "вопросы" : scope === "chats" ? "чаты" : "вопросы и чаты";
  if (!confirm(`Удалить все ${label} из текущего кабинета?`)) return;
  const payload = {};
  if (scope === "questions") payload.kind = "question";
  if (scope === "chats") payload.kind = "chat";
  const res = await fetch("/api/admin/conversations-clear", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось очистить данные");
    return;
  }
  const questionsInfo = document.getElementById("questionsInfo");
  const chatsInfo = document.getElementById("chatsInfo");
  if (questionsInfo) questionsInfo.textContent = `Удалено: ${data.deleted || 0}`;
  if (chatsInfo) chatsInfo.textContent = `Удалено: ${data.deleted || 0}`;
  await Promise.all([loadQuestions(), loadChats()]);
}

async function clearAllQuestions() {
  await clearAllConversations("questions");
}

async function clearAllChats() {
  await clearAllConversations("chats");
}

async function reloadChats() {
  await loadChats();
}

async function markChatWaiting() {
  const uid = String(chatsState.activeConversationUid || "").trim();
  if (!uid) {
    alert("Сначала выберите чат");
    return;
  }
  await setConversationStatus(uid, "waiting", "chat");
}

async function markChatClosed() {
  const uid = String(chatsState.activeConversationUid || "").trim();
  if (!uid) {
    alert("Сначала выберите чат");
    return;
  }
  await setConversationStatus(uid, "closed", "chat");
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
  const info = document.getElementById("accountsInfo");
  tbody.innerHTML = "";
  if (!res.ok) {
    if (info) {
      info.textContent = data.detail || "Ошибка загрузки кабинетов";
    }
    return;
  }
  if (info) {
    info.textContent = data.items?.length ? `Подключено кабинетов: ${data.items.length}` : "Кабинеты пока не подключены";
  }
  for (const account of data.items || []) {
    const tr = document.createElement("tr");
    const rawApiKey = String(account.api_key || "").trim();
    const apiKeyPreview = String(account.api_key_preview || "-");
    const maskedApiKey = rawApiKey ? smartMaskSecret(rawApiKey) : apiKeyPreview;
    const apiKeyTooltip = rawApiKey || apiKeyPreview;
    tr.innerHTML = `
      <td>${esc(account.id)}</td>
      <td>${esc(labelFromMap(marketplaceLabels, account.marketplace))}</td>
      <td>${esc(account.account_name)}</td>
      <td>${esc(account.api_url)}</td>
      <td>${esc((account.extra || {}).client_id || "-")}</td>
      <td class="account-api-key-cell">
        <div class="account-api-key-wrap">
          <span class="account-api-key-text" title="${esc(apiKeyTooltip)}">${esc(maskedApiKey || "-")}</span>
          <button
            type="button"
            class="icon-btn account-key-copy-btn"
            title="Скопировать полный ключ"
            aria-label="Скопировать полный ключ"
            ${rawApiKey ? "" : "disabled"}
          >📋</button>
        </div>
      </td>
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
    const copyBtn = tr.querySelector(".account-key-copy-btn");
    if (copyBtn && rawApiKey) {
      copyBtn.addEventListener("click", async () => {
        const copied = await copyAccountApiKey(rawApiKey);
        const infoEl = document.getElementById("accountsInfo");
        if (copied) {
          copyBtn.classList.add("copied");
          copyBtn.textContent = "✓";
          copyBtn.title = "Скопировано";
          if (infoEl) infoEl.textContent = "Ключ доступа скопирован в буфер обмена.";
          window.setTimeout(() => {
            copyBtn.classList.remove("copied");
            copyBtn.textContent = "📋";
            copyBtn.title = "Скопировать полный ключ";
          }, 1200);
        } else if (infoEl) {
          infoEl.textContent = "Не удалось скопировать ключ. Попробуйте вручную через подсказку.";
        }
      });
    }
    tbody.appendChild(tr);
  }
  teamState.accounts = Array.isArray(data.items) ? data.items : [];
}

async function loadUserSyncSettings() {
  const res = await fetch("/api/user-sync-settings");
  const data = await res.json();
  const input = document.getElementById("userSyncStartDate");
  const info = document.getElementById("userSyncSettingsInfo");
  if (!input || !info) return;
  if (!res.ok) {
    info.textContent = "Ошибка загрузки даты синхронизации";
    return;
  }
  input.value = data.sync_start_date || "";
  input.disabled = false;
  info.textContent = "";
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
    headers: jsonHeaders(),
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
  const res = await fetch(`/api/accounts/${accountId}/status`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось изменить статус источника");
    return;
  }
  if (!active) {
    document.getElementById("accountsInfo").textContent = "Источник отключен. Сбор по нему остановлен.";
  } else {
    document.getElementById("accountsInfo").textContent = "Источник включен.";
  }
  await loadAccounts();
}

async function deleteAccount(accountId) {
  if (!confirm("Удалить источник данных?")) return;
  const res = await fetch(`/api/accounts/${accountId}`, {
    method: "DELETE",
    headers: withCsrfHeaders(),
  });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || "Не удалось удалить источник");
    return;
  }
  document.getElementById("accountsInfo").textContent = "Источник удален. Ключ доступа удален из базы.";
  await loadAccounts();
}

function setTeamInfo(message, isError = false) {
  const info = document.getElementById("teamInfo");
  if (!info) return;
  info.textContent = String(message || "");
  info.style.color = isError ? "#b91c1c" : "";
}

function setModalVisibility(modalId, visible) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.toggle("hidden", !visible);
  modal.style.display = visible ? "flex" : "none";
  modal.setAttribute("aria-hidden", visible ? "false" : "true");
}

function updateTeamPermissionsPreview() {
  const preview = document.getElementById("teamPermissionsPreview");
  if (!preview) return;
  const permissions = Array.isArray(teamState.pendingPermissions) ? teamState.pendingPermissions : [];
  preview.textContent = permissions.length ? formatManagerPermissionsText(permissions) : "Разрешения не выбраны";
}

function closeManagerPermissionsModal() {
  setModalVisibility("managerPermissionsModal", false);
  teamState.managerModalUserId = null;
  const info = document.getElementById("managerPermissionsInfo");
  if (info) {
    info.textContent = "";
    info.style.color = "";
  }
}

function renderManagerPermissionsRows(accounts, permissions = []) {
  const tbody = document.getElementById("managerPermissionsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const permissionsByAccount = new Map(
    (permissions || []).map((row) => [Number(row.account_id || 0), row]),
  );
  for (const account of accounts || []) {
    const accountId = Number(account.id || 0);
    if (!accountId) continue;
    const rowPerm = permissionsByAccount.get(accountId) || {};
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(account.account_name || `Кабинет #${accountId}`)}</td>
      <td><input type="checkbox" data-account-id="${accountId}" data-scope="reviews" ${rowPerm.can_reviews ? "checked" : ""} /></td>
      <td><input type="checkbox" data-account-id="${accountId}" data-scope="questions" ${rowPerm.can_questions ? "checked" : ""} /></td>
      <td><input type="checkbox" data-account-id="${accountId}" data-scope="chats" ${rowPerm.can_chats ? "checked" : ""} /></td>
    `;
    tbody.appendChild(tr);
  }
}

function collectManagerPermissionsFromModal() {
  const map = new Map();
  document.querySelectorAll("#managerPermissionsTbody input[type='checkbox']").forEach((node) => {
    const accountId = Number(node.getAttribute("data-account-id") || "0");
    const scope = String(node.getAttribute("data-scope") || "");
    if (!accountId || !scope) return;
    if (!map.has(accountId)) {
      map.set(accountId, {
        account_id: accountId,
        can_reviews: false,
        can_questions: false,
        can_chats: false,
      });
    }
    const row = map.get(accountId);
    if (!row) return;
    if (scope === "reviews") row.can_reviews = Boolean(node.checked);
    if (scope === "questions") row.can_questions = Boolean(node.checked);
    if (scope === "chats") row.can_chats = Boolean(node.checked);
  });
  return Array.from(map.values()).filter((item) => item.can_reviews || item.can_questions || item.can_chats);
}

function formatManagerPermissionsText(permissions) {
  const rows = Array.isArray(permissions) ? permissions : [];
  if (!rows.length) return "Доступы не назначены";
  const accountById = new Map((teamState.accounts || []).map((item) => [Number(item.id || 0), item]));
  return rows
    .map((perm) => {
      const accountId = Number(perm.account_id || 0);
      const account = accountById.get(accountId);
      const accountName = account ? String(account.account_name || `#${accountId}`) : `#${accountId}`;
      const scopes = [];
      if (perm.can_reviews) scopes.push("отзывы");
      if (perm.can_questions) scopes.push("вопросы");
      if (perm.can_chats) scopes.push("чаты");
      return `${accountName}: ${scopes.join(", ") || "нет"}`;
    })
    .join("; ");
}

async function loadTeam() {
  if (!isTenantOwner()) return;
  const [teamRes, accountsRes] = await Promise.all([fetch("/api/tenant/team"), fetch("/api/accounts")]);
  const teamData = await teamRes.json();
  const accountsData = await accountsRes.json();
  if (!teamRes.ok) {
    setTeamInfo("Ошибка: " + (teamData.detail || "не удалось загрузить команду"), true);
    return;
  }
  if (!accountsRes.ok) {
    setTeamInfo("Ошибка: " + (accountsData.detail || "не удалось загрузить кабинеты"), true);
    return;
  }
  teamState.items = teamData.items || [];
  teamState.accounts = accountsData.items || [];
  const tbody = document.getElementById("teamTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!teamState.items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="6">Менеджеры пока не добавлены</td>';
    tbody.appendChild(tr);
  } else {
    for (const member of teamState.items) {
      const memberId = Number(member.id || 0);
      const permsText = formatManagerPermissionsText(member.manager_permissions || []);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(member.id)}</td>
        <td>${esc(member.email || "")}</td>
        <td>${esc(member.full_name || "")}</td>
        <td>${esc(roleLabels[member.role] || member.role || "-")}</td>
        <td>${esc(permsText)}</td>
        <td>
          <div class="row">
            <button class="icon-btn danger" title="Удалить менеджера" onclick="deleteTeamMember(${memberId})">🗑</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    }
  }
  setTeamInfo(`Менеджеров в команде: ${teamState.items.length}`);
}

function openTeamManagerModal() {
  if (!isTenantOwner()) {
    setTeamInfo("Доступ к команде есть только у владельца кабинета.", true);
    return;
  }
  showSettingsTab("team");
}

function closeTeamManagerModal() {
  closeManagerPermissionsModal();
  teamState.pendingPermissions = [];
  updateTeamPermissionsPreview();
}

async function deleteTeamMember(userId) {
  if (!confirm("Удалить менеджера из команды?")) return;
  const res = await fetch(`/api/tenant/team/${userId}/delete`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ confirm: true }),
  });
  const data = await res.json();
  if (!res.ok) {
    setTeamInfo("Ошибка: " + (data.detail || "не удалось удалить менеджера"), true);
    return;
  }
  setTeamInfo("Менеджер удален");
  await loadTeam();
}

async function openManagerPermissionsModalForCreate() {
  if (!isTenantOwner()) {
    setTeamInfo("Доступ к команде есть только у владельца кабинета.", true);
    return;
  }
  const email = String(document.getElementById("teamManagerEmail")?.value || "").trim();
  const password = String(document.getElementById("teamManagerPassword")?.value || "");
  if (!email || !password) {
    setTeamInfo("Сначала заполните email и пароль менеджера.", true);
    return;
  }
  if (!Array.isArray(teamState.accounts) || !teamState.accounts.length) {
    await loadAccounts();
  }
  if (!teamState.accounts.length) {
    setTeamInfo("Сначала добавьте хотя бы один кабинет источника.", true);
    return;
  }
  teamState.managerModalUserId = null;
  const info = document.getElementById("managerPermissionsInfo");
  if (info) {
    info.textContent = "";
    info.style.color = "";
  }
  const saveBtn = document.getElementById("managerPermissionsSaveBtn");
  if (saveBtn) {
    saveBtn.textContent = "Применить разрешения";
  }
  const permissions = Array.isArray(teamState.pendingPermissions) ? teamState.pendingPermissions : [];
  renderManagerPermissionsRows(teamState.accounts, permissions);
  setModalVisibility("managerPermissionsModal", true);
}

function applyManagerPermissionsSelection() {
  const permissions = collectManagerPermissionsFromModal();
  if (!permissions.length) {
    const info = document.getElementById("managerPermissionsInfo");
    if (info) {
      info.textContent = "Нужно выбрать хотя бы один доступ";
      info.style.color = "#b91c1c";
    }
    return;
  }
  teamState.pendingPermissions = permissions;
  closeManagerPermissionsModal();
  updateTeamPermissionsPreview();
  setTeamInfo("Разрешения менеджера выбраны");
}

async function saveNewManager() {
  if (!isTenantOwner()) return;
  const email = String(document.getElementById("teamManagerEmail")?.value || "").trim();
  const password = String(document.getElementById("teamManagerPassword")?.value || "");
  const fullName = String(document.getElementById("teamManagerFullName")?.value || "").trim() || null;
  if (!email || !password) {
    setTeamInfo("Укажите email и пароль менеджера", true);
    return;
  }
  const permissions = Array.isArray(teamState.pendingPermissions) ? teamState.pendingPermissions : [];
  if (!permissions.length) {
    setTeamInfo("Сначала нажмите «Разрешения» и сохраните доступы менеджера.", true);
    return;
  }
  const payload = {
    email,
    password,
    full_name: fullName,
    role: "feedback_manager",
    permissions,
  };
  const res = await fetch("/api/tenant/team", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    setTeamInfo("Ошибка: " + (data.detail || "не удалось создать менеджера"), true);
    return;
  }
  document.getElementById("teamManagerEmail").value = "";
  document.getElementById("teamManagerPassword").value = "";
  document.getElementById("teamManagerFullName").value = "";
  teamState.pendingPermissions = [];
  updateTeamPermissionsPreview();
  setTeamInfo("Менеджер создан");
  await loadTeam();
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
    headers: jsonHeaders(),
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
  const res = await fetch(`/api/templates/${encodeURIComponent(category)}`, {
    method: "DELETE",
    headers: withCsrfHeaders(),
  });
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
    headers: jsonHeaders(),
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
    details.removeAttribute("open");
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
        await fetch(`/api/template-subgroup/item/${itemId}`, {
          method: "DELETE",
          headers: withCsrfHeaders(),
        });
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
    headers: jsonHeaders(),
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

function renderUserTemplateVariables() {
  const tbody = document.getElementById("userTemplateVariablesTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const items = Array.isArray(userTemplateVariablesState.items) ? userTemplateVariablesState.items : [];
  if (!items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="4" class="small">Нет доступных пользовательских переменных.</td>`;
    tbody.appendChild(tr);
    return;
  }
  items.forEach((item, index) => {
    const tr = document.createElement("tr");
    const varKey = String(item.var_key || "");
    const title = String(item.title || varKey);
    const description = String(item.description || "");
    const currentValue = String(item.value || item.default_value || "");
    tr.innerHTML = `
      <td>${esc(varKey)}</td>
      <td>${esc(title)}</td>
      <td>${esc(description || "-")}</td>
      <td><input type="text" data-var-index="${index}" class="template-variable-value-input" value="${esc(currentValue)}" placeholder="Введите значение" oninput="onUserTemplateVariableInput(this)" /></td>
    `;
    tbody.appendChild(tr);
  });
}

function onUserTemplateVariableInput(inputElement) {
  const index = Number(inputElement.getAttribute("data-var-index") || -1);
  if (index < 0 || index >= userTemplateVariablesState.items.length) return;
  userTemplateVariablesState.items[index].value = String(inputElement.value || "");
}

async function loadUserTemplateVariables() {
  const res = await fetch("/api/user/template-variables");
  const data = await res.json();
  const info = document.getElementById("userTemplateVariablesInfo");
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось загрузить переменные");
    return;
  }
  userTemplateVariablesState.items = data.items || [];
  renderUserTemplateVariables();
  if (info) info.textContent = "";
}

async function saveUserTemplateVariables() {
  const info = document.getElementById("userTemplateVariablesInfo");
  const values = {};
  for (const item of userTemplateVariablesState.items) {
    const key = String(item.var_key || "").trim();
    if (!key) continue;
    values[key] = String(item.value || "").trim();
  }
  const res = await fetch("/api/user/template-variables", {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify({ values }),
  });
  const data = await res.json();
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось сохранить переменные");
    return;
  }
  userTemplateVariablesState.items = data.items || userTemplateVariablesState.items;
  renderUserTemplateVariables();
  if (info) info.textContent = "Переменные сохранены.";
}

function renderRecommendationsRows() {
  const tbody = document.getElementById("recommendationsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!recommendationsState.rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="3" class="small">Список пуст. Добавьте первую строку.</td>`;
    tbody.appendChild(tr);
    return;
  }
  recommendationsState.rows.forEach((row, index) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="text" value="${esc(row.source_article || "")}" placeholder="Например, 12345678" data-index="${index}" data-field="source" oninput="onRecommendationInput(this)" /></td>
      <td><input type="text" value="${esc(row.targets_csv || "")}" placeholder="Например, 87654321, 11223344" data-index="${index}" data-field="targets" oninput="onRecommendationInput(this)" /></td>
      <td><button class="icon-btn danger" title="Удалить строку" onclick="removeRecommendationRow(${index})">🗑</button></td>
    `;
    tbody.appendChild(tr);
  });
}

function onRecommendationInput(inputElement) {
  const index = Number(inputElement.getAttribute("data-index") || -1);
  if (index < 0 || index >= recommendationsState.rows.length) return;
  const field = String(inputElement.getAttribute("data-field") || "");
  if (field === "source") {
    recommendationsState.rows[index].source_article = String(inputElement.value || "");
  } else if (field === "targets") {
    recommendationsState.rows[index].targets_csv = String(inputElement.value || "");
  }
}

function addRecommendationRow() {
  recommendationsState.rows.push({ source_article: "", targets_csv: "" });
  renderRecommendationsRows();
}

function removeRecommendationRow(index) {
  if (index < 0 || index >= recommendationsState.rows.length) return;
  recommendationsState.rows.splice(index, 1);
  renderRecommendationsRows();
}

async function loadRecommendations() {
  const res = await fetch("/api/recommendations");
  const data = await res.json();
  const info = document.getElementById("recommendationsInfo");
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось загрузить рекомендации");
    return;
  }
  recommendationsState.rows = (data.items || []).map((item) => ({
    source_article: String(item.source_article || ""),
    targets_csv: String(item.targets_csv || ""),
  }));
  renderRecommendationsRows();
  if (info) info.textContent = "";
}

async function saveRecommendations() {
  const info = document.getElementById("recommendationsInfo");
  const payload = {
    rows: recommendationsState.rows.map((row) => ({
      source_article: String(row.source_article || "").trim(),
      targets_csv: String(row.targets_csv || "").trim(),
    })),
  };
  const res = await fetch("/api/recommendations", {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось сохранить рекомендации");
    return;
  }
  if (info) info.textContent = `Сохранено связок: ${data.pairs || 0}`;
  await loadRecommendations();
}

function triggerRecommendationsImport() {
  const input = document.getElementById("recommendationsImportInput");
  if (!input) return;
  input.value = "";
  input.click();
}

async function importRecommendationsFile(inputElement) {
  const info = document.getElementById("recommendationsInfo");
  const file = inputElement?.files?.[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/recommendations/import", {
    method: "POST",
    headers: withCsrfHeaders(),
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) {
    if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось импортировать Excel");
    return;
  }
  if (info) info.textContent = `Импорт завершен. Источников: ${data.sources || 0}, связок: ${data.pairs || 0}`;
  await loadRecommendations();
}

function exportRecommendations() {
  window.location.href = "/api/recommendations/export";
}

async function queueManual(reviewId) {
  await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/queue-manual`, {
    method: "POST",
    headers: withCsrfHeaders(),
  });
  await loadReviews();
}

async function autoReply(reviewId) {
  const res = await fetch(`/api/reviews/${encodeURIComponent(reviewId)}/auto-reply`, {
    method: "POST",
    headers: withCsrfHeaders(),
  });
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
    headers: jsonHeaders(),
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
  const userSyncDateInput = document.getElementById("userSyncStartDate");
  const userSyncInfo = document.getElementById("userSyncSettingsInfo");
  if (userSyncDateInput) {
    userSyncDateInput.value = data.sync_start_date || "";
    userSyncDateInput.disabled = false;
  }
  if (userSyncInfo) {
    userSyncInfo.textContent = "";
  }
  if (!Array.isArray(data.editable_template_variables)) {
    await loadUserTemplateVariables();
  }
  if (Array.isArray(data.editable_template_variables)) {
    userTemplateVariablesState.items = data.editable_template_variables.map((item) => ({
      ...item,
      value: String(item.value || item.default_value || ""),
    }));
    renderUserTemplateVariables();
  }
  setPasswordFieldsVisible(false);
  document.getElementById("profileInfo").textContent = "";
}

async function saveUserSyncSettings() {
  const input = document.getElementById("userSyncStartDate");
  const info = document.getElementById("userSyncSettingsInfo");
  if (!input || !info) return;
  const payload = {
    use_sync_start_date: true,
    sync_start_date: input.value || null,
  };
  const res = await fetch("/api/user-sync-settings", {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    info.textContent = "Ошибка: " + (data.detail || "не удалось сохранить дату");
    return;
  }
  const settings = data.settings || {};
  input.value = settings.sync_start_date || "";
  input.disabled = false;
  info.textContent = "Сохранено";
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
    headers: jsonHeaders(),
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
  document.body.classList.add(APP_BOOT_HIDE_CLASS);
  const permissions = getPermissions();
  const teamButton = document.getElementById("settings-tab-team");
  if (teamButton) {
    const visible = isTenantOwner();
    teamButton.classList.toggle("hidden", !visible);
    teamButton.style.display = visible ? "" : "none";
  }
  if (!permissions.can_view_analytics) {
    document.getElementById("section-analytics")?.classList.add("hidden");
  }
  const savedSettingsTab = readStoredUiState(ACTIVE_SETTINGS_TAB_STORAGE_KEY);
  let initialSettingsTab = SETTINGS_TAB_IDS.includes(savedSettingsTab) ? savedSettingsTab : "sources";
  if (!permissions.can_view_settings) {
    document.getElementById("section-settings")?.classList.add("hidden");
  } else {
    showSettingsTab(initialSettingsTab, { persist: false });
  }
  setupMobileSettingsTabSelect();
  const savedSection = readStoredUiState(ACTIVE_SECTION_STORAGE_KEY);
  let initialSection = SECTION_IDS.includes(savedSection) ? savedSection : "reviews";
  if (!canViewSection(initialSection)) initialSection = "reviews";
  showSection(initialSection, { persist: false });
  if (permissions.is_admin) {
    document.getElementById("adminStopSyncBtn")?.classList.remove("hidden");
    document.getElementById("adminClearReviewsBtn")?.classList.remove("hidden");
    document.getElementById("adminClearQuestionsBtn")?.classList.remove("hidden");
    document.getElementById("adminClearChatsBtn")?.classList.remove("hidden");
  }
  document.getElementById("reviewsPageSize").value = String(reviewsState.page_size);
  document.getElementById("questionsPageSize").value = String(questionsState.page_size);
  const sortFilter = document.getElementById("reviewsSortFilter");
  if (sortFilter) {
    sortFilter.value = reviewsState.sort;
    sortFilter.addEventListener("change", onReviewsSortChange);
  }
  const questionSortFilter = document.getElementById("questionSortFilter");
  if (questionSortFilter) {
    questionSortFilter.value = questionsState.sort;
    questionSortFilter.addEventListener("change", onQuestionsSortChange);
  }
  setDefaultReviewsDateRange(false);
  setDefaultQuestionsDateRange(false);
  updateReviewsDateFilterButton();
  updateQuestionsDateFilterButton();
  updateChatsDateFilterButton();
  document.getElementById("reviewsDateFrom")?.addEventListener("change", onReviewsDateInputChange);
  document.getElementById("reviewsDateTo")?.addEventListener("change", onReviewsDateInputChange);
  document.getElementById("questionsDateFrom")?.addEventListener("change", onQuestionsDateInputChange);
  document.getElementById("questionsDateTo")?.addEventListener("change", onQuestionsDateInputChange);
  document.getElementById("chatsDateFrom")?.addEventListener("change", onChatsDateInputChange);
  document.getElementById("chatsDateTo")?.addEventListener("change", onChatsDateInputChange);
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    hideChatEmojiPickerIfOutside(target);
    const dateWrap = document.querySelector(".reviews-date-wrap");
    const datePanel = document.getElementById("reviewsDateFilterPanel");
    if (datePanel && !datePanel.classList.contains("hidden") && dateWrap && !dateWrap.contains(target)) {
      toggleReviewsDateFilterPanel(false);
    }
    const questionsDateWrap = document.getElementById("questionsDateWrap");
    const questionsDatePanel = document.getElementById("questionsDateFilterPanel");
    if (
      questionsDatePanel &&
      !questionsDatePanel.classList.contains("hidden") &&
      questionsDateWrap &&
      !questionsDateWrap.contains(target)
    ) {
      toggleQuestionsDateFilterPanel(false);
    }
    const filtersPanel = document.getElementById("reviewsFiltersPanel");
    const filtersButton = document.getElementById("reviewsFiltersBtn");
    if (
      filtersPanel &&
      !filtersPanel.classList.contains("hidden") &&
      !filtersPanel.contains(target) &&
      filtersButton &&
      !filtersButton.contains(target)
    ) {
      toggleReviewsFiltersPanel(false);
    }
    const questionsFiltersPanel = document.getElementById("questionsFiltersPanel");
    const questionsFiltersButton = document.getElementById("questionsFiltersBtn");
    if (
      questionsFiltersPanel &&
      !questionsFiltersPanel.classList.contains("hidden") &&
      !questionsFiltersPanel.contains(target) &&
      questionsFiltersButton &&
      !questionsFiltersButton.contains(target)
    ) {
      toggleQuestionsFiltersPanel(false);
    }
  });
  onSourceMarketplaceChange();
  setPasswordFieldsVisible(false);
  setModalVisibility("managerPermissionsModal", false);
  setModalVisibility("chatQuickTemplatesModal", false);
  buildChatEmojiPicker();
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeManagerPermissionsModal();
    closeChatQuickTemplatesModal();
    toggleChatEmojiPicker(false);
    closeMobileNavMenu();
  });
  window.addEventListener("resize", closeMobileNavIfDesktop);
  document.getElementById("ruleCategory")?.addEventListener("change", syncRuleFormFromStore);
  document.getElementById("tplCategory")?.addEventListener("change", syncTemplateFormFromStore);
  loadReviews();
  loadQuestions();
  loadChats();
  if (permissions.can_view_analytics) {
    loadAnalytics();
  }
  if (permissions.can_view_settings) {
    loadAccounts();
    loadProfile();
    loadProcessingRules();
    loadTemplates();
    loadUserTemplateVariables();
    loadRecommendations();
  }
  requestAnimationFrame(() => {
    document.body.classList.remove(APP_BOOT_HIDE_CLASS);
  });
});

window.showSection = showSection;
window.showSettingsTab = showSettingsTab;
window.toggleMobileNavMenu = toggleMobileNavMenu;
window.closeMobileNavMenu = closeMobileNavMenu;
window.onMobileSettingsTabChange = onMobileSettingsTabChange;
window.toggleChatEmojiPicker = toggleChatEmojiPicker;
window.openChatQuickTemplatesModal = openChatQuickTemplatesModal;
window.closeChatQuickTemplatesModal = closeChatQuickTemplatesModal;
window.createChatQuickTemplate = createChatQuickTemplate;
