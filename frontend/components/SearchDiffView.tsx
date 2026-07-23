"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { SearchDiff, SearchMeta } from "@/lib/types";

interface Props {
  searches: SearchMeta[];
  onSelectPaper: (id: string) => void;
}

function DiffList({
  title,
  added,
  removed,
  addedTone = "emerald",
}: {
  title: string;
  added: string[];
  removed: string[];
  addedTone?: "emerald" | "amber";
}) {
  if (added.length === 0 && removed.length === 0) return null;
  const addedColor =
    addedTone === "emerald"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : "border-amber-200 bg-amber-50 text-amber-900";
  return (
    <div className="rounded-xl border border-stone-200 bg-white p-4">
      <p className="text-sm font-semibold text-stone-900">{title}</p>
      <div className="mt-2 space-y-1.5">
        {added.map((item, index) => (
          <p key={`+${index}`} className={`rounded-lg border px-3 py-1.5 text-sm ${addedColor}`}>
            <span className="mr-1.5 font-mono">+</span>
            {item}
          </p>
        ))}
        {removed.map((item, index) => (
          <p
            key={`-${index}`}
            className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-1.5 text-sm text-stone-500 line-through decoration-stone-300"
          >
            <span className="mr-1.5 font-mono no-underline">−</span>
            {item}
          </p>
        ))}
      </div>
    </div>
  );
}

export default function SearchDiffView({ searches, onSelectPaper }: Props) {
  const [aId, setAId] = useState(searches[1]?.id ?? searches[0]?.id ?? "");
  const [bId, setBId] = useState(searches[0]?.id ?? "");
  const [diff, setDiff] = useState<SearchDiff | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (searches.length < 2) return null;

  const compare = async () => {
    if (!aId || !bId || aId === bId) {
      setError("Pick two different searches to compare.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setDiff(await api.searchDiff(aId, bId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const label = (s: SearchMeta) => `${s.title} · ${s.created_at.slice(0, 10)}`;

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-stone-500">
        Compare two of your own past searches to see what actually changed — new
        papers, new or dropped themes, tensions, and open problems — instead of
        eyeballing two overviews side by side.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={aId}
          onChange={(event) => setAId(event.target.value)}
          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700"
        >
          {searches.map((s) => (
            <option key={s.id} value={s.id}>
              {label(s)}
            </option>
          ))}
        </select>
        <span aria-hidden className="text-stone-400">
          →
        </span>
        <select
          value={bId}
          onChange={(event) => setBId(event.target.value)}
          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700"
        >
          {searches.map((s) => (
            <option key={s.id} value={s.id}>
              {label(s)}
            </option>
          ))}
        </select>
        <button
          onClick={compare}
          disabled={busy}
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
        >
          {busy ? "Comparing…" : "Compare"}
        </button>
      </div>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {diff ? (
        <div className="space-y-3">
          <p className="text-sm text-stone-600">
            <span className="font-medium text-stone-900">{diff.b.paper_count} papers</span> now
            vs <span className="font-medium text-stone-900">{diff.a.paper_count}</span> then ·{" "}
            {diff.new_papers.length} new · {diff.shared_paper_count} shared
            {diff.dropped_papers.length > 0 ? ` · ${diff.dropped_papers.length} dropped` : ""}
          </p>

          {diff.new_papers.length > 0 || diff.dropped_papers.length > 0 ? (
            <div className="rounded-xl border border-stone-200 bg-white p-4">
              <p className="text-sm font-semibold text-stone-900">Papers</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {diff.new_papers.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => onSelectPaper(p.id)}
                    title={p.title}
                    className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs text-emerald-800 transition hover:border-emerald-400"
                  >
                    + {p.title.slice(0, 40)}
                    {p.title.length > 40 ? "…" : ""}
                  </button>
                ))}
                {diff.dropped_papers.map((p) => (
                  <span
                    key={p.id}
                    title={p.title}
                    className="rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-xs text-stone-500 line-through decoration-stone-300"
                  >
                    {p.title.slice(0, 40)}
                    {p.title.length > 40 ? "…" : ""}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          <DiffList title="Themes" added={diff.clusters_added} removed={diff.clusters_removed} />
          <DiffList
            title="Consensus"
            added={diff.consensus_added}
            removed={diff.consensus_removed}
          />
          <DiffList
            title="Tensions"
            added={diff.tensions_added}
            removed={diff.tensions_removed}
            addedTone="amber"
          />
          <DiffList
            title="Open problems"
            added={diff.open_problems_added}
            removed={diff.open_problems_removed}
          />

          {diff.clusters_added.length === 0 &&
          diff.clusters_removed.length === 0 &&
          diff.consensus_added.length === 0 &&
          diff.consensus_removed.length === 0 &&
          diff.tensions_added.length === 0 &&
          diff.tensions_removed.length === 0 &&
          diff.open_problems_added.length === 0 &&
          diff.open_problems_removed.length === 0 &&
          diff.new_papers.length === 0 &&
          diff.dropped_papers.length === 0 ? (
            <p className="text-sm text-stone-500">
              No difference between these two searches — same papers, same themes.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
