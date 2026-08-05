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

**Critical appraisal** — working through the search's papers one at a time
against a reviewer's checklist, rather than only summarising them:

- **The checklist** is Chris Lovejoy's questions for papers applying machine
  learning to healthcare — Overview, Data, Methodology, Performance,
  Conclusions. The sections generalise past healthcare, since every empirical
  paper has data, a method, a claimed result and a conclusion someone has to
  judge, so the *intent* of each question is kept and the wording adapts to the
  paper in front of it. One LLM call per section, then a verdict over the
  answers — the Conclusions questions genuinely depend on having worked through
  the rest, so they run last, over the answers rather than over the paper.
- **A queue, not a list.** Finishing a paper advances to the next one with no
  appraisal yet, in the search's own order. Progress is which appraisal files
  exist on disk rather than component state, so closing the tab loses nothing.
- **The questions match the kind of paper.** The checklist assumes an empirical
  study, so it branches on the `paper_type` the extraction already carries: a
  survey is asked what literature it covers, how papers were selected and whose
  work is missing; a theory paper what it assumes and what is proven rather
  than asserted; a dataset paper how it was annotated and licensed. Asked the
  stock questions a survey answers "not reported" down the page — which reads
  as a broken feature when the truth is that the wrong questions were asked.
- **Three ways of not answering, and only two are criticisms.** *not reported*
  means the paper should have said and didn't. *partial* means it half did.
  *not applicable* means the checklist asked something this kind of paper never
  had to answer — shown in grey, and explicitly not counted against the paper
  when the verdict is written.
- **It says which text it read.** An appraisal built from the abstract alone
  answers the Overview questions and almost nothing under Data or Performance,
  so it is labelled as such rather than passing for a full read. Deep-read the
  paper first and it uses the full text.

**Keeping up** — for when the field moves after you have mapped it:

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
  problems, suggested reading order, and how many papers you have appraised
  into one Markdown file — something to keep, paste into notes, or hand to someone
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
deep read, appraisal and chat, and is saved to `backend/data/settings.json` so it
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

### Or in one click

Once both are installed, `start.ps1` does the whole thing: it starts Ollama,
the backend and the frontend — each only if its port is down, so running it
twice will not spawn duplicates — waits for them, and opens the browser.

```powershell
.\start.ps1
```

For a desktop shortcut, point one at
`powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File <repo>\start.ps1`
and set its icon to `research-copilot.ico`. Two consoles stay open while the
app runs; closing them stops it.

The script finds Node itself and puts it on the PATH it hands the frontend,
rather than trusting the PATH it inherited. A shortcut launched from a process
that predates the Node install passes that stale environment down, and
`npm run dev` then dies in a console nothing is watching — the backend comes
up, the frontend never does. For the same reason it checks the venv,
`node_modules` and Node up front and opens a dialog naming the missing step:
launched from a shortcut there is no console for an error to appear in.

### 3. Tests (optional)

```powershell
cd backend
.venv\Scripts\pip install pytest pytest-asyncio
.venv\Scripts\python -m pytest
```

The suite covers the deterministic, LLM-free logic — id conventions and the
appraisal store, search diffing, the field report, map partitioning, the storage
layer, and the meta-commentary guard. Provider calls are stubbed, so it makes
no network requests, costs nothing, and runs in well under a second. Tests are
sandboxed to a tmp directory and never read or write `backend/data/`.

The frontend talks to the backend at `http://127.0.0.1:8321` by default —
override with `NEXT_PUBLIC_API_BASE` in `frontend/.env.local` if you move it.
If you run the frontend on a port other than 3000, nothing else changes (the
backend accepts any localhost origin).

### Using it from an iPad (or any other device on the network)

Next serves the API from its own origin and forwards `/api/*` to the backend
(see `next.config.ts`), so there is no API address to configure and no CORS to
widen — a relative `/api/…` resolves against whatever host served the page.
Two consequences worth knowing:

* **Only port 3000 is exposed.** The backend stays bound to `127.0.0.1`, so
  nothing on the network can reach it directly; every request arrives through
  Next, on the machine running it.
* **Open `http://<this-machine's-LAN-IP>:3000`** on the tablet. Find the IP
  with `(Get-NetIPAddress -AddressFamily IPv4 | Where-Object InterfaceAlias -eq 'Wi-Fi').IPAddress`.
  If it is handed out by DHCP it can change; reserve it in the router to make
  the address stable.
* **The origin has to be declared to `next dev`.** It serves the HTML and the
  static chunks to anyone who asks but withholds the dev-only requests
  hydration needs, so an undeclared origin gets a page that renders correctly
  and then ignores every tap — no error, nothing in the UI to say why, and
  invisible from the machine running it, since over `localhost` it is fine.
  `allowedDevOrigins` in `next.config.ts` covers the private ranges and the
  Tailscale namespace; add anything else you reach it from. Dev only —
  `next build`/`next start` ignore the setting.

Windows blocks the inbound connection until you allow it. From an **elevated**
PowerShell, once:

```powershell
New-NetFirewallRule -DisplayName "Research Copilot (LAN)" -Direction Inbound `
  -Protocol TCP -LocalPort 3000 -Action Allow -Profile Private
```

`-Profile Private` is deliberate: the rule applies on networks marked private
(home) and not on public ones (cafés, campus, hotels).

**There is no authentication.** Anyone who can reach port 3000 can read and
change the whole library and spend the day's model budget. That is fine on a
home network and not fine on a shared one — keep the firewall rule scoped to
private networks, and stop the frontend when on public Wi-Fi.

The app is also a home-screen app on iPadOS: Share → Add to Home Screen opens
it without Safari's toolbars.

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
| `RC_DIGEST_CHECK_INTERVAL` | `3600` (1 hour) | how often the follow scheduler checks whether a followed search is due for an auto-digest — not the digest interval itself (fixed at ~7 days, `scheduler.DIGEST_INTERVAL_DAYS`) |

## Six more ways in

- **Search your own library** — a semantic search box appears under *All
  papers*: "which of my papers discussed KV-cache compression?" without
  remembering which search turned it up. One embedding per paper, cached; a
  search costs one query embedding, no LLM call.
- **Your own notes** — a free-text box at the top of every paper's Summary
  tab, autosaved 800ms after you stop typing. The one part of the app that
  isn't AI-generated; included verbatim in the field report export.
- **Highlight a passage, then ask** — select any text inside a paper's
  Summary/Explain/Sections/Critique tab and a *💬 Ask about this* button
  appears. It switches to Chat with that exact passage injected as excerpt
  `[0]` — the model's primary anchor — rather than hoping retrieval finds it.
- **Upload a PDF** — *⤒ Upload PDF* in the header adds a paper that isn't on
  arXiv (a camera-ready, something emailed, a workshop paper). Text extraction
  is heuristic (heading detection, falling back to fixed-size chunks), and
  author/venue lists are left blank rather than guessed wrong — everything
  else (extraction, clustering, deep dive, appraisal) runs unchanged.
- **Follow a field** — a toggle on the field digest auto-refreshes it roughly
  weekly, respecting the OpenRouter daily cap. This runs in-process, only
  while the backend is up — there's no external cron, so a check due while
  the backend was off simply runs the next time it starts.

## Evidence tools

Four analyses aimed at *what a paper establishes*, not just what it says.

- **Results scoreboard** — every number the selected papers report, in one
  sortable table, including the baselines they compare against (so two papers
  disagreeing about the same baseline becomes visible). Numbers are copied as
  printed, never recomputed. Hyperparameters and training configuration are
  filtered out in code, not just discouraged in the prompt — models reliably
  return "Adam beta1 = 0.9" as a result row otherwise.
- **Code & reproducibility** — which papers link a repo, and which report
  seeds, hyperparameters, hardware and error bars. Pure regex over text already
  on disk: no LLM call, no network, instant across the whole library. Shows
  what a paper *mentions*, not a guarantee the link resolves, and distinguishes
  a full-text scan from an abstract-only one (absence of a signal means very
  little in the latter).
- **Research gaps** — unexplored intersections across the library, each with a
  concrete first experiment. Papers are referenced by list position rather than
  arXiv id, and out-of-range references are dropped rather than trusted.
- **Peer review** — a conference-style review with soundness / contribution /
  presentation scores and a recommendation. Unlike the Critique tab it commits
  to a verdict. Works from the abstract alone, with a correspondingly lower
  confidence score, so it is never gated behind a full read.

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
  chat.py          embed + retrieve + answer with citations (+ a highlighted
                   passage anchor, injected as excerpt [0])
  semantic_scholar.py  cached, rate-limited Graph API client
  citations.py     real citation edges, metrics, prerequisite ranking
  research.py      survey-matrix rows, related-work + BibTeX, comparisons
  appraisal.py     the reviewer checklist — per-section questions that branch
                   on paper type, then a verdict over the answers
  learning.py      field digests ("what's new in this field")
  library_search.py  semantic search over the whole library (embed once, cache)
  pdf_ingest.py    uploaded-PDF text extraction into the same Paper/FullText
                   shapes fulltext.py produces from arXiv HTML
  scheduler.py     which followed searches are due for an auto-digest
  prefetch.py      which papers to warm ahead of the reader, and when not to
  artifacts.py     code links + reproducibility signals (regex, no LLM)
  insights.py      results ledger, research gaps, peer review
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
  components/PaperAppraisal.tsx   checklist queue, one paper at a time
  components/FieldDigest.tsx      "what's new" + follow toggle for auto-digests
  components/LibrarySearch.tsx    semantic search over the whole library
  components/UploadPdf.tsx        add a paper that isn't on arXiv
  components/…                    pipeline card, clusters, relationships graph,
                                  tensions, consensus, open problems, reading order
  lib/penSelection.ts             Apple Pencil drag-to-select
  lib/anchoring.ts                re-finding a marked passage after re-render
  lib/highlightPaint.ts           painting highlights without touching the DOM
```

### Highlighting

Select a passage — mouse, finger, or Pencil — and the toolbar offers
**Highlight** alongside **Ask about this**. Marks are saved per paper and
per tab, and reappear on the text when you come back.

Two details make it work rather than merely appear to:

* **Anchors are text, not positions.** A highlight stores its quote plus about
  forty characters either side, and is re-found by searching for that. Storing
  "paragraph 3, characters 40–90" breaks the moment anything above it changes,
  and breaks *silently* — the mark still lands somewhere, just on the wrong
  words. The surrounding context only breaks ties when a phrase repeats. If
  the text genuinely changed, the highlight is listed as "text has changed"
  instead of pointing somewhere the reader never marked.
* **Panels that quote highlights are excluded from the search** via
  `data-no-anchor` (see `NO_ANCHOR_ATTR`). The list of saved highlights sits
  inside the region being searched, so without this every anchor matches its
  own entry in the sidebar rather than the passage in the paper.

Painting uses the CSS Custom Highlight API, which colours ranges without
touching the DOM — the reading pane is React-rendered, and wrapping matches in
`<mark>` means mutating a tree React will overwrite. Where the API is missing
(iPadOS before 17.2) highlights stop being *shaded*; they are still saved,
listed and openable.

A deep read makes one LLM call per section plus four reduce stages — ~11 on a
typical paper — and takes roughly 90 seconds on `qwen3:8b`; results are cached
to disk, so reopening a paper is instant.

A section longer than `deepdive.SECTION_WORD_LIMIT` (3,500 words) is read in
consecutive passes and merged, not truncated at the limit, so a long paper
costs a few calls more and is covered end to end. The distinction matters more
than it sounds: a truncated section still produces a confident digest, of the
part that fit — one paper here described three separate case studies and the
digest covered the first, with nothing to mark the other two as missing. Each
section records the words that actually reached the model, and the workspace
shows "read N of M words" whenever that is short of the section's length
rather than claiming the full text. Where the whole paper is covered it says
so, and means it. Papers with more sections than `MAX_SECTIONS` still lose
some, but *Limitations*, *Conclusion*, *Discussion* and *Broader Impact* are
kept ahead of length — they are short by nature and were the first to go when
length alone decided.

Most of that wait is avoidable, so the backend warms reads ahead of you
(`prefetch.py` decides what, `main.py` runs it). When results land it starts
reading the top paper; when you open a paper it starts on the two after it, in
the order the Papers list shows. Open one mid-warm-up and the workspace picks
up the run already in progress rather than starting over. The Papers list
marks whichever paper is being read ahead and which are waiting behind it, so
the work is visible without opening anything; the list polls `GET /api/prefetch`
for that, since nothing else would tell it when a background read starts or
finishes.

Three rules keep that from backfiring. It warms **one paper at a time and never
alongside a read already running** — a deep read is already several concurrent
calls, so a second one would slow down the paper you are actually looking at.
The look-ahead is **bounded at two** (`prefetch.LOOK_AHEAD`), because warming a
30-paper search end to end would spend most of a day's cap on papers you never
open. And it **stops near the daily cap or on an engine that isn't ready**: a
speculative read must never be the call that spends the budget your own
explicit reads need. A paper that fails — usually one arXiv has no HTML for —
is remembered and not retried, since a queue that keeps handing back the same
unreadable paper never drains. Warming decisions are logged under
`research-copilot.prefetch`; it is the only trace this leaves, since none of it
is a request you can watch.

Papers
that are PDF-only on arXiv (mostly pre-2023) have no HTML full text — the tool
says so and keeps the abstract-level summary. It refuses rather than reading
whatever arXiv served: for those papers `arxiv.org/html/{id}` answers 200 and
redirects to the `/abs/` landing page, which is large enough to pass any
size check, so the deep dive keys off LaTeXML markup and the redirect target
instead. Reading that page instead of the paper produces a confident-looking
deep dive built from an abstract, which is worse than no deep dive at all.

Every search merges its papers into a persistent collection so the reading map
grows coherently over time. Up to `RC_FULL_RECLUSTER_MAX` papers (default 40)
the whole collection is re-clustered each search; past that only the new papers
are placed into the existing clusters. That keeps stage 4 flat as the library
grows — a full re-cluster of ~90 papers is a single ~10k-token call that runs
for minutes and brushes the request timeout — and it stops each search from
reshuffling clusters you have already learned your way around. Papers the model
declines to place land in an **Unsorted** cluster and are retried next search.
Papers you mark as read stay marked across sessions.
