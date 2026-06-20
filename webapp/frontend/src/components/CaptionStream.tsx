/**
 * `CaptionStream` — live caption panel (task 18.1).
 *
 * Renders `store.captions`, which the caption reducer already keeps ordered
 * ascending by `start`, de-duplicated, and final-protected (Req 1.4). This
 * component is therefore presentational: it iterates the array as-is and does
 * not re-sort.
 *
 * Interim captions are visually distinguished from final ones (greyed +
 * italic) so a viewer can tell which text may still be revised (Req 1.2). When
 * a chunk error is present (`store.captionError`) it is shown inline above the
 * stream without removing any captions (Req 1.9). The panel auto-scrolls to the
 * newest caption as captions arrive.
 */

import { useEffect, useRef } from "react";
import { useAppStore } from "../store";

/** Format a `start`/`end` second offset as `m:ss`. */
function formatOffset(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export default function CaptionStream() {
  const captions = useAppStore((s) => s.captions);
  const captionError = useAppStore((s) => s.captionError);

  const endRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to the newest caption whenever the list grows/changes.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [captions]);

  return (
    <div className="flex h-full flex-col">
      {captionError !== null && (
        <div
          role="alert"
          className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
        >
          <span className="font-semibold">Transcription hiccup:</span>{" "}
          {captionError.message}
        </div>
      )}

      <div className="flex-1 overflow-y-auto rounded-xl border border-slate-200 bg-white p-4">
        {captions.length === 0 ? (
          <p className="flex h-full items-center justify-center text-sm text-slate-400">
            Captions will appear here as you speak.
          </p>
        ) : (
          <ul className="space-y-2">
            {captions.map((caption) => {
              const isInterim = caption.status === "interim";
              return (
                <li
                  key={caption.start}
                  className="flex gap-3 text-sm leading-relaxed"
                  data-status={caption.status}
                >
                  <span className="mt-0.5 shrink-0 font-mono text-xs tabular-nums text-slate-400">
                    {formatOffset(caption.start)}
                  </span>
                  <span
                    className={
                      isInterim
                        ? "italic text-slate-400"
                        : "text-slate-800"
                    }
                  >
                    {caption.text}
                  </span>
                </li>
              );
            })}
            <div ref={endRef} />
          </ul>
        )}
      </div>
    </div>
  );
}
