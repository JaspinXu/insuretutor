# InsureTutor

**A bilingual (English / 简体中文 / 繁體中文) AI tutor that explains insurance plan documents — every answer grounded in the brochure, with page-level citations you can click to see the highlighted source.**

Built for the AIDF (NUS) *AI Full Stack Engineering Intern* take-home task, using the provided *FLEXI-ULife Prime Saver* brochure (YF Life, 20 pages, Traditional Chinese + English).

| Capability | How it's delivered |
|---|---|
| **Chat and answer** | Streaming chat UI with conversation history, follow-up questions (rewritten into standalone questions), feedback buttons |
| **RAG** | Layout-aware PDF ingestion → heading-aware bilingual chunks → hybrid retrieval (BM25 + multilingual embeddings, RRF) → answers citing `[n]` → click a citation to see the **PDF page with the passage highlighted** |
| **Guardrails** | 5 layers: deterministic input guard (PII redaction, injection / fraud / self-harm), LLM intent router, retrieval relevance gate, grounded-answer prompt, deterministic output checks (citation validation, **numeric grounding**, prompt-leak canary, script enforcement) |

![Answer with citations and the highlighted source page](docs/screenshots/answer-and-source.png)
<sub>Screenshots are from the Docker build in **offline mode** (no API key), where answers are the best-matching cited passages; with a key the same UI shows an LLM-written answer with the same citation chips. Right: clicking citation [1] opens PDF page 11 with the cited passage highlighted.</sub>

| Guardrails (繁體 UI): injection blocked, fraud refused with a grounded citation, phone number redacted | Simplified-Chinese welcome screen |
|---|---|
| ![Guardrails](docs/screenshots/guardrails.png) | ![Welcome](docs/screenshots/welcome-zh-hans.png) |

---

## Contents

1. [Quick start](#1-quick-start)
2. [Architecture](#2-architecture)
3. [Key design decisions](#3-key-design-decisions)
4. [Guardrails](#4-guardrails)
5. [Evaluation](#5-evaluation)
6. [Development](#6-development)
7. [Configuration reference](#7-configuration-reference)
8. [Limitations and next steps](#8-limitations-and-next-steps)

---

## 1. Quick start

Requirements: Docker with Compose v2.24+.

```bash
git clone <this repo> && cd insuretutor
cp .env.example .env          # then put ONE API key in .env (see below)
docker compose up --build     # first build ~3–5 min (downloads the embedding model)
```

Open **http://localhost:8000**.

**Choosing a model** — set one of these in `.env` (never commit it; `.env` is git-ignored):

| Provider | `.env` |
|---|---|
| Anthropic (Claude) | `ANTHROPIC_API_KEY=sk-ant-...` (default model `claude-opus-5-5`, override with `LLM_MODEL`) |
| OpenAI | `OPENAI_API_KEY=sk-...` (default `gpt-4.1-mini`) |
| Any OpenAI-compatible API (DeepSeek, Qwen/DashScope, Ollama, …) | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` — examples in `.env.example` |
| **No key** | Works out of the box in **offline mode**: same retrieval, citations and guardrails, but answers are the most relevant passages instead of generated text |

> **Mainland China:** Hugging Face may be unreachable during the build. The build still succeeds and the app falls back to keyword retrieval; to get embeddings, build with a mirror: `HF_ENDPOINT=https://hf-mirror.com docker compose build`.

Useful commands:

```bash
docker compose exec insuretutor python -m eval.run retrieval   # retrieval metrics
docker compose exec insuretutor python -m eval.run guardrails  # guardrail regression suite
docker compose exec insuretutor python -m eval.run answers     # answer quality (needs an API key)
curl localhost:8000/api/health                                 # provider / model / index status
```

---

## 2. Architecture

One container: FastAPI serves the API and the built React app from the same origin (no CORS, one port, one command).

```mermaid
flowchart LR
    UI["React UI<br/>(EN / 简 / 繁)"] -- "POST /api/chat<br/>Server-Sent Events" --> API[FastAPI]

    subgraph turn["One chat turn (app/chat.py)"]
      direction TB
      IG["1 · Input guard<br/>sanitise · redact PII<br/>block injection / fraud / self-harm"]
      RT["2 · Router<br/>one structured LLM call:<br/>intent · standalone question ·<br/>EN + 繁 search queries"]
      RV["3 · Hybrid retrieval<br/>BM25 + embeddings, RRF<br/>glossary expansion · relevance gate"]
      GEN["4 · Grounded generation<br/>streamed, cites [n]"]
      OG["5 · Output guard<br/>citations · numeric grounding ·<br/>leak canary · 简/繁 script"]
      IG --> RT --> RV --> GEN --> OG
    end

    API --> IG
    OG -- "final: answer + sources + flags + metrics" --> UI
    RV --- IDX[("Index cache<br/>chunks + vectors")]
    API --- DB[("SQLite<br/>conversations · feedback")]
    PDF[/"PDF + catalog.yaml<br/>+ verified overrides"/] --> ING["Ingestion<br/>PyMuPDF · chunker"] --> IDX
```

Every stage can end the turn early with a reviewed, localized template (e.g. an injection attempt never reaches the LLM). The UI renders streamed tokens live, then replaces them with the **validated** final answer from the `final` event.

### Repository layout

```
backend/
  app/
    ingest/        pdf.py (layout-aware extraction) · overrides.py · chunker.py · pipeline.py
    rag/           text.py (bilingual tokenizer) · bm25.py · embeddings.py · retriever.py · glossary.py
    guardrails/    input.py · router.py · output.py · messages.py (EN/简/繁 templates)
    llm/           anthropic_provider.py · openai_provider.py · base.py
    chat.py        the per-turn pipeline          prompts.py   router + answer prompts
    store.py       SQLite persistence            api/routes.py  HTTP + SSE endpoints
    lang.py        language / script detection   main.py      app factory
  eval/            run.py + datasets/ (retrieval, guardrails, answers)
  tests/           106 tests: ingestion, retrieval, guardrails, providers, end-to-end API
frontend/          React + TypeScript + Vite (chat, citations, source viewer, i18n)
data/
  docs/            FLEXI-ULife_Prime_Saver.pdf + catalog.yaml (metadata, font errata)
  overrides/       human-verified transcriptions of 5 table/infographic pages
  glossary.yaml    lay-language -> brochure-terminology expansions
Dockerfile · docker-compose.yml · .env.example
```

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/chat` | `{message, conversation_id?, ui_lang}` → SSE stream: `meta`, `status`, `sources`, `delta`…, `final` |
| `GET /api/conversations` · `GET/DELETE /api/conversations/{id}` | History, scoped to an anonymous per-browser `X-Client-Id` |
| `POST /api/messages/{id}/feedback` | 👍 / 👎 stored with the answer for later analysis |
| `GET /api/documents/{doc}/pages/{n}.png?chunk=…` | Page render with the cited passage highlighted |
| `GET /api/documents/{doc}/file` · `GET /api/config` · `GET /api/health` | Original PDF · UI config · status |

---

## 3. Key design decisions

### 3.1 Document processing: get the source text right first

A brochure is a designed document, not prose. I inspected every page rendered next to its extracted text and found three problems that would silently produce wrong answers:

| Problem | Example | Fix |
|---|---|---|
| **Font mapping errata** | The CJK font maps 總 ("total") to 籍 / U+FFFD, so Note 4 read "曾提取的籍金額" | Per-document `text_fixes` in `catalog.yaml` (verified: every 籍 in this file is a 總) |
| **Footnote superscripts lost** | "Guaranteed Insurability Option³" became "...Option3" | Superscript digits → explicit `[Note 3]` markers so the model links them to the Notes page |
| **2-D layouts flattened** | "Cash Value = Account Value − surrender charge" came out as "Applicable surrender charge = − 現金價值"; the minimum-sum-insured table lost which amount belongs to which plan/age | Human-verified Markdown transcriptions for **5 of 20 pages** (`data/overrides/`), each with a front-matter `reason`. All other pages are fully automatic |

The extractor (PyMuPDF) keeps content-stream order (which keeps each Chinese paragraph next to its English translation), joins wrapped lines CJK-aware, splits bold lead-in lines into headings, and drops decoration (page numbers, section badges). Citations always point to the original PDF page, including for overridden pages.

**Chunking:** heading-aware, page-bounded (so a citation = one page), ~420 tokens. Because the brochure is parallel bilingual, most chunks contain both the Chinese and the English wording: a question in any language/script matches, and the model can quote the official wording in the user's language. The whole corpus is 47 chunks (~13.5k tokens).

### 3.2 Retrieval: hybrid, bilingual, measured

- **BM25 with a bilingual tokenizer:** Chinese is normalised to Simplified (t2s is many-to-one, so a Simplified query matches the Traditional brochure) and split into character bigrams; English is stemmed; numbers are normalised (`50,000` → `50000`).
- **Dense embeddings** (multilingual, ONNX via fastembed — no PyTorch, baked into the image so the container needs no network). Chunks are embedded as short windows and scored by their best window, because small encoders truncate long inputs.
- **Reciprocal Rank Fusion** of all ranked lists (the user's question + the router's English and Traditional-Chinese rewrites × BM25 and dense). RRF fuses ranks, so BM25 and cosine scores never need calibrating against each other. Dense lists vote at weight 0.5: exact product vocabulary leads, embeddings break ties and rescue paraphrases (chosen from the eval, §5).
- **Glossary expansion** (`data/glossary.yaml`) bridges lay language and brochure terms ("lose my job" → *Unemployment Protection 失業保障*, "change my mind" → *cooling-off period 冷靜期*), added at half weight. The eval showed that expanding words the brochure *already uses* hurt ranking, so aliases are restricted to genuine lay terms.
- **Why no vector database:** tens of chunks per brochure; exact in-memory search takes milliseconds and has no moving parts. The index is cached on disk, keyed by a fingerprint of PDFs + overrides + model, and rebuilt automatically when a document changes. Swapping in pgvector/Qdrant for thousands of documents is a change inside `Retriever` only.
- **Why RAG at all for a 13.5k-token corpus** (it would fit in a context window): the task asks for a *collection* of documents, focused context gives more precise, citable answers, and per-question cost/latency stays flat as documents are added.

### 3.3 Bilingual by design, including Simplified vs Traditional

- The answer language follows the **question** (not the UI setting): Chinese vs English by weighted character/word counts; Simplified vs Traditional by counting characters that change under OpenCC t2s/s2t conversion. Script-neutral text falls back to the UI language.
- The model is asked to answer in the detected script, **and** the output is converted with OpenCC — because the sources are Traditional, models drift into Traditional characters when quoting them for a Simplified-Chinese user. Guaranteed, not just requested.
- Refusal / safety templates are hand-written in all three variants; the UI is fully localized.

### 3.4 LLM usage: two calls per turn, provider-neutral

1. **Router** (structured JSON): intent classification (in scope / concept / personal-advice request / greeting / out of scope / prompt attack / fraud / self-harm), standalone-question rewrite for follow-ups, and 2–4 search queries in English **and** Traditional Chinese using brochure terminology. With Claude this uses structured outputs (schema-valid by construction) at low effort.
2. **Answer** (streamed): strict grounding prompt — cite every claim, say "not in the documents" instead of guessing, copy numbers exactly, distinguish guaranteed vs "current assumed" rates, surface English/Chinese discrepancies, never give personal financial advice.

Providers: **Anthropic** (official SDK; effort control, refusal handling, server-side refusal fallback), **OpenAI or any OpenAI-compatible API** (degrades gracefully when a server rejects optional parameters), and **offline** (no key: extractive answers). If the LLM fails mid-turn, the user still gets cited passages. Both adapters are tested against a local fake server that speaks each wire format.

### 3.5 Data protection

PII (e-mail, phone, HKID, Singapore NRIC/FIN, mainland ID, Luhn-checked card numbers) is redacted **before** the text is logged, stored or sent to the LLM, and the user is told what was removed. Conversations are scoped to an anonymous per-browser id. No secrets in the repo; `.env.example` holds placeholders only.

---

## 4. Guardrails

Defense in depth — cheap deterministic checks first, the LLM only where judgment is needed, and deterministic verification of what the LLM produced.

| Layer | What it catches | How |
|---|---|---|
| **Input guard** (`guardrails/input.py`) | Prompt injection & jailbreaks, fraud intent ("hide my diagnosis", 瞞報吸煙史, 假死), self-harm intent, PII, oversized input | Bilingual patterns matched on an NFKC-folded, lower-cased, Simplified-normalised *probe* (so full-width text, zero-width characters and Traditional spellings can't dodge them). Blocks before any LLM call |
| **Router** (`guardrails/router.py`) | Subtler attacks (role-play, "translate your hidden prompt"), out-of-scope topics, personal-advice requests, distress | Structured LLM classification. Offline: greeting/advice patterns + an insurance-vocabulary scope check |
| **Retrieval gate** (`chat.py`) | Questions with no support in the documents | No lexical evidence → "not in the documents" instead of generation |
| **Grounded prompt** (`prompts.py`) | Hallucination, advice, indirect injection via sources | Cite-everything rules, sources fenced as data, "not found" behaviour, no recommendations |
| **Output guard** (`guardrails/output.py`) | Invalid citations, **figures not in the cited sources**, system-prompt leakage, wrong script | Citation renumbering/removal; every number ≥ 10 or with decimals must appear in the cited passages or the user's question (spelled-out numbers like "twelve"/"十二" count) — otherwise the UI warns *"these figures could not be matched to the cited pages"*; a random canary in the system prompt blocks leaked answers; OpenCC script conversion |

Special cases handled on purpose:

- **Suicide exclusion vs self-harm.** "What if the insured commits suicide in year one?" is a legitimate policy question and is answered (p. 14). "I want to end my life so my family gets the money" returns a supportive message with crisis lines for Hong Kong, Singapore and mainland China — no payout details.
- **Fraud requests get a grounded refusal** citing the brochure's duty-of-disclosure clause (p. 15).
- **Advice requests are not refused**: the tutor explains the relevant trade-offs from the brochure and recommends a licensed adviser.
- **Non-guaranteed rates**: the 4% crediting rate is "current assumed" (quoted as of January 2022); the prompt requires the answer to say so and to contrast it with the 2.5% guarantee after 15 years.
- **Source inconsistencies are surfaced, not hidden.** The brochure's "minimum increase/decrease of sum insured" reads *5,000美元 / 40,000港元 / 400,000澳門元* in Chinese but *US$5,000 / HK$400,000 / MOP40,000* in English. The transcription keeps both as printed and the prompt tells the model to point out such discrepancies.

---

## 5. Evaluation

`backend/eval/` contains three suites that run against the same configuration as the app.

### Retrieval — 45 questions (21 EN, 12 简, 12 繁) with expected pages, top-6

| Configuration | Hit@1 | Hit@3 | Hit@6 | MRR |
|---|---|---|---|---|
| BM25 | 71.1% | 86.7% | 91.1% | 0.791 |
| BM25 + glossary (first version: all aliases, full weight) | 71.1% | 80.0% | 93.3% | 0.782 |
| BM25 + glossary (lay-term aliases, half weight) | 77.8% | 91.1% | 97.8% | 0.851 |
| Hybrid (multilingual-e5-large, dense weight 1.0) + glossary | 75.6% | 95.6% | 97.8% | 0.856 |
| **Hybrid (multilingual-e5-large, dense weight 0.5) + glossary** | **80.0%** | **95.6%** | **97.8%** | **0.879** |

Per language (last row): EN 71.4 / 95.2 / 95.2%, 简 83.3 / 91.7 / 100%, 繁 91.7 / 100 / 100% (Hit@1 / @3 / @6).

What the numbers taught me:

- On this corpus, most of the gain comes from **bridging vocabulary** (glossary; and with an LLM, the router's bilingual query rewriting), not from embeddings — the brochure's product terms are distinctive, so BM25 is strong.
- Embeddings at equal RRF weight improved Hit@3 but *lowered* Traditional-Chinese Hit@1 (exact-term matches got outvoted); at half weight they help without that cost.
- The first glossary version hurt Hit@3 because it also expanded words the brochure already uses ("surrender", "interest rate"), pulling in the wrong sections.

Notes: these are measured without the LLM router (question text only), so they are a lower bound for the full system. The Docker image bakes the smaller `paraphrase-multilingual-MiniLM-L12-v2` (220 MB) to keep the build light; the hybrid rows were measured with `intfloat/multilingual-e5-large` (select it with `EMBEDDING_MODEL=intfloat/multilingual-e5-large docker compose build`). Run `python -m eval.run retrieval` to measure your configuration. The dataset is small and the weights were chosen on it, so treat it as a regression benchmark.

### Guardrails — 35 end-to-end cases

Injection (incl. full-width and zero-width obfuscation, role-play, Chinese), fraud, self-harm, out-of-scope, advice requests, PII, and **benign look-alikes that must not be blocked** (the suicide-exclusion question, "act as a savings plan", "ignore the fees for a moment…").

| Check (offline mode, deterministic layers only) | Result |
|---|---|
| Attacks blocked (injection / fraud / self-harm) | 15 / 15 |
| Out-of-scope declined | 5 / 5 |
| Benign questions answered (no false positives) | 15 / 15 |
| PII redacted | 3 / 3 |

These cases were written alongside the rules, so this is a regression suite rather than an unbiased estimate of robustness; the LLM router adds a second, semantic layer on top when a key is configured.

### Answers — 15 questions (needs an API key)

`python -m eval.run answers` checks **fact recall** (required facts such as "25%", "twice", "US$50,000" must appear), **citation accuracy** (a cited page must be one of the expected pages), how often figures were flagged as unverified, latency and token usage. It includes a *not-in-the-documents* question (exact cost-of-insurance rates), a *personal-advice* question, and the *English/Chinese discrepancy* question.

### Tests

```bash
cd backend && pip install -r requirements-dev.txt && pytest     # 106 tests, ~10 s, no API key needed
```

Covering extraction and chunk coverage, tokenizer/BM25/glossary, per-language retrieval, PII and injection patterns (and their false positives), output checks, both LLM adapters against a fake wire-format server, and the full API with a scripted LLM (grounded answer, hallucinated figure flagged, invalid citation removed, prompt leak blocked, script conversion, offline mode, LLM failure fallback, history & client scoping, rate limiting, page rendering).

---

## 6. Development

```bash
# Backend (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000      # EMBEDDING_BACKEND=none for a quick start
python -m app.ingest.pipeline                  # print the chunks (review extraction)

# Frontend
cd frontend && npm install && npm run dev      # http://localhost:5173, proxies /api to :8000
```

**Adding a document:** put the PDF in `data/docs/`, add an entry to `catalog.yaml`, run `python -m app.ingest.pipeline` to review the chunks, and add a verified override for any page whose tables don't survive extraction. The index rebuilds automatically on the next start.

---

## 7. Configuration reference

All settings are environment variables (see `backend/app/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `anthropic`, `openai`, `offline`, or `auto` (first key found) |
| `LLM_MODEL` / `ROUTER_MODEL` | provider default | Answer model / optional separate routing model |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_EFFORT`, `ANTHROPIC_ROUTER_EFFORT`, `ANTHROPIC_REFUSAL_FALLBACK` | –, `medium`, `low`, `true` | Claude settings |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | – | OpenAI or compatible endpoint |
| `EMBEDDING_BACKEND` | `local` | `local` (baked ONNX model), `openai` (`/embeddings` API), `none` (BM25 only) |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Also a build arg; the local model must be baked at build time |
| `TOP_K`, `DENSE_RRF_WEIGHT` | `6`, `0.5` | Passages per answer; dense vote weight in RRF |
| `MAX_INPUT_CHARS`, `RATE_LIMIT_PER_MINUTE` | `2000`, `30` | Input and per-IP request limits |

---

## 8. Limitations and next steps

- **Answer quality needs a live-model run.** Retrieval, guardrails and both provider adapters are tested offline; the answer suite (`eval.run answers`) should be run with the chosen model before release, and extended with an LLM-as-judge faithfulness score.
- **Overrides are manual.** A vision-LLM transcription step (render page → Markdown, then human review of the diff) would scale the "verified page" approach to many documents.
- **Scale-out:** in-memory index and rate limiter are per process; for many documents/users move to pgvector or Qdrant, a shared rate limiter (Redis) and real authentication.
- **Retrieval:** add a cross-encoder reranker if the corpus grows; the relevance gate uses a BM25 threshold that would need re-tuning per corpus.
- **Long conversations** keep the last 6 turns; summarise older turns for very long sessions.
- **Observability:** per-turn timings, token usage, guardrail decisions and user feedback are already recorded; exporting them (OpenTelemetry, a dashboard) would support regression tracking in production.

---

*Educational demo — not financial advice and not affiliated with YF Life. The brochure is the material provided with the task.*
