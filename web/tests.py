from datetime import date
import io
import re
import os
import subprocess
import sys
import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from django.urls import reverse
from django.utils import timezone
from django.db import connection
from django.test.utils import CaptureQueriesContext

from dorm.models import Comment, Dorm, Inquiry, InquiryAnswer, Like, Notice, OutingApply, Post
from knowledge.chunking import build_chunks
from knowledge.embeddings import FakeEmbedder
from knowledge.indexing import embed_pending, sync_chunks


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


class AuthPageTests(TestCase):
    """로그인·회원가입 화면: 라벨·자동 완성·필드 오류 표시 (docs/adr/0020, 8단계)."""

    def signup_data(self, **changes):
        data = {'full_name': '홍길동', 'username': '20250009', 'department': '컴퓨터공학과',
                'password1': 'dorm-Life-2026!', 'password2': 'dorm-Life-2026!',
                'phone_number': '010-1234-5678', 'email': 'hong@example.com'}
        data.update(changes)
        return data

    def assert_label_for(self, html, field_id):
        self.assertIn(f'for="{field_id}"', html)
        self.assertIn(f'id="{field_id}"', html)

    def test_login_labels_and_autocomplete(self):
        html = self.client.get(reverse('web:login')).content.decode()
        for field_id in ('username', 'password'):
            self.assert_label_for(html, field_id)
        self.assertIn('autocomplete="username"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn(f'href="{reverse("web:signup")}"', html)

    def test_failed_login_keeps_username_and_marks_fields(self):
        User.objects.create_user('20250001', password='pw12345!')
        response = self.client.post(reverse('web:login'), {'username': '20250001', 'password': 'wrong'})
        self.assertContains(response, 'value="20250001"')
        self.assertContains(response, 'aria-invalid="true"', count=2)
        self.assertContains(response, 'class="dg-toast dg-toast--error')

    def test_signup_labels_and_autocomplete(self):
        html = self.client.get(reverse('web:signup')).content.decode()
        for field_id in ('full_name', 'username', 'department', 'password1', 'password2', 'phone_number', 'email'):
            self.assert_label_for(html, field_id)
        for value in ('name', 'username', 'new-password', 'tel', 'email'):
            self.assertIn(f'autocomplete="{value}"', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn('8자 이상', html)  # MinimumLengthValidator 기본값
        self.assertIn('010-1234-5678', html)
        self.assertIn(f'href="{reverse("web:login")}"', html)
        self.assertNotIn('aria-invalid', html)

    def test_signup_field_errors_render_next_to_field(self):
        User.objects.create_user('20250009', password='pw12345!')
        response = self.client.post(reverse('web:signup'), self.signup_data(password2='different-2026!'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('aria-invalid="true" aria-describedby="username_help username_err"', html)
        self.assertIn('id="username_err">이미 사용 중인 학번입니다.', html)
        self.assertIn('aria-describedby="password2_err"', html)
        self.assertIn('id="password2_err"', html)
        self.assertNotIn('id="email_err"', html)
        # 입력한 값은 남기고 비밀번호는 다시 쓰게 한다
        self.assertIn('value="홍길동"', html)
        self.assertNotIn('dorm-Life-2026!', html)

    def test_signup_still_creates_account(self):
        response = self.client.post(reverse('web:signup'), self.signup_data())
        self.assertRedirects(response, reverse('web:login'))
        self.assertEqual(User.objects.get(username='20250009').userprofile.full_name, '홍길동')


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
        self.assertContains(delete_page, timezone.localtime(self.post.created_at).strftime('%Y.%m.%d'))
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
                if 'class="dg-nav"' in f.read():
                    holders.append(name)
        self.assertEqual(holders, ['_nav.html'])

    def test_pages_render_one_nav_with_current_section(self):
        """지금 화면이 속한 묶음 하나만 강조하고, 지금 화면 링크에 aria-current를 단다 (docs/adr/0020)."""
        guide = self.client.get(reverse('web:guide'))
        self.assertContains(guide, 'class="dg-nav"', count=1)
        self.assertContains(guide, 'dg-nav__group is-current', count=1)
        bus = self.client.get(reverse('web:bus')).content.decode()
        self.assertEqual(bus.count('is-current'), 1)
        self.assertIn('href="/bus/" aria-current="page"', bus)
        self.assertNotContains(self.client.get(reverse('web:login')), 'is-current')

    def test_pages_that_had_no_menu_now_have_it(self):
        self.assertContains(self.client.get(reverse('web:login')), 'class="dg-nav"', count=1)
        self.assertContains(self.client.get(reverse('web:signup')), 'class="dg-nav"', count=1)
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(staff)
        for name in ('web:mypage', 'web:dorminfo', 'web:outside_manage', 'web:reward_penalty'):
            with self.subTest(name=name):
                self.assertContains(self.client.get(reverse(name)), 'class="dg-nav"', count=1)

    def test_messages_show_as_page_notice_not_browser_alert(self):
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'web')
        for name in os.listdir(template_dir):
            with open(os.path.join(template_dir, name), encoding='utf-8') as f:
                text = f.read()
            self.assertNotIn("alert('{{ message }}')", text, name)
            self.assertNotIn('alert("{{ message }}")', text, name)
        response = self.client.post(reverse('web:login'), {'username': 'nobody', 'password': 'wrong'}, follow=True)
        self.assertContains(response, 'class="dg-toast dg-toast--')

    def test_staff_sees_admin_menu_on_every_page(self):
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(staff)
        for name in ('web:home', 'web:bus', 'web:guide'):
            response = self.client.get(reverse(name))
            self.assertContains(response, '입실 신청 관리')
            self.assertContains(response, '외박 신청 관리')

    def test_superuser_admin_link_uses_this_site(self):
        boss = User.objects.create_superuser('boss', password='pw12345!')
        self.client.force_login(boss)
        response = self.client.get(reverse('web:bus'))
        self.assertContains(response, 'href="/admin/"')
        self.assertNotContains(response, '43.202.118.147')

    def test_student_does_not_see_admin_menu(self):
        self.client.force_login(User.objects.create_user('20250001', password='pw12345!'))
        response = self.client.get(reverse('web:home'))
        self.assertNotContains(response, '입실 신청 관리')
        self.assertNotContains(response, 'href="/admin/"')

    def test_template_placeholders_are_gone(self):
        response = self.client.get(reverse('web:home'))
        self.assertNotContains(response, '+01 123 456 7890')
        self.assertNotContains(response, 'fh5co-social')


class InquiryDetailWebTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('20250001', password='pw12345!')
        self.inquiry = Inquiry.objects.create(user=self.owner, title='문의', content='내용')
        self.url = reverse('web:inquiry_detail', args=[self.inquiry.pk])

    def test_staff_can_view_and_answer(self):
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(self.url), '내용')
        self.client.post(self.url, {'answer': '답변입니다'})
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.inquiryanswer.answer, '답변입니다')
        self.assertEqual(self.inquiry.inquiryanswer.admin, staff)

    def test_other_student_cannot_view_or_answer(self):
        self.client.force_login(User.objects.create_user('20250002', password='pw12345!'))
        self.assertRedirects(self.client.get(self.url), reverse('web:mypage'))
        self.client.post(self.url, {'answer': '셀프 답변'})
        self.assertFalse(InquiryAnswer.objects.exists())

    def test_owner_can_view_but_not_answer(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.post(self.url, {'answer': '셀프 답변'})
        self.assertFalse(InquiryAnswer.objects.exists())


class OutingUserLinkWebTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()
        self.client.force_login(self.student)

    def test_web_application_is_linked_to_account(self):
        self.client.post(reverse('web:apply_outing'),
                         {'name': '홍길동', 'student_number': '20250001', 'out_date': '2026-11-01'})
        self.assertEqual(OutingApply.objects.get().user, self.student)

    def test_outing_list_shows_own_applications_after_name_change(self):
        OutingApply.objects.create(user=self.student, name='홍길동', student_number='20250001', out_date='2026-11-01')
        OutingApply.objects.create(name='홍길동', student_number='20250001', out_date='2026-11-09')
        self.student.userprofile.full_name = '홍길순'
        self.student.userprofile.save()
        apps = self.client.get(reverse('web:outing_info')).context['applications']
        self.assertEqual([str(a.out_date) for a in apps], ['2026-11-01'])


class DormFieldValidationTests(TestCase):
    def test_unassigned_bed_is_a_valid_choice(self):
        dorm = Dorm(name='홍길동', student_number='20250001', gender='male')
        dorm.full_clean()  # position 기본값 0(미배정)도 유효해야 한다
        self.assertEqual(dorm.get_position_display(), '미배정')

    def test_check_in_rejects_long_student_number(self):
        self.client.force_login(User.objects.create_user('20250001', password='pw12345!'))
        response = self.client.post(reverse('web:check_in'),
                                    {'name': '홍길동', 'student_number': '12345678901', 'gender': 'male'})
        self.assertContains(response, '학번은 10자 이하로 입력해주세요.')
        self.assertFalse(Dorm.objects.exists())


class SharedThemeAssetTests(TestCase):
    """예전 테마(_theme_css.html / _theme_js.html)는 더 쓰지 않고, 새 화면은 새 CSS만 불러온다 (docs/adr/0020)."""

    def test_no_template_includes_the_old_theme_partials(self):
        # 챗봇(7단계)을 끝으로 _theme_css.html / _theme_js.html 을 쓰는 화면이 없다.
        from django.conf import settings
        pattern = re.compile(r"{%\s*include\s+['\"]web/_theme_(css|js)\.html")
        users = []
        for root in settings.TEMPLATES[0]['DIRS']:
            for folder, _, files in os.walk(root):
                for name in files:
                    path = os.path.join(folder, name)
                    with open(path, encoding='utf-8') as f:
                        if pattern.search(f.read()):
                            users.append(os.path.relpath(path, root))
        self.assertEqual(users, [])

    def test_redesigned_pages_use_only_the_new_css(self):
        """새 디자인으로 옮긴 화면은 예전 테마·Bootstrap·jQuery를 불러오지 않는다 (docs/adr/0020)."""
        self.client.force_login(User.objects.create_user('20250001', password='pw12345!'))
        with mock.patch('web.views.start_warm_up'):
            self.check_new_css_only(('web:home', 'web:guide', 'web:community', 'web:chatbot'))
        self.client.logout()
        self.check_new_css_only(('web:login', 'web:signup'))

    def check_new_css_only(self, names):
        for name in names:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'css/dorm.css', count=1)
                self.assertContains(response, 'css/dorm-shell.css', count=1)
                for old in ('css/style.css', 'bootstrap', 'jquery', 'js/main.js'):
                    self.assertNotContains(response, old)

    def test_board_pages_use_only_the_new_css(self):
        """게시판·공지 화면도 새 디자인만 쓴다 (docs/adr/0020, 5단계)."""
        student = User.objects.create_user('20250001', password='pw12345!')
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        post = Post.objects.create(author=student, title='t', content='c')
        notice = Notice.objects.create(title='t', content='c')
        pages = {
            student: [reverse('web:community_home'), reverse('web:community_detail', args=[post.pk]),
                      reverse('web:community_create'), reverse('web:community_update', args=[post.pk]),
                      reverse('web:community_delete', args=[post.pk]), reverse('web:notice'),
                      reverse('web:notice_detail', args=[notice.pk])],
            staff: [reverse('web:notice_create'), reverse('web:notice_update', args=[notice.pk]),
                    reverse('web:notice_delete', args=[notice.pk])],
        }
        for user, urls in pages.items():
            self.client.force_login(user)
            for url in urls:
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertContains(response, 'css/dorm.css', count=1)
                    for old in ('css/style.css', 'bootstrap', 'jquery', 'js/main.js', 'font-awesome'):
                        self.assertNotContains(response, old)


class CommunityHomeQueryCountTests(TestCase):
    """자유게시판 목록의 쿼리 수는 글 수와 상관없이 일정해야 한다."""

    def setUp(self):
        self.users = [User.objects.create_user(f'2025000{i}', password='pw12345!') for i in range(3)]
        self.client.force_login(self.users[0])

    def add_posts(self, n):
        for i in range(n):
            post = Post.objects.create(author=self.users[i % 3], title=f'글 {i}', content='내용')
            for user in self.users:
                Comment.objects.create(post=post, author=user, content='댓글')
                Like.objects.create(post=post, user=user)

    def count_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('web:community_home'))
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries), response

    def test_query_count_is_constant_and_counts_are_right(self):
        self.add_posts(2)
        few, _ = self.count_queries()
        self.add_posts(8)
        many, response = self.count_queries()
        self.assertEqual(many, few)
        post = response.context['posts'][0]
        self.assertEqual((post.like_count, post.comment_count), (3, 3))


class LoginRequiredLinkTests(TestCase):
    """로그인이 필요한 링크는 알림창 대신 실제 주소로 가고, 서버가 로그인 페이지로 보낸다."""

    def test_no_template_uses_the_alert_link(self):
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'web')
        for name in os.listdir(template_dir):
            with open(os.path.join(template_dir, name), encoding='utf-8') as f:
                self.assertNotIn("alert('로그인이 필요한 페이지입니다.')", f.read(), name)

    def test_anonymous_menu_links_point_to_real_pages(self):
        response = self.client.get(reverse('web:home'))
        for name in ('web:check_in', 'web:outside', 'web:notice', 'web:community_home', 'web:mypage'):
            self.assertContains(response, f'href="{reverse(name)}"')

    def test_board_lists_require_login(self):
        for name in ('web:notice', 'web:community_home'):
            response = self.client.get(reverse(name))
            self.assertRedirects(response, reverse('web:login') + '?next=' + reverse(name),
                                 fetch_redirect_response=False)

    def test_login_page_explains_why_when_redirected(self):
        self.assertContains(self.client.get(reverse('web:login'), {'next': '/check_in/'}),
                            '로그인이 필요한 페이지입니다.')
        self.assertNotContains(self.client.get(reverse('web:login')), '로그인이 필요한 페이지입니다.')

    def test_user_returns_to_requested_page_after_login(self):
        User.objects.create_user('20250001', password='pw12345!')
        response = self.client.post(reverse('web:login'),
                                    {'username': '20250001', 'password': 'pw12345!', 'next': '/notice/'})
        self.assertRedirects(response, '/notice/')


class StaticReferenceTests(TestCase):
    """템플릿의 {% static '...' %} 경로는 모두 실제 파일이어야 한다 (404 방지)."""

    def test_every_static_reference_in_templates_exists(self):
        import re
        from django.contrib.staticfiles import finders
        base = os.path.dirname(os.path.dirname(__file__))
        missing = []
        for folder, _, files in os.walk(os.path.join(base, 'templates')):
            for name in files:
                with open(os.path.join(folder, name), encoding='utf-8') as f:
                    for path in re.findall(r"\{% static '([^']+)' %\}", f.read()):
                        if not finders.find(path):
                            missing.append(f'{name}: {path}')
        self.assertEqual(missing, [])


class DatabaseSettingsTests(TestCase):
    """DB는 PostgreSQL이고 접속 정보는 환경변수에서 읽는다 (ADR 0005)."""

    def read_db_settings(self, **env):
        code = ('import django, json; django.setup(); from django.conf import settings; '
                'd = settings.DATABASES["default"]; print(json.dumps([d["ENGINE"], d["HOST"], str(d["PORT"]), d["NAME"]]))')
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'finalproject.settings', **env})
        import json
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_uses_postgresql_with_settings_from_environment(self):
        engine, host, port, name = self.read_db_settings(POSTGRES_HOST='db.example', POSTGRES_PORT='6543',
                                                         POSTGRES_DB='dorm_x')
        self.assertEqual((engine, host, port, name),
                         ('django.db.backends.postgresql', 'db.example', '6543', 'dorm_x'))


@override_settings(KNOWLEDGE_LLM={'BACKEND': 'fake'}, KNOWLEDGE_EMBEDDING={'BACKEND': 'fake'},
                   KNOWLEDGE_ROUTER={'BACKEND': 'fake'})
class AnswerDraftPanelTests(TestCase):
    """관리자 문의 화면의 AI 답변 초안: 만들기만 하고 저장·발송은 관리자가 한다."""

    @classmethod
    def setUpTestData(cls):
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(FakeEmbedder())
        cls.owner = User.objects.create_user('20250001', password='pw12345!')
        cls.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        cls.inquiry = Inquiry.objects.create(user=cls.owner, title='출입시간', content='생활관 출입시간 알려주세요')
        cls.url = reverse('web:inquiry_draft', args=[cls.inquiry.pk])

    def setUp(self):
        # 가짜 임베딩은 bge-m3와 유사도 눈금이 달라 근거 부족 기준을 끈다
        patcher = mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_staff_gets_an_editable_draft_with_evidence(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        draft = response.context['draft']
        self.assertEqual(draft.status, 'ok')
        self.assertEqual(response.context['form']['answer'].value(), draft.text)
        self.assertContains(response, draft.evidence[0].chunk.title)
        self.assertContains(response, f'action="{reverse("web:inquiry_detail", args=[self.inquiry.pk])}"')
        self.assertFalse(InquiryAnswer.objects.exists())  # 초안은 저장되지 않는다

    def test_detail_page_offers_the_draft_button_only_to_staff(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('web:inquiry_detail', args=[self.inquiry.pk])), self.url)
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('web:inquiry_detail', args=[self.inquiry.pk])), self.url)

    def test_students_cannot_request_a_draft(self):
        self.client.force_login(self.owner)
        with mock.patch('web.views.draft_answer') as draft_answer:
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        draft_answer.assert_not_called()

    def test_draft_needs_post(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_weak_evidence_shows_a_notice_and_leaves_the_answer_empty(self):
        self.client.force_login(self.staff)
        with mock.patch('knowledge.answering.MIN_SIMILARITY', 1.1):
            response = self.client.post(self.url)
        self.assertEqual(response.context['draft'].status, 'insufficient_evidence')
        self.assertContains(response, '직접 답변해 주세요')
        self.assertFalse(response.context['form']['answer'].value())

    def test_existing_answer_is_kept_when_no_draft_is_made(self):
        InquiryAnswer.objects.create(inquiry=self.inquiry, admin=self.staff, answer='기존 답변')
        self.client.force_login(self.staff)
        with mock.patch('knowledge.answering.MIN_SIMILARITY', 1.1):
            response = self.client.post(self.url)
        self.assertEqual(response.context['form']['answer'].value(), '기존 답변')

    def test_model_or_search_failure_is_shown_not_raised(self):
        self.client.force_login(self.staff)
        with mock.patch('web.views.draft_answer', side_effect=RuntimeError('임베딩 모델 라이브러리가 설치되지 않았습니다.')):
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '임베딩 모델 라이브러리가 설치되지 않았습니다.')


@override_settings(KNOWLEDGE_LLM={'BACKEND': 'fake'}, KNOWLEDGE_EMBEDDING={'BACKEND': 'fake'},
                   KNOWLEDGE_ROUTER={'BACKEND': 'fake'})
class ChatbotPageTests(TestCase):
    """학생 챗봇 화면 (ADR 0011)."""

    @classmethod
    def setUpTestData(cls):
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(FakeEmbedder())
        cls.student = User.objects.create_user('20250001', password='pw12345!')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        patcher = mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.student)

    def ask(self, question):
        return self.client.post(reverse('web:chatbot_ask'), {'question': question})

    def test_page_needs_login(self):
        self.client.logout()
        response = self.client.get(reverse('web:chatbot'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('web:login'), response['Location'])

    def test_page_shows_suggestions_and_a_caution(self):
        from knowledge.chat import load_suggestions
        response = self.client.get(reverse('web:chatbot'))
        self.assertEqual(response.status_code, 200)
        suggestions = load_suggestions()
        self.assertGreaterEqual(len(suggestions), 6)
        for item in suggestions:
            self.assertContains(response, item['label'])
        self.assertContains(response, 'AI 답변은 틀릴 수 있어요')

    def test_menu_links_to_the_chatbot(self):
        self.assertContains(self.client.get(reverse('web:rules')), reverse('web:chatbot'))

    def test_answer_comes_back_as_json_with_sources(self):
        response = self.ask('생활관 출입시간 알려주세요')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'answered')
        self.assertIn('[1]', data['text'])
        self.assertEqual(data['sources'][0]['number'], 1)
        self.assertTrue(data['sources'][0]['url'].startswith('/rules/'))

    def test_empty_or_too_long_questions_are_rejected(self):
        with mock.patch('web.views.reply_to') as answer_question:
            for question in ('', '   ', '가' * 501):
                response = self.ask(question)
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
        answer_question.assert_not_called()

    def test_ask_needs_post_and_login(self):
        self.assertEqual(self.client.get(reverse('web:chatbot_ask')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.ask('출입시간').status_code, 302)

    def test_more_than_ten_questions_a_minute_are_refused(self):
        for _ in range(10):
            self.assertEqual(self.ask('출입시간 알려주세요').status_code, 200)
        response = self.ask('출입시간 알려주세요')
        self.assertEqual(response.status_code, 429)
        self.assertIn('잠시 후', response.json()['error'])


@override_settings(KNOWLEDGE_LLM={'BACKEND': 'fake'}, KNOWLEDGE_EMBEDDING={'BACKEND': 'fake'},
                   KNOWLEDGE_ROUTER={'BACKEND': 'fake'})
class ChatbotFeedbackPageTests(TestCase):
    """챗봇 답마다 익명 기록과 👍/👎 (docs/adr/0012)."""

    @classmethod
    def setUpTestData(cls):
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(FakeEmbedder())
        cls.student = User.objects.create_user('20250001', password='pw12345!')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        patcher = mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.student)

    def feedback(self, **data):
        return self.client.post(reverse('web:chatbot_feedback'), data)

    def test_answer_comes_with_a_feedback_key_and_is_logged(self):
        from knowledge.models import ChatLog
        data = self.client.post(reverse('web:chatbot_ask'), {'question': '생활관 출입시간 알려주세요'}).json()
        self.assertEqual(ChatLog.objects.get(pk=data['log_id']).channel, 'web')
        key = data['feedback_token']
        self.assertEqual(self.feedback(log_id=data['log_id'], token=key, rating='up').status_code, 200)
        self.assertEqual(self.feedback(log_id=data['log_id'], token=key, rating='down').status_code, 409)
        self.assertEqual(self.feedback(log_id=data['log_id'], token='x', rating='up').status_code, 404)
        self.assertEqual(self.feedback(log_id='abc', token='x', rating='meh').status_code, 400)

    def test_logging_failure_does_not_break_the_answer(self):
        with mock.patch('knowledge.chat_log.ChatLog.objects.create', side_effect=RuntimeError('db down')):
            response = self.client.post(reverse('web:chatbot_ask'), {'question': '생활관 출입시간 알려주세요'})
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['status'], 'answered')
        self.assertIsNone(data['log_id'])

    def test_page_explains_what_is_stored(self):
        self.assertContains(self.client.get(reverse('web:chatbot')), '익명으로 저장')


class ChatbotWarmUpPageTests(TestCase):
    def test_opening_the_page_starts_warming_up_the_models(self):
        self.client.force_login(User.objects.create_user('20250001', password='pw12345!'))
        with mock.patch('web.views.start_warm_up') as start_warm_up:
            self.assertEqual(self.client.get(reverse('web:chatbot')).status_code, 200)
        start_warm_up.assert_called_once()


@override_settings(KNOWLEDGE_LLM={'BACKEND': 'fake'}, KNOWLEDGE_EMBEDDING={'BACKEND': 'fake'},
                   KNOWLEDGE_ROUTER={'BACKEND': 'fake'})
class ChatbotConversationPageTests(TestCase):
    """웹 챗봇의 이어지는 대화 (docs/adr/0014)."""

    @classmethod
    def setUpTestData(cls):
        sync_chunks(build_chunks(['rules']), ['rules'])
        embed_pending(FakeEmbedder())
        cls.student = User.objects.create_user('20250001', password='pw12345!')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        patcher = mock.patch('knowledge.answering.MIN_SIMILARITY', 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.student)

    def test_follow_up_message_continues_the_conversation(self):
        first = self.client.post(reverse('web:chatbot_ask'), {'question': '생활관 출입시간 알려주세요'}).json()
        self.assertEqual(first['kind'], 'new')
        second = self.client.post(reverse('web:chatbot_ask'),
                                  {'question': '요약해줘', 'conversation_id': first['conversation_id']}).json()
        self.assertEqual(second['kind'], 'meta')
        self.assertEqual(second['conversation_id'], first['conversation_id'])

    def test_page_has_a_new_conversation_button(self):
        self.assertContains(self.client.get(reverse('web:chatbot')), 'id="new-chat"')


class ChatbotPageLayoutTests(TestCase):
    """챗봇 화면의 새 디자인 (docs/adr/0020, 7단계). 답을 그리는 동작은 화면의 자바스크립트가 한다."""

    def setUp(self):
        self.client.force_login(User.objects.create_user('20250001', password='pw12345!'))
        with mock.patch('web.views.start_warm_up'):
            self.response = self.client.get(reverse('web:chatbot'))

    def test_question_box_has_a_label_and_a_send_button(self):
        self.assertContains(self.response, '<label class="dg-sr" for="question">')
        self.assertContains(self.response, 'id="question" name="question"')
        self.assertContains(self.response, '>보내기</button>')

    def test_suggested_questions_are_buttons_that_send_the_question(self):
        from knowledge.chat import load_suggestions
        for item in load_suggestions():
            self.assertContains(self.response, f'data-question="{item["question"]}"')

    def test_conversation_is_announced_and_notes_stay(self):
        self.assertContains(self.response, 'role="log"')
        self.assertContains(self.response, 'role="status"')
        self.assertContains(self.response, 'AI 답변은 틀릴 수 있어요')
        self.assertContains(self.response, '익명으로 저장')
        self.assertContains(self.response, f'{reverse("web:mypage")}?tab=inquiry')


class HomeBoardTests(TestCase):
    """홈 "오늘의 생활관": 규칙·식단·셔틀·내 외박 신청·공지를 한 화면에 (docs/adr/0020)."""

    def board(self, when, user=None):
        from web.home import today_board
        return today_board(timezone.make_aware(when), user)

    def test_hours_come_from_the_rules(self):
        from datetime import datetime
        board = self.board(datetime(2026, 10, 30, 22, 0))
        self.assertEqual((board['entry']['start'], board['entry']['end']), ('06:00', '23:00'))
        self.assertEqual((board['lights_out']['start'], board['lights_out']['end']), ('00:00', '06:00'))
        self.assertTrue(board['entry']['open'])
        self.assertFalse(self.board(datetime(2026, 10, 30, 23, 30))['entry']['open'])

    def test_next_shuttle_from_school_skips_blank_cells(self):
        from datetime import datetime
        board = self.board(datetime(2026, 10, 30, 12, 30))  # 터미널 방면 12시대 편은 운행하지 않음('<--')
        shuttles = {s['route']: s['time'] for s in board['shuttles']}
        self.assertEqual(shuttles['천안 터미널 방면'], '13:40')
        self.assertEqual(shuttles['천안 아산역 방면'], '14:00')
        late = self.board(datetime(2026, 10, 30, 22, 0))
        self.assertTrue(all(s['time'] is None and s['first'] for s in late['shuttles']))

    def test_meals_follow_the_weekday_and_weekend_has_none(self):
        from datetime import datetime
        friday = self.board(datetime(2026, 10, 30, 9, 0))
        self.assertEqual([m['name'] for m in friday['meals']], ['중식', '석식'])
        self.assertEqual(friday['meals'][0]['time'], '11:00–13:30')
        self.assertIn('잔치국수', friday['meals'][0]['dishes'])
        self.assertEqual(self.board(datetime(2026, 10, 31, 9, 0))['meals'], [])

    def test_latest_outing_for_the_student(self):
        from datetime import datetime
        student = User.objects.create_user('20250001', password='pw12345!')
        OutingApply.objects.create(user=student, name='김학생', student_number='20250001', out_date=date(2026, 10, 1))
        latest = OutingApply.objects.create(user=student, name='김학생', student_number='20250001',
                                            out_date=date(2026, 11, 1))
        self.assertEqual(self.board(datetime(2026, 10, 30, 9, 0), student)['outing'], latest)

    def test_home_page_shows_the_board_and_recent_notices(self):
        for i in range(4):
            Notice.objects.create(title=f'공지{i}', content='내용')
        response = self.client.get(reverse('web:home'))
        self.assertContains(response, '오늘의 생활관')
        self.assertContains(response, '06:00')
        self.assertContains(response, 'css/dorm.css')
        self.assertNotContains(response, 'css/style.css')
        self.assertContains(response, '공지3')
        self.assertNotContains(response, '공지0')  # 최근 3개만
        self.assertContains(response, '로그인하면')

    def test_student_sees_outing_status_and_staff_sees_pending_count(self):
        student = User.objects.create_user('20250001', password='pw12345!')
        OutingApply.objects.create(user=student, name='김학생', student_number='20250001', out_date=date(2026, 11, 1))
        self.client.force_login(student)
        response = self.client.get(reverse('web:home'))
        self.assertContains(response, '승인 대기')
        self.assertContains(response, reverse('web:outing_info'))
        self.client.force_login(User.objects.create_user('admin', password='pw12345!', is_staff=True))
        self.assertContains(self.client.get(reverse('web:home')), '처리할 외박 신청')


class ApplyFlowPageTests(TestCase):
    """입실·외박 신청 화면: 아는 정보는 미리 채우고, 오류 뒤에도 입력을 지우지 않는다 (docs/adr/0020)."""

    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()
        self.client.force_login(self.student)

    def test_outing_form_uses_the_logged_in_identity(self):
        response = self.client.get(reverse('web:outside'))
        self.assertContains(response, '홍길동')
        self.assertContains(response, 'name="name" value="홍길동"')
        self.assertContains(response, 'name="student_number" value="20250001"')
        self.assertContains(response, f'min="{timezone.localdate().isoformat()}"')
        self.assertContains(response, 'css/dorm.css')
        self.assertNotContains(response, 'css/style.css')

    def test_outing_form_lists_recent_requests(self):
        OutingApply.objects.create(user=self.student, name='홍길동', student_number='20250001',
                                   out_date=date(2026, 11, 7), status='approved')
        response = self.client.get(reverse('web:outside'))
        self.assertContains(response, '승인됨')
        self.assertContains(response, reverse('web:outing_info'))

    def test_check_in_form_is_prefilled_and_keeps_input_after_an_error(self):
        response = self.client.get(reverse('web:check_in'))
        self.assertContains(response, 'value="홍길동"')
        self.assertContains(response, 'value="20250001"')
        response = self.client.post(reverse('web:check_in'),
                                    {'name': '홍길동', 'student_number': '20250001', 'content': '조용한 방 희망'})
        self.assertContains(response, '필수 항목을 모두 입력해주세요.')
        self.assertContains(response, '조용한 방 희망')
        self.assertFalse(Dorm.objects.exists())

    def test_check_in_shows_status_instead_of_form_after_applying(self):
        Dorm.objects.create(user=self.student, name='홍길동', student_number='20250001', gender='male')
        response = self.client.get(reverse('web:check_in'))
        self.assertContains(response, '이미 입실 신청을 했어요')
        self.assertNotContains(response, 'name="gender"')

    def test_successful_check_in_goes_home_with_a_notice(self):
        response = self.client.post(reverse('web:check_in'),
                                    {'name': '홍길동', 'student_number': '20250001', 'gender': 'male'}, follow=True)
        self.assertContains(response, '기숙사 신청이 완료되었습니다.')
        self.assertContains(response, 'dg-toast--success')

    def test_no_success_alert_before_the_server_answers(self):
        for name in ('check_in', 'outside', 'apply_success'):
            with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'web', f'{name}.html'),
                      encoding='utf-8') as f:
                self.assertNotIn('alert(', f.read(), name)

    def test_success_page_links_to_my_requests(self):
        response = self.client.get(reverse('web:apply_success'))
        self.assertContains(response, reverse('web:outing_info'))
        self.assertContains(response, 'css/dorm.css')


class MyPageLayoutTests(TestCase):
    """마이페이지: 탭은 링크(?tab=), 문의 목록은 키보드로도 열 수 있는 링크, 답변 상태 표시 (docs/adr/0020)."""

    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.student.userprofile.full_name = '홍길동'
        self.student.userprofile.save()
        self.client.force_login(self.student)

    def test_tabs_are_links_and_only_the_active_panel_renders(self):
        response = self.client.get(reverse('web:mypage'))
        self.assertContains(response, 'href="?tab=inquiry"')
        self.assertContains(response, 'aria-current="page">내 정보')
        self.assertContains(response, '홍길동')
        self.assertNotContains(response, 'name="submit_inquiry"')
        self.assertNotContains(response, 'onclick=')
        self.assertContains(response, 'css/dorm.css')
        self.assertNotContains(response, 'css/style.css')

    def test_inquiry_tab_lists_inquiries_as_links_with_answer_status(self):
        answered = Inquiry.objects.create(user=self.student, title='답변 받은 문의', content='c')
        Inquiry.objects.create(user=self.student, title='기다리는 문의', content='c')
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        InquiryAnswer.objects.create(inquiry=answered, admin=staff, answer='a')
        response = self.client.get(reverse('web:mypage'), {'tab': 'inquiry'})
        self.assertContains(response, 'name="submit_inquiry"')
        self.assertContains(response, f'href="{reverse("web:inquiry_detail", args=[answered.pk])}"')
        self.assertContains(response, '답변 완료')
        self.assertContains(response, '답변 대기')

    def test_inquiry_list_query_count_does_not_grow(self):
        for i in range(3):
            Inquiry.objects.create(user=self.student, title=f'q{i}', content='c')
        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse('web:mypage'), {'tab': 'inquiry'})
        for i in range(5):
            Inquiry.objects.create(user=self.student, title=f'r{i}', content='c')
        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse('web:mypage'), {'tab': 'inquiry'})
        self.assertEqual(len(small), len(large))

    def test_invalid_inquiry_stays_on_the_inquiry_tab_with_errors(self):
        response = self.client.post(reverse('web:mypage'), {'submit_inquiry': '1', 'title': '', 'content': ''})
        self.assertContains(response, 'name="submit_inquiry"')
        self.assertContains(response, 'aria-invalid="true"')

    def test_staff_search_tab(self):
        staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse('web:mypage'), {'field': 'full_name', 'query': '길동'})
        self.assertContains(response, 'aria-current="page">학생 검색')
        self.assertContains(response, '20250001')


BOARD_TEMPLATES = ('community_home.html', 'community_detail.html', 'community_create.html', 'community_update.html',
                   'community_confirm_delete.html', 'notice.html', 'notice_detail.html', 'notice_create.html',
                   'notice_update.html', 'notice_confirm_delete.html')


class BoardPageTests(TestCase):
    """자유게시판·공지 화면 (docs/adr/0020, 5단계)."""

    def setUp(self):
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.other = User.objects.create_user('20250002', password='pw12345!')
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.client.force_login(self.student)

    def test_row_numbers_continue_on_the_next_page(self):
        for i in range(12):
            Post.objects.create(author=self.other, title=f'글 {i}', content='c')
            Notice.objects.create(title=f'공지 {i}', content='c')
        for name in ('web:community_home', 'web:notice'):
            with self.subTest(name=name):
                first = self.client.get(reverse(name))
                self.assertContains(first, '<td class="dg-boardlist__no">12</td>')  # 최신 글이 가장 큰 번호
                response = self.client.get(reverse(name), {'page': 2})
                self.assertContains(response, '<td class="dg-boardlist__no">2</td>')
                self.assertContains(response, '<td class="dg-boardlist__no">1</td>')
                self.assertNotContains(response, '<td class="dg-boardlist__no">12</td>')

    def test_list_does_not_number_anonymous_authors(self):
        Post.objects.create(author=self.other, title='남의 글', content='c')
        Post.objects.create(author=self.student, title='내 글', content='c')
        response = self.client.get(reverse('web:community_home'))
        self.assertNotContains(response, '익명1')
        self.assertNotContains(response, '익명2')
        self.assertContains(response, '>익명<', count=1)
        self.assertContains(response, '>나<', count=1)

    def test_comment_labels_are_stable_per_author_within_a_post(self):
        post = Post.objects.create(author=self.student, title='t', content='c')
        for author in (self.other, self.staff, self.other, self.student):
            Comment.objects.create(post=post, author=author, content='댓글')
        html = self.client.get(reverse('web:community_detail', args=[post.pk])).content.decode()
        labels = re.findall(r'class="dg-comments__who[^"]*">([^<]+)<', html)
        self.assertEqual(labels, ['익명1', '익명2', '익명1', '글쓴이'])

    def test_search_keyword_is_urlencoded_in_page_links(self):
        for i in range(12):
            Post.objects.create(author=self.other, title=f'a&b c {i}', content='c')
            Notice.objects.create(title=f'a&b c {i}', content='c')
        for name in ('web:community_home', 'web:notice'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name), {'kw': 'a&b c'})
                self.assertContains(response, 'kw=a%26b%20c')
                self.assertNotContains(response, 'kw=a&b c')
                self.assertNotContains(response, 'kw=a&amp;b c')

    def test_like_button_shows_whether_i_liked(self):
        post = Post.objects.create(author=self.other, title='t', content='c')
        url = reverse('web:community_detail', args=[post.pk])
        self.assertContains(self.client.get(url), 'aria-pressed="false"')
        Like.objects.create(user=self.student, post=post)
        self.assertContains(self.client.get(url), 'aria-pressed="true"')

    def test_comment_box_is_labelled_and_enter_does_not_submit(self):
        post = Post.objects.create(author=self.other, title='t', content='c')
        response = self.client.get(reverse('web:community_detail', args=[post.pk]))
        self.assertContains(response, 'for="comment-textarea"')
        self.assertContains(response, 'id="comment-textarea"', count=1)
        self.assertNotContains(response, 'keydown')

    def test_delete_goes_through_the_confirm_page(self):
        post = Post.objects.create(author=self.student, title='t', content='c')
        detail = self.client.get(reverse('web:community_detail', args=[post.pk]))
        self.assertContains(detail, f'href="{reverse("web:community_delete", args=[post.pk])}"')
        self.assertNotContains(self.client.get(reverse('web:community_home')), 'confirm(')
        others = Post.objects.create(author=self.other, title='t', content='c')
        self.assertNotContains(self.client.get(reverse('web:community_detail', args=[others.pk])),
                               reverse('web:community_delete', args=[others.pk]))
        notice = Notice.objects.create(title='공지', content='c')
        self.assertNotContains(self.client.get(reverse('web:notice_detail', args=[notice.pk])),
                               reverse('web:notice_delete', args=[notice.pk]))
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('web:notice_detail', args=[notice.pk])),
                            f'href="{reverse("web:notice_delete", args=[notice.pk])}"')
        self.assertNotContains(self.client.get(reverse('web:notice')), 'confirm(')
        confirm = self.client.get(reverse('web:notice_delete', args=[notice.pk]))
        self.assertContains(confirm, '공지')
        self.assertContains(confirm, notice.date.strftime('%Y.%m.%d'))
        self.assertContains(confirm, 'dg-btn--danger')

    def test_only_staff_sees_the_write_notice_button(self):
        self.assertNotContains(self.client.get(reverse('web:notice')), f'href="{reverse("web:notice_create")}"')
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('web:notice')), f'href="{reverse("web:notice_create")}"')

    def test_notice_create_has_one_form(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('web:notice_create'))
        self.assertContains(response, 'name="title"', count=1)
        self.assertContains(response, 'name="content"', count=1)

    def test_notice_detail_has_no_placeholder_text(self):
        notice = Notice.objects.create(title='공지', content='본문')
        response = self.client.get(reverse('web:notice_detail', args=[notice.pk]))
        self.assertNotContains(response, '{ 내용 }')
        self.assertNotContains(response, '제목:')
        self.assertContains(response, '<h1>공지</h1>')

    def test_counters_start_at_the_current_length(self):
        post = Post.objects.create(author=self.student, title='제목다섯자', content='c')
        response = self.client.get(reverse('web:community_update', args=[post.pk]))
        self.assertContains(response, '5/200자')
        self.assertContains(response, '1/1000자')

    def test_images_have_the_title_as_alt(self):
        post = Post.objects.create(author=self.student, title='사진 글', content='c', image='posts/x.png')
        response = self.client.get(reverse('web:community_detail', args=[post.pk]))
        self.assertContains(response, 'alt="사진 글"')

    def test_board_templates_have_no_dead_scripts(self):
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'web')
        for name in BOARD_TEMPLATES:
            with open(os.path.join(template_dir, name), encoding='utf-8') as f:
                text = f.read()
            for dead in ('alert(', 'confirm(', 'localStorage', 'notice-body', 'simplyCountdown', 'onsubmit', 'oninput'):
                self.assertNotIn(dead, text, f'{name}: {dead}')


class InfoPageTests(TestCase):
    """안내 화면(규칙·안내·식단·셔틀·편의시설)을 새 디자인으로 (docs/adr/0020, 6단계)."""
    OLD_KAKAO_KEY = 'aca3f50bafe4f955bd781786417506fb'
    PAGES = ('web:rules', 'web:info', 'web:menu', 'web:bus', 'web:acc')

    def at(self, *args):
        from datetime import datetime
        return timezone.make_aware(datetime(*args))

    def test_info_pages_use_only_the_new_css(self):
        for name in self.PAGES:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'css/dorm.css', count=1)
                self.assertContains(response, 'css/dorm-shell.css', count=1)
                for old in ('css/style.css', 'bootstrap', 'jquery', 'js/main.js', 'fh5co', '#f3dede', 'Noto Sans KR'):
                    self.assertNotContains(response, old)

    def test_rules_have_a_table_of_contents_with_article_anchors(self):
        response = self.client.get(reverse('web:rules'))
        self.assertContains(response, 'href="#article-3"')
        self.assertContains(response, 'id="article-3"')
        self.assertContains(response, 'id="article-14-2"')
        self.assertContains(response, 'href="#penalties"')
        self.assertContains(response, '<h2 id="article-1"', html=False)
        self.assertNotContains(response, '<br>')

    def test_rules_penalty_table_is_a_real_table(self):
        response = self.client.get(reverse('web:rules'))
        html = response.content.decode()
        table = html[html.index('id="penalties"'):]
        self.assertIn('class="dg-table', table)
        self.assertIn('<th scope="col">위반내용</th>', table)
        self.assertIn('class="dg-table__num">3점</td>', table)
        self.assertContains(response, '벌점 20점 이상 또는 퇴관 사유 위반 시')

    def test_info_has_chapters_and_articles_as_headings(self):
        response = self.client.get(reverse('web:info'))
        self.assertContains(response, '<h2 id="chapter-1"', html=False)
        self.assertContains(response, '<h3 id="article-26"', html=False)
        self.assertContains(response, 'href="#article-26"')
        self.assertContains(response, '관생 인원 점검 (매일 24:00)</li>')

    def test_menu_marks_today_by_weekday(self):
        from knowledge import sources
        from web.info_pages import week_menu
        friday = week_menu(sources.load('menu'), self.at(2026, 10, 30, 9, 0))
        self.assertEqual([d['is_today'] for d in friday['days']], [False, False, False, False, True])
        self.assertEqual(friday['meals'][0]['time'], '11:00–13:30')
        self.assertEqual(friday['days'][4]['meals'][0]['dishes'], ['잔치국수', '떡갈비', '영양고추치'])
        saturday = week_menu(sources.load('menu'), self.at(2026, 10, 31, 9, 0))
        self.assertFalse(any(d['is_today'] for d in saturday['days']))
        self.assertTrue(saturday['weekend'])

    def test_menu_page_shows_notes_and_today(self):
        with mock.patch('web.views.timezone.localtime', return_value=self.at(2026, 10, 28, 9, 0)):  # 수요일
            response = self.client.get(reverse('web:menu'))
        self.assertContains(response, '한 주의 예시 식단입니다')
        self.assertContains(response, 'dg-menu__day is-today', count=1)
        self.assertContains(response, '<details class="dg-menuday is-today" open>', html=False)

    def test_bus_marks_the_next_departure_from_school(self):
        from knowledge import sources
        from web.info_pages import bus_routes
        routes = {r['key']: r for r in bus_routes(sources.load('bus'), self.at(2026, 10, 30, 12, 30))}
        terminal = routes['terminal']
        self.assertEqual(terminal['next'], '13:40')
        marked = [row for row in terminal['inbound']['rows'] if row['is_next']]
        self.assertEqual([row['cells'][0]['time'] for row in marked], ['13:40'])
        self.assertFalse(any(row['is_next'] for row in terminal['outbound']['rows']))
        skipped = [row for row in terminal['outbound']['rows'] if row['skip']]
        self.assertEqual(skipped[0]['skip'], '운행 안 함')
        self.assertEqual(routes['asan']['next'], '14:00')
        late = bus_routes(sources.load('bus'), self.at(2026, 10, 30, 22, 0))
        self.assertTrue(all(r['next'] is None for r in late))

    def test_bus_route_tabs_and_tables(self):
        response = self.client.get(reverse('web:bus'))
        self.assertContains(response, 'href="?route=terminal" aria-current="page"')
        self.assertContains(response, '학교에서 나가는 편')
        self.assertContains(response, '학교로 오는 편')
        self.assertContains(response, 'id="table-terminal"')
        self.assertNotContains(response, 'id="table-asan"')
        self.assertNotContains(response, '&lt;--')
        asan = self.client.get(reverse('web:bus'), {'route': 'asan'})
        self.assertContains(asan, 'id="table-asan"')
        self.assertContains(asan, '휴게 시간')
        self.assertEqual(self.client.get(reverse('web:bus'), {'route': 'nope'}).status_code, 200)

    def test_acc_lists_every_place_without_the_map(self):
        from web.info_pages import PLACES
        response = self.client.get(reverse('web:acc'))
        for place in PLACES:
            self.assertContains(response, place['title'])
        self.assertContains(response, 'aria-pressed="true"')

    @override_settings(KAKAO_MAP_KEY='')
    def test_map_pages_render_a_fallback_without_the_key(self):
        for name in ('web:acc', 'web:bus'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'dapi.kakao.com')
                self.assertContains(response, '지도를 불러오지 못했어요')

    @override_settings(KAKAO_MAP_KEY='test-key-123')
    def test_map_pages_load_the_map_with_the_key_from_settings(self):
        for name in ('web:acc', 'web:bus'):
            with self.subTest(name=name):
                self.assertContains(self.client.get(reverse(name)),
                                    'dapi.kakao.com/v2/maps/sdk.js?appkey=test-key-123', count=1)

    def test_kakao_key_is_read_from_the_environment(self):
        from django.conf import settings
        self.assertTrue(hasattr(settings, 'KAKAO_MAP_KEY'))
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
        for root, _, files in os.walk(template_dir):
            for name in files:
                with open(os.path.join(root, name), encoding='utf-8') as f:
                    self.assertNotIn(self.OLD_KAKAO_KEY, f.read(), name)


class StaffPageTests(TestCase):
    """관리자 화면(입실·외박 신청 관리, 문의 상세, 상벌점)을 새 디자인으로 (docs/adr/0020, 9단계)."""
    OLD = ('css/style.css', 'bootstrap', 'jquery', 'js/main.js', 'font-awesome', '#F2DCDC', '#007bff')

    def setUp(self):
        self.staff = User.objects.create_user('admin', password='pw12345!', is_staff=True)
        self.student = User.objects.create_user('20250001', password='pw12345!')
        self.other = User.objects.create_user('20250002', password='pw12345!')
        self.inquiry = Inquiry.objects.create(user=self.student, title='문의', content='내용')

    def outing(self, user, day, status='pending', name='홍길동'):
        return OutingApply.objects.create(user=user, name=name, student_number=user.username,
                                          out_date=date(2026, 11, day), status=status)

    def test_staff_pages_use_only_the_new_css(self):
        detail = reverse('web:inquiry_detail', args=[self.inquiry.pk])
        pages = {
            self.staff: [reverse(n) for n in ('web:dorminfo', 'web:outside_manage', 'web:outing_info',
                                              'web:reward_penalty')] + [detail],
            self.student: [reverse('web:dorminfo'), reverse('web:outing_info'), detail],
        }
        for user, urls in pages.items():
            self.client.force_login(user)
            for url in urls:
                with self.subTest(user=user.username, url=url):
                    response = self.client.get(url)
                    self.assertContains(response, 'css/dorm.css', count=1)
                    self.assertContains(response, 'css/dorm-shell.css', count=1)
                    for old in self.OLD:
                        self.assertNotContains(response, old)

    # 입실 신청 관리
    def test_assignment_inputs_are_labelled_and_bed_is_a_choice(self):
        dorm = Dorm.objects.create(name='홍길동', student_number='20250001', gender='male')
        self.client.force_login(self.staff)
        html = self.client.get(reverse('web:dorminfo') + '?status=all').content.decode()
        for field in ('building', 'room', 'bed'):
            self.assertIn(f'for="{field}-{dorm.pk}"', html)
            self.assertIn(f'id="{field}-{dorm.pk}"', html)
        self.assertRegex(html, r'<select[^>]*name="position"')
        for n in '1234':
            self.assertIn(f'<option value="{n}">{n}번</option>', html)
        self.assertIn(f'action="{reverse("web:assign_room", args=[dorm.pk])}"', html)
        self.assertIn('미배정', html)
        self.assertNotIn('>Male<', html)

    def test_assigned_room_shows_as_a_plate(self):
        Dorm.objects.create(name='홍길동', student_number='20250001', gender='male',
                            building_name='A동', r_number=101, position=2)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('web:dorminfo') + '?status=all')
        self.assertContains(response, 'A동 101호')
        self.assertContains(response, '2번 침대')

    def test_dorm_filter_tabs(self):
        Dorm.objects.create(name='배정됨', student_number='20250001', gender='male',
                            building_name='A동', r_number=101, position=2)
        Dorm.objects.create(name='대기중', student_number='20250002', gender='female')
        self.client.force_login(self.staff)
        waiting = self.client.get(reverse('web:dorminfo'))
        self.assertEqual([d.name for d in waiting.context['dorms']], ['대기중'])
        self.assertContains(waiting, 'href="?status=all"')
        everyone = self.client.get(reverse('web:dorminfo') + '?status=all')
        self.assertEqual([d.name for d in everyone.context['dorms']], ['배정됨', '대기중'])

    def test_dorm_list_query_count_is_constant(self):
        self.client.force_login(self.staff)
        url = reverse('web:dorminfo') + '?status=all'
        Dorm.objects.create(name='a', student_number='1', gender='male')
        with CaptureQueriesContext(connection) as one:
            self.client.get(url)
        for i in range(2, 7):
            Dorm.objects.create(name='a', student_number=str(i), gender='male')
        with CaptureQueriesContext(connection) as many:
            self.client.get(url)
        self.assertEqual(len(one), len(many))

    def test_student_sees_only_own_application_without_assign_form(self):
        Dorm.objects.create(user=self.student, name='내신청', student_number='20250001', gender='male')
        Dorm.objects.create(user=self.other, name='남의신청', student_number='20250002', gender='male')
        self.client.force_login(self.student)
        response = self.client.get(reverse('web:dorminfo'))
        self.assertContains(response, '내신청')
        self.assertNotContains(response, '남의신청')
        self.assertNotContains(response, 'name="position"')
        self.assertNotContains(response, 'dg-tabs')

    def test_student_without_application_gets_a_link_to_apply(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get(reverse('web:dorminfo')), f'href="{reverse("web:check_in")}"')

    # 외박 신청 관리
    def test_reject_asks_once_more_and_approve_is_direct(self):
        outing = self.outing(self.student, 1)
        self.client.force_login(self.staff)
        html = self.client.get(reverse('web:outside_manage')).content.decode()
        self.assertNotIn('confirm(', html)
        reject = reverse('web:reject_outing', args=[outing.pk])
        self.assertRegex(html, r'<details[^>]*>\s*<summary[^>]*>반려</summary>\s*<form[^>]*method="post" action="'
                         + re.escape(reject) + '"')
        self.assertIn(f'action="{reverse("web:approve_outing", args=[outing.pk])}"', html)

    def test_approve_and_reject_show_a_notice(self):
        first, second = self.outing(self.student, 1), self.outing(self.student, 2)
        self.client.force_login(self.staff)
        response = self.client.post(reverse('web:approve_outing', args=[first.pk]), follow=True)
        self.assertContains(response, '승인했습니다')
        response = self.client.post(reverse('web:reject_outing', args=[second.pk]), follow=True)
        self.assertContains(response, '반려했습니다')

    def test_outing_status_is_written_not_only_coloured(self):
        self.outing(self.student, 1)
        self.outing(self.student, 2, 'approved')
        self.outing(self.student, 3, 'rejected')
        self.client.force_login(self.staff)
        response = self.client.get(reverse('web:outing_info') + '?status=all')
        for text in ('승인 대기', '승인됨', '반려됨'):
            self.assertContains(response, text)
        self.assertContains(response, 'dg-status--rejected')

    def test_outing_filter_defaults_to_pending_for_staff(self):
        late = self.outing(self.student, 9)
        done = self.outing(self.student, 1, 'approved')
        early = self.outing(self.other, 2, name='김철수')
        self.client.force_login(self.staff)
        pending = self.client.get(reverse('web:outside_manage')).context['applications']
        self.assertEqual([a.pk for a in pending], [early.pk, late.pk])  # 외박 날짜가 가까운 순
        everyone = self.client.get(reverse('web:outside_manage') + '?status=all').context['applications']
        self.assertEqual({a.pk for a in everyone}, {late.pk, done.pk, early.pk})
        bogus = self.client.get(reverse('web:outside_manage') + '?status=nope')
        self.assertEqual(bogus.status_code, 200)
        self.assertEqual([a.pk for a in bogus.context['applications']], [early.pk, late.pk])

    def test_outing_list_query_count_is_constant(self):
        self.client.force_login(self.staff)
        self.outing(self.student, 1)
        for status in ('', '?status=all'):
            with self.subTest(status=status):
                url = reverse('web:outside_manage') + status
                with CaptureQueriesContext(connection) as one:
                    self.client.get(url)
                for day in range(2, 7):
                    self.outing(self.other, day)
                with CaptureQueriesContext(connection) as many:
                    self.client.get(url)
                self.assertEqual(len(one), len(many))
                OutingApply.objects.exclude(user=self.student).delete()

    def test_student_sees_only_own_outings_without_actions(self):
        mine = self.outing(self.student, 1, 'approved')
        theirs = self.outing(self.other, 2, name='김철수')
        self.client.force_login(self.student)
        response = self.client.get(reverse('web:outing_info'))
        self.assertEqual([a.pk for a in response.context['applications']], [mine.pk])
        self.assertNotContains(response, '김철수')
        self.assertNotContains(response, reverse('web:approve_outing', args=[mine.pk]))
        self.assertNotContains(response, reverse('web:reject_outing', args=[theirs.pk]))
        self.assertContains(response, '승인됨')

    def test_student_without_outings_gets_a_link_to_apply(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('web:outing_info'))
        self.assertContains(response, f'href="{reverse("web:outside")}"')

    # 문의 상세
    def test_inquiry_answer_form_has_a_labelled_textarea(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse('web:inquiry_detail', args=[self.inquiry.pk])).content.decode()
        self.assertIn('for="id_answer"', html)
        self.assertRegex(html, r'<textarea[^>]*id="id_answer"')
        self.assertIn('답변 보내기', html)
        self.assertNotIn('onsubmit=', html)

    def test_inquiry_answer_errors_are_shown(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('web:inquiry_detail', args=[self.inquiry.pk]), {'answer': ''})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dg-field__error')
        self.assertContains(response, 'aria-invalid="true"')

    def test_student_sees_answer_but_no_form(self):
        InquiryAnswer.objects.create(inquiry=self.inquiry, admin=self.staff, answer='답변입니다')
        self.client.force_login(self.student)
        response = self.client.get(reverse('web:inquiry_detail', args=[self.inquiry.pk]))
        self.assertContains(response, '답변입니다')
        self.assertNotContains(response, 'name="answer"')
        self.assertNotContains(response, '답변 보내기')

    # 상벌점
    def test_reward_form_is_labelled_with_a_segmented_choice(self):
        self.client.force_login(self.staff)
        html = self.client.get(reverse('web:reward_penalty')).content.decode()
        self.assertIn('for="student_number"', html)
        self.assertIn('for="points"', html)
        self.assertIn('class="dg-choice"', html)
        self.assertRegex(html, r'name="point_type"[^>]*value="reward"[^>]*checked')
        self.assertIn('점수 주기', html)


class SoftAppShellTests(TestCase):
    """부드러운 앱 모양 (docs/adr/0021): 휴대폰 아래 탭 막대와 선 아이콘."""
    TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'web')

    def tabbar(self, url):
        html = self.client.get(url).content.decode()
        match = re.search(r'<nav class="dg-tabbar"[^>]*>(.*?)</nav>', html, re.S)
        self.assertIsNotNone(match, url)
        return match.group(1)

    def current_tabs(self, url):
        return re.findall(r'aria-current="page">.*?<span>([^<]+)</span>', self.tabbar(url), re.S)

    def test_student_tabbar_marks_the_current_section(self):
        self.client.force_login(User.objects.create_user('20250001', password='pw12345!'))
        self.assertEqual(self.current_tabs(reverse('web:home')), ['홈'])
        self.assertEqual(self.current_tabs(reverse('web:outside')), ['신청'])
        self.assertEqual(self.current_tabs(reverse('web:community_home')), ['게시판'])
        self.assertEqual(self.current_tabs(reverse('web:mypage')), ['마이'])
        with mock.patch('web.views.start_warm_up'):
            self.assertEqual(self.current_tabs(reverse('web:chatbot')), ['챗봇'])
        self.assertNotIn('관리', self.tabbar(reverse('web:home')))

    def test_staff_tabbar_has_the_staff_section_instead_of_requests(self):
        self.client.force_login(User.objects.create_user('admin', password='pw12345!', is_staff=True))
        bar = self.tabbar(reverse('web:dorminfo'))
        self.assertIn(f'href="{reverse("web:outside_manage")}"', bar)
        self.assertNotIn(f'href="{reverse("web:outside")}"', bar)
        self.assertEqual(self.current_tabs(reverse('web:dorminfo')), ['관리'])
        self.assertEqual(self.current_tabs(reverse('web:reward_penalty')), ['관리'])

    def test_every_icon_used_in_templates_draws_something(self):
        """아이콘 이름을 잘못 쓰면 빈 <svg>가 조용히 그려진다. 템플릿이 쓰는 이름마다 그림이 있는지 확인한다."""
        from django.template.loader import render_to_string
        names = set()
        for filename in os.listdir(self.TEMPLATE_DIR):
            with open(os.path.join(self.TEMPLATE_DIR, filename), encoding='utf-8') as f:
                names.update(re.findall(r"_icon\.html' with name='([a-z]+)'", f.read()))
        self.assertGreater(len(names), 20)
        for name in sorted(names):
            with self.subTest(icon=name):
                svg = render_to_string('web/_icon.html', {'name': name})
                self.assertRegex(svg, r'<svg class="dg-icon"[^>]*>.*<path d="[^"]+"', name)
        self.assertNotIn('<path', render_to_string('web/_icon.html', {'name': 'no-such-icon'}))
