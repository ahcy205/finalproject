"""학생 챗봇 메시지의 종류를 판단한다 (docs/adr/0014).

- smalltalk: 인사·감사·맞장구 → 정해진 짧은 답 (검색·답변 모델을 부르지 않음)
- meta: 앞 답을 다시/요약/쉽게/자세히 → 앞 답과 그 근거로 다시 쓴다
- followup: 앞 대화를 알아야 뜻이 통하는 질문 → 완전한 질문으로 다시 쓴 뒤 검색 (다음 PR)
- new: 새 질문 → 지금처럼 검색·답변

판단기
- 'jev': TypeSafe의 판단 전용 모델 Jev. 측정에서 가장 정확했다(새 문장 25개 1.00, 0.2초). 외부 API라
  개인정보를 가린 마지막 메시지와 바로 앞 한 턴만 보낸다. 실패하면 'llm'으로 바꿔 판단한다.
- 'llm': 답변용 로컬 모델(exaone)에게 한 단어로 고르게 한다 (0.88, 0.08초). 같은 모델이라 GPU에서 바꿔 올릴 필요가 없다.
- 'fake': 테스트용 대역. 몇 개의 낱말로만 판단한다.
규칙(정규식)만으로 판단하는 방식은 처음 보는 표현에서 0.44로 떨어져 쓰지 않는다.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from .llm import LLMError, get_llm

logger = logging.getLogger(__name__)

KINDS = ('smalltalk', 'meta', 'followup', 'new')
CRITERIA = {
    'smalltalk': '인사, 감사, 맞장구',
    'meta': '앞 답을 다시 말해 달라, 요약·정리·쉽게·자세히 설명해 달라는 요청',
    'followup': '앞 대화를 알아야 뜻이 통하는 질문 (그럼, 그건, ~은?, 예외는? 등)',
    'new': '앞 대화 없이도 뜻이 통하는 새 질문',
}
INSTRUCTIONS = '학생과 기숙사 안내 챗봇의 대화입니다. 학생의 마지막 메시지는 어떤 종류인가요?'
LLM_SYSTEM = (INSTRUCTIONS + '\n' + '\n'.join(f'- {kind}: {text}' for kind, text in CRITERIA.items())
              + '\n답은 smalltalk, meta, followup, new 중 한 단어만 쓰세요.')


def conversation_state(message, previous=None):
    """판단기에 넘길 글. previous: 바로 앞 턴 {'question', 'answer'} (개인정보를 가린 것)"""
    if previous:
        context = f"[앞 대화]\n학생: {previous['question']}\n챗봇: {previous['answer']}"
    else:
        context = '[앞 대화]\n(없음)'
    return f'{context}\n\n[마지막 메시지]\n학생: {message}'


class Router:
    name = ''

    def classify(self, message, previous=None):
        raise NotImplementedError


class FakeRouter(Router):
    """테스트용 대역. 실제 판단 성능과는 관계없다."""

    name = 'fake'

    def classify(self, message, previous=None):
        if any(word in message for word in ('안녕', '고마', '감사')):
            return 'smalltalk'
        if any(word in message for word in ('다시', '요약', '쉽게')):
            return 'meta'
        if message.startswith(('그럼', '그건', '그거')):
            return 'followup'
        return 'new'


class LLMRouter(Router):
    def __init__(self, llm=None):
        self.llm = llm or get_llm()
        self.name = f'llm:{self.llm.name}'

    def classify(self, message, previous=None):
        text = self.llm.generate(LLM_SYSTEM, conversation_state(message, previous)).strip().lower()
        return next((kind for kind in KINDS if kind in text), 'new')


class JevRouter(Router):
    URL = 'https://api.typesafe.ai/v1/systemone'

    def __init__(self, api_key, model='jev-1.14.0', timeout=3, fallback=None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = f'jev:{model}'
        self.fallback = fallback

    def _ask(self, state):
        body = {'model': self.model, 'state': state,
                'questions': {'kind': {'type': 'choice', 'instructions': INSTRUCTIONS, 'criteria': CRITERIA}}}
        request = urllib.request.Request(self.URL, data=json.dumps(body).encode('utf-8'), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {self.api_key}'})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
        kind = data['answers']['kind']['choice']
        if kind not in KINDS:
            raise ValueError(f'알 수 없는 종류: {kind}')
        return kind

    def classify(self, message, previous=None):
        try:
            return self._ask(conversation_state(message, previous))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
            # 키 오류·장애·시간 초과 등. 학생의 답을 막지 않도록 로컬 판단기로 넘긴다
            logger.warning('Jev 판단에 실패해 로컬 판단기를 씁니다: %s', exc)
            if self.fallback is None:
                return 'new'
            try:
                return self.fallback.classify(message, previous)
            except LLMError:
                return 'new'


def get_router(backend=None):
    config = getattr(settings, 'KNOWLEDGE_ROUTER', {})
    backend = backend or config.get('BACKEND', 'llm')
    if backend == 'fake':
        return FakeRouter()
    if backend == 'llm':
        return LLMRouter()
    if backend == 'jev':
        api_key = config.get('API_KEY')
        if not api_key:
            logger.warning('TYPESAFE_API_KEY가 없어 로컬 판단기를 씁니다.')
            return LLMRouter()
        return JevRouter(api_key, model=config.get('MODEL', 'jev-1.14.0'), fallback=LLMRouter())
    raise ValueError(f'알 수 없는 판단 방식입니다: {backend}')
