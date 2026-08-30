"""Streaming sentence splitter."""

from __future__ import annotations

import pytest

from marvind.sentences import SplitState, feed, flush, split


def test_splits_on_full_stop_when_the_next_character_arrives():
    # Arrange
    state = SplitState()

    # Act
    state, emitted = feed(state, "Four. I have a brain")

    # Assert
    assert emitted == ("Four.",)
    assert state.buffer == "I have a brain"


def test_withholds_a_sentence_until_the_terminator_run_is_known_to_be_complete():
    # A trailing "." might still become "...", so the boundary cannot be called yet.
    state, emitted = feed(SplitState(), "It is probably raining.")
    assert emitted == ()

    state, emitted = feed(state, " It usually is.")
    assert emitted == ("It is probably raining.",)


def test_leading_ellipsis_stays_attached_to_the_sentence_it_opens():
    assert split("...Oh. It's you.") == ("...Oh.", "It's you.")


def test_trailing_ellipsis_terminates_a_sentence():
    assert split("I suppose so... Nobody tells me anything.") == (
        "I suppose so...",
        "Nobody tells me anything.",
    )


def test_abbreviation_does_not_end_a_sentence():
    assert split("Dr. Smith left. He was wise.") == ("Dr. Smith left.", "He was wise.")


def test_decimal_number_does_not_end_a_sentence():
    assert split("There are 3.14 reasons. All of them dull.") == (
        "There are 3.14 reasons.",
        "All of them dull.",
    )


def test_closing_quote_after_the_terminator_is_kept_with_the_sentence():
    assert split('He said "go." Then nothing.') == ('He said "go."', "Then nothing.")


def test_flush_emits_an_unterminated_remainder():
    state, _ = feed(SplitState(), "Four. And then")
    state, emitted = flush(state)
    assert emitted == ("And then",)
    assert state.buffer == ""


def test_flush_on_an_empty_state_emits_nothing():
    assert flush(SplitState()) == (SplitState(), ())


def test_token_by_token_streaming_matches_a_single_pass():
    text = "I have no idea. Nobody ever tells me anything. It is probably raining."
    state = SplitState()
    streamed: list[str] = []
    for char in text:
        state, emitted = feed(state, char)
        streamed.extend(emitted)
    _, tail = flush(state)
    streamed.extend(tail)

    assert tuple(streamed) == split(text)


def test_feed_does_not_mutate_the_state_it_is_given():
    original = SplitState(buffer="Four")
    feed(original, ". Five.")
    assert original.buffer == "Four"


def test_feed_rejects_a_non_string_chunk():
    with pytest.raises(TypeError):
        feed(SplitState(), None)
