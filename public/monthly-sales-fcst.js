const monthlyFcstStatusLabels = { confirmed: "확정", scheduled: "예정", pipeline: "추진", undecided: "미정", carried_over: "차월 처리", cancelled: "취소 처리" };
const monthlyFcstBusinessLabels = { aesthetic: "에스테틱", medical: "메디컬", dental: "덴탈", total: "합계" };
const monthlyFcstTimingLabels = { current_new: "당월 추진", previous_carryover: "이월" };
const monthlyFcstCustomerHistoryLabels = { new: "신규 거래처", existing: "기존 거래처" };
const monthlyFcstRateLabels = { plan: "기준환율", shipment: "출고일 환율", pending: "환율 확인대기" };
const monthlyFcstCurrencies = ["USD", "EUR", "JPY", "CNH", "KRW"];
const monthlyFcstOwners = ["박정현", "김경태", "장윤선", "최령", "이인경", "김예원"];
const monthlyFcstStatuses = ["confirmed", "scheduled", "pipeline", "undecided", "carried_over", "cancelled"];
const monthlyFcstLiveMetrics = [
  { label: "총매출", note: "확정+예정+추진", key: "current_fcst", className: "forecast" },
  { label: "확정+예정", note: "고신뢰 매출", key: "high_confidence", className: "confidence" },
  { label: "확정", note: "영업 확정", key: "confirmed", className: "confirmed", status: "confirmed" },
  { label: "예정", note: "오더 합의·PO", key: "scheduled", className: "scheduled", status: "scheduled" },
  { label: "추진", note: "영업 추진 중", key: "pipeline", className: "pipeline", status: "pipeline" },
  { label: "미정", note: "추가 확인 필요", key: "undecided", className: "undecided", status: "undecided" },
  { label: "다음달 차월", note: "차월 예정·처리", key: "next_month", className: "carryover", carryover: "yes" },
];
const monthlyFcstLiveScopes = [
  { key: "total", label: "당월 전체 매출", note: "선택월 전체" },
  { key: "current_new", label: "당월 추진 시작", note: "이번 달 신규 추진", timing: "current_new" },
  { key: "previous_carryover", label: "이월 매출", note: "이전 달에서 넘어온 건", timing: "previous_carryover" },
];
const monthlyFcstSectionFilterFields = ["business_unit", "customer_name", "country", "timing_type", "customer_history", "owner_name", "carryover_decision"];
const monthlyFcstSectionFilterLabels = {
  business_unit: "사업분야", customer_name: "거래처", country: "국가",
  timing_type: "진행 시점", customer_history: "신규/기존", owner_name: "담당자", carryover_decision: "차월 구분",
};
const monthlyFcstSectionFixedOptions = {
  business_unit: ["aesthetic", "medical", "dental"],
  timing_type: ["current_new", "previous_carryover"],
  customer_history: ["new", "existing"],
  carryover_decision: ["no", "yes"],
};
const monthlyFcstSectionFilterSources = { customer_name: "customers", country: "countries", owner_name: "owners" };
const monthlyFcstSectionSearchFields = new Set(["customer_name", "country", "owner_name"]);
const monthlyFcstSectionFilters = Object.fromEntries(monthlyFcstStatuses.map(status => [
  status, Object.fromEntries(monthlyFcstSectionFilterFields.map(field => [field, new Set()])),
]));
let monthlyFcstSectionFilterMonth = "";
let monthlyFcstSectionFilterDraft = null;
let monthlyFcstSectionFilterDraftStatus = "";
let monthlyFcstGlobalFilterSnapshot = null;
let monthlyFcstGlobalFilterCommitted = false;
let monthlyFcstCustomerLinkGroups = [];

function monthlyFcstOperationKey() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function monthlyFcstShiftMonth(value, offset) {
  const [year, month] = value.split("-").map(Number);
  const date = new Date(year, month - 1 + offset, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function monthlyFcstCurrentMonth() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function monthlyFcstCurrentDate() {
  return localDate(new Date());
}

function monthlyFcstSelectedDate() {
  return $("#monthlyFcstDate").value || monthlyFcstCurrentDate();
}

function monthlyFcstSelectedMonth() {
  const selectedMonth = $("#monthlyFcstTargetMonth")?.value || "";
  return /^\d{4}-\d{2}$/.test(selectedMonth) ? selectedMonth : monthlyFcstCurrentMonth();
}

function monthlyFcstUsesAsOf() {
  return monthlyFcstSelectedDate() < monthlyFcstCurrentDate() || Boolean(state.monthlySalesFcstAsOfRound);
}

function syncMonthlyFcstQuickTabs() {
  const today = monthlyFcstCurrentDate();
  const current = monthlyFcstCurrentMonth();
  const selectedMonth = monthlyFcstSelectedMonth();
  const selectedDate = monthlyFcstSelectedDate();
  const active = selectedDate === today && selectedMonth === current
    ? "current"
    : selectedDate === today && selectedMonth === monthlyFcstShiftMonth(current, 1) ? "next" : "";
  state.monthlySalesFcstTab = active || "custom";
  $$('[data-monthly-fcst-tab]').forEach(button => button.classList.toggle("active", button.dataset.monthlyFcstTab === active));
}

function monthlyFcstApiPath() {
  const params = new URLSearchParams({ month: monthlyFcstSelectedMonth() });
  const mappings = {
    monthlyFcstCompareDate: "compare_date", monthlyFcstBusiness: "business_unit",
    monthlyFcstOwner: "owner", monthlyFcstStatus: "status", monthlyFcstSearch: "search",
    monthlyFcstCountry: "country", monthlyFcstCustomer: "customer", monthlyFcstTiming: "timing_type",
    monthlyFcstCustomerHistory: "customer_history",
    monthlyFcstOriginalMonth: "original_month", monthlyFcstSplit: "split",
    monthlyFcstCarryover: "carryover", monthlyFcstRisk: "risk",
  };
  Object.entries(mappings).forEach(([id, key]) => {
    const value = $("#" + id)?.value?.trim();
    if (value) params.set(key, value);
  });
  if (monthlyFcstUsesAsOf()) params.set("as_of", monthlyFcstSelectedDate());
  if (state.monthlySalesFcstAsOfRound) {
    params.set("as_of_round", state.monthlySalesFcstAsOfRound);
  }
  return `/api/monthly-sales-fcst?${params}`;
}

async function loadMonthlySalesFcst() {
  const month = monthlyFcstSelectedMonth();
  if (!month) return;
  $("#monthlyFcstGroups").classList.add("is-loading");
  try {
    const [result, erpStatus] = await Promise.all([
      api(monthlyFcstApiPath()),
      api("/api/erp/status").catch(() => null),
    ]);
    Object.assign(monthlyFcstBusinessLabels, result.business_units || {});
    if (monthlyFcstSectionFilterMonth !== result.month) {
      monthlyFcstResetAllSectionFilters();
      monthlyFcstSectionFilterMonth = result.month;
    }
    state.monthlySalesFcst = result;
    state.monthlySalesFcstErpStatus = erpStatus;
    renderMonthlySalesFcst();
  } catch (error) {
    toast(error.message, "error");
    $("#monthlyFcstGroups").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  } finally {
    $("#monthlyFcstGroups").classList.remove("is-loading");
  }
}

function monthlyFcstDisplayMoney(usd, krw, compact = false) {
  return `$${formatNumber(usd || 0, 2)}`;
}

function monthlyFcstDualMoney(usd, krw, signed = false) {
  const usdValue = Number(usd || 0);
  const krwValue = Number(krw || 0);
  const usdSign = signed && usdValue > 0 ? "+" : "";
  const krwSign = signed && krwValue > 0 ? "+" : "";
  return `<span class="monthly-fcst-dual-money"><strong>${usdSign}$${formatNumber(usdValue, 2)}</strong><small>${krwSign}₩${formatNumber(krwValue)}</small></span>`;
}

function monthlyFcstMetric(summary, key) {
  const usdKey = `${key}_usd`;
  const krwKey = `${key}_krw`;
  return monthlyFcstDisplayMoney(summary?.[usdKey] || 0, summary?.[krwKey] || 0, true);
}

function monthlyFcstToastResult(result) {
  if (result?.sheet_sync?.status === "failed") {
    toast(`${result.message || "앱 DB 저장 완료"} · Google Sheets 동기화 실패: ${result.sheet_sync.message}`, "error");
    return;
  }
  toast(result?.message || "처리를 완료했습니다.");
}

function renderMonthlySalesFcst() {
  const data = state.monthlySalesFcst;
  if (!data) return;
  const targetMonthInput = $("#monthlyFcstTargetMonth");
  if (targetMonthInput && targetMonthInput.value !== data.month) targetMonthInput.value = data.month;
  syncMonthlyFcstQuickTabs();
  renderMonthlyFcstPermissions(data);
  renderMonthlyFcstSheetStatus(data.sheet_sync);
  renderMonthlyFcstErpFreshness();
  renderMonthlyFcstRateBar(data);
  renderMonthlyFcstRounds(data.round_cards || []);
  renderMonthlyFcstLiveSummary(data.live_summary || data.summary || {}, data);
  renderMonthlyFcstSummary(data.summary || {}, data.compare_summary || null);
  renderMonthlyFcstRisks(data.rows || []);
  renderMonthlyFcstGroups(data.rows || []);
  renderMonthlyFcstRoundComparison(data.round_cards || []);
  syncMonthlyFcstFilterOptions(data.filters || {});
  updateMonthlyFcstGlobalFilterState();
}

function renderMonthlyFcstPermissions(data) {
  const editable = data.permissions.can_edit && data.month_setting.month_status === "open";
  $("#monthlyFcstAddBtn").classList.toggle("hidden", !editable);
  $("#monthlyFcstImportBtn").classList.toggle("hidden", !editable);
  $("#monthlyFcstCustomerLinksBtn").classList.toggle("hidden", !editable);
  const linkCount = Number(data.customer_link_summary?.needs_action || 0);
  $("#monthlyFcstCustomerLinksCount").textContent = linkCount ? `(${formatNumber(linkCount)})` : "";
  $("#monthlyFcstSettingsBtn").classList.toggle("hidden", !data.permissions.can_configure);
  $("#monthlyFcstSubmitBtn").classList.toggle("hidden", !data.permissions.can_manage || data.initial_fcst_submitted || data.read_only || data.month_setting.month_status === "closed");
  $("#monthlyFcstMonthToggleBtn").classList.toggle("hidden", !data.permissions.can_admin || data.read_only);
  $("#monthlyFcstMonthToggleBtn").textContent = data.month_setting.month_status === "closed" ? "마감월 재개방" : "월 마감";
  $("#monthlyFcstCurrentViewBtn").classList.toggle("hidden", !data.as_of);
  const notice = $("#monthlyFcstReadOnlyNotice");
  if (data.as_of) {
    notice.innerHTML = `<strong>${escapeHtml(monthlyFcstFormatMonth(data.month))} 예상매출 · ${escapeHtml(data.as_of)} 영업일 종료 기준</strong><span>해당 시점까지 시스템에 입력된 기록만 재현합니다. 실제 업무일(effective_at)은 이력에 별도로 보존되며 과거 화면에 소급하지 않습니다.</span>`;
    notice.classList.remove("hidden");
  } else if (data.month_setting.month_status === "closed") {
    notice.innerHTML = `<strong>${escapeHtml(data.month)} 마감 완료</strong><span>관리자가 사유를 입력해 재개방하기 전에는 수정·분리·차월할 수 없습니다.</span>`;
    notice.classList.remove("hidden");
  } else {
    notice.classList.add("hidden");
  }
}

function renderMonthlyFcstSheetStatus(sync) {
  const node = $("#monthlyFcstSheetStatus");
  const canManage = Boolean(state.monthlySalesFcst?.permissions?.can_manage);
  if (!sync?.configured) {
    node.className = `monthly-fcst-sync ${sync?.error ? "error" : "pending"}`;
    node.innerHTML = `<div><strong>${sync?.error ? "Google Sheets 설정 오류" : "Google Sheets 연결 준비"}</strong><span>${escapeHtml(sync?.error || "빈 Google Sheets 파일을 만든 뒤 서비스 계정 공유와 환경변수 설정이 필요합니다.")}</span></div>${canManage ? '<button class="mini-btn" data-monthly-open-settings type="button">설정방법</button>' : ""}`;
    return;
  }
  const failed = Boolean(sync.last_error);
  node.className = `monthly-fcst-sync ${failed ? "error" : sync.dirty ? "pending" : "success"}`;
  node.innerHTML = `<div><strong>${failed ? "Google Sheets 동기화 확인 필요" : sync.dirty ? "Google Sheets 동기화 대기" : "Google Sheets 동기화 완료"}</strong><span>${failed ? escapeHtml(sync.last_error) : sync.last_success_at ? `최근 성공 ${formatDate(sync.last_success_at, true)}` : "첫 동기화를 실행해 주세요."}</span></div>${canManage ? '<button class="mini-btn" data-monthly-sync-sheet type="button">지금 동기화</button>' : ""}`;
}

function renderMonthlyFcstErpFreshness() {
  const node = $("#monthlyFcstErpFreshness");
  if (!node) return;
  const status = state.monthlySalesFcstErpStatus;
  const freshness = status?.freshness || {};
  const last = status?.last_sync;
  node.className = `monthly-fcst-erp-freshness ${freshness.status === "normal" ? "success" : "warning"}`;
  node.innerHTML = `<div><strong>ERP Actual 최신성</strong><span>마지막 성공 ${last?.finished_at ? escapeHtml(formatDate(last.finished_at, true)) : "없음"} · 동기화 범위 ${escapeHtml(last?.date_from || "—")}~${escapeHtml(last?.date_to || "—")} · 최신 출고일 ${escapeHtml(freshness.latest_ship_date || "—")}</span></div><em>${escapeHtml(freshness.message || "상태 미확인")}</em>`;
}

function renderMonthlyFcstRateBar(data) {
  $("#monthlyFcstRateMonth").textContent = monthlyFcstFormatMonth(data.month);
  $("#monthlyFcstRateValues").innerHTML = monthlyFcstCurrencies.filter(currency => currency !== "KRW").map(currency => {
    const value = data.plan_rates?.[currency];
    const label = currency === "JPY" ? "JPY(1엔)" : currency;
    const amount = Number(value || 0) > 0 ? `${formatNumber(value, 4)}원` : "미설정";
    return `<span class="monthly-fcst-rate-value"><strong>${label}</strong><em>${amount}</em></span>`;
  }).join("");
}

function renderMonthlyFcstRounds(cards) {
  $("#monthlyFcstKpis").innerHTML = cards.map(card => {
    const unavailable = !card.available;
    const amount = unavailable ? '<span class="monthly-fcst-round-unavailable">—</span>' : monthlyFcstDualMoney(card.amount_usd, card.amount_krw);
    const secondary = card.secondary_label && card.available
      ? `<div class="monthly-fcst-round-secondary"><span>${escapeHtml(card.secondary_label)}</span>${monthlyFcstDualMoney(card.secondary_usd, card.secondary_krw)}</div>`
      : `<small>${escapeHtml(card.formula)}</small>`;
    const active = state.monthlySalesFcst?.as_of && state.monthlySalesFcst.as_of === card.cutoff_date
      && (!state.monthlySalesFcstAsOfRound || state.monthlySalesFcstAsOfRound === card.key);
    return `<button class="monthly-fcst-kpi monthly-fcst-round ${card.key} ${active ? "active" : ""} ${unavailable ? "unavailable" : ""}" data-monthly-round-date="${escapeHtml(card.cutoff_date || "")}" data-monthly-round-key="${escapeHtml(card.key)}" type="button" ${unavailable ? "disabled" : ""}><span>${escapeHtml(card.label)}</span>${amount}${secondary}<em>${card.cutoff_date ? `${escapeHtml(monthlyFcstFormatMonth(state.monthlySalesFcst.month))} 매출 · ${escapeHtml(monthlyFcstFormatShortDate(card.cutoff_date))} 기준` : "기준일 미설정"}</em></button>`;
  }).join("");
}

function renderMonthlyFcstLiveSummary(summary, data) {
  const liveStatus = data.live_status || { total: summary.total || {} };
  const historical = Boolean(data.as_of);
  $("#monthlyFcstLiveTitle").textContent = historical ? `${monthlyFcstFormatMonth(data.month)} 매출 · ${monthlyFcstFormatShortDate(data.live_as_of)} 기준 현황` : "오늘 기준 실시간 매출 현황";
  $("#monthlyFcstLiveDescription").textContent = historical
    ? "선택한 영업일 종료까지 시스템에 기록된 변경만 집계합니다. 실제 업무일은 상세 History에 별도로 보존됩니다."
    : "선택한 월의 오늘 현재 저장값을 기준으로 집계합니다.";
  $("#monthlyFcstLiveMeta").textContent = `${monthlyFcstFormatMonth(data.month)} · ${monthlyFcstFormatShortDate(data.live_as_of)} ${historical ? "기준" : "오늘 기준"}`;
  $("#monthlyFcstLiveSummary").innerHTML = monthlyFcstLiveScopes.map(row => {
    const values = liveStatus[row.key] || {};
    const metrics = monthlyFcstLiveMetrics.map((metric, index) => {
      const interactive = Boolean(metric.status || metric.carryover);
      const tag = interactive ? "button" : "div";
      const attributes = interactive
        ? ` type="button" data-monthly-summary-unit="total" data-monthly-summary-status="${metric.status || ""}" data-monthly-summary-timing="${row.timing || ""}" data-monthly-summary-carryover="${metric.carryover || ""}"`
        : "";
      return `<${tag} class="monthly-fcst-live-item ${metric.className} ${index === 0 ? "primary" : ""}"${attributes}><span>${escapeHtml(metric.label)}</span>${monthlyFcstDualMoney(values[`${metric.key}_usd`] || 0, values[`${metric.key}_krw`] || 0)}<small>${escapeHtml(metric.note)}</small></${tag}>`;
    }).join("");
    return `<section class="monthly-fcst-live-row"><div class="monthly-fcst-live-row-label"><strong>${escapeHtml(row.label)}</strong><span>${escapeHtml(row.note)}</span></div><div class="monthly-fcst-live-row-metrics columns-${monthlyFcstLiveMetrics.length}">${metrics}</div></section>`;
  }).join("");
}

function monthlyFcstRoundStageCell(card, scopeKey, metricKey) {
  if (!card?.available || !card.comparison) return '<td class="monthly-fcst-round-value unavailable">—</td>';
  const values = card.comparison[scopeKey] || {};
  return `<td class="monthly-fcst-round-value">${monthlyFcstDualMoney(values[`${metricKey}_usd`] || 0, values[`${metricKey}_krw`] || 0)}</td>`;
}

function monthlyFcstRoundDeltaCell(card, previousCard, scopeKey, metricKey) {
  if (!card?.available || !previousCard?.available || !card.comparison || !previousCard.comparison) {
    return '<td class="monthly-fcst-round-delta unavailable">—</td>';
  }
  const current = card.comparison[scopeKey] || {};
  const previous = previousCard.comparison[scopeKey] || {};
  const currentUsd = Number(current[`${metricKey}_usd`] || 0);
  const currentKrw = Number(current[`${metricKey}_krw`] || 0);
  const previousUsd = Number(previous[`${metricKey}_usd`] || 0);
  const previousKrw = Number(previous[`${metricKey}_krw`] || 0);
  const deltaUsd = currentUsd - previousUsd;
  const deltaKrw = currentKrw - previousKrw;
  const direction = deltaUsd > 0 ? "up" : deltaUsd < 0 ? "down" : "flat";
  const rate = previousUsd
    ? `${deltaUsd > 0 ? "+" : ""}${formatNumber(deltaUsd / Math.abs(previousUsd) * 100, 1)}%`
    : currentUsd ? "신규 발생" : "0.0%";
  return `<td class="monthly-fcst-round-delta ${direction}">${monthlyFcstDualMoney(deltaUsd, deltaKrw, true)}<small>${escapeHtml(rate)}</small></td>`;
}

function renderMonthlyFcstRoundComparison(cards) {
  const node = $("#monthlyFcstRoundComparison");
  if (!node) return;
  const orderedKeys = ["initial", "round1", "round2", "round3", "final"];
  const stages = orderedKeys.map(key => cards.find(card => card.key === key) || { key, label: key, available: false });
  const headers = stages.map((card, index) => {
    const stage = `<th class="monthly-fcst-round-stage"><strong>${escapeHtml(card.label)}</strong><small>${card.cutoff_date ? `${escapeHtml(monthlyFcstFormatShortDate(card.cutoff_date))} 기준` : "기준일 미설정"}</small></th>`;
    if (!index) return stage;
    return `${stage}<th class="monthly-fcst-round-delta-head">${escapeHtml(stages[index - 1].label)} 대비</th>`;
  }).join("");
  const body = monthlyFcstLiveScopes.map(scope => monthlyFcstLiveMetrics.map((metric, metricIndex) => {
    const scopeCell = metricIndex === 0
      ? `<th class="monthly-fcst-round-scope" rowspan="${monthlyFcstLiveMetrics.length}"><strong>${escapeHtml(scope.label)}</strong><small>${escapeHtml(scope.note)}</small></th>`
      : "";
    const values = stages.map((card, index) => {
      const valueCell = monthlyFcstRoundStageCell(card, scope.key, metric.key);
      return index ? `${valueCell}${monthlyFcstRoundDeltaCell(card, stages[index - 1], scope.key, metric.key)}` : valueCell;
    }).join("");
    return `<tr class="${metricIndex === 0 ? "scope-start" : ""}">${scopeCell}<th class="monthly-fcst-round-metric"><i class="${metric.className}"></i><strong>${escapeHtml(metric.label)}</strong><small>${escapeHtml(metric.note)}</small></th>${values}</tr>`;
  }).join("")).join("");
  node.innerHTML = `<div class="monthly-fcst-round-comparison-wrap"><table class="monthly-fcst-round-comparison-table"><thead><tr><th class="monthly-fcst-round-scope-head">구분</th><th class="monthly-fcst-round-metric-head">항목</th>${headers}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function monthlyFcstSummaryCell(item, key, status = "") {
  const usd = item[`${key}_usd`] || 0;
  const krw = item[`${key}_krw`] || 0;
  return `<button class="monthly-fcst-number" data-monthly-summary-unit="${item.business_unit}" data-monthly-summary-status="${status}" type="button">${monthlyFcstDualMoney(usd, krw)}</button>`;
}

function renderMonthlyFcstSummary(summary, compareSummary) {
  const keys = ["aesthetic", "medical", "dental", "total"];
  $("#monthlyFcstSummaryBody").innerHTML = keys.map(key => {
    const item = summary[key] || {};
    const compare = compareSummary?.[key];
    const comparison = compare ? item.current_fcst_usd - compare.current_fcst_usd : null;
    const comparisonKrw = compare ? item.current_fcst_krw - compare.current_fcst_krw : null;
    const compareMarkup = comparison == null ? "" : `<span class="summary-delta ${comparison < 0 ? "down" : "up"}">${monthlyFcstDualMoney(comparison, comparisonKrw, true)}</span>`;
    const note = item.target_variance_usd >= 0 ? "목표 이상" : "목표 미달";
    return `<tr class="${key === "total" ? "total" : ""}"><th>${escapeHtml(monthlyFcstBusinessLabels[key])}</th><td>${monthlyFcstDualMoney(item.target_usd, item.target_krw)}</td><td>${monthlyFcstDualMoney(item.initial_fcst_usd, item.initial_fcst_krw)}</td><td>${monthlyFcstDualMoney(item.current_fcst_usd, item.current_fcst_krw)}${compareMarkup}</td><td>${monthlyFcstDualMoney(item.carryover_in_usd, item.carryover_in_krw)}</td><td>${monthlyFcstDualMoney(item.new_usd, item.new_krw)}</td><td>${monthlyFcstSummaryCell(item, "confirmed", "confirmed")}</td><td>${monthlyFcstSummaryCell(item, "scheduled", "scheduled")}</td><td>${monthlyFcstSummaryCell(item, "pipeline", "pipeline")}</td><td>${monthlyFcstSummaryCell(item, "undecided", "undecided")}</td><td>${monthlyFcstDualMoney(item.high_confidence_usd, item.confirmed_krw + item.scheduled_krw)}</td><td>${monthlyFcstDualMoney(item.carryover_out_usd, item.carryover_out_krw)}</td><td class="${item.target_variance_usd < 0 ? "negative" : "positive"}">${monthlyFcstDualMoney(item.target_variance_usd, item.target_variance_krw, true)}</td><td class="${item.initial_variance_usd < 0 ? "negative" : "positive"}">${monthlyFcstDualMoney(item.initial_variance_usd, item.initial_variance_krw, true)}</td><td><strong>${item.achievement_pct == null ? "—" : `${formatNumber(item.achievement_pct, 1)}%`}</strong></td><td>${escapeHtml(note)}</td></tr>`;
  }).join("");
}

function renderMonthlyFcstRisks(rows) {
  const risks = rows
    .filter(row => monthlyFcstLedgerSection(row) !== "lineage_hidden")
    .flatMap(row => (row.warnings || []).map(warning => ({ row, warning })));
  $("#monthlyFcstRiskCount").textContent = "";
  $("#monthlyFcstRisks").innerHTML = risks.length ? risks.slice(0, 12).map(({ row, warning }) => `<button class="monthly-fcst-risk ${warning.level}" data-monthly-focus-row="${row.id}" type="button"><span>${warning.level === "error" ? "오류" : "주의"}</span><strong>${escapeHtml(row.customer_name)}</strong><small>${escapeHtml(row.sales_no)} · ${escapeHtml(warning.message)}</small></button>`).join("") : '<div class="classification-ok">현재 필터 기준으로 확인이 필요한 오류·주의사항이 없습니다.</div>';
}

function monthlyFcstBadges(row) {
  return [
    row.historical_round_key ? `<span class="monthly-fcst-tag historical">과거 ${escapeHtml({ initial: "최초 FCST", round1: "1차", round2: "2차", round3: "3차", final: "최종마감" }[row.historical_round_key] || "차수")}</span>` : "",
    row.customer_link_status === "temp_created" ? '<span class="monthly-fcst-tag customer-temp">임시등록</span>' : "",
    !row.customer_master_id || row.customer_link_status === "unlinked" ? '<span class="monthly-fcst-tag customer-review">마스터 미연결</span>' : "",
    row.customer_link_status === "review" ? '<span class="monthly-fcst-tag customer-review">연결오류</span>' : "",
    row.customer_link_status === "excluded" ? '<span class="monthly-fcst-tag customer-excluded">연결 제외</span>' : "",
    row.split_role === "original" ? '<span class="monthly-fcst-tag split-original">분리 원본</span>' : "",
    (["split", "carryover_split"].includes(row.split_role) || row.original_sales_id) ? '<span class="monthly-fcst-tag split">분리 매출</span>' : "",
    row.carryover_role === "inflow" ? '<span class="monthly-fcst-tag inflow">이월</span>' : "",
    row.carryover_role === "outflow" || row.record_status === "carried_over" ? '<span class="monthly-fcst-tag carryover">차월 처리</span>' : "",
    row.ledger_section === "cancelled" ? '<span class="monthly-fcst-tag cancelled">매출건 취소</span>' : "",
  ].filter(Boolean).join("");
}

function monthlyFcstFormatShortDate(value) {
  if (!value) return "—";
  const match = String(value).match(/^\d{4}-(\d{2})-(\d{2})$/);
  return match ? `${Number(match[1])}/${Number(match[2])}` : String(value);
}

function monthlyFcstFormatMonth(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})$/);
  return match ? `${match[1]}년 ${Number(match[2])}월` : String(value || "");
}

function monthlyFcstFormatCompactMonth(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})$/);
  return match ? `${Number(match[2])}월` : String(value || "");
}

function monthlyFcstUsd(value) {
  return `$${formatNumber(Number(value || 0), 2)}`;
}

function monthlyFcstKrw(value) {
  return `₩${formatNumber(Number(value || 0))}`;
}

function monthlyFcstProgress(row) {
  return `<div class="monthly-fcst-progress" aria-label="${escapeHtml(row.customer_name)} 진행단계">${(row.progress || []).map(stage => {
    const paired = ["payment", "shipment", "shipping"].includes(stage.key);
    const dateMarkup = paired
      ? `<small><em>예정</em>${escapeHtml(monthlyFcstFormatShortDate(stage.expected))}</small><small class="${stage.completed ? "actual" : ""}"><em>완료</em>${escapeHtml(monthlyFcstFormatShortDate(stage.actual))}</small>`
      : `<small class="${stage.completed ? "actual" : ""}">${escapeHtml(monthlyFcstFormatShortDate(stage.actual))}</small>`;
    return `<span class="${stage.completed ? "done" : stage.overdue ? "overdue" : stage.current ? "current" : ""}" title="${escapeHtml(stage.label)} · 실제 ${escapeHtml(stage.actual || "미입력")} · 예상 ${escapeHtml(stage.expected || "미입력")}"><i></i><b>${escapeHtml(stage.label)}</b>${dateMarkup}</span>`;
  }).join("")}</div>`;
}

function monthlyFcstCarryoverDecision(row) {
  return row.carryover_decision || (row.carryover_role === "outflow" || row.record_status === "carried_over" ? "yes" : "no");
}

function monthlyFcstLedgerSection(row) {
  if (row.ledger_section) return row.ledger_section;
  if (row.record_status === "carried_over") return "carried_over";
  if (row.record_status === "cancelled") return "cancelled";
  return row.sales_status;
}

function monthlyFcstCarryoverMarkup(row) {
  const outgoing = (row.carryover_history || []).at(-1);
  if (outgoing) {
    const retained = outgoing.status === "cancelled"
      ? `<strong class="monthly-fcst-carryover-no">당월 유지</strong><small>${escapeHtml(outgoing.cancel_effective_at || "처리일 확인")}</small>`
      : "";
    return `<strong class="monthly-fcst-carryover-yes">차월 처리</strong><small>${escapeHtml(outgoing.carryover_date || "—")}</small><small>→ ${escapeHtml(monthlyFcstFormatCompactMonth(outgoing.target_month))}</small>${retained}`;
  }
  const incoming = [...(row.carryover_in_history || [])].reverse().find(item => item.status === "active");
  if (incoming) {
    return `<strong class="monthly-fcst-carryover-in">${escapeHtml(monthlyFcstFormatCompactMonth(incoming.source_month))} 이월</strong><small>${escapeHtml(incoming.carryover_date || "—")}</small>`;
  }
  if (monthlyFcstCarryoverDecision(row) !== "yes") return '<span class="monthly-fcst-carryover-no">당월 유지</span>';
  const decisionDate = row.carryover_decided_at || "—";
  const targetMonth = row.carryover_target_month ? escapeHtml(monthlyFcstFormatCompactMonth(row.carryover_target_month)) : "대상월 미정";
  return `<strong class="monthly-fcst-carryover-planned">차월 예정</strong><small>${escapeHtml(decisionDate)}</small><small>→ ${targetMonth}</small>`;
}

function monthlyFcstActionButtons(row, readOnly) {
  const archived = Boolean(row.historical_round_key);
  if (archived) return [];
  const actionItems = [];
  if (!readOnly && row.record_status === "active") actionItems.push(
    `<button data-monthly-row-action="edit" data-id="${row.id}" type="button">수정</button>`
  );
  actionItems.push(`<button data-monthly-row-action="history" data-id="${row.id}" type="button">이력</button>`);
  if (!readOnly && row.record_status === "active") actionItems.push(
    `<button data-monthly-row-action="replan" data-id="${row.id}" type="button">계획환율 재적용</button>`,
    `<button data-monthly-row-action="split" data-id="${row.id}" type="button">매출 분리</button>`,
    `<button data-monthly-row-action="carryover" data-id="${row.id}" type="button">차월 처리</button>`,
    `<button class="danger" data-monthly-row-action="cancel" data-id="${row.id}" type="button">매출건 취소</button>`,
  );
  if (!readOnly && ["original", "split"].includes(row.split_role)) actionItems.push(`<button data-monthly-row-action="split-cancel" data-id="${row.id}" type="button">분리 취소</button>`);
  if (!readOnly && row.carryover_role !== "none") actionItems.push(`<button data-monthly-row-action="carryover-cancel" data-id="${row.id}" type="button">차월 취소</button>`);
  if (!readOnly && row.restore_allowed) actionItems.push(`<button data-monthly-row-action="restore" data-id="${row.id}" type="button">매출건 복원</button>`);
  return actionItems;
}

function monthlyFcstRowMarkup(row, readOnly) {
  const warning = (row.warnings || []).length ? `<span class="monthly-fcst-warning" title="확인 필요 ${row.warnings.length}건 · ${escapeHtml(row.warnings.map(item => item.message).join(", "))}">${row.warnings.length}</span>` : "";
  const disabled = row.record_status !== "active";
  const transactionCurrency = row.transaction_currency || "USD";
  const transactionAmount = row.transaction_amount || row.amount_usd;
  const customerHistory = row.customer_history || "existing";
  const rateUnit = transactionCurrency === "JPY" && row.applied_rate ? " / 1엔" : "";
  return `<tr id="monthly-fcst-row-${row.id}" class="monthly-fcst-clickable-row ${disabled ? "inactive" : ""}" data-monthly-row-id="${row.id}" tabindex="0"><td class="monthly-fcst-sticky sales-no-cell"><strong>${escapeHtml(row.sales_no)}</strong>${warning}<div>${monthlyFcstBadges(row)}</div></td><td class="monthly-fcst-sticky customer-cell"><strong>${escapeHtml(row.customer_name)}</strong></td><td>${escapeHtml(row.country)}</td><td class="amount-cell monthly-fcst-amount-cell"><strong>${monthlyFcstUsd(row.amount_usd)}</strong><small>${escapeHtml(transactionCurrency)} ${formatNumber(transactionAmount, 2)}</small><small>${monthlyFcstKrw(row.krw_amount)} · ${escapeHtml(monthlyFcstRateLabels[row.rate_type])} ${row.applied_rate ? formatNumber(row.applied_rate, 4) : "—"}${rateUnit}</small></td><td>${monthlyFcstProgress(row)}</td><td><strong>${escapeHtml(monthlyFcstTimingLabels[row.timing_type])}</strong></td><td class="monthly-fcst-carryover-cell">${monthlyFcstCarryoverMarkup(row)}</td><td><strong>${escapeHtml(monthlyFcstBusinessLabels[row.business_unit])}</strong></td><td><strong>${escapeHtml(monthlyFcstCustomerHistoryLabels[customerHistory])}</strong></td><td class="monthly-fcst-original-month"><strong>${escapeHtml(monthlyFcstFormatMonth(row.original_month))}</strong></td><td><strong>${escapeHtml(row.owner_name)}</strong></td><td class="monthly-fcst-notes">${escapeHtml(row.notes || "—")}</td><td class="monthly-fcst-row-chevron" aria-hidden="true">›</td></tr>`;
}

function monthlyFcstSectionFieldValue(row, field) {
  if (field === "carryover_decision") return monthlyFcstCarryoverDecision(row);
  return String(row[field] ?? "");
}

function monthlyFcstSectionOptionLabel(field, value) {
  if (field === "business_unit") return monthlyFcstBusinessLabels[value] || value;
  if (field === "timing_type") return monthlyFcstTimingLabels[value] || value;
  if (field === "customer_history") return monthlyFcstCustomerHistoryLabels[value] || value;
  if (field === "carryover_decision") return value === "yes" ? "차월 예정·처리" : "당월 유지";
  return value;
}

function monthlyFcstSectionFilteredRows(status, rows) {
  const filters = monthlyFcstSectionFilters[status];
  return rows.filter(row => monthlyFcstSectionFilterFields.every(field => {
    const selected = filters[field];
    return !selected.size || selected.has(monthlyFcstSectionFieldValue(row, field));
  }));
}

function monthlyFcstSectionActiveFilterCount(status) {
  return monthlyFcstSectionFilterFields.reduce((total, field) => total + monthlyFcstSectionFilters[status][field].size, 0);
}

function monthlyFcstCloneSectionFilters(status) {
  return Object.fromEntries(monthlyFcstSectionFilterFields.map(field => [field, new Set(monthlyFcstSectionFilters[status][field])]));
}

function monthlyFcstSectionAvailableValues(field) {
  const fixed = monthlyFcstSectionFixedOptions[field] || [];
  const source = monthlyFcstSectionFilterSources[field];
  const registered = source ? (state.monthlySalesFcst?.filters?.[source] || []) : [];
  const rows = (state.monthlySalesFcst?.rows || []).map(row => monthlyFcstSectionFieldValue(row, field));
  const selected = monthlyFcstSectionFilterDraft?.[field] ? [...monthlyFcstSectionFilterDraft[field]] : [];
  const values = [...new Set([...fixed, ...registered, ...rows, ...selected].map(value => String(value || "").trim()).filter(Boolean))];
  const extras = values.filter(value => !fixed.includes(value))
    .sort((a, b) => monthlyFcstSectionOptionLabel(field, a).localeCompare(monthlyFcstSectionOptionLabel(field, b), "ko"));
  return [...fixed, ...extras];
}

function monthlyFcstSectionFilterDrawerMarkup() {
  return monthlyFcstSectionFilterFields.map((field, index) => {
    const selected = monthlyFcstSectionFilterDraft[field];
    const values = monthlyFcstSectionAvailableValues(field);
    const search = monthlyFcstSectionSearchFields.has(field)
      ? `<input type="search" data-monthly-section-option-search placeholder="${monthlyFcstSectionFilterLabels[field]} 검색" aria-label="${monthlyFcstSectionFilterLabels[field]} 검색">`
      : "";
    const options = values.length
      ? values.map(value => `<button class="monthly-fcst-filter-option ${selected.has(value) ? "selected" : ""}" data-monthly-filter-field="${field}" data-monthly-filter-value="${escapeHtml(value)}" type="button" aria-pressed="${selected.has(value)}">${escapeHtml(monthlyFcstSectionOptionLabel(field, value))}</button>`).join("")
      : '<span class="monthly-fcst-section-no-option">등록된 선택항목이 없습니다.</span>';
    return `<details class="monthly-fcst-filter-field ${selected.size ? "active" : ""}" ${(index === 0 || selected.size) ? "open" : ""}><summary><strong>${monthlyFcstSectionFilterLabels[field]}</strong><span class="monthly-fcst-filter-field-state">${selected.size ? "선택됨" : "전체"}</span></summary><div class="monthly-fcst-filter-field-body">${search}<div class="monthly-fcst-filter-options">${options}</div></div></details>`;
  }).join("");
}

function openMonthlyFcstSectionFilter(status) {
  monthlyFcstSectionFilterDraftStatus = status;
  monthlyFcstSectionFilterDraft = monthlyFcstCloneSectionFilters(status);
  $("#monthlyFcstSectionFilterTitle").textContent = `${monthlyFcstStatusLabels[status]} 필터`;
  $("#monthlyFcstSectionFilterFields").innerHTML = monthlyFcstSectionFilterDrawerMarkup();
  $("#monthlyFcstSectionFilterDialog").showModal();
}

function handleMonthlyFcstSectionFilterOption(event) {
  const button = event.target.closest("[data-monthly-filter-field][data-monthly-filter-value]");
  if (!button || !monthlyFcstSectionFilterDraft) return;
  const selected = monthlyFcstSectionFilterDraft[button.dataset.monthlyFilterField];
  selected.has(button.dataset.monthlyFilterValue) ? selected.delete(button.dataset.monthlyFilterValue) : selected.add(button.dataset.monthlyFilterValue);
  const active = selected.has(button.dataset.monthlyFilterValue);
  button.classList.toggle("selected", active);
  button.setAttribute("aria-pressed", String(active));
  const field = button.closest(".monthly-fcst-filter-field");
  field.classList.toggle("active", Boolean(selected.size));
  field.querySelector(".monthly-fcst-filter-field-state").textContent = selected.size ? "선택됨" : "전체";
}

function handleMonthlyFcstSectionFilterSearch(event) {
  const input = event.target.closest("[data-monthly-section-option-search]");
  if (!input) return;
  const query = input.value.trim().toLocaleLowerCase();
  input.parentElement.querySelectorAll(".monthly-fcst-filter-option").forEach(option => {
    option.hidden = Boolean(query) && !option.textContent.toLocaleLowerCase().includes(query);
  });
}

function resetMonthlyFcstSectionFilterDraft() {
  if (!monthlyFcstSectionFilterDraft) return;
  monthlyFcstSectionFilterFields.forEach(field => monthlyFcstSectionFilterDraft[field].clear());
  $("#monthlyFcstSectionFilterFields").innerHTML = monthlyFcstSectionFilterDrawerMarkup();
}

function applyMonthlyFcstSectionFilter(event) {
  event.preventDefault();
  if (!monthlyFcstSectionFilterDraft || !monthlyFcstSectionFilterDraftStatus) return;
  monthlyFcstSectionFilterFields.forEach(field => {
    monthlyFcstSectionFilters[monthlyFcstSectionFilterDraftStatus][field] = new Set(monthlyFcstSectionFilterDraft[field]);
  });
  $("#monthlyFcstSectionFilterDialog").close();
  monthlyFcstSectionFilterDraft = null;
  renderMonthlyFcstGroups(state.monthlySalesFcst.rows || []);
}

function monthlyFcstSectionSubtotalMarkup(status, visibleItems, totalItems) {
  const ledgerRows = visibleItems.filter(row => monthlyFcstLedgerSection(row) === status);
  const customerCount = new Set(ledgerRows.map(row => row.customer_name.trim().toLocaleLowerCase())).size;
  const usd = ledgerRows.reduce((sum, row) => sum + Number(row.amount_usd || 0), 0);
  const krw = ledgerRows.reduce((sum, row) => sum + Number(row.krw_amount || 0), 0);
  return `<tr class="monthly-fcst-subtotal"><td class="monthly-fcst-sticky sales-no-cell"><strong>${monthlyFcstStatusLabels[status]} 소계</strong></td><td class="monthly-fcst-sticky customer-cell"><strong>거래처 ${formatNumber(customerCount)}곳</strong></td><td>—</td><td class="amount-cell"><strong>${monthlyFcstUsd(usd)}</strong><small>${monthlyFcstKrw(krw)}</small></td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>`;
}

function monthlyFcstResetAllSectionFilters() {
  monthlyFcstStatuses.forEach(status => monthlyFcstSectionFilterFields.forEach(field => monthlyFcstSectionFilters[status][field].clear()));
}

function renderMonthlyFcstGroups(rows) {
  const data = state.monthlySalesFcst;
  let visibleRowCount = 0;
  const markup = monthlyFcstStatuses.map(status => {
    const items = rows.filter(row => monthlyFcstLedgerSection(row) === status);
    const visibleItems = monthlyFcstSectionFilteredRows(status, items);
    visibleRowCount += visibleItems.length;
    const expanded = state.monthlySalesFcstExpanded.has(status);
    const filterCount = monthlyFcstSectionActiveFilterCount(status);
    const emptyText = filterCount ? "이 섹션의 필터 조건에 해당하는 매출 건이 없습니다." : "해당 상태의 매출 건이 없습니다.";
    const rowsMarkup = visibleItems.length ? visibleItems.map(row => monthlyFcstRowMarkup(row, data.read_only || !data.permissions.can_edit || data.month_setting.month_status === "closed")).join("") : `<tr><td colspan="13"><div class="empty-state">${emptyText}</div></td></tr>`;
    return `<section class="monthly-fcst-group ${status}"><div class="monthly-fcst-group-head"><button class="monthly-fcst-group-toggle" data-monthly-toggle-group="${status}" type="button" aria-expanded="${expanded}"><span class="monthly-fcst-chevron ${expanded ? "open" : ""}">›</span><strong>${monthlyFcstStatusLabels[status]}</strong></button><button class="monthly-fcst-group-filter-btn ${filterCount ? "active" : ""}" data-monthly-open-section-filter="${status}" type="button"><span>필터</span><em>${filterCount ? "적용됨" : "선택"}</em></button></div><div class="monthly-fcst-group-body ${expanded ? "" : "hidden"}"><div class="monthly-fcst-ledger-wrap"><table class="monthly-fcst-ledger"><thead><tr><th class="monthly-fcst-sticky sales-no-cell">관리번호</th><th class="monthly-fcst-sticky customer-cell">거래처</th><th>국가</th><th>매출액</th><th>진행현황</th><th>진행시점</th><th>차월구분</th><th>사업분야</th><th>신규/기존</th><th>최초 추진월</th><th>담당자</th><th>비고</th><th aria-label="상세 열기"></th></tr></thead><tbody>${rowsMarkup}${monthlyFcstSectionSubtotalMarkup(status, visibleItems, items)}</tbody></table></div></div></section>`;
  }).join("");
  $("#monthlyFcstGroups").innerHTML = markup;
}

function syncMonthlyFcstSelect(id, values) {
  const select = $(id);
  const selected = select.value;
  select.innerHTML = '<option value="">전체</option>' + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  if (values.includes(selected)) select.value = selected;
}

function syncMonthlyFcstFilterOptions(filters) {
  syncMonthlyFcstSelect("#monthlyFcstOwner", filters.owners || []);
  syncMonthlyFcstSelect("#monthlyFcstCountry", filters.countries || []);
  syncMonthlyFcstSelect("#monthlyFcstCustomer", filters.customers || []);
  syncMonthlyFcstSelect("#monthlyFcstOriginalMonth", filters.original_months || []);
}

function monthlyFcstFindSale(id) {
  return state.monthlySalesFcst?.rows?.find(row => row.id === id) || null;
}

function monthlyFcstMasterConnectionLabel(row) {
  if (row.customer_link_status === "temp_created") return "임시등록";
  if (!row.customer_master_id || row.customer_link_status === "unlinked") return "마스터 미연결";
  if (row.customer_link_status === "review") return "연결오류";
  if (row.customer_link_status === "excluded") return "연결 제외";
  return "Customer Master 연결됨";
}

function monthlyFcstDetailField(label, value, className = "") {
  return `<div class="monthly-fcst-detail-field ${className}"><span>${escapeHtml(label)}</span><strong>${value}</strong></div>`;
}

function openMonthlyFcstDetailDrawer(sale) {
  if (!sale) return;
  state.monthlySalesFcstSelected = sale.id;
  const readOnly = Boolean(state.monthlySalesFcst?.read_only || !state.monthlySalesFcst?.permissions?.can_edit || state.monthlySalesFcst?.month_setting?.month_status === "closed");
  const currency = sale.transaction_currency || "USD";
  const transactionAmount = sale.transaction_amount || sale.amount_usd;
  $("#monthlyFcstDetailTitle").textContent = `${sale.sales_no} · ${sale.customer_name}`;
  $("#monthlyFcstDetailSubtitle").textContent = `${monthlyFcstFormatMonth(sale.target_month)} 예상매출 · ${readOnly ? "조회 전용" : "현재 상태"}`;
  const masterStatus = monthlyFcstMasterConnectionLabel(sale);
  const masterId = sale.customer_master_id ? `<small>${escapeHtml(String(sale.customer_master_id))}</small>` : "";
  $("#monthlyFcstDetailBody").innerHTML = `
    <section><h3>핵심정보</h3><div class="monthly-fcst-detail-grid">
      ${monthlyFcstDetailField("거래처", escapeHtml(sale.customer_name))}
      ${monthlyFcstDetailField("거래처 국가", escapeHtml(sale.country))}
      ${monthlyFcstDetailField("매출액", `${monthlyFcstUsd(sale.amount_usd)}<small>${escapeHtml(currency)} ${formatNumber(transactionAmount, 2)} · ${monthlyFcstKrw(sale.krw_amount)}</small>`, "wide")}
      ${monthlyFcstDetailField("영업 진행상태", escapeHtml(monthlyFcstStatusLabels[sale.sales_status] || sale.sales_status))}
      ${monthlyFcstDetailField("진행시점", escapeHtml(monthlyFcstTimingLabels[sale.timing_type] || sale.timing_type))}
      ${monthlyFcstDetailField("차월구분", monthlyFcstCarryoverMarkup(sale))}
    </div></section>
    <section><h3>진행현황</h3>${monthlyFcstProgress(sale)}</section>
    <section><h3>FCST Snapshot·Master 연결</h3><div class="monthly-fcst-detail-grid">
      ${monthlyFcstDetailField("사업분야", escapeHtml(monthlyFcstBusinessLabels[sale.business_unit] || sale.business_unit))}
      ${monthlyFcstDetailField("담당자", escapeHtml(sale.owner_name || "—"))}
      ${monthlyFcstDetailField("최초 추진월", escapeHtml(monthlyFcstFormatMonth(sale.original_month)))}
      ${monthlyFcstDetailField("신규/기존", escapeHtml(monthlyFcstCustomerHistoryLabels[sale.customer_history || "existing"]))}
      ${monthlyFcstDetailField("Master 상태", `${escapeHtml(masterStatus)}${masterId}`, "wide")}
    </div><p>거래처명·국가·담당자는 이 FCST에 저장된 Snapshot입니다. 거래처 기준정보 수정은 Customer Master에서 진행합니다.</p></section>
    ${sale.commercial_context&&Object.keys(sale.commercial_context).length?`<section><h3>Order Commercial Context Snapshot</h3><div class="monthly-fcst-commercial-context">${monthlyFcstContextMarkup(sale.commercial_context)}</div><p>Master가 나중에 변경되어도 이 FCST의 당시 적용조건은 바뀌지 않습니다.</p></section>`:''}
    <section><h3>비고</h3><div class="monthly-fcst-detail-notes">${escapeHtml(sale.notes || "—")}</div></section>`;
  const actions = monthlyFcstActionButtons(sale, readOnly);
  $("#monthlyFcstDetailActions").innerHTML = actions.length ? actions.join("") : '<span>이관된 차수자료는 조회만 가능합니다.</span>';
  $("#monthlyFcstDetailDrawer").showModal();
}

function bindMonthlySalesFcstEvents() {
  $$('[data-monthly-fcst-tab]').forEach(button => button.addEventListener("click", () => switchMonthlyFcstTab(button.dataset.monthlyFcstTab)));
  if (!$("#monthlyFcstTargetMonth").value) $("#monthlyFcstTargetMonth").value = monthlyFcstCurrentMonth();
  if (!$("#monthlyFcstDate").value) $("#monthlyFcstDate").value = monthlyFcstCurrentDate();
  $("#monthlyFcstDate").max = monthlyFcstCurrentDate();
  $("#monthlyFcstTargetMonth").addEventListener("change", changeMonthlyFcstTargetMonth);
  $("#monthlyFcstDate").addEventListener("change", changeMonthlyFcstAsOfDate);
  $("#monthlyFcstGlobalFilterBtn").addEventListener("click", openMonthlyFcstGlobalFilter);
  $("#monthlyFcstGlobalFilterForm").addEventListener("submit", applyMonthlyFcstGlobalFilter);
  $("#monthlyFcstGlobalFilterDialog").addEventListener("close", () => {
    if (!monthlyFcstGlobalFilterCommitted && monthlyFcstGlobalFilterSnapshot) {
      Object.entries(monthlyFcstGlobalFilterSnapshot).forEach(([id, value]) => { $("#" + id).value = value; });
    }
    monthlyFcstGlobalFilterCommitted = false;
    monthlyFcstGlobalFilterSnapshot = null;
  });
  $$('[data-monthly-global-filter-cancel]').forEach(button => button.addEventListener("click", cancelMonthlyFcstGlobalFilter));
  $("#monthlyFcstFilterReset").addEventListener("click", resetMonthlyFcstFilterDialog);
  $("#monthlyFcstCurrentViewBtn").addEventListener("click", returnMonthlyFcstCurrentView);
  $("#monthlyFcstKpis").addEventListener("click", selectMonthlyFcstRound);
  $("#monthlyFcstAddBtn").addEventListener("click", () => openMonthlyFcstSaleDialog());
  $("#monthlyFcstSaleForm").addEventListener("submit", saveMonthlyFcstSale);
  $("#monthlyFcstSaleForm").addEventListener("input", renderMonthlyFcstConversionPreview);
  $("#monthlyFcstSaleForm").addEventListener("change", event => {
    renderMonthlyFcstCarryoverFields();
    renderMonthlyFcstConfirmationFields();
    if (event.target.name === "customer_master_id") syncMonthlyFcstSelectedCustomer();
    if (event.target.name === "owner_user_id") syncMonthlyFcstSelectedOwner();
    if (["interim_product_code","target_month"].includes(event.target.name)) refreshMonthlyFcstPromotions().then(renderMonthlyFcstCommercialContext);
    if (["pricing_selection","promotion_id","detach_promotion"].includes(event.target.name)) renderMonthlyFcstCommercialContext();
  });
  $("#monthlyFcstQuickCustomerOpenBtn").addEventListener("click", () => toggleMonthlyFcstQuickCustomer(true));
  $("#monthlyFcstQuickCustomerCancelBtn").addEventListener("click", () => toggleMonthlyFcstQuickCustomer(false));
  $("#monthlyFcstQuickCustomerSaveBtn").addEventListener("click", saveMonthlyFcstQuickCustomer);
  $("#monthlyFcstCustomerLinksBtn").addEventListener("click", openMonthlyFcstCustomerLinks);
  $("#monthlyFcstCustomerAutoMatchBtn").addEventListener("click", autoMatchMonthlyFcstCustomers);
  $("#monthlyFcstCustomerLinkFilter").addEventListener("change", renderMonthlyFcstCustomerLinks);
  $("#monthlyFcstCustomerLinkList").addEventListener("click", handleMonthlyFcstCustomerLinkAction);
  $("#monthlyFcstGroups").addEventListener("click", handleMonthlyFcstGroupClick);
  $("#monthlyFcstGroups").addEventListener("keydown", handleMonthlyFcstGroupKeydown);
  $("#monthlyFcstDetailActions").addEventListener("click", handleMonthlyFcstDetailAction);
  $("#monthlyFcstSectionFilterFields").addEventListener("click", handleMonthlyFcstSectionFilterOption);
  $("#monthlyFcstSectionFilterFields").addEventListener("input", handleMonthlyFcstSectionFilterSearch);
  $("#monthlyFcstSectionFilterForm").addEventListener("submit", applyMonthlyFcstSectionFilter);
  $("#monthlyFcstSectionFilterResetBtn").addEventListener("click", resetMonthlyFcstSectionFilterDraft);
  $("#monthlyFcstRisks").addEventListener("click", handleMonthlyFcstRiskClick);
  $("#monthlyFcstLiveSummary").addEventListener("click", handleMonthlyFcstSummaryClick);
  $("#monthlyFcstSummaryBody").addEventListener("click", handleMonthlyFcstSummaryClick);
  $("#monthlyFcstActionForm").addEventListener("submit", submitMonthlyFcstAction);
  $("#monthlyFcstSettingsBtn").addEventListener("click", openMonthlyFcstSettings);
  $("#monthlyFcstSettingsForm").addEventListener("submit", saveMonthlyFcstSettings);
  $("#monthlyFcstHistoryImportOpenBtn").addEventListener("click", openMonthlyFcstHistoryImport);
  $("#monthlyFcstHistoryImportForm").addEventListener("submit", importMonthlyFcstHistory);
  $("#monthlyFcstHistoryImportForm").elements.round_key.addEventListener("change", syncMonthlyFcstHistoryCutoff);
  $("#monthlyFcstHistoryTemplateBtn").addEventListener("click", () => { window.location.href = "/api/monthly-sales-fcst/template"; });
  $("#monthlyFcstSubmitBtn").addEventListener("click", submitMonthlyFcstInitial);
  $("#monthlyFcstMonthToggleBtn").addEventListener("click", toggleMonthlyFcstMonth);
  $("#monthlyFcstTemplateBtn").addEventListener("click", () => { window.location.href = "/api/monthly-sales-fcst/template"; });
  $("#monthlyFcstExportBtn").addEventListener("click", exportMonthlyFcst);
  $("#monthlyFcstImportBtn").addEventListener("click", () => { $("#monthlyFcstImportForm").reset(); $("#monthlyFcstImportErrors").innerHTML = ""; $("#monthlyFcstImportError").textContent = ""; $("#monthlyFcstImportDialog").showModal(); });
  $("#monthlyFcstImportForm").addEventListener("submit", importMonthlyFcst);
  $("#monthlyFcstSheetInitBtn").addEventListener("click", initializeMonthlyFcstSheet);
  $("#monthlyFcstSheetStatus").addEventListener("click", handleMonthlyFcstSheetAction);
}

function resetMonthlyFcstFilterDialog() {
  ["monthlyFcstCompareDate", "monthlyFcstBusiness", "monthlyFcstOwner", "monthlyFcstStatus", "monthlyFcstCountry", "monthlyFcstCustomer", "monthlyFcstTiming", "monthlyFcstOriginalMonth", "monthlyFcstSplit", "monthlyFcstCarryover", "monthlyFcstRisk", "monthlyFcstSearch"].forEach(id => { const node = $("#" + id); if (node) node.value = ""; });
  $("#monthlyFcstCustomerHistory").value = "";
}

function monthlyFcstGlobalFilterIds() {
  return ["monthlyFcstCompareDate", "monthlyFcstBusiness", "monthlyFcstOwner", "monthlyFcstStatus", "monthlyFcstCountry", "monthlyFcstCustomer", "monthlyFcstTiming", "monthlyFcstCustomerHistory", "monthlyFcstOriginalMonth", "monthlyFcstSplit", "monthlyFcstCarryover", "monthlyFcstRisk", "monthlyFcstSearch"];
}

function openMonthlyFcstGlobalFilter() {
  monthlyFcstGlobalFilterSnapshot = Object.fromEntries(monthlyFcstGlobalFilterIds().map(id => [id, $("#" + id).value]));
  monthlyFcstGlobalFilterCommitted = false;
  $("#monthlyFcstGlobalFilterDialog").showModal();
}

function cancelMonthlyFcstGlobalFilter() {
  if (monthlyFcstGlobalFilterSnapshot) {
    Object.entries(monthlyFcstGlobalFilterSnapshot).forEach(([id, value]) => { $("#" + id).value = value; });
  }
  $("#monthlyFcstGlobalFilterDialog").close();
}

function applyMonthlyFcstGlobalFilter(event) {
  event.preventDefault();
  monthlyFcstGlobalFilterCommitted = true;
  monthlyFcstGlobalFilterSnapshot = null;
  $("#monthlyFcstGlobalFilterDialog").close();
  loadMonthlySalesFcst();
}

function updateMonthlyFcstGlobalFilterState() {
  const count = monthlyFcstGlobalFilterIds().filter(id => {
    return Boolean($("#" + id)?.value?.trim());
  }).length;
  const stateNode = $("#monthlyFcstGlobalFilterState");
  stateNode.textContent = count ? `${count}개 적용` : "선택";
  $("#monthlyFcstGlobalFilterBtn").classList.toggle("active", Boolean(count));
}

function selectMonthlyFcstRound(event) {
  const button = event.target.closest("[data-monthly-round-date]");
  const cutoffDate = button?.dataset.monthlyRoundDate;
  if (!cutoffDate) return;
  $("#monthlyFcstTargetMonth").value = state.monthlySalesFcst?.month || monthlyFcstSelectedMonth();
  state.monthlySalesFcstTab = "custom";
  state.monthlySalesFcstAsOfRound = button.dataset.monthlyRoundKey || "";
  $("#monthlyFcstDate").value = cutoffDate;
  syncMonthlyFcstQuickTabs();
  loadMonthlySalesFcst();
}

function returnMonthlyFcstCurrentView() {
  state.monthlySalesFcstTab = "current";
  state.monthlySalesFcstAsOfRound = "";
  $("#monthlyFcstTargetMonth").value = monthlyFcstCurrentMonth();
  $("#monthlyFcstDate").value = monthlyFcstCurrentDate();
  syncMonthlyFcstQuickTabs();
  loadMonthlySalesFcst();
}

function switchMonthlyFcstTab(tab) {
  state.monthlySalesFcstTab = tab;
  state.monthlySalesFcstAsOfRound = "";
  const current = monthlyFcstCurrentMonth();
  $("#monthlyFcstTargetMonth").value = tab === "next" ? monthlyFcstShiftMonth(current, 1) : current;
  $("#monthlyFcstDate").value = monthlyFcstCurrentDate();
  syncMonthlyFcstQuickTabs();
  loadMonthlySalesFcst();
}

function changeMonthlyFcstTargetMonth() {
  state.monthlySalesFcstAsOfRound = "";
  syncMonthlyFcstQuickTabs();
  loadMonthlySalesFcst();
}

function changeMonthlyFcstAsOfDate() {
  const today = monthlyFcstCurrentDate();
  if (!$("#monthlyFcstDate").value || $("#monthlyFcstDate").value > today) {
    $("#monthlyFcstDate").value = today;
    toast("조회 기준일은 오늘 이후로 선택할 수 없습니다.", "error");
  }
  state.monthlySalesFcstAsOfRound = "";
  syncMonthlyFcstQuickTabs();
  loadMonthlySalesFcst();
}

function runMonthlyFcstRowAction(button) {
  const sale = monthlyFcstFindSale(button.dataset.id);
  if (!sale) return;
  const drawer = $("#monthlyFcstDetailDrawer");
  if (drawer.open) drawer.close();
  const action = button.dataset.monthlyRowAction;
  if (action === "edit") openMonthlyFcstSaleDialog(sale);
  if (action === "history") openMonthlyFcstHistory(sale);
  if (["replan", "split", "carryover", "cancel", "restore", "split-cancel", "carryover-cancel"].includes(action)) openMonthlyFcstAction(sale, action);
}

function handleMonthlyFcstGroupClick(event) {
  const filter = event.target.closest("[data-monthly-open-section-filter]");
  if (filter) {
    openMonthlyFcstSectionFilter(filter.dataset.monthlyOpenSectionFilter);
    return;
  }
  const toggle = event.target.closest("[data-monthly-toggle-group]");
  if (toggle) {
    const status = toggle.dataset.monthlyToggleGroup;
    state.monthlySalesFcstExpanded.has(status) ? state.monthlySalesFcstExpanded.delete(status) : state.monthlySalesFcstExpanded.add(status);
    renderMonthlyFcstGroups(state.monthlySalesFcst.rows || []);
    return;
  }
  const button = event.target.closest("[data-monthly-row-action]");
  if (button) return runMonthlyFcstRowAction(button);
  const row = event.target.closest("[data-monthly-row-id]");
  if (row) openMonthlyFcstDetailDrawer(monthlyFcstFindSale(row.dataset.monthlyRowId));
}

function handleMonthlyFcstGroupKeydown(event) {
  if (!['Enter', ' '].includes(event.key) || event.target.closest("button, input, select, a")) return;
  const row = event.target.closest("[data-monthly-row-id]");
  if (!row) return;
  event.preventDefault();
  openMonthlyFcstDetailDrawer(monthlyFcstFindSale(row.dataset.monthlyRowId));
}

function handleMonthlyFcstDetailAction(event) {
  const button = event.target.closest("[data-monthly-row-action]");
  if (button) runMonthlyFcstRowAction(button);
}

function handleMonthlyFcstRiskClick(event) {
  const button = event.target.closest("[data-monthly-focus-row]");
  if (!button) return;
  const row = document.getElementById(`monthly-fcst-row-${button.dataset.monthlyFocusRow}`);
  if (row) { row.scrollIntoView({ behavior: "smooth", block: "center" }); row.classList.add("focus-flash"); setTimeout(() => row.classList.remove("focus-flash"), 1800); }
}

function handleMonthlyFcstSummaryClick(event) {
  const button = event.target.closest("[data-monthly-summary-unit]");
  if (!button) return;
  $("#monthlyFcstBusiness").value = button.dataset.monthlySummaryUnit === "total" ? "" : button.dataset.monthlySummaryUnit;
  $("#monthlyFcstStatus").value = button.dataset.monthlySummaryStatus || "";
  if (button.dataset.monthlySummaryTiming !== undefined) $("#monthlyFcstTiming").value = button.dataset.monthlySummaryTiming || "";
  if (button.dataset.monthlySummaryCarryover !== undefined) $("#monthlyFcstCarryover").value = button.dataset.monthlySummaryCarryover || "";
  loadMonthlySalesFcst();
  $("#monthlyFcstGroups").scrollIntoView({ behavior: "smooth", block: "start" });
}

function setMonthlyFcstFormValue(form, name, value) {
  if (form.elements[name]) form.elements[name].value = value ?? "";
}

function monthlyFcstCustomerSelectOptions(selectedId, legacyName = "", legacyCountry = "") {
  const customers = state.customerOptions || [];
  const options = customers.map(customer => {
    const country = customer.headquarters_country || "국가 미입력";
    return `<option value="${escapeHtml(customer.id)}" ${String(customer.id) === String(selectedId || "") ? "selected" : ""}>${escapeHtml(customer.display_name)} · ${escapeHtml(country)} · ${escapeHtml(customer.customer_id)}</option>`;
  }).join("");
  const legacy = !selectedId && legacyName ? `<option value="" selected>연결 필요 · ${escapeHtml(legacyName)} · ${escapeHtml(legacyCountry || "국가 미입력")}</option>` : '<option value="">거래처 마스터 선택</option>';
  return legacy + options;
}

async function syncMonthlyFcstSelectedCustomer() {
  const form = $("#monthlyFcstSaleForm");
  const selected = (state.customerOptions || []).find(customer => String(customer.id) === String(form.elements.customer_master_id.value || ""));
  form.elements.country.readOnly = Boolean(selected);
  if (!selected) { form.elements.interim_product_code.innerHTML='<option value="">Customer 취급 Item 선택</option>'; renderMonthlyFcstCommercialContext(); return; }
  form.elements.customer_name.value = selected.display_name;
  form.elements.country.value = selected.headquarters_country || "";
  if (selected.default_currency) form.elements.transaction_currency.value = selected.default_currency;
  renderMonthlyFcstConversionPreview();
  try {
    const [taxonomy,bundle]=await Promise.all([
      state.commercialContextTaxonomy?Promise.resolve(state.commercialContextTaxonomy):api('/api/commercial-context/taxonomy'),
      api(`/api/customer-master/${selected.id}/commercial-context`),
    ]);
    state.commercialContextTaxonomy=taxonomy;
    const current=form.elements.interim_product_code.value;
    form.dataset.contractPolicy=bundle.commercial_context.contract_policy||'';
    form.elements.interim_product_code.innerHTML='<option value="">Customer 취급 Item 선택</option>'+(bundle.commercial_context.items||[]).map(item=>`<option value="${escapeHtml(item.interim_product_code)}">${escapeHtml(item.label)} · ${escapeHtml(monthlyFcstBusinessLabels[item.business_unit]||item.business_unit)}</option>`).join('');
    if([...form.elements.interim_product_code.options].some(option=>option.value===current))form.elements.interim_product_code.value=current;
    window.SearchablePicker?.refresh(form.elements.interim_product_code);
    await refreshMonthlyFcstPromotions();
    await renderMonthlyFcstCommercialContext();
  } catch(error){$("#monthlyFcstCommercialContext").innerHTML=`<strong>Commercial Context 확인 필요</strong><span>${escapeHtml(error.message)}</span>`;}
}

function monthlyFcstContextDate(){const month=$("#monthlyFcstSaleForm").elements.target_month.value||monthlyFcstSelectedMonth();return `${month}-01`;}

async function refreshMonthlyFcstPromotions(){
  const form=$("#monthlyFcstSaleForm"),customer=form.elements.customer_master_id.value,item=form.elements.interim_product_code.value;
  const selected=form.elements.promotion_id.value;
  if(!customer||!item){form.elements.promotion_id.innerHTML='<option value="">적용 가능한 Promotion 선택</option>';window.SearchablePicker?.refresh(form.elements.promotion_id);return;}
  const result=await api(`/api/commercial-context/promotions?customer_id=${encodeURIComponent(customer)}&interim_product_code=${encodeURIComponent(item)}&order_date=${encodeURIComponent(monthlyFcstContextDate())}`);
  form.elements.promotion_id.innerHTML='<option value="">적용 가능한 Promotion 선택</option>'+(result.items||[]).map(row=>`<option value="${escapeHtml(row.id)}">${escapeHtml(row.title)} · ${escapeHtml(row.start_date)}~${escapeHtml(row.end_date)}</option>`).join('');
  if((result.items||[]).some(row=>row.id===selected))form.elements.promotion_id.value=selected;
  window.SearchablePicker?.refresh(form.elements.promotion_id);
}

function monthlyFcstContextMarkup(context){
  if(!context)return '<strong>Commercial Context</strong><span>거래처와 Item을 선택하세요.</span>';
  const docs=(context.required_documents||[]).map(row=>row.label).join(' · ')||'없음';
  const holidays=[...(context.country_holidays||[]).map(row=>`${row.holiday_date.slice(5)} ${row.holiday_name}`),...(context.customer_closures||[]).map(row=>`${row.start_date.slice(5)}~${row.end_date.slice(5)} ${row.title}`)].join(' · ')||'없음';
  return `<div><strong>${escapeHtml(context.item?.label||'Item')} · ${escapeHtml(context.pricing_source==='promotion'?'Promotion':context.base_source==='contract'?'Contract':'Customer Default')}</strong><span>가격 ${escapeHtml(context.currency||'')} ${formatNumber(context.unit_price||0,2)} · FOC ${formatNumber(context.foc_markup_pct||0,2)}% (${escapeHtml(context.foc_display||'')}) · MOQ ${formatNumber(context.moq_quantity||0,2)} ${escapeHtml(context.moq_uom||'')}</span></div><div><b>Payment / Incoterms</b><span>${escapeHtml(context.payment_terms?.payment_method_code||context.payment_terms?.payment_method||'미지정')} · ${escapeHtml(context.incoterms||'미지정')}</span></div><div><b>Required Docs</b><span>${escapeHtml(docs)}</span></div><div><b>현지 일정</b><span>${escapeHtml(holidays)}</span></div>${context.logistics_warning?`<div class="warning"><b>물류·통관</b><span>${escapeHtml(context.logistics_warning)}</span></div>`:''}`;
}

async function renderMonthlyFcstCommercialContext(){
  const form=$("#monthlyFcstSaleForm"),node=$("#monthlyFcstCommercialContext"),customer=form.elements.customer_master_id.value,item=form.elements.interim_product_code.value;
  const usePromotion=form.elements.pricing_selection.value==='promotion';
  document.querySelector('.monthly-fcst-promotion-field').classList.toggle('hidden',!usePromotion);
  if(!customer||!item){node.innerHTML=monthlyFcstContextMarkup(null);form.dataset.commercialResolved='';return;}
  const promotion=usePromotion?form.elements.promotion_id.value:'';
  if(usePromotion&&!promotion){node.innerHTML='<strong>Promotion 선택 필요</strong><span>적용 가능한 Promotion을 검색해 선택하세요.</span>';form.dataset.commercialResolved='';return;}
  try{const result=await api('/api/commercial-context/resolve',{method:'POST',body:{customer_id:customer,interim_product_code:item,order_date:monthlyFcstContextDate(),promotion_id:promotion||null}});form.dataset.commercialResolved='1';node.innerHTML=monthlyFcstContextMarkup(result.context);}
  catch(error){form.dataset.commercialResolved='';node.innerHTML=`<strong>저장 차단 · Commercial Context 확인 필요</strong><span>${escapeHtml(error.message)}</span>`;}
}

function syncMonthlyFcstSelectedOwner() {
  const form = $("#monthlyFcstSaleForm");
  const option = form.elements.owner_user_id.selectedOptions?.[0];
  if (option?.dataset.ownerName) form.elements.owner_name.value = option.dataset.ownerName;
  $("#monthlyFcstQuickCustomerOwner").textContent = form.elements.owner_name.value || "담당자 선택 필요";
}

function monthlyFcstCustomerLinkStatusLabel(status) {
  return {
    auto_ready: "자동연결 가능", review: "후보 확인", unmatched: "마스터 없음",
    linked: "연결 완료", mixed: "연결 불일치", excluded: "연결 제외",
  }[status] || status;
}

function renderMonthlyFcstCustomerLinkSummary(summary = {}) {
  const items = [
    ["전체", summary.total || 0], ["연결 완료", summary.linked || 0],
    ["자동연결 가능", summary.auto_ready || 0], ["후보 확인", summary.review || 0],
    ["마스터 없음", summary.unmatched || 0], ["연결 제외", summary.excluded || 0],
  ];
  $("#monthlyFcstCustomerLinkSummary").innerHTML = items.map(([label, value]) =>
    `<span><small>${escapeHtml(label)}</small><strong>${formatNumber(value)}</strong></span>`
  ).join("");
}

function renderMonthlyFcstCustomerLinks() {
  const filter = $("#monthlyFcstCustomerLinkFilter").value;
  const groups = monthlyFcstCustomerLinkGroups.filter(group => {
    if (filter === "all") return true;
    if (filter === "needs_action") return ["auto_ready", "review", "unmatched", "mixed"].includes(group.link_status);
    return group.link_status === filter;
  });
  $("#monthlyFcstCustomerLinkList").innerHTML = groups.length ? groups.map(group => {
    const candidates = group.review_candidates || [];
    const suggested = candidates.map(candidate =>
      `<button class="monthly-fcst-candidate" type="button" data-link-group="${escapeHtml(group.group_key)}" data-customer-id="${escapeHtml(candidate.customer_master_id)}"><strong>${escapeHtml(candidate.display_name)}</strong><small>${escapeHtml(candidate.headquarters_country || candidate.erp_country_name || "국가 미입력")} · ${escapeHtml(candidate.customer_id)}</small></button>`
    ).join("");
    const resolved = ["linked", "excluded"].includes(group.link_status);
    return `<article class="monthly-fcst-customer-link-card ${escapeHtml(group.link_status)}">
      <div class="monthly-fcst-customer-link-head"><div><span class="monthly-fcst-link-status">${escapeHtml(monthlyFcstCustomerLinkStatusLabel(group.link_status))}</span><h3>${escapeHtml(group.customer_name)}</h3><p>${escapeHtml(group.country || "국가 미입력")} · FCST ${formatNumber(group.sales_count)}건 · ${escapeHtml((group.months || []).join(", "))}</p></div><strong>$${formatNumber(group.amount_usd || 0, 2)}</strong></div>
      ${suggested ? `<div class="monthly-fcst-candidate-list"><span>연결 후보</span>${suggested}</div>` : ""}
      ${resolved ? "" : `<div class="monthly-fcst-customer-link-controls"><label>직접 선택<input data-link-master-input="${escapeHtml(group.group_key)}" list="monthlyFcstCustomerMasterOptions" placeholder="고객 ID 또는 거래처명"></label><button class="btn outline" type="button" data-link-selected="${escapeHtml(group.group_key)}">선택 거래처 연결</button><button class="btn outline" type="button" data-link-temp="${escapeHtml(group.group_key)}">TEMP 거래처 생성</button><button class="btn ghost" type="button" data-link-exclude="${escapeHtml(group.group_key)}">연결 제외</button></div>`}
    </article>`;
  }).join("") : '<div class="empty-state">해당 상태의 기존 FCST 거래처가 없습니다.</div>';
}

async function refreshMonthlyFcstCustomerLinks() {
  const [links, options] = await Promise.all([
    api("/api/monthly-sales-fcst/customer-links"),
    api("/api/customer-master/options").catch(() => ({ customers: state.customerOptions || [] })),
  ]);
  monthlyFcstCustomerLinkGroups = links.groups || [];
  state.customerOptions = options.customers || [];
  $("#monthlyFcstCustomerMasterOptions").innerHTML = state.customerOptions.map(customer =>
    `<option value="${escapeHtml(customer.customer_id)}">${escapeHtml(customer.display_name)} · ${escapeHtml(customer.headquarters_country || "국가 미입력")}</option>`
  ).join("");
  renderMonthlyFcstCustomerLinkSummary(links.summary);
  renderMonthlyFcstCustomerLinks();
}

async function openMonthlyFcstCustomerLinks() {
  $("#monthlyFcstCustomerLinkError").textContent = "";
  $("#monthlyFcstCustomerLinkList").innerHTML = '<div class="empty-state">기존 FCST 거래처를 확인하는 중입니다.</div>';
  $("#monthlyFcstCustomerLinksDialog").showModal();
  try { await refreshMonthlyFcstCustomerLinks(); }
  catch (error) { $("#monthlyFcstCustomerLinkError").textContent = error.message; }
}

async function autoMatchMonthlyFcstCustomers() {
  const button = $("#monthlyFcstCustomerAutoMatchBtn");
  button.disabled = true; button.textContent = "연결 중…"; $("#monthlyFcstCustomerLinkError").textContent = "";
  try {
    const result = await api("/api/monthly-sales-fcst/customer-links/auto-match", { method: "POST", body: {} });
    await Promise.all([refreshMonthlyFcstCustomerLinks(), loadMonthlySalesFcst()]);
    toast(result.message);
  } catch (error) { $("#monthlyFcstCustomerLinkError").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "명확한 거래처 자동 연결"; }
}

async function resolveMonthlyFcstCustomer(groupKey, action, customerMasterId = null) {
  $("#monthlyFcstCustomerLinkError").textContent = "";
  const result = await api("/api/monthly-sales-fcst/customer-links/resolve", {
    method: "POST", body: { group_key: groupKey, action, customer_master_id: customerMasterId },
  });
  await Promise.all([refreshMonthlyFcstCustomerLinks(), loadMonthlySalesFcst()]);
  toast(result.message);
}

async function handleMonthlyFcstCustomerLinkAction(event) {
  const candidate = event.target.closest("[data-customer-id]");
  const selected = event.target.closest("[data-link-selected]");
  const temp = event.target.closest("[data-link-temp]");
  const excluded = event.target.closest("[data-link-exclude]");
  if (!candidate && !selected && !temp && !excluded) return;
  const button = candidate || selected || temp || excluded;
  button.disabled = true;
  try {
    if (candidate) await resolveMonthlyFcstCustomer(candidate.dataset.linkGroup, "link", candidate.dataset.customerId);
    else if (selected) {
      const input = document.querySelector(`[data-link-master-input="${selected.dataset.linkSelected}"]`);
      const typed = String(input?.value || "").trim();
      const master = (state.customerOptions || []).find(item => item.customer_id === typed || item.id === typed);
      if (!master) throw new Error("목록에서 연결할 거래처를 선택하세요.");
      await resolveMonthlyFcstCustomer(selected.dataset.linkSelected, "link", master.id);
    } else if (temp) {
      if (!window.confirm("이 FCST 거래처를 거래처 마스터에 TEMP 거래처로 생성할까요?")) return;
      await resolveMonthlyFcstCustomer(temp.dataset.linkTemp, "create_temp");
    } else {
      if (!window.confirm("이 FCST 거래처를 마스터 연결 대상에서 제외할까요? 매출 자료는 유지됩니다.")) return;
      await resolveMonthlyFcstCustomer(excluded.dataset.linkExclude, "exclude");
    }
  } catch (error) { $("#monthlyFcstCustomerLinkError").textContent = error.message; }
  finally { button.disabled = false; }
}

function toggleMonthlyFcstQuickCustomer(show) {
  const form = $("#monthlyFcstSaleForm");
  const panel = $("#monthlyFcstQuickCustomerPanel");
  panel.classList.toggle("hidden", !show);
  if (show) {
    form.elements.quick_customer_name.value = "";
    form.elements.quick_customer_country.value = "";
    syncMonthlyFcstSelectedOwner();
    form.elements.quick_customer_name.focus();
  }
}

async function saveMonthlyFcstQuickCustomer() {
  const form = $("#monthlyFcstSaleForm");
  const button = $("#monthlyFcstQuickCustomerSaveBtn");
  const displayName = form.elements.quick_customer_name.value.trim();
  const country = form.elements.quick_customer_country.value.trim();
  const ownerUserId = form.elements.owner_user_id.value;
  if (!displayName || !country || !ownerUserId) {
    $("#monthlyFcstSaleError").textContent = "빠른등록에는 거래처명·국가·담당자가 필요합니다.";
    return;
  }
  button.disabled = true; button.textContent = "등록 중…"; $("#monthlyFcstSaleError").textContent = "";
  try {
    const result = await api("/api/customer-master", {
      method: "POST",
      body: {
        display_name: displayName,
        headquarters_country: country,
        primary_owner_id: Number(ownerUserId),
        business_units: [form.elements.business_unit.value],
        relationship_type: "dealer",
        customer_role: "Distributor",
        default_currency: form.elements.transaction_currency.value || "USD",
      },
    });
    const options = await api("/api/customer-master/options");
    state.customerOptions = options.customers || [];
    form.elements.customer_master_id.innerHTML = monthlyFcstCustomerSelectOptions(result.customer.id);
    form.elements.customer_master_id.value = result.customer.id;
    form.elements.customer_history.value = "new";
    syncMonthlyFcstSelectedCustomer();
    toggleMonthlyFcstQuickCustomer(false);
    toast("신규 거래처를 등록하고 이 매출에 선택했습니다.");
  } catch (error) {
    $("#monthlyFcstSaleError").textContent = error.message;
  } finally {
    button.disabled = false; button.textContent = "빠른등록 후 선택";
  }
}

function openMonthlyFcstSaleDialog(sale = null) {
  const form = $("#monthlyFcstSaleForm");
  form.reset();
  toggleMonthlyFcstQuickCustomer(false);
  const activeOwners = state.monthlySalesFcst?.owner_options || [];
  const selectedOwner = sale?.owner_name || (monthlyFcstOwners.includes(state.me?.display_name) ? state.me.display_name : "");
  const selectedOwnerId = sale?.owner_user_id || activeOwners.find(owner => owner.display_name === selectedOwner)?.id || "";
  let ownerMarkup = '<option value="">담당자 선택</option>' + activeOwners.map(owner =>
    `<option value="${escapeHtml(owner.id)}" data-owner-name="${escapeHtml(owner.display_name)}">${escapeHtml(owner.display_name)}</option>`
  ).join("");
  if (sale?.owner_user_id && !activeOwners.some(owner => String(owner.id) === String(sale.owner_user_id))) {
    ownerMarkup += `<option value="${escapeHtml(sale.owner_user_id)}" data-owner-name="${escapeHtml(sale.owner_name)}">${escapeHtml(sale.owner_name)} · 과거 담당자</option>`;
  }
  form.elements.owner_user_id.innerHTML = ownerMarkup;
  $("#monthlyFcstSaleError").textContent = "";
  $("#monthlyFcstSaleDialogTitle").textContent = sale ? `${sale.sales_no} 수정` : "월별 매출 등록";
  const month = monthlyFcstSelectedMonth();
  form.elements.customer_master_id.innerHTML = monthlyFcstCustomerSelectOptions(sale?.customer_master_id, sale?.original_customer_name || sale?.customer_name, sale?.country);
  ["id", "version", "customer_name", "customer_master_id", "country", "owner_name", "owner_user_id", "business_unit", "customer_history", "original_month", "target_month", "timing_type", "sales_status", "confirmation_basis", "confirmation_note", "carryover_decision", "carryover_decided_at", "carryover_target_month", "carryover_decision_reason", "transaction_currency", "transaction_amount", "preliminary_actual_currency", "preliminary_actual_amount", "preliminary_reference_no", "preliminary_note", "notes", "interim_product_code", "source_promotion_id"].forEach(name => setMonthlyFcstFormValue(form, name === "source_promotion_id" ? "promotion_id" : name, sale?.[name]));
  setMonthlyFcstFormValue(form,"pricing_selection",sale?.source_promotion_id?"promotion":"base");
  setMonthlyFcstFormValue(form, "owner_user_id", selectedOwnerId);
  setMonthlyFcstFormValue(form, "owner_name", selectedOwner);
  setMonthlyFcstFormValue(form, "effective_at", monthlyFcstCurrentDate());
  if (!sale) {
    setMonthlyFcstFormValue(form, "original_month", month);
    setMonthlyFcstFormValue(form, "target_month", month);
    setMonthlyFcstFormValue(form, "timing_type", "current_new");
    setMonthlyFcstFormValue(form, "customer_history", "new");
    setMonthlyFcstFormValue(form, "transaction_currency", "USD");
    setMonthlyFcstFormValue(form, "sales_status", "pipeline");
    setMonthlyFcstFormValue(form, "carryover_decision", "no");
    setMonthlyFcstFormValue(form, "owner_user_id", selectedOwnerId);
    setMonthlyFcstFormValue(form, "owner_name", selectedOwner);
  } else {
    setMonthlyFcstFormValue(form, "transaction_currency", sale.transaction_currency || "USD");
    setMonthlyFcstFormValue(form, "transaction_amount", sale.transaction_amount || sale.amount_usd);
    setMonthlyFcstFormValue(form, "customer_history", sale.customer_history || "existing");
  }
  Object.entries(sale?.milestones || {}).forEach(([name, value]) => setMonthlyFcstFormValue(form, name, value));
  form.elements.target_month.readOnly = Boolean(sale);
  form.elements.transaction_currency.disabled = Boolean(sale);
  form.elements.country.readOnly = Boolean(form.elements.customer_master_id.value);
  form.dataset.legacyConfirmedWithoutBasis = sale?.sales_status === "confirmed" && !sale?.confirmation_basis ? "1" : "";
  form.dataset.planRateSnapshot = sale?.plan_rate ?? "";
  form.dataset.planUsdRateSnapshot = sale?.plan_usd_rate ?? "";
  syncMonthlyFcstSelectedOwner();
  renderMonthlyFcstCarryoverFields();
  renderMonthlyFcstConfirmationFields();
  renderMonthlyFcstConversionPreview();
  $("#monthlyFcstSaleDialog").showModal();
  form.querySelectorAll('select').forEach(select=>select.dataset.searchable='');window.SearchablePicker?.enhanceAll(form);[form.elements.customer_master_id,form.elements.owner_user_id,form.elements.interim_product_code,form.elements.promotion_id].forEach(field=>window.SearchablePicker?.refresh(field));
  document.querySelector('.monthly-fcst-promotion-detach').classList.toggle('hidden',!sale?.source_promotion_id);
  if(sale?.commercial_context&&Object.keys(sale.commercial_context).length){form.dataset.commercialResolved='1';$("#monthlyFcstCommercialContext").innerHTML=monthlyFcstContextMarkup(sale.commercial_context);}
  syncMonthlyFcstSelectedCustomer().then(()=>{if(sale?.interim_product_code){form.elements.interim_product_code.value=sale.interim_product_code;window.SearchablePicker?.refresh(form.elements.interim_product_code);refreshMonthlyFcstPromotions().then(()=>{form.elements.promotion_id.value=sale.source_promotion_id||'';window.SearchablePicker?.refresh(form.elements.promotion_id);if(!sale.commercial_context)renderMonthlyFcstCommercialContext();});}});
}

function renderMonthlyFcstCarryoverFields() {
  const form = $("#monthlyFcstSaleForm");
  const isCarryover = form.elements.carryover_decision.value === "yes";
  $$(".monthly-fcst-carryover-field", form).forEach(node => node.classList.toggle("hidden", !isCarryover));
  form.elements.carryover_decided_at.required = isCarryover;
  form.elements.carryover_target_month.required = isCarryover;
  if (isCarryover) {
    if (!form.elements.carryover_decided_at.value) form.elements.carryover_decided_at.value = localDate(new Date());
    if (!form.elements.carryover_target_month.value) {
      const sourceMonth = form.elements.target_month.value || monthlyFcstSelectedMonth();
      form.elements.carryover_target_month.value = monthlyFcstShiftMonth(sourceMonth, 1);
    }
  } else {
    form.elements.carryover_decided_at.value = "";
    form.elements.carryover_target_month.value = "";
    form.elements.carryover_decision_reason.value = "";
  }
}

function renderMonthlyFcstConfirmationFields() {
  const form = $("#monthlyFcstSaleForm");
  const confirmed = form.elements.sales_status.value === "confirmed";
  $$(".monthly-fcst-confirmation-field", form).forEach(node => node.classList.toggle("hidden", !confirmed));
}

function renderMonthlyFcstConversionPreview() {
  const form = $("#monthlyFcstSaleForm");
  const amount = Number(form.elements.transaction_amount.value || 0);
  const currency = form.elements.transaction_currency.value || "USD";
  const rates = state.monthlySalesFcst?.plan_rates || {};
  const existing = Boolean(form.elements.id.value);
  const selectedRate = currency === "KRW" ? 1 : Number(
    existing ? form.dataset.planRateSnapshot : rates[currency] || 0
  );
  const usdRate = Number(existing ? form.dataset.planUsdRateSnapshot : rates.USD || 0);
  const unit = 1;
  const krw = currency === "KRW" ? amount : amount / unit * selectedRate;
  const usd = currency === "USD" ? amount : usdRate ? krw / usdRate : 0;
  const missing = !selectedRate || (currency !== "USD" && !usdRate);
  $("#monthlyFcstConversionPreview").innerHTML = missing
    ? `<strong>기준환율 입력 필요</strong><span>상단에서 ${escapeHtml(currency === "USD" ? "USD" : `${currency}·USD`)} 환율을 먼저 입력하세요.</span>`
    : `<strong>USD 기준 $${formatNumber(usd, 2)} · 예상 원화 ${formatMoney(krw)}</strong><span>${existing ? "이 매출의 계획환율 Snapshot" : "월 신규 기본환율"} · ${escapeHtml(currency)} ${formatNumber(selectedRate, 4)}${currency === "JPY" ? " / 1엔" : ""}</span>`;
}

function monthlyFcstSalePayload(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  ["quick_customer_name", "quick_customer_country"].forEach(name => delete data[name]);
  const milestones = {};
  ["order_agreed_at", "po_received_at", "pi_no", "pi_sent_at", "pi_confirmed_at", "payment_expected_at", "payment_actual_at", "shipment_expected_at", "shipment_actual_at", "shipping_expected_at", "shipping_actual_at", "exception_reason"].forEach(name => { milestones[name] = data[name] || null; delete data[name]; });
  data.milestones = milestones;
  data.version = Number(data.version || 0);
  data.transaction_amount = Number(data.transaction_amount || 0);
  data.commercial_context_required = true;
  if(data.pricing_selection!=="promotion")data.promotion_id=null;
  delete data.pricing_selection;
  return data;
}

async function saveMonthlyFcstSale(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = monthlyFcstSalePayload(form);
  if (!payload.id && !payload.customer_master_id) {
    $("#monthlyFcstSaleError").textContent = "신규 매출은 거래처 마스터에서 거래처를 선택하세요.";
    form.elements.customer_master_id.focus();
    return;
  }
  if (!payload.id && !payload.owner_user_id) {
    $("#monthlyFcstSaleError").textContent = "담당자를 활성 사용자 목록에서 선택하세요.";
    form.elements.owner_user_id.focus();
    return;
  }
  if(!payload.id&&!payload.interim_product_code){$("#monthlyFcstSaleError").textContent="신규 매출은 Customer 취급 Item을 선택하세요.";form.elements.interim_product_code.focus();return;}
  if(!payload.id&&form.dataset.commercialResolved!=="1"){$("#monthlyFcstSaleError").textContent="Contract / Customer Default 상업조건을 먼저 확인하세요.";form.elements.interim_product_code.focus();return;}
  const suggestedStatus = payload.milestones.payment_actual_at || payload.milestones.shipment_actual_at ? "confirmed" : payload.milestones.pi_confirmed_at ? "scheduled" : null;
  if (suggestedStatus && payload.sales_status !== suggestedStatus) {
    payload.apply_status_suggestion = window.confirm(`입력한 진행일 기준 권장 상태는 ‘${monthlyFcstStatusLabels[suggestedStatus]}’입니다. 권장 상태로 변경할까요?\n\n취소를 누르면 선택한 상태를 유지하고 불일치 경고를 표시합니다.`);
  }
  const finalStatus = payload.apply_status_suggestion && suggestedStatus ? suggestedStatus : payload.sales_status;
  const legacyBasisAllowed = payload.id && form.dataset.legacyConfirmedWithoutBasis === "1" && payload.sales_status === "confirmed";
  if (finalStatus === "confirmed" && !payload.confirmation_basis && !legacyBasisAllowed) {
    $("#monthlyFcstSaleError").textContent = "영업상 확정으로 저장하려면 확정근거를 선택하세요.";
    form.elements.confirmation_basis.focus();
    return;
  }
  if (payload.confirmation_basis === "other" && !payload.confirmation_note?.trim()) {
    $("#monthlyFcstSaleError").textContent = "기타 확정근거의 내용을 입력하세요.";
    form.elements.confirmation_note.focus();
    return;
  }
  const button = $("#monthlyFcstSaleSubmitBtn");
  button.disabled = true; button.textContent = "저장 중…"; $("#monthlyFcstSaleError").textContent = "";
  try {
    const path = payload.id ? `/api/monthly-sales-fcst/sales/${payload.id}` : "/api/monthly-sales-fcst/sales";
    const result = await api(path, { method: payload.id ? "PUT" : "POST", body: payload });
    $("#monthlyFcstSaleDialog").close();
    await loadMonthlySalesFcst();
    if (result.status_adjusted_to && result.sheet_sync?.status !== "failed") result.message += ` 진행일에 따라 ${monthlyFcstStatusLabels[result.status_adjusted_to]} 상태가 적용되었습니다.`;
    else if (result.status_suggestion && result.sheet_sync?.status !== "failed") result.message += ` 선택한 상태를 유지했으며 ${monthlyFcstStatusLabels[result.status_suggestion]} 권장 경고가 표시됩니다.`;
    monthlyFcstToastResult(result);
  } catch (error) { $("#monthlyFcstSaleError").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "저장"; }
}

function openMonthlyFcstAction(sale, action) {
  const form = $("#monthlyFcstActionForm");
  form.reset();
  form.elements.sale_id.value = sale.id;
  form.elements.sale_version.value = sale.version;
  form.elements.action_type.value = action;
  form.elements.operation_key.value = monthlyFcstOperationKey();
  $("#monthlyFcstActionError").textContent = "";
  const transactionCurrency = sale.transaction_currency || "USD";
  const transactionAmount = sale.transaction_amount || sale.amount_usd;
  $("#monthlyFcstActionMeta").innerHTML = `<strong>${escapeHtml(sale.sales_no)} · ${escapeHtml(sale.customer_name)}</strong><span>현재 거래금액 ${escapeHtml(transactionCurrency)} ${formatNumber(transactionAmount, 2)} · USD 기준 ${monthlyFcstUsd(sale.amount_usd)}</span>`;
  const monthNext = monthlyFcstShiftMonth(sale.target_month, 1);
  const today = localDate(new Date());
  let title = ""; let fields = ""; let eyebrow = "SALES ACTION";
  if (action === "replan") {
    title = "계획환율 재적용"; eyebrow = "OFFICIAL FCST REPLAN";
    fields = `<label>실제 적용일<input name="effective_at" type="date" value="${today}" required></label><label class="full">재계획 사유<input name="reason" maxlength="500" required></label><div class="security-notice full"><strong>현재 월 기본환율을 이 매출의 새 계획 Snapshot으로 적용합니다.</strong><span>일반 수정이나 월 기본환율 변경만으로는 기존 Snapshot이 바뀌지 않습니다.</span></div>`;
  } else if (action === "split") {
    title = "매출분리"; eyebrow = "SPLIT SALES ORDER";
    fields = `<label>이번 진행금액(${escapeHtml(transactionCurrency)})<input name="proceed_amount" type="number" min="0.01" max="${transactionAmount - 0.01}" step="0.01" required></label><label>분리일<input name="split_date" type="date" value="${today}" required></label><label>분리 매출 대상월<input name="target_month" type="month" value="${sale.target_month}" readonly required><small>분리 후에도 같은 월입니다. 다음달 이동은 별도 차월로 처리합니다.</small></label><label>신규 PI 번호<input name="new_pi_no" maxlength="100"></label><label>신규 PI 발행일<input name="new_pi_issued_at" type="date"></label><label>신규 PI 컨펌일<input name="new_pi_confirmed_at" type="date"></label><label class="full">분리사유<input name="reason" maxlength="500" required></label><div class="monthly-fcst-split-preview full"><span>분리금액</span><strong id="monthlyFcstSplitAmount">${escapeHtml(transactionCurrency)} ${formatNumber(transactionAmount, 2)}</strong></div>`;
  } else if (action === "carryover") {
    title = "차월 처리"; eyebrow = "MOVE SALES TO NEXT MONTH";
    const carryTarget = sale.carryover_target_month || monthNext;
    const carryDate = sale.carryover_decided_at || today;
    fields = `<input name="carryover_type" type="hidden" value="full"><label>차월 거래금액<input value="${escapeHtml(transactionCurrency)} ${formatNumber(transactionAmount, 2)}" readonly></label><label>차월 대상월<input name="target_month" type="month" value="${escapeHtml(carryTarget)}" required></label><label>차월일<input name="carryover_date" type="date" value="${escapeHtml(carryDate)}" required></label><label class="full">차월사유<input name="reason" maxlength="500" value="${escapeHtml(sale.carryover_decision_reason || "")}" required></label><div class="security-notice full"><strong>일부 차월은 매출분리를 먼저 진행해 주세요.</strong><span>분리된 건을 선택해 차월 처리하면 됩니다.</span></div>`;
  } else {
    const names = { cancel: ["매출건 취소", "CANCEL SALES RECORD"], restore: ["매출건 복원", "RESTORE CANCELLED SALE"], "split-cancel": ["매출분리 취소", "CANCEL SPLIT"], "carryover-cancel": ["차월 취소", "CANCEL CARRYOVER"] };
    [title, eyebrow] = names[action];
    const businessDate = action === "carryover-cancel" ? `<label>당월 유지일<input name="effective_at" type="date" value="${today}" required></label>` : "";
    const notice = action === "cancel"
      ? "이 매출건을 취소 처리합니다. 데이터는 삭제되지 않고 History에 보존됩니다."
      : action === "restore"
        ? "취소 전 진행상태로 돌아가며 복원 사유와 처리자가 History에 보존됩니다."
        : action === "carryover-cancel"
          ? "N월 원본은 Active로 복귀하고 N+1월 이월건은 Active에서 제외됩니다. 차월 처리와 당월 유지 이력이 모두 보존됩니다."
          : "처리 전후 내용과 담당자·처리시각이 History에 보존됩니다.";
    fields = `${businessDate}<label class="${businessDate ? "" : "full"}">${title} 사유<input name="reason" maxlength="500" required></label><div class="security-notice full"><strong>${action === "restore" ? "원래 진행상태로 복원합니다." : "원장 행을 삭제하지 않습니다."}</strong><span>${notice}</span></div>`;
  }
  $("#monthlyFcstActionTitle").textContent = title;
  $("#monthlyFcstActionEyebrow").textContent = eyebrow;
  $("#monthlyFcstActionFields").innerHTML = fields;
  const proceed = form.elements.proceed_amount;
  if (proceed) proceed.addEventListener("input", () => { $("#monthlyFcstSplitAmount").textContent = `${transactionCurrency} ${formatNumber(Math.max(0, transactionAmount - Number(proceed.value || 0)), 2)}`; });
  $("#monthlyFcstActionDialog").showModal();
}

async function submitMonthlyFcstAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const action = data.action_type; const saleId = data.sale_id;
  const saleVersion = Number(data.sale_version || 0);
  delete data.action_type; delete data.sale_id; delete data.sale_version;
  if (action === "replan") data.version = saleVersion;
  const endpoint = action === "split" ? "split" : action === "carryover" ? "carryover" : action;
  const button = $("#monthlyFcstActionSubmitBtn");
  button.disabled = true; button.textContent = "처리 중…"; $("#monthlyFcstActionError").textContent = "";
  try {
    const result = await api(`/api/monthly-sales-fcst/sales/${saleId}/${endpoint}`, { method: "POST", body: data });
    $("#monthlyFcstActionDialog").close(); await loadMonthlySalesFcst(); monthlyFcstToastResult(result);
  } catch (error) { $("#monthlyFcstActionError").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "처리"; }
}

async function openMonthlyFcstHistory(sale) {
  $("#monthlyFcstHistoryTitle").textContent = `${sale.sales_no} 변경이력`;
  $("#monthlyFcstHistoryContent").innerHTML = '<div class="empty-state">이력을 불러오는 중입니다.</div>';
  $("#monthlyFcstHistoryDialog").showModal();
  try {
    const data = await api(`/api/monthly-sales-fcst/sales/${sale.id}/history`);
    $("#monthlyFcstHistoryContent").innerHTML = data.history.length ? data.history.map(item => `<article class="history-item"><div class="history-time"><strong>업무일 ${escapeHtml(item.effective_at || "—")}</strong><small>입력 ${formatDate(item.occurred_at, true)}</small></div><div class="history-main"><strong>${escapeHtml(item.event_type)} · ${escapeHtml(item.reason || "변경")}</strong><span>${escapeHtml(item.actor_name)} · ${monthlyFcstDisplayMoney(item.snapshot.amount_usd, item.snapshot.krw_amount)} · ${escapeHtml(monthlyFcstStatusLabels[item.snapshot.sales_status])}</span></div><div class="history-meta"><small>v${formatNumber(item.snapshot.version)}</small></div></article>`).join("") : '<div class="empty-state">변경 이력이 없습니다.</div>';
  } catch (error) { $("#monthlyFcstHistoryContent").innerHTML = `<div class="form-error">${escapeHtml(error.message)}</div>`; }
}

function renderMonthlyFcstHistoryImportStatus(data) {
  const node = $("#monthlyFcstHistoryImportStatus");
  const imported = new Map((data.historical_round_imports || []).map(item => [item.round_key, item]));
  const rounds = [
    ["initial", "최초 FCST"], ["round1", "1차"], ["round2", "2차"],
    ["round3", "3차"], ["final", "최종마감"],
  ];
  node.innerHTML = rounds.map(([key, label]) => {
    const item = imported.get(key);
    const revision = Number(item?.revision_count || 0);
    return item
      ? `<span class="imported"><strong>${escapeHtml(label)}</strong><em>${escapeHtml(monthlyFcstFormatShortDate(item.cutoff_date))} · ${formatNumber(item.row_count)}건${revision ? ` · 교체 ${formatNumber(revision)}회` : ""}</em></span>`
      : `<span><strong>${escapeHtml(label)}</strong><em>미이관</em></span>`;
  }).join("");
}

function openMonthlyFcstSettings() {
  const data = state.monthlySalesFcst; if (!data) return;
  const form = $("#monthlyFcstSettingsForm"); form.reset(); $("#monthlyFcstSettingsError").textContent = "";
  form.elements.target_month.value = data.month;
  monthlyFcstCurrencies.forEach(currency => {
    form.elements[`rate_${currency}`].value = currency === "KRW" ? 1 : (data.plan_rates?.[currency] ?? "");
  });
  const cutoffKeys = {
    initial_cutoff_date: "initial", round1_cutoff_date: "round1", round2_cutoff_date: "round2",
    round3_cutoff_date: "round3", final_cutoff_date: "final",
  };
  const importedRoundKeys = new Set((data.historical_round_imports || []).map(item => item.round_key));
  Object.entries(cutoffKeys).forEach(([name, key]) => {
    form.elements[name].value = data.month_setting?.[name] || "";
    form.elements[name].readOnly = importedRoundKeys.has(key);
    form.elements[name].title = importedRoundKeys.has(key) ? "과거자료가 이관되어 기준일이 고정되었습니다." : "";
  });
  ["aesthetic", "medical", "dental"].forEach(unit => {
    form.elements[`${unit}_target_usd`].value = data.summary?.[unit]?.target_usd || 0;
    form.elements[`${unit}_target_krw`].value = data.summary?.[unit]?.target_krw || 0;
  });
  renderMonthlyFcstHistoryImportStatus(data);
  const sync = data.sheet_sync;
  $("#monthlyFcstSheetSetup").innerHTML = sync.configured ? `<strong>Google Sheets 연결됨</strong><span>${sync.spreadsheet_url ? `<a href="${escapeHtml(sync.spreadsheet_url)}" target="_blank" rel="noopener">연결된 시트 열기</a>` : "서비스 계정 연결 완료"}</span>` : `<strong>Google Sheets 연결 전 설정</strong><ol><li>빈 Google Sheets 파일을 만듭니다.</li><li>서비스 계정 이메일에 편집권한으로 공유합니다.</li><li>AI SPACE 환경변수에 <code>GOOGLE_SHEETS_SPREADSHEET_ID</code>와 <code>GOOGLE_SERVICE_ACCOUNT_JSON_B64</code>를 등록합니다.</li><li>재배포 후 ‘Google Sheets 구성·동기화’를 누르면 10개 탭이 자동 생성됩니다.</li></ol>`;
  $("#monthlyFcstSheetInitBtn").classList.toggle("hidden", !data.permissions.can_admin);
  $("#monthlyFcstSheetInitBtn").disabled = !sync.configured || !data.permissions.can_admin;
  $("#monthlyFcstSettingsDialog").showModal();
}

function syncMonthlyFcstHistoryCutoff() {
  const form = $("#monthlyFcstHistoryImportForm");
  const key = form.elements.round_key.value;
  const fieldMap = {
    initial: "initial_cutoff_date", round1: "round1_cutoff_date", round2: "round2_cutoff_date",
    round3: "round3_cutoff_date", final: "final_cutoff_date",
  };
  const existing = (state.monthlySalesFcst?.historical_round_imports || []).find(item => item.round_key === key);
  const cutoff = state.monthlySalesFcst?.month_setting?.[fieldMap[key]] || existing?.cutoff_date || "";
  form.elements.cutoff_date.value = cutoff;
  const button = $("#monthlyFcstHistoryImportSubmitBtn");
  const reasonField = $("#monthlyFcstHistoryReplacementReasonField");
  const replacementNotice = $("#monthlyFcstHistoryReplacementNotice");
  form.elements.replace_existing.value = existing ? "1" : "";
  reasonField.classList.toggle("hidden", !existing);
  form.elements.replacement_reason.required = Boolean(existing);
  button.textContent = existing ? "검증 후 교체" : "검증 후 이관";
  if (!cutoff) {
    $("#monthlyFcstHistoryImportError").textContent = "월별 설정에서 선택한 차수의 기준일을 먼저 저장하세요.";
    button.disabled = true;
  } else {
    $("#monthlyFcstHistoryImportError").textContent = "";
    button.disabled = false;
  }
  if (existing) {
    replacementNotice.innerHTML = `<strong>${escapeHtml(existing.round_label)} 기존 자료를 교체합니다.</strong><span>${escapeHtml(existing.cutoff_date)} 기준 ${formatNumber(existing.row_count)}건은 삭제되지 않고 이전 버전 이력으로 보존됩니다.</span>`;
    replacementNotice.classList.remove("hidden");
  } else {
    form.elements.replacement_reason.value = "";
    replacementNotice.innerHTML = "";
    replacementNotice.classList.add("hidden");
  }
}

function openMonthlyFcstHistoryImport() {
  const data = state.monthlySalesFcst;
  if (!data) return;
  const form = $("#monthlyFcstHistoryImportForm");
  form.reset();
  form.elements.target_month.value = data.month;
  $("#monthlyFcstHistoryImportErrors").innerHTML = "";
  $("#monthlyFcstHistoryImportError").textContent = "";
  const importedKeys = new Set((data.historical_round_imports || []).map(item => item.round_key));
  const firstAvailable = ["initial", "round1", "round2", "round3", "final"].find(key => !importedKeys.has(key));
  form.elements.round_key.value = firstAvailable || "initial";
  syncMonthlyFcstHistoryCutoff();
  $("#monthlyFcstSettingsDialog").close();
  $("#monthlyFcstHistoryImportDialog").showModal();
}

async function importMonthlyFcstHistory(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#monthlyFcstHistoryImportSubmitBtn");
  const body = new FormData(form);
  button.disabled = true;
  button.textContent = "검증 중…";
  $("#monthlyFcstHistoryImportError").textContent = "";
  $("#monthlyFcstHistoryImportErrors").innerHTML = "";
  try {
    const response = await fetch("/api/monthly-sales-fcst/history/import", {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRF-Token": state.csrf, Accept: "application/json" }, body,
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error || "과거자료 이관에 실패했습니다.");
      error.rows = result.errors;
      throw error;
    }
    $("#monthlyFcstHistoryImportDialog").close();
    await loadMonthlySalesFcst();
    monthlyFcstToastResult(result);
    openMonthlyFcstSettings();
  } catch (error) {
    $("#monthlyFcstHistoryImportError").textContent = error.message;
    $("#monthlyFcstHistoryImportErrors").innerHTML = error.rows?.length
      ? error.rows.map(item => `<div><strong>${item.row}행</strong><span>${escapeHtml(item.message)}</span></div>`).join("")
      : "";
  } finally {
    if (!$("#monthlyFcstHistoryImportDialog").open) button.disabled = false;
    else syncMonthlyFcstHistoryCutoff();
  }
}

async function saveMonthlyFcstSettings(event) {
  event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form).entries());
  $("#monthlyFcstSettingsError").textContent = "";
  const rates = Object.fromEntries(monthlyFcstCurrencies.map(currency => [currency, currency === "KRW" ? 1 : Number(data[`rate_${currency}`] || 0)]));
  const currentRates = state.monthlySalesFcst?.plan_rates || {};
  const changedExisting = monthlyFcstCurrencies.some(currency => Number(currentRates[currency] || 0) > 0 && Math.abs(Number(currentRates[currency]) - rates[currency]) > 0.0001);
  if (changedExisting && !data.rate_correction_reason?.trim()) {
    $("#monthlyFcstSettingsError").textContent = "기존 기준환율을 변경하려면 변경사유를 입력하세요.";
    form.elements.rate_correction_reason.focus();
    return;
  }
  const targets = {}; ["aesthetic", "medical", "dental"].forEach(unit => { targets[unit] = { target_usd: Number(data[`${unit}_target_usd`] || 0), target_krw: Number(data[`${unit}_target_krw`] || 0) }; });
  const roundCutoffs = { initial: data.initial_cutoff_date || null, round1: data.round1_cutoff_date || null, round2: data.round2_cutoff_date || null, round3: data.round3_cutoff_date || null, final: data.final_cutoff_date || null };
  const button = $("#monthlyFcstSettingsSubmitBtn"); button.disabled = true; button.textContent = "저장 중…";
  try { const result = await api(`/api/monthly-sales-fcst/settings/${data.target_month}`, { method: "PUT", body: { rates, rate_correction_reason: data.rate_correction_reason || "", round_cutoffs: roundCutoffs, targets } }); $("#monthlyFcstSettingsDialog").close(); await loadMonthlySalesFcst(); monthlyFcstToastResult(result); }
  catch (error) { $("#monthlyFcstSettingsError").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "저장"; }
}

async function submitMonthlyFcstInitial() {
  const month = state.monthlySalesFcst?.month; if (!month || !window.confirm(`${month} 최초 FCST를 제출할까요? 제출 후 최초 값은 변경되지 않습니다.`)) return;
  try { const result = await api(`/api/monthly-sales-fcst/forecast/${month}/submit`, { method: "POST", body: {} }); await loadMonthlySalesFcst(); monthlyFcstToastResult(result); }
  catch (error) { toast(error.message, "error"); }
}

async function toggleMonthlyFcstMonth() {
  const data = state.monthlySalesFcst; if (!data) return;
  const reopening = data.month_setting.month_status === "closed";
  const reason = window.prompt(reopening ? "재개방 사유를 입력하세요." : "월 마감 확인내용을 입력하세요.");
  if (!reason?.trim()) return;
  try { const result = await api(`/api/monthly-sales-fcst/months/${data.month}/${reopening ? "reopen" : "close"}`, { method: "POST", body: { reason } }); await loadMonthlySalesFcst(); monthlyFcstToastResult(result); }
  catch (error) { toast(error.message, "error"); }
}

function exportMonthlyFcst() {
  const query = monthlyFcstApiPath().split("?")[1];
  window.location.href = `/api/monthly-sales-fcst/export?${query}`;
}

async function importMonthlyFcst(event) {
  event.preventDefault(); const form = event.currentTarget; const button = $("#monthlyFcstImportSubmitBtn");
  const body = new FormData(form); button.disabled = true; button.textContent = "검증 중…"; $("#monthlyFcstImportError").textContent = ""; $("#monthlyFcstImportErrors").innerHTML = "";
  try {
    const response = await fetch("/api/monthly-sales-fcst/import", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": state.csrf, Accept: "application/json" }, body });
    const result = await response.json();
    if (!response.ok) { const error = new Error(result.error || "업로드에 실패했습니다."); error.rows = result.errors; throw error; }
    $("#monthlyFcstImportDialog").close(); await loadMonthlySalesFcst(); monthlyFcstToastResult(result);
  } catch (error) {
    $("#monthlyFcstImportError").textContent = error.message;
    $("#monthlyFcstImportErrors").innerHTML = error.rows?.length ? error.rows.map(item => `<div><strong>${item.row}행</strong><span>${escapeHtml(item.message)}</span></div>`).join("") : "";
  } finally { button.disabled = false; button.textContent = "검증 후 가져오기"; }
}

async function initializeMonthlyFcstSheet() {
  const button = $("#monthlyFcstSheetInitBtn"); button.disabled = true; button.textContent = "구성 중…";
  try { const result = await api("/api/monthly-sales-fcst/sheets/initialize", { method: "POST", body: {} }); await loadMonthlySalesFcst(); toast(result.message); openMonthlyFcstSettings(); }
  catch (error) { $("#monthlyFcstSettingsError").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "Google Sheets 구성·동기화"; }
}

async function handleMonthlyFcstSheetAction(event) {
  if (event.target.closest("[data-monthly-open-settings]")) return openMonthlyFcstSettings();
  if (!event.target.closest("[data-monthly-sync-sheet]")) return;
  try { const result = await api("/api/monthly-sales-fcst/sheets/sync", { method: "POST", body: {} }); await loadMonthlySalesFcst(); toast(result.sheet_sync.status === "success" ? "Google Sheets 동기화를 완료했습니다." : result.sheet_sync.message); }
  catch (error) { toast(error.message, "error"); }
}
