"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { ArtifactsResponse } from "@/lib/types";

interface Props {
  onSelect: (paperId: string) => void;
}

export default function CodeAvailability({ onSelect }: Props) {
  const [data, setData] = useState<ArtifactsResponse | null>(null);
  const [onlyWithCode, setOnlyWithCode] = useState(true);

  useEffect(() => {
    api
      .artifacts()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const rows = useMemo(() => {
    if (!data) return [];
    return onlyWithCode ? data.papers.filter((p) => p.has_code) : data.papers;
  }, [data, onlyWithCode]);

  if (!data) return null;

  const withCode = data.papers.filter((p) => p.has_code).length;

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-stone-500">
        Which papers actually released code, and which report the details you need to
        reproduce them. Found by scanning the papers&apos; own text — so this shows what a
        paper <em>mentions</em>, not a guarantee the link still works.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-stone-600">
          <span className="font-semibold text-stone-900">{withCode}</span> of{" "}
          {data.papers.length} papers link code
        </span>
        <button
          onClick={() => setOnlyWithCode((value) => !value)}
          className="ml-auto rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-600 transition hover:border-stone-400"
        >
          {onlyWithCode ? "Show all papers" : "Only papers with code"}
        </button>
      </div>

      <ul className="space-y-2">
        {rows.slice(0, 60).map((paper) => (
          <li
            key={paper.paper_id}
            className="rounded-xl border border-stone-200 bg-white p-3.5"
          >
            <div className="flex items-start justify-between gap-3">
              <button
                onClick={() => onSelect(paper.paper_id)}
                className="text-left text-sm font-medium leading-snug text-stone-900 underline-offset-2 hover:underline"
              >
                {paper.title}
              </button>
              <span
                title={
                  paper.scanned_full_text
                    ? "Scanned the full text"
                    : "Only the abstract was available to scan — absence of a signal means little here"
                }
                className="shrink-0 font-mono text-[10px] uppercase tracking-wide text-stone-400"
              >
                {paper.scanned_full_text ? "full text" : "abstract only"}
              </span>
            </div>

            {paper.repos.length > 0 ? (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {paper.repos.slice(0, 3).map((repo) => (
                  <a
                    key={repo}
                    href={repo}
                    target="_blank"
                    rel="noreferrer"
                    className="max-w-full truncate rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-0.5 font-mono text-xs text-emerald-800 transition hover:border-emerald-400"
                  >
                    ↗ {repo.replace(/^https:\/\//, "")}
                  </a>
                ))}
              </div>
            ) : (
              <p className="mt-1.5 text-xs text-stone-400">No code link found</p>
            )}

            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(data.labels).map(([key, label]) => (
                <span
                  key={key}
                  className={
                    paper.signals[key]
                      ? "rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] text-stone-600"
                      : "rounded-full border border-dashed border-stone-200 px-2 py-0.5 text-[11px] text-stone-300"
                  }
                >
                  {paper.signals[key] ? "✓" : "–"} {label}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ul>
      {rows.length > 60 ? (
        <p className="text-xs text-stone-400">Showing the first 60 of {rows.length}.</p>
      ) : null}
    </div>
  );
}
