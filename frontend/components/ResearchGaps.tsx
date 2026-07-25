"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { GapReport } from "@/lib/types";

interface Props {
  onSelect: (paperId: string) => void;
}

export default function ResearchGaps({ onSelect }: Props) {
  const [report, setReport] = useState<GapReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .gaps()
      .then((result) => setReport(result.report))
      .catch(() => setReport(null));
  }, []);

  useEffect(load, [load]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.buildGaps();
      setReport(result.report);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-stone-500">
        Looks across your whole library for things nobody has tried yet — where one
        paper&apos;s method could be applied to another paper&apos;s setting. Each idea comes
        with a concrete first experiment.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={run}
          disabled={busy}
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
        >
          {report ? "Look again" : "Find research gaps"}
        </button>
        {busy ? (
          <span className="flex items-center gap-2 text-sm text-stone-500">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />
            Cross-referencing your papers…
          </span>
        ) : null}
        {report && !busy ? (
          <span className="text-xs text-stone-400">
            across {report.paper_count} most recent papers · {report.created_at.slice(0, 10)}
          </span>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
          {error}
        </div>
      ) : null}

      {report ? (
        <ul className="space-y-3">
          {report.gaps.map((gap, index) => (
            <li key={index} className="rounded-xl border border-stone-200 bg-white p-4">
              <div className="flex items-baseline gap-2.5">
                <span className="font-mono text-[11px] text-stone-300">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <p className="text-sm font-semibold leading-snug text-stone-900">
                  {gap.title}
                </p>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-stone-600">{gap.description}</p>
              <p className="mt-2 text-sm leading-relaxed text-stone-500">
                <span className="font-medium text-stone-600">Why it matters: </span>
                {gap.why_it_matters}
              </p>
              <p className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50/70 px-3 py-2 text-sm leading-relaxed text-emerald-900">
                <span className="font-medium">First step: </span>
                {gap.first_step}
              </p>
              {gap.paper_ids.length > 0 ? (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {gap.paper_ids.map((paperId, i) => (
                    <button
                      key={paperId}
                      onClick={() => onSelect(paperId)}
                      className="max-w-full truncate rounded-full border border-stone-200 bg-stone-50 px-2.5 py-0.5 text-xs text-stone-600 transition hover:border-stone-400"
                    >
                      {gap.paper_titles[i] ?? paperId}
                    </button>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
