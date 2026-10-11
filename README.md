# resource-ops

조직별 OpenAPI JSON에서 서비스·엔드포인트 카탈로그를 생성하고, 개발조직이 업무(Action)와
화면별 사용 방식(Page)을 YAML로 정의하는 GitOps 저장소입니다. Spring Cloud Config Server는
특정 커밋의 YAML을 제공하고, 별도 동기화 서버가 전체 검증 후 DB에 반영합니다.

## 파일과 작성 책임

| 경로 | 작성자 / 내용 |
| --- | --- |
| `openapi/<organization>/<service>.json` | 개발조직: 서비스의 OpenAPI 원본 |
| `services/<service>.yaml` | 자동 생성: Service, Endpoint 목록, OpenAPI 원문 |
| `actions/<metadata.name>.yaml` | 개발조직: 업무와 서비스 참조·method·path |
| `pages/<metadata.name>.yaml` | 화면 담당: Action 참조와 필요한 override |
| `scripts/generate_services.py` | 로컬·CI 공통 생성기 및 생성물 비교 |
| `scripts/catalog.py` | 전체 카탈로그 검증과 DB 중립 snapshot 생성 |

예제 `openapi/member-team/member-api.json`은 `services/member-api.yaml`이 됩니다.
Service와 그 안의 모든 Endpoint에 `metadata.organization: member-team`을 넣으며,
Service의 `metadata.name`은 JSON 파일의 확장자를 뺀 `member-api`입니다.
조직이 달라도 같은 서비스 파일명은 사용할 수 없습니다.
Service.spec에는 endpoints와 openapi만 저장하며 source 경로를 중복 저장하지 않습니다.

서비스 YAML은 `spec.openapi`에 원본 OpenAPI를 보존하고 `spec.endpoints`에 엔드포인트
식별자·설명·조직·method·path를 생성합니다. request/response를 별도 형식으로 다시 작성하지 않습니다.
`servers`, `components`, `$ref`, `content`, security 등 원본 계약을 함께 보존합니다.

Endpoint의 `metadata.name`은 `member-api.GET./v1/members/{memberId}`처럼
`<서비스명>.<메소드>.<원본 경로>`이며 경로의 `/`, `.`, 대소문자 등을 그대로 보존합니다.
`metadata.description`에는 operation의 summary를 우선 가져오고, 없거나 공백이면 description을
사용합니다. 둘 다 없으면 설명 필드는 생략하며 원본 OpenAPI 내용은 그대로 보존합니다.

Catalog kind와 manifest는 두지 않습니다. `services/`, `actions/`, `pages/`에서 YAML을 직접 탐색하며,
리소스 정의는 Service·Action·Page와 Service에서 추출하는 Endpoint로 구성합니다.

## 개발조직의 Action 작성

먼저 생성된 서비스 YAML의 `metadata.name`과 엔드포인트 method/path를 확인합니다.
`actions/members.contact.read.yaml`처럼 업무를 직접 추가합니다. 생성기는 Action을 만들거나 수정하지 않습니다.

```yaml
apiVersion: resource-ops/v1
kind: Action
metadata:
  name: members.contact.read
  title: 회원 연락처 보기
  organization: member-team
spec:
  endpoint:
    service: member-api
    method: GET
    path: /v1/members/{memberId}
  plugins:
    - name: confirm
      config:
        pool:
          users: [reviewer-a, reviewer-b]
          organizations: [security-team]
        count: 2
        execution: requester
    - name: history
      config:
        request:
          parameters:
            - in: path
              name: memberId
        responses:
          '200':
            fields: [/id, /email]
```

`spec.endpoint.service`는 **Service.metadata.name** 참조입니다. JSON의 `info.title`, `operationId`, 조직명,
파일 경로나 URL을 서비스 참조 키로 사용하지 않습니다. Endpoint ID를 Action에 작성하지 않으며,
서비스·method·path로 대조한 Endpoint의 `metadata.name`을 DB 연결 키로 사용합니다.
Page의 Action 참조 및 상위 Page 참조도 대상의 `metadata.name`을 사용합니다.

Action은 업무/권한 단위와 실행 전후 플러그인 연결을 정의합니다.
`spec.endpoint`에 호출 대상을, `spec.plugins` 단일 배열에 confirm/history를 연결합니다.
confirm은 `pool.users`에 명시한 닉네임과 `pool.organizations`의 소속 사용자를 합친 후보 중
서로 다른 `count`명의 확인을 요구합니다. `execution: requester`는 조건 충족 후
요청자가 실행하고, `automatic`은 조건 충족 시 자동 실행합니다.
`plugins`에 `name: history`만 연결하면 해당 Action의 전체 이력을 기록하도록 선언합니다.
events 설정 없이 확인 과정과 호출 과정의 모든 이벤트가 포함됩니다. 선택적인 `config.request`와
`config.responses`로 실제 실행 요청/응답에서 저장할 필드를 고릅니다. 생략한 값은 저장하지 않습니다.
Action.metadata.name과 실행 요청 ID를 기준으로 각 이벤트의 행위자·행위·시각·결과를 남기며,
확인 대기/거절/취소로 endpoint를 호출하지 않은 경우도 기록합니다. 배열 순서와 무관하게 수집은 Action 시작부터 수행합니다.
플러그인은 선택 사항이며 [실행 계약과 검증 범위](docs/catalog-model.md#action-실행-플러그인)를 따릅니다. 요청·응답 변경은 `Page.spec.actions[].overrides`에
원본에서 달라지는 부분만 작성합니다. 같은 Action도 Page별 사용 계약은 독립적입니다.
관계가 존재한다고 실행 권한이 자동 부여되는 것은 아니며, 실행 서버의 권한 확인이 필요합니다.

## 로컬 생성과 검증

Python 3.12 이상에서 실행합니다.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 지정한 JSON 하나만 변환: openapi/member-team/member-api.json
.venv/bin/python scripts/generate_services.py member-team/member-api
# 지정 서비스의 생성 결과 비교
.venv/bin/python scripts/generate_services.py member-team/member-api --check
# CI / 명시적인 전체 점검
.venv/bin/python scripts/generate_services.py --all --check
.venv/bin/python scripts/catalog.py --snapshot dist/catalog.snapshot.json
.venv/bin/python -m unittest discover -s tests -v
```

새 OpenAPI를 추가한 뒤 스크립트로 서비스 YAML을 생성하고, 이를 보고 Action을 작성한 다음
전체 검증을 실행합니다. 별도 파일 등록 없이 원본·생성물·Action을 함께 커밋합니다.
기존 OpenAPI 변경/이동도 같은 대상 명령을 실행하여 생성물 변경과 함께 커밋합니다.
선택 인자 없는 실행은 오류이며 전체 서비스 갱신·삭제 원본 정리는 명시적인 `--all` 실행으로 수행합니다.
단일 대상 변환은 다른 JSON 내용을 파싱하거나 다른 서비스 YAML을 수정·삭제하지 않습니다.
`dist/` snapshot은 Git에 저장하지 않습니다.

## PR 자동화

동일 저장소의 PR에서는 `--all --create-missing`을 실행합니다.

| 상태 | Workflow 처리 |
| --- | --- |
| 원본이 있고 서비스 YAML이 없음 | 생성 후 전체 검증, 같은 PR 브랜치에 봇 커밋 |
| 기존 서비스 YAML이 생성 결과와 동일 | 비교만 수행, 파일 수정·불필요한 커밋 없음 |
| 기존 서비스 YAML이 다름 | 덮어쓰지 않고 실패, 로컬 재생성 명령 안내 |
| 원본 없이 생성 YAML만 남음 | 실패, 원본 삭제 의도와 로컬 재생성 결과 확인 필요 |
| Action/Page 추가·삭제 | 디렉터리에서 자동 발견하여 전체 검증; 생성물 변경 없음 |
| Fork/Dependabot PR, master push, 수동 실행 | `--all --check`만 실행; 생성물을 미리 커밋해야 함 |

서비스 YAML은 주석·포맷까지 결정적인 결과와 비교합니다. JSON의 object key 순서나 공백은
생성 결과에 영향을 주지 않습니다. 기존 YAML 불일치는 임의 수정인지 미재생성인지 자동 단정하지 않고
모두 실패시킵니다.

봇은 검증·테스트 완료 후 `services/`만 커밋하며 force push하지 않습니다.
검증한 최종 커밋에 `catalog/validate` 상태를 기록하여 봇 push 후 추가 CI 실행에 의존하지 않습니다.
[GitHub 토큰 정책](https://docs.github.com/en/actions/concepts/security/github_token)에 따라
봇 갱신 후 후속 PR workflow가 승인을 기다릴 수도 있으므로 검증은 현재 실행 안에서 완료합니다.
쓰기 가능한 Actions 토큰이 필요합니다. 조직 정책이 이를 제한하면 생성물을 로컬에서 커밋합니다.
Fork에서 쓰기 권한을 얻기 위한 `pull_request_target`은 사용하지 않습니다.
필수 검사 및 branch protection은 별도 운영 설정이며 이 PR에서 변경하지 않습니다.

## 지원 범위와 연결

Swagger **2.0**, OpenAPI **3.0.x / 3.1.x / 3.2.x JSON**을 버전별 검증기와 adapter로 처리합니다.
버전은 최상위 `swagger`/`openapi`에서 판별하고 원문을 보존합니다. 문서 내부 JSON Pointer `$ref`를 지원하며
외부 refs는 bundle해야 합니다. `$id`·anchor·dynamic ref는 현재 범위 밖입니다.
[버전별 공식 문서·호환성·검증 절차](docs/openapi-compatibility.md)와 루트 [AGENTS.md](AGENTS.md)에
특정 파일 변환 및 호환성 작업 지침을 두었습니다.
OpenAPI 원본은 보존하지만 Page의 응답 필드 선택은 단일 JSON media type의 명확한 leaf schema만 지원합니다.
복합 스키마와 여러 media type의 projection은 추측하지 않고 실패합니다.

현재 예제는 가상 서비스 1개, 엔드포인트 2개, Action 3개, Page 2개이며
snapshot은 리소스 8개·관계 10개·Page 사용 계약 4개를 포함합니다.
실제 Config Server/DB reconciler 및 migration은 별도 구현이 필요합니다.

- [카탈로그 규격·OpenAPI 보존·Page override](docs/catalog-model.md)
- [Config Server에서 같은 SHA의 YAML 조회](docs/config-server.md)
- [DB 동기화·삭제·실패·롤백 계약](docs/synchronization.md)
