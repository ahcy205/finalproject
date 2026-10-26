"""API 문서(OpenAPI / Swagger)용 설명.

API 뷰는 JsonResponse를 직접 돌려주기 때문에 drf-spectacular가 요청·응답 형식을 스스로 알 수 없다.
여기에 엔드포인트별 요청 필드, 응답 형식, 권한을 적고 views.py에서 데코레이터로 붙인다.
API 동작에는 영향을 주지 않는다.
"""
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers

from .serializers import (
    CommentSerializer,
    DormSerializer,
    InquiryAnswerSerializer,
    InquirySerializer,
    NoticeSerializer,
    OutingApplySerializer,
    PostSerializer,
    UserProfileSerializer,
)

AUTH, MYPAGE, DORM, OUTING, NOTICE, BOARD, INQUIRY = '인증', '마이페이지·상벌점', '기숙사', '외박', '공지', '게시판', '문의'


def ok(name, /, **fields):
    """{"success": true, ...} 형태의 응답."""
    return inline_serializer(name=name, fields={'success': serializers.BooleanField(default=True), **fields})


ERROR_RESPONSE = inline_serializer(name='ErrorResponse', fields={
    'success': serializers.BooleanField(default=False),
    'error': serializers.JSONField(help_text='오류 메시지 (검증 오류는 필드별 목록)'),
})


def error(description):
    return OpenApiResponse(ERROR_RESPONSE, description=description)


def request(name, /, **fields):
    return inline_serializer(name=name, fields=fields)


def stack(*decorators):
    """GET/POST처럼 메서드별 설명을 한 뷰에 함께 붙인다."""
    def apply(view):
        for decorator in reversed(decorators):
            view = decorator(view)
        return view
    return apply


NEED_LOGIN = error('Token이 없거나 잘못됨')
STAFF_ONLY = error('관리자(스태프)만 가능')
NOT_FOUND = error('대상을 찾을 수 없음')
BAD_INPUT = error('입력값 오류')

# ---------------- 인증 ----------------
signup = extend_schema(
    tags=[AUTH], summary='회원가입', auth=[],
    description='웹 회원가입과 같은 비밀번호 규칙(8자 이상, 흔한 비밀번호·숫자만·아이디와 비슷한 비밀번호 금지)을 적용한다.',
    request=request('SignupRequest',
                    username=serializers.CharField(help_text='학번 (로그인 아이디)'),
                    password=serializers.CharField(),
                    email=serializers.EmailField(),
                    full_name=serializers.CharField(),
                    department=serializers.CharField(required=False)),
    responses={200: ok('SignupResponse', user_id=serializers.IntegerField()), 400: BAD_INPUT},
)

login = extend_schema(
    tags=[AUTH], summary='로그인 (Token 발급)', auth=[],
    description='응답의 `token`을 이후 요청 헤더에 `Authorization: Token <token>` 형태로 넣는다.',
    request=request('LoginRequest', username=serializers.CharField(), password=serializers.CharField()),
    responses={200: ok('LoginResponse', user_id=serializers.IntegerField(), is_staff=serializers.BooleanField(),
                       is_superuser=serializers.BooleanField(), token=serializers.CharField()),
               400: error('아이디 또는 비밀번호 오류')},
)

logout = extend_schema(
    tags=[AUTH], summary='로그아웃 (Token 삭제)', request=None,
    description='호출한 사용자의 Token을 삭제한다. 같은 계정으로 로그인한 다른 기기도 함께 로그아웃된다.',
    responses={200: ok('LogoutResponse'), 401: NEED_LOGIN},
)

# ---------------- 마이페이지·상벌점 ----------------
mypage = extend_schema(
    tags=[MYPAGE], summary='내 정보와 기숙사 배정',
    responses={200: ok('MypageResponse', mypage=inline_serializer(name='Mypage', fields={
        'user': UserProfileSerializer(), 'dorm': DormSerializer(allow_null=True)})), 401: NEED_LOGIN},
)

give_point = extend_schema(
    tags=[MYPAGE], summary='상벌점 부여 (관리자)',
    request=request('GivePointRequest',
                    student_id=serializers.CharField(help_text='학생 학번(아이디)'),
                    point_type=serializers.ChoiceField(choices=['reward', 'penalty']),
                    point=serializers.IntegerField(help_text='0이 아닌 정수')),
    responses={200: ok('GivePointResponse', profile=UserProfileSerializer()), 400: BAD_INPUT, 401: NEED_LOGIN,
               403: STAFF_ONLY, 404: error('해당 학번의 사용자 없음')},
)

# ---------------- 기숙사 ----------------
dorm_apply = extend_schema(
    tags=[DORM], summary='입실 신청',
    description='계정마다 한 번만 신청할 수 있고, 이미 등록된 학번이나 10자를 넘는 학번은 거부된다.',
    request=request('DormApplyRequest',
                    name=serializers.CharField(),
                    student_number=serializers.CharField(max_length=10),
                    gender=serializers.ChoiceField(choices=['male', 'female']),
                    content=serializers.CharField(required=False)),
    responses={200: ok('DormApplyResponse', dorm=DormSerializer()), 400: BAD_INPUT, 401: NEED_LOGIN},
)

dorm_list = extend_schema(
    tags=[DORM], summary='입실 신청 목록 (관리자)', operation_id='dorm_applications_list',
    responses={200: ok('DormListResponse', dorms=DormSerializer(many=True)), 401: NEED_LOGIN, 403: STAFF_ONLY},
)

_dorm_one = ok('DormDetailResponse', application=DormSerializer())
dorm_detail = stack(
    extend_schema(methods=['GET'], tags=[DORM], summary='입실 신청 조회 (관리자)',
                  responses={200: _dorm_one, 401: NEED_LOGIN, 403: STAFF_ONLY, 404: NOT_FOUND}),
    extend_schema(methods=['PATCH'], tags=[DORM], summary='방 배정 (관리자)',
                  description='보낸 필드만 바꾼다. position 0은 미배정, 1~4는 침대 번호.',
                  request=request('AssignRoomRequest',
                                  building_name=serializers.CharField(required=False),
                                  r_number=serializers.IntegerField(required=False),
                                  position=serializers.IntegerField(required=False, min_value=0, max_value=4)),
                  responses={200: _dorm_one, 400: BAD_INPUT, 401: NEED_LOGIN, 403: STAFF_ONLY, 404: NOT_FOUND}),
    extend_schema(methods=['DELETE'], tags=[DORM], summary='입실 신청 삭제 (관리자)',
                  responses={200: ok('DormDeleteResponse', message=serializers.CharField()),
                             401: NEED_LOGIN, 403: STAFF_ONLY, 404: NOT_FOUND}),
)

# ---------------- 외박 ----------------
outing_apply = extend_schema(
    tags=[OUTING], summary='외박 신청',
    description='이름·학번이 로그인한 계정과 같아야 한다. 신청은 그 계정에 연결되고 상태는 pending으로 시작한다.',
    request=request('OutingApplyRequest',
                    name=serializers.CharField(),
                    student_number=serializers.CharField(),
                    out_date=serializers.DateField(help_text='YYYY-MM-DD')),
    responses={200: ok('OutingApplyResponse', outing=OutingApplySerializer()), 400: BAD_INPUT, 401: NEED_LOGIN,
               403: error('이름·학번이 로그인 계정과 다름')},
)

outing_status = extend_schema(
    tags=[OUTING], summary='외박 신청 목록',
    description='학생은 자기 신청만, 관리자는 전체를 최신순으로 받는다.',
    responses={200: ok('OutingListResponse', list=OutingApplySerializer(many=True)), 401: NEED_LOGIN},
)

outing_approve = extend_schema(
    tags=[OUTING], summary='외박 승인 (관리자)', request=None,
    responses={200: ok('OutingApproveResponse', outing=OutingApplySerializer()), 401: NEED_LOGIN,
               403: STAFF_ONLY, 404: NOT_FOUND},
)

outing_reject = extend_schema(
    tags=[OUTING], summary='외박 거절 (관리자)', request=None,
    responses={200: ok('OutingRejectResponse'), 401: NEED_LOGIN, 403: STAFF_ONLY, 404: NOT_FOUND},
)

# ---------------- 공지 ----------------
notices = stack(
    extend_schema(methods=['GET'], tags=[NOTICE], summary='공지 목록', auth=[],
                  responses={200: ok('NoticeListResponse', notices=NoticeSerializer(many=True))}),
    extend_schema(methods=['POST'], tags=[NOTICE], summary='공지 작성 (관리자)',
                  request={'multipart/form-data': request('NoticeCreateRequest',
                                                          title=serializers.CharField(),
                                                          content=serializers.CharField(),
                                                          image=serializers.ImageField(required=False))},
                  responses={200: ok('NoticeCreateResponse', notice=NoticeSerializer()), 400: BAD_INPUT,
                             401: NEED_LOGIN, 403: STAFF_ONLY}),
)

# ---------------- 게시판 ----------------
posts = stack(
    extend_schema(methods=['GET'], tags=[BOARD], summary='게시글 목록', auth=[], operation_id='posts_list',
                  description='`page`를 주면 최신 글부터 20개씩, 주지 않으면 전체를 돌려준다.',
                  parameters=[OpenApiParameter('page', int, required=False, description='1부터 시작')],
                  responses={200: ok('PostListResponse', posts=PostSerializer(many=True),
                                     page=serializers.IntegerField(required=False),
                                     total_pages=serializers.IntegerField(required=False),
                                     has_next=serializers.BooleanField(required=False)),
                             400: error('page가 1 이상의 정수가 아님')}),
    extend_schema(methods=['POST'], tags=[BOARD], summary='게시글 작성',
                  request={'multipart/form-data': request('PostCreateRequest',
                                                          title=serializers.CharField(),
                                                          content=serializers.CharField(),
                                                          image=serializers.ImageField(required=False))},
                  responses={200: ok('PostCreateResponse', post=PostSerializer()), 400: BAD_INPUT, 401: NEED_LOGIN}),
)

_post_one = ok('PostDetailResponse', post=PostSerializer())
post_detail = stack(
    extend_schema(methods=['GET'], tags=[BOARD], summary='게시글 조회', auth=[],
                  responses={200: _post_one, 404: NOT_FOUND}),
    extend_schema(methods=['PUT'], tags=[BOARD], summary='게시글 수정 (작성자·관리자)',
                  description='보낸 필드만 바꾼다.',
                  request={'multipart/form-data': request('PostUpdateRequest',
                                                          title=serializers.CharField(required=False),
                                                          content=serializers.CharField(required=False),
                                                          image=serializers.ImageField(required=False))},
                  responses={200: _post_one, 400: BAD_INPUT, 403: error('작성자나 관리자가 아님'), 404: NOT_FOUND}),
    extend_schema(methods=['DELETE'], tags=[BOARD], summary='게시글 삭제 (작성자·관리자)',
                  responses={200: ok('PostDeleteResponse'), 403: error('작성자나 관리자가 아님'), 404: NOT_FOUND}),
)

like_post = extend_schema(
    tags=[BOARD], summary='좋아요 켜기·끄기', request=None,
    description='누를 때마다 좋아요가 켜지고 꺼진다.',
    responses={200: inline_serializer(name='LikeResponse', fields={
        'is_liked': serializers.BooleanField(), 'like_count': serializers.IntegerField()}),
        401: NEED_LOGIN, 404: NOT_FOUND},
)

comments = stack(
    extend_schema(methods=['GET'], tags=[BOARD], summary='댓글 목록', auth=[],
                  responses={200: ok('CommentListResponse', comments=CommentSerializer(many=True)), 404: NOT_FOUND}),
    extend_schema(methods=['POST'], tags=[BOARD], summary='댓글 작성',
                  request=request('CommentCreateRequest', content=serializers.CharField()),
                  responses={200: ok('CommentCreateResponse', comment=CommentSerializer()), 400: BAD_INPUT,
                             401: NEED_LOGIN, 404: NOT_FOUND}),
)

# ---------------- 문의 ----------------
inquiries = stack(
    extend_schema(methods=['GET'], tags=[INQUIRY], summary='문의 목록', operation_id='inquiries_list',
                  description='학생은 자기 문의만, 관리자는 전체를 최신순으로 받는다.',
                  responses={200: ok('InquiryListResponse', inquiries=InquirySerializer(many=True)), 401: NEED_LOGIN}),
    extend_schema(methods=['POST'], tags=[INQUIRY], summary='문의 등록', operation_id='inquiries_create',
                  request=request('InquiryCreateRequest', title=serializers.CharField(), content=serializers.CharField()),
                  responses={200: ok('InquiryCreateResponse', inquiry=InquirySerializer()), 400: BAD_INPUT,
                             401: NEED_LOGIN}),
)

inquiry_detail = stack(
    extend_schema(methods=['GET'], tags=[INQUIRY], summary='문의 조회 (작성자·관리자)',
                  responses={200: ok('InquiryDetailResponse', inquiry=InquirySerializer()), 401: NEED_LOGIN,
                             403: error('작성자나 관리자가 아님'), 404: NOT_FOUND}),
    extend_schema(methods=['POST'], tags=[INQUIRY], summary='답변 작성·수정 (관리자)', operation_id='inquiries_answer',
                  description='이미 답변이 있으면 덮어쓴다.',
                  request=request('InquiryAnswerRequest', answer=serializers.CharField()),
                  responses={200: ok('InquiryAnswerResponse', answer=InquiryAnswerSerializer()),
                             400: BAD_INPUT, 401: NEED_LOGIN, 403: STAFF_ONLY, 404: NOT_FOUND}),
)
