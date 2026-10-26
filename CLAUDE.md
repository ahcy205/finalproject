# CLAUDE.md

이 저장소에서 작업하는 AI(Claude Code)가 따르는 규칙입니다. 사람용 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md), 주요 결정과 이유는 [docs/adr/](docs/adr/)에 있습니다.

## 프로젝트

- 돔고돔락: 기숙사 통합 관리 시스템. Django 5.2 + Django REST Framework
- `web` 앱: HTML 화면(Django Template). 자체 모델 없음
- `dorm` 앱: 서비스 모델과 Android 앱용 REST API(`/api/`), API 문서 설명(`dorm/schema.py`)
- `knowledge` 앱: RAG용 원본 자료(`knowledge/data/*.yaml`, 규칙·안내 화면도 이 파일을 씀)와 검색 기능, 문의 답변 초안(`answering.py`, 로컬 LLM은 `llm.py`, 테스트는 `FakeLLM`)
- DB: PostgreSQL 17 + pgvector, `docker compose up -d db`로 실행 → [ADR 0005](docs/adr/0005-postgresql-pgvector.md). DB가 꺼져 있으면 SQLite로 대신 실행하지 않고 `dorm.E001` 점검 오류로 안내한다
- **로컬 실행 전용, 배포하지 않음** → [ADR 0002](docs/adr/0002-local-only.md)

## 명령

```
docker compose up -d db                           # DB 먼저
venv\Scripts\activate
python manage.py test web dorm knowledge          # 전체 테스트 (CI와 같음)
python manage.py spectacular --validate --fail-on-warn --file %TEMP%\schema.yml   # API 문서 검증
python manage.py runserver 127.0.0.1:8001         # 8000이 다른 프로그램에 쓰이고 있으면 8001
python manage.py build_knowledge_index --backend fake   # RAG 검색 자료 다시 만들기 (fake = 모델 없이)
python manage.py evaluate_knowledge_search              # 검색 품질 측정 (knowledge/eval/questions.yaml)
```

## 작업 순서

1. **새 기능, 구조 변경, API 변경**은 설계안(왜 필요한지 / 설계 / 확인 방법 / 위험 / 결정 필요)을 먼저 만들고, 사용자가 승인한 항목만 구현한다.
2. **작은 버그 수정과 문서 수정**은 바로 진행하고 끝난 뒤 보고한다. 사용자가 "설계안 없이 바로"라고 하면 그에 따른다.
3. 항목마다 브랜치와 PR을 하나씩 만든다. `main`에 직접 커밋하지 않는다.
4. 실패하는 테스트를 먼저 쓰고, 고친 뒤 통과를 확인한다. CI가 통과해야 머지한다(머지 커밋, 머지 후 브랜치 삭제).
5. 진행 중 설계와 다르게 해야 하면 먼저 묻고, PR에 "설계와 다른 점"으로 남긴다.
6. 끝나면 `CHANGELOG.md`, README, `docs/flowchart.html` 중 영향받는 문서를 함께 고친다.

## 검증

- 화면이나 API 응답이 바뀔 수 있으면 [tools/](tools/README.md)의 화면 비교로 수정 전후를 비교하고, 의도한 차이만 있는지 PR에 적는다.
- 버그는 실제 요청으로 재현한 뒤 고친다. 재현에는 테스트 DB나 롤백되는 트랜잭션을 쓰고, 개발 DB의 실제 데이터는 바꾸지 않는다.
- "통과했다", "확인했다"는 실제로 명령을 실행한 결과가 있을 때만 말한다.

## 코드 규칙

이 프로젝트에서 실제로 문제가 됐던 것들입니다.

- 화면이나 API에 내보내는 목록은 `order_by`를 명시하고, 동점이 생길 수 있으면 `id`를 보조 기준으로 붙인다(PostgreSQL은 순서를 보장하지 않음).
- 상태를 바꾸는 웹 뷰는 `@require_POST`. 권한은 `@login_required`와 `is_staff` 검사로 확인한다.
- 사용자 입력은 폼이나 시리얼라이저로 검증한다(숫자 변환, 길이, 중복, 이미지 파일 여부). 잘못된 입력에 500이 나면 안 된다.
- 목록 쿼리는 N+1을 피하고(`select_related`, `prefetch_related`, `annotate`), 쿼리 수 테스트로 고정한다.
- API는 필드를 추가만 하고 바꾸거나 지우지 않는다(앱 호환) → [ADR 0003](docs/adr/0003-api-backward-compatibility.md). API를 바꾸면 `dorm/schema.py` 설명도 같이 고친다.
- 상단 메뉴와 테마 CSS·JS는 공통 템플릿(`_nav.html`, `_theme_css.html`, `_theme_js.html`)을 쓰고 복사하지 않는다 → [ADR 0004](docs/adr/0004-template-partials.md).
- 템플릿의 `{% static %}` 경로는 실제 파일이어야 한다(테스트가 검사함).

## 하지 말 것

- 배포 설정 변경(`DEBUG`, `ALLOWED_HOSTS`, CORS). 사용자가 배포하기로 결정하기 전까지 그대로 둔다.
- 강제 푸시, 이력 재작성
- 비밀번호·API 키·토큰 커밋. 비밀 값은 환경변수로 읽는다(`DJANGO_SECRET_KEY` 등).
- `db.sqlite3`, `backups/`(DB 백업), `media/` 커밋
- 승인 없이 파일·데이터·계정 삭제

## 소통

- 사용자에게는 한국어로, 결과를 먼저 짧게 말한다.
- 커밋 메시지와 PR 형식은 [CONTRIBUTING.md](CONTRIBUTING.md)를 따른다.
