# resource-ops 작업 지침

## 특정 OpenAPI 파일 변환 요청

사용자가 특정 JSON의 변환·서비스 YAML 생성·갱신을 요청하면 반드시 저장소의 생성 스크립트를 실행한다.
생성 YAML을 직접 작성하거나 LLM으로 JSON을 YAML로 옮겨 적지 않는다.

1. 요청을 `openapi/<organization>/<service>.json`에 대응시킨다. 파일명이 서비스명이고 바로 위 디렉터리가 조직이다.
   파일 경로가 주어졌으면 여기서 `organization/service`를 추출한다. 추측으로 다른 서비스를 선택하지 않는다.
2. JSON 최상위의 `swagger` 또는 `openapi` 값을 확인한다. `info.version`은 업무 API 버전이며 명세 버전이 아니다.
3. `docs/openapi-compatibility.md`의 해당 버전 행과 공식 명세 링크를 읽는다. 최초 처리, 미검증 버전,
   검증 오류 또는 버전 처리 코드 변경 시 해당 **버전의 공식 문서**를 확인하고 차이를 검토한다.
   patch 버전 차이와 major/minor 기능 차이를 구분한다. 문서를 확인할 수 없으면 확인했다고 쓰지 않는다.
4. `.venv`가 없으면 생성하고 `requirements.txt`의 고정 의존성을 설치한다.
5. 지정한 파일만 변환한다. 예:

   ```sh
   .venv/bin/python scripts/generate_services.py member-team/member-api
   .venv/bin/python scripts/generate_services.py member-team/member-api --check
   ```

6. `services/member-api.yaml`의 metadata.name/organization, Endpoint 목록, OpenAPI 원문 보존 및 manifest diff를 확인한다.
   생성 스크립트는 선택한 서비스와 파일 목록만 갱신한다. 다른 서비스 YAML을 갱신하거나 삭제하지 않는다.
7. 전체 카탈로그 검증을 수행한다. 다른 서비스의 기존 오류가 나오면 그 파일을 임의 변경하지 말고
   지정 대상의 변환 성공 여부와 전체 검증 실패 원인을 구분해 보고한다.

   ```sh
   .venv/bin/python scripts/catalog.py --snapshot dist/catalog.snapshot.json
   ```

`--all`은 전체 처리를 명시적으로 요청받았거나 CI/전체 생성물 유지보수 작업인 경우에만 사용한다.
선택 인자 없는 실행을 전체 변환으로 간주하지 않는다. 원본 삭제 후 생성물 정리도 명시적인 전체 유지보수 작업이다.
서비스 참조가 필요한 Action은 생성 YAML의 Service.metadata.name과 method/path를 확인하여
`spec.endpoint.service/method/path`에 작성한다. 실행 전후 플러그인은 `spec.plugins.before/after`에
연결하며 요청/응답 필드 설정은 계속 Page의 overrides에 둔다. confirm에는 config.pool(users 닉네임 / organizations 조직 식별자),
count, execution(requester/automatic)을 반드시 작성하고 대상·확인 수를 추측하여 채우지 않는다.
history는 config.events로 수집 범위를 지정하며 confirm/endpoint 전체 이력은 [confirm, endpoint]로 선언한다.
이력의 Action 식별자는 해당 Action.metadata.name에서 가져오고 설정에 중복 작성하지 않는다.
after.history는 Action 시작부터 이벤트를 수집하며 endpoint 미실행 종료도 기록하는 계약이다.
Action/Page 정의는 별도 요청 없이 생성기에서 자동 생성하거나 수정하지 않는다.

## 명세 버전 호환성 작업

버전 문제를 피하려고 원본의 swagger/openapi 값을 다른 버전으로 바꾸거나 필드를 삭제해서 통과시키지 않는다.
다음 순서로 처리한다.

1. 정확한 버전과 실패한 객체/필드를 식별하고 `docs/openapi-compatibility.md`에 연결된 공식 명세에서 확인한다.
2. 기존 지원 버전과 비교하여 parameters/body/formData, content, schemas/$ref, nullable/type,
   exclusiveMinimum, servers/security, HTTP operation의 차이를 확인한다.
3. 검증 라이브러리의 공식 문서와 설치된 버전의 구현을 확인하고 적합한 **버전별 검증기**를 선택한다.
   알려지지 않은 major/minor를 기존 검증기에 무조건 통과시키지 않는다.
4. 원본 JSON은 그대로 보존한다. 필요한 차이는 생성기/카탈로그 adapter에 구현한다.
   Page override 지원 범위와 원본 가져오기 지원 범위를 구분하며, 해석할 수 없는 기능을 조용히 버리지 않는다.
5. `tests/fixtures/openapi/`에 해당 버전의 최소 재현 예제를 추가하고
   `tests/test_openapi_versions.py`에 생성·원문 보존·Action 연결·Page 사용 검증을 추가한다.
   단일 대상 격리 동작은 `tests/test_target_conversion.py`로 검증한다.
6. 공식 문서 URL, 확인일, 검증 라이브러리 버전, 지원/제한 항목을 호환성 문서에 갱신하고 전체 테스트를 실행한다.

   ```sh
   .venv/bin/python -m unittest discover -s tests -v
   .venv/bin/python scripts/generate_services.py --all --check
   git diff --check
   ```

단순 데이터 변환에는 새 테스트를 불필요하게 추가하지 않는다. 생성기·버전 처리 변경에는 해당 동작을 검증하는 회귀 테스트가 필요하다.

## CI 및 생성물 소유권

- CI 전체 검증은 `--all --check`, 누락 생성은 `--all --create-missing`을 사용한다.
- 기존 서비스 YAML이 원본의 생성 결과와 다르면 CI는 덮어쓰지 않고 실패해야 한다.
- `services/`와 자동 manifest만 생성물이며, `openapi/`, `actions/`, `pages/`는 사람이 관리하는 원본이다.
- 생성기/CI 변경 시 기존 생성물 비교, 다른 서비스 격리, 버전별 계약 보존을 유지한다.
- DB 연결/실행 서버 구현 여부와 카탈로그 변환·검증 완료를 구분해 보고한다.
