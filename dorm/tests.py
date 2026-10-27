import io
import os
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings

from dorm.models import Comment, Dorm, Inquiry, Notice, OutingApply, Post


def token_client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Token ' + Token.objects.create(user=user).key)
    return client


class InquiryDetailApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('20250001', password='pw12345!')
        self.other = User.objects.create_user('20250002', password='pw12345!')
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.inquiry = Inquiry.objects.create(user=self.owner, title='문의', content='개인 내용')
        self.url = f'/api/inquiries/{self.inquiry.pk}/'

    def test_anonymous_cannot_read(self):
        response = APIClient().get(self.url)
        self.assertIn(response.status_code, (401, 403))
        self.assertNotIn('개인 내용', response.content.decode())

    def test_other_student_cannot_read(self):
        response = token_client(self.other).get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_owner_can_read(self):
        response = token_client(self.owner).get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['inquiry']['content'], '개인 내용')

    def test_staff_can_read_and_answer(self):
        client = token_client(self.staff)
        self.assertEqual(client.get(self.url).status_code, 200)
        response = client.post(self.url, {'answer': '답변입니다'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.inquiry.inquiryanswer.answer, '답변입니다')

    def test_owner_cannot_answer(self):
        response = token_client(self.owner).post(self.url, {'answer': '셀프 답변'}, format='json')
        self.assertEqual(response.status_code, 403)


class OutingApplyApiTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()
        self.client = token_client(self.student)

    def test_own_application_is_saved(self):
        response = self.client.post('/api/outing_apply/',
                                    {'name': '홍길동', 'student_number': '20250001', 'out_date': '2026-11-01'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(OutingApply.objects.filter(student_number='20250001').exists())

    def test_other_student_is_rejected(self):
        response = self.client.post('/api/outing_apply/',
                                    {'name': '김철수', 'student_number': '20259999', 'out_date': '2026-11-01'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(OutingApply.objects.exists())


class InputValidationApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()

    def test_give_point_rejects_non_numeric_point(self):
        response = token_client(self.staff).post(
            '/api/give_point/', {'student_id': '20250001', 'point_type': 'reward', 'point': 'abc'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_dorm_apply_rejects_duplicate_student_number(self):
        Dorm.objects.create(name='다른 학생', student_number='20250001', gender='male')
        response = token_client(self.student).post(
            '/api/dorm_apply/', {'name': '홍길동', 'student_number': '20250001', 'gender': 'male'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Dorm.objects.filter(user=self.student).exists())

    def test_outing_apply_rejects_bad_date(self):
        response = token_client(self.student).post(
            '/api/outing_apply/', {'name': '홍길동', 'student_number': '20250001', 'out_date': '11월 1일'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(OutingApply.objects.exists())


class OutingStatusApiTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()
        self.outing = OutingApply.objects.create(user=self.student, name='홍길동', student_number='20250001',
                                                 out_date='2026-11-01', status='approved')

    def test_status_list_includes_approval_state(self):
        response = token_client(self.student).get('/api/sleepover/status/')
        self.assertEqual(response.json()['list'][0]['status'], 'approved')

    def test_new_application_reports_pending(self):
        response = token_client(self.student).post(
            '/api/outing_apply/', {'name': '홍길동', 'student_number': '20250001', 'out_date': '2026-11-02'},
            format='json')
        self.assertEqual(response.json()['outing']['status'], 'pending')


TEMP_MEDIA = tempfile.mkdtemp()


def png_file():
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(buf, 'PNG')
    return SimpleUploadedFile('notice.png', buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class NoticeImageApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)

    def test_list_includes_image_url(self):
        Notice.objects.create(title='이미지 없음', content='c')
        response = APIClient().get('/api/notices/')
        self.assertIsNone(response.json()['notices'][0]['image'])

    def test_staff_can_post_notice_with_image(self):
        response = token_client(self.staff).post(
            '/api/notices/', {'title': '공지', 'content': '내용', 'image': png_file()}, format='multipart')
        self.assertEqual(response.status_code, 200)
        image_url = response.json()['notice']['image']
        self.assertTrue(image_url.startswith('http://testserver/media/notices/'))
        self.assertTrue(image_url.endswith('.png'))

    def test_non_image_file_is_rejected(self):
        html = SimpleUploadedFile('x.html', b'<script>alert(1)</script>', content_type='text/html')
        response = token_client(self.staff).post(
            '/api/notices/', {'title': '공지', 'content': '내용', 'image': html}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Notice.objects.exists())


class OutingUserLinkApiTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()

    def test_application_is_linked_to_account(self):
        token_client(self.student).post(
            '/api/outing_apply/', {'name': '홍길동', 'student_number': '20250001', 'out_date': '2026-11-02'},
            format='json')
        self.assertEqual(OutingApply.objects.get().user, self.student)

    def test_status_list_follows_account_not_typed_name(self):
        OutingApply.objects.create(user=self.student, name='예전 이름', student_number='20250001', out_date='2026-11-01')
        OutingApply.objects.create(name='남의 신청', student_number='20250001', out_date='2026-11-03')
        listed = token_client(self.student).get('/api/sleepover/status/').json()['list']
        self.assertEqual([o['name'] for o in listed], ['예전 이름'])


class OutingUserMigrationTests(TransactionTestCase):
    """0005 마이그레이션이 기존 신청을 학번이 같은 계정에 연결한다."""

    def test_existing_outings_are_linked_by_student_number(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('dorm', '0004_notice_image_userprofile_phone_number')])
        old_apps = executor.loader.project_state([('dorm', '0004_notice_image_userprofile_phone_number')]).apps
        User = old_apps.get_model('auth', 'User')
        Outing = old_apps.get_model('dorm', 'OutingApply')
        student = User.objects.create(username='20250001')
        Outing.objects.create(name='홍길동', student_number='20250001', out_date='2026-11-01')
        Outing.objects.create(name='모름', student_number='99999999', out_date='2026-11-01')

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([('dorm', '0005_outingapply_user')])
        new_apps = executor.loader.project_state([('dorm', '0005_outingapply_user')]).apps
        Outing = new_apps.get_model('dorm', 'OutingApply')
        self.assertEqual(Outing.objects.get(student_number='20250001').user_id, student.pk)
        self.assertIsNone(Outing.objects.get(student_number='99999999').user_id)


class DormApplyLengthApiTests(TestCase):
    def test_long_student_number_is_rejected(self):
        student = User.objects.create_user('20250001', password='pw12345!')
        response = token_client(student).post(
            '/api/dorm_apply/', {'name': '홍길동', 'student_number': '12345678901', 'gender': 'male'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Dorm.objects.exists())


class SignupApiPasswordTests(TestCase):
    def signup(self, password):
        return APIClient().post('/api/signup/', {'username': '20250001', 'password': password,
                                                 'email': 's@example.com', 'full_name': '홍길동'}, format='json')

    def test_weak_password_is_rejected(self):
        for weak in ('1234', 'password', '20250001a'):
            response = self.signup(weak)
            self.assertEqual(response.status_code, 400, weak)
        self.assertFalse(User.objects.filter(username='20250001').exists())

    def test_strong_password_is_accepted(self):
        response = self.signup('dorm-Life-2026!')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.get(username='20250001').check_password('dorm-Life-2026!'))


class PostApiQueryCountTests(TestCase):
    """글이 늘어도 게시글 API의 쿼리 수는 늘지 않아야 한다 (N+1 방지)."""

    def setUp(self):
        self.users = [User.objects.create_user(f'2025000{i}', password='pw12345!') for i in range(3)]

    def add_posts(self, n):
        for i in range(n):
            post = Post.objects.create(author=self.users[i % 3], title=f'글 {i}', content='내용')
            for user in self.users:
                Comment.objects.create(post=post, author=user, content='댓글')

    def count_queries(self, url):
        with CaptureQueriesContext(connection) as ctx:
            response = APIClient().get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_post_list_query_count_is_constant(self):
        self.add_posts(5)
        few = self.count_queries('/api/posts/')
        self.add_posts(15)
        self.assertEqual(self.count_queries('/api/posts/'), few)
        self.assertLessEqual(few, 5)

    def test_post_detail_query_count_is_constant(self):
        self.add_posts(1)
        post = Post.objects.get()
        few = self.count_queries(f'/api/posts/{post.pk}/')
        for i in range(10):
            Comment.objects.create(post=post, author=self.users[i % 3], content='추가 댓글')
        self.assertEqual(self.count_queries(f'/api/posts/{post.pk}/'), few)


class PostApiPaginationTests(TestCase):
    """?page= 를 주면 20개씩, 주지 않으면 기존처럼 전체를 돌려준다 (기존 앱 호환)."""

    def setUp(self):
        author = User.objects.create_user('20250001', password='pw12345!')
        for i in range(45):
            Post.objects.create(author=author, title=f'글 {i}', content='내용')

    def get(self, query=''):
        return APIClient().get('/api/posts/' + query)

    def test_without_page_returns_everything_as_before(self):
        body = self.get().json()
        self.assertEqual(len(body['posts']), 45)
        self.assertNotIn('page', body)

    def test_pages_of_twenty(self):
        first = self.get('?page=1').json()
        self.assertEqual((len(first['posts']), first['page'], first['total_pages'], first['has_next']), (20, 1, 3, True))
        last = self.get('?page=3').json()
        self.assertEqual((len(last['posts']), last['has_next']), (5, False))
        self.assertEqual(first['posts'][0]['title'], '글 44')  # 최신 글부터

    def test_page_past_the_end_is_empty(self):
        body = self.get('?page=999').json()
        self.assertEqual((body['posts'], body['has_next']), ([], False))

    def test_invalid_page_is_rejected(self):
        for bad in ('abc', '0', '-1'):
            self.assertEqual(self.get(f'?page={bad}').status_code, 400, bad)


class LogoutApiTests(TestCase):
    def setUp(self):
        User.objects.create_user('20250001', password='dorm-Life-2026!')

    def login(self):
        response = APIClient().post('/api/login/', {'username': '20250001', 'password': 'dorm-Life-2026!'},
                                    format='json')
        return response.json()['token']

    def client_with(self, token):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        return client

    def test_logout_revokes_the_token(self):
        token = self.login()
        self.assertEqual(self.client_with(token).get('/api/mypage/').status_code, 200)
        response = self.client_with(token).post('/api/logout/')
        self.assertEqual((response.status_code, response.json()['success']), (200, True))
        self.assertEqual(self.client_with(token).get('/api/mypage/').status_code, 401)

    def test_login_again_issues_a_new_token(self):
        old = self.login()
        self.client_with(old).post('/api/logout/')
        new = self.login()
        self.assertNotEqual(new, old)
        self.assertEqual(self.client_with(new).get('/api/mypage/').status_code, 200)

    def test_logout_requires_a_token(self):
        self.assertEqual(APIClient().post('/api/logout/').status_code, 401)


class ApiDocsTests(TestCase):
    """API 문서(/api/docs/)와 OpenAPI 스키마(/api/schema/)."""

    def test_schema_lists_every_api_endpoint(self):
        response = APIClient().get('/api/schema/', {'format': 'json'})
        self.assertEqual(response.status_code, 200)
        paths = set(response.json()['paths'])
        expected = {'/api/signup/', '/api/login/', '/api/logout/', '/api/mypage/', '/api/give_point/',
                    '/api/dorm_apply/', '/api/dorm-applications/', '/api/dorm-applications/{id}/',
                    '/api/outing_apply/', '/api/sleepover/status/', '/api/sleepover/approve/{id}/',
                    '/api/sleepover/reject/{id}/', '/api/notices/', '/api/posts/', '/api/posts/{id}/',
                    '/api/posts/{id}/like/', '/api/posts/{post_id}/comments/', '/api/inquiries/',
                    '/api/inquiries/{id}/', '/api/chatbot/',
                    '/api/chatbot/feedback/'}
        self.assertEqual(paths, expected)

    def test_login_is_documented_with_its_token_response(self):
        schema = APIClient().get('/api/schema/', {'format': 'json'}).json()
        login = schema['paths']['/api/login/']['post']
        self.assertEqual(login['summary'], '로그인 (Token 발급)')
        self.assertIn('token', schema['components']['schemas']['LoginResponse']['properties'])

    def test_swagger_page_loads(self):
        response = self.client.get('/api/docs/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'swagger')


class DatabaseCheckTests(TestCase):
    """DB에 접속할 수 없으면 원인과 해결 방법을 알려 준다 (SQLite로 대신 실행하지 않음)."""

    def test_unreachable_database_reports_how_to_start_it(self):
        from unittest import mock
        from django.db import OperationalError
        from dorm.checks import check_database_connection
        with mock.patch('django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection',
                        side_effect=OperationalError('connection refused')):
            errors = check_database_connection(app_configs=None)
        self.assertEqual([e.id for e in errors], ['dorm.E001'])
        self.assertIn('docker compose up -d db', errors[0].hint)

    def test_reachable_database_has_no_errors(self):
        from dorm.checks import check_database_connection
        self.assertEqual(check_database_connection(app_configs=None), [])


class UserProfileSignalTests(TestCase):
    """회원가입 때는 프로필을 자동으로 만들고, 백업 데이터(loaddata)를 불러올 때는 만들지 않는다."""

    def test_profile_is_created_for_new_user(self):
        from dorm.models import UserProfile
        user = User.objects.create_user('20250001', password='pw12345!')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_loading_a_fixture_keeps_the_saved_profile(self):
        import json
        import tempfile as tf
        from django.core.management import call_command
        from dorm.models import UserProfile
        fixture = [
            {'model': 'auth.user', 'pk': 900, 'fields': {'username': 'fixture_user', 'password': '!'}},
            {'model': 'dorm.userprofile', 'pk': 900, 'fields': {'user': 900, 'full_name': '백업 이름',
                                                                 'department': '', 'phone_number': '',
                                                                 'reward_point': 3, 'penalty_point': 1}},
        ]
        with tf.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(fixture, f, ensure_ascii=False)
        try:
            call_command('loaddata', f.name, verbosity=0)
        finally:
            os.remove(f.name)
        profile = UserProfile.objects.get(user_id=900)
        self.assertEqual((profile.full_name, profile.reward_point), ('백업 이름', 3))


class StableOrderingTests(TestCase):
    """PostgreSQL은 정렬을 지정하지 않으면 순서를 보장하지 않으므로, 목록 순서를 명시적으로 고정한다."""

    def test_post_comments_come_in_id_order_even_with_equal_times(self):
        author = User.objects.create_user('20250001', password='pw12345!')
        post = Post.objects.create(author=author, title='t', content='c')
        ids = [Comment.objects.create(post=post, author=author, content=str(i)).pk for i in range(5)]
        Comment.objects.update(created_at=Comment.objects.first().created_at)  # 작성 시각이 모두 같은 경우
        for url in (f'/api/posts/{post.pk}/', '/api/posts/'):
            body = APIClient().get(url).json()
            comments = body['post']['comments'] if 'post' in body else body['posts'][0]['comments']
            self.assertEqual([c['id'] for c in comments], ids, url)
        listed = APIClient().get(f'/api/posts/{post.pk}/comments/').json()['comments']
        self.assertEqual([c['id'] for c in listed], ids)


@override_settings(KNOWLEDGE_LLM={'BACKEND': 'fake'}, KNOWLEDGE_EMBEDDING={'BACKEND': 'fake'})
class ChatbotApiTests(TestCase):
    """앱용 챗봇 API: 웹 챗봇과 같은 답을 JSON으로 준다 (ADR 0011)."""

    @classmethod
    def setUpTestData(cls):
        from knowledge.chunking import build_chunks
        from knowledge.embeddings import FakeEmbedder
        from knowledge.indexing import embed_pending, sync_chunks
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(FakeEmbedder())
        cls.student = User.objects.create_user('20250001', password='pw12345!')

    def setUp(self):
        from unittest import mock
        from django.core.cache import cache
        cache.clear()
        patcher = mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = token_client(self.student)

    def test_answer_with_sources(self):
        response = self.client.post('/api/chatbot/', {'question': '생활관 출입시간 알려주세요'}, format='json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'answered')
        self.assertIn('[1]', data['text'])
        self.assertEqual(set(data['sources'][0]), {'number', 'title', 'url'})

    def test_needs_a_token(self):
        self.assertEqual(APIClient().post('/api/chatbot/', {'question': '출입시간'}, format='json').status_code, 401)

    def test_bad_questions_are_rejected(self):
        for question in ('', '가' * 501):
            response = self.client.post('/api/chatbot/', {'question': question}, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json()['success'])

    def test_rate_limit_is_shared_with_the_web_page(self):
        from knowledge.chat import RATE_LIMIT, allow_request
        for _ in range(RATE_LIMIT):
            allow_request(self.student.pk)
        response = self.client.post('/api/chatbot/', {'question': '출입시간'}, format='json')
        self.assertEqual(response.status_code, 429)
        self.assertFalse(response.json()['success'])

    def test_only_post_is_allowed(self):
        self.assertEqual(self.client.get('/api/chatbot/').status_code, 405)


@override_settings(KNOWLEDGE_LLM={'BACKEND': 'fake'}, KNOWLEDGE_EMBEDDING={'BACKEND': 'fake'})
class ChatbotFeedbackApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from knowledge.chunking import build_chunks
        from knowledge.embeddings import FakeEmbedder
        from knowledge.indexing import embed_pending, sync_chunks
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(FakeEmbedder())
        cls.student = User.objects.create_user('20250001', password='pw12345!')

    def setUp(self):
        from unittest import mock
        from django.core.cache import cache
        cache.clear()
        patcher = mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = token_client(self.student)

    def test_api_answer_can_be_rated(self):
        from knowledge.models import ChatLog
        data = self.client.post('/api/chatbot/', {'question': '생활관 출입시간 알려주세요'}, format='json').json()
        self.assertEqual(ChatLog.objects.get(pk=data['log_id']).channel, 'api')
        body = {'log_id': data['log_id'], 'token': data['feedback_token'], 'rating': 'down', 'reason': 'irrelevant'}
        response = self.client.post('/api/chatbot/feedback/', body, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        body['rating'] = 'up'
        self.assertEqual(self.client.post('/api/chatbot/feedback/', body, format='json').status_code, 409)

    def test_bad_feedback_is_rejected(self):
        response = self.client.post('/api/chatbot/feedback/', {'log_id': 1, 'token': 'x', 'rating': 'meh'},
                                    format='json')
        self.assertEqual(response.status_code, 400)
