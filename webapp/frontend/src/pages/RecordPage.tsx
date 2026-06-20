/**
 * `RecordPage` — Page 1 of the consolidated two-page shell.
 *
 * Hosts the {@link LiveRecordingView} as the main content and exposes the
 * settings via a right-side {@link SlideOver} drawer rather than a separate nav
 * tab. A gear button (top-right) toggles the drawer, which renders the existing
 * {@link ConfigurationView} in its `embedded` form so its width fits the narrow
 * panel. No configuration logic is duplicated here.
 */

import { useState } from "react";
import LiveRecordingView from "../views/LiveRecordingView";
import ConfigurationView from "../views/ConfigurationView";
import SlideOver from "../components/SlideOver";

export default function RecordPage() {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="relative flex h-full flex-col">
      {/* Settings trigger — top-right of the Record page. */}
      <div className="flex justify-end px-2">
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={settingsOpen}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-colors hover:bg-slate-50 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          <span aria-hidden className="text-base leading-none">
            ⚙
          </span>
          Settings
        </button>
      </div>

      <div className="min-h-0 flex-1">
        <LiveRecordingView />
      </div>

      <SlideOver
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        title="Configuration"
      >
        <ConfigurationView embedded />
      </SlideOver>
    </div>
  );
}
