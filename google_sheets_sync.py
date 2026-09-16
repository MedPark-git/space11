"""Google Sheets mirror for the monthly sales FCST module.

The dashboard database remains the transactional source of truth.  Sheets is a
read-only operational mirror for managers and backup/export use.  The module is
loaded lazily so the application still starts before credentials are supplied.
"""

import base64
import json
import os
from datetime import datetime, timezone


SHEET_SCHEMAS = {
    "SALES": [
        "sales_id", "sales_no", "customer_name", "country", "owner_name",
        "business_unit", "customer_history", "transaction_currency", "transaction_amount",
        "currency", "original_month", "target_month",
        "timing_type", "amount_usd", "plan_rate", "actual_rate", "applied_rate",
        "rate_type", "krw_amount", "sales_status", "record_status",
        "split_role", "carryover_role", "carryover_status", "carryover_decided_at",
        "carryover_target_month", "carryover_decision_reason", "original_sales_id", "split_group_id",
        "notes", "version", "created_by", "created_at", "updated_by", "updated_at",
    ],
    "MILESTONES": [
        "sales_id", "sales_no", "order_agreed_at", "po_received_at", "pi_no",
        "pi_sent_at", "pi_confirmed_at", "payment_expected_at", "payment_actual_at",
        "shipment_expected_at", "shipment_actual_at", "shipping_expected_at",
        "shipping_actual_at", "exception_reason", "updated_at",
    ],
    "SPLIT_LINKS": [
        "id", "split_group_id", "original_sales_id", "child_sales_id",
        "amount_before", "proceed_amount", "split_amount", "split_date",
        "reason", "new_pi_no", "status", "created_by", "created_at",
        "cancelled_by", "cancelled_at", "cancel_reason",
    ],
    "CARRYOVER_HISTORY": [
        "id", "source_sales_id", "target_sales_id", "carryover_type",
        "source_month", "target_month", "amount_usd", "status_at_carryover",
        "carryover_label", "carryover_date", "reason", "status", "created_by",
        "created_at", "cancelled_by", "cancelled_at", "cancel_reason",
    ],
    "FORECAST": [
        "id", "target_month", "sales_id", "sales_no", "business_unit",
        "sales_status", "amount_usd", "krw_amount", "submitted_by", "submitted_at",
    ],
    "HISTORY": [
        "id", "sales_id", "sales_no", "event_type", "reason", "actor_name",
        "occurred_at", "snapshot_json",
    ],
    "RATES": [
        "rate_scope", "target_month", "rate_base_date", "currency", "rate", "source",
        "uploaded_file", "updated_by", "updated_at", "correction_reason",
    ],
    "TARGETS": [
        "target_month", "business_unit", "target_usd", "target_krw",
        "updated_by", "updated_at",
    ],
    "MASTER_CANDIDATES": [
        "customer_name", "country", "owner_name", "business_unit",
        "usage_count", "first_seen_at", "last_seen_at", "status",
    ],
    "SETTINGS": [
        "target_month", "month_status", "initial_cutoff_date", "round1_cutoff_date",
        "round2_cutoff_date", "round3_cutoff_date", "final_cutoff_date", "closed_by", "closed_at",
        "reopened_by", "reopened_at", "reopen_reason", "updated_at",
    ],
}


def _credential_info():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    encoded = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "").strip()
    if not raw and encoded:
        try:
            raw = base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:
            raise ValueError("Google 서비스 계정 Base64 값이 올바르지 않습니다.") from exc
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Google 서비스 계정 JSON 형식이 올바르지 않습니다.") from exc
    if data.get("type") != "service_account" or not data.get("client_email"):
        raise ValueError("Google 서비스 계정 인증정보가 아닙니다.")
    return data


def sheets_status():
    spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
    try:
        credential = _credential_info()
        error = None
    except ValueError as exc:
        credential = None
        error = str(exc)
    return {
        "configured": bool(spreadsheet_id and credential),
        "spreadsheet_id_set": bool(spreadsheet_id),
        "credentials_set": bool(credential),
        "service_account_email": credential.get("client_email") if credential else None,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}" if spreadsheet_id else None,
        "error": error,
        "tabs": list(SHEET_SCHEMAS),
    }


class GoogleSheetsMirror:
    API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self):
        self.spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
        self.credential_info = _credential_info()
        if not self.spreadsheet_id or not self.credential_info:
            raise ValueError("Google Sheets 연동정보가 아직 설정되지 않았습니다.")

        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as exc:
            raise RuntimeError("Google Sheets 연동 모듈 설치가 필요합니다.") from exc

        credentials = service_account.Credentials.from_service_account_info(
            self.credential_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self.session = AuthorizedSession(credentials)

    def _request(self, method, suffix="", **kwargs):
        url = f"{self.API_ROOT}/{self.spreadsheet_id}{suffix}"
        response = self.session.request(method, url, timeout=30, **kwargs)
        if response.status_code >= 400:
            detail = ""
            try:
                detail = response.json().get("error", {}).get("message", "")
            except Exception:
                detail = response.text[:300]
            raise RuntimeError(f"Google Sheets 저장 실패({response.status_code}): {detail or '응답을 확인할 수 없습니다.'}")
        return response.json() if response.content else {}

    def ensure_schema(self):
        metadata = self._request("GET", "?fields=sheets.properties")
        properties = [sheet["properties"] for sheet in metadata.get("sheets", [])]
        existing = {item["title"] for item in properties}
        setup_requests = []
        renamed_default = False
        if existing == {"Sheet1"} and "SALES" not in existing:
            default = properties[0]
            setup_requests.append({
                "updateSheetProperties": {
                    "properties": {"sheetId": default["sheetId"], "title": "SALES"},
                    "fields": "title",
                }
            })
            existing = {"SALES"}
            renamed_default = True
        missing = [name for name in SHEET_SCHEMAS if name not in existing]
        setup_requests.extend(
            {"addSheet": {"properties": {"title": name, "gridProperties": {"frozenRowCount": 1}}}}
            for name in missing
        )
        if setup_requests:
            self._request(
                "POST",
                ":batchUpdate",
                json={"requests": setup_requests},
            )
        metadata = self._request("GET", "?fields=sheets.properties")
        sheet_ids = {
            sheet["properties"]["title"]: sheet["properties"]["sheetId"]
            for sheet in metadata.get("sheets", [])
        }
        header_data = []
        for name, headers in SHEET_SCHEMAS.items():
            header_data.append({"range": f"'{name}'!A1", "majorDimension": "ROWS", "values": [headers]})
        self._request(
            "POST",
            "/values:batchUpdate",
            json={"valueInputOption": "RAW", "data": header_data},
        )
        format_requests = []
        for name, headers in SHEET_SCHEMAS.items():
            sheet_id = sheet_ids[name]
            format_requests.extend([
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                                  "startColumnIndex": 0, "endColumnIndex": len(headers)},
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": {"red": 0.027, "green": 0.231, "blue": 0.298},
                            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1}, "bold": True},
                            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                        }},
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
                    }
                },
                {
                    "setBasicFilter": {
                        "filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0,
                                             "startColumnIndex": 0, "endColumnIndex": len(headers)}}
                    }
                },
                {
                    "autoResizeDimensions": {
                        "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                                       "startIndex": 0, "endIndex": len(headers)}
                    }
                },
            ])
        self._request("POST", ":batchUpdate", json={"requests": format_requests})
        created_tabs = (["SALES"] if renamed_default else []) + missing
        return {"created_tabs": created_tabs, "tabs": list(SHEET_SCHEMAS)}

    def replace_all(self, sheet_rows):
        self.ensure_schema()
        self._request(
            "POST",
            "/values:batchClear",
            json={"ranges": [f"'{name}'!A2:ZZ" for name in SHEET_SCHEMAS]},
        )
        updates = []
        counts = {}
        for name, headers in SHEET_SCHEMAS.items():
            rows = sheet_rows.get(name, [])
            counts[name] = len(rows)
            if not rows:
                continue
            values = [[_sheet_value(row.get(header)) for header in headers] for row in rows]
            updates.append({"range": f"'{name}'!A2", "majorDimension": "ROWS", "values": values})
        if updates:
            self._request(
                "POST",
                "/values:batchUpdate",
                json={"valueInputOption": "RAW", "data": updates},
            )
        return {"synced_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "counts": counts}


def _sheet_value(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
