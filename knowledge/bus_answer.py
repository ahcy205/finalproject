"""셔틀 질문을 시간표에서 직접 답한다 (docs/adr/0017).

모델(exaone)은 시간표를 읽을 때 방향을 자주 반대로 말했다("터미널에서 학교 가는 첫차"에 "학교에서 터미널로 가는 첫차").
질문에서 정류장 하나와 방향이 분명할 때만 bus.yaml에서 시각을 골라 정해진 문장으로 답하고,
조금이라도 애매하면 None을 돌려 지금처럼 모델이 답하게 한다.
"""
import re
from dataclasses import dataclass

from . import sources
from .answering import Draft
from .chunking import TIME, with_ro
from .models import KnowledgeChunk
from .search import SearchHit

BUS_WORDS = re.compile(r'버스|셔틀|첫차|막차|차편|배차')
FIRST = re.compile(r'첫차|제일일찍|가장일찍|가장빠른|제일빠른')
LAST = re.compile(r'막차|마지막')
STOP = '#'  # 질문에서 찾은 정류장 자리
FROM_SCHOOL = re.compile(r'학교에서|학교출발|하교')
FROM_STOP = re.compile(re.escape(STOP) + r'에서')
TO_SCHOOL = re.compile(r'학교(로|에|까지|가|오|도착)|등교')
TO_STOP = re.compile(re.escape(STOP) + r'(으로|로|까지|가는|가|행|도착)')
SCHOOL_STOPS = {'학교 도착', '학교 출발'}


def _compact(text):
    return re.sub(r'\s+', '', text)


@dataclass
class BusPlan:
    route: str       # bus.yaml 노선 key
    direction: str   # 'outbound'(학교로 오는 편) | 'inbound'(학교에서 나가는 편)
    stop: str        # 질문한 정류장 (bus.yaml 이름)
    pick: str        # 'first' | 'last' | 'all'
    trips: list      # [(정류장 시각 또는 학교 출발 시각, 도착 시각)]

    @property
    def chunk_key(self):
        return f'bus:{self.route}:{self.direction}'

    def text(self):
        if self.direction == 'outbound':
            head = f'{self.stop}에서 학교로 오는 셔틀'
            items = [f'{self.stop} {start} 출발(학교 도착 {end})' for start, end in self.trips]
        else:
            head = f'학교에서 {with_ro(self.stop)} 가는 셔틀'
            items = [f'학교 {start} 출발({self.stop} 도착 {end})' for start, end in self.trips]
        if self.pick == 'first':
            return f'{head} 첫차는 {items[0]}이에요 [1].'
        if self.pick == 'last':
            return f'{head} 막차는 {items[-1]}이에요 [1].'
        return f'{head}은 {", ".join(items)}에 있어요 [1]. 하루 {len(items)}편이에요.'


def _stop_names(doc):
    """{띄어쓰기 없는 이름: (bus.yaml 정류장 이름, 노선 key 집합)}. 긴 이름부터 찾도록 정렬한다."""
    aliases = doc.get('stop_aliases', {})
    names = {}
    for route in doc['routes']:
        for stop in route['outbound_stops']:
            if stop in SCHOOL_STOPS:
                continue
            for name in [stop] + aliases.get(stop, []):
                names.setdefault(_compact(name), (stop, set()))[1].add(route['key'])
    return dict(sorted(names.items(), key=lambda item: -len(item[0])))


def lookup(question):
    """질문을 시간표 답으로 바꿀 수 있으면 BusPlan, 애매하면 None."""
    text = _compact(question)
    if not BUS_WORDS.search(text):
        return None
    doc = sources.load('bus')
    found = {}
    for name, (stop, routes) in _stop_names(doc).items():
        if name in text:
            found[stop] = routes
            text = text.replace(name, STOP)
    if len(found) != 1:
        return None  # 정류장이 없거나 둘 이상 (예: 두정역에서 터미널)
    stop, routes = next(iter(found.items()))
    if len(routes) != 1:
        return None  # 두 노선이 함께 서는 정류장 (학교 앞 삼거리)
    if FROM_SCHOOL.search(text):
        direction = 'inbound'
    elif FROM_STOP.search(text) or TO_SCHOOL.search(text):
        direction = 'outbound'
    elif TO_STOP.search(text):
        direction = 'inbound'
    else:
        return None
    route = next(r for r in doc['routes'] if r['key'] in routes)
    stops = route[f'{direction}_stops']
    at = stops.index(stop)
    trips = []
    for trip in route['trips']:
        times = trip[direction]
        if all(TIME.match(t) for t in times):
            trips.append((times[at], times[-1]) if direction == 'outbound' else (times[0], times[at]))
    if not trips:
        return None
    pick = 'first' if FIRST.search(text) else 'last' if LAST.search(text) else 'all'
    return BusPlan(route['key'], direction, stop, pick, trips)


def bus_draft(question):
    """시간표 답을 Draft로 만든다. 근거 [1]은 그 노선·방향의 버스 청크. 답할 수 없거나 청크가 없으면 None."""
    plan = lookup(question)
    if plan is None:
        return None
    chunk = KnowledgeChunk.objects.filter(key=plan.chunk_key).first()
    if chunk is None:
        return None
    return Draft('ok', plan.text(), evidence=[SearchHit(chunk=chunk, score=1.0)], cited=[1], model='bus-table')
