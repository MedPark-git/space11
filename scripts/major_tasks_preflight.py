#!/usr/bin/env python3
"""Read-only preflight report for a MedPark SQLite database before task migration."""

import argparse
import json
import sqlite3
from pathlib import Path


def payload(value):
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def main():
    parser = argparse.ArgumentParser(description="주요업무 마이그레이션 사전점검(읽기 전용)")
    parser.add_argument("database", help="점검할 SQLite 백업 파일")
    args = parser.parse_args()
    path = Path(args.database).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"DB 파일을 찾을 수 없습니다: {path}")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"records", "users", "audit_logs"}
    if not required.issubset(tables):
        raise SystemExit(f"필수 테이블이 없습니다: {sorted(required - tables)}")
    rows = db.execute("SELECT * FROM records WHERE entity_type='task' ORDER BY id").fetchall()
    parsed = {row["id"]: payload(row["payload_json"]) for row in rows}
    ids = set(parsed)
    details = [row for row in rows if str(parsed[row["id"]].get("parent_task_id") or "").strip()]
    orphans = [row for row in details if str(parsed[row["id"]].get("parent_task_id") or "").strip() not in ids]
    groups = [row for row in rows if parsed[row["id"]].get("task_kind") == "group"]
    report = {
        "database": str(path),
        "mode": "read_only",
        "legacy_task_count": len(rows),
        "legacy_group_count": len(groups),
        "legacy_detail_count": len(details),
        "legacy_orphan_detail_count": len(orphans),
        "legacy_deleted_count": sum(1 for row in rows if row["deleted_at"]),
        "missing_business_unit_count": sum(1 for row in rows if not parsed[row["id"]].get("business_unit")),
        "missing_owner_count": sum(1 for row in rows if row["owner_id"] is None),
        "missing_due_date_count": sum(1 for row in rows if not row["due_date"]),
        "orphan_legacy_ids": [row["id"] for row in orphans],
        "major_task_schema_present": "major_task_schema_migrations" in tables,
    }
    if "major_task_schema_migrations" in tables:
        report["applied_versions"] = [dict(row) for row in db.execute(
            "SELECT version,checksum,applied_at FROM major_task_schema_migrations ORDER BY applied_at"
        )]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    db.close()


if __name__ == "__main__":
    main()
