"""검색 자료로 저장하거나 외부 AI로 보내기 전에 개인정보를 가린다.

가리는 것: 전화번호, 이메일, 학번처럼 보이는 8–10자리 숫자, 그리고 호출하는 쪽이 알려 준 이름·아이디.
문장 속의 임의의 이름까지 찾아내지는 못하므로, 문의 작성자처럼 알 수 있는 사람의 이름은 known_names로 넘긴다.
"""
import re

PHONE = re.compile(r'(?<!\d)01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
STUDENT_NUMBER = re.compile(r'(?<!\d)\d{8,10}(?!\d)')


def mask_personal_info(text, known_names=()):
    if not text:
        return text
    text = EMAIL.sub('[이메일]', text)
    text = PHONE.sub('[전화번호]', text)
    text = STUDENT_NUMBER.sub('[학번]', text)
    # 긴 이름부터 가려야 '홍길동'이 '홍길'보다 먼저 처리된다
    for name in sorted({n.strip() for n in known_names if n and n.strip()}, key=len, reverse=True):
        if len(name) >= 2:
            text = text.replace(name, '[이름]')
    return text
