"""Relational major-task ledger, APIs, permissions, RAG and dashboard adapters."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import g, jsonify, request

from major_tasks_migration import MAJOR_TASKS_SCHEMA_VERSION
from maps_taxonomy import PARENT_BUSINESS_AREAS
import stage_work_items as stage_work


SEOUL = ZoneInfo("Asia/Seoul")
READ_ROLES = ("admin", "manager", "editor", "viewer")
WRITE_ROLES = ("admin", "manager", "editor")
MANAGE_ROLES = {"admin", "manager"}
TASK_STATUSES = {
    "not_started", "in_progress", "internal_work", "external_wait",
    "cooperation_wait", "hold", "completed", "cancelled",
}
ITEM_STATUSES = {"not_started", "in_progress", "waiting", "completed", "cancelled"}
BUSINESS = {
    "common": (),
    "dental": ("xenograft", "allograft"),
    "medical": ("bone_graft", "general_medical"),
    "aesthetic": ("adite", "pl_business"),
    "legacy_unclassified": (),
}
BUSINESS_LABELS = {
    "common": "공통",
    **PARENT_BUSINESS_AREAS,
    "legacy_unclassified": "기존 미분류",
}
RAG_SCORE = {"green": 0, "amber": 1, "red": 2}
BALL_OWNER_TYPES = {"internal", "executive", "department", "buyer", "external_agency", "logistics", "none"}
BALL_TYPE_ALIASES = {
    "internal": "internal",
    "customer": "buyer",
    "external": "external_agency",
    "none": "none",
}
BALL_CANONICAL_TYPES = {
    "internal": "internal",
    "buyer": "customer",
    "external_agency": "external",
    "executive": "internal",
    "department": "internal",
    "logistics": "external",
    "none": "none",
}
BLOCKER_CATEGORIES = {"customer", "regulatory", "commercial", "internal", "external", "other"}
DIRECTIVE_TYPES = {"ceo", "division_head", "other"}
STAGE_STATUSES = {"planned", "active", "completed", "inactive"}
MAX_UI_HIERARCHY_DEPTH = 3
STAGE_TEMPLATES = {
    "new_distributor": ("업체 발굴", "접촉", "샘플", "평가", "계약", "초도 주문"),
    "registration": ("자료준비", "제출", "검토", "보완", "승인"),
    "existing_expansion": ("기회 발굴", "제안", "협의", "발주", "실행"),
}
CANONICAL_WORKSTREAMS = {
    "신규사업개발": "new_business_development",
    "기존사업 확대": "existing_business_expansion",
    "인허가·등록": "regulatory_registration",
    "계약·상업조건": "contract_commercial",
    "마케팅·교육·전시": "marketing_education_exhibition",
    "내부·전략": "internal_strategy",
}
LEGACY_WORKSTREAM_REVIEW = {
    "신규시장·딜러개발": "new_business_development",
    "계약·가격·바이어 온보딩": "contract_commercial",
    "인허가·규제": "regulatory_registration",
    "프로모션·전시회·마케팅": "marketing_education_exhibition",
    "내부업무": "internal_strategy",
    "ODM·제품개발": None,
    "매출·수금·채권": None,
    "출고·물류·통관": None,
    "기타": None,
}
SECTION_NAME_MAX_LENGTH = 80
SECTION_RESERVED_NAMES = {
    "전체", "미분류", "section", "section 관리", "새 section", "+ 새 section",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(SEOUL).date()


def _row(row):
    return dict(row) if row is not None else None


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _clean(value, limit=1000):
    return str(value or "").strip()[:limit]


def _bool(value):
    return 1 if value in (True, 1, "1", "true", "on", "yes") else 0


def _int(value, default=None):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("숫자 형식이 올바르지 않습니다.") from exc


def _optional_days(value, label):
    parsed = _int(value)
    if parsed is not None and parsed < 0:
        raise ValueError(f"{label}은 0 이상의 숫자로 입력하세요.")
    return parsed


def _date(value, label="날짜"):
    value = _clean(value, 10)
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label}는 YYYY-MM-DD 형식으로 입력하세요.") from exc


def _section_name(value):
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        raise ValueError("Section 이름을 입력하세요.")
    if len(name) > SECTION_NAME_MAX_LENGTH:
        raise ValueError(f"Section 이름은 {SECTION_NAME_MAX_LENGTH}자 이내로 입력하세요.")
    if name.casefold() in SECTION_RESERVED_NAMES:
        raise ValueError("화면에서 사용하는 예약 이름은 Section 이름으로 사용할 수 없습니다.")
    return name


def _section_name_exists(db, name, exclude_id=None):
    rows = db.execute(
        "SELECT id,name FROM major_task_sections WHERE id<>COALESCE(?, '')",
        (exclude_id,),
    ).fetchall()
    key = name.casefold()
    return any(re.sub(r"\s+", " ", row["name"].strip()).casefold() == key for row in rows)


def _section_rows(db):
    return [dict(row) for row in db.execute(
        """SELECT s.*,
                  SUM(CASE WHEN t.id IS NOT NULL AND t.parent_task_id IS NULL THEN 1 ELSE 0 END) AS root_task_count,
                  COUNT(t.id) AS assigned_task_count
           FROM major_task_sections s
           LEFT JOIN major_tasks t ON t.section_id=s.id
           GROUP BY s.id
           ORDER BY s.sort_order,s.name COLLATE NOCASE,s.id"""
    )]


def _root_section(db, task_id):
    """Return the root task and its Section without changing descendant rows."""
    current = task_id
    seen = set()
    last = None
    while current and current not in seen:
        seen.add(current)
        row = db.execute(
            """SELECT t.id,t.parent_task_id,t.section_id,
                      s.name AS section_name,s.is_active AS section_active
               FROM major_tasks t
               LEFT JOIN major_task_sections s ON s.id=t.section_id
               WHERE t.id=?""",
            (current,),
        ).fetchone()
        if not row:
            break
        last = row
        if not row["parent_task_id"]:
            break
        current = row["parent_task_id"]
    if not last:
        return {
            "root_task_id": task_id, "section_id": None,
            "section_name": None, "section_active": None,
        }
    return {
        "root_task_id": last["id"],
        "section_id": last["section_id"],
        "section_name": last["section_name"],
        "section_active": last["section_active"],
    }


def _ball_owner_type(value):
    raw = _clean(value, 30)
    normalized = BALL_TYPE_ALIASES.get(raw, raw)
    if normalized not in BALL_OWNER_TYPES:
        raise ValueError("Ball 소유자 유형이 올바르지 않습니다.")
    return normalized


def _task_parent_cycle(db, task_id, parent_task_id):
    """Return True when the proposed parent would create a self/ancestor cycle."""
    if not parent_task_id:
        return False
    if task_id and parent_task_id == task_id:
        return True
    seen = set()
    current = parent_task_id
    while current:
        if current in seen or (task_id and current == task_id):
            return True
        seen.add(current)
        row = db.execute("SELECT parent_task_id FROM major_tasks WHERE id=?", (current,)).fetchone()
        if not row:
            return False
        current = row["parent_task_id"]
    return False


def _normalized_user_ids(db, values, label, *, required=False):
    """Validate one user-id based role list while preserving its UI order."""
    if values is None:
        return None
    if not isinstance(values, list):
        raise ValueError(f"{label} 목록 형식이 올바르지 않습니다.")
    normalized = []
    seen = set()
    for value in values:
        user_id = _int(value)
        if user_id is None:
            continue
        if user_id in seen:
            raise ValueError(f"같은 사용자를 {label}에 중복 지정할 수 없습니다.")
        if not _user_exists(db, user_id):
            raise ValueError(f"{label} 사용자를 찾을 수 없습니다.")
        seen.add(user_id)
        normalized.append(user_id)
    if required and not normalized:
        raise ValueError(f"{label}를 한 명 이상 지정하세요.")
    return normalized


def _task_depth(db, task_id):
    """Return the recursive 1-based task depth, or None for a broken/cyclic chain."""
    if not task_id:
        return 0
    depth = 0
    current = task_id
    seen = set()
    while current:
        if current in seen:
            return None
        seen.add(current)
        row = db.execute(
            "SELECT parent_task_id FROM major_tasks WHERE id=?", (current,)
        ).fetchone()
        if not row:
            return None
        depth += 1
        current = row["parent_task_id"]
    return depth


def _task_subtree_height(db, task_id):
    """Return the greatest descendant distance including the task itself."""
    if not task_id:
        return 1
    maximum = 1
    stack = [(task_id, 1)]
    seen = set()
    while stack:
        current, height = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        maximum = max(maximum, height)
        for row in db.execute(
            "SELECT id FROM major_tasks WHERE parent_task_id=?", (current,)
        ):
            stack.append((row["id"], height + 1))
    return maximum


def _task_path(db, task_id):
    """Build a root-to-task breadcrumb without trusting an acyclic database."""
    parts = []
    current = task_id
    seen = set()
    while current and current not in seen:
        seen.add(current)
        row = db.execute(
            "SELECT id,title,parent_task_id FROM major_tasks WHERE id=?", (current,)
        ).fetchone()
        if not row:
            break
        parts.append({"id": row["id"], "title": row["title"]})
        current = row["parent_task_id"]
    parts.reverse()
    return parts


def _parent_candidates(db):
    rows = db.execute(
        """SELECT id,title,status,parent_task_id,archived_at
           FROM major_tasks
           WHERE status<>'cancelled' AND archived_at IS NULL
           ORDER BY title COLLATE NOCASE"""
    ).fetchall()
    candidates = []
    for row in rows:
        path = _task_path(db, row["id"])
        depth = len(path)
        root_section = _root_section(db, row["id"])
        candidates.append({
            "id": row["id"],
            "title": row["title"],
            "status": row["status"],
            "parent_task_id": row["parent_task_id"],
            "depth": depth,
            "path": " > ".join(part["title"] for part in path),
            "ancestor_ids": [part["id"] for part in path[:-1]],
            "selectable": depth < MAX_UI_HIERARCHY_DEPTH,
            "root_task_id": root_section["root_task_id"],
            "root_section_id": root_section["section_id"],
            "root_section_name": root_section["section_name"],
            "root_section_active": root_section["section_active"],
        })
    candidates.sort(key=lambda row: (row["path"].casefold(), row["id"]))
    return candidates


def _version(data):
    value = _int(data.get("version"))
    if value is None or value < 1:
        raise ValueError("수정 버전이 없습니다. 최신 자료를 다시 불러오세요.")
    return value


def _user_exists(db, user_id):
    if user_id is None:
        return True
    return db.execute(
        "SELECT 1 FROM users WHERE id=? AND status='active' AND deleted_at IS NULL", (user_id,)
    ).fetchone() is not None


def _business_values(unit, subcategory, legacy=False):
    unit = _clean(unit, 40)
    subcategory = _clean(subcategory, 60)
    allowed = set(BUSINESS)
    if unit not in allowed or (unit == "legacy_unclassified" and not legacy):
        raise ValueError("주 사업분야를 선택하세요.")
    if BUSINESS[unit] and subcategory not in BUSINESS[unit]:
        raise ValueError("선택한 사업분야의 하위분류를 선택하세요.")
    if not BUSINESS[unit]:
        subcategory = ""
    return unit, subcategory


def _normalized_business_links(db, data, existing=None):
    """Validate the unified, ordered business-area pair payload when supplied."""
    raw_links = data.get("business_links")
    unified = data.get("business_links_mode") == "unified" or (
        isinstance(raw_links, list)
        and any(isinstance(link, dict) and "is_primary" in link for link in raw_links)
    )
    if not unified:
        return None
    if not isinstance(raw_links, list) or not raw_links:
        raise ValueError("사업분야·하위분류를 한 개 이상 연결하세요.")

    legacy = bool(existing and existing["legacy_record_id"])
    existing_pairs = set()
    if existing and existing["id"]:
        existing_pairs = {
            (row["business_unit"], row["business_subcategory"])
            for row in db.execute(
                "SELECT business_unit,business_subcategory FROM major_task_business_links WHERE task_id=?",
                (existing["id"],),
            )
        }
    normalized = []
    seen = set()
    primary_count = 0
    for link in raw_links:
        if not isinstance(link, dict):
            raise ValueError("사업분야 연결 정보를 다시 확인하세요.")
        raw_unit = _clean(link.get("business_unit"), 40)
        raw_subcategory = _clean(link.get("business_subcategory"), 60)
        try:
            unit, subcategory = _business_values(raw_unit, raw_subcategory, legacy=legacy)
        except ValueError:
            if (raw_unit, raw_subcategory) not in existing_pairs:
                raise
            unit, subcategory = raw_unit, raw_subcategory
        pair = (unit, subcategory)
        if pair in seen:
            raise ValueError("같은 사업분야·하위분류 Pair는 중복 추가할 수 없습니다.")
        seen.add(pair)
        is_primary = bool(_bool(link.get("is_primary")))
        primary_count += int(is_primary)
        normalized.append({
            "business_unit": unit,
            "business_subcategory": subcategory,
            "is_primary": is_primary,
        })
    if primary_count > 1:
        raise ValueError("Primary 사업분야 Pair는 하나만 지정하세요.")
    if primary_count == 0:
        normalized[0]["is_primary"] = True
    return normalized


def _task_row(db, task_id):
    return db.execute(
        """SELECT t.*,w.name AS workstream_name,w.color AS workstream_color,
                  w.review_cycle_days AS workstream_review_cycle_days,
                  w.due_soon_days AS workstream_due_soon_days,
                  w.hard_deadline_soon_days AS workstream_hard_deadline_soon_days,
                  o.display_name AS owner_name,d.display_name AS deputy_owner_name,
                  c.display_name AS customer_name,
                  sec.name AS section_name,sec.is_active AS section_active,
                  p.title AS parent_title,
                  s.name AS current_stage_name,s.status AS current_stage_status,
                  bo.display_name AS blocker_owner_name,
                  du.display_name AS directed_by_name,
                  cr.display_name AS created_by_name,
                  up.display_name AS updated_by_name
           FROM major_tasks t
           LEFT JOIN major_task_workstreams w ON w.id=t.workstream_id
           LEFT JOIN users o ON o.id=t.owner_id
           LEFT JOIN users d ON d.id=t.deputy_owner_id
           LEFT JOIN customer_master c ON c.id=t.customer_master_id
           LEFT JOIN major_task_sections sec ON sec.id=t.section_id
           LEFT JOIN major_tasks p ON p.id=t.parent_task_id
           LEFT JOIN major_task_stages s ON s.id=t.current_stage_id AND s.task_id=t.id
           LEFT JOIN users bo ON bo.id=t.blocker_owner_id
           LEFT JOIN users du ON du.id=t.directed_by_user_id
           LEFT JOIN users cr ON cr.id=t.created_by
           LEFT JOIN users up ON up.id=t.updated_by
           WHERE t.id=?""",
        (task_id,),
    ).fetchone()


def _task_relation(db, task, user_id):
    if not task or user_id is None:
        return set()
    relations = set()
    if task["created_by"] == user_id:
        relations.add("creator")
    if task["owner_id"] == user_id:
        relations.add("owner")
    if task["deputy_owner_id"] == user_id:
        relations.add("deputy")
    if db.execute(
        "SELECT 1 FROM major_task_assignees WHERE task_id=? AND user_id=? LIMIT 1",
        (task["id"], user_id),
    ).fetchone():
        relations.add("additional_owner")
    relations.update(row["relation_type"] for row in db.execute(
        "SELECT relation_type FROM major_task_people WHERE task_id=? AND user_id=?", (task["id"], user_id)
    ))
    return relations


def _can_structure(db, task, user):
    # Creator/owner/assignee links describe the work; they never grant or
    # remove ordinary edit permission. All write roles edit every task.
    return bool(user and user["role"] in WRITE_ROLES)


def _can_progress(db, task, user):
    if _can_structure(db, task, user):
        return True
    if user["role"] != "editor":
        return False
    if _task_relation(db, task, user["id"]) & {"participant", "cooperator"}:
        return True
    if db.execute(
        "SELECT 1 FROM major_task_milestones WHERE task_id=? AND (owner_id=? OR deputy_owner_id=?) AND is_active=1 LIMIT 1",
        (task["id"], user["id"], user["id"]),
    ).fetchone():
        return True
    if db.execute(
        "SELECT 1 FROM major_task_actions WHERE task_id=? AND (owner_id=? OR deputy_owner_id=?) AND is_active=1 LIMIT 1",
        (task["id"], user["id"], user["id"]),
    ).fetchone():
        return True
    return db.execute(
        """SELECT 1 FROM major_task_action_people p
           JOIN major_task_actions a ON a.id=p.action_id
           WHERE a.task_id=? AND a.is_active=1 AND p.user_id=? LIMIT 1""",
        (task["id"], user["id"]),
    ).fetchone() is not None


def _can_milestone(db, milestone, user):
    task = _task_row(db, milestone["task_id"])
    return _can_structure(db, task, user) or (
        user["role"] == "editor" and user["id"] in {milestone["owner_id"], milestone["deputy_owner_id"]}
    )


def _can_action(db, action, user):
    task = _task_row(db, action["task_id"])
    if _can_structure(db, task, user):
        return True
    milestone = db.execute(
        "SELECT owner_id,deputy_owner_id FROM major_task_milestones WHERE id=?",
        (action["milestone_id"],),
    ).fetchone()
    allowed = {action["owner_id"], action["deputy_owner_id"]}
    if milestone:
        allowed.update({milestone["owner_id"], milestone["deputy_owner_id"]})
    return user["role"] == "editor" and user["id"] in allowed


def _can_ball(db, ball, user):
    task = _task_row(db, ball["task_id"])
    if _can_structure(db, task, user):
        return True
    if ball["action_id"]:
        action = db.execute("SELECT * FROM major_task_actions WHERE id=? AND is_active=1", (ball["action_id"],)).fetchone()
        return bool(action and _can_action(db, action, user))
    if ball["milestone_id"]:
        milestone = db.execute("SELECT * FROM major_task_milestones WHERE id=? AND is_active=1", (ball["milestone_id"],)).fetchone()
        return bool(milestone and _can_milestone(db, milestone, user))
    return False


def _can_attachment(db, task, user, milestone=None, action=None, progress=None):
    if _can_structure(db, task, user):
        return True
    return bool(
        (action is not None and _can_action(db, action, user))
        or (milestone is not None and _can_milestone(db, milestone, user))
        or (progress is not None and user["role"] == "editor" and progress["created_by"] == user["id"])
    )


def _named_users(db, user_ids):
    ordered = []
    seen = set()
    for user_id in user_ids:
        if user_id is None or user_id in seen:
            continue
        seen.add(user_id)
        row = db.execute(
            "SELECT id AS user_id,display_name,role,status FROM users WHERE id=? AND deleted_at IS NULL",
            (user_id,),
        ).fetchone()
        if row:
            ordered.append(dict(row))
    return ordered


def _task_additional_owner_ids(db, task):
    ids = []
    if task["deputy_owner_id"] is not None:
        ids.append(task["deputy_owner_id"])
    ids.extend(
        row["user_id"] for row in db.execute(
            """SELECT user_id FROM major_task_assignees
               WHERE task_id=? AND relation_type='additional_owner'
               ORDER BY created_at,user_id""",
            (task["id"],),
        )
    )
    return [row["user_id"] for row in _named_users(db, ids) if row["user_id"] != task["owner_id"]]


def _task_owner_people(db, task):
    people = _named_users(db, [task["owner_id"], *_task_additional_owner_ids(db, task)])
    for person in people:
        person["is_primary"] = person["user_id"] == task["owner_id"]
        person["relation_type"] = "primary_owner" if person["is_primary"] else "additional_owner"
    return people


def _stage_assignee_ids(db, stage):
    relation_ids = [
        row["user_id"] for row in db.execute(
            """SELECT user_id FROM major_task_stage_people
               WHERE stage_id=? AND relation_type='assignee'
               ORDER BY created_at,user_id""",
            (stage["id"],),
        )
    ]
    ids = relation_ids or ([stage["owner_id"]] if stage["owner_id"] is not None else [])
    return [row["user_id"] for row in _named_users(db, ids)]


def _action_assignee_ids(db, action):
    ids = [action["owner_id"], action["deputy_owner_id"]]
    ids.extend(
        row["user_id"] for row in db.execute(
            """SELECT user_id FROM major_task_action_people
               WHERE action_id=? ORDER BY created_at,user_id""",
            (action["id"],),
        )
    )
    return [row["user_id"] for row in _named_users(db, ids)]


def _task_people_snapshot(db, task):
    relations = {
        "participant": [],
        "cooperator": [],
    }
    for row in db.execute(
        """SELECT relation_type,user_id FROM major_task_people
           WHERE task_id=? ORDER BY relation_type,user_id""",
        (task["id"],),
    ):
        relations[row["relation_type"]].append(row["user_id"])
    return {
        "created_by": task["created_by"],
        "primary_owner_id": task["owner_id"],
        "additional_owner_ids": _task_additional_owner_ids(db, task),
        "participant_ids": relations["participant"],
        "cooperator_ids": relations["cooperator"],
    }


def _touch_task(db, task_id, actor_id, occurred_at=None):
    stamp = occurred_at or _now()
    db.execute(
        "UPDATE major_tasks SET recent_updated_at=?,updated_at=?,updated_by=?,version=version+1 WHERE id=?",
        (stamp, stamp, actor_id, task_id),
    )


def _week_bounds(reference=None):
    reference = reference or _today()
    start = reference - timedelta(days=reference.weekday())
    return start, start + timedelta(days=6)


def _task_due(task):
    return task["hard_deadline_date"] if task["hard_deadline_enabled"] and task["hard_deadline_date"] else task["current_target_date"]


def _auto_rag(db, task):
    if task["status"] in {"completed", "cancelled"}:
        return "green", []
    today = _today()
    reasons = []
    risk = "green"

    def raise_risk(level, reason):
        nonlocal risk
        if RAG_SCORE[level] > RAG_SCORE[risk]:
            risk = level
        reasons.append(reason)

    workstream = db.execute(
        "SELECT review_cycle_days,due_soon_days,hard_deadline_soon_days FROM major_task_workstreams WHERE id=?",
        (task["workstream_id"],),
    ).fetchone()
    due_soon = int(task["due_soon_days_override"] if task["due_soon_days_override"] is not None else workstream["due_soon_days"] if workstream else 3)
    hard_soon = int(task["hard_deadline_soon_days_override"] if task["hard_deadline_soon_days_override"] is not None else workstream["hard_deadline_soon_days"] if workstream else 7)
    review_cycle = task["review_cycle_days_override"] if task["review_cycle_days_override"] is not None else workstream["review_cycle_days"] if workstream else None
    if review_cycle and task["recent_updated_at"]:
        try:
            last_update = datetime.fromisoformat(task["recent_updated_at"].replace("Z", "+00:00")).astimezone(SEOUL).date()
            if (today - last_update).days > int(review_cycle):
                raise_risk("amber", f"설정된 점검주기 {review_cycle}일 초과")
        except (TypeError, ValueError):
            pass
    if task["hard_deadline_enabled"] and task["hard_deadline_date"]:
        diff = (date.fromisoformat(task["hard_deadline_date"]) - today).days
        if diff < 0:
            raise_risk("red", "Hard Deadline 초과")
        elif diff <= hard_soon:
            raise_risk("amber", f"Hard Deadline D-{max(diff, 0)}")
    if task["next_action_date"]:
        diff = (date.fromisoformat(task["next_action_date"]) - today).days
        if diff < 0:
            raise_risk("red", "Due Overdue")
        elif diff <= due_soon:
            raise_risk("amber", f"Next Action D-{max(diff, 0)}")
    if task["blocker_active"]:
        raise_risk("red", "활성 Blocker")
    if not task["owner_id"]:
        raise_risk("amber", "담당자 미지정")
    if task["status"] == "hold" and not task["review_date"]:
        raise_risk("amber", "보류 재검토일 미지정")

    included_milestones = {row["id"] for row in db.execute(
        "SELECT id FROM major_task_milestones WHERE task_id=? AND is_active=1 AND is_required=1",
        (task["id"],),
    )}
    actions = db.execute(
        """SELECT a.* FROM major_task_actions a
           JOIN major_task_milestones m ON m.id=a.milestone_id
           WHERE a.task_id=? AND a.is_active=1 AND m.is_active=1 AND m.is_required=1
             AND a.status NOT IN ('completed','cancelled')
             AND (a.is_required=1 OR a.include_in_rag=1)""",
        (task["id"],),
    ).fetchall()
    action_by_id = {row["id"]: row for row in actions}
    balls = _current_balls(db, task["id"])
    for ball in balls:
        if ball["action_id"] and ball["action_id"] not in action_by_id:
            continue
        if not ball["action_id"] and ball["milestone_id"] and ball["milestone_id"] not in included_milestones:
            continue
        if ball["hard_deadline_impact"] in {"amber", "red"}:
            raise_risk(ball["hard_deadline_impact"], "외부대기가 목표기한에 영향")
        if BALL_CANONICAL_TYPES.get(ball["owner_type"], "external") != "internal":
            continue
        action = action_by_id.get(ball["action_id"])
        due = action["due_date"] if action else ball["resolution_due_date"]
        if due:
            diff = (date.fromisoformat(due) - today).days
            if diff < 0:
                raise_risk("red", "당사 내부 Ball 실행기한 초과")
            elif diff <= due_soon:
                raise_risk("amber", "당사 내부 Ball 실행기한 임박")
        if not ((action and action["next_action"]) or task["next_action"]):
            raise_risk("amber", "당사 내부 Ball 다음 액션 미지정")
    return risk, reasons


def _refresh_rag(db, task_id):
    task = _task_row(db, task_id)
    if not task:
        return
    auto, _reasons = _auto_rag(db, task)
    # RAG is a management judgement. Date/blocker calculations remain warnings
    # and must not silently overwrite the user's existing RAG decision.
    final = task["manual_rag"] or task["final_rag"]
    db.execute("UPDATE major_tasks SET auto_rag=?,final_rag=? WHERE id=?", (auto, final, task_id))


def refresh_major_task_rags(db):
    """Refresh warning severity without silently changing the management RAG."""
    changed = 0
    for row in db.execute(
        "SELECT id FROM major_tasks WHERE status NOT IN ('completed','cancelled') AND archived_at IS NULL"
    ).fetchall():
        task = _task_row(db, row["id"])
        auto, _reasons = _auto_rag(db, task)
        final = task["manual_rag"] or task["final_rag"]
        if auto == task["auto_rag"] and final == task["final_rag"]:
            continue
        now = _now()
        before = {"auto_rag": task["auto_rag"], "final_rag": task["final_rag"]}
        after = {"auto_rag": auto, "final_rag": final}
        db.execute("UPDATE major_tasks SET auto_rag=?,final_rag=? WHERE id=?", (auto, final, task["id"]))
        db.execute(
            """INSERT INTO audit_logs
               (occurred_at,actor_user_id,actor_username,action,entity_type,entity_id,summary,before_json,after_json)
               VALUES (?,NULL,'system','MAJOR_TASK_AUTO_RAG_UPDATE','major_task',?,?,?,?)""",
            (now,task["id"],f"{task['title']} 자동 RAG 재판정",_json(before),_json(after)),
        )
        changed += 1
    return changed


def _current_balls(db, task_id):
    return db.execute(
        """SELECT b.* FROM major_task_balls b
           WHERE b.task_id=? AND b.is_active=1 AND b.resolved_at IS NULL
             AND (b.action_id IS NOT NULL OR b.milestone_id IS NULL OR b.represents_whole_milestone=1
               OR NOT EXISTS (SELECT 1 FROM major_task_actions a
                              WHERE a.milestone_id=b.milestone_id AND a.is_active=1))
           ORDER BY COALESCE(b.follow_up_date,'9999-12-31'),b.created_at""",
        (task_id,),
    ).fetchall()


def _progress(db, task_id):
    milestones = db.execute(
        "SELECT * FROM major_task_milestones WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at",
        (task_id,),
    ).fetchall()
    if not milestones:
        return None, []
    details = []
    required_progress = []
    for milestone in milestones:
        actions = db.execute(
            "SELECT * FROM major_task_actions WHERE milestone_id=? AND is_active=1 ORDER BY display_order,created_at",
            (milestone["id"],),
        ).fetchall()
        included = [a for a in actions if a["is_required"] or a["include_in_progress"]]
        if included:
            pct = round(sum(1 for a in included if a["status"] == "completed") / len(included) * 100)
        elif milestone["status"] == "completed":
            pct = 100
        elif milestone["status"] == "not_started":
            pct = 0
        else:
            pct = None
        details.append({"id": milestone["id"], "name": milestone["name"], "status": milestone["status"], "progress": pct})
        if milestone["is_required"] and pct is not None:
            required_progress.append(pct)
    overall = round(sum(required_progress) / len(required_progress)) if required_progress else None
    return overall, details


def _ball_summary(db, task_id):
    balls = _current_balls(db, task_id)
    counts = {"internal": 0, "external": 0, "follow_up_due": 0}
    today = _today().isoformat()
    urgent = None
    for ball in balls:
        canonical_type = BALL_CANONICAL_TYPES.get(ball["owner_type"], "external")
        external = canonical_type in {"customer", "external"}
        counts["external" if external else "internal"] += int(canonical_type != "none")
        if external and ball["follow_up_date"] and ball["follow_up_date"] <= today:
            counts["follow_up_due"] += 1
        due = ball["follow_up_date"] or ball["resolution_due_date"] or "9999-12-31"
        if urgent is None or due < urgent[0]:
            urgent = (due, ball)
    return {
        **counts,
        "total": counts["internal"] + counts["external"],
        "urgent": ({
            "owner": urgent[1]["owner_detail"],
            "request": urgent[1]["request_text"],
            "date": urgent[0],
            "type": BALL_CANONICAL_TYPES.get(urgent[1]["owner_type"], "external"),
        } if urgent else None),
    }


def _current_action_summary(db, task):
    if task["next_action"]:
        return {
            "text": task["next_action"],
            "owner_id": task["owner_id"],
            "owner_name": task["owner_name"],
            "due_date": task["next_action_date"],
            "source": "task",
        }
    row = db.execute(
        """SELECT a.id,a.name,a.next_action,a.owner_id,a.due_date,u.display_name AS owner_name
           FROM major_task_actions a
           LEFT JOIN users u ON u.id=a.owner_id
           WHERE a.task_id=? AND a.is_active=1
             AND a.status NOT IN ('completed','cancelled')
           ORDER BY CASE a.status WHEN 'in_progress' THEN 0 WHEN 'waiting' THEN 1 ELSE 2 END,
                    COALESCE(a.due_date,'9999-12-31'),a.display_order,a.created_at
           LIMIT 1""",
        (task["id"],),
    ).fetchone()
    if not row:
        return {"text": "", "owner_id": None, "owner_name": "", "due_date": None, "source": "none"}
    return {
        "text": row["next_action"] or row["name"],
        "owner_id": row["owner_id"],
        "owner_name": row["owner_name"],
        "due_date": row["due_date"],
        "source": "action",
        "action_id": row["id"],
    }


def _parent_summary(db, task_id):
    direct_rows = db.execute(
        """SELECT id,status,final_rag,blocker_active,next_action_date,current_target_date,
                  hard_deadline_enabled,hard_deadline_date
           FROM major_tasks WHERE parent_task_id=?""",
        (task_id,),
    ).fetchall()
    rows = []
    seen = {task_id}
    stack = list(direct_rows)
    while stack:
        row = stack.pop(0)
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        rows.append(row)
        stack.extend(db.execute(
            """SELECT id,status,final_rag,blocker_active,next_action_date,current_target_date,
                      hard_deadline_enabled,hard_deadline_date
               FROM major_tasks WHERE parent_task_id=?""",
            (row["id"],),
        ).fetchall())
    today = _today()
    week_start, week_end = _week_bounds(today)

    def due(row):
        return row["next_action_date"] or (
            row["hard_deadline_date"] if row["hard_deadline_enabled"] and row["hard_deadline_date"]
            else row["current_target_date"]
        )

    return {
        "children": len(direct_rows),
        "direct_children": len(direct_rows),
        "descendants": len(rows),
        "active": sum(row["status"] not in {"completed", "cancelled"} for row in rows),
        "completed": sum(row["status"] == "completed" for row in rows),
        "green": sum(row["final_rag"] == "green" for row in rows),
        "amber": sum(row["final_rag"] == "amber" for row in rows),
        "red": sum(row["final_rag"] == "red" for row in rows),
        "blocked": sum(bool(row["blocker_active"]) for row in rows),
        "overdue": sum(bool(due(row) and due(row) < today.isoformat() and row["status"] not in {"completed", "cancelled"}) for row in rows),
        "due_this_week": sum(bool(due(row) and week_start.isoformat() <= due(row) <= week_end.isoformat() and row["status"] not in {"completed", "cancelled"}) for row in rows),
    }


def _serialize_stage(row, current_stage_id=None, db=None):
    stage = dict(row)
    stage["is_current"] = stage["id"] == current_stage_id
    stage["is_overdue"] = bool(
        stage.get("is_active")
        and stage.get("target_date")
        and not stage.get("completed_at")
        and stage["target_date"] < _today().isoformat()
    )
    if db is not None:
        stage["assignee_ids"] = _stage_assignee_ids(db, stage)
        stage["assignees"] = _named_users(db, stage["assignee_ids"])
    return stage


def _serialize_task(db, row, include_permissions=False, user=None, include_relations=False):
    item = dict(row)
    root_section = _root_section(db, row["id"])
    item["root_task_id"] = root_section["root_task_id"]
    item["root_section_id"] = root_section["section_id"]
    item["root_section_name"] = root_section["section_name"]
    item["root_section_active"] = root_section["section_active"]
    item["section_is_inherited"] = bool(row["parent_task_id"])
    active_stages = [
        _serialize_stage(stage, row["current_stage_id"], db)
        for stage in db.execute(
        """SELECT id,name,display_order,status,owner_id,target_date,started_at,completed_at,is_active
           FROM major_task_stages
           WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at""",
        (row["id"],),
    )]
    active_stage_ids = [stage["id"] for stage in active_stages]
    item["stage_pipeline"] = active_stages
    item["stage_count"] = len(active_stages)
    item["current_stage_position"] = (
        active_stage_ids.index(row["current_stage_id"]) + 1
        if row["current_stage_id"] in active_stage_ids else None
    )
    item["stage_overdue_count"] = sum(stage["is_overdue"] for stage in active_stages)
    item["owners"] = _task_owner_people(db, row)
    item["additional_owners"] = [person for person in item["owners"] if not person["is_primary"]]
    item["owner_count"] = len(item["owners"])
    item["owner_display"] = (
        f"{row['owner_name']} +{len(item['additional_owners'])}"
        if row["owner_name"] and item["additional_owners"] else row["owner_name"] or ""
    )
    item["hierarchy_path"] = _task_path(db, row["id"])
    item["hierarchy_depth"] = len(item["hierarchy_path"])
    item["progress"], item["milestones_summary"] = _progress(db, row["id"])
    item["ball_summary"] = _ball_summary(db, row["id"])
    item["effective_deadline"] = _task_due(row)
    item["current_action"] = _current_action_summary(db, row)
    item["operational_due"] = item["current_action"]["due_date"] or item["effective_deadline"]
    item["parent_summary"] = _parent_summary(db, row["id"])
    item["effective_review_cycle_days"] = row["review_cycle_days_override"] if row["review_cycle_days_override"] is not None else row["workstream_review_cycle_days"]
    item["effective_due_soon_days"] = row["due_soon_days_override"] if row["due_soon_days_override"] is not None else (row["workstream_due_soon_days"] if row["workstream_due_soon_days"] is not None else 3)
    item["effective_hard_deadline_soon_days"] = row["hard_deadline_soon_days_override"] if row["hard_deadline_soon_days_override"] is not None else (row["workstream_hard_deadline_soon_days"] if row["workstream_hard_deadline_soon_days"] is not None else 7)
    item["schedule_variance_days"] = (
        (date.fromisoformat(row["actual_completion_date"]) - date.fromisoformat(row["original_target_date"])).days
        if row["actual_completion_date"] and row["original_target_date"] else None
    )
    if include_relations:
        item["business_links"] = [dict(value) for value in db.execute(
            """SELECT business_unit,business_subcategory,is_primary
               FROM major_task_business_links WHERE task_id=?
               ORDER BY is_primary DESC,created_at,business_unit,business_subcategory""",
            (row["id"],),
        )]
        item["participants"] = [dict(value) for value in db.execute(
            """SELECT p.user_id,p.relation_type,u.display_name FROM major_task_people p
               JOIN users u ON u.id=p.user_id WHERE p.task_id=? ORDER BY p.relation_type,u.display_name""",
            (row["id"],),
        )]
        item["products"] = [dict(value) for value in db.execute(
            "SELECT id,product_code,product_name,source_type FROM major_task_products WHERE task_id=? ORDER BY product_name,product_code",
            (row["id"],),
        )]
    _auto, reasons = _auto_rag(db, row)
    item["warning_rag"] = _auto
    item["risk_warnings"] = reasons
    item["rag_reasons"] = reasons
    item["is_overdue"] = bool(item["operational_due"] and item["operational_due"] < _today().isoformat() and row["status"] not in {"completed", "cancelled"})
    if include_permissions and user:
        item["permissions"] = {
            "structure": _can_structure(db, row, user),
            "progress": _can_progress(db, row, user),
            "task_ball": _can_structure(db, row, user),
            "attachment": _can_structure(db, row, user),
            "manage": user["role"] in MANAGE_ROLES,
        }
    return item


def _list_where(args, current_user_id=None):
    clauses = ["1=1"]
    params = []
    archive = args.get("archive") == "1"
    clauses.append(
        "(t.status IN ('completed','cancelled') OR t.archived_at IS NOT NULL)"
        if archive else
        "(t.status NOT IN ('completed','cancelled') AND t.archived_at IS NULL)"
    )
    search = _clean(args.get("search"), 200)
    if search:
        clauses.append("(t.title LIKE ? OR t.country LIKE ? OR t.legacy_customer_name LIKE ? OR t.next_action LIKE ?)")
        params.extend([f"%{search}%"] * 4)
    values = {
        "status": "t.status", "workstream": "t.workstream_id",
        "country": "t.country", "customer": "t.customer_master_id", "rag": "t.final_rag",
    }
    for key, column in values.items():
        selected = [part for part in _clean(args.get(key), 500).split(",") if part]
        if selected:
            clauses.append(f"{column} IN ({','.join('?' for _ in selected)})")
            params.extend(selected)
    section = _clean(args.get("section"), 64)
    if section:
        section_clause = "r.section_id IS NULL" if section == "__unassigned__" else "r.section_id=?"
        clauses.append(
            f"""t.id IN (
                 WITH RECURSIVE section_tree(id) AS (
                   SELECT r.id FROM major_tasks r
                   WHERE r.parent_task_id IS NULL AND {section_clause}
                   UNION ALL
                   SELECT child.id FROM major_tasks child
                   JOIN section_tree parent ON child.parent_task_id=parent.id
                 )
                 SELECT id FROM section_tree
               )"""
        )
        if section != "__unassigned__":
            params.append(section)
    owners = [part for part in _clean(args.get("owner"), 500).split(",") if part]
    if owners:
        marks = ",".join("?" for _ in owners)
        clauses.append(
            f"(t.owner_id IN ({marks}) OR t.deputy_owner_id IN ({marks}) OR "
            f"EXISTS (SELECT 1 FROM major_task_assignees oa WHERE oa.task_id=t.id "
            f"AND oa.user_id IN ({marks})))"
        )
        params.extend(owners * 3)
    units = [part for part in _clean(args.get("business"), 300).split(",") if part]
    subs = [part for part in _clean(args.get("subcategory"), 300).split(",") if part]
    if units:
        clauses.append(
            f"EXISTS (SELECT 1 FROM major_task_business_links bl WHERE bl.task_id=t.id AND bl.business_unit IN ({','.join('?' for _ in units)}))"
        )
        params.extend(units)
    if subs:
        clauses.append(
            f"EXISTS (SELECT 1 FROM major_task_business_links bl WHERE bl.task_id=t.id AND bl.business_subcategory IN ({','.join('?' for _ in subs)}))"
        )
        params.extend(subs)
    if args.get("directive") == "1":
        clauses.append("t.ceo_directive=1")
    if args.get("blocker") == "1":
        clauses.append("t.blocker_active=1")
    if args.get("mine") == "1" and current_user_id is not None:
        clauses.append(
            "(t.owner_id=? OR t.deputy_owner_id=? OR EXISTS ("
            "SELECT 1 FROM major_task_assignees oa WHERE oa.task_id=t.id AND oa.user_id=?))"
        )
        params.extend((current_user_id, current_user_id, current_user_id))
    parent_filter = _clean(args.get("parent"), 64)
    if parent_filter:
        clauses.append("t.parent_task_id=?")
        params.append(parent_filter)
    hierarchy = _clean(args.get("hierarchy"), 20)
    if hierarchy == "root":
        clauses.append("t.parent_task_id IS NULL")
    elif hierarchy == "child":
        clauses.append("t.parent_task_id IS NOT NULL")
    if args.get("decision") == "1":
        clauses.append("EXISTS (SELECT 1 FROM major_task_progress_updates p WHERE p.task_id=t.id AND p.is_current=1 AND p.decision_needed<>'')")
    ball_filter = _clean(args.get("ball"), 20)
    if ball_filter == "internal":
        clauses.append("EXISTS (SELECT 1 FROM major_task_balls b WHERE b.task_id=t.id AND b.is_active=1 AND b.resolved_at IS NULL AND b.owner_type IN ('internal','executive','department'))")
    elif ball_filter == "customer":
        clauses.append("EXISTS (SELECT 1 FROM major_task_balls b WHERE b.task_id=t.id AND b.is_active=1 AND b.resolved_at IS NULL AND b.owner_type='buyer')")
    elif ball_filter == "external":
        clauses.append("EXISTS (SELECT 1 FROM major_task_balls b WHERE b.task_id=t.id AND b.is_active=1 AND b.resolved_at IS NULL AND b.owner_type IN ('external_agency','logistics'))")
    elif ball_filter == "none":
        clauses.append("NOT EXISTS (SELECT 1 FROM major_task_balls b WHERE b.task_id=t.id AND b.is_active=1 AND b.resolved_at IS NULL AND b.owner_type<>'none')")
    if args.get("followup") == "1":
        clauses.append("EXISTS (SELECT 1 FROM major_task_balls b WHERE b.task_id=t.id AND b.is_active=1 AND b.resolved_at IS NULL AND b.owner_type IN ('buyer','external_agency','logistics') AND b.follow_up_date<=?)")
        params.append(_today().isoformat())
    if args.get("overdue") == "1":
        clauses.append("COALESCE(t.next_action_date,CASE WHEN t.hard_deadline_enabled=1 THEN t.hard_deadline_date END,t.current_target_date)<?")
        params.append(_today().isoformat())
    if args.get("week_due") == "1":
        week_start, week_end = _week_bounds()
        clauses.append("COALESCE(t.next_action_date,CASE WHEN t.hard_deadline_enabled=1 THEN t.hard_deadline_date END,t.current_target_date) BETWEEN ? AND ?")
        params.extend((week_start.isoformat(), week_end.isoformat()))
    return " AND ".join(clauses), params


def list_task_rows(db, args, current_user_id=None):
    if refresh_major_task_rags(db):
        db.commit()
    where, params = _list_where(args, current_user_id)
    order_map = {
        "updated": "t.recent_updated_at DESC", "deadline": "COALESCE(t.next_action_date,t.hard_deadline_date,t.current_target_date,'9999-12-31')",
        "title": "t.title COLLATE NOCASE", "rag": "CASE t.final_rag WHEN 'red' THEN 0 WHEN 'amber' THEN 1 ELSE 2 END",
    }
    order = order_map.get(args.get("sort"), order_map["rag"] + ",COALESCE(t.next_action_date,t.hard_deadline_date,t.current_target_date,'9999-12-31')")
    return db.execute(
        """SELECT t.*,w.name AS workstream_name,w.color AS workstream_color,
                  w.review_cycle_days AS workstream_review_cycle_days,
                  w.due_soon_days AS workstream_due_soon_days,
                  w.hard_deadline_soon_days AS workstream_hard_deadline_soon_days,
                  o.display_name AS owner_name,d.display_name AS deputy_owner_name,
                  c.display_name AS customer_name,
                  sec.name AS section_name,sec.is_active AS section_active,
                  p.title AS parent_title,
                  s.name AS current_stage_name,s.status AS current_stage_status,
                  bo.display_name AS blocker_owner_name,
                  du.display_name AS directed_by_name
           FROM major_tasks t
           LEFT JOIN major_task_workstreams w ON w.id=t.workstream_id
           LEFT JOIN users o ON o.id=t.owner_id LEFT JOIN users d ON d.id=t.deputy_owner_id
           LEFT JOIN customer_master c ON c.id=t.customer_master_id
           LEFT JOIN major_task_sections sec ON sec.id=t.section_id
           LEFT JOIN major_tasks p ON p.id=t.parent_task_id
           LEFT JOIN major_task_stages s ON s.id=t.current_stage_id AND s.task_id=t.id
           LEFT JOIN users bo ON bo.id=t.blocker_owner_id
           LEFT JOIN users du ON du.id=t.directed_by_user_id
           WHERE """ + where + " ORDER BY " + order,
        params,
    ).fetchall()


def _summaries(db, rows, current_user_id=None):
    today = _today()
    week_start, week_end = _week_bounds(today)
    ids = [row["id"] for row in rows]
    ball_counts = {"internal": 0, "external": 0, "follow_up": 0}
    decision = 0
    for row in rows:
        balls = _ball_summary(db, row["id"])
        ball_counts["internal"] += balls["internal"]
        ball_counts["external"] += balls["external"]
        ball_counts["follow_up"] += balls["follow_up_due"]
        if db.execute(
            "SELECT 1 FROM major_task_progress_updates WHERE task_id=? AND is_current=1 AND decision_needed<>'' LIMIT 1", (row["id"],)
        ).fetchone():
            decision += 1
    def count(fn):
        return sum(1 for row in rows if fn(row))
    def operational_due(row):
        return row["next_action_date"] or _task_due(row)
    return {
        "total": len(rows),
        "mine": count(lambda r: current_user_id is not None and (
            current_user_id in {r["owner_id"], r["deputy_owner_id"]}
            or db.execute(
                "SELECT 1 FROM major_task_assignees WHERE task_id=? AND user_id=? LIMIT 1",
                (r["id"], current_user_id),
            ).fetchone() is not None
        )),
        "directive": count(lambda r: bool(r["ceo_directive"])),
        "internal_ball": ball_counts["internal"], "external_wait": ball_counts["external"],
        "follow_up_due": ball_counts["follow_up"],
        "red": count(lambda r: r["final_rag"] == "red"), "amber": count(lambda r: r["final_rag"] == "amber"),
        "blocked": count(lambda r: bool(r["blocker_active"])),
        "overdue": count(lambda r: bool(operational_due(r) and operational_due(r) < today.isoformat())),
        "week_due": count(lambda r: bool(operational_due(r) and week_start.isoformat() <= operational_due(r) <= week_end.isoformat())),
        "decision_needed": decision,
        "task_ids": ids,
    }


def major_task_dashboard_snapshot(db):
    try:
        rows = list_task_rows(db, {})
    except sqlite3.OperationalError:
        return {"total": 0, "done": 0, "overdue": 0, "major_tasks": [], "brief": []}
    completed = db.execute("SELECT COUNT(*) AS count FROM major_tasks WHERE status='completed'").fetchone()["count"]
    all_count = db.execute(
        "SELECT COUNT(*) AS count FROM major_tasks WHERE status<>'cancelled' AND (archived_at IS NULL OR status='completed')"
    ).fetchone()["count"]
    all_serialized = [_serialize_task(db, row) for row in rows]
    serialized = all_serialized[:12]
    today = _today().isoformat()
    brief = []
    for item in all_serialized:
        deadline = item["effective_deadline"]
        if item["final_rag"] in {"red", "amber"} or (deadline and deadline <= today) or item["ball_summary"]["follow_up_due"]:
            brief.append(item)
    return {
        "total": all_count, "done": completed,
        "overdue": sum(1 for item in all_serialized if item["is_overdue"]),
        "major_tasks": serialized, "brief": brief[:12],
    }


def major_tasks_for_country(db, country=None, customer_ids=()):
    clauses = ["t.status NOT IN ('completed','cancelled')", "t.archived_at IS NULL"]
    params = []
    if customer_ids:
        clauses.append(f"t.customer_master_id IN ({','.join('?' for _ in customer_ids)})")
        params.extend(customer_ids)
    elif country:
        clauses.append("t.country=?")
        params.append(country)
    else:
        return []
    return [dict(row) for row in db.execute(
        """SELECT t.id,t.title,t.status,t.current_target_date AS due_date,t.country,
                  u.display_name AS owner_name,t.final_rag
           FROM major_tasks t LEFT JOIN users u ON u.id=t.owner_id WHERE """ + " AND ".join(clauses), params
    )]


def _validate_task_input(db, data, existing=None):
    legacy = bool(existing and existing["legacy_record_id"])
    title = _clean(data.get("title", existing["title"] if existing else ""), 200)
    if not title:
        raise ValueError("주요업무명을 입력하세요.")
    unified_links = _normalized_business_links(db, data, existing)
    if unified_links is not None:
        primary_link = next(link for link in unified_links if link["is_primary"])
        unit, sub = primary_link["business_unit"], primary_link["business_subcategory"]
    else:
        raw_unit = data.get("primary_business_unit", existing["primary_business_unit"] if existing else "")
        raw_sub = data.get("primary_business_subcategory", existing["primary_business_subcategory"] if existing else "")
        try:
            unit, sub = _business_values(raw_unit, raw_sub, legacy=legacy)
        except ValueError:
            if not existing or (
                _clean(raw_unit, 40), _clean(raw_sub, 60)
            ) != (existing["primary_business_unit"], existing["primary_business_subcategory"]):
                raise
            unit, sub = existing["primary_business_unit"], existing["primary_business_subcategory"]
    owner_id = _int(data.get(
        "primary_owner_id",
        data.get("owner_id", existing["owner_id"] if existing else None),
    ))
    explicit_additional = "additional_owner_ids" in data
    additional_owner_ids = _normalized_user_ids(
        db, data.get("additional_owner_ids"), "공동 담당자"
    ) if explicit_additional else None
    if additional_owner_ids is not None and owner_id in additional_owner_ids:
        raise ValueError("대표 책임자를 공동 담당자에 중복 지정할 수 없습니다.")
    deputy = (
        additional_owner_ids[0] if additional_owner_ids
        else None if explicit_additional
        else _int(data.get("deputy_owner_id", existing["deputy_owner_id"] if existing else None))
    )
    if not _user_exists(db, owner_id) or not _user_exists(db, deputy):
        raise ValueError("담당자를 찾을 수 없습니다.")
    status = _clean(data.get("status", existing["status"] if existing else "not_started"), 40)
    if status not in TASK_STATUSES:
        raise ValueError("진행상태가 올바르지 않습니다.")
    if existing and existing["status"] in {"completed", "cancelled"} and status != existing["status"]:
        raise ValueError("완료·취소 상태 변경은 상세화면의 전용 처리 기능을 사용하세요.")
    if status in {"completed", "cancelled"} and (not existing or status != existing["status"]):
        raise ValueError("완료·취소는 상세화면의 전용 처리 기능을 사용하세요.")
    original = _date(data.get("original_target_date", existing["original_target_date"] if existing else None), "최초 목표완료일")
    current = _date(data.get("current_target_date", existing["current_target_date"] if existing else original), "현재 목표완료일")
    if existing and existing["original_target_date"] is not None and original != existing["original_target_date"]:
        raise ValueError("최초 목표완료일은 최초 저장 후 변경할 수 없습니다.")
    reason = _clean(data.get("target_change_reason", existing["target_change_reason"] if existing else ""), 500)
    if existing and current != existing["current_target_date"] and not reason:
        raise ValueError("목표완료일 변경사유를 입력하세요.")
    hard = _bool(data.get("hard_deadline_enabled", existing["hard_deadline_enabled"] if existing else False))
    hard_date = _date(data.get("hard_deadline_date", existing["hard_deadline_date"] if existing else None), "Hard Deadline")
    if hard and not hard_date:
        raise ValueError("Hard Deadline 날짜를 입력하세요.")
    if not hard:
        hard_date = None
    review_cycle_days = _optional_days(
        data.get("review_cycle_days_override", existing["review_cycle_days_override"] if existing else None),
        "개별 점검주기",
    )
    due_soon_days = _optional_days(
        data.get("due_soon_days_override", existing["due_soon_days_override"] if existing else None),
        "일반기한 임박기준",
    )
    hard_due_soon_days = _optional_days(
        data.get("hard_deadline_soon_days_override", existing["hard_deadline_soon_days_override"] if existing else None),
        "Hard Deadline 임박기준",
    )
    directive = _bool(data.get("ceo_directive", existing["ceo_directive"] if existing else False))
    directive_date = _date(data.get("directive_date", existing["directive_date"] if existing else None), "지시일")
    directive_type = _clean(data.get("directive_type", existing["directive_type"] if existing else ""), 30) or ("ceo" if directive else None)
    directed_by_user_id = _int(data.get("directed_by_user_id", existing["directed_by_user_id"] if existing else None))
    directive_note = _clean(data.get("directive_note", existing["directive_note"] if existing else ""), 1000)
    if directive and not directive_date:
        raise ValueError("지시일을 입력하세요.")
    if directive and directive_type not in DIRECTIVE_TYPES:
        raise ValueError("지시 구분이 올바르지 않습니다.")
    if not _user_exists(db, directed_by_user_id):
        raise ValueError("지시자를 찾을 수 없습니다.")
    if not directive:
        directive_date = None
        directive_type = None
        directed_by_user_id = None
        directive_note = ""
    next_action = _clean(data.get("next_action", existing["next_action"] if existing else ""), 1000)
    next_action_date = _date(data.get("next_action_date", existing["next_action_date"] if existing else None), "다음 액션 기한")
    next_check = _date(data.get("next_check_date", existing["next_check_date"] if existing else None), "다음 확인일")
    cooperation_department = _clean(data.get("cooperation_department", existing["cooperation_department"] if existing else ""), 200)
    cooperation_request = _clean(data.get("cooperation_request", existing["cooperation_request"] if existing else ""), 1000)
    hold_reason = _clean(data.get("hold_reason", existing["hold_reason"] if existing else ""), 1000)
    review_date = _date(data.get("review_date", existing["review_date"] if existing else None), "재검토일")
    final_result = _clean(data.get("final_result", existing["final_result"] if existing else ""), 3000)
    actual_completion = _date(data.get("actual_completion_date", existing["actual_completion_date"] if existing else None), "실제 완료일")
    cancel_reason = _clean(data.get("cancel_reason", existing["cancel_reason"] if existing else ""), 1000)
    if status == "internal_work" and (not next_action or not next_action_date):
        raise ValueError("내부작업은 다음 액션과 기한이 필요합니다.")
    if status == "external_wait":
        if not existing:
            raise ValueError("외부대기는 업무 저장 후 Ball 소유자와 Follow-up Date를 먼저 등록하세요.")
        has_external_ball = db.execute(
            """SELECT 1 FROM major_task_balls
               WHERE task_id=? AND is_active=1 AND resolved_at IS NULL
                 AND owner_type IN ('buyer','external_agency','logistics')
                 AND follow_up_date IS NOT NULL LIMIT 1""",
            (existing["id"],),
        ).fetchone()
        if not has_external_ball:
            raise ValueError("외부대기는 활성 Ball 소유자와 Follow-up Date를 먼저 등록하세요.")
    if status == "cooperation_wait" and (not cooperation_department or not cooperation_request or not next_check):
        raise ValueError("협조대기는 협조부서·요청내용·확인일이 필요합니다.")
    if status == "hold" and (not hold_reason or not review_date):
        raise ValueError("보류 사유와 재검토일을 입력하세요.")
    if status == "completed" and (not existing or existing["status"] != "completed") and (not final_result or not actual_completion):
        raise ValueError("완료 결과와 실제 완료일을 입력하세요.")
    if status == "cancelled" and (not existing or existing["status"] != "cancelled") and not cancel_reason:
        raise ValueError("취소 사유를 입력하세요.")
    manual_rag = data.get("manual_rag", existing["manual_rag"] if existing else None) or None
    manual_rag = _clean(manual_rag, 10) or None
    manual_reason = _clean(data.get("manual_rag_reason", existing["manual_rag_reason"] if existing else ""), 500)
    if manual_rag and manual_rag not in RAG_SCORE:
        raise ValueError("수동 RAG가 올바르지 않습니다.")
    if manual_rag and not manual_reason:
        raise ValueError("수동 RAG 변경 사유를 입력하세요.")
    workstream_id = _clean(data.get("workstream_id", existing["workstream_id"] if existing else ""), 32) or None
    if workstream_id and not db.execute("SELECT 1 FROM major_task_workstreams WHERE id=?", (workstream_id,)).fetchone():
        raise ValueError("워크스트림을 찾을 수 없습니다.")
    customer_id = _clean(data.get("customer_master_id", existing["customer_master_id"] if existing else ""), 64) or None
    if customer_id and not db.execute("SELECT 1 FROM customer_master WHERE id=?", (customer_id,)).fetchone():
        raise ValueError("거래처 마스터를 찾을 수 없습니다.")
    parent_task_id = _clean(data.get("parent_task_id", existing["parent_task_id"] if existing else ""), 64) or None
    task_id = existing["id"] if existing else None
    parent_row = db.execute(
        "SELECT id,status,archived_at FROM major_tasks WHERE id=?", (parent_task_id,)
    ).fetchone() if parent_task_id else None
    if parent_task_id and not parent_row:
        raise ValueError("상위 업무를 찾을 수 없습니다.")
    parent_changed = not existing or parent_task_id != existing["parent_task_id"]
    if parent_row and parent_changed and (
        parent_row["status"] == "cancelled" or parent_row["archived_at"] is not None
    ):
        raise ValueError("취소·아카이브된 업무는 상위 업무로 지정할 수 없습니다.")
    if _task_parent_cycle(db, task_id, parent_task_id):
        raise ValueError("상위·하위 업무 관계가 순환합니다.")
    if parent_task_id and parent_changed:
        parent_depth = _task_depth(db, parent_task_id)
        subtree_height = _task_subtree_height(db, task_id) if task_id else 1
        if parent_depth is None:
            raise ValueError("상위 업무 계층을 확인할 수 없습니다.")
        if parent_depth + subtree_height > MAX_UI_HIERARCHY_DEPTH:
            raise ValueError(f"현재 UI에서는 업무 계층을 {MAX_UI_HIERARCHY_DEPTH}단계까지 구성할 수 있습니다.")
    section_id = _clean(
        data.get("section_id", existing["section_id"] if existing else ""), 32
    ) or None
    if parent_task_id:
        # Section groups complete trees. Descendants keep no independent
        # grouping relation and are rendered under the root Task's Section.
        section_id = None
    elif section_id:
        section = db.execute(
            "SELECT id,is_active FROM major_task_sections WHERE id=?", (section_id,)
        ).fetchone()
        if not section:
            raise ValueError("Section을 찾을 수 없습니다.")
        if not section["is_active"] and (not existing or existing["section_id"] != section_id):
            raise ValueError("비활성 Section은 새로 선택할 수 없습니다.")
    blocker_active = _bool(data.get("blocker_active", existing["blocker_active"] if existing else False))
    blocker_category = _clean(data.get("blocker_category", existing["blocker_category"] if existing else ""), 30) or None
    blocker_description = _clean(data.get("blocker_description", existing["blocker_description"] if existing else ""), 2000)
    blocker_owner_id = _int(data.get("blocker_owner_id", existing["blocker_owner_id"] if existing else None))
    blocker_since = _date(data.get("blocker_since", existing["blocker_since"] if existing else None), "Blocker 시작일")
    blocker_resolved_at = _date(data.get("blocker_resolved_at", existing["blocker_resolved_at"] if existing else None), "Blocker 해결일")
    if not _user_exists(db, blocker_owner_id):
        raise ValueError("Blocker 담당자를 찾을 수 없습니다.")
    if blocker_active:
        if blocker_category not in BLOCKER_CATEGORIES or not blocker_description:
            raise ValueError("Blocker 구분과 내용을 입력하세요.")
        blocker_since = blocker_since or _today().isoformat()
        blocker_resolved_at = None
    elif existing and existing["blocker_active"] and not blocker_resolved_at:
        blocker_resolved_at = _today().isoformat()
    values = {
        "title": title, "primary_business_unit": unit, "primary_business_subcategory": sub,
        "workstream_id": workstream_id, "parent_task_id": parent_task_id,
        "section_id": section_id,
        "region": _clean(data.get("region", existing["region"] if existing else ""), 80),
        "country": _clean(data.get("country", existing["country"] if existing else ""), 80),
        "customer_master_id": customer_id,
        "legacy_customer_name": _clean(data.get("legacy_customer_name", existing["legacy_customer_name"] if existing else ""), 200),
        "customer_link_status": "linked" if customer_id else _clean(data.get("customer_link_status", existing["customer_link_status"] if existing else "unlinked"), 40),
        "product_name": _clean(data.get("product_name", existing["product_name"] if existing else ""), 300),
        "product_code": _clean(data.get("product_code", existing["product_code"] if existing else ""), 100),
        "purpose": _clean(data.get("purpose", existing["purpose"] if existing else ""), 3000),
        "completion_criteria": _clean(data.get("completion_criteria", existing["completion_criteria"] if existing else ""), 3000),
        "owner_id": owner_id, "deputy_owner_id": deputy,
        "importance": _clean(data.get("importance", existing["importance"] if existing else "medium"), 10),
        "start_date": _date(data.get("start_date", existing["start_date"] if existing else None), "시작일"),
        "original_target_date": original, "current_target_date": current, "target_change_reason": reason,
        "hard_deadline_enabled": hard, "hard_deadline_date": hard_date,
        "review_cycle_days_override": review_cycle_days,
        "due_soon_days_override": due_soon_days,
        "hard_deadline_soon_days_override": hard_due_soon_days,
        "status": status,
        "manual_rag": manual_rag, "manual_rag_reason": manual_reason,
        "next_action": next_action, "next_action_date": next_action_date, "next_check_date": next_check,
        "cooperation_department": cooperation_department, "cooperation_request": cooperation_request,
        "hold_reason": hold_reason, "review_date": review_date, "final_result": final_result,
        "final_deliverable": _clean(data.get("final_deliverable", existing["final_deliverable"] if existing else ""), 3000),
        "actual_completion_date": actual_completion,
        "major_risks": _clean(data.get("major_risks", existing["major_risks"] if existing else ""), 3000),
        "resolution": _clean(data.get("resolution", existing["resolution"] if existing else ""), 3000),
        "future_notes": _clean(data.get("future_notes", existing["future_notes"] if existing else ""), 3000),
        "final_report": _clean(data.get("final_report", existing["final_report"] if existing else ""), 3000),
        "cancel_reason": cancel_reason, "ceo_directive": directive, "directive_date": directive_date,
        "directive_type": directive_type, "directed_by_user_id": directed_by_user_id,
        "directive_note": directive_note,
        "blocker_active": blocker_active, "blocker_category": blocker_category,
        "blocker_description": blocker_description, "blocker_owner_id": blocker_owner_id,
        "blocker_since": blocker_since, "blocker_resolved_at": blocker_resolved_at,
        "notes": _clean(data.get("notes", existing["notes"] if existing else ""), 3000),
    }
    if values["importance"] not in {"high", "medium", "low"}:
        raise ValueError("중요도가 올바르지 않습니다.")
    return values


def _validate_stage_input(db, data, existing=None):
    name = _clean(data.get("name", existing["name"] if existing else ""), 200)
    if not name:
        raise ValueError("Stage 이름을 입력하세요.")
    status = _clean(data.get("status", existing["status"] if existing else "planned"), 20)
    if status not in STAGE_STATUSES:
        raise ValueError("Stage 상태가 올바르지 않습니다.")
    assignee_ids = _normalized_user_ids(
        db, data.get("assignee_ids"), "Stage 담당자"
    ) if "assignee_ids" in data else None
    owner_id = (
        assignee_ids[0] if assignee_ids
        else None if assignee_ids == []
        else _int(data.get("owner_id", existing["owner_id"] if existing else None))
    )
    if not _user_exists(db, owner_id):
        raise ValueError("Stage 담당자를 찾을 수 없습니다.")
    started_at = _date(data.get("started_at", existing["started_at"] if existing else None), "Stage 시작일")
    completed_at = _date(data.get("completed_at", existing["completed_at"] if existing else None), "Stage 완료일")
    if status == "active":
        started_at = started_at or _today().isoformat()
        completed_at = None
    if status == "completed":
        completed_at = completed_at or _today().isoformat()
    return {
        "name": name,
        "display_order": _int(data.get("display_order", existing["display_order"] if existing else 0), 0),
        "status": status,
        "owner_id": owner_id,
        "target_date": _date(data.get("target_date", existing["target_date"] if existing else None), "Stage 목표일"),
        "started_at": started_at,
        "completed_at": completed_at,
        "note": _clean(data.get("note", existing["note"] if existing else ""), 2000),
        "_assignee_ids": assignee_ids,
    }


def _validate_stage_pipeline_input(db, data, task_id=None):
    """Validate the registration/edit Stage Builder payload without creating a new ledger."""
    raw_stages = data.get("stages")
    if not isinstance(raw_stages, list):
        raise ValueError("Stage Pipeline 형식이 올바르지 않습니다.")
    if len(raw_stages) > 20:
        raise ValueError("Stage는 업무별 최대 20단계까지 구성할 수 있습니다.")

    existing = {}
    existing_current = None
    if task_id:
        existing = {
            row["id"]: dict(row)
            for row in db.execute(
                "SELECT * FROM major_task_stages WHERE task_id=? AND is_active=1",
                (task_id,),
            )
        }
        current_row = db.execute(
            "SELECT current_stage_id FROM major_tasks WHERE id=?", (task_id,)
        ).fetchone()
        existing_current = current_row["current_stage_id"] if current_row else None

    normalized = []
    keys = set()
    existing_ids = set()
    for index, raw in enumerate(raw_stages, start=1):
        if not isinstance(raw, dict):
            raise ValueError("각 Stage 정보를 다시 확인하세요.")
        stage_id = _clean(raw.get("id"), 32) or None
        if stage_id:
            if stage_id not in existing:
                raise ValueError("현재 업무의 활성 Stage만 수정할 수 있습니다.")
            if stage_id in existing_ids:
                raise ValueError("같은 Stage가 중복되었습니다.")
            existing_ids.add(stage_id)
            key = stage_id
        else:
            key = _clean(raw.get("client_id"), 80) or f"new-stage-{index}"
        if key in keys:
            raise ValueError("Stage 식별값이 중복되었습니다.")
        keys.add(key)
        source = existing.get(stage_id, {}) if stage_id else {}
        name = _clean(raw.get("name", source.get("name")), 200)
        if not name:
            raise ValueError(f"{index}단계 이름을 입력하세요.")
        target_date = _date(raw.get("target_date", source.get("target_date")), f"{index}단계 목표일")
        completed_at = _date(raw.get("completed_at", source.get("completed_at")), f"{index}단계 완료일")
        if "assignee_ids" in raw:
            assignee_ids = _normalized_user_ids(db, raw.get("assignee_ids"), f"{index}단계 담당자")
        elif source:
            assignee_ids = _stage_assignee_ids(db, source)
        else:
            assignee_ids = []
        requested_status = _clean(raw.get("status", source.get("status") or "planned"), 20)
        if requested_status not in STAGE_STATUSES - {"inactive"}:
            raise ValueError(f"{index}단계 상태가 올바르지 않습니다.")
        preserve_legacy_blank_completion = bool(
            source and source.get("status") == "completed" and not source.get("completed_at")
        )
        if requested_status == "completed" and not completed_at and not preserve_legacy_blank_completion:
            completed_at = _today().isoformat()
        normalized.append({
            "id": stage_id,
            "client_id": key,
            "name": name,
            "target_date": target_date,
            "completed_at": completed_at,
            "status": "completed" if completed_at or requested_status == "completed" else "planned",
            "assignee_ids": assignee_ids,
        })

    if "current_stage_key" in data:
        current_key = _clean(data.get("current_stage_key"), 80) or None
    elif existing_current and existing_current in keys:
        current_key = existing_current
    else:
        current_key = normalized[0]["client_id"] if normalized and not task_id else None
    if current_key and current_key not in keys:
        raise ValueError("현재 단계는 구성한 Stage 중에서 선택하세요.")
    for stage in normalized:
        if stage["client_id"] == current_key:
            if stage["completed_at"]:
                raise ValueError("완료된 Stage는 Current Stage로 지정할 수 없습니다.")
            stage["status"] = "active"
    for removed_id in set(existing) - existing_ids:
        if stage_work.stage_has_work(db, removed_id):
            raise ValueError("세부업무 이력이 있는 Stage는 삭제할 수 없습니다.")
    return normalized, current_key


def _stage_pipeline_snapshot(db, task_id):
    current_row = db.execute(
        "SELECT current_stage_id FROM major_tasks WHERE id=?", (task_id,)
    ).fetchone()
    current_id = current_row["current_stage_id"] if current_row else None
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "display_order": row["display_order"],
            "status": row["status"],
            "target_date": row["target_date"],
            "completed_at": row["completed_at"],
            "assignee_ids": _stage_assignee_ids(db, row),
            "is_current": row["id"] == current_id,
        }
        for row in db.execute(
            """SELECT id,name,display_order,status,owner_id,target_date,completed_at FROM major_task_stages
               WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at""",
            (task_id,),
        )
    ]


def _replace_stage_people(db, stage_id, assignee_ids, actor_id, now):
    if assignee_ids is None:
        return
    db.execute("DELETE FROM major_task_stage_people WHERE stage_id=?", (stage_id,))
    for user_id in assignee_ids:
        db.execute(
            """INSERT INTO major_task_stage_people
               (stage_id,user_id,relation_type,created_by,created_at)
               VALUES (?,?,'assignee',?,?)""",
            (stage_id, user_id, actor_id, now),
        )


def _apply_stage_pipeline(db, task_id, stages, current_key, actor_id, now):
    """Reconcile a visual Stage Builder draft with the existing canonical Stage rows."""
    before = _stage_pipeline_snapshot(db, task_id)
    existing = {
        row["id"]: dict(row)
        for row in db.execute(
            "SELECT * FROM major_task_stages WHERE task_id=? AND is_active=1",
            (task_id,),
        )
    }
    retained_ids = set()
    key_to_id = {}
    today = _today().isoformat()
    for order, spec in enumerate(stages, start=1):
        stage_id = spec["id"]
        is_current = spec["client_id"] == current_key
        pipeline_status = spec["status"]
        if stage_id:
            retained_ids.add(stage_id)
            source = existing[stage_id]
            status = pipeline_status
            started_at = source["started_at"] or (today if is_current else None)
            completed_at = spec["completed_at"] if status == "completed" else None
            if (
                source["name"] != spec["name"]
                or source["display_order"] != order
                or source["status"] != status
                or source["owner_id"] != (spec["assignee_ids"][0] if spec["assignee_ids"] else None)
                or source["target_date"] != spec["target_date"]
                or source["started_at"] != started_at
                or source["completed_at"] != completed_at
            ):
                db.execute(
                    """UPDATE major_task_stages
                       SET name=?,display_order=?,status=?,owner_id=?,target_date=?,started_at=?,completed_at=?,
                           updated_by=?,updated_at=?,version=version+1
                       WHERE id=?""",
                    (spec["name"], order, status,
                     spec["assignee_ids"][0] if spec["assignee_ids"] else None,
                     spec["target_date"], started_at,
                     completed_at, actor_id, now, stage_id),
                )
        else:
            stage_id = uuid.uuid4().hex
            status = pipeline_status
            db.execute(
                """INSERT INTO major_task_stages
                   (id,task_id,name,display_order,status,owner_id,target_date,started_at,completed_at,is_active,version,
                    created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,1,1,?,?,?,?)""",
                (stage_id, task_id, spec["name"], order, status,
                 spec["assignee_ids"][0] if spec["assignee_ids"] else None,
                 spec["target_date"],
                 today if is_current else None, spec["completed_at"],
                 actor_id, actor_id, now, now),
            )
        _replace_stage_people(db, stage_id, spec["assignee_ids"], actor_id, now)
        key_to_id[spec["client_id"]] = stage_id

    removed_ids = set(existing) - retained_ids
    for stage_id in removed_ids:
        db.execute(
            """UPDATE major_task_stages
               SET is_active=0,status='inactive',updated_by=?,updated_at=?,version=version+1
               WHERE id=?""",
            (actor_id, now, stage_id),
        )

    current_stage_id = key_to_id.get(current_key) if current_key else None
    db.execute(
        "UPDATE major_tasks SET current_stage_id=? WHERE id=?",
        (current_stage_id, task_id),
    )
    return before, _stage_pipeline_snapshot(db, task_id)


def _replace_task_relations(db, task_id, data, now, actor_id=None):
    if "additional_owner_ids" in data:
        additional_owner_ids = _normalized_user_ids(
            db, data.get("additional_owner_ids"), "공동 담당자"
        ) or []
        task = db.execute("SELECT owner_id FROM major_tasks WHERE id=?", (task_id,)).fetchone()
        if task and task["owner_id"] in additional_owner_ids:
            raise ValueError("대표 책임자를 공동 담당자에 중복 지정할 수 없습니다.")
        db.execute("DELETE FROM major_task_assignees WHERE task_id=?", (task_id,))
        for user_id in additional_owner_ids:
            db.execute(
                """INSERT INTO major_task_assignees
                   (task_id,user_id,relation_type,created_by,created_at)
                   VALUES (?,?,'additional_owner',?,?)""",
                (task_id, user_id, actor_id, now),
            )
    links = data.get("business_links")
    if links is not None:
        existing_task = db.execute("SELECT * FROM major_tasks WHERE id=?", (task_id,)).fetchone()
        normalized = _normalized_business_links(db, data, existing_task)
        db.execute("DELETE FROM major_task_business_links WHERE task_id=?", (task_id,))
        for link in normalized if normalized is not None else links:
            if not isinstance(link, dict):
                continue
            unit, sub = _business_values(link.get("business_unit"), link.get("business_subcategory"), legacy=True)
            db.execute(
                "INSERT OR IGNORE INTO major_task_business_links(task_id,business_unit,business_subcategory,is_primary,created_at) VALUES (?,?,?,?,?)",
                (task_id, unit, sub, int(bool(link.get("is_primary"))) if normalized is not None else 0, now),
            )
    participants = data.get("people")
    if participants is not None:
        db.execute("DELETE FROM major_task_people WHERE task_id=?", (task_id,))
        seen_people = set()
        for person in participants:
            user_id = _int(person.get("user_id")) if isinstance(person, dict) else None
            relation = _clean(person.get("relation_type"), 20) if isinstance(person, dict) else ""
            if relation not in {"participant", "cooperator"}:
                raise ValueError("참여자·협조자 역할이 올바르지 않습니다.")
            if not user_id or not _user_exists(db, user_id):
                raise ValueError("참여자·협조자 사용자를 찾을 수 없습니다.")
            key = (user_id, relation)
            if key in seen_people:
                raise ValueError("같은 역할에 동일 사용자를 중복 지정할 수 없습니다.")
            seen_people.add(key)
            db.execute(
                "INSERT INTO major_task_people(task_id,user_id,relation_type,created_at) VALUES (?,?,?,?)",
                (task_id, user_id, relation, now),
            )
    products = data.get("products")
    if products is None and ("product_name" in data or "product_code" in data):
        products = [{
            "product_name": data.get("product_name"),
            "product_code": data.get("product_code"),
            "source_type": "manual",
        }] if _clean(data.get("product_name"), 300) else []
    if products is not None:
        db.execute("DELETE FROM major_task_products WHERE task_id=?", (task_id,))
        for product in products:
            if not isinstance(product, dict):
                continue
            product_name = _clean(product.get("product_name"), 300)
            if not product_name:
                continue
            source_type = _clean(product.get("source_type") or "manual", 30)
            if source_type not in {"manual", "shipment", "customer_term"}:
                raise ValueError("관련 제품 출처가 올바르지 않습니다.")
            db.execute(
                """INSERT OR IGNORE INTO major_task_products
                   (id,task_id,product_code,product_name,source_type,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (uuid.uuid4().hex, task_id, _clean(product.get("product_code"), 100), product_name, source_type, now),
            )


def _replace_action_people(db, action_id, people, now):
    if people is None:
        return
    people = _normalized_user_ids(db, people, "Action 담당자") or []
    db.execute("DELETE FROM major_task_action_people WHERE action_id=?", (action_id,))
    for user_id in people:
        db.execute(
            """INSERT INTO major_task_action_people
               (action_id,user_id,relation_type,created_at) VALUES (?,?,'cooperator',?)""",
            (action_id, user_id, now),
        )


def _replace_workstream_business(db, workstream_id, links):
    if links is None:
        return
    validated = []
    for link in links:
        if not isinstance(link, dict):
            continue
        validated.append(_business_values(link.get("business_unit"), link.get("business_subcategory")))
    db.execute("DELETE FROM major_task_workstream_business WHERE workstream_id=?", (workstream_id,))
    for unit, subcategory in validated:
        db.execute(
            """INSERT OR IGNORE INTO major_task_workstream_business
               (workstream_id,business_unit,business_subcategory) VALUES (?,?,?)""",
            (workstream_id, unit, subcategory),
        )


def _instantiate_template(db, task_id, workstream_id, actor_id, now):
    if not workstream_id:
        return
    rows = db.execute(
        """SELECT t.* FROM major_task_workstream_templates t
           JOIN major_task_workstreams w ON w.id=t.workstream_id
           WHERE t.workstream_id=? AND t.template_version=w.template_version
           ORDER BY CASE item_type WHEN 'milestone' THEN 0 WHEN 'area' THEN 1 WHEN 'action' THEN 2 ELSE 3 END,
                    t.display_order,t.created_at""",
        (workstream_id,),
    ).fetchall()
    mapped = {}
    for row in rows:
        new_id = uuid.uuid4().hex
        mapped[row["id"]] = new_id
        if row["item_type"] == "milestone":
            db.execute(
                """INSERT INTO major_task_milestones
                   (id,task_id,name,description,status,is_required,display_order,is_active,version,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,'not_started',?,?,1,1,?,?,?,?)""",
                (new_id, task_id, row["name"], row["description"], row["is_required"], row["display_order"], actor_id, actor_id, now, now),
            )
        elif row["item_type"] == "area" and row["parent_id"] in mapped:
            db.execute(
                """INSERT INTO major_task_action_areas
                   (id,milestone_id,name,description,display_order,is_active,version,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,1,1,?,?,?,?)""",
                (new_id, mapped[row["parent_id"]], row["name"], row["description"], row["display_order"], actor_id, actor_id, now, now),
            )
        elif row["item_type"] == "action":
            parent = db.execute("SELECT item_type,parent_id FROM major_task_workstream_templates WHERE id=?", (row["parent_id"],)).fetchone()
            milestone_template = row["parent_id"] if parent and parent["item_type"] == "milestone" else parent["parent_id"] if parent else None
            if milestone_template in mapped:
                db.execute(
                    """INSERT INTO major_task_actions
                       (id,task_id,milestone_id,area_id,name,status,importance,is_required,include_in_progress,include_in_rag,display_order,is_active,version,created_by,updated_by,created_at,updated_at)
                       VALUES (?,?,?,?,?,'not_started','medium',?,?,?,?,1,1,?,?,?,?)""",
                    (new_id, task_id, mapped[milestone_template], mapped.get(row["parent_id"]) if parent and parent["item_type"] == "area" else None,
                     row["name"], row["is_required"], row["include_in_progress"], row["is_required"], row["display_order"], actor_id, actor_id, now, now),
                )
        elif row["item_type"] == "checklist" and row["parent_id"] in mapped:
            db.execute(
                """INSERT INTO major_task_checklists
                   (id,action_id,item_text,is_completed,is_required,display_order,version,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,0,?,?,1,?,?,?,?)""",
                (new_id, mapped[row["parent_id"]], row["name"], row["is_required"], row["display_order"], actor_id, actor_id, now, now),
            )


def _instantiate_stage_template(db, task_id, template_code, actor_id, now):
    names = STAGE_TEMPLATES.get(_clean(template_code, 40))
    if not names:
        return []
    created = []
    first_id = None
    for order, name in enumerate(names, start=1):
        stage_id = uuid.uuid4().hex
        first_id = first_id or stage_id
        db.execute(
            """INSERT INTO major_task_stages
               (id,task_id,name,display_order,status,started_at,is_active,version,created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,1,1,?,?,?,?)""",
            (stage_id, task_id, name, order, "active" if order == 1 else "planned",
             _today().isoformat() if order == 1 else None, actor_id, actor_id, now, now),
        )
        created.append(stage_id)
    db.execute("UPDATE major_tasks SET current_stage_id=? WHERE id=?", (first_id, task_id))
    return created


def _dependency_cycle(db, table, source_column, predecessor_column, source_id, predecessors):
    graph = {}
    for row in db.execute(f"SELECT {source_column},{predecessor_column} FROM {table}"):
        graph.setdefault(row[source_column], set()).add(row[predecessor_column])
    graph[source_id] = set(predecessors)
    visiting, visited = set(), set()
    def visit(node):
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, ())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False
    return visit(source_id)


def _copy_task_structure(db, source_task_id, target_task_id, actor_id, now):
    milestone_map = {}
    action_map = {}
    area_map = {}
    for source in db.execute(
        "SELECT * FROM major_task_stages WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at",
        (source_task_id,),
    ):
        target_stage_id = uuid.uuid4().hex
        assignee_ids = _stage_assignee_ids(db, source)
        db.execute(
            """INSERT INTO major_task_stages
               (id,task_id,name,display_order,status,owner_id,target_date,note,is_active,version,
                created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,'planned',?,?,?,1,1,?,?,?,?)""",
            (target_stage_id, target_task_id, source["name"], source["display_order"],
             assignee_ids[0] if assignee_ids else None, source["target_date"], source["note"],
             actor_id, actor_id, now, now),
        )
        _replace_stage_people(db, target_stage_id, assignee_ids, actor_id, now)
    for source in db.execute(
        "SELECT * FROM major_task_milestones WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at",
        (source_task_id,),
    ):
        target_id = uuid.uuid4().hex
        milestone_map[source["id"]] = target_id
        db.execute(
            """INSERT INTO major_task_milestones
               (id,task_id,name,description,planned_start_date,planned_end_date,owner_id,deputy_owner_id,
                status,is_required,display_order,is_active,version,created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?, 'not_started',?,?,1,1,?,?,?,?)""",
            (target_id,target_task_id,source["name"],source["description"],source["planned_start_date"],
             source["planned_end_date"],source["owner_id"],source["deputy_owner_id"],source["is_required"],
             source["display_order"],actor_id,actor_id,now,now),
        )
    for source in db.execute(
        """SELECT a.* FROM major_task_action_areas a JOIN major_task_milestones m ON m.id=a.milestone_id
           WHERE m.task_id=? AND a.is_active=1 ORDER BY a.display_order,a.created_at""", (source_task_id,)
    ):
        target_id=uuid.uuid4().hex;area_map[source["id"]]=target_id
        db.execute("""INSERT INTO major_task_action_areas
          (id,milestone_id,name,description,display_order,is_active,version,created_by,updated_by,created_at,updated_at)
          VALUES (?,?,?,?,?,1,1,?,?,?,?)""",
          (target_id,milestone_map[source["milestone_id"]],source["name"],source["description"],source["display_order"],actor_id,actor_id,now,now))
    for source in db.execute(
        "SELECT * FROM major_task_actions WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at",
        (source_task_id,),
    ):
        target_id=uuid.uuid4().hex;action_map[source["id"]]=target_id
        db.execute("""INSERT INTO major_task_actions
          (id,task_id,milestone_id,area_id,name,owner_id,deputy_owner_id,start_date,due_date,status,importance,
           is_required,include_in_progress,include_in_rag,next_action,display_order,is_active,version,created_by,updated_by,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,'not_started',?,?,?,?,?,?,1,1,?,?,?,?)""",
          (target_id,target_task_id,milestone_map[source["milestone_id"]],area_map.get(source["area_id"]),source["name"],
           source["owner_id"],source["deputy_owner_id"],source["start_date"],source["due_date"],source["importance"],
           source["is_required"],source["include_in_progress"],source["include_in_rag"],source["next_action"],
           source["display_order"],actor_id,actor_id,now,now))
        for person in db.execute("SELECT user_id FROM major_task_action_people WHERE action_id=?",(source["id"],)):
            db.execute("INSERT INTO major_task_action_people(action_id,user_id,relation_type,created_at) VALUES (?,?,'cooperator',?)",(target_id,person["user_id"],now))
        for check in db.execute("SELECT * FROM major_task_checklists WHERE action_id=? AND is_active=1 ORDER BY display_order,created_at",(source["id"],)):
            db.execute("""INSERT INTO major_task_checklists
              (id,action_id,item_text,is_completed,is_required,display_order,version,created_by,updated_by,created_at,updated_at)
              VALUES (?,?,?,0,?,?,1,?,?,?,?)""",
              (uuid.uuid4().hex,target_id,check["item_text"],check["is_required"],check["display_order"],actor_id,actor_id,now,now))
    for source in db.execute("""SELECT d.* FROM major_task_milestone_dependencies d
      JOIN major_task_milestones m ON m.id=d.milestone_id WHERE m.task_id=?""",(source_task_id,)):
        if source["milestone_id"] in milestone_map and source["predecessor_id"] in milestone_map:
            db.execute("INSERT INTO major_task_milestone_dependencies(milestone_id,predecessor_id,created_by,created_at) VALUES (?,?,?,?)",(milestone_map[source["milestone_id"]],milestone_map[source["predecessor_id"]],actor_id,now))
    for source in db.execute("""SELECT d.* FROM major_task_action_dependencies d
      JOIN major_task_actions a ON a.id=d.action_id WHERE a.task_id=?""",(source_task_id,)):
        if source["action_id"] in action_map and source["predecessor_id"] in action_map:
            db.execute("INSERT INTO major_task_action_dependencies(action_id,predecessor_id,created_by,created_at) VALUES (?,?,?,?)",(action_map[source["action_id"]],action_map[source["predecessor_id"]],actor_id,now))
    stage_count = db.execute(
        "SELECT COUNT(*) FROM major_task_stages WHERE task_id=?", (target_task_id,)
    ).fetchone()[0]
    return {"stages":stage_count,"milestones":len(milestone_map),"areas":len(area_map),"actions":len(action_map)}


def _apply_progress_state_changes(db, task, data, actor_id, now, audit_fn):
    """Apply optional Stage/RAG/task-level Ball changes in the same transaction.

    The current values remain in their canonical owners.  The progress row only
    stores references/provenance for the changes applied with that update.
    """
    stage_id = _clean(data.get("stage_id"), 32) or None
    rag_value = _clean(data.get("rag_value"), 10) or None
    rag_reason = _clean(data.get("rag_reason"), 500)
    ball_requested = "ball_type" in data and data.get("ball_type") not in (None, "")
    ball_type = _clean(data.get("ball_type"), 20) if ball_requested else None
    ball_owner_type = None
    ball_follow_up_date = None

    stage = None
    if stage_id:
        stage = db.execute(
            "SELECT * FROM major_task_stages WHERE id=? AND task_id=? AND is_active=1",
            (stage_id, task["id"]),
        ).fetchone()
        if not stage or stage["status"] in {"completed", "inactive"}:
            raise ValueError("현재 업무의 활성 미완료 Stage만 선택할 수 있습니다.")
    if rag_value:
        if rag_value not in RAG_SCORE:
            raise ValueError("RAG 값이 올바르지 않습니다.")
        if not rag_reason:
            raise ValueError("RAG 변경 사유를 입력하세요.")
    if ball_requested:
        ball_owner_type = _ball_owner_type(ball_type)
        ball_follow_up_date = _date(data.get("ball_follow_up_date"), "Ball Follow-up Date")

    changes = {}
    progress_next_action = _clean(data.get("next_action"), 1000)
    if progress_next_action:
        progress_due = _date(data.get("next_action_date"), "다음 액션 기한")
        before_action = {"next_action": task["next_action"], "next_action_date": task["next_action_date"]}
        after_action = {"next_action": progress_next_action, "next_action_date": progress_due}
        if before_action != after_action:
            db.execute(
                "UPDATE major_tasks SET next_action=?,next_action_date=? WHERE id=?",
                (progress_next_action, progress_due, task["id"]),
            )
            changes["next_action"] = {"before": before_action, "after": after_action}
            _audit(audit_fn, "MAJOR_TASK_NEXT_ACTION_CHANGE", "major_task", task["id"],
                   f"{task['title']} Next Action 변경", before_action, after_action)
    if stage and task["current_stage_id"] != stage_id:
        before_stage_id = task["current_stage_id"]
        if before_stage_id:
            db.execute(
                "UPDATE major_task_stages SET status=CASE WHEN status='active' THEN 'planned' ELSE status END,updated_by=?,updated_at=?,version=version+1 WHERE id=?",
                (actor_id, now, before_stage_id),
            )
        db.execute(
            "UPDATE major_task_stages SET status='active',started_at=COALESCE(started_at,?),updated_by=?,updated_at=?,version=version+1 WHERE id=?",
            (_today().isoformat(), actor_id, now, stage_id),
        )
        db.execute("UPDATE major_tasks SET current_stage_id=? WHERE id=?", (stage_id, task["id"]))
        changes["stage"] = {"before": before_stage_id, "after": stage_id}
        _audit(audit_fn, "MAJOR_TASK_STAGE_CURRENT_CHANGE", "major_task", task["id"],
               f"{task['title']} Current Stage 변경", {"stage_id": before_stage_id}, {"stage_id": stage_id})

    if rag_value and (task["manual_rag"] != rag_value or task["manual_rag_reason"] != rag_reason):
        before_rag = {"manual_rag": task["manual_rag"], "manual_rag_reason": task["manual_rag_reason"], "final_rag": task["final_rag"]}
        db.execute(
            "UPDATE major_tasks SET manual_rag=?,manual_rag_reason=?,final_rag=? WHERE id=?",
            (rag_value, rag_reason, rag_value, task["id"]),
        )
        after_rag = {"manual_rag": rag_value, "manual_rag_reason": rag_reason, "final_rag": rag_value}
        changes["rag"] = {"before": before_rag, "after": after_rag}
        _audit(audit_fn, "MAJOR_TASK_RAG_CHANGE", "major_task", task["id"],
               f"{task['title']} RAG 변경", before_rag, after_rag)

    applied_ball_id = None
    if ball_requested:
        prior_balls = db.execute(
            """SELECT * FROM major_task_balls
               WHERE task_id=? AND milestone_id IS NULL AND action_id IS NULL
                 AND is_active=1 AND resolved_at IS NULL ORDER BY created_at""",
            (task["id"],),
        ).fetchall()
        resolved_ids = []
        for prior in prior_balls:
            before_ball = dict(prior)
            db.execute(
                "UPDATE major_task_balls SET resolved_at=?,is_active=0,updated_by=?,updated_at=?,version=version+1 WHERE id=?",
                (_today().isoformat(), actor_id, now, prior["id"]),
            )
            after_ball = dict(db.execute("SELECT * FROM major_task_balls WHERE id=?", (prior["id"],)).fetchone())
            db.execute(
                """INSERT INTO major_task_ball_history
                   (id,ball_id,change_type,before_json,after_json,reason,changed_by,changed_at)
                   VALUES (?,?,'resolve',?,?,?,?,?)""",
                (uuid.uuid4().hex, prior["id"], _json(before_ball), _json(after_ball),
                 "진행이력에서 Current Ball 변경", actor_id, now),
            )
            resolved_ids.append(prior["id"])
        if ball_owner_type != "none":
            applied_ball_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO major_task_balls
                   (id,task_id,owner_type,owner_detail,request_text,wait_started_at,follow_up_date,
                    hard_deadline_impact,is_active,version,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,'none',1,1,?,?,?,?)""",
                (applied_ball_id, task["id"], ball_owner_type,
                 _clean(data.get("ball_holder"), 300), _clean(data.get("ball_note"), 2000),
                 _today().isoformat(), ball_follow_up_date, actor_id, actor_id, now, now),
            )
            created_ball = dict(db.execute("SELECT * FROM major_task_balls WHERE id=?", (applied_ball_id,)).fetchone())
            db.execute(
                """INSERT INTO major_task_ball_history
                   (id,ball_id,change_type,after_json,reason,changed_by,changed_at)
                   VALUES (?,?,'create',?,?,?,?)""",
                (uuid.uuid4().hex, applied_ball_id, _json(created_ball),
                 "진행이력에서 Current Ball 변경", actor_id, now),
            )
        changes["ball"] = {
            "resolved_ids": resolved_ids,
            "after_id": applied_ball_id,
            "after_type": BALL_CANONICAL_TYPES.get(ball_owner_type, "none"),
        }
        _audit(audit_fn, "MAJOR_TASK_CURRENT_BALL_CHANGE", "major_task", task["id"],
               f"{task['title']} Current Ball 변경", {"ball_ids": resolved_ids}, changes["ball"])

    return {
        "applied_stage_id": stage_id if "stage" in changes else None,
        "applied_ball_id": applied_ball_id,
        "applied_rag": rag_value if "rag" in changes else None,
        "state_change_json": _json(changes),
    }


def _audit(audit_fn, action, entity, entity_id, summary, before=None, after=None):
    audit_fn(action, entity, entity_id, summary, before, after)


def register_major_tasks(app, get_db, role_required, csrf_required, audit_fn):
    stage_work.register(app, get_db, role_required, csrf_required, audit_fn)
    @app.get("/api/major-tasks/meta")
    @role_required(*READ_ROLES)
    def major_tasks_meta():
        db = get_db()
        workstreams = [dict(row) for row in db.execute(
            "SELECT * FROM major_task_workstreams ORDER BY is_active DESC,display_order,name"
        )]
        for workstream in workstreams:
            name = workstream["name"]
            workstream["canonical_code"] = CANONICAL_WORKSTREAMS.get(name)
            workstream["taxonomy_status"] = "canonical" if name in CANONICAL_WORKSTREAMS else "legacy_review"
            workstream["recommended_canonical_code"] = LEGACY_WORKSTREAM_REVIEW.get(name)
        workstreams.sort(key=lambda row: (row["taxonomy_status"] != "canonical", row["display_order"], row["name"]))
        products = [dict(row) for row in db.execute(
            """SELECT product_code,product_name FROM (
                 SELECT DISTINCT COALESCE(product_code,'') AS product_code,COALESCE(product_name,'') AS product_name FROM shipments
                 UNION SELECT DISTINCT COALESCE(internal_product_code,''),product_name FROM customer_product_terms WHERE deleted_at IS NULL
               ) WHERE product_name<>'' ORDER BY product_name LIMIT 500"""
        )]
        customers = [dict(row) for row in db.execute(
            "SELECT id,customer_id,display_name,headquarters_country FROM customer_master ORDER BY display_name"
        )]
        countries = [row["country"] for row in db.execute(
            "SELECT DISTINCT country FROM major_tasks WHERE country<>'' ORDER BY country"
        )]
        parent_candidates = _parent_candidates(db)
        sections = _section_rows(db)
        return jsonify(
            schema_version=MAJOR_TASKS_SCHEMA_VERSION, workstreams=workstreams, products=products,
            customers=customers, countries=countries, parent_candidates=parent_candidates,
            sections=sections, section_can_edit=g.current_user["role"] in WRITE_ROLES,
            business={key: list(values) for key, values in BUSINESS.items()},
            business_labels=BUSINESS_LABELS,
            stage_templates={key: list(values) for key, values in STAGE_TEMPLATES.items()},
            ball_types={"internal": "우리", "customer": "고객", "external": "외부기관", "none": "없음"},
            blocker_categories=sorted(BLOCKER_CATEGORIES), directive_types=sorted(DIRECTIVE_TYPES),
            max_hierarchy_depth=MAX_UI_HIERARCHY_DEPTH,
            attachment_storage={"mode": "external_link_only", "upload_enabled": False},
        )

    @app.get("/api/major-task-sections")
    @role_required(*READ_ROLES)
    def major_task_sections_list():
        db = get_db()
        return jsonify(
            sections=_section_rows(db),
            unassigned_root_count=db.execute(
                "SELECT COUNT(*) FROM major_tasks WHERE parent_task_id IS NULL AND section_id IS NULL"
            ).fetchone()[0],
            can_edit=g.current_user["role"] in WRITE_ROLES,
        )

    @app.post("/api/major-task-sections")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_section_create():
        db = get_db(); data = request.get_json(silent=True) or {}
        try:
            name = _section_name(data.get("name"))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if _section_name_exists(db, name):
            return jsonify(error="같은 이름의 Section이 이미 있습니다."), 409
        section_id = uuid.uuid4().hex
        now = _now()
        sort_order = db.execute(
            "SELECT COALESCE(MAX(sort_order),0)+1 FROM major_task_sections"
        ).fetchone()[0]
        try:
            db.execute(
                """INSERT INTO major_task_sections
                   (id,name,sort_order,is_active,version,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,1,1,?,?,?,?)""",
                (section_id, name, sort_order, g.current_user["id"],
                 g.current_user["id"], now, now),
            )
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="같은 이름의 Section이 이미 있습니다."), 409
        created = next(row for row in _section_rows(db) if row["id"] == section_id)
        _audit(
            audit_fn, "SECTION_CREATE", "major_task_section", section_id,
            f"{name} Section 생성", None, created,
        )
        db.commit()
        return jsonify(message="Section이 생성되었습니다.", section=created), 201

    @app.patch("/api/major-task-sections/<section_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_section_update(section_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        existing = db.execute(
            "SELECT * FROM major_task_sections WHERE id=?", (section_id,)
        ).fetchone()
        if not existing:
            return jsonify(error="Section을 찾을 수 없습니다."), 404
        try:
            expected = _version(data)
            name = _section_name(data.get("name", existing["name"]))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if _section_name_exists(db, name, section_id):
            return jsonify(error="같은 이름의 Section이 이미 있습니다."), 409
        is_active = _bool(data.get("is_active", existing["is_active"]))
        before = dict(existing)
        if name == existing["name"] and is_active == existing["is_active"]:
            current = next(row for row in _section_rows(db) if row["id"] == section_id)
            return jsonify(message="변경할 Section 정보가 없습니다.", section=current)
        now = _now()
        try:
            cursor = db.execute(
                """UPDATE major_task_sections
                   SET name=?,is_active=?,updated_by=?,updated_at=?,version=version+1
                   WHERE id=? AND version=?""",
                (name, is_active, g.current_user["id"], now, section_id, expected),
            )
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="같은 이름의 Section이 이미 있습니다."), 409
        if cursor.rowcount != 1:
            db.rollback()
            return jsonify(
                error="다른 사용자가 먼저 Section을 수정했습니다. 최신 자료를 다시 불러오세요.",
                code="VERSION_CONFLICT",
            ), 409
        after = next(row for row in _section_rows(db) if row["id"] == section_id)
        if name != existing["name"]:
            _audit(
                audit_fn, "SECTION_RENAME", "major_task_section", section_id,
                f"{existing['name']} → {name} Section 이름변경", before, after,
            )
        if is_active != existing["is_active"]:
            action = "SECTION_REACTIVATE" if is_active else "SECTION_DEACTIVATE"
            verb = "재활성화" if is_active else "비활성화"
            _audit(
                audit_fn, action, "major_task_section", section_id,
                f"{name} Section {verb}", before, after,
            )
        db.commit()
        return jsonify(message="Section이 수정되었습니다.", section=after)

    @app.post("/api/major-task-sections/reorder")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_sections_reorder():
        db = get_db(); data = request.get_json(silent=True) or {}
        raw = data.get("sections")
        if not isinstance(raw, list):
            return jsonify(error="Section 순서 형식이 올바르지 않습니다."), 400
        existing = _section_rows(db)
        existing_ids = [row["id"] for row in existing]
        try:
            ordered = [
                {"id": _clean(item.get("id"), 32), "version": _int(item.get("version"))}
                for item in raw if isinstance(item, dict)
            ]
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        ordered_ids = [item["id"] for item in ordered]
        if (
            len(ordered) != len(raw)
            or len(set(ordered_ids)) != len(ordered_ids)
            or set(ordered_ids) != set(existing_ids)
            or any(item["version"] is None for item in ordered)
        ):
            return jsonify(error="모든 Section의 최신 순서를 다시 확인하세요."), 400
        if ordered_ids == existing_ids:
            return jsonify(message="Section 순서가 이미 같습니다.", sections=existing)
        before = [{"id": row["id"], "name": row["name"], "sort_order": row["sort_order"]} for row in existing]
        now = _now()
        for sort_order, item in enumerate(ordered, start=1):
            cursor = db.execute(
                """UPDATE major_task_sections
                   SET sort_order=?,updated_by=?,updated_at=?,version=version+1
                   WHERE id=? AND version=?""",
                (sort_order, g.current_user["id"], now, item["id"], item["version"]),
            )
            if cursor.rowcount != 1:
                db.rollback()
                return jsonify(
                    error="다른 사용자가 먼저 Section 순서를 수정했습니다. 최신 자료를 다시 불러오세요.",
                    code="VERSION_CONFLICT",
                ), 409
        after_rows = _section_rows(db)
        after = [{"id": row["id"], "name": row["name"], "sort_order": row["sort_order"]} for row in after_rows]
        _audit(
            audit_fn, "SECTION_REORDER", "major_task_section", "all",
            "Major Task Section 순서변경", before, after,
        )
        db.commit()
        return jsonify(message="Section 순서가 저장되었습니다.", sections=after_rows)

    @app.get("/api/major-tasks")
    @role_required(*READ_ROLES)
    def major_tasks_list():
        db = get_db()
        hierarchical = request.args.get("hierarchy") == "root" and request.args.get("include_children") == "1"
        if hierarchical:
            base_args = request.args.to_dict(flat=True)
            base_args.pop("hierarchy", None)
            base_args.pop("include_children", None)
            all_rows = list_task_rows(db, base_args, g.current_user["id"])
            matching_ids = {row["id"] for row in all_rows}
            rows = [
                row for row in all_rows
                if not row["parent_task_id"] or row["parent_task_id"] not in matching_ids
            ]
        else:
            rows = list_task_rows(db, request.args, g.current_user["id"])
            all_rows = rows
        page = max(1, _int(request.args.get("page"), 1))
        per_page = min(100, max(10, _int(request.args.get("per_page"), 30)))
        start = (page - 1) * per_page
        page_rows = rows[start:start + per_page]
        if hierarchical:
            children_by_parent = {}
            for child in all_rows:
                if child["parent_task_id"]:
                    children_by_parent.setdefault(child["parent_task_id"], []).append(child)
            def serialize_branch(row, depth=1, ancestors=None):
                ancestors = set(ancestors or ())
                item = _serialize_task(db, row, True, g.current_user)
                item["tree_depth"] = depth
                if row["id"] in ancestors:
                    item["children"] = []
                    item["hierarchy_warning"] = "cycle"
                    return item
                next_ancestors = ancestors | {row["id"]}
                item["children"] = [
                    serialize_branch(child, depth + 1, next_ancestors)
                    for child in children_by_parent.get(row["id"], [])
                    if child["id"] not in next_ancestors
                ]
                return item
            items = [serialize_branch(row) for row in page_rows]
        else:
            items = [_serialize_task(db, row, True, g.current_user) for row in page_rows]
        directives = [
            _serialize_task(db, row, True, g.current_user)
            for row in all_rows
            if row["ceo_directive"] and row["status"] not in {"completed", "cancelled"} and not row["archived_at"]
        ]
        directives.sort(key=lambda item: (
            0 if item["final_rag"] == "red" else 1,
            0 if item["is_overdue"] else 1,
            0 if item["final_rag"] == "amber" else 1,
            item["effective_deadline"] or "9999-12-31", item["directive_date"] or "9999-12-31",
        ))
        directives = directives[:50]
        stage_work.add_list_summaries(db, items, _today())
        return jsonify(
            items=items,
            directives=directives,
            summary=_summaries(db, all_rows, g.current_user["id"]),
            pagination={
                "page": page,
                "per_page": per_page,
                "total": len(rows),
                "total_tasks": len(all_rows),
                "pages": (len(rows) + per_page - 1) // per_page,
            },
        )

    @app.post("/api/major-tasks")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_tasks_create():
        db = get_db(); data = request.get_json(silent=True) or {}; now = _now()
        try:
            values = _validate_task_input(db, data)
            stage_pipeline = _validate_stage_pipeline_input(db, data) if "stages" in data else None
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        stage_template_code = _clean(data.get("stage_template_code"), 40)
        if stage_pipeline is None and stage_template_code and stage_template_code not in STAGE_TEMPLATES:
            return jsonify(error="Stage Template이 올바르지 않습니다."), 400
        if values["owner_id"] is None:
            values["owner_id"] = g.current_user["id"]
        task_id = uuid.uuid4().hex
        columns = list(values)
        db.execute(
            f"INSERT INTO major_tasks(id,{','.join(columns)},auto_rag,final_rag,recent_updated_at,version,created_by,updated_by,created_at,updated_at) VALUES (?{',?' * len(columns)},'green','green',?,1,?,?,?,?)",
            (task_id, *[values[key] for key in columns], now, g.current_user["id"], g.current_user["id"], now, now),
        )
        db.execute(
            "INSERT INTO major_task_business_links(task_id,business_unit,business_subcategory,is_primary,created_at) VALUES (?,?,?,?,?)",
            (task_id, values["primary_business_unit"], values["primary_business_subcategory"], 1, now),
        )
        try:
            _replace_task_relations(db, task_id, data, now, g.current_user["id"])
            db.execute(
                "INSERT OR IGNORE INTO major_task_business_links(task_id,business_unit,business_subcategory,is_primary,created_at) VALUES (?,?,?,?,?)",
                (task_id, values["primary_business_unit"], values["primary_business_subcategory"], 1, now),
            )
            _instantiate_template(db, task_id, values["workstream_id"], g.current_user["id"], now)
            if stage_pipeline is not None:
                pipeline_before, pipeline_after = _apply_stage_pipeline(
                    db, task_id, stage_pipeline[0], stage_pipeline[1], g.current_user["id"], now
                )
            else:
                _instantiate_stage_template(db, task_id, stage_template_code, g.current_user["id"], now)
                pipeline_before, pipeline_after = [], _stage_pipeline_snapshot(db, task_id)
            _refresh_rag(db, task_id)
            created = _serialize_task(db, _task_row(db, task_id), True, g.current_user, True)
            _audit(audit_fn, "MAJOR_TASK_CREATE", "major_task", task_id, f"{values['title']} 주요업무 생성", None, created)
            if values.get("section_id"):
                _audit(
                    audit_fn, "TASK_SECTION_CHANGE", "major_task", task_id,
                    f"{values['title']} Section 지정", None,
                    {"section_id": created["section_id"], "section_name": created["section_name"]},
                )
            if pipeline_after:
                _audit(audit_fn, "MAJOR_TASK_STAGE_PIPELINE_CREATE", "major_task", task_id,
                       f"{values['title']} Stage Pipeline 생성", pipeline_before, pipeline_after)
            db.commit()
        except ValueError as exc:
            db.rollback()
            return jsonify(error=str(exc)), 400
        except Exception:
            db.rollback(); raise
        return jsonify(message="주요업무가 등록되었습니다.", task=created), 201

    @app.get("/api/major-tasks/<task_id>")
    @role_required(*READ_ROLES)
    def major_task_detail(task_id):
        db = get_db()
        if refresh_major_task_rags(db):
            db.commit()
        task = _task_row(db, task_id)
        if not task:
            return jsonify(error="주요업무를 찾을 수 없습니다."), 404
        item = _serialize_task(db, task, True, g.current_user, True)
        item["stages"] = [
            _serialize_stage(row, item["current_stage_id"], db)
            for row in db.execute(
                """SELECT s.*,u.display_name AS owner_name
                   FROM major_task_stages s LEFT JOIN users u ON u.id=s.owner_id
                   WHERE s.task_id=? ORDER BY s.is_active DESC,s.display_order,s.created_at""",
                (task_id,),
            )
        ]
        for stage in item["stages"]:
            stage["permissions"] = {
                "edit": item["permissions"]["structure"],
                "deactivate": item["permissions"]["structure"] and bool(stage["is_active"]),
            }
        item["children"] = [
            _serialize_task(db, _task_row(db, child["id"]), True, g.current_user)
            for child in db.execute(
                "SELECT id FROM major_tasks WHERE parent_task_id=? ORDER BY status,title COLLATE NOCASE",
                (task_id,),
            )
        ]
        item["milestones"] = []
        for milestone in db.execute(
            "SELECT * FROM major_task_milestones WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at", (task_id,)
        ):
            m = dict(milestone)
            m["permissions"] = {"edit": _can_milestone(db, milestone, g.current_user), "deactivate": item["permissions"]["structure"]}
            m["predecessors"] = [row["predecessor_id"] for row in db.execute("SELECT predecessor_id FROM major_task_milestone_dependencies WHERE milestone_id=?", (m["id"],))]
            m["areas"] = [dict(row) for row in db.execute("SELECT * FROM major_task_action_areas WHERE milestone_id=? AND is_active=1 ORDER BY display_order,created_at", (m["id"],))]
            for area in m["areas"]:
                area["permissions"] = {"edit": m["permissions"]["edit"], "deactivate": item["permissions"]["structure"]}
            m["actions"] = []
            for action in db.execute("SELECT * FROM major_task_actions WHERE milestone_id=? AND is_active=1 ORDER BY display_order,created_at", (m["id"],)):
                a = dict(action)
                action_edit = _can_action(db, action, g.current_user)
                a["permissions"] = {"edit": action_edit, "deactivate": item["permissions"]["structure"]}
                a["predecessors"] = [row["predecessor_id"] for row in db.execute("SELECT predecessor_id FROM major_task_action_dependencies WHERE action_id=?", (a["id"],))]
                a["cooperators"] = [dict(row) for row in db.execute(
                    """SELECT p.user_id,u.display_name FROM major_task_action_people p
                       JOIN users u ON u.id=p.user_id WHERE p.action_id=? ORDER BY u.display_name""",
                    (a["id"],),
                )]
                a["assignee_ids"] = _action_assignee_ids(db, action)
                a["assignees"] = _named_users(db, a["assignee_ids"])
                a["checklists"] = [dict(row) for row in db.execute("SELECT * FROM major_task_checklists WHERE action_id=? AND is_active=1 ORDER BY display_order,created_at", (a["id"],))]
                for checklist in a["checklists"]:
                    checklist["permissions"] = {"edit": action_edit, "deactivate": item["permissions"]["structure"]}
                a["balls"] = [dict(row) for row in db.execute("SELECT * FROM major_task_balls WHERE action_id=? ORDER BY is_active DESC,created_at DESC", (a["id"],))]
                for ball in a["balls"]:
                    ball["ball_type"] = BALL_CANONICAL_TYPES.get(ball["owner_type"], "external")
                    ball["permissions"] = {"edit": _can_ball(db, ball, g.current_user)}
                m["actions"].append(a)
            m["balls"] = [dict(row) for row in db.execute("SELECT * FROM major_task_balls WHERE milestone_id=? AND action_id IS NULL ORDER BY is_active DESC,created_at DESC", (m["id"],))]
            for ball in m["balls"]:
                ball["ball_type"] = BALL_CANONICAL_TYPES.get(ball["owner_type"], "external")
                ball["permissions"] = {"edit": _can_ball(db, ball, g.current_user)}
            item["milestones"].append(m)
        item["task_balls"] = [dict(row) for row in db.execute("SELECT * FROM major_task_balls WHERE task_id=? AND milestone_id IS NULL AND action_id IS NULL ORDER BY is_active DESC,created_at DESC", (task_id,))]
        for ball in item["task_balls"]:
            ball["ball_type"] = BALL_CANONICAL_TYPES.get(ball["owner_type"], "external")
            ball["permissions"] = {"edit": _can_ball(db, ball, g.current_user)}
        item["progress_updates"] = [dict(row) for row in db.execute(
            """SELECT p.*,u.display_name AS author_name FROM major_task_progress_updates p
               LEFT JOIN users u ON u.id=p.created_by WHERE p.task_id=? AND p.is_current=1
               ORDER BY p.update_date DESC,p.created_at DESC""", (task_id,)
        )]
        item["progress_revisions"] = [dict(row) for row in db.execute(
            """SELECT p.*,u.display_name AS author_name FROM major_task_progress_updates p
               LEFT JOIN users u ON u.id=p.created_by WHERE p.task_id=? AND p.is_current=0
               ORDER BY p.created_at DESC""", (task_id,)
        )]
        for progress in item["progress_updates"] + item["progress_revisions"]:
            try:
                parsed_changes = json.loads(progress.get("state_change_json") or "{}")
                progress["state_changes"] = parsed_changes if isinstance(parsed_changes, dict) else {}
            except (TypeError, json.JSONDecodeError):
                progress["state_changes"] = {}
        for progress in item["progress_updates"]:
            progress["permissions"] = {
                "revise": item["permissions"]["structure"] or (
                    g.current_user["role"] == "editor" and progress["created_by"] == g.current_user["id"]
                )
            }
        item["target_history"] = [dict(row) for row in db.execute(
            """SELECT h.*,u.display_name AS changed_by_name FROM major_task_target_history h
               LEFT JOIN users u ON u.id=h.changed_by WHERE h.task_id=? ORDER BY h.changed_at DESC""", (task_id,)
        )]
        item["ball_history"] = [dict(row) for row in db.execute(
            """SELECT h.*,b.owner_type,b.owner_detail
               FROM major_task_ball_history h
               JOIN major_task_balls b ON b.id=h.ball_id
               WHERE b.task_id=? ORDER BY h.changed_at DESC""",
            (task_id,),
        )]
        item["attachments"] = [dict(row) for row in db.execute("SELECT * FROM major_task_attachments WHERE task_id=? AND is_active=1 ORDER BY created_at DESC", (task_id,))]
        for attachment in item["attachments"]:
            attachment["permissions"] = {"deactivate": item["permissions"]["structure"]}
        item["audit"] = [dict(row) for row in db.execute(
            """SELECT * FROM audit_logs
               WHERE (entity_type='major_task' AND entity_id=?)
                  OR (entity_type='task' AND entity_id IN (
                        SELECT legacy_record_id FROM major_task_legacy_mappings WHERE task_id=?
                     ))
               ORDER BY occurred_at DESC LIMIT 200""",
            (task_id, task_id),
        )]
        item["stage_work_items"] = stage_work.detail_items(db, task_id, _today())
        item["work_item_contacts"] = stage_work.contacts(db, task)
        return jsonify(task=item)

    @app.patch("/api/major-tasks/<task_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_update(task_id):
        db = get_db(); existing = _task_row(db, task_id); data = request.get_json(silent=True) or {}
        if not existing:
            return jsonify(error="주요업무를 찾을 수 없습니다."), 404
        if not _can_structure(db, existing, g.current_user):
            return jsonify(error="주요업무 구조를 수정할 권한이 없습니다."), 403
        try:
            expected = _version(data); values = _validate_task_input(db, data, existing)
            stage_pipeline = _validate_stage_pipeline_input(db, data, task_id) if "stages" in data else None
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        before = _serialize_task(db, existing, include_relations=True)
        people_before = _task_people_snapshot(db, existing)
        section_before = {
            "section_id": existing["section_id"],
            "section_name": existing["section_name"],
            "effective": _root_section(db, task_id),
        }
        now = _now(); columns = list(values)
        cursor = db.execute(
            f"UPDATE major_tasks SET {','.join(f'{key}=?' for key in columns)},updated_by=?,updated_at=?,recent_updated_at=?,version=version+1 WHERE id=? AND version=?",
            (*[values[key] for key in columns], g.current_user["id"], now, now, task_id, expected),
        )
        if cursor.rowcount != 1:
            db.rollback(); return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.", code="VERSION_CONFLICT"), 409
        try:
            _replace_task_relations(db, task_id, data, now, g.current_user["id"])
            db.execute("UPDATE major_task_business_links SET is_primary=0 WHERE task_id=?", (task_id,))
            db.execute(
                """INSERT INTO major_task_business_links(task_id,business_unit,business_subcategory,is_primary,created_at)
                   VALUES (?,?,?,?,?) ON CONFLICT(task_id,business_unit,business_subcategory) DO UPDATE SET is_primary=1""",
                (task_id, values["primary_business_unit"], values["primary_business_subcategory"], 1, now),
            )
            if values["current_target_date"] != existing["current_target_date"]:
                db.execute(
                    """INSERT INTO major_task_target_history
                       (id,task_id,previous_target_date,new_target_date,change_reason,changed_by,changed_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (uuid.uuid4().hex, task_id, existing["current_target_date"], values["current_target_date"],
                     values["target_change_reason"], g.current_user["id"], now),
                )
            pipeline_before = pipeline_after = None
            if stage_pipeline is not None:
                pipeline_before, pipeline_after = _apply_stage_pipeline(
                    db, task_id, stage_pipeline[0], stage_pipeline[1], g.current_user["id"], now
                )
            _refresh_rag(db, task_id)
            updated_row = _task_row(db, task_id)
            after = _serialize_task(db, updated_row, True, g.current_user, True)
            people_after = _task_people_snapshot(db, updated_row)
            section_after = {
                "section_id": updated_row["section_id"],
                "section_name": updated_row["section_name"],
                "effective": _root_section(db, task_id),
            }
            _audit(audit_fn, "MAJOR_TASK_UPDATE", "major_task", task_id, f"{after['title']} 주요업무 수정", before, after)
            if section_before != section_after:
                _audit(
                    audit_fn, "TASK_SECTION_CHANGE", "major_task", task_id,
                    f"{after['title']} Section 변경", section_before, section_after,
                )
            if people_before != people_after:
                _audit(
                    audit_fn, "MAJOR_TASK_PEOPLE_CHANGE", "major_task", task_id,
                    f"{after['title']} 책임자·참여자·협조자 변경", people_before, people_after,
                )
            if pipeline_before != pipeline_after:
                _audit(audit_fn, "MAJOR_TASK_STAGE_PIPELINE_UPDATE", "major_task", task_id,
                       f"{after['title']} Stage Pipeline 수정", pipeline_before, pipeline_after)
            db.commit()
        except ValueError as exc:
            db.rollback()
            return jsonify(error=str(exc)), 400
        except Exception:
            db.rollback(); raise
        return jsonify(message="주요업무가 수정되었습니다.", task=after)

    @app.post("/api/major-tasks/<task_id>/stages")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_stage_create(task_id):
        db = get_db(); task = _task_row(db, task_id); data = request.get_json(silent=True) or {}
        if not task:
            return jsonify(error="주요업무를 찾을 수 없습니다."), 404
        if not _can_structure(db, task, g.current_user):
            return jsonify(error="Stage를 추가할 권한이 없습니다."), 403
        try:
            values = _validate_stage_input(db, data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        assignee_ids = values.pop("_assignee_ids")
        if "display_order" not in data:
            values["display_order"] = db.execute(
                "SELECT COALESCE(MAX(display_order),0)+1 FROM major_task_stages WHERE task_id=?",
                (task_id,),
            ).fetchone()[0]
        stage_id = uuid.uuid4().hex; now = _now(); columns = list(values)
        db.execute(
            f"INSERT INTO major_task_stages(id,task_id,{','.join(columns)},is_active,version,created_by,updated_by,created_at,updated_at) "
            f"VALUES (?,?{',?' * len(columns)},1,1,?,?,?,?)",
            (stage_id, task_id, *[values[key] for key in columns], g.current_user["id"], g.current_user["id"], now, now),
        )
        if assignee_ids is None:
            assignee_ids = [values["owner_id"]] if values["owner_id"] is not None else []
        _replace_stage_people(db, stage_id, assignee_ids, g.current_user["id"], now)
        if _bool(data.get("is_current")):
            if values["status"] == "completed":
                db.rollback(); return jsonify(error="완료된 Stage를 Current Stage로 지정할 수 없습니다."), 400
            db.execute(
                "UPDATE major_task_stages SET status='planned' WHERE task_id=? AND id<>? AND status='active' AND is_active=1",
                (task_id, stage_id),
            )
            db.execute("UPDATE major_task_stages SET status='active',started_at=COALESCE(started_at,?) WHERE id=?", (_today().isoformat(), stage_id))
            db.execute("UPDATE major_tasks SET current_stage_id=? WHERE id=?", (stage_id, task_id))
        _touch_task(db, task_id, g.current_user["id"], now)
        created = _serialize_stage(
            db.execute("SELECT * FROM major_task_stages WHERE id=?", (stage_id,)).fetchone(),
            stage_id if _bool(data.get("is_current")) else None,
            db,
        )
        _audit(audit_fn, "MAJOR_TASK_STAGE_CREATE", "major_task", task_id, f"{created['name']} Stage 추가", None, created)
        db.commit()
        return jsonify(message="Stage가 추가되었습니다.", stage=created), 201

    @app.patch("/api/major-task-stages/<stage_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_stage_update(stage_id):
        db = get_db(); stage = db.execute("SELECT * FROM major_task_stages WHERE id=?", (stage_id,)).fetchone(); data = request.get_json(silent=True) or {}
        if not stage:
            return jsonify(error="Stage를 찾을 수 없습니다."), 404
        task = _task_row(db, stage["task_id"])
        if not _can_structure(db, task, g.current_user):
            return jsonify(error="Stage를 수정할 권한이 없습니다."), 403
        try:
            expected = _version(data); values = _validate_stage_input(db, data, stage)
            if values["status"] == "inactive" and stage_work.stage_has_work(db, stage_id):
                raise ValueError("세부업무 이력이 있는 Stage는 삭제할 수 없습니다.")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        assignee_ids = values.pop("_assignee_ids")
        make_current = _bool(data.get("is_current"))
        if make_current and (not stage["is_active"] or values["status"] == "completed"):
            return jsonify(error="활성 상태의 미완료 Stage만 Current Stage로 지정할 수 있습니다."), 400
        before = _serialize_stage(stage, task["current_stage_id"], db); now = _now(); columns = list(values)
        cursor = db.execute(
            f"UPDATE major_task_stages SET {','.join(f'{key}=?' for key in columns)},updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",
            (*[values[key] for key in columns], g.current_user["id"], now, stage_id, expected),
        )
        if cursor.rowcount != 1:
            db.rollback(); return jsonify(error="다른 사용자가 이 Stage를 수정했습니다. 새로고침 후 다시 확인하세요.", code="VERSION_CONFLICT"), 409
        if make_current:
            db.execute(
                "UPDATE major_task_stages SET status='planned' WHERE task_id=? AND id<>? AND status='active' AND is_active=1",
                (stage["task_id"], stage_id),
            )
            db.execute("UPDATE major_task_stages SET status='active',started_at=COALESCE(started_at,?) WHERE id=?", (_today().isoformat(), stage_id))
            db.execute("UPDATE major_tasks SET current_stage_id=? WHERE id=?", (stage_id, stage["task_id"]))
        elif values["status"] == "completed" and task["current_stage_id"] == stage_id:
            db.execute("UPDATE major_tasks SET current_stage_id=NULL WHERE id=?", (stage["task_id"],))
        if assignee_ids is not None:
            _replace_stage_people(db, stage_id, assignee_ids, g.current_user["id"], now)
        _touch_task(db, stage["task_id"], g.current_user["id"], now)
        current = db.execute("SELECT current_stage_id FROM major_tasks WHERE id=?", (stage["task_id"],)).fetchone()
        after = _serialize_stage(
            db.execute("SELECT * FROM major_task_stages WHERE id=?", (stage_id,)).fetchone(),
            current["current_stage_id"] if current else None,
            db,
        )
        if not before["completed_at"] and after["completed_at"]:
            audit_action, audit_summary = "MAJOR_TASK_STAGE_COMPLETE", f"{after['name']} Stage 완료"
        elif before["completed_at"] and not after["completed_at"]:
            audit_action, audit_summary = "MAJOR_TASK_STAGE_REOPEN", f"{after['name']} Stage 완료 취소"
        else:
            audit_action, audit_summary = "MAJOR_TASK_STAGE_UPDATE", f"{after['name']} Stage 수정"
        _audit(audit_fn, audit_action, "major_task", stage["task_id"], audit_summary, before, after)
        db.commit()
        return jsonify(message="Stage가 수정되었습니다.", stage=after)

    @app.post("/api/major-task-stages/<stage_id>/deactivate")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_stage_deactivate(stage_id):
        db = get_db(); stage = db.execute("SELECT * FROM major_task_stages WHERE id=? AND is_active=1", (stage_id,)).fetchone(); data = request.get_json(silent=True) or {}
        if not stage:
            return jsonify(error="활성 Stage를 찾을 수 없습니다."), 404
        task = _task_row(db, stage["task_id"])
        if not _can_structure(db, task, g.current_user):
            return jsonify(error="Stage를 종료할 권한이 없습니다."), 403
        if stage_work.stage_has_work(db, stage_id):
            return jsonify(error="세부업무 이력이 있는 Stage는 삭제할 수 없습니다.", code="STAGE_HAS_WORK_ITEMS"), 409
        try:
            expected = _version(data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        now = _now(); before = dict(stage)
        cursor = db.execute(
            """UPDATE major_task_stages SET is_active=0,status='inactive',updated_by=?,updated_at=?,version=version+1
               WHERE id=? AND version=?""",
            (g.current_user["id"], now, stage_id, expected),
        )
        if cursor.rowcount != 1:
            db.rollback(); return jsonify(error="다른 사용자가 이 Stage를 수정했습니다. 새로고침 후 다시 확인하세요.", code="VERSION_CONFLICT"), 409
        if task["current_stage_id"] == stage_id:
            db.execute("UPDATE major_tasks SET current_stage_id=NULL WHERE id=?", (stage["task_id"],))
        _touch_task(db, stage["task_id"], g.current_user["id"], now)
        after = dict(db.execute("SELECT * FROM major_task_stages WHERE id=?", (stage_id,)).fetchone())
        _audit(audit_fn, "MAJOR_TASK_STAGE_DEACTIVATE", "major_task", stage["task_id"], f"{stage['name']} Stage 종료", before, after)
        db.commit()
        return jsonify(message="Stage가 이력 보존 상태로 종료되었습니다.", stage=after)

    @app.put("/api/major-tasks/<task_id>/stages/reorder")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_stage_reorder(task_id):
        db = get_db(); task = _task_row(db, task_id); data = request.get_json(silent=True) or {}
        if not task:
            return jsonify(error="주요업무를 찾을 수 없습니다."), 404
        if not _can_structure(db, task, g.current_user):
            return jsonify(error="Stage 순서를 변경할 권한이 없습니다."), 403
        try:
            expected = _version(data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        ordered_ids = [_clean(value, 32) for value in data.get("ordered_ids", []) if _clean(value, 32)]
        current_ids = [row["id"] for row in db.execute(
            "SELECT id FROM major_task_stages WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at", (task_id,)
        )]
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(current_ids):
            return jsonify(error="활성 Stage 전체를 중복 없이 순서대로 보내세요."), 400
        now = _now(); before = current_ids
        cursor = db.execute(
            "UPDATE major_tasks SET recent_updated_at=?,updated_at=?,updated_by=?,version=version+1 WHERE id=? AND version=?",
            (now, now, g.current_user["id"], task_id, expected),
        )
        if cursor.rowcount != 1:
            db.rollback(); return jsonify(error="다른 사용자가 이 업무를 수정했습니다. 새로고침 후 다시 확인하세요.", code="VERSION_CONFLICT"), 409
        for order, value in enumerate(ordered_ids, start=1):
            db.execute("UPDATE major_task_stages SET display_order=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?", (order, g.current_user["id"], now, value))
        _audit(audit_fn, "MAJOR_TASK_STAGE_REORDER", "major_task", task_id, f"{task['title']} Stage 순서 변경", before, ordered_ids)
        db.commit()
        return jsonify(message="Stage 순서가 변경되었습니다.", ordered_ids=ordered_ids)

    @app.post("/api/major-tasks/<task_id>/cancel")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_cancel(task_id):
        db = get_db(); task = _task_row(db, task_id); data = request.get_json(silent=True) or {}
        if not task: return jsonify(error="주요업무를 찾을 수 없습니다."), 404
        if not _can_structure(db, task, g.current_user): return jsonify(error="취소 권한이 없습니다."), 403
        reason = _clean(data.get("reason"), 1000)
        if not reason: return jsonify(error="취소 사유를 입력하세요."), 400
        try: expected = _version(data)
        except ValueError as exc: return jsonify(error=str(exc)), 400
        before = dict(task); now = _now()
        cursor = db.execute("UPDATE major_tasks SET status='cancelled',cancel_reason=?,archived_at=?,updated_by=?,updated_at=?,recent_updated_at=?,version=version+1 WHERE id=? AND version=?", (reason, now, g.current_user["id"], now, now, task_id, expected))
        if cursor.rowcount != 1: db.rollback(); return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.", code="VERSION_CONFLICT"), 409
        _refresh_rag(db, task_id); after = dict(_task_row(db, task_id)); _audit(audit_fn, "MAJOR_TASK_CANCEL", "major_task", task_id, f"{task['title']} 취소", before, after); db.commit()
        return jsonify(message="취소된 업무가 아카이브로 이동했습니다.")

    @app.post("/api/major-tasks/<task_id>/restore")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_restore(task_id):
        db = get_db(); task = _task_row(db, task_id); data = request.get_json(silent=True) or {}
        if not task or task["status"] != "cancelled": return jsonify(error="복원할 취소업무를 찾을 수 없습니다."), 404
        if not _can_structure(db, task, g.current_user): return jsonify(error="복원 권한이 없습니다."), 403
        reason = _clean(data.get("reason"), 1000); status = _clean(data.get("status"), 40); target = _date(data.get("current_target_date"), "새 목표완료일")
        if not reason or status not in TASK_STATUSES - {"completed", "cancelled"} or not target: return jsonify(error="복원 사유·복원 상태·새 목표완료일을 입력하세요."), 400
        try: expected = _version(data)
        except ValueError as exc: return jsonify(error=str(exc)), 400
        change_owner = _bool(data.get("change_owner"))
        owner = _int(data.get("owner_id")) if change_owner else task["owner_id"]
        if not _user_exists(db, owner): return jsonify(error="담당자를 찾을 수 없습니다."), 400
        next_action = _clean(data.get("next_action", task["next_action"]), 1000)
        next_action_date = _date(data.get("next_action_date", task["next_action_date"]), "다음 액션 기한")
        cooperation_department = _clean(data.get("cooperation_department", task["cooperation_department"]), 200)
        cooperation_request = _clean(data.get("cooperation_request", task["cooperation_request"]), 1000)
        next_check_date = _date(data.get("next_check_date", task["next_check_date"]), "확인일")
        hold_reason = _clean(data.get("hold_reason", task["hold_reason"]), 1000)
        review_date = _date(data.get("review_date", task["review_date"]), "재검토일")
        if status == "internal_work" and (not next_action or not next_action_date):
            return jsonify(error="내부작업으로 복원하려면 다음 액션과 기한을 입력하세요."), 400
        if status == "external_wait" and not db.execute(
            """SELECT 1 FROM major_task_balls WHERE task_id=? AND is_active=1 AND resolved_at IS NULL
               AND owner_type IN ('executive','department','buyer','external_agency','logistics')
               AND follow_up_date IS NOT NULL LIMIT 1""", (task_id,)
        ).fetchone():
            return jsonify(error="외부대기로 복원하려면 활성 Ball 소유자와 Follow-up Date가 필요합니다."), 400
        if status == "cooperation_wait" and (not cooperation_department or not cooperation_request or not next_check_date):
            return jsonify(error="협조대기로 복원하려면 협조부서·요청내용·확인일을 입력하세요."), 400
        if status == "hold" and (not hold_reason or not review_date):
            return jsonify(error="보류로 복원하려면 보류 사유와 재검토일을 입력하세요."), 400
        before = dict(task); now = _now()
        cursor = db.execute(
            """UPDATE major_tasks SET status=?,current_target_date=?,target_change_reason=?,owner_id=?,
                      next_action=?,next_action_date=?,cooperation_department=?,cooperation_request=?,next_check_date=?,
                      hold_reason=?,review_date=?,cancel_reason='',archived_at=NULL,updated_by=?,updated_at=?,
                      recent_updated_at=?,version=version+1 WHERE id=? AND version=?""",
            (status,target,reason,owner,next_action,next_action_date,cooperation_department,cooperation_request,
             next_check_date,hold_reason,review_date,g.current_user["id"],now,now,task_id,expected),
        )
        if cursor.rowcount != 1: db.rollback(); return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.", code="VERSION_CONFLICT"), 409
        if target != task["current_target_date"]:
            db.execute(
                """INSERT INTO major_task_target_history
                   (id,task_id,previous_target_date,new_target_date,change_reason,changed_by,changed_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex,task_id,task["current_target_date"],target,f"복원: {reason}",g.current_user["id"],now),
            )
        _refresh_rag(db, task_id); after = dict(_task_row(db, task_id)); _audit(audit_fn, "MAJOR_TASK_RESTORE", "major_task", task_id, f"{task['title']} 복원", before, after); db.commit()
        return jsonify(message="주요업무가 복원되었습니다.")

    @app.post("/api/major-tasks/<task_id>/complete")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_complete(task_id):
        db = get_db(); task = _task_row(db, task_id); data = request.get_json(silent=True) or {}
        if not task: return jsonify(error="주요업무를 찾을 수 없습니다."), 404
        if not _can_structure(db, task, g.current_user): return jsonify(error="완료 권한이 없습니다."), 403
        incomplete = [dict(row) for row in db.execute(
            """SELECT 'milestone' AS item_type,id,name FROM major_task_milestones WHERE task_id=? AND is_active=1 AND is_required=1 AND status<>'completed'
               UNION ALL SELECT 'action',a.id,a.name FROM major_task_actions a
               JOIN major_task_milestones m ON m.id=a.milestone_id
               WHERE a.task_id=? AND a.is_active=1 AND m.is_active=1 AND m.is_required=1
                 AND a.is_required=1 AND a.status<>'completed'""", (task_id, task_id)
        )]
        exception = _clean(data.get("exception_reason"), 1000)
        if incomplete and not exception: return jsonify(error="필수 마일스톤·실행항목이 남아 있습니다. 예외 완료 사유를 입력하세요.", incomplete=incomplete), 400
        result = _clean(data.get("final_result"), 3000); completed_at = _date(data.get("actual_completion_date"), "실제 완료일")
        if not result or not completed_at: return jsonify(error="최종 결과와 실제 완료일을 입력하세요."), 400
        try: expected = _version(data)
        except ValueError as exc: return jsonify(error=str(exc)), 400
        before = dict(task); now = _now()
        cursor = db.execute("""UPDATE major_tasks SET status='completed',final_result=?,final_deliverable=?,actual_completion_date=?,major_risks=?,resolution=?,future_notes=?,final_report=?,completion_exception_reason=?,archived_at=?,updated_by=?,updated_at=?,recent_updated_at=?,version=version+1 WHERE id=? AND version=?""",
            (result,_clean(data.get("final_deliverable"),3000),completed_at,_clean(data.get("major_risks"),3000),_clean(data.get("resolution"),3000),_clean(data.get("future_notes"),3000),_clean(data.get("final_report"),3000),exception,now,g.current_user["id"],now,now,task_id,expected))
        if cursor.rowcount != 1: db.rollback(); return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.", code="VERSION_CONFLICT"), 409
        _refresh_rag(db, task_id); after = dict(_task_row(db, task_id)); _audit(audit_fn,"MAJOR_TASK_COMPLETE","major_task",task_id,f"{task['title']} 완료",before,after); db.commit()
        return jsonify(message="완료업무가 아카이브로 이동했습니다.")

    @app.post("/api/major-tasks/<task_id>/copy")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_copy(task_id):
        db = get_db(); source = _task_row(db, task_id); data = request.get_json(silent=True) or {}
        if not source:
            return jsonify(error="복사할 주요업무를 찾을 수 없습니다."), 404
        if not _can_structure(db, source, g.current_user):
            return jsonify(error="주요업무 복사 권한이 없습니다."), 403
        copy_data = {key: source[key] for key in (
            "primary_business_unit","primary_business_subcategory","workstream_id","section_id","region","country",
            "customer_master_id","legacy_customer_name","product_name","product_code","purpose","completion_criteria",
            "owner_id","deputy_owner_id","importance","start_date","original_target_date","current_target_date",
            "hard_deadline_enabled","hard_deadline_date","review_cycle_days_override",
            "due_soon_days_override","hard_deadline_soon_days_override","notes"
        )}
        copy_data.update({
            "title": _clean(data.get("title") or f"{source['title']} 복사본", 200),
            "status": "not_started", "ceo_directive": False, "directive_date": None,
            "manual_rag": None, "manual_rag_reason": "",
            "additional_owner_ids": _task_additional_owner_ids(db, source),
        })
        for key in (
            "primary_business_unit", "primary_business_subcategory", "owner_id", "primary_owner_id",
            "deputy_owner_id", "additional_owner_ids", "start_date", "original_target_date",
            "current_target_date", "hard_deadline_enabled", "hard_deadline_date",
            "section_id",
        ):
            if key in data:
                copy_data[key] = data[key]
        copy_data["business_links"] = [dict(row) for row in db.execute(
            """SELECT business_unit,business_subcategory FROM major_task_business_links
               WHERE task_id=? AND is_primary=0""", (task_id,)
        )]
        copy_data["people"] = [dict(row) for row in db.execute(
            "SELECT user_id,relation_type FROM major_task_people WHERE task_id=?", (task_id,)
        )]
        copy_data["products"] = [dict(row) for row in db.execute(
            "SELECT product_code,product_name,source_type FROM major_task_products WHERE task_id=?", (task_id,)
        )]
        try:
            values = _validate_task_input(db, copy_data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if values["owner_id"] is None:
            values["owner_id"] = g.current_user["id"]
        new_id = uuid.uuid4().hex; now = _now(); columns = list(values)
        db.execute(
            f"INSERT INTO major_tasks(id,{','.join(columns)},auto_rag,final_rag,recent_updated_at,version,created_by,updated_by,created_at,updated_at) VALUES (?{',?'*len(columns)},'green','green',?,1,?,?,?,?)",
            (new_id, *[values[key] for key in columns], now, g.current_user["id"], g.current_user["id"], now, now),
        )
        _replace_task_relations(db, new_id, copy_data, now, g.current_user["id"])
        db.execute(
            """INSERT OR IGNORE INTO major_task_business_links
               (task_id,business_unit,business_subcategory,is_primary,created_at) VALUES (?,?,?,?,?)""",
            (new_id, values["primary_business_unit"], values["primary_business_subcategory"], 1, now),
        )
        counts = _copy_task_structure(db, task_id, new_id, g.current_user["id"], now)
        _refresh_rag(db, new_id)
        created = _serialize_task(db, _task_row(db, new_id), True, g.current_user, True)
        _audit(audit_fn, "MAJOR_TASK_COPY", "major_task", new_id,
               f"{source['title']}에서 새 주요업무 복사", {"source_task_id": task_id},
               {"task": created, "structure": counts})
        db.commit()
        return jsonify(message="새 주요업무로 복사했습니다.", task=created, structure=counts), 201

    @app.post("/api/major-tasks/<task_id>/progress")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_add_progress(task_id):
        db=get_db(); task=_task_row(db,task_id); data=request.get_json(silent=True) or {}
        if not task: return jsonify(error="주요업무를 찾을 수 없습니다."),404
        if not _can_progress(db,task,g.current_user): return jsonify(error="진행이력을 추가할 권한이 없습니다."),403
        state_change_requested = bool(
            _clean(data.get("stage_id"),32) or _clean(data.get("rag_value"),10)
            or ("ball_type" in data and data.get("ball_type") not in (None,""))
        )
        canonical_change_requested = state_change_requested or bool(_clean(data.get("next_action"),1000))
        if state_change_requested and not _can_structure(db,task,g.current_user):
            return jsonify(error="Stage·RAG·Ball 변경은 업무 구조 수정 권한이 필요합니다."),403
        if canonical_change_requested:
            try: expected_task_version = _int(data.get("task_version"))
            except ValueError as exc: return jsonify(error=str(exc)),400
            if expected_task_version is None:
                return jsonify(error="현재 업무 버전을 다시 불러오세요."),400
            lock = db.execute(
                "UPDATE major_tasks SET version=version WHERE id=? AND version=?",
                (task_id, expected_task_version),
            )
            if lock.rowcount != 1:
                db.rollback()
                return jsonify(
                    error="다른 사용자가 이 업무를 수정했습니다. 새로고침 후 다시 확인하세요.",
                    code="VERSION_CONFLICT",
                ),409
        text=_clean(data.get("progress_text"),5000); update_date=_date(data.get("update_date") or _today().isoformat(),"업데이트일")
        if not text: return jsonify(error="진행한 내용을 입력하세요."),400
        try:
            progress_next_action_date = _date(data.get("next_action_date"),"다음 액션 기한")
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        milestone_id=_clean(data.get("milestone_id"),32) or None; action_id=_clean(data.get("action_id"),32) or None
        if milestone_id and not db.execute("SELECT 1 FROM major_task_milestones WHERE id=? AND task_id=?",(milestone_id,task_id)).fetchone(): return jsonify(error="마일스톤 연결이 올바르지 않습니다."),400
        if action_id and not db.execute("SELECT 1 FROM major_task_actions WHERE id=? AND task_id=?",(action_id,task_id)).fetchone(): return jsonify(error="실행항목 연결이 올바르지 않습니다."),400
        update_id=uuid.uuid4().hex; now=_now()
        try:
            applied = _apply_progress_state_changes(db,task,data,g.current_user["id"],now,audit_fn)
        except ValueError as exc:
            db.rollback(); return jsonify(error=str(exc)),400
        db.execute("""INSERT INTO major_task_progress_updates
          (id,task_id,milestone_id,action_id,update_date,progress_text,result_text,risk_text,next_action,next_action_date,
           decision_needed,cooperation_needed,attachment_note,applied_stage_id,applied_ball_id,applied_rag,state_change_json,
           is_current,version,created_by,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,?,?)""",
          (update_id,task_id,milestone_id,action_id,update_date,text,_clean(data.get("result_text"),3000),_clean(data.get("risk_text"),3000),_clean(data.get("next_action"),1000),progress_next_action_date,_clean(data.get("decision_needed"),2000),_clean(data.get("cooperation_needed"),2000),_clean(data.get("attachment_note"),1000),applied["applied_stage_id"],applied["applied_ball_id"],applied["applied_rag"],applied["state_change_json"],g.current_user["id"],now))
        _touch_task(db,task_id,g.current_user["id"],now); _refresh_rag(db,task_id)
        created=dict(db.execute("SELECT * FROM major_task_progress_updates WHERE id=?",(update_id,)).fetchone()); _audit(audit_fn,"MAJOR_TASK_PROGRESS_CREATE","major_task",task_id,f"{task['title']} 진행이력 추가",None,created); db.commit()
        return jsonify(message="진행이력이 추가되었습니다.",progress=created),201

    @app.post("/api/major-task-progress/<progress_id>/revise")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_revise_progress(progress_id):
        db=get_db();current=db.execute("SELECT * FROM major_task_progress_updates WHERE id=? AND is_current=1",(progress_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not current:return jsonify(error="수정할 진행이력을 찾을 수 없습니다."),404
        task=_task_row(db,current["task_id"])
        if not (
            _can_structure(db, task, g.current_user)
            or (g.current_user["role"] == "editor" and current["created_by"] == g.current_user["id"])
        ):return jsonify(error="자신이 작성한 진행이력만 수정할 수 있습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        reason=_clean(data.get("revision_reason"),1000)
        if not reason:return jsonify(error="진행이력 수정 사유를 입력하세요."),400
        text=_clean(data.get("progress_text",current["progress_text"]),5000)
        if not text:return jsonify(error="진행한 내용을 입력하세요."),400
        now=_now();new_id=uuid.uuid4().hex;root_id=current["original_update_id"] or current["id"]
        cursor=db.execute("UPDATE major_task_progress_updates SET is_current=0,version=version+1 WHERE id=? AND version=?",(progress_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        db.execute("""INSERT INTO major_task_progress_updates
          (id,task_id,milestone_id,action_id,update_date,progress_text,result_text,risk_text,next_action,next_action_date,
           decision_needed,cooperation_needed,attachment_note,applied_stage_id,applied_ball_id,applied_rag,state_change_json,
           original_update_id,revision_reason,is_current,version,created_by,created_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,?,?)""",
          (new_id,current["task_id"],current["milestone_id"],current["action_id"],_date(data.get("update_date",current["update_date"]),"업데이트일"),text,_clean(data.get("result_text",current["result_text"]),3000),_clean(data.get("risk_text",current["risk_text"]),3000),_clean(data.get("next_action",current["next_action"]),1000),_date(data.get("next_action_date",current["next_action_date"]),"다음 액션 기한"),_clean(data.get("decision_needed",current["decision_needed"]),2000),_clean(data.get("cooperation_needed",current["cooperation_needed"]),2000),_clean(data.get("attachment_note",current["attachment_note"]),1000),current["applied_stage_id"],current["applied_ball_id"],current["applied_rag"],current["state_change_json"],root_id,reason,g.current_user["id"],now))
        revised=dict(db.execute("SELECT * FROM major_task_progress_updates WHERE id=?",(new_id,)).fetchone());_touch_task(db,current["task_id"],g.current_user["id"],now);_audit(audit_fn,"MAJOR_TASK_PROGRESS_REVISE","major_task",current["task_id"],f"{task['title']} 진행이력 수정",dict(current),revised);db.commit();return jsonify(message="원문을 보존하고 진행이력을 수정했습니다.",progress=revised),201

    @app.post("/api/major-tasks/<task_id>/attachments")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_attachment_create(task_id):
        db=get_db();task=_task_row(db,task_id);data=request.get_json(silent=True) or {}
        if not task:return jsonify(error="주요업무를 찾을 수 없습니다."),404
        label=_clean(data.get("label"),300);external_url=_clean(data.get("external_url"),2000)
        if not label or not re.match(r"^https?://",external_url,re.I):return jsonify(error="첨부자료명과 http(s) 외부 링크를 입력하세요."),400
        milestone_id=_clean(data.get("milestone_id"),32) or None;action_id=_clean(data.get("action_id"),32) or None;progress_id=_clean(data.get("progress_update_id"),32) or None
        milestone=db.execute("SELECT * FROM major_task_milestones WHERE id=? AND task_id=? AND is_active=1",(milestone_id,task_id)).fetchone() if milestone_id else None
        action=db.execute("SELECT * FROM major_task_actions WHERE id=? AND task_id=? AND is_active=1",(action_id,task_id)).fetchone() if action_id else None
        progress=db.execute("SELECT * FROM major_task_progress_updates WHERE id=? AND task_id=?",(progress_id,task_id)).fetchone() if progress_id else None
        if milestone_id and not milestone:return jsonify(error="첨부할 마일스톤이 올바르지 않습니다."),400
        if action_id and not action:return jsonify(error="첨부할 실행항목이 올바르지 않습니다."),400
        if progress_id and not progress:return jsonify(error="첨부할 진행이력이 올바르지 않습니다."),400
        if not _can_attachment(db,task,g.current_user,milestone,action,progress):return jsonify(error="첨부자료 등록 권한이 없습니다."),403
        attachment_id=uuid.uuid4().hex;now=_now();db.execute("""INSERT INTO major_task_attachments
          (id,task_id,milestone_id,action_id,progress_update_id,label,external_url,notes,is_active,version,created_by,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,1,1,?,?,?)""",
          (attachment_id,task_id,milestone_id,action_id,progress_id,label,external_url,_clean(data.get("notes"),1000),g.current_user["id"],now,now));created=dict(db.execute("SELECT * FROM major_task_attachments WHERE id=?",(attachment_id,)).fetchone());_touch_task(db,task_id,g.current_user["id"],now);_audit(audit_fn,"MAJOR_TASK_ATTACHMENT_CREATE","major_task",task_id,f"{label} 첨부 링크 등록",None,created);db.commit();return jsonify(message="외부 첨부 링크가 등록되었습니다.",attachment=created),201

    @app.post("/api/major-task-attachments/<attachment_id>/deactivate")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def major_task_attachment_deactivate(attachment_id):
        db=get_db();row=db.execute("SELECT * FROM major_task_attachments WHERE id=? AND is_active=1",(attachment_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="첨부자료를 찾을 수 없습니다."),404
        task=_task_row(db,row["task_id"])
        if not _can_structure(db,task,g.current_user):return jsonify(error="첨부자료 비활성화 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        now=_now();cursor=db.execute("UPDATE major_task_attachments SET is_active=0,version=version+1,updated_at=? WHERE id=? AND version=?",(now,attachment_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _touch_task(db,row["task_id"],g.current_user["id"],now);_audit(audit_fn,"MAJOR_TASK_ATTACHMENT_DEACTIVATE","major_task",row["task_id"],f"{row['label']} 첨부 링크 비활성화",dict(row),{"is_active":0});db.commit();return jsonify(message="첨부 링크가 비활성화되었습니다.")

    @app.post("/api/major-tasks/<task_id>/milestones")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def milestone_create(task_id):
        db=get_db(); task=_task_row(db,task_id); data=request.get_json(silent=True) or {}
        if not task:return jsonify(error="주요업무를 찾을 수 없습니다."),404
        if not _can_structure(db,task,g.current_user):return jsonify(error="마일스톤을 추가할 권한이 없습니다."),403
        name=_clean(data.get("name"),200)
        if not name:return jsonify(error="마일스톤명을 입력하세요."),400
        milestone_id=uuid.uuid4().hex;now=_now();status=_clean(data.get("status") or "not_started",30)
        if status not in ITEM_STATUSES:return jsonify(error="마일스톤 상태가 올바르지 않습니다."),400
        owner=_int(data.get("owner_id"));deputy=_int(data.get("deputy_owner_id"))
        if not _user_exists(db,owner) or not _user_exists(db,deputy):return jsonify(error="마일스톤 담당자를 찾을 수 없습니다."),400
        db.execute("""INSERT INTO major_task_milestones
          (id,task_id,name,description,planned_start_date,planned_end_date,actual_completion_date,owner_id,deputy_owner_id,status,is_required,result,attachment_note,display_order,started_with_override_reason,is_active,version,created_by,updated_by,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,?,?,?,?)""",
          (milestone_id,task_id,name,_clean(data.get("description"),2000),_date(data.get("planned_start_date"),"예정 시작일"),_date(data.get("planned_end_date"),"예정 완료일"),_date(data.get("actual_completion_date"),"실제 완료일"),owner,deputy,status,_bool(data.get("is_required",True)),_clean(data.get("result"),3000),_clean(data.get("attachment_note"),1000),_int(data.get("display_order"),0),_clean(data.get("override_reason"),1000),g.current_user["id"],g.current_user["id"],now,now))
        _touch_task(db,task_id,g.current_user["id"],now);_refresh_rag(db,task_id);created=dict(db.execute("SELECT * FROM major_task_milestones WHERE id=?",(milestone_id,)).fetchone());_audit(audit_fn,"MAJOR_TASK_MILESTONE_CREATE","major_task",task_id,f"{name} 마일스톤 추가",None,created);db.commit();return jsonify(message="마일스톤이 추가되었습니다.",milestone=created),201

    @app.patch("/api/major-task-milestones/<milestone_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def milestone_update(milestone_id):
        db=get_db();m=db.execute("SELECT * FROM major_task_milestones WHERE id=? AND is_active=1",(milestone_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not m:return jsonify(error="마일스톤을 찾을 수 없습니다."),404
        if not _can_milestone(db,m,g.current_user):return jsonify(error="마일스톤 수정 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        predecessors=[_clean(v,32) for v in data.get("predecessors",[]) if _clean(v,32)]
        if milestone_id in predecessors:return jsonify(error="자기 자신을 선행 마일스톤으로 지정할 수 없습니다."),400
        for pred in predecessors:
            row=db.execute("SELECT task_id,status,is_active FROM major_task_milestones WHERE id=?",(pred,)).fetchone()
            if not row or row["task_id"]!=m["task_id"]:return jsonify(error="같은 주요업무의 마일스톤만 연결할 수 있습니다."),400
            if not row["is_active"] or row["status"]=="cancelled":return jsonify(error="비활성화되거나 취소된 마일스톤은 선행항목으로 연결할 수 없습니다."),400
        if _dependency_cycle(db,"major_task_milestone_dependencies","milestone_id","predecessor_id",milestone_id,predecessors):return jsonify(error="마일스톤 선행관계가 순환합니다."),400
        status=_clean(data.get("status",m["status"]),30)
        if status not in ITEM_STATUSES:return jsonify(error="마일스톤 상태가 올바르지 않습니다."),400
        incomplete=[pred for pred in predecessors if db.execute("SELECT status FROM major_task_milestones WHERE id=?",(pred,)).fetchone()["status"]!="completed"]
        override=_clean(data.get("override_reason",m["started_with_override_reason"]),1000)
        if status=="in_progress" and incomplete and not override:return jsonify(error="선행 마일스톤이 미완료입니다. 시작 사유를 입력하세요."),400
        owner_id=_int(data.get("owner_id"),m["owner_id"]);deputy_owner_id=_int(data.get("deputy_owner_id"),m["deputy_owner_id"])
        if not _user_exists(db,owner_id) or not _user_exists(db,deputy_owner_id):return jsonify(error="마일스톤 담당자를 찾을 수 없습니다."),400
        now=_now();before=dict(m);cursor=db.execute("""UPDATE major_task_milestones SET name=?,description=?,planned_start_date=?,planned_end_date=?,actual_completion_date=?,owner_id=?,deputy_owner_id=?,status=?,is_required=?,result=?,attachment_note=?,display_order=?,started_with_override_reason=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?""",
          (_clean(data.get("name",m["name"]),200),_clean(data.get("description",m["description"]),2000),_date(data.get("planned_start_date",m["planned_start_date"]),"예정 시작일"),_date(data.get("planned_end_date",m["planned_end_date"]),"예정 완료일"),_date(data.get("actual_completion_date",m["actual_completion_date"]),"실제 완료일"),owner_id,deputy_owner_id,status,_bool(data.get("is_required",m["is_required"])),_clean(data.get("result",m["result"]),3000),_clean(data.get("attachment_note",m["attachment_note"]),1000),_int(data.get("display_order"),m["display_order"]),override,g.current_user["id"],now,milestone_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        db.execute("DELETE FROM major_task_milestone_dependencies WHERE milestone_id=?",(milestone_id,))
        for pred in predecessors:db.execute("INSERT INTO major_task_milestone_dependencies(milestone_id,predecessor_id,created_by,created_at) VALUES (?,?,?,?)",(milestone_id,pred,g.current_user["id"],now))
        _touch_task(db,m["task_id"],g.current_user["id"],now);_refresh_rag(db,m["task_id"]);after=dict(db.execute("SELECT * FROM major_task_milestones WHERE id=?",(milestone_id,)).fetchone());_audit(audit_fn,"MAJOR_TASK_MILESTONE_UPDATE","major_task",m["task_id"],f"{after['name']} 마일스톤 수정",before,after);db.commit();return jsonify(message="마일스톤이 수정되었습니다.",milestone=after)

    @app.post("/api/major-task-milestones/<milestone_id>/deactivate")
    @app.post("/api/major-task-milestones/<milestone_id>/restore")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def milestone_active_state(milestone_id):
        db=get_db();m=db.execute("SELECT * FROM major_task_milestones WHERE id=?",(milestone_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not m:return jsonify(error="마일스톤을 찾을 수 없습니다."),404
        if not _can_structure(db,_task_row(db,m["task_id"]),g.current_user):return jsonify(error="마일스톤 구조변경 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        active=0 if request.path.endswith("/deactivate") else 1
        now=_now();before=dict(m);cursor=db.execute("UPDATE major_task_milestones SET is_active=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",(active,g.current_user["id"],now,milestone_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _touch_task(db,m["task_id"],g.current_user["id"],now);_refresh_rag(db,m["task_id"]);after=dict(db.execute("SELECT * FROM major_task_milestones WHERE id=?",(milestone_id,)).fetchone());verb="복원" if active else "비활성화";_audit(audit_fn,f"MAJOR_TASK_MILESTONE_{'RESTORE' if active else 'DEACTIVATE'}","major_task",m["task_id"],f"{m['name']} 마일스톤 {verb}",before,after);db.commit();return jsonify(message=f"마일스톤이 {verb}되었습니다.",milestone=after)

    @app.post("/api/major-task-milestones/<milestone_id>/areas")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def area_create(milestone_id):
        db=get_db();m=db.execute("SELECT * FROM major_task_milestones WHERE id=? AND is_active=1",(milestone_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not m:return jsonify(error="마일스톤을 찾을 수 없습니다."),404
        if not _can_milestone(db,m,g.current_user):return jsonify(error="세부 실행영역 추가 권한이 없습니다."),403
        name=_clean(data.get("name"),200)
        if not name:return jsonify(error="세부 실행영역명을 입력하세요."),400
        area_id=uuid.uuid4().hex;now=_now();db.execute("INSERT INTO major_task_action_areas(id,milestone_id,name,description,display_order,is_active,version,created_by,updated_by,created_at,updated_at) VALUES (?,?,?,?,?,1,1,?,?,?,?)",(area_id,milestone_id,name,_clean(data.get("description"),1000),_int(data.get("display_order"),0),g.current_user["id"],g.current_user["id"],now,now));_touch_task(db,m["task_id"],g.current_user["id"],now);created=dict(db.execute("SELECT * FROM major_task_action_areas WHERE id=?",(area_id,)).fetchone());_audit(audit_fn,"MAJOR_TASK_AREA_CREATE","major_task",m["task_id"],f"{name} 실행영역 추가",None,created);db.commit();return jsonify(message="세부 실행영역이 추가되었습니다.",area=created),201

    @app.patch("/api/major-task-areas/<area_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def area_update(area_id):
        db=get_db();row=db.execute("""SELECT a.*,m.task_id,m.owner_id AS milestone_owner_id FROM major_task_action_areas a JOIN major_task_milestones m ON m.id=a.milestone_id WHERE a.id=? AND a.is_active=1""",(area_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="세부 실행영역을 찾을 수 없습니다."),404
        task=_task_row(db,row["task_id"])
        if not (_can_structure(db,task,g.current_user) or (g.current_user["role"]=="editor" and row["milestone_owner_id"]==g.current_user["id"])):return jsonify(error="세부 실행영역 수정 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        name=_clean(data.get("name",row["name"]),200)
        if not name:return jsonify(error="세부 실행영역명을 입력하세요."),400
        now=_now();before=dict(row);cursor=db.execute("UPDATE major_task_action_areas SET name=?,description=?,display_order=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",(name,_clean(data.get("description",row["description"]),1000),_int(data.get("display_order",row["display_order"]),row["display_order"]),g.current_user["id"],now,area_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _touch_task(db,row["task_id"],g.current_user["id"],now);after=dict(db.execute("SELECT * FROM major_task_action_areas WHERE id=?",(area_id,)).fetchone());_audit(audit_fn,"MAJOR_TASK_AREA_UPDATE","major_task",row["task_id"],f"{name} 실행영역 수정",before,after);db.commit();return jsonify(message="세부 실행영역이 수정되었습니다.",area=after)

    @app.post("/api/major-task-areas/<area_id>/deactivate")
    @app.post("/api/major-task-areas/<area_id>/restore")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def area_active_state(area_id):
        db=get_db();row=db.execute("""SELECT a.*,m.task_id FROM major_task_action_areas a JOIN major_task_milestones m ON m.id=a.milestone_id WHERE a.id=?""",(area_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="세부 실행영역을 찾을 수 없습니다."),404
        if not _can_structure(db,_task_row(db,row["task_id"]),g.current_user):return jsonify(error="세부 실행영역 구조변경 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        active=0 if request.path.endswith("/deactivate") else 1;now=_now();before=dict(row);cursor=db.execute("UPDATE major_task_action_areas SET is_active=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",(active,g.current_user["id"],now,area_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _touch_task(db,row["task_id"],g.current_user["id"],now);after=dict(db.execute("SELECT * FROM major_task_action_areas WHERE id=?",(area_id,)).fetchone());verb="복원" if active else "비활성화";_audit(audit_fn,f"MAJOR_TASK_AREA_{'RESTORE' if active else 'DEACTIVATE'}","major_task",row["task_id"],f"{row['name']} 실행영역 {verb}",before,after);db.commit();return jsonify(message=f"세부 실행영역이 {verb}되었습니다.",area=after)

    @app.post("/api/major-task-milestones/<milestone_id>/actions")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def action_create(milestone_id):
        db=get_db();m=db.execute("SELECT * FROM major_task_milestones WHERE id=? AND is_active=1",(milestone_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not m:return jsonify(error="마일스톤을 찾을 수 없습니다."),404
        if not _can_milestone(db,m,g.current_user):return jsonify(error="실행항목 추가 권한이 없습니다."),403
        name=_clean(data.get("name"),300);status=_clean(data.get("status") or "not_started",30)
        if not name:return jsonify(error="실행항목명을 입력하세요."),400
        if status not in ITEM_STATUSES:return jsonify(error="실행항목 상태가 올바르지 않습니다."),400
        importance=_clean(data.get("importance") or "medium",10)
        if importance not in {"high","medium","low"}:return jsonify(error="실행항목 중요도가 올바르지 않습니다."),400
        area_id=_clean(data.get("area_id"),32) or None
        if area_id and not db.execute("SELECT 1 FROM major_task_action_areas WHERE id=? AND milestone_id=?",(area_id,milestone_id)).fetchone():return jsonify(error="세부 실행영역이 올바르지 않습니다."),400
        try:
            assignee_ids = _normalized_user_ids(db, data.get("assignee_ids"), "Action 담당자") if "assignee_ids" in data else None
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        owner_id = assignee_ids[0] if assignee_ids else _int(data.get("owner_id")) if assignee_ids is None else None
        deputy_owner_id = assignee_ids[1] if assignee_ids and len(assignee_ids) > 1 else _int(data.get("deputy_owner_id")) if assignee_ids is None else None
        if not _user_exists(db,owner_id) or not _user_exists(db,deputy_owner_id):return jsonify(error="실행항목 담당자를 찾을 수 없습니다."),400
        action_id=uuid.uuid4().hex;now=_now();db.execute("""INSERT INTO major_task_actions
          (id,task_id,milestone_id,area_id,name,owner_id,deputy_owner_id,start_date,due_date,actual_completion_date,status,importance,is_required,include_in_progress,include_in_rag,result,next_action,attachment_note,display_order,started_with_override_reason,is_active,version,created_by,updated_by,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,?,?,?,?)""",
          (action_id,m["task_id"],milestone_id,area_id,name,owner_id,deputy_owner_id,_date(data.get("start_date"),"시작일"),_date(data.get("due_date"),"완료예정일"),_date(data.get("actual_completion_date"),"실제 완료일"),status,importance,_bool(data.get("is_required",True)),_bool(data.get("include_in_progress",data.get("is_required",True))),_bool(data.get("include_in_rag",data.get("is_required",True))),_clean(data.get("result"),3000),_clean(data.get("next_action"),1000),_clean(data.get("attachment_note"),1000),_int(data.get("display_order"),0),_clean(data.get("override_reason"),1000),g.current_user["id"],g.current_user["id"],now,now));_replace_action_people(db,action_id,assignee_ids if assignee_ids is not None else data.get("cooperator_ids"),now);_touch_task(db,m["task_id"],g.current_user["id"],now);_refresh_rag(db,m["task_id"]);created=dict(db.execute("SELECT * FROM major_task_actions WHERE id=?",(action_id,)).fetchone());created["assignee_ids"]=_action_assignee_ids(db,created);created["assignees"]=_named_users(db,created["assignee_ids"]);_audit(audit_fn,"MAJOR_TASK_ACTION_CREATE","major_task",m["task_id"],f"{name} 실행항목 추가",None,created);db.commit();return jsonify(message="실행항목이 추가되었습니다.",action=created),201

    @app.patch("/api/major-task-actions/<action_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def action_update(action_id):
        db=get_db();a=db.execute("SELECT * FROM major_task_actions WHERE id=? AND is_active=1",(action_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not a:return jsonify(error="실행항목을 찾을 수 없습니다."),404
        if not _can_action(db,a,g.current_user):return jsonify(error="실행항목 수정 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        status=_clean(data.get("status",a["status"]),30)
        if status not in ITEM_STATUSES:return jsonify(error="실행항목 상태가 올바르지 않습니다."),400
        predecessors=[_clean(v,32) for v in data.get("predecessors",[]) if _clean(v,32)]
        if action_id in predecessors:return jsonify(error="자기 자신을 선행 실행항목으로 지정할 수 없습니다."),400
        for pred in predecessors:
            row=db.execute("SELECT task_id,status,is_active FROM major_task_actions WHERE id=?",(pred,)).fetchone()
            if not row or row["task_id"]!=a["task_id"]:return jsonify(error="같은 주요업무의 실행항목만 연결할 수 있습니다."),400
            if not row["is_active"] or row["status"]=="cancelled":return jsonify(error="비활성화되거나 취소된 실행항목은 선행항목으로 연결할 수 없습니다."),400
        if _dependency_cycle(db,"major_task_action_dependencies","action_id","predecessor_id",action_id,predecessors):return jsonify(error="실행항목 선행관계가 순환합니다."),400
        override=_clean(data.get("override_reason",a["started_with_override_reason"]),1000)
        incomplete_preds=[pred for pred in predecessors if db.execute("SELECT status FROM major_task_actions WHERE id=?",(pred,)).fetchone()["status"]!="completed"]
        if status=="in_progress" and incomplete_preds and not override:return jsonify(error="선행 실행항목이 미완료입니다. 시작 사유를 입력하세요."),400
        if status=="completed":
            remaining=db.execute("SELECT COUNT(*) AS count FROM major_task_checklists WHERE action_id=? AND is_active=1 AND is_required=1 AND is_completed=0",(action_id,)).fetchone()["count"]
            if remaining and not _clean(data.get("completion_override_reason"),1000):return jsonify(error="필수 체크리스트가 남아 있습니다. 예외 완료 사유를 입력하세요."),400
        try:
            assignee_ids = _normalized_user_ids(db, data.get("assignee_ids"), "Action 담당자") if "assignee_ids" in data else None
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        owner_id = assignee_ids[0] if assignee_ids else _int(data.get("owner_id"),a["owner_id"]) if assignee_ids is None else None
        deputy_owner_id = assignee_ids[1] if assignee_ids and len(assignee_ids)>1 else _int(data.get("deputy_owner_id"),a["deputy_owner_id"]) if assignee_ids is None else None
        if not _user_exists(db,owner_id) or not _user_exists(db,deputy_owner_id):return jsonify(error="실행항목 담당자를 찾을 수 없습니다."),400
        completion_override=_clean(data.get("completion_override_reason",a["completion_override_reason"]),1000)
        importance=_clean(data.get("importance",a["importance"]),10)
        if importance not in {"high","medium","low"}:return jsonify(error="실행항목 중요도가 올바르지 않습니다."),400
        area_id=_clean(data.get("area_id",a["area_id"]),32) or None
        if area_id and not db.execute("SELECT 1 FROM major_task_action_areas WHERE id=? AND milestone_id=? AND is_active=1",(area_id,a["milestone_id"])).fetchone():return jsonify(error="세부 실행영역이 올바르지 않습니다."),400
        now=_now();before=dict(a);before["assignee_ids"]=_action_assignee_ids(db,a);cursor=db.execute("""UPDATE major_task_actions SET area_id=?,name=?,owner_id=?,deputy_owner_id=?,start_date=?,due_date=?,actual_completion_date=?,status=?,importance=?,is_required=?,include_in_progress=?,include_in_rag=?,result=?,next_action=?,attachment_note=?,completion_override_reason=?,display_order=?,started_with_override_reason=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?""",
          (area_id,_clean(data.get("name",a["name"]),300),owner_id,deputy_owner_id,_date(data.get("start_date",a["start_date"]),"시작일"),_date(data.get("due_date",a["due_date"]),"완료예정일"),_date(data.get("actual_completion_date",a["actual_completion_date"]),"실제 완료일"),status,importance,_bool(data.get("is_required",a["is_required"])),_bool(data.get("include_in_progress",a["include_in_progress"])),_bool(data.get("include_in_rag",a["include_in_rag"])),_clean(data.get("result",a["result"]),3000),_clean(data.get("next_action",a["next_action"]),1000),_clean(data.get("attachment_note",a["attachment_note"]),1000),completion_override,_int(data.get("display_order",a["display_order"]),a["display_order"]),override,g.current_user["id"],now,action_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        db.execute("DELETE FROM major_task_action_dependencies WHERE action_id=?",(action_id,))
        for pred in predecessors:db.execute("INSERT INTO major_task_action_dependencies(action_id,predecessor_id,created_by,created_at) VALUES (?,?,?,?)",(action_id,pred,g.current_user["id"],now))
        _replace_action_people(db,action_id,assignee_ids if assignee_ids is not None else data.get("cooperator_ids"),now)
        _touch_task(db,a["task_id"],g.current_user["id"],now);_refresh_rag(db,a["task_id"]);after=dict(db.execute("SELECT * FROM major_task_actions WHERE id=?",(action_id,)).fetchone());after["assignee_ids"]=_action_assignee_ids(db,after);after["assignees"]=_named_users(db,after["assignee_ids"]);_audit(audit_fn,"MAJOR_TASK_ACTION_UPDATE","major_task",a["task_id"],f"{after['name']} 실행항목 담당자·내용 수정",before,after);db.commit();return jsonify(message="실행항목이 수정되었습니다.",action=after)

    @app.post("/api/major-task-actions/<action_id>/deactivate")
    @app.post("/api/major-task-actions/<action_id>/restore")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def action_active_state(action_id):
        db=get_db();a=db.execute("SELECT * FROM major_task_actions WHERE id=?",(action_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not a:return jsonify(error="실행항목을 찾을 수 없습니다."),404
        if not _can_structure(db,_task_row(db,a["task_id"]),g.current_user):return jsonify(error="실행항목 구조변경 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        active=0 if request.path.endswith("/deactivate") else 1;now=_now();before=dict(a);cursor=db.execute("UPDATE major_task_actions SET is_active=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",(active,g.current_user["id"],now,action_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _touch_task(db,a["task_id"],g.current_user["id"],now);_refresh_rag(db,a["task_id"]);after=dict(db.execute("SELECT * FROM major_task_actions WHERE id=?",(action_id,)).fetchone());verb="복원" if active else "비활성화";_audit(audit_fn,f"MAJOR_TASK_ACTION_{'RESTORE' if active else 'DEACTIVATE'}","major_task",a["task_id"],f"{a['name']} 실행항목 {verb}",before,after);db.commit();return jsonify(message=f"실행항목이 {verb}되었습니다.",action=after)

    @app.post("/api/major-task-actions/<action_id>/checklists")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def checklist_create(action_id):
        db=get_db();a=db.execute("SELECT * FROM major_task_actions WHERE id=? AND is_active=1",(action_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not a:return jsonify(error="실행항목을 찾을 수 없습니다."),404
        if not _can_action(db,a,g.current_user):return jsonify(error="체크리스트 추가 권한이 없습니다."),403
        text=_clean(data.get("item_text"),500)
        if not text:return jsonify(error="체크항목을 입력하세요."),400
        cid=uuid.uuid4().hex;now=_now();db.execute("INSERT INTO major_task_checklists(id,action_id,item_text,is_completed,is_required,display_order,version,created_by,updated_by,created_at,updated_at) VALUES (?,?,?,0,?,?,1,?,?,?,?)",(cid,action_id,text,_bool(data.get("is_required",True)),_int(data.get("display_order"),0),g.current_user["id"],g.current_user["id"],now,now));_touch_task(db,a["task_id"],g.current_user["id"],now);created=dict(db.execute("SELECT * FROM major_task_checklists WHERE id=?",(cid,)).fetchone());_audit(audit_fn,"MAJOR_TASK_CHECKLIST_CREATE","major_task",a["task_id"],f"{text} 체크리스트 추가",None,created);db.commit();return jsonify(message="체크리스트가 추가되었습니다.",checklist=created),201

    @app.patch("/api/major-task-checklists/<checklist_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def checklist_update(checklist_id):
        db=get_db();c=db.execute("SELECT * FROM major_task_checklists WHERE id=? AND is_active=1",(checklist_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not c:return jsonify(error="체크리스트를 찾을 수 없습니다."),404
        a=db.execute("SELECT * FROM major_task_actions WHERE id=?",(c["action_id"],)).fetchone()
        if not _can_action(db,a,g.current_user):return jsonify(error="체크리스트 수정 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        done=_bool(data.get("is_completed",c["is_completed"]));now=_now();before=dict(c);cursor=db.execute("UPDATE major_task_checklists SET item_text=?,is_completed=?,is_required=?,completed_by=?,completed_at=?,display_order=?,completion_override_reason=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",(_clean(data.get("item_text",c["item_text"]),500),done,_bool(data.get("is_required",c["is_required"])),g.current_user["id"] if done else None,now if done else None,_int(data.get("display_order"),c["display_order"]),_clean(data.get("completion_override_reason",c["completion_override_reason"]),1000),g.current_user["id"],now,checklist_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _touch_task(db,a["task_id"],g.current_user["id"],now);after=dict(db.execute("SELECT * FROM major_task_checklists WHERE id=?",(checklist_id,)).fetchone());_audit(audit_fn,"MAJOR_TASK_CHECKLIST_UPDATE","major_task",a["task_id"],f"{after['item_text']} 체크리스트 변경",before,after);db.commit();return jsonify(message="체크리스트가 변경되었습니다.",checklist=after)

    @app.post("/api/major-task-checklists/<checklist_id>/deactivate")
    @app.post("/api/major-task-checklists/<checklist_id>/restore")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def checklist_active_state(checklist_id):
        db=get_db();c=db.execute("SELECT * FROM major_task_checklists WHERE id=?",(checklist_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not c:return jsonify(error="체크리스트를 찾을 수 없습니다."),404
        a=db.execute("SELECT * FROM major_task_actions WHERE id=?",(c["action_id"],)).fetchone();task=_task_row(db,a["task_id"])
        if not _can_structure(db,task,g.current_user):return jsonify(error="체크리스트 구조변경 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        active=0 if request.path.endswith("/deactivate") else 1;now=_now();before=dict(c);cursor=db.execute("UPDATE major_task_checklists SET is_active=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",(active,g.current_user["id"],now,checklist_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _touch_task(db,a["task_id"],g.current_user["id"],now);after=dict(db.execute("SELECT * FROM major_task_checklists WHERE id=?",(checklist_id,)).fetchone());verb="복원" if active else "비활성화";_audit(audit_fn,f"MAJOR_TASK_CHECKLIST_{'RESTORE' if active else 'DEACTIVATE'}","major_task",a["task_id"],f"{c['item_text']} 체크리스트 {verb}",before,after);db.commit();return jsonify(message=f"체크리스트가 {verb}되었습니다.",checklist=after)

    @app.post("/api/major-tasks/<task_id>/balls")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def ball_create(task_id):
        db=get_db();task=_task_row(db,task_id);data=request.get_json(silent=True) or {}
        if not task:return jsonify(error="주요업무를 찾을 수 없습니다."),404
        try: owner_type=_ball_owner_type(data.get("owner_type"))
        except ValueError as exc:return jsonify(error=str(exc)),400
        action_id=_clean(data.get("action_id"),32) or None;milestone_id=_clean(data.get("milestone_id"),32) or None
        if action_id:
            action=db.execute("SELECT * FROM major_task_actions WHERE id=? AND task_id=? AND is_active=1",(action_id,task_id)).fetchone()
            if not action:return jsonify(error="실행항목 연결이 올바르지 않습니다."),400
            milestone_id=action["milestone_id"]
        elif milestone_id:
            milestone=db.execute("SELECT * FROM major_task_milestones WHERE id=? AND task_id=? AND is_active=1",(milestone_id,task_id)).fetchone()
            if not milestone:return jsonify(error="마일스톤 연결이 올바르지 않습니다."),400
        if action_id:
            allowed=_can_action(db,action,g.current_user)
        elif milestone_id:
            allowed=_can_milestone(db,milestone,g.current_user)
        else:
            allowed=_can_structure(db,task,g.current_user)
        if not allowed:return jsonify(error="Ball을 등록할 권한이 없습니다."),403
        follow_up_owner_id=_int(data.get("follow_up_owner_id"))
        if not _user_exists(db,follow_up_owner_id):return jsonify(error="Follow-up 담당자를 찾을 수 없습니다."),400
        impact=_clean(data.get("hard_deadline_impact") or "none",10)
        if impact not in {"none","amber","red"}:return jsonify(error="기한 영향도가 올바르지 않습니다."),400
        ball_id=uuid.uuid4().hex;now=_now();values=(ball_id,task_id,milestone_id,action_id,owner_type,_clean(data.get("owner_detail"),300),_clean(data.get("request_text"),2000),_date(data.get("wait_started_at"),"대기 시작일"),_date(data.get("last_requested_at"),"마지막 요청일"),_date(data.get("last_contacted_at"),"마지막 연락일"),_date(data.get("expected_reply_date"),"예상 회신일"),_date(data.get("follow_up_date"),"Follow-up Date"),_int(data.get("follow_up_owner_id")),_clean(data.get("cooperation_needed"),1000),_date(data.get("resolution_due_date"),"해결 예정일"),_bool(data.get("represents_whole_milestone")),_clean(data.get("hard_deadline_impact") or "none",10),g.current_user["id"],g.current_user["id"],now,now)
        db.execute("""INSERT INTO major_task_balls(id,task_id,milestone_id,action_id,owner_type,owner_detail,request_text,wait_started_at,last_requested_at,last_contacted_at,expected_reply_date,follow_up_date,follow_up_owner_id,cooperation_needed,resolution_due_date,represents_whole_milestone,hard_deadline_impact,is_active,version,created_by,updated_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,?,?,?,?)""",values)
        created=dict(db.execute("SELECT * FROM major_task_balls WHERE id=?",(ball_id,)).fetchone());db.execute("INSERT INTO major_task_ball_history(id,ball_id,change_type,after_json,changed_by,changed_at) VALUES (?,?, 'create',?,?,?)",(uuid.uuid4().hex,ball_id,_json(created),g.current_user["id"],now));_touch_task(db,task_id,g.current_user["id"],now);_refresh_rag(db,task_id);_audit(audit_fn,"MAJOR_TASK_BALL_CREATE","major_task",task_id,"Ball 소유권 등록",None,created);db.commit();return jsonify(message="Ball 소유권이 등록되었습니다.",ball=created),201

    @app.patch("/api/major-task-balls/<ball_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def ball_update(ball_id):
        db=get_db();b=db.execute("SELECT * FROM major_task_balls WHERE id=?",(ball_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not b:return jsonify(error="Ball 정보를 찾을 수 없습니다."),404
        task=_task_row(db,b["task_id"])
        if not _can_ball(db,b,g.current_user):return jsonify(error="Ball 수정 권한이 없습니다."),403
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        try: owner_type=_ball_owner_type(data.get("owner_type",b["owner_type"]))
        except ValueError as exc:return jsonify(error=str(exc)),400
        follow_up_owner_id=_int(data.get("follow_up_owner_id"),b["follow_up_owner_id"])
        if not _user_exists(db,follow_up_owner_id):return jsonify(error="Follow-up 담당자를 찾을 수 없습니다."),400
        impact=_clean(data.get("hard_deadline_impact",b["hard_deadline_impact"]),10)
        if impact not in {"none","amber","red"}:return jsonify(error="기한 영향도가 올바르지 않습니다."),400
        now=_now();resolved=_date(data.get("resolved_at",b["resolved_at"]),"해결 완료일");before=dict(b);cursor=db.execute("""UPDATE major_task_balls SET owner_type=?,owner_detail=?,request_text=?,wait_started_at=?,last_requested_at=?,last_contacted_at=?,expected_reply_date=?,follow_up_date=?,follow_up_owner_id=?,cooperation_needed=?,resolution_due_date=?,resolved_at=?,is_active=?,represents_whole_milestone=?,hard_deadline_impact=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?""",
          (owner_type,_clean(data.get("owner_detail",b["owner_detail"]),300),_clean(data.get("request_text",b["request_text"]),2000),_date(data.get("wait_started_at",b["wait_started_at"]),"대기 시작일"),_date(data.get("last_requested_at",b["last_requested_at"]),"마지막 요청일"),_date(data.get("last_contacted_at",b["last_contacted_at"]),"마지막 연락일"),_date(data.get("expected_reply_date",b["expected_reply_date"]),"예상 회신일"),_date(data.get("follow_up_date",b["follow_up_date"]),"Follow-up Date"),follow_up_owner_id,_clean(data.get("cooperation_needed",b["cooperation_needed"]),1000),_date(data.get("resolution_due_date",b["resolution_due_date"]),"해결 예정일"),resolved,0 if resolved else _bool(data.get("is_active",b["is_active"])),_bool(data.get("represents_whole_milestone",b["represents_whole_milestone"])),impact,g.current_user["id"],now,ball_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        after=dict(db.execute("SELECT * FROM major_task_balls WHERE id=?",(ball_id,)).fetchone());db.execute("INSERT INTO major_task_ball_history(id,ball_id,change_type,before_json,after_json,reason,changed_by,changed_at) VALUES (?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,ball_id,"resolve" if resolved else "update",_json(before),_json(after),_clean(data.get("reason"),1000),g.current_user["id"],now));_touch_task(db,b["task_id"],g.current_user["id"],now);_refresh_rag(db,b["task_id"]);_audit(audit_fn,"MAJOR_TASK_BALL_UPDATE","major_task",b["task_id"],"Ball 소유권 변경",before,after);db.commit();return jsonify(message="Ball 정보가 변경되었습니다.",ball=after)

    @app.get("/api/major-tasks/views/<view_name>")
    @role_required(*READ_ROLES)
    def major_task_view_data(view_name):
        db=get_db();filtered_rows=list_task_rows(db,request.args);task_ids=[row["id"] for row in filtered_rows]
        placeholders=",".join("?" for _ in task_ids)
        if view_name=="kanban":
            if not task_ids:return jsonify(items=[])
            rows=[dict(row) for row in db.execute("""SELECT a.id,a.name,a.status,a.due_date,a.owner_id,u.display_name AS owner_name,m.name AS milestone_name,t.id AS task_id,t.title AS task_title,t.final_rag FROM major_task_actions a JOIN major_tasks t ON t.id=a.task_id JOIN major_task_milestones m ON m.id=a.milestone_id LEFT JOIN users u ON u.id=a.owner_id WHERE a.is_active=1 AND a.status NOT IN ('completed','cancelled') AND t.id IN ("""+placeholders+") ORDER BY COALESCE(a.due_date,'9999-12-31'),a.display_order",task_ids)]
            return jsonify(items=rows)
        if view_name=="gantt":
            if not task_ids:return jsonify(items=[])
            milestones=[dict(row) for row in db.execute("""SELECT m.id,m.task_id,t.title AS task_title,m.name,m.planned_start_date,m.planned_end_date,m.status,t.current_target_date,t.hard_deadline_date,'milestone' AS item_type,m.display_order FROM major_task_milestones m JOIN major_tasks t ON t.id=m.task_id WHERE m.is_active=1 AND t.id IN ("""+placeholders+") ORDER BY COALESCE(m.planned_start_date,'9999-12-31'),m.display_order",task_ids)]
            actions=[dict(row) for row in db.execute("""SELECT a.id,a.task_id,t.title AS task_title,a.name,a.start_date AS planned_start_date,a.due_date AS planned_end_date,a.status,t.current_target_date,t.hard_deadline_date,'action' AS item_type,a.display_order,m.name AS milestone_name FROM major_task_actions a JOIN major_tasks t ON t.id=a.task_id JOIN major_task_milestones m ON m.id=a.milestone_id WHERE a.is_active=1 AND m.is_active=1 AND t.id IN ("""+placeholders+") ORDER BY COALESCE(a.start_date,a.due_date,'9999-12-31'),a.display_order",task_ids)]
            dependencies=[]
            for row in db.execute("""SELECT d.milestone_id AS item_id,d.predecessor_id,'milestone' AS item_type FROM major_task_milestone_dependencies d JOIN major_task_milestones m ON m.id=d.milestone_id WHERE m.task_id IN ("""+placeholders+") UNION ALL SELECT d.action_id,d.predecessor_id,'action' FROM major_task_action_dependencies d JOIN major_task_actions a ON a.id=d.action_id WHERE a.task_id IN ("""+placeholders+")",task_ids+task_ids):dependencies.append(dict(row))
            return jsonify(items=milestones+actions,dependencies=dependencies)
        if view_name=="weekly":
            start,end=_week_bounds();last_start=start-timedelta(days=7);last_end=start-timedelta(days=1);today=_today().isoformat()
            rows=filtered_rows
            result={key:[] for key in ("directive","risk","internal_due","external_followup","hard_deadline","cooperation","decision","hold_review","week_due","last_week_done","green_external")}
            for row in rows:
                item=_serialize_task(db,row);balls=_current_balls(db,row["id"])
                if row["ceo_directive"]:result["directive"].append(item)
                if row["final_rag"] in {"red","amber"}:result["risk"].append(item)
                if any(BALL_CANONICAL_TYPES.get(b["owner_type"],"external")=="internal" and (b["resolution_due_date"] or "9999")<=end.isoformat() for b in balls):result["internal_due"].append(item)
                if any(BALL_CANONICAL_TYPES.get(b["owner_type"],"external") in {"customer","external"} and b["follow_up_date"] and b["follow_up_date"]<=today for b in balls):result["external_followup"].append(item)
                if row["hard_deadline_date"] and row["hard_deadline_date"]<=end.isoformat():result["hard_deadline"].append(item)
                if row["status"]=="cooperation_wait":result["cooperation"].append(item)
                if db.execute("SELECT 1 FROM major_task_progress_updates WHERE task_id=? AND is_current=1 AND decision_needed<>'' LIMIT 1",(row["id"],)).fetchone():result["decision"].append(item)
                if row["status"]=="hold" and row["review_date"] and row["review_date"]<=end.isoformat():result["hold_review"].append(item)
                if row["current_target_date"] and start.isoformat()<=row["current_target_date"]<=end.isoformat():result["week_due"].append(item)
                if row["final_rag"]=="green" and any(BALL_CANONICAL_TYPES.get(b["owner_type"],"external") in {"customer","external"} and (not b["follow_up_date"] or b["follow_up_date"]>today) for b in balls):result["green_external"].append(item)
            archived_args=dict(request.args);archived_args.update({"archive":"1","status":"completed"});done=[row for row in list_task_rows(db,archived_args) if row["actual_completion_date"] and last_start.isoformat()<=row["actual_completion_date"]<=last_end.isoformat()];result["last_week_done"]=[_serialize_task(db,row) for row in done]
            return jsonify(week={"start":start.isoformat(),"end":end.isoformat()},sections=result)
        return jsonify(error="지원하지 않는 보기방식입니다."),400

    @app.get("/api/major-task-workstreams")
    @role_required(*READ_ROLES)
    def workstream_list():
        db=get_db();rows=[]
        for row in db.execute("SELECT * FROM major_task_workstreams ORDER BY is_active DESC,display_order,name"):
            item=dict(row);item["business_links"]=[dict(v) for v in db.execute("SELECT business_unit,business_subcategory FROM major_task_workstream_business WHERE workstream_id=?",(row["id"],))];item["template"]=[dict(v) for v in db.execute("SELECT * FROM major_task_workstream_templates WHERE workstream_id=? AND template_version=? ORDER BY display_order,created_at",(row["id"],row["template_version"]))];rows.append(item)
        return jsonify(workstreams=rows)

    @app.post("/api/major-tasks/<task_id>/copy-to-workstream-template")
    @role_required("admin","manager")
    @csrf_required
    def major_task_copy_to_workstream_template(task_id):
        db=get_db();task=_task_row(db,task_id);data=request.get_json(silent=True) or {};name=_clean(data.get("name"),200)
        if not task:return jsonify(error="주요업무를 찾을 수 없습니다."),404
        if not name:return jsonify(error="새 워크스트림명을 입력하세요."),400
        try:
            review_days=_optional_days(data.get("review_cycle_days"),"점검주기")
            due_days=_optional_days(data.get("due_soon_days",3),"일반기한 임박기준")
            hard_days=_optional_days(data.get("hard_deadline_soon_days",7),"Hard Deadline 임박기준")
        except ValueError as exc:return jsonify(error=str(exc)),400
        now=_now();workstream_id=uuid.uuid4().hex
        try:db.execute("""INSERT INTO major_task_workstreams
          (id,name,description,color,display_order,is_active,review_cycle_days,due_soon_days,hard_deadline_soon_days,template_version,version,created_by,updated_by,created_at,updated_at)
          VALUES (?,?,?,?,?,1,?,?,?,?,1,?,?,?,?)""",
          (workstream_id,name,_clean(data.get("description") or f"{task['title']}에서 생성",1000),_clean(data.get("color") or "#0a7d6b",20),_int(data.get("display_order"),0),review_days,due_days,hard_days,1,g.current_user["id"],g.current_user["id"],now,now))
        except sqlite3.IntegrityError:return jsonify(error="같은 이름의 워크스트림이 있습니다."),409
        db.execute("INSERT INTO major_task_workstream_business(workstream_id,business_unit,business_subcategory) VALUES (?,?,?)",(workstream_id,task["primary_business_unit"],task["primary_business_subcategory"]))
        milestone_map={};area_map={};action_map={};order=0
        for row in db.execute("SELECT * FROM major_task_milestones WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at",(task_id,)):
            order+=1;item_id=uuid.uuid4().hex;milestone_map[row["id"]]=item_id;db.execute("""INSERT INTO major_task_workstream_templates
              (id,workstream_id,parent_id,item_type,name,description,is_required,include_in_progress,display_order,template_version,version,created_at,updated_at)
              VALUES (?,?,NULL,'milestone',?,?,?,?,?,1,1,?,?)""",(item_id,workstream_id,row["name"],row["description"],row["is_required"],1,row["display_order"] or order,now,now))
        for row in db.execute("""SELECT a.* FROM major_task_action_areas a JOIN major_task_milestones m ON m.id=a.milestone_id WHERE m.task_id=? AND a.is_active=1 ORDER BY a.display_order,a.created_at""",(task_id,)):
            item_id=uuid.uuid4().hex;area_map[row["id"]]=item_id;db.execute("""INSERT INTO major_task_workstream_templates
              (id,workstream_id,parent_id,item_type,name,description,is_required,include_in_progress,display_order,template_version,version,created_at,updated_at)
              VALUES (?,?,?,'area',?,?,1,1,?,1,1,?,?)""",(item_id,workstream_id,milestone_map[row["milestone_id"]],row["name"],row["description"],row["display_order"],now,now))
        for row in db.execute("SELECT * FROM major_task_actions WHERE task_id=? AND is_active=1 ORDER BY display_order,created_at",(task_id,)):
            item_id=uuid.uuid4().hex;action_map[row["id"]]=item_id;db.execute("""INSERT INTO major_task_workstream_templates
              (id,workstream_id,parent_id,item_type,name,description,is_required,include_in_progress,display_order,template_version,version,created_at,updated_at)
              VALUES (?,?,?,'action',?,'',?,?,?,?,1,?,?)""",(item_id,workstream_id,area_map.get(row["area_id"]) or milestone_map[row["milestone_id"]],row["name"],row["is_required"],row["include_in_progress"],row["display_order"],1,now,now))
        for row in db.execute("""SELECT c.* FROM major_task_checklists c JOIN major_task_actions a ON a.id=c.action_id WHERE a.task_id=? AND c.is_active=1 ORDER BY c.display_order,c.created_at""",(task_id,)):
            db.execute("""INSERT INTO major_task_workstream_templates
              (id,workstream_id,parent_id,item_type,name,description,is_required,include_in_progress,display_order,template_version,version,created_at,updated_at)
              VALUES (?,?,?,'checklist',?,'',?,1,?,1,1,?,?)""",(uuid.uuid4().hex,workstream_id,action_map[row["action_id"]],row["item_text"],row["is_required"],row["display_order"],now,now))
        count=db.execute("SELECT COUNT(*) AS count FROM major_task_workstream_templates WHERE workstream_id=?",(workstream_id,)).fetchone()["count"];_audit(audit_fn,"MAJOR_TASK_TO_WORKSTREAM_TEMPLATE","major_task_workstream",workstream_id,f"{task['title']}에서 {name} 템플릿 생성",{"source_task_id":task_id},{"template_items":count});db.commit();return jsonify(message="새 워크스트림 템플릿으로 복사했습니다.",id=workstream_id,template_items=count),201

    @app.post("/api/major-task-workstreams")
    @role_required("admin","manager")
    @csrf_required
    def workstream_create():
        db=get_db();data=request.get_json(silent=True) or {};name=_clean(data.get("name"),200)
        if not name:return jsonify(error="워크스트림명을 입력하세요."),400
        try:
            review_days=_optional_days(data.get("review_cycle_days"),"점검주기")
            due_days=_optional_days(data.get("due_soon_days",3),"일반기한 임박기준")
            hard_days=_optional_days(data.get("hard_deadline_soon_days",7),"Hard Deadline 임박기준")
        except ValueError as exc:return jsonify(error=str(exc)),400
        wid=uuid.uuid4().hex;now=_now()
        try:db.execute("INSERT INTO major_task_workstreams(id,name,description,color,display_order,is_active,review_cycle_days,due_soon_days,hard_deadline_soon_days,template_version,version,created_by,updated_by,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?,1,?,?,?,?)",(wid,name,_clean(data.get("description"),1000),_clean(data.get("color") or "#0a7d6b",20),_int(data.get("display_order"),0),review_days,due_days,hard_days,1,g.current_user["id"],g.current_user["id"],now,now))
        except sqlite3.IntegrityError:return jsonify(error="같은 이름의 워크스트림이 있습니다."),409
        try:_replace_workstream_business(db,wid,data.get("business_links"))
        except ValueError as exc:db.rollback();return jsonify(error=str(exc)),400
        created=dict(db.execute("SELECT * FROM major_task_workstreams WHERE id=?",(wid,)).fetchone());_audit(audit_fn,"MAJOR_TASK_WORKSTREAM_CREATE","major_task_workstream",wid,f"{name} 워크스트림 생성",None,created);db.commit();return jsonify(message="워크스트림이 추가되었습니다.",workstream=created),201

    @app.patch("/api/major-task-workstreams/<workstream_id>")
    @role_required("admin","manager")
    @csrf_required
    def workstream_update(workstream_id):
        db=get_db();row=db.execute("SELECT * FROM major_task_workstreams WHERE id=?",(workstream_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="워크스트림을 찾을 수 없습니다."),404
        try:
            expected=_version(data)
            review_days=_optional_days(data.get("review_cycle_days",row["review_cycle_days"]),"점검주기")
            due_days=_optional_days(data.get("due_soon_days",row["due_soon_days"]),"일반기한 임박기준")
            hard_days=_optional_days(data.get("hard_deadline_soon_days",row["hard_deadline_soon_days"]),"Hard Deadline 임박기준")
        except ValueError as exc:return jsonify(error=str(exc)),400
        now=_now();before=dict(row);cursor=db.execute("UPDATE major_task_workstreams SET name=?,description=?,color=?,display_order=?,is_active=?,review_cycle_days=?,due_soon_days=?,hard_deadline_soon_days=?,updated_by=?,updated_at=?,version=version+1 WHERE id=? AND version=?",(_clean(data.get("name",row["name"]),200),_clean(data.get("description",row["description"]),1000),_clean(data.get("color",row["color"]),20),_int(data.get("display_order"),row["display_order"]),_bool(data.get("is_active",row["is_active"])),review_days,due_days,hard_days,g.current_user["id"],now,workstream_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        try:_replace_workstream_business(db,workstream_id,data.get("business_links"))
        except ValueError as exc:db.rollback();return jsonify(error=str(exc)),400
        after=dict(db.execute("SELECT * FROM major_task_workstreams WHERE id=?",(workstream_id,)).fetchone());_audit(audit_fn,"MAJOR_TASK_WORKSTREAM_UPDATE","major_task_workstream",workstream_id,f"{after['name']} 워크스트림 수정",before,after);db.commit();return jsonify(message="워크스트림이 수정되었습니다.",workstream=after)

    @app.put("/api/major-task-workstreams/<workstream_id>/template")
    @role_required("admin","manager")
    @csrf_required
    def workstream_template_replace(workstream_id):
        db=get_db();workstream=db.execute("SELECT * FROM major_task_workstreams WHERE id=?",(workstream_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not workstream:return jsonify(error="워크스트림을 찾을 수 없습니다."),404
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        items=data.get("template")
        if not isinstance(items,list):return jsonify(error="템플릿 항목 배열을 입력하세요."),400
        normalized=[];by_client={};allowed={"milestone":None,"area":"milestone","action":("milestone","area"),"checklist":"action"}
        for index,item in enumerate(items):
            if not isinstance(item,dict):return jsonify(error="템플릿 항목 형식이 올바르지 않습니다."),400
            client_id=_clean(item.get("client_id") or f"item-{index+1}",80);kind=_clean(item.get("item_type"),20);name=_clean(item.get("name"),300);parent=_clean(item.get("parent_client_id"),80) or None
            if not client_id or client_id in by_client or kind not in allowed or not name:return jsonify(error="템플릿 ID·유형·이름을 확인하세요."),400
            normalized_item={"client_id":client_id,"item_type":kind,"name":name,"parent_client_id":parent,"description":_clean(item.get("description"),1000),"is_required":_bool(item.get("is_required",True)),"include_in_progress":_bool(item.get("include_in_progress",True)),"display_order":_int(item.get("display_order"),index+1)};normalized.append(normalized_item);by_client[client_id]=normalized_item
        for item in normalized:
            required_parent=allowed[item["item_type"]];parent=by_client.get(item["parent_client_id"])
            if required_parent is None and item["parent_client_id"]:return jsonify(error="마일스톤은 상위 템플릿 항목을 가질 수 없습니다."),400
            if required_parent is not None and (not parent or parent["item_type"] not in ({required_parent} if isinstance(required_parent,str) else set(required_parent))):return jsonify(error=f"{item['name']}의 상위 템플릿 항목이 올바르지 않습니다."),400
        now=_now();next_version=int(workstream["template_version"] or 0)+1;before=[dict(row) for row in db.execute("SELECT * FROM major_task_workstream_templates WHERE workstream_id=? AND template_version=?",(workstream_id,workstream["template_version"]))]
        cursor=db.execute("UPDATE major_task_workstreams SET template_version=?,version=version+1,updated_by=?,updated_at=? WHERE id=? AND version=?",(next_version,g.current_user["id"],now,workstream_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        mapped={};type_order={"milestone":0,"area":1,"action":2,"checklist":3}
        for item in sorted(normalized,key=lambda value:(type_order[value["item_type"]],value["display_order"])):
            item_id=uuid.uuid4().hex;mapped[item["client_id"]]=item_id;db.execute("""INSERT INTO major_task_workstream_templates
              (id,workstream_id,parent_id,item_type,name,description,is_required,include_in_progress,display_order,template_version,version,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)""",
              (item_id,workstream_id,mapped.get(item["parent_client_id"]),item["item_type"],item["name"],item["description"],item["is_required"],item["include_in_progress"],item["display_order"],next_version,now,now))
        after=[dict(row) for row in db.execute("SELECT * FROM major_task_workstream_templates WHERE workstream_id=? AND template_version=? ORDER BY display_order,created_at",(workstream_id,next_version))];_audit(audit_fn,"MAJOR_TASK_WORKSTREAM_TEMPLATE_UPDATE","major_task_workstream",workstream_id,f"{workstream['name']} 템플릿 v{next_version} 저장",before,after);db.commit();return jsonify(message="워크스트림 템플릿이 저장되었습니다.",template_version=next_version,template=after)

    @app.post("/api/major-task-workstreams/<workstream_id>/copy")
    @role_required("admin","manager")
    @csrf_required
    def workstream_copy(workstream_id):
        db=get_db();source=db.execute("SELECT * FROM major_task_workstreams WHERE id=?",(workstream_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not source:return jsonify(error="워크스트림을 찾을 수 없습니다."),404
        name=_clean(data.get("name"),200)
        if not name:return jsonify(error="복사할 새 워크스트림명을 입력하세요."),400
        new_id=uuid.uuid4().hex;now=_now()
        try:
            db.execute("INSERT INTO major_task_workstreams(id,name,description,color,display_order,is_active,review_cycle_days,due_soon_days,hard_deadline_soon_days,template_version,copied_from_id,version,created_by,updated_by,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?,?,1,?,?,?,?)",(new_id,name,source["description"],source["color"],source["display_order"],source["review_cycle_days"],source["due_soon_days"],source["hard_deadline_soon_days"],1,workstream_id,g.current_user["id"],g.current_user["id"],now,now))
        except sqlite3.IntegrityError:
            db.rollback()
            return jsonify(error="같은 이름의 워크스트림이 이미 있습니다."),409
        mapped={}
        for link in db.execute("SELECT business_unit,business_subcategory FROM major_task_workstream_business WHERE workstream_id=?",(workstream_id,)):db.execute("INSERT INTO major_task_workstream_business(workstream_id,business_unit,business_subcategory) VALUES (?,?,?)",(new_id,link["business_unit"],link["business_subcategory"]))
        for item in db.execute("SELECT * FROM major_task_workstream_templates WHERE workstream_id=? AND template_version=? ORDER BY CASE item_type WHEN 'milestone' THEN 0 WHEN 'area' THEN 1 WHEN 'action' THEN 2 ELSE 3 END,display_order,created_at",(workstream_id,source["template_version"])):
            iid=uuid.uuid4().hex;mapped[item["id"]]=iid;db.execute("INSERT INTO major_task_workstream_templates(id,workstream_id,parent_id,item_type,name,description,is_required,include_in_progress,display_order,template_version,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,1,1,?,?)",(iid,new_id,mapped.get(item["parent_id"]),item["item_type"],item["name"],item["description"],item["is_required"],item["include_in_progress"],item["display_order"],now,now))
        _audit(audit_fn,"MAJOR_TASK_WORKSTREAM_COPY","major_task_workstream",new_id,f"{source['name']} → {name} 워크스트림 복사",dict(source),{"id":new_id,"name":name});db.commit();return jsonify(message="워크스트림과 템플릿이 복사되었습니다.",id=new_id),201

    @app.post("/api/major-tasks/<task_id>/links")
    @role_required("admin","manager")
    @csrf_required
    def major_task_link_create(task_id):
        db=get_db();task=_task_row(db,task_id);data=request.get_json(silent=True) or {}
        if not task:return jsonify(error="주요업무를 찾을 수 없습니다."),404
        link_type=_clean(data.get("link_type"),30);external_id=_clean(data.get("external_id"),200)
        if link_type not in {"promotion","customer","order","monthly_sales","shipment","external"} or not external_id:return jsonify(error="연결자료 유형과 고유 ID를 확인하세요."),400
        if link_type=="promotion":return jsonify(error="프로모션 연동은 이번 개편 범위에서 활성화하지 않았습니다."),409
        checks={"customer":("SELECT 1 FROM customer_master WHERE id=?",),"order":("SELECT 1 FROM records WHERE entity_type='order' AND id=?",),"monthly_sales":("SELECT 1 FROM monthly_sales WHERE id=?",),"shipment":("SELECT 1 FROM shipments WHERE issue_no=?",)}
        if link_type in checks and not db.execute(checks[link_type][0],(external_id,)).fetchone():return jsonify(error="연결할 원본자료를 찾을 수 없습니다."),400
        link_id=uuid.uuid4().hex;now=_now()
        try:db.execute("INSERT INTO major_task_external_links(id,task_id,link_type,external_id,linked_at,linked_by,status,notes,version) VALUES (?,?,?,?,?,?,'active',?,1)",(link_id,task_id,link_type,external_id,now,g.current_user["id"],_clean(data.get("notes"),1000)))
        except sqlite3.IntegrityError:return jsonify(error="동일한 활성 연결이 이미 있습니다."),409
        _audit(audit_fn,"MAJOR_TASK_LINK_CREATE","major_task",task_id,f"{link_type} 자료 연결",None,{"id":link_id,"external_id":external_id});db.commit();return jsonify(message="자료가 연결되었습니다.",id=link_id,version=1),201

    @app.post("/api/major-task-links/<link_id>/unlink")
    @role_required("admin","manager")
    @csrf_required
    def major_task_link_unlink(link_id):
        db=get_db();row=db.execute("SELECT * FROM major_task_external_links WHERE id=? AND status='active'",(link_id,)).fetchone();data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="활성 연결을 찾을 수 없습니다."),404
        try:expected=_version(data)
        except ValueError as exc:return jsonify(error=str(exc)),400
        now=_now();cursor=db.execute("UPDATE major_task_external_links SET status='unlinked',unlinked_at=?,unlinked_by=?,version=version+1 WHERE id=? AND version=?",(now,g.current_user["id"],link_id,expected))
        if cursor.rowcount!=1:db.rollback();return jsonify(error="다른 사용자가 먼저 수정했습니다. 최신 자료를 다시 불러오세요.",code="VERSION_CONFLICT"),409
        _audit(audit_fn,"MAJOR_TASK_LINK_UNLINK","major_task",row["task_id"],f"{row['link_type']} 자료 연결해제",dict(row),{"status":"unlinked","unlinked_at":now});db.commit();return jsonify(message="자료 연결이 해제되었습니다.")
