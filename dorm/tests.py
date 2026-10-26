from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from django.test import TestCase

from dorm.models import Dorm, Inquiry, OutingApply


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
