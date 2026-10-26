"""검색 자료(KnowledgeChunk)를 원본에서 다시 만든다.

    python manage.py build_knowledge_index                 # 전체 반영 + 임베딩
    python manage.py build_knowledge_index --source rules  # 일부 자료만
    python manage.py build_knowledge_index --no-embed      # 내용만 반영 (모델 없이)
    python manage.py build_knowledge_index --backend fake  # 가짜 임베딩 (모델 설치 없이 확인할 때)
"""
from django.core.management.base import BaseCommand

from knowledge.chunking import build_chunks
from knowledge.embeddings import get_embedder
from knowledge.indexing import embed_pending, sync_chunks
from knowledge.models import KnowledgeChunk


class Command(BaseCommand):
    help = '규칙·안내·셔틀버스·식단·공지·답변된 문의로 검색 자료를 만들고 임베딩한다.'

    def add_arguments(self, parser):
        parser.add_argument('--source', action='append', choices=KnowledgeChunk.Source.values,
                            help='반영할 자료 (여러 번 지정 가능). 없으면 전부')
        parser.add_argument('--no-embed', action='store_true', help='내용만 반영하고 임베딩은 하지 않음')
        parser.add_argument('--backend', help="임베딩 방식 ('sentence-transformers' 또는 'fake'). 기본은 설정값")
        parser.add_argument('--model', help='임베딩 모델 이름. 기본은 설정값 (BAAI/bge-m3)')

    def handle(self, *args, **options):
        selected = options['source'] or KnowledgeChunk.Source.values
        stats = sync_chunks(build_chunks(selected), selected)
        self.stdout.write('내용 반영: 추가 {created}, 수정 {updated}, 삭제 {deleted}, 그대로 {unchanged}'.format(**stats))
        if options['no_embed']:
            return
        embedder = get_embedder(options['backend'], options['model'])
        count = embed_pending(embedder)
        self.stdout.write(self.style.SUCCESS(f'임베딩: {count}개 ({embedder.name})'))
        self.stdout.write(f'검색 자료: 총 {KnowledgeChunk.objects.count()}개')
