"""공지·문의가 바뀌면 검색 자료(KnowledgeChunk)를 바로 고친다.

- 공지: 저장하면 청크 추가·수정, 지우면 삭제
- 문의: 답변이 달리거나 고쳐지면 청크 추가·수정, 답변이나 문의가 지워지면 삭제
- 내용이 바뀐 청크는 벡터를 비워 두고, 임베딩은 `build_knowledge_index`가 채운다(모델 실행이 느려서 요청 중에 하지 않음).
- 백업 불러오기(loaddata, raw=True) 중에는 건너뛴다. 불러온 뒤 색인 명령으로 한꺼번에 만든다.
- 검색 자료 갱신이 실패해도 공지·문의 저장은 막지 않고 오류만 기록한다. 검색 자료는 색인 명령으로 언제든 다시 맞출 수 있다.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from dorm.models import Inquiry, InquiryAnswer, Notice

from .chunking import inquiry_chunk, notice_chunk
from .indexing import delete_chunks, upsert_chunk

logger = logging.getLogger(__name__)


def _safely(action, description):
    try:
        # 저장점: 실패하면 검색 자료 쪽 변경만 되돌리고, 바깥 트랜잭션(공지 저장 등)은 계속 쓸 수 있게 한다
        with transaction.atomic():
            action()
    except Exception:  # 검색 자료 때문에 원래 작업이 실패하면 안 된다
        logger.exception('검색 자료 갱신 실패: %s (python manage.py build_knowledge_index로 다시 맞출 수 있음)',
                         description)


@receiver(post_save, sender=Notice)
def notice_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        _safely(lambda: upsert_chunk(notice_chunk(instance)), f'notice:{instance.pk}')


@receiver(post_delete, sender=Notice)
def notice_deleted(sender, instance, **kwargs):
    _safely(lambda: delete_chunks([f'notice:{instance.pk}']), f'notice:{instance.pk}')


@receiver(post_save, sender=InquiryAnswer)
def answer_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        _safely(lambda: upsert_chunk(inquiry_chunk(instance.inquiry)), f'inquiry:{instance.inquiry_id}')


@receiver(post_save, sender=Inquiry)
def inquiry_saved(sender, instance, raw=False, created=False, **kwargs):
    # 답변이 이미 달린 문의의 제목·내용이 바뀐 경우만 (답변 없는 문의는 검색 자료가 아님)
    if not raw and not created and InquiryAnswer.objects.filter(inquiry=instance).exists():
        _safely(lambda: upsert_chunk(inquiry_chunk(instance)), f'inquiry:{instance.pk}')


@receiver(post_delete, sender=InquiryAnswer)
def answer_deleted(sender, instance, **kwargs):
    _safely(lambda: delete_chunks([f'inquiry:{instance.inquiry_id}']), f'inquiry:{instance.inquiry_id}')
