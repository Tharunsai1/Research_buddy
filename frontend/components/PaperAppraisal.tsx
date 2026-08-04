"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Appraisal, AppraisalProgress, Paper } from "@/lib/types";

/** Reading the search's papers one at a time against a reviewer's checklist.
 *
 *  The queue is the point: appraising a paper only pays off when you keep
 *  going, so finishing one moves straight to the next rather than returning
 *  to a list and asking the reader to choose again. Progress lives on the
 *  backend (which appraisal files exist), not in component state, so closing
 *  the tab mid-way loses nothing.
 */
export default function PaperAppraisal({
  searchId,
  paperIds,
  papers,
  onSelectPaper,
}: {
  searchId: string;
  paperIds: string[];
  papers: Record<string, Paper>;
  onSelectPaper?: (paperId: string) => void;
}) {
  const [progress, setProgress] = useState<AppraisalProgress | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [appraisal, setAppraisal] = useState<Appraisal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = useMemo(
    () => new Set(progress?.appraised ?? []),
    [progress],
  );

  const refreshProgress = useCallback(async () => {
    try {
      setProgress(await api.appraisalProgress(searchId));
    } catch {
      /* progress is advisory; a failure here must not block appraising */
    }
  }, [searchId]);

  // Inlined rather than calling refreshProgress(): the state update has to
  // land in a promise continuation the effect can still cancel, so a search
  // switched mid-flight does not write the previous search's progress.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const latest = await api.appraisalProgress(searchId);
        if (!cancelled) setProgress(latest);
      } catch {
        /* progress is advisory; a failure here must not block appraising */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchId]);

  // Opening a paper shows its saved appraisal if there is one, and otherwise
  // leaves the pane empty with the run button — never auto-spends an LLM call.
  const open = useCallback(async (paperId: string) => {
    setCurrent(paperId);
    setAppraisal(null);
    setError(null);
    try {
      setAppraisal(await api.appraisal(paperId));
    } catch {
      /* 404 simply means "not appraised yet" */
    }
  }, []);

  const run = useCallback(
    async (paperId: string, refresh = false) => {
      setBusy(true);
      setError(null);
      try {
        setAppraisal(await api.runAppraisal(paperId, refresh));
        await refreshProgress();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Appraisal failed.");
      } finally {
        setBusy(false);
      }
    },
    [refreshProgress],
  );

  /** The next paper in the search's own order that has no appraisal yet. */
  const nextUp = useMemo(
    () => paperIds.find((id) => !done.has(id) && id !== current) ?? null,
    [paperIds, done, current],
  );

  const total = paperIds.length;
  const finished = paperIds.filter((id) => done.has(id)).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
        <div className="flex-1 min-w-[12rem]">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-sm font-medium text-stone-700">
              {finished} of {total} appraised
            </p>
            {finished === total && total > 0 ? (
              <span className="text-xs font-medium text-emerald-700">all done</span>
            ) : null}
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-stone-150">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: total ? `${(finished / total) * 100}%` : "0%" }}
            />
          </div>
        </div>
        {nextUp && !busy ? (
          <button
            type="button"
            onClick={() => open(nextUp)}
            className="rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-stone-700"
          >
            {finished === 0 ? "Start reading" : "Next paper"}
          </button>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {paperIds.map((id, index) => {
          const paper = papers[id];
          const isDone = done.has(id);
          const isCurrent = id === current;
          return (
            <button
              key={id}
              type="button"
              onClick={() => open(id)}
              title={paper?.title ?? id}
              className={`rounded-lg border px-2.5 py-1 text-xs transition ${
                isCurrent
                  ? "border-stone-900 bg-stone-900 text-white"
                  : isDone
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800 hover:border-emerald-300"
                    : "border-stone-200 bg-white text-stone-500 hover:border-stone-300"
              }`}
            >
              {isDone ? "✓ " : ""}
              {index + 1}
            </button>
          );
        })}
      </div>

      {current ? (
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs uppercase tracking-wide text-stone-400">
                Paper {paperIds.indexOf(current) + 1} of {total}
              </p>
              <button
                type="button"
                onClick={() => onSelectPaper?.(current)}
                className="mt-0.5 text-left text-sm font-semibold leading-snug text-stone-900 hover:underline"
              >
                {papers[current]?.title ?? current}
              </button>
            </div>
            <div className="flex shrink-0 gap-2">
              {appraisal ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run(current, true)}
                  className="rounded-lg border border-stone-200 px-3 py-1.5 text-sm text-stone-600 transition hover:bg-stone-100 disabled:opacity-50"
                >
                  Re-run
                </button>
              ) : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => run(current)}
                  className="rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-50"
                >
                  {busy ? "Reading…" : "Appraise this paper"}
                </button>
              )}
            </div>
          </div>

          {busy ? (
            <p className="mt-3 text-sm text-stone-500">
              Working through the checklist — five sections, about a minute.
            </p>
          ) : null}

          {error ? (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          ) : null}

          {appraisal ? (
            <div className="mt-4 space-y-4">
              {/* An abstract-only appraisal answers the Overview questions and
                  little else. Saying so is the difference between a thin
                  appraisal and a misleading one. */}
              {appraisal.source === "abstract" ? (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  From the abstract only — this paper has not been deep-read, so
                  most Data and Performance questions could not be answered.
                  Open it and use <em>Read full paper</em> first for a fuller
                  appraisal.
                </p>
              ) : null}

              {appraisal.sections.map((section) => (
                <div key={section.key}>
                  <p className="text-sm font-semibold text-stone-900">
                    {section.title}
                  </p>
                  <div className="mt-1.5 space-y-2.5">
                    {section.answers.map((a, i) => (
                      <div key={i} className="border-l-2 border-stone-150 pl-3">
                        <p className="text-sm font-medium text-stone-700">
                          {a.question}
                        </p>
                        <p className="mt-0.5 text-sm leading-relaxed text-stone-600">
                          {a.answer}
                        </p>
                        {/* Only two of these are criticisms. A question that
                            does not apply to this kind of paper says nothing
                            about the paper, so it stays grey. */}
                        {a.status !== "answered" ? (
                          <span
                            className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${
                              a.status === "not_reported"
                                ? "bg-red-50 text-red-700"
                                : a.status === "partial"
                                  ? "bg-amber-50 text-amber-800"
                                  : "bg-stone-100 text-stone-500"
                            }`}
                          >
                            {a.status === "not_reported"
                              ? "not reported by the paper"
                              : a.status === "partial"
                                ? "partially answered"
                                : "not applicable to this kind of paper"}
                          </span>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ))}

              <div className="rounded-lg bg-stone-50 p-3">
                <p className="text-sm font-semibold text-stone-900">Conclusions</p>
                <p className="mt-1 text-sm leading-relaxed text-stone-700">
                  {appraisal.conclusion}
                </p>
                <p
                  className={`mt-2 inline-block rounded px-2 py-0.5 text-xs font-medium ${
                    appraisal.justified
                      ? "bg-emerald-50 text-emerald-800"
                      : "bg-red-50 text-red-700"
                  }`}
                >
                  {appraisal.justified
                    ? "Supported by the evidence shown"
                    : "Not fully supported by the evidence shown"}
                </p>
                <p className="mt-2 text-sm leading-relaxed text-stone-600">
                  {appraisal.justification}
                </p>
                {appraisal.biggest_gap ? (
                  <p className="mt-2 text-sm leading-relaxed text-stone-600">
                    <span className="font-medium text-stone-800">Biggest gap: </span>
                    {appraisal.biggest_gap}
                  </p>
                ) : null}
                {appraisal.next_steps.length ? (
                  <>
                    <p className="mt-3 text-sm font-medium text-stone-800">
                      What you would want next
                    </p>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-stone-600">
                      {appraisal.next_steps.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </div>

              {nextUp ? (
                <button
                  type="button"
                  onClick={() => open(nextUp)}
                  className="w-full rounded-lg border border-stone-200 px-3 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
                >
                  Next paper → {papers[nextUp]?.title ?? nextUp}
                </button>
              ) : (
                <p className="text-center text-sm text-stone-500">
                  Every paper in this search has been appraised.
                </p>
              )}
            </div>
          ) : null}
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-stone-200 px-4 py-6 text-center text-sm text-stone-500">
          Work through this search&rsquo;s papers one at a time against a
          reviewer&rsquo;s checklist — what they did, their data, method,
          results, and whether the conclusion holds up.
        </p>
      )}
    </div>
  );
}
