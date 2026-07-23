"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type {
  ChatAnswer,
  DeepDive,
  DeepJob,
  Extraction,
  Paper,
} from "@/lib/types";
import RichText from "./RichText";

type Tab = "summary" | "explain" | "sections" | "critique" | "chat";
type Level = "undergrad" | "grad" | "expert";

const TABS: { key: Tab; label: string; deepOnly: boolean }[] = [
  { key: "summary", label: "Summary", deepOnly: false },
  { key: "explain", label: "Explain", deepOnly: true },
  { key: "sections", label: "Sections", deepOnly: true },
  { key: "critique", label: "Critique", deepOnly: true },
  { key: "chat", label: "Chat", deepOnly: true },
];

const LEVELS: { key: Level; label: string; hint: string }[] = [
  { key: "undergrad", label: "Beginner", hint: "No jargon, plain analogy" },
  { key: "grad", label: "Grad student", hint: "Assumes ML basics" },
  { key: "expert", label: "Expert", hint: "Only the delta vs prior work" },
];

interface Props {
  paper: Paper;
  extraction?: Extraction;
  number?: number;
  isRead: boolean;
  hasDeep: boolean;
  onToggleRead: (read: boolean) => void;
  onDeepDone: () => void;
  onClose: () => void;
}

/**
 * Chat opener prompts, built from this paper's own deep-read output instead of
 * a fixed list. The same four generic questions were showing under every
 * paper regardless of topic; reviewer_questions and the glossary are already
 * paper-specific and already loaded, so this needs no extra LLM call.
 */
function chatSuggestions(deep: DeepDive): string[] {
  const out: string[] = [];
  for (const q of deep.critique.reviewer_questions) {
    if (out.length >= 3) break;
    out.push(q.length <= 90 ? q : `${q.slice(0, 87)}…`);
  }
  const term = deep.glossary[0]?.term;
  if (term) out.push(`How does this paper use "${term}"?`);
  if (deep.contributions[0]) out.push("What's the main contribution, in one sentence?");
  return out.slice(0, 4);
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4">
      <p className="text-sm font-semibold text-stone-900">{title}</p>
      <div className="mt-1.5 text-sm leading-relaxed text-stone-600">{children}</div>
    </div>
  );
}

function StageDot({ status }: { status: string }) {
  if (status === "done")
    return <span className="h-2 w-2 shrink-0 rounded-full bg-[#0ca30c]" />;
  if (status === "active")
    return <span className="h-2 w-2 shrink-0 animate-pulse-dot rounded-full bg-[#2a78d6]" />;
  if (status === "error")
    return <span className="h-2 w-2 shrink-0 rounded-full bg-[#d03b3b]" />;
  return <span className="h-2 w-2 shrink-0 rounded-full border border-stone-300" />;
}

export default function PaperWorkspace({
  paper,
  extraction,
  number,
  isRead,
  hasDeep,
  onToggleRead,
  onDeepDone,
  onClose,
}: Props) {
  const [tab, setTab] = useState<Tab>("summary");
  const [level, setLevel] = useState<Level>("undergrad");
  const [deep, setDeep] = useState<DeepDive | null>(null);
  const [job, setJob] = useState<DeepJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [chatLog, setChatLog] = useState<
    { question: string; answer?: ChatAnswer; error?: string }[]
  >([]);
  const [asking, setAsking] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [onClose]);

  useEffect(() => {
    if (!hasDeep) return;
    api
      .deepDive(paper.id)
      .then(setDeep)
      .catch(() => setDeep(null));
  }, [paper.id, hasDeep]);

  const pollJob = useCallback(
    (jobId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const current = await api.deepJob(jobId);
          setJob(current);
          if (current.status !== "running") {
            if (pollRef.current) clearInterval(pollRef.current);
            if (current.status === "done") {
              setDeep(await api.deepDive(paper.id));
              onDeepDone();
            } else {
              setError(current.error ?? "Deep read failed.");
            }
          }
        } catch {
          /* transient poll failure */
        }
      }, 900);
    },
    [paper.id, onDeepDone],
  );

  // Resume progress if a read for this paper is already running (e.g. the
  // workspace was closed and reopened mid-read).
  useEffect(() => {
    if (hasDeep) return;
    let cancelled = false;
    api
      .runningDeepJob(paper.id)
      .then((result) => {
        if (cancelled) return;
        if ("id" in result && result.status === "running") {
          setJob(result);
          pollJob(result.id);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [paper.id, hasDeep, pollJob]);

  const startDeepDive = useCallback(async () => {
    setError(null);
    try {
      const { job_id } = await api.startDeepDive(paper.id);
      pollJob(job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [paper.id, pollJob]);

  const ask = async (event: React.FormEvent) => {
    event.preventDefault();
    const q = question.trim();
    if (!q || asking) return;
    setQuestion("");
    setChatLog((log) => [...log, { question: q }]);
    setAsking(true);
    try {
      const answer = await api.askPaper(paper.id, q);
      setChatLog((log) =>
        log.map((entry, i) => (i === log.length - 1 ? { ...entry, answer } : entry)),
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setChatLog((log) =>
        log.map((entry, i) => (i === log.length - 1 ? { ...entry, error: message } : entry)),
      );
    } finally {
      setAsking(false);
    }
  };

  const running = job?.status === "running";
  const terms = deep?.glossary ?? [];

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-stone-950/40 p-4 backdrop-blur-[2px] md:p-8"
      // Close only on a true backdrop click. Comparing target to currentTarget
      // is immune to inner elements unmounting mid-dispatch, which can skip a
      // child's stopPropagation and leak the click up here.
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={paper.title}
    >
      <div className="mx-auto w-full max-w-4xl rounded-2xl border border-stone-200 bg-[#fbfaf9] shadow-xl">
        {/* Header ------------------------------------------------------- */}
        <div className="border-b border-stone-200 p-6 pb-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
                {number ? `Paper #${number}` : "Paper"}
                {paper.relevance != null ? ` · ${Math.round(paper.relevance * 100)}% match` : ""}
                {extraction ? ` · ${extraction.paper_type}` : ""}
                {deep ? ` · full text read (${deep.total_words.toLocaleString()} words)` : ""}
              </p>
              <h2 className="mt-1 text-xl font-semibold leading-snug text-stone-900">
                {paper.title}
              </h2>
              <p className="mt-1.5 text-sm text-stone-500">
                {paper.authors.slice(0, 6).join(", ")}
                {paper.authors.length > 6 ? ` +${paper.authors.length - 6}` : ""} ·{" "}
                {paper.published} · {paper.primary_category}
              </p>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="shrink-0 rounded-lg border border-stone-200 bg-white px-2.5 py-1 text-sm text-stone-500 transition hover:bg-stone-100"
            >
              ✕
            </button>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <a
              href={paper.arxiv_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
            >
              ↗ arXiv
            </a>
            <a
              href={paper.pdf_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
            >
              ⤓ PDF
            </a>
            <button
              onClick={() => onToggleRead(!isRead)}
              className={
                isRead
                  ? "rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700 transition hover:bg-emerald-100"
                  : "rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
              }
            >
              {isRead ? "✓ Read" : "Mark as read"}
            </button>
            {!deep && !running ? (
              <button
                onClick={startDeepDive}
                className="rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-stone-700"
              >
                📖 Read full paper
              </button>
            ) : null}
            {running ? (
              <span className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm text-blue-700">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />
                Reading full paper…
              </span>
            ) : null}
          </div>

          {/* Tabs */}
          <div className="mt-4 flex flex-wrap gap-1">
            {TABS.map((entry) => {
              const locked = entry.deepOnly && !deep;
              return (
                <button
                  key={entry.key}
                  onClick={() => !locked && setTab(entry.key)}
                  disabled={locked}
                  title={locked ? "Read the full paper to unlock" : undefined}
                  className={
                    tab === entry.key
                      ? "rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-medium text-white"
                      : locked
                        ? "cursor-not-allowed rounded-lg px-3 py-1.5 text-sm text-stone-300"
                        : "rounded-lg px-3 py-1.5 text-sm text-stone-600 transition hover:bg-stone-100"
                  }
                >
                  {entry.label}
                  {locked ? " 🔒" : ""}
                </button>
              );
            })}
          </div>
        </div>

        {/* Body --------------------------------------------------------- */}
        <div className="p-6">
          {/* Deep-dive progress / errors */}
          {running && job ? (
            <div className="mb-5 rounded-xl border border-stone-200 bg-white p-4">
              <p className="text-sm font-medium text-stone-900">Reading the full paper</p>
              <p className="mt-0.5 text-xs text-stone-500">
                Fetching the paper from arXiv and studying it section by section — a few
                minutes on a local model.
              </p>
              <ul className="mt-3 space-y-2">
                {job.stages.map((stage) => (
                  <li key={stage.key} className="flex items-center gap-2.5">
                    <StageDot status={stage.status} />
                    <span
                      className={
                        stage.status === "active"
                          ? "text-xs font-medium text-stone-900"
                          : stage.status === "done"
                            ? "text-xs text-stone-600"
                            : "text-xs text-stone-400"
                      }
                    >
                      {stage.label}
                    </span>
                    {stage.detail ? (
                      <span className="ml-auto truncate text-xs text-stone-400">
                        {stage.detail}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {error ? (
            <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {error}
            </div>
          ) : null}

          {/* Summary tab */}
          {tab === "summary" ? (
            <div className="space-y-4">
              {extraction ? (
                <>
                  <div className="rounded-xl border border-stone-200 bg-white p-4">
                    <p className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
                      TL;DR
                    </p>
                    <p className="mt-1.5 text-[15px] leading-relaxed text-stone-800">
                      <RichText text={extraction.tldr} terms={terms} />
                    </p>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <Card title="Problem">
                      <RichText text={extraction.problem} terms={terms} />
                    </Card>
                    <Card title="Method">
                      <RichText text={extraction.method} terms={terms} />
                    </Card>
                    <Card title="Key results">
                      <RichText text={extraction.key_results} terms={terms} />
                    </Card>
                    <Card title="Why it matters">
                      <RichText text={extraction.why_it_matters} terms={terms} />
                    </Card>
                  </div>
                </>
              ) : null}

              {deep ? (
                <>
                  <Card title="Full-paper synthesis">
                    <RichText text={deep.deep_summary} terms={terms} />
                  </Card>
                  <div className="rounded-xl border border-stone-200 bg-white p-4">
                    <p className="text-sm font-semibold text-stone-900">Contributions</p>
                    <ul className="mt-2 space-y-1.5">
                      {deep.contributions.map((item, index) => (
                        <li key={index} className="flex gap-2 text-sm leading-relaxed text-stone-600">
                          <span className="text-stone-300">▸</span>
                          <span>
                            <RichText text={item} terms={terms} />
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <Card title="Results in detail">
                    <RichText text={deep.results_detail} terms={terms} />
                  </Card>
                </>
              ) : (
                <div className="rounded-xl border border-dashed border-stone-300 bg-white/60 p-5 text-center">
                  <p className="text-sm font-medium text-stone-700">
                    This summary comes from the abstract only
                  </p>
                  <p className="mx-auto mt-1 max-w-md text-sm leading-relaxed text-stone-500">
                    Read the full paper to unlock section-by-section digests, three-level
                    explanations, a jargon glossary, a critique card, and chat with citations.
                  </p>
                  {!running ? (
                    <button
                      onClick={startDeepDive}
                      className="mt-3 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700"
                    >
                      📖 Read full paper
                    </button>
                  ) : null}
                </div>
              )}

              {extraction ? (
                <div className="flex flex-wrap gap-1.5">
                  {extraction.keywords.map((keyword) => (
                    <span
                      key={keyword}
                      className="rounded-full border border-stone-200 bg-white px-2.5 py-0.5 text-xs text-stone-500"
                    >
                      {keyword}
                    </span>
                  ))}
                </div>
              ) : null}

              <details className="rounded-xl border border-stone-200 bg-white p-4">
                <summary className="cursor-pointer text-sm font-medium text-stone-700">
                  Original abstract
                </summary>
                <p className="mt-2 text-sm leading-relaxed text-stone-600">{paper.abstract}</p>
              </details>
            </div>
          ) : null}

          {/* Explain tab */}
          {tab === "explain" && deep ? (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-1.5">
                {LEVELS.map((entry) => (
                  <button
                    key={entry.key}
                    onClick={() => setLevel(entry.key)}
                    className={
                      level === entry.key
                        ? "rounded-lg border border-stone-900 bg-stone-900 px-3 py-1.5 text-sm font-medium text-white"
                        : "rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm text-stone-600 transition hover:border-stone-400"
                    }
                  >
                    {entry.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-stone-400">
                {LEVELS.find((entry) => entry.key === level)?.hint}
              </p>
              <div className="rounded-xl border border-stone-200 bg-white p-5">
                <p className="text-[15px] leading-relaxed text-stone-700">
                  <RichText text={deep.explanations[level]} terms={terms} />
                </p>
              </div>

              {terms.length > 0 ? (
                <div>
                  <p className="mb-2 text-sm font-semibold text-stone-900">
                    Glossary · {terms.length} terms
                  </p>
                  <div className="grid gap-2 md:grid-cols-2">
                    {terms.map((term) => (
                      <div
                        key={term.term}
                        className="rounded-xl border border-stone-200 bg-white p-3"
                      >
                        <p className="text-sm font-semibold text-stone-900">{term.term}</p>
                        <p className="mt-1 text-sm leading-relaxed text-stone-600">
                          {term.definition}
                        </p>
                        {term.in_this_paper ? (
                          <p className="mt-1.5 border-t border-stone-100 pt-1.5 text-xs leading-relaxed text-stone-500">
                            <span className="font-medium text-stone-600">In this paper: </span>
                            {term.in_this_paper}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Sections tab */}
          {tab === "sections" && deep ? (
            <div className="space-y-3">
              <p className="text-xs text-stone-400">
                Section-by-section reading of the full text ·{" "}
                <a
                  href={deep.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="underline underline-offset-2 hover:text-stone-600"
                >
                  source
                </a>
              </p>
              {deep.sections.map((section, index) => (
                <div key={index} className="rounded-xl border border-stone-200 bg-white p-4">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="text-sm font-semibold text-stone-900">{section.title}</p>
                    <span className="shrink-0 font-mono text-[11px] text-stone-400">
                      {section.words.toLocaleString()} words
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm leading-relaxed text-stone-600">
                    <RichText text={section.summary} terms={terms} />
                  </p>
                  <ul className="mt-2.5 space-y-1.5">
                    {section.key_points.map((point, i) => (
                      <li key={i} className="flex gap-2 text-sm leading-relaxed text-stone-600">
                        <span className="text-stone-300">▸</span>
                        <span>
                          <RichText text={point} terms={terms} />
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ) : null}

          {/* Critique tab */}
          {tab === "critique" && deep ? (
            <div className="space-y-3">
              <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                <p className="text-sm font-semibold text-amber-900">What this paper does not solve</p>
                <p className="mt-1.5 text-sm leading-relaxed text-amber-800">
                  <RichText text={deep.critique.not_solved} terms={terms} />
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-xl border border-stone-200 bg-white p-4">
                  <p className="text-sm font-semibold text-stone-900">Load-bearing assumptions</p>
                  <ul className="mt-2 space-y-1.5">
                    {deep.critique.assumptions.map((item, index) => (
                      <li key={index} className="flex gap-2 text-sm leading-relaxed text-stone-600">
                        <span className="text-stone-300">▸</span>
                        <span>
                          <RichText text={item} terms={terms} />
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-xl border border-stone-200 bg-white p-4">
                  <p className="text-sm font-semibold text-stone-900">Methodological weaknesses</p>
                  <ul className="mt-2 space-y-1.5">
                    {deep.critique.weaknesses.map((item, index) => (
                      <li key={index} className="flex gap-2 text-sm leading-relaxed text-stone-600">
                        <span className="text-stone-300">▸</span>
                        <span>
                          <RichText text={item} terms={terms} />
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              <div className="rounded-xl border border-stone-200 bg-white p-4">
                <p className="text-sm font-semibold text-stone-900">
                  Questions a reviewer would ask
                </p>
                <ol className="mt-2 space-y-2">
                  {deep.critique.reviewer_questions.map((item, index) => (
                    <li key={index} className="flex gap-3 text-sm leading-relaxed text-stone-600">
                      <span className="font-mono text-xs font-semibold text-stone-300">
                        Q{index + 1}
                      </span>
                      <span>
                        <RichText text={item} terms={terms} />
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          ) : null}

          {/* Chat tab */}
          {tab === "chat" && deep ? (
            <div className="space-y-4">
              <p className="text-xs text-stone-400">
                Answers are retrieved from {deep.chunk_count} passages of the full text and cite
                the sections they came from.
              </p>

              {chatLog.length === 0 ? (
                <div className="rounded-xl border border-dashed border-stone-300 bg-white/60 p-4">
                  <p className="text-sm text-stone-500">Try asking:</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {chatSuggestions(deep).map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => setQuestion(suggestion)}
                        className="rounded-full border border-stone-200 bg-white px-3 py-1 text-xs text-stone-600 transition hover:border-stone-400"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="space-y-4">
                {chatLog.map((entry, index) => (
                  <div key={index} className="space-y-2">
                    <p className="rounded-xl bg-stone-900 px-4 py-2.5 text-sm text-white">
                      {entry.question}
                    </p>
                    {entry.answer ? (
                      <div className="rounded-xl border border-stone-200 bg-white p-4">
                        <p className="text-sm leading-relaxed text-stone-700">
                          <RichText text={entry.answer.answer} terms={terms} />
                        </p>
                        <details className="mt-3 border-t border-stone-100 pt-2">
                          <summary className="cursor-pointer text-xs font-medium text-stone-500">
                            {entry.answer.sources.length} source passages
                          </summary>
                          <ul className="mt-2 space-y-2">
                            {entry.answer.sources.map((source, i) => (
                              <li key={i} className="rounded-lg bg-stone-50 p-2.5">
                                <p className="font-mono text-[11px] uppercase tracking-wide text-stone-400">
                                  [{i + 1}] {source.section} · {source.score.toFixed(2)}
                                </p>
                                <p className="mt-1 text-xs leading-relaxed text-stone-600">
                                  {source.text.slice(0, 400)}
                                  {source.text.length > 400 ? "…" : ""}
                                </p>
                              </li>
                            ))}
                          </ul>
                        </details>
                      </div>
                    ) : entry.error ? (
                      <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
                        {entry.error}
                      </p>
                    ) : (
                      <p className="flex items-center gap-2 rounded-xl border border-stone-200 bg-white px-4 py-2.5 text-sm text-stone-400">
                        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />
                        Searching the paper…
                      </p>
                    )}
                  </div>
                ))}
              </div>

              <form onSubmit={ask} className="flex gap-2">
                <input
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="Ask anything about this paper…"
                  disabled={asking}
                  className="w-full rounded-lg border border-stone-300 bg-white px-3.5 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none disabled:bg-stone-50"
                />
                <button
                  type="submit"
                  disabled={asking || !question.trim()}
                  className="shrink-0 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
                >
                  Ask
                </button>
              </form>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
