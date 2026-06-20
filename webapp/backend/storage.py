"""StorageManager: single choke point for writes to shared storage.

This module implements the :class:`StorageManager` described in the design's
"Components" section. It provides:

- ``recordings_dir()`` / ``notes_dir()`` accessors. Recordings live *outside*
  the notes dir (Req 8.1, 8.2); generated notes/transcripts/captions live in the
  notes dir (Req 8.3).
- ``write_lock()`` - a cross-process advisory lock (``fcntl.flock`` on a lockfile
  under ``notes/metadata/.write.lock``) that serializes concurrent writers so a
  tkinter + web write never corrupt each other (Req 9.3).
- Atomic writes (temp file + ``os.replace``) for ``write_notes``,
  ``write_transcript`` and ``write_captions`` so readers never observe partial
  content and a failed write leaves prior content intact.
- A storage-hygiene guard that rejects any write whose resolved target is a
  ``.wav`` path under the notes dir (Req 8.2); recording WAVs only go to the
  recordings dir.

Captions are serialized to JSON with ``start``, ``end``, ``text`` and ``status``
so the persisted form round-trips back into :class:`~webapp.backend.models.Caption`
objects (Req 2.9).
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from webapp.backend.models import Caption


class StorageError(Exception):
    """Raised when a write violates a storage invariant (e.g. WAV in notes)."""


# Default storage locations, relative to the base dir. In the real deployment
# ``notes/`` and ``recordings/`` are symlinks into an Obsidian vault, but they
# are treated here as plain directories. These names match the existing app
# (``config.RECORDINGS_DIR == "recordings"`` and ``NotesGenerator.notes_dir ==
# "notes"``).
DEFAULT_NOTES_DIR = "notes"
DEFAULT_RECORDINGS_DIR = "recordings"

# The project root is three levels up from this file
# (``<root>/webapp/backend/storage.py``). Used as the default base dir so the
# web backend reads/writes the same ``notes/`` and ``recordings/`` folders the
# tkinter app already uses, regardless of the process CWD (Req 9.2).
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

_LOCKFILE_NAME = ".write.lock"
_METADATA_DIRNAME = "metadata"


class StorageManager:
    """Serialized, atomic, location-safe access to shared notes/recordings storage."""

    def __init__(
        self,
        base_dir: Optional[str] = None,
        notes_dir: Optional[str] = None,
        recordings_dir: Optional[str] = None,
    ) -> None:
        """Create a StorageManager.

        Args:
            base_dir: Root under which ``notes/`` and ``recordings/`` live as
                siblings. Defaults to the project root so the web backend shares
                storage with the tkinter app independent of CWD (Req 9.2). Tests
                pass a temp directory here to isolate storage.
            notes_dir: Optional explicit override for the notes directory
                (generated notes/transcripts/captions). When omitted it is
                ``<base_dir>/notes``.
            recordings_dir: Optional explicit override for the recordings
                directory (WAV files); resides *outside* the notes dir. When
                omitted it is ``<base_dir>/recordings``.
        """
        self._base_dir = os.path.abspath(base_dir if base_dir is not None else _PROJECT_ROOT)
        self._notes_dir = os.path.abspath(
            notes_dir if notes_dir is not None
            else os.path.join(self._base_dir, DEFAULT_NOTES_DIR)
        )
        self._recordings_dir = os.path.abspath(
            recordings_dir if recordings_dir is not None
            else os.path.join(self._base_dir, DEFAULT_RECORDINGS_DIR)
        )
        self._metadata_dir = os.path.join(self._notes_dir, _METADATA_DIRNAME)
        self._lockfile_path = os.path.join(self._metadata_dir, _LOCKFILE_NAME)

        # In-process serialization + reentrancy support. ``write_lock`` is
        # reentrant within a single thread so the atomic-write helpers can be
        # called either standalone or nested under an outer ``write_lock``.
        self._rlock = threading.RLock()
        self._lock_depth = 0
        self._lock_fd: Optional[int] = None

    # ------------------------------------------------------------------
    # Directory accessors
    # ------------------------------------------------------------------

    def base_dir(self) -> str:
        """Return the absolute base directory path (parent of notes/recordings)."""
        return self._base_dir

    def notes_dir(self) -> str:
        """Return the absolute notes directory path."""
        return self._notes_dir

    def recordings_dir(self) -> str:
        """Return the absolute recordings directory path (outside the notes dir)."""
        return self._recordings_dir

    # ------------------------------------------------------------------
    # Cross-process write lock
    # ------------------------------------------------------------------

    @contextmanager
    def write_lock(self) -> Iterator[None]:
        """Acquire the cross-process advisory write lock.

        Uses ``fcntl.flock`` on a lockfile under ``notes/metadata/.write.lock``
        to serialize concurrent writers across processes (Req 9.3). The lock is
        reentrant within a single thread: nested ``write_lock`` calls only flock
        once (at the outermost level) and release on exit of the outermost block.
        """
        self._rlock.acquire()
        try:
            if self._lock_depth == 0:
                os.makedirs(self._metadata_dir, exist_ok=True)
                self._lock_fd = os.open(
                    self._lockfile_path, os.O_CREAT | os.O_RDWR, 0o644
                )
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
                if self._lock_depth == 0 and self._lock_fd is not None:
                    try:
                        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                    finally:
                        os.close(self._lock_fd)
                        self._lock_fd = None
        finally:
            self._rlock.release()

    # ------------------------------------------------------------------
    # Path resolution + guards
    # ------------------------------------------------------------------

    def _resolve_notes_target(self, path_or_name: str) -> str:
        """Resolve a relative filename / full path to an absolute path.

        Resolution rules:
        - Absolute paths are used as-is (normalized).
        - A bare filename (e.g. ``meeting_notes_X.md``) is joined under the notes
          dir.
        - A relative path that is project-root-relative (e.g.
          ``notes/meeting_notes_X.md``, as stored by the legacy tkinter app's
          metadata) is resolved against the base dir, then verified to land
          inside the notes dir. This avoids the ``notes/notes/...`` doubling bug
          that occurred when such paths were naively joined under the notes dir.

        The result is always an absolute, normalized path.
        """
        if os.path.isabs(path_or_name):
            return os.path.normpath(path_or_name)

        # A path containing a separator may be project-root-relative (legacy
        # metadata stores ``notes/<file>``). Resolve against the base dir and, if
        # that lands inside the notes dir, use it. Otherwise fall back to joining
        # under the notes dir (covers plain filenames and any other relatives).
        if os.sep in path_or_name or (os.altsep and os.altsep in path_or_name):
            base_relative = os.path.normpath(
                os.path.join(self._base_dir, path_or_name)
            )
            if self._is_within(self._notes_dir, base_relative):
                return base_relative

        return os.path.normpath(os.path.join(self._notes_dir, path_or_name))

    @staticmethod
    def _is_within(directory: str, target: str) -> bool:
        """Return True if ``target`` is inside ``directory`` (or equal to it)."""
        directory = os.path.abspath(directory)
        target = os.path.abspath(target)
        try:
            common = os.path.commonpath([directory, target])
        except ValueError:
            # Different drives / unrelated roots.
            return False
        return common == directory

    def _guard_wav_in_notes(self, target: str) -> None:
        """Reject any write whose target is a ``.wav`` path under the notes dir.

        Recording WAVs must only be written to the recordings dir (Req 8.1, 8.2).
        """
        if target.lower().endswith(".wav") and self._is_within(self._notes_dir, target):
            raise StorageError(
                f"Refusing to write WAV file into the notes directory: {target!r}. "
                "Recording WAV files must be written to the recordings directory."
            )

    # ------------------------------------------------------------------
    # Atomic writes
    # ------------------------------------------------------------------

    def _atomic_write_text(self, target: str, data: str) -> str:
        """Atomically write ``data`` to ``target`` (temp file + ``os.replace``).

        The write happens under ``write_lock`` so concurrent writers are
        serialized and readers never observe partial content; on failure the
        prior file contents are left intact and the temp file is cleaned up.
        """
        target = os.path.abspath(target)
        self._guard_wav_in_notes(target)

        with self.write_lock():
            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_", suffix=".part")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target)
            except BaseException:
                # Leave the prior content intact; remove the orphaned temp file.
                try:
                    os.unlink(tmp_path)
                except OSError as exc:
                    if exc.errno != errno.ENOENT:
                        raise
                raise
        return target

    # ------------------------------------------------------------------
    # Public write APIs
    # ------------------------------------------------------------------

    def write_notes(self, path_or_meeting_id: str, content: str) -> str:
        """Atomically write notes content and return the absolute path written.

        Accepts either an explicit relative filename / full path (preferred and
        reusable), or a bare meeting id, in which case the canonical
        ``meeting_notes_{id}.md`` filename under the notes dir is used.
        Versioning logic lives in the higher-level ``DocumentService``; this API
        just writes the given target atomically.
        """
        if path_or_meeting_id.endswith(".md") or os.sep in path_or_meeting_id or (
            os.altsep and os.altsep in path_or_meeting_id
        ):
            target = self._resolve_notes_target(path_or_meeting_id)
        else:
            target = self._resolve_notes_target(
                f"meeting_notes_{path_or_meeting_id}.md"
            )
        return self._atomic_write_text(target, content)

    def write_transcript(
        self, meeting_id: str, json_obj: object, text: str
    ) -> Tuple[str, str]:
        """Atomically write the transcript JSON and plain-text files.

        Writes ``transcript_{id}.json`` and ``transcript_{id}.txt`` into the
        notes dir (Req 8.3). Returns ``(json_path, txt_path)``.
        """
        json_target = self._resolve_notes_target(f"transcript_{meeting_id}.json")
        txt_target = self._resolve_notes_target(f"transcript_{meeting_id}.txt")

        # Serialize both, then write under a single lock span so the pair is
        # written together relative to other writers.
        json_data = json.dumps(json_obj, indent=2, ensure_ascii=False)
        with self.write_lock():
            json_path = self._atomic_write_text(json_target, json_data)
            txt_path = self._atomic_write_text(txt_target, text)
        return json_path, txt_path

    def write_captions(self, meeting_id: str, captions: Sequence[Caption]) -> str:
        """Atomically persist live captions as ``captions_{id}.json``.

        Each caption is serialized with ``start``, ``end``, ``text`` and
        ``status`` so the file round-trips back into :class:`Caption` objects via
        :meth:`read_captions` (Req 2.9). Returns the absolute path written.
        """
        target = self._resolve_notes_target(f"captions_{meeting_id}.json")
        payload = [
            {
                "start": c.start,
                "end": c.end,
                "text": c.text,
                "status": c.status,
            }
            for c in captions
        ]
        data = json.dumps(payload, indent=2, ensure_ascii=False)
        return self._atomic_write_text(target, data)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read_text(self, path: str) -> str:
        """Read and return the UTF-8 text content of ``path``.

        Relative paths are resolved under the notes dir; absolute paths are used
        as-is.
        """
        target = self._resolve_notes_target(path)
        with open(target, "r", encoding="utf-8") as f:
            return f.read()

    def read_captions(self, meeting_id_or_path: str) -> List[Caption]:
        """Read persisted captions back into :class:`Caption` objects (Req 2.9).

        Accepts either a meeting id (resolving to ``captions_{id}.json`` under the
        notes dir) or an explicit path.
        """
        if meeting_id_or_path.endswith(".json") or os.sep in meeting_id_or_path or (
            os.altsep and os.altsep in meeting_id_or_path
        ):
            target = self._resolve_notes_target(meeting_id_or_path)
        else:
            target = self._resolve_notes_target(
                f"captions_{meeting_id_or_path}.json"
            )
        raw = self.read_text(target)
        records: Iterable[dict] = json.loads(raw)
        return [
            Caption(
                start=rec["start"],
                end=rec["end"],
                text=rec["text"],
                status=rec["status"],
            )
            for rec in records
        ]
