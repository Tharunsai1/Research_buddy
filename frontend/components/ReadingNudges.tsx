"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ReadingNudge } from "@/lib/types";

interface Props {
  searchId: string;
  onSelectPaper: (id: string) => void;
}

/**
 * Joins quiz performance with the reading order's own dependency edges: if
 * the reader is scoring poorly on a foundational paper and a later paper
 * explicitly builds on it, nudge them to reread it before continuing. Free —
 * no LLM call, everything here already exists from quiz grading and
 * landscape synthesis.
 */
export default function ReadingNudges({ searchId, onSelectPaper }: Props) {
  const [nudges, setNudges] = useState<ReadingNudge[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .readingNudges(searchId)
      .then((result) => {
        if (!cancelled) setNudges(result.nudges);
      })
      .catch(() => {
        if (!cancelled) setNudges([]);
      });
    return () => {
      cancelled = true;
    };
  }, [searchId]);

  if (nudges.length === 0) return null;

  return (
    <div className="space-y-2">
      {nudges.map((nudge) => (
        <div
          key={nudge.weak_paper_id}
          className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3"
        >
          <p className="text-sm leading-relaxed text-amber-900">
            <span className="font-semibold">Shaky on this one</span> — you scored{" "}
            <span className="font-semibold">{Math.round(nudge.avg_score)}/100</span> on{" "}
            <button
              onClick={() => onSelectPaper(nudge.weak_paper_id)}
              className="font-medium underline underline-offset-2 hover:text-amber-950"
            >
              {nudge.weak_paper_title}
            </button>
            {nudge.reviewed_count > 1 ? ` (${nudge.reviewed_count} reviews)` : ""}, and{" "}
            {nudge.blocks.length === 1 ? (
              <button
                onClick={() => onSelectPaper(nudge.blocks[0])}
                className="font-medium underline underline-offset-2 hover:text-amber-950"
              >
                {nudge.blocks_titles[0]}
              </button>
            ) : (
              `${nudge.blocks.length} later papers`
            )}{" "}
            build{nudge.blocks.length === 1 ? "s" : ""} on it — worth a reread before
            continuing.
          </p>
        </div>
      ))}
    </div>
  );
}
