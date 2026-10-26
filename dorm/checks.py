"""Django 시스템 점검: 서버 실행·마이그레이션·테스트 전에 DB 접속을 확인한다.

DB가 꺼져 있을 때 SQLite로 대신 실행하지 않고(ADR 0005), 무엇을 하면 되는지 알려 준다.
"""
from django.core.checks import Error, register
from django.db import OperationalError, connection


@register()
def check_database_connection(app_configs, **kwargs):
    try:
        connection.ensure_connection()
    except OperationalError as exc:
        settings = connection.settings_dict
        return [Error(
            f"PostgreSQL에 접속할 수 없습니다 ({settings['HOST']}:{settings['PORT']}, DB {settings['NAME']}).",
            hint='Docker Desktop을 켠 뒤 프로젝트 폴더에서 `docker compose up -d db`를 실행하세요. '
                 f'원인: {str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__}',
            id='dorm.E001',
        )]
    return []
