# 원본 자료 (knowledge/data)

생활관 규칙·안내 문구의 원본입니다. **화면(`/rules/`, `/info/`)과 RAG 검색 색인이 같은 파일을 씁니다.** 문구를 고칠 때는 템플릿이 아니라 이 파일을 고칩니다.

| 파일 | 화면 | 내용 |
|---|---|---|
| `rules.yaml` | `/rules/` 생활관 규칙 | 조항 15개 + 제14조의2 + 부칙, 벌점표, 벌점 안내문 |
| `info.yaml` | `/info/` 생활관 안내 | 8개 장, 조항 27개 |

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

## 고칠 때

- 문구를 고치면 화면에는 바로 반영됩니다. RAG 검색 자료는 색인을 다시 만들 때 반영됩니다.
- 규칙 화면은 줄바꿈이 그대로 보이는 스타일(`white-space: pre-line`)이라, 템플릿(`templates/web/rules.html`)의 줄 구조는 바꾸지 않습니다.
- 고친 뒤 `python manage.py test knowledge`로 형식이 맞는지 확인합니다.
