# MedPark Global MAPS

해외영업 업무·매출·FCST를 관리하는 Flask 대시보드입니다. `월별 매출 FCST` 메뉴는 개별 매출 건, 진행단계, 최초 FCST, 매출분리, 차월, 과거 기준일, 환율, 목표, Excel 및 Google Sheets 백업을 통합 관리합니다.

## 월별 매출 FCST 저장 원칙

- 실제 운영 원장(Source of Truth): 기존 애플리케이션 SQLite DB (`/app/user_data/runtime/medpark_global_maps.db`)
- 관리자 확인·백업: 비공개 Google Sheets 자동 미러
- 모든 등록·수정·분리·차월·취소·환율·마감 작업은 앱에서 수행합니다.
- Google Sheets를 직접 수정한 내용은 앱 DB로 역반영하지 않습니다.
- Sheets 동기화가 실패해도 앱 DB의 저장 결과와 실패 상태를 구분해 표시하고, 관리자가 `지금 동기화`로 재시도할 수 있습니다.

## 거래처별 매출 현황

- 표 열은 `사업분야 → 거래처 → 국가 → 진행 시점 → 신규/기존 → 담당자 → USD 기준·거래금액 → KRW·환율 → 진행현황 → 차월 구분 → 비고 → 관리 → 관리번호` 순서입니다.
- 기존 단계 연결 그래프를 유지하면서 각 단계 아래에 날짜를 표시합니다. 수금·출고·선적은 예정일과 완료일을 함께 표시합니다.
- 확정·예정·추진·미정 섹션에는 각각 독립적인 복수선택 필터가 있습니다. 같은 항목의 선택값은 OR, 서로 다른 항목은 AND 조건입니다.
- 각 섹션 하단 소계는 현재 섹션 필터 결과를 기준으로 고유 거래처 수, USD 및 KRW를 계산합니다.
- 상세 표는 읽기 쉬운 열 너비를 유지하고, 섹션 안의 가로 스크롤로 전체 진행현황과 관리 열을 확인합니다.
- 차월 구분은 `차월 진행`과 `당월 유지` 두 값만 사용합니다. `차월 진행`은 결정일·대상월·사유를 기록하며, 실제 금액 이관은 별도의 차월 처리 기능을 실행해야 합니다.
- 일부 금액만 차월할 때는 해당 매출을 먼저 분리한 뒤 분리된 건을 전액 차월합니다.

## 월별 기준환율·차수별 조회

- 관리자·매니저·편집자가 `환율·차수 설정` 창에서 월별 `USD·EUR·JPY(1엔)·CNH·KRW` 기준환율을 직접 입력합니다. KRW는 1로 고정됩니다.
- 월 기준환율은 신규 FCST의 기본값이며, 매출 건에 저장된 `plan_rate`는 생성 또는 공식 재계획 당시의 스냅샷으로 유지됩니다.
- 담당자 수기 출고는 Preliminary로 저장하고 계획환율을 덮어쓰지 않습니다. 서울외국환중개 자동수집을 검증하기 전에는 캐시·관리자 입력 fallback을 사용하며 외부 장애가 저장을 막지 않습니다.
- 월마다 `최초 FCST·1차·2차·3차·최종마감` 기준일을 별도로 설정할 수 있으며, 카드를 누르면 해당 날짜 23:59:59 시점의 전체 대시보드를 조회합니다. 최종마감 기준일은 다음 달로도 지정할 수 있습니다.
- 카드 합산 기준은 최초 FCST·1차 `확정+예정+추진`, 2차 `확정+예정`과 보조값 `추진 포함 시`, 3차 `확정+예정`, 최종마감 `확정`입니다.
- 차수별 카드와 사업분야별 요약표는 USD와 KRW를 함께 표시하며, 관리자·매니저·편집자가 월별 차수 기준일을 설정할 수 있습니다.

## Google Sheets 최초 설정

1. Google Cloud에서 프로젝트를 만들고 **Google Sheets API**를 사용 설정합니다.
2. 서비스 계정을 만든 뒤 JSON 키를 발급합니다. JSON 파일은 소스·Git·공유 폴더에 올리지 않습니다.
3. Google Sheets에서 빈 스프레드시트를 하나 만들고 서비스 계정의 `client_email` 주소에 **편집자** 권한으로 공유합니다. 링크 공개는 사용하지 않습니다.
4. 스프레드시트 URL의 `/d/`와 다음 `/` 사이 값을 `GOOGLE_SHEETS_SPREADSHEET_ID`로 사용합니다.
5. 서비스 계정 JSON 전체를 Base64 한 줄로 인코딩하여 `GOOGLE_SERVICE_ACCOUNT_JSON_B64`로 등록합니다. AI SPACE 환경변수에는 줄바꿈 없는 문자열로 저장합니다.

macOS/Linux 예시:

```bash
base64 < service-account.json | tr -d '\n'
```

환경변수:

```text
GOOGLE_SHEETS_SPREADSHEET_ID=<스프레드시트 ID>
GOOGLE_SERVICE_ACCOUNT_JSON_B64=<서비스 계정 JSON의 Base64 문자열>
```

대안으로 `GOOGLE_SERVICE_ACCOUNT_JSON`에 JSON 원문을 등록할 수도 있지만, AI SPACE에서는 Base64 방식을 권장합니다. 환경변수 등록 후 재배포하고, 관리자 계정으로 `월별 매출 FCST → 목표·마감기준일 → Google Sheets 구성·동기화`를 한 번 실행합니다.

빈 스프레드시트의 기본 `Sheet1`은 `SALES`로 재사용되며 다음 10개 탭이 자동 구성됩니다.

| 탭 | 용도 |
|---|---|
| `SALES` | 현재·취소·전액차월 매출 원장 미러 |
| `MILESTONES` | 오더·PO·PI·수금·출고·선적 일정 |
| `SPLIT_LINKS` | 매출분리 원본/분리 건과 취소 이력 |
| `CARRYOVER_HISTORY` | 전액차월 연결 및 처리 이력(기존 일부차월 이력도 보존) |
| `FORECAST` | 덮어쓰지 않는 최초 FCST 스냅샷 |
| `HISTORY` | 매출 건별 변경 당시 전체 스냅샷 |
| `RATES` | 월별 다중통화 기준환율과 향후 출고일 확정환율 |
| `TARGETS` | 월·사업분야별 USD/KRW 목표 |
| `MASTER_CANDIDATES` | 입력된 거래처·국가·담당자·사업분야 후보 |
| `SETTINGS` | 월 마감·재개방과 차수별 기준일 설정 |

각 탭에는 헤더 색상, 자동 필터, 첫 행 고정과 열 자동폭이 적용됩니다.

## 출고일 확정환율·ERP 연동

서울외국환중개 환율 자동수집과 Amaranth ERP 출고현황의 FCST 자동 대조는 검증 전까지 활성화하지 않습니다. ERP 원문, 계획값, Preliminary 출고값은 서로 덮어쓰지 않습니다.

## 주요업무 원장

- 주요업무는 기존 SQLite와 `sqlite3` 연결을 유지하면서 `major_tasks` 관계형 원장으로 관리합니다.
- 기존 `records`의 `entity_type=task` 자료는 버전 지정 마이그레이션으로 보존 이전하며, 원본 레코드와 `payload_json`은 삭제하거나 덮어쓰지 않습니다.
- 기존 대분류 아래의 세부항목은 `기존 세부항목` 마일스톤의 실행항목으로 옮기며, 부모를 찾지 못한 세부항목은 독립 업무와 `이관 확인 필요` 상태로 보존합니다.
- 신규 화면은 목록·상세 지연로딩, 검색·필터·정렬·페이지 처리, 대표님 지시사항, 워크스트림 템플릿, 병렬 마일스톤, 실행영역·실행항목·체크리스트, Ball, RAG, 진행이력, 완료·취소·복원을 지원합니다.
- 외부 첨부파일 영구 저장소가 확인되지 않아 파일 자체 업로드는 활성화하지 않고 외부 링크와 메타정보만 저장합니다.
- 향후 자료 연결을 위한 범용 내부 테이블만 마련했으며 프로모션 화면·DB·API·FCST 로직은 변경하지 않습니다.

주요업무 운영 DB 적용 전에는 반드시 백업본으로 아래 절차를 수행합니다.

```bash
python scripts/major_tasks_preflight.py /path/to/backup.db
python scripts/major_tasks_migration_dry_run.py /path/to/backup.db
```

상세 절차와 전후 검증 쿼리는 `docs/major_tasks_migration.md`를 참고합니다.

## Excel 가져오기·내보내기

- `업로드 양식`: 입력 탭과 사용안내 탭, 사업분야/신규·기존/진행 시점/환종/상태/차월 구분 드롭다운을 제공합니다.
- 가져오기: 필수값·날짜·숫자·상태·환종·PI·중복 매출을 전체 검증하며, 오류가 한 행이라도 있으면 아무 행도 저장하지 않습니다.
- 내보내기: 조회월·기준일·필터·생성시각, USD/KRW 사업분야 요약과 매출 세부현황을 포함합니다.

## 로컬 검증

```bash
python -m unittest -v test_major_tasks.py test_customer_master.py test_monthly_sales_fcst.py
node --check public/monthly-sales-fcst.js
node --check public/major-tasks.js
node --check public/app.js
python -m py_compile app.py major_tasks.py major_tasks_migration.py monthly_sales_fcst.py google_sheets_sync.py
```

운영 배포와 환경변수 등록은 별도 승인 후 진행합니다.
