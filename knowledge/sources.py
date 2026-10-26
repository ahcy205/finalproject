"""생활관 규칙·안내·셔틀버스·식단 원본 자료를 읽는다.

자료는 knowledge/data/*.yaml에 있고, 화면(/rules/, /info/, /bus/, /menu/)과 RAG 검색 색인이 같은 파일을 쓴다.
파일이 작아서 요청마다 읽는다(수정하면 서버를 다시 켜지 않아도 화면에 바로 반영됨).
"""
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parent / 'data'
REGULATION_PAGES = ('rules', 'info')   # 장·조항 형식
TABLE_PAGES = ('bus', 'menu')           # 표 형식
PAGES = REGULATION_PAGES + TABLE_PAGES


def load(page):
    """page: PAGES 중 하나. 구조는 knowledge/data/README.md 참고."""
    if page not in PAGES:
        raise ValueError(f'알 수 없는 자료입니다: {page}')
    with open(DATA_DIR / f'{page}.yaml', encoding='utf-8') as f:
        return yaml.safe_load(f)
