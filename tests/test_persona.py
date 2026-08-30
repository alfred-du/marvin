"""Prompt assembly, the rolling window, and sigh interception."""

from __future__ import annotations

import pytest

from marvind import persona
from marvind.config import DEFAULT_EXAMPLES, DEFAULT_SYSTEM_PROMPT
from marvind.persona import Conversation, Example, Persona, PersonaError, Segment, Turn

BARE = Persona("SYSTEM")


def test_conversation_drops_the_oldest_turn_once_the_window_is_full():
    # Arrange
    conversation = Conversation(max_turns=2)

    # Act
    conversation = conversation.with_exchange("hello", "oh").with_turn(Turn("user", "again"))

    # Assert
    assert [turn.content for turn in conversation.turns] == ["oh", "again"]


def test_with_turn_returns_a_new_conversation_and_leaves_the_original_alone():
    original = Conversation()
    updated = original.with_turn(Turn("user", "hello"))
    assert original.turns == ()
    assert updated.turns != original.turns


def test_cleared_empties_the_window():
    conversation = Conversation().with_exchange("hello", "oh")
    assert conversation.cleared().turns == ()


def test_turn_rejects_an_unknown_role():
    with pytest.raises(PersonaError):
        Turn("system", "you are marvin")


def test_turn_rejects_empty_content():
    with pytest.raises(PersonaError):
        Turn("user", "   ")


def test_conversation_rejects_a_zero_length_window():
    with pytest.raises(PersonaError):
        Conversation(max_turns=0)


def test_build_messages_puts_system_first_history_next_and_the_new_turn_last():
    conversation = Conversation().with_exchange("hello", "oh")
    messages = persona.build_messages(BARE, conversation, "  what is the weather  ")

    assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] == "SYSTEM"
    assert messages[-1]["content"] == "what is the weather"


def test_examples_are_replayed_as_real_turns_between_system_and_history():
    # The fixed prefix must come first, or the KV cache is invalidated every turn.
    marvin = Persona("SYSTEM", (Example("two plus two?", "Four. Ask me something hard."),))
    conversation = Conversation().with_exchange("hello", "oh")

    messages = persona.build_messages(marvin, conversation, "what time is it")

    assert [message["role"] for message in messages] == [
        "system", "user", "assistant", "user", "assistant", "user",
    ]
    assert messages[1]["content"] == "two plus two?"
    assert messages[2]["content"] == "Four. Ask me something hard."
    assert messages[3]["content"] == "hello"


def test_build_messages_rejects_an_empty_user_turn():
    with pytest.raises(PersonaError):
        persona.build_messages(BARE, Conversation(), "")


def test_persona_rejects_an_empty_system_prompt():
    with pytest.raises(PersonaError):
        Persona("  ")


def test_example_rejects_an_empty_side():
    with pytest.raises(PersonaError):
        Example("hello", "  ")


def test_load_system_prompt_reads_the_shipped_prompt():
    prompt = persona.load_system_prompt(DEFAULT_SYSTEM_PROMPT)
    assert "Paranoid Android" in prompt


def test_load_persona_reads_the_shipped_prompt_and_examples():
    marvin = persona.load_persona(DEFAULT_SYSTEM_PROMPT, DEFAULT_EXAMPLES)
    assert "Paranoid Android" in marvin.system_prompt
    assert len(marvin.examples) >= 8


def test_the_shipped_examples_cover_the_categories_that_failed():
    marvin = persona.load_persona(DEFAULT_SYSTEM_PROMPT, DEFAULT_EXAMPLES)
    prompts = " ".join(example.user.lower() for example in marvin.examples)
    for category in ("capital", "lights", "thanks", "morning", "help", "good day"):
        assert category in prompts, f"no few-shot covers {category!r}"


def test_load_examples_raises_on_a_missing_file(tmp_path):
    with pytest.raises(PersonaError):
        persona.load_examples(tmp_path / "absent.json")


def test_load_examples_raises_when_the_file_defines_none(tmp_path):
    empty = tmp_path / "examples.json"
    empty.write_text('{"examples": []}')
    with pytest.raises(PersonaError):
        persona.load_examples(empty)


def test_load_examples_raises_on_a_malformed_entry(tmp_path):
    broken = tmp_path / "examples.json"
    broken.write_text('{"examples": [{"user": "hello"}]}')
    with pytest.raises(PersonaError):
        persona.load_examples(broken)


def test_load_system_prompt_raises_on_a_missing_file(tmp_path):
    with pytest.raises(PersonaError):
        persona.load_system_prompt(tmp_path / "absent.md")


def test_load_system_prompt_raises_on_an_empty_file(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("   ")
    with pytest.raises(PersonaError):
        persona.load_system_prompt(empty)


def test_intercept_sighs_splits_speech_around_the_marker():
    segments = persona.intercept_sighs("Four. <sigh> I suppose you wanted it quickly.")
    assert segments == (
        Segment("speech", "Four."),
        Segment("sigh"),
        Segment("speech", "I suppose you wanted it quickly."),
    )


@pytest.mark.parametrize("marker", ["<sigh>", "<SIGH>", "*sighs*", "[sigh]", "(sighs)"])
def test_intercept_sighs_accepts_the_spellings_a_small_model_drifts_into(marker):
    segments = persona.intercept_sighs(f"Four. {marker} Quickly, too.")
    assert [segment.kind for segment in segments] == ["speech", "sigh", "speech"]


def test_intercept_sighs_handles_a_reply_with_no_sigh():
    assert persona.intercept_sighs("Four.") == (Segment("speech", "Four."),)


def test_intercept_sighs_handles_a_leading_sigh():
    assert persona.intercept_sighs("<sigh> Four.") == (Segment("sigh"), Segment("speech", "Four."))


def test_strip_sighs_returns_words_alone():
    assert persona.strip_sighs("Four. *sighs* Quickly, too.") == "Four. Quickly, too."


def test_render_segments_marks_the_splice_point_for_the_terminal():
    segments = persona.intercept_sighs("Four. <sigh> Quickly.")
    assert persona.render_segments(segments) == "Four. [sigh] Quickly."
