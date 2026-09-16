"""Idempotent, additive Customer policy schema for existing SQLite releases."""

from __future__ import annotations


CUSTOMER_POLICY_SCHEMA_VERSION = "customer-master-operability-2026-09-14-v1"


INTERIM_PRODUCT_CODES_SQL = (
    "'medpark_bovine_s1','boss','colla','a1_oss','medpark_allo_medical',"
    "'medpark_allo_dental','s_derm','s_gen','s_gen_inject','adite',"
    "'a1_bonechip','a1_dbm'"
)


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_columns(db, table, definitions):
    existing = _columns(db, table)
    for name, definition in definitions.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def apply_customer_policy_schema(db):
    """Add policy fields/tables without classifying or rewriting existing rows."""
    _add_columns(db, "customer_master", {
        "business_stage": "TEXT CHECK(business_stage IS NULL OR business_stage IN ('new_prospect','regular_candidate','regular','discontinued'))",
        "business_stage_review_status": "TEXT NOT NULL DEFAULT 'review_required' CHECK(business_stage_review_status IN ('review_required','confirmed'))",
        "business_stage_reviewed_by": "INTEGER",
        "business_stage_reviewed_at": "TEXT",
        "master_maturity": "TEXT CHECK(master_maturity IS NULL OR master_maturity IN ('temporary','formal'))",
        "master_maturity_review_status": "TEXT NOT NULL DEFAULT 'review_required' CHECK(master_maturity_review_status IN ('review_required','confirmed'))",
        "master_maturity_reviewed_by": "INTEGER",
        "master_maturity_reviewed_at": "TEXT",
        "organization_role_review_status": "TEXT NOT NULL DEFAULT 'review_required' CHECK(organization_role_review_status IN ('review_required','confirmed'))",
        "organization_role_reviewed_by": "INTEGER",
        "organization_role_reviewed_at": "TEXT",
    })
    _add_columns(db, "customer_payment_terms", {
        "payment_method_code": "TEXT CHECK(payment_method_code IS NULL OR payment_method_code IN ('tt','lc','other'))",
        "payment_method_other": "TEXT NOT NULL DEFAULT ''",
        "payment_schedule_json": "TEXT NOT NULL DEFAULT '[]'",
        "normalization_status": "TEXT NOT NULL DEFAULT 'review_required' CHECK(normalization_status IN ('review_required','confirmed'))",
    })
    _add_columns(db, "customer_logistics", {
        "customs_broker": "TEXT NOT NULL DEFAULT ''",
        "courier_code": "TEXT CHECK(courier_code IS NULL OR courier_code IN ('dhl','fedex','ups','ems','tnt'))",
        "requires_import_invoice": "INTEGER NOT NULL DEFAULT 0",
        "requires_additional_documents": "INTEGER NOT NULL DEFAULT 0",
        "additional_documents_json": "TEXT NOT NULL DEFAULT '[]'",
        "additional_documents_note": "TEXT NOT NULL DEFAULT ''",
        "customs_invoice_notes": "TEXT NOT NULL DEFAULT ''",
        "normalization_status": "TEXT NOT NULL DEFAULT 'review_required' CHECK(normalization_status IN ('review_required','confirmed'))",
    })
    _add_columns(db, "customer_contacts", {
        "language_code": "TEXT CHECK(language_code IS NULL OR language_code IN ('en','ar','zh','ja','es','pt','ru','hi','fr','de'))",
    })
    _add_columns(db, "customer_contracts", {
        "contract_name": "TEXT NOT NULL DEFAULT ''",
        "contract_status_code": "TEXT CHECK(contract_status_code IS NULL OR contract_status_code IN ('draft','active','suspended','expired','terminated'))",
        "normalization_status": "TEXT NOT NULL DEFAULT 'review_required' CHECK(normalization_status IN ('review_required','confirmed'))",
    })
    _add_columns(db, "customer_product_terms", {
        "interim_product_code": f"TEXT CHECK(interim_product_code IS NULL OR interim_product_code IN ({INTERIM_PRODUCT_CODES_SQL}))",
    })
    db.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS customer_organization_roles (
          customer_id TEXT NOT NULL,
          role_code TEXT NOT NULL CHECK(role_code IN ('distributor','odm','clinic_hospital','kol','other')),
          provenance TEXT NOT NULL DEFAULT 'user_confirmed',
          created_by INTEGER,
          created_at TEXT NOT NULL,
          PRIMARY KEY(customer_id, role_code),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_customer_organization_roles_role
          ON customer_organization_roles(role_code, customer_id);

        CREATE TABLE IF NOT EXISTS customer_business_area_details (
          customer_id TEXT NOT NULL,
          detail_code TEXT NOT NULL CHECK(detail_code IN ('medical_os','medical_ns')),
          parent_business_unit TEXT NOT NULL DEFAULT 'medical' CHECK(parent_business_unit='medical'),
          provenance TEXT NOT NULL DEFAULT 'user_confirmed',
          created_by INTEGER,
          created_at TEXT NOT NULL,
          PRIMARY KEY(customer_id, detail_code),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS customer_languages (
          customer_id TEXT NOT NULL,
          language_code TEXT NOT NULL CHECK(language_code IN ('en','ar','zh','ja','es','pt','ru','hi','fr','de')),
          is_primary INTEGER NOT NULL DEFAULT 0,
          created_by INTEGER,
          created_at TEXT NOT NULL,
          PRIMARY KEY(customer_id, language_code),
          FOREIGN KEY(customer_id) REFERENCES customer_master(id) ON DELETE CASCADE,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_languages_primary
          ON customer_languages(customer_id) WHERE is_primary=1;

        CREATE INDEX IF NOT EXISTS idx_customer_master_business_stage
          ON customer_master(business_stage, business_stage_review_status, lifecycle_status);
        CREATE INDEX IF NOT EXISTS idx_customer_master_maturity
          ON customer_master(master_maturity, master_maturity_review_status);

        CREATE TABLE IF NOT EXISTS customer_contract_products (
          id TEXT PRIMARY KEY,
          contract_id TEXT NOT NULL,
          interim_product_code TEXT NOT NULL
            CHECK(interim_product_code IN ({INTERIM_PRODUCT_CODES_SQL})),
          future_product_master_id TEXT,
          source TEXT NOT NULL DEFAULT 'user',
          provenance TEXT NOT NULL DEFAULT 'user_confirmed',
          created_by INTEGER,
          updated_by INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          deleted_at TEXT,
          FOREIGN KEY(contract_id) REFERENCES customer_contracts(id) ON DELETE CASCADE,
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_contract_products_active
          ON customer_contract_products(contract_id, interim_product_code)
          WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_customer_contract_products_product
          ON customer_contract_products(interim_product_code, deleted_at, contract_id);

        CREATE TABLE IF NOT EXISTS customer_contract_countries (
          id TEXT PRIMARY KEY,
          contract_id TEXT NOT NULL,
          country_code TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'user',
          provenance TEXT NOT NULL DEFAULT 'user_confirmed',
          created_by INTEGER,
          updated_by INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          deleted_at TEXT,
          FOREIGN KEY(contract_id) REFERENCES customer_contracts(id) ON DELETE CASCADE,
          FOREIGN KEY(created_by) REFERENCES users(id),
          FOREIGN KEY(updated_by) REFERENCES users(id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_contract_countries_active
          ON customer_contract_countries(contract_id, country_code)
          WHERE deleted_at IS NULL;
        """
    )
    db.execute("PRAGMA optimize")
