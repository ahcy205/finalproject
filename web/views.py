from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout, login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from dorm.models import Notice, UserProfile, Post, Comment, Inquiry, InquiryAnswer, Dorm, OutingApply, Like
from django.utils import timezone
from django.shortcuts import get_object_or_404

from web.forms import CustomSignupForm, CommentForm, PostForm, InquiryForm, InquiryAnswerForm, OutingApplyForm, \
    NoticeForm


def index(request):
    return render(request, 'web/index.html')

def guide(request):
    return render(request, 'web/guide.html')

def community(request):
    return render(request, 'web/community.html')

@login_required
def mypage_view(request):
    user = request.user
    is_admin = user.is_staff or user.is_superuser

    dorm = Dorm.objects.filter(user=user).first()
    inquiries = Inquiry.objects.filter(user=user).order_by('-created_at')
    if is_admin:
        inquiries = Inquiry.objects.all().order_by('-created_at')

    if request.method == 'POST' and 'submit_inquiry' in request.POST and not is_admin:
        form = InquiryForm(request.POST)
        if form.is_valid():
            inquiry = form.save(commit=False)
            inquiry.user = user
            inquiry.save()
            return redirect(reverse('web:mypage') + '?tab=inquiry')
    else:
        form = InquiryForm()
    students = []

    if is_admin and 'query' in request.GET and 'field' in request.GET:
        query = request.GET.get('query', '').strip()
        field = request.GET.get('field', '').strip()

        if query and field:
            if field == 'gender':
                gender_map = {'남자': 'male', '여자': 'female'}
                gender_value = gender_map.get(query)
                if gender_value:
                    dorm_user_ids = Dorm.objects.filter(gender=gender_value).values_list('user_id', flat=True)
                    students = UserProfile.objects.filter(user_id__in=dorm_user_ids).order_by('full_name')
                else:
                    students = UserProfile.objects.none()

            elif field == 'building_name':
                dorm_user_ids = Dorm.objects.filter(building_name__icontains=query).values_list('user_id', flat=True)
                students = UserProfile.objects.filter(user_id__in=dorm_user_ids).order_by('full_name')

            elif field == 'r_number':
                dorm_user_ids = Dorm.objects.filter(r_number__icontains=query).values_list('user_id', flat=True)
                students = UserProfile.objects.filter(user_id__in=dorm_user_ids).order_by('full_name')

            elif field == 'student_number':
                students = UserProfile.objects.filter(user__username__icontains=query).order_by('full_name')

            elif field == 'phone_number':
                students = UserProfile.objects.filter(phone_number__icontains=query).select_related('user').order_by('full_name')

            elif field == 'reward_point':
                students = UserProfile.objects.filter(reward_point__icontains=query).select_related('user').order_by('full_name')

            elif field == 'penalty_point':
                students = UserProfile.objects.filter(penalty_point__icontains=query).select_related('user').order_by('full_name')

            else:
                filter_kwargs = {f"{field}__icontains": query}
                students = UserProfile.objects.filter(**filter_kwargs).order_by('full_name')

    context = {
        'user': user,
        'is_admin': is_admin,
        'dorm': dorm,
        'inquiries': inquiries,
        'form': form,
        'students': students,
    }
    return render(request, 'web/mypage.html', context)


@login_required
def inquiry_detail_view(request, pk):
    inquiry = get_object_or_404(Inquiry, pk=pk)
    user = request.user
    is_admin = user.is_superuser

    try:
        answer_instance = InquiryAnswer.objects.get(inquiry=inquiry)
    except InquiryAnswer.DoesNotExist:
        answer_instance = None

    if request.method == 'POST' and is_admin:
        form = InquiryAnswerForm(request.POST, instance=answer_instance)
        if form.is_valid():
            answer = form.save(commit=False)
            answer.inquiry = inquiry
            answer.admin = user
            answer.save()
            return redirect('web:inquiry_detail', pk=pk)
    else:
        form = InquiryAnswerForm(instance=answer_instance)

    if not is_admin and inquiry.user != user:
        return redirect('web:mypage')

    context = {
        'inquiry': inquiry,
        'form': form,
        'is_admin': is_admin,
    }
    return render(request, 'web/inquiry_detail.html', context)


def notice_list(request):
    kw = request.GET.get('kw', '')
    notices = Notice.objects.all()
    if kw:
        notices = notices.filter(title__icontains=kw)
    notices = notices.order_by('-id')

    paginator = Paginator(notices, 10)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)

    return render(request, 'web/notice.html', {
        'notices': page_obj,
        'page_obj': page_obj,
        'kw': kw,
    })

@login_required
@user_passes_test(lambda u: u.is_staff)
def notice_create(request):
    if request.method == "POST":
        form = NoticeForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('web:notice')
    else:
        form = NoticeForm()
    return render(request, 'web/notice_create.html', {'form': form})


@login_required
@user_passes_test(lambda u: u.is_staff)
def notice_delete(request, pk):
    notice = get_object_or_404(Notice, pk=pk)

    if request.method == "POST":
        notice.delete()
        return redirect('web:notice')

    return render(request, 'web/notice_confirm_delete.html', {'notice': notice})

@login_required
def notice_detail(request, pk):
    notice = get_object_or_404(Notice, pk=pk)
    return render(request, 'web/notice_detail.html', {'notice': notice})

@login_required
@user_passes_test(lambda u: u.is_staff)
def notice_update(request, notice_id):
    notice = get_object_or_404(Notice, pk=notice_id)

    if request.method == "POST":
        # NoticeForm의 ImageField가 실제 이미지 파일인지 검사한다
        form = NoticeForm(request.POST, request.FILES, instance=notice)
        if form.is_valid():
            form.save()
            return redirect('web:notice_detail', pk=notice.pk)

        if 'image' in form.errors:
            error = '이미지 파일(jpg, png 등)만 올릴 수 있습니다.'
        else:
            error = '제목과 내용을 모두 입력해주세요.'
        # 검증 실패 시 form이 바꿔 둔 값 대신 저장된 원래 공지를 다시 보여준다
        notice.refresh_from_db()
        return render(request, 'web/notice_update.html', {'notice': notice, 'error': error})

    return render(request, 'web/notice_update.html', {'notice': notice})




def menu(request):
    return render(request, 'web/menu.html')

@login_required
def check_in(request):
    if request.user.is_staff:
        return redirect('web:dorminfo')

    if request.method == 'POST':
        name = request.POST.get('name')
        student_number = request.POST.get('student_number')
        gender = request.POST.get('gender')
        content = request.POST.get('content')

        if not all([name, student_number, gender]):
            messages.error(request, '필수 항목을 모두 입력해주세요.')
            return render(request, 'web/check_in.html')

        if Dorm.objects.filter(user=request.user).exists():
            messages.error(request, '이미 신청한 기록이 있습니다.')
            return render(request, 'web/check_in.html')

        Dorm.objects.create(
            user=request.user,
            name=name,
            student_number=student_number,
            gender=gender,
            content=content
        )
        messages.success(request, '기숙사 신청이 완료되었습니다.')
        return redirect('web:home')

    return render(request, 'web/check_in.html')


@login_required
def outside(request):
    if request.user.is_staff:
        return redirect('web:outside_manage')

    if request.method == 'POST':
        form = OutingApplyForm(request.POST)
        if form.is_valid():
            form.save()
            request.session['show_success_alert'] = True
            return redirect('web:apply_success')
    else:
        form = OutingApplyForm()

    return render(request, 'web/outside.html', {'form': form})


def apply_success(request):
    show_alert = False
    if 'show_success_alert' in request.session:
        show_alert = request.session['show_success_alert']
        del request.session['show_success_alert']

    return render(request, 'web/apply_success.html', {'show_alert': show_alert})

@login_required
def outing_info(request):
    if request.user.is_staff:
        applications = OutingApply.objects.all()
    else:
        applications = OutingApply.objects.filter(
            name=request.user.userprofile.full_name,
            student_number=request.user.username
        )
    return render(request, 'web/outinfo.html', {
        'applications': applications,
        'is_admin': request.user.is_staff
    })


@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def approve_outing(request, pk):
    outing = get_object_or_404(OutingApply, pk=pk)
    outing.status = 'approved'
    outing.save()
    return redirect('web:outing_info')


@require_POST
@login_required
@user_passes_test(lambda u: u.is_staff)
def reject_outing(request, pk):
    outing = get_object_or_404(OutingApply, pk=pk)
    outing.status = 'rejected'
    outing.save()
    return redirect('web:outing_info')


def community_home(request):
    kw = request.GET.get('kw', '')
    post_list = Post.objects.all().order_by('-created_at')

    if kw:
        post_list = post_list.filter(title__icontains=kw)

    paginator = Paginator(post_list, 10)  # 10개씩 페이징
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)

    return render(request, 'web/community_home.html', {
        'posts': page_obj,
        'page_obj': page_obj,
        'kw': kw
    })

@login_required
def community_create(request):
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, '게시글이 성공적으로 작성되었습니다.')
            return redirect('web:community_detail', pk=post.pk)
        else:
            messages.error(request, '게시글 작성에 실패했습니다. 다시 시도해주세요.')
    else:
        form = PostForm()

    return render(request, 'web/community_create.html', {'form': form})


@login_required
def community_delete(request, pk):
    post = get_object_or_404(Post, pk=pk)

    if request.user != post.author and not request.user.is_staff:
        return redirect('web:community_home')

    if request.method == "POST":
        post.delete()
        return redirect('web:community_home')

    return render(request, 'web/community_confirm_delete.html', {'post': post})


@login_required
def community_detail(request, pk):
    post = get_object_or_404(Post, pk=pk)
    comments = Comment.objects.filter(post=post).order_by('created_at')
    comment_form = CommentForm()

    context = {
        'post': post,
        'comments': comments,
        'comment_form': comment_form,
    }
    return render(request, 'web/community_detail.html', context)

@login_required
def add_comment(request, pk):
    post = get_object_or_404(Post, pk=pk)

    if request.method == 'POST':
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.post = post
            comment.author = request.user
            comment.save()
        else:
            messages.error(request, '댓글 등록에 실패했습니다.')

    return redirect('web:community_detail', pk=pk)

@require_POST
@login_required
def delete_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)
    post_pk = comment.post.pk

    if comment.author == request.user or request.user.is_staff:
        comment.delete()
        messages.success(request, '댓글이 삭제되었습니다.')
    else:
        messages.error(request, '댓글을 삭제할 권한이 없습니다.')

    return redirect('web:community_detail', pk=post_pk)


@login_required
def community_update(request, post_id):
    post = get_object_or_404(Post, pk=post_id)

    if request.user != post.author and not request.user.is_staff:
        return redirect('web:community_home')

    if request.method == "POST":
        form = PostForm(request.POST, request.FILES, instance=post)  # request.FILES 추가
        if form.is_valid():
            form.save()
            messages.success(request, '게시글이 성공적으로 수정되었습니다.')
            return redirect('web:community_detail', pk=post.id)
        else:
            messages.error(request, '게시글 수정에 실패했습니다. 다시 시도해주세요.')
    else:
        form = PostForm(instance=post)

    return render(request, 'web/community_update.html', {'post': post})

def bus(request):
    return render(request, 'web/bus.html')

def acc(request):
    return render(request, 'web/acc.html')

def info(request):
    return render(request, 'web/info.html')

def rules(request):
    return render(request, 'web/rules.html')


def signup_views(request):
    if request.method == 'POST':
        form = CustomSignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data.get('email')
            user.save()

            full_name = form.cleaned_data.get('full_name')
            department = form.cleaned_data.get('department')
            phone_number = form.cleaned_data.get('phone_number')

            UserProfile.objects.update_or_create(
                user=user,
                defaults={'full_name': full_name, 'department': department, 'phone_number': phone_number}
            )

            return redirect('web:login')
        else:
            # form.errors를 템플릿으로 넘겨줌
            return render(request, 'web/signup.html', {'form': form, 'form_errors': form.errors})
    else:
        form = CustomSignupForm()
    return render(request, 'web/signup.html', {'form': form})


def login_views(request):
    next_url = request.POST.get('next') or request.GET.get('next', '')

    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # 같은 사이트 주소일 때만 이동 (외부 사이트로의 리다이렉트 방지)
            if url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(next_url)
            return redirect('web:home')
        else:
            messages.error(request, "아이디 또는 비밀번호가 올바르지 않습니다.")
            return render(request, 'web/login.html', {'username': username, 'next': next_url})

    else:
        return render(request, 'web/login.html', {'next': next_url})


@require_POST
def logout_views(request):
    logout(request)
    return redirect('web:home')


@login_required
@user_passes_test(lambda u: u.is_staff)
def reward_penalty(request):
    if request.method == 'POST':
        student_number = request.POST.get('student_number')
        point_type = request.POST.get('point_type')
        try:
            points = int(request.POST.get('points', 0))
        except (TypeError, ValueError):
            messages.error(request, "점수는 숫자로 입력해주세요.")
            return redirect('web:reward_penalty')

        if point_type not in ('reward', 'penalty'):
            messages.error(request, "상점 또는 벌점을 선택해주세요.")
            return redirect('web:reward_penalty')

        try:
            user = User.objects.get(username=student_number)
            profile = user.userprofile
            if point_type == 'reward':
                profile.reward_point += points
            else:
                profile.penalty_point += points
            profile.save()
            messages.success(request, f"{user.username} 학생에게 {points}점 부여 완료!")
        except User.DoesNotExist:
            messages.error(request, "해당 학번의 사용자를 찾을 수 없습니다.")

        return redirect('web:reward_penalty')

    return render(request, 'web/reward_penalty.html')


@require_POST
@login_required
def toggle_like(request, pk):
    post = get_object_or_404(Post, pk=pk)
    like, created = Like.objects.get_or_create(user=request.user, post=post)

    if not created:
        like.delete()
    return redirect('web:community_detail', pk=pk)

@require_POST
@user_passes_test(lambda u: u.is_staff)
def assign_room(request, dorm_id):
    dorm = get_object_or_404(Dorm, id=dorm_id)
    dorm.building_name = request.POST.get('building_name')
    dorm.r_number = request.POST.get('r_number')
    dorm.position = request.POST.get('position')
    dorm.save()
    return redirect('web:dorm_info')

@login_required
def dorm_info_view(request):
    is_admin = request.user.is_staff
    if is_admin:
        dorms = Dorm.objects.all()
    else:
        dorms = Dorm.objects.filter(user=request.user)
    return render(request, 'web/dorminfo.html', {'dorms': dorms, 'is_admin': is_admin})


@login_required
def apply_outing(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        student_number = request.POST.get('student_number', '').strip()

        user_name = request.user.userprofile.full_name.strip()
        user_number = request.user.username.strip()

        if name != user_name or student_number != user_number:
            messages.error(request, "제출한 이름 또는 학번이 로그인 정보와 일치하지 않습니다.")
            return redirect('web:outside')
        OutingApply.objects.create(
            name=name,
            student_number=student_number,
            out_date=request.POST.get('out_date'),
            applied_at=timezone.now()
        )

        return redirect('web:apply_success')

    return render(request, 'web/outside.html')

@login_required
def dorm_info_view(request):
    is_admin = request.user.is_staff
    if is_admin:
        dorms = Dorm.objects.all()
    else:
        dorms = Dorm.objects.filter(user=request.user)
    return render(request, 'web/dorminfo.html', {'dorms': dorms, 'is_admin': is_admin})


@require_POST
@user_passes_test(lambda u: u.is_staff)
def assign_room(request, dorm_id):
    dorm = get_object_or_404(Dorm, id=dorm_id)
    dorm.building_name = request.POST.get('building_name')
    dorm.r_number = request.POST.get('r_number')
    dorm.position = request.POST.get('position')
    dorm.save()
    return redirect('web:dorm_info')