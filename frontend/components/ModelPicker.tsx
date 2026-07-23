"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Engine, Health, OpenRouterUsage } from "@/lib/types";

interface Props {
  health: Health | null;
  busy: boolean;
  onSwitched: (health: Health) => void;
}

/**
 * Header control for choosing which model runs every LLM call.
 * The choice is persisted server-side, so it survives a reload/restart.
 */
export default function ModelPicker({ health, busy, onSwitched }: Props) {
  const [engines, setEngines] = useState<Engine[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [usage, setUsage] = useState<OpenRouterUsage | null>(null);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(() => {
    api
      .engines()
      .then((result) => {
        setEngines(result.engines);
        setActive(result.active);
        setUsage(result.openrouter_usage ?? null);
      })
      .catch(() => setEngines([]));
  }, []);

  useEffect(load, [load]);

  // The per-minute rate limit is enforced live and never surfaces here; the
  // per-day cap has no such backpressure, so keep usage roughly fresh as the
  // session goes on rather than only reading it once at mount.
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  // Keep in sync when health is refreshed elsewhere.
  useEffect(() => {
    if (health?.engine) setActive(health.engine);
  }, [health?.engine]);

  // Close the menu on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const choose = async (engine: Engine) => {
    if (engine.id === active) {
      setOpen(false);
      return;
    }
    setSwitching(true);
    setError(null);
    try {
      const updated = await api.selectEngine(engine.id);
      setActive(engine.id);
      onSwitched(updated);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSwitching(false);
    }
  };

  if (engines.length === 0) return null;

  const current = engines.find((e) => e.id === active);
  const disabled = busy || switching;

  return (
    <div className="relative" ref={boxRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title={
          busy
            ? "Finish the running job before switching models"
            : current?.blurb ?? "Choose the model"
        }
        className="flex items-center gap-2 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-700 transition hover:border-stone-400 disabled:opacity-50"
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${
            switching
              ? "animate-pulse-dot bg-[#2a78d6]"
              : health?.ready === false
                ? "bg-[#d03b3b]"
                : current?.provider === "ollama"
                  ? "bg-[#0ca30c]"
                  : "bg-[#2a78d6]"
          }`}
        />
        <span className="font-medium">{current?.label ?? "Model"}</span>
        <span className="text-xs text-stone-400">
          {current?.provider === "ollama" ? "local" : "hosted"}
        </span>
        {current?.provider === "openrouter" && usage?.near_cap ? (
          <span
            title={`${usage.used}/${usage.cap} OpenRouter requests used today — close to the free-tier daily cap`}
            className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700"
          >
            ⚠ {usage.remaining} left today
          </span>
        ) : null}
        <span aria-hidden className="text-stone-400">
          ▾
        </span>
      </button>

      {open ? (
        <div className="absolute right-0 z-50 mt-1.5 w-80 rounded-xl border border-stone-200 bg-white p-1.5 shadow-lg">
          {engines.map((engine) => {
            const isActive = engine.id === active;
            return (
              <button
                key={engine.id}
                onClick={() => choose(engine)}
                disabled={switching}
                className={`w-full rounded-lg p-2.5 text-left transition disabled:opacity-50 ${
                  isActive ? "bg-stone-100" : "hover:bg-stone-50"
                }`}
              >
                <span className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${
                      engine.provider === "ollama" ? "bg-[#0ca30c]" : "bg-[#2a78d6]"
                    }`}
                  />
                  <span className="text-sm font-medium text-stone-900">{engine.label}</span>
                  {isActive ? (
                    <span className="ml-auto text-xs text-stone-500">active</span>
                  ) : null}
                </span>
                <span className="mt-1 block pl-4 text-xs leading-relaxed text-stone-500">
                  {engine.blurb}
                </span>
                <span className="mt-0.5 block pl-4 font-mono text-[10px] text-stone-400">
                  {engine.model}
                </span>
                {engine.provider === "openrouter" && usage ? (
                  <span
                    className={
                      usage.near_cap
                        ? "mt-1 block pl-4 text-[10px] font-medium text-amber-600"
                        : "mt-1 block pl-4 text-[10px] text-stone-400"
                    }
                  >
                    {usage.near_cap ? "⚠ " : ""}
                    {usage.used}/{usage.cap} requests used today
                    {usage.near_cap ? " — close to the free-tier daily cap" : ""}
                  </span>
                ) : null}
              </button>
            );
          })}
          <p className="px-2.5 py-1.5 text-[11px] leading-relaxed text-stone-400">
            Applies to every new search, deep read, quiz and chat. Work already
            saved to disk is kept as-is.
          </p>
        </div>
      ) : null}

      {error ? (
        <p className="absolute right-0 top-full mt-1 w-72 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
