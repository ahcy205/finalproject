# 변경이력 (CHANGELOG)

돔고돔락 프로젝트의 수정 내역입니다. 변경할 때마다 PR을 하나씩 만들어 `main`에 머지했습니다.






## 2026-10-27 (13차) — RAG 4단계: 학생 챗봇

| PR | 내용 |
|---|---|
| [#54](https://github.com/ahcy205/finalproject/pull/54) | 챗봇 핵심 로직: 공개 자료만 사용, 검사를 통과한 답만 표시, 챗봇 평가 (ADR 0011) |
| [#55](https://github.com/ahcy205/finalproject/pull/55) | 챗봇 화면 `/chatbot/`, 상단 메뉴, 추천 질문 버튼, 1분 10회 요청 제한 |
| [#56](https://github.com/ahcy205/finalproject/pull/56) | 앱용 챗봇 API `POST /api/chatbot/` |
| [#57](https://github.com/ahcy205/finalproject/pull/57) | 익명 대화 기록(180일), 👍/👎, 관리자 목록, 못 답한 질문 내보내기 (ADR 0012) |
| [#58](https://github.com/ahcy205/finalproject/pull/58) | 챗봇 콜드 스타트 줄이기: 모델 유지 30분, 화면 열 때 미리 깨우기 (ADR 0013) |
| #59 | 이어지는 대화: 대화 기억, 메시지 종류 판단(Jev), 인사·다시 말하기·요약 (ADR 0014) |

- **사내·학교 FAQ형:** 자주 묻는 질문에 바로 답하고, 못 답한 질문을 찾아 자료를 보강하는 방식으로 설계했습니다. 다른 학생의 문의는 근거로 쓰지 않습니다.
- **답을 보여 주는 조건:** 근거가 충분하고, 인용 번호가 맞고, 앞 두 문장에서 "자료에 없다"고 하지 않을 때만 보여 줍니다. 그 밖에는 "답을 찾지 못했어요" 또는 관련 자료 링크를 보여 줍니다.
- **지시문:** 학생용으로 따로 쓴 지시문은 사실 오류가 늘어 버리고, 검증된 관리자 초안 지시문을 그대로 씁니다.
- **측정 (2회):** 사실 정확도 0.97 / 0.90, 정답 근거 인용 0.97 / 0.94, 잘못 거절 0.03 / 0.06, 범위 밖 거절 0.80 / 0.90. 범위 밖 질문 1건("휴학 신청")에서 근거에 없는 서류 안내를 덧붙인 한계를 ADR에 기록했습니다.
- **챗봇 화면(#55):** 로그인한 사용자는 "생활관 안내 → AI 챗봇"에서 질문할 수 있습니다. 답 아래에 출처(규정 조항, 원문 링크)를 보여 주고, 답을 못 찾으면 문의를 안내합니다. 자주 묻는 질문 8개는 버튼으로 두었습니다(`knowledge/data/faq_suggestions.yaml`). 한 사용자는 1분에 10번까지 질문할 수 있습니다. 모델이 쓴 `**굵게**` 기호는 지우고 보여 줍니다.
- **앱용 API(#56):** `POST /api/chatbot/`에 `{"question": "..."}`를 보내면 웹 챗봇과 같은 `{status, text, sources}`를 돌려줍니다. Token 인증이 필요하고, 요청 제한은 웹과 합산합니다. API 문서(`/api/docs/`)에 "AI 챗봇" 항목으로 설명을 추가했습니다.
- **익명 기록과 개선 순환(#57):** 질문(개인정보 가림)·답·근거·👍/👎를 사용자와 연결하지 않고 저장합니다. 평가는 답과 함께 받은 일회용 키로 한 번만 할 수 있고, 키는 해시로만 저장합니다. 180일이 지난 기록은 `purge_chat_logs`로 지우고, 못 답했거나 👎 받은 질문은 `export_chat_misses`로 평가 질문 형식으로 뽑아 자료 보강에 씁니다. 관리자는 Django 관리자 화면에서 읽기 전용으로 봅니다. 앱 API 응답에는 `log_id`, `feedback_token`이 추가됐고 `POST /api/chatbot/feedback/`이 생겼습니다.
- **응답 속도(#58):** 느린 원인은 답을 만드는 시간(3~4초)이 아니라 모델을 처음 올리는 시간이었습니다. Ollama가 5분 쉬면 모델을 내리던 것을 30분으로 늘리고(`KNOWLEDGE_LLM_KEEP_ALIVE`), 챗봇 화면을 열면 두 모델을 동시에, 실제 질문과 같은 설정으로, 지시문까지 미리 읽혀 둡니다. 모델이 모두 내려간 상태에서 첫 답이 13초 → 3.2~3.5초가 됐습니다.
- **이어지는 대화(#59):** "다시 말해줘", "요약해줘", "고마워"에도 답합니다. 대화는 서버 캐시에만 30분 동안 최근 3턴을 기억하고(DB 저장 없음), 화면에 "새 대화" 버튼이 생겼습니다. 메시지 종류는 판단 전용 모델 Jev(TypeSafe)로 고릅니다. 정답을 붙인 64문장에서 규칙은 처음 보는 표현에 0.44, 로컬 exaone은 0.88~0.92, Jev는 1.00(0.2초)이었습니다. 이를 위해 개인정보를 가린 마지막 메시지와 앞 한 턴이 외부로 전송되며(승인됨), 키가 없거나 실패하면 로컬 판단기로 바뀝니다. 다시 말하기·요약은 앞 답의 근거 원문으로 다시 쓰고 같은 검사를 거칩니다(두 번 측정, 표시 27/27, 원문에 없는 숫자 1건 / 0건). 앱 API에 `conversation_id`, `kind`가 추가됐습니다.

## 2026-10-26 (12차) — RAG 3단계: 문의 답변 초안

| PR | 내용 |
|---|---|
| [#49](https://github.com/ahcy205/finalproject/pull/49) | 로컬 LLM(Ollama) 호출, 답변 초안 만들기, 근거 부족 기준값 측정 (ADR 0007) |
| [#50](https://github.com/ahcy205/finalproject/pull/50) | 관리자 문의 화면에 "AI 답변 초안 만들기" 버튼과 근거 목록 |
| [#51](https://github.com/ahcy205/finalproject/pull/51) | 로컬 LLM 3개 비교, 기본 모델 exaone3.5:7.8b 확정 (ADR 0008) |
| [#52](https://github.com/ahcy205/finalproject/pull/52) | 검색어 동의어 보강: "전기장판"으로 물어도 "전열기" 규칙을 찾음 (ADR 0009) |
| [#53](https://github.com/ahcy205/finalproject/pull/53) | 답변 초안 지시문 개선: 예시 2개와 근거 뒤 한 줄 상기 (ADR 0010) |

- **로컬 LLM(`knowledge/llm.py`):** 유료 API 대신 이 PC에서 Ollama로 모델을 실행합니다. 비용이 없고 문의 내용이 PC 밖으로 나가지 않습니다. 기본 모델은 `exaone3.5:7.8b`이고, 후보 세 개 비교는 다음 PR에서 합니다.
- **답변 초안(`knowledge/answering.py`):** 문의에서 개인정보를 가림 → 근거 5개 검색 → 근거가 약하면 모델을 부르지 않음 → 모델이 근거만으로 [번호]를 붙여 작성 → 없는 번호를 인용했거나 인용이 없으면 경고. 답변된 문의는 자기 자신을 근거로 쓰지 않습니다.
- **근거 부족 기준값 0.45:** 답할 수 있는 평가 질문 32개는 모두 통과하고, 기숙사 자료로 답할 수 없는 질문 10개(평가 파일에 새로 추가) 중 4개를 모델 호출 전에 거릅니다. 나머지는 모델의 "확인할 수 없습니다" 답변이 맡습니다.
- **테스트:** 모델 대역(`FakeLLM`)으로 11개를 추가했습니다(Ollama 없이 CI에서 실행).
- **관리자 화면(#50):** 문의 상세의 "AI 답변 초안 만들기"를 누르면 초안을 답변 칸에 채우고, 사용한 근거 5개(인용된 근거 표시, 원문 링크, 유사도)와 경고를 보여 줍니다. 저장하기 전에는 아무것도 바뀌지 않고, 학생에게 자동으로 보내지 않습니다. 근거가 약하거나 Ollama가 꺼져 있으면 이유를 보여 주고 기존 답변 칸은 그대로 둡니다.
- **모델 비교(#51):** 평가 질문 29개에 "답에 들어 있어야 할 사실"을 붙이고 `evaluate_answer_drafts` 명령으로 측정했습니다.

| 모델 | 사실 정확도 | 정답 근거 인용 | 시간 중앙값 | 범위 밖 질문에서 지어냄 |
|---|---|---|---|---|
| **exaone3.5:7.8b (채택)** | **0.93** | **0.94** | 3.5초 | 6개 중 2 (추측) |
| qwen3:8b | 0.90 | 0.88 | 2.8초 | 6개 중 2 ("졸업 136학점" 등) |
| gemma4:e2b | 0.83 | 0.88 | 0.8초 | 0 |

  사실 정확도와 정답 근거 인용이 가장 높은 exaone을 기본으로 둡니다. 초안 원문은 `knowledge/eval/results/`에 있습니다.
- **검색어 보강(#52):** `knowledge/data/synonyms.yaml`의 일상어 → 규정 용어 목록으로 질문을 보강합니다. 평가 질문 hit@5 0.97 → 1.00, MRR 0.826 → 0.854. 평가에 없는 새 질문 10개에서도 5위 밖이던 3개를 찾게 됐고 나빠진 질문은 없습니다.
- **지시문 개선(#53):** 규칙을 늘린 안은 오히려 나빠져서, 규칙은 짧게 두고 예시 2개(답변·거절)와 근거 뒤 한 줄 상기를 넣었습니다. 두 번 잰 평균으로 정답 근거 인용 0.93 → 1.00, 인용 형식 문제 0.04 → 0, 범위 밖 질문에서 지어낸 구체적 내용 회당 2–3건 → 0건. 셔틀 방향 혼동도 사라졌습니다.

## 2026-10-26 (11차) — RAG 2단계: 검색 자료 저장소

| PR | 내용 |
|---|---|
| [#46](https://github.com/ahcy205/finalproject/pull/46) | 검색 자료 테이블(pgvector + pg_trgm), 자료 나누기, 개인정보 가리기, 색인 명령, 가짜 임베딩 |
| [#47](https://github.com/ahcy205/finalproject/pull/47) | 공지·문의를 저장하거나 지울 때 검색 자료 자동 갱신 |
| [#48](https://github.com/ahcy205/finalproject/pull/48) | 실제 임베딩 모델(bge-m3), 하이브리드 검색, 평가 질문 32개, 모델 3개 비교 (ADR 0006) |

- **테이블 `KnowledgeChunk`:** 1024차원 벡터와 HNSW 인덱스(코사인)로 의미 검색, 트라이그램 GIN 인덱스로 키워드 검색을 합니다. 마이그레이션이 `vector`·`pg_trgm` 확장도 만듭니다.
- **자료 나누기(`knowledge/chunking.py`):** 지금 데이터로 66개입니다.

| 자료 | 단위 | 개수 |
|---|---|---|
| 규칙 | 조항 + 벌점표 | 18 |
| 안내 | 조항 | 27 |
| 셔틀버스 | 노선 × 방향 | 4 |
| 식단 | 하루 | 5 |
| 공지 | 공지 하나 | 11 |
| 문의 | 답변이 달린 문의만 | 1 |

- **개인정보(`knowledge/privacy.py`):** 전화번호, 이메일, 학번처럼 보이는 숫자, 문의 작성자의 이름·아이디를 가린 뒤 저장합니다. 문의는 비공개라 근거 링크를 두지 않습니다.
- **색인 명령:** `python manage.py build_knowledge_index`. 바뀐 청크만 다시 임베딩하고, 원본에서 사라진 청크는 지웁니다. 임베딩 모델을 바꾸면 전부 다시 임베딩합니다.
- **임베딩 방식:** 실제 모델(`sentence-transformers`, 기본 bge-m3)과 테스트·CI용 가짜 임베딩(`fake`)을 설정으로 고릅니다. 실제 모델 라이브러리 설치와 검색 품질 비교는 다음 PR에서 합니다.
- **관리자 화면:** Django 관리자에서 검색 자료를 읽기 전용으로 볼 수 있습니다.
- **테스트:** 13건을 추가해 총 130건입니다.
- **자동 갱신(#47):** 공지를 저장하면 청크를 추가·수정하고, 지우면 삭제합니다. 문의는 답변이 달리면 추가하고, 답변이나 문의가 지워지면 삭제합니다.
  - 내용이 바뀐 청크는 벡터를 비워 두고, 임베딩은 색인 명령이 채웁니다. 모델 실행이 느려서 요청 중에는 하지 않습니다.
  - 검색 자료 갱신이 실패해도 공지·문의 저장은 막지 않고 오류만 기록합니다. 저장점으로 감싸서 바깥 트랜잭션도 그대로 쓸 수 있습니다.
  - 백업 불러오기(`loaddata`) 중에는 건너뜁니다.
  - 테스트를 5건 추가해 총 135건입니다.
- **검색과 모델 선택(#48):**
  - **하이브리드 검색**(`knowledge/search.py`): 의미 검색(pgvector)과 키워드 검색(pg_trgm)의 순위를 RRF로 합칩니다. 검색 직전에 아직 벡터가 없는 새 청크를 최대 20개까지 임베딩합니다.
  - **평가**: 학생 말투 질문 32개(`knowledge/eval/questions.yaml`)로 `python manage.py evaluate_knowledge_search`를 실행합니다.
  - **측정 결과** (자세한 내용은 [ADR 0006](docs/adr/0006-embedding-model-and-hybrid-search.md)):
    - 표준 RRF(k=60)는 1위 정확도를 0.72에서 0.50으로 떨어뜨렸습니다. 그래서 k=1, 키워드 비중 0.25로 바꿨습니다.
    - 임베딩 모델은 **bge-m3**를 채택했습니다(hit@5 0.97, MRR 0.826). e5-large는 1위 정확도가 조금 높지만 512토큰 제한이 있고, KURE-v1이 가장 낮았습니다.
  - **설치**: `requirements-ml.txt`(PyTorch CPU, sentence-transformers 등 40개)로 분리해서 CI에는 설치하지 않습니다. 모델 파일은 `HF_HOME`(이 PC는 `D:\HFCache`)에 저장합니다.
  - **테스트**: 11건을 추가해 총 146건입니다.

## 2026-10-26 (10차) — RAG 2단계: 원본 자료 분리

RAG 검색 자료로 쓸 생활관 규칙·안내 문구를 템플릿 HTML에서 데이터 파일로 옮겼습니다. 이제 화면과 검색이 같은 원본을 씁니다.

| PR | 내용 |
|---|---|
| [#44](https://github.com/ahcy205/finalproject/pull/44) | 새 앱 `knowledge`, `knowledge/data/rules.yaml`·`info.yaml`, 규칙·안내 화면을 데이터로 그리도록 변경 |
| #45 | 셔틀버스 시간표·식단표도 `knowledge/data/bus.yaml`·`menu.yaml`로 분리 |

- **데이터 만들기:** 템플릿을 프로그램으로 읽어 만들었습니다. 손으로 옮겨 적다가 생길 오타를 막기 위해서입니다. 결과는 규칙 조항 17개(제14조의2·부칙 포함)·벌점표 24행·안내문 3줄, 안내 8개 장·조항 27개로, 템플릿과 개수가 같습니다.
- **템플릿 크기:** `rules.html` 170줄 → 60줄, `info.html` 179줄 → 46줄
- **줄바꿈 유지:** 규칙 화면은 줄바꿈이 그대로 보이는 스타일(`pre-line`)이라, 화면 비교와 별도로 그 영역의 줄 구조 134줄을 한 줄씩 비교해 같음을 확인했습니다.
- **화면 비교:** 99개 화면이 모두 같습니다. 큰따옴표가 `&quot;`로 바뀌어 나가는 차이가 있지만 브라우저에서는 똑같이 보입니다.
- **테스트:** 데이터 형식과 화면 표시 테스트 7건을 추가했고(총 113건), 테스트 명령은 `python manage.py test web dorm knowledge`입니다.
- **버스·식단(#45):** 버스는 노선 2개에 각 12편, 식단은 5일 × 중식·석식입니다. 식단 HTML에 있던 짝이 맞지 않는 `</span>` 태그는 빠졌습니다(브라우저가 원래 무시하던 태그라 화면은 같음). 버스 화면은 그대로입니다.
- **원본 내용에서 확인이 필요한 것:**
  - 천안아산역 방면 시간표의 돌아가는 편이 `탕정역 09:45 → 천안아산역 09:30`처럼 시간이 거꾸로 되어 있습니다. 실제 운행 정보라 고치지 않고 그대로 옮겼습니다.
  - 식단은 2025년 6월 한 주의 예시입니다.

## 2026-10-26 (9차) — RAG 1단계: PostgreSQL + pgvector 전환

[RAG 도입 설계안](https://claude.ai/artifact/XSi6mvRkCP2sihnV5AZUPg)을 승인받아 1단계를 진행했습니다. 승인된 결정은 다음과 같습니다.
- 임베딩은 bge-m3로 시작하고 2단계에서 KURE-v1·multilingual-e5와 측정해서 확정합니다.
- 답변 생성은 Claude Opus 5.5를 씁니다.
- 학생용 챗봇은 3단계 평가를 통과한 뒤 진행합니다.
- SQLite 원본은 보관하고, SQLite로 대신 실행하는 기능은 두지 않습니다.

| PR | 내용 |
|---|---|
| #43 | DB를 SQLite에서 PostgreSQL 17 + pgvector(Docker)로 전환, 기존 데이터 이전, CI에 PostgreSQL 추가 |

### 변경
- `docker-compose.yml`: `pgvector/pgvector:0.8.1-pg17` 이미지. 127.0.0.1에서만 접속할 수 있고, Docker Desktop 그룹 이름은 `dorm_project`입니다.
- `settings.py`: DB 접속 정보를 환경변수(`POSTGRES_*`)에서 읽습니다. 로컬 개발 기본값이 있고, `DEBUG=False`면 비밀번호가 필수입니다.
- `dorm/checks.py`: DB에 접속할 수 없으면 서버 실행·마이그레이션·테스트 전에 `dorm.E001` 오류와 해결 방법(`docker compose up -d db`)을 보여 줍니다.
- `psycopg[binary]==3.3.6` 추가
- CI: GitHub Actions에 같은 PostgreSQL 이미지를 서비스로 추가
- 문서: README·CONTRIBUTING·CLAUDE.md 실행 방법, ADR 0005를 "채택"으로 변경, 흐름도의 DB 표기

### 전환하며 고친 문제
- **백업 불러오기 실패:** 백업을 불러올 때 "계정이 생기면 프로필 자동 생성" 신호가 실행돼 프로필이 중복으로 생겼습니다. 백업 불러오기(`raw=True`)일 때는 만들지 않도록 고쳤습니다.
- **목록 순서:** SQLite는 정렬을 지정하지 않은 목록을 번호순으로 돌려줬지만, PostgreSQL은 순서를 보장하지 않습니다(게시글 API의 댓글 순서가 실제로 바뀜). 그래서 화면과 API의 목록 13곳에 정렬을 명시했습니다. SQLite 때와 같은 순서가 나오도록, 동점일 때는 번호 오름차순을 보조 기준으로 썼습니다.
- **백업 파일 인코딩:** Windows에서 `dumpdata -o`가 UTF-8이 아닌 기본 인코딩(cp949)으로 저장해서, UTF-8 모드(`PYTHONUTF8=1`)로 다시 내보냈습니다.

### 데이터 이전 (로컬)
1. 원본 보관: `backups/db.sqlite3.before-postgres` (git 제외)
2. 내보내기: `PYTHONUTF8=1 python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e sessions -o backups/sqlite-dump.json`
3. PostgreSQL에서 `migrate` → `loaddata backups/sqlite-dump.json`
4. 확인
   - 14개 모델, 102건이 원본과 모두 일치
   - 새 데이터의 번호가 기존 번호 다음부터 이어짐
   - 관리자 로그인 정상
   - 로그인 세션은 옮기지 않아서 다시 로그인해야 합니다.

### 검증
- 테스트 106건 통과 (PostgreSQL)
- `tools/`로 SQLite 때와 PostgreSQL에서 99개 화면·API 응답을 비교: 모두 같음

## 2026-10-26 (8차) — 개발 규칙 문서화

대화로 정해 온 작업 규칙을 저장소 문서로 옮겼습니다. 설계안을 검토·승인받아 진행했습니다.

| PR | 내용 |
|---|---|
| [#41](https://github.com/ahcy205/finalproject/pull/41) | 화면 전후 비교 검증 도구를 `tools/`에 추가 (스냅샷, 비교, 정적 파일 검사) |
| #42 | `CLAUDE.md`(AI 작업 규칙), `CONTRIBUTING.md`(개발 규칙), `docs/adr/` 0001–0005(결정 기록), PR 템플릿 |

- 결정 사항: 설계안은 새 기능·구조·API 변경에만 작성하고, 작은 버그·문서 수정은 바로 진행한 뒤 보고합니다. 커밋 메시지는 영어, PR은 한국어로 씁니다.
- ADR 0005(PostgreSQL + pgvector)는 RAG 설계안 승인 전이라 "제안" 상태입니다.
- 설계와 다른 점: `CLAUDE.md`가 `tools/`를 가리켜서, 링크가 깨지지 않도록 검증 도구 PR을 먼저 올렸습니다.

## 2026-10-26 (7차) — 정적 파일 404 수정

| PR | 내용 |
|---|---|
| #40 | 없는 `css/bootstrap.min.css`를 불러오던 링크 정리, 게시글·공지 삭제 확인 화면에 스타일 적용, 없는 정적 파일 참조 검사 테스트 |

- **실제 404 확인:** 서버를 띄우고 브라우저로 화면을 열어 로그를 보니, 실제 404는 `css/bootstrap.min.css` 하나였습니다. CSS 안의 폰트·이미지 경로 9개는 화면에서 쓰이지 않아 요청되지 않으므로, 서드파티 CSS는 수정하지 않았습니다.
- **게시판·공지 화면 7개:** Bootstrap 5가 이미 CDN으로 로드되고 있었습니다. 404 나는 링크는 처음부터 아무 역할이 없었으므로 지웠습니다. 화면 변화는 없습니다.
- **게시글·공지 삭제 확인 화면 2개:** 불러오는 CSS가 이 깨진 파일 하나뿐이라 스타일이 전혀 없었습니다. 프로젝트의 `static/bootstrap.min.css`(Bootstrap 5.3.5)를 가리키게 해서 버튼 색과 여백이 원래 의도대로 표시됩니다.
- **재발 방지:** 템플릿의 `{% static %}` 경로가 모두 실제 파일인지 검사하는 테스트를 추가했습니다(`StaticReferenceTests`).
- **확인:** 수정 후 브라우저에서 화면 9개를 열어 404가 0건임을 확인했습니다. 99개 화면 비교에서는 깨진 링크 제거와 경로 수정만 달라졌습니다. 테스트는 100건 통과입니다.

## 2026-10-26 (6차) — 보완 설계안 실행

[보완 설계안](https://claude.ai/artifact/U7GRXJBNSkZPfcFoFWqzX6)을 검토·승인받은 뒤 7개 항목을 진행했습니다(PR #32–#39).

결정 사항은 다음과 같습니다.
- 페이지 나누기: A안(선택형)
- 메뉴 아이콘 8개: 유지
- 공지·자유게시판 목록: 로그인 필수

| PR | 설계안 | 내용 |
|---|---|---|
| [#32](https://github.com/ahcy205/finalproject/pull/32) | 1 | GitHub Actions CI: PR마다 설정 점검·마이그레이션 누락 검사·테스트 실행, README 배지 |
| [#33](https://github.com/ahcy205/finalproject/pull/33) | 2 | N+1 쿼리 개선: 글 20개 기준 게시글 API 103 → 4번, 자유게시판 35 → 5번 |
| [#34](https://github.com/ahcy205/finalproject/pull/34) | 3 | 게시글 API `?page=` 선택형 페이지 나누기 (20개씩, `page` 없으면 기존처럼 전체) |
| [#35](https://github.com/ahcy205/finalproject/pull/35) | 5 | 앱 로그아웃 API `POST /api/logout/` (Token 삭제) |
| [#36](https://github.com/ahcy205/finalproject/pull/36) | 7 | 로그인 필요 알림창 링크 14곳을 실제 링크로 교체, 공지·게시판 목록 로그인 필수, 로그인 후 원래 페이지로 이동 |
| [#37](https://github.com/ahcy205/finalproject/pull/37) | 6 | 미사용 정적 파일 23개 삭제 (메뉴 아이콘 8개·`sass/`는 유지) |
| [#38](https://github.com/ahcy205/finalproject/pull/38) | 4 | API 문서: drf-spectacular 0.30.0, Swagger `/api/docs/`, 19개 엔드포인트 설명, CI에 문서 검증 추가 |
| #39 | — | 변경이력·README·흐름도 갱신 |

### 설계와 달라진 점
- **#32:** 실패 확인용 커밋을 이력에서 지울 계획이었습니다. 하지만 강제 푸시가 권한 설정에서 막혀 있어서 되돌림 커밋으로 처리했습니다. 최종 변경 내용은 같습니다.
- **#34:** 정렬에 글 번호(`-id`)를 보조 기준으로 추가했습니다. 작성 시각이 같은 글이 있으면 순서가 흔들려서, 페이지를 넘길 때 같은 글이 두 번 나오거나 빠질 수 있었기 때문입니다(테스트에서 실제로 발생).
- **#38:** 설계에 더해 CI에 문서 검증 단계를 넣었습니다. API를 바꾸고 문서를 고치지 않으면 CI가 실패합니다. 문서 그룹 순서도 앱에서 쓰는 순서로 정했습니다.

### 검증 방법
화면을 바꿀 수 있는 PR(#33, #34, #36, #37, #38)은 수정 전후로 99개 화면·API 응답을 임시 DB에서 렌더링해 비교했습니다. 의도한 차이만 있는지 확인했습니다.

### 새로 발견한 문제 (수정하지 않음)
정적 파일을 정리하다가 **없는 파일을 참조하는 곳 10개**를 찾았습니다(브라우저에서 404).
- 화면 7개가 불러오는 `css/bootstrap.min.css`: 실제 파일은 `static/bootstrap.min.css`에 있습니다.
- CSS가 가리키는 `css/fonts/icomoon.*`, `css/fonts/flexslider-icon.*`, `css/owl.video.play.png`: 해당 경로에 파일이 없습니다.

다음 설계안에서 검토받겠습니다.

### 앱 영향
- 로그아웃 버튼에서 `POST /api/logout/`을 호출하면 서버의 Token도 무효화됩니다.
- 게시글 목록은 `?page=1`부터 요청하면 20개씩 받을 수 있습니다. 요청하지 않으면 기존과 같습니다.
- 요청·응답 형식은 `/api/docs/`에서 확인할 수 있습니다.

### 테스트

`python manage.py test web dorm`: 총 99건 (웹 66, API 33). PR마다 GitHub Actions에서도 실행됩니다.

### 남은 사항

- ~~없는 정적 파일 참조 10곳~~ → #40에서 해결
- **로컬 실행 전용:** 배포하지 않으므로 `DEBUG=True`, `ALLOWED_HOSTS=['*']`, CORS 전체 허용을 그대로 둡니다.
- **일부 화면의 head 구성:** `mypage.html`, `reward_penalty.html`, `inquiry_detail.html`은 불러오는 CSS·JS 구성이 달라서 공통 템플릿을 쓰지 않습니다.
- **Bootstrap 3·5 혼용:** 화면 7개가 두 버전을 함께 불러옵니다. 화면을 다시 디자인해야 해서 다루지 않았습니다.

## 2026-10-26 (5차) — 남은 과제 정리

남은 과제를 처리했습니다(PR #25–#31). 이 프로젝트는 배포하지 않기로 해서, 배포 설정은 그대로 두고 "로컬 실행 전용"으로 문서에 적었습니다.

| PR | 구분 | 내용 |
|---|---|---|
| [#25](https://github.com/ahcy205/finalproject/pull/25) | API | 외박 응답에 `status`, 공지 응답에 `image` 추가. 공지 작성 API에서 이미지 업로드 가능 (기존 필드 유지) |
| [#26](https://github.com/ahcy205/finalproject/pull/26) | 권한 | 웹 문의 상세도 `is_staff` 기준으로 통일. 스태프가 열람·답변 가능 |
| [#27](https://github.com/ahcy205/finalproject/pull/27) | 데이터 | `OutingApply.user` 외래키 추가, 기존 신청을 학번이 같은 계정에 연결하는 마이그레이션 `0005` |
| [#28](https://github.com/ahcy205/finalproject/pull/28) | 검증 | 침대 번호 선택지에 `0 = 미배정` 추가(마이그레이션 `0006`, DB 변경 없음), 10자 넘는 학번 거부 |
| [#29](https://github.com/ahcy205/finalproject/pull/29) | 검증 | 앱 회원가입 API에도 비밀번호 규칙 적용 |
| [#30](https://github.com/ahcy205/finalproject/pull/30) | 리팩터링 | 테마 CSS·JS 로드 코드를 `_theme_css.html`, `_theme_js.html`로 분리 (878줄 삭제) |
| #31 | 문서 | 변경이력·README·흐름도 갱신 |

### 로컬 DB에 적용한 마이그레이션
- `0005_outingapply_user`: 기존 외박 기록 5건 중 3건이 계정에 연결됐습니다. 나머지 2건은 같은 학번의 계정이 없어서 연결되지 않았고, 관리자 목록에서만 보입니다. 이 2건은 이전에도 학생 목록에 나오지 않던 기록입니다.
- `0006_dorm_position_unassigned_choice`: 선택지 정보만 바꿔서 실제 DB 변경이 없습니다.
- 되돌리려면 `python manage.py migrate dorm 0004`를 실행하면 됩니다.

### 앱 영향
- API 응답에는 필드를 **추가만** 해서 기존 앱이 쓰던 값은 그대로입니다.
- 회원가입 API는 이제 약한 비밀번호를 400으로 거부합니다. 앱 화면에 서버 오류 메시지를 보여 주면 됩니다.

### 테스트

`python manage.py test web dorm`: 총 81건 (웹 60, API 21)

## 2026-10-26 (4차) — 포트폴리오 정리

포트폴리오로 보여 주기 좋게 README, 화면 코드, 설정을 다듬었습니다(PR #19–#24).

| PR | 구분 | 내용 |
|---|---|---|
| [#19](https://github.com/ahcy205/finalproject/pull/19) | 문서 | README에 시스템 구조도(Mermaid)와 코드 점검·개선 요약 추가 |
| [#20](https://github.com/ahcy205/finalproject/pull/20) | 정리 | 무료 템플릿 meta 태그·홈 화면 미완성 문구("작성해주세요") 정리, README에 원작 템플릿 출처(CC BY 3.0) 표시 |
| [#21](https://github.com/ahcy205/finalproject/pull/21) | 보안 | `SECRET_KEY`를 코드에서 빼고 환경변수 `DJANGO_SECRET_KEY`로 읽기 |
| [#22](https://github.com/ahcy205/finalproject/pull/22) | 리팩터링 | 18개 템플릿에 복사된 상단 메뉴를 `templates/web/_nav.html` 하나로 분리 (1,564줄 삭제) |
| [#23](https://github.com/ahcy205/finalproject/pull/23) | 버그 | 관리자 메뉴를 모든 페이지에 표시, 하드코딩된 서버 IP 링크 수정, 샘플 전화번호·SNS 아이콘 제거 |
| #24 | 문서 | 변경이력·README·흐름도 갱신 |

### #21 SECRET_KEY 분리
- 환경변수가 없으면 `DEBUG=True`일 때만 개발용 키를 쓰고, `DEBUG=False`면 서버가 시작되지 않습니다.
- 노출된 기존 키는 더 이상 쓰지 않습니다(키 교체). 그래서 기존 로그인 세션은 한 번 로그아웃됩니다. 앱 Token과 비밀번호에는 영향이 없습니다.

### #22 · #23 상단 메뉴 공통화
- 같은 메뉴가 18개 파일에 복사되어 파일마다 조금씩 달라져 있었습니다. 강조 메뉴가 다르거나, 관리자 메뉴가 홈에만 있었습니다.
- #22는 화면 결과를 바꾸지 않는 순수 리팩터링입니다. 30개 페이지를 비로그인·학생·관리자로 렌더링한 90개 화면을 수정 전후로 비교했고, 공백을 빼면 모두 같았습니다.
- #23에서 메뉴 한 파일만 고쳐 문제 세 가지를 해결했습니다.
  - 관리자 메뉴가 홈에서만 보이던 문제
  - 관리자 링크가 예전 서버 IP(`43.202.118.147`)로 하드코딩되어 있던 문제
  - 템플릿 샘플 전화번호와 연결 없는 SNS 아이콘이 보이던 문제
- 브라우저에서 홈과 생활관 안내 화면이 정상 표시되는 것을 확인했습니다.

### 테스트

`python manage.py test web dorm`: 총 61건 (웹 51, API 10)

## 2026-10-26 (3차) — 코드 · git 정리

동작은 바꾸지 않고 코드와 저장소를 정리했습니다(PR #15–#18). 정리하다가 발견한 화면 버그 1건(게시글 삭제 화면의 작성일)도 함께 고쳤습니다.

| PR | 구분 | 내용 |
|---|---|---|
| [#15](https://github.com/ahcy205/finalproject/pull/15) | 정리 | 사용하지 않는 코드와 중복 URL 정리 |
| [#16](https://github.com/ahcy205/finalproject/pull/16) | 버그 | 잘못된 페이지 제목과 게시글 삭제 화면의 작성일 표시 수정 |
| [#17](https://github.com/ahcy205/finalproject/pull/17) | git | 업로드 파일·개인 설정 추적 해제, `requirements.txt` 추가 |
| #18 | 문서 | README 실행 방법·DB 표기, 변경이력 갱신 |

### #15 사용하지 않는 코드 정리
- `SignupSerializer`, `LoginSerializer`, `dorm/urls.py`(어디에도 include되지 않음) 삭제
- pyflakes로 찾은 미사용 import 삭제
- `web/urls.py`에 두 번씩 있던 `dorminfo/`, `assign_room/` 패턴을 하나로 정리하고, URL 이름을 `web:dorminfo`로 통일
- `dorm/app.py` → `dorm/apps.py`: Django는 `apps.py`에서만 AppConfig를 찾기 때문에 기존 `DormConfig`가 무시되고 있었습니다.

### #16 페이지 제목 · 작성일
- 게시글 삭제·수정 페이지가 "공지사항 …"으로 표시되던 제목과 문구를 "게시글 …"로 수정
- 공지 수정 페이지의 탭 제목 "공지사항 상세보기"를 "공지사항 수정"으로 수정
- 게시글 삭제 확인 화면이 없는 필드 `post.date`를 써서 작성일이 항상 빈칸이었습니다. `created_at`으로 고쳤습니다.

### #17 git 정리
- `media/`(업로드 이미지 16개), `.idea/`(5개), `.DS_Store`(6개)를 git 추적에서 빼고 `.gitignore`에 추가
- 가상환경 기준 `requirements.txt` 추가
- **주의:** 다른 PC에서 pull하면 그쪽 작업 폴더에서 위 파일들이 삭제됩니다. 필요하면 pull 전에 백업하거나, pull 후에 `git restore --source=593905b --worktree -- media .idea`로 되살릴 수 있습니다.

### #18 문서
- README: DB 항목을 "MariaDB (배포) / SQLite (로컬 개발)"로 구분하고, 로컬 실행 방법·테스트 명령·흐름도·변경이력 링크 추가

### 테스트

`python manage.py test web dorm`: 총 53건 (웹 43, API 10)

## 2026-10-26 (2차) — 보안 · 입력 검증

전체를 다시 점검하면서 찾은 보안 문제 4건과 500 에러를 고쳤습니다(PR #9–#13). 문제는 모두 롤백되는 테스트 데이터로 실제 요청을 보내 재현했고, 재현용 데이터와 파일은 남기지 않았습니다. API 테스트(`dorm/tests.py`)를 이번에 처음 추가했습니다.

### 요약

| PR | 구분 | 내용 | 변경 파일 |
|---|---|---|---|
| [#9](https://github.com/ahcy205/finalproject/pull/9) | 보안 | 문의 상세 API를 작성자와 관리자만 볼 수 있게 수정 | `dorm/permissions.py`, `dorm/views.py` |
| [#10](https://github.com/ahcy205/finalproject/pull/10) | 보안 | 공지 수정 시 이미지 파일만 업로드되게 검증 | `web/views.py` |
| [#11](https://github.com/ahcy205/finalproject/pull/11) | 보안 | 외박 신청 시 로그인한 본인 명의인지 확인 | `web/views.py`, `dorm/views.py` |
| [#12](https://github.com/ahcy205/finalproject/pull/12) | 보안 | 관리자 학생 검색을 화면의 검색 항목으로 제한 | `web/views.py` |
| [#13](https://github.com/ahcy205/finalproject/pull/13) | 버그 | 잘못된 입력으로 나던 500 에러를 오류 메시지로 처리 | `web/views.py`, `dorm/views.py`, `templates/web/check_in.html`, `templates/web/dorminfo.html` |
| #14 | 문서 | 변경이력 갱신, 흐름도(`docs/flowchart.html`) 추가 | `CHANGELOG.md`, `docs/flowchart.html` |

---

### #9 문의 상세 API 권한
- **문제:** `IsInquiryUserOrAdmin`이 GET 요청을 무조건 허용했습니다. 그래서 문의 id만 알면 **로그인하지 않은 사람이나 다른 학생도** `/api/inquiries/<id>/`로 남의 문의와 답변을 읽을 수 있었습니다.
- **변경:** 로그인한 작성자나 스태프만 허용합니다. 비로그인 요청은 401, 다른 학생은 403으로 거부합니다. 답변(POST)은 기존대로 스태프만 할 수 있습니다.

### #10 공지 이미지 검증
- **문제:** `notice_update`가 업로드된 파일을 검사하지 않고 저장해서, 스크립트가 든 `.html` 파일도 `media/`에 저장되고 사이트 주소로 열렸습니다.
- **변경:** 공지 작성처럼 `NoticeForm`(Pillow 이미지 검증)을 거칩니다. 이미지가 아니면 오류 메시지를 보여 주고, 새 파일이 없으면 기존 이미지를 유지합니다.

### #11 외박 신청 본인 확인
- **문제:** 웹 `/outside/` POST와 앱 `/api/outing_apply/`가 이름·학번을 로그인 계정과 비교하지 않아서, 다른 학생 이름으로 신청할 수 있었습니다. `/apply_outing/`은 날짜가 비면 500 에러가 났습니다.
- **변경:** 웹의 두 경로가 같은 `_save_outing` 함수(폼 검증 + 본인 확인)를 씁니다. API는 본인이 아니면 403으로 응답합니다.

### #12 관리자 학생 검색 필드 제한
- **문제:** 검색의 `else` 분기가 URL의 `field` 값을 그대로 조회 조건으로 써서, `field=user__password`로 비밀번호 해시를 조건 검색할 수 있었습니다. 없는 필드를 넣으면 500 에러가 났습니다.
- **변경:** 화면에 있는 이름·학과만 허용하고, 그 외 필드는 결과 없음으로 처리합니다.

### #13 입력 검증 (500 에러)
| 위치 | 입력 | 변경 후 |
|---|---|---|
| 웹 `/check_in/`, API `/api/dorm_apply/` | 이미 등록된 학번 | 오류 메시지 / 400 |
| 웹 `/assign_room/<id>/` | 빈칸, 숫자가 아닌 값 | 빈칸은 기존 값 유지, 방 번호는 숫자, 침대는 1~4만 허용 |
| API `/api/give_point/` | 숫자가 아닌 점수 | 400 |
| API `/api/outing_apply/` | 날짜 형식 오류 | 400 |

- `check_in.html`, `dorminfo.html`에 메시지 표시 영역을 추가했습니다. 기존에는 오류 메시지가 화면에 보이지 않았습니다.
- `web/views.py`에 두 번씩 정의되어 있던 `assign_room`, `dorm_info_view` 중 쓰이지 않던 앞쪽 정의를 삭제했습니다.

### 테스트

```
venv\Scripts\python manage.py test web dorm
```

웹 41건, API 10건, 총 51건입니다.

| 테스트 클래스 | 확인 내용 |
|---|---|
| `InquiryDetailApiTests` | 비로그인·다른 학생 차단, 작성자·관리자 조회, 작성자 답변 차단 |
| `NoticeImageTests` | html 업로드 거부, 이미지 허용, 기존 이미지 유지 |
| `OutingIdentityTests`, `OutingApplyApiTests` | 본인 명의만 저장, 빈 날짜 처리 |
| `AdminStudentSearchTests` | 이름·학과 검색, 비밀번호 필드 차단, 없는 필드 처리 |
| `CheckInDuplicateTests`, `AssignRoomTests`, `InputValidationApiTests` | 학번 중복, 방 배정 입력, API 점수·날짜 형식 |

## 2026-10-26 — 보안 및 웹 기능 버그 수정

코드 분석에서 나온 우선순위 높은 문제 4건을 고쳤습니다(PR #1–#4). 이어서 고친 내용을 다시 검토했고, 그때 발견한 후속 문제 3건도 고쳤습니다(PR #5–#7).

### 요약

| PR | 구분 | 내용 | 변경 파일 |
|---|---|---|---|
| [#1](https://github.com/ahcy205/finalproject/pull/1) | 보안 | 상벌점 페이지 관리자 권한 검사 추가 | `web/views.py` |
| [#2](https://github.com/ahcy205/finalproject/pull/2) | 보안 | 외박 승인/거절·댓글 삭제·좋아요를 POST로만 허용 | `web/views.py` |
| [#3](https://github.com/ahcy205/finalproject/pull/3) | 버그 | 마이페이지 로그인 필수화, `LOGIN_URL` 설정 | `web/views.py`, `finalproject/settings.py` |
| [#4](https://github.com/ahcy205/finalproject/pull/4) | 버그 | 웹 마이페이지 문의 등록 기능 수정 | `web/views.py`, `templates/web/mypage.html` |
| [#5](https://github.com/ahcy205/finalproject/pull/5) | 후속 (#1) | 상벌점 페이지에 처리 결과 메시지 표시 | `templates/web/reward_penalty.html` |
| [#6](https://github.com/ahcy205/finalproject/pull/6) | 후속 (#3) | 로그인 후 원래 요청한 페이지로 이동 | `web/views.py` |
| [#7](https://github.com/ahcy205/finalproject/pull/7) | 후속 (#4) | 마이페이지 탭 자동 전환 시 버튼 선택 표시 | `templates/web/mypage.html` |

각 PR에는 `web/tests.py` 테스트가 함께 들어 있습니다. PR #7은 jsdom으로 따로 확인했습니다.

---

### #1 상벌점 페이지 관리자 권한 검사 추가
- **문제:** `/reward/` 뷰(`reward_penalty`)에 권한 검사가 없었습니다. 그래서 로그인하지 않은 사람도 아무 학생의 상점·벌점을 바꿀 수 있었습니다. 점수에 숫자가 아닌 값을 넣으면 `int()` 변환에서 500 에러도 났습니다.
- **변경:**
  - `@login_required` + `@user_passes_test(lambda u: u.is_staff)` 추가
  - 점수가 숫자가 아니거나 `point_type`이 `reward`/`penalty`가 아니면 에러 메시지를 보여주고 되돌아감
- **참고:** 로그인한 학생이 이 페이지에 접근하면 로그인 페이지로 이동합니다. 다른 관리자 전용 페이지와 같은 방식입니다.

### #2 상태를 바꾸는 요청을 POST로만 허용
- **문제:** `approve_outing`, `reject_outing`, `delete_comment`, `toggle_like`가 GET 요청으로도 실행됐습니다. 링크를 열기만 해도(다른 사이트에 심어 둔 이미지 태그 등으로도) 데이터가 바뀔 수 있었습니다.
- **변경:** 네 뷰에 `@require_POST` 추가. GET 요청에는 405 응답을 보냅니다.
- **영향:** 템플릿(`outinfo.html`, `community_detail.html`)은 이미 POST 폼과 `{% csrf_token %}`을 쓰고 있어서 화면 동작은 그대로입니다.

### #3 마이페이지 로그인 필수화 및 `LOGIN_URL` 설정
- **문제:**
  1. 로그아웃 상태로 `/mypage/`에 접속하면 `AnonymousUser`로 DB를 조회하다가 500 에러가 났습니다.
  2. `LOGIN_URL`이 설정되어 있지 않아서, `@login_required`가 붙은 모든 페이지가 존재하지 않는 `/accounts/login/`으로 이동했습니다(404).
- **변경:** `mypage_view`에 `@login_required` 추가, `settings.py`에 `LOGIN_URL = 'web:login'` 추가

### #4 웹 마이페이지 문의 등록 기능 수정
- **문제:** 마이페이지 "문의하기" 폼은 `mypage_view`로 POST를 보내는데, 뷰에 POST 처리 코드가 없어서 문의가 저장되지 않았습니다.
- **변경:**
  - 학생이 보낸 `InquiryForm`을 검증한 뒤 로그인한 사용자 이름으로 저장
  - 등록 후 `/mypage/?tab=inquiry`로 이동해 "문의하기" 탭이 열린 상태로 표시
  - 입력 오류가 나면 오류 메시지와 함께 "문의하기" 탭 표시

### #5 상벌점 페이지에 처리 결과 메시지 표시 (#1 후속)
- **문제:** 뷰가 만드는 성공·오류 메시지를 `reward_penalty.html`이 표시하지 않았습니다. 그래서 메시지가 나중에 다른 페이지(게시글 상세 등)에서 뒤늦게 나타났습니다.
- **변경:** 제목 아래에 Bootstrap alert로 메시지 표시 (`error` 태그는 `alert-danger`)

### #6 로그인 후 원래 요청한 페이지로 이동 (#3 후속)
- **문제:** #3 이후 로그인이 필요한 페이지는 `/login/?next=...`로 이동합니다. 그런데 `login_views`가 `next`를 무시해서 로그인하면 항상 홈으로 갔습니다.
- **변경:**
  - `next`를 템플릿 hidden 필드로 전달하고, 로그인에 성공하면 그 주소로 이동
  - `url_has_allowed_host_and_scheme`로 같은 사이트 주소일 때만 이동 (외부 사이트로 보내는 오픈 리다이렉트 방지)
  - 로그인에 실패해도 `next` 값 유지

### #7 마이페이지 탭 자동 전환 시 버튼 선택 표시 (#4 후속)
- **문제:** `?tab=inquiry`나 검색 결과로 페이지가 열릴 때 탭 내용은 바뀌지만, 탭 버튼은 하나도 선택되지 않았습니다.
- **변경:** 클릭 이벤트 없이 `showTab`을 호출하면 해당 탭 id가 들어 있는 버튼을 찾아 활성화

---

### 테스트

이 프로젝트의 첫 자동 테스트를 `web/tests.py`에 추가했습니다(22건).

```
venv\Scripts\python manage.py test web
```

| 테스트 클래스 | 확인 내용 |
|---|---|
| `RewardPenaltyTests` | 비로그인·학생 차단, 관리자 허용, 잘못된 점수 입력, 결과 메시지 표시 |
| `GetRequestsDoNotChangeStateTests` | 4개 기능이 GET은 무시하고 POST로만 동작 |
| `LoginRedirectTests` | 비로그인 시 웹 로그인 페이지로 이동 |
| `MypageInquiryTests` | 문의 정상 등록, 빈 입력은 저장하지 않음 |
| `LoginNextTests` | `next` 유지·이동, 외부 URL 차단, 실패 시 유지 |
