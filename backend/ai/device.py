"""Shared torch device selection for embeddings / reranker."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def pick_torch_device() -> str:
    """Return 'cuda', 'mps', or 'cpu' and log once-friendly detail."""
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            logger.info("Torch device: CUDA (%s) · torch=%s", name, torch.__version__)
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            logger.info("Torch device: MPS · torch=%s", torch.__version__)
            return "mps"
        logger.info(
            "Torch device: CPU · torch=%s cuda_built=%s",
            torch.__version__,
            getattr(torch.version, "cuda", None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Torch device: CPU (%s)", exc)
    return "cpu"


def cuda_summary() -> str:
    """Short string for startup banners."""
    try:
        import torch

        if torch.cuda.is_available():
            return f"CUDA · {torch.cuda.get_device_name(0)}"
        built = getattr(torch.version, "cuda", None)
        if built:
            return f"CPU (torch+cu{built} but no GPU)"
        return "CPU"
    except Exception:  # noqa: BLE001
        return "CPU"
