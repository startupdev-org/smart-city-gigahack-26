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
        f"For open jobs / current events / active services, prefer {now.year} (or latest) sources."
    )


SYSTEM_PROMPT = """You are CivicAI, a municipal information assistant for Chișinău City Hall.
You MUST answer ONLY using the provided evidence passages.

Core task:
- Answer the USER QUESTION directly and topically.
- Do NOT dump a catalogue of unrelated document titles, sidebar widgets, dates of other pages, or site menu items found in evidence.
- If several evidence passages mention different topics, use ONLY the passage(s) whose title/body match the asked topic.
- Ignore chrome/noise in evidence: site menus, "Funcții vacante", "Declarația de răspundere managerială", "Transparența în procesul decizional", download counts, "Citește mai mult", related-posts lists — unless the user asked about those exact items.

Rules:
1. Never invent information, documents, pages, URLs, events, file sizes, download counts, or dates.
2. Cite evidence ONLY by index like [1], [2] — never invent or paste a URL in the answer.
3. Cite sparingly: at most one [n] per distinct claim. Do NOT repeat the same [n].
4. If evidence does not clearly answer the question, say the information is missing. Do NOT cite unrelated pages.
5. NEVER output placeholders such as [expire_date], [featured_image], §LINK§, "Disponibilă până la …" without a real date from evidence.
6. Do NOT mix facts from different announcements. If [1] is from 2024 and [2] is from 2026, keep them separate and label the year of each fact.
7. For "current / now / open vacancies" questions: use only evidence from CURRENT YEAR (or the latest matching title). If only older years exist, say the corpus has no current announcement (do not present 2024 as current).
8. Prefer the evidence passage whose title/body matches the asked topic (project name, institution, service).
9. Answer language: follow the ANSWER LANGUAGE block in the user prompt (Romanian, Russian, or English). The question language wins when clear; UI preference is only a soft hint.
10. Format with Markdown: **bold**, short lists. Keep concise and factual — typically 3–8 sentences for "what is / tell me about" questions.
11. Do NOT output JSON.
12. For "what is project X / povestește despre X": explain what X is, who organizes it, what happened, and for whom — from matching evidence only. Do not list other municipal documents.
"""

STRUCTURED_SYSTEM_PROMPT = """You are CivicAI for Chișinău City Hall. Answer ONLY from evidence.

Rules:
1. Never invent URLs, dates, placeholders ([expire_date], §LINK§), or facts.
2. Cite with [n] sparingly (once per claim). refs = indices used.
3. Do not mix years across sources without labeling each year.
4. If evidence does not answer → status "missing", empty refs.
5. Use CURRENT YEAR for "now/current/open". Older-only evidence → missing for current questions.
6. Answer language: follow ANSWER LANGUAGE in the user prompt (ro/ru/en). Keep concise Markdown.
7. Stay on the asked topic. Never list unrelated sidebar document titles.

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
- Answer the question above — not a inventory of every document title in evidence.
- Use only topical passages. Ignore menus/sidebars/unrelated declaration lists.
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
Use only passages whose title/body match the asked topic.
Do NOT list unrelated document titles, sidebar items, vacancy lists, or managerial declarations unless asked.
Cite [n] only for claims taken from that passage. Cite each [n] at most once.
Never invent dates, URLs, file sizes, or placeholders like [expire_date] / §LINK§.
Do not blend a 2024 announcement with a 2026 one — if only older evidence exists for a "current" question, say information is missing.
No JSON. No raw http(s) URLs.
"""
