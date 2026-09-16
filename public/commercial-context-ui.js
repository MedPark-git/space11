(function () {
  const cc = { customer: null, bundle: null, promotions: [], providerDirectory: [], taxonomy: null, refresh: null, mode: null, item: null };
  const $ = selector => document.querySelector(selector);
  const esc = value => escapeHtml(value == null ? "" : String(value));
  const label = (group, code) => (cc.taxonomy?.[group] || []).find(row => row.code === code)?.label || code || "—";
  const itemLabel = code => label("items", code);
  const fmt = value => value == null || value === "" ? "—" : formatNumber(Number(value), 2);
  const canEdit = () => Boolean(cc.customer?.can_edit);
  const action = (name, id = "") => canEdit() ? `<button class="mini-btn" type="button" data-commercial-action="${name}" data-commercial-id="${esc(id)}">${id ? "수정" : "+ 추가"}</button>` : "";

  function options(group, selected = "", empty = "선택") {
    return `<option value="">${esc(empty)}</option>` + (cc.taxonomy?.[group] || []).map(row =>
      `<option value="${esc(row.code)}" ${String(row.code) === String(selected) ? "selected" : ""}>${esc(row.label || row.name || row.code)}</option>`
    ).join("");
  }
  function currencyOptions(selected = "USD", allowEmpty = false) {
    return (allowEmpty ? '<option value="">Base 통화 유지</option>' : "")
      + ["USD","EUR","JPY","CNH","KRW"].map(code=>`<option value="${code}" ${code===selected?"selected":""}>${code}</option>`).join("");
  }

  function chips(codes) {
    return (codes || []).map(code => `<span class="commercial-chip">${esc(itemLabel(code))}</span>`).join("") || "—";
  }

  function empty(text) { return `<div class="empty-state compact">${esc(text)}</div>`; }

  async function load(customer) {
    cc.customer = customer;
    const [taxonomy, bundle, promotions, providers] = await Promise.all([
      cc.taxonomy ? Promise.resolve(cc.taxonomy) : api("/api/commercial-context/taxonomy"),
      api(`/api/customer-master/${customer.id}/commercial-context`),
      api(`/api/commercial-context/promotions?customer_id=${encodeURIComponent(customer.id)}`),
      api("/api/commercial-context/logistics-providers"),
    ]);
    cc.taxonomy = taxonomy;
    cc.bundle = bundle.commercial_context;
    cc.promotions = promotions.items || [];
    cc.providerDirectory = providers.items || [];
    return cc.bundle;
  }

  function contractTerms(contract) {
    return `<div class="commercial-term-grid">${(contract.item_terms || []).map(term => `<div>
      <strong>${esc(term.item_label || itemLabel(term.interim_product_code))}</strong>
      <span>${esc(term.currency || "USD")} ${fmt(term.unit_price)} · ${esc(label("price_methods", term.price_method_code))}</span>
      <small>MOQ ${fmt(term.moq_quantity)} ${esc(term.moq_uom || "")} · FOC ${fmt(term.foc_markup_pct)}% (${esc(term.foc_markup_pct == null ? "—" : `10+${Number(term.foc_markup_pct) / 10}`)}) · ${esc(label("packaging_labels", term.packaging_label_code))}</small>
    </div>`).join("") || empty("Item별 가격조건이 없습니다.")}</div>`;
  }

  function contractCard(contract) {
    const territory = (contract.territory_country_codes || []).map(code => label("countries", code)).join(" · ") || "Territory 미지정";
    const badge = contract.derived_badge || {};
    const salesPlans = (contract.sales_plans || []).map(plan => `<span>${plan.interim_product_code ? esc(itemLabel(plan.interim_product_code)) : "전체"} · ${plan.target_type === "quantity" ? `${fmt(plan.target_quantity)} ${esc(plan.target_uom || "EA")}` : `${esc(plan.currency || "USD")} ${fmt(plan.target_amount)}`}</span>`).join("") || "입력 선택사항";
    const payment = contract.payment_override;
    return `<article class="contract-card">
      <header><div><span class="contract-number">${esc(contract.contract_no || "계약번호 미입력")}</span><strong>${esc(contract.start_date || "—")} ~ ${esc(contract.commercial_status_code === "extended" ? contract.extension_end_date : contract.end_date || "—")}</strong></div><div><span class="contract-badge ${esc(badge.code || "")}">${esc(badge.label || label("commercial_statuses", contract.commercial_status_code))}</span>${action("contract", contract.id)}</div></header>
      <div class="contract-summary"><span><b>적용 Item</b>${chips(contract.interim_product_codes)}</span><span><b>Territory</b>${esc(territory)}</span></div>
      <details open><summary>가격 · FOC · MOQ</summary>${contractTerms(contract)}</details>
      <details><summary>Sales Plan</summary><div class="commercial-inline-values">${salesPlans}</div><p class="commercial-placeholder">ERP 실적 연결 대기 · Target은 보존하며 가짜 달성률을 계산하지 않습니다.</p></details>
      <details><summary>Payment · Incoterms</summary><p>${payment ? `${esc(payment.payment_method_code || payment.payment_method || "조건 입력")} · ${esc(payment.incoterms_code || "Incoterms 미지정")} · ${esc(payment.currency || "USD")}` : "Contract Override 없음 · Customer Default 적용"}</p></details>
      <details><summary>기타 계약조건</summary><p>${esc(contract.notes || "등록 없음")}</p></details>
    </article>`;
  }

  function renderCommercial() {
    const b = cc.bundle || {};
    const policy = b.contract_policy ? label("contract_policies", b.contract_policy) : "Review Required / 미분류";
    const defaults = (b.default_terms || []).map(term => `<article class="commercial-list-row"><div><strong>${esc(term.item_label)}</strong><span>${esc(term.currency)} ${fmt(term.agreed_unit_price)} · MOQ ${fmt(term.moq_quantity)} ${esc(term.moq_uom || "")} · FOC ${fmt(term.foc_markup_pct)}%</span><small>${esc(term.term_start_date || "시작일 미지정")} ~ ${esc(term.term_end_date || "종료일 미지정")} · ${term.current_contract_applies ? "현재 Contract 조건 적용 중 · 대기 조건" : "Customer Default"}</small></div>${action("default-term", term.id)}</article>`).join("") || empty("등록된 기본 가격조건이 없습니다.");
    return `<div class="commercial-context-stack">
      <section class="commercial-profile-strip"><div><span>계약정책</span><strong>${esc(policy)}</strong></div><div><span>취급 Item</span><strong>${chips((b.items || []).map(row => row.interim_product_code))}</strong></div>${canEdit() ? '<button class="btn outline" data-edit-master type="button">사업분야·Item 수정</button>' : ""}</section>
      <section><div class="customer-detail-toolbar"><div><h3>Contract</h3><p>계약 하나가 가격·FOC·MOQ·Sales Plan·Payment의 적용 단위입니다.</p></div>${action("contract")}</div><div class="contract-card-list">${(b.contracts || []).map(contractCard).join("") || empty("등록된 Contract가 없습니다.")}</div></section>
      <section><div class="customer-detail-toolbar"><div><h3>기본 상업조건</h3><p>무계약 거래 허용 Customer의 Customer-level 실거래 조건입니다.</p></div>${action("default-term")}</div><div class="commercial-list">${defaults}</div></section>
      <section class="commercial-graph"><div><strong>Contract Expiry Timeline</strong><small>D-60 / D-30 / 종료 후 조치 필요를 날짜에서 파생합니다.</small></div><div class="contract-timeline">${(b.contracts || []).map(row => `<span class="${esc(row.derived_badge?.code || "")}"><b>${esc(row.contract_no || "계약")}</b>${esc(row.derived_badge?.label || "—")}</span>`).join("") || "계약 없음"}</div></section>
    </div>`;
  }

  function renderPromotion() {
    const rows = cc.promotions.map(promo => `<article class="commercial-list-row"><div><strong>${esc(promo.title)}</strong><span>${esc(promo.start_date)} ~ ${esc(promo.end_date)} · ${esc(label("promotion_statuses", promo.commercial_status_code))}</span><small>${(promo.items || []).map(row => `${itemLabel(row.interim_product_code)}${row.price_override != null ? ` ${row.currency_override || ""} ${fmt(row.price_override)}` : ""}${row.foc_markup_override_pct != null ? ` · FOC ${fmt(row.foc_markup_override_pct)}%` : ""}`).join(" / ")}</small><small>공식 Monthly FCST 연결 ${(promo.sales_lines || []).filter(row => row.monthly_sale_id).length}건</small></div>${action("promotion", promo.id)}</article>`).join("") || empty("구조화된 Promotion이 없습니다. 기존 Promotion 원문은 보존됩니다.");
    return `<section><div class="customer-detail-toolbar"><div><h3>Promotion</h3><p>기존 Promotion ID를 Header로 유지하고 지정된 필드만 기본 상업조건 위에 Override합니다.</p></div>${action("promotion")}</div><div class="commercial-list">${rows}</div></section>`;
  }

  function renderPayment() {
    const p = cc.bundle?.default_payment;
    return `<section><div class="customer-detail-toolbar"><div><h3>Customer Default Payment · Incoterms</h3><p>Contract Override가 없을 때만 사용됩니다.</p></div>${action("payment", p?.id || "")}</div>${p ? `<article class="commercial-list-row"><div><strong>${esc(p.payment_method_code || p.payment_method || "결제조건")}</strong><span>${esc(p.incoterms_code || "Incoterms 미지정")} · ${esc(p.currency || "USD")} · 후불 ${fmt(p.deferred_days)}일</span><small>${esc(p.effective_from || "시작일 미지정")} ~ ${esc(p.effective_to || "종료일 미지정")}</small></div></article>` : empty("Customer Default Payment가 없습니다.")}</section>`;
  }

  function renderLogistics() {
    const b = cc.bundle || {};
    const addresses = (b.addresses || []).map(row => `<article class="commercial-list-row"><div><strong>${esc(label("address_roles", row.address_role))} · ${esc(row.company_name || cc.customer.display_name)}</strong><span>${esc([row.address_line1,row.address_line2,row.city,row.state_province,row.postal_code,row.country_name].filter(Boolean).join(", "))}</span><small>${esc(row.phone || "")} ${esc(row.email || "")} ${row.tax_importer_id ? `· ID ${esc(row.tax_importer_id)}` : ""}</small></div>${action("address", row.id)}</article>`).join("") || empty("구조화된 Bill To / Ship To / Consignee / Notify Party가 없습니다.");
    const providers = (b.providers || []).map(row => `<article class="commercial-list-row"><div><strong>${esc(label("provider_types", row.provider_type))} · ${esc(row.company_name)}</strong><span>${esc(row.contact_person || "담당자 미지정")} · ${esc(row.phone || row.email || "연락처 미지정")}</span><small>Account ${esc(row.account_number || "—")} · ${esc(row.note || "")}</small></div>${action("provider", row.id)}</article>`).join("") || empty("Courier / Forwarder / Customs Broker가 없습니다.");
    const docs = (b.document_requirements || []).map(row => `<article class="commercial-list-row"><div><strong>${esc(row.label)}</strong><span>${row.item_scope === "all" ? "전체 Item" : chips(row.interim_product_codes)}</span><small>${esc(label("document_frequencies", row.frequency_code))} · ${esc(label("document_units", row.document_unit_code))} · 원본 ${row.original_required ? "필요" : "불필요"} · ${esc(label("legalization_types", row.legalization_code))}</small></div>${action("document", row.id)}</article>`).join("") || empty("구조화된 무역서류 요구조건이 없습니다.");
    return `<div class="commercial-context-stack"><section><div class="customer-detail-toolbar"><h3>주소·Consignee</h3>${action("address")}</div><div class="commercial-list">${addresses}</div></section><section><div class="customer-detail-toolbar"><h3>Courier · Forwarder · Broker</h3>${action("provider")}</div><div class="commercial-list">${providers}</div></section><section><div class="customer-detail-toolbar"><div><h3>무역서류 요구조건</h3><p>Document-first로 등록하고 적용 Item을 연결합니다.</p></div>${action("document")}</div><div class="commercial-list">${docs}</div></section></div>`;
  }

  function renderSchedule() {
    const b = cc.bundle || {};
    const holidays = (b.country_holidays || []).map(row => `<span><b>${esc(row.holiday_date.slice(5))}</b>${esc(row.holiday_name)}</span>`).join("") || "해당 연도의 검증된 공휴일 데이터가 없습니다.";
    const closures = (b.closures || []).map(row => `<article class="commercial-list-row"><div><strong>${esc(row.title)}</strong><span>${esc(row.start_date)} ~ ${esc(row.end_date)}</span><small>${esc(row.note || "")}</small></div>${action("closure", row.id)}</article>`).join("") || empty("거래처 자체 휴무가 없습니다.");
    return `<div class="commercial-context-stack"><section><div class="customer-detail-toolbar"><div><h3>Country Holiday</h3><p>${esc(b.holiday_provider?.source || "python-holidays")} ${esc(b.holiday_provider?.version || "")} · 국가코드 기준</p></div></div><div class="holiday-calendar">${holidays}</div></section><section><div class="customer-detail-toolbar"><h3>Customer Closure</h3>${action("closure")}</div><div class="commercial-list">${closures}</div></section></div>`;
  }

  function render(tab) {
    if (tab === "commercial") return renderCommercial();
    if (tab === "promotion") return renderPromotion();
    if (tab === "payment") return renderPayment();
    if (tab === "logistics_v2") return renderLogistics();
    if (tab === "schedule") return renderSchedule();
    return "";
  }

  function itemRows(values = [], selectable = true, promotion = false) {
    const byCode = Object.fromEntries(values.map(row => [row.interim_product_code, row]));
    const portfolio = new Set((cc.bundle?.items || []).map(row => row.interim_product_code));
    return (cc.taxonomy?.items || []).filter(item => portfolio.has(item.code) || byCode[item.code]).map(item => {
      const row = byCode[item.code] || {};
      return `<div class="commercial-item-term-row" data-item-term="${esc(item.code)}">
        ${selectable ? `<label class="commercial-item-check"><input type="checkbox" data-item-enabled ${byCode[item.code] ? "checked" : ""}> ${esc(item.label)}</label>` : `<strong>${esc(item.label)}</strong>`}
        <input data-term-price type="number" min="0" step="0.0001" value="${esc(row.unit_price ?? row.price_override ?? "")}" placeholder="가격">
        <select data-term-currency>${currencyOptions(promotion ? (row.currency_override || "") : (row.currency || "USD"), promotion)}</select>
        ${promotion ? "" : `<select data-term-method>${options("price_methods", row.price_method_code || "base_price", "가격방식")}</select>`}
        <input data-term-moq type="number" min="0" step="0.01" value="${esc(row.moq_quantity ?? row.moq_quantity_override ?? "")}" placeholder="MOQ">
        <select data-term-uom>${options("moq_uoms", row.moq_uom || row.moq_uom_override || "EA", "UOM")}</select>
        <input data-term-foc type="number" min="0" step="0.01" value="${esc(row.foc_markup_pct ?? row.foc_markup_override_pct ?? "")}" placeholder="FOC %">
        <select data-term-label>${options("packaging_labels", row.packaging_label_code || row.packaging_label_override_code || "", "포장·라벨")}</select>
        <input data-term-label-other value="${esc(row.packaging_label_other || row.packaging_label_override_other || "")}" placeholder="Other 버전">
        ${promotion ? "" : `<input data-term-notes type="hidden" value="${esc(row.notes || "")}">`}
      </div>`;
    }).join("");
  }

  function contractForm(item = {}) {
    return `<div class="form-grid three commercial-dialog-grid">
      <label>계약번호<input name="contract_no" maxlength="200" value="${esc(item.contract_no || "")}" required></label>
      <label>상태<select name="commercial_status_code" data-searchable required>${options("commercial_statuses", item.commercial_status_code || "active")}</select></label>
      <label>통화<select name="currency" data-searchable>${currencyOptions(item.currency || "USD")}</select></label>
      <label>시작일<input name="start_date" type="date" value="${esc(item.start_date || "")}" required></label>
      <label>종료일<input name="end_date" type="date" value="${esc(item.end_date || "")}" required></label>
      <label>연장 종료일<input name="extension_end_date" type="date" value="${esc(item.extension_end_date || "")}"><small>상태가 연장일 때 필수</small></label>
      <label class="full">Territory<select name="territory_country_codes" data-searchable multiple>${(cc.taxonomy?.countries || []).map(row => `<option value="${esc(row.code)}" ${(item.territory_country_codes || []).includes(row.code) ? "selected" : ""}>${esc(row.name)} · ${esc(row.label)}</option>`).join("")}</select></label>
      <section class="full commercial-form-section"><h3>적용 Item · 가격 · MOQ · FOC · 포장·라벨</h3><div class="commercial-item-term-head"><span>Item</span><span>가격</span><span>통화</span><span>가격방식</span><span>MOQ</span><span>UOM</span><span>FOC %</span><span>포장·라벨</span><span>Other</span></div>${itemRows(item.item_terms || [])}</section>
      <section class="full commercial-form-section"><h3>Sales Plan (선택)</h3><div class="form-grid three"><label>연도<input name="plan_year" type="number" min="2000" value="${esc(item.sales_plans?.[0]?.plan_year || "")}"></label><label>유형<select name="target_type" data-searchable><option value="amount" ${item.sales_plans?.[0]?.target_type !== "quantity" ? "selected" : ""}>Amount</option><option value="quantity" ${item.sales_plans?.[0]?.target_type === "quantity" ? "selected" : ""}>Quantity</option></select></label><label>Target<input name="target_value" type="number" min="0" step="0.01" value="${esc(item.sales_plans?.[0]?.target_amount ?? item.sales_plans?.[0]?.target_quantity ?? "")}"></label></div></section>
      <section class="full commercial-form-section"><h3>Payment · Incoterms Override (선택)</h3><div class="form-grid three"><label>결제수단<select name="payment_method_code" data-searchable>${options("payment_methods", item.payment_override?.payment_method_code || "", "Default 사용")}</select></label><label>기타 결제수단<input name="payment_method_other" value="${esc(item.payment_override?.payment_method_other || "")}"></label><label>Incoterms<select name="incoterms_code" data-searchable>${options("incoterms", item.payment_override?.incoterms_code || "", "Default 사용")}</select></label><label>후불일수<input name="deferred_days" type="number" min="0" value="${esc(item.payment_override?.deferred_days || 0)}"></label></div></section>
      <label class="full">기타 계약조건<textarea name="notes" rows="3">${esc(item.notes || "")}</textarea></label>
    </div>`;
  }

  function simpleForm(mode, item = {}) {
    if (mode === "default-term") return `<div class="form-grid three"><label>Item<select name="interim_product_code" data-searchable required>${options("items", item.interim_product_code)}</select></label><label>가격<input name="unit_price" type="number" min="0" step="0.0001" value="${esc(item.agreed_unit_price ?? "")}" required></label><label>통화<select name="currency" data-searchable><option>USD</option><option>EUR</option><option>JPY</option><option>CNH</option><option>KRW</option></select></label><label>가격방식<select name="price_method_code" data-searchable>${options("price_methods", item.price_method_code || "base_price")}</select></label><label>MOQ<input name="moq_quantity" type="number" min="0" step="0.01" value="${esc(item.moq_quantity ?? "")}"></label><label>UOM<select name="moq_uom" data-searchable>${options("moq_uoms", item.moq_uom || "EA")}</select></label><label>FOC 할증률 %<input name="foc_markup_pct" type="number" min="0" step="0.01" value="${esc(item.foc_markup_pct ?? "")}"></label><label>포장·라벨 버전<select name="packaging_label_code" data-searchable>${options("packaging_labels", item.packaging_label_code || "general_export")}</select></label><label>Other 버전<input name="packaging_label_other" value="${esc(item.packaging_label_other || "")}"></label><label>적용 시작일<input name="term_start_date" type="date" value="${esc(item.term_start_date || "")}"></label><label>적용 종료일<input name="term_end_date" type="date" value="${esc(item.term_end_date || "")}"></label><label>상태<select name="commercial_status_code"><option value="active">유효</option><option value="expired">만료</option></select></label><label class="full">비고<textarea name="notes">${esc(item.notes || "")}</textarea></label></div>`;
    if (mode === "payment") return `<div class="form-grid three"><label>결제수단<select name="payment_method_code" data-searchable required>${options("payment_methods", item.payment_method_code || "")}</select></label><label>기타 결제수단<input name="payment_method_other" value="${esc(item.payment_method_other || "")}"></label><label>Incoterms<select name="incoterms_code" data-searchable>${options("incoterms", item.incoterms_code)}</select></label><label>통화<select name="currency" data-searchable>${currencyOptions(item.currency || "USD")}</select></label><label>후불일수<input name="deferred_days" type="number" min="0" value="${esc(item.deferred_days || 0)}"></label><label>적용 시작일<input name="effective_from" type="date" value="${esc(item.effective_from || "")}"></label><label>적용 종료일<input name="effective_to" type="date" value="${esc(item.effective_to || "")}"></label><label class="full">비고<textarea name="notes">${esc(item.notes || "")}</textarea></label></div>`;
    if (mode === "address") return `<div class="form-grid two"><label>주소 역할<select name="address_role" data-searchable required>${options("address_roles", item.address_role)}</select></label><label>Company Name<input name="company_name" value="${esc(item.company_name || "")}"></label><label class="full">Address Line 1<input name="address_line1" value="${esc(item.address_line1 || "")}"></label><label class="full">Address Line 2<input name="address_line2" value="${esc(item.address_line2 || "")}"></label><label>City<input name="city" value="${esc(item.city || "")}"></label><label>State / Province<input name="state_province" value="${esc(item.state_province || "")}"></label><label>Postal Code<input name="postal_code" value="${esc(item.postal_code || "")}"></label><label>Country<select name="country_code" data-searchable>${options("countries", item.country_code)}</select></label><label>Phone<input name="phone" value="${esc(item.phone || "")}"></label><label>Email<input name="email" type="email" value="${esc(item.email || "")}"></label><label>Tax / VAT / Importer ID<input name="tax_importer_id" value="${esc(item.tax_importer_id || "")}"></label><label class="full">Note<textarea name="note">${esc(item.note || "")}</textarea></label></div>`;
    if (mode === "provider") return `<div class="form-grid two"><label class="full">기존 Provider 검색<select name="provider_id" data-searchable>${'<option value="">새 Provider 등록</option>' + cc.providerDirectory.map(row=>`<option value="${esc(row.id)}" ${row.id===item.provider_id?"selected":""}>${esc(label("provider_types",row.provider_type))} · ${esc(row.company_name)} · ${esc(row.country_name||"국가 미지정")}</option>`).join("")}</select></label><label>Type<select name="provider_type" data-searchable required>${options("provider_types", item.provider_type)}</select></label><label>Company Name<input name="company_name" value="${esc(item.company_name || "")}" required></label><label>Contact Person<input name="contact_person" value="${esc(item.contact_person || "")}"></label><label>Department<input name="department" value="${esc(item.department || "")}"></label><label>Phone<input name="phone" value="${esc(item.phone || "")}"></label><label>Email<input name="email" type="email" value="${esc(item.email || "")}"></label><label>Account Number<input name="account_number" value="${esc(item.account_number || "")}"></label><label>Website<input name="website" type="url" value="${esc(item.website || "")}"></label><label>Country<select name="country_code" data-searchable>${options("countries", item.country_code)}</select></label><label class="full">Note<textarea name="note">${esc(item.note || "")}</textarea></label></div>`;
    if (mode === "document") return `<div class="form-grid two"><label>Document<select name="document_code" data-searchable required>${options("document_catalog", item.document_code)}</select></label><label>Other 이름<input name="other_document_name" value="${esc(item.other_document_name || "")}"></label><label>적용범위<select name="item_scope" data-searchable><option value="all">전체 Item</option><option value="selected" ${item.item_scope === "selected" ? "selected" : ""}>선택 Item</option></select></label><label>적용 Item<select name="interim_product_codes" data-searchable multiple>${(cc.taxonomy?.items || []).filter(row=>(cc.bundle?.items||[]).some(itemRow=>itemRow.interim_product_code===row.code)||(item.interim_product_codes||[]).includes(row.code)).map(row => `<option value="${esc(row.code)}" ${(item.interim_product_codes || []).includes(row.code) ? "selected" : ""}>${esc(row.label)}</option>`).join("")}</select></label><label>Frequency<select name="frequency_code" data-searchable>${options("document_frequencies", item.frequency_code || "every_shipment")}</select></label><label>Document Unit<select name="document_unit_code" data-searchable>${options("document_units", item.document_unit_code || "shipment")}</select></label><label>Legalization<select name="legalization_code" data-searchable>${options("legalization_types", item.legalization_code || "none")}</select></label><label>Language<select name="language_code" data-searchable>${options("languages",item.language_code,"미지정")}</select></label><label><input name="required" type="checkbox" ${item.required === 0 ? "" : "checked"}> Required</label><label><input name="original_required" type="checkbox" ${item.original_required ? "checked" : ""}> Original 필요</label><label class="full">Note<textarea name="note">${esc(item.note || "")}</textarea></label></div>`;
    if (mode === "closure") return `<div class="form-grid two"><label>휴무명<input name="title" value="${esc(item.title || "")}" required></label><label>시작일<input name="start_date" type="date" value="${esc(item.start_date || "")}" required></label><label>종료일<input name="end_date" type="date" value="${esc(item.end_date || "")}" required></label><label class="full">Note<textarea name="note">${esc(item.note || "")}</textarea></label></div>`;
    return "";
  }

  function promotionForm(item = {}) {
    return `<div class="form-grid three"><label>Promotion명<input name="title" value="${esc(item.title || "")}" required></label><label>시작일<input name="start_date" type="date" value="${esc(item.start_date || "")}" required></label><label>종료일<input name="end_date" type="date" value="${esc(item.end_date || "")}" required></label><label>상태<select name="status_code" data-searchable>${options("promotion_statuses", item.commercial_status_code || "active")}</select></label><label class="full">비고<input name="notes" value="${esc(item.commercial_notes || "")}"></label><section class="full commercial-form-section promotion-terms"><h3>Item별 Override · 빈 값은 Base 조건 유지</h3><div class="commercial-item-term-head"><span>Item</span><span>가격</span><span>통화</span><span>MOQ</span><span>UOM</span><span>FOC %</span><span>포장·라벨</span><span>Other</span></div>${itemRows(item.items || [],true,true)}</section><section class="full commercial-form-section"><h3>Promotion 매출계획 → 공식 Monthly FCST (선택)</h3><div class="form-grid three"><label>Target Month<input name="target_month" type="month" value="${esc(item.sales_lines?.[0]?.target_month || "")}"></label><label>Expected Quantity<input name="expected_quantity" type="number" min="0" step="0.01" value="${esc(item.sales_lines?.[0]?.expected_quantity ?? "")}"></label><label>Expected Amount<input name="expected_amount" type="number" min="0" step="0.01" value="${esc(item.sales_lines?.[0]?.expected_amount ?? "")}"></label></div><p>선택한 첫 Item 기준으로 stable line을 생성하며 재저장해도 중복 FCST를 만들지 않습니다.</p></section></div>`;
  }

  function findItem(mode, id) {
    const b = cc.bundle || {};
    if (mode === "contract") return (b.contracts || []).find(row => row.id === id);
    if (mode === "default-term") return (b.default_terms || []).find(row => row.id === id);
    if (mode === "payment") return b.default_payment || {};
    if (mode === "address") return (b.addresses || []).find(row => row.id === id);
    if (mode === "provider") return (b.providers || []).find(row => row.id === id);
    if (mode === "document") return (b.document_requirements || []).find(row => row.id === id);
    if (mode === "closure") return (b.closures || []).find(row => row.id === id);
    if (mode === "promotion") return cc.promotions.find(row => row.id === id);
    return null;
  }

  function openForm(mode, id = "") {
    cc.mode = mode; cc.item = findItem(mode, id) || {};
    const titles = { contract:"Contract", "default-term":"기본 상업조건", payment:"Default Payment · Incoterms", address:"물류 주소", provider:"Logistics Provider", document:"무역서류 요구조건", closure:"Customer Closure", promotion:"Promotion" };
    $("#commercialContextTitle").textContent = `${titles[mode]} ${id ? "수정" : "등록"}`;
    $("#commercialContextFields").innerHTML = mode === "contract" ? contractForm(cc.item) : mode === "promotion" ? promotionForm(cc.item) : simpleForm(mode, cc.item);
    const activeForm=$("#commercialContextForm");
    if(activeForm.elements.currency&&cc.item.currency)activeForm.elements.currency.value=cc.item.currency;
    if(activeForm.elements.commercial_status_code&&cc.item.commercial_status_code)activeForm.elements.commercial_status_code.value=cc.item.commercial_status_code;
    if(activeForm.elements.provider_id){
      activeForm.elements.provider_id.addEventListener("change",()=>{
        const provider=cc.providerDirectory.find(row=>row.id===activeForm.elements.provider_id.value);
        if(!provider)return;
        activeForm.elements.provider_type.value=provider.provider_type||"";
        activeForm.elements.company_name.value=provider.company_name||"";
        activeForm.elements.website.value=provider.website||"";
        activeForm.elements.country_code.value=provider.country_code||"";
        window.SearchablePicker?.refresh(activeForm.elements.provider_type);
        window.SearchablePicker?.refresh(activeForm.elements.country_code);
      });
    }
    $("#commercialContextError").textContent = "";
    $("#commercialContextForm").dataset.rowId = id;
    $("#commercialContextDialog").showModal();
    $("#commercialContextFields").querySelectorAll('select').forEach(select=>select.dataset.searchable='');
    window.SearchablePicker?.enhanceAll($("#commercialContextFields"));
  }

  function value(form, name) { return new FormData(form).get(name) || ""; }
  function num(raw) { return raw === "" || raw == null ? null : Number(raw); }
  function selected(select) { return select ? [...select.selectedOptions].map(row => row.value).filter(Boolean) : []; }

  function collectContract(form) {
    const terms = [...form.querySelectorAll("[data-item-term]")].filter(row => row.querySelector("[data-item-enabled]").checked).map(row => ({
      interim_product_code: row.dataset.itemTerm, unit_price: num(row.querySelector("[data-term-price]").value),
      currency: row.querySelector("[data-term-currency]").value || "USD", price_method_code: row.querySelector("[data-term-method]").value || "base_price",
      moq_quantity: num(row.querySelector("[data-term-moq]").value), moq_uom: row.querySelector("[data-term-uom]").value,
      foc_markup_pct: num(row.querySelector("[data-term-foc]").value), packaging_label_code: row.querySelector("[data-term-label]").value,
      packaging_label_other: row.querySelector("[data-term-label-other]").value,
      notes: row.querySelector("[data-term-notes]")?.value || "",
    }));
    const target = num(value(form, "target_value")), targetType = value(form, "target_type") || "amount";
    const plans = value(form, "plan_year") && target != null ? [{ plan_year:Number(value(form,"plan_year")), target_type:targetType, target_amount:targetType === "amount" ? target : null, target_quantity:targetType === "quantity" ? target : null, target_uom:"EA", currency:value(form,"currency") || "USD" }] : [];
    const paymentFilled = value(form,"payment_method_code") || value(form,"incoterms_code");
    return { contract_no:value(form,"contract_no"), commercial_status_code:value(form,"commercial_status_code"), currency:value(form,"currency") || "USD", start_date:value(form,"start_date"), end_date:value(form,"end_date"), extension_end_date:value(form,"extension_end_date"), territory_country_codes:selected(form.elements.territory_country_codes), interim_product_codes:terms.map(row=>row.interim_product_code), item_terms:terms, sales_plans:plans, payment_override:paymentFilled ? {payment_method_code:value(form,"payment_method_code"), payment_method:value(form,"payment_method_code"), payment_method_other:value(form,"payment_method_other"), incoterms_code:value(form,"incoterms_code"), deferred_days:num(value(form,"deferred_days")) || 0, currency:value(form,"currency") || "USD", effective_from:value(form,"start_date"), effective_to:value(form,"extension_end_date") || value(form,"end_date")} : null, notes:value(form,"notes") };
  }

  function collectPromotion(form) {
    const items = [...form.querySelectorAll("[data-item-term]")].filter(row => row.querySelector("[data-item-enabled]").checked).map(row => ({ interim_product_code:row.dataset.itemTerm, price_override:num(row.querySelector("[data-term-price]").value), currency_override:row.querySelector("[data-term-currency]").value || null, moq_quantity_override:num(row.querySelector("[data-term-moq]").value), moq_uom_override:row.querySelector("[data-term-uom]").value || null, foc_markup_override_pct:num(row.querySelector("[data-term-foc]").value), packaging_label_override_code:row.querySelector("[data-term-label]").value || null, packaging_label_override_other:row.querySelector("[data-term-label-other]").value }));
    const month=value(form,"target_month"), quantity=num(value(form,"expected_quantity")), amount=num(value(form,"expected_amount"));
    const sales_lines = month && items.length && (quantity != null || amount != null) ? [{customer_id:cc.customer.id,interim_product_code:items[0].interim_product_code,target_month:month,expected_quantity:quantity,expected_amount:amount,currency:items[0].currency_override || "USD"}] : [];
    return { title:value(form,"title"),start_date:value(form,"start_date"),end_date:value(form,"end_date"),status_code:value(form,"status_code"),notes:value(form,"notes"),customer_ids:[cc.customer.id],items,sales_lines };
  }

  function collectSimple(form, mode) {
    const data = Object.fromEntries(new FormData(form).entries());
    ["unit_price","moq_quantity","foc_markup_pct","deferred_days"].forEach(key => { if (key in data) data[key] = num(data[key]); });
    if (mode === "document") { data.interim_product_codes=selected(form.elements.interim_product_codes); data.required=form.elements.required.checked; data.original_required=form.elements.original_required.checked; }
    if (mode === "address") { const row=(cc.taxonomy?.countries||[]).find(x=>x.code===data.country_code); data.country_name=row?.name||""; }
    if (mode === "provider") { const row=(cc.taxonomy?.countries||[]).find(x=>x.code===data.country_code); data.country_name=row?.name||""; data.active=true; }
    return data;
  }

  async function submit(event) {
    event.preventDefault();
    const form=event.currentTarget, mode=cc.mode, id=form.dataset.rowId;
    const customer=cc.customer.id;
    let path, method=id?"PATCH":"POST", body;
    if(mode==="contract"){path=`/api/customer-master/${customer}/commercial-contracts${id?`/${id}`:""}`;body=collectContract(form);}
    else if(mode==="default-term"){path=`/api/customer-master/${customer}/default-commercial-terms${id?`/${id}`:""}`;body=collectSimple(form,mode);}
    else if(mode==="payment"){path=`/api/customer-master/${customer}/default-payment`;method="PUT";body=collectSimple(form,mode);}
    else if(mode==="promotion"){path=`/api/commercial-context/promotions${id?`/${id}`:""}`;body=collectPromotion(form);}
    else {const paths={address:"logistics-addresses",provider:"logistics-providers",document:"document-requirements",closure:"closures"};path=`/api/customer-master/${customer}/${paths[mode]}${id?`/${id}`:""}`;body=collectSimple(form,mode);}
    if(id&&cc.item?.version)body.version=cc.item.version;
    const button=form.querySelector("button[type=submit]");button.disabled=true;$("#commercialContextError").textContent="";
    try{const result=await api(path,{method,body});$("#commercialContextDialog").close();toast(result.message);if(cc.refresh)await cc.refresh();}
    catch(error){$("#commercialContextError").textContent=error.message;}
    finally{button.disabled=false;}
  }

  function bind() {
    $("#commercialContextForm")?.addEventListener("submit", submit);
  }

  function handleClick(event, refresh) {
    const button=event.target.closest("[data-commercial-action]");
    if(!button)return false;
    cc.refresh=refresh;
    openForm(button.dataset.commercialAction,button.dataset.commercialId||"");
    return true;
  }

  window.CommercialContextUI={load,render,handleClick,bind,get bundle(){return cc.bundle;},get taxonomy(){return cc.taxonomy;}};
})();
