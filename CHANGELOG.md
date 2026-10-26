# 변경이력 (CHANGELOG)

돔고돔락 프로젝트의 수정 내역입니다. 변경할 때마다 PR을 하나씩 만들어 `main`에 머지했습니다.

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

### 남은 과제 (이번 범위 밖)

- **API:** `OutingApplySerializer`에 `status`가 없어 앱에서 외박 승인 상태를 볼 수 없습니다. Notice 시리얼라이저에도 `image`가 빠져 있습니다.
- **API:** `apply_outing_api`와 웹 `outside` 뷰가 신청자 이름·학번을 로그인 사용자와 대조하지 않습니다.
- **입력 검증:** API `give_point_api`의 `int()` 변환, `assign_room`의 빈 값 처리에서 500 에러가 날 수 있습니다.
- **권한 일관성:** `inquiry_detail_view`만 `is_superuser`로 검사해서 스태프 계정이 웹에서 문의에 답변할 수 없습니다.
- **배포 설정:** `SECRET_KEY` 하드코딩, `DEBUG=True`, `ALLOWED_HOSTS=['*']`, CORS 전체 허용
- **정리:** `web/views.py`의 `dorm_info_view`·`assign_room` 중복 정의, 사용하지 않는 시리얼라이저와 `dorm/urls.py`
