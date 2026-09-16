from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


IMPORT_VERSION = "2026-08-13-v1"
ACTION_KEY = f"source-data-import:{IMPORT_VERSION}"
FORECAST_CORRECTION_VERSION = "2026-08-monthly-sales-v2"
FORECAST_CORRECTION_ACTION_KEY = f"monthly-sales-fcst-correction:{FORECAST_CORRECTION_VERSION}"
FORECAST_CORRECTION_FILE = "monthly_sales_fcst_2026_08.json"
HISTORICAL_SALES_VERSION = "2026-08-14-v1"
HISTORICAL_SALES_ACTION_KEY = f"historical-sales-correction:{HISTORICAL_SALES_VERSION}"
HISTORICAL_SALES_FILE = "historical_sales_2024_2025.json.gz.b64"
SOURCE_FILES = {
    "business_plan": "1. 매출 사업계획_기존자료.xlsx",
    "monthly_sales": "2. 월매출 자료_기존자료.xlsx",
    "shipments": "3. 전체출고이력(ERP)_기존자료.xlsx",
    "cash_plan": "4. 자금계획(비용,지출)_기존자료.xlsx",
    "receivables": "5. 통합미수금 관리_신규자료.xlsx",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _payload(value):
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ").strip())


def _key(value):
    return re.sub(r"[^0-9a-z가-힣]+", "", _text(value).casefold())


def _source_id(kind, key):
    digest = hashlib.sha256(f"medpark-global-maps|{IMPORT_VERSION}|{kind}|{key}".encode("utf-8")).hexdigest()
    return digest[:32]


def _number(value, default=0.0):
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    text = str(value or "").strip()
    if not text or text.startswith("#") or text.upper() in {"X", "-"}:
        return default
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    try:
        result = float(cleaned)
    except (TypeError, ValueError):
        return default
    return -result if negative else result


def _percent(value, default=100.0):
    if value in (None, ""):
        return default
    result = _number(value, default)
    if -2 <= result <= 2:
        result *= 100
    return max(0.0, min(100.0, result))


def _iso_date(value, default_year=2026):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and 20000 <= float(value) <= 80000:
        return (date(1899, 12, 30) + timedelta(days=int(float(value)))).isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    matches = []
    for match in re.finditer(r"(?<!\d)(20\d{2}|\d{2})[./-](\d{1,2})[./-](\d{1,2})(?!\d)", text):
        year = int(match.group(1))
        if year < 100:
            year += 2000
        matches.append((year, int(match.group(2)), int(match.group(3))))
    if not matches:
        for match in re.finditer(r"(?<!\d)(\d{1,2})[./-](\d{1,2})(?!\d)", text):
            matches.append((default_year, int(match.group(1)), int(match.group(2))))
    for year, month, day in reversed(matches):
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def _business_unit(value):
    text = _text(value).casefold()
    if "에스테틱" in text or "aesthetic" in text or "adite" in text or "아디떼" in text:
        return "aesthetic"
    if "메디컬" in text or "메디칼" in text or "medical" in text or "orthopedic" in text:
        return "medical"
    if "덴탈" in text or "dental" in text:
        return "dental"
    return "unclassified"


def _cash_category(value):
    text = _text(value)
    if "덴탈" in text and "수금" in text:
        return "overseas_dental_collection"
    if ("메디컬" in text or "메디칼" in text) and "수금" in text:
        return "overseas_medical_collection"
    if "에스테틱" in text and "수금" in text:
        return "overseas_aesthetic_collection"
    if "전시회" in text:
        return "exhibition"
    if "운반" in text or "운송" in text:
        return "transport"
    if "출장" in text or "여비" in text:
        return "travel"
    if "프로모션" in text or "판매장려" in text:
        return "promotion"
    if "인허가" in text:
        return "regulatory"
    if "수수료" in text:
        return "fee"
    if "수입" in text:
        return "other_income"
    return "other_expense"


def _record_source(source_name, source_row, source_url=""):
    return {
        "import_batch": IMPORT_VERSION,
        "source_name": source_name,
        "source_row": source_row,
        "source_url": source_url,
        "imported_from_legacy": True,
    }


def _insert_record(db, admin, *, source_kind, source_row, entity_type, title, status="active",
                   due_date=None, region="", country="", amount=0, currency="USD", payload=None):
    record_id = _source_id(source_kind, f"{source_row}|{title}")
    now = _now()
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO records
          (id, entity_type, title, owner_id, status, due_date, region, country, amount,
           currency, payload_json, created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id, entity_type, str(title or "원본 데이터")[:200], admin["id"], status,
            due_date, str(region or "")[:80], str(country or "")[:80], float(amount or 0),
            str(currency or "USD").upper()[:8], _safe_json(payload or {}), admin["id"],
            admin["id"], now, now,
        ),
    )
    return record_id, int(cursor.rowcount or 0)


def _account_lookup(db):
    rows = db.execute(
        "SELECT id, title, region, country, payload_json FROM records WHERE entity_type = 'account' AND deleted_at IS NULL"
    ).fetchall()
    result = {}
    for row in rows:
        aliases = [row["title"]]
        payload = _payload(row["payload_json"])
        aliases.extend(payload.get("erp_partner_aliases") or [])
        aliases.extend([payload.get("erp_partner_name"), payload.get("source_account_name")])
        for alias in aliases:
            if _key(alias):
                result[_key(alias)] = row["id"]
    return result


def _find_account_id(account_lookup, name):
    target = _key(name)
    if not target:
        return None
    if target in account_lookup:
        return account_lookup[target]
    if len(target) >= 4:
        matches = [record_id for alias, record_id in account_lookup.items() if target in alias or alias in target]
        if len(set(matches)) == 1:
            return matches[0]
    return None


def _import_google_records(db, admin, google_data):
    counts = {"accounts": 0, "accounts_merged": 0, "transport": 0, "tasks": 0, "assignments": 0, "promotions": 0}
    source_name = google_data["source"]["title"]
    source_url = f"https://docs.google.com/spreadsheets/d/{google_data['source']['spreadsheet_id']}"
    existing_rows = db.execute(
        "SELECT * FROM records WHERE entity_type = 'account' AND deleted_at IS NULL"
    ).fetchall()
    existing = {_key(row["title"]): row for row in existing_rows}

    for item in google_data.get("accounts", []):
        title = _text(item.get("name"))
        if not title:
            continue
        source = _record_source(source_name, item.get("source_row"), source_url)
        price_condition = " · ".join(
            f"{label} {item.get(key)}" for label, key in (
                ("S1", "price_s1"), ("BOSS", "price_boss"), ("COLLA", "price_colla"), ("A1", "price_a1")
            ) if item.get(key) not in (None, "")
        )
        payload = {
            **source,
            "business_unit": "dental",
            "priority": "High" if _number(item.get("plan_neutral")) >= 100000 else "Medium",
            "description": item.get("issues") or item.get("work_history") or "",
            "next_action": item.get("work_history") or item.get("q3_promotion") or "",
            "contact_person": item.get("contact") or "",
            "erp_partner_name": title,
            "erp_partner_code": str(item.get("erp_partner_code") or ""),
            "erp_partner_aliases": [],
            "main_items": item.get("main_items") or "",
            "current_price_condition": price_condition,
            "source_owner_name": item.get("source_owner_name") or "",
            "source_primary_owner": item.get("source_primary_owner") or "",
            "source_secondary_owner": item.get("source_secondary_owner") or "",
            "support_owner": item.get("support_owner") or "",
            "backup_owner": item.get("backup_owner") or "",
            "contract_type": item.get("contract_type") or "",
            "contract_status": item.get("contract_status") or "",
            "contract_start": item.get("contract_start") or "",
            "contract_end": item.get("contract_end") or "",
            "contract_amount": _number(item.get("contract_amount")),
            "total_order_count": _number(item.get("total_order_count")),
            "total_order_amount": _number(item.get("total_order_amount")),
            "average_order_amount": _number(item.get("average_order_amount")),
            "sales_2025": _number(item.get("sales_2025")),
            "sales_2026": _number(item.get("sales_2026")),
            "achievement_rate": _percent(item.get("achievement_rate"), 0),
            "plan_2026_optimistic": _number(item.get("plan_optimistic")),
            "plan_2026_neutral": _number(item.get("plan_neutral")),
            "plan_2026_conservative": _number(item.get("plan_conservative")),
            "handled_implants": item.get("handled_implants") or "",
            "order_cycle": item.get("order_cycle") or "",
            "last_order": item.get("last_order") or "",
            "next_order_possible": item.get("next_order_possible") or "",
            "latest_contact_date": item.get("latest_contact_date") or "",
            "latest_meeting_date": item.get("latest_meeting_date") or "",
            "education_update": item.get("education_update") or "",
            "work_history": item.get("work_history") or "",
            "account_classification": item.get("classification") or "",
            "medpark_fill_target": item.get("medpark_fill_target") or "",
            "packaging_regulatory_issue": item.get("packaging_regulatory_issue") or "",
            "dental_kit_promotion": item.get("dental_kit_promotion") or "",
            "q3_promotion": item.get("q3_promotion") or "",
            "promotion_target_amount": _number(item.get("promotion_target_amount")),
        }
        existing_row = existing.get(_key(title))
        if existing_row:
            before = _payload(existing_row["payload_json"])
            merged = dict(before)
            seed_like = set(before).issubset({"stage", "contact", "priority"})
            for key, value in payload.items():
                if seed_like or merged.get(key) in (None, "", [], {}):
                    merged[key] = value
            region = item.get("region") if seed_like or not existing_row["region"] else existing_row["region"]
            country = item.get("country") if seed_like or not existing_row["country"] else existing_row["country"]
            db.execute(
                "UPDATE records SET region = ?, country = ?, payload_json = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                (region or "", country or "", _safe_json(merged), admin["id"], _now(), existing_row["id"]),
            )
            counts["accounts_merged"] += 1
        else:
            _, inserted = _insert_record(
                db, admin, source_kind="google-account", source_row=item.get("source_row"),
                entity_type="account", title=title, status="active", region=item.get("region"),
                country=item.get("country"), amount=0, currency="USD", payload=payload,
            )
            counts["accounts"] += inserted
    account_lookup = _account_lookup(db)

    for item in google_data.get("transports", []):
        account_name = _text(item.get("account_name"))
        account_id = _find_account_id(account_lookup, account_name)
        forwarder = item.get("nominated_forwarder") or item.get("medpark_forwarder") or (
            "DHL" if item.get("dhl") else "FEDEX" if item.get("fedex") else ""
        )
        description_parts = [item.get("label_requirements"), item.get("document_requirements"), item.get("other_requirements"), item.get("notes")]
        payload = {
            **_record_source(source_name, item.get("source_row"), source_url),
            "account_id": account_id or "", "account_name": account_name,
            "business_unit": "dental", "forwarder": forwarder or "",
            "courier_account": item.get("courier_account") or "",
            "nominated_forwarder": item.get("nominated_forwarder") or "",
            "nominated_contact": item.get("nominated_contact") or "",
            "nominated_email": item.get("nominated_email") or "",
            "nominated_phone": item.get("nominated_phone") or "",
            "medpark_forwarder": item.get("medpark_forwarder") or "",
            "medpark_contact": item.get("medpark_contact") or "",
            "medpark_phone": item.get("medpark_phone") or "",
            "label_requirements": item.get("label_requirements") or "",
            "document_requirements": item.get("document_requirements") or "",
            "description": "\n".join(str(value) for value in description_parts if value),
        }
        _, inserted = _insert_record(
            db, admin, source_kind="google-transport", source_row=item.get("source_row"),
            entity_type="transport", title=f"{account_name} 운송정보", status="active",
            country=item.get("country"), payload=payload,
        )
        counts["transport"] += inserted

    for item in google_data.get("tasks", []):
        description = _text(item.get("description"))
        first_line = str(item.get("description") or "").strip().splitlines()[0] if item.get("description") else "주요 업무"
        title = _text(item.get("keyword")) or _text(first_line)
        due_date = _iso_date(item.get("target_completion_raw"))
        payload = {
            **_record_source(source_name, item.get("source_row"), source_url),
            "business_unit": "unclassified", "priority": "High",
            "description": item.get("description") or "", "category": item.get("category") or "",
            "keyword": item.get("keyword") or "", "source_owner_name": item.get("source_owner_name") or "",
            "first_report_at": item.get("first_report_at") or "", "target_completion_raw": item.get("target_completion_raw") or "",
            "report_time": item.get("report_time") or "", "source_notes": item.get("notes") or "",
        }
        _, inserted = _insert_record(
            db, admin, source_kind="google-task", source_row=item.get("source_row"),
            entity_type="task", title=title, status=item.get("status") or "in_progress",
            due_date=due_date, payload=payload,
        )
        counts["tasks"] += inserted

    for item in google_data.get("assignments", []):
        country = _text(item.get("country"))
        owners = " / ".join(filter(None, [item.get("primary_owner"), item.get("secondary_owner")]))
        payload = {
            **_record_source(source_name, item.get("source_row"), source_url),
            "business_unit": "dental", "priority": "Medium",
            "description": f"정 담당 {item.get('primary_owner') or '-'} · 부 담당 {item.get('secondary_owner') or '-'}",
            "primary_owner": item.get("primary_owner") or "", "secondary_owner": item.get("secondary_owner") or "",
            "support_owner": item.get("support_owner") or "", "medpark_bone_owner": item.get("medpark_bone_owner") or "",
            "adite_owner": item.get("adite_owner") or "", "assignment_owner_names": owners,
            "source_owner_name": item.get("primary_owner") or "",
        }
        _, inserted = _insert_record(
            db, admin, source_kind="google-assignment", source_row=item.get("source_row"),
            entity_type="task", title=f"담당지역 배정 · {country}", status="done",
            region=item.get("region"), country=country, payload=payload,
        )
        counts["assignments"] += inserted

    for item in google_data.get("accounts", []):
        q3 = _text(item.get("q3_promotion"))
        kit = _text(item.get("dental_kit_promotion"))
        account_name = _text(item.get("name"))
        account_id = _find_account_id(account_lookup, account_name)
        promotions = []
        if q3 and "대상아님" not in q3.replace(" ", "") and q3 not in {"X", "#N/A", "해당X"}:
            promotions.append(("Q3", "3/4분기 할증 프로모션", q3))
        if kit and kit not in {"X", "#N/A", "해당X", "없음"}:
            promotions.append(("KIT", "덴탈 KIT 제공 프로모션", kit))
        for promo_code, item_name, details in promotions:
            promo_id = f"SRC-{promo_code}-{int(_number(item.get('no'), item.get('source_row') or 0)):03d}"
            amount = _number(item.get("promotion_target_amount"))
            payload = {
                **_record_source(source_name, item.get("source_row"), source_url),
                "promotion_id": promo_id, "account_id": account_id or "", "account_name": account_name,
                "source_owner_name": item.get("source_owner_name") or "",
                "business_unit": "dental", "item_name": item_name, "promotion_terms": details,
                "description": details, "target_month": "2026-08", "start_date": "2026-07-01",
                "end_date": "2026-09-30", "target_ship_date": "2026-09-30",
                "forecast_stage": "sales_activity", "forecast_confidence": 20,
                "forecast_included": False, "target_units": 0, "achieved_units": 0,
                "achieved_amount": 0, "budget_amount": 0,
            }
            status = "running" if any(marker in details for marker in ("진행", "확정", "발송", "나가")) else "planned"
            _, inserted = _insert_record(
                db, admin, source_kind=f"google-promotion-{promo_code.casefold()}", source_row=item.get("source_row"),
                entity_type="promotion", title=f"{account_name} · {item_name}", status=status,
                due_date="2026-09-30", region=item.get("region"), country=item.get("country"),
                amount=amount, currency="USD", payload=payload,
            )
            counts["promotions"] += inserted
    return counts


def _plan_key(value):
    key = _key(value)
    aliases = {"asnnan": "asnan", "asnan": "asnan", "josephllc": "josephllp"}
    return aliases.get(key, key)


def _import_business_plan(db, admin, workbook_path):
    from openpyxl import load_workbook

    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    scenarios = {"낙관_피벗": "optimistic", "중립_피벗": "neutral", "보수_피벗": "conservative"}
    plans = {}
    for sheet_name, scenario in scenarios.items():
        ws = wb[sheet_name]
        for row_number, row in enumerate(ws.iter_rows(min_row=4, max_col=14, values_only=True), 4):
            name = _text(row[0])
            if not name or "grand total" in name.casefold() or "총합" in name:
                continue
            key = _plan_key(name)
            entry = plans.setdefault(key, {"name": name, "source_rows": {}, "scenarios": {}})
            entry["source_rows"][scenario] = row_number
            entry["scenarios"][scenario] = {
                "total": _number(row[1]),
                "months": [_number(value) for value in row[2:14]],
            }
    account_lookup = _account_lookup(db)
    inserted = 0
    for key, entry in plans.items():
        neutral = entry["scenarios"].get("neutral", {}).get("total", 0)
        target = neutral or entry["scenarios"].get("optimistic", {}).get("total", 0) or entry["scenarios"].get("conservative", {}).get("total", 0)
        account_id = _find_account_id(account_lookup, entry["name"])
        payload = {
            **_record_source(SOURCE_FILES["business_plan"], min(entry["source_rows"].values())),
            "account_id": account_id or "", "account_name": entry["name"], "business_unit": "dental",
            "goal_type": "sales", "target_unit": "USD", "target_value": target,
            "actual_value": 0, "original_target_date": "2026-12-31", "mid_review_date": "2026-06-30",
            "description": "2026년 거래처별 낙관·중립·보수 월별 사업계획",
            "plan_year": 2026, "scenario_plan": entry["scenarios"], "scenario_source_rows": entry["source_rows"],
        }
        _, count = _insert_record(
            db, admin, source_kind="xlsx-business-plan", source_row=key,
            entity_type="goal", title=f"2026 사업계획 · {entry['name']}", status="active",
            due_date="2026-12-31", amount=target, currency="USD", payload=payload,
        )
        inserted += count
    return {"goals": inserted, "source_accounts": len(plans)}


def _import_monthly_forecast(db, admin, workbook_path):
    from openpyxl import load_workbook

    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    ws = wb["raw data"]
    month = "2025-11"
    existing_cycle = db.execute(
        "SELECT * FROM forecast_cycles WHERE forecast_month = ? AND round_no = 1", (month,)
    ).fetchone()
    now = _now()
    if existing_cycle:
        cycle_id = existing_cycle["id"]
        cycle_inserted = 0
    else:
        cycle_id = _source_id("forecast-cycle", f"{month}|1")
        db.execute(
            """
            INSERT INTO forecast_cycles
              (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, cny_krw, status,
               created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, 1, ?, 1500, 1650, 225, 'closed', ?, ?, ?, ?)
            """,
            (cycle_id, month, "2025-10-25", admin["id"], admin["id"], now, now),
        )
        cycle_inserted = 1
    account_lookup = _account_lookup(db)
    items = 0
    for row_number, row in enumerate(ws.iter_rows(min_row=5, max_row=33, max_col=16, values_only=True), 5):
        if row[0] in (None, ""):
            continue
        account_name = _text(row[6]) or f"{_text(row[5])} 신규 업체"
        title = f"{month} 매출추진 · {account_name}"
        raw_status = _text(row[3])
        agreement = _text(row[4])
        confidence = 60 if "합의" in agreement else 25 if "risk" in _text(row[11]).casefold() else 35
        expected = _iso_date(row[14], default_year=2025) or _iso_date(row[13], default_year=2025)
        notes = "\n".join(str(value) for value in (row[12], row[15]) if value not in (None, ""))
        source_owner = _text(row[7])
        account_id = _find_account_id(account_lookup, account_name)
        item_id = _source_id("xlsx-monthly-forecast", row_number)
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO forecast_items
              (id, cycle_id, title, account_id, account_name, business_unit, item_name,
               stage, confidence, foreign_amount, currency, expected_ship_date, owner_id, notes,
               status, source_type, source_id, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, '', 'sales_activity', ?, ?, 'USD', ?, ?, ?,
                    'active', 'legacy_monthly_xlsx', ?, ?, ?, ?, ?)
            """,
            (
                item_id, cycle_id, title, account_id, account_name, _business_unit(row[1]),
                confidence, _number(row[10]), expected, admin["id"],
                f"원담당자: {source_owner or '-'} · 원본 상태: {raw_status or '-'} · 가능성: {_text(row[11]) or '-'}\n{notes}".strip(),
                f"row-{row_number}", admin["id"], admin["id"], now, now,
            ),
        )
        items += int(cursor.rowcount or 0)
    return {"forecast_cycles": cycle_inserted, "forecast_items": items}


def _import_cash_plan(db, admin, workbook_path):
    from openpyxl import load_workbook

    ws = load_workbook(workbook_path, read_only=True, data_only=True)["8월실적"]
    inserted = 0
    for row_number, row in enumerate(ws.iter_rows(min_row=8, max_row=40, max_col=41, values_only=True), 8):
        flow_label = _text(row[6])
        if flow_label not in {"수금", "지출"}:
            continue
        flow_type = "cash_in" if flow_label == "수금" else "cash_out"
        currency = _text(row[14]).upper() or "KRW"
        foreign_amount = _number(row[15])
        cash_in_krw = _number(row[16])
        cash_out_krw = _number(row[19]) or _number(row[26])
        if currency != "KRW" and foreign_amount:
            amount = foreign_amount
        else:
            currency = "KRW"
            amount = cash_in_krw if flow_type == "cash_in" else cash_out_krw
        plan_date = _iso_date(row[9]) or _iso_date(row[11])
        execution_date = _iso_date(row[11])
        actual = _text(row[0]).upper() == "ACT"
        title = " · ".join(filter(None, [_text(row[12]), _text(row[13])])) or f"자금계획 {row_number}행"
        plan_krw = cash_in_krw if flow_type == "cash_in" else cash_out_krw
        exchange_rate = plan_krw / foreign_amount if foreign_amount and plan_krw else (1 if currency == "KRW" else 0)
        payload = {
            **_record_source(SOURCE_FILES["cash_plan"], row_number),
            "business_unit": _business_unit(row[5]), "flow_type": flow_type,
            "plan_actual_type": "actual" if actual else "planned",
            "execution_category": _cash_category(row[7]), "transaction_type": _text(row[8]),
            "plan_date": plan_date or "", "card_payment_date": _iso_date(row[10]) or "",
            "execution_date": execution_date if actual else "", "maturity_date": _iso_date(row[28]) or "",
            "counterparty": _text(row[12]), "description": _text(row[13]),
            "exchange_rate": exchange_rate, "adjustment_rate": _percent(row[17]),
            "payment_rate": _percent(row[20]), "actual_foreign_amount": foreign_amount if actual and currency != "KRW" else 0,
            "actual_krw_amount": plan_krw if actual else 0, "payment_condition": _text(row[27]),
            "previous_month_carryover": bool(row[29]), "current_month_carryover": bool(row[30]),
            "intentional_carryover": bool(row[37]), "split_payment": bool(row[38]),
            "source_owner_name": _text(row[31]), "cash_notes": " · ".join(filter(None, [_text(row[25]), _text(row[39]), _text(row[40])])),
            "source_cash_in_krw": cash_in_krw, "source_cash_out_krw": cash_out_krw,
        }
        status = "executed" if actual else "carried_over" if row[29] or row[30] else "planned"
        _, count = _insert_record(
            db, admin, source_kind="xlsx-cash-plan", source_row=row_number,
            entity_type="cash_plan", title=title, status=status, due_date=plan_date,
            amount=amount, currency=currency, payload=payload,
        )
        inserted += count
    return {"cash_plan": inserted}


def _import_receivables(db, admin, workbook_path):
    from openpyxl import load_workbook

    ws = load_workbook(workbook_path, read_only=True, data_only=True)["Sheet1"]
    terms = {}
    for row_number, row in enumerate(ws.iter_rows(min_row=4, max_row=21, max_col=14, values_only=True), 4):
        if not row[1]:
            continue
        terms[_key(row[1])] = {
            "country": _text(row[2]), "label": _text(row[3]),
            "advance_ratio": _percent(row[4], 0),
            "installment_1_days": _number(row[5]), "installment_1_ratio": _percent(row[6], 0),
            "installment_2_days": _number(row[7]), "installment_2_ratio": _percent(row[8], 0),
            "installment_3_days": _number(row[9]), "installment_3_ratio": _percent(row[10], 0),
            "installment_4_days": _number(row[11]), "installment_4_ratio": _percent(row[12], 0),
            "notes": _text(row[13]),
        }
    account_lookup = _account_lookup(db)
    inserted = 0
    for row_number, row in enumerate(ws.iter_rows(min_row=38, max_col=30, values_only=True), 38):
        account_name = _text(row[1])
        amount = _number(row[3])
        if not account_name or amount <= 0:
            continue
        term = terms.get(_key(account_name), {})
        account_id = _find_account_id(account_lookup, account_name)
        ship_date = _iso_date(row[2])
        received = sum(_number(row[index]) for index in (6, 16, 18, 20, 22))
        balance = _number(row[28], max(0, amount - received))
        payload = {
            **_record_source(SOURCE_FILES["receivables"], row_number),
            "account_id": account_id or "", "account_name": account_name, "business_unit": "dental",
            "invoice_no": _text(row[4]) or f"LEGACY-AR-{row_number}", "shipment_no": "",
            "ship_date": ship_date or "", "invoice_date": ship_date or "",
            "payment_condition_label": term.get("label", ""), "receivable_exchange_rate": 0,
            "advance_ratio": term.get("advance_ratio", 0),
            "installment_1_days": term.get("installment_1_days", 0), "installment_1_ratio": term.get("installment_1_ratio", 0),
            "installment_2_days": term.get("installment_2_days", 0), "installment_2_ratio": term.get("installment_2_ratio", 0),
            "installment_3_days": term.get("installment_3_days", 0), "installment_3_ratio": term.get("installment_3_ratio", 0),
            "installment_4_days": term.get("installment_4_days", 0), "installment_4_ratio": term.get("installment_4_ratio", 0),
            "advance_received_date": _iso_date(row[5]) or "", "advance_received_amount": _number(row[6]),
            "receipt_1_date": _iso_date(row[15]) or "", "receipt_1_amount": _number(row[16]),
            "receipt_2_date": _iso_date(row[17]) or "", "receipt_2_amount": _number(row[18]),
            "receipt_3_date": _iso_date(row[19]) or "", "receipt_3_amount": _number(row[20]),
            "receipt_4_date": _iso_date(row[21]) or "", "receipt_4_amount": _number(row[22]),
            "collection_status": "collection_required", "risk_level": "p1" if any("독촉" in _text(row[index]) for index in range(23, 27)) else "watch",
            "shipment_hold": False, "legal_review": False, "representative_approval": False,
            "recovery_plan": " · ".join(_text(row[index]) for index in range(23, 27) if row[index]),
            "source_balance": balance, "source_received": _number(row[27]),
        }
        due_date = _iso_date(row[7]) or ship_date
        status = "paid" if balance <= 0 else "overdue" if due_date and due_date < date.today().isoformat() else "current"
        _, count = _insert_record(
            db, admin, source_kind="xlsx-receivable", source_row=row_number,
            entity_type="receivable", title=f"{account_name} 미수채권", status=status,
            due_date=due_date, country=term.get("country", ""), amount=amount, currency="USD", payload=payload,
        )
        inserted += count

    rows = db.execute("SELECT id, title, payload_json FROM records WHERE entity_type = 'account' AND deleted_at IS NULL").fetchall()
    for row in rows:
        term = terms.get(_key(row["title"]))
        if not term:
            continue
        payload = _payload(row["payload_json"])
        payload.update({
            "ar_condition_label": term.get("label", ""), "ar_advance_ratio": term.get("advance_ratio", 0),
            "ar_installment_1_days": term.get("installment_1_days", 0), "ar_installment_1_ratio": term.get("installment_1_ratio", 0),
            "ar_installment_2_days": term.get("installment_2_days", 0), "ar_installment_2_ratio": term.get("installment_2_ratio", 0),
            "ar_installment_3_days": term.get("installment_3_days", 0), "ar_installment_3_ratio": term.get("installment_3_ratio", 0),
            "ar_installment_4_days": term.get("installment_4_days", 0), "ar_installment_4_ratio": term.get("installment_4_ratio", 0),
            "ar_terms_notes": term.get("notes", ""),
        })
        db.execute("UPDATE records SET payload_json = ?, updated_by = ?, updated_at = ? WHERE id = ?", (_safe_json(payload), admin["id"], _now(), row["id"]))
    return {"receivables": inserted, "ar_term_accounts": len(terms)}


def _import_shipments(db, admin, workbook_path, country_resolver=None, business_classifier=None):
    from openpyxl import load_workbook

    ws = load_workbook(workbook_path, read_only=True, data_only=True)["기초_(외화)"]
    header_row = next(ws.iter_rows(min_row=1, max_row=1, max_col=35, values_only=True))
    inserted = 0
    source_lines = 0
    excluded_lines = 0
    source_issues = set()
    included_issues = set()
    foreign_total = 0.0
    krw_total = 0.0
    min_date = None
    max_date = None
    synced_at = _now()
    legacy_rates = {
        "KRW": 1.0, "USD": 1430.0, "EUR": 1650.0, "CNY": 225.0,
        "AED": 390.0, "SAR": 381.0, "SGD": 1100.0, "CHF": 1800.0,
        "JPY": 9.5, "TRY": 35.0, "GBP": 1900.0, "INR": 17.0,
    }
    for row_number, row in enumerate(ws.iter_rows(min_row=2, max_row=12234, max_col=35, values_only=True), 2):
        issue_no = _text(row[1])
        if not issue_no:
            continue
        source_lines += 1
        source_issues.add(issue_no)
        trade_type = _text(row[4])
        compact_trade = re.sub(r"\s+", "", trade_type).upper()
        if any(marker in compact_trade for marker in ("LOCAL", "DOMESTIC", "국내", "로컬")):
            excluded_lines += 1
            continue
        if compact_trade not in {"T/T", "TT", "L/C", "LC", "D/P", "DP", "D/A", "DA", "CAD", "C.A.D", "구매승인서"}:
            excluded_lines += 1
            continue
        domestic_context = " ".join(_text(value) for value in (row[27], row[29], row[30]))
        product_context = " ".join(_text(value) for value in (row[8], row[9], row[10]))
        if any(marker in domestic_context for marker in ("수도권", "서울")) or (
            "국내" in product_context and _text(row[5]).upper() == "KRW"
        ):
            excluded_lines += 1
            continue
        ship_date = _iso_date(row[0])
        if not ship_date:
            continue
        included_issues.add(issue_no)
        min_date = min(min_date, ship_date) if min_date else ship_date
        max_date = max(max_date, ship_date) if max_date else ship_date
        classification = _text(row[28])
        country_raw = _text(row[30])
        country = country_resolver(country_raw) if country_resolver else None
        header = {
            "soFgNm": trade_type, "attrNm": _text(row[2]),
            "partnerClassification": classification, "countryNm": country_raw,
        }
        line = {
            "itemCd": _text(row[8]), "itemNm": _text(row[9]), "itemDc": _text(row[10]),
            "itemsetNm": _text(row[26]), "pjtNm": _text(row[16]),
        }
        if business_classifier:
            unit = business_classifier(header, line, classification)
        else:
            unit = _business_unit(f"{classification} {_text(row[26])} {_text(row[9])}")
        foreign_amount = _number(row[14])
        currency = _text(row[5]).upper() or "KRW"
        exchange_rate = legacy_rates.get(currency, legacy_rates["USD"])
        krw_supply = foreign_amount * exchange_rate
        foreign_total += foreign_amount
        krw_total += krw_supply
        issue_seq = int(_number(row[7], row_number))
        raw = {
            "source": SOURCE_FILES["shipments"], "source_row": row_number,
            "header": header, "line": line,
            "order_no": _text(row[23]), "order_seq": row[24], "lc_no": _text(row[25]),
            "warehouse": _text(row[18]), "warehouse_location": _text(row[19]), "lot_no": _text(row[20]),
            "source_helper_amount": _number(row[32]),
            "legacy_krw_rate": exchange_rate,
            "legacy_krw_rate_note": "원본 파일에 면장 발급시점 환율이 없어 2026-08-05 자금계획 기준환율 및 통화별 보조환율로 환산",
        }
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO shipments
              (issue_no, issue_seq, ship_date, is_overseas, trade_type, business_unit,
               partner_classification, metadata_version, partner_code, partner_name,
               country_code, country_name, product_code, product_name, specification,
               quantity, currency, exchange_rate, foreign_amount, krw_supply, krw_vat,
               krw_total, manager_name, department_name, raw_json, synced_at)
            VALUES (?, ?, ?, 1, ?, ?, ?, 1, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                issue_no, issue_seq, ship_date, trade_type, unit, classification, _text(row[2]),
                country.get("map_id") if country else None, country.get("name") if country else country_raw,
                _text(row[8]), _text(row[9]), _text(row[10]), _number(row[12]), currency,
                exchange_rate, foreign_amount, krw_supply, krw_supply, _text(row[6]), _text(row[29]),
                _safe_json(raw), synced_at,
            ),
        )
        inserted += int(cursor.rowcount or 0)
    if min_date and max_date:
        db.execute(
            """
            INSERT INTO erp_sync_runs
              (started_at, finished_at, requested_by, date_from, date_to, status,
               header_count, source_header_count, excluded_header_count, line_count,
               foreign_amount, krw_amount, error_message)
            VALUES (?, ?, ?, ?, ?, 'success', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                synced_at, synced_at, admin["id"], min_date, max_date, len(included_issues),
                len(source_issues), max(0, len(source_issues) - len(included_issues)), inserted,
                foreign_total, krw_total,
                f"기존 ERP 엑셀 이관 · LOCAL/국내 제외 {excluded_lines}행 · 과거 면장환율 미포함으로 기준환율 추정환산",
            ),
        )
    return {
        "shipment_source_lines": source_lines, "shipments": inserted,
        "shipment_excluded_lines": excluded_lines, "shipment_headers": len(included_issues),
        "shipment_foreign_amount": round(foreign_total, 2), "shipment_krw_amount": round(krw_total, 2),
        "shipment_date_from": min_date, "shipment_date_to": max_date,
    }


def _import_exchange_rates(db, cash_workbook_path):
    from openpyxl import load_workbook

    ws = load_workbook(cash_workbook_path, read_only=True, data_only=True)["8월실적"]
    rates = {"USD": _number(ws["P2"].value), "EUR": _number(ws["P3"].value), "CNY": _number(ws["P4"].value)}
    rate_date = _iso_date(ws["F4"].value) or "2026-08-05"
    inserted = 0
    for currency, rate in rates.items():
        if rate <= 0:
            continue
        cursor = db.execute(
            "INSERT OR IGNORE INTO exchange_rates (rate_date, currency, krw_rate, source, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (rate_date, currency, rate, "기존 자금계획 기준환율", _now()),
        )
        inserted += int(cursor.rowcount or 0)
    return {"exchange_rates": inserted, "exchange_rate_date": rate_date, "exchange_rate_values": rates}


def _load_normalized_payloads(source_dir):
    normalized_dir = Path(source_dir) / "normalized"
    manifest_path = normalized_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != IMPORT_VERSION:
        raise ValueError("Normalized import manifest version does not match the application importer")
    if manifest.get("encoding") != "base64+gzip+json":
        raise ValueError("Unsupported normalized import encoding")

    payloads = {}
    for chunk in manifest.get("chunks") or []:
        name = _text(chunk.get("name"))
        filename = _text(chunk.get("file"))
        if not name or not filename or Path(filename).name != filename:
            raise ValueError("Invalid normalized import chunk declaration")
        encoded = "".join((normalized_dir / filename).read_text(encoding="ascii").split())
        compressed = base64.b64decode(encoded, validate=True)
        digest = hashlib.sha256(compressed).hexdigest()
        if digest != chunk.get("sha256"):
            raise ValueError(f"Normalized import checksum mismatch: {name}")
        payload = json.loads(gzip.decompress(compressed).decode("utf-8"))
        if payload.get("version") != IMPORT_VERSION:
            raise ValueError(f"Normalized import chunk version mismatch: {name}")
        if name == "modules":
            row_count = len(payload.get("records") or [])
            if payload.get("kind") != "modules":
                raise ValueError("Invalid normalized modules chunk")
        else:
            row_count = len(payload.get("shipments") or [])
            if payload.get("kind") != "shipments":
                raise ValueError(f"Invalid normalized shipment chunk: {name}")
        if row_count != int(chunk.get("rows") or 0):
            raise ValueError(f"Normalized import row count mismatch: {name}")
        payloads[name] = payload

    if "modules" not in payloads:
        raise ValueError("Normalized import modules chunk is missing")
    return manifest, payloads


def _import_normalized_payloads(db, admin, source_dir):
    manifest, payloads = _load_normalized_payloads(source_dir)
    modules = payloads["modules"]
    account_lookup = _account_lookup(db)
    record_counts = {"goal": 0, "cash_plan": 0, "receivable": 0}

    for row in modules.get("records") or []:
        payload = _payload(row.get("payload_json"))
        if payload.get("source_name") == SOURCE_FILES["business_plan"]:
            continue
        account_name = payload.get("account_name") or ""
        mapped_account_id = _find_account_id(account_lookup, account_name)
        if mapped_account_id:
            payload["account_id"] = mapped_account_id
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO records
              (id, entity_type, title, owner_id, status, due_date, region, country, amount,
               currency, payload_json, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"], row["entity_type"], row["title"], admin["id"], row.get("status") or "active",
                row.get("due_date"), row.get("region") or "", row.get("country") or "",
                float(row.get("amount") or 0), row.get("currency") or "USD", _safe_json(payload),
                admin["id"], admin["id"], row.get("created_at") or _now(), row.get("updated_at") or _now(),
            ),
        )
        if row.get("entity_type") in record_counts:
            record_counts[row["entity_type"]] += int(cursor.rowcount or 0)

    ar_term_accounts = 0
    for patch in modules.get("account_patches") or []:
        account_id = _find_account_id(account_lookup, patch.get("account_name"))
        if not account_id:
            continue
        account_row = db.execute("SELECT payload_json FROM records WHERE id = ?", (account_id,)).fetchone()
        account_payload = _payload(account_row["payload_json"] if account_row else "{}")
        changed = False
        for key, value in (patch.get("payload") or {}).items():
            if account_payload.get(key) in (None, "", [], {}):
                account_payload[key] = value
                changed = True
        if changed:
            db.execute(
                "UPDATE records SET payload_json = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                (_safe_json(account_payload), admin["id"], _now(), account_id),
            )
            ar_term_accounts += 1

    cycle_map = {}
    forecast_cycles = 0
    for row in modules.get("cycles") or []:
        existing = db.execute(
            "SELECT id FROM forecast_cycles WHERE forecast_month = ? AND round_no = ?",
            (row["forecast_month"], int(row["round_no"])),
        ).fetchone()
        if existing:
            cycle_map[row["id"]] = existing["id"]
            continue
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO forecast_cycles
              (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, cny_krw,
               status, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"], row["forecast_month"], int(row["round_no"]), row["as_of_date"],
                float(row.get("usd_krw") or 0), float(row.get("eur_krw") or 0),
                float(row.get("cny_krw") or 0), row.get("status") or "open", admin["id"], admin["id"],
                row.get("created_at") or _now(), row.get("updated_at") or _now(),
            ),
        )
        forecast_cycles += int(cursor.rowcount or 0)
        cycle_map[row["id"]] = row["id"]

    forecast_items = 0
    for row in modules.get("forecast_items") or []:
        cycle_id = cycle_map.get(row["cycle_id"])
        if not cycle_id:
            raise ValueError(f"Forecast cycle mapping is missing for item {row['id']}")
        account_id = _find_account_id(account_lookup, row.get("account_name"))
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO forecast_items
              (id, cycle_id, title, account_id, account_name, business_unit, item_name, stage,
               confidence, foreign_amount, currency, expected_ship_date, owner_id, notes, status,
               carryover_from_id, carryover_from_month, copied_from_id, source_type, source_id,
               created_by, updated_by, created_at, updated_at, deleted_at, deleted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"], cycle_id, row["title"], account_id, row.get("account_name") or "",
                row.get("business_unit") or "unclassified", row.get("item_name") or "",
                row.get("stage") or "sales_activity", float(row.get("confidence") or 0),
                float(row.get("foreign_amount") or 0), row.get("currency") or "USD",
                row.get("expected_ship_date"), admin["id"], row.get("notes") or "",
                row.get("status") or "active", row.get("carryover_from_id"),
                row.get("carryover_from_month"), row.get("copied_from_id"), row.get("source_type"),
                row.get("source_id"), admin["id"], admin["id"], row.get("created_at") or _now(),
                row.get("updated_at") or _now(), row.get("deleted_at"), None,
            ),
        )
        forecast_items += int(cursor.rowcount or 0)

    exchange_rates = 0
    exchange_rate_values = {}
    exchange_rate_date = None
    for row in modules.get("exchange_rates") or []:
        cursor = db.execute(
            "INSERT OR IGNORE INTO exchange_rates (rate_date, currency, krw_rate, source, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (row["rate_date"], row["currency"], float(row["krw_rate"]), row["source"], row["fetched_at"]),
        )
        exchange_rates += int(cursor.rowcount or 0)
        exchange_rate_date = row["rate_date"]
        exchange_rate_values[row["currency"]] = float(row["krw_rate"])

    shipments = 0
    shipment_issues = set()
    shipment_foreign_amount = 0.0
    shipment_krw_amount = 0.0
    shipment_date_from = None
    shipment_date_to = None
    for name, chunk in payloads.items():
        if name == "modules":
            continue
        for row in chunk.get("shipments") or []:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO shipments
                  (issue_no, issue_seq, ship_date, is_overseas, trade_type, business_unit,
                   partner_classification, metadata_version, partner_code, partner_name,
                   country_code, country_name, product_code, product_name, specification,
                   quantity, currency, exchange_rate, foreign_amount, krw_supply, krw_vat,
                   krw_total, manager_name, department_name, raw_json, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["issue_no"], int(row["issue_seq"]), row["ship_date"], int(row.get("is_overseas") or 0),
                    row.get("trade_type"), row.get("business_unit") or "unclassified",
                    row.get("partner_classification"), int(row.get("metadata_version") or 0),
                    row.get("partner_code"), row.get("partner_name"), row.get("country_code"),
                    row.get("country_name"), row.get("product_code"), row.get("product_name"),
                    row.get("specification"), float(row.get("quantity") or 0), row.get("currency"),
                    float(row.get("exchange_rate") or 0), float(row.get("foreign_amount") or 0),
                    float(row.get("krw_supply") or 0), float(row.get("krw_vat") or 0),
                    float(row.get("krw_total") or 0), row.get("manager_name"), row.get("department_name"),
                    row.get("raw_json") or "{}", row.get("synced_at") or _now(),
                ),
            )
            if int(cursor.rowcount or 0):
                shipments += 1
                shipment_issues.add(row["issue_no"])
                shipment_foreign_amount += float(row.get("foreign_amount") or 0)
                shipment_krw_amount += float(row.get("krw_total") or 0)
                ship_date = row["ship_date"]
                shipment_date_from = min(shipment_date_from, ship_date) if shipment_date_from else ship_date
                shipment_date_to = max(shipment_date_to, ship_date) if shipment_date_to else ship_date

    sync = modules.get("erp_sync_run") or {}
    if shipments:
        started_at = sync.get("started_at") or _now()
        db.execute(
            """
            INSERT INTO erp_sync_runs
              (started_at, finished_at, requested_by, date_from, date_to, status,
               header_count, source_header_count, excluded_header_count, line_count,
               foreign_amount, krw_amount, error_message)
            VALUES (?, ?, ?, ?, ?, 'success', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at, sync.get("finished_at") or started_at, admin["id"], shipment_date_from,
                shipment_date_to, len(shipment_issues), int(sync.get("source_header_count") or len(shipment_issues)),
                int(sync.get("excluded_header_count") or 0), shipments, shipment_foreign_amount,
                shipment_krw_amount, sync.get("error_message") or "정규화된 기존 ERP 데이터 이관",
            ),
        )

    expected = manifest.get("expected") or {}
    return {
        "goals": record_counts["goal"], "cash_plan": record_counts["cash_plan"],
        "receivables": record_counts["receivable"], "ar_term_accounts": ar_term_accounts,
        "forecast_cycles": forecast_cycles, "forecast_items": forecast_items,
        "exchange_rates": exchange_rates, "exchange_rate_date": exchange_rate_date,
        "exchange_rate_values": exchange_rate_values,
        "shipment_source_lines": int(expected.get("shipments") or shipments) + int(expected.get("excluded_local_or_domestic_rows") or 0),
        "shipments": shipments,
        "shipment_excluded_lines": int(expected.get("excluded_local_or_domestic_rows") or 0),
        "shipment_headers": len(shipment_issues),
        "shipment_foreign_amount": round(shipment_foreign_amount, 2),
        "shipment_krw_amount": round(shipment_krw_amount, 2),
        "shipment_date_from": shipment_date_from,
        "shipment_date_to": shipment_date_to,
        "normalized_source": True,
    }


def apply_source_data_import(db, app_dir, country_resolver=None, business_classifier=None):
    if db.execute("SELECT 1 FROM one_time_actions WHERE action_key = ?", (ACTION_KEY,)).fetchone():
        return None
    app_dir = Path(app_dir)
    source_dir = Path(os.environ.get("SOURCE_IMPORT_DIR") or (app_dir / "data" / "source"))
    xlsx_dir = Path(os.environ.get("SOURCE_IMPORT_XLSX_DIR") or source_dir)
    google_path = Path(os.environ.get("SOURCE_IMPORT_GOOGLE_JSON") or (source_dir / "google_sheet_import.json"))
    normalized_manifest = source_dir / "normalized" / "manifest.json"
    paths = {key: xlsx_dir / filename for key, filename in SOURCE_FILES.items()}
    required_paths = [google_path] if normalized_manifest.exists() else [
        google_path,
        paths["monthly_sales"],
        paths["shipments"],
        paths["cash_plan"],
        paths["receivables"],
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        return {"status": "skipped", "reason": "source files missing", "missing": missing}
    admin = db.execute("SELECT * FROM users WHERE role = 'admin' AND deleted_at IS NULL ORDER BY id LIMIT 1").fetchone()
    if not admin:
        return {"status": "skipped", "reason": "administrator missing"}
    google_data = json.loads(google_path.read_text(encoding="utf-8"))
    if google_data.get("version") != IMPORT_VERSION:
        raise ValueError("Google Sheet import version does not match the application importer")
    summary = {"status": "imported", "version": IMPORT_VERSION}
    try:
        db.execute("BEGIN")
        summary.update(_import_google_records(db, admin, google_data))
        if normalized_manifest.exists():
            summary.update(_import_normalized_payloads(db, admin, source_dir))
        else:
            summary.update(_import_monthly_forecast(db, admin, paths["monthly_sales"]))
            summary.update(_import_cash_plan(db, admin, paths["cash_plan"]))
            summary.update(_import_receivables(db, admin, paths["receivables"]))
            summary.update(_import_exchange_rates(db, paths["cash_plan"]))
            summary.update(_import_shipments(
                db, admin, paths["shipments"], country_resolver=country_resolver,
                business_classifier=business_classifier,
            ))
        now = _now()
        db.execute("INSERT INTO one_time_actions (action_key, applied_at) VALUES (?, ?)", (ACTION_KEY, now))
        db.execute(
            """
            INSERT INTO audit_logs
              (occurred_at, actor_user_id, actor_username, action, entity_type, summary, after_json)
            VALUES (?, ?, ?, 'SOURCE_IMPORT', 'record', ?, ?)
            """,
            (now, admin["id"], admin["username"], "기존 해외사업부 원본 데이터 일괄 이관", _safe_json(summary)),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return summary


def apply_monthly_sales_fcst_correction(db, app_dir):
    """Import the user-confirmed 2026-08 FCST snapshots without touching user-entered rows."""
    if db.execute(
        "SELECT 1 FROM one_time_actions WHERE action_key = ?",
        (FORECAST_CORRECTION_ACTION_KEY,),
    ).fetchone():
        return None

    source_path = Path(app_dir) / "data" / "source" / FORECAST_CORRECTION_FILE
    if not source_path.exists():
        return {"status": "skipped", "reason": "forecast correction source missing"}
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("version") != FORECAST_CORRECTION_VERSION:
        raise ValueError("Monthly sales FCST correction version does not match")

    admin = db.execute(
        "SELECT * FROM users WHERE role = 'admin' AND deleted_at IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin:
        return {"status": "skipped", "reason": "administrator missing"}

    month = str(source.get("forecast_month") or "")
    rates = source.get("rates") or {}
    labels = {"aesthetic": "에스테틱", "medical": "메디컬", "dental": "덴탈"}
    now = _now()
    created_cycles = 0
    created_items = 0
    hidden_business_goals = 0
    totals = {}
    try:
        db.execute("BEGIN")

        imported_goal_rows = db.execute(
            "SELECT id, payload_json FROM records WHERE entity_type = 'goal' AND deleted_at IS NULL"
        ).fetchall()
        ignored_goal_ids = [
            row["id"] for row in imported_goal_rows
            if _payload(row["payload_json"]).get("source_name") == SOURCE_FILES["business_plan"]
        ]
        if ignored_goal_ids:
            db.executemany(
                "UPDATE records SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                [(now, admin["id"], admin["id"], now, record_id) for record_id in ignored_goal_ids],
            )
            hidden_business_goals = len(ignored_goal_ids)

        for cycle_source in source.get("cycles") or []:
            round_no = int(cycle_source["round_no"])
            cycle = db.execute(
                "SELECT * FROM forecast_cycles WHERE forecast_month = ? AND round_no = ?",
                (month, round_no),
            ).fetchone()
            if cycle:
                cycle_id = cycle["id"]
                db.execute(
                    """
                    UPDATE forecast_cycles
                    SET as_of_date = ?, status = ?, updated_by = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        cycle_source["as_of_date"], cycle_source.get("status") or "closed",
                        admin["id"], now, cycle_id,
                    ),
                )
            else:
                cycle_id = _source_id("monthly-sales-fcst-cycle", f"{month}|{round_no}")
                cursor = db.execute(
                    """
                    INSERT INTO forecast_cycles
                      (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, cny_krw,
                       status, created_by, updated_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id, month, round_no, cycle_source["as_of_date"],
                        float(rates["USD"]), float(rates["EUR"]), float(rates["CNY"]),
                        cycle_source.get("status") or "closed", admin["id"], admin["id"], now, now,
                    ),
                )
                created_cycles += int(cursor.rowcount or 0)

            expected_total = float(cycle_source.get("total_krw") or 0)
            source_total = 0.0
            for item_source in cycle_source.get("items") or []:
                unit = item_source["business_unit"]
                foreign_amount = float(item_source.get("foreign_amount") or 0)
                source_krw = float(item_source.get("krw_amount") or 0)
                calculated_krw = round(foreign_amount * float(rates["USD"]), 2)
                if abs(calculated_krw - source_krw) > 0.01:
                    raise ValueError(
                        f"FCST source reconciliation failed: {month} round {round_no} {unit}"
                    )
                source_total += source_krw
                source_id = f"{month}-round-{round_no}-{unit}"
                item_id = _source_id("monthly-sales-fcst-item", source_id)
                label = labels.get(unit, unit)
                notes = (
                    f"원본: {source['source_name']} · {source['sheet_name']}!{item_source['source_cell']} "
                    f"(외화 {item_source['source_foreign_cell']})\n"
                    f"기준: {cycle_source['source_label']} · USD 1 = KRW {float(rates['USD']):,.0f}\n"
                    f"원본 스냅샷: USD {foreign_amount:,.2f} · KRW {source_krw:,.0f}"
                )
                cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO forecast_items
                      (id, cycle_id, title, account_id, account_name, business_unit, item_name,
                       stage, confidence, foreign_amount, currency, expected_ship_date, owner_id,
                       notes, status, source_type, source_id, created_by, updated_by, created_at, updated_at)
                    VALUES (?, ?, ?, NULL, ?, ?, ?, 'sales_activity', 100, ?, 'KRW', ?, ?, ?,
                            'active', 'legacy_monthly_summary', ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id, cycle_id, f"2026년 8월 {round_no}차 FCST · {label}",
                        f"{label} 합계", unit, "사업분야 합계", source_krw, "2026-08-31",
                        admin["id"], notes, source_id, admin["id"], admin["id"], now, now,
                    ),
                )
                created_items += int(cursor.rowcount or 0)

            if abs(source_total - expected_total) > 0.01:
                raise ValueError(f"FCST round total reconciliation failed: {month} round {round_no}")
            imported_total = db.execute(
                """
                SELECT COALESCE(SUM(foreign_amount), 0) AS krw
                FROM forecast_items
                WHERE cycle_id = ? AND source_type = 'legacy_monthly_summary'
                  AND deleted_at IS NULL AND status = 'active'
                """,
                (cycle_id,),
            ).fetchone()["krw"]
            if abs(float(imported_total or 0) - expected_total) > 0.01:
                raise ValueError(f"Imported FCST total reconciliation failed: {month} round {round_no}")
            totals[str(round_no)] = expected_total

        summary = (
            f"월매출 원본 기준 2026년 8월 FCST 1·2차 재분류 · "
            f"1차 KRW {totals.get('1', 0):,.0f} · 2차 KRW {totals.get('2', 0):,.0f} · "
            f"사업계획 원본 목표 {hidden_business_goals}건 화면 제외"
        )
        db.execute(
            """
            INSERT INTO audit_logs
              (occurred_at, actor_user_id, actor_username, action, entity_type, summary, after_json)
            VALUES (?, ?, ?, 'FORECAST_SOURCE_CORRECTION', 'forecast_cycle', ?, ?)
            """,
            (
                now, admin["id"], admin["username"], summary,
                _safe_json({
                    "source": source["source_name"], "forecast_month": month,
                    "totals": totals, "created_cycles": created_cycles,
                    "created_items": created_items, "hidden_business_goals": hidden_business_goals,
                }),
            ),
        )
        db.execute(
            "INSERT INTO one_time_actions (action_key, applied_at) VALUES (?, ?)",
            (FORECAST_CORRECTION_ACTION_KEY, now),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "corrected", "forecast_month": month, "totals": totals,
        "created_cycles": created_cycles, "created_items": created_items,
        "hidden_business_goals": hidden_business_goals,
    }


def apply_historical_sales_correction(db, app_dir):
    """Apply exact 2024-2025 KRW amounts from the ERP export to existing shipment keys."""
    if db.execute(
        "SELECT 1 FROM one_time_actions WHERE action_key = ?",
        (HISTORICAL_SALES_ACTION_KEY,),
    ).fetchone():
        return None

    source_path = Path(app_dir) / "data" / "source" / HISTORICAL_SALES_FILE
    if not source_path.exists():
        return {"status": "skipped", "reason": "historical sales correction source missing"}
    encoded = "".join(source_path.read_text(encoding="ascii").split())
    source = json.loads(gzip.decompress(base64.b64decode(encoded, validate=True)).decode("utf-8"))
    if source.get("version") != HISTORICAL_SALES_VERSION:
        raise ValueError("Historical sales correction version does not match")

    admin = db.execute(
        "SELECT * FROM users WHERE role = 'admin' AND deleted_at IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin:
        return {"status": "skipped", "reason": "administrator missing"}

    columns = source.get("columns") or []
    required_columns = {
        "issue_no", "issue_seq", "ship_date", "partner_name", "product_code", "quantity",
        "krw_supply", "krw_vat", "krw_total", "source_row",
    }
    if set(columns) != required_columns:
        raise ValueError("Historical sales correction columns are invalid")
    expected = source.get("expected") or {}
    source_rows = source.get("rows") or []
    if len(source_rows) != int(expected.get("rows") or 0):
        raise ValueError("Historical sales correction row count is invalid")

    now = _now()
    updated = 0
    totals = {"2024": 0.0, "2025": 0.0}
    issue_keys = set()
    try:
        db.execute("BEGIN")
        for values in source_rows:
            item = dict(zip(columns, values))
            row = db.execute(
                "SELECT * FROM shipments WHERE issue_no = ? AND issue_seq = ?",
                (item["issue_no"], int(item["issue_seq"])),
            ).fetchone()
            if not row:
                raise ValueError(
                    f"Historical ERP shipment is missing: {item['issue_no']} / {item['issue_seq']}"
                )
            comparisons = {
                "ship_date": (row["ship_date"], item["ship_date"]),
                "partner_name": (_text(row["partner_name"]), _text(item["partner_name"])),
                "product_code": (_text(row["product_code"]), _text(item["product_code"])),
            }
            for field, (prior, incoming) in comparisons.items():
                if prior != incoming:
                    raise ValueError(
                        f"Historical ERP reconciliation failed: {item['issue_no']} {field}"
                    )
            if abs(float(row["quantity"] or 0) - float(item["quantity"] or 0)) > 0.0001:
                raise ValueError(f"Historical ERP reconciliation failed: {item['issue_no']} quantity")
            foreign_amount = float(row["foreign_amount"] or 0)
            krw_supply = float(item["krw_supply"] or 0)
            exchange_rate = float(row["exchange_rate"] or 0)
            if abs(foreign_amount) > 0.000001:
                calculated_rate = krw_supply / foreign_amount
                if calculated_rate > 0:
                    exchange_rate = calculated_rate
            raw = _payload(row["raw_json"])
            raw["historical_krw_source"] = {
                "source_name": source["source_name"],
                "sheet_name": source["sheet_name"],
                "source_row": int(item["source_row"]),
                "amount_basis": "ERP 출고이력 실제 원화 공급가",
                "import_version": HISTORICAL_SALES_VERSION,
            }
            raw["legacy_krw_rate_note"] = (
                "2024·2025 출고는 ERP 원화 공급가로 보정; 외화 환율은 원화 공급가/외화금액으로 역산"
            )
            cursor = db.execute(
                """
                UPDATE shipments
                SET exchange_rate = ?, krw_supply = ?, krw_vat = ?, krw_total = ?,
                    raw_json = ?, synced_at = ?
                WHERE issue_no = ? AND issue_seq = ?
                """,
                (
                    exchange_rate, krw_supply, float(item["krw_vat"] or 0),
                    float(item["krw_total"] or 0), _safe_json(raw), now,
                    item["issue_no"], int(item["issue_seq"]),
                ),
            )
            updated += int(cursor.rowcount or 0)
            year = str(item["ship_date"])[:4]
            totals[year] = totals.get(year, 0) + krw_supply
            issue_keys.add(item["issue_no"])

        if updated != int(expected["rows"]):
            raise ValueError("Historical ERP correction did not update every expected row")
        if len(issue_keys) != int(expected["issues"]):
            raise ValueError("Historical ERP correction issue count does not reconcile")
        for year, expected_total in (expected.get("krw_supply_by_year") or {}).items():
            if abs(totals.get(year, 0) - float(expected_total)) > 0.01:
                raise ValueError(f"Historical ERP correction total does not reconcile: {year}")
            database_total = db.execute(
                """
                SELECT COALESCE(SUM(krw_supply), 0) AS amount FROM shipments
                WHERE is_overseas = 1 AND substr(ship_date, 1, 4) = ?
                """,
                (year,),
            ).fetchone()["amount"]
            if abs(float(database_total or 0) - float(expected_total)) > 0.01:
                raise ValueError(f"Historical ERP database total does not reconcile: {year}")

        summary = (
            f"ERP 엑셀 2024·2025 해외 출고 원화 매출 보정 · {updated:,}라인 / "
            f"{len(issue_keys):,}건 · 2024 KRW {totals['2024']:,.0f} · "
            f"2025 KRW {totals['2025']:,.0f}"
        )
        db.execute(
            """
            INSERT INTO audit_logs
              (occurred_at, actor_user_id, actor_username, action, entity_type, summary, after_json)
            VALUES (?, ?, ?, 'HISTORICAL_SALES_IMPORT', 'shipment', ?, ?)
            """,
            (
                now, admin["id"], admin["username"], summary,
                _safe_json({
                    "source_name": source["source_name"], "period": source["period"],
                    "updated_lines": updated, "shipment_count": len(issue_keys), "totals": totals,
                }),
            ),
        )
        db.execute(
            "INSERT INTO one_time_actions (action_key, applied_at) VALUES (?, ?)",
            (HISTORICAL_SALES_ACTION_KEY, now),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "corrected", "updated_lines": updated,
        "shipment_count": len(issue_keys), "totals": totals,
    }
