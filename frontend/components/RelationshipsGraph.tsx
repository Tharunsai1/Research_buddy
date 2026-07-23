"use client";

import { useMemo, useState } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceCenter,
  forceSimulation,
  forceX,
  forceY,
  type SimulationNodeDatum,
} from "d3-force";
import type { Edge, Paper } from "@/lib/types";

const W = 860;
const H = 360;
const PAD = 46;
const R = 17;

interface GraphNode extends SimulationNodeDatum {
  id: string;
  index_: number;
}

interface Props {
  paperIds: string[];
  papers: Record<string, Paper>;
  edges: Edge[];
  onSelect: (paperId: string) => void;
}

export default function RelationshipsGraph({ paperIds, papers, edges, onSelect }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  const { nodes, links } = useMemo(() => {
    const nodes: GraphNode[] = paperIds.map((id, i) => ({
      id,
      index_: i + 1,
      // Deterministic seed positions around an ellipse.
      x: W / 2 + Math.cos((i / paperIds.length) * Math.PI * 2) * 240,
      y: H / 2 + Math.sin((i / paperIds.length) * Math.PI * 2) * 90,
    }));
    const ids = new Set(paperIds);
    const links = edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({ ...e }));

    const simulation = forceSimulation<GraphNode>(nodes)
      .force(
        "link",
        forceLink<GraphNode, (typeof links)[number] & SimulationNodeDatum>(
          links as never,
        )
          .id((d: GraphNode) => d.id)
          .distance(140)
          .strength(0.35),
      )
      // distanceMax keeps repulsion local, so unconnected papers drift apart
      // instead of being flung at the walls.
      .force("charge", forceManyBody().strength(-360).distanceMax(360))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide(R + 26))
      .force("x", forceX(W / 2).strength(0.045))
      .force("y", forceY(H / 2).strength(0.09))
      .stop();

    // Clamp on every tick, not once at the end. Clamping only after the run
    // teleports every escaped node onto the border, where they stack on top of
    // each other; clamping as it settles lets collide spread them out instead.
    for (let i = 0; i < 400; i += 1) {
      simulation.tick();
      for (const node of nodes) {
        node.x = Math.max(PAD, Math.min(W - PAD, node.x ?? W / 2));
        node.y = Math.max(PAD, Math.min(H - PAD, node.y ?? H / 2));
      }
    }
    return { nodes, links: links as unknown as (Edge & { source: GraphNode; target: GraphNode })[] };
  }, [paperIds, edges]);

  const numberOf = (id: string) => paperIds.indexOf(id) + 1;

  if (nodes.length === 0) return null;

  const isActive = (link: Edge & { source: GraphNode; target: GraphNode }) =>
    hovered != null && (link.source.id === hovered || link.target.id === hovered);
  const neighbours = new Set<string>();
  if (hovered) {
    for (const link of links) {
      if (link.source.id === hovered) neighbours.add(link.target.id);
      if (link.target.id === hovered) neighbours.add(link.source.id);
    }
  }

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block w-full"
        role="img"
        aria-label="Relationships between the papers in this search"
      >
        <defs>
          <marker
            id="rel-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 7 4 L 0 7 z" fill="#a8a29e" />
          </marker>
          <marker
            id="rel-arrow-active"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 7 4 L 0 7 z" fill="#57534e" />
          </marker>
        </defs>

        {links.map((link, index) => {
          const sx = link.source.x!;
          const sy = link.source.y!;
          const tx = link.target.x!;
          const ty = link.target.y!;
          const dx = tx - sx;
          const dy = ty - sy;
          const length = Math.max(Math.hypot(dx, dy), 1);
          // Bow each edge sideways so parallel pairs stay readable, and stop
          // short of the node so the arrowhead sits outside the circle.
          const bow = Math.min(30, length * 0.16);
          const nx = -(dy / length) * bow;
          const ny = (dx / length) * bow;
          const midX = (sx + tx) / 2 + nx;
          const midY = (sy + ty) / 2 + ny;
          const trim = R + 7;
          const x1 = sx + (dx / length) * trim;
          const y1 = sy + (dy / length) * trim;
          const x2 = tx - (dx / length) * trim;
          const y2 = ty - (dy / length) * trim;
          const active = isActive(link);
          return (
            <g key={index}>
              <path
                d={`M ${x1} ${y1} Q ${midX} ${midY} ${x2} ${y2}`}
                fill="none"
                stroke={active ? "#57534e" : hovered ? "#ededeb" : "#dcd9d6"}
                strokeWidth={active ? 1.9 : 1.2}
                markerEnd={active ? "url(#rel-arrow-active)" : "url(#rel-arrow)"}
              />
              {/* Labelling every edge at once is what made this unreadable —
                  the relationship list below carries the detail, so only the
                  hovered paper's edges are named here. */}
              {active ? (
                <text
                  x={midX}
                  y={midY}
                  textAnchor="middle"
                  fontSize={10}
                  fill="#57534e"
                  paintOrder="stroke"
                  stroke="#ffffff"
                  strokeWidth={3.5}
                  strokeLinejoin="round"
                  className="select-none"
                >
                  {link.kind.replace(/_/g, " ")}
                </text>
              ) : null}
            </g>
          );
        })}

        {nodes.map((node) => {
          const dimmed = hovered != null && hovered !== node.id && !neighbours.has(node.id);
          return (
            <g
              key={node.id}
              transform={`translate(${node.x},${node.y})`}
              className="cursor-pointer"
              opacity={dimmed ? 0.3 : 1}
              onPointerEnter={() => setHovered(node.id)}
              onPointerLeave={() => setHovered(null)}
              onClick={() => onSelect(node.id)}
            >
              <circle r={R + 9} fill="transparent" />
              <circle
                r={R}
                fill={hovered === node.id ? "#0c0a09" : "#1c1917"}
                stroke="#ffffff"
                strokeWidth={hovered === node.id ? 3 : 0}
              />
              <text
                y={4}
                textAnchor="middle"
                fontSize={11}
                fontWeight={600}
                fill="#ffffff"
                className="pointer-events-none select-none"
              >
                #{node.index_}
              </text>
            </g>
          );
        })}
      </svg>

      <p className="min-h-[1.25rem] px-1 text-xs text-stone-500">
        {hovered
          ? `#${numberOf(hovered)} — ${papers[hovered]?.title ?? ""}`
          : "Hover a paper to trace its relationships · click to open"}
      </p>

      <ul className="mt-4 space-y-2 border-t border-stone-100 pt-4">
        {links.map((link, index) => {
          const active = isActive(link);
          return (
            <li
              key={index}
              className={`flex gap-3 rounded-md px-1.5 py-1 text-sm transition ${
                active ? "bg-stone-100" : ""
              }`}
              onPointerEnter={() => setHovered(link.source.id)}
              onPointerLeave={() => setHovered(null)}
            >
              <span className="shrink-0 font-mono text-xs font-semibold text-emerald-700">
                #{numberOf(link.source.id)} → #{numberOf(link.target.id)}
              </span>
              <span className="text-stone-600">{link.description}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
