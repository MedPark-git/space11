#!/usr/bin/env python3
"""Create and verify an isolated Customer policy migration candidate.

The source is always opened immutable/read-only.  The script refuses to replace
an output file, so it cannot be pointed at an operational database by accident.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from customer_policy_schema import apply_customer_policy_schema  # noqa: E402


PROTECTED_TABLES = (
    "customer_master",
    "customer_contacts",
    "customer_contracts",
    "customer_payment_terms",
    "customer_logistics",
    "customer_business_areas",
    "customer_sales_countries",
    "customer_meetings",
    "monthly_sales",
    "monthly_sales_history",
    "major_tasks",
    "shipments",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ids_digest(db, table):
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if "id" not in columns:
        return None
    values = [str(row[0]) for row in db.execute(f'SELECT id FROM "{table}" ORDER BY id')]
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


def content_digest(db, table, columns):
    digest = hashlib.sha256()
    quoted = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
    order = ' ORDER BY "id"' if "id" in columns else " ORDER BY rowid"
    for row in db.execute(f'SELECT {quoted} FROM "{table}"{order}'):
        digest.update(json.dumps(list(row), ensure_ascii=False, default=str, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def baseline(db, protected_columns):
    existing = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    result = {}
    for table in PROTECTED_TABLES:
        if table in existing:
            result[table] = {
                "count": db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
                "ids_sha256": ids_digest(db, table),
                "protected_content_sha256": content_digest(db, table, protected_columns[table]),
            }
    if "monthly_sales" in existing:
        columns = {row[1] for row in db.execute("PRAGMA table_info(monthly_sales)")}
        if "customer_master_id" in columns:
            result["monthly_sales"]["unlinked_customer_count"] = db.execute(
                """SELECT COUNT(*) FROM monthly_sales s
                   WHERE s.customer_master_id IS NOT NULL
                     AND NOT EXISTS (SELECT 1 FROM customer_master c WHERE c.id=s.customer_master_id)"""
            ).fetchone()[0]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="latest safe DB backup")
    parser.add_argument("output", type=Path, help="new isolated clone path")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        parser.error("source DB does not exist")
    if source == output:
        parser.error("source and output must be different")
    if output.exists():
        parser.error("output already exists; refusing to overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)

    source_db = sqlite3.connect(f"file:{source}?mode=ro&immutable=1", uri=True)
    target_db = sqlite3.connect(output)
    try:
        source_db.backup(target_db)
        target_db.row_factory = sqlite3.Row
        existing_tables = {
            row[0] for row in target_db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        protected_columns = {
            table: [row[1] for row in target_db.execute(f"PRAGMA table_info({table})")]
            for table in PROTECTED_TABLES if table in existing_tables
        }
        before = baseline(target_db, protected_columns)
        apply_customer_policy_schema(target_db)
        target_db.commit()
        first_schema = [
            tuple(row) for row in target_db.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name LIKE 'customer_%' ORDER BY type,name"
            )
        ]
        apply_customer_policy_schema(target_db)
        target_db.commit()
        second_schema = [
            tuple(row) for row in target_db.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name LIKE 'customer_%' ORDER BY type,name"
            )
        ]
        after = baseline(target_db, protected_columns)
        integrity = target_db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [tuple(row) for row in target_db.execute("PRAGMA foreign_key_check")]
        new_table_counts = {
            table: target_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "customer_organization_roles",
                "customer_business_area_details",
                "customer_languages",
                "customer_contract_products",
                "customer_contract_countries",
            )
        }
        report = {
            "source": str(source),
            "source_sha256": sha256(source),
            "output": str(output),
            "protected_before": before,
            "protected_after": after,
            "protected_unchanged": before == after,
            "schema_idempotent": first_schema == second_schema,
            "new_table_counts": new_table_counts,
            "integrity_check": integrity,
            "foreign_key_violation_count": len(foreign_keys),
            "production_accessed": False,
            "source_written": False,
        }
    finally:
        source_db.close()
        target_db.close()
    # SQLite may finish writing connection metadata while closing the target.
    # Hash only the final, closed artifact so the reported digest is stable.
    report["output_sha256"] = sha256(output)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        if args.report.exists():
            parser.error("report already exists; refusing to overwrite")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not (
        report["protected_unchanged"]
        and report["schema_idempotent"]
        and report["integrity_check"] == "ok"
        and report["foreign_key_violation_count"] == 0
        and all(value == 0 for value in report["new_table_counts"].values())
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
