/* Exhibition operations: all edits use the Exhibition canonical API. */
(function () {
  'use strict';
  let ctx, options, listing, detail, activeTab='basic', editing=null;
  const seoulToday=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  let filters={year:seoulToday().slice(0,4)},calendarExpanded=false;
  let calendarMonth=seoulToday().slice(0,7);
  let generation=0;
  const root=()=>document.querySelector('#view-exhibition');
  const esc=v=>ctx.escapeHtml(String(v??''));
  const money=n=>'₩'+Number(n||0).toLocaleString('ko-KR');
  const num=n=>Number(n||0).toLocaleString('ko-KR',{maximumFractionDigits:2});
  const writable=()=>Boolean(options?.permissions.write);
  const api=(path,opts)=>ctx.api('/api/exhibitions'+path,opts);
  const tabs=[['basic','기본정보'],['organizer','주관사 / Pavilion'],['support','참가 / 정부지원'],['checklist','사전준비'],['shipments','제품 / 물류'],['travel','출장 / 현지운영'],['booth','Booth / 현장운영'],['meetings','Meeting / Lead'],['sales','판매 / 재고 / 수금'],['expenses','비용'],['return','종료 / 귀국'],['followups','Follow-up / 성과']];
  const label=(key,value)=>options?.choices[key]?.[value]??value??'—';
  const today=()=>listing?.today||seoulToday();
  const utc=d=>{const [y,m,day]=d.split('-').map(Number);return new Date(Date.UTC(y,m-1,day));};
  const iso=d=>[d.getUTCFullYear(),String(d.getUTCMonth()+1).padStart(2,'0'),String(d.getUTCDate()).padStart(2,'0')].join('-');
  const shift=(d,n)=>{const x=utc(d);x.setUTCDate(x.getUTCDate()+n);return iso(x);};
  const notice=(text,error=false)=>ctx.toast(text,error?'error':'success');
  const button=(text,attrs='',className='')=>`<button type="button" class="ex-button ${className}" ${attrs}>${text}</button>`;
  function saveFilters(){try{sessionStorage.setItem('maps:exhibition-filters',JSON.stringify({shared_filters:filters,calendarExpanded,calendarMonth}));}catch(_e){}}
  function init(context){ctx=context;try{const x=JSON.parse(sessionStorage.getItem('maps:exhibition-filters')||'null');if(x){filters={...filters,...(x.shared_filters||(x.mode==='calendar'?x.filters?.calendar:x.filters?.list)||{})};calendarExpanded=!!x.calendarExpanded;if(/^\d{4}-\d{2}$/.test(x.calendarMonth||''))calendarMonth=x.calendarMonth;if(filters.year)calendarMonth=filters.year+'-'+(filters.month||calendarMonth.slice(5));}}catch(_e){} }

  async function load(){
    if(!ctx)return;
    const token=++generation;root().innerHTML='<div class="ex-loading">전시회 현황을 불러오는 중…</div>';
    try{const [o,l]=await Promise.all([api('/options'),api('')]);if(token!==generation)return;options=o;listing=l;renderMain();}
    catch(e){root().innerHTML=`<div class="ex-error">${esc(e.message)} ${button('다시 시도','data-ex-reload')}</div>`;bindMain();}
  }
  function select(name,values,value,placeholder='전체'){
    return `<select name="${esc(name)}" aria-label="${esc(name)}"><option value="">${esc(placeholder)}</option>${Object.entries(values).sort(([a],[b])=>name==='month'?a.localeCompare(b):0).map(([k,v])=>`<option value="${esc(k)}" ${String(value)===String(k)?'selected':''}>${esc(v)}</option>`).join('')}</select>`;
  }
  function filterMarkup(){
    const f=filters, countries=Object.fromEntries([...new Set(listing.items.map(e=>e.country))].sort().map(v=>[v,v]));
    const cities=Object.fromEntries([...new Set(listing.items.map(e=>e.city).filter(Boolean))].sort().map(v=>[v,v]));
    const base=[['participation','참가상태',options.choices.participation],['business_area','사업분야',options.choices.business],['country','국가',countries],['importance','중요도',options.choices.importance],['relationship','행사관계',options.choices.relationship]];
    {
      const years=[...new Set([...Array.from({length:5},(_,i)=>String(Number(seoulToday().slice(0,4))+i-1)),...listing.items.flatMap(e=>[e.start_date.slice(0,4),e.end_date.slice(0,4)]),f.year].filter(Boolean))].sort();
      base.unshift(['year','연도',Object.fromEntries(years.map(v=>[v,v+'년']))],['month','월',Object.fromEntries(Array.from({length:12},(_,i)=>[String(i+1).padStart(2,'0'),(i+1)+'월']))]);
      base.push(['city','도시',cities],['person_id','출장자 / 담당자',Object.fromEntries(options.users.map(u=>[u.id,u.display_name]))],['pavilion','Korean Pavilion',options.choices.tristate]);
    }
    return `<form class="ex-filters" id="exFilters">${base.map(([key,title,vals])=>`<label>${title}${select(key,vals,f[key])}</label>`).join('')}${button('필터 초기화','data-ex-reset')}</form>`;
  }
  function filtered(){const f=filters;return listing.items.filter(e=>{
    // Date-only inclusive overlap, including cross-month/year events.
    if(f.year){const from=f.year+'-'+(f.month||'01')+'-01',to=f.month?shift(iso(new Date(Date.UTC(Number(f.year),Number(f.month),1))),-1):f.year+'-12-31';if(e.end_date<from||e.start_date>to)return false;}
    else if(f.month){let overlap=false;for(let year=Number(e.start_date.slice(0,4));year<=Number(e.end_date.slice(0,4));year++){const from=year+'-'+f.month+'-01',to=shift(iso(new Date(Date.UTC(year,Number(f.month),1))),-1);if(e.end_date>=from&&e.start_date<=to)overlap=true;}if(!overlap)return false;}
    if(['country','city','importance','relationship','participation','pavilion'].some(k=>f[k]&&e[k]!==f[k]))return false;
    if(f.business_area&&!e.business_areas.includes(f.business_area))return false;
    if(f.person_id&&String(e.owner_id)!==f.person_id&&!e.people_ids.map(String).includes(f.person_id))return false;
    return true;
  });}
  function badge(text,style=''){return `<span class="ex-badge ${esc(style)}">${esc(text)}</span>`;}
  function renderMain(){
    const k=listing.kpi;const cards=[['올해 전체 행사',k.total],['참가 확정',k.exhibiting],['참관 확정',k.visiting],['후보',k.candidate],['이번달 행사',k.this_month],['준비업무 기한초과',k.overdue],['Follow-up 미완료',k.followup_open],['올해 예상비용',money(k.budget_krw)],['올해 실제비용',money(k.actual_krw)]];
    root().innerHTML=`<div class="ex-heading"><div><h2>전시회 / Exhibition</h2><p>행사 결정부터 준비, 현장운영, 귀국 후 Follow-up까지</p></div><div>${writable()?button('체크리스트 기준 관리','data-ex-templates')+button('+ 행사 등록','data-ex-new','primary'):badge('읽기 전용')}</div></div><div class="ex-kpis">${cards.map(([t,v])=>`<article><span>${t}</span><strong>${v}</strong></article>`).join('')}</div><section class="ex-calendar-panel ${calendarExpanded?'expanded':'compact'}" aria-label="전시회 Calendar">${calendarMarkup()}</section><div class="ex-toolbar"><small>Calendar와 List에 같은 필터가 적용됩니다.</small>${button('새로고침','data-ex-reload')}</div>${filterMarkup()}<div id="exResults">${listMarkup()}</div>`;
    bindMain();
  }
  function listMarkup(){
    const rows=filtered(),groups={};for(const e of rows)(groups[e.start_date.slice(0,7)]??=[]).push(e);
    if(!rows.length)return '<div class="ex-empty">표시할 전시회가 없습니다. 필터를 변경하거나 행사를 등록하세요.</div>';
    return Object.entries(groups).map(([month,items])=>`<details class="ex-month" open><summary>${month.slice(0,4)}년 ${Number(month.slice(5))}월 · ${items.length}개 행사</summary><div class="ex-table-wrap"><table class="ex-table"><thead><tr>${['일정','행사명','국가 / 도시','사업분야','중요도','행사관계','참가상태','Korean Pavilion','출장인원','준비현황','제품 / 물류','예상 / 실제비용','Follow-up','비고'].map(t=>`<th>${t}</th>`).join('')}</tr></thead><tbody>${items.map(e=>{const s=e.summary;return `<tr><td class="ex-date">${esc(e.start_date.slice(5))}~${esc(e.end_date.slice(5))}<small>${s.days_to_start>=0?'D-'+s.days_to_start:'D+'+Math.abs(s.days_to_start)}</small></td><td>${button(esc(e.name),`data-ex-open="${e.id}"`,'link')}<small>${esc(e.english_name)}</small></td><td>${esc(e.country)}<small>${esc(e.city)}</small></td><td>${e.business_areas.map(v=>esc(label('business',v))).join(' · ')}</td><td>${esc(label('importance',e.importance))}</td><td>${esc(label('relationship',e.relationship))}</td><td>${badge(label('participation',e.participation),'status-'+e.participation)}</td><td>${esc(label('tristate',e.pavilion))}</td><td>${s.travelers}명</td><td><b>${s.readiness}%</b><small class="${s.overdue?'ex-danger':''}">Overdue ${s.overdue}</small></td><td>${esc(s.shipment_status)}<small>${s.shipment_count}건</small></td><td>${money(s.budget_krw)}<small>${money(s.actual_krw)}</small></td><td>${s.followup_open}건</td><td class="ex-note">${esc(e.notes)}</td></tr>`;}).join('')}</tbody></table></div></details>`).join('');
  }
  function calendarMarkup(){
    const first=calendarMonth+'-01',d=utc(first),start=shift(first,-d.getUTCDay()),next=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1)),last=shift(iso(next),-1),end=shift(last,6-utc(last).getUTCDay());
    const events=filtered().filter(e=>e.end_date>=start&&e.start_date<=end);
    const weeks=[];for(let ws=start;ws<=end;ws=shift(ws,7)){
      const we=shift(ws,6),lanes=[];const bars=events.filter(e=>e.end_date>=ws&&e.start_date<=we).map(e=>{
        const a=e.start_date<ws?ws:e.start_date,b=e.end_date>we?we:e.end_date,from=Math.round((utc(a)-utc(ws))/86400000),to=Math.round((utc(b)-utc(ws))/86400000);let lane=0;while(lanes[lane]?.some(([x,y])=>!(to<x||from>y)))lane++;(lanes[lane]??=[]).push([from,to]);return {e,from,to,lane};
      });
      weeks.push(`<div class="ex-week"><div class="ex-days">${Array.from({length:7},(_,i)=>{const day=shift(ws,i);return `<div class="${day.slice(0,7)!==calendarMonth?'muted':''} ${day===today()?'today':''}"><time datetime="${day}">${Number(day.slice(8))}</time></div>`;}).join('')}</div><div class="ex-bars">${lanes.map((_,lane)=>`<div class="ex-bar-lane">${bars.filter(b=>b.lane===lane).map(({e,from,to})=>`<button type="button" class="ex-calendar-event ex-start-${from+1} ex-end-${to+2} status-${esc(e.participation)}" data-ex-open="${e.id}" data-event-start="${e.start_date}" data-event-end="${e.end_date}" data-segment-start="${shift(ws,from)}" data-segment-end="${shift(ws,to)}" aria-label="${esc(e.name)} ${e.start_date}~${e.end_date}" title="${esc(e.name)} · ${e.start_date}~${e.end_date}">${e.start_date<ws?'‹ ':''}${esc(e.name)}${e.end_date>we?' ›':''}</button>`).join('')}</div>`).join('')}</div></div>`);
    }
    return `<div class="ex-calendar-heading">${button(calendarExpanded?'축소':'확대',`data-ex-expand aria-expanded="${calendarExpanded}"`)}${button('‹ 이전','data-ex-month="-1"')}<label><span class="sr-only">Calendar 월</span><input type="month" id="exCalendarMonth" aria-label="Calendar 월" value="${calendarMonth}"></label>${button('다음 ›','data-ex-month="1"')}<div class="ex-legend">${Object.entries(options.choices.participation).map(([k,v])=>badge(v,'status-'+k)).join('')}</div></div><div class="ex-calendar weeks-${weeks.length}"><div class="ex-weekdays">${['일','월','화','수','목','금','토'].map(x=>`<span>${x}</span>`).join('')}</div>${weeks.join('')}</div>`;
  }
  function bindMain(){
    root().onclick=async ev=>{const el=ev.target.closest('button');if(!el)return;
      if(el.hasAttribute('data-ex-reload'))return load();
      if(el.hasAttribute('data-ex-expand')){calendarExpanded=!calendarExpanded;saveFilters();renderMain();}
      if(el.hasAttribute('data-ex-reset')){filters={};saveFilters();renderMain();}
      if(el.dataset.exOpen)await openDetail(el.dataset.exOpen);
      if(el.hasAttribute('data-ex-new'))openNew();
      if(el.hasAttribute('data-ex-templates'))await openTemplates();
      if(el.dataset.exMonth){const d=utc(calendarMonth+'-01');d.setUTCMonth(d.getUTCMonth()+Number(el.dataset.exMonth));calendarMonth=iso(d).slice(0,7);filters.year=calendarMonth.slice(0,4);filters.month=calendarMonth.slice(5);saveFilters();renderMain();}
    };
    root().onchange=ev=>{if(ev.target.closest('#exFilters')){filters[ev.target.name]=ev.target.value;if(ev.target.name==='year'&&filters.year)calendarMonth=filters.year+'-'+(filters.month||calendarMonth.slice(5));if(ev.target.name==='month'&&filters.month)calendarMonth=(filters.year||calendarMonth.slice(0,4))+'-'+filters.month;saveFilters();renderMain();}if(ev.target.id==='exCalendarMonth'&&/^\d{4}-\d{2}$/.test(ev.target.value)){calendarMonth=ev.target.value;filters.year=calendarMonth.slice(0,4);filters.month=calendarMonth.slice(5);saveFilters();renderMain();}};
    root().querySelector('#exFilters')?.addEventListener('submit',e=>e.preventDefault());
  }
  function dialog(){let d=document.querySelector('#exDetailDialog');if(!d){d=document.createElement('dialog');d.id='exDetailDialog';d.className='ex-detail-dialog';document.body.append(d);d.addEventListener('close',()=>{window.SearchablePicker?.closeAll();editing=null;});}return d;}
  function showDialog(markup){const d=dialog();window.SearchablePicker?.closeAll();d.innerHTML=markup;if(!d.open)d.showModal();d.onclick=detailClick;d.onchange=detailChange;d.onsubmit=saveForm;enhance();return d;}
  function enhance(){dialog().querySelectorAll('select[data-ex-search]').forEach(el=>window.SearchablePicker?.enhance(el));}
  function referenceOptions(target,kind,row){
    if(target==='users')return Object.fromEntries(options.users.filter(u=>u.status==='active'||u.id===row?.user_id||u.id===row?.owner_id).map(u=>[u.id,u.display_name]));
    if(target==='customer_master')return Object.fromEntries(options.customers.map(u=>[u.id,u.display_name]));
    if(target==='customer_contacts'){const customer=row?.customer_id;return Object.fromEntries(options.contacts.filter(u=>u.customer_id===customer).map(u=>[u.id,u.contact_name]));}
    if(target==='records')return Object.fromEntries(options.cash_plans.map(u=>[u.id,u.title]));
    return Object.fromEntries((detail?.[target]||[]).filter(x=>x.is_active).map(x=>[x.id,x.name||x.company_name||x.description||x.title||x.id]));
  }
  function field(kind,name,spec,value,row,compact=false){
    spec={...spec,label:spec.label==='대표 담당자'?'주담당자':spec.label};
    const typ=spec.type,disabled=!writable()?' disabled':'',required=spec.required?' required':'',attrs=`name="${esc(name)}" aria-label="${esc(spec.label)}"${disabled}${required}`;
    let input;
    if(typ.startsWith('choice:')||typ.startsWith('ref:')||['product','inventory'].includes(typ)||name==='situation'){
      const vals=name==='situation'?options.situations:typ.startsWith('choice:')?options.choices[typ.split(':')[1]]:typ.startsWith('ref:')?referenceOptions(typ.split(':')[1],kind,row):typ==='product'?options.products:Object.fromEntries((detail?.inventory||[]).map(x=>[x.product_key,x.product_name+' · 재고 '+num(x.closing)]));
      input=`<select ${attrs} ${typ.startsWith('ref:')||typ==='product'?'data-ex-search':''}><option value="">선택</option>${Object.entries(vals).map(([k,v])=>`<option value="${esc(k)}" ${String(value)===String(k)?'selected':''}>${esc(v)}</option>`).join('')}</select>`;
    }else if(typ==='bool')input=`<input type="checkbox" ${attrs} ${value?'checked':''}>`;
    else if(typ==='textarea')input=`<textarea ${attrs} rows="3">${esc(value)}</textarea>`;
    else input=`<input ${attrs} type="${typ==='datetime'?'datetime-local':['date','email','url'].includes(typ)?typ:['number','integer'].includes(typ)?'number':'text'}" ${typ==='number'?'step="any"':typ==='integer'?'step="1"':''} value="${esc(value??'')}">`;
    return compact?input:`<label class="ex-field ${typ==='textarea'?'wide':''} ${typ==='bool'?'check':''}"><span>${esc(spec.label)}${spec.required?' *':''}</span>${input}</label>`;
  }
  function formMarkup(kind,row={},isNew=false){
    const spec=options.fields[kind];const fields=Object.entries(spec).map(([n,s])=>field(kind,n,s,row[n]??s.default,row));
    if(kind==='exhibitions')fields.push(`<label class="ex-field wide"><span>사업분야 (복수선택) *</span><select name="business_areas" aria-label="사업분야 (복수선택)" multiple data-ex-search ${writable()?'':'disabled'}>${Object.entries(options.choices.business).map(([k,v])=>`<option value="${k}" ${(row.business_areas||['dental']).includes(k)?'selected':''}>${esc(v)}</option>`).join('')}</select></label>`);
    return `<form class="ex-edit-form" data-kind="${kind}" data-id="${esc(row.id||'')}" data-version="${row.version||''}"><div class="ex-form-grid">${fields.join('')}</div>${kind==='expenses'?`<div class="ex-rate-help"><label>공통 기준환율 불러오기 ${select('_reference_rate',Object.fromEntries(options.rates.map((r,i)=>[i,`${r.currency} · ${r.rate_date} · ${r.krw_rate}`])),'')}</label><small>선택한 값을 이 비용의 환율로 기록합니다.</small></div>`:''}<div class="ex-form-error" role="alert"></div><div class="ex-form-actions">${writable()?'<button type="submit" class="ex-button primary">'+(isNew?'등록':'저장')+'</button>':''}${button(isNew?'입력 취소':'닫기','data-ex-cancel-edit')}</div></form>`;
  }
  function openNew(){detail=null;editing={kind:'exhibitions',id:null};showDialog(`<header><div><small>EXHIBITION OPERATIONS</small><h2>행사 등록</h2></div>${button('닫기','data-ex-close')}</header><p class="ex-intro">등록하면 전체 Standard Checklist가 생성됩니다. 필요 없는 항목은 해당없음으로 표시하세요.</p>${formMarkup('exhibitions',{},true)}`);}
  async function openDetail(id,tab='basic',focus=null){
    try{detail=await api('/'+id);activeTab=tab;editing=null;renderDetail();if(focus)focusRow(focus);}catch(e){notice(e.message,true);}
  }
  function readinessMarkup(){const s=detail.summary;return `<div class="ex-readiness"><div><small>출국 / 행사 준비 상태</small><strong>${s.readiness}%</strong><progress max="100" value="${s.readiness}"></progress><span>${s.completed_checklist}/${s.total_checklist} 완료 · 미완료 ${s.remaining}건</span></div><div><b class="${s.overdue?'ex-danger':''}">기한초과 ${s.overdue}건</b><p>${esc(s.shipment_status)} · 결제대기 ${s.payment_pending}건</p><p>예상 ${money(s.budget_krw)} · 실제 ${money(s.actual_krw)}</p></div><details><summary>누락 / 기한초과 / 결제대기 확인</summary><div class="ex-alert-list">${[...s.alerts,...s.remaining_items,...s.payment_items].map(r=>button(esc(r.title),`data-ex-focus-kind="${r.kind}" data-ex-focus-id="${r.id}"`,'link')).join('')||'확인할 항목이 없습니다.'}</div></details></div>`;}
  function renderDetail(){
    const ev=detail.event;showDialog(`<header><div><small>${esc(ev.country)} · ${esc(ev.city)} · ${ev.start_date}~${ev.end_date}</small><h2>${esc(ev.name)}</h2></div><div>${badge(label('participation',ev.participation),'status-'+ev.participation)}${button('새로고침','data-ex-detail-refresh')}${button('닫기','data-ex-close')}</div></header>${readinessMarkup()}<nav class="ex-tabs" aria-label="전시회 상세 영역">${tabs.map(([k,v])=>button(v,`data-ex-tab="${k}" aria-pressed="${activeTab===k}"`,activeTab===k?'selected':'')).join('')}</nav><div id="exTabContent">${tabMarkup()}</div>`);
  }
  function tabMarkup(){
    if(activeTab==='basic')return `<h3>기본정보</h3>${formMarkup('exhibitions',detail.event)}`;
    if(activeTab==='organizer')return entityMarkup('organizers')+entityMarkup('organizer_contacts')+entityMarkup('pavilion');
    if(activeTab==='support')return entityMarkup('support')+checklistMarkup(['A','GS']);
    if(activeTab==='checklist')return checklistMarkup();
    if(activeTab==='shipments')return entityMarkup('shipments')+entityMarkup('shipment_items')+checklistMarkup(['B','HC','FW']);
    if(activeTab==='travel')return entityMarkup('people')+checklistMarkup(['C','D','E']);
    if(activeTab==='booth')return checklistMarkup(['F','G','H','I','J','K']);
    if(activeTab==='meetings')return entityMarkup('meetings')+entityMarkup('leads');
    if(activeTab==='sales')return inventoryMarkup()+entityMarkup('sales')+entityMarkup('stock_uses')+entityMarkup('adjustments');
    if(activeTab==='expenses')return entityMarkup('expenses');
    if(activeTab==='return')return checklistMarkup(['L','M']);
    if(activeTab==='followups')return outcomeMarkup()+entityMarkup('followups');
    return '';
  }
  const columns={people:['user_id','role','departure_date','return_date'],organizers:['role','company_name','country','email','phone'],organizer_contacts:['organizer_id','name','job_title','email','phone'],pavilion:['available','participating','name','organizer','application_due'],support:['program_name','approval','support_limit','self_pay','settlement_due','settlement_status'],shipments:['name','method','planned_date','requested','request_date','actual_date','status'],shipment_items:['shipment_id','product_name_snapshot','product_code_snapshot','quantity','purpose','lot'],adjustments:['product_key','quantity','reason','adjustment_date'],stock_uses:['product_key','use_type','quantity','reason','use_date'],sales:['sale_date','buyer','product_key','quantity','unit_price','currency','payment_status','received_amount'],meetings:['meeting_at','company_name','meeting_type','location','owner_id','preparation_status'],leads:['company_name','country','contact_name','grade','owner_id','target_due_date','status'],expenses:['category','description','budget','actual','currency','subsidy_amount','payment_date'],followups:['company_name','next_action','owner_id','target_due_date','status']};
  function valueMarkup(kind,name,row){const spec=options.fields[kind][name],value=row[name];if(spec.type.startsWith('choice:'))return esc(label(spec.type.split(':')[1],value));if(spec.type.startsWith('ref:'))return esc(referenceOptions(spec.type.split(':')[1],kind,row)[value]||'—');if(spec.type==='inventory')return esc(detail.inventory.find(x=>x.product_key===value)?.product_name||value);if(spec.type==='bool')return value?'Yes':'No';if(spec.type==='number')return num(value);return esc(value||'—');}
  function evidenceMarkup(kind,row){const files=(detail.files||[]).filter(f=>f.is_active&&f.linked_kind===kind&&f.linked_id===row.id);return `<div class="ex-evidence">${files.map(f=>`<a href="/api/exhibitions/files/${f.id}" target="_blank" rel="noopener">${esc(f.original_name)}</a>`).join(' ')}${writable()?`<label class="ex-upload">증빙 추가<input type="file" data-ex-file-kind="${kind}" data-ex-file-id="${row.id}" aria-label="${esc(row.title||row.name||row.description||'항목')} 증빙 추가"></label>`:''}</div>`;}
  function entityMarkup(kind){
    const rows=(detail[kind]||[]).filter(r=>r.is_active),cols=columns[kind];const newRow=editing?.kind===kind&&!editing.id;
    return `<section class="ex-entity"><div class="ex-section-heading"><h3>${esc(options.titles[kind])}</h3>${writable()&&!(kind==='pavilion'&&rows.length)?button('+ 추가',`data-ex-add="${kind}"`):''}</div>${newRow?formMarkup(kind,{},true):''}${rows.length?`<div class="ex-table-wrap"><table class="ex-table"><thead><tr>${cols.map(k=>`<th>${esc(options.fields[kind][k].label)}</th>`).join('')}<th>완료 / 증빙 / 관리</th></tr></thead><tbody>${rows.map(row=>`<tr id="ex-row-${row.id}">${cols.map(n=>`<td>${valueMarkup(kind,n,row)}</td>`).join('')}<td>${row.completed_at?`<small>완료 ${esc(row.completed_at.slice(0,10))}</small>`:''}${button('상세 / 수정',`data-ex-edit-kind="${kind}" data-ex-edit-id="${row.id}"`,'link')}${evidenceMarkup(kind,row)}</td></tr>${editing?.kind===kind&&editing.id===row.id?`<tr><td colspan="${cols.length+1}">${formMarkup(kind,row)}</td></tr>`:''}`).join('')}</tbody></table></div>`:'<p class="ex-empty small">아직 등록된 항목이 없습니다.</p>'}</section>`;
  }
  function checklistMarkup(groups=null){
    const all=(detail.checklist||[]).filter(r=>r.is_active&&(!groups||groups.includes(r.situation)));const groupsMap={};for(const r of all)(groupsMap[r.situation]??=[]).push(r);
    return `<section class="ex-entity"><div class="ex-section-heading"><h3>Situation Checklist</h3>${writable()?button('+ 준비업무 추가','data-ex-add="checklist"'):''}</div><p class="ex-help">필요 없는 항목은 해당없음으로 표시하세요. 목표일을 직접 바꾸면 행사일 변경 시 유지됩니다.</p>${editing?.kind==='checklist'&&!editing.id?formMarkup('checklist',{situation:groups?.[0]||'A'},true):''}${Object.entries(groupsMap).map(([key,rows])=>{
      rows.sort((a,b)=>a.sort_order-b.sort_order);const completed=rows.filter(r=>['completed','na'].includes(r.status)).length;
      return `<details class="ex-situation" data-situation="${key}" ${groups||key==='A'?'open':''}><summary>${esc(key)}. ${esc(options.situations[key])} <span>${completed}/${rows.length} 처리</span></summary><div class="ex-table-wrap"><table class="ex-table ex-checklist"><thead><tr>${['업무','필요여부','담당','권장일 / 목표일','상태','완료일','비용 / 증빙','비고 / 관리'].map(t=>`<th>${t}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr id="ex-row-${row.id}" class="${row.due_status==='overdue'?'ex-overdue':''} ${row.status==='na'?'ex-na':''}" data-checklist-id="${row.id}"><td>${esc(row.title)}</td><td>${field('checklist','required',options.fields.checklist.required,row.required,row,true)}</td><td>${field('checklist','owner_id',options.fields.checklist.owner_id,row.owner_id,row,true)}</td><td><small>권장 ${row.recommended_due_date||'—'}</small>${field('checklist','target_due_date',options.fields.checklist.target_due_date,row.target_due_date,row,true)}<small>${row.due_manual?'수동 확정':'자동 계산'}</small></td><td>${field('checklist','status',options.fields.checklist.status,row.status,row,true)}</td><td>${esc(row.completed_at?.slice(0,10)||'—')}</td><td>${field('checklist','expense_id',options.fields.checklist.expense_id,row.expense_id,row,true)}${evidenceMarkup('checklist',row)}</td><td><input aria-label="비고" name="notes" value="${esc(row.notes)}" ${writable()?'':'disabled'}>${writable()?button('행 저장',`data-ex-save-check="${row.id}"`):''}<small class="ex-row-feedback" role="status"></small></td></tr>`).join('')}</tbody></table></div></details>`;
    }).join('')}</section>`;
  }
  function inventoryMarkup(){return `<section class="ex-entity"><h3>현장재고</h3><p class="ex-help">출고완료 제품 → Opening − 판매 − Sample − 기타사용 ± 조정 = Closing</p><div class="ex-table-wrap"><table class="ex-table"><thead><tr>${['제품','Opening','판매','Sample','기타사용','Adjustment','Closing'].map(t=>`<th>${t}</th>`).join('')}</tr></thead><tbody>${detail.inventory.map(r=>`<tr><td>${esc(r.product_name)}</td>${['opening','sale','sample','other_out','adjustment','closing'].map(k=>`<td>${num(r[k])}</td>`).join('')}</tr>`).join('')||'<tr><td colspan="7">출고완료된 제품이 없습니다.</td></tr>'}</tbody></table></div></section>`;}
  function outcomeMarkup(){const s=detail.summary;return `<div class="ex-outcomes">${[['총 상담건수',s.meeting_count],['신규 Lead',s.lead_count],['기존 고객 Meeting',s.existing_customer_meetings],['Qualified Lead',s.qualified_leads],['Sample 제공',num(s.sample_quantity)],['판매수량',num(s.sale_quantity)],['Follow-up 미완료',s.followup_open],['총 비용',money(s.actual_krw)],['정부지원금',money(s.subsidy_krw)],['회사 실부담',money(s.company_cost_krw)]].map(([t,v])=>`<article><span>${t}</span><strong>${v}</strong></article>`).join('')}${Object.entries(s.sales_by_currency).map(([currency,x])=>`<article><span>${esc(currency)} 현장매출 / 수금 / 미수</span><strong>${num(x.revenue)} / ${num(x.received)} / ${num(x.outstanding)}</strong></article>`).join('')}</div>`;}
  function readForm(form,kind){const result={};for(const [n,s] of Object.entries(options.fields[kind])){const el=form.querySelector(`[name="${n}"]`);if(!el)continue;result[n]=s.type==='bool'?Number(el.checked):['number','integer'].includes(s.type)?Number(el.value||0):s.type==='ref:users'?(el.value?Number(el.value):null):s.type.startsWith('ref:')||['date','datetime'].includes(s.type)?el.value||null:el.value;}
    if(kind==='exhibitions')result.business_areas=[...form.querySelector('[name="business_areas"]').selectedOptions].map(o=>o.value);
    if(form.dataset.version)result.version=Number(form.dataset.version);return result;
  }
  async function saveForm(ev){ev.preventDefault();const form=ev.target.closest('.ex-edit-form');if(!form||!writable())return;const kind=form.dataset.kind,id=form.dataset.id,err=form.querySelector('.ex-form-error'),submit=form.querySelector('[type="submit"]');err.textContent='';submit.disabled=true;
    try{const body=readForm(form,kind);const path=kind==='exhibitions'?(id?'/'+id:''):kind==='templates'?'/items/templates/'+id:id?'/items/'+kind+'/'+id:'/'+detail.event.id+'/'+kind;const result=await api(path,{method:id?'PATCH':'POST',body});notice('저장했습니다.');editing=null;
      if(kind==='templates'){await openTemplates();return;}
      if(kind==='exhibitions'&&!id){detail=result;activeTab='basic';}else detail=await api('/'+detail.event.id);
      listing=await api('');renderMain();renderDetail();
    }catch(e){err.textContent=e.message+(e.status===409?' · 입력 내용을 확인한 뒤 새로고침하세요.':'');}finally{submit.disabled=false;}
  }
  const tabFor=kind=>({checklist:'checklist',shipments:'shipments',shipment_items:'shipments',expenses:'expenses',followups:'followups',sales:'sales',leads:'meetings',meetings:'meetings',people:'travel'}[kind]||'basic');
  function focusRow(id){const row=dialog().querySelector('#ex-row-'+id);if(!row)return;row.closest('details')?.setAttribute('open','');row.classList.add('ex-highlight');row.scrollIntoView?.({block:'center',behavior:'smooth'});setTimeout(()=>row.classList.remove('ex-highlight'),6000);}
  async function detailClick(ev){const el=ev.target.closest('button');if(!el)return;
    if(el.hasAttribute('data-ex-close')){dialog().close();return;}
    if(el.dataset.exTab){activeTab=el.dataset.exTab;editing=null;renderDetail();}
    if(el.hasAttribute('data-ex-detail-refresh'))return openDetail(detail.event.id,activeTab);
    if(el.dataset.exAdd){editing={kind:el.dataset.exAdd,id:null};renderDetail();dialog().querySelector('.ex-edit-form input')?.focus();}
    if(el.dataset.exEditKind){editing={kind:el.dataset.exEditKind,id:el.dataset.exEditId};renderDetail();focusRow(el.dataset.exEditId);}
    if(el.hasAttribute('data-ex-cancel-edit')){editing=null;if(detail?.event)renderDetail();else if(detail?.templates)await openTemplates();else dialog().close();}
    if(el.dataset.exFocusKind){activeTab=tabFor(el.dataset.exFocusKind);editing=null;renderDetail();focusRow(el.dataset.exFocusId);}
    if(el.dataset.exSaveCheck)await saveChecklist(el.dataset.exSaveCheck,el);
    if(el.dataset.exTemplateEdit){const row=detail.templates.find(x=>x.id===el.dataset.exTemplateEdit);showDialog(`<header><h2>Standard Checklist 기준 수정</h2>${button('닫기','data-ex-close')}</header><p>변경한 기준은 이후 생성하는 행사에 적용됩니다.</p>${formMarkup('templates',row)}`);}
  }
  async function saveChecklist(id,buttonNode){const row=detail.checklist.find(x=>x.id===id),tr=buttonNode.closest('tr'),data={version:row.version};for(const n of ['required','owner_id','target_due_date','status','expense_id','notes']){const el=tr.querySelector(`[name="${n}"]`);data[n]=el.value||(['owner_id','target_due_date','expense_id'].includes(n)?null:'');if(n==='owner_id'&&data[n])data[n]=Number(data[n]);}
    if(data.target_due_date===row.target_due_date)delete data.target_due_date;
    if(row.required==='na'&&data.status!=='na'&&data.required==='na')data.required='required';
    buttonNode.disabled=true;const feedback=tr.querySelector('.ex-row-feedback');try{await api('/items/checklist/'+id,{method:'PATCH',body:data});detail=await api('/'+detail.event.id);listing=await api('');renderMain();renderDetail();focusRow(id);notice('준비업무를 저장했습니다.');}catch(e){feedback.textContent=e.message;buttonNode.disabled=false;}}
  async function detailChange(ev){const el=ev.target;
    if(el.dataset.exFileKind&&el.files?.[0]){const form=new FormData();form.set('linked_kind',el.dataset.exFileKind);form.set('linked_id',el.dataset.exFileId);form.set('file',el.files[0]);el.disabled=true;try{const r=await fetch('/api/exhibitions/'+detail.event.id+'/files',{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':ctx.state.csrf},body:form});const result=await r.json();if(!r.ok)throw new Error(result.error||'파일 업로드 실패');detail=await api('/'+detail.event.id);renderDetail();notice('증빙을 추가했습니다.');}catch(e){notice(e.message,true);el.disabled=false;}return;}
    const form=el.closest('.ex-edit-form');if(!form)return;
    if(el.name==='interim_product_code'&&el.value){form.querySelector('[name="product_name_snapshot"]').value=options.products[el.value];form.querySelector('[name="product_code_snapshot"]').value=el.value;}
    if(el.name==='target_due_date'&&form.dataset.kind==='checklist')form.querySelector('[name="due_manual"]').checked=true;
    if(el.name==='_reference_rate'&&el.value!==''){const r=options.rates[Number(el.value)];for(const [k,v] of Object.entries({currency:r.currency,krw_rate:r.krw_rate,rate_date:r.rate_date,rate_source:r.source}))form.querySelector(`[name="${k}"]`).value=v;}
    if(el.name==='customer_id'&&form.dataset.kind==='meetings'){const selectEl=form.querySelector('[name="contact_id"]');if(selectEl){window.SearchablePicker?.destroy?.(selectEl);selectEl.innerHTML='<option value="">선택</option>'+options.contacts.filter(r=>r.customer_id===el.value).map(r=>`<option value="${r.id}">${esc(r.contact_name)}</option>`).join('');window.SearchablePicker?.enhance(selectEl);}}
  }
  async function openTemplates(){try{detail={templates:(await api('/templates')).items};showDialog(`<header><h2>Standard Checklist 기준 관리</h2>${button('닫기','data-ex-close')}</header><p>권장 Offset은 행사 시작일 기준입니다. 기준 변경은 이후 생성하는 행사에 적용됩니다.</p><div class="ex-table-wrap"><table class="ex-table"><thead><tr><th>Situation</th><th>업무명</th><th>필요여부</th><th>권장 Offset</th><th>관리</th></tr></thead><tbody>${detail.templates.map(r=>`<tr><td>${esc(options.situations[r.situation])}</td><td>${esc(r.title)}</td><td>${esc(label('required',r.required))}</td><td>${r.offset_days}</td><td>${button('수정',`data-ex-template-edit="${r.id}"`)}</td></tr>`).join('')}</tbody></table></div>`);}catch(e){notice(e.message,true);}}
  window.ExhibitionsUI={init,load,openDetail};
})();
