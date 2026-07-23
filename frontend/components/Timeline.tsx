"use client";

import { useMemo, useState } from "react";
import { clusterColor } from "@/lib/palette";
import type { CitationMetrics, MapCluster, Paper } from "@/lib/types";

const W = 900;
const ROW_H = 34;
const PAD_L = 168;
const PAD_R = 24;
const PAD_T = 26;

interface Props {
  papers: Record<string, Paper>;
  clusters: MapCluster[];
  citations?: Record<string, CitationMetrics>;
  read: string[];
  onSelect: (paperId: string) => void;
}

interface Dot {
  id: string;
  title: string;
  x: number;
  r: number;
  date: string;
  citations: number;
  read: boolean;
}

function monthsBetween(a: Date, b: Date): number {
  return (b.getFullYear() - a.getFullYear()) * 12 + (b.getMonth() - a.getMonth());
}

export default function Timeline({
  papers,
  clusters,
  citations = {},
  read,
  onSelect,
}: Props) {
  const [hovered, setHovered] = useState<Dot | null>(null);
  const readSet = useMemo(() => new Set(read), [read]);

  const { rows, ticks, height } = useMemo(() => {
    const dated = Object.values(papers).filter((p) => /^\d{4}-\d{2}-\d{2}/.test(p.published));
    if (dated.length === 0) return { rows: [], ticks: [], height: 120 };

    const times = dated.map((p) => new Date(p.published).getTime());
    const min = new Date(Math.min(...times));
    const max = new Date(Math.max(...times));
    // Pad the axis by a month on each side so dots never touch the edges.
    const start = new Date(min.getFullYear(), min.getMonth() - 1, 1);
    const end = new Date(max.getFullYear(), max.getMonth() + 1, 1);
    const span = Math.max(monthsBetween(start, end), 1);
    const plotWidth = W - PAD_L - PAD_R;
    const xOf = (published: string) =>
      PAD_L + (monthsBetween(start, new Date(published)) / span) * plotWidth;

    const rows = clusters.map((cluster, index) => {
      const dots: Dot[] = cluster.paper_ids
        .map((id) => papers[id])
        .filter((p): p is Paper => Boolean(p) && /^\d{4}-\d{2}-\d{2}/.test(p.published))
        .map((paper) => {
          const count = citations[paper.id]?.citations ?? 0;
          return {
            id: paper.id,
            title: paper.title,
            x: xOf(paper.published),
            r: Math.max(3.5, Math.min(11, 3.5 + Math.sqrt(count) * 0.5)),
            date: paper.published,
            citations: count,
            read: readSet.has(paper.id),
          };
        })
        .sort((a, b) => a.x - b.x);
      return { name: cluster.name, color: clusterColor(index, "light"), dots };
    });

    // One tick per year, or per half-year for short spans.
    const ticks: { x: number; label: string }[] = [];
    const step = span > 30 ? 12 : 6;
    for (let m = 0; m <= span; m += step) {
      const date = new Date(start.getFullYear(), start.getMonth() + m, 1);
      ticks.push({
        x: PAD_L + (m / span) * plotWidth,
        label:
          step === 12
            ? String(date.getFullYear())
            : `${date.toLocaleString("en", { month: "short" })} ${String(date.getFullYear()).slice(2)}`,
      });
    }

    return {
      rows,
      ticks,
      height: PAD_T + rows.length * ROW_H + 18,
    };
  }, [papers, clusters, citations, readSet]);

  if (rows.length === 0) return null;

  return (
    <div className="relative rounded-xl border border-stone-200 bg-white p-4">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        className="block w-full"
        role="img"
        aria-label="Timeline of papers by cluster and publication date"
      >
        {ticks.map((tick, index) => (
          <g key={index}>
            <line
              x1={tick.x}
              y1={PAD_T - 10}
              x2={tick.x}
              y2={height - 14}
              stroke="#e7e5e4"
              strokeWidth={1}
            />
            <text x={tick.x} y={PAD_T - 16} textAnchor="middle" fontSize={10} fill="#a8a29e">
              {tick.label}
            </text>
          </g>
        ))}

        {rows.map((row, rowIndex) => {
          const y = PAD_T + rowIndex * ROW_H + ROW_H / 2;
          const first = row.dots[0];
          const last = row.dots[row.dots.length - 1];
          return (
            <g key={row.name}>
              <text x={0} y={y + 3.5} fontSize={11} fill="#57534e">
                {row.name.length > 26 ? `${row.name.slice(0, 25)}…` : row.name}
              </text>
              {first && last && last.x > first.x ? (
                <line
                  x1={first.x}
                  y1={y}
                  x2={last.x}
                  y2={y}
                  stroke={row.color}
                  strokeOpacity={0.25}
                  strokeWidth={2}
                  strokeLinecap="round"
                />
              ) : null}
              {row.dots.map((dot) => (
                <circle
                  key={dot.id}
                  cx={dot.x}
                  cy={y}
                  r={hovered?.id === dot.id ? dot.r + 2 : dot.r}
                  fill={row.color}
                  fillOpacity={dot.read ? 0.35 : 0.9}
                  stroke={dot.read ? row.color : "#ffffff"}
                  strokeWidth={dot.read ? 1.5 : 1}
                  className="cursor-pointer"
                  onMouseEnter={() => setHovered(dot)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onSelect(dot.id)}
                />
              ))}
            </g>
          );
        })}
      </svg>

      {hovered ? (
        <div className="pointer-events-none absolute left-4 right-4 bottom-1 rounded-lg border border-stone-200 bg-white/95 px-3 py-1.5 shadow-sm">
          <p className="truncate text-xs font-medium text-stone-800">{hovered.title}</p>
          <p className="text-[11px] text-stone-500">
            {hovered.date}
            {hovered.citations > 0 ? ` · ${hovered.citations.toLocaleString()} citations` : ""}
            {hovered.read ? " · read" : ""}
          </p>
        </div>
      ) : null}
    </div>
  );
}
