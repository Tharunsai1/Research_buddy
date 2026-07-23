"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, downloadFile } from "@/lib/api";
import type { Flashcard, Grade, Paper } from "@/lib/types";

interface Props {
  paperIds: string[];
  papers: Record<string, Paper>;
  read: string[];
}

type Mode = "browse" | "quiz";

const KIND_STYLE: Record<string, string> = {
  definition: "bg-blue-50 text-blue-700 border-blue-200",
  concept: "bg-violet-50 text-violet-700 border-violet-200",
  result: "bg-emerald-50 text-emerald-700 border-emerald-200",
  critique: "bg-amber-50 text-amber-800 border-amber-200",
};

const VERDICT_STYLE: Record<Grade["verdict"], string> = {
  correct: "border-emerald-200 bg-emerald-50 text-emerald-800",
  partial: "border-amber-200 bg-amber-50 text-amber-900",
  incorrect: "border-red-200 bg-red-50 text-red-800",
};

export default function StudyDeck({ paperIds, papers, read }: Props) {
  const [mode, setMode] = useState<Mode>("browse");
  const [cards, setCards] = useState<Flashcard[]>([]);
  const [dueCount, setDueCount] = useState(0);
  const [cardPapers, setCardPapers] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Set<string>>(new Set());

  // quiz state
  const [queue, setQueue] = useState<Flashcard[]>([]);
  const [position, setPosition] = useState(0);
  const [answer, setAnswer] = useState("");
  const [grade, setGrade] = useState<Grade | null>(null);
  const [session, setSession] = useState({ correct: 0, partial: 0, incorrect: 0 });

  const refresh = useCallback(async () => {
    try {
      const result = await api.cards();
      setCards(result.cards);
      setDueCount(result.due);
      setCardPapers(result.papers);
    } catch {
      /* backend may not have any cards yet */
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const missing = useMemo(
    () => paperIds.filter((id) => !cardPapers.includes(id)),
    [paperIds, cardPapers],
  );

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      for (const [index, id] of missing.entries()) {
        setProgress(`Writing cards ${index + 1}/${missing.length} · ${papers[id]?.title.slice(0, 40)}…`);
        await api.makeCards(id);
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setProgress("");
    }
  };

  const startQuiz = async (dueOnly: boolean) => {
    setError(null);
    try {
      const result = await api.cards({ dueOnly });
      const pool = result.cards.filter((c) => paperIds.includes(c.paper_id));
      if (pool.length === 0) {
        setError(
          dueOnly
            ? "Nothing is due right now — come back later, or quiz the whole deck."
            : "No cards yet. Generate some first.",
        );
        return;
      }
      // Shuffle so repeated sessions don't drill in the same order.
      const shuffled = [...pool].sort(() => Math.random() - 0.5);
      setQueue(shuffled);
      setPosition(0);
      setAnswer("");
      setGrade(null);
      setSession({ correct: 0, partial: 0, incorrect: 0 });
      setMode("quiz");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const current = queue[position];
    if (!current || !answer.trim() || busy) return;
    setBusy(true);
    setError(null);
    setProgress("Grading your answer…");
    try {
      const result = await api.gradeCard(current.id, answer);
      setGrade(result.grade);
      setSession((s) => ({ ...s, [result.grade.verdict]: s[result.grade.verdict] + 1 }));
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setProgress("");
    }
  };

  const next = () => {
    setGrade(null);
    setAnswer("");
    setPosition((p) => p + 1);
  };

  const toggleReveal = (id: string) =>
    setRevealed((current) => {
      const copy = new Set(current);
      if (copy.has(id)) copy.delete(id);
      else copy.add(id);
      return copy;
    });

  const deckCards = cards.filter((c) => paperIds.includes(c.paper_id));
  const deckDue = deckCards.filter(
    (c) => !c.due || new Date(c.due) <= new Date(),
  ).length;
  const current = queue[position];
  const finished = mode === "quiz" && position >= queue.length;

  return (
    <div className="space-y-4">
      {error ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
          {error}
        </div>
      ) : null}

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2">
        {missing.length > 0 ? (
          <button
            onClick={generate}
            disabled={busy}
            className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
          >
            Generate cards for {missing.length} paper{missing.length === 1 ? "" : "s"}
          </button>
        ) : null}
        {deckCards.length > 0 ? (
          <>
            <button
              onClick={() => startQuiz(true)}
              disabled={busy}
              className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
            >
              Quiz me{deckDue > 0 ? ` · ${deckDue} due` : ""}
            </button>
            <button
              onClick={() => startQuiz(false)}
              disabled={busy}
              className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm font-medium text-stone-700 transition hover:border-stone-400 disabled:opacity-40"
            >
              Quiz all {deckCards.length}
            </button>
            <button
              onClick={() =>
                downloadFile(
                  "/api/cards/anki",
                  { paper_ids: paperIds },
                  "research-copilot-cards.txt",
                ).catch((e) => setError(String(e)))
              }
              className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm font-medium text-stone-700 transition hover:border-stone-400"
            >
              ⤓ Anki
            </button>
            {mode === "quiz" ? (
              <button
                onClick={() => setMode("browse")}
                className="rounded-lg border border-stone-200 bg-white px-3 py-2 text-sm text-stone-600 transition hover:border-stone-400"
              >
                Exit quiz
              </button>
            ) : null}
          </>
        ) : null}
        {busy ? (
          <span className="flex items-center gap-2 text-sm text-stone-500">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-stone-200 border-t-stone-500" />
            {progress}
          </span>
        ) : null}
      </div>

      {deckCards.length > 0 && mode === "browse" ? (
        <p className="text-xs text-stone-400">
          {deckCards.length} cards across {new Set(deckCards.map((c) => c.paper_id)).size}{" "}
          papers · {deckDue} due now · {read.length} papers marked read
        </p>
      ) : null}

      {/* ---------------- Quiz ---------------- */}
      {mode === "quiz" ? (
        finished ? (
          <div className="rounded-xl border border-stone-200 bg-white p-6 text-center">
            <p className="text-base font-semibold text-stone-900">Session complete</p>
            <p className="mt-1 text-sm text-stone-500">
              {queue.length} card{queue.length === 1 ? "" : "s"} reviewed
            </p>
            <div className="mt-4 flex justify-center gap-3">
              {(["correct", "partial", "incorrect"] as const).map((key) => (
                <div key={key} className="rounded-lg border border-stone-200 px-4 py-2">
                  <p className="text-xl font-semibold text-stone-900">{session[key]}</p>
                  <p className="text-xs capitalize text-stone-500">{key}</p>
                </div>
              ))}
            </div>
            <button
              onClick={() => setMode("browse")}
              className="mt-5 rounded-lg border border-stone-200 bg-white px-4 py-2 text-sm font-medium text-stone-700 transition hover:border-stone-400"
            >
              Back to deck
            </button>
          </div>
        ) : current ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-stone-400">
              <span>
                Card {position + 1} of {queue.length}
              </span>
              <span className="truncate">{papers[current.paper_id]?.title.slice(0, 54)}</span>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-stone-100">
              <div
                className="h-full bg-stone-900 transition-all"
                style={{ width: `${(position / queue.length) * 100}%` }}
              />
            </div>

            <div className="rounded-xl border border-stone-200 bg-white p-5">
              <span
                className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                  KIND_STYLE[current.kind] ?? "border-stone-200 bg-stone-50 text-stone-600"
                }`}
              >
                {current.kind}
              </span>
              <p className="mt-3 text-[17px] font-medium leading-snug text-stone-900">
                {current.question}
              </p>

              <form onSubmit={submit} className="mt-4">
                <textarea
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  disabled={grade !== null || busy}
                  rows={4}
                  placeholder="Answer in your own words — you'll get partial credit for the right idea."
                  className="w-full rounded-lg border border-stone-300 bg-white px-3.5 py-2.5 text-sm text-stone-900 placeholder:text-stone-400 focus:border-stone-500 focus:outline-none disabled:bg-stone-50"
                />
                {grade === null ? (
                  <button
                    type="submit"
                    disabled={busy || !answer.trim()}
                    className="mt-2 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-stone-700 disabled:opacity-40"
                  >
                    Check answer
                  </button>
                ) : null}
              </form>

              {grade ? (
                <div className="mt-4 space-y-3">
                  <div className={`rounded-xl border p-4 ${VERDICT_STYLE[grade.verdict]}`}>
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-semibold capitalize">{grade.verdict}</p>
                      <p className="font-mono text-sm">{grade.score}/100</p>
                    </div>
                    <p className="mt-1.5 text-sm leading-relaxed">{grade.feedback}</p>
                    {grade.missed.length > 0 ? (
                      <ul className="mt-2 space-y-1">
                        {grade.missed.map((item, index) => (
                          <li key={index} className="flex gap-2 text-sm">
                            <span>·</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                  <div className="rounded-xl bg-stone-50 p-4">
                    <p className="font-mono text-[11px] uppercase tracking-widest text-stone-400">
                      Reference answer
                    </p>
                    <p className="mt-1 text-sm leading-relaxed text-stone-700">
                      {current.answer}
                    </p>
                  </div>
                  <button
                    onClick={next}
                    className="w-full rounded-lg bg-stone-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-stone-700"
                  >
                    {position + 1 >= queue.length ? "Finish session" : "Next card →"}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        ) : null
      ) : null}

      {/* ---------------- Browse ---------------- */}
      {mode === "browse" && deckCards.length > 0 ? (
        <ul className="space-y-2">
          {deckCards.map((card) => (
            <li key={card.id} className="rounded-xl border border-stone-200 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                      KIND_STYLE[card.kind] ?? "border-stone-200 bg-stone-50 text-stone-600"
                    }`}
                  >
                    {card.kind}
                  </span>
                  <p className="mt-1.5 text-sm font-medium text-stone-900">{card.question}</p>
                  {revealed.has(card.id) ? (
                    <p className="mt-1.5 text-sm leading-relaxed text-stone-600">{card.answer}</p>
                  ) : null}
                  <p className="mt-1 text-[11px] text-stone-400">
                    {card.reps > 0
                      ? `reviewed ${card.reps}× · next ${card.due}${
                          card.last_score != null ? ` · last ${card.last_score}/100` : ""
                        }`
                      : "not reviewed yet"}
                  </p>
                </div>
                <button
                  onClick={() => toggleReveal(card.id)}
                  className="shrink-0 rounded-lg border border-stone-200 px-2.5 py-1 text-xs text-stone-600 transition hover:border-stone-400"
                >
                  {revealed.has(card.id) ? "Hide" : "Show"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {deckCards.length === 0 && missing.length === 0 && !busy ? (
        <p className="text-sm text-stone-500">No papers in this search to make cards from.</p>
      ) : null}
    </div>
  );
}
