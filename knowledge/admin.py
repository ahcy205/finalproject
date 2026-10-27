from django.contrib import admin

from .models import ChatLog, KnowledgeChunk


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


@admin.register(ChatLog)
class ChatLogAdmin(admin.ModelAdmin):
    """챗봇 대화 기록 확인용 (읽기 전용, docs/adr/0012). 누가 물었는지는 저장하지 않는다.
    오래된 기록은 purge_chat_logs, 평가 질문 후보는 export_chat_misses로 처리한다."""

    list_display = ('created_at', 'short_question', 'status', 'feedback', 'feedback_reason', 'channel', 'seconds')
    list_filter = ('status', 'feedback', 'feedback_reason', 'channel')
    search_fields = ('question', 'answer')
    date_hierarchy = 'created_at'
    exclude = ('feedback_token_hash',)

    @admin.display(description='질문')
    def short_question(self, obj):
        return obj.question[:60]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in ChatLog._meta.fields if f.name != 'feedback_token_hash']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
