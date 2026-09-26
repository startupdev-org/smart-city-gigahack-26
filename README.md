# smart-city-gigahack-26

# CivicAI

### Evidence-based AI assistant for Chișinău

> **„Nu doar îți răspundem. Îți arătăm exact de unde știm.”**

Asistent AI municipal peste corpusul oficial al Primăriei: răspunsuri verificate în **română și rusă**, cu **citat exact (document + pasaj)**, flag pentru **lipsă / contradicție**, **navigare către pagina de contact** relevantă, plus **estimare cost lunar** (local vs API).

**Deploy:** totul pe acest PC, **fără Docker**.  
**Surse:** vezi [`sources.md`](./sources.md).

---

## Aliniere la challenge (must-have)

| Cerință | Cum o acoperim |
|---------|----------------|
| Răspunsuri pe corpus definit | RAG pe sursele din `sources.md` |
| RO + RU | Detectare limbă + UI bilingv + aceleași citări |
| Citare document + pasaj | Chunk metadata + panel Evidence + highlight |
| Missing / conflict | Status structurat `missing` \| `conflict` + UI dedicat |
| Website navigation | Card „Unde mergeți mai departe?” + mapping topic→URL |
| Cost lunar model | Pagină/admin Cost: self-hosted vs API |
| Bonus feedback | 👍/👎 + motiv + agregat în Admin |
| Bonus inovație | Living Municipal Knowledge Base (versiuni + conflicte + next action) |

---

## 1. Demo live (obligatoriu)

```text
Cetățean / Angajat:
"Ce acte sunt necesare pentru X?"
        ↓
  CivicAI (auth session)
        ↓
  Hybrid Retrieval + Reranker
        ↓
  Top 5 evidence
        ↓
  Evidence verification
        ↓
  Qwen3 (Ollama) → JSON structurat
        ↓
┌──────────────────────────────────────┐
│ Răspuns + listă acte                 │
│ Surse: Regulamentul X, §3 · p.4      │
│ ✓ Informație verificată              │
│ → Contact / pagină oficială          │
└──────────────────────────────────────┘
```

### Situații de demonstrat

| Situație | Exemplu | Output |
|----------|---------|--------|
| **Normal** | „Care sunt pașii pentru X?” | Răspuns + surse + next-action |
| **Lipsă** | „Care este amenda pentru Y?” | ⚠️ Nu e în corpus + link contact |
| **Conflict** | „Care este termenul pentru X?” | ⚠️ Contradicție A vs B (side-by-side) |
| **Bilingv** | Aceeași întrebare în RU | Răspuns RU, aceleași surse |
| **Change** | Admin: regulament actualizat | Diff `-30 zile` / `+20 zile` |

---

## 2. Corpus

Nu indexăm internetul. Doar catalogul din [`sources.md`](./sources.md) (+ Anexa 1 oficială când e disponibilă).

```text
Țintă: ~100–500 documente/pagini
Demo: 10–20 PDF-uri foarte relevante + crawl P0/P1
```

Calitate și latență > volum.

---

## 3. Arhitectură (local)

```text
┌─────────────────────────────────────────────┐
│                 Next.js                      │
│  /  Chat (Cetățean | Angajat)                │
│  /sources  Evidence viewer                   │
│  /admin    Crawl · Changes · Cost · Users    │
│  /login    Auth                              │
│  localhost:3000                              │
└─────────────────────┬───────────────────────┘
                      │ JWT / session
                      ▼
┌─────────────────────────────────────────────┐
│                 FastAPI                      │
│  auth · chat · search · sources · feedback   │
│  admin · crawl control · cost                │
│  localhost:8000                              │
└───────┬───────────────┬──────────────┬──────┘
        ▼               ▼              ▼
 PostgreSQL+pgvector  Ollama        Crawler
 localhost:5432       Qwen3-8B      Worker
                      BGE-M3        (Playwright
                      Reranker       + parsers)
        └───────────────┴──────────────┘
                        ▼
              Hybrid RAG + Verify + Navigate
```

---

## 4. Stack

| Strat | Tehnologie |
|-------|------------|
| Frontend | Next.js, TypeScript, Tailwind, shadcn/ui, Lucide |
| Backend | Python, FastAPI |
| Auth | JWT (access + refresh) · roluri `citizen` / `employee` / `admin` |
| Database | PostgreSQL + pgvector (local) |
| LLM | Qwen3 8B Q4 via Ollama (RTX 3070) |
| Embeddings | **BAAI/bge-m3** (obligatoriu) |
| Reranking | **BAAI/bge-reranker-v2-m3** (obligatoriu) |
| Retrieval | Hybrid: dense (pgvector) + lexical (BM25 / `tsvector`) |
| Crawler | Python + Playwright + extractors PDF/DOCX/XLSX/OCR |
| Fallback LLM | GPT-5 mini API (dacă local eșuează) |

UI: dark, curat, contrast ridicat, accesibil (keyboard, labels, text lizibil).

---

## 5. Autentificare

Auth este parte din MVP (nu „complicată”, dar reală).

| Rol | Acces |
|-----|--------|
| `citizen` | Chat, sources, feedback (înregistrare ușoară / guest opțional pentru demo public) |
| `employee` | Chat în mod Angajat + istoric sesiuni |
| `admin` | Crawl, surse, users, cost, metrics |

### Flow

```text
POST /auth/register | /auth/login
  → access_token (JWT, short-lived)
  → refresh_token (httpOnly cookie sau DB)
Protected routes: Authorization: Bearer …
Admin endpoints: require role=admin
```

### Tabele auth

```text
users: id, email, password_hash, role, language_pref, created_at
sessions: id, user_id, refresh_hash, expires_at, revoked
```

Chat-ul poate permite **guest demo** (fără cont) pentru pitch, dar Admin + crawl + feedback agregat cer login.

---

## 6. Schema DB

### Core

| Tabel | Câmpuri cheie |
|-------|----------------|
| `sources` | id, name, url, type, language, active, priority, last_crawled_at |
| `documents` | id, source_id, title, url, language, content, content_hash, mime_type, published_at, updated_at |
| `chunks` | id, document_id, content, page, section, embedding, tsv |
| `document_changes` | id, document_id, old_hash, new_hash, diff, detected_at |
| `messages` | id, session_id, user_id, role, content, status, created_at |
| `message_sources` | message_id, chunk_id, relevance |
| `topic_links` | topic_ro, topic_ru, url, contact_label, contact_value |
| `feedback` | id, message_id, user_id, useful, reason, created_at |
| `users` / `sessions` | auth |

Fără 25 de tabele — doar ce e necesar pentru must-have + auth + navigare + feedback.

---

## 7. Crawler sofisticat

Crawler-ul nu e „5 pași minimal”. Este un **pipeline de ingestie municipală** care citește pagini, documente și atașamente.

### Capacități

| Capacitate | Detaliu |
|------------|---------|
| Discovery | Sitemap XML + BFS pe domeniu + linkuri din `sources.md` |
| Clasificare | `html` · `pdf` · `docx` · `xlsx` · `image` (scan) · `unknown` |
| HTML | Playwright (JS-rendered), extracție main content, limba paginii |
| PDF | text layer (pypdf/pdfplumber); dacă e scan → OCR (Tesseract ro+ru) |
| DOCX / XLSX | python-docx / openpyxl → text tabular normalizat |
| Atașamente | Urmărește `Fișiere anexate` de pe paginile Primăriei |
| Dedup | SHA-256 pe conținut normalizat |
| Versioning | hash schimbat → `document_changes` + re-chunk + re-embed |
| Politeness | rate limit, robots.txt respect, retry/backoff |
| Observability | job status în Admin: queued / running / ok / failed |
| Scope | Allowlist domenii: `chisinau.md`, `*.chisinau.md`, URL-uri din Anexa 1 |

### Pipeline

```text
sources.md / DB sources
        ↓
   URL frontier (priority P0→P2)
        ↓
   Fetch (Playwright / HTTP)
        ↓
   Detect type + language
        ↓
   Extract text (+ page/section where possible)
        ↓
   Normalize → SHA-256
        ↓
   unchanged? skip
   changed? save version + diff
        ↓
   Chunk 500–800 tokens, overlap ~100
        ↓
   Embed BGE-M3 → pgvector
   Update tsvector for lexical search
```

### Module (`backend/crawler/`)

```text
sitemap.py      # sitemap + URL seed
frontier.py     # queue, priorities, allowlist
fetcher.py      # Playwright + HTTP
classifier.py   # MIME / extension / content sniff
html_parser.py  # content + links + attachments
pdf.py          # text + OCR fallback
office.py       # docx / xlsx
diff.py         # hash + textual diff
pipeline.py     # orchestrator
jobs.py         # crawl jobs for Admin
```

---

## 8. Chunking & citări

```text
PDF 50 pagini → Page 1…N → chunks ~500–800 tokens, overlap ~100
```

```json
{
  "document_id": 15,
  "page": 4,
  "section": "3.2",
  "text": "...",
  "embedding": [...],
  "source_url": "https://..."
}
```

Citare UI: **Regulamentul X — pagina 4 — secțiunea 3.2** → click → Evidence panel cu highlight + Open document.

---

## 9. Pipeline RAG (cu reranker)

```text
USER QUESTION
      │
      ▼
Auth context + language detection (RO/RU)
      │
      ▼
Query embedding (BGE-M3)
      │
      ▼
Hybrid retrieval
  • dense: pgvector top 20
  • lexical: tsvector / BM25 top 20
  • merge + dedupe
      │
      ▼
Reranker BGE-reranker-v2-m3 → Top 5 evidence
      │
      ▼
Evidence verification (supported / missing / conflict)
      │
      ▼
Qwen3 → structured JSON
      │
      ▼
Topic routing → contact / official page
      │
      ▼
Answer + sources + status + next_action
```

Reranker-ul este **obligatoriu** — crește accuracy pe criteriul de 20%.

---

## 10. Output structurat

```json
{
  "status": "supported",
  "answer": "...",
  "sources": [
    {
      "document": "Regulamentul X",
      "page": 4,
      "section": "3.2",
      "quote": "...",
      "url": "https://..."
    }
  ],
  "next_action": {
    "label": "Contactați Ghișeul Unic",
    "url": "https://www.chisinau.md/ro",
    "contact": "+373 22 20 15 05"
  },
  "confidence": "high",
  "language": "ro"
}
```

Statusuri: `supported` | `missing` | `conflict`.

La `conflict`, `sources` conține ambele tabere; UI le afișează side-by-side.  
La `missing`, `answer` explică lipsa și `next_action` duce la pagina relevantă.

---

## 11. Prompt (concept)

```text
You are a municipal information assistant for Chișinău City Hall.
Answer ONLY using the provided evidence.

Rules:
1. Never invent information.
2. Every factual claim must be supported by a quoted passage.
3. If evidence lacks the answer → status "missing".
4. If sources contradict → status "conflict" (show both sides, do not pick a winner).
5. Cite exact document, page/section, and quote.
6. Answer in the user's language (ro/ru).
7. Do not use external knowledge.
8. Suggest next_action only from provided topic links.

USER QUESTION: {question}
EVIDENCE: {chunks}
TOPIC_LINKS: {links}
```

---

## 12. Tools

| Tool | Scop |
|------|------|
| `search_documents` | Hybrid search + rerank |
| `get_document` | Document by id |
| `get_document_changes` | Version history / diff |
| `find_contact` | Topic → official page / contact (`topic_links`) |

---

## 13. Interfață

### Pagini

| Rută | Rol |
|------|-----|
| `/login` | Auth (citizen / employee / admin) |
| `/` | Chat — mod **Cetățean** \| **Angajat** |
| `/sources` | Document + pasaj + highlight |
| `/admin` | Crawl, changes, conflicts, feedback, latency, users |
| `/admin/cost` | Estimare cost lunar (must-have) |

### Chat

- Switch RO | RU (+ detectare automată din întrebare)
- Surse clickable → Evidence drawer
- Badge status: verified / missing / conflict
- Badge „Actualizat {dată}” dacă documentul are change recent
- Card **Unde mergeți mai departe?** (navigare site)
- Feedback 👍/👎 + motiv

### Conflict UI

```text
┌─────────────┬─────────────┐
│ Document A  │ Document B  │
│ „30 zile”   │ „20 zile”   │
│ p.4 · §3.2  │ p.7 · §2    │
└─────────────┴─────────────┘
⚠️ Informații contradictorii în corpus
```

### Accessibility (criteriu 20%)

- Contrast WCAG AA, font lizibil, focus vizibil
- Navigare keyboard, aria-labels
- Mesaje sistem în limbaj simplu (RO+RU)
- Responsive mobile

---

## 14. USP / Inovație (30%)

**Living Municipal Knowledge Base**

```text
ce există → ce s-a schimbat → ce e actual → ce se contrazice → unde merge cetățeanul
```

Nu e chatbot generic, ci:

**Source + Passage + Version + Conflict + Navigation**

Plus mod dual **Cetățean / Angajat** pe același corpus.

---

## 15. Cost lunar (must-have)

În `/admin/cost`:

```text
Self-hosted
  Model: Qwen3-8B Q4 · Ollama
  Hardware: RTX 3070 · acest PC
  Deploy: local Chișinău
  Cost LLM: ~0 MDL (doar electricitate)

Cloud fallback
  Model: GPT-5 mini
  Estimare pe 10.000 întrebări/lună:
    input tokens × price + output tokens × price

Comparație side-by-side + total estimat lunar
```

---

## 16. Demo 3 minute

| Timp | Acțiune |
|------|---------|
| 0:00 | Problema: info există, cetățeanul nu știe unde |
| 0:20 | Login rapid → întrebare RO → citat clickable |
| 0:50 | Next-action: pagină contact Primărie |
| 1:10 | Aceeași întrebare RU |
| 1:35 | Missing → flag + link oficial |
| 2:00 | Conflict side-by-side |
| 2:25 | Admin: diff versiune + cost lunar + feedback % |

---

## 17. Ordinea de construcție (~48h)

| P | Timp | Deliverable |
|---|------|-------------|
| **P1** | 4–6h | Postgres + schema + seed docs + embeddings + hybrid search |
| **P2** | 2h | Reranker în pipeline |
| **P3** | 3–4h | Qwen3 + structured output + citations + verify |
| **P4** | 2h | Auth (JWT + roles) |
| **P5** | 3–4h | Frontend chat + evidence + RO/RU + next-action |
| **P6** | 4–5h | Crawler sofisticat (HTML+PDF+office+OCR+versioning) |
| **P7** | 2h | Conflict UI + change badges |
| **P8** | 1–2h | Admin + cost + feedback |
| **P9** | rest | Accessibility, eval set 15 Q, polish |

---

## 18. Ce NU facem

- Docker / Kubernetes / microservicii
- Redis, Kafka, Neo4j, Elasticsearch
- Fine-tuning / model propriu
- App mobilă nativă
- 20 tools / knowledge graph complet
- Crawl în afara allowlist-ului din `sources.md` / Anexa 1

---

## 19. Structura repo

```text
civic-ai/
├── apps/web/                 # Next.js
│   ├── app/
│   ├── components/
│   └── lib/
├── backend/
│   ├── api/
│   │   ├── auth.py
│   │   ├── chat.py
│   │   ├── documents.py
│   │   ├── sources.py
│   │   ├── feedback.py
│   │   ├── admin.py
│   │   └── cost.py
│   ├── ai/
│   │   ├── llm.py
│   │   ├── embeddings.py
│   │   ├── retrieval.py      # hybrid
│   │   ├── reranker.py       # obligatoriu
│   │   ├── verifier.py
│   │   └── prompts.py
│   ├── crawler/              # pipeline sofisticat
│   ├── db/
│   └── auth/
├── scripts/
├── eval/                     # 15 întrebări + expected status
├── sources.md                # catalog surse
├── README.md
└── .env
```

---

## 20. Rulare locală

| Serviciu | Port | Cum |
|----------|------|-----|
| PostgreSQL + pgvector | `5432` | Serviciu Windows local |
| Ollama (Qwen3 + embeddings host) | `11434` | `ollama serve` |
| FastAPI | `8000` | `uvicorn` |
| Next.js | `3000` | `npm run dev` |
| Crawler worker | — | `python -m backend.crawler.pipeline` |

```env
DATABASE_URL=postgresql://user:pass@localhost:5432/civic_ai
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
JWT_SECRET=change-me
OPENAI_API_KEY=                 # optional fallback
NEXT_PUBLIC_API_URL=http://localhost:8000
```

```text
1. PostgreSQL
2. ollama serve
3. uvicorn backend.main:app --reload --port 8000
4. cd apps/web && npm run dev
5. (opțional) python -m backend.crawler.pipeline --priority P0
```

---

## 21. Decizii blocate

```text
Frontend:     Next.js + TS + shadcn
Backend:      FastAPI
Auth:         JWT + roles (citizen / employee / admin)
Database:     PostgreSQL + pgvector (local)
Crawler:      Sophisticated Playwright pipeline (pages + docs + OCR)
Embeddings:   BGE-M3
Reranker:     BGE-reranker-v2-m3 (obligatoriu)
Retrieval:    Hybrid dense + lexical
LLM:          Qwen3-8B Q4 via Ollama
Fallback:     GPT-5 mini API
Architecture: RAG + Verify + Navigate
USP:          Source + Passage + Version + Conflict + Navigation
Deploy:       Local pe acest PC — fără Docker
Sources:      sources.md (+ Annex 1 when available)
```

**Pitch-winning path:** răspuns verificabil → sursă exactă → RO/RU → missing + contact → conflict side-by-side → change detected → cost lunar.
