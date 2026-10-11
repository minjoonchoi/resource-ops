# 자동 생성 계약과 Page 처리 설계

원본 JSON은 서비스 개발조직이 관리하고, 생성 Service는 호출·요청 검증·응답 처리에 필요한 계약을 제공합니다.
Action은 업무와 호출 대상을, Page는 해당 업무를 화면에서 사용할 때의 입력 주입·scope 검사·응답 노출을 정의합니다.
YAML 문서의 kind는 Service, Action, Page입니다. 엔드포인트는 Service.spec.endpoints에 포함합니다.

## 추출 기준

| OpenAPI 입력 | 생성 Service | 처리 |
| --- | --- | --- |
| 파일 경로 | metadata.name / organization | `openapi/<조직>/<서비스>.json`에서 결정 |
| info.title | metadata.title | 서비스 표시 이름 |
| swagger / openapi | spec.openapi-version | 원래 명세 버전 그대로 기록 |
| servers 또는 Swagger 서버 정보 | spec.servers, endpoints[].servers | 기본 서버와 다른 endpoint 서버만 별도 저장 |
| paths의 HTTP operation | spec.endpoints[] | method/path와 사람이 읽을 수 있는 metadata.name |
| operation.summary / description | endpoint.metadata.description | 공백이 아닌 summary 우선, 없으면 description |
| path/operation parameters | endpoint.request.parameters | 상속을 합성한 이름·위치·필수·스키마·직렬화 설정 |
| requestBody 또는 Swagger body/formData | endpoint.request.body | required, content, 필요한 form 직렬화 정보 |
| responses | endpoint.responses | 모든 상태의 content/schema와 응답 헤더 계약 |
| security | endpoint.security | 상속 후 유효 요구조건. `[]`도 명시 |
| components.schemas / definitions | spec.schemas | 호출 계약에서 참조하는 정의와 전이·재귀 참조, discriminator 대상만 포함 |
| 사용되는 securitySchemes / securityDefinitions | spec.security-schemes | 실제 요구하는 인증 방식의 정의 |
| info.version·contact·license, tags, externalDocs, operationId | 생성하지 않음 | 원본 JSON에서 확인 |
| 예제, 필드의 title/description, links, callbacks/webhooks, x- 확장 | 생성하지 않음 | 화면 처리/요청 검증 계약에 사용하지 않음 |
| 미사용 컴포넌트 | 생성하지 않음 | 생성물에 필요 없는 정의 제외 |

schema의 type/format/required/enum/default, 수치·문자열·배열 제약, readOnly/writeOnly,
nullable/null type, 조합과 추가 속성 규칙은 유지합니다. enum/default/const 안의 실제 데이터는 그대로 보존합니다.
예를 들어 `properties.description`이라는 실제 API 필드는 설명용 description 키와 달리 제거하지 않습니다.
해석하지 못하는 스키마 제약은 조용히 버리지 않고 생성 오류로 보고합니다.

설명용 변경은 선택된 metadata.title/description을 바꾸지 않으면 생성 YAML을 변경하지 않습니다.
요청/응답 필드·타입·제약·직렬화·인증이 바뀌면 생성물도 바뀌며 관련 Page/History 선택을 다시 검증합니다.

## Service → Action → Page 예제

아래는 회원 검색 API가 있는 경우의 연결 예제입니다. 실제 services YAML은 반드시 생성 스크립트로 만듭니다.
요청·응답의 타입/필수 여부는 Service에 한 번 정의하며, Page에는 화면에서 필요한 처리 규칙만 씁니다.

```yaml
api-version: resource-ops/v1
kind: Service
metadata:
  name: member-search-api
  title: 회원 검색 API
  organization: member-team
spec:
  openapi-version: 3.0.4
  servers:
    - url: https://members.example.invalid
  endpoints:
    - metadata:
        name: member-search-api.POST./v1/members/search
        organization: member-team
        description: 회원 검색
      method: POST
      path: /v1/members/search
      security: []
      request:
        parameters: []
        body:
          required: true
          content:
            application/json:
              schema:
                type: object
                required: [requester, organizationCode]
                properties:
                  requester:
                    type: object
                    required: [email]
                    properties:
                      email:
                        type: string
                        format: email
                  organizationCode:
                    type: string
      responses:
        '200':
          content:
            application/json:
              schema:
                type: object
                properties:
                  items:
                    type: array
                    items:
                      $ref: '#/schemas/Member'
                  total:
                    type: integer
  schemas:
    Member:
      type: object
      properties:
        id:
          type: string
        nickname:
          type: string
        email:
          type: string
        internalNote:
          type: string
```

`content`는 전송 형식과 schema를 연결하는 표준 문법입니다. media type, 배열, nullable, 재귀 참조 등의
의미를 잃지 않도록 유지합니다. Swagger 2.0도 같은 request/body/content 구조로 추출하지만 명세 버전은 바꾸지 않습니다.
`$ref`는 **Service.spec 기준**이며 `#/schemas/Member`는 `Service.spec.schemas.Member`를 가리킵니다.
YAML 문서 전체나 원본 JSON을 참조 루트로 사용하지 않습니다.

```yaml
api-version: resource-ops/v1
kind: Action
metadata:
  name: members.search
  title: 회원 검색
spec:
  endpoint:
    service: member-search-api
    method: POST
    path: /v1/members/search
```

Action의 service는 Service.metadata.name 참조이며 method/path는 직접 작성하고 생성 계약과 대조합니다.
plugins는 기존 confirm/history 단일 배열을 유지합니다. Action에서 요청/응답 필드를 다시 정의하지 않습니다.

```yaml
api-version: resource-ops/v1
kind: Page
metadata:
  name: member-search
  title: 회원 검색 화면
spec:
  path: /members/search
  actions:
    - action: members.search
      request:
        body:
          requester:
            email:
              source: subject
              field: email
          organizationCode:
            source: scope
            name: organization-codes
      response:
        fields:
          items:
            id: true
            nickname: true
            email:
              mask: email
          total: true
```

이 Page에서 requester.email은 인증된 요청자의 email로 덮어쓰고 organizationCode는 UI 입력을 scope로 검증합니다.
결과는 items[].id/nickname/email과 total만 포함하며 email은 마스킹합니다. internalNote와 미지정 필드는 제거합니다.
`request.query`도 실제 파라미터명을 키로 사용하여 같은 source 규칙을 적용합니다.

## Page 처리 규칙

| Page 선언 | 의미 |
| --- | --- |
| request 생략 / 규칙 없는 필드 | UI 입력을 사용하고 Service의 요청 계약으로 검증 |
| source: subject + field | 인증된 원래 요청자의 id/nickname/email 주입. UI 입력은 해당 값을 덮어쓸 수 없음 |
| source: scope + name | 등록된 scope에서 요청자에게 허용한 값으로 입력 검증. 값 주입 아님 |
| response 생략 | 별도 응답 선택·마스킹 없음 |
| response.fields | 실제 HTTP 200에서 명시한 필드만 포함, 나머지 모두 drop |
| true | 해당 leaf 값 유지 |
| mask: 이름 | 해당 leaf를 포함하되 등록한 규칙으로 마스킹 |

객체는 실제 depth대로 작성하며 배열은 Service의 items를 따라 요소마다 같은 규칙을 적용합니다.
객체 전체 true, flat 경로, 빈 fields, false는 허용하지 않습니다. API 필드명은 원래 표기 그대로 씁니다.
scope 필드의 누락/null/빈 배열은 승인으로 처리하지 않습니다. subject 주입 실패나 scope/mask 해석 실패도 호출/노출을 차단합니다.
미지정 필드의 입력은 보존하되 원본 schema가 additionalProperties를 제한하면 그 제약을 따라야 합니다.

실행 서버는 다음 순서를 구현해야 합니다.

1. Page/Action 권한과 카탈로그 revision을 확인하고 Service 계약을 찾습니다. history는 Action 시작부터 수집합니다.
2. subject 값을 주입한 최종 입력에 Service의 타입/필수/제약 및 scope 검사를 적용합니다.
3. confirm이 있으면 이 확정 입력과 요청자·Page·revision에 대해 확인을 받습니다.
   호출 직전에 실행 권한·확인 조건·scope 허용 여부를 다시 검사하고 입력이 바뀌면 기존 확인을 재사용하지 않습니다.
4. Service의 서버·인증·직렬화 계약대로 호출합니다. history 값 선택은 실제 송신 요청/수신 응답을 기준으로 합니다.
5. upstream 응답을 해당 상태의 Service 계약으로 검증한 뒤 실제 200이면 Page fields를 적용합니다.
   200 계약 선택은 `200 → 2XX → default` 순서지만 Page 규칙을 다른 상태에 적용하지 않습니다.
6. 화이트리스트에 있는 leaf만 남기고 마스킹합니다. 최종 출력에 제거한 원본 required 필드를 다시 추가하지 않습니다.

이 저장소는 선언·정적 검증·snapshot까지 구현합니다. 실제 API 호출, subject/scope/mask 해석, confirm/history 실행은 소비자 구현 범위입니다.
지원하는 Page field 선택은 단일 JSON media type, 명확한 객체/배열/leaf schema입니다.
복합/boolean/untyped schema, 제약 sibling ref, tuple·순환 배열, form/multipart·streaming 필드 가공은 추측하지 않고 거부합니다.

## 생성·검증 절차

1. `generate_services.py <organization>/<service>`로 선택한 JSON을 읽고 버전에 맞는 원본 검증기를 적용합니다.
2. 상속을 합성하고 필요한 계약만 추출한 뒤 사용 스키마를 닫힌 참조 집합으로 구성합니다.
3. 생성된 계약도 원래 버전의 검증기로 검사합니다. 검증용 OpenAPI envelope는 메모리에만 만들며 YAML에 저장하지 않습니다.
4. 결정적인 YAML을 생성합니다. CI는 누락분만 생성하고 기존 파일은 바이트 단위 비교만 합니다.
5. Action 연결과 Page/History의 필드 선택을 생성 Service만으로 검사하고 snapshot을 만듭니다.

`--from-generated`는 원본 JSON 없이 계약 오류·참조 오류를 검증합니다. 설명이나 유효한 계약을 임의로 바꿨는지까지
증명할 수는 없으므로 CI의 원본 재생성 비교를 대신하지 않습니다.

기존 `spec.openapi` 방식과 호환되지 않는 구조 변경입니다. 기존 서비스는 생성 스크립트로 다시 만들고 소비자는
Service.spec.schemas를 참조 루트로 사용하도록 함께 갱신해야 합니다. 자동 생성 원본 파일 경로, Action 참조,
Page의 request/response 문법은 유지하면서 검증 대상을 생성 계약으로 전환합니다.
