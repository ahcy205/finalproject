# 검증 도구

화면이나 API 응답이 바뀔 수 있는 수정을 할 때, 수정 전후를 비교해 **의도한 차이만 생겼는지** 확인하는 도구입니다. 테스트를 대신하지 않고, 테스트가 잡기 어려운 "다른 화면이 같이 바뀌지 않았는지"를 확인하는 용도입니다.

| 파일 | 하는 일 |
|---|---|
| `snapshot.py` | 임시 테스트 DB에 예시 데이터를 만들고, 화면 30개와 게시글 API 3개를 비로그인·학생·관리자로 렌더링해 저장 (99개 파일) |
| `compare_snapshots.py` | 두 스냅샷 폴더를 공백 차이를 빼고 비교해서 바뀐 줄만 출력 |
| `check_static_refs.py` | 화면과 CSS가 참조하는 `/static/` 파일이 실제로 있는지 검사 |

실제 `db.sqlite3`는 사용하지 않습니다. 같은 코드라면 몇 번을 실행해도 결과가 똑같습니다.

## 사용 순서

가상환경을 켠 상태에서 프로젝트 폴더에서 실행합니다.

```
# 1. 수정 전 (main 상태)
python tools/snapshot.py tools/snapshots/before

# 2. 코드 수정

# 3. 수정 후
python tools/snapshot.py tools/snapshots/after

# 4. 비교
python tools/compare_snapshots.py tools/snapshots/before tools/snapshots/after
```

- 마지막 줄에 `99/99개 화면이 같습니다`가 나오면 화면 변화가 없는 것입니다.
- 차이가 있으면 바뀐 화면 이름과 줄이 `-`(수정 전), `+`(수정 후)로 나옵니다. 의도한 차이인지 확인하고 PR의 "확인"에 적습니다.
- 설명용 HTML 주석만 지운 경우처럼 주석 차이를 무시하려면 `--ignore-comments`를 붙입니다.
- 정적 파일 경로를 바꿨다면 `python tools/check_static_refs.py tools/snapshots/after`도 실행합니다.

`tools/snapshots/`는 `.gitignore`에 들어 있어 커밋되지 않습니다.

## 화면을 추가했을 때

새 화면이 생기면 `snapshot.py`의 `pages()` 목록에 주소를 추가하고, 필요한 예시 데이터는 `seed()`에 추가합니다.
