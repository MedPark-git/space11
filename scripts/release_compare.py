#!/usr/bin/env python3
"""Compare release-critical invariants between two SQLite databases."""

import argparse
import hashlib
import json
import sqlite3


def connect(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def scalar(db, sql, params=()):
    row = db.execute(sql, params).fetchone()
    return row[0] if row else None


def raw_digest(db):
    digest = hashlib.sha256()
    for row in db.execute(
        "SELECT issue_no,issue_seq,COALESCE(raw_json,'') FROM shipments ORDER BY issue_no,issue_seq"
    ):
        digest.update("\x1f".join(str(value) for value in row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def common_column_digest(before, after, table, order_by):
    before_columns = [row[1] for row in before.execute(f"PRAGMA table_info({table})")]
    after_columns = {row[1] for row in after.execute(f"PRAGMA table_info({table})")}
    columns = [column for column in before_columns if column in after_columns]
    select_list = ",".join(f'"{column}"' for column in columns)

    def digest_rows(db):
        digest = hashlib.sha256()
        for row in db.execute(f"SELECT {select_list} FROM {table} ORDER BY {order_by}"):
            digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    return {"columns": columns, "before": digest_rows(before), "after": digest_rows(after)}


def totals(db):
    result = {}
    for table in ("customer_master", "monthly_sales", "monthly_sales_history", "shipments"):
        result[f"{table}_count"] = int(scalar(db, f"SELECT COUNT(*) FROM {table}") or 0)
    row = db.execute(
        "SELECT ROUND(COALESCE(SUM(krw_supply),0),2),ROUND(COALESCE(SUM(krw_total),0),2) FROM shipments"
    ).fetchone()
    result["shipments_krw_supply"] = row[0]
    result["shipments_krw_total"] = row[1]
    row = db.execute(
        """SELECT ROUND(COALESCE(SUM(amount_usd),0),4),ROUND(COALESCE(SUM(krw_amount),0),2)
           FROM monthly_sales WHERE record_status='active'"""
    ).fetchone()
    result["active_fcst_usd"] = row[0]
    result["active_fcst_krw"] = row[1]
    result["shipments_raw_json_sha256"] = raw_digest(db)
    result["quick_check"] = scalar(db, "PRAGMA quick_check")
    result["foreign_key_violations"] = len(db.execute("PRAGMA foreign_key_check").fetchall())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    before = connect(args.before)
    after = connect(args.after)
    before_totals = totals(before)
    after_totals = totals(after)
    preserved_tables = {
        "customer_master": common_column_digest(before, after, "customer_master", "id"),
        "monthly_sales": common_column_digest(before, after, "monthly_sales", "id"),
        "monthly_sales_history": common_column_digest(before, after, "monthly_sales_history", "id"),
    }
    after.execute("ATTACH DATABASE ? AS prior", (args.before,))
    changed_countries = [dict(row) for row in after.execute(
        """SELECT COALESCE(p.country_code,'') AS old_code,
                  COALESCE(p.country_name,'') AS old_name,
                  COALESCE(n.country_code,'') AS new_code,
                  COALESCE(n.country_name,'') AS new_name,
                  COUNT(*) AS row_count,
                  ROUND(COALESCE(SUM(n.krw_total),0),2) AS krw_total
           FROM shipments n
           JOIN prior.shipments p ON p.issue_no=n.issue_no AND p.issue_seq=n.issue_seq
           WHERE COALESCE(p.country_code,'')<>COALESCE(n.country_code,'')
              OR COALESCE(p.country_name,'')<>COALESCE(n.country_name,'')
           GROUP BY old_code,old_name,new_code,new_name
           ORDER BY row_count DESC,new_name"""
    ).fetchall()]
    invariants = {
        key: before_totals[key] == after_totals[key]
        for key in (
            "customer_master_count", "monthly_sales_count", "monthly_sales_history_count",
            "shipments_count", "shipments_krw_supply", "shipments_krw_total",
            "active_fcst_usd", "active_fcst_krw", "shipments_raw_json_sha256",
        )
    }
    invariants.update({
        f"{table}_existing_fields": values["before"] == values["after"]
        for table, values in preserved_tables.items()
    })
    report = {
        "before": before_totals,
        "after": after_totals,
        "invariants": invariants,
        "preserved_table_digests": preserved_tables,
        "all_critical_invariants_pass": all(invariants.values()),
        "country_normalization_changes": changed_countries,
        "country_change_count": sum(row["row_count"] for row in changed_countries),
        "country_change_krw_total": round(sum(row["krw_total"] for row in changed_countries), 2),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    before.close()
    after.close()
    if not report["all_critical_invariants_pass"] or after_totals["quick_check"] != "ok" or after_totals["foreign_key_violations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
