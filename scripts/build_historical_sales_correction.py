#!/usr/bin/env python3
"""Build the deployable 2024-2025 KRW shipment correction from an ERP .xls export."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import xlrd


VERSION = "2026-08-14-v1"
VALID_TRADES = {"T/T", "TT", "L/C", "LC", "D/P", "DP", "D/A", "DA", "CAD", "C.A.D", "구매승인서"}
YEARS = {"2024", "2025"}


def compact_trade(value):
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def text(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ").strip())


def load_normalized_shipments(project_dir, year):
    path = project_dir / "data" / "source" / "normalized" / f"shipments-{year}.json.gz.b64"
    compressed = base64.b64decode("".join(path.read_text(encoding="ascii").split()), validate=True)
    payload = json.loads(gzip.decompress(compressed).decode("utf-8"))
    return {(row["issue_no"], int(row["issue_seq"])): row for row in payload["shipments"]}


def build(source_path, project_dir):
    workbook = xlrd.open_workbook(str(source_path))
    sheet = workbook.sheet_by_index(0)
    headers = [text(sheet.cell_value(0, col)) for col in range(sheet.ncols)]
    required = {
        "고객", "출고일자", "출고번호", "거래구분", "No", "품번", "출고수량",
        "공급가", "부가세", "합계액",
    }
    missing_headers = sorted(required - set(headers))
    if missing_headers:
        raise ValueError(f"Required ERP columns are missing: {', '.join(missing_headers)}")
    index = {name: headers.index(name) for name in required}

    expected = {}
    for year in YEARS:
        expected.update(load_normalized_shipments(project_dir, year))

    rows = []
    seen = set()
    totals = defaultdict(float)
    issues = defaultdict(set)
    trade_counts = Counter()
    for row_number in range(1, sheet.nrows):
        ship_date = text(sheet.cell_value(row_number, index["출고일자"])).replace("/", "-")
        year = ship_date[:4]
        if year not in YEARS:
            continue
        trade_type = text(sheet.cell_value(row_number, index["거래구분"]))
        if compact_trade(trade_type) not in VALID_TRADES:
            continue
        issue_no = text(sheet.cell_value(row_number, index["출고번호"]))
        issue_seq = int(float(sheet.cell_value(row_number, index["No"])))
        partner_name = text(sheet.cell_value(row_number, index["고객"]))
        product_code = text(sheet.cell_value(row_number, index["품번"]))
        quantity = float(sheet.cell_value(row_number, index["출고수량"]) or 0)
        krw_supply = float(sheet.cell_value(row_number, index["공급가"]) or 0)
        krw_vat = float(sheet.cell_value(row_number, index["부가세"]) or 0)
        krw_total = float(sheet.cell_value(row_number, index["합계액"]) or 0)
        key = (issue_no, issue_seq)
        if key in seen:
            raise ValueError(f"Duplicate issue key in ERP workbook: {key}")
        seen.add(key)
        normalized = expected.get(key)
        if not normalized:
            raise ValueError(f"ERP workbook issue key is missing from normalized source: {key}")
        checks = {
            "ship_date": (ship_date, normalized.get("ship_date")),
            "partner_name": (partner_name, text(normalized.get("partner_name"))),
            "product_code": (product_code, text(normalized.get("product_code"))),
        }
        for field, (actual, prior) in checks.items():
            if actual != prior:
                raise ValueError(f"ERP reconciliation failed for {key} {field}: {actual!r} != {prior!r}")
        if abs(quantity - float(normalized.get("quantity") or 0)) > 0.0001:
            raise ValueError(f"ERP reconciliation failed for {key} quantity")
        if abs(krw_supply + krw_vat - krw_total) > 0.01:
            raise ValueError(f"ERP amount reconciliation failed for {key}")
        rows.append([
            issue_no, issue_seq, ship_date, partner_name, product_code, quantity,
            krw_supply, krw_vat, krw_total, row_number + 1,
        ])
        totals[year] += krw_supply
        issues[year].add(issue_no)
        trade_counts[trade_type] += 1

    if set(expected) != seen:
        missing = sorted(set(expected) - seen)[:10]
        raise ValueError(f"ERP workbook is missing normalized 2024-2025 rows: {missing}")

    payload = {
        "version": VERSION,
        "source_name": source_path.name,
        "sheet_name": sheet.name,
        "period": {"date_from": "2024-01-01", "date_to": "2025-12-31"},
        "columns": [
            "issue_no", "issue_seq", "ship_date", "partner_name", "product_code", "quantity",
            "krw_supply", "krw_vat", "krw_total", "source_row",
        ],
        "expected": {
            "rows": len(rows),
            "issues": sum(len(value) for value in issues.values()),
            "rows_by_year": dict(Counter(row[2][:4] for row in rows)),
            "issues_by_year": {year: len(value) for year, value in sorted(issues.items())},
            "krw_supply_by_year": {year: round(value, 2) for year, value in sorted(totals.items())},
            "krw_supply_total": round(sum(totals.values()), 2),
            "trade_type_rows": dict(sorted(trade_counts.items())),
        },
        "rows": rows,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    output = project_dir / "data" / "source" / "historical_sales_2024_2025.json.gz.b64"
    output.write_text(encoded + "\n", encoding="ascii")
    return output, payload["expected"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    output, expected = build(args.source.resolve(), args.project.resolve())
    print(json.dumps({"output": str(output), "expected": expected}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
