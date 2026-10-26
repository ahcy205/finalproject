import io
import math

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
    def setUp(self):
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
