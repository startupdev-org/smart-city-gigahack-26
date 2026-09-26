"""Real-world LLM / embedding pricing + municipal ops cost projections."""

from __future__ import annotations

from typing import Any

# Prices USD per 1M tokens (input / output). Updated for GigaHack planning (2025–2026 ballpark).
# Sources: public vendor pricing pages — treat as planning estimates, not invoices.

LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "local_ollama": {
        "label": "Local · Ollama (qwen3:8b)",
        "input_per_m": 0.0,
        "output_per_m": 0.0,
        "notes": "Cost = electricitate + amortizare GPU/PC",
        "category": "self_hosted",
    },
    "groq_llama70b": {
        "label": "Groq · Llama 3.3 70B",
        "input_per_m": 0.59,
        "output_per_m": 0.79,
        "notes": "https://groq.com/pricing",
        "category": "cloud",
    },
    "groq_gpt_oss_120b": {
        "label": "Groq · openai/gpt-oss-120b",
        "input_per_m": 0.15,
        "output_per_m": 0.60,
        "notes": "Groq OSS tier (indicativ)",
        "category": "cloud",
    },
    "groq_llama8b": {
        "label": "Groq · Llama 3.1 8B Instant",
        "input_per_m": 0.05,
        "output_per_m": 0.08,
        "notes": "https://groq.com/pricing",
        "category": "cloud",
    },
    "openai_gpt4o_mini": {
        "label": "OpenAI · GPT-4o mini",
        "input_per_m": 0.15,
        "output_per_m": 0.60,
        "notes": "https://openai.com/api/pricing",
        "category": "cloud",
    },
    "openai_gpt4o": {
        "label": "OpenAI · GPT-4o",
        "input_per_m": 2.50,
        "output_per_m": 10.00,
        "notes": "https://openai.com/api/pricing",
        "category": "cloud",
    },
    "openai_gpt41": {
        "label": "OpenAI · GPT-4.1",
        "input_per_m": 2.00,
        "output_per_m": 8.00,
        "notes": "indicativ",
        "category": "cloud",
    },
    "anthropic_haiku": {
        "label": "Anthropic · Claude 3.5 Haiku",
        "input_per_m": 0.80,
        "output_per_m": 4.00,
        "notes": "https://www.anthropic.com/pricing",
        "category": "cloud",
    },
    "anthropic_sonnet": {
        "label": "Anthropic · Claude Sonnet 4",
        "input_per_m": 3.00,
        "output_per_m": 15.00,
        "notes": "https://www.anthropic.com/pricing",
        "category": "cloud",
    },
    "google_flash": {
        "label": "Google · Gemini 2.0 Flash",
        "input_per_m": 0.10,
        "output_per_m": 0.40,
        "notes": "https://ai.google.dev/pricing",
        "category": "cloud",
    },
    "google_pro": {
        "label": "Google · Gemini 1.5 Pro",
        "input_per_m": 1.25,
        "output_per_m": 5.00,
        "notes": "indicativ",
        "category": "cloud",
    },
    "mistral_small": {
        "label": "Mistral · Small",
        "input_per_m": 0.10,
        "output_per_m": 0.30,
        "notes": "https://mistral.ai/products/la-plateforme",
        "category": "cloud",
    },
    "deepseek_chat": {
        "label": "DeepSeek · Chat",
        "input_per_m": 0.27,
        "output_per_m": 1.10,
        "notes": "https://api-docs.deepseek.com/quick_start/pricing",
        "category": "cloud",
    },
}

EMBEDDING_PROVIDERS: dict[str, dict[str, Any]] = {
    "local_bge_m3": {
        "label": "Local · BGE-M3",
        "per_m": 0.0,
        "notes": "inclus în self-hosted",
    },
    "openai_embed_3_small": {
        "label": "OpenAI · text-embedding-3-small",
        "per_m": 0.02,
        "notes": "https://openai.com/api/pricing",
    },
    "openai_embed_3_large": {
        "label": "OpenAI · text-embedding-3-large",
        "per_m": 0.13,
        "notes": "https://openai.com/api/pricing",
    },
    "voyage_2": {
        "label": "Voyage · voyage-2",
        "per_m": 0.10,
        "notes": "indicativ",
    },
}

RERANK_PROVIDERS: dict[str, dict[str, Any]] = {
    "local_bge": {
        "label": "Local · bge-reranker-v2-m3",
        "per_1k_queries": 0.0,
        "notes": "self-hosted",
    },
    "cohere_rerank": {
        "label": "Cohere · Rerank 3.5",
        "per_1k_queries": 2.00,
        "notes": "≈ $2 / 1k search units (indicativ)",
    },
}

FX_MDL_PER_USD = 17.85  # BNM-ish planning rate (EUR/USD basket ≈ MD)

# Estimated monthly OPEX for CivicAI on a Chișinău on-prem / hybrid box
# (not the placeholder 40/18/5… — calibrated for always-on RAG + light support)
DEFAULT_OPEX = {
    "infra_fixed_usd": 55.0,  # share: PC/server amortizare, UPS, router, monitoring
    "electricity_usd": 28.0,  # ~180–220W avg × 24/7 × ~3.5 MDL/kWh
    "storage_usd": 12.0,  # Postgres + embeddings + backups growth
    "bandwidth_usd": 14.0,  # crawl bursts + API egress via CF origin
    "support_hours": 16.0,  # ~2 zile ops / lună (ingest, feedback, hotfix)
    "support_hourly_usd": 15.0,  # tarif ops MD (USD)
    "target_profit_usd": 450.0,
    "margin_pct": 30.0,  # preferred planning lever when set
    "fx_mdl": FX_MDL_PER_USD,
    "active_users": 200,
    "requests_per_user_month": 28.0,
}


def _round(x: float, n: int = 4) -> float:
    return round(float(x), n)


def llm_cost_usd(
    *,
    questions: int,
    avg_in: int,
    avg_out: int,
    provider_id: str,
    tool_calls_per_q: float = 1.2,
    tool_extra_in: int = 400,
    tool_extra_out: int = 120,
) -> dict[str, Any]:
    p = LLM_PROVIDERS.get(provider_id) or LLM_PROVIDERS["groq_llama70b"]
    # main answer turn + tool/agent turns
    total_in = questions * (avg_in + tool_calls_per_q * tool_extra_in)
    total_out = questions * (avg_out + tool_calls_per_q * tool_extra_out)
    cost = total_in / 1_000_000 * p["input_per_m"] + total_out / 1_000_000 * p["output_per_m"]
    return {
        "provider_id": provider_id,
        "label": p["label"],
        "category": p["category"],
        "input_tokens": int(total_in),
        "output_tokens": int(total_out),
        "input_usd": _round(total_in / 1_000_000 * p["input_per_m"]),
        "output_usd": _round(total_out / 1_000_000 * p["output_per_m"]),
        "total_usd": _round(cost),
        "notes": p["notes"],
        "rates": {"input_per_m": p["input_per_m"], "output_per_m": p["output_per_m"]},
    }


def embedding_cost_usd(*, chunks_indexed: int, avg_tokens_per_chunk: int, provider_id: str) -> dict[str, Any]:
    p = EMBEDDING_PROVIDERS.get(provider_id) or EMBEDDING_PROVIDERS["local_bge_m3"]
    tokens = chunks_indexed * avg_tokens_per_chunk
    cost = tokens / 1_000_000 * p["per_m"]
    return {
        "provider_id": provider_id,
        "label": p["label"],
        "tokens": int(tokens),
        "total_usd": _round(cost),
        "notes": p["notes"],
        "rate_per_m": p["per_m"],
    }


def rerank_cost_usd(*, questions: int, provider_id: str) -> dict[str, Any]:
    p = RERANK_PROVIDERS.get(provider_id) or RERANK_PROVIDERS["local_bge"]
    cost = questions / 1000 * p["per_1k_queries"]
    return {
        "provider_id": provider_id,
        "label": p["label"],
        "queries": questions,
        "total_usd": _round(cost),
        "notes": p["notes"],
        "rate_per_1k": p["per_1k_queries"],
    }


def project_costs(
    *,
    active_users: int | None = None,
    requests_per_user_month: float | None = None,
    avg_input_tokens: int = 1400,
    avg_output_tokens: int = 420,
    tool_calls_per_q: float = 1.3,
    llm_provider: str = "groq_gpt_oss_120b",
    embedding_provider: str = "local_bge_m3",
    rerank_provider: str = "local_bge",
    chunks_indexed: int = 0,
    avg_chunk_tokens: int = 400,
    infra_fixed_usd: float | None = None,
    electricity_usd: float | None = None,
    storage_usd: float | None = None,
    bandwidth_usd: float | None = None,
    support_hours: float | None = None,
    support_hourly_usd: float | None = None,
    target_profit_usd: float | None = None,
    margin_pct: float | None = None,
    fx_mdl: float | None = None,
) -> dict[str, Any]:
    d = DEFAULT_OPEX
    active_users = int(active_users if active_users is not None else d["active_users"])
    requests_per_user_month = float(
        requests_per_user_month
        if requests_per_user_month is not None
        else d["requests_per_user_month"]
    )
    infra_fixed_usd = float(
        infra_fixed_usd if infra_fixed_usd is not None else d["infra_fixed_usd"]
    )
    electricity_usd = float(
        electricity_usd if electricity_usd is not None else d["electricity_usd"]
    )
    storage_usd = float(storage_usd if storage_usd is not None else d["storage_usd"])
    bandwidth_usd = float(
        bandwidth_usd if bandwidth_usd is not None else d["bandwidth_usd"]
    )
    support_hours = float(
        support_hours if support_hours is not None else d["support_hours"]
    )
    support_hourly_usd = float(
        support_hourly_usd
        if support_hourly_usd is not None
        else d["support_hourly_usd"]
    )
    target_profit_usd = float(
        target_profit_usd if target_profit_usd is not None else d["target_profit_usd"]
    )
    fx_mdl = float(fx_mdl if fx_mdl is not None else d["fx_mdl"])
    # margin_pct stays None unless caller sets it (None → profit-target mode)
    questions = int(round(active_users * requests_per_user_month))
    llm = llm_cost_usd(
        questions=questions,
        avg_in=avg_input_tokens,
        avg_out=avg_output_tokens,
        provider_id=llm_provider,
        tool_calls_per_q=tool_calls_per_q,
    )
    emb = embedding_cost_usd(
        chunks_indexed=chunks_indexed,
        avg_tokens_per_chunk=avg_chunk_tokens,
        provider_id=embedding_provider,
    )
    # amortize re-embed monthly delta ~5% of corpus
    emb_monthly = dict(emb)
    emb_monthly["total_usd"] = _round(emb["total_usd"] * 0.05)
    emb_monthly["note_amortized"] = "5% corpus refresh / lună"
    rr = rerank_cost_usd(questions=questions, provider_id=rerank_provider)

    support = _round(support_hours * support_hourly_usd)
    opex = {
        "llm_usd": llm["total_usd"],
        "embeddings_usd": emb_monthly["total_usd"],
        "rerank_usd": rr["total_usd"],
        "infra_fixed_usd": _round(infra_fixed_usd),
        "electricity_usd": _round(electricity_usd),
        "storage_usd": _round(storage_usd),
        "bandwidth_usd": _round(bandwidth_usd),
        "support_usd": support,
    }
    variable = _round(llm["total_usd"] + emb_monthly["total_usd"] + rr["total_usd"])
    fixed = _round(
        infra_fixed_usd + electricity_usd + storage_usd + bandwidth_usd + support
    )
    total_cost = _round(variable + fixed)

    if margin_pct is not None:
        # price from margin: cost / (1 - margin)
        m = max(0.0, min(0.95, margin_pct / 100.0))
        revenue_needed = _round(total_cost / (1 - m)) if m < 1 else total_cost
        profit = _round(revenue_needed - total_cost)
    else:
        profit = _round(target_profit_usd)
        revenue_needed = _round(total_cost + profit)

    per_user = _round(revenue_needed / active_users) if active_users else 0.0
    per_request = _round(revenue_needed / questions) if questions else 0.0
    break_even_users = (
        int(round(fixed / max(0.01, (revenue_needed / active_users) - (variable / max(1, active_users)))))
        if active_users and revenue_needed > variable
        else active_users
    )

    # scenario matrix across providers
    scenarios = []
    for pid in (
        "local_ollama",
        "groq_llama8b",
        "groq_gpt_oss_120b",
        "groq_llama70b",
        "openai_gpt4o_mini",
        "openai_gpt4o",
        "anthropic_haiku",
        "anthropic_sonnet",
        "google_flash",
        "deepseek_chat",
        "mistral_small",
    ):
        sc = llm_cost_usd(
            questions=questions,
            avg_in=avg_input_tokens,
            avg_out=avg_output_tokens,
            provider_id=pid,
            tool_calls_per_q=tool_calls_per_q,
        )
        sc_total = _round(sc["total_usd"] + emb_monthly["total_usd"] + rr["total_usd"] + fixed)
        scenarios.append(
            {
                **sc,
                "stack_total_usd": sc_total,
                "stack_total_mdl": _round(sc_total * fx_mdl, 0),
                "suggested_price_per_user_usd": _round(
                    (sc_total + target_profit_usd) / active_users
                )
                if active_users
                else None,
            }
        )
    scenarios.sort(key=lambda x: x["stack_total_usd"])

    # sensitivity: users × requests cloud
    sensitivity = []
    for u in sorted({max(1, active_users // 2), active_users, active_users * 2, active_users * 5}):
        for r in sorted(
            {
                max(1.0, requests_per_user_month / 2),
                requests_per_user_month,
                requests_per_user_month * 2,
            }
        ):
            q = int(round(u * r))
            c = llm_cost_usd(
                questions=q,
                avg_in=avg_input_tokens,
                avg_out=avg_output_tokens,
                provider_id=llm_provider,
                tool_calls_per_q=tool_calls_per_q,
            )["total_usd"]
            sens_total = _round(c + emb_monthly["total_usd"] + rr["total_usd"] + fixed)
            sensitivity.append(
                {
                    "users": u,
                    "req_per_user": r,
                    "questions": q,
                    "total_cost_usd": sens_total,
                    "per_user_cost_usd": _round(sens_total / u),
                }
            )

    return {
        "inputs": {
            "active_users": active_users,
            "requests_per_user_month": requests_per_user_month,
            "questions_per_month": questions,
            "avg_input_tokens": avg_input_tokens,
            "avg_output_tokens": avg_output_tokens,
            "tool_calls_per_q": tool_calls_per_q,
            "llm_provider": llm_provider,
            "embedding_provider": embedding_provider,
            "rerank_provider": rerank_provider,
            "target_profit_usd": target_profit_usd,
            "margin_pct": margin_pct,
            "fx_mdl_per_usd": fx_mdl,
        },
        "breakdown": opex,
        "totals": {
            "variable_usd": variable,
            "fixed_usd": fixed,
            "total_cost_usd": total_cost,
            "total_cost_mdl": _round(total_cost * fx_mdl, 0),
            "revenue_needed_usd": revenue_needed,
            "revenue_needed_mdl": _round(revenue_needed * fx_mdl, 0),
            "profit_usd": profit,
            "profit_mdl": _round(profit * fx_mdl, 0),
            "margin_realized_pct": _round(100 * profit / revenue_needed, 1)
            if revenue_needed
            else 0,
            "price_per_user_month_usd": per_user,
            "price_per_user_month_mdl": _round(per_user * fx_mdl, 0),
            "price_per_request_usd": per_request,
            "cost_per_request_usd": _round(total_cost / questions, 4) if questions else 0,
            "break_even_users_approx": break_even_users,
        },
        "llm": llm,
        "embeddings": emb_monthly,
        "rerank": rr,
        "provider_catalog": {
            "llm": [
                {"id": k, "label": v["label"], "in": v["input_per_m"], "out": v["output_per_m"]}
                for k, v in LLM_PROVIDERS.items()
            ],
            "embedding": [
                {"id": k, "label": v["label"], "per_m": v["per_m"]}
                for k, v in EMBEDDING_PROVIDERS.items()
            ],
            "rerank": [
                {"id": k, "label": v["label"], "per_1k": v["per_1k_queries"]}
                for k, v in RERANK_PROVIDERS.items()
            ],
        },
        "scenarios": scenarios,
        "sensitivity": sensitivity,
        "recommendation": _recommend(scenarios, total_cost, llm_provider),
    }


def _recommend(scenarios: list[dict], current_total: float, current_id: str) -> str:
    if not scenarios:
        return "Insufficient data."
    best = scenarios[0]
    cur = next((s for s in scenarios if s["provider_id"] == current_id), None)
    lines = [
        f"Cel mai ieftin stack: {best['label']} ≈ ${best['stack_total_usd']}/lună.",
    ]
    if cur and cur["provider_id"] != best["provider_id"]:
        delta = _round(cur["stack_total_usd"] - best["stack_total_usd"])
        lines.append(
            f"Față de selecția curentă ({cur['label']}) economisești ~${delta}/lună trecând pe {best['label']}."
        )
    local = next((s for s in scenarios if s["provider_id"] == "local_ollama"), None)
    if local:
        lines.append(
            f"Self-hosted rămâne cel mai confidențial: ~${local['stack_total_usd']}/lună (infra + energie)."
        )
    return " ".join(lines)


def catalog() -> dict[str, Any]:
    return {
        "llm": LLM_PROVIDERS,
        "embedding": EMBEDDING_PROVIDERS,
        "rerank": RERANK_PROVIDERS,
        "fx_mdl_per_usd": FX_MDL_PER_USD,
        "default_opex": DEFAULT_OPEX,
        "opex_notes": {
            "infra_fixed_usd": "Amortizare PC/server + UPS + rețea + monitoring (share lunar)",
            "electricity_usd": "Workstation RAG ~200W × 24/7 la tariful MD (~3.5 MDL/kWh)",
            "storage_usd": "Creștere Postgres/pgvector + backup-uri",
            "bandwidth_usd": "Crawl periodic + răspunsuri API prin origin Cloudflare",
            "support_hours": "~2 zile ops / lună (ingest, feedback, hotfix)",
            "support_hourly_usd": "Tarif ops Chișinău (USD)",
            "margin_pct": "Marjă țintă pe venit (preferată față de profit fix)",
        },
    }
