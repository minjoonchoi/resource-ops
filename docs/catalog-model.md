# YAML 카탈로그 규격 v1

## 문서와 식별자

각 파일은 YAML 문서 하나이며 다음 공통 필드를 사용합니다.

```yaml
apiVersion: resource-ops/v1
kind: Action
metadata:
  name: members.detail.read
  title: 회원 기본 정보 보기
spec:
  service: member-api
  method: GET
  path: /v1/members/{memberId}
```

- 리소스의 안정적 식별자는 `(kind, metadata.name)`입니다. 표시용 `title`과 선택 `description`은 변경 가능합니다.
- `name`은 소문자로 시작하고 소문자·숫자·점·하이픈을 사용합니다. 최대 128자입니다.
- 파일명은 `metadata.name.yaml`, 디렉터리는 kind별 복수형으로 고정합니다.
- Config Server의 profile 파일 선택과 충돌하는 `-default` 이름 접미사는 금지합니다.
- 이름 변경은 삭제+생성입니다. 파일과 모든 참조를 함께 변경하고 삭제 영향을 검토합니다.
- 파일 간 참조 식별키는 대상 정의의 `metadata.name`입니다. 파일 경로·표시용 title·URL은 참조 키로 사용하지 않습니다. 참조 필드가 대상 kind를 결정하므로 다른 kind의 같은 이름과 혼동하지 않습니다.
- Endpoint.server, Action.service와 Page.actions[].action/parent 참조는 문자열 이름을 사용합니다. Action의 method/path는 직접 작성합니다.
- 알 수 없는 필드는 실패합니다. 확장은 스키마·검증기·소비자·문서를 함께 변경합니다.
- wire 필드명은 원본 그대로 사용합니다. `organization_code`와 `organizationCode`를 자동 변환하지 않습니다.
- 환경·리전은 리소스 identity에 포함하지 않습니다. 현재 v1은 공통 카탈로그 하나이며 프로파일별 오버레이를 지원하지 않습니다.

## Server와 Endpoint

`Server.spec.baseUrl`은 논리 서버의 URL입니다. prefix 경로를 포함할 수 있지만 끝에 `/`를 붙이지 않습니다.
호출 URL은 `baseUrl + Endpoint.spec.path`입니다. 사용자정보·비밀번호·query·fragment는 URL에 넣지 않습니다.
서버 프로세스나 Pod 인스턴스마다 리소스를 만들지 않습니다.

Endpoint에는 `server`, `method`, `path`, `request`, `responses`가 필요합니다.
`server + method + path`는 중복될 수 없습니다. `/members/{id}`와 `/members/{memberId}`도 같은 경로로 취급합니다.

| 위치 | 형태 | 규칙 |
| --- | --- | --- |
| `request.parameters` | `in`, `name`, `required`, `schema` 배열 | `in`: path/query/header/cookie |
| `request.body` | 선택 `required`, `schema` | JSON body 계약 |
| `responses` | HTTP 상태코드 → `description`, `schema` | 상태코드는 `"200"`처럼 문자열로 작성 |

path의 모든 `{parameter}`는 required path parameter와 정확히 대응해야 합니다.
header 이름은 대소문자를 구분하지 않고, 나머지 parameter 이름은 구분합니다.
Authorization, Proxy-Authorization, Host, Cookie header는 전송 계층이 관리하므로 parameter로 정의하지 않습니다.
개별 cookie는 `in: cookie`로 정의합니다. Parameter는 v1에서 null이 아닌 scalar만 지원합니다.
복합 값은 JSON body에 정의하며, parameter serialization은 각 위치의 HTTP 인코딩을 적용합니다.

`schema`는 JSON Schema 2020-12 중 명시적인 타입을 사용하는 제한된 부분집합입니다.
object는 `properties`와 `additionalProperties: false`, array는 `items`를 반드시 선언합니다.
scalar 타입, `required`, `enum`, `const`, 숫자 범위, 문자열 길이, 배열 길이를 지원합니다.
`$ref`, `allOf`/`oneOf`/`anyOf`, 동적 키, nullable 타입 조합, multipart와 binary는 v1 범위 밖입니다.
컨테이너의 required 목록은 실제 선언된 property만 가리킬 수 있습니다.
확장 시 소비자가 처리할 수 없는 키워드를 조용히 통과시키지 않습니다.

## Action과 Page별 사용 정의

Action의 `spec.service`는 Server 이름을 참조하고, `method`와 `path`는 직접 명시합니다.
서비스 주소는 참조한 `Server.spec.baseUrl`에서 가져오며 Action에 중복 작성하지 않습니다.
호출 URL은 참조한 Server의 `baseUrl + Action.spec.path`입니다. `endpoint: members.get` 같은 ID 참조는 허용하지 않습니다.
요청·응답 필드 설정은 Action에 두지 않습니다.
여러 Action이 같은 API를 업무/권한 단위로 명시할 수 있습니다.
실제 화면에서 어떻게 사용할지는 `Page.spec.actions[]`에 정의합니다.

현재 `Server` 리소스가 API 제공 서비스의 등록 정의입니다. method/path는 가독성을 위해 직접 작성하며
검증 스크립트가 다음과 같이 불일치를 차단합니다.

| Action 필드 | 대조 대상 | 검증 |
| --- | --- | --- |
| `service` | Server.metadata.name | 참조한 서비스가 등록되어 있어야 함 |
| `method` + `path` | 같은 Server의 Endpoint.method/path | 유효한 Endpoint 하나와 정확히 일치 |

서비스명으로 범위를 제한한 후 method/path를 대조합니다. 다른 서비스의 동일 경로나 동일 base URL로 대신 매칭하지 않습니다.
URL, HTTP 메서드, path 대소문자, trailing slash를 임의 정규화하거나 오타를 자동 보정하지 않습니다.
경로의 `{memberId}`를 `{id}`로 바꾸는 것도 불일치입니다. Page override의 parameter 이름과 일관되어야 하기 때문입니다.
같은 서비스의 중복 route는 먼저 거부하므로 매칭 결과가 모호해지지 않습니다.
어떤 Page에도 연결되지 않은 Action도 전체 검증 대상입니다.

검증 오류는 Action 파일과 문제 필드를 표시합니다. 예를 들어 미등록 서비스는
`spec.service: unregistered service`와 서비스명을, 존재하지 않는 경로는
`no registered Endpoint`와 서비스·method·path를 표시합니다.
이는 등록 명세 간 일치 검증이며 실제 서버로 API 호출을 실행하지 않습니다.
Endpoint method/path를 바꾸면 관련 Action 직접 명세도 같은 PR에서 함께 수정해야 합니다.
서비스 주소는 Server에서만 변경하며, 참조한 모든 Page 사용 계약에 재계산되어 반영됩니다.
Endpoint 이름만 바뀌고 서비스·method·path가 같다면 Action 수정 없이 새 이름으로 관계가 도출됩니다.

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
          "200":
            fields: [/items/*/id, /items/*/nickname, /total]
    - action: members.detail.read
```

이 예제는 목록 조회의 조직코드·size·200 응답만 변경합니다.
page parameter와 400 응답은 Endpoint 그대로이며 별도 입력 정의가 필요 없습니다.
두 번째 사용 정의는 override가 없어 `members.get`의 원본 요청·응답 전체를 상속합니다.
실제 카탈로그 파일에는 같은 Action을 Page별로 다르게 선택하는 예제가 들어 있습니다.

| 위치 | 적용 규칙 |
| --- | --- |
| `overrides` 생략 | Endpoint 원본 계약 전체 상속 |
| `overrides.request.parameters` | `(in, name)`에 해당하는 parameter의 값 출처만 교체 |
| request parameter 생략 | 원본 required/type/range 유지, 호출자 입력 사용 |
| request body | Endpoint 원본 schema/required 유지, 호출자 입력 사용 |
| `overrides.responses."200".fields` | 해당 상태코드의 응답 필드 선택 목록을 교체 |
| 응답 상태코드 생략 | 해당 상태코드의 원본 응답 전체 상속 |

배열 전체를 재귀 merge하거나 `fields`를 원본 필드와 합집합으로 합치지 않습니다.
변경하는 parameter/status만 지정하며, 생략은 삭제를 뜻하지 않습니다.
빈 `overrides`, 빈 parameter/response override는 쓰지 않고 해당 키를 생략합니다.
Page override로 Action의 서비스·method·path나 Endpoint 원본 schema를 바꿀 수 없습니다.
호출 대상 변경은 등록 정의와 Action 직접 명세를 함께 수정하거나 다른 API를 명시한 Action으로 표현합니다.

## Page override의 요청 생성

`overrides.request.parameters`에서 다음과 같이 기본 호출자 입력을 변경할 수 있습니다.

| 표현 | 의미 |
| --- | --- |
| `source: subject.id` | 인증된 주체의 문자열 ID |
| `source: subject.email` | 인증된 주체의 이메일 |
| `source: subject.nickname` | 인증된 주체의 닉네임 |
| `source: subject.organization.code` | 요청 맥락에서 검증된 주체의 조직코드 하나 |
| `value: 20` | 카탈로그에 정의한 고정값 |

`source`와 `value` 중 하나만 지정합니다. `source: input`은 기본 동작이므로 원본 YAML에서는 생략합니다.
표현식이나 `${...}` 문법은 사용하지 않습니다. header 이름은 대소문자를 구분하지 않고 매칭합니다.
원본에 없는 parameter, 중복 override, 타입/범위를 벗어난 고정값은 검증 실패입니다.
복수 조직 사용자의 조직 선택은 인증/권한 계층이 확정합니다. 문자열 subject 값만 지원합니다.
주체 값이 없거나 원본 제약에 맞지 않으면 실행 서버가 호출을 거부합니다.

실행 서버는 다음 순서를 준수해야 합니다. 이 저장소의 CLI는 실행을 대신하지 않습니다.

1. 인증·Page 접근·Action 허용·조건을 검증하고 등록된 `(Page, Action)` 사용 정의를 찾습니다.
2. Endpoint와 해당 Page의 override를 합성합니다. 클라이언트가 전송한 override는 사용하지 않습니다.
3. 원본 parameter 중 override가 없는 값은 호출자 입력으로 받고, 주입/고정값은 서버에서 생성합니다.
4. 주입/고정값은 동일 이름의 사용자 입력으로 덮어쓸 수 없습니다. 원본에 없는 입력은 upstream에 전달하지 않습니다.
5. 최종 요청에 Endpoint의 required/type/range/body schema를 검증하고 호출합니다.

필수 parameter와 필수 body는 override가 없어도 원본 계약에 따라 호출자가 제공해야 합니다.
선택 parameter/body의 입력이 없으면 upstream에서도 생략합니다.
**body 내부 필드별 주입·부분 수정은 현재 v1에 포함하지 않습니다.**

## Page override의 응답 필드 선택

성공·오류 응답 중 **바꾸려는 상태코드만** `overrides.responses`에 작성합니다.
해당 상태코드에 `fields`를 쓰면 선택한 leaf만 반환합니다. 생략한 상태코드는 원본 그대로입니다.
Endpoint에 없는 상태코드나 원본 schema와 맞지 않는 응답은 실행 서버가 관리하는 일반 오류로 처리합니다.

`fields`는 JSON Pointer escape를 사용하고 배열 요소에 한해 `*`를 추가한 경로입니다.

| 예시 | 의미 |
| --- | --- |
| `/id` | 최상위 id |
| `/items/*/nickname` | items 배열의 각 객체에서 nickname |
| `/tags/*` | scalar 배열의 각 값 |
| `/a~1b` | 이름이 `a/b`인 property |
| `/a~0b` | 이름이 `a~b`인 property |
| `""` | 응답 전체가 scalar 또는 null인 경우 해당 값 |

object/array 전체를 선택할 수 없고 최종 leaf를 지정해야 합니다.
실행 서버는 선택한 leaf만 남기되 부모 object 구조, 배열 순서와 요소 수를 보존합니다.
선택한 선택 필드가 없으면 생략하고, 필요한 구조 컨테이너/빈 배열은 보존합니다.
필터링 전 응답을 Endpoint schema로 검증하며, 필터링된 결과에 원본 required 목록을 다시 강제하지 않습니다.
`type: "null"`은 body가 없는 HTTP 응답에도 사용할 수 있으며 소비자는 빈 body와 JSON null을 명시적으로 처리합니다.
`fields` override가 있는 응답은 Endpoint에 새 필드가 추가되어도 선택 목록에 자동 포함되지 않습니다.
override가 없는 응답은 Endpoint 전체를 상속하므로 원본에 추가된 필드도 포함합니다.
필드 이름 변경, 마스킹 알고리즘, 값 변환, 조건별 projection은 후속 규격 확장 대상입니다.

## Page와 연결

Page는 `path`, `actions`와 선택 `parent`를 가집니다. `actions: []`인 화면도 가능합니다.
각 사용 정의는 `action`과 선택 `overrides`를 가집니다. `(Page, Action)` 쌍은 유일해야 합니다.
같은 Action을 다른 Page에서 사용할 수 있으며 서로의 override를 공유하거나 변경하지 않습니다.
`path`는 현재 카탈로그의 단일 프런트엔드 라우트 공간에서 유일합니다.
`parent`는 탐색 계층이며 path prefix나 권한 상속을 의미하지 않습니다. 순환 연결은 금지합니다.

| 원본 필드 | 파생 관계 | 방향 |
| --- | --- | --- |
| Endpoint.server | `providedBy` | Endpoint → Server |
| Action.service + method + path 대조 결과 | `invokes` | Action → 검증된 Endpoint |
| Page.actions[].action | `uses` | Page → Action, 관계 속성으로 overrides 보존 |
| Page.parent | `childOf` | 자식 Page → 부모 Page |

역방향 탐색은 같은 관계를 DB에서 조회해 구성합니다.
역방향 배열이나 별도 연결 문서를 수작업으로 유지하지 않습니다.
`invokes.to`와 `pageActionUsages.endpoint`의 Endpoint 이름은 검증 후 생성하는 추적 정보이며 Action YAML의 입력 참조가 아닙니다.
어떤 Page에도 연결되지 않은 Action도 허용합니다. 구조상 사용 위치와 실제 실행 권한은 서로 다른 정보입니다.
Action만으로 페이지별 필드 제한을 결정할 수 없습니다. 페이지 경유 호출은 서버가 유효한 Page 맥락을 확인해야 합니다.
직접 Endpoint 허용이나 Page 밖 Action 호출의 권한 판단은 별도이며, 임의 Page의 override를 전역 기본값으로 사용하지 않습니다.

## 검증 경계

검증기는 중복 YAML 키, anchors/aliases, 다중 문서, 비문자열 map key,
1 MiB 초과 파일, `${...}`, manifest 누락/초과 파일, 경로 이탈과 symlink를 거부합니다.
각 문서를 JSON Schema로 검사하고 전체 참조, route 중복, Action 직접 명세 대조, Page 순환, 사용 정의 중복과 Page override를 추가 검사합니다.
snapshot의 `pageActionUsages`에는 Page/Action/Endpoint 식별자와 합성된 `effective` 계약이 들어갑니다.
effective는 참조한 Server에서 가져온 service 정보(`name`, `baseUrl`)와 Action의 method/path에 원본 Endpoint의 요청·응답 계약을 결합하고,
parameter/body의 `source` 또는 `value`, 명시한 응답의 `fields`를 더한 결과입니다.
응답 `schema`는 필터링 전 upstream 검증용 원본이며, 최종 선택 목록은 `fields`가 결정합니다.
이 값은 파생 데이터로만 저장하며 원본 Endpoint나 다른 Page를 수정하지 않습니다.
데이터가 없는 manifest를 정상적인 전체 삭제로 취급하지 않습니다.
이 검증은 실제 API가 선언한 계약을 지키는지, subject 정보가 존재하는지,
DB 외부 정책이 리소스를 참조하는지까지 확인하지 않으며 해당 부분은 실행·동기화 서버 책임입니다.
