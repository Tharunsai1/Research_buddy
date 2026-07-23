"use client";

import type { Job } from "@/lib/types";

interface Props {
  job: Job;
  papersPerSearch: number;
  onDismiss: () => void;
}

function StageDot({ status }: { status: string }) {
  if (status === "done")
    return <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-[#0ca30c]" />;
  if (status === "active")
    return <span className="h-2.5 w-2.5 shrink-0 animate-pulse-dot rounded-full bg-[#2a78d6]" />;
  if (status === "error")
    return <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-[#d03b3b]" />;
  return <span className="h-2.5 w-2.5 shrink-0 rounded-full border border-stone-300 bg-stone-100" />;
}

export default function PipelineCard({ job, papersPerSearch, onDismiss }: Props) {
  const active = job.stages.find((s) => s.status === "active");
  const failed = job.status === "error";

  return (
    <div className="mx-auto mt-14 w-full max-w-md rounded-2xl border border-stone-200 bg-white p-6 shadow-sm">
      <div className="flex items-center gap-3">
        {failed ? (
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-red-50 text-sm text-[#d03b3b]">
            ✕
          </span>
        ) : job.status === "done" ? (
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-50 text-sm text-[#0ca30c]">
            ✓
          </span>
        ) : (
          <span
            className="h-5 w-5 animate-spin rounded-full border-2 border-stone-200 border-t-stone-600"
            aria-hidden
          />
        )}
        <h2 className="text-base font-semibold text-stone-900">
          {failed ? "Pipeline failed" : job.status === "done" ? "Pipeline complete" : "Running pipeline"}
        </h2>
      </div>

      <p className="mt-2 min-h-5 text-sm text-stone-600">
        {failed ? job.error : (active?.detail || active?.label || "Loading results…")}
      </p>
      {!failed && (
        <p className="mt-0.5 text-xs text-stone-400">
          Usually takes 1–2 minutes for {papersPerSearch} papers.
        </p>
      )}

      <ul className="mt-5 space-y-3">
        {job.stages.map((stage) => (
          <li key={stage.key} className="flex items-center gap-3">
            <StageDot status={stage.status} />
            <span
              className={
                stage.status === "active"
                  ? "text-sm font-medium text-stone-900"
                  : stage.status === "done"
                    ? "text-sm text-stone-700"
                    : stage.status === "error"
                      ? "text-sm text-[#d03b3b]"
                      : "text-sm text-stone-400"
              }
            >
              {stage.label}
            </span>
            {stage.status === "done" && stage.detail ? (
              <span className="ml-auto truncate text-xs text-stone-400">{stage.detail}</span>
            ) : null}
          </li>
        ))}
      </ul>

      {failed ? (
        <button
          onClick={onDismiss}
          className="mt-5 w-full rounded-lg border border-stone-200 bg-stone-50 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
        >
          Dismiss
        </button>
      ) : null}
    </div>
  );
}
