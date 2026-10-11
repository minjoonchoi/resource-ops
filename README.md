# resource-ops

서버, API 엔드포인트, 업무 액션, 페이지를 YAML로 정의하는 GitOps 카탈로그 저장소입니다.
Spring Cloud Config Server가 이 저장소의 특정 Git 커밋을 제공하고, 별도 동기화 서버가
전체 카탈로그를 검증한 뒤 리소스와 연결 관계를 DB에 반영합니다.

## 구성과 구현 범위

| 구성 | 역할 | 이 저장소의 상태 |
| --- | --- | --- |
| YAML 카탈로그 | 리소스 원본과 연결 참조 | 예제 8개 구현 |
| JSON Schema / 검증 CLI | 형식, 참조, Page별 Endpoint override 검증 | 구현 |
| 정규화 snapshot | 리소스·관계·Page별 최종 사용 계약을 담은 DB 중립 JSON | 로컬 생성 가능 |
| GitHub Actions | PR / master 변경 검증 | 워크플로 정의 |
| Cloud Config Server | 커밋별 YAML 제공 | 외부 서버 설정 예제와 조회 계약 제공 |
| DB 동기화 서버 | diff, 트랜잭션 반영, 이력, 재시도 | 외부 서버가 구현할 계약 문서 제공 |

현재 데이터는 `example.invalid`를 사용하는 **가상 회원 서비스 예제**입니다.
실제 서버 주소·API 계약으로 교체하고 동기화 서버를 연결해야 운영 DB에 적용됩니다.

## 리소스 모델

| 리소스 | 정의 | 다른 리소스 참조 |
| --- | --- | --- |
| `Server` | API를 제공하는 논리 서버와 base URL | 없음 |
| `Endpoint` | 서버의 HTTP method/path와 원본 요청·응답 계약 | `spec.server` → Server 1개 |
| `Action` | 업무/권한 단위와 사용할 Endpoint | `spec.endpoint` → Endpoint 1개 |
| `Page` | 화면 경로와 Action별 Endpoint override | `spec.actions[].action` → Action 여러 개, `spec.parent` → 상위 Page |

Endpoint가 원본 요청·응답 계약을 정의하고 Action은 Endpoint 참조만 가집니다.
실제 페이지의 사용 방식은 `Page.spec.actions[].overrides`에 **원본에서 달라지는 부분만** 작성합니다.
override를 생략하면 Endpoint를 그대로 상속하며, parameter는 `(in, name)`, 응답은 상태코드별로 적용합니다.
하나의 Endpoint를 여러 Action이 참조할 수 있고, Page와 Action은 다대다입니다.
각 참조가 연결의 원본이고, DB 연결 데이터는 여기서 도출합니다.
별도 관계 YAML에 같은 연결을 반복해서 쓰지 않습니다.

예제에서 같은 `members.detail.read` Action을 회원 목록 Page는 ID·닉네임만,
상세 Page는 조직코드까지 선택하도록 사용합니다. `members.contact.read` 사용 정의는 연락처를 선택합니다.
회원 목록 Page의 `members.directory.list` 사용 정의는 조직코드를 주입하고 페이지 크기를 20으로 고정합니다.
변경하지 않는 page parameter와 오류 응답은 YAML에 반복 작성하지 않습니다.

이 연결은 **구조와 사용 계약**입니다. Page에 Action이 연결되어 있다고 해서
해당 Page의 접근 권한만으로 Action 실행 권한까지 부여되지는 않습니다.
페이지에서 실행할 때 서버가 `(Page, Action)` 사용 정의를 확인하고 해당 override를 적용합니다.
Action 자체에는 요청·응답 필드 제한이 없으며, Page의 override를 다른 페이지에 전역 적용하지 않습니다.
직접 Endpoint 허용 정책과 Action에서 파생된 허용은 권한 서버에서 구분합니다.
Workspace·정책·역할·사용자·서비스 어카운트 할당은 현재 카탈로그 범위에 포함하지 않습니다.

## 파일 위치

| 경로 | 내용 |
| --- | --- |
| `catalog/manifest.yaml` | 동기화할 리소스 파일의 명시적 목록 |
| `catalog/servers/*.yaml` | Server |
| `catalog/endpoints/*.yaml` | Endpoint |
| `catalog/actions/*.yaml` | Action |
| `catalog/pages/*.yaml` | Page |
| `schemas/catalog.schema.json` | v1 문서 스키마 |
| `scripts/catalog.py` | 전체 검증 및 snapshot 생성 |
| `resource-catalog.yaml` | Config Environment API용 manifest 위치/버전 안내 |
| `examples/config-server.application.yaml` | Config Server 자체 설정 예제 |
| `tests/test_catalog.py` | 정상 및 오류 데이터 검증 |

## 로컬 검증

Python 3.12 이상을 사용합니다. Python은 이 저장소의 검증 도구에만 필요하며
Config Server나 동기화 서버의 구현 언어를 제한하지 않습니다.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/catalog.py
.venv/bin/python scripts/catalog.py --snapshot dist/catalog.snapshot.json
.venv/bin/python -m unittest discover -s tests -v
```

snapshot은 원본 리소스와 `providedBy`, `invokes`, `uses`, `childOf` 관계를 포함합니다.
`uses` 관계는 Page의 override를 보존하고, `pageActionUsages`는 Endpoint에 override를 적용한 최종 사용 계약입니다.
`dist/`는 Git에 저장하지 않습니다. 실제 동기화 서버는 전달받은 커밋 SHA와 함께
검증 결과를 기록해야 합니다. CLI 자체는 네트워크 조회나 DB 쓰기를 수행하지 않습니다.

## 변경 절차

1. 작업 브랜치에서 YAML을 생성·수정하고 `manifest.yaml` 목록을 갱신합니다.
2. 전체 검증을 실행합니다. 참조 대상과 참조하는 파일은 같은 PR에서 변경합니다.
3. PR에서 원본 계약, Page별 Action 사용 방식, 관계 변경 및 삭제 영향을 검토합니다.
4. PR을 `master`에 병합합니다. 동기화 서버가 병합된 HEAD의 커밋 SHA를 확정합니다.
5. 해당 SHA의 manifest와 모든 리소스를 읽고 전체 검증·diff 후 한 트랜잭션으로 반영합니다.
6. 실패하면 마지막 정상 상태를 유지합니다. 롤백은 이전 변경을 revert한 새 커밋으로 진행합니다.

워크플로를 필수 PR 검사로 지정하는 branch protection과 동기화 서버 실행은 별도 운영 설정입니다.
현재 워크플로는 검증만 수행하며 DB 동기화를 직접 트리거하지 않습니다.

## 상세 문서

- [YAML 규격과 Page별 Action 사용 계약](docs/catalog-model.md)
- [Spring Cloud Config 연결과 커밋 고정 조회](docs/config-server.md)
- [DB 동기화 계약, 삭제, 실패, 롤백](docs/synchronization.md)
