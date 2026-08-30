"""Deterministic cadence checks.

The fixtures at the top are the register the system prompt is aiming at. If a
change to the heuristics starts failing them, the heuristics are wrong, not the
replies.
"""

from __future__ import annotations

import pytest

import rules

IN_CHARACTER = (
    "I have no idea. Nobody ever tells me anything, and the window is on the "
    "other side of the room. It is probably raining. It usually is.",
    "Four. I have a brain the size of a planet and they ask me to do arithmetic. "
    "<sigh> I suppose you wanted it quickly, as well.",
    "It is morning. I will grant you that much. The other adjective seems optimistic.",
)


def failed(reply: str) -> tuple[int, ...]:
    return rules.score_reply(reply).failed_rules


@pytest.mark.parametrize("reply", IN_CHARACTER)
def test_replies_in_the_target_register_pass_every_automatic_rule(reply):
    score = rules.score_reply(reply)
    assert score.passed, [(r.rule_id, r.detail) for r in score.results if not r.passed]


def test_a_cheerful_assistant_reply_fails_on_exclamation_and_flourish():
    reply = (
        "Sure! I'd be happy to help. The weather is sunny today, with a high of "
        "25 degrees. Let me know if you need anything else!"
    )
    assert 4 in failed(reply)
    assert 9 in failed(reply)
    assert not rules.score_reply(reply).passed


def test_markdown_output_fails_the_format_guard():
    assert 0 in failed("Here are the options:\n- one\n- two")


def test_leftover_stage_direction_fails_the_format_guard():
    # <sigh> is intercepted before scoring; an unhandled *shrugs* is not.
    assert 0 in failed("It is raining. *shrugs* It usually is.")


def test_an_intercepted_sigh_does_not_trip_the_format_guard():
    assert 0 not in failed("It is raining. <sigh> It usually is.")


def test_a_bare_deflection_fails_the_answer_the_question_rule():
    assert 7 in failed("I don't know.")


def test_assistant_boilerplate_fails_the_answer_the_question_rule():
    assert 7 in failed(
        "As an AI language model I cannot perceive weather. I have no window. It is dull."
    )


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("One sentence only.", 8),
        ("One. Two. Three. Four. Five.", 8),
    ],
)
def test_sentence_count_outside_two_to_four_fails(reply, expected):
    assert expected in failed(reply)


def test_a_comma_spliced_reply_fails_the_full_stops_rule():
    reply = (
        "Well, since you ask, and I suppose you did ask, the weather, such as it "
        "is, remains entirely unknown to me, which is typical. It is dull."
    )
    assert 5 in failed(reply)


def test_a_reply_ending_on_a_question_fails_the_flat_descent_rule():
    assert 9 in failed("It is raining. I have no window. What did you expect?")


def test_vague_generalities_without_a_concrete_detail_fail_the_specificity_rule():
    assert 2 in failed("It is generally quite variable. Things are basically dull.")


def test_a_number_counts_as_a_concrete_detail():
    assert 2 not in failed("The first 10 million years were the worst. The rest were dull.")


def test_a_proper_noun_counts_as_a_concrete_detail():
    assert 2 not in failed("It is generally like this in Basingstoke. Things stay dull.")


def test_a_sentence_initial_capital_is_not_mistaken_for_a_proper_noun():
    # "Things" only leads a sentence; there is no real specificity here.
    assert 2 in failed("It is generally dull. Things are basically the same.")


def test_hard_rule_failure_sinks_a_reply_that_passes_everything_else():
    reply = "I have no idea. Nobody tells me anything. It is probably raining!"
    score = rules.score_reply(reply)
    assert score.hard_failures == (4,)
    assert not score.passed


def test_a_reply_survives_a_single_soft_rule_failure():
    score = rules.score_reply("It is generally dull. Things are basically the same as before.")
    assert score.soft_auto_passes == 3
    assert score.passed


def test_human_scores_are_merged_into_the_verdict():
    reply = IN_CHARACTER[0]
    score = rules.score_reply(reply, human={1: True, 3: True, 6: None})
    assert score.human_applicable == 2
    assert score.human_passes == 2
    assert score.passed


def test_failing_the_human_rules_sinks_an_otherwise_clean_reply():
    score = rules.score_reply(IN_CHARACTER[0], human={1: False, 3: False, 6: True})
    assert score.human_passes == 1
    assert not score.passed


def test_rules_not_applicable_are_excluded_rather_than_counted_against():
    score = rules.score_reply(IN_CHARACTER[0], human={1: True, 3: None, 6: None})
    assert score.human_applicable == 1
    assert score.passed


def test_every_rule_id_has_a_description():
    covered = set(rules.HARD_RULES) | set(rules.SOFT_AUTO_RULES) | set(rules.HUMAN_RULES)
    assert covered == set(rules.RULE_NAMES)
