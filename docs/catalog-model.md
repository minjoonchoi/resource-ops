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

하나의 생성 YAML에는 Service 문서 하나가 들어갑니다. spec에는 endpoints와 openapi만 저장합니다.
원본 위치는 metadata.organization/name으로 `openapi/<organization>/<name>.json`을 결정하므로
spec.source는 저장하지 않습니다.

| 위치 | 생성 규칙 |
| --- | --- |
| `kind` | `Service` |
| `metadata.name` | JSON 파일명에서 확장자 제거 |
| `metadata.organization` | 원본의 조직 디렉터리명 |
| `metadata.title` | OpenAPI `info.title` |
| `spec.openapi` | 파싱한 원본 OpenAPI 전체, 손실 없이 보존 |
| `spec.endpoints[]` | `paths`의 각 HTTP operation에서 생성한 metadata·method·path |

Endpoint의 `metadata.organization`은 Service와 같습니다. `metadata.name`은
`<service>.<method>.<원본 path>`로 생성합니다. 예: `member-api.GET./v1/members/{memberId}`.
표준 메서드는 `GET`, `POST`처럼 대문자로, 3.2 확장 메서드는 원래 대소문자/토큰 그대로 사용합니다.
경로의 `/`, `.`, `{}`, 대소문자, percent encoding 및 trailing slash를 변환하거나 생략하지 않습니다.
Endpoint 이름은 경로 길이에 맞춰 보존하며 Service/Action/Page 이름의 128자 제한을 적용하지 않습니다.
전체 문자열을 식별키로 사용하고 점으로 분리하여 service/method/path를 복원하지 않습니다.
각 값은 별도 필드에서 읽으며, 검증기는 원문에서 재생성한 이름과 metadata가 일치하는지 확인합니다.
`operationId`는 원문에 보존하며 필수 식별키로 사용하지 않습니다. 누락되어도 생성할 수 있고,
설명·operationId가 바뀌어도 동일 서비스·method·path의 Endpoint identity는 유지됩니다.
같은 method/path의 중복 route 및 전체 카탈로그의 Endpoint identity 중복은 거부합니다.
특히 서비스명과 확장 메서드 모두 점을 포함하여 조합이 충돌하는 경우도 전체 검증에서 실패합니다.

Endpoint의 `metadata.description`은 operation의 공백이 아닌 `summary`를 우선 사용하고,
없거나 공백이면 공백이 아닌 `description`을 사용합니다. 선택된 문자열은 원문 그대로 복사하며,
둘 다 없거나 공백이면 필드를 생략합니다. `operationId`나 method/path로 설명을 대신 만들지 않습니다.
Endpoint에는 `metadata.title`을 생성하지 않으며 원본 OpenAPI의 summary/description은 모두 보존합니다.

```yaml
metadata:
  name: member-api.GET./v1/members/{memberId}
  organization: member-team
  description: 회원 단건 조회
method: GET
path: /v1/members/{memberId}
```

기존 해시 기반 이름은 이 규칙으로 변경됩니다. 동기화 소비자는 새 snapshot의 Endpoint 및 관계를
함께 반영해야 합니다. Action은 service/method/path로 연결되므로 이름 변경 때문에 수정할 필요가 없습니다.

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

Action의 `metadata.organization`은 선택적인 담당조직 표시입니다. 자동 생성 Service/Endpoint는
원본 경로에서 조직이 반드시 결정됩니다. 조직 표시 자체로 권한이 부여되지는 않습니다.
Action의 endpoint에는 Endpoint ID, request, responses, field 제한을 작성하지 않습니다.
history.config의 필드 선택은 이력에 저장할 값만 정의하며 호출 계약의 변경은 Page에 둡니다.
`spec.endpoint.service`는 **생성 Service의 metadata.name**을 참조하고 endpoint.method/path는 직접 명세합니다.
서비스가 존재해야 하고 그 서비스의 operation과 method/path 및 경로 변수명이 정확히 일치해야 합니다.
다른 서비스의 동일 URL·path로 대신 매칭하거나 대소문자·trailing slash를 보정하지 않습니다.
동일 서비스에서 `/members/{id}`와 `/members/{memberId}`처럼 모호한 route도 거부합니다.
Page에서 아직 사용하지 않는 Action도 검증합니다. 여러 Action이 같은 API를 사용할 수 있습니다.

## Action 실행 플러그인

Action의 `spec`은 `endpoint`와 선택적인 `plugins`로 구성합니다. `endpoint`는 필수이며
Service.metadata.name 참조와 method/path만 담습니다. 기존 spec 최상위의 service/method/path는
허용하지 않으므로 소비자도 `spec.endpoint`로 전환해야 합니다.

| 필드 | 역할 |
| --- | --- |
| `spec.endpoint` | 실행할 엔드포인트 한 개: service, method, path |
| `spec.plugins` | 선택적인 단일 플러그인 배열. confirm/history를 각각 최대 한 번 연결 |
| confirm의 `config` | 필수 확인 대상·필요 인원·실행 방식 |
| history 선언 | `name: history`로 Action 전체 이력 기록. 선택적인 config로 요청/응답 저장 필드 지정 |

플러그인을 사용하지 않으면 `plugins`를 생략합니다. confirm만, history만 또는 둘 다 연결할 수 있습니다.
before/after 구분 없이 단일 배열로 작성하며 빈 배열·알 수 없는 이름·같은 name의 중복 연결은 거부합니다.
설정이 달라도 같은 플러그인을 여러 번 연결할 수 없습니다. 기존 before/after 객체는 허용하지 않습니다.
배열 순서는 보존하지만 실행 단계를 결정하지 않습니다. confirm은 이름에 따라 endpoint 실행을 제어하고,
history는 선언 위치와 무관하게 Action 시작부터 전체 이력을 수집합니다.
새 플러그인은 카탈로그 schema와 실행 서버의 등록/검증을 함께 확장해야 합니다.
플러그인의 name은 실행 서버에 등록된 구현 식별자이며 카탈로그 리소스 참조가 아닙니다.
Service/Action/Page 간 참조는 계속 대상 metadata.name을 사용합니다.

### Confirm 조건

confirm.config에는 pool, count, execution을 모두 작성합니다. 생략된 조건으로 통과하는 기본값은
없습니다. 예제의 reviewer-a/b는 가상 닉네임이고 security-team은 가상 조직 식별자입니다.

| 필드 | 의미 |
| --- | --- |
| `pool.users` | 확인 후보로 직접 지정하는 사용자 닉네임 목록 |
| `pool.organizations` | 확인 후보를 가져올 조직 식별자 목록 |
| `count` | 합쳐진 pool에서 필요한 서로 다른 사용자의 확인 수. 1 이상의 정수 |
| `execution: requester` | count 충족 후 실행 대기. 원래 요청자가 명시적으로 실행해야 호출 |
| `execution: automatic` | count 충족 시 실행 서버가 해당 요청을 즉시 실행 대상으로 전환 |

users와 organizations 중 하나 이상을 지정하며 함께 사용할 수 있습니다. 사용하지 않는 목록은
생략합니다. kind/name 대상 객체, roles, targets, requiredCount는 허용하지 않습니다.
users는 사용자 metadata.name이 아닌 **닉네임을 명시하는 목록**입니다. organizations는 외부 조직 정의의
metadata.name에 대응하는 식별자입니다. 이 저장소에는 사용자/조직 정의가 없으므로 실행 서버가
닉네임을 실제 사용자 식별자로 해석하고 조직의 직접 소속 사용자를 조회합니다. 하위 조직은 암묵적으로
확장하지 않습니다. 존재하지 않거나 여러 사람을 가리키는 모호한 닉네임은 오류로 처리합니다.
입력 문자열은 대소문자 변경이나 공백 제거 없이 보존합니다.

명시한 사용자와 조직 소속 사용자를 **하나의 pool로 합쳐 실제 사용자 식별자로 중복 제거**합니다.
어느 목록/조직에서 왔는지와 무관하게 pool의 서로 다른 count명이 확인하면 조건을 충족합니다.
조직마다 확인을 받거나 직접 지정한 사용자 모두의 확인을 받을 필요는 없습니다.
같은 사람의 반복 확인이나 여러 조직 소속은 한 명으로 계산합니다. 개별 거절/미응답은 확인 수에 포함하지
않으며 다른 후보들로 count가 충족되면 실행 조건은 충족됩니다.

빈 pool·빈 목록·목록 내 중복·공백뿐인 닉네임/조직 식별자·잘못된 실행 방식·누락 조건·0/음수/소수 count는
카탈로그 검증에서 거부합니다. users만 지정했을 때 count가 닉네임 수보다 큰 설정도 거부합니다.
조직을 포함하면 실행 서버가 소속 조회와 사용자 중복 제거 후 최종 pool의 인원이 count 이상인지 검사합니다.
미존재 조직이나 후보 부족은 확인 요청을 시작하기 전에 오류로 처리합니다.

확인은 하나의 실행 요청에 귀속됩니다. 요청자·Action·Page 맥락·확정 입력·카탈로그 revision을
함께 고정하고, 다른 입력이나 수정된 정책에 기존 확인을 재사용하지 않습니다. 실제 호출 직전에
요청자의 실행 권한과 확인자의 자격·유효 확인 수를 다시 검사합니다. requester 방식은 원래 요청자만
실행할 수 있고 automatic 방식도 그 요청자의 권한/입력 맥락을 사용합니다.
동시 확인·중복 이벤트는 동일 실행 요청을 원자적으로 한 번만 실행 대상으로 전환해야 합니다.
네트워크 재시도 시 endpoint의 중복 호출 방지는 실행 서버와 upstream의 idempotency 계약이 필요합니다.

실행 서버가 따라야 할 단계 계약은 다음과 같습니다.

1. history가 연결되었으면 Action 시작 시 이력 수집을 준비합니다.
   Action 권한과 입력을 검증하고 Page 사용 맥락의 override를 적용합니다.
2. confirm이 연결되었으면 count명의 유효 확인이 모일 때까지 대기합니다.
   requester 방식은 충족 후 요청자의 실행 명령을 기다리고 automatic 방식은 충족 시 자동 실행합니다.
   조건 미충족·요청 취소·오류 상태에서는 endpoint를 호출하지 않습니다. 확인 UI는 플러그인 구현에서 결정합니다.
3. endpoint 호출을 시도하고 결과를 확정합니다. history는 해당 Action의 모든 이벤트를 발생 시점마다 기록합니다.
   확인 과정과 API 오류·timeout 등 실패 결과도 포함하며, endpoint를 호출하지 않은 종료도 기록합니다.
4. history 저장 실패를 이유로 이미 실행한 endpoint를 다시 호출하지 않습니다.
   실행 식별자로 이력 저장을 재시도/중복 방지하고 저장 실패를 별도 상태로 추적합니다.

위 내용은 실행 소비자 계약이며 이 저장소의 스크립트는 확인 UI, API 호출, DB 이력 저장을 실행하지 않습니다.
confirm.config의 구조/정적 조건과 history.config.request/responses의 구조 및 OpenAPI 필드 존재 여부를 검증합니다.
history의 events/actionName/groupBy 등 별도 범위/분류 설정은 거부합니다.
외부 대상의 존재/소속과 플러그인별 실행 지원 여부는 실행 서버가
업무 호출 전에 검사해야 하며, 지원하지 않는 플러그인을 무시하고 endpoint를 호출하면 안 됩니다.
이력의 저장소·보존 기간과 확인 UI는 플러그인 구현 계약에서 정의합니다. 이력의 공통 필드는 아래 계약을 따릅니다.
요청/응답 값은 history.config에 명시한 필드만 저장하며 호출 계약의 필드 변경은 하지 않습니다.

플러그인 구성은 Action에 속하므로 모든 Page 사용에 동일하게 적용됩니다. Page overrides로 플러그인을
제거·변경할 수 없습니다. Page 밖에서 Action을 실행하는 경우에도 Action.spec.plugins를 적용합니다.
`resources`의 Action 원본과 `pageActionUsages.plugins`에 단일 배열을 그대로 보존하고 plugins 생략은 사용 계약에서 빈 배열로 정규화합니다. `pageActionUsages.effective`는 기존처럼 엔드포인트의 요청/응답 계약입니다.

### History 요청/응답 값 선택

history.config를 생략하면 행위자·Action·시각·결과 등의 공통 이력만 기록하고 요청/응답 값은 저장하지
않습니다. request/responses 중 필요한 쪽만 작성합니다. 각 선택 목록은 비어 있을 수 없으며 생략한
파라미터·본문·응답 상태·필드는 자동 수집하지 않습니다. events 설정은 계속 사용하지 않습니다.

```yaml
plugins:
  - name: history
    config:
      request:
        parameters:
          - in: path
            name: memberId
          - in: query
            name: organizationCode
        body:
          fields: [/reason, /items/*/id]
      responses:
        '200':
          fields: [/id, /result/status]
        '400':
          fields: [/code]
```

위 예시는 각 필드가 실제 OpenAPI에 존재하는 API에 적용하는 형식 예시입니다.
저장소의 회원 연락처 예제는 path memberId와 200 응답의 /id, /email만 선택합니다.

- request.parameters는 `(in, name)`으로 path/query/header/cookie 파라미터를 지정합니다.
  단순 값은 이름만 지정하며 객체/배열 파라미터는 fields로 leaf를 명시합니다. 예: fields: [/*/id].
  header 이름은 대소문자를 구분하지 않으며 그 외 이름은 정확히 일치해야 합니다.
- request.body.fields 및 responses.<status>.fields는 JSON Pointer 형태의 leaf 경로입니다.
  배열 요소는 `*`, 경로 안의 `/`·`~`는 `~1`·`~0`을 사용합니다. 중첩 객체 전체를 선택할 수 없습니다.
  루트가 scalar인 schema에는 빈 문자열 경로를 사용할 수 있습니다.
- 존재하지 않는 파라미터/필드/상태, 본문 없는 요청/응답의 본문 선택, 중복 선택을 거부합니다.
  파라미터의 content 방식, 여러 media type, JSON 이외 본문, 복합/boolean/untyped schema는 현재 선택을
  명확히 검증할 수 없어 거부합니다. 원본 OpenAPI 자체의 보존/가져오기 범위는 달라지지 않습니다.
- Page에서 사용하지 않는 Action도 검증합니다. 전체 로컬 검증과 --from-generated 소비자 검증에 동일하게 적용합니다.

실행 서버는 **Page 주입/고정값 적용 후 실제로 보낸 최종 요청 값**을 기록합니다. confirm 입력이나
OpenAPI example/default를 실제 실행값으로 대신 저장하지 않습니다. 응답은 Page fields로 화면에 반환할
필드를 줄이기 전의 endpoint 응답에서 선택합니다. 따라서 Page에 노출하지 않는 필드도 명시적으로
history에 선택할 수 있으며, 저장된 이력의 조회 권한은 실행 서버가 따로 적용해야 합니다.
이 설정은 로그 수집 목적이며 API의 요청/응답이나 Page projection을 수정하지 않습니다.

응답 상태는 OpenAPI 계약의 정확한 상태코드 → 범위(2XX 등) → default 순서로 해당 계약을 찾고,
그 계약 키에 작성한 history 선택을 사용합니다. 매칭된 계약에 선택이 없으면 값을 저장하지 않으며
다른 상태의 필드를 대신 적용하지 않습니다. 실제로 없는 선택 필드는 생략하고 명시적인 null과 구분합니다.
응답이 없거나 JSON 파싱/추출에 실패하면 결과·오류 상태를 기록하며 원문 전체 저장으로 대체하지 않습니다.
endpoint 미실행 시 실제 요청/응답 값을 만들지 않습니다. 네트워크 전송을 시도한 뒤 실패한 경우에는
확인 가능한 실제 요청 값과 실패 결과를 기록합니다.
선택한 요청 값은 호출 시작 이력, 응답 값은 해당 호출 결과 이력의 details에 붙이고 executionId로 연결합니다.
실제 값 추출/DB 저장은 실행 서버 구현 범위이며 이 저장소는 설정과 계약 검증을 제공합니다.

### History 수집 및 저장 계약

`plugins`에 `name: history`만 연결하면 해당 Action의 **모든 이력**을 기록합니다.
별도 events나 이벤트 범위 선택은 없으며 Action 요청·확인·endpoint 실행·종료 과정이 모두 포함됩니다.
선택적인 config는 이력 이벤트에 추가할 실제 요청/응답 값만 지정합니다.
confirm 플러그인이 없는 Action에서도 history만 연결할 수 있습니다. 실제로 발생하지 않은 confirm
이벤트는 만들지 않습니다. history를 생략하면 이 플러그인에 의한 이력 저장은 요청하지 않은 것입니다.

history는 플러그인 배열 위치와 무관하게 Action 전체 실행을 관찰합니다. endpoint 완료 시 한 번 호출하는 콜백으로 구현하면
대기 중인 확인이나 endpoint 미실행 이력을 잃으므로, 실행 서버는 Action 진입부터 수집기를 활성화하고
각 이벤트를 내구성 있게 저장해야 합니다. confirm이 며칠 동안 대기해도 기록을 완료 시점까지 미루지 않습니다.

| 범위 | 기록할 행위/전이 |
| --- | --- |
| action | 업무 요청 생성, 권한/입력 검증 결과, 요청 취소, 완료·실패 등 전체 실행 상태 전이 |
| confirm | 확인 요청 생성, 후보별 확인·거절·철회, count 충족/미충족 전이, 요청 취소·만료·오류 |
| endpoint | 요청자의 실행 명령 또는 자동 실행 예약, 호출 시작, 성공·API 오류·timeout·네트워크 오류, 호출 생략/차단 |

철회·만료 등 기능을 실행 서버가 지원해 실제로 발생한 경우 기록합니다. count 미달이나 취소로 끝나면
confirm 이력과 endpoint.skipped(사유 포함)를 남기며 호출 시작/성공 이력을 만들지 않습니다.
자동 실행에서는 마지막 확인자와 자동 실행 주체를 서로 다른 이벤트 행위자로 기록합니다.

이벤트마다 다음 공통 정보를 저장합니다. 필드 선택 옵션으로 행위자나 Action 식별자를 끄지 않습니다.

| 필드 | 저장 값 |
| --- | --- |
| `actionName` | 해당 Action.metadata.name. YAML 설정에 별도 키로 중복 작성하지 않음 |
| `executionId` | 하나의 업무 실행 요청 ID. 동일 Action의 반복 실행/동시 요청을 구분 |
| `eventId`, `sequence`, `occurredAt` | 중복 저장 방지 키, 실행 요청 내 순서, 발생 시각 |
| `event` | confirm.approved, endpoint.started 등 실제 발생한 행위/전이 |
| `actor` | 실제 행위자의 종류(user/system), 안정적인 ID, 당시 사용자 닉네임(사용자일 때) |
| `requester` | 원래 요청자의 안정적인 ID와 요청 당시 닉네임 |
| `result`, `reason` | 행위 결과와 거절·오류·호출 생략 사유(해당할 때) |
| `catalogRevision`, `page` | 요청에 고정한 카탈로그 revision과 Page 맥락(있을 때) |
| `details` | confirm의 현재 확인 수/count 또는 endpoint의 service/method/path·실행 방식·HTTP 상태 등 |

Action.metadata.name은 조회/분류 기준이고 executionId는 개별 실행의 연결 기준입니다.
닉네임 변경 후에도 누가 수행했는지 추적할 수 있도록 사용자 ID와 당시 닉네임을 함께 저장합니다.
시스템이 만든 자동 실행·상태 전이는 시스템 행위자와 원래 요청자를 모두 남깁니다.
이벤트를 처리할 때의 새 Action 이름으로 과거 이력을 덮어쓰지 않고 요청에 고정한 이름/revision을 유지합니다.

snapshot의 Action.metadata.name 또는 pageActionUsages.action이 history의 actionName 바인딩입니다.
플러그인 설정에서 다른 actionName/groupBy를 지정하는 것은 거부합니다. Page 밖 실행도 Action 원본의
metadata.name과 plugins를 사용합니다. 실제 이력 이벤트는 카탈로그 snapshot에 포함하지 않습니다.

중복 이벤트 재처리는 eventId로 멱등 저장하고, 이력 저장 실패는 내구성 큐/outbox 등으로 복구해야 합니다.
이력 복구 때문에 endpoint를 다시 실행하지 않습니다. 저장소/실행 서버는 이 저장소에서 구현하지 않습니다.

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
