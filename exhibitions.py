"""Exhibition canonical operations ledger; never writes other business ledgers."""
import hashlib
import json
import re
import sqlite3
import uuid
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import g, jsonify, request, send_file
from werkzeug.utils import secure_filename
from exhibition_catalog import VERSION, CHOICES, SPECS, TITLES, SITUATIONS, standard_templates
from maps_taxonomy import INTERIM_CONTRACT_PRODUCTS

READ_ROLES=('admin','manager','editor','viewer')
WRITE_ROLES=('admin','manager','editor')
TABLES={k:('exhibitions' if k=='exhibitions' else 'exhibition_'+k) for k in SPECS}
COMMON='''version INTEGER NOT NULL DEFAULT 1 CHECK(version>0), is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), created_by INTEGER REFERENCES users(id), updated_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL'''
EXTRA={
 'templates': 'template_key TEXT UNIQUE',
 'checklist': 'template_id TEXT REFERENCES exhibition_templates(id) ON DELETE RESTRICT, recommended_due_date TEXT, completed_at TEXT',
 'shipment_items': 'product_key TEXT NOT NULL, future_product_master_id TEXT',
 'followups': 'completed_at TEXT, future_major_task_id TEXT',
}

def sql_field(name, spec):
 kind=spec['type']; default=spec['default']; sqltype='INTEGER' if kind in ('integer','bool') or kind=='ref:users' else 'REAL' if kind=='number' else 'TEXT'
 result=f'"{name}" {sqltype}'
 if default is not None:
  result+=' NOT NULL DEFAULT '+(str(default) if isinstance(default,(int,float)) else "'"+default.replace("'","''")+"'")
 if spec['required']: result+=' NOT NULL'
 if kind.startswith('ref:'):
  target=kind.split(':',1)[1];result+=' REFERENCES '+TABLES.get(target,target)+'(id) ON DELETE RESTRICT'
 if kind.startswith('choice:'):
  choices=CHOICES[kind.split(':',1)[1]];result+=' CHECK("'+name+'" IN ('+','.join("'"+k+"'" for k in choices)+'))'
 if kind=='bool':result+=' CHECK("'+name+'" IN (0,1))'
 return result

def ddl_statements():
 rows=[]
 for key, fields in SPECS.items():
  parts=['id TEXT PRIMARY KEY']
  if key not in ('exhibitions','templates'):parts.append('exhibition_id TEXT NOT NULL REFERENCES exhibitions(id) ON DELETE RESTRICT')
  parts.extend(sql_field(n,s) for n,s in fields.items()); parts.append(COMMON)
  if key in EXTRA:parts.append(EXTRA[key])
  if key in ('pavilion',):parts.append('UNIQUE(exhibition_id)')
  if key=='exhibitions':parts.append('CHECK(end_date>=start_date)')
  rows.append('CREATE TABLE IF NOT EXISTS '+TABLES[key]+' ('+','.join(parts)+')')
  if key not in ('exhibitions','templates'):rows.append(f'CREATE INDEX IF NOT EXISTS idx_exhibition_{key}_event ON {TABLES[key]}(exhibition_id,is_active)')
  cols='id,exhibition_id' if key not in ('exhibitions','templates') else 'id'
  predicate=' OR '.join(f'NEW.{c}<>OLD.{c}' for c in cols.split(','))
  rows.append(f"CREATE TRIGGER IF NOT EXISTS exhibition_{key}_immutable BEFORE UPDATE OF {cols} ON {TABLES[key]} WHEN {predicate} BEGIN SELECT RAISE(ABORT,'Exhibition identity is immutable'); END")
 rows.extend([
  "CREATE TABLE IF NOT EXISTS exhibition_business_areas (exhibition_id TEXT NOT NULL REFERENCES exhibitions(id) ON DELETE RESTRICT, business_area TEXT NOT NULL CHECK(business_area IN ('dental','medical','aesthetic')), PRIMARY KEY(exhibition_id,business_area))",
  'CREATE INDEX IF NOT EXISTS idx_exhibition_calendar ON exhibitions(is_active,start_date,end_date)',
  'CREATE INDEX IF NOT EXISTS idx_exhibition_check_due ON exhibition_checklist(status,target_due_date)',
  '''CREATE TABLE IF NOT EXISTS exhibition_files (id TEXT PRIMARY KEY, exhibition_id TEXT NOT NULL REFERENCES exhibitions(id) ON DELETE RESTRICT, linked_kind TEXT NOT NULL, linked_id TEXT NOT NULL, original_name TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, '''+COMMON+')',
 ])
 return rows
DDL=ddl_statements()
CHECKSUM=hashlib.sha256(('\n'.join(DDL)+json.dumps(standard_templates(),sort_keys=True)).encode()).hexdigest()

def schema_ready(db):
 try:
  row=db.execute('SELECT checksum FROM exhibition_schema_migrations WHERE version=?',(VERSION,)).fetchone()
  tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  return bool(row and row[0]==CHECKSUM and (set(TABLES.values())|{'exhibition_files','exhibition_business_areas'}).issubset(tables))
 except sqlite3.Error:return False

def init_schema(db, now_fn):
 db.execute('CREATE TABLE IF NOT EXISTS exhibition_schema_migrations(version TEXT PRIMARY KEY,checksum TEXT NOT NULL,applied_at TEXT NOT NULL)')
 row=db.execute('SELECT checksum FROM exhibition_schema_migrations WHERE version=?',(VERSION,)).fetchone()
 if row:
  if row[0]!=CHECKSUM:raise RuntimeError('Exhibition migration checksum mismatch')
  if not schema_ready(db):raise RuntimeError('Exhibition migration tables missing')
  return False
 db.execute('SAVEPOINT exhibition_schema')
 try:
  for sql in DDL:db.execute(sql)
  now=now_fn()
  for item in standard_templates():
   item.update(id=uuid.uuid4().hex,created_at=now,updated_at=now)
   insert(db,'templates',item)
  db.execute('INSERT INTO exhibition_schema_migrations VALUES(?,?,?)',(VERSION,CHECKSUM,now))
  db.execute('RELEASE SAVEPOINT exhibition_schema')
 except Exception:
  db.execute('ROLLBACK TO SAVEPOINT exhibition_schema');db.execute('RELEASE SAVEPOINT exhibition_schema');raise
 return True

def insert(db,kind,row):
 db.execute(f'INSERT INTO {TABLES[kind]} ('+','.join('"'+x+'"' for x in row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))

def today():return datetime.now(ZoneInfo('Asia/Seoul')).date()
def iso_offset(start,offset):return (date.fromisoformat(start)+timedelta(days=offset)).isoformat()
def due(value,status='open'):
 delta=(date.fromisoformat(value)-today()).days if value else None
 return {'days_delta':delta,'due_status':('none' if delta is None or status in ('completed','cancelled','na','closed') else 'overdue' if delta<0 else 'today' if delta==0 else 'soon' if delta<=3 else 'normal')}
def amount(value):return round(float(value),6)
def product_key(row):
 if row.get('interim_product_code'):return 'interim:'+row['interim_product_code']
 value=row.get('product_code_snapshot') or row['product_name_snapshot']
 return ('code:' if row.get('product_code_snapshot') else 'name:')+unicodedata.normalize('NFKC',value.strip()).casefold()

class Fault(Exception):
 def __init__(self,message,status=400):super().__init__(message);self.status=status

def row_at(db,kind,id):
 row=db.execute(f'SELECT * FROM {TABLES[kind]} WHERE id=?',(id,)).fetchone()
 if not row:raise Fault('항목을 찾을 수 없습니다.',404)
 return dict(row)

def inventory(bundle):
 lines={}
 completed={r['id'] for r in bundle.get('shipments',[]) if r['is_active'] and r['status']=='completed'}
 def item(key,name=None,code=None):
  if key not in lines:lines[key]=dict(product_key=key,product_name=name or key,product_code=code or '',opening=0,sale=0,sample=0,other_out=0,adjustment=0,closing=0)
  return lines[key]
 for r in bundle.get('shipment_items',[]):
  if r['is_active'] and r['shipment_id'] in completed:
   item(r['product_key'],r['product_name_snapshot'],r['product_code_snapshot'])['opening']+=r['quantity']
 for kind,target in [('sales','sale'),('adjustments','adjustment'),('stock_uses',None)]:
  for r in bundle.get(kind,[]):
   if r['is_active']:item(r['product_key'])[target or r['use_type']]+=r['quantity']
 for r in lines.values():r['closing']=amount(r['opening']-r['sale']-r['sample']-r['other_out']+r['adjustment'])
 return sorted(lines.values(),key=lambda r:r['product_name'].casefold())

def load_bundle(db,event_id=None):
 """One query per relation, independent of event count; no N+1 detail queries."""
 where=' WHERE exhibition_id=?' if event_id else '';params=(event_id,) if event_id else ()
 bundle={k:[dict(r) for r in db.execute('SELECT * FROM '+t+where,params)] for k,t in TABLES.items() if k not in ('exhibitions','templates')}
 bundle['business_areas']=[dict(r) for r in db.execute('SELECT * FROM exhibition_business_areas'+where,params)]
 bundle['files']=[dict(r) for r in db.execute('SELECT id,exhibition_id,linked_kind,linked_id,original_name,sha256,size_bytes,version,is_active,created_by,created_at FROM exhibition_files'+where,params)]
 return bundle

def summarize(event,bundle):
 check=[r for r in bundle['checklist'] if r['is_active'] and r['status']!='na' and r['required']!='na']
 done=[r for r in check if r['status']=='completed'];remaining=[r for r in check if r['status']!='completed']
 late=[r for r in remaining if r['target_due_date'] and r['target_due_date']<today().isoformat()]
 follow=[r for r in bundle['followups'] if r['is_active'] and r['status']=='open']
 lead_pending=[r for r in bundle['leads'] if r['is_active'] and r['status'] not in ('closed',)]
 shipments=[r for r in bundle['shipments'] if r['is_active'] and r['status']!='cancelled']
 ship_missing=[r for r in shipments if r['status']!='completed']
 expenses=[r for r in bundle['expenses'] if r['is_active']]
 stocks=inventory(bundle);sales=[r for r in bundle['sales'] if r['is_active']]; meetings=[r for r in bundle['meetings'] if r['is_active']];leads=[r for r in bundle['leads'] if r['is_active']]
 currency={}
 for s in sales:
  bucket=currency.setdefault(s['currency'],dict(revenue=0,received=0,outstanding=0))
  total=amount(s['quantity']*s['unit_price']);bucket['revenue']+=total;bucket['received']+=s['received_amount'];bucket['outstanding']+=total-s['received_amount']
 budget=sum(r['budget']*r['krw_rate'] for r in expenses);actual=sum(r['actual']*r['krw_rate'] for r in expenses);subsidy=sum(r['subsidy_amount'] for r in expenses if r['subsidy_eligible'])
 alerts=[dict(kind='checklist',id=r['id'],title=r['title'],target_due_date=r['target_due_date'],**due(r['target_due_date'])) for r in late]
 for r in ship_missing:
  if not r['requested'] or (r['planned_date'] and r['planned_date']<today().isoformat()):alerts.append(dict(kind='shipments',id=r['id'],title=r['name']+(' · 출고요청 필요' if not r['requested'] else ' · 출고 지연'),target_due_date=r['planned_date'],**due(r['planned_date'])))
 payments=[r for r in expenses if r['actual']>0 and not r['payment_date']]
 return dict(total_checklist=len(check),completed_checklist=len(done),readiness=round(100*len(done)/len(check)) if check else 100,remaining=len(remaining),overdue=len(late),followup_open=len(follow),lead_followup_open=len(lead_pending),travelers=sum(r['is_active'] and r['role']=='traveler' for r in bundle['people']),shipment_count=len(shipments),shipment_pending=len(ship_missing),shipment_status='없음' if not shipments else '출고 완료' if not ship_missing else '출고 진행중',days_to_start=(date.fromisoformat(event['start_date'])-today()).days,budget_krw=round(budget),actual_krw=round(actual),subsidy_krw=round(subsidy),company_cost_krw=round(actual-subsidy),meeting_count=len(meetings),existing_customer_meetings=sum(bool(r['customer_id']) for r in meetings),lead_count=len(leads),qualified_leads=sum(r['status']=='qualified' for r in leads),sample_quantity=sum(r['sample'] for r in stocks),sale_quantity=sum(r['sale'] for r in stocks),sales_by_currency=currency,payment_pending=len(payments),alerts=alerts,remaining_items=[dict(id=r['id'],title=r['title'],kind='checklist') for r in remaining[:10]],payment_items=[dict(id=r['id'],title=r['description'],kind='expenses') for r in payments])

def register(app,get_db,role_required,csrf_required,audit_fn,now_fn,storage_root):
 def guard(fn):
  @wraps(fn)
  def wrapped(*a,**kw):
   try:return fn(*a,**kw)
   except Fault as exc:return jsonify(error=str(exc)),exc.status
  return wrapped
 def tx(fn):
  db=get_db()
  try:
   db.execute('BEGIN IMMEDIATE');result=fn(db);db.commit();return result
  except Fault as exc:db.rollback();return jsonify(error=str(exc)),exc.status
  except (ValueError,InvalidOperation) as exc:db.rollback();return jsonify(error=str(exc)),400
  except sqlite3.IntegrityError:
   db.rollback();return jsonify(error='연결 항목 또는 값의 제약을 확인하세요.'),400
  except Exception:db.rollback();raise
 def actor_fields(create=False):
  result=dict(updated_by=g.current_user['id'],updated_at=now_fn())
  if create:result.update(id=uuid.uuid4().hex,created_by=g.current_user['id'],created_at=result['updated_at'])
  return result
 def audit(kind,id,before,after,action=None):
  name=after.get('name') or after.get('title') or after.get('company_name') or after.get('description') or TITLES.get(kind,'Exhibition')
  audit_fn(action or ('EXHIBITION_'+('CREATE' if before is None else 'UPDATE') if kind=='exhibitions' else 'EXHIBITION_'+kind.upper()+'_'+('CREATE' if before is None else 'UPDATE')),TABLES[kind],id,name,before,after,connection=get_db())
 def parse():
  raw=request.get_json(silent=True)
  if not isinstance(raw,dict):raise Fault('JSON 입력을 확인하세요.')
  return raw
 def event_writable(db,event_id):
  ev=row_at(db,'exhibitions',event_id)
  if not ev['is_active']:raise Fault('보관된 행사입니다. 기본정보에서 복원하세요.',409)
  return ev
 def validate(db,kind,raw,old,event_id):
  fields=SPECS[kind];result={}
  extra={'version','is_active','business_areas'}
  unexpected=set(raw)-set(fields)-extra
  if unexpected:raise Fault('수정할 수 없는 필드: '+', '.join(sorted(unexpected)))
  for name,spec in fields.items():
   value=raw.get(name,old.get(name,spec['default']));typ=spec['type'];label=spec['label']
   if typ in ('integer','number'):
    try:
     n=Decimal(str(value))
     if not n.is_finite() or abs(n)>Decimal('100000000000000'):raise ValueError()
     if typ=='integer' and n!=n.to_integral_value():raise ValueError()
     value=int(n) if typ=='integer' else float(n)
    except (InvalidOperation,ValueError,TypeError):raise Fault(label+' 숫자를 확인하세요.')
   elif typ=='bool':
    if value not in (0,1,True,False):raise Fault(label+' 값을 확인하세요.')
    value=int(value)
   elif typ.startswith('ref:'):
    value=value or None
    if value is not None:
     target=typ.split(':')[1];table=TABLES.get(target,target)
     linked=db.execute('SELECT * FROM '+table+' WHERE id=?',(value,)).fetchone()
     if not linked:raise Fault(label+' 연결을 확인하세요.')
     if target in TABLES and dict(linked).get('exhibition_id')!=event_id:raise Fault('다른 행사의 항목을 연결할 수 없습니다.')
     if target=='users' and value!=old.get(name) and (linked['status']!='active' or linked['deleted_at']):raise Fault('활성 사용자를 선택하세요.')
     if target=='records' and linked['entity_type']!='cash_plan':raise Fault('자금계획 항목만 연결할 수 있습니다.')
     if target=='users':value=int(value)
   elif typ in ('date','datetime'):
    value=value or None
    if value:
     try:
      if typ=='date':
       if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
       date.fromisoformat(value)
      else:datetime.fromisoformat(value)
     except (ValueError,TypeError):raise Fault(label+' 날짜를 확인하세요.')
   else:
    if not isinstance(value,str):raise Fault(label+' 문자를 확인하세요.')
    value=value.strip()
    if len(value)>(10000 if typ=='textarea' else 1000):raise Fault(label+' 내용이 너무 깁니다.')
    if typ.startswith('choice:') and value not in CHOICES[typ.split(':')[1]]:raise Fault(label+' 값을 확인하세요.')
    if typ=='url' and value and not re.match(r'^https?://[^\s]+$',value):raise Fault('Website는 https:// 또는 http:// 주소로 입력하세요.')
    if typ=='email' and value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):raise Fault('Email 형식을 확인하세요.')
    if typ=='product' and value and value not in INTERIM_CONTRACT_PRODUCTS:raise Fault('제품 선택을 확인하세요.')
   if spec['required'] and (value is None or value==''):raise Fault(label+' 값이 필요합니다.')
   result[name]=value
  if 'is_active' in raw:
   if raw['is_active'] not in (0,1,True,False):raise Fault('활성상태를 확인하세요.')
   result['is_active']=int(raw['is_active'])
  if kind=='exhibitions':
   if result['end_date']<result['start_date']:raise Fault('종료일은 시작일 이후여야 합니다.')
  if kind in ('templates','checklist'):
   if result['situation'] not in SITUATIONS:raise Fault('Situation을 확인하세요.')
   if not -730<=result['offset_days']<=730:raise Fault('권장 Offset은 -730~730일입니다.')
  if kind=='checklist':
   start=row_at(db,'exhibitions',event_id)['start_date'];result['recommended_due_date']=iso_offset(start,result['offset_days'])
   if 'target_due_date' in raw and 'due_manual' not in raw:result['due_manual']=1
   if not result['due_manual']:result['target_due_date']=result['recommended_due_date']
   if result['required']=='na' or result['status']=='na':result['required']='na';result['status']='na'
   result['completed_at']=old.get('completed_at') or now_fn() if result['status']=='completed' else None
  if kind=='followups':result['completed_at']=old.get('completed_at') or now_fn() if result['status']=='completed' else None
  if kind=='shipments':
   if old.get('status')=='completed':raise Fault('출고완료 이력은 수정할 수 없습니다. 재고조정으로 기록하세요.',409)
   if result['method']=='other' and not result['other_method']:raise Fault('기타 운송방식을 설명하세요.')
   if result['requested'] and not result['request_date']:raise Fault('출고요청일을 입력하세요.')
   if result['status']=='completed':
    if not result['actual_date']:raise Fault('실제 출고일을 입력하세요.')
    lines=db.execute('SELECT * FROM exhibition_shipment_items WHERE shipment_id=? AND is_active=1',(old.get('id'),)).fetchall()
    if not lines:raise Fault('제품 Line을 먼저 등록하세요.')
  if kind=='shipment_items':
   ship=row_at(db,'shipments',result['shipment_id'])
   if ship['status']!='planned' or not ship['is_active']:raise Fault('출고 준비 상태에서만 제품을 수정할 수 있습니다.',409)
   if old and old['shipment_id']!=result['shipment_id']:raise Fault('제품 Line의 출고건은 변경할 수 없습니다.')
   if result['quantity']<=0:raise Fault('제품 수량은 0보다 커야 합니다.')
   result['product_key']=product_key(result)
  if kind in ('adjustments','stock_uses','sales'):
   stock={r['product_key']:r for r in inventory(load_bundle(db,event_id))}
   if result['product_key'] not in stock:raise Fault('출고완료 제품을 선택하세요.')
   if kind=='adjustments' and result['quantity']==0:raise Fault('조정 수량은 0일 수 없습니다.')
   if kind!='adjustments' and result['quantity']<=0:raise Fault('수량은 0보다 커야 합니다.')
   if kind in ('adjustments','stock_uses') and old:raise Fault('재고 이력은 수정하지 않습니다. 사유를 포함한 새 조정으로 기록하세요.',409)
  if kind=='sales':
   if result['unit_price']<0:raise Fault('단가는 음수일 수 없습니다.')
   total=amount(result['quantity']*result['unit_price'])
   if result['payment_status']=='paid':result['received_amount']=total
   elif result['payment_status']=='unpaid':result['received_amount']=0
   elif not 0<result['received_amount']<total:raise Fault('부분수금액은 0보다 크고 판매금액보다 작아야 합니다.')
  if kind=='meetings' and result['contact_id']:
   linked=db.execute('SELECT customer_id,deleted_at FROM customer_contacts WHERE id=?',(result['contact_id'],)).fetchone()
   if linked['customer_id']!=result['customer_id'] or linked['deleted_at']:raise Fault('선택 Customer의 활성 Contact를 선택하세요.')
  if kind in ('expenses','sales','pavilion','support'):
   result['currency']=result['currency'].upper()
   if not re.fullmatch('[A-Z]{3}',result['currency']):raise Fault('통화는 USD, KRW 등 3자리 코드입니다.')
  if kind=='expenses':
   if min(result['budget'],result['actual'],result['subsidy_amount'])<0 or result['krw_rate']<=0:raise Fault('비용은 0 이상, 환율은 0보다 커야 합니다.')
   if result['currency']=='KRW':result['krw_rate']=1
   if result['subsidy_amount']>result['actual']*result['krw_rate']+0.01:raise Fault('지원금은 실제비용을 초과할 수 없습니다.')
  return result
 def update_row(db,kind,old,values,version):
  if type(version)!=int or version!=old['version']:raise Fault('다른 사용자가 수정했습니다. 새로고침 후 다시 저장하세요.',409)
  values.update(actor_fields());values['version']=version+1
  cur=db.execute('UPDATE '+TABLES[kind]+' SET '+','.join('"'+k+'"=?' for k in values)+' WHERE id=? AND version=?',tuple(values.values())+(old['id'],version))
  if cur.rowcount!=1:raise Fault('다른 사용자가 수정했습니다.',409)
  after=row_at(db,kind,old['id']);audit(kind,old['id'],old,after)
  return after
 def business_areas(db,event,raw,create=False):
  values=raw.get('business_areas')
  if values is None:
   values=[r[0] for r in db.execute('SELECT business_area FROM exhibition_business_areas WHERE exhibition_id=?',(event['id'],))] or [event['primary_business_area']]
  if not isinstance(values,list) or not values or any(v not in CHOICES['business'] for v in values):raise Fault('사업분야를 1개 이상 선택하세요.')
  if event['primary_business_area'] not in values:raise Fault('Primary 사업분야는 선택 사업분야에 포함되어야 합니다.')
  before=[r[0] for r in db.execute('SELECT business_area FROM exhibition_business_areas WHERE exhibition_id=?',(event['id'],))]
  if sorted(set(values))!=sorted(before):
   db.execute('DELETE FROM exhibition_business_areas WHERE exhibition_id=?',(event['id'],))
   db.executemany('INSERT INTO exhibition_business_areas VALUES(?,?)',[(event['id'],v) for v in sorted(set(values))])
   audit_fn('EXHIBITION_BUSINESS_AREAS_CHANGE','exhibitions',event['id'],'사업분야 변경',before,sorted(set(values)),connection=db)
 def full_detail(db,id):
  ev=row_at(db,'exhibitions',id);bundle=load_bundle(db,id)
  for r in bundle['checklist']:r.update(due(r['target_due_date'],r['status']))
  for r in bundle['followups']:r.update(due(r['target_due_date'],r['status']))
  for r in bundle['sales']:r['amount']=amount(r['quantity']*r['unit_price'])
  for r in bundle['expenses']:r.update(budget_krw=round(r['budget']*r['krw_rate']),actual_krw=round(r['actual']*r['krw_rate']),company_cost_krw=round(r['actual']*r['krw_rate']-r['subsidy_amount']))
  ev['business_areas']=[r['business_area'] for r in bundle.pop('business_areas')]
  return dict(event=ev,**bundle,inventory=inventory(bundle),summary=summarize(ev,bundle))

 @app.get('/api/exhibitions/options')
 @role_required(*READ_ROLES)
 def exhibition_options():
  db=get_db()
  return jsonify(choices=CHOICES,fields=SPECS,titles=TITLES,situations=SITUATIONS,products=INTERIM_CONTRACT_PRODUCTS,permissions={'write':g.current_user['role'] in WRITE_ROLES},users=[dict(r) for r in db.execute('SELECT id,display_name,status FROM users WHERE deleted_at IS NULL ORDER BY display_name')],customers=[dict(r) for r in db.execute('SELECT id,display_name,country_code FROM customer_master ORDER BY display_name')],contacts=[dict(r) for r in db.execute("SELECT id,customer_id,contact_name,department_title FROM customer_contacts WHERE deleted_at IS NULL AND employment_status='active'")],rates=[dict(r) for r in db.execute('SELECT * FROM exchange_rates ORDER BY rate_date DESC,currency')],cash_plans=[dict(r) for r in db.execute("SELECT id,title FROM records WHERE entity_type='cash_plan' AND deleted_at IS NULL")],schema_version=VERSION)

 @app.get('/api/exhibitions')
 @role_required(*READ_ROLES)
 @guard
 def exhibition_list():
  db=get_db();events=[dict(r) for r in db.execute('SELECT * FROM exhibitions WHERE is_active=1 ORDER BY start_date,name,id')];all_bundle=load_bundle(db)
  grouped={e['id']:{k:[] for k in all_bundle} for e in events}
  for k,rows in all_bundle.items():
   for row in rows:
    if row['exhibition_id'] in grouped:grouped[row['exhibition_id']][k].append(row)
  year=str(today().year);annual=[e for e in events if e['start_date'][:4]==year];summaries={e['id']:summarize(e,grouped[e['id']]) for e in events}
  kpi=dict(year=int(year),total=len(annual),exhibiting=sum(e['participation']=='exhibiting' for e in annual),visiting=sum(e['participation']=='visiting' for e in annual),candidate=sum(e['participation']=='candidate' for e in annual),this_month=sum(e['start_date'][:7]<=today().isoformat()[:7]<=e['end_date'][:7] for e in events),overdue=sum(s['overdue'] for s in summaries.values()),followup_open=sum(s['followup_open'] for s in summaries.values()),budget_krw=sum(summaries[e['id']]['budget_krw'] for e in annual),actual_krw=sum(summaries[e['id']]['actual_krw'] for e in annual))
  result=[]
  for e in events:
   b=grouped[e['id']];e['business_areas']=[r['business_area'] for r in b['business_areas']];e['pavilion']=next((r['available'] for r in b['pavilion'] if r['is_active']),'unknown');e['people_ids']=[r['user_id'] for r in b['people'] if r['is_active']];e['summary']=summaries[e['id']]
   q=request.args
   if q.get('year') and e['start_date'][:4]!=q['year']:continue
   if q.get('month') and e['start_date'][5:7]!=q['month'].zfill(2):continue
   if any(q.get(k) and e[k]!=q[k] for k in ('country','city','importance','relationship','participation','pavilion')):continue
   if q.get('business_area') and q['business_area'] not in e['business_areas']:continue
   if q.get('person_id') and str(e['owner_id'])!=q['person_id'] and q['person_id'] not in [str(v) for v in e['people_ids']]:continue
   if q.get('from') and e['end_date']<q['from']:continue
   if q.get('to') and e['start_date']>q['to']:continue
   result.append(e)
  return jsonify(items=result,kpi=kpi,today=today().isoformat())

 @app.get('/api/exhibitions/templates')
 @role_required(*READ_ROLES)
 def exhibition_templates():return jsonify(items=[dict(r) for r in get_db().execute('SELECT * FROM exhibition_templates ORDER BY sort_order,id')])

 @app.get('/api/exhibitions/<event_id>')
 @role_required(*READ_ROLES)
 @guard
 def exhibition_detail(event_id):return jsonify(full_detail(get_db(),event_id))

 @app.post('/api/exhibitions')
 @role_required(*WRITE_ROLES)
 @csrf_required
 def exhibition_create():
  def work(db):
   raw=parse();values=validate(db,'exhibitions',raw,{},None);values.update(actor_fields(True));insert(db,'exhibitions',values);ev=row_at(db,'exhibitions',values['id']);business_areas(db,ev,raw,True)
   for t in db.execute('SELECT * FROM exhibition_templates WHERE is_active=1 ORDER BY sort_order,id').fetchall():
    item={k:t[k] for k in ('situation','title','required','offset_days','sort_order')};item.update(actor_fields(True));item.update(exhibition_id=ev['id'],template_id=t['id'],recommended_due_date=iso_offset(ev['start_date'],t['offset_days']),target_due_date=iso_offset(ev['start_date'],t['offset_days']),status='na' if t['required']=='na' else 'not_started');insert(db,'checklist',item)
   pavilion=actor_fields(True);pavilion['exhibition_id']=ev['id'];insert(db,'pavilion',pavilion)
   audit('exhibitions',ev['id'],None,{**ev,'standard_checklist_count':db.execute('SELECT COUNT(*) FROM exhibition_checklist WHERE exhibition_id=?',(ev['id'],)).fetchone()[0]})
   return jsonify(full_detail(db,ev['id'])),201
  return tx(work)

 @app.patch('/api/exhibitions/<event_id>')
 @role_required(*WRITE_ROLES)
 @csrf_required
 def exhibition_update(event_id):
  def work(db):
   raw=parse();old=row_at(db,'exhibitions',event_id);values=validate(db,'exhibitions',raw,old,event_id);after=update_row(db,'exhibitions',old,values,raw.get('version'));business_areas(db,after,raw)
   if after['participation']!=old['participation']:audit('exhibitions',event_id,old,after,'EXHIBITION_PARTICIPATION_CHANGE')
   if after['start_date']!=old['start_date']:
    for row in db.execute('SELECT * FROM exhibition_checklist WHERE exhibition_id=?',(event_id,)).fetchall():
     r=dict(row);change={'recommended_due_date':iso_offset(after['start_date'],r['offset_days'])}
     if not r['due_manual']:change['target_due_date']=change['recommended_due_date']
     update_row(db,'checklist',r,change,r['version'])
   return jsonify(full_detail(db,event_id))
  return tx(work)

 @app.post('/api/exhibitions/<event_id>/<kind>')
 @role_required(*WRITE_ROLES)
 @csrf_required
 def exhibition_child_create(event_id,kind):
  def work(db):
   if kind not in SPECS or kind in ('exhibitions','templates'):raise Fault('지원하지 않는 항목입니다.',404)
   event_writable(db,event_id);raw=parse();values=validate(db,kind,raw,{},event_id);values.update(actor_fields(True));values['exhibition_id']=event_id;insert(db,kind,values);after=row_at(db,kind,values['id'])
   if kind in ('sales','adjustments','stock_uses') and any(r['closing']< -0.000001 for r in inventory(load_bundle(db,event_id))):raise Fault('현장 재고가 부족합니다. 출고완료 또는 사유가 있는 재고조정을 먼저 확인하세요.',409)
   audit(kind,after['id'],None,after,'EXHIBITION_INVENTORY_ADJUST' if kind=='adjustments' else None)
   return jsonify(item=after),201
  return tx(work)

 @app.patch('/api/exhibitions/items/<kind>/<item_id>')
 @role_required(*WRITE_ROLES)
 @csrf_required
 def exhibition_child_update(kind,item_id):
  def work(db):
   if kind not in SPECS or kind=='exhibitions':raise Fault('지원하지 않는 항목입니다.',404)
   old=row_at(db,kind,item_id);event_id=old.get('exhibition_id')
   if event_id:event_writable(db,event_id)
   raw=parse();values=validate(db,kind,raw,old,event_id);after=update_row(db,kind,old,values,raw.get('version'))
   if kind in ('sales','adjustments','stock_uses') and any(r['closing']< -0.000001 for r in inventory(load_bundle(db,event_id))):raise Fault('재고 부족으로 수정할 수 없습니다.',409)
   if kind=='shipments' and after['status']=='completed':audit(kind,item_id,old,after,'EXHIBITION_SHIPMENT_COMPLETE')
   if kind in ('checklist','followups') and old['status']!=after['status']:audit(kind,item_id,old,after,'EXHIBITION_'+('CHECKLIST' if kind=='checklist' else 'FOLLOWUP')+('_COMPLETE' if after['status']=='completed' else '_REOPEN' if old['status']=='completed' else '_STATUS_CHANGE'))
   return jsonify(item=after)
  return tx(work)

 @app.post('/api/exhibitions/<event_id>/files')
 @role_required(*WRITE_ROLES)
 @csrf_required
 def exhibition_file_create(event_id):
  created_path=None
  def work(db):
   nonlocal created_path
   event_writable(db,event_id);kind=request.form.get('linked_kind','exhibitions');linked=request.form.get('linked_id',event_id)
   if kind not in TABLES or kind=='templates':raise Fault('증빙 연결을 확인하세요.')
   row=row_at(db,kind,linked)
   if (row['id'] if kind=='exhibitions' else row.get('exhibition_id'))!=event_id:raise Fault('같은 행사에만 증빙을 연결할 수 있습니다.')
   file=request.files.get('file')
   if not file or not file.filename:raise Fault('파일을 선택하세요.')
   content=file.stream.read(10*1024*1024+1)
   if not content or len(content)>10*1024*1024:raise Fault('파일은 10MB 이내로 올려주세요.')
   meta=actor_fields(True);meta.update(exhibition_id=event_id,linked_kind=kind,linked_id=linked,original_name=Path(file.filename.replace('\\','/')).name[:200],storage_name=uuid.uuid4().hex,sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content))
   folder=Path(storage_root)/'exhibitions';folder.mkdir(parents=True,exist_ok=True);created_path=folder/meta['storage_name'];created_path.write_bytes(content)
   db.execute('INSERT INTO exhibition_files ('+','.join(meta)+') VALUES('+','.join('?' for _ in meta)+')',tuple(meta.values()))
   safe={k:v for k,v in meta.items() if k!='storage_name'};audit_fn('EXHIBITION_FILE_CREATE','exhibition_files',meta['id'],meta['original_name'],None,safe,connection=db)
   return jsonify(item=safe),201
  try:
   result=tx(work)
   if isinstance(result,tuple) and result[1]>=400 and created_path:created_path.unlink(missing_ok=True)
   return result
  except Exception:
   if created_path:created_path.unlink(missing_ok=True)
   raise

 @app.get('/api/exhibitions/files/<file_id>')
 @role_required(*READ_ROLES)
 @guard
 def exhibition_file_download(file_id):
  row=get_db().execute('SELECT * FROM exhibition_files WHERE id=? AND is_active=1',(file_id,)).fetchone()
  if not row:raise Fault('파일을 찾을 수 없습니다.',404)
  path=Path(storage_root)/'exhibitions'/row['storage_name']
  if not path.is_file():raise Fault('파일을 찾을 수 없습니다.',404)
  response=send_file(path,as_attachment=True,download_name=row['original_name'],mimetype='application/octet-stream');response.headers['X-Content-Type-Options']='nosniff';return response
