// 상단 메뉴(펼침 메뉴, 모바일 서랍)와 알림 닫기 (docs/adr/0020). jQuery 없이 동작한다.
(function () {
  var bar = document.querySelector('.dg-bar');
  if (bar) {
    var groups = bar.querySelectorAll('.dg-nav__group');
    var opener = bar.querySelector('.dg-bar__menu');
    var closer = bar.querySelector('.dg-nav__close');
    var scrim = document.querySelector('.dg-scrim');
    var wide = window.matchMedia('(min-width: 960px)');

    function closeMenus(except) {
      groups.forEach(function (group) {
        if (group === except) return;
        group.classList.remove('is-open');
        var toggle = group.querySelector('.dg-nav__toggle');
        if (toggle) toggle.setAttribute('aria-expanded', 'false');
      });
    }

    groups.forEach(function (group) {
      var toggle = group.querySelector('.dg-nav__toggle');
      if (!toggle) return;
      toggle.addEventListener('click', function () {
        var open = !group.classList.contains('is-open');
        closeMenus(group);
        group.classList.toggle('is-open', open);
        toggle.setAttribute('aria-expanded', String(open));
      });
      // 마우스로는 올리기만 해도 열린다 (넓은 화면)
      group.addEventListener('mouseenter', function () {
        if (!wide.matches) return;
        closeMenus(group);
        group.classList.add('is-open');
        toggle.setAttribute('aria-expanded', 'true');
      });
      group.addEventListener('mouseleave', function () {
        if (!wide.matches) return;
        group.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });

    document.addEventListener('click', function (event) {
      if (!bar.contains(event.target)) closeMenus();
    });

    function setDrawer(open) {
      bar.classList.toggle('is-drawer-open', open);
      opener.setAttribute('aria-expanded', String(open));
      if (scrim) scrim.hidden = !open;
      document.documentElement.style.overflow = open ? 'hidden' : '';
      if (open) {
        var first = bar.querySelector('.dg-nav__close');
        if (first) first.focus();
      } else {
        opener.focus();
      }
    }
    if (opener) opener.addEventListener('click', function () { setDrawer(true); });
    if (closer) closer.addEventListener('click', function () { setDrawer(false); });
    if (scrim) scrim.addEventListener('click', function () { setDrawer(false); });

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      if (bar.classList.contains('is-drawer-open')) { setDrawer(false); return; }
      var open = bar.querySelector('.dg-nav__group.is-open .dg-nav__toggle');
      closeMenus();
      if (open) open.focus();
    });

    // 넓은 화면으로 바뀌면 서랍 상태를 지운다
    wide.addEventListener('change', function (event) {
      if (event.matches && bar.classList.contains('is-drawer-open')) {
        bar.classList.remove('is-drawer-open');
        opener.setAttribute('aria-expanded', 'false');
        if (scrim) scrim.hidden = true;
        document.documentElement.style.overflow = '';
      }
      closeMenus();
    });
  }

  // 알림: 닫기 버튼, 성공·안내는 6초 뒤 자동으로 사라짐
  function dismiss(toast) {
    toast.classList.add('is-leaving');
    setTimeout(function () { toast.remove(); }, 160);
  }
  document.querySelectorAll('.dg-toast').forEach(function (toast) {
    toast.querySelector('.dg-toast__close').addEventListener('click', function () { dismiss(toast); });
    if (toast.hasAttribute('data-autohide')) setTimeout(function () { dismiss(toast); }, 6000);
  });
})();
