"""문장을 벡터로 바꾼다(임베딩).

- 'sentence-transformers': 실제 모델(bge-m3 등)을 이 PC에서 실행한다. `pip install -r requirements-ml.txt` 필요
- 'fake': 단어를 해시해서 만드는 가짜 벡터. 모델 설치·API 키 없이 테스트와 CI가 돌아가게 한다.
  같은 단어를 많이 공유하는 문장끼리 가까워지므로 검색 테스트에도 쓸 수 있다.

어떤 것을 쓸지는 settings.KNOWLEDGE_EMBEDDING(환경변수 KNOWLEDGE_EMBEDDING_BACKEND / _MODEL)로 정한다.
"""
import hashlib
import math
import re
import threading

from django.conf import settings

from .models import EMBEDDING_DIMENSIONS


class Embedder:
    name = ''

    def embed_documents(self, texts):
        raise NotImplementedError

    def embed_query(self, text):
        return self.embed_documents([text])[0]


class FakeEmbedder(Embedder):
    """단어 해시 기반 가짜 임베딩 (테스트·CI용). 결과는 항상 같다."""

    name = 'fake'
    TOKEN = re.compile(r'[0-9A-Za-z가-힣]+')

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def _vector(self, text):
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for token in self.TOKEN.findall(text.lower()):
            # 한국어는 조사가 붙어 단어가 달라지므로 앞 두 글자도 함께 넣는다 ("외박을" ~ "외박")
            for piece in {token, token[:2]}:
                digest = hashlib.md5(piece.encode('utf-8')).digest()
                vector[int.from_bytes(digest[:4], 'little') % EMBEDDING_DIMENSIONS] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class SentenceTransformerEmbedder(Embedder):
    """로컬 모델 (BAAI/bge-m3, nlpai-lab/KURE-v1, intfloat/multilingual-e5-large 등).

    모델은 처음 쓸 때 한 번만 내려받고 메모리에 올린다(bge-m3 약 2.2GB).
    e5 계열은 질문과 문서 앞에 'query: ' / 'passage: '를 붙여야 성능이 나온다.
    """

    _models = {}
    _lock = threading.Lock()

    def __init__(self, model_name, query_prefix='', document_prefix=''):
        self.name = model_name
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix

    @property
    def model(self):
        with self._lock:  # 미리 깨우기와 첫 질문이 동시에 와도 모델(약 2.2GB)을 한 번만 올린다
            return self._load()

    def _load(self):
        if self.name not in self._models:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    '임베딩 모델 라이브러리가 설치되지 않았습니다. `pip install -r requirements-ml.txt`를 실행하거나, '
                    '테스트용으로 KNOWLEDGE_EMBEDDING_BACKEND=fake를 설정하세요.') from exc
            self._models[self.name] = SentenceTransformer(self.name, device='cpu')
        return self._models[self.name]

    def _encode(self, texts):
        vectors = self.model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
        result = [v.tolist() for v in vectors]
        if result and len(result[0]) != EMBEDDING_DIMENSIONS:
            raise RuntimeError(f'{self.name}의 벡터 크기({len(result[0])})가 저장 칸({EMBEDDING_DIMENSIONS})과 다릅니다.')
        return result

    def embed_documents(self, texts):
        return self._encode([self.document_prefix + t for t in texts])

    def embed_query(self, text):
        return self._encode([self.query_prefix + text])[0]


# 모델별로 필요한 접두어
PREFIXES = {
    'intfloat/multilingual-e5-large': ('query: ', 'passage: '),
    'intfloat/multilingual-e5-base': ('query: ', 'passage: '),
    'intfloat/multilingual-e5-small': ('query: ', 'passage: '),
}


def get_embedder(backend=None, model=None):
    config = getattr(settings, 'KNOWLEDGE_EMBEDDING', {})
    backend = backend or config.get('BACKEND', 'sentence-transformers')
    if backend == 'fake':
        return FakeEmbedder()
    if backend == 'sentence-transformers':
        model = model or config.get('MODEL', 'BAAI/bge-m3')
        query_prefix, document_prefix = PREFIXES.get(model, ('', ''))
        return SentenceTransformerEmbedder(model, query_prefix, document_prefix)
    raise ValueError(f'알 수 없는 임베딩 방식입니다: {backend}')
