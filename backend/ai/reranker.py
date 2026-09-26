from __future__ import annotations

import logging
from functools import lru_cache

from backend.config import get_settings

logger = logging.getLogger(__name__)


class RerankerService:
    """BAAI/bge-reranker-v2-m3 — mandatory, tuned for low latency."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or get_settings().reranker_model
        self._ranker = None

    def _load(self):
        if self._ranker is None:
            from FlagEmbedding import FlagReranker

            logger.info("Loading reranker %s …", self.model_name)
            # shorter max_length ≈ much faster on CPU / 8GB GPU
            self._ranker = FlagReranker(
                self.model_name,
                use_fp16=False,
                max_length=128,
            )
        return self._ranker

    def warm(self) -> None:
        ranker = self._load()
        ranker.compute_score([["test", "pasaj test"]], normalize=True)

    def rerank(
        self,
        query: str,
        passages: list[str],
        top_k: int | None = None,
    ) -> list[tuple[int, float]]:
        if not passages:
            return []
        k = top_k or get_settings().rerank_top_k
        ranker = self._load()
        pairs = [[query, p] for p in passages]
        scores = ranker.compute_score(pairs, normalize=True)
        if isinstance(scores, (float, int)):
            scores = [float(scores)]
        ranked = sorted(enumerate(scores), key=lambda x: float(x[1]), reverse=True)
        return [(i, float(s)) for i, s in ranked[:k]]


@lru_cache
def get_reranker_service() -> RerankerService:
    return RerankerService()
