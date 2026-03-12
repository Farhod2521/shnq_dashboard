from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://postgres:password@localhost:5432/shnq_ai"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    CHAT_MODEL: str = "gpt-4o-mini"
    CHAT_GUEST_MESSAGE_LIMIT: int = 3
    OPENAI_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    HF_TOKEN: str | None = None
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "clause_embeddings_bge_m3"
    RAG_USE_QDRANT: bool = True
    RAG_TOP_K: int = 8
    RAG_MIN_SCORE: float = 0.15
    RAG_DENSE_K: int = 24
    RAG_LEXICAL_K: int = 24
    RAG_FINAL_K: int = 10
    RAG_RRF_K: int = 60
    RAG_ENABLE_RERANK: bool = True
    RAG_RERANK_CANDIDATES: int = 40
    RAG_STRICT_MIN_SCORE: float = 0.24
    RAG_KEYWORD_WEIGHT: float = 0.15
    RAG_REWRITE_QUERY: bool = False
    RAG_REWRITE_MAX_TOKENS: int = 80
    RAG_FINAL_MAX_TOKENS: int = 420
    RAG_RERANK_MAX_TOKENS: int = 80
    RAG_FEWSHOT_ENABLED: bool = True
    RAG_FEWSHOT_FILE: str = "app/data/qa_fewshot.json"
    RAG_TABLE_ROW_TOP_K: int = 5
    RAG_TABLE_ROW_MIN_SCORE: float = 0.16
    RAG_TABLE_ROW_SCAN_LIMIT: int = 1200
    RAG_TABLE_INTENT_ROW_TOP_K: int = 8
    RAG_RICH_SOURCE_CLAUSE_THRESHOLD: float = 0.42
    RAG_IMAGE_TOP_K: int = 3
    RAG_IMAGE_MIN_SCORE: float = 0.22
    RAG_MULTILINGUAL_NATIVE_FIRST: bool = True
    RAG_MULTILINGUAL_TRANSLATE_FALLBACK: bool = True
    RAG_TRANSLATION_FALLBACK_THRESHOLD: float = 0.35
    RAG_TRANSLATED_QUERY_SCORE_WEIGHT: float = 0.97
    RAG_AMBIGUITY_SCORE_GAP: float = 0.03
    RAG_AMBIGUITY_MAX_DOCS: int = 6
    RAG_ALLOW_DOCUMENT_SUGGESTIONS: bool = False
    RAG_LOW_CONFIDENCE_FLOOR: float = 0.12
    RAG_NEAR_STRICT_MARGIN: float = 0.03
    RAG_DOC_DOMINANCE_MIN_RATIO: float = 0.8
    RAG_STRONG_KEYWORD_MIN: float = 0.3
    RAG_DOMINANCE_WINDOW: int = 5
    RAG_DOC_ROUTE_TOP_K: int = 3
    RAG_DOC_ROUTE_DENSE_K: int = 50
    RAG_DOC_ROUTE_MIN_SCORE: float = 0.12
    RAG_DOC_ROUTE_LLM_ENABLED: bool = False
    RAG_DOC_ROUTE_LLM_MODEL: str = "gpt-4.1-mini"
    RAG_DOC_ROUTE_LLM_MAX_CANDIDATES: int = 5
    RAG_DOC_ROUTE_CLOSE_RATIO: float = 0.9
    RAG_DOC_ROUTE_LOW_CONFIDENCE: float = 0.22
    RAG_DOC_ROUTE_GLOBAL_FALLBACK: bool = True
    RAG_ENABLE_SOFT_TABLE_PROBE: bool = False
    RAG_ENABLE_UNIFIED_RERANK: bool = True
    RAG_DUPLICATE_SIM_THRESHOLD: float = 0.9
    RAG_DEEP_CLAUSE_DISCOVERY: bool = True
    RAG_DEEP_CLAUSE_MULTIPLIER: int = 2
    RAG_NUMERIC_SCORE_WEIGHT: float = 0.24
    RAG_NUMERIC_RESCUE_MIN_SCORE: float = 0.08
    RAG_DEBUG_LOGGING: bool = True
    PIPELINE_MAX_PARALLEL: int = 2
    EMBEDDING_TIMEOUT_SECONDS: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
