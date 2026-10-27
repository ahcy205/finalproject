"""챗봇 답을 보여 주기 전에 판단 모델로 검증한다 (docs/adr/0015).

인용 검사(번호가 맞는지)와 첫 문장 검사("자료에 없다"로 시작하는지)를 통과해도, 답이 근거와 다른 사실을 말하거나
질문에 답하지 않는 경우가 있었다. 예: "도서관 몇 시까지 해?"에 생활관 출입시간을 도서관 시간처럼 답함.
그래서 TypeSafe Jev에게 두 가지를 묻는다.

- answers: 답이 질문에 실제로 답하는가 (근거에 없다고만 하거나 다른 내용을 말하면 아니오)
- contradicts: 답에 근거와 어긋나는 사실이 있는가 (시간·숫자·점수·허용 여부·방향·대상)

둘 다 통과해야 보여 준다: answers ≥ ANSWERS_MIN, contradicts < CONTRADICTS_MAX.
"모든 문장이 근거에 있는가"로 물으면 인사말·이유 설명 때문에 좋은 답도 대부분 떨어져서(28개 중 19개만 통과) 쓰지 않는다.

Jev를 쓸 수 없으면(키 없음, 장애) 검증 없이 기존 검사만으로 동작한다. 답을 만든 로컬 모델이 자기 답을
검증하는 것은 의미가 약해 대신 쓰지 않는다.
"""
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

ANSWERS_MIN = 0.5
CONTRADICTS_MAX = 0.8
QUESTIONS = {
    'answers': {'type': 'noul', 'instructions': '답이 [질문]에 실제로 답하는가? [근거]에 답이 없다고만 하거나 질문과 다른 내용을 말하면 아니오.'},
    'contradicts': {'type': 'noul', 'instructions': '답에 [근거]와 어긋나는 내용이 있는가? 근거와 다른 시간·날짜·숫자·점수, 근거와 반대되는 허용 여부, '
                    '다른 방향이나 다른 대상을 말하면 예. 인사말, 이유 설명, 문의 안내처럼 사실이 아닌 문장은 판단하지 않는다.'},
}


@dataclass
class Verdict:
    passed: bool
    checked: bool = True                 # False면 검증하지 못함(판단기 없음·실패) → 기존 검사만으로 통과
    scores: dict = field(default_factory=dict)
    reason: str = ''


def verification_state(question, hits, answer):
    lines = ['[질문]', question, '', '[근거]']
    for number, hit in enumerate(hits, start=1):
        lines += [f'[{number}] {hit.chunk.title}', hit.chunk.content, '']
    lines += ['[답]', answer]
    return '\n'.join(lines)


def decide(scores):
    if scores['answers'] < ANSWERS_MIN:
        return Verdict(False, scores=scores, reason='질문에 답하지 않음')
    if scores['contradicts'] >= CONTRADICTS_MAX:
        return Verdict(False, scores=scores, reason='근거와 어긋남')
    return Verdict(True, scores=scores)


class Verifier:
    name = ''

    def verify(self, question, hits, answer):
        raise NotImplementedError


class NoVerifier(Verifier):
    name = 'none'

    def verify(self, question, hits, answer):
        return Verdict(True, checked=False)


class FakeVerifier(Verifier):
    """테스트용 대역: 답에 '[검증 실패]'가 있으면 떨어뜨린다."""

    name = 'fake'

    def verify(self, question, hits, answer):
        if '[검증 실패]' in answer:
            return Verdict(False, scores={'answers': 0.0, 'contradicts': 1.0}, reason='질문에 답하지 않음')
        return Verdict(True, scores={'answers': 1.0, 'contradicts': 0.0})


class JevVerifier(Verifier):
    URL = 'https://api.typesafe.ai/v1/systemone'

    def __init__(self, api_key, model='jev-1.14.0', timeout=5):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = f'jev:{model}'

    def verify(self, question, hits, answer):
        body = {'model': self.model, 'state': verification_state(question, hits, answer), 'questions': QUESTIONS}
        request = urllib.request.Request(self.URL, data=json.dumps(body).encode('utf-8'), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {self.api_key}'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
            answers = data['answers']
            scores = {'answers': float(answers['answers']['noul']), 'contradicts': float(answers['contradicts']['noul'])}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning('Jev 답 검증에 실패해 검증 없이 보여 줍니다: %s', exc)
            return Verdict(True, checked=False, reason=str(exc))
        return decide(scores)


def get_verifier(backend=None):
    config = getattr(settings, 'KNOWLEDGE_VERIFIER', {})
    backend = backend or config.get('BACKEND', 'none')
    if backend == 'none':
        return NoVerifier()
    if backend == 'fake':
        return FakeVerifier()
    if backend == 'jev':
        api_key = config.get('API_KEY')
        if not api_key:
            logger.warning('TYPESAFE_API_KEY가 없어 답 검증 없이 동작합니다.')
            return NoVerifier()
        return JevVerifier(api_key, model=config.get('MODEL', 'jev-1.14.0'))
    raise ValueError(f'알 수 없는 검증 방식입니다: {backend}')
