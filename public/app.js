const state = {
  me: null,
  csrf: "",
  permissions: {},
  users: [],
  records: [],
  accountSummaries: [],
  customerOptions: [],
  currentOrderDefaults: null,
  currentEntity: "pipeline",
  dashboard: null,
  sales: null,
  forecast: null,
  forecastRounds: null,
  monthlySalesFcst: null,
  monthlySalesFcstTab: "current",
  monthlySalesFcstAsOfRound: "",
  monthlySalesFcstExpanded: new Set(["confirmed", "scheduled", "pipeline", "undecided"]),
  monthlySalesFcstSelected: null,
  forecastRoundSelected: null,
  forecastRoundDirty: false,
  forecastDetailSelectedGroup: null,
  forecastDetailExpandedId: null,
  editingForecastDetail: null,
  mapData: null,
  worldTopology: null,
  worldShapes: null,
  mapSelectedId: null,
  recordCountryFilter: null,
  forecastCountryFilter: null,
  salesCountryFilter: null,
  exchangeRates: null,
  erpStatus: null,
  forcePasswordChange: false,
  editingPayload: {},
  journeyAccountId: null,
  editingForecastItem: null,
  pendingForecastEntryAfterCycle: false,
  expandedTaskGroups: new Set(),
  taskSort: { key: "updatedAt", direction: "desc" },
};

const LAST_VIEW_STORAGE_KEY = "medpark-global-maps:last-view";

const recordConfig = {
  goal: {
    title: "목표·중간점검",
    eyebrow: "TARGET & MID-TERM REVIEW",
    description: "최초 목표, 중간 점검일, 실적과 수정 목표일을 이력과 함께 관리합니다.",
    statuses: ["active", "on_track", "at_risk", "achieved", "closed"],
  },
  pipeline: {
    title: "파이프라인",
    eyebrow: "GLOBAL OPPORTUNITY PIPELINE",
    description: "기회 금액, 단계, 확률과 다음 액션을 담당자별로 관리합니다.",
    statuses: ["discovery", "qualified", "proposal", "negotiation", "won", "lost"],
  },
  account: {
    title: "거래처 마스터",
    eyebrow: "ERP ACCOUNT LEDGER · CUSTOMER INTELLIGENCE",
    description: "ERP 원본정보와 담당자 입력정보를 분리해 거래처 전 과정을 관리합니다.",
    statuses: ["active", "prospect", "hold", "closed"],
  },
  activity: {
    title: "영업 활동",
    eyebrow: "CUSTOMER CONTACT & FOLLOW-UP",
    description: "WhatsApp, 이메일, 통화, 화상미팅과 전시회 후속조치를 거래처별로 관리합니다.",
    statuses: ["planned", "in_progress", "follow_up", "done", "cancelled"],
  },
  order: {
    title: "수주·출고 진행",
    eyebrow: "PO TO SHIPMENT CONTROL",
    description: "PO 접수부터 PI, 컨펌, 수금, 선적서류와 출고까지 목표일을 관리합니다.",
    statuses: ["po_received", "pi_sent", "pi_confirmed", "payment_received", "shipping_docs", "shipped", "on_hold", "cancelled"],
  },
  cash_plan: {
    title: "자금계획",
    eyebrow: "MONTHLY CASH IN · OUT CONTROL",
    description: "수금·지출의 계획, 조정, 실행, 이월과 월말 예상잔액을 일자별로 관리합니다.",
    statuses: ["planned", "confirmed", "executed", "carried_over", "cancelled"],
  },
  receivable: {
    title: "미수금·채권",
    eyebrow: "ACCOUNTS RECEIVABLE & COLLECTION CONTROL",
    description: "거래처별 후불조건, 회차별 예정·실제입금, 잔액, 연체와 회수계획을 관리합니다.",
    statuses: ["current", "due", "overdue", "promise", "partial_paid", "paid", "hold", "legal"],
  },
  task: {
    title: "주요 업무",
    eyebrow: "PRIORITY ACTION BOARD",
    description: "담당 업무의 기한과 진행 상태를 관리합니다.",
    statuses: ["todo", "in_progress", "blocked", "done"],
  },
  agenda: {
    title: "일정·아젠다",
    eyebrow: "SCHEDULE & AGENDA",
    description: "회의, 출장, 보고 일정과 핵심 아젠다를 관리합니다.",
    statuses: ["scheduled", "in_progress", "completed", "cancelled"],
  },
  promotion: {
    title: "프로모션",
    eyebrow: "GLOBAL PROMOTION CONTROL",
    description: "국가·거래처별 프로모션 예산과 실행 상태를 관리합니다.",
    statuses: ["planned", "approved", "running", "completed", "cancelled"],
  },
  transport: {
    title: "운송 정보",
    eyebrow: "LOGISTICS & DELIVERY",
    description: "거래처별 운송조건, 포워더와 리드타임 정보를 관리합니다.",
    statuses: ["active", "planned", "hold", "closed"],
  },
};

const statusLabels = {
  active: "활성", prospect: "잠재", hold: "보류", closed: "종료",
  discovery: "발굴", qualified: "검증", proposal: "제안", negotiation: "협상", won: "수주", lost: "실주",
  todo: "예정", in_progress: "진행 중", blocked: "차단", done: "완료",
  not_started: "미착수", internal_work: "내부작업", external_wait: "외부대기",
  cooperation_wait: "협조대기", hold: "보류",
  scheduled: "예정", completed: "완료", cancelled: "취소",
  planned: "계획", approved: "승인", running: "실행 중",
  confirmed: "확정 예정", executed: "실행 완료", carried_over: "차월 이월",
  current: "정상채권", due: "만기 도래", overdue: "연체", promise: "입금 약속",
  partial_paid: "부분 수금", paid: "회수 완료", legal: "법무 검토",
  pending: "승인 대기", disabled: "사용 중지", viewer: "조회", editor: "편집", manager: "매니저", admin: "관리자",
  on_track: "정상", at_risk: "주의", achieved: "달성",
  follow_up: "후속조치", po_received: "PO 접수", pi_sent: "PI 발송", pi_confirmed: "PI 컨펌",
  payment_received: "수금 완료", shipping_docs: "선적서류 준비", shipped: "출고 완료", on_hold: "보류",
};

const viewTitles = {
  overview: ["GLOBAL BUSINESS CONTROL TOWER", "종합 현황"],
  daily: ["DAILY SALES & OPERATIONS HUDDLE", "오늘·아침회의"],
  forecast: ["FORECAST CONTROL · 1ST / 2ND / 3RD CLOSE", "월별 FCST"],
  forecast_rounds: ["FORECAST ROUND · INPUT / REVIEW / CLOSE", "FCST 차수 업무관리"],
  monthly_sales_fcst: ["MONTHLY SALES · FORECAST · CARRYOVER", "월별 매출 FCST"],
  sales: ["AMARANTH 10 · EXPORT ONLY", "해외 월별 매출"],
  users: ["ACCESS CONTROL", "사용자 관리"],
  history: ["IMMUTABLE AUDIT TRAIL", "변경 이력"],
};

const activityLabels = {
  whatsapp: "WhatsApp", email_check: "이메일 확인", email_send: "이메일 발송",
  phone: "유선 통화", video_meeting: "화상 미팅", exhibition: "전시회", visit: "대면 방문", other: "기타",
};

const orderSteps = [
  ["po_received", "PO 접수"], ["pi_sent", "PI 발송"], ["pi_confirmed", "PI 컨펌"],
  ["payment_received", "수금"], ["shipping_docs", "선적서류"], ["shipped", "출고"],
];

const segmentLabels = {
  all: "전체 해외",
  dental: "덴탈",
  medical: "메디컬",
  aesthetic: "에스테틱",
  unclassified: "미분류",
};

const forecastStageLabels = {
  sales_activity: "일반 영업추진",
  pi_received: "PI 수령",
  payment_received: "수금 완료",
};

const forecastStageDefaults = { sales_activity: 20, pi_received: 60, payment_received: 95 };

const flowTypeLabels = { cash_in: "수금", cash_out: "지출", opening_liquid: "기초 유동자금", fixed_fund: "고정자금" };
const riskLevelLabels = { normal: "정상", watch: "주의", p1: "P1 즉시회수", legal: "법무검토" };
const cashCategoryLabels = {
  overseas_dental_collection: "해외 덴탈 수금", overseas_medical_collection: "해외 메디컬 수금",
  overseas_aesthetic_collection: "해외 에스테틱 수금", exhibition: "해외전시회", transport: "운반비",
  travel: "여비교통비", promotion: "판매장려금·프로모션", product_purchase: "상품구입",
  regulatory: "인허가", fee: "지급수수료", other_income: "기타수입", other_expense: "기타비용",
};

const recordTextPayloadFields = [
  "business_unit", "company_name", "goal_type", "target_unit", "original_target_date", "mid_review_date", "revised_target_date",
  "review_result", "activity_type", "contact_person", "activity_at", "next_action_date", "next_action",
  "po_received_date", "pi_sent_date", "pi_confirmed_date", "payment_received_date", "shipping_docs_date",
  "shipped_date", "next_target_date", "document_no", "erp_partner_name", "erp_partner_code", "main_items",
  "current_price_condition", "ar_condition_label", "ar_terms_notes", "flow_type", "plan_actual_type",
  "execution_category", "transaction_type", "plan_date", "card_payment_date", "execution_date", "maturity_date",
  "counterparty", "payment_condition", "cost_nature", "account_subject", "cash_notes", "invoice_no", "shipment_no",
  "ship_date", "invoice_date", "payment_condition_label", "risk_level", "advance_received_date", "receipt_1_date",
  "receipt_2_date", "receipt_3_date", "receipt_4_date", "promise_date", "next_collection_date", "collection_status",
  "recovery_plan", "promotion_id", "item_name", "baseline_price_condition", "promotion_terms", "start_date", "end_date",
  "target_month", "target_ship_date", "forecast_stage", "completed_at", "proposal_target_date", "proposal_actual_date",
  "approval_target_date", "approval_actual_date", "offer_target_date", "offer_actual_date", "order_target_date",
  "order_actual_date", "promotion_payment_target_date", "promotion_payment_actual_date",
  "promotion_shipment_target_date", "promotion_shipment_actual_date",
  "customer_terms_mode", "order_terms_change_reason", "order_payment_method", "order_collection_basis",
  "order_product_name", "order_moq_basis", "order_moq_exception_reason", "order_moq_exception_approver",
  "address", "established_date", "first_transaction_date", "representative_name",
  "account_contact_name", "contact_phone", "contact_email", "account_notes",
];
const recordNumericPayloadFields = [
  "target_value", "actual_value", "ar_advance_ratio", "ar_installment_1_days", "ar_installment_1_ratio",
  "ar_installment_2_days", "ar_installment_2_ratio", "ar_installment_3_days", "ar_installment_3_ratio",
  "ar_installment_4_days", "ar_installment_4_ratio", "exchange_rate", "adjustment_rate", "payment_rate",
  "actual_foreign_amount", "actual_krw_amount", "receivable_exchange_rate", "advance_ratio",
  "installment_1_days", "installment_1_ratio", "installment_2_days", "installment_2_ratio",
  "installment_3_days", "installment_3_ratio", "installment_4_days", "installment_4_ratio",
  "advance_received_amount", "receipt_1_amount", "receipt_2_amount", "receipt_3_amount", "receipt_4_amount",
  "promise_amount", "baseline_unit_price", "promotion_unit_price", "target_units", "achieved_units",
  "budget_amount", "achieved_amount", "forecast_confidence",
  "order_advance_ratio", "order_deferred_days", "order_agreed_unit_price", "order_moq",
  "order_paid_quantity", "order_foc_quantity",
];
const recordBooleanPayloadFields = [
  "previous_month_carryover", "current_month_carryover", "intentional_carryover", "split_payment",
  "shipment_hold", "legal_review",
  "representative_approval", "forecast_included",
];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function syncSalesMonthOptions(year) {
  const node = $("#salesMonth");
  if (!node) return;
  node.innerHTML = '<option value="all">연간 전체</option>' + Array.from({ length: 12 }, (_, index) => {
    const month = String(index + 1).padStart(2, "0");
    return `<option value="${year}-${month}">${index + 1}월</option>`;
  }).join("");
}

function operationalForecastMonth() {
  const now = new Date();
  const target = new Date(now.getFullYear(), now.getMonth() + (now.getDate() >= 25 ? 1 : 0), 1);
  return `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, "0")}`;
}

function forecastApiPath() {
  const month = $("#forecastMonth")?.value || operationalForecastMonth();
  const round = $("#forecastRound")?.value || "latest";
  return `/api/forecast?month=${encodeURIComponent(month)}&round=${encodeURIComponent(round)}`;
}

function forecastRoundOverviewApiPath() {
  const month = $("#forecastRoundMonth")?.value || "2026-08";
  return `/api/forecast-rounds/overview?month=${encodeURIComponent(month)}`;
}

function salesApiPath() {
  const year = $("#salesYear")?.value || new Date().getFullYear();
  const segment = $("#salesSegment")?.value || "all";
  const month = $("#salesMonth")?.value || "all";
  const country = state.salesCountryFilter?.map_id || "";
  return `/api/sales?year=${encodeURIComponent(year)}&segment=${encodeURIComponent(segment)}&month=${encodeURIComponent(month)}&country=${encodeURIComponent(country)}`;
}

function mapApiPath() {
  const month = $("#mapMonth")?.value || operationalForecastMonth();
  const segment = $("#mapSegment")?.value || "all";
  return `/api/map?month=${encodeURIComponent(month)}&segment=${encodeURIComponent(segment)}`;
}

async function loadWorldTopology() {
  if (state.worldTopology) return state.worldTopology;
  const response = await fetch("/assets/countries-110m.json", { credentials: "same-origin" });
  if (!response.ok) throw new Error("세계지도 자료를 불러오지 못했습니다.");
  state.worldTopology = await response.json();
  return state.worldTopology;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message, type = "success") {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show ${type === "error" ? "error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 4200);
}

function setActionMessage(selector, message = "", type = "success") {
  const node = $(selector);
  if (!node) return;
  node.textContent = message;
  node.className = `action-message${message ? ` show ${type === "error" ? "error" : "success"}` : ""}`;
}

async function api(path, options = {}, allowCsrfRetry = true, initializationRetries = 4) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  let body = options.body;
  if (body && typeof body !== "string") {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && state.csrf && !path.includes("/auth/login") && !path.includes("/auth/register")) {
    headers["X-CSRF-Token"] = state.csrf;
  }
  let response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...options, method, headers, body });
  } catch (_error) {
    throw new Error("네트워크 연결이 불안정합니다. 연결 상태를 확인한 뒤 다시 눌러 주세요.");
  }
  let data = {};
  try { data = await response.json(); } catch { data = {}; }
  if (response.status === 403 && data.code === "CSRF_EXPIRED" && allowCsrfRetry && state.me) {
    try {
      const meResponse = await fetch("/api/auth/me", { credentials: "same-origin", headers: { Accept: "application/json" } });
      const me = await meResponse.json();
      if (meResponse.ok && me.authenticated) {
        state.me = me.user;
        state.csrf = me.csrf_token;
        state.permissions = me.permissions;
        return api(path, options, false, initializationRetries);
      }
    } catch (_error) { /* fall through to the original error */ }
  }
  if (
    response.status === 503
    && data.code === "DATABASE_INITIALIZING"
    && ["GET", "HEAD"].includes(method)
    && initializationRetries > 0
  ) {
    await new Promise(resolve => window.setTimeout(resolve, 1500));
    return api(path, options, allowCsrfRetry, initializationRetries - 1);
  }
  if (response.status === 401 && !path.includes("/auth/login")) {
    showAuth("login");
  }
  if (response.status === 428 && data.password_change_required) {
    openPasswordDialog(true);
  }
  if (!response.ok) {
    const error = new Error(data.error || `요청 실패 (${response.status})`);
    error.detail = data.detail;
    error.status = response.status;
    error.code = data.code;
    error.data = data;
    throw error;
  }
  return data;
}

function formatNumber(value, maximumFractionDigits = 0) {
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits }).format(Number(value || 0));
}

function formatMoney(value, currency = "KRW") {
  const amount = Number(value || 0);
  if (currency === "KRW") return `₩${formatNumber(amount)}`;
  return `${escapeHtml(currency)} ${formatNumber(amount, 2)}`;
}

function compactMoney(value, currency = "KRW") {
  return formatMoney(value, currency);
}

function formatDate(value, withTime = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  return new Intl.DateTimeFormat("ko-KR", withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(date);
}

function badge(value) {
  const text = statusLabels[value] || value || "—";
  const cls = ["active", "done", "completed", "won", "achieved", "on_track", "shipped", "payment_received", "executed", "paid", "current"].includes(value) ? "success" :
    ["pending", "proposal", "in_progress", "planned", "scheduled", "follow_up", "po_received", "pi_sent", "pi_confirmed", "shipping_docs", "confirmed", "due", "promise", "partial_paid", "carried_over"].includes(value) ? "warning" :
    ["disabled", "lost", "cancelled", "blocked", "at_risk", "on_hold", "overdue", "hold", "legal"].includes(value) ? "danger" :
    ["negotiation", "qualified", "approved", "running"].includes(value) ? "info" : "";
  return `<span class="badge ${cls}">${escapeHtml(text)}</span>`;
}

function selectAuthTab(tab = "login") {
  $$(".auth-tab").forEach(item => item.classList.toggle("active", item.dataset.authTab === tab));
  const login = tab === "login";
  $("#loginForm").classList.toggle("hidden", !login);
  $("#registerForm").classList.toggle("hidden", login);
  $("#loginError").textContent = "";
  $("#registerMessage").textContent = "";
}

function showAuth(tab = "login") {
  state.me = null;
  state.csrf = "";
  state.permissions = {};
  selectAuthTab(tab);
  $("#appShell").classList.add("hidden");
  $("#authScreen").classList.remove("hidden");
}

function showApp() {
  const authenticated = Boolean(state.me);
  $("#authScreen").classList.add("hidden");
  $("#appShell").classList.remove("hidden");
  $("#userName").textContent = authenticated ? state.me.display_name : "공개 조회";
  $("#userRole").textContent = authenticated ? state.me.role.toUpperCase() : "READ ONLY";
  $("#userInitial").textContent = authenticated ? state.me.display_name.slice(0, 1).toUpperCase() : "공";
  $("#todayLabel").textContent = new Intl.DateTimeFormat("ko-KR", { dateStyle: "long" }).format(new Date());
  $$(".permission-edit").forEach(node => node.classList.toggle("hidden", !state.permissions.can_edit));
  $$(".permission-sync").forEach(node => node.classList.toggle("hidden", !state.permissions.can_sync_erp));
  $$(".permission-manage").forEach(node => node.classList.toggle("hidden", !authenticated || !["admin", "manager"].includes(state.me.role)));
  const userNav = $('.nav-item[data-view="users"]');
  userNav.classList.toggle("hidden", !authenticated || !["admin", "manager"].includes(state.me.role));
  $("#addUserBtn").classList.toggle("hidden", !authenticated || state.me.role !== "admin");
  $("#publicRegisterBtn").classList.toggle("hidden", authenticated);
  $("#manageLoginBtn").classList.toggle("hidden", authenticated);
  $("#passwordBtn").classList.toggle("hidden", !authenticated);
  $("#logoutBtn").classList.toggle("hidden", !authenticated);
}

async function initialize() {
  bindEvents();
  const currentYear = new Date().getFullYear();
  const yearSelect = $("#salesYear");
  for (let y = currentYear - 3; y <= currentYear + 1; y += 1) {
    yearSelect.insertAdjacentHTML("beforeend", `<option value="${y}" ${y === currentYear ? "selected" : ""}>${y}년</option>`);
  }
  syncSalesMonthOptions(currentYear);
  $("#forecastMonth").value = operationalForecastMonth();
  $("#mapMonth").value = operationalForecastMonth();
  $("#recordMonthFilter").value = `${currentYear}-${String(new Date().getMonth() + 1).padStart(2, "0")}`;
  try {
    const me = await api("/api/auth/me");
    state.me = me.authenticated ? me.user : null;
    state.csrf = me.authenticated ? me.csrf_token : "";
    state.permissions = me.authenticated ? me.permissions : {};
    if (!state.me) {
      showAuth("login");
      return;
    }
    showApp();
    await loadAll();
    restoreLastView();
    if (state.me?.must_change_password) openPasswordDialog(true);
  } catch (error) {
    state.me = null;
    state.csrf = "";
    state.permissions = {};
    showAuth("login");
    if (error.status && error.status !== 401) toast(error.message, "error");
  }
}

async function loadAll() {
  try {
    const userEndpoint = state.me ? (["admin", "manager"].includes(state.me.role) ? "/api/users" : "/api/users/directory") : null;
    const usersRequest = userEndpoint ? api(userEndpoint) : Promise.resolve({ users: [] });
    const customerOptionsRequest = state.me ? api("/api/customer-master/options").catch(() => ({ customers: [] })) : Promise.resolve({ customers: [] });
    const mapRequest = Promise.all([api(mapApiPath()), loadWorldTopology()])
      .then(([data]) => ({ data }))
      .catch(error => ({ error }));
    const forecastRoundsRequest = api(forecastRoundOverviewApiPath()).catch(error => ({ rounds: [], quality_notes: [], error: error.message }));
    const [dashboard, records, accountSummaries, customerOptions, users, erpStatus, sales, forecast, forecastRounds, exchangeRates, mapResult] = await Promise.all([
      api("/api/dashboard"),
      api("/api/records"),
      api("/api/accounts/summary"),
      customerOptionsRequest,
      usersRequest,
      api("/api/erp/status"),
      api(salesApiPath()),
      api(forecastApiPath()),
      forecastRoundsRequest,
      api("/api/exchange-rates"),
      mapRequest,
    ]);
    state.dashboard = dashboard;
    state.records = records.records;
    state.accountSummaries = accountSummaries.accounts || [];
    state.customerOptions = customerOptions.customers || [];
    state.users = users.users;
    state.erpStatus = erpStatus;
    state.sales = sales;
    state.forecast = forecast;
    state.forecastRounds = forecastRounds;
    state.forecastRoundSelected = forecastRounds.selected_round ?? forecastRounds.rounds?.[0]?.round_no ?? null;
    state.exchangeRates = exchangeRates;
    state.mapData = mapResult.data || null;
    if (window.MajorTasksUI) window.MajorTasksUI.init({ api, state, escapeHtml, formatDate, formatNumber, toast });
    renderOverview();
    renderForecast();
    renderForecastRounds();
    renderExchangeRates();
    renderDaily();
    renderSales();
    renderErpStatus();
    renderGlobalMap(mapResult.error);
    renderRecordView();
    if (state.me && ["admin", "manager"].includes(state.me.role)) renderUsers();
    await loadHistory();
  } catch (error) {
    toast(error.message, "error");
  }
}

function bindEvents() {
  $$(".auth-tab").forEach(button => button.addEventListener("click", () => selectAuthTab(button.dataset.authTab)));

  $("#loginForm").addEventListener("submit", handleLogin);
  $("#registerForm").addEventListener("submit", handleRegister);
  $("#manageLoginBtn").addEventListener("click", () => showAuth("login"));
  $("#publicRegisterBtn").addEventListener("click", () => showAuth("register"));
  $("#publicBackBtn").addEventListener("click", () => $("#loginForm input[name='username']").focus());
  $("#logoutBtn").addEventListener("click", handleLogout);
  $("#passwordBtn").addEventListener("click", () => openPasswordDialog(false));
  $("#passwordForm").addEventListener("submit", handlePasswordChange);
  $("#passwordDialog").addEventListener("cancel", event => {
    if (state.forcePasswordChange) event.preventDefault();
  });
  $("#menuToggle").addEventListener("click", () => $(".sidebar").classList.toggle("open"));

  $$(".nav-item").forEach(button => button.addEventListener("click", () => {
    if (state.forecastRoundDirty && button.dataset.view !== "forecast_rounds" && !window.confirm("저장하지 않은 FCST 차수 내용이 있습니다. 메뉴를 이동할까요?")) return;
    if (button.dataset.view !== "forecast_rounds") state.forecastRoundDirty = false;
    const reloadSales = button.dataset.view === "sales" && Boolean(state.salesCountryFilter);
    if (Object.hasOwn(recordConfig, button.dataset.view)) state.recordCountryFilter = null;
    if (button.dataset.view === "forecast") state.forecastCountryFilter = null;
    if (button.dataset.view === "sales") state.salesCountryFilter = null;
    switchView(button.dataset.view);
    if (reloadSales) loadSales();
  }));
  $$('[data-jump]').forEach(button => button.addEventListener("click", () => switchView(button.dataset.jump)));
  $$("[data-close-dialog]").forEach(button => button.addEventListener("click", () => {
    if (button.dataset.closeDialog === "forecastCycleDialog") state.pendingForecastEntryAfterCycle = false;
    $("#" + button.dataset.closeDialog).close();
  }));

  $("#recordSearch").addEventListener("input", renderRecordTable);
  $("#recordStatusFilter").addEventListener("change", renderRecordTable);
  $("#accountRegionFilter").addEventListener("change", () => { populateAccountCountryFilter(); renderRecordTable(); });
  $("#accountCountryFilter").addEventListener("change", renderRecordTable);
  $("#accountOwnerFilter").addEventListener("change", renderRecordTable);
  $("#accountSort").addEventListener("change", renderRecordTable);
  $("#recordMonthFilter").addEventListener("change", () => { renderRecordModuleSummary(); renderRecordTable(); });
  $("#recordSegmentFilter").addEventListener("change", () => { renderRecordModuleSummary(); renderRecordTable(); });
  $("#addRecordBtn").addEventListener("click", () => openRecordDialog());
  $("#recordForm").addEventListener("submit", saveRecord);
  $("#recordForm").addEventListener("input", handleRecordFormInput);
  $("#recordForm").addEventListener("change", handleRecordFormInput);
  $("#targetForm").addEventListener("submit", saveDashboardTarget);
  $("#recordTableBody").addEventListener("click", handleRecordAction);
  $("#recordTableHead").addEventListener("click", handleTaskSort);
  $("#addUserBtn").addEventListener("click", openAdminUserDialog);
  $("#adminUserForm").addEventListener("submit", handleAdminUserCreate);
  $("#resetPasswordForm").addEventListener("submit", handleResetPassword);
  $("#usersTableBody").addEventListener("click", handleUserAction);
  $("#refreshHistoryBtn").addEventListener("click", loadHistory);
  $("#historyAction").addEventListener("change", loadHistory);
  $("#salesYear").addEventListener("change", () => { syncSalesMonthOptions($("#salesYear").value); loadSales(); });
  $("#salesSegment").addEventListener("change", loadSales);
  $("#salesMonth").addEventListener("change", loadSales);
  $("#mapMonth").addEventListener("change", loadGlobalMap);
  $("#mapSegment").addEventListener("change", loadGlobalMap);
  $("#erpSyncBtn").addEventListener("click", openErpDialog);
  $("#erpForm").addEventListener("submit", handleErpSync);
  $("#forecastMonth").addEventListener("change", loadForecast);
  $("#forecastRound").addEventListener("change", loadForecast);
  $("#forecastRoundMonth").addEventListener("change", () => {
    if (state.forecastRoundDirty && !window.confirm("저장하지 않은 FCST 차수 내용이 있습니다. 대상월을 변경할까요?")) {
      $("#forecastRoundMonth").value = state.forecastRounds?.forecast_month || "2026-08";
      return;
    }
    state.forecastDetailSelectedGroup = null;
    loadForecastRoundOverview();
  });
  $("#forecastRoundCards").addEventListener("click", event => {
    const button = event.target.closest("[data-round-snapshot]");
    if (!button) return;
    if (state.forecastRoundDirty && !window.confirm("저장하지 않은 내용이 있습니다. 다른 차수로 이동할까요?")) return;
    state.forecastRoundSelected = Number(button.dataset.roundSnapshot);
    state.forecastDetailSelectedGroup = null;
    state.forecastRoundDirty = false;
    renderForecastRounds();
  });
  $("#forecastCloseRounds").addEventListener("click", event => {
    const button = event.target.closest("[data-round-snapshot]");
    if (!button) return;
    if (state.forecastRoundDirty && !window.confirm("저장하지 않은 내용이 있습니다. 다른 차수로 이동할까요?")) return;
    state.forecastRoundSelected = Number(button.dataset.roundSnapshot);
    state.forecastDetailSelectedGroup = null;
    state.forecastRoundDirty = false;
    renderForecastRounds();
  });
  ["#forecastDetailDimension", "#forecastDetailBusiness", "#forecastDetailStage"].forEach(selector => $(selector).addEventListener("change", () => {
    state.forecastDetailSelectedGroup = null;
    renderForecastRoundDetails(selectedForecastRound());
  }));
  $("#forecastCloseBusiness").addEventListener("change", () => renderForecastCloseDashboard(selectedForecastRound()));
  $("#forecastCloseScope").addEventListener("change", () => renderForecastCloseDashboard(selectedForecastRound()));
  $("#forecastCloseAll").addEventListener("click", event => {
    const button = event.target.closest("[data-close-round-detail]");
    if (!button) return;
    state.forecastRoundSelected = Number(button.dataset.closeRoundDetail);
    $("#forecastCloseScope").value = "selected";
    state.forecastDetailSelectedGroup = null;
    renderForecastRounds();
  });
  $("#forecastDetailSearch").addEventListener("input", () => {
    state.forecastDetailSelectedGroup = null;
    renderForecastRoundDetails(selectedForecastRound());
  });
  $("#forecastDetailSearch").addEventListener("keydown", event => { if (event.key === "Enter") event.preventDefault(); });
  $("#forecastDetailGroupBody").addEventListener("click", event => {
    const row = event.target.closest("[data-detail-group-index]");
    const round = selectedForecastRound();
    if (!row || !round) return;
    const groups = forecastDetailGroups(round, forecastDetailFilteredRows(round), $("#forecastDetailDimension").value || "round");
    state.forecastDetailSelectedGroup = groups[Number(row.dataset.detailGroupIndex)]?.key || null;
    renderForecastRoundDetails(round);
  });
  $("#forecastDetailBody").addEventListener("click", handleForecastDetailAction);
  $("#forecastDetailBody").addEventListener("input", handleForecastDetailRateInput);
  $("#forecastDetailAddBtn").addEventListener("click", () => openForecastDetailDialog());
  $("#forecastDetailForm").addEventListener("submit", saveForecastRoundDetail);
  $("#forecastDetailForm").addEventListener("input", handleForecastDetailRateInput);
  $("#forecastRoundInitializeBtn").addEventListener("click", initializeForecastRoundWorkflows);
  $("#forecastRoundWorkflowForm").addEventListener("submit", event => {
    event.preventDefault();
    saveForecastRoundWorkflow();
  });
  $("#forecastRoundWorkflowForm").addEventListener("input", event => {
    if (!event.target.matches("input, textarea")) return;
    if (event.target.closest(".forecast-detail-workbench")) return;
    state.forecastRoundDirty = true;
    recalculateForecastRoundInputs();
  });
  $("#forecastRoundWorkflowForm").addEventListener("change", event => {
    if (!event.target.matches("input, textarea")) return;
    if (event.target.closest(".forecast-detail-workbench")) return;
    state.forecastRoundDirty = true;
    recalculateForecastRoundInputs();
  });
  $("#forecastRoundConfirmBtn").addEventListener("click", confirmForecastRoundWorkflow);
  $("#forecastRoundReopenBtn").addEventListener("click", reopenForecastRoundWorkflow);
  $("#forecastRoundCopyNextBtn").addEventListener("click", copyForecastRoundWorkflowNext);
  $("#forecastCycleBtn").addEventListener("click", () => {
    state.pendingForecastEntryAfterCycle = false;
    openForecastCycleDialog();
  });
  $("#forecastCopyBtn").addEventListener("click", copyForecastRound);
  $("#forecastAddBtn").addEventListener("click", handleForecastAdd);
  $("#forecastCycleForm").addEventListener("submit", saveForecastCycle);
  $("#forecastCycleDialog").addEventListener("cancel", () => { state.pendingForecastEntryAfterCycle = false; });
  $("#useDailyFxBtn").addEventListener("click", useDailyFxRates);
  $("#forecastItemForm").addEventListener("submit", saveForecastItem);
  $("#forecastItemForm").elements.stage.addEventListener("change", handleForecastStageChange);
  $("#forecastItemForm").elements.currency.addEventListener("change", renderForecastConversionPreview);
  $("#forecastItemForm").elements.foreign_amount.addEventListener("input", renderForecastConversionPreview);
  $("#forecastTableBody").addEventListener("click", handleForecastAction);
  $("#worldMap").addEventListener("click", handleMapCountryClick);
  $("#worldMap").addEventListener("keydown", handleMapCountryKeydown);
  $("#mapCountryDetail").addEventListener("click", handleMapDetailAction);
  $("#forecastCountryFilterChip").addEventListener("click", clearForecastCountryFilter);
  $("#salesCountryFilterChip").addEventListener("click", clearSalesCountryFilter);
  $("#recordCountryFilterChip").addEventListener("click", clearRecordCountryFilter);
  $("#copyAgendaBtn").addEventListener("click", copyMorningAgenda);
  $("#printAgendaBtn").addEventListener("click", () => window.print());
  $$("[data-quick-add]").forEach(button => button.addEventListener("click", () => {
    state.currentEntity = button.dataset.quickAdd;
    openRecordDialog();
  }));
  $("#morningAgenda").addEventListener("click", handleAgendaAction);
  $("#morningPreview").addEventListener("click", handleAgendaAction);
  $("#kpiGrid").addEventListener("click", handleDashboardNavigate);
  $("#targetPerformanceGrid").addEventListener("click", handleTargetEdit);
  $("#financeOverview").addEventListener("click", handleDashboardNavigate);
  $("#regionList").addEventListener("click", handleDashboardNavigate);
  $("#priorityTasks").addEventListener("click", handleAgendaAction);
  $("#priorityPipeline").addEventListener("click", handleAgendaAction);
  $("#overviewSalesChart").addEventListener("click", handleSalesChartClick);
  $("#salesChart").addEventListener("click", handleSalesChartClick);
  $("#salesTableBody").addEventListener("click", handleSalesChartClick);
  $("#partnerSales").addEventListener("click", handlePartnerJourneyAction);
  $("#overviewTopPartners").addEventListener("click", handlePartnerJourneyAction);
  $("#shipmentDetailBody").addEventListener("click", handlePartnerJourneyAction);
  $("#accountJourneyContent").addEventListener("click", handleJourneyAction);
  bindMonthlySalesFcstEvents();
  if (window.CustomerMasterUI) window.CustomerMasterUI.bind();
  $$("[data-account-add]").forEach(button => button.addEventListener("click", () => openJourneyAdd(button.dataset.accountAdd)));
}

async function handleLogin(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const button = formElement.querySelector('button[type="submit"]');
  button.disabled = true;
  button.textContent = "로그인 중…";
  $("#loginError").textContent = "";
  try {
    const form = new FormData(formElement);
    const data = await api("/api/auth/login", { method: "POST", body: { username: form.get("username"), password: form.get("password") } });
    state.me = data.user;
    state.csrf = data.csrf_token;
    const me = await api("/api/auth/me");
    state.permissions = me.permissions;
    showApp();
    formElement.reset();
    await loadAll();
    restoreLastView();
    if (state.me.must_change_password) {
      openPasswordDialog(true);
      toast("보안을 위해 임시 비밀번호를 먼저 변경해 주세요.");
    } else {
      toast(`${state.me.display_name}님, 로그인되었습니다.`);
    }
  } catch (error) {
    $("#loginError").textContent = error.message;
  } finally { button.disabled = false; button.textContent = "로그인"; }
}

async function handleRegister(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const message = $("#registerMessage");
  message.textContent = "";
  const button = formElement.querySelector('button[type="submit"]');
  const form = new FormData(formElement);
  if (form.get("password") !== form.get("password_confirm")) {
    message.style.color = "#c93b3b";
    message.textContent = "비밀번호 확인이 일치하지 않습니다.";
    return;
  }
  button.disabled = true;
  button.textContent = "등록 중…";
  try {
    const data = await api("/api/auth/register", { method: "POST", body: Object.fromEntries(form.entries()) });
    message.style.color = "";
    message.textContent = data.message;
    formElement.reset();
  } catch (error) { message.textContent = error.message; message.style.color = "#c93b3b"; }
  finally { button.disabled = false; button.textContent = "등록 신청"; }
}

async function handleLogout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch (error) {
    toast(`로그아웃하지 못했습니다. 다시 시도해 주세요. (${error.message})`, "error");
    return;
  }
  state.me = null;
  state.csrf = "";
  state.permissions = {};
  state.forcePasswordChange = false;
  const loginForm = $("#loginForm");
  loginForm.reset();
  loginForm.elements.username.value = "";
  loginForm.elements.password.value = "";
  $("#loginError").textContent = "";
  if ($("#passwordDialog").open) $("#passwordDialog").close();
  showAuth("login");
  toast("로그아웃되었습니다.");
}

function openPasswordDialog(required = false) {
  state.forcePasswordChange = Boolean(required);
  const dialog = $("#passwordDialog");
  const form = $("#passwordForm");
  form.reset();
  state.currentOrderDefaults = null;
  $("#recordOrderTermsStatus").textContent = "거래처를 선택하면 현재 결제조건과 제품조건을 불러옵니다.";
  $("#recordOrderTermsStatus").classList.remove("warning-text");
  form.elements.order_terms_change_reason.required = false;
  $("#passwordError").textContent = "";
  $("#passwordRequiredNotice").classList.toggle("hidden", !required);
  $$(".password-dialog-close").forEach(button => button.classList.toggle("hidden", required));
  if (!dialog.open) dialog.showModal();
  window.setTimeout(() => form.elements.current_password.focus(), 0);
}

async function handlePasswordChange(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const errorNode = $("#passwordError");
  const button = $("#passwordSubmitBtn");
  errorNode.textContent = "";
  if (form.get("new_password") !== form.get("new_password_confirm")) {
    errorNode.textContent = "새 비밀번호 확인이 일치하지 않습니다.";
    return;
  }
  button.disabled = true;
  button.textContent = "변경 중…";
  try {
    const data = await api("/api/auth/password", { method: "POST", body: Object.fromEntries(form.entries()) });
    state.csrf = data.csrf_token;
    state.me = data.user;
    state.forcePasswordChange = false;
    formElement.reset();
    $("#passwordDialog").close();
    showApp();
    toast(data.message);
  } catch (error) {
    errorNode.textContent = error.message;
    formElement.elements.current_password.focus();
  } finally {
    button.disabled = false;
    button.textContent = "비밀번호 변경";
  }
}

function availableView(view) {
  const button = $$(".nav-item").find(node => node.dataset.view === view);
  return button && !button.classList.contains("hidden") ? view : "overview";
}

function restoreLastView() {
  let view = "overview";
  try { view = sessionStorage.getItem(LAST_VIEW_STORAGE_KEY) || view; } catch (_error) { /* storage can be disabled */ }
  switchView(availableView(view));
}

function switchView(requestedView) {
  const view = availableView(requestedView);
  const isCustomerMaster = view === "account";
  const isMajorTasks = view === "task";
  const isRecord = Object.hasOwn(recordConfig, view) && !isCustomerMaster && !isMajorTasks;
  const previousEntity = state.currentEntity;
  state.currentEntity = isRecord ? view : state.currentEntity;
  if (isRecord && previousEntity !== view) {
    $("#recordSearch").value = "";
    $("#recordStatusFilter").value = "";
  }
  $$(".nav-item").forEach(node => node.classList.toggle("active", node.dataset.view === view));
  $$(".view").forEach(node => node.classList.remove("active"));
  $(isCustomerMaster ? "#view-account-master" : isMajorTasks ? "#view-major-tasks" : isRecord ? "#view-records" : `#view-${view}`).classList.add("active");
  const title = isCustomerMaster ? [recordConfig.account.eyebrow, recordConfig.account.title] : isMajorTasks ? [recordConfig.task.eyebrow, recordConfig.task.title] : isRecord ? [recordConfig[view].eyebrow, recordConfig[view].title] : viewTitles[view];
  $("#pageEyebrow").textContent = title?.[0] || "GLOBAL MAPS";
  $("#pageTitle").textContent = title?.[1] || "Global MAPS";
  if (isRecord) renderRecordView();
  if (isMajorTasks && window.MajorTasksUI) window.MajorTasksUI.load();
  if (isCustomerMaster && window.CustomerMasterUI) window.CustomerMasterUI.load();
  if (view === "daily") renderDaily();
  if (view === "forecast") renderForecast();
  if (view === "forecast_rounds") renderForecastRounds();
  if (view === "monthly_sales_fcst") loadMonthlySalesFcst();
  if (view === "history") loadHistory();
  if (view === "users") renderUsers();
  try { sessionStorage.setItem(LAST_VIEW_STORAGE_KEY, view); } catch (_error) { /* storage can be disabled */ }
  $(".sidebar").classList.remove("open");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function shiftMonth(value, offset = 1) {
  const [year, month] = value.split("-").map(Number);
  const date = new Date(year, month - 1 + offset, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function renderExchangeRates() {
  const container = $("#fxStrip");
  if (!container) return;
  const rows = state.exchangeRates?.rates || [];
  if (!rows.length) {
    container.innerHTML = `<div class="fx-error"><strong>기준환율을 불러오지 못했습니다.</strong><span>${escapeHtml(state.exchangeRates?.warning || "FCST 차수 설정에서 기준환율을 직접 입력하세요.")}</span></div>`;
    return;
  }
  const labels = { USD: ["미국 달러", "$"], EUR: ["유로", "€"], JPY: ["일본 엔", "¥"], CNY: ["중국 위안", "CN¥"] };
  container.innerHTML = `<div class="fx-title"><span>DAILY REFERENCE FX</span><strong>${escapeHtml(rows[0].rate_date)} 기준환율</strong><small>1 외화단위당 원화 · FCST 설정 시 불러오기 가능</small></div>${rows.map(row => `<div class="fx-rate"><span>${labels[row.currency]?.[1] || row.currency} ${escapeHtml(row.currency)}</span><strong>₩${formatNumber(row.krw_rate, 2)}</strong><small>${labels[row.currency]?.[0] || row.currency}</small></div>`).join("")}<div class="fx-source"><span>${state.exchangeRates.stale ? "최근 영업일" : "오늘"}</span><small>중앙은행 기준환율</small></div>`;
}

function forecastForeignText(summary) {
  const entries = Object.entries(summary?.foreign_totals || {}).filter(([, value]) => Number(value));
  return entries.length ? entries.map(([currency, value]) => formatMoney(value, currency)).join(" · ") : "외화 입력 없음";
}

function forecastKpiMarkup(summary) {
  const completion = Number(summary?.achievement_pct || 0);
  return [
    ["전체 FCST", formatMoney(summary?.total_krw || 0), forecastForeignText(summary), "forecast"],
    ["가중 FCST", formatMoney(summary?.weighted_krw || 0), "단계별 확률을 반영한 위험조정 금액", "weighted"],
    ["ERP 확정매출", formatMoney(summary?.erp_actual_krw || 0), "면장 발급시점 환율 반영 · 출고 완료", "actual"],
    ["FCST 잔여", formatMoney(summary?.remaining_to_fcst_krw || 0), `ERP 달성률 ${formatNumber(completion, 1)}% · 이월 ${formatNumber(summary?.carryover_count || 0)}건`, "remaining"],
  ].map(card => `<article class="forecast-hero-card ${card[3]}"><span>${card[0]}</span><strong>${card[1]}</strong><small>${escapeHtml(card[2])}</small></article>`).join("");
}

function forecastStageMarkup(stages, compact = false) {
  return (stages || []).map(row => `<div class="forecast-stage-card ${escapeHtml(row.key)} ${compact ? "compact" : ""}"><div><span>${escapeHtml(row.label)}</span><b>${formatNumber(row.count)}건</b></div><strong>${formatMoney(row.krw_amount)}</strong><small>기본 ${formatNumber(row.default_confidence)}% · 가중 ${formatMoney(row.weighted_krw)}</small></div>`).join("");
}

function roundComparisonMarkup(rows, selectedRound = null) {
  if (!rows?.length) return '<p class="agenda-empty">아직 생성된 가마감 차수가 없습니다.</p>';
  return rows.map(row => `<button class="round-row ${Number(selectedRound) === Number(row.round_no) ? "selected" : ""}" type="button" data-forecast-round="${row.round_no}"><span>${row.round_no}차</span><div><strong>${formatMoney(row.total_krw)}</strong><small>${escapeHtml(row.as_of_date)} · ERP ${formatMoney(row.erp_actual_krw)}</small></div><b>${formatNumber(row.item_count)}건</b></button>`).join("");
}

function forecastSummaryForRows(rows, country = null) {
  const total = rows.reduce((sum, row) => sum + Number(row.krw_amount || 0), 0);
  const weighted = rows.reduce((sum, row) => sum + Number(row.weighted_krw || 0), 0);
  const actual = Number(country?.erp_actual_krw || 0);
  const foreignTotals = {};
  rows.forEach(row => { foreignTotals[row.currency] = (foreignTotals[row.currency] || 0) + Number(row.foreign_amount || 0); });
  return {
    total_krw: total,
    weighted_krw: weighted,
    erp_actual_krw: actual,
    remaining_to_fcst_krw: Math.max(total - actual, 0),
    achievement_pct: total ? (actual / total) * 100 : 0,
    item_count: rows.length,
    carryover_count: rows.filter(row => row.is_carryover).length,
    foreign_totals: foreignTotals,
    by_stage: ["sales_activity", "pi_received", "payment_received"].map(stage => {
      const selected = rows.filter(row => row.stage === stage);
      return {
        key: stage, label: forecastStageLabels[stage], default_confidence: forecastStageDefaults[stage],
        count: selected.length,
        krw_amount: selected.reduce((sum, row) => sum + Number(row.krw_amount || 0), 0),
        weighted_krw: selected.reduce((sum, row) => sum + Number(row.weighted_krw || 0), 0),
      };
    }),
  };
}

function renderOverviewForecast() {
  if (!state.forecast) return;
  const f = state.forecast;
  const roundText = f.selected_round ? `${f.selected_round}차 가마감` : "차수 미설정";
  $("#overviewForecastTitle").textContent = `${f.forecast_month} FCST · ${roundText}`;
  $("#overviewForecastKpis").innerHTML = forecastKpiMarkup(f.summary);
  $("#overviewForecastStages").innerHTML = f.cycle ? forecastStageMarkup(f.summary.by_stage, true) : '<div class="forecast-empty"><strong>FCST 차수를 먼저 설정하세요.</strong><span>관리자가 기준환율과 1차 가마감을 만들면 담당자가 항목을 입력할 수 있습니다.</span></div>';
  $("#overviewForecastRounds").innerHTML = roundComparisonMarkup(f.round_summaries, f.selected_round);
  $$("[data-forecast-round]", $("#overviewForecastRounds")).forEach(button => button.addEventListener("click", () => {
    switchView("forecast");
    $("#forecastRound").value = button.dataset.forecastRound;
    loadForecast();
  }));
}

function renderForecast() {
  if (!state.forecast) return;
  const f = state.forecast;
  const cycle = f.cycle;
  const allRows = f.items || [];
  const countryFilter = state.forecastCountryFilter;
  const rows = countryFilter ? allRows.filter(item => item.account_country_code === countryFilter.map_id) : allRows;
  const summary = countryFilter ? forecastSummaryForRows(rows, countryFilter) : (f.summary || {});
  renderCountryFilterChips();
  $("#forecastKpis").innerHTML = forecastKpiMarkup(summary);
  $("#forecastStageCards").innerHTML = cycle ? forecastStageMarkup(summary.by_stage) : '<div class="forecast-empty"><strong>선택한 월의 FCST가 없습니다.</strong><span>관리자가 1차 가마감과 기준환율을 설정해 주세요.</span></div>';
  $("#forecastRoundComparison").innerHTML = roundComparisonMarkup(f.round_summaries, f.selected_round);
  $$("[data-forecast-round]", $("#forecastRoundComparison")).forEach(button => button.addEventListener("click", () => {
    $("#forecastRound").value = button.dataset.forecastRound;
    loadForecast();
  }));
  const rates = cycle?.rates || {};
  $("#forecastDefinition").innerHTML = cycle
    ? `<div><strong>${escapeHtml(f.forecast_month)} · ${escapeHtml(cycle.round_label)} · 기준일 ${escapeHtml(cycle.as_of_date)}</strong><span>전체 FCST는 입력금액 합계입니다. 가중 FCST만 단계별 확률을 적용합니다.</span></div><div class="definition-rates"><span>USD ${formatNumber(rates.USD, 2)}원</span><span>EUR ${formatNumber(rates.EUR, 2)}원</span><span>CNY ${formatNumber(rates.CNY, 2)}원</span><b>${cycle.status === "closed" ? "차수 마감" : "입력 가능"}</b></div>`
    : `<div><strong>${escapeHtml(f.forecast_month)} FCST 차수 미설정</strong><span>FCST 기준환율은 입력 시점에 고정되며 ERP 확정매출 환율과 섞지 않습니다.</span></div>`;
  const addButton = $("#forecastAddBtn");
  addButton.disabled = false;
  addButton.title = !cycle
    ? "FCST 차수와 기준환율 설정 후 항목을 등록합니다."
    : cycle.status === "closed"
      ? "마감된 차수입니다. 클릭하면 다음 처리 방법을 안내합니다."
      : `${cycle.round_label}에 FCST 항목을 등록합니다.`;
  $("#forecastCopyBtn").disabled = !cycle || Number(cycle.round_no) >= 3;
  $("#forecastTableTitle").textContent = `${f.forecast_month} ${cycle?.round_label || "FCST"} ${countryFilter ? `· ${countryFilter.label}` : ""} 상세`;
  $("#forecastItemCount").textContent = `총 ${formatNumber(rows.length)}건`;
  $("#forecastTableBody").innerHTML = rows.length ? rows.map(item => {
    const canModify = Boolean(!item.source_type && state.me && (state.permissions.can_edit_all || (state.me.role === "editor" && item.owner_id === state.me.id)) && cycle?.status !== "closed");
    const actions = item.source_type === "promotion" ? `<button class="mini-btn emphasis" data-forecast-action="promotion-source" data-id="${item.id}">프로모션에서 보기</button>` : canModify ? `<div class="table-actions forecast-actions"><button class="mini-btn" data-forecast-action="edit" data-id="${item.id}">수정</button><button class="mini-btn emphasis" data-forecast-action="carryover" data-id="${item.id}">다음달 이월</button><button class="mini-btn danger" data-forecast-action="delete" data-id="${item.id}">삭제</button></div>` : '<span class="muted">조회 전용</span>';
    const source = item.source_type === "promotion"
      ? '<span class="badge info">프로모션 자동</span>'
      : item.source_type === "legacy_monthly_summary"
        ? '<span class="badge info">월매출 원본</span>'
        : item.is_carryover
          ? `<span class="carryover-badge">${escapeHtml(item.carryover_from_month)} 이월</span>`
          : `${f.selected_round || "—"}차 신규`;
    return `<tr><td class="table-title">${escapeHtml(item.account_name || "거래처 미지정")}<span class="table-sub">${escapeHtml(item.title)}${item.item_name ? ` · ${escapeHtml(item.item_name)}` : ""}</span></td><td>${escapeHtml(segmentLabels[item.business_unit] || item.business_unit)}</td><td><span class="forecast-stage-badge ${escapeHtml(item.stage)}">${escapeHtml(item.stage_label)}</span><span class="table-sub">가중 ${formatNumber(item.confidence)}%</span></td><td><strong>${formatMoney(item.foreign_amount, item.currency)}</strong></td><td>₩${formatNumber(item.applied_rate, 2)}<span class="table-sub">1 ${escapeHtml(item.currency)} 기준</span></td><td><strong>${formatMoney(item.krw_amount)}</strong><span class="table-sub">가중 ${formatMoney(item.weighted_krw)}</span></td><td>${formatDate(item.expected_ship_date)}</td><td>${source}</td><td>${escapeHtml(item.owner_name || "미지정")}</td><td>${actions}</td></tr>`;
  }).join("") : `<tr><td colspan="10"><div class="empty-state">${countryFilter ? `${escapeHtml(countryFilter.label)}에 연결된 FCST 항목이 없습니다.` : "선택한 차수에 등록된 FCST 항목이 없습니다."}</div></td></tr>`;
}

function forecastRoundMillion(value, signed = false) {
  if (value === null || value === undefined || value === "") return "확인 필요";
  const amount = Number(value) / 1000000;
  const prefix = signed && amount > 0 ? "+" : "";
  return `${prefix}${formatNumber(amount, 1)}`;
}

function forecastRoundInputMillion(value) {
  const amount = Number(value || 0) / 1000000;
  return String(Math.round(amount * 1000) / 1000);
}

function selectedForecastRound() {
  const rounds = state.forecastRounds?.rounds || [];
  return rounds.find(round => Number(round.round_no) === Number(state.forecastRoundSelected)) || rounds[0] || null;
}

function forecastRoundCardMarkup(rounds, selectedRound) {
  return rounds.map((round, index) => {
    const total = round.business_units?.total || {};
    const previous = rounds[index - 1]?.business_units?.total?.current_expected;
    const delta = previous === undefined ? null : Number(total.current_expected || 0) - Number(previous || 0);
    const deltaPct = previous ? delta / Number(previous) * 100 : null;
    const selected = Number(round.round_no) === Number(selectedRound);
    const progress = round.progress || { completed: 0, required: 0, percent: 0 };
    return `<button class="forecast-round-card ${selected ? "selected" : ""} ${round.status === "confirmed" ? "confirmed" : ""}" type="button" role="tab" aria-selected="${selected}" data-round-snapshot="${round.round_no}">
      <div class="forecast-round-card-head"><span>${escapeHtml(round.round_label)}</span><b>${round.status === "confirmed" ? "확정 · 잠금" : `작성 중 · ${progress.completed}/${progress.required}`}</b></div>
      <strong>${forecastRoundMillion(total.current_expected)}<small>백만원</small></strong>
      <div class="forecast-round-card-metrics"><span>확정+예정 <b>${forecastRoundMillion(total.confirmed_scheduled)}</b></span><span>추진 <b>${forecastRoundMillion(total.pipeline)}</b></span></div>
      <div class="forecast-round-progress"><i style="width:${Math.min(100, Number(progress.percent || 0))}%"></i></div>
      <footer><span>${round.as_of_date ? `${formatDate(round.as_of_date)} 기준` : "기준일 미입력"}</span><b>${delta === null ? "시작 단계" : `${forecastRoundMillion(delta, true)} · ${deltaPct === null ? "—" : `${deltaPct >= 0 ? "+" : ""}${formatNumber(deltaPct, 1)}%`}`}</b></footer>
    </button>`;
  }).join("");
}

function forecastRoundKpiMarkup(round) {
  const total = round.business_units?.total || {};
  const nextTotal = Number(total.next_month || 0) + Number(total.next_pipeline || 0);
  return [
    ["사업계획", total.plan, "선택 월 사업 목표", "forecast"],
    ["예상매출", total.current_expected, "확정·예정·추진 합계", "weighted"],
    ["확정+예정", total.confirmed_scheduled, `이월 ${forecastRoundMillion(total.carryover)}백만원`, "actual"],
    ["차월 예상", nextTotal, `확정·예정 ${forecastRoundMillion(total.next_month)} · 추진 ${forecastRoundMillion(total.next_pipeline)}`, "remaining"],
  ].map(([label, value, note, style]) => `<article class="forecast-hero-card ${style}"><span>${label}</span><strong>${forecastRoundMillion(value)}백만원</strong><small>${escapeHtml(note)}</small></article>`).join("");
}

function forecastRoundBusinessMarkup(data, round) {
  const units = (data.business_units || []).filter(unit => unit.key !== "total");
  const canEdit = Boolean(round.permissions?.can_edit);
  const fields = ["plan", "initial_fcst", "first_expected", "carryover", "current_month", "pipeline"];
  const tailFields = ["next_month", "next_pipeline"];
  const inputCell = (unit, row, field) => `<td><input type="number" min="0" step="0.001" inputmode="decimal" data-round-field="${field}" value="${forecastRoundInputMillion(row[field])}" aria-label="${escapeHtml(unit.label)} ${field}" ${canEdit ? "" : "disabled"}></td>`;
  const rows = units.map(unit => {
    const row = round.business_units?.[unit.key] || {};
    return `<tr data-round-unit="${unit.key}"><td><strong>${escapeHtml(unit.label)}</strong>${row.notes ? `<span class="forecast-round-unit-note" title="${escapeHtml(row.notes)}">${escapeHtml(row.notes)}</span>` : ""}</td>${fields.map(field => inputCell(unit, row, field)).join("")}<td class="calculated" data-calc="current_expected">${forecastRoundMillion(row.current_expected)}</td>${tailFields.map(field => inputCell(unit, row, field)).join("")}<td class="calculated ${Number(row.plan_variance || 0) < 0 ? "negative" : "positive"}" data-calc="plan_variance">${forecastRoundMillion(row.plan_variance, true)}</td></tr>`;
  });
  const total = round.business_units?.total || {};
  const totalFields = ["plan", "initial_fcst", "first_expected", "carryover", "current_month", "pipeline"];
  rows.push(`<tr class="forecast-round-total"><td>합계</td>${totalFields.map(field => `<td data-total-field="${field}">${forecastRoundMillion(total[field])}</td>`).join("")}<td class="calculated" data-total-field="current_expected">${forecastRoundMillion(total.current_expected)}</td><td data-total-field="next_month">${forecastRoundMillion(total.next_month)}</td><td data-total-field="next_pipeline">${forecastRoundMillion(total.next_pipeline)}</td><td class="calculated ${Number(total.plan_variance || 0) < 0 ? "negative" : "positive"}" data-total-field="plan_variance">${forecastRoundMillion(total.plan_variance, true)}</td></tr>`);
  return rows.join("");
}

function forecastRoundChecklistMarkup(round) {
  const canEdit = Boolean(round.permissions?.can_edit);
  return (round.checklist || []).map(item => `<label class="forecast-round-check-item ${item.completed ? "completed" : ""}">
    <input type="checkbox" data-check-key="${escapeHtml(item.check_key)}" ${item.completed ? "checked" : ""} ${canEdit ? "" : "disabled"}>
    <span>${escapeHtml(item.label)}${item.required ? " *" : ""}</span>
    <input type="text" data-check-note="${escapeHtml(item.check_key)}" value="${escapeHtml(item.note || "")}" maxlength="500" placeholder="확인 내용 또는 이슈 메모" ${canEdit ? "" : "disabled"}>
    ${item.completed_by_name ? `<small class="forecast-round-check-meta">${escapeHtml(item.completed_by_name)} · ${formatDate(item.completed_at)}</small>` : ""}
  </label>`).join("");
}

function forecastRoundCompositionMarkup(round) {
  const total = round.business_units?.total || {};
  const expected = Number(total.current_expected || 0);
  const nextTotal = Number(total.next_month || 0) + Number(total.next_pipeline || 0);
  const rows = [
    ["확정+예정", Number(total.confirmed_scheduled || 0), "confirmed"],
    ["추진", Number(total.pipeline || 0), "pipeline"],
    ["전월 이월", Number(total.carryover || 0), "carryover"],
    ["당월 매출", Number(total.current_month || 0), "current"],
    ["차월 예상", nextTotal, "next"],
  ];
  return rows.map(([label, value, style]) => {
    const pct = expected ? value / expected * 100 : 0;
    return `<div class="forecast-composition-row ${style}"><div><span>${label}</span><strong>${forecastRoundMillion(value)}백만원</strong></div><div class="forecast-composition-track"><i style="width:${Math.min(Math.max(pct, 0), 100)}%"></i></div><small>선택 차수 예상매출 대비 ${formatNumber(pct, 1)}%</small></div>`;
  }).join("");
}

function forecastRoundComparisonMarkup(data) {
  const rounds = data.rounds || [];
  const metrics = [
    ["사업계획", "plan", false],
    ["월초 FCST", "initial_fcst", false],
    ["1차 예상매출", "first_expected", false],
    ["차수 예상매출", "current_expected", false],
    ["확정+예정", "confirmed_scheduled", false],
    ["전월 이월", "carryover", false],
    ["당월 매출", "current_month", false],
    ["추진", "pipeline", false],
    ["차월 확정·예정", "next_month", false],
    ["차월 추진", "next_pipeline", false],
    ["사업계획 대비", "plan_variance", true],
    ["월초 FCST 대비", "initial_variance", true],
  ];
  return metrics.map(([label, key, signed]) => `<tr><td><strong>${label}</strong></td>${[0, 1, 2, 3].map(roundNo => {
    const round = rounds.find(item => Number(item.round_no) === roundNo);
    const value = round?.business_units?.total?.[key];
    const selected = Number(state.forecastRoundSelected) === roundNo ? "selected" : "";
    return `<td class="${selected} ${signed && Number(value || 0) < 0 ? "negative" : ""}">${forecastRoundMillion(value, signed)}</td>`;
  }).join("")}</tr>`).join("");
}

const forecastCloseManagementTypes = [
  ["additional", "추가추진"], ["promotion", "프로모션"], ["expiring_inventory", "임박재고"],
];

function forecastCloseRows(round, business = $("#forecastCloseBusiness")?.value || "") {
  return (round?.details || []).filter(detail => !business || detail.business_unit === business);
}

function forecastCloseCurrent(detail) {
  return Number(detail.carryover_krw || 0) + Number(detail.current_krw || 0);
}

function forecastCloseSummary(round, business = $("#forecastCloseBusiness")?.value || "") {
  const rows = forecastCloseRows(round, business);
  const unit = business ? round?.business_units?.[business] : round?.business_units?.total;
  const result = { rows, target: Number(unit?.plan || 0), minimum: 0, pipeline: 0, undecided: 0, secured: 0, maximum: 0 };
  rows.forEach(detail => {
    const amount = forecastCloseCurrent(detail);
    if (["confirmed", "scheduled"].includes(detail.sales_stage)) result.minimum += amount;
    else if (detail.sales_stage === "pipeline") result.pipeline += amount;
    else result.undecided += amount;
  });
  result.secured = result.minimum + result.pipeline;
  result.maximum = result.secured + result.undecided;
  if (!rows.length) {
    result.minimum = Number(unit?.confirmed_scheduled || 0);
    result.pipeline = Number(unit?.pipeline || 0);
    result.secured = Number(unit?.current_expected || 0);
    result.maximum = result.secured;
  }
  result.remaining = Math.max(result.target - result.secured, 0);
  result.achievement = result.target ? result.secured / result.target * 100 : 0;
  return result;
}

function forecastCloseMatchKey(detail) {
  if (detail.tracking_key) return `tracking:${detail.tracking_key}`;
  return `detail:${forecastCloseCompositeKey(detail)}`;
}

function forecastCloseCompositeKey(detail) {
  return [detail.business_unit, detail.country_name, detail.account_name, detail.item_name, detail.classification]
    .map(value => String(value || "").trim().toLocaleLowerCase()).join("|");
}

function forecastClosePreviousRound(round) {
  return [...(state.forecastRounds?.rounds || [])]
    .filter(item => Number(item.round_no) < Number(round?.round_no))
    .sort((a, b) => Number(b.round_no) - Number(a.round_no))[0] || null;
}

function forecastCloseFxImpact(round, business) {
  const previous = forecastClosePreviousRound(round);
  if (!previous) return { amount: 0, previous: null };
  const previousDetails = forecastCloseRows(previous, business);
  const previousRows = new Map(previousDetails.map(detail => [forecastCloseMatchKey(detail), detail]));
  const previousCompositeRows = new Map(previousDetails.map(detail => [forecastCloseCompositeKey(detail), detail]));
  let amount = 0;
  forecastCloseRows(round, business).forEach(detail => {
    const before = previousRows.get(forecastCloseMatchKey(detail)) || previousCompositeRows.get(forecastCloseCompositeKey(detail));
    if (!before || detail.currency === "KRW") return;
    const foreign = Number(detail.carryover_foreign || 0) + Number(detail.current_foreign || 0);
    amount += foreign * (Number(detail.applied_rate || 0) - Number(before.applied_rate || 0));
  });
  return { amount, previous };
}

function forecastCloseKpiMarkup(round, summary, business) {
  const fx = forecastCloseFxImpact(round, business);
  const previousSummary = fx.previous ? forecastCloseSummary(fx.previous, business) : null;
  const delta = previousSummary ? summary.secured - previousSummary.secured : null;
  return [
    ["총 목표", summary.target, "선택 차수 사업계획", "target"],
    ["현재 확보", summary.secured, `확정·예정 ${forecastRoundMillion(summary.minimum)} + 추진 ${forecastRoundMillion(summary.pipeline)}`, "secured"],
    ["달성률", summary.achievement, `잔여 ${forecastRoundMillion(summary.remaining)}백만원`, "achievement", true],
    ["전 차수 변동", delta, fx.previous ? `${fx.previous.round_label} 대비` : "이전 차수 없음", "delta"],
    ["환율 영향", fx.amount, fx.previous ? "동일 상세행의 적용환율 차이" : "비교 차수 없음", "fx"],
  ].map(([label, value, note, style, percent]) => `<div class="forecast-close-kpi ${style}"><span>${label}</span><strong>${percent ? `${formatNumber(value, 1)}%` : value === null ? "—" : `${forecastRoundMillion(value, style === "delta" || style === "fx")}백만원`}</strong><small>${escapeHtml(note)}</small></div>`).join("");
}

function forecastCloseScenarioMarkup(summary) {
  const ceiling = Math.max(summary.target, summary.maximum, 1);
  return [
    ["최소", summary.minimum, "확정·예정", "minimum"],
    ["현재", summary.secured, "확정·예정+추진", "secured"],
    ["최대", summary.maximum, "미정 포함", "maximum"],
    ["목표", summary.target, "사업계획", "target"],
  ].map(([label, value, note, style]) => `<div class="forecast-close-bar ${style}"><div><b>${label}</b><span>${escapeHtml(note)}</span><strong>${forecastRoundMillion(value)}백만원</strong></div><div><i style="width:${Math.min(value / ceiling * 100, 100)}%"></i></div></div>`).join("");
}

function forecastCloseProgressMarkup(summary) {
  return [["order_received", "오더접수"], ["pi_issued", "PI발행"], ["payment_completed", "입금완료"], ["shipment_completed", "출고완료"]].map(([key, label]) => {
    const rows = summary.rows.filter(detail => detail.progress_status === key);
    const amount = rows.reduce((sum, detail) => sum + forecastCloseCurrent(detail), 0);
    return `<div class="forecast-close-status ${key}"><span>${label}</span><strong>${forecastRoundMillion(amount)}백만원</strong><small>${formatNumber(rows.length)}건</small></div>`;
  }).join("");
}

function forecastCloseRoundsMarkup(business) {
  const rounds = state.forecastRounds?.rounds || [];
  const maximum = Math.max(...rounds.map(item => forecastCloseSummary(item, business).secured), 1);
  return rounds.map(item => {
    const summary = forecastCloseSummary(item, business);
    const selected = Number(item.round_no) === Number(state.forecastRoundSelected);
    return `<button type="button" data-round-snapshot="${item.round_no}" class="forecast-close-round ${selected ? "selected" : ""}"><span>${escapeHtml(item.round_label)}</span><div><i style="height:${Math.max(summary.secured / maximum * 100, summary.secured ? 8 : 0)}%"></i></div><strong>${forecastRoundMillion(summary.secured)}</strong><small>백만원</small></button>`;
  }).join("");
}

function forecastCloseInitiativesMarkup(summary) {
  const rows = forecastCloseManagementTypes.map(([key, label]) => {
    const details = summary.rows.filter(detail => detail.management_type === key);
    const target = details.reduce((sum, detail) => sum + Number(detail.plan_krw || 0), 0);
    const secured = details.reduce((sum, detail) => sum + forecastCloseCurrent(detail), 0);
    return { key, label, count: details.length, target, secured, remaining: Math.max(target - secured, 0) };
  });
  if (!rows.some(row => row.count)) return `<div class="forecast-close-empty">상세자료에서 관리유형을 지정하면 백업·프로모션 현황이 표시됩니다.</div>`;
  return rows.map(row => `<div class="forecast-close-initiative ${row.key}"><div><b>${row.label}</b><span>${row.count}건</span></div><strong>${forecastRoundMillion(row.secured)} / ${forecastRoundMillion(row.target)}</strong><small>잔여 ${forecastRoundMillion(row.remaining)}백만원</small></div>`).join("");
}

function forecastCloseAccountsMarkup(summary) {
  const accounts = new Map();
  summary.rows.forEach(detail => {
    const key = `${detail.country_name}|${detail.account_name}`;
    const row = accounts.get(key) || { country: detail.country_name, account: detail.account_name, business: detail.business_label, amount: 0, statuses: new Set(), targetDate: null };
    row.amount += forecastCloseCurrent(detail);
    row.statuses.add(detail.progress_status_label || "오더접수");
    if (detail.target_date && (!row.targetDate || detail.target_date < row.targetDate)) row.targetDate = detail.target_date;
    accounts.set(key, row);
  });
  const rows = [...accounts.values()].sort((a, b) => b.amount - a.amount).slice(0, 5);
  return rows.length ? rows.map(row => `<tr><td><strong>${escapeHtml(row.country || "국가 미지정")}</strong><span class="table-sub">${escapeHtml(row.account || "거래처 미지정")}</span></td><td>${escapeHtml(row.business || "—")}</td><td>${escapeHtml([...row.statuses].join(" · "))}</td><td><strong>${forecastRoundMillion(row.amount)}백만원</strong></td><td>${row.targetDate ? formatDate(row.targetDate) : "—"}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty-state">표시할 상세자료가 없습니다.</div></td></tr>`;
}

function forecastCloseChangesMarkup(summary) {
  const rows = [...summary.rows].filter(detail => detail.change_reason || detail.notes || detail.target_date)
    .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || ""))).slice(0, 5);
  if (!rows.length) return `<div class="forecast-close-empty">변동사유·목표일·후속조치를 입력하면 최근 변경사항이 표시됩니다.</div>`;
  return rows.map(detail => `<article><div><span class="forecast-management-badge ${escapeHtml(detail.management_type || "regular")}">${escapeHtml(detail.management_type_label || "일반")}</span><strong>${escapeHtml(detail.account_name || "거래처 미지정")}</strong><time>${detail.target_date ? `${formatDate(detail.target_date)} 목표` : "목표일 미입력"}</time></div><p>${escapeHtml(detail.change_reason || detail.notes || "후속조치 미입력")}</p></article>`).join("");
}

function forecastCloseAllKpisMarkup(business) {
  const rounds = state.forecastRounds?.rounds || [];
  const cards = [0, 1, 2, 3].map(roundNo => {
    const item = rounds.find(round => Number(round.round_no) === roundNo);
    if (!item) return [roundNo === 0 ? "미정" : `${roundNo}차`, null, "자료 없음", "round"];
    const summary = forecastCloseSummary(item, business);
    const previous = forecastClosePreviousRound(item);
    const previousSummary = previous ? forecastCloseSummary(previous, business) : null;
    const delta = previousSummary ? summary.secured - previousSummary.secured : null;
    return [item.round_label, summary.secured, `달성 ${formatNumber(summary.achievement, 1)}%${delta === null ? "" : ` · 전차수 ${forecastRoundMillion(delta, true)}`}`, "round"];
  });
  const latest = [...rounds].sort((a, b) => Number(b.round_no) - Number(a.round_no))[0];
  const latestSummary = latest ? forecastCloseSummary(latest, business) : null;
  cards.push(["최종 잔여", latestSummary?.remaining ?? null, latest ? `${latest.round_label} 기준` : "자료 없음", "remaining"]);
  return cards.map(([label, value, note, style]) => `<div class="forecast-close-kpi ${style}"><span>${escapeHtml(label)}</span><strong>${value === null ? "—" : `${forecastRoundMillion(value)}백만원`}</strong><small>${escapeHtml(note)}</small></div>`).join("");
}

function forecastCloseAllProgressMarkup(summary) {
  return [["order_received", "오더"], ["pi_issued", "PI"], ["payment_completed", "입금"], ["shipment_completed", "출고"]].map(([key, label]) => {
    const details = summary.rows.filter(detail => detail.progress_status === key);
    const amount = details.reduce((sum, detail) => sum + forecastCloseCurrent(detail), 0);
    return `<div class="${key}"><span>${label}</span><strong>${forecastRoundMillion(amount)}</strong><small>${details.length}건</small></div>`;
  }).join("");
}

function forecastCloseAllInitiativeSummary(summary) {
  const details = summary.rows.filter(detail => detail.management_type && detail.management_type !== "regular");
  return {
    count: details.length,
    target: details.reduce((sum, detail) => sum + Number(detail.plan_krw || 0), 0),
    secured: details.reduce((sum, detail) => sum + forecastCloseCurrent(detail), 0),
  };
}

function forecastCloseAllMarkup(business) {
  const rounds = state.forecastRounds?.rounds || [];
  if (!rounds.length) return `<div class="forecast-close-empty">비교할 차수자료가 없습니다.</div>`;
  return [...rounds].sort((a, b) => Number(a.round_no) - Number(b.round_no)).map(item => {
    const summary = forecastCloseSummary(item, business);
    const previous = forecastClosePreviousRound(item);
    const previousSummary = previous ? forecastCloseSummary(previous, business) : null;
    const delta = previousSummary ? summary.secured - previousSummary.secured : null;
    const fx = forecastCloseFxImpact(item, business);
    const initiative = forecastCloseAllInitiativeSummary(summary);
    const scenarioMax = Math.max(summary.target, summary.maximum, 1);
    return `<article class="forecast-close-all-card ${Number(item.round_no) === Number(state.forecastRoundSelected) ? "selected" : ""}">
      <header><div><span>${escapeHtml(item.round_label)}</span><strong>${item.status === "confirmed" ? "확정 · 잠금" : "작성 중"}</strong></div><small>${item.as_of_date ? `${formatDate(item.as_of_date)} 기준` : "기준일 미입력"}</small></header>
      <div class="forecast-close-all-main"><span>현재 확보</span><strong>${forecastRoundMillion(summary.secured)}<small>백만원</small></strong><b>${formatNumber(summary.achievement, 1)}%</b></div>
      <div class="forecast-close-all-metrics"><div><span>목표</span><strong>${forecastRoundMillion(summary.target)}</strong></div><div><span>확정·예정</span><strong>${forecastRoundMillion(summary.minimum)}</strong></div><div><span>추진</span><strong>${forecastRoundMillion(summary.pipeline)}</strong></div><div><span>잔여</span><strong>${forecastRoundMillion(summary.remaining)}</strong></div></div>
      <div class="forecast-close-all-scenario"><div><span>최소</span><i><b style="width:${Math.min(summary.minimum / scenarioMax * 100, 100)}%"></b></i><strong>${forecastRoundMillion(summary.minimum)}</strong></div><div><span>현재</span><i><b style="width:${Math.min(summary.secured / scenarioMax * 100, 100)}%"></b></i><strong>${forecastRoundMillion(summary.secured)}</strong></div><div><span>최대</span><i><b style="width:${Math.min(summary.maximum / scenarioMax * 100, 100)}%"></b></i><strong>${forecastRoundMillion(summary.maximum)}</strong></div></div>
      <div class="forecast-close-all-progress">${forecastCloseAllProgressMarkup(summary)}</div>
      <div class="forecast-close-all-foot"><div><span>전 차수 변동</span><strong>${delta === null ? "—" : `${forecastRoundMillion(delta, true)}백만원`}</strong></div><div><span>환율 영향</span><strong>${previous ? `${forecastRoundMillion(fx.amount, true)}백만원` : "—"}</strong></div><div><span>추가매출 관리</span><strong>${initiative.count}건 · ${forecastRoundMillion(initiative.secured)}/${forecastRoundMillion(initiative.target)}</strong></div></div>
      <button type="button" class="btn outline" data-close-round-detail="${item.round_no}">${escapeHtml(item.round_label)} 상세보기</button>
    </article>`;
  }).join("");
}

function renderForecastCloseDashboard(round) {
  if (!round) return;
  const business = $("#forecastCloseBusiness")?.value || "";
  const scope = $("#forecastCloseScope")?.value || "selected";
  const allMode = scope === "all";
  $("#forecastCloseSelected").classList.toggle("hidden", allMode);
  $("#forecastCloseAll").classList.toggle("hidden", !allMode);
  if (allMode) {
    $("#forecastCloseKpis").innerHTML = forecastCloseAllKpisMarkup(business);
    $("#forecastCloseAll").innerHTML = forecastCloseAllMarkup(business);
    return;
  }
  const summary = forecastCloseSummary(round, business);
  $("#forecastCloseKpis").innerHTML = forecastCloseKpiMarkup(round, summary, business);
  $("#forecastCloseScenario").innerHTML = forecastCloseScenarioMarkup(summary);
  $("#forecastCloseProgress").innerHTML = forecastCloseProgressMarkup(summary);
  $("#forecastCloseRounds").innerHTML = forecastCloseRoundsMarkup(business);
  $("#forecastCloseInitiatives").innerHTML = forecastCloseInitiativesMarkup(summary);
  $("#forecastCloseAccounts").innerHTML = forecastCloseAccountsMarkup(summary);
  $("#forecastCloseChanges").innerHTML = forecastCloseChangesMarkup(summary);
}

function forecastDetailFilteredRows(round) {
  const business = $("#forecastDetailBusiness")?.value || "";
  const stage = $("#forecastDetailStage")?.value || "";
  const search = ($("#forecastDetailSearch")?.value || "").trim().toLocaleLowerCase();
  return (round?.details || []).filter(detail => {
    if (business && detail.business_unit !== business) return false;
    if (stage && detail.sales_stage !== stage) return false;
    if (!search) return true;
    return [detail.country_name, detail.account_name, detail.item_name, detail.classification, detail.owner_name, detail.change_reason, detail.notes]
      .some(value => String(value || "").toLocaleLowerCase().includes(search));
  });
}

function forecastDetailGroupKey(detail, dimension, round) {
  if (dimension === "item") return detail.item_name || "품목 미지정";
  if (dimension === "country") return detail.country_name || "국가 미지정";
  if (dimension === "account") return detail.account_name || "거래처 미지정";
  return round?.round_label || "선택 차수";
}

function forecastDetailLatest(detail) {
  const values = ["order_agreed_at", "po_received_at", "pi_sent_at", "payment_expected_at", "payment_completed_at", "shipment_expected_at", "shipment_completed_at", "shipping_completed_at"]
    .map(key => detail[key]).filter(Boolean).sort();
  return values.at(-1) || null;
}

function forecastDetailGroups(round, rows, dimension) {
  const groups = new Map();
  rows.forEach(detail => {
    const key = forecastDetailGroupKey(detail, dimension, round);
    if (!groups.has(key)) groups.set(key, { key, label: key, rows: [], confirmed_scheduled: 0, pipeline: 0, undecided: 0, current: 0, next: 0, last_activity: null, last_amount: 0 });
    const group = groups.get(key);
    const current = Number(detail.carryover_krw || 0) + Number(detail.current_krw || 0);
    group.rows.push(detail);
    group.current += current;
    group.next += Number(detail.next_krw || 0);
    if (["confirmed", "scheduled"].includes(detail.sales_stage)) group.confirmed_scheduled += current;
    else if (detail.sales_stage === "pipeline") group.pipeline += current;
    else group.undecided += current;
    const latest = forecastDetailLatest(detail);
    if (latest && (!group.last_activity || latest >= group.last_activity)) {
      group.last_activity = latest;
      group.last_amount = current;
    }
  });
  return [...groups.values()].sort((a, b) => b.current - a.current || a.label.localeCompare(b.label, "ko"));
}

function forecastDetailSummary(round, rows) {
  const official = Number(round?.business_units?.total?.current_expected || 0);
  const summary = { official, allocated: 0, confirmed_scheduled: 0, pipeline: 0, undecided: 0, next: 0, count: rows.length };
  rows.forEach(detail => {
    const current = Number(detail.carryover_krw || 0) + Number(detail.current_krw || 0);
    if (["confirmed", "scheduled"].includes(detail.sales_stage)) summary.confirmed_scheduled += current;
    else if (detail.sales_stage === "pipeline") summary.pipeline += current;
    else summary.undecided += current;
    summary.next += Number(detail.next_krw || 0);
  });
  summary.allocated = summary.confirmed_scheduled + summary.pipeline;
  summary.gap = official - summary.allocated;
  summary.coverage = official ? summary.allocated / official * 100 : 0;
  return summary;
}

function forecastDetailKpiMarkup(round, rows) {
  const summary = forecastDetailSummary(round, rows);
  return [
    { label: "공식 차수 예상", value: `${forecastRoundMillion(summary.official)}백만원`, note: "기존 차수 요약값 · 변경하지 않음" },
    { label: "상세 배분액", value: `${forecastRoundMillion(summary.allocated)}백만원`, note: `확정·예정 ${forecastRoundMillion(summary.confirmed_scheduled)} · 추진 ${forecastRoundMillion(summary.pipeline)}` },
    { label: "상세 배분율", value: `${formatNumber(summary.coverage, 1)}%`, note: `${formatNumber(summary.count)}건 · 현재 필터 적용` },
    { label: "미배분 차이", value: `${forecastRoundMillion(summary.gap)}백만원`, note: summary.gap < 0 ? "상세 배분액이 공식 요약을 초과합니다." : "엑셀 수식·누락 품목 확인용", style: "warning" },
  ].map(card => `<div class="forecast-detail-kpi ${card.style || ""}"><span>${card.label}</span><strong>${card.value}</strong><small>${escapeHtml(card.note)}</small></div>`).join("");
}

function forecastDetailGroupMarkup(groups) {
  if (!groups.length) return `<tr><td colspan="7"><div class="empty-state">조건에 맞는 상세자료가 없습니다.</div></td></tr>`;
  if (!groups.some(group => group.key === state.forecastDetailSelectedGroup)) state.forecastDetailSelectedGroup = groups[0].key;
  return groups.map((group, index) => `<tr data-detail-group-index="${index}" class="${group.key === state.forecastDetailSelectedGroup ? "selected" : ""}"><td><strong>${escapeHtml(group.label)}</strong><span class="table-sub">${[...new Set(group.rows.map(row => row.business_label))].filter(Boolean).join(" · ")}</span></td><td>${formatNumber(group.rows.length)}</td><td>${forecastRoundMillion(group.confirmed_scheduled)}</td><td>${forecastRoundMillion(group.pipeline)}</td><td>${forecastRoundMillion(group.undecided)}</td><td><strong>${forecastRoundMillion(group.current)}</strong></td><td>${forecastRoundMillion(group.next)}</td></tr>`).join("");
}

function forecastDetailInsightMarkup(group) {
  if (!group) return `<h4>선택 결과 없음</h4><p>조회 조건을 변경하거나 상세자료를 추가하세요.</p>`;
  return `<h4>${escapeHtml(group.label)}</h4><p>선택 카테고리 요약 · 이 메뉴에 입력된 자료만 반영</p><div class="forecast-detail-insight-grid">
    <div><span>당월 상세</span><strong>${forecastRoundMillion(group.current)}백만원</strong></div>
    <div><span>상세 건수</span><strong>${formatNumber(group.rows.length)}건</strong></div>
    <div><span>마지막 업무일</span><strong>${group.last_activity ? formatDate(group.last_activity) : "입력 없음"}</strong></div>
    <div><span>해당 금액</span><strong>${forecastRoundMillion(group.last_amount)}백만원</strong></div>
    <div><span>전월 매출액</span><strong>데이터 축적 중</strong></div>
    <div><span>전년 동월</span><strong>데이터 축적 중</strong></div>
    <div><span>주문 주기</span><strong>데이터 축적 중</strong></div>
    <div><span>연동 상태</span><strong>엑셀 독립 운영</strong></div>
  </div>`;
}

function forecastDetailRowMarkup(detail, canEdit) {
  const current = Number(detail.carryover_krw || 0) + Number(detail.current_krw || 0);
  const latest = forecastDetailLatest(detail);
  const expanded = canEdit && state.forecastDetailExpandedId === detail.id;
  const actions = canEdit ? `<div class="forecast-detail-actions"><button class="btn outline" type="button" data-detail-edit="${escapeHtml(detail.id)}">수정</button> <button class="btn subtle" type="button" data-detail-delete="${escapeHtml(detail.id)}">삭제</button></div>` : "—";
  const row = `<tr class="forecast-detail-data-row${expanded ? " expanded" : ""}" data-detail-row="${escapeHtml(detail.id)}" aria-expanded="${expanded ? "true" : "false"}"><td><span class="forecast-detail-stage ${escapeHtml(detail.sales_stage)}">${escapeHtml(detail.sales_stage_label)}</span><span class="forecast-management-badge ${escapeHtml(detail.management_type || "regular")}">${escapeHtml(detail.management_type_label || "일반")}</span></td><td><span class="forecast-detail-progress ${escapeHtml(detail.progress_status || "order_received")}">${escapeHtml(detail.progress_status_label || "오더접수")}</span></td><td>${escapeHtml(detail.business_label)}</td><td class="table-title">${escapeHtml(detail.country_name || "국가 미지정")}<span class="table-sub">${escapeHtml(detail.account_name || "거래처 미지정")}</span></td><td class="table-title">${escapeHtml(detail.item_name || "품목 미지정")}<span class="table-sub">${escapeHtml(detail.classification || "분류 미입력")}</span></td><td>${escapeHtml(detail.owner_name || "미지정")}<span class="table-sub">${escapeHtml(detail.timing_note || "시점 미입력")}</span></td><td><strong>${forecastRoundMillion(current)}백만원</strong><span class="table-sub">이월 ${forecastRoundMillion(detail.carryover_krw)} · 당월 ${forecastRoundMillion(detail.current_krw)}</span></td><td>${forecastRoundMillion(detail.next_krw)}백만원</td><td>${latest ? formatDate(latest) : "—"}</td><td>${actions}</td></tr>`;
  return row + (expanded ? forecastDetailInlineFormMarkup(detail) : "");
}

function forecastDetailOptionMarkup(options, selected) {
  return options.map(([value, label]) => `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`).join("");
}

function forecastDetailInlineFormMarkup(detail) {
  const value = field => escapeHtml(detail[field] ?? "");
  const salesStages = [["confirmed", "확정 매출"], ["scheduled", "예정 매출"], ["pipeline", "추진 매출"], ["undecided", "미정"]];
  const progressStatuses = [["order_received", "오더접수"], ["pi_issued", "PI발행"], ["payment_completed", "입금완료"], ["shipment_completed", "출고완료"]];
  const managementTypes = [["regular", "일반"], ["additional", "추가추진"], ["promotion", "프로모션"], ["expiring_inventory", "임박재고"]];
  const businessUnits = [["aesthetic", "에스테틱"], ["medical", "메디컬"], ["dental", "덴탈"]];
  const currencies = ["USD", "EUR", "JPY", "CNY", "KRW"].map(item => [item, item]);
  return `<tr class="forecast-detail-inline-row"><td colspan="10"><div class="forecast-detail-inline-form" data-detail-inline-form="${value("id")}">
    <div class="forecast-detail-inline-head"><div><strong>상세항목 수정</strong><span>${escapeHtml(detail.country_name || "국가 미지정")} · ${escapeHtml(detail.account_name || "거래처 미지정")} · ${escapeHtml(detail.item_name || "품목 미지정")}</span></div><button class="icon-btn" type="button" data-detail-collapse="${value("id")}" aria-label="상세항목 닫기">×</button></div>
    <div class="form-grid forecast-detail-inline-fields">
      <label>진행구분<select name="sales_stage" required>${forecastDetailOptionMarkup(salesStages, detail.sales_stage)}</select></label>
      <label>진행상태<select name="progress_status" required>${forecastDetailOptionMarkup(progressStatuses, detail.progress_status || "order_received")}</select></label>
      <label>관리유형<select name="management_type" required>${forecastDetailOptionMarkup(managementTypes, detail.management_type || "regular")}</select></label>
      <label>사업분야<select name="business_unit" required>${forecastDetailOptionMarkup(businessUnits, detail.business_unit)}</select></label>
      <label>통화<select name="currency">${forecastDetailOptionMarkup(currencies, detail.currency || "USD")}</select></label>
      <label>국가<input name="country_name" required maxlength="150" value="${value("country_name")}"></label>
      <label>거래처<input name="account_name" required maxlength="200" value="${value("account_name")}"></label>
      <label>품목<input name="item_name" required maxlength="200" value="${value("item_name")}"></label>
      <label>분류<input name="classification" maxlength="100" value="${value("classification")}"></label>
      <label>담당자<input name="owner_name" maxlength="100" value="${value("owner_name")}"></label>
      <label>매출 시점<input name="timing_note" maxlength="200" value="${value("timing_note")}"></label>
      <label>목표일<input name="target_date" type="date" value="${value("target_date")}"></label>
      <label>적용 환율<input name="applied_rate" type="number" min="0" step="0.0001" value="${value("applied_rate")}"><small class="forecast-detail-fx-note">수정 시 현재 상세자료의 원화만 자동 변경</small></label>
    </div>
    <div class="forecast-detail-amount-grid">
      <div><strong>목표금액</strong><label>외화<input name="plan_foreign" type="number" min="0" step="0.01" value="${value("plan_foreign")}"></label><label>원화<input name="plan_krw" type="number" min="0" step="1" value="${value("plan_krw")}"></label></div>
      <div><strong>전월 이월</strong><label>외화<input name="carryover_foreign" type="number" min="0" step="0.01" value="${value("carryover_foreign")}"></label><label>원화<input name="carryover_krw" type="number" min="0" step="1" value="${value("carryover_krw")}"></label></div>
      <div><strong>당월</strong><label>외화<input name="current_foreign" type="number" min="0" step="0.01" value="${value("current_foreign")}"></label><label>원화<input name="current_krw" type="number" min="0" step="1" value="${value("current_krw")}"></label></div>
      <div><strong>차월</strong><label>외화<input name="next_foreign" type="number" min="0" step="0.01" value="${value("next_foreign")}"></label><label>원화<input name="next_krw" type="number" min="0" step="1" value="${value("next_krw")}"></label></div>
    </div>
    <details class="forecast-detail-date-fields" open><summary>수주·수금·선적 일정</summary><div class="form-grid two">
      <label>수주/합의일<input name="order_agreed_at" type="date" value="${value("order_agreed_at")}"></label><label>PO 접수일<input name="po_received_at" type="date" value="${value("po_received_at")}"></label>
      <label>PI 발송일<input name="pi_sent_at" type="date" value="${value("pi_sent_at")}"></label><label>입금 예정일<input name="payment_expected_at" type="date" value="${value("payment_expected_at")}"></label>
      <label>입금 완료일<input name="payment_completed_at" type="date" value="${value("payment_completed_at")}"></label><label>선적 예정일<input name="shipment_expected_at" type="date" value="${value("shipment_expected_at")}"></label>
      <label>선적 완료일<input name="shipment_completed_at" type="date" value="${value("shipment_completed_at")}"></label><label>출고 완료일<input name="shipping_completed_at" type="date" value="${value("shipping_completed_at")}"></label>
    </div></details>
    <label>변동사유<input name="change_reason" maxlength="500" value="${value("change_reason")}" placeholder="거래처 일정 변경, 환율 변경, 신규 오더 추가 등"></label>
    <label>메모<textarea name="notes" rows="3" maxlength="3000">${value("notes")}</textarea></label>
    <p class="form-error" data-detail-inline-error role="alert" aria-live="assertive"></p>
    <div class="modal-actions"><button class="btn outline" type="button" data-detail-collapse="${value("id")}">취소</button><button class="btn primary" type="button" data-detail-inline-save="${value("id")}">변경사항 저장</button></div>
  </div></td></tr>`;
}

function renderForecastRoundDetails(round) {
  if (!round) return;
  const dimension = $("#forecastDetailDimension")?.value || "round";
  const dimensionLabels = { round: "차수별", item: "품목별", country: "국가별", account: "거래처별" };
  const rows = forecastDetailFilteredRows(round);
  const groups = forecastDetailGroups(round, rows, dimension);
  if (!groups.some(group => group.key === state.forecastDetailSelectedGroup)) state.forecastDetailSelectedGroup = groups[0]?.key || null;
  const selected = groups.find(group => group.key === state.forecastDetailSelectedGroup) || groups[0] || null;
  const visibleRows = selected ? selected.rows : [];
  $("#forecastDetailKpis").innerHTML = forecastDetailKpiMarkup(round, rows);
  $("#forecastDetailGroupTitle").textContent = `${round.round_label} · ${dimensionLabels[dimension]} 요약`;
  $("#forecastDetailGroupBody").innerHTML = forecastDetailGroupMarkup(groups);
  $("#forecastDetailInsight").innerHTML = forecastDetailInsightMarkup(selected);
  $("#forecastDetailListTitle").textContent = selected ? `${selected.label} 상세자료` : "상세자료";
  $("#forecastDetailCount").textContent = `${formatNumber(visibleRows.length)}건`;
  if (!visibleRows.some(detail => detail.id === state.forecastDetailExpandedId)) state.forecastDetailExpandedId = null;
  $("#forecastDetailBody").innerHTML = visibleRows.length ? visibleRows.map(detail => forecastDetailRowMarkup(detail, Boolean(round.permissions?.can_edit))).join("") : `<tr><td colspan="10"><div class="empty-state">선택한 기준의 상세자료가 없습니다.</div></td></tr>`;
  $("#forecastDetailAddBtn").classList.toggle("hidden", !round.permissions?.can_edit);
}

function renderForecastRounds() {
  const data = state.forecastRounds;
  if (!data) return;
  const rounds = data.rounds || [];
  const round = selectedForecastRound();
  const initializeButton = $("#forecastRoundInitializeBtn");
  initializeButton.classList.toggle("hidden", !data.can_initialize);
  $("#forecastRoundCards").innerHTML = rounds.length
    ? forecastRoundCardMarkup(rounds, round?.round_no)
    : `<div class="forecast-empty forecast-round-empty"><strong>${escapeHtml(data.forecast_month)} 차수 업무가 아직 시작되지 않았습니다.</strong><span>${data.can_initialize ? "해당 월 업무 시작을 눌러 미정·1·2·3차 입력공간을 만드세요." : "관리자 또는 매니저가 대상월 업무를 시작할 수 있습니다."}</span></div>`;
  $("#forecastRoundQualityNotes").innerHTML = (data.quality_notes || []).map(note => `<li>${escapeHtml(note)}</li>`).join("");
  $("#forecastRoundWorkflowForm").classList.toggle("hidden", !round);
  if (!round) {
    $("#forecastRoundSource").innerHTML = `<div><strong>${escapeHtml(data.forecast_month || $("#forecastRoundMonth").value)} 업무 미시작</strong><span>운영 중인 대상월: ${(data.available_months || []).map(value => escapeHtml(value)).join(", ") || "없음"}</span></div>`;
    $("#forecastRoundKpis").innerHTML = "";
    $("#forecastDetailKpis").innerHTML = "";
    $("#forecastDetailGroupBody").innerHTML = "";
    $("#forecastDetailBody").innerHTML = "";
    state.forecastRoundDirty = false;
    return;
  }
  state.forecastRoundSelected = round.round_no;
  const progress = round.progress || { completed: 0, required: 0 };
  $("#forecastRoundSource").innerHTML = `<div><strong>${escapeHtml(data.forecast_month)} · ${escapeHtml(round.round_label)} · ${round.as_of_date ? `${formatDate(round.as_of_date)} 기준` : "기준일 미입력"}</strong><span>초기 원본: ${escapeHtml(round.source_name || data.source_name || "직접 입력")} · 금액 입력 단위 ${escapeHtml(data.display_unit || "백만원")}</span></div><div class="definition-rates"><span>USD ${formatNumber(round.rates?.USD || 0, 2)}원</span><span>EUR ${formatNumber(round.rates?.EUR || 0, 2)}원</span><span>JPY ${formatNumber(round.rates?.JPY || 0, 4)}원</span><span>CNY ${formatNumber(round.rates?.CNY || 0, 2)}원</span><b>${escapeHtml(round.status_note)}</b></div>`;
  $("#forecastRoundKpis").innerHTML = forecastRoundKpiMarkup(round);
  $("#forecastRoundBusinessTitle").textContent = `${round.round_label} · 사업분야별 입력·현황`;
  $("#forecastRoundRate").textContent = round.as_of_date ? `${formatDate(round.as_of_date)} 기준` : "기준일 미입력";
  $("#forecastRoundBusinessBody").innerHTML = forecastRoundBusinessMarkup(data, round);
  $("#forecastRoundChecklist").innerHTML = forecastRoundChecklistMarkup(round);
  $("#forecastRoundComposition").innerHTML = forecastRoundCompositionMarkup(round);
  $("#forecastRoundComparisonBody").innerHTML = forecastRoundComparisonMarkup(data);
  renderForecastCloseDashboard(round);
  renderForecastRoundDetails(round);
  $("#forecastRoundAsOfDate").value = round.as_of_date || "";
  $("#forecastRoundUsd").value = round.rates?.USD || "";
  $("#forecastRoundEur").value = round.rates?.EUR || "";
  $("#forecastRoundJpy").value = round.rates?.JPY || "";
  $("#forecastRoundCny").value = round.rates?.CNY || "";
  $("#forecastRoundNotes").value = round.notes || "";
  const canEdit = Boolean(round.permissions?.can_edit);
  ["#forecastRoundAsOfDate", "#forecastRoundUsd", "#forecastRoundEur", "#forecastRoundJpy", "#forecastRoundCny", "#forecastRoundNotes"].forEach(selector => { $(selector).disabled = !canEdit; });
  $("#forecastRoundWorkflowForm").classList.toggle("is-locked", !canEdit);
  const lockbar = $("#forecastRoundLockState").parentElement;
  lockbar.classList.toggle("locked", round.status === "confirmed");
  $("#forecastRoundLockState").innerHTML = round.status === "confirmed"
    ? `<strong>${escapeHtml(round.round_label)} 확정 · 수정 잠금</strong><span>${escapeHtml(round.confirmed_by_name || "관리자")} · ${formatDate(round.confirmed_at)} 확정</span>`
    : `<strong>${escapeHtml(round.round_label)} 작성 중 · 체크 ${progress.completed}/${progress.required}</strong><span>${round.permissions?.can_edit ? "입력 후 임시 저장하고, 검토가 끝나면 확정하세요." : "조회 권한으로 접속했습니다."}</span>`;
  $("#forecastRoundSaveBtn").classList.toggle("hidden", !round.permissions?.can_edit);
  $("#forecastRoundConfirmBtn").classList.toggle("hidden", !round.permissions?.can_confirm);
  $("#forecastRoundReopenBtn").classList.toggle("hidden", !round.permissions?.can_reopen);
  $("#forecastRoundCopyNextBtn").classList.toggle("hidden", !(round.permissions?.can_reopen && Number(round.round_no) < 3));
  setActionMessage("#forecastRoundActionMessage", "");
}

function recalculateForecastRoundInputs() {
  const totals = { plan: 0, initial_fcst: 0, first_expected: 0, carryover: 0, current_month: 0, pipeline: 0, next_month: 0, next_pipeline: 0 };
  $$('[data-round-unit]', $("#forecastRoundBusinessBody")).forEach(row => {
    const values = {};
    $$('[data-round-field]', row).forEach(input => {
      values[input.dataset.roundField] = Math.max(0, Number(input.value || 0));
      totals[input.dataset.roundField] += values[input.dataset.roundField];
    });
    const expected = values.carryover + values.current_month + values.pipeline;
    const variance = expected - values.plan;
    $('[data-calc="current_expected"]', row).textContent = formatNumber(expected, 1);
    const varianceNode = $('[data-calc="plan_variance"]', row);
    varianceNode.textContent = `${variance > 0 ? "+" : ""}${formatNumber(variance, 1)}`;
    varianceNode.classList.toggle("negative", variance < 0);
    varianceNode.classList.toggle("positive", variance >= 0);
  });
  totals.current_expected = totals.carryover + totals.current_month + totals.pipeline;
  totals.plan_variance = totals.current_expected - totals.plan;
  Object.entries(totals).forEach(([field, value]) => {
    const node = $(`[data-total-field="${field}"]`, $("#forecastRoundBusinessBody"));
    if (!node) return;
    node.textContent = `${field === "plan_variance" && value > 0 ? "+" : ""}${formatNumber(value, 1)}`;
    if (field === "plan_variance") {
      node.classList.toggle("negative", value < 0);
      node.classList.toggle("positive", value >= 0);
    }
  });
  $$('.forecast-round-check-item', $("#forecastRoundChecklist")).forEach(item => item.classList.toggle("completed", Boolean($("input[type='checkbox']", item)?.checked)));
}

function forecastRoundWorkflowBody() {
  const entries = {};
  $$('[data-round-unit]', $("#forecastRoundBusinessBody")).forEach(row => {
    const values = {};
    $$('[data-round-field]', row).forEach(input => { values[input.dataset.roundField] = Number(input.value || 0) * 1000000; });
    entries[row.dataset.roundUnit] = values;
  });
  const checklist = $$('[data-check-key]', $("#forecastRoundChecklist")).map(input => ({
    check_key: input.dataset.checkKey,
    completed: input.checked,
    note: $(`[data-check-note="${input.dataset.checkKey}"]`, $("#forecastRoundChecklist"))?.value || "",
  }));
  return {
    as_of_date: $("#forecastRoundAsOfDate").value,
    rates: { USD: Number($("#forecastRoundUsd").value || 0), EUR: Number($("#forecastRoundEur").value || 0), JPY: Number($("#forecastRoundJpy").value || 0), CNY: Number($("#forecastRoundCny").value || 0) },
    notes: $("#forecastRoundNotes").value,
    entries,
    checklist,
  };
}

async function loadForecastRoundOverview(preferredRound = null) {
  try {
    const data = await api(forecastRoundOverviewApiPath());
    state.forecastRounds = data;
    state.forecastRoundSelected = preferredRound ?? data.selected_round ?? data.rounds?.[0]?.round_no ?? null;
    state.forecastRoundDirty = false;
    renderForecastRounds();
  } catch (error) {
    toast(error.message, "error");
  }
}

const forecastDetailAmountFields = ["plan_foreign", "plan_krw", "carryover_foreign", "carryover_krw", "current_foreign", "current_krw", "next_foreign", "next_krw", "applied_rate"];
const forecastDetailDateFields = ["order_agreed_at", "po_received_at", "pi_sent_at", "payment_expected_at", "payment_completed_at", "shipment_expected_at", "shipment_completed_at", "shipping_completed_at", "target_date"];
const forecastDetailTextFields = ["sales_stage", "progress_status", "management_type", "business_unit", "classification", "country_name", "account_name", "item_name", "owner_name", "timing_note", "currency", "change_reason", "notes"];
const forecastDetailFxPairs = [["plan_foreign", "plan_krw"], ["carryover_foreign", "carryover_krw"], ["current_foreign", "current_krw"], ["next_foreign", "next_krw"]];

function recalculateForecastDetailKrw(container) {
  const rateInput = container?.querySelector('[name="applied_rate"]');
  if (!rateInput || rateInput.value.trim() === "") return;
  const rate = Number(rateInput.value);
  if (!Number.isFinite(rate) || rate < 0) return;
  forecastDetailFxPairs.forEach(([foreignField, krwField]) => {
    const foreignInput = container.querySelector(`[name="${foreignField}"]`);
    const krwInput = container.querySelector(`[name="${krwField}"]`);
    const foreignAmount = Number(foreignInput?.value || 0);
    if (!krwInput || !Number.isFinite(foreignAmount) || foreignAmount === 0) return;
    krwInput.value = String(Math.round(foreignAmount * rate));
    krwInput.classList.add("fx-auto-updated");
    window.setTimeout(() => krwInput.classList.remove("fx-auto-updated"), 700);
  });
}

function handleForecastDetailRateInput(event) {
  if (event.target?.name !== "applied_rate") return;
  const container = event.target.closest("[data-detail-inline-form], #forecastDetailForm");
  recalculateForecastDetailKrw(container);
}

function openForecastDetailDialog(detail = null) {
  const round = selectedForecastRound();
  if (!round?.permissions?.can_edit) return;
  state.editingForecastDetail = detail;
  const form = $("#forecastDetailForm");
  form.reset();
  form.elements.id.value = detail?.id || "";
  $("#forecastDetailFormError").textContent = "";
  $("#forecastDetailDialogTitle").textContent = detail ? "상세자료 수정" : "상세자료 추가";
  $("#forecastDetailDialogRound").textContent = `${round.forecast_month} · ${round.round_label} · ${round.status === "draft" ? "작성 중" : "확정"}`;
  const defaults = { sales_stage: "pipeline", progress_status: "order_received", management_type: "regular", business_unit: "dental", item_name: "품목 미지정", currency: "USD" };
  forecastDetailTextFields.forEach(field => {
    if (form.elements[field]) form.elements[field].value = detail?.[field] ?? defaults[field] ?? "";
  });
  forecastDetailAmountFields.forEach(field => { form.elements[field].value = detail?.[field] || ""; });
  forecastDetailDateFields.forEach(field => { form.elements[field].value = detail?.[field] || ""; });
  $("#forecastDetailDialog").showModal();
  window.setTimeout(() => form.elements.country_name.focus(), 0);
}

function forecastDetailFormBody(form = $("#forecastDetailForm")) {
  const data = form instanceof HTMLFormElement
    ? Object.fromEntries(new FormData(form).entries())
    : Object.fromEntries($$("[name]", form).map(control => [control.name, control.value]));
  delete data.id;
  forecastDetailAmountFields.forEach(field => { data[field] = Number(data[field] || 0); });
  return data;
}

async function saveInlineForecastRoundDetail(form) {
  if (!form) return;
  const round = selectedForecastRound();
  if (!round?.permissions?.can_edit) return;
  const id = form.dataset.detailInlineForm;
  const button = form.querySelector("[data-detail-inline-save]");
  const errorNode = form.querySelector("[data-detail-inline-error]");
  button.disabled = true;
  errorNode.textContent = "";
  try {
    const data = await api(`/api/forecast-rounds/${encodeURIComponent(round.forecast_month)}/${round.round_no}/details/${encodeURIComponent(id)}`, { method: "PUT", body: forecastDetailFormBody(form) });
    toast(data.message);
    state.forecastDetailExpandedId = id;
    await loadForecastRoundOverview(round.round_no);
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function saveForecastRoundDetail(event) {
  event.preventDefault();
  const round = selectedForecastRound();
  if (!round?.permissions?.can_edit) return;
  const id = $("#forecastDetailForm").elements.id.value;
  const button = $("#forecastDetailSubmitBtn");
  button.disabled = true;
  $("#forecastDetailFormError").textContent = "";
  try {
    const path = `/api/forecast-rounds/${encodeURIComponent(round.forecast_month)}/${round.round_no}/details${id ? `/${encodeURIComponent(id)}` : ""}`;
    const data = await api(path, { method: id ? "PUT" : "POST", body: forecastDetailFormBody() });
    $("#forecastDetailDialog").close();
    state.editingForecastDetail = null;
    toast(data.message);
    await loadForecastRoundOverview(round.round_no);
  } catch (error) {
    $("#forecastDetailFormError").textContent = error.message;
  } finally { button.disabled = false; }
}

async function deleteForecastRoundDetail(detail) {
  const round = selectedForecastRound();
  if (!round?.permissions?.can_edit || !detail) return;
  if (!window.confirm(`${detail.account_name || "선택 자료"} · ${detail.item_name || "품목 미지정"} 상세자료를 삭제할까요? 변경 이력은 보존됩니다.`)) return;
  try {
    const data = await api(`/api/forecast-rounds/${encodeURIComponent(round.forecast_month)}/${round.round_no}/details/${encodeURIComponent(detail.id)}`, { method: "DELETE" });
    toast(data.message);
    await loadForecastRoundOverview(round.round_no);
  } catch (error) { toast(error.message, "error"); }
}

function handleForecastDetailAction(event) {
  const round = selectedForecastRound();
  if (!round) return;
  const edit = event.target.closest("[data-detail-edit]");
  const remove = event.target.closest("[data-detail-delete]");
  const collapse = event.target.closest("[data-detail-collapse]");
  const save = event.target.closest("[data-detail-inline-save]");
  const row = event.target.closest("[data-detail-row]");
  const id = edit?.dataset.detailEdit || remove?.dataset.detailDelete || collapse?.dataset.detailCollapse || save?.dataset.detailInlineSave || row?.dataset.detailRow;
  if (!id || (event.target.closest("input, select, textarea, label") && !edit && !remove && !collapse)) return;
  const detail = (round.details || []).find(item => item.id === id);
  if (save) {
    saveInlineForecastRoundDetail(save.closest("[data-detail-inline-form]"));
    return;
  }
  if (remove) {
    deleteForecastRoundDetail(detail);
    return;
  }
  if (collapse) {
    state.forecastDetailExpandedId = null;
  } else if ((edit || row) && round.permissions?.can_edit) {
    state.forecastDetailExpandedId = state.forecastDetailExpandedId === id && !edit ? null : id;
  }
  renderForecastRoundDetails(round);
  if (state.forecastDetailExpandedId) window.setTimeout(() => $(`[data-detail-inline-form="${state.forecastDetailExpandedId}"] input[name="country_name"]`)?.focus(), 0);
}

async function initializeForecastRoundWorkflows() {
  const month = $("#forecastRoundMonth").value;
  if (!window.confirm(`${month} 미정·1·2·3차 업무 입력공간을 만들까요?`)) return;
  const button = $("#forecastRoundInitializeBtn");
  button.disabled = true;
  try {
    const data = await api("/api/forecast-rounds/initialize", { method: "POST", body: { forecast_month: month } });
    toast(data.message);
    await loadForecastRoundOverview(0);
  } catch (error) { toast(error.message, "error"); }
  finally { button.disabled = false; }
}

async function saveForecastRoundWorkflow(silent = false) {
  const round = selectedForecastRound();
  if (!round?.permissions?.can_edit) return false;
  const button = $("#forecastRoundSaveBtn");
  button.disabled = true;
  setActionMessage("#forecastRoundActionMessage", "저장 중...");
  try {
    const data = await api(`/api/forecast-rounds/${encodeURIComponent(round.forecast_month)}/${round.round_no}`, { method: "PUT", body: forecastRoundWorkflowBody() });
    state.forecastRoundDirty = false;
    await loadForecastRoundOverview(round.round_no);
    if (!silent) toast(data.message);
    setActionMessage("#forecastRoundActionMessage", data.message);
    return true;
  } catch (error) {
    const detail = Array.isArray(error.detail) ? ` · ${error.detail.join(", ")}` : "";
    setActionMessage("#forecastRoundActionMessage", `${error.message}${detail}`, "error");
    toast(error.message, "error");
    return false;
  } finally { button.disabled = false; }
}

async function confirmForecastRoundWorkflow() {
  let round = selectedForecastRound();
  if (!round?.permissions?.can_confirm) return;
  if (!window.confirm(`${round.round_label} 내용을 확정하면 더 이상 수정할 수 없습니다. 확정할까요?`)) return;
  if (state.forecastRoundDirty && !(await saveForecastRoundWorkflow(true))) return;
  round = selectedForecastRound();
  const button = $("#forecastRoundConfirmBtn");
  button.disabled = true;
  try {
    const data = await api(`/api/forecast-rounds/${encodeURIComponent(round.forecast_month)}/${round.round_no}/confirm`, { method: "POST", body: {} });
    toast(data.message);
    await loadForecastRoundOverview(round.round_no);
  } catch (error) {
    const detail = Array.isArray(error.detail) ? ` · 미완료: ${error.detail.join(", ")}` : "";
    setActionMessage("#forecastRoundActionMessage", `${error.message}${detail}`, "error");
    toast(error.message, "error");
  } finally { button.disabled = false; }
}

async function reopenForecastRoundWorkflow() {
  const round = selectedForecastRound();
  if (!round?.permissions?.can_reopen) return;
  const reason = window.prompt(`${round.round_label} 확정을 재개방하는 사유를 입력하세요.`);
  if (reason === null) return;
  const button = $("#forecastRoundReopenBtn");
  button.disabled = true;
  try {
    const data = await api(`/api/forecast-rounds/${encodeURIComponent(round.forecast_month)}/${round.round_no}/reopen`, { method: "POST", body: { reason } });
    toast(data.message);
    await loadForecastRoundOverview(round.round_no);
  } catch (error) { setActionMessage("#forecastRoundActionMessage", error.message, "error"); toast(error.message, "error"); }
  finally { button.disabled = false; }
}

async function copyForecastRoundWorkflowNext() {
  const round = selectedForecastRound();
  if (!round || Number(round.round_no) >= 3) return;
  if (!window.confirm(`${round.round_label} 확정값을 ${Number(round.round_no) + 1}차로 이관할까요? 기존 입력값이 있으면 이관되지 않습니다.`)) return;
  const button = $("#forecastRoundCopyNextBtn");
  button.disabled = true;
  try {
    const data = await api(`/api/forecast-rounds/${encodeURIComponent(round.forecast_month)}/${round.round_no}/copy-next`, { method: "POST", body: {} });
    toast(data.message);
    await loadForecastRoundOverview(Number(round.round_no) + 1);
  } catch (error) { setActionMessage("#forecastRoundActionMessage", error.message, "error"); toast(error.message, "error"); }
  finally { button.disabled = false; }
}

async function loadForecast() {
  try {
    state.forecast = await api(forecastApiPath());
    renderForecast();
    renderOverviewForecast();
    if ($("#mapMonth").value === state.forecast.forecast_month) await loadGlobalMap();
  } catch (error) { toast(error.message, "error"); }
}

function openForecastCycleDialog() {
  const form = $("#forecastCycleForm");
  form.reset();
  $("#forecastCycleError").textContent = "";
  const cycle = state.forecast?.cycle;
  form.elements.forecast_month.value = state.forecast?.forecast_month || $("#forecastMonth").value || operationalForecastMonth();
  form.elements.round_no.value = cycle?.round_no || (state.forecast?.cycles?.length ? Math.min(3, state.forecast.cycles.length + 1) : 1);
  form.elements.as_of_date.value = cycle?.as_of_date || todayIso();
  form.elements.status.value = cycle?.status || "open";
  form.elements.usd_krw.value = cycle?.rates?.USD || "";
  form.elements.eur_krw.value = cycle?.rates?.EUR || "";
  form.elements.jpy_krw.value = cycle?.rates?.JPY || "";
  form.elements.cny_krw.value = cycle?.rates?.CNY || "";
  if (!cycle) populateForecastCycleRates(false);
  $("#forecastCycleDialogTitle").textContent = cycle
    ? `${cycle.round_label} 기준 수정`
    : state.pendingForecastEntryAfterCycle
      ? `${form.elements.forecast_month.value} ${form.elements.round_no.value}차 FCST 시작`
      : "FCST 차수·기준환율 설정";
  $("#forecastCycleDialog").showModal();
}

function populateForecastCycleRates(notify = true) {
  const rows = state.exchangeRates?.rates || [];
  if (!rows.length) {
    if (notify) toast("오늘 기준환율을 불러오지 못했습니다. 직접 입력해 주세요.", "error");
    return false;
  }
  const form = $("#forecastCycleForm");
  rows.forEach(row => { if (form.elements[`${row.currency.toLowerCase()}_krw`]) form.elements[`${row.currency.toLowerCase()}_krw`].value = Number(row.krw_rate).toFixed(2); });
  if (notify) toast(`${rows[0].rate_date} 기준환율을 입력했습니다.`);
  return true;
}

function useDailyFxRates() {
  populateForecastCycleRates(true);
}

async function saveForecastCycle(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#forecastCycleSubmitBtn");
  const errorNode = $("#forecastCycleError");
  errorNode.textContent = "";
  button.disabled = true;
  try {
    const body = Object.fromEntries(new FormData(form).entries());
    body.round_no = Number(body.round_no);
    const result = await api("/api/forecast/cycles", { method: "POST", body });
    const openEntryAfterSave = state.pendingForecastEntryAfterCycle;
    $("#forecastCycleDialog").close();
    $("#forecastMonth").value = body.forecast_month;
    $("#forecastRound").value = String(body.round_no);
    await loadForecast();
    await loadHistory();
    toast(result.message);
    if (openEntryAfterSave) {
      state.pendingForecastEntryAfterCycle = false;
      if (state.forecast?.cycle?.status === "open") openForecastItemDialog();
      else toast("FCST가 마감 상태로 저장되어 항목 등록창을 열지 않았습니다.", "error");
    }
  } catch (error) { errorNode.textContent = error.message; }
  finally { button.disabled = false; }
}

async function copyForecastRound() {
  const cycle = state.forecast?.cycle;
  if (!cycle) return toast("복사할 FCST 차수를 선택하세요.", "error");
  confirmAction("다음 차수 생성", `${cycle.round_label}의 현재 FCST 항목을 ${Number(cycle.round_no) + 1}차 가마감으로 복사하시겠습니까? 복사 후 각 항목을 수정해 차수 간 변동을 남길 수 있습니다.`, async () => {
    const result = await api(`/api/forecast/cycles/${cycle.id}/copy-next`, { method: "POST" });
    $("#forecastRound").value = String(Number(cycle.round_no) + 1);
    await loadForecast();
    await loadHistory();
    toast(result.message);
  });
}

function canManageForecastCycles() {
  return Boolean(state.me && ["admin", "manager"].includes(state.me.role));
}

function handleForecastAdd() {
  const cycle = state.forecast?.cycle;
  if (!cycle) {
    if (!canManageForecastCycles()) {
      return toast("관리자가 이 월의 FCST 차수와 기준환율을 먼저 설정해야 합니다.", "error");
    }
    state.pendingForecastEntryAfterCycle = true;
    openForecastCycleDialog();
    toast("기준환율과 차수를 저장하면 FCST 등록창이 바로 이어서 열립니다.");
    return;
  }
  if (cycle.status === "closed") {
    const message = canManageForecastCycles() && Number(cycle.round_no) < 3
      ? "마감된 차수입니다. ‘다음 차수 복사’를 먼저 실행한 뒤 등록해 주세요."
      : "마감된 차수에는 FCST를 등록할 수 없습니다.";
    return toast(message, "error");
  }
  openForecastItemDialog();
}

function openForecastItemDialog(item = null) {
  const cycle = state.forecast?.cycle;
  if (!cycle) return toast("관리자가 FCST 차수와 기준환율을 먼저 설정해야 합니다.", "error");
  if (cycle.status === "closed") return toast("마감된 차수에는 FCST를 등록하거나 수정할 수 없습니다.", "error");
  state.editingForecastItem = item;
  const form = $("#forecastItemForm");
  form.reset();
  $("#forecastItemError").textContent = "";
  form.elements.id.value = item?.id || "";
  form.elements.cycle_id.value = cycle.id;
  form.elements.account_id.innerHTML = accountOptions(item?.account_id || "");
  form.elements.owner_id.innerHTML = ownerOptions(item?.owner_id || state.me?.id);
  form.elements.title.value = item?.title || "";
  form.elements.account_id.value = item?.account_id || "";
  form.elements.item_name.value = item?.item_name || "";
  form.elements.business_unit.value = item?.business_unit || "dental";
  form.elements.stage.value = item?.stage || "sales_activity";
  form.elements.confidence.value = item?.confidence ?? forecastStageDefaults.sales_activity;
  form.elements.expected_ship_date.value = item?.expected_ship_date || "";
  form.elements.foreign_amount.value = item?.foreign_amount ?? "";
  form.elements.currency.value = item?.currency || "USD";
  form.elements.owner_id.value = item?.owner_id || state.me?.id || "";
  form.elements.notes.value = item?.notes || "";
  form.elements.owner_id.disabled = state.me?.role === "editor";
  $("#forecastItemDialogTitle").textContent = item ? "FCST 수정" : "FCST 등록";
  $("#forecastItemCycleNotice").innerHTML = `<strong>${escapeHtml(cycle.forecast_month)} · ${escapeHtml(cycle.round_label)}</strong><span>USD ${formatNumber(cycle.rates.USD, 2)}원 · EUR ${formatNumber(cycle.rates.EUR, 2)}원 · CNY ${formatNumber(cycle.rates.CNY, 2)}원</span>`;
  renderForecastConversionPreview();
  $("#forecastItemDialog").showModal();
}

function handleForecastStageChange() {
  const form = $("#forecastItemForm");
  form.elements.confidence.value = forecastStageDefaults[form.elements.stage.value] ?? form.elements.confidence.value;
  renderForecastConversionPreview();
}

function renderForecastConversionPreview() {
  const form = $("#forecastItemForm");
  const cycle = state.forecast?.cycle;
  if (!cycle) return;
  const currency = form.elements.currency.value || "USD";
  const amount = Number(form.elements.foreign_amount.value || 0);
  const rate = Number(cycle.rates?.[currency] || (currency === "KRW" ? 1 : 0));
  const confidence = Number(form.elements.confidence.value || 0);
  const krw = amount * rate;
  $("#forecastConversionPreview").innerHTML = `<div><span>입력 외화</span><strong>${formatMoney(amount, currency)}</strong></div><div><span>FCST 원화 환산</span><strong>${formatMoney(krw)}</strong><small>${currency} 1 = ₩${formatNumber(rate, 2)}</small></div><div><span>가중 FCST</span><strong>${formatMoney(krw * confidence / 100)}</strong><small>확률 ${formatNumber(confidence)}%</small></div>`;
}

async function saveForecastItem(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const id = data.get("id");
  const account = state.records.find(row => row.id === data.get("account_id"));
  const body = Object.fromEntries(data.entries());
  body.account_name = account?.title || "";
  body.confidence = Number(body.confidence);
  body.foreign_amount = Number(body.foreign_amount);
  const button = $("#forecastItemSubmitBtn");
  const errorNode = $("#forecastItemError");
  button.disabled = true;
  errorNode.textContent = "";
  try {
    const result = await api(id ? `/api/forecast/items/${id}` : "/api/forecast/items", { method: id ? "PATCH" : "POST", body });
    $("#forecastItemDialog").close();
    await loadForecast();
    await loadHistory();
    toast(result.message);
  } catch (error) { errorNode.textContent = error.message; }
  finally { button.disabled = false; }
}

function handleForecastAction(event) {
  const button = event.target.closest("[data-forecast-action]");
  if (!button) return;
  const item = state.forecast?.items?.find(row => row.id === button.dataset.id);
  if (!item) return;
  if (button.dataset.forecastAction === "promotion-source") {
    const promotion = state.records.find(row => row.id === item.source_id && row.entity_type === "promotion");
    if (promotion) focusRecord(promotion);
    else { switchView("promotion"); $("#recordSearch").value = item.title; renderRecordTable(); }
    return;
  }
  if (button.dataset.forecastAction === "edit") openForecastItemDialog(item);
  if (button.dataset.forecastAction === "carryover") {
    const nextMonth = shiftMonth(state.forecast.forecast_month, 1);
    confirmAction("다음 달 FCST 이월", `“${item.title}”을 ${nextMonth} 1차 FCST로 이월하시겠습니까? 현재 월에는 이월 처리 이력이 남고, 다음 달에는 “${state.forecast.forecast_month} 이월”로 표시됩니다.`, async () => {
      const result = await api(`/api/forecast/items/${item.id}/carryover`, { method: "POST", body: { target_month: nextMonth, target_round: 1 } });
      await loadForecast();
      await loadHistory();
      toast(result.message);
    });
  }
  if (button.dataset.forecastAction === "delete") confirmAction("FCST 삭제", `“${item.title}” FCST를 삭제하시겠습니까? 삭제 전 내용은 변경 이력에 남습니다.`, async () => {
    const result = await api(`/api/forecast/items/${item.id}`, { method: "DELETE" });
    await loadForecast();
    await loadHistory();
    toast(result.message);
  });
}

function decodeTopologyArc(topology, index, cache) {
  const arcIndex = index < 0 ? ~index : index;
  if (!cache.has(arcIndex)) {
    const transform = topology.transform || { scale: [1, 1], translate: [0, 0] };
    let x = 0;
    let y = 0;
    const points = (topology.arcs?.[arcIndex] || []).map(([dx, dy]) => {
      x += dx;
      y += dy;
      return [x * transform.scale[0] + transform.translate[0], y * transform.scale[1] + transform.translate[1]];
    });
    cache.set(arcIndex, points);
  }
  const points = cache.get(arcIndex) || [];
  return index < 0 ? [...points].reverse() : points;
}

function topologyRing(topology, arcIndexes, cache) {
  const points = [];
  (arcIndexes || []).forEach((index, position) => {
    const arc = decodeTopologyArc(topology, index, cache);
    points.push(...(position ? arc.slice(1) : arc));
  });
  return points;
}

function projectMapPoint([longitude, latitude]) {
  return [((longitude + 180) / 360) * 1000, ((85 - latitude) / 145) * 480];
}

function shapeFromGeometry(topology, geometry, cache) {
  const polygons = geometry.type === "Polygon" ? [geometry.arcs] : geometry.type === "MultiPolygon" ? geometry.arcs : [];
  let path = "";
  let bestBounds = null;
  polygons.forEach(polygon => {
    (polygon || []).forEach((ringIndexes, ringIndex) => {
      const projected = topologyRing(topology, ringIndexes, cache).map(projectMapPoint);
      if (projected.length < 3) return;
      path += `M${projected.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join("L")}Z`;
      if (ringIndex === 0) {
        const xs = projected.map(point => point[0]);
        const ys = projected.map(point => point[1]);
        const bounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
        bounds.area = Math.max(0, bounds.maxX - bounds.minX) * Math.max(0, bounds.maxY - bounds.minY);
        if (!bestBounds || bounds.area > bestBounds.area) bestBounds = bounds;
      }
    });
  });
  return {
    id: String(geometry.id || "").padStart(3, "0"),
    name: geometry.properties?.name || "",
    path,
    cx: bestBounds ? (bestBounds.minX + bestBounds.maxX) / 2 : 0,
    cy: bestBounds ? (bestBounds.minY + bestBounds.maxY) / 2 : 0,
  };
}

function buildWorldShapes() {
  if (state.worldShapes) return state.worldShapes;
  const topology = state.worldTopology;
  const geometries = topology?.objects?.countries?.geometries || [];
  const cache = new Map();
  state.worldShapes = geometries
    .filter(geometry => String(geometry.id).padStart(3, "0") !== "010")
    .map(geometry => shapeFromGeometry(topology, geometry, cache))
    .filter(shape => shape.path);
  return state.worldShapes;
}

function mapCountryTone(country) {
  if (!country) return "none";
  if (Number(country.erp_actual_krw)) return "actual";
  if (Number(country.forecast_total_krw)) return "forecast";
  if (Number(country.pipeline_count) || Number(country.open_actions)) return "pipeline";
  return "account";
}

function mapCountryById(mapId) {
  return state.mapData?.countries?.find(country => country.map_id === String(mapId)) || null;
}

function renderMapSummary() {
  const totals = state.mapData?.totals || {};
  $("#mapSummary").innerHTML = [
    ["활동 국가", `${formatNumber(totals.country_count)}개국`, `거래처 ${formatNumber(totals.account_count)}개`],
    ["선택월 전체 FCST", formatMoney(totals.forecast_total_krw), `지도 매칭 ${formatMoney(totals.forecast_mapped_krw)}`],
    ["ERP 확정매출", formatMoney(totals.erp_actual_krw), `지도 매칭 ${formatMoney(totals.erp_mapped_krw)}`],
    ["미결 후속조치", `${formatNumber(totals.open_actions)}건`, `기한 초과 ${formatNumber(totals.overdue_actions)}건`],
  ].map(([label, value, note]) => `<div><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join("");
}

function mapDetailList(title, rows, renderRow, empty) {
  return `<section class="map-detail-section"><h4>${escapeHtml(title)}<b>${formatNumber(rows.length)}</b></h4><div>${rows.length ? rows.map(renderRow).join("") : `<p>${escapeHtml(empty)}</p>`}</div></section>`;
}

function renderMapCountryDetail(country) {
  const container = $("#mapCountryDetail");
  if (!country) {
    container.innerHTML = '<div class="map-detail-empty"><strong>국가를 선택하세요.</strong><span>지도의 색상 국가나 표시점을 누르면 상세 내역이 나옵니다.</span></div>';
    return;
  }
  const stages = country.stage_counts || {};
  container.innerHTML = `
    <div class="map-detail-head"><div><p>${escapeHtml(country.region || "권역 미지정")}</p><h3>${escapeHtml(country.label)}</h3><span>${escapeHtml(country.name)}</span></div><span class="map-detail-status ${mapCountryTone(country)}">${Number(country.erp_actual_krw) ? "ERP 확정" : Number(country.forecast_total_krw) ? "FCST 진행" : "영업 추진"}</span></div>
    <div class="map-detail-kpis">
      <div><span>전체 FCST</span><strong>${formatMoney(country.forecast_total_krw)}</strong><small>가중 ${formatMoney(country.forecast_weighted_krw)}</small></div>
      <div><span>ERP 확정</span><strong>${formatMoney(country.erp_actual_krw)}</strong><small>출고 ${formatNumber(country.shipment_count)}건</small></div>
      <div><span>거래처·파이프라인</span><strong>${formatNumber(country.account_count)}·${formatNumber(country.pipeline_count)}</strong><small>업체·진행 기회</small></div>
      <div><span>미결·지연</span><strong>${formatNumber(country.open_actions)}·${formatNumber(country.overdue_actions)}</strong><small>후속조치·기한 초과</small></div>
    </div>
    <div class="map-stage-chips"><span>일반 영업 ${formatNumber(stages.sales_activity)}건</span><span>PI ${formatNumber(stages.pi_received)}건</span><span>수금 ${formatNumber(stages.payment_received)}건</span></div>
    <div class="map-detail-actions">
      <button type="button" data-country-action="account">거래처 열기</button>
      <button type="button" data-country-action="monthly_sales_fcst">월별 매출 FCST 열기</button>
      <button type="button" data-country-action="sales">ERP 매출 열기</button>
    </div>
    <div class="map-detail-lists">
      ${mapDetailList("거래처", country.accounts || [], row => `<button type="button" data-map-record-id="${escapeHtml(row.id)}"><strong>${escapeHtml(row.title)}</strong><span>${escapeHtml(row.owner_name)} · ${escapeHtml(statusLabels[row.status] || row.status)}</span></button>`, "등록된 거래처가 없습니다.")}
      ${mapDetailList("FCST", country.forecast_items || [], row => `<button type="button" data-country-action="monthly_sales_fcst"><strong>${escapeHtml(row.account_name || row.title)}</strong><span>${escapeHtml(row.stage_label)} · ${formatMoney(row.krw_amount)}</span></button>`, "선택월 FCST가 없습니다.")}
      ${mapDetailList("미결 후속조치", country.actions || [], row => `<button type="button" data-map-record-id="${escapeHtml(row.id)}"><strong>${escapeHtml(row.title)}</strong><span>${escapeHtml(row.owner_name)}${row.due_date ? ` · ${escapeHtml(formatDate(row.due_date))}` : ""}</span></button>`, "미결 업무가 없습니다.")}
      ${mapDetailList("ERP 거래처 매출", country.erp_partners || [], row => `<button type="button" data-erp-partner="${escapeHtml(row.partner_name)}"><strong>${escapeHtml(row.partner_name)}</strong><span>${formatMoney(row.krw_supply)}</span></button>`, "선택월 ERP 출고가 없습니다.")}
    </div>`;
}

function renderGlobalMap(error = null) {
  const container = $("#worldMap");
  if (error || !state.mapData || !state.worldTopology) {
    container.innerHTML = `<div class="empty-state"><strong>지도를 표시하지 못했습니다.</strong><span>${escapeHtml(error?.message || "잠시 후 다시 시도해 주세요.")}</span></div>`;
    $("#mapSummary").innerHTML = "";
    return;
  }
  const countries = state.mapData.countries || [];
  if (!countries.some(country => country.map_id === state.mapSelectedId)) state.mapSelectedId = countries[0]?.map_id || null;
  const countryMap = new Map(countries.map(country => [country.map_id, country]));
  const shapes = buildWorldShapes();
  const paths = shapes.map(shape => {
    const country = countryMap.get(shape.id);
    const interactive = Boolean(country);
    const selected = shape.id === state.mapSelectedId;
    const title = country ? `${country.label} · FCST ${formatMoney(country.forecast_total_krw)} · ERP ${formatMoney(country.erp_actual_krw)} · 미결 ${formatNumber(country.open_actions)}건` : shape.name;
    return `<path class="map-country ${mapCountryTone(country)} ${selected ? "selected" : ""}" d="${shape.path}" fill-rule="evenodd" ${interactive ? `data-map-id="${shape.id}" tabindex="0" role="button" aria-label="${escapeHtml(title)}"` : ""}><title>${escapeHtml(title)}</title></path>`;
  }).join("");
  const markers = countries.map(country => {
    const shape = shapes.find(item => item.id === country.map_id);
    if (!shape) return "";
    const amount = Number(country.erp_actual_krw || 0) + Number(country.forecast_total_krw || 0);
    const radius = amount ? Math.min(14, 7 + Math.log10(Math.max(amount, 1)) / 2.5) : Math.min(10, 6 + Number(country.open_actions || 0) / 3);
    return `<g class="map-marker ${mapCountryTone(country)} ${country.map_id === state.mapSelectedId ? "selected" : ""}" data-map-id="${country.map_id}" tabindex="0" role="button" aria-label="${escapeHtml(country.label)} 상세 열기"><circle cx="${shape.cx.toFixed(2)}" cy="${shape.cy.toFixed(2)}" r="${radius.toFixed(1)}"></circle><text x="${shape.cx.toFixed(2)}" y="${(shape.cy + 4).toFixed(2)}">${formatNumber(country.account_count + country.forecast_count + country.shipment_count)}</text><title>${escapeHtml(country.label)} 상세 열기</title></g>`;
  }).join("");
  container.innerHTML = `<svg viewBox="0 0 1000 480" role="img" aria-label="${escapeHtml(state.mapData.month)} ${escapeHtml(state.mapData.segment_label)} 해외사업 세계지도"><rect class="map-ocean" width="1000" height="480" rx="20"></rect><g class="map-graticule"><path d="M0 120H1000M0 240H1000M0 360H1000M250 0V480M500 0V480M750 0V480"></path></g><g>${paths}</g><g>${markers}</g></svg>`;
  renderMapSummary();
  renderMapCountryDetail(mapCountryById(state.mapSelectedId));
  const unmatched = state.mapData.unmatched || {};
  const issues = Number(unmatched.record_count || 0) + Number(unmatched.forecast_count || 0) + Number(unmatched.shipment_count || 0);
  $("#mapDataQuality").className = `map-data-quality ${issues ? "warning" : "ok"}`;
  $("#mapDataQuality").innerHTML = issues
    ? `<strong>국가 미매칭 ${formatNumber(issues)}건</strong><span>거래처·업무 ${formatNumber(unmatched.record_count)}건 · FCST ${formatNumber(unmatched.forecast_count)}건 ${formatMoney(unmatched.forecast_total_krw)} · ERP 출고 ${formatNumber(unmatched.shipment_count)}건 ${formatMoney(unmatched.erp_actual_krw)} — 거래처의 국가와 ERP 연결명을 확인해 주세요.</span>`
    : `<strong>국가 매칭 정상</strong><span>FCST와 ERP 출고가 등록된 국가에 모두 연결되었습니다. 최신 ERP 동기화 ${formatDate(state.mapData.source?.erp_last_sync, true)}</span>`;
}

async function loadGlobalMap() {
  const container = $("#worldMap");
  container.innerHTML = '<div class="empty-state">선택한 조건으로 지도를 갱신하는 중입니다.</div>';
  try {
    await loadWorldTopology();
    state.mapData = await api(mapApiPath());
    renderGlobalMap();
  } catch (error) {
    renderGlobalMap(error);
    toast(error.message, "error");
  }
}

function selectMapCountry(mapId) {
  if (!mapCountryById(mapId)) return;
  state.mapSelectedId = String(mapId);
  renderGlobalMap();
}

function handleMapCountryClick(event) {
  const target = event.target.closest("[data-map-id]");
  if (target) selectMapCountry(target.dataset.mapId);
}

function handleMapCountryKeydown(event) {
  if (!["Enter", " "].includes(event.key)) return;
  const target = event.target.closest("[data-map-id]");
  if (!target) return;
  event.preventDefault();
  selectMapCountry(target.dataset.mapId);
}

function renderCountryFilterChips() {
  const recordChip = $("#recordCountryFilterChip");
  recordChip.classList.toggle("hidden", !state.recordCountryFilter);
  recordChip.textContent = state.recordCountryFilter ? `${state.recordCountryFilter.label} · 국가필터 ×` : "";
  const forecastChip = $("#forecastCountryFilterChip");
  forecastChip.classList.toggle("hidden", !state.forecastCountryFilter);
  forecastChip.innerHTML = state.forecastCountryFilter ? `<span>${escapeHtml(state.forecastCountryFilter.label)} FCST만 보는 중</span><b>필터 해제 ×</b>` : "";
  const salesChip = $("#salesCountryFilterChip");
  salesChip.classList.toggle("hidden", !state.salesCountryFilter);
  salesChip.innerHTML = state.salesCountryFilter ? `<span>${escapeHtml(state.salesCountryFilter.label)} ERP 매출만 보는 중</span><b>필터 해제 ×</b>` : "";
}

function clearRecordCountryFilter() {
  state.recordCountryFilter = null;
  renderRecordView();
}

function clearForecastCountryFilter() {
  state.forecastCountryFilter = null;
  renderForecast();
}

function clearSalesCountryFilter() {
  state.salesCountryFilter = null;
  loadSales();
}

function handleMapDetailAction(event) {
  const partnerButton = event.target.closest("[data-erp-partner]");
  if (partnerButton) return openPartnerJourney(partnerButton.dataset.erpPartner);
  const recordButton = event.target.closest("[data-map-record-id]");
  if (recordButton) {
    const record = state.records.find(row => row.id === recordButton.dataset.mapRecordId);
    if (!record && window.MajorTasksUI) {
      switchView("task");
      return window.MajorTasksUI.openById(recordButton.dataset.mapRecordId);
    }
    if (record?.entity_type === "account") return openAccountJourney(record);
    state.recordCountryFilter = null;
    return focusRecord(record);
  }
  const actionButton = event.target.closest("[data-country-action]");
  if (!actionButton) return;
  const country = mapCountryById(state.mapSelectedId);
  if (!country) return;
  const action = actionButton.dataset.countryAction;
  if (action === "account") {
    state.recordCountryFilter = country;
    $("#recordSearch").value = "";
    switchView(action);
    renderRecordView();
  }
  if (action === "monthly_sales_fcst") {
    const currentMonth = operationalForecastMonth();
    const targetMonth = state.mapData.month;
    $("#monthlyFcstTargetMonth").value = targetMonth;
    $("#monthlyFcstDate").value = localDate(new Date());
    state.monthlySalesFcstTab = targetMonth === currentMonth ? "current" : targetMonth === monthlyFcstShiftMonth(currentMonth, 1) ? "next" : "custom";
    state.monthlySalesFcstAsOfRound = "";
    syncMonthlyFcstQuickTabs();
    switchView("monthly_sales_fcst");
  }
  if (action === "sales") {
    state.salesCountryFilter = country;
    const [year] = state.mapData.month.split("-");
    $("#salesYear").value = year;
    syncSalesMonthOptions(year);
    $("#salesMonth").value = state.mapData.month;
    $("#salesSegment").value = state.mapData.segment || "all";
    switchView("sales");
    loadSales();
  }
}

function numeric(value, fallback = 0) {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function truthy(value) {
  return value === true || ["true", "1", "yes", "on"].includes(String(value || "").toLowerCase());
}

function addIsoDays(value, days = 0) {
  if (!value) return "";
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return "";
  date.setDate(date.getDate() + numeric(days));
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function dateDiffDays(from, to) {
  if (!from || !to) return 0;
  const start = new Date(`${String(from).slice(0, 10)}T00:00:00`);
  const end = new Date(`${String(to).slice(0, 10)}T00:00:00`);
  return Math.floor((end - start) / 86400000);
}

function latestFxRate(currency, explicitRate = 0) {
  if (currency === "KRW") return 1;
  if (numeric(explicitRate) > 0) return numeric(explicitRate);
  return numeric((state.exchangeRates?.rates || []).find(row => row.currency === currency)?.krw_rate);
}

function recordKrwAmount(row, amount = null, explicitRate = 0) {
  return numeric(amount === null ? row.amount : amount) * latestFxRate(row.currency || "KRW", explicitRate);
}

function receivableSchedule(row, asOf = todayIso()) {
  const payload = row.payload || {};
  const baseDate = payload.invoice_date || payload.ship_date || row.due_date || "";
  const definitions = [
    { key: "advance", label: "선금", days: 0, ratio: numeric(payload.advance_ratio), receivedDate: payload.advance_received_date, receivedAmount: numeric(payload.advance_received_amount) },
    ...[1, 2, 3, 4].map(index => ({
      key: `installment_${index}`, label: `${index}차`, days: numeric(payload[`installment_${index}_days`]),
      ratio: numeric(payload[`installment_${index}_ratio`]), receivedDate: payload[`receipt_${index}_date`],
      receivedAmount: numeric(payload[`receipt_${index}_amount`]),
    })),
  ].filter(item => item.ratio > 0);
  if (!definitions.length && numeric(row.amount) > 0) {
    definitions.push({ key: "single", label: "일괄", days: 0, ratio: 100, receivedDate: payload.receipt_1_date, receivedAmount: numeric(payload.receipt_1_amount) });
  }
  const schedules = definitions.map(item => {
    const plannedAmount = numeric(row.amount) * item.ratio / 100;
    const remaining = Math.max(plannedAmount - item.receivedAmount, 0);
    const dueDate = item.key === "advance" ? baseDate : addIsoDays(baseDate, item.days);
    const overdueDays = remaining > 0 && dueDate && dueDate < asOf ? dateDiffDays(dueDate, asOf) : 0;
    return { ...item, plannedAmount, remaining, dueDate, overdueDays };
  });
  const collected = schedules.reduce((sum, item) => sum + item.receivedAmount, 0);
  const balance = Math.max(numeric(row.amount) - collected, 0);
  const unpaid = schedules.filter(item => item.remaining > Math.max(0.01, numeric(row.amount) * .00001)).sort((a, b) => String(a.dueDate || "9999").localeCompare(String(b.dueDate || "9999")));
  const next = unpaid[0] || null;
  const maxOverdueDays = Math.max(0, ...unpaid.map(item => item.overdueDays));
  const overdueAmount = unpaid.filter(item => item.dueDate && item.dueDate <= asOf).reduce((sum, item) => sum + item.remaining, 0);
  let agingKey = "not_due";
  let agingLabel = "만기 미도래";
  if (balance <= 0.01) { agingKey = "paid"; agingLabel = "회수 완료"; }
  else if (maxOverdueDays >= 365) { agingKey = "over_365"; agingLabel = "12개월 이상"; }
  else if (maxOverdueDays >= 90) { agingKey = "over_90"; agingLabel = "90일 이상"; }
  else if (maxOverdueDays >= 60) { agingKey = "days_60_89"; agingLabel = "60~89일"; }
  else if (maxOverdueDays >= 30) { agingKey = "days_30_59"; agingLabel = "30~59일"; }
  else if (maxOverdueDays > 0) { agingKey = "days_1_29"; agingLabel = "1~29일 연체"; }
  else if (next?.dueDate && next.dueDate <= asOf) { agingKey = "due"; agingLabel = "만기 도래"; }
  else if (next?.dueDate && dateDiffDays(asOf, next.dueDate) <= 7) { agingKey = "due_week"; agingLabel = "7일 내 수금"; }
  return { schedules, collected, balance, unpaid, next, maxOverdueDays, overdueAmount, agingKey, agingLabel };
}

function cashPlanSummary(rows, month) {
  const selected = rows.filter(row => {
    const date = row.payload?.plan_date || row.due_date || row.payload?.execution_date || "";
    return !month || String(date).startsWith(month);
  });
  const summary = { selected, opening: 0, fixed: 0, plannedIn: 0, adjustedIn: 0, actualIn: 0, plannedOut: 0, adjustedOut: 0, actualOut: 0 };
  selected.forEach(row => {
    const payload = row.payload || {};
    const planKrw = recordKrwAmount(row, null, payload.exchange_rate);
    const actualKrw = numeric(payload.actual_krw_amount) || recordKrwAmount(row, payload.actual_foreign_amount, payload.exchange_rate) || (row.status === "executed" ? planKrw : 0);
    if (payload.flow_type === "opening_liquid") summary.opening += planKrw;
    else if (payload.flow_type === "fixed_fund") summary.fixed += planKrw;
    else if (payload.flow_type === "cash_in") {
      summary.plannedIn += planKrw;
      summary.adjustedIn += planKrw * numeric(payload.adjustment_rate, 100) / 100;
      summary.actualIn += actualKrw;
    } else if (payload.flow_type === "cash_out") {
      summary.plannedOut += planKrw;
      summary.adjustedOut += planKrw * numeric(payload.payment_rate, 100) / 100;
      summary.actualOut += actualKrw;
    }
  });
  summary.forecastLiquid = summary.opening + summary.adjustedIn - summary.adjustedOut;
  summary.forecastTotal = summary.forecastLiquid + summary.fixed;
  return summary;
}

function receivableSummary(rows) {
  const details = rows.map(row => ({ row, ...receivableSchedule(row) }));
  const summary = {
    details,
    total: details.reduce((sum, item) => sum + recordKrwAmount(item.row, null, item.row.payload?.receivable_exchange_rate), 0),
    collected: details.reduce((sum, item) => sum + recordKrwAmount(item.row, item.collected, item.row.payload?.receivable_exchange_rate), 0),
    balance: details.reduce((sum, item) => sum + recordKrwAmount(item.row, item.balance, item.row.payload?.receivable_exchange_rate), 0),
    overdue: details.reduce((sum, item) => sum + recordKrwAmount(item.row, item.overdueAmount, item.row.payload?.receivable_exchange_rate), 0),
    dueWeek: details.filter(item => item.next?.dueDate && item.next.dueDate >= todayIso() && dateDiffDays(todayIso(), item.next.dueDate) <= 7).reduce((sum, item) => sum + recordKrwAmount(item.row, item.next.remaining, item.row.payload?.receivable_exchange_rate), 0),
    p1Count: details.filter(item => item.row.payload?.risk_level === "p1" || item.maxOverdueDays >= 90).length,
  };
  summary.collectionRate = summary.total ? summary.collected / summary.total * 100 : 0;
  return summary;
}

function promotionSummary(rows, month) {
  const selected = rows.filter(row => !month || row.payload?.target_month === month);
  const active = selected.filter(row => !["completed", "cancelled"].includes(row.status));
  const target = selected.reduce((sum, row) => sum + recordKrwAmount(row), 0);
  const achieved = selected.reduce((sum, row) => sum + recordKrwAmount(row, row.payload?.achieved_amount), 0);
  const endingSoon = active.filter(row => row.payload?.end_date && dateDiffDays(todayIso(), row.payload.end_date) >= 0 && dateDiffDays(todayIso(), row.payload.end_date) <= 14).length;
  return { selected, active, target, achieved, achievementRate: target ? achieved / target * 100 : 0, endingSoon };
}

function renderFinanceOverview() {
  const month = $("#recordMonthFilter")?.value || todayIso().slice(0, 7);
  const cash = cashPlanSummary(state.records.filter(row => row.entity_type === "cash_plan"), month);
  const ar = receivableSummary(state.records.filter(row => row.entity_type === "receivable"));
  const promotions = promotionSummary(state.records.filter(row => row.entity_type === "promotion"), month);
  $("#financeOverview").innerHTML = [
    ["이번 달 자금계획", formatMoney(cash.adjustedIn - cash.adjustedOut), `수금 ${formatMoney(cash.adjustedIn)} · 지출 ${formatMoney(cash.adjustedOut)}`, "cash_plan", cash.forecastLiquid < 0 ? "danger" : "cash"],
    ["미수채권 잔액", formatMoney(ar.balance), `연체 ${formatMoney(ar.overdue)} · P1 ${formatNumber(ar.p1Count)}건`, "receivable", ar.overdue > 0 ? "danger" : "receivable"],
    ["프로모션 달성", `${formatNumber(promotions.achievementRate, 1)}%`, `목표 ${formatMoney(promotions.target)} · 진행 ${formatNumber(promotions.active.length)}건`, "promotion", "promotion"],
  ].map(card => `<button type="button" class="finance-overview-card ${card[4]}" data-dashboard-view="${card[3]}"><span>${card[0]}</span><strong>${card[1]}</strong><small>${card[2]} · 상세 보기 →</small></button>`).join("");
}

const shareColors = ["#079a7f", "#3f82d7", "#efb347", "#dc6d64", "#6e8f96", "#8d6bc4", "#46a5ad", "#a4b34f", "#bd7b4c", "#64748b", "#0f766e", "#94a3b8"];

function renderTargetPerformance() {
  const targets = state.dashboard?.targets;
  if (!targets) return;
  const editable = Boolean(state.permissions.can_edit_all);
  const rows = [
    {
      type: "year", label: `${state.dashboard.year} 연간 매출`, target: targets.year.target_krw,
      actual: targets.year.actual_krw, percent: targets.year.achievement_pct,
      breakdown: `ERP 누적 ${formatMoney(targets.year.actual_krw)}`,
    },
    {
      type: "month", label: `${Number(state.dashboard.current_month.slice(5))}월 매출`, target: targets.month.target_krw,
      actual: targets.month.expected_krw, percent: targets.month.achievement_pct,
      breakdown: `출고완료 ${formatMoney(targets.month.actual_krw)} · 출고대기 ${formatMoney(targets.month.pending_ship_krw)} (${formatNumber(targets.month.pending_ship_count)}건)`,
    },
  ];
  $("#targetPerformanceGrid").innerHTML = rows.map(row => {
    const capped = Math.max(0, Math.min(100, Number(row.percent || 0)));
    const targetText = Number(row.target) ? formatMoney(row.target) : "목표 미설정";
    return `<article class="target-performance-card ${escapeHtml(row.type)}">
      <div class="target-performance-head"><div><span>${escapeHtml(row.label)} 목표 vs 달성</span><strong>${formatMoney(row.actual)}</strong></div>${editable ? `<button type="button" class="mini-btn emphasis" data-target-type="${escapeHtml(row.type)}">목표 수정</button>` : ""}</div>
      <div class="target-progress"><span style="width:${capped}%"></span></div>
      <div class="target-performance-meta"><b>목표 ${targetText}</b><b>달성률 ${formatNumber(row.percent, 1)}%</b></div>
      <small>${escapeHtml(row.breakdown)}</small>
    </article>`;
  }).join("");
}

function renderShareChart(container, rows, centerLabel) {
  if (!rows?.length || !rows.some(row => Number(row.amount) > 0)) {
    container.innerHTML = '<div class="empty-state">집계 가능한 ERP 매출이 없습니다.</div>';
    return;
  }
  const visible = rows.slice(0, 8);
  let cursor = 0;
  const segments = visible.map((row, index) => {
    const start = cursor;
    cursor += Number(row.share || 0);
    return `${shareColors[index % shareColors.length]} ${start}% ${Math.min(cursor, 100)}%`;
  });
  if (cursor < 100) segments.push(`#dce8e6 ${cursor}% 100%`);
  container.innerHTML = `<div class="share-donut" style="background:conic-gradient(${segments.join(",")})"><div><strong>${escapeHtml(centerLabel)}</strong><span>${formatMoney(visible.reduce((sum, row) => sum + Number(row.amount || 0), 0))}</span></div></div><div class="share-legend">${visible.map((row, index) => `<div><i style="background:${shareColors[index % shareColors.length]}"></i><span>${escapeHtml(row.label || row.key)}</span><strong>${formatNumber(row.share, 1)}%</strong><small>${compactMoney(row.amount, "KRW")}</small></div>`).join("")}</div>`;
}

function renderOverviewTopPartners() {
  const rows = state.dashboard?.top_partners || [];
  const max = Math.max(...rows.map(row => Number(row.amount || 0)), 1);
  $("#overviewTopPartners").innerHTML = rows.length ? rows.map((row, index) => {
    const target = row.account_id ? `data-account-id="${escapeHtml(row.account_id)}"` : `data-erp-partner="${escapeHtml(row.partner_name)}"`;
    const merged = Number(row.erp_partner_names?.length || 0) > 1 ? ` · ERP명 ${formatNumber(row.erp_partner_names.length)}개 통합` : "";
    return `<button type="button" ${target}><span>${index + 1}</span><div><strong>${escapeHtml(row.partner_name)}</strong><i><b style="width:${Math.max(2, Number(row.amount || 0) / max * 100)}%"></b></i></div><em>${compactMoney(row.amount, "KRW")}<small>${formatNumber(row.shipment_count)}건${escapeHtml(merged)}</small></em></button>`;
  }).join("") : '<div class="empty-state">거래처 매출이 없습니다.</div>';
}

function renderCountryCoverage() {
  const coverage = state.dashboard?.country_coverage || {};
  const group = (title, count, rows, value) => `<section><div><h4>${escapeHtml(title)}</h4><strong>${formatNumber(count)}개국</strong></div><div class="country-chip-list">${rows.length ? rows.map(row => `<span><b>${escapeHtml(row.label)}</b><small>${escapeHtml(value(row))}</small></span>`).join("") : '<p class="agenda-empty">해당 국가가 없습니다.</p>'}</div></section>`;
  $("#countryCoverage").innerHTML = group("활동국가", coverage.active_count || 0, coverage.active || [], row => compactMoney(row.amount, "KRW")) + group("타겟국가", coverage.target_count || 0, coverage.target || [], row => `거래처 ${formatNumber(row.account_count)}개`);
}

function handleTargetEdit(event) {
  const button = event.target.closest("[data-target-type]");
  if (!button || !state.permissions.can_edit_all) return;
  const type = button.dataset.targetType;
  const target = state.dashboard?.targets?.[type];
  if (!target) return;
  const form = $("#targetForm");
  form.reset();
  form.elements.target_type.value = type;
  form.elements.target_key.value = target.target_key;
  form.elements.target_krw.value = Number(target.target_krw || 0);
  $("#targetDialogTitle").textContent = `${target.target_key} ${type === "year" ? "연간" : "월간"} 매출 목표 수정`;
  $("#targetDialogMeta").textContent = type === "year" ? "ERP 해외 출고 누계와 비교합니다." : "출고완료와 수금완료 출고대기 합계와 비교합니다.";
  $("#targetFormError").textContent = "";
  $("#targetDialog").showModal();
}

async function saveDashboardTarget(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const button = $("#targetSubmitBtn");
  const errorNode = $("#targetFormError");
  errorNode.textContent = "";
  button.disabled = true;
  try {
    const result = await api("/api/dashboard/targets", { method: "PUT", body: { target_type: data.get("target_type"), target_key: data.get("target_key"), target_krw: Number(data.get("target_krw") || 0) } });
    $("#targetDialog").close();
    await refreshOverview();
    toast(result.message);
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderOverview() {
  if (!state.dashboard) return;
  renderExchangeRates();
  renderOverviewForecast();
  const d = state.dashboard;
  renderTargetPerformance();
  renderShareChart($("#regionShareChart"), d.shares?.regions || [], "8개 권역");
  renderShareChart($("#modelShareChart"), d.shares?.models || [], "제품 모델");
  renderShareChart($("#businessShareChart"), d.shares?.business_units || [], "사업분야");
  renderOverviewTopPartners();
  renderCountryCoverage();
  renderFinanceOverview();
  const completion = d.task_total ? Math.round((d.task_done / d.task_total) * 100) : 0;
  const cards = [
    ["해외 ERP 누적 공급가", compactMoney(d.actual_krw, "KRW"), `${d.year}년 국내·LOCAL 제외`, "sales"],
    ["파이프라인", compactMoney(d.pipeline_amount, "USD"), `${d.pipeline_count}개 기회 등록`, "pipeline"],
    ["해외 거래처", formatNumber(d.account_count), "활성·잠재 거래처 합계", "account"],
    ["업무 완료율", `${completion}%`, `미완료 ${Math.max(0, d.task_total - d.task_done)} · 지연 ${d.task_overdue}`, "daily"],
  ];
  $("#kpiGrid").innerHTML = cards.map(card => `<button class="kpi-card clickable-card" type="button" data-dashboard-view="${card[3]}"><span class="label">${card[0]}</span><strong>${card[1]}</strong><small>${card[2]} · 눌러서 상세 보기</small></button>`).join("");
  $("#regionList").innerHTML = d.regions.length ? d.regions.map(row => `<button class="region-row clickable-row" type="button" data-region="${escapeHtml(row.region)}"><strong>${escapeHtml(row.region)}</strong><span>${row.count}</span></button>`).join("") : '<div class="empty-state">거래처 데이터가 없습니다.</div>';

  const tasks = d.major_tasks || [];
  const taskBusinessLabels = { common: "공통", dental: "덴탈", medical: "메디컬", aesthetic: "에스테틱", legacy_unclassified: "기존 미분류" };
  $("#priorityTasks").innerHTML = tasks.length ? tasks.map(row => `<tr data-major-task-id="${escapeHtml(row.id)}"><td>${escapeHtml(taskBusinessLabels[row.field] || row.field || "공통")}</td><td>${escapeHtml(row.country || "—")}</td><td class="table-title">${escapeHtml(row.title)}<span class="table-sub">${escapeHtml(row.other || "")}</span></td><td><span class="rag-pill ${escapeHtml(row.rag || "green")}">${escapeHtml(String(row.rag || "green").toUpperCase())}</span><span class="table-sub">${escapeHtml(statusLabels[row.status] || row.status)}${row.progress == null ? "" : ` · ${formatNumber(row.progress)}%`}</span></td><td>${escapeHtml(row.owner_name || "미지정")}</td><td>${formatDate(row.due_date)}</td><td>${escapeHtml((row.other || "—").slice(0, 80))}</td></tr>`).join("") : '<tr><td colspan="7"><div class="empty-state">진행 업무가 없습니다.</div></td></tr>';
  const pipelines = state.records.filter(row => row.entity_type === "pipeline" && !["won", "lost"].includes(row.status)).sort((a, b) => Number(b.amount) - Number(a.amount)).slice(0, 5);
  $("#priorityPipeline").innerHTML = pipelines.length ? pipelines.map(row => compactRow(row, compactMoney(row.amount, row.currency))).join("") : '<div class="empty-state">파이프라인이 없습니다.</div>';
  const brief = buildDailyBrief();
  $("#morningPreview").innerHTML = brief.preview.length ? brief.preview.map(item => agendaRow(item, true)).join("") : '<div class="empty-state">오늘 확인할 미결업무가 없습니다.</div>';
  renderBarChart($("#overviewSalesChart"), state.sales?.monthly || [], true);
}

function compactRow(row, value) {
  return `<button class="compact-row clickable-row" type="button" data-record-id="${escapeHtml(row.id)}"><span class="bullet"></span><div><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(row.owner_name || "담당자 미지정")} · ${escapeHtml(row.payload?.account_name || row.region || row.country || statusLabels[row.status] || row.status)}</small></div><span>${escapeHtml(value)}</span></button>`;
}

function renderBarChart(container, monthly, compact = false) {
  if (!monthly?.length || !monthly.some(row => Number(row.krw_supply) > 0)) {
    container.innerHTML = '<div class="empty-state">동기화된 ERP 매출이 없습니다.<br>월별 매출에서 ERP 동기화를 실행하세요.</div>';
    return;
  }
  const max = Math.max(...monthly.map(row => Number(row.krw_supply || 0)), 1);
  container.innerHTML = `<div class="bar-chart">${monthly.map(row => {
    const amount = Number(row.krw_supply || 0);
    const height = Math.max(1, (amount / max) * (compact ? 88 : 95));
    return `<button class="bar-item" type="button" data-sales-month="${escapeHtml(row.month)}" aria-label="${Number(row.month.slice(5))}월 ${escapeHtml(formatMoney(amount))} 상세 보기"><div class="bar-track"><div class="bar" style="height:${height}%" data-value="${escapeHtml(compactMoney(amount, "KRW"))}"></div></div><div class="bar-label">${Number(row.month.slice(5))}월</div></button>`;
  }).join("")}</div>`;
}

function todayIso() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function recordActionDate(row) {
  const payload = row.payload || {};
  if (row.entity_type === "receivable") return payload.next_collection_date || payload.promise_date || receivableSchedule(row).next?.dueDate || "";
  if (row.entity_type === "cash_plan") return payload.execution_date || payload.plan_date || payload.maturity_date || row.due_date || "";
  if (row.entity_type === "promotion") return payload.target_ship_date || payload.end_date || row.due_date || "";
  return payload.next_action_date || payload.next_target_date || payload.revised_target_date ||
    payload.mid_review_date || row.due_date || payload.activity_at?.slice(0, 10) || "";
}

function isClosedRecord(row) {
  return ["done", "completed", "cancelled", "closed", "lost", "shipped", "achieved", "executed", "paid"].includes(row.status);
}

function actionableRecords() {
  const today = todayIso();
  return state.records
    .filter(row => ["agenda", "event", "activity", "order", "goal", "pipeline", "cash_plan", "receivable", "promotion"].includes(row.entity_type) && !isClosedRecord(row))
    .sort((a, b) => {
      const aDate = recordActionDate(a) || "9999-12-31";
      const bDate = recordActionDate(b) || "9999-12-31";
      const aScore = aDate < today ? 0 : aDate === today ? 1 : 2;
      const bScore = bDate < today ? 0 : bDate === today ? 1 : 2;
      if (aScore !== bScore) return aScore - bScore;
      return aDate.localeCompare(bDate) || String(a.title).localeCompare(String(b.title), "ko");
    });
}

function briefItem(row, tone = "normal", note = "") {
  return { row, tone, note: note || `${row.owner_name || "담당자 미지정"} · ${statusLabels[row.status] || row.status}` };
}

function buildDailyBrief() {
  const today = todayIso();
  const active = actionableRecords();
  const financeTypes = new Set(["cash_plan", "receivable", "promotion"]);
  const majorTasks = (state.dashboard?.major_task_brief || []).map(item => ({
    ...item, entity_type: "major_task", due_date: item.effective_deadline,
    payload: { next_action: item.next_action }, owner_name: item.owner_name,
  }));
  const operations = [...majorTasks, ...active.filter(row => !financeTypes.has(row.entity_type))];
  const overdue = operations.filter(row => recordActionDate(row) && recordActionDate(row) < today).map(row => briefItem(row, "danger", `목표일 ${formatDate(recordActionDate(row))} · ${row.owner_name || "담당자 미지정"}`));
  const dueToday = operations.filter(row => recordActionDate(row) === today).map(row => briefItem(row, "today", `${activityLabels[row.payload?.activity_type] || statusLabels[row.status] || "오늘 확인"} · ${row.owner_name || "담당자 미지정"}`));
  const unresolved = operations.filter(row => ["major_task", "pipeline", "goal"].includes(row.entity_type) && !recordActionDate(row)).map(row => briefItem(row, "warning", `목표일 미지정 · ${row.owner_name || "담당자 미지정"}`));
  const orders = operations.filter(row => row.entity_type === "order" && !["shipped", "cancelled"].includes(row.status)).map(row => briefItem(row, recordActionDate(row) && recordActionDate(row) <= today ? "warning" : "normal", `${statusLabels[row.status] || row.status} · 다음 목표 ${recordActionDate(row) ? formatDate(recordActionDate(row)) : "미지정"}`));
  const collections = active.filter(row => row.entity_type === "receivable").filter(row => {
    const detail = receivableSchedule(row);
    return detail.maxOverdueDays > 0 || (detail.next?.dueDate && detail.next.dueDate >= today && dateDiffDays(today, detail.next.dueDate) <= 7) || (row.payload?.promise_date && row.payload.promise_date <= today);
  }).map(row => {
    const detail = receivableSchedule(row);
    const note = detail.maxOverdueDays ? `${detail.maxOverdueDays}일 연체 · 잔액 ${formatMoney(detail.balance, row.currency)}` : `다음 수금 ${detail.next?.dueDate ? formatDate(detail.next.dueDate) : "미지정"} · ${formatMoney(detail.balance, row.currency)}`;
    return briefItem(row, detail.maxOverdueDays ? "danger" : "warning", note);
  });
  const cashActions = active.filter(row => row.entity_type === "cash_plan" && recordActionDate(row) && recordActionDate(row) <= today).map(row => briefItem(row, recordActionDate(row) < today ? "danger" : "today", `${flowTypeLabels[row.payload?.flow_type] || "자금"} · ${formatMoney(row.amount, row.currency)} · ${row.payload?.counterparty || row.title}`));
  const promotionActions = active.filter(row => row.entity_type === "promotion" && recordActionDate(row) && recordActionDate(row) <= today).map(row => briefItem(row, recordActionDate(row) < today ? "danger" : "today", `프로모션 ${row.payload?.promotion_id || ""} · 목표 ${formatMoney(row.amount, row.currency)}`));
  const meetings = state.records.filter(row => {
    const type = row.payload?.activity_type;
    const date = recordActionDate(row);
    return date === today && (["agenda", "event"].includes(row.entity_type) || ["phone", "video_meeting", "exhibition", "visit"].includes(type));
  }).map(row => briefItem(row, "today", `${activityLabels[row.payload?.activity_type] || "회의·일정"} · ${row.payload?.account_name || row.country || row.region || ""}`));
  const financeActions = [...collections, ...cashActions, ...promotionActions].filter((item, index, all) => all.findIndex(other => other.row.id === item.row.id) === index);
  const preview = [...overdue, ...dueToday, ...financeActions, ...unresolved, ...orders].filter((item, index, all) => all.findIndex(other => other.row.id === item.row.id) === index).slice(0, 6);
  return { overdue, dueToday, unresolved, orders, collections, cashActions, promotionActions, financeActions, meetings, preview };
}

function agendaRow(item, compact = false) {
  const row = item.row;
  const entityName = row.entity_type === "major_task" ? "주요 업무" : recordConfig[row.entity_type]?.title || "업무";
  const target = row.entity_type === "major_task" ? `data-major-task-id="${escapeHtml(row.id)}"` : `data-record-id="${escapeHtml(row.id)}"`;
  return `<button class="agenda-row ${escapeHtml(item.tone)} ${compact ? "compact" : ""}" type="button" ${target}>
    <span class="agenda-check">${item.tone === "danger" ? "!" : item.tone === "today" ? "●" : "○"}</span>
    <span class="agenda-copy"><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(item.note)}</small></span>
    <span class="agenda-type">${escapeHtml(entityName)}</span>
  </button>`;
}

function agendaSection(number, title, items, emptyMessage) {
  return `<section class="agenda-section"><div class="agenda-section-head"><span>${number}</span><h4>${escapeHtml(title)}</h4><b>${items.length}</b></div><div>${items.length ? items.map(item => agendaRow(item)).join("") : `<p class="agenda-empty">${escapeHtml(emptyMessage)}</p>`}</div></section>`;
}

function renderDaily() {
  if (!state.records) return;
  const brief = buildDailyBrief();
  $("#dailyBriefDate").textContent = `${formatDate(todayIso())} 기준 · 오늘 할 일, 미결업무와 거래처 후속조치를 자동 정리합니다.`;
  const counters = [
    ["오늘 목표", brief.dueToday.length, "오늘 처리·확인"],
    ["기한 초과", brief.overdue.length, "우선 논의 필요"],
    ["수금·자금 경보", brief.financeActions.length, "채권·집행·프로모션"],
    ["진행 중 수주", brief.orders.length, "PO부터 출고까지"],
  ];
  $("#dailyKpiGrid").innerHTML = counters.map((item, index) => `<article class="kpi-card daily-kpi ${index === 1 && item[1] ? "alert" : ""}"><span class="label">${item[0]}</span><strong>${formatNumber(item[1])}</strong><small>${item[2]}</small></article>`).join("");
  $("#morningAgenda").innerHTML = [
    agendaSection("01", "기한 초과·미결업무", brief.overdue, "기한이 지난 업무가 없습니다."),
    agendaSection("02", "오늘 해야 할 일·확인사항", brief.dueToday, "오늘 목표로 등록된 항목이 없습니다."),
    agendaSection("03", "수금·자금·프로모션 점검", brief.financeActions, "오늘 점검할 자금·채권·프로모션 경보가 없습니다."),
    agendaSection("04", "목표일과 담당 확정 필요", brief.unresolved, "목표일 미지정 항목이 없습니다."),
    agendaSection("05", "거래처 수주·출고 진행", brief.orders, "진행 중인 수주 건이 없습니다."),
  ].join("");
  $("#todayMeetings").innerHTML = `<h4>오늘 연락·미팅</h4>${brief.meetings.length ? brief.meetings.map(item => agendaRow(item, true)).join("") : '<p class="agenda-empty">오늘 예정된 통화·미팅·전시회가 없습니다.</p>'}`;
}

function handleDashboardNavigate(event) {
  const viewButton = event.target.closest("[data-dashboard-view]");
  if (viewButton) return switchView(viewButton.dataset.dashboardView);
  const regionButton = event.target.closest("[data-region]");
  if (regionButton) {
    switchView("account");
    $("#recordSearch").value = "";
    $("#accountRegionFilter").value = regionButton.dataset.region;
    populateAccountCountryFilter();
    renderRecordTable();
  }
}

function focusRecord(record) {
  if (!record || !recordConfig[record.entity_type]) return;
  switchView(record.entity_type);
  $("#recordSearch").value = record.title;
  $("#recordStatusFilter").value = "";
  renderRecordTable();
}

function handleAgendaAction(event) {
  const majorTask = event.target.closest("[data-major-task-id]");
  if (majorTask && window.MajorTasksUI) {
    switchView("task");
    return window.MajorTasksUI.openById(majorTask.dataset.majorTaskId);
  }
  const button = event.target.closest("[data-record-id]");
  if (!button) return;
  const record = state.records.find(row => row.id === button.dataset.recordId);
  focusRecord(record);
}

function handleSalesChartClick(event) {
  const button = event.target.closest("[data-sales-month]");
  if (!button) return;
  switchView("sales");
  $("#salesMonth").value = button.dataset.salesMonth;
  loadSales();
}

function handlePartnerJourneyAction(event) {
  const accountButton = event.target.closest("[data-account-id]");
  if (accountButton) {
    const account = state.records.find(row => row.id === accountButton.dataset.accountId && row.entity_type === "account");
    if (account) return openAccountJourney(account);
  }
  const button = event.target.closest("[data-erp-partner]");
  if (!button) return;
  openPartnerJourney(button.dataset.erpPartner);
}

async function copyMorningAgenda() {
  const brief = buildDailyBrief();
  const groups = [
    ["1. 기한 초과·미결업무", brief.overdue], ["2. 오늘 해야 할 일·확인사항", brief.dueToday],
    ["3. 수금·자금·프로모션 점검", brief.financeActions], ["4. 목표일과 담당 확정 필요", brief.unresolved],
    ["5. 거래처 수주·출고 진행", brief.orders],
  ];
  const text = [`[해외사업부 아침회의] ${formatDate(todayIso())}`, ...groups.flatMap(([title, items]) => ["", title, ...(items.length ? items.map(item => `- ${item.row.title} / ${item.note}`) : ["- 해당 없음"])])].join("\n");
  try {
    await navigator.clipboard.writeText(text);
    toast("아침회의 아젠다를 복사했습니다.");
  } catch (_error) { toast("복사 권한이 없어 회의자료 인쇄를 이용해 주세요.", "error"); }
}

function renderSales() {
  if (!state.sales) return;
  renderCountryFilterChips();
  renderBarChart($("#salesChart"), state.sales.monthly);
  $$("[data-sales-month]", $("#salesChart")).forEach(button => button.classList.toggle("selected", button.dataset.salesMonth === state.sales.selected_month));
  const segments = state.sales.segments || [];
  const mainSegments = segments.filter(row => row.key !== "unclassified");
  $("#salesSegmentCards").innerHTML = mainSegments.map(row => `
    <button class="segment-kpi-card ${escapeHtml(row.key)}" type="button" data-sales-segment="${escapeHtml(row.key)}">
      <span>${escapeHtml(row.label)}</span>
      <strong>${compactMoney(row.krw_supply, "KRW")}</strong>
      <small>해외매출 ${formatNumber(row.share, 1)}% · 출고 ${formatNumber(row.shipment_count)}건</small>
    </button>
  `).join("");
  const maxSegment = Math.max(...mainSegments.map(row => Number(row.krw_supply || 0)), 1);
  const quality = segments.find(row => row.key === "unclassified");
  $("#businessUnitSales").innerHTML = mainSegments.map(row => {
    const width = Math.max(Number(row.krw_supply) ? 4 : 0, (Number(row.krw_supply || 0) / maxSegment) * 100);
    return `<button class="business-unit-row" type="button" data-sales-segment="${escapeHtml(row.key)}">
      <div><strong>${escapeHtml(row.label)}</strong><span>${formatNumber(row.share, 1)}%</span></div>
      <div class="business-unit-track"><span class="${escapeHtml(row.key)}" style="width:${width}%"></span></div>
      <small>${compactMoney(row.krw_supply, "KRW")} · ${formatNumber(row.line_count)}라인</small>
    </button>`;
  }).join("") + (Number(quality?.line_count || 0) ? `<button class="classification-warning" type="button" data-sales-segment="unclassified">미분류 ${formatNumber(quality.line_count)}라인 · 확인 필요</button>` : '<div class="classification-ok">모든 해외 출고가 3개 사업군으로 분류되었습니다.</div>');
  $$("[data-sales-segment]").forEach(button => button.addEventListener("click", () => {
    $("#salesSegment").value = button.dataset.salesSegment;
    loadSales();
  }));
  const partners = state.sales.partners || [];
  const periodLabel = state.sales.selected_month === "all" ? `${state.sales.year}년` : `${Number(state.sales.selected_month.slice(5))}월`;
  const countryLabel = state.sales.country_filter?.label ? `${state.sales.country_filter.label} · ` : "";
  $("#partnerSalesTitle").textContent = `${countryLabel}${periodLabel} ${state.sales.segment_label || segmentLabels[$("#salesSegment").value]} · 거래처별 매출 TOP 20`;
  $("#partnerSales").innerHTML = partners.length ? partners.map((row, index) => `<button type="button" class="rank-row rank-row-button" data-erp-partner="${escapeHtml(row.partner_name || "미지정")}"><b>${index + 1}</b><strong title="${escapeHtml(row.partner_name || "미지정")}">${escapeHtml(row.partner_name || "미지정")}</strong><span>${compactMoney(row.krw_supply, "KRW")} · ${formatNumber(row.shipment_count)}건</span></button>`).join("") : '<div class="empty-state">거래처 매출이 없습니다.</div>';
  $("#salesTableBody").innerHTML = state.sales.monthly.map(row => {
    const currencies = Object.entries(row.currencies || {}).filter(([, value]) => Number(value)).map(([currency, value]) => `${currency} ${formatNumber(value)}`).join(" · ") || "—";
    return `<tr class="clickable-table-row" data-sales-month="${escapeHtml(row.month)}"><td class="table-title"><button class="table-link" type="button" data-sales-month="${escapeHtml(row.month)}">${escapeHtml(row.month)} 상세 →</button></td><td>${formatNumber(row.shipment_count)}</td><td>${formatNumber(row.line_count)}</td><td>${formatMoney(row.krw_supply)}</td><td>${formatMoney(row.krw_total)}</td><td>${escapeHtml(currencies)}</td></tr>`;
  }).join("");
  const items = state.sales.items || [];
  $("#itemSalesTitle").textContent = `${countryLabel}${periodLabel} · 품목별 해외매출`;
  $("#itemSalesCount").textContent = `총 ${formatNumber(items.length)}개 품목`;
  $("#itemSalesBody").innerHTML = items.length ? items.map(row => `<tr><td>${escapeHtml(segmentLabels[row.business_unit] || row.business_unit || "미분류")}</td><td>${escapeHtml(row.product_code)}</td><td class="table-title">${escapeHtml(row.product_name)}${row.specification ? `<span class="table-sub">${escapeHtml(row.specification)}</span>` : ""}</td><td>${formatNumber(row.shipment_count)}건</td><td>${formatNumber(row.quantity, 2)}</td><td>${formatMoney(row.krw_supply)}</td></tr>`).join("") : '<tr><td colspan="6"><div class="empty-state">선택 조건의 품목 매출이 없습니다.</div></td></tr>';
  const shipments = state.sales.shipments || [];
  $("#shipmentDetailTitle").textContent = `${countryLabel}${periodLabel} · 출고 건별 내역`;
  $("#shipmentDetailBody").innerHTML = shipments.length ? shipments.map(row => `<tr><td>${formatDate(row.ship_date)}</td><td class="table-title">${escapeHtml(row.issue_no)}</td><td><button type="button" class="table-link" data-erp-partner="${escapeHtml(row.partner_name)}">${escapeHtml(row.partner_name)}</button></td><td>${escapeHtml(row.trade_type)}</td><td>${formatNumber(row.line_count)}</td><td>${formatMoney(row.krw_supply)}</td></tr>`).join("") : '<tr><td colspan="6"><div class="empty-state">선택 조건의 출고 내역이 없습니다.</div></td></tr>';
}

function renderErpStatus() {
  if (!state.erpStatus) return;
  const configured = state.erpStatus.configured;
  const last = state.erpStatus.last_sync;
  const freshness = state.erpStatus.freshness || {};
  $("#erpDot").className = `status-dot ${configured ? "online" : "error"}`;
  $("#erpSidebarStatus").textContent = configured ? (last?.status === "success" ? `최근 ${formatDate(last.finished_at)}` : "연결 설정 완료") : "환경설정 필요";
  const card = $("#erpStatusCard");
  card.className = `erp-status-card ${configured && freshness.status !== "stale" ? "" : "error"}`;
  const sourceCount = Number(last?.source_header_count || last?.header_count || 0);
  const excludedCount = Number(last?.excluded_header_count || 0);
  const detail = last ? `마지막 성공 ${formatDate(last.finished_at || last.started_at, true)} · 범위 ${escapeHtml(last.date_from || "—")}~${escapeHtml(last.date_to || "—")} · 전체 ${formatNumber(sourceCount)}건 중 국내·LOCAL ${formatNumber(excludedCount)}건 제외 · 해외 ${formatNumber(last.header_count)}건 / ${formatNumber(last.line_count)}라인` : "아직 성공한 동기화 이력이 없습니다.";
  const latestShip = freshness.latest_ship_date ? `최신 ERP 출고일 ${escapeHtml(freshness.latest_ship_date)}` : "최신 출고일 미확인";
  const salesQuality = state.sales?.actual_quality;
  const pending = salesQuality?.review_pending || {};
  const officialActual = salesQuality?.official_actual || {};
  const mappingEvidence = salesQuality?.mapping_evidence || {};
  const sampleQuality = (salesQuality?.rows || []).find(row => row.review_status === "sample_zero") || {};
  const qualityNote = Number(pending.line_count || 0)
    ? ` · 선택 조건 검토대기 ${formatNumber(pending.line_count)}라인 (표시 합계에 대한 공식 Actual 확정 전)`
    : "";
  const sampleNote = Number(sampleQuality.line_count || 0)
    ? `견본 ${formatNumber(sampleQuality.line_count)}라인은 원문금액을 보존하고 공식 인식매출 0원 정책 대상입니다. `
    : "";
  const officialNote = Number(officialActual.covered_line_count || 0)
    ? `검증범위 공식 인식매출 ${formatMoney(officialActual.recognized_sales_krw)} · ${formatNumber(officialActual.covered_line_count)}라인. `
    : "";
  const mappingNote = Number(mappingEvidence.matched_rows || 0)
    ? `Excel↔API ${formatNumber(mappingEvidence.matched_rows)}행·${formatNumber(mappingEvidence.matched_issues)}출고 Mapping 검증 완료. `
    : "Excel↔API Mapping 검증정보를 확인할 수 없습니다. ";
  const legacyJpyNote = Number(mappingEvidence.legacy_jpy_api_only_rows?.length || 0)
    ? `재발행 전 JPY ${formatNumber(mappingEvidence.legacy_jpy_api_only_rows.length)}행은 공식 Actual에서 제외하고 재동기화를 기다립니다. `
    : "";
  card.innerHTML = `<div><strong>${configured ? "Amaranth 10 해외 출고 · 최신성/품질" : "Amaranth API 설정 필요"}</strong><span>${escapeHtml(detail)}</span><span>${escapeHtml(latestShip)} · ${escapeHtml(freshness.message || "상태 미확인")}${escapeHtml(qualityNote)}</span><span class="erp-filter-note">${escapeHtml(mappingNote + officialNote + sampleNote + legacyJpyNote)}JPY는 1엔 기준만 허용하며 거래통화금액은 환종별로만 표시합니다.</span></div><span class="erp-badge">${freshness.status === "normal" ? "CURRENT" : freshness.status === "stale" ? "STALE" : configured ? "READY" : "NOT READY"}</span>`;
}

async function loadSales() {
  try {
    state.sales = await api(salesApiPath());
    renderSales();
    renderOverview();
  } catch (error) { toast(error.message, "error"); }
}

function renderRecordView() {
  const config = recordConfig[state.currentEntity];
  if (!config) return;
  $("#recordEyebrow").textContent = config.eyebrow;
  $("#recordTitle").textContent = config.title;
  $("#recordDescription").textContent = config.description;
  $("#recordSearch").placeholder = state.currentEntity === "task" ? "필드, 국가, 업체명, 업무 제목, 담당자 검색" : "제목, 거래처, 국가, 담당자 검색";
  const filter = $("#recordStatusFilter");
  filter.innerHTML = '<option value="">모든 상태</option>' + config.statuses.map(status => `<option value="${status}">${statusLabels[status] || status}</option>`).join("");
  const specialized = ["cash_plan", "receivable", "promotion"].includes(state.currentEntity);
  $$(".special-record-filter").forEach(node => node.classList.toggle("hidden", !specialized));
  $("#accountMasterFilters").classList.toggle("hidden", state.currentEntity !== "account");
  if (state.currentEntity === "account") populateAccountMasterFilters();
  if (!specialized) {
    $("#recordMonthFilter").value = todayIso().slice(0, 7);
    $("#recordSegmentFilter").value = "all";
  }
  renderCountryFilterChips();
  renderRecordModuleSummary();
  renderRecordTable();
}

function accountSummary(accountId) {
  return state.accountSummaries.find(row => row.id === accountId) || {};
}

function populateSelectOptions(select, values, emptyLabel) {
  const current = select.value;
  select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>` + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  if (values.includes(current)) select.value = current;
}

function populateAccountMasterFilters() {
  const regions = [...new Set(state.accountSummaries.map(row => row.region).filter(Boolean))];
  const order = ["중동", "동유럽", "서유럽", "아프리카", "북미", "남미", "오세아니아", "아시아", "미지정"];
  regions.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  populateSelectOptions($("#accountRegionFilter"), regions, "전체 권역");
  populateAccountCountryFilter();
  const owners = [...new Set(state.accountSummaries.map(row => row.owner_name).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  populateSelectOptions($("#accountOwnerFilter"), owners, "전체 담당자");
}

function populateAccountCountryFilter() {
  const region = $("#accountRegionFilter").value;
  const countries = [...new Set(state.accountSummaries.filter(row => !region || row.region === region).map(row => row.country).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  populateSelectOptions($("#accountCountryFilter"), countries, "전체 국가");
}

function effectiveRecordStatus(row) {
  if (row.entity_type !== "receivable") return row.status;
  const detail = receivableSchedule(row);
  if (detail.balance <= 0.01) return "paid";
  if (truthy(row.payload?.legal_review) || row.payload?.risk_level === "legal") return "legal";
  if (truthy(row.payload?.shipment_hold)) return "hold";
  if (detail.maxOverdueDays > 0) return "overdue";
  if (row.payload?.collection_status === "promise_received") return "promise";
  if (detail.next?.dueDate && detail.next.dueDate <= todayIso()) return "due";
  if (detail.collected > 0) return "partial_paid";
  return "current";
}

function recordMonthValue(row) {
  const payload = row.payload || {};
  if (row.entity_type === "cash_plan") return String(payload.plan_date || payload.execution_date || payload.maturity_date || row.due_date || "").slice(0, 7);
  if (row.entity_type === "promotion") return payload.target_month || String(payload.target_ship_date || payload.end_date || row.due_date || "").slice(0, 7);
  return String(payload.invoice_date || payload.ship_date || row.due_date || "").slice(0, 7);
}

function moduleRows(entityType = state.currentEntity) {
  const segment = $("#recordSegmentFilter")?.value || "all";
  return state.records.filter(row => row.entity_type === entityType && (segment === "all" || row.payload?.business_unit === segment));
}

function summaryCard(label, value, note, tone = "") {
  return `<div class="module-summary-card ${escapeHtml(tone)}"><span>${escapeHtml(label)}</span><strong>${value}</strong><small>${escapeHtml(note)}</small></div>`;
}

function renderCashPlanSummary(rows, month) {
  const summary = cashPlanSummary(rows, month);
  const outRows = summary.selected.filter(row => row.payload?.flow_type === "cash_out");
  const variableOut = outRows.filter(row => row.payload?.cost_nature === "variable").reduce((sum, row) => sum + recordKrwAmount(row, null, row.payload?.exchange_rate), 0);
  const fixedOut = outRows.filter(row => row.payload?.cost_nature === "fixed").reduce((sum, row) => sum + recordKrwAmount(row, null, row.payload?.exchange_rate), 0);
  const carried = summary.selected.filter(row => truthy(row.payload?.previous_month_carryover) || truthy(row.payload?.current_month_carryover) || row.status === "carried_over").length;
  const splitCount = summary.selected.filter(row => truthy(row.payload?.split_payment)).length;
  const pending = summary.selected.filter(row => !["executed", "cancelled"].includes(row.status)).length;
  return `<div class="module-summary-cards">${[
    summaryCard("조정 예상 수금", formatMoney(summary.adjustedIn), `실제 ${formatMoney(summary.actualIn)}`, "in"),
    summaryCard("조정 예상 지출", formatMoney(summary.adjustedOut), `실제 ${formatMoney(summary.actualOut)}`, "out"),
    summaryCard("월간 예상 순증감", formatMoney(summary.adjustedIn - summary.adjustedOut), `계획 ${formatMoney(summary.plannedIn - summary.plannedOut)}`, summary.adjustedIn - summary.adjustedOut < 0 ? "danger" : "net"),
    summaryCard("월말 예상 총자금", formatMoney(summary.forecastTotal), `유동 ${formatMoney(summary.forecastLiquid)} · 고정 ${formatMoney(summary.fixed)}`, "total"),
  ].join("")}</div><div class="module-breakdown-grid">
    <div><span>계획 대비 수금 실행률</span><strong>${formatNumber(summary.adjustedIn ? summary.actualIn / summary.adjustedIn * 100 : 0, 1)}%</strong><small>${formatMoney(summary.actualIn)} / ${formatMoney(summary.adjustedIn)}</small></div>
    <div><span>계획 대비 지출 실행률</span><strong>${formatNumber(summary.adjustedOut ? summary.actualOut / summary.adjustedOut * 100 : 0, 1)}%</strong><small>${formatMoney(summary.actualOut)} / ${formatMoney(summary.adjustedOut)}</small></div>
    <div><span>고정비 / 변동비 계획</span><strong>${formatMoney(fixedOut)}</strong><small>변동비 ${formatMoney(variableOut)}</small></div>
    <div><span>미집행·이월 점검</span><strong>${formatNumber(pending)}건</strong><small>이월 ${formatNumber(carried)}건 · 분할 ${formatNumber(splitCount)}건</small></div>
  </div>`;
}

function renderReceivableSummary(rows, month) {
  const summary = receivableSummary(rows);
  const expectedMonth = summary.details.reduce((sum, item) => sum + item.schedules.filter(schedule => String(schedule.dueDate || "").startsWith(month)).reduce((part, schedule) => part + recordKrwAmount(item.row, schedule.plannedAmount, item.row.payload?.receivable_exchange_rate), 0), 0);
  const collectedMonth = summary.details.reduce((sum, item) => sum + item.schedules.filter(schedule => String(schedule.receivedDate || "").startsWith(month)).reduce((part, schedule) => part + recordKrwAmount(item.row, schedule.receivedAmount, item.row.payload?.receivable_exchange_rate), 0), 0);
  const aging = { not_due: 0, days_1_29: 0, days_30_59: 0, days_60_89: 0, over_90: 0, over_365: 0 };
  summary.details.forEach(item => item.unpaid.forEach(schedule => {
    let key = "not_due";
    if (schedule.overdueDays >= 365) key = "over_365";
    else if (schedule.overdueDays >= 90) key = "over_90";
    else if (schedule.overdueDays >= 60) key = "days_60_89";
    else if (schedule.overdueDays >= 30) key = "days_30_59";
    else if (schedule.overdueDays > 0) key = "days_1_29";
    aging[key] += recordKrwAmount(item.row, schedule.remaining, item.row.payload?.receivable_exchange_rate);
  }));
  const holdCount = summary.details.filter(item => truthy(item.row.payload?.shipment_hold)).length;
  const approvalCount = summary.details.filter(item => truthy(item.row.payload?.representative_approval) || item.maxOverdueDays >= 90).length;
  return `<div class="module-summary-cards five">${[
    summaryCard("채권 총액", formatMoney(summary.total), `${formatNumber(rows.length)}건`, "total"),
    summaryCard("누적 수금액", formatMoney(summary.collected), `회수율 ${formatNumber(summary.collectionRate, 1)}%`, "in"),
    summaryCard("미수금 잔액", formatMoney(summary.balance), `7일 내 ${formatMoney(summary.dueWeek)}`, "net"),
    summaryCard("연체채권", formatMoney(summary.overdue), `P1·90일+ ${formatNumber(summary.p1Count)}건`, summary.overdue ? "danger" : ""),
    summaryCard(`${Number(month.slice(5))}월 수금계획`, formatMoney(expectedMonth), `실제 ${formatMoney(collectedMonth)}`, "receivable"),
  ].join("")}</div><div class="aging-strip">
    ${[["만기 미도래", aging.not_due], ["1~29일", aging.days_1_29], ["30~59일", aging.days_30_59], ["60~89일", aging.days_60_89], ["90일 이상", aging.over_90], ["12개월 이상", aging.over_365]].map(([label, value], index) => `<div class="${index >= 4 && value ? "risk" : ""}"><span>${label}</span><strong>${formatMoney(value)}</strong></div>`).join("")}
  </div><div class="module-policy-note"><strong>회수조치 점검</strong><span>신규출고 보류 ${formatNumber(holdCount)}건 · 추가여신 대표 승인 대상 ${formatNumber(approvalCount)}건 · 회수약속 미이행과 90일 이상 채권은 아침회의에 우선 표시됩니다.</span></div>`;
}

function renderPromotionSummary(rows, month) {
  const summary = promotionSummary(rows, month);
  const budget = summary.selected.reduce((sum, row) => sum + recordKrwAmount(row, row.payload?.budget_amount), 0);
  const forecastCount = summary.selected.filter(row => truthy(row.payload?.forecast_included)).length;
  const statusCounts = ["planned", "approved", "running", "completed"].map(status => [status, summary.selected.filter(row => row.status === status).length]);
  return `<div class="module-summary-cards">${[
    summaryCard("프로모션 목표매출", formatMoney(summary.target), `${formatNumber(summary.selected.length)}건`, "total"),
    summaryCard("달성매출", formatMoney(summary.achieved), `달성률 ${formatNumber(summary.achievementRate, 1)}%`, "in"),
    summaryCard("프로모션 예산", formatMoney(budget), `목표 대비 ${formatNumber(summary.target ? budget / summary.target * 100 : 0, 1)}%`, "out"),
    summaryCard("진행·종료 임박", `${formatNumber(summary.active.length)}건`, `14일 내 종료 ${formatNumber(summary.endingSoon)}건 · FCST ${formatNumber(forecastCount)}건`, summary.endingSoon ? "danger" : "promotion"),
  ].join("")}</div><div class="status-stage-strip">${statusCounts.map(([status, count]) => `<div><span>${escapeHtml(statusLabels[status])}</span><strong>${formatNumber(count)}</strong></div>`).join("")}</div><div class="module-policy-note"><strong>자동 연결</strong><span>목표매출은 매출 반영월의 최신 FCST 차수에 프로모션 ID로 연결됩니다. 프로모션에서 수정하면 FCST도 함께 갱신되고, 취소·삭제하면 열린 차수에서 제외됩니다.</span></div>`;
}

function renderRecordModuleSummary() {
  const container = $("#recordModuleSummary");
  const month = $("#recordMonthFilter")?.value || todayIso().slice(0, 7);
  const rows = moduleRows();
  if (state.currentEntity === "cash_plan") container.innerHTML = renderCashPlanSummary(rows, month);
  else if (state.currentEntity === "receivable") container.innerHTML = renderReceivableSummary(rows, month);
  else if (state.currentEntity === "promotion") container.innerHTML = renderPromotionSummary(rows, month);
  else container.innerHTML = "";
  container.classList.toggle("hidden", !["cash_plan", "receivable", "promotion"].includes(state.currentEntity));
}

function filteredRecords() {
  const query = $("#recordSearch").value.trim().toLowerCase();
  const status = $("#recordStatusFilter").value;
  const month = $("#recordMonthFilter")?.value || "";
  const segment = $("#recordSegmentFilter")?.value || "all";
  const countryIds = new Set(state.recordCountryFilter?.record_ids || []);
  const accountIds = new Set(state.recordCountryFilter?.account_ids || []);
  const accountRegion = $("#accountRegionFilter")?.value || "";
  const accountCountry = $("#accountCountryFilter")?.value || "";
  const accountOwner = $("#accountOwnerFilter")?.value || "";
  return state.records.filter(row => {
    if (row.entity_type !== state.currentEntity) return false;
    if (status && effectiveRecordStatus(row) !== status) return false;
    if (segment !== "all" && row.payload?.business_unit !== segment) return false;
    const recordMonth = recordMonthValue(row);
    if (month && ["cash_plan", "promotion"].includes(row.entity_type) && recordMonth && recordMonth !== month) return false;
    if (state.recordCountryFilter && !countryIds.has(row.id) && !accountIds.has(row.id) && !accountIds.has(row.payload?.account_id)) return false;
    if (row.entity_type === "account") {
      const summary = accountSummary(row.id);
      if (accountRegion && summary.region !== accountRegion) return false;
      if (accountCountry && summary.country !== accountCountry) return false;
      if (accountOwner && summary.owner_name !== accountOwner) return false;
    }
    if (!query) return true;
    return [row.title, row.owner_name, row.region, row.country, row.payload?.account_name, row.payload?.company_name, row.payload?.description,
      row.payload?.counterparty, row.payload?.invoice_no, row.payload?.shipment_no, row.payload?.promotion_id,
      row.payload?.item_name, row.payload?.recovery_plan, row.payload?.promotion_terms, row.payload?.representative_name,
      row.payload?.account_contact_name, row.payload?.contact_phone, row.payload?.contact_email, row.payload?.address,
    ].some(value => String(value || "").toLowerCase().includes(query));
  });
}

function renderAccountMasterTable(rows) {
  const sort = $("#accountSort").value || "sales_desc";
  const sorted = [...rows].sort((a, b) => {
    const aSummary = accountSummary(a.id);
    const bSummary = accountSummary(b.id);
    if (sort === "sales_asc") return Number(aSummary.average_annual_sales_5y || 0) - Number(bSummary.average_annual_sales_5y || 0) || a.title.localeCompare(b.title, "ko");
    if (sort === "first_asc") return String(aSummary.first_transaction_year || "9999").localeCompare(String(bSummary.first_transaction_year || "9999")) || a.title.localeCompare(b.title, "ko");
    if (sort === "name_asc") return a.title.localeCompare(b.title, "ko");
    if (sort === "owner_asc") return String(aSummary.owner_name || "").localeCompare(String(bSummary.owner_name || ""), "ko") || a.title.localeCompare(b.title, "ko");
    if (sort === "region_asc") return String(aSummary.region || "").localeCompare(String(bSummary.region || ""), "ko") || a.title.localeCompare(b.title, "ko");
    if (sort === "country_asc") return String(aSummary.country || "").localeCompare(String(bSummary.country || ""), "ko") || a.title.localeCompare(b.title, "ko");
    return Number(bSummary.average_annual_sales_5y || 0) - Number(aSummary.average_annual_sales_5y || 0) || a.title.localeCompare(b.title, "ko");
  });
  $("#recordTableHead").innerHTML = '<tr><th>거래처</th><th>담당자</th><th>권역</th><th>국가</th><th>연평균매출액</th><th>최초거래연도</th><th>상태</th><th>관리</th></tr>';
  $("#recordTableBody").innerHTML = sorted.length ? sorted.map(row => {
    const summary = accountSummary(row.id);
    const canModify = Boolean(state.permissions.can_edit_all || (state.me?.role === "editor" && (row.owner_id === state.me.id || row.created_by === state.me.id)));
    const editActions = canModify ? `<button class="mini-btn" data-action="edit" data-id="${escapeHtml(row.id)}">수정</button><button class="mini-btn danger" data-action="delete" data-id="${escapeHtml(row.id)}">삭제</button>` : "";
    return `<tr class="clickable-table-row" data-action="journey" data-id="${escapeHtml(row.id)}"><td class="table-title"><button type="button" class="table-link table-link-strong" data-action="journey" data-id="${escapeHtml(row.id)}">${escapeHtml(row.title)}</button><span class="table-sub">${escapeHtml(row.payload?.main_items || row.payload?.account_notes || "")}</span></td><td>${escapeHtml(summary.owner_name || row.owner_name || "미지정")}</td><td>${escapeHtml(summary.region || "미지정")}</td><td>${escapeHtml(summary.country || row.country || "미지정")}</td><td><strong>${formatMoney(summary.average_annual_sales_5y || 0)}</strong><span class="table-sub">최근 5개년 평균</span></td><td>${escapeHtml(summary.first_transaction_year || "—")}<span class="table-sub">최근 ${summary.last_transaction_date ? formatDate(summary.last_transaction_date) : "거래 없음"}</span></td><td>${badge(row.status)}</td><td><div class="table-actions"><button class="mini-btn emphasis" data-action="journey" data-id="${escapeHtml(row.id)}">상세</button>${editActions}</div></td></tr>`;
  }).join("") : '<tr><td colspan="8"><div class="empty-state">선택 조건의 거래처가 없습니다.</div></td></tr>';
}

function canModifyRecord(row) {
  return Boolean(state.permissions.can_edit_all || (state.me?.role === "editor" && (row.owner_id === state.me.id || row.created_by === state.me.id)));
}

function taskGroupSummary(parent, children) {
  if (!children.length) return {
    status: parent.status,
    owner: parent.owner_name || "미지정",
    dueDate: parent.due_date,
    amount: Number(parent.amount || 0),
    currency: parent.currency || "USD",
    updatedAt: parent.updated_at,
    done: 0,
  };
  const done = children.filter(row => ["done", "completed"].includes(row.status)).length;
  const open = children.filter(row => !["done", "completed", "cancelled", "closed"].includes(row.status));
  const status = done === children.length ? "done" : children.some(row => row.status === "blocked") ? "blocked" : children.some(row => row.status === "in_progress") ? "in_progress" : "todo";
  const ownerNames = [...new Set(children.map(row => row.owner_name || "미지정"))];
  const dueDates = (open.length ? open : children).map(row => row.due_date).filter(Boolean).sort();
  const currencies = [...new Set(children.map(row => row.currency || "USD"))];
  return {
    status,
    owner: ownerNames.length <= 2 ? ownerNames.join(" · ") : `${ownerNames.slice(0, 2).join(" · ")} 외 ${ownerNames.length - 2}명`,
    dueDate: dueDates[0] || parent.due_date,
    amount: children.reduce((sum, row) => sum + Number(row.amount || 0), 0),
    currency: currencies.length === 1 ? currencies[0] : parent.currency || "USD",
    updatedAt: [parent, ...children].map(row => row.updated_at || "").sort().at(-1),
    done,
  };
}

function taskField(row, parent = null) {
  const value = row.payload?.business_unit || parent?.payload?.business_unit || "unclassified";
  return segmentLabels[value] || value || "미분류";
}

function taskCountry(row, parent = null) {
  return row.country || parent?.country || "미입력";
}

function taskCompany(row, parent = null) {
  return row.payload?.company_name || row.payload?.account_name || parent?.payload?.company_name || parent?.payload?.account_name || "미입력";
}

function taskSortHeader(key, label) {
  const active = state.taskSort.key === key;
  const direction = active ? state.taskSort.direction : "none";
  const icon = !active ? "↕" : direction === "asc" ? "↑" : "↓";
  return `<th aria-sort="${direction === "none" ? "none" : direction === "asc" ? "ascending" : "descending"}"><button type="button" class="task-sort-button ${active ? "active" : ""}" data-task-sort="${escapeHtml(key)}">${escapeHtml(label)}<span aria-hidden="true">${icon}</span></button></th>`;
}

function compareTaskValues(a, b, direction) {
  const factor = direction === "asc" ? 1 : -1;
  if (typeof a === "number" && typeof b === "number") return (a - b) * factor;
  return String(a ?? "").localeCompare(String(b ?? ""), "ko", { numeric: true, sensitivity: "base" }) * factor;
}

function taskGroupSortValue(parent, children, key) {
  const summary = taskGroupSummary(parent, children);
  if (key === "field") return taskField(parent);
  if (key === "country") return taskCountry(parent);
  if (key === "company") return taskCompany(parent);
  if (key === "status") return statusLabels[summary.status] || summary.status;
  if (key === "owner") return summary.owner;
  if (key === "dueDate") return summary.dueDate || "9999-12-31";
  if (key === "amount") return Number(summary.amount || 0);
  return summary.updatedAt || "";
}

function handleTaskSort(event) {
  const button = event.target.closest("[data-task-sort]");
  if (!button || state.currentEntity !== "task") return;
  const key = button.dataset.taskSort;
  if (state.taskSort.key === key) state.taskSort.direction = state.taskSort.direction === "asc" ? "desc" : "asc";
  else state.taskSort = { key, direction: ["dueDate", "updatedAt", "amount"].includes(key) ? "desc" : "asc" };
  renderRecordTable();
}

function renderTaskRecordTable(filteredRows) {
  const allTasks = state.records.filter(row => row.entity_type === "task");
  const allTaskIds = new Set(allTasks.map(row => row.id));
  const matchingIds = new Set(filteredRows.map(row => row.id));
  const childrenByParent = new Map();
  allTasks.forEach(row => {
    const parentId = row.payload?.parent_task_id;
    if (!parentId || !allTaskIds.has(parentId)) return;
    if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
    childrenByParent.get(parentId).push(row);
  });
  childrenByParent.forEach(children => children.sort((a, b) => Number(a.payload?.task_order || 9999) - Number(b.payload?.task_order || 9999) || String(a.due_date || "9999").localeCompare(String(b.due_date || "9999"))));
  const parents = allTasks.filter(row => !row.payload?.parent_task_id || !allTaskIds.has(row.payload.parent_task_id)).filter(parent => {
    if (matchingIds.has(parent.id)) return true;
    return (childrenByParent.get(parent.id) || []).some(child => matchingIds.has(child.id));
  }).sort((a, b) => {
    const comparison = compareTaskValues(
      taskGroupSortValue(a, childrenByParent.get(a.id) || [], state.taskSort.key),
      taskGroupSortValue(b, childrenByParent.get(b.id) || [], state.taskSort.key),
      state.taskSort.direction,
    );
    return comparison || a.title.localeCompare(b.title, "ko");
  });
  const detailCount = parents.reduce((sum, parent) => sum + (childrenByParent.get(parent.id) || []).length, 0);
  $("#recordCount").textContent = `대분류 ${parents.length}건 · 세부항목 ${detailCount}건`;
  $("#recordTableHead").innerHTML = `<tr>${taskSortHeader("field", "필드")}${taskSortHeader("country", "국가")}${taskSortHeader("company", "업체명")}${taskSortHeader("status", "상태")}${taskSortHeader("owner", "담당자")}${taskSortHeader("dueDate", "기한")}${taskSortHeader("amount", "금액 / 조건")}${taskSortHeader("updatedAt", "최근 수정")}<th>관리</th></tr>`;
  if (!parents.length) {
    $("#recordTableBody").innerHTML = '<tr><td colspan="9"><div class="empty-state">선택 조건의 주요 업무가 없습니다.</div></td></tr>';
    return;
  }
  $("#recordTableBody").innerHTML = parents.map(parent => {
    const children = childrenByParent.get(parent.id) || [];
    const expanded = state.expandedTaskGroups.has(parent.id);
    const summary = taskGroupSummary(parent, children);
    const description = parent.payload?.description || "";
    const canModify = canModifyRecord(parent);
    const amount = summary.amount ? formatMoney(summary.amount, summary.currency) : "—";
    const controls = canModify ? `<div class="table-actions task-group-actions"><button class="mini-btn emphasis" data-action="add-task-child" data-id="${escapeHtml(parent.id)}">+ 세부항목</button><button class="mini-btn" data-action="edit" data-id="${escapeHtml(parent.id)}">수정</button><button class="mini-btn danger" data-action="delete" data-id="${escapeHtml(parent.id)}">삭제</button></div>` : '<span class="muted">조회 전용</span>';
    const parentRow = `<tr class="task-group-row ${expanded ? "expanded" : ""}" data-action="toggle-task-group" data-id="${escapeHtml(parent.id)}"><td><button type="button" class="task-group-toggle" data-action="toggle-task-group" data-id="${escapeHtml(parent.id)}" aria-expanded="${expanded}"><span class="task-group-arrow">›</span><strong>${escapeHtml(taskField(parent))}</strong></button><span class="table-sub">세부항목 ${children.length}건 · 완료 ${summary.done}건</span></td><td>${escapeHtml(taskCountry(parent))}</td><td class="table-title task-company-cell"><strong>${escapeHtml(taskCompany(parent))}</strong><span class="table-sub task-title-line">${escapeHtml(parent.title)}</span>${description ? `<span class="table-sub task-multiline">${escapeHtml(description)}</span>` : ""}</td><td>${badge(summary.status)}</td><td>${escapeHtml(summary.owner)}</td><td>${formatDate(summary.dueDate)}</td><td>${escapeHtml(amount)}</td><td>${formatDate(summary.updatedAt)}</td><td>${controls}</td></tr>`;
    if (!expanded) return parentRow;
    if (!children.length) return parentRow + `<tr class="task-detail-empty"><td colspan="9"><div><strong>등록된 세부항목이 없습니다.</strong><span>오른쪽의 ‘+ 세부항목’을 눌러 첫 항목을 입력하세요.</span></div></td></tr>`;
    const childRows = children.map((child, index) => {
      const childCanModify = canModifyRecord(child);
      const childDescription = child.payload?.description || "";
      const childAmount = Number(child.amount) ? formatMoney(child.amount, child.currency) : "—";
      const childControls = childCanModify ? `<div class="table-actions task-detail-actions"><button class="mini-btn" data-action="edit" data-id="${escapeHtml(child.id)}">수정</button><button class="mini-btn danger" data-action="delete" data-id="${escapeHtml(child.id)}">삭제</button></div>` : '<span class="muted">조회 전용</span>';
      return `<tr class="task-detail-row"><td><div class="task-detail-title"><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(taskField(child, parent))}</strong></div></td><td>${escapeHtml(taskCountry(child, parent))}</td><td class="table-title task-company-cell"><strong>${escapeHtml(taskCompany(child, parent))}</strong><span class="table-sub task-title-line">${escapeHtml(child.title)}</span>${childDescription ? `<span class="table-sub task-multiline">${escapeHtml(childDescription)}</span>` : ""}</td><td>${badge(child.status)}</td><td>${escapeHtml(child.owner_name || "미지정")}</td><td>${formatDate(child.due_date)}</td><td>${escapeHtml(childAmount)}</td><td>${formatDate(child.updated_at)}</td><td>${childControls}</td></tr>`;
    }).join("");
    return parentRow + childRows;
  }).join("");
}

function renderRecordTable() {
  const rows = filteredRecords();
  $("#recordCount").textContent = `총 ${rows.length}건`;
  if (state.currentEntity === "account") {
    renderAccountMasterTable(rows);
    return;
  }
  if (state.currentEntity === "task") {
    renderTaskRecordTable(rows);
    return;
  }
  const isPipeline = state.currentEntity === "pipeline";
  const isTask = ["task", "agenda"].includes(state.currentEntity);
  const financeSpecialized = ["cash_plan", "receivable", "promotion"].includes(state.currentEntity);
  const specialized = ["goal", "activity", "order", "account"].includes(state.currentEntity);
  if (financeSpecialized) {
    renderFinanceRecordTable(rows);
    return;
  }
  $("#recordTableHead").innerHTML = specialized
    ? `<tr><th>항목</th><th>상태</th><th>담당자</th><th>${state.currentEntity === "account" ? "권역 / 국가" : "거래처 / 사업분야"}</th><th>${state.currentEntity === "goal" ? "점검·목표일" : state.currentEntity === "order" ? "수주 단계" : state.currentEntity === "activity" ? "접촉·후속조치" : "영업 진행"}</th><th>${state.currentEntity === "goal" ? "달성률" : "금액 / 목표일"}</th><th>최근 수정</th><th>관리</th></tr>`
    : `<tr><th>항목</th><th>상태</th><th>담당자</th><th>${isTask ? "기한" : "권역 / 국가"}</th>${isPipeline ? "<th>금액</th><th>확률</th>" : "<th>금액 / 조건</th>"}<th>최근 수정</th><th>관리</th></tr>`;
  $("#recordTableBody").innerHTML = rows.length ? rows.map(row => {
    const canModify = Boolean(state.permissions.can_edit_all || (state.me?.role === "editor" && (row.owner_id === state.me.id || row.created_by === state.me.id)));
    const description = row.payload?.description || row.payload?.next_action || row.payload?.contact || "";
    const location = isTask ? formatDate(row.due_date) : [row.region, row.country].filter(Boolean).join(" / ") || "—";
    const amount = Number(row.amount) ? formatMoney(row.amount, row.currency) : (row.payload?.incoterms || row.payload?.channel || "—");
    const probability = isPipeline ? `<td>${row.payload?.probability ?? 0}%</td>` : "";
    const editActions = canModify ? `<button class="mini-btn" data-action="edit" data-id="${row.id}">수정</button><button class="mini-btn danger" data-action="delete" data-id="${row.id}">삭제</button>` : "";
    const journeyAction = row.entity_type === "account" ? `<button class="mini-btn emphasis" data-action="journey" data-id="${row.id}">매출·이력</button>` : "";
    const actions = `<div class="table-actions">${journeyAction}${editActions || (!journeyAction ? '<span class="muted">조회 전용</span>' : "")}</div>`;
    const titleHtml = row.entity_type === "account"
      ? `<button type="button" class="table-link table-link-strong" data-action="journey" data-id="${escapeHtml(row.id)}">${escapeHtml(row.title)}</button>`
      : escapeHtml(row.title);
    if (specialized) {
      let relation = [row.payload?.account_name, segmentLabels[row.payload?.business_unit]].filter(Boolean).join(" / ") || "—";
      let milestone = "—";
      let valueHtml = escapeHtml(Number(row.amount) ? formatMoney(row.amount, row.currency) : "—");
      if (row.entity_type === "account") {
        relation = [row.region, row.country].filter(Boolean).join(" / ") || "—";
        const linked = linkedAccountRecords(row.id);
        milestone = `영업활동 ${linked.filter(item => item.entity_type === "activity").length} · 수주 ${linked.filter(item => item.entity_type === "order" && !isClosedRecord(item)).length}`;
        valueHtml = escapeHtml(row.payload?.priority || row.payload?.contact || "—");
      } else if (row.entity_type === "goal") {
        relation = `${goalTypeLabel(row.payload?.goal_type)}${row.payload?.business_unit ? ` / ${segmentLabels[row.payload.business_unit]}` : ""}`;
        milestone = `점검 ${row.payload?.mid_review_date ? formatDate(row.payload.mid_review_date) : "미지정"}<span class="table-sub">수정목표 ${row.payload?.revised_target_date ? formatDate(row.payload.revised_target_date) : row.payload?.original_target_date ? formatDate(row.payload.original_target_date) : "미지정"}</span>`;
        valueHtml = goalProgress(row);
      } else if (row.entity_type === "activity") {
        milestone = `${activityLabels[row.payload?.activity_type] || "영업 활동"}<span class="table-sub">${row.payload?.activity_at ? formatDate(row.payload.activity_at, true) : formatDate(row.due_date)}</span>`;
        valueHtml = escapeHtml(row.payload?.next_action_date ? formatDate(row.payload.next_action_date) : "후속일 미지정");
      } else if (row.entity_type === "order") {
        milestone = orderProgressHtml(row);
        valueHtml = escapeHtml(row.payload?.next_target_date ? formatDate(row.payload.next_target_date) : "다음 목표일 미지정");
      }
      return `<tr><td class="table-title">${titleHtml}${description ? `<span class="table-sub">${escapeHtml(description)}</span>` : ""}</td><td>${badge(row.status)}</td><td>${escapeHtml(row.owner_name || "미지정")}</td><td>${escapeHtml(relation)}</td><td>${milestone}</td><td>${valueHtml}</td><td>${formatDate(row.updated_at)}</td><td>${actions}</td></tr>`;
    }
    return `<tr><td class="table-title">${escapeHtml(row.title)}${description ? `<span class="table-sub">${escapeHtml(description)}</span>` : ""}</td><td>${badge(row.status)}</td><td>${escapeHtml(row.owner_name || "미지정")}</td><td>${escapeHtml(location)}</td><td>${escapeHtml(amount)}</td>${probability}<td>${formatDate(row.updated_at)}</td><td>${actions}</td></tr>`;
  }).join("") : `<tr><td colspan="8"><div class="empty-state">등록된 ${escapeHtml(recordConfig[state.currentEntity].title)} 데이터가 없습니다.</div></td></tr>`;
}

function recordActionMarkup(row, canModify, extra = "") {
  const edit = canModify ? `<button class="mini-btn" data-action="edit" data-id="${row.id}">수정</button><button class="mini-btn danger" data-action="delete" data-id="${row.id}">삭제</button>` : "";
  return `<div class="table-actions finance-actions">${canModify ? extra : ""}${edit || '<span class="muted">조회 전용</span>'}</div>`;
}

function financeRecordPermissions(row) {
  return Boolean(state.permissions.can_edit_all || (state.me?.role === "editor" && (row.owner_id === state.me.id || row.created_by === state.me.id)));
}

function promotionMilestone(row) {
  const payload = row.payload || {};
  const stages = [
    ["조건 제안", "proposal_target_date", "proposal_actual_date"], ["내부 승인", "approval_target_date", "approval_actual_date"],
    ["거래처 제안", "offer_target_date", "offer_actual_date"], ["오더·PI", "order_target_date", "order_actual_date"],
    ["수금", "promotion_payment_target_date", "promotion_payment_actual_date"], ["출고", "promotion_shipment_target_date", "promotion_shipment_actual_date"],
  ];
  const completed = stages.filter(([, , actual]) => payload[actual]).length;
  const next = stages.find(([, , actual]) => !payload[actual]);
  return { completed, total: stages.length, nextLabel: next?.[0] || "종료", nextDate: next ? payload[next[1]] : payload.completed_at };
}

function renderCashPlanRows(rows) {
  $("#recordTableHead").innerHTML = `<tr><th>항목 / 거래처</th><th>구분·상태</th><th>사업분야</th><th>계획·실행일</th><th>계획금액</th><th>조정금액</th><th>실행금액</th><th>결제·이월</th><th>담당자</th><th>관리</th></tr>`;
  $("#recordTableBody").innerHTML = rows.length ? rows.map(row => {
    const payload = row.payload || {};
    const canModify = financeRecordPermissions(row);
    const planKrw = recordKrwAmount(row, null, payload.exchange_rate);
    const rate = payload.flow_type === "cash_out" ? numeric(payload.payment_rate, 100) : numeric(payload.adjustment_rate, 100);
    const adjusted = planKrw * rate / 100;
    const actual = numeric(payload.actual_krw_amount) || recordKrwAmount(row, payload.actual_foreign_amount, payload.exchange_rate) || (row.status === "executed" ? planKrw : 0);
    const execute = !["executed", "cancelled"].includes(row.status) ? `<button class="mini-btn emphasis" data-action="execute" data-id="${row.id}">실행완료</button>` : "";
    const carry = [truthy(payload.previous_month_carryover) ? "전월이월" : "", truthy(payload.current_month_carryover) ? "차월이월" : "", truthy(payload.intentional_carryover) ? "지급조정" : "", truthy(payload.split_payment) ? "분할" : ""].filter(Boolean).join(" · ") || "—";
    return `<tr><td class="table-title">${escapeHtml(row.title)}<span class="table-sub">${escapeHtml(payload.counterparty || "거래처 미지정")} · ${escapeHtml(cashCategoryLabels[payload.execution_category] || payload.execution_category || "집행항목 미지정")}</span></td><td><strong>${escapeHtml(flowTypeLabels[payload.flow_type] || "—")}</strong><span class="table-sub">${badge(row.status)}</span></td><td>${escapeHtml(segmentLabels[payload.business_unit] || "미지정")}</td><td>${formatDate(payload.plan_date || row.due_date)}<span class="table-sub">실행 ${formatDate(payload.execution_date)}</span></td><td><strong>${formatMoney(row.amount, row.currency)}</strong><span class="table-sub">${formatMoney(planKrw)}</span></td><td><strong>${formatMoney(adjusted)}</strong><span class="table-sub">반영률 ${formatNumber(rate, 1)}%</span></td><td><strong>${formatMoney(actual)}</strong><span class="table-sub">${actual ? `실행률 ${formatNumber(adjusted ? actual / adjusted * 100 : 0, 1)}%` : "미집행"}</span></td><td>${escapeHtml(payload.payment_condition || "—")}<span class="table-sub">${escapeHtml(carry)}</span></td><td>${escapeHtml(row.owner_name || "미지정")}<span class="table-sub">${formatDate(row.updated_at)}</span></td><td>${recordActionMarkup(row, canModify, execute)}</td></tr>`;
  }).join("") : '<tr><td colspan="10"><div class="empty-state">선택한 월의 자금계획이 없습니다.</div></td></tr>';
}

function renderReceivableRows(rows) {
  $("#recordTableHead").innerHTML = `<tr><th>거래처 / 인보이스</th><th>채권상태·위험</th><th>사업분야</th><th>다음 수금일정</th><th>채권 총액</th><th>누적 수금</th><th>미수금 잔액</th><th>회수약속·조치</th><th>담당자</th><th>관리</th></tr>`;
  $("#recordTableBody").innerHTML = rows.length ? rows.map(row => {
    const payload = row.payload || {};
    const detail = receivableSchedule(row);
    const status = effectiveRecordStatus(row);
    const canModify = financeRecordPermissions(row);
    const risk = detail.maxOverdueDays >= 90 && payload.risk_level === "normal" ? "p1" : payload.risk_level || "normal";
    const nextText = detail.next ? `${detail.next.label} ${formatDate(detail.next.dueDate)}` : "예정 없음";
    const overdueText = detail.maxOverdueDays ? `${formatNumber(detail.maxOverdueDays)}일 연체` : detail.agingLabel;
    const approvals = [truthy(payload.shipment_hold) ? "출고보류" : "", truthy(payload.legal_review) ? "법무검토" : "", truthy(payload.representative_approval) || detail.maxOverdueDays >= 90 ? "대표승인" : ""].filter(Boolean).join(" · ");
    return `<tr class="${detail.maxOverdueDays >= 90 ? "risk-row" : ""}"><td class="table-title">${escapeHtml(payload.account_name || row.title)}<span class="table-sub">${escapeHtml(payload.invoice_no || row.title)} · 출고 ${formatDate(payload.ship_date)}</span></td><td>${badge(status)}<span class="table-sub ${detail.maxOverdueDays ? "text-danger" : ""}">${escapeHtml(overdueText)} · ${escapeHtml(riskLevelLabels[risk] || risk)}</span></td><td>${escapeHtml(segmentLabels[payload.business_unit] || "미지정")}</td><td><strong>${escapeHtml(nextText)}</strong><span class="table-sub">${detail.next ? formatMoney(detail.next.remaining, row.currency) : "—"}</span></td><td><strong>${formatMoney(row.amount, row.currency)}</strong><span class="table-sub">${formatMoney(recordKrwAmount(row, null, payload.receivable_exchange_rate))}</span></td><td><strong>${formatMoney(detail.collected, row.currency)}</strong><span class="table-sub">회수율 ${formatNumber(numeric(row.amount) ? detail.collected / numeric(row.amount) * 100 : 0, 1)}%</span></td><td><strong>${formatMoney(detail.balance, row.currency)}</strong><span class="table-sub ${detail.overdueAmount ? "text-danger" : ""}">연체 ${formatMoney(detail.overdueAmount, row.currency)}</span></td><td>${payload.promise_date ? `${formatDate(payload.promise_date)} · ${formatMoney(payload.promise_amount, row.currency)}` : "약속 미등록"}<span class="table-sub">${escapeHtml(approvals || payload.recovery_plan || "회수계획 확인")}</span></td><td>${escapeHtml(row.owner_name || "미지정")}<span class="table-sub">${formatDate(row.updated_at)}</span></td><td>${recordActionMarkup(row, canModify)}</td></tr>`;
  }).join("") : '<tr><td colspan="10"><div class="empty-state">등록된 미수금·채권이 없습니다.</div></td></tr>';
}

function renderPromotionRows(rows) {
  $("#recordTableHead").innerHTML = `<tr><th>ID / 프로모션</th><th>거래처·아이템</th><th>상태·타임라인</th><th>기존가격 → 프로모션</th><th>목표매출</th><th>달성매출</th><th>달성률</th><th>FCST 반영</th><th>담당자</th><th>관리</th></tr>`;
  $("#recordTableBody").innerHTML = rows.length ? rows.map(row => {
    const payload = row.payload || {};
    const canModify = financeRecordPermissions(row);
    const achieved = numeric(payload.achieved_amount);
    const rate = numeric(row.amount) ? achieved / numeric(row.amount) * 100 : 0;
    const milestone = promotionMilestone(row);
    const complete = !["completed", "cancelled"].includes(row.status) ? `<button class="mini-btn emphasis" data-action="complete-promotion" data-id="${row.id}">완료</button>` : "";
    const price = `${payload.baseline_unit_price ? formatMoney(payload.baseline_unit_price, row.currency) : payload.baseline_price_condition || "—"} → ${payload.promotion_unit_price ? formatMoney(payload.promotion_unit_price, row.currency) : payload.promotion_terms || "—"}`;
    return `<tr><td class="table-title">${escapeHtml(payload.promotion_id || "ID 미지정")}<span class="table-sub">${escapeHtml(row.title)}</span></td><td>${escapeHtml(payload.account_name || "거래처 미지정")}<span class="table-sub">${escapeHtml(payload.item_name || "품목 미지정")} · ${escapeHtml(segmentLabels[payload.business_unit] || "미지정")}</span></td><td>${badge(row.status)}<span class="table-sub">${formatNumber(milestone.completed)}/${formatNumber(milestone.total)} · 다음 ${escapeHtml(milestone.nextLabel)} ${milestone.nextDate ? formatDate(milestone.nextDate) : "일정 미지정"}</span></td><td>${price}<span class="table-sub">${escapeHtml(payload.promotion_terms || "추가조건 미입력")}</span></td><td><strong>${formatMoney(row.amount, row.currency)}</strong><span class="table-sub">수량 ${formatNumber(payload.target_units, 2)}</span></td><td><strong>${formatMoney(achieved, row.currency)}</strong><span class="table-sub">수량 ${formatNumber(payload.achieved_units, 2)}</span></td><td><div class="progress-cell"><div><span style="width:${Math.min(100, rate)}%"></span></div><b>${formatNumber(rate, 1)}%</b></div></td><td>${truthy(payload.forecast_included) ? '<span class="badge info">자동반영</span>' : '<span class="badge">미반영</span>'}<span class="table-sub">${escapeHtml(payload.target_month || "월 미지정")} · ${escapeHtml(forecastStageLabels[payload.forecast_stage] || "일반 영업추진")}</span></td><td>${escapeHtml(row.owner_name || "미지정")}<span class="table-sub">종료 ${formatDate(payload.end_date)}</span></td><td>${recordActionMarkup(row, canModify, complete)}</td></tr>`;
  }).join("") : '<tr><td colspan="10"><div class="empty-state">선택한 월의 프로모션이 없습니다.</div></td></tr>';
}

function renderFinanceRecordTable(rows) {
  if (state.currentEntity === "cash_plan") renderCashPlanRows(rows);
  if (state.currentEntity === "receivable") renderReceivableRows(rows);
  if (state.currentEntity === "promotion") renderPromotionRows(rows);
}

function goalTypeLabel(value) {
  return { sales: "매출", pipeline: "파이프라인", account: "거래처", activity: "영업활동", task: "업무" }[value] || "목표";
}

function goalProgress(row) {
  const target = Number(row.payload?.target_value || 0);
  const actual = Number(row.payload?.actual_value || 0);
  const percent = target ? Math.min(999, Math.round((actual / target) * 100)) : Number(row.payload?.probability || 0);
  return `<div class="progress-cell"><div><span style="width:${Math.min(100, percent)}%"></span></div><b>${formatNumber(percent)}%</b><small>${formatNumber(actual, 2)} / ${formatNumber(target, 2)} ${escapeHtml(row.payload?.target_unit || "")}</small></div>`;
}

function orderStepIndex(status) {
  return Math.max(0, orderSteps.findIndex(([key]) => key === status));
}

function orderProgressHtml(row) {
  const current = orderStepIndex(row.status);
  return `<div class="order-progress" aria-label="${escapeHtml(statusLabels[row.status] || row.status)}">${orderSteps.map(([key, label], index) => `<span class="${index <= current && !["on_hold", "cancelled"].includes(row.status) ? "done" : ""}" title="${escapeHtml(label)}"></span>`).join("")}</div><span class="table-sub">${escapeHtml(statusLabels[row.status] || row.status)}</span>`;
}

function linkedAccountRecords(accountId) {
  const account = state.records.find(row => row.id === accountId);
  const accountName = String(account?.title || "").toLowerCase();
  return state.records.filter(row => row.entity_type !== "account" && (
    row.payload?.account_id === accountId ||
    (account && String(row.payload?.account_name || "").toLowerCase() === accountName) ||
    (accountName && String(row.title || "").toLowerCase().includes(accountName))
  ));
}

function ownerOptions(selected) {
  return state.users.filter(user => !user.status || user.status === "active").map(user => `<option value="${user.id}" ${Number(selected) === user.id ? "selected" : ""}>${escapeHtml(user.display_name)} (${escapeHtml(statusLabels[user.role] || user.role)})</option>`).join("");
}

function accountOptions(selected) {
  const masterValues = new Set();
  const masterOptions = (state.customerOptions || []).map(row => {
    const value = row.source_record_id || `cm:${row.id}`;
    masterValues.add(row.source_record_id || "");
    return `<option value="${escapeHtml(value)}" ${selected === value ? "selected" : ""}>${escapeHtml(row.display_name)} · ${escapeHtml(row.headquarters_country || row.sales_region || "국가 미지정")} · ${escapeHtml(row.customer_id)}</option>`;
  }).join("");
  const legacyOptions = state.records.filter(row => row.entity_type === "account" && !masterValues.has(row.id)).sort((a, b) => a.title.localeCompare(b.title, "ko")).map(row => `<option value="${escapeHtml(row.id)}" ${selected === row.id ? "selected" : ""}>${escapeHtml(row.title)} · ${escapeHtml(row.country || row.region || "국가 미지정")} · 기존자료</option>`).join("");
  return '<option value="">거래처 미지정</option>' + masterOptions + legacyOptions;
}

function selectedCustomerMaster(value) {
  return (state.customerOptions || []).find(row => (row.source_record_id || `cm:${row.id}`) === value) || null;
}

function toggleRecordFields(entityType) {
  const commonBusiness = ["account", "goal", "pipeline", "activity", "order", "task", "cash_plan", "receivable", "promotion"].includes(entityType);
  const detailedModule = ["cash_plan", "receivable", "promotion"].includes(entityType);
  $("#recordCommonBusinessFields").classList.toggle("hidden", !commonBusiness);
  $("#recordAccountLinkField").classList.toggle("hidden", entityType === "account");
  $("#recordTaskCompanyField").classList.toggle("hidden", entityType !== "task");
  $("#recordCommonBusinessTitle").textContent = entityType === "task" ? "필드·업체 분류" : "거래처·사업분야";
  $("#recordBusinessUnitLabel").textContent = entityType === "task" ? "필드" : "사업분야";
  $("#recordAccountProfileFields").classList.toggle("hidden", entityType !== "account");
  $("#recordAccountMapFields").classList.toggle("hidden", entityType !== "account");
  $("#recordAccountCommercialFields").classList.toggle("hidden", entityType !== "account");
  $("#recordGoalFields").classList.toggle("hidden", entityType !== "goal");
  $("#recordActivityFields").classList.toggle("hidden", entityType !== "activity");
  $("#recordOrderFields").classList.toggle("hidden", entityType !== "order");
  $("#recordCashPlanFields").classList.toggle("hidden", entityType !== "cash_plan");
  $("#recordReceivableFields").classList.toggle("hidden", entityType !== "receivable");
  $("#recordPromotionFields").classList.toggle("hidden", entityType !== "promotion");
  $("#recordDerivedPreview").classList.toggle("hidden", !detailedModule);
  $("#recordDueDateField").classList.toggle("hidden", detailedModule);
  $("#recordProbabilityField").classList.toggle("hidden", detailedModule);
  $("#recordPriorityField").classList.toggle("hidden", ["receivable", "promotion"].includes(entityType));
  $("#recordAmountLabel").textContent = entityType === "account" ? "수기 기준매출액" : entityType === "cash_plan" ? "계획 금액" : entityType === "receivable" ? "채권 총액" : entityType === "promotion" ? "목표 매출" : "금액";
  if ($("#recordForm").elements.promotion_id) $("#recordForm").elements.promotion_id.required = entityType === "promotion";
  if ($("#recordForm").elements.target_month) $("#recordForm").elements.target_month.required = entityType === "promotion";
  $("#dueDateLabel").textContent = entityType === "goal" ? "최종 목표일" : entityType === "activity" ? "활동 예정일" : entityType === "order" ? "전체 출고 목표일" : entityType === "pipeline" ? "다음 액션 목표일" : "기한";
}

function setFormValue(form, name, value) {
  if (form.elements[name]) form.elements[name].value = value ?? "";
}

function openRecordDialog(record = null, options = {}) {
  const form = $("#recordForm");
  form.reset();
  form.elements.title.placeholder = "";
  $("#recordFormError").textContent = "";
  const config = recordConfig[state.currentEntity];
  const parentTask = options.parentTask || null;
  state.editingPayload = {
    ...(record?.payload || {}),
    ...(parentTask ? { task_kind: "detail", parent_task_id: parentTask.id } : {}),
  };
  toggleRecordFields(state.currentEntity);
  $("#recordDialogTitle").textContent = record ? `${config.title} 수정` : parentTask ? "세부항목 등록" : `${config.title} 등록`;
  form.elements.id.value = record?.id || "";
  form.elements.entity_type.value = state.currentEntity;
  form.elements.status.innerHTML = config.statuses.map(status => `<option value="${status}">${statusLabels[status] || status}</option>`).join("");
  form.elements.owner_id.innerHTML = ownerOptions(record?.owner_id || parentTask?.owner_id || state.me?.id);
  const selectedAccount = record?.payload?.customer_master_id
    ? ((state.customerOptions || []).find(row => row.id === record.payload.customer_master_id)?.source_record_id || `cm:${record.payload.customer_master_id}`)
    : (record?.payload?.account_id || "");
  form.elements.account_id.innerHTML = accountOptions(selectedAccount);
  if (record) {
    form.elements.title.value = record.title || "";
    form.elements.status.value = record.status || config.statuses[0];
    form.elements.owner_id.value = record.owner_id || state.me?.id || "";
    form.elements.due_date.value = record.due_date || "";
    form.elements.region.value = record.region || "";
    form.elements.country.value = record.country || "";
    form.elements.amount.value = record.amount || 0;
    form.elements.currency.value = record.currency || "USD";
    form.elements.description.value = record.payload?.description || record.payload?.next_action || "";
    form.elements.priority.value = record.payload?.priority || "Medium";
    form.elements.probability.value = record.payload?.probability ?? "";
  }
  [...recordTextPayloadFields, ...recordNumericPayloadFields].forEach(name => setFormValue(form, name, record?.payload?.[name] ?? ""));
  recordBooleanPayloadFields.forEach(name => { if (form.elements[name]) form.elements[name].checked = truthy(record?.payload?.[name]); });
  setFormValue(form, "erp_partner_aliases", Array.isArray(record?.payload?.erp_partner_aliases) ? record.payload.erp_partner_aliases.join(", ") : "");
  if (!record) {
    if (state.currentEntity === "goal") setFormValue(form, "goal_type", "sales");
    if (state.currentEntity === "activity") setFormValue(form, "activity_type", "whatsapp");
    if (state.currentEntity === "order") {
      setFormValue(form, "next_target_date", todayIso());
      setFormValue(form, "customer_terms_mode", "default");
      setFormValue(form, "order_collection_basis", "shipment_date");
      setFormValue(form, "order_moq_basis", "paid");
    }
    if (state.currentEntity === "cash_plan") {
      setFormValue(form, "flow_type", "cash_in"); setFormValue(form, "plan_actual_type", "planned");
      setFormValue(form, "adjustment_rate", 100); setFormValue(form, "payment_rate", 100);
      setFormValue(form, "plan_date", todayIso()); setFormValue(form, "currency", "KRW");
    }
    if (state.currentEntity === "receivable") {
      setFormValue(form, "risk_level", "normal"); setFormValue(form, "collection_status", "monitoring");
      setFormValue(form, "currency", "USD"); setFormValue(form, "installment_1_ratio", 100);
    }
    if (state.currentEntity === "promotion") {
      setFormValue(form, "target_month", $("#recordMonthFilter").value || todayIso().slice(0, 7));
      setFormValue(form, "forecast_stage", "sales_activity"); setFormValue(form, "forecast_confidence", 20);
      form.elements.forecast_included.checked = true;
    }
    if (parentTask) {
      setFormValue(form, "owner_id", parentTask.owner_id || state.me?.id || "");
      setFormValue(form, "region", parentTask.region || "");
      setFormValue(form, "country", parentTask.country || "");
      setFormValue(form, "currency", parentTask.currency || "USD");
      setFormValue(form, "business_unit", parentTask.payload?.business_unit || "");
      setFormValue(form, "company_name", parentTask.payload?.company_name || parentTask.payload?.account_name || "");
      form.elements.title.placeholder = `${parentTask.title}의 세부 업무`;
    } else {
      form.elements.title.placeholder = "";
    }
  }
  if (state.me?.role === "editor") form.elements.owner_id.disabled = true;
  else form.elements.owner_id.disabled = false;
  if (state.currentEntity === "order") {
    form.elements.order_terms_change_reason.required = form.elements.customer_terms_mode.value !== "default";
  }
  syncAccountDefaults(form, true, record?.id || "");
  updateRecordDerivedPreview();
  $("#recordDialog").showModal();
}

function setIfAvailable(form, name, value, onlyEmpty = false) {
  const field = form.elements[name];
  if (!field || value === null || value === undefined || value === "") return;
  if (onlyEmpty && field.value !== "") return;
  field.value = value;
}

function syncAccountDefaults(form, onlyEmpty = false, orderRecordId = "") {
  const selected = form.elements.account_id?.value || "";
  const master = selectedCustomerMaster(selected);
  const account = state.records.find(row => row.id === selected && row.entity_type === "account");
  if (!master && !account) {
    if (state.currentEntity === "order") {
      state.currentOrderDefaults = null;
      $("#recordOrderTermsStatus").textContent = "거래처를 선택하면 현재 결제조건과 제품조건을 불러옵니다.";
    }
    return;
  }
  const payload = account?.payload || {};
  setIfAvailable(form, "region", master?.sales_region || account?.region, onlyEmpty);
  setIfAvailable(form, "country", master?.headquarters_country || account?.country, onlyEmpty);
  setIfAvailable(form, "business_unit", payload.business_unit, onlyEmpty);
  if (state.currentEntity === "task") setIfAvailable(form, "company_name", master?.display_name || account?.title, onlyEmpty);
  if (state.currentEntity === "cash_plan") setIfAvailable(form, "counterparty", master?.display_name || account?.title, onlyEmpty);
  if (state.currentEntity === "receivable") {
    setIfAvailable(form, "payment_condition_label", payload.ar_condition_label, onlyEmpty);
    setIfAvailable(form, "advance_ratio", payload.ar_advance_ratio, onlyEmpty);
    for (let index = 1; index <= 4; index += 1) {
      setIfAvailable(form, `installment_${index}_days`, payload[`ar_installment_${index}_days`], onlyEmpty);
      setIfAvailable(form, `installment_${index}_ratio`, payload[`ar_installment_${index}_ratio`], onlyEmpty);
    }
  }
  if (state.currentEntity === "promotion") {
    setIfAvailable(form, "baseline_price_condition", payload.current_price_condition, onlyEmpty);
  }
  if (state.currentEntity === "order" && master) loadCustomerOrderTerms(form, master, onlyEmpty, orderRecordId);
}

async function loadCustomerOrderTerms(form, master, onlyEmpty = false, orderRecordId = "") {
  const selectedValue = form.elements.account_id?.value || "";
  const statusNode = $("#recordOrderTermsStatus");
  statusNode.textContent = "거래처 기본조건을 불러오는 중입니다.";
  try {
    let snapshot = null;
    if (orderRecordId) snapshot = (await api(`/api/customer-master/order-snapshots/${orderRecordId}`)).snapshot;
    const data = snapshot ? { payment_terms:snapshot.payment_terms, product_terms:snapshot.product_terms } : await api(`/api/customer-master/${master.id}/order-defaults`);
    if ((form.elements.account_id?.value || "") !== selectedValue) return;
    state.currentOrderDefaults = data;
    const payment = data.payment_terms || {}, product = (data.product_terms || [])[0] || {};
    setIfAvailable(form,"order_payment_method",payment.payment_method,onlyEmpty);
    setIfAvailable(form,"order_collection_basis",payment.collection_basis,onlyEmpty);
    setIfAvailable(form,"order_advance_ratio",payment.advance_ratio,onlyEmpty);
    setIfAvailable(form,"order_deferred_days",payment.deferred_days,onlyEmpty);
    setIfAvailable(form,"order_product_name",product.product_name,onlyEmpty);
    setIfAvailable(form,"order_agreed_unit_price",product.agreed_unit_price,onlyEmpty);
    setIfAvailable(form,"order_moq",product.moq,onlyEmpty);
    setIfAvailable(form,"order_moq_basis",product.moq_basis,onlyEmpty);
    setIfAvailable(form,"order_paid_quantity",product.paid_quantity,onlyEmpty);
    setIfAvailable(form,"order_foc_quantity",product.foc_quantity,onlyEmpty);
    const hasTerms = Object.keys(payment).length || (data.product_terms || []).length;
    statusNode.textContent = snapshot
      ? "이 주문에 고정 저장된 조건입니다. 이후 마스터 변경의 영향을 받지 않습니다."
      : hasTerms
        ? `현재 기본조건: ${payment.payment_method || "결제조건 미등록"} · 제품조건 ${(data.product_terms || []).length}건`
        : "등록된 기본조건이 없습니다. 이번 주문만 입력하거나 새 기본조건으로 저장하세요.";
  } catch (error) {
    state.currentOrderDefaults = null;
    statusNode.textContent = error.message;
  }
}

function recordDraft(form = $("#recordForm")) {
  const data = new FormData(form);
  const payload = {};
  recordTextPayloadFields.forEach(name => { payload[name] = data.get(name) || ""; });
  recordNumericPayloadFields.forEach(name => { payload[name] = data.get(name) === "" || data.get(name) === null ? null : numeric(data.get(name)); });
  recordBooleanPayloadFields.forEach(name => { payload[name] = Boolean(form.elements[name]?.checked); });
  return { amount: numeric(data.get("amount")), currency: data.get("currency") || "USD", payload };
}

function updateRecordDerivedPreview() {
  const form = $("#recordForm");
  const container = $("#recordDerivedPreview");
  if (!["cash_plan", "receivable", "promotion"].includes(state.currentEntity)) return;
  const row = recordDraft(form);
  if (form.elements.advance_ratio_shadow) form.elements.advance_ratio_shadow.value = row.payload.advance_ratio ?? "";
  if (state.currentEntity === "cash_plan") {
    const planKrw = recordKrwAmount(row, null, row.payload.exchange_rate);
    const rate = row.payload.flow_type === "cash_out" ? numeric(row.payload.payment_rate, 100) : numeric(row.payload.adjustment_rate, 100);
    const adjusted = planKrw * rate / 100;
    const actual = numeric(row.payload.actual_krw_amount) || recordKrwAmount(row, row.payload.actual_foreign_amount, row.payload.exchange_rate);
    container.innerHTML = `<div><span>계획 원화환산</span><strong>${formatMoney(planKrw)}</strong><small>${row.currency} ${formatNumber(row.amount, 2)} · 환율 ${formatNumber(latestFxRate(row.currency, row.payload.exchange_rate), 2)}</small></div><div><span>조정 반영액</span><strong>${formatMoney(adjusted)}</strong><small>${formatNumber(rate, 1)}% 반영</small></div><div><span>실제 실행액</span><strong>${formatMoney(actual)}</strong><small>${actual ? `계획 대비 ${formatNumber(adjusted ? actual / adjusted * 100 : 0, 1)}%` : "실행 전"}</small></div>`;
  } else if (state.currentEntity === "receivable") {
    const detail = receivableSchedule(row);
    const scheduleText = detail.schedules.map(item => `${item.label} ${item.dueDate ? formatDate(item.dueDate) : "일자 미정"} · ${formatMoney(item.plannedAmount, row.currency)}`).join("<br>") || "수금 비율을 입력하세요.";
    container.innerHTML = `<div><span>자동 수금일정</span><strong>${detail.schedules.length}회</strong><small>${scheduleText}</small></div><div><span>누적 수금 / 잔액</span><strong>${formatMoney(detail.collected, row.currency)}</strong><small>잔액 ${formatMoney(detail.balance, row.currency)}</small></div><div class="${detail.maxOverdueDays ? "danger" : ""}"><span>현재 채권상태</span><strong>${escapeHtml(detail.agingLabel)}</strong><small>${detail.maxOverdueDays ? `${formatNumber(detail.maxOverdueDays)}일 연체 · 독촉·출고보류 검토` : detail.next?.dueDate ? `다음 수금 ${formatDate(detail.next.dueDate)}` : "일정 확인 필요"}</small></div>`;
  } else {
    const target = numeric(row.amount);
    const achieved = numeric(row.payload.achieved_amount);
    const discount = numeric(row.payload.baseline_unit_price) ? (1 - numeric(row.payload.promotion_unit_price) / numeric(row.payload.baseline_unit_price)) * 100 : 0;
    container.innerHTML = `<div><span>프로모션 목표매출</span><strong>${formatMoney(target, row.currency)}</strong><small>${formatNumber(row.payload.target_units, 2)}개 · 단가 ${formatMoney(row.payload.promotion_unit_price, row.currency)}</small></div><div><span>현재 달성</span><strong>${formatNumber(target ? achieved / target * 100 : 0, 1)}%</strong><small>${formatMoney(achieved, row.currency)} · ${formatNumber(row.payload.achieved_units, 2)}개</small></div><div><span>가격·FCST 영향</span><strong>${discount ? `${formatNumber(discount, 1)}% 할인` : "조건 확인"}</strong><small>${truthy(row.payload.forecast_included) ? `${row.payload.target_month || "목표월 미지정"} FCST 자동 반영` : "FCST 미반영"}</small></div>`;
  }
}

function handleRecordFormInput(event) {
  const form = $("#recordForm");
  if (event.target.name === "account_id") syncAccountDefaults(form, false);
  if (state.currentEntity === "order" && event.target.name === "customer_terms_mode") {
    form.elements.order_terms_change_reason.required = event.target.value !== "default";
    $("#recordOrderTermsStatus").classList.toggle("warning-text", event.target.value !== "default");
  }
  if (state.currentEntity === "promotion" && event.target.name === "forecast_stage") {
    form.elements.forecast_confidence.value = forecastStageDefaults[event.target.value] ?? 20;
  }
  if (state.currentEntity === "promotion" && ["promotion_unit_price", "target_units"].includes(event.target.name)) {
    const target = numeric(form.elements.promotion_unit_price.value) * numeric(form.elements.target_units.value);
    if (target > 0) form.elements.amount.value = target;
  }
  if (state.currentEntity === "promotion" && ["promotion_unit_price", "achieved_units"].includes(event.target.name)) {
    const achieved = numeric(form.elements.promotion_unit_price.value) * numeric(form.elements.achieved_units.value);
    if (achieved > 0) form.elements.achieved_amount.value = achieved;
  }
  if (event.target.name === "currency") {
    if (state.currentEntity === "cash_plan" && !numeric(form.elements.exchange_rate.value)) form.elements.exchange_rate.value = latestFxRate(event.target.value) || "";
    if (state.currentEntity === "receivable" && !numeric(form.elements.receivable_exchange_rate.value)) form.elements.receivable_exchange_rate.value = latestFxRate(event.target.value) || "";
  }
  updateRecordDerivedPreview();
}

async function saveRecord(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const id = data.get("id");
  const selectedAccountValue = data.get("account_id") || "";
  const customerMaster = selectedCustomerMaster(selectedAccountValue);
  const account = state.records.find(row => row.id === selectedAccountValue);
  const payload = {
    ...state.editingPayload,
    priority: data.get("priority"),
    description: data.get("description"),
    probability: data.get("probability") === "" ? null : Number(data.get("probability")),
    account_id: data.get("entity_type") === "account" ? "" : (customerMaster ? (customerMaster.source_record_id || "") : (selectedAccountValue.startsWith("cm:") ? "" : selectedAccountValue)),
    customer_master_id: data.get("entity_type") === "account" ? "" : (customerMaster?.id || ""),
    account_name: data.get("entity_type") === "account" ? "" : (customerMaster?.display_name || account?.title || ""),
    erp_partner_aliases: String(data.get("erp_partner_aliases") || "").split(",").map(value => value.trim()).filter(Boolean),
  };
  recordTextPayloadFields.forEach(name => { payload[name] = data.get(name) || ""; });
  recordNumericPayloadFields.forEach(name => { payload[name] = data.get(name) === "" || data.get(name) === null ? null : numeric(data.get(name)); });
  recordBooleanPayloadFields.forEach(name => { payload[name] = Boolean(form.elements[name]?.checked); });
  const entityType = data.get("entity_type");
  if (entityType === "order" && customerMaster) {
    payload.order_payment_terms = {
      payment_method: data.get("order_payment_method") || "",
      advance_ratio: numeric(data.get("order_advance_ratio")),
      collection_basis: data.get("order_collection_basis") || "shipment_date",
      deferred_days: numeric(data.get("order_deferred_days")),
      installments_json: [], currency: data.get("currency") || customerMaster.default_currency || "USD",
    };
    payload.order_product_terms = data.get("order_product_name") ? [{
      product_name: data.get("order_product_name"),
      agreed_unit_price: numeric(data.get("order_agreed_unit_price")),
      currency: data.get("currency") || customerMaster.default_currency || "USD",
      moq: numeric(data.get("order_moq")), moq_basis: data.get("order_moq_basis") || "paid",
      paid_quantity: numeric(data.get("order_paid_quantity")), foc_quantity: numeric(data.get("order_foc_quantity")),
    }] : [];
    payload.order_moq_exception_reason = data.get("order_moq_exception_reason") || "";
    payload.order_moq_exception_approver = data.get("order_moq_exception_approver") || "";
  }
  if (entityType === "task") {
    payload.task_kind = payload.parent_task_id ? "detail" : "group";
  }
  let dueDate = data.get("due_date");
  let status = data.get("status");
  const draft = { amount: numeric(data.get("amount")), currency: data.get("currency") || "USD", payload };
  if (entityType === "cash_plan") {
    dueDate = payload.execution_date || payload.plan_date || payload.maturity_date || "";
    if ((payload.execution_date && (numeric(payload.actual_krw_amount) || numeric(payload.actual_foreign_amount))) || payload.plan_actual_type === "actual") status = "executed";
  }
  if (entityType === "receivable") {
    const detail = receivableSchedule(draft);
    dueDate = payload.next_collection_date || payload.promise_date || detail.next?.dueDate || "";
    status = detail.balance <= 0.01 ? "paid" : truthy(payload.legal_review) || payload.risk_level === "legal" ? "legal" : truthy(payload.shipment_hold) ? "hold" : detail.maxOverdueDays > 0 ? "overdue" : payload.collection_status === "promise_received" ? "promise" : detail.next?.dueDate && detail.next.dueDate <= todayIso() ? "due" : detail.collected > 0 ? "partial_paid" : "current";
  }
  if (entityType === "promotion") {
    dueDate = payload.target_ship_date || payload.end_date || "";
    if (status === "completed" && !payload.completed_at) payload.completed_at = todayIso();
  }
  const body = {
    entity_type: entityType, title: data.get("title"), status,
    owner_id: data.get("owner_id"), due_date: dueDate, region: data.get("region"),
    country: data.get("country"), amount: data.get("amount"), currency: data.get("currency"), payload,
  };
  const button = form.querySelector('button[type="submit"]');
  const errorNode = $("#recordFormError");
  errorNode.textContent = "";
  button.disabled = true;
  button.textContent = "저장 중…";
  try {
    const result = await api(id ? `/api/records/${id}` : "/api/records", { method: id ? "PATCH" : "POST", body });
    const existingIndex = state.records.findIndex(row => row.id === result.record.id);
    if (existingIndex >= 0) state.records[existingIndex] = result.record;
    else state.records.unshift(result.record);
    if (entityType === "task" && payload.parent_task_id) state.expandedTaskGroups.add(payload.parent_task_id);
    $("#recordDialog").close();
    renderRecordModuleSummary();
    renderRecordTable();
    await refreshOverview();
    if (entityType === "promotion") await loadForecast();
    toast(result.message);
  } catch (error) {
    errorNode.textContent = error.message;
    errorNode.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } finally {
    button.disabled = false;
    button.textContent = "저장";
  }
}

function handleRecordAction(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const record = state.records.find(row => row.id === button.dataset.id);
  if (!record) return;
  if (button.dataset.action === "toggle-task-group") {
    if (state.expandedTaskGroups.has(record.id)) state.expandedTaskGroups.delete(record.id);
    else state.expandedTaskGroups.add(record.id);
    renderRecordTable();
    return;
  }
  if (button.dataset.action === "add-task-child") {
    state.currentEntity = "task";
    state.expandedTaskGroups.add(record.id);
    openRecordDialog(null, { parentTask: record });
    return;
  }
  if (button.dataset.action === "edit") openRecordDialog(record);
  if (button.dataset.action === "journey") openAccountJourney(record);
  if (button.dataset.action === "execute") confirmAction(
    "자금 실행 완료",
    `“${record.title}” 계획금액을 오늘 전액 실행한 것으로 처리하시겠습니까? 실행일과 실제금액이 기록되며 변경 이력도 남습니다.`,
    async () => {
      const payload = { ...record.payload, execution_date: todayIso(), plan_actual_type: "actual" };
      if (record.currency === "KRW") payload.actual_krw_amount = numeric(record.amount);
      else {
        payload.actual_foreign_amount = numeric(record.amount);
        payload.actual_krw_amount = recordKrwAmount(record, null, payload.exchange_rate);
      }
      const result = await api(`/api/records/${record.id}`, { method: "PATCH", body: {
        entity_type: record.entity_type, title: record.title, status: "executed", owner_id: record.owner_id,
        due_date: todayIso(), region: record.region, country: record.country, amount: record.amount,
        currency: record.currency, payload,
      } });
      state.records[state.records.findIndex(row => row.id === record.id)] = result.record;
      renderRecordModuleSummary(); renderRecordTable(); await refreshOverview();
      toast("자금 실행 완료로 반영했습니다.");
    },
  );
  if (button.dataset.action === "complete-promotion") confirmAction(
    "프로모션 종료",
    `“${record.payload?.promotion_id || record.title}” 프로모션을 오늘 기준으로 완료 처리하시겠습니까? 달성액과 타임라인은 그대로 보존됩니다.`,
    async () => {
      const payload = { ...record.payload, completed_at: todayIso() };
      const result = await api(`/api/records/${record.id}`, { method: "PATCH", body: {
        entity_type: record.entity_type, title: record.title, status: "completed", owner_id: record.owner_id,
        due_date: record.due_date, region: record.region, country: record.country, amount: record.amount,
        currency: record.currency, payload,
      } });
      state.records[state.records.findIndex(row => row.id === record.id)] = result.record;
      renderRecordModuleSummary(); renderRecordTable(); await refreshOverview(); await loadForecast();
      toast("프로모션을 완료 처리했습니다. 이력은 계속 보존됩니다.");
    },
  );
  if (button.dataset.action === "delete") confirmAction(
    "항목 삭제",
    (() => {
      const childCount = record.entity_type === "task" && !record.payload?.parent_task_id
        ? state.records.filter(row => row.entity_type === "task" && row.payload?.parent_task_id === record.id).length
        : 0;
      return childCount
        ? `“${record.title}” 대분류와 세부항목 ${childCount}건을 함께 삭제하시겠습니까? 화면에서는 사라지지만 변경 이력은 계속 보존됩니다.`
        : `“${record.title}” 항목을 삭제하시겠습니까? 화면에서는 사라지지만 삭제 전 데이터와 담당자 이력은 계속 보존됩니다.`;
    })(),
    async () => {
      const result = await api(`/api/records/${record.id}`, { method: "DELETE" });
      const deletedIds = new Set([record.id, ...(result.deleted_child_ids || [])]);
      state.records = state.records.filter(row => !deletedIds.has(row.id));
      state.expandedTaskGroups.delete(record.id);
      renderRecordModuleSummary();
      renderRecordTable();
      await refreshOverview();
      if (record.entity_type === "promotion") await loadForecast();
      toast(result.message);
    },
  );
}

function journeySection(title, rows, account) {
  if (!rows.length) return `<section class="journey-section"><h3>${escapeHtml(title)}</h3><p class="agenda-empty">등록된 내용이 없습니다.</p></section>`;
  return `<section class="journey-section"><h3>${escapeHtml(title)}</h3><div class="journey-list">${rows.map(row => {
    const date = recordActionDate(row);
    const activity = row.entity_type === "activity" ? activityLabels[row.payload?.activity_type] : "";
    const progress = row.entity_type === "order" ? orderProgressHtml(row) : "";
    return `<button type="button" class="journey-row" data-journey-record="${escapeHtml(row.id)}"><span class="journey-line-dot ${escapeHtml(row.entity_type)}"></span><span><strong>${escapeHtml(row.title)}</strong><small>${escapeHtml(activity || statusLabels[effectiveRecordStatus(row)] || effectiveRecordStatus(row))} · ${escapeHtml(row.owner_name || "담당자 미지정")}${date ? ` · ${escapeHtml(formatDate(date))}` : ""}</small>${progress}</span><span>${["pipeline", "cash_plan", "receivable", "promotion"].includes(row.entity_type) && Number(row.amount) ? compactMoney(row.amount, row.currency) : "→"}</span></button>`;
  }).join("")}</div></section>`;
}

function journeyAccountProfileSection(account, detail) {
  if (!account) return "";
  const payload = account.payload || {};
  const fields = [
    ["회사명", account.title], ["주소", payload.address],
    ["수기 기준매출액", Number(account.amount) ? formatMoney(account.amount, account.currency) : "—"],
    ["ERP 누적매출", formatMoney(detail.summary?.krw_supply || 0)], ["설립일", formatDate(payload.established_date)],
    ["최초거래일", formatDate(payload.first_transaction_date || detail.summary?.first_ship_date)], ["대표자명", payload.representative_name],
    ["담당자명", payload.account_contact_name || payload.contact_person], ["연락처", payload.contact_phone],
    ["이메일", payload.contact_email], ["기타", payload.account_notes || payload.description],
  ];
  const canEdit = Boolean(state.permissions.can_edit_all || (state.me?.role === "editor" && (account.owner_id === state.me.id || account.created_by === state.me.id)));
  return `<section class="journey-section span-all account-profile-section"><div class="journey-section-head"><div><h3>거래처 기본정보</h3><p>회사·담당자 정보와 ERP 매출 연결 기준입니다.</p></div>${canEdit ? '<button type="button" class="mini-btn emphasis" data-journey-account-edit>기본정보 수정</button>' : ""}</div><div class="account-profile-grid">${fields.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "—")}</strong></div>`).join("")}</div></section>`;
}

function journeyYearlySection(detail) {
  const rows = detail.annual_five_years || [];
  const max = Math.max(...rows.map(row => Number(row.krw_supply || 0)), 1);
  const period = rows.length ? `${rows[0].year}~${rows[rows.length - 1].year}` : "최근 5년";
  return `<section class="journey-section span-all"><div class="journey-section-head"><div><h3>최근 5년 연간매출</h3><p>${escapeHtml(period)} ERP 해외 출고 공급가 기준입니다.</p></div><strong>연평균 ${formatMoney(detail.summary?.average_annual_sales_5y || 0)}</strong></div><div class="journey-year-chart">${rows.map(row => `<div><strong>${compactMoney(row.krw_supply, "KRW")}</strong><span><i style="height:${Math.max(2, Number(row.krw_supply || 0) / max * 100)}%"></i></span><b>${escapeHtml(row.year)}</b></div>`).join("")}</div></section>`;
}

function journeyMonthlySection(detail) {
  const rows = detail.monthly || [];
  const currentYear = new Date().getFullYear();
  const years = [String(currentYear), String(currentYear - 1), String(currentYear - 2)];
  const rowMap = new Map(rows.map(row => [row.month, row]));
  return `<section class="journey-section span-all"><div class="journey-section-head"><div><h3>최근 3년 월별 매출</h3><p>${escapeHtml(years[years.length - 1])}~${escapeHtml(years[0])} 월별 ERP 출고 매출과 출고 건수입니다.</p></div></div><div class="journey-month-groups">${years.map((year, index) => {
    const yearRows = Array.from({ length: 12 }, (_, monthIndex) => rowMap.get(`${year}-${String(monthIndex + 1).padStart(2, "0")}`) || { month: `${year}-${String(monthIndex + 1).padStart(2, "0")}`, krw_supply: 0, shipment_count: 0, line_count: 0, quantity: 0 });
    return `<details ${index === 0 ? "open" : ""}><summary><strong>${escapeHtml(year)}년</strong><span>${formatMoney(yearRows.reduce((sum, row) => sum + Number(row.krw_supply || 0), 0))}</span></summary><div class="journey-table-wrap"><table class="journey-table"><thead><tr><th>월</th><th>ERP 매출</th><th>출고</th><th>품목라인</th><th>수량</th></tr></thead><tbody>${yearRows.map(row => `<tr><td>${Number(row.month.slice(5))}월</td><td>${formatMoney(row.krw_supply)}</td><td>${formatNumber(row.shipment_count)}건</td><td>${formatNumber(row.line_count)}</td><td>${formatNumber(row.quantity, 2)}</td></tr>`).join("")}</tbody></table></div></details>`;
  }).join("")}</div></section>`;
}

function journeyItemSection(detail) {
  const rows = detail.items_by_year || [];
  if (!rows.length) return '<section class="journey-section span-all"><h3>최근 3년 품목별 매출</h3><p class="agenda-empty">품목 이력이 없습니다.</p></section>';
  const years = [...new Set(rows.map(row => String(row.year)))].sort().reverse();
  return `<section class="journey-section span-all"><div class="journey-section-head"><div><h3>최근 3년 품목별 매출</h3><p>연도별 사업분야·품목·규격 출고 실적입니다.</p></div><span>${formatNumber(rows.length)}개 항목</span></div><div class="journey-month-groups">${years.map((year, index) => {
    const yearRows = rows.filter(row => String(row.year) === year);
    return `<details ${index === 0 ? "open" : ""}><summary><strong>${escapeHtml(year)}년</strong><span>${formatMoney(yearRows.reduce((sum, row) => sum + Number(row.krw_supply || 0), 0))}</span></summary><div class="journey-table-wrap"><table class="journey-table"><thead><tr><th>사업분야</th><th>품번·품명</th><th>규격</th><th>수량</th><th>출고</th><th>매출</th></tr></thead><tbody>${yearRows.map(row => `<tr><td>${escapeHtml(segmentLabels[row.business_unit] || "미분류")}</td><td><strong>${escapeHtml(row.product_code)}</strong><small>${escapeHtml(row.product_name)}</small></td><td>${escapeHtml(row.specification || "—")}</td><td>${formatNumber(row.quantity, 2)}</td><td>${formatNumber(row.shipment_count)}건</td><td>${formatMoney(row.krw_supply)}</td></tr>`).join("")}</tbody></table></div></details>`;
  }).join("")}</div></section>`;
}

function journeyShipmentSection(detail) {
  const rows = detail.shipments || [];
  if (!rows.length) return '<section class="journey-section span-all"><h3>ERP 출고 이력</h3><p class="agenda-empty">출고 이력이 없습니다.</p></section>';
  return `<section class="journey-section span-all"><div class="journey-section-head"><div><h3>ERP 출고 이력</h3><p>출고번호를 펼치면 공급가·ERP 합계액 원문·공식 인식매출과 자료 근거가 나옵니다.</p></div><span>최근 ${formatNumber(rows.length)}건</span></div><div class="shipment-history-list">${rows.map(row => `<details class="shipment-history-row"><summary><span><strong>${escapeHtml(row.issue_no)}</strong><small>${formatDate(row.ship_date)} · ${escapeHtml(row.trade_type)} · ${escapeHtml((row.business_units || []).map(unit => segmentLabels[unit] || "미분류").join(" / "))}</small></span><span><strong>${formatMoney(row.krw_supply)}</strong><small>${formatNumber(row.line_count)}라인 · ${escapeHtml((row.source_labels || []).join(" / "))}</small></span></summary><div class="journey-table-wrap"><table class="journey-table shipment-line-table"><thead><tr><th>순번</th><th>사업분야</th><th>품번·품명</th><th>규격·LOT</th><th>수량</th><th>외화·환율</th><th>원화 공급가</th><th>ERP 합계액</th><th>공식 인식매출</th><th>자료근거</th></tr></thead><tbody>${(row.lines || []).map(line => `<tr><td>${formatNumber(line.issue_seq)}</td><td>${escapeHtml(segmentLabels[line.business_unit] || "미분류")}</td><td><strong>${escapeHtml(line.product_code || "—")}</strong><small>${escapeHtml(line.product_name || "품목명 미지정")}</small></td><td>${escapeHtml(line.specification || "—")}${line.lot_no ? `<small>LOT ${escapeHtml(line.lot_no)}</small>` : ""}</td><td>${formatNumber(line.quantity, 2)}</td><td>${formatMoney(line.foreign_amount, line.currency)}<small>환율 ${formatNumber(line.exchange_rate, 4)}</small></td><td>${formatMoney(line.krw_supply)}</td><td>${formatMoney(line.erp_raw_total_krw)}</td><td>${line.recognized_sales_krw === null || line.recognized_sales_krw === undefined ? "검토대기" : formatMoney(line.recognized_sales_krw)}<small>${escapeHtml(line.actual_review_status || "unclassified")}</small></td><td><strong>${escapeHtml(line.source?.label || "ERP")}</strong><small>${escapeHtml(line.source?.amount_basis || "")}${line.source?.source_row ? ` · 원본 ${formatNumber(line.source.source_row)}행` : ""}</small></td></tr>`).join("")}</tbody></table></div></details>`).join("")}</div></section>`;
}

function journeyReceivableSection(account, detail, rows) {
  const payload = account?.payload || {};
  const summary = receivableSummary(rows);
  const paymentTerms = payload.ar_condition_label || [
    numeric(payload.ar_advance_ratio) ? `선금 ${formatNumber(payload.ar_advance_ratio)}%` : "",
    ...[1, 2, 3, 4].map(index => numeric(payload[`ar_installment_${index}_ratio`]) ? `${index}차 ${formatNumber(payload[`ar_installment_${index}_ratio`])}%/${formatNumber(payload[`ar_installment_${index}_days`])}일` : ""),
  ].filter(Boolean).join(" · ") || "결제조건 미등록";
  const shipmentTotal = Number(detail.summary?.krw_supply || 0);
  const coverage = shipmentTotal ? summary.total / shipmentTotal * 100 : 0;
  const table = rows.length ? `<div class="journey-table-wrap"><table class="journey-table"><thead><tr><th>출고·인보이스</th><th>출고일</th><th>채권총액</th><th>입금누계</th><th>미수잔액</th><th>다음 입금</th><th>관리</th></tr></thead><tbody>${rows.map(row => {
    const item = receivableSchedule(row);
    return `<tr><td><strong>${escapeHtml(row.payload?.shipment_no || row.payload?.invoice_no || row.title)}</strong><small>${escapeHtml(row.payload?.invoice_no || "")}</small></td><td>${formatDate(row.payload?.ship_date || row.payload?.invoice_date)}</td><td>${formatMoney(row.amount, row.currency)}</td><td>${formatMoney(item.collected, row.currency)}</td><td><strong>${formatMoney(item.balance, row.currency)}</strong><small>${item.maxOverdueDays ? `${formatNumber(item.maxOverdueDays)}일 연체` : item.agingLabel}</small></td><td>${item.next ? `${formatDate(item.next.dueDate)}<small>${formatMoney(item.next.remaining, row.currency)}</small>` : "—"}</td><td><button type="button" class="mini-btn" data-journey-record="${escapeHtml(row.id)}">채권 열기</button></td></tr>`;
  }).join("")}</tbody></table></div>` : '<p class="agenda-empty">출고 대비 입금 내역이 아직 등록되지 않았습니다. 미수금·채권 메뉴에서 인보이스별 입금내역을 등록하세요.</p>';
  return `<section class="journey-section span-all account-receivable-section"><div class="journey-section-head"><div><h3>미수금 / 결제조건</h3><p>카드를 눌러 출고 대비 입금·잔액 내역을 펼쳐봅니다.</p></div><span>${escapeHtml(paymentTerms)}</span></div><div class="account-receivable-kpis"><div><span>ERP 출고 누계</span><strong>${formatMoney(shipmentTotal)}</strong></div><div><span>등록 채권총액</span><strong>${formatMoney(summary.total)}</strong><small>출고대비 등록 ${formatNumber(coverage, 1)}%</small></div><div><span>입금 누계</span><strong>${formatMoney(summary.collected)}</strong></div><div><span>미수금 잔액</span><strong>${formatMoney(summary.balance)}</strong><small>연체 ${formatMoney(summary.overdue)}</small></div></div><details class="account-receivable-details"><summary><strong>출고 대비 입금 세부내용</strong><span>${formatNumber(rows.length)}건 · 클릭하여 펼치기</span></summary>${table}</details>${payload.ar_terms_notes ? `<p class="module-policy-note"><strong>결제조건 비고</strong><span>${escapeHtml(payload.ar_terms_notes)}</span></p>` : ""}</section>`;
}

function journeyHistorySection(detail) {
  const rows = detail.history || [];
  if (!rows.length) return '<section class="journey-section span-all"><h3>담당자 변경 이력</h3><p class="agenda-empty">기록된 변경 이력이 없습니다.</p></section>';
  return `<section class="journey-section span-all"><div class="journey-section-head"><div><h3>담당자 변경 이력</h3><p>거래처와 연결된 영업·수주·채권 자료의 등록·수정·삭제 기록입니다.</p></div><span>${formatNumber(rows.length)}건</span></div><div class="journey-audit-list">${rows.map(row => `<div><span class="badge">${escapeHtml(row.action)}</span><p><strong>${escapeHtml(row.summary)}</strong><small>${escapeHtml(row.actor_username || "담당자")} · ${formatDate(row.occurred_at, true)}</small></p></div>`).join("")}</div></section>`;
}

function renderAccountJourney(account, detail) {
  state.journeyAccountId = account?.id || null;
  const linked = account ? linkedAccountRecords(account.id).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at))) : [];
  const pipelines = linked.filter(row => row.entity_type === "pipeline");
  const activities = linked.filter(row => row.entity_type === "activity");
  const orders = linked.filter(row => row.entity_type === "order");
  const tasks = linked.filter(row => ["task", "agenda"].includes(row.entity_type));
  const receivables = linked.filter(row => row.entity_type === "receivable");
  const promotions = linked.filter(row => row.entity_type === "promotion");
  const cashPlans = linked.filter(row => row.entity_type === "cash_plan");
  const title = account?.title || detail.requested_partner || detail.matched_partner_names?.[0] || "ERP 거래처";
  const matchedNames = detail.matched_partner_names || [];
  $("#accountJourneyTitle").textContent = title;
  $("#accountJourneyMeta").textContent = account
    ? `${[account.region, account.country].filter(Boolean).join(" · ") || "권역 미지정"} · 담당 ${account.owner_name || "미지정"}${matchedNames.length ? ` · ERP ${matchedNames.join(", ")}` : " · ERP 연결명 확인 필요"}`
    : `ERP 출고 거래처 · ${matchedNames.join(", ")} · 거래처 마스터 연결 전`;
  const yearly = new Map((detail.yearly || []).map(row => [String(row.year), row]));
  $("#accountJourneySummary").innerHTML = [
    ["누적 ERP 매출", formatMoney(detail.summary?.krw_supply)],
    ["2024 실제 매출", formatMoney(yearly.get("2024")?.krw_supply)],
    ["2025 실제 매출", formatMoney(yearly.get("2025")?.krw_supply)],
    ["2026 ERP 매출", formatMoney(yearly.get("2026")?.krw_supply)],
    ["누적 출고", `${formatNumber(detail.summary?.shipment_count)}건`],
    ["최근 출고", formatDate(detail.summary?.last_ship_date)],
  ].map(item => `<div><span>${item[0]}</span><strong>${item[1]}</strong></div>`).join("");
  const linkNotice = detail.link_status === "unmatched_erp_partner"
    ? '<div class="journey-link-notice warning"><strong>거래처 마스터 연결 필요</strong><span>ERP 매출·출고는 조회할 수 있습니다. 거래처 마스터의 ERP 연결명에 이 업체명을 넣으면 영업활동·수주·미수금·프로모션 이력과 자동으로 합쳐집니다.</span></div>'
    : detail.link_status === "account_without_erp_match"
      ? '<div class="journey-link-notice warning"><strong>ERP 출고명 확인 필요</strong><span>거래처는 등록되어 있으나 일치하는 ERP 거래처명이 없습니다. 거래처 수정에서 ERP 연결명을 확인해 주세요.</span></div>'
      : `<div class="journey-link-notice"><strong>ERP·영업 이력 연결됨</strong><span>${formatNumber(detail.linked_record_count)}개 관련 업무와 ${formatNumber(detail.history?.length)}개 변경 기록을 함께 조회합니다.</span></div>`;
  $("#accountJourneyContent").innerHTML = [
    `<section class="journey-source-strip span-all">${linkNotice}<div>${(detail.source_notes || []).map(note => `<span>${escapeHtml(note)}</span>`).join("")}</div></section>`,
    journeyAccountProfileSection(account, detail), journeyYearlySection(detail), journeyMonthlySection(detail), journeyItemSection(detail), journeyShipmentSection(detail),
    journeySection("기회·파이프라인", pipelines, account), journeySection("연락·미팅 이력", activities, account),
    journeySection("PO부터 출고까지", orders, account), journeyReceivableSection(account, detail, receivables),
    journeySection("프로모션 이력", promotions, account), journeySection("수금·지출 계획", cashPlans, account),
    journeySection("관련 미결업무", tasks, account), journeyHistorySection(detail),
  ].join("");
  $("#accountJourneyActions").classList.toggle("hidden", !account || !state.permissions.can_edit);
}

function openJourneyLoading(title, meta) {
  $("#accountJourneyTitle").textContent = title;
  $("#accountJourneyMeta").textContent = meta;
  $("#accountJourneySummary").innerHTML = '<div><span>매출·출고 이력</span><strong>불러오는 중…</strong></div>';
  $("#accountJourneyContent").innerHTML = '<div class="journey-loading span-all"><span></span><strong>ERP 매출과 담당자 이력을 연결하고 있습니다.</strong></div>';
  $("#accountJourneyActions").classList.add("hidden");
  if (!$("#accountJourneyDialog").open) $("#accountJourneyDialog").showModal();
}

async function openAccountJourney(account) {
  if (!account) return;
  state.journeyAccountId = account.id;
  openJourneyLoading(account.title, `${[account.region, account.country].filter(Boolean).join(" · ") || "권역 미지정"} · ERP 출고이력 조회 중`);
  try {
    const detail = await api(`/api/accounts/${encodeURIComponent(account.id)}/detail`);
    renderAccountJourney(account, detail);
  } catch (error) {
    $("#accountJourneyContent").innerHTML = `<div class="journey-error span-all"><strong>거래처 이력을 불러오지 못했습니다.</strong><span>${escapeHtml(error.message)}</span></div>`;
    toast(error.message, "error");
  }
}

async function openPartnerJourney(partnerName) {
  if (!partnerName) return;
  state.journeyAccountId = null;
  openJourneyLoading(partnerName, "ERP 거래처의 연도·월·출고·품목 이력 조회 중");
  try {
    const detail = await api(`/api/partners/detail?name=${encodeURIComponent(partnerName)}`);
    const account = detail.account ? (state.records.find(row => row.id === detail.account.id) || detail.account) : null;
    renderAccountJourney(account, detail);
  } catch (error) {
    $("#accountJourneyContent").innerHTML = `<div class="journey-error span-all"><strong>ERP 거래처 이력을 불러오지 못했습니다.</strong><span>${escapeHtml(error.message)}</span></div>`;
    toast(error.message, "error");
  }
}

function handleJourneyAction(event) {
  const editAccount = event.target.closest("[data-journey-account-edit]");
  if (editAccount) {
    const account = state.records.find(row => row.id === state.journeyAccountId && row.entity_type === "account");
    if (!account) return;
    $("#accountJourneyDialog").close();
    switchView("account");
    openRecordDialog(account);
    return;
  }
  const button = event.target.closest("[data-journey-record]");
  if (!button) return;
  const record = state.records.find(row => row.id === button.dataset.journeyRecord);
  $("#accountJourneyDialog").close();
  focusRecord(record);
}

function openJourneyAdd(entityType) {
  const account = state.records.find(row => row.id === state.journeyAccountId);
  if (!account) return;
  $("#accountJourneyDialog").close();
  switchView(entityType);
  openRecordDialog();
  setFormValue($("#recordForm"), "account_id", account.id);
  setFormValue($("#recordForm"), "title", entityType === "activity" ? `${account.title} 영업 연락` : `${account.title} 신규 수주`);
}

function confirmAction(title, message, action) {
  $("#confirmTitle").textContent = title;
  $("#confirmMessage").textContent = message;
  const button = $("#confirmActionBtn");
  button.onclick = async () => {
    button.disabled = true;
    try { await action(); $("#confirmDialog").close(); }
    catch (error) { toast(error.message, "error"); }
    finally { button.disabled = false; }
  };
  $("#confirmDialog").showModal();
}

async function refreshOverview() {
  const [dashboard, records, accountSummaries, mapData] = await Promise.all([api("/api/dashboard"), api("/api/records"), api("/api/accounts/summary"), api(mapApiPath())]);
  state.dashboard = dashboard;
  state.records = records.records;
  state.accountSummaries = accountSummaries.accounts || [];
  state.mapData = mapData;
  renderOverview();
  renderGlobalMap();
  renderDaily();
  if (state.currentEntity === "account") renderRecordView();
}

function renderUsers() {
  const isAdmin = state.me?.role === "admin";
  $("#usersTableBody").innerHTML = state.users.map(user => {
    const controls = isAdmin && user.id !== state.me.id ? `<div class="table-actions"><button class="mini-btn" data-user-action="reset-password" data-user-id="${user.id}">비번 초기화</button><button class="mini-btn" data-user-action="save" data-user-id="${user.id}">저장</button><button class="mini-btn danger" data-user-action="delete" data-user-id="${user.id}">삭제</button></div>` : '<span class="muted">—</span>';
    const role = isAdmin && user.id !== state.me.id ? `<select class="user-role" data-user-id="${user.id}">${["viewer", "editor", "manager", "admin"].map(value => `<option value="${value}" ${user.role === value ? "selected" : ""}>${statusLabels[value]}</option>`).join("")}</select>` : badge(user.role);
    const status = isAdmin && user.id !== state.me.id ? `<select class="user-status" data-user-id="${user.id}">${["pending", "active", "disabled"].map(value => `<option value="${value}" ${user.status === value ? "selected" : ""}>${statusLabels[value]}</option>`).join("")}</select>` : badge(user.status);
    const passwordState = user.must_change_password ? '<span class="badge warning">변경 필요</span>' : '<span class="badge success">설정 완료</span>';
    return `<tr><td class="table-title">${escapeHtml(user.display_name)}${user.id === state.me.id ? '<span class="table-sub">현재 로그인</span>' : ""}</td><td>${escapeHtml(user.username)}</td><td>${escapeHtml(user.email || "—")}</td><td>${role}</td><td>${status}</td><td>${passwordState}</td><td>${formatDate(user.last_login_at, true)}</td><td>${controls}</td></tr>`;
  }).join("");
}

function sortUsers() {
  state.users.sort((a, b) => {
    if (a.status === "pending" && b.status !== "pending") return -1;
    if (a.status !== "pending" && b.status === "pending") return 1;
    return a.display_name.localeCompare(b.display_name, "ko");
  });
}

function openAdminUserDialog() {
  const form = $("#adminUserForm");
  form.reset();
  form.elements.role.value = "editor";
  form.elements.status.value = "active";
  $("#adminUserError").textContent = "";
  setActionMessage("#userActionMessage");
  $("#userCreateDialog").showModal();
  window.setTimeout(() => form.elements.username.focus(), 0);
}

async function handleAdminUserCreate(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const errorNode = $("#adminUserError");
  const button = $("#adminUserSubmitBtn");
  errorNode.textContent = "";
  if (form.get("password") !== form.get("password_confirm")) {
    errorNode.textContent = "임시 비밀번호 확인이 일치하지 않습니다.";
    return;
  }
  button.disabled = true;
  button.textContent = "등록 중…";
  try {
    const result = await api("/api/users", { method: "POST", body: Object.fromEntries(form.entries()) });
    state.users.push(result.user);
    sortUsers();
    renderUsers();
    formElement.reset();
    $("#userCreateDialog").close();
    setActionMessage("#userActionMessage", result.message);
    toast(result.message);
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "사용자 등록";
  }
}

function openResetPasswordDialog(user) {
  const form = $("#resetPasswordForm");
  form.reset();
  form.elements.user_id.value = user.id;
  $("#resetPasswordTarget").textContent = `${user.display_name} (${user.username}) 계정에 새 임시 비밀번호를 발급합니다.`;
  $("#resetPasswordError").textContent = "";
  $("#resetPasswordDialog").showModal();
  window.setTimeout(() => form.elements.password.focus(), 0);
}

async function handleResetPassword(event) {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const errorNode = $("#resetPasswordError");
  const button = $("#resetPasswordSubmitBtn");
  errorNode.textContent = "";
  if (form.get("password") !== form.get("password_confirm")) {
    errorNode.textContent = "임시 비밀번호 확인이 일치하지 않습니다.";
    return;
  }
  button.disabled = true;
  button.textContent = "발급 중…";
  try {
    const id = Number(form.get("user_id"));
    const result = await api(`/api/users/${id}/reset-password`, { method: "POST", body: { password: form.get("password"), password_confirm: form.get("password_confirm") } });
    const index = state.users.findIndex(user => user.id === id);
    if (index >= 0) state.users[index] = result.user;
    renderUsers();
    formElement.reset();
    $("#resetPasswordDialog").close();
    toast(result.message);
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "임시 비밀번호 발급";
  }
}

async function handleUserAction(event) {
  const button = event.target.closest("button[data-user-action]");
  if (!button) return;
  const id = Number(button.dataset.userId);
  const user = state.users.find(row => row.id === id);
  if (!user) return;
  if (button.dataset.userAction === "reset-password") {
    openResetPasswordDialog(user);
    return;
  }
  if (button.dataset.userAction === "save") {
    const role = $(`.user-role[data-user-id="${id}"]`).value;
    const status = $(`.user-status[data-user-id="${id}"]`).value;
    button.disabled = true;
    button.textContent = "저장 중…";
    setActionMessage("#userActionMessage");
    try {
      const result = await api(`/api/users/${id}`, { method: "PATCH", body: { role, status } });
      state.users[state.users.findIndex(row => row.id === id)] = result.user;
      renderUsers();
      setActionMessage("#userActionMessage", `${user.display_name}: ${result.message}`);
      toast(result.message);
    } catch (error) {
      setActionMessage("#userActionMessage", error.message, "error");
      toast(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "저장";
    }
  }
  if (button.dataset.userAction === "delete") {
    confirmAction("사용자 삭제", `${user.display_name} (${user.username}) 계정을 비활성 삭제하시겠습니까? 사용자와 업무 이력은 계속 보존됩니다.`, async () => {
      const result = await api(`/api/users/${id}`, { method: "DELETE" });
      state.users = state.users.filter(row => row.id !== id);
      renderUsers();
      toast(result.message);
    });
  }
}

async function loadHistory() {
  try {
    const action = $("#historyAction").value;
    const data = await api(`/api/history?limit=200${action ? `&action=${encodeURIComponent(action)}` : ""}`);
    const container = $("#historyTimeline");
    container.innerHTML = data.history.length ? data.history.map(item => `<article class="history-item"><div class="history-time">${formatDate(item.occurred_at, true)}</div><div class="history-main"><strong>${escapeHtml(item.summary)}</strong><span>${escapeHtml(item.actor_username)} · ${escapeHtml(item.entity_type)} ${item.entity_id ? `#${escapeHtml(item.entity_id).slice(0, 12)}` : ""}</span></div><div class="history-meta">${badge(item.action)}<small>${escapeHtml(item.ip_address || "")}</small></div></article>`).join("") : '<div class="empty-state">변경 이력이 없습니다.</div>';
  } catch (error) { toast(error.message, "error"); }
}

function openErpDialog() {
  const form = $("#erpForm");
  $("#erpFormError").textContent = "";
  const selectedYear = Number($("#salesYear").value);
  const now = new Date();
  const month = selectedYear === now.getFullYear() ? now.getMonth() : 0;
  const first = new Date(selectedYear, month, 1);
  const last = selectedYear === now.getFullYear() && month === now.getMonth() ? now : new Date(selectedYear, month + 1, 0);
  form.elements.date_from.value = localDate(first);
  form.elements.date_to.value = localDate(last);
  form.dataset.previewReady = "";
  form.dataset.requiresForce = "";
  $("#erpPreflightResult").classList.add("hidden");
  $("#erpPreflightResult").innerHTML = "";
  $("#erpSubmitBtn").textContent = "ERP 응답 검증";
  $("#erpDialog").showModal();
}

function localDate(date) {
  const y = date.getFullYear();
  return `${y}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

async function handleErpSync(event) {
  event.preventDefault();
  const button = $("#erpSubmitBtn");
  const form = new FormData(event.currentTarget);
  const errorNode = $("#erpFormError");
  errorNode.textContent = "";
  button.disabled = true;
  const applying = event.currentTarget.dataset.previewReady === "yes";
  button.textContent = applying ? "검증 결과 반영 중…" : "ERP 조회·검증 중…";
  toast("Amaranth 출고 헤더와 상세 데이터를 가져오고 있습니다.");
  try {
    let force = false;
    let forceReason = "";
    if (applying && event.currentTarget.dataset.requiresForce === "yes") {
      if (state.me?.role !== "admin") throw new Error("비정상 급감 강제반영은 관리자만 할 수 있습니다.");
      forceReason = window.prompt("비정상 급감에도 반영해야 하는 업무상 사유를 입력하세요.", "")?.trim() || "";
      if (!forceReason) throw new Error("강제반영 사유가 없어 반영을 취소했습니다.");
      force = true;
    }
    const result = await api("/api/erp/sync", { method: "POST", body: {
      date_from: form.get("date_from"), date_to: form.get("date_to"),
      confirm_apply: applying, force, force_reason: forceReason,
    } });
    if (result.preview) {
      const metrics = result.metrics || {};
      const warnings = [...(metrics.hard_blocks || []), ...(metrics.force_blocks || []), ...(metrics.warnings || [])];
      const currencies = Object.entries(metrics.currency_transaction_totals || {}).map(([key, value]) => `${key} ${formatNumber(value, 4)}`).join(" · ") || "없음";
      const node = $("#erpPreflightResult");
      node.classList.remove("hidden");
      node.innerHTML = `<strong>반영 전 비교</strong><dl><div><dt>Header</dt><dd>전체 ${formatNumber(metrics.source_header_count)} / 해외 ${formatNumber(metrics.overseas_header_count)} / 제외 ${formatNumber(metrics.excluded_header_count)}</dd></div><div><dt>Detail</dt><dd>기존 ${formatNumber(metrics.existing_line_count)} → 신규 ${formatNumber(metrics.detail_count)}</dd></div><div><dt>저장 공급가</dt><dd>${formatMoney(metrics.existing_krw_supply)} → ${formatMoney(metrics.new_krw_supply)}</dd></div><div><dt>거래통화</dt><dd>${escapeHtml(currencies)}</dd></div></dl>${warnings.length ? `<ul>${warnings.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}`;
      if ((metrics.hard_blocks || []).length) {
        event.currentTarget.dataset.previewReady = "";
        button.textContent = "ERP 응답 다시 검증";
        throw new Error("필수 검증 실패로 반영할 수 없습니다. 기존 데이터는 유지됩니다.");
      }
      event.currentTarget.dataset.previewReady = "yes";
      event.currentTarget.dataset.requiresForce = result.requires_force ? "yes" : "";
      button.textContent = result.requires_force ? "관리자 강제사유 입력 후 반영" : "검증 결과 확인 후 반영";
      toast("ERP 비교검증이 끝났습니다. 결과를 확인한 뒤 반영 버튼을 눌러 주세요.");
      return;
    }
    $("#erpDialog").close();
    state.erpStatus = await api("/api/erp/status");
    state.sales = await api(salesApiPath());
    state.dashboard = await api("/api/dashboard");
    state.forecast = await api(forecastApiPath());
    state.mapData = await api(mapApiPath());
    renderErpStatus(); renderSales(); renderForecast(); renderOverview(); renderGlobalMap(); await loadHistory();
    const metrics = result.metrics || {};
    toast(`${result.message} 전체 ${formatNumber(metrics.source_header_count)}건 중 국내·LOCAL ${formatNumber(metrics.excluded_header_count)}건 제외, 해외 ${formatNumber(metrics.overseas_header_count)}건`);
  } catch (error) {
    const message = `${error.message}${error.detail ? ` · ${error.detail}` : ""}`;
    errorNode.textContent = message;
    toast(message, "error");
  }
  finally {
    button.disabled = false;
    if (event.currentTarget.dataset.previewReady !== "yes") button.textContent = "ERP 응답 검증";
  }
}

window.addEventListener("beforeunload", event => {
  if (!state.forecastRoundDirty) return;
  event.preventDefault();
  event.returnValue = "";
});

initialize();
