"""챗봇이 못 답한 질문과 👎 받은 질문을 평가 질문 후보로 내보낸다 (docs/adr/0012).

    python manage.py export_chat_misses                       # 최근 30일, 화면에 출력
    python manage.py export_chat_misses --days 90 --output misses.yaml

출력은 knowledge/eval/questions.yaml의 questions 형식과 같다. 관리자가 질문마다 원인을 확인하고
- 자료가 없으면 공지·규정 문구를 보강하고,
- 단어가 달라 못 찾았으면 knowledge/data/synonyms.yaml에 추가하고,
- 정답 청크를 expected에 적어 평가 질문 파일에 옮긴 뒤 evaluate_answer_drafts --mode chat으로 다시 잰다.
"""
from collections import OrderedDict
from datetime import timedelta

import yaml
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from knowledge.models import ChatLog


class Command(BaseCommand):
    help = '못 답한 질문·👎 받은 질문을 평가 질문 후보(YAML)로 내보낸다.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='최근 며칠의 기록을 볼지 (기본 30)')
        parser.add_argument('--output', help='저장할 파일. 없으면 화면에 출력')

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(days=options['days'])
        misses = (ChatLog.objects.filter(created_at__gte=since)
                  .filter(Q(status__in=['no_answer', 'unverified']) | Q(feedback=ChatLog.Feedback.DOWN))
                  .order_by('created_at', 'id'))
        grouped = OrderedDict()
        for log in misses:
            item = grouped.setdefault(log.question, {'q': log.question, 'expected': [], 'count': 0, 'reasons': []})
            item['count'] += 1
            reason = f'👎 {log.feedback_reason}'.strip() if log.feedback == ChatLog.Feedback.DOWN else log.status
            if reason not in item['reasons']:
                item['reasons'].append(reason)
        items = sorted(grouped.values(), key=lambda i: -i['count'])
        text = yaml.safe_dump(items, allow_unicode=True, sort_keys=False) if items else '[]\n'
        header = (f'# 최근 {options["days"]}일 동안 챗봇이 못 답했거나 👎 받은 질문 {len(items)}개\n'
                  '# expected에 정답 청크 key를 적고 knowledge/eval/questions.yaml로 옮긴다\n')
        if options['output']:
            with open(options['output'], 'w', encoding='utf-8') as f:
                f.write(header + text)
            self.stdout.write(f'{len(items)}개를 {options["output"]}에 저장했습니다.')
        else:
            self.stdout.write(header + text)
