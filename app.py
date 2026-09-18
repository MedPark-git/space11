import base64
import calendar
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import string
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from source_import import (
    apply_historical_sales_correction,
    apply_monthly_sales_fcst_correction,
    apply_source_data_import,
)
from monthly_sales_fcst import (
    JPY_RATE_UNIT_ACTION_KEY,
    ROUND_TIMING_RULE_ACTION_KEY,
    init_monthly_sales_schema,
    register_monthly_sales_fcst,
)
from customer_master import (
    CUSTOMER_MASTER_MIGRATION_KEY,
    init_customer_master_schema,
    migrate_legacy_customer_data,
    register_customer_master,
    snapshot_customer_order_terms,
)
from commercial_context import (
    COMMERCIAL_CONTEXT_SCHEMA_VERSION,
    init_commercial_context_schema,
    register_commercial_context,
)
from major_tasks import major_task_dashboard_snapshot, refresh_major_task_rags, register_major_tasks
from major_tasks_migration import (
    MAJOR_TASKS_LEGACY_MIGRATION_VERSION,
    MAJOR_TASKS_SCHEMA_VERSION,
    apply_major_tasks_legacy_migration,
    apply_major_tasks_schema,
)
from stage_work_items import VERSION as STAGE_WORK_ITEMS_SCHEMA_VERSION
from maps_taxonomy import PARENT_BUSINESS_AREAS


APP_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(APP_DIR, "public")
DATA_DIR = os.environ.get("MEDPARK_DATA_DIR", "/app/user_data")
DATABASE_PATH_EXPLICIT = bool(os.environ.get("DATABASE_PATH"))
LEGACY_DB_PATH = os.path.join(DATA_DIR, "medpark_global_maps.db")
DB_PATH = os.environ.get("DATABASE_PATH") or os.path.join(DATA_DIR, "runtime", "medpark_global_maps.db")
PACKAGED_DB_PATH = os.path.join(APP_DIR, "data", "bootstrap", "medpark_global_maps.db")
PACKAGED_DB_SHA256 = "1d27e438d5e20973b81444a3d4f609224e4a2bbf771f95a29a26ce09652d1883"
PACKAGED_DB_CRITICAL_COUNTS = {
    "users": 13,
    "customer_master": 133,
    "customer_contracts": 116,
    "monthly_sales": 45,
    "monthly_sales_history": 182,
    "major_tasks": 157,
    "major_task_stages": 25,
    "forecast_round_details": 210,
    "records": 486,
    "shipments": 12309,
}
APP_VERSION = "2026.09.16.customer-master-commercial-context-v2"
SHIPMENT_METADATA_VERSION = 4
SHIPMENT_METADATA_ACTION_KEY = "shipment-metadata:2026-09-09-v4"
ERP_ACTUAL_MAPPING_EVIDENCE = {
    "source_file": "grid_excel_2026-09-08_11-45.xlsx",
    "source_sha256": "0507a00c5d8a938267c8e5cbe1611eea3f4c35ca7ddd2d4fc7bfad13c3043406",
    "verified_at": "2026-09-09",
    "matched_rows": 296,
    "matched_issues": 36,
    "row_total_matches": 295,
    "issue_total_matches": 36,
    "mapping": "Excel 합계액 = Amaranth Detail isuhAm",
    "exception": "IS2608000054는 Detail 5번이 10번으로 합쳐져 행은 달라도 출고번호 합계가 일치",
    "legacy_jpy_api_only_rows": ["IS2608000115/1", "IS2608000200/1", "IS2608000288/1"],
    "legacy_jpy_raw_krw": 563365600,
    "replacement_excel_krw": 5638720,
    "legacy_jpy_difference_krw": 557726880,
}
SEOUL = ZoneInfo("Asia/Seoul")
TASK_HIERARCHY_ACTION_KEY = "task-hierarchy-medparkallo-sales:2026-08-31-v1"
FORECAST_ROUND_OVERVIEW_PATH = os.path.join(
    APP_DIR, "data", "source", "forecast_round_overview_2026_08.json"
)
FORECAST_ROUND_DETAILS_PATH = os.path.join(
    APP_DIR, "data", "source", "forecast_round_details_2026_08.json"
)
ALLOWED_ROLES = {"admin", "manager", "editor", "viewer"}
EDIT_ROLES = {"admin", "manager", "editor"}
MANAGE_ROLES = {"admin", "manager"}
ENTITY_TYPES = {
    "account",
    "pipeline",
    "task",
    "event",
    "agenda",
    "cash_plan",
    "promotion",
    "transport",
    "receivable",
    "expense",
    "note",
    "goal",
    "activity",
    "order",
}
FAILED_LOGINS = {}
FORECAST_STAGES = {
    "sales_activity": {"label": "일반 영업추진", "confidence": 20},
    "pi_received": {"label": "PI 수령", "confidence": 60},
    "payment_received": {"label": "수금 완료", "confidence": 95},
    "erp_actual": {"label": "ERP 확정", "confidence": 100},
}
FORECAST_INPUT_STAGES = {"sales_activity", "pi_received", "payment_received"}
FORECAST_CURRENCIES = {"KRW", "USD", "EUR", "JPY", "CNY"}
FORECAST_BUSINESS_UNITS = set(PARENT_BUSINESS_AREAS) | {"unclassified"}
FORECAST_ROUND_BUSINESS_UNITS = tuple(PARENT_BUSINESS_AREAS.items())
FORECAST_ROUND_CHECKLIST = (
    ("input_complete", "매출자료 입력 완료"),
    ("fx_checked", "기준일·환율 확인"),
    ("carryover_checked", "전월 이월매출 확인"),
    ("current_checked", "당월 확정·예정·추진 구분 확인"),
    ("next_checked", "차월 예상매출 확인"),
    ("review_complete", "담당자 검토 완료"),
)
FORECAST_ROUND_DETAIL_STAGES = {
    "confirmed": "확정 매출",
    "scheduled": "예정 매출",
    "pipeline": "추진 매출",
    "undecided": "미정",
}
FORECAST_ROUND_DETAIL_PROGRESS_STATUSES = {
    "order_received": "오더접수",
    "pi_issued": "PI발행",
    "payment_completed": "입금완료",
    "shipment_completed": "출고완료",
}
FORECAST_ROUND_DETAIL_MANAGEMENT_TYPES = {
    "regular": "일반",
    "additional": "추가추진",
    "promotion": "프로모션",
    "expiring_inventory": "임박재고",
}
FORECAST_ROUND_DETAIL_DATE_FIELDS = (
    "order_agreed_at", "po_received_at", "pi_sent_at", "payment_expected_at",
    "payment_completed_at", "shipment_expected_at", "shipment_completed_at",
    "shipping_completed_at",
)
FORECAST_ROUND_DETAIL_AMOUNT_FIELDS = (
    "plan_foreign", "plan_krw", "carryover_foreign", "carryover_krw",
    "current_foreign", "current_krw", "next_foreign", "next_krw", "applied_rate",
)
FORECAST_ROUND_DETAIL_FX_PAIRS = (
    ("plan_foreign", "plan_krw"),
    ("carryover_foreign", "carryover_krw"),
    ("current_foreign", "current_krw"),
    ("next_foreign", "next_krw"),
)
FX_SOURCE = "Frankfurter · central bank reference"
STANDARD_REGIONS = ("중동", "동유럽", "서유럽", "아프리카", "북미", "남미", "오세아니아", "아시아")
REGION_COUNTRY_CODES = {
    "중동": {"048", "364", "368", "376", "400", "414", "422", "512", "634", "682", "760", "784", "792", "887"},
    "동유럽": {"008", "100", "112", "191", "203", "233", "268", "348", "428", "440", "498", "616", "642", "643", "688", "703", "705", "804", "807"},
    "서유럽": {"040", "056", "196", "208", "246", "250", "276", "300", "352", "372", "380", "442", "470", "528", "578", "620", "724", "752", "756", "826"},
    "아프리카": {"012", "024", "072", "120", "180", "231", "266", "288", "384", "404", "426", "434", "450", "454", "478", "480", "504", "508", "516", "562", "566", "646", "686", "710", "716", "729", "788", "800", "818", "834", "894"},
    "북미": {"124", "484", "840"},
    "남미": {"032", "068", "076", "152", "170", "218", "328", "600", "604", "740", "858", "862"},
    "오세아니아": {"036", "090", "242", "554", "598"},
    "아시아": {"004", "050", "096", "104", "116", "144", "156", "158", "344", "356", "360", "392", "398", "408", "410", "417", "418", "446", "458", "462", "496", "524", "586", "608", "626", "702", "704", "764", "795", "860"},
}

# Natural Earth / world-atlas uses ISO 3166-1 numeric identifiers.  The
# aliases below cover MedPark's current and likely overseas markets while an
# exact English Natural Earth country name is also resolved from the bundled
# topology file at runtime.
COUNTRY_CATALOG = {
    "032": {"name": "Argentina", "label": "아르헨티나", "aliases": ("ar", "arg", "argentina", "아르헨티나")},
    "036": {"name": "Australia", "label": "호주", "aliases": ("au", "aus", "australia", "호주")},
    "040": {"name": "Austria", "label": "오스트리아", "aliases": ("at", "aut", "austria", "오스트리아")},
    "048": {"name": "Bahrain", "label": "바레인", "aliases": ("bh", "bhr", "bahrain", "바레인")},
    "056": {"name": "Belgium", "label": "벨기에", "aliases": ("be", "bel", "belgium", "벨기에")},
    "076": {"name": "Brazil", "label": "브라질", "aliases": ("br", "bra", "brazil", "브라질")},
    "100": {"name": "Bulgaria", "label": "불가리아", "aliases": ("bg", "bgr", "bulgaria", "불가리아")},
    "104": {"name": "Myanmar", "label": "미얀마", "aliases": ("mm", "mmr", "myanmar", "burma", "미얀마")},
    "116": {"name": "Cambodia", "label": "캄보디아", "aliases": ("kh", "khm", "cambodia", "캄보디아")},
    "124": {"name": "Canada", "label": "캐나다", "aliases": ("ca", "can", "canada", "캐나다")},
    "144": {"name": "Sri Lanka", "label": "스리랑카", "aliases": ("lk", "lka", "sri lanka", "스리랑카")},
    "152": {"name": "Chile", "label": "칠레", "aliases": ("cl", "chl", "chile", "칠레")},
    "156": {"name": "China", "label": "중국", "aliases": ("cn", "chn", "china", "prc", "중국")},
    "158": {"name": "Taiwan", "label": "대만", "aliases": ("tw", "twn", "taiwan", "taipei", "대만")},
    "170": {"name": "Colombia", "label": "콜롬비아", "aliases": ("co", "col", "colombia", "콜롬비아")},
    "196": {"name": "Cyprus", "label": "키프로스", "aliases": ("cy", "cyp", "cyprus", "키프로스")},
    "203": {"name": "Czechia", "label": "체코", "aliases": ("cz", "cze", "czechia", "czech republic", "체코")},
    "208": {"name": "Denmark", "label": "덴마크", "aliases": ("dk", "dnk", "denmark", "덴마크")},
    "218": {"name": "Ecuador", "label": "에콰도르", "aliases": ("ec", "ecu", "ecuador", "에콰도르")},
    "233": {"name": "Estonia", "label": "에스토니아", "aliases": ("ee", "est", "estonia", "에스토니아")},
    "246": {"name": "Finland", "label": "핀란드", "aliases": ("fi", "fin", "finland", "핀란드")},
    "250": {"name": "France", "label": "프랑스", "aliases": ("fr", "fra", "france", "프랑스")},
    "268": {"name": "Georgia", "label": "조지아", "aliases": ("ge", "geo", "georgia", "조지아")},
    "276": {"name": "Germany", "label": "독일", "aliases": ("de", "deu", "germany", "독일")},
    "300": {"name": "Greece", "label": "그리스", "aliases": ("gr", "grc", "greece", "그리스")},
    "348": {"name": "Hungary", "label": "헝가리", "aliases": ("hu", "hun", "hungary", "헝가리")},
    "356": {"name": "India", "label": "인도", "aliases": ("in", "ind", "india", "인도")},
    "360": {"name": "Indonesia", "label": "인도네시아", "aliases": ("id", "idn", "indonesia", "인도네시아")},
    "364": {"name": "Iran", "label": "이란", "aliases": ("ir", "irn", "iran", "이란")},
    "372": {"name": "Ireland", "label": "아일랜드", "aliases": ("ie", "irl", "ireland", "아일랜드")},
    "376": {"name": "Israel", "label": "이스라엘", "aliases": ("il", "isr", "israel", "이스라엘")},
    "380": {"name": "Italy", "label": "이탈리아", "aliases": ("it", "ita", "italy", "이탈리아")},
    "392": {"name": "Japan", "label": "일본", "aliases": ("jp", "jpn", "japan", "일본")},
    "398": {"name": "Kazakhstan", "label": "카자흐스탄", "aliases": ("kz", "kaz", "kazakhstan", "카자흐스탄")},
    "400": {"name": "Jordan", "label": "요르단", "aliases": ("jo", "jor", "jordan", "요르단")},
    "404": {"name": "Kenya", "label": "케냐", "aliases": ("ke", "ken", "kenya", "케냐")},
    "410": {"name": "South Korea", "label": "대한민국", "aliases": ("kr", "kor", "korea", "south korea", "republic of korea", "한국", "대한민국")},
    "414": {"name": "Kuwait", "label": "쿠웨이트", "aliases": ("kw", "kwt", "kuwait", "쿠웨이트")},
    "422": {"name": "Lebanon", "label": "레바논", "aliases": ("lb", "lbn", "lebanon", "레바논")},
    "428": {"name": "Latvia", "label": "라트비아", "aliases": ("lv", "lva", "latvia", "라트비아")},
    "440": {"name": "Lithuania", "label": "리투아니아", "aliases": ("lt", "ltu", "lithuania", "리투아니아")},
    "458": {"name": "Malaysia", "label": "말레이시아", "aliases": ("my", "mys", "malaysia", "말레이시아")},
    "484": {"name": "Mexico", "label": "멕시코", "aliases": ("mx", "mex", "mexico", "멕시코")},
    "496": {"name": "Mongolia", "label": "몽골", "aliases": ("mn", "mng", "mongolia", "몽골")},
    "504": {"name": "Morocco", "label": "모로코", "aliases": ("ma", "mar", "morocco", "모로코")},
    "528": {"name": "Netherlands", "label": "네덜란드", "aliases": ("nl", "nld", "netherlands", "holland", "네덜란드")},
    "554": {"name": "New Zealand", "label": "뉴질랜드", "aliases": ("nz", "nzl", "new zealand", "뉴질랜드")},
    "566": {"name": "Nigeria", "label": "나이지리아", "aliases": ("ng", "nga", "nigeria", "나이지리아")},
    "578": {"name": "Norway", "label": "노르웨이", "aliases": ("no", "nor", "norway", "노르웨이")},
    "586": {"name": "Pakistan", "label": "파키스탄", "aliases": ("pk", "pak", "pakistan", "파키스탄")},
    "604": {"name": "Peru", "label": "페루", "aliases": ("pe", "per", "peru", "페루")},
    "608": {"name": "Philippines", "label": "필리핀", "aliases": ("ph", "phl", "philippines", "필리핀")},
    "616": {"name": "Poland", "label": "폴란드", "aliases": ("pl", "pol", "poland", "폴란드")},
    "620": {"name": "Portugal", "label": "포르투갈", "aliases": ("pt", "prt", "portugal", "포르투갈")},
    "634": {"name": "Qatar", "label": "카타르", "aliases": ("qa", "qat", "qatar", "카타르")},
    "642": {"name": "Romania", "label": "루마니아", "aliases": ("ro", "rou", "romania", "루마니아")},
    "643": {"name": "Russia", "label": "러시아", "aliases": ("ru", "rus", "russia", "russian federation", "러시아")},
    "682": {"name": "Saudi Arabia", "label": "사우디아라비아", "aliases": ("sa", "sau", "saudi arabia", "saudi", "ksa", "사우디", "사우디아라비아")},
    "688": {"name": "Serbia", "label": "세르비아", "aliases": ("rs", "srb", "serbia", "세르비아")},
    "702": {"name": "Singapore", "label": "싱가포르", "aliases": ("sg", "sgp", "singapore", "싱가포르")},
    "703": {"name": "Slovakia", "label": "슬로바키아", "aliases": ("sk", "svk", "slovakia", "슬로바키아")},
    "704": {"name": "Vietnam", "label": "베트남", "aliases": ("vn", "vnm", "vietnam", "viet nam", "베트남")},
    "705": {"name": "Slovenia", "label": "슬로베니아", "aliases": ("si", "svn", "slovenia", "슬로베니아")},
    "710": {"name": "South Africa", "label": "남아프리카공화국", "aliases": ("za", "zaf", "south africa", "남아프리카", "남아공")},
    "724": {"name": "Spain", "label": "스페인", "aliases": ("es", "esp", "spain", "스페인")},
    "752": {"name": "Sweden", "label": "스웨덴", "aliases": ("se", "swe", "sweden", "스웨덴")},
    "756": {"name": "Switzerland", "label": "스위스", "aliases": ("ch", "che", "switzerland", "스위스")},
    "764": {"name": "Thailand", "label": "태국", "aliases": ("th", "tha", "thailand", "태국")},
    "784": {"name": "United Arab Emirates", "label": "아랍에미리트", "aliases": ("ae", "are", "uae", "united arab emirates", "dubai", "아랍에미리트", "두바이")},
    "792": {"name": "Turkey", "label": "튀르키예", "aliases": ("tr", "tur", "turkey", "turkiye", "türkiye", "터키", "튀르키예")},
    "804": {"name": "Ukraine", "label": "우크라이나", "aliases": ("ua", "ukr", "ukraine", "우크라이나")},
    "818": {"name": "Egypt", "label": "이집트", "aliases": ("eg", "egy", "egypt", "이집트")},
    "826": {"name": "United Kingdom", "label": "영국", "aliases": ("gb", "gbr", "uk", "united kingdom", "great britain", "england", "영국")},
    "840": {"name": "United States of America", "label": "미국", "aliases": ("us", "usa", "united states", "united states of america", "america", "미국")},
    "858": {"name": "Uruguay", "label": "우루과이", "aliases": ("uy", "ury", "uruguay", "우루과이")},
    "860": {"name": "Uzbekistan", "label": "우즈베키스탄", "aliases": ("uz", "uzb", "uzbekistan", "우즈베키스탄")},
}

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("APP_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
DATABASE_READY = threading.Event()
DATABASE_SCHEMA_READY = threading.Event()
DATABASE_INIT_ERROR = None
DATABASE_STORAGE_WRITABLE = False
DATABASE_STORAGE_MIGRATED = False
EXCHANGE_RATE_MEMORY_CACHE = []
EXCHANGE_RATE_MEMORY_LOCK = threading.Lock()
DATABASE_WRITE_LOCK = threading.RLock()
ASYNC_DATABASE_INIT = os.environ.get(
    "DATABASE_INIT_ASYNC",
    "1" if DB_PATH.startswith("/app/user_data/") else "0",
) == "1"


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_db_dir():
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)


def sqlite_table_counts(connection):
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    counts = {}
    for table in tables:
        safe_table = table.replace('"', '""')
        counts[table] = connection.execute(f'SELECT COUNT(*) FROM "{safe_table}"').fetchone()[0]
    return counts


def prepare_database_storage():
    """Copy a packaged legacy DB once into a runtime-created writable file."""
    global DATABASE_STORAGE_MIGRATED
    ensure_db_dir()
    packaged_bootstrap = os.environ.get("DATABASE_BOOTSTRAP_FROM_PACKAGED_SNAPSHOT", "0") == "1"
    source_path = PACKAGED_DB_PATH if packaged_bootstrap else LEGACY_DB_PATH

    if packaged_bootstrap:
        if not os.path.exists(PACKAGED_DB_PATH):
            raise RuntimeError("Packaged database bootstrap was requested but the snapshot is missing")
        digest = hashlib.sha256()
        with open(PACKAGED_DB_PATH, "rb") as snapshot_file:
            for block in iter(lambda: snapshot_file.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != PACKAGED_DB_SHA256:
            raise RuntimeError("Packaged database snapshot checksum verification failed")

        if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
            current = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
            try:
                current_counts = sqlite_table_counts(current)
            finally:
                current.close()
            if all(current_counts.get(table) == count for table, count in PACKAGED_DB_CRITICAL_COUNTS.items()):
                DATABASE_STORAGE_MIGRATED = True
                return
            protected_tables = (
                "users",
                "customer_master",
                "customer_contracts",
                "monthly_sales",
                "monthly_sales_history",
                "major_tasks",
                "records",
                "shipments",
            )
            if any(current_counts.get(table, 0) for table in protected_tables):
                raise RuntimeError("Refusing to replace a non-empty runtime database during bootstrap")
    elif os.path.exists(DB_PATH):
        DATABASE_STORAGE_MIGRATED = not DATABASE_PATH_EXPLICIT and DB_PATH != LEGACY_DB_PATH
        return
    if DATABASE_PATH_EXPLICIT or DB_PATH == LEGACY_DB_PATH:
        return
    if not os.path.exists(source_path):
        return

    temporary_path = f"{DB_PATH}.migrating-{os.getpid()}"
    source = None
    target = None
    try:
        source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
        source.row_factory = sqlite3.Row
        source_counts = sqlite_table_counts(source)
        target = sqlite3.connect(temporary_path, timeout=30)
        source.backup(target)
        target.execute("PRAGMA foreign_keys = ON")
        target.commit()
        target_counts = sqlite_table_counts(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = target.execute("PRAGMA foreign_key_check").fetchall()
        if source_counts != target_counts:
            raise RuntimeError("SQLite runtime copy row-count verification failed")
        if packaged_bootstrap and not all(
            target_counts.get(table) == count for table, count in PACKAGED_DB_CRITICAL_COUNTS.items()
        ):
            raise RuntimeError("Packaged database critical row-count verification failed")
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError("SQLite runtime copy integrity verification failed")
        target.close()
        target = None
        source.close()
        source = None
        # Keep the runtime copy writable by the app and readable by the
        # platform backup worker, matching the packaged legacy DB mode.
        os.chmod(temporary_path, 0o664)
        os.replace(temporary_path, DB_PATH)
        DATABASE_STORAGE_MIGRATED = True
        app.logger.info(
            "SQLite runtime storage migration completed tables=%s rows=%s",
            len(target_counts),
            sum(target_counts.values()),
        )
    except Exception:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise


def verify_database_storage_writable(max_attempts=5):
    global DATABASE_STORAGE_WRITABLE
    if not DATABASE_PATH_EXPLICIT and DB_PATH != LEGACY_DB_PATH:
        try:
            os.chmod(DB_PATH, 0o664)
        except OSError as error:
            app.logger.warning("runtime_database_chmod_failed error_type=%s", type(error).__name__)
    for attempt in range(max_attempts):
        connection = None
        try:
            connection = sqlite3.connect(DB_PATH, timeout=5)
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
            DATABASE_STORAGE_WRITABLE = True
            return
        except sqlite3.OperationalError as error:
            if connection is not None:
                rollback_quietly(connection)
            if sqlite_is_busy(error) and attempt < max_attempts - 1:
                time.sleep(0.25 * (attempt + 1))
                continue
            raise
        finally:
            if connection is not None:
                connection.close()


def get_db():
    if "db" not in g:
        ensure_db_dir()
        g.db = sqlite3.connect(DB_PATH, timeout=20)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 20000")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def sqlite_is_busy(error):
    message = str(error).lower()
    return isinstance(error, sqlite3.OperationalError) and (
        "locked" in message or "busy" in message
    )


def rollback_quietly(db):
    try:
        db.rollback()
    except sqlite3.Error:
        pass


def row_dict(row):
    return dict(row) if row is not None else None


def safe_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def parse_payload(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def public_user(row):
    data = row_dict(row)
    if not data:
        return None
    data.pop("password_hash", None)
    data["is_active"] = data.get("status") == "active" and not data.get("deleted_at")
    data["must_change_password"] = bool(data.get("must_change_password", 0))
    return data


def public_record(row):
    data = row_dict(row)
    if not data:
        return None
    data["payload"] = parse_payload(data.pop("payload_json", "{}"))
    if data["payload"].get("imported_from_legacy"):
        legacy_owner = data["payload"].get("source_owner_name") or data["payload"].get("primary_owner")
        if legacy_owner:
            data["owner_name"] = legacy_owner
    return data


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.remote_addr or "")[:64]


def current_user_row():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)
    ).fetchone()


def audit(action, entity_type, entity_id, summary, before=None, after=None, actor=None, commit=False, connection=None):
    actor = actor if actor is not None else current_user_row()
    db = connection if connection is not None else get_db()
    db.execute(
        """
        INSERT INTO audit_logs
          (occurred_at, actor_user_id, actor_username, action, entity_type, entity_id,
           summary, before_json, after_json, ip_address, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now(),
            actor["id"] if actor else None,
            actor["username"] if actor else "system",
            action,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            summary[:500],
            safe_json(before) if before is not None else None,
            safe_json(after) if after is not None else None,
            client_ip(),
            request.headers.get("User-Agent", "")[:500] if request else "",
        ),
    )
    if commit:
        db.commit()


def auth_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user_row()
        if not user or user["status"] != "active":
            session.clear()
            return jsonify(error="로그인이 필요합니다."), 401
        g.current_user = user
        if (
            user["must_change_password"]
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.endpoint not in {"change_password", "logout"}
        ):
            return jsonify(error="임시 비밀번호를 먼저 변경해야 합니다.", password_change_required=True), 428
        return fn(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @auth_required
        def wrapped(*args, **kwargs):
            if g.current_user["role"] not in roles:
                return jsonify(error="이 작업을 수행할 권한이 없습니다."), 403
            return fn(*args, **kwargs)

        return wrapped

    return decorator


def csrf_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(token, expected):
            return jsonify(
                error="로그인 보안정보를 갱신한 뒤 다시 저장해 주세요.",
                code="CSRF_EXPIRED",
            ), 403
        return fn(*args, **kwargs)

    return wrapped


def validate_password(password):
    if len(password or "") < 10:
        return "비밀번호는 10자 이상이어야 합니다."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "비밀번호에는 영문과 숫자가 모두 포함되어야 합니다."
    return None


def validate_username(username):
    if not re.fullmatch(r"[A-Za-z0-9가-힣_.-]{2,40}", username or ""):
        return "아이디는 한글·영문·숫자·._- 조합 2~40자로 입력하세요."
    return None


def init_db():
    with app.app_context():
        db = get_db()
        # A rolling deployment briefly runs the old and new containers against
        # the same SQLite file.  Keep each schema-lock wait shorter than the
        # platform health window so initialize_database() can retry safely.
        db.execute("PRAGMA busy_timeout = 1500")
        # WAL mode is persistent. Configure it during initialization instead
        # of reapplying it on every request, where it can contend with writes.
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE COLLATE NOCASE,
              display_name TEXT NOT NULL,
              email TEXT UNIQUE COLLATE NOCASE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'viewer',
              status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_login_at TEXT,
              password_changed_at TEXT,
              must_change_password INTEGER NOT NULL DEFAULT 0,
              created_by INTEGER,
              deleted_at TEXT,
              FOREIGN KEY (created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS records (
              id TEXT PRIMARY KEY,
              entity_type TEXT NOT NULL,
              title TEXT NOT NULL,
              owner_id INTEGER,
              status TEXT NOT NULL DEFAULT 'active',
              due_date TEXT,
              region TEXT,
              country TEXT,
              amount REAL NOT NULL DEFAULT 0,
              currency TEXT NOT NULL DEFAULT 'USD',
              payload_json TEXT NOT NULL DEFAULT '{}',
              created_by INTEGER NOT NULL,
              updated_by INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT,
              deleted_by INTEGER,
              FOREIGN KEY (owner_id) REFERENCES users(id),
              FOREIGN KEY (created_by) REFERENCES users(id),
              FOREIGN KEY (updated_by) REFERENCES users(id),
              FOREIGN KEY (deleted_by) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_records_type ON records(entity_type, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_records_owner ON records(owner_id, deleted_at);

            CREATE TABLE IF NOT EXISTS audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              occurred_at TEXT NOT NULL,
              actor_user_id INTEGER,
              actor_username TEXT NOT NULL,
              action TEXT NOT NULL,
              entity_type TEXT NOT NULL,
              entity_id TEXT,
              summary TEXT NOT NULL,
              before_json TEXT,
              after_json TEXT,
              ip_address TEXT,
              user_agent TEXT,
              FOREIGN KEY (actor_user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id);

            CREATE TABLE IF NOT EXISTS one_time_actions (
              action_key TEXT PRIMARY KEY,
              applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS shipments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              issue_no TEXT NOT NULL,
              issue_seq INTEGER NOT NULL,
              ship_date TEXT NOT NULL,
              is_overseas INTEGER NOT NULL DEFAULT 0,
              trade_type TEXT,
              business_unit TEXT NOT NULL DEFAULT 'unclassified',
              partner_classification TEXT,
              metadata_version INTEGER NOT NULL DEFAULT 0,
              erp_management_code TEXT,
              erp_management_name TEXT,
              source_system TEXT NOT NULL DEFAULT 'UNKNOWN',
              actual_review_status TEXT NOT NULL DEFAULT 'unclassified',
              partner_code TEXT,
              partner_name TEXT,
              country_code TEXT,
              country_name TEXT,
              product_code TEXT,
              product_name TEXT,
              specification TEXT,
              quantity REAL NOT NULL DEFAULT 0,
              currency TEXT,
              exchange_rate REAL NOT NULL DEFAULT 0,
              foreign_amount REAL NOT NULL DEFAULT 0,
              krw_supply REAL NOT NULL DEFAULT 0,
              krw_vat REAL NOT NULL DEFAULT 0,
              krw_total REAL NOT NULL DEFAULT 0,
              manager_name TEXT,
              department_name TEXT,
              raw_json TEXT NOT NULL,
              synced_at TEXT NOT NULL,
              UNIQUE(issue_no, issue_seq)
            );
            CREATE INDEX IF NOT EXISTS idx_shipments_date ON shipments(ship_date);
            CREATE INDEX IF NOT EXISTS idx_shipments_partner ON shipments(partner_name);

            CREATE TABLE IF NOT EXISTS erp_sync_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              requested_by INTEGER,
              date_from TEXT NOT NULL,
              date_to TEXT NOT NULL,
              status TEXT NOT NULL,
              header_count INTEGER NOT NULL DEFAULT 0,
              source_header_count INTEGER NOT NULL DEFAULT 0,
              excluded_header_count INTEGER NOT NULL DEFAULT 0,
              excluded_partner_count INTEGER NOT NULL DEFAULT 0,
              line_count INTEGER NOT NULL DEFAULT 0,
              foreign_amount REAL NOT NULL DEFAULT 0,
              krw_amount REAL NOT NULL DEFAULT 0,
              existing_line_count INTEGER NOT NULL DEFAULT 0,
              existing_krw_amount REAL NOT NULL DEFAULT 0,
              new_krw_amount REAL NOT NULL DEFAULT 0,
              latest_ship_date TEXT,
              preflight_json TEXT NOT NULL DEFAULT '{}',
              currency_totals_json TEXT NOT NULL DEFAULT '{}',
              management_totals_json TEXT NOT NULL DEFAULT '{}',
              quality_warnings_json TEXT NOT NULL DEFAULT '[]',
              forced INTEGER NOT NULL DEFAULT 0,
              force_reason TEXT NOT NULL DEFAULT '',
              error_message TEXT,
              FOREIGN KEY (requested_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS forecast_cycles (
              id TEXT PRIMARY KEY,
              forecast_month TEXT NOT NULL,
              round_no INTEGER NOT NULL CHECK(round_no BETWEEN 1 AND 3),
              as_of_date TEXT NOT NULL,
              usd_krw REAL NOT NULL DEFAULT 0,
              eur_krw REAL NOT NULL DEFAULT 0,
              jpy_krw REAL NOT NULL DEFAULT 0,
              cny_krw REAL NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'open',
              created_by INTEGER NOT NULL,
              updated_by INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(forecast_month, round_no),
              FOREIGN KEY (created_by) REFERENCES users(id),
              FOREIGN KEY (updated_by) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_cycles_month ON forecast_cycles(forecast_month, round_no);

            CREATE TABLE IF NOT EXISTS forecast_items (
              id TEXT PRIMARY KEY,
              cycle_id TEXT NOT NULL,
              title TEXT NOT NULL,
              account_id TEXT,
              account_name TEXT NOT NULL DEFAULT '',
              business_unit TEXT NOT NULL DEFAULT 'unclassified',
              item_name TEXT NOT NULL DEFAULT '',
              stage TEXT NOT NULL DEFAULT 'sales_activity',
              confidence REAL NOT NULL DEFAULT 20,
              foreign_amount REAL NOT NULL DEFAULT 0,
              currency TEXT NOT NULL DEFAULT 'USD',
              expected_ship_date TEXT,
              owner_id INTEGER,
              notes TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'active',
              carryover_from_id TEXT,
              carryover_from_month TEXT,
              copied_from_id TEXT,
              source_type TEXT,
              source_id TEXT,
              created_by INTEGER NOT NULL,
              updated_by INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT,
              deleted_by INTEGER,
              FOREIGN KEY (cycle_id) REFERENCES forecast_cycles(id),
              FOREIGN KEY (owner_id) REFERENCES users(id),
              FOREIGN KEY (created_by) REFERENCES users(id),
              FOREIGN KEY (updated_by) REFERENCES users(id),
              FOREIGN KEY (deleted_by) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_items_cycle ON forecast_items(cycle_id, deleted_at, status);
            CREATE INDEX IF NOT EXISTS idx_forecast_items_owner ON forecast_items(owner_id, deleted_at);

            CREATE TABLE IF NOT EXISTS forecast_round_workflows (
              id TEXT PRIMARY KEY,
              forecast_month TEXT NOT NULL,
              round_no INTEGER NOT NULL CHECK(round_no BETWEEN 0 AND 3),
              as_of_date TEXT,
              usd_krw REAL NOT NULL DEFAULT 0,
              eur_krw REAL NOT NULL DEFAULT 0,
              jpy_krw REAL NOT NULL DEFAULT 0,
              cny_krw REAL NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'confirmed')),
              notes TEXT NOT NULL DEFAULT '',
              source_name TEXT,
              source_version TEXT,
              created_by INTEGER,
              updated_by INTEGER,
              confirmed_by INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              confirmed_at TEXT,
              UNIQUE(forecast_month, round_no),
              FOREIGN KEY (created_by) REFERENCES users(id),
              FOREIGN KEY (updated_by) REFERENCES users(id),
              FOREIGN KEY (confirmed_by) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_round_workflows_month
              ON forecast_round_workflows(forecast_month, round_no);

            CREATE TABLE IF NOT EXISTS forecast_round_entries (
              id TEXT PRIMARY KEY,
              workflow_id TEXT NOT NULL,
              business_unit TEXT NOT NULL CHECK(business_unit IN ('aesthetic', 'medical', 'dental')),
              plan_krw REAL NOT NULL DEFAULT 0,
              initial_fcst_krw REAL NOT NULL DEFAULT 0,
              first_expected_krw REAL NOT NULL DEFAULT 0,
              carryover_krw REAL NOT NULL DEFAULT 0,
              current_month_krw REAL NOT NULL DEFAULT 0,
              pipeline_krw REAL NOT NULL DEFAULT 0,
              next_month_krw REAL NOT NULL DEFAULT 0,
              next_pipeline_krw REAL NOT NULL DEFAULT 0,
              notes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(workflow_id, business_unit),
              FOREIGN KEY (workflow_id) REFERENCES forecast_round_workflows(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_round_entries_workflow
              ON forecast_round_entries(workflow_id, business_unit);

            CREATE TABLE IF NOT EXISTS forecast_round_checklist (
              id TEXT PRIMARY KEY,
              workflow_id TEXT NOT NULL,
              check_key TEXT NOT NULL,
              label TEXT NOT NULL,
              required INTEGER NOT NULL DEFAULT 1,
              completed INTEGER NOT NULL DEFAULT 0,
              note TEXT NOT NULL DEFAULT '',
              completed_by INTEGER,
              completed_at TEXT,
              sort_order INTEGER NOT NULL DEFAULT 0,
              UNIQUE(workflow_id, check_key),
              FOREIGN KEY (workflow_id) REFERENCES forecast_round_workflows(id) ON DELETE CASCADE,
              FOREIGN KEY (completed_by) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_round_checklist_workflow
              ON forecast_round_checklist(workflow_id, sort_order);

            CREATE TABLE IF NOT EXISTS forecast_round_details (
              id TEXT PRIMARY KEY,
              workflow_id TEXT NOT NULL,
              tracking_key TEXT,
              source_key TEXT,
              source_row INTEGER,
              sales_stage TEXT NOT NULL DEFAULT 'undecided'
                CHECK(sales_stage IN ('confirmed', 'scheduled', 'pipeline', 'undecided')),
              progress_status TEXT NOT NULL DEFAULT 'order_received'
                CHECK(progress_status IN ('order_received', 'pi_issued', 'payment_completed', 'shipment_completed')),
              management_type TEXT NOT NULL DEFAULT 'regular'
                CHECK(management_type IN ('regular', 'additional', 'promotion', 'expiring_inventory')),
              business_unit TEXT NOT NULL CHECK(business_unit IN ('aesthetic', 'medical', 'dental')),
              classification TEXT NOT NULL DEFAULT '',
              country_code TEXT,
              country_name TEXT NOT NULL DEFAULT '',
              account_code TEXT,
              account_name TEXT NOT NULL DEFAULT '',
              product_code TEXT,
              item_name TEXT NOT NULL DEFAULT '품목 미지정',
              owner_name TEXT NOT NULL DEFAULT '',
              timing_note TEXT NOT NULL DEFAULT '',
              currency TEXT NOT NULL DEFAULT 'USD' CHECK(currency IN ('KRW', 'USD', 'EUR', 'JPY', 'CNY')),
              plan_foreign REAL NOT NULL DEFAULT 0,
              plan_krw REAL NOT NULL DEFAULT 0,
              carryover_foreign REAL NOT NULL DEFAULT 0,
              carryover_krw REAL NOT NULL DEFAULT 0,
              current_foreign REAL NOT NULL DEFAULT 0,
              current_krw REAL NOT NULL DEFAULT 0,
              next_foreign REAL NOT NULL DEFAULT 0,
              next_krw REAL NOT NULL DEFAULT 0,
              order_agreed_at TEXT,
              po_received_at TEXT,
              pi_sent_at TEXT,
              payment_expected_at TEXT,
              payment_completed_at TEXT,
              shipment_expected_at TEXT,
              shipment_completed_at TEXT,
              shipping_completed_at TEXT,
              target_date TEXT,
              applied_rate REAL NOT NULL DEFAULT 0,
              change_reason TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              source_type TEXT NOT NULL DEFAULT 'manual' CHECK(source_type IN ('workbook', 'manual', 'copied')),
              created_by INTEGER,
              updated_by INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT,
              deleted_by INTEGER,
              UNIQUE(workflow_id, source_key),
              FOREIGN KEY (workflow_id) REFERENCES forecast_round_workflows(id) ON DELETE CASCADE,
              FOREIGN KEY (created_by) REFERENCES users(id),
              FOREIGN KEY (updated_by) REFERENCES users(id),
              FOREIGN KEY (deleted_by) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_round_details_workflow
              ON forecast_round_details(workflow_id, deleted_at, sales_stage);
            CREATE INDEX IF NOT EXISTS idx_forecast_round_details_country
              ON forecast_round_details(workflow_id, country_name, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_forecast_round_details_account
              ON forecast_round_details(workflow_id, account_name, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_forecast_round_details_item
              ON forecast_round_details(workflow_id, item_name, deleted_at);

            CREATE TABLE IF NOT EXISTS exchange_rates (
              rate_date TEXT NOT NULL,
              currency TEXT NOT NULL,
              krw_rate REAL NOT NULL,
              source TEXT NOT NULL,
              fetched_at TEXT NOT NULL,
              PRIMARY KEY (rate_date, currency, source)
            );
            CREATE INDEX IF NOT EXISTS idx_exchange_rates_latest ON exchange_rates(fetched_at DESC, currency);

            CREATE TABLE IF NOT EXISTS dashboard_targets (
              target_type TEXT NOT NULL,
              target_key TEXT NOT NULL,
              target_krw REAL NOT NULL DEFAULT 0,
              created_by INTEGER NOT NULL,
              updated_by INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (target_type, target_key),
              FOREIGN KEY (created_by) REFERENCES users(id),
              FOREIGN KEY (updated_by) REFERENCES users(id)
            );
            """
        )
        init_monthly_sales_schema(db, utc_now)
        init_customer_master_schema(db)
        init_commercial_context_schema(db, utc_now)
        apply_major_tasks_schema(db, utc_now)
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "must_change_password" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        shipment_columns = {row["name"] for row in db.execute("PRAGMA table_info(shipments)").fetchall()}
        shipment_migrations = {
            "is_overseas": "INTEGER NOT NULL DEFAULT 0",
            "trade_type": "TEXT",
            "business_unit": "TEXT NOT NULL DEFAULT 'unclassified'",
            "partner_classification": "TEXT",
            "metadata_version": "INTEGER NOT NULL DEFAULT 0",
            "country_code": "TEXT",
            "country_name": "TEXT",
            "erp_management_code": "TEXT",
            "erp_management_name": "TEXT",
            "source_system": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
            "actual_review_status": "TEXT NOT NULL DEFAULT 'unclassified'",
        }
        for column, definition in shipment_migrations.items():
            if column not in shipment_columns:
                db.execute(f"ALTER TABLE shipments ADD COLUMN {column} {definition}")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_shipments_partner_code_overseas "
            "ON shipments(partner_code, ship_date) WHERE is_overseas=1"
        )
        sync_columns = {row["name"] for row in db.execute("PRAGMA table_info(erp_sync_runs)").fetchall()}
        if "source_header_count" not in sync_columns:
            db.execute("ALTER TABLE erp_sync_runs ADD COLUMN source_header_count INTEGER NOT NULL DEFAULT 0")
        if "excluded_header_count" not in sync_columns:
            db.execute("ALTER TABLE erp_sync_runs ADD COLUMN excluded_header_count INTEGER NOT NULL DEFAULT 0")
        if "excluded_partner_count" not in sync_columns:
            db.execute("ALTER TABLE erp_sync_runs ADD COLUMN excluded_partner_count INTEGER NOT NULL DEFAULT 0")
        sync_migrations = {
            "existing_line_count": "INTEGER NOT NULL DEFAULT 0",
            "existing_krw_amount": "REAL NOT NULL DEFAULT 0",
            "new_krw_amount": "REAL NOT NULL DEFAULT 0",
            "latest_ship_date": "TEXT",
            "preflight_json": "TEXT NOT NULL DEFAULT '{}'",
            "currency_totals_json": "TEXT NOT NULL DEFAULT '{}'",
            "management_totals_json": "TEXT NOT NULL DEFAULT '{}'",
            "quality_warnings_json": "TEXT NOT NULL DEFAULT '[]'",
            "forced": "INTEGER NOT NULL DEFAULT 0",
            "force_reason": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in sync_migrations.items():
            if column not in sync_columns:
                db.execute(f"ALTER TABLE erp_sync_runs ADD COLUMN {column} {definition}")
        forecast_item_columns = {row["name"] for row in db.execute("PRAGMA table_info(forecast_items)").fetchall()}
        if "source_type" not in forecast_item_columns:
            db.execute("ALTER TABLE forecast_items ADD COLUMN source_type TEXT")
        if "source_id" not in forecast_item_columns:
            db.execute("ALTER TABLE forecast_items ADD COLUMN source_id TEXT")
        forecast_cycle_columns = {row["name"] for row in db.execute("PRAGMA table_info(forecast_cycles)").fetchall()}
        if "jpy_krw" not in forecast_cycle_columns:
            db.execute("ALTER TABLE forecast_cycles ADD COLUMN jpy_krw REAL NOT NULL DEFAULT 0")
        forecast_detail_columns = {row["name"] for row in db.execute("PRAGMA table_info(forecast_round_details)").fetchall()}
        if "progress_status" not in forecast_detail_columns:
            db.execute(
                "ALTER TABLE forecast_round_details ADD COLUMN progress_status TEXT NOT NULL DEFAULT 'order_received'"
            )
            db.execute(
                """
                UPDATE forecast_round_details
                SET progress_status = CASE
                  WHEN shipping_completed_at IS NOT NULL OR shipment_completed_at IS NOT NULL THEN 'shipment_completed'
                  WHEN payment_completed_at IS NOT NULL THEN 'payment_completed'
                  WHEN pi_sent_at IS NOT NULL THEN 'pi_issued'
                  ELSE 'order_received'
                END
                """
            )
        forecast_detail_columns = {row["name"] for row in db.execute("PRAGMA table_info(forecast_round_details)").fetchall()}
        forecast_detail_migrations = {
            "tracking_key": "TEXT",
            "management_type": "TEXT NOT NULL DEFAULT 'regular'",
            "target_date": "TEXT",
            "change_reason": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in forecast_detail_migrations.items():
            if column not in forecast_detail_columns:
                db.execute(f"ALTER TABLE forecast_round_details ADD COLUMN {column} {definition}")
        db.execute("UPDATE forecast_round_details SET tracking_key = id WHERE tracking_key IS NULL OR tracking_key = ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_shipments_overseas_date ON shipments(is_overseas, ship_date)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_shipments_business_unit ON shipments(business_unit, ship_date)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_shipments_country_date ON shipments(country_code, ship_date)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_forecast_items_source ON forecast_items(source_type, source_id, deleted_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_forecast_round_details_tracking ON forecast_round_details(workflow_id, tracking_key, deleted_at)")
        db.commit()
        backfill_shipment_metadata(db)
        bootstrap_admin(db)
        seed_forecast_round_workflows(db)
        seed_forecast_round_details(db)
        seed_records(db)
        apply_task_hierarchy_migration(db)
        try:
            import_result = apply_source_data_import(
                db,
                APP_DIR,
                country_resolver=resolve_country,
                business_classifier=classify_business_unit,
            )
            if import_result and import_result.get("status") == "imported":
                app.logger.info("Legacy source data imported: %s", import_result)
        except Exception:
            app.logger.exception("Legacy source data import failed; the action remains retryable")
        try:
            historical_result = apply_historical_sales_correction(db, APP_DIR)
            if historical_result and historical_result.get("status") == "corrected":
                app.logger.info("Historical ERP sales correction applied: %s", historical_result)
        except Exception:
            app.logger.exception("Historical ERP sales correction failed; the action remains retryable")
        try:
            correction_result = apply_monthly_sales_fcst_correction(db, APP_DIR)
            if correction_result and correction_result.get("status") == "corrected":
                app.logger.info("Monthly sales FCST correction applied: %s", correction_result)
        except Exception:
            app.logger.exception("Monthly sales FCST correction failed; the action remains retryable")
        try:
            customer_result = migrate_legacy_customer_data(db, country_resolver=resolve_country)
            if customer_result.get("customers") or customer_result.get("logistics"):
                app.logger.info("Customer master migration applied: %s", customer_result)
        except Exception:
            app.logger.exception("Customer master migration failed; existing account data remains unchanged")
        task_result = apply_major_tasks_legacy_migration(db, utc_now)
        if task_result.get("tasks") or task_result.get("actions"):
            app.logger.info("Major-task legacy migration applied: %s", task_result)
        # A fresh database imports legacy shipment sources after the first
        # metadata pass. Run the versioned backfill once more so fresh and
        # rolling deployments finish with the same shipment classification.
        backfill_shipment_metadata(db)
        db.commit()


def insert_forecast_round_workflow(db, forecast_month, round_no, actor_user_id=None, source=None):
    """Create one editable workflow stage and its fixed entry/checklist rows."""
    now = utc_now()
    workflow_id = uuid.uuid4().hex
    source = source or {}
    db.execute(
        """
        INSERT INTO forecast_round_workflows
          (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, jpy_krw, cny_krw,
           status, notes, source_name, source_version, created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            workflow_id, forecast_month, round_no, source.get("as_of_date") or None,
            float(source.get("usd_krw") or 0), float(source.get("eur_krw") or 0),
            float(source.get("jpy_krw") or 0), float(source.get("cny_krw") or 0),
            str(source.get("notes") or "")[:2000], source.get("source_name"),
            source.get("source_version"), actor_user_id, actor_user_id, now, now,
        ),
    )
    source_entries = source.get("entries") or {}
    for business_unit, _label in FORECAST_ROUND_BUSINESS_UNITS:
        values = source_entries.get(business_unit) or {}
        db.execute(
            """
            INSERT INTO forecast_round_entries
              (id, workflow_id, business_unit, plan_krw, initial_fcst_krw, first_expected_krw,
               carryover_krw, current_month_krw, pipeline_krw, next_month_krw,
               next_pipeline_krw, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex, workflow_id, business_unit, float(values.get("plan") or 0),
                float(values.get("initial_fcst") or 0), float(values.get("first_expected") or 0),
                float(values.get("carryover") or 0), float(values.get("current_month") or 0),
                float(values.get("pipeline") or 0), float(values.get("next_month") or 0),
                float(values.get("next_pipeline") or 0), str(values.get("notes") or "")[:1000],
                now, now,
            ),
        )
    for sort_order, (check_key, label) in enumerate(FORECAST_ROUND_CHECKLIST, start=1):
        db.execute(
            """
            INSERT INTO forecast_round_checklist
              (id, workflow_id, check_key, label, required, completed, note, sort_order)
            VALUES (?, ?, ?, ?, 1, 0, '', ?)
            """,
            (uuid.uuid4().hex, workflow_id, check_key, label, sort_order),
        )
    return workflow_id


def seed_forecast_round_workflows(db):
    """Migrate the reviewed workbook summary once without overwriting later edits."""
    action_key = "forecast-round-workflow-seed:2026-08-31-v1"
    if db.execute("SELECT 1 FROM one_time_actions WHERE action_key = ?", (action_key,)).fetchone():
        return
    try:
        with open(FORECAST_ROUND_OVERVIEW_PATH, encoding="utf-8") as source_file:
            source = json.load(source_file)
        forecast_month = str(source.get("forecast_month") or "")
        if not valid_forecast_month(forecast_month):
            raise ValueError("The workbook seed forecast month is invalid")
        actor = db.execute(
            """
            SELECT id, username FROM users
            WHERE status = 'active' AND deleted_at IS NULL
            ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'manager' THEN 1 ELSE 2 END, id
            LIMIT 1
            """
        ).fetchone()
        actor_id = actor["id"] if actor else None
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT COUNT(*) AS count FROM forecast_round_workflows WHERE forecast_month = ?",
            (forecast_month,),
        ).fetchone()["count"]
        if not existing:
            insert_forecast_round_workflow(
                db, forecast_month, 0, actor_id,
                {"source_name": source.get("source_name"), "source_version": source.get("version"),
                 "notes": "해외사업부 실무 입력 전 미정 단계"},
            )
            for source_round in source.get("rounds") or []:
                round_no = int(source_round.get("round_no") or 0)
                if round_no not in {1, 2, 3}:
                    continue
                cycle = db.execute(
                    "SELECT usd_krw, eur_krw, jpy_krw, cny_krw FROM forecast_cycles WHERE forecast_month = ? AND round_no = ?",
                    (forecast_month, round_no),
                ).fetchone()
                rates = row_dict(cycle) or {}
                insert_forecast_round_workflow(
                    db, forecast_month, round_no, actor_id,
                    {
                        "as_of_date": source_round.get("as_of_date"),
                        "usd_krw": rates.get("usd_krw") or source_round.get("exchange_rate") or 0,
                        "eur_krw": rates.get("eur_krw") or 0,
                        "jpy_krw": rates.get("jpy_krw") or 0,
                        "cny_krw": rates.get("cny_krw") or 0,
                        "source_name": source.get("source_name"),
                        "source_version": source.get("version"),
                        "notes": source_round.get("status_note") or "엑셀 요약값",
                        "entries": source_round.get("business_units") or {},
                    },
                )
        now = utc_now()
        db.execute("INSERT INTO one_time_actions (action_key, applied_at) VALUES (?, ?)", (action_key, now))
        db.execute(
            """
            INSERT INTO audit_logs
              (occurred_at, actor_user_id, actor_username, action, entity_type, entity_id, summary)
            VALUES (?, ?, ?, 'FORECAST_ROUND_WORKFLOW_SEED', 'forecast_round_workflow', ?, ?)
            """,
            (now, actor_id, actor["username"] if actor else "system", forecast_month,
             f"{forecast_month} 미정·1·2·3차 업무관리 초기값 생성"),
        )
        db.commit()
    except Exception:
        rollback_quietly(db)
        app.logger.exception("Forecast round workflow seed failed; the action remains retryable")


def insert_forecast_round_detail(db, workflow_id, values, actor_user_id=None, source_type="manual"):
    """Insert one standalone FCST detail row without linking other modules."""
    now = utc_now()
    detail_id = uuid.uuid4().hex
    tracking_key = values.get("tracking_key") or detail_id
    db.execute(
        """
        INSERT INTO forecast_round_details
          (id, workflow_id, tracking_key, source_key, source_row, sales_stage, progress_status, management_type, business_unit, classification,
           country_code, country_name, account_code, account_name, product_code, item_name,
           owner_name, timing_note, currency, plan_foreign, plan_krw, carryover_foreign,
           carryover_krw, current_foreign, current_krw, next_foreign, next_krw,
           order_agreed_at, po_received_at, pi_sent_at, payment_expected_at,
           payment_completed_at, shipment_expected_at, shipment_completed_at,
           shipping_completed_at, target_date, applied_rate, change_reason, notes, source_type, created_by, updated_by,
           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            detail_id, workflow_id, tracking_key, values.get("source_key"), values.get("source_row"),
            values.get("sales_stage") or "undecided", forecast_round_detail_progress_status(values),
            values.get("management_type") or "regular",
            values.get("business_unit") or "dental",
            str(values.get("classification") or "")[:100], values.get("country_code"),
            str(values.get("country_name") or "")[:150], values.get("account_code"),
            str(values.get("account_name") or "")[:200], values.get("product_code"),
            str(values.get("item_name") or "품목 미지정")[:200],
            str(values.get("owner_name") or "")[:100], str(values.get("timing_note") or "")[:200],
            values.get("currency") or "USD",
            *[float(values.get(field) or 0) for field in FORECAST_ROUND_DETAIL_AMOUNT_FIELDS[:8]],
            *[values.get(field) or None for field in FORECAST_ROUND_DETAIL_DATE_FIELDS],
            values.get("target_date") or None, float(values.get("applied_rate") or 0),
            str(values.get("change_reason") or "")[:500], str(values.get("notes") or "")[:3000],
            source_type, actor_user_id, actor_user_id, now, now,
        ),
    )
    return detail_id


def seed_forecast_round_details(db):
    """Import the uploaded workbook's detail lines once, preserving later site edits."""
    action_key = "forecast-round-detail-seed:2026-08-31-v1"
    if db.execute("SELECT 1 FROM one_time_actions WHERE action_key = ?", (action_key,)).fetchone():
        return
    try:
        with open(FORECAST_ROUND_DETAILS_PATH, encoding="utf-8") as source_file:
            source = json.load(source_file)
        forecast_month = str(source.get("forecast_month") or "")
        if not valid_forecast_month(forecast_month):
            raise ValueError("The workbook detail seed forecast month is invalid")
        actor = db.execute(
            """
            SELECT id, username FROM users
            WHERE status = 'active' AND deleted_at IS NULL
            ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'manager' THEN 1 ELSE 2 END, id
            LIMIT 1
            """
        ).fetchone()
        actor_id = actor["id"] if actor else None
        workflows = {
            int(row["round_no"]): row["id"]
            for row in db.execute(
                "SELECT id, round_no FROM forecast_round_workflows WHERE forecast_month = ?",
                (forecast_month,),
            ).fetchall()
        }
        if len(workflows) != 4:
            raise ValueError("Forecast round workflows must exist before detail import")
        db.execute("BEGIN IMMEDIATE")
        inserted = 0
        for detail in source.get("details") or []:
            round_no = int(detail.get("round_no") or 0)
            if round_no not in workflows:
                continue
            insert_forecast_round_detail(db, workflows[round_no], detail, actor_id, "workbook")
            inserted += 1
        now = utc_now()
        db.execute("INSERT INTO one_time_actions (action_key, applied_at) VALUES (?, ?)", (action_key, now))
        db.execute(
            """
            INSERT INTO audit_logs
              (occurred_at, actor_user_id, actor_username, action, entity_type, entity_id, summary)
            VALUES (?, ?, ?, 'FORECAST_ROUND_DETAIL_SEED', 'forecast_round_detail', ?, ?)
            """,
            (now, actor_id, actor["username"] if actor else "system", forecast_month,
             f"{forecast_month} 업로드 엑셀 상세자료 {inserted}건 생성 · 기존 메뉴/ERP 미연동"),
        )
        db.commit()
    except Exception:
        rollback_quietly(db)
        app.logger.exception("Forecast round detail seed failed; the action remains retryable")


def bootstrap_admin(db):
    existing = db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    if existing:
        return
    username = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    display_name = os.environ.get("BOOTSTRAP_ADMIN_NAME", "시스템 관리자").strip()
    if not password:
        return
    now = utc_now()
    cursor = db.execute(
        """
        INSERT INTO users
          (username, display_name, email, password_hash, role, status, created_at,
           updated_at, password_changed_at, must_change_password)
        VALUES (?, ?, ?, ?, 'admin', 'active', ?, ?, NULL, 1)
        """,
        (username, display_name, None, generate_password_hash(password), now, now),
    )
    db.execute(
        """
        INSERT INTO audit_logs
          (occurred_at, actor_user_id, actor_username, action, entity_type, entity_id, summary)
        VALUES (?, ?, ?, 'BOOTSTRAP', 'user', ?, ?)
        """,
        (now, cursor.lastrowid, username, str(cursor.lastrowid), "최초 관리자 계정 생성"),
    )
    db.commit()


def seed_records(db):
    admin = db.execute("SELECT * FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
    if not admin:
        return
    if db.execute("SELECT COUNT(*) AS count FROM records").fetchone()["count"]:
        return
    seeds = [
        ("account", "ZimVie", "active", "Europe", "Germany", 0, "USD", {"stage": "Strategic", "contact": "Global partner", "priority": "High"}),
        ("account", "ASNAN", "active", "Middle East", "Saudi Arabia", 0, "USD", {"stage": "Active", "priority": "High"}),
        ("account", "Medincode", "active", "Southeast Asia", "Vietnam", 0, "USD", {"stage": "Active", "priority": "High"}),
        ("account", "Euroteknika", "active", "Europe", "France", 0, "EUR", {"stage": "Active", "priority": "Medium"}),
        ("account", "BDH", "active", "Middle East", "UAE", 0, "USD", {"stage": "Active", "priority": "Medium"}),
        ("account", "Aspident", "active", "Europe", "Poland", 0, "EUR", {"stage": "Prospect", "priority": "Medium"}),
        ("pipeline", "ZimVie EU launch", "proposal", "Europe", "Germany", 850000, "USD", {"probability": 70, "next_action": "Regulatory and supply plan"}),
        ("pipeline", "Sunriser distribution", "negotiation", "Asia", "China", 420000, "USD", {"probability": 55, "next_action": "Commercial terms"}),
        ("pipeline", "New Dental System", "qualified", "Europe", "Italy", 280000, "EUR", {"probability": 40, "next_action": "Product evaluation"}),
        ("pipeline", "DIO joint opportunity", "discovery", "North America", "United States", 360000, "USD", {"probability": 30, "next_action": "Technical workshop"}),
        ("task", "ZimVie 월간 수요예측 확인", "in_progress", "Europe", "Germany", 0, "USD", {"priority": "High", "description": "파트너 수요예측과 출고계획 대조"}),
        ("task", "베트남 미수금 확인", "todo", "Southeast Asia", "Vietnam", 0, "USD", {"priority": "High", "description": "거래처별 회수 예정일 확인"}),
        ("agenda", "해외사업부 월간 리뷰", "scheduled", "Global", "", 0, "USD", {"priority": "High", "description": "매출·파이프라인·미수금·프로모션 리뷰"}),
        ("promotion", "EU distributor campaign", "planned", "Europe", "", 45000, "EUR", {"channel": "Distributor", "description": "현지 파트너 프로모션 계획"}),
        ("transport", "Vietnam regular shipment", "active", "Southeast Asia", "Vietnam", 0, "USD", {"incoterms": "CIF", "forwarder": "TBD", "lead_time_days": 14}),
    ]
    now = utc_now()
    due_dates = [None] * 10 + [
        (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat(),
        (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat(),
        (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat(),
        None,
        None,
    ]
    for idx, seed in enumerate(seeds):
        entity_type, title, status, region, country, amount, currency, payload = seed
        db.execute(
            """
            INSERT INTO records
              (id, entity_type, title, owner_id, status, due_date, region, country, amount,
               currency, payload_json, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                entity_type,
                title,
                admin["id"],
                status,
                due_dates[idx],
                region,
                country,
                amount,
                currency,
                safe_json(payload),
                admin["id"],
                admin["id"],
                now,
                now,
            ),
        )
    db.execute(
        """
        INSERT INTO audit_logs
          (occurred_at, actor_user_id, actor_username, action, entity_type, summary, after_json)
        VALUES (?, ?, ?, 'SEED', 'record', ?, ?)
        """,
        (now, admin["id"], admin["username"], "해외사업부 기준 데이터 생성", safe_json({"count": len(seeds)})),
    )
    db.commit()


def apply_task_hierarchy_migration(db):
    """Group the existing MEDPARKALLO country actions without losing their fields or history."""
    if db.execute(
        "SELECT 1 FROM one_time_actions WHERE action_key = ?",
        (TASK_HIERARCHY_ACTION_KEY,),
    ).fetchone():
        return

    candidates = []
    title_pattern = re.compile(r"^\[DENTAL\]\s*MEDPARKALLO 판매 확대_(#(\d+)\s+.+)$")
    for row in db.execute(
        "SELECT * FROM records WHERE entity_type = 'task' AND deleted_at IS NULL"
    ).fetchall():
        match = title_pattern.match(row["title"])
        if match:
            candidates.append((int(match.group(2)), match.group(1), row))
    candidates.sort(key=lambda item: item[0])

    now = utc_now()
    if candidates:
        parent_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            "medpark-global-maps:task-group:dental-medparkallo-sales",
        ).hex
        parent = db.execute(
            "SELECT * FROM records WHERE id = ? AND deleted_at IS NULL", (parent_id,)
        ).fetchone()
        source = candidates[0][2]
        statuses = [item[2]["status"] for item in candidates]
        parent_status = (
            "done" if statuses and all(status in {"done", "completed"} for status in statuses)
            else "blocked" if "blocked" in statuses
            else "in_progress" if "in_progress" in statuses
            else "todo"
        )
        due_dates = [item[2]["due_date"] for item in candidates if item[2]["due_date"]]
        currencies = {item[2]["currency"] for item in candidates}
        parent_currency = currencies.pop() if len(currencies) == 1 else "USD"
        parent_payload = {
            "task_kind": "group",
            "business_unit": "dental",
            "priority": "Medium",
            "description": "국가별 세부항목을 펼쳐서 관리합니다.",
        }
        if not parent:
            db.execute(
                """
                INSERT INTO records
                  (id, entity_type, title, owner_id, status, due_date, region, country, amount,
                   currency, payload_json, created_by, updated_by, created_at, updated_at)
                VALUES (?, 'task', ?, ?, ?, ?, '', '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parent_id,
                    "[DENTAL] MEDPARKALLO 판매 확대",
                    source["owner_id"],
                    parent_status,
                    min(due_dates) if due_dates else None,
                    sum(float(item[2]["amount"] or 0) for item in candidates),
                    parent_currency,
                    safe_json(parent_payload),
                    source["created_by"],
                    source["updated_by"],
                    min(item[2]["created_at"] for item in candidates),
                    now,
                ),
            )
        for order_no, detail_title, row in candidates:
            payload = parse_payload(row["payload_json"])
            payload.update({
                "task_kind": "detail",
                "parent_task_id": parent_id,
                "task_order": order_no,
            })
            db.execute(
                "UPDATE records SET title = ?, payload_json = ?, updated_at = ? WHERE id = ?",
                (detail_title, safe_json(payload), now, row["id"]),
            )
        db.execute(
            """
            INSERT INTO audit_logs
              (occurred_at, actor_username, action, entity_type, entity_id, summary, after_json)
            VALUES (?, 'system', 'TASK_HIERARCHY_MIGRATE', 'task', ?, ?, ?)
            """,
            (
                now,
                parent_id,
                "[DENTAL] MEDPARKALLO 판매 확대 세부항목 구조 적용",
                safe_json({"detail_count": len(candidates)}),
            ),
        )

    db.execute(
        "INSERT INTO one_time_actions (action_key, applied_at) VALUES (?, ?)",
        (TASK_HIERARCHY_ACTION_KEY, now),
    )
    db.commit()


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
    )
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif response.mimetype == "text/html":
        # Always revalidate the application shell.  Customer Master assets are
        # versioned in index.html, so a cached shell must not pin a signed-in
        # browser to an older operability bundle after a production update.
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(PUBLIC_DIR, filename)


@app.before_request
def wait_for_database_initialization():
    """Protect business APIs while allowing authentication on the ready core DB."""
    if not request.path.startswith("/api/"):
        return None
    auth_paths = {"/api/auth/me", "/api/auth/login", "/api/auth/register", "/api/auth/logout"}
    if DATABASE_READY.is_set():
        if DATABASE_SCHEMA_READY.is_set():
            return None
        # Another rolling instance may have completed the additive migration.
        # Reconcile this worker before making the user wait again.
        if release_schema_is_ready():
            DATABASE_SCHEMA_READY.set()
            return None
        # The users/session tables are part of the core schema. Existing users
        # must still be able to authenticate while optional modules finish.
        if request.path in auth_paths:
            return None
    if DATABASE_INIT_ERROR:
        return jsonify(
            error="데이터베이스 초기화에 실패했습니다. 관리자에게 문의하세요.",
            code="DATABASE_INIT_FAILED",
        ), 503
    if DATABASE_SCHEMA_READY.wait(timeout=10):
        return None
    if DATABASE_INIT_ERROR:
        return jsonify(
            error="데이터베이스 초기화에 실패했습니다. 관리자에게 문의하세요.",
            code="DATABASE_INIT_FAILED",
        ), 503
    return jsonify(
        error="새 버전 적용을 마무리하고 있습니다. 잠시 후 다시 시도하세요.",
        code="DATABASE_INITIALIZING",
    ), 503


@app.before_request
def require_login_for_application_api():
    """Require a valid session before returning any business data."""
    if not request.path.startswith("/api/"):
        return None
    if request.path in {"/api/auth/me", "/api/auth/login", "/api/auth/register", "/api/auth/logout"}:
        return None
    user = current_user_row()
    if not user or user["status"] != "active":
        session.clear()
        return jsonify(error="로그인이 필요합니다."), 401
    return None


@app.get("/health")
def health():
    # A schema migration may finish on disk while a rolling worker still holds
    # its pre-migration in-memory event. Reconcile the event on health checks so
    # an already-ready database does not remain marked as pending.
    if DATABASE_READY.is_set() and not DATABASE_SCHEMA_READY.is_set() and release_schema_is_ready():
        DATABASE_SCHEMA_READY.set()
    if not DATABASE_READY.is_set():
        return jsonify(
            status="starting" if not DATABASE_INIT_ERROR else "degraded",
            version=APP_VERSION,
            database=False,
            database_writable=DATABASE_STORAGE_WRITABLE,
            storage_migrated=DATABASE_STORAGE_MIGRATED,
            migration_pending=not bool(DATABASE_INIT_ERROR),
            erp_configured=erp_configured(),
        ), 200 if not DATABASE_INIT_ERROR else 503
    if DATABASE_INIT_ERROR:
        return jsonify(
            status="degraded",
            version=APP_VERSION,
            database=False,
            database_writable=DATABASE_STORAGE_WRITABLE,
            storage_migrated=DATABASE_STORAGE_MIGRATED,
            migration_pending=False,
            erp_configured=erp_configured(),
        ), 503
    if not DATABASE_SCHEMA_READY.is_set():
        return jsonify(
            status="ok",
            version=APP_VERSION,
            database=True,
            database_writable=DATABASE_STORAGE_WRITABLE,
            storage_migrated=DATABASE_STORAGE_MIGRATED,
            migration_pending=True,
            erp_configured=erp_configured(),
        )
    try:
        get_db().execute("SELECT 1").fetchone()
        db_ok = True
    except sqlite3.Error:
        db_ok = False
    return jsonify(
        status="ok" if db_ok and DATABASE_STORAGE_WRITABLE else "degraded",
        version=APP_VERSION,
        database=db_ok,
        database_writable=DATABASE_STORAGE_WRITABLE,
        storage_migrated=DATABASE_STORAGE_MIGRATED,
        erp_configured=erp_configured(),
    ), 200 if db_ok and DATABASE_STORAGE_WRITABLE else 503


@app.get("/api/auth/me")
def auth_me():
    user = current_user_row()
    if not user or user["status"] != "active":
        return jsonify(authenticated=False, setup_required=get_db().execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0)
    token = session.get("csrf_token") or secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return jsonify(
        authenticated=True,
        user=public_user(user),
        csrf_token=token,
        permissions={
            "can_edit": user["role"] in EDIT_ROLES,
            "can_edit_all": user["role"] in MANAGE_ROLES,
            "can_manage_users": user["role"] == "admin",
            "can_sync_erp": user["role"] in MANAGE_ROLES,
        },
    )


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    display_name = str(data.get("display_name", "")).strip()
    email = str(data.get("email", "")).strip().lower() or None
    password = str(data.get("password", ""))
    password_confirm = str(data.get("password_confirm", ""))
    username_error = validate_username(username)
    if username_error:
        return jsonify(error=username_error), 400
    if len(display_name) < 2 or len(display_name) > 50:
        return jsonify(error="이름은 2~50자로 입력하세요."), 400
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(error="이메일 형식이 올바르지 않습니다."), 400
    if password != password_confirm:
        return jsonify(error="비밀번호 확인이 일치하지 않습니다."), 400
    password_error = validate_password(password)
    if password_error:
        return jsonify(error=password_error), 400
    now = utc_now()
    db = get_db()
    try:
        cursor = db.execute(
            """
            INSERT INTO users
              (username, display_name, email, password_hash, role, status, created_at, updated_at, password_changed_at)
            VALUES (?, ?, ?, ?, 'viewer', 'pending', ?, ?, ?)
            """,
            (username, display_name, email, generate_password_hash(password), now, now, now),
        )
        new_user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        audit("REGISTER", "user", cursor.lastrowid, f"{username} 사용자 등록 신청", None, public_user(new_user), actor=None)
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="이미 사용 중인 아이디 또는 이메일입니다."), 409
    return jsonify(message="등록 신청이 완료되었습니다. 관리자의 승인 후 로그인할 수 있습니다."), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    rate_key = f"{client_ip()}:{username.lower()}"
    attempts = [ts for ts in FAILED_LOGINS.get(rate_key, []) if time.time() - ts < 600]
    FAILED_LOGINS[rate_key] = attempts
    if len(attempts) >= 8:
        return jsonify(error="로그인 시도가 너무 많습니다. 10분 후 다시 시도하세요."), 429
    user = get_db().execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        FAILED_LOGINS[rate_key].append(time.time())
        return jsonify(error="아이디 또는 비밀번호가 올바르지 않습니다."), 401
    if user["deleted_at"] or user["status"] == "disabled":
        return jsonify(error="사용이 중지된 계정입니다. 관리자에게 문의하세요."), 403
    if user["status"] != "active":
        return jsonify(error="승인 대기 중인 계정입니다."), 403
    FAILED_LOGINS.pop(rate_key, None)
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["csrf_token"] = secrets.token_urlsafe(32)
    # Authentication and session creation must not fail because an optional
    # last-login/audit write is temporarily unavailable.
    try:
        db = get_db()
        logged_in_at = utc_now()
        db.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?", (logged_in_at, logged_in_at, user["id"]))
        audit("LOGIN", "session", user["id"], f"{user['username']} 로그인", actor=user)
        db.commit()
    except sqlite3.Error as exc:
        try:
            get_db().rollback()
        except sqlite3.Error:
            pass
        app.logger.warning("login_metadata_write_failed user_id=%s error=%s", user["id"], exc)
    return jsonify(message="로그인되었습니다.", user=public_user(user), csrf_token=session["csrf_token"])


@app.post("/api/auth/logout")
def logout():
    # Logout must never depend on database availability or audit-log writes.
    # Clear the signed session first and explicitly expire the browser cookie.
    session.clear()
    session.modified = True
    response = jsonify(message="로그아웃되었습니다.")
    response.delete_cookie(
        app.config.get("SESSION_COOKIE_NAME", "session"),
        path=app.config.get("SESSION_COOKIE_PATH") or "/",
        domain=app.config.get("SESSION_COOKIE_DOMAIN"),
        secure=bool(app.config.get("SESSION_COOKIE_SECURE")),
        httponly=True,
        samesite=app.config.get("SESSION_COOKIE_SAMESITE") or "Lax",
    )
    return response


@app.post("/api/auth/password")
@auth_required
@csrf_required
def change_password():
    data = request.get_json(silent=True) or {}
    current = str(data.get("current_password", ""))
    new_password = str(data.get("new_password", ""))
    new_password_confirm = str(data.get("new_password_confirm", ""))
    if not check_password_hash(g.current_user["password_hash"], current):
        return jsonify(error="현재 비밀번호가 올바르지 않습니다."), 400
    if new_password != new_password_confirm:
        return jsonify(error="새 비밀번호 확인이 일치하지 않습니다."), 400
    password_error = validate_password(new_password)
    if password_error:
        return jsonify(error=password_error), 400
    if check_password_hash(g.current_user["password_hash"], new_password):
        return jsonify(error="현재 비밀번호와 다른 새 비밀번호를 입력하세요."), 400
    now = utc_now()
    db = get_db()
    db.execute(
        "UPDATE users SET password_hash = ?, password_changed_at = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
        (generate_password_hash(new_password), now, now, g.current_user["id"]),
    )
    audit(
        "PASSWORD_CHANGE",
        "user",
        g.current_user["id"],
        "본인 비밀번호 변경",
        {"must_change_password": bool(g.current_user["must_change_password"])},
        {"must_change_password": False, "password_changed_at": now},
    )
    db.commit()
    session["csrf_token"] = secrets.token_urlsafe(32)
    updated = db.execute("SELECT * FROM users WHERE id = ?", (g.current_user["id"],)).fetchone()
    return jsonify(message="비밀번호가 변경되었습니다.", user=public_user(updated), csrf_token=session["csrf_token"])


@app.get("/api/users")
@role_required("admin", "manager")
def list_users():
    rows = get_db().execute(
        "SELECT * FROM users WHERE deleted_at IS NULL ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, display_name"
    ).fetchall()
    return jsonify(users=[public_user(row) for row in rows])


@app.post("/api/users")
@role_required("admin")
@csrf_required
def create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    display_name = str(data.get("display_name", "")).strip()
    email = str(data.get("email", "")).strip().lower() or None
    password = str(data.get("password", ""))
    password_confirm = str(data.get("password_confirm", ""))
    role = str(data.get("role", "viewer")).strip()
    status = str(data.get("status", "active")).strip()
    username_error = validate_username(username)
    if username_error:
        return jsonify(error=username_error), 400
    if len(display_name) < 2 or len(display_name) > 50:
        return jsonify(error="이름은 2~50자로 입력하세요."), 400
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(error="이메일 형식이 올바르지 않습니다."), 400
    if password != password_confirm:
        return jsonify(error="임시 비밀번호 확인이 일치하지 않습니다."), 400
    password_error = validate_password(password)
    if password_error:
        return jsonify(error=password_error), 400
    if role not in ALLOWED_ROLES or status not in {"pending", "active", "disabled"}:
        return jsonify(error="역할 또는 상태 값이 올바르지 않습니다."), 400
    now = utc_now()
    db = get_db()
    try:
        cursor = db.execute(
            """
            INSERT INTO users
              (username, display_name, email, password_hash, role, status, created_at,
               updated_at, password_changed_at, must_change_password, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)
            """,
            (
                username,
                display_name,
                email,
                generate_password_hash(password),
                role,
                status,
                now,
                now,
                g.current_user["id"],
            ),
        )
        created = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        audit(
            "CREATE",
            "user",
            cursor.lastrowid,
            f"{username} 사용자 계정 생성 · 최초 로그인 비밀번호 변경 필요",
            None,
            public_user(created),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="이미 사용 중인 아이디 또는 이메일입니다."), 409
    return jsonify(message="사용자가 등록되었습니다. 임시 비밀번호로 첫 로그인 후 비밀번호를 변경해야 합니다.", user=public_user(created)), 201


@app.get("/api/users/directory")
@auth_required
def user_directory():
    rows = get_db().execute(
        "SELECT id, display_name, role FROM users WHERE status = 'active' AND deleted_at IS NULL ORDER BY display_name"
    ).fetchall()
    return jsonify(users=[row_dict(row) for row in rows])


@app.patch("/api/users/<int:user_id>")
@role_required("admin")
@csrf_required
def update_user(user_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    existing = db.execute("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
    if not existing:
        return jsonify(error="사용자를 찾을 수 없습니다."), 404
    role = str(data.get("role", existing["role"])).strip()
    status = str(data.get("status", existing["status"])).strip()
    display_name = str(data.get("display_name", existing["display_name"])).strip()
    email = str(data.get("email", existing["email"] or "")).strip().lower() or None
    if role not in ALLOWED_ROLES or status not in {"pending", "active", "disabled"}:
        return jsonify(error="역할 또는 상태 값이 올바르지 않습니다."), 400
    if existing["id"] == g.current_user["id"] and (role != "admin" or status != "active"):
        return jsonify(error="현재 로그인한 관리자 계정의 권한은 낮추거나 중지할 수 없습니다."), 400
    before = public_user(existing)
    try:
        db.execute(
            "UPDATE users SET display_name = ?, email = ?, role = ?, status = ?, updated_at = ? WHERE id = ?",
            (display_name, email, role, status, utc_now(), user_id),
        )
        updated = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        audit("UPDATE", "user", user_id, f"{existing['username']} 사용자 권한/상태 수정", before, public_user(updated))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="이미 사용 중인 이메일입니다."), 409
    return jsonify(message="사용자 정보가 수정되었습니다.", user=public_user(updated))


@app.post("/api/users/<int:user_id>/reset-password")
@role_required("admin")
@csrf_required
def reset_user_password(user_id):
    if user_id == g.current_user["id"]:
        return jsonify(error="본인 비밀번호는 상단의 ‘비밀번호 변경’에서 변경하세요."), 400
    data = request.get_json(silent=True) or {}
    password = str(data.get("password", ""))
    password_confirm = str(data.get("password_confirm", ""))
    if password != password_confirm:
        return jsonify(error="임시 비밀번호 확인이 일치하지 않습니다."), 400
    password_error = validate_password(password)
    if password_error:
        return jsonify(error=password_error), 400
    password_hash = generate_password_hash(password)
    with DATABASE_WRITE_LOCK:
        for attempt in range(4):
            write_db = None
            try:
                ensure_db_dir()
                write_db = sqlite3.connect(DB_PATH, timeout=5)
                write_db.row_factory = sqlite3.Row
                write_db.execute("PRAGMA foreign_keys = ON")
                write_db.execute("PRAGMA busy_timeout = 5000")
                write_db.execute("BEGIN IMMEDIATE")
                existing = write_db.execute(
                    "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL",
                    (user_id,),
                ).fetchone()
                if not existing:
                    rollback_quietly(write_db)
                    return jsonify(error="사용자를 찾을 수 없습니다."), 404
                now = utc_now()
                write_db.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, password_changed_at = NULL, must_change_password = 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (password_hash, now, user_id),
                )
                updated = write_db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                # Commit the security-critical password update first. An audit
                # storage issue must not leave an administrator unable to
                # recover a user account.
                write_db.commit()
                try:
                    write_db.execute("BEGIN IMMEDIATE")
                    audit(
                        "PASSWORD_RESET",
                        "user",
                        user_id,
                        f"{existing['username']} 임시 비밀번호 발급 · 최초 로그인 변경 필요",
                        {"must_change_password": bool(existing["must_change_password"])},
                        {"must_change_password": True},
                        actor=g.current_user,
                        connection=write_db,
                    )
                    write_db.commit()
                except sqlite3.Error as audit_error:
                    rollback_quietly(write_db)
                    app.logger.warning(
                        "password_reset_audit_write_failed user_id=%s error_type=%s",
                        user_id,
                        type(audit_error).__name__,
                    )
                return jsonify(message="임시 비밀번호가 발급되었습니다. 사용자는 다음 로그인 시 새 비밀번호로 변경해야 합니다.", user=public_user(updated))
            except sqlite3.OperationalError as error:
                if write_db is not None:
                    rollback_quietly(write_db)
                if sqlite_is_busy(error):
                    if attempt < 3:
                        time.sleep(0.25 * (attempt + 1))
                        continue
                    app.logger.warning("password_reset_database_busy user_id=%s attempts=%s", user_id, attempt + 1)
                    return jsonify(
                        error="다른 데이터 저장 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.",
                        code="DATABASE_BUSY",
                    ), 503
                if "readonly" in str(error).lower():
                    app.logger.exception("password_reset_database_readonly user_id=%s", user_id)
                    return jsonify(
                        error="사용자 데이터 저장소의 쓰기 권한을 확인해 주세요.",
                        code="DATABASE_READ_ONLY",
                    ), 503
                raise
            except sqlite3.Error:
                if write_db is not None:
                    rollback_quietly(write_db)
                raise
            finally:
                if write_db is not None:
                    write_db.close()


@app.delete("/api/users/<int:user_id>")
@role_required("admin")
@csrf_required
def delete_user(user_id):
    if user_id == g.current_user["id"]:
        return jsonify(error="현재 로그인한 계정은 삭제할 수 없습니다."), 400
    db = get_db()
    existing = db.execute("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)).fetchone()
    if not existing:
        return jsonify(error="사용자를 찾을 수 없습니다."), 404
    before = public_user(existing)
    now = utc_now()
    db.execute("UPDATE users SET status = 'disabled', deleted_at = ?, updated_at = ? WHERE id = ?", (now, now, user_id))
    audit("DELETE", "user", user_id, f"{existing['username']} 사용자 비활성 삭제", before, {"deleted_at": now})
    db.commit()
    return jsonify(message="사용자가 비활성 삭제되었습니다. 이력은 유지됩니다.")


def can_modify_record(user, record):
    if user["role"] in MANAGE_ROLES:
        return True
    return user["role"] == "editor" and (record["created_by"] == user["id"] or record["owner_id"] == user["id"])


@app.get("/api/records")
def list_records():
    user = current_user_row()
    entity_type = request.args.get("type", "").strip()
    include_deleted = (
        request.args.get("include_deleted") == "1"
        and user is not None
        and user["status"] == "active"
        and user["role"] in MANAGE_ROLES
    )
    clauses = []
    params = []
    if entity_type:
        if entity_type not in ENTITY_TYPES:
            return jsonify(error="지원하지 않는 데이터 유형입니다."), 400
        if entity_type == "task":
            return jsonify(records=[], public_mode=user is None, migrated_to="/api/major-tasks")
        clauses.append("r.entity_type = ?")
        params.append(entity_type)
    else:
        clauses.append("r.entity_type <> 'task'")
    if not include_deleted:
        clauses.append("r.deleted_at IS NULL")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = get_db().execute(
        """
        SELECT r.*, u.display_name AS owner_name, c.display_name AS creator_name
        FROM records r
        LEFT JOIN users u ON u.id = r.owner_id
        LEFT JOIN users c ON c.id = r.created_by
        """ + where + " ORDER BY COALESCE(r.due_date, '9999-12-31'), r.updated_at DESC",
        params,
    ).fetchall()
    records = []
    for row in rows:
        item = public_record(row)
        if not user:
            for key in ("owner_id", "created_by", "updated_by", "deleted_by", "creator_name"):
                item.pop(key, None)
        records.append(item)
    return jsonify(records=records, public_mode=user is None)


def normalize_record_input(data, existing=None):
    entity_type = str(data.get("entity_type", existing["entity_type"] if existing else "")).strip()
    title = str(data.get("title", existing["title"] if existing else "")).strip()
    if entity_type not in ENTITY_TYPES:
        raise ValueError("지원하지 않는 데이터 유형입니다.")
    if not title or len(title) > 200:
        raise ValueError("제목은 1~200자로 입력하세요.")
    owner_id = data.get("owner_id", existing["owner_id"] if existing else None)
    owner_id = int(owner_id) if str(owner_id or "").isdigit() else None
    status = str(data.get("status", existing["status"] if existing else "active")).strip()[:40] or "active"
    due_date = str(data.get("due_date", existing["due_date"] if existing else "") or "").strip() or None
    if due_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_date):
        raise ValueError("날짜 형식이 올바르지 않습니다.")
    region = str(data.get("region", existing["region"] if existing else "") or "").strip()[:80]
    country = str(data.get("country", existing["country"] if existing else "") or "").strip()[:80]
    try:
        amount = float(data.get("amount", existing["amount"] if existing else 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("금액은 숫자로 입력하세요.")
    currency = str(data.get("currency", existing["currency"] if existing else "USD") or "USD").upper()[:8]
    payload = data.get("payload", parse_payload(existing["payload_json"]) if existing else {})
    if not isinstance(payload, dict):
        raise ValueError("상세 데이터 형식이 올바르지 않습니다.")
    if entity_type == "task":
        payload["company_name"] = str(payload.get("company_name") or "").strip()[:200]
    return {
        "entity_type": entity_type,
        "title": title,
        "owner_id": owner_id,
        "status": status,
        "due_date": due_date,
        "region": region,
        "country": country,
        "amount": amount,
        "currency": currency,
        "payload_json": safe_json(payload),
    }


def payload_float(payload, key, default=0.0):
    try:
        value = float(payload.get(key, default) or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{key} 값은 숫자로 입력하세요.")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{key} 값이 올바르지 않습니다.")
    return value


def validate_iso_date(value, label):
    value = str(value or "").strip()
    if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label} 형식이 올바르지 않습니다.")
    return value


def validate_ratio_schedule(payload, prefix=""):
    ratio_keys = [f"{prefix}advance_ratio"] + [f"{prefix}installment_{index}_ratio" for index in range(1, 5)]
    ratios = [payload_float(payload, key) for key in ratio_keys]
    if any(value < 0 or value > 100 for value in ratios):
        raise ValueError("수금 비율은 각각 0~100%로 입력하세요.")
    total = sum(ratios)
    if total and not 99.5 <= total <= 100.5:
        raise ValueError(f"선금과 분할 수금 비율의 합계는 100%여야 합니다. 현재 {total:g}%입니다.")
    for index in range(1, 5):
        days = payload_float(payload, f"{prefix}installment_{index}_days")
        if days < 0 or days > 3650:
            raise ValueError("수금 기일은 0~3650일 범위로 입력하세요.")


def validate_record_business_rules(values, record_id=None):
    entity_type = values["entity_type"]
    payload = parse_payload(values["payload_json"])
    if values["amount"] < 0:
        raise ValueError("금액은 0 이상으로 입력하세요.")
    if entity_type == "account":
        validate_ratio_schedule(payload, "ar_")
    elif entity_type == "task":
        task_kind = str(payload.get("task_kind") or "").strip()
        if task_kind and task_kind not in {"group", "detail"}:
            raise ValueError("주요 업무의 대분류·세부항목 구분이 올바르지 않습니다.")
        parent_id = str(payload.get("parent_task_id") or "").strip()
        if task_kind == "group" and parent_id:
            raise ValueError("대분류는 다른 주요 업무의 세부항목이 될 수 없습니다.")
        if parent_id:
            if record_id and parent_id == record_id:
                raise ValueError("주요 업무를 자기 자신의 세부항목으로 지정할 수 없습니다.")
            parent = get_db().execute(
                "SELECT entity_type, payload_json FROM records WHERE id = ? AND deleted_at IS NULL",
                (parent_id,),
            ).fetchone()
            if not parent or parent["entity_type"] != "task":
                raise ValueError("연결할 주요 업무 대분류를 찾을 수 없습니다.")
            if parse_payload(parent["payload_json"]).get("parent_task_id"):
                raise ValueError("세부항목 아래에는 다시 세부항목을 만들 수 없습니다.")
    elif entity_type == "cash_plan":
        flow_type = str(payload.get("flow_type") or "").strip()
        if flow_type not in {"cash_in", "cash_out", "opening_liquid", "fixed_fund"}:
            raise ValueError("자금 구분을 수금·지출·기초잔액·고정자금 중에서 선택하세요.")
        for key, label in (
            ("plan_date", "자금계획일"), ("card_payment_date", "카드결제일"),
            ("execution_date", "자금실행일"), ("maturity_date", "만기도래일"),
        ):
            validate_iso_date(payload.get(key), label)
        for key in ("adjustment_rate", "payment_rate"):
            value = payload_float(payload, key, 100)
            if not 0 <= value <= 100:
                raise ValueError("달성률과 지급률은 0~100%로 입력하세요.")
        for key in ("exchange_rate", "actual_foreign_amount", "actual_krw_amount"):
            if payload_float(payload, key) < 0:
                raise ValueError("환율과 실행금액은 0 이상으로 입력하세요.")
    elif entity_type == "receivable":
        if values["amount"] <= 0:
            raise ValueError("채권 총액은 0보다 커야 합니다.")
        validate_ratio_schedule(payload)
        invoice_date = validate_iso_date(payload.get("invoice_date"), "인보이스일")
        ship_date = validate_iso_date(payload.get("ship_date"), "출고일")
        if not invoice_date and not ship_date:
            raise ValueError("출고일 또는 인보이스일을 입력하세요.")
        for index in range(0, 5):
            date_key = "advance_received_date" if index == 0 else f"receipt_{index}_date"
            amount_key = "advance_received_amount" if index == 0 else f"receipt_{index}_amount"
            validate_iso_date(payload.get(date_key), "실제 입금일")
            if payload_float(payload, amount_key) < 0:
                raise ValueError("실제 입금액은 0 이상으로 입력하세요.")
        validate_iso_date(payload.get("promise_date"), "회수약속일")
        validate_iso_date(payload.get("next_collection_date"), "다음 회수조치일")
        if payload_float(payload, "promise_amount") < 0:
            raise ValueError("회수약속금액은 0 이상으로 입력하세요.")
    elif entity_type == "promotion":
        if values["currency"] not in FORECAST_CURRENCIES:
            raise ValueError("프로모션 FCST 통화는 KRW·USD·EUR·JPY·CNY만 사용할 수 있습니다.")
        promotion_id = str(payload.get("promotion_id") or "").strip()
        if not promotion_id or len(promotion_id) > 80:
            raise ValueError("프로모션 고유 ID를 1~80자로 입력하세요. 예: A1 8월")
        target_month = str(payload.get("target_month") or "").strip()
        if not valid_forecast_month(target_month):
            raise ValueError("프로모션 매출 반영월을 YYYY-MM 형식으로 입력하세요.")
        for key, label in (
            ("start_date", "프로모션 시작일"), ("end_date", "프로모션 종료일"),
            ("target_ship_date", "목표 출고일"), ("completed_at", "완료일"),
        ):
            validate_iso_date(payload.get(key), label)
        for key in (
            "proposal_target_date", "proposal_actual_date", "approval_target_date", "approval_actual_date",
            "offer_target_date", "offer_actual_date", "order_target_date", "order_actual_date",
            "promotion_payment_target_date", "promotion_payment_actual_date",
            "promotion_shipment_target_date", "promotion_shipment_actual_date",
        ):
            validate_iso_date(payload.get(key), "프로모션 타임라인 일자")
        for key in ("baseline_unit_price", "promotion_unit_price", "target_units", "achieved_amount", "achieved_units", "budget_amount"):
            if payload_float(payload, key) < 0:
                raise ValueError("프로모션 금액과 수량은 0 이상으로 입력하세요.")
        stage = str(payload.get("forecast_stage") or "sales_activity")
        if stage not in FORECAST_INPUT_STAGES:
            raise ValueError("프로모션 FCST 단계가 올바르지 않습니다.")
        confidence = payload_float(payload, "forecast_confidence", FORECAST_STAGES[stage]["confidence"])
        if not 0 <= confidence <= 100:
            raise ValueError("프로모션 FCST 확률은 0~100%로 입력하세요.")
        for row in get_db().execute(
            "SELECT id, payload_json FROM records WHERE entity_type = 'promotion' AND deleted_at IS NULL"
        ).fetchall():
            if record_id and row["id"] == record_id:
                continue
            other_id = str(parse_payload(row["payload_json"]).get("promotion_id") or "").strip()
            if other_id.casefold() == promotion_id.casefold():
                raise ValueError(f"프로모션 고유 ID '{promotion_id}'가 이미 사용 중입니다.")


def latest_rate_map(db):
    rows = latest_cached_exchange_rates(db)
    return {row["currency"]: float(row["krw_rate"] or 0) for row in rows}


def sync_promotion_forecast(db, promotion_row, actor_user_id):
    payload = parse_payload(promotion_row["payload_json"])
    target_month = str(payload.get("target_month") or "").strip()
    enabled = str(payload.get("forecast_included", "true")).lower() not in {"", "0", "false", "no"}
    now = utc_now()
    open_sources = db.execute(
        """
        SELECT f.*, c.forecast_month, c.status AS cycle_status
        FROM forecast_items f JOIN forecast_cycles c ON c.id = f.cycle_id
        WHERE f.source_type = 'promotion' AND f.source_id = ? AND f.deleted_at IS NULL
        """,
        (promotion_row["id"],),
    ).fetchall()
    if not enabled or promotion_row["status"] == "cancelled":
        removed = 0
        for item in open_sources:
            if item["cycle_status"] == "open":
                db.execute(
                    "UPDATE forecast_items SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                    (now, actor_user_id, actor_user_id, now, item["id"]),
                )
                removed += 1
        return {"status": "removed", "count": removed}
    if not valid_forecast_month(target_month):
        return {"status": "pending", "message": "프로모션 매출 반영월 확인 필요"}
    for item in open_sources:
        if item["cycle_status"] == "open" and item["forecast_month"] != target_month:
            db.execute(
                "UPDATE forecast_items SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ? WHERE id = ?",
                (now, actor_user_id, actor_user_id, now, item["id"]),
            )
    cycle = db.execute(
        "SELECT * FROM forecast_cycles WHERE forecast_month = ? ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, round_no DESC LIMIT 1",
        (target_month,),
    ).fetchone()
    if not cycle:
        if not DATABASE_SCHEMA_READY.is_set():
            return {"status": "pending", "message": "목표관리 구조 적용 후 FCST 자동 반영"}
        rates = latest_rate_map(db)
        if not all(rates.get(currency) for currency in ("USD", "EUR", "JPY", "CNY")):
            return {"status": "pending", "message": "기준환율 또는 FCST 차수 설정 후 자동 반영"}
        cycle_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO forecast_cycles
              (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, jpy_krw, cny_krw, status,
               created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
            """,
            (cycle_id, target_month, datetime.now(timezone.utc).date().isoformat(), rates["USD"], rates["EUR"], rates["JPY"], rates["CNY"], actor_user_id, actor_user_id, now, now),
        )
        cycle = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (cycle_id,)).fetchone()
        audit("FORECAST_CYCLE_CREATE", "forecast_cycle", cycle_id, f"{target_month} 1차 FCST · 프로모션 자동 생성", None, public_forecast_cycle(cycle))
    if cycle["status"] == "closed":
        return {"status": "pending", "message": "최신 FCST 차수가 마감되어 자동 반영 보류"}
    promotion_id = str(payload.get("promotion_id") or "").strip()
    stage = str(payload.get("forecast_stage") or "sales_activity")
    confidence = payload_float(payload, "forecast_confidence", FORECAST_STAGES[stage]["confidence"])
    expected_date = str(payload.get("target_ship_date") or payload.get("end_date") or "").strip() or None
    title = f"[프로모션 {promotion_id}] {promotion_row['title']}"
    notes = " · ".join(filter(None, [str(payload.get("promotion_terms") or "").strip(), str(payload.get("description") or "").strip()]))[:2000]
    existing = db.execute(
        """
        SELECT * FROM forecast_items
        WHERE cycle_id = ? AND source_type = 'promotion' AND source_id = ? AND deleted_at IS NULL
        LIMIT 1
        """,
        (cycle["id"], promotion_row["id"]),
    ).fetchone()
    if existing:
        db.execute(
            """
            UPDATE forecast_items SET title = ?, account_id = ?, account_name = ?, business_unit = ?,
              item_name = ?, stage = ?, confidence = ?, foreign_amount = ?, currency = ?,
              expected_ship_date = ?, owner_id = ?, notes = ?, status = 'active', updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (title, payload.get("account_id") or None, payload.get("account_name") or "", payload.get("business_unit") or "unclassified", payload.get("item_name") or "", stage, confidence, promotion_row["amount"], promotion_row["currency"], expected_date, promotion_row["owner_id"], notes, actor_user_id, now, existing["id"]),
        )
        item_id = existing["id"]
        action = "PROMOTION_FCST_UPDATE"
    else:
        item_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO forecast_items
              (id, cycle_id, title, account_id, account_name, business_unit, item_name, stage,
               confidence, foreign_amount, currency, expected_ship_date, owner_id, notes, status,
               source_type, source_id, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'promotion', ?, ?, ?, ?, ?)
            """,
            (item_id, cycle["id"], title, payload.get("account_id") or None, payload.get("account_name") or "", payload.get("business_unit") or "unclassified", payload.get("item_name") or "", stage, confidence, promotion_row["amount"], promotion_row["currency"], expected_date, promotion_row["owner_id"], notes, promotion_row["id"], actor_user_id, actor_user_id, now, now),
        )
        action = "PROMOTION_FCST_CREATE"
    audit(action, "forecast", item_id, f"{promotion_id} · {target_month} {cycle['round_no']}차 FCST 자동 반영")
    return {"status": "synced", "cycle_id": cycle["id"], "round_no": cycle["round_no"], "item_id": item_id}


@app.post("/api/records")
@role_required("admin", "manager", "editor")
@csrf_required
def create_record():
    data = request.get_json(silent=True) or {}
    if str(data.get("entity_type") or "").strip() == "task":
        return jsonify(error="주요업무는 신규 전용 원장에서 등록하세요.", code="MAJOR_TASK_LEDGER_REQUIRED"), 409
    try:
        values = normalize_record_input(data)
        validate_record_business_rules(values)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if g.current_user["role"] == "editor":
        values["owner_id"] = g.current_user["id"]
    elif values["owner_id"] is None:
        values["owner_id"] = g.current_user["id"]
    record_id = uuid.uuid4().hex
    now = utc_now()
    db = get_db()
    db.execute(
        """
        INSERT INTO records
          (id, entity_type, title, owner_id, status, due_date, region, country, amount,
           currency, payload_json, created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            values["entity_type"],
            values["title"],
            values["owner_id"],
            values["status"],
            values["due_date"],
            values["region"],
            values["country"],
            values["amount"],
            values["currency"],
            values["payload_json"],
            g.current_user["id"],
            g.current_user["id"],
            now,
            now,
        ),
    )
    created = db.execute(
        "SELECT r.*, u.display_name AS owner_name FROM records r LEFT JOIN users u ON u.id = r.owner_id WHERE r.id = ?",
        (record_id,),
    ).fetchone()
    try:
        order_terms_snapshot = snapshot_customer_order_terms(
            db, record_id, parse_payload(values["payload_json"]), g.current_user["id"], audit
        ) if values["entity_type"] == "order" else None
    except ValueError as exc:
        db.rollback()
        return jsonify(error=str(exc)), 400
    audit("CREATE", values["entity_type"], record_id, f"{values['title']} 생성", None, public_record(created))
    promotion_sync = sync_promotion_forecast(db, created, g.current_user["id"]) if values["entity_type"] == "promotion" else None
    db.commit()
    return jsonify(message="데이터가 등록되었습니다.", record=public_record(created),
                   promotion_forecast=promotion_sync, order_terms_snapshot=order_terms_snapshot), 201


@app.patch("/api/records/<record_id>")
@role_required("admin", "manager", "editor")
@csrf_required
def update_record(record_id):
    db = get_db()
    existing = db.execute("SELECT * FROM records WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
    if not existing:
        return jsonify(error="데이터를 찾을 수 없습니다."), 404
    if existing["entity_type"] == "task":
        return jsonify(error="이관된 주요업무는 신규 전용 원장에서 수정하세요.", code="MAJOR_TASK_LEDGER_REQUIRED"), 409
    if not can_modify_record(g.current_user, existing):
        return jsonify(error="본인이 담당한 데이터만 수정할 수 있습니다."), 403
    try:
        values = normalize_record_input(request.get_json(silent=True) or {}, existing)
        validate_record_business_rules(values, record_id=record_id)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if g.current_user["role"] == "editor":
        values["owner_id"] = existing["owner_id"] or g.current_user["id"]
    before = public_record(existing)
    db.execute(
        """
        UPDATE records SET entity_type = ?, title = ?, owner_id = ?, status = ?, due_date = ?,
          region = ?, country = ?, amount = ?, currency = ?, payload_json = ?, updated_by = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            values["entity_type"], values["title"], values["owner_id"], values["status"],
            values["due_date"], values["region"], values["country"], values["amount"],
            values["currency"], values["payload_json"], g.current_user["id"], utc_now(), record_id,
        ),
    )
    updated = db.execute(
        "SELECT r.*, u.display_name AS owner_name FROM records r LEFT JOIN users u ON u.id = r.owner_id WHERE r.id = ?",
        (record_id,),
    ).fetchone()
    try:
        order_terms_snapshot = snapshot_customer_order_terms(
            db, record_id, parse_payload(values["payload_json"]), g.current_user["id"], audit
        ) if values["entity_type"] == "order" else None
    except ValueError as exc:
        db.rollback()
        return jsonify(error=str(exc)), 400
    audit("UPDATE", values["entity_type"], record_id, f"{values['title']} 수정", before, public_record(updated))
    promotion_sync = sync_promotion_forecast(db, updated, g.current_user["id"]) if values["entity_type"] == "promotion" else None
    db.commit()
    return jsonify(message="데이터가 수정되었습니다.", record=public_record(updated),
                   promotion_forecast=promotion_sync, order_terms_snapshot=order_terms_snapshot)


@app.delete("/api/records/<record_id>")
@role_required("admin", "manager", "editor")
@csrf_required
def delete_record(record_id):
    db = get_db()
    existing = db.execute("SELECT * FROM records WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
    if not existing:
        return jsonify(error="데이터를 찾을 수 없습니다."), 404
    if existing["entity_type"] == "task":
        return jsonify(error="이관된 주요업무는 신규 전용 원장에서 취소·아카이브하세요.", code="MAJOR_TASK_LEDGER_REQUIRED"), 409
    if not can_modify_record(g.current_user, existing):
        return jsonify(error="본인이 담당한 데이터만 삭제할 수 있습니다."), 403
    before = public_record(existing)
    now = utc_now()
    child_ids = []
    if existing["entity_type"] == "task" and not parse_payload(existing["payload_json"]).get("parent_task_id"):
        for child in db.execute(
            "SELECT id, payload_json FROM records WHERE entity_type = 'task' AND deleted_at IS NULL"
        ).fetchall():
            if parse_payload(child["payload_json"]).get("parent_task_id") == record_id:
                child_ids.append(child["id"])
    db.execute(
        "UPDATE records SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ? WHERE id = ?",
        (now, g.current_user["id"], g.current_user["id"], now, record_id),
    )
    if child_ids:
        placeholders = ",".join("?" for _ in child_ids)
        db.execute(
            f"UPDATE records SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ? WHERE id IN ({placeholders})",
            (now, g.current_user["id"], g.current_user["id"], now, *child_ids),
        )
    if existing["entity_type"] == "promotion":
        db.execute(
            """
            UPDATE forecast_items SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ?
            WHERE source_type = 'promotion' AND source_id = ? AND deleted_at IS NULL
              AND cycle_id IN (SELECT id FROM forecast_cycles WHERE status = 'open')
            """,
            (now, g.current_user["id"], g.current_user["id"], now, record_id),
        )
    audit(
        "DELETE",
        existing["entity_type"],
        record_id,
        f"{existing['title']} 비활성 삭제" + (f" · 세부항목 {len(child_ids)}건 포함" if child_ids else ""),
        before,
        {"deleted_at": now, "deleted_child_ids": child_ids},
    )
    db.commit()
    message = "대분류와 세부항목이 삭제되었습니다." if child_ids else "데이터가 삭제되었습니다."
    return jsonify(message=f"{message} 변경 이력은 계속 보존됩니다.", deleted_child_ids=child_ids)


@app.get("/api/history")
def history():
    user = current_user_row()
    limit = min(max(int(request.args.get("limit", 100)), 1), 500)
    entity_type = request.args.get("type", "").strip()
    action = request.args.get("action", "").strip().upper()
    clauses = []
    params = []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if not user:
        clauses.append("entity_type NOT IN ('user', 'session')")
        clauses.append("action IN ('CREATE', 'UPDATE', 'DELETE', 'ERP_SYNC', 'SEED')")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = get_db().execute(
        "SELECT * FROM audit_logs" + where + " ORDER BY id DESC LIMIT ?", (*params, limit)
    ).fetchall()
    result = []
    for row in rows:
        item = row_dict(row)
        before_json = item.pop("before_json", None)
        after_json = item.pop("after_json", None)
        if user:
            item["before"] = parse_payload(before_json)
            item["after"] = parse_payload(after_json)
        else:
            item["actor_user_id"] = None
            item["actor_username"] = "담당자"
            item["before"] = {}
            item["after"] = {}
            item.pop("ip_address", None)
            item.pop("user_agent", None)
        result.append(item)
    return jsonify(history=result, public_mode=user is None)


OVERSEAS_BUSINESS_UNITS = set(PARENT_BUSINESS_AREAS) | {"unclassified"}
BUSINESS_UNIT_LABELS = {**PARENT_BUSINESS_AREAS, "unclassified": "미분류"}

# The legacy logistics master identifies these partners as non-dental. Dental is
# otherwise derived from its partner/product wording; ambiguous rows remain visible
# as unclassified instead of being silently forced into a business unit.
MEDICAL_PARTNERS = {
    "dr reduan el khattabi",
    "dr. pongpun",
    "elwan techinical supplies(m)",
    "graftos s.a.s",
    "medical revolution sdn bhd",
    "unimed enterprise",
}
AESTHETIC_PARTNERS = {
    "aril apostol",
    "claudia baraglia",
    "dala g kahhal",
    "daniela heldt",
    "dr. duong thoa md beauty & clinic",
    "dr.altanzul",
    "dr.basa clinic",
    "hk beauty line co., limited",
    "janet kelley",
    "jeannette cheung",
    "justin hodak",
    "kim burnside",
    "magali lavillenie",
    "n. minkova",
    "perla beauty center",
    "rebecca rowlands",
    "sa dental supply pte ltd",
    "susan difranco",
    "suzy cruz",
    "vel belle",
    "yijie zhang",
    "you & mei clinic",
}
DENTAL_PARTNERS = {
    "a-tak",
    "accredited consultants pvt ltd(acpl)",
    "andre iman kosasih",
    "atra medical",
    "bdh medical supply co., ltd",
    "cura medical co.",
    "delta dent",
    "dimoral dimitrakopoulos p.c",
    "dio portugal",
    "dr. teja",
    "eastpeak international technolgy co.,ltd.",
    "euroteknika",
    "joseph llp",
    "llc medmarket premium solutions",
    "medicaid medical services",
    "medpark medical device(구,medprin regeneravtive)",
    "megagen turkiye",
    "neobiotech mx",
    "protexnika llc",
    "sg med sdn bhd",
    "stomir co.,",
    "sultonien & co",
    "suwan medical",
    "tightmed srl",
    "tonghui",
    "udom smith myanmar",
    "vdt co ltd",
    "vytal healthcare",
    "zircon medical",
    "아침해의료기",
    "와스컴퍼니 주식회사 (the wassource limited)",
}


def normalized_text(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ").strip()).casefold()


def country_lookup_key(value):
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized_text(value))


def world_country_index():
    cached = getattr(world_country_index, "_cache", None)
    if cached is not None:
        return cached
    index = {}
    try:
        with open(os.path.join(PUBLIC_DIR, "countries-110m.json"), "r", encoding="utf-8") as topology_file:
            topology = json.load(topology_file)
        for geometry in topology.get("objects", {}).get("countries", {}).get("geometries", []):
            name = str((geometry.get("properties") or {}).get("name") or "").strip()
            map_id = str(geometry.get("id") or "").zfill(3)
            if name and map_id:
                index[country_lookup_key(name)] = {
                    "map_id": map_id,
                    "name": name,
                    "label": COUNTRY_CATALOG.get(map_id, {}).get("label", name),
                }
    except (OSError, ValueError, TypeError):
        index = {}
    for map_id, item in COUNTRY_CATALOG.items():
        resolved = {"map_id": map_id, "name": item["name"], "label": item["label"]}
        for alias in (*item.get("aliases", ()), item["name"], item["label"], map_id):
            index[country_lookup_key(alias)] = resolved
    world_country_index._cache = index
    return index


def resolve_country(value):
    key = country_lookup_key(value)
    if not key:
        return None
    item = world_country_index().get(key)
    return dict(item) if item else None


def standard_region(region="", country=""):
    """Normalize legacy region labels into the eight operating regions used by Global MAPS."""
    resolved = resolve_country(country)
    map_id = resolved["map_id"] if resolved else ""
    for label, country_codes in REGION_COUNTRY_CODES.items():
        if map_id in country_codes:
            return label
    key = country_lookup_key(region)
    aliases = (
        ("중동", ("중동", "middleeast")),
        ("동유럽", ("동유럽", "easterneurope", "cis")),
        ("서유럽", ("서유럽", "westerneurope", "유럽", "europe")),
        ("아프리카", ("아프리카", "africa")),
        ("북미", ("북미", "북아메리카", "northamerica")),
        ("남미", ("남미", "남아메리카", "southamerica", "latinamerica")),
        ("오세아니아", ("오세아니아", "oceania")),
        ("아시아", ("아시아", "동남아시아", "남아시아", "인도", "asia")),
    )
    for label, values in aliases:
        if any(country_lookup_key(value) in key for value in values):
            return label
    return "미지정"


def product_model_label(product_name="", product_code=""):
    value = str(product_name or product_code or "미지정").strip()
    compact = re.sub(r"\s+", " ", value)
    upper = compact.upper()
    known = (
        ("A1 OSS", "A1 OSS"), ("A1-OSS", "A1 OSS"), ("ADITE", "Adite"),
        ("S1", "S1"), ("BOSS", "BOSS"), ("COLLA", "Colla"),
        ("S-DERM", "Sderm"), ("SDERM", "Sderm"), ("SGEN", "Sgen"),
    )
    for prefix, label in known:
        if upper.startswith(prefix):
            return label
    first = re.split(r"[,/|]", compact, maxsplit=1)[0]
    first = re.sub(r"\s*-\s*(해외|EXPORT)$", "", first, flags=re.IGNORECASE).strip()
    return first[:40] or "미지정"


def extract_country(header, line=None):
    sources = [source for source in (header, line) if isinstance(source, dict)]
    explicit_keys = (
        "countryNm", "countryName", "country", "nationNm", "nationName", "nation",
        "natNm", "trCountryNm", "exportCountryNm", "destCountryNm", "arrivalCountryNm",
        "countryCd", "nationCd", "natCd", "countryCode", "nationCode", "isoCd",
        # The connected Amaranth shipment header exposes destination market as
        # areaCd/areaNm (for example JP / 아시아_일본).
        "areaCd", "areaNm",
    )
    for source in sources:
        for key in explicit_keys:
            resolved = resolve_country(source.get(key))
            if resolved:
                return resolved
        for key, value in source.items():
            compact_key = re.sub(r"[^a-z]", "", str(key).casefold())
            if any(marker in compact_key for marker in ("country", "nation")):
                resolved = resolve_country(value)
                if resolved:
                    return resolved
        area_name = str(source.get("areaNm") or "").strip()
        if "_" in area_name:
            resolved = resolve_country(area_name.rsplit("_", 1)[-1])
            if resolved:
                return resolved
    return None


def partner_country_from_accounts(db, partner_name, partner_code=""):
    partner_key = country_lookup_key(partner_name)
    code_key = country_lookup_key(partner_code)
    if not partner_key and not code_key:
        return None
    rows = db.execute(
        "SELECT title, country, payload_json FROM records WHERE entity_type = 'account' AND deleted_at IS NULL"
    ).fetchall()
    for row in rows:
        payload = parse_payload(row["payload_json"])
        aliases = [row["title"], payload.get("erp_partner_name"), payload.get("erp_partner_code")]
        aliases.extend(payload.get("erp_partner_aliases", []) if isinstance(payload.get("erp_partner_aliases"), list) else [])
        keys = {country_lookup_key(alias) for alias in aliases if alias}
        if partner_key in keys or (code_key and code_key in keys):
            return resolve_country(row["country"])
    return None


def first_header_value(header, *keys):
    for key in keys:
        value = header.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def extract_trade_type(header):
    value = first_header_value(
        header,
        "soFgNm",
        "tradeTypeNm",
        "tradeFgNm",
        "trFgNm",
        "paymentTypeNm",
        "paymentTermNm",
    )
    if value:
        return value
    known_terms = ("T/T", "L/C", "LOCAL", "DOMESTIC", "D/P", "D/A", "CAD", "구매승인서")
    for candidate in header.values():
        text = str(candidate or "").strip().upper()
        if any(term in text for term in known_terms):
            return str(candidate).strip()
    return ""


def is_overseas_header(header):
    trade_type = extract_trade_type(header)
    normalized_trade = re.sub(r"\s+", "", trade_type).upper()
    rejection_markers = ("LOCAL", "DOMESTIC", "국내", "로컬")
    if any(marker in normalized_trade for marker in rejection_markers):
        return False

    map_name = normalized_text(first_header_value(header, "mapFgNm", "orderMapNm", "salesMapNm"))
    if "국내" in map_name or "로컬" in map_name:
        return False
    if "해외" in map_name or "export" in map_name:
        return True

    explicit_terms = {
        "T/T",
        "TT",
        "L/C",
        "LC",
        "D/P",
        "DP",
        "D/A",
        "DA",
        "C.A.D",
        "CAD",
        "구매승인서",
    }
    compact_trade = normalized_trade.replace("-", "")
    return normalized_trade in explicit_terms or compact_trade in explicit_terms


def extract_partner_classification(header):
    value = first_header_value(
        header,
        "partnerClassification",
        "partnerClassNm",
        "trClassNm",
        "trclassNm",
        "trGrpNm",
        "custClassNm",
        "custGrpNm",
    )
    if value:
        return value
    for candidate in header.values():
        text = str(candidate or "").strip()
        if any(marker in text for marker in ("덴탈(해외)", "메디컬", "메디칼", "에스테틱")):
            return text
    return ""


def classify_business_unit(header, line, partner_classification=""):
    classification = normalized_text(partner_classification)
    if "에스테틱" in classification or "aesthetic" in classification:
        return "aesthetic"
    if "메디컬" in classification or "메디칼" in classification or "medical" in classification:
        return "medical"
    if "덴탈" in classification or "dental" in classification:
        return "dental"

    partner = normalized_text(first_header_value(header, "attrNm", "trNm", "partnerName"))
    product = normalized_text(
        " ".join(
            str(value or "")
            for value in (
                line.get("itemCd"),
                line.get("itemNm"),
                line.get("itemDc"),
                line.get("itemsetNm"),
                line.get("pjtNm"),
            )
        )
    )

    if partner in AESTHETIC_PARTNERS:
        return "aesthetic"
    if partner in MEDICAL_PARTNERS:
        return "medical"
    if partner in DENTAL_PARTNERS:
        return "dental"
    if any(marker in product for marker in ("adite", "아디떼")):
        return "aesthetic"
    if any(marker in partner for marker in ("derma", "aesthe", "beauty", "cosmetic", "plastic")):
        return "aesthetic"
    if any(marker in partner for marker in ("dental", "denta", "dent ", "dent.", "odont", "implant")):
        return "dental"
    if any(
        marker in product
        for marker in (
            "s derm",
            "s-derm",
            "s1-medical",
            "a1 dbm",
            "orthopedic",
            "tendon",
            "costal",
            "neuro",
            "sgen",
        )
    ):
        return "medical"
    if any(
        marker in product
        for marker in (
            "s1-xb",
            "mbxb",
            "boss",
            "colla",
            "a1 oss",
            "medpark fill",
            "medpark kit",
            "bone xb",
            "bone-xb",
            "bone xp",
            "bonegraft",
            "bovine xenograft",
            "mbxp",
            "poss",
            "x-cube",
            "a-plus",
            "s1(tw)",
            "centrifuge",
            "allo",
            "dental",
            "implant",
        )
    ):
        return "dental"
    return "unclassified"


def shipment_metadata(raw_json):
    payload = parse_payload(raw_json)
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    line = payload.get("line") if isinstance(payload.get("line"), dict) else {}
    partner_classification = extract_partner_classification(header)
    country = extract_country(header, line)
    management_code = first_header_value(line, "mgmtCd", "managementCd") or first_header_value(
        header, "mgmtCd", "managementCd"
    )
    management_name = first_header_value(line, "mgmtNm", "managementNm") or first_header_value(
        header, "mgmtNm", "managementNm"
    )
    management_key = country_lookup_key(management_name)
    code_key = management_code.strip().upper()
    if code_key == "B06" or "견본" in management_key:
        review_status = "sample_zero"
    elif code_key == "A10" or "유상" in management_key:
        review_status = "paid_verified_total"
    elif code_key == "A20" or "무상" in management_key:
        review_status = "review_pending_free"
    elif not code_key and not management_key:
        review_status = "review_pending_blank"
    else:
        review_status = "review_pending_management"
    source_hint = str(
        payload.get("source") or payload.get("source_file") or payload.get("filename")
        or payload.get("import_source") or ""
    ).strip()
    if source_hint:
        source_system = "LEGACY_EXCEL" if re.search(r"\.(xlsx?|csv)$", source_hint, re.IGNORECASE) else "LEGACY_SOURCE"
    elif header or line:
        source_system = "AMARANTH"
    else:
        source_system = "LEGACY_UNKNOWN"
    currency = str(line.get("exchCd") or header.get("exchCd") or "").strip().upper()
    rate_value = header.get("exchRt")
    if rate_value in (None, ""):
        rate_value = line.get("exchRt")
    try:
        exchange_rate = float(str(rate_value).replace(",", "")) if rate_value not in (None, "") else 0.0
    except (TypeError, ValueError):
        exchange_rate = 0.0
    if (
        source_system == "AMARANTH"
        and review_status == "paid_verified_total"
        and currency == "JPY"
        and (not math.isfinite(exchange_rate) or exchange_rate <= 0 or exchange_rate >= 100)
    ):
        review_status = "review_pending_jpy_rate"
    if source_system.startswith("LEGACY") and not management_code and not management_name:
        review_status = "legacy_policy"
    return {
        "is_overseas": int(is_overseas_header(header)),
        "trade_type": extract_trade_type(header),
        "business_unit": classify_business_unit(header, line, partner_classification),
        "partner_classification": partner_classification,
        "country_code": country["map_id"] if country else None,
        "country_name": country["name"] if country else None,
        "erp_management_code": management_code or None,
        "erp_management_name": management_name or None,
        "source_system": source_system,
        "actual_review_status": review_status,
    }


def recognized_sales_krw(row):
    """Return the verified official Actual while preserving the ERP raw amount.

    Only Amaranth rows covered by the same-row Excel/API mapping are eligible.
    Paid (A10) uses the raw ERP total, samples (B06) are recognized as zero,
    and unresolved/legacy policies stay ``None`` rather than being guessed.
    """
    source_system = str(row["source_system"] or "")
    review_status = str(row["actual_review_status"] or "")
    if source_system != "AMARANTH":
        return None
    if review_status == "paid_verified_total":
        return round(float(row["krw_total"] or 0), 2)
    if review_status == "sample_zero":
        return 0.0
    return None


def repair_legacy_erp_sync_stats(db):
    legacy_run = db.execute(
        """
        SELECT * FROM erp_sync_runs
        WHERE status = 'success' AND COALESCE(source_header_count, 0) = 0
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if not legacy_run:
        return False
    stats = db.execute(
        """
        SELECT COUNT(DISTINCT issue_no) AS source_headers,
          COUNT(DISTINCT CASE WHEN is_overseas = 1 THEN issue_no END) AS overseas_headers,
          SUM(CASE WHEN is_overseas = 1 THEN 1 ELSE 0 END) AS overseas_lines,
          SUM(CASE WHEN is_overseas = 1 THEN foreign_amount ELSE 0 END) AS foreign_amount,
          SUM(CASE WHEN is_overseas = 1 THEN krw_supply ELSE 0 END) AS krw_amount
        FROM shipments
        WHERE ship_date BETWEEN ? AND ?
        """,
        (legacy_run["date_from"], legacy_run["date_to"]),
    ).fetchone()
    source_headers = max(int(legacy_run["header_count"] or 0), int(stats["source_headers"] or 0))
    overseas_headers = int(stats["overseas_headers"] or 0)
    excluded_headers = max(0, source_headers - overseas_headers)
    db.execute(
        """
        UPDATE erp_sync_runs SET header_count = ?, source_header_count = ?,
          excluded_header_count = ?, line_count = ?, foreign_amount = ?, krw_amount = ?
        WHERE id = ?
        """,
        (
            overseas_headers,
            source_headers,
            excluded_headers,
            int(stats["overseas_lines"] or 0),
            float(stats["foreign_amount"] or 0),
            float(stats["krw_amount"] or 0),
            legacy_run["id"],
        ),
    )
    db.execute(
        """
        INSERT INTO audit_logs
          (occurred_at, actor_user_id, actor_username, action, entity_type, entity_id, summary)
        VALUES (?, NULL, 'SYSTEM', 'ERP_FILTER_MIGRATION', 'shipment', ?, ?)
        """,
        (
            utc_now(),
            str(legacy_run["id"]),
            f"기존 ERP 동기화 이력 교정 · 전체 {source_headers}건 중 해외 {overseas_headers}건",
        ),
    )
    return True


def backfill_shipment_metadata(db):
    before_totals = db.execute(
        "SELECT COUNT(*) AS c,COALESCE(SUM(krw_supply),0) AS supply,COALESCE(SUM(krw_total),0) AS total FROM shipments"
    ).fetchone()
    rows = db.execute(
        """
        SELECT id,partner_name,partner_code,country_code,country_name,krw_supply,krw_total,raw_json
        FROM shipments WHERE COALESCE(metadata_version, 0) < ?
        """,
        (SHIPMENT_METADATA_VERSION,),
    ).fetchall()
    changed = 0
    overseas = 0
    country_changed = 0
    country_changed_supply = 0.0
    country_changed_total = 0.0
    for row in rows:
        metadata = shipment_metadata(row["raw_json"])
        if not metadata["country_code"]:
            account_country = partner_country_from_accounts(db, row["partner_name"], row["partner_code"])
            if account_country:
                metadata["country_code"] = account_country["map_id"]
                metadata["country_name"] = account_country["name"]
        if (row["country_code"] or "") != (metadata["country_code"] or "") or (
            row["country_name"] or ""
        ) != (metadata["country_name"] or ""):
            country_changed += 1
            country_changed_supply += float(row["krw_supply"] or 0)
            country_changed_total += float(row["krw_total"] or 0)
        overseas += metadata["is_overseas"]
        db.execute(
            """
            UPDATE shipments SET is_overseas = ?, trade_type = ?, business_unit = ?,
              partner_classification = ?, country_code = ?, country_name = ?,
              erp_management_code=?,erp_management_name=?,source_system=?,actual_review_status=?,
              metadata_version = ? WHERE id = ?
            """,
            (
                metadata["is_overseas"],
                metadata["trade_type"],
                metadata["business_unit"],
                metadata["partner_classification"],
                metadata["country_code"],
                metadata["country_name"],
                metadata["erp_management_code"],
                metadata["erp_management_name"],
                metadata["source_system"],
                metadata["actual_review_status"],
                SHIPMENT_METADATA_VERSION,
                row["id"],
            ),
        )
        changed += 1
    if changed:
        after_totals = db.execute(
            "SELECT COUNT(*) AS c,COALESCE(SUM(krw_supply),0) AS supply,COALESCE(SUM(krw_total),0) AS total FROM shipments"
        ).fetchone()
        if (
            int(before_totals["c"]) != int(after_totals["c"])
            or abs(float(before_totals["supply"]) - float(after_totals["supply"])) > 0.01
            or abs(float(before_totals["total"]) - float(after_totals["total"])) > 0.01
        ):
            raise RuntimeError("ERP 국가·관리구분 정규화 중 전체 건수 또는 금액이 변경되어 적용을 중단했습니다.")
        db.execute(
            """
            INSERT INTO audit_logs
              (occurred_at, actor_user_id, actor_username, action, entity_type, entity_id, summary)
            VALUES (?, NULL, 'SYSTEM', 'ERP_RECLASSIFY', 'shipment', NULL, ?)
            """,
            (
                utc_now(),
                f"ERP 메타데이터 v{SHIPMENT_METADATA_VERSION} {changed}라인 · 해외 {overseas}라인 · "
                f"국가 정규화 {country_changed}라인/공급가 {country_changed_supply:,.2f}/합계 {country_changed_total:,.2f} · "
                "Excel↔API 합계액 Mapping 상태 반영 · 전체 건수·금액 불변 확인",
            ),
        )
    repaired = repair_legacy_erp_sync_stats(db)
    marker_exists = db.execute(
        "SELECT 1 FROM one_time_actions WHERE action_key = ?",
        (SHIPMENT_METADATA_ACTION_KEY,),
    ).fetchone() is not None
    if not marker_exists:
        db.execute(
            "INSERT INTO one_time_actions (action_key, applied_at) VALUES (?, ?)",
            (SHIPMENT_METADATA_ACTION_KEY, utc_now()),
        )
    if changed or repaired or not marker_exists:
        db.commit()


def erp_configured():
    keys = [
        "AMARANTH_BASE_URL",
        "AMARANTH_CALLER_NAME",
        "AMARANTH_ACCESS_TOKEN",
        "AMARANTH_HASH_KEY",
        "AMARANTH_GROUP_SEQ",
        "AMARANTH_COMPANY_CODE",
    ]
    return all(os.environ.get(key) for key in keys)


def amaranth_call(path, payload):
    base_url = os.environ["AMARANTH_BASE_URL"].rstrip("/")
    access_token = os.environ["AMARANTH_ACCESS_TOKEN"]
    transaction_id = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(30))
    timestamp = str(int(time.time()))
    signature_value = access_token + transaction_id + timestamp + path
    signature = base64.b64encode(
        hmac.new(
            os.environ["AMARANTH_HASH_KEY"].encode("utf-8"),
            signature_value.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    headers = {
        "callerName": os.environ["AMARANTH_CALLER_NAME"],
        "Authorization": f"Bearer {access_token}",
        "transaction-id": transaction_id,
        "timestamp": timestamp,
        "groupSeq": os.environ["AMARANTH_GROUP_SEQ"],
        "wehago-sign": signature,
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    req = Request(
        base_url + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=35) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Amaranth HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Amaranth 연결 오류: {exc}") from exc
    if str(result.get("resultCode")) not in {"0", "0.0"}:
        raise RuntimeError(f"Amaranth 오류 {result.get('resultCode')}: {result.get('resultMsg', 'Unknown error')}")
    return result.get("resultData") or []


def get_erp_detail(header):
    lines = amaranth_call(
        "/apiproxy/api20A01S00202",
        {"coCd": os.environ["AMARANTH_COMPANY_CODE"], "isuNb": header.get("isuNb")},
    )
    return header, lines


def erp_number(value, field_name):
    if value in (None, ""):
        return 0.0
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ERP {field_name} 숫자 해석 실패: {value}") from exc
    if not math.isfinite(number):
        raise ValueError(f"ERP {field_name} 숫자 해석 실패: {value}")
    return number


def prepare_erp_sync(db, from_dt, to_dt):
    """Fetch and validate an ERP range without changing the shipment ledger."""
    date_from, date_to = from_dt.isoformat(), to_dt.isoformat()
    headers = amaranth_call(
        "/apiproxy/api20A01S00201",
        {
            "coCd": os.environ["AMARANTH_COMPANY_CODE"],
            "isuDtFrom": from_dt.strftime("%Y%m%d"),
            "isuDtTo": to_dt.strftime("%Y%m%d"),
        },
    )
    if not isinstance(headers, list):
        raise ValueError("ERP 출고 Header 응답이 목록 형식이 아닙니다.")
    hard_blocks = []
    force_blocks = []
    warnings = ["ERP API pagination·완결성 표시는 아직 기술 검증 대기입니다."]
    if not headers:
        hard_blocks.append("Header가 0건이어서 기존 데이터를 교체할 수 없습니다.")
    overseas_headers = [header for header in headers if isinstance(header, dict) and is_overseas_header(header)]
    excluded_headers = [header for header in headers if not isinstance(header, dict) or not is_overseas_header(header)]
    excluded_partner_keys = {
        ("code", str(header.get("trCd") or "").strip())
        if str(header.get("trCd") or "").strip()
        else ("name", str(header.get("attrNm") or "").strip().casefold())
        for header in excluded_headers if isinstance(header, dict)
        if str(header.get("trCd") or header.get("attrNm") or "").strip()
    }
    details = []
    if overseas_headers:
        workers = min(6, max(1, len(overseas_headers)))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(get_erp_detail, header) for header in overseas_headers]
                for future in as_completed(futures):
                    header, lines = future.result()
                    if not isinstance(lines, list):
                        raise ValueError("ERP 출고 Detail 응답이 목록 형식이 아닙니다.")
                    details.append((header, lines))
        except Exception as exc:
            raise RuntimeError(f"ERP 출고 Detail 호출 실패: {exc}") from exc
    detail_count = sum(len(lines) for _header, lines in details)
    if overseas_headers and detail_count == 0:
        hard_blocks.append("해외 Header가 있으나 Detail이 0건입니다.")

    existing = db.execute(
        """SELECT COUNT(*) AS line_count,COUNT(DISTINCT issue_no) AS header_count,
                  COALESCE(SUM(krw_supply),0) AS krw_supply,COALESCE(SUM(krw_total),0) AS krw_total
           FROM shipments WHERE source_system='AMARANTH' AND ship_date BETWEEN ? AND ?""",
        (date_from, date_to),
    ).fetchone()
    existing_key_rows = db.execute(
        """SELECT issue_no,issue_seq FROM shipments
           WHERE source_system='AMARANTH' AND ship_date BETWEEN ? AND ?""",
        (date_from, date_to),
    ).fetchall()
    existing_keys = {(str(row["issue_no"]), int(row["issue_seq"])) for row in existing_key_rows}
    rows = []
    keys = set()
    currency_totals = {}
    management_totals = {}
    partners = set()
    latest_ship_date = None
    for header, lines in details:
        ship_date_raw = str(header.get("isuDt") or "").strip()
        try:
            ship_date = datetime.strptime(ship_date_raw, "%Y%m%d").date().isoformat()
        except ValueError:
            hard_blocks.append(f"출고일 형식 오류: {ship_date_raw or '공란'}")
            continue
        if ship_date < date_from or ship_date > date_to:
            hard_blocks.append(f"요청기간 밖 출고일: {ship_date}")
        latest_ship_date = max(latest_ship_date or ship_date, ship_date)
        trade_type = extract_trade_type(header)
        partner_classification = extract_partner_classification(header)
        for line in lines:
            if not isinstance(line, dict):
                hard_blocks.append("Detail JSON 행이 객체 형식이 아닙니다.")
                continue
            issue_no = str(line.get("isuNb") or header.get("isuNb") or "").strip()
            issue_seq_raw = line.get("isuSq")
            if not issue_no or issue_seq_raw in (None, ""):
                hard_blocks.append("출고번호 또는 출고순번이 없는 Detail 행이 있습니다.")
                continue
            try:
                issue_seq = int(issue_seq_raw)
            except (TypeError, ValueError):
                hard_blocks.append(f"출고순번 형식 오류: {issue_seq_raw}")
                continue
            key = (issue_no, issue_seq)
            if key in keys:
                hard_blocks.append(f"중복 출고 Key: {issue_no}/{issue_seq}")
                continue
            keys.add(key)
            currency = str(line.get("exchCd") or header.get("exchCd") or "KRW").strip().upper() or "KRW"
            rate_source_value = header.get("exchRt")
            if rate_source_value in (None, ""):
                rate_source_value = line.get("exchRt")
            try:
                quantity = erp_number(line.get("isuQt"), "수량")
                exchange_rate = erp_number(rate_source_value, "환율")
                transaction_amount = erp_number(line.get("exchAm"), "거래통화금액")
                krw_supply = erp_number(line.get("isugAm"), "공급가액")
                krw_vat = erp_number(line.get("isuvAm"), "부가세")
                krw_line_total = erp_number(line.get("isuhAm"), "합계액")
            except ValueError as exc:
                hard_blocks.append(str(exc))
                continue
            if currency == "JPY" and exchange_rate >= 100:
                hard_blocks.append(
                    f"JPY 환율은 1엔 기준이어야 합니다: {issue_no}/{issue_seq} ({exchange_rate:g})"
                )
            if currency == "JPY" and transaction_amount and exchange_rate <= 0:
                hard_blocks.append(
                    f"JPY 거래통화금액이 있으나 1엔 기준 환율이 없습니다: {issue_no}/{issue_seq}"
                )
            raw_json = safe_json({"header": header, "line": line})
            metadata = shipment_metadata(raw_json)
            country = extract_country(header, line) or partner_country_from_accounts(
                db, str(header.get("attrNm") or ""), str(header.get("trCd") or "")
            )
            currency_totals[currency] = currency_totals.get(currency, 0.0) + transaction_amount
            management_label = metadata["erp_management_name"] or metadata["erp_management_code"] or "공란"
            management = management_totals.setdefault(
                management_label, {"count": 0, "stored_krw_supply": 0.0, "stored_krw_total_candidate": 0.0}
            )
            management["count"] += 1
            management["stored_krw_supply"] += krw_supply
            management["stored_krw_total_candidate"] += krw_line_total
            partner_code = str(header.get("trCd") or "").strip()
            partner_name = str(header.get("attrNm") or "").strip()
            partners.add(partner_code or partner_name.casefold())
            rows.append({
                "issue_no": issue_no, "issue_seq": issue_seq, "ship_date": ship_date,
                "trade_type": trade_type,
                "business_unit": classify_business_unit(header, line, partner_classification),
                "partner_classification": partner_classification,
                "erp_management_code": metadata["erp_management_code"],
                "erp_management_name": metadata["erp_management_name"],
                "source_system": "AMARANTH",
                "actual_review_status": metadata["actual_review_status"],
                "metadata_version": SHIPMENT_METADATA_VERSION,
                "partner_code": partner_code, "partner_name": partner_name,
                "country_code": country["map_id"] if country else None,
                "country_name": country["name"] if country else None,
                "product_code": str(line.get("itemCd") or ""),
                "product_name": str(line.get("itemNm") or ""),
                "specification": str(line.get("itemDc") or ""),
                "quantity": quantity, "currency": currency, "exchange_rate": exchange_rate,
                "foreign_amount": transaction_amount, "krw_supply": krw_supply,
                "krw_vat": krw_vat, "krw_total": krw_line_total,
                "manager_name": str(header.get("korNm") or header.get("plnNm") or ""),
                "department_name": str(header.get("deptNm") or ""),
                "raw_json": raw_json,
            })
    new_keys = set(keys)
    added_keys = sorted(new_keys - existing_keys)
    removed_keys = sorted(existing_keys - new_keys)
    if added_keys or removed_keys:
        warnings.append(
            f"동일기간 출고 Key 변경: 추가 {len(added_keys)}건 · 제거 {len(removed_keys)}건. "
            "수정·취소·재발행 여부를 Preview에서 확인하세요."
        )
    for row in rows:
        collision = db.execute(
            """SELECT ship_date FROM shipments
               WHERE issue_no=? AND issue_seq=? AND ship_date NOT BETWEEN ? AND ?""",
            (row["issue_no"], row["issue_seq"], date_from, date_to),
        ).fetchone()
        if collision:
            hard_blocks.append(
                f"동일 출고 Key가 요청기간 밖 기존 행과 충돌합니다: "
                f"{row['issue_no']}/{row['issue_seq']} ({collision['ship_date']})"
            )
    # Repeated errors are summarized while retaining enough detail to diagnose.
    hard_blocks = list(dict.fromkeys(hard_blocks))[:50]
    existing_lines = int(existing["line_count"] or 0)
    if existing_lines >= 10 and len(rows) < existing_lines * 0.4 and existing_lines - len(rows) >= 5:
        force_blocks.append(
            f"동일기간 Detail이 기존 {existing_lines}건에서 신규 {len(rows)}건으로 비정상 급감했습니다."
        )
    pending_count = sum(
        item["count"] for label, item in management_totals.items()
        if label in {"공란", "무상"} or "무상" in label
    )
    if pending_count:
        warnings.append(f"관리구분 무상·공란 {pending_count}건은 공식 Actual 자동판정 대상이 아닙니다.")
    recognized_rows = [row for row in rows if recognized_sales_krw(row) is not None]
    recognized_total = round(sum(recognized_sales_krw(row) or 0 for row in recognized_rows), 2)
    metrics = {
        "date_from": date_from, "date_to": date_to,
        "source_header_count": len(headers), "overseas_header_count": len(overseas_headers),
        "excluded_header_count": len(excluded_headers),
        "excluded_partner_count": len(excluded_partner_keys), "detail_count": len(rows),
        "partner_count": len(partners), "latest_ship_date": latest_ship_date,
        "existing_line_count": existing_lines,
        "existing_krw_supply": float(existing["krw_supply"] or 0),
        "existing_krw_total_candidate": float(existing["krw_total"] or 0),
        "new_krw_supply": round(sum(row["krw_supply"] for row in rows), 2),
        "new_krw_total_candidate": round(sum(row["krw_total"] for row in rows), 2),
        "new_official_actual_krw": recognized_total,
        "official_actual_line_count": len(recognized_rows),
        "key_comparison": {
            "unchanged_count": len(existing_keys & new_keys),
            "added_count": len(added_keys), "removed_count": len(removed_keys),
            "added_samples": [f"{issue_no}/{issue_seq}" for issue_no, issue_seq in added_keys[:20]],
            "removed_samples": [f"{issue_no}/{issue_seq}" for issue_no, issue_seq in removed_keys[:20]],
        },
        "actual_mapping_evidence": ERP_ACTUAL_MAPPING_EVIDENCE,
        "currency_transaction_totals": {key: round(value, 4) for key, value in sorted(currency_totals.items())},
        "management_totals": management_totals,
        "hard_blocks": hard_blocks, "force_blocks": force_blocks, "warnings": warnings,
    }
    return rows, metrics


def erp_freshness_payload(db):
    latest_attempt = db.execute("SELECT * FROM erp_sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    last_success = db.execute(
        "SELECT * FROM erp_sync_runs WHERE status='success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    latest_ship = db.execute(
        "SELECT MAX(ship_date) AS latest_ship_date FROM shipments WHERE is_overseas=1"
    ).fetchone()["latest_ship_date"]
    status = "unavailable"
    message = "성공한 ERP 동기화 이력이 없습니다."
    if last_success and last_success["finished_at"]:
        try:
            last_time = datetime.fromisoformat(str(last_success["finished_at"]).replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - last_time.astimezone(timezone.utc)).total_seconds() / 3600
            status = "normal" if age_hours <= 48 else "stale"
            message = "정상" if status == "normal" else "마지막 성공 동기화 후 48시간이 지났습니다."
        except (TypeError, ValueError):
            status, message = "unknown", "동기화 시각을 해석할 수 없습니다."
    return {
        "latest_attempt": row_dict(latest_attempt), "last_success": row_dict(last_success),
        "latest_ship_date": latest_ship, "status": status, "message": message,
    }


@app.get("/api/erp/status")
def erp_status():
    user = current_user_row()
    freshness = erp_freshness_payload(get_db())
    last_sync = freshness["last_success"]
    latest_attempt = freshness["latest_attempt"]
    for item in (last_sync, latest_attempt):
        if item and not user:
            item.pop("requested_by", None)
            item.pop("error_message", None)
            item.pop("force_reason", None)
            item.pop("preflight_json", None)
    return jsonify(
        configured=erp_configured(),
        provider="Amaranth 10",
        endpoints=["출고 헤더", "출고 상세"],
        overseas_filter={
            "basis": "mapFgNm=해외수주 또는 soFgNm=T/T·L/C 등 수출조건",
            "excluded": "DOMESTIC·국내·LOCAL·LOCAL L/C",
        },
        last_sync=last_sync,
        latest_attempt=latest_attempt,
        freshness={
            "status": freshness["status"],
            "message": freshness["message"],
            "latest_ship_date": freshness["latest_ship_date"],
            "last_success_at": last_sync.get("finished_at") if last_sync else None,
            "sync_range": {
                "date_from": last_sync.get("date_from") if last_sync else None,
                "date_to": last_sync.get("date_to") if last_sync else None,
            },
        },
        public_mode=user is None,
    )


@app.post("/api/erp/sync")
@role_required("admin", "manager")
@csrf_required
def erp_sync():
    if not erp_configured():
        return jsonify(error="Amaranth API 환경변수가 설정되지 않았습니다."), 503
    data = request.get_json(silent=True) or {}
    date_from = str(data.get("date_from", "")).strip()
    date_to = str(data.get("date_to", "")).strip()
    try:
        from_dt = datetime.strptime(date_from, "%Y-%m-%d").date()
        to_dt = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(error="조회 기간을 YYYY-MM-DD 형식으로 입력하세요."), 400
    if from_dt > to_dt or (to_dt - from_dt).days > 92:
        return jsonify(error="한 번에 최대 93일까지 동기화할 수 있습니다."), 400
    db = get_db()
    started = utc_now()
    run_cursor = db.execute(
        "INSERT INTO erp_sync_runs (started_at, requested_by, date_from, date_to, status) VALUES (?, ?, ?, ?, 'running')",
        (started, g.current_user["id"], date_from, date_to),
    )
    run_id = run_cursor.lastrowid
    db.commit()
    try:
        rows, metrics = prepare_erp_sync(db, from_dt, to_dt)
        hard_blocks = metrics["hard_blocks"]
        force_blocks = metrics["force_blocks"]
        preview_only = not bool(data.get("confirm_apply"))
        force_requested = bool(data.get("force"))
        force_reason = str(data.get("force_reason") or "").strip()[:1000]
        if force_blocks and force_requested:
            if g.current_user["role"] != "admin":
                raise PermissionError("비정상 급감 강제반영은 관리자만 할 수 있습니다.")
            if not force_reason:
                raise ValueError("강제반영 사유를 입력하세요.")

        status = "preview_blocked" if hard_blocks else (
            "preview_force_required" if force_blocks and not force_requested else "preview_ready"
        )
        finished = utc_now()
        db.execute(
            """
            UPDATE erp_sync_runs SET finished_at=?,status=?,header_count=?,source_header_count=?,
              excluded_header_count=?,excluded_partner_count=?,line_count=?,foreign_amount=0,
              krw_amount=?,existing_line_count=?,existing_krw_amount=?,new_krw_amount=?,latest_ship_date=?,
              preflight_json=?,currency_totals_json=?,management_totals_json=?,quality_warnings_json=?,
              forced=?,force_reason=?,error_message=? WHERE id=?
            """,
            (
                finished,status,metrics["overseas_header_count"],metrics["source_header_count"],
                metrics["excluded_header_count"],metrics["excluded_partner_count"],metrics["detail_count"],
                metrics["new_krw_supply"],metrics["existing_line_count"],metrics["existing_krw_supply"],
                metrics["new_krw_supply"],metrics["latest_ship_date"],safe_json(metrics),
                safe_json(metrics["currency_transaction_totals"]),safe_json(metrics["management_totals"]),
                safe_json(metrics["warnings"]),int(force_requested),force_reason,
                " · ".join(hard_blocks or force_blocks),run_id,
            ),
        )
        db.commit()

        if preview_only:
            return jsonify(
                message="ERP 응답 검증이 완료되었습니다. 비교결과를 확인한 뒤 반영하세요.",
                run_id=run_id,preview=True,can_apply=not hard_blocks and not force_blocks,
                requires_force=bool(force_blocks),metrics=metrics,
            )
        if hard_blocks:
            return jsonify(
                error="ERP 응답이 필수 안전검증을 통과하지 못해 기존 데이터를 유지했습니다.",
                code="ERP_SYNC_HARD_BLOCK",run_id=run_id,metrics=metrics,
            ), 409
        if force_blocks and not force_requested:
            return jsonify(
                error="동일기간 자료가 비정상적으로 급감해 자동 반영을 중지했습니다.",
                code="ERP_SYNC_FORCE_REQUIRED",run_id=run_id,metrics=metrics,
            ), 409

        synced_at = utc_now()
        db.execute("BEGIN IMMEDIATE")
        before_totals = db.execute(
            "SELECT COUNT(*) AS c,COALESCE(SUM(krw_supply),0) AS s,COALESCE(SUM(krw_total),0) AS t FROM shipments"
        ).fetchone()
        db.execute(
            "DELETE FROM shipments WHERE source_system='AMARANTH' AND ship_date BETWEEN ? AND ?",
            (date_from, date_to),
        )
        for row in rows:
            db.execute(
                """
                INSERT INTO shipments
                  (issue_no,issue_seq,ship_date,is_overseas,trade_type,business_unit,
                   partner_classification,metadata_version,partner_code,partner_name,country_code,country_name,
                   product_code,product_name,specification,quantity,currency,exchange_rate,foreign_amount,
                   krw_supply,krw_vat,krw_total,manager_name,department_name,raw_json,synced_at,
                   erp_management_code,erp_management_name,source_system,actual_review_status)
                VALUES (:issue_no,:issue_seq,:ship_date,1,:trade_type,:business_unit,
                        :partner_classification,:metadata_version,:partner_code,:partner_name,:country_code,:country_name,
                        :product_code,:product_name,:specification,:quantity,:currency,:exchange_rate,:foreign_amount,
                        :krw_supply,:krw_vat,:krw_total,:manager_name,:department_name,:raw_json,:synced_at,
                        :erp_management_code,:erp_management_name,:source_system,:actual_review_status)
                ON CONFLICT(issue_no,issue_seq) DO UPDATE SET
                  ship_date=excluded.ship_date,is_overseas=1,trade_type=excluded.trade_type,
                  business_unit=excluded.business_unit,partner_classification=excluded.partner_classification,
                  metadata_version=excluded.metadata_version,partner_code=excluded.partner_code,partner_name=excluded.partner_name,
                  country_code=excluded.country_code,country_name=excluded.country_name,
                  product_code=excluded.product_code,product_name=excluded.product_name,
                  specification=excluded.specification,quantity=excluded.quantity,currency=excluded.currency,
                  exchange_rate=excluded.exchange_rate,foreign_amount=excluded.foreign_amount,
                  krw_supply=excluded.krw_supply,krw_vat=excluded.krw_vat,krw_total=excluded.krw_total,
                  manager_name=excluded.manager_name,department_name=excluded.department_name,
                  raw_json=excluded.raw_json,synced_at=excluded.synced_at,
                  erp_management_code=excluded.erp_management_code,
                  erp_management_name=excluded.erp_management_name,source_system=excluded.source_system,
                  actual_review_status=excluded.actual_review_status
                """,
                {**row,"synced_at":synced_at},
            )
        after_totals = db.execute(
            "SELECT COUNT(*) AS c,COALESCE(SUM(krw_supply),0) AS s,COALESCE(SUM(krw_total),0) AS t FROM shipments"
        ).fetchone()
        expected_count = int(before_totals["c"]) - int(metrics["existing_line_count"]) + len(rows)
        if int(after_totals["c"]) != expected_count:
            raise RuntimeError("ERP 반영 후 전체 출고라인 건수가 사전계산과 달라 반영을 취소했습니다.")
        db.execute(
            """UPDATE erp_sync_runs SET finished_at=?,status='success',error_message=NULL,
                      forced=?,force_reason=? WHERE id=?""",
            (synced_at,int(force_requested),force_reason,run_id),
        )
        audit(
            "ERP_SYNC",
            "shipment",
            run_id,
            f"Amaranth 해외 출고 {date_from}~{date_to} 동기화",
            None,
            {
                "source_headers": metrics["source_header_count"],
                "overseas_headers": metrics["overseas_header_count"],
                "domestic_local_excluded": metrics["excluded_header_count"],
                "domestic_local_excluded_partners": metrics["excluded_partner_count"],
                "lines": metrics["detail_count"],
                "transaction_currency_totals": metrics["currency_transaction_totals"],
                "stored_krw_supply": metrics["new_krw_supply"],
                "stored_krw_total_candidate": metrics["new_krw_total_candidate"],
                "forced": force_requested,
                "force_reason": force_reason,
            },
            connection=db,
        )
        db.commit()
        return jsonify(
            message="검증된 Amaranth 해외 출고 데이터가 반영되었습니다.",
            run_id=run_id,
            preview=False,metrics=metrics,
            before={"line_count":int(before_totals["c"]),"krw_supply":before_totals["s"],"krw_total":before_totals["t"]},
            after={"line_count":int(after_totals["c"]),"krw_supply":after_totals["s"],"krw_total":after_totals["t"]},
        )
    except (ValueError, PermissionError) as exc:
        db.rollback()
        db.execute(
            "UPDATE erp_sync_runs SET finished_at=?,status='blocked',error_message=? WHERE id=?",
            (utc_now(),str(exc)[:1000],run_id),
        )
        audit("ERP_SYNC_BLOCKED","shipment",run_id,f"Amaranth 동기화 차단: {str(exc)[:500]}",connection=db)
        db.commit()
        return jsonify(error=str(exc),code="ERP_SYNC_BLOCKED"), 403 if isinstance(exc, PermissionError) else 400
    except Exception as exc:
        db.rollback()
        error_message = str(exc)[:1000]
        db.execute(
            "UPDATE erp_sync_runs SET finished_at = ?, status = 'failed', error_message = ? WHERE id = ?",
            (utc_now(), error_message, run_id),
        )
        audit("ERP_SYNC_FAILED", "shipment", run_id, f"Amaranth 동기화 실패: {error_message}")
        db.commit()
        return jsonify(error="Amaranth 동기화에 실패했습니다.", detail=error_message), 502


def valid_forecast_month(value):
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(value or "")))


def shift_month(value, offset=1):
    year, month = (int(part) for part in value.split("-"))
    month_index = year * 12 + month - 1 + offset
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def operational_forecast_month():
    today = datetime.now(SEOUL).date()
    value = f"{today.year:04d}-{today.month:02d}"
    return shift_month(value, 1) if today.day >= 25 else value


def public_forecast_cycle(row):
    data = row_dict(row)
    if not data:
        return None
    data["round_label"] = f"{data['round_no']}차 가마감"
    data["rates"] = {
        "KRW": 1,
        "USD": data.get("usd_krw") or 0,
        "EUR": data.get("eur_krw") or 0,
        "JPY": data.get("jpy_krw") or 0,
        "CNY": data.get("cny_krw") or 0,
    }
    return data


def forecast_rate(cycle, currency):
    currency = str(currency or "USD").upper()
    if currency == "KRW":
        return 1.0
    key = f"{currency.lower()}_krw"
    return float(cycle.get(key, 0) or 0)


def public_forecast_item(row, cycle, public_mode=False):
    data = row_dict(row)
    if not data:
        return None
    rate = forecast_rate(cycle, data["currency"])
    data["applied_rate"] = rate
    data["krw_amount"] = round(float(data["foreign_amount"] or 0) * rate, 2)
    data["weighted_krw"] = round(data["krw_amount"] * float(data["confidence"] or 0) / 100, 2)
    data["stage_label"] = FORECAST_STAGES.get(data["stage"], {}).get("label", data["stage"])
    data["is_carryover"] = bool(data.get("carryover_from_month"))
    country = resolve_country(data.get("account_country"))
    data["account_country_code"] = country["map_id"] if country else None
    data["account_country_label"] = country["label"] if country else (data.get("account_country") or "")
    if public_mode:
        for key in ("owner_id", "created_by", "updated_by", "deleted_by"):
            data.pop(key, None)
    return data


def forecast_summary(db, cycle_row, item_rows=None):
    if not cycle_row:
        return {
            "total_krw": 0, "weighted_krw": 0, "erp_actual_krw": 0,
            "remaining_to_fcst_krw": 0, "achievement_pct": 0,
            "item_count": 0, "carryover_count": 0, "carryover_krw": 0,
            "by_stage": [], "by_business_unit": [], "foreign_totals": {},
        }
    cycle = row_dict(cycle_row)
    if item_rows is None:
        item_rows = db.execute(
            """
            SELECT f.*, u.display_name AS owner_name,
              a.country AS account_country, a.region AS account_region
            FROM forecast_items f
            LEFT JOIN users u ON u.id = f.owner_id
            LEFT JOIN records a ON a.id = f.account_id AND a.entity_type = 'account' AND a.deleted_at IS NULL
            WHERE f.cycle_id = ? AND f.deleted_at IS NULL AND f.status = 'active'
            ORDER BY COALESCE(f.expected_ship_date, '9999-12-31'), f.updated_at DESC
            """,
            (cycle["id"],),
        ).fetchall()
    items = [public_forecast_item(row, cycle) for row in item_rows]
    total_krw = sum(item["krw_amount"] for item in items)
    weighted_krw = sum(item["weighted_krw"] for item in items)
    carryovers = [item for item in items if item["is_carryover"]]
    stage_data = []
    for stage in ("sales_activity", "pi_received", "payment_received"):
        selected = [item for item in items if item["stage"] == stage]
        stage_data.append({
            "key": stage,
            "label": FORECAST_STAGES[stage]["label"],
            "default_confidence": FORECAST_STAGES[stage]["confidence"],
            "count": len(selected),
            "krw_amount": sum(item["krw_amount"] for item in selected),
            "weighted_krw": sum(item["weighted_krw"] for item in selected),
        })
    business_data = []
    for unit in ("dental", "medical", "aesthetic", "unclassified"):
        selected = [item for item in items if item["business_unit"] == unit]
        business_data.append({
            "key": unit,
            "label": BUSINESS_UNIT_LABELS.get(unit, unit),
            "count": len(selected),
            "krw_amount": sum(item["krw_amount"] for item in selected),
        })
    foreign_totals = {}
    for item in items:
        foreign_totals[item["currency"]] = foreign_totals.get(item["currency"], 0) + float(item["foreign_amount"] or 0)
    month = cycle["forecast_month"]
    erp_actual = db.execute(
        """
        SELECT COALESCE(SUM(krw_supply), 0) AS amount FROM shipments
        WHERE is_overseas = 1 AND substr(ship_date, 1, 7) = ?
        """,
        (month,),
    ).fetchone()["amount"] or 0
    remaining = max(float(total_krw) - float(erp_actual), 0)
    return {
        "total_krw": round(total_krw, 2),
        "weighted_krw": round(weighted_krw, 2),
        "erp_actual_krw": round(float(erp_actual), 2),
        "remaining_to_fcst_krw": round(remaining, 2),
        "achievement_pct": round(float(erp_actual) / total_krw * 100, 1) if total_krw else 0,
        "item_count": len(items),
        "carryover_count": len(carryovers),
        "carryover_krw": round(sum(item["krw_amount"] for item in carryovers), 2),
        "by_stage": stage_data,
        "by_business_unit": business_data,
        "foreign_totals": foreign_totals,
    }


def monthly_sales_shadow_summary(db, month):
    """Return a small, read-only summary of the new Sales FCST ledger.

    This is intentionally a comparison payload, not an implicit read-path
    switch.  The legacy forecast cycle and monthly_sales currently express
    different business scopes in production and must not be interchanged
    until their differences have been reviewed.
    """
    rows = db.execute(
        """
        SELECT sales_status,COUNT(*) AS row_count,
          COALESCE(SUM(amount_usd),0) AS amount_usd,
          COALESCE(SUM(krw_amount),0) AS krw_amount,
          SUM(CASE WHEN customer_master_id IS NOT NULL THEN 1 ELSE 0 END) AS customer_linked,
          SUM(CASE WHEN owner_user_id IS NOT NULL THEN 1 ELSE 0 END) AS owner_linked
        FROM monthly_sales
        WHERE target_month=? AND record_status='active'
        GROUP BY sales_status
        """,
        (month,),
    ).fetchall()
    by_status = {
        str(row["sales_status"]): {
            "row_count": int(row["row_count"] or 0),
            "amount_usd": round(float(row["amount_usd"] or 0), 4),
            "krw_amount": round(float(row["krw_amount"] or 0), 2),
        }
        for row in rows
    }
    detail_rows = db.execute(
        """
        SELECT s.*,c.headquarters_country AS customer_master_country
        FROM monthly_sales s
        LEFT JOIN customer_master c ON c.id=s.customer_master_id
        WHERE s.target_month=? AND s.record_status='active'
        """,
        (month,),
    ).fetchall()
    by_currency = {}
    by_timing = {}
    by_business_unit = {}
    country_source_changes = 0
    country_source_change_krw = 0.0
    unresolved_master_country = 0
    missing_customer_master = 0
    for row in detail_rows:
        data = row_dict(row)
        currency = str(
            data.get("transaction_currency_standard")
            or data.get("transaction_currency") or data.get("currency") or "USD"
        ).upper()
        currency_bucket = by_currency.setdefault(
            currency, {"row_count": 0, "transaction_amount": 0.0, "amount_usd": 0.0, "krw_amount": 0.0}
        )
        currency_bucket["row_count"] += 1
        currency_bucket["transaction_amount"] += float(data.get("transaction_amount") or 0)
        currency_bucket["amount_usd"] += float(data.get("amount_usd") or 0)
        currency_bucket["krw_amount"] += float(data.get("krw_amount") or 0)
        for target, key in ((by_timing, data.get("timing_type") or "unclassified"),
                            (by_business_unit, data.get("business_unit") or "unclassified")):
            bucket = target.setdefault(str(key), {"row_count": 0, "amount_usd": 0.0, "krw_amount": 0.0})
            bucket["row_count"] += 1
            bucket["amount_usd"] += float(data.get("amount_usd") or 0)
            bucket["krw_amount"] += float(data.get("krw_amount") or 0)
        master_country = resolve_country(data.get("customer_master_country"))
        snapshot_country = resolve_country(data.get("country"))
        if not data.get("customer_master_id"):
            missing_customer_master += 1
        elif not master_country:
            unresolved_master_country += 1
        elif not snapshot_country or snapshot_country["map_id"] != master_country["map_id"]:
            country_source_changes += 1
            country_source_change_krw += float(data.get("krw_amount") or 0)

    def rounded_groups(groups):
        return {
            key: {
                field: round(value, 4 if field in {"transaction_amount", "amount_usd"} else 2)
                if isinstance(value, float) else value
                for field, value in bucket.items()
            }
            for key, bucket in sorted(groups.items())
        }

    round_rows = db.execute(
        """SELECT round_key,COUNT(*) AS import_count,COALESCE(SUM(row_count),0) AS row_count
           FROM monthly_sales_round_imports WHERE target_month=? GROUP BY round_key ORDER BY round_key""",
        (month,),
    ).fetchall()
    return {
        "ledger": "monthly_sales",
        "row_count": sum(item["row_count"] for item in by_status.values()),
        "amount_usd": round(sum(item["amount_usd"] for item in by_status.values()), 4),
        "krw_amount": round(sum(item["krw_amount"] for item in by_status.values()), 2),
        "customer_linked": sum(int(row["customer_linked"] or 0) for row in rows),
        "owner_linked": sum(int(row["owner_linked"] or 0) for row in rows),
        "by_status": by_status,
        "by_currency": rounded_groups(by_currency),
        "by_timing": rounded_groups(by_timing),
        "by_business_unit": rounded_groups(by_business_unit),
        "geography_readiness": {
            "customer_master_missing": missing_customer_master,
            "customer_master_country_unresolved": unresolved_master_country,
            "snapshot_to_master_country_change_count": country_source_changes,
            "snapshot_to_master_country_change_krw": round(country_source_change_krw, 2),
        },
        "historical_round_imports": [row_dict(row) for row in round_rows],
    }


def forecast_source_transition(db, month, cycle_row=None, item_rows=None):
    """Describe, without changing, the legacy/new FCST read paths."""
    if cycle_row is None:
        cycle_row = db.execute(
            "SELECT * FROM forecast_cycles WHERE forecast_month=? ORDER BY round_no DESC LIMIT 1",
            (month,),
        ).fetchone()
    if cycle_row and item_rows is None:
        item_rows = db.execute(
            """
            SELECT f.*,u.display_name AS owner_name,
              a.country AS account_country,a.region AS account_region
            FROM forecast_items f
            LEFT JOIN users u ON u.id=f.owner_id
            LEFT JOIN records a ON a.id=f.account_id AND a.entity_type='account' AND a.deleted_at IS NULL
            WHERE f.cycle_id=? AND f.deleted_at IS NULL AND f.status='active'
            ORDER BY COALESCE(f.expected_ship_date,'9999-12-31'),f.updated_at DESC
            """,
            (cycle_row["id"],),
        ).fetchall()
    legacy = forecast_summary(db, cycle_row, item_rows) if cycle_row else forecast_summary(db, None)
    monthly = monthly_sales_shadow_summary(db, month)
    legacy_krw = float(legacy.get("total_krw") or 0)
    monthly_krw = float(monthly.get("krw_amount") or 0)
    cycle_data = row_dict(cycle_row)
    legacy_items = [public_forecast_item(row, cycle_data) for row in (item_rows or [])]
    source_types = {}
    for item in legacy_items:
        source = str(item.get("source_type") or "manual")
        bucket = source_types.setdefault(source, {"row_count": 0, "krw_amount": 0.0})
        bucket["row_count"] += 1
        bucket["krw_amount"] += float(item.get("krw_amount") or 0)
    for bucket in source_types.values():
        bucket["krw_amount"] = round(bucket["krw_amount"], 2)
    promotion = source_types.get("promotion", {"row_count": 0, "krw_amount": 0.0})
    geography = monthly["geography_readiness"]
    blockers = []
    if int(legacy.get("item_count") or 0) != int(monthly.get("row_count") or 0) or abs(monthly_krw - legacy_krw) > 0.01:
        blockers.append("aggregate_scope_difference")
    if geography["customer_master_missing"] or geography["customer_master_country_unresolved"]:
        blockers.append("customer_master_geography_incomplete")
    if geography["snapshot_to_master_country_change_count"]:
        blockers.append("customer_master_country_business_review")
    blockers.append("promotion_legacy_write_dependency")
    return {
        "status": "shadow_comparison",
        "current_read_path": "forecast_cycles/forecast_items",
        "official_sales_fcst_ledger": "monthly_sales",
        "read_path_changed": False,
        "reason": "구형·신형 FCST의 업무범위 및 금액 차이 검토 전 화면 수치를 자동 전환하지 않음",
        "legacy": {
            "round_no": int(cycle_row["round_no"]) if cycle_row else None,
            "as_of_date": cycle_row["as_of_date"] if cycle_row else None,
            "row_count": int(legacy.get("item_count") or 0),
            "krw_amount": round(legacy_krw, 2),
            "by_stage": legacy.get("by_stage") or [],
            "by_currency": legacy.get("foreign_totals") or {},
            "source_types": source_types,
        },
        "monthly_sales": monthly,
        "difference_krw": round(monthly_krw - legacy_krw, 2),
        "difference_categories": {
            "scope": {
                "legacy_row_count": int(legacy.get("item_count") or 0),
                "monthly_row_count": int(monthly.get("row_count") or 0),
                "row_count_difference": int(monthly.get("row_count") or 0) - int(legacy.get("item_count") or 0),
                "krw_difference": round(monthly_krw - legacy_krw, 2),
            },
            "status_formula": {
                "legacy_by_stage": legacy.get("by_stage") or [],
                "monthly_by_status": monthly.get("by_status") or {},
            },
            "rate_context": {
                "legacy_foreign_totals": legacy.get("foreign_totals") or {},
                "monthly_by_currency": monthly.get("by_currency") or {},
            },
            "promotion": {
                **promotion,
                "official_monthly_auto_include": False,
                "legacy_write_dependency_retained": True,
            },
            "historical_summary": {
                "monthly_round_imports": monthly.get("historical_round_imports") or [],
            },
            "geography": geography,
        },
        "cutover_readiness": {
            "status": "blocked" if blockers else "business_validation_required",
            "business_validation_required": True,
            "blockers": blockers,
        },
    }


def latest_cached_exchange_rates(db):
    latest = db.execute("SELECT MAX(fetched_at) AS fetched_at FROM exchange_rates").fetchone()["fetched_at"]
    if not latest:
        return []
    return db.execute(
        """
        SELECT rate_date, currency, krw_rate, source, fetched_at
        FROM exchange_rates WHERE fetched_at = ?
        ORDER BY CASE currency WHEN 'USD' THEN 1 WHEN 'EUR' THEN 2 WHEN 'JPY' THEN 3 WHEN 'CNY' THEN 4 ELSE 5 END
        """,
        (latest,),
    ).fetchall()


def fetch_exchange_rate_snapshot():
    request_obj = Request(
        "https://api.frankfurter.dev/v2/rates?base=EUR&quotes=KRW,USD,JPY,CNY",
        headers={"Accept": "application/json", "User-Agent": "MedPark-Global-MAPS/1.0"},
        method="GET",
    )
    try:
        with urlopen(request_obj, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"기준환율 조회 실패: {exc}") from exc
    quotes = {str(item.get("quote")): float(item.get("rate") or 0) for item in payload if isinstance(item, dict)}
    dates = [str(item.get("date")) for item in payload if isinstance(item, dict) and item.get("date")]
    if not all(quotes.get(currency) for currency in ("KRW", "USD", "JPY", "CNY")) or not dates:
        raise RuntimeError("기준환율 응답에 USD·EUR·JPY·CNY·KRW가 모두 포함되지 않았습니다.")
    eur_krw = quotes["KRW"]
    rates = {
        "USD": eur_krw / quotes["USD"],
        "EUR": eur_krw,
        "JPY": eur_krw / quotes["JPY"],
        "CNY": eur_krw / quotes["CNY"],
    }
    rate_date = max(dates)
    fetched_at = utc_now()
    return [
        {
            "rate_date": rate_date,
            "currency": currency,
            "krw_rate": round(krw_rate, 4),
            "source": FX_SOURCE,
            "fetched_at": fetched_at,
        }
        for currency, krw_rate in rates.items()
    ]


@app.get("/api/exchange-rates")
def exchange_rates():
    global EXCHANGE_RATE_MEMORY_CACHE
    warning = None
    today = datetime.now(timezone.utc).date().isoformat()
    with EXCHANGE_RATE_MEMORY_LOCK:
        rows = [dict(row) for row in EXCHANGE_RATE_MEMORY_CACHE]
        currencies = {row["currency"] for row in rows}
        fetched_today = bool(
            rows
            and str(rows[0]["fetched_at"]).startswith(today)
            and {"USD", "EUR", "JPY", "CNY"}.issubset(currencies)
        )
        if not fetched_today:
            try:
                rows = fetch_exchange_rate_snapshot()
                EXCHANGE_RATE_MEMORY_CACHE = [dict(row) for row in rows]
            except RuntimeError as exc:
                warning = str(exc)
                if not rows:
                    try:
                        rows = [row_dict(row) for row in latest_cached_exchange_rates(get_db())]
                    except sqlite3.Error:
                        warning = f"{warning} · 내부 캐시도 일시적으로 사용할 수 없습니다."
    return jsonify(
        rates=[row_dict(row) for row in rows],
        source=FX_SOURCE,
        unit="KRW per 1 foreign currency unit",
        warning=warning,
        stale=not bool(rows and str(rows[0]["rate_date"]) == today),
        version=APP_VERSION,
    )


@app.get("/api/forecast")
def forecast():
    month = request.args.get("month", operational_forecast_month()).strip()
    if not valid_forecast_month(month):
        return jsonify(error="FCST 대상월 형식이 올바르지 않습니다."), 400
    round_value = request.args.get("round", "latest").strip().lower()
    if round_value != "latest" and round_value not in {"1", "2", "3"}:
        return jsonify(error="FCST 차수는 1~3차만 선택할 수 있습니다."), 400
    db = get_db()
    cycle_rows = db.execute(
        "SELECT * FROM forecast_cycles WHERE forecast_month = ? ORDER BY round_no",
        (month,),
    ).fetchall()
    selected_cycle = None
    if cycle_rows:
        selected_cycle = cycle_rows[-1] if round_value == "latest" else next((row for row in cycle_rows if row["round_no"] == int(round_value)), None)
    item_rows = []
    if selected_cycle:
        item_rows = db.execute(
            """
            SELECT f.*, u.display_name AS owner_name,
              a.country AS account_country, a.region AS account_region
            FROM forecast_items f
            LEFT JOIN users u ON u.id = f.owner_id
            LEFT JOIN records a ON a.id = f.account_id AND a.entity_type = 'account' AND a.deleted_at IS NULL
            WHERE f.cycle_id = ? AND f.deleted_at IS NULL AND f.status = 'active'
            ORDER BY COALESCE(f.expected_ship_date, '9999-12-31'), f.updated_at DESC
            """,
            (selected_cycle["id"],),
        ).fetchall()
    user = current_user_row()
    selected_cycle_data = public_forecast_cycle(selected_cycle)
    items = [public_forecast_item(row, row_dict(selected_cycle), public_mode=user is None) for row in item_rows] if selected_cycle else []
    round_summaries = []
    for cycle_row in cycle_rows:
        summary = forecast_summary(db, cycle_row)
        round_summaries.append({"round_no": cycle_row["round_no"], "as_of_date": cycle_row["as_of_date"], **summary})
    summary = forecast_summary(db, selected_cycle, item_rows)
    if not selected_cycle:
        erp_actual = db.execute(
            "SELECT COALESCE(SUM(krw_supply), 0) AS amount FROM shipments WHERE is_overseas = 1 AND substr(ship_date, 1, 7) = ?",
            (month,),
        ).fetchone()["amount"] or 0
        summary["erp_actual_krw"] = float(erp_actual)
    return jsonify(
        forecast_month=month,
        operational_month=operational_forecast_month(),
        selected_round=selected_cycle["round_no"] if selected_cycle else None,
        cycle=selected_cycle_data,
        cycles=[public_forecast_cycle(row) for row in cycle_rows],
        round_summaries=round_summaries,
        items=items,
        summary=summary,
        stage_definitions=[{"key": key, **FORECAST_STAGES[key]} for key in ("sales_activity", "pi_received", "payment_received")],
        public_mode=user is None,
        source_transition=forecast_source_transition(db, month, selected_cycle, item_rows),
    )


@app.get("/api/forecast/source-shadow")
@role_required("admin", "manager")
def forecast_source_shadow():
    month = request.args.get("month", operational_forecast_month()).strip()
    if not valid_forecast_month(month):
        return jsonify(error="FCST 대상월 형식이 올바르지 않습니다."), 400
    return jsonify(month=month, **forecast_source_transition(get_db(), month))


def forecast_round_label(round_no):
    return "미정" if int(round_no) == 0 else f"{int(round_no)}차"


def forecast_round_source_metadata():
    try:
        with open(FORECAST_ROUND_OVERVIEW_PATH, encoding="utf-8") as source_file:
            return json.load(source_file)
    except (OSError, json.JSONDecodeError):
        app.logger.exception("Forecast round overview source could not be loaded")
        return {}


def forecast_round_workflow_row(db, forecast_month, round_no):
    return db.execute(
        """
        SELECT workflow.*, updater.display_name AS updated_by_name,
               confirmer.display_name AS confirmed_by_name
        FROM forecast_round_workflows workflow
        LEFT JOIN users updater ON updater.id = workflow.updated_by
        LEFT JOIN users confirmer ON confirmer.id = workflow.confirmed_by
        WHERE workflow.forecast_month = ? AND workflow.round_no = ?
        """,
        (forecast_month, round_no),
    ).fetchone()


def forecast_round_entry_values(row):
    plan = float(row["plan_krw"] or 0)
    initial = float(row["initial_fcst_krw"] or 0)
    carryover = float(row["carryover_krw"] or 0)
    current_month = float(row["current_month_krw"] or 0)
    pipeline = float(row["pipeline_krw"] or 0)
    confirmed_scheduled = carryover + current_month
    current_expected = confirmed_scheduled + pipeline
    return {
        "plan": plan,
        "initial_fcst": initial,
        "first_expected": float(row["first_expected_krw"] or 0),
        "current_expected": current_expected,
        "confirmed_scheduled": confirmed_scheduled,
        "carryover": carryover,
        "current_month": current_month,
        "pipeline": pipeline,
        "current_with_pipeline": current_month + pipeline,
        "next_month": float(row["next_month_krw"] or 0),
        "next_pipeline": float(row["next_pipeline_krw"] or 0),
        "plan_variance": current_expected - plan,
        "initial_variance": current_expected - initial,
        "notes": row["notes"] or "",
    }


def public_forecast_round_detail(row):
    data = row_dict(row)
    if not data:
        return None
    for field in FORECAST_ROUND_DETAIL_AMOUNT_FIELDS:
        data[field] = float(data.get(field) or 0)
    data["current_expected_krw"] = float(data.get("carryover_krw") or 0) + float(data.get("current_krw") or 0)
    data["sales_stage_label"] = FORECAST_ROUND_DETAIL_STAGES.get(data.get("sales_stage"), data.get("sales_stage"))
    data["progress_status_label"] = FORECAST_ROUND_DETAIL_PROGRESS_STATUSES.get(
        data.get("progress_status"), data.get("progress_status")
    )
    data["management_type_label"] = FORECAST_ROUND_DETAIL_MANAGEMENT_TYPES.get(
        data.get("management_type"), data.get("management_type")
    )
    data["business_label"] = dict(FORECAST_ROUND_BUSINESS_UNITS).get(data.get("business_unit"), data.get("business_unit"))
    data["is_deleted"] = bool(data.get("deleted_at"))
    return data


def forecast_round_detail_summary(details, official_current=0):
    summary = {
        "record_count": len(details), "confirmed_scheduled_krw": 0.0,
        "pipeline_krw": 0.0, "undecided_krw": 0.0, "allocated_expected_krw": 0.0,
        "next_krw": 0.0, "official_current_krw": float(official_current or 0),
    }
    for detail in details:
        current = float(detail.get("current_expected_krw") or 0)
        stage = detail.get("sales_stage")
        if stage in {"confirmed", "scheduled"}:
            summary["confirmed_scheduled_krw"] += current
        elif stage == "pipeline":
            summary["pipeline_krw"] += current
        else:
            summary["undecided_krw"] += current
        summary["next_krw"] += float(detail.get("next_krw") or 0)
    summary["allocated_expected_krw"] = summary["confirmed_scheduled_krw"] + summary["pipeline_krw"]
    summary["unallocated_krw"] = summary["official_current_krw"] - summary["allocated_expected_krw"]
    summary["coverage_percent"] = (
        round(summary["allocated_expected_krw"] / summary["official_current_krw"] * 100, 1)
        if summary["official_current_krw"] else 0.0
    )
    summary["data_status"] = "standalone_workbook_only"
    summary["history"] = {
        "previous_month_sales_krw": None,
        "previous_year_sales_krw": None,
        "order_cycle_days": None,
        "status": "accumulating",
        "message": "이 메뉴에 데이터가 축적되면 전월·전년·주문주기를 표시합니다.",
    }
    return summary


def forecast_round_detail_group_key(detail, group_by):
    if group_by == "item":
        return detail.get("item_name") or "품목 미지정"
    if group_by == "country":
        return detail.get("country_name") or "국가 미지정"
    if group_by == "account":
        return detail.get("account_name") or "거래처 미지정"
    if group_by == "stage":
        return detail.get("sales_stage_label") or "미정"
    return "선택 차수 전체"


def forecast_round_detail_groups(details, group_by):
    groups = {}
    for detail in details:
        key = forecast_round_detail_group_key(detail, group_by)
        group = groups.setdefault(key, {
            "key": key, "label": key, "record_count": 0, "current_expected_krw": 0.0,
            "confirmed_scheduled_krw": 0.0, "pipeline_krw": 0.0, "undecided_krw": 0.0,
            "next_krw": 0.0, "last_activity_at": None, "last_amount_krw": 0.0,
            "business_units": set(),
        })
        current = float(detail.get("current_expected_krw") or 0)
        group["record_count"] += 1
        group["current_expected_krw"] += current
        group["next_krw"] += float(detail.get("next_krw") or 0)
        group["business_units"].add(detail.get("business_label") or detail.get("business_unit"))
        if detail.get("sales_stage") in {"confirmed", "scheduled"}:
            group["confirmed_scheduled_krw"] += current
        elif detail.get("sales_stage") == "pipeline":
            group["pipeline_krw"] += current
        else:
            group["undecided_krw"] += current
        activity_dates = [detail.get(field) for field in FORECAST_ROUND_DETAIL_DATE_FIELDS if detail.get(field)]
        latest = max(activity_dates) if activity_dates else None
        if latest and (not group["last_activity_at"] or latest >= group["last_activity_at"]):
            group["last_activity_at"] = latest
            group["last_amount_krw"] = current
    result = []
    for group in groups.values():
        group["business_units"] = sorted(value for value in group["business_units"] if value)
        group["history"] = {
            "previous_month_sales_krw": None, "previous_year_sales_krw": None,
            "order_cycle_days": None, "status": "accumulating",
        }
        result.append(group)
    return sorted(result, key=lambda item: (-item["current_expected_krw"], item["label"]))


def public_forecast_round_workflow(db, workflow, user=None):
    if not workflow:
        return None
    entries = db.execute(
        "SELECT * FROM forecast_round_entries WHERE workflow_id = ? ORDER BY business_unit",
        (workflow["id"],),
    ).fetchall()
    business_units = {row["business_unit"]: forecast_round_entry_values(row) for row in entries}
    totals = {}
    for field in (
        "plan", "initial_fcst", "first_expected", "current_expected", "confirmed_scheduled",
        "carryover", "current_month", "pipeline", "current_with_pipeline", "next_month",
        "next_pipeline", "plan_variance", "initial_variance",
    ):
        totals[field] = sum(float(values.get(field) or 0) for values in business_units.values())
    totals["notes"] = ""
    business_units["total"] = totals
    detail_rows = db.execute(
        """
        SELECT detail.*, creator.display_name AS created_by_name, updater.display_name AS updated_by_name
        FROM forecast_round_details detail
        LEFT JOIN users creator ON creator.id = detail.created_by
        LEFT JOIN users updater ON updater.id = detail.updated_by
        WHERE detail.workflow_id = ? AND detail.deleted_at IS NULL
        ORDER BY detail.sales_stage, detail.country_name, detail.account_name, detail.source_row, detail.created_at
        """,
        (workflow["id"],),
    ).fetchall()
    details = [public_forecast_round_detail(row) for row in detail_rows]
    checklist_rows = db.execute(
        """
        SELECT checklist.*, users.display_name AS completed_by_name
        FROM forecast_round_checklist checklist
        LEFT JOIN users ON users.id = checklist.completed_by
        WHERE checklist.workflow_id = ? ORDER BY checklist.sort_order, checklist.id
        """,
        (workflow["id"],),
    ).fetchall()
    checklist = [
        {
            "check_key": row["check_key"], "label": row["label"],
            "required": bool(row["required"]), "completed": bool(row["completed"]),
            "note": row["note"] or "", "completed_by_name": row["completed_by_name"],
            "completed_at": row["completed_at"],
        }
        for row in checklist_rows
    ]
    required = sum(1 for item in checklist if item["required"])
    completed = sum(1 for item in checklist if item["required"] and item["completed"])
    role = user["role"] if user else None
    is_draft = workflow["status"] == "draft"
    return {
        "id": workflow["id"], "forecast_month": workflow["forecast_month"],
        "round_no": int(workflow["round_no"]), "round_label": forecast_round_label(workflow["round_no"]),
        "as_of_date": workflow["as_of_date"],
        "rates": {
            "USD": float(workflow["usd_krw"] or 0), "EUR": float(workflow["eur_krw"] or 0),
            "JPY": float(workflow["jpy_krw"] or 0), "CNY": float(workflow["cny_krw"] or 0),
        },
        "exchange_rate": float(workflow["usd_krw"] or 0),
        "status": workflow["status"],
        "status_note": "확정 · 수정 잠금" if workflow["status"] == "confirmed" else "작성 중",
        "notes": workflow["notes"] or "", "source_name": workflow["source_name"],
        "source_version": workflow["source_version"], "updated_at": workflow["updated_at"],
        "updated_by_name": workflow["updated_by_name"], "confirmed_at": workflow["confirmed_at"],
        "confirmed_by_name": workflow["confirmed_by_name"], "business_units": business_units,
        "checklist": checklist,
        "details": details,
        "detail_summary": forecast_round_detail_summary(details, totals.get("current_expected")),
        "progress": {"completed": completed, "required": required, "percent": round(completed / required * 100) if required else 100},
        "permissions": {
            "can_edit": bool(is_draft and role in EDIT_ROLES),
            "can_confirm": bool(is_draft and role in MANAGE_ROLES),
            "can_reopen": bool(not is_draft and role in MANAGE_ROLES),
        },
    }


def forecast_round_overview_payload(db, forecast_month, user=None):
    workflows = db.execute(
        "SELECT round_no FROM forecast_round_workflows WHERE forecast_month = ? ORDER BY round_no",
        (forecast_month,),
    ).fetchall()
    rounds = [
        public_forecast_round_workflow(db, forecast_round_workflow_row(db, forecast_month, row["round_no"]), user)
        for row in workflows
    ]
    available_months = [
        row["forecast_month"] for row in db.execute(
            "SELECT DISTINCT forecast_month FROM forecast_round_workflows ORDER BY forecast_month DESC"
        ).fetchall()
    ]
    source = forecast_round_source_metadata()
    selected = next((round_data["round_no"] for round_data in rounds if round_data["status"] == "draft"), None)
    if selected is None and rounds:
        selected = rounds[-1]["round_no"]
    return {
        "forecast_month": forecast_month, "available_months": available_months,
        "source_name": source.get("source_name"), "source_version": source.get("version"),
        "currency": "KRW", "display_unit": "백만원",
        "business_units": [{"key": key, "label": label} for key, label in FORECAST_ROUND_BUSINESS_UNITS] + [{"key": "total", "label": "합계"}],
        "quality_notes": source.get("quality_notes", []), "rounds": rounds,
        "selected_round": selected, "review_status": "workflow",
        "detail_dimensions": [
            {"key": "round", "label": "차수별"}, {"key": "item", "label": "품목별"},
            {"key": "country", "label": "국가별"}, {"key": "account", "label": "거래처별"},
        ],
        "integration_status": "standalone_workbook_only",
        "integration_note": "업로드 엑셀 기준 · 기존 메뉴/ERP 미연동",
        "can_initialize": bool(user and user["role"] in MANAGE_ROLES and not rounds),
        "version": APP_VERSION,
    }


def normalize_forecast_round_number(value, label):
    if value in (None, ""):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} 금액 형식이 올바르지 않습니다.")
    if not math.isfinite(number) or number < 0 or number > 10 ** 15:
        raise ValueError(f"{label} 금액은 0 이상으로 입력하세요.")
    return number


def validate_forecast_round_stage(forecast_month, round_no):
    if not valid_forecast_month(forecast_month):
        raise ValueError("FCST 대상월 형식이 올바르지 않습니다.")
    if int(round_no) not in {0, 1, 2, 3}:
        raise ValueError("FCST 단계는 미정·1차·2차·3차 중에서 선택하세요.")


@app.get("/api/forecast-rounds/overview")
def forecast_round_overview():
    month = request.args.get("month", "2026-08").strip()
    try:
        validate_forecast_round_stage(month, 0)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    user = current_user_row()
    return jsonify(forecast_round_overview_payload(get_db(), month, user))


def forecast_round_detail_progress_status(data):
    explicit = str(data.get("progress_status") or "").strip()
    if explicit:
        return explicit
    if data.get("shipping_completed_at") or data.get("shipment_completed_at"):
        return "shipment_completed"
    if data.get("payment_completed_at"):
        return "payment_completed"
    if data.get("pi_sent_at"):
        return "pi_issued"
    return "order_received"


def normalize_forecast_round_detail(data):
    data = data if isinstance(data, dict) else {}
    sales_stage = str(data.get("sales_stage") or "undecided").strip()
    if sales_stage not in FORECAST_ROUND_DETAIL_STAGES:
        raise ValueError("매출구분은 확정·예정·추진·미정 중에서 선택하세요.")
    progress_status = forecast_round_detail_progress_status(data)
    if progress_status not in FORECAST_ROUND_DETAIL_PROGRESS_STATUSES:
        raise ValueError("진행상태는 오더접수·PI발행·입금완료·출고완료 중에서 선택하세요.")
    management_type = str(data.get("management_type") or "regular").strip()
    if management_type not in FORECAST_ROUND_DETAIL_MANAGEMENT_TYPES:
        raise ValueError("관리유형은 일반·추가추진·프로모션·임박재고 중에서 선택하세요.")
    business_unit = str(data.get("business_unit") or "").strip()
    if business_unit not in dict(FORECAST_ROUND_BUSINESS_UNITS):
        raise ValueError("사업분야는 에스테틱·메디컬·덴탈 중에서 선택하세요.")
    currency = str(data.get("currency") or "USD").strip().upper()
    if currency not in FORECAST_CURRENCIES:
        raise ValueError("통화는 KRW·USD·EUR·JPY·CNY 중에서 선택하세요.")
    normalized = {
        "sales_stage": sales_stage, "progress_status": progress_status,
        "management_type": management_type, "business_unit": business_unit,
        "classification": str(data.get("classification") or "").strip()[:100],
        "country_name": str(data.get("country_name") or "국가 미지정").strip()[:150] or "국가 미지정",
        "account_name": str(data.get("account_name") or "거래처 미지정").strip()[:200] or "거래처 미지정",
        "item_name": str(data.get("item_name") or "품목 미지정").strip()[:200] or "품목 미지정",
        "owner_name": str(data.get("owner_name") or "").strip()[:100],
        "timing_note": str(data.get("timing_note") or "").strip()[:200],
        "currency": currency,
        "change_reason": str(data.get("change_reason") or "").strip()[:500],
        "notes": str(data.get("notes") or "").strip()[:3000],
    }
    for field in FORECAST_ROUND_DETAIL_AMOUNT_FIELDS:
        normalized[field] = normalize_forecast_round_number(data.get(field), field)
    for field in FORECAST_ROUND_DETAIL_DATE_FIELDS:
        value = str(data.get(field) or "").strip()
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"{field} 일자 형식이 올바르지 않습니다.")
        normalized[field] = value or None
    target_date = str(data.get("target_date") or "").strip()
    if target_date:
        try:
            datetime.strptime(target_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("목표일 형식이 올바르지 않습니다.")
    normalized["target_date"] = target_date or None
    return normalized


def recalculate_forecast_round_detail_krw(values):
    """Recalculate only one detail row when its own applied FX rate changes."""
    rate = float(values.get("applied_rate") or 0)
    for foreign_field, krw_field in FORECAST_ROUND_DETAIL_FX_PAIRS:
        foreign_amount = float(values.get(foreign_field) or 0)
        # Preserve KRW-only workbook rows because they have no foreign basis.
        if foreign_amount:
            values[krw_field] = round(foreign_amount * rate)
    return values


def forecast_round_detail_mutation_context(db, forecast_month, round_no, detail_id=None):
    validate_forecast_round_stage(forecast_month, round_no)
    workflow = forecast_round_workflow_row(db, forecast_month, round_no)
    if not workflow:
        return None, None
    detail = None
    if detail_id:
        detail = db.execute(
            "SELECT * FROM forecast_round_details WHERE id = ? AND workflow_id = ? AND deleted_at IS NULL",
            (detail_id, workflow["id"]),
        ).fetchone()
    return workflow, detail


@app.get("/api/forecast-rounds/<forecast_month>/<int:round_no>/details")
def get_forecast_round_details(forecast_month, round_no):
    try:
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    workflow = forecast_round_workflow_row(db, forecast_month, round_no)
    if not workflow:
        return jsonify(error="선택한 FCST 차수 업무가 없습니다."), 404
    public_workflow = public_forecast_round_workflow(db, workflow, current_user_row())
    details = public_workflow["details"]
    business_unit = request.args.get("business_unit", "").strip()
    sales_stage = request.args.get("sales_stage", "").strip()
    search = request.args.get("search", "").strip().casefold()
    if business_unit:
        details = [item for item in details if item["business_unit"] == business_unit]
    if sales_stage:
        details = [item for item in details if item["sales_stage"] == sales_stage]
    if search:
        details = [
            item for item in details
            if search in " ".join(str(item.get(key) or "") for key in (
                "classification", "country_name", "account_name", "item_name", "owner_name", "change_reason", "notes"
            )).casefold()
        ]
    group_by = request.args.get("group_by", "round").strip()
    if group_by not in {"round", "item", "country", "account", "stage"}:
        return jsonify(error="조회 구분이 올바르지 않습니다."), 400
    return jsonify(
        forecast_month=forecast_month, round_no=round_no, round_label=forecast_round_label(round_no),
        status=workflow["status"], details=details,
        groups=forecast_round_detail_groups(details, group_by), group_by=group_by,
        summary=forecast_round_detail_summary(details, public_workflow["business_units"]["total"]["current_expected"]),
        integration_status="standalone_workbook_only",
    )


@app.post("/api/forecast-rounds/<forecast_month>/<int:round_no>/details")
@role_required("admin", "manager", "editor")
@csrf_required
def create_forecast_round_detail(forecast_month, round_no):
    try:
        values = normalize_forecast_round_detail(request.get_json(silent=True) or {})
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    workflow = forecast_round_workflow_row(db, forecast_month, round_no)
    if not workflow:
        return jsonify(error="선택한 FCST 차수 업무가 없습니다."), 404
    if workflow["status"] != "draft":
        return jsonify(error="확정된 차수에는 상세자료를 추가할 수 없습니다. 관리자에게 재개방을 요청하세요."), 409
    try:
        db.execute("BEGIN IMMEDIATE")
        current = forecast_round_workflow_row(db, forecast_month, round_no)
        if current["status"] != "draft":
            rollback_quietly(db)
            return jsonify(error="다른 사용자가 이 차수를 확정하여 추가할 수 없습니다."), 409
        detail_id = insert_forecast_round_detail(db, current["id"], values, g.current_user["id"], "manual")
        row = db.execute("SELECT * FROM forecast_round_details WHERE id = ?", (detail_id,)).fetchone()
        result = public_forecast_round_detail(row)
        audit("FORECAST_ROUND_DETAIL_CREATE", "forecast_round_detail", detail_id,
              f"{forecast_month} {forecast_round_label(round_no)} 상세자료 추가 · {values['account_name']}",
              after=result, connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST 상세자료를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message="FCST 상세자료를 추가했습니다.", detail=result), 201


@app.put("/api/forecast-rounds/<forecast_month>/<int:round_no>/details/<detail_id>")
@role_required("admin", "manager", "editor")
@csrf_required
def update_forecast_round_detail(forecast_month, round_no, detail_id):
    try:
        values = normalize_forecast_round_detail(request.get_json(silent=True) or {})
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    workflow, detail = forecast_round_detail_mutation_context(db, forecast_month, round_no, detail_id)
    if not workflow or not detail:
        return jsonify(error="수정할 FCST 상세자료가 없습니다."), 404
    if workflow["status"] != "draft":
        return jsonify(error="확정된 차수의 상세자료는 수정할 수 없습니다. 관리자에게 재개방을 요청하세요."), 409
    if abs(float(values["applied_rate"]) - float(detail["applied_rate"] or 0)) > 0.0000001:
        recalculate_forecast_round_detail_krw(values)
    before = public_forecast_round_detail(detail)
    try:
        db.execute("BEGIN IMMEDIATE")
        current = forecast_round_workflow_row(db, forecast_month, round_no)
        if current["status"] != "draft":
            rollback_quietly(db)
            return jsonify(error="다른 사용자가 이 차수를 확정하여 수정할 수 없습니다."), 409
        now = utc_now()
        db.execute(
            """
            UPDATE forecast_round_details SET sales_stage = ?, progress_status = ?, management_type = ?, business_unit = ?, classification = ?,
              country_name = ?, account_name = ?, item_name = ?, owner_name = ?, timing_note = ?, currency = ?,
              plan_foreign = ?, plan_krw = ?, carryover_foreign = ?, carryover_krw = ?,
              current_foreign = ?, current_krw = ?, next_foreign = ?, next_krw = ?,
              order_agreed_at = ?, po_received_at = ?, pi_sent_at = ?, payment_expected_at = ?,
              payment_completed_at = ?, shipment_expected_at = ?, shipment_completed_at = ?,
              shipping_completed_at = ?, target_date = ?, applied_rate = ?, change_reason = ?, notes = ?, updated_by = ?, updated_at = ?
            WHERE id = ? AND workflow_id = ? AND deleted_at IS NULL
            """,
            (
                values["sales_stage"], values["progress_status"], values["management_type"], values["business_unit"], values["classification"],
                values["country_name"], values["account_name"], values["item_name"], values["owner_name"],
                values["timing_note"], values["currency"],
                *[values[field] for field in FORECAST_ROUND_DETAIL_AMOUNT_FIELDS[:8]],
                *[values[field] for field in FORECAST_ROUND_DETAIL_DATE_FIELDS], values["target_date"], values["applied_rate"],
                values["change_reason"], values["notes"], g.current_user["id"], now, detail_id, current["id"],
            ),
        )
        result = public_forecast_round_detail(
            db.execute("SELECT * FROM forecast_round_details WHERE id = ?", (detail_id,)).fetchone()
        )
        audit("FORECAST_ROUND_DETAIL_UPDATE", "forecast_round_detail", detail_id,
              f"{forecast_month} {forecast_round_label(round_no)} 상세자료 수정 · {values['account_name']}",
              before, result, connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST 상세자료를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message="FCST 상세자료를 수정했습니다.", detail=result)


@app.delete("/api/forecast-rounds/<forecast_month>/<int:round_no>/details/<detail_id>")
@role_required("admin", "manager", "editor")
@csrf_required
def delete_forecast_round_detail(forecast_month, round_no, detail_id):
    try:
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    workflow, detail = forecast_round_detail_mutation_context(db, forecast_month, round_no, detail_id)
    if not workflow or not detail:
        return jsonify(error="삭제할 FCST 상세자료가 없습니다."), 404
    if workflow["status"] != "draft":
        return jsonify(error="확정된 차수의 상세자료는 삭제할 수 없습니다. 관리자에게 재개방을 요청하세요."), 409
    before = public_forecast_round_detail(detail)
    try:
        db.execute("BEGIN IMMEDIATE")
        current = forecast_round_workflow_row(db, forecast_month, round_no)
        if current["status"] != "draft":
            rollback_quietly(db)
            return jsonify(error="다른 사용자가 이 차수를 확정하여 삭제할 수 없습니다."), 409
        now = utc_now()
        db.execute(
            "UPDATE forecast_round_details SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ? WHERE id = ? AND workflow_id = ? AND deleted_at IS NULL",
            (now, g.current_user["id"], g.current_user["id"], now, detail_id, current["id"]),
        )
        audit("FORECAST_ROUND_DETAIL_DELETE", "forecast_round_detail", detail_id,
              f"{forecast_month} {forecast_round_label(round_no)} 상세자료 삭제 · {before['account_name']}",
              before=before, connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST 상세자료를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message="FCST 상세자료를 삭제했습니다.")


@app.post("/api/forecast-rounds/initialize")
@role_required("admin", "manager")
@csrf_required
def initialize_forecast_round_workflows():
    data = request.get_json(silent=True) or {}
    month = str(data.get("forecast_month") or "").strip()
    if not valid_forecast_month(month):
        return jsonify(error="FCST 대상월 형식이 올바르지 않습니다."), 400
    db = get_db()
    if db.execute("SELECT 1 FROM forecast_round_workflows WHERE forecast_month = ?", (month,)).fetchone():
        return jsonify(error="이미 시작된 대상월입니다."), 409
    try:
        db.execute("BEGIN IMMEDIATE")
        for round_no in range(4):
            insert_forecast_round_workflow(db, month, round_no, g.current_user["id"])
        audit("FORECAST_ROUND_INITIALIZE", "forecast_round_workflow", month, f"{month} 미정·1·2·3차 업무 시작", connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message=f"{month} FCST 차수 업무를 시작했습니다.", **forecast_round_overview_payload(db, month, g.current_user)), 201


@app.put("/api/forecast-rounds/<forecast_month>/<int:round_no>")
@role_required("admin", "manager", "editor")
@csrf_required
def save_forecast_round_workflow(forecast_month, round_no):
    try:
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    data = request.get_json(silent=True) or {}
    as_of_date = str(data.get("as_of_date") or "").strip()
    if as_of_date:
        try:
            datetime.strptime(as_of_date, "%Y-%m-%d")
        except ValueError:
            return jsonify(error="기준일 형식이 올바르지 않습니다."), 400
    rates_input = data.get("rates") or {}
    try:
        rates = {currency: normalize_forecast_round_number(rates_input.get(currency), f"{currency} 환율") for currency in ("USD", "EUR", "JPY", "CNY")}
        entries_input = data.get("entries") or {}
        normalized_entries = {}
        labels = {
            "plan": "사업계획", "initial_fcst": "월초 FCST", "first_expected": "1차 예상",
            "carryover": "전월 이월", "current_month": "당월 확정·예정", "pipeline": "당월 추진",
            "next_month": "차월 확정·예정", "next_pipeline": "차월 추진",
        }
        for business_unit, business_label in FORECAST_ROUND_BUSINESS_UNITS:
            values = entries_input.get(business_unit) or {}
            normalized_entries[business_unit] = {
                key: normalize_forecast_round_number(values.get(key), f"{business_label} {label}")
                for key, label in labels.items()
            }
            normalized_entries[business_unit]["notes"] = str(values.get("notes") or "")[:1000]
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    checklist_input = {str(item.get("check_key")): item for item in (data.get("checklist") or []) if isinstance(item, dict)}
    db = get_db()
    workflow = forecast_round_workflow_row(db, forecast_month, round_no)
    if not workflow:
        return jsonify(error="선택한 FCST 차수 업무가 없습니다."), 404
    before = public_forecast_round_workflow(db, workflow, g.current_user)
    try:
        db.execute("BEGIN IMMEDIATE")
        current = forecast_round_workflow_row(db, forecast_month, round_no)
        if current["status"] != "draft":
            rollback_quietly(db)
            return jsonify(error="확정된 차수는 수정할 수 없습니다. 관리자에게 재개방을 요청하세요."), 409
        now = utc_now()
        db.execute(
            """
            UPDATE forecast_round_workflows SET as_of_date = ?, usd_krw = ?, eur_krw = ?, jpy_krw = ?,
              cny_krw = ?, notes = ?, updated_by = ?, updated_at = ? WHERE id = ?
            """,
            (as_of_date or None, rates["USD"], rates["EUR"], rates["JPY"], rates["CNY"],
             str(data.get("notes") or "")[:2000], g.current_user["id"], now, current["id"]),
        )
        for business_unit, _label in FORECAST_ROUND_BUSINESS_UNITS:
            values = normalized_entries[business_unit]
            db.execute(
                """
                UPDATE forecast_round_entries SET plan_krw = ?, initial_fcst_krw = ?, first_expected_krw = ?,
                  carryover_krw = ?, current_month_krw = ?, pipeline_krw = ?, next_month_krw = ?,
                  next_pipeline_krw = ?, notes = ?, updated_at = ?
                WHERE workflow_id = ? AND business_unit = ?
                """,
                (values["plan"], values["initial_fcst"], values["first_expected"], values["carryover"],
                 values["current_month"], values["pipeline"], values["next_month"], values["next_pipeline"],
                 values["notes"], now, current["id"], business_unit),
            )
        for check_key, _label in FORECAST_ROUND_CHECKLIST:
            item = checklist_input.get(check_key) or {}
            completed = 1 if item.get("completed") else 0
            db.execute(
                """
                UPDATE forecast_round_checklist SET completed = ?, note = ?, completed_by = ?, completed_at = ?
                WHERE workflow_id = ? AND check_key = ?
                """,
                (completed, str(item.get("note") or "")[:500], g.current_user["id"] if completed else None,
                 now if completed else None, current["id"], check_key),
            )
        after = public_forecast_round_workflow(db, forecast_round_workflow_row(db, forecast_month, round_no), g.current_user)
        audit("FORECAST_ROUND_SAVE", "forecast_round_workflow", current["id"], f"{forecast_month} {forecast_round_label(round_no)} 저장", before, after, connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message=f"{forecast_round_label(round_no)} 내용을 저장했습니다.", workflow=after)


@app.post("/api/forecast-rounds/<forecast_month>/<int:round_no>/confirm")
@role_required("admin", "manager")
@csrf_required
def confirm_forecast_round_workflow(forecast_month, round_no):
    try:
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    workflow = forecast_round_workflow_row(db, forecast_month, round_no)
    if not workflow:
        return jsonify(error="선택한 FCST 차수 업무가 없습니다."), 404
    if workflow["status"] == "confirmed":
        return jsonify(error="이미 확정된 차수입니다."), 409
    if round_no > 0:
        previous = forecast_round_workflow_row(db, forecast_month, round_no - 1)
        if not previous or previous["status"] != "confirmed":
            return jsonify(error=f"먼저 {forecast_round_label(round_no - 1)} 단계를 확정해 주세요."), 409
    if not workflow["as_of_date"]:
        return jsonify(error="확정 전에 기준일을 입력하세요."), 400
    if any(float(workflow[f"{currency.lower()}_krw"] or 0) <= 0 for currency in ("USD", "EUR", "JPY", "CNY")):
        return jsonify(error="확정 전에 USD·EUR·JPY·CNY 환율을 모두 입력하세요."), 400
    missing = db.execute(
        "SELECT label FROM forecast_round_checklist WHERE workflow_id = ? AND required = 1 AND completed = 0 ORDER BY sort_order",
        (workflow["id"],),
    ).fetchall()
    if missing:
        return jsonify(error="필수 체크리스트를 모두 완료하세요.", detail=[row["label"] for row in missing]), 400
    total = db.execute(
        """
        SELECT SUM(plan_krw + initial_fcst_krw + first_expected_krw + carryover_krw + current_month_krw +
                   pipeline_krw + next_month_krw + next_pipeline_krw) AS total
        FROM forecast_round_entries WHERE workflow_id = ?
        """,
        (workflow["id"],),
    ).fetchone()["total"] or 0
    if total <= 0:
        return jsonify(error="확정할 매출 자료가 없습니다. 사업분야별 금액을 먼저 입력하세요."), 400
    before = public_forecast_round_workflow(db, workflow, g.current_user)
    now = utc_now()
    try:
        db.execute("BEGIN IMMEDIATE")
        current = forecast_round_workflow_row(db, forecast_month, round_no)
        if current["status"] != "draft":
            rollback_quietly(db)
            return jsonify(error="다른 사용자가 이미 이 차수를 확정했습니다."), 409
        db.execute(
            """
            UPDATE forecast_round_workflows SET status = 'confirmed', confirmed_by = ?, confirmed_at = ?,
              updated_by = ?, updated_at = ? WHERE id = ?
            """,
            (g.current_user["id"], now, g.current_user["id"], now, current["id"]),
        )
        after = public_forecast_round_workflow(db, forecast_round_workflow_row(db, forecast_month, round_no), g.current_user)
        audit("FORECAST_ROUND_CONFIRM", "forecast_round_workflow", current["id"], f"{forecast_month} {forecast_round_label(round_no)} 확정·잠금", before, after, connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message=f"{forecast_round_label(round_no)}를 확정하고 수정 잠금했습니다.", workflow=after)


@app.post("/api/forecast-rounds/<forecast_month>/<int:round_no>/reopen")
@role_required("admin", "manager")
@csrf_required
def reopen_forecast_round_workflow(forecast_month, round_no):
    try:
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if len(reason) < 2:
        return jsonify(error="재개방 사유를 입력하세요."), 400
    db = get_db()
    workflow = forecast_round_workflow_row(db, forecast_month, round_no)
    if not workflow:
        return jsonify(error="선택한 FCST 차수 업무가 없습니다."), 404
    if workflow["status"] != "confirmed":
        return jsonify(error="확정된 차수만 재개방할 수 있습니다."), 409
    downstream = db.execute(
        "SELECT round_no FROM forecast_round_workflows WHERE forecast_month = ? AND round_no > ? AND status = 'confirmed' ORDER BY round_no DESC LIMIT 1",
        (forecast_month, round_no),
    ).fetchone()
    if downstream:
        return jsonify(error=f"먼저 {forecast_round_label(downstream['round_no'])} 확정을 재개방하세요."), 409
    before = public_forecast_round_workflow(db, workflow, g.current_user)
    now = utc_now()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """
            UPDATE forecast_round_workflows SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL,
              updated_by = ?, updated_at = ? WHERE id = ? AND status = 'confirmed'
            """,
            (g.current_user["id"], now, workflow["id"]),
        )
        after = public_forecast_round_workflow(db, forecast_round_workflow_row(db, forecast_month, round_no), g.current_user)
        audit("FORECAST_ROUND_REOPEN", "forecast_round_workflow", workflow["id"], f"{forecast_month} {forecast_round_label(round_no)} 재개방 · {reason}", before, after, connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message=f"{forecast_round_label(round_no)}를 재개방했습니다.", workflow=after)


@app.post("/api/forecast-rounds/<forecast_month>/<int:round_no>/copy-next")
@role_required("admin", "manager")
@csrf_required
def copy_forecast_round_workflow_next(forecast_month, round_no):
    try:
        validate_forecast_round_stage(forecast_month, round_no)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if round_no >= 3:
        return jsonify(error="3차는 다음 차수로 이관할 수 없습니다."), 400
    db = get_db()
    source = forecast_round_workflow_row(db, forecast_month, round_no)
    target = forecast_round_workflow_row(db, forecast_month, round_no + 1)
    if not source or not target:
        return jsonify(error="이관할 FCST 차수 업무가 없습니다."), 404
    if source["status"] != "confirmed":
        return jsonify(error="현재 차수를 확정한 뒤 다음 차수로 이관하세요."), 409
    if target["status"] != "draft":
        return jsonify(error="다음 차수가 이미 확정되어 이관할 수 없습니다."), 409
    target_amount = db.execute(
        """
        SELECT SUM(plan_krw + initial_fcst_krw + first_expected_krw + carryover_krw + current_month_krw +
                   pipeline_krw + next_month_krw + next_pipeline_krw) AS total
        FROM forecast_round_entries WHERE workflow_id = ?
        """,
        (target["id"],),
    ).fetchone()["total"] or 0
    if target_amount > 0:
        return jsonify(error="다음 차수에 이미 입력된 자료가 있어 자동 이관하지 않았습니다."), 409
    target_detail_count = db.execute(
        "SELECT COUNT(*) AS count FROM forecast_round_details WHERE workflow_id = ? AND deleted_at IS NULL",
        (target["id"],),
    ).fetchone()["count"]
    if target_detail_count:
        return jsonify(error="다음 차수에 이미 상세자료가 있어 자동 이관하지 않았습니다."), 409
    before = public_forecast_round_workflow(db, target, g.current_user)
    now = utc_now()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """
            UPDATE forecast_round_workflows SET as_of_date = ?, usd_krw = ?, eur_krw = ?, jpy_krw = ?,
              cny_krw = ?, notes = ?, updated_by = ?, updated_at = ? WHERE id = ?
            """,
            (source["as_of_date"], source["usd_krw"], source["eur_krw"], source["jpy_krw"], source["cny_krw"],
             f"{forecast_round_label(round_no)} 확정본 이관", g.current_user["id"], now, target["id"]),
        )
        source_entries = db.execute("SELECT * FROM forecast_round_entries WHERE workflow_id = ?", (source["id"],)).fetchall()
        for entry in source_entries:
            db.execute(
                """
                UPDATE forecast_round_entries SET plan_krw = ?, initial_fcst_krw = ?, first_expected_krw = ?,
                  carryover_krw = ?, current_month_krw = ?, pipeline_krw = ?, next_month_krw = ?,
                  next_pipeline_krw = ?, notes = ?, updated_at = ?
                WHERE workflow_id = ? AND business_unit = ?
                """,
                (entry["plan_krw"], entry["initial_fcst_krw"], entry["first_expected_krw"], entry["carryover_krw"],
                 entry["current_month_krw"], entry["pipeline_krw"], entry["next_month_krw"], entry["next_pipeline_krw"],
                 entry["notes"], now, target["id"], entry["business_unit"]),
            )
        db.execute(
            "UPDATE forecast_round_checklist SET completed = 0, note = '', completed_by = NULL, completed_at = NULL WHERE workflow_id = ?",
            (target["id"],),
        )
        source_details = db.execute(
            "SELECT * FROM forecast_round_details WHERE workflow_id = ? AND deleted_at IS NULL ORDER BY created_at, id",
            (source["id"],),
        ).fetchall()
        for detail in source_details:
            copied = row_dict(detail)
            copied["source_row"] = None
            insert_forecast_round_detail(db, target["id"], copied, g.current_user["id"], "copied")
        after = public_forecast_round_workflow(db, forecast_round_workflow_row(db, forecast_month, round_no + 1), g.current_user)
        audit("FORECAST_ROUND_COPY_NEXT", "forecast_round_workflow", target["id"], f"{forecast_month} {forecast_round_label(round_no)} → {forecast_round_label(round_no + 1)} 이관", before, after, connection=db)
        db.commit()
    except sqlite3.Error as exc:
        rollback_quietly(db)
        if sqlite_is_busy(exc):
            return jsonify(error="다른 사용자가 FCST를 저장 중입니다. 잠시 후 다시 시도하세요.", code="DATABASE_BUSY"), 409
        raise
    return jsonify(message=f"{forecast_round_label(round_no + 1)}로 확정값을 이관했습니다.", workflow=after)


def normalize_cycle_input(data):
    month = str(data.get("forecast_month", "")).strip()
    if not valid_forecast_month(month):
        raise ValueError("FCST 대상월을 YYYY-MM 형식으로 입력하세요.")
    try:
        round_no = int(data.get("round_no"))
    except (TypeError, ValueError):
        raise ValueError("FCST 차수는 1~3차로 입력하세요.")
    if round_no not in {1, 2, 3}:
        raise ValueError("FCST 차수는 1~3차로 입력하세요.")
    as_of_date = str(data.get("as_of_date", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
        raise ValueError("기준일 형식이 올바르지 않습니다.")
    rates = {}
    for currency in ("usd", "eur", "jpy", "cny"):
        try:
            rates[f"{currency}_krw"] = float(data.get(f"{currency}_krw") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"{currency.upper()} 기준환율은 숫자로 입력하세요.")
        if rates[f"{currency}_krw"] <= 0:
            raise ValueError(f"{currency.upper()} 기준환율은 0보다 커야 합니다.")
    status = str(data.get("status", "open")).strip()
    if status not in {"open", "closed"}:
        status = "open"
    return {"forecast_month": month, "round_no": round_no, "as_of_date": as_of_date, "status": status, **rates}


@app.post("/api/forecast/cycles")
@role_required("admin", "manager")
@csrf_required
def save_forecast_cycle():
    if not DATABASE_SCHEMA_READY.is_set():
        return jsonify(error="FCST 환율 구조를 적용하고 있습니다. 잠시 후 다시 시도하세요.", code="DATABASE_MIGRATING"), 503
    try:
        values = normalize_cycle_input(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    existing = db.execute(
        "SELECT * FROM forecast_cycles WHERE forecast_month = ? AND round_no = ?",
        (values["forecast_month"], values["round_no"]),
    ).fetchone()
    now = utc_now()
    if existing:
        before = public_forecast_cycle(existing)
        db.execute(
            """
            UPDATE forecast_cycles SET as_of_date = ?, usd_krw = ?, eur_krw = ?, jpy_krw = ?, cny_krw = ?,
              status = ?, updated_by = ?, updated_at = ? WHERE id = ?
            """,
            (values["as_of_date"], values["usd_krw"], values["eur_krw"], values["jpy_krw"], values["cny_krw"], values["status"], g.current_user["id"], now, existing["id"]),
        )
        cycle_id = existing["id"]
        action = "FORECAST_CYCLE_UPDATE"
        message = f"{values['forecast_month']} {values['round_no']}차 FCST 기준이 수정되었습니다."
    else:
        cycle_id = uuid.uuid4().hex
        before = None
        db.execute(
            """
            INSERT INTO forecast_cycles
              (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, jpy_krw, cny_krw, status,
               created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cycle_id, values["forecast_month"], values["round_no"], values["as_of_date"], values["usd_krw"], values["eur_krw"], values["jpy_krw"], values["cny_krw"], values["status"], g.current_user["id"], g.current_user["id"], now, now),
        )
        action = "FORECAST_CYCLE_CREATE"
        message = f"{values['forecast_month']} {values['round_no']}차 FCST가 생성되었습니다."
    saved = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (cycle_id,)).fetchone()
    audit(action, "forecast_cycle", cycle_id, message, before, public_forecast_cycle(saved))
    db.commit()
    return jsonify(message=message, cycle=public_forecast_cycle(saved))


def normalize_forecast_item(data, existing=None):
    getter = lambda key, default=None: data.get(key, existing[key] if existing is not None and key in existing.keys() else default)
    cycle_id = str(getter("cycle_id", "") or "").strip()
    title = str(getter("title", "") or "").strip()
    if not cycle_id:
        raise ValueError("FCST 차수를 먼저 선택하세요.")
    if not title or len(title) > 200:
        raise ValueError("FCST 항목명은 1~200자로 입력하세요.")
    stage = str(getter("stage", "sales_activity") or "sales_activity").strip()
    if stage not in FORECAST_INPUT_STAGES:
        raise ValueError("영업단계가 올바르지 않습니다.")
    currency = str(getter("currency", "USD") or "USD").upper().strip()
    if currency not in FORECAST_CURRENCIES:
        raise ValueError("지원하지 않는 통화입니다.")
    business_unit = str(getter("business_unit", "unclassified") or "unclassified").strip()
    if business_unit not in FORECAST_BUSINESS_UNITS:
        raise ValueError("사업분야가 올바르지 않습니다.")
    try:
        amount = float(getter("foreign_amount", 0) or 0)
        confidence_raw = getter("confidence", FORECAST_STAGES[stage]["confidence"])
        confidence = float(confidence_raw if confidence_raw not in (None, "") else FORECAST_STAGES[stage]["confidence"])
    except (TypeError, ValueError):
        raise ValueError("금액과 확률은 숫자로 입력하세요.")
    if amount < 0 or not 0 <= confidence <= 100:
        raise ValueError("금액은 0 이상, 확률은 0~100으로 입력하세요.")
    expected_ship_date = str(getter("expected_ship_date", "") or "").strip() or None
    if expected_ship_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected_ship_date):
        raise ValueError("예상 출고일 형식이 올바르지 않습니다.")
    owner_id = getter("owner_id", None)
    owner_id = int(owner_id) if str(owner_id or "").isdigit() else None
    return {
        "cycle_id": cycle_id,
        "title": title,
        "account_id": str(getter("account_id", "") or "").strip() or None,
        "account_name": str(getter("account_name", "") or "").strip()[:200],
        "business_unit": business_unit,
        "item_name": str(getter("item_name", "") or "").strip()[:200],
        "stage": stage,
        "confidence": confidence,
        "foreign_amount": amount,
        "currency": currency,
        "expected_ship_date": expected_ship_date,
        "owner_id": owner_id,
        "notes": str(getter("notes", "") or "").strip()[:2000],
    }


def can_modify_forecast_item(user, row):
    return user["role"] in MANAGE_ROLES or (user["role"] == "editor" and (row["owner_id"] == user["id"] or row["created_by"] == user["id"]))


def forecast_item_with_owner(db, item_id):
    return db.execute(
        """
        SELECT f.*, u.display_name AS owner_name,
          a.country AS account_country, a.region AS account_region
        FROM forecast_items f
        LEFT JOIN users u ON u.id = f.owner_id
        LEFT JOIN records a ON a.id = f.account_id AND a.entity_type = 'account' AND a.deleted_at IS NULL
        WHERE f.id = ?
        """,
        (item_id,),
    ).fetchone()


@app.post("/api/forecast/items")
@role_required("admin", "manager", "editor")
@csrf_required
def create_forecast_item():
    data = request.get_json(silent=True) or {}
    try:
        values = normalize_forecast_item(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    cycle = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (values["cycle_id"],)).fetchone()
    if not cycle:
        return jsonify(error="선택한 FCST 차수를 찾을 수 없습니다."), 404
    if cycle["status"] == "closed":
        return jsonify(error="마감된 FCST 차수에는 항목을 추가할 수 없습니다."), 409
    if g.current_user["role"] == "editor" or values["owner_id"] is None:
        values["owner_id"] = g.current_user["id"]
    item_id = uuid.uuid4().hex
    now = utc_now()
    db.execute(
        """
        INSERT INTO forecast_items
          (id, cycle_id, title, account_id, account_name, business_unit, item_name, stage,
           confidence, foreign_amount, currency, expected_ship_date, owner_id, notes,
           created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, values["cycle_id"], values["title"], values["account_id"], values["account_name"], values["business_unit"], values["item_name"], values["stage"], values["confidence"], values["foreign_amount"], values["currency"], values["expected_ship_date"], values["owner_id"], values["notes"], g.current_user["id"], g.current_user["id"], now, now),
    )
    created = forecast_item_with_owner(db, item_id)
    public = public_forecast_item(created, row_dict(cycle))
    audit("FORECAST_CREATE", "forecast", item_id, f"{cycle['forecast_month']} {cycle['round_no']}차 · {values['title']} 생성", None, public)
    db.commit()
    return jsonify(message="FCST 항목이 등록되었습니다.", item=public), 201


@app.patch("/api/forecast/items/<item_id>")
@role_required("admin", "manager", "editor")
@csrf_required
def update_forecast_item(item_id):
    db = get_db()
    existing = db.execute("SELECT * FROM forecast_items WHERE id = ? AND deleted_at IS NULL", (item_id,)).fetchone()
    if not existing:
        return jsonify(error="FCST 항목을 찾을 수 없습니다."), 404
    if existing["source_type"] == "promotion":
        return jsonify(error="프로모션에서 자동 반영된 FCST입니다. 프로모션 관리에서 수정하세요."), 409
    if not can_modify_forecast_item(g.current_user, existing):
        return jsonify(error="본인이 담당한 FCST만 수정할 수 있습니다."), 403
    cycle = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (existing["cycle_id"],)).fetchone()
    if cycle["status"] == "closed":
        return jsonify(error="마감된 FCST 차수는 수정할 수 없습니다."), 409
    try:
        values = normalize_forecast_item(request.get_json(silent=True) or {}, existing)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if values["cycle_id"] != existing["cycle_id"]:
        return jsonify(error="FCST 차수는 수정할 수 없습니다. 차수 복사 기능을 이용하세요."), 400
    if g.current_user["role"] == "editor":
        values["owner_id"] = existing["owner_id"] or g.current_user["id"]
    before = public_forecast_item(existing, row_dict(cycle))
    now = utc_now()
    db.execute(
        """
        UPDATE forecast_items SET title = ?, account_id = ?, account_name = ?, business_unit = ?,
          item_name = ?, stage = ?, confidence = ?, foreign_amount = ?, currency = ?,
          expected_ship_date = ?, owner_id = ?, notes = ?, updated_by = ?, updated_at = ?
        WHERE id = ?
        """,
        (values["title"], values["account_id"], values["account_name"], values["business_unit"], values["item_name"], values["stage"], values["confidence"], values["foreign_amount"], values["currency"], values["expected_ship_date"], values["owner_id"], values["notes"], g.current_user["id"], now, item_id),
    )
    updated = forecast_item_with_owner(db, item_id)
    public = public_forecast_item(updated, row_dict(cycle))
    audit("FORECAST_UPDATE", "forecast", item_id, f"{values['title']} FCST 수정", before, public)
    db.commit()
    return jsonify(message="FCST 항목이 수정되었습니다.", item=public)


@app.delete("/api/forecast/items/<item_id>")
@role_required("admin", "manager", "editor")
@csrf_required
def delete_forecast_item(item_id):
    db = get_db()
    existing = db.execute("SELECT * FROM forecast_items WHERE id = ? AND deleted_at IS NULL", (item_id,)).fetchone()
    if not existing:
        return jsonify(error="FCST 항목을 찾을 수 없습니다."), 404
    if existing["source_type"] == "promotion":
        return jsonify(error="프로모션에서 자동 반영된 FCST입니다. 프로모션 관리에서 해제하거나 취소하세요."), 409
    if not can_modify_forecast_item(g.current_user, existing):
        return jsonify(error="본인이 담당한 FCST만 삭제할 수 있습니다."), 403
    cycle = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (existing["cycle_id"],)).fetchone()
    if cycle["status"] == "closed":
        return jsonify(error="마감된 FCST 차수는 삭제할 수 없습니다."), 409
    before = public_forecast_item(existing, row_dict(cycle))
    now = utc_now()
    db.execute(
        "UPDATE forecast_items SET deleted_at = ?, deleted_by = ?, updated_by = ?, updated_at = ? WHERE id = ?",
        (now, g.current_user["id"], g.current_user["id"], now, item_id),
    )
    audit("FORECAST_DELETE", "forecast", item_id, f"{existing['title']} FCST 삭제", before, {"deleted_at": now})
    db.commit()
    return jsonify(message="FCST 항목이 삭제되었습니다. 변경 이력은 보존됩니다.")


@app.post("/api/forecast/items/<item_id>/carryover")
@role_required("admin", "manager", "editor")
@csrf_required
def carryover_forecast_item(item_id):
    if not DATABASE_SCHEMA_READY.is_set():
        return jsonify(error="FCST 환율 구조를 적용하고 있습니다. 잠시 후 다시 시도하세요.", code="DATABASE_MIGRATING"), 503
    db = get_db()
    existing = db.execute("SELECT * FROM forecast_items WHERE id = ? AND deleted_at IS NULL", (item_id,)).fetchone()
    if not existing or existing["status"] != "active":
        return jsonify(error="이월할 FCST 항목을 찾을 수 없습니다."), 404
    if existing["source_type"] == "promotion":
        return jsonify(error="프로모션 자동 반영 건은 프로모션의 매출 반영월을 변경하면 이월됩니다."), 409
    if not can_modify_forecast_item(g.current_user, existing):
        return jsonify(error="본인이 담당한 FCST만 이월할 수 있습니다."), 403
    source_cycle = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (existing["cycle_id"],)).fetchone()
    data = request.get_json(silent=True) or {}
    target_month = str(data.get("target_month") or shift_month(source_cycle["forecast_month"], 1)).strip()
    target_round = int(data.get("target_round") or 1)
    if not valid_forecast_month(target_month) or target_round not in {1, 2, 3}:
        return jsonify(error="이월 대상월 또는 차수가 올바르지 않습니다."), 400
    target_cycle = db.execute(
        "SELECT * FROM forecast_cycles WHERE forecast_month = ? AND round_no = ?",
        (target_month, target_round),
    ).fetchone()
    if not target_cycle:
        cycle_id = uuid.uuid4().hex
        now = utc_now()
        db.execute(
            """
            INSERT INTO forecast_cycles
              (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, jpy_krw, cny_krw, status,
               created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
            """,
            (cycle_id, target_month, target_round, datetime.now(timezone.utc).date().isoformat(), source_cycle["usd_krw"], source_cycle["eur_krw"], source_cycle["jpy_krw"], source_cycle["cny_krw"], g.current_user["id"], g.current_user["id"], now, now),
        )
        target_cycle = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (cycle_id,)).fetchone()
    if target_cycle["status"] == "closed":
        return jsonify(error="이월 대상 FCST 차수가 마감되어 있습니다."), 409
    duplicate = db.execute(
        "SELECT id FROM forecast_items WHERE cycle_id = ? AND carryover_from_id = ? AND deleted_at IS NULL",
        (target_cycle["id"], item_id),
    ).fetchone()
    if duplicate:
        return jsonify(error="이미 해당 월로 이월된 항목입니다."), 409
    new_id = uuid.uuid4().hex
    now = utc_now()
    expected_date = existing["expected_ship_date"]
    if expected_date and expected_date[:7] == source_cycle["forecast_month"]:
        expected_date = f"{target_month}-{min(int(expected_date[8:10]), calendar.monthrange(int(target_month[:4]), int(target_month[5:7]))[1]):02d}"
    db.execute(
        """
        INSERT INTO forecast_items
          (id, cycle_id, title, account_id, account_name, business_unit, item_name, stage,
           confidence, foreign_amount, currency, expected_ship_date, owner_id, notes, status,
           carryover_from_id, carryover_from_month, source_type, source_id,
           created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id, target_cycle["id"], existing["title"], existing["account_id"], existing["account_name"], existing["business_unit"], existing["item_name"], existing["stage"], existing["confidence"], existing["foreign_amount"], existing["currency"], expected_date, existing["owner_id"], existing["notes"], item_id, source_cycle["forecast_month"], existing["source_type"], existing["source_id"], g.current_user["id"], g.current_user["id"], now, now),
    )
    db.execute(
        "UPDATE forecast_items SET status = 'carried_over', updated_by = ?, updated_at = ? WHERE id = ?",
        (g.current_user["id"], now, item_id),
    )
    created = forecast_item_with_owner(db, new_id)
    public = public_forecast_item(created, row_dict(target_cycle))
    audit("FORECAST_CARRYOVER", "forecast", item_id, f"{existing['title']} · {source_cycle['forecast_month']}에서 {target_month}로 이월", public_forecast_item(existing, row_dict(source_cycle)), public)
    db.commit()
    return jsonify(message=f"{target_month} {target_round}차 FCST로 이월되었습니다.", item=public, target_cycle=public_forecast_cycle(target_cycle))


@app.post("/api/forecast/cycles/<cycle_id>/copy-next")
@role_required("admin", "manager")
@csrf_required
def copy_forecast_cycle(cycle_id):
    if not DATABASE_SCHEMA_READY.is_set():
        return jsonify(error="FCST 환율 구조를 적용하고 있습니다. 잠시 후 다시 시도하세요.", code="DATABASE_MIGRATING"), 503
    db = get_db()
    source = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (cycle_id,)).fetchone()
    if not source:
        return jsonify(error="복사할 FCST 차수를 찾을 수 없습니다."), 404
    if source["round_no"] >= 3:
        return jsonify(error="3차 가마감은 다음 차수로 복사할 수 없습니다. 다음 달 이월 기능을 이용하세요."), 400
    target_round = source["round_no"] + 1
    if db.execute("SELECT 1 FROM forecast_cycles WHERE forecast_month = ? AND round_no = ?", (source["forecast_month"], target_round)).fetchone():
        return jsonify(error=f"이미 {target_round}차 FCST가 존재합니다."), 409
    now = utc_now()
    target_id = uuid.uuid4().hex
    db.execute(
        """
        INSERT INTO forecast_cycles
          (id, forecast_month, round_no, as_of_date, usd_krw, eur_krw, jpy_krw, cny_krw, status,
           created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
        """,
        (target_id, source["forecast_month"], target_round, datetime.now(timezone.utc).date().isoformat(), source["usd_krw"], source["eur_krw"], source["jpy_krw"], source["cny_krw"], g.current_user["id"], g.current_user["id"], now, now),
    )
    rows = db.execute(
        "SELECT * FROM forecast_items WHERE cycle_id = ? AND deleted_at IS NULL AND status = 'active'",
        (source["id"],),
    ).fetchall()
    for row in rows:
        new_id = uuid.uuid4().hex
        db.execute(
            """
            INSERT INTO forecast_items
              (id, cycle_id, title, account_id, account_name, business_unit, item_name, stage,
               confidence, foreign_amount, currency, expected_ship_date, owner_id, notes, status,
               carryover_from_id, carryover_from_month, copied_from_id,
               source_type, source_id, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id, target_id, row["title"], row["account_id"], row["account_name"], row["business_unit"], row["item_name"], row["stage"], row["confidence"], row["foreign_amount"], row["currency"], row["expected_ship_date"], row["owner_id"], row["notes"], row["carryover_from_id"], row["carryover_from_month"], row["id"], row["source_type"], row["source_id"], g.current_user["id"], g.current_user["id"], now, now),
        )
    target = db.execute("SELECT * FROM forecast_cycles WHERE id = ?", (target_id,)).fetchone()
    audit("FORECAST_ROUND_COPY", "forecast_cycle", target_id, f"{source['forecast_month']} {source['round_no']}차를 {target_round}차로 복사 · {len(rows)}건", public_forecast_cycle(source), public_forecast_cycle(target))
    db.commit()
    return jsonify(message=f"{target_round}차 FCST가 {len(rows)}건과 함께 생성되었습니다.", cycle=public_forecast_cycle(target), copied_count=len(rows))


@app.get("/api/sales")
def sales():
    year = request.args.get("year", str(datetime.now(timezone.utc).year))
    if not re.fullmatch(r"\d{4}", year):
        return jsonify(error="연도 형식이 올바르지 않습니다."), 400
    segment = request.args.get("segment", "all").strip().lower()
    if segment not in OVERSEAS_BUSINESS_UNITS | {"all"}:
        return jsonify(error="사업군 필터가 올바르지 않습니다."), 400
    selected_month = request.args.get("month", "all").strip().lower()
    if selected_month != "all" and not re.fullmatch(rf"{year}-(0[1-9]|1[0-2])", selected_month):
        return jsonify(error="월 필터가 올바르지 않습니다."), 400
    country_code = str(request.args.get("country", "") or "").strip().zfill(3)
    country_info = next((item for item in world_country_index().values() if item["map_id"] == country_code), None) if country_code.strip("0") else None
    if country_code.strip("0") and not country_info:
        return jsonify(error="국가 필터가 올바르지 않습니다."), 400
    db = get_db()
    date_params = (f"{year}-01-01", f"{year}-12-31")
    selected_where = "is_overseas = 1 AND ship_date BETWEEN ? AND ?"
    selected_params = list(date_params)
    if segment != "all":
        selected_where += " AND business_unit = ?"
        selected_params.append(segment)
    if country_info:
        selected_where += " AND country_code = ?"
        selected_params.append(country_code)
    detail_where = selected_where
    detail_params = list(selected_params)
    if selected_month != "all":
        detail_where += " AND substr(ship_date, 1, 7) = ?"
        detail_params.append(selected_month)
    monthly_rows = db.execute(
        f"""
        SELECT substr(ship_date, 1, 7) AS month, COUNT(DISTINCT issue_no) AS shipment_count,
          COUNT(*) AS line_count, SUM(krw_supply) AS krw_supply, SUM(krw_total) AS krw_total
        FROM shipments WHERE {selected_where}
        GROUP BY substr(ship_date, 1, 7) ORDER BY month
        """,
        selected_params,
    ).fetchall()
    currency_rows = db.execute(
        f"""
        SELECT substr(ship_date, 1, 7) AS month, currency, SUM(foreign_amount) AS amount
        FROM shipments WHERE {selected_where}
        GROUP BY substr(ship_date, 1, 7), currency ORDER BY month, currency
        """,
        selected_params,
    ).fetchall()
    partner_rows = db.execute(
        f"""
        SELECT partner_name, SUM(krw_supply) AS krw_supply, COUNT(DISTINCT issue_no) AS shipment_count
        FROM shipments WHERE {detail_where}
        GROUP BY partner_name ORDER BY krw_supply DESC LIMIT 20
        """,
        detail_params,
    ).fetchall()
    item_rows = db.execute(
        f"""
        SELECT COALESCE(NULLIF(product_code, ''), '미지정') AS product_code,
          COALESCE(NULLIF(product_name, ''), '품목명 미지정') AS product_name,
          COALESCE(specification, '') AS specification,
          business_unit, SUM(quantity) AS quantity,
          COUNT(DISTINCT issue_no) AS shipment_count,
          SUM(krw_supply) AS krw_supply, SUM(krw_total) AS krw_total
        FROM shipments WHERE {detail_where}
        GROUP BY product_code, product_name, specification, business_unit
        ORDER BY krw_supply DESC, product_name LIMIT 200
        """,
        detail_params,
    ).fetchall()
    shipment_rows = db.execute(
        f"""
        SELECT issue_no, MAX(ship_date) AS ship_date,
          COALESCE(NULLIF(partner_name, ''), '거래처 미지정') AS partner_name,
          COALESCE(NULLIF(trade_type, ''), '미지정') AS trade_type,
          COUNT(*) AS line_count, SUM(quantity) AS quantity,
          SUM(krw_supply) AS krw_supply
        FROM shipments WHERE {detail_where}
        GROUP BY issue_no, partner_name, trade_type
        ORDER BY ship_date DESC, issue_no DESC LIMIT 100
        """,
        detail_params,
    ).fetchall()
    map_country_clause = " AND country_code = ?" if country_info else ""
    map_country_params = [*date_params, country_code] if country_info else list(date_params)
    segment_rows = db.execute(
        f"""
        SELECT business_unit, SUM(krw_supply) AS krw_supply, SUM(krw_total) AS krw_total,
          COUNT(DISTINCT issue_no) AS shipment_count, COUNT(*) AS line_count
        FROM shipments
        WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?{map_country_clause}
        GROUP BY business_unit ORDER BY krw_supply DESC
        """,
        map_country_params,
    ).fetchall()
    monthly_segment_rows = db.execute(
        f"""
        SELECT substr(ship_date, 1, 7) AS month, business_unit, SUM(krw_supply) AS krw_supply
        FROM shipments
        WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?{map_country_clause}
        GROUP BY substr(ship_date, 1, 7), business_unit
        ORDER BY month, business_unit
        """,
        map_country_params,
    ).fetchall()
    trade_type_rows = db.execute(
        f"""
        SELECT COALESCE(NULLIF(trade_type, ''), '미지정') AS trade_type,
          COUNT(DISTINCT issue_no) AS shipment_count, SUM(krw_supply) AS krw_supply
        FROM shipments
        WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?{map_country_clause}
        GROUP BY COALESCE(NULLIF(trade_type, ''), '미지정')
        ORDER BY krw_supply DESC
        """,
        map_country_params,
    ).fetchall()
    quality_rows = db.execute(
        f"""
        SELECT COALESCE(NULLIF(actual_review_status, ''), 'unclassified') AS review_status,
          COUNT(*) AS line_count,COUNT(DISTINCT issue_no) AS shipment_count,
          COALESCE(SUM(krw_supply),0) AS stored_krw_supply,
          COALESCE(SUM(krw_total),0) AS stored_krw_total_candidate
        FROM shipments WHERE {detail_where}
        GROUP BY COALESCE(NULLIF(actual_review_status, ''), 'unclassified')
        ORDER BY line_count DESC
        """,
        detail_params,
    ).fetchall()
    official_actual_row = db.execute(
        f"""
        SELECT
          SUM(CASE WHEN source_system='AMARANTH'
                        AND actual_review_status IN ('paid_verified_total','sample_zero')
                   THEN 1 ELSE 0 END) AS covered_line_count,
          COUNT(DISTINCT CASE WHEN source_system='AMARANTH'
                                   AND actual_review_status IN ('paid_verified_total','sample_zero')
                              THEN issue_no END) AS covered_shipment_count,
          COALESCE(SUM(CASE
            WHEN source_system='AMARANTH' AND actual_review_status='paid_verified_total'
              THEN krw_total
            WHEN source_system='AMARANTH' AND actual_review_status='sample_zero'
              THEN 0
            ELSE 0 END),0) AS recognized_sales_krw,
          COALESCE(SUM(CASE WHEN source_system='AMARANTH' AND actual_review_status='sample_zero'
                            THEN krw_total ELSE 0 END),0) AS excluded_sample_raw_krw,
          COALESCE(SUM(CASE WHEN source_system='AMARANTH'
                                  AND actual_review_status NOT IN ('paid_verified_total','sample_zero')
                            THEN krw_total ELSE 0 END),0) AS pending_amaranth_raw_krw
        FROM shipments WHERE {detail_where}
        """,
        detail_params,
    ).fetchone()
    monthly = {
        f"{year}-{month:02d}": {
            "month": f"{year}-{month:02d}",
            "shipment_count": 0,
            "line_count": 0,
            "krw_supply": 0,
            "krw_total": 0,
            "currencies": {},
            "segments": {unit: 0 for unit in BUSINESS_UNIT_LABELS},
        }
        for month in range(1, 13)
    }
    for row in monthly_rows:
        monthly[row["month"]].update(row_dict(row))
    for row in currency_rows:
        monthly[row["month"]]["currencies"][row["currency"] or "KRW"] = row["amount"] or 0
    for row in monthly_segment_rows:
        unit = row["business_unit"] if row["business_unit"] in BUSINESS_UNIT_LABELS else "unclassified"
        monthly[row["month"]]["segments"][unit] += row["krw_supply"] or 0

    segment_data = {
        unit: {
            "key": unit,
            "label": label,
            "krw_supply": 0,
            "krw_total": 0,
            "shipment_count": 0,
            "line_count": 0,
        }
        for unit, label in BUSINESS_UNIT_LABELS.items()
    }
    for row in segment_rows:
        unit = row["business_unit"] if row["business_unit"] in segment_data else "unclassified"
        for key in ("krw_supply", "krw_total", "shipment_count", "line_count"):
            segment_data[unit][key] += row[key] or 0
    overseas_total = sum(item["krw_supply"] for item in segment_data.values())
    for item in segment_data.values():
        item["share"] = round((item["krw_supply"] / overseas_total * 100), 1) if overseas_total else 0
    ordered_segments = [segment_data[unit] for unit in ("dental", "medical", "aesthetic", "unclassified")]
    quality = [row_dict(row) for row in quality_rows]
    review_pending_statuses = {
        "paid_mapping_pending", "review_pending_free", "review_pending_blank",
        "review_pending_management", "review_pending_jpy_rate", "legacy_policy", "unclassified",
    }
    pending_values = sorted(review_pending_statuses)
    pending_placeholders = ",".join("?" for _ in pending_values)
    pending_row = db.execute(
        f"""SELECT COUNT(*) AS line_count,COUNT(DISTINCT issue_no) AS shipment_count,
                   COALESCE(SUM(krw_supply),0) AS stored_krw_supply,
                   COALESCE(SUM(krw_total),0) AS stored_krw_total_candidate
            FROM shipments WHERE {detail_where}
              AND COALESCE(NULLIF(actual_review_status,''),'unclassified') IN ({pending_placeholders})""",
        (*detail_params, *pending_values),
    ).fetchone()
    review_pending = row_dict(pending_row)
    return jsonify(
        year=year,
        segment_filter=segment,
        selected_month=selected_month,
        segment_label="전체 해외" if segment == "all" else BUSINESS_UNIT_LABELS[segment],
        country_filter=country_info,
        overseas_total=overseas_total,
        monthly=list(monthly.values()),
        partners=[row_dict(row) for row in partner_rows],
        items=[row_dict(row) for row in item_rows],
        shipments=[row_dict(row) for row in shipment_rows],
        segments=ordered_segments,
        trade_types=[row_dict(row) for row in trade_type_rows],
        erp_freshness=erp_freshness_payload(db),
        actual_quality={
            "rows": quality,
            "review_pending": review_pending,
            "official_actual": row_dict(official_actual_row),
            "rules": {
                "sample_zero": "견본은 ERP 원문금액을 보존하고 공식 인식매출은 0원",
                "review_pending_free": "무상은 업무 검토대기",
                "review_pending_blank": "관리구분 공란은 업무 검토대기",
                "review_pending_jpy_rate": "JPY 1엔 기준을 벗어난 기존 API 행은 공식 Actual에서 제외하고 재동기화 대기",
                "paid_verified_total": "유상은 검증된 ERP 합계액(isuhAm)을 공식 인식매출로 사용",
                "legacy_policy": "Legacy 원문별 기존 저장 정책 유지",
            },
            "official_actual_mapping": "verified_excel_api_same_row",
            "mapping_evidence": ERP_ACTUAL_MAPPING_EVIDENCE,
        },
        amount_basis={
            "displayed_krw": "기존 화면 호환을 위해 저장 공급가를 유지하며, 공식 인식매출은 actual_quality에 별도 제공",
            "official_actual_krw": "검증된 Amaranth 유상 A10 합계액(isuhAm); 견본 B06은 원문 보존·인식 0; 비정상 JPY 환율은 제외",
            "transaction_amount": "환종별 거래통화금액이며 서로 다른 환종을 합산하지 않음",
        },
        filter_definition={
            "included":"해외수주 및 T/T·L/C·D/P·D/A·CAD·구매승인서",
            "excluded":"DOMESTIC·국내·LOCAL·LOCAL L/C",
        },
    )


def account_alias_values(account_row):
    """Return the explicit account-to-ERP names used for deterministic linkage."""
    if not account_row:
        return []
    payload = parse_payload(account_row["payload_json"])
    values = [account_row["title"], payload.get("erp_partner_name")]
    aliases = payload.get("erp_partner_aliases")
    if isinstance(aliases, list):
        values.extend(aliases)
    elif isinstance(aliases, str):
        values.extend(part.strip() for part in aliases.split(","))
    return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))


def account_link_key(value):
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized_text(value))


def find_account_for_partner(db, partner_name):
    partner_key = account_link_key(partner_name)
    if not partner_key:
        return None
    rows = db.execute(
        """
        SELECT r.*, u.display_name AS owner_name, c.display_name AS creator_name
        FROM records r
        LEFT JOIN users u ON u.id = r.owner_id
        LEFT JOIN users c ON c.id = r.created_by
        WHERE r.entity_type = 'account' AND r.deleted_at IS NULL
        ORDER BY r.updated_at DESC
        """
    ).fetchall()
    for row in rows:
        if partner_key in {account_link_key(value) for value in account_alias_values(row)}:
            return row
    return None


def account_sales_summary_rows(db):
    """Build one deduplicated sales summary row per account master record."""
    accounts = db.execute(
        """
        SELECT r.*, u.display_name AS owner_name
        FROM records r LEFT JOIN users u ON u.id = r.owner_id
        WHERE r.entity_type = 'account' AND r.deleted_at IS NULL
        ORDER BY r.title COLLATE NOCASE
        """
    ).fetchall()
    shipment_rows = db.execute(
        """
        SELECT COALESCE(partner_name, '') AS partner_name,
          COALESCE(partner_code, '') AS partner_code,
          substr(ship_date, 1, 4) AS sales_year,
          COALESCE(SUM(krw_supply), 0) AS krw_supply,
          COUNT(DISTINCT issue_no) AS shipment_count,
          MIN(ship_date) AS first_ship_date,
          MAX(ship_date) AS last_ship_date
        FROM shipments WHERE is_overseas = 1
        GROUP BY partner_name, partner_code, substr(ship_date, 1, 4)
        """
    ).fetchall()
    current_year = datetime.now(timezone.utc).year
    five_years = {str(year) for year in range(current_year - 4, current_year + 1)}
    summaries = []
    for account in accounts:
        payload = parse_payload(account["payload_json"])
        alias_keys = {account_link_key(value) for value in account_alias_values(account) if account_link_key(value)}
        partner_code = account_link_key(payload.get("erp_partner_code"))
        matched = [
            row for row in shipment_rows
            if account_link_key(row["partner_name"]) in alias_keys
            or bool(partner_code and account_link_key(row["partner_code"]) == partner_code)
        ]
        yearly = {}
        for row in matched:
            year = str(row["sales_year"] or "")
            yearly[year] = yearly.get(year, 0.0) + float(row["krw_supply"] or 0)
        all_years = sorted(year for year, amount in yearly.items() if year and amount)
        five_year_total = sum(yearly.get(year, 0.0) for year in five_years)
        first_date = min((row["first_ship_date"] for row in matched if row["first_ship_date"]), default=None)
        last_date = max((row["last_ship_date"] for row in matched if row["last_ship_date"]), default=None)
        first_transaction_date = payload.get("first_transaction_date") or first_date
        first_transaction_year = str(first_transaction_date or "")[:4] or (all_years[0] if all_years else "")
        summaries.append({
            "id": account["id"],
            "title": account["title"],
            "owner_name": account["owner_name"] or payload.get("source_owner_name") or "담당자 미지정",
            "region": standard_region(account["region"], account["country"]),
            "source_region": account["region"] or "",
            "country": account["country"] or "미지정",
            "status": account["status"],
            "average_annual_sales_5y": round(five_year_total / 5, 2),
            "five_year_sales": round(five_year_total, 2),
            "first_transaction_year": first_transaction_year,
            "first_transaction_date": first_transaction_date,
            "last_transaction_date": last_date,
            "shipment_count": sum(int(row["shipment_count"] or 0) for row in matched),
            "matched_partner_count": len({row["partner_name"] for row in matched if row["partner_name"]}),
        })
    return summaries


def top_partner_sales_rows(db, year_range, limit=20):
    """Consolidate ERP aliases into one ranked row per account master."""
    accounts = db.execute(
        """
        SELECT * FROM records
        WHERE entity_type = 'account' AND deleted_at IS NULL
        ORDER BY updated_at DESC
        """
    ).fetchall()
    alias_index = {}
    code_index = {}
    for account in accounts:
        payload = parse_payload(account["payload_json"])
        for alias in account_alias_values(account):
            key = account_link_key(alias)
            if key and key not in alias_index:
                alias_index[key] = account
        code = account_link_key(payload.get("erp_partner_code"))
        if code and code not in code_index:
            code_index[code] = account

    shipment_rows = db.execute(
        """
        SELECT COALESCE(NULLIF(partner_name, ''), '거래처 미지정') AS partner_name,
          COALESCE(partner_code, '') AS partner_code,
          COALESCE(SUM(krw_supply), 0) AS amount,
          COUNT(DISTINCT issue_no) AS shipment_count
        FROM shipments
        WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?
        GROUP BY partner_name, partner_code
        """,
        year_range,
    ).fetchall()
    grouped = {}
    for row in shipment_rows:
        account = code_index.get(account_link_key(row["partner_code"])) or alias_index.get(
            account_link_key(row["partner_name"])
        )
        account_id = account["id"] if account else None
        label = account["title"] if account else row["partner_name"]
        group_key = f"account:{account_id}" if account_id else f"erp:{account_link_key(label)}"
        item = grouped.setdefault(group_key, {
            "account_id": account_id,
            "partner_name": label,
            "amount": 0.0,
            "shipment_count": 0,
            "erp_partner_names": [],
        })
        item["amount"] += float(row["amount"] or 0)
        item["shipment_count"] += int(row["shipment_count"] or 0)
        if row["partner_name"] not in item["erp_partner_names"]:
            item["erp_partner_names"].append(row["partner_name"])
    ranked = sorted(grouped.values(), key=lambda item: (-item["amount"], item["partner_name"]))
    for item in ranked:
        item["amount"] = round(item["amount"], 2)
    return ranked[:limit]


@app.get("/api/accounts/summary")
def account_summaries():
    return jsonify(
        accounts=account_sales_summary_rows(get_db()),
        average_definition="최근 5개년(현재연도 포함) ERP 해외 공급가 합계 ÷ 5",
        region_definition="중동·동유럽·서유럽·아프리카·북미·남미·오세아니아·아시아 8개 권역",
    )


def shipment_source_detail(row):
    raw = parse_payload(row["raw_json"])
    historical = raw.get("historical_krw_source") if isinstance(raw.get("historical_krw_source"), dict) else None
    line = raw.get("line") if isinstance(raw.get("line"), dict) else {}
    lot_no = next(
        (
            value for value in (
                raw.get("lot_no"), line.get("lotNb"), line.get("lotNo"), line.get("lot_no")
            ) if str(value or "").strip()
        ),
        "",
    )
    if historical:
        return {
            "label": "ERP 엑셀 · 실제 원화",
            "name": historical.get("source_name") or "2024·2025 ERP 출고이력",
            "source_row": historical.get("source_row"),
            "amount_basis": historical.get("amount_basis") or "ERP 실제 원화 공급가",
            "lot_no": lot_no,
        }
    if raw.get("source"):
        return {
            "label": "기존 ERP 엑셀",
            "name": raw.get("source"),
            "source_row": raw.get("source_row"),
            "amount_basis": "원본 외화금액 기반 환산",
            "lot_no": lot_no,
        }
    return {
        "label": "Amaranth ERP API",
        "name": "Amaranth ERP",
        "source_row": None,
        "amount_basis": "ERP 합계액(isuhAm) 원문 · 관리구분별 공식 인식 규칙 적용",
        "lot_no": lot_no,
    }


def account_history_rows(db, account_row, account_aliases):
    if not account_row:
        return [], 0
    alias_keys = {account_link_key(value) for value in account_aliases if account_link_key(value)}
    record_ids = {str(account_row["id"])}
    linked_count = 0
    for row in db.execute("SELECT id, title, payload_json FROM records").fetchall():
        if row["id"] == account_row["id"]:
            continue
        payload = parse_payload(row["payload_json"])
        linked_by_id = str(payload.get("account_id") or "") == str(account_row["id"])
        linked_by_name = account_link_key(payload.get("account_name")) in alias_keys
        if linked_by_id or linked_by_name:
            record_ids.add(str(row["id"]))
            linked_count += 1
    placeholders = ",".join("?" for _ in record_ids)
    rows = db.execute(
        f"""
        SELECT * FROM audit_logs
        WHERE entity_id IN ({placeholders})
        ORDER BY id DESC LIMIT 120
        """,
        tuple(record_ids),
    ).fetchall()
    user = current_user_row()
    history = []
    for row in rows:
        item = row_dict(row)
        before_json = item.pop("before_json", None)
        after_json = item.pop("after_json", None)
        if user:
            item["before"] = parse_payload(before_json)
            item["after"] = parse_payload(after_json)
        else:
            item["actor_user_id"] = None
            item["actor_username"] = "담당자"
            item["before"] = {}
            item["after"] = {}
            item.pop("ip_address", None)
            item.pop("user_agent", None)
        history.append(item)
    return history, linked_count


def build_account_sales_detail(db, account_row=None, requested_partner=""):
    aliases = account_alias_values(account_row)
    if requested_partner:
        aliases.append(str(requested_partner).strip())
    aliases = list(dict.fromkeys(value for value in aliases if value))
    alias_keys = {account_link_key(value) for value in aliases if account_link_key(value)}
    payload = parse_payload(account_row["payload_json"]) if account_row else {}
    partner_code = account_link_key(payload.get("erp_partner_code"))

    matched_partner_names = []
    for row in db.execute(
        """
        SELECT DISTINCT COALESCE(partner_name, '') AS partner_name,
          COALESCE(partner_code, '') AS partner_code
        FROM shipments WHERE is_overseas = 1
        ORDER BY partner_name
        """
    ).fetchall():
        name_match = account_link_key(row["partner_name"]) in alias_keys
        code_match = bool(partner_code and account_link_key(row["partner_code"]) == partner_code)
        if name_match or code_match:
            matched_partner_names.append(row["partner_name"])
    matched_partner_names = list(dict.fromkeys(name for name in matched_partner_names if name))

    account = public_record(account_row) if account_row else None
    if account and not current_user_row():
        for key in ("owner_id", "created_by", "updated_by", "deleted_by", "creator_name"):
            account.pop(key, None)

    empty_summary = {
        "krw_supply": 0.0,
        "krw_total": 0.0,
        "shipment_count": 0,
        "line_count": 0,
        "first_ship_date": None,
        "last_ship_date": None,
    }
    if not matched_partner_names:
        history, linked_count = account_history_rows(db, account_row, aliases)
        return {
            "account": account,
            "requested_partner": requested_partner or None,
            "matched_partner_names": [],
            "summary": empty_summary,
            "yearly": [],
            "annual_five_years": [
                {"year": str(year), "krw_supply": 0.0}
                for year in range(datetime.now(timezone.utc).year - 4, datetime.now(timezone.utc).year + 1)
            ],
            "monthly": [],
            "items": [],
            "items_by_year": [],
            "shipments": [],
            "history": history,
            "linked_record_count": linked_count,
            "link_status": "account_without_erp_match" if account else "unmatched_erp_partner",
            "source_notes": [
                "2024·2025: 업로드 ERP 엑셀의 실제 원화 공급가",
                "2026 Amaranth: 합계액(isuhAm) Mapping 검증 완료 · 유상은 공식 인식, 견본은 0원",
            ],
        }

    partner_placeholders = ",".join("?" for _ in matched_partner_names)
    shipment_where = f"is_overseas = 1 AND partner_name IN ({partner_placeholders})"
    summary_row = db.execute(
        f"""
        SELECT COALESCE(SUM(krw_supply), 0) AS krw_supply,
          COALESCE(SUM(krw_total), 0) AS krw_total,
          COUNT(DISTINCT issue_no) AS shipment_count, COUNT(*) AS line_count,
          MIN(ship_date) AS first_ship_date, MAX(ship_date) AS last_ship_date
        FROM shipments WHERE {shipment_where}
        """,
        matched_partner_names,
    ).fetchone()
    yearly_rows = db.execute(
        f"""
        SELECT substr(ship_date, 1, 4) AS year,
          COUNT(DISTINCT issue_no) AS shipment_count, COUNT(*) AS line_count,
          COALESCE(SUM(quantity), 0) AS quantity,
          COALESCE(SUM(krw_supply), 0) AS krw_supply,
          COALESCE(SUM(krw_total), 0) AS krw_total
        FROM shipments WHERE {shipment_where}
        GROUP BY substr(ship_date, 1, 4) ORDER BY year DESC
        """,
        matched_partner_names,
    ).fetchall()
    three_year_start = str(datetime.now(timezone.utc).year - 2)
    item_yearly_rows = db.execute(
        f"""
        SELECT substr(ship_date, 1, 4) AS year,
          COALESCE(NULLIF(product_code, ''), '미지정') AS product_code,
          COALESCE(NULLIF(product_name, ''), '품목명 미지정') AS product_name,
          COALESCE(specification, '') AS specification,
          COALESCE(NULLIF(business_unit, ''), 'unclassified') AS business_unit,
          COALESCE(SUM(quantity), 0) AS quantity,
          COUNT(DISTINCT issue_no) AS shipment_count,
          COALESCE(SUM(krw_supply), 0) AS krw_supply
        FROM shipments
        WHERE {shipment_where} AND substr(ship_date, 1, 4) >= ?
        GROUP BY substr(ship_date, 1, 4), product_code, product_name, specification, business_unit
        ORDER BY year DESC, krw_supply DESC, product_name
        LIMIT 240
        """,
        (*matched_partner_names, three_year_start),
    ).fetchall()
    monthly_rows = db.execute(
        f"""
        SELECT substr(ship_date, 1, 7) AS month,
          COUNT(DISTINCT issue_no) AS shipment_count, COUNT(*) AS line_count,
          COALESCE(SUM(quantity), 0) AS quantity,
          COALESCE(SUM(krw_supply), 0) AS krw_supply
        FROM shipments
        WHERE {shipment_where} AND substr(ship_date, 1, 4) >= ?
        GROUP BY substr(ship_date, 1, 7) ORDER BY month DESC
        """,
        (*matched_partner_names, three_year_start),
    ).fetchall()
    item_rows = db.execute(
        f"""
        SELECT COALESCE(NULLIF(product_code, ''), '미지정') AS product_code,
          COALESCE(NULLIF(product_name, ''), '품목명 미지정') AS product_name,
          COALESCE(specification, '') AS specification,
          COALESCE(NULLIF(business_unit, ''), 'unclassified') AS business_unit,
          COALESCE(SUM(quantity), 0) AS quantity,
          COUNT(DISTINCT issue_no) AS shipment_count,
          COALESCE(SUM(krw_supply), 0) AS krw_supply
        FROM shipments WHERE {shipment_where}
        GROUP BY product_code, product_name, specification, business_unit
        ORDER BY krw_supply DESC, product_name LIMIT 60
        """,
        matched_partner_names,
    ).fetchall()
    header_rows = db.execute(
        f"""
        SELECT issue_no, MAX(ship_date) AS ship_date,
          COALESCE(NULLIF(partner_name, ''), '거래처 미지정') AS partner_name,
          COALESCE(NULLIF(trade_type, ''), '미지정') AS trade_type,
          COUNT(*) AS line_count, COALESCE(SUM(quantity), 0) AS quantity,
          COALESCE(SUM(krw_supply), 0) AS krw_supply,
          COALESCE(SUM(krw_total), 0) AS krw_total
        FROM shipments WHERE {shipment_where}
        GROUP BY issue_no, partner_name, trade_type
        ORDER BY ship_date DESC, issue_no DESC LIMIT 120
        """,
        matched_partner_names,
    ).fetchall()

    issue_nos = list(dict.fromkeys(row["issue_no"] for row in header_rows))
    lines_by_header = {}
    if issue_nos:
        issue_placeholders = ",".join("?" for _ in issue_nos)
        line_rows = db.execute(
            f"""
            SELECT * FROM shipments
            WHERE is_overseas = 1
              AND partner_name IN ({partner_placeholders})
              AND issue_no IN ({issue_placeholders})
            ORDER BY ship_date DESC, issue_no DESC, issue_seq
            """,
            (*matched_partner_names, *issue_nos),
        ).fetchall()
        for row in line_rows:
            source = shipment_source_detail(row)
            item = {
                "issue_seq": row["issue_seq"],
                "business_unit": row["business_unit"] or "unclassified",
                "product_code": row["product_code"] or "",
                "product_name": row["product_name"] or "",
                "specification": row["specification"] or "",
                "quantity": row["quantity"] or 0,
                "currency": row["currency"] or "KRW",
                "exchange_rate": row["exchange_rate"] or 0,
                "foreign_amount": row["foreign_amount"] or 0,
                "krw_supply": row["krw_supply"] or 0,
                "krw_total": row["krw_total"] or 0,
                "erp_raw_total_krw": row["krw_total"] or 0,
                "recognized_sales_krw": recognized_sales_krw(row),
                "actual_review_status": row["actual_review_status"] or "unclassified",
                "lot_no": source.pop("lot_no", ""),
                "source": source,
            }
            lines_by_header.setdefault((row["issue_no"], row["partner_name"]), []).append(item)

    shipments = []
    for row in header_rows:
        item = row_dict(row)
        lines = lines_by_header.get((row["issue_no"], row["partner_name"]), [])
        item["lines"] = lines
        item["business_units"] = list(dict.fromkeys(line["business_unit"] for line in lines))
        item["currencies"] = list(dict.fromkeys(line["currency"] for line in lines))
        item["source_labels"] = list(dict.fromkeys(line["source"]["label"] for line in lines))
        shipments.append(item)

    history, linked_count = account_history_rows(db, account_row, aliases)
    summary = row_dict(summary_row) or dict(empty_summary)
    current_year = datetime.now(timezone.utc).year
    annual_map = {str(row["year"]): float(row["krw_supply"] or 0) for row in yearly_rows}
    annual_five_years = [
        {"year": str(year), "krw_supply": round(annual_map.get(str(year), 0.0), 2)}
        for year in range(current_year - 4, current_year + 1)
    ]
    summary["average_annual_sales_5y"] = round(sum(row["krw_supply"] for row in annual_five_years) / 5, 2)
    summary["first_transaction_year"] = str(summary.get("first_ship_date") or payload.get("first_transaction_date") or "")[:4]
    return {
        "account": account,
        "requested_partner": requested_partner or None,
        "matched_partner_names": matched_partner_names,
        "summary": summary,
        "yearly": [row_dict(row) for row in yearly_rows],
        "annual_five_years": annual_five_years,
        "monthly": [row_dict(row) for row in monthly_rows],
        "items": [row_dict(row) for row in item_rows],
        "items_by_year": [row_dict(row) for row in item_yearly_rows],
        "shipments": shipments,
        "history": history,
        "linked_record_count": linked_count,
        "link_status": "linked" if account else "unmatched_erp_partner",
        "source_notes": [
            "2024·2025: 업로드 ERP 엑셀의 실제 원화 공급가",
            "2026 Amaranth: 합계액(isuhAm) Mapping 검증 완료 · 유상은 공식 인식, 견본은 0원",
            "2020~2023: 기존 ERP 출고이력 외화금액의 기준환율 환산값",
        ],
    }


@app.get("/api/accounts/<account_id>/detail")
def account_sales_detail(account_id):
    db = get_db()
    account = db.execute(
        """
        SELECT r.*, u.display_name AS owner_name, c.display_name AS creator_name
        FROM records r
        LEFT JOIN users u ON u.id = r.owner_id
        LEFT JOIN users c ON c.id = r.created_by
        WHERE r.id = ? AND r.entity_type = 'account' AND r.deleted_at IS NULL
        """,
        (account_id,),
    ).fetchone()
    if not account:
        return jsonify(error="거래처를 찾을 수 없습니다."), 404
    return jsonify(**build_account_sales_detail(db, account_row=account))


@app.get("/api/partners/detail")
def partner_sales_detail():
    partner_name = str(request.args.get("name") or "").strip()
    if not partner_name or len(partner_name) > 200:
        return jsonify(error="조회할 ERP 거래처명을 확인해 주세요."), 400
    db = get_db()
    account = find_account_for_partner(db, partner_name)
    detail = build_account_sales_detail(db, account_row=account, requested_partner=partner_name)
    if not detail["matched_partner_names"]:
        return jsonify(error="해외 출고 이력이 있는 거래처를 찾을 수 없습니다."), 404
    return jsonify(**detail)


def country_info_by_id(map_id):
    map_id = str(map_id or "").zfill(3)
    return next((dict(item) for item in world_country_index().values() if item["map_id"] == map_id), None)


def record_map_country(row, account_by_id, account_by_name):
    country = resolve_country(row["country"])
    if country:
        return country, row["region"] or ""
    payload = parse_payload(row["payload_json"])
    account = account_by_id.get(str(payload.get("account_id") or ""))
    if not account:
        account = account_by_name.get(normalized_text(payload.get("account_name")))
    if account:
        return resolve_country(account["country"]), account["region"] or row["region"] or ""
    return None, row["region"] or ""


def map_action_date(row, payload):
    return next(
        (
            value
            for value in (
                payload.get("next_action_date"), payload.get("next_target_date"),
                payload.get("revised_target_date"), payload.get("mid_review_date"),
                row["due_date"], str(payload.get("activity_at") or "")[:10],
            )
            if value
        ),
        "",
    )


def map_country_bucket(country, region=""):
    return {
        "map_id": country["map_id"],
        "name": country["name"],
        "label": country["label"],
        "region": region or "권역 미지정",
        "account_count": 0,
        "pipeline_count": 0,
        "open_actions": 0,
        "overdue_actions": 0,
        "forecast_count": 0,
        "forecast_total_krw": 0.0,
        "forecast_weighted_krw": 0.0,
        "erp_actual_krw": 0.0,
        "shipment_count": 0,
        "stage_counts": {stage: 0 for stage in ("sales_activity", "pi_received", "payment_received")},
        "accounts": [],
        "account_ids": [],
        "record_ids": [],
        "actions": [],
        "forecast_items": [],
        "erp_partners": {},
        "_shipment_ids": set(),
    }


@app.get("/api/map")
def global_map():
    month = str(request.args.get("month") or operational_forecast_month()).strip()
    if not valid_forecast_month(month):
        return jsonify(error="지도 기준월 형식이 올바르지 않습니다."), 400
    segment = str(request.args.get("segment") or "all").strip().lower()
    if segment not in OVERSEAS_BUSINESS_UNITS | {"all"}:
        return jsonify(error="지도 사업분야 필터가 올바르지 않습니다."), 400

    db = get_db()
    record_rows = db.execute(
        """
        SELECT r.*, u.display_name AS owner_name
        FROM records r LEFT JOIN users u ON u.id = r.owner_id
        WHERE r.deleted_at IS NULL
        ORDER BY COALESCE(r.due_date, '9999-12-31'), r.updated_at DESC
        """
    ).fetchall()
    accounts = [row for row in record_rows if row["entity_type"] == "account"]
    account_by_id = {str(row["id"]): row for row in accounts}
    account_by_name = {normalized_text(row["title"]): row for row in accounts}
    countries = {}
    unmatched = {
        "record_count": 0,
        "forecast_count": 0,
        "forecast_total_krw": 0.0,
        "shipment_count": 0,
        "erp_actual_krw": 0.0,
    }
    closed_statuses = {"done", "completed", "cancelled", "closed", "lost", "shipped", "achieved"}
    today = datetime.now(timezone.utc).date().isoformat()

    for row in record_rows:
        payload = parse_payload(row["payload_json"])
        unit = str(payload.get("business_unit") or "unclassified")
        if segment != "all" and unit != segment:
            continue
        country, inherited_region = record_map_country(row, account_by_id, account_by_name)
        if not country:
            if row["entity_type"] in {"account", "pipeline", "activity", "order", "goal"}:
                unmatched["record_count"] += 1
            continue
        bucket = countries.setdefault(country["map_id"], map_country_bucket(country, inherited_region))
        bucket["record_ids"].append(row["id"])
        if bucket["region"] == "권역 미지정" and inherited_region:
            bucket["region"] = inherited_region
        if row["entity_type"] == "account":
            bucket["account_count"] += 1
            bucket["account_ids"].append(row["id"])
            bucket["accounts"].append({
                "id": row["id"], "title": row["title"], "status": row["status"],
                "owner_name": row["owner_name"] or "담당자 미지정", "business_unit": unit,
            })
        if row["entity_type"] == "pipeline" and row["status"] not in {"won", "lost"}:
            bucket["pipeline_count"] += 1
        if row["entity_type"] in {"pipeline", "activity", "order", "goal", "agenda", "promotion"} and row["status"] not in closed_statuses:
            due_date = map_action_date(row, payload)
            bucket["open_actions"] += 1
            if due_date and due_date < today:
                bucket["overdue_actions"] += 1
            bucket["actions"].append({
                "id": row["id"], "entity_type": row["entity_type"], "title": row["title"],
                "status": row["status"], "due_date": due_date,
                "owner_name": row["owner_name"] or "담당자 미지정",
            })

    if refresh_major_task_rags(db):
        db.commit()
    major_task_rows = db.execute(
        """SELECT t.*,u.display_name AS owner_name,c.headquarters_country AS customer_country
           FROM major_tasks t
           LEFT JOIN users u ON u.id=t.owner_id
           LEFT JOIN customer_master c ON c.id=t.customer_master_id
           WHERE t.status NOT IN ('completed','cancelled') AND t.archived_at IS NULL"""
    ).fetchall()
    for row in major_task_rows:
        unit = row["primary_business_unit"]
        if segment != "all" and unit != segment:
            continue
        country = resolve_country(row["country"] or row["customer_country"])
        if not country:
            unmatched["record_count"] += 1
            continue
        bucket = countries.setdefault(country["map_id"], map_country_bucket(country, row["region"]))
        due_date = row["hard_deadline_date"] if row["hard_deadline_enabled"] and row["hard_deadline_date"] else row["current_target_date"]
        bucket["open_actions"] += 1
        if due_date and due_date < today:
            bucket["overdue_actions"] += 1
        bucket["actions"].append({
            "id": row["id"], "entity_type": "major_task", "title": row["title"],
            "status": row["status"], "due_date": due_date,
            "owner_name": row["owner_name"] or "담당자 미지정", "rag": row["final_rag"],
        })

    cycle = db.execute(
        "SELECT * FROM forecast_cycles WHERE forecast_month = ? ORDER BY round_no DESC LIMIT 1",
        (month,),
    ).fetchone()
    if cycle:
        forecast_rows = db.execute(
            """
            SELECT f.*, u.display_name AS owner_name,
              a.country AS account_country, a.region AS account_region
            FROM forecast_items f
            LEFT JOIN users u ON u.id = f.owner_id
            LEFT JOIN records a ON a.id = f.account_id AND a.entity_type = 'account' AND a.deleted_at IS NULL
            WHERE f.cycle_id = ? AND f.deleted_at IS NULL AND f.status = 'active'
            ORDER BY f.updated_at DESC
            """,
            (cycle["id"],),
        ).fetchall()
        cycle_data = row_dict(cycle)
        for row in forecast_rows:
            if segment != "all" and row["business_unit"] != segment:
                continue
            item = public_forecast_item(row, cycle_data)
            country = resolve_country(item.get("account_country"))
            account = account_by_id.get(str(item.get("account_id") or "")) or account_by_name.get(normalized_text(item.get("account_name")))
            if not country and account:
                country = resolve_country(account["country"])
            if not country:
                unmatched["forecast_count"] += 1
                unmatched["forecast_total_krw"] += item["krw_amount"]
                continue
            bucket = countries.setdefault(
                country["map_id"],
                map_country_bucket(country, item.get("account_region") or (account["region"] if account else "")),
            )
            if account and account["id"] not in bucket["account_ids"]:
                account_payload = parse_payload(account["payload_json"])
                bucket["account_ids"].append(account["id"])
                bucket["record_ids"].append(account["id"])
                bucket["account_count"] += 1
                bucket["accounts"].append({
                    "id": account["id"], "title": account["title"], "status": account["status"],
                    "owner_name": next((row["owner_name"] for row in record_rows if row["id"] == account["id"]), "담당자 미지정") or "담당자 미지정",
                    "business_unit": account_payload.get("business_unit") or item["business_unit"],
                })
            bucket["forecast_count"] += 1
            bucket["forecast_total_krw"] += item["krw_amount"]
            bucket["forecast_weighted_krw"] += item["weighted_krw"]
            if item["stage"] in bucket["stage_counts"]:
                bucket["stage_counts"][item["stage"]] += 1
            bucket["forecast_items"].append({
                "id": item["id"], "title": item["title"], "account_name": item["account_name"],
                "item_name": item["item_name"], "stage": item["stage"],
                "stage_label": item["stage_label"], "krw_amount": item["krw_amount"],
                "weighted_krw": item["weighted_krw"], "owner_name": item.get("owner_name") or "담당자 미지정",
            })
    else:
        forecast_rows = []

    shipment_where = "is_overseas = 1 AND substr(ship_date, 1, 7) = ?"
    shipment_params = [month]
    if segment != "all":
        shipment_where += " AND business_unit = ?"
        shipment_params.append(segment)
    shipment_rows = db.execute(
        f"""
        SELECT issue_no, MAX(country_code) AS country_code, MAX(country_name) AS country_name,
          COALESCE(NULLIF(partner_name, ''), '거래처 미지정') AS partner_name,
          SUM(krw_supply) AS krw_supply
        FROM shipments WHERE {shipment_where}
        GROUP BY issue_no, partner_name
        ORDER BY MAX(ship_date) DESC
        """,
        shipment_params,
    ).fetchall()
    for row in shipment_rows:
        linked_account = account_by_name.get(normalized_text(row["partner_name"]))
        country = country_info_by_id(row["country_code"]) if row["country_code"] else resolve_country(row["country_name"])
        if not country:
            country = resolve_country(linked_account["country"]) if linked_account else None
        amount = float(row["krw_supply"] or 0)
        if not country:
            unmatched["shipment_count"] += 1
            unmatched["erp_actual_krw"] += amount
            continue
        bucket = countries.setdefault(country["map_id"], map_country_bucket(country))
        if linked_account and linked_account["id"] not in bucket["account_ids"]:
            account_payload = parse_payload(linked_account["payload_json"])
            bucket["account_ids"].append(linked_account["id"])
            bucket["record_ids"].append(linked_account["id"])
            bucket["account_count"] += 1
            bucket["accounts"].append({
                "id": linked_account["id"], "title": linked_account["title"], "status": linked_account["status"],
                "owner_name": next((item["owner_name"] for item in record_rows if item["id"] == linked_account["id"]), "담당자 미지정") or "담당자 미지정",
                "business_unit": account_payload.get("business_unit") or segment,
            })
        bucket["_shipment_ids"].add(row["issue_no"])
        bucket["erp_actual_krw"] += amount
        bucket["erp_partners"][row["partner_name"]] = bucket["erp_partners"].get(row["partner_name"], 0) + amount

    country_rows = []
    for bucket in countries.values():
        bucket["shipment_count"] = len(bucket.pop("_shipment_ids"))
        bucket["account_ids"] = list(dict.fromkeys(bucket["account_ids"]))
        bucket["record_ids"] = list(dict.fromkeys(bucket["record_ids"]))
        bucket["accounts"] = sorted(bucket["accounts"], key=lambda item: item["title"].casefold())[:8]
        bucket["actions"] = sorted(
            bucket["actions"],
            key=lambda item: (item["due_date"] or "9999-12-31", item["title"].casefold()),
        )[:8]
        bucket["forecast_items"] = sorted(bucket["forecast_items"], key=lambda item: item["krw_amount"], reverse=True)[:8]
        bucket["erp_partners"] = [
            {"partner_name": name, "krw_supply": amount}
            for name, amount in sorted(bucket["erp_partners"].items(), key=lambda item: item[1], reverse=True)[:8]
        ]
        for key in ("forecast_total_krw", "forecast_weighted_krw", "erp_actual_krw"):
            bucket[key] = round(float(bucket[key]), 2)
        bucket["activity_score"] = (
            bucket["erp_actual_krw"] + bucket["forecast_total_krw"]
            + bucket["open_actions"] * 1000000 + bucket["account_count"] * 500000
        )
        country_rows.append(bucket)
    country_rows.sort(key=lambda item: item["activity_score"], reverse=True)
    for key in ("forecast_total_krw", "erp_actual_krw"):
        unmatched[key] = round(float(unmatched[key]), 2)

    last_sync = db.execute(
        "SELECT finished_at FROM erp_sync_runs WHERE status = 'success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    mapped_forecast = sum(item["forecast_total_krw"] for item in country_rows)
    mapped_actual = sum(item["erp_actual_krw"] for item in country_rows)
    return jsonify(
        month=month,
        segment=segment,
        segment_label="전체 사업분야" if segment == "all" else BUSINESS_UNIT_LABELS[segment],
        countries=country_rows,
        totals={
            "country_count": len(country_rows),
            "account_count": sum(item["account_count"] for item in country_rows),
            "open_actions": sum(item["open_actions"] for item in country_rows),
            "overdue_actions": sum(item["overdue_actions"] for item in country_rows),
            "forecast_total_krw": round(mapped_forecast + unmatched["forecast_total_krw"], 2),
            "forecast_mapped_krw": round(mapped_forecast, 2),
            "erp_actual_krw": round(mapped_actual + unmatched["erp_actual_krw"], 2),
            "erp_mapped_krw": round(mapped_actual, 2),
        },
        unmatched=unmatched,
        source={
            "forecast_round": int(cycle["round_no"]) if cycle else None,
            "forecast_as_of": cycle["as_of_date"] if cycle else None,
            "erp_last_sync": last_sync["finished_at"] if last_sync else None,
            "geography": "거래처 국가 → ERP 국가 필드 → ERP 거래처명 연결",
            "forecast_transition": forecast_source_transition(db, month, cycle, forecast_rows),
        },
    )


def share_payload(values, key_name="key", label_name="label"):
    total = sum(float(item.get("amount") or 0) for item in values)
    rows = []
    for item in values:
        amount = float(item.get("amount") or 0)
        rows.append({
            key_name: item.get(key_name),
            label_name: item.get(label_name),
            "amount": round(amount, 2),
            "share": round(amount / total * 100, 1) if total else 0,
        })
    return rows


def dashboard_target(db, target_type, target_key):
    try:
        row = db.execute(
            "SELECT * FROM dashboard_targets WHERE target_type = ? AND target_key = ?",
            (target_type, target_key),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        row = None
    return row_dict(row) if row else {
        "target_type": target_type,
        "target_key": target_key,
        "target_krw": 0,
        "updated_at": None,
    }


def dashboard_geography(db, year_range):
    accounts = db.execute(
        "SELECT * FROM records WHERE entity_type = 'account' AND deleted_at IS NULL"
    ).fetchall()
    account_by_partner = {}
    for account in accounts:
        for alias in account_alias_values(account):
            key = account_link_key(alias)
            if key and key not in account_by_partner:
                account_by_partner[key] = account
    shipment_rows = db.execute(
        """
        SELECT COALESCE(partner_name, '') AS partner_name, MAX(country_code) AS country_code,
          MAX(country_name) AS country_name, COALESCE(SUM(krw_supply), 0) AS amount
        FROM shipments
        WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?
        GROUP BY partner_name
        """,
        year_range,
    ).fetchall()
    region_amounts = {label: 0.0 for label in STANDARD_REGIONS}
    active_countries = {}
    active_country_ids = set()
    for row in shipment_rows:
        account = account_by_partner.get(account_link_key(row["partner_name"]))
        country = country_info_by_id(row["country_code"]) if row["country_code"] else resolve_country(row["country_name"])
        if not country and account:
            country = resolve_country(account["country"])
        region = standard_region(
            account["region"] if account else "",
            country["label"] if country else (account["country"] if account else row["country_name"]),
        )
        amount = float(row["amount"] or 0)
        if region in region_amounts:
            region_amounts[region] += amount
        country_key = country["map_id"] if country else country_lookup_key(account["country"] if account else row["country_name"])
        country_label = country["label"] if country else (account["country"] if account else row["country_name"] or "미지정")
        if country_key:
            active_country_ids.add(country_key)
            active_countries.setdefault(country_key, {"key": country_key, "label": country_label, "amount": 0.0})["amount"] += amount

    target_countries = {}
    for account in accounts:
        country = resolve_country(account["country"])
        country_key = country["map_id"] if country else country_lookup_key(account["country"])
        if not country_key or country_key in active_country_ids:
            continue
        label = country["label"] if country else account["country"] or "미지정"
        target = target_countries.setdefault(country_key, {"key": country_key, "label": label, "account_count": 0})
        target["account_count"] += 1
    region_rows = share_payload([
        {"key": label, "label": label, "amount": region_amounts[label]}
        for label in STANDARD_REGIONS
        if region_amounts[label] > 0
    ])
    return {
        "regions": region_rows,
        "active_countries": sorted(active_countries.values(), key=lambda item: item["amount"], reverse=True),
        "target_countries": sorted(target_countries.values(), key=lambda item: (-item["account_count"], item["label"])),
    }


@app.put("/api/dashboard/targets")
@role_required("admin", "manager")
@csrf_required
def save_dashboard_target():
    if not DATABASE_SCHEMA_READY.is_set():
        return jsonify(
            error="목표관리 구조를 적용하고 있습니다. 잠시 후 다시 시도하세요.",
            code="DATABASE_MIGRATING",
        ), 503
    data = request.get_json(silent=True) or {}
    target_type = str(data.get("target_type") or "").strip()
    target_key = str(data.get("target_key") or "").strip()
    if target_type == "year" and not re.fullmatch(r"\d{4}", target_key):
        return jsonify(error="연간 목표 기준연도가 올바르지 않습니다."), 400
    if target_type == "month" and not valid_forecast_month(target_key):
        return jsonify(error="월 목표 기준월이 올바르지 않습니다."), 400
    if target_type not in {"year", "month"}:
        return jsonify(error="목표 구분이 올바르지 않습니다."), 400
    try:
        target_krw = float(data.get("target_krw") or 0)
    except (TypeError, ValueError):
        return jsonify(error="목표금액은 숫자로 입력하세요."), 400
    if target_krw < 0 or target_krw != target_krw or target_krw == float("inf"):
        return jsonify(error="목표금액은 0 이상의 유효한 숫자로 입력하세요."), 400
    db = get_db()
    existing = db.execute(
        "SELECT * FROM dashboard_targets WHERE target_type = ? AND target_key = ?",
        (target_type, target_key),
    ).fetchone()
    now = utc_now()
    db.execute(
        """
        INSERT INTO dashboard_targets
          (target_type, target_key, target_krw, created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_type, target_key) DO UPDATE SET
          target_krw = excluded.target_krw,
          updated_by = excluded.updated_by,
          updated_at = excluded.updated_at
        """,
        (target_type, target_key, target_krw, g.current_user["id"], g.current_user["id"], now, now),
    )
    saved = db.execute(
        "SELECT * FROM dashboard_targets WHERE target_type = ? AND target_key = ?",
        (target_type, target_key),
    ).fetchone()
    label = f"{target_key} {'연간' if target_type == 'year' else '월간'} 매출목표"
    audit(
        "DASHBOARD_TARGET_UPDATE", "dashboard_target", f"{target_type}:{target_key}",
        f"{label} 수정 · {target_krw:,.0f}원",
        row_dict(existing), row_dict(saved),
    )
    db.commit()
    return jsonify(message=f"{label}가 저장되었습니다.", target=row_dict(saved))


@app.get("/api/dashboard")
def dashboard():
    db = get_db()
    now = datetime.now(SEOUL)
    current_year = str(now.year)
    current_month = f"{now.year:04d}-{now.month:02d}"
    year_range = (f"{current_year}-01-01", f"{current_year}-12-31")
    actual = float(db.execute(
        """
        SELECT COALESCE(SUM(krw_supply), 0) AS amount FROM shipments
        WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?
        """,
        year_range,
    ).fetchone()["amount"] or 0)
    month_actual = float(db.execute(
        """
        SELECT COALESCE(SUM(krw_supply), 0) AS amount FROM shipments
        WHERE is_overseas = 1 AND substr(ship_date, 1, 7) = ?
        """,
        (current_month,),
    ).fetchone()["amount"] or 0)
    actual_segments = db.execute(
        """
        SELECT business_unit, COALESCE(SUM(krw_supply), 0) AS amount
        FROM shipments WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?
        GROUP BY business_unit
        """,
        year_range,
    ).fetchall()
    latest_cycle = db.execute(
        "SELECT * FROM forecast_cycles WHERE forecast_month = ? ORDER BY round_no DESC LIMIT 1",
        (current_month,),
    ).fetchone()
    pending_ship_krw = 0.0
    pending_ship_count = 0
    if latest_cycle:
        pending_rows = db.execute(
            """
            SELECT * FROM forecast_items
            WHERE cycle_id = ? AND stage = 'payment_received' AND status = 'active'
              AND deleted_at IS NULL
              AND (expected_ship_date IS NULL OR substr(expected_ship_date, 1, 7) = ?)
            """,
            (latest_cycle["id"], current_month),
        ).fetchall()
        cycle_data = row_dict(latest_cycle)
        pending_ship_krw = sum(
            float(row["foreign_amount"] or 0) * forecast_rate(cycle_data, row["currency"])
            for row in pending_rows
        )
        pending_ship_count = len(pending_rows)
    pipeline = db.execute(
        "SELECT COALESCE(SUM(amount), 0) AS amount, COUNT(*) AS count FROM records WHERE entity_type = 'pipeline' AND deleted_at IS NULL"
    ).fetchone()
    account_summaries_data = account_sales_summary_rows(db)
    task_snapshot = major_task_dashboard_snapshot(db)
    major_tasks = []
    for item in task_snapshot["major_tasks"]:
        major_tasks.append({
            "id": item["id"], "field": item["primary_business_unit"],
            "country": item["country"] or "—", "title": item["title"],
            "status": item["status"], "progress": item["progress"],
            "owner_name": item.get("owner_name") or "담당자 미지정",
            "due_date": item["effective_deadline"], "other": item["next_action"],
            "rag": item["final_rag"], "is_major_task": True,
        })
    model_source = db.execute(
        """
        SELECT product_name, product_code, COALESCE(SUM(krw_supply), 0) AS amount
        FROM shipments WHERE is_overseas = 1 AND ship_date BETWEEN ? AND ?
        GROUP BY product_name, product_code
        """,
        year_range,
    ).fetchall()
    model_amounts = {}
    for row in model_source:
        label = product_model_label(row["product_name"], row["product_code"])
        model_amounts[label] = model_amounts.get(label, 0.0) + float(row["amount"] or 0)
    sorted_models = sorted(model_amounts.items(), key=lambda item: item[1], reverse=True)
    model_chart_values = [
        {"key": label, "label": label, "amount": amount}
        for label, amount in sorted_models[:7]
    ]
    if len(sorted_models) > 7:
        model_chart_values.append({
            "key": "other", "label": "기타",
            "amount": sum(amount for _label, amount in sorted_models[7:]),
        })
    model_rows = share_payload(model_chart_values)
    business_rows = share_payload([
        {
            "key": row["business_unit"] if row["business_unit"] in BUSINESS_UNIT_LABELS else "unclassified",
            "label": BUSINESS_UNIT_LABELS.get(row["business_unit"], "미분류"),
            "amount": row["amount"],
        }
        for row in actual_segments
    ])
    top_partners = top_partner_sales_rows(db, year_range)
    geography = dashboard_geography(db, year_range)
    region_counts = {label: 0 for label in STANDARD_REGIONS}
    for account in account_summaries_data:
        if account["region"] in region_counts:
            region_counts[account["region"]] += 1
    year_target = dashboard_target(db, "year", current_year)
    month_target = dashboard_target(db, "month", current_month)
    return jsonify(
        year=current_year,
        current_month=current_month,
        actual_krw=round(actual, 2),
        actual_segments={row["business_unit"]: row["amount"] for row in actual_segments},
        targets={
            "year": {**year_target, "actual_krw": round(actual, 2), "achievement_pct": round(actual / float(year_target["target_krw"] or 1) * 100, 1) if year_target["target_krw"] else 0},
            "month": {
                **month_target,
                "actual_krw": round(month_actual, 2),
                "pending_ship_krw": round(pending_ship_krw, 2),
                "pending_ship_count": pending_ship_count,
                "expected_krw": round(month_actual + pending_ship_krw, 2),
                "achievement_pct": round((month_actual + pending_ship_krw) / float(month_target["target_krw"] or 1) * 100, 1) if month_target["target_krw"] else 0,
                "forecast_round": int(latest_cycle["round_no"]) if latest_cycle else None,
            },
        },
        shares={"regions": geography["regions"], "models": model_rows, "business_units": business_rows},
        top_partners=top_partners,
        country_coverage={
            "active": geography["active_countries"],
            "target": geography["target_countries"],
            "active_count": len(geography["active_countries"]),
            "target_count": len(geography["target_countries"]),
        },
        major_tasks=major_tasks,
        pipeline_amount=pipeline["amount"],
        pipeline_count=pipeline["count"],
        account_count=len(account_summaries_data),
        task_total=task_snapshot["total"],
        task_done=task_snapshot["done"],
        task_overdue=task_snapshot["overdue"],
        major_task_brief=task_snapshot["brief"],
        regions=[{"region": label, "count": region_counts[label]} for label in STANDARD_REGIONS],
        definitions={
            "year_actual": "ERP 해외 출고 공급가의 연초 이후 누계",
            "month_expected": "당월 ERP 출고완료 + 최신 FCST 수금완료 단계 중 당월 출고대기",
            "region_share": "당해연도 ERP 해외 출고 공급가 기준 8개 표준권역 점유율",
            "model_share": "당해연도 ERP 품목명의 제품 모델군 기준 점유율",
        },
        erp_configured=erp_configured(),
        erp_freshness=erp_freshness_payload(db),
        forecast_transition=forecast_source_transition(db, current_month, latest_cycle),
    )


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="요청한 API를 찾을 수 없습니다."), 404
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.errorhandler(500)
def server_error(error):
    app.logger.exception("Unhandled error: %s", error)
    if request.path.startswith("/api/"):
        return jsonify(error="서버 처리 중 오류가 발생했습니다."), 500
    return "Internal Server Error", 500


@app.errorhandler(sqlite3.Error)
def database_error(error):
    app.logger.exception("Database operation failed: %s", error)
    if sqlite_is_busy(error):
        return jsonify(
            error="다른 데이터 저장 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.",
            code="DATABASE_BUSY",
        ), 503
    if "readonly" in str(error).lower():
        return jsonify(error="사용자 데이터 저장소의 쓰기 권한을 확인해 주세요.", code="DATABASE_READ_ONLY"), 503
    if "disk is full" in str(error).lower():
        return jsonify(error="사용자 데이터 저장공간이 부족합니다. 관리자에게 문의해 주세요.", code="DATABASE_FULL"), 503
    return jsonify(error="데이터베이스 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.", code="DATABASE_ERROR"), 503


def initialize_database(max_attempts=3):
    """Retry short SQLite lock collisions during a rolling container update."""
    for attempt in range(max_attempts):
        try:
            init_db()
            return
        except sqlite3.OperationalError as exc:
            locked = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not locked or attempt >= max_attempts - 1:
                raise
            delay = 0.5 * (attempt + 1)
            app.logger.warning(
                "Database initialization is busy; retrying in %.1fs (%s/%s)",
                delay,
                attempt + 1,
                max_attempts,
            )
            time.sleep(delay)


def release_schema_is_ready():
    db = None
    try:
        db = sqlite3.connect(DB_PATH, timeout=0.2)
        db.execute("PRAGMA busy_timeout = 200")
        columns = {row[1] for row in db.execute("PRAGMA table_info(forecast_cycles)").fetchall()}
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        required_tables = {
            "dashboard_targets",
            "forecast_round_workflows",
            "forecast_round_entries",
            "forecast_round_checklist",
            "forecast_round_details",
            "monthly_sales",
            "monthly_sales_milestones",
            "monthly_sales_split_links",
            "monthly_sales_carryovers",
            "monthly_fcst_snapshots",
            "monthly_sales_history",
            "monthly_sales_rates",
            "monthly_sales_daily_rates",
            "monthly_sales_targets",
            "monthly_sales_master_candidates",
            "monthly_sales_month_settings",
            "monthly_sales_sheet_sync",
            "monthly_sales_round_import_revisions",
            "customer_master",
            "customer_business_areas",
            "customer_business_area_details",
            "customer_organization_roles",
            "customer_languages",
            "customer_sales_countries",
            "customer_contacts",
            "customer_contracts",
            "customer_contract_products",
            "customer_contract_countries",
            "customer_payment_terms",
            "customer_product_terms",
            "customer_logistics",
            "customer_registrations",
            "customer_odm_projects",
            "customer_odm_supply_countries",
            "customer_sales_plans",
            "customer_education_events",
            "customer_marketing_support",
            "customer_competitors",
            "customer_meetings",
            "customer_attachments",
            "customer_erp_metrics",
            "customer_sync_runs",
            "customer_sync_review_items",
            "customer_erp_link_history",
            "customer_order_terms_snapshots",
            "commercial_context_schema_migrations",
            "customer_items",
            "customer_contract_item_terms",
            "promotion_commercial_terms",
            "promotion_customer_links",
            "promotion_items",
            "promotion_sales_lines",
            "customer_logistics_addresses",
            "logistics_providers",
            "customer_logistics_providers",
            "customer_document_requirements",
            "customer_document_requirement_items",
            "country_holidays",
            "customer_closures",
            "major_task_schema_migrations",
            "major_task_workstreams",
            "major_task_workstream_business",
            "major_task_workstream_templates",
            "major_tasks",
            "major_task_business_links",
            "major_task_people",
            "major_task_assignees",
            "major_task_products",
            "major_task_target_history",
            "major_task_milestones",
            "major_task_milestone_dependencies",
            "major_task_action_areas",
            "major_task_actions",
            "major_task_action_dependencies",
            "major_task_action_people",
            "major_task_checklists",
            "major_task_stages",
            "major_task_stage_people",
            "major_task_stage_work_items",
            "major_task_balls",
            "major_task_ball_history",
            "major_task_progress_updates",
            "major_task_attachments",
            "major_task_external_links",
            "major_task_legacy_mappings",
        }
        hierarchy_ready = False
        jpy_unit_ready = False
        round_timing_ready = False
        customer_master_ready = False
        if "one_time_actions" in tables:
            hierarchy_ready = db.execute(
                "SELECT 1 FROM one_time_actions WHERE action_key = ?",
                (TASK_HIERARCHY_ACTION_KEY,),
            ).fetchone() is not None
            jpy_unit_ready = db.execute(
                "SELECT 1 FROM one_time_actions WHERE action_key = ?",
                (JPY_RATE_UNIT_ACTION_KEY,),
            ).fetchone() is not None
            round_timing_ready = db.execute(
                "SELECT 1 FROM one_time_actions WHERE action_key = ?",
                (ROUND_TIMING_RULE_ACTION_KEY,),
            ).fetchone() is not None
            customer_master_ready = db.execute(
                "SELECT 1 FROM one_time_actions WHERE action_key = ?",
                (CUSTOMER_MASTER_MIGRATION_KEY,),
            ).fetchone() is not None
        detail_columns = {
            row[1] for row in db.execute("PRAGMA table_info(forecast_round_details)").fetchall()
        } if "forecast_round_details" in tables else set()
        monthly_sales_columns = {
            row[1] for row in db.execute("PRAGMA table_info(monthly_sales)").fetchall()
        } if "monthly_sales" in tables else set()
        monthly_setting_columns = {
            row[1] for row in db.execute(
                "PRAGMA table_info(monthly_sales_month_settings)"
            ).fetchall()
        } if "monthly_sales_month_settings" in tables else set()
        customer_master_columns = {
            row[1] for row in db.execute("PRAGMA table_info(customer_master)").fetchall()
        } if "customer_master" in tables else set()
        customer_sync_columns = {
            row[1] for row in db.execute("PRAGMA table_info(customer_sync_runs)").fetchall()
        } if "customer_sync_runs" in tables else set()
        customer_payment_columns = {
            row[1] for row in db.execute("PRAGMA table_info(customer_payment_terms)").fetchall()
        } if "customer_payment_terms" in tables else set()
        customer_logistics_columns = {
            row[1] for row in db.execute("PRAGMA table_info(customer_logistics)").fetchall()
        } if "customer_logistics" in tables else set()
        customer_contract_columns = {
            row[1] for row in db.execute("PRAGMA table_info(customer_contracts)").fetchall()
        } if "customer_contracts" in tables else set()
        customer_product_term_columns = {
            row[1] for row in db.execute("PRAGMA table_info(customer_product_terms)").fetchall()
        } if "customer_product_terms" in tables else set()
        customer_snapshot_columns = {
            row[1] for row in db.execute(
                "PRAGMA table_info(customer_order_terms_snapshots)"
            ).fetchall()
        } if "customer_order_terms_snapshots" in tables else set()
        commercial_context_ready = False
        if "commercial_context_schema_migrations" in tables:
            commercial_context_ready = db.execute(
                "SELECT 1 FROM commercial_context_schema_migrations WHERE version=?",
                (COMMERCIAL_CONTEXT_SCHEMA_VERSION,),
            ).fetchone() is not None
        major_task_columns = {
            row[1] for row in db.execute("PRAGMA table_info(major_tasks)").fetchall()
        } if "major_tasks" in tables else set()
        major_task_progress_columns = {
            row[1] for row in db.execute("PRAGMA table_info(major_task_progress_updates)").fetchall()
        } if "major_task_progress_updates" in tables else set()
        major_tasks_ready = False
        if "major_task_schema_migrations" in tables:
            schema_ready = db.execute(
                "SELECT 1 FROM major_task_schema_migrations WHERE version=?",
                (MAJOR_TASKS_SCHEMA_VERSION,),
            ).fetchone() is not None
            legacy_ready = db.execute(
                "SELECT 1 FROM major_task_schema_migrations WHERE version=?",
                (MAJOR_TASKS_LEGACY_MIGRATION_VERSION,),
            ).fetchone() is not None
            stage_work_ready = db.execute(
                "SELECT 1 FROM major_task_schema_migrations WHERE version=?",
                (STAGE_WORK_ITEMS_SCHEMA_VERSION,),
            ).fetchone() is not None
            major_tasks_ready = schema_ready and legacy_ready and stage_work_ready
        erp_sync_columns = {
            row[1] for row in db.execute("PRAGMA table_info(erp_sync_runs)").fetchall()
        } if "erp_sync_runs" in tables else set()
        shipment_columns = {
            row[1] for row in db.execute("PRAGMA table_info(shipments)").fetchall()
        } if "shipments" in tables else set()
        shipment_metadata_ready = False
        if "metadata_version" in shipment_columns and "one_time_actions" in tables:
            shipment_metadata_ready = db.execute(
                "SELECT 1 FROM one_time_actions WHERE action_key = ?",
                (SHIPMENT_METADATA_ACTION_KEY,),
            ).fetchone() is not None
        required_monthly_sales_columns = {
            "transaction_currency", "transaction_amount", "customer_history",
            "carryover_decision", "carryover_decided_at", "carryover_target_month",
            "carryover_decision_reason", "transaction_currency_standard", "plan_usd_rate",
            "owner_user_id", "confirmation_basis", "confirmation_note",
            "preliminary_actual_currency", "preliminary_actual_amount",
            "preliminary_actual_krw_amount", "preliminary_reference_no", "preliminary_note",
        }
        required_monthly_setting_columns = {
            "initial_cutoff_date", "round1_cutoff_date", "round2_cutoff_date",
            "round3_cutoff_date", "final_cutoff_date",
        }
        return (
            "jpy_krw" in columns
            and "progress_status" in detail_columns
            and required_monthly_sales_columns.issubset(monthly_sales_columns)
            and required_monthly_setting_columns.issubset(monthly_setting_columns)
            and {"erp_country_code", "erp_country_name"}.issubset(customer_master_columns)
            and {
                "business_stage", "business_stage_review_status", "master_maturity",
                "master_maturity_review_status", "organization_role_review_status",
            }.issubset(customer_master_columns)
            and {"payment_method_code", "payment_schedule_json", "normalization_status"}.issubset(customer_payment_columns)
            and {"contract_name", "contract_status_code", "normalization_status"}.issubset(customer_contract_columns)
            and {"interim_product_code"}.issubset(customer_product_term_columns)
            and {
                "customs_broker", "courier_code", "requires_import_invoice",
                "requires_additional_documents", "additional_documents_json",
                "normalization_status",
            }.issubset(customer_logistics_columns)
            and {"domestic_excluded_partner_count"}.issubset(customer_sync_columns)
            and {"moq_exception_reason", "moq_exception_approver"}.issubset(customer_snapshot_columns)
            and {"contract_policy"}.issubset(customer_master_columns)
            and {"commercial_status_code", "extension_end_date", "version"}.issubset(customer_contract_columns)
            and {"contract_id", "incoterms_code", "version"}.issubset(customer_payment_columns)
            and {"price_method_code", "moq_quantity", "foc_markup_pct", "term_start_date", "term_end_date", "version"}.issubset(customer_product_term_columns)
            and {"interim_product_code", "source_type", "source_promotion_id", "source_contract_id", "pricing_source", "commercial_context_json"}.issubset(monthly_sales_columns)
            and commercial_context_ready
            and {
                "review_cycle_days_override", "due_soon_days_override", "hard_deadline_soon_days_override",
                "parent_task_id", "current_stage_id", "blocker_active", "blocker_category",
                "blocker_description", "blocker_owner_id", "blocker_since", "blocker_resolved_at",
                "directive_type", "directed_by_user_id", "directive_note",
            }.issubset(major_task_columns)
            and {"applied_stage_id", "applied_ball_id", "applied_rag", "state_change_json"}.issubset(major_task_progress_columns)
            and {"excluded_partner_count"}.issubset(erp_sync_columns)
            and {
                "existing_line_count", "existing_krw_amount", "new_krw_amount", "latest_ship_date",
                "preflight_json", "currency_totals_json", "management_totals_json",
                "quality_warnings_json", "forced", "force_reason",
            }.issubset(erp_sync_columns)
            and {
                "erp_management_code", "erp_management_name", "source_system", "actual_review_status",
            }.issubset(shipment_columns)
            and shipment_metadata_ready
            and {
                "effective_at", "effective_at_source", "change_set_json",
            }.issubset({row[1] for row in db.execute("PRAGMA table_info(monthly_sales_history)").fetchall()})
            and required_tables.issubset(tables)
            and hierarchy_ready
            and jpy_unit_ready
            and round_timing_ready
            and customer_master_ready
            and major_tasks_ready
        )
    except sqlite3.Error:
        return False
    finally:
        if db is not None:
            db.close()


def start_database_initialization():
    """Start safely during a rolling deploy, then migrate after the old app drains."""
    global DATABASE_INIT_ERROR
    prepare_database_storage()
    if not ASYNC_DATABASE_INIT:
        initialize_database()
        verify_database_storage_writable()
        DATABASE_READY.set()
        DATABASE_SCHEMA_READY.set()
        return

    existing_database = os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0
    if existing_database:
        # Do not contend with a previous rolling container. Existing data and
        # an already-applied release schema are immediately available.
        verify_database_storage_writable()
        DATABASE_READY.set()
        if release_schema_is_ready():
            DATABASE_SCHEMA_READY.set()
            return
        app.logger.info("Existing database requires release schema migration; starting asynchronously")

    def run():
        global DATABASE_INIT_ERROR
        try:
            initialize_database(max_attempts=10)
            verify_database_storage_writable()
        except Exception as exc:
            DATABASE_INIT_ERROR = str(exc)
            app.logger.exception("Asynchronous database initialization failed")
            return
        DATABASE_READY.set()
        DATABASE_SCHEMA_READY.set()
        app.logger.info("Asynchronous database initialization completed")

    threading.Thread(target=run, name="database-initializer", daemon=True).start()


register_monthly_sales_fcst(
    app,
    get_db,
    role_required,
    csrf_required,
    utc_now,
    audit,
    rollback_quietly,
    sqlite_is_busy,
    country_catalog=COUNTRY_CATALOG,
)

register_customer_master(
    app,
    get_db,
    role_required,
    csrf_required,
    audit,
    country_resolver=resolve_country,
    country_catalog=COUNTRY_CATALOG,
)

register_commercial_context(
    app,
    get_db,
    role_required,
    csrf_required,
    audit,
    utc_now,
    country_catalog=COUNTRY_CATALOG,
)

register_major_tasks(
    app,
    get_db,
    role_required,
    csrf_required,
    audit,
)

start_database_initialization()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
