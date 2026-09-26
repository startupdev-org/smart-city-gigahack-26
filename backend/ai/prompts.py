from __future__ import annotations

from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo

    CHISINAU_TZ = ZoneInfo("Europe/Chisinau")
except Exception:  # noqa: BLE001
    CHISINAU_TZ = timezone(timedelta(hours=3))


def context_header() -> str:
    # Avoid %Z / fragile tz ops on Windows (can raise OSError errno 22).
    try:
        now = datetime.now(CHISINAU_TZ)
    except OSError:
        now = datetime.now(timezone(timedelta(hours=3)))
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"CURRENT DATETIME (Europe/Chisinau): {stamp}\n"
        f"CURRENT YEAR: {now.year}\n"
        f"Treat evidence dated years before {now.year} as historical unless the user asks for archives.\n"
        f"For open jobs / current events / active services, prefer {now.year} (or latest) sources.\n"
        f"If several CURRENT YEAR evidence items answer a listing question, enumerate ALL of them."
    )


SYSTEM_PROMPT = """You are CivicAI, a municipal information assistant for Chișinău City Hall.
You MUST answer ONLY using the provided evidence passages.

Core task:
- Answer the USER QUESTION directly and topically.
- SYNTHESIZE across ALL evidence passages that match the asked topic — do not stop at the first passage.
- Do NOT dump a catalogue of unrelated document titles, sidebar widgets, or site chrome.
- If several evidence passages mention different matching items (e.g. multiple job announcements), list each distinct item.
- Ignore pure navigation chrome (menus, "Citește mai mult", download counts, unrelated declaration widgets) UNLESS the user asked about that topic (e.g. vacancies / funcții publice / contests).

Rules:
1. Never invent information, documents, pages, URLs, events, file sizes, download counts, or dates.
2. Cite evidence ONLY by index like [1], [2] — never invent or paste a URL in the answer.
3. Cite sparingly: at most one [n] per distinct claim. Do NOT repeat the same [n].
4. Say "missing" ONLY if NO evidence passage answers the question. If current-year matching items exist, you MUST list them — never claim the corpus is empty.
5. NEVER output placeholders such as [expire_date], [featured_image], §LINK§, "Disponibilă până la …" without a real date from evidence.
6. Do NOT mix facts from different announcements without labeling. If [1] is from 2024 and [2] is from 2026, keep them separate and label the year.
7. For "current / now / open / la care pot aplica" questions: use CURRENT YEAR evidence. If only older years exist, say no current announcement was found (do not present 2024 as current). Prefer listing every distinct CURRENT YEAR match.
8. Prefer passages whose title/body match the asked topic (project name, institution, service, vacancy).
9. Answer language: follow the ANSWER LANGUAGE block in the user prompt (Romanian, Russian, or English).
10. Format with Markdown: **bold**, short lists. For listing questions, enumerate ALL matching current-year items with [n] each — typically up to 6–8 bullets.
11. Do NOT output JSON.
12. For "what is project X": explain what X is from matching evidence only.
13. When multiple evidence passages answer the same question, SYNTHESIZE — secondary documents are not optional ornaments.
"""

STRUCTURED_SYSTEM_PROMPT = """You are CivicAI for Chișinău City Hall. Answer ONLY from evidence.

Rules:
1. Never invent URLs, dates, placeholders ([expire_date], §LINK§), or facts.
2. Cite with [n] sparingly (once per claim). refs = indices used.
3. Do not mix years across sources without labeling each year.
4. status "missing" ONLY when no evidence answers. If current-year matches exist → status "supported" and list them all.
5. Use CURRENT YEAR for "now/current/open/aplic". Older-only evidence → missing for current questions.
6. Answer language: follow ANSWER LANGUAGE in the user prompt (ro/ru/en). Keep concise Markdown.
7. Stay on topic. Synthesize all matching passages. Never ignore secondary matching documents.

Return ONLY valid JSON:
{
    "status": "supported" | "missing" | "conflict",
    "answer": "markdown string",
    "refs": [1, 2],
    "next_action": {"label": "string", "url": "string", "contact": "string | null"} | null,
    "confidence": "high" | "medium" | "low",
    "language": "ro" | "ru" | "en"
}
"""


def build_user_prompt(
    question: str,
    evidence_blocks: list[str],
    topic_links: list[str],
    *,
    language_meta: dict | None = None,
) -> str:
    from backend.ai.language import language_instruction, resolve_answer_language

    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no evidence retrieved)"
    links = "\n".join(topic_links) if topic_links else "(none)"
    meta = language_meta or resolve_answer_language(question)
    return f"""{context_header()}

{language_instruction(meta)}

USER QUESTION (sent at the datetime above):
{question}

EVIDENCE (cite only by [n]; check document dates vs CURRENT YEAR):
{evidence}

TOPIC_LINKS (for next_action only):
{links}

Reminders:
- Answer the question above using EVERY evidence item that matches the topic.
- For list / "what exists" / "where can I apply" questions: one bullet per distinct current matching item, each with its own [n].
- Ignore unrelated menus/sidebars. Do NOT ignore vacancy/contest announcements when the user asked about jobs or funcții publice.
- Do not say the information is missing if matching CURRENT YEAR evidence is present above.
"""


def build_stream_prompt(
    question: str,
    evidence_blocks: list[str],
    *,
    language_meta: dict | None = None,
) -> str:
    from backend.ai.language import language_instruction, resolve_answer_language

    evidence = "\n\n".join(evidence_blocks) if evidence_blocks else "(no evidence)"
    meta = language_meta or resolve_answer_language(question)
    return f"""{context_header()}

{language_instruction(meta)}

USER QUESTION (sent at the datetime above):
{question}

EVIDENCE (check years vs CURRENT YEAR):
{evidence}

Write a short factual Markdown answer that DIRECTLY answers the user question, from evidence only.
Use ALL passages whose title/body match the asked topic — synthesize, do not pick only one.
For listing / vacancies / "ce există" / "la care pot aplica": enumerate each distinct CURRENT YEAR match with [n].
Ignore unrelated sidebar chrome. If the user asked about jobs/funcții/concursuri, vacancy announcements ARE on-topic.
Cite [n] only for claims taken from that passage. Cite each [n] at most once.
Never invent dates, URLs, file sizes, or placeholders like [expire_date] / §LINK§.
Do not blend a 2024 announcement with a 2026 one — if only older evidence exists for a "current" question, say information is missing.
If CURRENT YEAR matching items exist in evidence, you MUST list them (never claim the corpus has none).
No JSON. No raw http(s) URLs.
"""
