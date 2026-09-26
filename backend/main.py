import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.api.admin import router as admin_router
from backend.api.auth import router as auth_router, seed_admin
from backend.api.chat import router as chat_router
from backend.api.chats import router as chats_router
from backend.api.crawl import router as crawl_router
from backend.api.search import router as search_router
from backend.db.database import Base, SessionLocal, engine

# register auth/admin/chat tables
from backend.api import admin as _admin  # noqa: F401
from backend.api import auth as _auth  # noqa: F401
from backend.api import chats as _chats  # noqa: F401

logger = logging.getLogger(__name__)

app = FastAPI(
    title="CivicAI API",
    description="Evidence-based municipal assistant for Chișinău",
    version="0.6.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(search_router)
app.include_router(chat_router)
app.include_router(chats_router)
app.include_router(crawl_router)
app.include_router(auth_router)
app.include_router(admin_router)


def _ensure_vector_index() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS chunks_embedding_vec_hnsw
                    ON chunks USING hnsw (embedding_vec vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                    """
                )
            )
        logger.info("pgvector HNSW index ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("HNSW index skipped: %s", exc)


def _migrate_schema() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS approved BOOLEAN DEFAULT FALSE"
                )
            )
            conn.execute(
                text("UPDATE users SET approved = TRUE WHERE role = 'admin'")
            )
            conn.execute(
                text("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS answer TEXT")
            )
            conn.execute(
                text("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS detail TEXT")
            )
        logger.info("Schema migrate ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Schema migrate: %s", exc)


@app.on_event("startup")
def on_startup() -> None:
    from backend.ai.mode_banner import print_llm_mode_banner
    from backend.ai.runtime_settings import get_llm_runtime

    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    with SessionLocal() as db:
        seed_admin(db)
    _ensure_vector_index()

    rt = get_llm_runtime()
    provider = rt.get("provider") or "local"
    model = (
        rt.get("local_model") if provider == "local" else rt.get("groq_model")
    ) or "?"
    print_llm_mode_banner(provider=provider, model=str(model))
    threading.Thread(target=_warm_models, daemon=True).start()


def _warm_models() -> None:
    """Eager-load local stack only when LLM provider is local."""
    from backend.ai.mode_banner import warm_local_stack
    from backend.ai.runtime_settings import get_llm_runtime

    rt = get_llm_runtime()
    provider = rt.get("provider") or "local"

    if provider == "local":
        logger.info("Local LLM mode — warming Ollama + RAG models…")
        warm_local_stack(include_rag=True, include_ollama=True)
    else:
        logger.info(
            "API LLM mode — skipping local model load "
            "(embeddings/reranker load lazily on first search; "
            "Ollama loads only when you switch to Local in Admin)"
        )


@app.get("/")
def root() -> dict:
    return {
        "name": "CivicAI",
        "phase": "fast-rag+stream+max-crawl",
        "endpoints": [
            "/api/health",
            "/api/search",
            "POST /api/chat",
            "POST /api/chat/stream",
            "POST /api/crawl/start",
            "POST /api/auth/login",
            "GET /api/admin/stats",
        ],
    }
