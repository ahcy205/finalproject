# 원본 자료 (knowledge/data)

생활관 규칙·안내 문구의 원본입니다. **화면(`/rules/`, `/info/`)과 RAG 검색 색인이 같은 파일을 씁니다.** 문구를 고칠 때는 템플릿이 아니라 이 파일을 고칩니다.

| 파일 | 화면 | 내용 |
|---|---|---|
| `rules.yaml` | `/rules/` 생활관 규칙 | 조항 15개 + 제14조의2 + 부칙, 벌점표, 벌점 안내문 |
| `info.yaml` | `/info/` 생활관 안내 | 8개 장, 조항 27개 |
| `bus.yaml` | `/bus/` 셔틀버스 | 노선 2개(천안 터미널·천안아산역 방면), 노선마다 12편 |
| `menu.yaml` | `/menu/` 주간 식단표 | 5일 × 중식·석식 (2025년 6월 16–20일 예시 식단) |
| `synonyms.yaml` | (화면 없음) | 검색어 보강: 학생이 쓰는 말 → 규정 용어 ([ADR 0009](../../docs/adr/0009-query-synonyms.md)) |
| `faq_suggestions.yaml` | `/chatbot/` AI 챗봇 | 첫 화면의 추천 질문 버튼 ([ADR 0011](../../docs/adr/0011-student-chatbot.md)) |

## 형식

```yaml
page: rules            # 자료 이름 (knowledge.sources.load()에 넘기는 값)
url: /rules/           # 이 자료를 보여 주는 화면 (검색 결과의 근거 링크로 씀)
title: 생활관 규칙
sections:              # 장. 장이 없는 문서는 title: null 인 장 하나
- title: 제 1 장 구분
  articles:            # 조항. RAG 검색에서 조항 하나가 검색 단위(청크)가 됨
  - title: 제1조 (목적)  # 화면에 보이는 제목 그대로
    number: '1'        # 조 번호. "제14조의2"는 '14-2'. 부칙처럼 번호가 없으면 생략
    lines:             # 화면에서 줄바꿈되는 단위
    - 이 수칙은 ...
```

`rules.yaml`에는 위 형식 외에 벌점표(`penalty_table`)와 표 아래 안내문(`notes`)이 있습니다.

### 표 형식 (bus, menu)

```yaml
# bus.yaml
routes:
- key: terminal                 # 화면의 표 id (table-terminal)
  title: 천안 터미널 방면
  outbound_stops: [천안 터미널, ..., 학교 도착]   # 학교로 오는 편
  inbound_stops: [학교 출발, ..., 천안 터미널]    # 학교에서 나가는 편
  trips:
  - bus: (1호차)
    outbound: ['08:25', ...]     # outbound_stops와 같은 순서·개수
    inbound: ['09:20', ...]

# menu.yaml
days: [{date: 06월 16일, weekday: 월}, ...]
meals:
- name: 중식
  price: 4,500원
  rows:                          # 화면의 표 한 줄
  - time: '11:00'
    dishes: [떡만두국, ...]       # days와 같은 순서·개수
```

`bus.yaml`과 `menu.yaml`의 `notes`는 화면에 표시되지 않고, 검색 자료를 만들 때 함께 쓰는 설명입니다.

`bus.yaml`의 `stop_aliases`는 챗봇이 질문에서 정류장을 찾을 때 쓰는 다른 이름입니다(`정류장 이름: [다른 이름, ...]`, 띄어쓰기 무시). 정류장을 추가하거나 이름을 바꾸면 함께 고칩니다 ([ADR 0017](../../docs/adr/0017-bus-answers-from-timetable.md)).

## 고칠 때

- 문구를 고치면 화면에는 바로 반영됩니다. RAG 검색 자료는 `python manage.py build_knowledge_index`를 실행할 때 반영됩니다(바뀐 조항만 다시 임베딩). 공지와 답변된 문의는 저장할 때 내용이 자동으로 반영되고, 임베딩만 색인 명령이 채웁니다.
- 규칙 화면은 줄바꿈이 그대로 보이는 스타일(`white-space: pre-line`)이라, 템플릿(`templates/web/rules.html`)의 줄 구조는 바꾸지 않습니다.
- 고친 뒤 `python manage.py test knowledge`로 형식이 맞는지 확인합니다.
