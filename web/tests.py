from datetime import date
import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from django.urls import reverse

from dorm.models import Comment, Inquiry, Like, Notice, OutingApply, Post


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

    def test_success_message_is_shown_on_reward_page(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, self.data, follow=True)
        self.assertContains(response, '20250001 학생에게 5점 부여 완료!')

    def test_error_message_is_shown_on_reward_page(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, {**self.data, 'points': 'abc'}, follow=True)
        self.assertContains(response, '점수는 숫자로 입력해주세요.')

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


class MypageInquiryTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.client.force_login(self.student)
        self.url = reverse('web:mypage')

    def test_student_can_submit_inquiry(self):
        response = self.client.post(self.url, {'title': '문의', 'content': '내용', 'submit_inquiry': ''})
        self.assertRedirects(response, self.url + '?tab=inquiry')
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.user, self.student)
        self.assertEqual(inquiry.title, '문의')

    def test_invalid_inquiry_is_not_saved(self):
        response = self.client.post(self.url, {'title': '', 'content': '', 'submit_inquiry': ''})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(Inquiry.objects.exists())


class LoginNextTests(TestCase):
    def setUp(self):
        User.objects.create_user('20250001', password='pw12345!')
        self.url = reverse('web:login')

    def login(self, next_url):
        return self.client.post(self.url, {'username': '20250001', 'password': 'pw12345!', 'next': next_url})

    def test_login_page_keeps_next_in_form(self):
        response = self.client.get(self.url, {'next': '/mypage/'})
        self.assertContains(response, 'name="next" value="/mypage/"')

    def test_login_redirects_to_next(self):
        self.assertRedirects(self.login('/mypage/'), '/mypage/')

    def test_login_ignores_external_next(self):
        response = self.login('https://evil.example.com/')
        self.assertRedirects(response, reverse('web:home'))

    def test_login_without_next_goes_home(self):
        self.assertRedirects(self.login(''), reverse('web:home'))

    def test_failed_login_keeps_next(self):
        response = self.client.post(self.url, {'username': '20250001', 'password': 'wrong', 'next': '/mypage/'})
        self.assertContains(response, 'name="next" value="/mypage/"')


TEMP_MEDIA = tempfile.mkdtemp()


def png_file(name='notice.png'):
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def html_file():
    return SimpleUploadedFile('x.html', b'<script>alert(1)</script>', content_type='text/html')


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class NoticeImageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(self.staff)
        self.notice = Notice.objects.create(title='원래 제목', content='원래 내용')
        self.url = reverse('web:notice_update', args=[self.notice.pk])

    def test_update_rejects_non_image_file(self):
        response = self.client.post(self.url, {'title': '새 제목', 'content': '새 내용', 'image': html_file()})
        self.assertEqual(response.status_code, 200)
        self.notice.refresh_from_db()
        self.assertFalse(self.notice.image)
        self.assertEqual(self.notice.title, '원래 제목')

    def test_update_accepts_image(self):
        response = self.client.post(self.url, {'title': '새 제목', 'content': '새 내용', 'image': png_file()})
        self.assertRedirects(response, reverse('web:notice_detail', args=[self.notice.pk]))
        self.notice.refresh_from_db()
        self.assertTrue(self.notice.image.name.endswith('.png'))
        self.assertEqual(self.notice.title, '새 제목')

    def test_update_without_new_image_keeps_old_image(self):
        self.client.post(self.url, {'title': 't', 'content': 'c', 'image': png_file()})
        self.notice.refresh_from_db()
        old = self.notice.image.name
        self.client.post(self.url, {'title': '다시', 'content': 'c'})
        self.notice.refresh_from_db()
        self.assertEqual(self.notice.image.name, old)
        self.assertEqual(self.notice.title, '다시')

    def test_update_requires_title_and_content(self):
        response = self.client.post(self.url, {'title': '', 'content': ''})
        self.assertContains(response, '제목과 내용을 모두 입력해주세요.')

    def test_create_rejects_non_image_file(self):
        self.client.post(reverse('web:notice_create'), {'title': 't', 'content': 'c', 'image': html_file()})
        self.assertFalse(Notice.objects.filter(title='t').exists())
