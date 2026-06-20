"""Core backend data models and transcript-shape helpers.

This module defines the dataclasses and transcript-shape helpers shared across
the live-transcription web-UI backend (Task 2.1):

- :class:`Caption` - a single live caption (frozen; identity for de-dup is ``start``).
- :class:`SessionState` - the recording session state surfaced over the API/WS.
- :class:`StopResult` - the result of stopping a recording.
- :class:`AppConfig` - the applied live/transcription/notes configuration.
- :class:`MeetingSummary` / :class:`NotesVersion` - history + version metadata.
- ``TranscriptResult`` shape helpers - :func:`build_transcript_result`,
  :func:`validate_transcript_result`, and :func:`extract_transcript_text` for the
  shared AWS-Transcribe-compatible schema where
  ``results.transcripts[0].transcript`` is a ``str``.

The transcript shape intentionally aligns with the structure produced by the
test ``FakeTranscriber`` (``webapp/backend/tests/fake_transcriber.py``) and the
existing batch services, so notes generation is source-agnostic
(Req 3.1, 2.4, 2.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Caption
# ---------------------------------------------------------------------------

CaptionStatus = Literal["interim", "final"]


@dataclass(frozen=True)
class Caption:
    """A single live transcription caption.

    Attributes:
        start: Seconds from recording start. Identity for de-duplication /
            replacement is this ``start`` timestamp (Req 1.7).
        end: Seconds from recording start; ``end >= start``.
        text: The transcribed text for this caption.
        status: ``"interim"`` (subject to revision) or ``"final"`` (Req 1.2).

    The dataclass is frozen so captions are hashable and safe to store in
    de-duplicated collections keyed by ``start``.
    """

    start: float
    end: float
    text: str
    status: CaptionStatus

    def __post_init__(self) -> None:
        if self.status not in ("interim", "final"):
            raise ValueError(
                f"Caption.status must be 'interim' or 'final', got {self.status!r}"
            )
        if self.end < self.start:
            raise ValueError(
                f"Caption.end ({self.end}) must be >= start ({self.start})"
            )


# ---------------------------------------------------------------------------
# SessionState
# ---------------------------------------------------------------------------

RecordingState = Literal["idle", "recording", "paused", "finalizing"]


@dataclass
class SessionState:
    """Server-side recording session state surfaced to the frontend.

    Attributes:
        state: The recording state-machine value.
        meeting_id: ``YYYYMMDD_HHMMSS`` id assigned at start, else ``None``.
        device_id: The selected input device id, else ``None``.
        duration_seconds: Elapsed recorded (non-paused) duration in seconds.
        started_at: ISO-8601 start timestamp, else ``None``.
        final_progress: Final-pass progress (0..100) while finalizing, else ``None``.
    """

    state: RecordingState
    meeting_id: Optional[str] = None
    device_id: Optional[int] = None
    duration_seconds: float = 0.0
    started_at: Optional[str] = None
    final_progress: Optional[int] = None


# ---------------------------------------------------------------------------
# StopResult
# ---------------------------------------------------------------------------


@dataclass
class StopResult:
    """The outcome of stopping a recording.

    Attributes:
        meeting_id: The meeting id of the stopped recording, else ``None``.
        recording_path: Path to the WAV file (in ``recordings/`` only), else ``None``.
        has_recording: True when a non-empty recording file is present (Req 2.1/2.2).
        was_silent: True when the recording was classified as silent (Req 5.8).
        peak_amplitude: The peak absolute sample amplitude observed.
    """

    meeting_id: Optional[str] = None
    recording_path: Optional[str] = None
    has_recording: bool = False
    was_silent: bool = False
    peak_amplitude: int = 0


# ---------------------------------------------------------------------------
# AppConfig
# ---------------------------------------------------------------------------

TranscriptionServiceId = Literal["whisper", "aws", "mac"]
WhisperModelSize = Literal["tiny", "base", "small", "medium", "large"]


@dataclass
class AppConfig:
    """The applied live/transcription/notes configuration.

    Validated against allowed option sets by ``ConfigService`` (Req 6.1, 6.3);
    the literal types document the allowed values for static checkers.
    """

    transcription_service: TranscriptionServiceId
    whisper_model_size: WhisperModelSize
    ai_model_id: str
    input_device_id: Optional[int] = None
    live_window_seconds: float = 5.0
    live_overlap_seconds: float = 2.0
    final_pass_max_attempts: int = 2
    silence_threshold: int = 30
    silence_fraction_threshold: float = 0.95


# ---------------------------------------------------------------------------
# MeetingSummary / NotesVersion
# ---------------------------------------------------------------------------


@dataclass
class MeetingSummary:
    """A meeting history entry (maps onto ``VersionManager`` metadata).

    Attributes:
        meeting_id: The meeting id (``YYYYMMDD_HHMMSS``).
        display_date: Human-readable meeting date for the history list.
        title: The meeting title.
        latest_version: The highest saved notes version number.
    """

    meeting_id: str
    display_date: str
    title: str
    latest_version: int


@dataclass
class NotesVersion:
    """A single saved notes version of a meeting.

    Attributes:
        version_num: The version number.
        name: The version display name.
        creation_time: ISO-8601 creation timestamp.
        is_default: Whether this is the default/active version.
    """

    version_num: int
    name: str
    creation_time: str
    is_default: bool


# ---------------------------------------------------------------------------
# TranscriptResult shape helpers
# ---------------------------------------------------------------------------

# A segment is (start_seconds, end_seconds, text). Mirrors the FakeTranscriber.
Segment = Tuple[float, float, str]


class TranscriptResultError(ValueError):
    """Raised when a transcript object does not conform to the shared schema."""


def build_transcript_result(segments: Sequence[Segment]) -> dict:
    """Build a shared AWS-Transcribe-compatible transcript dict from segments.

    The shape matches what the test ``FakeTranscriber`` produces:
    ``results.transcripts[0].transcript`` is the space-joined segment text (a
    ``str``), and ``results.items`` contains one pronunciation item per word
    with timing derived evenly across each segment's duration. This is the
    canonical builder for production code paths (the live engine's persisted
    output normalizes to this shape).
    """
    segments = list(segments)
    transcript_text = " ".join(text.strip() for _, _, text in segments).strip()

    items: List[dict] = []
    aws_segments: List[dict] = []
    speaker_label = "spk_0"

    for start, end, text in segments:
        words = text.split()
        duration = max(end - start, 0.0)
        word_duration = duration / max(len(words), 1)
        seg_item_indices: List[int] = []
        for j, word in enumerate(words):
            word_start = start + j * word_duration
            word_end = word_start + word_duration
            items.append(
                {
                    "start_time": f"{word_start:.3f}",
                    "end_time": f"{word_end:.3f}",
                    "type": "pronunciation",
                    "alternatives": [{"content": word, "confidence": "1.0"}],
                    "speaker_label": speaker_label,
                }
            )
            seg_item_indices.append(len(items) - 1)
        aws_segments.append(
            {
                "speaker_label": speaker_label,
                "start_time": f"{start:.3f}",
                "end_time": f"{end:.3f}",
                "items": seg_item_indices,
            }
        )

    return {
        "jobName": "live-transcription",
        "status": "COMPLETED",
        "results": {
            "transcripts": [{"transcript": transcript_text}],
            "items": items,
            "speaker_labels": {
                "speakers": [{"speaker_label": speaker_label}],
                "segments": aws_segments,
            },
        },
    }


def build_transcript_result_from_text(text: str) -> dict:
    """Build a minimal conforming transcript dict from a plain transcript string.

    Useful for normalizing live-caption fallback output into the shared schema
    without per-word timing.
    """
    transcript_text = (text or "").strip()
    return {
        "jobName": "live-transcription",
        "status": "COMPLETED",
        "results": {
            "transcripts": [{"transcript": transcript_text}],
            "items": [],
            "speaker_labels": {"speakers": [], "segments": []},
        },
    }


def validate_transcript_result(obj: Any) -> bool:
    """Validate that ``obj`` conforms to the shared transcript schema.

    The schema requires ``obj["results"]["transcripts"][0]["transcript"]`` to be
    a ``str`` (Req 3.1). Returns ``True`` when valid; raises
    :class:`TranscriptResultError` describing the first violation otherwise so
    callers can choose to assert or catch.
    """
    if not isinstance(obj, dict):
        raise TranscriptResultError(
            f"transcript result must be a dict, got {type(obj).__name__}"
        )

    results = obj.get("results")
    if not isinstance(results, dict):
        raise TranscriptResultError(
            "transcript result missing dict 'results' key"
        )

    transcripts = results.get("transcripts")
    if not isinstance(transcripts, list) or len(transcripts) == 0:
        raise TranscriptResultError(
            "transcript result 'results.transcripts' must be a non-empty list"
        )

    first = transcripts[0]
    if not isinstance(first, dict):
        raise TranscriptResultError(
            "transcript result 'results.transcripts[0]' must be a dict"
        )

    transcript = first.get("transcript")
    if not isinstance(transcript, str):
        raise TranscriptResultError(
            "transcript result 'results.transcripts[0].transcript' must be a str, "
            f"got {type(transcript).__name__}"
        )

    return True


def is_valid_transcript_result(obj: Any) -> bool:
    """Boolean variant of :func:`validate_transcript_result` (never raises)."""
    try:
        return validate_transcript_result(obj)
    except TranscriptResultError:
        return False


def extract_transcript_text(obj: Any) -> str:
    """Return ``results.transcripts[0].transcript`` after validating the shape.

    Raises :class:`TranscriptResultError` if ``obj`` does not conform.
    """
    validate_transcript_result(obj)
    return obj["results"]["transcripts"][0]["transcript"]
