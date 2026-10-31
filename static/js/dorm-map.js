// 카카오 지도 불러오기 (셔틀버스·주변 편의시설, docs/adr/0020).
// 키가 없거나 스크립트를 불러오지 못하면 지도 칸에 안내 문구를 보여 준다. 시간표·목록은 지도 없이도 쓸 수 있다.
(function () {
  var box = document.querySelector('[data-map]');

  function fail() {
    if (!box) return;
    var canvas = box.querySelector('.dg-map__canvas');
    var fallback = box.querySelector('.dg-map__fallback');
    if (canvas) canvas.hidden = true;
    if (fallback) fallback.hidden = false;
    document.documentElement.classList.add('dg-map-off');
  }

  window.dgMapFailed = fail;
  window.dgMapReady = function (init) {
    var canvas = box && box.querySelector('.dg-map__canvas');
    if (!canvas) { fail(); return; }
    if (!(window.kakao && kakao.maps && kakao.maps.load)) { fail(); return; }
    var started = false;
    var timer = setTimeout(function () { if (!started) fail(); }, 8000);
    kakao.maps.load(function () {
      started = true;
      clearTimeout(timer);
      try { init(canvas); } catch (e) { fail(); }
    });
  };
})();
