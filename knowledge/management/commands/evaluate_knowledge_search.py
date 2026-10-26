"""검색 품질을 평가 질문(knowledge/eval/questions.yaml)으로 측정한다.

    python manage.py evaluate_knowledge_search                                   # 설정의 모델 하나
    python manage.py evaluate_knowledge_search --model BAAI/bge-m3 --model nlpai-lab/KURE-v1
    python manage.py evaluate_knowledge_search --backend fake                    # 모델 없이 동작 확인

모델마다 검색 자료를 그 모델로 다시 임베딩한 뒤 측정한다(마지막 모델의 벡터가 DB에 남는다).
지표:
- hit@1 / hit@5: 정답 청크가 1위 / 5위 안에 든 질문 비율
- MRR: 정답이 처음 나온 순위 r의 1/r 평균 (높을수록 정답이 위에 있음)
"""
import time
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from knowledge.embeddings import get_embedder
from knowledge.indexing import embed_pending
from knowledge.models import KnowledgeChunk
from knowledge.search import search

QUESTIONS = Path(__file__).resolve().parents[2] / 'eval' / 'questions.yaml'
MODES = (('hybrid', True, True), ('vector', True, False), ('keyword', False, True))


def load_questions(path=QUESTIONS):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)['questions']


def evaluate(questions, embedder, use_vector, use_keyword, k=5, keyword_weight=None):
    """반환: {'hit@1', 'hit@5', 'mrr', 'misses': [질문...]}"""
    hit1 = hit5 = 0
    reciprocal = 0.0
    misses = []
    for item in questions:
        result = search(item['q'], k=k, embedder=embedder, use_vector=use_vector, use_keyword=use_keyword,
                        keyword_weight=keyword_weight)
        keys = [h.chunk.key for h in result.hits]
        rank = next((i for i, key in enumerate(keys, start=1) if key in item['expected']), None)
        if rank == 1:
            hit1 += 1
        if rank:
            hit5 += 1
            reciprocal += 1.0 / rank
        else:
            misses.append({'q': item['q'], 'expected': item['expected'], 'got': keys[:3]})
    n = len(questions)
    return {'hit@1': hit1 / n, 'hit@5': hit5 / n, 'mrr': reciprocal / n, 'misses': misses}


class Command(BaseCommand):
    help = '평가 질문으로 검색 품질(hit@1, hit@5, MRR)을 측정하고 임베딩 모델을 비교한다.'

    def add_arguments(self, parser):
        parser.add_argument('--model', action='append', help='비교할 모델 (여러 번 지정). 없으면 설정값')
        parser.add_argument('--backend', help="임베딩 방식 ('sentence-transformers' 또는 'fake')")
        parser.add_argument('--questions', default=str(QUESTIONS), help='평가 질문 파일')
        parser.add_argument('--show-misses', action='store_true', help='하이브리드 검색에서 놓친 질문 출력')
        parser.add_argument('--keyword-weight', type=float, action='append',
                            help='하이브리드 검색의 키워드 비중 (여러 번 지정해 비교). 없으면 search.KEYWORD_WEIGHT')

    def handle(self, *args, **options):
        questions = load_questions(options['questions'])
        if not KnowledgeChunk.objects.exists():
            self.stderr.write('검색 자료가 없습니다. 먼저 `python manage.py build_knowledge_index --no-embed`를 실행하세요.')
            return
        models = options['model'] or [None]
        rows = []
        for model in models:
            embedder = get_embedder(options['backend'], model)
            started = time.perf_counter()
            embedded = embed_pending(embedder)
            embed_seconds = time.perf_counter() - started
            started = time.perf_counter()
            results = {name: evaluate(questions, embedder, v, kw) for name, v, kw in MODES}
            for weight in options['keyword_weight'] or []:
                results[f'hybrid (키워드 {weight:g})'] = evaluate(questions, embedder, True, True, keyword_weight=weight)
            per_query_ms = (time.perf_counter() - started) / (len(questions) * len(MODES)) * 1000
            rows.append((embedder.name, results, embedded, embed_seconds, per_query_ms))

            self.stdout.write(f'\n## {embedder.name}  (질문 {len(questions)}개, 청크 {embedded}개 임베딩 '
                              f'{embed_seconds:.1f}초, 검색 평균 {per_query_ms:.0f}ms)')
            self.stdout.write('| 검색 방식 | hit@1 | hit@5 | MRR |\n|---|---|---|---|')
            for name in results:
                r = results[name]
                self.stdout.write(f'| {name} | {r["hit@1"]:.2f} | {r["hit@5"]:.2f} | {r["mrr"]:.3f} |')
            if options['show_misses']:
                for miss in results['hybrid']['misses']:
                    self.stdout.write(f'- 놓침: {miss["q"]}  정답 {miss["expected"]}  결과 {miss["got"]}')

        if len(rows) > 1:
            self.stdout.write('\n## 요약 (하이브리드 검색)\n| 모델 | hit@1 | hit@5 | MRR | 임베딩 시간 |\n|---|---|---|---|---|')
            for name, results, embedded, seconds, _ in rows:
                r = results['hybrid']
                self.stdout.write(f'| {name} | {r["hit@1"]:.2f} | {r["hit@5"]:.2f} | {r["mrr"]:.3f} | {seconds:.1f}초 |')
