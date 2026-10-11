# Spring Cloud Config 연결

## 역할과 설정

이 저장소는 Config Server가 읽는 Git backend입니다. 실행 가능한 Spring Boot 서버를 포함하지 않습니다.
Config Server는 버전별 YAML을 제공하고, 리소스 해석·검증·DB 반영은 동기화 서버가 담당합니다.

[examples/config-server.application.yaml](../examples/config-server.application.yaml)을
Config Server 자체 설정에 반영합니다. `@EnableConfigServer`와 버전 호환성이 맞는 Spring Cloud 구성이
있는 서버를 전제로 합니다. Git 기본 브랜치는 이 저장소의 `master`입니다.
`clone-on-start`는 기동 시 저장소 접근 실패를 드러내고, `refresh-rate: 0`은 요청 시 Git 상태를 갱신합니다.
카탈로그 동기화 주기 자체는 동기화 서버의 스케줄러가 결정합니다.

`search-paths`는 지정하지 않습니다. plain-text 요청의 경로에 `services/...`, `actions/...`, `pages/...`를 포함합니다.
리소스 하위 디렉터리를 search-path로 중복 등록하지 않습니다.
운영에서는 Config Server 접근 인증, Git 읽기 자격증명, 재사용 가능한 checkout 디렉터리를 서버 환경에 설정합니다.
이 저장소에는 실행 환경의 자격증명 값을 저장하지 않습니다.

## 두 API의 구분

| 용도 | 요청 | 사용 데이터 |
| --- | --- | --- |
| 현재 브랜치 revision 확인 | `GET /resource-catalog/default/master` | Environment JSON의 `version`과 설정 marker |
| 개별 리소스 조회 | `GET /resource-catalog/default/{sha}/services/member-api.yaml` | 생성된 Service YAML (엔드포인트별 요청·응답 계약 포함) |

루트 `resource-catalog.yaml`은 Environment API에 규격 버전을 알리는 작은 설정입니다.
리소스 문서 자체를 Spring property source로 평탄화하거나 여러 YAML을 속성 우선순위로 합성하지 않습니다.
일반 `/{application}-{profile}.yaml` 렌더링 API도 카탈로그 원본 조회에 사용하지 않습니다.

Spring의 plain-text API는 `/{application}/{profile}/{label}/{path}`를 지원하고,
Git backend의 label에는 커밋 ID를 사용할 수 있습니다.
plain-text 파일은 `${...}` 치환과 profile별 파일 선택이 일어날 수 있으므로
카탈로그에서는 placeholder를 금지하고 **profile을 `default`로 고정**합니다.
`*-default.yaml` 같은 파일을 별도 오버레이로 만들지 않습니다.

## 조회 절차

1. 정상 인증된 Config Server에서 Environment 응답을 읽습니다.
2. `version`이 유효한 전체 Git SHA인지 확인하고 해당 동기화 시도의 `source-revision`으로 확정합니다.
3. 같은 SHA의 Git checkout 또는 Git 트리 API로 services/actions/pages 아래의 전체 YAML 경로를 탐색합니다.
   기본 plain-text API는 개별 파일 조회용이므로 파일 목록은 동기화 서버가 Git에서 구합니다.
   트리 API의 pagination/truncated 여부를 확인하여 완전한 목록임을 보장합니다.
   이후 모든 파일 조회는 **같은 SHA**를 label로 사용합니다.
4. 파일별 성공 응답과 YAML 해석, 전체 스키마 및 참조 검증이 모두 성공해야 diff를 만듭니다.
5. 처리 중 master가 바뀌면 현재 snapshot과 섞지 않고 다음 동기화 시도에서 새 SHA를 읽습니다.
6. Config Server의 checkout 캐시가 이전 SHA를 반환해도 완료 상태를 오인하지 않도록 주기적으로 재조회합니다.

웹훅은 동기화 작업을 깨우는 신호로 사용할 수 있습니다. 오래되거나 순서가 뒤집힌 웹훅의 SHA를
그대로 적용하지 말고, 설정된 저장소·브랜치의 현재 HEAD를 다시 조회합니다.
새 HEAD가 아직 Config Server에 보이지 않으면 재시도하고 다른 revision으로 성공 처리하지 않습니다.
PR 검증용 merge SHA와 실제 master에 병합된 SHA가 다를 수 있습니다.

다음 명령은 Config Server가 실행 중일 때 수동으로 확인하는 예제입니다.

```sh
CONFIG_SERVER_URL='http://localhost:8888'
curl --fail --silent --show-error \
  "$CONFIG_SERVER_URL/resource-catalog/default/master"

# 위 JSON의 version을 그대로 복사합니다. placeholder를 실제 SHA로 교체합니다.
CATALOG_REVISION='<environment-version>'
curl --fail --silent --show-error \
  "$CONFIG_SERVER_URL/resource-catalog/default/$CATALOG_REVISION/services/member-api.yaml"
```

소비자는 HTTP timeout, bounded retry, 응답 크기 한도를 적용하고 HTML 오류 페이지나 빈 응답을
빈 카탈로그로 처리하지 않습니다. Git 트리에서 얻은 resource 경로는 고정된 세 디렉터리와
이 저장소의 경로 규칙을 검사한 뒤 조회합니다. 파일 목록 탐색이 불완전하면 DB 반영을 중단합니다.
환경설정 marker가 가리키는 임의의 외부 URL을 따라가지 않습니다.
카탈로그 전체를 내려받아 격리된 임시 디렉터리에 보관한 뒤 같은 검증 규칙을 적용할 수 있습니다.
`python scripts/catalog.py --root <download-directory> --from-generated`는 OpenAPI JSON 없이
내려받은 생성 YAML과 Action/Page를 검증합니다. 검증기와 schema는 배포된 신뢰 버전을 사용합니다.
CI에서는 이 옵션을 쓰지 않고 JSON 원본과 생성물의 일치까지 검사합니다.
Service YAML에 호출에 필요한 요청/응답·참조 스키마·서버·인증 계약이 포함되므로 JSON을 추가 조회할 필요는 없습니다.
참조 루트는 Service.spec이며 설명용 문서와 미사용 컴포넌트는 전달하지 않습니다.
원본과 생성물의 동일성은 CI에서 검증합니다. --from-generated는 원본 대비 임의 수정 여부를 판정하지 않습니다.

## 연결 시 확인할 항목

- `resource-catalog/default/master`에서 `version`과 `resource-ops.api-version` marker를 확인합니다.
- 같은 SHA의 Git 트리에서 찾은 YAML 파일 6개를 읽어 리소스 8개와 참조 10개가 만들어지는지 확인합니다.
- Action의 서비스 참조를 확인하고 직접 작성한 method·path를 등록 정의와 대조해 일치하는 Endpoint 연결을 도출하는지 확인합니다.
- Page별 사용 계약 4개를 도출하고 동일 Action의 요청/응답 규칙이 각 Page에 독립적으로 적용되는지 확인합니다.
- master가 변경되어도 이전 SHA 조회 결과가 그대로 유지되는지 확인합니다.
- 존재하지 않는 파일·label, 잘못된 YAML, 네트워크 장애가 DB 변경으로 이어지지 않는지 확인합니다.
- consumer는 지원하는 `api-version`의 스키마/검증기를 배포에 포함하고 알 수 없는 버전은 거부합니다.
  저장소가 제공하는 새 스키마를 자동 실행하거나 알 수 없는 규격을 동적으로 수용하지 않습니다.

위 항목은 실제 Config Server와 동기화 서버 연결 시 수행할 통합 검증입니다.
저장소의 Python 테스트는 카탈로그 검증기만 실행하며 Config Server/DB 통합 실행을 대신하지 않습니다.

## 공식 자료

- [Spring Cloud Config: Serving Plain Text](https://docs.spring.io/spring-cloud-config/reference/server/serving-plain-text.html)
- [Spring Cloud Config: Git Backend](https://docs.spring.io/spring-cloud-config/reference/server/environment-repository/git-backend.html)
- [Spring Cloud Config: Environment Repository](https://docs.spring.io/spring-cloud-config/reference/server/environment-repository.html)
