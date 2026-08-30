"""Configuration for the LLM path. Immutable, validated at construction."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM_PROMPT = REPO_ROOT / "pi" / "prompts" / "marvin.system.md"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"

# Two to four sentences (rule 8) is well under this; the cap only stops runaways.
DEFAULT_MAX_TOKENS = 200
DEFAULT_TEMPERATURE = 0.75
DEFAULT_TOP_P = 0.9
DEFAULT_REPEAT_PENALTY = 1.12
DEFAULT_TIMEOUT_S = 180.0
# -1 lets the server pick. Pin it for a reproducible cadence-eval run.
DEFAULT_SEED = -1
DEFAULT_MAX_TURNS = 8


class ConfigError(ValueError):
    """Raised when configuration is out of range or unusable."""


@dataclass(frozen=True)
class BrainConfig:
    """Everything the llama-server client needs."""

    base_url: str = DEFAULT_BASE_URL
    system_prompt_path: Path = DEFAULT_SYSTEM_PROMPT
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P
    repeat_penalty: float = DEFAULT_REPEAT_PENALTY
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_turns: int = DEFAULT_MAX_TURNS
    request_timeout_s: float = DEFAULT_TIMEOUT_S
    seed: int = DEFAULT_SEED
    stop: tuple[str, ...] = field(default_factory=lambda: ("\nUser:", "\nMarvin:"))

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ConfigError(f"base_url must be an http(s) URL, got {self.base_url!r}")
        if not 0.0 <= self.temperature <= 2.0:
            raise ConfigError(f"temperature must be in [0, 2], got {self.temperature}")
        if not 0.0 < self.top_p <= 1.0:
            raise ConfigError(f"top_p must be in (0, 1], got {self.top_p}")
        if self.max_tokens < 1:
            raise ConfigError(f"max_tokens must be >= 1, got {self.max_tokens}")
        if self.max_turns < 1:
            raise ConfigError(f"max_turns must be >= 1, got {self.max_turns}")
        if self.request_timeout_s <= 0:
            raise ConfigError(f"request_timeout_s must be > 0, got {self.request_timeout_s}")

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/chat/completions"

    @property
    def health_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/health"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> BrainConfig:
        """Build from MARVIN_* environment variables, falling back to defaults."""
        source = os.environ if env is None else env
        return cls(
            base_url=source.get("MARVIN_LLM_URL", DEFAULT_BASE_URL),
            system_prompt_path=Path(source.get("MARVIN_SYSTEM_PROMPT", str(DEFAULT_SYSTEM_PROMPT))),
            temperature=_as_float(source, "MARVIN_TEMPERATURE", DEFAULT_TEMPERATURE),
            top_p=_as_float(source, "MARVIN_TOP_P", DEFAULT_TOP_P),
            repeat_penalty=_as_float(source, "MARVIN_REPEAT_PENALTY", DEFAULT_REPEAT_PENALTY),
            max_tokens=_as_int(source, "MARVIN_MAX_TOKENS", DEFAULT_MAX_TOKENS),
            max_turns=_as_int(source, "MARVIN_MAX_TURNS", DEFAULT_MAX_TURNS),
            request_timeout_s=_as_float(source, "MARVIN_TIMEOUT_S", DEFAULT_TIMEOUT_S),
            seed=_as_int(source, "MARVIN_SEED", DEFAULT_SEED),
        )


def _as_float(source: dict[str, str] | os._Environ, key: str, fallback: float) -> float:
    raw = source.get(key)
    if raw is None:
        return fallback
    try:
        return float(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from error


def _as_int(source: dict[str, str] | os._Environ, key: str, fallback: int) -> int:
    raw = source.get(key)
    if raw is None:
        return fallback
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from error
