"""ConfigService: applied configuration over ``config.py`` + ``user_settings.json``.

This service (Task 4.1) wraps the existing ``config.py`` defaults
(``TRANSCRIPTION_SERVICE``, ``WHISPER_MODEL_SIZE``, ``BEDROCK_MODEL_ID``),
overlays any persisted values from ``user_settings.json``, and exposes the
applied :class:`~webapp.backend.models.AppConfig` to the rest of the backend.

Responsibilities:

- :meth:`ConfigService.get` - return the current applied config.
- :meth:`ConfigService.update` - validate a patch against the allowed option
  sets, reject out-of-range values while **retaining** the last-applied config,
  and on success apply + persist (Req 6.6, 6.7).
- :meth:`ConfigService.available_models` - list backend AI models via
  ``AWSHandler.list_available_models`` with a graceful offline fallback (Req 6.5).
- :meth:`ConfigService.select_device` - persist the selected input device
  (Req 5.2).
- :meth:`ConfigService.snapshot` - return an immutable copy of the current
  config so an in-flight operation is unaffected by later updates (Req 6.8).

Persistence (Req 6.9): the applied config is written back to
``user_settings.json`` so it survives restarts. Writes **merge** with any
existing keys in that file (e.g. ``output_device``) rather than clobbering
unrelated settings, and use the same key names the existing tkinter app uses
(``input_device``, ``ai_model``) so the two UIs stay compatible.

Model validation (Req 6.7) is **lenient by default** so the config still works
offline: ``ai_model_id`` must be a non-empty string, but it is only required to
be a member of :meth:`available_models` when ``strict_model_validation`` is
enabled. This avoids a hard failure when the Bedrock model list cannot be
fetched (no credentials / offline) while still rejecting obviously invalid
types.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from webapp.backend.models import AppConfig

# Allowed option sets (Req 6.1, 6.3).
ALLOWED_TRANSCRIPTION_SERVICES = ("whisper", "aws", "mac")
ALLOWED_WHISPER_MODEL_SIZES = ("tiny", "base", "small", "medium", "large")

# Default AI models surfaced when the Bedrock list cannot be fetched (offline).
_FALLBACK_MODELS: List[Dict[str, str]] = [
    {"id": "anthropic.claude-v2:1", "name": "Claude 2"},
    {"id": "anthropic.claude-3-sonnet-20240229-v1:0", "name": "Claude 3 Sonnet"},
    {"id": "anthropic.claude-3-haiku-20240307-v1:0", "name": "Claude 3 Haiku"},
]


def _project_root() -> str:
    """Absolute path to the project root (two levels up from this file).

    ``webapp/backend/config_service.py`` -> project root.
    """
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def _default_settings_path() -> str:
    """Default location of ``user_settings.json`` (project root)."""
    return os.path.join(_project_root(), "user_settings.json")


class ConfigValidationError(ValueError):
    """Raised when a config update contains a value outside its allowed set.

    When raised by :meth:`ConfigService.update`, the active configuration is
    left unchanged and nothing is persisted (Req 6.7).
    """


class ConfigService:
    """Applied configuration over ``config.py`` defaults + ``user_settings.json``."""

    def __init__(
        self,
        settings_path: Optional[str] = None,
        *,
        aws_handler: Any = None,
        aws_handler_factory: Optional[Callable[[], Any]] = None,
        models_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        strict_model_validation: bool = False,
    ) -> None:
        """Create a ConfigService.

        Args:
            settings_path: Path to ``user_settings.json``. Defaults to the file
                at the project root (shared with the tkinter app).
            aws_handler: A pre-built ``AWSHandler`` instance (optional). If
                omitted, one is created lazily via ``aws_handler_factory`` only
                when :meth:`available_models` is first called (so construction
                never triggers AWS calls at import/``get`` time).
            aws_handler_factory: Zero-arg callable returning an ``AWSHandler``.
                Defaults to constructing the real ``AWSHandler``. Injectable for
                tests to avoid real AWS calls.
            models_provider: Zero-arg callable returning the model list directly,
                bypassing ``AWSHandler`` entirely. Highest precedence; useful for
                tests and for the API layer to inject a cached list.
            strict_model_validation: When True, ``update`` requires
                ``ai_model_id`` to be a member of :meth:`available_models`. When
                False (default), only a non-empty string is required so the
                service works offline.
        """
        self._settings_path = settings_path or _default_settings_path()
        self._aws_handler = aws_handler
        self._aws_handler_factory = aws_handler_factory
        self._models_provider = models_provider
        self._strict_model_validation = strict_model_validation

        self._lock = threading.RLock()
        # The current applied configuration.
        self._config: AppConfig = self._load_initial_config()

    # ------------------------------------------------------------------
    # Loading / defaults
    # ------------------------------------------------------------------

    def _load_initial_config(self) -> AppConfig:
        """Build the initial config from ``config.py`` defaults + persisted file."""
        defaults = self._defaults_from_config_py()
        persisted = self._read_settings_file()
        return self._merge_into_appconfig(defaults, persisted)

    @staticmethod
    def _defaults_from_config_py() -> AppConfig:
        """Read defaults from the existing top-level ``config.py``."""
        try:
            import config as app_config  # top-level module (added to sys.path)

            transcription_service = getattr(app_config, "TRANSCRIPTION_SERVICE", "whisper")
            whisper_model_size = getattr(app_config, "WHISPER_MODEL_SIZE", "small")
            ai_model_id = getattr(
                app_config, "BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"
            )
        except Exception:
            # Be resilient if config.py is unavailable for any reason.
            transcription_service = "whisper"
            whisper_model_size = "small"
            ai_model_id = "anthropic.claude-3-sonnet-20240229-v1:0"

        return AppConfig(
            transcription_service=transcription_service,
            whisper_model_size=whisper_model_size,
            ai_model_id=ai_model_id,
            input_device_id=None,
        )

    def _read_settings_file(self) -> Dict[str, Any]:
        """Read ``user_settings.json`` if present, else an empty dict."""
        try:
            if os.path.exists(self._settings_path):
                with open(self._settings_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            # Corrupt/unreadable settings should not crash startup; fall back to
            # config.py defaults only.
            pass
        return {}

    @staticmethod
    def _merge_into_appconfig(defaults: AppConfig, persisted: Dict[str, Any]) -> AppConfig:
        """Overlay persisted ``user_settings.json`` values onto ``config.py`` defaults.

        Supports both the existing tkinter key names (``ai_model``,
        ``input_device``) and the ``AppConfig`` field names so either form
        round-trips.
        """
        cfg = copy.deepcopy(defaults)

        if isinstance(persisted.get("transcription_service"), str):
            cfg.transcription_service = persisted["transcription_service"]
        if isinstance(persisted.get("whisper_model_size"), str):
            cfg.whisper_model_size = persisted["whisper_model_size"]

        # AI model: existing app persists under "ai_model"; also accept
        # "ai_model_id".
        ai_model = persisted.get("ai_model_id", persisted.get("ai_model"))
        if isinstance(ai_model, str) and ai_model:
            cfg.ai_model_id = ai_model

        # Input device: existing app persists under "input_device"; also accept
        # "input_device_id".
        device = persisted.get("input_device_id", persisted.get("input_device"))
        if isinstance(device, int) and not isinstance(device, bool):
            cfg.input_device_id = device

        # Advanced tuning fields persisted under their AppConfig names.
        for fld, caster in (
            ("live_window_seconds", float),
            ("live_overlap_seconds", float),
            ("final_pass_max_attempts", int),
            ("silence_threshold", int),
            ("silence_fraction_threshold", float),
        ):
            if fld in persisted and isinstance(persisted[fld], (int, float)) and not isinstance(
                persisted[fld], bool
            ):
                try:
                    setattr(cfg, fld, caster(persisted[fld]))
                except (TypeError, ValueError):
                    pass

        return cfg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self) -> AppConfig:
        """Return the current applied configuration.

        Returns the live object; callers that need isolation from later updates
        should use :meth:`snapshot`.
        """
        with self._lock:
            return self._config

    def snapshot(self) -> AppConfig:
        """Return an immutable (deep-copied) snapshot of the current config.

        An in-flight operation can capture the config at start via this method
        and remain unaffected by later :meth:`update`/:meth:`select_device`
        calls (Req 6.8).
        """
        with self._lock:
            return copy.deepcopy(self._config)

    def update(self, patch: Dict[str, Any]) -> AppConfig:
        """Validate ``patch`` and, if valid, apply + persist it.

        Validates ``transcription_service``, ``whisper_model_size`` and
        ``ai_model_id`` against their allowed option sets (Req 6.6). If any value
        is out of range, raises :class:`ConfigValidationError` and leaves the
        active configuration unchanged with nothing persisted (Req 6.7). On
        success the merged config is applied and written to ``user_settings.json``
        (Req 6.9).

        Args:
            patch: Mapping of config field names to new values. Unknown keys are
                ignored. Accepts both ``ai_model_id``/``ai_model`` and
                ``input_device_id``/``input_device`` spellings.

        Returns:
            The newly applied :class:`AppConfig`.
        """
        if patch is None:
            patch = {}
        if not isinstance(patch, dict):
            raise ConfigValidationError(
                f"config patch must be a dict, got {type(patch).__name__}"
            )

        with self._lock:
            # Build a candidate on a copy so a rejection leaves the live config
            # untouched (Req 6.7).
            candidate = copy.deepcopy(self._config)

            if "transcription_service" in patch:
                value = patch["transcription_service"]
                if value not in ALLOWED_TRANSCRIPTION_SERVICES:
                    raise ConfigValidationError(
                        f"transcription_service {value!r} is not one of "
                        f"{ALLOWED_TRANSCRIPTION_SERVICES}"
                    )
                candidate.transcription_service = value

            if "whisper_model_size" in patch:
                value = patch["whisper_model_size"]
                if value not in ALLOWED_WHISPER_MODEL_SIZES:
                    raise ConfigValidationError(
                        f"whisper_model_size {value!r} is not one of "
                        f"{ALLOWED_WHISPER_MODEL_SIZES}"
                    )
                candidate.whisper_model_size = value

            if "ai_model_id" in patch or "ai_model" in patch:
                value = patch.get("ai_model_id", patch.get("ai_model"))
                self._validate_ai_model_id(value)
                candidate.ai_model_id = value

            if "input_device_id" in patch or "input_device" in patch:
                value = patch.get("input_device_id", patch.get("input_device"))
                candidate.input_device_id = self._validate_device_id(value)

            # Optional advanced numeric tuning fields.
            self._apply_numeric_patch(candidate, patch)

            # All validations passed: commit and persist.
            self._config = candidate
            self._persist()
            return self._config

    def select_device(self, device_id: Optional[int]) -> AppConfig:
        """Persist the selected input device (Req 5.2).

        Args:
            device_id: A non-negative int device index, or ``None`` to clear.

        Returns:
            The updated :class:`AppConfig` with ``input_device_id`` applied. The
            value is persisted to ``user_settings.json`` under ``input_device``
            (the key the existing app uses) and survives restarts until changed.
        """
        with self._lock:
            validated = self._validate_device_id(device_id)
            candidate = copy.deepcopy(self._config)
            candidate.input_device_id = validated
            self._config = candidate
            self._persist()
            return self._config

    def available_models(self) -> List[Dict[str, Any]]:
        """Return the available AI models (Req 6.5).

        Uses ``AWSHandler.list_available_models`` when available, falling back to
        a static default list if the handler cannot be built or the call fails
        (so the UI/config still work offline).
        """
        # 1) Explicit provider wins (tests / cached API list).
        if self._models_provider is not None:
            try:
                models = self._models_provider()
                if isinstance(models, list):
                    return models
            except Exception:
                return list(_FALLBACK_MODELS)
            return list(_FALLBACK_MODELS)

        # 2) Use / lazily build an AWSHandler.
        handler = self._get_aws_handler()
        if handler is None:
            return list(_FALLBACK_MODELS)
        try:
            models = handler.list_available_models()
            if isinstance(models, list) and models:
                return models
        except Exception:
            pass
        return list(_FALLBACK_MODELS)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_aws_handler(self) -> Any:
        """Lazily obtain an ``AWSHandler`` instance, or ``None`` on failure.

        Never raises - any construction error degrades to the offline fallback.
        """
        if self._aws_handler is not None:
            return self._aws_handler
        try:
            if self._aws_handler_factory is not None:
                self._aws_handler = self._aws_handler_factory()
            else:
                from aws_services import AWSHandler  # top-level module

                self._aws_handler = AWSHandler()
        except Exception:
            self._aws_handler = None
        return self._aws_handler

    def _validate_ai_model_id(self, value: Any) -> None:
        """Validate an ``ai_model_id`` candidate.

        Always requires a non-empty string (rejects obviously invalid types).
        When ``strict_model_validation`` is enabled, additionally requires
        membership in :meth:`available_models`. Otherwise membership is not
        enforced so the service works offline (documented leniency for Req 6.7).
        """
        if not isinstance(value, str) or not value.strip():
            raise ConfigValidationError(
                f"ai_model_id must be a non-empty string, got {value!r}"
            )
        if self._strict_model_validation:
            allowed_ids = {
                m.get("id")
                for m in self.available_models()
                if isinstance(m, dict)
            }
            if value not in allowed_ids:
                raise ConfigValidationError(
                    f"ai_model_id {value!r} is not in the available models list"
                )

    @staticmethod
    def _validate_device_id(value: Any) -> Optional[int]:
        """Validate an input-device id: ``None`` or a non-negative int."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigValidationError(
                f"input device id must be an int or None, got {value!r}"
            )
        if value < 0:
            raise ConfigValidationError(
                f"input device id must be non-negative, got {value}"
            )
        return value

    @staticmethod
    def _apply_numeric_patch(candidate: AppConfig, patch: Dict[str, Any]) -> None:
        """Validate + apply optional advanced numeric tuning fields from a patch."""
        numeric_fields = {
            "live_window_seconds": (float, lambda v: v > 0),
            "live_overlap_seconds": (float, lambda v: v >= 0),
            "final_pass_max_attempts": (int, lambda v: v >= 1),
            "silence_threshold": (int, lambda v: v >= 0),
            "silence_fraction_threshold": (float, lambda v: 0.0 <= v <= 1.0),
        }
        for fld, (caster, predicate) in numeric_fields.items():
            if fld not in patch:
                continue
            value = patch[fld]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigValidationError(
                    f"{fld} must be a number, got {value!r}"
                )
            casted = caster(value)
            if not predicate(casted):
                raise ConfigValidationError(
                    f"{fld} value {value!r} is out of range"
                )
            setattr(candidate, fld, casted)

    def _persist(self) -> None:
        """Write the applied config to ``user_settings.json`` (merging existing keys).

        Preserves unrelated keys already in the file (e.g. ``output_device``) and
        uses the existing app's key names (``input_device``, ``ai_model``) so the
        tkinter UI stays compatible (Req 6.9).
        """
        existing = self._read_settings_file()
        merged = dict(existing)

        merged["transcription_service"] = self._config.transcription_service
        merged["whisper_model_size"] = self._config.whisper_model_size
        merged["ai_model"] = self._config.ai_model_id
        merged["input_device"] = self._config.input_device_id

        # Persist advanced tuning fields under their AppConfig names so a reload
        # reproduces the exact applied config.
        merged["live_window_seconds"] = self._config.live_window_seconds
        merged["live_overlap_seconds"] = self._config.live_overlap_seconds
        merged["final_pass_max_attempts"] = self._config.final_pass_max_attempts
        merged["silence_threshold"] = self._config.silence_threshold
        merged["silence_fraction_threshold"] = self._config.silence_fraction_threshold

        # Atomic write: temp file + os.replace to avoid partial/corrupt files.
        tmp_path = f"{self._settings_path}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(merged, f, indent=2)
        os.replace(tmp_path, self._settings_path)
