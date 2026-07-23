import type {
  AppState,
  CardsResponse,
  EnginesResponse,
  ChatAnswer,
  CompareResult,
  DeepDive,
  DeepJob,
  Digest,
  Flashcard,
  GradeResult,
  Health,
  Job,
  MatrixRow,
  Prerequisite,
  RelatedWork,
  SearchDetail,
  SearchDiff,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8321";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error(`Backend not reachable at ${API_BASE}. Is uvicorn running?`);
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
  askPaper: (paper_id: string, question: string) =>
    request<ChatAnswer>(`/api/papers/${paper_id}/chat`, {
      method: "POST",
      body: JSON.stringify({ question }),
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
