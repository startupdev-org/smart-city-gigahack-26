"""Measure the real CivicAI streaming path without saving credentials.

Examples:
  CIVICAI_EMAIL=you@example.com CIVICAI_PASSWORD=... python3 scripts/benchmark_ai.py
  CIVICAI_TOKEN=... python3 scripts/benchmark_ai.py --repeat 3 --output /tmp/civicai-benchmark.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CASES = {
    "documents_ro": ("Ce acte îmi trebuie pentru autorizația de construire?", "ro"),
    "documents_ru": ("Какие документы нужны для разрешения на строительство?", "ru"),
    "deadline": ("Există contradicții privind termenul autorizației de construire?", "ro"),
    "current_jobs": ("Există concursuri pentru funcții publice vacante acum?", "ro"),
    "contact": ("Care este contactul DGAURF?", "ro"),
    "missing": ("Informație despre vacanța inventată XYZ123 care nu există", "ro"),
}


def request_json(base: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(
        base + path,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if body else "GET",
    )
    with urlopen(req, timeout=10) as response:
        return json.load(response)


def access_token(base: str) -> str:
    token = os.environ.get("CIVICAI_TOKEN", "").strip()
    if token:
        return token
    email = "admin@civic.ai".strip()
    password = "admin123".strip()
    if not email or not password:
        raise ValueError("Set CIVICAI_TOKEN or CIVICAI_EMAIL and CIVICAI_PASSWORD")
    return request_json(
        base, "/api/auth/login", {"email": email, "password": password}
    )["access_token"]


def run_case(base: str, token: str, name: str, timeout: float) -> dict:
    question, language = CASES[name]
    body = json.dumps(
        {"question": question, "top_k": 12, "ui_language": language}
    ).encode("utf-8")
    req = Request(
        base + "/api/chat/stream",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    started = time.perf_counter()
    first_token_ms = None
    tools = []
    result = None
    event_name = "message"
    data_lines = []

    def consume_event() -> None:
        nonlocal first_token_ms, result
        if not data_lines:
            return
        try:
            data = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return
        if event_name == "token" and first_token_ms is None:
            first_token_ms = round((time.perf_counter() - started) * 1000)
        elif event_name == "tool" and data.get("status") in ("done", "error"):
            tools.append(
                {
                    "name": data.get("name"),
                    "status": data.get("status"),
                    "ms": data.get("ms"),
                    "detail": data.get("detail"),
                }
            )
        elif event_name == "result":
            result = data

    with urlopen(req, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                consume_event()
                event_name = "message"
                data_lines = []
            elif line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        consume_event()

    wall_ms = round((time.perf_counter() - started) * 1000)
    if result is None:
        raise RuntimeError("Stream ended without a result event")
    answer = result.get("answer") or ""
    status = result.get("status")
    source_count = len(result.get("sources") or [])
    citation_count = len(re.findall(r"\[\d+\]", answer))
    quality_flags = []
    if not answer.strip():
        quality_flags.append("empty_answer")
    if status in ("supported", "conflict") and not source_count:
        quality_flags.append("claim_without_source")
    if name == "missing" and status != "missing":
        quality_flags.append("invented_topic_not_marked_missing")
    return {
        "case": name,
        "question": question,
        "status": status,
        "wall_ms": wall_ms,
        "first_token_ms": first_token_ms,
        "server_latency_ms": result.get("latency_ms"),
        "sources": source_count,
        "citations": citation_count,
        "quality_flags": quality_flags,
        "confidence": result.get("confidence"),
        "answer": answer,
        "tools": tools,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--case", action="append", choices=CASES, dest="cases")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    base = args.base_url.rstrip("/")
    try:
        health = request_json(base, "/api/health")
        token = access_token(base)
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 2
    print(f"API: {health.get('status', 'unknown')} | cases: {len(args.cases or CASES)} | repeat: {args.repeat}")
    rows = []
    for _ in range(args.repeat):
        for name in args.cases or CASES:
            try:
                row = run_case(base, token, name, args.timeout)
            except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
                row = {"case": name, "error": str(exc)}
            rows.append(row)
            if "error" in row:
                print(f"{name:15} ERROR {row['error']}")
            else:
                print(
                    f"{name:15} {str(row['status']):10} "
                    f"total={row['wall_ms']:6}ms first={str(row['first_token_ms']):>6}ms "
                    f"sources={row['sources']} citations={row['citations']}"
                    + (f" flags={','.join(row['quality_flags'])}" if row["quality_flags"] else "")
                )
    successful = [r for r in rows if "wall_ms" in r]
    wall_times = sorted(r["wall_ms"] for r in successful)
    summary = {
        "completed": len(successful),
        "failed": len(rows) - len(successful),
        "median_wall_ms": round(statistics.median(r["wall_ms"] for r in successful))
        if successful else None,
        "max_wall_ms": max((r["wall_ms"] for r in successful), default=None),
        "p95_wall_ms": wall_times[max(0, (95 * len(wall_times) + 99) // 100 - 1)]
        if wall_times else None,
        "median_first_token_ms": round(
            statistics.median(
                r["first_token_ms"] for r in successful if r["first_token_ms"] is not None
            )
        ) if any(r["first_token_ms"] is not None for r in successful) else None,
        "quality_flags": sum(len(r["quality_flags"]) for r in successful),
    }
    print("Summary:", json.dumps(summary, ensure_ascii=False))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"summary": summary, "results": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved: {args.output}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
