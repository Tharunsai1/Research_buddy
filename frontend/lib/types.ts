export interface Paper {
  id: string;
  title: string;
  authors: string[];
  abstract: string;
  published: string;
  categories: string[];
  primary_category: string;
  arxiv_url: string;
  pdf_url: string;
  comment?: string | null;
  relevance?: number | null;
}

export interface Extraction {
  tldr: string;
  problem: string;
  method: string;
  key_results: string;
  why_it_matters: string;
  keywords: string[];
  paper_type: string;
}

export interface Edge {
  source: string;
  target: string;
  kind: string;
  description: string;
  bridge?: boolean;
  /** true = real citation from Semantic Scholar; false = LLM-inferred */
  real?: boolean;
}

export interface CitationMetrics {
  citations: number;
  influential: number;
  references: number;
  year: number | null;
}

export interface Prerequisite {
  arxiv_id: string;
  title: string;
  citation_count: number;
  year: number | null;
  cited_by: string[];
  in_library: boolean;
}

export interface SearchCluster {
  name: string;
  description: string;
  paper_ids: string[];
}

export interface Tension {
  name: string;
  description: string;
  side_a: { label: string; paper_ids: string[] };
  side_b: { label: string; paper_ids: string[] };
}

export interface OpenProblem {
  title: string;
  description: string;
  paper_ids: string[];
}

export interface ReadingStep {
  paper_id: string;
  stage: "foundation" | "core" | "frontier";
  why: string;
}

export interface SearchDetail {
  id: string;
  query: string;
  title: string;
  created_at: string;
  paper_ids: string[];
  overview: string;
  clusters: SearchCluster[];
  edges: Edge[];
  tensions: Tension[];
  consensus: string[];
  open_problems: OpenProblem[];
  reading_order: ReadingStep[];
  followed?: boolean;
}

export interface SearchMeta {
  id: string;
  query: string;
  title: string;
  created_at: string;
  paper_count: number;
}

export interface MapCluster {
  name: string;
  paper_ids: string[];
}

export interface AppState {
  papers: Record<string, Paper>;
  extractions: Record<string, Extraction>;
  read: string[];
  map: {
    clusters: MapCluster[];
    edges: Edge[];
    seminal?: Record<string, string>;
  };
  searches: SearchMeta[];
  latest_search_id: string | null;
  deep_read: string[];
  citations?: Record<string, CitationMetrics>;
}

// --- deep dive ------------------------------------------------------------

export interface SectionDigest {
  title: string;
  summary: string;
  key_points: string[];
  words: number;
}

export interface Explanations {
  undergrad: string;
  grad: string;
  expert: string;
}

export interface GlossaryTerm {
  term: string;
  definition: string;
  in_this_paper: string;
}

export interface Critique {
  not_solved: string;
  assumptions: string[];
  weaknesses: string[];
  reviewer_questions: string[];
}

export interface DeepDive {
  paper_id: string;
  source_url: string;
  total_words: number;
  deep_summary: string;
  contributions: string[];
  results_detail: string;
  sections: SectionDigest[];
  explanations: Explanations;
  glossary: GlossaryTerm[];
  critique: Critique;
  chunk_count: number;
  created_at: string;
}

export interface DeepJobPartial {
  source_url?: string;
  total_words?: number;
  sections?: SectionDigest[];
  synthesis?: { deep_summary: string; contributions: string[]; results_detail: string };
  explanations?: Explanations;
  glossary?: GlossaryTerm[];
  critique?: Critique;
}

export interface DeepJob {
  id: string;
  paper_id: string;
  status: "running" | "done" | "error";
  stages: StageState[];
  error?: string | null;
  /** Filled in as each generation phase finishes, before the job is fully done. */
  partial?: DeepJobPartial;
}

export interface ChatSource {
  section: string;
  text: string;
  score: number;
}

export interface ChatAnswer {
  answer: string;
  sources: ChatSource[];
}

// --- research toolkit -----------------------------------------------------

export interface MatrixRow {
  paper_id: string;
  task: string;
  method_family: string;
  key_idea: string;
  datasets: string[];
  metrics: string[];
  headline_result: string;
  code_available: string;
  code_url: string | null;
  from_fulltext: boolean;
}

export interface RelatedWorkParagraph {
  theme: string;
  text: string;
}

export interface RelatedWork {
  paragraphs: RelatedWorkParagraph[];
  gap_statement: string;
  bibtex: string;
  keys: Record<string, string>;
  paper_ids: string[];
}

export interface Comparison {
  problem_a: string;
  problem_b: string;
  method_a: string;
  method_b: string;
  results_a: string;
  results_b: string;
  strengths_a: string;
  strengths_b: string;
  limitations_a: string;
  limitations_b: string;
  key_difference: string;
  when_to_use_a: string;
  when_to_use_b: string;
}

export interface CompareResult {
  paper_a: string;
  paper_b: string;
  comparison: Comparison;
}

// --- learning loop --------------------------------------------------------

export interface Flashcard {
  id: string;
  paper_id: string;
  question: string;
  answer: string;
  kind: string;
  /** For kind="relationship": the other paper in the pair. */
  related_paper_id?: string | null;
  due: string;
  interval: number;
  ease: number;
  reps: number;
  lapses: number;
  last_score: number | null;
}

export interface Grade {
  verdict: "correct" | "partial" | "incorrect";
  score: number;
  feedback: string;
  missed: string[];
}

export interface GradeResult {
  grade: Grade;
  card: Flashcard;
}

export interface CardsResponse {
  cards: Flashcard[];
  total: number;
  due: number;
  papers: string[];
}

export interface DigestHighlight {
  paper_id: string;
  why_it_matters: string;
  challenges_consensus: boolean;
  relation: string;
}

export interface Digest {
  search_id: string;
  query: string;
  created_at: string;
  checked_count: number;
  new_paper_ids: string[];
  headline: string;
  summary: string;
  highlights: DigestHighlight[];
}

// --- search history diffing ------------------------------------------------

export interface PaperBrief {
  id: string;
  title: string;
}

export interface SearchDiffSide {
  id: string;
  query: string;
  title: string;
  created_at: string;
  paper_count: number;
}

export interface SearchDiff {
  a: SearchDiffSide;
  b: SearchDiffSide;
  shared_paper_count: number;
  new_papers: PaperBrief[];
  dropped_papers: PaperBrief[];
  clusters_added: string[];
  clusters_removed: string[];
  consensus_added: string[];
  consensus_removed: string[];
  tensions_added: string[];
  tensions_removed: string[];
  open_problems_added: string[];
  open_problems_removed: string[];
}

export interface LibrarySearchHit {
  paper_id: string;
  score: number;
  paper: Paper;
}

export interface LibrarySearchResult {
  query: string;
  results: LibrarySearchHit[];
}

export interface ReadingNudge {
  weak_paper_id: string;
  weak_paper_title: string;
  avg_score: number;
  reviewed_count: number;
  blocks: string[];
  blocks_titles: string[];
}

export interface StageState {
  key: string;
  label: string;
  status: "pending" | "active" | "done" | "error";
  detail: string;
}

export interface Job {
  id: string;
  query: string;
  status: "running" | "done" | "error";
  stages: StageState[];
  error?: string | null;
  search_id?: string | null;
}

export interface Health {
  ok: boolean;
  engine?: string;
  provider: string;
  model: string;
  ready: boolean;
  detail?: string | null;
  embeddings_ready?: boolean;
  embeddings_detail?: string | null;
  cross_encoder: string;
  papers_per_search: number;
}

export interface Engine {
  id: string;
  label: string;
  provider: string;
  model: string;
  blurb: string;
  speed: string;
}

export interface OpenRouterUsage {
  used: number;
  cap: number;
  remaining: number;
  near_cap: boolean;
}

export interface EnginesResponse {
  active: string;
  engines: Engine[];
  openrouter_usage?: OpenRouterUsage;
}

/** Code availability + reproducibility signals (regex over the paper's text). */
export interface PaperArtifacts {
  paper_id: string;
  title: string;
  published: string;
  repos: string[];
  has_code: boolean;
  signals: Record<string, boolean>;
  signal_count: number;
  signal_total: number;
  scanned_full_text: boolean;
}

export interface ArtifactsResponse {
  papers: PaperArtifacts[];
  labels: Record<string, string>;
}

/** One reported evaluation number. */
export interface ResultRow {
  paper_id: string;
  system: string;
  is_this_paper: boolean;
  dataset: string;
  metric: string;
  value: string;
  split: string;
}

export interface ResearchGap {
  title: string;
  description: string;
  why_it_matters: string;
  first_step: string;
  paper_ids: string[];
  paper_titles: string[];
}

export interface GapReport {
  gaps: ResearchGap[];
  paper_count: number;
  created_at: string;
}

export interface PeerReview {
  paper_id: string;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  questions: string[];
  soundness: number;
  contribution: number;
  presentation: number;
  recommendation: string;
  confidence: number;
  from_fulltext: boolean;
  created_at: string;
}

/** What the backend's warm-up queue is doing. `warming` is the paper being
 *  read right now (at most one — warming is deliberately serial). */
export interface PrefetchState {
  warming: string | null;
  queued: string[];
}

/** A passage the reader marked. `quote` plus `prefix`/`suffix` is the anchor —
 *  see lib/anchoring.ts for why it is text rather than a position. */
export interface Highlight {
  id: string;
  paper_id: string;
  tab: string;
  quote: string;
  prefix: string;
  suffix: string;
  note: string;
  created_at: string;
}
