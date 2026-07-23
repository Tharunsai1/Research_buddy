"use client";

import { clusterColor } from "@/lib/palette";
import type {
  OpenProblem,
  Paper,
  ReadingStep,
  SearchCluster,
  Tension,
} from "@/lib/types";

export function SectionTitle({ icon, children }: { icon: string; children: React.ReactNode }) {
  return (
    <h2 className="flex items-center gap-2 text-sm font-semibold text-stone-900">
      <span aria-hidden className="text-stone-400">
        {icon}
      </span>
      {children}
    </h2>
  );
}

function PaperChip({
  id,
  number,
  papers,
  onSelect,
}: {
  id: string;
  number: number;
  papers: Record<string, Paper>;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(id)}
      title={papers[id]?.title}
      className="rounded-md border border-stone-200 bg-white px-2 py-0.5 font-mono text-[11px] font-semibold text-stone-600 transition hover:border-stone-400 hover:text-stone-900"
    >
      #{number}
    </button>
  );
}

interface CommonProps {
  papers: Record<string, Paper>;
  numberOf: (id: string) => number;
  onSelect: (id: string) => void;
}

export function ClustersSection({
  clusters,
  papers,
  numberOf,
  onSelect,
}: CommonProps & { clusters: SearchCluster[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {clusters.map((cluster, index) => (
        <div key={cluster.name + index} className="rounded-xl border border-stone-200 bg-white p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-stone-900">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: clusterColor(index, "light") }}
            />
            {cluster.name}
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-stone-600">{cluster.description}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {cluster.paper_ids.map((id) => (
              <PaperChip key={id} id={id} number={numberOf(id)} papers={papers} onSelect={onSelect} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function TensionsSection({
  tensions,
  papers,
  numberOf,
  onSelect,
}: CommonProps & { tensions: Tension[] }) {
  if (tensions.length === 0) return null;
  return (
    <div className="space-y-3">
      {tensions.map((tension, index) => (
        <div key={index} className="rounded-xl border border-stone-200 bg-white p-4">
          <p className="text-sm font-semibold text-stone-900">{tension.name}</p>
          <p className="mt-1.5 text-sm leading-relaxed text-stone-600">{tension.description}</p>
          <div className="mt-3 grid items-start gap-3 md:grid-cols-[1fr_auto_1fr]">
            <div className="rounded-lg bg-stone-50 p-3">
              <p className="text-xs font-medium text-stone-700">{tension.side_a.label}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tension.side_a.paper_ids.map((id) => (
                  <PaperChip key={id} id={id} number={numberOf(id)} papers={papers} onSelect={onSelect} />
                ))}
              </div>
            </div>
            <span className="hidden pt-3 font-mono text-[11px] font-semibold uppercase text-stone-400 md:block">
              vs
            </span>
            <div className="rounded-lg bg-stone-50 p-3">
              <p className="text-xs font-medium text-stone-700">{tension.side_b.label}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {tension.side_b.paper_ids.map((id) => (
                  <PaperChip key={id} id={id} number={numberOf(id)} papers={papers} onSelect={onSelect} />
                ))}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ConsensusSection({ consensus }: { consensus: string[] }) {
  if (consensus.length === 0) return null;
  return (
    <ul className="space-y-2 rounded-xl border border-stone-200 bg-white p-4">
      {consensus.map((statement, index) => (
        <li key={index} className="flex gap-2.5 text-sm leading-relaxed text-stone-600">
          <span aria-hidden className="mt-0.5 text-[#0ca30c]">
            ✓
          </span>
          {statement}
        </li>
      ))}
    </ul>
  );
}

export function OpenProblemsSection({
  problems,
  papers,
  numberOf,
  onSelect,
}: CommonProps & { problems: OpenProblem[] }) {
  if (problems.length === 0) return null;
  return (
    <ol className="space-y-3">
      {problems.map((problem, index) => (
        <li key={index} className="flex gap-4 rounded-xl border border-stone-200 bg-white p-4">
          <span className="font-mono text-sm font-semibold text-stone-300">
            {String(index + 1).padStart(2, "0")}
          </span>
          <div>
            <p className="text-sm font-semibold text-stone-900">{problem.title}</p>
            <p className="mt-1 text-sm leading-relaxed text-stone-600">{problem.description}</p>
            {problem.paper_ids.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {problem.paper_ids.map((id) => (
                  <PaperChip key={id} id={id} number={numberOf(id)} papers={papers} onSelect={onSelect} />
                ))}
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

const STAGE_LABEL: Record<ReadingStep["stage"], string> = {
  foundation: "Foundations",
  core: "Core methods",
  frontier: "Frontier",
};

export function ReadingOrderSection({
  readingOrder,
  papers,
  read,
  onSelect,
}: {
  readingOrder: ReadingStep[];
  papers: Record<string, Paper>;
  read: string[];
  onSelect: (id: string) => void;
}) {
  const readSet = new Set(read);
  const stages: ReadingStep["stage"][] = ["foundation", "core", "frontier"];
  let counter = 0;
  return (
    <div className="space-y-4">
      {stages.map((stage) => {
        const steps = readingOrder.filter((step) => step.stage === stage);
        if (steps.length === 0) return null;
        return (
          <div key={stage}>
            <p className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
              {STAGE_LABEL[stage]}
            </p>
            <ol className="mt-2 space-y-2">
              {steps.map((step) => {
                counter += 1;
                const paper = papers[step.paper_id];
                const isRead = readSet.has(step.paper_id);
                return (
                  <li
                    key={step.paper_id}
                    className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white p-3.5"
                  >
                    <span
                      className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-[11px] font-semibold ${
                        isRead ? "bg-emerald-600 text-white" : "bg-stone-100 text-stone-500"
                      }`}
                    >
                      {isRead ? "✓" : counter}
                    </span>
                    <div className="min-w-0">
                      <button
                        onClick={() => onSelect(step.paper_id)}
                        className={`text-left text-sm font-medium leading-snug underline-offset-2 hover:underline ${
                          isRead ? "text-stone-400 line-through" : "text-stone-900"
                        }`}
                      >
                        {paper?.title ?? step.paper_id}
                      </button>
                      {step.why ? (
                        <p className="mt-0.5 text-xs leading-relaxed text-stone-500">{step.why}</p>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        );
      })}
    </div>
  );
}
