"""답 문장의 시각이 근거의 같은 주제 줄에 있는지 확인한다 (docs/adr/0019).

모델이 같은 조문의 출입시간(06:00-23:00)을 소등 시간처럼 "23:00 이후 소등"이라고 답했고, Jev 검증도 이를
통과시켰다(ADR 0018). 모델을 쓰지 않는 규칙이라 결과가 매번 같다.

- 시각이 있는 문장마다, 그 시각이 적힌 근거 줄(또는 제목)을 찾는다.
- 그런 줄이 없으면 "근거에 없는 시각".
- 줄은 있지만 문장과 겹치는 주제어(한글 두 글자 앞부분)가 없으면 "다른 주제의 시각".
- 주제어에는 synonyms.yaml을 더한다(통금 → 출입시간). 오전·오후가 없는 "11시"는 11:00과 23:00을 모두 인정한다.
"""
import re

from .search import load_synonyms

TIME = re.compile(r'(오전|오후|아침|낮|저녁|밤|새벽)?\s*(?:(\d{1,2})\s*(?::\s*(\d{2})|시(?:\s*(\d{1,2})\s*분|\s*(반))?)|(자정))')
PM = {'오후', '저녁', '밤'}
WORD = re.compile(r'[가-힣]{2,}')
# 거의 모든 문장에 나와 주제를 가리지 못하는 말 (앞 두 글자로 비교)
COMMON = {'안녕', '생활', '기숙', '시간', '이후', '이전', '까지', '부터', '입니', '있습', '합니', '원칙', '일반',
          '경우', '관련', '확인', '문의', '주시', '감사', '근거', '자료', '규칙', '매일', '오전', '오후', '저녁', '아침'}
SENTENCE = re.compile(r'(?<=[.!?])\s+|\n')


def times(text):
    """글 속 시각마다 가능한 (시, 분) 집합. 오전·오후가 없는 "N시"는 두 가지로 본다."""
    found = []
    for match in TIME.finditer(text):
        period, hour, minute, minute2, half, midnight = match.groups()
        if midnight:
            found.append({(0, 0)})
            continue
        hour = int(hour)
        if hour > 24:
            continue
        minute = int(minute or minute2 or (30 if half else 0))
        if period in PM and hour < 12:
            hour += 12
        hour %= 24
        if period is None and ':' not in match.group(0) and 1 <= hour < 12:
            found.append({(hour, minute), (hour + 12, minute)})
        else:
            found.append({(hour, minute)})
    return found


def words(text, synonyms):
    extra = ' '.join(' '.join(values) for word, values in synonyms.items() if word in text)
    return {w[:2] for w in WORD.findall(f'{text} {extra}')} - COMMON


def mismatched_times(text, hits):
    """근거와 맞지 않는 시각 설명 목록. 비어 있으면 통과."""
    lines = [line for hit in hits for line in [hit.chunk.title, *hit.chunk.content.split('\n')]]
    line_times = [set().union(*times(line)) if times(line) else set() for line in lines]
    synonyms = load_synonyms()
    problems = []
    for sentence in SENTENCE.split(text):
        for candidates in times(sentence):
            label = '/'.join(f'{h:02d}:{m:02d}' for h, m in sorted(candidates))
            matching = [line for line, found in zip(lines, line_times) if candidates & found]
            if not matching:
                problems.append(f'근거에 없는 시각 {label}: {sentence.strip()[:60]}')
            elif not any(words(sentence, synonyms) & words(line, synonyms) for line in matching):
                problems.append(f'다른 주제의 시각 {label}: {sentence.strip()[:60]}')
    return problems
