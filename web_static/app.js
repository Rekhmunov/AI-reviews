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
  product_search: "",
  has_contradiction: false,
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
  accountId: "all",
  status: "all",
};
const chatsState = {
  bucket: "new",
  sort: "newest",
  date_from: null,
  date_to: null,
  source: "all",
  accountId: "all",
  status: "all",
  search: "",
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
  pendingCanSupplies: false,
};
let syncInProgress = false;
let syncStopStatusTimer = null;
let syncCapabilityCheckInProgress = false;
let globalSyncPollTimer = null;
let globalSyncProgressDots = 0;
let chatAutoRefreshTimer = null;
let uiRefreshTimer = null;
const CHAT_AUTO_REFRESH_MS = 30000; // refresh open chat messages every 30s
const UI_REFRESH_MS = 60000;        // refresh chat list from DB every 60s (after server auto-sync)
const CHANNEL_ICONS = { "Отзывы": "⭐", "Вопросы": "❓", "Чаты": "💬" };
const ACTIVE_SECTION_STORAGE_KEY = "feedpilot_active_section";
const ACTIVE_SETTINGS_TAB_STORAGE_KEY = "feedpilot_active_settings_tab";
const SECTION_IDS = ["reviews", "conversations", "chats", "analytics", "settings", "stock-settings", "stock-work", "supplies-wb", "supplies-ozon", "supplies-poa", "supplies-settings", "profile"];
const SETTINGS_TAB_IDS = ["sources", "rules", "templates", "recommendations", "products", "team", "template-variables"];
const APP_BOOT_HIDE_CLASS = "app-boot-hidden";
const MOBILE_NAV_BREAKPOINT_PX = 900;

function showSyncProgress() {
  const bar = document.getElementById("syncProgressBar");
  if (bar) bar.style.display = "block";
}

function hideSyncProgress() {
  const bar = document.getElementById("syncProgressBar");
  if (bar) bar.style.display = "none";
  const fill = document.getElementById("syncProgressFill");
  if (fill) fill.style.width = "5%";
  const text = document.getElementById("syncProgressText");
  if (text) text.textContent = "";
}

function updateSyncProgressUI(p) {
  if (!p || !p.in_progress) return;

  const fill = document.getElementById("syncProgressFill");
  const accountsText = document.getElementById("syncProgressAccountsText");
  const pctEl = document.getElementById("syncProgressPct");
  const detail = document.getElementById("syncProgressText");

  // Row 1: accounts counter
  const totalAcc = Number(p.total_accounts || 0);
  const curAcc = Number(p.current_account || 0);
  if (accountsText) {
    accountsText.textContent = totalAcc > 0 ? `Кабинет ${curAcc} из ${totalAcc}` : "";
  }

  // Row 2: detail — channel + loaded/total counter
  const account = String(p.account || "").trim();
  const channel = String(p.channel || "").trim();
  const loaded = Number(p.loaded || 0);
  // Total expected: server may expose it, or fall back to sessionStorage from preview
  const totalItems = Number(p.total_items || 0) || Number(sessionStorage.getItem("sync_total_items") || 0);
  const channelIcon = CHANNEL_ICONS[channel] || "📦";

  let detailParts = [];
  if (account) detailParts.push(account);
  if (channel) detailParts.push(`${channelIcon} ${channel}`);
  if (loaded > 0 || totalItems > 0) {
    const loadedStr = loaded.toLocaleString("ru-RU");
    const totalStr = totalItems > 0 ? `/${totalItems.toLocaleString("ru-RU")}` : "";
    detailParts.push(`${loadedStr}${totalStr}`);
  }

  if (detail) {
    const step = String(p.step || "").trim();
    detail.textContent = detailParts.length ? detailParts.join("  ·  ") : (step || "Синхронизация...");
  }

  // Progress bar + counter display
  let pct = 5;
  if (totalItems > 0 && loaded > 0) {
    // Use loaded/total for accurate progress
    pct = Math.min(Math.round((loaded / totalItems) * 100), 95);
  } else if (totalAcc > 0 && curAcc > 0) {
    // Fall back to account progress
    pct = Math.min(Math.round((curAcc / totalAcc) * 100), 95);
  }
  if (fill) fill.style.width = `${pct}%`;
  if (pctEl) pctEl.textContent = `${pct}%`;
}

async function pollGlobalSyncStatus() {
  try {
    const res = await fetch("/api/sync/status");
    if (!res.ok) {
      stopGlobalSyncPoll();
      return;
    }
    const p = await res.json();
    if (p.in_progress && p.is_manual) {
      showSyncProgress();
      updateSyncProgressUI(p);
      globalSyncPollTimer = window.setTimeout(pollGlobalSyncStatus, 2000);
    } else {
      // Sync just finished
      syncInProgress = false;
      const syncButton = document.getElementById("syncAllBtn");
      if (syncButton) {
        syncButton.disabled = false;
        syncButton.textContent = "Синхронизировать все активные кабинеты";
      }
      if (document.getElementById("syncProgressBar")?.style.display !== "none") {
        // Show completion briefly then hide
        const fill = document.getElementById("syncProgressFill");
        const det = document.getElementById("syncProgressText");
        const acc2 = document.getElementById("syncProgressAccountsText");
        const pct2 = document.getElementById("syncProgressPct");
        if (fill) fill.style.width = "100%";
        if (det) det.textContent = "✅ Готово — данные загружены";
        if (acc2) acc2.textContent = "";
        if (pct2) pct2.textContent = "100%";
        window.setTimeout(hideSyncProgress, 4000);
        // Reload data
        const tasks = [loadReviews(), loadQuestions(), loadChats()];
        if (canViewSection && canViewSection("analytics")) tasks.push(loadAnalytics());
        await Promise.all(tasks).catch(() => {});
      }
      stopGlobalSyncPoll();
    }
  } catch (_) {
    globalSyncPollTimer = window.setTimeout(pollGlobalSyncStatus, 4000);
  }
}

function startGlobalSyncPoll() {
  stopGlobalSyncPoll();
  globalSyncPollTimer = window.setTimeout(pollGlobalSyncStatus, 800);
}

function stopGlobalSyncPoll() {
  if (globalSyncPollTimer !== null) {
    window.clearTimeout(globalSyncPollTimer);
    globalSyncPollTimer = null;
  }
}

// Silent UI refresh: reload chat list from DB every 60s so new messages from
// the server auto-sync appear in the list without requiring page reload.
function startUiRefresh() {
  stopUiRefresh();
  uiRefreshTimer = window.setInterval(() => {
    if (!syncInProgress) {
      loadChats();
    }
  }, UI_REFRESH_MS);
}

function stopUiRefresh() {
  if (uiRefreshTimer !== null) {
    window.clearInterval(uiRefreshTimer);
    uiRefreshTimer = null;
  }
}

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
  // Show only first 2 chars + fixed 4 asterisks — compact, no long strings
  const start = clean.slice(0, 2);
  return `${start}****`;
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
  const defaults = { can_view_analytics: true, can_view_settings: true, can_view_supplies: false, can_view_feedback: true, is_admin: false };
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
    can_view_supplies: Boolean(
      fromWindow.can_view_supplies !== undefined
        ? fromWindow.can_view_supplies
        : defaults.can_view_supplies,
    ),
    can_view_feedback: Boolean(
      fromWindow.can_view_feedback !== undefined
        ? fromWindow.can_view_feedback
        : defaults.can_view_feedback,
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
  if (section === "supplies-wb") return permissions.can_view_supplies;
  if (section === "supplies-ozon") return permissions.can_view_supplies;
  if (section === "supplies-poa") return permissions.can_view_supplies;
  if (section === "supplies-settings") return permissions.can_view_settings || permissions.can_view_supplies;
  if (section === "reviews" || section === "conversations" || section === "chats") {
    return permissions.can_view_feedback;
  }
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

// Map section → parent nav-group id (for active state on group title)
const SECTION_TO_NAV_GROUP = {
  reviews: "feedback",
  conversations: "feedback",
  chats: "feedback",
  settings: "feedback",
  "stock-settings": "stock",
  "stock-work": "stock",
};

function toggleNavGroup(groupId) {
  const group = document.getElementById("navgroup-" + groupId);
  if (!group) return;
  const isOpen = group.classList.contains("open");
  document.querySelectorAll(".nav-group.open").forEach((g) => g.classList.remove("open"));
  if (!isOpen) group.classList.add("open");
}

// Position flyout submenus using fixed positioning so they escape
// any overflow:hidden/auto ancestor and appear above .main content.
function _positionNavFlyout(navGroup) {
  const items = navGroup.querySelector(".nav-group-items");
  if (!items || items.style.display === "none") return;
  const rect = navGroup.getBoundingClientRect();
  items.style.left = (rect.right + 4) + "px";
  items.style.top = rect.top + "px";
}

// Apply positioning on hover for all desktop nav groups
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-group").forEach(group => {
    group.addEventListener("mouseenter", () => _positionNavFlyout(group));
  });
});

// ── Nav group collapse / expand ─────────────────────────────────────────────
const NAV_GROUP_STORAGE_KEY = "feedpilot_nav_groups";

function _getNavGroupStates() {
  try { return JSON.parse(localStorage.getItem(NAV_GROUP_STORAGE_KEY) || "{}"); }
  catch (_) { return {}; }
}

function _setNavGroupState(group, collapsed) {
  const s = _getNavGroupStates();
  s[group] = collapsed;
  localStorage.setItem(NAV_GROUP_STORAGE_KEY, JSON.stringify(s));
}

function _applyNavGroup(group, collapsed, animate) {
  const wrapper = document.getElementById(`nav-group-${group}`);
  const arrow   = document.getElementById(`nav-group-${group}-arrow`);
  if (!wrapper) return;
  if (collapsed) {
    if (animate) {
      wrapper.style.maxHeight = wrapper.scrollHeight + "px";
      requestAnimationFrame(() => { wrapper.style.maxHeight = "0px"; wrapper.style.marginBottom = "0px"; });
    } else {
      wrapper.style.maxHeight = "0px";
      wrapper.style.marginBottom = "0px";
    }
    if (arrow) arrow.style.transform = "rotate(-90deg)";
  } else {
    wrapper.style.maxHeight = wrapper.scrollHeight ? wrapper.scrollHeight + "px" : "1000px";
    wrapper.style.marginBottom = "";
    if (arrow) arrow.style.transform = "rotate(0deg)";
  }
}

function toggleNavGroup(group) {
  const states = _getNavGroupStates();
  const nowCollapsed = !states[group]; // toggle
  _setNavGroupState(group, nowCollapsed);
  _applyNavGroup(group, nowCollapsed, true);
}
window.toggleNavGroup = toggleNavGroup;

function initNavGroups() {
  const states = _getNavGroupStates();
  const perms = getPermissions();

  // Feedback section: show only if user has at least one feedback-related permission
  const hasFeedback = perms.can_view_feedback || perms.can_view_settings || perms.can_view_analytics;
  const feedbackHeader = document.getElementById("nav-group-feedback-header");
  const feedbackWrapper = document.getElementById("nav-group-feedback");
  if (!hasFeedback) {
    if (feedbackHeader) feedbackHeader.style.display = "none";
    if (feedbackWrapper) { feedbackWrapper.style.maxHeight = "0px"; feedbackWrapper.style.overflow = "hidden"; }
  } else {
    const collapsed = Boolean(states["feedback"]);
    _applyNavGroup("feedback", collapsed, false);
  }

  // Supplies section: visibility controlled by existing JS (nav-section-supplies)
  const suppliesWrapper = document.getElementById("nav-group-supplies");
  if (suppliesWrapper) {
    const collapsed = Boolean(states["supplies"]);
    _applyNavGroup("supplies", collapsed, false);
  }
}
// ────────────────────────────────────────────────────────────────────────────

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
  // Refresh chat list when navigating back to chats so Dmitry's message
  // doesn't disappear due to stale background-timer data.
  if (section === "chats" && !syncInProgress) {
    // Clear search input to prevent browser autofill from filtering chats
    const _si = document.getElementById("chatsSearchInput");
    if (_si && _si.value) { _si.value = ""; chatsState.search = ""; }
    chatsState._searchUserTyped = false;
    loadChats();
  }
  if (section === "supplies-ozon") {
    if (!ozonState.items.length) loadOzonSupplies(true);
    initOzonSuppliesColumnResizer();
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
  if (tab === "products") {
    loadProducts();
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
    "supplies-wb": "Поставки — WB",
    "supplies-settings": "Поставки — Настройки",
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
  _updateChatBucketButtons();
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

function setQuestionAccountFilterOptions(accounts) {
  const select = document.getElementById("questionPanelSourceFilter");
  if (!select) return;
  const current = String(questionsState.accountId || "all");
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "all";
  defaultOption.textContent = "Источник: все";
  select.appendChild(defaultOption);
  for (const acc of accounts || []) {
    const opt = document.createElement("option");
    opt.value = String(acc.account_id);
    opt.textContent = String(acc.name || acc.source || acc.account_id);
    select.appendChild(opt);
  }
  select.value = current;
  if (!Array.from(select.options).some((o) => o.value === current)) {
    select.value = "all";
    questionsState.accountId = "all";
  }
}

function setQuestionSourceFilterOptions(options) {
  // Legacy: kept for compatibility, now superseded by setQuestionAccountFilterOptions
}

function setChatSourceFilterOptions(options) {
  // Legacy stub — superseded by setChatAccountFilterOptions
}

function setChatAccountFilterOptions(accounts) {
  const select = document.getElementById("chatPanelSourceFilter");
  if (!select) return;
  const current = String(chatsState.accountId || "all");
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "all";
  defaultOption.textContent = "Источник: все";
  select.appendChild(defaultOption);
  for (const acc of accounts || []) {
    const opt = document.createElement("option");
    opt.value = String(acc.account_id);
    opt.textContent = String(acc.name || acc.source || acc.account_id);
    select.appendChild(opt);
  }
  select.value = current;
  if (!Array.from(select.options).some((o) => o.value === current)) {
    select.value = "all";
    chatsState.accountId = "all";
  }
}

function populateCategoryFilter() {
  const categorySelect = document.getElementById("categoryFilter");
  if (!categorySelect) return;
  const current = categorySelect.value;
  categorySelect.innerHTML = '<option value="">Категория: все</option>';
  const categories = Object.keys(templateStore).sort();
  for (const cat of categories) {
    const label = labelFromMap(categoryLabels, cat) || cat;
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = label;
    categorySelect.appendChild(opt);
  }
  categorySelect.value = categories.includes(current) ? current : "";
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
  populateCategoryFilter();
  const sourceSelect = document.getElementById("sourceFilter");
  const statusSelect = document.getElementById("statusFilter");
  const prioritySelect = document.getElementById("priorityFilter");
  const categorySelect = document.getElementById("categoryFilter");
  if (sourceSelect) sourceSelect.value = reviewsState.source || "all";
  if (statusSelect) statusSelect.value = reviewsState.status || "all";
  if (prioritySelect) prioritySelect.value = reviewsState.priority || "";
  if (categorySelect) categorySelect.value = reviewsState.category || "";
  const productSearch = document.getElementById("reviewProductSearch");
  if (productSearch) productSearch.value = reviewsState.product_search || "";
  const contradictionCheck = document.getElementById("reviewContradictionFilter");
  if (contradictionCheck) contradictionCheck.checked = Boolean(reviewsState.has_contradiction);
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
  reviewsState.product_search = String(document.getElementById("reviewProductSearch")?.value || "").trim();
  reviewsState.has_contradiction = Boolean(document.getElementById("reviewContradictionFilter")?.checked);
  reviewsState.page = 1;
  toggleReviewsFiltersPanel(false);
  loadReviews();
}

function resetReviewsFilters() {
  reviewsState.source = "all";
  reviewsState.status = "all";
  reviewsState.priority = "";
  reviewsState.category = "";
  reviewsState.product_search = "";
  reviewsState.has_contradiction = false;
  const sourceSelect = document.getElementById("sourceFilter");
  const statusSelect = document.getElementById("statusFilter");
  const prioritySelect = document.getElementById("priorityFilter");
  const categorySelect = document.getElementById("categoryFilter");
  if (sourceSelect) sourceSelect.value = "all";
  if (statusSelect) statusSelect.value = "all";
  if (prioritySelect) prioritySelect.value = "";
  if (categorySelect) categorySelect.value = "";
  const ps = document.getElementById("reviewProductSearch");
  if (ps) ps.value = "";
  const cc = document.getElementById("reviewContradictionFilter");
  if (cc) cc.checked = false;
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

function toggleChatsSortDropdown() {
  const dd = document.getElementById("chatsSortDropdown");
  if (dd) dd.classList.toggle("hidden");
}

function toggleChatsSearch() {
  const row = document.getElementById("chatsSearchRow");
  const input = document.getElementById("chatsSearchInput");
  if (!row) return;
  const isHidden = row.classList.contains("hidden");
  row.classList.toggle("hidden", !isHidden);
  if (isHidden && input) {
    input.focus();
  } else if (!isHidden && input) {
    input.value = "";
    chatsState.search = "";
    renderChatsList();
  }
}

function onChatsSearchInput() {
  const input = document.getElementById("chatsSearchInput");
  const val = String(input?.value || "").trim();
  // Ignore browser-autofilled values: emails or long text (>40 chars without user intent)
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val) || (val.length > 40 && !chatsState._searchUserTyped)) {
    input.value = "";
    return;
  }
  chatsState._searchUserTyped = val.length > 0;
  chatsState.search = val;
  loadChats();
}

function selectChatsSort(value) {
  chatsState.sort = value;
  // Keep the select element in sync
  const sortSelect = document.getElementById("chatsSortSelect");
  if (sortSelect) sortSelect.value = value;
  // Update legacy active state on dropdown options (if any remain)
  const options = document.querySelectorAll(".chats-sort-option");
  options.forEach((opt) => opt.classList.toggle("active", opt.getAttribute("data-value") === value));
  const dd = document.getElementById("chatsSortDropdown");
  if (dd) dd.classList.add("hidden");
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

function _updateSyncPreviewConfirmBtn() {
  const confirmBtn = document.getElementById("syncPreviewConfirmBtn");
  if (!confirmBtn) return;
  const checks = document.querySelectorAll(".sync-preview-check");
  const anyChecked = Array.from(checks).some((cb) => cb.checked);
  confirmBtn.disabled = !anyChecked;
}

function _getSelectedSyncAccountIds() {
  const allChecks = document.querySelectorAll(".sync-preview-check");
  // If no checkboxes exist (preview failed to load), sync all accounts
  if (allChecks.length === 0) return null;
  const ids = Array.from(allChecks)
    .filter((cb) => cb.checked)
    .map((cb) => Number(cb.value))
    .filter((n) => n > 0);
  return ids.length > 0 ? ids : null;
}

function closeSyncPreviewModal() {
  setModalVisibility("syncPreviewModal", false);
  // Reset flag so user can open preview again after closing
  syncCapabilityCheckInProgress = false;
}

function openSyncPreviewModal() {
  setModalVisibility("syncPreviewModal", true);
}

async function syncAll() {
  if (syncCapabilityCheckInProgress) return;
  if (syncInProgress) return;
  syncCapabilityCheckInProgress = true;
  const syncInfo = document.getElementById("syncInfo");
  const previewContent = document.getElementById("syncPreviewContent");
  const previewSince = document.getElementById("syncPreviewSinceText");
  const previewInfo = document.getElementById("syncPreviewInfo");
  const confirmBtn = document.getElementById("syncPreviewConfirmBtn");

  try {
    if (syncInfo) syncInfo.textContent = "Проверяем количество данных для синхронизации...";

    // Show modal with loading state immediately
    if (previewContent) previewContent.innerHTML = '<div class="sync-preview-loading">⏳ Подсчёт данных...</div>';
    if (previewInfo) previewInfo.textContent = "";
    if (confirmBtn) confirmBtn.disabled = true;
    openSyncPreviewModal();

    // Load preview data (counts per channel) with 30s timeout
    let previewData = null;
    let previewOk = false;
    try {
      const previewController = new AbortController();
      const previewTimeout = window.setTimeout(() => previewController.abort(), 30000);
      const previewRes = await fetch("/api/sync/preview", { signal: previewController.signal });
      window.clearTimeout(previewTimeout);
      previewData = await previewRes.json();
      previewOk = previewRes.ok;
    } catch (_fetchErr) {
      previewOk = false;
    }

    if (!previewOk) {
      // Preview failed (e.g. old server without this endpoint, or network error).
      // Still allow the user to proceed — just show a fallback message.
      if (previewSince) previewSince.innerHTML = "";
      if (previewContent) previewContent.innerHTML =
        `<p class="small" style="color:#6b7280;margin:4px 0">
          Не удалось подсчитать количество данных заранее.<br>
          Синхронизация будет выполнена с учётом настроенной даты начала загрузки.
        </p>`;
      if (confirmBtn) confirmBtn.disabled = false;
      if (syncInfo) syncInfo.textContent = "";
      return;
    }

    const items = Array.isArray(previewData.items) ? previewData.items : [];
    if (!items.length) {
      closeSyncPreviewModal();
      if (syncInfo) syncInfo.textContent = "Нет активных кабинетов для синхронизации.";
      return;
    }

    // Build table with per-account counts
    const hasWb = items.some((i) => String(i.marketplace || "").toLowerCase() === "wb");
    const sinceDateText = previewData.since_date
      ? `Дата начала загрузки: <b>${previewData.since_date}</b>`
      : "Дата начала загрузки не ограничена — загрузятся все данные";
    const wbNote = hasWb && previewData.since_date
      ? `<br><span class="small" style="color:#9ca3af">⚠️ WB не фильтрует отзывы по дате на стороне API — показано общее число неотвеченных. Реально сохранятся только отзывы, созданные с ${previewData.since_date}.</span>`
      : "";
    if (previewSince) previewSince.innerHTML = sinceDateText + wbNote;

    const countCell = (n) =>
      `<td class="sync-preview-count${n === 0 ? " zero" : ""}">${n.toLocaleString("ru-RU")}</td>`;

    let rows = items.map((item) => {
      const aid = String(item.account_id || "");
      const name = String(item.account_name || `Кабинет #${aid || "?"}`);
      const mp = String(item.marketplace || "").toUpperCase();
      return `<tr data-account-id="${aid}">
        <td>
          <label class="sync-preview-check-label">
            <input type="checkbox" class="sync-preview-check" value="${aid}" checked>
            ${name} <span class="small" style="color:#9ca3af">${mp}</span>
          </label>
        </td>
        ${countCell(Number(item.reviews || 0))}
        ${countCell(Number(item.questions || 0))}
        ${countCell(Number(item.chats || 0))}
      </tr>`;
    }).join("");

    if (items.length > 1) {
      rows += `<tr class="total-row" id="syncPreviewTotalRow">
        <td>Итого (выбрано)</td>
        ${countCell(Number(previewData.total_reviews || 0))}
        ${countCell(Number(previewData.total_questions || 0))}
        ${countCell(Number(previewData.total_chats || 0))}
      </tr>`;
    }

    if (previewContent) {
      previewContent.innerHTML = `
        <table class="sync-preview-table">
          <thead>
            <tr>
              <th></th>
              <th>⭐ Отзывы</th>
              <th>❓ Вопросы</th>
              <th>💬 Чаты</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>`;
      // Update confirm button state based on checkboxes
      previewContent.querySelectorAll(".sync-preview-check").forEach((cb) => {
        cb.addEventListener("change", _updateSyncPreviewConfirmBtn);
      });
    }
    // Save total expected items for progress display
    if (previewOk && previewData) {
      const total = Number(previewData.total || 0);
      sessionStorage.setItem("sync_total_items", String(total));
    }
    if (confirmBtn) confirmBtn.disabled = false;
    if (syncInfo) syncInfo.textContent = "";
  } catch (_error) {
    // On any unexpected error still let the user proceed
    if (previewSince) previewSince.innerHTML = "";
    if (previewContent) previewContent.innerHTML =
      `<p class="small" style="color:#6b7280;margin:4px 0">
        Не удалось подсчитать количество данных заранее.
        Можно продолжить синхронизацию.
      </p>`;
    const confirmBtn2 = document.getElementById("syncPreviewConfirmBtn");
    if (confirmBtn2) confirmBtn2.disabled = false;
    if (syncInfo) syncInfo.textContent = "";
  } finally {
    syncCapabilityCheckInProgress = false;
  }
}

async function confirmSyncPreview() {
  closeSyncPreviewModal();

  if (syncInProgress) return;
  const syncButton = document.getElementById("syncAllBtn");
  const syncInfo = document.getElementById("syncInfo");
  syncInProgress = true;
  if (syncButton) {
    syncButton.disabled = true;
    syncButton.textContent = "⏳ Синхронизация...";
  }
  if (syncInfo) syncInfo.textContent = "";
  showSyncProgress();
  startGlobalSyncPoll();

  try {
    const totalExpected = Number(sessionStorage.getItem("sync_total_items") || 0);
    const selectedIds = _getSelectedSyncAccountIds();
    const payload = {
      all_accounts: selectedIds === null,
      account_id: null,
      account_ids: selectedIds,
      total_expected: totalExpected || null,
    };
    const res = await fetch("/api/sync", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      const errMsg = res.status === 409
        ? "Синхронизация уже выполняется (авто-синк). Подождите ~1 минуту и попробуйте снова."
        : "Ошибка: " + (data.detail || "синхронизация не выполнена");
      if (syncInfo) syncInfo.textContent = errMsg;
      // Show error in a brief alert so it's visible regardless of current section
      if (res.status === 409) alert(errMsg);
      stopGlobalSyncPoll();
      hideSyncProgress();
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
    stopGlobalSyncPoll();
    sessionStorage.removeItem("sync_total_items");
    const fill = document.getElementById("syncProgressFill");
    const detailEl = document.getElementById("syncProgressText");
    const accEl = document.getElementById("syncProgressAccountsText");
    const pctEl2 = document.getElementById("syncProgressPct");
    if (fill) fill.style.width = "100%";
    if (detailEl) detailEl.textContent = "✅ Готово — данные загружены";
    if (accEl) accEl.textContent = "";
    if (pctEl2) pctEl2.textContent = "100%";
    window.setTimeout(hideSyncProgress, 2000);
    const tasks = [loadReviews(), loadQuestions(), loadChats()];
    if (canViewSection("analytics")) tasks.push(loadAnalytics());
    await Promise.all(tasks);
    // Show detailed sync report modal
    try {
      const statusRes = await fetch("/api/sync/status");
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        if (statusData.last_sync_report) {
          openSyncReportModal(statusData.last_sync_report);
        }
      }
    } catch (_) {}
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
  if (reviewsState.product_search) query.set("product_search", reviewsState.product_search);
  if (reviewsState.has_contradiction) query.set("has_contradiction", "1");
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
    tr.innerHTML = `<td colspan="3" class="small">Ошибка: ${esc(data.detail || "не удалось загрузить отзывы")}</td>`;
    tbody.appendChild(tr);
    return;
  }
  for (const review of data.items || []) {
    const tr = document.createElement("tr");
    const sendErrorMessage = String(review.send_error_message || "").trim();
    const hasSendError = review.status === "queued_for_operator" && Boolean(sendErrorMessage);
    const hasSavedReply = Boolean(String(review.auto_reply || "").trim()) && hasSendError;
    // Contradiction — must be declared before use
    const contradiction = (review.metadata || {}).rating_contradiction;
    if (hasSendError) tr.classList.add("review-row-send-error");
    if (contradiction) tr.classList.add("review-row-contradiction");
    const sendErrorIcon = hasSendError
      ? `<span class="send-error-indicator" title="Ошибка отправки: ${esc(sendErrorMessage)}">❗</span>`
      : "";
    const contradictionIcon = contradiction
      ? `<span class="review-contradiction-badge" data-tip="${esc("Яндекс определил \u00AB" + (contradiction.yandex_group_title || contradiction.yandex_group) + "\u00BB, но оценка " + contradiction.rating + " \u2605. Требует проверки")}">!</span>`
      : "";
    const retryBtn = hasSavedReply
      ? `<button type="button" class="review-icon-btn review-retry-btn" title="Повторить отправку" onclick="retryReviewSend('${esc(review.review_uid)}')">🔄</button>`
      : "";
    // --- Column 1: Review ---
    const meta = review.metadata || {};
    const rawProduct = (meta.raw || {}).productDetails || {};
    const groupTitle = labelFromMap(categoryLabels, review.category) || esc(review.category || "");
    const subgroup = esc(review.classified_subgroup || "");
    const textParts = [];
    if (review.text) textParts.push(`<div class="review-text">${esc(review.text)}</div>`);
    const rawItem = meta.raw || {};
    if (rawItem.pros) textParts.push(`<div class="review-pros small"><b>Достоинства:</b> ${esc(rawItem.pros)}</div>`);
    if (rawItem.cons) textParts.push(`<div class="review-cons small"><b>Недостатки:</b> ${esc(rawItem.cons)}</div>`);

    // --- Column 2: Reply ---
    const reviewUid = esc(review.review_uid);
    const isAnswered = review.status === "answered_auto" || review.status === "answered_manual";
    const isOzon = String(review.source || "").toLowerCase().includes("ozon");

    let replyText;
    if (isAnswered) {
      // Show the ACTUAL sent reply, not the AI suggestion
      const actualReply = String(review.manual_reply || review.auto_reply || "").trim();
      if (actualReply) {
        replyText = actualReply;
      } else if (isOzon) {
        replyText = "Ответ предоставлен напрямую через портал ОЗОНа или другой сервис";
      } else {
        replyText = "";
      }
    } else {
      // New/queued review — show suggestion for editing
      replyText = String(review.suggested_reply || review.auto_reply || "");
    }

    // --- Column 3: Product ---
    const productName = esc(rawProduct.productName || rawItem.productName || "");
    const article = esc(rawProduct.supplierArticle || rawItem.supplierArticle || "");
    const brand = esc(rawProduct.brand || rawItem.brand || "");
    const seller = esc(rawProduct.seller || rawItem.seller || "");
    // Build marketplace link for product name
    const nmId = rawProduct.nmId || rawItem.nmId || rawItem.nmID || rawItem.productId || null;
    const ozonProductId = rawItem.product_id || rawItem.productId || rawItem.item_id || null;
    let productUrl = "";
    if (review.source === "ozon" || String(review.source || "").toLowerCase().includes("ozon")) {
      if (ozonProductId) productUrl = `https://www.ozon.ru/product/${ozonProductId}/`;
    } else if (nmId) {
      productUrl = `https://www.wildberries.ru/catalog/${nmId}/detail.aspx`;
    }

    tr.innerHTML = `
      <td class="review-col-review">
        <div class="review-group-title">${groupTitle}${contradictionIcon}</div>
        <div class="review-stars">${renderRatingStars(review.rating)}</div>
        ${textParts.join("")}
        ${subgroup ? `<div class="review-subgroup-tag">${subgroup}</div>` : ""}
        <div class="review-meta-small">${esc(review.author || "")} · ${esc(_toMsk((meta.raw || {}).createdDate || review.created_at || ""))}</div>
      </td>
      <td class="review-col-reply">
        ${isAnswered ? `
          <textarea class="review-reply-textarea review-reply-answered" id="reply-${reviewUid}" readonly>${esc(replyText)}</textarea>
        ` : `
          <textarea class="review-reply-textarea" id="reply-${reviewUid}" readonly>${esc(replyText)}</textarea>
          <div class="review-reply-actions">
            <button type="button" class="review-icon-btn" title="Отправить ответ" onclick="sendReviewReply('${reviewUid}')">📤</button>
            <button type="button" class="review-icon-btn" title="${contradiction ? "Шаблон недоступен: требует ручной проверки" : "Другой шаблон"}" ${contradiction ? "disabled" : ""} onclick="refreshReviewTemplate('${reviewUid}', '${esc(review.category || "")}', '${esc(review.classified_subgroup || "")}')">🔄</button>
            <button type="button" class="review-icon-btn" title="Шаблоны" onclick="openReviewTemplatesModal('${reviewUid}')">📋</button>
            <button type="button" class="review-icon-btn" title="Редактировать" onclick="editReviewReply('${reviewUid}')">✏️</button>
            ${retryBtn}
            ${sendErrorIcon}
          </div>
        `}
      </td>
      <td class="review-col-product">
        ${productName
          ? productUrl
            ? `<div class="review-product-name"><a href="${productUrl}" target="_blank" rel="noopener noreferrer" class="review-product-link">${productName}</a></div>`
            : `<div class="review-product-name">${productName}</div>`
          : ""}
        ${article ? `<div class="review-product-detail small">Артикул: ${article}</div>` : ""}
        ${brand ? `<div class="review-product-detail small">Бренд: ${brand}</div>` : ""}
        ${seller ? `<div class="review-product-detail small">Продавец: ${seller}</div>` : ""}
        ${review.product_photo_url ? `<img src="${esc(review.product_photo_url)}" class="product-thumb" alt="" onerror="this.style.display='none'">` : ""}
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

// ── Supply module (Поставки) ──────────────────────────────────────────────────

const SUPPLY_STATUS_LABELS = { 1: "Новая", 2: "Запланирована", 3: "Отгрузка разрешена", 4: "На приёмке", 5: "Принята", 6: "Отгружено на воротах" };

let suppliesState = {
  items: [],
  total: 0,
  page: 1,
  page_size: (() => { try { const v = parseInt(localStorage.getItem("supplies_page_size")); return [30,50,100].includes(v) ? v : 50; } catch(_) { return 50; } })(),
  sources: [],
};

function onSupplySourceMarketplaceChange() {
  const mp = document.getElementById("newSupplySourceMarketplace")?.value || "wb";
  const clientIdRow = document.getElementById("newSupplyOzonClientIdRow");
  const apiKeyPlaceholder = document.getElementById("newSupplySourceApiKey");
  if (clientIdRow) clientIdRow.style.display = mp === "ozon" ? "" : "none";
  if (apiKeyPlaceholder) apiKeyPlaceholder.placeholder = mp === "ozon" ? "API-ключ OZON (из личного кабинета продавца)" : "Токен WB Поставки";
}
window.onSupplySourceMarketplaceChange = onSupplySourceMarketplaceChange;

function toggleAddSupplySourceForm(show) {
  const form = document.getElementById("addSupplySourceForm");
  if (!form) return;
  form.classList.toggle("hidden", !show);
  form.style.display = show ? "" : "none";
  if (!show) {
    const nameEl = document.getElementById("newSupplySourceName");
    const keyEl = document.getElementById("newSupplySourceApiKey");
    const mpEl = document.getElementById("newSupplySourceMarketplace");
    const cidEl = document.getElementById("newSupplySourceClientId");
    if (nameEl) nameEl.value = "";
    if (keyEl) keyEl.value = "";
    if (mpEl) mpEl.value = "wb";
    if (cidEl) cidEl.value = "";
    onSupplySourceMarketplaceChange();
  }
}

async function loadSupplySources() {
  const res = await fetch("/api/supply-sources").catch(() => null);
  if (!res || !res.ok) return;
  const data = await res.json();
  suppliesState.sources = Array.isArray(data) ? data : [];
  renderSupplySourcesTable();
  updateSuppliesSourceFilter();
}

function updateSuppliesSourceFilter() {
  const sel = document.getElementById("suppliesSourceFilter");
  if (!sel) return;
  while (sel.options.length > 1) sel.remove(1);
  for (const src of suppliesState.sources) {
    const opt = document.createElement("option");
    opt.value = String(src.id);
    opt.textContent = String(src.name || `Источник #${src.id}`);
    sel.appendChild(opt);
  }
}

function renderSupplySourcesTable() {
  const tbody = document.getElementById("supplySourcesTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const sources = suppliesState.sources;
  if (!sources.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">Источники не добавлены</td></tr>';
    return;
  }
  sources.forEach((src, idx) => {
    const tr = document.createElement("tr");
    const lastSync = src.last_synced_at
      ? new Date(src.last_synced_at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "—";
    const fullPreview = src.api_key_preview || "—";
    const shortPreview = fullPreview.length > 18 ? fullPreview.slice(0, 14) + "…" : fullPreview;
    const mpLabel = (src.marketplace||"wb").toUpperCase() === "OZON" ? '<span style="color:#005bff;font-weight:600">OZON</span>' : '<span style="color:#8b4513;font-weight:600">WB</span>';
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td>${mpLabel}</td>
      <td>${esc(src.name || "")}</td>
      <td class="supply-src-key-cell">
        <span class="supply-src-key-text" title="${esc(fullPreview)}">${esc(shortPreview)}</span>
      </td>
      <td>${src.is_enabled ? '<span style="color:#16a34a;font-weight:600">Да</span>' : '<span style="color:#9ca3af">Нет</span>'}</td>
      <td class="small" style="color:#64748b">${lastSync}</td>
      <td>
        <div class="row" style="gap:6px;flex-wrap:nowrap">
          <button class="secondary small-btn" onclick="toggleSupplySource(${src.id}, ${!src.is_enabled})">${src.is_enabled ? "Отключить" : "Включить"}</button>
          <button class="secondary small-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="deleteSupplySource(${src.id})">Удалить</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function createSupplySource() {
  const nameEl = document.getElementById("newSupplySourceName");
  const keyEl = document.getElementById("newSupplySourceApiKey");
  const mpEl = document.getElementById("newSupplySourceMarketplace");
  const cidEl = document.getElementById("newSupplySourceClientId");
  const info = document.getElementById("addSupplySourceInfo");
  const name = (nameEl?.value || "").trim();
  const api_key = (keyEl?.value || "").trim();
  const marketplace = mpEl?.value || "wb";
  const client_id = (cidEl?.value || "").trim();
  if (!name) { if (info) { info.textContent = "Введите название"; info.style.color = "#b91c1c"; } return; }
  if (!api_key) { if (info) { info.textContent = "Введите API-ключ"; info.style.color = "#b91c1c"; } return; }
  if (marketplace === "ozon" && !client_id) { if (info) { info.textContent = "Введите Client-ID"; info.style.color = "#b91c1c"; } return; }
  if (info) { info.textContent = "Сохранение..."; info.style.color = ""; }
  const res = await fetch("/api/supply-sources", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ name, api_key, marketplace, client_id }),
  }).catch(() => null);
  if (!res) { if (info) { info.textContent = "Ошибка сети"; info.style.color = "#b91c1c"; } return; }
  if (!res.ok) {
    const rawText = await res.text().catch(() => "");
    console.error("supply-sources POST error:", res.status, rawText);
    let msg = "Ошибка " + res.status;
    try {
      const err = JSON.parse(rawText);
      const detail = err.detail;
      msg = Array.isArray(detail)
        ? detail.map((e) => e.msg || JSON.stringify(e)).join("; ")
        : String(detail || msg);
    } catch (_) {}
    if (info) { info.textContent = msg; info.style.color = "#b91c1c"; }
    return;
  }
  if (info) { info.textContent = "Сохранено"; info.style.color = "#16a34a"; }
  toggleAddSupplySourceForm(false);
  await loadSupplySources();
}

async function toggleSupplySource(sourceId, isEnabled) {
  await fetch(`/api/supply-sources/${sourceId}/toggle`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify({ is_enabled: isEnabled }),
  }).catch(() => null);
  await loadSupplySources();
}

async function deleteSupplySource(sourceId) {
  if (!confirm("Удалить источник? Все данные о поставках из него будут удалены.")) return;
  await fetch(`/api/supply-sources/${sourceId}`, { method: "DELETE", headers: jsonHeaders() }).catch(() => null);
  await loadSupplySources();
}

async function loadSupplies(resetPage = false) {
  if (resetPage) suppliesState.page = 1;
  const sourceId = document.getElementById("suppliesSourceFilter")?.value || "";
  const statusId = document.getElementById("suppliesStatusFilter")?.value || "";
  const productionFilter = document.getElementById("suppliesProductionFilter")?.value || "";
  const searchFilter = document.getElementById("suppliesSearchFilter")?.value.trim() || "";
  const dateFrom = document.getElementById("suppliesDateFrom")?.value || "";
  const dateTo = document.getElementById("suppliesDateTo")?.value || "";
  const params = new URLSearchParams({ page: suppliesState.page, page_size: suppliesState.page_size });
  if (sourceId) params.set("source_id", sourceId);
  if (statusId) params.set("status_id", statusId);
  if (productionFilter) params.set("production", productionFilter);
  if (searchFilter) params.set("search", searchFilter);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const info = document.getElementById("suppliesInfo");
  if (info) info.textContent = "Загрузка...";
  const res = await fetch("/api/supplies?" + params.toString()).catch(() => null);
  if (!res || !res.ok) {
    if (info) info.textContent = "Ошибка загрузки";
    return;
  }
  const data = await res.json();
  suppliesState.items = data.items || [];
  suppliesState.total = data.total || 0;
  suppliesState.page = data.page || 1;
  renderSuppliesTable();
  const totalPages = Math.max(1, Math.ceil(suppliesState.total / suppliesState.page_size));
  if (info) info.textContent = `Поставок: ${suppliesState.total}`;
  const pageInfo = document.getElementById("suppliesPageInfo");
  if (pageInfo) pageInfo.textContent = `${suppliesState.page} / ${totalPages}`;
  const prevBtn = document.getElementById("suppliesPrevBtn");
  const nextBtn = document.getElementById("suppliesNextBtn");
  if (prevBtn) prevBtn.disabled = suppliesState.page <= 1;
  if (nextBtn) nextBtn.disabled = suppliesState.page >= totalPages;
  // Sync page size select with current state
  const psSel = document.getElementById("suppliesPageSizeSelect");
  if (psSel) psSel.value = String(suppliesState.page_size);
}

function changeSuppliesPageSize(val) {
  const size = parseInt(val);
  if (![30,50,100].includes(size)) return;
  suppliesState.page_size = size;
  suppliesState.page = 1;
  try { localStorage.setItem("supplies_page_size", String(size)); } catch(_) {}
  loadSupplies(true);
}

function suppliesChangePage(delta) {
  const totalPages = Math.max(1, Math.ceil(suppliesState.total / suppliesState.page_size));
  const newPage = Math.max(1, Math.min(totalPages, suppliesState.page + delta));
  if (newPage === suppliesState.page) return;
  suppliesState.page = newPage;
  loadSupplies();
}

function _supplyWarehouseLabel(item) {
  const dest = (item.warehouse_name || "").trim();
  const transit = (item.transit_warehouse_name || "").trim();
  if (transit && dest) return `${esc(transit)} → <b>${esc(dest)}</b>`;
  if (dest) return esc(dest);
  return "—";
}

// Abbreviate driver name: "Иванов Иван Иванович" → "Иванов И.И."
function _shortDriverName(fullName) {
  if (!fullName) return "";
  const parts = fullName.trim().split(/\s+/);
  if (parts.length === 1) return parts[0];
  const last = parts[0];
  const initials = parts.slice(1).map(p => p[0] ? p[0].toUpperCase() + "." : "").join("");
  return last + " " + initials;
}

function _renderSupplyDocButtons(item) {
  // Parse slots from drivers_json or legacy fields
  let slots = [];
  if (item.drivers_json) {
    try { slots = JSON.parse(item.drivers_json); } catch (_) {}
  }
  if (!slots.length) {
    slots = [{ pass_number: item.pass_number || "", driver_name: item.driver_name || "", pallets_count: item.pallets_count || "" }];
  }
  const validSlots = slots.filter(s => _isWbGiCode(s.pass_number));
  if (!validSlots.length) return "";

  const totalPallets = slots.reduce((s, sl) => s + (parseInt(sl.pallets_count) || 0), 0);
  const totalPalletsStr = totalPallets > 0 ? String(totalPallets) : (slots[0]?.pallets_count || "");
  const multi = validSlots.length > 1;
  let html = "";

  // Helper: get effective driver name for a slot
  const _effectiveName = (s) => s.manual_driver_name || s.driver_name || "";

  // ШК поставки — per driver
  validSlots.forEach((s, i) => {
    const dName = _shortDriverName(_effectiveName(s));
    const label = multi ? `⬇ ШК — ${dName || `Вод. ${i+1}`}` : "⬇ ШК поставки";
    html += `<button class="supply-detail-link supply-barcode-link" onclick="downloadSupplyBarcode('${esc(s.pass_number)}',${item.supply_id})">${label}</button>`;
  });

  const _pRow = `display:flex;flex-wrap:nowrap;align-items:center;gap:2px;width:100%;min-width:0`;
  const _pBtn = `flex:0 0 60px;min-width:60px;width:60px;height:28px;padding:0;font-size:15px;font-family:'Segoe UI Symbol','Arial Unicode MS',sans-serif`;

  // Упаковочный лист — per driver (only pass_number changes)
  validSlots.forEach((s, i) => {
    if (!_isWbGiCode(s.pass_number)) return;
    const dName = _shortDriverName(_effectiveName(s));
    const label = multi ? `⬇ УЛ — ${dName || `Вод. ${i+1}`}` : "⬇ Упаковочный лист";
    html += `<div style="${_pRow}"><button class="supply-detail-link supply-packing-link" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" onclick="downloadPackingListForSlot(${item.supply_id},${i})">${label}</button><button class="supply-detail-link supply-print-btn" style="${_pBtn}" onclick="printPackingListForSlot(${item.supply_id},${i})" title="Печать">⎙</button></div>`;
  });

  // Доверенность — per driver
  validSlots.forEach((s, i) => {
    if (!_effectiveName(s)) return;
    const dName = _shortDriverName(_effectiveName(s));
    const label = multi ? `⬇ Довер. — ${dName}` : "⬇ Доверенность";
    html += `<div style="${_pRow}"><button class="supply-detail-link supply-poa-link" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" onclick="downloadPoAForSlot(${item.supply_id},${i})">${label}</button><button class="supply-detail-link supply-print-btn" style="${_pBtn}" onclick="printPoAForSlot(${item.supply_id},${i})" title="Печать">⎙</button></div>`;
  });

  // ТТН — per driver
  validSlots.forEach((s, i) => {
    if (!_effectiveName(s)) return;
    const dName = _shortDriverName(_effectiveName(s));
    const label = multi ? `⬇ ТТН — ${dName}` : "⬇ ТТН";
    html += `<div style="${_pRow}"><button class="supply-detail-link supply-ttn-link" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" onclick="downloadTTNForSlot(${item.supply_id},${i})">${label}</button><button class="supply-detail-link supply-print-btn" style="${_pBtn}" onclick="printTTNForSlot(${item.supply_id},${i})" title="Печать">⎙</button></div>`;
  });

  return html;
}

function renderSuppliesTable() {
  const tbody = document.getElementById("suppliesTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!suppliesState.items.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">Нет данных. Нажмите «Синхронизировать».</td></tr>';
    return;
  }
  for (const item of suppliesState.items) {
    const supplyDate = item.supply_date
      ? new Date(item.supply_date).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
      : "—";
    const statusLabel = SUPPLY_STATUS_LABELS[item.status_id] || String(item.status_id || "—");
    const tr = document.createElement("tr");
    tr.className = "supply-row";
    tr.dataset.supplyId = String(item.supply_id);
    tr.innerHTML = `
      <td style="width:32px;padding:0 4px;text-align:center">
        <input type="checkbox" class="supply-row-checkbox" data-supply-id="${item.supply_id}" onchange="onSupplyCheckboxChange()" />
      </td>
      <td class="supply-expand-cell">
        <button class="supply-expand-btn" title="Показать товары" onclick="toggleSupplyGoods(this, ${item.supply_id})" aria-label="Развернуть">▶</button>
      </td>
      <td><span class="supply-id-text">${item.supply_id}</span></td>
      <td class="supply-legal-cell">${esc(item.supplier_name || "—")}</td>
      <td class="supply-wh-cell">${_supplyWarehouseLabel(item)}</td>
      <td class="supply-prod-cell">${item.production ? esc(item.production) : '<span class="supply-prod-empty">Требует заполнения</span>'}</td>
      <td class="supply-date-cell">${supplyDate}</td>
      <td class="supply-qty-cell">${item.quantity ?? "—"}</td>
      <td><span class="supply-status-badge supply-status-${item.status_id}">${statusLabel}</span></td>
      <td class="supply-links-cell">
        <div class="supply-links-col">
          <button class="supply-detail-link" onclick="openSupplyDetailsModal(${item.supply_id})">☰ Детали поставки</button>
          ${_renderSupplyDocButtons(item)}
        </div>
      </td>
    `;
    tbody.appendChild(tr);
    const goodsTr = document.createElement("tr");
    goodsTr.className = "supply-goods-row hidden";
    goodsTr.dataset.supplyId = String(item.supply_id);
    goodsTr.innerHTML = `<td colspan="10"><div class="supply-goods-container" id="supply-goods-${item.supply_id}"><span class="small" style="color:#94a3b8">Загрузка…</span></div></td>`;
    tbody.appendChild(goodsTr);
  }
}

async function toggleSupplyGoods(btn, supplyId) {
  const goodsRow = document.querySelector(`.supply-goods-row[data-supply-id="${supplyId}"]`);
  if (!goodsRow) return;
  const isOpen = !goodsRow.classList.contains("hidden");
  if (isOpen) {
    goodsRow.classList.add("hidden");
    btn.textContent = "▶";
    btn.classList.remove("expanded");
    return;
  }
  goodsRow.classList.remove("hidden");
  btn.textContent = "▼";
  btn.classList.add("expanded");
  const container = document.getElementById(`supply-goods-${supplyId}`);
  if (!container || container.dataset.loaded) return;
  const res = await fetch(`/api/supplies/${supplyId}/goods`).catch(() => null);
  if (!res || !res.ok) {
    container.innerHTML = '<span class="small" style="color:#b91c1c">Ошибка загрузки товаров</span>';
    return;
  }
  const goods = await res.json();
  container.dataset.loaded = "1";
  if (!goods.length) {
    container.innerHTML = '<span class="small" style="color:#94a3b8">Нет товаров</span>';
    return;
  }
  let html = '<table class="supply-goods-table"><thead><tr><th>Арт. WB (nmID)</th><th>Наименование</th><th>Кол-во</th></tr></thead><tbody>';
  for (const g of goods) {
    const name = g.product_name || esc(g.vendor_code || "—");
    html += `<tr>
      <td>${g.nm_id || "—"}</td>
      <td>${esc(name)}</td>
      <td>${g.quantity ?? "—"}</td>
    </tr>`;
  }
  html += "</tbody></table>";
  container.innerHTML = html;
}

const SUPPLY_BOX_TYPE_LABELS = {
  0: "Не указан",
  1: "Короба",
  2: "Короба",
  5: "Монопаллеты / СГТ",
  6: "Паллеты",
};

let _supplyDetailsCurrentId = null;
let _supplyDriversCache = [];

// ── Supply drivers ──

async function loadSupplyDrivers() {
  const res = await fetch("/api/supply-drivers").catch(() => null);
  if (!res || !res.ok) return;
  _supplyDriversCache = await res.json().catch(() => []);
  renderSupplyDriversTable();
  _populateDriverSelect();
}

function renderSupplyDriversTable() {
  const tbody = document.getElementById("supplyDriversTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!_supplyDriversCache.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">Водители не добавлены</td></tr>';
    return;
  }
  _supplyDriversCache.forEach((d, idx) => {
    const tr = document.createElement("tr");
    tr.dataset.id = d.id;
    tr.innerHTML = `
      <td>${idx + 1}</td>
      <td class="editable-cell">${esc(d.full_name || "")}</td>
      <td class="editable-cell">${esc(d.in_person || "")}</td>
      <td class="editable-cell">${esc(d.documents || "")}</td>
      <td>
        <div class="row" style="gap:4px;flex-wrap:nowrap">
          <button class="secondary small-btn" onclick="startEditDriver(${d.id})">✏</button>
          <button class="secondary small-btn" style="color:#b91c1c;border-color:#fca5a5"
            onclick="deleteSupplyDriver(${d.id})" title="Удалить">🗑</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function _populateDriverSelect(currentValue) {
  const sel = document.getElementById("sdDriverSelect");
  if (!sel) return;
  const prev = currentValue !== undefined ? currentValue : sel.value;
  // Keep only first option (placeholder) and __new__
  while (sel.options.length > 1) sel.remove(1);
  // Insert drivers before __new__ option
  for (const d of _supplyDriversCache) {
    const opt = document.createElement("option");
    opt.value = d.full_name;
    opt.textContent = d.full_name;
    sel.insertBefore(opt, sel.options[sel.options.length - 1]);
  }
  // Add __new__ at end if not present
  if (!Array.from(sel.options).find((o) => o.value === "__new__")) {
    const newOpt = document.createElement("option");
    newOpt.value = "__new__"; newOpt.textContent = "＋ Новый водитель…";
    sel.appendChild(newOpt);
  }
  // Restore selection
  if (prev) sel.value = prev;
}

function toggleAddDriverForm(show) {
  const form = document.getElementById("addDriverForm");
  if (!form) return;
  form.classList.toggle("hidden", !show);
  form.style.display = show ? "" : "none";
  if (!show) {
    const inp = document.getElementById("newDriverName");
    if (inp) inp.value = "";
    const ipEl = document.getElementById("newDriverInPerson");
    if (ipEl) ipEl.value = "";
    const docs = document.getElementById("newDriverDocuments");
    if (docs) docs.value = "";
    const info = document.getElementById("addDriverInfo");
    if (info) { info.textContent = ""; info.style.color = ""; }
  }
}

async function _createDriverRequest(name, infoEl, documents, in_person) {
  if (infoEl) { infoEl.textContent = "Сохранение…"; infoEl.style.color = ""; }
  const res = await fetch("/api/supply-drivers", {
    method: "POST", headers: jsonHeaders(),
    body: JSON.stringify({ full_name: name, documents: documents || "", in_person: in_person || "" }),
  }).catch(() => null);
  if (!res || !res.ok) {
    const err = await res?.json().catch(() => ({})) || {};
    const msg = res?.status === 409
      ? `Водитель «${name}» уже существует`
      : (err.detail || "Ошибка сохранения");
    if (infoEl) { infoEl.textContent = msg; infoEl.style.color = "#b91c1c"; }
    return false;
  }
  return true;
}

async function saveSupplyDriver() {
  const inp = document.getElementById("newDriverName");
  const info = document.getElementById("addDriverInfo");
  const name = (inp?.value || "").trim();
  const inpVal = document.getElementById("newDriverInPerson")?.value.trim() || "";
  const docs = document.getElementById("newDriverDocuments")?.value.trim() || "";
  if (!name) { if (info) { info.textContent = "Введите имя"; info.style.color = "#b91c1c"; } return; }
  const ok = await _createDriverRequest(name, info, docs, inpVal);
  if (!ok) return;
  if (info) { info.textContent = "Добавлен"; info.style.color = "#16a34a"; }
  toggleAddDriverForm(false);
  await loadSupplyDrivers();
}

async function startEditDriver(id) {
  const item = _supplyDriversCache.find((x) => x.id === id);
  if (!item) return;
  const tr = document.querySelector(`#supplyDriversTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const cells = tr.querySelectorAll(".editable-cell");
  cells[0].innerHTML = `<input class="edit-inline-input" data-field="name" value="${esc(item.full_name||"")}" />`;
  cells[1].innerHTML = `<input class="edit-inline-input" data-field="inp" value="${esc(item.in_person||"")}" />`;
  cells[2].innerHTML = `<input class="edit-inline-input" data-field="docs" value="${esc(item.documents||"")}" />`;
  const actionCell = tr.cells[tr.cells.length - 1];
  actionCell.innerHTML = `<div class="row" style="gap:4px;flex-wrap:nowrap">
    <button class="secondary small-btn" style="color:#16a34a;border-color:#86efac" onclick="saveEditDriver(${id})">Сохранить</button>
    <button class="secondary small-btn" onclick="loadSupplyDrivers()">Отмена</button>
  </div>`;
  cells[0].querySelector("input")?.focus();
}

async function saveEditDriver(id) {
  const tr = document.querySelector(`#supplyDriversTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const name = tr.querySelector("[data-field='name']")?.value.trim() || "";
  const inp = tr.querySelector("[data-field='inp']")?.value.trim() || "";
  const docs = tr.querySelector("[data-field='docs']")?.value.trim() || "";
  if (!name) return;
  await fetch(`/api/supply-drivers/${id}`, { method: "PATCH", headers: jsonHeaders(), body: JSON.stringify({ full_name: name, in_person: inp, documents: docs }) }).catch(() => null);
  await loadSupplyDrivers();
}

async function deleteSupplyDriver(driverId) {
  if (!confirm("Удалить водителя?")) return;
  await fetch(`/api/supply-drivers/${driverId}`, { method: "DELETE", headers: jsonHeaders() }).catch(() => null);
  await loadSupplyDrivers();
}

// Called when user selects "＋ Новый водитель…" in the modal dropdown
function onDriverSelectChange() {
  const sel = document.getElementById("sdDriverSelect");
  const form = document.getElementById("sdNewDriverForm");
  if (!sel || !form) return;
  if (sel.value === "__new__") {
    form.classList.remove("hidden"); form.style.display = "";
    document.getElementById("sdNewDriverName")?.focus();
  } else {
    form.classList.add("hidden"); form.style.display = "none";
  }
}

function cancelNewDriverInModal() {
  const form = document.getElementById("sdNewDriverForm");
  if (form) { form.classList.add("hidden"); form.style.display = "none"; }
  const inp = document.getElementById("sdNewDriverName");
  if (inp) inp.value = "";
  const sel = document.getElementById("sdDriverSelect");
  if (sel) sel.value = "";
}

async function addDriverFromModal() {
  const inp = document.getElementById("sdNewDriverName");
  const info = document.getElementById("sdNewDriverInfo");
  const name = (inp?.value || "").trim();
  if (!name) { if (info) { info.textContent = "Введите имя"; info.style.color = "#b91c1c"; } return; }
  const ok = await _createDriverRequest(name, info);
  if (!ok) return;
  // Refresh cache + settings table
  await loadSupplyDrivers();
  // Select the new driver in the dropdown
  _populateDriverSelect(name);
  const sel = document.getElementById("sdDriverSelect");
  if (sel) sel.value = name;
  // Hide inline form and clear
  cancelNewDriverInModal();
  if (inp) inp.value = "";
  if (info) { info.textContent = ""; }
}

// ── Driver slots for WB supply details ────────────────────────────────────
let _sdSlots = []; // [{pass_number, driver_name, pallets_count}]

function _sdGetSlots() {
  const container = document.getElementById("sdDriverSlots");
  if (!container) return [];
  const slots = [];
  container.querySelectorAll(".sd-slot").forEach((row, idx) => {
    const manualName = row.querySelector(`[data-field="manual_driver_name"]`);
    const manualDocs = row.querySelector(`[data-field="manual_driver_docs"]`);
    const isManual = manualName !== null;
    const prevSlot = _sdSlots[idx] || {};
    slots.push({
      pass_number:        row.querySelector(`[data-field="pass_number"]`)?.value.trim() || "",
      driver_name:        isManual ? "" : (row.querySelector(`[data-field="driver_name"]`)?.value || ""),
      pallets_count:      row.querySelector(`[data-field="pallets_count"]`)?.value.trim() || "",
      manual_driver_name: isManual ? (manualName.value.trim() || undefined) : undefined,
      manual_driver_docs: isManual ? (manualDocs?.value.trim() || undefined) : undefined,
      _manual_mode:       isManual,
    });
  });
  return slots;
}

function _sdRenderSlots() {
  const container = document.getElementById("sdDriverSlots");
  if (!container) return;
  const driverOptions = _supplyDriversCache.map(d =>
    `<option value="${esc(d.full_name||"")}">${esc(d.full_name||"")}</option>`
  ).join("");
  let html = "";
  _sdSlots.forEach((slot, idx) => {
    const isFirst = idx === 0;
    const isManual = Boolean(slot.manual_driver_name !== undefined ? slot.manual_driver_name : false);
    // manual mode: if manual_driver_name is set (even empty string after toggle)
    const manualMode = slot._manual_mode || false;
    const slotTitle = _sdSlots.length > 1 ? `<div class="sd-slot-num">Водитель ${idx + 1}</div>` : "";
    html += `<div class="sd-slot" data-slot="${idx}">`;
    html += slotTitle;
    // ШК поставки
    html += `<div class="supply-detail-row">
      <span class="supply-detail-label">ШК поставки</span>
      <div style="display:flex;gap:6px;align-items:center;flex:1">
        <input data-field="pass_number" type="text" class="supply-detail-input"
               value="${esc(slot.pass_number)}" placeholder="WB-GI-XXXXXXX" autocomplete="off" />
        ${isFirst
          ? `<button type="button" class="secondary icon-btn" onclick="sdAddSlot()" title="Добавить водителя" style="flex-shrink:0;width:32px;height:32px;font-size:15px">＋</button>`
          : `<button type="button" class="secondary icon-btn" onclick="sdRemoveSlot(${idx})" title="Удалить" style="flex-shrink:0;color:#b91c1c;border-color:#fca5a5;width:32px;height:32px">✕</button>`
        }
      </div>
    </div>`;
    // Водитель: dropdown or manual input
    html += `<div class="supply-detail-row">
      <span class="supply-detail-label">Водитель</span>
      <div style="display:flex;gap:6px;align-items:center;flex:1">
        ${manualMode
          ? `<div style="flex:1;display:flex;flex-direction:column;gap:4px">
               <input data-field="manual_driver_name" type="text" class="supply-detail-input"
                      value="${esc(slot.manual_driver_name||"")}" placeholder="Имя и фамилия" autocomplete="off" />
               <input data-field="manual_driver_docs" type="text" class="supply-detail-input"
                      value="${esc(slot.manual_driver_docs||"")}" placeholder="Документы (серия, №)" autocomplete="off" />
             </div>`
          : `<select data-field="driver_name" class="supply-detail-input" style="height:36px;flex:1">
               <option value="">— Требует заполнения —</option>
               ${driverOptions}
             </select>`
        }
        <button type="button" class="secondary icon-btn" onclick="sdToggleManualDriver(${idx})"
          title="${manualMode ? 'Выбрать из справочника' : 'Ввести вручную'}"
          style="flex-shrink:0;width:32px;height:32px;font-size:14px;${manualMode ? 'color:#b91c1c;border-color:#fca5a5' : ''}">${manualMode ? '✕' : '✏'}</button>
      </div>
    </div>`;
    // Паллет
    html += `<div class="supply-detail-row">
      <span class="supply-detail-label">Паллет</span>
      <input data-field="pallets_count" type="text" class="supply-detail-input"
             value="${esc(slot.pallets_count)}" placeholder="Требует заполнения" autocomplete="off" />
    </div>`;
    html += `</div>`;
  });
  container.innerHTML = html;
  // Set driver select values (dropdown mode only)
  _sdSlots.forEach((slot, idx) => {
    if (!slot._manual_mode) {
      const sel = container.querySelectorAll(".sd-slot")[idx]?.querySelector(`[data-field="driver_name"]`);
      if (sel) sel.value = slot.driver_name || "";
    }
  });
}

function sdToggleManualDriver(idx) {
  // Save current values before toggle
  _sdSlots = _sdGetSlots();
  const slot = _sdSlots[idx];
  if (!slot) return;
  slot._manual_mode = !slot._manual_mode;
  if (!slot._manual_mode) {
    // Switching back to dropdown — clear manual fields
    slot.manual_driver_name = undefined;
    slot.manual_driver_docs = undefined;
  } else {
    // Switching to manual — clear dropdown selection
    slot.driver_name = "";
  }
  _sdRenderSlots();
}
window.sdToggleManualDriver = sdToggleManualDriver;

function sdAddSlot() {
  _sdSlots = _sdGetSlots();
  _sdSlots.push({ pass_number: "", driver_name: "", pallets_count: "", _manual_mode: false });
  _sdRenderSlots();
}
window.sdAddSlot = sdAddSlot;

function sdRemoveSlot(idx) {
  _sdSlots = _sdGetSlots();
  _sdSlots.splice(idx, 1);
  _sdRenderSlots();
}
window.sdRemoveSlot = sdRemoveSlot;

function openSupplyDetailsModal(supplyId) {
  const item = suppliesState.items.find((x) => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;
  _supplyDetailsCurrentId = item.supply_id;

  document.getElementById("supplyDetailsTitle").textContent = `Детали поставки № ${item.supply_id}`;
  document.getElementById("sdSupplyId").textContent = item.supply_id;

  const supplyDateEl = document.getElementById("sdSupplyDate");
  if (supplyDateEl) {
    supplyDateEl.textContent = item.supply_date
      ? new Date(item.supply_date).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
      : "—";
  }
  const whEl = document.getElementById("sdWarehouse");
  if (whEl) whEl.innerHTML = _supplyWarehouseLabel(item);
  document.getElementById("sdQuantity").textContent = item.quantity != null ? `${item.quantity} шт.` : "—";
  document.getElementById("sdBoxType").textContent = SUPPLY_BOX_TYPE_LABELS[item.box_type_id] || `тип ${item.box_type_id || "—"}`;
  document.getElementById("sdSupplier").textContent = item.supplier_name || "—";

  const notesEl = document.getElementById("sdNotes");
  if (notesEl) notesEl.value = item.notes || "";
  _populateProductionSelects();
  const prodSel = document.getElementById("sdProduction");
  if (prodSel) prodSel.value = item.production || "";

  // Build slots from drivers_json or legacy fields
  if (item.drivers_json) {
    try { _sdSlots = JSON.parse(item.drivers_json); } catch (_) { _sdSlots = []; }
  }
  if (!_sdSlots || !_sdSlots.length) {
    _sdSlots = [{ pass_number: item.pass_number || "", driver_name: item.driver_name || "", pallets_count: item.pallets_count || "" }];
  }
  // Restore manual mode flag based on saved data
  _sdSlots.forEach(s => {
    s._manual_mode = Boolean(s.manual_driver_name);
  });
  _sdRenderSlots();

  const info = document.getElementById("sdInfo");
  if (info) { info.textContent = ""; info.style.color = ""; }
  const modal = document.getElementById("supplyDetailsModal");
  if (modal) { modal.classList.remove("hidden"); modal.removeAttribute("aria-hidden"); }
}

function copySupplyDetails() {
  const get = (id) => (document.getElementById(id)?.textContent || "").trim();
  const val = (id) => (document.getElementById(id)?.value || "").trim();
  const slots = _sdGetSlots();
  const lines = [
    `Поставка №: ${get("sdSupplyId")}`,
    `Дата поставки: ${get("sdSupplyDate")}`,
    `Поставщик: ${get("sdSupplier")}`,
    `Склад: ${document.getElementById("sdWarehouse")?.innerText || get("sdWarehouse") || "—"}`,
    `Количество: ${get("sdQuantity")}`,
    `Тип поставки: ${get("sdBoxType")}`,
    `Производство: ${document.getElementById("sdProduction")?.value || "—"}`,
    ...slots.map((s, i) => [
      `ШК поставки${slots.length > 1 ? ` (${i+1})` : ""}: ${s.pass_number || "—"}`,
      `Водитель${slots.length > 1 ? ` (${i+1})` : ""}: ${s.driver_name || "—"}`,
      `Паллет${slots.length > 1 ? ` (${i+1})` : ""}: ${s.pallets_count || "—"}`,
    ]).flat(),
    `Примечание: ${val("sdNotes") || "—"}`,
  ];
  const text = lines.join("\n");

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      const info = document.getElementById("sdInfo");
      if (info) {
        info.textContent = "Скопировано";
        info.style.color = "#16a34a";
        setTimeout(() => { if (info.textContent === "Скопировано") info.textContent = ""; }, 2000);
      }
    }).catch(() => _copyFallback(text));
  } else {
    _copyFallback(text);
  }
}

function _copyFallback(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  try { document.execCommand("copy"); } catch (_) {}
  document.body.removeChild(ta);
  const info = document.getElementById("sdInfo");
  if (info) { info.textContent = "Скопировано"; info.style.color = "#16a34a";
    setTimeout(() => { if (info.textContent === "Скопировано") info.textContent = ""; }, 2000); }
}

function closeSupplyDetailsModal() {
  const modal = document.getElementById("supplyDetailsModal");
  if (modal) { modal.classList.add("hidden"); modal.setAttribute("aria-hidden", "true"); }
  _supplyDetailsCurrentId = null;
}

async function saveSupplyManualFields() {
  if (!_supplyDetailsCurrentId) return;
  const btn = document.getElementById("sdSaveBtn");
  const info = document.getElementById("sdInfo");
  const notes = document.getElementById("sdNotes")?.value.trim() || null;
  const production = document.getElementById("sdProduction")?.value || null;

  // Read all slots
  const slots = _sdGetSlots();
  const first = slots[0] || {};
  const passNumber = first.pass_number || null;
  const palletsCount = first.pallets_count || null;
  const driverName = first.driver_name || null;
  const driversJson = slots.length > 0 ? JSON.stringify(slots) : null;

  if (btn) { btn.disabled = true; btn.textContent = "Сохранение…"; }
  const res = await fetch(`/api/supplies/${_supplyDetailsCurrentId}/manual-fields`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify({ pass_number: passNumber, pallets_count: palletsCount, driver_name: driverName, notes, production, drivers_json: driversJson }),
  }).catch(() => null);
  if (btn) { btn.disabled = false; btn.textContent = "Сохранить"; }

  if (!res || !res.ok) {
    const err = await res?.json().catch(() => ({})) || {};
    if (info) { info.textContent = err.detail || "Ошибка сохранения"; info.style.color = "#b91c1c"; }
    return;
  }
  // Update local state so reopening the modal shows fresh values
  const item = suppliesState.items.find((x) => x.supply_id === _supplyDetailsCurrentId);
  if (item) {
    item.pass_number   = passNumber;
    item.pallets_count = palletsCount;
    item.driver_name   = driverName;
    item.notes         = notes;
    item.production    = production;
    item.drivers_json  = driversJson;
  }
  // Re-render table so columns (Производство, etc.) update immediately
  renderSuppliesTable();
  // Close modal after successful save
  closeSupplyDetailsModal();
}

// ── Supply warehouses ──
let _supplyWarehousesCache = [];

async function loadSupplyWarehouses() {
  const res = await fetch("/api/supply-warehouses").catch(() => null);
  if (!res || !res.ok) return;
  _supplyWarehousesCache = await res.json().catch(() => []);
  renderSupplyWarehousesTbody();
}

function renderSupplyWarehousesTbody() {
  const tbody = document.getElementById("supplyWarehousesTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!_supplyWarehousesCache.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">Склады не добавлены</td></tr>';
    return;
  }
  _supplyWarehousesCache.forEach((w, i) => {
    const tr = document.createElement("tr");
    tr.dataset.id = w.id;
    tr.innerHTML = `<td>${i+1}</td><td class="editable-cell">${esc(w.warehouse_name||"")}</td><td class="editable-cell">${esc(w.address||"")}</td>
      <td>
        <div class="row" style="gap:4px;flex-wrap:nowrap">
          <button class="secondary small-btn icon-btn" onclick="startEditWarehouse(${w.id})" title="Редактировать">✏</button>
          <button class="secondary small-btn icon-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="deleteSupplyWarehouse(${w.id})" title="Удалить">🗑</button>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });
}

async function startEditWarehouse(id) {
  const item = _supplyWarehousesCache.find((x) => x.id === id);
  if (!item) return;
  const tr = document.querySelector(`#supplyWarehousesTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const cells = tr.querySelectorAll(".editable-cell");
  cells[0].innerHTML = `<input class="edit-inline-input" value="${esc(item.warehouse_name||"")}" />`;
  cells[1].innerHTML = `<input class="edit-inline-input" value="${esc(item.address||"")}" />`;
  const actionCell = tr.cells[tr.cells.length - 1];
  actionCell.innerHTML = `<div class="row" style="gap:4px;flex-wrap:nowrap">
    <button class="secondary small-btn" style="color:#16a34a;border-color:#86efac" onclick="saveEditWarehouse(${id})">Сохранить</button>
    <button class="secondary small-btn" onclick="loadSupplyWarehouses()">Отмена</button>
  </div>`;
}

async function saveEditWarehouse(id) {
  const tr = document.querySelector(`#supplyWarehousesTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const inputs = tr.querySelectorAll(".edit-inline-input");
  const name = inputs[0]?.value.trim() || "";
  const addr = inputs[1]?.value.trim() || "";
  if (!name) return;
  await fetch(`/api/supply-warehouses/${id}`, { method: "PATCH", headers: jsonHeaders(), body: JSON.stringify({ warehouse_name: name, address: addr }) }).catch(() => null);
  await loadSupplyWarehouses();
}

function toggleAddWarehouseForm(show) {
  const form = document.getElementById("addWarehouseForm");
  if (!form) return;
  form.classList.toggle("hidden", !show); form.style.display = show ? "" : "none";
  if (!show) { document.getElementById("newWarehouseName").value = ""; document.getElementById("newWarehouseAddress").value = ""; }
}

async function saveSupplyWarehouse() {
  const name = document.getElementById("newWarehouseName")?.value.trim();
  const addr = document.getElementById("newWarehouseAddress")?.value.trim() || "";
  const info = document.getElementById("addWarehouseInfo");
  if (!name) { if (info) { info.textContent = "Введите название"; info.style.color = "#b91c1c"; } return; }
  const res = await fetch("/api/supply-warehouses", { method: "POST", headers: jsonHeaders(), body: JSON.stringify({ warehouse_name: name, address: addr }) }).catch(() => null);
  if (!res || !res.ok) { const e = await res?.json().catch(()=>({})) || {}; if (info) { info.textContent = e.detail||"Ошибка"; info.style.color = "#b91c1c"; } return; }
  if (info) { info.textContent = "Сохранено"; info.style.color = "#16a34a"; }
  toggleAddWarehouseForm(false);
  await loadSupplyWarehouses();
}

async function deleteSupplyWarehouse(id) {
  if (!confirm("Удалить склад?")) return;
  await fetch(`/api/supply-warehouses/${id}`, { method: "DELETE", headers: jsonHeaders() }).catch(() => null);
  await loadSupplyWarehouses();
}

// ── Supply legal entities ──
let _supplyLegalEntitiesCache = [];

async function loadSupplyLegalEntities() {
  const res = await fetch("/api/supply-legal-entities").catch(() => null);
  if (!res || !res.ok) return;
  _supplyLegalEntitiesCache = await res.json().catch(() => []);
  renderSupplyLegalEntitiesTbody();
}

function renderSupplyLegalEntitiesTbody() {
  const tbody = document.getElementById("supplyLegalEntitiesTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!_supplyLegalEntitiesCache.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-cell">Юридические лица не добавлены</td></tr>';
    return;
  }
  _supplyLegalEntitiesCache.forEach((e, i) => {
    const tr = document.createElement("tr");
    tr.dataset.id = e.id;
    tr.innerHTML = `<td>${i+1}</td><td class="editable-cell">${esc(e.short_name||"")}</td><td class="editable-cell">${esc(e.full_name||"")}</td><td class="editable-cell">${esc(e.requisites||"")}</td><td class="editable-cell">${esc(e.signatories||"")}</td><td class="editable-cell">${esc(e.in_person||"")}</td><td class="editable-cell">${esc(e.basis||"")}</td>
      <td>
        <div class="row" style="gap:4px;flex-wrap:nowrap">
          <button class="secondary small-btn" onclick="startEditLegalEntity(${e.id})">✏</button>
          <button class="secondary small-btn icon-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="deleteSupplyLegalEntity(${e.id})" title="Удалить">🗑</button>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });
}

async function startEditLegalEntity(id) {
  const item = _supplyLegalEntitiesCache.find((x) => x.id === id);
  if (!item) return;
  const tr = document.querySelector(`#supplyLegalEntitiesTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const cells = tr.querySelectorAll(".editable-cell");
  cells[0].innerHTML = `<input class="edit-inline-input" value="${esc(item.short_name||"")}" />`;
  cells[1].innerHTML = `<input class="edit-inline-input" value="${esc(item.full_name||"")}" />`;
  cells[2].innerHTML = `<input class="edit-inline-input" value="${esc(item.requisites||"")}" />`;
  cells[3].innerHTML = `<input class="edit-inline-input" value="${esc(item.signatories||"")}" />`;
  cells[4].innerHTML = `<input class="edit-inline-input" value="${esc(item.in_person||"")}" />`;
  cells[5].innerHTML = `<input class="edit-inline-input" value="${esc(item.basis||"")}" />`;
  // Insert a sub-row for signature upload below the edit row
  const sigRow = document.createElement("tr");
  sigRow.id = `le-sig-row-${id}`;
  sigRow.style.background = "#f8fafc";
  sigRow.innerHTML = `<td colspan="8" style="padding:4px 8px;border-top:none">
    <div style="display:flex;align-items:center;gap:8px">
      <span class="small" style="color:#64748b">Подпись:</span>
      <span id="le-sig-container-${id}"><span class="small" style="color:#94a3b8">Загрузка…</span></span>
    </div>
  </td>`;
  tr.after(sigRow);
  loadEditLegalSig(id);

  const actionCell = tr.cells[tr.cells.length - 1];
  actionCell.innerHTML = `<div class="row" style="gap:4px;flex-wrap:nowrap">
    <button class="secondary small-btn" style="color:#16a34a;border-color:#86efac" onclick="saveEditLegalEntity(${id})">Сохранить</button>
    <button class="secondary small-btn" onclick="loadSupplyLegalEntities()">Отмена</button>
  </div>`;
}

async function saveEditLegalEntity(id) {
  const tr = document.querySelector(`#supplyLegalEntitiesTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const inputs = tr.querySelectorAll(".edit-inline-input");
  const short = inputs[0]?.value.trim() || "";
  const full = inputs[1]?.value.trim() || "";
  const req = inputs[2]?.value.trim() || "";
  const sig = inputs[3]?.value.trim() || "";
  const inp = inputs[4]?.value.trim() || "";
  const bas = inputs[5]?.value.trim() || "";
  if (!short) return;
  const sigPayload = { short_name: short, full_name: full, requisites: req, signatories: sig, in_person: inp, basis: bas };
  if (_editLegalSigClear) { sigPayload.clear_signature = true; }
  else if (_editLegalSigBase64) { sigPayload.signature_image = _editLegalSigBase64; }
  const saveRes = await fetch(`/api/supply-legal-entities/${id}`, { method: "PATCH", headers: jsonHeaders(), body: JSON.stringify(sigPayload) }).catch(() => null);
  if (!saveRes || !saveRes.ok) {
    const errData = await saveRes?.json().catch(() => ({})) || {};
    alert("Ошибка сохранения: " + (errData.detail || (saveRes ? saveRes.status : "сеть")));
    return;
  }
  _editLegalSigBase64 = null;
  _editLegalSigClear = false;
  await loadSupplyLegalEntities();
}

function toggleAddLegalEntityForm(show) {
  const form = document.getElementById("addLegalEntityForm");
  if (!form) return;
  form.classList.toggle("hidden", !show); form.style.display = show ? "" : "none";
  if (!show) {
    ["newLegalShortName","newLegalFullName","newLegalRequisites","newLegalSignatories","newLegalInPerson","newLegalBasis"].forEach((id) => { const el = document.getElementById(id); if(el) el.value=""; });
  }
}

async function saveSupplyLegalEntity() {
  const short = document.getElementById("newLegalShortName")?.value.trim();
  const full = document.getElementById("newLegalFullName")?.value.trim() || "";
  const req = document.getElementById("newLegalRequisites")?.value.trim() || "";
  const sig = document.getElementById("newLegalSignatories")?.value.trim() || "";
  const inp = document.getElementById("newLegalInPerson")?.value.trim() || "";
  const bas = document.getElementById("newLegalBasis")?.value.trim() || "";
  const info = document.getElementById("addLegalEntityInfo");
  if (!short) { if (info) { info.textContent = "Введите короткое название"; info.style.color = "#b91c1c"; } return; }
  const newSigPayload = { short_name: short, full_name: full, requisites: req, signatories: sig, in_person: inp, basis: bas };
  if (_newLegalSigBase64) newSigPayload.signature_image = _newLegalSigBase64;
  const res = await fetch("/api/supply-legal-entities", { method: "POST", headers: jsonHeaders(), body: JSON.stringify(newSigPayload) }).catch(() => null);
  if (!res || !res.ok) { const e = await res?.json().catch(()=>({})) || {}; if (info) { info.textContent = e.detail||"Ошибка"; info.style.color = "#b91c1c"; } return; }
  if (info) { info.textContent = "Сохранено"; info.style.color = "#16a34a"; }
  _newLegalSigBase64 = null;
  toggleAddLegalEntityForm(false);
  await loadSupplyLegalEntities();
}

async function deleteSupplyLegalEntity(id) {
  if (!confirm("Удалить юридическое лицо?")) return;
  await fetch(`/api/supply-legal-entities/${id}`, { method: "DELETE", headers: jsonHeaders() }).catch(() => null);
  await loadSupplyLegalEntities();
}

// ── Legal entity signature handling ────────────────────────────────────────
let _newLegalSigBase64 = null;  // pending signature for create form
let _editLegalSigBase64 = null; // pending new signature for edit
let _editLegalSigClear = false; // flag to clear existing signature on save

function _fileToBase64(file) {
  // Resize to max 400×200 to keep base64 small (~20-40 KB)
  return new Promise((res, rej) => {
    if (file.size > 5 * 1024 * 1024) { rej(new Error("Файл слишком большой (максимум 5 МБ)")); return; }
    const reader = new FileReader();
    reader.onerror = rej;
    reader.onload = (evt) => {
      const img = new Image();
      img.onerror = rej;
      img.onload = () => {
        const MAX_W = 400, MAX_H = 200;
        let w = img.width, h = img.height;
        if (w > MAX_W) { h = Math.round(h * MAX_W / w); w = MAX_W; }
        if (h > MAX_H) { w = Math.round(w * MAX_H / h); h = MAX_H; }
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        canvas.getContext("2d").drawImage(img, 0, 0, w, h);
        res(canvas.toDataURL("image/png"));
      };
      img.src = evt.target.result;
    };
    reader.readAsDataURL(file);
  });
}

// Create form
async function onNewLegalSigSelected(input) {
  const file = input.files?.[0];
  if (!file) return;
  try {
    _newLegalSigBase64 = await _fileToBase64(file);
    document.getElementById("newLegalSigArea").style.display = "none";
    const prev = document.getElementById("newLegalSigPreview");
    prev.style.display = "flex";
    document.getElementById("newLegalSigImg").src = _newLegalSigBase64;
  } catch(e) { alert(e.message); }
}

function clearNewLegalSig() {
  _newLegalSigBase64 = null;
  document.getElementById("newLegalSigArea").style.display = "";
  const prev = document.getElementById("newLegalSigPreview");
  prev.style.display = "none";
  const inp = document.getElementById("newLegalSigFile");
  if (inp) inp.value = "";
}

// Edit inline — load existing signature
async function loadEditLegalSig(entityId) {
  _editLegalSigBase64 = null;
  _editLegalSigClear = false;
  const res = await fetch(`/api/supply-legal-entities/${entityId}/signature`).catch((e)=>{
    console.error("[sig] fetch error:", e); return null;
  });
  console.log("[sig] entityId:", entityId, "status:", res?.status, "ok:", res?.ok);
  let data = {};
  if (res && res.ok) {
    try { data = await res.json(); } catch(e) { console.error("[sig] json parse error:", e); }
  } else if (res) {
    const txt = await res.text().catch(()=>"");
    console.warn("[sig] non-ok response:", res.status, txt.slice(0,200));
  }
  console.log("[sig] data:", data?.signature_image ? "HAS_IMAGE len="+data.signature_image.length : "NO_IMAGE");
  const existing = data.signature_image || null;
  _renderEditLegalSigUI(existing, entityId);
}

function _renderEditLegalSigUI(existingBase64, entityId) {
  const container = document.getElementById(`le-sig-container-${entityId}`);
  if (!container) return;
  if (existingBase64 && !_editLegalSigClear) {
    container.innerHTML = `
      <span style="color:#16a34a;font-size:15px">✓</span>
      <img src="${existingBase64}" style="height:32px;border:1px solid #e2e8f0;border-radius:4px;margin:0 6px" />
      <button type="button" class="secondary small-btn icon-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="deleteEditLegalSig(${entityId})" title="Удалить подпись">×</button>`;
  } else if (_editLegalSigBase64) {
    container.innerHTML = `
      <span style="color:#16a34a;font-size:15px">✓</span>
      <img src="${_editLegalSigBase64}" style="height:32px;border:1px solid #e2e8f0;border-radius:4px;margin:0 6px" />
      <button type="button" class="secondary small-btn icon-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="clearEditLegalSigNew(${entityId})" title="Отменить">×</button>`;
  } else {
    container.innerHTML = `<label style="cursor:pointer">
      <span class="secondary" style="display:inline-block;padding:3px 8px;border:1px solid #cbd5e1;border-radius:6px;font-size:12px;background:#f8fafc">📎 Загрузить</span>
      <input type="file" accept="image/*" style="display:none" onchange="onEditLegalSigSelected(this, ${entityId})" />
    </label>`;
  }
}

async function onEditLegalSigSelected(input, entityId) {
  const file = input.files?.[0];
  if (!file) return;
  try {
    _editLegalSigBase64 = await _fileToBase64(file);
    _editLegalSigClear = false;
    _renderEditLegalSigUI(null, entityId);
  } catch(e) { alert(e.message); }
}

async function deleteEditLegalSig(entityId) {
  if (!confirm("Удалить подпись? Изменение применится при нажатии «Сохранить»")) return;
  _editLegalSigClear = true;
  _editLegalSigBase64 = null;
  _renderEditLegalSigUI(null, entityId);
}

function clearEditLegalSigNew(entityId) {
  _editLegalSigBase64 = null;
  _editLegalSigClear = false;
  _renderEditLegalSigUI(null, entityId);
}

window.onNewLegalSigSelected = onNewLegalSigSelected;
window.clearNewLegalSig = clearNewLegalSig;
window.deleteEditLegalSig = deleteEditLegalSig;
window.clearEditLegalSigNew = clearEditLegalSigNew;
window.onEditLegalSigSelected = onEditLegalSigSelected;

// ── Packing list (Word docx via HTML) ──
function downloadPackingList(supplyId) {
  const item = suppliesState.items.find((x) => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;

  // Resolve data
  const passNumber = item.pass_number || "";
  const supplierName = item.supplier_name || "";
  const palletsCount = item.pallets_count || "";
  const boxTypeLabel = SUPPLY_BOX_TYPE_LABELS[item.box_type_id] || "";
  const destWarehouse = (item.warehouse_name || "").trim();
  const transitWarehouse = (item.transit_warehouse_name || "").trim();
  const supplyDateRaw = item.supply_date || "";
  let dateDisplay = "";
  if (supplyDateRaw) {
    try { dateDisplay = new Date(supplyDateRaw).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" }); } catch (_) {}
  }

  // Warehouse address lookup
  const whMap = Object.fromEntries(_supplyWarehousesCache.map((w) => [w.warehouse_name, w.address]));
  // Transit: "Склад" = address of transit warehouse (before arrow), "Склад назначения" = address of destination
  let whForPickup, whForDest;
  if (transitWarehouse) {
    whForPickup = whMap[transitWarehouse] || transitWarehouse;
    whForDest = whMap[destWarehouse] || destWarehouse;
  } else {
    whForPickup = whMap[destWarehouse] || destWarehouse;
    whForDest = whForPickup;
  }

  // Legal entity full name
  const leMap = Object.fromEntries(_supplyLegalEntitiesCache.map((e) => [e.short_name, e.full_name]));
  const fullLegalName = leMap[supplierName] || supplierName;

  // Barcode cell is left empty — user will paste the barcode label (58×40mm) manually
  const barcodeImgTag = "";

  // Build HTML for Word
  const html = `
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8">
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View></w:WordDocument></xml><![endif]-->
<style>
  @page { size: 210mm 297mm; margin: 20mm 15mm 20mm 25mm; }
  body { font-family: "Times New Roman", serif; font-size: 12pt; }
  h1 { text-align: center; font-size: 13pt; font-weight: bold; margin: 0 0 4pt; }
  h2 { text-align: center; font-size: 22pt; font-weight: bold; margin: 12pt 0 8pt; text-transform: uppercase; }
  table { width: 100%; border-collapse: collapse; margin-top: 8pt; }
  td { border: 1px solid #000; padding: 6pt 8pt; vertical-align: middle; font-size: 11pt; }
  .label-col { width: 40%; }
  .barcode-cell { height: 120pt; min-height: 120pt; text-align: center; vertical-align: middle; width: 60%; }
</style>
</head>
<body>
<h1>Упаковочный лист ${esc(supplierName)}</h1>
<h1>(поставка №${esc(item.supply_id || "")}, ${esc(passNumber)})</h1>
<h2>${esc(boxTypeLabel)}</h2>
<table>
  <tr><td class="label-col">Порядковый номер паллеты</td><td></td></tr>
  <tr><td>Количество паллет</td><td>${esc(palletsCount)}</td></tr>
  <tr><td>Количество коробок на паллете</td><td></td></tr>
  <tr><td>Склад</td><td>${esc(whForPickup)}</td></tr>
  <tr><td>Склад назначения</td><td>${esc(whForDest)}</td></tr>
  <tr><td>Тип поставки</td><td><b>${esc(boxTypeLabel)}</b></td></tr>
  <tr><td>Наименование юридического лица</td><td>${esc(fullLegalName)}</td></tr>
  <tr><td>Дата поставки</td><td>${esc(dateDisplay)}</td></tr>
  <tr><td>Штрих-код поставки</td><td class="barcode-cell">${barcodeImgTag}</td></tr>
</table>
</body></html>`;

  const blob = new Blob(["\uFEFF" + html], { type: "application/msword" });
  const url = URL.createObjectURL(blob);
  const fn = [passNumber, dateDisplay.replace(/\./g,""), destWarehouse, item.quantity != null ? `${item.quantity} шт.` : ""].filter(Boolean).join(", ");
  const win = window.open("", "_blank");
  if (win) {
    const a = win.document.createElement("a");
    a.href = url; a.download = `Упаковочный лист ${fn}.doc`;
    win.document.body.appendChild(a); a.click();
    setTimeout(() => { try { win.close(); } catch(_){} URL.revokeObjectURL(url); }, 1500);
  } else {
    const a = document.createElement("a");
    a.href = url; a.download = `Упаковочный лист ${fn}.doc`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}

// ── Power of Attorney (Доверенность М-2) ──

function _getPoaSequenceNumber() {
  const today = new Date().toISOString().slice(0, 10);
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem("poa_counter") || "{}"); } catch (_) {}
  const count = (stored.date === today ? (stored.count || 0) : 0) + 1;
  try { localStorage.setItem("poa_counter", JSON.stringify({ date: today, count })); } catch (_) {}
  return count;
}

function _numToRussianWords(n) {
  n = parseInt(n) || 0;
  if (n <= 0) return "ноль";
  const ones = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"];
  const teens = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
    "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"];
  const tens = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"];
  const hundreds = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"];
  let result = "";
  if (n >= 100) { result += hundreds[Math.floor(n / 100)] + " "; n %= 100; }
  if (n >= 10 && n <= 19) return (result + teens[n - 10]).trim();
  if (n >= 20) { result += tens[Math.floor(n / 10)] + " "; n %= 10; }
  if (n > 0) result += ones[n];
  return result.trim();
}

async function downloadPoA(supplyId) {
  const item = suppliesState.items.find((x) => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;

  // 1. PoA number = supply ID (not sequential counter)
  const seqNum = String(item.supply_id || "");

  // Current date
  const now = new Date();
  const dd = String(now.getDate()).padStart(2, "0");
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const yyyy = now.getFullYear();
  const dateDisplay = `${dd}.${mm}.${yyyy}`;
  const dateNoSep = `${dd}${mm}${yyyy}`;

  // Legal entity lookup by supplier_name (short_name)
  const supplierShort = item.supplier_name || "";
  const le = _supplyLegalEntitiesCache.find((e) => e.short_name === supplierShort) || {};
  const orgFull = le.full_name || supplierShort;
  const orgReq = le.requisites || "";
  const orgLine = [orgFull, orgReq].filter(Boolean).join(", ");

  // Driver lookup — support manual (temporary) driver via _manual_driver_docs
  const driverName = item.driver_name || "";
  const driverObj = _supplyDriversCache.find((d) => d.full_name === driverName) || {};
  const driverDocs = item._manual_driver_docs !== undefined ? item._manual_driver_docs : (driverObj.documents || "");

  // Pallets (kept for fallback)
  const palletsRaw = parseInt(item.pallets_count) || 0;

  // 2. Fetch real goods for the goods table
  let poaGoods = [];
  try {
    const gr = await fetch(`/api/supplies/${supplyId}/goods`).catch(()=>null);
    if (gr && gr.ok) poaGoods = await gr.json().catch(()=>[]);
  } catch(_) {}
  if (!poaGoods.length) poaGoods = [{ product_name: "Текстильные товары", vendor_code: "", quantity: palletsRaw }];

  const html = `
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"
  xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8">
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View></w:WordDocument></xml><![endif]-->
<style>
  @page { size: 210mm 297mm; margin: 15mm 10mm 15mm 25mm; }
  body { font-family: "Times New Roman", serif; font-size: 11pt; line-height: 1.4; }
  .small { font-size: 8pt; text-align: center; }
  .underline { text-decoration: underline; }
  .center { text-align: center; }
  .right { text-align: right; }
  .bold { font-weight: bold; }
  table.outer { width: 100%; border-collapse: collapse; margin-bottom: 8pt; }
  table.codes { border-collapse: collapse; margin-left: auto; font-size: 9pt; }
  table.codes td { border: 1px solid #000; padding: 2pt 6pt; }
  table.mat { width: 100%; border-collapse: collapse; margin-top: 6pt; font-size: 10pt; }
  table.mat td, table.mat th { border: 1px solid #000; padding: 3pt 5pt; text-align: center; }
  .sig-row { width: 100%; margin-top: 10pt; }
  .dotline { display: inline-block; border-bottom: 1px solid #000; min-width: 120pt; }
  p { margin: 3pt 0; }
</style>
</head>
<body>

<!-- Header: org left, form codes right -->
<table class="outer">
  <tr>
    <td style="width:55%;vertical-align:top;font-size:11pt">
      Организация <span class="underline">${esc(orgFull)}</span>
    </td>
    <td style="width:45%;vertical-align:top;text-align:right;font-size:8pt">
      Типовая межотраслевая форма № М-2<br>
      Утверждена постановлением Госстата России от 30.10.97 № 71а<br><br>
      <table class="codes">
        <tr><td colspan="2" class="bold center">Коды</td></tr>
        <tr><td>Форма по ОКУД</td><td>0315001</td></tr>
        <tr><td>по ОКПО</td><td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td></tr>
      </table>
    </td>
  </tr>
</table>

<p style="text-align:center;font-size:14pt;font-weight:bold;margin:10pt 0 4pt"><b>Доверенность № ${seqNum}</b></p>

<p>Дата выдачи <span class="underline bold">${dateDisplay}</span></p>
<p>Доверенность действительна 14 дней с даты подписания.</p>
<p style="margin-top:6pt">${esc(orgLine)}</p>
<p class="small">наименование потребителя и его адрес</p>
<p style="margin-top:4pt">${esc(orgLine)}</p>
<p class="small">наименование плательщика и его адрес</p>

<p style="margin-top:8pt">
  Доверенность выдана &nbsp;&nbsp;
  <span class="underline" style="min-width:60pt;display:inline-block">водителю</span>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <span class="underline">${esc(driverName)}</span>
</p>
<p class="small" style="padding-left:120pt">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; фамилия, имя, отчество</p>

${driverDocs ? `<p>${esc(driverDocs)}</p>` : ""}

<p style="margin-top:6pt">
  На отправку груза от &nbsp;&nbsp;
  <span class="underline">&nbsp;&nbsp;&nbsp;&nbsp;${esc(supplierShort)}&nbsp;&nbsp;&nbsp;&nbsp;</span>
</p>
<p class="small" style="text-align:center">наименование поставщика</p>

<p style="margin-top:4pt">
  материальных ценностей по транспортной накладной &nbsp;
  <span class="underline bold">${seqNum}</span>
  &nbsp; от &nbsp;
  <span class="underline bold">${dateDisplay}</span>
</p>
<p class="small">наименование, номер и дата документа</p>

<p style="margin-top:10pt">Перечень материальных ценностей, подлежащих доставке</p>
<table class="mat">
  <tr>
    <th style="width:8%">Номер по порядку</th>
    <th style="width:44%">Материальные ценности</th>
    <th style="width:16%">Единица измерения</th>
    <th style="width:32%">Количество</th>
  </tr>
  ${poaGoods.map((g, i) => `<tr>
    <td>${i+1}</td>
    <td>${esc(g.product_name || g.vendor_code || "Товар")}</td>
    <td>шт.</td>
    <td>${g.quantity ?? "—"}</td>
  </tr>`).join("")}
</table>

<p style="margin-top:18pt">
  Подпись лица, получившего доверенность удостоверяем.
  &nbsp;&nbsp;&nbsp;&nbsp;
  <span class="dotline">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>
  &nbsp;&nbsp;
  (${esc(driverName)})
</p>

<table style="width:100%;margin-top:18pt;border-collapse:collapse">
  <tr>
    <td style="width:25%;vertical-align:bottom">Руководитель<br><span style="font-size:8pt">М.П.</span></td>
    <td style="width:30%;vertical-align:bottom;text-align:center">
      <span class="dotline">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span><br>
      <span class="small">подпись</span>
    </td>
    <td style="width:45%;vertical-align:bottom;text-align:center">
      (${esc(le.signatories || supplierShort)})<br>
      <span class="small">расшифровка подписи</span>
    </td>
  </tr>
</table>

<table style="width:100%;margin-top:14pt;border-collapse:collapse">
  <tr>
    <td style="width:25%;vertical-align:bottom">Главный бухгалтер</td>
    <td style="width:30%;vertical-align:bottom;text-align:center">
      <span class="dotline">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span><br>
      <span class="small">подпись</span>
    </td>
    <td style="width:45%;vertical-align:bottom;text-align:center">
      (${esc(le.signatories || supplierShort)})<br>
      <span class="small">расшифровка подписи</span>
    </td>
  </tr>
</table>

</body></html>`;

  const blob = new Blob(["\uFEFF" + html], { type: "application/msword" });
  const url = URL.createObjectURL(blob);
  const supplyDateDisp = item.supply_date
    ? new Date(item.supply_date).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
    : dateDisplay;
  const destWh = (item.warehouse_name || "").trim();
  const poaFileName = `Доверенность №${seqNum}, ${supplierShort} от ${supplyDateDisp}, ${destWh}, ${driverName}.doc`;
  const winPoa = window.open("", "_blank");
  if (winPoa) {
    const a = winPoa.document.createElement("a");
    a.href = url; a.download = poaFileName;
    winPoa.document.body.appendChild(a); a.click();
    setTimeout(() => { try { winPoa.close(); } catch(_){} URL.revokeObjectURL(url); }, 1500);
  } else {
    const a = document.createElement("a");
    a.href = url; a.download = poaFileName; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}

// ── TTN (ТОРГ-12) ──

function _rublesInWords(amount) {
  if (!amount || amount <= 0) return "ноль рублей 00 коп";
  const ones1 = ["","один","два","три","четыре","пять","шесть","семь","восемь","девять"];
  const ones2 = ["","одна","две","три","четыре","пять","шесть","семь","восемь","девять"]; // feminine for тысяча
  const teens = ["десять","одиннадцать","двенадцать","тринадцать","четырнадцать","пятнадцать","шестнадцать","семнадцать","восемнадцать","девятнадцать"];
  const tens = ["","","двадцать","тридцать","сорок","пятьдесят","шестьдесят","семьдесят","восемьдесят","девяносто"];
  const hundreds = ["","сто","двести","триста","четыреста","пятьсот","шестьсот","семьсот","восемьсот","девятьсот"];

  function threeDigits(n, feminine) {
    let r = "";
    if (n >= 100) { r += hundreds[Math.floor(n/100)] + " "; n %= 100; }
    if (n >= 10 && n <= 19) { r += teens[n-10]; return r.trim(); }
    if (n >= 20) { r += tens[Math.floor(n/10)] + " "; n %= 10; }
    if (n > 0) r += (feminine ? ones2[n] : ones1[n]);
    return r.trim();
  }
  function millionWord(n) {
    const last2 = n % 100; const last1 = n % 10;
    if (last2 >= 11 && last2 <= 19) return "миллионов";
    if (last1 === 1) return "миллион";
    if (last1 >= 2 && last1 <= 4) return "миллиона";
    return "миллионов";
  }
  function thousandWord(n) {
    const last2 = n % 100; const last1 = n % 10;
    if (last2 >= 11 && last2 <= 19) return "тысяч";
    if (last1 === 1) return "тысяча";
    if (last1 >= 2 && last1 <= 4) return "тысячи";
    return "тысяч";
  }

  let parts = [];
  const mil = Math.floor(amount / 1000000);
  const tho = Math.floor((amount % 1000000) / 1000);
  const rem = amount % 1000;
  if (mil > 0) parts.push(threeDigits(mil, false) + " " + millionWord(mil));
  if (tho > 0) parts.push(threeDigits(tho, true) + " " + thousandWord(tho));
  if (rem > 0) parts.push(threeDigits(rem, false));
  return parts.join(" ") + " рублей 00 коп";
}

async function downloadTTN(supplyId) {
  if (typeof JSZip === "undefined") { alert("JSZip не загружен. Перезагрузите страницу."); return; }
  const item = suppliesState.items.find((x) => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;

  // Ensure legal entities cache is loaded
  if (!_supplyLegalEntitiesCache.length) await loadSupplyLegalEntities();

  const now = new Date();
  const dd = String(now.getDate()).padStart(2,"0"), mm = String(now.getMonth()+1).padStart(2,"0"), yyyy = now.getFullYear();
  const dateDisp = `${dd}.${mm}.${yyyy}`;

  const supplierShort = item.supplier_name || "";
  // Match by short_name, fallback to first legal entity, then to WB supplier name
  const le = _supplyLegalEntitiesCache.find((e) => e.short_name === supplierShort)
          || _supplyLegalEntitiesCache[0]
          || {};
  const orgFull = le.full_name || supplierShort;
  const orgReq  = le.requisites || "";
  const orgLine = [orgFull, orgReq].filter(Boolean).join(", ");

  const destWh  = (item.warehouse_name || "").trim();
  const whMap   = Object.fromEntries(_supplyWarehousesCache.map((w) => [w.warehouse_name, w.address]));
  const whAddr  = whMap[destWh] || "";
  const recipientLine = [destWh, whAddr].filter(Boolean).join(", ");

  const driverName = item.driver_name || "";
  const pallets    = parseInt(item.pallets_count) || 0;
  const palletsWord = _numToRussianWords(pallets);
  const totalAmount = pallets * 100000;
  const am = totalAmount.toLocaleString("ru-RU");
  const amountWords = _rublesInWords(totalAmount);
  const supplyId_ = String(item.supply_id || "");

  // Fetch actual goods list for this supply
  let goodsList = [];
  let goodsNames = [];
  try {
    const gr = await fetch(`/api/supplies/${supplyId_}/goods`).catch(() => null);
    if (gr && gr.ok) {
      goodsList = await gr.json().catch(() => []);
      goodsNames = goodsList.map(g => g.product_name || g.vendor_code || "Товар").filter(Boolean);
    }
  } catch(_) {}
  if (!goodsNames.length) goodsNames = [`Текстильные товары (${pallets} ${palletsWord})`];

  // Fetch prices (discountedPrice) keyed by nmID using same source token
  let nmPrices = {};
  try {
    const pr = await fetch(`/api/supplies/${supplyId_}/nm-prices`).catch(() => null);
    if (pr && pr.ok) { const pd = await pr.json().catch(() => ({})); nmPrices = pd.prices || {}; }
  } catch(_) {}

  const supplyDateDisp = item.supply_date
    ? new Date(item.supply_date).toLocaleDateString("ru-RU", { day:"2-digit", month:"2-digit", year:"numeric" })
    : dateDisp;


  // Fetch template and fill placeholders
  let tplData;
  try {
    const resp = await fetch("/static/torg12_tpl.docx");
    if (!resp.ok) throw new Error("template not found");
    tplData = await resp.arrayBuffer();
  } catch(e) {
    alert("Не удалось загрузить шаблон ТТН: " + e.message);
    return;
  }

  const zip = await JSZip.loadAsync(tplData);
  let docXml = await zip.file("word/document.xml").async("string");

  // Replace all placeholders with actual values
  const rpl = (xml, ph, val) => xml.split(ph).join(val.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"));

  docXml = rpl(docXml, "{{TTN_NUMBER}}", supplyId_);
  docXml = rpl(docXml, "{{ORG_FULL}}",   orgLine);
  docXml = rpl(docXml, "{{SUPPLIER}}",   orgLine);
  docXml = rpl(docXml, "{{PAYER}}",      orgLine);
  docXml = rpl(docXml, "{{ORDER_DATE}}",  supplyId_);
  docXml = rpl(docXml, "{{DOC_NUM_VAL}}",supplyId_);
  docXml = rpl(docXml, "{{DOC_DATE_VAL}}",dateDisp);
  // Duplicate data row for each good — substituting {{GOODS_NAME}} and {{PRICE}} per row
  const dataRowRx = /(<w:tr[\s>](?:(?!<\/w:tr>).)*?\{\{GOODS_NAME\}\}.*?<\/w:tr>)/s;
  const dataRowMatch = docXml.match(dataRowRx);
  const VAT_RATE = 0.22;
  // fmt helpers
  const fmt2 = (n) => Number(n).toLocaleString("ru-RU", {minimumFractionDigits:2, maximumFractionDigits:2});
  const esc_ = (s) => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  // Calculate total quantity from actual goods
  const totalGoodsQty = goodsList.reduce((s, g) => s + (parseInt(g.quantity) || 0), 0);
  const qtyTotal = totalGoodsQty || pallets;

  // Per-row amounts accumulator for totals
  let totalExcl = 0, totalVat = 0, totalIncl = 0;

  if (dataRowMatch) {
    const rowTpl = dataRowMatch[1];
    const multiRows = goodsList.map((g, rowIdx) => {
      const name = g.product_name || g.vendor_code || "Товар";
      const nm = String(g.nm_id || "");
      const qty = parseInt(g.quantity) || 0;
      // discountedPrice from WB is price WITH VAT (22% inclusive)
      const priceIncl = (nm && nmPrices[nm]) ? parseFloat(nmPrices[nm]) : null;
      // Price without VAT (Цена в ТОРГ-12 = без НДС)
      const priceExcl  = priceIncl != null ? priceIncl / (1 + VAT_RATE) : null;
      const rowAmtExcl = priceExcl  != null ? priceExcl  * qty : null;
      const rowVat     = rowAmtExcl != null ? rowAmtExcl * VAT_RATE : null;
      const rowAmtIncl = rowAmtExcl != null ? rowAmtExcl + rowVat : null;
      if (rowAmtExcl != null) { totalExcl += rowAmtExcl; totalVat += rowVat; totalIncl += rowAmtIncl; }
      return rowTpl
        .replace("{{ROW_NUM}}",         String(rowIdx + 1))
        .replace("{{GOODS_NAME}}",      esc_(name))
        .replace("{{PRICE}}",           esc_(priceExcl != null ? fmt2(priceExcl) : "—"))
        .split("{{ROW_QTY}}").join(String(qty))
        .replace("{{ROW_AMOUNT_EXCL}}", esc_(rowAmtExcl != null ? fmt2(rowAmtExcl) : "—"))
        .replace("{{ROW_VAT_SUM}}",     esc_(rowVat     != null ? fmt2(rowVat)     : "—"))
        .replace("{{ROW_AMOUNT_INCL}}", esc_(rowAmtIncl != null ? fmt2(rowAmtIncl) : "—"));
    }).join("") || rowTpl.replace("{{GOODS_NAME}}", esc_(goodsNames[0] || "Товар"));
    docXml = docXml.replace(rowTpl, multiRows);
  } else {
    docXml = rpl(docXml, "{{GOODS_NAME}}", goodsNames[0] || "Товар");
  }

  // Fallback replacements (in case no goods)
  docXml = docXml.split("{{ROW_NUM}}").join("1");
  docXml = docXml.split("{{ROW_QTY}}").join(String(qtyTotal));
  docXml = docXml.split("{{ROW_AMOUNT_EXCL}}").join("—");
  docXml = docXml.split("{{ROW_VAT_SUM}}").join("—");
  docXml = docXml.split("{{ROW_AMOUNT_INCL}}").join("—");
  docXml = docXml.split("{{PRICE}}").join("—");

  docXml = rpl(docXml, "{{QTY}}",       String(qtyTotal));
  docXml = rpl(docXml, "{{QTY_SHT}}",   `${qtyTotal} шт`);
  const fmtNum = (n) => fmt2(n);
  const totalExclFmt  = totalExcl  > 0 ? fmtNum(totalExcl)  : fmtNum(totalAmount);
  const totalVatFmt   = totalVat   > 0 ? fmtNum(totalVat)   : fmtNum(Math.round(totalAmount * VAT_RATE));
  const totalInclFmt  = totalIncl  > 0 ? fmtNum(totalIncl)  : fmtNum(totalAmount + Math.round(totalAmount * VAT_RATE));
  docXml = rpl(docXml, "{{TOTAL_EXCL}}", totalExclFmt);
  docXml = rpl(docXml, "{{TOTAL_VAT}}",  totalVatFmt);
  docXml = rpl(docXml, "{{TOTAL_INCL}}", totalInclFmt);
  // Legacy fallbacks
  docXml = rpl(docXml, "{{AMOUNT}}",          totalExclFmt);
  docXml = rpl(docXml, "{{VAT_SUM}}",         totalVatFmt);
  docXml = rpl(docXml, "{{AMOUNT_WITH_VAT}}", totalInclFmt);
  const finalTotalIncl = totalIncl > 0 ? totalIncl : (totalAmount + Math.round(totalAmount * VAT_RATE));
  docXml = rpl(docXml, "{{AMOUNT_WORDS}}",    _rublesInWords(Math.round(finalTotalIncl)));
  docXml = rpl(docXml, "{{PAGES_COUNT}}", "1");
  docXml = rpl(docXml, "{{ITEMS_COUNT}}", String(goodsList.length || goodsNames.length || 1));
  const _n = new Date();
  const _docDateFull = `«${String(_n.getDate()).padStart(2,"0")}» ${["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"][_n.getMonth()]} ${_n.getFullYear()}`;
  const _issuedBy = [le.full_name || supplierShort, le.requisites].filter(Boolean).join(", ");
  const _totalInclNum = totalIncl > 0 ? totalIncl : (totalAmount + Math.round(totalAmount * VAT_RATE));
  docXml = rpl(docXml, "{{TOTAL_RUB}}", String(Math.floor(_totalInclNum)));
  docXml = rpl(docXml, "{{TOTAL_KOP}}", String(Math.round((_totalInclNum % 1) * 100)).padStart(2,"0"));
  docXml = rpl(docXml, "{{SUPPLY_ID}}",      supplyId_);
  docXml = rpl(docXml, "{{DOC_DATE_FULL}}",  _docDateFull);
  docXml = rpl(docXml, "{{ISSUED_BY}}",      supplierShort || "—");
  docXml = rpl(docXml, "{{SIGNATORIES}}", le.signatories || supplierShort || "—");
  const _prodName = item.production || "";
  const _prodObj = _supplyProductionsCache.find(p => p.name === _prodName) || {};
  docXml = rpl(docXml, "{{PROD_HEAD}}", _prodObj.head_name || _prodName || "—");
  docXml = rpl(docXml, "{{SIGN_SUPPLIER}}",supplierShort);
  docXml = rpl(docXml, "{{SIGN_DRIVER}}", driverName);

  zip.file("word/document.xml", docXml);
  const blob = await zip.generateAsync({
    type: "blob",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  });

  const url = URL.createObjectURL(blob);
  const ttnQty = item.quantity != null ? item.quantity : pallets;
  const ttnFileName = `ТТН ${supplierShort} от ${supplyDateDisp}, ${destWh}, ${ttnQty} шт..docx`;
  const win = window.open("", "_blank");
  if (win) {
    const a = win.document.createElement("a");
    a.href = url; a.download = ttnFileName; win.document.body.appendChild(a); a.click();
    setTimeout(() => { try { win.close(); } catch(_){} URL.revokeObjectURL(url); }, 1500);
  } else {
    const a = document.createElement("a");
    a.href = url; a.download = ttnFileName; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}

// ── Supply barcode PDF ──

function _isWbGiCode(val) {
  return Boolean(val && /^WB-GI-\d+$/.test(String(val).trim()));
}

function downloadSupplyBarcode(passNumber, supplyId) {
  if (!_isWbGiCode(passNumber)) return;

  if (typeof JsBarcode === "undefined" || typeof window.jspdf === "undefined") {
    alert("Библиотеки для генерации штрихкода загружаются. Попробуйте через секунду.");
    return;
  }

  // Get supply data for filename and bottom label text
  const item = suppliesState.items.find((x) => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  const warehouseName = (item?.warehouse_name || "").trim();
  const quantity = item?.quantity != null ? `${item.quantity} шт` : "";
  const supplyDateRaw = item?.supply_date || "";
  let dateStr = "";
  if (supplyDateRaw) {
    try {
      const d = new Date(supplyDateRaw);
      const dd = String(d.getDate()).padStart(2, "0");
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const yyyy = d.getFullYear();
      dateStr = `${dd}${mm}${yyyy}`;
    } catch (_) {}
  }

  // Find driver from slot matching this passNumber
  let driverName = "";
  if (item) {
    const iSlots = _getItemSlots(supplyId);
    const slot = iSlots.find(s => s.pass_number === passNumber) || iSlots[0] || {};
    driverName = slot.effectiveDriverName || "";
  }

  // File name: "WB-GI-XXXXXXX, DDMMYYYY, Склад, N шт, Фамилия И."
  const dateStrDisplay = dateStr ? `${dateStr.slice(0,2)}.${dateStr.slice(2,4)}.${dateStr.slice(4)}` : "";
  const nameParts = [passNumber];
  if (dateStrDisplay) nameParts.push(dateStrDisplay);
  if (warehouseName) nameParts.push(warehouseName);
  if (quantity) nameParts.push(quantity);
  if (driverName) nameParts.push(_shortDriverName(driverName));
  const fileName = nameParts.join(", ");

  // Bottom label lines: date+warehouse+qty on first line, driver on second
  const bottomParts = [];
  if (dateStr) bottomParts.push(`${dateStr.slice(0,2)}.${dateStr.slice(2,4)}.${dateStr.slice(4)}`);
  if (warehouseName) bottomParts.push(warehouseName);
  if (quantity) bottomParts.push(quantity);
  const bottomLine1 = bottomParts.join("   ");
  const bottomText = driverName ? bottomLine1 + (bottomLine1 ? "\n" : "") + driverName : bottomLine1;

  // Render barcode to canvas — tall lines
  const canvas = document.createElement("canvas");
  try {
    JsBarcode(canvas, passNumber, {
      format: "CODE128",
      width: 3,
      height: 168,  // +20%
      displayValue: false,
      margin: 0,
      background: "#ffffff",
      lineColor: "#000000",
    });
  } catch (e) {
    alert("Ошибка генерации штрихкода: " + e.message);
    return;
  }

  const barcodeDataUrl = canvas.toDataURL("image/png");
  const barcodeAspect = canvas.height / canvas.width;

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: "landscape", unit: "mm", format: [40, 58] });

  const pageW = 58;
  const pageH = 40;
  const pad = 1.5;

  // Dashed border
  doc.setLineDashPattern([1.2, 0.8], 0);
  doc.setDrawColor(190, 190, 190);
  doc.setLineWidth(0.3);
  doc.rect(pad, pad, pageW - pad * 2, pageH - pad * 2);

  // Top: pass number — bold, orange (ASCII only, no Cyrillic issue)
  doc.setFont("helvetica", "bold");
  doc.setFontSize(9);
  doc.setTextColor(0, 0, 0);
  doc.text(passNumber, pageW / 2, pad + 5, { align: "center" });

  // Barcode: shifted down for more spacing after top text
  const barcodeX = pad + 1.5;
  const barcodeW = pageW - pad * 2 - 3;
  const barcodeH = Math.min(barcodeW * barcodeAspect, 23);  // +20%
  const barcodeY = pad + 8;  // more gap from top text
  doc.addImage(barcodeDataUrl, "PNG", barcodeX, barcodeY, barcodeW, barcodeH);

  // Bottom text: render Cyrillic via canvas (jsPDF default fonts don't support Russian)
  if (bottomText) {
    const bottomY = barcodeY + barcodeH + 2.5;
    const SCALE = 4;
    const fontSize = 9 * SCALE;
    const canvasW = Math.round((pageW - pad * 2 - 4) * SCALE * 3.78);
    const lineH = 12 * SCALE;
    const textCanvas = document.createElement("canvas");
    textCanvas.width = canvasW;
    textCanvas.height = 6 * lineH;
    const ctx = textCanvas.getContext("2d");
    ctx.font = `bold ${fontSize}px Arial`;
    // Split on explicit \n first, then word-wrap each segment
    const segments = bottomText.split("\n");
    const lines = [];
    for (const seg of segments) {
      const words = seg.split(/\s+/);
      let cur = "";
      for (const w of words) {
        const test = cur ? cur + " " + w : w;
        if (ctx.measureText(test).width > canvasW - 8 && cur) { lines.push(cur); cur = w; }
        else cur = test;
      }
      if (cur) lines.push(cur);
    }
    // Resize canvas to exact height needed
    textCanvas.height = lines.length * lineH + 4;
    ctx.clearRect(0, 0, canvasW, textCanvas.height);
    ctx.fillStyle = "rgb(0,0,0)";
    ctx.font = `bold ${fontSize}px Arial`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    lines.forEach((line, i) => ctx.fillText(line, canvasW / 2, i * lineH + 2));
    const imgW = pageW - pad * 2 - 4;
    const imgH = lines.length * lineH / (SCALE * 3.78);
    doc.addImage(textCanvas.toDataURL("image/png"), "PNG", pad + 2, bottomY, imgW, imgH);
  }

  doc.save(`${fileName}.pdf`);
}

function printSupplyBarcode(passNumber, supplyId) {
  if (!_isWbGiCode(passNumber)) return;
  if (typeof JsBarcode === "undefined") {
    alert("Библиотека штрихкодов загружается. Попробуйте через секунду.");
    return;
  }

  const item = suppliesState.items.find((x) => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;

  // === Exact same data as downloadSupplyBarcode ===
  const warehouseName = (item.warehouse_name || "").trim();
  const quantity = item.quantity != null ? `${item.quantity} шт` : "";
  const supplyDateRaw = item.supply_date || "";
  let dateStr = "";
  if (supplyDateRaw) {
    try {
      const d = new Date(supplyDateRaw);
      dateStr = String(d.getDate()).padStart(2,"0") + String(d.getMonth()+1).padStart(2,"0") + d.getFullYear();
    } catch(_) {}
  }
  // Find driver from slot matching this passNumber
  const _pSlots = _getItemSlots(item.supply_id || supplyId);
  const _pSlot = _pSlots.find(s => s.pass_number === passNumber) || _pSlots[0] || {};
  const driverNamePrint = _pSlot.effectiveDriverName || "";
  const bottomParts = [];
  if (dateStr) bottomParts.push(`${dateStr.slice(0,2)}.${dateStr.slice(2,4)}.${dateStr.slice(4)}`);
  if (warehouseName) bottomParts.push(warehouseName);
  if (quantity) bottomParts.push(quantity);
  const bottomLine1p = bottomParts.join("   ");
  const bottomText = driverNamePrint ? bottomLine1p + (bottomLine1p ? "\n" : "") + driverNamePrint : bottomLine1p;

  // === Render barcode to canvas (same settings) ===
  const bcCanvas = document.createElement("canvas");
  JsBarcode(bcCanvas, passNumber, { format:"CODE128", width:3, height:168, displayValue:false, margin:0, background:"#ffffff", lineColor:"#000000" });
  const bcDataUrl = bcCanvas.toDataURL("image/png");
  const bcAspect = bcCanvas.height / bcCanvas.width;

  // === Render bottom text to canvas (same Cyrillic workaround) ===
  let textDataUrl = "", textImgH = 0;
  if (bottomText) {
    const PAD = 1.5, PAGE_W = 58, SCALE = 4;
    const fontSize = 9 * SCALE;
    const canvasW = Math.round((PAGE_W - PAD * 2 - 4) * SCALE * 3.78);
    const lineH = 12 * SCALE;
    const tCanvas = document.createElement("canvas");
    tCanvas.width = canvasW; tCanvas.height = 4 * lineH;
    const ctx = tCanvas.getContext("2d");
    ctx.font = `bold ${fontSize}px Arial`;
    const segments2 = bottomText.split("\n");
    const lines = []; let cur = "";
    for (const seg of segments2) {
      const words = seg.split(/\s+/);
      cur = "";
      for (const w of words) {
        const test = cur ? cur + " " + w : w;
        if (ctx.measureText(test).width > canvasW - 8 && cur) { lines.push(cur); cur = w; }
        else cur = test;
      }
      if (cur) lines.push(cur);
    }
    tCanvas.height = lines.length * lineH + 4;
    ctx.clearRect(0, 0, canvasW, tCanvas.height);
    ctx.fillStyle = "#000"; ctx.font = `bold ${fontSize}px Arial`;
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    lines.forEach((l,i) => ctx.fillText(l, canvasW/2, i*lineH+2));
    textDataUrl = tCanvas.toDataURL("image/png");
    textImgH = lines.length * lineH / (SCALE * 3.78);
  }

  // === Build print window ===
  // Convert mm to px at 96dpi: 1mm = 3.7795px
  const MMpx = 3.7795;
  const PAD = 1.5, PAGE_W = 58, PAGE_H = 40;
  const bcX = PAD + 1.5, bcW = PAGE_W - PAD*2 - 3;
  const bcH = Math.min(bcW * bcAspect, 23);
  const bcY = PAD + 8;
  const txtY = bcY + bcH + 2.5;

  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
@page { size: 58mm 40mm; margin: 0; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 58mm; height: 40mm; overflow: hidden; position: relative; background: #fff; }
canvas, img { position: absolute; display: block; }
</style></head><body>
<canvas id="c" width="${Math.round(PAGE_W*MMpx)}" height="${Math.round(PAGE_H*MMpx)}"></canvas>
<script>
(function(){
  const c = document.getElementById("c");
  const ctx = c.getContext("2d");
  const mm = ${MMpx};
  // Dashed border
  ctx.setLineDash([1.2*mm, 0.8*mm]);
  ctx.strokeStyle = "rgb(190,190,190)"; ctx.lineWidth = 0.3*mm;
  ctx.strokeRect(${PAD}*mm, ${PAD}*mm, ${PAGE_W-PAD*2}*mm, ${PAGE_H-PAD*2}*mm);
  ctx.setLineDash([]);
  // Top text
  ctx.font = "bold " + 9*(mm*0.352778*2.835) + "px Helvetica, Arial";
  ctx.fillStyle = "#000"; ctx.textAlign = "center"; ctx.textBaseline = "top";
  ctx.fillText(${JSON.stringify(passNumber)}, ${PAGE_W/2}*mm, (${PAD}+2)*mm);
  // Barcode
  const bc = new Image(); bc.onload = function() {
    ctx.drawImage(bc, ${bcX}*mm, ${bcY}*mm, ${bcW}*mm, ${bcH}*mm);
    ${textDataUrl ? `
    const bt = new Image(); bt.onload = function() {
      ctx.drawImage(bt, (${PAD}+2)*mm, ${txtY}*mm, (${PAGE_W-PAD*2-4})*mm, ${textImgH}*mm);
      window.print();
    }; bt.src = ${JSON.stringify(textDataUrl)};
    ` : "window.print();"}
  }; bc.src = ${JSON.stringify(bcDataUrl)};
})();
<\/script>
</body></html>`;

  const win = window.open("", "_blank", "width=300,height=250");
  if (!win) { alert("Разрешите всплывающие окна для печати"); return; }
  win.document.write(html);
  win.document.close();
}

window.printSupplyBarcode = printSupplyBarcode;

function printPackingList(supplyId) {
  const url = `/api/supplies/${supplyId}/packing-list.pdf`;
  const win = window.open(url, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}
window.printPackingList = printPackingList;

function printPoA(supplyId) {
  const url = `/api/supplies/${supplyId}/poa.pdf`;
  const win = window.open(url, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}
window.printPoA = printPoA;

// Per-slot wrappers (multi-driver support)
function _getItemSlots(supplyId) {
  const item = suppliesState.items.find(x => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return [];
  let slots = [];
  if (item.drivers_json) { try { slots = JSON.parse(item.drivers_json); } catch (_) {} }
  if (!slots.length) slots = [{ pass_number: item.pass_number||"", driver_name: item.driver_name||"", pallets_count: item.pallets_count||"" }];
  // Add effectiveDriverName helper
  return slots.map(s => ({
    ...s,
    effectiveDriverName: s.manual_driver_name || s.driver_name || "",
    effectiveDriverDocs: s.manual_driver_docs || "",
  }));
}

async function downloadPoAForSlot(supplyId, slotIdx) {
  const item = suppliesState.items.find(x => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;
  const slots = _getItemSlots(supplyId);
  const slot = slots[slotIdx] || slots[0] || {};
  const orig = { driver_name: item.driver_name, pallets_count: item.pallets_count };
  item.driver_name = slot.effectiveDriverName || item.driver_name;
  item.pallets_count = slot.pallets_count || item.pallets_count;
  item._manual_driver_docs = slot.effectiveDriverDocs || "";
  await downloadPoA(supplyId);
  item.driver_name = orig.driver_name;
  item.pallets_count = orig.pallets_count;
  delete item._manual_driver_docs;
}

function printPoAForSlot(supplyId, slotIdx) {
  const win = window.open(`/api/supplies/${supplyId}/poa.pdf?slot_index=${slotIdx}`, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}

async function downloadTTNForSlot(supplyId, slotIdx) {
  const item = suppliesState.items.find(x => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;
  const slots = _getItemSlots(supplyId);
  const slot = slots[slotIdx] || slots[0] || {};
  const orig = { driver_name: item.driver_name, pallets_count: item.pallets_count };
  item.driver_name = slot.effectiveDriverName || item.driver_name;
  item.pallets_count = slot.pallets_count || item.pallets_count;
  item._manual_driver_docs = slot.effectiveDriverDocs || "";
  await downloadTTN(supplyId);
  item.driver_name = orig.driver_name;
  item.pallets_count = orig.pallets_count;
  delete item._manual_driver_docs;
}

function printTTNForSlot(supplyId, slotIdx) {
  const win = window.open(`/api/supplies/${supplyId}/ttn.pdf?slot_index=${slotIdx}`, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}

async function downloadPackingListForSlot(supplyId, slotIdx) {
  const item = suppliesState.items.find(x => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;
  const slots = _getItemSlots(supplyId);
  const slot = slots[slotIdx] || slots[0] || {};
  const orig = item.pass_number;
  item.pass_number = slot.pass_number || item.pass_number;
  downloadPackingList(supplyId);
  item.pass_number = orig;
}

function printPackingListForSlot(supplyId, slotIdx) {
  const win = window.open(`/api/supplies/${supplyId}/packing-list.pdf?slot_index=${slotIdx}`, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}

window.downloadPackingListForSlot = downloadPackingListForSlot;
window.printPackingListForSlot = printPackingListForSlot;
window.downloadPoAForSlot = downloadPoAForSlot;
window.printPoAForSlot = printPoAForSlot;
window.downloadTTNForSlot = downloadTTNForSlot;
window.printTTNForSlot = printTTNForSlot;

// ═══════════════════════════════════════════════════════════════════════════
// OZON SUPPLIES MODULE — fully isolated from WB
// ═══════════════════════════════════════════════════════════════════════════

// ── OZON date range calendar (mirrors WB calendar 1:1) ────────────────────
const _ozonCal = {
  viewYear: new Date().getFullYear(),
  viewMonth: new Date().getMonth(),
  startDate: null,
  endDate: null,
  hoveredDate: null,
};

function _ozonCalRender() {
  const container = document.getElementById("ozonCalendar");
  if (!container) return;
  const { viewYear: y, viewMonth: m, startDate: s, endDate: e, hoveredDate: h } = _ozonCal;
  const firstDay = new Date(y, m, 1);
  const lastDay = new Date(y, m + 1, 0);
  const startOffset = (firstDay.getDay() + 6) % 7;
  const today = new Date(); today.setHours(0,0,0,0);
  const fmtDisp = (d) => d ? `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}.${d.getFullYear()}` : "";

  let html = `<div class="cal-header" onclick="event.stopPropagation()">
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_ozonCalPrevMonth()">◄</button>
    <span class="cal-title">${_calMonths[m]} ${y}</span>
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_ozonCalNextMonth()">►</button>
  </div>
  <div class="cal-grid" onmouseleave="_ozonCalClearHover()">`;
  _calDays.forEach((d) => { html += `<div class="cal-cell cal-dow">${d}</div>`; });
  for (let i = 0; i < startOffset; i++) html += `<div class="cal-cell cal-empty"></div>`;
  for (let d = 1; d <= lastDay.getDate(); d++) {
    const date = new Date(y, m, d);
    const isToday = date.getTime() === today.getTime();
    const isStart = s && date.getTime() === s.getTime();
    const isEnd = e && date.getTime() === e.getTime();
    const rangeEnd = e || h;
    const inRange = s && rangeEnd && date > (s < rangeEnd ? s : rangeEnd) && date < (s < rangeEnd ? rangeEnd : s);
    let cls = "cal-cell cal-day";
    if (isStart || isEnd) cls += " cal-selected";
    if (isStart) cls += " cal-range-start";
    if (isEnd) cls += " cal-range-end";
    if (inRange) cls += " cal-in-range";
    if (isToday) cls += " cal-today";
    const iso = `${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
    html += `<div class="${cls}" data-date="${iso}" onclick="event.stopPropagation();_ozonCalPickDate(${y},${m},${d})" onmouseenter="_ozonCalHover(${y},${m},${d})">${d}</div>`;
  }
  html += `</div>`;
  if (s || e) {
    html += `<div class="cal-range-label" onclick="event.stopPropagation()">${fmtDisp(s) || "…"} — ${fmtDisp(e) || "…"}</div>`;
  }
  html += `<div class="cal-footer" onclick="event.stopPropagation()">
    <button type="button" class="secondary" onclick="event.stopPropagation();clearOzonDateFilter()">Сбросить</button>
  </div>`;
  container.innerHTML = html;
}

function _ozonCalPickDate(y, m, d) {
  const date = new Date(y, m, d);
  date.setHours(0, 0, 0, 0);
  if (!_ozonCal.startDate || (_ozonCal.startDate && _ozonCal.endDate)) {
    _ozonCal.startDate = date; _ozonCal.endDate = null;
  } else {
    if (date < _ozonCal.startDate) { _ozonCal.endDate = _ozonCal.startDate; _ozonCal.startDate = date; }
    else if (date.getTime() === _ozonCal.startDate.getTime()) { _ozonCal.startDate = null; }
    else { _ozonCal.endDate = date; }
  }
  _ozonCalRender();
  if (_ozonCal.startDate && _ozonCal.endDate) {
    const fmt = (dt) => `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,"0")}-${String(dt.getDate()).padStart(2,"0")}`;
    const f = document.getElementById("ozonDateFrom");
    const t = document.getElementById("ozonDateTo");
    if (f) f.value = fmt(_ozonCal.startDate);
    if (t) t.value = fmt(_ozonCal.endDate);
    loadOzonSupplies(true);
    _updateOzonDateBtn();
    setTimeout(() => toggleOzonDatePanel(false), 300);
  }
}

function _ozonCalHover(y, m, d) {
  if (!_ozonCal.startDate || _ozonCal.endDate) return;
  _ozonCal.hoveredDate = new Date(y, m, d);
  const s = _ozonCal.startDate;
  document.querySelectorAll("#ozonCalendar .cal-day[data-date]").forEach((el) => {
    const dt = new Date(el.dataset.date + "T00:00:00");
    const h2 = _ozonCal.hoveredDate;
    const inRange = s && h2 && dt > (s < h2 ? s : h2) && dt < (s < h2 ? h2 : s);
    el.classList.toggle("cal-in-range", inRange);
  });
}
function _ozonCalClearHover() {
  if (_ozonCal.hoveredDate) {
    _ozonCal.hoveredDate = null;
    document.querySelectorAll("#ozonCalendar .cal-day.cal-in-range").forEach((el) => el.classList.remove("cal-in-range"));
  }
}
function _ozonCalPrevMonth() {
  if (_ozonCal.viewMonth === 0) { _ozonCal.viewMonth = 11; _ozonCal.viewYear--; }
  else _ozonCal.viewMonth--;
  _ozonCalRender();
}
function _ozonCalNextMonth() {
  if (_ozonCal.viewMonth === 11) { _ozonCal.viewMonth = 0; _ozonCal.viewYear++; }
  else _ozonCal.viewMonth++;
  _ozonCalRender();
}

function toggleOzonDatePanel(show) {
  const panel = document.getElementById("ozonDatePanel");
  if (!panel) return;
  const isVisible = panel.style.display === "flex";
  const shouldShow = show !== undefined ? Boolean(show) : !isVisible;
  panel.style.display = shouldShow ? "flex" : "none";
  if (shouldShow) _ozonCalRender();
  _updateOzonDateBtn();
}

function _updateOzonDateBtn() {
  const btn = document.getElementById("ozonDateBtn");
  if (!btn) return;
  if (_ozonCal.startDate && _ozonCal.endDate) {
    const fmt = (d) => d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
    btn.textContent = `${fmt(_ozonCal.startDate)}–${fmt(_ozonCal.endDate)}`;
  } else {
    btn.textContent = "📅";
  }
}

function clearOzonDateFilter() {
  _ozonCal.startDate = null; _ozonCal.endDate = null; _ozonCal.hoveredDate = null;
  const from = document.getElementById("ozonDateFrom");
  const to = document.getElementById("ozonDateTo");
  if (from) from.value = "";
  if (to) to.value = "";
  _ozonCalRender();
  _updateOzonDateBtn();
  toggleOzonDatePanel(false);
  loadOzonSupplies(true);
}
// Moscow warehouse IDs (cluster 4039 — Москва, МО и Дальние регионы, direct supply only)
const OZON_MOSCOW_WH_IDS = new Set([
  15431806189000, 1020002458344000, 19262731541000,
  1020000759116000, 1020001642383000,
  23843917228000, 23902289166000,
  1020000241710000, 23948599159000,
  1020000115166000, 1020003227965000,
  1020001853757000,
  1020000435290000, 1020000989855000,
  1020001853954000,
  1020002007811000, 1020000268887000,
]);

const OZON_STATUS_LABELS = {
  "DATA_FILLING":                   "Заполнение данных",
  "READY_TO_SUPPLY":                "Готово к отгрузке",
  "IN_TRANSIT":                     "В пути",
  "COMPLETED":                      "Принята",
  "REPORTS_CONFIRMATION_AWAITING":  "Согласование актов",
  "CANCELLED":                      "Отменена",
};

const ozonState = { items: [], allItems: [], total: 0, page: 1, page_size: 50 };
let _ozonSyncPollTimer = null;
let _ozonDetailsCurrentId = null;
let _selectedOzonIds = new Set();

// ── Load & render ──────────────────────────────────────────────────────────
async function loadOzonSupplies(resetPage = false) {
  if (resetPage) ozonState.page = 1;
  const statusF = document.getElementById("ozonStatusFilter")?.value || "";
  const prodF = document.getElementById("ozonProductionFilter")?.value || "";
  const dateFrom = document.getElementById("ozonDateFrom")?.value || "";
  const dateTo = document.getElementById("ozonDateTo")?.value || "";
  const params = new URLSearchParams({ page: ozonState.page, page_size: ozonState.page_size });
  const res = await fetch(`/api/ozon-supplies?${params}`).catch(() => null);
  if (!res || !res.ok) return;
  const data = await res.json().catch(() => ({}));
  let items = data.items || [];
  // Client-side filtering
  if (statusF) items = items.filter(x => (x.state || "") === statusF);
  if (prodF) items = items.filter(x => (x.production || "") === prodF);
  if (dateFrom) items = items.filter(x => (x.supply_date || "").slice(0,10) >= dateFrom);
  if (dateTo) items = items.filter(x => (x.supply_date || "").slice(0,10) <= dateTo);
  ozonState.allItems = items;   // full filtered set
  ozonState.total = items.length;
  _populateOzonProductionFilter();
  _applyOzonPage();
  _updateOzonBatchUI();
}

function _applyOzonPage() {
  const start = (ozonState.page - 1) * ozonState.page_size;
  ozonState.items = (ozonState.allItems || []).slice(start, start + ozonState.page_size);
  renderOzonTable();
  _updateOzonPagination();
}

function _populateOzonProductionFilter() {
  const sel = document.getElementById("ozonProductionFilter");
  if (!sel) return;
  const cur = sel.value;
  const prods = [...new Set(_supplyProductionsCache.map(p => p.name))];
  sel.innerHTML = '<option value="">Все производства</option>' +
    prods.map(n => `<option value="${esc(n)}"${n===cur?' selected':''}>${esc(n)}</option>`).join("");
}

function renderOzonTable() {
  const tbody = document.getElementById("ozonSuppliesTbody");
  if (!tbody) return;
  const sq = (document.getElementById("ozonSearchFilter")?.value || "").toLowerCase();
  let rows = ozonState.items;
  if (sq) rows = rows.filter(x => (x.supply_order_number||"").toLowerCase().includes(sq) || (x.warehouse_name||"").toLowerCase().includes(sq));

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">Поставки не найдены</td></tr>';
    return;
  }
  tbody.innerHTML = "";
  rows.forEach((item, idx) => {
    const tr = document.createElement("tr");
    tr.className = "supply-row";
    tr.dataset.supplyId = String(item.supply_order_id);
    const statusLabel = OZON_STATUS_LABELS[item.state] || (item.state || "—");
    const statusClass = { "DATA_FILLING":"supply-status-2", "READY_TO_SUPPLY":"supply-status-3", "IN_TRANSIT":"supply-status-4", "COMPLETED":"supply-status-5", "REPORTS_CONFIRMATION_AWAITING":"supply-status-6", "CANCELLED":"supply-status-1" }[item.state] || "";
    const supplyDate = item.supply_date
      ? (() => { try { return new Date(item.supply_date).toLocaleDateString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric"}); } catch(_){return item.supply_date;} })()
      : "Не назначена";
    tr.innerHTML = `
      <td style="width:32px;padding:0 4px;text-align:center">
        <input type="checkbox" class="ozon-row-checkbox" data-supply-id="${item.supply_order_id}" onchange="onOzonCheckboxChange()" />
      </td>
      <td class="supply-expand-cell">
        <button class="supply-expand-btn" onclick="toggleOzonGoods(this, ${item.supply_order_id})" aria-label="Развернуть">▶</button>
      </td>
      <td><span class="supply-id-text">${item.supply_order_number || item.supply_order_id}</span></td>
      <td class="supply-legal-cell">${esc(item.supplier_name || "—")}</td>
      <td>${item.is_crossdock && item.transit_warehouse_name
        ? `${esc(item.transit_warehouse_name)} → <strong>${esc(item.warehouse_name || "—")}</strong>`
        : (item.warehouse_name || "—") + ((!item.is_crossdock && OZON_MOSCOW_WH_IDS.has(Number(item.warehouse_id)))
            ? ' <strong>(Москва)</strong>' : '')}</td>
      <td class="supply-prod-cell">${item.production ? esc(item.production) : '<span class="supply-prod-empty">Требует заполнения</span>'}</td>
      <td>${esc(supplyDate)}</td>
      <td>${item.total_quantity || "—"}</td>
      <td><span class="supply-status-badge ${statusClass}">${esc(statusLabel)}</span></td>
      <td class="supply-links-cell">
        <div class="supply-links-col">
          <button class="supply-detail-link" onclick="openOzonDetailsModal(${item.supply_order_id})">☰ Детали поставки</button>
          <div style="display:flex;flex-wrap:nowrap;align-items:center;gap:2px;width:100%;min-width:0"><button class="supply-detail-link supply-poa-link" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" onclick="downloadOzonPoA(${item.supply_order_id})">⬇ Доверенность</button><button class="supply-detail-link supply-print-btn" style="flex:0 0 60px;min-width:60px;width:60px;height:28px;padding:0;font-size:13px;font-family:'Segoe UI Symbol','Arial Unicode MS',sans-serif;display:flex;align-items:center;justify-content:center" onclick="window.open('/api/ozon-supplies/${item.supply_order_id}/poa.pdf','_blank')" title="Печать">⎙</button></div>
          <div style="display:flex;flex-wrap:nowrap;align-items:center;gap:2px;width:100%;min-width:0"><button class="supply-detail-link supply-ttn-link" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" onclick="window.open('/api/ozon-supplies/${item.supply_order_id}/ttn.pdf','_blank')">⬇ ТТН</button><button class="supply-detail-link supply-print-btn" style="flex:0 0 60px;min-width:60px;width:60px;height:28px;padding:0;font-size:13px;font-family:'Segoe UI Symbol','Arial Unicode MS',sans-serif" onclick="window.open('/api/ozon-supplies/${item.supply_order_id}/ttn.pdf','_blank')" title="Печать">⎙</button></div>
        </div>
      </td>`;
    tbody.appendChild(tr);
    // Goods row
    const goodsTr = document.createElement("tr");
    goodsTr.className = "supply-goods-row hidden";
    goodsTr.dataset.supplyId = String(item.supply_order_id);
    goodsTr.innerHTML = `<td colspan="10"><div class="supply-goods-container" id="ozon-goods-${item.supply_order_id}"><span class="small" style="color:#94a3b8">Загрузка…</span></div></td>`;
    tbody.appendChild(goodsTr);
  });
}

async function toggleOzonGoods(btn, supplyId) {
  const goodsRow = document.querySelector(`.supply-goods-row[data-supply-id="${supplyId}"]`);
  if (!goodsRow) return;
  const isOpen = !goodsRow.classList.contains("hidden");
  if (isOpen) { goodsRow.classList.add("hidden"); btn.textContent = "▶"; return; }
  goodsRow.classList.remove("hidden"); btn.textContent = "▼";
  const container = document.getElementById(`ozon-goods-${supplyId}`);
  if (!container || container.dataset.loaded) return;
  const res = await fetch(`/api/ozon-supplies/${supplyId}/goods`).catch(() => null);
  if (!res || !res.ok) { container.innerHTML = '<span class="small" style="color:#b91c1c">Ошибка загрузки</span>'; return; }
  const goods = await res.json().catch(() => []);
  container.dataset.loaded = "1";
  if (!goods.length) { container.innerHTML = '<span class="small" style="color:#94a3b8">Нет товаров</span>'; return; }
  // Update quantity cell in the parent row
  const totalQty = goods.reduce((s, g) => s + (Number(g.quantity) || 0), 0);
  if (totalQty > 0) {
    const parentRow = document.querySelector(`.supply-row[data-supply-id="${supplyId}"]`);
    if (parentRow) {
      const cells = parentRow.querySelectorAll("td");
      // qty is 7th td (0-indexed: checkbox,expand,#,warehouse,prod,date,qty,status,links)
      if (cells[6]) cells[6].textContent = totalQty;
    }
  }
  let html = '<table class="supply-goods-table"><thead><tr><th>SKU OZON</th><th>Наименование</th><th>Арт. продавца</th><th>Кол-во</th></tr></thead><tbody>';
  for (const g of goods) {
    // product_name from our catalog (by offer_id), fallback to offer_id, then API name
    const displayName = g.product_name || g.offer_id || g.name || "—";
    html += `<tr><td>${g.sku || "—"}</td><td>${esc(displayName)}</td><td>${esc(g.offer_id || "—")}</td><td>${g.quantity ?? "—"}</td></tr>`;
  }
  html += "</tbody></table>";
  container.innerHTML = html;
}

function _updateOzonPagination() {
  const total = ozonState.total;
  const totalPages = Math.max(1, Math.ceil(total / ozonState.page_size));
  const info = document.getElementById("ozonPageInfo");
  if (info) info.textContent = `${ozonState.page} / ${totalPages}`;
  const prev = document.getElementById("ozonPrevBtn");
  const next = document.getElementById("ozonNextBtn");
  if (prev) prev.disabled = ozonState.page <= 1;
  if (next) next.disabled = ozonState.page >= totalPages;
  const inf = document.getElementById("ozonInfo");
  if (inf) inf.textContent = `Поставок: ${total}`;
}

function ozonChangePage(delta) {
  const totalPages = Math.max(1, Math.ceil(ozonState.total / ozonState.page_size));
  ozonState.page = Math.max(1, Math.min(totalPages, ozonState.page + delta));
  _applyOzonPage();
}

// ── Sync ───────────────────────────────────────────────────────────────────
async function syncOzonSupplies() {
  const btn = document.getElementById("ozonSyncBtn");
  const stopBtn = document.getElementById("ozonStopBtn");
  if (btn) { btn.disabled = true; btn.textContent = "⏳ Синхронизация…"; }
  if (stopBtn) stopBtn.classList.remove("hidden");
  const res = await fetch("/api/ozon-supplies/sync", { method: "POST", headers: jsonHeaders() }).catch(() => null);
  if (!res || !res.ok) {
    const e = await res?.json().catch(()=>({})) || {};
    if (btn) { btn.disabled = false; btn.textContent = "🔄 Синхронизировать"; }
    if (stopBtn) stopBtn.classList.add("hidden");
    alert("Ошибка: " + (e.message || e.detail || res?.status)); return;
  }
  _ozonPollSync();
}

async function stopOzonSync() {
  const stopBtn = document.getElementById("ozonStopBtn");
  if (stopBtn) { stopBtn.disabled = true; stopBtn.textContent = "⏳"; }
  const res = await fetch("/api/ozon-supplies/sync/stop", { method: "POST", headers: jsonHeaders() }).catch(() => null);
  // If sync wasn't running, restore button immediately (poll timer is not active)
  if (!res || !res.ok) {
    if (stopBtn) { stopBtn.disabled = false; stopBtn.textContent = "🛑"; stopBtn.classList.add("hidden"); }
    return;
  }
  const data = await res.json().catch(() => ({}));
  if (!data.ok) {
    // Sync was not in progress — restore stop button and hide it
    if (stopBtn) { stopBtn.disabled = false; stopBtn.textContent = "🛑"; stopBtn.classList.add("hidden"); }
  }
  // If data.ok = true, poll timer will handle restoring the button when sync finishes
}

function _ozonPollSync() {
  if (_ozonSyncPollTimer) clearInterval(_ozonSyncPollTimer);
  _ozonSyncPollTimer = setInterval(async () => {
    const r = await fetch("/api/ozon-supplies/sync/status").catch(() => null);
    if (!r || !r.ok) return;
    const d = await r.json().catch(() => ({}));
    const info = document.getElementById("ozonSyncInfo");
    const synced = Number(d.synced ?? 0);
    const total = Number(d.total ?? 0);
    if (d.in_progress) {
      const progressText = total > 0
        ? `Загружено ${synced} из ${total} поставок`
        : synced > 0 ? `Загружено ${synced} поставок…` : "Загрузка списка…";
      if (info) { info.textContent = progressText; info.style.color = "#64748b"; }
    } else {
      clearInterval(_ozonSyncPollTimer);
      const btn = document.getElementById("ozonSyncBtn");
      const stopBtn = document.getElementById("ozonStopBtn");
      if (btn) { btn.disabled = false; btn.textContent = "🔄 Синхронизировать"; }
      if (stopBtn) { stopBtn.classList.add("hidden"); stopBtn.disabled = false; stopBtn.textContent = "🛑"; }
      if (info) { info.textContent = d.message || `Готово. Загружено ${synced} поставок.`; info.style.color = "#16a34a"; }
      await loadOzonSupplies(true);
    }
  }, 1000);
}

async function clearOzonSupplies() {
  if (!confirm("Удалить все поставки OZON?")) return;
  await fetch("/api/ozon-supplies", { method: "DELETE", headers: jsonHeaders() });
  await loadOzonSupplies(true);
}

// ── Details modal ──────────────────────────────────────────────────────────
async function openOzonDetailsModal(supplyId) {
  const item = ozonState.items.find(x => x.supply_order_id === supplyId || x.supply_order_id === Number(supplyId));
  if (!item) return;
  _ozonDetailsCurrentId = item.supply_order_id;

  const supplyDate = item.supply_date
    ? (() => { try { return new Date(item.supply_date).toLocaleDateString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric"}); } catch(_){return item.supply_date;} })()
    : "Не назначена";

  document.getElementById("ozonSdOrderNum").textContent = item.supply_order_number || item.supply_order_id;
  document.getElementById("ozonSdDate").textContent = supplyDate;
  const wh = document.getElementById("ozonSdWarehouse");
  if (wh) {
    if (item.is_crossdock && item.transit_warehouse_name) {
      wh.innerHTML = `${esc(item.transit_warehouse_name)} → <strong>${esc(item.warehouse_name || "—")}</strong>`;
    } else {
      const moscowTag = (!item.is_crossdock && OZON_MOSCOW_WH_IDS.has(Number(item.warehouse_id)))
        ? ' <strong>(Москва)</strong>' : '';
      wh.innerHTML = esc(item.warehouse_name || "—") + moscowTag;
    }
  }
  document.getElementById("ozonSdQty").textContent = item.total_quantity || "—";
  const ozonSdTypeEl = document.getElementById("ozonSdType");
  if (ozonSdTypeEl) ozonSdTypeEl.textContent = item.creation_flow || "—";
  const ozonPalletsEl = document.getElementById("ozonSdPallets");
  if (ozonPalletsEl) ozonPalletsEl.value = item.pallets_count || "";

  // Load driver/vehicle from OZON API (or cache)
  const driverEl = document.getElementById("ozonSdDriver");
  const vehicleEl = document.getElementById("ozonSdVehicle");
  const phoneEl = document.getElementById("ozonSdPhone");
  const vehicleRow = document.getElementById("ozonSdVehicleRow");
  const phoneRow = document.getElementById("ozonSdPhoneRow");
  if (driverEl) driverEl.textContent = "Загрузка…";
  fetch(`/api/ozon-supplies/${item.supply_order_id}/vehicle`).then(r => r.json()).then(d => {
    const v = d.vehicle || {};
    if (driverEl) driverEl.textContent = v.driver_name || "—";
    if (v.vehicle_model || v.vehicle_number) {
      if (vehicleEl) vehicleEl.textContent = [v.vehicle_model, v.vehicle_number].filter(Boolean).join(" ");
      if (vehicleRow) vehicleRow.style.display = "";
    }
    // phone removed from modal per requirements
    if (d.error === "no_role") {
      if (driverEl) driverEl.textContent = "—  (нужны расширенные права API)";
    }
  }).catch(() => { if (driverEl) driverEl.textContent = "—"; });

  // Load cargo places
  const cargoEl = document.getElementById("ozonSdCargoes");
  if (cargoEl) {
    cargoEl.textContent = "Загрузка…";
    fetch(`/api/ozon-supplies/${item.supply_order_id}/cargoes-info`).then(r => r.json()).then(d => {
      const groups = d.groups || [];
      if (!groups.length) { cargoEl.textContent = "Ещё не заполнены"; return; }
      const typeLabel = t => t === "BOX" ? "короба" : t === "PALLET" ? "паллета" : t.toLowerCase();
      const contLabel = c => c === "MONO" ? "моно" : c === "MIXED" ? "микс" : c.toLowerCase();
      cargoEl.textContent = groups.map(g => `${g.count} ${typeLabel(g.type)} — ${contLabel(g.content_type)}`).join("\n");
    }).catch(() => { cargoEl.textContent = "Ещё не заполнены"; });
  }
  document.getElementById("ozonSdNotes").value = item.notes || "";

  // Populate production dropdown
  _populateProductionSelects();
  const prodSel = document.getElementById("ozonSdProduction");
  if (prodSel) prodSel.value = item.production || "";

  // Populate driver dropdown
  const dSel = document.getElementById("ozonSdDriverSelect");
  if (dSel) {
    if (!_supplyDriversCache.length) await loadSupplyDrivers();
    dSel.innerHTML = '<option value="">— Не выбран —</option>' +
      _supplyDriversCache.map(d => `<option value="${esc(d.full_name||"")}">${esc(d.full_name||"")}</option>`).join("");
    dSel.value = item.driver_name || "";
  }

  const modal = document.getElementById("ozonDetailsModal");
  if (modal) { modal.classList.remove("hidden"); modal.style.display = ""; }
}

function closeOzonDetailsModal() {
  const modal = document.getElementById("ozonDetailsModal");
  if (modal) { modal.classList.add("hidden"); modal.style.display = "none"; }
  _ozonDetailsCurrentId = null;
}

function onOzonDriverSelectChange(val) {}

async function saveOzonManualFields() {
  if (!_ozonDetailsCurrentId) return;
  const payload = {
    pallets_count: document.getElementById("ozonSdPallets")?.value || "",
    notes: document.getElementById("ozonSdNotes")?.value || "",
    production: document.getElementById("ozonSdProduction")?.value || "",
  };
  await fetch(`/api/ozon-supplies/${_ozonDetailsCurrentId}/manual-fields`, {
    method: "PATCH", headers: jsonHeaders(), body: JSON.stringify(payload)
  }).catch(() => null);
  closeOzonDetailsModal();
  await loadOzonSupplies();
}

// ── Batch selection (same logic as WB) ────────────────────────────────────
function onOzonCheckboxChange() {
  _selectedOzonIds.clear();
  document.querySelectorAll(".ozon-row-checkbox:checked").forEach(cb => _selectedOzonIds.add(Number(cb.dataset.supplyId)));
  _updateOzonBatchUI();
}

function toggleSelectAllOzon(checked) {
  document.querySelectorAll(".ozon-row-checkbox").forEach(cb => { cb.checked = checked; });
  onOzonCheckboxChange();
}

function _updateOzonBatchUI() {
  // reuse same batch wrap if needed — OZON uses same conditions
  // For now just log — batch docs for OZON TBD
}

// ── Register all handlers ──────────────────────────────────────────────────
window.loadOzonSupplies = loadOzonSupplies;
window.renderOzonTable = renderOzonTable;
window.syncOzonSupplies = syncOzonSupplies;
window.stopOzonSync = stopOzonSync;
window.copyOzonDetails = copyOzonDetails;
window.clearOzonSupplies = clearOzonSupplies;
window.ozonChangePage = ozonChangePage;
window.toggleOzonGoods = toggleOzonGoods;
window.openOzonDetailsModal = openOzonDetailsModal;
window.closeOzonDetailsModal = closeOzonDetailsModal;
window.saveOzonManualFields = saveOzonManualFields;
window.onOzonCheckboxChange = onOzonCheckboxChange;
window.toggleSelectAllOzon = toggleSelectAllOzon;

async function downloadOzonPoA(supplyId) {
  const item = (ozonState.allItems || ozonState.items || []).find(x => x.supply_order_id === supplyId || x.supply_order_id === Number(supplyId));
  if (!item) return;

  const now = new Date();
  const dd = String(now.getDate()).padStart(2, "0");
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const yyyy = now.getFullYear();
  const dateDisplay = `${dd}.${mm}.${yyyy}`;

  // Legal entity — same cache as WB
  const supplierShort = item.supplier_name || "";
  const le = _supplyLegalEntitiesCache.find(e => e.short_name === supplierShort) || (_supplyLegalEntitiesCache[0] || {});
  const orgFull = le.full_name || supplierShort;
  const orgReq = le.requisites || "";
  const orgLine = [orgFull, orgReq].filter(Boolean).join(", ");

  // Driver from OZON vehicle API
  let driverName = "";
  let driverDocs = "";
  try {
    const vr = await fetch(`/api/ozon-supplies/${supplyId}/vehicle`, {credentials: 'include'}).catch(() => null);
    if (vr && vr.ok) {
      const vd = await vr.json().catch(() => ({}));
      const v = vd.vehicle || {};
      driverName = v.driver_name || "";
      driverDocs = v.driver_phone || "";
    }
  } catch(_) {}

  // Goods
  let poaGoods = [];
  try {
    const gr = await fetch(`/api/ozon-supplies/${supplyId}/goods`, {credentials: 'include'}).catch(() => null);
    if (gr && gr.ok) poaGoods = await gr.json().catch(() => []);
  } catch(_) {}
  if (!poaGoods.length) poaGoods = [{ name: "Товары OZON", offer_id: "", quantity: "—" }];

  const supplyNum = String(item.supply_order_number || "");
  const wh = String(item.warehouse_name || "");

  const html = `
<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"
  xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8">
<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View></w:WordDocument></xml><![endif]-->
<style>
  @page { size: 210mm 297mm; margin: 15mm 10mm 15mm 25mm; }
  body { font-family: "Times New Roman", serif; font-size: 12pt; line-height: 1.15; }
  .small { font-size: 8pt; text-align: center; }
  .underline { text-decoration: underline; }
  .center { text-align: center; }
  .bold { font-weight: bold; }
  table.outer { width: 100%; border-collapse: collapse; margin-bottom: 6pt; }
  table.codes { border-collapse: collapse; margin-left: auto; font-size: 9pt; }
  table.codes td { border: 1px solid #000; padding: 2pt 6pt; }
  table.mat { width: 100%; border-collapse: collapse; margin-top: 4pt; font-size: 11pt; border: 1px solid #000; }
  table.mat td, table.mat th { border: 1px solid #000; padding: 2pt 4pt; text-align: center; white-space: nowrap; }
  table.mat td.mat-name, table.mat th.mat-name { text-align: left; white-space: normal; }
  .dotline { display: inline-block; border-bottom: 1px solid #000; min-width: 120pt; }
  p { margin: 1pt 0; }
</style>
</head>
<body>
<table class="outer">
  <tr>
    <td style="width:55%;vertical-align:top;font-size:12pt">
      Организация <span class="underline">${esc(orgFull)}</span>
    </td>
    <td style="width:45%;vertical-align:top;text-align:right;font-size:8pt">
      Типовая межотраслевая форма № М-2<br>
      Утверждена постановлением Госстата России от 30.10.97 № 71а<br><br>
      <table class="codes">
        <tr><td colspan="2" class="bold center">Коды</td></tr>
        <tr><td>Форма по ОКУД</td><td>0315001</td></tr>
        <tr><td>по ОКПО</td><td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td></tr>
      </table>
    </td>
  </tr>
</table>

<p style="text-align:center;font-size:14pt;font-weight:bold;margin:10pt 0 4pt"><b>Доверенность № ${esc(supplyNum)}</b></p>

<p>Дата выдачи <span class="underline bold">${dateDisplay}</span></p>
<p>Доверенность действительна 14 дней с даты подписания.</p>
<p style="margin-top:6pt">${esc(orgLine)}</p>
<p class="small">наименование потребителя и его адрес</p>
<p style="margin-top:4pt">${esc(orgLine)}</p>
<p class="small">наименование плательщика и его адрес</p>

<p style="margin-top:8pt">
  Доверенность выдана &nbsp;&nbsp;
  <span class="underline" style="min-width:60pt;display:inline-block">водителю</span>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <span class="underline">${esc(driverName)}</span>
</p>
<p class="small" style="padding-left:120pt">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; фамилия, имя, отчество</p>

${driverDocs ? `<p>${esc(driverDocs)}</p>` : ""}

<p style="margin-top:6pt">
  На отправку груза от &nbsp;&nbsp;
  <span class="underline">&nbsp;&nbsp;&nbsp;&nbsp;${esc(wh)}&nbsp;&nbsp;&nbsp;&nbsp;</span>
</p>
<p class="small" style="text-align:center">наименование поставщика</p>

<p style="margin-top:4pt">
  материальных ценностей. Основание: №<span class="underline bold">${esc(supplyNum)}</span>
  &nbsp; от &nbsp;
  <span class="underline bold">${dateDisplay}</span>
</p>
<p class="small">наименование, номер и дата документа</p>

<p style="margin-top:10pt">Перечень материальных ценностей, подлежащих доставке</p>
<table class="mat">
  <colgroup><col style="width:5%"><col style="width:75%"><col style="width:10%"><col style="width:10%"></colgroup>
  <tr>
    <th style="white-space:nowrap">№</th>
    <th class="mat-name">Материальные ценности</th>
    <th style="white-space:nowrap">Ед. изм.</th>
    <th style="white-space:nowrap">Кол-во</th>
  </tr>
  ${poaGoods.map((g, i) => `<tr>
    <td style="white-space:nowrap">${i+1}</td>
    <td class="mat-name">${esc(g.name || g.offer_id || "Товар")}</td>
    <td style="white-space:nowrap">шт.</td>
    <td style="white-space:nowrap">${g.quantity ?? "—"}</td>
  </tr>`).join("")}
</table>

<p style="margin-top:18pt">
  Подпись лица, получившего доверенность удостоверяем.
  &nbsp;&nbsp;&nbsp;&nbsp;
  <span class="dotline">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>
  &nbsp;&nbsp;
  (${esc(driverName)})
</p>

<table style="width:100%;margin-top:18pt;border-collapse:collapse">
  <tr>
    <td style="width:25%;vertical-align:bottom">Руководитель<br><span style="font-size:8pt">М.П.</span></td>
    <td style="width:30%;vertical-align:bottom;text-align:center">
      <span class="dotline">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span><br>
      <span class="small">подпись</span>
    </td>
    <td style="width:45%;vertical-align:bottom;text-align:center">
      (${esc(le.signatories || supplierShort)})<br>
      <span class="small">расшифровка подписи</span>
    </td>
  </tr>
</table>

<table style="width:100%;margin-top:14pt;border-collapse:collapse">
  <tr>
    <td style="width:25%;vertical-align:bottom">Главный бухгалтер</td>
    <td style="width:30%;vertical-align:bottom;text-align:center">
      <span class="dotline">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span><br>
      <span class="small">подпись</span>
    </td>
    <td style="width:45%;vertical-align:bottom;text-align:center">
      (${esc(le.signatories || supplierShort)})<br>
      <span class="small">расшифровка подписи</span>
    </td>
  </tr>
</table>

</body></html>`;

  const blob = new Blob(["\uFEFF" + html], { type: "application/msword" });
  const url = URL.createObjectURL(blob);
  const supplyDateDisp = item.supply_date
    ? new Date(item.supply_date).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" })
    : dateDisplay;
  const poaFileName = `Доверенность №${supplyNum}, ${supplierShort} от ${supplyDateDisp}, ${wh}, ${driverName}.doc`;
  const winPoa = window.open("", "_blank");
  if (winPoa) {
    const a = winPoa.document.createElement("a");
    a.href = url; a.download = poaFileName;
    winPoa.document.body.appendChild(a); a.click();
    setTimeout(() => { try { winPoa.close(); } catch(_){} URL.revokeObjectURL(url); }, 1500);
  } else {
    const a = document.createElement("a");
    a.href = url; a.download = poaFileName; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}
window.downloadOzonPoA = downloadOzonPoA;

// ═══════════════════════════════════════════════════════════════════════════
// OZON BINDING MERGE MODULE
// ═══════════════════════════════════════════════════════════════════════════

let _ozonBindFiles   = [];   // [{name, normalizedName, arrayBuffer}]
let _ozonBindMerged  = [];   // [{name, blob}]

function openOzonBindingModal() {
  const m = document.getElementById("ozonBindingModal");
  if (m) { m.classList.remove("hidden"); }
}
function closeOzonBindingModal() {
  const m = document.getElementById("ozonBindingModal");
  if (m) { m.classList.add("hidden"); }
  // Clear all data to free browser memory
  _ozonBindFiles = [];
  _ozonBindMerged = [];
  const log = document.getElementById("ozonBindLog");
  if (log) log.innerHTML = '<span style="color:#94a3b8">Загрузите файлы xlsx для начала работы…</span>';
  const mergeBtn = document.getElementById("ozonBindMergeBtn");
  const dlBtn = document.getElementById("ozonBindDownloadBtn");
  if (mergeBtn) mergeBtn.disabled = true;
  if (dlBtn) { dlBtn.disabled = true; dlBtn.style.opacity = "0.4"; }
}
window.openOzonBindingModal = openOzonBindingModal;
window.closeOzonBindingModal = closeOzonBindingModal;

function ozonBindLoad() {
  document.getElementById("ozonBindFileInput")?.click();
}
window.ozonBindLoad = ozonBindLoad;

async function ozonBindOnFiles(fileList) {
  if (!fileList || !fileList.length) return;
  if (typeof JSZip === "undefined") {
    _bindLog('<span style="color:#b91c1c">Ошибка: JSZip не загружен. Перезагрузите страницу.</span>', "err");
    return;
  }
  _bindLog("Загрузка файлов…", "info");
  let added = 0;
  for (const file of fileList) {
    const buf = await file.arrayBuffer();
    if (file.name.toLowerCase().endsWith(".zip")) {
      // Extract xlsx files from ZIP
      _bindLog(`📦 Распаковка архива: <b>${esc(file.name)}</b>…`, "info");
      try {
        const zip = await JSZip.loadAsync(buf);
        let xlsxCount = 0;
        for (const [path, entry] of Object.entries(zip.files)) {
          if (entry.dir) continue;
          const fname = path.split("/").pop();
          if (!fname.toLowerCase().endsWith(".xlsx")) continue;
          const xlsxBuf = await entry.async("arraybuffer");
          const norm = _bindNormName(fname);
          _ozonBindFiles.push({ name: fname, normalizedName: norm, arrayBuffer: xlsxBuf });
          _bindLog(`  ✓ Из архива: <b>${esc(fname)}</b>`, "ok");
          xlsxCount++;
          added++;
        }
        if (xlsxCount === 0) {
          _bindLog(`  ⚠ В архиве <b>${esc(file.name)}</b> xlsx-файлов не найдено.`, "warn");
        } else {
          _bindLog(`  📦 Извлечено из архива: <b>${xlsxCount}</b> файлов.`, "info");
        }
      } catch (e) {
        _bindLog(`<span style="color:#b91c1c">❌ Ошибка распаковки <b>${esc(file.name)}</b>: ${esc(String(e))}</span>`, "err");
      }
    } else {
      // Regular xlsx
      const norm = _bindNormName(file.name);
      _ozonBindFiles.push({ name: file.name, normalizedName: norm, arrayBuffer: buf });
      _bindLog(`✓ Загружен: <b>${esc(file.name)}</b>`, "ok");
      added++;
    }
  }
  _bindLog(`Всего файлов в очереди: <b>${_ozonBindFiles.length}</b>.`, "info");
  document.getElementById("ozonBindMergeBtn").disabled = _ozonBindFiles.length < 2;
  document.getElementById("ozonBindDownloadBtn").disabled = true;
  document.getElementById("ozonBindDownloadBtn").style.opacity = "0.4";
  document.getElementById("ozonBindFileInput").value = "";
}
window.ozonBindOnFiles = ozonBindOnFiles;

function ozonBindClear() {
  _ozonBindFiles = [];
  _ozonBindMerged = [];
  _bindLog("🗑 Все файлы удалены.", "warn");
  document.getElementById("ozonBindMergeBtn").disabled = true;
  document.getElementById("ozonBindDownloadBtn").disabled = true;
  document.getElementById("ozonBindDownloadBtn").style.opacity = "0.4";
}
window.ozonBindClear = ozonBindClear;

function _bindNormName(fileName) {
  // Remove extension, replace underscores/dashes with space, collapse spaces, lowercase
  return fileName
    .replace(/\.xlsx?$/i, "")
    .replace(/[_\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

async function ozonBindMerge() {
  if (!_ozonBindFiles.length) return;
  _bindLog("═══════════════════════════════", "info");
  _bindLog("⚡ Начало объединения…", "info");
  _ozonBindMerged = [];

  // Group files by normalized name
  const groups = new Map(); // normalizedName → [{name, arrayBuffer}]
  for (const f of _ozonBindFiles) {
    if (!groups.has(f.normalizedName)) groups.set(f.normalizedName, []);
    groups.get(f.normalizedName).push(f);
  }

  let mergedCount = 0;
  let skippedCount = 0;

  for (const [normName, files] of groups) {
    if (files.length === 1) {
      _bindLog(`<span style="color:#d97706">⚠ Нет пары для: <b>${esc(files[0].name)}</b> — добавлен без объединения</span>`, "warn");
      // Add as-is (no merge needed)
      const blob = new Blob([files[0].arrayBuffer], {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"});
      _ozonBindMerged.push({ name: files[0].name, blob });
      skippedCount++;
      continue;
    }

    _bindLog(`📎 Объединение <b>${files.length}</b> файлов: «${esc(files[0].name)}»`, "info");

    try {
      if (typeof JSZip === "undefined") {
        _bindLog('<span style="color:#b91c1c">Ошибка: JSZip не загружен. Перезагрузите страницу.</span>', "err");
        return;
      }
      const mergedBlob = await _bindMergeXlsx(files);
      const outputName = files[0].name; // Use first file's original name
      _ozonBindMerged.push({ name: outputName, blob: mergedBlob });
      _bindLog(`✅ Объединено → <b>${esc(outputName)}</b> (${files.length} источника)`, "ok");
      mergedCount++;
    } catch (e) {
      _bindLog(`<span style="color:#b91c1c">❌ Ошибка объединения «${esc(files[0].name)}»: ${esc(String(e))}</span>`, "err");
      skippedCount++;
    }
  }

  _bindLog("═══════════════════════════════", "info");
  _bindLog(`Готово. Объединено: <b>${mergedCount}</b>. Не объединено: <b style="color:${skippedCount?'#b91c1c':'inherit'}">${skippedCount}</b>.`, "info");

  const canDownload = _ozonBindMerged.length > 0;
  document.getElementById("ozonBindDownloadBtn").disabled = !canDownload;
  document.getElementById("ozonBindDownloadBtn").style.opacity = canDownload ? "1" : "0.4";
}
window.ozonBindMerge = ozonBindMerge;

async function _bindMergeXlsx(files) {
  // Load all zips
  const zips = [];
  for (const f of files) {
    const z = await JSZip.loadAsync(f.arrayBuffer);
    zips.push(z);
  }

  // Use first file as base
  const baseZip = zips[0];

  // Find the first sheet XML path in workbook
  const sheetPath = await _bindFindSheetPath(baseZip);

  // Get base sheet XML
  let baseSheetXml = await baseZip.file(sheetPath)?.async("string") || "";

  // Extract header row and data rows from base
  const baseRows = _bindExtractRows(baseSheetXml);
  // Data rows = rows 2+, filtered to only rows that have actual cell values
  let allDataRows = baseRows.slice(1).filter(_bindRowHasValues);

  // Append data rows from other files (also filtered)
  // Convert shared strings to inline to avoid index mismatch between files
  for (let i = 1; i < zips.length; i++) {
    const sp = await _bindFindSheetPath(zips[i]);
    const xml = await zips[i].file(sp)?.async("string") || "";
    const ss = await _bindGetSharedStrings(zips[i]);
    const rows = _bindExtractRows(xml);
    const converted = rows.slice(1)
      .filter(_bindRowHasValues)
      .map(r => ss.length ? _bindConvertSharedStrings(r, ss) : r);
    allDataRows = allDataRows.concat(converted);
  }

  // Renumber all rows (header=1, data=2,3,...)
  const headerRow = _bindRenumberRow(baseRows[0], 1);
  const numberedData = allDataRows.map((r, idx) => _bindRenumberRow(r, idx + 2));
  const newRows = [headerRow, ...numberedData].join("\n");

  // Replace sheetData in base XML
  const newSheetXml = baseSheetXml.replace(
    /<sheetData>[\s\S]*?<\/sheetData>/,
    `<sheetData>\n${newRows}\n</sheetData>`
  );

  // Build output zip (copy base, replace sheet)
  const outZip = new JSZip();
  const baseFiles = baseZip.files;
  for (const [path, zipObj] of Object.entries(baseFiles)) {
    if (zipObj.dir) { outZip.folder(path); continue; }
    if (path === sheetPath) {
      outZip.file(path, newSheetXml);
    } else {
      const content = await zipObj.async("arraybuffer");
      outZip.file(path, content);
    }
  }

  return await outZip.generateAsync({ type: "blob", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
}

async function _bindFindSheetPath(zip) {
  // Default: xl/worksheets/sheet1.xml
  // Check workbook.xml.rels for sheet order
  const defaultPath = "xl/worksheets/sheet1.xml";
  if (zip.file(defaultPath)) return defaultPath;
  // Try to find any sheet
  const keys = Object.keys(zip.files);
  const sheet = keys.find(k => k.match(/xl\/worksheets\/sheet\d+\.xml/));
  return sheet || defaultPath;
}

function _bindExtractRows(sheetXml) {
  // Extract <row ...>...</row> elements from sheetData
  const sdMatch = sheetXml.match(/<sheetData>([\s\S]*?)<\/sheetData>/);
  if (!sdMatch) return [];
  const sdContent = sdMatch[1];
  const rows = [];
  const rowRegex = /<row\b[^>]*>[\s\S]*?<\/row>/g;
  let m;
  while ((m = rowRegex.exec(sdContent)) !== null) {
    rows.push(m[0]);
  }
  return rows;
}

async function _bindGetSharedStrings(zip) {
  const xml = await zip.file("xl/sharedStrings.xml")?.async("string") || "";
  if (!xml) return [];
  const strings = [];
  const siRegex = /<si>([\s\S]*?)<\/si>/g;
  let m;
  while ((m = siRegex.exec(xml)) !== null) {
    // Concatenate all <t> fragments (handles rich text)
    const tRegex = /<t[^>]*>([^<]*)<\/t>/g;
    let text = ""; let tm;
    while ((tm = tRegex.exec(m[1])) !== null) text += tm[1];
    strings.push(text);
  }
  return strings;
}

function _bindConvertSharedStrings(rowXml, sharedStrings) {
  // Replace t="s" shared-string cells with t="inlineStr" inline cells
  return rowXml.replace(
    /<c([^>]*)\bt="s"([^>]*)>\s*<v>(\d+)<\/v>\s*<\/c>/g,
    (match, pre, post, idxStr) => {
      const value = sharedStrings[parseInt(idxStr, 10)] || "";
      const safe = value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      // Keep all attributes except t="s", add t="inlineStr"
      const attrs = (pre + post).replace(/\s*\bt="s"/, "").trim();
      return `<c ${attrs} t="inlineStr"><is><t>${safe}</t></is></c>`;
    }
  );
}

function _bindRowHasValues(rowXml) {
  // Row is considered non-empty if it has at least one cell with a <v> value
  return /<v[^/]/.test(rowXml) || /<v\/>/.test(rowXml) || /t="inlineStr"/.test(rowXml);
}

function _bindRenumberRow(rowXml, newRowNum) {
  // Update r="N" attribute on <row> element
  let updated = rowXml.replace(/(<row\b[^>]*\b)r="(\d+)"/, `$1r="${newRowNum}"`);
  // Update cell r="X{N}" references (column letter + row number)
  updated = updated.replace(/\br="([A-Z]+)\d+"/g, `r="$1${newRowNum}"`);
  return updated;
}

function ozonBindDownload() {
  if (!_ozonBindMerged.length) return;
  _bindLog("═══════════════════════════════", "info");
  _bindLog(`📂 Готово к скачиванию <b>${_ozonBindMerged.length}</b> файлов — нажмите каждую кнопку:`, "info");
  _ozonBindMerged.forEach(({ name, blob }, i) => {
    const url = URL.createObjectURL(blob);
    const line = document.createElement("div");
    line.style.cssText = "display:flex;align-items:center;gap:8px;margin:3px 0";
    const btn = document.createElement("button");
    btn.className = "secondary";
    btn.style.cssText = "font-size:12px;padding:3px 10px;flex-shrink:0";
    btn.textContent = "⬇ Скачать";
    btn.onclick = async () => {
      // Convert blob to base64 and embed in an HTML page that opens in new tab
      // This is the only cross-browser way to get both: new tab + correct filename
      const dataUrl = await new Promise(resolve => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result);
        reader.readAsDataURL(blob);
      });
      const safeName = name.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
      const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${esc(name)}</title></head>
<body><p style="font-family:sans-serif;color:#64748b">Скачивание файла <b>${esc(name)}</b>…</p>
<script>
(function(){
  var a=document.createElement('a');
  a.href='${dataUrl}';
  a.download='${safeName}';
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  setTimeout(function(){window.close();},1500);
})();
<\/script></body></html>`;
      const htmlBlob = new Blob([html], {type: "text/html"});
      const htmlUrl = URL.createObjectURL(htmlBlob);
      window.open(htmlUrl, "_blank");
      setTimeout(() => URL.revokeObjectURL(htmlUrl), 5000);
      btn.textContent = "✓ Скачан";
      btn.style.color = "#16a34a";
    };
    const nameSpan = document.createElement("span");
    nameSpan.style.cssText = "font-size:12px;color:#1e293b;word-break:break-all";
    nameSpan.textContent = name;
    line.appendChild(btn);
    line.appendChild(nameSpan);
    const log = document.getElementById("ozonBindLog");
    if (log) { log.appendChild(line); log.scrollTop = log.scrollHeight; }
  });
}
window.ozonBindDownload = ozonBindDownload;

function _bindLog(html, type) {
  const log = document.getElementById("ozonBindLog");
  if (!log) return;
  // Clear placeholder on first real message
  if (log.querySelector("span[style*='94a3b8']")) log.innerHTML = "";
  const line = document.createElement("div");
  line.innerHTML = html;
  if (type === "err") line.style.color = "#b91c1c";
  else if (type === "ok") line.style.color = "#16a34a";
  else if (type === "warn") line.style.color = "#d97706";
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}
window.onOzonDriverSelectChange = onOzonDriverSelectChange;

function copyOzonDetails() {
  const get = (id) => (document.getElementById(id)?.textContent || "").trim();
  const val = (id) => (document.getElementById(id)?.value || "").trim();
  const driverSel = document.getElementById("ozonSdDriverSelect");
  const driverVal = driverSel
    ? Array.from(driverSel.options).find((o) => o.value === driverSel.value)?.text || ""
    : "";
  const lines = [
    `Поставка №: ${get("ozonSdOrderNum")}`,
    `Дата поставки: ${get("ozonSdDate")}`,
    `Склад: ${document.getElementById("ozonSdWarehouse")?.innerText || get("ozonSdWarehouse") || "—"}`,
    `Производство: ${document.getElementById("ozonSdProduction")?.value || "—"}`,
    `Количество: ${get("ozonSdQty")}`,
    `Паллет: ${val("ozonSdPallets") || "—"}`,
    `Тип поставки: ${get("ozonSdType")}`,
    `Водитель: ${driverVal || "—"}`,
    `Примечание: ${val("ozonSdNotes") || "—"}`,
  ];
  navigator.clipboard.writeText(lines.join("\n")).then(() => {
    const info = document.getElementById("ozonSdInfo");
    if (info) { info.textContent = "Скопировано!"; setTimeout(() => { info.textContent = ""; }, 2000); }
  }).catch(() => {});
}
window.toggleOzonDatePanel = toggleOzonDatePanel;
window.clearOzonDateFilter = clearOzonDateFilter;
window._ozonCalPickDate = _ozonCalPickDate;
window._ozonCalPrevMonth = _ozonCalPrevMonth;
window._ozonCalNextMonth = _ozonCalNextMonth;
window._ozonCalHover = _ozonCalHover;
window._ozonCalClearHover = _ozonCalClearHover;

// ── Batch supply selection ────────────────────────────────────────────────
let _selectedSupplyIds = new Set();

function onSupplyCheckboxChange() {
  _selectedSupplyIds.clear();
  document.querySelectorAll(".supply-row-checkbox:checked").forEach(cb => {
    _selectedSupplyIds.add(Number(cb.dataset.supplyId));
  });
  _updateBatchActionUI();
}

function toggleSelectAllSupplies(checked) {
  document.querySelectorAll(".supply-row-checkbox").forEach(cb => { cb.checked = checked; });
  onSupplyCheckboxChange();
}

function _updateBatchActionUI() {
  const count = _selectedSupplyIds.size;
  const wrap = document.getElementById("suppliesBatchWrap");
  const btn = document.getElementById("suppliesBatchBtn");
  const countEl = document.getElementById("suppliesBatchCount");
  if (!wrap) return;

  if (count < 2) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "";
  if (countEl) countEl.textContent = `(${count})`;

  const selectedItems = suppliesState.items.filter(x => _selectedSupplyIds.has(x.supply_id));
  const drivers = [...new Set(selectedItems.map(x => (x.driver_name || "").trim()))];
  const legalEntities = [...new Set(selectedItems.map(x => (x.supplier_name || "").trim()))];
  const sameDriver = drivers.length === 1 && drivers[0] !== "";
  const sameLegal = legalEntities.length === 1;
  const allHavePassNumber = selectedItems.every(x => _isWbGiCode(x.pass_number));

  if (btn) {
    btn.disabled = !sameDriver || !sameLegal || !allHavePassNumber;
    btn.title = !sameDriver
      ? "Все поставки должны иметь одного водителя"
      : !sameLegal
      ? "Все поставки должны иметь одно юридическое лицо"
      : !allHavePassNumber
      ? "У некоторых поставок не заполнен ШК поставки"
      : "";
  }
}

function toggleSuppliesBatchMenu(e) {
  e.stopPropagation();
  const menu = document.getElementById("suppliesBatchMenu");
  if (!menu) return;
  const isHidden = menu.classList.contains("hidden");
  menu.classList.toggle("hidden", !isHidden);
  if (!isHidden) return;
  const close = () => { menu.classList.add("hidden"); document.removeEventListener("click", close); };
  setTimeout(() => document.addEventListener("click", close), 10);
}

function _getCombinedDocNumber() {
  const now = new Date();
  const dd = String(now.getDate()).padStart(2,"0");
  const mm = String(now.getMonth()+1).padStart(2,"0");
  const yyyy = now.getFullYear();
  const dateKey = `${dd}${mm}${yyyy}`;
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem("combined_doc_counter") || "{}"); } catch(_) {}
  const n = stored.date === dateKey ? (stored.n || 0) + 1 : 1;
  try { localStorage.setItem("combined_doc_counter", JSON.stringify({ date: dateKey, n })); } catch(_) {}
  return `${dateKey}_${n}`;
}

async function _getCombinedGoods() {
  const ids = [..._selectedSupplyIds];
  const allGoods = [];
  for (const sid of ids) {
    try {
      const r = await fetch(`/api/supplies/${sid}/goods`).catch(()=>null);
      if (r && r.ok) {
        const goods = await r.json().catch(()=>[]);
        goods.forEach(g => allGoods.push(g));
      }
    } catch(_) {}
  }
  return allGoods;
}

async function downloadCombinedPoA() {
  document.getElementById("suppliesBatchMenu")?.classList.add("hidden");
  const ids = [..._selectedSupplyIds];
  const items = suppliesState.items.filter(x => ids.includes(x.supply_id));
  if (!items.length) return;
  const refItem = items[0];

  if (!_supplyLegalEntitiesCache.length) await loadSupplyLegalEntities();
  const supplierShort = refItem.supplier_name || "";
  const le = _supplyLegalEntitiesCache.find(e => e.short_name === supplierShort) || _supplyLegalEntitiesCache[0] || {};
  const orgFull = le.full_name || supplierShort;
  const orgLine = [orgFull, le.requisites].filter(Boolean).join(", ");
  const driverName = refItem.driver_name || "";
  const driverObj = _supplyDriversCache.find(d => d.full_name === driverName) || {};
  const driverDocs = refItem._manual_driver_docs !== undefined ? refItem._manual_driver_docs : (driverObj.documents || "");
  const docNum = _getCombinedDocNumber();
  const now = new Date();
  const dateDisplay = now.toLocaleDateString("ru-RU", {day:"2-digit",month:"2-digit",year:"numeric"});

  const allGoods = await _getCombinedGoods();

  const goodsRows = allGoods.map((g, i) => `<tr>
    <td>${i+1}</td>
    <td>${esc(g.product_name||g.vendor_code||"Товар")}</td>
    <td>шт.</td>
    <td>${g.quantity??0}</td>
  </tr>`).join("");

  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8">
<style>
  @page{size:210mm 297mm;margin:15mm 10mm 15mm 25mm}body{font-family:"Times New Roman",serif;font-size:11pt;line-height:1.4}
  .small{font-size:8pt;text-align:center}.underline{text-decoration:underline}.center{text-align:center}.bold{font-weight:bold}
  table.codes{border-collapse:collapse;margin-left:auto;font-size:9pt}table.codes td{border:1px solid #000;padding:2pt 6pt}
  table.mat{width:100%;border-collapse:collapse;margin-top:6pt;font-size:10pt}
  table.mat td,table.mat th{border:1px solid #000;padding:3pt 5pt;text-align:center}
  p{margin:3pt 0}.dotline{display:inline-block;border-bottom:1px solid #000;min-width:120pt}
</style></head><body>
<table style="width:100%;border-collapse:collapse;margin-bottom:8pt"><tr>
  <td style="width:55%;vertical-align:top">${esc(orgFull)}</td>
  <td style="width:45%;vertical-align:top;text-align:right;font-size:8pt">
    Типовая межотраслевая форма № М-2<br>Утверждена постановлением Госстата России от 30.10.97 № 71а<br>
    <table class="codes"><tr><td colspan="2" class="bold center">Коды</td></tr>
    <tr><td>Форма по ОКУД</td><td>0315001</td></tr><tr><td>по ОКПО</td><td>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</td></tr></table>
  </td></tr></table>
<p style="text-align:center;font-size:14pt;font-weight:bold;margin:10pt 0 4pt"><b>Доверенность № ${docNum}</b></p>
<p>Дата выдачи <span class="underline bold">${dateDisplay}</span></p>
<p>Доверенность действительна 14 дней с даты подписания.</p>
<p style="margin-top:6pt">${esc(orgLine)}</p><p class="small">наименование потребителя и его адрес</p>
<p style="margin-top:4pt">${esc(orgLine)}</p><p class="small">наименование плательщика и его адрес</p>
<p style="margin-top:8pt">Доверенность выдана &nbsp;<u>водителю</u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; <u>${esc(driverName)}</u></p>
<p class="small" style="padding-left:80pt">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; фамилия, имя, отчество</p>
${driverDocs ? `<p>${esc(driverDocs)}</p>` : ""}
<p style="margin-top:6pt">На отправку груза от &nbsp;<u>&nbsp;${esc(supplierShort)}&nbsp;</u></p>
<p class="small" style="text-align:center">наименование поставщика</p>
<p style="margin-top:4pt">материальных ценностей по транспортным накладным суммарно</p>
<p style="margin-top:10pt">Перечень материальных ценностей, подлежащих доставке</p>
<table class="mat">
  <tr><th style="width:8%">№</th><th style="width:44%">Материальные ценности</th><th style="width:16%">Ед. изм.</th><th style="width:32%">Количество</th></tr>
  ${goodsRows}
</table>
<p style="margin-top:18pt">Подпись лица, получившего доверенность удостоверяем. &nbsp;&nbsp;&nbsp;&nbsp; ______________________________ &nbsp;&nbsp; (${esc(driverName)})</p>
<table style="width:100%;margin-top:18pt;border-collapse:collapse">
  <tr>
    <td style="width:25%;vertical-align:bottom">Руководитель<br><small>М.П.</small></td>
    <td style="width:30%;vertical-align:bottom;text-align:center">______________________________<br><small>подпись</small></td>
    <td style="width:45%;vertical-align:bottom;text-align:center">${esc(le.signatories||supplierShort)}<br><small>расшифровка подписи</small></td>
  </tr>
</table>
</body></html>`;

  const blob = new Blob(["\uFEFF" + html], {type:"application/msword"});
  const url = URL.createObjectURL(blob);
  const win = window.open("","_blank");
  if (win) {
    const a = win.document.createElement("a"); a.href=url; a.download=`Доверенность суммарная ${docNum}.doc`;
    win.document.body.appendChild(a); a.click();
    setTimeout(()=>{try{win.close();}catch(_){} URL.revokeObjectURL(url);},1500);
  }
}

async function printCombinedPoA() {
  document.getElementById("suppliesBatchMenu")?.classList.add("hidden");
  const ids = [..._selectedSupplyIds];
  const url = `/api/supplies/combined-poa.pdf?ids=${ids.join(",")}`;
  const win = window.open(url, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}

async function downloadCombinedTTN() {
  document.getElementById("suppliesBatchMenu")?.classList.add("hidden");
  if (typeof JSZip === "undefined") { alert("JSZip не загружен. Перезагрузите страницу."); return; }
  const ids = [..._selectedSupplyIds];
  const docNum = _getCombinedDocNumber();

  if (!_supplyLegalEntitiesCache.length) await loadSupplyLegalEntities();
  const refItem = suppliesState.items.find(x => ids.includes(x.supply_id)) || {};
  const supplierShort = refItem.supplier_name || "";
  const le = _supplyLegalEntitiesCache.find(e => e.short_name === supplierShort) || _supplyLegalEntitiesCache[0] || {};
  const orgLine = [le.full_name||supplierShort, le.requisites].filter(Boolean).join(", ");
  const driverName = refItem.driver_name || "";
  const pallets = parseInt(refItem.pallets_count) || 0;

  const now = new Date();
  const dd=String(now.getDate()).padStart(2,"0"), mm=String(now.getMonth()+1).padStart(2,"0"), yyyy=now.getFullYear();
  const dateDisp = `${dd}.${mm}.${yyyy}`;

  // Fetch all goods from all selected supplies
  let allGoods = [];
  let nmPrices = {};
  for (const sid of ids) {
    try {
      const gr = await fetch(`/api/supplies/${sid}/goods`).catch(()=>null);
      if (gr&&gr.ok) { const g=await gr.json().catch(()=>[]); allGoods=allGoods.concat(g); }
      const pr = await fetch(`/api/supplies/${sid}/nm-prices`).catch(()=>null);
      if (pr&&pr.ok) { const pd=await pr.json().catch(()=>{}); Object.assign(nmPrices, pd.prices||{}); }
    } catch(_){}
  }

  const VAT_RATE=0.22; const fmt2=(n)=>Number(n).toLocaleString("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2});
  const esc_=(s)=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  let totalExcl=0,totalVat=0,totalIncl=0;
  const qtyTotal = allGoods.reduce((s,g)=>s+(parseInt(g.quantity)||0),0);

  // Load TTN template and fill
  const tplResp = await fetch("/static/torg12_tpl.docx").catch(()=>null);
  if (!tplResp||!tplResp.ok) { alert("Шаблон ТТН не найден"); return; }
  const tplData = await tplResp.arrayBuffer();
  const zip = await JSZip.loadAsync(tplData);
  let docXml = await zip.file("word/document.xml").async("string");
  const rpl=(xml,ph,val)=>xml.split(ph).join(val.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"));

  const dataRowRx=/(<w:tr[\s>](?:(?!<\/w:tr>).)*?\{\{GOODS_NAME\}\}.*?<\/w:tr>)/s;
  const dataRowMatch=docXml.match(dataRowRx);
  const fmtP=(p)=>Number(p).toLocaleString("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2});
  if (dataRowMatch&&allGoods.length) {
    const rowTpl=dataRowMatch[1];
    const rows=allGoods.map((g,i)=>{
      const qty=parseInt(g.quantity)||0; const nm=String(g.nm_id||"");
      const pI=(nm&&nmPrices[nm])?parseFloat(nmPrices[nm]):null;
      const pE=pI!=null?pI/(1+VAT_RATE):null; const aE=pE!=null?pE*qty:null;
      const vA=aE!=null?aE*VAT_RATE:null; const aI=aE!=null?aE+vA:null;
      if(aE!=null){totalExcl+=aE;totalVat+=vA;totalIncl+=aI;}
      return rowTpl.replace("{{ROW_NUM}}",String(i+1))
        .replace("{{GOODS_NAME}}",esc_(g.product_name||g.vendor_code||"Товар"))
        .replace("{{PRICE}}",esc_(pE!=null?fmtP(pE):"—"))
        .split("{{ROW_QTY}}").join(String(qty))
        .replace("{{ROW_AMOUNT_EXCL}}",esc_(aE!=null?fmtP(aE):"—"))
        .replace("{{ROW_VAT_SUM}}",esc_(vA!=null?fmtP(vA):"—"))
        .replace("{{ROW_AMOUNT_INCL}}",esc_(aI!=null?fmtP(aI):"—"));
    }).join("");
    docXml=docXml.replace(rowTpl,rows,1);
  }
  const fmtN=(n)=>n>0?fmt2(n):"—";
  const amtWords=totalIncl>0?_rublesInWords(Math.round(totalIncl)):"—";
  for(const [ph,val] of [
    ["{{TTN_NUMBER}}",docNum],["{{ORG_FULL}}",orgLine],["{{SUPPLIER}}",orgLine],["{{PAYER}}",orgLine],
    ["{{ORDER_DATE}}",ids.join(", ")],["{{DOC_NUM_VAL}}",docNum],["{{DOC_DATE_VAL}}",dateDisp],
    ["{{GOODS_NAME}}",allGoods[0]?.product_name||"Товар"],["{{ROW_NUM}}","1"],
    ["{{PRICE}}","—"],["{{ROW_AMOUNT_EXCL}}","—"],["{{ROW_VAT_SUM}}","—"],["{{ROW_AMOUNT_INCL}}","—"],
    ["{{QTY}}",String(qtyTotal)],["{{QTY_SHT}}",`${qtyTotal} шт`],
    ["{{TOTAL_EXCL}}",fmtN(totalExcl)],["{{TOTAL_VAT}}",fmtN(totalVat)],["{{TOTAL_INCL}}",fmtN(totalIncl)],
    ["{{AMOUNT}}",fmtN(totalExcl)],["{{VAT_SUM}}",fmtN(totalVat)],["{{AMOUNT_WITH_VAT}}",fmtN(totalIncl)],
    ["{{TOTAL_RUB}}",String(Math.floor(totalIncl||0))],["{{TOTAL_KOP}}","00"],
    ["{{PAGES_COUNT}}","1"],["{{ITEMS_COUNT}}",String(allGoods.length)],
    ["{{SUPPLY_ID}}",docNum],["{{DOC_DATE_FULL}}",`«${dd}» ${["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"][now.getMonth()]} ${yyyy}`],
    ["{{ISSUED_BY}}",supplierShort||"—"],
    ["{{SIGNATORIES}}",le.signatories||supplierShort||"—"],
    ["{{PROD_HEAD}}",le.signatories||supplierShort||"—"],["{{SIGN_SUPPLIER}}",supplierShort],["{{SIGN_DRIVER}}",driverName],
    ["{{AMOUNT_WORDS}}",amtWords],
  ]) { docXml=rpl(docXml,ph,val); }
  docXml=docXml.replace(/\{\{ROW_QTY\}\}/g,String(qtyTotal));

  zip.file("word/document.xml",docXml);
  const blob=await zip.generateAsync({type:"blob",mimeType:"application/vnd.openxmlformats-officedocument.wordprocessingml.document"});
  const url=URL.createObjectURL(blob);
  const win=window.open("","_blank");
  if(win){const a=win.document.createElement("a");a.href=url;a.download=`ТТН суммарная ${docNum}.docx`;win.document.body.appendChild(a);a.click();setTimeout(()=>{try{win.close();}catch(_){}URL.revokeObjectURL(url);},1500);}
}

async function printCombinedTTN() {
  document.getElementById("suppliesBatchMenu")?.classList.add("hidden");
  const ids = [..._selectedSupplyIds];
  const url = `/api/supplies/combined-ttn.pdf?ids=${ids.join(",")}`;
  const win = window.open(url, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}

window.onSupplyCheckboxChange = onSupplyCheckboxChange;
window.toggleSelectAllSupplies = toggleSelectAllSupplies;
window.toggleSuppliesBatchMenu = toggleSuppliesBatchMenu;
window.downloadCombinedPoA = downloadCombinedPoA;
window.printCombinedPoA = printCombinedPoA;
window.downloadCombinedTTN = downloadCombinedTTN;
window.printCombinedTTN = printCombinedTTN;

// ── Supplies column resizer ──
const SUPPLIES_COL_WIDTHS_KEY = "supplies_col_widths";
// Default widths as percentages (9 columns: expand, id, legal, wh, prod, date, qty, status, links)
// Must sum to 100
const SUPPLIES_DEFAULT_WIDTHS = [3, 9, 14, 19, 10, 9, 7, 11, 18];

function initSuppliesColumnResizer() {
  const table = document.getElementById("suppliesTable");
  if (!table) return;
  let widths = SUPPLIES_DEFAULT_WIDTHS.slice();
  try {
    const saved = JSON.parse(localStorage.getItem(SUPPLIES_COL_WIDTHS_KEY) || "null");
    // Only restore if saved widths match current column count
    if (Array.isArray(saved) && saved.length === widths.length) widths = saved;
    else if (Array.isArray(saved)) localStorage.removeItem(SUPPLIES_COL_WIDTHS_KEY);
  } catch (_) {}
  _applySuppliesColWidths(widths);

  // Attach drag handlers to resize handles
  table.querySelectorAll("th .col-resize-handle").forEach((handle) => {
    let startX = 0, colIdx = 0, startWidths = [];
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const th = handle.parentElement;
      colIdx = parseInt(th.getAttribute("data-col") || "0");
      startX = e.clientX;
      startWidths = _getSuppliesColWidths();
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    });
    function onMouseMove(e) {
      const tableEl = document.getElementById("suppliesTable");
      if (!tableEl) return;
      const tableW = tableEl.offsetWidth || 1;
      const deltaPct = ((e.clientX - startX) / tableW) * 100;
      const newWidths = startWidths.slice();
      const minPct = 3;
      const nextIdx = colIdx < newWidths.length - 1 ? colIdx + 1 : colIdx - 1;
      let newCur = Math.max(minPct, startWidths[colIdx] + deltaPct);
      let newNext = Math.max(minPct, startWidths[nextIdx] - deltaPct);
      // Clamp so total stays stable
      const diff = newCur - startWidths[colIdx];
      if (newNext < minPct) {
        newCur = startWidths[colIdx] + (startWidths[nextIdx] - minPct);
        newNext = minPct;
      }
      newWidths[colIdx] = Math.round(newCur * 10) / 10;
      newWidths[nextIdx] = Math.round(newNext * 10) / 10;
      _applySuppliesColWidths(newWidths);
    }
    function onMouseUp() {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      // Save current widths
      try {
        localStorage.setItem(SUPPLIES_COL_WIDTHS_KEY, JSON.stringify(_getSuppliesColWidths()));
      } catch (_) {}
    }
  });
}

function _applySuppliesColWidths(widths) {
  // Skip cols with data-fixed attribute (e.g. checkbox col)
  const cols = Array.from(document.querySelectorAll("#suppliesColgroup col"))
    .filter(c => !c.dataset.fixed);
  cols.forEach((col, i) => {
    if (widths[i] !== undefined) col.style.width = widths[i] + "%";
  });
}

function _getSuppliesColWidths() {
  const cols = Array.from(document.querySelectorAll("#suppliesColgroup col"))
    .filter(c => !c.dataset.fixed);
  return cols.map((col) => parseFloat(col.style.width) || SUPPLIES_DEFAULT_WIDTHS[0]);
}

function toggleSuppliesFilter() { /* legacy stub */ }

// ── OZON Supplies column resizer ──
const OZON_SUPPLIES_COL_WIDTHS_KEY = "ozon_supplies_col_widths";
// Default widths as percentages (9 logical cols: expand, id, legal, wh, prod, date, qty, status, links)
const OZON_SUPPLIES_DEFAULT_WIDTHS = [3, 9, 11, 19, 9, 9, 6, 11, 23];
let _ozonColResizerInited = false;

function initOzonSuppliesColumnResizer() {
  const table = document.getElementById("ozonSuppliesTable");
  if (!table) return;

  // Apply saved/default widths every time (handles page reloads)
  let widths = OZON_SUPPLIES_DEFAULT_WIDTHS.slice();
  try {
    const saved = JSON.parse(localStorage.getItem(OZON_SUPPLIES_COL_WIDTHS_KEY) || "null");
    if (Array.isArray(saved) && saved.length === widths.length) widths = saved;
    else if (Array.isArray(saved)) localStorage.removeItem(OZON_SUPPLIES_COL_WIDTHS_KEY);
  } catch (_) {}
  _applyOzonSuppliesColWidths(widths);

  // Attach drag handlers only once
  if (_ozonColResizerInited) return;
  _ozonColResizerInited = true;

  table.querySelectorAll("th .col-resize-handle").forEach((handle) => {
    let startX = 0, colIdx = 0, startWidths = [];
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const th = handle.parentElement;
      colIdx = parseInt(th.getAttribute("data-col") || "0");
      startX = e.clientX;
      startWidths = _getOzonSuppliesColWidths();
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    });
    function onMouseMove(e) {
      const tableEl = document.getElementById("ozonSuppliesTable");
      if (!tableEl) return;
      const tableW = tableEl.offsetWidth || 1;
      const deltaPct = ((e.clientX - startX) / tableW) * 100;
      const newWidths = startWidths.slice();
      const minPct = 3;
      const nextIdx = colIdx < newWidths.length - 1 ? colIdx + 1 : colIdx - 1;
      let newCur = Math.max(minPct, startWidths[colIdx] + deltaPct);
      let newNext = Math.max(minPct, startWidths[nextIdx] - deltaPct);
      if (newNext < minPct) {
        newCur = startWidths[colIdx] + (startWidths[nextIdx] - minPct);
        newNext = minPct;
      }
      newWidths[colIdx] = Math.round(newCur * 10) / 10;
      newWidths[nextIdx] = Math.round(newNext * 10) / 10;
      _applyOzonSuppliesColWidths(newWidths);
    }
    function onMouseUp() {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      try {
        localStorage.setItem(OZON_SUPPLIES_COL_WIDTHS_KEY, JSON.stringify(_getOzonSuppliesColWidths()));
      } catch (_) {}
    }
  });
}

function _applyOzonSuppliesColWidths(widths) {
  const cols = Array.from(document.querySelectorAll("#ozonSuppliesColgroup col"))
    .filter(c => !c.dataset.fixed);
  cols.forEach((col, i) => {
    if (widths[i] !== undefined) col.style.width = widths[i] + "%";
  });
}

function _getOzonSuppliesColWidths() {
  const cols = Array.from(document.querySelectorAll("#ozonSuppliesColgroup col"))
    .filter(c => !c.dataset.fixed);
  return cols.map((col) => parseFloat(col.style.width) || OZON_SUPPLIES_DEFAULT_WIDTHS[0]);
}

// ── Supplies date range calendar ──
const _cal = {
  viewYear: new Date().getFullYear(),
  viewMonth: new Date().getMonth(), // 0-11
  startDate: null, // Date or null
  endDate: null,   // Date or null
  hoveredDate: null,
};
const _calMonths = ["Январь","Февраль","Март","Апрель","Май","Июнь",
  "Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"];
const _calDays = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"];

function _calRender() {
  const container = document.getElementById("suppliesCalendar");
  if (!container) return;
  const { viewYear: y, viewMonth: m, startDate: s, endDate: e, hoveredDate: h } = _cal;
  const firstDay = new Date(y, m, 1);
  const lastDay = new Date(y, m + 1, 0);
  let startOffset = (firstDay.getDay() + 6) % 7;
  const today = new Date(); today.setHours(0,0,0,0);
  const fmtDisp = (d) => d ? `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}.${d.getFullYear()}` : "";

  let html = `<div class="cal-header" onclick="event.stopPropagation()">
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_calPrevMonth()">◄</button>
    <span class="cal-title">${_calMonths[m]} ${y}</span>
    <button type="button" class="cal-nav" onclick="event.stopPropagation();_calNextMonth()">►</button>
  </div>
  <div class="cal-grid" onmouseleave="_calClearHover()">`;
  _calDays.forEach((d) => { html += `<div class="cal-cell cal-dow">${d}</div>`; });
  for (let i = 0; i < startOffset; i++) html += `<div class="cal-cell cal-empty"></div>`;
  for (let d = 1; d <= lastDay.getDate(); d++) {
    const date = new Date(y, m, d);
    const isToday = date.getTime() === today.getTime();
    const isStart = s && date.getTime() === s.getTime();
    const isEnd = e && date.getTime() === e.getTime();
    const rangeEnd = e || h;
    const inRange = s && rangeEnd && date > (s < rangeEnd ? s : rangeEnd) && date < (s < rangeEnd ? rangeEnd : s);
    let cls = "cal-cell cal-day";
    if (isStart || isEnd) cls += " cal-selected";
    if (isStart) cls += " cal-range-start";
    if (isEnd) cls += " cal-range-end";
    if (inRange) cls += " cal-in-range";
    if (isToday) cls += " cal-today";
    // stopPropagation prevents the document click handler from closing the panel
    const iso = `${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
    html += `<div class="${cls}" data-date="${iso}" onclick="event.stopPropagation();_calPickDate(${y},${m},${d})" onmouseenter="_calHover(${y},${m},${d})">${d}</div>`;
  }
  html += `</div>`;
  if (s || e) {
    html += `<div class="cal-range-label" onclick="event.stopPropagation()">${fmtDisp(s) || "…"} — ${fmtDisp(e) || "…"}</div>`;
  }
  html += `<div class="cal-footer" onclick="event.stopPropagation()">
    <button type="button" class="secondary" onclick="event.stopPropagation();clearSuppliesDateFilter()">Сбросить</button>
  </div>`;
  container.innerHTML = html;
}

function _calPickDate(y, m, d) {
  const date = new Date(y, m, d);
  date.setHours(0, 0, 0, 0);
  if (!_cal.startDate || (_cal.startDate && _cal.endDate)) {
    _cal.startDate = date; _cal.endDate = null;
  } else {
    if (date < _cal.startDate) { _cal.endDate = _cal.startDate; _cal.startDate = date; }
    else if (date.getTime() === _cal.startDate.getTime()) { _cal.startDate = null; }
    else { _cal.endDate = date; }
  }
  _calRender();
  if (_cal.startDate && _cal.endDate) {
    const fmt = (dt) => `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,"0")}-${String(dt.getDate()).padStart(2,"0")}`;
    const f = document.getElementById("suppliesDateFrom");
    const t = document.getElementById("suppliesDateTo");
    if (f) f.value = fmt(_cal.startDate);
    if (t) t.value = fmt(_cal.endDate);
    loadSupplies(true);
    _updateDateBtn();
    setTimeout(() => toggleSuppliesDatePanel(false), 300);
  }
}

function _calHover(y, m, d) {
  if (!_cal.startDate || _cal.endDate) return;
  const hovered = new Date(y, m, d);
  _cal.hoveredDate = hovered;
  // Update only CSS classes — no full re-render (avoids infinite mouseenter loop)
  const s = _cal.startDate;
  document.querySelectorAll("#suppliesCalendar .cal-day[data-date]").forEach((el) => {
    const dt = new Date(el.dataset.date + "T00:00:00");
    const inRange = s && hovered && dt > (s < hovered ? s : hovered) && dt < (s < hovered ? hovered : s);
    el.classList.toggle("cal-in-range", inRange);
  });
}
function _calClearHover() {
  if (_cal.hoveredDate) {
    _cal.hoveredDate = null;
    document.querySelectorAll("#suppliesCalendar .cal-day.cal-in-range").forEach((el) => {
      el.classList.remove("cal-in-range");
    });
  }
}

function _calPrevMonth() {
  if (_cal.viewMonth === 0) { _cal.viewMonth = 11; _cal.viewYear--; }
  else _cal.viewMonth--;
  _calRender();
}
function _calNextMonth() {
  if (_cal.viewMonth === 11) { _cal.viewMonth = 0; _cal.viewYear++; }
  else _cal.viewMonth++;
  _calRender();
}

function toggleSuppliesDatePanel(show) {
  const panel = document.getElementById("suppliesDatePanel");
  if (!panel) return;
  const isVisible = panel.style.display === "flex";
  const shouldShow = show !== undefined ? Boolean(show) : !isVisible;
  panel.style.display = shouldShow ? "flex" : "none";
  if (shouldShow) _calRender();
  _updateDateBtn();
}

function _updateDateBtn() {
  const btn = document.getElementById("suppliesDateBtn");
  if (!btn) return;
  if (_cal.startDate && _cal.endDate) {
    const fmt = (d) => d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
    btn.textContent = `${fmt(_cal.startDate)}–${fmt(_cal.endDate)}`;
  } else {
    btn.textContent = "📅";
  }
}

function applySuppliesDateFilter() { loadSupplies(true); _updateDateBtn(); }

function clearSuppliesDateFilter() {
  _cal.startDate = null; _cal.endDate = null; _cal.hoveredDate = null;
  const from = document.getElementById("suppliesDateFrom");
  const to = document.getElementById("suppliesDateTo");
  if (from) from.value = "";
  if (to) to.value = "";
  _calRender();
  _updateDateBtn();
  toggleSuppliesDatePanel(false);
  loadSupplies(true);
}

let _suppliesSyncPollTimer = null;

async function syncSupplies() {
  const btn = document.getElementById("suppliesSyncBtn");
  const info = document.getElementById("suppliesSyncInfo");
  const sourceId = document.getElementById("suppliesSourceFilter")?.value || "";
  const body = sourceId ? { source_id: parseInt(sourceId) } : {};

  _setSuppliesSyncingUI(true);
  if (btn) btn.textContent = "⏳ Запуск…";
  if (info) { info.textContent = "Подключение к WB…"; info.style.color = "#64748b"; }

  const res = await fetch("/api/supplies/sync", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  }).catch(() => null);

  if (!res || !res.ok) {
    const rawText = await res?.text().catch(() => "") || "";
    let detail = `Ошибка ${res?.status || "сети"}`;
    try { detail = JSON.parse(rawText).detail || detail; } catch (_) {}
    _setSuppliesSyncingUI(false);
    if (info) { info.textContent = detail; info.style.color = "#b91c1c"; }
    return;
  }

  // Start polling for progress
  if (_suppliesSyncPollTimer) clearInterval(_suppliesSyncPollTimer);
  _suppliesSyncPollTimer = setInterval(_pollSupplySyncStatus, 800);
}

function _setSuppliesSyncingUI(isSyncing) {
  const syncBtn = document.getElementById("suppliesSyncBtn");
  const clearBtn = document.getElementById("suppliesClearBtn");
  if (syncBtn) syncBtn.disabled = isSyncing;
  if (clearBtn) clearBtn.disabled = isSyncing;
  if (!isSyncing && syncBtn) syncBtn.textContent = "🔄 Синхронизировать";
}

async function _pollSupplySyncStatus() {
  const btn = document.getElementById("suppliesSyncBtn");
  const info = document.getElementById("suppliesSyncInfo");

  const res = await fetch("/api/supplies/sync/status", { headers: jsonHeaders() }).catch(() => null);
  if (!res || !res.ok) return;
  const state = await res.json().catch(() => ({}));

  const synced = Number(state.synced ?? 0);
  const total = Number(state.total ?? 0);

  if (state.in_progress) {
    const progressText = total > 0
      ? `Загружено ${synced} из ${total} поставок`
      : synced > 0 ? `Загружено ${synced} поставок…` : "Загрузка списка…";
    if (btn) btn.textContent = `⏳ ${synced}${total > 0 ? "/" + total : ""}`;
    if (info) { info.textContent = progressText; info.style.color = "#64748b"; }
  } else {
    clearInterval(_suppliesSyncPollTimer);
    _suppliesSyncPollTimer = null;
    _setSuppliesSyncingUI(false);
    const hasErrors = Array.isArray(state.errors) && state.errors.length;
    if (info) {
      const finalText = total > 0
        ? `Готово. Загружено ${synced} из ${total} поставок.` + (hasErrors ? ` Ошибки: ${state.errors.join("; ")}` : "")
        : (state.message || `Готово. Загружено ${synced} поставок.`);
      info.textContent = finalText;
      info.style.color = hasErrors ? "#b45309" : "#16a34a";
    }
    await loadSupplies(true);
    await loadSupplySources();
  }
}

async function clearSupplies() {
  if (!confirm("Удалить все поставки из таблицы и базы данных?")) return;
  const btn = document.getElementById("suppliesClearBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Удаление…"; }
  const res = await fetch("/api/supplies", {
    method: "DELETE",
    headers: jsonHeaders(),
  }).catch(() => null);
  if (btn) { btn.disabled = false; btn.textContent = "Удалить поставки"; }
  if (!res || !res.ok) {
    alert("Ошибка при удалении");
    return;
  }
  const data = await res.json().catch(() => ({}));
  const info = document.getElementById("suppliesSyncInfo");
  if (info) { info.textContent = `Удалено ${data.deleted ?? 0} поставок`; info.style.color = "#64748b"; }
  await loadSupplies(true);
}

// ── Stock module ─────────────────────────────────────────────────────────────

let stockSourcesState = { items: [], activeSourceId: null };

function openAddStockSourceModal() {
  document.getElementById("addStockInfo").textContent = "";
  document.getElementById("addStockName").value = "";
  document.getElementById("addStockApiKey").value = "";
  document.getElementById("addStockClientId").value = "";
  const mp = document.getElementById("addStockMarketplace");
  if (mp) mp.value = "wb";
  toggleOzonClientIdRow();
  setModalVisibility("addStockSourceModal", true);
}

function closeAddStockSourceModal() {
  setModalVisibility("addStockSourceModal", false);
}

function toggleOzonClientIdRow() {
  const mp = document.getElementById("addStockMarketplace")?.value;
  const row = document.getElementById("addStockOzonClientRow");
  if (row) row.style.display = mp === "ozon" ? "flex" : "none";
}

async function confirmAddStockSource() {
  const info = document.getElementById("addStockInfo");
  const marketplace = document.getElementById("addStockMarketplace")?.value || "wb";
  const name = String(document.getElementById("addStockName")?.value || "").trim();
  const apiKey = String(document.getElementById("addStockApiKey")?.value || "").trim();
  const clientId = String(document.getElementById("addStockClientId")?.value || "").trim();
  if (!name) { if (info) info.textContent = "Введите название"; return; }
  if (!apiKey) { if (info) info.textContent = "Введите API-ключ"; return; }
  try {
    const res = await fetch("/api/stock/sources", {
      method: "POST", headers: jsonHeaders(),
      body: JSON.stringify({ marketplace, account_name: name, api_key: apiKey, client_id: clientId }),
    });
    const data = await res.json();
    if (!res.ok) { if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось добавить"); return; }
    closeAddStockSourceModal();
    await loadStockSources();
  } catch (_) { if (info) info.textContent = "Ошибка соединения"; }
}

async function loadStockSources() {
  const res = await fetch("/api/stock/sources");
  if (!res.ok) return;
  const data = await res.json();
  stockSourcesState.items = data.items || [];
  renderStockSources();
  renderStockWorkTabs();
}

function renderStockSources() {
  const tbody = document.getElementById("stockSourcesTbody");
  if (!tbody) return;
  const items = stockSourcesState.items;
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="small">Источников нет</td></tr>';
    return;
  }
  tbody.innerHTML = items.map((s, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${esc(String(s.marketplace || "").toUpperCase())}</td>
      <td>${esc(s.account_name || "")}</td>
      <td><code>${esc(s.api_key || "")}</code></td>
      <td>${esc(String(s.interval_hours || 24))} ч</td>
      <td>${s.is_active ? "Да" : "Нет"}</td>
      <td class="small">${esc(s.last_synced_at ? s.last_synced_at.slice(0, 16).replace("T", " ") : "—")}</td>
      <td>
        <button class="secondary" onclick="deleteStockSource(${s.id})">Удалить</button>
      </td>
    </tr>
  `).join("");
}

async function deleteStockSource(sourceId) {
  if (!confirm("Удалить этот источник остатков?")) return;
  const res = await fetch(`/api/stock/sources/${sourceId}`, { method: "DELETE", headers: withCsrfHeaders() });
  if (res.ok) await loadStockSources();
}

async function saveStockSourceSettings() {
  const interval = Number(document.getElementById("stockSyncInterval")?.value || 24);
  const retention = Number(document.getElementById("stockRetentionDays")?.value || 30);
  const info = document.getElementById("stockSyncInfo");
  // Save per-source (apply to all active sources)
  for (const src of stockSourcesState.items) {
    await fetch(`/api/stock/sources/${src.id}`, {
      method: "PUT", headers: jsonHeaders(),
      body: JSON.stringify({ interval_hours: interval, retention_days: retention }),
    });
  }
  if (info) info.textContent = "Сохранено";
  setTimeout(() => { if (info) info.textContent = ""; }, 3000);
}

async function syncStockSources() {
  const info = document.getElementById("stockSyncInfo");
  if (info) info.textContent = "Синхронизация...";
  try {
    const res = await fetch("/api/stock/sync", { method: "POST", headers: jsonHeaders(), body: JSON.stringify({}) });
    const data = await res.json();
    if (info) info.textContent = res.ok ? `Готово. Синхронизировано: ${data.synced}` : "Ошибка";
    await loadStockReports();
    await loadStockSources();
    if (stockSourcesState.activeSourceId) await loadStockWorkData(stockSourcesState.activeSourceId);
  } catch (_) { if (info) info.textContent = "Ошибка соединения"; }
}

async function deleteAllStockReports() {
  if (!confirm("Удалить все скачанные отчёты остатков?")) return;
  await fetch("/api/stock/reports", { method: "DELETE", headers: withCsrfHeaders() });
  await loadStockReports();
}

async function loadStockReports() {
  const res = await fetch("/api/stock/reports");
  if (!res.ok) return;
  const data = await res.json();
  const tbody = document.getElementById("stockReportsTbody");
  if (!tbody) return;
  const items = data.items || [];
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="small">Отчётов нет</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(r => {
    const src = stockSourcesState.items.find(s => s.id === r.source_id);
    const srcName = src ? esc(src.account_name) : `#${r.source_id}`;
    const date = esc((r.downloaded_at || "").slice(0, 16).replace("T", " "));
    const status = r.status === "ok" ? "✅" : `❌ ${esc(r.error_message || "")}`;
    const dl = r.file_path ? `<a href="/api/stock/reports/${r.id}/download" target="_blank">⬇ Скачать</a>` : "—";
    return `<tr><td>${srcName}</td><td>${date}</td><td>${r.rows_count || 0}</td><td>${status}</td><td>${dl}</td></tr>`;
  }).join("");
}

// ── Stock settings helpers ────────────────────────────────────────────────────

function _stockKey(sourceId, key) { return `stock_${sourceId}_${key}`; }

function _getHiddenWarehouses(sourceId) {
  try { return new Set(JSON.parse(localStorage.getItem(_stockKey(sourceId, "hidden_wh")) || "[]")); }
  catch (_) { return new Set(); }
}

function _setHiddenWarehouses(sourceId, set) {
  localStorage.setItem(_stockKey(sourceId, "hidden_wh"), JSON.stringify([...set]));
}

function _getStockThreshold(sourceId) {
  return Number(localStorage.getItem(_stockKey(sourceId, "threshold")) || 0);
}

function _setStockThreshold(sourceId, val) {
  localStorage.setItem(_stockKey(sourceId, "threshold"), String(Number(val) || 0));
}

function _getFixedColWidth(sourceId, col) {
  const defaults = { product: 200, wbid: 110 };
  return Number(localStorage.getItem(_stockKey(sourceId, `fixed_col_${col}`)) || defaults[col] || 100);
}

function _setFixedColWidth(sourceId, col, w) {
  localStorage.setItem(_stockKey(sourceId, `fixed_col_${col}`), String(w));
}

function _getDateColWidth(sourceId, colIdx) {
  return Number(localStorage.getItem(_stockKey(sourceId, `date_col_${colIdx}`)) || 110);
}

function _setDateColWidth(sourceId, colIdx, w) {
  localStorage.setItem(_stockKey(sourceId, `date_col_${colIdx}`), String(w));
}

function _getCollapsed(sourceId) {
  try { return new Set(JSON.parse(localStorage.getItem(_stockKey(sourceId, "collapsed_wh")) || "[]")); }
  catch (_) { return new Set(); }
}

function _getAllKnownWarehouses(sourceId) {
  try { return JSON.parse(localStorage.getItem(_stockKey(sourceId, "all_wh")) || "[]"); }
  catch (_) { return []; }
}

function _saveAllKnownWarehouses(sourceId, warehouses) {
  // Merge with existing known warehouses to preserve even if data changes
  const existing = _getAllKnownWarehouses(sourceId);
  const merged = [...new Set([...existing, ...warehouses])];
  localStorage.setItem(_stockKey(sourceId, "all_wh"), JSON.stringify(merged));
}

function _setCollapsed(sourceId, set) {
  localStorage.setItem(_stockKey(sourceId, "collapsed_wh"), JSON.stringify([...set]));
}

// Convert UTC ISO date string to Moscow time (UTC+3) label
function _toMsk(isoStr) {
  if (!isoStr) return "—";
  try {
    const normalized = isoStr.includes("+") || isoStr.endsWith("Z") ? isoStr : isoStr + "Z";
    const d = new Date(normalized);
    if (isNaN(d.getTime())) return isoStr.slice(0, 16);
    const msk = new Date(d.getTime() + 3 * 3600 * 1000);
    const dd = String(msk.getUTCDate()).padStart(2, "0");
    const mm = String(msk.getUTCMonth() + 1).padStart(2, "0");
    const yy = String(msk.getUTCFullYear()).slice(-2);
    const hh = String(msk.getUTCHours()).padStart(2, "0");
    const min = String(msk.getUTCMinutes()).padStart(2, "0");
    return `${dd}.${mm}.${yy} ${hh}:${min}`;
  } catch (_) { return isoStr.slice(0, 16); }
}

// ── Tab rendering ─────────────────────────────────────────────────────────────

function renderStockWorkTabs() {
  const container = document.getElementById("stockWorkSources");
  if (!container) return;
  const items = stockSourcesState.items.filter(s => s.is_active);
  if (!items.length) {
    container.innerHTML = '<p class="small" style="padding:12px;color:#9ca3af">Нет активных источников. Добавьте источник в Настройки.</p>';
    return;
  }
  // Auto-select first source if none is active
  if (!stockSourcesState.activeSourceId) {
    stockSourcesState.activeSourceId = items[0].id;
    setTimeout(() => loadStockWorkData(items[0].id), 0);
  }
  container.innerHTML = items.map(s => `
    <div class="stock-tab-group">
      <button type="button" class="stock-source-tab ${stockSourcesState.activeSourceId === s.id ? 'active' : ''}"
        onclick="selectStockSource(${s.id})">${esc(s.account_name)}</button>
      <button type="button" class="stock-tab-gear" title="Настройки отображения"
        onclick="openStockSettings(${s.id})">⚙</button>
    </div>`
  ).join("");
}

async function selectStockSource(sourceId) {
  stockSourcesState.activeSourceId = sourceId;
  renderStockWorkTabs();
  await loadStockWorkData(sourceId);
}

// ── Main data loader ──────────────────────────────────────────────────────────

async function loadStockWorkData(sourceId) {
  const wrap = document.getElementById("stockWorkTableWrap");
  if (!wrap) return;
  wrap.innerHTML = '<p class="small" style="padding:16px;color:#9ca3af">⏳ Загрузка...</p>';
  const res = await fetch(`/api/stock/data?source_id=${sourceId}`);
  if (!res.ok) { wrap.innerHTML = '<p class="small" style="padding:16px;color:#dc2626">Ошибка загрузки данных</p>'; return; }
  const data = await res.json();
  const dates = data.dates || [];
  const rows = data.rows || [];
  if (!dates.length || !rows.length) {
    wrap.innerHTML = '<p class="small" style="padding:16px;color:#9ca3af">Данных нет. Нажмите «Синхронизировать» для скачивания отчёта.</p>';
    return;
  }
  renderStockDataTable(sourceId, dates, rows, wrap);
}

function renderStockDataTable(sourceId, dates, rows, wrap) {
  const hidden = _getHiddenWarehouses(sourceId);
  const collapsed = _getCollapsed(sourceId);
  const threshold = _getStockThreshold(sourceId);
  const colWProduct = _getFixedColWidth(sourceId, "product");
  const colWWbid = _getFixedColWidth(sourceId, "wbid");

  // Group rows by warehouse
  const byWarehouse = new Map();
  for (const r of rows) {
    const wh = r.warehouse_name || "Без склада";
    if (!byWarehouse.has(wh)) byWarehouse.set(wh, []);
    byWarehouse.get(wh).push(r);
  }
  // Save all warehouse names (before filtering) so settings can show them even when hidden
  _saveAllKnownWarehouses(sourceId, [...byWarehouse.keys()]);

  // Build colgroup for reliable fixed-layout width control
  const colgroup = `<colgroup>
    <col data-col="product" style="width:${colWProduct}px">
    <col data-col="wbid" style="width:${colWWbid}px">
    ${dates.map((_, i) => `<col data-colidx="${i}" style="width:${_getDateColWidth(sourceId, i)}px">`).join("")}
  </colgroup>`;

  // Build header — each date column independent
  const dateHeaders = dates.map((d, i) =>
    `<th class="stock-date-col stock-resizable" data-col-type="date" data-colidx="${i}" data-date="${esc(d)}">${esc(_toMsk(d))}</th>`
  ).join("");

  let tbody = "";
  for (const [wh, whRows] of byWarehouse) {
    if (hidden.has(wh)) continue;
    const isCollapsed = collapsed.has(wh);
    tbody += `<tr class="stock-warehouse-row" data-wh="${esc(wh)}" data-sid="${sourceId}">
      <td colspan="${2 + dates.length}" class="stock-warehouse-cell">
        <button type="button" class="stock-collapse-btn" onclick="toggleStockWarehouse('${esc(wh)}',${sourceId})">${isCollapsed ? "▶" : "▼"}</button>
        <span class="stock-warehouse-name">${esc(wh)}</span>
      </td>
    </tr>`;
    if (!isCollapsed) {
      for (const r of whRows) {
        // Determine if any date value is below threshold
        let highlight = false;
        if (threshold > 0) {
          for (const d of dates) {
            const v = r.dates[d];
            if (v !== undefined && v < threshold) { highlight = true; break; }
          }
        }
        const rowClass = highlight ? " class=\"stock-row-low\"" : "";
        const dateCells = dates.map(d => {
          const v = r.dates[d];
          const low = threshold > 0 && v !== undefined && v < threshold;
          return `<td class="stock-num${low ? " stock-cell-low" : ""}">${v !== undefined ? v : "—"}</td>`;
        }).join("");
        tbody += `<tr${rowClass}>
          <td class="stock-product-cell">&nbsp;&nbsp;&nbsp;${esc(r.seller_article)}</td>
          <td class="stock-num">${esc(r.wb_article)}</td>
          ${dateCells}
        </tr>`;
      }
    }
  }

  wrap.innerHTML = `
    <div class="stock-table-outer">
      <table class="stock-data-table" id="stockDataTable_${sourceId}">
        ${colgroup}
        <thead>
          <tr>
            <th class="stock-fixed-col stock-col-product stock-resizable" data-col="product" style="left:0">Склад / Артикул продавца</th>
            <th class="stock-fixed-col stock-col-wbid stock-resizable" data-col="wbid" style="left:${colWProduct}px">Артикул ВБ</th>
            ${dateHeaders}
          </tr>
        </thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>`;
  _applyStockStickyOffsets(sourceId, colWProduct, colWWbid);

  // Add column resize listeners
  _initStockColResize(sourceId);
}

function toggleStockWarehouse(wh, sourceId) {
  const collapsed = _getCollapsed(sourceId);
  if (collapsed.has(wh)) collapsed.delete(wh); else collapsed.add(wh);
  _setCollapsed(sourceId, collapsed);
  loadStockWorkData(sourceId);
}

// ── Column resize ─────────────────────────────────────────────────────────────

function _applyStockStickyOffsets(sourceId, colWProduct, colWWbid) {
  const table = document.getElementById(`stockDataTable_${sourceId}`);
  if (!table) return;
  // Update wbid header left
  const wbidTh = table.querySelector("th[data-col='wbid']");
  if (wbidTh) wbidTh.style.left = colWProduct + "px";
  // Update colgroup cols
  const cols = table.querySelectorAll("colgroup col");
  if (cols[0]) cols[0].style.width = colWProduct + "px";
  if (cols[1]) cols[1].style.width = colWWbid + "px";
  // Update body cell sticky positions
  table.querySelectorAll("tbody tr:not(.stock-warehouse-row)").forEach(tr => {
    const cells = tr.querySelectorAll("td");
    if (cells[1]) cells[1].style.left = colWProduct + "px";
  });
}

function _initStockColResize(sourceId) {
  const table = document.getElementById(`stockDataTable_${sourceId}`);
  if (!table) return;
  table.querySelectorAll(".stock-resizable").forEach(th => {
    const handle = document.createElement("div");
    handle.className = "stock-resize-handle";
    th.appendChild(handle);
    let startX = 0, startW = 0;
    handle.addEventListener("mousedown", e => {
      e.preventDefault();
      startX = e.clientX;
      startW = th.offsetWidth;
      const col = th.dataset.col;
      const colIdx = th.dataset.colidx !== undefined ? Number(th.dataset.colidx) : -1;
      const onMove = ev => {
        const newW = Math.max(40, startW + ev.clientX - startX);
        // Update colgroup col width (most reliable with table-layout:fixed)
        const cols = table.querySelectorAll("colgroup col");
        if (col === "product") {
          if (cols[0]) cols[0].style.width = newW + "px";
          _setFixedColWidth(sourceId, "product", newW);
          _applyStockStickyOffsets(sourceId, newW, _getFixedColWidth(sourceId, "wbid"));
        } else if (col === "wbid") {
          if (cols[1]) cols[1].style.width = newW + "px";
          _setFixedColWidth(sourceId, "wbid", newW);
          _applyStockStickyOffsets(sourceId, _getFixedColWidth(sourceId, "product"), newW);
        } else if (colIdx >= 0) {
          // Individual date column
          if (cols[2 + colIdx]) cols[2 + colIdx].style.width = newW + "px";
          _setDateColWidth(sourceId, colIdx, newW);
        }
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

// ── Settings modal ────────────────────────────────────────────────────────────

let _stockSettingsSourceId = null;

function openStockSettings(sourceId) {
  _stockSettingsSourceId = sourceId;
  const hidden = _getHiddenWarehouses(sourceId);
  const threshold = _getStockThreshold(sourceId);

  // Use persisted full list of warehouses (includes hidden ones)
  let warehouses = _getAllKnownWarehouses(sourceId);

  // Also merge any currently visible warehouse rows from DOM (in case not yet saved)
  const wrap = document.getElementById("stockWorkTableWrap");
  if (wrap) {
    wrap.querySelectorAll("[data-wh]").forEach(r => {
      const wh = r.getAttribute("data-wh");
      if (wh && !warehouses.includes(wh)) warehouses.push(wh);
    });
  }

  const whList = warehouses.length ? warehouses.map(wh => {
    const isHidden = hidden.has(wh);
    return `
    <div class="stock-settings-wh-row">
      <button type="button" class="stock-eye-btn ${isHidden ? 'hidden-wh' : ''}"
        onclick="_toggleWhVisibility('${esc(wh)}')" title="${isHidden ? 'Показать склад' : 'Скрыть склад'}">
        ${isHidden ? '🚫' : '👁️'}
      </button>
      <span class="stock-wh-label${isHidden ? '" style="color:#94a3b8;text-decoration:line-through' : ''}">${esc(wh)}</span>
    </div>`;
  }).join("") : '<p class="small" style="color:#9ca3af">Загрузите данные сначала</p>';

  const modal = document.getElementById("stockSettingsModal");
  if (!modal) return;
  document.getElementById("stockSettingsWhList").innerHTML = whList;
  document.getElementById("stockSettingsThreshold").value = threshold || "";
  modal.classList.remove("hidden");
}

function closeStockSettingsModal() {
  document.getElementById("stockSettingsModal")?.classList.add("hidden");
}

function _toggleWhVisibility(wh) {
  if (!_stockSettingsSourceId) return;
  const hidden = _getHiddenWarehouses(_stockSettingsSourceId);
  if (hidden.has(wh)) hidden.delete(wh); else hidden.add(wh);
  _setHiddenWarehouses(_stockSettingsSourceId, hidden);
  // Update button in modal
  openStockSettings(_stockSettingsSourceId);
}

// ── Product catalog ───────────────────────────────────────────────────────────

let _productCatalogItems = [];

function openProductCatalogModal() {
  document.getElementById("productCatalogModal")?.classList.remove("hidden");
  // Reset add form
  document.getElementById("addProductForm")?.classList.add("hidden");
  document.getElementById("addProductError")?.classList.add("hidden");
  if (document.getElementById("addProductName")) document.getElementById("addProductName").value = "";
  if (document.getElementById("addProductWbArticle")) document.getElementById("addProductWbArticle").value = "";
  if (document.getElementById("addProductOzonArticle")) document.getElementById("addProductOzonArticle").value = "";
  loadProductCatalog();
}

function closeProductCatalogModal() {
  document.getElementById("productCatalogModal")?.classList.add("hidden");
}

function toggleAddProductForm() {
  const form = document.getElementById("addProductForm");
  if (!form) return;
  const isHidden = form.classList.contains("hidden");
  form.classList.toggle("hidden", !isHidden);
  if (isHidden) {
    document.getElementById("addProductName")?.focus();
    document.getElementById("addProductError")?.classList.add("hidden");
  }
}

async function saveNewProduct() {
  const name = String(document.getElementById("addProductName")?.value || "").trim();
  const wb = String(document.getElementById("addProductWbArticle")?.value || "").trim();
  const ozon = String(document.getElementById("addProductOzonArticle")?.value || "").trim();
  const errEl = document.getElementById("addProductError");

  if (!wb) {
    if (errEl) { errEl.textContent = "Артикул ВБ обязателен"; errEl.classList.remove("hidden"); }
    document.getElementById("addProductWbArticle")?.focus();
    return;
  }
  if (errEl) errEl.classList.add("hidden");

  try {
    const res = await fetch("/api/stock/products", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ product_name: name, wb_article: wb, ozon_article: ozon }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ошибка");
    // Clear form and hide
    document.getElementById("addProductName").value = "";
    document.getElementById("addProductWbArticle").value = "";
    document.getElementById("addProductOzonArticle").value = "";
    document.getElementById("addProductForm")?.classList.add("hidden");
    await loadProductCatalog();
    // Reload stock table if active
    if (stockSourcesState.activeSourceId) loadStockWorkData(stockSourcesState.activeSourceId);
  } catch (e) {
    if (errEl) { errEl.textContent = `Ошибка: ${esc(String(e))}`; errEl.classList.remove("hidden"); }
  }
}

async function loadProductCatalog() {
  const tbody = document.getElementById("productCatalogTableBody");
  if (tbody) tbody.innerHTML = '<tr><td colspan="4" style="padding:16px;color:#9ca3af;text-align:center">Загрузка...</td></tr>';
  try {
    const res = await fetch("/api/stock/products");
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    _productCatalogItems = data.items || [];
    renderProductCatalog();
    const status = document.getElementById("productCatalogStatus");
    if (status) status.textContent = `Товаров в каталоге: ${_productCatalogItems.length}`;
  } catch (e) {
    const tbody = document.getElementById("productCatalogTableBody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" style="padding:16px;color:#dc2626;text-align:center">Ошибка: ${esc(String(e))}</td></tr>`;
  }
}

function renderProductCatalog() {
  const tbody = document.getElementById("productCatalogTableBody");
  if (!tbody) return;
  if (!_productCatalogItems.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="padding:16px;color:#9ca3af;text-align:center">Каталог пуст. Загрузите файл Excel.</td></tr>';
    return;
  }
  tbody.innerHTML = _productCatalogItems.map(item => `
    <tr style="border-bottom:1px solid #f1f5f9">
      <td style="padding:7px 10px">${esc(item.product_name || "")}</td>
      <td style="padding:7px 10px;font-family:monospace;font-size:12px">${esc(item.wb_article || "")}</td>
      <td style="padding:7px 10px;font-family:monospace;font-size:12px">${esc(item.ozon_article || "")}</td>
      <td style="padding:4px 6px;text-align:center">
        <button type="button" class="secondary" style="padding:2px 8px;font-size:11px" onclick="deleteProductCatalogItem(${item.id})" title="Удалить">✕</button>
      </td>
    </tr>`).join("");
}

async function deleteProductCatalogItem(id) {
  const res = await fetch(`/api/stock/products/${id}`, { method: "DELETE", headers: withCsrfHeaders() });
  if (res.ok) {
    _productCatalogItems = _productCatalogItems.filter(i => i.id !== id);
    renderProductCatalog();
    const status = document.getElementById("productCatalogStatus");
    if (status) status.textContent = `Товаров в каталоге: ${_productCatalogItems.length}`;
  }
}

async function clearProductCatalog() {
  if (!confirm("Очистить весь каталог товаров?")) return;
  await fetch("/api/stock/products/clear", { method: "DELETE", headers: withCsrfHeaders() });
  await loadProductCatalog();
}

async function importProductCatalogExcel(input) {
  const file = input.files[0];
  if (!file) return;
  const status = document.getElementById("productCatalogStatus");
  if (status) status.textContent = "Импорт...";
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch("/api/stock/products/import", { method: "POST", headers: withCsrfHeaders(), body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ошибка");
    if (status) status.textContent = `✓ Импортировано ${data.imported} товаров`;
    await loadProductCatalog();
    // Reload stock table if source is active
    if (stockSourcesState.activeSourceId) loadStockWorkData(stockSourcesState.activeSourceId);
  } catch (e) {
    if (status) status.textContent = `Ошибка: ${esc(String(e))}`;
  }
  input.value = "";
}

function applyStockSettings() {
  if (!_stockSettingsSourceId) return;
  const thr = Number(document.getElementById("stockSettingsThreshold")?.value || 0);
  _setStockThreshold(_stockSettingsSourceId, thr);
  closeStockSettingsModal();
  loadStockWorkData(_stockSettingsSourceId);
}

// Initialize stock module when entering stock sections
const _origShowSection = typeof showSection === "function" ? showSection : null;

// ── Review reply actions ─────────────────────────────────────────────────────

async function retryReviewSend(reviewUid) {
  const btn = document.querySelector(`button.review-retry-btn[onclick*="${reviewUid}"]`);
  if (btn) { btn.disabled = true; btn.textContent = "⏳"; }
  try {
    const res = await fetch(`/api/reviews/${encodeURIComponent(reviewUid)}/retry-send`, {
      method: "POST",
      headers: jsonHeaders(),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(`Ошибка повторной отправки: ${data.detail || "Неизвестная ошибка"}`);
      if (btn) { btn.disabled = false; btn.textContent = "🔄"; }
      return;
    }
    await loadReviews();
  } catch (e) {
    alert(`Ошибка: ${e}`);
    if (btn) { btn.disabled = false; btn.textContent = "🔄"; }
  }
}

async function sendReviewReply(reviewUid) {
  const textarea = document.getElementById(`reply-${reviewUid}`);
  const text = String(textarea?.value || "").trim();
  if (!text) { alert("Введите текст ответа"); return; }
  try {
    const res = await fetch(`/api/reviews/${encodeURIComponent(reviewUid)}/reply`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ response_text: text }),
    });
    const data = await res.json();
    if (!res.ok) { alert("Ошибка: " + (data.detail || "не удалось отправить")); return; }
    await loadReviews();
  } catch (err) {
    alert("Ошибка при отправке ответа");
  }
}

async function refreshReviewTemplate(reviewUid, groupId, subgroup) {
  if (!groupId) return;
  try {
    const q = new URLSearchParams({ group_id: groupId, subgroup: subgroup || "", review_uid: reviewUid || "" });
    const res = await fetch(`/api/reviews/random-template?${q}`);
    if (!res.ok) return;
    const data = await res.json();
    const textarea = document.getElementById(`reply-${reviewUid}`);
    if (textarea && data.template_text) {
      textarea.value = data.template_text;
    }
  } catch (_) {}
}

function editReviewReply(reviewUid) {
  const textarea = document.getElementById(`reply-${reviewUid}`);
  if (!textarea) return;
  if (textarea.readOnly) {
    textarea.readOnly = false;
    textarea.focus();
    textarea.style.borderColor = "#2563eb";
  } else {
    textarea.readOnly = true;
    textarea.style.borderColor = "";
  }
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

// ── Question reply & templates ────────────────────────────────────────────────

let _questionSendUid = null;

function _findQuestionTextarea(uid) {
  // Cannot use getElementById or CSS.escape inside attribute selector quotes safely.
  // Iterate all question textareas and compare dataset.uid directly.
  let found = null;
  document.querySelectorAll("textarea.review-reply-textarea[data-uid]").forEach(el => {
    if (el.dataset.uid === uid) found = el;
  });
  return found;
}

function openQuestionSendConfirm(uid) {
  const ta = _findQuestionTextarea(uid);
  const text = String(ta?.value || "").trim();
  if (!text) {
    alert("Введите текст ответа");
    ta?.focus();
    return;
  }
  _questionSendUid = uid;
  const confirmTextEl = document.getElementById("questionSendConfirmText");
  if (confirmTextEl) confirmTextEl.textContent = text;
  document.getElementById("questionSendConfirmModal")?.classList.remove("hidden");
}

function closeQuestionSendConfirmModal() {
  document.getElementById("questionSendConfirmModal")?.classList.add("hidden");
  _questionSendUid = null;
}

async function _doSendQuestionReply() {
  if (!_questionSendUid) return;
  const uid = _questionSendUid;
  const ta = _findQuestionTextarea(uid);
  const text = String(ta?.value || "").trim();
  const btn = document.getElementById("questionSendConfirmBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Отправка..."; }
  try {
    await sendConversationReply(uid, text, `${uid}:${Date.now()}`);
    closeQuestionSendConfirmModal();
    await loadQuestions();
  } catch (error) {
    alert(error instanceof Error ? error.message : "Не удалось отправить ответ");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Отправить"; }
  }
}

// Question templates

let questionTemplatesState = { items: [], targetUid: null };

function openQuestionTemplatesModal(uid) {
  questionTemplatesState.targetUid = uid;
  document.getElementById("questionQuickTemplatesModal")?.classList.remove("hidden");
  document.getElementById("questionTemplateNameInput") && (document.getElementById("questionTemplateNameInput").value = "");
  document.getElementById("questionTemplateInput") && (document.getElementById("questionTemplateInput").value = "");
  document.getElementById("questionAddForm")?.classList.add("hidden");
  document.getElementById("questionSaveBtn")?.classList.add("hidden");
  loadQuestionTemplates();
}

function closeQuestionTemplatesModal() {
  document.getElementById("questionQuickTemplatesModal")?.classList.add("hidden");
  questionTemplatesState.targetUid = null;
  _editingQuestionTemplateId = null;
}

async function loadQuestionTemplates() {
  const listEl = document.getElementById("questionTemplatesList");
  const infoEl = document.getElementById("questionTemplatesInfo");
  if (listEl) listEl.innerHTML = '<p class="small" style="color:#9ca3af">Загрузка...</p>';
  try {
    const res = await fetch("/api/question-quick-templates");
    const data = await res.json();
    if (!res.ok) { if (infoEl) infoEl.textContent = data.detail || "Ошибка"; return; }
    questionTemplatesState.items = data.items || [];
    renderQuestionTemplatesList();
  } catch (_) {
    if (infoEl) infoEl.textContent = "Ошибка загрузки шаблонов";
  }
}

let _editingQuestionTemplateId = null;

function renderQuestionTemplatesList() {
  const listEl = document.getElementById("questionTemplatesList");
  if (!listEl) return;
  const items = questionTemplatesState.items;
  if (!items.length) {
    listEl.innerHTML = '<p class="small" style="color:#9ca3af">Шаблонов нет. Добавьте первый.</p>';
    return;
  }
  listEl.innerHTML = items.map(t => {
    const isEditing = _editingQuestionTemplateId === t.id;
    return `
    <div class="chat-quick-template-item" style="flex-direction:column;align-items:stretch;gap:6px">
      <div style="display:flex;align-items:center;gap:6px">
        <div style="flex:1;cursor:pointer;font-size:13px;font-weight:500;padding:4px 0"
          onclick="selectQuestionTemplate(${t.id})" title="${esc(t.template_text)}">${esc(t.template_name)}</div>
        <button type="button" class="qt-btn qt-edit" title="Редактировать"
          onclick="toggleEditQuestionTemplate(${t.id})">✏</button>
        <button type="button" class="qt-btn qt-delete" title="Удалить"
          onclick="deleteQuestionTemplate(${t.id})">✕</button>
      </div>
      ${isEditing ? `
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px">
        <input id="editQTplName_${t.id}" type="text" value="${esc(t.template_name)}"
          autocomplete="off" placeholder="Название" style="width:100%;box-sizing:border-box;margin-bottom:6px">
        <textarea id="editQTplText_${t.id}" rows="3" autocomplete="off"
          style="width:100%;box-sizing:border-box;resize:vertical"
          placeholder="Текст шаблона...">${esc(t.template_text)}</textarea>
        <div class="row" style="gap:6px;margin-top:6px">
          <button type="button" style="font-size:12px" onclick="saveEditQuestionTemplate(${t.id})">Сохранить</button>
          <button type="button" class="secondary" style="font-size:12px" onclick="toggleEditQuestionTemplate(${t.id})">Отмена</button>
        </div>
      </div>` : ""}
    </div>`;
  }).join("");
}

function toggleEditQuestionTemplate(id) {
  _editingQuestionTemplateId = _editingQuestionTemplateId === id ? null : id;
  renderQuestionTemplatesList();
  if (_editingQuestionTemplateId === id) {
    document.getElementById(`editQTplName_${id}`)?.focus();
  }
}

async function saveEditQuestionTemplate(id) {
  const name = String(document.getElementById(`editQTplName_${id}`)?.value || "").trim();
  const text = String(document.getElementById(`editQTplText_${id}`)?.value || "").trim();
  const infoEl = document.getElementById("questionTemplatesInfo");
  if (!name || !text) {
    if (infoEl) infoEl.textContent = "Заполните название и текст";
    return;
  }
  try {
    const res = await fetch(`/api/question-quick-templates/${id}`, {
      method: "PUT", headers: jsonHeaders(),
      body: JSON.stringify({ template_name: name, template_text: text }),
    });
    const data = await res.json();
    if (!res.ok) { if (infoEl) infoEl.textContent = data.detail || "Ошибка"; return; }
    _editingQuestionTemplateId = null;
    if (infoEl) infoEl.textContent = "";
    await loadQuestionTemplates();
  } catch (_) {
    if (infoEl) infoEl.textContent = "Ошибка сохранения";
  }
}

function selectQuestionTemplate(templateId) {
  const tpl = questionTemplatesState.items.find(t => t.id === templateId);
  if (!tpl || !questionTemplatesState.targetUid) return;
  const uid = questionTemplatesState.targetUid;
  const ta = _findQuestionTextarea(uid);
  if (ta) {
    ta.value = tpl.template_text;
    ta.removeAttribute("readonly");
    ta.focus();
  }
  closeQuestionTemplatesModal();
}

async function saveQuestionTemplate() {
  const name = String(document.getElementById("questionTemplateNameInput")?.value || "").trim();
  const text = String(document.getElementById("questionTemplateInput")?.value || "").trim();
  const infoEl = document.getElementById("questionTemplatesInfo");
  if (!name || !text) {
    if (infoEl) infoEl.textContent = "Заполните название и текст";
    return;
  }
  try {
    const res = await fetch("/api/question-quick-templates", {
      method: "POST", headers: jsonHeaders(),
      body: JSON.stringify({ template_name: name, template_text: text }),
    });
    const data = await res.json();
    if (!res.ok) { if (infoEl) infoEl.textContent = data.detail || "Ошибка"; return; }
    if (infoEl) infoEl.textContent = "";
    document.getElementById("questionTemplateNameInput").value = "";
    document.getElementById("questionTemplateInput").value = "";
    await loadQuestionTemplates();
  } catch (_) {
    if (infoEl) infoEl.textContent = "Ошибка сохранения";
  }
}

async function deleteQuestionTemplate(templateId) {
  if (!confirm("Удалить шаблон?")) return;
  try {
    await fetch(`/api/question-quick-templates/${templateId}`, {
      method: "DELETE", headers: withCsrfHeaders(),
    });
    await loadQuestionTemplates();
  } catch (_) {}
}

async function moveQuestionToProcessed(conversationUid) {
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(conversationUid)}/mark-answered`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      const data = await res.json();
      alert("Ошибка: " + (data.detail || "не удалось перенести в обработанные"));
      return;
    }
    await loadQuestions();
  } catch (err) {
    alert("Ошибка: не удалось перенести в обработанные");
  }
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
  const accountIdRaw = String(
    document.getElementById("questionPanelSourceFilter")?.value || questionsState.accountId || "all",
  );
  const status = String(
    document.getElementById("questionPanelStatusFilter")?.value || questionsState.status || "all",
  );
  questionsState.accountId = accountIdRaw;
  questionsState.status = status;
  const sort = String(document.getElementById("questionSortFilter")?.value || questionsState.sort || "newest");
  questionsState.sort = sort;

  const query = new URLSearchParams();
  query.set("kind", "question");
  if (accountIdRaw && accountIdRaw !== "all") query.set("account_id", accountIdRaw);
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
    const uid = esc(item.conversation_uid);
    const meta = item.metadata || {};
    const rawItem = meta.raw || {};
    const isOzon = String(item.source || "").toLowerCase().includes("ozon");
    const isProcessed = questionsState.bucket === "processed";

    // Source badge
    const sourceIcon = isOzon
      ? `<span class="chat-list-badge" style="margin-left:6px;vertical-align:middle">OZON</span>`
      : `<span class="chat-list-badge" style="margin-left:6px;vertical-align:middle">WB</span>`;

    // Date/time MSK
    const qDateRaw = rawItem.createdDate || item.last_message_at || item.updated_at || "";
    const qDateStr = qDateRaw ? _toMsk(qDateRaw) : "—";

    // Column 1: Question
    const questionText = item.message_text || rawItem.text || "";

    // Column 2: Reply
    let replyContent;
    if (isProcessed) {
      // Show actual reply — our system reply OR portal reply (raw.answer.text for WB)
      const ourReply = String(item.last_sent_text || "").trim();
      const portalReply = String((rawItem.answer || {}).text || "").trim();
      const actualReply = ourReply || portalReply;
      let replyText;
      if (actualReply) {
        replyText = actualReply;
      } else if (isOzon) {
        replyText = "Ответ предоставлен напрямую через портал ОЗОНа или другой сервис";
      } else {
        replyText = "";
      }
      replyContent = `<textarea class="review-reply-textarea review-reply-answered" readonly>${esc(replyText)}</textarea>`;
    } else {
      // Use data-uid attribute instead of id to avoid ':' in CSS selectors
      replyContent = `
        <textarea class="review-reply-textarea" data-uid="${uid}" placeholder="Введите ответ на вопрос..." readonly></textarea>
        <div class="review-reply-actions">
          <button type="button" class="review-icon-btn" title="Отправить ответ"
            data-action="q-send" data-uid="${uid}">📤</button>
          <button type="button" class="review-icon-btn" title="Шаблоны"
            data-action="q-templates" data-uid="${uid}">📋</button>
          <button type="button" class="review-icon-btn" title="Перенести в обработанные"
            data-action="q-move" data-uid="${uid}">✅</button>
        </div>`;
    }

    // Column 3: Product
    // WB: product info in productDetails; Ozon: sku + product_url in rawItem directly
    let productCell = "";
    if (isOzon) {
      const ozonSku = rawItem.sku || null;
      const ozonUrl = rawItem.product_url || (ozonSku ? `https://www.ozon.ru/product/${ozonSku}/` : "");
      if (ozonUrl || ozonSku) {
        // Try to find product name from catalog by SKU
        const catalogProduct = ozonSku
          ? (_productsCache || []).find(p => String(p.ozon_sku || "").trim() === String(ozonSku).trim())
          : null;
        const linkLabel = catalogProduct?.name ? esc(catalogProduct.name) : "Смотреть на Ozon";
        productCell = `<div class="review-product-name">${
          ozonUrl
            ? `<a href="${esc(ozonUrl)}" target="_blank" rel="noopener noreferrer" class="review-product-link">${linkLabel}</a>`
            : linkLabel
        }</div>${ozonSku ? `<div class="review-product-detail small">SKU: ${esc(String(ozonSku))}</div>` : ""}`;
      }
    } else {
      const pd = (rawItem.productDetails && typeof rawItem.productDetails === "object") ? rawItem.productDetails : {};
      const productName = esc(pd.productName || rawItem.productName || rawItem.subjectName || pd.subjectName || "");
      const article = esc(pd.supplierArticle || rawItem.supplierArticle || "");
      const nmId = pd.nmId || pd.nmID || rawItem.nmId || rawItem.nmID || null;
      const productUrl = nmId ? `https://www.wildberries.ru/catalog/${nmId}/detail.aspx` : "";
      if (productName) {
        productCell = `<div class="review-product-name">${productUrl
            ? `<a href="${productUrl}" target="_blank" rel="noopener noreferrer" class="review-product-link">${productName}</a>`
            : productName}</div>${article ? `<div class="review-product-detail small">Артикул: ${article}</div>` : ""}`;
      }
    }

    tr.innerHTML = `
      <td class="review-col-review">
        <div class="review-group-title">
          Вопрос от покупателя${sourceIcon}
        </div>
        ${questionText ? `<div class="review-text">${esc(questionText)}</div>` : ""}
        <div class="review-meta-small">${esc(item.customer_name || "")}${item.customer_name && qDateStr !== "—" ? " · " : ""}${qDateStr !== "—" ? qDateStr : ""}</div>
      </td>
      <td class="review-col-reply">${replyContent}</td>
      <td class="review-col-product">${productCell}${item.product_photo_url ? `<img src="${esc(item.product_photo_url)}" class="product-thumb" alt="" onerror="this.style.display='none'">` : ""}</td>
    `;

    // Make textarea editable on click for new questions
    // NOTE: uid may contain ':' which is invalid in CSS selectors
    if (!isProcessed) {
      const ta = tr.querySelector("textarea.review-reply-textarea");
      if (ta) {
        ta.addEventListener("focus", () => { ta.removeAttribute("readonly"); });
        ta.addEventListener("blur", () => { if (!ta.value.trim()) ta.setAttribute("readonly", ""); });
      }
    }

    tbody?.appendChild(tr);
  }

  // Event delegation for question action buttons (avoids ':' in onclick attributes)
  if (tbody) {
    tbody.onclick = (e) => {
      const btn = e.target.closest("[data-action]");
      if (!btn) return;
      const btnUid = btn.dataset.uid;
      const action = btn.dataset.action;
      if (action === "q-send") openQuestionSendConfirm(btnUid);
      else if (action === "q-templates") openQuestionTemplatesModal(btnUid);
      else if (action === "q-move") moveQuestionToProcessed(btnUid);
    };
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
  questionsState.status = String(data.status || questionsState.status || "all");
  window._questionAccountOptions = data.account_options || [];
  setQuestionAccountFilterOptions(data.account_options || []);

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
    const preview = String(item.message_text || "").replace(/\s+/g, " ").trim();
    const unread = Number(item.unread_count || 0);
    const name = esc(item.customer_name || item.external_conversation_id || "Диалог");
    const source = esc((item.source || "").toUpperCase());
    // Format date: dd.mm.yy from last_message_at
    let dateStr = "";
    const lmt = String(item.last_message_at || item.updated_at || "");
    if (lmt) {
      try {
        const d = new Date(lmt);
        if (!isNaN(d.getTime())) {
          const dd = String(d.getDate()).padStart(2, "0");
          const mm = String(d.getMonth() + 1).padStart(2, "0");
          const yy = String(d.getFullYear()).slice(-2);
          dateStr = `${dd}.${mm}.${yy}`;
        }
      } catch (_) {}
    }
    button.innerHTML = `
      <div class="chat-list-head">
        <span class="chat-list-name">${name}</span>
        <div class="chat-list-meta">
          ${dateStr ? `<span class="chat-list-date">${esc(dateStr)}</span>` : ""}
          <span class="chat-list-badge">${source}</span>
          ${unread > 0 && (item.source || "").toLowerCase() !== "ozon" ? `<span class="chat-list-unread">${unread}</span>` : ""}
        </div>
      </div>
    `;
    button.addEventListener("click", () => {
      selectChatConversation(item.conversation_uid);
    });
    container.appendChild(button);
  }
}

function isMobileChatView() {
  return window.matchMedia(`(max-width: ${MOBILE_NAV_BREAKPOINT_PX}px)`).matches;
}

function showChatListPanel() {
  const listPanel = document.querySelector(".chats-list-panel");
  const threadPanel = document.querySelector(".chats-thread-panel");
  if (listPanel) listPanel.classList.remove("mobile-hidden");
  if (threadPanel) threadPanel.classList.remove("mobile-visible");
}

function showChatThreadPanel() {
  const listPanel = document.querySelector(".chats-list-panel");
  const threadPanel = document.querySelector(".chats-thread-panel");
  if (listPanel) listPanel.classList.add("mobile-hidden");
  if (threadPanel) threadPanel.classList.add("mobile-visible");
  const backBtn = document.getElementById("chatBackBtn");
  if (backBtn) backBtn.classList.remove("hidden");
}

function goBackToChats() {
  chatsState.activeConversationUid = "";
  stopChatAutoRefresh();
  showChatListPanel();
}

function renderMobileChatBackBtn() {
  const backBtn = document.getElementById("chatBackBtn");
  if (!backBtn) return;
  if (isMobileChatView()) {
    backBtn.classList.remove("hidden");
  } else {
    backBtn.classList.add("hidden");
  }
}

function renderChatsList() {
  const all = Array.isArray(chatsState.items) ? chatsState.items : [];
  const emptyText = String(chatsState.search || "").trim()
    ? `По запросу «${chatsState.search}» ничего не найдено`
    : chatsState.bucket === "processed"
      ? "Нет обработанных чатов"
      : "Нет чатов, требующих ответа";
  renderChatListGroup("chatsList", all, emptyText);
  // On mobile, if no active chat - show list panel
  if (isMobileChatView() && !chatsState.activeConversationUid) {
    showChatListPanel();
  }
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
  // Emoji picker is now CSS hover-driven; JS toggle kept for compatibility
  const wrap = document.querySelector(".chat-emoji-wrap");
  if (!wrap) return;
  if (forceVisible === false) {
    wrap.classList.remove("emoji-open");
  } else if (forceVisible === true) {
    wrap.classList.add("emoji-open");
  } else {
    wrap.classList.toggle("emoji-open");
  }
}

function hideChatEmojiPickerIfOutside(target) {
  // No-op: emoji picker closes via CSS :hover + mouseout
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
    const name = String(item.template_name || "").trim() || text.slice(0, 40);
    if (!templateId || !text) continue;

    const row = document.createElement("div");
    row.className = "chat-quick-template-item";
    row.dataset.templateId = String(templateId);

    // Normal view: name (clickable) + edit + delete buttons
    row.innerHTML = `
      <div class="chat-quick-template-name" style="cursor:pointer" title="Нажмите чтобы вставить">${esc(name)}</div>
      <div class="chat-quick-template-actions">
        <button type="button" class="qt-btn qt-edit" title="Редактировать">✏</button>
        <button type="button" class="qt-btn qt-delete" title="Удалить">✕</button>
      </div>
    `;

    row.querySelector(".chat-quick-template-name")?.addEventListener("click", () => {
      appendTextToChatInput(text);
      setChatQuickTemplatesInfo("Шаблон подставлен в поле ответа.");
      closeChatQuickTemplatesModal();
    });

    row.querySelector(".qt-edit")?.addEventListener("click", () => {
      // Replace row content with inline edit form
      row.innerHTML = `
        <div class="qt-edit-form">
          <input type="text" class="qt-edit-name" maxlength="200" value="${esc(name)}" placeholder="Название" autocomplete="off">
          <textarea class="qt-edit-text" rows="3" maxlength="2000" autocomplete="off">${esc(text)}</textarea>
          <div class="row" style="gap:8px;margin-top:6px">
            <button type="button" class="qt-save-btn">Сохранить</button>
            <button type="button" class="secondary qt-cancel-btn">Отмена</button>
          </div>
        </div>
      `;
      row.querySelector(".qt-save-btn")?.addEventListener("click", async () => {
        const newName = String(row.querySelector(".qt-edit-name")?.value || "").trim();
        const newText = String(row.querySelector(".qt-edit-text")?.value || "").trim();
        if (!newName) { setChatQuickTemplatesInfo("Введите название шаблона", true); return; }
        if (!newText) { setChatQuickTemplatesInfo("Введите текст шаблона", true); return; }
        await updateChatQuickTemplate(templateId, newName, newText);
      });
      row.querySelector(".qt-cancel-btn")?.addEventListener("click", () => {
        renderChatQuickTemplatesList();
      });
    });

    row.querySelector(".qt-delete")?.addEventListener("click", async () => {
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
  document.getElementById("chatAddForm")?.classList.add("hidden");
  document.getElementById("chatSaveBtn")?.classList.add("hidden");
  loadChatQuickTemplates();
}

function closeChatQuickTemplatesModal() {
  setModalVisibility("chatQuickTemplatesModal", false);
  const nameInput = document.getElementById("chatQuickTemplateNameInput");
  const textInput = document.getElementById("chatQuickTemplateInput");
  if (nameInput) nameInput.value = "";
  if (textInput instanceof HTMLTextAreaElement) textInput.value = "";
  setChatQuickTemplatesInfo("");
}

async function createChatQuickTemplate() {
  const nameInput = document.getElementById("chatQuickTemplateNameInput");
  const textInput = document.getElementById("chatQuickTemplateInput");
  const name = String(nameInput?.value || "").trim();
  const text = String(textInput?.value || "").trim();
  if (!name) {
    setChatQuickTemplatesInfo("Введите название шаблона", true);
    return;
  }
  if (!text) {
    setChatQuickTemplatesInfo("Введите текст шаблона", true);
    return;
  }
  const res = await fetch("/api/chat-quick-templates", {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ template_name: name, template_text: text }),
  });
  const data = await res.json();
  if (!res.ok) {
    setChatQuickTemplatesInfo(data.detail || "Не удалось добавить шаблон", true);
    return;
  }
  if (nameInput) nameInput.value = "";
  if (textInput) textInput.value = "";
  setChatQuickTemplatesInfo("");
  await loadChatQuickTemplates();
}

async function updateChatQuickTemplate(templateId, newName, newText) {
  const cleanId = Number(templateId || 0);
  if (!cleanId) return;
  const res = await fetch(`/api/chat-quick-templates/${cleanId}`, {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify({ template_name: newName, template_text: newText }),
  });
  const data = await res.json();
  if (!res.ok) {
    setChatQuickTemplatesInfo(data.detail || "Не удалось обновить шаблон", true);
    return;
  }
  setChatQuickTemplatesInfo("");
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
  setChatQuickTemplatesInfo("");
  await loadChatQuickTemplates();
}

function formatChatMessageTime(createdAt) {
  if (!createdAt) return "";
  try {
    const d = new Date(createdAt);
    if (isNaN(d.getTime())) return "";
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    if (sameDay) return time;
    const date = d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
    return `${date}, ${time}`;
  } catch (_) {
    return "";
  }
}

function renderChatMessages(messages, convMeta) {
  const thread = document.getElementById("chatMessages");
  if (!thread) return;
  thread.innerHTML = "";
  if (!Array.isArray(messages) || !messages.length) {
    renderChatsThreadPlaceholder("Сообщений пока нет");
    return;
  }
  // For Ozon chats, images require auth → proxy through our backend
  const isOzon = String((convMeta || {}).source || "").toLowerCase() === "ozon";
  const ozonAccountId = Number((convMeta || {}).account_id || 0);
  for (const message of messages) {
    const rawDirection = message.direction;
    const direction = rawDirection ? String(rawDirection).toLowerCase() : null;
    const outbound = direction === "outbound";
    const bubble = document.createElement("div");
    if (direction === null) {
      bubble.className = "chat-bubble inbound";
    } else {
      bubble.className = `chat-bubble ${outbound ? "outbound" : "inbound"}`;
    }
    const status = String(message.send_status || "").toLowerCase();
    const errorHint = status === "failed" ? String(message.send_error_message || "Ошибка отправки") : "";
    if (status === "failed") bubble.classList.add("failed");
    const timeStr = formatChatMessageTime(message.created_at);
    let senderLabel = "";
    if (direction !== null) {
      senderLabel = outbound
        ? (message.operator_name || "Продавец")
        : (message.operator_name || "Покупатель");
    }
    const metaParts = [];
    if (senderLabel) metaParts.push(esc(senderLabel));
    if (timeStr) metaParts.push(`<span class="chat-msg-time">${esc(timeStr)}</span>`);
    if (errorHint) metaParts.push(`<span style="color:#b91c1c">${esc(errorHint)}</span>`);

    // Render message content: parse [img:url] tokens as images
    // Matches: [img:https://...], [img:wb-download:uuid], [img:http://...]
    const rawText = String(message.message_text || "");
    const imgRegex = /\[img:([^\]]+)\]/g;
    let contentHtml = "";
    const imgMatches = [...rawText.matchAll(imgRegex)];
    if (imgMatches.length > 0) {
      // Show images; Ozon and WB images need to be proxied through our backend
      const convAccountId = Number((convMeta || {}).account_id || 0);
      const convSource = String((convMeta || {}).source || "").toLowerCase();
      contentHtml = imgMatches.map((m) => {
        let imgSrc = m[1];
        if (convSource === "ozon" && convAccountId && imgSrc.includes("api-seller.ozon.ru")) {
          imgSrc = `/api/ozon-image?url=${encodeURIComponent(imgSrc)}&account_id=${convAccountId}`;
        } else if (imgSrc.startsWith("wb-download:") && convAccountId) {
          const dlId = imgSrc.slice("wb-download:".length);
          imgSrc = `/api/wb-image?id=${encodeURIComponent(dlId)}&account_id=${convAccountId}`;
        } else if (imgSrc.includes("sellers-chat-inner") && convAccountId) {
          // Legacy internal WB K8s URL — extract UUID and proxy
          const uuidMatch = imgSrc.match(/\/file\/([0-9a-f-]{36})/i);
          if (uuidMatch) {
            imgSrc = `/api/wb-image?id=${encodeURIComponent(uuidMatch[1])}&account_id=${convAccountId}`;
          }
        }
        return `<img src="${esc(imgSrc)}" class="chat-bubble-img" alt="Фото" loading="lazy" onclick="openChatImgLightbox(this.src)" />`;
      }).join("");
      // If there's also text outside [img:] tokens, show it too
      const textOnly = rawText.replace(imgRegex, "").trim();
      if (textOnly) contentHtml += `<div class="chat-bubble-text">${esc(textOnly)}</div>`;
    } else {
      contentHtml = `<div class="chat-bubble-text">${esc(rawText)}</div>`;
    }

    bubble.innerHTML = `
      ${contentHtml}
      ${metaParts.length ? `<div class="chat-bubble-meta">${metaParts.join(" · ")}</div>` : ""}
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
  const titleSpan = document.getElementById("chatThreadTitle");
  const badgeWrap = document.getElementById("chatOrderBadgeWrap");
  const activeConversation = findActiveChatConversation();
  if (titleSpan) {
    titleSpan.textContent = activeConversation
      ? `${activeConversation.customer_name || "Чат"} · ${String(activeConversation.source || "").toUpperCase()}`
      : "Чат";
  }
  if (badgeWrap) {
    if (activeConversation) {
      const _meta = activeConversation.metadata || {};
      const _raw = (_meta.raw || _meta) || {};
      const _gc = _raw.goodCard || {};
      const _productName = String(_gc.name || "").trim();
      const _nmId = String(_gc.nmID || _gc.nmId || "").trim();
      if (_productName || _nmId) {
        const tipLines = [_productName, _nmId ? "Артикул WB: " + _nmId : ""].filter(Boolean).join("\n");
        const _productLine = _nmId
          ? `<a href="https://www.wildberries.ru/catalog/${esc(_nmId)}/detail.aspx" target="_blank" rel="noopener noreferrer" style="color:#93c5fd;text-decoration:underline">${esc(_productName || "Товар WB")}</a>`
          : esc(_productName);
        const _articleLine = _nmId ? `<div style="margin-top:4px;color:#94a3b8;font-size:11px">Артикул WB: ${esc(_nmId)}</div>` : "";
        badgeWrap.innerHTML = `<span class="chat-order-badge" style="margin-left:8px;position:relative">Данные заказа<div class="chat-order-tooltip"><div class="chat-order-tooltip-content">${_productLine}${_articleLine}</div></div></span>`;
      } else {
        badgeWrap.innerHTML = "";
      }
    } else {
      badgeWrap.innerHTML = "";
    }
  }
  // Only show loading placeholder on first open, not on 30s background refreshes
  if (!chatsState.loadedConversations) chatsState.loadedConversations = new Set();
  const isFirstOpen = !chatsState.loadedConversations.has(uid);
  chatsState.loadedConversations.add(uid);
  if (isFirstOpen) {
    renderChatsThreadPlaceholder("Загрузка переписки...");
  }
  // refresh=1 on first open to fetch full history from WB API
  const refreshParam = isFirstOpen ? "&refresh=1" : "";
  const res = await fetch(`/api/conversations/${encodeURIComponent(uid)}/messages?limit=200${refreshParam}`);
  const data = await res.json();
  if (!res.ok) {
    renderChatsThreadPlaceholder(String(data.detail || "Не удалось загрузить переписку"));
    return;
  }
  const dbMessages = Array.isArray(data.messages) ? data.messages : [];
  const merged = [];
  if (!dbMessages.length) {
    // No history in DB yet — show the last message text as a fallback.
    // Use last_message_at from conversation for the timestamp.
    // last_sender from metadata tells us who wrote it.
    const conv = data.conversation || activeConversation || {};
    const sourceText = String(conv.message_text || "").trim();
    if (sourceText) {
      const meta = conv.metadata || {};
      const lastSender = String(meta.last_sender || "").toLowerCase();
      // If we know the last sender, show it; otherwise show as inbound (buyer)
      const direction = lastSender === "seller" ? "outbound" : "inbound";
      const senderName = lastSender === "seller" ? "Продавец" : (conv.customer_name || "Покупатель");
      merged.push({
        direction: direction,
        message_text: sourceText,
        operator_name: senderName,
        send_status: "sent",
        created_at: conv.last_message_at || conv.updated_at || null,
      });
    }
  }
  for (const row of dbMessages) {
    merged.push(row);
  }
  const convMeta = data.conversation || activeConversation || {};
  renderChatMessages(merged, convMeta);
}

function closeSyncReportModal() {
  setModalVisibility("syncReportModal", false);
}

function openSyncReportModal(report) {
  if (!report) return;
  const title = document.getElementById("syncReportTitle");
  const body = document.getElementById("syncReportBody");
  const logEl = document.getElementById("syncReportLog");
  if (!title || !body) return;

  const cancelled = report.cancelled;
  title.textContent = cancelled ? "⚠️ Синхронизация остановлена" : "✅ Синхронизация завершена";

  const CHANNEL_LABELS = { reviews: "⭐ Отзывы", questions: "❓ Вопросы", chats: "💬 Чаты" };

  let html = "";
  const accounts = Array.isArray(report.accounts) ? report.accounts : [];
  for (const acct of accounts) {
    const channels = acct.channels || {};
    let chHtml = "";
    for (const [ch, data] of Object.entries(channels)) {
      const label = CHANNEL_LABELS[ch] || ch;
      const loaded = Number(data.loaded || 0);
      const skipped = Number(data.skipped || 0);
      if (!data.ok && data.error) {
        chHtml += `<div class="sync-report-channel">
          <span class="sync-report-channel-name">${label}</span>
          <span class="sync-report-channel-err">❌ Ошибка: ${esc(String(data.error).slice(0, 80))}</span>
        </div>`;
      } else if (data.ok || loaded > 0) {
        const skipNote = skipped > 0 ? `, пропущено старых: ${skipped.toLocaleString("ru-RU")}` : "";
        chHtml += `<div class="sync-report-channel">
          <span class="sync-report-channel-name">${label}</span>
          <span class="sync-report-channel-ok">✅ загружено: ${loaded.toLocaleString("ru-RU")}${skipNote}</span>
        </div>`;
      } else {
        chHtml += `<div class="sync-report-channel">
          <span class="sync-report-channel-name">${label}</span>
          <span class="sync-report-channel-skip">— нет доступа или не настроен</span>
        </div>`;
      }
    }
    html += `<div class="sync-report-account">
      <div class="sync-report-account-name">${esc(acct.account_name || `#${acct.account_id}`)}</div>
      <div class="sync-report-channels">${chHtml}</div>
    </div>`;
  }
  if (!html) {
    html = `<p class="small" style="color:#6b7280">Нет данных о синхронизации.</p>`;
  }
  body.innerHTML = html;

  // Log
  const logLines = Array.isArray(report.log) ? report.log : [];
  if (logEl) logEl.textContent = logLines.length ? logLines.join("\n") : "(лог пуст)";

  setModalVisibility("syncReportModal", true);
}

function openResetTemplatesModal() {
  document.getElementById("resetTemplatesInfo").textContent = "";
  setModalVisibility("resetTemplatesModal", true);
}

function closeResetTemplatesModal() {
  setModalVisibility("resetTemplatesModal", false);
}

async function confirmResetTemplates() {
  const info = document.getElementById("resetTemplatesInfo");
  if (info) info.textContent = "Обновляем...";
  try {
    const res = await fetch("/api/templates/reset-to-defaults", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) {
      if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось сбросить");
      return;
    }
    closeResetTemplatesModal();
    // Reload templates
    if (typeof loadTemplates === "function") await loadTemplates();
    if (typeof loadProcessingRules === "function") await loadProcessingRules();
  } catch (err) {
    if (info) info.textContent = "Ошибка при сбросе шаблонов";
  }
}

function openChatImgLightbox(src) {
  const lb = document.getElementById("chatImgLightbox");
  const img = document.getElementById("chatImgLightboxImg");
  if (!lb || !img) return;
  img.src = src;
  lb.classList.add("active");
  // Close on Escape key
  document.addEventListener("keydown", _lbKeyClose);
}

function closeChatImgLightbox() {
  const lb = document.getElementById("chatImgLightbox");
  if (lb) lb.classList.remove("active");
  document.removeEventListener("keydown", _lbKeyClose);
}

function _lbKeyClose(e) {
  if (e.key === "Escape") closeChatImgLightbox();
}

function startChatAutoRefresh(uid) {
  stopChatAutoRefresh();
  if (!uid || String(uid).includes(":question:")) return;
  chatAutoRefreshTimer = window.setInterval(async () => {
    if (!chatsState.activeConversationUid) return;
    // Reload messages from DB (auto-sync keeps DB up to date).
    await loadChatMessages(chatsState.activeConversationUid);
    // Also refresh chat list so bucket changes (New/Answered) are reflected.
    if (!syncInProgress) loadChats();
  }, CHAT_AUTO_REFRESH_MS);
}

function stopChatAutoRefresh() {
  if (chatAutoRefreshTimer !== null) {
    window.clearInterval(chatAutoRefreshTimer);
    chatAutoRefreshTimer = null;
  }
}

function selectChatConversation(conversationUid) {
  chatsState.activeConversationUid = String(conversationUid || "");
  renderChatsList();
  _updateChatBucketButtons();
  // On mobile: switch to thread panel when a chat is selected
  if (isMobileChatView() && chatsState.activeConversationUid) {
    showChatThreadPanel();
    renderMobileChatBackBtn();
  }
  loadChatMessages(chatsState.activeConversationUid);
  startChatAutoRefresh(chatsState.activeConversationUid);
}

async function loadChats() {
  // Don't update the chat list while a sync is in progress — wait for sync to finish
  // so the list is only shown once with correct Answered/New bucket assignment.
  if (syncInProgress) return;

  // Guard: if browser autofilled the search input with an email/unrelated value,
  // clear it so chats are not inadvertently filtered.
  const _searchEl = document.getElementById("chatsSearchInput");
  if (_searchEl) {
    const _autofilled = _searchEl.value && _searchEl.value !== chatsState.search;
    if (_autofilled && !chatsState.search) {
      _searchEl.value = "";
    }
  }

  const accountIdRaw = String(document.getElementById("chatPanelSourceFilter")?.value || chatsState.accountId || "all");
  const status = String(document.getElementById("chatPanelStatusFilter")?.value || chatsState.status || "all");
  chatsState.accountId = accountIdRaw;
  chatsState.status = status;
  const sort = String(chatsState.sort || "newest");
  chatsState.sort = sort;

  const PAGE_SIZE = 1000;
  const hasSearch = String(chatsState.search || "").trim().length > 0;
  const buildQuery = (page) => {
    const q = new URLSearchParams();
    q.set("kind", "chat");
    if (accountIdRaw && accountIdRaw !== "all") q.set("account_id", accountIdRaw);
    if (status && status !== "all") q.set("status", status);
    if (chatsState.date_from) q.set("date_from", chatsState.date_from);
    if (chatsState.date_to) q.set("date_to", chatsState.date_to);
    q.set("bucket", chatsState.bucket || "all");
    q.set("sort", sort);
    q.set("page", String(page));
    q.set("page_size", String(PAGE_SIZE));
    if (hasSearch) q.set("search", chatsState.search);
    return q;
  };

  // Load first page
  const res = await fetch("/api/conversations?" + buildQuery(1).toString());
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

  // If there are more pages, load them all
  let allItems = Array.isArray(data.items) ? data.items : [];
  const totalPages = Number(data.pages || 1);
  if (totalPages > 1) {
    const pagePromises = [];
    for (let p = 2; p <= totalPages; p++) {
      pagePromises.push(
        fetch("/api/conversations?" + buildQuery(p).toString())
          .then((r) => r.json())
          .then((d) => (Array.isArray(d.items) ? d.items : []))
          .catch(() => [])
      );
    }
    const extraPages = await Promise.all(pagePromises);
    for (const pg of extraPages) allItems = allItems.concat(pg);
  }

  chatsState.items = allItems;
  const newCount = Number(data.new_count || 0);
  const processedCount = Number(data.processed_count || 0);
  const chatsTabNew = document.getElementById("chats-tab-new");
  if (chatsTabNew) chatsTabNew.textContent = `Новые чаты (${newCount})`;
  const chatsTabProcessed = document.getElementById("chats-tab-processed");
  if (chatsTabProcessed) chatsTabProcessed.textContent = `Обработанные чаты (${processedCount})`;

  chatsState.date_from = data.date_from || chatsState.date_from || null;
  chatsState.date_to = data.date_to || chatsState.date_to || null;
  chatsState.status = String(data.status || chatsState.status || "all");
  setChatAccountFilterOptions(data.account_options || []);

  // Update sort select
  const chatsSortSelect = document.getElementById("chatsSortSelect");
  if (chatsSortSelect) chatsSortSelect.value = chatsState.sort || "newest";
  const sortOptions = document.querySelectorAll(".chats-sort-option");
  sortOptions.forEach((opt) => opt.classList.toggle("active", opt.getAttribute("data-value") === (chatsState.sort || "newest")));
  const panelSourceFilter = document.getElementById("chatPanelSourceFilter");
  if (panelSourceFilter && !Array.from(panelSourceFilter.options).some((o) => o.value === chatsState.accountId)) {
    panelSourceFilter.value = "all";
  }
  const panelStatusFilter = document.getElementById("chatPanelStatusFilter");
  if (panelStatusFilter) panelStatusFilter.value = chatsState.status || "all";
  updateChatsDateFilterButton();

  // Guard: never set a question UID as active chat conversation
  const isValidChatUid = (uid) => uid && !String(uid).includes(":question:");
  if (!isValidChatUid(chatsState.activeConversationUid)) {
    chatsState.activeConversationUid = "";
  }
  const hasActive = chatsState.items.some((item) => item.conversation_uid === chatsState.activeConversationUid);
  if (!hasActive) {
    // On mobile: don't auto-select first chat — show the list instead
    if (isMobileChatView()) {
      chatsState.activeConversationUid = "";
    } else {
      const firstChat = chatsState.items.find(item => isValidChatUid(item.conversation_uid));
      chatsState.activeConversationUid = firstChat ? String(firstChat.conversation_uid) : "";
    }
  }
  renderChatsList();
  if (chatsState.activeConversationUid) {
    if (isMobileChatView()) {
      showChatThreadPanel();
      renderMobileChatBackBtn();
    }
    await loadChatMessages(chatsState.activeConversationUid);
  } else {
    if (isMobileChatView()) {
      showChatListPanel();
    }
    renderChatsThreadPlaceholder("Выберите чат слева");
    const titleSpan2 = document.getElementById("chatThreadTitle");
    if (titleSpan2) titleSpan2.textContent = "Чат не выбран";
    const backBtn2 = document.getElementById("chatBackBtn");
    if (backBtn2) backBtn2.classList.add("hidden");
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

// ── Shared template modal helpers ────────────────────────────────────────────

function qtemplToggleAdd(scope) {
  const formId = scope === "chat" ? "chatAddForm" : scope === "review" ? "reviewAddForm" : "questionAddForm";
  const saveId = scope === "chat" ? "chatSaveBtn" : scope === "review" ? "reviewSaveBtn" : "questionSaveBtn";
  const form = document.getElementById(formId);
  const saveBtn = document.getElementById(saveId);
  if (!form) return;
  const isHidden = form.classList.contains("hidden");
  form.classList.toggle("hidden", !isHidden);
  if (saveBtn) saveBtn.classList.toggle("hidden", !isHidden);
  if (isHidden) {
    // Focus the name input when opening
    form.querySelector("input")?.focus();
  }
}

// ── Review quick templates modal ──────────────────────────────────────────────

let _reviewTemplatesActiveUid = null;

function openReviewTemplatesModal(reviewUid) {
  _reviewTemplatesActiveUid = reviewUid || null;
  document.getElementById("reviewQuickTemplatesModal")?.classList.remove("hidden");
  document.getElementById("reviewTemplatesInfo").textContent = "";
  document.getElementById("reviewQuickTemplateNameInput").value = "";
  document.getElementById("reviewQuickTemplateInput").value = "";
  // Reset add form to hidden
  document.getElementById("reviewAddForm")?.classList.add("hidden");
  document.getElementById("reviewSaveBtn")?.classList.add("hidden");
  loadReviewTemplates();
}

function closeReviewTemplatesModal() {
  document.getElementById("reviewQuickTemplatesModal")?.classList.add("hidden");
  _reviewTemplatesActiveUid = null;
}

async function loadReviewTemplates() {
  const list = document.getElementById("reviewTemplatesList");
  const info = document.getElementById("reviewTemplatesInfo");
  if (!list) return;
  try {
    const res = await fetch("/api/review-quick-templates");
    const data = await res.json();
    const items = data.items || [];
    list.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "small";
      empty.style.color = "#94a3b8";
      empty.textContent = "Нет шаблонов. Добавьте первый ниже.";
      list.appendChild(empty);
      return;
    }
    for (const tpl of items) {
      const item = document.createElement("div");
      item.className = "chat-quick-template-item";
      item.style.flexDirection = "column";
      item.style.alignItems = "stretch";
      item.style.gap = "6px";
      item.dataset.tplId = tpl.id;
      item.innerHTML = `
        <div style="display:flex;align-items:center;gap:6px">
          <span class="chat-quick-template-name" style="cursor:pointer;flex:1" title="${esc(tpl.template_text)}" onclick="selectReviewTemplate(${tpl.id})">${esc(tpl.template_name || tpl.template_text)}</span>
          <button type="button" class="qt-btn qt-edit" title="Редактировать" onclick="toggleEditReviewTemplate(${tpl.id})">✏</button>
          <button type="button" class="qt-btn qt-delete" title="Удалить" onclick="deleteReviewTemplate(${tpl.id})">✕</button>
        </div>
        <div id="editRTpl_${tpl.id}" class="hidden" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px;flex-direction:column;gap:6px">
          <input id="editRTplName_${tpl.id}" type="text" value="${esc(tpl.template_name)}" placeholder="Название" style="width:100%;box-sizing:border-box">
          <textarea id="editRTplText_${tpl.id}" rows="3" style="width:100%;box-sizing:border-box;resize:vertical">${esc(tpl.template_text)}</textarea>
          <div style="display:flex;gap:6px">
            <button type="button" style="font-size:12px" onclick="saveEditReviewTemplate(${tpl.id})">Сохранить</button>
            <button type="button" class="secondary" style="font-size:12px" onclick="toggleEditReviewTemplate(${tpl.id})">Отмена</button>
          </div>
        </div>`;
      list.appendChild(item);
    }
  } catch (e) {
    if (info) info.textContent = "Ошибка загрузки шаблонов";
  }
}

function toggleEditReviewTemplate(id) {
  const el = document.getElementById(`editRTpl_${id}`);
  if (!el) return;
  const hidden = el.classList.toggle("hidden");
  el.style.display = hidden ? "none" : "flex";
  if (!hidden) document.getElementById(`editRTplName_${id}`)?.focus();
}

async function saveEditReviewTemplate(id) {
  const name = String(document.getElementById(`editRTplName_${id}`)?.value || "").trim();
  const text = String(document.getElementById(`editRTplText_${id}`)?.value || "").trim();
  const info = document.getElementById("reviewTemplatesInfo");
  if (!name || !text) { if (info) info.textContent = "Заполните название и текст"; return; }
  try {
    const res = await fetch(`/api/review-quick-templates/${id}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify({ template_name: name, template_text: text }),
    });
    const data = await res.json();
    if (!res.ok) { if (info) info.textContent = data.detail || "Ошибка"; return; }
    if (info) info.textContent = "";
    await loadReviewTemplates();
  } catch (e) { if (info) info.textContent = "Ошибка сохранения"; }
}

async function selectReviewTemplate(templateId) {
  if (!_reviewTemplatesActiveUid) return;
  const res = await fetch("/api/review-quick-templates");
  const data = await res.json();
  const tpl = (data.items || []).find(t => t.id === templateId);
  if (!tpl) return;
  const textarea = document.getElementById(`reply-${_reviewTemplatesActiveUid}`);
  if (textarea) {
    textarea.value = tpl.template_text;
    textarea.removeAttribute("readonly");
    textarea.dispatchEvent(new Event("input"));
  }
  closeReviewTemplatesModal();
}

async function saveReviewQuickTemplate() {
  const name = String(document.getElementById("reviewQuickTemplateNameInput")?.value || "").trim();
  const text = String(document.getElementById("reviewQuickTemplateInput")?.value || "").trim();
  const info = document.getElementById("reviewTemplatesInfo");
  if (!name) { if (info) info.textContent = "Введите название"; return; }
  if (!text) { if (info) info.textContent = "Введите текст"; return; }
  if (info) info.textContent = "";
  try {
    const res = await fetch("/api/review-quick-templates", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ template_name: name, template_text: text }),
    });
    const data = await res.json();
    if (!res.ok) { if (info) info.textContent = data.detail || "Ошибка"; return; }
    document.getElementById("reviewQuickTemplateNameInput").value = "";
    document.getElementById("reviewQuickTemplateInput").value = "";
    await loadReviewTemplates();
  } catch (e) { if (info) info.textContent = "Ошибка сохранения"; }
}

async function deleteReviewTemplate(templateId) {
  if (!confirm("Удалить шаблон?")) return;
  const info = document.getElementById("reviewTemplatesInfo");
  try {
    const res = await fetch(`/api/review-quick-templates/${templateId}`, {
      method: "DELETE", headers: withCsrfHeaders(),
    });
    if (!res.ok) { if (info) info.textContent = "Ошибка удаления"; return; }
    await loadReviewTemplates();
  } catch (e) { if (info) info.textContent = "Ошибка удаления"; }
}

// ── Contradiction rules modal ─────────────────────────────────────────────────

async function openContradictionRulesModal() {
  document.getElementById("contradictionRulesModal")?.classList.remove("hidden");
  // Ensure template groups are loaded (same source as Шаблоны tab)
  if (!templateGroupsState.items.length) {
    await loadTemplateGroups();
  }
  const sel = document.getElementById("contradictionGroupSelect");
  if (sel) {
    sel.innerHTML = '<option value="">Выберите категорию...</option>';
    // Use templateGroupsState — exactly the same groups shown in Шаблоны tab
    const groups = templateGroupsState.items.filter(g => {
      const gid = String(g.group_id || g.id || "");
      return gid && gid !== "textless_ratings";
    });
    for (const g of groups) {
      const gid = String(g.group_id || g.id || "");
      const label = String(g.title || g.group_title || labelFromMap(categoryLabels, gid) || gid);
      const opt = document.createElement("option");
      opt.value = gid;
      opt.textContent = label;
      sel.appendChild(opt);
    }
  }
  await loadContradictionRules();
}

function closeContradictionRulesModal() {
  document.getElementById("contradictionRulesModal")?.classList.add("hidden");
}

async function loadContradictionRules() {
  const list = document.getElementById("contradictionRulesModalList");
  const summary = document.getElementById("contradictionRulesList");
  try {
    const res = await fetch("/api/contradiction-rules");
    const data = await res.json();
    const items = data.items || [];
    if (list) {
      if (!items.length) {
        list.innerHTML = '<div class="small" style="color:#94a3b8">Нет правил. Добавьте условие ниже.</div>';
      } else {
        list.innerHTML = items.map(item => {
          const groupLabel = labelFromMap(categoryLabels, item.group_id) || item.group_id;
          const ratingsStr = (item.ratings || []).map(r => `${r}★`).join(", ");
          return `<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 12px;border:1px solid #e2e8f0;border-radius:6px">
            <span><strong>${esc(groupLabel)}</strong> → оценки: ${esc(ratingsStr)}</span>
            <button type="button" class="secondary" style="padding:4px 10px;font-size:12px" onclick="deleteContradictionRule('${esc(item.group_id)}')">Удалить</button>
          </div>`;
        }).join("");
      }
    }
    // Update inline summary in settings pane
    if (summary) {
      summary.textContent = items.length
        ? items.map(i => `${labelFromMap(categoryLabels, i.group_id) || i.group_id}: ${(i.ratings||[]).join(",")}★`).join(" · ")
        : "Правила не настроены";
    }
  } catch (e) {
    if (list) list.textContent = "Ошибка загрузки";
  }
}

async function addContradictionRule() {
  const groupId = document.getElementById("contradictionGroupSelect")?.value;
  const checkedRatings = Array.from(document.querySelectorAll(".cr-rating:checked")).map(cb => Number(cb.value));
  const info = document.getElementById("contradictionRulesModalInfo");
  if (!groupId) { if (info) info.textContent = "Выберите категорию"; return; }
  if (!checkedRatings.length) { if (info) info.textContent = "Выберите хотя бы одну оценку"; return; }
  if (info) info.textContent = "";
  try {
    const res = await fetch(`/api/contradiction-rules?group_id=${encodeURIComponent(groupId)}&ratings=${encodeURIComponent(JSON.stringify(checkedRatings))}`, {
      method: "POST", headers: withCsrfHeaders(),
    });
    const data = await res.json();
    if (!res.ok) { if (info) info.textContent = data.detail || "Ошибка"; return; }
    // Reset checkboxes
    document.querySelectorAll(".cr-rating").forEach(cb => cb.checked = false);
    await loadContradictionRules();
  } catch (e) { if (info) info.textContent = "Ошибка"; }
}

async function deleteContradictionRule(groupId) {
  if (!confirm("Удалить правило?")) return;
  try {
    await fetch(`/api/contradiction-rules?group_id=${encodeURIComponent(groupId)}`, {
      method: "DELETE", headers: withCsrfHeaders(),
    });
    await loadContradictionRules();
  } catch (e) { alert("Ошибка удаления"); }
}

// ── Clear questions by source modal ──────────────────────────────────────────

let _clearQuestionsSelectedSource = null;

function openClearQuestionsModal() {
  const modal = document.getElementById("clearQuestionsModal");
  if (!modal) return;
  const list = document.getElementById("clearQuestionsSourceList");
  if (!list) return;

  // Build source options from account_options loaded by loadQuestions()
  const accounts = Array.isArray(window._questionAccountOptions) ? window._questionAccountOptions : [];
  list.innerHTML = "";
  _clearQuestionsSelectedSource = null;

  // "All sources" option
  const allLabel = document.createElement("label");
  allLabel.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer";
  allLabel.innerHTML = `<input type="radio" name="clearQSrc" value="__all__"> <span>Все источники</span>`;
  list.appendChild(allLabel);

  for (const acc of accounts) {
    const label = document.createElement("label");
    label.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer";
    label.innerHTML = `<input type="radio" name="clearQSrc" value="${esc(String(acc.source || ""))}"> <span>${esc(acc.name || acc.source || String(acc.account_id))}</span>`;
    list.appendChild(label);
  }

  // Default: select first option
  const first = list.querySelector("input[type=radio]");
  if (first) first.checked = true;

  modal.classList.remove("hidden");
}

function closeClearQuestionsModal() {
  document.getElementById("clearQuestionsModal")?.classList.add("hidden");
  _clearQuestionsSelectedSource = null;
}

async function confirmClearQuestions() {
  const selected = document.querySelector("input[name=clearQSrc]:checked");
  const sourceVal = selected ? selected.value : "__all__";
  const sourceLabel = selected?.parentElement?.querySelector("span")?.textContent || "все источники";

  if (!confirm(`Удалить вопросы (${sourceLabel}) из базы?`)) return;

  const btn = document.getElementById("clearQuestionsConfirmBtn");
  if (btn) btn.disabled = true;

  const payload = { kind: "question" };
  if (sourceVal && sourceVal !== "__all__") payload.source = sourceVal;

  try {
    const res = await fetch("/api/admin/conversations-clear", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Не удалось очистить вопросы");
      return;
    }
    const info = document.getElementById("questionsInfo");
    if (info) info.textContent = `Удалено: ${data.deleted || 0}`;
    closeClearQuestionsModal();
    await loadQuestions();
  } catch (e) {
    alert("Ошибка при удалении");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function clearAllQuestions() {
  openClearQuestionsModal();
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

function _updateChatBucketButtons() {
  const bucket = chatsState.bucket || "new";
  const toAnsweredBtn = document.getElementById("chatMoveToAnsweredBtn");
  const toNewBtn = document.getElementById("chatMoveToNewBtn");
  if (!toAnsweredBtn || !toNewBtn) return;
  if (bucket === "processed") {
    // In "Answered" tab → show "Move to New", hide "Move to Answered"
    toAnsweredBtn.classList.add("hidden");
    toNewBtn.classList.remove("hidden");
  } else {
    // In "New" tab (or "all") → show "Move to Answered", hide "Move to New"
    toAnsweredBtn.classList.remove("hidden");
    toNewBtn.classList.add("hidden");
  }
}

async function markChatAnswered() {
  const uid = String(chatsState.activeConversationUid || "").trim();
  if (!uid) {
    alert("Сначала выберите чат");
    return;
  }
  const info = document.getElementById("chatsInfo");
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(uid)}/mark-answered`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) {
      if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось перенести в отвеченные");
      return;
    }
    if (info) info.textContent = "Чат перенесён в «Отвеченные»";
    await loadChats();
  } catch (err) {
    if (info) info.textContent = "Ошибка: не удалось перенести в отвеченные";
  }
}

async function markChatNew() {
  const uid = String(chatsState.activeConversationUid || "").trim();
  if (!uid) {
    alert("Сначала выберите чат");
    return;
  }
  const info = document.getElementById("chatsInfo");
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(uid)}/move-to-new`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) {
      if (info) info.textContent = "Ошибка: " + (data.detail || "не удалось перенести в новые");
      return;
    }
    if (info) info.textContent = "Чат перенесён в «Новые»";
    await loadChats();
  } catch (err) {
    if (info) info.textContent = "Ошибка: не удалось перенести в новые";
  }
}

// ── Analytics ────────────────────────────────────────────────────────────────

function _anDonut(svgId, segments) {
  // segments: [{value, color, label}]
  const svg = document.getElementById(svgId);
  if (!svg) return;
  svg.innerHTML = "";
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (!total) {
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", "60"); circle.setAttribute("cy", "60");
    circle.setAttribute("r", "44"); circle.setAttribute("fill", "none");
    circle.setAttribute("stroke", "#e2e8f0"); circle.setAttribute("stroke-width", "20");
    svg.appendChild(circle);
    return;
  }
  const cx = 60, cy = 60, r = 44, sw = 20;
  const circumference = 2 * Math.PI * r;
  let offset = 0;
  // Start from top (-90deg)
  for (const seg of segments) {
    if (!seg.value) continue;
    const frac = seg.value / total;
    const dash = frac * circumference;
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", cx); circle.setAttribute("cy", cy);
    circle.setAttribute("r", r); circle.setAttribute("fill", "none");
    circle.setAttribute("stroke", seg.color); circle.setAttribute("stroke-width", sw);
    circle.setAttribute("stroke-dasharray", `${dash} ${circumference - dash}`);
    circle.setAttribute("stroke-dashoffset", circumference * 0.25 - offset * circumference);
    circle.setAttribute("transform", `rotate(-90 ${cx} ${cy})`);
    circle.setAttribute("stroke-linecap", "butt");
    svg.appendChild(circle);
    offset += frac;
  }
}

function _anLegend(containerId, segments, total) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = segments.filter(s => s.value > 0).map(s => {
    const pct = total ? Math.round(s.value / total * 100) : 0;
    return `<div class="an-legend-item">
      <span class="an-legend-dot" style="background:${s.color}"></span>
      <span class="an-legend-text">${esc(s.label)}</span>
      <span class="an-legend-val">${s.value} <span class="an-legend-pct">${pct}%</span></span>
    </div>`;
  }).join("");
}

function resetAnalyticsDates() {
  const f = document.getElementById("analyticsDateFrom");
  const t = document.getElementById("analyticsDateTo");
  if (f) f.value = "";
  if (t) t.value = "";
  loadAnalytics();
}

async function loadAnalytics() {
  const source = String(document.getElementById("analyticsSourceFilter")?.value || "");
  const dateFrom = String(document.getElementById("analyticsDateFrom")?.value || "");
  const dateTo = String(document.getElementById("analyticsDateTo")?.value || "");
  const q = new URLSearchParams();
  if (source) q.set("source", source);
  if (dateFrom) q.set("date_from", dateFrom);
  if (dateTo) q.set("date_to", dateTo);
  const url = "/api/analytics" + (q.toString() ? "?" + q.toString() : "");
  const res = await fetch(url);
  const data = await res.json();
  const info = document.getElementById("analyticsInfo");
  if (!res.ok) {
    if (info) info.textContent = data.detail || "Ошибка загрузки аналитики";
    return;
  }
  if (info) info.textContent = "";

  const total = data.total_reviews || 0;

  // KPI cards
  document.getElementById("anTotal").textContent = total.toLocaleString("ru");
  document.getElementById("anProcessed").textContent = (data.processed_reviews || 0).toLocaleString("ru");
  const pctEl = document.getElementById("anProcessedPct");
  if (pctEl) pctEl.textContent = total ? `${data.processed_percent || 0}% обработано` : "";
  document.getElementById("anHighRating").textContent = (data.high_rating_count || 0).toLocaleString("ru");
  document.getElementById("anLowRating").textContent = (data.low_rating_count || 0).toLocaleString("ru");
  document.getElementById("anQuestions").textContent = (data.questions_count || 0).toLocaleString("ru");
  document.getElementById("anChats").textContent = (data.chats_count || 0).toLocaleString("ru");

  // Rating donut (1–5 stars)
  const byRating = data.by_rating || {};
  const ratingColors = { 5: "#16a34a", 4: "#65a30d", 3: "#d97706", 2: "#ea580c", 1: "#dc2626" };
  const ratingSegments = [5, 4, 3, 2, 1].map(s => ({
    value: byRating[s] || 0,
    color: ratingColors[s],
    label: `${s} ★`,
  }));
  const ratingTotal = ratingSegments.reduce((sum, s) => sum + s.value, 0);
  _anDonut("anRatingChart", ratingSegments);
  _anLegend("anRatingLegend", ratingSegments, ratingTotal);

  // Category donut — titles from templateGroupsState (same as Settings → Templates page)
  const groupTitleMap = {};
  for (const g of (templateGroupsState.items || [])) {
    const gid = String(g.group_id || g.id || "");
    const gtitle = String(g.title || g.group_title || "");
    if (gid && gtitle) groupTitleMap[gid] = gtitle;
  }
  const _catLabel = (cat) =>
    groupTitleMap[cat] || labelFromMap(categoryLabels, cat) || cat;

  const catColors = ["#2563eb","#16a34a","#d97706","#7c3aed","#0891b2","#db2777","#94a3b8","#64748b","#f59e0b","#10b981"];
  const byCategory = Array.isArray(data.by_category) ? data.by_category : [];
  const catTotal = byCategory.reduce((s, x) => s + x.count, 0);
  const catSegments = byCategory.slice(0, 9).map((c, i) => ({
    value: c.count,
    color: catColors[i % catColors.length],
    label: _catLabel(c.category),
  }));
  if (byCategory.length > 9) {
    const rest = byCategory.slice(9).reduce((s, x) => s + x.count, 0);
    catSegments.push({ value: rest, color: "#cbd5e1", label: "Прочие" });
  }
  _anDonut("anCategoryChart", catSegments);
  _anLegend("anCategoryLegend", catSegments, catTotal);

  // Source table
  const tbody = document.getElementById("anSourceTbody");
  if (tbody) {
    const rows = Array.isArray(data.by_source) ? data.by_source : [];
    const srcLabels = { wb: "Wildberries", ozon: "Ozon" };
    tbody.innerHTML = rows.map(r => {
      const pct = r.total ? Math.round(r.processed / r.total * 100) : 0;
      const pp = r.total ? Math.round(r.positive / r.total * 100) : 0;
      const np = r.total ? Math.round(r.negative / r.total * 100) : 0;
      return `<tr>
        <td><strong>${esc(srcLabels[r.source] || r.source.toUpperCase())}</strong></td>
        <td>${r.total.toLocaleString("ru")}</td>
        <td>${r.processed.toLocaleString("ru")} <span class="an-pct">${pct}%</span></td>
        <td class="an-positive">${r.positive.toLocaleString("ru")} <span class="an-pct">${pp}%</span></td>
        <td class="an-negative">${r.negative.toLocaleString("ru")} <span class="an-pct">${np}%</span></td>
      </tr>`;
    }).join("") || '<tr><td colspan="5" class="small" style="color:#94a3b8;padding:16px">Нет данных</td></tr>';
  }
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

  // Mobile card list
  const mobileList = document.getElementById("accountsMobileList");
  if (mobileList) {
    mobileList.innerHTML = "";
    for (const account of data.items || []) {
      const rawApiKey = String(account.api_key || "").trim();
      const apiKeyPreview = String(account.api_key_preview || "-");
      const masked = rawApiKey ? smartMaskSecret(rawApiKey) : apiKeyPreview;
      const mp = String(account.marketplace || "").toLowerCase();
      const mpLabel = labelFromMap(marketplaceLabels, account.marketplace);
      const isActive = Boolean(account.is_active);

      // Show only the hostname of the API URL to keep the card compact
      let apiUrlShort = String(account.api_url || "");
      try { apiUrlShort = new URL(apiUrlShort).hostname; } catch (_) {}

      const card = document.createElement("div");
      card.className = "account-card";
      card.innerHTML = `
        <div class="account-card-header">
          <span class="account-card-name">${esc(account.account_name)}</span>
          <div style="display:flex;gap:5px;flex-shrink:0">
            <span class="account-card-badge ${mp}">${esc(mpLabel)}</span>
            <span class="account-card-badge ${isActive ? "active" : "inactive"}">${isActive ? "Активен" : "Отключён"}</span>
          </div>
        </div>
        <div class="account-card-row">
          <span class="account-card-label">API URL</span>
          <span class="account-card-value" title="${esc(account.api_url)}">${esc(apiUrlShort)}</span>
        </div>
        ${(account.extra || {}).client_id ? `<div class="account-card-row"><span class="account-card-label">Client-Id</span><span class="account-card-value">${esc((account.extra || {}).client_id)}</span></div>` : ""}
        <div class="account-card-row">
          <span class="account-card-label">Ключ</span>
          <div class="account-card-key-wrap">
            <span title="${esc(masked || "-")}">${esc(masked || "-")}</span>
            ${rawApiKey ? `<button type="button" class="mobile-copy-key-btn" title="Скопировать ключ" data-key="${esc(rawApiKey)}">📋</button>` : ""}
          </div>
        </div>
        <div class="account-card-actions">
          <button class="secondary" onclick="toggleAccount(${account.id}, ${isActive ? "false" : "true"})">${isActive ? "Отключить" : "Включить"}</button>
          <button class="secondary danger" onclick="deleteAccount(${account.id})">🗑 Удалить</button>
        </div>
      `;
      const copyBtn = card.querySelector(".mobile-copy-key-btn");
      if (copyBtn) {
        copyBtn.addEventListener("click", async () => {
          const key = copyBtn.getAttribute("data-key") || "";
          const copied = await copyAccountApiKey(key);
          if (copied) {
            copyBtn.textContent = "✓";
            window.setTimeout(() => { copyBtn.textContent = "📋"; }, 1500);
          }
        });
      }
      mobileList.appendChild(card);
    }
  }
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
  const canSupplies = Boolean(teamState.pendingCanSupplies);
  if (!permissions.length && !canSupplies) {
    preview.textContent = "Разрешения не выбраны";
  } else {
    preview.textContent = formatManagerPermissionsText(permissions, canSupplies);
  }
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

// ── Supply permissions table ──────────────────────────────────────────────
function renderManagerSupplyPermissionsRows(supplySources, supplyPerms) {
  const tbody = document.getElementById("managerSupplyPermissionsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!supplySources || !supplySources.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:#94a3b8;font-size:12px;text-align:center">Нет источников поставок</td></tr>';
    return;
  }
  const sources = supplyPerms?.sources || {};
  const rowCount = supplySources.length;
  supplySources.forEach((src, idx) => {
    const sid = String(src.id);
    const mp = (src.marketplace || "wb").toLowerCase();
    const srcPerms = sources[sid] || {};
    const tr = document.createElement("tr");
    let settingsCell = "";
    let poaCell = "";
    if (idx === 0) {
      settingsCell = `<td rowspan="${rowCount}" style="text-align:center;vertical-align:middle">
        <input type="checkbox" id="managerSupplySettings" ${supplyPerms?.can_supply_settings ? "checked" : ""} />
      </td>`;
      poaCell = `<td rowspan="${rowCount}" style="text-align:center;vertical-align:middle">
        <input type="checkbox" id="managerSupplyPoa" ${supplyPerms?.can_supply_poa ? "checked" : ""} />
      </td>`;
    }
    const tdSt = "padding:10px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;color:#1e293b";
    const tdCt = tdSt + ";text-align:center";
    const wbDisabled = mp !== "wb" ? "disabled" : "";
    const wbStyle = mp !== "wb" ? "opacity:0.2;cursor:default" : "";
    const ozonDisabled = mp !== "ozon" ? "disabled" : "";
    const ozonStyle = mp !== "ozon" ? "opacity:0.2;cursor:default" : "";
    const settingsMerge = settingsCell ? settingsCell.replace("<td ", `<td style="${tdCt}" `) : "";
    const poaMerge = poaCell ? poaCell.replace("<td ", `<td style="${tdCt}" `) : "";
    tr.innerHTML = `
      <td style="${tdSt}">${esc(src.name || `Источник #${sid}`)}</td>
      <td style="${tdCt}"><input type="checkbox" data-source-id="${sid}" data-col="wb"
          ${srcPerms.wb ? "checked" : ""} ${wbDisabled} style="${wbStyle}" /></td>
      <td style="${tdCt}"><input type="checkbox" data-source-id="${sid}" data-col="ozon"
          ${srcPerms.ozon ? "checked" : ""} ${ozonDisabled} style="${ozonStyle}" /></td>
      ${settingsMerge}${poaMerge}
    `;
    tbody.appendChild(tr);
  });
}

function collectManagerSupplyPermissionsFromModal() {
  const sources = {};
  document.querySelectorAll("#managerSupplyPermissionsTbody input[data-source-id]").forEach(cb => {
    const sid = cb.getAttribute("data-source-id");
    const col = cb.getAttribute("data-col");
    if (!sid || !col) return;
    if (!sources[sid]) sources[sid] = { wb: false, ozon: false };
    sources[sid][col] = Boolean(cb.checked);
  });
  return {
    sources,
    can_supply_settings: Boolean(document.getElementById("managerSupplySettings")?.checked),
    can_supply_poa: Boolean(document.getElementById("managerSupplyPoa")?.checked),
  };
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
    const tdStyle = "padding:10px 12px;border-bottom:1px solid #f1f5f9;font-size:13px;color:#1e293b";
    const tdCenter = tdStyle + ";text-align:center";
    tr.innerHTML = `
      <td style="${tdStyle}">${esc(account.account_name || `Кабинет #${accountId}`)}</td>
      <td style="${tdCenter}"><input type="checkbox" data-account-id="${accountId}" data-scope="reviews" ${rowPerm.can_reviews ? "checked" : ""} /></td>
      <td style="${tdCenter}"><input type="checkbox" data-account-id="${accountId}" data-scope="questions" ${rowPerm.can_questions ? "checked" : ""} /></td>
      <td style="${tdCenter}"><input type="checkbox" data-account-id="${accountId}" data-scope="chats" ${rowPerm.can_chats ? "checked" : ""} /></td>
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

function formatManagerPermissionsText(permissions, canSupplies, supplyPermissions) {
  const rows = Array.isArray(permissions) ? permissions : [];
  // Build supplies summary from granular permissions
  const sp = supplyPermissions || {};
  const srcMap = sp.sources || {};
  const supplyParts = [];
  for (const [sid, sv] of Object.entries(srcMap)) {
    if (sv.wb) supplyParts.push("ВБ");
    if (sv.ozon) supplyParts.push("ОЗОН");
  }
  if (sp.can_supply_settings) supplyParts.push("Настройки");
  if (sp.can_supply_poa) supplyParts.push("Доверенности");
  // Deduplicate
  const uniqueParts = [...new Set(supplyParts)];
  const suppliesText = uniqueParts.length
    ? "Поставки: " + uniqueParts.join(", ")
    : (canSupplies ? "Поставки" : "");
  if (!rows.length && !suppliesText) return "Доступы не назначены";
  if (!rows.length) return suppliesText;
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
    .join("; ") + (suppliesText ? "; " + suppliesText : "");
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
  const mobileList = document.getElementById("teamMobileList");
  if (mobileList) mobileList.innerHTML = "";

  if (!teamState.items.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="6">Менеджеры пока не добавлены</td>';
    tbody.appendChild(tr);
    if (mobileList) {
      mobileList.innerHTML = '<p class="small" style="color:#9ca3af;margin:4px 0">Менеджеры пока не добавлены</p>';
    }
  } else {
    for (const member of teamState.items) {
      const memberId = Number(member.id || 0);
      const permsText = formatManagerPermissionsText(member.manager_permissions || [], member.can_supplies, member.supply_permissions);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(member.id)}</td>
        <td>${esc(member.email || "")}</td>
        <td>${esc(member.full_name || "")}</td>
        <td>${esc(roleLabels[member.role] || member.role || "-")}</td>
        <td>${esc(permsText)}</td>
        <td>
          <div class="row" style="gap:4px">
            <button class="icon-btn" title="Редактировать" onclick="openEditTeamMember(${memberId})">✏</button>
            <button class="icon-btn danger" title="Удалить менеджера" onclick="deleteTeamMember(${memberId})">🗑</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);

      // Mobile card
      if (mobileList) {
        const card = document.createElement("div");
        card.className = "team-card";
        card.innerHTML = `
          <div class="team-card-header">
            <span class="team-card-email">${esc(member.email || "")}</span>
            <span class="account-card-badge" style="background:rgba(99,102,241,0.12);color:#4338ca">${esc(roleLabels[member.role] || member.role || "-")}</span>
          </div>
          ${member.full_name ? `<div class="team-card-row">ФИО: <b>${esc(member.full_name)}</b></div>` : ""}
          ${permsText ? `<div class="team-card-row small" style="white-space:pre-wrap">${esc(permsText)}</div>` : ""}
          <div class="team-card-actions">
            <button class="secondary danger" onclick="deleteTeamMember(${memberId})">🗑 Удалить</button>
          </div>
        `;
        mobileList.appendChild(card);
      }
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

// ── Edit team member ────────────────────────────────────────────────────────
let _editingMemberId = null;

async function openEditTeamMember(userId) {
  _editingMemberId = userId;
  const member = teamState.items.find(m => Number(m.id) === userId);
  if (!member) return;
  document.getElementById("editMemberFullName").value = member.full_name || "";
  document.getElementById("editMemberPassword").value = "";
  document.getElementById("editMemberInfo").textContent = "";
  // Show current permissions
  const permText = formatManagerPermissionsText(member.manager_permissions || [], member.can_supplies, member.supply_permissions);
  document.getElementById("editMemberPermissionsPreview").textContent = permText || "Нет доступов";
  // Pre-load permissions into the shared permissions modal state
  _pendingManagerPermissions = (member.manager_permissions || []).map(p => ({...p}));
  _pendingManagerCanSupplies = Boolean(member.can_supplies);
  const modal = document.getElementById("editTeamMemberModal");
  if (modal) { modal.classList.remove("hidden"); modal.style.display = ""; }
}

function closeEditTeamMember() {
  const modal = document.getElementById("editTeamMemberModal");
  if (modal) { modal.classList.add("hidden"); modal.style.display = "none"; }
  _editingMemberId = null;
}

async function openManagerPermissionsModalForEdit() {
  if (!Array.isArray(teamState.accounts) || !teamState.accounts.length) await loadAccounts();
  const member = teamState.items.find(m => Number(m.id) === _editingMemberId);
  if (!member) return;
  teamState.pendingPermissions = (member.manager_permissions || []).map(p => ({...p}));
  teamState.pendingCanSupplies = Boolean(member.can_supplies);
  // Load supply permissions
  const spRes = await fetch(`/api/tenant/team/${_editingMemberId}/supply-permissions`).catch(() => null);
  const spData = spRes?.ok ? await spRes.json().catch(() => ({})) : {};
  teamState.pendingSupplyPermissions = spData;
  const info = document.getElementById("managerPermissionsInfo");
  if (info) { info.textContent = ""; info.style.color = ""; }
  const saveBtn = document.getElementById("managerPermissionsSaveBtn");
  if (saveBtn) saveBtn.textContent = "Применить разрешения";
  renderManagerPermissionsRows(teamState.accounts, teamState.pendingPermissions);
  // Load supply sources and render supply table
  const ssRes = await fetch("/api/supply-sources").catch(() => null);
  const ssSources = ssRes?.ok ? await ssRes.json().catch(() => []) : [];
  renderManagerSupplyPermissionsRows(ssSources, teamState.pendingSupplyPermissions);
  setModalVisibility("managerPermissionsModal", true);
}

async function saveEditTeamMember() {
  if (!_editingMemberId) return;
  const uid = _editingMemberId;
  const fullName = document.getElementById("editMemberFullName")?.value.trim() || "";
  const password = document.getElementById("editMemberPassword")?.value || "";
  const info = document.getElementById("editMemberInfo");
  if (info) { info.textContent = "Сохранение..."; info.style.color = ""; }
  try {
    // Update full name
    await fetch(`/api/tenant/team/${uid}/profile`, {
      method: "PATCH", headers: jsonHeaders(), body: JSON.stringify({ full_name: fullName })
    });
    // Update password if provided
    if (password) {
      if (password.length < 8) {
        if (info) { info.textContent = "Пароль минимум 8 символов"; info.style.color = "#b91c1c"; }
        return;
      }
      const pr = await fetch(`/api/tenant/team/${uid}/password`, {
        method: "POST", headers: jsonHeaders(), body: JSON.stringify({ password })
      });
      if (!pr.ok) {
        const e = await pr.json().catch(() => ({}));
        if (info) { info.textContent = e.detail || "Ошибка смены пароля"; info.style.color = "#b91c1c"; }
        return;
      }
    }
    // Update permissions
    const permsPayload = (teamState.pendingPermissions || []).filter(p => p.can_reviews || p.can_questions || p.can_chats);
    await fetch(`/api/tenant/team/${uid}/permissions`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify({ permissions: permsPayload })
    });
    const sp = teamState.pendingSupplyPermissions || {};
    await fetch(`/api/tenant/team/${uid}/supplies-access`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify({
        can_supplies: Boolean(teamState.pendingCanSupplies),
        can_supply_settings: Boolean(sp.can_supply_settings),
        can_supply_poa: Boolean(sp.can_supply_poa),
        supply_sources: sp.sources || {},
      })
    });
    if (info) { info.textContent = "Сохранено"; info.style.color = "#16a34a"; }
    await loadTeam();
    setTimeout(closeEditTeamMember, 800);
  } catch(e) {
    if (info) { info.textContent = "Ошибка: " + e.message; info.style.color = "#b91c1c"; }
  }
}

window.openEditTeamMember = openEditTeamMember;
window.closeEditTeamMember = closeEditTeamMember;
window.openManagerPermissionsModalForEdit = openManagerPermissionsModalForEdit;
window.saveEditTeamMember = saveEditTeamMember;

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
  // Load supply sources for new manager (no existing permissions)
  const ssRes = await fetch("/api/supply-sources").catch(() => null);
  const ssSources = ssRes?.ok ? await ssRes.json().catch(() => []) : [];
  renderManagerSupplyPermissionsRows(ssSources, {});
  setModalVisibility("managerPermissionsModal", true);
}

function applyManagerPermissionsSelection() {
  const permissions = collectManagerPermissionsFromModal();
  const supplyPerms = collectManagerSupplyPermissionsFromModal();
  teamState.pendingSupplyPermissions = supplyPerms;
  const hasAnySupply = supplyPerms.can_supply_settings || supplyPerms.can_supply_poa ||
    Object.values(supplyPerms.sources || {}).some(s => s.wb || s.ozon);
  teamState.pendingCanSupplies = hasAnySupply;
  if (!permissions.length && !hasAnySupply) {
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
  // Update preview in edit modal if open
  const editPreview = document.getElementById("editMemberPermissionsPreview");
  if (editPreview && _editingMemberId) {
    const txt = formatManagerPermissionsText(permissions, teamState.pendingCanSupplies, teamState.pendingSupplyPermissions);
    editPreview.textContent = txt || "Нет доступов";
  }
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
  const canSupplies = Boolean(teamState.pendingCanSupplies);
  if (!permissions.length && !canSupplies) {
    setTeamInfo("Сначала нажмите «Разрешения» и выберите хотя бы один доступ.", true);
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
    const detail = data.detail;
    const msg = Array.isArray(detail)
      ? detail.map((e) => e.msg || JSON.stringify(e)).join("; ")
      : String(detail || "не удалось создать менеджера");
    setTeamInfo("Ошибка: " + msg, true);
    return;
  }
  // Set can_supplies if checked
  if (teamState.pendingCanSupplies && data.item?.id) {
    await fetch(`/api/tenant/team/${data.item.id}/supplies-access`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify({ can_supplies: true }),
    }).catch(() => {});
  }
  document.getElementById("teamManagerEmail").value = "";
  document.getElementById("teamManagerPassword").value = "";
  document.getElementById("teamManagerFullName").value = "";
  teamState.pendingPermissions = [];
  teamState.pendingCanSupplies = false;
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
  populateCategoryFilter();
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

// ── Product photos catalog ────────────────────────────────────────────────────

let _productsCache = [];

function openAddProductForm(editItem = null) {
  document.getElementById("productAddForm")?.classList.remove("hidden");
  document.getElementById("productFormInfo").textContent = "";
  document.getElementById("productFormEditId").value = editItem ? String(editItem.id) : "";
  document.getElementById("productFormName").value = editItem?.name || "";
  document.getElementById("productFormSupplierArticle").value = editItem?.supplier_article || "";
  document.getElementById("productFormWbNmid").value = editItem?.wb_nmid || "";
  document.getElementById("productFormOzonSku").value = editItem?.ozon_sku || "";
  document.getElementById("productFormPhoto").value = "";
  document.getElementById("productFormName").focus();
}

function closeAddProductForm() {
  document.getElementById("productAddForm")?.classList.add("hidden");
}

async function loadProducts() {
  const tbody = document.getElementById("productsTbody");
  const info = document.getElementById("productsInfo");
  if (!tbody) return;
  try {
    const res = await fetch("/api/products");
    const data = await res.json();
    _productsCache = data.items || [];
    if (info) info.textContent = `Товаров: ${_productsCache.length}`;
    tbody.innerHTML = "";
    if (!_productsCache.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="small" style="color:#94a3b8;padding:16px">Нет товаров. Нажмите «+ Добавить товар»</td></tr>';
      return;
    }
    for (const item of _productsCache) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${item.photo_url ? `<img src="${esc(item.photo_url)}" class="product-thumb" alt="" onerror="this.style.display='none'">` : '<div class="product-thumb-empty"></div>'}</td>
        <td>${esc(item.name || "")}</td>
        <td>${esc(item.supplier_article || "—")}</td>
        <td>${esc(item.wb_nmid || "—")}</td>
        <td>${esc(item.ozon_sku || "—")}</td>
        <td>
          <button type="button" class="secondary" style="font-size:12px;padding:4px 8px" onclick="editProduct(${item.id})">✏</button>
          <button type="button" class="secondary danger" style="font-size:12px;padding:4px 8px" onclick="deleteProduct(${item.id})">✕</button>
        </td>`;
      tbody.appendChild(tr);
    }
  } catch (e) {
    if (info) info.textContent = "Ошибка загрузки";
  }
}

function editProduct(id) {
  const item = _productsCache.find(p => p.id === id);
  if (item) openAddProductForm(item);
}

async function saveProduct() {
  const editId = String(document.getElementById("productFormEditId")?.value || "").trim();
  const name = String(document.getElementById("productFormName")?.value || "").trim();
  const supplierArticle = String(document.getElementById("productFormSupplierArticle")?.value || "").trim();
  const wbNmid = String(document.getElementById("productFormWbNmid")?.value || "").trim();
  const ozonSku = String(document.getElementById("productFormOzonSku")?.value || "").trim();
  const photoFile = document.getElementById("productFormPhoto")?.files?.[0];
  const info = document.getElementById("productFormInfo");
  if (!name) { if (info) info.textContent = "Введите наименование"; return; }
  const fd = new FormData();
  fd.append("name", name);
  fd.append("supplier_article", supplierArticle);
  fd.append("wb_nmid", wbNmid);
  fd.append("ozon_sku", ozonSku);
  if (photoFile) fd.append("photo", photoFile);
  try {
    const url = editId ? `/api/products/${editId}` : "/api/products";
    const method = editId ? "PUT" : "POST";
    const res = await fetch(url, { method, body: fd, headers: withCsrfHeaders() });
    const data = await res.json();
    if (!res.ok) { if (info) info.textContent = data.detail || "Ошибка"; return; }
    closeAddProductForm();
    await loadProducts();
  } catch (e) { if (info) info.textContent = "Ошибка сохранения"; }
}

async function deleteProduct(id) {
  if (!confirm("Удалить товар?")) return;
  try {
    await fetch(`/api/products/${id}`, { method: "DELETE", headers: withCsrfHeaders() });
    await loadProducts();
  } catch (e) { alert("Ошибка удаления"); }
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
  if (!permissions.can_view_supplies) {
    document.getElementById("section-supplies-wb")?.classList.add("hidden");
    document.getElementById("section-supplies-settings")?.classList.add("hidden");
  }
  if (!permissions.can_view_feedback) {
    ["section-reviews", "section-conversations", "section-chats"].forEach((id) => {
      document.getElementById(id)?.classList.add("hidden");
    });
    // Hide feedback nav items
    ["nav-reviews", "nav-conversations", "nav-chats"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = "none";
    });
    // Also hide the nav section label if all feedback items are hidden
    const feedbackLabel = document.querySelector(".sidebar-nav .nav-section-label");
    if (feedbackLabel) feedbackLabel.style.display = "none";
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
  initNavGroups();
  if (permissions.is_admin) {
    document.getElementById("adminStopSyncBtn")?.classList.remove("hidden");
    document.getElementById("adminClearReviewsBtn")?.classList.remove("hidden");
    document.getElementById("adminClearQuestionsBtn")?.classList.remove("hidden");
    document.getElementById("adminClearChatsBtn")?.classList.remove("hidden");
    // Delete all chats button is only for admins — managers should not accidentally
    // wipe all chat history
    document.getElementById("clearChatsBtn")?.classList.remove("hidden");
    // Reset templates button — admins only
    document.getElementById("resetTemplatesToDefaultsBtn")?.classList.remove("hidden");
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
    // Close sort dropdown when clicking outside
    // Close supplies date panel on outside click
    const suppliesDatePanelEl = document.getElementById("suppliesDatePanel");
    const suppliesDateBtnEl = document.getElementById("suppliesDateBtn");
    if (suppliesDatePanelEl && suppliesDatePanelEl.style.display === "flex" &&
        !suppliesDatePanelEl.contains(target) && suppliesDateBtnEl && !suppliesDateBtnEl.contains(target)) {
      toggleSuppliesDatePanel(false);
    }
    // Close OZON date panel on outside click
    const ozonDatePanelEl = document.getElementById("ozonDatePanel");
    const ozonDateBtnEl = document.getElementById("ozonDateBtn");
    if (ozonDatePanelEl && ozonDatePanelEl.style.display === "flex" &&
        !ozonDatePanelEl.contains(target) && ozonDateBtnEl && !ozonDateBtnEl.contains(target)) {
      toggleOzonDatePanel(false);
    }
    const sortWrap = document.querySelector(".chats-sort-wrap");
    const sortDd = document.getElementById("chatsSortDropdown");
    if (sortDd && !sortDd.classList.contains("hidden") && sortWrap && !sortWrap.contains(target)) {
      sortDd.classList.add("hidden");
    }
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
    closeSupplyDetailsModal();
    toggleChatEmojiPicker(false);
    closeMobileNavMenu();
  });
  window.addEventListener("resize", closeMobileNavIfDesktop);
  document.getElementById("ruleCategory")?.addEventListener("change", syncRuleFormFromStore);
  document.getElementById("tplCategory")?.addEventListener("change", syncTemplateFormFromStore);
  // On page load: check if a manual sync is already running (e.g. user navigated
  // away and came back). Only show the progress bar for manual syncs — not for
  // the background 60s auto-sync which runs silently.
  fetch("/api/sync/status").then((r) => r.ok ? r.json() : null).then((p) => {
    if (p && p.in_progress && p.is_manual) {
      syncInProgress = true;
      const syncButton = document.getElementById("syncAllBtn");
      if (syncButton) {
        syncButton.disabled = true;
        syncButton.textContent = "⏳ Синхронизация...";
      }
      showSyncProgress();
      updateSyncProgressUI(p);
      startGlobalSyncPoll();
    }
  }).catch(() => {});

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
    loadContradictionRules();
    loadProducts();
  }
  // Supplies module
  if (permissions.can_view_supplies) {
    const suppliesNavLabel = document.getElementById("nav-section-supplies");
    if (suppliesNavLabel) suppliesNavLabel.style.display = "flex";
    // "Удалить поставки" — только для владельцев, не для менеджеров
    if (!permissions.can_view_settings) {
      const clearBtn = document.getElementById("suppliesClearBtn");
      if (clearBtn) clearBtn.style.display = "none";
      // Скрыть вкладку "Источники" в настройках поставок — только водители
      const sourcesTab = document.getElementById("supplies-settings-tab-sources");
      if (sourcesTab) sourcesTab.style.display = "none";
    }
    Promise.all([
      loadSupplySources(),
      loadSupplyDrivers(),
      loadSupplyWarehouses(),
      loadSupplyLegalEntities(),
      loadSupplyProductions(),
      loadSupplyContractors(),
      loadPoARecords(),
    ]).then(() => loadSupplies()).catch(() => {});
    initSuppliesColumnResizer();
    initOzonSuppliesColumnResizer();
  }
  // Load stock sources/reports lazily
  loadStockSources().then(() => loadStockReports()).catch(() => {});
  // Hook ozon client-id toggle
  document.getElementById("addStockMarketplace")?.addEventListener("change", toggleOzonClientIdRow);
  requestAnimationFrame(() => {
    document.body.classList.remove(APP_BOOT_HIDE_CLASS);
  });
  // Start silent 60s UI refresh so chat list stays up-to-date
  // without requiring manual page reload
  startUiRefresh();
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
// Supplies module
window.toggleAddDriverForm = toggleAddDriverForm;
window.saveSupplyDriver = saveSupplyDriver;
window.deleteSupplyDriver = deleteSupplyDriver;
window.addDriverFromModal = addDriverFromModal;
window.cancelNewDriverInModal = cancelNewDriverInModal;
window.onDriverSelectChange = onDriverSelectChange;
window.toggleAddSupplySourceForm = toggleAddSupplySourceForm;
window.createSupplySource = createSupplySource;
window.toggleSupplySource = toggleSupplySource;
window.deleteSupplySource = deleteSupplySource;
window.syncSupplies = syncSupplies;
window.clearSupplies = clearSupplies;
window.loadSupplies = loadSupplies;
window.suppliesChangePage = suppliesChangePage;
window.changeSuppliesPageSize = changeSuppliesPageSize;
window.toggleSupplyGoods = toggleSupplyGoods;
window.startEditDriver = startEditDriver;
window.saveEditDriver = saveEditDriver;
window.startEditWarehouse = startEditWarehouse;
window.saveEditWarehouse = saveEditWarehouse;
window.startEditLegalEntity = startEditLegalEntity;
window.saveEditLegalEntity = saveEditLegalEntity;
window.toggleAddWarehouseForm = toggleAddWarehouseForm;
window.saveSupplyWarehouse = saveSupplyWarehouse;
window.deleteSupplyWarehouse = deleteSupplyWarehouse;
window.toggleAddLegalEntityForm = toggleAddLegalEntityForm;
window.saveSupplyLegalEntity = saveSupplyLegalEntity;
window.deleteSupplyLegalEntity = deleteSupplyLegalEntity;

// ── Supply Productions ──────────────────────────────────────────────────────
let _supplyProductionsCache = [];

async function loadSupplyProductions() {
  const res = await fetch("/api/supply-productions").catch(() => null);
  if (!res || !res.ok) return;
  _supplyProductionsCache = await res.json().catch(() => []);
  renderSupplyProductionsTbody();
  _populateProductionSelects();
}

function _populateProductionSelects() {
  const names = _supplyProductionsCache.map(p => p.name);
  // Filter dropdown (top of table)
  const filterSel = document.getElementById("suppliesProductionFilter");
  if (filterSel) {
    const cur = filterSel.value;
    filterSel.innerHTML = '<option value="">Все производства</option>' +
      names.map(n => `<option value="${esc(n)}"${n===cur?' selected':''}>${esc(n)}</option>`).join("");
  }
  // Modal dropdown (WB)
  const modalSel = document.getElementById("sdProduction");
  if (modalSel) {
    const cur = modalSel.value;
    modalSel.innerHTML = '<option value="">— Не выбрано —</option>' +
      names.map(n => `<option value="${esc(n)}"${n===cur?' selected':''}>${esc(n)}</option>`).join("");
  }
  // Modal dropdown (OZON)
  const ozonModalSel = document.getElementById("ozonSdProduction");
  if (ozonModalSel) {
    const cur = ozonModalSel.value;
    ozonModalSel.innerHTML = '<option value="">— Не выбрано —</option>' +
      names.map(n => `<option value="${esc(n)}"${n===cur?' selected':''}>${esc(n)}</option>`).join("");
  }
}

function renderSupplyProductionsTbody() {
  const tbody = document.getElementById("supplyProductionsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!_supplyProductionsCache.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">Производства не добавлены</td></tr>';
    return;
  }
  _supplyProductionsCache.forEach((p, i) => {
    const tr = document.createElement("tr");
    tr.dataset.id = p.id;
    tr.innerHTML = `<td>${i+1}</td>
      <td class="editable-cell">${esc(p.name||"")}</td>
      <td class="editable-cell">${esc(p.head_name||"")}</td>
      <td>
        <div class="row" style="gap:4px;flex-wrap:nowrap">
          <button class="secondary small-btn" onclick="startEditProduction(${p.id})">✏</button>
          <button class="secondary small-btn icon-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="deleteSupplyProduction(${p.id})" title="Удалить">🗑</button>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });
}

async function startEditProduction(id) {
  const item = _supplyProductionsCache.find(x => x.id === id);
  if (!item) return;
  const tr = document.querySelector(`#supplyProductionsTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const cells = tr.querySelectorAll(".editable-cell");
  cells[0].innerHTML = `<input class="edit-inline-input" value="${esc(item.name||"")}" />`;
  cells[1].innerHTML = `<input class="edit-inline-input" value="${esc(item.head_name||"")}" />`;
  tr.cells[tr.cells.length-1].innerHTML = `<div class="row" style="gap:4px;flex-wrap:nowrap">
    <button class="secondary small-btn" style="color:#16a34a;border-color:#86efac" onclick="saveEditProduction(${id})">Сохранить</button>
    <button class="secondary small-btn" onclick="loadSupplyProductions()">Отмена</button>
  </div>`;
}

async function saveEditProduction(id) {
  const tr = document.querySelector(`#supplyProductionsTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const inputs = tr.querySelectorAll(".edit-inline-input");
  const name = inputs[0]?.value.trim() || "";
  const head_name = inputs[1]?.value.trim() || "";
  if (!name) return;
  await fetch(`/api/supply-productions/${id}`, { method: "PATCH", headers: jsonHeaders(), body: JSON.stringify({ name, head_name }) }).catch(() => null);
  await loadSupplyProductions();
}

function toggleAddProductionForm(show) {
  const form = document.getElementById("addProductionForm");
  if (!form) return;
  form.classList.toggle("hidden", !show); form.style.display = show ? "" : "none";
  if (!show) {
    ["newProductionName","newProductionHead"].forEach(id => { const el = document.getElementById(id); if(el) el.value=""; });
  }
}

async function saveSupplyProduction() {
  const name = document.getElementById("newProductionName")?.value.trim();
  const head_name = document.getElementById("newProductionHead")?.value.trim() || "";
  const info = document.getElementById("addProductionInfo");
  if (!name) { if (info) { info.textContent = "Введите название"; info.style.color = "#b91c1c"; } return; }
  if (info) { info.textContent = "Сохранение..."; info.style.color = ""; }
  const res = await fetch("/api/supply-productions", { method: "POST", headers: jsonHeaders(), body: JSON.stringify({ name, head_name }) }).catch(() => null);
  if (!res || !res.ok) { const e = await res?.json().catch(()=>({})) || {}; if (info) { info.textContent = e.detail||"Ошибка"; info.style.color = "#b91c1c"; } return; }
  if (info) { info.textContent = "Сохранено"; info.style.color = "#16a34a"; }
  toggleAddProductionForm(false);
  await loadSupplyProductions();
}

async function deleteSupplyProduction(id) {
  if (!confirm("Удалить производство?")) return;
  await fetch(`/api/supply-productions/${id}`, { method: "DELETE", headers: jsonHeaders() }).catch(() => null);
  await loadSupplyProductions();
}

window.toggleAddProductionForm = toggleAddProductionForm;
window.saveSupplyProduction = saveSupplyProduction;
window.deleteSupplyProduction = deleteSupplyProduction;
window.startEditProduction = startEditProduction;
window.saveEditProduction = saveEditProduction;
window.loadSupplyProductions = loadSupplyProductions;

// ── Supply Contractors ──────────────────────────────────────────────────────
let _supplyContractorsCache = [];

async function loadSupplyContractors() {
  const res = await fetch("/api/supply-contractors").catch(() => null);
  if (!res || !res.ok) return;
  _supplyContractorsCache = await res.json().catch(() => []);
  renderSupplyContractorsTbody();
}

function renderSupplyContractorsTbody() {
  const tbody = document.getElementById("supplyContractorsTbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!_supplyContractorsCache.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">Контрагенты не добавлены</td></tr>';
    return;
  }
  _supplyContractorsCache.forEach((c, i) => {
    const tr = document.createElement("tr");
    tr.dataset.id = c.id;
    tr.innerHTML = `<td>${i+1}</td>
      <td class="editable-cell">${esc(c.name||"")}</td>
      <td class="editable-cell">${esc(c.requisites||"")}</td>
      <td>
        <div class="row" style="gap:4px;flex-wrap:nowrap">
          <button class="secondary small-btn" onclick="startEditContractor(${c.id})">✏</button>
          <button class="secondary small-btn icon-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="deleteSupplyContractor(${c.id})" title="Удалить">🗑</button>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });
}

async function startEditContractor(id) {
  const item = _supplyContractorsCache.find(x => x.id === id);
  if (!item) return;
  const tr = document.querySelector(`#supplyContractorsTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const cells = tr.querySelectorAll(".editable-cell");
  cells[0].innerHTML = `<input class="edit-inline-input" value="${esc(item.name||"")}" />`;
  cells[1].innerHTML = `<input class="edit-inline-input" value="${esc(item.requisites||"")}" />`;
  tr.cells[tr.cells.length-1].innerHTML = `<div class="row" style="gap:4px;flex-wrap:nowrap">
    <button class="secondary small-btn" style="color:#16a34a;border-color:#86efac" onclick="saveEditContractor(${id})">Сохранить</button>
    <button class="secondary small-btn" onclick="loadSupplyContractors()">Отмена</button>
  </div>`;
}

async function saveEditContractor(id) {
  const tr = document.querySelector(`#supplyContractorsTbody tr[data-id="${id}"]`);
  if (!tr) return;
  const inputs = tr.querySelectorAll(".edit-inline-input");
  const name = inputs[0]?.value.trim() || "";
  const requisites = inputs[1]?.value.trim() || "";
  if (!name) return;
  await fetch(`/api/supply-contractors/${id}`, { method: "PATCH", headers: jsonHeaders(), body: JSON.stringify({ name, requisites }) }).catch(() => null);
  await loadSupplyContractors();
}

function toggleAddContractorForm(show) {
  const form = document.getElementById("addContractorForm");
  if (!form) return;
  form.classList.toggle("hidden", !show); form.style.display = show ? "" : "none";
  if (!show) {
    ["newContractorName","newContractorRequisites"].forEach(id => { const el = document.getElementById(id); if(el) el.value=""; });
  }
}

async function saveSupplyContractor() {
  const name = document.getElementById("newContractorName")?.value.trim();
  const requisites = document.getElementById("newContractorRequisites")?.value.trim() || "";
  const info = document.getElementById("addContractorInfo");
  if (!name) { if (info) { info.textContent = "Введите название"; info.style.color = "#b91c1c"; } return; }
  if (info) { info.textContent = "Сохранение..."; info.style.color = ""; }
  const res = await fetch("/api/supply-contractors", { method: "POST", headers: jsonHeaders(), body: JSON.stringify({ name, requisites }) }).catch(() => null);
  if (!res || !res.ok) { const e = await res?.json().catch(()=>({})) || {}; if (info) { info.textContent = e.detail||"Ошибка"; info.style.color = "#b91c1c"; } return; }
  if (info) { info.textContent = "Сохранено"; info.style.color = "#16a34a"; }
  toggleAddContractorForm(false);
  await loadSupplyContractors();
}

async function deleteSupplyContractor(id) {
  if (!confirm("Удалить контрагента?")) return;
  await fetch(`/api/supply-contractors/${id}`, { method: "DELETE", headers: jsonHeaders() }).catch(() => null);
  await loadSupplyContractors();
}

window.toggleAddContractorForm = toggleAddContractorForm;
window.saveSupplyContractor = saveSupplyContractor;
window.deleteSupplyContractor = deleteSupplyContractor;
window.startEditContractor = startEditContractor;
window.saveEditContractor = saveEditContractor;
window.loadSupplyContractors = loadSupplyContractors;

// ── Supply PoA Records ────────────────────────────────────────────────────
let _poaRecords = [];

async function loadPoARecords() {
  const res = await fetch("/api/supply-poa-records").catch(() => null);
  if (!res || !res.ok) return;
  _poaRecords = await res.json().catch(() => []);
  _populatePoAFilters();
  renderPoATable();
}

function _populatePoAFilters() {
  const cf = document.getElementById("poaContractorFilter");
  const df = document.getElementById("poaDriverFilter");
  if (cf) {
    const contractors = [...new Map(_poaRecords.map(r => [r.contractor_id, r.c_name])).entries()];
    cf.innerHTML = '<option value="">Все контрагенты</option>' +
      contractors.map(([id, name]) => `<option value="${id}">${esc(name||"")}</option>`).join("");
  }
  if (df) {
    const drivers = [...new Map(_poaRecords.map(r => [r.driver_id, r.d_full])).entries()];
    df.innerHTML = '<option value="">Все водители</option>' +
      drivers.map(([id, name]) => `<option value="${id}">${esc(name||"")}</option>`).join("");
  }
}

function renderPoATable() {
  const tbody = document.getElementById("poaTbody");
  if (!tbody) return;
  const cf = document.getElementById("poaContractorFilter")?.value || "";
  const df = document.getElementById("poaDriverFilter")?.value || "";
  const sq = (document.getElementById("poaSearch")?.value || "").toLowerCase();

  let rows = _poaRecords;
  if (cf) rows = rows.filter(r => String(r.contractor_id) === cf);
  if (df) rows = rows.filter(r => String(r.driver_id) === df);
  if (sq) rows = rows.filter(r =>
    (r.le_short||"").toLowerCase().includes(sq) ||
    (r.c_name||"").toLowerCase().includes(sq) ||
    (r.d_full||"").toLowerCase().includes(sq)
  );

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">Доверенности не найдены</td></tr>';
    return;
  }
  tbody.innerHTML = "";
  rows.forEach((r, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i+1}</td>
      <td>${esc(r.poa_date||"")}</td>
      <td>${esc(r.le_short||"")}</td>
      <td>${esc(r.c_name||"")}</td>
      <td>${esc((r.driver_id > 0 ? r.d_full : r.driver_manual_name)||"")}</td>
      <td>
        <div class="row" style="gap:4px;flex-wrap:nowrap">
          <button class="secondary small-btn icon-btn" onclick="downloadPoAPdf(${r.id})" title="Скачать PDF" style="font-size:10px;min-width:36px">PDF</button>
          <button class="secondary small-btn icon-btn" onclick="downloadPoADoc(${r.id})" title="Скачать DOC" style="font-size:10px;min-width:36px">DOC</button>
          <button class="secondary small-btn icon-btn" onclick="printPoARecord(${r.id})" title="Печать">⎙</button>
          <button class="secondary small-btn icon-btn" onclick="openEditPoAModal(${r.id})" title="Редактировать">✏</button>
          <button class="secondary small-btn icon-btn" style="color:#2563eb;border-color:#93c5fd" onclick="openCopyPoAModal(${r.id})" title="Копировать">⎘</button>
          <button class="secondary small-btn icon-btn" style="color:#b91c1c;border-color:#fca5a5" onclick="deletePoARecord(${r.id})" title="Удалить">🗑</button>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });
}

function _poaFileName(id, ext) {
  const r = _poaRecords.find(x => x.id === id);
  if (!r) return `Доверенность_${id}.${ext}`;
  const le = (r.le_short || "").replace(/[/\\?%*:|"<>]/g, "");
  const cn = (r.c_name || "").replace(/[/\\?%*:|"<>]/g, "");
  const dr = (r.driver_id > 0 ? r.d_full : r.driver_manual_name || "").replace(/[/\\?%*:|"<>]/g, "");
  return `${le}_${cn}_${dr}.${ext}`;
}

function downloadPoADoc(id) {
  const a = document.createElement("a");
  a.href = `/api/supply-poa-records/${id}/doc`;
  a.download = _poaFileName(id, "doc");
  a.click();
}

function downloadPoAPdf(id) {
  const a = document.createElement("a");
  a.href = `/api/supply-poa-records/${id}/pdf`;
  a.download = _poaFileName(id, "pdf");
  a.click();
}

window.downloadPoADoc = downloadPoADoc;
window.downloadPoAPdf = downloadPoAPdf;

function printPoARecord(id) {
  const url = `/api/supply-poa-records/${id}/html`;
  const win = window.open(url, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
  // Auto-print after page loads
  if (win) {
    win.addEventListener("load", () => {
      try { win.print(); } catch(_) {}
    });
  }
}

async function deletePoARecord(id) {
  if (!confirm("Удалить доверенность?")) return;
  await fetch(`/api/supply-poa-records/${id}`, { method: "DELETE", headers: jsonHeaders() }).catch(() => null);
  await loadPoARecords();
}

async function _openPoAModal(mode, record) {
  _poaModalMode = mode;
  _poaEditingId = mode === "edit" ? record?.id : null;
  // Ensure caches loaded
  if (!_supplyLegalEntitiesCache.length) await loadSupplyLegalEntities();
  if (!_supplyContractorsCache.length) await loadSupplyContractors();
  if (!_supplyDriversCache.length) await loadSupplyDrivers();
  // Populate dropdowns
  const lSel = document.getElementById("poaCreateLegal");
  const cSel = document.getElementById("poaCreateContractor");
  const dSel = document.getElementById("poaCreateDriver");
  if (lSel) lSel.innerHTML = '<option value="">— Выберите юр. лицо —</option>' +
    _supplyLegalEntitiesCache.map(e => `<option value="${e.id}">${esc(e.short_name||"")}</option>`).join("");
  if (cSel) cSel.innerHTML = '<option value="">— Выберите контрагента —</option>' +
    _supplyContractorsCache.map(c => `<option value="${c.id}">${esc(c.name||"")}</option>`).join("");
  if (dSel) dSel.innerHTML = '<option value="">— Выберите водителя —</option>' +
    _supplyDriversCache.map(d => `<option value="${d.id}">${esc(d.full_name||"")}</option>`).join("");
  const info = document.getElementById("poaCreateInfo");
  if (info) { info.textContent = ""; info.style.color = ""; }
  // Reset manual driver mode
  _poaManualDriverMode = false;
  const mf = document.getElementById("poaManualDriverFields");
  if (mf) mf.style.display = "none";
  if (dSel) dSel.disabled = false;
  const btn = document.getElementById("poaManualDriverBtn");
  if (btn) { btn.style.background = ""; btn.style.borderColor = ""; }
  // Pre-fill if edit or copy
  if (record) {
    if (lSel) lSel.value = String(record.legal_entity_id || "");
    if (cSel) cSel.value = String(record.contractor_id || "");
    const dId = record.driver_id || 0;
    if (dId > 0) {
      if (dSel) dSel.value = String(dId);
    } else if (record.driver_manual_name) {
      _poaManualDriverMode = true;
      if (mf) mf.style.display = "block";
      if (dSel) dSel.disabled = true;
      if (btn) { btn.style.background = "#dbeafe"; btn.style.borderColor = "#3b82f6"; }
      const mn = document.getElementById("poaManualDriverName");
      const md = document.getElementById("poaManualDriverDocs");
      if (mn) mn.value = record.driver_manual_name || "";
      if (md) md.value = record.driver_manual_docs || "";
    }
  }
  // Update modal title
  const title = document.querySelector("#createPoAModal h4");
  if (title) {
    title.textContent = mode === "edit" ? "Редактировать доверенность" :
                        mode === "copy" ? "Копировать доверенность" : "Создать доверенность";
  }
  const saveBtn = document.querySelector("#createPoAModal button[onclick='savePoARecord()']");
  if (saveBtn) saveBtn.textContent = mode === "edit" ? "Сохранить изменения" : "Сохранить";
  const modal = document.getElementById("createPoAModal");
  if (modal) { modal.classList.remove("hidden"); modal.style.display = ""; }
}

async function openCreatePoAModal() { await _openPoAModal("create", null); }
async function openEditPoAModal(id) { await _openPoAModal("edit", _poaRecords.find(r => r.id === id)); }
async function openCopyPoAModal(id)  { await _openPoAModal("copy", _poaRecords.find(r => r.id === id)); }

window.openEditPoAModal = openEditPoAModal;
window.openCopyPoAModal = openCopyPoAModal;

let _poaManualDriverMode = false;
let _poaModalMode = "create"; // "create" | "edit" | "copy"
let _poaEditingId = null;

function togglePoAManualDriver() {
  _poaManualDriverMode = !_poaManualDriverMode;
  const mf = document.getElementById("poaManualDriverFields");
  const dSel = document.getElementById("poaCreateDriver");
  const btn = document.getElementById("poaManualDriverBtn");
  if (_poaManualDriverMode) {
    if (mf) { mf.style.display = "block"; }
    if (dSel) { dSel.disabled = true; dSel.value = ""; }
    if (btn) { btn.style.background = "#dbeafe"; btn.style.borderColor = "#3b82f6"; }
  } else {
    if (mf) { mf.style.display = "none"; }
    if (dSel) { dSel.disabled = false; }
    if (btn) { btn.style.background = ""; btn.style.borderColor = ""; }
  }
}

window.togglePoAManualDriver = togglePoAManualDriver;

function closeCreatePoAModal() {
  _poaManualDriverMode = false;
  const modal = document.getElementById("createPoAModal");
  if (modal) { modal.classList.add("hidden"); modal.style.display = "none"; }
}

async function savePoARecord() {
  const leId = parseInt(document.getElementById("poaCreateLegal")?.value || "0");
  const cId  = parseInt(document.getElementById("poaCreateContractor")?.value || "0");
  const dId  = _poaManualDriverMode ? 0 : parseInt(document.getElementById("poaCreateDriver")?.value || "0");
  const manualName = _poaManualDriverMode ? (document.getElementById("poaManualDriverName")?.value.trim() || "") : "";
  const manualDocs = _poaManualDriverMode ? (document.getElementById("poaManualDriverDocs")?.value.trim() || "") : "";
  const info = document.getElementById("poaCreateInfo");
  if (!leId || !cId) {
    if (info) { info.textContent = "Выберите юр. лицо и контрагента"; info.style.color = "#b91c1c"; }
    return;
  }
  if (!_poaManualDriverMode && !dId) {
    if (info) { info.textContent = "Выберите водителя или введите вручную"; info.style.color = "#b91c1c"; }
    return;
  }
  if (_poaManualDriverMode && !manualName) {
    if (info) { info.textContent = "Введите ФИО водителя"; info.style.color = "#b91c1c"; }
    return;
  }
  if (info) { info.textContent = "Сохранение..."; info.style.color = ""; }
  const payload = JSON.stringify({ legal_entity_id: leId, contractor_id: cId, driver_id: dId,
    driver_manual_name: manualName, driver_manual_docs: manualDocs });
  let res;
  if (_poaModalMode === "edit" && _poaEditingId) {
    res = await fetch(`/api/supply-poa-records/${_poaEditingId}`, {
      method: "PATCH", headers: jsonHeaders(), body: payload
    }).catch(() => null);
  } else {
    res = await fetch("/api/supply-poa-records", {
      method: "POST", headers: jsonHeaders(), body: payload
    }).catch(() => null);
  }
  if (!res || !res.ok) {
    const e = await res?.json().catch(()=>({})) || {};
    if (info) { info.textContent = e.detail || "Ошибка"; info.style.color = "#b91c1c"; }
    return;
  }
  closeCreatePoAModal();
  await loadPoARecords();
}

window.openCreatePoAModal = openCreatePoAModal;
window.closeCreatePoAModal = closeCreatePoAModal;
window.savePoARecord = savePoARecord;
window.renderPoATable = renderPoATable;
window.printPoARecord = printPoARecord;
window.deletePoARecord = deletePoARecord;
window.loadPoARecords = loadPoARecords;

async function printTTN(supplyId) {
  // Open PDF generated server-side (LibreOffice converts DOCX→PDF, browser prints it)
  const url = `/api/supplies/${supplyId}/ttn.pdf`;
  const win = window.open(url, "_blank");
  if (!win) alert("Разрешите всплывающие окна для печати");
}

async function _printTTN_html_fallback(supplyId) {
  const item = suppliesState.items.find((x) => x.supply_id === supplyId || x.supply_id === Number(supplyId));
  if (!item) return;

  if (!_supplyLegalEntitiesCache.length) await loadSupplyLegalEntities();
  const supplierShort = item.supplier_name || "";
  const le = _supplyLegalEntitiesCache.find((e) => e.short_name === supplierShort) || _supplyLegalEntitiesCache[0] || {};
  const orgLine = [le.full_name || supplierShort, le.requisites].filter(Boolean).join(", ");

  const now = new Date();
  const dd = String(now.getDate()).padStart(2,"0"), mm = String(now.getMonth()+1).padStart(2,"0"), yyyy = now.getFullYear();
  const dateDisp = `${dd}.${mm}.${yyyy}`;
  const supplyDate = item.supply_date
    ? new Date(item.supply_date).toLocaleDateString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric"})
    : dateDisp;
  const wh = (item.warehouse_name || "").trim();
  const supplyId_ = String(item.supply_id || "");
  const driverName = item.driver_name || "";
  const VAT_RATE = 0.22;
  const fmt2 = (n) => Number(n).toLocaleString("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2});

  let goodsList = [];
  try {
    const gr = await fetch(`/api/supplies/${supplyId_}/goods`).catch(()=>null);
    if (gr && gr.ok) goodsList = await gr.json().catch(()=>[]);
  } catch(_){}

  let nmPrices = {};
  try {
    const pr = await fetch(`/api/supplies/${supplyId_}/nm-prices`).catch(()=>null);
    if (pr && pr.ok) { const pd = await pr.json().catch(()=>({})); nmPrices = pd.prices||{}; }
  } catch(_){}

  const qtyTotal = goodsList.reduce((s,g)=>s+(parseInt(g.quantity)||0),0);
  let totalExcl=0, totalVat=0, totalIncl=0;

  const goodsRows = goodsList.map((g, i) => {
    const qty = parseInt(g.quantity)||0;
    const nm = String(g.nm_id||"");
    const priceIncl = (nm && nmPrices[nm]) ? parseFloat(nmPrices[nm]) : null;
    const priceExcl = priceIncl!=null ? priceIncl/(1+VAT_RATE) : null;
    const amtExcl   = priceExcl!=null ? priceExcl*qty : null;
    const vatAmt    = amtExcl!=null ? amtExcl*VAT_RATE : null;
    const amtIncl   = amtExcl!=null ? amtExcl+vatAmt : null;
    if (amtExcl!=null){totalExcl+=amtExcl;totalVat+=vatAmt;totalIncl+=amtIncl;}
    const name = esc(g.product_name||g.vendor_code||"Товар");
    return `<tr>
      <td class="c">${i+1}</td>
      <td>${name}</td>
      <td class="c">—</td><td class="c">шт.</td><td class="c">—</td><td class="c">—</td>
      <td class="c">1</td>
      <td class="c">${qty}</td>
      <td class="c">—</td>
      <td class="c">${qty}</td>
      <td class="c">${priceExcl!=null?fmt2(priceExcl):"—"}</td>
      <td class="c">${amtExcl!=null?fmt2(amtExcl):"—"}</td>
      <td class="c">22%</td>
      <td class="c">${vatAmt!=null?fmt2(vatAmt):"—"}</td>
      <td class="c">${amtIncl!=null?fmt2(amtIncl):"—"}</td>
    </tr>`;
  }).join("");

  const totalExclFmt = totalExcl>0?fmt2(totalExcl):"—";
  const totalVatFmt  = totalVat>0?fmt2(totalVat):"—";
  const totalInclFmt = totalIncl>0?fmt2(totalIncl):"—";
  const amtWords = totalIncl>0 ? _rublesInWords(Math.round(totalIncl)) : "—";

  // Exact column widths from torg12_tpl.docx (twips → %)
  // Total: 15709 tw. Cols: 567,3121,737,737,737,737,737,737,737,737,1134,1418,737,1418,1418
  const CW = [3.6,19.9,4.7,4.7,4.7,4.7,4.7,4.7,4.7,4.7,7.2,9.0,4.7,9.0,9.0].map(p=>p+"%");

  const colgroupHtml = CW.map(w=>`<col style="width:${w}">`).join("");

  const html = `<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"/>
<title>ТТН № ${supplyId_}</title>
<style>
@page{size:A4 landscape;margin:10mm 8mm}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Times New Roman",serif;font-size:7.5pt;color:#000}
/* Header table (org info + codes) */
.t-hdr{width:100%;border-collapse:collapse;margin-bottom:2pt;font-size:7.5pt}
.t-hdr td{border:none;padding:1.5pt 2pt;vertical-align:top}
.t-hdr .td-org{width:58%;border-bottom:1px solid #555}
.t-hdr .td-codes{width:42%;vertical-align:top}
.t-codes{width:100%;border-collapse:collapse;font-size:7pt;margin-top:1pt}
.t-codes th,.t-codes td{border:1px solid #000;padding:1pt 3pt}
.t-codes th{text-align:center;background:#f0f0f0}
/* Title table */
.t-title{width:100%;border-collapse:collapse;margin:3pt 0 2pt;font-size:8pt}
.t-title td,.t-title th{border:1px solid #000;padding:1.5pt 3pt;text-align:center}
.t-title .title-cell{font-size:12pt;font-weight:bold;border:none;text-align:center;padding:3pt 0}
/* Main goods table */
.t-goods{width:100%;border-collapse:collapse;font-size:6.5pt;table-layout:fixed}
.t-goods th,.t-goods td{border:1px solid #000;padding:1pt 1.5pt;vertical-align:middle;overflow:hidden;word-break:break-word}
.t-goods th{text-align:center;background:#f5f5f5;line-height:1.2}
.c{text-align:center}.r{text-align:right}
.fw{font-weight:bold}
/* Footer */
.footer-line{margin-top:4pt;font-size:7pt;border-top:1px solid #000;padding-top:2pt}
.sig-wrap{display:flex;justify-content:space-between;margin-top:6pt;font-size:7pt}
.sig-block{width:49%}
.sig-row{margin-top:5pt}
.sig-row span{display:inline-block;min-width:140pt;border-bottom:1px solid #000}
.sig-label{font-size:6pt;color:#555;margin-top:1pt}
</style></head><body>

<!-- HEADER: org info left, codes right -->
<table class="t-hdr"><tr>
  <td class="td-org">
    <div><b>Организация–грузоотправитель:</b> ООО «РВБ», Ногинский район, г.Электросталь, посёлок Случайный, д.5</div>
    <div style="font-size:6pt;color:#555">организация–грузоотправитель, адрес, номер телефона, банковские реквизиты / структурное подразделение</div>
  </td>
  <td class="td-codes" rowspan="5">
    <div style="text-align:right;font-size:7pt">Унифицированная форма № ТОРГ-12<br/>Утверждена постановлением Госкомстата России от 25.12.98 №132</div>
    <table class="t-codes" style="margin-top:3pt">
      <tr><th colspan="2">Код</th></tr>
      <tr><td>Форма по ОКУД</td><td class="c">0330212</td></tr>
      <tr><td>по ОКПО</td><td class="c"></td></tr>
      <tr><td>Вид деятельности по ОКДП</td><td class="c"></td></tr>
    </table>
  </td>
</tr><tr>
  <td class="td-org" style="padding-top:3pt">
    <div><b>Грузоотправитель:</b> ООО «РВБ», Ногинский район, г.Электросталь, посёлок Случайный, д.5</div>
    <div style="font-size:6pt;color:#555">наименование организации, адрес, номер телефона, банковские реквизиты</div>
  </td>
</tr><tr>
  <td class="td-org" style="padding-top:3pt">
    <div><b>Поставщик:</b> ${esc(orgLine||"—")}</div>
    <div style="font-size:6pt;color:#555">наименование организации, адрес, номер телефона, банковские реквизиты</div>
  </td>
</tr><tr>
  <td class="td-org" style="padding-top:3pt">
    <div><b>Плательщик:</b> ${esc(orgLine||"—")}</div>
    <div style="font-size:6pt;color:#555">наименование организации, адрес, номер телефона, банковские реквизиты</div>
  </td>
</tr><tr>
  <td class="td-org" style="padding-top:3pt">
    <div><b>Основание:</b> Заказ № ${supplyId_}</div>
    <div style="margin-top:2pt;font-size:6.5pt;display:flex;gap:20pt">
      <span>Транспортная накладная № _______ от _______</span>
      <span>Вид операции: _______</span>
    </div>
  </td>
</tr></table>

<!-- TITLE -->
<table class="t-title">
  <tr>
    <td class="title-cell" colspan="2">ТОВАРНАЯ НАКЛАДНАЯ &nbsp; №&nbsp;${supplyId_}</td>
  </tr>
  <tr>
    <th style="width:50%">Номер документа</th>
    <th style="width:50%">Дата составления</th>
  </tr>
  <tr>
    <td>${supplyId_}</td>
    <td>${supplyDate}</td>
  </tr>
</table>

<!-- GOODS TABLE -->
<table class="t-goods"><colgroup>${colgroupHtml}</colgroup>
  <thead>
    <tr>
      <th rowspan="3">Номер<br/>по<br/>порядку</th>
      <th rowspan="3">Товар (наименование, характеристика, сорт, артикул товара)</th>
      <th rowspan="3">код</th>
      <th colspan="2">Единица измерения</th>
      <th rowspan="3">Вид<br/>упаковки</th>
      <th colspan="2">Количество</th>
      <th rowspan="3">Масса<br/>брутто</th>
      <th rowspan="3">Кол-во<br/>(масса<br/>нетто)</th>
      <th rowspan="3">Цена,<br/>руб.,&nbsp;коп.</th>
      <th rowspan="3">Сумма без<br/>учёта НДС,<br/>руб.,&nbsp;коп.</th>
      <th colspan="2">НДС</th>
      <th rowspan="3">Сумма с<br/>учётом НДС,<br/>руб.,&nbsp;коп.</th>
    </tr>
    <tr>
      <th>наиме-<br/>нование</th><th>код по ОКЕИ</th>
      <th>в одном<br/>месте</th><th>мест,<br/>штук</th>
      <th>ставка,&nbsp;%</th><th>сумма,<br/>руб.,&nbsp;коп.</th>
    </tr>
    <tr><th>4</th><th>5</th><th>7</th><th>8</th><th>13</th><th>14</th></tr>
    <tr><td class="c">1</td><td class="c">2</td><td class="c">3</td><td class="c">4</td><td class="c">5</td><td class="c">6</td><td class="c">7</td><td class="c">8</td><td class="c">9</td><td class="c">10</td><td class="c">11</td><td class="c">12</td><td class="c">13</td><td class="c">14</td><td class="c">15</td></tr>
  </thead>
  <tbody>
    ${goodsRows||`<tr><td colspan="15" class="c">—</td></tr>`}
    <tr class="fw">
      <td colspan="7" class="r" style="font-weight:bold">Всего по накладной</td>
      <td class="c fw">${qtyTotal}</td>
      <td class="c">—</td>
      <td class="c fw">${qtyTotal}</td>
      <td class="c">—</td>
      <td class="c fw">${totalExclFmt}</td>
      <td class="c">×</td>
      <td class="c fw">${totalVatFmt}</td>
      <td class="c fw">${totalInclFmt}</td>
    </tr>
  </tbody>
</table>

<div class="footer-line">
  Товарная накладная имеет приложение на _____ листах и содержит _____ порядковых номеров записей.<br/>
  Всего отпущено на сумму: <b>${amtWords}</b>
</div>

<div class="sig-wrap">
  <div class="sig-block">
    <div class="sig-row">Отпуск разрешил &nbsp;<span>&nbsp;${esc(supplierShort)}</span></div>
    <div class="sig-label">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; подпись &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; расшифровка подписи</div>
    <div class="sig-row">Главный бухгалтер &nbsp;<span>&nbsp;${esc(supplierShort)}</span></div>
    <div class="sig-label">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; подпись &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; расшифровка подписи</div>
    <div class="sig-row">Отпуск груза произвел &nbsp;<span>&nbsp;${esc(supplierShort)}</span></div>
    <div class="sig-label">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; подпись &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; расшифровка подписи</div>
  </div>
  <div class="sig-block">
    <div class="sig-row">Груз принял &nbsp;<span>&nbsp;${esc(driverName)}</span></div>
    <div class="sig-label">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; подпись &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; расшифровка подписи</div>
    <div class="sig-row">Груз получил грузополучатель &nbsp;<span>&nbsp;</span></div>
    <div class="sig-label">должность &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; подпись &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; расшифровка подписи</div>
    <div style="margin-top:8pt">«&nbsp;&nbsp;&nbsp;»&nbsp;______________&nbsp;${yyyy}&nbsp;г.</div>
  </div>
</div>
</body></html>`;

  const win = window.open("","_blank","width=1100,height=780");
  if (!win){alert("Разрешите всплывающие окна для печати");return;}
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(()=>win.print(), 500);
}

window.downloadPackingList = downloadPackingList;
window.downloadPoA = downloadPoA;
window.downloadTTN = downloadTTN;
window.printTTN = printTTN;
window.downloadSupplyBarcode = downloadSupplyBarcode;
window.initSuppliesColumnResizer = initSuppliesColumnResizer;
window.initOzonSuppliesColumnResizer = initOzonSuppliesColumnResizer;
window.toggleSuppliesFilter = toggleSuppliesFilter;
window.toggleSuppliesDatePanel = toggleSuppliesDatePanel;
window.applySuppliesDateFilter = applySuppliesDateFilter;
window.clearSuppliesDateFilter = clearSuppliesDateFilter;
window._calPrevMonth = _calPrevMonth;
window._calNextMonth = _calNextMonth;
window._calPickDate = _calPickDate;
window._calHover = _calHover;
window._calClearHover = _calClearHover;
window.copySupplyDetails = copySupplyDetails;
window.openSupplyDetailsModal = openSupplyDetailsModal;
window.closeSupplyDetailsModal = closeSupplyDetailsModal;
window.saveSupplyManualFields = saveSupplyManualFields;
window.showSuppliesSettingsTab = function(tab) {
  const permissions = getPermissions();
  // Redirect manager (no settings access) away from sources tab to drivers
  if (tab === "sources" && !permissions.can_view_settings) tab = "drivers";
  document.querySelectorAll("#section-supplies-settings .settings-tab-btn").forEach((b) => b.classList.remove("active"));
  document.getElementById(`supplies-settings-tab-${tab}`)?.classList.add("active");
  document.querySelectorAll("[id^='supplies-settings-pane-']").forEach((p) => { p.classList.add("hidden"); p.style.display = "none"; });
  const pane = document.getElementById(`supplies-settings-pane-${tab}`);
  if (pane) { pane.classList.remove("hidden"); pane.style.display = ""; }
};
