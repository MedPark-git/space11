"""Major Task binary documents in persistent runtime storage, not SQLite BLOBs."""
import functools
import hashlib
import io
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from flask import g, jsonify, request, send_file
import major_tasks as mt

VERSION='major-tasks-2026-09-20-report-composition-documents-v1'
FILE_LIMIT=10*1024*1024
TOTAL_LIMIT=200*1024*1024
RUNTIME_LIMIT=768*1024*1024  # audited Cafe24 project quota: 1024 MB; reserve headroom
DDL=[
'''CREATE TABLE IF NOT EXISTS major_task_documents (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES major_tasks(id) ON DELETE RESTRICT,
 original_name TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL,
 size_bytes INTEGER NOT NULL CHECK(size_bytes>0 AND size_bytes<=10485760), mime_type TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', replaces_document_id TEXT REFERENCES major_task_documents(id) ON DELETE RESTRICT,
 revision INTEGER NOT NULL DEFAULT 1, is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
 version INTEGER NOT NULL DEFAULT 1,created_by INTEGER NOT NULL REFERENCES users(id),updated_by INTEGER NOT NULL REFERENCES users(id),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL, UNIQUE(replaces_document_id))''',
'''CREATE INDEX IF NOT EXISTS major_task_documents_task ON major_task_documents(task_id,is_active,created_at)''',
'''CREATE TABLE IF NOT EXISTS major_task_report_documents (
 report_item_id TEXT NOT NULL REFERENCES major_task_report_items(id) ON DELETE RESTRICT,
 document_id TEXT NOT NULL REFERENCES major_task_documents(id) ON DELETE RESTRICT,
 created_by INTEGER NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,
 PRIMARY KEY(report_item_id,document_id))''',
'''CREATE TRIGGER IF NOT EXISTS major_task_document_no_delete BEFORE DELETE ON major_task_documents
 BEGIN SELECT RAISE(ABORT,'Documents are retained; use soft delete'); END''',
'''CREATE TRIGGER IF NOT EXISTS major_task_document_content_immutable BEFORE UPDATE ON major_task_documents
 WHEN NEW.id IS NOT OLD.id OR NEW.task_id IS NOT OLD.task_id OR NEW.storage_name IS NOT OLD.storage_name
 OR NEW.sha256 IS NOT OLD.sha256 OR NEW.size_bytes IS NOT OLD.size_bytes OR NEW.original_name IS NOT OLD.original_name
 OR NEW.mime_type IS NOT OLD.mime_type OR NEW.revision IS NOT OLD.revision OR NEW.replaces_document_id IS NOT OLD.replaces_document_id
 OR NEW.created_by IS NOT OLD.created_by OR NEW.created_at IS NOT OLD.created_at
 BEGIN SELECT RAISE(ABORT,'Upload a new document version'); END''',
'''CREATE TRIGGER IF NOT EXISTS major_report_document_task_match BEFORE INSERT ON major_task_report_documents
 WHEN (SELECT task_id FROM major_task_report_items WHERE id=NEW.report_item_id) IS NOT
 (SELECT task_id FROM major_task_documents WHERE id=NEW.document_id)
 BEGIN SELECT RAISE(ABORT,'Document must belong to report task'); END''',
]
for op in ('INSERT','UPDATE','DELETE'):
 refs=['OLD'] if op=='DELETE' else ['NEW','OLD'] if op=='UPDATE' else ['NEW']
 test=' OR '.join("(SELECT r.status FROM major_task_reports r JOIN major_task_report_items i ON i.report_id=r.id WHERE i.id="+ref+".report_item_id)='final'" for ref in refs)
 DDL.append(f"CREATE TRIGGER IF NOT EXISTS major_report_document_final_{op.lower()} BEFORE {op} ON major_task_report_documents WHEN {test} BEGIN SELECT RAISE(ABORT,'Final report is immutable'); END")
CHECKSUM=hashlib.sha256(('ADD major_task_report_items.is_active INTEGER NOT NULL DEFAULT 1\n'+'\n'.join(DDL)).encode()).hexdigest()

def schema_ready(db):
 r=db.execute('SELECT checksum FROM major_task_schema_migrations WHERE version=?',(VERSION,)).fetchone()
 return bool(r and r[0]==CHECKSUM)

def init_schema(db,now_fn):
 r=db.execute('SELECT checksum FROM major_task_schema_migrations WHERE version=?',(VERSION,)).fetchone()
 if r:
  if r[0]!=CHECKSUM:raise RuntimeError('Report documents migration checksum mismatch')
  return False
 db.execute('SAVEPOINT report_documents_schema')
 try:
  if 'is_active' not in {r[1] for r in db.execute('PRAGMA table_info(major_task_report_items)')}:db.execute('ALTER TABLE major_task_report_items ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
  for sql in DDL:db.execute(sql)
  db.execute('INSERT INTO major_task_schema_migrations VALUES(?,?,?)',(VERSION,CHECKSUM,now_fn()))
  db.execute('RELEASE report_documents_schema')
 except Exception:
  db.execute('ROLLBACK TO report_documents_schema');db.execute('RELEASE report_documents_schema');raise
 return True

class Fault(ValueError):
 def __init__(self,message,status=400):super().__init__(message);self.status=status

def folder(db):
 path=next(r[2] for r in db.execute('PRAGMA database_list') if r[1]=='main')
 if not path:raise Fault('영구 파일 저장영역을 확인할 수 없습니다.',503)
 return Path(path).resolve().parent/'major_task_documents'

def usage(db):
 root=folder(db).parent; scope=root.parent if root.name=='runtime' else root
 used=sum(p.stat().st_size for p in scope.rglob('*') if p.is_file() and not p.is_symlink())
 total=db.execute('SELECT COALESCE(SUM(size_bytes),0) FROM major_task_documents').fetchone()[0]
 return dict(file_limit=FILE_LIMIT,total_limit=TOTAL_LIMIT,used_bytes=total,runtime_bytes=used,runtime_limit=RUNTIME_LIMIT,retains_deleted=True)

def metadata(row):
 d=dict(row);d.pop('storage_name',None)
 d['download_url']='/api/major-task-documents/'+d['id']+'/download'
 return d

def linked(db,item_id):
 return [metadata(r) for r in db.execute('''SELECT d.*,u.display_name AS uploader_name FROM major_task_report_documents l
 JOIN major_task_documents d ON d.id=l.document_id JOIN users u ON u.id=d.created_by WHERE l.report_item_id=? ORDER BY l.created_at,d.id''',(item_id,))]

MIMES={'pdf':'application/pdf','doc':'application/msword','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','xls':'application/vnd.ms-excel','xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','ppt':'application/vnd.ms-powerpoint','pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png'}
def validate_file(upload):
 raw=upload.filename or '';name=Path(raw.replace('\\','/')).name
 if not name or name in ('.','..') or len(name)>200 or any(ord(c)<32 or ord(c)==127 for c in name):raise Fault('파일명을 확인하세요.')
 ext=Path(name).suffix.lower().lstrip('.')
 if ext not in MIMES:raise Fault('PDF / Office 문서 / JPG / PNG 파일만 올릴 수 있습니다.')
 content=upload.stream.read(FILE_LIMIT+1)
 if not content or len(content)>FILE_LIMIT:raise Fault('파일은 10MB 이내로 올려주세요.',413)
 mime=upload.mimetype or 'application/octet-stream'
 if mime not in (MIMES[ext],'application/octet-stream') and not (ext in ('docx','xlsx','pptx') and mime in ('application/zip','application/x-zip-compressed')):raise Fault('확장자와 파일 MIME 형식이 다릅니다.')
 valid=False
 if ext=='pdf':valid=content.startswith(b'%PDF-') and b'%%EOF' in content[-2048:]
 elif ext in ('jpg','jpeg'):valid=content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9')
 elif ext=='png':valid=content.startswith(b'\x89PNG\r\n\x1a\n') and b'IHDR' in content[:20] and content[-8:-4]==b'IEND'
 elif ext in ('doc','xls','ppt'):
  marker={'doc':'WordDocument','xls':'Workbook','ppt':'PowerPoint Document'}[ext]
  valid=content.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1') and marker.encode('utf-16le') in content
 elif ext in ('docx','xlsx','pptx'):
  try:
   with zipfile.ZipFile(io.BytesIO(content)) as z:
    names=z.namelist();part={'docx':'word/document.xml','xlsx':'xl/workbook.xml','pptx':'ppt/presentation.xml'}[ext]
    valid='[Content_Types].xml' in names and part in names and len(names)<=5000 and sum(i.file_size for i in z.infolist())<=100*1024*1024 and all(not i.flag_bits&1 and 'vbaproject' not in i.filename.lower() and not i.filename.startswith('/') and '..' not in Path(i.filename.replace('\\','/')).parts for i in z.infolist())
  except (zipfile.BadZipFile,ValueError):pass
 if not valid:raise Fault('파일의 실제 형식이 확장자와 맞지 않거나 지원하지 않는 문서입니다.')
 return name,content,MIMES[ext]

def register(app,get_db,role_required,csrf_required,audit_fn):
 def safe(fn):
  @functools.wraps(fn)
  def run(*args,**kwargs):
   try:return fn(*args,**kwargs)
   except (Fault,ValueError,TypeError) as e:get_db().rollback();return jsonify(error=str(e)),getattr(e,'status',400)
  return run
 def emit(action,task_id,before,after):mt._audit(audit_fn,'MAJOR_TASK_DOCUMENT_'+action,'major_task',task_id,'관련 문서 '+action,before,after)
 @app.get('/api/major-tasks/<task_id>/documents')
 @role_required(*mt.READ_ROLES)
 @safe
 def document_list(task_id):
  db=get_db()
  if not db.execute('SELECT 1 FROM major_tasks WHERE id=?',(task_id,)).fetchone():raise Fault('업무를 찾을 수 없습니다.',404)
  rows=db.execute('SELECT d.*,u.display_name AS uploader_name FROM major_task_documents d JOIN users u ON u.id=d.created_by WHERE d.task_id=? ORDER BY d.created_at DESC,d.id',(task_id,))
  return jsonify(items=[metadata(r) for r in rows],storage=usage(db),can_write=g.current_user['role'] in mt.WRITE_ROLES)
 @app.post('/api/major-tasks/<task_id>/documents')
 @role_required(*mt.WRITE_ROLES)
 @csrf_required
 @safe
 def document_upload(task_id):
  request.max_content_length=FILE_LIMIT+64*1024
  db=get_db();created=None
  try:
   file=request.files.get('file')
   if not file:raise Fault('파일을 선택하세요.')
   name,content,mime=validate_file(file);description=request.form.get('description','').strip()
   if len(description)>1000:raise Fault('설명은 1000자 이내로 입력하세요.')
   db.execute('BEGIN IMMEDIATE')
   if not db.execute('SELECT 1 FROM major_tasks WHERE id=?',(task_id,)).fetchone():raise Fault('업무를 찾을 수 없습니다.',404)
   replacing=request.form.get('replaces_document_id') or None;old=None
   if replacing:
    old=db.execute('SELECT * FROM major_task_documents WHERE id=? AND task_id=?',(replacing,task_id)).fetchone()
    if not old:raise Fault('기존 문서를 찾을 수 없습니다.',404)
    if old['version']!=mt._version(request.form) or not old['is_active']:raise Fault('문서가 변경되었습니다. 다시 불러오세요.',409)
    if db.execute('SELECT 1 FROM major_task_documents WHERE replaces_document_id=?',(replacing,)).fetchone():raise Fault('이미 새 버전이 있습니다.',409)
   use=usage(db);root=folder(db);root.mkdir(parents=True,exist_ok=True)
   if use['used_bytes']+len(content)>TOTAL_LIMIT or use['runtime_bytes']+len(content)>RUNTIME_LIMIT or shutil.disk_usage(root).free<len(content)+64*1024*1024:raise Fault('문서 저장공간 한도에 도달했습니다. 관리자에게 문의하세요.',413)
   now=mt._now();actor=g.current_user['id'];ident=uuid.uuid4().hex
   values=dict(id=ident,task_id=task_id,original_name=name,storage_name=uuid.uuid4().hex,sha256=hashlib.sha256(content).hexdigest(),size_bytes=len(content),mime_type=mime,description=description,replaces_document_id=replacing,revision=(old['revision']+1 if old else 1),created_by=actor,updated_by=actor,created_at=now,updated_at=now)
   created=root/values['storage_name']
   with created.open('xb') as f:f.write(content)
   db.execute('INSERT INTO major_task_documents ('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values()))
   if old:db.execute('UPDATE major_task_documents SET is_active=0,version=version+1,updated_by=?,updated_at=? WHERE id=?',(actor,now,replacing))
   new=dict(db.execute('SELECT * FROM major_task_documents WHERE id=?',(ident,)).fetchone());emit('VERSION_CREATE' if old else 'UPLOAD',task_id,metadata(old) if old else None,metadata(new));db.commit();return jsonify(item=metadata(new)),201
  except Exception:
   db.rollback()
   if created:created.unlink(missing_ok=True)
   raise
 @app.delete('/api/major-task-documents/<document_id>')
 @role_required(*mt.WRITE_ROLES)
 @csrf_required
 @safe
 def document_remove(document_id):
  data=request.get_json(silent=True) or {};expected=mt._version(data);db=get_db();db.execute('BEGIN IMMEDIATE')
  row=db.execute('SELECT * FROM major_task_documents WHERE id=?',(document_id,)).fetchone()
  if not row:raise Fault('문서를 찾을 수 없습니다.',404)
  if row['version']!=expected:raise Fault('다른 사용자가 먼저 수정했습니다.',409)
  db.execute('UPDATE major_task_documents SET is_active=0,version=version+1,updated_by=?,updated_at=? WHERE id=?',(g.current_user['id'],mt._now(),document_id));emit('SOFT_DELETE',row['task_id'],metadata(row),dict(id=document_id,is_active=0));db.commit();return jsonify(message='문서를 사용중지했습니다. 과거 완료 보고서의 파일은 보존됩니다.')
 @app.get('/api/major-task-documents/<document_id>/download')
 @role_required(*mt.READ_ROLES)
 @safe
 def document_download(document_id):
  db=get_db();row=db.execute('SELECT * FROM major_task_documents WHERE id=?',(document_id,)).fetchone()
  retained=row and db.execute("SELECT 1 FROM major_task_report_documents l JOIN major_task_report_items i ON i.id=l.report_item_id JOIN major_task_reports r ON r.id=i.report_id WHERE l.document_id=? AND r.status='final'",(document_id,)).fetchone()
  if not row or not (row['is_active'] or retained):raise Fault('문서를 찾을 수 없습니다.',404)
  if not re.fullmatch('[0-9a-f]{32}',row['storage_name']):raise Fault('파일 저장정보 오류',500)
  root=folder(db).resolve();path=root/row['storage_name']
  if path.is_symlink() or not path.is_file() or path.resolve().parent!=root:raise Fault('파일을 찾을 수 없습니다.',404)
  response=send_file(path,as_attachment=True,download_name=row['original_name'],mimetype='application/octet-stream',max_age=0)
  response.headers['X-Content-Type-Options']='nosniff';response.headers['Cache-Control']='private, no-store';return response
