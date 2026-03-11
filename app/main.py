from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.shnq import router as shnq_router
from app.api.upload import (
    resume_document_pipelines_on_startup,
    router as upload_router,
)
from app.db.base import Base
from app.db.schema_upgrade import ensure_section_category_schema
from app.db.session import engine
from app.models import *  # noqa: F401,F403


def create_app() -> FastAPI:
    app = FastAPI(
        title="SHNQ AI Backend",
        description="Multi-document RAG system for SHNQ",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # productionda aniq domain qo'ying
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(shnq_router, prefix="/api/conversations", tags=["Conversations"])
    app.include_router(auth_router, prefix="/api/auth", tags=["Auth"])
    app.include_router(chat_router, prefix="/api/chat", tags=["Chat"])
    app.include_router(upload_router, prefix="/api/upload", tags=["Upload"])

    @app.on_event("startup")
    def _resume_stuck_document_pipelines():
        resumed = resume_document_pipelines_on_startup(
            include_failed=False,
            limit=1000,
            max_parallel=None,
        )
        if resumed:
            print(f"[startup] Resumed {resumed} stuck document pipeline(s).")

    return app


Base.metadata.create_all(bind=engine)
ensure_section_category_schema(engine)
app = create_app()
