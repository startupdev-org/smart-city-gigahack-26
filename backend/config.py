from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/civic_ai"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    # LLM provider: local (Ollama) | groq (Groq Cloud OpenAI-compatible API)
    llm_provider: str = "local"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    embedding_dim: int = 1024
    jwt_secret: str = "civic-ai-dev-secret-change-me"
    openai_api_key: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    chunk_size_tokens: int = 650
    chunk_overlap_tokens: int = 100
    retrieve_dense_k: int = 6
    retrieve_lexical_k: int = 6
    rerank_candidates: int = 6
    rerank_top_k: int = 4
    # Crawler — absolute maximal annex / source coverage
    crawl_max_pages: int = 100_000
    crawl_max_depth: int = 25
    crawl_delay_ms: int = 25
    crawl_timeout_s: float = 45.0
    crawl_sitemap_max_urls: int = 8_000
    crawl_user_agent: str = (
        "CivicAI-Crawler/0.2 (+https://localhost; municipal hackathon research)"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
