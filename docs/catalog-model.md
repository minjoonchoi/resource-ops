# 카탈로그 규격 v1

## 원본과 생성물

`openapi/<organization>/<service>.json`을 원본으로 커밋합니다. 조직 디렉터리는 한 단계이며
그 이름을 변환 없이 Service와 Endpoint의 `metadata.organization`에 넣습니다.
JSON 파일명에서 `.json`만 제거한 값을 Service의 `metadata.name`으로 사용합니다.
서비스명은 소문자 시작, 소문자·숫자·점·하이픈, 최대 128자이며 `-default` 접미사는 금지합니다.
같은 서비스명은 조직을 달리해도 중복될 수 없습니다. 출력 경로가 `services/<service>.yaml`이기 때문입니다.

파일 간 참조 식별키는 대상 정의의 `metadata.name`입니다. 리소스 identity는 `(kind, metadata.name)`이며
참조 필드가 대상 kind를 결정합니다. `organization`과 `title`은 식별키가 아닙니다.
조직 디렉터리 이동은 조직 정보 갱신, JSON 파일명 변경은 서비스 identity 변경으로 취급합니다.
서비스명 변경 시 관련 Action의 service 참조도 변경해야 합니다.

## Service와 Endpoint

하나의 생성 YAML에는 Service 문서 하나가 들어갑니다.

| 위치 | 생성 규칙 |
| --- | --- |
| `kind` | `Service` |
| `metadata.name` | JSON 파일명에서 확장자 제거 |
| `metadata.organization` | 원본의 조직 디렉터리명 |
| `metadata.title` | OpenAPI `info.title` |
| `spec.source` | 저장소 기준 OpenAPI 원본 경로 |
| `spec.openapi` | 파싱한 원본 OpenAPI 전체, 손실 없이 보존 |
| `spec.endpoints[]` | `paths`의 각 HTTP operation에서 생성한 metadata·method·path |

Endpoint의 `metadata.organization`은 Service와 같습니다. `metadata.name`은
`<service>.<소문자 method>.<SHA-256(path UTF-8)의 앞 16자리>`로 생성합니다.
`operationId`는 원문에 보존하며 필수 식별키로 사용하지 않습니다. 빠져 있거나 camelCase여도
가져올 수 있고, 제목·operationId가 바뀌어도 동일 서비스·method·path의 Endpoint identity는 유지됩니다.
3.2 확장 메서드는 `<service>.operation.<SHA-256(method + 공백 + path)의 앞 16자리>`를 사용하며
메서드 대소문자를 보존합니다. 해시 충돌로 identity가 중복되면 전체 snapshot 생성을 실패시킵니다.

request/response는 OpenAPI의 `parameters`, `requestBody`, `responses`, `content`, `schema`로 보존합니다.
`$ref`도 그대로 보존하고 **Service.spec.openapi를 참조 루트**로 해석합니다.
Endpoint metadata 목록에는 request/response를 중복 복사하지 않습니다.
DB snapshot을 만들 때 Endpoint 리소스를 추출하여 method/path, service 참조, OpenAPI operation을 저장합니다.
Service의 원문과 Endpoint의 operation을 함께 보관해야 재사용 schema를 해석할 수 있습니다.

OpenAPI 기본 규칙대로 path 공통 parameter를 operation parameter가 `(in, name)` 기준으로 덮어씁니다.
header 이름은 대소문자를 구분하지 않습니다. servers는 operation → path → 문서 순서로 상속하고,
아무것도 없으면 OpenAPI 기본 상대 주소 `/`를 보존합니다. 여러 서버와 server variables도 보존하며
하나의 base URL을 임의 선택하지 않습니다. security 역시 operation 설정 또는 문서 설정을 사용합니다.
실제 서버 선택·변수 치환·인증·상대 URL 기준은 소비자의 실행 설정 책임입니다.

Swagger 2.0도 같은 Service 구조에 원문을 보존합니다. body/formData·consumes/produces·서버 정보는
snapshot에서 adapter로 합성하며 세부 규칙은 [버전 호환성 문서](openapi-compatibility.md)를 따릅니다.

## Action과 참조

개발조직은 생성된 YAML을 확인한 뒤 `actions/<metadata.name>.yaml`을 직접 작성합니다.

```yaml
apiVersion: resource-ops/v1
kind: Action
metadata:
  name: members.detail.read
  title: 회원 기본 정보 보기
  organization: member-team
spec:
  service: member-api
  method: GET
  path: /v1/members/{memberId}
```

Action의 `metadata.organization`은 선택적인 담당조직 표시입니다. 자동 생성 Service/Endpoint는
원본 경로에서 조직이 반드시 결정됩니다. 조직 표시 자체로 권한이 부여되지는 않습니다.
Action에는 Endpoint ID, request, responses, field 제한을 작성하지 않습니다.
`service`는 **생성 Service의 metadata.name**을 참조하고 method/path는 직접 명세합니다.
서비스가 존재해야 하고 그 서비스의 operation과 method/path 및 경로 변수명이 정확히 일치해야 합니다.
다른 서비스의 동일 URL·path로 대신 매칭하거나 대소문자·trailing slash를 보정하지 않습니다.
동일 서비스에서 `/members/{id}`와 `/members/{memberId}`처럼 모호한 route도 거부합니다.
Page에서 아직 사용하지 않는 Action도 검증합니다. 여러 Action이 같은 API를 사용할 수 있습니다.

## Page의 sparse override

`pages/<metadata.name>.yaml`의 `spec.actions[]`에는 Action 참조와 필요한 변경분만 작성합니다.
`parent`는 상위 Page의 metadata.name 참조이며 순환을 허용하지 않습니다.

```yaml
apiVersion: resource-ops/v1
kind: Page
metadata:
  name: members
  title: 회원 관리
spec:
  path: /members
  actions:
    - action: members.directory.list
      overrides:
        request:
          parameters:
            - in: query
              name: organizationCode
              source: subject.organization.code
            - in: query
              name: size
              value: 20
        responses:
          '200':
            fields: [/items/*/id, /items/*/nickname, /total]
```

- 생략한 요청·응답·상태코드는 원본 계약을 상속합니다. 빈 overrides/parameters/fields를 작성하지 않습니다.
- 요청 parameter는 `(in, name)` 기준으로 `source` 또는 `value` 중 하나만 지정합니다.
- `source`는 `subject.id`, `subject.email`, `subject.nickname`, `subject.organization.code`입니다.
- 고정값은 OpenAPI 버전에 맞춰 원본 schema로 검증합니다. subject 값은 실행 시에도 제약을 검증해야 합니다.
- override하지 않은 parameter와 requestBody는 호출자 입력을 사용합니다. YAML에 `source: input`을 반복하지 않습니다.
- 원본 required, serialization, type, enum, range 등 계약은 그대로 유지합니다. method/path/schema를 Page에서 바꾸지 않습니다.
- 원본 `schema` parameter에 대한 주입만 지원합니다. `content` parameter 주입 및 전송/인증 header override는 거부합니다.
- 응답 `fields`는 해당 상태코드의 선택 목록 전체를 교체합니다. 지정하지 않은 오류 응답은 원본 전체를 상속합니다.
- HTTP 코드, 범위 코드(`2XX` 등), `default`를 원본 키 그대로 사용할 수 있습니다. 상태코드는 YAML 문자열로 작성합니다.

응답 선택은 정확히 하나의 `application/json` 또는 `application/*+json` media type에 schema가 있을 때 지원합니다.
필드는 JSON Pointer escaping(`~1`: `/`, `~0`: `~`)을 사용하며 array의 요소만 `*`로 선택합니다.
`/items/*/id`는 모든 배열 요소의 id입니다. object/array 전체 대신 개별 leaf를 선택합니다.
정적인 properties/items와 내부 `$ref`를 따라가며 nullable scalar를 지원합니다.
`allOf`/`oneOf`/`anyOf` 등 복합 스키마, boolean/untyped schema, 제약 sibling을 가진 3.1/3.2 `$ref`에 대한
projection은 안전하게 결론 낼 수 없어 거부합니다. 원본 보존이나 override 없는 상속은 가능합니다.

실행 서버는 Page·Action 권한과 `(Page, Action)` 사용 맥락을 확인하고 요청 입력/주입값을 검증한 뒤 호출합니다.
upstream 응답을 OpenAPI 계약으로 검증한 후 fields를 적용하며 부모 구조·배열 순서·요소 수를 보존합니다.
매칭되지 않은 응답이나 스키마 위반 응답은 일반 오류로 처리합니다. CLI는 API를 호출하지 않습니다.
Action만으로 Page별 필드 제한을 결정할 수 없으므로 Page 밖 호출 정책은 별도 정의해야 합니다.

## Manifest와 snapshot

`catalog/manifest.yaml`은 생성된 service 파일과 직접 작성한 actions/pages 파일을 정렬한 자동 목록입니다.
로컬 `generate_services.py <organization>/<service>`는 선택한 서비스와 현재 파일 목록만 갱신하며, PR은 서비스 YAML을 새로 만들거나 Action/Page가 추가·삭제될 때 목록을 갱신합니다.
기존 서비스 YAML은 PR에서 재생성 결과와 바이트 단위 비교만 하며 덮어쓰지 않습니다.
OpenAPI 변경·이동 시 지정 대상 명령으로 갱신한 결과까지 커밋합니다.
원본 삭제 후 생성물 정리·전체 재생성은 명시적인 `--all` 유지보수 명령으로 수행합니다.
직접 작성한 Action/Page는 생성기가 수정하거나 삭제하지 않습니다.

| 관계 | 방향 |
| --- | --- |
| `providedBy` | Endpoint → Service |
| `invokes` | Action → method/path 대조로 찾은 Endpoint |
| `uses` | Page → Action, overrides 속성 보존 |
| `childOf` | Page → 상위 Page |

snapshot의 `resources`에는 Service, 추출된 Endpoint, Action, Page를 포함합니다.
`pageActionUsages`의 key는 Page/Action이고 `endpoint`는 매칭된 Endpoint.metadata.name입니다.
`effective`는 service의 name/servers, method/path/security, request의 parameters/body, responses를 포함합니다.
parameter/body에는 `source` 또는 `value`, 명시한 response에는 `fields`가 추가됩니다.
content/schema/headers/links 등 원본 응답 속성을 보존하고 `$ref` 루트는 연결된 Service.spec.openapi입니다.
이 파생 계약은 독립적인 OpenAPI 문서가 아니며 응답 schema는 projection 전 upstream 검증용입니다.

## 검증 경계

Swagger 2.0과 OpenAPI 3.0.x/3.1.x/3.2.x를 각각의 표준 검증기로 검사합니다. JSON 중복 키·NaN/Infinity·16 MiB 초과 원본을 거부합니다.
동일 커밋에서 오프라인 재현하기 위해 외부 파일/URL `$ref`는 bundle 후 입력해야 합니다.
내부 JSON Pointer `$ref`와 재귀 schema는 보존하지만 `$id`, anchors, dynamic refs는 지원하지 않습니다.
callbacks/webhooks의 별도 Endpoint 등록은 현재 범위 밖입니다.
callbacks/webhooks는 원문에 보존하며 `paths`의 inbound HTTP operation만 Endpoint로 등록합니다.

YAML 중복 키·비문자열 map key·anchors/aliases·다중 문서·32 MiB 초과 파일·symlink·경로 이탈을 거부합니다.
Config Server가 내용을 치환하지 않도록 `${...}`를 금지하고 `*-default.yaml`도 금지합니다.
빈 OpenAPI 목록은 전체 삭제로 취급하지 않습니다. 알 수 없는 카탈로그 필드는 실패합니다.
검증은 선언 간 일치 여부를 검사하며 실제 API 동작, DB 외부 참조, 운영 서버의 정책 판정은 별도 검증 대상입니다.

표준 및 사용 라이브러리: [OpenAPI 3.0](https://spec.openapis.org/oas/v3.0.3),
[OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0),
[openapi-spec-validator](https://openapi-spec-validator.readthedocs.io/en/latest/python.html).
