"""홈 "오늘의 생활관" 안내판에 쓰는 값 (docs/adr/0020).

새 데이터를 만들지 않고 규칙·식단·셔틀 YAML(knowledge/data)과 외박 신청·공지 DB를 읽기만 한다.
"""
import re

from dorm.models import Notice, OutingApply
from knowledge import sources

RANGE = re.compile(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})')
CLOCK = re.compile(r'^\d{1,2}:\d{2}$')
WEEKDAYS = '월화수목금토일'


def _minutes(text):
    hour, minute = text.split(':')
    return int(hour) * 60 + int(minute)


def _rule_range(keyword):
    """생활관 규칙에서 keyword가 있는 줄의 'HH:MM-HH:MM'. 규칙 문구가 바뀌어도 화면이 따라간다."""
    for section in sources.load('rules')['sections']:
        for article in section['articles']:
            for line in article['lines']:
                found = RANGE.search(line)
                if keyword in line and found:
                    return {'start': found.group(1), 'end': found.group(2)}
    return None


def _meals(weekday):
    if weekday > 4:  # 식단표는 평일만 있다
        return []
    doc = sources.load('menu')
    meals = []
    for meal in doc['meals']:
        times = [row['time'] for row in meal['rows'] if row['time']]
        dishes = [row['dishes'][weekday] for row in meal['rows'] if row['dishes'][weekday]]
        meals.append({'name': meal['name'], 'price': meal['price'], 'time': '–'.join(times), 'dishes': dishes,
                      'end': times[-1] if times else ''})
    return meals


def _shuttles(now_minutes):
    """노선마다 학교에서 출발하는 다음 편. 오늘 남은 편이 없으면 첫차를 알려 준다."""
    result = []
    for route in sources.load('bus')['routes']:
        times = sorted({trip['inbound'][0] for trip in route['trips'] if CLOCK.match(str(trip['inbound'][0]))},
                       key=_minutes)
        upcoming = [t for t in times if _minutes(t) >= now_minutes]
        result.append({'route': route['title'], 'time': upcoming[0] if upcoming else None,
                       'first': times[0] if times else None, 'later': upcoming[1:3]})
    return result


def today_board(now, user=None):
    """now: 현지 시각(aware datetime), user: 로그인한 사용자 또는 None"""
    minutes = now.hour * 60 + now.minute
    entry = _rule_range('출입시간')
    if entry:
        entry['open'] = _minutes(entry['start']) <= minutes < _minutes(entry['end'])
    meals = _meals(now.weekday())
    for meal in meals:
        meal['over'] = bool(meal['end']) and minutes >= _minutes(meal['end'])
    board = {
        'now': now,
        'weekday': WEEKDAYS[now.weekday()],
        'entry': entry,
        'lights_out': _rule_range('소등'),
        'meals': meals,
        'shuttles': _shuttles(minutes),
        'notices': list(Notice.objects.order_by('-date', '-id')[:3]),
        'outing': None,
        'pending_outings': None,
    }
    if user is not None and user.is_authenticated:
        if user.is_staff:
            board['pending_outings'] = OutingApply.objects.filter(status='pending').count()
        else:
            board['outing'] = OutingApply.objects.filter(user=user).order_by('-applied_at', '-id').first()
    return board
