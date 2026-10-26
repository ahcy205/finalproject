"""학생 챗봇 (RAG 4단계, docs/adr/0011).

관리자 답변 초안(answering.py)과 같은 검색·모델·인용 검사를 쓰지만, 답이 사람 확인 없이 학생에게 바로 가므로
더 엄격하다.

- 근거는 공개 자료만 쓴다 (규칙·안내·셔틀·식단·공지). 다른 학생의 문의·답변은 쓰지 않는다.
- 인용 검사를 통과한 답만 보여 준다. 없는 번호를 인용했거나 인용이 없으면 답을 숨기고 관련 자료 링크만 준다.
- 근거가 약하거나, 모델이 "확인할 수 없다"고 하거나, 첫 문장에서 "자료에 없다"고 하면 문의를 남기도록 안내한다.
- 한 번에 질문 하나만 받는다(앞 대화를 기억하지 않음).
"""
import re
from dataclasses import dataclass, field

from .answering import REFUSAL_PHRASE, SYSTEM_PROMPT as DRAFT_SYSTEM_PROMPT, draft_for_text
from .models import KnowledgeChunk

Source = KnowledgeChunk.Source
PUBLIC_SOURCES = [Source.RULES, Source.INFO, Source.BUS, Source.MENU, Source.NOTICE]
MAX_QUESTION_LENGTH = 500
RELATED_LINKS = 3  # 답을 숨길 때 보여 줄 관련 자료 수

# 학생용으로 따로 쓴 지시문(2~4문장, 인사말 없이)은 측정에서 사실 오류가 늘어 버렸다.
# 검증된 관리자 초안 지시문(ADR 0010)을 그대로 쓴다 (docs/adr/0011)
SYSTEM_PROMPT = DRAFT_SYSTEM_PROMPT

# 첫 문장에서 "자료에 없다"고 하면, 관계없는 근거 번호를 붙였더라도 답을 찾지 못한 것으로 본다
NOT_FOUND = re.compile(r'확인할 수 없|확인하기 어렵|확인되지 않|명시되어 있지 않|언급되어 있지 않|포함되어 있지 않|나와 있지 않')
GREETING = re.compile(r'^\s*안녕하세요[.!]?\s*')
SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

NO_ANSWER_MESSAGE = '생활관 자료에서 답을 찾지 못했어요. 마이페이지에서 문의를 남겨 주시면 관리자가 답변해 드려요.'
UNVERIFIED_MESSAGE = '답변의 근거를 확인하지 못해 보여 드리지 않았어요. 아래 관련 자료를 확인하시거나 문의를 남겨 주세요.'
ERROR_MESSAGE = '지금은 챗봇을 사용할 수 없어요. 잠시 후 다시 시도하시거나 마이페이지에서 문의를 남겨 주세요.'


@dataclass
class ChatReply:
    status: str                  # 'answered' | 'no_answer' | 'unverified' | 'error'
    text: str                    # 학생에게 보여 줄 문장
    sources: list = field(default_factory=list)   # [{'number', 'title', 'url'}] 답의 출처 또는 관련 자료
    draft: object = None         # 내부 결과 (평가·로그용, 학생에게 보이지 않음)


def opens_with_not_found(text, sentences=2):
    """인사말을 뺀 앞 두 문장에 "자료에 없다"는 말이 있는지. 범위 밖 질문에 "명시되어 있지 않습니다 [5]"처럼
    관계없는 번호를 붙여 인용 검사를 통과하는 답을 거른다."""
    body = GREETING.sub('', text)
    return any(NOT_FOUND.search(s) for s in SENTENCE_END.split(body)[:sentences])


def source_links(draft, numbers):
    return [{'number': n, 'title': draft.evidence[n - 1].chunk.title, 'url': draft.evidence[n - 1].chunk.url}
            for n in numbers]


def answer_question(question, known_names=(), llm=None, embedder=None, min_similarity=None):
    """학생 질문에 답한다. question은 길이 검사를 마친 문자열이어야 한다(MAX_QUESTION_LENGTH)."""
    draft = draft_for_text('', question[:MAX_QUESTION_LENGTH], known_names=known_names, llm=llm, embedder=embedder,
                           min_similarity=min_similarity, sources=PUBLIC_SOURCES, system_prompt=SYSTEM_PROMPT)
    if draft.status == 'error':
        return ChatReply('error', ERROR_MESSAGE, draft=draft)
    if (draft.status == 'insufficient_evidence' or (REFUSAL_PHRASE in draft.text and not draft.cited)
            or opens_with_not_found(draft.text)):
        return ChatReply('no_answer', NO_ANSWER_MESSAGE, draft=draft)
    if draft.warnings or not draft.cited:
        related = list(range(1, min(RELATED_LINKS, len(draft.evidence)) + 1))
        return ChatReply('unverified', UNVERIFIED_MESSAGE, source_links(draft, related), draft=draft)
    return ChatReply('answered', draft.text, source_links(draft, draft.cited), draft=draft)
