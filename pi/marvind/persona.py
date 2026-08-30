"""Prompt assembly, the rolling context window, and <sigh> interception.

This is the only module that knows what Marvin is. It holds no I/O beyond
reading the system prompt off disk, so the whole of it is testable without a
model server.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

USER = "user"
ASSISTANT = "assistant"
SYSTEM = "system"
VALID_ROLES = frozenset({USER, ASSISTANT})

DEFAULT_MAX_TURNS = 8

# The model is told to emit the literal token <sigh>. Small models drift, so
# the common stage-direction spellings are accepted too and normalised away.
SIGH_PATTERN = re.compile(r"<\s*sighs?\s*>|\*\s*sighs?\s*\*|\[\s*sighs?\s*\]|\(\s*sighs?\s*\)", re.IGNORECASE)

SPEECH = "speech"
SIGH = "sigh"

SIGH_DISPLAY = "[sigh]"


class PersonaError(RuntimeError):
    """Raised when the persona cannot be assembled."""


@dataclass(frozen=True)
class Turn:
    """One utterance in the conversation."""

    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise PersonaError(f"role must be one of {sorted(VALID_ROLES)}, got {self.role!r}")
        if not self.content.strip():
            raise PersonaError("turn content must not be empty")


@dataclass(frozen=True)
class Conversation:
    """A rolling window of turns. Never mutated; every change returns a new one."""

    turns: tuple[Turn, ...] = ()
    max_turns: int = DEFAULT_MAX_TURNS

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise PersonaError(f"max_turns must be >= 1, got {self.max_turns}")

    def with_turn(self, turn: Turn) -> Conversation:
        """Append a turn, dropping the oldest once the window is full."""
        return replace(self, turns=(self.turns + (turn,))[-self.max_turns :])

    def with_exchange(self, user_text: str, assistant_text: str) -> Conversation:
        return self.with_turn(Turn(USER, user_text)).with_turn(Turn(ASSISTANT, assistant_text))

    def cleared(self) -> Conversation:
        return replace(self, turns=())


@dataclass(frozen=True)
class Segment:
    """A stretch of output bound for one renderer: synthesised speech, or a splice."""

    kind: str
    text: str = ""


def load_system_prompt(path: Path) -> str:
    """Read the system prompt, failing loudly rather than running personality-free."""
    try:
        prompt = Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise PersonaError(f"cannot read system prompt at {path}: {error}") from error
    if not prompt:
        raise PersonaError(f"system prompt at {path} is empty")
    return prompt


def build_messages(
    system_prompt: str,
    conversation: Conversation,
    user_text: str,
) -> tuple[dict[str, str], ...]:
    """Assemble the chat payload: system prompt, rolling window, then this turn."""
    if not system_prompt.strip():
        raise PersonaError("system prompt must not be empty")
    if not user_text.strip():
        raise PersonaError("user text must not be empty")

    history = tuple({"role": turn.role, "content": turn.content} for turn in conversation.turns)
    return (
        {"role": SYSTEM, "content": system_prompt},
        *history,
        {"role": USER, "content": user_text.strip()},
    )


def intercept_sighs(text: str) -> tuple[Segment, ...]:
    """Split text into speech and sigh segments.

    Piper never sees a sigh; MVP.md section 6.2 splices a recorded one into the
    PCM instead. Until the voice chain exists, the segment list is the seam.
    """
    segments: list[Segment] = []
    cursor = 0
    for match in SIGH_PATTERN.finditer(text):
        speech = text[cursor : match.start()].strip()
        if speech:
            segments.append(Segment(SPEECH, speech))
        segments.append(Segment(SIGH))
        cursor = match.end()

    tail = text[cursor:].strip()
    if tail:
        segments.append(Segment(SPEECH, tail))
    return tuple(segments)


def strip_sighs(text: str) -> str:
    """The reply as words alone. What the cadence eval scores."""
    return " ".join(
        segment.text for segment in intercept_sighs(text) if segment.kind == SPEECH
    ).strip()


def render_segments(segments: tuple[Segment, ...]) -> str:
    """Human-readable rendering for the terminal, standing in for audio."""
    return " ".join(
        SIGH_DISPLAY if segment.kind == SIGH else segment.text for segment in segments
    ).strip()
