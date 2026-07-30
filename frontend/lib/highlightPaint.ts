/**
 * Drawing saved highlights over the text.
 *
 * Uses the CSS Custom Highlight API, which paints ranges without touching the
 * DOM. That matters here: the reading pane is React-rendered, and the usual
 * trick of wrapping matches in <mark> elements means mutating a tree React
 * believes it owns — which it then overwrites on the next render, or worse,
 * throws on. Registered ranges survive scrolling and reflow on their own,
 * with no repositioning code.
 *
 * Where the API is missing the highlights simply do not paint. They are still
 * stored, still listed, and still openable from the notebook — a reader on an
 * older iPad loses the shading, not the annotations.
 */

import { locateAnchor, type TextAnchor } from "./anchoring";

/** Name registered with CSS.highlights; matched by ::highlight() in globals.css. */
const REGISTRY_KEY = "rc-highlight";

interface HighlightLike extends TextAnchor {
  id: string;
}

export function highlightPaintingSupported(): boolean {
  return typeof CSS !== "undefined" && !!CSS.highlights && typeof Highlight !== "undefined";
}

/**
 * Paint every anchor that can still be found inside `root`.
 *
 * Returns the ids that could not be located, so the caller can tell the reader
 * which annotations have come loose from their text instead of quietly
 * dropping them.
 */
export function paintHighlights(root: Node | null, highlights: HighlightLike[]): string[] {
  if (!highlightPaintingSupported()) return [];
  if (!root) {
    CSS.highlights.delete(REGISTRY_KEY);
    return [];
  }

  const ranges: Range[] = [];
  const orphaned: string[] = [];
  for (const highlight of highlights) {
    const range = locateAnchor(root, highlight);
    if (range) ranges.push(range);
    else orphaned.push(highlight.id);
  }

  if (ranges.length === 0) CSS.highlights.delete(REGISTRY_KEY);
  else CSS.highlights.set(REGISTRY_KEY, new Highlight(...ranges));

  return orphaned;
}

/** Clear the painting — on unmount, or when switching papers. */
export function clearHighlights(): void {
  if (highlightPaintingSupported()) CSS.highlights.delete(REGISTRY_KEY);
}

/**
 * Scroll a saved highlight into view and flash it.
 *
 * The flash is a second, separately-registered range rather than a class on
 * the element, for the same reason as above: there is no element to put a
 * class on, only a position in text.
 */
export function revealHighlight(root: Node | null, anchor: TextAnchor): boolean {
  if (!root) return false;
  const range = locateAnchor(root, anchor);
  if (!range) return false;

  const rect = range.getBoundingClientRect();
  if (rect.height || rect.width) {
    const target = range.startContainer.parentElement;
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  if (highlightPaintingSupported()) {
    CSS.highlights.set("rc-highlight-flash", new Highlight(range));
    window.setTimeout(() => CSS.highlights.delete("rc-highlight-flash"), 1600);
  }
  return true;
}
