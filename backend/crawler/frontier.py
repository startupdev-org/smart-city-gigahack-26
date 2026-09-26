from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(order=True)
class FrontierItem:
    priority: int
    depth: int
    url: str = field(compare=False)


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    if h.startswith("www."):
        h = h[4:]
    return h or "unknown"


class Frontier:
    """Priority frontier with per-host rotation so one site cannot monopolize the crawl."""

    def __init__(self) -> None:
        self._by_host: dict[str, deque[FrontierItem]] = defaultdict(deque)
        self._hosts: deque[str] = deque()
        self._seen: set[str] = set()
        self._host_counts: dict[str, int] = defaultdict(int)

    def add(self, url: str, *, depth: int = 0, priority: int = 100) -> bool:
        if url in self._seen:
            return False
        self._seen.add(url)
        host = _host(url)
        item = FrontierItem(priority=priority, depth=depth, url=url)
        q = self._by_host[host]
        was_empty = len(q) == 0
        # insert by priority (lower first)
        inserted = False
        for i, existing in enumerate(q):
            if (item.priority, item.depth) < (existing.priority, existing.depth):
                q.insert(i, item)
                inserted = True
                break
        if not inserted:
            q.append(item)
        if was_empty:
            self._hosts.append(host)
        return True

    def pop(self) -> FrontierItem | None:
        if not self._hosts:
            return None
        # pick host with fewest fetched so far among those with queue
        best_host = None
        best_score = None
        for _ in range(len(self._hosts)):
            host = self._hosts[0]
            self._hosts.rotate(-1)
            if not self._by_host[host]:
                continue
            score = (self._host_counts[host], self._by_host[host][0].priority)
            if best_score is None or score < best_score:
                best_score = score
                best_host = host
        if best_host is None:
            # cleanup empty
            self._hosts = deque(h for h in self._hosts if self._by_host[h])
            return None
        item = self._by_host[best_host].popleft()
        self._host_counts[best_host] += 1
        if not self._by_host[best_host]:
            self._by_host.pop(best_host, None)
            self._hosts = deque(h for h in self._hosts if h != best_host)
        return item

    def __len__(self) -> int:
        return sum(len(q) for q in self._by_host.values())

    @property
    def seen_count(self) -> int:
        return len(self._seen)
