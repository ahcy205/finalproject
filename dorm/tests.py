import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings

from dorm.models import Dorm, Inquiry, Notice, OutingApply


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
