"""Customer commercial/order context v2.

This module is deliberately additive.  Existing Customer, Contract, Monthly
Sales, Promotion and ERP ledgers remain canonical; the tables below only add
stable item relations, structured terms and immutable sale-time lineage.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timezone

from flask import g, jsonify, request

from maps_taxonomy import INTERIM_CONTRACT_PRODUCTS, LANGUAGES, PAYMENT_METHODS


COMMERCIAL_CONTEXT_SCHEMA_VERSION = "customer-commercial-context-2026-09-15-v2"
WRITE_ROLES = ("admin", "manager", "editor")
READ_ROLES = (*WRITE_ROLES, "viewer")

ITEM_BUSINESS_UNITS = {
    "medpark_bovine_s1": "dental",
    "boss": "dental",
    "colla": "dental",
    "a1_oss": "dental",
    "medpark_allo_medical": "medical",
    "medpark_allo_dental": "dental",
    "s_derm": "aesthetic",
    "s_gen": "aesthetic",
    "s_gen_inject": "aesthetic",
    "adite": "aesthetic",
    "a1_bonechip": "dental",
    "a1_dbm": "dental",
}

CONTRACT_POLICIES = {
    "contract_required": "계약 필수",
    "no_contract_allowed": "무계약 거래 허용",
}
COMMERCIAL_STATUSES = {"active": "유효", "extended": "연장", "expired": "만료"}
PRICE_METHODS = {"base_price": "기본가", "base_plus_foc_markup": "기본가 + FOC 할증"}
PACKAGING_LABELS = {
    "ce": "CE",
    "fda": "FDA",
    "general_export": "General Export",
    "other": "Other",
}
INCOTERMS = {code: code for code in ("EXW", "FCA", "FOB", "CIF", "CIP", "DAP", "DDP")}
MOQ_UOMS = {code: label for code, label in (("EA", "EA"), ("BOX", "Box"), ("KIT", "Kit"), ("PACK", "Pack"), ("SET", "Set"))}
PROVIDER_TYPES = {
    "courier": "Courier",
    "forwarder": "Forwarder",
    "customs_broker": "Customs Broker",
}
DOCUMENT_CATALOG = {
    "commercial_invoice": "Commercial Invoice",
    "packing_list": "Packing List",
    "coo": "COO / CO",
    "coa": "COA",
    "doc": "DoC / Declaration of Conformity",
    "ce_certificate": "CE Certificate",
    "fsc_cfs": "FSC / CFS",
    "iso_13485": "ISO 13485",
    "sterilization_certificate": "Sterilization Certificate",
    "batch_lot_release": "Batch / Lot Release Certificate",
    "awb": "AWB",
    "bill_of_lading": "B/L",
    "import_permit": "Import Permit",
    "registration_certificate_copy": "Registration Certificate Copy",
    "other": "Other",
}
DOCUMENT_FREQUENCIES = {
    "every_shipment": "Every Shipment",
    "first_shipment_only": "First Shipment Only",
    "on_request": "On Request",
}
DOCUMENT_UNITS = {
    "shipment": "Shipment-level",
    "item": "Item-level",
    "lot": "Lot-level",
}
LEGALIZATION_TYPES = {
    "none": "None",
    "notarization": "Notarization",
    "apostille": "Apostille",
    "consular": "Consular Legalization",
}
ADDRESS_ROLES = {
    "bill_to": "Bill To",
    "ship_to": "Ship To",
    "consignee": "Consignee",
    "notify_party": "Notify Party",
}
PROMOTION_STATUSES = {
    "draft": "작성중",
    "active": "유효",
    "paused": "일시중지",
    "expired": "만료",
    "cancelled": "취소",
}


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _uuid():
    return uuid.uuid4().hex


def _clean(value, maximum=1000, required=False, label="값"):
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label}을(를) 입력하세요.")
    if len(text) > maximum:
        raise ValueError(f"{label}은(는) {maximum}자 이내로 입력하세요.")
    return text


def _date(value, label="일자", required=False):
    text = _clean(value, 10)
    if not text:
        if required:
            raise ValueError(f"{label}을(를) 입력하세요.")
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} 형식이 올바르지 않습니다.") from exc


def _month(value, label="대상월"):
    text = _clean(value, 7, True, label)
    try:
        datetime.strptime(text, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"{label}은 YYYY-MM 형식이어야 합니다.") from exc
    return text


def _number(value, label, minimum=0, allow_none=False):
    if value in (None, "") and allow_none:
        return None
    try:
        result = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}은(는) 숫자로 입력하세요.") from exc
    if result < minimum:
        raise ValueError(f"{label}은(는) {minimum} 이상이어야 합니다.")
    return result


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _row(row):
    return dict(row) if row is not None else None


def _column_names(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_columns(db, table, definitions):
    existing = _column_names(db, table)
    for name, definition in definitions.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_commercial_context_schema(db, now_fn=None):
    """Apply only idempotent, nullable/additive commercial-context schema."""
    timestamp = now_fn() if now_fn else _now()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS commercial_context_schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS customer_items (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          business_unit TEXT NOT NULL,
          interim_product_code TEXT NOT NULL,
          future_product_master_id TEXT,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_items_active
          ON customer_items(customer_id, interim_product_code) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_customer_items_customer
          ON customer_items(customer_id, deleted_at, business_unit);

        CREATE TABLE IF NOT EXISTS customer_contract_item_terms (
          id TEXT PRIMARY KEY,
          contract_id TEXT NOT NULL,
          interim_product_code TEXT NOT NULL,
          future_product_master_id TEXT,
          unit_price REAL,
          currency TEXT,
          price_method_code TEXT,
          moq_quantity REAL,
          moq_uom TEXT,
          foc_markup_pct REAL,
          packaging_label_code TEXT,
          packaging_label_other TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(contract_id) REFERENCES customer_contracts(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_contract_item_terms_active
          ON customer_contract_item_terms(contract_id, interim_product_code) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_contract_item_terms_item
          ON customer_contract_item_terms(interim_product_code, deleted_at, contract_id);

        CREATE TABLE IF NOT EXISTS promotion_commercial_terms (
          promotion_id TEXT PRIMARY KEY,
          start_date TEXT NOT NULL,
          end_date TEXT NOT NULL,
          status_code TEXT NOT NULL DEFAULT 'draft',
          notes TEXT NOT NULL DEFAULT '',
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(promotion_id) REFERENCES records(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS promotion_customer_links (
          id TEXT PRIMARY KEY,
          promotion_id TEXT NOT NULL,
          customer_id TEXT NOT NULL,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(promotion_id) REFERENCES records(id),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_promotion_customer_active
          ON promotion_customer_links(promotion_id, customer_id) WHERE deleted_at IS NULL;
        CREATE TABLE IF NOT EXISTS promotion_items (
          id TEXT PRIMARY KEY,
          promotion_id TEXT NOT NULL,
          interim_product_code TEXT NOT NULL,
          future_product_master_id TEXT,
          price_override REAL,
          currency_override TEXT,
          foc_markup_override_pct REAL,
          moq_quantity_override REAL,
          moq_uom_override TEXT,
          packaging_label_override_code TEXT,
          packaging_label_override_other TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(promotion_id) REFERENCES records(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_promotion_item_active
          ON promotion_items(promotion_id, interim_product_code) WHERE deleted_at IS NULL;
        CREATE TABLE IF NOT EXISTS promotion_sales_lines (
          id TEXT PRIMARY KEY,
          promotion_id TEXT NOT NULL,
          customer_id TEXT NOT NULL,
          interim_product_code TEXT NOT NULL,
          target_month TEXT NOT NULL,
          expected_quantity REAL,
          expected_amount REAL,
          currency TEXT,
          monthly_sale_id TEXT,
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(promotion_id) REFERENCES records(id),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id),
          FOREIGN KEY(monthly_sale_id) REFERENCES monthly_sales(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_promotion_sales_line_identity
          ON promotion_sales_lines(promotion_id, customer_id, interim_product_code, target_month)
          WHERE deleted_at IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS ux_promotion_sales_line_monthly_sale
          ON promotion_sales_lines(monthly_sale_id) WHERE monthly_sale_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS customer_logistics_addresses (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          address_role TEXT NOT NULL,
          company_name TEXT NOT NULL DEFAULT '',
          address_line1 TEXT NOT NULL DEFAULT '',
          address_line2 TEXT NOT NULL DEFAULT '',
          city TEXT NOT NULL DEFAULT '', state_province TEXT NOT NULL DEFAULT '',
          postal_code TEXT NOT NULL DEFAULT '', country_code TEXT,
          country_name TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '', tax_importer_id TEXT NOT NULL DEFAULT '',
          note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_customer_addresses
          ON customer_logistics_addresses(customer_id, address_role, deleted_at);

        CREATE TABLE IF NOT EXISTS logistics_providers (
          id TEXT PRIMARY KEY,
          provider_type TEXT NOT NULL,
          company_name TEXT NOT NULL,
          website TEXT NOT NULL DEFAULT '', country_code TEXT,
          country_name TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_logistics_provider_identity
          ON logistics_providers(provider_type, company_name COLLATE NOCASE, COALESCE(country_code,''))
          WHERE deleted_at IS NULL;
        CREATE TABLE IF NOT EXISTS customer_logistics_providers (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          provider_id TEXT NOT NULL,
          contact_person TEXT NOT NULL DEFAULT '', department TEXT NOT NULL DEFAULT '',
          phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
          account_number TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id),
          FOREIGN KEY(provider_id) REFERENCES logistics_providers(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_provider_active
          ON customer_logistics_providers(customer_id, provider_id, account_number COLLATE NOCASE)
          WHERE deleted_at IS NULL;

        CREATE TABLE IF NOT EXISTS customer_document_requirements (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          document_code TEXT NOT NULL,
          other_document_name TEXT NOT NULL DEFAULT '',
          item_scope TEXT NOT NULL DEFAULT 'all',
          required INTEGER NOT NULL DEFAULT 1,
          frequency_code TEXT NOT NULL DEFAULT 'every_shipment',
          document_unit_code TEXT NOT NULL DEFAULT 'shipment',
          original_required INTEGER NOT NULL DEFAULT 0,
          legalization_code TEXT NOT NULL DEFAULT 'none',
          language_code TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_customer_document_requirements
          ON customer_document_requirements(customer_id, required, deleted_at);
        CREATE TABLE IF NOT EXISTS customer_document_requirement_items (
          id TEXT PRIMARY KEY,
          requirement_id TEXT NOT NULL,
          interim_product_code TEXT NOT NULL,
          future_product_master_id TEXT,
          created_by INTEGER, created_at TEXT NOT NULL,
          FOREIGN KEY(requirement_id) REFERENCES customer_document_requirements(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          UNIQUE(requirement_id, interim_product_code)
        );

        CREATE TABLE IF NOT EXISTS country_holidays (
          id TEXT PRIMARY KEY,
          country_code TEXT NOT NULL,
          holiday_date TEXT NOT NULL,
          holiday_name TEXT NOT NULL,
          holiday_year INTEGER NOT NULL,
          source TEXT NOT NULL,
          source_version TEXT,
          created_at TEXT NOT NULL,
          UNIQUE(country_code, holiday_date, holiday_name)
        );
        CREATE INDEX IF NOT EXISTS idx_country_holiday_lookup
          ON country_holidays(country_code, holiday_date);
        CREATE TABLE IF NOT EXISTS customer_closures (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          start_date TEXT NOT NULL, end_date TEXT NOT NULL,
          title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_customer_closure_lookup
          ON customer_closures(customer_id, start_date, end_date, deleted_at);
        """
    )
    _add_columns(db, "customer_master", {
        "contract_policy": "TEXT",
        "contract_policy_reviewed_by": "INTEGER REFERENCES users(id)",
        "contract_policy_reviewed_at": "TEXT",
    })
    _add_columns(db, "customer_contracts", {
        "commercial_status_code": "TEXT",
        "extension_end_date": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
    })
    _add_columns(db, "customer_product_terms", {
        "price_method_code": "TEXT",
        "moq_quantity": "REAL",
        "moq_uom": "TEXT",
        "foc_markup_pct": "REAL",
        "packaging_label_code": "TEXT",
        "packaging_label_other": "TEXT NOT NULL DEFAULT ''",
        "term_start_date": "TEXT",
        "term_end_date": "TEXT",
        "commercial_status_code": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "future_product_master_id": "TEXT",
    })
    _add_columns(db, "customer_payment_terms", {
        "contract_id": "TEXT REFERENCES customer_contracts(id)",
        "incoterms_code": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
    })
    _add_columns(db, "customer_sales_plans", {
        "contract_id": "TEXT REFERENCES customer_contracts(id)",
        "target_type": "TEXT",
        "interim_product_code": "TEXT",
        "target_amount": "REAL",
        "target_quantity": "REAL",
        "target_uom": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "future_product_master_id": "TEXT",
    })
    _add_columns(db, "monthly_sales", {
        "interim_product_code": "TEXT",
        "future_product_master_id": "TEXT",
        "source_type": "TEXT",
        "source_promotion_id": "TEXT REFERENCES records(id)",
        "source_promotion_line_id": "TEXT REFERENCES promotion_sales_lines(id)",
        "source_contract_id": "TEXT REFERENCES customer_contracts(id)",
        "source_customer_term_id": "TEXT REFERENCES customer_product_terms(id)",
        "pricing_source": "TEXT",
        "snapshot_unit_price": "REAL",
        "snapshot_currency": "TEXT",
        "snapshot_moq_quantity": "REAL",
        "snapshot_moq_uom": "TEXT",
        "snapshot_foc_markup_pct": "REAL",
        "snapshot_label_code": "TEXT",
        "snapshot_label_other": "TEXT NOT NULL DEFAULT ''",
        "snapshot_payment_terms_json": "TEXT",
        "snapshot_incoterms": "TEXT",
        "commercial_context_json": "TEXT",
        "commercial_context_resolved_at": "TEXT",
        "commercial_terms_managed": "INTEGER NOT NULL DEFAULT 0",
    })
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_monthly_sale_promotion_line "
        "ON monthly_sales(source_promotion_line_id) WHERE source_promotion_line_id IS NOT NULL"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_monthly_sales_commercial_source "
        "ON monthly_sales(customer_master_id, interim_product_code, source_contract_id, source_promotion_id)"
    )
    db.execute(
        "INSERT OR IGNORE INTO commercial_context_schema_migrations(version,applied_at) VALUES (?,?)",
        (COMMERCIAL_CONTEXT_SCHEMA_VERSION, timestamp),
    )


def commercial_schema_ready(db):
    row = db.execute(
        "SELECT 1 FROM commercial_context_schema_migrations WHERE version=?",
        (COMMERCIAL_CONTEXT_SCHEMA_VERSION,),
    ).fetchone()
    return bool(row)


def taxonomy_payload():
    def options(values):
        return [{"code": code, "label": label} for code, label in values.items()]

    return {
        "items": [
            {"code": code, "label": label, "business_unit": ITEM_BUSINESS_UNITS[code]}
            for code, label in INTERIM_CONTRACT_PRODUCTS.items()
        ],
        "contract_policies": options(CONTRACT_POLICIES),
        "commercial_statuses": options(COMMERCIAL_STATUSES),
        "price_methods": options(PRICE_METHODS),
        "packaging_labels": options(PACKAGING_LABELS),
        "incoterms": options(INCOTERMS),
        "moq_uoms": options(MOQ_UOMS),
        "provider_types": options(PROVIDER_TYPES),
        "document_catalog": options(DOCUMENT_CATALOG),
        "document_frequencies": options(DOCUMENT_FREQUENCIES),
        "document_units": options(DOCUMENT_UNITS),
        "legalization_types": options(LEGALIZATION_TYPES),
        "address_roles": options(ADDRESS_ROLES),
        "promotion_statuses": options(PROMOTION_STATUSES),
        "payment_methods": options(PAYMENT_METHODS),
        "languages": options(LANGUAGES),
    }


def validate_item_code(value):
    code = _clean(value, 80, True, "아이템")
    if code not in INTERIM_CONTRACT_PRODUCTS:
        raise ValueError("승인된 Interim Item 목록에서 선택하세요.")
    return code


def validate_contract_policy(value, allow_none=True):
    policy = _clean(value, 40) or None
    if policy is None and allow_none:
        return None
    if policy not in CONTRACT_POLICIES:
        raise ValueError("계약정책은 계약 필수 또는 무계약 거래 허용 중에서 선택하세요.")
    return policy


def validate_customer_item_scope(item_codes, business_units):
    """Keep the Customer Portfolio's stable Items under selected business areas."""
    units = set(business_units or [])
    validated = [validate_item_code(value) for value in (item_codes or [])]
    invalid = [code for code in validated if ITEM_BUSINESS_UNITS[code] not in units]
    if invalid:
        labels = " · ".join(INTERIM_CONTRACT_PRODUCTS.get(code, code) for code in invalid)
        raise ValueError(f"선택한 사업분야에 속하지 않는 Item이 있습니다: {labels}")
    return validated


def customer_item_rows(db, customer_id):
    return [
        _row(row) | {"label": INTERIM_CONTRACT_PRODUCTS.get(row["interim_product_code"], row["interim_product_code"])}
        for row in db.execute(
            "SELECT * FROM customer_items WHERE customer_id=? AND deleted_at IS NULL ORDER BY business_unit,created_at,id",
            (customer_id,),
        ).fetchall()
    ]


def replace_customer_items(db, customer_id, item_codes, actor_id, timestamp=None):
    timestamp = timestamp or _now()
    requested = {validate_item_code(value) for value in (item_codes or [])}
    active = {
        row["interim_product_code"]: row
        for row in db.execute(
            "SELECT * FROM customer_items WHERE customer_id=? AND deleted_at IS NULL", (customer_id,)
        ).fetchall()
    }
    removed = sorted(set(active) - requested)
    if removed:
        db.executemany(
            "UPDATE customer_items SET deleted_at=?,updated_by=?,updated_at=? WHERE customer_id=? AND interim_product_code=? AND deleted_at IS NULL",
            [(timestamp, actor_id, timestamp, customer_id, code) for code in removed],
        )
    for code in sorted(requested - set(active)):
        reusable = db.execute(
            "SELECT id FROM customer_items WHERE customer_id=? AND interim_product_code=? AND deleted_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (customer_id, code),
        ).fetchone()
        if reusable:
            db.execute(
                "UPDATE customer_items SET business_unit=?,deleted_at=NULL,updated_by=?,updated_at=? WHERE id=?",
                (ITEM_BUSINESS_UNITS[code], actor_id, timestamp, reusable["id"]),
            )
        else:
            db.execute(
                """INSERT INTO customer_items
                   (id,customer_id,business_unit,interim_product_code,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_uuid(), customer_id, ITEM_BUSINESS_UNITS[code], code, actor_id, actor_id, timestamp, timestamp),
            )
    return customer_item_rows(db, customer_id)


def _effective_contract_end(contract):
    if contract.get("commercial_status_code") == "extended":
        return contract.get("extension_end_date")
    return contract.get("end_date")


def _overlap(start_a, end_a, start_b, end_b):
    return start_a <= end_b and start_b <= end_a


def _validate_contract_state(values):
    start = _date(values.get("start_date"), "계약 시작일", True)
    end = _date(values.get("end_date"), "계약 종료일", True)
    if start > end:
        raise ValueError("계약 시작일은 종료일보다 늦을 수 없습니다.")
    status = _clean(values.get("commercial_status_code"), 20, True, "계약상태")
    if status not in COMMERCIAL_STATUSES:
        raise ValueError("계약상태는 유효·연장·만료 중에서 선택하세요.")
    extension_end = _date(values.get("extension_end_date"), "연장 종료일")
    if status == "extended":
        if not extension_end:
            raise ValueError("연장 계약은 연장 종료일을 입력하세요.")
        if extension_end <= end:
            raise ValueError("연장 종료일은 기존 계약 종료일보다 늦어야 합니다.")
    return start, end, status, extension_end


def _validate_term(values, *, partial=False):
    result = {}
    code = values.get("interim_product_code")
    if code is not None or not partial:
        result["interim_product_code"] = validate_item_code(code)
    fields = {
        "unit_price": ("가격", True),
        "moq_quantity": ("MOQ 수량", True),
        "foc_markup_pct": ("FOC 할증률", True),
    }
    for key, (label, nullable) in fields.items():
        if key in values or not partial:
            result[key] = _number(values.get(key), label, 0, nullable)
    for key, maximum in (("currency", 8), ("price_method_code", 40), ("moq_uom", 20),
                         ("packaging_label_code", 40), ("packaging_label_other", 200), ("notes", 2000)):
        if key in values or not partial:
            result[key] = _clean(values.get(key), maximum)
    if result.get("unit_price") is None and not partial:
        raise ValueError("실거래 가격을 입력하세요.")
    if result.get("currency") and result["currency"] not in {"USD", "EUR", "JPY", "CNH", "KRW"}:
        raise ValueError("통화는 USD·EUR·JPY·CNH·KRW 중에서 선택하세요.")
    if result.get("price_method_code") and result["price_method_code"] not in PRICE_METHODS:
        raise ValueError("가격방식을 목록에서 선택하세요.")
    if result.get("moq_uom") and result["moq_uom"] not in MOQ_UOMS:
        raise ValueError("MOQ 단위를 목록에서 선택하세요.")
    if result.get("packaging_label_code") and result["packaging_label_code"] not in PACKAGING_LABELS:
        raise ValueError("포장·라벨 버전을 목록에서 선택하세요.")
    if result.get("packaging_label_code") == "other" and not result.get("packaging_label_other"):
        raise ValueError("Other 포장·라벨 버전명을 입력하세요.")
    return result


def _contract_item_codes(db, contract_id):
    return [
        row["interim_product_code"]
        for row in db.execute(
            "SELECT interim_product_code FROM customer_contract_products WHERE contract_id=? AND deleted_at IS NULL ORDER BY interim_product_code",
            (contract_id,),
        ).fetchall()
    ]


def validate_contract_item_conflicts(db, customer_id, contract_id, item_codes, start_date, effective_end, status):
    if status not in {"active", "extended"}:
        return
    for code in item_codes:
        rows = db.execute(
            """SELECT DISTINCT c.*
               FROM customer_contracts c
               JOIN customer_contract_products p ON p.contract_id=c.id AND p.deleted_at IS NULL
               WHERE c.customer_id=? AND c.id<>? AND c.deleted_at IS NULL
                 AND c.commercial_status_code IN ('active','extended')
                 AND p.interim_product_code=?""",
            (customer_id, contract_id or "", code),
        ).fetchall()
        for raw in rows:
            other = _row(raw)
            other_start = other.get("start_date")
            other_end = _effective_contract_end(other)
            if other_start and other_end and _overlap(start_date, effective_end, other_start, other_end):
                label = INTERIM_CONTRACT_PRODUCTS.get(code, code)
                raise ValueError(
                    f"{label}에 같은 기간 적용되는 유효/연장 계약이 이미 있습니다: "
                    f"{other.get('contract_no') or other['id']}"
                )


def _assert_customer_portfolio(db, customer_id, item_codes, label="상업조건"):
    portfolio = {
        row["interim_product_code"]
        for row in db.execute(
            "SELECT interim_product_code FROM customer_items WHERE customer_id=? AND deleted_at IS NULL",
            (customer_id,),
        ).fetchall()
    }
    missing = set(item_codes) - portfolio
    if missing:
        names = " · ".join(INTERIM_CONTRACT_PRODUCTS.get(code, code) for code in sorted(missing))
        raise ValueError(f"{label} Item은 먼저 Customer 취급 Item에 등록하세요: {names}")


def _replace_contract_products(db, contract_id, item_codes, actor_id, timestamp):
    requested = {validate_item_code(value) for value in item_codes}
    current = {
        row["interim_product_code"]: row
        for row in db.execute(
            "SELECT * FROM customer_contract_products WHERE contract_id=? AND deleted_at IS NULL", (contract_id,)
        ).fetchall()
    }
    for code in sorted(set(current) - requested):
        db.execute(
            "UPDATE customer_contract_products SET deleted_at=?,updated_by=?,updated_at=? WHERE id=?",
            (timestamp, actor_id, timestamp, current[code]["id"]),
        )
    for code in sorted(requested - set(current)):
        reusable = db.execute(
            "SELECT id FROM customer_contract_products WHERE contract_id=? AND interim_product_code=? AND deleted_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (contract_id, code),
        ).fetchone()
        if reusable:
            db.execute(
                "UPDATE customer_contract_products SET deleted_at=NULL,updated_by=?,updated_at=? WHERE id=?",
                (actor_id, timestamp, reusable["id"]),
            )
        else:
            db.execute(
                """INSERT INTO customer_contract_products
                   (id,contract_id,interim_product_code,source,provenance,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,'user','user_confirmed',?,?,?,?)""",
                (_uuid(), contract_id, code, actor_id, actor_id, timestamp, timestamp),
            )


def _upsert_contract_item_terms(db, contract_id, terms, actor_id, timestamp):
    requested = {}
    for raw in terms:
        term = _validate_term(raw)
        code = term["interim_product_code"]
        if code in requested:
            raise ValueError("같은 계약 Item 조건을 중복 등록할 수 없습니다.")
        requested[code] = term
    active = {
        row["interim_product_code"]: _row(row)
        for row in db.execute(
            "SELECT * FROM customer_contract_item_terms WHERE contract_id=? AND deleted_at IS NULL", (contract_id,)
        ).fetchall()
    }
    for code in sorted(set(active) - set(requested)):
        db.execute(
            "UPDATE customer_contract_item_terms SET deleted_at=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?",
            (timestamp, actor_id, timestamp, active[code]["id"]),
        )
    for code, term in requested.items():
        existing = active.get(code)
        if existing:
            db.execute(
                """UPDATE customer_contract_item_terms
                   SET unit_price=?,currency=?,price_method_code=?,moq_quantity=?,moq_uom=?,
                       foc_markup_pct=?,packaging_label_code=?,packaging_label_other=?,notes=?,
                       updated_by=?,updated_at=?,version=version+1
                   WHERE id=?""",
                (term.get("unit_price"), term.get("currency"), term.get("price_method_code"),
                 term.get("moq_quantity"), term.get("moq_uom"), term.get("foc_markup_pct"),
                 term.get("packaging_label_code"), term.get("packaging_label_other", ""), term.get("notes", ""),
                 actor_id, timestamp, existing["id"]),
            )
        else:
            db.execute(
                """INSERT INTO customer_contract_item_terms
                   (id,contract_id,interim_product_code,unit_price,currency,price_method_code,
                    moq_quantity,moq_uom,foc_markup_pct,packaging_label_code,packaging_label_other,notes,
                    created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_uuid(), contract_id, code, term.get("unit_price"), term.get("currency"),
                 term.get("price_method_code"), term.get("moq_quantity"), term.get("moq_uom"),
                 term.get("foc_markup_pct"), term.get("packaging_label_code"), term.get("packaging_label_other", ""),
                 term.get("notes", ""), actor_id, actor_id, timestamp, timestamp),
            )


def _contract_badge(contract, today=None):
    today = today or date.today()
    start = contract.get("start_date")
    effective_end = _effective_contract_end(contract)
    status = contract.get("commercial_status_code")
    if not status:
        return {"code": "review_required", "label": "상태 확인 필요", "days": None}
    if start and date.fromisoformat(start) > today:
        return {"code": "not_started", "label": "시작 전", "days": (date.fromisoformat(start) - today).days}
    if status == "expired":
        return {"code": "expired", "label": "만료", "days": None}
    if effective_end:
        days = (date.fromisoformat(effective_end) - today).days
        if days < 0:
            return {"code": "action_required", "label": "계약기간 종료 · 조치 필요", "days": days}
        if days <= 30:
            return {"code": "d30", "label": f"D-{days}" if days else "D-Day", "days": days}
        if days <= 60:
            return {"code": "d60", "label": f"D-{days}", "days": days}
    return {"code": status, "label": COMMERCIAL_STATUSES.get(status, status), "days": None}


def _contract_payload(db, row):
    contract = _row(row)
    contract["interim_product_codes"] = _contract_item_codes(db, contract["id"])
    contract["territory_country_codes"] = [
        item["country_code"] for item in db.execute(
            "SELECT country_code FROM customer_contract_countries WHERE contract_id=? AND deleted_at IS NULL ORDER BY country_code",
            (contract["id"],),
        ).fetchall()
    ]
    contract["item_terms"] = [
        _row(item) | {"item_label": INTERIM_CONTRACT_PRODUCTS.get(item["interim_product_code"], item["interim_product_code"])}
        for item in db.execute(
            "SELECT * FROM customer_contract_item_terms WHERE contract_id=? AND deleted_at IS NULL ORDER BY interim_product_code",
            (contract["id"],),
        ).fetchall()
    ]
    contract["sales_plans"] = [
        _row(item) for item in db.execute(
            "SELECT * FROM customer_sales_plans WHERE contract_id=? AND deleted_at IS NULL ORDER BY plan_year,interim_product_code",
            (contract["id"],),
        ).fetchall()
    ]
    contract["sales_plans_v2"] = contract["sales_plans"]
    contract["payment_override"] = _row(db.execute(
        "SELECT * FROM customer_payment_terms WHERE contract_id=? AND deleted_at IS NULL AND is_current=1 ORDER BY created_at DESC LIMIT 1",
        (contract["id"],),
    ).fetchone())
    contract["derived_badge"] = _contract_badge(contract)
    return contract


def _default_term_payload(row):
    item = _row(row)
    item["item_label"] = INTERIM_CONTRACT_PRODUCTS.get(item.get("interim_product_code"), item.get("product_name") or "")
    return item


def _country_alpha2(country_code, country_catalog):
    item = (country_catalog or {}).get(str(country_code or "").zfill(3)) or {}
    for alias in item.get("aliases", ()):
        alias = str(alias).strip()
        if len(alias) == 2 and alias.isalpha():
            return alias.upper()
    return None


def ensure_country_holidays(db, country_code, year, country_catalog=None):
    code = str(country_code or "").zfill(3)
    if not code or code == "000":
        return {"status": "unavailable", "message": "거래처 국가코드를 먼저 확인하세요."}
    existing = db.execute(
        "SELECT COUNT(*) AS c FROM country_holidays WHERE country_code=? AND holiday_year=?",
        (code, int(year)),
    ).fetchone()["c"]
    if existing:
        return {"status": "cached", "count": existing}
    alpha2 = _country_alpha2(code, country_catalog)
    if not alpha2:
        return {"status": "unavailable", "message": "공휴일 Provider용 국가코드를 확인할 수 없습니다."}
    try:
        import holidays  # optional, pinned runtime dependency
        calendar = holidays.country_holidays(alpha2, years=[int(year)], language="en_US")
        version = getattr(holidays, "__version__", "unknown")
    except (ImportError, KeyError, NotImplementedError, ValueError) as exc:
        return {"status": "unavailable", "message": f"검증된 공휴일 Provider를 사용할 수 없습니다: {type(exc).__name__}"}
    timestamp = _now()
    for holiday_date, name in sorted(calendar.items()):
        db.execute(
            """INSERT OR IGNORE INTO country_holidays
               (id,country_code,holiday_date,holiday_name,holiday_year,source,source_version,created_at)
               VALUES (?,?,?,?,?,'python-holidays',?,?)""",
            (_uuid(), code, holiday_date.isoformat(), str(name), int(year), version, timestamp),
        )
    return {"status": "generated", "count": len(calendar), "source": "python-holidays", "version": version}


def required_documents(db, customer_id, item_code):
    rows = db.execute(
        """SELECT r.* FROM customer_document_requirements r
           WHERE r.customer_id=? AND r.deleted_at IS NULL AND r.required=1
             AND (r.item_scope='all' OR EXISTS (
               SELECT 1 FROM customer_document_requirement_items i
               WHERE i.requirement_id=r.id AND i.interim_product_code=?
             ))
           ORDER BY r.document_code,r.created_at""",
        (customer_id, item_code),
    ).fetchall()
    return [
        _row(row) | {"label": row["other_document_name"] if row["document_code"] == "other" else DOCUMENT_CATALOG.get(row["document_code"], row["document_code"])}
        for row in rows
    ]


def _payment_context(db, customer_id, contract_id, order_date):
    if contract_id:
        override = db.execute(
            """SELECT * FROM customer_payment_terms
               WHERE customer_id=? AND contract_id=? AND deleted_at IS NULL AND is_current=1
                 AND (effective_from IS NULL OR effective_from<=?)
                 AND (effective_to IS NULL OR effective_to>=?)
               ORDER BY COALESCE(effective_from,'') DESC,created_at DESC LIMIT 1""",
            (customer_id, contract_id, order_date, order_date),
        ).fetchone()
        if override:
            return _row(override), "contract_override"
    default = db.execute(
        """SELECT * FROM customer_payment_terms
           WHERE customer_id=? AND contract_id IS NULL AND deleted_at IS NULL AND is_current=1
             AND (effective_from IS NULL OR effective_from<=?)
             AND (effective_to IS NULL OR effective_to>=?)
           ORDER BY COALESCE(effective_from,'') DESC,created_at DESC LIMIT 1""",
        (customer_id, order_date, order_date),
    ).fetchone()
    return (_row(default), "customer_default") if default else ({}, "none")


def _active_promotion_item(db, promotion_id, customer_id, item_code, order_date):
    if not promotion_id:
        return None
    row = db.execute(
        """SELECT p.*,t.start_date,t.end_date,t.status_code,r.title
           FROM promotion_items p
           JOIN promotion_commercial_terms t ON t.promotion_id=p.promotion_id
           JOIN records r ON r.id=p.promotion_id AND r.deleted_at IS NULL
           JOIN promotion_customer_links c ON c.promotion_id=p.promotion_id
             AND c.customer_id=? AND c.deleted_at IS NULL
           WHERE p.promotion_id=? AND p.interim_product_code=? AND p.deleted_at IS NULL
             AND t.status_code='active' AND t.start_date<=? AND t.end_date>=?""",
        (customer_id, promotion_id, item_code, order_date, order_date),
    ).fetchone()
    if not row:
        raise ValueError("선택한 Promotion의 Customer·Item·기간 Scope가 주문 조건과 일치하지 않습니다.")
    return _row(row)


def resolve_customer_order_context(db, customer_id, item_code, order_date, promotion_id=None, country_catalog=None):
    """Resolve one authoritative, sale-time commercial context."""
    item_code = validate_item_code(item_code)
    order_date = _date(order_date, "주문 기준일", True)
    customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        raise ValueError("거래처 마스터를 찾을 수 없습니다.")
    customer = _row(customer)
    policy = customer.get("contract_policy")
    contracts = []
    for raw in db.execute(
        """SELECT DISTINCT c.* FROM customer_contracts c
           JOIN customer_contract_products p ON p.contract_id=c.id AND p.deleted_at IS NULL
           WHERE c.customer_id=? AND c.deleted_at IS NULL
             AND c.commercial_status_code IN ('active','extended')
             AND p.interim_product_code=? AND c.start_date<=?""",
        (customer_id, item_code, order_date),
    ).fetchall():
        contract = _row(raw)
        effective_end = _effective_contract_end(contract)
        if effective_end and effective_end >= order_date:
            contracts.append(contract)
    if len(contracts) > 1:
        raise ValueError("같은 Customer+Item+기간에 적용 가능한 Contract가 2개 이상입니다. Customer Master에서 먼저 정리하세요.")

    base = None
    base_type = None
    contract = contracts[0] if contracts else None
    if contract:
        base = _row(db.execute(
            """SELECT * FROM customer_contract_item_terms
               WHERE contract_id=? AND interim_product_code=? AND deleted_at IS NULL""",
            (contract["id"], item_code),
        ).fetchone())
        if not base or base.get("unit_price") is None:
            raise ValueError("현재 Contract의 Item 실거래 가격조건이 없습니다. Customer Master에서 먼저 등록하세요.")
        base_type = "contract"
    elif policy == "no_contract_allowed":
        rows = db.execute(
            """SELECT * FROM customer_product_terms
               WHERE customer_id=? AND interim_product_code=? AND deleted_at IS NULL
                 AND commercial_status_code='active'
                 AND (term_start_date IS NULL OR term_start_date<=?)
                 AND (term_end_date IS NULL OR term_end_date>=?)
               ORDER BY COALESCE(term_start_date,'') DESC,created_at DESC""",
            (customer_id, item_code, order_date, order_date),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("같은 Customer+Item+기간에 적용 가능한 기본 가격조건이 2개 이상입니다.")
        if rows:
            base = _row(rows[0])
            base_type = "customer_default"
    if not base:
        if policy == "contract_required":
            raise ValueError("현재 적용 가능한 계약이 없습니다. 거래처 Master에서 신규계약 또는 연장 처리를 먼저 진행하세요.")
        if policy == "no_contract_allowed":
            raise ValueError("무계약 거래용 현재 기본 가격조건이 없습니다. 거래처 Master에서 먼저 등록하세요.")
        raise ValueError("거래처 계약정책이 미분류입니다. 거래처 Master에서 계약정책을 먼저 확인하세요.")

    promotion = _active_promotion_item(db, promotion_id, customer_id, item_code, order_date)
    unit_price = base.get("unit_price") if base_type == "contract" else base.get("agreed_unit_price")
    currency = base.get("currency")
    moq_quantity = base.get("moq_quantity")
    moq_uom = base.get("moq_uom")
    foc_markup_pct = base.get("foc_markup_pct")
    label_code = base.get("packaging_label_code")
    label_other = base.get("packaging_label_other") or ""
    if promotion:
        if promotion.get("price_override") is not None:
            unit_price = promotion["price_override"]
        if promotion.get("currency_override"):
            currency = promotion["currency_override"]
        if promotion.get("moq_quantity_override") is not None:
            moq_quantity = promotion["moq_quantity_override"]
        if promotion.get("moq_uom_override"):
            moq_uom = promotion["moq_uom_override"]
        if promotion.get("foc_markup_override_pct") is not None:
            foc_markup_pct = promotion["foc_markup_override_pct"]
        if promotion.get("packaging_label_override_code"):
            label_code = promotion["packaging_label_override_code"]
            label_other = promotion.get("packaging_label_override_other") or ""
    payment, payment_source = _payment_context(db, customer_id, contract["id"] if contract else None, order_date)
    docs = required_documents(db, customer_id, item_code)
    year = int(order_date[:4])
    holiday_status = ensure_country_holidays(db, customer.get("country_code"), year, country_catalog)
    month_start = order_date[:7] + "-01"
    month_end = order_date[:7] + "-31"
    holidays_rows = [
        _row(row) for row in db.execute(
            "SELECT * FROM country_holidays WHERE country_code=? AND holiday_date BETWEEN ? AND ? ORDER BY holiday_date",
            (str(customer.get("country_code") or "").zfill(3), month_start, month_end),
        ).fetchall()
    ]
    closures = [
        _row(row) for row in db.execute(
            """SELECT * FROM customer_closures WHERE customer_id=? AND deleted_at IS NULL
               AND start_date<=? AND end_date>=? ORDER BY start_date""",
            (customer_id, month_end, month_start),
        ).fetchall()
    ]
    legacy_logistics = _row(db.execute(
        "SELECT * FROM customer_logistics WHERE customer_id=? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1",
        (customer_id,),
    ).fetchone()) or {}
    context = {
        "customer": {"id": customer["id"], "customer_id": customer["customer_id"], "display_name": customer["display_name"], "contract_policy": policy},
        "item": {"code": item_code, "label": INTERIM_CONTRACT_PRODUCTS[item_code], "business_unit": ITEM_BUSINESS_UNITS[item_code]},
        "order_date": order_date,
        "base_source": base_type,
        "source_contract_id": contract["id"] if contract else None,
        "source_customer_term_id": base["id"] if base_type == "customer_default" else None,
        "source_promotion_id": promotion_id or None,
        "pricing_source": "promotion" if promotion else base_type,
        "unit_price": unit_price,
        "currency": currency,
        "moq_quantity": moq_quantity,
        "moq_uom": moq_uom,
        "foc_markup_pct": foc_markup_pct,
        "foc_display": f"10+{float(foc_markup_pct or 0) / 10:g}" if foc_markup_pct is not None else "",
        "packaging_label_code": label_code,
        "packaging_label_other": label_other,
        "payment_terms": payment,
        "payment_source": payment_source,
        "incoterms": payment.get("incoterms_code") or legacy_logistics.get("incoterms") or "",
        "required_documents": docs,
        "logistics_warning": legacy_logistics.get("customs_invoice_notes") or legacy_logistics.get("notes") or "",
        "country_holidays": holidays_rows,
        "customer_closures": closures,
        "holiday_provider": holiday_status,
        "resolved_at": _now(),
    }
    return context


def monthly_sale_context_columns(context, *, source_type=None, promotion_line_id=None):
    return {
        "interim_product_code": context["item"]["code"],
        "source_type": source_type or ("promotion" if context.get("source_promotion_id") else "regular"),
        "source_promotion_id": context.get("source_promotion_id"),
        "source_promotion_line_id": promotion_line_id,
        "source_contract_id": context.get("source_contract_id"),
        "source_customer_term_id": context.get("source_customer_term_id"),
        "pricing_source": context.get("pricing_source"),
        "snapshot_unit_price": context.get("unit_price"),
        "snapshot_currency": context.get("currency"),
        "snapshot_moq_quantity": context.get("moq_quantity"),
        "snapshot_moq_uom": context.get("moq_uom"),
        "snapshot_foc_markup_pct": context.get("foc_markup_pct"),
        "snapshot_label_code": context.get("packaging_label_code"),
        "snapshot_label_other": context.get("packaging_label_other") or "",
        "snapshot_payment_terms_json": _json(context.get("payment_terms") or {}),
        "snapshot_incoterms": context.get("incoterms") or "",
        "commercial_context_json": _json(context),
        "commercial_context_resolved_at": context.get("resolved_at") or _now(),
        "commercial_terms_managed": int(bool(context.get("source_promotion_id"))),
    }


def apply_monthly_sale_context(db, sale_id, context, *, source_type=None, promotion_line_id=None):
    columns = monthly_sale_context_columns(context, source_type=source_type, promotion_line_id=promotion_line_id)
    db.execute(
        "UPDATE monthly_sales SET " + ",".join(f"{key}=?" for key in columns) + " WHERE id=?",
        (*columns.values(), sale_id),
    )


def inherit_monthly_sale_context(db, source_sale_id, target_sale_id):
    """Copy an immutable order snapshot to a split/carryover derivative.

    The stable Promotion Sales Line stays attached to exactly one official
    Monthly Sale.  A derivative keeps the commercial lineage and values, but
    is no longer source-managed by that one Promotion line.
    """
    source = db.execute(
        """SELECT interim_product_code,future_product_master_id,source_type,source_promotion_id,
                  source_contract_id,source_customer_term_id,pricing_source,snapshot_unit_price,
                  snapshot_currency,snapshot_moq_quantity,snapshot_moq_uom,snapshot_foc_markup_pct,
                  snapshot_label_code,snapshot_label_other,snapshot_payment_terms_json,
                  snapshot_incoterms,commercial_context_json,commercial_context_resolved_at
           FROM monthly_sales WHERE id=?""",
        (source_sale_id,),
    ).fetchone()
    if not source or not source["interim_product_code"]:
        return
    columns = [
        "interim_product_code", "future_product_master_id", "source_type", "source_promotion_id",
        "source_contract_id", "source_customer_term_id", "pricing_source", "snapshot_unit_price",
        "snapshot_currency", "snapshot_moq_quantity", "snapshot_moq_uom", "snapshot_foc_markup_pct",
        "snapshot_label_code", "snapshot_label_other", "snapshot_payment_terms_json",
        "snapshot_incoterms", "commercial_context_json", "commercial_context_resolved_at",
    ]
    values = [source[column] for column in columns]
    if source["source_promotion_id"]:
        values[columns.index("source_type")] = "promotion_derivative"
    db.execute(
        "UPDATE monthly_sales SET " + ",".join(f"{column}=?" for column in columns)
        + ",source_promotion_line_id=NULL,commercial_terms_managed=0 WHERE id=?",
        (*values, target_sale_id),
    )


def customer_commercial_bundle(db, customer_id, country_catalog=None):
    customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        raise ValueError("거래처를 찾을 수 없습니다.")
    customer = _row(customer)
    current_year = date.today().year
    holiday_provider = ensure_country_holidays(db, customer.get("country_code"), current_year, country_catalog)
    contracts = [
        _contract_payload(db, row)
        for row in db.execute(
            "SELECT * FROM customer_contracts WHERE customer_id=? AND deleted_at IS NULL ORDER BY COALESCE(start_date,'') DESC,created_at DESC",
            (customer_id,),
        ).fetchall()
    ]
    documents = []
    for row in db.execute(
        "SELECT * FROM customer_document_requirements WHERE customer_id=? AND deleted_at IS NULL ORDER BY document_code,created_at",
        (customer_id,),
    ).fetchall():
        item = _row(row)
        item["interim_product_codes"] = [
            value["interim_product_code"] for value in db.execute(
                "SELECT interim_product_code FROM customer_document_requirement_items WHERE requirement_id=? ORDER BY interim_product_code",
                (item["id"],),
            ).fetchall()
        ]
        item["label"] = item["other_document_name"] if item["document_code"] == "other" else DOCUMENT_CATALOG.get(item["document_code"], item["document_code"])
        documents.append(item)
    providers = [
        _row(row) for row in db.execute(
            """SELECT cp.*,p.provider_type,p.company_name,p.website,p.country_code,p.country_name,
                      p.active AS provider_active,p.version AS provider_version
               FROM customer_logistics_providers cp JOIN logistics_providers p ON p.id=cp.provider_id
               WHERE cp.customer_id=? AND cp.deleted_at IS NULL AND p.deleted_at IS NULL
               ORDER BY p.provider_type,p.company_name COLLATE NOCASE""",
            (customer_id,),
        ).fetchall()
    ]
    return {
        "contract_policy": customer.get("contract_policy"),
        "contract_policy_review_required": not bool(customer.get("contract_policy")),
        "items": customer_item_rows(db, customer_id),
        "contracts": contracts,
        "default_terms": [
            _default_term_payload(row) for row in db.execute(
                """SELECT * FROM customer_product_terms WHERE customer_id=? AND deleted_at IS NULL
                   ORDER BY interim_product_code,COALESCE(term_start_date,'') DESC,created_at DESC""",
                (customer_id,),
            ).fetchall()
        ],
        "default_payment": _row(db.execute(
            "SELECT * FROM customer_payment_terms WHERE customer_id=? AND contract_id IS NULL AND deleted_at IS NULL AND is_current=1 ORDER BY created_at DESC LIMIT 1",
            (customer_id,),
        ).fetchone()),
        "addresses": [_row(row) for row in db.execute(
            "SELECT * FROM customer_logistics_addresses WHERE customer_id=? AND deleted_at IS NULL ORDER BY address_role,created_at",
            (customer_id,),
        ).fetchall()],
        "providers": providers,
        "document_requirements": documents,
        "closures": [_row(row) for row in db.execute(
            "SELECT * FROM customer_closures WHERE customer_id=? AND deleted_at IS NULL ORDER BY start_date DESC",
            (customer_id,),
        ).fetchall()],
        "country_holidays": [_row(row) for row in db.execute(
            "SELECT * FROM country_holidays WHERE country_code=? AND holiday_year=? ORDER BY holiday_date",
            (str(customer.get("country_code") or "").zfill(3), current_year),
        ).fetchall()],
        "holiday_provider": holiday_provider,
        "sales_plan_actual_status": "ERP 실적 연결 대기",
    }


def _ensure_customer(db, customer_id):
    customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        raise ValueError("거래처를 찾을 수 없습니다.")
    return customer


def _assert_version(data, row, label="정보"):
    requested = data.get("version")
    if requested in (None, ""):
        return
    try:
        requested = int(requested)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 버전 정보가 올바르지 않습니다.") from exc
    if requested != int(row["version"] or 1):
        error = RuntimeError(f"다른 사용자가 먼저 {label}를 수정했습니다. 최신 내용을 다시 불러오세요.")
        error.code = "VERSION_CONFLICT"
        raise error


def _replace_contract_countries(db, contract_id, country_codes, country_catalog, actor_id, timestamp):
    requested = {_clean(value, 3) for value in (country_codes or []) if _clean(value, 3)}
    invalid = requested - set(country_catalog or {})
    if invalid:
        raise ValueError("계약 Territory는 표준 국가목록에서 선택하세요.")
    active = {
        row["country_code"]: row
        for row in db.execute(
            "SELECT * FROM customer_contract_countries WHERE contract_id=? AND deleted_at IS NULL", (contract_id,)
        ).fetchall()
    }
    for code in sorted(set(active) - requested):
        db.execute(
            "UPDATE customer_contract_countries SET deleted_at=?,updated_by=?,updated_at=? WHERE id=?",
            (timestamp, actor_id, timestamp, active[code]["id"]),
        )
    for code in sorted(requested - set(active)):
        reusable = db.execute(
            "SELECT id FROM customer_contract_countries WHERE contract_id=? AND country_code=? AND deleted_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (contract_id, code),
        ).fetchone()
        if reusable:
            db.execute(
                "UPDATE customer_contract_countries SET deleted_at=NULL,updated_by=?,updated_at=? WHERE id=?",
                (actor_id, timestamp, reusable["id"]),
            )
        else:
            db.execute(
                """INSERT INTO customer_contract_countries
                   (id,contract_id,country_code,source,provenance,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,'user','user_confirmed',?,?,?,?)""",
                (_uuid(), contract_id, code, actor_id, actor_id, timestamp, timestamp),
            )


def _normalize_payment(data, customer_id, contract_id=None):
    method_code = _clean(data.get("payment_method_code"), 40)
    if method_code and method_code not in PAYMENT_METHODS:
        raise ValueError("결제수단을 목록에서 선택하세요.")
    method_other = _clean(data.get("payment_method_other"), 200)
    if method_code == "other" and not method_other:
        raise ValueError("기타 결제수단명을 입력하세요.")
    schedule = data.get("payment_schedule") or data.get("payment_schedule_json") or []
    if isinstance(schedule, str):
        try:
            schedule = json.loads(schedule or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError("지급 Schedule 형식이 올바르지 않습니다.") from exc
    incoterms = _clean(data.get("incoterms_code"), 10).upper()
    if incoterms and incoterms not in INCOTERMS:
        raise ValueError("Incoterms를 목록에서 선택하세요.")
    effective_from = _date(data.get("effective_from"), "Payment 적용 시작일")
    effective_to = _date(data.get("effective_to"), "Payment 적용 종료일")
    if effective_from and effective_to and effective_from > effective_to:
        raise ValueError("Payment 적용 시작일은 종료일보다 늦을 수 없습니다.")
    return {
        "customer_id": customer_id,
        "contract_id": contract_id,
        "payment_method": _clean(data.get("payment_method"), 500),
        "payment_method_code": method_code or None,
        "payment_method_other": method_other,
        "payment_schedule_json": _json(schedule),
        "collection_basis": _clean(data.get("collection_basis"), 40) or "shipment_date",
        "deferred_days": int(_number(data.get("deferred_days"), "후불일수", 0)),
        "currency": _clean(data.get("currency"), 8) or "USD",
        "incoterms_code": incoterms or None,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "notes": _clean(data.get("notes"), 2000),
    }


def _upsert_payment(db, customer_id, contract_id, data, actor_id, timestamp):
    values = _normalize_payment(data, customer_id, contract_id)
    existing = db.execute(
        """SELECT * FROM customer_payment_terms
           WHERE customer_id=? AND contract_id IS ? AND deleted_at IS NULL AND is_current=1
           ORDER BY created_at DESC LIMIT 1""",
        (customer_id, contract_id),
    ).fetchone()
    if existing:
        if data.get("version") not in (None, ""):
            _assert_version(data, existing, "Payment 조건")
        db.execute(
            """UPDATE customer_payment_terms SET payment_method=?,payment_method_code=?,payment_method_other=?,
               payment_schedule_json=?,collection_basis=?,deferred_days=?,currency=?,incoterms_code=?,
               effective_from=?,effective_to=?,notes=?,updated_by=?,updated_at=?,version=version+1
               WHERE id=?""",
            (values["payment_method"], values["payment_method_code"], values["payment_method_other"],
             values["payment_schedule_json"], values["collection_basis"], values["deferred_days"],
             values["currency"], values["incoterms_code"], values["effective_from"], values["effective_to"],
             values["notes"], actor_id, timestamp, existing["id"]),
        )
        return existing["id"]
    row_id = _uuid()
    db.execute(
        """INSERT INTO customer_payment_terms
           (id,customer_id,contract_id,payment_method,payment_method_code,payment_method_other,
            payment_schedule_json,collection_basis,deferred_days,currency,incoterms_code,
            effective_from,effective_to,notes,is_current,created_by,updated_by,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)""",
        (row_id, customer_id, contract_id, values["payment_method"], values["payment_method_code"],
         values["payment_method_other"], values["payment_schedule_json"], values["collection_basis"],
         values["deferred_days"], values["currency"], values["incoterms_code"], values["effective_from"],
         values["effective_to"], values["notes"], actor_id, actor_id, timestamp, timestamp),
    )
    return row_id


def _replace_sales_plans(db, customer_id, contract_id, plans, actor_id, timestamp):
    if plans is None:
        return
    requested = {}
    for raw in plans:
        target_type = _clean(raw.get("target_type"), 20) or "amount"
        if target_type not in {"amount", "quantity"}:
            raise ValueError("Sales Plan 유형은 Amount 또는 Quantity 중에서 선택하세요.")
        item_code = _clean(raw.get("interim_product_code"), 80)
        if item_code:
            item_code = validate_item_code(item_code)
        plan_year = int(_number(raw.get("plan_year"), "Sales Plan 연도", 2000))
        target_amount = _number(raw.get("target_amount"), "목표금액", 0, True)
        target_quantity = _number(raw.get("target_quantity"), "목표수량", 0, True)
        if target_type == "amount" and target_amount is None:
            raise ValueError("Amount Sales Plan은 목표금액을 입력하세요.")
        if target_type == "quantity" and target_quantity is None:
            raise ValueError("Quantity Sales Plan은 목표수량을 입력하세요.")
        business_unit = ITEM_BUSINESS_UNITS.get(item_code, _clean(raw.get("business_unit"), 20))
        product_group = f"contract:{contract_id}:{item_code or 'total'}"
        key = (plan_year, business_unit, product_group)
        if key in requested:
            raise ValueError("같은 Contract Sales Plan 범위를 중복 등록할 수 없습니다.")
        requested[key] = {
            "plan_year": plan_year, "business_unit": business_unit, "product_group": product_group,
            "target_type": target_type, "interim_product_code": item_code or None,
            "target_amount": target_amount, "target_quantity": target_quantity,
            "target_uom": _clean(raw.get("target_uom"), 20), "applied_amount": target_amount or 0,
            "currency": _clean(raw.get("currency"), 8) or "USD", "override_reason": _clean(raw.get("notes"), 1000),
        }
    current = {
        (row["plan_year"], row["business_unit"], row["product_group"]): row
        for row in db.execute("SELECT * FROM customer_sales_plans WHERE contract_id=? AND deleted_at IS NULL", (contract_id,)).fetchall()
    }
    for key, row in current.items():
        if key not in requested:
            db.execute(
                "UPDATE customer_sales_plans SET deleted_at=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?",
                (timestamp, actor_id, timestamp, row["id"]),
            )
    for key, values in requested.items():
        existing = db.execute(
            """SELECT * FROM customer_sales_plans WHERE customer_id=? AND plan_year=?
               AND business_unit=? AND product_group=?""",
            (customer_id, *key),
        ).fetchone()
        if existing:
            db.execute(
                """UPDATE customer_sales_plans SET contract_id=?,target_type=?,interim_product_code=?,
                   target_amount=?,target_quantity=?,target_uom=?,applied_amount=?,currency=?,override_reason=?,
                   deleted_at=NULL,updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
                (contract_id, values["target_type"], values["interim_product_code"], values["target_amount"],
                 values["target_quantity"], values["target_uom"], values["applied_amount"], values["currency"],
                 values["override_reason"], actor_id, timestamp, existing["id"]),
            )
        else:
            row_id = _uuid()
            db.execute(
                """INSERT INTO customer_sales_plans
                   (id,customer_id,contract_id,plan_year,business_unit,product_group,target_type,
                    interim_product_code,target_amount,target_quantity,target_uom,applied_amount,currency,
                    override_reason,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row_id, customer_id, contract_id, values["plan_year"], values["business_unit"], values["product_group"],
                 values["target_type"], values["interim_product_code"], values["target_amount"],
                 values["target_quantity"], values["target_uom"], values["applied_amount"], values["currency"],
                 values["override_reason"], actor_id, actor_id, timestamp, timestamp),
            )


def _term_signature(raw):
    normalized = _validate_term(raw)
    return tuple(normalized.get(key) for key in (
        "interim_product_code", "unit_price", "currency", "price_method_code",
        "moq_quantity", "moq_uom", "foc_markup_pct", "packaging_label_code",
        "packaging_label_other", "notes",
    ))


def _payment_signature(raw, customer_id, contract_id):
    if not raw:
        return None
    normalized = _normalize_payment(raw, customer_id, contract_id)
    return tuple(normalized.get(key) for key in (
        "payment_method_code", "payment_method_other", "payment_schedule_json",
        "collection_basis", "deferred_days", "currency", "incoterms_code",
        "effective_from", "notes",
    ))


def _sales_plan_signature(raw):
    target_type = _clean(raw.get("target_type"), 20) or "amount"
    return (
        int(_number(raw.get("plan_year"), "Sales Plan 연도", 2000)),
        target_type,
        _clean(raw.get("interim_product_code"), 80) or None,
        _number(raw.get("target_amount"), "목표금액", 0, True),
        _number(raw.get("target_quantity"), "목표수량", 0, True),
        _clean(raw.get("target_uom"), 20) or None,
        _clean(raw.get("currency"), 8) or "USD",
        _clean(raw.get("override_reason", raw.get("notes")), 1000),
    )


def _assert_period_only_extension(db, customer_id, contract_id, existing, merged, item_codes, terms, data):
    """An extension preserves every commercial term and changes only its period."""
    scalar_keys = ("contract_no", "start_date", "end_date", "exclusivity", "currency", "notes")
    requested_scalars = tuple(
        _clean(merged.get(key), 4000) if key != "currency" else (_clean(merged.get(key), 8) or "USD")
        for key in scalar_keys
    )
    previous_scalars = tuple(
        (_clean(existing[key], 8) or "USD") if key == "currency" else _clean(existing[key], 4000)
        for key in scalar_keys
    )
    previous_items = sorted(_contract_item_codes(db, contract_id))
    previous_countries = sorted(
        row["country_code"] for row in db.execute(
            "SELECT country_code FROM customer_contract_countries WHERE contract_id=? AND deleted_at IS NULL",
            (contract_id,),
        ).fetchall()
    )
    requested_countries = sorted(
        data.get("territory_country_codes") if "territory_country_codes" in data else previous_countries
    )
    previous_terms = sorted(
        _term_signature(_row(row)) for row in db.execute(
            "SELECT * FROM customer_contract_item_terms WHERE contract_id=? AND deleted_at IS NULL",
            (contract_id,),
        ).fetchall()
    )
    requested_terms = sorted(_term_signature(row) for row in terms)
    previous_payment = db.execute(
        """SELECT * FROM customer_payment_terms WHERE customer_id=? AND contract_id=?
           AND deleted_at IS NULL AND is_current=1 ORDER BY created_at DESC LIMIT 1""",
        (customer_id, contract_id),
    ).fetchone()
    requested_payment = data.get("payment_override") if data.get("payment_override") is not None else _row(previous_payment)
    previous_plans = sorted(
        _sales_plan_signature(_row(row)) for row in db.execute(
            "SELECT * FROM customer_sales_plans WHERE contract_id=? AND deleted_at IS NULL",
            (contract_id,),
        ).fetchall()
    )
    requested_plans = data.get("sales_plans")
    if requested_plans is None:
        requested_plans = [_row(row) for row in db.execute(
            "SELECT * FROM customer_sales_plans WHERE contract_id=? AND deleted_at IS NULL",
            (contract_id,),
        ).fetchall()]
    if any((
        previous_scalars != requested_scalars,
        previous_items != sorted(item_codes),
        previous_countries != requested_countries,
        previous_terms != requested_terms,
        _payment_signature(_row(previous_payment), customer_id, contract_id)
        != _payment_signature(requested_payment, customer_id, contract_id),
        previous_plans != sorted(_sales_plan_signature(row) for row in requested_plans),
    )):
        raise ValueError("연장은 기존 상업조건을 그대로 유지하고 기간만 변경할 때 사용합니다. 조건 변경은 신규 계약으로 등록하세요.")


def _save_contract(db, customer_id, data, actor_id, country_catalog, contract_id=None):
    _ensure_customer(db, customer_id)
    existing = db.execute(
        "SELECT * FROM customer_contracts WHERE id=? AND customer_id=? AND deleted_at IS NULL",
        (contract_id, customer_id),
    ).fetchone() if contract_id else None
    if contract_id and not existing:
        raise ValueError("수정할 계약을 찾을 수 없습니다.")
    if existing:
        _assert_version(data, existing, "계약")
    merged = _row(existing) or {}
    merged.update(data)
    start, end, status, extension_end = _validate_contract_state(merged)
    terms = data.get("item_terms")
    if terms is None and existing:
        terms = [_row(row) for row in db.execute(
            "SELECT * FROM customer_contract_item_terms WHERE contract_id=? AND deleted_at IS NULL", (contract_id,)
        ).fetchall()]
    terms = terms or []
    item_codes = data.get("interim_product_codes")
    if item_codes is None:
        item_codes = [row.get("interim_product_code") for row in terms] if terms else (_contract_item_codes(db, contract_id) if contract_id else [])
    item_codes = list(dict.fromkeys(validate_item_code(value) for value in item_codes))
    if not item_codes:
        raise ValueError("계약 적용 Item을 하나 이상 선택하세요.")
    _assert_customer_portfolio(db, customer_id, item_codes, "계약")
    effective_end = extension_end if status == "extended" else end
    legacy_status = "active" if status == "extended" else status
    if existing and status == "extended":
        _assert_period_only_extension(db, customer_id, contract_id, existing, merged, item_codes, terms, data)
    validate_contract_item_conflicts(db, customer_id, contract_id, item_codes, start, effective_end, status)
    timestamp = _now()
    if existing:
        db.execute(
            """UPDATE customer_contracts SET contract_no=?,start_date=?,end_date=?,commercial_status_code=?,
               contract_status_code=?,extension_end_date=?,exclusivity=?,currency=?,notes=?,
               updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
            (_clean(merged.get("contract_no"), 200), start, end, status, legacy_status, extension_end,
             _clean(merged.get("exclusivity"), 40), _clean(merged.get("currency"), 8) or "USD",
             _clean(merged.get("notes"), 4000), actor_id, timestamp, contract_id),
        )
    else:
        contract_id = _uuid()
        db.execute(
            """INSERT INTO customer_contracts
               (id,customer_id,contract_no,contract_name,contract_status,contract_status_code,
                commercial_status_code,start_date,end_date,extension_end_date,exclusivity,currency,notes,
                normalization_status,created_by,updated_by,created_at,updated_at,version)
               VALUES (?,?,?,'',?,?,?,?,?,?,?,?,?,'confirmed',?,?,?,?,1)""",
            (contract_id, customer_id, _clean(merged.get("contract_no"), 200), legacy_status, legacy_status, status,
             start, end, extension_end, _clean(merged.get("exclusivity"), 40),
             _clean(merged.get("currency"), 8) or "USD", _clean(merged.get("notes"), 4000),
             actor_id, actor_id, timestamp, timestamp),
        )
    _replace_contract_products(db, contract_id, item_codes, actor_id, timestamp)
    if "territory_country_codes" in data or not existing:
        _replace_contract_countries(db, contract_id, data.get("territory_country_codes") or [], country_catalog, actor_id, timestamp)
    if terms is not None:
        invalid_terms = {row.get("interim_product_code") for row in terms} - set(item_codes)
        if invalid_terms:
            raise ValueError("가격조건 Item은 계약 적용 Item에 포함되어야 합니다.")
        _upsert_contract_item_terms(db, contract_id, terms, actor_id, timestamp)
    if data.get("payment_override") is not None:
        _upsert_payment(db, customer_id, contract_id, data.get("payment_override") or {}, actor_id, timestamp)
    _replace_sales_plans(db, customer_id, contract_id, data.get("sales_plans"), actor_id, timestamp)
    return _contract_payload(db, db.execute("SELECT * FROM customer_contracts WHERE id=?", (contract_id,)).fetchone())


def _validate_default_term_conflict(db, customer_id, term_id, item_code, start, end, status):
    if status != "active":
        return
    start_key, end_key = start or "0001-01-01", end or "9999-12-31"
    rows = db.execute(
        """SELECT * FROM customer_product_terms
           WHERE customer_id=? AND id<>? AND interim_product_code=? AND deleted_at IS NULL
             AND commercial_status_code='active'""",
        (customer_id, term_id or "", item_code),
    ).fetchall()
    for row in rows:
        other_start = row["term_start_date"] or "0001-01-01"
        other_end = row["term_end_date"] or "9999-12-31"
        if _overlap(start_key, end_key, other_start, other_end):
            raise ValueError("같은 Customer+Item+기간에 Active 기본 가격조건이 이미 있습니다.")


def _save_default_term(db, customer_id, data, actor_id, term_id=None):
    _ensure_customer(db, customer_id)
    existing = db.execute(
        "SELECT * FROM customer_product_terms WHERE id=? AND customer_id=? AND deleted_at IS NULL",
        (term_id, customer_id),
    ).fetchone() if term_id else None
    if term_id and not existing:
        raise ValueError("수정할 기본 가격조건을 찾을 수 없습니다.")
    if existing:
        _assert_version(data, existing, "기본 가격조건")
    merged = _row(existing) or {}
    merged.update(data)
    normalized = _validate_term({
        "interim_product_code": merged.get("interim_product_code"),
        "unit_price": merged.get("agreed_unit_price", merged.get("unit_price")),
        "currency": merged.get("currency"),
        "price_method_code": merged.get("price_method_code"),
        "moq_quantity": merged.get("moq_quantity"),
        "moq_uom": merged.get("moq_uom"),
        "foc_markup_pct": merged.get("foc_markup_pct"),
        "packaging_label_code": merged.get("packaging_label_code"),
        "packaging_label_other": merged.get("packaging_label_other"),
        "notes": merged.get("notes"),
    })
    start = _date(merged.get("term_start_date"), "기본조건 적용 시작일")
    end = _date(merged.get("term_end_date"), "기본조건 적용 종료일")
    if start and end and start > end:
        raise ValueError("기본조건 적용 시작일은 종료일보다 늦을 수 없습니다.")
    status = _clean(merged.get("commercial_status_code"), 20) or "active"
    if status not in {"active", "expired"}:
        raise ValueError("기본 가격조건 상태는 유효 또는 만료 중에서 선택하세요.")
    _assert_customer_portfolio(db, customer_id, [normalized["interim_product_code"]], "기본 가격조건")
    _validate_default_term_conflict(db, customer_id, term_id, normalized["interim_product_code"], start, end, status)
    timestamp = _now()
    if existing:
        db.execute(
            """UPDATE customer_product_terms SET interim_product_code=?,product_name=?,agreed_unit_price=?,currency=?,
               price_method_code=?,moq_quantity=?,moq=?,moq_uom=?,foc_markup_pct=?,packaging_label_code=?,
               packaging_label_other=?,term_start_date=?,term_end_date=?,commercial_status_code=?,notes=?,
               updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
            (normalized["interim_product_code"], INTERIM_CONTRACT_PRODUCTS[normalized["interim_product_code"]],
             normalized["unit_price"], normalized["currency"], normalized["price_method_code"],
             normalized["moq_quantity"], normalized["moq_quantity"] or 0, normalized["moq_uom"],
             normalized["foc_markup_pct"], normalized["packaging_label_code"], normalized["packaging_label_other"],
             start, end, status, normalized["notes"], actor_id, timestamp, term_id),
        )
    else:
        term_id = _uuid()
        db.execute(
            """INSERT INTO customer_product_terms
               (id,customer_id,interim_product_code,product_name,price_type,agreed_unit_price,currency,
                moq,moq_basis,price_method_code,moq_quantity,moq_uom,foc_markup_pct,
                packaging_label_code,packaging_label_other,term_start_date,term_end_date,
                commercial_status_code,notes,is_current,created_by,updated_by,created_at,updated_at,version)
               VALUES (?,?,?,?,'customer',?,?,?,'paid',?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,1)""",
            (term_id, customer_id, normalized["interim_product_code"], INTERIM_CONTRACT_PRODUCTS[normalized["interim_product_code"]],
             normalized["unit_price"], normalized["currency"], normalized["moq_quantity"] or 0,
             normalized["price_method_code"], normalized["moq_quantity"], normalized["moq_uom"],
             normalized["foc_markup_pct"], normalized["packaging_label_code"], normalized["packaging_label_other"],
             start, end, status, normalized["notes"], actor_id, actor_id, timestamp, timestamp),
        )
    return _default_term_payload(db.execute("SELECT * FROM customer_product_terms WHERE id=?", (term_id,)).fetchone())


def _save_address(db, customer_id, data, actor_id, row_id=None):
    _ensure_customer(db, customer_id)
    existing = db.execute(
        "SELECT * FROM customer_logistics_addresses WHERE id=? AND customer_id=? AND deleted_at IS NULL",
        (row_id, customer_id),
    ).fetchone() if row_id else None
    if row_id and not existing:
        raise ValueError("수정할 주소를 찾을 수 없습니다.")
    if existing:
        _assert_version(data, existing, "주소")
    merged = _row(existing) or {}
    merged.update(data)
    role = _clean(merged.get("address_role"), 30, True, "주소 역할")
    if role not in ADDRESS_ROLES:
        raise ValueError("주소 역할을 Bill To·Ship To·Consignee·Notify Party 중에서 선택하세요.")
    country_code = _clean(merged.get("country_code"), 3) or None
    timestamp = _now()
    values = (
        role, _clean(merged.get("company_name"), 300), _clean(merged.get("address_line1"), 500),
        _clean(merged.get("address_line2"), 500), _clean(merged.get("city"), 120),
        _clean(merged.get("state_province"), 120), _clean(merged.get("postal_code"), 40),
        country_code, _clean(merged.get("country_name"), 120), _clean(merged.get("phone"), 100),
        _clean(merged.get("email"), 200), _clean(merged.get("tax_importer_id"), 200),
        _clean(merged.get("note"), 2000), int(bool(merged.get("active", True))),
    )
    if existing:
        db.execute(
            """UPDATE customer_logistics_addresses SET address_role=?,company_name=?,address_line1=?,
               address_line2=?,city=?,state_province=?,postal_code=?,country_code=?,country_name=?,phone=?,
               email=?,tax_importer_id=?,note=?,active=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
            (*values, actor_id, timestamp, row_id),
        )
    else:
        row_id = _uuid()
        db.execute(
            """INSERT INTO customer_logistics_addresses
               (id,customer_id,address_role,company_name,address_line1,address_line2,city,state_province,
                postal_code,country_code,country_name,phone,email,tax_importer_id,note,active,
                created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row_id, customer_id, *values, actor_id, actor_id, timestamp, timestamp),
        )
    return _row(db.execute("SELECT * FROM customer_logistics_addresses WHERE id=?", (row_id,)).fetchone())


def _save_provider(db, customer_id, data, actor_id, row_id=None):
    _ensure_customer(db, customer_id)
    existing_relation = db.execute(
        "SELECT * FROM customer_logistics_providers WHERE id=? AND customer_id=? AND deleted_at IS NULL",
        (row_id, customer_id),
    ).fetchone() if row_id else None
    if row_id and not existing_relation:
        raise ValueError("수정할 물류 Provider를 찾을 수 없습니다.")
    if existing_relation:
        _assert_version(data, existing_relation, "물류 Provider")
    provider_id = data.get("provider_id") or (existing_relation["provider_id"] if existing_relation else None)
    provider = db.execute("SELECT * FROM logistics_providers WHERE id=? AND deleted_at IS NULL", (provider_id,)).fetchone() if provider_id else None
    provider_type = _clean(data.get("provider_type", provider["provider_type"] if provider else ""), 30, True, "Provider 유형")
    if provider_type not in PROVIDER_TYPES:
        raise ValueError("Provider 유형을 Courier·Forwarder·Customs Broker 중에서 선택하세요.")
    company_name = _clean(data.get("company_name", provider["company_name"] if provider else ""), 300, True, "Provider 회사명")
    country_code = _clean(data.get("country_code", provider["country_code"] if provider else ""), 3) or None
    timestamp = _now()
    if not provider:
        provider = db.execute(
            """SELECT * FROM logistics_providers WHERE provider_type=?
               AND company_name=? COLLATE NOCASE AND COALESCE(country_code,'')=COALESCE(?,'') AND deleted_at IS NULL""",
            (provider_type, company_name, country_code),
        ).fetchone()
    if provider:
        provider_id = provider["id"]
        if data.get("update_directory"):
            db.execute(
                """UPDATE logistics_providers SET website=?,country_code=?,country_name=?,active=?,
                   updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
                (_clean(data.get("website"), 500), country_code, _clean(data.get("country_name"), 120),
                 int(bool(data.get("provider_active", True))), actor_id, timestamp, provider_id),
            )
    else:
        provider_id = _uuid()
        db.execute(
            """INSERT INTO logistics_providers
               (id,provider_type,company_name,website,country_code,country_name,active,
                created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,1,?,?,?,?)""",
            (provider_id, provider_type, company_name, _clean(data.get("website"), 500), country_code,
             _clean(data.get("country_name"), 120), actor_id, actor_id, timestamp, timestamp),
        )
    relation_values = (
        _clean(data.get("contact_person"), 200), _clean(data.get("department"), 200),
        _clean(data.get("phone"), 100), _clean(data.get("email"), 200),
        _clean(data.get("account_number"), 200), _clean(data.get("note"), 2000),
        int(bool(data.get("active", True))),
    )
    if existing_relation:
        db.execute(
            """UPDATE customer_logistics_providers SET provider_id=?,contact_person=?,department=?,phone=?,
               email=?,account_number=?,note=?,active=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
            (provider_id, *relation_values, actor_id, timestamp, row_id),
        )
    else:
        row_id = _uuid()
        db.execute(
            """INSERT INTO customer_logistics_providers
               (id,customer_id,provider_id,contact_person,department,phone,email,account_number,note,active,
                created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row_id, customer_id, provider_id, *relation_values, actor_id, actor_id, timestamp, timestamp),
        )
    return _row(db.execute(
        """SELECT cp.*,p.provider_type,p.company_name,p.website,p.country_code,p.country_name,
                  p.active AS provider_active,p.version AS provider_version
           FROM customer_logistics_providers cp JOIN logistics_providers p ON p.id=cp.provider_id WHERE cp.id=?""",
        (row_id,),
    ).fetchone())


def _replace_document_items(db, requirement_id, item_codes, actor_id, timestamp):
    requested = {validate_item_code(value) for value in (item_codes or [])}
    current = {
        row["interim_product_code"]: row
        for row in db.execute(
            "SELECT * FROM customer_document_requirement_items WHERE requirement_id=?", (requirement_id,)
        ).fetchall()
    }
    for code in set(current) - requested:
        db.execute("DELETE FROM customer_document_requirement_items WHERE id=?", (current[code]["id"],))
    for code in requested - set(current):
        db.execute(
            """INSERT INTO customer_document_requirement_items
               (id,requirement_id,interim_product_code,created_by,created_at) VALUES (?,?,?,?,?)""",
            (_uuid(), requirement_id, code, actor_id, timestamp),
        )


def _save_document(db, customer_id, data, actor_id, row_id=None):
    _ensure_customer(db, customer_id)
    existing = db.execute(
        "SELECT * FROM customer_document_requirements WHERE id=? AND customer_id=? AND deleted_at IS NULL",
        (row_id, customer_id),
    ).fetchone() if row_id else None
    if row_id and not existing:
        raise ValueError("수정할 무역서류 요구조건을 찾을 수 없습니다.")
    if existing:
        _assert_version(data, existing, "무역서류 요구조건")
    merged = _row(existing) or {}
    merged.update(data)
    document_code = _clean(merged.get("document_code"), 60, True, "Document")
    if document_code not in DOCUMENT_CATALOG:
        raise ValueError("Document를 기본 Catalog에서 선택하세요.")
    other_name = _clean(merged.get("other_document_name"), 200)
    if document_code == "other" and not other_name:
        raise ValueError("Other Document 이름을 입력하세요.")
    item_scope = _clean(merged.get("item_scope"), 20) or "all"
    if item_scope not in {"all", "selected"}:
        raise ValueError("Document 적용범위를 전체 Item 또는 선택 Item으로 지정하세요.")
    item_codes = data.get("interim_product_codes")
    if item_codes is None and existing:
        item_codes = [row["interim_product_code"] for row in db.execute(
            "SELECT interim_product_code FROM customer_document_requirement_items WHERE requirement_id=?", (row_id,)
        ).fetchall()]
    item_codes = item_codes or []
    if item_scope == "selected" and not item_codes:
        raise ValueError("선택 Item 범위에는 Item을 하나 이상 지정하세요.")
    frequency = _clean(merged.get("frequency_code"), 40) or "every_shipment"
    unit = _clean(merged.get("document_unit_code"), 40) or "shipment"
    legalization = _clean(merged.get("legalization_code"), 40) or "none"
    if frequency not in DOCUMENT_FREQUENCIES or unit not in DOCUMENT_UNITS or legalization not in LEGALIZATION_TYPES:
        raise ValueError("Document Frequency·Unit·Legalization 값을 목록에서 선택하세요.")
    timestamp = _now()
    values = (document_code, other_name, item_scope, int(bool(merged.get("required", True))), frequency,
              unit, int(bool(merged.get("original_required", False))), legalization,
              _clean(merged.get("language_code"), 20), _clean(merged.get("note"), 2000))
    if existing:
        db.execute(
            """UPDATE customer_document_requirements SET document_code=?,other_document_name=?,item_scope=?,
               required=?,frequency_code=?,document_unit_code=?,original_required=?,legalization_code=?,
               language_code=?,note=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
            (*values, actor_id, timestamp, row_id),
        )
    else:
        row_id = _uuid()
        db.execute(
            """INSERT INTO customer_document_requirements
               (id,customer_id,document_code,other_document_name,item_scope,required,frequency_code,
                document_unit_code,original_required,legalization_code,language_code,note,
                created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row_id, customer_id, *values, actor_id, actor_id, timestamp, timestamp),
        )
    _replace_document_items(db, row_id, item_codes if item_scope == "selected" else [], actor_id, timestamp)
    result = _row(db.execute("SELECT * FROM customer_document_requirements WHERE id=?", (row_id,)).fetchone())
    result["interim_product_codes"] = list(item_codes) if item_scope == "selected" else []
    return result


def _save_closure(db, customer_id, data, actor_id, row_id=None):
    _ensure_customer(db, customer_id)
    existing = db.execute(
        "SELECT * FROM customer_closures WHERE id=? AND customer_id=? AND deleted_at IS NULL",
        (row_id, customer_id),
    ).fetchone() if row_id else None
    if row_id and not existing:
        raise ValueError("수정할 거래처 휴무일을 찾을 수 없습니다.")
    if existing:
        _assert_version(data, existing, "거래처 휴무일")
    merged = _row(existing) or {}
    merged.update(data)
    start = _date(merged.get("start_date"), "휴무 시작일", True)
    end = _date(merged.get("end_date"), "휴무 종료일", True)
    if start > end:
        raise ValueError("휴무 시작일은 종료일보다 늦을 수 없습니다.")
    title = _clean(merged.get("title"), 300, True, "휴무명")
    note = _clean(merged.get("note"), 2000)
    timestamp = _now()
    if existing:
        db.execute(
            """UPDATE customer_closures SET start_date=?,end_date=?,title=?,note=?,updated_by=?,updated_at=?,
               version=version+1 WHERE id=?""",
            (start, end, title, note, actor_id, timestamp, row_id),
        )
    else:
        row_id = _uuid()
        db.execute(
            """INSERT INTO customer_closures
               (id,customer_id,start_date,end_date,title,note,created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (row_id, customer_id, start, end, title, note, actor_id, actor_id, timestamp, timestamp),
        )
    return _row(db.execute("SELECT * FROM customer_closures WHERE id=?", (row_id,)).fetchone())


def _replace_promotion_customers(db, promotion_id, customer_ids, actor_id, timestamp):
    requested = set(customer_ids or [])
    for customer_id in requested:
        _ensure_customer(db, customer_id)
    current = {row["customer_id"]: row for row in db.execute(
        "SELECT * FROM promotion_customer_links WHERE promotion_id=? AND deleted_at IS NULL", (promotion_id,)
    ).fetchall()}
    for customer_id in set(current) - requested:
        db.execute("UPDATE promotion_customer_links SET deleted_at=?,updated_by=?,updated_at=? WHERE id=?",
                   (timestamp, actor_id, timestamp, current[customer_id]["id"]))
    for customer_id in requested - set(current):
        reusable = db.execute(
            "SELECT id FROM promotion_customer_links WHERE promotion_id=? AND customer_id=? AND deleted_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (promotion_id, customer_id),
        ).fetchone()
        if reusable:
            db.execute("UPDATE promotion_customer_links SET deleted_at=NULL,updated_by=?,updated_at=? WHERE id=?",
                       (actor_id, timestamp, reusable["id"]))
        else:
            db.execute(
                """INSERT INTO promotion_customer_links
                   (id,promotion_id,customer_id,created_by,updated_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?)""",
                (_uuid(), promotion_id, customer_id, actor_id, actor_id, timestamp, timestamp),
            )


def _normalize_promotion_item(raw):
    code = validate_item_code(raw.get("interim_product_code"))
    result = {"interim_product_code": code}
    for key, label in (("price_override", "Promotion 가격"), ("foc_markup_override_pct", "Promotion FOC"),
                       ("moq_quantity_override", "Promotion MOQ")):
        result[key] = _number(raw.get(key), label, 0, True)
    result["currency_override"] = _clean(raw.get("currency_override"), 8) or None
    if result["currency_override"] and result["currency_override"] not in {"USD", "EUR", "JPY", "CNH", "KRW"}:
        raise ValueError("Promotion 통화를 목록에서 선택하세요.")
    result["moq_uom_override"] = _clean(raw.get("moq_uom_override"), 20) or None
    result["packaging_label_override_code"] = _clean(raw.get("packaging_label_override_code"), 40) or None
    result["packaging_label_override_other"] = _clean(raw.get("packaging_label_override_other"), 200)
    return result


def _replace_promotion_items(db, promotion_id, items, actor_id, timestamp):
    requested = {}
    for raw in items or []:
        item = _normalize_promotion_item(raw)
        if item["interim_product_code"] in requested:
            raise ValueError("같은 Promotion Item을 중복 등록할 수 없습니다.")
        requested[item["interim_product_code"]] = item
    if not requested:
        raise ValueError("Promotion Item을 하나 이상 선택하세요.")
    current = {row["interim_product_code"]: _row(row) for row in db.execute(
        "SELECT * FROM promotion_items WHERE promotion_id=? AND deleted_at IS NULL", (promotion_id,)
    ).fetchall()}
    for code in set(current) - set(requested):
        db.execute("UPDATE promotion_items SET deleted_at=?,updated_by=?,updated_at=? WHERE id=?",
                   (timestamp, actor_id, timestamp, current[code]["id"]))
    for code, item in requested.items():
        existing = current.get(code)
        values = (item["price_override"], item["currency_override"], item["foc_markup_override_pct"],
                  item["moq_quantity_override"], item["moq_uom_override"], item["packaging_label_override_code"],
                  item["packaging_label_override_other"])
        if existing:
            db.execute(
                """UPDATE promotion_items SET price_override=?,currency_override=?,foc_markup_override_pct=?,
                   moq_quantity_override=?,moq_uom_override=?,packaging_label_override_code=?,
                   packaging_label_override_other=?,updated_by=?,updated_at=? WHERE id=?""",
                (*values, actor_id, timestamp, existing["id"]),
            )
        else:
            db.execute(
                """INSERT INTO promotion_items
                   (id,promotion_id,interim_product_code,price_override,currency_override,
                    foc_markup_override_pct,moq_quantity_override,moq_uom_override,
                    packaging_label_override_code,packaging_label_override_other,
                    created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_uuid(), promotion_id, code, *values, actor_id, actor_id, timestamp, timestamp),
            )


def _promotion_payload(db, promotion_id):
    row = db.execute(
        """SELECT r.*,t.start_date,t.end_date,t.status_code AS commercial_status_code,t.notes AS commercial_notes,
                  t.version AS commercial_version
           FROM records r JOIN promotion_commercial_terms t ON t.promotion_id=r.id
           WHERE r.id=? AND r.entity_type='promotion' AND r.deleted_at IS NULL""",
        (promotion_id,),
    ).fetchone()
    if not row:
        return None
    result = _row(row)
    result["customer_ids"] = [item["customer_id"] for item in db.execute(
        "SELECT customer_id FROM promotion_customer_links WHERE promotion_id=? AND deleted_at IS NULL ORDER BY customer_id", (promotion_id,)
    ).fetchall()]
    result["items"] = [_row(item) for item in db.execute(
        "SELECT * FROM promotion_items WHERE promotion_id=? AND deleted_at IS NULL ORDER BY interim_product_code", (promotion_id,)
    ).fetchall()]
    result["sales_lines"] = [_row(item) for item in db.execute(
        "SELECT * FROM promotion_sales_lines WHERE promotion_id=? AND deleted_at IS NULL ORDER BY target_month,customer_id,interim_product_code", (promotion_id,)
    ).fetchall()]
    return result


def _promotion_sale_amount(line, context):
    amount = _number(line.get("expected_amount"), "예상 매출금액", 0, True)
    quantity = _number(line.get("expected_quantity"), "예상 수량", 0, True)
    if amount is None and quantity is not None:
        amount = quantity * float(context.get("unit_price") or 0)
    if amount is None or amount <= 0:
        raise ValueError("Promotion 매출계획에는 Expected Amount 또는 Expected Quantity를 입력하세요.")
    return amount, quantity


def _sync_promotion_sale(db, promotion, line_row, actor, now_fn, audit_fn, country_catalog):
    from monthly_sales_fcst import (
        add_history,
        assert_month_open,
        convert_transaction_amount,
        next_sales_no,
        plan_rates,
        sale_snapshot,
    )

    line = _row(line_row)
    order_date = line["target_month"] + "-01"
    context = resolve_customer_order_context(
        db, line["customer_id"], line["interim_product_code"], order_date,
        promotion_id=line["promotion_id"], country_catalog=country_catalog,
    )
    amount, quantity = _promotion_sale_amount(line, context)
    currency = _clean(line.get("currency"), 8) or context.get("currency") or "USD"
    rates = plan_rates(db, line["target_month"])
    amount_usd, krw_amount, plan_rate = convert_transaction_amount(amount, currency, rates)
    assert_month_open(db, line["target_month"], now_fn)
    customer = db.execute("SELECT * FROM customer_master WHERE id=?", (line["customer_id"],)).fetchone()
    owner_id = promotion.get("owner_id") or actor["id"]
    owner = db.execute("SELECT display_name FROM users WHERE id=?", (owner_id,)).fetchone()
    owner_name = owner["display_name"] if owner else actor["display_name"]
    timestamp = now_fn()
    sale = db.execute("SELECT * FROM monthly_sales WHERE source_promotion_line_id=?", (line["id"],)).fetchone()
    if sale and sale["record_status"] != "active":
        raise ValueError("연결된 Promotion FCST가 취소/차월되어 자동 수정할 수 없습니다. 연결 해제 후 다시 처리하세요.")
    if sale:
        before = sale_snapshot(db, sale["id"])
        db.execute(
            """UPDATE monthly_sales SET customer_name=?,country=?,owner_name=?,owner_user_id=?,business_unit=?,
               transaction_currency=?,transaction_currency_standard=?,transaction_amount=?,amount_usd=?,
               plan_rate=?,plan_usd_rate=?,applied_rate=?,krw_amount=?,updated_by=?,updated_at=?,version=version+1
               WHERE id=?""",
            (customer["display_name"], customer["headquarters_country"], owner_name, owner_id,
             ITEM_BUSINESS_UNITS[line["interim_product_code"]], "CNY" if currency == "CNH" else currency,
             currency, amount, amount_usd, plan_rate, float(rates.get("USD") or 0), plan_rate, krw_amount,
             actor["id"], timestamp, sale["id"]),
        )
        apply_monthly_sale_context(db, sale["id"], context, source_type="promotion", promotion_line_id=line["id"])
        add_history(db, sale["id"], "PROMOTION_SYNC", "Promotion 조건/매출계획 동기화", actor, now_fn)
        audit_fn(
            "PROMOTION_MONTHLY_FCST_UPDATE", "monthly_sale", sale["id"],
            f"{promotion['title']} Promotion FCST 동기화", before, sale_snapshot(db, sale["id"]), connection=db,
        )
        sale_id = sale["id"]
    else:
        sale_id = _uuid()
        sales_no = next_sales_no(db, line["target_month"])
        db.execute(
            """INSERT INTO monthly_sales
               (id,sales_no,customer_name,country,owner_name,owner_user_id,business_unit,currency,
                transaction_currency,transaction_currency_standard,transaction_amount,customer_history,
                original_month,target_month,timing_type,amount_usd,plan_rate,plan_usd_rate,applied_rate,
                rate_type,krw_amount,sales_status,record_status,split_role,carryover_role,carryover_decision,
                notes,version,created_by,updated_by,customer_master_id,original_customer_name,
                customer_link_status,customer_linked_at,customer_linked_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,'USD',?,?,?,'existing',?,?,'current_new',?,?,?,?,
                       'plan',?,'pipeline','active','none','none','no',?,1,?,?,?,?,
                       'linked',?,?,?,?)""",
            (sale_id, sales_no, customer["display_name"], customer["headquarters_country"], owner_name, owner_id,
             ITEM_BUSINESS_UNITS[line["interim_product_code"]], "CNY" if currency == "CNH" else currency,
             currency, amount, line["target_month"], line["target_month"], amount_usd, plan_rate,
             float(rates.get("USD") or 0), plan_rate, krw_amount,
             f"Promotion · {promotion['title']} · 예상수량 {quantity:g}" if quantity is not None else f"Promotion · {promotion['title']}",
             actor["id"], actor["id"], line["customer_id"], customer["display_name"], timestamp,
             actor["id"], timestamp, timestamp),
        )
        apply_monthly_sale_context(db, sale_id, context, source_type="promotion", promotion_line_id=line["id"])
        add_history(db, sale_id, "PROMOTION_CREATE", "Promotion 매출계획에서 공식 FCST 생성", actor, now_fn)
        audit_fn(
            "PROMOTION_MONTHLY_FCST_CREATE", "monthly_sale", sale_id,
            f"{promotion['title']} Promotion → Monthly Sales FCST 생성", None, sale_snapshot(db, sale_id), connection=db,
        )
    db.execute(
        "UPDATE promotion_sales_lines SET monthly_sale_id=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?",
        (sale_id, actor["id"], timestamp, line["id"]),
    )
    return sale_snapshot(db, sale_id)


def _upsert_promotion_sales_lines(db, promotion, lines, actor, now_fn, audit_fn, country_catalog):
    results = []
    for raw in lines or []:
        customer_id = _clean(raw.get("customer_id"), 80, True, "Promotion Customer")
        item_code = validate_item_code(raw.get("interim_product_code"))
        target_month = _month(raw.get("target_month"))
        if not db.execute(
            "SELECT 1 FROM promotion_customer_links WHERE promotion_id=? AND customer_id=? AND deleted_at IS NULL",
            (promotion["id"], customer_id),
        ).fetchone():
            raise ValueError("Promotion Sales Line Customer는 Promotion 적용 Customer에 포함되어야 합니다.")
        if not db.execute(
            "SELECT 1 FROM promotion_items WHERE promotion_id=? AND interim_product_code=? AND deleted_at IS NULL",
            (promotion["id"], item_code),
        ).fetchone():
            raise ValueError("Promotion Sales Line Item은 Promotion 적용 Item에 포함되어야 합니다.")
        amount = _number(raw.get("expected_amount"), "예상 매출금액", 0, True)
        quantity = _number(raw.get("expected_quantity"), "예상 수량", 0, True)
        currency = _clean(raw.get("currency"), 8) or None
        existing = db.execute(
            """SELECT * FROM promotion_sales_lines WHERE promotion_id=? AND customer_id=?
               AND interim_product_code=? AND target_month=? AND deleted_at IS NULL""",
            (promotion["id"], customer_id, item_code, target_month),
        ).fetchone()
        timestamp = now_fn()
        if existing:
            if raw.get("version") not in (None, ""):
                _assert_version(raw, existing, "Promotion 매출계획")
            line_id = existing["id"]
            db.execute(
                """UPDATE promotion_sales_lines SET expected_quantity=?,expected_amount=?,currency=?,
                   updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
                (quantity, amount, currency, actor["id"], timestamp, line_id),
            )
        else:
            line_id = _uuid()
            db.execute(
                """INSERT INTO promotion_sales_lines
                   (id,promotion_id,customer_id,interim_product_code,target_month,expected_quantity,
                    expected_amount,currency,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (line_id, promotion["id"], customer_id, item_code, target_month, quantity, amount,
                 currency, actor["id"], actor["id"], timestamp, timestamp),
            )
        line_row = db.execute("SELECT * FROM promotion_sales_lines WHERE id=?", (line_id,)).fetchone()
        results.append(_sync_promotion_sale(db, promotion, line_row, actor, now_fn, audit_fn, country_catalog))
    return results


def _save_promotion(db, data, actor, now_fn, audit_fn, country_catalog, promotion_id=None):
    existing_record = db.execute(
        "SELECT * FROM records WHERE id=? AND entity_type='promotion' AND deleted_at IS NULL", (promotion_id,)
    ).fetchone() if promotion_id else None
    if promotion_id and not existing_record:
        raise ValueError("수정할 Promotion을 찾을 수 없습니다.")
    title = _clean(data.get("title", existing_record["title"] if existing_record else ""), 300, True, "Promotion명")
    start = _date(data.get("start_date"), "Promotion 시작일", True)
    end = _date(data.get("end_date"), "Promotion 종료일", True)
    if start > end:
        raise ValueError("Promotion 시작일은 종료일보다 늦을 수 없습니다.")
    status = _clean(data.get("status_code"), 20) or "draft"
    if status not in PROMOTION_STATUSES:
        raise ValueError("Promotion 상태를 목록에서 선택하세요.")
    customers = list(dict.fromkeys(data.get("customer_ids") or []))
    if not customers:
        raise ValueError("Promotion 적용 Customer를 하나 이상 선택하세요.")
    items = data.get("items") or []
    item_codes = [validate_item_code(item.get("interim_product_code")) for item in items]
    for customer_id in customers:
        _assert_customer_portfolio(db, customer_id, item_codes, "Promotion")
    timestamp = now_fn()
    owner_id = data.get("owner_id") or (existing_record["owner_id"] if existing_record else actor["id"])
    if not db.execute("SELECT 1 FROM users WHERE id=? AND status='active' AND deleted_at IS NULL", (owner_id,)).fetchone():
        raise ValueError("Promotion 담당자는 활성 사용자에서 선택하세요.")
    if existing_record:
        terms = db.execute("SELECT * FROM promotion_commercial_terms WHERE promotion_id=?", (promotion_id,)).fetchone()
        if terms and data.get("version") not in (None, ""):
            _assert_version(data, terms, "Promotion")
        before = _promotion_payload(db, promotion_id) if terms else _row(existing_record)
        db.execute(
            "UPDATE records SET title=?,owner_id=?,status=?,updated_by=?,updated_at=? WHERE id=?",
            (title, owner_id, status, actor["id"], timestamp, promotion_id),
        )
        if terms:
            db.execute(
                """UPDATE promotion_commercial_terms SET start_date=?,end_date=?,status_code=?,notes=?,
                   updated_by=?,updated_at=?,version=version+1 WHERE promotion_id=?""",
                (start, end, status, _clean(data.get("notes"), 2000), actor["id"], timestamp, promotion_id),
            )
        else:
            db.execute(
                """INSERT INTO promotion_commercial_terms
                   (promotion_id,start_date,end_date,status_code,notes,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (promotion_id, start, end, status, _clean(data.get("notes"), 2000), actor["id"], actor["id"], timestamp, timestamp),
            )
    else:
        promotion_id = _uuid()
        payload = {"promotion_id": _clean(data.get("promotion_code"), 80) or promotion_id, "commercial_context_v2": True}
        db.execute(
            """INSERT INTO records
               (id,entity_type,title,owner_id,status,amount,currency,payload_json,created_by,updated_by,created_at,updated_at)
               VALUES (?,'promotion',?,?,?,0,'USD',?,?,?,?,?)""",
            (promotion_id, title, owner_id, status, _json(payload), actor["id"], actor["id"], timestamp, timestamp),
        )
        db.execute(
            """INSERT INTO promotion_commercial_terms
               (promotion_id,start_date,end_date,status_code,notes,created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (promotion_id, start, end, status, _clean(data.get("notes"), 2000), actor["id"], actor["id"], timestamp, timestamp),
        )
        before = None
    _replace_promotion_customers(db, promotion_id, customers, actor["id"], timestamp)
    _replace_promotion_items(db, promotion_id, items, actor["id"], timestamp)
    promotion = _promotion_payload(db, promotion_id)
    sales = _upsert_promotion_sales_lines(
        db, promotion, data.get("sales_lines"), actor, now_fn, audit_fn, country_catalog,
    )
    after = _promotion_payload(db, promotion_id)
    action = "PROMOTION_COMMERCIAL_UPDATE" if before else "PROMOTION_COMMERCIAL_CREATE"
    audit_fn(action, "promotion", promotion_id, f"{title} 구조화 Promotion {'수정' if before else '등록'}", before, after, connection=db)
    return after, sales


def register_commercial_context(app, get_db, role_required, csrf_required, audit_fn, now_fn, country_catalog=None):
    def fail(exc):
        status = 409 if isinstance(exc, RuntimeError) or "이미" in str(exc) or "2개 이상" in str(exc) else 400
        payload = {"error": str(exc)}
        if getattr(exc, "code", None):
            payload["code"] = exc.code
        return jsonify(payload), status

    def transact(work):
        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            result = work(db)
            db.commit()
            return result
        except (ValueError, RuntimeError, sqlite3.Error) as exc:
            db.rollback()
            return fail(exc)

    @app.get("/api/commercial-context/taxonomy")
    @role_required(*READ_ROLES)
    def commercial_context_taxonomy():
        payload = taxonomy_payload()
        payload["countries"] = [
            {"code": code, "name": item.get("name") or code, "label": item.get("label") or item.get("name") or code}
            for code, item in sorted((country_catalog or {}).items(), key=lambda row: (row[1].get("name") or "").casefold())
        ]
        return jsonify(payload)

    @app.get("/api/customer-master/<customer_id>/commercial-context")
    @role_required(*READ_ROLES)
    def get_customer_commercial_context(customer_id):
        db = get_db()
        try:
            bundle = customer_commercial_bundle(db, customer_id, country_catalog)
            db.commit()  # persists only generated provider-backed holiday cache rows
            return jsonify(commercial_context=bundle)
        except (ValueError, sqlite3.Error) as exc:
            db.rollback()
            return fail(exc)

    @app.put("/api/customer-master/<customer_id>/commercial-profile")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_customer_commercial_profile(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            customer = _ensure_customer(db, customer_id)
            expected = data.get("expected_version")
            if expected not in (None, "") and int(expected) != int(customer["version"]):
                exc = RuntimeError("다른 사용자가 먼저 거래처를 수정했습니다. 최신 내용을 다시 불러오세요.")
                exc.code = "CUSTOMER_VERSION_CONFLICT"
                raise exc
            before = customer_commercial_bundle(db, customer_id, country_catalog)
            policy = validate_contract_policy(data.get("contract_policy"), allow_none=True)
            timestamp = now_fn()
            db.execute(
                """UPDATE customer_master SET contract_policy=?,contract_policy_reviewed_by=?,
                   contract_policy_reviewed_at=?,updated_by=?,updated_at=?,version=version+1
                   WHERE id=?""",
                (policy, g.current_user["id"] if policy else None, timestamp if policy else None,
                 g.current_user["id"], timestamp, customer_id),
            )
            replace_customer_items(db, customer_id, data.get("item_codes") or [], g.current_user["id"], timestamp)
            after = customer_commercial_bundle(db, customer_id, country_catalog)
            audit_fn("CUSTOMER_COMMERCIAL_PROFILE_UPDATE", "customer_master", customer_id,
                     f"{customer['display_name']} 계약정책·취급 Item 수정", before, after, connection=db)
            return jsonify(message="계약정책과 취급 Item을 저장했습니다.", commercial_context=after)

        return transact(work)

    @app.post("/api/customer-master/<customer_id>/commercial-contracts")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def create_commercial_contract(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            contract = _save_contract(db, customer_id, data, g.current_user["id"], country_catalog)
            audit_fn("CONTRACT_CREATE", "customer_contract", contract["id"],
                     f"{contract.get('contract_no') or contract['id']} 계약 등록", None, contract, connection=db)
            return jsonify(message="Contract를 등록했습니다.", contract=contract), 201

        return transact(work)

    @app.patch("/api/customer-master/<customer_id>/commercial-contracts/<contract_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_commercial_contract(customer_id, contract_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            before_row = db.execute("SELECT * FROM customer_contracts WHERE id=?", (contract_id,)).fetchone()
            before = _contract_payload(db, before_row) if before_row else None
            contract = _save_contract(db, customer_id, data, g.current_user["id"], country_catalog, contract_id)
            action = "CONTRACT_EXTEND" if contract.get("commercial_status_code") == "extended" and (before or {}).get("commercial_status_code") != "extended" else (
                "CONTRACT_EXPIRE" if contract.get("commercial_status_code") == "expired" and (before or {}).get("commercial_status_code") != "expired" else "CONTRACT_UPDATE"
            )
            audit_fn(action, "customer_contract", contract_id,
                     f"{contract.get('contract_no') or contract_id} 계약 수정", before, contract, connection=db)
            return jsonify(message="Contract를 저장했습니다.", contract=contract)

        return transact(work)

    @app.post("/api/customer-master/<customer_id>/default-commercial-terms")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def create_default_commercial_term(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            term = _save_default_term(db, customer_id, data, g.current_user["id"])
            audit_fn("CUSTOMER_DEFAULT_TERM_CREATE", "customer_product_term", term["id"],
                     f"{term['item_label']} 기본 가격조건 등록", None, term, connection=db)
            return jsonify(message="기본 가격조건을 등록했습니다.", term=term), 201

        return transact(work)

    @app.patch("/api/customer-master/<customer_id>/default-commercial-terms/<term_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_default_commercial_term(customer_id, term_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            before = _row(db.execute("SELECT * FROM customer_product_terms WHERE id=?", (term_id,)).fetchone())
            term = _save_default_term(db, customer_id, data, g.current_user["id"], term_id)
            audit_fn("CUSTOMER_DEFAULT_TERM_UPDATE", "customer_product_term", term_id,
                     f"{term['item_label']} 기본 가격조건 수정", before, term, connection=db)
            return jsonify(message="기본 가격조건을 저장했습니다.", term=term)

        return transact(work)

    @app.put("/api/customer-master/<customer_id>/default-payment")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_default_payment(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            row_id = _upsert_payment(db, customer_id, None, data, g.current_user["id"], now_fn())
            result = _row(db.execute("SELECT * FROM customer_payment_terms WHERE id=?", (row_id,)).fetchone())
            audit_fn("CUSTOMER_DEFAULT_PAYMENT_UPDATE", "customer_payment_term", row_id,
                     "Customer Default Payment·Incoterms 저장", None, result, connection=db)
            return jsonify(message="기본 Payment·Incoterms를 저장했습니다.", payment=result)

        return transact(work)

    @app.post("/api/commercial-context/resolve")
    @role_required(*READ_ROLES)
    def resolve_commercial_context_api():
        data = request.get_json(silent=True) or {}
        db = get_db()
        try:
            context = resolve_customer_order_context(
                db, _clean(data.get("customer_id"), 80, True, "Customer"),
                data.get("interim_product_code"), data.get("order_date"),
                promotion_id=data.get("promotion_id"), country_catalog=country_catalog,
            )
            db.commit()
            return jsonify(context=context)
        except (ValueError, sqlite3.Error) as exc:
            db.rollback()
            return fail(exc)

    @app.post("/api/customer-master/<customer_id>/logistics-addresses")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def create_logistics_address(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            item = _save_address(db, customer_id, data, g.current_user["id"])
            audit_fn("CUSTOMER_ADDRESS_CREATE", "customer_logistics_address", item["id"],
                     f"{ADDRESS_ROLES[item['address_role']]} 주소 등록", None, item, connection=db)
            return jsonify(message="주소를 등록했습니다.", item=item), 201

        return transact(work)

    @app.patch("/api/customer-master/<customer_id>/logistics-addresses/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_logistics_address(customer_id, row_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            before = _row(db.execute("SELECT * FROM customer_logistics_addresses WHERE id=?", (row_id,)).fetchone())
            item = _save_address(db, customer_id, data, g.current_user["id"], row_id)
            audit_fn("CUSTOMER_ADDRESS_UPDATE", "customer_logistics_address", row_id,
                     f"{ADDRESS_ROLES[item['address_role']]} 주소 수정", before, item, connection=db)
            return jsonify(message="주소를 저장했습니다.", item=item)

        return transact(work)

    @app.post("/api/customer-master/<customer_id>/logistics-providers")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def create_logistics_provider(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            item = _save_provider(db, customer_id, data, g.current_user["id"])
            audit_fn("CUSTOMER_PROVIDER_CREATE", "customer_logistics_provider", item["id"],
                     f"{item['company_name']} Provider 연결", None, item, connection=db)
            return jsonify(message="물류 Provider를 연결했습니다.", item=item), 201

        return transact(work)

    @app.patch("/api/customer-master/<customer_id>/logistics-providers/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_logistics_provider(customer_id, row_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            before = _row(db.execute("SELECT * FROM customer_logistics_providers WHERE id=?", (row_id,)).fetchone())
            item = _save_provider(db, customer_id, data, g.current_user["id"], row_id)
            audit_fn("CUSTOMER_PROVIDER_UPDATE", "customer_logistics_provider", row_id,
                     f"{item['company_name']} Provider 수정", before, item, connection=db)
            return jsonify(message="물류 Provider를 저장했습니다.", item=item)

        return transact(work)

    @app.get("/api/commercial-context/logistics-providers")
    @role_required(*READ_ROLES)
    def search_logistics_providers():
        query = _clean(request.args.get("q"), 100).casefold()
        provider_type = _clean(request.args.get("type"), 30)
        rows = get_db().execute(
            "SELECT * FROM logistics_providers WHERE deleted_at IS NULL AND active=1 ORDER BY company_name COLLATE NOCASE"
        ).fetchall()
        items = [_row(row) for row in rows if (not query or query in row["company_name"].casefold()) and (not provider_type or row["provider_type"] == provider_type)]
        return jsonify(items=items[:50])

    @app.post("/api/customer-master/<customer_id>/document-requirements")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def create_document_requirement(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            item = _save_document(db, customer_id, data, g.current_user["id"])
            audit_fn("DOCUMENT_REQUIREMENT_CREATE", "customer_document_requirement", item["id"],
                     f"{DOCUMENT_CATALOG.get(item['document_code'], item['document_code'])} 요구조건 등록", None, item, connection=db)
            return jsonify(message="무역서류 요구조건을 등록했습니다.", item=item), 201

        return transact(work)

    @app.patch("/api/customer-master/<customer_id>/document-requirements/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_document_requirement(customer_id, row_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            before = _row(db.execute("SELECT * FROM customer_document_requirements WHERE id=?", (row_id,)).fetchone())
            item = _save_document(db, customer_id, data, g.current_user["id"], row_id)
            audit_fn("DOCUMENT_REQUIREMENT_UPDATE", "customer_document_requirement", row_id,
                     f"{DOCUMENT_CATALOG.get(item['document_code'], item['document_code'])} 요구조건 수정", before, item, connection=db)
            return jsonify(message="무역서류 요구조건을 저장했습니다.", item=item)

        return transact(work)

    @app.post("/api/customer-master/<customer_id>/closures")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def create_customer_closure(customer_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            item = _save_closure(db, customer_id, data, g.current_user["id"])
            audit_fn("CUSTOMER_CLOSURE_CREATE", "customer_closure", item["id"],
                     f"{item['title']} 거래처 휴무 등록", None, item, connection=db)
            return jsonify(message="거래처 휴무를 등록했습니다.", item=item), 201

        return transact(work)

    @app.patch("/api/customer-master/<customer_id>/closures/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_customer_closure(customer_id, row_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            before = _row(db.execute("SELECT * FROM customer_closures WHERE id=?", (row_id,)).fetchone())
            item = _save_closure(db, customer_id, data, g.current_user["id"], row_id)
            audit_fn("CUSTOMER_CLOSURE_UPDATE", "customer_closure", row_id,
                     f"{item['title']} 거래처 휴무 수정", before, item, connection=db)
            return jsonify(message="거래처 휴무를 저장했습니다.", item=item)

        return transact(work)

    @app.delete("/api/customer-master/<customer_id>/commercial-resources/<resource>/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def deactivate_commercial_resource(customer_id, resource, row_id):
        definitions = {
            "address": ("customer_logistics_addresses", "CUSTOMER_ADDRESS_DEACTIVATE"),
            "provider": ("customer_logistics_providers", "CUSTOMER_PROVIDER_DEACTIVATE"),
            "document": ("customer_document_requirements", "DOCUMENT_REQUIREMENT_DEACTIVATE"),
            "closure": ("customer_closures", "CUSTOMER_CLOSURE_DEACTIVATE"),
            "default-term": ("customer_product_terms", "CUSTOMER_DEFAULT_TERM_DEACTIVATE"),
        }
        if resource not in definitions:
            return jsonify(error="종료할 Commercial Resource 유형이 올바르지 않습니다."), 400
        table, action = definitions[resource]
        data = request.get_json(silent=True) or {}

        def work(db):
            row = db.execute(f"SELECT * FROM {table} WHERE id=? AND customer_id=? AND deleted_at IS NULL", (row_id, customer_id)).fetchone()
            if not row:
                raise ValueError("종료할 정보를 찾을 수 없습니다.")
            if "version" in row.keys():
                _assert_version(data, row, "Commercial Resource")
            timestamp = now_fn()
            db.execute(f"UPDATE {table} SET deleted_at=?,updated_by=?,updated_at=? WHERE id=?", (timestamp, g.current_user["id"], timestamp, row_id))
            audit_fn(action, resource, row_id, f"{resource} 사용종료", _row(row), None, connection=db)
            return jsonify(message="사용종료했습니다. 이력은 보존됩니다.")

        return transact(work)

    @app.get("/api/commercial-context/promotions")
    @role_required(*READ_ROLES)
    def list_commercial_promotions():
        db = get_db()
        customer_id = _clean(request.args.get("customer_id"), 80)
        item_code = _clean(request.args.get("interim_product_code"), 80)
        order_date = _clean(request.args.get("order_date"), 10)
        sql = """SELECT DISTINCT r.id FROM records r
                 JOIN promotion_commercial_terms t ON t.promotion_id=r.id
                 LEFT JOIN promotion_customer_links c ON c.promotion_id=r.id AND c.deleted_at IS NULL
                 LEFT JOIN promotion_items i ON i.promotion_id=r.id AND i.deleted_at IS NULL
                 WHERE r.entity_type='promotion' AND r.deleted_at IS NULL"""
        params = []
        if customer_id:
            sql += " AND c.customer_id=?"; params.append(customer_id)
        if item_code:
            sql += " AND i.interim_product_code=?"; params.append(item_code)
        if order_date:
            sql += " AND t.start_date<=? AND t.end_date>=? AND t.status_code='active'"; params.extend([order_date, order_date])
        sql += " ORDER BY r.title COLLATE NOCASE"
        items = [_promotion_payload(db, row["id"]) for row in db.execute(sql, params).fetchall()]
        return jsonify(items=items)

    @app.post("/api/commercial-context/promotions")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def create_commercial_promotion():
        data = request.get_json(silent=True) or {}

        def work(db):
            promotion, sales = _save_promotion(db, data, g.current_user, now_fn, audit_fn, country_catalog)
            return jsonify(message="Promotion과 공식 Monthly FCST 연결을 저장했습니다.", promotion=promotion, monthly_sales=sales), 201

        return transact(work)

    @app.patch("/api/commercial-context/promotions/<promotion_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def update_commercial_promotion(promotion_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            promotion, sales = _save_promotion(db, data, g.current_user, now_fn, audit_fn, country_catalog, promotion_id)
            return jsonify(message="Promotion과 연결 FCST를 동기화했습니다.", promotion=promotion, monthly_sales=sales)

        return transact(work)

    @app.post("/api/commercial-context/promotions/<promotion_id>/sales-lines")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def sync_commercial_promotion_sales(promotion_id):
        data = request.get_json(silent=True) or {}

        def work(db):
            promotion = _promotion_payload(db, promotion_id)
            if not promotion:
                raise ValueError("구조화 Promotion을 찾을 수 없습니다.")
            sales = _upsert_promotion_sales_lines(db, promotion, data.get("sales_lines") or [], g.current_user, now_fn, audit_fn, country_catalog)
            audit_fn("PROMOTION_MONTHLY_FCST_SYNC", "promotion", promotion_id,
                     f"{promotion['title']} 공식 Monthly FCST 동기화", None,
                     {"sale_ids": [sale["id"] for sale in sales]}, connection=db)
            return jsonify(message="Promotion 매출계획을 공식 Monthly FCST에 반영했습니다.", monthly_sales=sales)

        return transact(work)
