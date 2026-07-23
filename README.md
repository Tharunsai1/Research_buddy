# Research Copilot

Map an entire ML research field from a single search, then actually understand
the papers in it — a fully local tool for researchers and students.

**Mapping a field:** enter a topic (e.g. *retrieval-augmented generation*) →
arXiv pulls candidate papers → a cross-encoder + LLM rerank them by semantic
relevance → structured extraction per paper (TL;DR, problem, method, key
results, why it matters) → cross-paper synthesis into a research landscape
(method clusters, paper relationships, tensions, consensus, open problems,
suggested reading order) → an interactive reading map that accumulates papers
across searches.

**Understanding one paper** — click any paper, then *Read full paper*. The tool
fetches the paper's full text from arXiv's HTML (no PDF parsing), reads it
section by section, and unlocks a five-tab workspace:

| Tab | What you get |
|---|---|
| **Summary** | Abstract-level cards plus a full-text synthesis, the paper's contributions, and its results in detail |
| **Explain** | The same paper at three levels — *Beginner* (no jargon, plain analogy), *Grad student*, *Expert* (only the delta vs prior work) — plus the full glossary |
| **Sections** | A digest of every section with concrete key points (numbers, datasets, equations preserved) |
| **Critique** | What the paper does *not* solve, its load-bearing assumptions, methodological weaknesses, and the questions a reviewer would ask |
| **Chat** | Ask anything; answers are retrieved from the indexed full text and cite the sections they came from. The starter prompts are drawn from *this* paper's own reviewer questions and glossary — not a generic list |

Technical terms are underlined throughout — hover or click for a plain-English
definition and how *this* paper uses the concept.

**Real citation data** (Semantic Scholar, free, no key, no LLM cost). Hit
*Load citation data* and the map stops being merely plausible:

- **Nodes are sized by citation count**, and the most-cited paper in each
  cluster gets a ring — the seminal work is visible at a glance.
- **Solid edges are real citations** pulled from reference lists; dotted edges
  are the LLM's inferred relationships. You can always tell which is which.
- **Read these first** ranks papers the current search's papers cite repeatedly
  but your library doesn't contain — the actual foundations of *that* field.
  (Ranking over the whole library instead surfaces other fields' foundations —
  T5 and GShard under a Stable Diffusion search — which then join it as
  unconnected nodes, so the list is scoped to the search you are viewing.)
  *+ Add* fetches the paper, summarizes it, and folds it into **both** the
  global map and the search you added it from: it appears in that search's
  paper list, relationship graph (wired up with real citation edges from the
  papers that cite it), toolkit selector, and at the top of the reading order
  as a foundation. Takes a minute or two — one LLM call.
- **Timeline view** plots every cluster on a shared time axis, so you can see
  which sub-areas emerged when.

The map has a **This search / All papers** toggle. *This search* — the default —
shows only the papers the current search returned, grouped by that search's own
method clusters. *All papers* is the accumulated library across every search.
Click a node to open the paper; drag one to pin it where you drop it. Scroll or
pinch to zoom (toward the cursor), drag empty background to pan, and use the
+/−/reset controls in the corner — at 90+ papers in *All papers*, 1:1 is too
dense to read without it.

**Research toolkit** — three tools for when you're writing, not just reading:

- **Literature matrix** — the classic survey table (task, method family,
  datasets, metrics, headline result, code link), auto-filled per paper and
  exportable to CSV. Rows built from a full-text deep read are flagged
  *from full text*; abstract-only rows are less reliable, so the provenance
  is always visible.
- **Related work** — drafts themed, comparative paragraphs with inline
  `\cite{key}` commands plus a matching `.bib` file, using standard
  `lewis2020retrievalaugmented`-style keys. Ends with a gap statement.
- **Compare two** — any two papers side by side on problem, method, results,
  strengths, limitations, and when to use each.

**Learning loop** — for actually retaining what you read:

- **Study deck** — flashcards per paper. Definition cards come free from the
  glossary; the model adds *concept*, *result*, and *critique* cards.
  *Relationship* cards test papers against each other — "how does X build on
  Y?" — reusing the map's own edge descriptions, so they cost nothing to
  generate and appear automatically. A **Quiz on** selector scopes the whole
  deck (and the quiz pool) to one cluster instead of the full search, so you
  can test whether you understand how a sub-theme's papers relate, not just
  each one in isolation — a relationship card only counts as in-scope when
  *both* papers it connects are in the selected cluster. Export to **Anki**
  (tab-separated, tagged per paper).
- **Quiz mode** — answer in your own words and the model grades against the
  paper (or, for a relationship card, against the edge description): verdict,
  0–100 score, what you missed, and the reference answer. Grades drive
  **spaced repetition** (SM-2 lite): correct → 1, 3, 8… days; wrong → back to
  tomorrow. *Quiz me* shows only what's due.
- **What's new in this field** — re-runs a saved search against arXiv, keeps
  only papers you don't have, and reports what changed, flagging anything that
  **challenges the consensus** you already mapped. New papers fold into the
  library so the map keeps growing.
- **Compare past searches** — pick any two of your own past searches (the same
  query re-run later, or two related ones) and see what actually changed:
  papers added or dropped, themes gained or lost, consensus and tensions that
  shifted, open problems that appeared or got resolved. Pure diff over data
  you already have — no LLM call, so it's instant.
- **Field report** — the *⤓ Field report* button next to the map bundles a
  search's overview, method clusters (with links), tensions, consensus, open
  problems, suggested reading order, and your flashcard progress into one
  Markdown file — something to keep, paste into notes, or hand to someone
  else. No LLM call; it's all data the search already produced.

## Stack

- **Backend** — FastAPI + [`arxiv`](https://pypi.org/project/arxiv/) + an LLM
  (default: **OpenRouter** running NVIDIA `nemotron-3-ultra-550b-a55b:free`;
  alternatively **Ollama** locally with grammar-constrained JSON output, or the
  Anthropic API) + `sentence-transformers` cross-encoder
  (`ms-marco-MiniLM-L-6-v2`) for reranking + `nomic-embed-text` for
  chat-with-paper retrieval. Full text comes from arXiv's LaTeXML HTML, parsed
  with BeautifulSoup. Everything persists as JSON under `backend/data/`.
- **Frontend** — Next.js (App Router) + Tailwind + `d3-force` for the
  force-directed reading map.

## Setup

### Switching models

The header has a **model picker** — flip between the hosted and local model at
any time without restarting. The choice applies to every subsequent search,
deep read, quiz and chat, and is saved to `backend/data/settings.json` so it
survives a restart. Work already written to disk is untouched.

| Model | Where | Trade-off |
|---|---|---|
| **Nemotron 3 Ultra** | hosted (OpenRouter, free tier) | Deeper analysis, cites real numbers · ~4 min/paper |
| **Qwen3 8B** | local (Ollama) | Offline and free, shallower · ~90s/paper |

Claude appears as a third option only when `ANTHROPIC_API_KEY` is set.

The picker tracks Nemotron's OpenRouter usage against the free tier's daily
cap and shows a quiet count (e.g. "312/1000 requests used today"); past 90% it
turns into an amber warning so a big search doesn't burn the rest of the day's
budget without warning.

### 0. LLM

**Default — OpenRouter (free model, hosted).** Get a key at
[openrouter.ai/keys](https://openrouter.ai/keys), then put it in `backend/.env`:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

The default model (`nvidia/nemotron-3-ultra-550b-a55b:free`) costs $0/token.
The free tier allows **20 requests/minute**, and **50 requests/day** until the
account has ever held **$10** in credit — a one-time top-up that permanently
raises the cap to **1,000/day** (credits don't expire and remain spendable).
The backend rate-limits itself to stay under the per-minute cap and retries
429s with backoff.

**Embeddings always run locally** — OpenRouter is a chat-completions gateway
and doesn't serve the embedding model. Only *chat-with-paper* needs it:

```powershell
# install Ollama (ollama.com), then:
ollama pull nomic-embed-text
```

**Alternatives** — set `RC_PROVIDER` in `backend/.env`:
- `ollama` — fully offline (`ollama pull qwen3:8b`), no key, no rate limits
- `anthropic` — set `ANTHROPIC_API_KEY` and `RC_MODEL`

### 1. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn main:app --port 8321
```

### 2. Frontend (second terminal)

```powershell
cd frontend
npm install
npm run dev                     # http://localhost:3000
```

### 3. Tests (optional)

```powershell
cd backend
.venv\Scripts\pip install pytest pytest-asyncio
.venv\Scripts\python -m pytest
```

The suite covers the deterministic, LLM-free logic — card scheduling and id
conventions, search diffing, the field report, map partitioning, the storage
layer, and the meta-commentary guard. Provider calls are stubbed, so it makes
no network requests, costs nothing, and runs in well under a second. Tests are
sandboxed to a tmp directory and never read or write `backend/data/`.

The frontend talks to the backend at `http://127.0.0.1:8321` by default —
override with `NEXT_PUBLIC_API_BASE` in `frontend/.env.local` if you move it.
If you run the frontend on a port other than 3000, nothing else changes (the
backend accepts any localhost origin).

Open the app, type any ML topic in plain English, and watch the four-stage
pipeline run: **Query arXiv → Rank by relevance → Generate summaries → Map
research landscape**. With the default local model a search is free; speed
depends on your GPU (the pipeline makes ~11 LLM calls per search). With
`RC_PROVIDER=anthropic` each search costs roughly $0.30–0.60.

## Configuration (backend/.env)

| Variable | Default | Meaning |
|---|---|---|
| `RC_PROVIDER` | `ollama` | `ollama` or `anthropic` |
| `RC_OLLAMA_MODEL` | `qwen3:8b` | Ollama model for all LLM stages |
| `RC_EMBED_MODEL` | `nomic-embed-text` | embeddings for chat-with-paper |
| `RC_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server |
| `RC_OLLAMA_CTX` | `16384` | context window per call |
| `ANTHROPIC_API_KEY` | — | required only when `RC_PROVIDER=anthropic` |
| `RC_MODEL` | `claude-opus-4-8` | Anthropic model |
| `RC_FULL_RECLUSTER_MAX` | `40` | above this library size, only new papers are clustered |
| `RC_PAPERS` | `8` | papers selected per search |
| `RC_CANDIDATES` | `60` | max arXiv candidates before reranking |
| `RC_CROSS_ENCODER` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | reranker model |
| `RC_DISABLE_CE` | unset | set `1` to skip the cross-encoder (LLM-only ranking) |
| `S2_API_KEY` | unset | optional Semantic Scholar key; raises the shared rate limit |
| `RC_OPENROUTER_DAILY_CAP` | `1000` | free-tier daily request budget the model picker warns against; set to `50` if the account has never funded $10 |

## Architecture

```
backend/
  main.py          FastAPI routes (search, state, deep dive, chat)
  pipeline.py      four-stage orchestration per search
  arxiv_client.py  stage 1 — retrieval (arXiv API)
  rerank.py        stage 2 — cross-encoder scores + LLM shortlist
  extract.py       stage 3 — structured per-paper summaries
  synthesize.py    stage 4 — landscape + global reading-map synthesis
  fulltext.py      arXiv HTML fetch → sections → retrieval chunks
  deepdive.py      per-paper map-reduce: section digests → synthesis,
                   explanations, glossary, critique
  chat.py          embed + retrieve + answer with citations
  semantic_scholar.py  cached, rate-limited Graph API client
  citations.py     real citation edges, metrics, prerequisite ranking
  research.py      survey-matrix rows, related-work + BibTeX, comparisons
  learning.py      flashcards, SM-2 scheduling, answer grading, field digests
  store.py         JSON persistence + in-memory job registry
  models.py        pydantic schemas (also used as LLM structured outputs)
  meta_guard.py    rejects model meta-commentary ("The user wants me to…")
                   before it reaches the reader; drives a retry in llm.py
  tests/           pytest suite over the LLM-free logic (see Setup step 3)
frontend/
  app/page.tsx                    single-page UI (search → pipeline → results)
  components/ReadingMap.tsx       force-directed map (click to open, drag to pin)
  components/PaperWorkspace.tsx   five-tab paper reader + deep-read progress
  components/RichText.tsx         glossary tooltips, bold/math formatting
  components/Timeline.tsx         clusters on a shared time axis
  components/Prerequisites.tsx    "read these first" + add-to-map
  components/ResearchToolkit.tsx  matrix / related work / compare
  components/StudyDeck.tsx        flashcards + graded quiz mode
  components/FieldDigest.tsx      "what's new" follow mode
  components/…                    pipeline card, clusters, relationships graph,
                                  tensions, consensus, open problems, reading order
```

A deep read makes ~11 LLM calls and takes roughly 90 seconds per paper on
`qwen3:8b`; results are cached to disk, so reopening a paper is instant. Papers
that are PDF-only on arXiv (mostly pre-2023) have no HTML full text — the tool
says so and keeps the abstract-level summary.

Every search merges its papers into a persistent collection so the reading map
grows coherently over time. Up to `RC_FULL_RECLUSTER_MAX` papers (default 40)
the whole collection is re-clustered each search; past that only the new papers
are placed into the existing clusters. That keeps stage 4 flat as the library
grows — a full re-cluster of ~90 papers is a single ~10k-token call that runs
for minutes and brushes the request timeout — and it stops each search from
reshuffling clusters you have already learned your way around. Papers the model
declines to place land in an **Unsorted** cluster and are retried next search.
Papers you mark as read stay marked across sessions.
