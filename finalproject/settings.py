import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = True

# 비밀 키는 코드에 두지 않고 환경변수 DJANGO_SECRET_KEY에서 읽는다.
# 로컬 개발(DEBUG=True)에서만 개발용 키를 허용하고, 배포(DEBUG=False)에서는 반드시 설정해야 한다.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY 환경변수를 설정해주세요.')
    SECRET_KEY = 'django-insecure-local-development-only'

ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    'drf_spectacular',
    'dorm',
    'web',
    'knowledge',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'finalproject.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [ BASE_DIR / 'templates' ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'finalproject.wsgi.application'

# PostgreSQL + pgvector (ADR 0005). 개발용 DB는 `docker compose up -d db`로 띄운다.
# 접속 정보는 docker-compose.yml과 같은 환경변수를 읽는다. 기본값은 로컬 개발 전용이며,
# DEBUG=False에서는 비밀번호 환경변수가 반드시 있어야 한다.
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', '')
if not POSTGRES_PASSWORD:
    if not DEBUG:
        raise ImproperlyConfigured('POSTGRES_PASSWORD 환경변수를 설정해주세요.')
    POSTGRES_PASSWORD = 'dorm-local-dev'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'dorm'),
        'USER': os.environ.get('POSTGRES_USER', 'dorm'),
        'PASSWORD': POSTGRES_PASSWORD,
        'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
        'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        # DB가 꺼져 있으면 오래 기다리지 않고 바로 안내한다 (dorm/checks.py)
        'OPTIONS': {'connect_timeout': 3},
    }
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'web:login'

CORS_ALLOW_ALL_ORIGINS = True


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# RAG 검색 자료의 임베딩 (knowledge/embeddings.py)
# BACKEND: 'sentence-transformers'(로컬 모델, requirements-ml.txt 필요) 또는 'fake'(테스트·CI용)
KNOWLEDGE_EMBEDDING = {
    'BACKEND': os.environ.get('KNOWLEDGE_EMBEDDING_BACKEND', 'sentence-transformers'),
    'MODEL': os.environ.get('KNOWLEDGE_EMBEDDING_MODEL', 'BAAI/bge-m3'),
}

# RAG 답변 초안을 쓰는 언어 모델 (knowledge/llm.py, ADR 0007)
# BACKEND: 'ollama'(이 PC의 로컬 모델) 또는 'fake'(테스트·CI용)
KNOWLEDGE_LLM = {
    'BACKEND': os.environ.get('KNOWLEDGE_LLM_BACKEND', 'ollama'),
    'MODEL': os.environ.get('KNOWLEDGE_LLM_MODEL', 'exaone3.5:7.8b'),
    'HOST': os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434'),
    # 마지막 요청 뒤 모델을 GPU에 남겨 둘 시간. '30m', '2h', '-1'(계속) 등 (docs/adr/0013)
    'KEEP_ALIVE': os.environ.get('KNOWLEDGE_LLM_KEEP_ALIVE', '30m'),
}

# 챗봇 메시지 종류 판단기 (knowledge/router.py, docs/adr/0014)
# BACKEND: 'jev'(TypeSafe Jev, 외부 API, 실패하면 'llm'), 'llm'(로컬 답변 모델), 'fake'(테스트)
# 키(TYPESAFE_API_KEY)가 없으면 'llm'을 쓴다. 키는 환경변수로만 읽고 저장소에 넣지 않는다.
KNOWLEDGE_ROUTER = {
    'BACKEND': os.environ.get('KNOWLEDGE_ROUTER_BACKEND', 'jev' if os.environ.get('TYPESAFE_API_KEY') else 'llm'),
    'API_KEY': os.environ.get('TYPESAFE_API_KEY', ''),
    'MODEL': os.environ.get('KNOWLEDGE_ROUTER_MODEL', 'jev-1.14.0'),
}

# API 문서 (/api/docs/)
SPECTACULAR_SETTINGS = {
    'TITLE': '돔고돔락 API',
    'DESCRIPTION': '기숙사 통합 관리 시스템의 Android 앱용 REST API. '
                   '로그인 API에서 받은 Token을 `Authorization: Token <token>` 헤더에 넣어 호출한다.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # 문서에 표시할 그룹 순서 (앱에서 쓰는 순서)
    'TAGS': [
        {'name': '인증', 'description': '회원가입, 로그인(Token 발급), 로그아웃'},
        {'name': '마이페이지·상벌점'},
        {'name': '기숙사', 'description': '입실 신청과 방 배정'},
        {'name': '외박', 'description': '외박 신청과 승인'},
        {'name': '공지'},
        {'name': '게시판', 'description': '익명 자유게시판: 글, 댓글, 좋아요'},
        {'name': '문의', 'description': '학생 문의와 관리자 답변'},
    ],
}