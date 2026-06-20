"""Shared pytest fixtures for the backend test suite.

Exposes the :class:`FakeTranscriber` helper as fixtures so live-engine,
final-pass, and selection tests can request deterministic transcripts and
configurable failure behavior.
"""

from __future__ import annotations

import pytest

from webapp.backend.tests.fake_transcriber import (
    DEFAULT_SEGMENTS,
    FakeTranscriber,
    build_transcript_result,
)


@pytest.fixture
def fake_transcriber() -> FakeTranscriber:
    """A FakeTranscriber that always succeeds with deterministic segments."""
    return FakeTranscriber()


@pytest.fixture
def make_fake_transcriber():
    """Factory fixture to build FakeTranscribers with custom config.

    Example::

        def test_retries(make_fake_transcriber):
            t = make_fake_transcriber(fail_times=2)
            ...
    """

    def _make(segments=None, fail_times: int = 0, id: str = "fake") -> FakeTranscriber:
        kwargs = {"fail_times": fail_times, "id": id}
        if segments is not None:
            kwargs["segments"] = list(segments)
        return FakeTranscriber(**kwargs)

    return _make


__all__ = [
    "fake_transcriber",
    "make_fake_transcriber",
    "DEFAULT_SEGMENTS",
    "build_transcript_result",
]
