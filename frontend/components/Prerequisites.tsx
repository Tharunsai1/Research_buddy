"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Paper, Prerequisite } from "@/lib/types";

interface Props {
  papers: Record<string, Paper>;
  enrichedCount: number;
  /** Search to fold the paper into, so it shows up where the reader is looking. */
  searchId?: string | null;
  onAdded: () => void;
}

export default function Prerequisites({
  papers,
  enrichedCount,
  searchId,
  onAdded,
}: Props) {
  const [items, setItems] = useState<Prerequisite[] | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(() => {
    api
      .prerequisites(12, searchId)
      .then((result) => setItems(result.prerequisites))
      .catch(() => setItems([]));
  }, [searchId]);

  useEffect(() => {
    if (enrichedCount > 0) load();
  }, [enrichedCount, load]);

  const add = async (prerequisite: Prerequisite) => {
    setAdding(prerequisite.arxiv_id);
    setError(null);
    try {
      const result = await api.addPaper(prerequisite.arxiv_id, searchId);
      // A refused add still returns 200 with a reason. Dropping the row here
      // without saying why is what made this look like a dead button.
      if (!result.added) {
        setError(result.reason ?? "That paper could not be added.");
        return;
      }
      setItems((current) =>
        (current ?? []).filter((p) => p.arxiv_id !== prerequisite.arxiv_id),
      );
      onAdded();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAdding(null);
    }
  };

  if (enrichedCount === 0 || items === null) return null;
  if (items.length === 0) return null;

  const shown = expanded ? items : items.slice(0, 5);

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-stone-500">
        Papers the papers in this search cite repeatedly but your library
        doesn&apos;t contain — the foundations this field is built on. Adding one
        pulls it into this search and your map.
      </p>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {adding ? (
        <div className="rounded-xl border border-stone-200 bg-stone-50 px-4 py-2.5 text-sm text-stone-600">
          Fetching the paper and summarizing it — this takes a minute or two on
          the hosted model. It joins your map when it finishes.
        </div>
      ) : null}

      <ol className="space-y-2">
        {shown.map((item) => (
          <li
            key={item.arxiv_id}
            className="flex items-start gap-4 rounded-xl border border-stone-200 bg-white p-4"
          >
            <div className="flex w-14 shrink-0 flex-col items-center rounded-lg bg-stone-900 px-2 py-1.5">
              <span className="font-mono text-sm font-semibold text-white">
                {item.cited_by.length}×
              </span>
              <span className="text-[9px] uppercase tracking-wide text-stone-400">cited</span>
            </div>
            <div className="min-w-0 flex-1">
              <a
                href={`https://arxiv.org/abs/${item.arxiv_id}`}
                target="_blank"
                rel="noreferrer"
                className="text-[15px] font-medium leading-snug text-stone-900 underline-offset-2 hover:underline"
              >
                {item.title}
              </a>
              <p className="mt-0.5 text-xs text-stone-400">
                {item.year ?? "—"} · {item.citation_count.toLocaleString()} citations
                worldwide · cited by{" "}
                {item.cited_by
                  .slice(0, 2)
                  .map((id) => papers[id]?.title?.slice(0, 32) ?? id)
                  .join("; ")}
                {item.cited_by.length > 2 ? ` +${item.cited_by.length - 2} more` : ""}
              </p>
            </div>
            <button
              onClick={() => add(item)}
              disabled={adding !== null}
              className="shrink-0 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:border-stone-400 disabled:opacity-40"
            >
              {adding === item.arxiv_id ? "Adding…" : "+ Add"}
            </button>
          </li>
        ))}
      </ol>

      {items.length > 5 ? (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-stone-500 underline underline-offset-2 hover:text-stone-800"
        >
          {expanded ? "Show fewer" : `Show ${items.length - 5} more`}
        </button>
      ) : null}
    </div>
  );
}
