# 주요업무 원장 마이그레이션 운영 절차

이 문서는 스키마 `major-tasks-2026-09-07-v2`와 기존자료 이관 `major-tasks-legacy-2026-09-07-v1`을 운영 SQLite에 적용하기 전에 실행할 백업·복제 검증·건수 대조 절차입니다. 애플리케이션 기본 DB는 `/app/user_data/runtime/medpark_global_maps.db`이며, 모든 점검은 먼저 백업본에서 수행합니다.

## 1. 배포 전 중지 조건

다음 중 하나라도 해당하면 배포와 운영 마이그레이션을 중단합니다.

- SQLite 백업을 만들거나 복원 시험을 할 수 없음
- `records`, `users`, `audit_logs` 중 하나가 없음
- 복제 DB 드라이런에서 `passed`가 `false`
- 기존 `records.task` 원문, `payload_json`, 핵심 필드 또는 이관 매핑 불일치가 발생
- 드라이런 두 번째 실행에서 신규 주요업무·마일스톤·실행항목이 다시 생성됨
- 애플리케이션이 새 원장과 기존 `records.task`를 동시에 집계함

## 2. 읽기 전용 사전점검

운영 DB 파일을 직접 인자로 주지 말고 먼저 복사한 백업본을 사용합니다.

```bash
python scripts/major_tasks_preflight.py /secure/backup/medpark_global_maps-before-major-tasks.db
```

확인 항목은 전체 task, group, detail, 부모 없는 detail, 삭제표시, 누락 사업분야·담당자·기한, 기존 스키마 버전입니다. 운영 건수는 이 명령 결과를 보고 확정하며 소스만으로 추정하지 않습니다.

## 3. 복제 DB 마이그레이션 검증

```bash
python scripts/major_tasks_migration_dry_run.py /secure/backup/medpark_global_maps-before-major-tasks.db
```

도구는 SQLite backup API로 임시 복제본을 만든 뒤에만 스키마와 이관을 실행합니다. 원본 파일 SHA-256, 기존 레코드 원문, 매핑 누락, `payload_json`, 제목·담당자·기한·금액·통화·상세내용, 재실행 멱등성을 검증합니다.

필수 결과:

- `source_unchanged: true`
- `legacy_rows_unchanged: true`
- `missing_mapping_ids: []`
- `payload_mismatch_ids: []`
- `preserved_field_mismatch_ids: []`
- 첫 번째 실행의 `status: applied`
- 두 번째 실행의 `status: already_applied`
- `raw_idempotency_check`의 `tasks`, `milestones`, `actions`, `orphans`가 모두 `0`
- `readiness_markers`에 스키마 버전과 기존자료 이관 버전이 모두 존재
- `passed: true`

## 4. 수동 건수 비교 쿼리

```sql
SELECT COUNT(*) AS legacy_total
FROM records
WHERE entity_type = 'task';

SELECT COUNT(*) AS migrated_mapping_total
FROM major_task_legacy_mappings;

SELECT COUNT(*) AS migrated_top_level_total
FROM major_tasks
WHERE legacy_record_id IS NOT NULL;

SELECT COUNT(*) AS migrated_detail_total
FROM major_task_legacy_mappings
WHERE action_id IS NOT NULL;

SELECT COUNT(*) AS orphan_review_total
FROM major_tasks
WHERE migration_review_required = 1;

SELECT legacy_record_id
FROM major_task_legacy_mappings
GROUP BY legacy_record_id
HAVING COUNT(*) > 1;
```

`legacy_total`과 `migrated_mapping_total`은 같아야 합니다. 대분류와 세부항목은 하나의 주요업무와 하위 실행항목으로 재구성되므로 `legacy_total`과 `migrated_top_level_total`은 같지 않을 수 있습니다.

## 5. 운영 적용 순서

1. 쓰기 작업을 잠시 막고 SQLite WAL·SHM을 포함한 일관된 백업을 생성합니다.
2. 백업을 별도 위치에 보존하고 실제 복원 가능 여부를 확인합니다.
3. 백업본에 사전점검과 드라이런을 실행합니다.
4. 코드 배포 시 애플리케이션 초기화 트랜잭션이 버전 지정 스키마와 기존자료 이관을 적용하고, 두 완료 마커가 모두 기록된 경우에만 새 원장을 준비 완료로 판단합니다.
5. `/api/health`와 릴리스 스키마 검사를 확인합니다.
6. 위 건수 비교와 샘플 원문 대조를 다시 실행합니다.
7. 주요업무, 메인 대시보드, 세계지도, 거래처 상세, 일일 요약, 완료율·지연건수를 확인합니다.
8. 문제가 있으면 쓰기를 중지하고 배포 전 코드와 DB 백업본을 함께 복원합니다.

## 6. 데이터 원칙

- 기존 `records.task`는 검증 전 삭제하지 않습니다.
- 신규 기능과 관련 화면은 새 주요업무 원장만 읽어 이중집계를 방지합니다.
- 업무·하위 구조·이력은 물리삭제하지 않고 취소·비활성화·아카이브로 보존합니다.
- 프로모션과 ERP의 기존 호출·저장 로직은 이 마이그레이션에서 변경하지 않습니다.
- 운영 파일 저장소가 확정되기 전에는 외부 링크만 첨부자료로 저장합니다.
