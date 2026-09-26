from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from backend.config import get_settings

logger = logging.getLogger(__name__)


def _pick_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            logger.info("Embeddings device: CUDA (%s)", name)
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            logger.info("Embeddings device: MPS")
            return "mps"
    except Exception:  # noqa: BLE001
        pass
    logger.info("Embeddings device: CPU")
    return "cpu"


class EmbeddingService:
    """BAAI/bge-m3 via sentence-transformers (GPU when available, else CPU)."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or get_settings().embedding_model
        self._model = None
        self._device: str | None = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._device = _pick_device()
            logger.info("Loading embedding model %s on %s …", self.model_name, self._device)
            self._model = SentenceTransformer(self.model_name, device=self._device)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32 if self._device == "cuda" else 8,
        )
        return [v.astype(np.float32).tolist() for v in np.asarray(vectors)]

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        query = f"Represent this sentence for searching relevant passages: {text}"
        vector = model.encode(
            query,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=1,
        )
        return np.asarray(vector, dtype=np.float32).tolist()

    def warm(self) -> None:
        self.embed_query("autorizatie construire Chisinau")


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
