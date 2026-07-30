import type {
  AppState,
  ArtifactsResponse,
  CardsResponse,
  EnginesResponse,
  ChatAnswer,
  CompareResult,
  DeepDive,
  DeepJob,
  Digest,
  Flashcard,
  GapReport,
  GradeResult,
  Health,
  Highlight,
  Job,
  LibrarySearchResult,
  MatrixRow,
  PeerReview,
  PrefetchState,
  ReadingNudge,
  Prerequisite,
  RelatedWork,
  ResultRow,
  SearchDetail,
  SearchDiff,
} from "./types";

/** Empty by default: next.config.ts rewrites `/api/*` to the backend, so a
 *  relative URL resolves against whichever host served the page. That is what
 *  lets the same build work on this machine and from an iPad on the network —
 *  a baked-in address would be wrong on one of them. Set
 *  NEXT_PUBLIC_API_BASE only to point at a backend somewhere else entirely. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

/** For error messages, where "" would read as a missing address. */
const API_LABEL = API_BASE || "/api on this server";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error(`Backend not reachable at ${API_LABEL}. Is uvicorn running?`);
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep default detail */
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  health: () => request<Health>("/api/health"),
  engines: () => request<EnginesResponse>("/api/engines"),
  selectEngine: (engine: string) =>
    request<Health>("/api/engines/select", {
      method: "POST",
      body: JSON.stringify({ engine }),
    }),
  state: () => request<AppState>("/api/state"),
  startSearch: (query: string) =>
    request<{ job_id: string }>("/api/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  searchDetail: (id: string) => request<SearchDetail>(`/api/searches/${id}`),
  setRead: (paper_id: string, read: boolean) =>
    request<{ read: string[] }>("/api/read", {
      method: "POST",
      body: JSON.stringify({ paper_id, read }),
    }),
  startDeepDive: (paper_id: string) =>
    request<{ job_id: string }>(`/api/papers/${paper_id}/deepdive`, {
      method: "POST",
    }),
  deepJob: (job_id: string) => request<DeepJob>(`/api/deepjobs/${job_id}`),
  runningDeepJob: (paper_id: string) =>
    request<DeepJob | { job_id: null }>(`/api/papers/${paper_id}/deepjob`),
  deepDive: (paper_id: string) => request<DeepDive>(`/api/papers/${paper_id}/deep`),
  /** Advisory: tells the backend where the reader is so it can warm the deep
   *  reads they are most likely to open next. Returns immediately. */
  prefetch: (reading_order: string[], after_paper_id: string | null = null) =>
    request<PrefetchState>("/api/prefetch", {
      method: "POST",
      body: JSON.stringify({ reading_order, after_paper_id }),
    }),
  prefetchState: () => request<PrefetchState>("/api/prefetch"),

  highlights: (paper_id: string) =>
    request<{ highlights: Highlight[] }>(`/api/papers/${paper_id}/highlights`),
  allHighlights: () => request<{ highlights: Highlight[] }>("/api/highlights"),
  addHighlight: (
    paper_id: string,
    body: { tab: string; quote: string; prefix: string; suffix: string; note?: string },
  ) =>
    request<Highlight>(`/api/papers/${paper_id}/highlights`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  removeHighlight: (paper_id: string, highlight_id: string) =>
    request<{ removed: string }>(
      `/api/papers/${paper_id}/highlights/${highlight_id}`,
      { method: "DELETE" },
    ),
  enrich: (refresh = false) =>
    request<{ fetched: number; total: number; missing?: string[] }>(
      `/api/enrich?refresh=${refresh}`,
      { method: "POST" },
    ),
  prerequisites: (limit = 20, search_id?: string | null) =>
    request<{
      prerequisites: Prerequisite[];
      enriched: number;
      library: number;
      scoped?: boolean;
    }>(
      `/api/prerequisites?limit=${limit}${
        search_id ? `&search_id=${encodeURIComponent(search_id)}` : ""
      }`,
    ),
  addPaper: (arxiv_id: string, search_id?: string | null) =>
    request<{
      added: boolean;
      paper_id?: string;
      title?: string;
      reason?: string;
      attached_to_search?: boolean;
    }>("/api/papers/add", {
      method: "POST",
      body: JSON.stringify({ arxiv_id, search_id: search_id ?? null }),
    }),
  removePaper: (paper_id: string) =>
    request<{ removed: boolean; searches_updated: string[] }>(
      `/api/papers/${paper_id}`,
      { method: "DELETE" },
    ),
  askPaper: (paper_id: string, question: string, anchor?: string) =>
    request<ChatAnswer>(`/api/papers/${paper_id}/chat`, {
      method: "POST",
      body: JSON.stringify({ question, anchor }),
    }),
  matrix: (paper_ids: string[], refresh = false) =>
    request<{ rows: MatrixRow[] }>(`/api/matrix?refresh=${refresh}`, {
      method: "POST",
      body: JSON.stringify({ paper_ids }),
    }),
  relatedWork: (paper_ids: string[], topic: string) =>
    request<RelatedWork>("/api/related-work", {
      method: "POST",
      body: JSON.stringify({ paper_ids, topic }),
    }),
  compare: (paper_a: string, paper_b: string) =>
    request<CompareResult>("/api/compare", {
      method: "POST",
      body: JSON.stringify({ paper_a, paper_b }),
    }),
  makeCards: (paper_id: string, refresh = false) =>
    request<{ cards: Flashcard[]; generated: boolean }>(
      `/api/papers/${paper_id}/cards?refresh=${refresh}`,
      { method: "POST" },
    ),
  cards: (options: { dueOnly?: boolean; paperId?: string } = {}) => {
    const params = new URLSearchParams();
    if (options.dueOnly) params.set("due_only", "true");
    if (options.paperId) params.set("paper_id", options.paperId);
    const query = params.toString();
    return request<CardsResponse>(`/api/cards${query ? `?${query}` : ""}`);
  },
  gradeCard: (card_id: string, answer: string) =>
    request<GradeResult>("/api/cards/grade", {
      method: "POST",
      body: JSON.stringify({ card_id, answer }),
    }),
  relationshipCards: (search_id: string) =>
    request<{ cards: Flashcard[]; generated: number }>(
      `/api/searches/${search_id}/relationship-cards`,
      { method: "POST" },
    ),
  searchDiff: (a: string, b: string) =>
    request<SearchDiff>(
      `/api/search-diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`,
    ),
  runDigest: (search_id: string) =>
    request<Digest>(`/api/searches/${search_id}/digest`, { method: "POST" }),
  digests: (search_id: string) =>
    request<{ digests: Digest[] }>(`/api/searches/${search_id}/digests`),
  setFollowed: (search_id: string, followed: boolean) =>
    request<{ search_id: string; followed: boolean }>(`/api/searches/${search_id}/follow`, {
      method: "POST",
      body: JSON.stringify({ followed }),
    }),
  librarySearch: (q: string, limit = 10) =>
    request<LibrarySearchResult>(
      `/api/library/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  readingNudges: (search_id: string) =>
    request<{ nudges: ReadingNudge[] }>(`/api/searches/${search_id}/reading-nudges`),
  artifacts: () => request<ArtifactsResponse>(`/api/library/artifacts`),
  buildResults: (paper_ids: string[], refresh = false) =>
    request<{ rows: ResultRow[] }>(`/api/results${refresh ? "?refresh=true" : ""}`, {
      method: "POST",
      body: JSON.stringify({ paper_ids }),
    }),
  results: () => request<{ rows: ResultRow[] }>(`/api/results`),
  gaps: () => request<{ report: GapReport | null }>(`/api/library/gaps`),
  buildGaps: () =>
    request<{ report: GapReport }>(`/api/library/gaps`, { method: "POST" }),
  review: (paper_id: string) =>
    request<{ review: PeerReview | null }>(`/api/papers/${paper_id}/review`),
  buildReview: (paper_id: string, refresh = false) =>
    request<{ review: PeerReview }>(
      `/api/papers/${paper_id}/review${refresh ? "?refresh=true" : ""}`,
      { method: "POST" },
    ),
  uploadPdf: async (
    file: File,
  ): Promise<{ added: boolean; paper_id?: string; title?: string; reason?: string; word_count?: number }> => {
    const formData = new FormData();
    formData.append("file", file);
    let response: Response;
    try {
      // No Content-Type header here on purpose — the browser sets the
      // multipart boundary itself; forcing application/json (request<T>'s
      // default) would break the upload.
      response = await fetch(`${API_BASE}/api/papers/upload`, { method: "POST", body: formData });
    } catch {
      throw new Error(`Backend not reachable at ${API_LABEL}. Is uvicorn running?`);
    }
    if (!response.ok) {
      let detail = `Upload failed (${response.status})`;
      try {
        const body = await response.json();
        if (body?.detail) detail = String(body.detail);
      } catch {
        /* keep default detail */
      }
      throw new Error(detail);
    }
    return response.json();
  },
  getNote: (paperId: string) =>
    request<{ paper_id: string; text: string }>(
      `/api/papers/${encodeURIComponent(paperId)}/note`,
    ),
  setNote: (paperId: string, text: string) =>
    request<{ paper_id: string; text: string }>(
      `/api/papers/${encodeURIComponent(paperId)}/note`,
      { method: "POST", body: JSON.stringify({ text }) },
    ),
};

/** Downloads that stream a file back rather than JSON. */
export async function downloadFile(
  path: string,
  body: unknown,
  filename: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `Download failed (${response.status})`;
    try {
      detail = (await response.json())?.detail ?? detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
