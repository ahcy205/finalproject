import io
import json
import math
import urllib.error
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from dorm.models import Inquiry, InquiryAnswer, Notice
from knowledge import sources
from knowledge.chunking import build_chunks, inquiry_chunks, notice_chunks
from knowledge.embeddings import FakeEmbedder, get_embedder
from knowledge.indexing import embed_pending, sync_chunks
from knowledge.models import EMBEDDING_DIMENSIONS, KnowledgeChunk
from knowledge.privacy import mask_personal_info
from knowledge.answering import draft_answer, draft_for_text
from knowledge.llm import FakeLLM, LLMError, OllamaLLM, get_llm
from knowledge.search import search


class RegulationDataTests(TestCase):
    """knowledge/data의 규칙·안내 자료 형식."""

    def articles(self, doc):
        return [a for section in doc['sections'] for a in section['articles']]

    def test_rules_have_every_article_and_the_penalty_table(self):
        doc = sources.load('rules')
        numbers = [a.get('number') for a in self.articles(doc)]
        self.assertEqual(numbers, [str(n) for n in range(1, 15)] + ['14-2', '15', None])  # 마지막은 부칙
        self.assertEqual(len(doc['penalty_table']['rows']), 24)
        self.assertEqual(len(doc['notes']), 3)

    def test_info_has_eight_chapters_and_27_articles(self):
        doc = sources.load('info')
        self.assertEqual(len(doc['sections']), 8)
        self.assertEqual([a['number'] for a in self.articles(doc)], [str(n) for n in range(1, 28)])

    def test_every_article_has_text(self):
        for page in sources.REGULATION_PAGES:
            for article in self.articles(sources.load(page)):
                self.assertTrue(article['lines'], f'{page} {article["title"]}')
                self.assertTrue(all(isinstance(line, str) and line.strip() for line in article['lines']))

    def test_unknown_page_is_rejected(self):
        with self.assertRaises(ValueError):
            sources.load('../settings')


class RegulationPagesTests(TestCase):
    """화면이 데이터 파일의 내용을 그대로 보여 준다."""

    def test_pages_show_every_article_from_the_data(self):
        for page, url_name in (('rules', 'web:rules'), ('info', 'web:info')):
            html = self.client.get(reverse(url_name)).content.decode()
            doc = sources.load(page)
            for section in doc['sections']:
                for article in section['articles']:
                    self.assertIn(f'<strong>{article["title"]}</strong>', html)

    def test_rules_page_shows_the_penalty_table(self):
        response = self.client.get(reverse('web:rules'))
        self.assertContains(response, '<td>관내 흡연</td><td>퇴관</td>')
        self.assertContains(response, '1시간당 2점 감면')

    def test_quotes_are_escaped_safely(self):
        # 데이터의 큰따옴표는 HTML 엔티티로 나가고, 화면에는 똑같이 보인다
        self.assertContains(self.client.get(reverse('web:rules')), '(이하 &quot;관생&quot;이라 한다)')


class TableDataTests(TestCase):
    """셔틀버스 시간표·식단 자료 형식과 화면 표시."""

    def test_bus_routes_have_a_time_for_every_stop(self):
        doc = sources.load('bus')
        self.assertEqual([r['key'] for r in doc['routes']], ['terminal', 'asan'])
        for route in doc['routes']:
            self.assertEqual(route['outbound_stops'][-1], '학교 도착')
            self.assertEqual(route['inbound_stops'][0], '학교 출발')
            self.assertEqual(len(route['trips']), 12)
            for trip in route['trips']:
                self.assertEqual(len(trip['outbound']), len(route['outbound_stops']))
                self.assertEqual(len(trip['inbound']), len(route['inbound_stops']))

    def test_menu_has_a_dish_for_every_day(self):
        doc = sources.load('menu')
        self.assertEqual([d['weekday'] for d in doc['days']], ['월', '화', '수', '목', '금'])
        self.assertEqual([m['name'] for m in doc['meals']], ['중식', '석식'])
        for meal in doc['meals']:
            for row in meal['rows']:
                self.assertEqual(len(row['dishes']), 5)

    def test_bus_page_shows_both_routes_from_the_data(self):
        response = self.client.get(reverse('web:bus'))
        self.assertContains(response, 'id="table-terminal"')
        self.assertContains(response, 'id="table-asan" style="display: none;"')
        self.assertContains(response, '<td>(1호차)</td><td>08:25</td>')
        self.assertContains(response, '<th class="text-center" scope="col">천안 아산역(KTX)</th>')

    def test_menu_page_shows_meals_and_escapes_ampersand(self):
        response = self.client.get(reverse('web:menu'))
        self.assertContains(response, '<td class="time-col" rowspan="3">중식<br>(4,500원)</td>')
        self.assertContains(response, '<td>상추쌈&amp;쌈장</td>')
        self.assertNotContains(response, '</span></td>')


class PrivacyTests(TestCase):
    def test_masks_phone_email_and_student_number(self):
        text = '연락처 010-1234-5678, 01098765432, mail me@school.ac.kr, 학번 22041013입니다'
        self.assertEqual(mask_personal_info(text),
                         '연락처 [전화번호], [전화번호], mail [이메일], 학번 [학번]입니다')

    def test_masks_known_names_but_keeps_times_and_prices(self):
        text = '홍길동 학생 문의: 출입시간 06:00-23:00, 식비 4,500원, 2025년 6월'
        self.assertEqual(mask_personal_info(text, known_names=['홍길동']),
                         '[이름] 학생 문의: 출입시간 06:00-23:00, 식비 4,500원, 2025년 6월')


class ChunkingTests(TestCase):
    def test_static_sources_become_one_chunk_per_article_route_and_day(self):
        counts = {}
        for chunk in build_chunks(['rules', 'info', 'bus', 'menu']):
            counts[chunk.source] = counts.get(chunk.source, 0) + 1
        rules = sources.load('rules')
        self.assertEqual(counts['rules'], sum(len(s['articles']) for s in rules['sections']) + 1)  # + 벌점표
        self.assertEqual(counts['info'], 27)
        self.assertEqual(counts['bus'], 4)   # 노선 2개 × 방향 2개
        self.assertEqual(counts['menu'], 5)  # 5일

    def test_rule_chunk_keeps_article_number_and_link(self):
        chunk = next(c for c in build_chunks(['rules']) if c.key == 'rules:article:3')
        self.assertEqual(chunk.title, '생활관 규칙 제3조 (생활규범)')
        self.assertIn('06:00-23:00', chunk.content)
        self.assertEqual((chunk.url, chunk.metadata['article']), ('/rules/', '3'))

    def test_bus_chunk_lists_stops_with_times_and_skips_breaks(self):
        chunk = next(c for c in build_chunks(['bus']) if c.key == 'bus:terminal:outbound')
        self.assertIn('(1호차) 천안 터미널 08:25 → 두정역 08:35', chunk.content)
        self.assertIn('이 시간대는 운행하지 않음', chunk.content)

    def test_notice_and_answered_inquiry_chunks(self):
        Notice.objects.create(title='점호 안내', content='매일 24:00 점호, 문의 010-1111-2222')
        student = User.objects.create_user('20250001', password='pw12345!')
        student.userprofile.full_name = '홍길동'
        student.userprofile.save()
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        answered = Inquiry.objects.create(user=student, title='외박 문의', content='홍길동(20250001)입니다. 외박 되나요?')
        InquiryAnswer.objects.create(inquiry=answered, admin=staff, answer='홍길동 학생, 외박 신청 메뉴를 이용하세요.')
        Inquiry.objects.create(user=student, title='답변 없는 문의', content='내용')

        notice = notice_chunks()[0]
        self.assertEqual(notice.url, reverse('web:notice_detail', args=[Notice.objects.get().pk]))
        self.assertIn('[전화번호]', notice.content)

        chunks = inquiry_chunks()
        self.assertEqual(len(chunks), 1)  # 답변이 달린 문의만
        self.assertEqual(chunks[0].content,
                         '문의: [이름]([학번])입니다. 외박 되나요?\n답변: [이름] 학생, 외박 신청 메뉴를 이용하세요.')
        self.assertEqual(chunks[0].url, '')


class IndexingTests(TestCase):
    """색인 명령(sync_chunks / embed_pending) 자체의 동작. 저장 시 자동 갱신(AutoSyncTests)은 꺼 두고 확인한다."""

    def setUp(self):
        from unittest import mock
        patcher = mock.patch('knowledge.signals._safely')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.embedder = FakeEmbedder()
        self.notice = Notice.objects.create(title='소등 안내', content='00:00 소등')

    def index(self, selected=('notice',)):
        stats = sync_chunks(build_chunks(selected), selected)
        embedded = embed_pending(self.embedder)
        return stats, embedded

    def test_reindex_only_reembeds_changed_chunks(self):
        stats, embedded = self.index()
        self.assertEqual((stats['created'], embedded), (1, 1))
        stats, embedded = self.index()
        self.assertEqual((stats['unchanged'], embedded), (1, 0))

        self.notice.content = '01:00 소등으로 변경'
        self.notice.save()
        stats, embedded = self.index()
        self.assertEqual((stats['updated'], embedded), (1, 1))
        self.assertIn('01:00', KnowledgeChunk.objects.get(key=f'notice:{self.notice.pk}').content)

    def test_deleted_source_rows_are_removed_without_touching_other_sources(self):
        self.index(('notice', 'rules'))
        rules_count = KnowledgeChunk.objects.filter(source='rules').count()
        self.notice.delete()
        stats, _ = self.index(('notice',))
        self.assertEqual(stats['deleted'], 1)
        self.assertEqual(KnowledgeChunk.objects.filter(source='rules').count(), rules_count)

    def test_changing_model_reembeds_everything(self):
        self.index()

        class OtherModel(FakeEmbedder):
            name = 'other-model'

        self.assertEqual(embed_pending(OtherModel()), 1)
        self.assertEqual(KnowledgeChunk.objects.get().embedding_model, 'other-model')


class EmbeddingTests(TestCase):
    def test_fake_vectors_are_normalized_and_similar_texts_are_closer(self):
        embedder = get_embedder('fake')
        a, b, c = embedder.embed_documents(['외박 신청 방법', '외박을 신청하려면', '셔틀버스 시간표'])
        self.assertEqual(len(a), EMBEDDING_DIMENSIONS)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in a)), 1.0, places=6)

        def cosine(x, y):
            return sum(p * q for p, q in zip(x, y))

        self.assertGreater(cosine(a, b), cosine(a, c))

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ValueError):
            get_embedder('nope')


class KnowledgeIndexCommandTests(TestCase):
    def test_command_builds_every_source(self):
        out = io.StringIO()
        call_command('build_knowledge_index', '--backend', 'fake', stdout=out)
        self.assertIn('임베딩:', out.getvalue())
        sources_in_db = set(KnowledgeChunk.objects.values_list('source', flat=True))
        self.assertTrue({'rules', 'info', 'bus', 'menu'} <= sources_in_db)
        self.assertFalse(KnowledgeChunk.objects.filter(embedding__isnull=True).exists())

    def test_database_has_vector_and_trigram_indexes(self):
        with connection.cursor() as cursor:
            cursor.execute("select extname from pg_extension where extname in ('vector', 'pg_trgm') order by 1")
            self.assertEqual([r[0] for r in cursor.fetchall()], ['pg_trgm', 'vector'])
            cursor.execute("select indexdef from pg_indexes where indexname = 'knowledge_embedding_hnsw'")
            self.assertIn('USING hnsw (embedding vector_cosine_ops)', cursor.fetchone()[0])


class AutoSyncTests(TestCase):
    """공지·문의를 저장하거나 지우면 검색 자료가 바로 바뀐다."""

    def chunk(self, key):
        return KnowledgeChunk.objects.filter(key=key).first()

    def test_notice_create_update_delete(self):
        notice = Notice.objects.create(title='점호 안내', content='매일 24:00, 문의 010-1111-2222')
        key = f'notice:{notice.pk}'
        self.assertEqual(self.chunk(key).title, '공지: 점호 안내')
        self.assertIn('[전화번호]', self.chunk(key).content)

        embed_pending(FakeEmbedder())
        notice.content = '매일 23:30으로 변경'
        notice.save()
        changed = self.chunk(key)
        self.assertIn('23:30', changed.content)
        self.assertIsNone(changed.embedding)  # 내용이 바뀌면 예전 벡터를 쓰지 않는다

        notice.delete()
        self.assertIsNone(self.chunk(key))

    def test_inquiry_appears_only_after_it_is_answered(self):
        student = User.objects.create_user('20250001', password='pw12345!')
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        inquiry = Inquiry.objects.create(user=student, title='소음 문의', content='옆방이 시끄러워요')
        key = f'inquiry:{inquiry.pk}'
        self.assertIsNone(self.chunk(key))

        answer = InquiryAnswer.objects.create(inquiry=inquiry, admin=staff, answer='생활감에게 전달했습니다.')
        self.assertIn('답변: 생활감에게 전달했습니다.', self.chunk(key).content)

        inquiry.content = '옆방이 밤마다 시끄러워요'
        inquiry.save()
        self.assertIn('밤마다', self.chunk(key).content)

        answer.delete()
        self.assertIsNone(self.chunk(key))

    def test_deleting_an_answered_inquiry_removes_its_chunk(self):
        student = User.objects.create_user('20250001', password='pw12345!')
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        inquiry = Inquiry.objects.create(user=student, title='t', content='c')
        InquiryAnswer.objects.create(inquiry=inquiry, admin=staff, answer='a')
        inquiry.delete()  # 답변도 함께 삭제됨(CASCADE)
        self.assertFalse(KnowledgeChunk.objects.filter(source='inquiry').exists())

    def test_index_failure_does_not_block_saving_a_notice(self):
        from unittest import mock
        with mock.patch('knowledge.signals.notice_chunk', side_effect=RuntimeError('boom')), \
                self.assertLogs('knowledge.signals', level='ERROR') as logs:
            notice = Notice.objects.create(title='저장은 되어야 함', content='내용')
        self.assertTrue(Notice.objects.filter(pk=notice.pk).exists())
        self.assertIn('검색 자료 갱신 실패', logs.output[0])
        # 같은 트랜잭션에서 다른 쿼리도 계속 쓸 수 있어야 한다
        self.assertEqual(Notice.objects.count(), 1)

    def test_loading_a_fixture_skips_auto_sync(self):
        import json
        import os
        import tempfile
        fixture = [{'model': 'dorm.notice', 'pk': 901, 'fields': {'title': '백업 공지', 'content': '내용',
                                                                   'image': '', 'date': '2026-01-01'}}]
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(fixture, f, ensure_ascii=False)
        try:
            call_command('loaddata', f.name, verbosity=0)
        finally:
            os.remove(f.name)
        self.assertTrue(Notice.objects.filter(pk=901).exists())
        self.assertIsNone(self.chunk('notice:901'))  # 불러온 뒤 색인 명령으로 만든다


class SearchTests(TestCase):
    """하이브리드 검색 (가짜 임베딩으로 확인)."""

    @classmethod
    def setUpTestData(cls):
        cls.embedder = FakeEmbedder()
        selected = ['rules', 'info', 'bus', 'menu']
        sync_chunks(build_chunks(selected), selected)
        embed_pending(cls.embedder)

    def test_finds_the_curfew_article(self):
        result = search('생활관 출입시간 06:00-23:00', k=5, embedder=self.embedder)
        self.assertEqual(result.hits[0].chunk.key, 'rules:article:3')
        self.assertEqual(set(result.hits[0].found_by), {'vector', 'keyword'})
        self.assertIsNotNone(result.best_similarity)

    def test_source_filter(self):
        result = search('셔틀버스 시간', k=5, sources=['bus'], embedder=self.embedder)
        self.assertTrue(result.hits)
        self.assertTrue(all(h.chunk.source == 'bus' for h in result.hits))

    def test_chunk_without_embedding_is_found_by_keyword(self):
        notice = Notice.objects.create(title='보일러 점검', content='이번 주 금요일 보일러 점검으로 온수가 끊깁니다')
        # 검색 직전 임베딩을 끄면 키워드로만 찾힌다
        result = search('보일러 점검 온수', k=20, embedder=self.embedder, embed_new=False)
        hit = next(h for h in result.hits if h.chunk.key == f'notice:{notice.pk}')
        self.assertEqual(hit.found_by, ['keyword'])

    def test_new_chunk_is_embedded_right_before_search(self):
        notice = Notice.objects.create(title='보일러 점검', content='이번 주 금요일 보일러 점검으로 온수가 끊깁니다')
        result = search('보일러 점검 온수', k=3, embedder=self.embedder)
        self.assertEqual(result.hits[0].chunk.key, f'notice:{notice.pk}')
        self.assertEqual(set(result.hits[0].found_by), {'vector', 'keyword'})

    def test_keyword_only_has_no_similarity(self):
        result = search('출입시간', k=3, use_vector=False)
        self.assertTrue(result.hits)
        self.assertIsNone(result.best_similarity)

    def test_vectors_from_another_model_are_ignored(self):
        class OtherModel(FakeEmbedder):
            name = 'other-model'

        result = search('출입시간', k=3, embedder=OtherModel(), use_keyword=False)
        self.assertEqual(result.hits, [])


class EvaluateCommandTests(TestCase):
    def setUp(self):
        selected = ['rules', 'info', 'bus', 'menu']
        sync_chunks(build_chunks(selected), selected)

    def test_question_file_points_at_existing_chunks(self):
        from knowledge.management.commands.evaluate_knowledge_search import load_questions
        keys = set(KnowledgeChunk.objects.values_list('key', flat=True))
        questions = load_questions()
        self.assertGreaterEqual(len(questions), 30)
        for item in questions:
            self.assertTrue(set(item['expected']) <= keys, item['q'])

    def test_command_reports_metrics_for_each_mode(self):
        out = io.StringIO()
        call_command('evaluate_knowledge_search', '--backend', 'fake', stdout=out)
        text = out.getvalue()
        for mode in ('hybrid', 'vector', 'keyword'):
            self.assertIn(f'| {mode} |', text)

    def test_evaluate_counts_hits_and_mrr(self):
        from knowledge.management.commands.evaluate_knowledge_search import evaluate
        embedder = FakeEmbedder()
        embed_pending(embedder)
        questions = [{'q': '생활관 출입시간 06:00-23:00', 'expected': ['rules:article:3']},
                     {'q': '존재하지않는질문쀍', 'expected': ['rules:article:999']}]
        result = evaluate(questions, embedder, True, True)
        self.assertEqual((result['hit@1'], result['hit@5'], result['mrr']), (0.5, 0.5, 0.5))
        self.assertEqual(result['misses'][0]['q'], '존재하지않는질문쀍')


class KeywordWeightTests(TestCase):
    """키워드 비중 0이면 의미 검색 순위 그대로, 기본값은 ADR 0006의 측정값."""

    @classmethod
    def setUpTestData(cls):
        cls.embedder = FakeEmbedder()
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(cls.embedder)

    def test_zero_keyword_weight_keeps_vector_order(self):
        query = '세탁실 이용 시간'
        vector_only = [h.chunk.key for h in search(query, k=5, embedder=self.embedder, use_keyword=False).hits]
        weighted = [h.chunk.key for h in search(query, k=5, embedder=self.embedder, keyword_weight=0).hits]
        self.assertEqual(weighted, vector_only)

    def test_defaults_match_the_measured_choice(self):
        from knowledge import search as search_module
        self.assertEqual((search_module.RRF_K, search_module.KEYWORD_WEIGHT), (1, 0.25))


class RecordingLLM(FakeLLM):
    """FakeLLM과 같게 답하고(또는 정해 둔 답을 돌려주고), 받은 지시와 근거를 기록한다."""

    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply

    def generate(self, system, prompt):
        self.calls.append((system, prompt))
        return self.reply if self.reply is not None else super().generate(system, prompt)


class AnswerDraftTests(TestCase):
    """문의 답변 초안: 근거 부족 판단, 개인정보 가리기, 인용 검사 (모델은 대역 사용)."""

    @classmethod
    def setUpTestData(cls):
        cls.embedder = FakeEmbedder()
        selected = ['rules', 'info']
        sync_chunks(build_chunks(selected), selected)
        embed_pending(cls.embedder)

    def draft(self, title, content, llm, **kwargs):
        # 가짜 임베딩의 유사도는 bge-m3와 눈금이 달라 기준값을 테스트마다 직접 준다
        kwargs.setdefault('min_similarity', 0.0)
        return draft_for_text(title, content, llm=llm, embedder=self.embedder, **kwargs)

    def test_draft_cites_the_evidence_it_was_given(self):
        llm = RecordingLLM()
        draft = self.draft('출입시간 문의', '생활관 출입시간이 06:00-23:00 맞나요?', llm)
        self.assertEqual(draft.status, 'ok')
        self.assertEqual(len(draft.evidence), 5)
        self.assertEqual(draft.cited, [1])
        self.assertEqual(draft.warnings, [])
        self.assertEqual(draft.model, 'fake')
        system, prompt = llm.calls[0]
        self.assertIn('근거]에 적힌 내용만', system)
        self.assertIn(f'[1] {draft.evidence[0].chunk.title}', prompt)

    def test_personal_info_never_reaches_the_model_or_the_draft(self):
        llm = RecordingLLM(reply='홍길동 학생(010-1234-5678), 출입시간은 23:00까지입니다 [1]')
        draft = self.draft('외박 문의', '저는 홍길동, 22041013, 010-1234-5678 입니다. 출입시간 알려주세요',
                           llm, known_names=['홍길동'])
        prompt = llm.calls[0][1]
        for secret in ('홍길동', '22041013', '010-1234-5678'):
            self.assertNotIn(secret, prompt)
            self.assertNotIn(secret, draft.text)

    def test_weak_evidence_skips_the_model(self):
        llm = RecordingLLM()
        draft = self.draft('날씨', '오늘 서울 날씨 어때요?', llm, min_similarity=0.99)
        self.assertEqual(draft.status, 'insufficient_evidence')
        self.assertEqual(llm.calls, [])
        self.assertIn('직접 답변', draft.warnings[0])

    def test_made_up_citation_numbers_are_flagged(self):
        draft = self.draft('출입시간', '출입시간 알려주세요', RecordingLLM(reply='23:00까지입니다 [1][9]'))
        self.assertEqual(draft.cited, [1])
        self.assertIn('[9]', draft.warnings[0])

    def test_missing_citations_are_flagged(self):
        draft = self.draft('출입시간', '출입시간 알려주세요', RecordingLLM(reply='23:00까지입니다.'))
        self.assertIn('근거 번호가 없습니다', draft.warnings[0])

    def test_refusal_without_citations_is_not_a_warning(self):
        draft = self.draft('출입시간', '출입시간 알려주세요', RecordingLLM(reply='근거 자료에서 확인할 수 없습니다.'))
        self.assertEqual(draft.warnings, [])

    def test_model_failure_is_reported_not_raised(self):
        class Broken(FakeLLM):
            def generate(self, system, prompt):
                raise LLMError('Ollama에 연결할 수 없습니다')

        draft = self.draft('출입시간', '출입시간 알려주세요', Broken())
        self.assertEqual(draft.status, 'error')
        self.assertIn('연결할 수 없습니다', draft.warnings[0])

    def test_inquiry_draft_does_not_use_its_own_answer_as_evidence(self):
        student = User.objects.create_user('20250001', password='pw12345!')
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        inquiry = Inquiry.objects.create(user=student, title='출입시간', content='생활관 출입시간 알려주세요')
        InquiryAnswer.objects.create(inquiry=inquiry, admin=staff, answer='06:00-23:00입니다')
        own_key = f'inquiry:{inquiry.pk}'
        embed_pending(self.embedder)
        self.assertIn(own_key, [h.chunk.key for h in search('출입시간\n생활관 출입시간 알려주세요',
                                                             embedder=self.embedder).hits])
        draft = draft_answer(inquiry, llm=RecordingLLM(), embedder=self.embedder, min_similarity=0.0)
        self.assertEqual(len(draft.evidence), 5)
        self.assertNotIn(own_key, [h.chunk.key for h in draft.evidence])


class LLMBackendTests(TestCase):
    def test_ollama_sends_a_chat_request_and_strips_thinking(self):
        captured = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            captured['url'] = request.full_url
            captured['body'] = json.loads(request.data.decode('utf-8'))
            reply = {'message': {'content': '<think>고민</think>출입시간은 23:00까지입니다 [1]'}}
            return Response(json.dumps(reply).encode('utf-8'))

        with mock.patch('urllib.request.urlopen', fake_urlopen):
            text = OllamaLLM('exaone3.5:7.8b', 'http://127.0.0.1:11434/').generate('규칙', '문의')
        self.assertEqual(text, '출입시간은 23:00까지입니다 [1]')
        self.assertEqual(captured['url'], 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(captured['body']['model'], 'exaone3.5:7.8b')
        self.assertFalse(captured['body']['stream'])
        self.assertEqual([m['role'] for m in captured['body']['messages']], ['system', 'user'])

    def test_ollama_connection_failure_becomes_llm_error(self):
        def refuse(request, timeout):
            raise urllib.error.URLError('connection refused')

        with mock.patch('urllib.request.urlopen', refuse), self.assertRaises(LLMError) as ctx:
            OllamaLLM('m', 'http://127.0.0.1:11434').generate('s', 'p')
        self.assertIn('Ollama', str(ctx.exception))

    def test_get_llm_backends(self):
        self.assertIsInstance(get_llm('fake'), FakeLLM)
        self.assertEqual(get_llm('ollama', 'qwen3:8b').name, 'qwen3:8b')
        with self.assertRaises(ValueError):
            get_llm('nope')


class AnswerDraftEvaluationTests(TestCase):
    """답변 초안 평가 명령의 채점 규칙."""

    def make_draft(self, text, cited=(), status='ok', warnings=()):
        from knowledge.answering import Draft
        from knowledge.search import SearchHit
        evidence = [SearchHit(chunk=KnowledgeChunk(key=key, title=key, content=''), score=1.0) for key in ('rules:article:3', 'info:article:1')]
        return Draft(status=status, text=text, evidence=evidence, cited=list(cited), warnings=list(warnings))

    def test_facts_accept_any_alternative(self):
        from knowledge.management.commands.evaluate_answer_drafts import grade
        item = {'q': '통금?', 'expected': ['rules:article:3'], 'facts': ['23:00|오후 11시']}
        row = grade('answerable', item, self.make_draft('출입은 오후 11시까지입니다 [1]', cited=[1]))
        self.assertTrue(row['facts_ok'])
        self.assertTrue(row['cites_expected'])
        self.assertFalse(row['refused'])

    def test_citing_the_wrong_evidence_is_not_counted(self):
        from knowledge.management.commands.evaluate_answer_drafts import grade
        item = {'q': '통금?', 'expected': ['rules:article:3'], 'facts': ['23:00']}
        row = grade('answerable', item, self.make_draft('명현관입니다 [2]', cited=[2]))
        self.assertFalse(row['facts_ok'])
        self.assertFalse(row['cites_expected'])

    def test_refusals_and_foreign_text(self):
        from knowledge.management.commands.evaluate_answer_drafts import grade
        refused = grade('out_of_scope', '도서관?', self.make_draft('근거 자료에서 확인할 수 없습니다.'))
        skipped = grade('out_of_scope', '도서관?', self.make_draft('', status='insufficient_evidence'))
        answered = grade('out_of_scope', '도서관?', self.make_draft('도서관은 22時까지입니다 [1]', cited=[1]))
        self.assertTrue(refused['refused'])
        self.assertTrue(skipped['refused'])
        self.assertFalse(answered['refused'])
        self.assertTrue(answered['foreign'])

    def test_command_runs_with_fake_models(self):
        selected = ['rules', 'info']
        sync_chunks(build_chunks(selected), selected)
        out = io.StringIO()
        call_command('evaluate_answer_drafts', backend='fake', embedding_backend='fake', min_similarity=0.0,
                     limit=3, stdout=out)
        table = out.getvalue()
        self.assertIn('| fake |', table)
        self.assertIn('답할 수 있는 질문 3개, 범위 밖 질문 3개', table)


class QueryExpansionTests(TestCase):
    """학생이 쓰는 말을 규정 용어로 보강하는 검색어 확장."""

    def test_everyday_words_get_regulation_terms(self):
        from knowledge.search import expand_query
        self.assertEqual(expand_query('전기장판 써도 돼?'), '전기장판 써도 돼? (전열기 난방 도구)')
        self.assertEqual(expand_query('룸메랑 안 맞아'), '룸메랑 안 맞아 (실원 실 이동)')

    def test_terms_already_in_the_question_are_not_repeated(self):
        from knowledge.search import expand_query
        self.assertEqual(expand_query('통금 출입시간 알려줘'), '통금 출입시간 알려줘')
        self.assertEqual(expand_query('담배랑 전자담배'), '담배랑 전자담배 (흡연)')

    def test_other_questions_are_unchanged(self):
        from knowledge.search import expand_query
        self.assertEqual(expand_query('수요일 점심 메뉴 뭐야?'), '수요일 점심 메뉴 뭐야?')

    def test_search_uses_the_expanded_query(self):
        selected = ['rules']
        sync_chunks(build_chunks(selected), selected)
        embed_pending(FakeEmbedder())
        keys = [h.chunk.key for h in search('전기장판 써도 돼?', embedder=FakeEmbedder(), use_vector=False).hits]
        self.assertIn('rules:article:10', keys)


class DraftPromptTests(TestCase):
    """작은 모델이 규칙을 지키도록: 예시를 보여 주고, 근거 바로 뒤에 핵심 규칙을 한 번 더 둔다 (ADR 0010)."""

    def test_prompt_ends_with_the_rule_reminder(self):
        from knowledge.answering import REMINDER, build_prompt
        from knowledge.search import SearchHit
        hit = SearchHit(chunk=KnowledgeChunk(key='rules:article:3', title='제3조', content='06:00-23:00'), score=1.0)
        prompt = build_prompt('통금', '몇 시까지?', [hit])
        self.assertTrue(prompt.endswith(REMINDER))
        self.assertIn('[1] 제3조\n06:00-23:00', prompt)

    def test_system_prompt_shows_an_answer_and_a_refusal(self):
        from knowledge.answering import SYSTEM_PROMPT
        self.assertIn('예시 1', SYSTEM_PROMPT)
        self.assertIn('답변: 근거 자료에서 확인할 수 없습니다.', SYSTEM_PROMPT)


class StudentChatTests(TestCase):
    """학생 챗봇: 공개 자료만 쓰고, 인용 검사를 통과한 답만 보여 준다 (ADR 0011)."""

    @classmethod
    def setUpTestData(cls):
        cls.embedder = FakeEmbedder()
        selected = ['rules', 'info']
        sync_chunks(build_chunks(selected), selected)
        student = User.objects.create_user('20250001', password='pw12345!')
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        cls.inquiry = Inquiry.objects.create(user=student, title='출입시간', content='생활관 출입시간 알려주세요')
        InquiryAnswer.objects.create(inquiry=cls.inquiry, admin=staff, answer='06:00-23:00입니다')
        embed_pending(cls.embedder)

    def ask(self, question, llm, **kwargs):
        from knowledge.chat import answer_question
        kwargs.setdefault('min_similarity', 0.0)
        return answer_question(question, llm=llm, embedder=self.embedder, **kwargs)

    def test_cited_answer_is_shown_with_its_sources(self):
        llm = RecordingLLM()
        reply = self.ask('생활관 출입시간 알려주세요', llm)
        self.assertEqual(reply.status, 'answered')
        self.assertEqual(reply.text, reply.draft.text)
        self.assertEqual([s['number'] for s in reply.sources], [1])
        self.assertEqual(reply.sources[0]['title'], reply.draft.evidence[0].chunk.title)
        from knowledge.chat import SYSTEM_PROMPT
        self.assertEqual(llm.calls[0][0], SYSTEM_PROMPT)

    def test_other_students_inquiries_are_never_used(self):
        reply = self.ask('생활관 출입시간 알려주세요', RecordingLLM())
        keys = [h.chunk.key for h in reply.draft.evidence]
        self.assertNotIn(f'inquiry:{self.inquiry.pk}', keys)
        self.assertTrue(all(not key.startswith('inquiry:') for key in keys))

    def test_uncited_or_made_up_citations_are_hidden(self):
        from knowledge.chat import UNVERIFIED_MESSAGE
        for reply_text in ('23:00까지입니다.', '23:00까지입니다 [9]'):
            reply = self.ask('출입시간 알려주세요', RecordingLLM(reply=reply_text))
            self.assertEqual(reply.status, 'unverified')
            self.assertEqual(reply.text, UNVERIFIED_MESSAGE)
            self.assertNotIn('23:00', reply.text)
            self.assertEqual([s['number'] for s in reply.sources], [1, 2, 3])

    def test_refusal_and_weak_evidence_suggest_an_inquiry(self):
        from knowledge.chat import NO_ANSWER_MESSAGE
        refused = self.ask('출입시간 알려주세요', RecordingLLM(reply='근거 자료에서 확인할 수 없습니다. 생활관에 직접 문의해 주세요.'))
        llm = RecordingLLM()
        weak = self.ask('오늘 날씨 어때?', llm, min_similarity=0.99)
        for reply in (refused, weak):
            self.assertEqual(reply.status, 'no_answer')
            self.assertEqual(reply.text, NO_ANSWER_MESSAGE)
            self.assertEqual(reply.sources, [])
        self.assertEqual(llm.calls, [])

    def test_model_failure_gives_a_friendly_message(self):
        from knowledge.chat import ERROR_MESSAGE

        class Broken(FakeLLM):
            def generate(self, system, prompt):
                raise LLMError('Ollama에 연결할 수 없습니다')

        reply = self.ask('출입시간 알려주세요', Broken())
        self.assertEqual(reply.status, 'error')
        self.assertEqual(reply.text, ERROR_MESSAGE)

    def test_long_questions_are_cut_and_personal_info_is_masked(self):
        from knowledge.chat import MAX_QUESTION_LENGTH
        llm = RecordingLLM()
        self.ask('저는 010-1234-5678 입니다. 출입시간 ' + '가' * 2000, llm)
        prompt = llm.calls[0][1]
        self.assertNotIn('010-1234-5678', prompt)
        self.assertLess(prompt.count('가'), MAX_QUESTION_LENGTH)

    def test_chat_mode_of_the_evaluation_command(self):
        out = io.StringIO()
        call_command('evaluate_answer_drafts', mode='chat', backend='fake', embedding_backend='fake',
                     min_similarity=0.0, limit=2, stdout=out)
        self.assertIn('## 학생 챗봇 평가', out.getvalue())

    def test_answers_that_open_with_not_found_are_not_shown(self):
        from knowledge.chat import NO_ANSWER_MESSAGE, opens_with_not_found
        self.assertTrue(opens_with_not_found('안녕하세요. 졸업 학점은 근거 자료에 명시되어 있지 않습니다 [5]. 학과에 문의하세요.'))
        reply = self.ask('졸업 학점', RecordingLLM(reply='졸업 학점은 근거 자료에 명시되어 있지 않습니다 [1].'))
        self.assertEqual(reply.status, 'no_answer')
        self.assertEqual(reply.text, NO_ANSWER_MESSAGE)

    def test_a_later_caveat_does_not_hide_a_good_answer(self):
        from knowledge.chat import opens_with_not_found
        text = '안녕하세요. 남자 기숙사는 명현관입니다 [1]. 여자 기숙사는 명인관입니다 [1]. 다른 별칭은 확인할 수 없습니다.'
        self.assertFalse(opens_with_not_found(text))
        reply = self.ask('남자 기숙사 이름', RecordingLLM(reply=text))
        self.assertEqual(reply.status, 'answered')

    def test_markdown_bold_is_removed_from_answers(self):
        reply = self.ask('출입시간', RecordingLLM(reply='1. **출입시간**: 06:00-23:00입니다 [1].'))
        self.assertEqual(reply.status, 'answered')
        self.assertEqual(reply.text, '1. 출입시간: 06:00-23:00입니다 [1].')


class ChatLogTests(TestCase):
    """익명 대화 기록과 👍/👎 (docs/adr/0012). 누가 물었는지는 저장하지 않는다."""

    @classmethod
    def setUpTestData(cls):
        cls.embedder = FakeEmbedder()
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(cls.embedder)

    def reply(self, question='생활관 출입시간 알려주세요', llm=None, names=()):
        from knowledge.chat import answer_question
        return answer_question(question, known_names=names, llm=llm or RecordingLLM(), embedder=self.embedder,
                               min_similarity=0.0)

    def record(self, reply, channel='web'):
        from knowledge.chat_log import record_chat
        return record_chat(reply, channel)

    def test_log_keeps_the_masked_question_but_not_the_person(self):
        from knowledge.models import ChatLog
        log, token = self.record(self.reply('저는 홍길동(010-1234-5678)인데 출입시간 알려주세요', names=['홍길동']))
        self.assertNotIn('홍길동', log.question)
        self.assertNotIn('010-1234-5678', log.question)
        self.assertIn('[이름]', log.question)
        self.assertEqual(log.status, 'answered')
        self.assertEqual(log.channel, 'web')
        self.assertTrue(log.cited_keys)
        self.assertEqual(len(log.evidence_keys), 5)
        related = [f.name for f in ChatLog._meta.get_fields() if f.is_relation]
        self.assertEqual(related, [])  # 사용자와 연결하지 않는다
        self.assertNotEqual(log.feedback_token_hash, token)  # 키는 해시로만 저장

    def test_only_the_key_holder_can_rate_once(self):
        from knowledge.chat_log import give_feedback
        log, token = self.record(self.reply())
        self.assertEqual(give_feedback(log.pk, 'wrong-key', 'up'), 'invalid')
        self.assertEqual(give_feedback(log.pk + 999, token, 'up'), 'invalid')
        self.assertEqual(give_feedback(log.pk, token, 'down', 'wrong'), 'ok')
        self.assertEqual(give_feedback(log.pk, token, 'up'), 'already')
        log.refresh_from_db()
        self.assertEqual((log.feedback, log.feedback_reason), ('down', 'wrong'))
        self.assertIsNotNone(log.feedback_at)

    def test_reason_is_kept_only_for_thumbs_down(self):
        from knowledge.chat_log import give_feedback
        log, token = self.record(self.reply())
        self.assertEqual(give_feedback(log.pk, token, 'up', 'wrong'), 'ok')
        log.refresh_from_db()
        self.assertEqual(log.feedback_reason, '')
        other, other_token = self.record(self.reply())
        self.assertEqual(give_feedback(other.pk, other_token, 'down', 'nonsense'), 'invalid')

    def test_old_logs_are_purged_after_the_retention_period(self):
        from datetime import timedelta
        from django.utils import timezone
        from knowledge.models import ChatLog
        old, _ = self.record(self.reply())
        recent, _ = self.record(self.reply())
        ChatLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=181))
        ChatLog.objects.filter(pk=recent.pk).update(created_at=timezone.now() - timedelta(days=179))
        out = io.StringIO()
        call_command('purge_chat_logs', stdout=out)
        self.assertEqual(list(ChatLog.objects.values_list('pk', flat=True)), [recent.pk])
        self.assertIn('1개', out.getvalue())

    def test_misses_are_exported_as_eval_question_candidates(self):
        import yaml as yaml_module
        from knowledge.chat_log import give_feedback
        refusal = '근거 자료에서 확인할 수 없습니다.'
        self.record(self.reply('도서관 몇 시까지 열어?', llm=RecordingLLM(reply=refusal)))
        self.record(self.reply('도서관 몇 시까지 열어?', llm=RecordingLLM(reply=refusal)))
        disliked, token = self.record(self.reply('세탁 몇 시까지 돼?'))
        give_feedback(disliked.pk, token, 'down', 'wrong')
        liked, token = self.record(self.reply('출입시간 알려줘'))
        give_feedback(liked.pk, token, 'up')
        out = io.StringIO()
        call_command('export_chat_misses', stdout=out)
        items = yaml_module.safe_load(out.getvalue())
        questions = {item['q']: item for item in items}
        self.assertEqual(questions['도서관 몇 시까지 열어?']['count'], 2)
        self.assertEqual(questions['세탁 몇 시까지 돼?']['reasons'], ['👎 wrong'])
        self.assertNotIn('출입시간 알려줘', questions)
        self.assertTrue(all(item['expected'] == [] for item in items))

    def test_followup_misses_are_exported_with_the_rewritten_question(self):
        import yaml as yaml_module
        refusal = '근거 자료에서 확인할 수 없습니다.'
        reply = self.reply('그럼 주말에는?', llm=RecordingLLM(reply=refusal))
        reply.rewritten_question = '주말에 세탁실 이용 시간은 언제인가요?'
        self.record(reply)
        out = io.StringIO()
        call_command('export_chat_misses', stdout=out)
        self.assertEqual([item['q'] for item in yaml_module.safe_load(out.getvalue())],
                         ['주말에 세탁실 이용 시간은 언제인가요?'])


class WarmUpTests(TestCase):
    """콜드 스타트 줄이기: 모델 유지 시간과 미리 깨우기 (docs/adr/0013)."""

    def capture(self, reply=None):
        captured = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            captured.append((request.full_url, json.loads(request.data.decode('utf-8'))))
            return Response(json.dumps(reply or {'message': {'content': '답 [1]'}}).encode('utf-8'))

        return captured, mock.patch('urllib.request.urlopen', fake_urlopen)

    def test_every_request_keeps_the_model_loaded(self):
        captured, patch = self.capture()
        with patch:
            OllamaLLM('m', 'http://127.0.0.1:11434', keep_alive='30m').generate('s', 'p')
        self.assertEqual(captured[0][1]['keep_alive'], '30m')

    def test_keep_alive_comes_from_settings(self):
        from django.test import override_settings
        with override_settings(KNOWLEDGE_LLM={'BACKEND': 'ollama', 'MODEL': 'm', 'KEEP_ALIVE': '-1'}):
            self.assertEqual(get_llm().keep_alive, '-1')
        with override_settings(KNOWLEDGE_LLM={'BACKEND': 'ollama', 'MODEL': 'm'}):
            self.assertEqual(get_llm().keep_alive, '30m')

    def test_warm_up_reads_the_system_prompt_with_the_same_options(self):
        from knowledge.llm import OPTIONS
        captured, patch = self.capture()
        llm = OllamaLLM('exaone3.5:7.8b', 'http://127.0.0.1:11434', keep_alive='30m')
        with patch:
            llm.warm_up('규칙')
            llm.generate('규칙', '문의')
        (warm_url, warm), (_, real) = captured
        self.assertEqual(warm_url, 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(warm['messages'][0], {'role': 'system', 'content': '규칙'})
        self.assertEqual(warm['options']['num_predict'], 1)
        # num_ctx 등이 다르면 Ollama가 질문 때 모델을 다시 올린다
        self.assertEqual({k: v for k, v in warm['options'].items() if k != 'num_predict'}, real['options'])
        self.assertEqual(real['options'], OPTIONS)
        self.assertEqual(warm['keep_alive'], '30m')

    def test_warm_up_runs_once_while_models_are_warm(self):
        from knowledge import chat
        calls = []

        class Embedder:
            def embed_query(self, text):
                calls.append('embed')

        class Model:
            def warm_up(self, system=''):
                calls.append('llm' if system else 'llm without prompt')

        chat._last_warm_up = None
        with mock.patch('knowledge.chat.get_embedder', return_value=Embedder()), \
                mock.patch('knowledge.chat.get_llm', return_value=Model()):
            self.assertTrue(chat.warm_up_models())
            self.assertFalse(chat.warm_up_models())  # 방금 깨웠으면 다시 하지 않는다
        self.assertEqual(sorted(calls), ['embed', 'llm'])

    def test_warm_up_failure_is_only_logged(self):
        from knowledge import chat

        class Model:
            def warm_up(self, system=''):
                raise LLMError('Ollama에 연결할 수 없습니다')

        chat._last_warm_up = None
        with mock.patch('knowledge.chat.get_embedder', return_value=FakeEmbedder()), \
                mock.patch('knowledge.chat.get_llm', return_value=Model()), \
                self.assertLogs('knowledge.chat', level='WARNING'):
            self.assertTrue(chat.warm_up_models())


class RouterTests(TestCase):
    """메시지 종류 판단기 (docs/adr/0014)."""

    def test_jev_request_and_answer(self):
        from knowledge.router import CRITERIA, JevRouter
        captured = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            captured['url'] = request.full_url
            captured['auth'] = request.get_header('Authorization')
            captured['body'] = json.loads(request.data.decode('utf-8'))
            reply = {'model': 'jev-1.14.0', 'answers': {'kind': {'type': 'choice', 'choice': 'meta', 'confidence': 0.9}}}
            return Response(json.dumps(reply).encode('utf-8'))

        previous = {'question': '통금 몇 시야?', 'answer': '06:00-23:00입니다 [1].'}
        with mock.patch('urllib.request.urlopen', fake_urlopen):
            kind = JevRouter('test-key').classify('요약해줘', previous)
        self.assertEqual(kind, 'meta')
        self.assertEqual(captured['url'], 'https://api.typesafe.ai/v1/systemone')
        self.assertEqual(captured['auth'], 'Bearer test-key')
        question = captured['body']['questions']['kind']
        self.assertEqual((question['type'], question['criteria']), ('choice', CRITERIA))
        self.assertIn('통금 몇 시야?', captured['body']['state'])
        self.assertTrue(captured['body']['state'].endswith('학생: 요약해줘'))

    def test_jev_failure_falls_back_to_the_local_router(self):
        from knowledge.router import FakeRouter, JevRouter

        def refuse(request, timeout):
            raise urllib.error.URLError('down')

        with mock.patch('urllib.request.urlopen', refuse), self.assertLogs('knowledge.router', level='WARNING'):
            self.assertEqual(JevRouter('k', fallback=FakeRouter()).classify('고마워'), 'smalltalk')
            self.assertEqual(JevRouter('k').classify('고마워'), 'new')

    def test_llm_router_reads_one_word(self):
        from knowledge.router import LLMRouter
        self.assertEqual(LLMRouter(RecordingLLM(reply=' Followup')).classify('그럼 벌점은?'), 'followup')
        self.assertEqual(LLMRouter(RecordingLLM(reply='모르겠어요')).classify('?'), 'new')

    def test_router_choice_from_settings(self):
        from django.test import override_settings
        from knowledge.router import JevRouter, LLMRouter, get_router
        with override_settings(KNOWLEDGE_ROUTER={'BACKEND': 'jev', 'API_KEY': ''},
                               KNOWLEDGE_LLM={'BACKEND': 'fake'}):
            self.assertIsInstance(get_router(), LLMRouter)  # 키가 없으면 로컬
        with override_settings(KNOWLEDGE_ROUTER={'BACKEND': 'jev', 'API_KEY': 'k'},
                               KNOWLEDGE_LLM={'BACKEND': 'fake'}):
            router = get_router()
            self.assertIsInstance(router, JevRouter)
            self.assertIsInstance(router.fallback, LLMRouter)


class ConversationTests(TestCase):
    """이어지는 대화: 서버에만 기억하고, 종류별로 처리한다 (docs/adr/0014)."""

    @classmethod
    def setUpTestData(cls):
        cls.embedder = FakeEmbedder()
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(cls.embedder)

    def setUp(self):
        from django.core.cache import cache
        from knowledge.router import FakeRouter
        cache.clear()
        self.router = FakeRouter()

    def say(self, message, conversation_id=None, user_id=1, llm=None):
        from knowledge.conversation import reply_to
        return reply_to(message, user_id, conversation_id, router=self.router, llm=llm or RecordingLLM(),
                        embedder=self.embedder, min_similarity=0.0)

    def test_new_question_starts_a_conversation(self):
        reply, conversation_id = self.say('생활관 출입시간 알려주세요')
        self.assertEqual((reply.status, reply.kind), ('answered', 'new'))
        self.assertRegex(conversation_id, r'^[A-Za-z0-9_-]{16,64}$')

    def test_smalltalk_needs_no_search_or_model(self):
        from knowledge.conversation import GREETING_REPLY, THANKS_REPLY
        llm = RecordingLLM()
        with mock.patch('knowledge.conversation.answer_question') as answer_question:
            hello, _ = self.say('안녕', llm=llm)
            thanks, _ = self.say('고마워', llm=llm)
        answer_question.assert_not_called()
        self.assertEqual(llm.calls, [])
        self.assertEqual((hello.text, hello.kind, hello.status), (GREETING_REPLY, 'smalltalk', 'answered'))
        self.assertEqual(thanks.text, THANKS_REPLY)

    def test_summary_uses_the_previous_answer_and_its_evidence(self):
        first, conversation_id = self.say('생활관 출입시간 알려주세요')
        llm = RecordingLLM(reply='출입시간은 06:00-23:00입니다 [1].')
        summary, same_id = self.say('요약해줘', conversation_id, llm=llm)
        self.assertEqual(same_id, conversation_id)
        self.assertEqual((summary.status, summary.kind), ('answered', 'meta'))
        system, prompt = llm.calls[0]
        self.assertIn('[앞 답]\n' + first.text, prompt)
        self.assertIn(f'[1] {first.draft.evidence[0].chunk.title}', prompt)
        self.assertIn('[학생의 요청]\n요약해줘', prompt)
        self.assertEqual([h.chunk.key for h in summary.draft.evidence], [h.chunk.key for h in first.draft.evidence])
        self.assertEqual(summary.sources[0]['title'], first.draft.evidence[0].chunk.title)

    def test_summary_with_a_made_up_citation_is_hidden(self):
        _, conversation_id = self.say('생활관 출입시간 알려주세요')
        summary, _ = self.say('요약해줘', conversation_id, llm=RecordingLLM(reply='24시간 출입 가능합니다 [9].'))
        self.assertEqual(summary.status, 'unverified')
        self.assertNotIn('24시간', summary.text)

    def test_nothing_to_repeat_after_a_missing_answer(self):
        from knowledge.conversation import NOTHING_TO_REPEAT
        refusal = RecordingLLM(reply='근거 자료에서 확인할 수 없습니다.')
        first, conversation_id = self.say('도서관 몇 시까지 해?', llm=refusal)
        self.assertEqual(first.status, 'no_answer')
        llm = RecordingLLM()
        again, _ = self.say('다시 말해줘', conversation_id, llm=llm)
        self.assertEqual((again.status, again.text), ('no_answer', NOTHING_TO_REPEAT))
        self.assertEqual(llm.calls, [])

    def test_meta_without_a_conversation_is_a_new_question(self):
        reply, _ = self.say('다시 출입시간 알려주세요')
        self.assertEqual(reply.kind, 'new')

    def test_memory_is_per_user_and_keeps_three_turns(self):
        from knowledge.conversation import MAX_TURNS, load_turns
        _, conversation_id = self.say('생활관 출입시간 알려주세요', user_id=1)
        other, _ = self.say('요약해줘', conversation_id, user_id=2)  # 남의 대화 번호로는 이어지지 않는다
        self.assertEqual(other.kind, 'new')
        for question in ('세탁 시간', '대청소 요일', '점검 시간'):
            self.say(question, conversation_id, user_id=1)
        turns = load_turns(1, conversation_id)
        self.assertEqual(len(turns), MAX_TURNS)
        self.assertEqual(turns[-1]['question'], '점검 시간')

    def test_memory_expires_after_thirty_minutes(self):
        from knowledge.conversation import MEMORY_SECONDS
        self.assertEqual(MEMORY_SECONDS, 30 * 60)
        with mock.patch('knowledge.conversation.cache') as fake_cache:
            fake_cache.get.return_value = []
            self.say('안녕')
        self.assertEqual(fake_cache.set.call_args.kwargs['timeout'], MEMORY_SECONDS)

    def test_bad_conversation_ids_start_over(self):
        _, conversation_id = self.say('안녕', conversation_id='../../etc')
        self.assertNotEqual(conversation_id, '../../etc')

    def test_kind_is_logged(self):
        from knowledge.chat_log import record_chat
        reply, _ = self.say('고마워')
        log, _ = record_chat(reply, 'web')
        self.assertEqual(log.kind, 'smalltalk')

    def test_meta_mode_of_the_evaluation_command(self):
        out = io.StringIO()
        with mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0):
            call_command('evaluate_answer_drafts', mode='meta', backend='fake', embedding_backend='fake',
                         min_similarity=0.0, limit=3, stdout=out)
        self.assertIn('## 다시 말하기·요약 평가', out.getvalue())

    def rewriting_llm(self, rewrite):
        """다시 쓰기 요청에는 정해 둔 질문을, 답 요청에는 FakeLLM처럼 답한다."""
        from knowledge.conversation import REWRITE_SYSTEM

        class RewritingLLM(RecordingLLM):
            def generate(self, system, prompt):
                if system == REWRITE_SYSTEM:
                    self.calls.append((system, prompt))
                    if isinstance(rewrite, Exception):
                        raise rewrite
                    return rewrite
                return super().generate(system, prompt)
        return RewritingLLM()

    def test_followup_is_rewritten_into_a_standalone_question(self):
        from knowledge.conversation import REWRITE_SYSTEM
        first, conversation_id = self.say('대청소는 무슨 요일에 해?')
        llm = self.rewriting_llm('[바꾼 질문] 호실 점검은 무슨 요일에 하나요?\n설명은 쓰지 않습니다.')
        reply, _ = self.say('그럼 호실 점검은?', conversation_id, llm=llm)
        self.assertEqual(reply.kind, 'followup')
        self.assertEqual(reply.question, '그럼 호실 점검은?')
        self.assertEqual(reply.rewritten_question, '호실 점검은 무슨 요일에 하나요?')
        system, prompt = llm.calls[0]
        self.assertEqual(system, REWRITE_SYSTEM)
        self.assertIn('대청소는 무슨 요일에 해?', prompt)
        self.assertIn('그럼 호실 점검은?', prompt)
        self.assertIn('호실 점검은 무슨 요일에 하나요?', llm.calls[1][1])  # 답은 다시 쓴 질문으로 찾고 쓴다
        self.assertEqual(reply.status, 'answered')

    def test_followup_is_verified_against_the_rewritten_question(self):
        from knowledge.verify import FakeVerifier
        _, conversation_id = self.say('대청소는 무슨 요일에 해?')
        verifier = FakeVerifier()
        with mock.patch.object(verifier, 'verify', wraps=verifier.verify) as verify:
            from knowledge.conversation import reply_to
            reply_to('그럼 호실 점검은?', 1, conversation_id, router=self.router,
                     llm=self.rewriting_llm('호실 점검은 언제 하나요?'), embedder=self.embedder,
                     min_similarity=0.0, verifier=verifier)
        self.assertEqual(verify.call_args.args[0], '호실 점검은 언제 하나요?')

    def test_failed_rewrite_falls_back_to_the_original_message(self):
        from knowledge.llm import LLMError
        _, conversation_id = self.say('대청소는 무슨 요일에 해?')
        for rewrite in (LLMError('down'), '', '근거 자료에서 확인할 수 없습니다.', '호실 점검은 수요일입니다.'):
            reply, _ = self.say('그럼 호실 점검은?', conversation_id, llm=self.rewriting_llm(rewrite))
            self.assertEqual(reply.kind, 'followup')
            self.assertEqual(reply.rewritten_question, '')
            self.assertNotEqual(reply.status, 'error')

    def test_rewritten_question_is_masked_and_remembered(self):
        from knowledge.conversation import load_turns
        _, conversation_id = self.say('대청소는 무슨 요일에 해?')
        reply, _ = self.say('그럼 호실 점검은?', conversation_id,
                            llm=self.rewriting_llm('010-1234-5678 학생의 호실 점검은 언제인가요?'))
        self.assertNotIn('010-1234-5678', reply.rewritten_question)
        self.assertEqual(load_turns(1, conversation_id)[-1]['rewritten_question'], reply.rewritten_question)

    def test_next_followup_sees_the_rewritten_question(self):
        _, conversation_id = self.say('대청소는 무슨 요일에 해?')
        self.say('그럼 호실 점검은?', conversation_id, llm=self.rewriting_llm('호실 점검은 언제 하나요?'))
        llm = self.rewriting_llm('호실 점검 시간은 몇 시인가요?')
        self.say('그럼 몇 시에?', conversation_id, llm=llm)
        self.assertIn('호실 점검은 언제 하나요?', llm.calls[0][1])

    def test_rewritten_question_is_logged(self):
        from knowledge.chat_log import record_chat
        _, conversation_id = self.say('대청소는 무슨 요일에 해?')
        reply, _ = self.say('그럼 호실 점검은?', conversation_id, llm=self.rewriting_llm('호실 점검은 언제 하나요?'))
        log, _ = record_chat(reply, 'web')
        self.assertEqual((log.kind, log.rewritten_question), ('followup', '호실 점검은 언제 하나요?'))

    def test_followup_mode_of_the_evaluation_command(self):
        out = io.StringIO()
        with mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0):
            call_command('evaluate_answer_drafts', mode='followup', backend='fake', embedding_backend='fake',
                         min_similarity=0.0, limit=3, stdout=out)
        self.assertIn('## 이어지는 질문 평가', out.getvalue())

    def test_router_evaluation_command(self):
        out = io.StringIO()
        call_command('evaluate_router', backend='fake', stdout=out)
        text = out.getvalue()
        self.assertIn('## 메시지 종류 판단: fake', text)
        self.assertIn('| tuned |', text)
        self.assertIn('| held_out |', text)


class AnswerVerificationTests(TestCase):
    """답을 보여 주기 전 판단 모델 검증 (docs/adr/0015)."""

    @classmethod
    def setUpTestData(cls):
        cls.embedder = FakeEmbedder()
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(cls.embedder)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def jev_call(self, scores, raise_error=None):
        captured = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            if raise_error:
                raise raise_error
            captured['body'] = json.loads(request.data.decode('utf-8'))
            answers = {name: {'type': 'noul', 'noul': value} for name, value in scores.items()}
            return Response(json.dumps({'answers': answers}).encode('utf-8'))

        return captured, mock.patch('urllib.request.urlopen', fake_urlopen)

    def hits(self):
        return search('생활관 출입시간', embedder=self.embedder).hits[:2]

    def test_jev_is_asked_both_questions_with_question_evidence_and_answer(self):
        from knowledge.verify import QUESTIONS, JevVerifier
        captured, patch = self.jev_call({'answers': 0.9, 'contradicts': 0.1})
        hits = self.hits()
        with patch:
            verdict = JevVerifier('k').verify('통금 몇 시야?', hits, '23:00까지입니다 [1].')
        self.assertTrue(verdict.passed)
        self.assertTrue(verdict.checked)
        self.assertEqual(captured['body']['questions'], QUESTIONS)
        state = captured['body']['state']
        self.assertTrue(state.startswith('[질문]\n통금 몇 시야?'))
        self.assertIn(f'[1] {hits[0].chunk.title}', state)
        self.assertTrue(state.endswith('[답]\n23:00까지입니다 [1].'))

    def test_thresholds(self):
        from knowledge.verify import decide
        self.assertTrue(decide({'answers': 0.5, 'contradicts': 0.79}).passed)
        self.assertEqual(decide({'answers': 0.49, 'contradicts': 0.0}).reason, '질문에 답하지 않음')
        self.assertEqual(decide({'answers': 1.0, 'contradicts': 0.8}).reason, '근거와 어긋남')

    def test_jev_failure_shows_the_answer_unverified_by_jev(self):
        from knowledge.verify import JevVerifier
        _, patch = self.jev_call({}, raise_error=urllib.error.URLError('down'))
        with patch, self.assertLogs('knowledge.verify', level='WARNING'):
            verdict = JevVerifier('k').verify('q', self.hits(), 'a')
        self.assertTrue(verdict.passed)
        self.assertFalse(verdict.checked)

    def test_verifier_choice_from_settings(self):
        from django.test import override_settings
        from knowledge.verify import JevVerifier, NoVerifier, get_verifier
        with override_settings(KNOWLEDGE_VERIFIER={'BACKEND': 'jev', 'API_KEY': ''}):
            self.assertIsInstance(get_verifier(), NoVerifier)
        with override_settings(KNOWLEDGE_VERIFIER={'BACKEND': 'jev', 'API_KEY': 'k'}):
            self.assertIsInstance(get_verifier(), JevVerifier)
        with override_settings(KNOWLEDGE_VERIFIER={}):
            self.assertIsInstance(get_verifier(), NoVerifier)

    def test_rejected_answer_is_hidden_with_related_links(self):
        from knowledge.chat import UNVERIFIED_MESSAGE, answer_question
        from knowledge.verify import FakeVerifier
        reply = answer_question('생활관 출입시간 알려주세요', llm=RecordingLLM(reply='도서관은 23:00까지 엽니다 [1]. [검증 실패]'),
                                embedder=self.embedder, min_similarity=0.0, verifier=FakeVerifier())
        self.assertEqual((reply.status, reply.text), ('unverified', UNVERIFIED_MESSAGE))
        self.assertEqual(reply.verdict.reason, '질문에 답하지 않음')
        self.assertTrue(reply.sources)
        passed = answer_question('생활관 출입시간 알려주세요', llm=RecordingLLM(), embedder=self.embedder,
                                 min_similarity=0.0, verifier=FakeVerifier())
        self.assertEqual(passed.status, 'answered')

    def test_rewritten_answers_are_verified_against_the_original_question(self):
        from knowledge.conversation import reply_to
        from knowledge.router import FakeRouter

        class Recording:
            def __init__(self):
                self.questions = []

            def verify(self, question, hits, answer):
                from knowledge.verify import Verdict
                self.questions.append(question)
                return Verdict('[검증 실패]' not in answer)

        verifier = Recording()
        kwargs = {'router': FakeRouter(), 'embedder': self.embedder, 'min_similarity': 0.0, 'verifier': verifier}
        _, conversation_id = reply_to('생활관 출입시간 알려주세요', 1, llm=RecordingLLM(), **kwargs)
        summary, _ = reply_to('요약해줘', 1, conversation_id, llm=RecordingLLM(reply='23:00까지 [1]. [검증 실패]'), **kwargs)
        self.assertEqual(summary.status, 'unverified')
        self.assertEqual(verifier.questions, ['생활관 출입시간 알려주세요', '생활관 출입시간 알려주세요'])

    def test_verification_is_logged(self):
        from knowledge.chat import answer_question
        from knowledge.chat_log import record_chat
        from knowledge.verify import FakeVerifier
        reply = answer_question('생활관 출입시간 알려주세요', llm=RecordingLLM(reply='23:00 [1]. [검증 실패]'),
                                embedder=self.embedder, min_similarity=0.0, verifier=FakeVerifier())
        log, _ = record_chat(reply, 'web')
        self.assertEqual(log.verification['passed'], False)
        self.assertEqual(log.verification['reason'], '질문에 답하지 않음')
