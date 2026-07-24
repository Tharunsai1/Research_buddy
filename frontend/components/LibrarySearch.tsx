"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { LibrarySearchHit } from "@/lib/types";

interface Props {
  onSelectPaper: (id: string) => void;
}

export default function LibrarySearch({ onSelectPaper }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LibrarySearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    const q = query.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api.librarySearch(q);
      setResults(data.results);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResults(null);
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    setQuery("");
    setResults(null);
    setError(null);
  };

  return (
    <div className="space-y-3 rounded-xl border border-stone-200 bg-white p-4">
      <div className="flex items-center gap-2">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") run();
          }}
          placeholder="Search your whole library — e.g. KV-cache compression"
          className="flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none"
        />
        <button
          onClick={run}
          disabled={busy || !query.trim()}
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
        >
          {busy ? "Searching…" : "Search"}
        </button>
        {results !== null ? (
          <button
            onClick={clear}
            className="rounded-lg border border-stone-200 px-3 py-2 text-sm text-stone-500 transition hover:border-stone-400"
          >
            Clear
          </button>
        ) : null}
      </div>

      <p className="text-xs text-stone-400">
        Ranks every paper you have collected by meaning, not keyword — finds a paper even if
        it never uses the exact words you searched for.
      </p>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {results !== null && !error ? (
        results.length === 0 ? (
          <p className="text-sm text-stone-500">No matches in your library yet.</p>
        ) : (
          <ol className="space-y-2">
            {results.map((hit, index) => (
              <li key={hit.paper_id}>
                <button
                  onClick={() => onSelectPaper(hit.paper_id)}
                  className="flex w-full items-start gap-3 rounded-lg border border-stone-200 px-3 py-2.5 text-left transition hover:border-stone-400 hover:bg-stone-50"
                >
                  <span className="mt-0.5 shrink-0 font-mono text-[11px] text-stone-400">
                    #{index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-stone-900">
                      {hit.paper.title}
                    </span>
                    <span className="block truncate text-xs text-stone-400">
                      {hit.paper.authors.slice(0, 3).join(", ")}
                      {hit.paper.authors.length > 3 ? " et al." : ""} ·{" "}
                      {hit.paper.published.slice(0, 4)}
                    </span>
                  </span>
                  <span className="shrink-0 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[10px] font-medium text-stone-500">
                    {Math.max(0, Math.round(hit.score * 100))}% match
                  </span>
                </button>
              </li>
            ))}
          </ol>
        )
      ) : null}
    </div>
  );
}
