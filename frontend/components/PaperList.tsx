"use client";

import type { Extraction, Paper } from "@/lib/types";

interface Props {
  paperIds: string[];
  papers: Record<string, Paper>;
  extractions: Record<string, Extraction>;
  read: string[];
  deepRead?: string[];
  onSelect: (paperId: string) => void;
  onToggleRead: (paperId: string, read: boolean) => void;
}

export default function PaperList({
  paperIds,
  papers,
  extractions,
  read,
  deepRead = [],
  onSelect,
  onToggleRead,
}: Props) {
  const readSet = new Set(read);
  const deepSet = new Set(deepRead);
  return (
    <ol className="space-y-3">
      {paperIds.map((id, index) => {
        const paper = papers[id];
        const extraction = extractions[id];
        if (!paper) return null;
        const isRead = readSet.has(id);
        return (
          <li
            key={id}
            className="group rounded-xl border border-stone-200 bg-white p-4 transition hover:border-stone-300 hover:shadow-sm"
          >
            <div className="flex items-start gap-4">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-stone-900 font-mono text-[11px] font-semibold text-white">
                #{index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <button
                  onClick={() => onSelect(id)}
                  className="text-left text-[15px] font-medium leading-snug text-stone-900 underline-offset-2 hover:underline"
                >
                  {paper.title}
                </button>
                <p className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-stone-400">
                  <span className="truncate">
                    {paper.authors.slice(0, 4).join(", ")}
                    {paper.authors.length > 4 ? " et al." : ""} · {paper.published.slice(0, 4)}
                    {paper.relevance != null
                      ? ` · ${Math.round(paper.relevance * 100)}% match`
                      : ""}
                  </span>
                  {deepSet.has(id) ? (
                    <span className="shrink-0 rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
                      full text
                    </span>
                  ) : null}
                </p>
                {extraction ? (
                  <p className="mt-1.5 text-sm leading-relaxed text-stone-600">
                    {extraction.tldr}
                  </p>
                ) : null}
              </div>
              <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-stone-400">
                <input
                  type="checkbox"
                  checked={isRead}
                  onChange={(event) => onToggleRead(id, event.target.checked)}
                  className="h-4 w-4 accent-emerald-600"
                />
                read
              </label>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
