"""답변 초안 품질을 평가 질문으로 측정하고 LLM을 비교한다 (ADR 0007, 0008).

    python manage.py evaluate_answer_drafts                                     # 설정의 모델 하나
    python manage.py evaluate_answer_drafts --model exaone3.5:7.8b --model qwen3:8b --output result.json
    python manage.py evaluate_answer_drafts --backend fake --embedding-backend fake --min-similarity 0

검색은 모델과 관계없이 같으므로, 차이는 모두 LLM에서 나온다.
지표:
- 사실 정확도: facts가 있는 질문 중 초안에 그 사실이 모두 들어간 비율
- 정답 근거 인용: 초안이 인용한 근거 중에 정답 청크가 있는 비율
- 인용 형식 문제: 없는 번호를 인용했거나 인용이 하나도 없는 초안 비율
- 잘못 거절: 답할 수 있는 질문인데 "확인할 수 없습니다"라고 하거나 근거 부족으로 막힌 비율
- 범위 밖 거절: 기숙사 자료로 답할 수 없는 질문을 거절한 비율 (높을수록 좋음)
- 외국어 섞임: 한자·일본 문자가 섞인 초안 비율
- 시간: 질문 하나당 초안 생성 시간 (모델을 메모리에 올리는 첫 호출은 제외)
"""
import json
import re
import statistics

from django.core.management.base import BaseCommand

from knowledge.answering import REFUSAL_PHRASE, draft_for_text
from knowledge.chat import answer_question
from knowledge.embeddings import get_embedder
from knowledge.llm import LLMError, get_llm
from knowledge.management.commands.evaluate_knowledge_search import QUESTIONS
from knowledge.models import KnowledgeChunk

import yaml

REFUSAL = REFUSAL_PHRASE
FOREIGN = re.compile(r'[぀-ヿ一-鿿]')  # 일본 가나, 한자


def load_eval_set(path=QUESTIONS):
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data['questions'], data.get('out_of_scope', [])


def has_fact(text, fact):
    return any(alternative in text for alternative in fact.split('|'))


def is_refusal(draft):
    return draft.status == 'insufficient_evidence' or (draft.status == 'ok' and REFUSAL in draft.text)


def grade(kind, item, draft):
    """초안 하나를 채점한다. kind: 'answerable' | 'out_of_scope'"""
    row = {
        'kind': kind,
        'q': item['q'] if kind == 'answerable' else item,
        'status': draft.status,
        'text': draft.text,
        'cited': draft.cited,
        'warnings': draft.warnings,
        'seconds': round(draft.seconds, 2),
        'evidence': [h.chunk.key for h in draft.evidence],
        'refused': is_refusal(draft),
        'foreign': bool(FOREIGN.search(draft.text)),
        'format_problem': draft.status == 'ok' and bool(draft.warnings) and not is_refusal(draft),
    }
    if kind == 'answerable':
        facts = item.get('facts') or []
        row['facts'] = facts
        row['facts_ok'] = all(has_fact(draft.text, f) for f in facts) if facts else None
        cited_keys = {draft.evidence[n - 1].chunk.key for n in draft.cited}
        row['cites_expected'] = bool(cited_keys & set(item['expected']))
    return row


def grade_chat(kind, item, reply):
    """챗봇 답 채점. 학생이 실제로 보는 것만 센다: 숨긴 답(unverified)은 답하지 않은 것으로 본다."""
    row = grade(kind, item, reply.draft)
    row['chat_status'] = reply.status
    row['refused'] = reply.status != 'answered'  # 답 속의 거절 문구가 아니라, 답을 보여 줬는지로 센다
    if reply.status != 'answered':
        row['format_problem'] = False
        if kind == 'answerable':
            row['facts_ok'] = False if row['facts'] else None
            row['cites_expected'] = False
    return row


def summarize(rows):
    answerable = [r for r in rows if r['kind'] == 'answerable']
    out_of_scope = [r for r in rows if r['kind'] == 'out_of_scope']
    with_facts = [r for r in answerable if r['facts_ok'] is not None]
    generated = [r for r in rows if r['status'] == 'ok']
    seconds = [r['seconds'] for r in generated]

    def ratio(items, key):
        return sum(1 for r in items if r[key]) / len(items) if items else 0.0

    return {
        'facts': ratio(with_facts, 'facts_ok'),
        'cites_expected': ratio(answerable, 'cites_expected'),
        'format_problem': ratio(generated, 'format_problem'),
        'wrong_refusal': ratio(answerable, 'refused'),
        'out_of_scope_refusal': ratio(out_of_scope, 'refused'),
        'foreign': ratio(generated, 'foreign'),
        'errors': sum(1 for r in rows if r['status'] == 'error'),
        'hidden': sum(1 for r in rows if r.get('chat_status') == 'unverified'),
        'median_seconds': statistics.median(seconds) if seconds else 0.0,
        'max_seconds': max(seconds) if seconds else 0.0,
    }


class Command(BaseCommand):
    help = '평가 질문으로 답변 초안 품질(사실, 인용, 거절, 시간)을 측정하고 LLM을 비교한다.'

    def add_arguments(self, parser):
        parser.add_argument('--model', action='append', help='비교할 LLM (여러 번 지정). 없으면 설정값')
        parser.add_argument('--backend', help="LLM 방식 ('ollama' 또는 'fake')")
        parser.add_argument('--embedding-backend', help="임베딩 방식 ('sentence-transformers' 또는 'fake')")
        parser.add_argument('--min-similarity', type=float, help='근거 부족 기준. 없으면 answering.MIN_SIMILARITY')
        parser.add_argument('--questions', default=str(QUESTIONS), help='평가 질문 파일')
        parser.add_argument('--limit', type=int, help='질문 수 제한 (빠른 확인용)')
        parser.add_argument('--output', help='초안 원문과 채점 결과를 저장할 JSON 파일')
        parser.add_argument('--mode', choices=['draft', 'chat'], default='draft',
                            help="draft: 관리자 답변 초안, chat: 학생 챗봇 (학생에게 보이는 답만 채점)")

    def handle(self, *args, **options):
        if not KnowledgeChunk.objects.exists():
            self.stderr.write('검색 자료가 없습니다. 먼저 `python manage.py build_knowledge_index`를 실행하세요.')
            return
        questions, out_of_scope = load_eval_set(options['questions'])
        if options['limit']:
            questions, out_of_scope = questions[:options['limit']], out_of_scope[:options['limit']]
        cases = [('answerable', q, q['q']) for q in questions] + [('out_of_scope', q, q) for q in out_of_scope]
        embedder = get_embedder(options['embedding_backend'])

        report = {}
        for model in options['model'] or [None]:
            llm = get_llm(options['backend'], model)
            try:
                llm.generate('한 단어로 답하세요.', '안녕하세요')  # 모델을 메모리에 올린다 (시간 측정에서 제외)
            except LLMError as exc:
                self.stderr.write(f'{llm.name}: {exc}')
                continue
            rows = []
            for kind, item, text in cases:
                if options['mode'] == 'chat':
                    reply = answer_question(text, llm=llm, embedder=embedder,
                                            min_similarity=options['min_similarity'])
                    rows.append(grade_chat(kind, item, reply))
                else:
                    draft = draft_for_text('', text, llm=llm, embedder=embedder,
                                           min_similarity=options['min_similarity'])
                    rows.append(grade(kind, item, draft))
                self.stdout.write(f'  [{llm.name}] {len(rows)}/{len(cases)} {rows[-1].get("chat_status", rows[-1]["status"])} '
                                  f'{rows[-1]["seconds"]:.1f}초')
            report[llm.name] = {'summary': summarize(rows), 'rows': rows}

        label = '학생 챗봇' if options['mode'] == 'chat' else '답변 초안'
        self.stdout.write(f'\n## {label} 평가 (답할 수 있는 질문 {len(questions)}개, 범위 밖 질문 {len(out_of_scope)}개)')
        self.stdout.write('| 모델 | 사실 정확도 | 정답 근거 인용 | 인용 형식 문제 | 잘못 거절 | 범위 밖 거절 | 외국어 섞임 '
                          '| 시간 중앙값 | 최대 | 오류 | 숨긴 답 |\n|---|---|---|---|---|---|---|---|---|---|---|')
        for name, result in report.items():
            s = result['summary']
            self.stdout.write(
                f'| {name} | {s["facts"]:.2f} | {s["cites_expected"]:.2f} | {s["format_problem"]:.2f} '
                f'| {s["wrong_refusal"]:.2f} | {s["out_of_scope_refusal"]:.2f} | {s["foreign"]:.2f} '
                f'| {s["median_seconds"]:.1f}초 | {s["max_seconds"]:.1f}초 | {s["errors"]} | {s["hidden"]} |')

        if options['output']:
            with open(options['output'], 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            self.stdout.write(f'\n초안 원문: {options["output"]}')
