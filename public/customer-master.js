(function () {
  const cm = { loaded:false, customers:[], latestSync:null, openReviews:0, taxonomy:null, commercialTaxonomy:null, segment:"dental", map:null, mapSelected:null, detail:null, tab:"overview", page:1, masterOriginal:null, detailOriginal:null };
  const lifecycleLabels = { active:"거래 중", paused:"일시중단", dormant:"장기휴면", contract_ended:"계약종료", ended:"거래종료" };
  const sourceLabels = { erp:"ERP 연동", manual:"수동 등록", temporary:"임시", legacy:"기존 이관" };
  const relationLabels = { dealer:"Dealer", odm:"ODM", dealer_odm:"Dealer+ODM" };
  const businessLabels = { medical:"메디컬", dental:"덴탈", aesthetic:"에스테틱" };
  const businessDetailLabels = { dental:"Dental", aesthetic:"Aesthetic", medical_os:"Medical (OS)", medical_ns:"Medical (NS)", medical_unspecified:"Medical (상세 검토 필요)" };
  const stageLabels = { new_prospect:"신규후보", regular_candidate:"정규후보", regular:"정규", discontinued:"중단" };
  const maturityLabels = { temporary:"임시 Master", formal:"정식 Master" };
  const organizationRoleLabels = { distributor:"Distributor", odm:"ODM", clinic_hospital:"Clinic / Hospital", kol:"KOL", other:"Other" };
  const tabDefinitions = [
    ["overview","기본정보"], ["commercial","상업조건"], ["promotion","Promotion"],
    ["payment","Payment"], ["logistics_v2","물류·통관"],
    ["registrations","인허가"], ["schedule","일정"], ["activities","주요업무·활동"],
    ["system","기타·시스템"],
  ];
  const kindGroup = {contacts:"overview",contracts:"contracts_products","product-terms":"contracts_products","payment-terms":"sales_terms","sales-plans":"sales_terms",logistics:"logistics",registrations:"registrations",meetings:"activities",education:"activities",marketing:"activities","odm-projects":"system",competitors:"system"};
  const kindLabels = {contacts:"담당자",contracts:"계약","product-terms":"고객별 가격·FOC·MOQ", "payment-terms":"결제·여신조건", "sales-plans":"사업계획",logistics:"물류·통관",registrations:"인허가",meetings:"미팅·이슈",education:"제품교육",marketing:"홍보지원","odm-projects":"ODM 프로젝트",competitors:"경쟁제품"};
  const fieldLabels = {
    contact_name:"성명", department_title:"부서·직책", responsibility:"담당업무", is_decision_maker:"의사결정권자", is_primary_contact:"대표 연락담당", email:"이메일", phone:"전화번호", messenger:"WhatsApp 등", language:"기존 사용 언어 원문", language_code:"사용 언어", employment_status:"재직상태", notes:"비고",
    contract_name:"계약명·구분", contract_no:"계약번호", contract_type:"기존 계약유형 원문", exclusivity:"독점/비독점", contract_status:"기존 계약상태 원문", contract_status_code:"계약상태", start_date:"시작일", end_date:"종료일", auto_renew:"자동연장", notice_deadline:"통보기한", territory:"기존 Territory 원문", territory_country_codes:"계약 국가", territory_countries:"계약 국가", products_scope:"기존 제품범위 원문", interim_product_codes:"계약 제품", currency:"통화", contract_amount:"계약금액", annual_min_amount:"연간 최소구매금액", annual_min_quantity:"연간 최소구매수량", approval_user_name:"승인자", approval_date:"승인일", renewal_date:"갱신 예정일",
    payment_method:"기존 결제조건 원문", payment_method_code:"결제수단", payment_method_other:"기타 결제수단", advance_ratio:"기존 선불 비율", deferred_ratio:"기존 후불 비율", collection_basis:"수금기준", deferred_days:"후불일수", installments_json:"기존 분할수금 원문", payment_schedule_json:"지급 Schedule", normalization_status:"구조화 확인상태", lc_terms:"L/C 조건", fee_bearer:"송금수수료 부담", credit_limit:"여신한도", hold_on_overdue:"연체 시 출고보류", approver_name:"승인자", evidence_path:"근거자료", effective_from:"적용 시작", effective_to:"적용 종료", is_current:"현재 조건",
    interim_product_code:"Interim Product", product_name:"기존 제품명 원문", specification:"규격", internal_product_code:"내부 제품코드", customer_product_code:"고객사 제품코드", price_type:"가격방식", base_unit_price:"기존 기본단가", agreed_unit_price:"거래처 합의단가", moq:"MOQ", moq_basis:"MOQ 판단기준", paid_quantity:"기준 유상수량", foc_quantity:"FOC 수량", foc_condition:"FOC 표시조건", foc_ratio:"FOC 할증률", effective_unit_price:"FOC 포함 실질단가", packaging_label:"포장·라벨 요구사항",
    incoterms:"Incoterms", transport_mode:"운송방식", forwarder:"Preferred Forwarder", customs_broker:"Customs Broker", courier_code:"Courier", courier_account:"Courier 고객번호", origin_address:"출고지", destination_address:"도착지", consignee:"Consignee", notify_party:"Notify Party", default_port:"도착 공항·항구", required_documents:"기존 필요서류 원문", coa_required:"기존 COA", coo_required:"기존 COO", fsc_required:"기존 FSC", shipping_mark:"Shipping Mark", originals_required:"원본 필요", external_system:"외부시스템", insurance_bearer:"운송보험 부담", requires_import_invoice:"수입용 Invoice 필요", requires_additional_documents:"Invoice 외 추가서류 필요", additional_documents_json:"필요 추가서류", additional_documents_note:"기타 필요서류", customs_invoice_notes:"통관 / Invoice 특이사항", normalization_status:"구조화 확인상태",
    country_name:"국가", registration_status:"인허가 상태", registration_no:"허가번호", holder_name:"허가권자", application_date:"신청일", valid_from:"유효 시작", valid_to:"유효 종료", certificate_path:"허가증", label_languages:"포장·라벨 언어",
    project_no:"프로젝트번호", brand_name:"고객 브랜드명", product_spec:"요청 제품·규격", development_stage:"개발단계", expected_quantity:"예상수량", target_unit_price:"목표단가", sample_date:"샘플일", specification_confirmed_at:"사양 확정일", regulatory_owner:"인허가 책임", development_cost:"개발비", tooling_cost:"금형비", nda_signed:"NDA", quality_agreement:"품질계약", expected_po_date:"예상 PO일", expected_launch_date:"예상 출시일", owner_id:"담당자", next_action_date:"다음 조치일", issue_notes:"이슈",
    plan_year:"기준연도", business_unit:"사업분야", product_group:"제품군", optimistic_amount:"낙관계획", neutral_amount:"중립계획", conservative_amount:"보수계획", applied_amount:"최종 적용계획", override_next_order_date:"수정 다음 오더일", override_reason:"수정사유",
    event_date:"교육일", attendees:"참석자", education_type:"교육방식", trainer_name:"교육담당자", material_path:"교육자료", followup_required:"추가교육 필요", next_event_date:"다음 교육예정일",
    support_date:"지원일", support_item:"지원품목", quantity:"수량", support_amount:"지원금액", shipping_info:"배송정보", promotion_record_id:"관련 프로모션",
    product_category:"제품분류", brand_name:"브랜드", handles_implants:"임플란트 취급", main_products:"주요 경쟁제품", estimated_scale:"예상 판매규모",
    meeting_date:"미팅일", discussion:"논의내용", decisions:"결정사항", issue_text:"이슈", importance:"중요도", next_action:"후속조치", due_date:"완료기한", action_status:"진행상태", next_meeting_date:"다음 미팅일",
  };
  const detailFields = {
    contacts:["contact_name","department_title","responsibility","is_decision_maker","is_primary_contact","email","phone","messenger","language_code","employment_status","notes"],
    contracts:["contract_name","contract_no","contract_status_code","exclusivity","start_date","end_date","auto_renew","notice_deadline","interim_product_codes","territory_country_codes","currency","contract_amount","annual_min_amount","annual_min_quantity","approval_user_name","approval_date","renewal_date","notes"],
    "payment-terms":["payment_method_code","payment_method_other","payment_schedule_json","collection_basis","deferred_days","lc_terms","currency","fee_bearer","credit_limit","hold_on_overdue","approver_name","evidence_path","effective_from","effective_to","is_current","notes"],
    "product-terms":["interim_product_code","specification","internal_product_code","customer_product_code","price_type","agreed_unit_price","currency","moq","moq_basis","paid_quantity","foc_quantity","foc_condition","packaging_label","is_current","notes"],
    logistics:["incoterms","transport_mode","forwarder","customs_broker","courier_code","courier_account","origin_address","destination_address","consignee","notify_party","default_port","requires_import_invoice","requires_additional_documents","additional_documents_json","additional_documents_note","customs_invoice_notes","shipping_mark","originals_required","external_system","insurance_bearer","notes"],
    registrations:["country_name","product_name","specification","registration_status","registration_no","holder_name","application_date","approval_date","valid_from","valid_to","renewal_date","certificate_path","label_languages","notes"],
    "odm-projects":["project_no","brand_name","product_spec","development_stage","expected_quantity","moq","target_unit_price","sample_date","specification_confirmed_at","packaging_label","regulatory_owner","development_cost","tooling_cost","nda_signed","quality_agreement","expected_po_date","expected_launch_date","owner_id","next_action_date","issue_notes"],
    "sales-plans":["plan_year","business_unit","product_group","optimistic_amount","neutral_amount","conservative_amount","applied_amount","currency","override_next_order_date","override_reason"],
    education:["product_name","event_date","attendees","education_type","trainer_name","material_path","followup_required","next_event_date","notes"],
    marketing:["support_date","support_item","quantity","support_amount","currency","shipping_info","promotion_record_id","notes"],
    competitors:["product_category","brand_name","handles_implants","main_products","estimated_scale","notes"],
    meetings:["meeting_date","attendees","discussion","decisions","issue_text","importance","next_action","owner_id","due_date","action_status","next_meeting_date"],
  };
  const numericFields = new Set(["contract_amount","annual_min_amount","annual_min_quantity","advance_ratio","deferred_days","credit_limit","base_unit_price","agreed_unit_price","moq","paid_quantity","foc_quantity","expected_quantity","target_unit_price","development_cost","tooling_cost","plan_year","optimistic_amount","neutral_amount","conservative_amount","applied_amount","quantity","support_amount"]);
  const dateFields = new Set(["start_date","end_date","notice_deadline","approval_date","renewal_date","effective_from","effective_to","application_date","valid_from","valid_to","sample_date","specification_confirmed_at","expected_po_date","expected_launch_date","next_action_date","override_next_order_date","event_date","next_event_date","support_date","meeting_date","due_date","next_meeting_date"]);
  const boolFields = new Set(["is_decision_maker","is_primary_contact","auto_renew","hold_on_overdue","is_current","coa_required","coo_required","fsc_required","originals_required","nda_signed","quality_agreement","followup_required","handles_implants","requires_import_invoice","requires_additional_documents"]);

  function userOptions(selected, includeEmpty=true) {
    const empty = includeEmpty ? '<option value="">미지정</option>' : '';
    return empty + (state.users || []).filter(user => !user.status || user.status === "active").map(user => `<option value="${user.id}" ${Number(selected) === Number(user.id) ? "selected" : ""}>${escapeHtml(user.display_name)}</option>`).join("");
  }
  function cmMoney(value) { return formatMoney(Number(value || 0), "KRW"); }
  function effectiveRoles(row) { return row.organization_roles?.length ? row.organization_roles : (row.organization_role_candidates || []); }
  function filteredCustomers(active=true) {
    const q = String($("#customerMasterSearch").value || "").trim().toLowerCase();
    const source = $("#customerSourceFilter").value, region = $("#customerRegionFilter").value;
    const country = $("#customerCountryFilter").value, business = $("#customerBusinessFilter").value;
    const owner = $("#customerOwnerFilter").value, contract = $("#customerContractFilter").value;
    const role = $("#customerOrganizationRoleFilter").value, stage = $("#customerStageFilter").value;
    const incomplete = $("#customerIncompleteFilter").checked, reviewOnly = $("#customerReviewFilter").checked;
    return cm.customers.filter(row => {
      const isActive = row.lifecycle_status === "active" && row.business_stage !== "discontinued";
      if (active !== isActive) return false;
      if (source === "erp" && !row.erp_partner_code) return false;
      if (source === "temporary" && !String(row.customer_id||"").startsWith("TEMP-")) return false;
      if (source && !["erp","temporary"].includes(source) && row.source_type !== source) return false;
      if (region && row.sales_region !== region) return false;
      if (country && row.headquarters_country !== country && !(row.sales_countries||[]).some(item=>item.country_name===country)) return false;
      if (business === "odm" && !effectiveRoles(row).includes("odm")) return false;
      if (business && business !== "odm" && !(row.business_units||[]).includes(business)) return false;
      if (owner && ![row.primary_owner_id,row.secondary_owner_id].some(id=>String(id||"")===owner)) return false;
      if (contract && (row.contract_status||"미등록") !== contract) return false;
      if (role && !(row.organization_roles||[]).includes(role)) return false;
      if (stage === "review_required" && row.business_stage_review_status === "confirmed" && row.business_stage) return false;
      if (stage && stage !== "review_required" && row.business_stage !== stage) return false;
      if (reviewOnly && !row.review_required) return false;
      if (incomplete && row.completion?.complete) return false;
      if (q && ![row.display_name,row.erp_original_name,row.customer_id,row.erp_partner_code].some(value => String(value || "").toLowerCase().includes(q))) return false;
      return true;
    });
  }
  function renderSyncSummary() {
    const sync = cm.latestSync || {};
    const when = sync.finished_at ? formatDate(sync.finished_at, true) : "아직 실행 전";
    const domesticPartnerCount = sync.domestic_excluded_partner_count;
    const domesticValue = domesticPartnerCount == null ? "확인 대기" : `${formatNumber(domesticPartnerCount)}개`;
    const domesticNote = domesticPartnerCount == null && Number(sync.domestic_excluded_count || 0) > 0
      ? `기존 이력: ${formatNumber(sync.domestic_excluded_count)}개 출고 헤더 제외`
      : "ERP 응답의 거래처 코드 기준";
    $("#customerSyncSummary").innerHTML = `
      <div class="customer-sync-main"><span>마지막 거래처 동기화</span><strong>${escapeHtml(when)}</strong><small>ERP 조회 전용 · 거래처 코드 trCd 기준 · ERP 역전송 없음</small></div>
      <div><span>신규 추가</span><strong>${formatNumber(sync.created_count || 0)}건</strong></div>
      <div><span>갱신</span><strong>${formatNumber(sync.updated_count || 0)}건</strong></div>
      <div><span>중복 검토</span><strong>${formatNumber(sync.duplicate_review_count || 0)}건</strong></div>
      <div><span>Domestic 제외</span><strong>${domesticValue}</strong><small>${domesticNote}</small></div>
      <div><span>오류</span><strong>${formatNumber(sync.error_count || 0)}건</strong><small>열린 검토 ${formatNumber(cm.openReviews)}건</small></div>`;
  }
  function renderKpis() {
    const all=cm.customers, active=all.filter(row=>row.lifecycle_status==="active"), inactive=all.length-active.length;
    const classified=all.filter(row=>row.business_stage&&row.business_stage_review_status==="confirmed").length;
    const formal=all.filter(row=>row.master_maturity==="formal"&&row.master_maturity_review_status==="confirmed").length;
    const temp=all.filter(row=>row.technical_identity_status==="temporary_identity").length;
    const review=all.filter(row=>row.review_required).length, sales=active.reduce((sum,row)=>sum+Number(row.current_year_sales_krw||0),0);
    $("#customerMasterKpis").innerHTML = [["전체 거래처",`${formatNumber(all.length)}개`],["업무단계 확정",`${formatNumber(classified)}개`],["정식 Master",`${formatNumber(formal)}개`],["TEMP Identity",`${formatNumber(temp)}개`],["정책 확인 필요",`${formatNumber(review)}개`],["올해 ERP 매출",cmMoney(sales)]].map(([label,value])=>`<div><span>${label}</span><strong>${value}</strong></div>`).join("");
  }
  function renderFilters() {
    const select=$("#customerRegionFilter"), current=select.value;
    const regions=[...new Set(cm.customers.map(row=>row.sales_region).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"ko"));
    select.innerHTML='<option value="">전체 소재권역</option>'+regions.map(value=>`<option ${value===current?"selected":""}>${escapeHtml(value)}</option>`).join("");
    const countrySelect=$("#customerCountryFilter"), currentCountry=countrySelect.value;
    const countries=[...new Set(cm.customers.flatMap(row=>[row.headquarters_country,...(row.sales_countries||[]).map(item=>item.country_name)]).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"ko"));
    countrySelect.innerHTML='<option value="">전체 국가</option>'+countries.map(value=>`<option ${value===currentCountry?"selected":""}>${escapeHtml(value)}</option>`).join("");
    const ownerSelect=$("#customerOwnerFilter"), currentOwner=ownerSelect.value;
    ownerSelect.innerHTML='<option value="">전체 담당자</option>'+userOptions(currentOwner,false);
    const contractSelect=$("#customerContractFilter"), currentContract=contractSelect.value;
    const contracts=[...new Set(cm.customers.map(row=>row.contract_status||"미등록"))].sort((a,b)=>a.localeCompare(b,"ko"));
    contractSelect.innerHTML='<option value="">전체 계약상태</option>'+contracts.map(value=>`<option value="${escapeHtml(value)}" ${value===currentContract?"selected":""}>${escapeHtml(value==='미등록'?value:taxonomyLabel('contract_statuses',value))}</option>`).join("");
  }
  function completionHtml(row) {
    return `<div class="customer-completion"><div><span style="width:${Number(row.completion?.percent||0)}%"></span></div><small>${formatNumber(row.completion?.percent||0)}% · ${row.completion?.complete?"완료":"정보 입력 필요"}</small></div>`;
  }
  function customerTable(rows, inactive=false) {
    if (!rows.length) return '<div class="empty-state">선택 조건의 거래처가 없습니다.</div>';
    return `<table class="customer-table"><thead><tr><th>소재권역</th><th>국가</th><th>고객명</th><th>업무단계</th><th>조직 역할</th><th>정·부 담당자</th><th>사업분야 · Item</th><th>계약상태·종료일</th><th>올해 매출</th><th>사업계획 달성률</th><th>마지막 오더</th><th>다음 예상 오더</th><th>주요 이슈</th><th>정보 완성도</th></tr></thead><tbody>${rows.map(row=>`<tr data-customer-id="${escapeHtml(row.id)}" class="${inactive?"customer-inactive-row":""}">
      <td>${escapeHtml(row.sales_region||"미분류")}</td><td>${escapeHtml(row.headquarters_country||"미분류")}</td>
      <td class="customer-name-cell"><strong>${escapeHtml(row.display_name)}</strong><small>${escapeHtml(row.erp_original_name||"ERP 원본명 없음")}</small><div class="customer-badges"><span class="customer-chip ${row.source_type==='erp'?'erp':''}">${escapeHtml(sourceLabels[row.source_type]||row.source_type)}</span>${row.review_required?'<span class="customer-chip warning">정책 확인 필요</span>':''}${row.duplicate_review_status==='review_required'?'<span class="customer-chip danger">중복 검토</span>':''}</div></td>
      <td><strong>${escapeHtml(stageLabels[row.business_stage]||"미분류")}</strong><span class="table-sub">${row.business_stage_review_status==='confirmed'?'확정':'Review Required'}</span></td>
      <td>${effectiveRoles(row).map(role=>`<span class="customer-chip ${row.organization_roles?.length?'':'warning'}">${escapeHtml(organizationRoleLabels[role]||role)}</span>`).join(' ')||'—'}<span class="table-sub">${row.organization_roles?.length?'확정':'기존값 후보'}</span></td>
      <td>${escapeHtml(row.primary_owner_name||"미지정")}<span class="table-sub">부 ${escapeHtml(row.secondary_owner_name||"미지정")}</span></td>
      <td>${(row.business_units||[]).map(unit=>`<span class="customer-chip">${escapeHtml(businessLabels[unit]||unit)}</span>`).join(" ")||"—"}<span class="table-sub">${(row.commercial_items||[]).map(item=>escapeHtml(taxonomyLabel('interim_contract_products',item.interim_product_code))).join(' · ')||'Item 미설정'}</span></td>
      <td>${row.contract_badge?`<span class="customer-chip ${['action_required','expired'].includes(row.contract_badge.code)?'danger':['d30','d60'].includes(row.contract_badge.code)?'warning':''}">${escapeHtml(row.contract_badge.label)}</span>`:'미등록'}<span class="table-sub ${row.contract_days_remaining!=null&&row.contract_days_remaining<=60?'warning-text':''}">${formatDate(row.contract_end_date)}</span></td>
      <td><strong>${cmMoney(row.current_year_sales_krw)}</strong><span class="table-sub">누적 ${cmMoney(row.cumulative_sales_krw)}</span></td><td>${row.plan_achievement_rate==null?'—':`${formatNumber(row.plan_achievement_rate,1)}%`}<span class="table-sub">계획 ${cmMoney(row.current_year_plan)}</span></td><td>${formatDate(row.last_ship_date)}</td><td>${formatDate(row.next_expected_order_date)}</td><td>${escapeHtml(row.latest_issue||"—")}<span class="table-sub">${formatDate(row.latest_meeting_date)}</span></td><td>${completionHtml(row)}</td></tr>`).join("")}</tbody></table>`;
  }
  function renderLists() {
    const active=filteredCustomers(true), inactive=filteredCustomers(false), perPage=Number($("#customerPerPage").value||20);
    const pages=Math.max(1,Math.ceil(active.length/perPage));cm.page=Math.min(cm.page,pages);
    const pageRows=active.slice((cm.page-1)*perPage,cm.page*perPage);
    $("#customerMasterCount").textContent=`활성 ${active.length} · 중단 ${inactive.length} · ${cm.page}/${pages}페이지`;
    $("#customerActiveRegions").innerHTML=pageRows.length?`<section class="customer-region-group"><header><h3>전체 거래처</h3><span>${formatNumber(active.length)}개 중 ${formatNumber((cm.page-1)*perPage+1)}–${formatNumber((cm.page-1)*perPage+pageRows.length)}</span></header><div class="customer-table-card">${customerTable(pageRows)}</div></section>`:'<div class="empty-state">선택 조건의 활성 거래처가 없습니다.</div>';
    $("#customerPagination").innerHTML=active.length>perPage?Array.from({length:pages},(_,index)=>index+1).map(page=>`<button type="button" data-customer-page="${page}" class="${page===cm.page?'active':''}">${page}</button>`).join(''):'';
    $("#customerInactiveCount").textContent=formatNumber(inactive.length); $("#customerInactiveList").innerHTML=customerTable(inactive,true);
  }
  async function load(force=false) {
    if (cm.loaded&&!force){renderAll();return;}
    $("#customerActiveRegions").innerHTML='<div class="empty-state">거래처 마스터를 불러오는 중입니다.</div>';
    try {
      const [data,taxonomy,commercialTaxonomy]=await Promise.all([api('/api/customer-master'),cm.taxonomy?Promise.resolve(cm.taxonomy):api('/api/customer-master/taxonomy'),cm.commercialTaxonomy?Promise.resolve(cm.commercialTaxonomy):api('/api/commercial-context/taxonomy')]);
      cm.taxonomy=taxonomy;cm.commercialTaxonomy=commercialTaxonomy;cm.customers=data.customers||[];cm.latestSync=data.latest_sync;cm.openReviews=data.open_review_count||0;
      Object.assign(businessLabels,Object.fromEntries((taxonomy.business_parent||[]).map(item=>[item.code,item.label])));
      Object.assign(stageLabels,Object.fromEntries((taxonomy.customer_stages||[]).map(item=>[item.code,item.label])));
      Object.assign(maturityLabels,Object.fromEntries((taxonomy.master_maturities||[]).map(item=>[item.code,item.label])));
      Object.assign(organizationRoleLabels,Object.fromEntries((taxonomy.organization_roles||[]).map(item=>[item.code,item.label])));
      cm.loaded=true;renderAll();await loadMap();
    }
    catch(error){toast(error.message,"error"); $("#customerActiveRegions").innerHTML=`<div class="empty-state">${escapeHtml(error.message)}</div>`;}
  }
  function renderAll(){renderSyncSummary();renderKpis();renderFilters();renderLists();}
  async function loadMap(){
    try{cm.map=await api(`/api/customer-master/map?segment=${encodeURIComponent(cm.segment)}`); if(!state.worldTopology)await loadWorldTopology(); renderMap();}
    catch(error){$("#customerWorldMap").innerHTML=`<div class="empty-state">${escapeHtml(error.message)}</div>`;}
  }
  function renderMap(){
    const rows=cm.map?.countries||[], byCode=new Map(rows.map(row=>[String(row.country_code||'').padStart(3,'0'),row]));
    if(!rows.some(row=>String(row.country_code||'').padStart(3,'0')===cm.mapSelected))cm.mapSelected=rows[0]?String(rows[0].country_code||'').padStart(3,'0'):null;
    const paths=buildWorldShapes().map(shape=>{const row=byCode.get(shape.id),tone=!row||Number(row.active_count)===0?'none':Number(row.active_count)>=2?'many':'one';const selected=shape.id===cm.mapSelected;const title=row?`${row.country_name} · 활성 ${row.active_count}개 · 중단 ${row.inactive_count||0}개`:shape.name;return `<path class="map-country ${tone} ${selected?'selected':''}" d="${shape.path}" fill-rule="evenodd" ${row?`data-cm-map-id="${shape.id}" tabindex="0" role="button"`:''}><title>${escapeHtml(title)}</title></path>`;}).join('');
    $("#customerWorldMap").innerHTML=`<svg viewBox="0 0 1000 480" role="img" aria-label="거래처 마스터 ${escapeHtml(businessLabels[cm.segment]||'ODM')} 지도"><rect class="map-ocean" width="1000" height="480" rx="20"></rect><g>${paths}</g></svg>`; renderMapDetail(byCode.get(cm.mapSelected));
  }
  function renderMapDetail(country){
    const node=$("#customerMapDetail"); if(!country){node.innerHTML='<div class="empty-state">해당 분야의 활성 공급국가가 없습니다.</div>';return;}
    node.innerHTML=`<h4>${escapeHtml(country.country_name)}</h4><p>${escapeHtml(country.sales_region||'미분류')} · 활성 ${formatNumber(country.active_count)}개 · 중단 ${formatNumber(country.inactive_count||0)}개 · 올해 ${cmMoney(country.current_year_sales_krw)}</p>${(country.customers||[]).map(row=>`<button class="customer-map-account ${row.lifecycle_status==='active'?'':'inactive'}" data-customer-id="${escapeHtml(row.id)}" type="button"><strong>${escapeHtml(row.display_name)}</strong><span>${escapeHtml(row.primary_owner_name||'미지정')} · 올해 ${cmMoney(row.current_year_sales_krw)}</span><span>마지막 출고 ${formatDate(row.last_ship_date)} · 계약종료 ${formatDate(row.contract_end_date)}</span></button>`).join('')}`;
  }
  function sortedValues(values){return [...values].map(String).sort();}
  function sameValues(left,right){return JSON.stringify(sortedValues(left||[]))===JSON.stringify(sortedValues(right||[]));}
  function collectMasterValues(form){
    const data=new FormData(form),result={};
    ["display_name","legal_name_en","erp_partner_code","erp_original_name","headquarters_country","sales_region","relationship_type","customer_role","business_stage","master_maturity","primary_owner_id","secondary_owner_id","default_currency","timezone_name","website","address","first_transaction_date","last_information_reviewed_at","notes"].forEach(name=>{result[name]=data.get(name)||"";});
    result.organization_roles=data.getAll("organization_roles");result.language_codes=data.getAll("language_codes");result.business_units=data.getAll("business_units");result.item_codes=data.getAll("item_codes");result.contract_policy=data.get("contract_policy")||"";
    return result;
  }
  function changedMasterPayload(form){
    const values=collectMasterValues(form),original=cm.masterOriginal;
    if(!original){
      values.primary_owner_id=values.primary_owner_id||null;values.secondary_owner_id=values.secondary_owner_id||null;return values;
    }
    const body={expected_version:original.version};
    ["display_name","legal_name_en","headquarters_country","sales_region","business_stage","master_maturity","primary_owner_id","secondary_owner_id","default_currency","timezone_name","website","address","first_transaction_date","last_information_reviewed_at","notes"].forEach(name=>{
      const current=String(values[name]??""),before=String(original[name]??"");
      if(current!==before)body[name]=name.endsWith("_id")?(values[name]||null):values[name];
    });
    if(String(values.contract_policy||"")!==String(original.contract_policy||""))body.contract_policy=values.contract_policy||null;
    [["organization_roles",values.organization_roles,original.organization_roles],["language_codes",values.language_codes,original.language_codes],["business_units",values.business_units,original.business_units],["item_codes",values.item_codes,original.commercial_item_codes||[]]].forEach(([name,current,before])=>{if(!sameValues(current,before))body[name]=current;});
    return body;
  }
  function updateMasterDirty(){
    const form=$("#customerMasterForm"),changed=cm.masterOriginal?Object.keys(changedMasterPayload(form)).some(key=>key!=="expected_version"):true;
    form.classList.toggle("is-dirty",changed);$("#customerMasterDirtyState").textContent=changed?"저장하지 않은 변경사항이 있습니다.":"변경사항 없음";
  }
  function syncMasterItemScope(dropInvalid=false){
    const form=$("#customerMasterForm"),selectedBusiness=new Set([...form.elements.business_units.selectedOptions].map(option=>option.value));
    const itemByCode=new Map((cm.commercialTaxonomy?.items||[]).map(item=>[item.code,item]));
    [...form.elements.item_codes.options].forEach(option=>{
      const item=itemByCode.get(option.value),allowed=Boolean(item&&selectedBusiness.has(item.business_unit));
      if(!allowed&&dropInvalid)option.selected=false;
      const preserveExisting=option.selected&&!dropInvalid;
      option.hidden=!allowed&&!preserveExisting;
      option.disabled=!allowed&&!preserveExisting;
    });
    window.SearchablePicker?.refresh(form.elements.item_codes);
  }
  function openMasterForm(customer=null){
    const form=$("#customerMasterForm");form.reset();$("#customerMasterFormError").textContent='';$("#customerMasterDialogTitle").textContent=customer?'거래처 기본정보 수정':'수동 거래처 등록';
    form.elements.id.value=customer?.id||'';form.elements.primary_owner_id.innerHTML=userOptions(customer?.primary_owner_id);form.elements.secondary_owner_id.innerHTML=userOptions(customer?.secondary_owner_id);
    const countrySelect=form.elements.headquarters_country,countries=cm.taxonomy?.countries||[];
    countrySelect.innerHTML='<option value="">국가 선택</option>'+countries.map(item=>`<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} · ${escapeHtml(item.label)}</option>`).join('');
    if(customer?.headquarters_country&&!countries.some(item=>item.name===customer.headquarters_country))countrySelect.insertAdjacentHTML('beforeend',`<option value="${escapeHtml(customer.headquarters_country)}">${escapeHtml(customer.headquarters_country)} · 기존 원문(확인 필요)</option>`);
    $("#customerTimezoneOptions").innerHTML=(cm.taxonomy?.timezones||[]).map(value=>`<option value="${escapeHtml(value)}"></option>`).join('');
    ['display_name','legal_name_en','erp_partner_code','erp_original_name','headquarters_country','sales_region','relationship_type','customer_role','business_stage','master_maturity','default_currency','timezone_name','website','address','first_transaction_date','last_information_reviewed_at','notes'].forEach(name=>{if(form.elements[name])form.elements[name].value=customer?.[name]||'';});
    [...form.elements.organization_roles.options].forEach(option=>option.selected=(customer?.organization_roles||[]).includes(option.value));
    [...form.elements.language_codes.options].forEach(option=>option.selected=(customer?.language_codes||[]).includes(option.value));
    [...form.elements.business_units.options].forEach(option=>option.selected=(customer?.business_units||[]).includes(option.value));
    const commercial=customer?.commercial_context||(customer&&cm.detail?.id===customer.id?cm.detail.commercial_context:{})||{};
    form.elements.item_codes.innerHTML=(cm.commercialTaxonomy?.items||[]).map(item=>`<option value="${escapeHtml(item.code)}">${escapeHtml(item.label)} · ${escapeHtml(businessLabels[item.business_unit]||item.business_unit)}</option>`).join('');
    const selectedItems=customer?.commercial_item_codes||(commercial.items||[]).map(item=>item.interim_product_code)||[];
    [...form.elements.item_codes.options].forEach(option=>option.selected=selectedItems.includes(option.value));
    syncMasterItemScope(false);
    form.elements.contract_policy.value=customer?.contract_policy||commercial.contract_policy||'';
    form.dataset.legacyRoleCandidate=customer?.organization_roles?.length?'':(customer?.organization_role_candidates||[]).join(',');
    [form.elements.business_stage,form.elements.master_maturity,form.elements.organization_roles,form.elements.business_units,form.elements.contract_policy].forEach(field=>field.required=!customer);
    form.elements.erp_partner_code.readOnly=Boolean(customer);cm.masterOriginal=customer?JSON.parse(JSON.stringify({...customer,commercial_item_codes:selectedItems})):null;updateMasterDirty();$("#customerMasterDialog").showModal();form.querySelectorAll('select').forEach(select=>select.dataset.searchable='');window.SearchablePicker?.enhanceAll(form);[form.elements.primary_owner_id,form.elements.secondary_owner_id,form.elements.headquarters_country,form.elements.organization_roles,form.elements.language_codes,form.elements.business_units,form.elements.item_codes,form.elements.contract_policy].forEach(field=>window.SearchablePicker?.refresh(field));
  }
  async function saveMaster(event){
    event.preventDefault();const form=event.currentTarget,id=form.elements.id.value,body=changedMasterPayload(form);
    if(id&&!Object.keys(body).some(key=>key!=="expected_version")){toast("변경된 정보가 없습니다.");$("#customerMasterDialog").close();return;}
    const button=form.querySelector('button[type="submit"]');button.disabled=true;$("#customerMasterFormError").textContent='';
    try{const result=await api(id?`/api/customer-master/${id}`:'/api/customer-master',{method:id?'PATCH':'POST',body});$("#customerMasterDialog").close();cm.loaded=false;await load(true);toast(result.message);if(id)await openDetail(id);}
    catch(error){showFormError(form,"#customerMasterFormError",error);}finally{button.disabled=false;}
  }
  async function openDetail(id){
    try{const dialog=$("#customerDetailDialog"),wasOpen=dialog.open;const data=await api(`/api/customer-master/${id}`);cm.detail=data.customer;if(window.CommercialContextUI){cm.detail.commercial_context=await window.CommercialContextUI.load(cm.detail);cm.detail.commercial_item_codes=(cm.detail.commercial_context.items||[]).map(item=>item.interim_product_code);}if(!wasOpen)cm.tab='overview';renderDetail();if(!wasOpen)dialog.showModal();}
    catch(error){toast(error.message,'error');}
  }
  function renderDetail(){
    const c=cm.detail;if(!c)return;$("#customerDetailTitle").textContent=c.display_name;$("#customerDetailSubtitle").textContent=`Customer 360 · ${c.headquarters_country||'소재국가 미확인'}`;
    const roleText=effectiveRoles(c).map(role=>organizationRoleLabels[role]||role).join(' · ')||'역할 미분류';
    const owner=(state.users.find(user=>Number(user.id)===Number(c.primary_owner_id))||{}).display_name||'미지정';
    const business=(c.business_units||[]).map(code=>businessLabels[code]||code).join(' · ')||'미분류';
    $("#customerDetailHeader").innerHTML=`<div class="summary-name"><span>Customer</span><strong>${escapeHtml(c.display_name)}</strong><small>${escapeHtml(c.legal_name_en||c.erp_original_name||'법인명 미확인')}</small></div><div><span>소재국가</span><strong>${escapeHtml(c.headquarters_country||'미확인')}</strong><small>${escapeHtml(c.sales_region||'권역 미분류')}</small></div><div><span>내부 담당자</span><strong>${escapeHtml(owner)}</strong><small>부담당자 ${escapeHtml(c.secondary_owner_id?((state.users.find(user=>Number(user.id)===Number(c.secondary_owner_id))||{}).display_name||'지정'):'미지정')}</small></div><div><span>업무단계</span><strong>${escapeHtml(stageLabels[c.business_stage]||'미분류')}</strong><small>${c.business_stage_review_status==='confirmed'?'확정':'Review Required'}</small></div><div><span>조직 역할</span><strong>${escapeHtml(roleText)}</strong><small>${c.organization_roles?.length?'확정':'Legacy Candidate'}</small></div><div><span>사업분야</span><strong>${escapeHtml(business)}</strong><small>상위 ${(c.business_units||[]).map(code=>businessLabels[code]||code).join(' · ')||'미분류'}</small></div><div><span>Review Required</span><strong>${formatNumber(c.review_required_count||0)}개</strong><small>${c.review_required?'항목별 확인 필요':'정책 확인 완료'}</small></div><div><span>ERP 연결</span><strong>${c.erp_partner_code?'Linked':'Unlinked'}</strong><small>${escapeHtml(c.erp_original_name||'외부 ID 미연결')}</small></div>`;
    $("#customerDetailTabs").innerHTML=tabDefinitions.map(([key,label])=>`<button data-customer-tab="${key}" class="${key===cm.tab?'active':''}" aria-selected="${key===cm.tab?'true':'false'}" type="button">${escapeHtml(label)}</button>`).join('');
    const alertNode=$("#customerDetailAlerts");alertNode.classList.toggle('hidden',!(c.alerts||[]).length);alertNode.innerHTML=(c.alerts||[]).map(item=>`<span>${escapeHtml(item.message)}</span>`).join('');
    $("#customerEditBtn").textContent='기본정보·정책 수정';$("#customerEditBtn").classList.toggle('hidden',!c.can_edit);$("#customerLinkErpBtn").classList.toggle('hidden',Boolean(c.erp_partner_code)||!["admin","manager"].includes(state.me?.role));$("#customerDeactivateBtn").classList.toggle('hidden',!c.can_edit||c.lifecycle_status!=='active');$("#customerRestoreBtn").classList.toggle('hidden',!c.can_edit||c.lifecycle_status==='active');renderDetailTab();
  }
  function taxonomyLabel(group,value){return Object.fromEntries((cm.taxonomy?.[group]||[]).map(item=>[item.code,item.label]))[value]||value;}
  function valueText(key,value){if(value===null||value===undefined||value==='')return '—';if(boolFields.has(key))return Number(value)?'예':'아니오';if(dateFields.has(key))return formatDate(value);if(key.endsWith('_at')||key.endsWith('_date'))return formatDate(value,true);if(numericFields.has(key)||['foc_ratio','effective_unit_price'].includes(key))return formatNumber(value,2);if(key==='payment_method_code')return taxonomyLabel('payment_methods',value);if(key==='courier_code')return taxonomyLabel('couriers',value);if(key==='contract_status_code')return taxonomyLabel('contract_statuses',value);if(key==='exclusivity')return taxonomyLabel('contract_exclusivities',value);if(key==='language_code')return taxonomyLabel('languages',value);if(key==='employment_status')return taxonomyLabel('contact_employment_statuses',value);if(key==='importance')return taxonomyLabel('meeting_importance',value);if(key==='action_status')return taxonomyLabel('meeting_action_statuses',value);if(key==='interim_product_code')return taxonomyLabel('interim_contract_products',value);if(key==='interim_product_codes')return (value||[]).map(code=>taxonomyLabel('interim_contract_products',code)).join(' · ')||'—';if(key==='territory_country_codes')return (value||[]).map(code=>taxonomyLabel('countries',code)).join(' · ')||'—';if(key==='territory_countries')return (value||[]).map(item=>item.label||item.name||item.code).join(' · ')||'—';if(key==='installments_json'){try{return JSON.parse(value).map(row=>`${row.label||''} ${row.days||0}일 ${row.ratio||0}%`).join(' · ')||'—';}catch(_){return value;}}if(key==='payment_schedule_json'){try{const triggers=Object.fromEntries((cm.taxonomy?.payment_triggers||[]).map(item=>[item.code,item.label]));return JSON.parse(value).map(row=>`${row.sequence||''}) ${row.percentage||0}% / ${triggers[row.trigger]||row.trigger}${row.note?' / '+row.note:''}`).join(' · ')||'—';}catch(_){return value;}}if(key==='additional_documents_json'){try{const docs=Object.fromEntries((cm.taxonomy?.additional_documents||[]).map(item=>[item.code,item.label]));return JSON.parse(value).map(code=>docs[code]||code).join(' · ')||'—';}catch(_){return value;}}if(key==='normalization_status')return value==='confirmed'?'구조화 확인 완료':'Review Required';return Array.isArray(value)?value.join(' · '):String(value);}
  function cardTitle(item,kind){
    if(kind==='contracts')return item.contract_name||item.contract_no||'계약';
    if(kind==='contacts')return item.contact_name||'담당자';
    if(kind==='payment-terms')return valueText('payment_method_code',item.payment_method_code)||'결제조건';
    if(kind==='product-terms')return valueText('interim_product_code',item.interim_product_code)||item.product_name||'고객별 제품조건';
    if(kind==='logistics')return item.incoterms||item.forwarder||'물류·통관 Default';
    if(kind==='registrations')return item.product_name||item.registration_no||'인허가';
    if(kind==='meetings')return formatDate(item.meeting_date)||'미팅';
    return item.project_no||item.brand_name||item.product_name||item.event_date||item.support_date||item.product_category||'상세정보';
  }
  function detailCard(item,kind=null){
    const title=cardTitle(item,kind),titleKeys={contracts:['contract_name'],contacts:['contact_name'],registrations:['product_name'],meetings:['meeting_date']}[kind]||[];
    const keys=Object.keys(item).filter(key=>!['id','customer_id','created_by','updated_by','created_at','updated_at','deleted_at','source_transport_record_id','payload','payload_json','territory_country_codes'].includes(key)&&!titleKeys.includes(key)&&item[key]!==''&&item[key]!==null);
    const actions=kind&&cm.detail.can_edit?`<span><button class="mini-btn" data-edit-detail="${kind}" data-row-id="${escapeHtml(item.id)}" type="button">수정</button><button class="mini-btn danger" data-delete-detail="${kind}" data-row-id="${escapeHtml(item.id)}" type="button">종료</button></span>`:'';
    return `<article class="customer-detail-card"><header><strong>${escapeHtml(title)}</strong><small>${formatDate(item.updated_at,true)} ${actions}</small></header><dl>${keys.map(key=>`<div class="${['contract_type','contract_status','territory','products_scope','payment_method','required_documents','language'].includes(key)?'legacy-field':''}"><dt>${escapeHtml(fieldLabels[key]||key)}</dt><dd>${escapeHtml(valueText(key,item[key]))}</dd></div>`).join('')}</dl></article>`;
  }
  function renderDetailTab(){
    const c=cm.detail,node=$("#customerDetailContent");
    const roleText=effectiveRoles(c).map(role=>organizationRoleLabels[role]||role).join(' · ')||'역할 미분류';
    if(["commercial","promotion","payment","logistics_v2","schedule"].includes(cm.tab)&&window.CommercialContextUI){node.innerHTML=window.CommercialContextUI.render(cm.tab);window.SearchablePicker?.enhanceAll(node);return;}
    if(cm.tab==='overview'){
      const countryRows=(c.sales_countries||[]).map(row=>`<span class="customer-chip">${escapeHtml(row.country_name)}${row.is_primary?' · 주':''}${c.can_edit?` <button class="mini-btn" data-delete-sales-country="${escapeHtml(row.id)}" type="button">×</button>`:''}</span>`).join(' ')||'등록 없음';
      const itemRows=(c.commercial_context?.items||[]).map(item=>`<span class="customer-chip">${escapeHtml(item.label)}</span>`).join(' ')||'Item 미설정';
      node.innerHTML=`<section><div class="customer-detail-toolbar"><div><h3>기본정보</h3><p>Legacy 하위분류는 시스템에서 보존하고, 신규 상업 흐름은 Stable Item Identity를 사용합니다.</p></div>${c.can_edit?'<button class="btn outline" data-edit-master type="button">수정</button>':''}</div><div class="customer-detail-list"><article class="customer-detail-card"><dl><div><dt>업무단계</dt><dd>${escapeHtml(stageLabels[c.business_stage]||'미분류 / Review Required')}</dd></div><div><dt>Master 정리상태</dt><dd>${escapeHtml(maturityLabels[c.master_maturity]||'Review Required')}</dd></div><div><dt>조직 역할</dt><dd>${escapeHtml(roleText)}</dd></div><div><dt>사업분야</dt><dd>${(c.business_units||[]).map(unit=>escapeHtml(businessLabels[unit]||unit)).join(' · ')||'—'}</dd></div><div><dt>취급 Item</dt><dd>${itemRows}</dd></div><div><dt>계약정책</dt><dd>${escapeHtml(c.commercial_context?.contract_policy?((cm.commercialTaxonomy?.contract_policies||[]).find(row=>row.code===c.commercial_context.contract_policy)?.label||c.commercial_context.contract_policy):'Review Required / 미분류')}</dd></div><div><dt>내부 정·부 담당자</dt><dd>${escapeHtml(c.primary_owner_id?((state.users.find(u=>Number(u.id)===Number(c.primary_owner_id))||{}).display_name||'지정'):'미지정')} / ${escapeHtml(c.secondary_owner_id?((state.users.find(u=>Number(u.id)===Number(c.secondary_owner_id))||{}).display_name||'지정'):'미지정')}</dd></div><div><dt>소재국가·권역</dt><dd>${escapeHtml(c.headquarters_country||'—')} · ${escapeHtml(c.sales_region||'미분류')}</dd></div><div><dt>판매 담당국가</dt><dd>${countryRows} ${c.can_edit?'<button class="mini-btn" data-add-sales-country type="button">+ 국가</button>':''}</dd></div><div><dt>주소</dt><dd>${escapeHtml(c.address||'—')}</dd></div><div><dt>홈페이지</dt><dd>${escapeHtml(c.website||'—')}</dd></div><div><dt>비고</dt><dd>${escapeHtml(c.notes||'—')}</dd></div></dl></article></div></section>${detailSection('업체 담당자',c.contacts||[],'contacts','담당자')}`;return;
    }
    if(cm.tab==='overview_legacy'){
      const countryRows=(c.sales_countries||[]).map(row=>`<span class="customer-chip">${escapeHtml(row.country_name)}${row.is_primary?' · 주':''}${c.can_edit?` <button class="mini-btn" data-delete-sales-country="${escapeHtml(row.id)}" type="button">×</button>`:''}</span>`).join(' ')||'등록 없음';
      const reviewRows=(c.review_required_reasons||[]).map(code=>`<span class="customer-chip warning">${escapeHtml({customer_stage:'업무단계',master_maturity:'Master 정리상태',organization_role:'조직 역할',medical_detail:'Medical 상세',contracts:'계약',payment_terms:'결제조건',logistics:'물류조건'}[code]||code)} 확인 필요</span>`).join(' ');
      node.innerHTML=`<section><div class="customer-detail-toolbar"><h3>기본정보·정책 검토</h3>${c.can_edit?'<button class="btn outline" data-edit-master type="button">수정</button>':''}</div>${reviewRows?`<div class="customer-policy-review">${reviewRows}</div>`:'<div class="customer-policy-complete">정책 확인이 완료되었습니다.</div>'}<div class="customer-detail-list"><article class="customer-detail-card"><dl><div><dt>업무단계</dt><dd>${escapeHtml(stageLabels[c.business_stage]||'미분류 / Review Required')}</dd></div><div><dt>Master 정리상태</dt><dd>${escapeHtml(maturityLabels[c.master_maturity]||'Review Required')} · ERP 연결과 별도</dd></div><div><dt>조직 역할</dt><dd>${escapeHtml(roleText)}${c.organization_roles?.length?'':' · Legacy Candidate'}</dd></div><div><dt>관리 소재국가·권역</dt><dd>${escapeHtml(c.headquarters_country||'—')} · ${escapeHtml(c.sales_region||'미분류')}</dd></div><div><dt>정·부 담당자</dt><dd>${escapeHtml(c.primary_owner_id?((state.users.find(u=>Number(u.id)===Number(c.primary_owner_id))||{}).display_name||'지정'):'미지정')} / ${escapeHtml(c.secondary_owner_id?((state.users.find(u=>Number(u.id)===Number(c.secondary_owner_id))||{}).display_name||'지정'):'미지정')}</dd></div><div><dt>상세 사업분야</dt><dd>${(c.business_area_details||[]).map(unit=>escapeHtml(businessDetailLabels[unit]||unit)).join(' · ')||'—'}</dd></div><div><dt>사용 언어</dt><dd>${(c.language_codes||[]).map(code=>escapeHtml(taxonomyLabel('languages',code))).join(' · ')||escapeHtml(c.preferred_language||'—')}</dd></div><div><dt>Timezone</dt><dd>${escapeHtml(c.timezone_name||'—')}</dd></div><div><dt>판매 담당국가</dt><dd>${countryRows} ${c.can_edit?'<button class="mini-btn" data-add-sales-country type="button">+ 국가</button>':''}</dd></div><div><dt>주소</dt><dd>${escapeHtml(c.address||'—')}</dd></div><div><dt>홈페이지</dt><dd>${escapeHtml(c.website||'—')}</dd></div><div><dt>비고</dt><dd>${escapeHtml(c.notes||'—')}</dd></div></dl></article></div></section>${detailSection('업체 담당자',c.contacts||[],'contacts','담당자')}`;return;
    }
    if(cm.tab==='contracts_products'){
      node.innerHTML=`<div class="customer-context-note"><strong>계약 제품</strong>은 계약 범위이고, <strong>고객별 가격·FOC·MOQ</strong>는 별도 조건 원장입니다.</div>${detailSection('계약·계약제품',c.contracts||[],'contracts','계약')}${detailSection('고객별 가격·FOC·MOQ',c.product_terms||[],'product-terms','제품조건')}`;return;
    }
    if(cm.tab==='sales_terms'){
      const countryRows=(c.sales_countries||[]).map(row=>`<span class="customer-chip">${escapeHtml(row.country_name)}${row.is_primary?' · 주':''}${c.can_edit?` <button class="mini-btn" data-delete-sales-country="${escapeHtml(row.id)}" type="button">×</button>`:''}</span>`).join(' ')||'등록 없음';
      node.innerHTML=`<section><div class="customer-detail-toolbar"><h3>영업 분류·판매국가</h3>${c.can_edit?'<button class="btn outline" data-edit-master type="button">수정</button>':''}</div><article class="customer-detail-card"><dl><div><dt>조직 역할</dt><dd>${escapeHtml(roleText)}</dd></div><div><dt>상세 사업분야</dt><dd>${(c.business_area_details||[]).map(code=>escapeHtml(businessDetailLabels[code]||code)).join(' · ')||'—'}</dd></div><div><dt>판매 담당국가</dt><dd>${countryRows} ${c.can_edit?'<button class="mini-btn" data-add-sales-country type="button">+ 국가</button>':''}</dd></div></dl></article></section>${detailSection('결제·여신조건',c.payment_terms||[],'payment-terms','결제조건')}${detailSection('Customer Sales Plan',c.sales_plans||[],'sales-plans','사업계획')}`;return;
    }
    if(cm.tab==='logistics'){node.innerHTML=detailSection('물류·통관 Default',c.logistics||[],'logistics','물류조건');return;}
    if(cm.tab==='registrations'){node.innerHTML=detailSection('제품별 인허가',c.registrations||[],'registrations','인허가');return;}
    if(cm.tab==='activities'){
      const taskRows=(c.major_tasks||[]).map(task=>`<button type="button" class="customer-map-account" data-major-task-id="${escapeHtml(task.id)}"><strong>${escapeHtml(task.title)}</strong><span>진행위험도 ${escapeHtml(({green:'정상',amber:'주의',red:'위험'})[task.final_rag||'green'])} · ${escapeHtml(task.owner_name||'담당자 미지정')} · ${formatDate(task.hard_deadline_date||task.current_target_date)}</span></button>`).join('')||'<div class="empty-state">내부 UUID로 연결된 미결 주요업무가 없습니다.</div>';
      const promotionRows=(c.promotions||[]).map(row=>detailCard({...row,payload_json:undefined})).join('')||'<div class="empty-state">연결된 프로모션이 없습니다.</div>';
      node.innerHTML=`<section><div class="customer-detail-toolbar"><h3>관련 미결 주요업무</h3></div><div class="customer-detail-list">${taskRows}</div></section>${detailSection('미팅·이슈',c.meetings||[],'meetings','미팅')}${detailSection('제품교육',c.education||[],'education','교육')}${detailSection('홍보물 지원',c.marketing||[],'marketing','지원내역')}<section><div class="customer-detail-toolbar"><h3>기존 프로모션 연결</h3></div><div class="customer-detail-list">${promotionRows}</div></section>`;return;
    }
    if(cm.tab==='system'){
      const shipments=(c.recent_shipments||[]).map(row=>`<article class="customer-detail-card"><header><strong>${escapeHtml(row.issue_no)}</strong><small>${formatDate(row.ship_date)}</small></header><dl><div><dt>품목</dt><dd>${escapeHtml(row.product_name)}</dd></div><div><dt>수량</dt><dd>${formatNumber(row.quantity,2)}</dd></div><div><dt>외화금액</dt><dd>${escapeHtml(row.currency)} ${formatNumber(row.foreign_amount,2)}</dd></div><div><dt>공급가</dt><dd>${cmMoney(row.krw_supply)}</dd></div></dl></article>`).join('')||'<div class="empty-state">ERP 코드로 연결된 출고가 없습니다.</div>';
      const odm=(c.odm_projects||[]).map(project=>`${detailCard(project,'odm-projects')}<article class="customer-detail-card"><header><strong>ODM 최종 공급국가</strong>${c.can_edit?`<button class="mini-btn" data-add-odm-country="${escapeHtml(project.id)}" type="button">+ 국가</button>`:''}</header><p>${(project.supply_countries||[]).map(row=>`${escapeHtml(row.country_name)} · ${escapeHtml(row.supply_status)}`).join(' / ')||'등록 없음'}</p></article>`).join('')||`<div class="empty-state">등록된 ODM 프로젝트가 없습니다.${c.can_edit?' <button class="mini-btn" data-add-detail="odm-projects" type="button">+ ODM 프로젝트 추가</button>':''}</div>`;
      const audit=(c.audit||[]).map(row=>`<article class="customer-detail-card"><header><strong>${escapeHtml(row.action)}</strong><small>${formatDate(row.occurred_at,true)} · ${escapeHtml(row.actor_username)}</small></header><p>${escapeHtml(row.summary)}</p></article>`).join('')||'<div class="empty-state">변경이력이 없습니다.</div>';
      node.innerHTML=`<section><div class="customer-detail-toolbar"><h3>시스템 정보</h3></div><article class="customer-detail-card system-card"><dl><div><dt>내부 UUID</dt><dd>${escapeHtml(c.id)}</dd></div><div><dt>표시 ID</dt><dd>${escapeHtml(c.customer_id)}</dd></div><div><dt>ERP ID</dt><dd>${escapeHtml(c.erp_partner_code||'미연결')}</dd></div><div><dt>ERP 원본명</dt><dd>${escapeHtml(c.erp_original_name||'—')}</dd></div><div><dt>ERP 원본국가</dt><dd>${escapeHtml(c.erp_country_name||'—')}</dd></div><div><dt>Version</dt><dd>${formatNumber(c.version)}</dd></div></dl></article></section><section><div class="customer-detail-toolbar"><h3>ERP 출고 이력</h3></div><div class="customer-detail-list">${shipments}</div></section><section><div class="customer-detail-toolbar"><h3>ODM 프로젝트</h3>${c.can_edit?'<button class="btn outline" data-add-detail="odm-projects" type="button">+ 추가</button>':''}</div><div class="customer-detail-list">${odm}</div></section>${detailSection('경쟁제품',c.competitors||[],'competitors','경쟁제품')}<section><div class="customer-detail-toolbar"><h3>변경이력</h3></div><div class="customer-detail-list">${audit}</div></section>`;return;
    }
  }
  function detailSection(title,rows,kind,emptyLabel='정보'){const action=kind&&cm.detail.can_edit?`<button class="btn outline" data-add-detail="${kind}" type="button">+ 추가</button>`:'';return `<section><div class="customer-detail-toolbar"><h3>${escapeHtml(title)}</h3>${action}</div><div class="customer-detail-list">${rows.map(item=>detailCard(item,kind)).join('')||`<div class="empty-state">등록된 ${escapeHtml(emptyLabel)}이(가) 없습니다. ${action}</div>`}</div></section>`;}
  function fieldInput(name){
    const label=fieldLabels[name]||name;
    if(boolFields.has(name))return `<label><span>${escapeHtml(label)}</span><input name="${name}" type="checkbox"></label>`;
    if(name==='payment_method_code')return `<label>${escapeHtml(label)}<select name="${name}" required><option value="">선택</option>${(cm.taxonomy?.payment_methods||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='courier_code')return `<label>${escapeHtml(label)}<select name="${name}"><option value="">미지정</option>${(cm.taxonomy?.couriers||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='contract_status_code')return `<label>${escapeHtml(label)}<select name="${name}" required><option value="">선택</option>${(cm.taxonomy?.contract_statuses||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='exclusivity')return `<label>${escapeHtml(label)}<select name="${name}" required><option value="">선택</option>${(cm.taxonomy?.contract_exclusivities||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='interim_product_codes')return `<fieldset class="full customer-document-options"><legend>${escapeHtml(label)} · 복수선택</legend>${(cm.taxonomy?.interim_contract_products||[]).map(item=>`<label><input name="interim_product_codes" type="checkbox" value="${item.code}"> ${escapeHtml(item.label)}</label>`).join('')}</fieldset>`;
    if(name==='territory_country_codes')return `<label class="full">${escapeHtml(label)} · 복수선택<select name="territory_country_codes" multiple size="7">${(cm.taxonomy?.countries||[]).map(item=>`<option value="${escapeHtml(item.code)}">${escapeHtml(item.name)} · ${escapeHtml(item.label||item.name)}</option>`).join('')}</select><small>기존 Territory 원문은 자동 변환하지 않고 별도로 보존됩니다.</small></label>`;
    if(name==='interim_product_code')return `<label>${escapeHtml(label)}<select name="${name}" required><option value="">선택</option>${(cm.taxonomy?.interim_contract_products||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='language_code')return `<label>${escapeHtml(label)}<select name="${name}"><option value="">미지정</option>${(cm.taxonomy?.languages||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='employment_status')return `<label>${escapeHtml(label)}<select name="${name}">${(cm.taxonomy?.contact_employment_statuses||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='importance')return `<label>${escapeHtml(label)}<select name="${name}"><option value="">미지정</option>${(cm.taxonomy?.meeting_importance||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='action_status')return `<label>${escapeHtml(label)}<select name="${name}">${(cm.taxonomy?.meeting_action_statuses||[]).map(item=>`<option value="${item.code}">${escapeHtml(item.label)}</option>`).join('')}</select></label>`;
    if(name==='country_name')return `<label>${escapeHtml(label)}<select name="${name}" required><option value="">국가 선택</option>${(cm.taxonomy?.countries||[]).map(item=>`<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} · ${escapeHtml(item.label||item.name)}</option>`).join('')}</select></label>`;
    if(name==='payment_schedule_json')return `<div class="full customer-payment-schedule"><div class="customer-payment-schedule-head"><div><strong>${escapeHtml(label)}</strong><small>단계 수는 자유롭게 조정할 수 있으며 비율 합계는 100%여야 합니다.</small></div><button class="mini-btn" data-payment-schedule-add type="button">+ 단계 추가</button></div><div id="customerPaymentScheduleRows"></div></div>`;
    if(name==='additional_documents_json')return `<fieldset class="full customer-document-options"><legend>${escapeHtml(label)}</legend>${(cm.taxonomy?.additional_documents||[]).map(item=>`<label><input name="additional_documents" type="checkbox" value="${item.code}"> ${escapeHtml(item.label)}</label>`).join('')}</fieldset>`;
    if(name==='moq_basis')return `<label>${escapeHtml(label)}<select name="${name}" required><option value="">선택</option><option value="paid">유상수량 기준</option><option value="total_supply">유상+FOC 총공급수량 기준</option></select></label>`;
    if(name==='business_unit')return `<label>${escapeHtml(label)}<select name="${name}"><option value="medical">메디컬</option><option value="dental">덴탈</option><option value="aesthetic">에스테틱</option></select></label>`;
    if(name==='currency')return `<label>${escapeHtml(label)}<select name="${name}"><option>USD</option><option>EUR</option><option>JPY</option><option>CNH</option><option>KRW</option></select></label>`;
    if(name==='owner_id')return `<label>${escapeHtml(label)}<select name="${name}">${userOptions()}</select></label>`;
    if(name==='product_name')return `<label>${escapeHtml(label)}<input name="${name}" list="customerProductOptions" type="text"></label>`;
    if(name==='installments_json')return `<label class="full">${escapeHtml(label)}<textarea name="${name}" rows="2" placeholder='[{"label":"1차","days":30,"ratio":50}]'></textarea></label>`;
    if(name==='notes'||name.endsWith('_notes')||['discussion','decisions','issue_text','next_action','packaging_label','required_documents','additional_documents_note','customs_invoice_notes'].includes(name))return `<label class="full">${escapeHtml(label)}<textarea name="${name}" rows="3"></textarea></label>`;
    const type=dateFields.has(name)?'date':numericFields.has(name)?'number':name==='email'?'email':name==='phone'?'tel':'text';
    const required=['contract_name','start_date','end_date'].includes(name)?'required':'';
    return `<label>${escapeHtml(label)}<input name="${name}" type="${type}" ${numericFields.has(name)?'step="0.01"':''} ${required}></label>`;
  }
  function paymentTriggerOptions(selected=''){
    return '<option value="">시점 선택</option>'+(cm.taxonomy?.payment_triggers||[]).map(item=>`<option value="${item.code}" ${item.code===selected?'selected':''}>${escapeHtml(item.label)}</option>`).join('');
  }
  function paymentScheduleRows(form,compact=false){
    const rows=[...form.querySelectorAll('[data-payment-schedule-row]')].map((row,index)=>({sequence:index+1,percentage:row.querySelector('[data-payment-percentage]').value,trigger:row.querySelector('[data-payment-trigger]').value,note:row.querySelector('[data-payment-note]').value}));
    return compact?rows.filter(row=>row.percentage!==''||row.trigger||row.note.trim()):rows;
  }
  function renderPaymentScheduleRows(rows){
    const node=$("#customerPaymentScheduleRows");if(!node)return;
    node.innerHTML=rows.length?rows.map((row,index)=>`<div class="customer-payment-schedule-row" data-payment-schedule-row><span class="customer-payment-sequence">${index+1}</span><input data-payment-percentage type="number" min="0" max="100" step="0.01" value="${escapeHtml(row.percentage??'')}" placeholder="비율 %" aria-label="${index+1}단계 비율"><select data-payment-trigger aria-label="${index+1}단계 지급시점">${paymentTriggerOptions(row.trigger||'')}</select><input data-payment-note maxlength="500" value="${escapeHtml(row.note||'')}" placeholder="조건/비고" aria-label="${index+1}단계 비고"><div class="customer-payment-row-actions"><button class="mini-btn" data-payment-schedule-move="-1" data-payment-index="${index}" type="button" ${index===0?'disabled':''} aria-label="위로 이동">↑</button><button class="mini-btn" data-payment-schedule-move="1" data-payment-index="${index}" type="button" ${index===rows.length-1?'disabled':''} aria-label="아래로 이동">↓</button><button class="mini-btn danger" data-payment-schedule-remove data-payment-index="${index}" type="button" aria-label="단계 삭제">−</button></div></div>`).join(''):'<div class="empty-state compact">등록된 지급단계가 없습니다. ‘+ 단계 추가’를 눌러 주세요.</div>';
  }
  function editPaymentSchedule(action,index=null,direction=0){
    const form=$("#customerDetailEditForm"),rows=paymentScheduleRows(form);
    if(action==='add')rows.push({percentage:'',trigger:'',note:''});
    if(action==='remove')rows.splice(index,1);
    if(action==='move'){
      const target=index+direction;if(target<0||target>=rows.length)return;
      [rows[index],rows[target]]=[rows[target],rows[index]];
    }
    renderPaymentScheduleRows(rows);updateDetailDirty();
  }
  function detailItems(kind){return cm.detail?.[kind.replaceAll('-','_')]||[];}
  function detailFormPayload(form,withConcurrency=true){
    const data=new FormData(form),kind=data.get('kind'),body={};
    (detailFields[kind]||[]).forEach(name=>{
      if(name==='payment_schedule_json')body[name]=paymentScheduleRows(form,true).map((row,index)=>({sequence:index+1,percentage:row.percentage===''?0:Number(row.percentage),trigger:row.trigger,note:row.note}));
      else if(name==='additional_documents_json')body[name]=data.getAll('additional_documents');
      else if(['interim_product_codes','territory_country_codes'].includes(name))body[name]=data.getAll(name);
      else if(boolFields.has(name))body[name]=Boolean(form.elements[name]?.checked);
      else if(numericFields.has(name))body[name]=data.get(name)===''?0:Number(data.get(name));
      else body[name]=data.get(name)||'';
    });
    if(withConcurrency&&data.get('row_id')&&cm.detailOriginal?.item?.updated_at)body.expected_updated_at=cm.detailOriginal.item.updated_at;
    return body;
  }
  function detailFingerprint(form){return JSON.stringify(detailFormPayload(form,false));}
  function updateDetailDirty(){
    const form=$("#customerDetailEditForm");if(!form||!cm.detailOriginal)return;
    const changed=!cm.detailOriginal.item||detailFingerprint(form)!==cm.detailOriginal.fingerprint;
    form.classList.toggle('is-dirty',changed);$("#customerDetailDirtyState").textContent=changed?(cm.detailOriginal.item?'저장하지 않은 변경사항이 있습니다.':'새 정보를 입력하고 있습니다.'):'변경사항 없음';
  }
  function clearFieldErrors(form){form.querySelectorAll('.customer-field-error').forEach(node=>node.remove());form.querySelectorAll('.field-invalid').forEach(node=>node.classList.remove('field-invalid'));}
  function showFormError(form,summarySelector,error){
    clearFieldErrors(form);$(summarySelector).textContent=error.message;
    const field=error.data?.field;if(!field)return;
    let input=form.elements[field];if(input&&input.length&&!input.tagName)input=input[0];
    let wrapper=input?.closest('label,fieldset');
    if(!wrapper&&field==='payment_schedule_json')wrapper=form.querySelector('.customer-payment-schedule');
    if(!wrapper&&field==='interim_product_codes')wrapper=form.querySelector('input[name="interim_product_codes"]')?.closest('fieldset');
    if(wrapper){wrapper.classList.add('field-invalid');wrapper.insertAdjacentHTML('beforeend',`<small class="customer-field-error">${escapeHtml(error.message)}</small>`);input?.focus();}
  }
  function openDetailEdit(kind,item=null){
    const form=$("#customerDetailEditForm");form.reset();form.elements.customer_id.value=cm.detail.id;form.elements.kind.value=kind;form.elements.row_id.value=item?.id||'';$("#customerDetailEditTitle").textContent=`${kindLabels[kind]||kind} ${item?'수정':'등록'}`;$("#customerDetailEditFields").innerHTML=(detailFields[kind]||[]).map(fieldInput).join('');
    (detailFields[kind]||[]).forEach(name=>{const field=form.elements[name];if(!field||!item)return;if(boolFields.has(name))field.checked=Boolean(Number(item[name]));else field.value=item[name]??'';});
    if(item&&kind==='contracts'){
      [...form.querySelectorAll('input[name="interim_product_codes"]')].forEach(input=>input.checked=(item.interim_product_codes||[]).includes(input.value));
      [...form.elements.territory_country_codes.options].forEach(option=>option.selected=(item.territory_country_codes||[]).includes(option.value));
      const raw=[['기존 계약유형',item.contract_type],['기존 계약상태',item.contract_status],['기존 Territory',item.territory],['기존 제품범위',item.products_scope]].filter(([,value])=>value);
      if(raw.length)$("#customerDetailEditFields").insertAdjacentHTML('afterbegin',`<div class="full customer-legacy-notice"><strong>Legacy Raw · 자동 변환하지 않음</strong>${raw.map(([label,value])=>`<span>${escapeHtml(label)}: ${escapeHtml(value)}</span>`).join('')}</div>`);
    }
    if(kind==='payment-terms'){
      let schedule=[];if(item){try{schedule=JSON.parse(item.payment_schedule_json||'[]');}catch(_){schedule=[];}}
      renderPaymentScheduleRows(schedule.length?schedule:[{percentage:'',trigger:'',note:''}]);
    }
    if(item&&kind==='logistics'){let documents=[];try{documents=JSON.parse(item.additional_documents_json||'[]');}catch(_){}[...form.querySelectorAll('input[name="additional_documents"]')].forEach(input=>input.checked=documents.includes(input.value));}
    $("#customerDetailEditError").textContent='';clearFieldErrors(form);cm.detailOriginal={item:item?JSON.parse(JSON.stringify(item)):null,fingerprint:detailFingerprint(form)};updateDetailDirty();$("#customerDetailEditDialog").showModal();form.querySelectorAll('select').forEach(select=>select.dataset.searchable='');window.SearchablePicker?.enhanceAll(form);
  }
  async function saveDetail(event){event.preventDefault();const form=event.currentTarget,data=new FormData(form),customerId=data.get('customer_id'),kind=data.get('kind'),rowId=data.get('row_id'),body=detailFormPayload(form);if(kind==='contracts'&&!body.interim_product_codes.length){return showFormError(form,"#customerDetailEditError",{message:'계약 제품을 하나 이상 선택하세요.',data:{field:'interim_product_codes'}});}if(rowId&&detailFingerprint(form)===cm.detailOriginal?.fingerprint){toast('변경된 정보가 없습니다.');$("#customerDetailEditDialog").close();return;}const button=form.querySelector('button[type="submit"]');button.disabled=true;$("#customerDetailEditError").textContent='';clearFieldErrors(form);try{const result=await api(`/api/customer-master/${customerId}/details/${kind}${rowId?`/${rowId}`:''}`,{method:rowId?'PATCH':'POST',body});$("#customerDetailEditDialog").close();toast(result.message);await openDetail(customerId);cm.tab=kindGroup[kind]||'overview';renderDetail();cm.loaded=false;await load(true);}catch(error){showFormError(form,"#customerDetailEditError",error);}finally{button.disabled=false;}}
  async function deleteDetail(kind,rowId){if(!window.confirm('이 상세정보를 종료할까요? 데이터와 변경이력은 보존됩니다.'))return;const item=detailItems(kind).find(row=>row.id===rowId);try{const result=await api(`/api/customer-master/${cm.detail.id}/details/${kind}/${rowId}`,{method:'DELETE',body:{expected_updated_at:item?.updated_at}});toast(result.message);const currentTab=cm.tab;await openDetail(cm.detail.id);cm.tab=currentTab;renderDetail();cm.loaded=false;await load(true);}catch(error){toast(error.message,'error');}}
  function openStatus(mode){const form=$("#customerStatusForm");form.reset();form.elements.customer_id.value=cm.detail.id;form.elements.mode.value=mode;const restore=mode==='restore';$("#customerStatusTitle").textContent=restore?'거래처 복원':'거래중단 처리';$("#customerDeactivateFields").classList.toggle('hidden',restore);$("#customerRestoreFields").classList.toggle('hidden',!restore);form.elements.business_stage.required=restore;form.elements.restore_reason.required=restore;form.elements.inactive_reason.required=!restore;form.elements.inactive_date.value=todayIso();$("#customerStatusError").textContent='';$("#customerStatusDialog").showModal();}
  async function saveStatus(event){event.preventDefault();const data=new FormData(event.currentTarget),id=data.get('customer_id'),mode=data.get('mode'),body=Object.fromEntries(data.entries());try{const result=await api(`/api/customer-master/${id}/${mode==='restore'?'restore':'deactivate'}`,{method:'POST',body});$("#customerStatusDialog").close();$("#customerDetailDialog").close();toast(result.message);cm.loaded=false;await load(true);}catch(error){$("#customerStatusError").textContent=error.message;}}
  async function syncCustomers(){if(!window.confirm('현재 저장된 ERP 해외 출고 원장에서 거래처 코드를 기준으로 동기화할까요? ERP에는 쓰지 않습니다.'))return;const button=$("#customerErpSyncBtn");button.disabled=true;button.textContent='동기화 중…';try{const result=await api('/api/customer-master/sync',{method:'POST',body:{}});toast(result.message);cm.loaded=false;await load(true);await openSyncHistory();}catch(error){toast(error.message,'error');}finally{button.disabled=false;button.textContent='ERP 거래처 동기화';}}
  async function openSyncHistory(){try{const data=await api('/api/customer-master/sync-history');$("#customerSyncHistoryContent").innerHTML=`<div class="customer-sync-runs">${(data.runs||[]).map(row=>`<div class="customer-sync-run"><div><span>실행일시</span><strong>${formatDate(row.finished_at||row.started_at,true)}</strong></div><div><span>해외 코드</span><strong>${formatNumber(row.overseas_partner_count)}</strong></div><div><span>신규</span><strong>${formatNumber(row.created_count)}</strong></div><div><span>갱신</span><strong>${formatNumber(row.updated_count)}</strong></div><div><span>중복</span><strong>${formatNumber(row.duplicate_review_count)}</strong></div><div><span>Domestic 제외</span><strong>${row.domestic_excluded_partner_count==null?'확인 대기':`${formatNumber(row.domestic_excluded_partner_count)}개`}</strong><small>${row.domestic_excluded_partner_count==null&&Number(row.domestic_excluded_count||0)>0?`출고 헤더 ${formatNumber(row.domestic_excluded_count)}건 제외`:'거래처 코드 기준'}</small></div><div><span>오류</span><strong>${formatNumber(row.error_count)}</strong></div></div>`).join('')||'<div class="empty-state">동기화 이력이 없습니다.</div>'}</div><section class="customer-review-list"><h3>담당자 검토 필요 ${(data.reviews||[]).length}건</h3>${(data.reviews||[]).map(row=>`<div class="customer-review-item"><strong>${escapeHtml(row.erp_partner_name||row.erp_partner_code||row.external_key)}</strong><span>${escapeHtml(row.reason)}</span></div>`).join('')}</section>`;$("#customerSyncDialog").showModal();}catch(error){toast(error.message,'error');}}
  function openCountryRelation(context,projectId=''){
    const form=$("#customerCountryRelationForm");form.reset();form.elements.context.value=context;form.elements.project_id.value=projectId;
    form.elements.country_name.innerHTML='<option value="">국가 선택</option>'+(cm.taxonomy?.countries||[]).map(item=>`<option value="${escapeHtml(item.name)}">${escapeHtml(item.label||item.name)}</option>`).join('');
    const sales=context==='sales';$("#customerCountryRelationTitle").textContent=sales?'판매 담당국가 등록':'ODM 최종 공급국가 등록';$("#customerCountryPrimaryField").classList.toggle('hidden',!sales);$("#customerCountryRelationError").textContent='';$("#customerCountryRelationDialog").showModal();form.elements.country_name.dataset.searchable='';window.SearchablePicker?.enhance(form.elements.country_name);window.SearchablePicker?.refresh(form.elements.country_name);
  }
  async function saveCountryRelation(event){
    event.preventDefault();const form=event.currentTarget,data=new FormData(form),context=data.get('context'),countryName=data.get('country_name'),projectId=data.get('project_id');
    try{
      const path=context==='sales'?`/api/customer-master/${cm.detail.id}/sales-countries`:`/api/customer-master/${cm.detail.id}/odm-projects/${projectId}/countries`;
      const body=context==='sales'?{country_name:countryName,is_primary:form.elements.is_primary.checked}:{country_name:countryName,supply_status:'planned'};
      const result=await api(path,{method:'POST',body});$("#customerCountryRelationDialog").close();toast(result.message);const currentTab=cm.tab;await openDetail(cm.detail.id);cm.tab=currentTab;renderDetail();if(context!=='sales')await loadMap();
    }catch(error){$("#customerCountryRelationError").textContent=error.message;}
  }
  async function deleteSalesCountry(rowId){
    if(!window.confirm('이 판매 담당국가를 제외할까요?'))return;
    try{const result=await api(`/api/customer-master/${cm.detail.id}/sales-countries/${rowId}`,{method:'DELETE'});toast(result.message);await openDetail(cm.detail.id);}
    catch(error){toast(error.message,'error');}
  }
  async function linkErp(){
    const code=window.prompt('연결할 ERP 거래처 코드(trCd)를 입력하세요.');if(!code)return;
    const message=`현재 거래처 '${cm.detail.display_name}'에 ERP 코드 ${code}를 연결합니다. 내부 UUID와 과거 이력은 유지됩니다. 확정할까요?`;
    if(!window.confirm(message))return;
    try{const result=await api(`/api/customer-master/${cm.detail.id}/link-erp`,{method:'POST',body:{erp_partner_code:code,confirmed:true,comparison:{display_name:cm.detail.display_name,previous_erp_code:cm.detail.erp_partner_code||''}}});toast(result.message);cm.loaded=false;await load(true);await openDetail(cm.detail.id);}
    catch(error){toast(error.message,'error');}
  }
  function handleCustomerClick(event){const target=event.target.closest('[data-customer-id]');if(target)openDetail(target.dataset.customerId);}
  function syncHeadquartersRegion(event){const selected=(cm.taxonomy?.countries||[]).find(item=>item.name===event.target.value);if(selected)event.target.form.elements.sales_region.value=selected.sales_region||'미분류';}
  function filterChanged(){cm.page=1;renderLists();}
  function bind(){
    $("#customerAddBtn").addEventListener('click',()=>openMasterForm());$("#customerMasterForm").addEventListener('submit',saveMaster);$("#customerErpSyncBtn").addEventListener('click',syncCustomers);$("#customerSyncHistoryBtn").addEventListener('click',openSyncHistory);
    ['customerMasterSearch','customerSourceFilter','customerRegionFilter','customerCountryFilter','customerBusinessFilter','customerOwnerFilter','customerOrganizationRoleFilter','customerContractFilter','customerStageFilter','customerPerPage','customerReviewFilter','customerIncompleteFilter'].forEach(id=>$("#"+id).addEventListener(id==='customerMasterSearch'?'input':'change',filterChanged));
    $("#customerMasterForm").elements.headquarters_country.addEventListener('change',syncHeadquartersRegion);
    $("#customerMasterForm").elements.business_units.addEventListener('change',()=>syncMasterItemScope(true));
    $("#customerPagination").addEventListener('click',event=>{const button=event.target.closest('[data-customer-page]');if(!button)return;cm.page=Number(button.dataset.customerPage);renderLists();});
    $("#customerActiveRegions").addEventListener('click',handleCustomerClick);$("#customerInactiveList").addEventListener('click',handleCustomerClick);$("#customerMapDetail").addEventListener('click',handleCustomerClick);
    $("#customerMapSegments").addEventListener('click',event=>{const button=event.target.closest('[data-customer-map-segment]');if(!button)return;cm.segment=button.dataset.customerMapSegment;cm.mapSelected=null;[...$("#customerMapSegments").querySelectorAll('button')].forEach(node=>node.classList.toggle('active',node===button));loadMap();});
    $("#customerWorldMap").addEventListener('click',event=>{const target=event.target.closest('[data-cm-map-id]');if(!target)return;cm.mapSelected=target.dataset.cmMapId;const country=(cm.map?.countries||[]).find(row=>String(row.country_code||'').padStart(3,'0')===cm.mapSelected);if(country){$("#customerCountryFilter").value=country.country_name;$("#customerBusinessFilter").value=cm.segment;renderLists();}renderMap();});
    $("#customerDetailTabs").addEventListener('click',event=>{const button=event.target.closest('[data-customer-tab]');if(!button)return;cm.tab=button.dataset.customerTab;renderDetail();});
    $("#customerDetailContent").addEventListener('click',event=>{
      if(window.CommercialContextUI?.handleClick(event,async()=>{const tab=cm.tab;await openDetail(cm.detail.id);cm.tab=tab;renderDetail();cm.loaded=false;await load(true);} ))return;
      const editMaster=event.target.closest('[data-edit-master]');if(editMaster)return openMasterForm(cm.detail);
      const add=event.target.closest('[data-add-detail]');if(add)return openDetailEdit(add.dataset.addDetail);
      const edit=event.target.closest('[data-edit-detail]');if(edit)return openDetailEdit(edit.dataset.editDetail,detailItems(edit.dataset.editDetail).find(item=>item.id===edit.dataset.rowId));
      const remove=event.target.closest('[data-delete-detail]');if(remove)return deleteDetail(remove.dataset.deleteDetail,remove.dataset.rowId);
      const addCountry=event.target.closest('[data-add-sales-country]');if(addCountry)return openCountryRelation('sales');
      const removeCountry=event.target.closest('[data-delete-sales-country]');if(removeCountry)return deleteSalesCountry(removeCountry.dataset.deleteSalesCountry);
      const odmCountry=event.target.closest('[data-add-odm-country]');if(odmCountry)return openCountryRelation('odm',odmCountry.dataset.addOdmCountry);
      const majorTask=event.target.closest('[data-major-task-id]');if(majorTask&&window.MajorTasksUI){$("#customerDetailDialog").close();switchView("task");return window.MajorTasksUI.openById(majorTask.dataset.majorTaskId);}
    });
    $("#customerLinkErpBtn").addEventListener('click',linkErp);$("#customerCountryRelationForm").addEventListener('submit',saveCountryRelation);
    $("#customerDetailEditFields").addEventListener('click',event=>{
      const add=event.target.closest('[data-payment-schedule-add]');if(add)return editPaymentSchedule('add');
      const remove=event.target.closest('[data-payment-schedule-remove]');if(remove)return editPaymentSchedule('remove',Number(remove.dataset.paymentIndex));
      const move=event.target.closest('[data-payment-schedule-move]');if(move)return editPaymentSchedule('move',Number(move.dataset.paymentIndex),Number(move.dataset.paymentScheduleMove));
    });
    $("#customerMasterForm").addEventListener('input',updateMasterDirty);$("#customerMasterForm").addEventListener('change',updateMasterDirty);
    $("#customerDetailEditFields").addEventListener('input',updateDetailDirty);$("#customerDetailEditFields").addEventListener('change',updateDetailDirty);
    $("#customerEditBtn").addEventListener('click',()=>openMasterForm(cm.detail));$("#customerDeactivateBtn").addEventListener('click',()=>openStatus('deactivate'));$("#customerRestoreBtn").addEventListener('click',()=>openStatus('restore'));$("#customerStatusForm").addEventListener('submit',saveStatus);$("#customerDetailEditForm").addEventListener('submit',saveDetail);window.CommercialContextUI?.bind();
  }
  window.CustomerMasterUI={bind,load,refresh:()=>load(true)};
})();
