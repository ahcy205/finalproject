from django.apps import AppConfig


class DormConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dorm'

    def ready(self):
        from . import checks  # noqa: F401  (시스템 점검 등록)