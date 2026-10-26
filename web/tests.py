from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from dorm.models import Comment, Like, OutingApply, Post


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


class GetRequestsDoNotChangeStateTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(self.staff)
        self.outing = OutingApply.objects.create(name='홍길동', student_number='20250001', out_date=date.today())
        self.post = Post.objects.create(author=self.staff, title='t', content='c')
        self.comment = Comment.objects.create(post=self.post, author=self.staff, content='c')

    def test_approve_outing_rejects_get(self):
        self.client.get(reverse('web:approve_outing', args=[self.outing.pk]))
        self.outing.refresh_from_db()
        self.assertEqual(self.outing.status, 'pending')

    def test_reject_outing_rejects_get(self):
        self.client.get(reverse('web:reject_outing', args=[self.outing.pk]))
        self.outing.refresh_from_db()
        self.assertEqual(self.outing.status, 'pending')

    def test_approve_outing_works_with_post(self):
        self.client.post(reverse('web:approve_outing', args=[self.outing.pk]))
        self.outing.refresh_from_db()
        self.assertEqual(self.outing.status, 'approved')

    def test_delete_comment_rejects_get(self):
        self.client.get(reverse('web:delete_comment', args=[self.comment.pk]))
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_delete_comment_works_with_post(self):
        self.client.post(reverse('web:delete_comment', args=[self.comment.pk]))
        self.assertFalse(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_toggle_like_rejects_get(self):
        self.client.get(reverse('web:toggle_like', args=[self.post.pk]))
        self.assertFalse(Like.objects.exists())

    def test_toggle_like_works_with_post(self):
        self.client.post(reverse('web:toggle_like', args=[self.post.pk]))
        self.assertTrue(Like.objects.filter(user=self.staff, post=self.post).exists())


class LoginRedirectTests(TestCase):
    def test_anonymous_mypage_redirects_to_login(self):
        response = self.client.get(reverse('web:mypage'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('web:login')))

    def test_login_required_pages_redirect_to_web_login(self):
        response = self.client.get(reverse('web:check_in'))
        self.assertTrue(response.url.startswith(reverse('web:login')))
