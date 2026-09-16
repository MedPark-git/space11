"""Versioned, additive migration for the relational major-task ledger.

The production database is intentionally not touched by this module on import.
`apply_major_tasks_schema()` and `apply_major_tasks_legacy_migration()` are
invoked by the application's existing SQLite initialization transaction.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict


MAJOR_TASKS_SCHEMA_VERSION = "major-tasks-2026-09-15-compact-custom-section-v1"
MAJOR_TASKS_LEGACY_MIGRATION_VERSION = "major-tasks-legacy-2026-09-07-v1"
MAJOR_TASKS_SCHEMA_CHECKSUM = ""


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _payload(value):
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _uuid(label):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"medpark-global-maps:{label}").hex


SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS major_task_schema_migrations (
      version TEXT PRIMARY KEY,
      checksum TEXT NOT NULL,
      applied_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_workstreams (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL UNIQUE COLLATE NOCASE,
      description TEXT NOT NULL DEFAULT '',
      color TEXT NOT NULL DEFAULT '#0a7d6b',
      display_order INTEGER NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 1,
      review_cycle_days INTEGER,
      due_soon_days INTEGER NOT NULL DEFAULT 3,
      hard_deadline_soon_days INTEGER NOT NULL DEFAULT 7,
      template_version INTEGER NOT NULL DEFAULT 1,
      copied_from_id TEXT,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(created_by) REFERENCES users(id),
      FOREIGN KEY(updated_by) REFERENCES users(id),
      FOREIGN KEY(copied_from_id) REFERENCES major_task_workstreams(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_sections (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL COLLATE NOCASE,
      sort_order INTEGER NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(created_by) REFERENCES users(id),
      FOREIGN KEY(updated_by) REFERENCES users(id)
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_major_task_sections_name
       ON major_task_sections(name COLLATE NOCASE)""",
    """CREATE TABLE IF NOT EXISTS major_task_workstream_business (
      workstream_id TEXT NOT NULL,
      business_unit TEXT NOT NULL,
      business_subcategory TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(workstream_id, business_unit, business_subcategory),
      FOREIGN KEY(workstream_id) REFERENCES major_task_workstreams(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_workstream_templates (
      id TEXT PRIMARY KEY,
      workstream_id TEXT NOT NULL,
      parent_id TEXT,
      item_type TEXT NOT NULL CHECK(item_type IN ('milestone','area','action','checklist')),
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      is_required INTEGER NOT NULL DEFAULT 1,
      include_in_progress INTEGER NOT NULL DEFAULT 1,
      display_order INTEGER NOT NULL DEFAULT 0,
      template_version INTEGER NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(workstream_id) REFERENCES major_task_workstreams(id) ON DELETE CASCADE,
      FOREIGN KEY(parent_id) REFERENCES major_task_workstream_templates(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_tasks (
      id TEXT PRIMARY KEY,
      legacy_record_id TEXT UNIQUE,
      title TEXT NOT NULL,
      primary_business_unit TEXT NOT NULL,
      primary_business_subcategory TEXT NOT NULL DEFAULT '',
      workstream_id TEXT,
      section_id TEXT,
      region TEXT NOT NULL DEFAULT '',
      country TEXT NOT NULL DEFAULT '',
      customer_master_id TEXT,
      legacy_customer_name TEXT NOT NULL DEFAULT '',
      customer_link_status TEXT NOT NULL DEFAULT 'unlinked',
      product_name TEXT NOT NULL DEFAULT '',
      product_code TEXT NOT NULL DEFAULT '',
      purpose TEXT NOT NULL DEFAULT '',
      completion_criteria TEXT NOT NULL DEFAULT '',
      owner_id INTEGER,
      deputy_owner_id INTEGER,
      importance TEXT NOT NULL DEFAULT 'medium' CHECK(importance IN ('high','medium','low')),
      start_date TEXT,
      original_target_date TEXT,
      current_target_date TEXT,
      target_change_reason TEXT NOT NULL DEFAULT '',
      hard_deadline_enabled INTEGER NOT NULL DEFAULT 0,
      hard_deadline_date TEXT,
      review_cycle_days_override INTEGER,
      due_soon_days_override INTEGER,
      hard_deadline_soon_days_override INTEGER,
      status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','internal_work','external_wait','cooperation_wait','hold','completed','cancelled')),
      auto_rag TEXT NOT NULL DEFAULT 'green' CHECK(auto_rag IN ('green','amber','red')),
      manual_rag TEXT CHECK(manual_rag IN ('green','amber','red')),
      final_rag TEXT NOT NULL DEFAULT 'green' CHECK(final_rag IN ('green','amber','red')),
      manual_rag_reason TEXT NOT NULL DEFAULT '',
      next_action TEXT NOT NULL DEFAULT '',
      next_action_date TEXT,
      next_check_date TEXT,
      cooperation_department TEXT NOT NULL DEFAULT '',
      cooperation_request TEXT NOT NULL DEFAULT '',
      hold_reason TEXT NOT NULL DEFAULT '',
      review_date TEXT,
      final_result TEXT NOT NULL DEFAULT '',
      final_deliverable TEXT NOT NULL DEFAULT '',
      actual_completion_date TEXT,
      major_risks TEXT NOT NULL DEFAULT '',
      resolution TEXT NOT NULL DEFAULT '',
      future_notes TEXT NOT NULL DEFAULT '',
      final_report TEXT NOT NULL DEFAULT '',
      completion_exception_reason TEXT NOT NULL DEFAULT '',
      cancel_reason TEXT NOT NULL DEFAULT '',
      ceo_directive INTEGER NOT NULL DEFAULT 0,
      directive_date TEXT,
      legacy_description TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      legacy_amount REAL NOT NULL DEFAULT 0,
      legacy_currency TEXT NOT NULL DEFAULT 'USD',
      legacy_priority TEXT NOT NULL DEFAULT '',
      legacy_status TEXT NOT NULL DEFAULT '',
      legacy_task_kind TEXT NOT NULL DEFAULT '',
      legacy_parent_task_id TEXT,
      legacy_task_order INTEGER,
      legacy_payload_json TEXT NOT NULL DEFAULT '{}',
      migration_review_required INTEGER NOT NULL DEFAULT 0,
      recent_updated_at TEXT NOT NULL,
      archived_at TEXT,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(workstream_id) REFERENCES major_task_workstreams(id),
      FOREIGN KEY(section_id) REFERENCES major_task_sections(id),
      FOREIGN KEY(customer_master_id) REFERENCES customer_master(id),
      FOREIGN KEY(owner_id) REFERENCES users(id),
      FOREIGN KEY(deputy_owner_id) REFERENCES users(id),
      FOREIGN KEY(created_by) REFERENCES users(id),
      FOREIGN KEY(updated_by) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_business_links (
      task_id TEXT NOT NULL,
      business_unit TEXT NOT NULL,
      business_subcategory TEXT NOT NULL DEFAULT '',
      is_primary INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      PRIMARY KEY(task_id, business_unit, business_subcategory),
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_people (
      task_id TEXT NOT NULL,
      user_id INTEGER NOT NULL,
      relation_type TEXT NOT NULL CHECK(relation_type IN ('participant','cooperator')),
      created_at TEXT NOT NULL,
      PRIMARY KEY(task_id, user_id, relation_type),
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_assignees (
      task_id TEXT NOT NULL,
      user_id INTEGER NOT NULL,
      relation_type TEXT NOT NULL DEFAULT 'additional_owner'
        CHECK(relation_type='additional_owner'),
      created_by INTEGER,
      created_at TEXT NOT NULL,
      PRIMARY KEY(task_id, user_id, relation_type),
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(created_by) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_products (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      product_code TEXT NOT NULL DEFAULT '',
      product_name TEXT NOT NULL,
      source_type TEXT NOT NULL DEFAULT 'manual' CHECK(source_type IN ('manual','shipment','customer_term')),
      created_at TEXT NOT NULL,
      UNIQUE(task_id, product_code, product_name),
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_target_history (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      previous_target_date TEXT,
      new_target_date TEXT,
      change_reason TEXT NOT NULL,
      changed_by INTEGER,
      changed_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(changed_by) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_milestones (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      planned_start_date TEXT,
      planned_end_date TEXT,
      actual_completion_date TEXT,
      owner_id INTEGER,
      deputy_owner_id INTEGER,
      status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','waiting','completed','cancelled')),
      is_required INTEGER NOT NULL DEFAULT 1,
      result TEXT NOT NULL DEFAULT '',
      attachment_note TEXT NOT NULL DEFAULT '',
      completion_override_reason TEXT NOT NULL DEFAULT '',
      display_order INTEGER NOT NULL DEFAULT 0,
      started_with_override_reason TEXT NOT NULL DEFAULT '',
      is_active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(owner_id) REFERENCES users(id),
      FOREIGN KEY(deputy_owner_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_milestone_dependencies (
      milestone_id TEXT NOT NULL,
      predecessor_id TEXT NOT NULL,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      PRIMARY KEY(milestone_id, predecessor_id),
      FOREIGN KEY(milestone_id) REFERENCES major_task_milestones(id) ON DELETE CASCADE,
      FOREIGN KEY(predecessor_id) REFERENCES major_task_milestones(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_action_areas (
      id TEXT PRIMARY KEY,
      milestone_id TEXT NOT NULL,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      display_order INTEGER NOT NULL DEFAULT 0,
      is_active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(milestone_id) REFERENCES major_task_milestones(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_actions (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      milestone_id TEXT NOT NULL,
      area_id TEXT,
      legacy_record_id TEXT UNIQUE,
      name TEXT NOT NULL,
      owner_id INTEGER,
      deputy_owner_id INTEGER,
      start_date TEXT,
      due_date TEXT,
      actual_completion_date TEXT,
      status TEXT NOT NULL DEFAULT 'not_started' CHECK(status IN ('not_started','in_progress','waiting','completed','cancelled')),
      importance TEXT NOT NULL DEFAULT 'medium' CHECK(importance IN ('high','medium','low')),
      is_required INTEGER NOT NULL DEFAULT 1,
      include_in_progress INTEGER NOT NULL DEFAULT 1,
      include_in_rag INTEGER NOT NULL DEFAULT 1,
      result TEXT NOT NULL DEFAULT '',
      next_action TEXT NOT NULL DEFAULT '',
      attachment_note TEXT NOT NULL DEFAULT '',
      completion_override_reason TEXT NOT NULL DEFAULT '',
      display_order INTEGER NOT NULL DEFAULT 0,
      started_with_override_reason TEXT NOT NULL DEFAULT '',
      legacy_description TEXT NOT NULL DEFAULT '',
      legacy_amount REAL NOT NULL DEFAULT 0,
      legacy_currency TEXT NOT NULL DEFAULT 'USD',
      legacy_payload_json TEXT NOT NULL DEFAULT '{}',
      is_active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(milestone_id) REFERENCES major_task_milestones(id) ON DELETE CASCADE,
      FOREIGN KEY(area_id) REFERENCES major_task_action_areas(id),
      FOREIGN KEY(owner_id) REFERENCES users(id),
      FOREIGN KEY(deputy_owner_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_action_dependencies (
      action_id TEXT NOT NULL,
      predecessor_id TEXT NOT NULL,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      PRIMARY KEY(action_id, predecessor_id),
      FOREIGN KEY(action_id) REFERENCES major_task_actions(id) ON DELETE CASCADE,
      FOREIGN KEY(predecessor_id) REFERENCES major_task_actions(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_action_people (
      action_id TEXT NOT NULL,
      user_id INTEGER NOT NULL,
      relation_type TEXT NOT NULL DEFAULT 'cooperator' CHECK(relation_type='cooperator'),
      created_at TEXT NOT NULL,
      PRIMARY KEY(action_id, user_id, relation_type),
      FOREIGN KEY(action_id) REFERENCES major_task_actions(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_checklists (
      id TEXT PRIMARY KEY,
      action_id TEXT NOT NULL,
      item_text TEXT NOT NULL,
      is_completed INTEGER NOT NULL DEFAULT 0,
      is_required INTEGER NOT NULL DEFAULT 1,
      completed_by INTEGER,
      completed_at TEXT,
      display_order INTEGER NOT NULL DEFAULT 0,
      completion_override_reason TEXT NOT NULL DEFAULT '',
      is_active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(action_id) REFERENCES major_task_actions(id) ON DELETE CASCADE,
      FOREIGN KEY(completed_by) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_stages (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      name TEXT NOT NULL,
      display_order INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'planned'
        CHECK(status IN ('planned','active','completed','inactive')),
      owner_id INTEGER,
      target_date TEXT,
      started_at TEXT,
      completed_at TEXT,
      note TEXT NOT NULL DEFAULT '',
      is_active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(owner_id) REFERENCES users(id),
      FOREIGN KEY(created_by) REFERENCES users(id),
      FOREIGN KEY(updated_by) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_stage_people (
      stage_id TEXT NOT NULL,
      user_id INTEGER NOT NULL,
      relation_type TEXT NOT NULL DEFAULT 'assignee'
        CHECK(relation_type='assignee'),
      created_by INTEGER,
      created_at TEXT NOT NULL,
      PRIMARY KEY(stage_id, user_id, relation_type),
      FOREIGN KEY(stage_id) REFERENCES major_task_stages(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(created_by) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_balls (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      milestone_id TEXT,
      action_id TEXT,
      owner_type TEXT NOT NULL CHECK(owner_type IN ('internal','executive','department','buyer','external_agency','logistics','none')),
      owner_detail TEXT NOT NULL DEFAULT '',
      request_text TEXT NOT NULL DEFAULT '',
      wait_started_at TEXT,
      last_requested_at TEXT,
      last_contacted_at TEXT,
      expected_reply_date TEXT,
      follow_up_date TEXT,
      follow_up_owner_id INTEGER,
      cooperation_needed TEXT NOT NULL DEFAULT '',
      resolution_due_date TEXT,
      resolved_at TEXT,
      is_active INTEGER NOT NULL DEFAULT 1,
      represents_whole_milestone INTEGER NOT NULL DEFAULT 0,
      hard_deadline_impact TEXT NOT NULL DEFAULT 'none' CHECK(hard_deadline_impact IN ('none','amber','red')),
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      updated_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(milestone_id) REFERENCES major_task_milestones(id),
      FOREIGN KEY(action_id) REFERENCES major_task_actions(id),
      FOREIGN KEY(follow_up_owner_id) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_ball_history (
      id TEXT PRIMARY KEY,
      ball_id TEXT NOT NULL,
      change_type TEXT NOT NULL,
      before_json TEXT,
      after_json TEXT,
      reason TEXT NOT NULL DEFAULT '',
      changed_by INTEGER,
      changed_at TEXT NOT NULL,
      FOREIGN KEY(ball_id) REFERENCES major_task_balls(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_progress_updates (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      milestone_id TEXT,
      action_id TEXT,
      update_date TEXT NOT NULL,
      progress_text TEXT NOT NULL,
      result_text TEXT NOT NULL DEFAULT '',
      risk_text TEXT NOT NULL DEFAULT '',
      next_action TEXT NOT NULL DEFAULT '',
      next_action_date TEXT,
      decision_needed TEXT NOT NULL DEFAULT '',
      cooperation_needed TEXT NOT NULL DEFAULT '',
      attachment_note TEXT NOT NULL DEFAULT '',
      applied_stage_id TEXT,
      applied_ball_id TEXT,
      applied_rag TEXT,
      state_change_json TEXT NOT NULL DEFAULT '{}',
      original_update_id TEXT,
      revision_reason TEXT NOT NULL DEFAULT '',
      is_current INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(milestone_id) REFERENCES major_task_milestones(id),
      FOREIGN KEY(action_id) REFERENCES major_task_actions(id),
      FOREIGN KEY(original_update_id) REFERENCES major_task_progress_updates(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_attachments (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      milestone_id TEXT,
      action_id TEXT,
      progress_update_id TEXT,
      label TEXT NOT NULL,
      external_url TEXT NOT NULL,
      notes TEXT NOT NULL DEFAULT '',
      is_active INTEGER NOT NULL DEFAULT 1,
      version INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE,
      FOREIGN KEY(milestone_id) REFERENCES major_task_milestones(id),
      FOREIGN KEY(action_id) REFERENCES major_task_actions(id),
      FOREIGN KEY(progress_update_id) REFERENCES major_task_progress_updates(id)
    )""",
    """CREATE TABLE IF NOT EXISTS major_task_external_links (
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      link_type TEXT NOT NULL CHECK(link_type IN ('promotion','customer','order','monthly_sales','shipment','external')),
      external_id TEXT NOT NULL,
      linked_at TEXT NOT NULL,
      linked_by INTEGER,
      status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','unlinked')),
      unlinked_at TEXT,
      unlinked_by INTEGER,
      notes TEXT NOT NULL DEFAULT '',
      version INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id) ON DELETE CASCADE
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_major_task_external_active
      ON major_task_external_links(task_id, link_type, external_id) WHERE status='active'""",
    """CREATE TABLE IF NOT EXISTS major_task_legacy_mappings (
      legacy_record_id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      milestone_id TEXT,
      action_id TEXT,
      migration_status TEXT NOT NULL,
      legacy_task_kind TEXT NOT NULL DEFAULT '',
      legacy_parent_task_id TEXT,
      legacy_task_order INTEGER,
      legacy_payload_json TEXT NOT NULL DEFAULT '{}',
      migrated_at TEXT NOT NULL,
      FOREIGN KEY(task_id) REFERENCES major_tasks(id)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_major_tasks_filters
      ON major_tasks(status, primary_business_unit, final_rag, current_target_date)""",
    """CREATE INDEX IF NOT EXISTS idx_major_tasks_owner ON major_tasks(owner_id, deputy_owner_id, status)""",
    """CREATE INDEX IF NOT EXISTS idx_major_tasks_customer ON major_tasks(customer_master_id, status)""",
    """CREATE INDEX IF NOT EXISTS idx_major_milestones_task ON major_task_milestones(task_id, is_active, display_order)""",
    """CREATE INDEX IF NOT EXISTS idx_major_actions_task ON major_task_actions(task_id, is_active, status, due_date)""",
    """CREATE INDEX IF NOT EXISTS idx_major_balls_active ON major_task_balls(task_id, is_active, resolved_at, follow_up_date)""",
    """CREATE INDEX IF NOT EXISTS idx_major_progress_task ON major_task_progress_updates(task_id, is_current, update_date DESC, created_at DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_major_checklists_action ON major_task_checklists(action_id, is_active, display_order)""",
    """CREATE INDEX IF NOT EXISTS idx_major_stages_task ON major_task_stages(task_id, is_active, display_order)""",
    """CREATE INDEX IF NOT EXISTS idx_major_task_sections_order ON major_task_sections(is_active, sort_order, name)""",
)


DEFAULT_WORKSTREAMS = (
    "신규시장·딜러개발", "계약·가격·바이어 온보딩", "인허가·규제", "ODM·제품개발",
    "프로모션·전시회·마케팅", "매출·수금·채권", "출고·물류·통관", "내부업무", "기타",
    "신규사업개발", "기존사업 확대", "인허가·등록", "계약·상업조건",
    "마케팅·교육·전시", "내부·전략",
)


MAJOR_TASKS_SCHEMA_CHECKSUM = hashlib.sha256(
    ("\n".join(SCHEMA_STATEMENTS) + "\n" + "\n".join(DEFAULT_WORKSTREAMS)).encode("utf-8")
).hexdigest()
MAJOR_TASKS_LEGACY_MIGRATION_CHECKSUM = hashlib.sha256(
    b"legacy-task-to-relational-ledger-v1:preserve-source-and-map-every-record"
).hexdigest()


def apply_major_tasks_schema(db, now_fn):
    """Apply the current schema atomically and seed editable workstreams idempotently."""
    now = now_fn()
    existing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='major_task_schema_migrations'"
    ).fetchone()
    if existing:
        row = db.execute(
            "SELECT checksum FROM major_task_schema_migrations WHERE version=?",
            (MAJOR_TASKS_SCHEMA_VERSION,),
        ).fetchone()
        if row:
            if row["checksum"] != MAJOR_TASKS_SCHEMA_CHECKSUM:
                raise RuntimeError("주요업무 마이그레이션 체크섬이 일치하지 않습니다.")
            return False
    db.execute("SAVEPOINT major_tasks_schema_v2")
    try:
        for statement in SCHEMA_STATEMENTS:
            db.execute(statement)
        task_columns = {row["name"] for row in db.execute("PRAGMA table_info(major_tasks)")}
        additive_task_columns = {
            "review_cycle_days_override": "INTEGER",
            "due_soon_days_override": "INTEGER",
            "hard_deadline_soon_days_override": "INTEGER",
            "parent_task_id": "TEXT",
            "section_id": "TEXT REFERENCES major_task_sections(id)",
            "current_stage_id": "TEXT",
            "blocker_active": "INTEGER NOT NULL DEFAULT 0",
            "blocker_category": "TEXT",
            "blocker_description": "TEXT NOT NULL DEFAULT ''",
            "blocker_owner_id": "INTEGER",
            "blocker_since": "TEXT",
            "blocker_resolved_at": "TEXT",
            "directive_type": "TEXT",
            "directed_by_user_id": "INTEGER",
            "directive_note": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in additive_task_columns.items():
            if column not in task_columns:
                db.execute(f"ALTER TABLE major_tasks ADD COLUMN {column} {definition}")
        progress_columns = {row["name"] for row in db.execute("PRAGMA table_info(major_task_progress_updates)")}
        additive_progress_columns = {
            "applied_stage_id": "TEXT",
            "applied_ball_id": "TEXT",
            "applied_rag": "TEXT",
            "state_change_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, definition in additive_progress_columns.items():
            if column not in progress_columns:
                db.execute(f"ALTER TABLE major_task_progress_updates ADD COLUMN {column} {definition}")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_major_tasks_parent "
            "ON major_tasks(parent_task_id, status)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_major_tasks_section "
            "ON major_tasks(section_id, parent_task_id, status)"
        )
        for order, name in enumerate(DEFAULT_WORKSTREAMS, start=1):
            db.execute(
                """INSERT OR IGNORE INTO major_task_workstreams
                   (id,name,description,color,display_order,is_active,due_soon_days,
                    hard_deadline_soon_days,template_version,version,created_at,updated_at)
                   VALUES (?,?,?,?,?,1,3,7,1,1,?,?)""",
                (_uuid(f"major-task-workstream:{name}"), name, "", "#0a7d6b", order, now, now),
            )
        db.execute(
            "INSERT INTO major_task_schema_migrations(version,checksum,applied_at) VALUES (?,?,?)",
            (MAJOR_TASKS_SCHEMA_VERSION, MAJOR_TASKS_SCHEMA_CHECKSUM, now),
        )
        db.execute("PRAGMA optimize")
        db.execute("RELEASE SAVEPOINT major_tasks_schema_v2")
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT major_tasks_schema_v2")
        db.execute("RELEASE SAVEPOINT major_tasks_schema_v2")
        raise
    return True


def _business(payload):
    value = str(payload.get("business_unit") or "").strip().lower()
    return value if value in {"dental", "medical", "aesthetic"} else "legacy_unclassified"


def _status(value):
    return {
        "todo": "not_started", "active": "in_progress", "in_progress": "in_progress",
        "blocked": "hold", "hold": "hold", "done": "completed", "completed": "completed",
        "cancelled": "cancelled", "closed": "cancelled",
    }.get(str(value or "").lower(), "not_started")


def _importance(payload):
    value = str(payload.get("priority") or "medium").lower()
    return value if value in {"high", "medium", "low"} else "medium"


def _customer_link(db, legacy_row, payload):
    account_id = str(payload.get("account_id") or "").strip()
    if not account_id:
        return None, "unlinked"
    row = db.execute(
        "SELECT id FROM customer_master WHERE id=? OR source_record_id=?",
        (account_id, account_id),
    ).fetchone()
    return (row["id"], "linked") if row else (None, "review_required")


def _insert_task(db, row, payload, now, orphan=False):
    task_id = _uuid(f"major-task:legacy:{row['id']}")
    customer_id, link_status = _customer_link(db, row, payload)
    status = _status(row["status"])
    description = str(payload.get("description") or "")
    company = str(payload.get("company_name") or payload.get("account_name") or "")
    values = {
        "id": task_id,
        "legacy_record_id": row["id"],
        "title": row["title"],
        "primary_business_unit": _business(payload),
        "workstream_id": None,
        "region": row["region"] or "",
        "country": row["country"] or "",
        "customer_master_id": customer_id,
        "legacy_customer_name": company,
        "customer_link_status": link_status,
        "purpose": description,
        "completion_criteria": "",
        "owner_id": row["owner_id"],
        "importance": _importance(payload),
        "original_target_date": row["due_date"],
        "current_target_date": row["due_date"],
        "status": status,
        "auto_rag": "green",
        "final_rag": "green",
        "next_action": str(payload.get("next_action") or ""),
        "legacy_description": description,
        "legacy_amount": float(row["amount"] or 0),
        "legacy_currency": row["currency"] or "USD",
        "legacy_priority": str(payload.get("priority") or ""),
        "legacy_status": row["status"] or "",
        "legacy_task_kind": str(payload.get("task_kind") or ""),
        "legacy_parent_task_id": str(payload.get("parent_task_id") or "") or None,
        "legacy_task_order": int(payload.get("task_order") or 0) or None,
        "legacy_payload_json": row["payload_json"] or "{}",
        "migration_review_required": 1 if orphan else 0,
        "recent_updated_at": row["updated_at"] or now,
        "archived_at": row["deleted_at"],
        "version": 1,
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "created_at": row["created_at"] or now,
        "updated_at": row["updated_at"] or now,
    }
    columns = list(values)
    db.execute(
        f"INSERT OR IGNORE INTO major_tasks ({','.join(columns)}) "
        f"VALUES ({','.join('?' for _ in columns)})",
        tuple(values[column] for column in columns),
    )
    db.execute(
        """INSERT OR IGNORE INTO major_task_business_links
           (task_id,business_unit,business_subcategory,is_primary,created_at) VALUES (?,?,?,?,?)""",
        (task_id, _business(payload), "", 1, now),
    )
    return task_id


def migrate_legacy_tasks(db, now_fn):
    """Copy legacy records.task rows without mutating or deleting their source rows."""
    now = now_fn()
    rows = db.execute(
        "SELECT * FROM records WHERE entity_type='task' ORDER BY created_at,id"
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    payloads = {row["id"]: _payload(row["payload_json"]) for row in rows}
    children = defaultdict(list)
    for row in rows:
        parent = str(payloads[row["id"]].get("parent_task_id") or "").strip()
        if parent:
            children[parent].append(row)
    stats = {"legacy": len(rows), "tasks": 0, "milestones": 0, "actions": 0, "orphans": 0, "skipped": 0}
    db.execute("SAVEPOINT major_tasks_legacy_v1")
    try:
        # Top-level records become the official major-task rows.
        for row in rows:
            payload = payloads[row["id"]]
            parent_id = str(payload.get("parent_task_id") or "").strip()
            if parent_id and parent_id in by_id:
                continue
            if db.execute("SELECT 1 FROM major_task_legacy_mappings WHERE legacy_record_id=?", (row["id"],)).fetchone():
                stats["skipped"] += 1
                continue
            orphan = bool(parent_id and parent_id not in by_id)
            task_id = _insert_task(db, row, payload, now, orphan=orphan)
            stats["tasks"] += 1
            stats["orphans"] += int(orphan)
            db.execute(
                """INSERT INTO major_task_legacy_mappings
                   (legacy_record_id,task_id,migration_status,legacy_task_kind,legacy_parent_task_id,
                    legacy_task_order,legacy_payload_json,migrated_at) VALUES (?,?,?,?,?,?,?,?)""",
                (row["id"], task_id, "review_required" if orphan else "migrated",
                 str(payload.get("task_kind") or ""), parent_id or None,
                 int(payload.get("task_order") or 0) or None, row["payload_json"] or "{}", now),
            )

        # Existing grouped details become action items under one migration milestone.
        for parent_id, detail_rows in children.items():
            if parent_id not in by_id:
                continue
            mapping = db.execute(
                "SELECT task_id FROM major_task_legacy_mappings WHERE legacy_record_id=?", (parent_id,)
            ).fetchone()
            if not mapping:
                parent = by_id[parent_id]
                parent_payload = payloads[parent_id]
                task_id = _insert_task(db, parent, parent_payload, now)
                db.execute(
                    """INSERT OR IGNORE INTO major_task_legacy_mappings
                       (legacy_record_id,task_id,migration_status,legacy_task_kind,legacy_parent_task_id,
                        legacy_task_order,legacy_payload_json,migrated_at) VALUES (?,?, 'migrated',?,?,?,?,?)""",
                    (parent_id, task_id, str(parent_payload.get("task_kind") or ""), None,
                     int(parent_payload.get("task_order") or 0) or None, parent["payload_json"] or "{}", now),
                )
                stats["tasks"] += 1
            else:
                task_id = mapping["task_id"]
            milestone_id = _uuid(f"major-task:legacy-milestone:{parent_id}")
            before = db.total_changes
            db.execute(
                """INSERT OR IGNORE INTO major_task_milestones
                   (id,task_id,name,description,status,is_required,display_order,is_active,version,
                    created_by,updated_by,created_at,updated_at)
                   VALUES (?,?, '기존 세부항목','기존 주요업무의 세부항목을 원문 그대로 이전했습니다.',
                           'not_started',1,1,1,1,?,?,?,?)""",
                (milestone_id, task_id, by_id[parent_id]["created_by"], by_id[parent_id]["updated_by"], now, now),
            )
            if db.total_changes > before:
                stats["milestones"] += 1
            for detail in sorted(detail_rows, key=lambda item: (int(payloads[item["id"]].get("task_order") or 999999), item["created_at"], item["id"])):
                detail_payload = payloads[detail["id"]]
                existing = db.execute(
                    "SELECT 1 FROM major_task_legacy_mappings WHERE legacy_record_id=?", (detail["id"],)
                ).fetchone()
                if existing:
                    stats["skipped"] += 1
                    continue
                action_id = _uuid(f"major-task:legacy-action:{detail['id']}")
                action_status = {
                    "todo": "not_started", "in_progress": "in_progress", "blocked": "waiting",
                    "done": "completed", "completed": "completed", "cancelled": "cancelled",
                }.get(str(detail["status"] or "").lower(), "not_started")
                db.execute(
                    """INSERT INTO major_task_actions
                      (id,task_id,milestone_id,legacy_record_id,name,owner_id,due_date,status,importance,
                       is_required,include_in_progress,include_in_rag,result,next_action,display_order,
                       legacy_description,legacy_amount,legacy_currency,legacy_payload_json,is_active,
                       version,created_by,updated_by,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,1,1,1,'',?,?,?,?,?,?,?,1,?,?,?,?)""",
                    (
                        action_id, task_id, milestone_id, detail["id"], detail["title"], detail["owner_id"],
                        detail["due_date"], action_status, _importance(detail_payload),
                        str(detail_payload.get("next_action") or ""), int(detail_payload.get("task_order") or 0),
                        str(detail_payload.get("description") or ""), float(detail["amount"] or 0),
                        detail["currency"] or "USD", detail["payload_json"] or "{}",
                        0 if detail["deleted_at"] else 1, detail["created_by"],
                        detail["updated_by"], detail["created_at"] or now, detail["updated_at"] or now,
                    ),
                )
                db.execute(
                    """INSERT INTO major_task_legacy_mappings
                       (legacy_record_id,task_id,milestone_id,action_id,migration_status,legacy_task_kind,
                        legacy_parent_task_id,legacy_task_order,legacy_payload_json,migrated_at)
                       VALUES (?,?,?,?, 'migrated',?,?,?,?,?)""",
                    (detail["id"], task_id, milestone_id, action_id,
                     str(detail_payload.get("task_kind") or "detail"), parent_id,
                     int(detail_payload.get("task_order") or 0) or None, detail["payload_json"] or "{}", now),
                )
                stats["actions"] += 1
        db.execute("RELEASE SAVEPOINT major_tasks_legacy_v1")
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT major_tasks_legacy_v1")
        db.execute("RELEASE SAVEPOINT major_tasks_legacy_v1")
        raise
    return stats


def apply_major_tasks_legacy_migration(db, now_fn):
    """Migrate legacy task rows and record readiness in one transaction.

    The separate marker prevents a schema-only partial run from making the
    application treat the new ledger as authoritative.
    """
    row = db.execute(
        "SELECT checksum FROM major_task_schema_migrations WHERE version=?",
        (MAJOR_TASKS_LEGACY_MIGRATION_VERSION,),
    ).fetchone()
    if row:
        if row["checksum"] != MAJOR_TASKS_LEGACY_MIGRATION_CHECKSUM:
            raise RuntimeError("주요업무 기존자료 이관 체크섬이 일치하지 않습니다.")
        return {"legacy": 0, "tasks": 0, "milestones": 0, "actions": 0, "orphans": 0, "skipped": 0, "status": "already_applied"}
    now = now_fn()
    db.execute("SAVEPOINT major_tasks_legacy_release_v1")
    try:
        stats = migrate_legacy_tasks(db, now_fn)
        db.execute(
            "INSERT INTO major_task_schema_migrations(version,checksum,applied_at) VALUES (?,?,?)",
            (MAJOR_TASKS_LEGACY_MIGRATION_VERSION, MAJOR_TASKS_LEGACY_MIGRATION_CHECKSUM, now),
        )
        db.execute("RELEASE SAVEPOINT major_tasks_legacy_release_v1")
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT major_tasks_legacy_release_v1")
        db.execute("RELEASE SAVEPOINT major_tasks_legacy_release_v1")
        raise
    return {**stats, "status": "applied"}
