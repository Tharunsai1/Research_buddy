"use client";

import { Fragment, useMemo, useState } from "react";
import type { GlossaryTerm } from "@/lib/types";

/**
 * Renders model prose with two affordances:
 *  - **bold** and $math$ spans get light formatting
 *  - glossary terms are underlined and explained on hover/focus
 *
 * Each term is annotated at most once per block so the text stays readable
 * rather than turning into a wall of underlines.
 */

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function TermTooltip({ term, label }: { term: GlossaryTerm; label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className="relative inline"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        className="cursor-help border-b border-dashed border-stone-400 text-inherit underline-offset-2 hover:border-stone-700"
        aria-label={`Definition of ${term.term}`}
      >
        {label}
      </button>
      {open ? (
        <span className="absolute bottom-full left-0 z-50 mb-1.5 block w-72 rounded-lg border border-stone-200 bg-white p-3 text-left shadow-lg">
          <span className="block text-xs font-semibold text-stone-900">{term.term}</span>
          <span className="mt-1 block text-xs leading-relaxed text-stone-600">
            {term.definition}
          </span>
          {term.in_this_paper ? (
            <span className="mt-1.5 block border-t border-stone-100 pt-1.5 text-xs leading-relaxed text-stone-500">
              <span className="font-medium text-stone-600">In this paper: </span>
              {term.in_this_paper}
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}

function annotate(text: string, terms: GlossaryTerm[], keyPrefix: string) {
  if (terms.length === 0) return text;

  const byLength = [...terms].sort((a, b) => b.term.length - a.term.length);
  const pattern = new RegExp(
    `\\b(${byLength.map((t) => escapeRegExp(t.term)).join("|")})\\b`,
    "gi",
  );

  const nodes: React.ReactNode[] = [];
  const seen = new Set<string>();
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    const key = match[0].toLowerCase();
    const term = byLength.find((t) => t.term.toLowerCase() === key);
    if (!term || seen.has(key)) continue;
    seen.add(key);
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    nodes.push(
      <TermTooltip key={`${keyPrefix}-${match.index}`} term={term} label={match[0]} />,
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

export default function RichText({
  text,
  terms = [],
  className,
}: {
  text: string;
  terms?: GlossaryTerm[];
  className?: string;
}) {
  const parts = useMemo(() => {
    // Split on **bold** and $math$ so those render distinctly from prose.
    const segments = text.split(/(\*\*[^*]+\*\*|\$[^$]{1,120}\$)/g);
    return segments.filter((s) => s.length > 0);
  }, [text]);

  return (
    <span className={className}>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return (
            <strong key={index} className="font-semibold text-stone-900">
              {part.slice(2, -2)}
            </strong>
          );
        }
        if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
          return (
            <code
              key={index}
              className="rounded bg-stone-100 px-1 font-mono text-[0.9em] text-stone-700"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        return <Fragment key={index}>{annotate(part, terms, String(index))}</Fragment>;
      })}
    </span>
  );
}
