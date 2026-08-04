"use client";

import { useRef, useState } from "react";
import { api } from "@/lib/api";

interface Props {
  disabled?: boolean;
  onUploaded: (paperId: string) => void;
}

/**
 * A paper that isn't on arXiv â€” a camera-ready, something a professor
 * emailed, a workshop paper never posted. Extracted text flows through the
 * exact same pipeline as an arXiv result: extraction, clustering into the
 * global map, deep dive, appraisal. Only authors/venue are left blank
 * rather than guessed â€” unreliable to parse from arbitrary PDF layouts.
 */
export default function UploadPdf({ disabled, onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = async (file: File) => {
    const looksLikePdf =
      file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!looksLikePdf) {
      setError("Only PDF files are supported.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.uploadPdf(file);
      if (result.added && result.paper_id) {
        onUploaded(result.paper_id);
      } else {
        setError(result.reason ?? "Could not add this paper.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) handleFile(file);
        }}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || busy}
        title="Add a paper that isn't on arXiv â€” upload any PDF"
        className="shrink-0 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-medium text-stone-700 transition hover:border-stone-400 disabled:opacity-40"
      >
        {busy ? "Reading PDFâ€¦" : "â¤’ Upload PDF"}
      </button>
      {error ? <p className="max-w-[240px] text-right text-xs text-red-600">{error}</p> : null}
    </div>
  );
}

