"""안내 화면(규칙·안내·식단·셔틀·편의시설)에 쓰는 값 (docs/adr/0020).

YAML 원본(knowledge/data)은 RAG 색인도 쓰므로 고치지 않고, 화면에 맞게 읽기만 한다.
"""
import re

from web.home import CLOCK, WEEKDAYS, _shuttles

ARTICLE_TITLE = re.compile(r'^(제\s*\d+\s*조(?:의\s*\d+)?)\s*(?:\((.*)\))?\s*$')
CHAPTER_NO = re.compile(r'제\s*(\d+)\s*장')
NUMBERED = re.compile(r'^(\d+)\.\s+(.*)$')
SKIP_MARKS = {'<--', '--', '---', '-->', ''}

# 주변 편의시설 (예전 acc.html의 지도 자료를 그대로 옮김). category 순서가 걸러 보기 버튼 순서다.
CATEGORIES = ('식당', '편의점', '카페', '주유소', '정류장')
PLACES = [
    {'lat': 36.8514, 'lng': 127.0615, 'title': '중앙 정류장', 'category': '정류장'},
    {'lat': 36.8505, 'lng': 127.0620, 'title': 'GS25', 'category': '편의점'},
    {'lat': 36.8505, 'lng': 127.0620, 'title': '블루포트 카페', 'category': '카페'},
    {'lat': 36.8506, 'lng': 127.0606, 'title': '교내식당', 'category': '식당'},
    {'lat': 36.8498, 'lng': 127.0510, 'title': '이마트 24', 'category': '편의점'},
    {'lat': 36.8499, 'lng': 127.0510, 'title': '삼순이 감자탕', 'category': '식당'},
    {'lat': 36.8496, 'lng': 127.0511, 'title': '커피에 반하다', 'category': '카페'},
    {'lat': 36.8495, 'lng': 127.0511, 'title': '기봉이 김밥', 'category': '식당'},
    {'lat': 36.8494, 'lng': 127.0512, 'title': '도향', 'category': '식당'},
    {'lat': 36.8456, 'lng': 127.0449, 'title': 'CU', 'category': '편의점'},
    {'lat': 36.8456, 'lng': 127.0449, 'title': '카페 온더웨이', 'category': '카페'},
    {'lat': 36.8455, 'lng': 127.0472, 'title': 'GS25', 'category': '편의점'},
    {'lat': 36.8450, 'lng': 127.0481, 'title': 'SK 주유소', 'category': '주유소'},
    {'lat': 36.8462, 'lng': 127.0505, 'title': '이레 관광농원 대동 소머리국밥', 'category': '식당'},
    {'lat': 36.8450, 'lng': 127.0478, 'title': '세븐일레븐', 'category': '편의점'},
]


def places():
    """분류 순서대로, 같은 분류 안에서는 원래 순서대로. id는 지도 마커와 목록을 잇는 번호."""
    numbered = [{**place, 'id': i} for i, place in enumerate(PLACES)]
    return sorted(numbered, key=lambda p: (CATEGORIES.index(p['category']), p['id']))


def _blocks(lines):
    """줄 목록 → 문단과 목록. '- 항목'은 점 목록, '1. 항목'은 번호 목록으로 묶는다."""
    blocks = []
    for line in lines:
        text = str(line).strip()
        if text.startswith('- '):
            kind, item = 'ul', text[2:].strip()
        elif NUMBERED.match(text):
            kind, item = 'ol', NUMBERED.match(text).group(2)
        else:
            blocks.append({'type': 'p', 'text': text.lstrip('▣ ').strip() if text.startswith('▣') else text,
                           'lead': text.startswith('▣')})
            continue
        if blocks and blocks[-1]['type'] == kind:
            blocks[-1]['items'].append(item)
        else:
            blocks.append({'type': kind, 'items': [item]})
    return blocks


def _article(article):
    title = str(article['title']).strip()
    found = ARTICLE_TITLE.match(title)
    label, name = (found.group(1).replace(' ', ''), found.group(2) or '') if found else (title, '')
    number = article.get('number')
    return {'id': f'article-{number}' if number else 'article-addenda', 'label': label, 'name': name,
            'blocks': _blocks(article.get('lines') or [])}


def regulation(doc):
    """rules.yaml / info.yaml → 장(제목 없으면 None)과 조항. 앵커 id는 조 번호라 문구가 바뀌어도 유지된다."""
    sections = []
    for i, section in enumerate(doc['sections'], start=1):
        title = section.get('title')
        found = CHAPTER_NO.search(title or '')
        sections.append({
            'id': f'chapter-{found.group(1) if found else i}',
            'title': title,
            'label': f'제{found.group(1)}장' if found else title,
            'name': CHAPTER_NO.sub('', title).strip() if title else '',
            'articles': [_article(a) for a in section['articles']],
        })
    return sections


def penalty_table(doc):
    table = doc.get('penalty_table')
    if not table:
        return None
    return {
        'title': str(table['title']).lstrip('▣ ').strip(),
        'columns': table['columns'],
        'rows': table['rows'],
        'show_note': any(row.get('note') for row in table['rows']),
    }


def week_menu(doc, now):
    """요일마다 중식·석식. 예시 식단이라 날짜가 아니라 요일로 오늘을 찾는다(주말은 없음)."""
    today = WEEKDAYS[now.weekday()]
    meals = []
    for meal in doc['meals']:
        times = [row['time'] for row in meal['rows'] if row['time']]
        meals.append({'name': meal['name'], 'price': meal['price'], 'time': '–'.join(times)})
    days = []
    for i, day in enumerate(doc['days']):
        day_meals = []
        for meal, info in zip(doc['meals'], meals):
            dishes = [row['dishes'][i] for row in meal['rows'] if row['dishes'][i]]
            day_meals.append({**info, 'dishes': dishes})
        days.append({'date': day['date'], 'weekday': day['weekday'], 'is_today': day['weekday'] == today,
                     'meals': day_meals})
    for j, meal in enumerate(meals):  # 넓은 화면 표의 한 줄 (끼니 × 요일)
        meal['cells'] = [{'dishes': day['meals'][j]['dishes'], 'is_today': day['is_today']} for day in days]
    return {'days': days, 'meals': meals, 'weekend': now.weekday() > 4, 'today': today,
            'notes': doc.get('notes') or []}


def _direction(stops, trips, key, next_time=None):
    rows, marked = [], False
    for trip in trips:
        values = [str(v).strip() for v in trip[key]]
        cells = [{'time': v if CLOCK.match(v) else None} for v in values]
        skip = None
        if not any(c['time'] for c in cells):
            # '휴게'·'시간'처럼 두 방향 칸에 나눠 적힌 말은 합쳐서 보여 준다 (outbound → inbound 순서)
            both = [str(v).strip() for v in trip['outbound'] + trip['inbound']]
            words = [v for v in both if v not in SKIP_MARKS and not CLOCK.match(v)]
            skip = ' '.join(words) if words else '운행 안 함'
        is_next = bool(next_time) and not marked and cells[0]['time'] == next_time
        marked = marked or is_next
        rows.append({'bus': str(trip['bus']).strip('() '), 'cells': cells, 'skip': skip, 'is_next': is_next})
    return {'stops': stops, 'rows': rows}


def bus_routes(doc, now):
    """노선마다 학교로 오는 편·학교에서 나가는 편. 학교 출발 다음 편은 홈 안내판과 같은 계산(web.home)."""
    upcoming = {s['route']: s for s in _shuttles(now.hour * 60 + now.minute)}
    routes = []
    for route in doc['routes']:
        shuttle = upcoming.get(route['title'], {})
        next_time = shuttle.get('time')
        routes.append({
            'key': route['key'], 'title': route['title'], 'next': next_time, 'first': shuttle.get('first'),
            'inbound': _direction(route['inbound_stops'], route['trips'], 'inbound', next_time),
            'outbound': _direction(route['outbound_stops'], route['trips'], 'outbound'),
        })
    return routes
