/**
 * Finding a marked passage again after the page has re-rendered.
 *
 * The obvious anchor — "third paragraph, characters 40 to 90" — breaks the
 * first time anything above it changes, and breaks silently: the highlight
 * still lands somewhere, just on the wrong words. This instead stores the
 * quoted text plus a little of what surrounds it, and searches for that. If
 * the text is still there it is found wherever it moved to; if it genuinely
 * changed, the search fails and the highlight is reported as orphaned rather
 * than pointing at something the reader never marked.
 *
 * The surrounding context is only there to disambiguate. "the model" occurs
 * dozens of times in a paper; the words either side of it usually do not.
 */

/** How much text either side to remember. Long enough to disambiguate a
 *  repeated phrase, short enough that an edit nearby does not break it. */
const CONTEXT = 40;

export interface TextAnchor {
  quote: string;
  prefix: string;
  suffix: string;
}

interface FlatText {
  text: string;
  /** Each text node with where it starts in `text`. */
  pieces: { node: Text; start: number }[];
}

/**
 * Marks a subtree as not part of the document being annotated.
 *
 * Anything that displays a highlight's own text — the list of saved
 * highlights, the notebook — must carry this. Without it those panels are
 * themselves searchable, so every anchor matches the copy of itself sitting in
 * the sidebar instead of the passage in the paper, and highlights appear to
 * work while pointing at the wrong thing entirely.
 */
export const NO_ANCHOR_ATTR = "data-no-anchor";

/** The root's visible text as one string, with a map back to its text nodes. */
function flatten(root: Node): FlatText {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return node.parentElement?.closest(`[${NO_ANCHOR_ATTR}]`)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT;
    },
  });
  const pieces: { node: Text; start: number }[] = [];
  let text = "";
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const textNode = node as Text;
    pieces.push({ node: textNode, start: text.length });
    text += textNode.data;
  }
  return { text, pieces };
}

/** Flat offset of a (node, offset) position, or null if it isn't under root. */
function flatOffsetOf(flat: FlatText, node: Node, offset: number): number | null {
  for (const piece of flat.pieces) {
    if (piece.node === node) return piece.start + offset;
  }
  // A position can land on an element rather than a text node — when a
  // selection ends at a paragraph boundary, for instance. Fall back to the
  // first text node inside it.
  if (node.nodeType === Node.ELEMENT_NODE) {
    const child = (node as Element).childNodes[offset] ?? null;
    if (child) {
      for (const piece of flat.pieces) {
        if (piece.node === child || child.contains(piece.node)) return piece.start;
      }
    }
  }
  return null;
}

/** Turn a flat offset back into a (node, offset) pair. */
function positionAt(flat: FlatText, offset: number): { node: Text; offset: number } | null {
  for (let i = flat.pieces.length - 1; i >= 0; i--) {
    const piece = flat.pieces[i];
    if (offset >= piece.start) {
      return { node: piece.node, offset: Math.min(offset - piece.start, piece.node.data.length) };
    }
  }
  return null;
}

/** Describe a live selection so it can be found again later. */
export function describeRange(root: Node, range: Range): TextAnchor | null {
  const flat = flatten(root);
  const start = flatOffsetOf(flat, range.startContainer, range.startOffset);
  const end = flatOffsetOf(flat, range.endContainer, range.endOffset);
  if (start === null || end === null || end <= start) return null;
  return {
    quote: flat.text.slice(start, end),
    prefix: flat.text.slice(Math.max(0, start - CONTEXT), start),
    suffix: flat.text.slice(end, end + CONTEXT),
  };
}

/** How many characters two strings share, counting inward from the join. */
function overlapFromEnd(a: string, b: string): number {
  let n = 0;
  while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n++;
  return n;
}

function overlapFromStart(a: string, b: string): number {
  let n = 0;
  while (n < a.length && n < b.length && a[n] === b[n]) n++;
  return n;
}

/**
 * Find the anchored passage inside `root`, or null if it is no longer there.
 *
 * Every occurrence of the quote is scored by how much of the remembered
 * context still matches around it, and the best wins. A single occurrence is
 * returned even with no context match — the words are the anchor, the context
 * only breaks ties.
 */
export function locateAnchor(root: Node, anchor: TextAnchor): Range | null {
  if (!anchor.quote) return null;
  const flat = flatten(root);

  const candidates: number[] = [];
  let at = flat.text.indexOf(anchor.quote);
  while (at !== -1) {
    candidates.push(at);
    at = flat.text.indexOf(anchor.quote, at + 1);
  }
  if (candidates.length === 0) return null;

  let bestStart = candidates[0];
  if (candidates.length > 1) {
    let bestScore = -1;
    for (const start of candidates) {
      const before = flat.text.slice(Math.max(0, start - CONTEXT), start);
      const after = flat.text.slice(start + anchor.quote.length, start + anchor.quote.length + CONTEXT);
      const score = overlapFromEnd(before, anchor.prefix) + overlapFromStart(after, anchor.suffix);
      if (score > bestScore) {
        bestScore = score;
        bestStart = start;
      }
    }
  }

  const from = positionAt(flat, bestStart);
  const to = positionAt(flat, bestStart + anchor.quote.length);
  if (!from || !to) return null;

  const range = document.createRange();
  try {
    range.setStart(from.node, from.offset);
    range.setEnd(to.node, to.offset);
  } catch {
    return null; // offsets went stale between flatten and here
  }
  return range;
}
