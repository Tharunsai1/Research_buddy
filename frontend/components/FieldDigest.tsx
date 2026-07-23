"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Digest, Paper } from "@/lib/types";

interface Props {
  searchId: string;
  papers: Record<string, Paper>;
  onSelect: (paperId: string) => void;
  onUpdated: () => void;
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

export default function FieldDigest({ searchId, papers, onSelect, onUpdated }: Props) {
  const [digests, setDigests] = useState<Digest[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .digests(searchId)
      .then((result) => setDigests(result.digests))
      .catch(() => setDigests([]));
  }, [searchId]);

  useEffect(load, [load]);

  const check = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.runDigest(searchId);
      load();
      onUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const latest = digests?.[0];
  const older = digests?.slice(1) ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={check}
          disabled={busy}
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
        >
          {latest ? "Check for new papers" : "Check this field for updates"}
        </button>
        {busy ? (
          <span className="flex items-center gap-2 text-sm text-stone-500">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />
            Searching arXiv and reading what&apos;s new…
          </span>
        ) : null}
        {latest && !busy ? (
          <span className="text-xs text-stone-400">
            last checked {timeAgo(latest.created_at)}
          </span>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
          {error}
        </div>
      ) : null}

      {!latest && !busy ? (
        <p className="text-sm leading-relaxed text-stone-500">
          Re-runs this search against arXiv, keeps only papers your library doesn&apos;t
          have, and tells you what actually changed — including anything that
          challenges the consensus you already mapped.
        </p>
      ) : null}

      {latest ? (
        <div className="rounded-xl border border-stone-200 bg-white p-5">
          <p className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
            {latest.created_at.slice(0, 10)} · {latest.checked_count} candidates checked ·{" "}
            {latest.new_paper_ids.length} new
          </p>
          <h3 className="mt-1 text-base font-semibold text-stone-900">{latest.headline}</h3>
          <p className="mt-2 text-sm leading-relaxed text-stone-600">{latest.summary}</p>

          {latest.highlights.length > 0 ? (
            <ul className="mt-4 space-y-2.5">
              {latest.highlights.map((highlight) => {
                const paper = papers[highlight.paper_id];
                return (
                  <li
                    key={highlight.paper_id}
                    className="rounded-xl border border-stone-200 bg-stone-50/60 p-3.5"
                  >
                    <div className="flex items-start gap-2">
                      {highlight.challenges_consensus ? (
                        <span
                          title="Challenges an existing consensus point"
                          className="mt-0.5 shrink-0 rounded-full border border-amber-300 bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-900"
                        >
                          ⚠ challenges consensus
                        </span>
                      ) : null}
                    </div>
                    <button
                      onClick={() => onSelect(highlight.paper_id)}
                      className="mt-1 text-left text-sm font-medium leading-snug text-stone-900 underline-offset-2 hover:underline"
                    >
                      {paper?.title ?? highlight.paper_id}
                    </button>
                    <p className="mt-1 text-sm leading-relaxed text-stone-600">
                      {highlight.why_it_matters}
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-stone-500">
                      {highlight.relation}
                    </p>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}

      {older.length > 0 ? (
        <details className="rounded-xl border border-stone-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-medium text-stone-700">
            Earlier checks ({older.length})
          </summary>
          <ul className="mt-3 space-y-2">
            {older.map((digest, index) => (
              <li key={index} className="border-l-2 border-stone-200 pl-3">
                <p className="text-xs text-stone-400">
                  {digest.created_at.slice(0, 10)} · {digest.new_paper_ids.length} new
                </p>
                <p className="text-sm text-stone-700">{digest.headline}</p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
