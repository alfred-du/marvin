"""llama-server client.

Talks to llama.cpp's OpenAI-compatible endpoint over stdlib HTTP, so the Pi
needs no third-party runtime dependency. The SSE decoding is factored into
pure functions that take an iterable of lines, which is what makes the whole
streaming path testable with no server running.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from marvind import sentences
from marvind.config import BrainConfig

SSE_DATA_PREFIX = "data:"
SSE_DONE = "[DONE]"
HEALTH_POLL_INTERVAL_S = 0.5
JSON_CONTENT_TYPE = "application/json"


class BrainError(RuntimeError):
    """Raised when the model server is unreachable or speaks nonsense."""


@dataclass(frozen=True)
class Reply:
    """A finished completion, with the stage timings that Phase 3 will care about."""

    text: str
    sentences: tuple[str, ...]
    first_token_s: float
    first_sentence_s: float
    total_s: float


def build_payload(
    config: BrainConfig,
    messages: Sequence[dict[str, str]],
    *,
    stream: bool,
) -> dict[str, object]:
    """The request body. Extra llama.cpp sampling keys are ignored by other servers."""
    if not messages:
        raise BrainError("messages must not be empty")
    return {
        "messages": list(messages),
        "stream": stream,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "repeat_penalty": config.repeat_penalty,
        "max_tokens": config.max_tokens,
        "stop": list(config.stop),
        "seed": config.seed,
    }


def iter_deltas(lines: Iterable[bytes | str]) -> Iterator[str]:
    """Decode an SSE line stream into content deltas."""
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line or not line.startswith(SSE_DATA_PREFIX):
            continue

        payload = line[len(SSE_DATA_PREFIX) :].strip()
        if payload == SSE_DONE:
            return

        try:
            event = json.loads(payload)
        except json.JSONDecodeError as error:
            raise BrainError(f"malformed SSE payload from server: {payload[:120]!r}") from error

        if "error" in event:
            raise BrainError(f"server reported an error: {event['error']}")

        for choice in event.get("choices", ()):
            content = (choice.get("delta") or {}).get("content")
            if content:
                yield content


def stream_deltas(
    config: BrainConfig,
    messages: Sequence[dict[str, str]],
) -> Iterator[str]:
    """Yield token deltas as the server produces them."""
    request = urllib.request.Request(
        config.chat_url,
        data=json.dumps(build_payload(config, messages, stream=True)).encode("utf-8"),
        headers={"Content-Type": JSON_CONTENT_TYPE, "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.request_timeout_s) as response:
            yield from iter_deltas(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:200]
        raise BrainError(f"llama-server returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise BrainError(
            f"cannot reach llama-server at {config.base_url}: {error.reason}. Is it running?"
        ) from error


def stream_sentences(
    config: BrainConfig,
    messages: Sequence[dict[str, str]],
) -> Iterator[str]:
    """Yield whole sentences as soon as each one completes.

    This is mechanism 2 of MVP.md section 5. Piper is handed a sentence while
    the model is still generating the next one.
    """
    state = sentences.SplitState()
    for delta in stream_deltas(config, messages):
        state, completed = sentences.feed(state, delta)
        yield from completed
    _, tail = sentences.flush(state)
    yield from tail


def generate(
    config: BrainConfig,
    messages: Sequence[dict[str, str]],
    *,
    on_sentence: "callable[[str], None] | None" = None,
) -> Reply:
    """Stream a full reply, timing the boundaries Phase 3 gates on."""
    started = time.perf_counter()
    first_token_s = 0.0
    first_sentence_s = 0.0
    collected: list[str] = []

    state = sentences.SplitState()
    for delta in stream_deltas(config, messages):
        if not first_token_s:
            first_token_s = time.perf_counter() - started
        state, completed = sentences.feed(state, delta)
        for sentence in completed:
            if not first_sentence_s:
                first_sentence_s = time.perf_counter() - started
            collected.append(sentence)
            if on_sentence is not None:
                on_sentence(sentence)

    _, tail = sentences.flush(state)
    for sentence in tail:
        if not first_sentence_s:
            first_sentence_s = time.perf_counter() - started
        collected.append(sentence)
        if on_sentence is not None:
            on_sentence(sentence)

    if not collected:
        raise BrainError("llama-server produced no output")

    return Reply(
        text=" ".join(collected),
        sentences=tuple(collected),
        first_token_s=first_token_s,
        first_sentence_s=first_sentence_s,
        total_s=time.perf_counter() - started,
    )


def wait_for_server(config: BrainConfig, timeout_s: float = 120.0) -> None:
    """Block until /health reports ready, or raise. Used at daemon start."""
    deadline = time.monotonic() + timeout_s
    last_error = "no attempt made"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(config.health_url, timeout=5.0) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except urllib.error.HTTPError as error:
            last_error = f"HTTP {error.code}"  # 503 while the model loads
        except urllib.error.URLError as error:
            last_error = str(error.reason)
        time.sleep(HEALTH_POLL_INTERVAL_S)
    raise BrainError(f"llama-server at {config.base_url} not ready after {timeout_s}s: {last_error}")
