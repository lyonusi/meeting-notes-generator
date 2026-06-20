"""Shared ``FakeTranscriber`` test helper.

A deterministic, dependency-free stand-in for the real transcription services.
It conforms to the same call shape as the existing services
(``transcribe(audio_file_path, callback=None)``) and returns the shared
AWS-Transcribe-compatible ``TranscriptResult`` structure:

    {
      "results": {
        "transcripts": [{"transcript": <str>}],
        "items": [...],
        "speaker_labels": {"speakers": [...], "segments": [...]},
      }
    }

It is used by the live-engine, final-pass, and selection property tests
(Tasks 6, 9, and others) to exercise retries and transcript selection without
loading any models or making network calls.

Key features:

- **Deterministic output** - the same ``segments`` always produce the same
  transcript dict, so property tests can assert exact equality.
- **Fail-K-times-then-succeed** - construct with ``fail_times=K`` to make the
  first ``K`` ``transcribe`` calls raise ``TranscriberError`` before the
  ``(K + 1)``-th call succeeds. This drives the final-pass retry property
  (Property 7) and resilience tests.
- **Call accounting** - ``call_count`` records how many times ``transcribe``
  was invoked (including failed attempts) so tests can assert attempt counts.
- **Progress callback** - if a ``callback`` is supplied it is invoked with
  ``(message, percent)`` pairs ending at ``100`` on success, matching the
  existing services and feeding the progress-monotonicity property (Property 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple


class TranscriberError(RuntimeError):
    """Raised by :class:`FakeTranscriber` when a call is configured to fail."""


# A segment is (start_seconds, end_seconds, text).
Segment = Tuple[float, float, str]

# Default deterministic segments used when none are supplied.
DEFAULT_SEGMENTS: List[Segment] = [
    (0.0, 2.0, "hello world"),
    (2.0, 4.0, "this is a test"),
    (4.0, 6.0, "of the transcriber"),
]


def build_transcript_result(segments: Sequence[Segment]) -> dict:
    """Build the shared AWS-Transcribe-compatible transcript dict from segments.

    ``results.transcripts[0].transcript`` is the space-joined segment text (a
    ``str``), and ``results.items`` contains one pronunciation item per word
    with timing derived evenly across each segment's duration.
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
        "jobName": "fake-transcription",
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


@dataclass
class FakeTranscriber:
    """Deterministic transcription service double for tests.

    Args:
        segments: Deterministic segments to emit. Defaults to
            :data:`DEFAULT_SEGMENTS`.
        fail_times: Number of leading ``transcribe`` calls that raise
            :class:`TranscriberError` before a call succeeds. ``0`` (default)
            means it always succeeds.
        id: Optional identifier mirroring the transcription-service id.
    """

    segments: List[Segment] = field(default_factory=lambda: list(DEFAULT_SEGMENTS))
    fail_times: int = 0
    id: str = "fake"
    call_count: int = field(default=0, init=False)

    def transcribe(
        self,
        audio_file_path: str,
        callback: Optional[Callable[[str, int], None]] = None,
    ) -> dict:
        """Return the deterministic transcript dict, failing ``fail_times`` first.

        Each invocation increments :attr:`call_count`. The first ``fail_times``
        invocations raise :class:`TranscriberError`; subsequent invocations
        return :func:`build_transcript_result` for the configured segments.
        """
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise TranscriberError(
                f"FakeTranscriber configured to fail (attempt {self.call_count} "
                f"of {self.fail_times})"
            )

        if callback:
            callback("Transcribing (fake)...", 50)

        result = build_transcript_result(self.segments)

        if callback:
            callback("Transcription complete!", 100)

        return result

    def reset(self) -> None:
        """Reset the call counter so the failure sequence can be replayed."""
        self.call_count = 0
