#!/usr/bin/env python3
"""Clone a SQLite backup, run the task migration on the clone, and verify preservation."""

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from major_tasks_migration import (
    MAJOR_TASKS_LEGACY_MIGRATION_VERSION,
    MAJOR_TASKS_SCHEMA_VERSION,
    apply_major_tasks_legacy_migration,
    apply_major_tasks_schema,
    migrate_legacy_tasks,
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def payload(value):
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def main():
    parser = argparse.ArgumentParser(description="주요업무 마이그레이션 복제 DB 검증")
    parser.add_argument("database", help="운영 DB가 아닌 백업 SQLite 파일")
    args = parser.parse_args()
    source_path = Path(args.database).expanduser().resolve()
    if not source_path.is_file():
        raise SystemExit(f"DB 파일을 찾을 수 없습니다: {source_path}")
    before_hash = sha256(source_path)
    with tempfile.TemporaryDirectory(prefix="major-task-dry-run-") as directory:
        clone_path = Path(directory) / "migration-check.db"
        source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        clone = sqlite3.connect(clone_path)
        source.backup(clone)
        source.close()
        clone.row_factory = sqlite3.Row
        clone.execute("PRAGMA foreign_keys=ON")
        legacy_before = [dict(row) for row in clone.execute(
            "SELECT * FROM records WHERE entity_type='task' ORDER BY id"
        )]
        original_json = {row["id"]: row["payload_json"] or "{}" for row in legacy_before}
        schema_created = apply_major_tasks_schema(clone, now)
        stats = apply_major_tasks_legacy_migration(clone, now)
        clone.commit()
        second = apply_major_tasks_legacy_migration(clone, now)
        raw_idempotency = migrate_legacy_tasks(clone, now)
        clone.commit()
        legacy_after = [dict(row) for row in clone.execute(
            "SELECT * FROM records WHERE entity_type='task' ORDER BY id"
        )]
        mapping_rows = clone.execute("SELECT * FROM major_task_legacy_mappings").fetchall()
        missing_mapping = sorted(set(original_json) - {row["legacy_record_id"] for row in mapping_rows})
        payload_mismatches = [row["legacy_record_id"] for row in mapping_rows
                              if row["legacy_payload_json"] != original_json.get(row["legacy_record_id"], "{}")]
        field_mismatches = []
        for mapping in mapping_rows:
            legacy = next(row for row in legacy_before if row["id"] == mapping["legacy_record_id"])
            target = clone.execute(
                "SELECT name AS title,owner_id,due_date,legacy_amount AS amount,legacy_currency AS currency,legacy_description FROM major_task_actions WHERE id=?"
                if mapping["action_id"] else
                "SELECT title,owner_id,current_target_date AS due_date,legacy_amount AS amount,legacy_currency AS currency,legacy_description FROM major_tasks WHERE id=?",
                (mapping["action_id"] or mapping["task_id"],),
            ).fetchone()
            data = payload(legacy["payload_json"])
            expected_description = str(data.get("description") or "")
            if not target or target["title"] != legacy["title"] or target["owner_id"] != legacy["owner_id"] or target["due_date"] != legacy["due_date"] or float(target["amount"] or 0) != float(legacy["amount"] or 0) or target["currency"] != (legacy["currency"] or "USD") or target["legacy_description"] != expected_description:
                field_mismatches.append(mapping["legacy_record_id"])
        report = {
            "source_database": str(source_path),
            "source_unchanged": before_hash == sha256(source_path),
            "schema_created_on_clone": schema_created,
            "first_run": stats,
            "second_run": second,
            "raw_idempotency_check": raw_idempotency,
            "readiness_markers": [row[0] for row in clone.execute(
                "SELECT version FROM major_task_schema_migrations WHERE version IN (?,?) ORDER BY version",
                (MAJOR_TASKS_SCHEMA_VERSION, MAJOR_TASKS_LEGACY_MIGRATION_VERSION),
            )],
            "legacy_rows_unchanged": legacy_before == legacy_after,
            "major_task_count": clone.execute("SELECT COUNT(*) FROM major_tasks").fetchone()[0],
            "milestone_count": clone.execute("SELECT COUNT(*) FROM major_task_milestones").fetchone()[0],
            "action_count": clone.execute("SELECT COUNT(*) FROM major_task_actions").fetchone()[0],
            "mapping_count": len(mapping_rows),
            "missing_mapping_ids": missing_mapping,
            "payload_mismatch_ids": payload_mismatches,
            "preserved_field_mismatch_ids": field_mismatches,
            "passed": before_hash == sha256(source_path) and legacy_before == legacy_after and not missing_mapping and not payload_mismatches and not field_mismatches and stats["status"] == "applied" and second["status"] == "already_applied" and raw_idempotency["tasks"] == 0 and raw_idempotency["actions"] == 0,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        clone.close()


if __name__ == "__main__":
    main()
