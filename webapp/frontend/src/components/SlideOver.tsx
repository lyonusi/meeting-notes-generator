/**
 * `SlideOver` — a right-side slide-over drawer (panel) overlaying the page.
 *
 * Used by the Record page to surface the Configuration view without a separate
 * nav tab. It renders a semi-transparent backdrop plus a fixed panel that
 * slides in from the right with a Tailwind `translate-x` transition.
 *
 * Accessibility:
 * - The panel is a `role="dialog"` with `aria-modal="true"` and is labelled by
 *   its title.
 * - Escape closes the drawer; clicking the backdrop closes the drawer.
 * - On open, focus moves to the panel; on close, focus returns to the element
 *   that was focused before opening.
 *
 * The drawer stays mounted (so the open/close transition can animate) but is
 * inert and hidden from assistive tech while closed.
 */

import { useEffect, useId, useRef } from "react";

export interface SlideOverProps {
  /** Whether the drawer is open. */
  open: boolean;
  /** Called when the user requests to close (X, backdrop click, or Escape). */
  onClose: () => void;
  /** Accessible title for the drawer, shown in the header and as its label. */
  title: string;
  /** The drawer body content. */
  children: React.ReactNode;
}

export default function SlideOver({
  open,
  onClose,
  title,
  children,
}: SlideOverProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  /** The element focused before the drawer opened, restored on close. */
  const previouslyFocused = useRef<HTMLElement | null>(null);

  // Close on Escape while open.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  // Move focus into the panel on open; restore it on close.
  useEffect(() => {
    if (open) {
      previouslyFocused.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      // Defer so the panel is focusable after it becomes visible.
      const id = window.requestAnimationFrame(() => {
        panelRef.current?.focus();
      });
      return () => window.cancelAnimationFrame(id);
    }
    previouslyFocused.current?.focus();
    return undefined;
  }, [open]);

  return (
    <div
      className={[
        "fixed inset-0 z-40",
        open ? "" : "pointer-events-none",
      ].join(" ")}
      aria-hidden={open ? undefined : true}
    >
      {/* Backdrop */}
      <div
        className={[
          "absolute inset-0 bg-slate-900/40 transition-opacity duration-300",
          open ? "opacity-100" : "opacity-0",
        ].join(" ")}
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={[
          "absolute inset-y-0 right-0 flex w-full max-w-[420px] flex-col bg-slate-50 shadow-xl outline-none",
          "transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
      >
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
          <h2 id={titleId} className="text-sm font-semibold text-slate-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <span aria-hidden className="text-lg leading-none">
              ✕
            </span>
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
