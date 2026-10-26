"""화면 스냅샷: 모든 웹 화면과 주요 API 응답을 비로그인·학생·관리자로 렌더링해 폴더에 저장한다.

수정 전과 수정 후에 각각 실행한 뒤 compare_snapshots.py로 비교한다. 사용법은 tools/README.md 참고.

    python tools/snapshot.py tools/snapshots/before

임시 테스트 DB에 고정된 예시 데이터를 만들어 쓰므로 실제 db.sqlite3는 바뀌지 않고,
같은 코드라면 몇 번을 실행해도 결과가 똑같다.
"""
import argparse
import logging
import os
import re
import sys
from datetime import date, datetime, timezone as dt_tz

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finalproject.settings')

import django  # noqa: E402

django.setup()

from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402

FIXED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt_tz.utc)
CSRF = re.compile(r'(name="csrfmiddlewaretoken" value=")[^"]+(")')


def seed():
    """화면마다 내용이 보이도록 예시 데이터를 만든다. 날짜는 고정해서 실행할 때마다 같은 결과가 나오게 한다."""
    from django.contrib.auth.models import User
    from dorm.models import Comment, Dorm, Inquiry, InquiryAnswer, Like, Notice, OutingApply, Post

    staff = User.objects.create_user('admin', password='pw12345!', is_staff=True, is_superuser=True)
    student = User.objects.create_user('20250001', password='pw12345!', email='s@example.com')
    profile = student.userprofile
    profile.full_name, profile.department, profile.phone_number = '홍길동', '컴퓨터공학과', '010-0000-0000'
    profile.save()

    Dorm.objects.create(user=student, name='홍길동', student_number='20250001', gender='male',
                        building_name='A동', r_number=101, position=1, content='신청 내용')
    OutingApply.objects.create(user=student, name='홍길동', student_number='20250001', out_date=date(2026, 1, 3))
    OutingApply.objects.update(applied_at=FIXED)

    notice = Notice.objects.create(title='공지 제목', content='공지 내용')
    Notice.objects.update(date=date(2026, 1, 2))

    post = Post.objects.create(author=student, title='글 제목', content='글 내용')
    post2 = Post.objects.create(author=staff, title='두 번째 글', content='내용')
    for author, text in [(staff, '댓글'), (student, '댓글 2'), (staff, '댓글 3')]:
        Comment.objects.create(post=post, author=author, content=text)
    Comment.objects.create(post=post2, author=student, content='다른 글 댓글')
    for target, user in [(post, student), (post, staff), (post2, student)]:
        Like.objects.create(post=target, user=user)
    Post.objects.update(created_at=FIXED, updated_at=FIXED)
    Post.objects.filter(pk=post2.pk).update(created_at=datetime(2026, 1, 3, 3, 4, 5, tzinfo=dt_tz.utc))
    Comment.objects.update(created_at=FIXED)

    inquiry = Inquiry.objects.create(user=student, title='문의 제목', content='문의 내용')
    InquiryAnswer.objects.create(inquiry=inquiry, admin=staff, answer='답변')
    Inquiry.objects.update(created_at=FIXED)
    InquiryAnswer.objects.update(answered_at=FIXED)
    return {'staff': staff, 'student': student, 'notice': notice, 'post': post, 'inquiry': inquiry}


def pages(d):
    return [
        '/', '/guide/', '/community/', '/mypage/', f'/inquiry/{d["inquiry"].pk}/', '/signup/', '/dorminfo/',
        '/login/', '/notice/', '/notice_create/', f'/notice/delete/{d["notice"].pk}/', f'/notice/{d["notice"].pk}/',
        f'/notice/{d["notice"].pk}/edit/', '/menu/', '/check_in/', '/outside/', '/outside/manage/',
        '/community_home/', f'/post/{d["post"].pk}/', '/post/create/', f'/post/{d["post"].pk}/delete/',
        f'/post/{d["post"].pk}/edit/', '/bus/', '/acc/', '/info/', '/rules/', '/apply_success/', '/outinfo/',
        '/reward/', '/mypage/?field=full_name&query=홍', '/chatbot/',
        '/api/posts/', f'/api/posts/{d["post"].pk}/', f'/api/posts/{d["post"].pk}/comments/',
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out_dir', help='스냅샷을 저장할 폴더 (예: tools/snapshots/before)')
    out = os.path.abspath(parser.parse_args().out_dir)

    logging.disable(logging.CRITICAL)
    setup_test_environment()
    runner = DiscoverRunner(verbosity=0)
    old_config = runner.setup_databases()
    try:
        from django.test import Client
        data = seed()
        os.makedirs(out, exist_ok=True)
        count = 0
        for who, user in [('anon', None), ('student', data['student']), ('staff', data['staff'])]:
            client = Client()
            if user:
                client.force_login(user)
            for url in pages(data):
                response = client.get(url)
                body = response.content.decode('utf-8', 'replace') if response.status_code == 200 else ''
                body = CSRF.sub(r'\1CSRF\2', body)
                name = f"{who}__{re.sub(r'[^A-Za-z0-9]+', '_', url).strip('_') or 'home'}.html"
                with open(os.path.join(out, name), 'w', encoding='utf-8', newline='\n') as f:
                    f.write(f'<!-- status {response.status_code} {response.get("Location", "")} -->\n{body}')
                count += 1
        print(f'{count}개 화면을 저장했습니다: {out}')
    finally:
        runner.teardown_databases(old_config)


if __name__ == '__main__':
    main()
