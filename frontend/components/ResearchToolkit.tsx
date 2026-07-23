"use client";

import { useMemo, useState } from "react";
import { api, downloadFile } from "@/lib/api";
import type { Comparison, MatrixRow, Paper, RelatedWork } from "@/lib/types";
import RichText from "./RichText";

type Tool = "matrix" | "related" | "compare";

const TOOLS: { key: Tool; label: string; blurb: string }[] = [
  { key: "matrix", label: "Literature matrix", blurb: "The survey table, filled in for you." },
  { key: "related", label: "Related work", blurb: "A drafted section with \\cite{} keys + .bib." },
  { key: "compare", label: "Compare two", blurb: "Side-by-side on problem, method, results." },
];

interface Props {
  paperIds: string[];
  papers: Record<string, Paper>;
  topic: string;
}

function Spinner({ label }: { label: string }) {
  return (
    <span className="flex items-center gap-2 text-sm text-stone-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />
      {label}
    </span>
  );
}

export default function ResearchToolkit({ paperIds, papers, topic }: Props) {
  const [tool, setTool] = useState<Tool>("matrix");
  const [selected, setSelected] = useState<string[]>(paperIds);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState("");

  const [rows, setRows] = useState<MatrixRow[] | null>(null);
  const [related, setRelated] = useState<RelatedWork | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [pair, setPair] = useState<[string, string]>([
    paperIds[0] ?? "",
    paperIds[1] ?? "",
  ]);
  const [copied, setCopied] = useState<string | null>(null);

  const numberOf = useMemo(
    () => (id: string) => paperIds.indexOf(id) + 1,
    [paperIds],
  );

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );

  const copy = async (text: string, what: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(what);
    setTimeout(() => setCopied(null), 1600);
  };

  const run = async (fn: () => Promise<void>, label: string) => {
    setBusy(true);
    setError(null);
    setProgress(label);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setProgress("");
    }
  };

  const buildMatrix = () =>
    run(async () => {
      const result = await api.matrix(selected);
      setRows(result.rows);
    }, `Extracting rows for ${selected.length} papers…`);

  const buildRelated = () =>
    run(async () => {
      setRelated(await api.relatedWork(selected, topic));
    }, "Drafting the related-work section…");

  const buildComparison = () =>
    run(async () => {
      const result = await api.compare(pair[0], pair[1]);
      setComparison(result.comparison);
    }, "Comparing the two papers…");

  const relatedText = related
    ? related.paragraphs.map((p) => p.text).join("\n\n") +
      "\n\n" +
      related.gap_statement
    : "";

  return (
    <div className="space-y-4">
      {/* Tool switcher */}
      <div className="flex flex-wrap gap-1">
        {TOOLS.map((entry) => (
          <button
            key={entry.key}
            onClick={() => setTool(entry.key)}
            className={
              tool === entry.key
                ? "rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-medium text-white"
                : "rounded-lg px-3 py-1.5 text-sm text-stone-600 transition hover:bg-stone-100"
            }
          >
            {entry.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-stone-400">
        {TOOLS.find((t) => t.key === tool)?.blurb}
      </p>

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {/* Paper selection (matrix + related work) */}
      {tool !== "compare" ? (
        <div className="rounded-xl border border-stone-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-stone-800">
              {selected.length} of {paperIds.length} papers selected
            </p>
            <div className="flex gap-1.5">
              <button
                onClick={() => setSelected(paperIds)}
                className="rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-600 transition hover:border-stone-400"
              >
                All
              </button>
              <button
                onClick={() => setSelected([])}
                className="rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-600 transition hover:border-stone-400"
              >
                None
              </button>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {paperIds.map((id, index) => (
              <button
                key={id}
                onClick={() => toggle(id)}
                title={papers[id]?.title}
                className={
                  selected.includes(id)
                    ? "rounded-md bg-stone-900 px-2 py-1 font-mono text-[11px] font-semibold text-white"
                    : "rounded-md border border-stone-200 px-2 py-1 font-mono text-[11px] text-stone-500 transition hover:border-stone-400"
                }
              >
                #{index + 1}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* ---------------- Matrix ---------------- */}
      {tool === "matrix" ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={buildMatrix}
              disabled={busy || selected.length === 0}
              className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
            >
              {rows ? "Rebuild matrix" : "Build matrix"}
            </button>
            {rows ? (
              <button
                onClick={() =>
                  downloadFile(
                    "/api/matrix/csv",
                    { paper_ids: rows.map((r) => r.paper_id) },
                    "literature-matrix.csv",
                  ).catch((e) => setError(String(e)))
                }
                className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm font-medium text-stone-700 transition hover:border-stone-400"
              >
                ⤓ CSV
              </button>
            ) : null}
            {busy ? <Spinner label={progress} /> : null}
          </div>

          {rows ? (
            <div className="overflow-x-auto rounded-xl border border-stone-200 bg-white">
              <table className="w-full min-w-[1000px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-stone-200 bg-stone-50 text-left">
                    {["#", "Paper", "Task", "Method family", "Datasets", "Metrics", "Headline result", "Code"].map(
                      (header) => (
                        <th
                          key={header}
                          className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-stone-500"
                        >
                          {header}
                        </th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const paper = papers[row.paper_id];
                    return (
                      <tr key={row.paper_id} className="border-b border-stone-100 align-top">
                        <td className="px-3 py-2.5 font-mono text-xs text-stone-400">
                          {numberOf(row.paper_id)}
                        </td>
                        <td className="max-w-[220px] px-3 py-2.5">
                          <span className="line-clamp-2 text-stone-800">{paper?.title}</span>
                          <span className="mt-0.5 block text-xs text-stone-400">
                            {paper?.published.slice(0, 4)}
                            {row.from_fulltext ? " · from full text" : ""}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-stone-600">{row.task}</td>
                        <td className="px-3 py-2.5 text-stone-600">{row.method_family}</td>
                        <td className="px-3 py-2.5 text-xs text-stone-600">
                          {row.datasets.length ? row.datasets.join(", ") : "—"}
                        </td>
                        <td className="px-3 py-2.5 text-xs text-stone-600">
                          {row.metrics.length ? row.metrics.join(", ") : "—"}
                        </td>
                        <td className="max-w-[240px] px-3 py-2.5 text-xs text-stone-600">
                          <RichText text={row.headline_result} />
                        </td>
                        <td className="px-3 py-2.5 text-xs">
                          {row.code_url ? (
                            <a
                              href={row.code_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-emerald-700 underline underline-offset-2"
                            >
                              repo
                            </a>
                          ) : row.code_available === "yes" ? (
                            <span className="text-emerald-700">yes</span>
                          ) : (
                            <span className="text-stone-400">{row.code_available}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* ---------------- Related work ---------------- */}
      {tool === "related" ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={buildRelated}
              disabled={busy || selected.length < 2}
              className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
            >
              {related ? "Redraft section" : "Draft related work"}
            </button>
            <button
              onClick={() =>
                downloadFile("/api/bibtex", { paper_ids: selected }, "references.bib").catch(
                  (e) => setError(String(e)),
                )
              }
              disabled={selected.length === 0}
              className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm font-medium text-stone-700 transition hover:border-stone-400 disabled:opacity-40"
            >
              ⤓ .bib
            </button>
            {busy ? <Spinner label={progress} /> : null}
          </div>
          {selected.length < 2 ? (
            <p className="text-xs text-stone-400">Select at least two papers.</p>
          ) : null}

          {related ? (
            <div className="space-y-3">
              <div className="rounded-xl border border-stone-200 bg-white p-5">
                <div className="mb-3 flex items-center justify-between">
                  <p className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
                    Draft — Related Work
                  </p>
                  <button
                    onClick={() => copy(relatedText, "draft")}
                    className="rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-600 transition hover:border-stone-400"
                  >
                    {copied === "draft" ? "Copied ✓" : "Copy text"}
                  </button>
                </div>
                {related.paragraphs.map((paragraph, index) => (
                  <div key={index} className="mb-4">
                    <p className="text-sm font-semibold text-stone-900">{paragraph.theme}</p>
                    <p className="mt-1 text-[15px] leading-relaxed text-stone-700">
                      {paragraph.text}
                    </p>
                  </div>
                ))}
                <div className="rounded-lg bg-amber-50/70 p-3">
                  <p className="text-xs font-semibold text-amber-900">Gap statement</p>
                  <p className="mt-1 text-sm leading-relaxed text-amber-900">
                    {related.gap_statement}
                  </p>
                </div>
              </div>

              <details className="rounded-xl border border-stone-200 bg-white p-4">
                <summary className="cursor-pointer text-sm font-medium text-stone-700">
                  BibTeX ({Object.keys(related.keys).length} entries)
                </summary>
                <div className="mt-2 flex justify-end">
                  <button
                    onClick={() => copy(related.bibtex, "bib")}
                    className="rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-600 transition hover:border-stone-400"
                  >
                    {copied === "bib" ? "Copied ✓" : "Copy BibTeX"}
                  </button>
                </div>
                <pre className="mt-2 overflow-x-auto rounded-lg bg-stone-50 p-3 text-xs leading-relaxed text-stone-700">
                  {related.bibtex}
                </pre>
              </details>
            </div>
          ) : null}
        </div>
      ) : null}

      {/* ---------------- Compare ---------------- */}
      {tool === "compare" ? (
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            {([0, 1] as const).map((slot) => (
              <div key={slot} className="rounded-xl border border-stone-200 bg-white p-3">
                <label className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
                  Paper {slot === 0 ? "A" : "B"}
                </label>
                <select
                  value={pair[slot]}
                  onChange={(event) =>
                    setPair((current) => {
                      const next: [string, string] = [...current];
                      next[slot] = event.target.value;
                      return next;
                    })
                  }
                  className="mt-1 w-full rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-sm text-stone-800 focus:border-stone-500 focus:outline-none"
                >
                  {paperIds.map((id, index) => (
                    <option key={id} value={id}>
                      #{index + 1} — {papers[id]?.title.slice(0, 60)}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={buildComparison}
              disabled={busy || pair[0] === pair[1]}
              className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
            >
              Compare
            </button>
            {pair[0] === pair[1] ? (
              <span className="text-xs text-stone-400">Pick two different papers.</span>
            ) : null}
            {busy ? <Spinner label={progress} /> : null}
          </div>

          {comparison ? (
            <div className="overflow-x-auto rounded-xl border border-stone-200 bg-white">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-stone-200 bg-stone-50 text-left">
                    <th className="w-28 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-stone-500">
                      Dimension
                    </th>
                    <th className="px-3 py-2 text-xs font-semibold text-stone-700">
                      A · {papers[pair[0]]?.title.slice(0, 46)}
                    </th>
                    <th className="px-3 py-2 text-xs font-semibold text-stone-700">
                      B · {papers[pair[1]]?.title.slice(0, 46)}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["Problem", comparison.problem_a, comparison.problem_b],
                      ["Method", comparison.method_a, comparison.method_b],
                      ["Results", comparison.results_a, comparison.results_b],
                      ["Strengths", comparison.strengths_a, comparison.strengths_b],
                      ["Limitations", comparison.limitations_a, comparison.limitations_b],
                      ["Use it when", comparison.when_to_use_a, comparison.when_to_use_b],
                    ] as const
                  ).map(([label, a, b]) => (
                    <tr key={label} className="border-b border-stone-100 align-top">
                      <td className="px-3 py-3 text-xs font-semibold text-stone-500">{label}</td>
                      <td className="px-3 py-3 leading-relaxed text-stone-700">
                        <RichText text={a} />
                      </td>
                      <td className="px-3 py-3 leading-relaxed text-stone-700">
                        <RichText text={b} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="border-t border-stone-200 bg-stone-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">
                  Key difference
                </p>
                <p className="mt-1 text-sm leading-relaxed text-stone-700">
                  <RichText text={comparison.key_difference} />
                </p>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
