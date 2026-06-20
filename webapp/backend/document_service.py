"""DocumentService: notes/transcript read, edit, save, versioning, regenerate.

This service (Task 11.3) reads, edits, saves, and versions a meeting's notes and
transcripts. It **orchestrates** the existing modules rather than reimplementing
them (Req 4.5):

- All writes go through :class:`~webapp.backend.storage.StorageManager` so they
  are atomic and serialized under the cross-process write lock (Req 7.5, 9.3).
- Notes versioning reuses the existing on-disk scheme
  (``meeting_notes_{id}.md`` for v1, ``meeting_notes_{id}_v{n}.md`` for later
  versions) that :class:`NotesGenerator` already produces, and registers each
  version with :class:`VersionManager` so both UIs see consistent metadata
  (Req 7.6).
- Regeneration calls ``NotesGenerator.generate_notes_from_transcript`` and
  returns the produced notes **without persisting** them (Req 7.8).

Behavioral contracts:

- **Save creates a strictly greater version** (Req 7.6). The next version number
  is ``max(existing file versions, metadata latest_version) + 1`` (1 when none
  exist). Prior version files are never modified - a new file is always written.
- **Read-back** (Req 7.4): immediately reading a just-saved version returns
  exactly the bytes that were written.
- **Not-found leaves stored data unchanged** (Req 4.6): reading notes/transcript
  for a meeting/version/resource that does not exist raises
  :class:`NotFoundError` and writes nothing. ``VersionManager.get_metadata``
  only auto-creates metadata when notes/transcript files already exist, so a
  truly missing meeting yields ``None`` with no side effects.
- **Regeneration does not persist** (Req 7.8): no file is written; the produced
  notes are returned for review. A missing transcript raises
  :class:`NotFoundError`; a generator that yields nothing raises
  :class:`GenerationError` so the caller can keep the previously displayed notes
  (Req 7.9).

Dependency injection: ``StorageManager`` and ``VersionManager`` are injected for
testability and default to real instances pointing at the standard notes dir.
``NotesGenerator`` is **not** constructed eagerly (its ``__init__`` initializes
``AWSHandler`` with network/credential calls); it is injected or lazily built via
``notes_generator_factory`` only when regeneration is actually requested, so this
module imports light with no AWS calls.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional

from webapp.backend.models import build_transcript_result_from_text
from webapp.backend.storage import StorageManager


class NotFoundError(Exception):
    """Raised when a referenced meeting/version/resource does not exist (Req 4.6).

    The :attr:`resource` attribute identifies the missing resource so the API
    layer can surface it in the ``{error:{code,message,resource}}`` envelope.
    Raising this leaves all stored data unchanged.
    """

    def __init__(self, resource: str, message: Optional[str] = None) -> None:
        self.resource = resource
        super().__init__(message or f"Resource not found: {resource}")


class GenerationError(Exception):
    """Raised when notes regeneration produced no content (Req 7.9).

    Distinct from :class:`NotFoundError` so the caller can keep the previously
    displayed notes rather than treating it as a missing resource.
    """


@dataclass
class NotesSaveResult:
    """The outcome of saving a notes version.

    Attributes:
        meeting_id: The meeting the notes belong to.
        version_num: The version number created by the save (strictly greater
            than any prior version).
        notes_path: Absolute path of the written notes file.
        is_new_version: True when a prior version already existed (i.e. this save
            created an additional version rather than the first one).
    """

    meeting_id: str
    version_num: int
    notes_path: str
    is_new_version: bool


@dataclass
class TranscriptSaveResult:
    """The outcome of saving an edited transcript.

    Attributes:
        meeting_id: The meeting the transcript belongs to.
        json_path: Absolute path of the written transcript JSON file.
        text_path: Absolute path of the written transcript text file.
    """

    meeting_id: str
    json_path: str
    text_path: str


# Notes filename: ``meeting_notes_{id}.md`` (v1) or ``meeting_notes_{id}_v{n}.md``.
_NOTES_PREFIX = "meeting_notes_"
_NOTES_SUFFIX = ".md"


class DocumentService:
    """Read/edit/save/version notes + transcripts via StorageManager and VersionManager."""

    def __init__(
        self,
        storage: Optional[StorageManager] = None,
        version_manager: Any = None,
        notes_generator: Any = None,
        *,
        notes_generator_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Create a DocumentService.

        Args:
            storage: A :class:`StorageManager`. Defaults to a real one pointing
                at the standard ``notes``/``recordings`` dirs under the project
                root (Req 9.2). Tests inject a temp-dir-backed manager.
            version_manager: A ``VersionManager`` instance. Defaults to a real one
                bound to ``storage.notes_dir()`` so file layout and metadata stay
                in the same directory.
            notes_generator: Optional pre-built ``NotesGenerator`` for the
                regenerate path. Injectable so the API layer shares one instance
                and tests can supply a double.
            notes_generator_factory: Optional zero-arg callable returning a
                ``NotesGenerator``; invoked lazily only when regeneration is
                requested (avoids eager AWS initialization at construction time).
        """
        self._storage = storage if storage is not None else StorageManager()
        self._notes_dir = self._storage.notes_dir()
        if version_manager is not None:
            self._version_manager = version_manager
        else:
            from version_manager import VersionManager  # top-level module

            self._version_manager = VersionManager(self._notes_dir)
        self._notes_generator = notes_generator
        self._notes_generator_factory = notes_generator_factory

    # ------------------------------------------------------------------
    # Notes: read
    # ------------------------------------------------------------------

    def read_notes(self, meeting_id: str, version: Optional[int] = None) -> str:
        """Return a meeting's notes content, optionally for a specific version.

        With ``version=None`` the default version (or, lacking metadata, the
        highest-numbered notes file on disk) is read. Raises
        :class:`NotFoundError` if the meeting/version has no notes file, leaving
        stored data unchanged (Req 4.6).
        """
        metadata = self._version_manager.get_metadata(meeting_id)

        if version is not None:
            path = self._resolve_version_notes_path(meeting_id, metadata, int(version))
            if not path or not os.path.exists(path):
                raise NotFoundError(
                    f"meeting:{meeting_id}/notes/v{version}",
                    f"No notes for meeting {meeting_id} version {version}",
                )
            return self._storage.read_text(path)

        # Default/latest version.
        path = None
        if metadata:
            default = self._version_manager.get_default_version(meeting_id)
            if default is not None:
                path = self._resolve_version_notes_path(
                    meeting_id, metadata, int(default)
                )
        if not path or not os.path.exists(path):
            path = self._find_latest_notes_file(meeting_id)
        if not path or not os.path.exists(path):
            raise NotFoundError(
                f"meeting:{meeting_id}/notes",
                f"No notes found for meeting {meeting_id}",
            )
        return self._storage.read_text(path)

    # ------------------------------------------------------------------
    # Notes: save (versioned)
    # ------------------------------------------------------------------

    def save_notes(
        self,
        meeting_id: str,
        content: str,
        *,
        name: Optional[str] = None,
        comments: Optional[str] = None,
        model_id: Optional[str] = None,
        transcription_service: Optional[str] = None,
    ) -> NotesSaveResult:
        """Persist edited notes as a new, strictly-greater version (Req 7.4, 7.6).

        Computes the next version number, writes the corresponding notes file
        atomically through :class:`StorageManager` (under the cross-process write
        lock), and registers the version with :class:`VersionManager`. Prior
        version files are never touched, so all earlier versions are retained
        unchanged (Req 7.6). The just-written content is readable back via
        :meth:`read_notes` (Req 7.4).
        """
        # Hold the write lock across version computation + write + metadata update
        # so two concurrent savers cannot pick the same version number.
        with self._storage.write_lock():
            existing_versions = self._existing_versions(meeting_id)
            next_version = (max(existing_versions) + 1) if existing_versions else 1
            is_new_version = bool(existing_versions)

            filename = self._notes_filename(meeting_id, next_version)
            notes_path = self._storage.write_notes(filename, content)

            transcript_path = self._existing_path(f"transcript_{meeting_id}.txt")
            transcript_json_path = self._existing_path(f"transcript_{meeting_id}.json")

            version_info = {
                "version_num": next_version,
                "notes_path": notes_path,
                "transcript_path": transcript_path,
                "transcript_json_path": transcript_json_path,
                "creation_time": datetime.now().isoformat(),
                "name": name or f"Version {next_version}",
                "comments": comments or "",
            }
            if model_id is not None:
                version_info["model_id"] = model_id
            if transcription_service is not None:
                version_info["transcription_service"] = transcription_service

            self._version_manager.create_or_update_metadata(meeting_id, version_info)

        return NotesSaveResult(
            meeting_id=meeting_id,
            version_num=next_version,
            notes_path=notes_path,
            is_new_version=is_new_version,
        )

    # ------------------------------------------------------------------
    # Transcript: read / save
    # ------------------------------------------------------------------

    def read_transcript(self, meeting_id: str) -> str:
        """Return a meeting's plain-text transcript (Req 7.2).

        Reads ``transcript_{id}.txt`` from the notes dir. Raises
        :class:`NotFoundError` when no transcript exists, leaving stored data
        unchanged (Req 4.6).
        """
        txt_path = self._existing_path(f"transcript_{meeting_id}.txt")
        if txt_path:
            return self._storage.read_text(txt_path)

        # Fall back to the JSON transcript's text field if only JSON exists.
        json_path = self._existing_path(f"transcript_{meeting_id}.json")
        if json_path:
            import json

            try:
                data = json.loads(self._storage.read_text(json_path))
                return data["results"]["transcripts"][0]["transcript"]
            except (KeyError, IndexError, TypeError, ValueError):
                pass

        raise NotFoundError(
            f"meeting:{meeting_id}/transcript",
            f"No transcript found for meeting {meeting_id}",
        )

    def read_transcript_json(self, meeting_id: str) -> dict:
        """Return a meeting's transcript JSON object (shared transcript schema).

        Raises :class:`NotFoundError` when no transcript JSON exists.
        """
        json_path = self._existing_path(f"transcript_{meeting_id}.json")
        if not json_path:
            raise NotFoundError(
                f"meeting:{meeting_id}/transcript",
                f"No transcript JSON found for meeting {meeting_id}",
            )
        import json

        return json.loads(self._storage.read_text(json_path))

    def save_transcript(self, meeting_id: str, text: str) -> TranscriptSaveResult:
        """Persist an edited transcript atomically (Req 7.4, 7.5).

        Writes both the ``transcript_{id}.json`` and ``transcript_{id}.txt``
        files through :class:`StorageManager` so the JSON and text stay
        consistent and the write is atomic/serialized. The JSON is rebuilt from
        the edited text into the shared transcript schema so notes generation can
        consume it. Returns the written paths; read back the text via
        :meth:`read_transcript`.
        """
        json_obj = build_transcript_result_from_text(text)
        json_path, text_path = self._storage.write_transcript(meeting_id, json_obj, text)
        return TranscriptSaveResult(
            meeting_id=meeting_id, json_path=json_path, text_path=text_path
        )

    # ------------------------------------------------------------------
    # Regeneration (no persistence)
    # ------------------------------------------------------------------

    def regenerate_notes(
        self, meeting_id: str, model_id: Optional[str] = None
    ) -> str:
        """Regenerate notes from the meeting's transcript without persisting (Req 7.8).

        Loads the meeting's transcript JSON and calls
        ``NotesGenerator.generate_notes_from_transcript`` to produce notes for
        review. **Nothing is written to disk** - the caller persists later via
        :meth:`save_notes` only if the user explicitly saves.

        Raises:
            NotFoundError: if the meeting has no transcript to regenerate from.
            GenerationError: if the generator produced no notes (Req 7.9), so the
                caller can retain the previously displayed notes.
        """
        transcript_json = self.read_transcript_json(meeting_id)  # raises NotFound

        generator = self._get_notes_generator()
        if generator is None:
            raise GenerationError(
                "Notes generator is unavailable; cannot regenerate notes."
            )

        notes_content = generator.generate_notes_from_transcript(
            transcript_json, model_id=model_id
        )
        if not notes_content:
            raise GenerationError(
                f"Notes regeneration produced no content for meeting {meeting_id}"
            )
        return notes_content

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_notes_generator(self) -> Any:
        """Return an injected/lazily-built ``NotesGenerator`` or ``None``.

        Never raises; the factory is only invoked when regeneration is requested
        so import/construction never triggers AWS calls.
        """
        if self._notes_generator is not None:
            return self._notes_generator
        if self._notes_generator_factory is not None:
            try:
                self._notes_generator = self._notes_generator_factory()
            except Exception:
                self._notes_generator = None
        return self._notes_generator

    def _existing_path(self, filename: str) -> Optional[str]:
        """Return the absolute path of ``filename`` under notes dir if it exists."""
        path = os.path.join(self._notes_dir, filename)
        return path if os.path.exists(path) else None

    @staticmethod
    def _notes_filename(meeting_id: str, version: int) -> str:
        """Build the notes filename for a meeting + version.

        Version 1 uses the base ``meeting_notes_{id}.md`` (matching the existing
        ``NotesGenerator`` scheme); later versions use ``..._v{n}.md``.
        """
        if version <= 1:
            return f"{_NOTES_PREFIX}{meeting_id}{_NOTES_SUFFIX}"
        return f"{_NOTES_PREFIX}{meeting_id}_v{version}{_NOTES_SUFFIX}"

    def _version_from_filename(self, meeting_id: str, filename: str) -> Optional[int]:
        """Parse the version number from a notes filename for ``meeting_id``.

        Returns 1 for the base file, ``n`` for ``..._v{n}.md``, or ``None`` if the
        filename does not belong to this meeting.
        """
        base = re.escape(f"{_NOTES_PREFIX}{meeting_id}")
        m = re.fullmatch(rf"{base}(?:_v(\d+))?{re.escape(_NOTES_SUFFIX)}", filename)
        if not m:
            return None
        return int(m.group(1)) if m.group(1) else 1

    def _existing_versions(self, meeting_id: str) -> List[int]:
        """All known version numbers for a meeting (from files + metadata).

        Combining both sources guarantees the next version is strictly greater
        than anything previously written or recorded, even if files and metadata
        are momentarily out of sync (Req 7.6).
        """
        versions: set[int] = set()

        if os.path.isdir(self._notes_dir):
            for filename in os.listdir(self._notes_dir):
                v = self._version_from_filename(meeting_id, filename)
                if v is not None:
                    versions.add(v)

        metadata = self._version_manager.get_metadata(meeting_id)
        if metadata and isinstance(metadata, dict):
            for key in (metadata.get("versions") or {}).keys():
                try:
                    versions.add(int(key))
                except (TypeError, ValueError):
                    continue
            latest = metadata.get("latest_version")
            if isinstance(latest, int) and not isinstance(latest, bool):
                versions.add(latest)

        return sorted(versions)

    def _resolve_version_notes_path(
        self, meeting_id: str, metadata: Any, version: int
    ) -> Optional[str]:
        """Resolve the notes file path for a specific version.

        Prefers the path recorded in metadata; falls back to the conventional
        filename under the notes dir.
        """
        if metadata and isinstance(metadata, dict):
            info = (metadata.get("versions") or {}).get(str(version))
            if isinstance(info, dict) and info.get("notes_path"):
                return info["notes_path"]
        return os.path.join(self._notes_dir, self._notes_filename(meeting_id, version))

    def _find_latest_notes_file(self, meeting_id: str) -> Optional[str]:
        """Return the highest-numbered existing notes file for a meeting, if any."""
        if not os.path.isdir(self._notes_dir):
            return None
        best_version: Optional[int] = None
        best_path: Optional[str] = None
        for filename in os.listdir(self._notes_dir):
            v = self._version_from_filename(meeting_id, filename)
            if v is None:
                continue
            if best_version is None or v > best_version:
                best_version = v
                best_path = os.path.join(self._notes_dir, filename)
        return best_path
