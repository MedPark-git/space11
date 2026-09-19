"""Controlled Exhibition fields and standard situation checklist (no business seed)."""
from maps_taxonomy import PARENT_BUSINESS_AREAS, MEETING_IMPORTANCE, INTERIM_CONTRACT_PRODUCTS

VERSION = 'exhibition-2026-09-19-operations-v1'
CHOICES = {
 'business': {k:PARENT_BUSINESS_AREAS[k] for k in ('dental','medical','aesthetic')},
 'importance': MEETING_IMPORTANCE,
 'relationship': {'general':'일반 전시회 / 학회','partner_host':'Partner 자체 주최 행사','partner_attend':'Partner 참가 행사','medpark':'MedPark 자체 행사','other':'기타'},
 'participation': {'candidate':'후보','exhibiting':'참가 확정','visiting':'참관 확정','declined':'불참','completed':'완료'},
 'tristate': {'unknown':'Unknown','yes':'Yes','no':'No'},
 'check_status': {'not_started':'미착수','in_progress':'진행','completed':'완료','na':'해당없음'},
 'required': {'required':'필요','optional':'선택','na':'해당없음'},
 'shipment_method': {'hand_carry':'Hand Carry','forwarder':'Forwarder','none':'없음','other':'기타'},
 'shipment_status': {'planned':'출고 준비','completed':'출고 완료','cancelled':'취소'},
 'payment_method': {'cash':'Cash','card':'Card','bank_transfer':'Bank Transfer','other':'기타'},
 'payment_status': {'paid':'수금완료','unpaid':'미수','partial':'부분수금'},
 'meeting_type': {'appointment':'사전예약','walk_in':'Walk-in','our_booth':'우리 Booth 방문','visit_booth':'타 Booth 방문','partner_intro':'Partner 소개','other':'기타'},
 'open_status': {'open':'미완료','completed':'완료','cancelled':'취소'},
 'lead_status': {'new':'신규','qualified':'Qualified','follow_up':'Follow-up','closed':'종료'},
 'grade': {'A':'A','B':'B','C':'C'},
 'expense_category': {'booth':'Booth / 참가비','flight':'항공','hotel':'호텔','logistics':'물류','transport':'교통','meals':'식비','services':'Booth 부대서비스','marketing':'인쇄 / 홍보물','sales_prep':'판매 준비','other':'기타'},
 'organizer_role': {'official':'Official Organizer','korea_branch':'한국지사','korea_agent':'한국 Agent','agency':'전시대행사'},
 'person_role': {'traveler':'출장자','support':'운영지원'},
 'approval': {'not_applied':'미신청','applied':'신청','approved':'승인','rejected':'미승인','na':'해당없음'},
 'settlement': {'open':'준비','submitted':'제출','completed':'완료','na':'해당없음'},
 'use_type': {'sample':'Sample','other_out':'기타사용'},
}

# Field tuples: label, type, default, required. Domain tables remain explicit.
def f(label, kind='text', default='', required=False):
 return {'label':label,'type':kind,'default':default,'required':required}
def e(label, choice, default, required=False): return f(label,'choice:'+choice,default,required)
def ref(label, target, required=False): return f(label,'ref:'+target,None,required)
def day(label): return f(label,'date',None)
def num(label, default=0): return f(label,'number',default)
def flag(label): return f(label,'bool',0)
N=f('비고','textarea')
SPECS = {
 'exhibitions': dict(name=f('행사명',required=True), english_name=f('영문 행사명'),country=f('국가',required=True),city=f('도시'),venue=f('Venue'),start_date=f('시작일','date',None,True),end_date=f('종료일','date',None,True),primary_business_area=e('Primary 사업분야','business','dental'),importance=e('중요도','importance','medium'),relationship=e('행사관계','relationship','general'),participation=e('참가상태','participation','candidate'),booth_no=f('Booth No.'),hall=f('Hall'),website=f('공식 Website','url'),owner_id=ref('대표 담당자','users'),partner_id=ref('관련 Partner','customer_master'),notes=N),
 'people':dict(user_id=ref('출장자 / 지원자','users',True),role=e('역할','person_role','traveler'),departure_date=day('출국일'),return_date=day('귀국일'),flight=f('항공편 / 예약'),hotel=f('호텔 / 예약'),local_phone=f('현지 연락처'),transport_app=f('교통 App'),emergency_contact=f('현지 긴급 연락처'),notes=N),
 'organizers':dict(role=e('역할','organizer_role','official'),company_name=f('회사명',required=True),country=f('국가'),website=f('Website','url'),email=f('대표 Email','email'),phone=f('대표 전화'),role_notes=f('담당 역할'),notes=N),
 'organizer_contacts':dict(organizer_id=ref('주관사 / Agent','organizers',True),name=f('담당자명',required=True),job_title=f('직책'),email=f('Email','email'),phone=f('전화'),whatsapp=f('WhatsApp'),notes=N),
 'pavilion':dict(available=e('Korean Pavilion 여부','tristate','unknown'),participating=flag('실제 Pavilion 참가'),name=f('Pavilion 명칭'),organizer=f('Pavilion 주관사'),contact=f('담당자'),email=f('Email','email'),phone=f('전화'),support_linked=flag('지원사업 연결'),application_due=day('신청마감일'),fee=num('참가비'),currency=f('통화',default='KRW'),booth_scope=f('제공 Booth 범위'),notes=N),
 'support':dict(enabled=flag('지원사업 대상'),program_name=f('지원사업명'),organizing_agency=f('주관기관'),executing_agency=f('수행기관'),application_due=day('신청기한'),approval=e('승인상태','approval','not_applied'),support_limit=num('지원한도'),self_pay=num('자부담'),currency=f('통화',default='KRW'),eligible_categories=f('지원가능 비용항목','textarea'),designated_provider=flag('지정 수행기관 사용'),organizer_prepay=flag('주관사 대납'),reimbursement_allowed=flag('회사 선결제 후 정산 가능'),designated_card=flag('지정카드 사용 필요'),overseas_transfer=flag('해외송금 인정'),required_evidence=f('필요 증빙','textarea'),result_report_required=flag('결과보고 필요'),settlement_due=day('정산기한'),settlement_status=e('정산상태','settlement','open'),notes=N),
 'templates':dict(situation=f('Situation',required=True),title=f('업무명',required=True),required=e('필요여부','required','required'),offset_days=f('권장 Due Offset (행사 시작일 기준)','integer',-30),sort_order=f('정렬순서','integer',0)),
 'checklist':dict(situation=f('Situation',required=True),title=f('업무명',required=True),required=e('필요여부','required','required'),owner_id=ref('담당자','users'),offset_days=f('권장 Offset','integer',-30),target_due_date=day('목표일'),due_manual=flag('목표일 수동 확정'),status=e('상태','check_status','not_started'),expense_id=ref('비용 연결','expenses'),notes=N,sort_order=f('정렬순서','integer',0)),
 'shipments':dict(name=f('출고건명',required=True),planned_date=day('출고 예정일'),requested=flag('출고요청'),request_date=day('출고요청일'),actual_date=day('실제 출고일'),method=e('Shipping Method','shipment_method','hand_carry'),other_method=f('기타방식 설명'),owner_id=ref('담당자','users'),status=e('출고상태','shipment_status','planned'),notes=N),
 'shipment_items':dict(shipment_id=ref('출고건','shipments',True),interim_product_code=f('제품','product'),product_name_snapshot=f('제품명',required=True),product_code_snapshot=f('제품코드'),quantity=num('실제 / 예정 수량'),purpose=f('목적'),lot=f('Lot'),expiry=day('Expiry'),notes=N),
 'adjustments':dict(product_key=f('제품','inventory',required=True),quantity=num('증감 수량'),reason=f('조정 사유',required=True),adjustment_date=day('조정일')),
 'stock_uses':dict(product_key=f('제품','inventory',required=True),use_type=e('사용구분','use_type','sample'),quantity=num('수량'),use_date=day('사용일'),reason=f('사용 사유',required=True)),
 'sales':dict(sale_date=f('판매일','date',None,True),buyer=f('Buyer / 고객',required=True),customer_id=ref('기존 Customer','customer_master'),product_key=f('제품','inventory',required=True),quantity=num('Qty'),unit_price=num('Unit Price'),currency=f('Currency',default='USD'),payment_method=e('Payment Method','payment_method','cash'),payment_status=e('Payment Status','payment_status','paid'),received_amount=num('수금액'),invoice=flag('Invoice 발행'),receipt=flag('Receipt 발행'),notes=N),
 'meetings':dict(meeting_at=f('일정 / 시간','datetime',None,True),company_name=f('회사',required=True),customer_id=ref('기존 Customer','customer_master'),country=f('국가'),contact_id=ref('기존 Customer Contact','customer_contacts'),contact_name=f('신규 Contact'),meeting_type=e('Meeting Type','meeting_type','appointment'),location=f('장소 / Booth'),purpose=f('목적'),interested_products=f('관심제품'),owner_id=ref('담당자','users'),preparation_status=e('준비상태','check_status','not_started'),meeting_note=f('Meeting Note','textarea'),next_action=f('Next Action'),history_notes=f('과거 Meeting / 거래 / 제안 / 가격 History','textarea')),
 'leads':dict(company_name=f('회사명',required=True),country=f('국가'),contact_name=f('담당자'),email=f('Email','email'),phone=f('전화'),whatsapp=f('WhatsApp'),interested_products=f('관심제품'),business_area=e('사업분야','business','dental'),consultation=f('상담내용','textarea'),grade=e('Lead Grade','grade','B'),owner_id=ref('Follow-up 담당자','users'),target_due_date=day('Follow-up Due'),status=e('상태','lead_status','new')),
 'expenses':dict(category=e('Category','expense_category','booth'),description=f('비용내용',required=True),budget=num('Budget'),actual=num('Actual'),currency=f('Currency',default='KRW'),krw_rate=num('1 외화당 KRW 환율',1),rate_date=day('환율 기준일'),rate_source=f('환율 출처',default='manual'),subsidy_eligible=flag('지원금 대상'),subsidy_amount=num('지원금액 (원)'),payment_date=day('결제일'),payment_due=day('결제기한'),payment_method=e('결제방법','payment_method','bank_transfer'),corporate_card=flag('법인카드'),remittance=flag('송금'),source_record_id=ref('기존 자금계획 참조','records'),notes=N),
 'followups':dict(company_name=f('업체',required=True),customer_id=ref('기존 Customer','customer_master'),lead_id=ref('Lead 연결','leads'),meeting_id=ref('Meeting 연결','meetings'),result=f('상담결과','textarea'),next_action=f('Next Action',required=True),owner_id=ref('담당자','users'),target_due_date=day('Due'),status=e('상태','open_status','open'),notes=N),
}
TITLES={'people':'출장 / 현지운영','organizers':'주관사 / Agent','organizer_contacts':'주관사 담당자','pavilion':'Korean Pavilion','support':'참가 / 정부지원','checklist':'사전준비 Checklist','shipments':'제품 / 출고 / 물류','shipment_items':'출고 제품','adjustments':'재고조정','stock_uses':'Sample / 기타사용','sales':'현장판매 / 수금','meetings':'Meeting','leads':'신규 Lead','expenses':'비용','followups':'사후 Follow-up','templates':'Standard Checklist Template'}
SITUATIONS={
 'A':'참가결정 직후','B':'제품 / 출고 / 물류','C':'출국 전','D':'현지 도착','E':'호텔','F':'전시장 사전확인 / Booth Setup','G':'행사 당일 Booth 운영','H':'우리 Booth 업체 Meeting','I':'타 업체 Booth 방문','J':'현장판매','K':'식사 / 간식 / 운영지원','L':'행사종료 / 철거 / 귀국','M':'귀국 후','HC':'Hand Carry','FW':'Forwarder','GS':'정부지원 상세',
}
# Full defaults, copied only when an event is explicitly created.
DEFAULT_GROUPS={
 'A':(-45,'참가신청|Booth 위치 검토|Booth 크기 결정|참가 계약|Organizer Invoice|참가비 지급기한|참가비 송금|송금증|입금확인|Exhibitor Portal 가입/등록|회사정보 등록|Logo 제출|Company Profile 제출|Exhibitor List 등록|Badge 신청|초청장 필요 여부|전기 신청|Internet 신청|부스 부대서비스 신청|정부지원 검토|출장인원 확정'),
 'B':(-60,'전시제품 선정|필요수량 확정|출고 예정일 확정|출고요청|출고 완료|운송방식 확정|Invoice / Packing List|현지 통관자료|Forwarder 관련 준비|Hand Carry 준비'),
 'C':(-3,'여권|Visa|항공권|호텔 예약|호텔 사전등록|필요 시 여권사본 업로드|여행자보험|법인카드|현금|현지화폐|법인폰|로밍 / eSIM / Wi-Fi|충전기|보조배터리|명함|간편식 / 음식|공항 택시|수하물 규정|Hand Carry 제품 인수'),
 'D':(-1,'입국수속|Hand Carry 통관|현지 통관 문제 발생 시 연락처|환전|SIM|현지 교통 App (Uber / Careem / Grab / Yandex / Bolt / 기타)|교통 App 카드등록|공항→호텔 이동'),
 'E':(-1,'예약확인|Check-in|Deposit|숙박자 등록|여권 제출 / Upload|조식|행사장 이동방법|제품 보관|Shuttle'),
 'F':(-1,'Venue|Hall|Booth No.|Badge|Contractor 연락처|설치시간|물류도착 확인|Booth 상태|그래픽|조명|전기|Wi-Fi|Monitor|Tablet|Furniture|Storage|Sample|제품 Display|Brochure|Price List|명함|Meeting Table|쓰레기통|멀티탭|충전기|테이프|가위|형광조끼|청소도구'),
 'G':(0,'제품진열|Opening Stock 확인|Brochure|Sample|Tablet|영상|Price List|명함|상담록|Staff 배치|Meeting Schedule'),
 'H':(-7,'Meeting 시간|회사명|참석자|과거 Meeting History|업체조사|기존 매출/거래|기존 제안|관심제품|가격 History|경쟁제품|회사소개|Product Presentation|Tablet|영상|Brochure|Technical File|Clinical Case|Sample Kit|Hands-on Kit|Price List'),
 'I':(-3,'방문업체|Booth|목적|약속시간|담당자|회사소개자료|제품자료|질문사항|Meeting Result|Next Action'),
 'J':(0,'Price List|판매재고|Invoice|Receipt|Shopping Bag|Card Reader|Card Reader 충전|현금|잔돈|돈가방|고무줄|수금증|포스트잇|Daily Closing'),
 'K':(0,'Staff 점심|물|커피|Snack|고객 응대 음료|휴식 Rotation'),
 'L':(3,'Closing Stock|판매수량 확정|Sample 수량|Booth 철거|렌탈반납|전시품 회수|잔여제품 처리|Hotel Check-out|공항 이동|수하물|귀국 Hand Carry|필요 세관사항'),
 'M':(14,'출장비 정산|법인카드 증빙|현금 정산|Organizer Invoice|호텔 증빙|항공 증빙|택시 증빙|물류 증빙|식대 증빙|기타비용 증빙|정부지원 증빙|정부지원 정산|현장판매 정산|잔여재고 확인|Lead 정리|Meeting Minutes|사진 업로드|출장보고|Exhibition 결과보고|Follow-up 생성'),
 'HC':(-7,'제품 준비|출고요청 확인|제품 List|Invoice / Packing List 필요 여부|Not for Sale 필요 여부|현지 허가자료|전시회 참가 Confirmation|휴대 담당자|가방/수하물 배분|출국 당일 제품 인수|현지 통관 대응자료|수출면장 필요 여부'),
 'FW':(-60,'Forwarder 선정|Quote|Consignee|Pickup 일정|Invoice|Packing List|HS Code|Not for Sale 필요 여부|Exhibition Purpose Letter 필요 여부|Registration / Permit 필요 여부|AWB|출항|현지도착|Customs Clearance|최종 Delivery|Booth / Warehouse 도착확인'),
 'GS':(-45,'지원사업 신청기한 확인|지원 승인 확인|지원가능 비용항목 확인|지정 수행기관 확인|주관사 대납 여부 확인|선결제 정산 가능 여부|지정카드 필요 여부|해외송금 인정 여부|필요 증빙 확보|결과보고 제출|지원금 정산기한 확인|지원금 정산 완료'),
}
def standard_templates():
 rows=[]
 for group,(offset,titles) in DEFAULT_GROUPS.items():
  for index,title in enumerate(titles.split('|')):
   due={'출고요청':-90,'호텔 예약':-45,'Badge 신청':-20}.get(title,offset)
   rows.append(dict(situation=group,title=title,required='optional' if title=='수출면장 필요 여부' else 'required',offset_days=due,sort_order=len(rows),template_key=f'{group}-{index+1:02d}'))
 return rows
