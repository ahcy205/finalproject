"""답변 문장을 쓰는 언어 모델(LLM) 호출 (ADR 0007).

- 'ollama': 이 PC에서 실행하는 로컬 모델 (Ollama, http://127.0.0.1:11434). 무료이고 데이터가 PC 밖으로 나가지 않는다.
- 'fake': 테스트·CI용 대역. 받은 근거를 정해진 규칙으로 엮어 항상 같은 답을 돌려준다.
  AI의 글솜씨가 아니라 우리 코드(근거 부족 판단, 개인정보 가리기, 인용 검사)를 검사하기 위해 쓴다.

나중에 Claude·GPT 같은 API를 쓰려면 LLM을 상속한 클래스를 추가하고 get_llm()에 등록하면 된다.
설정: settings.KNOWLEDGE_LLM (환경변수 KNOWLEDGE_LLM_BACKEND / KNOWLEDGE_LLM_MODEL / OLLAMA_HOST)
"""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings


class LLMError(Exception):
    """모델을 부르지 못했을 때 (Ollama가 꺼져 있음, 모델 없음, 시간 초과 등)."""


class LLM:
    name = ''

    def generate(self, system, prompt):
        """system: 역할·규칙, prompt: 문의와 근거. 반환: 답변 문장"""
        raise NotImplementedError


class FakeLLM(LLM):
    """테스트용 대역. 첫 번째 근거의 첫 문장을 인용해 항상 같은 형식으로 답한다."""

    name = 'fake'
    EVIDENCE = re.compile(r'^\[(\d+)\] (.+)\n(.+)$', re.M)

    def generate(self, system, prompt):
        found = self.EVIDENCE.findall(prompt)
        if not found:
            return '근거 자료에서 확인할 수 없습니다.'
        number, title, first_line = found[0]
        return f'안녕하세요. {title}에 따르면 {first_line} [{number}]\n자세한 내용은 생활관에 문의해 주세요.'


class OllamaLLM(LLM):
    """Ollama의 /api/chat을 부른다. 답변 초안은 정확해야 하므로 temperature를 낮게 둔다."""

    def __init__(self, model, host, timeout=180):
        self.name = model
        self.host = host.rstrip('/')
        self.timeout = timeout

    def generate(self, system, prompt):
        body = {
            'model': self.name,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
            'stream': False,
            'think': False,  # 추론 과정을 길게 쓰는 모델(qwen3 등)도 답만 쓰게 한다
            'options': {'temperature': 0.2, 'num_ctx': 8192},
        }
        request = urllib.request.Request(f'{self.host}/api/chat', data=json.dumps(body).encode('utf-8'),
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:200]
            raise LLMError(f'Ollama가 요청을 거절했습니다({exc.code}): {detail}. '
                           f'`ollama pull {self.name}`로 모델을 받았는지 확인하세요.') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f'Ollama({self.host})에 연결할 수 없습니다. Ollama가 실행 중인지 확인하세요. ({exc})') from exc
        content = (data.get('message') or {}).get('content', '').strip()
        # 일부 모델은 think=False여도 <think>...</think>를 남긴다
        return re.sub(r'<think>.*?</think>', '', content, flags=re.S).strip()


def get_llm(backend=None, model=None):
    config = getattr(settings, 'KNOWLEDGE_LLM', {})
    backend = backend or config.get('BACKEND', 'ollama')
    if backend == 'fake':
        return FakeLLM()
    if backend == 'ollama':
        return OllamaLLM(model or config.get('MODEL', 'exaone3.5:7.8b'),
                         config.get('HOST', 'http://127.0.0.1:11434'))
    raise ValueError(f'알 수 없는 LLM 방식입니다: {backend}')
