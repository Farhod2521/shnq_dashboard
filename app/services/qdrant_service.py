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
                    },
                )
            ],
        )
    except Exception:
        return


def search_clause_ids(query_vector: list[float], limit: int = 8, shnq_code: str | None = None) -> list[tuple[str, float]]:
    if not settings.RAG_USE_QDRANT or not query_vector:
        return []

    q_filter = None
    if shnq_code:
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        q_filter = Filter(
            must=[FieldCondition(key="shnq_code", match=MatchValue(value=shnq_code))]
        )

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
