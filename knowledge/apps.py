from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'knowledge'
    verbose_name = 'RAG 검색 자료'

    def ready(self):
        from . import signals  # noqa: F401  (공지·문의 저장 시 검색 자료 자동 갱신)
