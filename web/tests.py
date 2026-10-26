from datetime import date
import io
import os
import subprocess
import sys
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from django.urls import reverse
from django.utils import timezone

from dorm.models import Comment, Dorm, Inquiry, Like, Notice, OutingApply, Post


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


class OutingIdentityTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()
        self.client.force_login(self.student)
        self.mine = {'name': '홍길동', 'student_number': '20250001', 'out_date': '2026-11-01'}
        self.other = {'name': '김철수', 'student_number': '20259999', 'out_date': '2026-11-01'}

    def test_apply_outing_saves_own_application(self):
        response = self.client.post(reverse('web:apply_outing'), self.mine)
        self.assertRedirects(response, reverse('web:apply_success'))
        self.assertTrue(OutingApply.objects.filter(student_number='20250001').exists())

    def test_apply_outing_rejects_other_student(self):
        self.client.post(reverse('web:apply_outing'), self.other)
        self.assertFalse(OutingApply.objects.exists())

    def test_outside_post_rejects_other_student(self):
        self.client.post(reverse('web:outside'), self.other)
        self.assertFalse(OutingApply.objects.exists())

    def test_outside_post_saves_own_application(self):
        self.client.post(reverse('web:outside'), self.mine)
        self.assertTrue(OutingApply.objects.filter(student_number='20250001').exists())

    def test_missing_date_does_not_crash(self):
        response = self.client.post(reverse('web:apply_outing'), {**self.mine, 'out_date': ''})
        self.assertRedirects(response, reverse('web:outside'))
        self.assertFalse(OutingApply.objects.exists())


class AdminStudentSearchTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.department = '컴퓨터공학과'
        self.student.userprofile.save()
        self.client.force_login(self.staff)

    def search(self, field, query):
        return self.client.get(reverse('web:mypage'), {'field': field, 'query': query})

    def test_search_by_name_and_department(self):
        self.assertEqual(list(self.search('full_name', '길동').context['students']), [self.student.userprofile])
        self.assertEqual(list(self.search('department', '컴퓨터').context['students']), [self.student.userprofile])

    def test_password_field_cannot_be_searched(self):
        response = self.search('user__password', 'pbkdf2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['students']), 0)

    def test_unknown_field_does_not_crash(self):
        response = self.search('nope', 'x')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['students']), 0)


class CheckInDuplicateTests(TestCase):
    def setUp(self):
        first = User.objects.create_user('20250001', password='pw12345!')
        Dorm.objects.create(user=first, name='홍길동', student_number='20250001', gender='male')
        self.student = User.objects.create_user('20250002', password='pw12345!')
        self.client.force_login(self.student)

    def test_duplicate_student_number_shows_error(self):
        response = self.client.post(reverse('web:check_in'),
                                    {'name': '김철수', 'student_number': '20250001', 'gender': 'male'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '이미 등록된 학번입니다.')
        self.assertFalse(Dorm.objects.filter(user=self.student).exists())


class AssignRoomTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(self.staff)
        self.dorm = Dorm.objects.create(name='홍길동', student_number='20250001', gender='male',
                                        building_name='A동', r_number=101, position=1)
        self.url = reverse('web:assign_room', args=[self.dorm.pk])

    def assign(self, **data):
        base = {'building_name': '', 'r_number': '', 'position': ''}
        return self.client.post(self.url, {**base, **data}, follow=True)

    def test_blank_fields_keep_existing_values(self):
        response = self.assign(building_name='B동')
        self.assertEqual(response.status_code, 200)
        self.dorm.refresh_from_db()
        self.assertEqual((self.dorm.building_name, self.dorm.r_number, self.dorm.position), ('B동', 101, 1))

    def test_full_assignment(self):
        self.assign(building_name='C동', r_number='305', position='3')
        self.dorm.refresh_from_db()
        self.assertEqual((self.dorm.building_name, self.dorm.r_number, self.dorm.position), ('C동', 305, 3))

    def test_invalid_numbers_are_rejected(self):
        response = self.assign(r_number='abc', position='7')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '방 번호는 숫자로 입력해주세요.')
        self.dorm.refresh_from_db()
        self.assertEqual((self.dorm.r_number, self.dorm.position), (101, 1))

    def test_position_out_of_range_is_rejected(self):
        response = self.assign(position='7')
        self.assertContains(response, '침대 위치는 1~4 중에서 입력해주세요.')
        self.dorm.refresh_from_db()
        self.assertEqual(self.dorm.position, 1)

    def test_all_blank_shows_message(self):
        response = self.assign()
        self.assertContains(response, '배정할 값을 입력해주세요.')


class PageTitleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('20250001', password='pw12345!', is_staff=True)
        self.client.force_login(self.user)
        self.post = Post.objects.create(author=self.user, title='t', content='c')
        self.notice = Notice.objects.create(title='t', content='c')

    def test_post_pages_are_not_titled_as_notices(self):
        delete_page = self.client.get(reverse('web:community_delete', args=[self.post.pk]))
        self.assertContains(delete_page, '<title>게시글 삭제 확인</title>')
        self.assertNotContains(delete_page, '공지사항')
        self.assertContains(delete_page, timezone.localtime(self.post.created_at).strftime('%Y-%m-%d'))
        self.assertContains(self.client.get(reverse('web:community_update', args=[self.post.pk])),
                            '<title>게시글 수정</title>')

    def test_notice_update_title(self):
        self.assertContains(self.client.get(reverse('web:notice_update', args=[self.notice.pk])),
                            '<title>공지사항 수정</title>')


class SecretKeySettingsTests(TestCase):
    """SECRET_KEY는 코드가 아니라 환경변수에서 읽는다."""

    def read_secret_key(self, **env):
        code = 'import django; django.setup(); from django.conf import settings; print(settings.SECRET_KEY)'
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'finalproject.settings', **env})
        return result.stdout.strip().splitlines()[-1]

    def test_secret_key_comes_from_environment(self):
        self.assertEqual(self.read_secret_key(DJANGO_SECRET_KEY='from-env-1234'), 'from-env-1234')

    def test_leaked_key_is_not_in_settings(self):
        settings_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'finalproject', 'settings.py')
        with open(settings_file, encoding='utf-8') as f:
            self.assertNotIn('98z%w$o&kv', f.read())


class SharedNavTests(TestCase):
    """상단 메뉴는 templates/web/_nav.html 한 곳에만 있다."""

    def test_nav_markup_lives_only_in_partial(self):
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'web')
        holders = []
        for name in os.listdir(template_dir):
            with open(os.path.join(template_dir, name), encoding='utf-8') as f:
                if '<nav class="fh5co-nav"' in f.read():
                    holders.append(name)
        self.assertEqual(holders, ['_nav.html'])

    def test_pages_render_one_nav_with_active_menu(self):
        guide = self.client.get(reverse('web:guide'))
        self.assertContains(guide, '<nav class="fh5co-nav"', count=1)
        self.assertContains(guide, 'class="has-dropdown active"', count=1)
        self.assertNotContains(self.client.get(reverse('web:bus')), 'has-dropdown active')

    def test_home_keeps_admin_menu_for_staff(self):
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse('web:home')), '입실 신청 관리')
