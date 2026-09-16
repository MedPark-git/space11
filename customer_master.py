"""Relational customer master built on the application's existing SQLite ledger.

The module deliberately consumes the already-synchronised ``shipments`` table.
It never calls or writes back to Amaranth ERP, and it keeps ERP-owned fields
separate from fields maintained by Global MAPS users.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import available_timezones

from flask import g, jsonify, request

from customer_policy_schema import apply_customer_policy_schema
from maps_taxonomy import (
    ADDITIONAL_DOCUMENTS,
    COURIERS,
    CONTACT_EMPLOYMENT_STATUSES,
    CONTRACT_EXCLUSIVITIES,
    CONTRACT_STATUSES,
    CUSTOMER_BUSINESS_AREA_DETAILS,
    CUSTOMER_STAGES,
    INTERIM_CONTRACT_PRODUCTS,
    LANGUAGES,
    MASTER_MATURITIES,
    MEETING_ACTION_STATUSES,
    MEETING_IMPORTANCE,
    ORGANIZATION_ROLES,
    PARENT_BUSINESS_AREAS,
    PAYMENT_METHODS,
    PAYMENT_TRIGGERS,
    business_parent,
    legacy_role_candidates,
    taxonomy_payload,
)


READ_ROLES = ("admin", "manager", "editor", "viewer")
WRITE_ROLES = ("admin", "manager", "editor")
MANAGE_ROLES = {"admin", "manager"}
ACTIVE_STATUSES = {"active"}
LIFECYCLE_STATUSES = {"active", "paused", "dormant", "contract_ended", "ended"}
RELATIONSHIP_TYPES = {"dealer", "odm", "dealer_odm"}
SOURCE_TYPES = {"erp", "manual", "temporary", "legacy"}
BUSINESS_UNITS = set(PARENT_BUSINESS_AREAS)
SELECTABLE_BUSINESS_DETAILS = {
    code for code, definition in CUSTOMER_BUSINESS_AREA_DETAILS.items()
    if definition.get("selectable")
}
IANA_TIMEZONES = frozenset(available_timezones())
CUSTOMER_MASTER_MIGRATION_KEY = "customer-master-relational-migration:2026-09-05-v1"
CONTRACT_CURRENCIES = {"USD", "EUR", "JPY", "CNH", "KRW"}


class FieldValidationError(ValueError):
    """Validation error that lets the UI keep the message beside one field."""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def _validation_error(exc):
    payload = {"error": str(exc)}
    if getattr(exc, "field", None):
        payload["field"] = exc.field
    return jsonify(**payload), 400


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _mutation_now():
    """High-resolution token for optimistic child-row updates."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _payload(value):
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _row(row):
    return dict(row) if row is not None else None


def _uuid():
    return str(uuid.uuid4())


def _stable_uuid(namespace, source_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"medpark-global-maps:{namespace}:{source_id}"))


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _number(value, default=0.0):
    try:
        number = float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        raise ValueError("숫자 형식이 올바르지 않습니다.")
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("숫자 형식이 올바르지 않습니다.")
    return number


def _iso_date(value, label="날짜"):
    value = _clean(value, 10)
    if value:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{label}는 YYYY-MM-DD 형식으로 입력하세요.") from exc
    return value or None


def _legacy_iso_date(value):
    """Keep a malformed legacy date out of typed columns without aborting migration."""
    value = _clean(value, 20)
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _valid_erp_code(value):
    value = _clean(value, 80)
    return value if re.fullmatch(r"[0-9]+", value) else ""


def _name_key(value):
    return re.sub(r"[^0-9a-z가-힣]+", "", _clean(value, 300).casefold())


def _similar_name(left, right):
    left_key, right_key = _name_key(left), _name_key(right)
    if not left_key or not right_key or left_key == right_key:
        return bool(left_key and left_key == right_key)
    if min(len(left_key), len(right_key)) >= 7 and (
        left_key in right_key or right_key in left_key
    ):
        return True
    return difflib.SequenceMatcher(None, left_key, right_key).ratio() >= 0.88


def init_customer_master_schema(db):
    """Create additive relational tables only; never replace the current DB."""
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS customer_master (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL UNIQUE,
          erp_partner_code TEXT UNIQUE,
          erp_original_name TEXT NOT NULL DEFAULT '',
          erp_country_code TEXT,
          erp_country_name TEXT NOT NULL DEFAULT '',
          display_name TEXT NOT NULL,
          legal_name_en TEXT NOT NULL DEFAULT '',
          headquarters_country TEXT NOT NULL DEFAULT '',
          country_code TEXT,
          sales_region TEXT NOT NULL DEFAULT '미분류',
          source_type TEXT NOT NULL CHECK(source_type IN ('erp','manual','temporary','legacy')),
          relationship_type TEXT NOT NULL DEFAULT 'dealer'
            CHECK(relationship_type IN ('dealer','odm','dealer_odm')),
          customer_role TEXT NOT NULL DEFAULT 'Distributor',
          primary_owner_id INTEGER,
          secondary_owner_id INTEGER,
          lifecycle_status TEXT NOT NULL DEFAULT 'active'
            CHECK(lifecycle_status IN ('active','paused','dormant','contract_ended','ended')),
          default_currency TEXT NOT NULL DEFAULT 'USD',
          preferred_language TEXT NOT NULL DEFAULT '',
          timezone_name TEXT NOT NULL DEFAULT '',
          website TEXT NOT NULL DEFAULT '',
          address TEXT NOT NULL DEFAULT '',
          first_transaction_date TEXT,
          last_information_reviewed_at TEXT,
          data_steward_id INTEGER,
          notes TEXT NOT NULL DEFAULT '',
          duplicate_review_status TEXT NOT NULL DEFAULT 'clear'
            CHECK(duplicate_review_status IN ('clear','review_required','resolved')),
          inactive_date TEXT,
          inactive_reason TEXT NOT NULL DEFAULT '',
          restart_probability TEXT NOT NULL DEFAULT '',
          review_date TEXT,
          restored_at TEXT,
          restore_reason TEXT NOT NULL DEFAULT '',
          erp_last_seen_at TEXT,
          source_record_id TEXT UNIQUE,
          version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER,
          updated_by INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(primary_owner_id) REFERENCES users(id),
          FOREIGN KEY(secondary_owner_id) REFERENCES users(id),
          FOREIGN KEY(data_steward_id) REFERENCES users(id),
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_customer_master_region
          ON customer_master(sales_region, lifecycle_status);
        CREATE INDEX IF NOT EXISTS idx_customer_master_country
          ON customer_master(country_code, lifecycle_status);
        CREATE INDEX IF NOT EXISTS idx_customer_master_owner
          ON customer_master(primary_owner_id, secondary_owner_id);

        CREATE TABLE IF NOT EXISTS customer_business_areas (
          customer_id TEXT NOT NULL,
          business_unit TEXT NOT NULL CHECK(business_unit IN ('medical','dental','aesthetic')),
          created_at TEXT NOT NULL,
          PRIMARY KEY(customer_id, business_unit),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_sales_countries (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          country_code TEXT NOT NULL,
          country_name TEXT NOT NULL,
          sales_region TEXT NOT NULL DEFAULT '미분류',
          is_primary INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          UNIQUE(customer_id, country_code),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_contacts (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          contact_name TEXT NOT NULL,
          department_title TEXT NOT NULL DEFAULT '',
          responsibility TEXT NOT NULL DEFAULT '',
          is_decision_maker INTEGER NOT NULL DEFAULT 0,
          is_primary_contact INTEGER NOT NULL DEFAULT 0,
          email TEXT NOT NULL DEFAULT '',
          phone TEXT NOT NULL DEFAULT '',
          messenger TEXT NOT NULL DEFAULT '',
          language TEXT NOT NULL DEFAULT '',
          employment_status TEXT NOT NULL DEFAULT 'active',
          notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_contracts (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          contract_no TEXT NOT NULL DEFAULT '',
          contract_type TEXT NOT NULL DEFAULT '',
          exclusivity TEXT NOT NULL DEFAULT '',
          contract_status TEXT NOT NULL DEFAULT 'draft',
          start_date TEXT, end_date TEXT,
          auto_renew INTEGER NOT NULL DEFAULT 0,
          notice_deadline TEXT,
          territory TEXT NOT NULL DEFAULT '',
          products_scope TEXT NOT NULL DEFAULT '',
          currency TEXT NOT NULL DEFAULT 'USD',
          contract_amount REAL NOT NULL DEFAULT 0,
          annual_min_amount REAL NOT NULL DEFAULT 0,
          annual_min_quantity REAL NOT NULL DEFAULT 0,
          approval_user_name TEXT NOT NULL DEFAULT '', approval_date TEXT,
          renewal_date TEXT, notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_contracts_customer_end
          ON customer_contracts(customer_id, deleted_at, end_date);

        CREATE TABLE IF NOT EXISTS customer_payment_terms (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          payment_method TEXT NOT NULL DEFAULT '',
          advance_ratio REAL NOT NULL DEFAULT 0,
          deferred_ratio REAL NOT NULL DEFAULT 0,
          collection_basis TEXT NOT NULL DEFAULT 'shipment_date',
          deferred_days INTEGER NOT NULL DEFAULT 0,
          installments_json TEXT NOT NULL DEFAULT '[]',
          lc_terms TEXT NOT NULL DEFAULT '',
          currency TEXT NOT NULL DEFAULT 'USD',
          fee_bearer TEXT NOT NULL DEFAULT '',
          credit_limit REAL NOT NULL DEFAULT 0,
          hold_on_overdue INTEGER NOT NULL DEFAULT 0,
          approver_name TEXT NOT NULL DEFAULT '',
          evidence_path TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          effective_from TEXT, effective_to TEXT, is_current INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_payment_terms_current
          ON customer_payment_terms(customer_id, deleted_at, is_current, effective_from);

        CREATE TABLE IF NOT EXISTS customer_product_terms (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          product_name TEXT NOT NULL, specification TEXT NOT NULL DEFAULT '',
          internal_product_code TEXT NOT NULL DEFAULT '', customer_product_code TEXT NOT NULL DEFAULT '',
          price_type TEXT NOT NULL DEFAULT 'customer',
          base_unit_price REAL NOT NULL DEFAULT 0, agreed_unit_price REAL NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT 'USD', moq REAL NOT NULL DEFAULT 0,
          moq_basis TEXT NOT NULL CHECK(moq_basis IN ('paid','total_supply')),
          paid_quantity REAL NOT NULL DEFAULT 0, foc_quantity REAL NOT NULL DEFAULT 0,
          foc_condition TEXT NOT NULL DEFAULT '', foc_ratio REAL NOT NULL DEFAULT 0,
          effective_unit_price REAL NOT NULL DEFAULT 0,
          packaging_label TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          is_current INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_product_terms
          ON customer_product_terms(customer_id, product_name, is_current, deleted_at);

        CREATE TABLE IF NOT EXISTS customer_logistics (
          id TEXT PRIMARY KEY,
          customer_id TEXT NOT NULL,
          incoterms TEXT NOT NULL DEFAULT '', transport_mode TEXT NOT NULL DEFAULT '',
          forwarder TEXT NOT NULL DEFAULT '', courier_account TEXT NOT NULL DEFAULT '',
          origin_address TEXT NOT NULL DEFAULT '', destination_address TEXT NOT NULL DEFAULT '',
          consignee TEXT NOT NULL DEFAULT '', notify_party TEXT NOT NULL DEFAULT '',
          default_port TEXT NOT NULL DEFAULT '', required_documents TEXT NOT NULL DEFAULT '',
          coa_required INTEGER NOT NULL DEFAULT 0, coo_required INTEGER NOT NULL DEFAULT 0,
          fsc_required INTEGER NOT NULL DEFAULT 0, shipping_mark TEXT NOT NULL DEFAULT '',
          originals_required INTEGER NOT NULL DEFAULT 0, external_system TEXT NOT NULL DEFAULT '',
          insurance_bearer TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          source_transport_record_id TEXT UNIQUE,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_logistics_customer
          ON customer_logistics(customer_id, deleted_at);

        CREATE TABLE IF NOT EXISTS customer_registrations (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          country_code TEXT NOT NULL DEFAULT '', country_name TEXT NOT NULL DEFAULT '',
          product_name TEXT NOT NULL, specification TEXT NOT NULL DEFAULT '',
          registration_status TEXT NOT NULL DEFAULT '', registration_no TEXT NOT NULL DEFAULT '',
          holder_name TEXT NOT NULL DEFAULT '', application_date TEXT, approval_date TEXT,
          valid_from TEXT, valid_to TEXT, renewal_date TEXT,
          renewal_owner_id INTEGER, certificate_path TEXT NOT NULL DEFAULT '',
          label_languages TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_registrations_customer_expiry
          ON customer_registrations(customer_id, deleted_at, valid_to);

        CREATE TABLE IF NOT EXISTS customer_odm_projects (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          project_no TEXT NOT NULL UNIQUE, brand_name TEXT NOT NULL DEFAULT '',
          product_spec TEXT NOT NULL DEFAULT '', development_stage TEXT NOT NULL DEFAULT 'inquiry',
          expected_quantity REAL NOT NULL DEFAULT 0, moq REAL NOT NULL DEFAULT 0,
          target_unit_price REAL NOT NULL DEFAULT 0, sample_date TEXT, specification_confirmed_at TEXT,
          packaging_label TEXT NOT NULL DEFAULT '', regulatory_owner TEXT NOT NULL DEFAULT '',
          development_cost REAL NOT NULL DEFAULT 0, tooling_cost REAL NOT NULL DEFAULT 0,
          nda_signed INTEGER NOT NULL DEFAULT 0, quality_agreement INTEGER NOT NULL DEFAULT 0,
          expected_po_date TEXT, expected_launch_date TEXT,
          owner_id INTEGER, next_action_date TEXT, issue_notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_odm_projects_customer
          ON customer_odm_projects(customer_id, deleted_at);

        CREATE TABLE IF NOT EXISTS customer_odm_supply_countries (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
          country_code TEXT NOT NULL, country_name TEXT NOT NULL,
          supply_status TEXT NOT NULL DEFAULT 'planned', product_spec TEXT NOT NULL DEFAULT '',
          expected_start_date TEXT, actual_start_date TEXT,
          expected_quantity REAL NOT NULL DEFAULT 0, expected_sales REAL NOT NULL DEFAULT 0,
          registration_required INTEGER NOT NULL DEFAULT 0, registration_status TEXT NOT NULL DEFAULT '',
          owner_id INTEGER, notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          UNIQUE(project_id, country_code, product_spec),
          FOREIGN KEY(project_id) REFERENCES customer_odm_projects(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_odm_supply_project_country
          ON customer_odm_supply_countries(project_id, country_code, deleted_at);

        CREATE TABLE IF NOT EXISTS customer_sales_plans (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          plan_year INTEGER NOT NULL, business_unit TEXT NOT NULL DEFAULT '', product_group TEXT NOT NULL DEFAULT '',
          optimistic_amount REAL NOT NULL DEFAULT 0, neutral_amount REAL NOT NULL DEFAULT 0,
          conservative_amount REAL NOT NULL DEFAULT 0, applied_amount REAL NOT NULL DEFAULT 0,
          currency TEXT NOT NULL DEFAULT 'USD', override_next_order_date TEXT,
          override_reason TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          UNIQUE(customer_id, plan_year, business_unit, product_group),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_sales_plans_customer_year
          ON customer_sales_plans(customer_id, plan_year, deleted_at);

        CREATE TABLE IF NOT EXISTS customer_education_events (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          product_name TEXT NOT NULL DEFAULT '', event_date TEXT, attendees TEXT NOT NULL DEFAULT '',
          education_type TEXT NOT NULL DEFAULT '', trainer_name TEXT NOT NULL DEFAULT '',
          material_path TEXT NOT NULL DEFAULT '', followup_required INTEGER NOT NULL DEFAULT 0,
          next_event_date TEXT, notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_marketing_support (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          support_date TEXT, support_item TEXT NOT NULL DEFAULT '', quantity REAL NOT NULL DEFAULT 0,
          support_amount REAL NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'USD',
          shipping_info TEXT NOT NULL DEFAULT '', promotion_record_id TEXT, notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_competitors (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          product_category TEXT NOT NULL DEFAULT '', brand_name TEXT NOT NULL DEFAULT '',
          handles_implants INTEGER NOT NULL DEFAULT 0, main_products TEXT NOT NULL DEFAULT '',
          estimated_scale TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_meetings (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          meeting_date TEXT, attendees TEXT NOT NULL DEFAULT '', discussion TEXT NOT NULL DEFAULT '',
          decisions TEXT NOT NULL DEFAULT '', issue_text TEXT NOT NULL DEFAULT '',
          importance TEXT NOT NULL DEFAULT '', next_action TEXT NOT NULL DEFAULT '',
          owner_id INTEGER, due_date TEXT, action_status TEXT NOT NULL DEFAULT 'open', next_meeting_date TEXT,
          created_by INTEGER, updated_by INTEGER,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_customer_meetings_customer_date
          ON customer_meetings(customer_id, deleted_at, meeting_date);

        CREATE TABLE IF NOT EXISTS customer_attachments (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          linked_entity_type TEXT NOT NULL DEFAULT 'customer', linked_entity_id TEXT,
          file_type TEXT NOT NULL DEFAULT '', file_path TEXT NOT NULL,
          original_name TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
          checksum_sha256 TEXT NOT NULL DEFAULT '', created_by INTEGER, created_at TEXT NOT NULL,
          deleted_at TEXT,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_erp_metrics (
          customer_id TEXT PRIMARY KEY,
          shipment_count INTEGER NOT NULL DEFAULT 0,
          first_ship_date TEXT, last_ship_date TEXT,
          current_year_sales_krw REAL NOT NULL DEFAULT 0,
          previous_year_sales_krw REAL NOT NULL DEFAULT 0,
          cumulative_sales_krw REAL NOT NULL DEFAULT 0,
          average_order_cycle_days REAL,
          next_expected_order_date TEXT,
          last_product_name TEXT NOT NULL DEFAULT '', last_quantity REAL NOT NULL DEFAULT 0,
          calculated_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_sync_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at TEXT NOT NULL, finished_at TEXT,
          requested_by INTEGER, status TEXT NOT NULL,
          shipment_row_count INTEGER NOT NULL DEFAULT 0,
          overseas_partner_count INTEGER NOT NULL DEFAULT 0,
          created_count INTEGER NOT NULL DEFAULT 0, updated_count INTEGER NOT NULL DEFAULT 0,
          duplicate_review_count INTEGER NOT NULL DEFAULT 0,
          missing_code_count INTEGER NOT NULL DEFAULT 0,
          missing_country_count INTEGER NOT NULL DEFAULT 0,
          domestic_excluded_count INTEGER NOT NULL DEFAULT 0,
          domestic_excluded_partner_count INTEGER,
          error_count INTEGER NOT NULL DEFAULT 0, error_message TEXT,
          FOREIGN KEY(requested_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS customer_sync_review_items (
          id TEXT PRIMARY KEY, sync_run_id INTEGER,
          review_type TEXT NOT NULL,
          external_key TEXT NOT NULL,
          erp_partner_code TEXT, erp_partner_name TEXT NOT NULL DEFAULT '',
          candidate_customer_ids_json TEXT NOT NULL DEFAULT '[]',
          reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
          resolution_note TEXT NOT NULL DEFAULT '', resolved_by INTEGER, resolved_at TEXT,
          created_at TEXT NOT NULL,
          UNIQUE(review_type, external_key, status),
          FOREIGN KEY(sync_run_id) REFERENCES customer_sync_runs(id)
        );
        CREATE INDEX IF NOT EXISTS idx_customer_sync_review_open
          ON customer_sync_review_items(status, review_type, created_at);

        CREATE TABLE IF NOT EXISTS customer_erp_link_history (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          previous_erp_code TEXT, new_erp_code TEXT NOT NULL,
          comparison_json TEXT NOT NULL DEFAULT '{}', confirmed_by INTEGER,
          confirmed_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS customer_order_terms_snapshots (
          id TEXT PRIMARY KEY, order_record_id TEXT NOT NULL,
          customer_id TEXT NOT NULL, payment_terms_json TEXT NOT NULL,
          product_terms_json TEXT NOT NULL DEFAULT '[]', exception_reason TEXT NOT NULL DEFAULT '',
          moq_exception_reason TEXT NOT NULL DEFAULT '',
          moq_exception_approver TEXT NOT NULL DEFAULT '',
          created_by INTEGER, created_at TEXT NOT NULL,
          UNIQUE(order_record_id),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id)
        );
        """
    )
    sync_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(customer_sync_runs)").fetchall()
    }
    if "domestic_excluded_partner_count" not in sync_columns:
        db.execute(
            "ALTER TABLE customer_sync_runs ADD COLUMN domestic_excluded_partner_count INTEGER"
        )
    master_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(customer_master)").fetchall()
    }
    if "erp_country_code" not in master_columns:
        db.execute("ALTER TABLE customer_master ADD COLUMN erp_country_code TEXT")
    if "erp_country_name" not in master_columns:
        db.execute("ALTER TABLE customer_master ADD COLUMN erp_country_name TEXT NOT NULL DEFAULT ''")
    snapshot_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(customer_order_terms_snapshots)").fetchall()
    }
    if "moq_exception_reason" not in snapshot_columns:
        db.execute(
            "ALTER TABLE customer_order_terms_snapshots ADD COLUMN moq_exception_reason TEXT NOT NULL DEFAULT ''"
        )
    if "moq_exception_approver" not in snapshot_columns:
        db.execute(
            "ALTER TABLE customer_order_terms_snapshots ADD COLUMN moq_exception_approver TEXT NOT NULL DEFAULT ''"
        )
    apply_customer_policy_schema(db)
    db.execute("PRAGMA optimize")


def _system_audit(db, action, entity_type, entity_id, summary, before=None, after=None):
    db.execute(
        """
        INSERT INTO audit_logs
          (occurred_at, actor_user_id, actor_username, action, entity_type, entity_id,
           summary, before_json, after_json)
        VALUES (?, NULL, 'SYSTEM', ?, ?, ?, ?, ?, ?)
        """,
        (_now(), action, entity_type, entity_id, summary,
         _json(before) if before is not None else None,
         _json(after) if after is not None else None),
    )


def _next_temp_customer_id(db, relationship_type="dealer"):
    year = datetime.now(timezone.utc).year
    prefix = f"TEMP-ODM-{year}" if relationship_type == "odm" else f"TEMP-{year}"
    rows = db.execute(
        "SELECT customer_id FROM customer_master WHERE customer_id LIKE ?",
        (f"{prefix}-%",),
    ).fetchall()
    sequence = 1
    for row in rows:
        match = re.search(r"-(\d+)$", row["customer_id"])
        if match:
            sequence = max(sequence, int(match.group(1)) + 1)
    width = 3 if relationship_type == "odm" else 4
    return f"{prefix}-{sequence:0{width}d}"


def _status_from_legacy(status):
    return {
        "hold": "paused", "closed": "ended", "disabled": "ended",
    }.get(_clean(status, 40), "active")


def _insert_review(db, review_type, external_key, reason, *, sync_run_id=None,
                   erp_code="", erp_name="", candidates=None):
    existing = db.execute(
        "SELECT id FROM customer_sync_review_items WHERE review_type=? AND external_key=? AND status='open'",
        (review_type, external_key),
    ).fetchone()
    if existing:
        return existing["id"], False
    review_id = _uuid()
    db.execute(
        """
        INSERT INTO customer_sync_review_items
          (id, sync_run_id, review_type, external_key, erp_partner_code,
           erp_partner_name, candidate_customer_ids_json, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (review_id, sync_run_id, review_type, external_key, erp_code or None,
         erp_name, _json(candidates or []), reason, _now()),
    )
    return review_id, True


def migrate_legacy_customer_data(db, country_resolver=None):
    """Repeat-safe migration from generic account/transport records.

    Existing records remain untouched and act as the rollback/reference source.
    """
    init_customer_master_schema(db)
    now = _now()
    accounts = db.execute(
        "SELECT * FROM records WHERE entity_type='account' AND deleted_at IS NULL ORDER BY created_at, id"
    ).fetchall()
    code_owners = defaultdict(list)
    for account in accounts:
        code = _valid_erp_code(_payload(account["payload_json"]).get("erp_partner_code"))
        if code:
            code_owners[code].append(account["id"])

    inserted = 0
    for account in accounts:
        if db.execute("SELECT 1 FROM customer_master WHERE source_record_id=?", (account["id"],)).fetchone():
            continue
        payload = _payload(account["payload_json"])
        raw_code = _clean(payload.get("erp_partner_code"), 80)
        valid_code = _valid_erp_code(raw_code)
        code_is_unique = bool(valid_code and len(code_owners[valid_code]) == 1)
        relationship = "dealer"
        relation_text = _clean(payload.get("relationship_type") or payload.get("account_classification"), 120).casefold()
        if "odm" in relation_text and ("dealer" in relation_text or "딜러" in relation_text):
            relationship = "dealer_odm"
        elif "odm" in relation_text:
            relationship = "odm"
        customer_id = valid_code if code_is_unique else _next_temp_customer_id(db, relationship)
        master_id = _stable_uuid("legacy-account", account["id"])
        source_type = "legacy" if len(payload) > 5 else "manual"
        notes = _clean(payload.get("account_notes") or payload.get("description") or payload.get("work_history"), 4000)
        country = _clean(account["country"], 120)
        resolved = country_resolver(country) if country and country_resolver else None
        country_code = resolved.get("map_id") if resolved else None
        sales_region = _clean(account["region"], 80) or "미분류"
        duplicate_status = "review_required" if valid_code and not code_is_unique else "clear"
        db.execute(
            """
            INSERT INTO customer_master
              (id, customer_id, erp_partner_code, erp_original_name, display_name,
               headquarters_country, country_code, sales_region, source_type,
               relationship_type, primary_owner_id, lifecycle_status, default_currency,
               address, first_transaction_date, notes, duplicate_review_status,
               source_record_id, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (master_id, customer_id, valid_code if code_is_unique else None,
             _clean(payload.get("erp_partner_name") or account["title"], 300),
             _clean(account["title"], 300), country, country_code, sales_region,
             source_type, relationship, account["owner_id"], _status_from_legacy(account["status"]),
             _clean(account["currency"] or "USD", 8), _clean(payload.get("address"), 1000),
             _legacy_iso_date(payload.get("first_transaction_date")), notes,
             duplicate_status, account["id"], account["created_by"], account["updated_by"],
             account["created_at"] or now, account["updated_at"] or now),
        )
        business = _clean(payload.get("business_unit"), 40)
        if business in BUSINESS_UNITS:
            db.execute(
                "INSERT OR IGNORE INTO customer_business_areas(customer_id,business_unit,created_at) VALUES (?,?,?)",
                (master_id, business, now),
            )
        contact_name = _clean(payload.get("account_contact_name") or payload.get("contact_person"), 200)
        if contact_name:
            db.execute(
                """INSERT INTO customer_contacts
                   (id,customer_id,contact_name,is_primary_contact,email,phone,notes,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,1,?,?,?,?,?,?,?)""",
                (_stable_uuid("legacy-contact", account["id"]), master_id, contact_name,
                 _clean(payload.get("contact_email"), 300), _clean(payload.get("contact_phone"), 200),
                 "기존 거래처 자료에서 이관", account["created_by"], account["updated_by"], now, now),
            )
        if any(payload.get(key) not in (None, "", 0) for key in (
            "contract_type", "contract_status", "contract_start", "contract_end", "contract_amount"
        )):
            db.execute(
                """INSERT INTO customer_contracts
                   (id,customer_id,contract_type,contract_status,start_date,end_date,contract_amount,
                    notes,created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_stable_uuid("legacy-contract", account["id"]), master_id,
                 _clean(payload.get("contract_type"), 120), _clean(payload.get("contract_status"), 80) or "active",
                 _legacy_iso_date(payload.get("contract_start")),
                 _legacy_iso_date(payload.get("contract_end")),
                 _number(payload.get("contract_amount")), "기존 거래처 자료에서 이관",
                 account["created_by"], account["updated_by"], now, now),
            )
        ratios = []
        advance = _number(payload.get("ar_advance_ratio"))
        if advance:
            ratios.append({"label": "선불", "days": 0, "ratio": advance})
        for index in range(1, 5):
            ratio = _number(payload.get(f"ar_installment_{index}_ratio"))
            if ratio:
                ratios.append({"label": f"{index}차", "days": int(_number(payload.get(f"ar_installment_{index}_days"))), "ratio": ratio})
        if ratios or payload.get("ar_condition_label") or payload.get("ar_terms_notes"):
            db.execute(
                """INSERT INTO customer_payment_terms
                   (id,customer_id,payment_method,advance_ratio,deferred_ratio,installments_json,currency,notes,
                    created_by,updated_by,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_stable_uuid("legacy-payment", account["id"]), master_id,
                 _clean(payload.get("ar_condition_label"), 120), advance, max(0, 100 - advance),
                 _json(ratios), _clean(account["currency"] or "USD", 8),
                 _clean(payload.get("ar_terms_notes"), 2000), account["created_by"],
                 account["updated_by"], now, now),
            )
        if valid_code and not code_is_unique:
            _insert_review(
                db, "duplicate_legacy_code", valid_code,
                f"기존 거래처 {len(code_owners[valid_code])}곳에 같은 ERP 코드가 입력돼 자동 연결하지 않았습니다.",
                erp_code=valid_code, erp_name=account["title"],
                candidates=[_stable_uuid("legacy-account", source_id) for source_id in code_owners[valid_code]],
            )
        elif raw_code and not valid_code:
            _insert_review(
                db, "invalid_legacy_code", account["id"],
                f"기존 ERP 코드 값 '{raw_code}'은 정식 숫자 코드가 아니어서 임시 고객 ID를 발급했습니다.",
                erp_name=account["title"], candidates=[master_id],
            )
        _system_audit(db, "CUSTOMER_MIGRATE", "customer_master", master_id,
                      f"기존 거래처 '{account['title']}' 거래처 마스터 이관")
        inserted += 1

    source_to_customer = {
        row["source_record_id"]: row["id"]
        for row in db.execute("SELECT id,source_record_id FROM customer_master WHERE source_record_id IS NOT NULL")
    }
    transports = db.execute(
        "SELECT * FROM records WHERE entity_type='transport' AND deleted_at IS NULL ORDER BY created_at,id"
    ).fetchall()
    linked_transport = 0
    for transport in transports:
        if db.execute("SELECT 1 FROM customer_logistics WHERE source_transport_record_id=?", (transport["id"],)).fetchone():
            continue
        payload = _payload(transport["payload_json"])
        customer_id = source_to_customer.get(_clean(payload.get("account_id"), 100))
        if not customer_id:
            transport_name = _clean(payload.get("account_name") or transport["title"].removesuffix(" 운송정보"), 300)
            matches = db.execute(
                """SELECT id FROM customer_master
                   WHERE lower(display_name)=lower(?) AND lower(headquarters_country)=lower(?)""",
                (transport_name, _clean(transport["country"], 120)),
            ).fetchall()
            if len(matches) == 1:
                customer_id = matches[0]["id"]
        if not customer_id:
            _insert_review(
                db, "transport_unlinked", transport["id"],
                "기존 고객 ID·ERP 코드·고객명+국가의 정확한 일치가 없어 자동 연결하지 않았습니다.",
                erp_name=_clean(payload.get("account_name") or transport["title"], 300),
            )
            continue
        db.execute(
            """INSERT INTO customer_logistics
               (id,customer_id,incoterms,transport_mode,forwarder,courier_account,
                required_documents,shipping_mark,notes,source_transport_record_id,
                created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_stable_uuid("legacy-transport", transport["id"]), customer_id,
             _clean(payload.get("incoterms"), 80), _clean(payload.get("transport_mode"), 120),
             _clean(payload.get("forwarder") or payload.get("nominated_forwarder") or payload.get("medpark_forwarder"), 300),
             _clean(payload.get("courier_account"), 200), _clean(payload.get("document_requirements"), 2000),
             _clean(payload.get("label_requirements"), 1000), _clean(payload.get("description"), 3000),
             transport["id"], transport["created_by"], transport["updated_by"],
             transport["created_at"] or now, transport["updated_at"] or now),
        )
        linked_transport += 1
    if inserted or linked_transport:
        _system_audit(
            db, "CUSTOMER_MIGRATION", "customer_master", None,
            f"거래처 {inserted}건·운송정보 {linked_transport}건 안전 이관",
            after={"customers": inserted, "logistics": linked_transport},
        )
    db.execute(
        "INSERT OR IGNORE INTO one_time_actions(action_key,applied_at) VALUES (?,?)",
        (CUSTOMER_MASTER_MIGRATION_KEY, _now()),
    )
    db.commit()
    return {"customers": inserted, "logistics": linked_transport}


def _country_from_shipment(row, country_resolver=None):
    if row.get("country_name"):
        resolved = country_resolver(row["country_name"]) if country_resolver else None
        return (resolved or {}).get("map_id"), (resolved or {}).get("name", row["country_name"])
    raw = _payload(row.get("raw_json"))
    header = raw.get("header") if isinstance(raw.get("header"), dict) else {}
    candidates = [header.get("areaCd"), header.get("areaNm")]
    area_name = _clean(header.get("areaNm"), 120)
    if "_" in area_name:
        candidates.append(area_name.rsplit("_", 1)[-1])
    for candidate in candidates:
        resolved = country_resolver(candidate) if candidate and country_resolver else None
        if resolved:
            return resolved.get("map_id"), resolved.get("name")
    return None, ""


def _sales_region(country_code, fallback=""):
    code = _clean(country_code, 3).zfill(3) if country_code else ""
    if code == "840": return "미국"
    if code == "643": return "러시아"
    if code == "156": return "중국"
    if code in {"124", "484", "304", "666"}: return "북미(미국 제외)"
    if code in {"051", "031", "112", "268", "398", "417", "498", "762", "795", "860"}: return "CIS(러시아 제외)"
    if code in {"032", "044", "052", "068", "076", "084", "092", "136", "152", "170", "188", "192", "212", "214", "218", "222", "238", "254", "308", "312", "320", "328", "332", "340", "388", "474", "500", "558", "591", "600", "604", "630", "659", "660", "662", "670", "740", "780", "796", "858", "862"}: return "중남미·카리브"
    if code in {"048", "364", "368", "376", "400", "414", "422", "512", "634", "682", "760", "784", "792", "887"}: return "중동"
    if code in {"012", "024", "072", "120", "180", "231", "266", "288", "384", "404", "426", "434", "450", "454", "478", "480", "504", "508", "516", "562", "566", "646", "686", "710", "716", "729", "788", "800", "818", "834", "894"}: return "아프리카"
    if code in {"036", "090", "242", "554", "598"}: return "오세아니아"
    if code in {"040", "056", "100", "191", "196", "203", "208", "233", "246", "250", "276", "300", "348", "352", "372", "380", "428", "440", "442", "470", "528", "578", "616", "620", "642", "688", "703", "705", "724", "752", "756", "804", "807", "826"}: return "유럽"
    if code in {"004", "050", "096", "104", "116", "144", "158", "344", "356", "360", "392", "408", "410", "418", "446", "458", "462", "496", "524", "586", "608", "626", "702", "704", "764"}: return "아시아(중국 제외)"
    return fallback or "미분류"


def _can_edit(customer):
    # Customer Master is shared canonical reference data.  Keep viewers
    # read-only, but do not hide canonical maintenance behind a sales-owner
    # assignment that is absent for most migrated customers.  Management-only
    # actions (ERP sync/link and review resolution) retain their own guards.
    return g.current_user["role"] in WRITE_ROLES


def _json_list(value, label):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} 형식이 올바르지 않습니다.") from exc
    if not isinstance(value, list):
        raise ValueError(f"{label}은 목록 형식이어야 합니다.")
    return value


def _policy_relation_values(db, customer_id):
    parent_units = [
        row["business_unit"] for row in db.execute(
            "SELECT business_unit FROM customer_business_areas WHERE customer_id=? ORDER BY business_unit",
            (customer_id,),
        )
    ]
    medical_details = [
        row["detail_code"] for row in db.execute(
            "SELECT detail_code FROM customer_business_area_details WHERE customer_id=? ORDER BY detail_code",
            (customer_id,),
        )
    ]
    detail_codes = [unit for unit in parent_units if unit in {"dental", "aesthetic"}]
    detail_codes.extend(medical_details)
    if "medical" in parent_units and not medical_details:
        detail_codes.append("medical_unspecified")
    roles = [
        row["role_code"] for row in db.execute(
            "SELECT role_code FROM customer_organization_roles WHERE customer_id=? ORDER BY role_code",
            (customer_id,),
        )
    ]
    languages = [
        row["language_code"] for row in db.execute(
            "SELECT language_code FROM customer_languages WHERE customer_id=? ORDER BY is_primary DESC,language_code",
            (customer_id,),
        )
    ]
    return {
        "business_units": parent_units,
        "business_area_details": detail_codes,
        "organization_roles": roles,
        "language_codes": languages,
    }


def _contract_relation_values(db, contract_id, country_catalog=None):
    product_codes = [
        row["interim_product_code"] for row in db.execute(
            """SELECT interim_product_code FROM customer_contract_products
               WHERE contract_id=? AND deleted_at IS NULL
               ORDER BY interim_product_code""",
            (contract_id,),
        )
    ]
    country_codes = [
        row["country_code"] for row in db.execute(
            """SELECT country_code FROM customer_contract_countries
               WHERE contract_id=? AND deleted_at IS NULL
               ORDER BY country_code""",
            (contract_id,),
        )
    ]
    countries = []
    catalog = country_catalog or {}
    for code in country_codes:
        definition = catalog.get(code) or {}
        countries.append({
            "code": code,
            "name": definition.get("name", code),
            "label": definition.get("label", definition.get("name", code)),
        })
    return {
        "interim_product_codes": product_codes,
        "territory_country_codes": country_codes,
        "territory_countries": countries,
    }


def _decorate_contract(db, value, country_catalog=None):
    item = dict(value)
    item.update(_contract_relation_values(db, item["id"], country_catalog))
    return item


def _normalize_contract_relations(data, country_catalog=None):
    values = {}
    if "interim_product_codes" in data:
        products = {
            _clean(value, 80)
            for value in _json_list(data.get("interim_product_codes"), "계약 제품")
        }
        invalid = products - set(INTERIM_CONTRACT_PRODUCTS)
        if invalid:
            raise FieldValidationError("interim_product_codes", "계약 제품 목록에 없는 코드가 포함되어 있습니다.")
        values["interim_product_codes"] = sorted(products)
    if "territory_country_codes" in data:
        countries = {
            _clean(value, 8)
            for value in _json_list(data.get("territory_country_codes"), "계약 국가")
        }
        valid = set(country_catalog or {})
        if countries - valid:
            raise FieldValidationError("territory_country_codes", "계약 국가는 표준 국가목록에서 선택하세요.")
        values["territory_country_codes"] = sorted(countries)
    return values


def _replace_contract_relation_rows(db, contract_id, relation_values, actor_id, now):
    definitions = (
        ("interim_product_codes", "customer_contract_products", "interim_product_code"),
        ("territory_country_codes", "customer_contract_countries", "country_code"),
    )
    for input_key, table, code_column in definitions:
        if input_key not in relation_values:
            continue
        requested = set(relation_values[input_key])
        active_rows = {
            row[code_column]: dict(row) for row in db.execute(
                f"SELECT * FROM {table} WHERE contract_id=? AND deleted_at IS NULL",
                (contract_id,),
            )
        }
        removed = set(active_rows) - requested
        if removed:
            placeholders = ",".join("?" for _ in removed)
            db.execute(
                f"""UPDATE {table}
                    SET deleted_at=?,updated_by=?,updated_at=?
                    WHERE contract_id=? AND deleted_at IS NULL
                      AND {code_column} IN ({placeholders})""",
                (now, actor_id, now, contract_id, *sorted(removed)),
            )
        for code in sorted(requested - set(active_rows)):
            db.execute(
                f"""INSERT INTO {table}
                    (id,contract_id,{code_column},source,provenance,created_by,updated_by,created_at,updated_at)
                    VALUES (?, ?, ?, 'user', 'user_confirmed', ?, ?, ?, ?)""",
                (_uuid(), contract_id, code, actor_id, actor_id, now, now),
            )


def _contract_normalization_status(existing, normalized, relations, current_relations):
    submitted = bool(
        {"contract_name", "contract_status_code", "exclusivity"} & set(normalized)
        or {"interim_product_codes"} & set(relations)
    )
    if not submitted:
        return None
    final = dict(existing or {})
    final.update(normalized)
    products = relations.get(
        "interim_product_codes",
        (current_relations or {}).get("interim_product_codes", []),
    )
    complete = bool(
        _clean(final.get("contract_name"), 300)
        and final.get("contract_status_code") in CONTRACT_STATUSES
        and final.get("exclusivity") in CONTRACT_EXCLUSIVITIES
        and final.get("start_date")
        and final.get("end_date")
        and products
    )
    return "confirmed" if complete else "review_required"


def _customer_review_reasons(db, customer, relations=None):
    relations = relations or _policy_relation_values(db, customer["id"])
    reasons = []
    if not customer.get("business_stage") or customer.get("business_stage_review_status") != "confirmed":
        reasons.append("customer_stage")
    if not customer.get("master_maturity") or customer.get("master_maturity_review_status") != "confirmed":
        reasons.append("master_maturity")
    if not relations["organization_roles"] or customer.get("organization_role_review_status") != "confirmed":
        reasons.append("organization_role")
    if "medical_unspecified" in relations["business_area_details"]:
        reasons.append("medical_detail")
    payment_review = db.execute(
        "SELECT 1 FROM customer_payment_terms WHERE customer_id=? AND deleted_at IS NULL AND normalization_status='review_required' LIMIT 1",
        (customer["id"],),
    ).fetchone()
    logistics_review = db.execute(
        "SELECT 1 FROM customer_logistics WHERE customer_id=? AND deleted_at IS NULL AND normalization_status='review_required' LIMIT 1",
        (customer["id"],),
    ).fetchone()
    contract_review = db.execute(
        "SELECT 1 FROM customer_contracts WHERE customer_id=? AND deleted_at IS NULL AND normalization_status='review_required' LIMIT 1",
        (customer["id"],),
    ).fetchone()
    if contract_review:
        reasons.append("contracts")
    if payment_review:
        reasons.append("payment_terms")
    if logistics_review:
        reasons.append("logistics")
    return reasons


def _decorate_customer_policy(db, value):
    item = dict(value)
    relations = _policy_relation_values(db, item["id"])
    item.update(relations)
    item["organization_role_candidates"] = legacy_role_candidates(
        item.get("relationship_type"), item.get("customer_role")
    )
    item["technical_identity_status"] = (
        "temporary_identity" if str(item.get("customer_id") or "").startswith("TEMP-")
        else "stable_identity"
    )
    item["review_required_reasons"] = _customer_review_reasons(db, item, relations)
    item["review_required"] = bool(item["review_required_reasons"])
    item["review_required_count"] = len(item["review_required_reasons"])
    return item


def _replace_policy_relations(db, customer_id, data, actor_id, now):
    if "organization_roles" in data:
        roles = {_clean(value, 40) for value in _json_list(data.get("organization_roles"), "거래처 역할")}
        invalid = roles - set(ORGANIZATION_ROLES)
        if invalid:
            raise ValueError("거래처 역할 코드가 올바르지 않습니다.")
        db.execute("DELETE FROM customer_organization_roles WHERE customer_id=?", (customer_id,))
        for role in sorted(roles):
            db.execute(
                "INSERT INTO customer_organization_roles(customer_id,role_code,provenance,created_by,created_at) VALUES (?,?,'user_confirmed',?,?)",
                (customer_id, role, actor_id, now),
            )
        db.execute(
            """UPDATE customer_master
               SET organization_role_review_status=?,organization_role_reviewed_by=?,organization_role_reviewed_at=?
               WHERE id=?""",
            ("confirmed" if roles else "review_required", actor_id if roles else None,
             now if roles else None, customer_id),
        )

    if "language_codes" in data:
        languages = [_clean(value, 10) for value in _json_list(data.get("language_codes"), "사용 언어")]
        if set(languages) - set(LANGUAGES):
            raise ValueError("사용 언어 코드가 올바르지 않습니다.")
        deduplicated = list(dict.fromkeys(languages))
        db.execute("DELETE FROM customer_languages WHERE customer_id=?", (customer_id,))
        for index, language in enumerate(deduplicated):
            db.execute(
                "INSERT INTO customer_languages(customer_id,language_code,is_primary,created_by,created_at) VALUES (?,?,?,?,?)",
                (customer_id, language, int(index == 0), actor_id, now),
            )

    if "business_area_details" in data:
        details = {_clean(value, 40) for value in _json_list(data.get("business_area_details"), "상세 사업분야")}
        invalid = details - SELECTABLE_BUSINESS_DETAILS
        if invalid:
            raise ValueError("상세 사업분야 코드가 올바르지 않습니다.")
        parents = {business_parent(code) for code in details}
        db.execute("DELETE FROM customer_business_areas WHERE customer_id=?", (customer_id,))
        db.execute("DELETE FROM customer_business_area_details WHERE customer_id=?", (customer_id,))
        for parent in sorted(parents - {None}):
            db.execute(
                "INSERT INTO customer_business_areas(customer_id,business_unit,created_at) VALUES (?,?,?)",
                (customer_id, parent, now),
            )
        for detail in sorted(details & {"medical_os", "medical_ns"}):
            db.execute(
                """INSERT INTO customer_business_area_details
                   (customer_id,detail_code,parent_business_unit,provenance,created_by,created_at)
                   VALUES (?,?,'medical','user_confirmed',?,?)""",
                (customer_id, detail, actor_id, now),
            )


def _validate_master_policy(data):
    values = {}
    if "business_stage" in data:
        stage = _clean(data.get("business_stage"), 40) or None
        if stage not in CUSTOMER_STAGES:
            raise ValueError("거래처 업무단계를 선택하세요.")
        values.update({
            "business_stage": stage,
            "business_stage_review_status": "confirmed",
            "business_stage_reviewed_by": g.current_user["id"],
            "business_stage_reviewed_at": _now(),
            "lifecycle_status": "ended" if stage == "discontinued" else "active",
        })
    if "master_maturity" in data:
        maturity = _clean(data.get("master_maturity"), 40) or None
        if maturity not in MASTER_MATURITIES:
            raise ValueError("Master 정리상태를 선택하세요.")
        values.update({
            "master_maturity": maturity,
            "master_maturity_review_status": "confirmed",
            "master_maturity_reviewed_by": g.current_user["id"],
            "master_maturity_reviewed_at": _now(),
        })
    if "timezone_name" in data:
        timezone_name = _clean(data.get("timezone_name"), 100)
        if timezone_name and timezone_name not in IANA_TIMEZONES:
            raise ValueError("IANA Timezone 목록에서 선택하세요.")
        values["timezone_name"] = timezone_name
    return values


def _completion(db, customer_id):
    customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
    checks = {
        "기본정보": bool(customer["display_name"] and customer["headquarters_country"] and customer["relationship_type"]),
        "담당자": bool(customer["primary_owner_id"]),
        "계약·결제조건": bool(db.execute("SELECT 1 FROM customer_contracts WHERE customer_id=? AND deleted_at IS NULL LIMIT 1", (customer_id,)).fetchone()
                            or db.execute("SELECT 1 FROM customer_payment_terms WHERE customer_id=? AND deleted_at IS NULL LIMIT 1", (customer_id,)).fetchone()),
        "제품·FOC·MOQ": bool(db.execute("SELECT 1 FROM customer_product_terms WHERE customer_id=? AND deleted_at IS NULL LIMIT 1", (customer_id,)).fetchone()),
        "물류·통관": bool(db.execute("SELECT 1 FROM customer_logistics WHERE customer_id=? AND deleted_at IS NULL LIMIT 1", (customer_id,)).fetchone()),
        "인허가": bool(db.execute("SELECT 1 FROM customer_registrations WHERE customer_id=? AND deleted_at IS NULL LIMIT 1", (customer_id,)).fetchone()),
        "다음 액션": bool(db.execute("SELECT 1 FROM customer_meetings WHERE customer_id=? AND deleted_at IS NULL AND due_date IS NOT NULL LIMIT 1", (customer_id,)).fetchone()),
    }
    complete = sum(checks.values())
    return {"percent": round(complete / len(checks) * 100), "checks": checks, "complete": complete == len(checks)}


def _sync_from_shipments(db, actor_id, country_resolver, audit_fn=None):
    started = _now()
    run_id = db.execute(
        "INSERT INTO customer_sync_runs(started_at,requested_by,status) VALUES (?,?,'running')",
        (started, actor_id),
    ).lastrowid
    db.commit()
    stats = {"created": 0, "updated": 0, "duplicates": 0, "missing_code": 0,
             "missing_country": 0, "errors": 0}
    try:
        shipment_rows = [dict(row) for row in db.execute(
            "SELECT * FROM shipments WHERE is_overseas=1 ORDER BY ship_date,id"
        ).fetchall()]
        coded = defaultdict(list)
        missing = defaultdict(list)
        for row in shipment_rows:
            code = _valid_erp_code(row.get("partner_code"))
            if code:
                coded[code].append(row)
            else:
                missing[_clean(row.get("partner_name"), 300).casefold()].append(row)
        for partner_key, rows in missing.items():
            partner_name = _clean(rows[-1].get("partner_name"), 300) if rows else ""
            if not partner_name:
                continue
            _insert_review(
                db, "missing_erp_code", hashlib.sha256(partner_key.encode()).hexdigest()[:24],
                "과거 출고 이관자료에 ERP 거래처 코드가 없어 이름으로 자동 생성·병합하지 않았습니다.",
                sync_run_id=run_id, erp_name=partner_name,
            )
            stats["missing_code"] += 1

        current_year = datetime.now(timezone.utc).year
        existing_customers = [dict(row) for row in db.execute("SELECT * FROM customer_master").fetchall()]
        for code, rows in coded.items():
            latest = max(rows, key=lambda item: (item.get("ship_date") or "", item.get("id") or 0))
            original_name = _clean(latest.get("partner_name"), 300) or f"ERP {code}"
            country_code = None
            country_name = ""
            for item in reversed(rows):
                country_code, country_name = _country_from_shipment(item, country_resolver)
                if country_name:
                    break
            if country_name:
                for item in rows:
                    if not item.get("country_name"):
                        db.execute(
                            "UPDATE shipments SET country_code=?,country_name=? WHERE id=?",
                            (country_code, country_name, item["id"]),
                        )
            customer = db.execute("SELECT * FROM customer_master WHERE erp_partner_code=?", (code,)).fetchone()
            if customer:
                db.execute(
                    """UPDATE customer_master SET erp_original_name=?,erp_country_code=?,erp_country_name=?,
                       headquarters_country=CASE WHEN headquarters_country='' THEN ? ELSE headquarters_country END,
                       country_code=COALESCE(country_code,?), sales_region=CASE WHEN sales_region='미분류' THEN ? ELSE sales_region END,
                       erp_last_seen_at=?, updated_at=?, version=version+1 WHERE id=?""",
                    (original_name, country_code, country_name, country_name, country_code, _sales_region(country_code),
                     latest.get("ship_date"), _now(), customer["id"]),
                )
                customer_id = customer["id"]
                stats["updated"] += 1
            else:
                candidates = [item for item in existing_customers
                              if item.get("erp_partner_code") != code
                              and (_similar_name(original_name, item.get("display_name"))
                                   or _similar_name(original_name, item.get("erp_original_name")))]
                duplicate_status = "review_required" if candidates else "clear"
                customer_id = _uuid()
                db.execute(
                    """INSERT INTO customer_master
                       (id,customer_id,erp_partner_code,erp_original_name,erp_country_code,erp_country_name,
                        display_name,headquarters_country,country_code,sales_region,source_type,relationship_type,duplicate_review_status,
                        erp_last_seen_at,created_by,updated_by,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,'dealer',?,?,?,?,?,?)""",
                    (customer_id, code, code, original_name, country_code, country_name,
                     original_name, country_name,
                     country_code, _sales_region(country_code), "erp", duplicate_status,
                     latest.get("ship_date"), actor_id, actor_id, _now(), _now()),
                )
                units = {row.get("business_unit") for row in rows if row.get("business_unit") in BUSINESS_UNITS}
                for unit in units:
                    db.execute("INSERT OR IGNORE INTO customer_business_areas VALUES (?,?,?)", (customer_id, unit, _now()))
                if candidates:
                    _insert_review(
                        db, "similar_name_different_code", code,
                        "이름이 비슷하지만 ERP 코드가 달라 별도 거래처로 만들고 중복 검토 대상으로 표시했습니다.",
                        sync_run_id=run_id, erp_code=code, erp_name=original_name,
                        candidates=[item["id"] for item in candidates],
                    )
                    stats["duplicates"] += 1
                existing_customers.append(dict(db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()))
                stats["created"] += 1
            issue_dates = sorted({row.get("ship_date") for row in rows if row.get("ship_date")})
            cycles = [(date.fromisoformat(right) - date.fromisoformat(left)).days
                      for left, right in zip(issue_dates, issue_dates[1:]) if right > left]
            avg_days = round(sum(cycles) / len(cycles), 1) if cycles else None
            next_date = (date.fromisoformat(issue_dates[-1]) + timedelta(days=round(avg_days))).isoformat() if issue_dates and avg_days else None
            current_sales = sum(_number(row.get("krw_supply")) for row in rows if str(row.get("ship_date", ""))[:4] == str(current_year))
            previous_sales = sum(_number(row.get("krw_supply")) for row in rows if str(row.get("ship_date", ""))[:4] == str(current_year - 1))
            db.execute(
                """INSERT INTO customer_erp_metrics
                   (customer_id,shipment_count,first_ship_date,last_ship_date,current_year_sales_krw,
                    previous_year_sales_krw,cumulative_sales_krw,average_order_cycle_days,
                    next_expected_order_date,last_product_name,last_quantity,calculated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(customer_id) DO UPDATE SET shipment_count=excluded.shipment_count,
                    first_ship_date=excluded.first_ship_date,last_ship_date=excluded.last_ship_date,
                    current_year_sales_krw=excluded.current_year_sales_krw,
                    previous_year_sales_krw=excluded.previous_year_sales_krw,
                    cumulative_sales_krw=excluded.cumulative_sales_krw,
                    average_order_cycle_days=excluded.average_order_cycle_days,
                    next_expected_order_date=excluded.next_expected_order_date,
                    last_product_name=excluded.last_product_name,last_quantity=excluded.last_quantity,
                    calculated_at=excluded.calculated_at""",
                (customer_id, len({row.get("issue_no") for row in rows}),
                 issue_dates[0] if issue_dates else None, issue_dates[-1] if issue_dates else None,
                 current_sales, previous_sales, sum(_number(row.get("krw_supply")) for row in rows),
                 avg_days, next_date, _clean(latest.get("product_name"), 300),
                 _number(latest.get("quantity")), _now()),
            )
            if not country_name:
                _insert_review(
                    db, "missing_country", code,
                    "ERP 출고 응답에서 국가를 확정할 수 없습니다.", sync_run_id=run_id,
                    erp_code=code, erp_name=original_name, candidates=[customer_id],
                )
                stats["missing_country"] += 1
        last_erp_run = db.execute(
            """SELECT excluded_header_count,excluded_partner_count
               FROM erp_sync_runs WHERE status='success' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        domestic = int(last_erp_run["excluded_header_count"] or 0) if last_erp_run else 0
        domestic_partners = None
        if last_erp_run and int(last_erp_run["excluded_partner_count"] or 0) > 0:
            domestic_partners = int(last_erp_run["excluded_partner_count"])
        finished = _now()
        db.execute(
            """UPDATE customer_sync_runs SET finished_at=?,status='success',shipment_row_count=?,
               overseas_partner_count=?,created_count=?,updated_count=?,duplicate_review_count=?,
               missing_code_count=?,missing_country_count=?,domestic_excluded_count=?,
               domestic_excluded_partner_count=?,error_count=? WHERE id=?""",
            (finished, len(shipment_rows), len(coded), stats["created"], stats["updated"],
             stats["duplicates"], stats["missing_code"], stats["missing_country"], domestic,
             domestic_partners, stats["errors"], run_id),
        )
        audit_after = stats | {
            "domestic_excluded_headers": domestic,
            "domestic_excluded_partners": domestic_partners,
            "coded_partners": len(coded),
        }
        if audit_fn:
            audit_fn(
                "CUSTOMER_ERP_SYNC", "customer_master", str(run_id),
                f"ERP 코드 기준 거래처 동기화 · 신규 {stats['created']} · 갱신 {stats['updated']}",
                None, audit_after,
            )
        else:
            _system_audit(
                db, "CUSTOMER_ERP_SYNC", "customer_master", str(run_id),
                f"ERP 코드 기준 거래처 동기화 · 신규 {stats['created']} · 갱신 {stats['updated']}",
                after=audit_after,
            )
        db.commit()
        return _row(db.execute("SELECT * FROM customer_sync_runs WHERE id=?", (run_id,)).fetchone())
    except Exception as exc:
        db.rollback()
        db.execute(
            "UPDATE customer_sync_runs SET finished_at=?,status='failed',error_count=1,error_message=? WHERE id=?",
            (_now(), _clean(exc, 1000), run_id),
        )
        db.commit()
        raise


DETAIL_TABLES = {
    "contacts": ("customer_contacts", {"contact_name", "department_title", "responsibility", "is_decision_maker", "is_primary_contact", "email", "phone", "messenger", "language", "language_code", "employment_status", "notes"}),
    "contracts": ("customer_contracts", {"contract_name", "contract_no", "contract_type", "exclusivity", "contract_status", "contract_status_code", "start_date", "end_date", "auto_renew", "notice_deadline", "territory", "products_scope", "currency", "contract_amount", "annual_min_amount", "annual_min_quantity", "approval_user_name", "approval_date", "renewal_date", "notes"}),
    "payment-terms": ("customer_payment_terms", {"payment_method", "payment_method_code", "payment_method_other", "advance_ratio", "deferred_ratio", "collection_basis", "deferred_days", "installments_json", "payment_schedule_json", "lc_terms", "currency", "fee_bearer", "credit_limit", "hold_on_overdue", "approver_name", "evidence_path", "notes", "effective_from", "effective_to", "is_current"}),
    "product-terms": ("customer_product_terms", {"interim_product_code", "product_name", "specification", "internal_product_code", "customer_product_code", "price_type", "base_unit_price", "agreed_unit_price", "currency", "moq", "moq_basis", "paid_quantity", "foc_quantity", "foc_condition", "packaging_label", "notes", "is_current"}),
    "logistics": ("customer_logistics", {"incoterms", "transport_mode", "forwarder", "customs_broker", "courier_code", "courier_account", "origin_address", "destination_address", "consignee", "notify_party", "default_port", "required_documents", "coa_required", "coo_required", "fsc_required", "shipping_mark", "originals_required", "external_system", "insurance_bearer", "requires_import_invoice", "requires_additional_documents", "additional_documents_json", "additional_documents_note", "customs_invoice_notes", "notes"}),
    "registrations": ("customer_registrations", {"country_code", "country_name", "product_name", "specification", "registration_status", "registration_no", "holder_name", "application_date", "approval_date", "valid_from", "valid_to", "renewal_date", "renewal_owner_id", "certificate_path", "label_languages", "notes"}),
    "odm-projects": ("customer_odm_projects", {"project_no", "brand_name", "product_spec", "development_stage", "expected_quantity", "moq", "target_unit_price", "sample_date", "specification_confirmed_at", "packaging_label", "regulatory_owner", "development_cost", "tooling_cost", "nda_signed", "quality_agreement", "expected_po_date", "expected_launch_date", "owner_id", "next_action_date", "issue_notes"}),
    "sales-plans": ("customer_sales_plans", {"plan_year", "business_unit", "product_group", "optimistic_amount", "neutral_amount", "conservative_amount", "applied_amount", "currency", "override_next_order_date", "override_reason"}),
    "education": ("customer_education_events", {"product_name", "event_date", "attendees", "education_type", "trainer_name", "material_path", "followup_required", "next_event_date", "notes"}),
    "marketing": ("customer_marketing_support", {"support_date", "support_item", "quantity", "support_amount", "currency", "shipping_info", "promotion_record_id", "notes"}),
    "competitors": ("customer_competitors", {"product_category", "brand_name", "handles_implants", "main_products", "estimated_scale", "notes"}),
    "meetings": ("customer_meetings", {"meeting_date", "attendees", "discussion", "decisions", "issue_text", "importance", "next_action", "owner_id", "due_date", "action_status", "next_meeting_date"}),
}


DATE_FIELDS = {"start_date", "end_date", "notice_deadline", "approval_date", "renewal_date", "effective_from", "effective_to", "application_date", "valid_from", "valid_to", "sample_date", "specification_confirmed_at", "expected_po_date", "expected_launch_date", "next_action_date", "override_next_order_date", "event_date", "next_event_date", "support_date", "meeting_date", "due_date", "next_meeting_date"}
NUMBER_FIELDS = {"contract_amount", "annual_min_amount", "annual_min_quantity", "advance_ratio", "deferred_ratio", "deferred_days", "credit_limit", "base_unit_price", "agreed_unit_price", "moq", "paid_quantity", "foc_quantity", "expected_quantity", "target_unit_price", "development_cost", "tooling_cost", "plan_year", "optimistic_amount", "neutral_amount", "conservative_amount", "applied_amount", "quantity", "support_amount"}
BOOLEAN_FIELDS = {"auto_renew", "hold_on_overdue", "is_current", "is_decision_maker", "is_primary_contact", "coa_required", "coo_required", "fsc_required", "originals_required", "nda_signed", "quality_agreement", "followup_required", "handles_implants", "requires_import_invoice", "requires_additional_documents"}


def _normalize_detail(kind, data, country_resolver=None):
    _table, fields = DETAIL_TABLES[kind]
    values = {}
    for field in fields:
        if field not in data:
            continue
        if field in DATE_FIELDS:
            values[field] = _iso_date(data.get(field), field)
        elif field in NUMBER_FIELDS:
            values[field] = _number(data.get(field))
        elif field in BOOLEAN_FIELDS:
            values[field] = int(bool(data.get(field)))
        elif field in {"installments_json", "payment_schedule_json", "additional_documents_json"}:
            value = data.get(field, [])
            value = _json_list(value, {
                "installments_json": "기존 분할수금",
                "payment_schedule_json": "지급 Schedule",
                "additional_documents_json": "추가 필요서류",
            }[field])
            values[field] = _json(value)
        else:
            values[field] = _clean(data.get(field), 4000)
    if kind == "contacts":
        if not values.get("contact_name"):
            raise FieldValidationError("contact_name", "업체 담당자명을 입력하세요.")
        if values.get("email") and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"]):
            raise FieldValidationError("email", "이메일 형식을 확인하세요.")
        if values.get("language_code") and values["language_code"] not in LANGUAGES:
            raise FieldValidationError("language_code", "사용 언어를 목록에서 선택하세요.")
        if values.get("employment_status") and values["employment_status"] not in CONTACT_EMPLOYMENT_STATUSES:
            raise FieldValidationError("employment_status", "재직상태를 목록에서 선택하세요.")
    if kind == "contracts":
        if "contract_status_code" in values:
            status = values.get("contract_status_code") or None
            if status and status not in CONTRACT_STATUSES:
                raise FieldValidationError("contract_status_code", "계약상태를 목록에서 선택하세요.")
        if "exclusivity" in values:
            exclusivity = values.get("exclusivity") or None
            if exclusivity and exclusivity not in CONTRACT_EXCLUSIVITIES:
                raise FieldValidationError("exclusivity", "독점구분을 목록에서 선택하세요.")
        if "currency" in values and values["currency"] not in CONTRACT_CURRENCIES:
            raise FieldValidationError("currency", "통화를 목록에서 선택하세요.")
    if kind == "product-terms":
        code = values.get("interim_product_code") or None
        if code and code not in INTERIM_CONTRACT_PRODUCTS:
            raise FieldValidationError("interim_product_code", "Interim Product 목록에서 선택하세요.")
        if code and not values.get("product_name"):
            values["product_name"] = INTERIM_CONTRACT_PRODUCTS[code]
        if not values.get("product_name"):
            raise FieldValidationError("product_name", "제품명을 입력하세요.")
        if values.get("moq_basis") not in {"paid", "total_supply"}:
            raise FieldValidationError("moq_basis", "MOQ 판단기준을 유상수량 또는 총공급수량으로 선택하세요.")
        paid = _number(values.get("paid_quantity"))
        foc = _number(values.get("foc_quantity"))
        price = _number(values.get("agreed_unit_price"))
        if foc > 0 and paid <= 0:
            raise FieldValidationError("foc_quantity", "FOC 수량이 있으면 기준 유상수량은 0보다 커야 합니다.")
        total = paid + foc
        values["foc_ratio"] = round(foc / paid * 100, 6) if paid else 0
        values["effective_unit_price"] = round(paid * price / total, 6) if total else 0
    if kind == "payment-terms":
        if "payment_method_code" in values:
            if values["payment_method_code"] not in PAYMENT_METHODS:
                raise FieldValidationError("payment_method_code", "결제수단은 T/T, L/C, 기타 중에서 선택하세요.")
            if values["payment_method_code"] == "other" and not values.get("payment_method_other"):
                raise FieldValidationError("payment_method_other", "기타 결제수단을 입력하세요.")
        if "payment_schedule_json" in values:
            schedule = json.loads(values["payment_schedule_json"] or "[]")
            if not schedule:
                raise FieldValidationError("payment_schedule_json", "지급 Schedule 단계를 하나 이상 등록하세요.")
            normalized = []
            for index, item in enumerate(schedule, start=1):
                if not isinstance(item, dict):
                    raise FieldValidationError("payment_schedule_json", "지급 Schedule 각 행의 형식이 올바르지 않습니다.")
                percentage = _number(item.get("percentage"))
                if percentage <= 0 or percentage > 100:
                    raise FieldValidationError("payment_schedule_json", "지급 Schedule 비율은 0보다 크고 100 이하여야 합니다.")
                trigger = _clean(item.get("trigger"), 40)
                if trigger not in PAYMENT_TRIGGERS:
                    raise FieldValidationError("payment_schedule_json", "지급 Schedule 시점을 목록에서 선택하세요.")
                normalized.append({
                    "sequence": index,
                    "percentage": percentage,
                    "trigger": trigger,
                    "note": _clean(item.get("note"), 500),
                })
            ratio_sum = sum(item["percentage"] for item in normalized)
            if normalized and not 99.5 <= ratio_sum <= 100.5:
                raise FieldValidationError("payment_schedule_json", f"지급 Schedule 비율 합계는 100%여야 합니다. 현재 {ratio_sum:g}%입니다.")
            values["payment_schedule_json"] = _json(normalized)
            values["normalization_status"] = "confirmed"
        elif "installments_json" in values or "advance_ratio" in values:
            # Backward-compatible validation for legacy API callers.  It never
            # rewrites the new canonical schedule or declares legacy raw values confirmed.
            installments = json.loads(values.get("installments_json", "[]"))
            ratio_sum = _number(values.get("advance_ratio")) + sum(
                _number(item.get("ratio")) for item in installments if isinstance(item, dict)
            )
            if ratio_sum and not 99.5 <= ratio_sum <= 100.5:
                raise FieldValidationError("advance_ratio", f"선불과 분할수금 비율 합계는 100%여야 합니다. 현재 {ratio_sum:g}%입니다.")
            values["deferred_ratio"] = max(0, 100 - _number(values.get("advance_ratio")))
    if kind == "logistics":
        if "courier_code" in values:
            courier = values.get("courier_code") or None
            if courier and courier not in COURIERS:
                raise FieldValidationError("courier_code", "Courier는 DHL, FedEx, UPS, EMS, TNT 중에서 선택하세요.")
        if "additional_documents_json" in values:
            documents = json.loads(values["additional_documents_json"] or "[]")
            if set(documents) - set(ADDITIONAL_DOCUMENTS):
                raise FieldValidationError("additional_documents_json", "추가 필요서류 코드가 올바르지 않습니다.")
            if (values.get("requires_additional_documents") and not documents
                    and not values.get("additional_documents_note")):
                raise FieldValidationError("additional_documents_json", "추가서류가 필요하면 원산지증명서를 선택하거나 기타 필요서류를 입력하세요.")
            values["additional_documents_json"] = _json(list(dict.fromkeys(documents)))
            values["normalization_status"] = "confirmed"
    if kind == "registrations" and "country_name" in values:
        name = values.get("country_name")
        resolved = country_resolver(name) if name and country_resolver else None
        if name and not resolved:
            raise FieldValidationError("country_name", "대상국가는 표준 국가목록에서 선택하세요.")
        values["country_code"] = (resolved or {}).get("map_id", "")
        values["country_name"] = (resolved or {}).get("name", "")
    if kind == "meetings":
        if values.get("importance") and values["importance"] not in MEETING_IMPORTANCE:
            raise FieldValidationError("importance", "중요도를 목록에서 선택하세요.")
        if values.get("action_status") and values["action_status"] not in MEETING_ACTION_STATUSES:
            raise FieldValidationError("action_status", "진행상태를 목록에서 선택하세요.")
    return values


def _validate_detail_state(kind, existing, values):
    final = dict(existing or {})
    final.update(values)
    intervals = {
        "contracts": ("start_date", "end_date", "계약 시작일은 종료일보다 늦을 수 없습니다."),
        "payment-terms": ("effective_from", "effective_to", "적용 시작일은 종료일보다 늦을 수 없습니다."),
        "registrations": ("valid_from", "valid_to", "유효 시작일은 종료일보다 늦을 수 없습니다."),
    }
    if kind not in intervals:
        return
    start_field, end_field, message = intervals[kind]
    start_value, end_value = final.get(start_field), final.get(end_field)
    if start_value and end_value and start_value > end_value:
        raise FieldValidationError(end_field, message)


def customer_order_defaults(db, customer_id):
    """Return current terms only; callers copy these values into an order snapshot."""
    customer = db.execute(
        "SELECT * FROM customer_master WHERE id=?", (customer_id,)
    ).fetchone()
    if not customer:
        raise ValueError("거래처 마스터에서 연결 거래처를 찾을 수 없습니다.")
    payment = db.execute(
        """SELECT * FROM customer_payment_terms
           WHERE customer_id=? AND deleted_at IS NULL AND is_current=1
           ORDER BY COALESCE(effective_from,'') DESC,created_at DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()
    products = db.execute(
        """SELECT * FROM customer_product_terms
           WHERE customer_id=? AND deleted_at IS NULL AND is_current=1
           ORDER BY product_name COLLATE NOCASE,created_at DESC""",
        (customer_id,),
    ).fetchall()
    return {
        "customer": {
            "id": customer["id"], "customer_id": customer["customer_id"],
            "display_name": customer["display_name"],
            "default_currency": customer["default_currency"],
        },
        "payment_terms": dict(payment) if payment else {},
        "product_terms": [dict(row) for row in products],
    }


def snapshot_customer_order_terms(db, order_record_id, payload, actor_id, audit_fn=None):
    """Freeze the terms applied to an order. Existing snapshots are immutable."""
    existing = db.execute(
        "SELECT * FROM customer_order_terms_snapshots WHERE order_record_id=?",
        (order_record_id,),
    ).fetchone()
    if existing:
        return dict(existing)
    customer_id = _clean(payload.get("customer_master_id"), 80)
    if not customer_id and payload.get("account_id"):
        linked = db.execute(
            "SELECT id FROM customer_master WHERE source_record_id=?",
            (_clean(payload.get("account_id"), 100),),
        ).fetchone()
        customer_id = linked["id"] if linked else ""
    if not customer_id:
        return None
    defaults = customer_order_defaults(db, customer_id)
    mode = _clean(payload.get("customer_terms_mode"), 30) or "default"
    if mode not in {"default", "order_override", "save_as_default"}:
        raise ValueError("주문 결제·제품조건 적용방식이 올바르지 않습니다.")
    reason = _clean(payload.get("order_terms_change_reason"), 2000)
    if mode != "default" and not reason:
        raise ValueError("거래처 기본조건과 다르게 적용하려면 변경사유를 입력하세요.")
    if mode == "default":
        payment = defaults["payment_terms"]
        products = defaults["product_terms"]
        if not payment and not products:
            raise ValueError(
                "거래처 기본조건이 없습니다. 이번 주문만 입력하거나 새 기본조건으로 저장하세요."
            )
        requested_products = payload.get("order_product_terms") or []
        if isinstance(requested_products, list) and requested_products:
            selected = []
            for requested in requested_products:
                if not isinstance(requested, dict) or not _clean(requested.get("product_name"), 300):
                    continue
                base = next(
                    (dict(row) for row in products
                     if _clean(row.get("product_name"), 300).casefold()
                     == _clean(requested.get("product_name"), 300).casefold()),
                    None,
                )
                if base:
                    base["paid_quantity"] = _number(requested.get("paid_quantity"))
                    base["foc_quantity"] = _number(requested.get("foc_quantity"))
                    paid, foc = base["paid_quantity"], base["foc_quantity"]
                    total = paid + foc
                    base["foc_ratio"] = round(foc / paid * 100, 6) if paid else 0
                    base["effective_unit_price"] = round(
                        paid * _number(base.get("agreed_unit_price")) / total, 6
                    ) if total else 0
                    selected.append(base)
            if selected:
                products = selected
    else:
        payment = payload.get("order_payment_terms") or {}
        products = payload.get("order_product_terms") or []
        if not isinstance(payment, dict) or not isinstance(products, list):
            raise ValueError("주문 적용조건 형식이 올바르지 않습니다.")
        payment = _normalize_detail("payment-terms", payment)
        products = [_normalize_detail("product-terms", row) for row in products]
    moq_exception_reason = _clean(payload.get("order_moq_exception_reason"), 2000)
    moq_exception_approver = _clean(payload.get("order_moq_exception_approver"), 300)
    moq_warnings = []
    for product in products:
        moq = _number(product.get("moq"))
        paid = _number(product.get("paid_quantity"))
        foc = _number(product.get("foc_quantity"))
        basis_quantity = paid if product.get("moq_basis") == "paid" else paid + foc
        if moq > 0 and basis_quantity < moq:
            moq_warnings.append({
                "product_name": product.get("product_name"), "moq": moq,
                "basis_quantity": basis_quantity, "moq_basis": product.get("moq_basis"),
            })
    if moq_warnings and (not moq_exception_reason or not moq_exception_approver):
        raise ValueError("MOQ 미충족 주문은 예외사유와 승인자를 모두 입력하세요.")
    now = _now()
    if mode == "save_as_default":
        if payment:
            db.execute(
                "UPDATE customer_payment_terms SET is_current=0,updated_by=?,updated_at=? WHERE customer_id=? AND deleted_at IS NULL AND is_current=1",
                (actor_id, now, customer_id),
            )
            payment_row = dict(payment)
            payment_row.update({"id": _uuid(), "customer_id": customer_id, "is_current": 1,
                                "created_by": actor_id, "updated_by": actor_id,
                                "created_at": now, "updated_at": now})
            columns = list(payment_row)
            db.execute(
                f"INSERT INTO customer_payment_terms ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                [payment_row[key] for key in columns],
            )
        for product in products:
            db.execute(
                "UPDATE customer_product_terms SET is_current=0,updated_by=?,updated_at=? WHERE customer_id=? AND product_name=? AND deleted_at IS NULL AND is_current=1",
                (actor_id, now, customer_id, product["product_name"]),
            )
            product_row = dict(product)
            product_row.update({"id": _uuid(), "customer_id": customer_id, "is_current": 1,
                                "created_by": actor_id, "updated_by": actor_id,
                                "created_at": now, "updated_at": now})
            columns = list(product_row)
            db.execute(
                f"INSERT INTO customer_product_terms ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                [product_row[key] for key in columns],
            )
    snapshot_id = _uuid()
    db.execute(
        """INSERT INTO customer_order_terms_snapshots
           (id,order_record_id,customer_id,payment_terms_json,product_terms_json,
            exception_reason,moq_exception_reason,moq_exception_approver,created_by,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (snapshot_id, order_record_id, customer_id, _json(payment), _json(products),
         reason, moq_exception_reason, moq_exception_approver, actor_id, now),
    )
    after = {"mode": mode, "customer_id": customer_id, "payment_terms": payment,
             "product_terms": products, "exception_reason": reason,
             "moq_warnings": moq_warnings,
             "moq_exception_reason": moq_exception_reason,
             "moq_exception_approver": moq_exception_approver}
    if audit_fn:
        audit_fn("CUSTOMER_ORDER_TERMS_SNAPSHOT", "customer_master", customer_id,
                 f"주문 {order_record_id} 적용조건 고정 저장", None, after)
    else:
        _system_audit(db, "CUSTOMER_ORDER_TERMS_SNAPSHOT", "customer_master", customer_id,
                      f"주문 {order_record_id} 적용조건 고정 저장", after=after)
    return dict(db.execute(
        "SELECT * FROM customer_order_terms_snapshots WHERE id=?", (snapshot_id,)
    ).fetchone())


def register_customer_master(app, get_db, role_required, csrf_required, audit_fn,
                             country_resolver=None, country_catalog=None):
    @app.get("/api/customer-master/taxonomy")
    @role_required(*READ_ROLES)
    def customer_master_taxonomy():
        payload = taxonomy_payload()
        payload["countries"] = [
            {
                "code": code,
                "name": definition.get("name", ""),
                "label": definition.get("label", definition.get("name", "")),
                "sales_region": _sales_region(code),
            }
            for code, definition in sorted((country_catalog or {}).items(), key=lambda item: item[1].get("name", ""))
        ]
        payload["timezones"] = sorted(IANA_TIMEZONES)
        payload["contract"] = {
            "customer_identity": "customer_master.id",
            "country_catalog": "ISO-3166 numeric + canonical English name",
            "business_parent_axis": list(PARENT_BUSINESS_AREAS),
            "legacy_role_values_are_candidates_only": True,
        }
        return jsonify(**payload)

    @app.get("/api/customer-master/options")
    @role_required(*READ_ROLES)
    def customer_master_options():
        rows = get_db().execute(
            """SELECT id,customer_id,display_name,headquarters_country,sales_region,
                      default_currency,source_record_id,primary_owner_id,secondary_owner_id,
                      business_stage,master_maturity
               FROM customer_master WHERE lifecycle_status='active'
                 AND COALESCE(business_stage,'')<>'discontinued'
               ORDER BY display_name COLLATE NOCASE"""
        ).fetchall()
        return jsonify(customers=[dict(row) for row in rows])

    @app.get("/api/customer-master/<customer_id>/order-defaults")
    @role_required(*READ_ROLES)
    def customer_master_order_defaults(customer_id):
        try:
            defaults = customer_order_defaults(get_db(), customer_id)
        except ValueError as exc:
            return jsonify(error=str(exc)), 404
        return jsonify(**defaults)

    @app.get("/api/customer-master/order-snapshots/<order_record_id>")
    @role_required(*READ_ROLES)
    def customer_master_order_snapshot(order_record_id):
        row = get_db().execute(
            "SELECT * FROM customer_order_terms_snapshots WHERE order_record_id=?",
            (order_record_id,),
        ).fetchone()
        if not row:
            return jsonify(snapshot=None)
        snapshot = dict(row)
        snapshot["payment_terms"] = json.loads(snapshot.pop("payment_terms_json") or "{}")
        snapshot["product_terms"] = json.loads(snapshot.pop("product_terms_json") or "[]")
        return jsonify(snapshot=snapshot)

    @app.get("/api/customer-master")
    @role_required(*READ_ROLES)
    def customer_master_list():
        db = get_db()
        clauses, params = ["1=1"], []
        source = _clean(request.args.get("source"), 30)
        status = _clean(request.args.get("status"), 30)
        region = _clean(request.args.get("region"), 80)
        relationship = _clean(request.args.get("relationship"), 30)
        business_stage = _clean(request.args.get("business_stage"), 40)
        maturity = _clean(request.args.get("master_maturity"), 40)
        role_code = _clean(request.args.get("organization_role"), 40)
        search = _clean(request.args.get("q"), 200)
        if source:
            clauses.append("c.source_type=?"); params.append(source)
        if status:
            clauses.append("c.lifecycle_status=?"); params.append(status)
        if region:
            clauses.append("c.sales_region=?"); params.append(region)
        if relationship:
            clauses.append("c.relationship_type=?"); params.append(relationship)
        if business_stage:
            clauses.append("c.business_stage=?"); params.append(business_stage)
        if maturity:
            clauses.append("c.master_maturity=?"); params.append(maturity)
        if role_code:
            clauses.append("EXISTS (SELECT 1 FROM customer_organization_roles cor WHERE cor.customer_id=c.id AND cor.role_code=?)")
            params.append(role_code)
        if search:
            clauses.append("(c.display_name LIKE ? OR c.erp_original_name LIKE ? OR c.customer_id LIKE ? OR COALESCE(c.erp_partner_code,'') LIKE ?)")
            params.extend([f"%{search}%"] * 4)
        rows = db.execute(
            """SELECT c.*, p.display_name AS primary_owner_name, s.display_name AS secondary_owner_name,
                      COALESCE(m.shipment_count,0) AS shipment_count,m.first_ship_date,m.last_ship_date,
                      COALESCE(m.current_year_sales_krw,0) AS current_year_sales_krw,
                      COALESCE(m.previous_year_sales_krw,0) AS previous_year_sales_krw,
                      COALESCE(m.cumulative_sales_krw,0) AS cumulative_sales_krw,
                      m.average_order_cycle_days,m.next_expected_order_date,
                      (SELECT COALESCE(cc.contract_status_code,cc.contract_status) FROM customer_contracts cc
                       WHERE cc.customer_id=c.id AND cc.deleted_at IS NULL
                       ORDER BY COALESCE(cc.end_date,'9999-12-31') DESC,cc.created_at DESC LIMIT 1)
                        AS contract_status,
                      (SELECT cc.end_date FROM customer_contracts cc
                       WHERE cc.customer_id=c.id AND cc.deleted_at IS NULL
                       ORDER BY COALESCE(cc.end_date,'9999-12-31') DESC,cc.created_at DESC LIMIT 1)
                        AS contract_end_date,
                      COALESCE((SELECT SUM(sp.applied_amount) FROM customer_sales_plans sp
                       WHERE sp.customer_id=c.id AND sp.deleted_at IS NULL
                         AND sp.plan_year=CAST(strftime('%Y','now') AS INTEGER)),0) AS current_year_plan,
                      (SELECT cm.meeting_date FROM customer_meetings cm
                       WHERE cm.customer_id=c.id AND cm.deleted_at IS NULL
                       ORDER BY COALESCE(cm.meeting_date,'') DESC,cm.created_at DESC LIMIT 1)
                        AS latest_meeting_date,
                      (SELECT cm.issue_text FROM customer_meetings cm
                       WHERE cm.customer_id=c.id AND cm.deleted_at IS NULL
                       ORDER BY COALESCE(cm.meeting_date,'') DESC,cm.created_at DESC LIMIT 1)
                        AS latest_issue
               FROM customer_master c
               LEFT JOIN users p ON p.id=c.primary_owner_id
               LEFT JOIN users s ON s.id=c.secondary_owner_id
               LEFT JOIN customer_erp_metrics m ON m.customer_id=c.id
               WHERE """ + " AND ".join(clauses) + " ORDER BY CASE WHEN c.lifecycle_status='active' THEN 0 ELSE 1 END,c.sales_region,c.display_name COLLATE NOCASE",
            params,
        ).fetchall()
        customers = []
        for row in rows:
            item = _decorate_customer_policy(db, row)
            from commercial_context import _contract_badge
            latest_contract = db.execute(
                """SELECT * FROM customer_contracts WHERE customer_id=? AND deleted_at IS NULL
                   ORDER BY COALESCE(extension_end_date,end_date,'9999-12-31') DESC,created_at DESC LIMIT 1""",
                (row["id"],),
            ).fetchone()
            item["contract_badge"] = _contract_badge(dict(latest_contract)) if latest_contract else None
            if latest_contract and latest_contract["commercial_status_code"]:
                item["contract_status"] = latest_contract["commercial_status_code"]
                item["contract_end_date"] = latest_contract["extension_end_date"] if latest_contract["commercial_status_code"] == "extended" else latest_contract["end_date"]
            item["commercial_items"] = [dict(value) for value in db.execute(
                """SELECT ci.interim_product_code,ci.business_unit FROM customer_items ci
                   WHERE ci.customer_id=? AND ci.deleted_at IS NULL ORDER BY ci.business_unit,ci.created_at""",
                (row["id"],),
            ).fetchall()]
            item["sales_countries"] = [dict(r) for r in db.execute("SELECT country_code,country_name,sales_region,is_primary FROM customer_sales_countries WHERE customer_id=? ORDER BY is_primary DESC,country_name", (row["id"],))]
            item["completion"] = _completion(db, row["id"])
            plan = _number(item.get("current_year_plan"))
            item["plan_achievement_rate"] = round(
                _number(item.get("current_year_sales_krw")) / plan * 100, 1
            ) if plan > 0 else None
            if item.get("contract_end_date"):
                item["contract_days_remaining"] = (
                    date.fromisoformat(item["contract_end_date"]) - date.today()
                ).days
            else:
                item["contract_days_remaining"] = None
            item["can_edit"] = _can_edit(row)
            customers.append(item)
        latest_sync = _row(db.execute("SELECT * FROM customer_sync_runs ORDER BY id DESC LIMIT 1").fetchone())
        review_count = db.execute("SELECT COUNT(*) AS count FROM customer_sync_review_items WHERE status='open'").fetchone()["count"]
        return jsonify(customers=customers, latest_sync=latest_sync, open_review_count=review_count,
                       customer_review_count=sum(1 for item in customers if item["review_required"]),
                       definitions={"erp_code":"trCd", "erp_name":"attrNm", "export_filter":"mapFgNm + soFgNm", "country":"areaCd + areaNm"})

    @app.get("/api/customer-master/review-queue")
    @role_required(*READ_ROLES)
    def customer_master_review_queue():
        db = get_db()
        rows = db.execute(
            """SELECT id,customer_id,display_name,source_type,relationship_type,customer_role,
                      business_stage,business_stage_review_status,master_maturity,
                      master_maturity_review_status,organization_role_review_status
               FROM customer_master ORDER BY display_name COLLATE NOCASE"""
        ).fetchall()
        items = []
        for row in rows:
            item = _decorate_customer_policy(db, row)
            if item["review_required"]:
                items.append(item)
        return jsonify(items=items, total=len(items), auto_classified=0)

    @app.get("/api/customer-master/<customer_id>")
    @role_required(*READ_ROLES)
    def customer_master_detail(customer_id):
        db = get_db()
        customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            return jsonify(error="거래처를 찾을 수 없습니다."), 404
        result = _decorate_customer_policy(db, customer)
        result["sales_countries"] = [dict(r) for r in db.execute("SELECT * FROM customer_sales_countries WHERE customer_id=?", (customer_id,))]
        result["metrics"] = _row(db.execute("SELECT * FROM customer_erp_metrics WHERE customer_id=?", (customer_id,)).fetchone())
        result["completion"] = _completion(db, customer_id)
        result["can_edit"] = _can_edit(customer)
        for kind, (table, _fields) in DETAIL_TABLES.items():
            result[kind.replace("-", "_")] = [dict(row) for row in db.execute(f"SELECT * FROM {table} WHERE customer_id=? AND deleted_at IS NULL ORDER BY created_at DESC", (customer_id,))]
        result["contracts"] = [
            _decorate_contract(db, contract, country_catalog)
            for contract in result.get("contracts", [])
        ]
        projects = result.get("odm_projects", [])
        for project in projects:
            project["supply_countries"] = [dict(row) for row in db.execute("SELECT * FROM customer_odm_supply_countries WHERE project_id=? AND deleted_at IS NULL", (project["id"],))]
        result["promotions"] = [dict(row) | {"payload": _payload(row["payload_json"])} for row in db.execute("SELECT * FROM records WHERE entity_type='promotion' AND deleted_at IS NULL AND json_extract(payload_json,'$.account_id') IN (?,?) ORDER BY updated_at DESC", (customer["source_record_id"] or "", customer_id))]
        result["major_tasks"] = [dict(row) for row in db.execute(
            """SELECT t.id,t.title,t.status,t.final_rag,t.current_target_date,t.hard_deadline_date,
                      t.next_action,u.display_name AS owner_name
               FROM major_tasks t LEFT JOIN users u ON u.id=t.owner_id
               WHERE t.customer_master_id=? AND t.status NOT IN ('completed','cancelled') AND t.archived_at IS NULL
               ORDER BY CASE t.final_rag WHEN 'red' THEN 0 WHEN 'amber' THEN 1 ELSE 2 END,
                        COALESCE(t.hard_deadline_date,t.current_target_date,'9999-12-31')""",
            (customer_id,),
        )]
        result["recent_shipments"] = [dict(row) for row in db.execute("SELECT ship_date,issue_no,product_code,product_name,quantity,currency,foreign_amount,krw_supply FROM shipments WHERE partner_code=? AND is_overseas=1 ORDER BY ship_date DESC,id DESC LIMIT 30", (customer["erp_partner_code"] or "",))]
        result["audit"] = [dict(row) for row in db.execute("SELECT * FROM audit_logs WHERE entity_type='customer_master' AND entity_id=? ORDER BY occurred_at DESC LIMIT 100", (customer_id,))]
        today = date.today()
        alerts = []
        for contract in result.get("contracts", []):
            if contract.get("end_date"):
                days = (date.fromisoformat(contract["end_date"]) - today).days
                if days in range(0, 61):
                    alerts.append({"type": "contract", "days": days,
                                   "message": f"계약 {contract.get('contract_no') or ''} 종료까지 {days}일"})
        for registration in result.get("registrations", []):
            if registration.get("valid_to"):
                days = (date.fromisoformat(registration["valid_to"]) - today).days
                if days in range(0, 61):
                    alerts.append({"type": "registration", "days": days,
                                   "message": f"{registration.get('product_name') or '제품'} 인허가 만료까지 {days}일"})
        result["alerts"] = sorted(alerts, key=lambda item: item["days"])
        return jsonify(customer=result)

    @app.post("/api/customer-master")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_master_create():
        db = get_db(); data = request.get_json(silent=True) or {}
        from commercial_context import (
            replace_customer_items,
            validate_contract_policy,
            validate_customer_item_scope,
        )
        try:
            policy_values = _validate_master_policy(data)
            validate_customer_item_scope(data.get("item_codes") or [], data.get("business_units") or [])
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        relationship = _clean(data.get("relationship_type"), 30) or "dealer"
        if relationship not in RELATIONSHIP_TYPES:
            return jsonify(error="거래관계가 올바르지 않습니다."), 400
        display_name = _clean(data.get("display_name"), 300)
        if not display_name:
            return jsonify(error="화면 표시용 거래처명을 입력하세요."), 400
        country = _clean(data.get("headquarters_country"), 120)
        resolved = country_resolver(country) if country and country_resolver else None
        if country and not resolved:
            return jsonify(error="소재국가는 표준 국가목록에서 선택하세요."), 400
        duplicate = db.execute(
            """SELECT id,customer_id,display_name,headquarters_country,lifecycle_status
               FROM customer_master
               WHERE lower(trim(display_name))=lower(trim(?))
                 AND lower(trim(headquarters_country))=lower(trim(?))
               LIMIT 1""",
            (display_name, country),
        ).fetchone()
        if duplicate:
            return jsonify(
                error="같은 거래처명과 국가의 거래처가 이미 있습니다. 기존 거래처를 선택하세요.",
                existing_customer=dict(duplicate),
            ), 409
        primary_owner_id = data.get("primary_owner_id") or None
        if primary_owner_id is not None and not db.execute(
            "SELECT 1 FROM users WHERE id=? AND status='active' AND deleted_at IS NULL",
            (primary_owner_id,),
        ).fetchone():
            return jsonify(error="활성 사용자만 주 담당자로 선택할 수 있습니다."), 400
        erp_code = _valid_erp_code(data.get("erp_partner_code"))
        if data.get("erp_partner_code") and not erp_code:
            return jsonify(error="ERP 거래처 코드는 숫자 코드만 입력할 수 있습니다. 코드가 없으면 비워두세요."), 400
        if erp_code and db.execute("SELECT 1 FROM customer_master WHERE erp_partner_code=?", (erp_code,)).fetchone():
            return jsonify(error="이미 연결된 ERP 거래처 코드입니다."), 409
        master_id = _uuid(); now = _now()
        customer_public_id = erp_code or _next_temp_customer_id(db, relationship)
        db.execute(
            """INSERT INTO customer_master
               (id,customer_id,erp_partner_code,erp_original_name,display_name,legal_name_en,
                headquarters_country,country_code,sales_region,source_type,relationship_type,
                customer_role,primary_owner_id,secondary_owner_id,lifecycle_status,default_currency,
                preferred_language,timezone_name,website,address,notes,data_steward_id,
                created_by,updated_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (master_id, customer_public_id, erp_code or None, _clean(data.get("erp_original_name"), 300),
             display_name, _clean(data.get("legal_name_en"), 300), country,
             (resolved or {}).get("map_id"), _clean(data.get("sales_region"), 80) or _sales_region((resolved or {}).get("map_id")),
             "manual" if erp_code else "temporary", relationship, _clean(data.get("customer_role"), 100) or "Distributor",
             primary_owner_id, data.get("secondary_owner_id") or None,
             "active", _clean(data.get("default_currency"), 8) or "USD",
             _clean(data.get("preferred_language"), 80), _clean(data.get("timezone_name"), 100),
             _clean(data.get("website"), 500), _clean(data.get("address"), 1000), _clean(data.get("notes"), 4000),
             data.get("data_steward_id") or None, g.current_user["id"], g.current_user["id"], now, now),
        )
        if policy_values:
            db.execute(
                "UPDATE customer_master SET " + ",".join(f"{key}=?" for key in policy_values) + " WHERE id=?",
                [*policy_values.values(), master_id],
            )
        try:
            _replace_policy_relations(db, master_id, data, g.current_user["id"], now)
            if "contract_policy" in data:
                contract_policy = validate_contract_policy(data.get("contract_policy"), allow_none=True)
                db.execute(
                    """UPDATE customer_master SET contract_policy=?,contract_policy_reviewed_by=?,
                       contract_policy_reviewed_at=? WHERE id=?""",
                    (contract_policy, g.current_user["id"] if contract_policy else None,
                     now if contract_policy else None, master_id),
                )
            if "item_codes" in data:
                replace_customer_items(db, master_id, data.get("item_codes") or [], g.current_user["id"], now)
        except ValueError as exc:
            db.rollback()
            return jsonify(error=str(exc)), 400
        if "business_area_details" not in data:
            for unit in data.get("business_units") or []:
                if unit in BUSINESS_UNITS:
                    db.execute("INSERT INTO customer_business_areas VALUES (?,?,?)", (master_id, unit, now))
        after = _decorate_customer_policy(db, db.execute("SELECT * FROM customer_master WHERE id=?", (master_id,)).fetchone())
        audit_fn("CUSTOMER_CREATE", "customer_master", master_id, f"{display_name} 거래처 등록", None, after)
        db.commit()
        return jsonify(message="거래처가 등록되었습니다.", customer=after), 201

    @app.patch("/api/customer-master/<customer_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_master_update(customer_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        from commercial_context import (
            replace_customer_items,
            validate_contract_policy,
            validate_customer_item_scope,
        )
        customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer):
            return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        expected_version = data.get("expected_version")
        if expected_version is not None:
            try:
                expected_version = int(expected_version)
            except (TypeError, ValueError):
                return jsonify(error="거래처 버전 정보가 올바르지 않습니다.", field="expected_version"), 400
            if expected_version != int(customer["version"]):
                return jsonify(
                    error="다른 사용자가 먼저 거래처 정보를 수정했습니다. 최신 내용을 다시 불러온 뒤 저장하세요.",
                    code="CUSTOMER_VERSION_CONFLICT",
                    current_version=customer["version"],
                ), 409
        before = _decorate_customer_policy(db, customer)
        before["commercial_item_codes"] = [row["interim_product_code"] for row in db.execute(
            "SELECT interim_product_code FROM customer_items WHERE customer_id=? AND deleted_at IS NULL ORDER BY interim_product_code",
            (customer_id,),
        ).fetchall()]
        try:
            policy_values = _validate_master_policy(data)
            if "item_codes" in data or "business_units" in data:
                proposed_items = data.get("item_codes") if "item_codes" in data else before["commercial_item_codes"]
                proposed_units = data.get("business_units") if "business_units" in data else before.get("business_units", [])
                validate_customer_item_scope(proposed_items or [], proposed_units or [])
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        allowed = {"display_name", "legal_name_en", "headquarters_country", "sales_region", "relationship_type", "customer_role", "primary_owner_id", "secondary_owner_id", "default_currency", "preferred_language", "timezone_name", "website", "address", "first_transaction_date", "last_information_reviewed_at", "data_steward_id", "notes"}
        values = {}
        for field in allowed:
            if field not in data: continue
            if field in {"first_transaction_date", "last_information_reviewed_at"}:
                values[field] = _iso_date(data.get(field), field)
            elif field.endswith("_id"):
                values[field] = data.get(field) or None
            else:
                values[field] = _clean(data.get(field), 4000 if field == "notes" else 1000)
        if "display_name" in values and not values["display_name"]:
            return jsonify(error="화면 표시용 거래처명을 입력하세요."), 400
        if values.get("relationship_type") and values["relationship_type"] not in RELATIONSHIP_TYPES:
            return jsonify(error="거래관계가 올바르지 않습니다."), 400
        if "headquarters_country" in values:
            resolved = country_resolver(values["headquarters_country"]) if values["headquarters_country"] and country_resolver else None
            if values["headquarters_country"] and not resolved:
                return jsonify(error="소재국가는 표준 국가목록에서 선택하세요."), 400
            values["country_code"] = (resolved or {}).get("map_id")
            if "sales_region" not in values:
                values["sales_region"] = _sales_region(values["country_code"])
        values.update(policy_values)
        if "contract_policy" in data:
            contract_policy = validate_contract_policy(data.get("contract_policy"), allow_none=True)
            values.update({
                "contract_policy": contract_policy,
                "contract_policy_reviewed_by": g.current_user["id"] if contract_policy else None,
                "contract_policy_reviewed_at": _now() if contract_policy else None,
            })
        values.update({"updated_by": g.current_user["id"], "updated_at": _now()})
        assignments = ",".join(f"{key}=?" for key in values) + ",version=version+1"
        params = [*values.values(), customer_id]
        where = "id=?"
        if expected_version is not None:
            where += " AND version=?"
            params.append(expected_version)
        changed = db.execute(f"UPDATE customer_master SET {assignments} WHERE {where}", params)
        if changed.rowcount != 1:
            db.rollback()
            return jsonify(
                error="다른 사용자가 먼저 거래처 정보를 수정했습니다. 최신 내용을 다시 불러온 뒤 저장하세요.",
                code="CUSTOMER_VERSION_CONFLICT",
            ), 409
        try:
            _replace_policy_relations(db, customer_id, data, g.current_user["id"], values["updated_at"])
            if "item_codes" in data:
                replace_customer_items(db, customer_id, data.get("item_codes") or [], g.current_user["id"], values["updated_at"])
        except ValueError as exc:
            db.rollback()
            return jsonify(error=str(exc)), 400
        if "business_units" in data and "business_area_details" not in data:
            db.execute("DELETE FROM customer_business_areas WHERE customer_id=?", (customer_id,))
            for unit in data.get("business_units") or []:
                if unit in BUSINESS_UNITS:
                    db.execute("INSERT INTO customer_business_areas VALUES (?,?,?)", (customer_id, unit, _now()))
        after = _decorate_customer_policy(db, db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone())
        after["commercial_item_codes"] = [row["interim_product_code"] for row in db.execute(
            "SELECT interim_product_code FROM customer_items WHERE customer_id=? AND deleted_at IS NULL ORDER BY interim_product_code",
            (customer_id,),
        ).fetchall()]
        audit_fn("CUSTOMER_UPDATE", "customer_master", customer_id, f"{after['display_name']} 거래처 수정", before, after)
        db.commit()
        return jsonify(message="거래처 정보가 저장되었습니다.", customer=after)

    @app.post("/api/customer-master/<customer_id>/deactivate")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_master_deactivate(customer_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        reason = _clean(data.get("inactive_reason"), 2000)
        if not reason: return jsonify(error="거래중단 사유를 입력하세요."), 400
        before = dict(customer); now = _now()
        db.execute("""UPDATE customer_master SET lifecycle_status='ended',business_stage='discontinued',
                     business_stage_review_status='confirmed',business_stage_reviewed_by=?,business_stage_reviewed_at=?,
                     inactive_date=?,inactive_reason=?,restart_probability=?,review_date=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
                   (g.current_user["id"], now,
                    _iso_date(data.get("inactive_date"), "거래중단일") or now[:10], reason,
                    _clean(data.get("restart_probability"), 100), _iso_date(data.get("review_date"), "재검토 예정일"),
                    g.current_user["id"], now, customer_id))
        after = _decorate_customer_policy(db, db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone())
        audit_fn("CUSTOMER_DEACTIVATE", "customer_master", customer_id, f"{customer['display_name']} 거래중단", before, after)
        db.commit(); return jsonify(message="거래중단 상태로 이동했습니다.", customer=after)

    @app.post("/api/customer-master/<customer_id>/restore")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_master_restore(customer_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        reason = _clean(data.get("restore_reason"), 2000)
        if not reason: return jsonify(error="복원 사유를 입력하세요."), 400
        stage = _clean(data.get("business_stage"), 40) or None
        if stage == "discontinued" or (stage and stage not in CUSTOMER_STAGES):
            return jsonify(error="복원 후 업무단계를 신규후보, 정규후보, 정규 중에서 선택하세요."), 400
        before = dict(customer); now = _now()
        db.execute("""UPDATE customer_master SET lifecycle_status='active',business_stage=?,
                     business_stage_review_status=?,business_stage_reviewed_by=?,business_stage_reviewed_at=?,
                     restored_at=?,restore_reason=?,updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
                   (stage, "confirmed" if stage else "review_required",
                    g.current_user["id"] if stage else None, now if stage else None,
                    now, reason, g.current_user["id"], now, customer_id))
        after = _decorate_customer_policy(db, db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone())
        audit_fn("CUSTOMER_RESTORE", "customer_master", customer_id, f"{customer['display_name']} 거래 복원", before, after)
        db.commit(); return jsonify(message="활성 거래처로 복원했습니다.", customer=after)

    @app.post("/api/customer-master/sync")
    @role_required("admin", "manager")
    @csrf_required
    def customer_master_sync():
        result = _sync_from_shipments(get_db(), g.current_user["id"], country_resolver, audit_fn)
        return jsonify(message="현재 ERP 출고 원장에서 거래처를 코드 기준으로 동기화했습니다.", sync=result)

    @app.get("/api/customer-master/sync-history")
    @role_required(*READ_ROLES)
    def customer_master_sync_history():
        db = get_db()
        runs = [dict(row) for row in db.execute("SELECT * FROM customer_sync_runs ORDER BY id DESC LIMIT 50")]
        reviews = [dict(row) for row in db.execute("SELECT * FROM customer_sync_review_items WHERE status='open' ORDER BY created_at DESC LIMIT 300")]
        for item in reviews:
            item["candidate_customer_ids"] = json.loads(item.pop("candidate_customer_ids_json") or "[]")
        return jsonify(runs=runs, reviews=reviews)

    @app.post("/api/customer-master/<customer_id>/link-erp")
    @role_required("admin", "manager")
    @csrf_required
    def customer_master_link_erp(customer_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        code = _valid_erp_code(data.get("erp_partner_code"))
        if not code: return jsonify(error="연결할 ERP 숫자 코드를 입력하세요."), 400
        conflict = db.execute("SELECT id,display_name FROM customer_master WHERE erp_partner_code=? AND id<>?", (code, customer_id)).fetchone()
        if conflict: return jsonify(error=f"이미 {conflict['display_name']} 거래처에 연결된 ERP 코드입니다."), 409
        source = db.execute("SELECT * FROM shipments WHERE partner_code=? AND is_overseas=1 ORDER BY ship_date DESC,id DESC LIMIT 1", (code,)).fetchone()
        if not source: return jsonify(error="현재 ERP 출고 원장에서 해당 코드를 찾을 수 없습니다."), 400
        if not data.get("confirmed"): return jsonify(error="비교 확인 후 연결 확정이 필요합니다."), 400
        before = dict(customer); now = _now()
        erp_country_code, erp_country_name = _country_from_shipment(dict(source), country_resolver)
        db.execute("""UPDATE customer_master SET customer_id=?,erp_partner_code=?,erp_original_name=?,
                   erp_country_code=?,erp_country_name=?,source_type='erp',
                   headquarters_country=CASE WHEN headquarters_country='' THEN ? ELSE headquarters_country END,
                   country_code=COALESCE(country_code,?),updated_by=?,updated_at=?,version=version+1 WHERE id=?""",
                   (code, code, source["partner_name"], erp_country_code, erp_country_name,
                    erp_country_name, erp_country_code, g.current_user["id"], now, customer_id))
        db.execute("""INSERT INTO customer_erp_link_history(id,customer_id,previous_erp_code,new_erp_code,comparison_json,confirmed_by,confirmed_at) VALUES (?,?,?,?,?,?,?)""",
                   (_uuid(), customer_id, customer["erp_partner_code"], code, _json(data.get("comparison") or {}), g.current_user["id"], now))
        after = _row(db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone())
        audit_fn("CUSTOMER_ERP_LINK", "customer_master", customer_id, f"{customer['display_name']} ERP 코드 {code} 연결", before, after)
        db.commit(); return jsonify(message="기존 거래처에 ERP 코드를 연결했습니다. 관련 이력과 내부 UUID는 유지됩니다.", customer=after)

    @app.post("/api/customer-master/reviews/<review_id>/resolve")
    @role_required("admin", "manager")
    @csrf_required
    def customer_master_review_resolve(review_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        item = db.execute("SELECT * FROM customer_sync_review_items WHERE id=? AND status='open'", (review_id,)).fetchone()
        if not item: return jsonify(error="열린 검토항목을 찾을 수 없습니다."), 404
        note = _clean(data.get("resolution_note"), 2000)
        if not note: return jsonify(error="처리 결과를 입력하세요."), 400
        db.execute("UPDATE customer_sync_review_items SET status='resolved',resolution_note=?,resolved_by=?,resolved_at=? WHERE id=?",
                   (note, g.current_user["id"], _now(), review_id))
        audit_fn("CUSTOMER_REVIEW_RESOLVE", "customer_master", item["erp_partner_code"] or item["external_key"], "거래처 동기화 검토항목 처리", dict(item), {"resolution_note": note})
        db.commit(); return jsonify(message="검토항목을 처리했습니다.")

    @app.post("/api/customer-master/<customer_id>/sales-countries")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_sales_country_create(customer_id):
        db = get_db(); data = request.get_json(silent=True) or {}
        customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        country_name = _clean(data.get("country_name"), 120)
        resolved = country_resolver(country_name) if country_name and country_resolver else None
        if not resolved: return jsonify(error="판매 담당국가를 확인할 수 없습니다."), 400
        row_id = _uuid(); now = _now(); is_primary = int(bool(data.get("is_primary")))
        if is_primary:
            db.execute("UPDATE customer_sales_countries SET is_primary=0 WHERE customer_id=?", (customer_id,))
        try:
            db.execute(
                """INSERT INTO customer_sales_countries
                   (id,customer_id,country_code,country_name,sales_region,is_primary,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (row_id, customer_id, resolved["map_id"], resolved["name"],
                 _sales_region(resolved["map_id"]), is_primary, now),
            )
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                return jsonify(error="이미 등록된 판매 담당국가입니다."), 409
            raise
        audit_fn("CUSTOMER_SALES_COUNTRY_CREATE", "customer_master", customer_id,
                 f"{customer['display_name']} 판매 담당국가 {resolved['name']} 등록", None,
                 {"country_code": resolved["map_id"], "country_name": resolved["name"]})
        db.commit(); return jsonify(message="판매 담당국가를 등록했습니다."), 201

    @app.delete("/api/customer-master/<customer_id>/sales-countries/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_sales_country_delete(customer_id, row_id):
        db = get_db(); customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        existing = db.execute("SELECT * FROM customer_sales_countries WHERE id=? AND customer_id=?", (row_id, customer_id)).fetchone()
        if not existing: return jsonify(error="판매 담당국가를 찾을 수 없습니다."), 404
        db.execute("DELETE FROM customer_sales_countries WHERE id=?", (row_id,))
        audit_fn("CUSTOMER_SALES_COUNTRY_DELETE", "customer_master", customer_id,
                 f"{customer['display_name']} 판매 담당국가 {existing['country_name']} 종료", dict(existing), None)
        db.commit(); return jsonify(message="판매 담당국가를 목록에서 제외했습니다.")

    @app.post("/api/customer-master/<customer_id>/details/<kind>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_detail_create(customer_id, kind):
        if kind not in DETAIL_TABLES: return jsonify(error="지원하지 않는 상세정보 유형입니다."), 404
        db = get_db(); customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        data = request.get_json(silent=True) or {}
        try:
            values = _normalize_detail(kind, data, country_resolver)
            relation_values = _normalize_contract_relations(data, country_catalog) if kind == "contracts" else {}
            _validate_detail_state(kind, {}, values)
        except ValueError as exc:
            return _validation_error(exc)
        table, _fields = DETAIL_TABLES[kind]; row_id = _uuid(); now = _mutation_now()
        if kind == "contracts":
            normalization = _contract_normalization_status({}, values, relation_values, {})
            if normalization:
                values["normalization_status"] = normalization
        values.update({"id": row_id, "customer_id": customer_id, "created_by": g.current_user["id"], "updated_by": g.current_user["id"], "created_at": now, "updated_at": now})
        columns = list(values); placeholders = ",".join("?" for _ in columns)
        db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", [values[key] for key in columns])
        if kind == "contracts":
            _replace_contract_relation_rows(db, row_id, relation_values, g.current_user["id"], now)
        created_row = db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        created = _decorate_contract(db, created_row, country_catalog) if kind == "contracts" else _row(created_row)
        audit_fn("CUSTOMER_DETAIL_CREATE", "customer_master", customer_id, f"{customer['display_name']} {kind} 등록", None, created)
        db.commit(); return jsonify(message="상세정보를 등록했습니다.", item=created), 201

    @app.patch("/api/customer-master/<customer_id>/details/<kind>/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_detail_update(customer_id, kind, row_id):
        if kind not in DETAIL_TABLES: return jsonify(error="지원하지 않는 상세정보 유형입니다."), 404
        db = get_db(); customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        table, _fields = DETAIL_TABLES[kind]; existing = db.execute(f"SELECT * FROM {table} WHERE id=? AND customer_id=? AND deleted_at IS NULL", (row_id, customer_id)).fetchone()
        if not existing: return jsonify(error="상세정보를 찾을 수 없습니다."), 404
        data = request.get_json(silent=True) or {}
        expected_updated_at = data.get("expected_updated_at")
        if expected_updated_at is not None and expected_updated_at != existing["updated_at"]:
            return jsonify(
                error="다른 사용자가 먼저 이 정보를 수정했습니다. 최신 내용을 다시 불러온 뒤 저장하세요.",
                code="CUSTOMER_DETAIL_VERSION_CONFLICT",
                current_updated_at=existing["updated_at"],
            ), 409
        try:
            values = _normalize_detail(kind, data, country_resolver)
            relation_values = _normalize_contract_relations(data, country_catalog) if kind == "contracts" else {}
            _validate_detail_state(kind, existing, values)
        except ValueError as exc:
            return _validation_error(exc)
        current_relations = _contract_relation_values(db, row_id, country_catalog) if kind == "contracts" else {}
        if kind == "contracts":
            normalization = _contract_normalization_status(existing, values, relation_values, current_relations)
            if normalization:
                values["normalization_status"] = normalization
        now = _mutation_now()
        values.update({"updated_by": g.current_user["id"], "updated_at": now})
        params = [*values.values(), row_id]
        where = "id=?"
        if expected_updated_at is not None:
            where += " AND updated_at=?"
            params.append(expected_updated_at)
        changed = db.execute(f"UPDATE {table} SET " + ",".join(f"{key}=?" for key in values) + f" WHERE {where}", params)
        if changed.rowcount != 1:
            db.rollback()
            return jsonify(error="다른 사용자가 먼저 이 정보를 수정했습니다.", code="CUSTOMER_DETAIL_VERSION_CONFLICT"), 409
        before = _decorate_contract(db, existing, country_catalog) if kind == "contracts" else dict(existing)
        if kind == "contracts":
            _replace_contract_relation_rows(db, row_id, relation_values, g.current_user["id"], now)
        updated_row = db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        updated = _decorate_contract(db, updated_row, country_catalog) if kind == "contracts" else _row(updated_row)
        audit_fn("CUSTOMER_DETAIL_UPDATE", "customer_master", customer_id, f"{customer['display_name']} {kind} 수정", before, updated)
        db.commit(); return jsonify(message="상세정보를 수정했습니다.", item=updated)

    @app.delete("/api/customer-master/<customer_id>/details/<kind>/<row_id>")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_detail_delete(customer_id, kind, row_id):
        if kind not in DETAIL_TABLES: return jsonify(error="지원하지 않는 상세정보 유형입니다."), 404
        db = get_db(); customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        if not customer: return jsonify(error="거래처를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        table, _fields = DETAIL_TABLES[kind]; existing = db.execute(f"SELECT * FROM {table} WHERE id=? AND customer_id=? AND deleted_at IS NULL", (row_id, customer_id)).fetchone()
        if not existing: return jsonify(error="상세정보를 찾을 수 없습니다."), 404
        data = request.get_json(silent=True) or {}
        expected_updated_at = data.get("expected_updated_at")
        if expected_updated_at is not None and expected_updated_at != existing["updated_at"]:
            return jsonify(error="다른 사용자가 먼저 이 정보를 수정했습니다.", code="CUSTOMER_DETAIL_VERSION_CONFLICT"), 409
        now = _mutation_now()
        params = [now, g.current_user["id"], now, row_id]
        where = "id=?"
        if expected_updated_at is not None:
            where += " AND updated_at=?"
            params.append(expected_updated_at)
        changed = db.execute(f"UPDATE {table} SET deleted_at=?,updated_by=?,updated_at=? WHERE {where}", params)
        if changed.rowcount != 1:
            db.rollback()
            return jsonify(error="다른 사용자가 먼저 이 정보를 수정했습니다.", code="CUSTOMER_DETAIL_VERSION_CONFLICT"), 409
        before = _decorate_contract(db, existing, country_catalog) if kind == "contracts" else dict(existing)
        if kind == "contracts":
            db.execute("UPDATE customer_contract_products SET deleted_at=?,updated_by=?,updated_at=? WHERE contract_id=? AND deleted_at IS NULL", (now, g.current_user["id"], now, row_id))
            db.execute("UPDATE customer_contract_countries SET deleted_at=?,updated_by=?,updated_at=? WHERE contract_id=? AND deleted_at IS NULL", (now, g.current_user["id"], now, row_id))
        audit_fn("CUSTOMER_DETAIL_DELETE", "customer_master", customer_id, f"{customer['display_name']} {kind} 종료", before, {"deleted_at": now})
        db.commit(); return jsonify(message="상세정보를 이력 보존 상태로 종료했습니다.")

    @app.post("/api/customer-master/<customer_id>/odm-projects/<project_id>/countries")
    @role_required(*WRITE_ROLES)
    @csrf_required
    def customer_odm_country_create(customer_id, project_id):
        db = get_db(); customer = db.execute("SELECT * FROM customer_master WHERE id=?", (customer_id,)).fetchone()
        project = db.execute("SELECT * FROM customer_odm_projects WHERE id=? AND customer_id=? AND deleted_at IS NULL", (project_id, customer_id)).fetchone()
        if not customer or not project: return jsonify(error="ODM 프로젝트를 찾을 수 없습니다."), 404
        if not _can_edit(customer): return jsonify(error="이 거래처를 수정할 권한이 없습니다."), 403
        data = request.get_json(silent=True) or {}; country_name = _clean(data.get("country_name"), 120)
        resolved = country_resolver(country_name) if country_name and country_resolver else None
        if not resolved: return jsonify(error="최종 공급국가를 확인할 수 없습니다."), 400
        row_id = _uuid(); now = _now()
        db.execute("""INSERT INTO customer_odm_supply_countries
                     (id,project_id,country_code,country_name,supply_status,product_spec,expected_start_date,actual_start_date,
                      expected_quantity,expected_sales,registration_required,registration_status,owner_id,notes,
                      created_by,updated_by,created_at,updated_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (row_id, project_id, resolved["map_id"], resolved["name"], _clean(data.get("supply_status"), 40) or "planned",
                    _clean(data.get("product_spec"), 500), _iso_date(data.get("expected_start_date")), _iso_date(data.get("actual_start_date")),
                    _number(data.get("expected_quantity")), _number(data.get("expected_sales")), int(bool(data.get("registration_required"))),
                    _clean(data.get("registration_status"), 100), data.get("owner_id") or None, _clean(data.get("notes"), 2000),
                    g.current_user["id"], g.current_user["id"], now, now))
        audit_fn("CUSTOMER_ODM_COUNTRY_CREATE", "customer_master", customer_id, f"ODM 최종 공급국가 {resolved['name']} 등록", None, {"project_id": project_id, "country": resolved["name"]})
        db.commit(); return jsonify(message="ODM 최종 공급국가를 등록했습니다."), 201

    @app.get("/api/customer-master/map")
    @role_required(*READ_ROLES)
    def customer_master_map():
        db = get_db(); segment = _clean(request.args.get("segment"), 30) or "dental"
        if segment not in BUSINESS_UNITS | {"odm"}: return jsonify(error="지도 구분이 올바르지 않습니다."), 400
        if segment == "odm":
            rows = db.execute("""SELECT s.country_code,s.country_name,c.sales_region,c.id,c.display_name,c.lifecycle_status,
                              c.primary_owner_id,u.display_name AS primary_owner_name,
                              COALESCE(m.current_year_sales_krw,0) AS current_year_sales_krw,m.last_ship_date,
                              (SELECT cc.end_date FROM customer_contracts cc WHERE cc.customer_id=c.id
                               AND cc.deleted_at IS NULL ORDER BY COALESCE(cc.end_date,'9999-12-31') DESC,
                               cc.created_at DESC LIMIT 1) AS contract_end_date
                              FROM customer_odm_supply_countries s
                              JOIN customer_odm_projects p ON p.id=s.project_id AND p.deleted_at IS NULL
                              JOIN customer_master c ON c.id=p.customer_id
                              LEFT JOIN users u ON u.id=c.primary_owner_id
                              LEFT JOIN customer_erp_metrics m ON m.customer_id=c.id
                              WHERE s.deleted_at IS NULL AND s.supply_status!='ended'
                              AND (
                                EXISTS (SELECT 1 FROM customer_organization_roles cor
                                        WHERE cor.customer_id=c.id AND cor.role_code='odm')
                                OR (c.organization_role_review_status!='confirmed'
                                    AND c.relationship_type IN ('odm','dealer_odm'))
                              )""").fetchall()
        else:
            rows = db.execute("""SELECT COALESCE(sc.country_code,c.country_code) AS country_code,
                              COALESCE(sc.country_name,c.headquarters_country) AS country_name,
                              COALESCE(sc.sales_region,c.sales_region) AS sales_region,c.id,c.display_name,
                              c.lifecycle_status,c.primary_owner_id,u.display_name AS primary_owner_name,
                              COALESCE(m.current_year_sales_krw,0) AS current_year_sales_krw,m.last_ship_date,
                              (SELECT cc.end_date FROM customer_contracts cc WHERE cc.customer_id=c.id
                               AND cc.deleted_at IS NULL ORDER BY COALESCE(cc.end_date,'9999-12-31') DESC,
                               cc.created_at DESC LIMIT 1) AS contract_end_date
                              FROM customer_master c JOIN customer_business_areas b ON b.customer_id=c.id AND b.business_unit=?
                              LEFT JOIN customer_sales_countries sc ON sc.customer_id=c.id
                              LEFT JOIN users u ON u.id=c.primary_owner_id
                              LEFT JOIN customer_erp_metrics m ON m.customer_id=c.id
                              WHERE (
                                EXISTS (SELECT 1 FROM customer_organization_roles cor
                                        WHERE cor.customer_id=c.id AND cor.role_code='distributor')
                                OR (c.organization_role_review_status!='confirmed'
                                    AND c.relationship_type IN ('dealer','dealer_odm'))
                              )""", (segment,)).fetchall()
        grouped = defaultdict(lambda: {"active_count": 0, "inactive_count": 0, "customers": [], "current_year_sales_krw": 0})
        for row in rows:
            code = row["country_code"] or ""; item = grouped[code]
            item["country_code"] = code; item["country_name"] = row["country_name"] or "미분류"
            item["sales_region"] = row["sales_region"] or _sales_region(code)
            active = row["lifecycle_status"] == "active"
            item["active_count" if active else "inactive_count"] += 1
            if active:
                item["current_year_sales_krw"] += _number(row["current_year_sales_krw"])
            item["customers"].append({
                "id": row["id"], "display_name": row["display_name"],
                "lifecycle_status": row["lifecycle_status"],
                "primary_owner_name": row["primary_owner_name"] or "미지정",
                "current_year_sales_krw": _number(row["current_year_sales_krw"]),
                "last_ship_date": row["last_ship_date"],
                "contract_end_date": row["contract_end_date"],
            })
        return jsonify(segment=segment, countries=list(grouped.values()))
