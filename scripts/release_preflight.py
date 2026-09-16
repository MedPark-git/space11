#!/usr/bin/env python3
"""Read-only release baseline for the MedPark SQLite production database."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def scalar(db, sql, params=()):
    row = db.execute(sql, params).fetchone()
    return row[0] if row else None


def rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def has_table(db, name):
    return bool(scalar(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def table_columns(db, name):
    return {row[1] for row in db.execute(f"PRAGMA table_info({name})").fetchall()}


def shipment_raw_digest(db):
    """Hash ERP source payloads in a stable order so normalization cannot alter raw data unnoticed."""
    digest = hashlib.sha256()
    for row in db.execute(
        "SELECT issue_no,issue_seq,COALESCE(raw_json,'') FROM shipments ORDER BY issue_no,issue_seq"
    ):
        digest.update("\x1f".join(str(value) for value in row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    report = {
        "database": str(db_path),
        "size_bytes": db_path.stat().st_size,
        "sha256": digest,
        "quick_check": scalar(db, "PRAGMA quick_check"),
        "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        "counts": {},
    }
    for table in ("customer_master", "monthly_sales", "monthly_sales_history", "shipments", "erp_sync_runs"):
        if has_table(db, table):
            report["counts"][table] = int(scalar(db, f"SELECT COUNT(*) FROM {table}") or 0)
    if has_table(db, "monthly_sales"):
        monthly_columns = table_columns(db, "monthly_sales")
        report["monthly_sales"] = rows(
            db,
            """SELECT target_month,record_status,sales_status,COUNT(*) AS row_count,
                      ROUND(COALESCE(SUM(amount_usd),0),4) AS amount_usd,
                      ROUND(COALESCE(SUM(krw_amount),0),2) AS krw_amount
               FROM monthly_sales GROUP BY target_month,record_status,sales_status
               ORDER BY target_month,record_status,sales_status""",
        )
        missing_links = ["customer_master_id IS NULL"]
        if "owner_user_id" in monthly_columns:
            missing_links.append("owner_user_id IS NULL")
        report["monthly_sales_unlinked"] = int(scalar(
            db, f"SELECT COUNT(*) FROM monthly_sales WHERE {' OR '.join(missing_links)}"
        ) or 0)
        report["monthly_sales_schema"] = {
            "owner_user_id": "owner_user_id" in monthly_columns,
            "plan_usd_rate": "plan_usd_rate" in monthly_columns,
            "transaction_currency_standard": "transaction_currency_standard" in monthly_columns,
        }
    if has_table(db, "shipments"):
        report["shipments_raw_json_sha256"] = shipment_raw_digest(db)
        report["shipments"] = dict(db.execute(
            """SELECT COUNT(*) AS row_count,COUNT(DISTINCT issue_no) AS issue_count,
                      ROUND(COALESCE(SUM(krw_supply),0),2) AS krw_supply,
                      ROUND(COALESCE(SUM(krw_total),0),2) AS krw_total,
                      MAX(ship_date) AS latest_ship_date,
                      SUM(CASE WHEN raw_json IS NULL OR raw_json='' THEN 1 ELSE 0 END) AS missing_raw
               FROM shipments"""
        ).fetchone())
        report["shipments_by_month"] = rows(
            db,
            """SELECT substr(ship_date,1,7) AS month,COUNT(*) AS row_count,
                      ROUND(COALESCE(SUM(krw_supply),0),2) AS krw_supply,
                      ROUND(COALESCE(SUM(krw_total),0),2) AS krw_total
               FROM shipments GROUP BY substr(ship_date,1,7) ORDER BY month""",
        )
        report["shipments_by_country"] = rows(
            db,
            """SELECT COALESCE(country_code,'') AS country_code,COALESCE(country_name,'') AS country_name,
                      COUNT(*) AS row_count,ROUND(COALESCE(SUM(krw_supply),0),2) AS krw_supply,
                      ROUND(COALESCE(SUM(krw_total),0),2) AS krw_total
               FROM shipments GROUP BY country_code,country_name ORDER BY country_code,country_name""",
        )
    if has_table(db, "erp_sync_runs"):
        latest = db.execute(
            "SELECT * FROM erp_sync_runs WHERE status='success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        report["last_successful_erp_sync"] = dict(latest) if latest else None
    db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
