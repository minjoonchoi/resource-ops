export const resourceCommit='36ce08baadde9e8d275d76fcded70140d4bf2553';
export const orionCommit='966c449013273553c7912f74b4f02945c048396c';
export const evidence=[
 {title:'resource-ops · 카탈로그 모델',repo:'resource-ops',path:'docs/catalog-model.md',sha:resourceCommit,summary:'Service / Action / Page, (kind, metadata.name), Action의 endpoint·plugins, Page별 요청·응답 규칙'},
 {title:'resource-ops · DB 동기화 계약',repo:'resource-ops',path:'docs/synchronization.md',sha:resourceCommit,summary:'전체 snapshot 트랜잭션, soft deactivate, drift 복구, Git revert를 통한 롤백'},
 {title:'Orion · YAML 화면 계약',repo:'orion',path:'docs/screens/18-yaml-gitops-contract.md',sha:orionCommit,summary:'제품 UI 구현됨. 운영 API·DB·Gateway 통합은 미완료로 명시'},
 {title:'Orion · 정의 파서',repo:'orion',path:'src/features/definition-contract/model.ts',sha:orionCommit,summary:'domain.actions / workspace.pages 등을 읽는 파서. 이 파일에서 Task / Capability 분기 미확인'},
 {title:'Orion · 리소스 동기화 모델',repo:'orion',path:'src/features/resource-sync/model.ts',sha:orionCommit,summary:'ResourceBundle v1alpha1, actions/pages 등 기존 유형. Task / Capability 열거 없음'}
];
export const comparisons=[
 {topic:'파일 탐색',old:'services/** · actions/** · pages/**',next:'platform/<platform>/<workspace>/<domain>/**.yaml · service/<organization>/**.yaml',state:'목표 규칙',note:'현재 resource-ops 트리와 다릅니다. 신규 탐색기와 이관 정책이 필요합니다.'},
 {topic:'리소스 식별',old:'(kind, metadata.name) · 동기화 서버는 (source-id, kind, name)',next:'Page / Task / Capability 전역 키 + 조직을 포함한 Service 전역 키',state:'목표 규칙',note:'기존 ID와 새 전역 키의 매핑, 참조 이관은 미확인입니다.'},
 {topic:'실행 단위',old:'Action → Service 이름 + method/path로 단일 endpoint 참조',next:'Task / Capability를 별도 유형으로 수집',state:'미확인',note:'Task ↔ Capability ↔ Page 관계, 실행 단위 및 cardinality는 제공된 계약에 없습니다.'},
 {topic:'요청 · 응답',old:'resource-ops Page의 Action 사용 정의에서 주입·scope·200 응답 필드/마스킹',next:'Task / Capability 중 규칙을 소유할 유형 미정',state:'미확인',note:'새 구조에 기존 의미를 자동으로 옮기지 않습니다. Orion Action 필드 모델과도 별도 비교가 필요합니다.'},
 {topic:'실행 플러그인',old:'Action.spec.plugins 단일 배열 · confirm / history',next:'새 구조의 플러그인 위치와 실행 순서 미정',state:'미확인',note:'승인 조건, 실행 요청 고정, 이력 필드 선택을 보존하는 어댑터가 필요합니다.'},
 {topic:'해시 · 리비전',old:'정규화 CatalogSnapshot의 content-sha256 · 전체 Git SHA',next:'파일 원문 UTF-8 SHA-256 · 성공한 변경 동기화의 파일 리비전',state:'차이 확인',note:'정규화 문서 해시와 원문 해시는 서로 다른 값입니다. 주석·공백 변경도 원문 변경입니다.'},
 {topic:'실패 단위',old:'전체 snapshot 검증 및 단일 DB 트랜잭션 · 실패 시 전체 rollback',next:'독립 파일 단위 성공 / 실패 추적을 시뮬레이션',state:'차이 확인',note:'이 콘솔의 부분 반영은 설계 가정입니다. 참조가 있는 운영 카탈로그의 원자성 계약은 미확인입니다.'},
 {topic:'삭제 · 복원',old:'유효한 전체 트리에서 누락된 리소스 soft deactivate · 동일 identity 재활성',next:'파일 부재 → 삭제 리비전, 재등장 → 복원 리비전',state:'목표 규칙',note:'감사 이력을 보존하는 논리 삭제로 표현합니다. 외부 정책 참조 조회와 차단은 미연동입니다.'},
 {topic:'선택 롤백',old:'Git revert PR 병합으로 새 desired revision 생성',next:'파일의 기존 리비전으로 적용 포인터 전환 · 별도 감사 이벤트',state:'차이 확인',note:'Git 원문은 유지됩니다. 원문과 적용 상태가 다르면 드리프트로 표시하고 재동기화 시 기존 최신 리비전을 재사용합니다.'},
 {topic:'Orion 소비자',old:'확인한 모델은 Action / Page 및 ResourceBundle 중심',next:'Task / Capability 수용·권한 평가·Gateway 실행',state:'미확인',note:'직접 호환을 보장할 수 없습니다. 운영 API·DB·Gateway 통합은 Orion 문서에서도 미완료입니다.'}
];
