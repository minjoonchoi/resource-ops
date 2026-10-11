# OpenAPI 버전 호환성

공식 명세 확인일: **2026-10-11**. 원본 최상위 `swagger` / `openapi`로 버전을 판별합니다.
`info.version`은 판별에 사용하지 않습니다. 원본 버전과 내용은 Service.spec.openapi에 그대로 저장합니다.
변환 중 문서 다운로드나 원격 API 호출을 하지 않으며, 공식 문서는 구현/호환성 검토 시 확인합니다.

## 버전별 처리

| 입력 | 공식 문서 | 문서 / 값 검증기 | 카탈로그 처리 |
| --- | --- | --- | --- |
| Swagger 2.0 | [2.0](https://spec.openapis.org/oas/v2.0.html) | OpenAPIV2SpecValidator / Draft4Validator | host·basePath·schemes, consumes·produces, body·formData, definitions를 해석 |
| OpenAPI 3.0.x | [3.0.4](https://spec.openapis.org/oas/v3.0.4.html) | OpenAPIV30SpecValidator 기반 / OAS30WriteValidator | nullable, boolean exclusiveMinimum, requestBody/content, components |
| OpenAPI 3.1.x | [3.1.2](https://spec.openapis.org/oas/v3.1.2.html) | OpenAPIV31SpecValidator / OAS31Validator | JSON Schema 2020-12의 null type·boolean schema·숫자 exclusiveMinimum·$ref sibling 제약 |
| OpenAPI 3.2.x | [3.2.0](https://spec.openapis.org/oas/v3.2.0.html), [3.2.1](https://spec.openapis.org/oas/v3.2.1.html) | OpenAPIV32SpecValidator / OAS32Validator | 3.1 처리와 QUERY·additionalOperations·querystring·itemSchema 보존 |

고정 라이브러리: `openapi-spec-validator==0.9.0`, `openapi-schema-validator==0.9.0`,
`jsonschema==4.26.0`. [문서 검증기 선택](https://openapi-spec-validator.readthedocs.io/en/latest/python.html),
[값 검증기](https://openapi-schema-validator.readthedocs.io/en/latest/validation.html)를 참고합니다.

3.x의 기능 구분은 major.minor 기준입니다. patch 버전만 달라서 거부하지 않습니다.
3.0 검증기의 내장 meta-schema는 patch를 한 자리 숫자로 제한하므로,
`PatchCompatibleOpenAPIV30SpecValidator`가 버전 문자열 pattern만 여러 자리 숫자로 확장합니다.
나머지 구조/의미 검증은 원래 검증기를 유지하며 원본 버전을 바꾸지 않습니다.
이 처리는 [OAS Versions 규칙](https://spec.openapis.org/oas/v3.0.4.html#versions)에 근거합니다.
미지원 major/minor, 누락·숫자 버전, swagger/openapi 동시 선언은 파일 변경 전에 명확한 오류를 반환합니다.

검증한 실제 버전은 2.0, 3.0.0–3.0.4, 3.1.0–3.1.2, 3.2.0–3.2.1입니다.
3.0.99/3.1.99/3.2.99는 patch 호환 규칙의 합성 테스트이며 발표된 버전이라는 의미가 아닙니다.

## Swagger 2.0 adapter

2.0 원문을 3.x로 다시 저장하지 않습니다. `swagger_adapter.py`는 snapshot의 Page 사용 계약만
공통 표현으로 만듭니다. schema 참조는 계속 원본의 `#/definitions/...`를 가리킵니다.

- path/operation parameter를 합성하고 비-body parameter의 원래 type·collectionFormat을 보존합니다.
- body parameter는 request.body.content로 옮기며 원본을 `x-swagger-body-parameter`에도 남깁니다.
- formData는 object body로 나타내며 file은 binary 표현을 사용합니다.
  원래 type·collectionFormat·각 필드 설정은 `x-swagger-form-parameters`에 보존합니다.
- consumes/produces는 operation 설정을 우선하고, 없으면 문서 값을 상속합니다.
  둘 다 없을 때 `*/*`로 미지정임을 나타내며 JSON이라고 가정하지 않습니다.
- host와 schemes가 있으면 서버 URL을 구성합니다. 없으면 상대/프로토콜 상대 URL과
  `swaggerServer`의 원래 host/basePath/schemes를 함께 보존합니다. 실행 설정에서 기준 URL을 제공해야 합니다.
- 2.0 response schema·headers·examples를 유지하면서 content 표현을 추가합니다.
  실제 form serialization과 인증 적용은 소비자 구현 책임입니다.

## 3.1 / 3.2 차이

null과 수치 범위는 해당 버전의 값 검증기로 검사합니다. 3.1/3.2의 `$ref`와 sibling 제약을 함께 검사하므로
`$ref` 뒤의 maxLength 같은 제한을 잃지 않습니다. boolean schema도 가져오기와 값 검증에서 허용합니다.

3.2의 고정 `query` operation은 `QUERY`로 등록합니다. `additionalOperations`의 키는 전송할 HTTP method를
그대로 사용하므로 `COPY`와 `copy`는 서로 다릅니다. Action에서도 대소문자를 그대로 작성해야 합니다.
표준 메서드의 기존 Endpoint 이름은 유지하고, 확장 메서드는 method와 path를 함께 해시하여 충돌을 피합니다.
querystring의 content와 스트리밍 itemSchema 등 새 필드는 원문·사용 계약에 보존합니다.
응답 명세가 생략된 operation도 등록하며 Page가 없는 응답을 override하려 하면 검증에서 실패합니다.

## 가져오기와 Page override의 경계

버전 지원이 모든 실행 기능의 구현을 의미하지는 않습니다. 다음 제한은 버전 판별 오류와 구분합니다.

- 문서 내부 JSON Pointer `$ref`를 사용합니다. 외부 refs는 bundle해야 하며 `$id`·anchor·dynamic refs는 현재 처리 범위 밖입니다.
- 하나 이상의 `paths` operation이 있는 서비스 카탈로그를 대상으로 합니다. callbacks/webhooks는 원문에 보존하지만 별도 Endpoint로 등록하지 않습니다.
- Page의 field projection은 단일 JSON media type의 명확한 leaf schema를 대상으로 합니다.
  여러 media type, 복합·boolean schema, 제약 sibling을 가진 ref, 스트리밍 itemSchema의 projection은 추측하지 않습니다.
- parameter 주입은 schema 방식만 지원합니다. querystring/content parameter·form 내부 필드의 주입은 별도 확장이 필요합니다.
- 전체 계약은 원문에 보존됩니다. Config Server에서 내용 치환을 막기 위한 placeholder 제한 등은 [카탈로그 규격](catalog-model.md)을 따릅니다.

## 버전 확인·확장 절차

1. 대상 JSON의 최상위 버전과 실패한 객체 위치를 확인합니다.
2. 해당 버전의 공식 문서를 열어 기존 지원 family와 달라진 필드·타입·상속·참조 규칙을 확인합니다.
   동일 minor의 patch 차이는 기능 차이로 취급하지 않습니다.
3. 설치할 검증 라이브러리의 공식 지원 목록과 실제 버전의 동작을 확인합니다.
4. 원본을 수정하여 우회하지 않고 버전별 검증기/adapter에 필요한 처리를 구현합니다.
5. 해당 버전의 fixture로 원문 보존, 서비스·Endpoint 생성, Action 매칭, Page 계약을 검증합니다.
6. 이 문서의 URL·확인일·검증 버전·제한과 의존성 pin을 갱신하고 CI를 통과시킵니다.

루트 [AGENTS.md](../AGENTS.md)가 특정 파일 변환 요청에도 이 절차와 스크립트 실행을 적용하도록 지시합니다.
