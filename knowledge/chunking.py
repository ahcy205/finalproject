"""원본 자료를 검색 단위(청크)로 나눈다.

| 자료 | 청크 단위 | 이유 |
|---|---|---|
| 생활관 규칙·안내 | 조항 하나 | 답변 근거로 "제3조에 따라"처럼 조항을 인용할 수 있다 |
| 벌점표 | 표 전체 + 안내문 하나 | 행 하나는 너무 짧아 검색이 불안정하다 (24행이라 한 청크에 들어감) |
| 셔틀버스 | 노선 × 방향 하나 | "터미널 가는 버스" 같은 질문이 노선·방향 단위다 |
| 식단 | 하루 하나 | "수요일 식단" 같은 질문이 하루 단위다 |
| 공지 | 공지 하나 | |
| 문의 | 답변이 달린 문의 하나 (문의 + 답변) | 답변이 없는 문의는 근거가 될 수 없어 제외 |

모든 청크는 개인정보를 가린 뒤 만든다(knowledge.privacy).
"""
import hashlib
import re
from dataclasses import dataclass, field

from django.urls import reverse

from . import sources
from .models import KnowledgeChunk
from .privacy import mask_personal_info

Source = KnowledgeChunk.Source
TIME = re.compile(r'^\d{1,2}:\d{2}$')


@dataclass
class Chunk:
    source: str
    key: str
    title: str
    content: str
    url: str = ''
    metadata: dict = field(default_factory=dict)

    def content_hash(self):
        return hashlib.sha256(f'{self.title}\n{self.content}'.encode('utf-8')).hexdigest()


def regulation_chunks(page):
    """생활관 규칙(rules)·안내(info): 조항 하나 = 청크 하나."""
    doc = sources.load(page)
    source = Source.RULES if page == 'rules' else Source.INFO
    chunks = []
    for section in doc['sections']:
        for index, article in enumerate(section['articles']):
            number = article.get('number')
            ident = f'article:{number}' if number else f'section:{section["title"] or ""}:{index}'
            heading = ' '.join(x for x in (doc['title'], section['title'], article['title']) if x)
            chunks.append(Chunk(
                source=source, key=f'{page}:{ident}', title=heading,
                content='\n'.join(article['lines']), url=doc['url'],
                metadata={'page': page, 'article': number, 'article_title': article['title'],
                          'section': section['title']},
            ))
    if 'penalty_table' in doc:
        table = doc['penalty_table']
        lines = [f'{row["no"]}. {row["violation"]}: {row["points"]}' + (f' ({row["note"]})' if row['note'] else '')
                 for row in table['rows']]
        chunks.append(Chunk(
            source=source, key=f'{page}:penalty_table', title=f'{doc["title"]} 벌점 기준 (별표1)',
            content='\n'.join(lines + [''] + doc.get('notes', [])).strip(), url=doc['url'],
            metadata={'page': page, 'article': 'penalty_table', 'article_title': table['title']},
        ))
    return chunks


def bus_chunks():
    """셔틀버스: 노선 × 방향(학교로 오는 편 / 학교에서 나가는 편) 하나 = 청크 하나."""
    doc = sources.load('bus')
    chunks = []
    for route in doc['routes']:
        for direction, label, stops in (('outbound', '학교로 오는 편', route['outbound_stops']),
                                        ('inbound', '학교에서 나가는 편', route['inbound_stops'])):
            lines = []
            for trip in route['trips']:
                times = trip[direction]
                if all(TIME.match(t) for t in times):
                    lines.append(f'{trip["bus"]} ' + ' → '.join(f'{stop} {time}' for stop, time in zip(stops, times)))
                else:
                    lines.append(f'{trip["bus"]} 이 시간대는 운행하지 않음')
            chunks.append(Chunk(
                source=Source.BUS, key=f'bus:{route["key"]}:{direction}',
                title=f'{doc["title"]} {route["title"]} {label}',
                content='\n'.join(lines + doc.get('notes', [])), url=doc['url'],
                metadata={'route': route['key'], 'direction': direction, 'stops': stops},
            ))
    return chunks


def menu_chunks():
    """식단: 하루 하나 = 청크 하나."""
    doc = sources.load('menu')
    chunks = []
    for index, day in enumerate(doc['days']):
        lines = []
        for meal in doc['meals']:
            times = '·'.join(row['time'] for row in meal['rows'] if row['time'])
            dishes = ', '.join(row['dishes'][index] for row in meal['rows'] if row['dishes'][index])
            lines.append(f'{meal["name"]} ({meal["price"]}, {times}): {dishes}')
        chunks.append(Chunk(
            source=Source.MENU, key=f'menu:{day["date"]}',
            title=f'{doc["title"]} {day["date"]} ({day["weekday"]})',
            content='\n'.join(lines + doc.get('notes', [])), url=doc['url'],
            metadata={'date': day['date'], 'weekday': day['weekday']},
        ))
    return chunks


def notice_chunks():
    """공지: 공지 하나 = 청크 하나."""
    from dorm.models import Notice
    return [notice_chunk(n) for n in Notice.objects.order_by('id')]


def notice_chunk(notice):
    return Chunk(
        source=Source.NOTICE, key=f'notice:{notice.pk}', title=f'공지: {mask_personal_info(notice.title)}',
        content=mask_personal_info(notice.content), url=reverse('web:notice_detail', args=[notice.pk]),
        metadata={'notice_id': notice.pk, 'date': notice.date.isoformat() if notice.date else None},
    )


def inquiry_chunks():
    """문의: 답변이 달린 문의 하나 = 청크 하나 (문의 + 답변). 작성자 이름·아이디는 가린다."""
    from dorm.models import Inquiry
    answered = (Inquiry.objects.filter(inquiryanswer__isnull=False)
                .select_related('inquiryanswer', 'user__userprofile').order_by('id'))
    return [inquiry_chunk(i) for i in answered]


def inquiry_chunk(inquiry):
    user = inquiry.user
    names = [user.username, getattr(getattr(user, 'userprofile', None), 'full_name', '')]

    def mask(text):
        return mask_personal_info(text, known_names=names)

    return Chunk(
        source=Source.INQUIRY, key=f'inquiry:{inquiry.pk}', title=f'답변된 문의: {mask(inquiry.title)}',
        content=f'문의: {mask(inquiry.content)}\n답변: {mask(inquiry.inquiryanswer.answer)}',
        url='',  # 문의는 작성자와 관리자만 볼 수 있어 근거 링크를 두지 않는다
        metadata={'inquiry_id': inquiry.pk},
    )


BUILDERS = {
    Source.RULES: lambda: regulation_chunks('rules'),
    Source.INFO: lambda: regulation_chunks('info'),
    Source.BUS: bus_chunks,
    Source.MENU: menu_chunks,
    Source.NOTICE: notice_chunks,
    Source.INQUIRY: inquiry_chunks,
}


def build_chunks(selected=None):
    """selected: Source 값 목록. 없으면 전부."""
    chunks = []
    for source in selected or BUILDERS:
        chunks.extend(BUILDERS[source]())
    return chunks
