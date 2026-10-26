"""하이브리드 검색: 의미 검색(pgvector)과 키워드 검색(pg_trgm)의 순위를 RRF로 합친다.

- 의미 검색: 질문 벡터와 청크 벡터의 코사인 거리 (HNSW 인덱스). "통금"으로 물어도 "출입시간" 조항을 찾는다.
- 키워드 검색: 질문과 본문의 글자 3개 단위 유사도(word_similarity). "23:00", "외박"처럼 정확한 말이 중요할 때 보완한다.
- RRF(Reciprocal Rank Fusion): 각 검색의 순위 r에 대해 비중/(RRF_K + r)를 더한다. 점수 크기가 다른 두 검색을
  순위만으로 합칠 수 있어서 쓴다. 키워드 검색은 비중을 낮춰 보조로만 쓴다(평가 결과, docs/adr/0006).

결과의 best_similarity(가장 가까운 청크의 코사인 유사도)로 "근거가 충분한지"를 판단할 수 있다.
임베딩이 아직 없는 청크(방금 저장된 공지·답변)는 키워드 점수만 받아 순위가 크게 밀린다(RRF). 그래서 검색 직전에
그런 청크를 최대 PENDING_EMBED_LIMIT개까지 바로 임베딩한다. 저장 직후의 새 자료는 몇 개뿐이라 금방 끝나고,
많이 밀려 있으면 나머지는 `build_knowledge_index`가 채운다.
"""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from django.contrib.postgres.search import TrigramWordSimilarity
from pgvector.django import CosineDistance

from .embeddings import get_embedder
from .indexing import embed_pending
from .models import KnowledgeChunk

# RRF 상수. 일반적으로 60을 쓰지만, 이 자료에서는 60이면 의미 검색 1·2위의 점수 차가 너무 작아져
# 약한 키워드 점수에도 1위가 뒤집혔다. 평가 결과로 1을 쓴다 (docs/adr/0006)
RRF_K = 1
CANDIDATES = 20         # 각 검색에서 뽑는 후보 수
KEYWORD_MIN_SIMILARITY = 0.1
PENDING_EMBED_LIMIT = 20  # 검색 직전에 임베딩할 최대 청크 수
# 키워드 검색 점수의 비중 (의미 검색 = 1). 평가 결과로 정한다 (docs/adr/0006)
KEYWORD_WEIGHT = 0.25


SYNONYMS_FILE = Path(__file__).resolve().parent / 'data' / 'synonyms.yaml'


@lru_cache(maxsize=1)
def load_synonyms():
    with open(SYNONYMS_FILE, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def expand_query(query):
    """학생이 쓰는 말을 규정 용어로 보강한다. "전기장판 써도 돼?" → "전기장판 써도 돼? (전열기 난방 도구)"

    규칙에 "전열기"라고만 적혀 있으면 "전기장판"으로는 의미 검색도 키워드 검색도 찾지 못한다 (docs/adr/0009).
    """
    terms = []
    for word, replacements in load_synonyms().items():
        if word in query:
            terms += [t for t in replacements if t not in query and t not in terms]
    return f'{query} ({" ".join(terms)})' if terms else query


@dataclass
class SearchHit:
    chunk: KnowledgeChunk
    score: float                      # RRF 점수
    similarity: float | None = None   # 코사인 유사도 (의미 검색에서 찾은 경우)
    keyword_similarity: float | None = None
    found_by: list = field(default_factory=list)  # ['vector', 'keyword']


@dataclass
class SearchResult:
    query: str
    hits: list

    @property
    def best_similarity(self):
        values = [h.similarity for h in self.hits if h.similarity is not None]
        return max(values) if values else None


def search(query, k=5, sources=None, embedder=None, use_vector=True, use_keyword=True, embed_new=True,
           keyword_weight=None):
    """질문과 가까운 청크 k개를 돌려준다. sources: KnowledgeChunk.Source 값 목록으로 자료를 제한."""
    query = expand_query(query)
    base = KnowledgeChunk.objects.all()
    if sources:
        base = base.filter(source__in=sources)

    hits = {}

    weights = {'vector': 1.0, 'keyword': KEYWORD_WEIGHT if keyword_weight is None else keyword_weight}

    def add(chunk, rank, kind, **values):
        hit = hits.setdefault(chunk.pk, SearchHit(chunk=chunk, score=0.0))
        hit.score += weights[kind] / (RRF_K + rank)
        hit.found_by.append(kind)
        for name, value in values.items():
            setattr(hit, name, value)

    if use_vector:
        embedder = embedder or get_embedder()
        if embed_new:
            embed_pending(embedder, limit=PENDING_EMBED_LIMIT, only_missing=True)
        vector = embedder.embed_query(query)
        nearest = (base.filter(embedding__isnull=False, embedding_model=embedder.name)
                   .annotate(distance=CosineDistance('embedding', vector))
                   .order_by('distance', 'id')[:CANDIDATES])
        for rank, chunk in enumerate(nearest, start=1):
            add(chunk, rank, 'vector', similarity=1.0 - chunk.distance)

    if use_keyword:
        matches = (base.annotate(keyword=TrigramWordSimilarity(query, 'content'))
                   .filter(keyword__gte=KEYWORD_MIN_SIMILARITY)
                   .order_by('-keyword', 'id')[:CANDIDATES])
        for rank, chunk in enumerate(matches, start=1):
            add(chunk, rank, 'keyword', keyword_similarity=chunk.keyword)

    ranked = sorted(hits.values(), key=lambda h: (-h.score, h.chunk.pk))[:k]
    return SearchResult(query=query, hits=ranked)
