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
  endpoint: members.get
  request:
    parameters:
      - in: path
        name: memberId
        source: input
  responses:
    "200":
      fields: [/id, /nickname, /organizationCode]
    "404":
      fields: [/code, /message]
```

- 리소스의 안정적 식별자는 `(kind, metadata.name)`입니다. 표시용 `title`과 선택 `description`은 변경 가능합니다.
- `name`은 소문자로 시작하고 소문자·숫자·점·하이픈을 사용합니다. 최대 128자입니다.
- 파일명은 `metadata.name.yaml`, 디렉터리는 kind별 복수형으로 고정합니다.
- Config Server의 profile 파일 선택과 충돌하는 `-default` 이름 접미사는 금지합니다.
- 이름 변경은 삭제+생성입니다. 파일과 모든 참조를 함께 변경하고 삭제 영향을 검토합니다.
- 참조 필드는 문자열 이름만 사용합니다. 대상 kind는 필드가 결정합니다.
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

## Action의 요청 생성

Action은 Endpoint의 method/path/서버/원본 schema를 복제하지 않습니다.
`spec.endpoint`는 정확히 하나의 Endpoint를 가리킵니다.
여러 Action이 같은 Endpoint를 업무별로 재사용할 수 있습니다.

`request.parameters`는 Endpoint parameter를 골라 값을 얻는 방법을 지정합니다.

| 표현 | 의미 |
| --- | --- |
| `source: input` | 호출자가 제공하는 해당 parameter 값 |
| `source: subject.id` | 인증된 주체의 문자열 ID |
| `source: subject.email` | 인증된 주체의 이메일 |
| `source: subject.nickname` | 인증된 주체의 닉네임 |
| `source: subject.organization.code` | 요청 맥락에서 검증된 주체의 조직코드 하나 |
| `value: 20` | 카탈로그에 정의한 고정값 |

`source`와 `value` 중 하나만 지정합니다. 표현식이나 `${...}` 문법은 사용하지 않습니다.
복수 조직 사용자는 어떤 조직을 선택할지 인증/권한 계층이 확정해야 하며 임의로 첫 조직을 선택하지 않습니다.
문자열 subject 값만 지원합니다. 주체 필드가 없거나 타입/제약이 맞지 않으면 호출을 거부합니다.

실행 서버는 다음 순서를 준수해야 합니다. 이 저장소의 CLI는 실행을 대신하지 않습니다.

1. 인증·Action 허용·조건을 확인하고 신뢰할 수 있는 subject context를 확보합니다.
2. `source: input`으로 선언한 값만 사용자 입력에서 읽습니다.
3. subject 주입과 고정값은 서버에서 생성합니다. 동일 이름의 사용자 입력으로 덮어쓸 수 없습니다.
4. 선언되지 않은 parameter는 upstream에 전달하지 않습니다. 거부 응답을 권장하며 묵시적 passthrough는 금지합니다.
5. Endpoint의 required/type/range를 최종 생성 값에 검증하고 요청을 보냅니다.

Endpoint의 required parameter는 Action에서 반드시 값을 생성해야 합니다.
선택 parameter는 생략할 수 있으며, `source: input`인 선택 parameter의 입력이 없으면 upstream에서도 생략합니다.
body는 `request.body: {source: input}`을 명시한 경우에만 원본 Endpoint schema 전체를 사용합니다.
필수 body를 생략할 수 없습니다. **body 내부 필드별 주입·부분 수정은 현재 v1에 포함하지 않습니다.**

## Action의 응답 필드 선택

`responses`에는 Endpoint에 정의된 모든 상태코드의 처리 범위를 명시합니다.
성공 응답뿐 아니라 오류 응답에도 필드 선택을 적용합니다.
정의하지 않은 상태코드나 원본 schema와 맞지 않는 응답은 upstream 원문을 그대로 반환하지 않고
실행 서버가 관리하는 일반 오류로 처리합니다.

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
선택되지 않은 새 필드는 Endpoint에 추가되어도 자동 노출되지 않습니다.
필드 이름 변경, 마스킹 알고리즘, 값 변환, 조건별 projection은 후속 규격 확장 대상입니다.

## Page와 연결

Page는 `path`, `actions`와 선택 `parent`를 가집니다. `actions: []`인 화면도 가능합니다.
`path`는 현재 카탈로그의 단일 프런트엔드 라우트 공간에서 유일합니다.
`parent`는 탐색 계층이며 path prefix나 권한 상속을 의미하지 않습니다. 순환 연결은 금지합니다.

| 원본 필드 | 파생 관계 | 방향 |
| --- | --- | --- |
| Endpoint.server | `providedBy` | Endpoint → Server |
| Action.endpoint | `invokes` | Action → Endpoint |
| Page.actions | `uses` | Page → Action |
| Page.parent | `childOf` | 자식 Page → 부모 Page |

역방향 탐색은 같은 관계를 DB에서 조회해 구성합니다.
역방향 배열이나 별도 연결 문서를 수작업으로 유지하지 않습니다.
어떤 Page에도 연결되지 않은 Action도 허용합니다. 구조상 사용 위치와 실제 실행 권한은 서로 다른 정보입니다.

## 검증 경계

검증기는 중복 YAML 키, anchors/aliases, 다중 문서, 비문자열 map key,
1 MiB 초과 파일, `${...}`, manifest 누락/초과 파일, 경로 이탈과 symlink를 거부합니다.
각 문서를 JSON Schema로 검사하고 전체 참조, route 중복, Page 순환, Action 계약을 추가 검사합니다.
데이터가 없는 manifest를 정상적인 전체 삭제로 취급하지 않습니다.
이 검증은 실제 API가 선언한 계약을 지키는지, subject 정보가 존재하는지,
DB 외부 정책이 리소스를 참조하는지까지 확인하지 않으며 해당 부분은 실행·동기화 서버 책임입니다.
