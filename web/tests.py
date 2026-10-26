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
from django.db import connection
from django.test.utils import CaptureQueriesContext

from dorm.models import Comment, Dorm, Inquiry, InquiryAnswer, Like, Notice, OutingApply, Post


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
    """테마 CSS·JS는 _theme_css.html / _theme_js.html 에서 한 번씩만 로드된다."""

    def test_theme_css_and_js_load_once(self):
        response = self.client.get(reverse('web:guide'))
        self.assertContains(response, 'css/style.css', count=1)
        self.assertContains(response, 'js/main.js', count=1)
        self.assertNotContains(response, 'bootstrap@5.3.0')

    def test_bootstrap5_option_keeps_css_order(self):
        self.client.force_login(User.objects.create_user('20250001', password='pw12345!'))
        html = self.client.get(reverse('web:community_home')).content.decode()
        order = [html.index(x) for x in ('bootstrap@5.3.0', 'font-awesome/6.0.0', '/static/css/bootstrap.css',
                                         '/static/css/style.css')]
        self.assertEqual(order, sorted(order))


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
