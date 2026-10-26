"""학생 문의에 대한 답변 초안을 만든다 (RAG 3단계).

흐름
1. 문의 제목·내용에서 개인정보를 가린다 (모델에도, 로그에도 원문을 넘기지 않음).
2. 하이브리드 검색으로 근거 5개를 찾는다. 공개 자료(규칙·안내·버스·식단·공지)와 다른 학생의 답변된 문의를 쓰되,
   같은 문의 자신은 근거에서 뺀다.
3. 가장 가까운 근거의 유사도가 MIN_SIMILARITY보다 낮으면 초안을 만들지 않는다 (모델을 부르지 않음).
4. 모델에게 "근거에 있는 내용만, 문장마다 [번호]로 인용"하도록 지시해 초안을 받는다.
5. 초안의 [번호]가 실제로 넘긴 근거인지 검사한다. 없는 번호는 경고로 남긴다.

초안은 관리자가 확인하고 고쳐서 보내는 용도이며, 학생에게 바로 보내지 않는다.
"""
import re
import time
from dataclasses import dataclass, field

from .llm import LLMError, get_llm
from .privacy import mask_personal_info
from .search import search

# 근거가 부족하다고 볼 유사도 기준 (bge-m3 기준 측정값, docs/adr/0007).
# 답할 수 있는 평가 질문 32개는 모두 0.479 이상이었다.
MIN_SIMILARITY = 0.45
EVIDENCE_COUNT = 5

SYSTEM_PROMPT = '''당신은 대학 기숙사(생활관) 관리자를 돕는 비서입니다. 학생 문의에 대한 답변 초안을 씁니다.

규칙:
1. 아래 [근거]에 적힌 내용만 사용합니다. 근거에 없는 사실, 날짜, 시간, 점수를 지어내지 않고, 상식으로 추측해 덧붙이지 않습니다.
2. 근거를 사용한 문장 끝에는 [근거] 목록의 번호를 [1]처럼 붙입니다. 근거 본문 안의 항목 번호는 근거 번호가 아닙니다.
3. 근거로 답할 수 없는 질문이면 "근거 자료에서 확인할 수 없습니다. 생활관에 직접 문의해 주세요."라고만 씁니다.
4. 학생에게 보내는 존댓말로, 3~6문장으로 씁니다.
5. 학생의 이름, 학번, 연락처를 쓰지 않습니다.

예시 1 (근거로 답할 수 있는 문의)
[문의] 다리미실 쓰고 나서 뭐 해야 돼요?
[근거] [1] 생활관 규칙 제6조 (공용시설 이용) ... 다리미실을 이용할 때에는 화재에 특히 유의하여야 하며 사용 후에는 반드시 전원을 제거한 후 정돈하여야 한다.
답변: 안녕하세요. 다리미실을 사용한 뒤에는 반드시 전원을 뽑고 주변을 정돈해 주셔야 합니다 [1]. 사용하는 동안에는 화재에 특히 유의해 주세요 [1]. 감사합니다.

예시 2 (근거로 답할 수 없는 문의)
[문의] 학교 축제는 언제 해요?
[근거] (축제와 관계없는 셔틀버스·식단 자료)
답변: 근거 자료에서 확인할 수 없습니다. 생활관에 직접 문의해 주세요.'''

REMINDER = ('위 [근거]만 사용해 답변을 쓰세요. 근거를 쓴 문장 끝에는 [번호]를 붙이고, '
            '근거로 답할 수 없으면 "근거 자료에서 확인할 수 없습니다. 생활관에 직접 문의해 주세요."라고만 쓰세요.')

CITATION = re.compile(r'\[(\d+)\]')


@dataclass
class Draft:
    status: str                     # 'ok' | 'insufficient_evidence' | 'error'
    text: str = ''
    evidence: list = field(default_factory=list)   # SearchHit 목록 (번호 = 순서 + 1)
    cited: list = field(default_factory=list)      # 초안에서 인용한 근거 번호
    warnings: list = field(default_factory=list)
    model: str = ''
    seconds: float = 0.0
    best_similarity: float | None = None


def build_prompt(title, content, hits):
    lines = ['[문의]', f'제목: {title}', f'내용: {content}', '', '[근거]']
    for number, hit in enumerate(hits, start=1):
        lines += [f'[{number}] {hit.chunk.title}', hit.chunk.content, '']
    # 작은 모델은 긴 지시보다 바로 앞의 말을 더 잘 따른다. 근거 뒤에 핵심 규칙을 한 번 더 둔다
    lines.append(REMINDER)
    return '\n'.join(lines).strip()


def check_citations(text, evidence_count):
    cited = sorted({int(n) for n in CITATION.findall(text)})
    warnings = []
    invalid = [n for n in cited if not 1 <= n <= evidence_count]
    if invalid:
        warnings.append(f'없는 근거 번호를 인용했습니다: {invalid}')
    if not cited and '확인할 수 없' not in text:
        warnings.append('근거 번호가 없습니다. 근거와 맞는지 확인하세요.')
    return [n for n in cited if 1 <= n <= evidence_count], warnings


def draft_for_text(title, content, known_names=(), exclude_keys=(), llm=None, embedder=None,
                   min_similarity=None):
    """제목·내용으로 초안을 만든다. 평가와 화면이 함께 쓴다.

    min_similarity: 근거 부족 기준. 없으면 MIN_SIMILARITY (bge-m3 측정값이라 다른 임베딩은 따로 정한다)
    """
    title = mask_personal_info(title, known_names)
    content = mask_personal_info(content, known_names)
    result = search(f'{title}\n{content}', k=EVIDENCE_COUNT + len(exclude_keys), embedder=embedder)
    hits = [h for h in result.hits if h.chunk.key not in exclude_keys][:EVIDENCE_COUNT]
    best = max((h.similarity for h in hits if h.similarity is not None), default=None)
    draft = Draft(status='ok', evidence=hits, best_similarity=best)

    threshold = MIN_SIMILARITY if min_similarity is None else min_similarity
    if best is None or best < threshold:
        draft.status = 'insufficient_evidence'
        draft.warnings.append('관련 근거를 찾지 못해 초안을 만들지 않았습니다. 직접 답변해 주세요.')
        return draft

    llm = llm or get_llm()
    draft.model = llm.name
    started = time.perf_counter()
    try:
        text = llm.generate(SYSTEM_PROMPT, build_prompt(title, content, hits))
    except LLMError as exc:
        draft.status = 'error'
        draft.warnings.append(str(exc))
        return draft
    finally:
        draft.seconds = time.perf_counter() - started
    draft.text = mask_personal_info(text, known_names)  # 모델이 개인정보를 만들어 내도 한 번 더 가린다
    draft.cited, draft.warnings = check_citations(draft.text, len(hits))
    return draft


def draft_answer(inquiry, llm=None, embedder=None, min_similarity=None):
    """문의(dorm.models.Inquiry)에 대한 초안. 같은 문의의 검색 자료는 근거에서 뺀다."""
    user = inquiry.user
    names = [user.username, getattr(getattr(user, 'userprofile', None), 'full_name', '')]
    return draft_for_text(inquiry.title, inquiry.content, known_names=names,
                          exclude_keys=(f'inquiry:{inquiry.pk}',), llm=llm, embedder=embedder,
                          min_similarity=min_similarity)
