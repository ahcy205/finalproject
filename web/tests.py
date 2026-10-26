from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class RewardPenaltyTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.url = reverse('web:reward_penalty')
        self.data = {'student_number': '20250001', 'points': '5', 'point_type': 'reward'}

    def reward(self):
        self.student.userprofile.refresh_from_db()
        return self.student.userprofile.reward_point

    def test_anonymous_cannot_give_points(self):
        self.client.post(self.url, self.data)
        self.assertEqual(self.reward(), 0)

    def test_student_cannot_give_points(self):
        self.client.force_login(self.student)
        self.client.post(self.url, self.data)
        self.assertEqual(self.reward(), 0)

    def test_staff_can_give_points(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, self.data)
        self.assertEqual(self.reward(), 5)

    def test_non_numeric_points_does_not_crash(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, {**self.data, 'points': 'abc'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.reward(), 0)

