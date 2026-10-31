# 0004. 화면 공통 부분은 include 조각으로 나눈다

- 상태: 채택 (테마 조각 `_theme_css.html`·`_theme_js.html`은 2026-10-31 화면 개편으로 없어짐 → [ADR 0020](0020-ui-design-system.md). `_nav.html`은 계속 씀)
- 날짜: 2026-10-26

## 배경

FreeHTML5 무료 템플릿을 바탕으로 화면을 만들면서, 같은 상단 메뉴(약 85줄)가 템플릿 18개에, 같은 CSS·JS 로드 코드가 십여 개에 복사되어 있었다. 복사본이 조금씩 달라져서 관리자 메뉴가 홈에만 있거나, 없는 CSS를 불러오는 등의 문제가 생겼다(PR #22, #23, #30, #40). 화면마다 `<head>` 구성과 페이지 구조도 달라서 `base.html` 하나로 상속하기 어렵다.

## 결정

공통 부분을 `{% include %}` 조각으로 나눈다.

- `templates/web/_nav.html`: 상단 메뉴. `active`로 강조할 메뉴를 고른다.
- `templates/web/_theme_css.html`: 테마 CSS. `bootstrap5`, `fontawesome` 옵션으로 화면별 추가 파일을 원래 순서대로 불러온다.
- `templates/web/_theme_js.html`: 테마 JS

조각으로 바꿀 때는 화면 비교 도구([tools/](../../tools/README.md))로 수정 전후 화면이 같은지 확인한다.

## 검토한 다른 안

- **`base.html` 상속(`{% extends %}`)으로 한 번에 바꾸기:** 가장 깔끔하지만, 화면마다 다른 `<head>`와 구조를 하나로 맞추다 보면 화면이 바뀌거나 깨질 위험이 크다. 화면 하나씩 확인하며 옮겨야 해서 작업량도 크다.
- **그대로 두기:** 복사본이 계속 어긋난다.

## 결과

- 좋아지는 점: 메뉴 하나를 고치면 모든 화면에 반영된다. PR #22에서 1,564줄, PR #30에서 878줄이 줄었다.
- 감수하는 점: 각 템플릿은 여전히 자기 `<html>` 골격을 가진다. `mypage.html`, `reward_penalty.html`, `inquiry_detail.html`은 구성이 달라서 공통 CSS·JS 조각을 쓰지 않는다.
- 다시 볼 조건: 화면 디자인을 새로 정리하게 되면 그때 `base.html` 상속으로 옮기는 것을 검토한다(Bootstrap 3·5 혼용 정리와 함께).
