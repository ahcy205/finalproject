from django.contrib import admin

from .models import KnowledgeChunk


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    """검색 자료 확인용. 원본(knowledge/data, 공지, 문의)에서 다시 만드는 사본이라 여기서 고치지 않는다."""

    list_display = ('title', 'source', 'has_embedding', 'embedding_model', 'updated_at')
    list_filter = ('source', 'embedding_model')
    search_fields = ('title', 'content', 'key')
    readonly_fields = ('source', 'key', 'title', 'content', 'url', 'metadata', 'content_hash', 'embedding_model',
                       'updated_at')
    exclude = ('embedding',)

    @admin.display(boolean=True, description='임베딩')
    def has_embedding(self, obj):
        return obj.embedding is not None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
