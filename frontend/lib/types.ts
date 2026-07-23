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

export interface DeepJob {
  id: string;
  paper_id: string;
  status: "running" | "done" | "error";
  stages: StageState[];
  error?: string | null;
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

export interface EnginesResponse {
  active: string;
  engines: Engine[];
}
