"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { API_BASE, api } from "@/lib/api";
import type {
  ChatAnswer,
  DeepDive,
  DeepJob,
  Extraction,
  Paper,
  PeerReview,
} from "@/lib/types";
import RichText from "./RichText";

type Tab = "summary" | "explain" | "sections" | "critique" | "review" | "chat";
type Level = "undergrad" | "grad" | "expert";

const TABS: { key: Tab; label: string; deepOnly: boolean }[] = [
  { key: "summary", label: "Summary", deepOnly: false },
  { key: "explain", label: "Explain", deepOnly: true },
  { key: "sections", label: "Sections", deepOnly: true },
  { key: "critique", label: "Critique", deepOnly: true },
  // Works from the abstract alone (with a lower confidence score), so unlike
  // the other analysis tabs this one is never locked.
  { key: "review", label: "Review", deepOnly: false },
  { key: "chat", label: "Chat", deepOnly: true },
];

const RECOMMENDATION_STYLE: Record<string, string> = {
  "strong accept": "border-emerald-300 bg-emerald-50 text-emerald-800",
  accept: "border-emerald-200 bg-emerald-50 text-emerald-700",
  borderline: "border-amber-200 bg-amber-50 text-amber-800",
  reject: "border-red-200 bg-red-50 text-red-700",
  "strong reject": "border-red-300 bg-red-50 text-red-800",
};

function ScoreBar({ label, score }: { label: string; score: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-24 shrink-0 text-xs text-stone-500">{label}</span>
      <span className="flex gap-0.5">
        {[1, 2, 3, 4, 5].map((step) => (
          <span
            key={step}
            className={
              step <= score
                ? "h-1.5 w-5 rounded-full bg-stone-800"
                : "h-1.5 w-5 rounded-full bg-stone-200"
            }
          />
        ))}
      </span>
      <span className="font-mono text-xs text-stone-500">{score}/5</span>
    </div>
  );
}

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
  /** Called after the paper is removed from the library — undo for a wrong add/placement. */
  onRemoved: () => void;
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
  onRemoved,
  onClose,
}: Props) {
  const [tab, setTab] = useState<Tab>("summary");
  const [level, setLevel] = useState<Level>("undergrad");
  const [deep, setDeep] = useState<DeepDive | null>(null);
  const [job, setJob] = useState<DeepJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [question, setQuestion] = useState("");
  const [chatLog, setChatLog] = useState<
    { question: string; anchor?: string; answer?: ChatAnswer; error?: string }[]
  >([]);
  const [asking, setAsking] = useState(false);
  const [highlight, setHighlight] = useState<{ text: string; top: number; left: number } | null>(
    null,
  );
  const [pendingAnchor, setPendingAnchor] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [noteText, setNoteText] = useState("");
  const [noteSaved, setNoteSaved] = useState("");
  const [noteLoaded, setNoteLoaded] = useState(false);
  const [noteSaving, setNoteSaving] = useState(false);
  const [review, setReview] = useState<PeerReview | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const noteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const noteRef = useRef({ text: "", saved: "" });
  noteRef.current = { text: noteText, saved: noteSaved };

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

  // Load any saved review when the paper changes. Generating one is always an
  // explicit click — it costs an LLM call.
  useEffect(() => {
    let cancelled = false;
    setReview(null);
    api
      .review(paper.id)
      .then((result) => {
        if (!cancelled) setReview(result.review);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [paper.id]);

  const runReview = async (refresh = false) => {
    setReviewBusy(true);
    setError(null);
    try {
      const result = await api.buildReview(paper.id, refresh);
      setReview(result.review);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setReviewBusy(false);
    }
  };

  // Highlight-and-ask: a document-level listener (not one scoped to the
  // content div) so the floating button also disappears when the reader
  // clicks away to somewhere else in the workspace, not just when they make
  // a new selection inside the reading pane. Gated on `deep` because the
  // Chat tab itself is — "Ask about this" would otherwise be a dead end.
  useEffect(() => {
    const onSelection = () => {
      const selection = window.getSelection();
      const text = selection?.toString().trim() ?? "";
      if (!deep || !text || text.length < 3 || text.length > 2000 || !selection?.rangeCount) {
        setHighlight(null);
        return;
      }
      const range = selection.getRangeAt(0);
      if (!contentRef.current?.contains(range.commonAncestorContainer)) {
        setHighlight(null);
        return;
      }
      const rect = range.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) {
        setHighlight(null);
        return;
      }
      setHighlight({ text, top: Math.max(rect.top - 44, 8), left: rect.left + rect.width / 2 });
    };
    document.addEventListener("mouseup", onSelection);
    document.addEventListener("keyup", onSelection);
    return () => {
      document.removeEventListener("mouseup", onSelection);
      document.removeEventListener("keyup", onSelection);
    };
  }, [deep]);

  // Notes: load fresh whenever the open paper changes, then autosave 800ms
  // after typing stops so there is no separate Save button to remember to
  // click. The workspace can switch straight from one paper to another
  // without unmounting (no `key` on this component in page.tsx), so a
  // pending edit is flushed in this effect's own cleanup — covering both a
  // paper switch and the workspace closing, not just an unmount.
  useEffect(() => {
    setNoteLoaded(false);
    let cancelled = false;
    api
      .getNote(paper.id)
      .then((result) => {
        if (cancelled) return;
        setNoteText(result.text);
        setNoteSaved(result.text);
        setNoteLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setNoteLoaded(true);
      });
    return () => {
      cancelled = true;
      if (noteTimerRef.current) clearTimeout(noteTimerRef.current);
      const { text, saved } = noteRef.current;
      if (text !== saved) {
        api.setNote(paper.id, text).catch(() => {});
      }
    };
  }, [paper.id]);

  useEffect(() => {
    if (!noteLoaded || noteText === noteSaved) return;
    if (noteTimerRef.current) clearTimeout(noteTimerRef.current);
    noteTimerRef.current = setTimeout(() => {
      setNoteSaving(true);
      api
        .setNote(paper.id, noteText)
        .then((result) => setNoteSaved(result.text))
        .catch(() => {})
        .finally(() => setNoteSaving(false));
    }, 800);
    return () => {
      if (noteTimerRef.current) clearTimeout(noteTimerRef.current);
    };
  }, [noteText, noteSaved, noteLoaded, paper.id]);

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

  const doRemove = async () => {
    setRemoving(true);
    setError(null);
    try {
      await api.removePaper(paper.id);
      onRemoved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRemoving(false);
      setConfirmRemove(false);
    }
  };

  const ask = async (event: React.FormEvent) => {
    event.preventDefault();
    const q = question.trim();
    if (!q || asking) return;
    const anchor = pendingAnchor ?? undefined;
    setQuestion("");
    setPendingAnchor(null);
    setChatLog((log) => [...log, { question: q, anchor }]);
    setAsking(true);
    try {
      const answer = await api.askPaper(paper.id, q, anchor);
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

  const useHighlight = () => {
    if (!highlight) return;
    setPendingAnchor(highlight.text);
    setTab("chat");
    setHighlight(null);
    window.getSelection()?.removeAllRanges();
  };

  const running = job?.status === "running";

  // Deep dive takes ~90s-4min; waiting for the whole thing to unlock any
  // reading is the slow part, not the total time. Each generation phase
  // (sections, synthesis, explanations, glossary, critique) lands
  // independently on the job while it's still running — surface each as soon
  // as it's ready instead of gating everything on full completion. `deep`
  // (the saved, complete DeepDive) always wins once it exists.
  const partial = job?.partial;
  const sectionsReady = Boolean(deep) || Boolean(partial?.sections?.length);
  const synthesisReady = Boolean(deep) || Boolean(partial?.synthesis);
  const explainReady = Boolean(deep) || Boolean(partial?.explanations);
  const critiqueReady = Boolean(deep) || Boolean(partial?.critique);

  const view: DeepDive | null =
    deep ??
    (partial
      ? {
          paper_id: paper.id,
          source_url: partial.source_url ?? "",
          total_words: partial.total_words ?? 0,
          deep_summary: partial.synthesis?.deep_summary ?? "",
          contributions: partial.synthesis?.contributions ?? [],
          results_detail: partial.synthesis?.results_detail ?? "",
          sections: partial.sections ?? [],
          explanations: partial.explanations ?? { undergrad: "", grad: "", expert: "" },
          glossary: partial.glossary ?? [],
          critique:
            partial.critique ?? {
              not_solved: "",
              assumptions: [],
              weaknesses: [],
              reviewer_questions: [],
            },
          chunk_count: 0,
          created_at: "",
        }
      : null);

  const terms = view?.glossary ?? [];

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
      {highlight
        ? createPortal(
            <button
              onClick={useHighlight}
              style={{ top: highlight.top, left: highlight.left, transform: "translateX(-50%)" }}
              className="fixed z-[60] whitespace-nowrap rounded-full bg-stone-900 px-3 py-1.5 text-xs font-medium text-white shadow-lg transition hover:bg-stone-700"
            >
              💬 Ask about this
            </button>,
            document.body,
          )
        : null}

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
            {paper.arxiv_url ? (
              <a
                href={paper.arxiv_url}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
              >
                ↗ arXiv
              </a>
            ) : (
              <span
                title="Uploaded directly — not published on arXiv"
                className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-1.5 text-sm font-medium text-stone-400"
              >
                📄 Uploaded PDF
              </span>
            )}
            <a
              href={paper.pdf_url.startsWith("/") ? `${API_BASE}${paper.pdf_url}` : paper.pdf_url}
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
            {confirmRemove ? (
              <span className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-1.5 text-sm text-red-700">
                Remove from library?
                <button
                  onClick={doRemove}
                  disabled={removing}
                  className="font-medium underline underline-offset-2 disabled:opacity-50"
                >
                  {removing ? "Removing…" : "Yes, remove"}
                </button>
                <button
                  onClick={() => setConfirmRemove(false)}
                  disabled={removing}
                  className="text-red-400 hover:text-red-600 disabled:opacity-50"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                onClick={() => setConfirmRemove(true)}
                title="Remove this paper from your library — undoes a mistaken add or placement"
                className="rounded-lg border border-transparent px-3 py-1.5 text-sm text-stone-400 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
              >
                🗑 Remove
              </button>
            )}
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
              const ready: Record<Tab, boolean> = {
                summary: true,
                explain: explainReady,
                sections: sectionsReady,
                critique: critiqueReady,
                // Reviewable from the abstract alone, so never gated.
                review: true,
                // Chat needs the passage index, built only after the full
                // read finishes — no partial version of that is meaningful.
                chat: Boolean(deep),
              };
              const locked = entry.deepOnly && !ready[entry.key];
              // Ready early but the rest of the read is still in flight —
              // this tab may still fill in further (e.g. sections done,
              // critique not yet).
              const stillFilling = running && !locked && entry.deepOnly && !deep;
              return (
                <button
                  key={entry.key}
                  onClick={() => !locked && setTab(entry.key)}
                  disabled={locked}
                  title={
                    locked
                      ? "Read the full paper to unlock"
                      : stillFilling
                        ? "Ready early — the rest of the read is still in progress"
                        : undefined
                  }
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
                  {stillFilling ? (
                    <span className="ml-1.5 inline-block h-1.5 w-1.5 animate-pulse-dot rounded-full bg-[#2a78d6] align-middle" />
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>

        {/* Body --------------------------------------------------------- */}
        <div className="p-6" ref={contentRef}>
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
              <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-stone-900">Your notes</p>
                  <span className="text-xs text-stone-400">
                    {noteSaving ? "Saving…" : noteLoaded && noteText ? "Saved" : ""}
                  </span>
                </div>
                <textarea
                  value={noteText}
                  onChange={(event) => setNoteText(event.target.value)}
                  disabled={!noteLoaded}
                  placeholder="Half-formed thoughts, questions, or how this contradicts another paper — yours, not generated. Saves automatically."
                  rows={3}
                  maxLength={20000}
                  className="mt-2 w-full resize-y rounded-lg border border-amber-200 bg-white px-3 py-2 text-sm leading-relaxed text-stone-800 placeholder:text-stone-400 focus:border-amber-400 focus:outline-none disabled:opacity-60"
                />
              </div>

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

              {synthesisReady && view ? (
                <>
                  <Card title="Full-paper synthesis">
                    <RichText text={view.deep_summary} terms={terms} />
                  </Card>
                  <div className="rounded-xl border border-stone-200 bg-white p-4">
                    <p className="text-sm font-semibold text-stone-900">Contributions</p>
                    <ul className="mt-2 space-y-1.5">
                      {view.contributions.map((item, index) => (
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
                    <RichText text={view.results_detail} terms={terms} />
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
          {tab === "explain" && explainReady && view ? (
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
                  <RichText text={view.explanations[level]} terms={terms} />
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
          {tab === "sections" && sectionsReady && view ? (
            <div className="space-y-3">
              <p className="text-xs text-stone-400">
                Section-by-section reading of the full text
                {view.source_url ? (
                  <>
                    {" · "}
                    <a
                      href={view.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="underline underline-offset-2 hover:text-stone-600"
                    >
                      source
                    </a>
                  </>
                ) : null}
              </p>
              {view.sections.map((section, index) => (
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
          {tab === "critique" && critiqueReady && view ? (
            <div className="space-y-3">
              <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                <p className="text-sm font-semibold text-amber-900">What this paper does not solve</p>
                <p className="mt-1.5 text-sm leading-relaxed text-amber-800">
                  <RichText text={view.critique.not_solved} terms={terms} />
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-xl border border-stone-200 bg-white p-4">
                  <p className="text-sm font-semibold text-stone-900">Load-bearing assumptions</p>
                  <ul className="mt-2 space-y-1.5">
                    {view.critique.assumptions.map((item, index) => (
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
                    {view.critique.weaknesses.map((item, index) => (
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
                  {view.critique.reviewer_questions.map((item, index) => (
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

          {/* Review tab */}
          {tab === "review" ? (
            <div className="space-y-4">
              <p className="text-sm leading-relaxed text-stone-500">
                A conference-style review with scores — harsher and more committal than
                the Critique tab, which only lists concerns. Useful for pressure-testing
                a paper, or your own draft.
              </p>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => runReview(Boolean(review))}
                  disabled={reviewBusy}
                  className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
                >
                  {review ? "Write a fresh review" : "Review this paper"}
                </button>
                {reviewBusy ? (
                  <span className="flex items-center gap-2 text-sm text-stone-500">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />
                    Reviewing…
                  </span>
                ) : null}
                {review && !reviewBusy ? (
                  <span className="text-xs text-stone-400">
                    {review.from_fulltext ? "from the full text" : "from the abstract only"}
                    {review.created_at ? ` · ${review.created_at.slice(0, 10)}` : ""}
                  </span>
                ) : null}
              </div>

              {review ? (
                <>
                  <div className="rounded-xl border border-stone-200 bg-white p-5">
                    <div className="flex flex-wrap items-center gap-3">
                      <span
                        className={`rounded-full border px-3 py-1 text-sm font-semibold capitalize ${
                          RECOMMENDATION_STYLE[review.recommendation] ??
                          "border-stone-200 bg-stone-50 text-stone-700"
                        }`}
                      >
                        {review.recommendation}
                      </span>
                      <span className="text-xs text-stone-400">
                        reviewer confidence {review.confidence}/5
                      </span>
                    </div>
                    <div className="mt-4 space-y-1.5">
                      <ScoreBar label="Soundness" score={review.soundness} />
                      <ScoreBar label="Contribution" score={review.contribution} />
                      <ScoreBar label="Presentation" score={review.presentation} />
                    </div>
                    <p className="mt-4 border-t border-stone-100 pt-3 text-sm leading-relaxed text-stone-700">
                      <RichText text={review.summary} terms={terms} />
                    </p>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
                      <p className="text-sm font-semibold text-emerald-900">Strengths</p>
                      <ul className="mt-2 space-y-1.5">
                        {review.strengths.map((item, index) => (
                          <li
                            key={index}
                            className="flex gap-2 text-sm leading-relaxed text-emerald-900/90"
                          >
                            <span className="text-emerald-400">+</span>
                            <span>
                              <RichText text={item} terms={terms} />
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="rounded-xl border border-red-200 bg-red-50/50 p-4">
                      <p className="text-sm font-semibold text-red-900">Weaknesses</p>
                      <ul className="mt-2 space-y-1.5">
                        {review.weaknesses.map((item, index) => (
                          <li
                            key={index}
                            className="flex gap-2 text-sm leading-relaxed text-red-900/90"
                          >
                            <span className="text-red-400">−</span>
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
                      Questions for the authors
                    </p>
                    <ol className="mt-2 space-y-2">
                      {review.questions.map((item, index) => (
                        <li
                          key={index}
                          className="flex gap-3 text-sm leading-relaxed text-stone-600"
                        >
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
                </>
              ) : null}
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
                    {entry.anchor ? (
                      <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs italic leading-relaxed text-amber-800">
                        “{entry.anchor.length > 180
                          ? `${entry.anchor.slice(0, 180)}…`
                          : entry.anchor}
                        ”
                      </p>
                    ) : null}
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

              {pendingAnchor ? (
                <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
                  <span className="min-w-0 flex-1 italic">
                    “{pendingAnchor.length > 220 ? `${pendingAnchor.slice(0, 220)}…` : pendingAnchor}”
                  </span>
                  <button
                    type="button"
                    onClick={() => setPendingAnchor(null)}
                    title="Ask without this highlighted passage"
                    className="shrink-0 text-amber-500 hover:text-amber-700"
                  >
                    ✕
                  </button>
                </div>
              ) : null}

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
