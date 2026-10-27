"""학생 챗봇의 익명 대화 기록과 👍/👎 (docs/adr/0012).

사내·학교 FAQ형 챗봇처럼, 못 답한 질문·숨긴 답·👎를 모아 자료(공지, 규정 문구, 동의어)를 보강하고
평가 질문에 추가하는 데 쓴다. 기록 실패가 학생의 답을 막으면 안 되므로 오류는 로그만 남긴다.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import ChatLog

logger = logging.getLogger(__name__)
RETENTION_DAYS = 180


def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def record_chat(reply, channel):
    """답 하나를 기록한다. 반환: (ChatLog, 일회용 평가 키) 또는 기록 실패 시 (None, None)"""
    token = secrets.token_urlsafe(16)
    draft = reply.draft
    try:
        with transaction.atomic():
            log = ChatLog.objects.create(
                channel=channel,
                question=reply.question,
                status=reply.status,
                kind=getattr(reply, 'kind', ''),
                answer=reply.text,
                model_text=getattr(draft, 'text', '') or '',
                cited_keys=[draft.evidence[n - 1].chunk.key for n in draft.cited] if draft else [],
                evidence_keys=[h.chunk.key for h in draft.evidence] if draft else [],
                best_similarity=getattr(draft, 'best_similarity', None),
                model=getattr(draft, 'model', '') or '',
                seconds=round(getattr(draft, 'seconds', 0.0) or 0.0, 2),
                feedback_token_hash=hash_token(token),
            )
    except Exception:
        logger.exception('챗봇 대화 기록을 저장하지 못했습니다')
        return None, None
    return log, token


def give_feedback(log_id, token, rating, reason=''):
    """👍/👎를 기록한다. 반환: 'ok' | 'invalid'(키가 틀림·없는 기록·잘못된 값) | 'already'(이미 평가함)"""
    if rating not in ChatLog.Feedback.values:
        return 'invalid'
    if rating == ChatLog.Feedback.DOWN and reason and reason not in ChatLog.Reason.values:
        return 'invalid'
    with transaction.atomic():
        log = ChatLog.objects.select_for_update().filter(pk=log_id).first()
        if log is None or not hmac.compare_digest(log.feedback_token_hash, hash_token(str(token))):
            return 'invalid'
        if log.feedback:
            return 'already'
        log.feedback = rating
        log.feedback_reason = reason if rating == ChatLog.Feedback.DOWN else ''
        log.feedback_at = timezone.now()
        log.save(update_fields=['feedback', 'feedback_reason', 'feedback_at'])
    return 'ok'


def purge_old(days=RETENTION_DAYS):
    """보관 기간이 지난 기록을 지운다. 반환: 지운 개수"""
    deleted, _ = ChatLog.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()
    return deleted
