from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from app.core.config import settings


@lru_cache(maxsize=1)
def _client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)


def _ensure_collection(vector_size: int):
    client = _client()
    try:
        collections = {c.name for c in client.get_collections().collections}
        if settings.QDRANT_COLLECTION in collections:
            return
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    except Exception:
        # Qdrant vaqtincha ishlamasa pipeline to'xtab qolmasin.
        return


def upsert_clause_embedding(
    clause_id: str,
    vector: list[float],
    shnq_code: str,
    clause_number: str | None,
    chapter_title: str | None,
    document_id: str | None = None,
    section_id: str | None = None,
    page: str | None = None,
    language: str | None = None,
    content_type: str | None = None,
):
    if not settings.RAG_USE_QDRANT or not vector:
        return
    try:
        _ensure_collection(len(vector))
        _client().upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[
                PointStruct(
                    id=clause_id,
                    vector=vector,
                    payload={
                        "source_type": "clause",
                        "shnq_code": shnq_code,
                        "clause_number": clause_number,
                        "chapter_title": chapter_title,
                        "document_id": document_id,
                        "section_id": section_id,
                        "page": page,
                        "language": language,
                        "content_type": content_type,
                    },
                )
            ],
        )
    except Exception:
        return


def _build_filter(
    shnq_code: str | None = None,
    shnq_codes: list[str] | None = None,
    metadata_filters: dict[str, list[str]] | None = None,
):
    if not shnq_code and not shnq_codes and not metadata_filters:
        return None
    try:
        from qdrant_client.http.models import FieldCondition, Filter, MatchAny, MatchValue
    except Exception:
        return None

    must = []
    merged_codes: list[str] = []
    if shnq_code:
        merged_codes.append(shnq_code)
    if shnq_codes:
        merged_codes.extend([code for code in shnq_codes if code])
    uniq_codes = list(dict.fromkeys(merged_codes))
    if len(uniq_codes) == 1:
        must.append(FieldCondition(key="shnq_code", match=MatchValue(value=uniq_codes[0])))
    elif len(uniq_codes) > 1:
        must.append(FieldCondition(key="shnq_code", match=MatchAny(any=uniq_codes)))

    for key, values in (metadata_filters or {}).items():
        cleaned = [value for value in values if value]
        if not cleaned:
            continue
        if len(cleaned) == 1:
            must.append(FieldCondition(key=key, match=MatchValue(value=cleaned[0])))
        else:
            must.append(FieldCondition(key=key, match=MatchAny(any=cleaned)))
    return Filter(must=must) if must else None


def search_clause_ids(
    query_vector: list[float],
    limit: int = 8,
    shnq_code: str | None = None,
    shnq_codes: list[str] | None = None,
    metadata_filters: dict[str, list[str]] | None = None,
) -> list[tuple[str, float]]:
    if not settings.RAG_USE_QDRANT or not query_vector:
        return []
    q_filter = _build_filter(shnq_code=shnq_code, shnq_codes=shnq_codes, metadata_filters=metadata_filters)

    try:
        hits = _client().search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=query_vector,
            query_filter=q_filter,
            limit=limit,
        )
        return [(str(hit.id), float(hit.score)) for hit in hits]
    except Exception:
        return []
