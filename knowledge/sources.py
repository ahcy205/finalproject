"""생활관 규칙·안내 같은 원본 자료를 읽는다.

자료는 knowledge/data/*.yaml에 있고, 화면(/rules/, /info/)과 RAG 검색 색인이 같은 파일을 쓴다.
파일이 작아서 요청마다 읽는다(수정하면 서버를 다시 켜지 않아도 화면에 바로 반영됨).
"""
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parent / 'data'
REGULATION_PAGES = ('rules', 'info')


def load(page):
    """page: 'rules' 또는 'info'. 구조는 knowledge/data/README.md 참고."""
    if page not in REGULATION_PAGES:
        raise ValueError(f'알 수 없는 자료입니다: {page}')
    with open(DATA_DIR / f'{page}.yaml', encoding='utf-8') as f:
        return yaml.safe_load(f)
