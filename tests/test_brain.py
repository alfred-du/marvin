"""llama-server client: payload shape and SSE decoding, with no server running."""

from __future__ import annotations

import json

import pytest

from marvind.brain import BrainError, Reply, build_payload, iter_deltas, stream_sentences
from marvind.config import BrainConfig


def sse(content: str) -> bytes:
    return b"data: " + json.dumps({"choices": [{"delta": {"content": content}}]}).encode()


def test_build_payload_carries_the_sampling_settings_and_the_messages():
    # Arrange
    config = BrainConfig(temperature=0.5, top_p=0.8, max_tokens=64, seed=11)
    messages = [{"role": "user", "content": "hello"}]

    # Act
    payload = build_payload(config, messages, stream=True)

    # Assert
    assert payload["messages"] == messages
    assert payload["stream"] is True
    assert payload["temperature"] == 0.5
    assert payload["top_p"] == 0.8
    assert payload["max_tokens"] == 64
    assert payload["seed"] == 11


def test_build_payload_bans_the_exclamation_token_at_decode():
    # Rule 4 is absolute, so it is enforced rather than requested.
    payload = build_payload(BrainConfig(), [{"role": "user", "content": "hi"}], stream=False)
    assert payload["logit_bias"] == [["!", False]]


def test_build_payload_omits_logit_bias_when_nothing_is_suppressed():
    config = BrainConfig(suppressed_tokens=())
    payload = build_payload(config, [{"role": "user", "content": "hi"}], stream=False)
    assert "logit_bias" not in payload


def test_build_payload_rejects_an_empty_message_list():
    with pytest.raises(BrainError):
        build_payload(BrainConfig(), [], stream=True)


def test_iter_deltas_yields_content_in_order():
    lines = [sse("Four."), b"", sse(" Oh."), b"data: [DONE]"]
    assert list(iter_deltas(lines)) == ["Four.", " Oh."]


def test_iter_deltas_stops_at_done_and_ignores_anything_after():
    lines = [sse("Four."), b"data: [DONE]", sse(" never seen")]
    assert list(iter_deltas(lines)) == ["Four."]


def test_iter_deltas_skips_keepalives_and_comment_lines():
    lines = [b": ping", b"\n", sse("Four."), b"event: message"]
    assert list(iter_deltas(lines)) == ["Four."]


def test_iter_deltas_skips_a_role_only_opening_chunk():
    opener = b'data: {"choices":[{"delta":{"role":"assistant"}}]}'
    assert list(iter_deltas([opener, sse("Four.")])) == ["Four."]


def test_iter_deltas_raises_on_malformed_json():
    with pytest.raises(BrainError, match="malformed SSE"):
        list(iter_deltas([b"data: {not json"]))


def test_iter_deltas_raises_when_the_server_reports_an_error():
    payload = b'data: {"error": {"message": "context exceeded"}}'
    with pytest.raises(BrainError, match="context exceeded"):
        list(iter_deltas([payload]))


def test_iter_deltas_accepts_str_lines_as_well_as_bytes():
    assert list(iter_deltas([sse("Four.").decode()])) == ["Four."]


def test_stream_sentences_reassembles_sentences_across_token_boundaries(monkeypatch):
    # Arrange: tokens split mid-sentence, as they arrive from a real server.
    tokens = ["I have", " no idea.", " Nobody", " tells me anything.", " It is late"]
    monkeypatch.setattr("marvind.brain.stream_deltas", lambda config, messages: iter(tokens))

    # Act
    emitted = list(stream_sentences(BrainConfig(), [{"role": "user", "content": "hi"}]))

    # Assert: the unterminated tail is flushed rather than dropped.
    assert emitted == ["I have no idea.", "Nobody tells me anything.", "It is late"]


def test_generate_raises_when_the_server_produces_nothing(monkeypatch):
    from marvind.brain import generate

    monkeypatch.setattr("marvind.brain.stream_deltas", lambda config, messages: iter(()))
    with pytest.raises(BrainError, match="no output"):
        generate(BrainConfig(), [{"role": "user", "content": "hi"}])


def test_generate_times_the_stage_boundaries_and_calls_back_per_sentence(monkeypatch):
    monkeypatch.setattr(
        "marvind.brain.stream_deltas",
        lambda config, messages: iter(["Four.", " Oh."]),
    )
    seen: list[str] = []

    from marvind.brain import generate

    reply = generate(BrainConfig(), [{"role": "user", "content": "hi"}], on_sentence=seen.append)

    assert isinstance(reply, Reply)
    assert reply.sentences == ("Four.", "Oh.")
    assert reply.text == "Four. Oh."
    assert seen == ["Four.", "Oh."]
    assert 0 < reply.first_token_s <= reply.total_s
    assert 0 < reply.first_sentence_s <= reply.total_s
