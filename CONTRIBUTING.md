# 개발 규칙

이 저장소에 변경을 올리는 방법입니다. PR #1–#41에서 실제로 써 온 방식을 정리했습니다. AI로 작업할 때의 추가 규칙은 [CLAUDE.md](CLAUDE.md), 주요 결정과 그 이유는 [docs/adr/](docs/adr/)에 있습니다.

## 1. 환경 준비

```
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- Python 3.12
- 비밀 키는 환경변수 `DJANGO_SECRET_KEY`에서 읽습니다. 로컬 개발(`DEBUG=True`)에서는 없어도 실행됩니다.
- DB는 현재 SQLite입니다. PostgreSQL + pgvector로 전환하면 Docker 실행 단계가 추가됩니다([ADR 0005](docs/adr/0005-postgresql-pgvector.md)).

## 2. 작업 단위

- **PR 하나에 항목 하나.** 관련 없는 변경을 섞지 않습니다.
- **새 기능, 구조 변경, API 변경**은 설계안(왜 필요한지 / 설계 / 확인 방법 / 위험)을 먼저 공유하고 합의한 뒤 시작합니다. 작은 버그 수정과 문서 수정은 바로 진행합니다.
- 되돌리기 어려운 결정(DB, 외부 서비스, API 호환성 등)은 [docs/adr/](docs/adr/)에 기록합니다.

## 3. 브랜치

`종류/하는-일` 형식, 영어 소문자와 하이픈을 씁니다. 예: `fix/login-next-redirect`

| 종류 | 쓰는 경우 |
|---|---|
| `fix/` | 버그·보안 수정 |
| `feat/` | 새 기능 |
| `refactor/` | 동작을 바꾸지 않는 구조 정리 |
| `perf/` | 성능 개선 |
| `docs/` | 문서만 변경 |
| `chore/`, `ci/` | 정리, 설정, CI |

## 4. 커밋 메시지

영어로 씁니다.

- **첫 줄:** 무엇을 했는지 명령형으로 짧게. 예: `Fix N+1 queries in the board page and the posts API`
- **본문:** 왜 바꿨는지. 어떤 문제가 있었고 무엇을 바꿨는지 2–5줄
- AI가 함께 작성한 커밋은 끝에 `Co-Authored-By:` 줄을 남깁니다.

## 5. PR

- **제목과 본문은 한국어**로 씁니다. 본문은 PR 템플릿의 순서(문제 → 변경 → 설계와 다른 점 → 확인)를 따릅니다.
- **CI가 통과해야 머지**합니다. CI는 설정 점검, 마이그레이션 누락 검사, API 문서 검증, 테스트를 실행합니다.
- 머지는 **머지 커밋** 방식으로 하고, 머지한 브랜치는 삭제합니다.
- 강제 푸시로 이력을 고치지 않습니다. 되돌릴 때는 되돌림 커밋을 씁니다.

## 6. 테스트

```
python manage.py test web dorm
```

- 웹 화면 테스트는 `web/tests.py`, 모델과 API 테스트는 `dorm/tests.py`에 둡니다.
- **버그 수정에는 그 버그를 재현하는 테스트를 함께 추가합니다.** 수정 전에는 실패하고 수정 후에는 통과해야 합니다.
- 외부 서비스(AI API 등)는 가짜 응답으로 바꿔서, API 키 없이도 테스트와 CI가 돌아가게 합니다.
- 화면이나 API 응답이 바뀔 수 있는 변경은 [tools/](tools/README.md)로 수정 전후를 비교하고 결과를 PR에 적습니다.

## 7. 코드에서 지킬 것

- 상태를 바꾸는 웹 요청은 POST만 받습니다(`@require_POST`). 권한은 `@login_required`와 `is_staff`로 검사합니다.
- 사용자 입력은 폼이나 시리얼라이저로 검증합니다. 잘못된 입력에 500 에러가 나면 안 됩니다.
- 목록 화면과 API는 N+1 쿼리를 피하고, 쿼리 수 테스트로 고정합니다.
- 앱 API는 필드를 **추가만** 합니다([ADR 0003](docs/adr/0003-api-backward-compatibility.md)). API를 바꾸면 `dorm/schema.py` 설명도 고칩니다.
- 상단 메뉴, 테마 CSS·JS는 공통 템플릿을 씁니다([ADR 0004](docs/adr/0004-template-partials.md)).
- 비밀번호, API 키, `db.sqlite3`, `media/`는 커밋하지 않습니다.

## 8. 변경이력

기능·버그 PR이 머지되면 [CHANGELOG.md](CHANGELOG.md)에 PR 번호와 함께 기록합니다. 문서만 바꾼 PR은 생략할 수 있습니다.
