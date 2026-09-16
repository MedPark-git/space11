"""Canonical MAPS taxonomies shared by Customer, FCST, Dashboard and Tasks.

Only stable codes live here.  Domain tables keep ownership of their own values;
this module merely prevents each read/write path from inventing a different enum
or label for the same concept.
"""

from __future__ import annotations

import re


PARENT_BUSINESS_AREAS = {
    "aesthetic": "에스테틱",
    "medical": "메디컬",
    "dental": "덴탈",
}

CUSTOMER_BUSINESS_AREA_DETAILS = {
    "dental": {"label": "Dental", "parent": "dental", "selectable": True},
    "aesthetic": {"label": "Aesthetic", "parent": "aesthetic", "selectable": True},
    "medical_os": {"label": "Medical (OS)", "parent": "medical", "selectable": True},
    "medical_ns": {"label": "Medical (NS)", "parent": "medical", "selectable": True},
    # Transitional display-only code.  It preserves an existing parent Medical
    # row without pretending that OS/NS was historically known.
    "medical_unspecified": {
        "label": "Medical (상세 검토 필요)",
        "parent": "medical",
        "selectable": False,
    },
}

CUSTOMER_STAGES = {
    "new_prospect": "신규후보",
    "regular_candidate": "정규후보",
    "regular": "정규",
    "discontinued": "중단",
}

MASTER_MATURITIES = {
    "temporary": "임시 Master",
    "formal": "정식 Master",
}

ORGANIZATION_ROLES = {
    "distributor": "Distributor",
    "odm": "ODM",
    "clinic_hospital": "Clinic / Hospital",
    "kol": "KOL",
    "other": "Other",
}

LANGUAGES = {
    "en": "영어",
    "ar": "아랍어",
    "zh": "중국어",
    "ja": "일본어",
    "es": "스페인어",
    "pt": "포르투갈어",
    "ru": "러시아어",
    "hi": "힌디어",
    "fr": "프랑스어",
    "de": "독일어",
}

PAYMENT_METHODS = {
    "tt": "T/T",
    "lc": "L/C",
    "other": "기타",
}

PAYMENT_TRIGGERS = {
    "order_confirmation": "Order Confirmation",
    "before_shipment": "Before Shipment",
    "after_shipment": "After Shipment",
    "invoice_date": "Invoice Date",
    "fixed_date": "Fixed Date",
    "other": "기타",
}

COURIERS = {
    "dhl": "DHL",
    "fedex": "FedEx",
    "ups": "UPS",
    "ems": "EMS",
    "tnt": "TNT",
}

ADDITIONAL_DOCUMENTS = {
    "certificate_of_origin": "Certificate of Origin / 원산지증명서",
}

INTERIM_CONTRACT_PRODUCTS = {
    "medpark_bovine_s1": "MedPark Bovine (S1)",
    "boss": "BOSS",
    "colla": "COLLA",
    "a1_oss": "A1 OSS",
    "medpark_allo_medical": "MedPark Allo (Medical)",
    "medpark_allo_dental": "MedPark Allo (Dental)",
    "s_derm": "S Derm",
    "s_gen": "S Gen",
    "s_gen_inject": "S Gen Inject",
    "adite": "Adite",
    "a1_bonechip": "A1 Bonechip",
    "a1_dbm": "A1 DBM",
}

CONTRACT_STATUSES = {
    "draft": "작성·협의중",
    "active": "유효",
    "suspended": "일시중지",
    "expired": "만료",
    "terminated": "종료",
}

CONTRACT_EXCLUSIVITIES = {
    "exclusive": "Exclusive / 독점",
    "non_exclusive": "Non-exclusive / 비독점",
    # Some current contracts explicitly mix exclusivity by product.  This is a
    # real business state, not an automatic conversion of the legacy raw text.
    "mixed": "Mixed / 제품별 상이",
}

CONTACT_EMPLOYMENT_STATUSES = {
    "active": "재직",
    "inactive": "퇴사·비활성",
}

MEETING_IMPORTANCE = {
    "high": "높음",
    "medium": "보통",
    "low": "낮음",
}

MEETING_ACTION_STATUSES = {
    "open": "진행 전",
    "in_progress": "진행 중",
    "done": "완료",
    "cancelled": "취소",
}

REVIEW_STATUSES = {"review_required", "confirmed"}


def business_parent(code: str | None) -> str | None:
    """Return the common three-axis parent code without guessing unknown data."""
    value = str(code or "").strip().lower()
    if value in PARENT_BUSINESS_AREAS:
        return value
    detail = CUSTOMER_BUSINESS_AREA_DETAILS.get(value)
    return detail["parent"] if detail else None


def _role_tokens(*values):
    for value in values:
        for token in re.split(r"[^0-9a-z가-힣]+", str(value or "").casefold()):
            if token:
                yield token


def legacy_role_candidates(*values) -> list[str]:
    """Return review candidates only; callers must never persist these silently."""
    tokens = set(_role_tokens(*values))
    candidates = []
    if tokens & {"dealer", "distributor", "딜러", "대리점", "총판"}:
        candidates.append("distributor")
    if "odm" in tokens or "oem" in tokens:
        candidates.append("odm")
    if tokens & {"clinic", "hospital", "병원", "의원", "클리닉"}:
        candidates.append("clinic_hospital")
    return candidates


def options(mapping):
    return [{"code": code, "label": label} for code, label in mapping.items()]


def taxonomy_payload():
    return {
        "business_parent": options(PARENT_BUSINESS_AREAS),
        "customer_business_area_details": [
            {"code": code, **definition}
            for code, definition in CUSTOMER_BUSINESS_AREA_DETAILS.items()
        ],
        "customer_stages": options(CUSTOMER_STAGES),
        "master_maturities": options(MASTER_MATURITIES),
        "organization_roles": options(ORGANIZATION_ROLES),
        "languages": options(LANGUAGES),
        "payment_methods": options(PAYMENT_METHODS),
        "payment_triggers": options(PAYMENT_TRIGGERS),
        "couriers": options(COURIERS),
        "additional_documents": options(ADDITIONAL_DOCUMENTS),
        "interim_contract_products": options(INTERIM_CONTRACT_PRODUCTS),
        "contract_statuses": options(CONTRACT_STATUSES),
        "contract_exclusivities": options(CONTRACT_EXCLUSIVITIES),
        "contact_employment_statuses": options(CONTACT_EMPLOYMENT_STATUSES),
        "meeting_importance": options(MEETING_IMPORTANCE),
        "meeting_action_statuses": options(MEETING_ACTION_STATUSES),
    }
