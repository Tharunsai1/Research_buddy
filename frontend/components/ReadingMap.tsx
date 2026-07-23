"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationNodeDatum,
} from "d3-force";
import { CLUSTER_DARK, UNCLUSTERED_DARK, clusterColor } from "@/lib/palette";
import type { CitationMetrics, Edge, MapCluster, Paper } from "@/lib/types";

const W = 920;
const H = 520;
const PAD = 26;
const MIN_SCALE = 0.4;
const MAX_SCALE = 5;

function clampScale(scale: number): number {
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));
}

interface MapNode extends SimulationNodeDatum {
  id: string;
  title: string;
  cluster: number; // -1 = unclustered
  read: boolean;
  citations: number;
  radius: number;
  seminal: boolean;
}

interface MapLink {
  source: MapNode | string;
  target: MapNode | string;
  kind: string;
  bridge: boolean;
  real: boolean;
}

interface Props {
  papers: Record<string, Paper>;
  clusters: MapCluster[];
  edges: Edge[];
  read: string[];
  citations?: Record<string, CitationMetrics>;
  seminal?: Record<string, string>;
  onSelect: (paperId: string) => void;
}

/** Area-proportional radius so a 10x citation count doesn't render 10x wide. */
function radiusFor(citations: number): number {
  return Math.max(6, Math.min(20, 6 + Math.sqrt(citations) * 0.75));
}

export default function ReadingMap({
  papers,
  clusters,
  edges,
  read,
  citations = {},
  seminal = {},
  onSelect,
}: Props) {
  const readSet = useMemo(() => new Set(read), [read]);
  const [, setTick] = useState(0);
  const [hovered, setHovered] = useState<MapNode | null>(null);
  const simRef = useRef<Simulation<MapNode, undefined> | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ node: MapNode; moved: boolean } | null>(null);
  // A drag ends with a click event on the node; swallow that one.
  const suppressClickRef = useRef(false);

  // Pan/zoom of the whole map, applied as a transform on the content group.
  // At 90+ papers the default 1:1 view is too dense to read; this is what
  // makes "All papers" usable instead of just a colorful blur.
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const viewRef = useRef(view);
  viewRef.current = view;
  const panRef = useRef<{
    startClientX: number;
    startClientY: number;
    startX: number;
    startY: number;
  } | null>(null);
  const [panning, setPanning] = useState(false);

  const { nodes, links } = useMemo(() => {
    const clusterOf = new Map<string, number>();
    clusters.forEach((cluster, index) => {
      cluster.paper_ids.forEach((pid) => clusterOf.set(pid, index));
    });
    const seminalIds = new Set(Object.values(seminal));
    const nodes: MapNode[] = Object.values(papers).map((paper) => {
      const count = citations[paper.id]?.citations ?? 0;
      return {
        id: paper.id,
        title: paper.title,
        cluster: clusterOf.get(paper.id) ?? -1,
        read: readSet.has(paper.id),
        citations: count,
        radius: radiusFor(count),
        seminal: seminalIds.has(paper.id),
      };
    });
    const ids = new Set(nodes.map((n) => n.id));
    const links: MapLink[] = edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        kind: e.kind,
        bridge: Boolean(e.bridge),
        real: Boolean(e.real),
      }));
    return { nodes, links };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [papers, clusters, edges, citations, seminal]);

  // Keep read state in sync without rebuilding the simulation.
  useEffect(() => {
    nodes.forEach((node) => {
      node.read = readSet.has(node.id);
    });
    setTick((t) => t + 1);
  }, [readSet, nodes]);

  useEffect(() => {
    const clusterCount = Math.max(clusters.length, 1);
    const anchor = (index: number) => {
      if (index < 0) return { x: W / 2, y: H / 2 };
      const angle = (index / clusterCount) * Math.PI * 2 - Math.PI / 2;
      return { x: W / 2 + Math.cos(angle) * 260, y: H / 2 + Math.sin(angle) * 140 };
    };

    const simulation = forceSimulation<MapNode>(nodes)
      .force(
        "link",
        forceLink<MapNode, MapLink>(links as MapLink[])
          .id((d) => d.id)
          .distance(64)
          .strength(0.25),
      )
      .force("charge", forceManyBody().strength(-110))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide<MapNode>((d) => d.radius + 4))
      .force("x", forceX<MapNode>((d) => anchor(d.cluster).x).strength(0.07))
      .force("y", forceY<MapNode>((d) => anchor(d.cluster).y).strength(0.09))
      .on("tick", () => {
        for (const node of nodes) {
          node.x = Math.max(PAD, Math.min(W - PAD, node.x ?? W / 2));
          node.y = Math.max(PAD, Math.min(H - PAD, node.y ?? H / 2));
        }
        setTick((t) => t + 1);
      });

    simRef.current = simulation;
    return () => {
      simulation.stop();
      simRef.current = null;
    };
  }, [nodes, links, clusters.length]);

  const toViewBox = (event: { clientX: number; clientY: number }) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: ((event.clientX - rect.left) / rect.width) * W,
      y: ((event.clientY - rect.top) / rect.height) * H,
    };
  };

  // Undo the pan/zoom transform to get the node-space coordinate a screen
  // point corresponds to — needed so drag-to-pin still tracks the cursor
  // correctly while zoomed in or panned.
  const toWorld = (event: { clientX: number; clientY: number }) => {
    const vb = toViewBox(event);
    const { x, y, scale } = viewRef.current;
    return { x: (vb.x - x) / scale, y: (vb.y - y) / scale };
  };

  // Dragging pins a node where it is dropped, so the reader can untangle a
  // crowded corner and have it stay put.
  const startDrag = (event: React.PointerEvent, node: MapNode) => {
    event.preventDefault();
    event.stopPropagation(); // don't also start a background pan
    dragRef.current = { node, moved: false };
    node.fx = node.x;
    node.fy = node.y;
    simRef.current?.alphaTarget(0.15).restart();
  };

  const startPan = (event: React.PointerEvent) => {
    if (event.target !== event.currentTarget) return; // only empty background
    panRef.current = {
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: view.x,
      startY: view.y,
    };
    setPanning(true);
  };

  const handlePointerMove = (event: React.PointerEvent) => {
    const pan = panRef.current;
    if (pan) {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;
      const dx = ((event.clientX - pan.startClientX) / rect.width) * W;
      const dy = ((event.clientY - pan.startClientY) / rect.height) * H;
      setView((v) => ({ ...v, x: pan.startX + dx, y: pan.startY + dy }));
      return;
    }
    const drag = dragRef.current;
    if (!drag) return;
    const { x, y } = toWorld(event);
    if (Math.hypot(x - (drag.node.fx ?? x), y - (drag.node.fy ?? y)) > 2) {
      drag.moved = true;
    }
    drag.node.fx = Math.max(PAD, Math.min(W - PAD, x));
    drag.node.fy = Math.max(PAD, Math.min(H - PAD, y));
  };

  const endDrag = () => {
    panRef.current = null;
    setPanning(false);
    const drag = dragRef.current;
    if (!drag) return;
    suppressClickRef.current = drag.moved;
    dragRef.current = null;
    simRef.current?.alphaTarget(0);
  };

  const handlePointerLeave = () => {
    endDrag();
    setHovered(null);
  };

  const handleNodeClick = (node: MapNode) => {
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onSelect(node.id);
  };

  // Wheel needs a non-passive native listener — React's synthetic onWheel is
  // passive by default, so preventDefault() there won't stop the page behind
  // the map from also scrolling while the reader is trying to zoom it.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = svg.getBoundingClientRect();
      const vbX = ((event.clientX - rect.left) / rect.width) * W;
      const vbY = ((event.clientY - rect.top) / rect.height) * H;
      setView((v) => {
        const factor = Math.exp(-event.deltaY * 0.001);
        const scale = clampScale(v.scale * factor);
        const worldX = (vbX - v.x) / v.scale;
        const worldY = (vbY - v.y) / v.scale;
        return { scale, x: vbX - worldX * scale, y: vbY - worldY * scale };
      });
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const zoomBy = (factor: number) => {
    setView((v) => {
      const scale = clampScale(v.scale * factor);
      // Zoom toward the current view's center so button zoom feels anchored,
      // not like it yanks the map toward a corner.
      const worldCx = (W / 2 - v.x) / v.scale;
      const worldCy = (H / 2 - v.y) / v.scale;
      return { scale, x: W / 2 - worldCx * scale, y: H / 2 - worldCy * scale };
    });
  };

  const resetView = () => setView({ x: 0, y: 0, scale: 1 });

  const nodeColor = (node: MapNode) =>
    node.cluster < 0 ? UNCLUSTERED_DARK : clusterColor(node.cluster, "dark");

  const hoveredId = hovered?.id;
  const hasCitations = nodes.some((n) => n.citations > 0);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-stone-800 bg-[#0d1117] shadow-sm">
      <div className="pointer-events-none absolute left-4 top-3 z-10 rounded-md bg-white/5 px-3 py-1.5 backdrop-blur-sm">
        <p className="text-xs font-medium text-stone-200">Reading map</p>
        <p className="text-[11px] text-stone-400">
          {nodes.length} papers · click to open · drag a paper to rearrange · scroll or
          pinch to zoom · drag the background to pan
        </p>
      </div>

      <div className="absolute right-3 top-3 z-10 flex flex-col gap-1">
        <button
          type="button"
          onClick={() => zoomBy(1.4)}
          aria-label="Zoom in"
          className="flex h-7 w-7 items-center justify-center rounded-md border border-white/10 bg-white/5 text-sm text-stone-200 backdrop-blur-sm transition hover:bg-white/15"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => zoomBy(1 / 1.4)}
          aria-label="Zoom out"
          className="flex h-7 w-7 items-center justify-center rounded-md border border-white/10 bg-white/5 text-sm text-stone-200 backdrop-blur-sm transition hover:bg-white/15"
        >
          −
        </button>
        {view.scale !== 1 || view.x !== 0 || view.y !== 0 ? (
          <button
            type="button"
            onClick={resetView}
            aria-label="Reset zoom and pan"
            title="Reset view"
            className="flex h-7 w-7 items-center justify-center rounded-md border border-white/10 bg-white/5 text-[11px] text-stone-200 backdrop-blur-sm transition hover:bg-white/15"
          >
            ⟲
          </button>
        ) : null}
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className={`block h-[420px] w-full sm:h-[480px] ${panning ? "cursor-grabbing" : "cursor-grab"}`}
        onPointerDown={startPan}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerLeave={handlePointerLeave}
        role="img"
        aria-label="Force-directed reading map of collected papers, colored by cluster"
      >
        <g transform={`translate(${view.x},${view.y}) scale(${view.scale})`}>
        {[
        ...(links as (MapLink & { source: MapNode; target: MapNode })[]).map(
          (link, index) => {
            const active =
              hoveredId != null &&
              (link.source.id === hoveredId || link.target.id === hoveredId);
            // Real citations read as solid and brighter; inferred links are
            // dimmer, and cross-search bridges stay dashed.
            const stroke = active
              ? "#e7e5e4"
              : link.real
                ? "rgba(255,255,255,0.42)"
                : "rgba(255,255,255,0.13)";
            return (
              <line
                key={index}
                x1={link.source.x}
                y1={link.source.y}
                x2={link.target.x}
                y2={link.target.y}
                stroke={stroke}
                strokeWidth={active ? 1.8 : link.real ? 1.3 : 1}
                strokeDasharray={link.bridge ? "4 4" : link.real ? undefined : "2 3"}
              />
            );
          },
        ),
        ...nodes.map((node) => (
          <g
            key={node.id}
            transform={`translate(${node.x ?? 0},${node.y ?? 0})`}
            className="cursor-pointer"
            onPointerEnter={() => setHovered(node)}
            onPointerDown={(event) => startDrag(event, node)}
            onClick={() => handleNodeClick(node)}
          >
            <circle r={node.radius + 8} fill="transparent" />
            {node.seminal ? (
              <circle
                r={node.radius + 3.5}
                fill="none"
                stroke={nodeColor(node)}
                strokeOpacity={0.55}
                strokeWidth={1.2}
              />
            ) : null}
            <circle
              r={node.id === hoveredId ? node.radius + 2 : node.radius}
              fill={nodeColor(node)}
              fillOpacity={node.read ? 0.4 : 0.95}
              stroke={node.read ? "#ffffff" : "rgba(255,255,255,0.25)"}
              strokeOpacity={node.read ? 0.7 : 1}
              strokeWidth={node.read ? 1.5 : 0.5}
            />
            {node.read ? (
              <text
                y={3}
                textAnchor="middle"
                fontSize={Math.min(10, node.radius)}
                fill="#ffffff"
                className="pointer-events-none select-none"
              >
                ✓
              </text>
            ) : null}
          </g>
        )),
        ]}
        </g>
      </svg>

      {hovered ? (
        <div
          className="pointer-events-none absolute z-20 max-w-xs -translate-x-1/2 rounded-lg border border-stone-700 bg-stone-900/95 px-3 py-2 shadow-lg"
          style={{
            left: `${(((hovered.x ?? 0) * view.scale + view.x) / W) * 100}%`,
            top: `calc(${(((hovered.y ?? 0) * view.scale + view.y) / H) * 100}% - 8px)`,
            transform: "translate(-50%, -100%)",
          }}
        >
          <p className="text-xs font-medium leading-snug text-stone-100">
            {hovered.title}
          </p>
          <p className="mt-0.5 text-[11px] text-stone-400">
            {hovered.cluster >= 0 ? clusters[hovered.cluster]?.name : "Unclustered"}
            {hovered.citations > 0
              ? ` · ${hovered.citations.toLocaleString()} citations`
              : ""}
            {hovered.seminal ? " · most cited here" : ""}
            {hovered.read ? " · read" : ""}
          </p>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-white/5 px-4 py-3">
        {clusters.map((cluster, index) => (
          <span key={cluster.name + index} className="flex items-center gap-1.5 text-[11px] text-[#c3c2b7]">
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: CLUSTER_DARK[index % CLUSTER_DARK.length] }}
            />
            {cluster.name}
          </span>
        ))}
        {hasCitations ? (
          <span className="ml-auto flex items-center gap-3 text-[11px] text-stone-500">
            <span className="flex items-center gap-1.5">
              <svg width="26" height="12" aria-hidden>
                <circle cx="5" cy="6" r="3" fill="#8b949e" />
                <circle cx="18" cy="6" r="5.5" fill="#8b949e" />
              </svg>
              size = citations
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="22" height="8" aria-hidden>
                <line x1="0" y1="4" x2="22" y2="4" stroke="rgba(255,255,255,0.42)" strokeWidth="1.3" />
              </svg>
              cites
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="22" height="8" aria-hidden>
                <line
                  x1="0"
                  y1="4"
                  x2="22"
                  y2="4"
                  stroke="rgba(255,255,255,0.16)"
                  strokeWidth="1"
                  strokeDasharray="2 3"
                />
              </svg>
              related
            </span>
          </span>
        ) : null}
      </div>
    </div>
  );
}
