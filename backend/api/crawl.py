from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from backend.crawler.pipeline import run_crawl

router = APIRouter(prefix="/api/crawl", tags=["crawl"])


class CrawlRequest(BaseModel):
    max_pages: int = Field(100_000, ge=1, le=500_000)
    max_depth: int = Field(25, ge=0, le=50)
    hosts: list[str] | None = None
    seed_limit: int | None = Field(None, ge=1, le=500)


class CrawlResponse(BaseModel):
    status: str
    message: str


def _job(req: CrawlRequest) -> None:
    run_crawl(
        max_pages=req.max_pages,
        max_depth=req.max_depth,
        only_hosts=req.hosts,
        seed_limit=req.seed_limit,
    )


@router.post("/start", response_model=CrawlResponse)
def start_crawl(body: CrawlRequest, background: BackgroundTasks) -> CrawlResponse:
    background.add_task(_job, body)
    return CrawlResponse(
        status="started",
        message=(
            f"Crawl queued: max_pages={body.max_pages}, max_depth={body.max_depth}, "
            f"hosts={body.hosts or 'annex-all'}"
        ),
    )


@router.post("/run-sync")
def run_sync(body: CrawlRequest) -> dict:
    """Blocking crawl — use for small tests only."""
    return run_crawl(
        max_pages=body.max_pages,
        max_depth=body.max_depth,
        only_hosts=body.hosts,
        seed_limit=body.seed_limit,
    )
