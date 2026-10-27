"""학생 챗봇의 이어지는 대화 (docs/adr/0014).

- 대화 기억은 서버 캐시에만 둔다: 사용자·대화별 최근 MAX_TURNS턴, 마지막 메시지 뒤 MEMORY_SECONDS초.
  DB에는 남기지 않는다(익명 기록 ChatLog는 그대로, ADR 0012).
- 브라우저·앱이 보낸 "앞 대화"는 받지 않는다. 받으면 아무 글이나 "앞 답"이라며 넣고 "요약해줘"로
  근거 없는 내용을 말하게 만들 수 있다. 클라이언트는 대화 번호(conversation_id)만 보내고,
  그 번호도 사용자별로 나뉘어 있어 남의 대화를 불러올 수 없다.
- 메시지 종류(router.py)에 따라 처리한다.
  - smalltalk: 정해진 답
  - meta: 앞 답과 그 근거 원문으로 다시 쓴다. 인용·첫 문장 검사를 똑같이 거친다
  - followup: 아직 다시 쓰지 않고 새 질문처럼 답한다 (다음 PR)
  - new: chat.answer_question()
"""
import re
import secrets

from django.core.cache import cache

from .answering import REFUSAL_PHRASE, Draft, check_citations
from .chat import (ERROR_MESSAGE, MAX_QUESTION_LENGTH, MARKDOWN_BOLD, NO_ANSWER_MESSAGE, RELATED_LINKS,
                   UNVERIFIED_MESSAGE, ChatReply, answer_question, opens_with_not_found, source_links)
from .llm import LLMError, get_llm
from .models import KnowledgeChunk
from .privacy import mask_personal_info
from .router import get_router
from .search import SearchHit

MAX_TURNS = 3
MEMORY_SECONDS = 30 * 60
CONVERSATION_ID = re.compile(r'^[A-Za-z0-9_-]{16,64}$')

GREETING_WORDS = ('안녕', '하이', 'ㅎㅇ', '반가')
GREETING_REPLY = '안녕하세요! 생활관 규칙·안내·셔틀버스·식단·공지에 대해 궁금한 점을 물어보세요.'
THANKS_REPLY = '도움이 됐다니 다행이에요. 더 궁금한 점이 있으면 언제든 물어보세요.'
NOTHING_TO_REPEAT = '앞에서 드린 답이 없어서 다시 말씀드릴 내용이 없어요. 궁금한 점을 질문으로 보내 주세요.'

META_SYSTEM = '''당신은 대학 기숙사(생활관)의 안내 챗봇입니다. 학생이 바로 앞 답을 다시 말해 달라거나, 요약하거나,
쉽게 또는 자세히 설명해 달라고 요청했습니다.

규칙:
1. 학생의 요청대로 [앞 답]을 다시 씁니다. 요약이면 짧게, 쉽게면 쉬운 말로, 자세히면 [근거]의 내용을 더 풀어 씁니다.
2. [근거]에 적힌 내용만 사용합니다. 근거와 앞 답에 없는 사실, 날짜, 시간, 점수를 새로 만들지 않습니다.
3. 근거를 사용한 문장 끝에는 [근거] 목록의 번호를 [1]처럼 붙입니다.
4. 학생에게 보내는 존댓말로 씁니다. 학생의 이름, 학번, 연락처를 쓰지 않습니다.'''


def new_conversation_id():
    return secrets.token_urlsafe(16)


def _key(user_id, conversation_id):
    return f'chatbot:conversation:{user_id}:{conversation_id}'


def load_turns(user_id, conversation_id):
    return cache.get(_key(user_id, conversation_id), [])


def save_turn(user_id, conversation_id, turn):
    turns = (load_turns(user_id, conversation_id) + [turn])[-MAX_TURNS:]
    cache.set(_key(user_id, conversation_id), turns, timeout=MEMORY_SECONDS)


def forget(user_id, conversation_id):
    cache.delete(_key(user_id, conversation_id))


def evidence_hits(keys):
    """저장해 둔 근거 key를 같은 순서의 SearchHit로 되살린다 (번호를 앞 답과 똑같이 맞추기 위해)."""
    chunks = KnowledgeChunk.objects.in_bulk(keys, field_name='key')
    return [SearchHit(chunk=chunks[key], score=0.0) for key in keys if key in chunks]


def smalltalk_reply(message):
    text = GREETING_REPLY if any(word in message for word in GREETING_WORDS) else THANKS_REPLY
    return ChatReply('answered', text, [], draft=Draft(status='ok', text=text))


def meta_reply(message, previous, llm=None):
    """앞 답을 학생의 요청대로 다시 쓴다. 앞 답이 없거나 답을 찾지 못한 답이면 다시 쓸 것이 없다고 한다."""
    if not previous or previous['status'] != 'answered' or not previous['evidence_keys']:
        return ChatReply('no_answer', NOTHING_TO_REPEAT, [], draft=Draft(status='insufficient_evidence'))
    hits = evidence_hits(previous['evidence_keys'])
    llm = llm or get_llm()
    lines = ['[앞 질문]', previous['question'], '', '[근거]']
    for number, hit in enumerate(hits, start=1):
        lines += [f'[{number}] {hit.chunk.title}', hit.chunk.content, '']
    lines += ['[앞 답]', previous['answer'], '', '[학생의 요청]', message]
    prompt = '\n'.join(lines)
    draft = Draft(status='ok', evidence=hits, model=llm.name)
    try:
        text = llm.generate(META_SYSTEM, prompt)
    except LLMError as exc:
        draft.status = 'error'
        draft.warnings.append(str(exc))
        return ChatReply('error', ERROR_MESSAGE, draft=draft)
    draft.text = mask_personal_info(text)
    draft.cited, draft.warnings = check_citations(draft.text, len(hits))
    if (REFUSAL_PHRASE in draft.text and not draft.cited) or opens_with_not_found(draft.text):
        return ChatReply('no_answer', NO_ANSWER_MESSAGE, draft=draft)
    if draft.warnings or not draft.cited:
        return ChatReply('unverified', UNVERIFIED_MESSAGE, source_links(draft, list(range(1, min(RELATED_LINKS, len(hits)) + 1))),
                         draft=draft)
    return ChatReply('answered', MARKDOWN_BOLD.sub(r'\1', draft.text), source_links(draft, draft.cited), draft=draft)


def reply_to(message, user_id, conversation_id=None, known_names=(), router=None, llm=None, embedder=None,
             min_similarity=None):
    """대화 안의 메시지 하나에 답한다. 반환: (ChatReply, conversation_id). reply.kind에 메시지 종류가 들어 있다."""
    if not conversation_id or not CONVERSATION_ID.match(conversation_id):
        conversation_id = new_conversation_id()
    masked = mask_personal_info(message[:MAX_QUESTION_LENGTH], known_names)
    turns = load_turns(user_id, conversation_id)
    previous = turns[-1] if turns else None

    try:
        kind = (router or get_router()).classify(masked, previous)
    except LLMError:
        kind = 'new'
    if kind in ('meta', 'followup') and not previous:
        kind = 'new'  # 앞 대화가 없으면 이어질 것이 없다

    if kind == 'smalltalk':
        reply = smalltalk_reply(masked)
    elif kind == 'meta':
        reply = meta_reply(masked, previous, llm=llm)
    else:
        reply = answer_question(masked, llm=llm, embedder=embedder, min_similarity=min_similarity)
    reply.question = masked
    reply.kind = kind

    draft = reply.draft
    save_turn(user_id, conversation_id, {
        'question': masked, 'answer': reply.text, 'status': reply.status, 'kind': kind,
        # meta 답은 앞 답의 근거를 그대로 쓰므로, 다시 "요약해줘"라고 해도 같은 근거로 이어진다
        'evidence_keys': [h.chunk.key for h in draft.evidence] if draft and draft.evidence else [],
    })
    return reply, conversation_id
