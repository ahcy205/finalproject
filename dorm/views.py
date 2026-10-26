from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from rest_framework.authtoken.models import Token
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, parser_classes
)
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from .models import (
    Dorm, OutingApply, Notice, Post,
    UserProfile, Inquiry, InquiryAnswer, Like
)
from .serializers import (
    DormSerializer,
    OutingApplySerializer,
    NoticeSerializer,
    NoticeCreateSerializer,
    PostSerializer,
    CommentSerializer,
    UserProfileSerializer,
    InquirySerializer,
    InquiryCreateSerializer,
    InquiryAnswerSerializer,
    InquiryAnswerCreateSerializer,
)
from .permissions import IsAuthorOrAdmin, IsInquiryUserOrAdmin
from datetime import date


@api_view(['POST'])
@permission_classes([AllowAny])
def signup_api(request):
    username = request.data.get('username')
    password = request.data.get('password')
    email = request.data.get('email')
    department = request.data.get('department', '')
    full_name = request.data.get('full_name', '')

    if not all([username, password, email, full_name]):
        return JsonResponse({'success': False, 'error': 'All fields are required.'}, status=400)

    if User.objects.filter(username=username).exists():
        return JsonResponse({'success': False, 'error': 'Username already exists.'}, status=400)
    if User.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'error': 'Email already registered.'}, status=400)

    # 웹 회원가입과 같은 비밀번호 규칙(AUTH_PASSWORD_VALIDATORS)을 적용한다
    try:
        validate_password(password, user=User(username=username, email=email))
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': ' '.join(e.messages)}, status=400)

    user = User.objects.create_user(username=username, password=password, email=email)
    profile, created = UserProfile.objects.get_or_create(
        user=user,
        defaults={'department': department, 'full_name': full_name}
    )
    if not created:
        profile.department = department
        profile.full_name = full_name
        profile.save()

    return JsonResponse({'success': True, 'user_id': user.id})


@api_view(['POST'])
@permission_classes([AllowAny])
def login_api(request):
    username = request.data.get('username')
    password = request.data.get('password')
    if not all([username, password]):
        return JsonResponse({'success': False, 'error': 'Username and password are required.'}, status=400)
    user = authenticate(username=username, password=password)
    if not user:
        return JsonResponse({'success': False, 'error': 'Invalid username or password.'}, status=400)
    token, _ = Token.objects.get_or_create(user=user)
    return JsonResponse({
        'success': True,
        'user_id': user.id,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
        'token': token.key
    })


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def mypage_api(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)
    dorm = Dorm.objects.filter(user=user).first()
    profile_data = UserProfileSerializer(profile).data
    profile_data['is_staff'] = user.is_staff
    profile_data['is_superuser'] = user.is_superuser
    return JsonResponse({
        'success': True,
        'mypage': {
            'user': profile_data,
            'dorm': DormSerializer(dorm).data if dorm else None
        }
    })


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def give_point_api(request):
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    student_id = request.data.get('student_id')
    point_type = request.data.get('point_type')
    try:
        point = int(request.data.get('point', 0))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Point must be a number.'}, status=400)
    if not all([student_id, point_type]) or point == 0:
        return JsonResponse({'success': False, 'error': 'All fields are required.'}, status=400)
    try:
        target = User.objects.get(username=student_id).userprofile
    except (User.DoesNotExist, UserProfile.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'User not found.'}, status=404)
    if point_type == 'reward':
        target.reward_point += point
    elif point_type == 'penalty':
        target.penalty_point += point
    else:
        return JsonResponse({'success': False, 'error': 'Invalid point_type.'}, status=400)
    target.save()
    return JsonResponse({'success': True, 'profile': UserProfileSerializer(target).data})


@api_view(['GET', 'POST'])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def notices_api(request):
    if request.method == 'GET':
        notices = Notice.objects.order_by('-date')
        data = NoticeSerializer(notices, many=True, context={'request': request}).data
        return JsonResponse({'success': True, 'notices': data})
    auth = TokenAuthentication()
    auth_result = auth.authenticate(request)
    if not auth_result:
        return JsonResponse({'success': False, 'error': 'Authentication required.'}, status=401)
    user, _ = auth_result
    if not user.is_staff:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    serializer = NoticeCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return JsonResponse({'success': False, 'error': serializer.errors}, status=400)
    notice = serializer.save()
    return JsonResponse({'success': True, 'notice': NoticeSerializer(notice, context={'request': request}).data})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def apply_dorm_api(request):
    user = request.user
    name = request.data.get('name')
    stud = request.data.get('student_number')
    gender = request.data.get('gender')
    content = request.data.get('content', '')
    if not all([name, stud, gender]):
        return JsonResponse(
            {'success': False, 'error': 'Name, student number and gender are required.'},
            status=400
        )
    if Dorm.objects.filter(user=user).exists():
        return JsonResponse({'success': False, 'error': 'Dorm application already exists.'}, status=400)
    if len(stud) > 10:
        return JsonResponse({'success': False, 'error': 'Student number must be 10 characters or fewer.'}, status=400)
    if Dorm.objects.filter(student_number=stud).exists():
        return JsonResponse({'success': False, 'error': 'Student number already registered.'}, status=400)

    dorm = Dorm.objects.create(
        user=user,
        name=name,
        student_number=stud,
        gender=gender,
        content=content
    )

    return JsonResponse({'success': True, 'dorm': DormSerializer(dorm).data})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def apply_outing_api(request):
    name = request.data.get('name')
    stud = request.data.get('student_number')
    outdate = request.data.get('out_date')
    if not all([name, stud, outdate]):
        return JsonResponse(
            {'success': False, 'error': 'Name, student number, and outing date are required.'},
            status=400
        )
    try:
        outdate = date.fromisoformat(str(outdate))
    except ValueError:
        return JsonResponse({'success': False, 'error': 'out_date must be YYYY-MM-DD.'}, status=400)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if name.strip() != profile.full_name.strip() or stud.strip() != request.user.username.strip():
        return JsonResponse(
            {'success': False, 'error': 'Name or student number does not match the logged-in user.'},
            status=403
        )
    outing = OutingApply.objects.create(
        user=request.user,
        name=name,
        student_number=stud,
        out_date=outdate
    )
    return JsonResponse({'success': True, 'outing': OutingApplySerializer(outing).data})


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def outing_apply_status_api(request):
    user = request.user
    if user.is_staff:
        applies = OutingApply.objects.all().order_by('-applied_at')
    else:
        applies = OutingApply.objects.filter(user=user).order_by('-applied_at')
    serializer = OutingApplySerializer(applies, many=True)
    return JsonResponse({'success': True, 'list': serializer.data})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def approve_outing_api(request, pk):
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    try:
        outing = OutingApply.objects.get(pk=pk)
    except OutingApply.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Not found.'}, status=404)
    outing.status = 'approved'
    outing.save()
    return JsonResponse({'success': True, 'outing': OutingApplySerializer(outing).data})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def reject_outing_api(request, pk):
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    try:
        outing = OutingApply.objects.get(pk=pk)
    except OutingApply.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Not found.'}, status=404)
    outing.status = 'rejected'
    outing.save()
    return JsonResponse({'success': True})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedOrReadOnly])
@parser_classes([MultiPartParser, FormParser])
def posts_api(request):
    if request.method == 'GET':
        qs = Post.objects.order_by('-created_at')
        return Response({
            'success': True,
            'posts': PostSerializer(qs, many=True, context={'request': request}).data
        })
    serializer = PostSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response({'success': True, 'post': serializer.data})


@api_view(['GET', 'PUT', 'DELETE'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthorOrAdmin])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def post_detail_api(request, pk):
    try:
        post = Post.objects.get(pk=pk)
    except Post.DoesNotExist:
        return Response({'success': False, 'error': 'Not found'}, status=404)

    perm = IsAuthorOrAdmin()
    if not perm.has_object_permission(request, None, post):
        return Response({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method == 'GET':
        return Response({'success': True, 'post': PostSerializer(post, context={'request': request}).data})
    if request.method == 'PUT':
        serializer = PostSerializer(post, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'success': True, 'post': serializer.data})
    post.delete()
    return Response({'success': True})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticatedOrReadOnly])
@parser_classes([JSONParser])
def comments_api(request, post_id):
    try:
        post = Post.objects.get(pk=post_id)
    except Post.DoesNotExist:
        return Response({'success': False, 'error': 'Post not found'}, status=404)
    if request.method == 'GET':
        qs = post.comments.order_by('created_at')
        return Response(
            {'success': True, 'comments': CommentSerializer(qs, many=True, context={'request': request}).data})
    serializer = CommentSerializer(data={'content': request.data.get('content')}, context={'request': request})
    serializer.is_valid(raise_exception=True)
    serializer.save(post=post)
    return Response({'success': True, 'comment': serializer.data})


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def inquiries_api(request):
    user = request.user
    if request.method == 'GET':
        qs = Inquiry.objects.order_by('-created_at') if user.is_staff else Inquiry.objects.filter(user=user).order_by(
            '-created_at')
        return Response({'success': True, 'inquiries': InquirySerializer(qs, many=True).data})
    serializer = InquiryCreateSerializer(data=request.data)
    if serializer.is_valid():
        inquiry = serializer.save(user=user)
        return Response({'success': True, 'inquiry': InquirySerializer(inquiry).data})
    return Response({'success': False, 'error': serializer.errors}, status=400)


@api_view(['GET', 'POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated, IsInquiryUserOrAdmin])
def inquiry_detail_api(request, pk):
    try:
        inquiry = Inquiry.objects.get(pk=pk)
    except Inquiry.DoesNotExist:
        return Response({'success': False, 'error': 'Not found'}, status=404)

    perm = IsInquiryUserOrAdmin()
    if request.method == 'GET' and not perm.has_object_permission(request, None, inquiry):
        return Response({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method == 'POST' and not request.user.is_staff:
        return Response({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method == 'GET':
        return Response({'success': True, 'inquiry': InquirySerializer(inquiry).data})

    serializer = InquiryAnswerCreateSerializer(data=request.data)
    if serializer.is_valid():
        answer, created = InquiryAnswer.objects.get_or_create(
            inquiry=inquiry,
            defaults={'admin': request.user, 'answer': serializer.validated_data['answer']}
        )
        if not created:
            answer.answer = serializer.validated_data['answer']
            answer.save()
        return Response({'success': True, 'answer': InquiryAnswerSerializer(answer).data})
    return Response({'success': False, 'error': serializer.errors}, status=400)


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def dorm_applications_list_api(request):
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    dorms = Dorm.objects.all().order_by('-id')
    data = DormSerializer(dorms, many=True).data
    return JsonResponse({'success': True, 'dorms': data})


@api_view(['GET', 'PATCH', 'DELETE'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def dorm_application_detail_api(request, pk):
    try:
        dorm = Dorm.objects.get(pk=pk)
    except Dorm.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Dorm application not found.'}, status=404)

    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method == 'GET':
        return JsonResponse({'success': True, 'application': DormSerializer(dorm).data})

    elif request.method == 'PATCH':
        building = request.data.get('building_name')
        room = request.data.get('r_number')
        position = request.data.get('position')

        updated = False

        if building is not None:
            dorm.building_name = building
            updated = True

        if room is not None:
            try:
                dorm.r_number = int(room)
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Invalid room number'}, status=400)
            updated = True

        if position is not None:
            try:
                dorm.position = int(position)
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Invalid position'}, status=400)
            updated = True

        if updated:
            dorm.save()
            return JsonResponse({'success': True, 'application': DormSerializer(dorm).data})
        else:
            return JsonResponse({'success': False, 'error': 'No fields to update.'}, status=400)

    elif request.method == 'DELETE':
        dorm.delete()
        return JsonResponse({'success': True, 'message': 'Dorm application deleted.'})


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def like_post_api(request, pk):
    try:
        post = Post.objects.get(pk=pk)
    except Post.DoesNotExist:
        return Response({'success': False, 'error': 'Post not found'}, status=404)
    user = request.user
    like_obj, created = Like.objects.get_or_create(user=user, post=post)
    if not created:
        like_obj.delete()
        return Response({'is_liked': False, 'like_count': post.likes.count()})
    return Response({'is_liked': True, 'like_count': post.likes.count()})