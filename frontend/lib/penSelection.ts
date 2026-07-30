/**
 * Text selection driven by an Apple Pencil.
 *
 * Safari does not select text when you drag a pen across a page — it scrolls,
 * the same as a finger. So dragging to highlight has to be built: watch the
 * pointer, ask the document which character sits under the tip, and extend a
 * Range as the tip moves.
 *
 * Kept out of the component because none of it is React: it is pointer
 * plumbing plus two vendor-split DOM calls, and it is far easier to reason
 * about (and to swap when WebKit changes) on its own.
 */

export interface CaretPoint {
  node: Node;
  offset: number;
}

/**
 * Which character sits at these viewport coordinates.
 *
 * Two APIs do this and browsers disagree on which they ship:
 * `caretRangeFromPoint` is the older WebKit one and is what Safari has had for
 * years; `caretPositionFromPoint` is the standard and what Firefox has always
 * had. Safari only gained the standard one recently, so trying WebKit's first
 * is what makes this work on an iPad that has not been updated.
 */
export function caretAt(x: number, y: number): CaretPoint | null {
  const doc = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
    caretPositionFromPoint?: (
      x: number,
      y: number,
    ) => { offsetNode: Node; offset: number } | null;
  };

  if (typeof doc.caretRangeFromPoint === "function") {
    const range = doc.caretRangeFromPoint(x, y);
    if (range) return { node: range.startContainer, offset: range.startOffset };
  }
  if (typeof doc.caretPositionFromPoint === "function") {
    const position = doc.caretPositionFromPoint(x, y);
    if (position) return { node: position.offsetNode, offset: position.offset };
  }
  return null;
}

/** True for an Apple Pencil (or any other stylus). */
export function isPen(event: PointerEvent): boolean {
  return event.pointerType === "pen";
}

export interface PenSelectionOptions {
  /** Only drags that start inside this element select. */
  container: () => HTMLElement | null;
  /** Called when a pen drag finishes having selected something. */
  onSelected: () => void;
}

/**
 * Wire pen-drag-to-select onto the document. Returns a teardown function.
 *
 * Finger and mouse are left completely alone, so ordinary scrolling and
 * ordinary selection keep working exactly as before — the pen is the only
 * pointer this intercepts.
 */
export function attachPenSelection({
  container,
  onSelected,
}: PenSelectionOptions): () => void {
  let anchor: CaretPoint | null = null;
  let moved = false;
  let penId: number | null = null;

  const down = (event: PointerEvent) => {
    if (!isPen(event)) return;
    const root = container();
    if (!root || !(event.target instanceof Node) || !root.contains(event.target)) return;

    // Leave controls alone. Cancelling pointerdown suppresses the click that
    // would otherwise follow, so claiming the event here would stop a pen tap
    // from opening a glossary term — the reading pane has those inline, mid
    // sentence, exactly where a highlight is likely to start.
    if (event.target instanceof Element && event.target.closest("button, a, input, textarea, select")) {
      return;
    }

    const point = caretAt(event.clientX, event.clientY);
    if (!point) return;

    // Stops the page scrolling under the pen. Only reached for a pen inside
    // the reading pane, so a finger swipe anywhere still scrolls normally.
    if (event.cancelable) event.preventDefault();

    anchor = point;
    moved = false;
    penId = event.pointerId;
    window.getSelection()?.removeAllRanges();
  };

  const move = (event: PointerEvent) => {
    if (anchor === null || event.pointerId !== penId) return;
    const focus = caretAt(event.clientX, event.clientY);
    if (!focus) return;
    if (event.cancelable) event.preventDefault();

    const selection = window.getSelection();
    if (!selection) return;
    // setBaseAndExtent handles a drag that runs backwards (right to left, or
    // up the page) without any of the start/end juggling a Range needs.
    selection.setBaseAndExtent(anchor.node, anchor.offset, focus.node, focus.offset);
    if (!selection.isCollapsed) moved = true;
  };

  const up = (event: PointerEvent) => {
    if (anchor === null || event.pointerId !== penId) return;
    anchor = null;
    penId = null;
    // A tap without a drag is not a selection — let it fall through as a tap
    // rather than firing the toolbar on an empty range.
    if (moved) onSelected();
    moved = false;
  };

  const cancel = () => {
    anchor = null;
    penId = null;
    moved = false;
  };

  // Non-passive: preventDefault is the whole point, and browsers treat pointer
  // listeners on touch-like inputs as passive by default, which silently
  // ignores it. Removal only matches on type, listener and capture, so the
  // options object is deliberately not repeated below.
  document.addEventListener("pointerdown", down, { passive: false });
  document.addEventListener("pointermove", move, { passive: false });
  document.addEventListener("pointerup", up);
  document.addEventListener("pointercancel", cancel);

  return () => {
    document.removeEventListener("pointerdown", down);
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", up);
    document.removeEventListener("pointercancel", cancel);
  };
}
