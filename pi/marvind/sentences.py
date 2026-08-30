"""Streaming sentence splitter.

Tokens arrive from llama-server one fragment at a time. Piper needs whole
sentences. This module turns the former into the latter without ever waiting
for the full completion, which is the mechanism behind MVP.md section 5.

Everything here is a pure function over an immutable ``SplitState``. Feeding a
chunk returns a new state plus whatever sentences became complete; nothing is
mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

TERMINATORS = frozenset(".!?")

# Characters allowed between the terminator and the following whitespace, so
# that a quoted or parenthesised sentence still closes correctly.
CLOSERS = frozenset("\"')]}”’")

# Trailing words that take a full stop without ending a sentence.
ABBREVIATIONS = frozenset(
    {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "no", "etc", "eg", "ie", "approx"}
)

# A boundary needs at least this many letters before it, so a leading "..." or a
# stray "?" is absorbed into the sentence that follows rather than emitted alone.
MIN_SENTENCE_LETTERS = 2


@dataclass(frozen=True)
class SplitState:
    """Text seen so far that has not yet formed a complete sentence."""

    buffer: str = ""


def feed(state: SplitState, chunk: str) -> tuple[SplitState, tuple[str, ...]]:
    """Absorb a token fragment, returning the new state and completed sentences."""
    if not isinstance(chunk, str):
        raise TypeError(f"chunk must be str, got {type(chunk).__name__}")
    return _drain(replace(state, buffer=state.buffer + chunk))


def flush(state: SplitState) -> tuple[SplitState, tuple[str, ...]]:
    """Emit whatever is left, terminated or not. Call once the stream ends."""
    drained, sentences = _drain(state)
    remainder = drained.buffer.strip()
    if not remainder:
        return SplitState(), sentences
    return SplitState(), sentences + (remainder,)


def split(text: str) -> tuple[str, ...]:
    """Split a complete string. Convenience wrapper over feed + flush."""
    state, sentences = feed(SplitState(), text)
    _, tail = flush(state)
    return sentences + tail


def _drain(state: SplitState) -> tuple[SplitState, tuple[str, ...]]:
    """Pull every complete sentence out of the buffer."""
    buffer = state.buffer
    sentences: list[str] = []
    while True:
        boundary = _find_boundary(buffer)
        if boundary is None:
            break
        sentence, buffer = buffer[:boundary].strip(), buffer[boundary:].lstrip()
        if sentence:
            sentences.append(sentence)
    return SplitState(buffer=buffer), tuple(sentences)


def _find_boundary(buffer: str) -> int | None:
    """Index just past the first real sentence end, or None if there isn't one yet."""
    index = 0
    length = len(buffer)
    while index < length:
        if buffer[index] not in TERMINATORS:
            index += 1
            continue

        run_end = _scan(buffer, index, TERMINATORS)
        close_end = _scan(buffer, run_end, CLOSERS)

        # The run may still be growing ("." could become "..."), and the
        # character that decides the boundary has not arrived. Wait for it.
        if close_end >= length:
            return None

        if not buffer[close_end].isspace():
            index = close_end
            continue

        head = buffer[:close_end]
        is_single_stop = run_end - index == 1 and buffer[index] == "."
        if is_single_stop and _ends_with_abbreviation(buffer[:index]):
            index = close_end
            continue
        if _letter_count(head) < MIN_SENTENCE_LETTERS:
            index = close_end
            continue
        return close_end

    return None


def _scan(buffer: str, start: int, members: frozenset[str]) -> int:
    """Index of the first character at or after ``start`` not in ``members``."""
    index = start
    while index < len(buffer) and buffer[index] in members:
        index += 1
    return index


def _ends_with_abbreviation(head: str) -> bool:
    word = head.rsplit(maxsplit=1)[-1] if head.strip() else ""
    return word.strip(".").lower() in ABBREVIATIONS


def _letter_count(text: str) -> int:
    return sum(1 for char in text if char.isalpha())
