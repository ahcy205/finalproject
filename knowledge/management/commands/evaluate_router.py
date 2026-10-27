"""챗봇 메시지 종류 판단기의 정확도와 속도를 잰다 (docs/adr/0014).

    python manage.py evaluate_router                  # 설정의 판단기 (KNOWLEDGE_ROUTER)
    python manage.py evaluate_router --backend llm    # 로컬 답변 모델
    python manage.py evaluate_router --backend jev    # TypeSafe Jev (TYPESAFE_API_KEY 필요, 외부로 전송됨)

평가 문장은 knowledge/eval/router_messages.yaml. tuned / held_out 세트를 따로 보여 준다.
"""
import time
from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from knowledge.router import get_router

MESSAGES = Path(__file__).resolve().parents[2] / 'eval' / 'router_messages.yaml'


class Command(BaseCommand):
    help = '챗봇 메시지 종류 판단기의 정확도와 속도를 잰다.'

    def add_arguments(self, parser):
        parser.add_argument('--backend', help="판단기 ('jev', 'llm', 'fake'). 없으면 설정값")
        parser.add_argument('--file', default=str(MESSAGES), help='평가 문장 파일')

    def handle(self, *args, **options):
        with open(options['file'], encoding='utf-8') as f:
            data = yaml.safe_load(f)
        router = get_router(options['backend'])
        previous = data['previous']
        results = {}
        for item in data['messages']:
            started = time.perf_counter()
            got = router.classify(str(item['m']), previous)
            seconds = time.perf_counter() - started
            bucket = results.setdefault(item['set'], {'correct': 0, 'total': 0, 'times': [], 'misses': []})
            bucket['total'] += 1
            bucket['times'].append(seconds)
            if got == item['kind']:
                bucket['correct'] += 1
            else:
                bucket['misses'].append(f"{item['m']} ({item['kind']}→{got})")
        self.stdout.write(f'\n## 메시지 종류 판단: {router.name}')
        self.stdout.write('| 세트 | 정확도 | 시간 중앙값 | 최대 |\n|---|---|---|---|')
        for name, b in results.items():
            times = sorted(b['times'])
            self.stdout.write(f"| {name} | {b['correct']}/{b['total']} = {b['correct'] / b['total']:.2f} "
                              f"| {times[len(times) // 2] * 1000:.0f}ms | {times[-1] * 1000:.0f}ms |")
        for name, b in results.items():
            for miss in b['misses']:
                self.stdout.write(f'- {name} 틀림: {miss}')
