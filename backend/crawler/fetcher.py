from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes
    final_url: str


class Fetcher:
    def __init__(self) -> None:
        settings = get_settings()
        self.timeout = settings.crawl_timeout_s
        self.headers = {
            "User-Agent": settings.crawl_user_agent,
            "Accept": "*/*",
        }

    def fetch(self, url: str) -> FetchResult | None:
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.headers,
            ) as client:
                resp = client.get(url)
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                return FetchResult(
                    url=url,
                    status=resp.status_code,
                    content_type=ctype or "application/octet-stream",
                    body=resp.content,
                    final_url=str(resp.url),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetch failed %s: %s", url, exc)
            return None
