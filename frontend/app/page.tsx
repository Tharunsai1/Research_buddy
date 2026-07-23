"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, downloadFile } from "@/lib/api";
import type { AppState, Health, Job, SearchDetail } from "@/lib/types";
import PipelineCard from "@/components/PipelineCard";
import PaperList from "@/components/PaperList";
import PaperWorkspace from "@/components/PaperWorkspace";
import FieldDigest from "@/components/FieldDigest";
import SearchDiffView from "@/components/SearchDiffView";
import ModelPicker from "@/components/ModelPicker";
import Prerequisites from "@/components/Prerequisites";
import ReadingMap from "@/components/ReadingMap";
import ResearchToolkit from "@/components/ResearchToolkit";
import StudyDeck from "@/components/StudyDeck";
import RelationshipsGraph from "@/components/RelationshipsGraph";
import Timeline from "@/components/Timeline";
import {
  ClustersSection,
  ConsensusSection,
  OpenProblemsSection,
  ReadingOrderSection,
  SectionTitle,
  TensionsSection,
} from "@/components/Sections";

const EXAMPLES = [
  "retrieval-augmented generation",
  "diffusion policy learning",
  "mixture of experts",
  "LLM agents",
];

type View = "idle" | "running" | "results";

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [app, setApp] = useState<AppState | null>(null);
  const [search, setSearch] = useState<SearchDetail | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [view, setView] = useState<View>("idle");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [mapView, setMapView] = useState<"map" | "timeline">("map");
  const [scope, setScope] = useState<"search" | "all">("search");
  const [enriching, setEnriching] = useState(false);
  const [exportingReport, setExportingReport] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prefetchedRef = useRef<Set<string>>(new Set());

  const refresh = useCallback(async (searchId?: string | null) => {
    const state = await api.state();
    setApp(state);
    const id = searchId ?? state.latest_search_id;
    if (id) {
      setSearch(await api.searchDetail(id));
      return true;
    }
    setSearch(null);
    return false;
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setHealth(await api.health());
        const hasResults = await refresh();
        setView(hasResults ? "results" : "idle");
      } catch {
        setBackendDown(true);
      }
    })();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refresh]);

  const submit = async (topic: string) => {
    const trimmed = topic.trim();
    if (!trimmed || view === "running") return;
    setSubmitError(null);
    try {
      const { job_id } = await api.startSearch(trimmed);
      setJob({
        id: job_id,
        query: trimmed,
        status: "running",
        stages: [],
      } as unknown as Job);
      setView("running");
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const current = await api.job(job_id);
          setJob(current);
          if (current.status !== "running") {
            if (pollRef.current) clearInterval(pollRef.current);
            if (current.status === "done") {
              await refresh(current.search_id);
              setView("results");
              setQuery("");
            }
          }
        } catch {
          /* transient poll failure — keep polling */
        }
      }, 800);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    }
  };

  const toggleRead = async (paperId: string, read: boolean) => {
    setApp((previous) =>
      previous
        ? {
            ...previous,
            read: read
              ? [...previous.read, paperId]
              : previous.read.filter((id) => id !== paperId),
          }
        : previous,
    );
    try {
      const result = await api.setRead(paperId, read);
      setApp((previous) => (previous ? { ...previous, read: result.read } : previous));
    } catch {
      /* keep optimistic state; next refresh reconciles */
    }
  };

  const numberOf = (id: string) => (search ? search.paper_ids.indexOf(id) + 1 : 0);
  const paperCount = app ? Object.keys(app.papers).length : 0;
  const enrichedCount = app?.citations ? Object.keys(app.citations).length : 0;

  // "This search" narrows the map to the papers this search returned, grouped by
  // that search's own method clusters; "All papers" is the accumulated library.
  const mapData = useMemo(() => {
    if (!app) return null;
    if (scope === "all" || !search) {
      return {
        papers: app.papers,
        clusters: app.map.clusters,
        edges: app.map.edges,
        count: Object.keys(app.papers).length,
      };
    }
    const ids = new Set(search.paper_ids);
    return {
      papers: Object.fromEntries(
        Object.entries(app.papers).filter(([id]) => ids.has(id)),
      ),
      clusters: search.clusters.map((c) => ({
        name: c.name,
        paper_ids: c.paper_ids.filter((id) => ids.has(id)),
      })),
      edges: search.edges,
      count: search.paper_ids.length,
    };
  }, [app, search, scope]);

  // Deep dive is the slow part (~90s-4min). Once the paper the reader is on
  // finishes its own deep read, quietly start the next paper in that search's
  // reading order in the background, so it's already done by the time they
  // click it. Best-effort: errors are swallowed and a paper is only ever
  // queued once per session.
  const prefetchNextInOrder = useCallback(
    (afterPaperId: string) => {
      if (!search || !app) return;
      const order = search.reading_order;
      const index = order.findIndex((step) => step.paper_id === afterPaperId);
      if (index === -1 || index + 1 >= order.length) return;
      const nextId = order[index + 1].paper_id;
      if (
        prefetchedRef.current.has(nextId) ||
        (app.deep_read ?? []).includes(nextId) ||
        !app.papers[nextId]
      ) {
        return;
      }
      prefetchedRef.current.add(nextId);
      api
        .runningDeepJob(nextId)
        .then((running) => {
          if ("id" in running && running.status === "running") return; // already in flight
          return api.startDeepDive(nextId);
        })
        .catch(() => {
          prefetchedRef.current.delete(nextId); // let a later trigger retry
        });
    },
    [search, app],
  );

  // Covers re-opening a paper that was already deep-read in an earlier
  // session — onDeepDone won't fire again, so this is the only trigger.
  useEffect(() => {
    if (selected && (app?.deep_read ?? []).includes(selected)) {
      prefetchNextInOrder(selected);
    }
  }, [selected, app?.deep_read, prefetchNextInOrder]);

  const enrich = async () => {
    setEnriching(true);
    setSubmitError(null);
    try {
      await api.enrich();
      setApp(await api.state());
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setEnriching(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 pb-24 sm:px-6">
      {/* ---------------------------------------------------------------- */}
      <header className="flex flex-col gap-3 border-b border-stone-200 py-4 sm:flex-row sm:items-center">
        <div className="shrink-0 sm:w-56">
          <h1 className="text-[15px] font-semibold tracking-tight text-stone-900">
            Research Copilot
          </h1>
          <p className="text-xs text-stone-400">arXiv search &amp; summarization</p>
        </div>
        <form
          className="flex flex-1 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            submit(query);
          }}
        >
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search an ML research topic — e.g. retrieval-augmented generation"
            disabled={view === "running"}
            className="w-full rounded-lg border border-stone-300 bg-white px-3.5 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none disabled:bg-stone-50 disabled:text-stone-400"
          />
          <button
            type="submit"
            disabled={view === "running" || !query.trim()}
            className="shrink-0 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
          >
            Map it
          </button>
        </form>
        <ModelPicker
          health={health}
          busy={view === "running"}
          onSwitched={setHealth}
        />
      </header>
      <p className="pt-2 text-xs text-stone-400">Cross-paper synthesis across your results</p>

      {/* Banners ---------------------------------------------------------- */}
      {backendDown ? (
        <div className="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Backend not reachable. Start it with{" "}
          <code className="rounded bg-red-100 px-1 font-mono text-xs">
            uvicorn main:app --port 8321
          </code>{" "}
          in <code className="rounded bg-red-100 px-1 font-mono text-xs">backend/</code>, then
          reload this page.
        </div>
      ) : null}
      {health && !health.ready ? (
        <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span className="font-medium">Setup:</span>{" "}
          {health.detail ?? `The ${health.provider} provider isn't ready.`}
        </div>
      ) : null}
      {health?.ready && health.embeddings_ready === false ? (
        <div className="mt-6 rounded-xl border border-stone-200 bg-stone-50 px-4 py-3 text-sm text-stone-600">
          <span className="font-medium">Chat-with-paper unavailable:</span>{" "}
          {health.embeddings_detail} Everything else works.
        </div>
      ) : null}
      {submitError ? (
        <div className="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {submitError}
        </div>
      ) : null}

      {/* Running ---------------------------------------------------------- */}
      {view === "running" && job ? (
        <PipelineCard
          job={job}
          papersPerSearch={health?.papers_per_search ?? 8}
          onDismiss={() => setView(search ? "results" : "idle")}
        />
      ) : null}

      {/* Empty state ------------------------------------------------------ */}
      {view === "idle" && !backendDown ? (
        <div className="mx-auto mt-24 max-w-md text-center">
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl border border-stone-200 bg-white text-stone-400 shadow-sm">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
          </div>
          <h2 className="mt-4 text-base font-semibold text-stone-900">
            Search a topic to get started
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-stone-500">
            Enter a machine learning research area above. We&apos;ll retrieve the most relevant
            arXiv papers, rank them, and generate structured summaries you can read here.
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => {
                  setQuery(example);
                  submit(example);
                }}
                className="rounded-full border border-stone-200 bg-white px-3 py-1.5 text-xs text-stone-600 transition hover:border-stone-400 hover:text-stone-900"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* Results ---------------------------------------------------------- */}
      {view === "results" && app && search ? (
        <main className="mt-6 space-y-10">
          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-stone-500">
                Your <span className="font-medium text-stone-800">{search.title}</span> reading
                map · {mapData?.count ?? paperCount} paper
                {(mapData?.count ?? paperCount) === 1 ? "" : "s"}
                {scope === "search" ? ` of ${paperCount} collected` : ""}
                {enrichedCount > 0 ? " · real citation data" : ""}
              </p>
              <div className="flex items-center gap-2">
                <div className="flex rounded-lg border border-stone-200 bg-white p-0.5">
                  {(
                    [
                      ["search", "This search"],
                      ["all", "All papers"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      onClick={() => setScope(value)}
                      title={
                        value === "search"
                          ? "Only the papers this search returned"
                          : "Every paper collected across all searches"
                      }
                      className={
                        scope === value
                          ? "rounded-md bg-stone-900 px-2.5 py-1 text-xs font-medium text-white"
                          : "rounded-md px-2.5 py-1 text-xs text-stone-600 transition hover:bg-stone-100"
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
                {enrichedCount < paperCount ? (
                  <button
                    onClick={enrich}
                    disabled={enriching}
                    className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-400 disabled:opacity-50"
                  >
                    {enriching ? "Fetching citations…" : "↻ Load citation data"}
                  </button>
                ) : null}
                <button
                  onClick={async () => {
                    setExportingReport(true);
                    setSubmitError(null);
                    try {
                      await downloadFile(
                        `/api/searches/${search.id}/report`,
                        {},
                        `${search.id}-field-report.md`,
                      );
                    } catch (e) {
                      setSubmitError(e instanceof Error ? e.message : String(e));
                    } finally {
                      setExportingReport(false);
                    }
                  }}
                  disabled={exportingReport}
                  title="Overview, clusters, reading order and flashcard progress as one Markdown file"
                  className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-700 transition hover:border-stone-400 disabled:opacity-50"
                >
                  {exportingReport ? "Exporting…" : "⤓ Field report"}
                </button>
                <div className="flex rounded-lg border border-stone-200 bg-white p-0.5">
                  {(["map", "timeline"] as const).map((view) => (
                    <button
                      key={view}
                      onClick={() => setMapView(view)}
                      className={
                        mapView === view
                          ? "rounded-md bg-stone-900 px-2.5 py-1 text-xs font-medium text-white"
                          : "rounded-md px-2.5 py-1 text-xs text-stone-600 transition hover:bg-stone-100"
                      }
                    >
                      {view === "map" ? "Map" : "Timeline"}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {mapView === "map" ? (
              <ReadingMap
                papers={mapData?.papers ?? app.papers}
                clusters={mapData?.clusters ?? app.map.clusters}
                edges={mapData?.edges ?? app.map.edges}
                read={app.read}
                citations={app.citations}
                seminal={app.map.seminal}
                onSelect={setSelected}
              />
            ) : (
              <Timeline
                papers={mapData?.papers ?? app.papers}
                clusters={mapData?.clusters ?? app.map.clusters}
                citations={app.citations}
                read={app.read}
                onSelect={setSelected}
              />
            )}
            {app.searches.length > 1 ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-stone-400">Searches:</span>
                {app.searches.map((meta) => (
                  <button
                    key={meta.id}
                    onClick={async () => setSearch(await api.searchDetail(meta.id))}
                    className={
                      meta.id === search.id
                        ? "rounded-full border border-stone-900 bg-stone-900 px-3 py-1 text-xs text-white"
                        : "rounded-full border border-stone-200 bg-white px-3 py-1 text-xs text-stone-600 transition hover:border-stone-400"
                    }
                  >
                    {meta.title || meta.query}
                  </button>
                ))}
              </div>
            ) : null}
          </section>

          <section className="rounded-xl border border-stone-200 bg-white p-5">
            <p className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
              Field overview · {search.paper_ids.length} papers ·{" "}
              {search.created_at.slice(0, 10)}
            </p>
            <h2 className="mt-1 text-lg font-semibold text-stone-900">{search.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-stone-600">{search.overview}</p>
          </section>

          <section className="space-y-3">
            <SectionTitle icon="◫">Method clusters</SectionTitle>
            <ClustersSection
              clusters={search.clusters}
              papers={app.papers}
              numberOf={numberOf}
              onSelect={setSelected}
            />
          </section>

          <section className="space-y-3">
            <SectionTitle icon="≡">Papers</SectionTitle>
            <PaperList
              paperIds={search.paper_ids}
              papers={app.papers}
              extractions={app.extractions}
              read={app.read}
              deepRead={app.deep_read}
              onSelect={setSelected}
              onToggleRead={toggleRead}
            />
          </section>

          <section className="space-y-3 rounded-xl border border-stone-200 bg-white p-5">
            <SectionTitle icon="⌥">Paper relationships</SectionTitle>
            <RelationshipsGraph
              paperIds={search.paper_ids}
              papers={app.papers}
              edges={search.edges}
              onSelect={setSelected}
            />
          </section>

          {search.tensions.length > 0 ? (
            <section className="space-y-3">
              <SectionTitle icon="⚠">Tensions</SectionTitle>
              <TensionsSection
                tensions={search.tensions}
                papers={app.papers}
                numberOf={numberOf}
                onSelect={setSelected}
              />
            </section>
          ) : null}

          {search.consensus.length > 0 ? (
            <section className="space-y-3">
              <SectionTitle icon="✓">Consensus</SectionTitle>
              <ConsensusSection consensus={search.consensus} />
            </section>
          ) : null}

          {search.open_problems.length > 0 ? (
            <section className="space-y-3">
              <SectionTitle icon="?">Open problems</SectionTitle>
              <OpenProblemsSection
                problems={search.open_problems}
                papers={app.papers}
                numberOf={numberOf}
                onSelect={setSelected}
              />
            </section>
          ) : null}

          {enrichedCount > 0 ? (
            <section className="space-y-3">
              <SectionTitle icon="⚑">Read these first</SectionTitle>
              <Prerequisites
                papers={app.papers}
                enrichedCount={enrichedCount}
                searchId={search.id}
                onAdded={() => {
                  // Refresh the search too, not just the library — the added
                  // paper joins this search's list, graph and reading order.
                  refresh(search.id).catch(() => {});
                }}
              />
            </section>
          ) : null}

          <section className="space-y-3">
            <SectionTitle icon="◷">What&apos;s new in this field</SectionTitle>
            <FieldDigest
              key={`digest-${search.id}`}
              searchId={search.id}
              papers={app.papers}
              onSelect={setSelected}
              onUpdated={() => {
                api.state().then(setApp).catch(() => {});
              }}
            />
          </section>

          {app.searches.length > 1 ? (
            <section className="space-y-3">
              <SectionTitle icon="⇄">Compare past searches</SectionTitle>
              <SearchDiffView searches={app.searches} onSelectPaper={setSelected} />
            </section>
          ) : null}

          <section className="space-y-3">
            <SectionTitle icon="✎">Study deck</SectionTitle>
            <StudyDeck
              key={`deck-${search.id}`}
              searchId={search.id}
              paperIds={search.paper_ids}
              clusters={search.clusters}
              papers={app.papers}
              read={app.read}
            />
          </section>

          <section className="space-y-3">
            <SectionTitle icon="⌗">Research toolkit</SectionTitle>
            <ResearchToolkit
              key={search.id}
              paperIds={search.paper_ids}
              papers={app.papers}
              topic={search.title || search.query}
            />
          </section>

          <section className="space-y-3">
            <SectionTitle icon="→">Suggested reading order</SectionTitle>
            <ReadingOrderSection
              readingOrder={search.reading_order}
              papers={app.papers}
              read={app.read}
              onSelect={setSelected}
            />
          </section>
        </main>
      ) : null}

      {/* Paper workspace -------------------------------------------------- */}
      {selected && app?.papers[selected] ? (
        <PaperWorkspace
          paper={app.papers[selected]}
          extraction={app.extractions[selected]}
          number={numberOf(selected) || undefined}
          isRead={app.read.includes(selected)}
          hasDeep={(app.deep_read ?? []).includes(selected)}
          onToggleRead={(read) => toggleRead(selected, read)}
          onDeepDone={() => {
            api
              .state()
              .then(setApp)
              .then(() => prefetchNextInOrder(selected))
              .catch(() => {});
          }}
          onRemoved={() => {
            setSelected(null);
            // Removal can change the current search's paper list, clusters,
            // edges and reading order, not just the library.
            refresh(search?.id).catch(() => {});
          }}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}
