"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Paper, ResultRow } from "@/lib/types";

interface Props {
  paperIds: string[];
  papers: Record<string, Paper>;
  onSelect: (paperId: string) => void;
}

type SortKey = "dataset" | "metric" | "value" | "system";

/** Server rejects more than this per request; keep the button honest about
 *  how many it will actually process. */
const MAX_PAPERS = 30;

/** Numeric prefix of a printed value ("87.3%" -> 87.3), or null if there is
 *  none. Sorting has to fall back to text for values like "3.5 days". */
function numericValue(value: string): number | null {
  const match = value.match(/-?\d+(?:[.,]\d+)?/);
  if (!match) return null;
  const parsed = Number.parseFloat(match[0].replace(",", "."));
  return Number.isFinite(parsed) ? parsed : null;
}

export default function ResultsBoard({ paperIds, papers, onSelect }: Props) {
  const [rows, setRows] = useState<ResultRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("dataset");
  const [descending, setDescending] = useState(false);
  const [datasetFilter, setDatasetFilter] = useState("");

  const load = useCallback(() => {
    api
      .results()
      .then((result) => setRows(result.rows))
      .catch(() => setRows([]));
  }, []);

  useEffect(load, [load]);

  const extract = async () => {
    setBusy(true);
    setError(null);
    try {
      // Cached per paper server-side, so this only spends calls on papers
      // that have never been extracted.
      await api.buildResults(paperIds.slice(0, MAX_PAPERS));
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const datasets = useMemo(() => {
    const names = new Set(rows.map((row) => row.dataset).filter(Boolean));
    return Array.from(names).sort();
  }, [rows]);

  const visible = useMemo(() => {
    const filtered = datasetFilter
      ? rows.filter((row) => row.dataset === datasetFilter)
      : rows;
    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "value") {
        const av = numericValue(a.value);
        const bv = numericValue(b.value);
        if (av !== null && bv !== null) return av - bv;
        if (av !== null) return -1;
        if (bv !== null) return 1;
        return a.value.localeCompare(b.value);
      }
      return String(a[sortKey]).localeCompare(String(b[sortKey]));
    });
    return descending ? sorted.reverse() : sorted;
  }, [rows, datasetFilter, sortKey, descending]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setDescending((value) => !value);
    } else {
      setSortKey(key);
      setDescending(key === "value");
    }
  };

  const headerClass = (key: SortKey) =>
    `cursor-pointer select-none px-2 py-1.5 text-left font-medium transition hover:text-stone-900 ${
      sortKey === key ? "text-stone-900" : "text-stone-500"
    }`;

  const arrow = (key: SortKey) =>
    sortKey === key ? (descending ? " ↓" : " ↑") : "";

  return (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-stone-500">
        Every number these papers report, in one table — including the baselines they
        compare against, so you can spot two papers claiming different values for the
        same baseline. Numbers are copied as printed, never recomputed.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={extract}
          disabled={busy || paperIds.length === 0}
          className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
        >
          {rows.length > 0
            ? "Extract any missing papers"
            : `Extract results for ${Math.min(paperIds.length, MAX_PAPERS)} papers`}
        </button>
        {busy ? (
          <span className="flex items-center gap-2 text-sm text-stone-500">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />
            Reading each paper for numbers…
          </span>
        ) : null}
        {rows.length > 0 && !busy ? (
          <span className="text-xs text-stone-400">
            {rows.length} rows · {new Set(rows.map((r) => r.paper_id)).size} papers
          </span>
        ) : null}
        {datasets.length > 1 ? (
          <select
            value={datasetFilter}
            onChange={(event) => setDatasetFilter(event.target.value)}
            className="ml-auto rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-xs text-stone-600"
          >
            <option value="">All datasets ({datasets.length})</option>
            {datasets.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
          {error}
        </div>
      ) : null}

      {visible.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-stone-200 bg-white">
          <table className="w-full min-w-[42rem] text-sm">
            <thead className="border-b border-stone-200 bg-stone-50/60 text-xs uppercase tracking-wide">
              <tr>
                <th className={headerClass("system")} onClick={() => toggleSort("system")}>
                  System{arrow("system")}
                </th>
                <th className={headerClass("dataset")} onClick={() => toggleSort("dataset")}>
                  Dataset{arrow("dataset")}
                </th>
                <th className={headerClass("metric")} onClick={() => toggleSort("metric")}>
                  Metric{arrow("metric")}
                </th>
                <th className={headerClass("value")} onClick={() => toggleSort("value")}>
                  Value{arrow("value")}
                </th>
                <th className="px-2 py-1.5 text-left font-medium text-stone-500">Paper</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row, index) => (
                <tr key={index} className="border-b border-stone-100 last:border-0">
                  <td className="px-2 py-1.5 text-stone-800">
                    {row.system}
                    {row.is_this_paper ? (
                      <span
                        title="This paper's own proposed method"
                        className="ml-1.5 rounded bg-emerald-50 px-1 py-0.5 text-[10px] font-medium text-emerald-700"
                      >
                        theirs
                      </span>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 text-stone-600">
                    {row.dataset}
                    {row.split ? (
                      <span className="ml-1 text-xs text-stone-400">({row.split})</span>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 text-stone-600">{row.metric}</td>
                  <td className="px-2 py-1.5 font-mono text-stone-900">{row.value}</td>
                  <td className="max-w-[14rem] px-2 py-1.5">
                    <button
                      onClick={() => onSelect(row.paper_id)}
                      className="truncate text-left text-xs text-stone-500 underline-offset-2 hover:text-stone-800 hover:underline"
                    >
                      {papers[row.paper_id]?.title ?? row.paper_id}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
