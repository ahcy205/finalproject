"""보관 기간(기본 180일)이 지난 챗봇 대화 기록을 지운다 (docs/adr/0012).

    python manage.py purge_chat_logs            # 180일이 지난 기록
    python manage.py purge_chat_logs --days 90
"""
from django.core.management.base import BaseCommand

from knowledge.chat_log import RETENTION_DAYS, purge_old


class Command(BaseCommand):
    help = '보관 기간이 지난 챗봇 대화 기록을 지운다.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=RETENTION_DAYS, help=f'보관 일수 (기본 {RETENTION_DAYS})')

    def handle(self, *args, **options):
        count = purge_old(options['days'])
        self.stdout.write(f'{options["days"]}일이 지난 챗봇 대화 기록 {count}개를 지웠습니다.')
