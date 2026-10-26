"""청크를 검색 자료 테이블(KnowledgeChunk)에 반영하고 임베딩한다.

1. 내용 반영(sync_chunks): 원본에서 만든 청크를 저장한다. 새 청크는 추가, 바뀐 청크는 고치고 벡터를 비우고,
   원본에서 사라진 청크는 지운다. 한 트랜잭션으로 처리해서 검색 자료가 원본과 어긋난 채로 남지 않게 한다.
2. 임베딩(embed_pending): 벡터가 비어 있거나 다른 모델로 만든 청크만 골라 임베딩한다.
   모델 실행은 느릴 수 있어서 내용 반영과 나눠 두었다.
"""
from django.db import transaction
from django.db.models import Q

from .models import KnowledgeChunk


def sync_chunks(chunks, sources):
    """sources에 속한 청크를 chunks와 똑같이 맞춘다. 반환: {'created', 'updated', 'deleted', 'unchanged'}"""
    stats = {'created': 0, 'updated': 0, 'deleted': 0, 'unchanged': 0}
    keys = {c.key for c in chunks}
    assert len(keys) == len(chunks), '청크 key가 중복되었습니다'
    with transaction.atomic():
        existing = {c.key: c for c in KnowledgeChunk.objects.filter(source__in=sources)}
        for chunk in chunks:
            digest = chunk.content_hash()
            row = existing.get(chunk.key)
            if row is None:
                KnowledgeChunk.objects.create(
                    source=chunk.source, key=chunk.key, title=chunk.title, content=chunk.content, url=chunk.url,
                    metadata=chunk.metadata, content_hash=digest)
                stats['created'] += 1
                continue
            if (row.content_hash, row.url, row.metadata, row.source) == (digest, chunk.url, chunk.metadata, chunk.source):
                stats['unchanged'] += 1
                continue
            if row.content_hash != digest:
                row.embedding, row.embedding_model = None, ''  # 내용이 바뀌면 예전 벡터는 쓰지 않는다
            row.source, row.title, row.content, row.url = chunk.source, chunk.title, chunk.content, chunk.url
            row.metadata, row.content_hash = chunk.metadata, digest
            row.save()
            stats['updated'] += 1
        stale = KnowledgeChunk.objects.filter(source__in=sources).exclude(key__in=keys)
        stats['deleted'] = stale.count()
        stale.delete()
    return stats


def delete_chunks(keys):
    return KnowledgeChunk.objects.filter(key__in=keys).delete()[0]


def embed_pending(embedder, batch_size=32):
    """벡터가 없거나 embedder와 다른 모델로 만든 청크를 임베딩한다. 반환: 임베딩한 청크 수"""
    pending = KnowledgeChunk.objects.filter(Q(embedding__isnull=True) | ~Q(embedding_model=embedder.name)).order_by('id')
    done = 0
    ids = list(pending.values_list('id', flat=True))
    for start in range(0, len(ids), batch_size):
        batch = list(KnowledgeChunk.objects.filter(id__in=ids[start:start + batch_size]).order_by('id'))
        vectors = embedder.embed_documents([c.embedding_text() for c in batch])
        for chunk, vector in zip(batch, vectors):
            chunk.embedding, chunk.embedding_model = vector, embedder.name
        KnowledgeChunk.objects.bulk_update(batch, ['embedding', 'embedding_model'])
        done += len(batch)
    return done


def upsert_chunk(chunk):
    """청크 하나를 추가하거나 고친다 (공지·문의 저장 시 자동 갱신용). 내용이 바뀌면 벡터를 비운다."""
    digest = chunk.content_hash()
    row = KnowledgeChunk.objects.filter(key=chunk.key).first()
    if row is None:
        return KnowledgeChunk.objects.create(
            source=chunk.source, key=chunk.key, title=chunk.title, content=chunk.content, url=chunk.url,
            metadata=chunk.metadata, content_hash=digest)
    if row.content_hash != digest:
        row.embedding, row.embedding_model = None, ''
    row.title, row.content, row.url, row.metadata, row.content_hash = (
        chunk.title, chunk.content, chunk.url, chunk.metadata, digest)
    row.save()
    return row
