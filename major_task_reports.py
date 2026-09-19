"""대표님 보고서 drafts and immutable final snapshots; never write source tasks."""
import functools
import hashlib
import json
import uuid
from flask import g, jsonify, request
import major_tasks as mt
import stage_work_items as work

VERSION = 'major-tasks-2026-09-20-executive-reports-v1'
DDL = [
'''CREATE TABLE IF NOT EXISTS major_task_reports (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, report_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','final')),
 snapshot_json TEXT, completed_at TEXT, version INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL REFERENCES users(id),updated_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 CHECK((status='final' AND snapshot_json IS NOT NULL AND completed_at IS NOT NULL) OR
       (status='draft' AND snapshot_json IS NULL AND completed_at IS NULL)))''',
'''CREATE TABLE IF NOT EXISTS major_task_report_items (
 id TEXT PRIMARY KEY,report_id TEXT NOT NULL REFERENCES major_task_reports(id) ON DELETE RESTRICT,
 task_id TEXT NOT NULL REFERENCES major_tasks(id) ON DELETE RESTRICT,
 report_text TEXT NOT NULL DEFAULT '',decision_text TEXT NOT NULL DEFAULT '',
 work_items_json TEXT NOT NULL DEFAULT '[]',sort_order INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1,created_by INTEGER NOT NULL REFERENCES users(id),
 updated_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(report_id,task_id))''',
'''CREATE TABLE IF NOT EXISTS major_task_report_comments (
 id TEXT PRIMARY KEY,report_item_id TEXT NOT NULL REFERENCES major_task_report_items(id) ON DELETE RESTRICT,
 body TEXT NOT NULL CHECK(length(trim(body)) BETWEEN 1 AND 3000),version INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL REFERENCES users(id),updated_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
'''CREATE TRIGGER IF NOT EXISTS major_report_final_update BEFORE UPDATE ON major_task_reports
 WHEN OLD.status='final' BEGIN SELECT RAISE(ABORT,'Final report is immutable'); END''',
'''CREATE TRIGGER IF NOT EXISTS major_report_final_delete BEFORE DELETE ON major_task_reports
 WHEN OLD.status='final' BEGIN SELECT RAISE(ABORT,'Final report is immutable'); END''',
]
for table, expr in [('major_task_report_items','SELECT status FROM major_task_reports WHERE id={ref}.report_id'),
                    ('major_task_report_comments','SELECT r.status FROM major_task_reports r JOIN major_task_report_items i ON i.report_id=r.id WHERE i.id={ref}.report_item_id')]:
    for op in ('INSERT','UPDATE','DELETE'):
        ref = 'OLD' if op=='DELETE' else 'NEW'
        condition = f"({expr.format(ref=ref)})='final'"
        if op == 'UPDATE': condition += f" OR ({expr.format(ref='OLD')})='final'"
        DDL.append(f"CREATE TRIGGER IF NOT EXISTS {table}_final_{op.lower()} BEFORE {op} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'Final report is immutable'); END")
CHECKSUM=hashlib.sha256('\n'.join(DDL).encode()).hexdigest()


def schema_ready(db):
    row=db.execute('SELECT checksum FROM major_task_schema_migrations WHERE version=?',(VERSION,)).fetchone()
    return bool(row and row[0]==CHECKSUM)


def init_schema(db,now_fn):
    row=db.execute('SELECT checksum FROM major_task_schema_migrations WHERE version=?',(VERSION,)).fetchone()
    if row:
        if row[0]!=CHECKSUM:raise RuntimeError('Report migration checksum mismatch')
        return False
    db.execute('SAVEPOINT report_schema')
    try:
        for sql in DDL:db.execute(sql)
        db.execute('INSERT INTO major_task_schema_migrations VALUES(?,?,?)',(VERSION,CHECKSUM,now_fn()))
        db.execute('RELEASE report_schema')
    except Exception:
        db.execute('ROLLBACK TO report_schema');db.execute('RELEASE report_schema');raise
    return True


def dump(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def text_field(data,key,default='',limit=6000):
    value=data.get(key,default)
    if not isinstance(value,str) or len(value)>limit:raise ValueError('입력 길이 또는 형식을 확인하세요.')
    return value.strip()


def live_task(db,task_id):
    task=mt._task_row(db,task_id)
    if not task:raise ValueError('선택한 주요업무를 찾을 수 없습니다.')
    item=mt._serialize_task(db,task,False,g.current_user)
    all_work=work.detail_items(db,task_id,mt._today())
    keys=['id','title','owner_name','owner_display','current_stage_name','final_rag','operational_due',
          'current_target_date','blocker_active','blocker_description','ball_summary','status','version','stage_pipeline']
    result={k:item.get(k) for k in keys}
    result['owners']=[{'id':p['user_id'] if 'user_id' in p else p.get('id'),'name':p['display_name'],'is_primary':p['is_primary']} for p in item.get('owners',[])]
    result['open_work_items']=[w for w in all_work if w['status']=='open']
    result['flagged_work_items']=[w for w in all_work if w['status']!='cancelled' and (w['report_required'] or w['decision_required'])]
    return result


def candidate(w):
    return {k:w.get(k) for k in ['id','content','stage_name','assignee_name','target_due_date','ball_label','status','report_required','decision_required','decision_request']}|{'include':True}


def draft_detail(db,report):
    report=dict(report)
    if report['status']=='final':
        return {'report':{k:v for k,v in report.items() if k!='snapshot_json'},'snapshot':json.loads(report['snapshot_json']),'items':[]}
    items=[]
    for row in db.execute('SELECT * FROM major_task_report_items WHERE report_id=? ORDER BY sort_order,id',(report['id'],)):
        item=dict(row);item['work_items']=json.loads(item.pop('work_items_json'));item['task']=live_task(db,item['task_id'])
        item['comments']=[dict(r) for r in db.execute('SELECT c.*,u.display_name AS author_name FROM major_task_report_comments c JOIN users u ON u.id=c.created_by WHERE c.report_item_id=? ORDER BY c.created_at,c.id',(item['id'],))]
        items.append(item)
    report.pop('snapshot_json')
    return {'report':report,'items':items}


def register(app,get_db,role_required,csrf_required,audit_fn):
    def guarded(fn):
        @functools.wraps(fn)
        def call(*a,**kw):
            try:return fn(*a,**kw)
            except (ValueError,TypeError) as exc:
                get_db().rollback();return jsonify(error=str(exc)),400
        return call
    def payload():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise ValueError('입력 형식을 확인하세요.')
        return data
    def lock(report_id,data):
        db=get_db();expected=mt._version(data);db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM major_task_reports WHERE id=?',(report_id,)).fetchone()
        if not row:db.rollback();return None,(jsonify(error='보고서를 찾을 수 없습니다.'),404)
        if row['version']!=expected:db.rollback();return None,(jsonify(error='다른 사용자가 먼저 수정했습니다.',code='VERSION_CONFLICT'),409)
        if row['status']!='draft':db.rollback();return None,(jsonify(error='최종 완료된 보고서는 변경할 수 없습니다.'),409)
        return row,None
    def bump(db,row):
        db.execute('UPDATE major_task_reports SET version=version+1,updated_by=?,updated_at=? WHERE id=?',(g.current_user['id'],mt._now(),row['id']))
    def emit(action,report_id,before,after):
        mt._audit(audit_fn,'MAJOR_TASK_REPORT_'+action,'major_task_report',report_id,'대표님 보고서 '+action,before,after)

    @app.get('/api/major-task-reports/candidates')
    @role_required(*mt.READ_ROLES)
    def candidates():
        rows=get_db().execute('''SELECT t.id,t.title,t.parent_task_id,t.final_rag,t.status,u.display_name AS owner_name,
            s.name AS current_stage_name FROM major_tasks t LEFT JOIN users u ON u.id=t.owner_id
            LEFT JOIN major_task_stages s ON s.id=t.current_stage_id WHERE t.status<>'cancelled' ORDER BY t.title,t.id''')
        return jsonify(items=[dict(r) for r in rows])

    @app.get('/api/major-task-reports')
    @role_required(*mt.READ_ROLES)
    def report_list():
        rows=get_db().execute('SELECT r.id,r.title,r.report_date,r.status,r.version,r.created_at,r.completed_at,u.display_name AS author_name FROM major_task_reports r JOIN users u ON u.id=r.created_by ORDER BY r.created_at DESC,r.id DESC')
        return jsonify(items=[dict(r) for r in rows],can_write=g.current_user['role'] in mt.WRITE_ROLES)

    @app.get('/api/major-task-reports/<report_id>')
    @role_required(*mt.READ_ROLES)
    def report_get(report_id):
        db=get_db();r=db.execute('SELECT * FROM major_task_reports WHERE id=?',(report_id,)).fetchone()
        if not r:return jsonify(error='보고서를 찾을 수 없습니다.'),404
        return jsonify(**draft_detail(db,r))

    @app.post('/api/major-task-reports')
    @role_required(*mt.WRITE_ROLES)
    @csrf_required
    @guarded
    def report_create():
        data=payload();ids=data.get('task_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise ValueError('보고할 주요업무를 1~100개 선택하세요.')
        title=text_field(data,'title','대표님 보고서',200) or '대표님 보고서';day=mt._date(data.get('report_date') or mt._today().isoformat(),'보고일')
        db=get_db();db.execute('BEGIN IMMEDIATE');now=mt._now();actor=g.current_user['id'];rid=uuid.uuid4().hex
        tasks=[live_task(db,x) for x in ids]
        db.execute('INSERT INTO major_task_reports(id,title,report_date,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(rid,title,day,actor,actor,now,now))
        for i,t in enumerate(tasks):
            db.execute('INSERT INTO major_task_report_items(id,report_id,task_id,work_items_json,sort_order,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,rid,t['id'],dump([candidate(w) for w in t['flagged_work_items']]),i,actor,actor,now,now))
        emit('CREATE',rid,None,dict(title=title,report_date=day,task_ids=ids));db.commit()
        return jsonify(**draft_detail(db,db.execute('SELECT * FROM major_task_reports WHERE id=?',(rid,)).fetchone())),201

    @app.patch('/api/major-task-reports/<report_id>/items/<item_id>')
    @role_required(*mt.WRITE_ROLES)
    @csrf_required
    @guarded
    def item_update(report_id,item_id):
        data=payload();r,error=lock(report_id,data)
        if error:return error
        db=get_db();row=db.execute('SELECT * FROM major_task_report_items WHERE id=? AND report_id=?',(item_id,report_id)).fetchone()
        if not row:db.rollback();return jsonify(error='보고 항목을 찾을 수 없습니다.'),404
        report_text=text_field(data,'report_text',row['report_text']);decision_text=text_field(data,'decision_text',row['decision_text'])
        chosen=data.get('work_items',json.loads(row['work_items_json']))
        old_candidates={x['id']:x for x in json.loads(row['work_items_json'])}
        if not isinstance(chosen,list) or len(chosen)>200 or any(not isinstance(x,dict) or x.get('id') not in old_candidates for x in chosen):raise ValueError('보고 후보 항목을 확인하세요.')
        if len({x['id'] for x in chosen})!=len(chosen):raise ValueError('보고 후보가 중복되었습니다.')
        values=[]
        for x in chosen:
            if not isinstance(x.get('include',True),bool):raise ValueError('포함 여부를 확인하세요.')
            v={**old_candidates[x['id']], 'include':x.get('include',True)}
            v['content']=text_field(x,'content',v['content'],1000)
            v['decision_request']=text_field({**x,'decision_request':x.get('decision_request') or ''},'decision_request',limit=3000)
            values.append(v)
        db.execute('UPDATE major_task_report_items SET report_text=?,decision_text=?,work_items_json=?,version=version+1,updated_by=?,updated_at=? WHERE id=?',(report_text,decision_text,dump(values),g.current_user['id'],mt._now(),item_id))
        bump(db,r);after=dict(db.execute('SELECT * FROM major_task_report_items WHERE id=?',(item_id,)).fetchone());emit('ITEM_UPDATE',report_id,dict(row),after);db.commit()
        return jsonify(**draft_detail(db,db.execute('SELECT * FROM major_task_reports WHERE id=?',(report_id,)).fetchone()))

    @app.post('/api/major-task-reports/<report_id>/items/<item_id>/comments')
    @role_required(*mt.WRITE_ROLES)
    @csrf_required
    @guarded
    def comment_add(report_id,item_id):
        data=payload();body=text_field(data,'body',limit=3000)
        if not body:raise ValueError('담당자 코멘트를 입력하세요.')
        r,error=lock(report_id,data)
        if error:return error
        db=get_db()
        if not db.execute('SELECT 1 FROM major_task_report_items WHERE id=? AND report_id=?',(item_id,report_id)).fetchone():db.rollback();return jsonify(error='보고 항목을 찾을 수 없습니다.'),404
        now=mt._now();actor=g.current_user['id'];cid=uuid.uuid4().hex
        db.execute('INSERT INTO major_task_report_comments(id,report_item_id,body,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(cid,item_id,body,actor,actor,now,now));bump(db,r);emit('COMMENT_CREATE',report_id,None,dict(id=cid,report_item_id=item_id,body=body,author_id=actor));db.commit()
        return jsonify(**draft_detail(db,db.execute('SELECT * FROM major_task_reports WHERE id=?',(report_id,)).fetchone())),201

    @app.post('/api/major-task-reports/<report_id>/finalize')
    @role_required(*mt.WRITE_ROLES)
    @csrf_required
    @guarded
    def report_finalize(report_id):
        data=payload();r,error=lock(report_id,data)
        if error:return error
        db=get_db();detail=draft_detail(db,r);now=mt._now()
        snapshot={'title':r['title'],'report_date':r['report_date'],'created_at':r['created_at'],'completed_at':now,'created_by':r['created_by'],'completed_by':g.current_user['id'],'items':detail['items']}
        for item in snapshot['items']:
            # Keep the existing snapshot envelope and candidate API. Decisions are
            # captured from the Work Item ledger at finalization, never from a
            # report-only edited copy; no separate decision field/ledger is added.
            canonical={w['id']:w for w in item['task']['flagged_work_items']}
            chosen={w['id']:w for w in item['work_items']}
            for wid, saved in chosen.items():
                current=canonical.get(wid,{})
                saved['decision_required']=current.get('decision_required',0)
                saved['decision_request']=current.get('decision_request') if saved['decision_required'] else None
            for wid, current in canonical.items():
                if wid not in chosen and current['decision_required']:
                    item['work_items'].append(candidate(current))
            excluded={x['id'] for x in item['work_items'] if not x['include']}
            item['task']['open_work_items']=[x for x in item['task']['open_work_items'] if x['id'] not in excluded]
            item['work_items']=[x for x in item['work_items'] if x['include']]
            item['task'].pop('flagged_work_items',None)
        db.execute("UPDATE major_task_reports SET status='final',snapshot_json=?,completed_at=?,version=version+1,updated_by=?,updated_at=? WHERE id=?",(dump(snapshot),now,g.current_user['id'],now,report_id))
        emit('FINALIZE',report_id,{'status':'draft','version':r['version']},{'status':'final','snapshot_sha256':hashlib.sha256(dump(snapshot).encode()).hexdigest()});db.commit()
        return jsonify(**draft_detail(db,db.execute('SELECT * FROM major_task_reports WHERE id=?',(report_id,)).fetchone()))
