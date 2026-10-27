from django.contrib.postgres.indexes import GinIndex
from django.db import models
from pgvector.django import HnswIndex, VectorField

# 비교 대상 임베딩 모델(bge-m3, KURE-v1, multilingual-e5-large)이 모두 1024차원이다.
EMBEDDING_DIMENSIONS = 1024


class KnowledgeChunk(models.Model):
    """RAG 검색의 단위(청크). 규칙 조항 하나, 공지 하나, 답변된 문의 하나처럼 근거로 보여 줄 수 있는 크기로 나눈다.

    원본은 knowledge/data/*.yaml과 공지·문의 테이블이고, 이 테이블은 그것을 검색하기 좋게 만든 사본이다.
    언제든 `python manage.py build_knowledge_index`로 다시 만들 수 있다.
    """

    class Source(models.TextChoices):
        RULES = 'rules', '생활관 규칙'
        INFO = 'info', '생활관 안내'
        BUS = 'bus', '셔틀버스'
        MENU = 'menu', '식단'
        NOTICE = 'notice', '공지'
        INQUIRY = 'inquiry', '답변된 문의'

    source = models.CharField(max_length=20, choices=Source.choices)
    # 원본 안에서의 위치. 예: 'rules:article:3', 'notice:21'. 다시 색인할 때 같은 청크를 찾는 열쇠
    key = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=200)
    content = models.TextField()
    # 근거로 보여 줄 화면 주소. 비공개 자료(문의)는 비워 둔다
    url = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # title + content의 해시. 내용이 바뀐 청크만 다시 임베딩하는 데 쓴다
    content_hash = models.CharField(max_length=64)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)
    # 어떤 모델로 만든 벡터인지. 모델을 바꾸면 전부 다시 임베딩한다
    embedding_model = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['source', 'key']
        indexes = [
            # 의미 검색: 코사인 거리 기준 근사 최근접 이웃(HNSW)
            HnswIndex(name='knowledge_embedding_hnsw', fields=['embedding'], m=16, ef_construction=64,
                      opclasses=['vector_cosine_ops']),
            # 키워드 검색: 글자 3개 단위 유사도(pg_trgm). 한국어 형태소 분석 없이도 부분 일치를 찾는다
            GinIndex(name='knowledge_content_trgm', fields=['content'], opclasses=['gin_trgm_ops']),
            models.Index(fields=['source'], name='knowledge_source_idx'),
        ]

    def __str__(self):
        return f'[{self.get_source_display()}] {self.title}'

    def embedding_text(self):
        """임베딩할 문장. 제목에 조항 번호·공지 제목 같은 핵심 단어가 있어 함께 넣는다."""
        return f'{self.title}\n{self.content}'


class ChatLog(models.Model):
    """학생 챗봇 대화 기록 (docs/adr/0012). 못 답한 질문을 찾아 자료를 보강하는 데만 쓴다.

    - 누가 물었는지 저장하지 않는다(사용자·IP 없음). 질문은 개인정보를 가린 뒤 저장한다.
    - 👍/👎는 답을 받은 사람만 한 번 줄 수 있다. 답과 함께 준 일회용 키를 해시로만 저장해 확인한다.
    - RETENTION_DAYS(180일)가 지나면 `python manage.py purge_chat_logs`로 지운다.
    """

    class Channel(models.TextChoices):
        WEB = 'web', '웹'
        API = 'api', '앱'

    class Feedback(models.TextChoices):
        UP = 'up', '👍'
        DOWN = 'down', '👎'

    class Reason(models.TextChoices):
        WRONG = 'wrong', '틀림'
        IRRELEVANT = 'irrelevant', '질문과 관계없음'
        INSUFFICIENT = 'insufficient', '부족함'

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    question = models.TextField(help_text='개인정보를 가린 질문')
    status = models.CharField(max_length=20, help_text='answered / no_answer / unverified / error')
    answer = models.TextField(help_text='학생에게 보여 준 문장')
    model_text = models.TextField(blank=True, help_text='모델이 쓴 원래 답 (숨긴 답도 포함, 개인정보 가림)')
    cited_keys = models.JSONField(default=list, blank=True)
    evidence_keys = models.JSONField(default=list, blank=True)
    best_similarity = models.FloatField(null=True, blank=True)
    model = models.CharField(max_length=100, blank=True)
    seconds = models.FloatField(default=0)
    feedback = models.CharField(max_length=10, choices=Feedback.choices, blank=True)
    feedback_reason = models.CharField(max_length=20, choices=Reason.choices, blank=True)
    feedback_at = models.DateTimeField(null=True, blank=True)
    feedback_token_hash = models.CharField(max_length=64)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['status'], name='chatlog_status_idx'),
                   models.Index(fields=['feedback'], name='chatlog_feedback_idx')]

    def __str__(self):
        return f'[{self.status}] {self.question[:40]}'
