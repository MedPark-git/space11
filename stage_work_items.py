"""Stage execution ledger. Legacy Milestone Actions remain unchanged."""
import hashlib
import json
import sqlite3
import uuid
from datetime import date, timedelta

from flask import g, jsonify, request

VERSION = "major-tasks-2026-09-18-stage-work-items-v1"
BALLS = {"internal": "메드파크 해외영업", "department": "메드파크 타부서", "buyer": "상대측"}
DDL = (
    """CREATE TABLE IF NOT EXISTS major_task_stage_work_items (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL REFERENCES major_tasks(id) ON DELETE RESTRICT,
      stage_id TEXT NOT NULL REFERENCES major_task_stages(id) ON DELETE RESTRICT,
      content TEXT NOT NULL CHECK(length(trim(content)) BETWEEN 1 AND 1000),
      ball_type TEXT NOT NULL CHECK(ball_type IN ('internal','department','buyer')),
      assignee_user_id INTEGER REFERENCES users(id),
      contact_id TEXT REFERENCES customer_contacts(id),
      counterparty_name TEXT,
      target_due_date TEXT,
      completed_at TEXT,
      status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','completed','cancelled')),
      sort_order INTEGER NOT NULL DEFAULT 0,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER NOT NULL REFERENCES users(id),
      updated_by INTEGER NOT NULL REFERENCES users(id),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      CHECK((status='completed' AND completed_at IS NOT NULL) OR
            (status<>'completed' AND completed_at IS NULL)),
      CHECK((ball_type='buyer' AND assignee_user_id IS NULL) OR
            (ball_type<>'buyer' AND contact_id IS NULL AND counterparty_name IS NULL))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_stage_work_due ON major_task_stage_work_items(status,target_due_date,task_id)",
    "CREATE INDEX IF NOT EXISTS idx_stage_work_stage ON major_task_stage_work_items(stage_id,status,sort_order)",
    """CREATE TRIGGER IF NOT EXISTS stage_work_parent_insert BEFORE INSERT ON major_task_stage_work_items
       WHEN NOT EXISTS(SELECT 1 FROM major_task_stages s WHERE s.id=NEW.stage_id AND s.task_id=NEW.task_id AND s.is_active=1)
       BEGIN SELECT RAISE(ABORT,'Work Item Stage/Task mismatch'); END""",
    """CREATE TRIGGER IF NOT EXISTS stage_work_identity_update BEFORE UPDATE OF id,task_id,stage_id ON major_task_stage_work_items
       WHEN NEW.id<>OLD.id OR NEW.task_id<>OLD.task_id OR NEW.stage_id<>OLD.stage_id
       BEGIN SELECT RAISE(ABORT,'Work Item identity is immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS stage_work_stage_deactivate BEFORE UPDATE OF is_active,status ON major_task_stages
       WHEN (NEW.is_active=0 OR NEW.status='inactive') AND EXISTS(SELECT 1 FROM major_task_stage_work_items w WHERE w.stage_id=OLD.id)
       BEGIN SELECT RAISE(ABORT,'Stage has execution history'); END""",
    """CREATE TRIGGER IF NOT EXISTS stage_work_stage_delete BEFORE DELETE ON major_task_stages
       WHEN EXISTS(SELECT 1 FROM major_task_stage_work_items w WHERE w.stage_id=OLD.id)
       BEGIN SELECT RAISE(ABORT,'Stage has execution history'); END""",
)


def init_schema(db, now_fn):
    checksum = hashlib.sha256("\n".join(DDL).encode()).hexdigest()
    row = db.execute("SELECT checksum FROM major_task_schema_migrations WHERE version=?", (VERSION,)).fetchone()
    if row:
        if row[0] != checksum:
            raise RuntimeError("Stage Work Item migration checksum mismatch")
        return False
    db.execute("SAVEPOINT stage_work_schema")
    try:
        for statement in DDL:
            db.execute(statement)
        db.execute("INSERT INTO major_task_schema_migrations(version,checksum,applied_at) VALUES(?,?,?)", (VERSION, checksum, now_fn()))
        db.execute("RELEASE SAVEPOINT stage_work_schema")
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT stage_work_schema")
        db.execute("RELEASE SAVEPOINT stage_work_schema")
        raise
    return True


def stage_has_work(db, stage_id):
    return bool(db.execute("SELECT 1 FROM major_task_stage_work_items WHERE stage_id=? LIMIT 1", (stage_id,)).fetchone())


def due_projection(item, today):
    item = dict(item)
    due = item.get("target_due_date")
    delta = (date.fromisoformat(due) - today).days if due else None
    item["days_delta"] = delta
    item["due_status"] = ("none" if delta is None or item["status"] != "open" else
                          "overdue" if delta < 0 else "today" if delta == 0 else "soon" if delta <= 3 else "normal")
    item["ball_label"] = BALLS[item["ball_type"]]
    return item


SELECT = """SELECT w.*,s.name AS stage_name,t.title AS task_name,t.current_stage_id,
 t.final_rag AS rag,t.customer_master_id,t.country,
 COALESCE(u.display_name,c.contact_name,w.counterparty_name,'') AS assignee_name,
 cm.display_name AS customer_name
 FROM major_task_stage_work_items w
 JOIN major_tasks t ON t.id=w.task_id
 JOIN major_task_stages s ON s.id=w.stage_id AND s.task_id=w.task_id
 LEFT JOIN users u ON u.id=w.assignee_user_id
 LEFT JOIN customer_contacts c ON c.id=w.contact_id
 LEFT JOIN customer_master cm ON cm.id=t.customer_master_id
 """


def detail_items(db, task_id, today):
    return [due_projection(row, today) for row in db.execute(
        SELECT + " WHERE w.task_id=? ORDER BY w.sort_order,w.created_at,w.id", (task_id,))]


def contacts(db, task):
    return [dict(row) for row in db.execute(
        "SELECT id,contact_name,department_title FROM customer_contacts WHERE customer_id=? AND deleted_at IS NULL AND employment_status='active' ORDER BY is_primary_contact DESC,contact_name",
        (task["customer_master_id"],))] if task["customer_master_id"] else []


def add_list_summaries(db, items, today):
    flat = []
    def walk(branch):
        for item in branch:
            flat.append(item)
            walk(item.get("children", []))
    walk(items)
    if not flat:
        return
    by_id = {item["id"]: item for item in flat}
    # One batch query for the entire page/tree, never one request per Task.
    marks = ",".join("?" for _ in by_id)
    groups = {key: [] for key in by_id}
    for row in db.execute(SELECT + f" WHERE w.status='open' AND w.task_id IN ({marks}) ORDER BY w.target_due_date IS NULL,w.target_due_date,w.sort_order,w.created_at,w.id", tuple(by_id)):
        value = due_projection(row, today)
        if row["stage_id"] == row["current_stage_id"]:
            groups[row["task_id"]].append(value)
    for item in flat:
        work = groups[item["id"]]
        item["stage_work_summary"] = {"total": len(work), "items": work[:3]}


def register(app, get_db, role_required, csrf_required, audit_fn):
    import major_tasks as mt

    def stage_context(db, stage_id):
        stage = db.execute("SELECT * FROM major_task_stages WHERE id=?", (stage_id,)).fetchone()
        task = mt._task_row(db, stage["task_id"]) if stage else None
        return stage, task

    def writable(stage, task):
        return bool(stage and task and stage["is_active"] and stage["status"] != "inactive"
                    and task["status"] not in {"completed", "cancelled"} and not task["archived_at"])

    def validate(db, task, data, old=None):
        old = dict(old or {})
        content = data.get("content", old.get("content", ""))
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 1000:
            raise ValueError("업무내용은 1~1000자로 입력하세요.")
        ball = data.get("ball_type", old.get("ball_type", "internal"))
        if ball not in BALLS:
            raise ValueError("Ball 값을 확인하세요.")
        # Changing Ball clears the old side's identity unless explicitly supplied.
        same = old.get("ball_type", ball) == ball
        user_id = data.get("assignee_user_id", old.get("assignee_user_id") if same else None)
        contact_id = data.get("contact_id", old.get("contact_id") if same else None) or None
        name = data.get("counterparty_name", old.get("counterparty_name") if same else None)
        if name is not None and (not isinstance(name, str) or len(name.strip()) > 200):
            raise ValueError("상대측 담당자명은 200자 이내로 입력하세요.")
        name = name.strip() or None if name else None
        if ball == "buyer":
            user_id = None
            if contact_id:
                if not db.execute("SELECT 1 FROM customer_contacts WHERE id=? AND customer_id=? AND deleted_at IS NULL AND employment_status='active'", (contact_id, task["customer_master_id"])).fetchone():
                    if contact_id != old.get("contact_id"):
                        raise ValueError("연결 거래처의 활성 담당자를 선택하세요.")
                name = None
            elif name and contacts(db, task) and name != old.get("counterparty_name"):
                raise ValueError("등록된 거래처 담당자를 먼저 선택하세요.")
        else:
            contact_id = name = None
            if user_id not in (None, ""):
                if isinstance(user_id, bool) or not str(user_id).isdigit():
                    raise ValueError("내부 담당자를 확인하세요.")
                user_id = int(user_id)
                if user_id != old.get("assignee_user_id"):
                    mt._normalized_user_ids(db, [user_id], "세부업무 담당자")
            else:
                user_id = None
        order = data.get("sort_order", old.get("sort_order", 0))
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 1000000:
            raise ValueError("정렬순서는 0 이상의 정수여야 합니다.")
        return dict(content=content.strip(), ball_type=ball, assignee_user_id=user_id,
                    contact_id=contact_id, counterparty_name=name,
                    target_due_date=mt._date(data.get("target_due_date", old.get("target_due_date")), "목표기한"),
                    sort_order=order)

    def emit(event, task_id, before, after):
        mt._audit(audit_fn, "MAJOR_TASK_WORK_ITEM_" + event, "major_task", task_id,
                  after["content"] + " · " + event, before, after)

    @app.get("/api/major-task-stages/<stage_id>/work-items")
    @role_required(*mt.READ_ROLES)
    def work_list(stage_id):
        db = get_db(); stage, task = stage_context(db, stage_id)
        if not stage:
            return jsonify(error="Stage를 찾을 수 없습니다."), 404
        return jsonify(items=[i for i in detail_items(db, task["id"], mt._today()) if i["stage_id"] == stage_id],
                       contacts=contacts(db, task), ball_types=BALLS)

    @app.post("/api/major-task-stages/<stage_id>/work-items")
    @role_required(*mt.WRITE_ROLES)
    @csrf_required
    def work_create(stage_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(error="입력 형식을 확인하세요."), 400
        db.execute("BEGIN IMMEDIATE")
        stage, task = stage_context(db, stage_id)
        if not stage:
            db.rollback(); return jsonify(error="Stage를 찾을 수 없습니다."), 404
        if not writable(stage, task):
            db.rollback(); return jsonify(error="활성 업무·Stage에서 등록하세요."), 409
        try:
            values = validate(db, task, data)
        except (ValueError, TypeError) as exc:
            db.rollback(); return jsonify(error=str(exc)), 400
        now = mt._now(); work_id = uuid.uuid4().hex
        values.update(id=work_id, task_id=task["id"], stage_id=stage_id, status="open", completed_at=None,
                      version=1, created_by=g.current_user["id"], updated_by=g.current_user["id"], created_at=now, updated_at=now)
        columns = list(values)
        db.execute(f"INSERT INTO major_task_stage_work_items ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", tuple(values.values()))
        emit("CREATE", task["id"], None, values)
        db.commit()
        return jsonify(item=values, message="세부업무가 등록되었습니다."), 201

    @app.patch("/api/major-task-work-items/<work_id>")
    @app.post("/api/major-task-work-items/<work_id>/<operation>")
    @role_required(*mt.WRITE_ROLES)
    @csrf_required
    def work_update(work_id, operation=None):
        db = get_db(); data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(error="입력 형식을 확인하세요."), 400
        if operation not in (None, "complete", "reopen", "cancel"):
            return jsonify(error="지원하지 않는 변경입니다."), 404
        try:
            expected = mt._version(data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM major_task_stage_work_items WHERE id=?", (work_id,)).fetchone()
        if not old:
            db.rollback(); return jsonify(error="세부업무를 찾을 수 없습니다."), 404
        old = dict(old)
        if old["version"] != expected:
            db.rollback(); return jsonify(error="다른 사용자가 먼저 수정했습니다. 새로고침 후 확인하세요.", code="VERSION_CONFLICT"), 409
        stage, task = stage_context(db, old["stage_id"])
        if not writable(stage, task):
            db.rollback(); return jsonify(error="활성 업무·Stage에서 수정하세요."), 409
        if old["status"] == "cancelled" or (operation == "reopen" and old["status"] != "completed") or (operation in (None, "complete", "cancel") and old["status"] != "open"):
            db.rollback(); return jsonify(error="현재 세부업무 상태에서 할 수 없는 변경입니다."), 409
        try:
            if any(k in data and data[k] != old[k] for k in ("id", "task_id", "stage_id")):
                raise ValueError("세부업무의 Task/Stage/ID는 변경할 수 없습니다.")
            values = validate(db, task, data, old) if operation is None else {}
        except (ValueError, TypeError) as exc:
            db.rollback(); return jsonify(error=str(exc)), 400
        now = mt._now()
        if operation:
            values.update(status={"complete": "completed", "reopen": "open", "cancel": "cancelled"}[operation],
                          completed_at=now if operation == "complete" else None)
        values.update(updated_by=g.current_user["id"], updated_at=now, version=expected+1)
        cursor = db.execute(f"UPDATE major_task_stage_work_items SET {','.join(k+'=?' for k in values)} WHERE id=? AND version=?", (*values.values(), work_id, expected))
        if cursor.rowcount != 1:
            db.rollback(); return jsonify(error="동시 수정 충돌", code="VERSION_CONFLICT"), 409
        after = {**old, **values}
        emit(operation.upper() if operation else "UPDATE", task["id"], old, after)
        if not operation:
            for event, keys in (("BALL_CHANGE", ["ball_type"]), ("ASSIGNEE_CHANGE", ["assignee_user_id", "contact_id", "counterparty_name"]), ("DUE_CHANGE", ["target_due_date"])):
                if any(old[k] != after[k] for k in keys):
                    emit(event, task["id"], old, after)
        db.commit()
        return jsonify(item=after, message="세부업무가 변경되었습니다.")

    @app.get("/api/major-tasks/work-items/due")
    @role_required(*mt.READ_ROLES)
    def work_due():
        db = get_db(); today = mt._today()
        args = request.args.to_dict()
        # Task list paging/collapse never hides matching Child/Grandchild work.
        for key in ("hierarchy", "parent", "archive", "page", "per_page"):
            args.pop(key, None)
        if args.pop("scope", "") == "all":
            args = {}
        where, params = mt._list_where(args, g.current_user["id"])
        rows = db.execute(SELECT + " WHERE " + where + " AND s.is_active=1 AND w.status='open' AND w.target_due_date IS NOT NULL AND w.target_due_date<=? ORDER BY w.target_due_date,w.sort_order,w.created_at,w.id", (*params, (today+timedelta(days=3)).isoformat())).fetchall()
        # One dictionary query for all paths/sections, avoiding per-item queries.
        tasks = {r["id"]: dict(r) for r in db.execute("SELECT id,title,parent_task_id,section_id FROM major_tasks")}
        sections = {r["id"]: r["name"] for r in db.execute("SELECT id,name FROM major_task_sections")}
        groups = {"overdue": [], "upcoming": []}
        for row in rows:
            value = due_projection(row, today); path = []; cursor = tasks.get(row["task_id"]); seen = set(); section_id = None
            while cursor and cursor["id"] not in seen:
                seen.add(cursor["id"]); path.append(cursor["title"]); section_id = cursor["section_id"]; cursor = tasks.get(cursor["parent_task_id"])
            value.update(task_path=" > ".join(reversed(path)), section_id=section_id, section=sections.get(section_id, "미분류"))
            groups["overdue" if value["due_status"] == "overdue" else "upcoming"].append(value)
        return jsonify(today=today.isoformat(), timezone="Asia/Seoul", due_soon_days=3,
                       counts={key: len(items) for key, items in groups.items()}, **groups)
