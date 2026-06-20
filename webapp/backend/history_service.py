"""HistoryService: descending-ordered meeting history and versions.

This service (Task 11.1) wraps the existing :class:`VersionManager` and
:class:`NotesGenerator` listing helpers and maps their output onto the backend
data models (:class:`~webapp.backend.models.MeetingSummary` and
:class:`~webapp.backend.models.NotesVersion`). It does **not** reimplement
metadata or versioning logic (Req 4.5); it only orchestrates and re-orders.

Responsibilities:

- :meth:`HistoryService.list_meetings` - return the meeting history as a list of
  :class:`MeetingSummary`, ordered by meeting start timestamp **descending**
  (most recent first) (Req 7.1).
- :meth:`HistoryService.get_versions` - for a given meeting, return its
  :class:`NotesVersion` list ordered by creation timestamp **descending**
  (Req 7.7).

Reuse / construction notes:

- ``VersionManager.get_all_meetings_with_metadata()`` already returns the merged
  per-meeting metadata (auto-discovering meetings that only have notes files).
  ``VersionManager`` is the source of truth for ``meeting_id``, ``display_date``,
  ``latest_version`` and the per-version records.
- Meeting titles come from ``NotesGenerator.get_notes_list()`` (keyed by the
  meeting timestamp) when a ``NotesGenerator`` is available. Because constructing
  a real ``NotesGenerator`` eagerly initializes ``AWSHandler`` (network/credential
  calls), this service does **not** build one by default. When the API layer
  wires a shared ``NotesGenerator`` in, pass it via ``notes_generator`` (or a
  ``notes_generator_factory``) and titles are sourced from
  ``get_notes_list()``. Otherwise titles fall back to the first heading line of
  the meeting's default notes file - a lightweight read that needs no AWS.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from webapp.backend.models import MeetingSummary, NotesVersion

# Transcript files a recorded-but-not-yet-noted meeting leaves behind. Used to
# discover meetings that have a transcript (and thus can have notes generated)
# but no notes file or metadata yet, so they still appear in the history list.
_TRANSCRIPT_RE = re.compile(r"^transcript_(\d{8}_\d{6})\.(?:json|txt)$")


def _default_notes_dir() -> str:
    """Absolute path to the standard ``notes`` directory (project root/notes).

    Mirrors :data:`webapp.backend.storage.DEFAULT_NOTES_DIR` resolved against the
    project root so the web backend reads the same notes folder as the tkinter
    app regardless of the process CWD (Req 9.2).
    """
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(project_root, "notes")


class HistoryService:
    """Descending-ordered meeting history backed by ``VersionManager``."""

    def __init__(
        self,
        version_manager: Any = None,
        notes_generator: Any = None,
        *,
        notes_dir: Optional[str] = None,
        notes_generator_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Create a HistoryService.

        Args:
            version_manager: A ``VersionManager`` instance. When omitted, a real
                one is constructed against ``notes_dir`` (lightweight - it only
                touches the filesystem).
            notes_generator: An optional pre-built ``NotesGenerator`` used to
                source meeting titles via ``get_notes_list()``. Injectable so the
                API layer can share one instance. Not constructed by default to
                avoid eager AWS initialization.
            notes_dir: Override for the notes directory. Defaults to
                ``<project_root>/notes``.
            notes_generator_factory: Optional zero-arg callable returning a
                ``NotesGenerator``; used lazily (and guarded) only when titles are
                requested and no ``notes_generator`` was injected.
        """
        self._notes_dir = os.path.abspath(notes_dir or _default_notes_dir())
        if version_manager is not None:
            self._version_manager = version_manager
        else:
            from version_manager import VersionManager  # top-level module

            self._version_manager = VersionManager(self._notes_dir)
        self._notes_generator = notes_generator
        self._notes_generator_factory = notes_generator_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_meetings(self) -> List[MeetingSummary]:
        """Return the meeting history ordered by start timestamp descending.

        Wraps ``VersionManager.get_all_meetings_with_metadata()`` and maps each
        metadata record onto a :class:`MeetingSummary`. The result is sorted by
        the meeting start timestamp (the ``YYYYMMDD_HHMMSS`` ``meeting_id``) in
        descending order so the most recent meeting is first (Req 7.1).
        """
        metadatas = self._version_manager.get_all_meetings_with_metadata() or []
        title_map = self._build_title_map()

        summaries: List[MeetingSummary] = []
        seen_ids: set[str] = set()
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            meeting_id = metadata.get("meeting_id")
            if not meeting_id:
                continue
            seen_ids.add(meeting_id)
            summaries.append(
                MeetingSummary(
                    meeting_id=meeting_id,
                    display_date=metadata.get("display_date", "Unknown Date"),
                    title=self._resolve_title(meeting_id, metadata, title_map),
                    latest_version=self._resolve_latest_version(metadata),
                )
            )

        # Also surface meetings that only have a transcript (just recorded, no
        # notes generated/saved yet). VersionManager only discovers meetings with
        # notes files or metadata, so without this a freshly transcribed meeting
        # would be invisible in the history list and the user could never reach
        # the "Generate Notes" action for it.
        for meeting_id in self._discover_transcript_only_ids(seen_ids):
            seen_ids.add(meeting_id)
            summaries.append(
                MeetingSummary(
                    meeting_id=meeting_id,
                    display_date=self._display_date_from_id(meeting_id),
                    title="Untitled Meeting (no notes yet)",
                    latest_version=0,
                )
            )

        # Sort by meeting start timestamp descending. The meeting_id is a
        # fixed-width YYYYMMDD_HHMMSS string, so a reverse lexicographic sort is a
        # reverse chronological sort (Req 7.1).
        summaries.sort(key=lambda s: s.meeting_id, reverse=True)
        return summaries

    def get_versions(self, meeting_id: str) -> List[NotesVersion]:
        """Return a meeting's notes versions ordered by creation time descending.

        Maps each entry in the meeting's ``VersionManager`` metadata onto a
        :class:`NotesVersion` and orders them by creation timestamp descending
        (most recent first), breaking ties by version number descending
        (Req 7.7). Returns an empty list when the meeting has no metadata.
        """
        metadata = self._version_manager.get_metadata(meeting_id)
        if not metadata or not isinstance(metadata, dict):
            return []

        versions_dict = metadata.get("versions") or {}
        versions: List[NotesVersion] = []
        for ver_key, info in versions_dict.items():
            if not isinstance(info, dict):
                continue
            try:
                version_num = int(ver_key)
            except (TypeError, ValueError):
                continue
            versions.append(
                NotesVersion(
                    version_num=version_num,
                    name=info.get("name", f"Version {version_num}"),
                    creation_time=info.get("creation_time", ""),
                    is_default=bool(info.get("is_default", False)),
                )
            )

        # Order by creation timestamp descending; ISO-8601 strings sort
        # chronologically, so a reverse string sort yields newest-first. Use
        # version_num as a stable tie-breaker (also descending).
        versions.sort(key=lambda v: (v.creation_time, v.version_num), reverse=True)
        return versions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_transcript_only_ids(self, already_seen: set) -> List[str]:
        """Return meeting ids that have a transcript file but weren't already seen.

        Scans the notes dir for ``transcript_{id}.json``/``.txt`` files so a
        recorded meeting with a transcript but no notes/metadata still appears in
        the history (and can have notes generated). Ids already produced from
        metadata/notes are skipped.
        """
        if not os.path.isdir(self._notes_dir):
            return []
        ids: set[str] = set()
        for filename in os.listdir(self._notes_dir):
            match = _TRANSCRIPT_RE.match(filename)
            if match:
                meeting_id = match.group(1)
                if meeting_id not in already_seen:
                    ids.add(meeting_id)
        return sorted(ids)

    @staticmethod
    def _display_date_from_id(meeting_id: str) -> str:
        """Format a ``YYYYMMDD_HHMMSS`` meeting id as a human-readable date."""
        try:
            dt = datetime.strptime(meeting_id, "%Y%m%d_%H%M%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return meeting_id

    @staticmethod
    def _resolve_latest_version(metadata: Dict[str, Any]) -> int:
        """Best-effort extraction of the latest version number from metadata."""
        latest = metadata.get("latest_version")
        if isinstance(latest, int) and not isinstance(latest, bool):
            return latest
        versions = metadata.get("versions") or {}
        nums = []
        for key in versions.keys():
            try:
                nums.append(int(key))
            except (TypeError, ValueError):
                continue
        return max(nums) if nums else 1

    def _build_title_map(self) -> Dict[str, str]:
        """Build a ``{meeting_id: title}`` map from ``NotesGenerator.get_notes_list()``.

        Returns an empty map when no ``NotesGenerator`` is available; titles then
        fall back to reading the notes file heading (see :meth:`_resolve_title`).
        """
        generator = self._get_notes_generator()
        if generator is None:
            return {}
        try:
            notes_list = generator.get_notes_list() or []
        except Exception:
            return {}

        title_map: Dict[str, str] = {}
        for entry in notes_list:
            if not isinstance(entry, dict):
                continue
            timestamp = entry.get("timestamp")
            title = entry.get("title")
            if timestamp and title:
                # get_notes_list is sorted newest-first and may list multiple
                # versions per meeting; keep the first (newest) title seen.
                title_map.setdefault(timestamp, title)
        return title_map

    def _get_notes_generator(self) -> Any:
        """Return an injected/lazily-built ``NotesGenerator`` or ``None``.

        Never raises and never eagerly constructs the real ``NotesGenerator``
        (which would init AWS); a factory is only invoked when explicitly
        provided.
        """
        if self._notes_generator is not None:
            return self._notes_generator
        if self._notes_generator_factory is not None:
            try:
                self._notes_generator = self._notes_generator_factory()
            except Exception:
                self._notes_generator = None
        return self._notes_generator

    def _resolve_title(
        self,
        meeting_id: str,
        metadata: Dict[str, Any],
        title_map: Dict[str, str],
    ) -> str:
        """Resolve a meeting's display title.

        Prefers the title from ``NotesGenerator.get_notes_list()`` (keyed by
        meeting id); otherwise reads the first heading line of the meeting's
        default/latest notes file. Falls back to a generic placeholder.
        """
        if meeting_id in title_map:
            return title_map[meeting_id]

        notes_path = self._default_notes_path(metadata)
        if notes_path and os.path.exists(notes_path):
            try:
                with open(notes_path, "r", encoding="utf-8") as f:
                    first_line = f.readline().strip()
                title = first_line.lstrip("#").strip()
                if title:
                    return title
            except Exception:
                pass
        return "Untitled Meeting"

    @staticmethod
    def _default_notes_path(metadata: Dict[str, Any]) -> Optional[str]:
        """Return the notes path of the default version (or the highest version)."""
        versions = metadata.get("versions") or {}
        if not versions:
            return None
        # Prefer the explicitly-default version.
        for info in versions.values():
            if isinstance(info, dict) and info.get("is_default") and info.get("notes_path"):
                return info["notes_path"]
        # Otherwise the highest version number with a notes path.
        best_key: Optional[int] = None
        best_path: Optional[str] = None
        for key, info in versions.items():
            if not isinstance(info, dict) or not info.get("notes_path"):
                continue
            try:
                num = int(key)
            except (TypeError, ValueError):
                continue
            if best_key is None or num > best_key:
                best_key = num
                best_path = info["notes_path"]
        return best_path
