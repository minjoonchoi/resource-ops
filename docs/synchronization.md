# DB 동기화 계약

이 문서는 이 저장소를 소비하는 **별도 동기화 서버의 구현 계약**입니다.
현재 저장소에는 DB 연결 코드, migration, reconciler 실행 서버 또는 운영 배포가 포함되지 않습니다.

## 원본과 소유권

Git의 유효한 전체 snapshot이 카탈로그 리소스와 연결의 원본입니다.
동기화 대상 식별자는 `(sourceId, catalogName, kind, name)`입니다.
`sourceId`는 동기화 서버에 등록한 저장소/관리 범위의 안정적 ID이며 YAML로 임의 변경하지 않습니다.
일반 사용자·조직·역할·정책 할당, 서비스 어카운트, API Key, 결재 데이터는 별도 소유 영역입니다.
카탈로그 동기화가 이 데이터를 덮어쓰거나 연쇄 삭제하지 않습니다.

DB 관리 화면에서 Git 관리 리소스의 원본 필드를 수정하지 않습니다.
조회 및 변경 제안은 가능하지만 원본 변경은 PR로 돌아가야 합니다.
DB drift가 생기면 같은 Git revision이라도 다시 비교해 desired state로 복구해야 합니다.

## 입력과 정규화

한 동기화 시도는 `sourceId`, `catalogName`, `sourceRevision`(전체 commit SHA),
manifest와 그 안의 모든 리소스 문서를 입력으로 받습니다.
`catalogName`은 등록된 카탈로그와 manifest.metadata.name이 일치하는지 확인합니다.
어떤 파일도 다른 commit SHA에서 섞어 읽지 않습니다.

1. manifest, YAML 문법, `apiVersion`, 문서 스키마를 검증합니다.
2. 파일 목록·identity·참조·Endpoint 계약·Page별 override·Page 계층을 검증합니다.
3. kind/name으로 리소스를 정렬하고 참조에서 네 가지 연결과 Page별 최종 사용 계약을 도출합니다.
4. 현재 DB 상태와 비교하여 create/update/deactivate/unchanged 계획을 만듭니다.
5. DB 외부 참조(예: 활성 정책)가 삭제 예정 리소스를 사용하면 전체 반영을 차단하고 충돌을 보고합니다.

운영 consumer는 명시된 manifest 파일만 읽습니다. 로컬 CI는 추가로 Git 작업 트리 전체를 검사하여
manifest에 등록하지 않은 YAML도 잡습니다. 어떤 파일이든 읽기/검증에 실패하면 완성된 snapshot이 아닙니다.

검증 CLI의 snapshot에는 다음 값이 들어 있습니다.

| 필드 | 의미 |
| --- | --- |
| `apiVersion`, `kind` | `resource-ops/v1`, `CatalogSnapshot` |
| `metadata` | 카탈로그의 이름·제목·설명 |
| `resources` | kind/name 순서의 검증된 원본 리소스 |
| `relations` | from/type/to 순서의 파생 연결, uses 관계는 overrides 속성 보존 |
| `pageActionUsages` | page/action 순서의 최종 사용 계약: page, action, endpoint, effective |
| `contentSha256` | hash 필드 자체를 제외한 정규화 문서의 SHA-256 |

hash 입력은 UTF-8 JSON이며 object key를 정렬하고 불필요한 공백 없이 직렬화합니다.
resources, relations, pageActionUsages는 정렬하지만 각 리소스 내부 배열 순서는 보존합니다.
hash는 이 Python CLI의 동일 구현 내 변경 비교에 사용할 수 있습니다.
다른 언어 구현은 JSON 숫자/Unicode 직렬화 차이를 고려해야 하며 이 규칙을 검증 없이 범용 JCS로 간주하지 않습니다.
revision은 Git provenance, hash는 내용 비교 보조 정보입니다. 둘을 같은 값으로 취급하지 않습니다.
DB drift 확인 없이 `sourceRevision` 또는 hash가 같다는 이유만으로 항상 비교를 생략하지 않습니다.

Page의 Action 사용 정의가 override의 원본입니다. `uses.overrides`와 `pageActionUsages`는
거기서 도출한 데이터이며 별도의 편집 원본으로 사용하지 않습니다.
Action에는 endpoint 참조만 저장하고, 요청/응답 필드 설정은 Page 사용 정의에 저장합니다.
사용 계약의 key는 `(sourceId, catalogName, page, action)`입니다.
Endpoint나 Action 참조가 변경되면 연결된 모든 Page의 effective를 다시 계산합니다.
변경된 Page 파일만 부분 처리하면 상속 데이터가 오래된 상태로 남으므로 전체 snapshot에서 재계산합니다.

## 트랜잭션과 동시 실행

전체 snapshot 검증과 diff 준비 후 하나의 DB 트랜잭션에서 반영합니다.

1. `(sourceId, catalogName)` 상태 행에 lock을 획득합니다.
2. 계획 작성 시 관측한 generation/observedRevision이 현재 상태와 같은지 확인합니다.
3. 새 desiredRevision이 예약되었으면 오래된 작업의 반영을 취소하고 최신 snapshot으로 다시 계획합니다.
4. Server → Endpoint → Action → Page 순서로 upsert합니다. Page parent FK는 모든 Page upsert 뒤 연결합니다.
5. 이 source/catalog가 소유한 연결과 Page별 사용 계약을 새 snapshot과 일치하도록 교체합니다.
6. snapshot에서 제거된 리소스를 비활성화하고 처리된 sourceRevision/hash/통계를 기록합니다.
7. 리소스·연결·Page별 사용 계약·observedRevision·성공 이력을 함께 commit합니다.

동일 commit 재실행은 중복 리소스나 관계를 만들지 않아야 합니다. 위 소유권 identity와
`(sourceId, catalogName, from, type, to)`에 unique constraint를 둡니다.
identity가 재등장하면 기존 내부 PK를 유지하며 재활성화합니다.
상세 diff 후 lock을 잡기 전에 상태가 달라지면 기존 계획을 재사용하지 않습니다.

Git SHA 자체는 대소 비교로 신구를 판단할 수 없습니다.
스케줄러가 주기적으로 최신 HEAD를 resolve하고 generation을 할당하며,
늦게 끝난 오래된 조회가 새 desiredRevision을 덮어쓰지 않도록 poll/예약 과정도 직렬화합니다.
여러 인스턴스는 DB lock/lease로 같은 source의 예약·적용을 조정합니다.

## 삭제와 장애

삭제는 **정상적으로 내려받고 검증한 새 snapshot에서 빠진 기존 관리 리소스**만 대상으로 합니다.
manifest에서만 제거하고 파일을 남기면 CI 실패입니다. 파일만 지워도 실패합니다.
남은 리소스가 삭제 대상을 참조해도 검증에 실패합니다.

v1 기본 삭제 방식은 soft deactivate입니다. 관련 관리 연결은 같은 트랜잭션에서 제거합니다.
비활성 리소스는 새 권한 판정/실행에서 사용할 수 없습니다.
DB 외부의 활성 정책 등에서 삭제 대상을 참조하면 자동 cascade 대신 전체 시도를 blocked 상태로 남깁니다.
먼저 의존 정책을 정리하거나 별도 마이그레이션을 완료한 뒤 재시도합니다.
영구 purge와 전체 카탈로그 제거는 이 프로토콜의 정상 동기화에 포함하지 않습니다.
빈 manifest가 전체 삭제를 유발하지 않도록 현재 규격에서 금지합니다.

| 상황 | 처리 |
| --- | --- |
| HTTP 오류, timeout, 파일 누락, YAML/스키마 오류 | DB 변경 없이 failed, 정상 revision 유지 |
| 참조 오류, 중복 경로, Page override 불일치 | DB 변경 없이 failed, 경로와 원인 기록 |
| 활성 정책 등 외부 참조로 삭제 불가 | DB 변경 없이 blocked, 영향 대상 기록 |
| DB 오류 또는 충돌 | 전체 rollback 후 새 snapshot/현재 상태로 재계획 |
| 같은 revision 재시도 | DB 실제 상태 비교 후 idempotent 반영 또는 no-op |
| 더 최신 revision 존재 | 오래된 적용 중단, 최신 desiredRevision 처리 |

실패 이력은 rollback된 데이터 트랜잭션 밖에서 별도 기록합니다.
운영 status는 `desiredRevision`, `observedRevision`, `contentSha256`,
마지막 성공 시각, 마지막 오류, 변경 건수, drift 여부를 포함합니다.
revision이 같아도 drift가 있으면 out of sync입니다.
모든 반영과 drift 검증이 성공한 상태만 synced로 표시합니다.

## 트리거와 롤백

주기적인 HEAD 조회가 기본 복구 경로입니다. 웹훅/수동 동기화는 같은 reconcile 작업을 요청합니다.
Config Server의 refresh 또는 Spring Cloud Bus 이벤트만으로 DB가 동기화되지는 않습니다.
master에 병합된 revision을 자동 반영할지, 별도 배포 승인을 둘지는 consumer 운영 설정에서 결정합니다.
이 저장소 CI에는 DB 연결 자격증명이나 동기화 API 호출을 넣지 않습니다.

운영 롤백은 문제가 된 커밋을 revert하는 PR을 병합해 **새 desiredRevision**을 만드는 방식입니다.
revert도 동일한 전체 검증과 외부 참조 검사를 거칩니다.
force push나 DB 수동 수정 없이 Git 이력과 적용 이력을 연결합니다.

## 소비자 완료 기준

- 동일 SHA 전체 조회, 실패 시 무변경, 같은 commit 재시도, DB drift 복구를 통합 검증합니다.
- 연결 제거와 리소스 비활성화의 원자성, 외부 참조 차단, 두 worker의 경합을 검증합니다.
- Page별 상속·subject 주입·응답 projection은 DB 적재와 별개로 실행 서버에서 검증합니다.
- 같은 Action의 Page별 override가 섞이지 않는지, 변경하지 않은 요청/응답을 상속하는지 검증합니다.
- snapshot/diff/오류를 운영자가 확인할 수 있어야 합니다. 비밀값이나 사용자 실제 데이터는 이력에 기록하지 않습니다.
