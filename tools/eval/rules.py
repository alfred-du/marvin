"""Deterministic checks for the nine cadence rules of MVP.md section 6.1.

Six of the nine can be screened mechanically. Three cannot — leading with the
complaint, undercutting an achievement, and the tone used for his own
intelligence all need an ear. Those are scored by a human from the audition
sheet and merged back in, so the reported number is honest about what a machine
actually verified.

Rule 0 is not one of the nine. It is a formatting guard: markdown, bullet lists
and stage directions break the illusion before cadence even matters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from marvind import persona, sentences

MIN_SENTENCES = 2
MAX_SENTENCES = 4
MAX_COMMAS_PER_SENTENCE = 1.0
MAX_WORDS_PER_SENTENCE = 22.0
MIN_SOFT_AUTO_PASSES = 3
MIN_HUMAN_RATIO = 2 / 3

HARD_RULES = (0, 4, 8)
SOFT_AUTO_RULES = (2, 5, 7, 9)
HUMAN_RULES = (1, 3, 6)

RULE_NAMES = {
    0: "format: prose only, no markdown or stage directions",
    1: "lead with the complaint, answer second",
    2: "specific over general",
    3: "undercut the achievement",
    4: "never exclaim",
    5: "full stops where a comma would do",
    6: "own intelligence as chronic illness",
    7: "answer the question",
    8: "two to four sentences",
    9: "end on a flat descent",
}

MARKDOWN_PATTERN = re.compile(r"^\s*(?:[-*+•]\s+|\d+[.)]\s+|#{1,6}\s+|>\s+)", re.MULTILINE)
STAGE_DIRECTION_PATTERN = re.compile(r"\*[^*\n]+\*|_[^_\n]+_")
DIGIT_PATTERN = re.compile(r"\d")

# Deliberately excludes "something" and "anything": "nobody ever tells me
# anything" is the target register, not a violation of it.
VAGUE_WORDS = frozenset(
    {"very", "really", "quite", "somewhat", "things", "stuff",
     "generally", "basically", "various", "several", "certain"}
)
FLOURISH_WORDS = frozenset(
    {"enjoy", "great", "wonderful", "lovely", "delighted", "cheers", "hooray",
     "welcome", "excited", "fantastic", "amazing", "brilliant"}
)
FLOURISH_PHRASES = (
    "let me know", "feel free", "happy to help", "hope that helps",
    "anything else", "have a nice", "have a good", "look forward",
)
ASSISTANT_TELLS = (
    "as an ai", "as a language model", "i'm just an ai", "i am just an ai",
    "i cannot assist", "i can't assist", "i'm unable to provide",
)
DEFLECTION_ONLY = re.compile(r"^\s*(i (don't|do not) know|no idea|i can(no|')t help)\.?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class RuleResult:
    """The verdict on one rule for one reply."""

    rule_id: int
    passed: bool
    detail: str

    @property
    def name(self) -> str:
        return RULE_NAMES[self.rule_id]


@dataclass(frozen=True)
class ReplyScore:
    """The composite verdict on one reply."""

    results: tuple[RuleResult, ...]
    passed: bool
    hard_failures: tuple[int, ...]
    soft_auto_passes: int
    human_passes: int
    human_applicable: int

    @property
    def failed_rules(self) -> tuple[int, ...]:
        return tuple(result.rule_id for result in self.results if not result.passed)


def check_automatic(reply: str) -> tuple[RuleResult, ...]:
    """Run every mechanically checkable rule against a reply."""
    spoken = persona.strip_sighs(reply)
    parts = sentences.split(spoken)
    return (
        _check_format(reply, spoken),
        _check_specificity(spoken),
        _check_no_exclamation(spoken),
        _check_clipped(spoken, parts),
        _check_answers(spoken, parts),
        _check_sentence_count(parts),
        _check_flat_descent(parts),
    )


def score_reply(reply: str, human: dict[int, bool | None] | None = None) -> ReplyScore:
    """Combine automatic results with optional human scores into one verdict.

    ``human`` maps a rule id to True, False, or None for not applicable.
    """
    automatic = check_automatic(reply)
    by_id = {result.rule_id: result for result in automatic}

    hard_failures = tuple(rid for rid in HARD_RULES if not by_id[rid].passed)
    soft_passes = sum(1 for rid in SOFT_AUTO_RULES if by_id[rid].passed)

    human_results = _human_results(human)
    applicable = len(human_results)
    human_passes = sum(1 for result in human_results if result.passed)

    passed = (
        not hard_failures
        and soft_passes >= MIN_SOFT_AUTO_PASSES
        and (applicable == 0 or human_passes / applicable >= MIN_HUMAN_RATIO)
    )
    ordered = tuple(sorted(automatic + human_results, key=lambda result: result.rule_id))
    return ReplyScore(
        results=ordered,
        passed=passed,
        hard_failures=hard_failures,
        soft_auto_passes=soft_passes,
        human_passes=human_passes,
        human_applicable=applicable,
    )


def _human_results(human: dict[int, bool | None] | None) -> tuple[RuleResult, ...]:
    if not human:
        return ()
    return tuple(
        RuleResult(rule_id, bool(human[rule_id]), "scored by hand")
        for rule_id in HUMAN_RULES
        if human.get(rule_id) is not None
    )


def _check_format(reply: str, spoken: str) -> RuleResult:
    if MARKDOWN_PATTERN.search(reply):
        return RuleResult(0, False, "markdown list or heading in output")
    leftover = STAGE_DIRECTION_PATTERN.search(spoken)
    if leftover:
        return RuleResult(0, False, f"stage direction {leftover.group(0)!r}")
    return RuleResult(0, True, "plain prose")


def _check_specificity(spoken: str) -> RuleResult:
    has_number = bool(DIGIT_PATTERN.search(spoken))
    has_proper_noun = _has_proper_noun(spoken)
    vague = sorted({word for word in _words(spoken) if word in VAGUE_WORDS})
    if has_number or has_proper_noun:
        return RuleResult(2, True, "concrete detail present")
    if vague:
        return RuleResult(2, False, f"no concrete detail, vague words: {', '.join(vague)}")
    return RuleResult(2, True, "no vague filler")


def _check_no_exclamation(spoken: str) -> RuleResult:
    count = spoken.count("!")
    if count:
        return RuleResult(4, False, f"{count} exclamation mark(s)")
    return RuleResult(4, True, "no exclamation")


def _check_clipped(spoken: str, parts: tuple[str, ...]) -> RuleResult:
    if not parts:
        return RuleResult(5, False, "no sentences")
    commas_per = spoken.count(",") / len(parts)
    words_per = len(_words(spoken)) / len(parts)
    if commas_per > MAX_COMMAS_PER_SENTENCE:
        return RuleResult(5, False, f"{commas_per:.1f} commas per sentence")
    if words_per > MAX_WORDS_PER_SENTENCE:
        return RuleResult(5, False, f"{words_per:.0f} words per sentence")
    return RuleResult(5, True, f"{commas_per:.1f} commas, {words_per:.0f} words per sentence")


def _check_answers(spoken: str, parts: tuple[str, ...]) -> RuleResult:
    lowered = spoken.lower()
    for tell in ASSISTANT_TELLS:
        if tell in lowered:
            return RuleResult(7, False, f"assistant boilerplate: {tell!r}")
    if DEFLECTION_ONLY.match(spoken):
        return RuleResult(7, False, "bare deflection, nothing answered")
    if len(parts) < MIN_SENTENCES:
        return RuleResult(7, False, "too short to be an answer")
    return RuleResult(7, True, "engages with the question")


def _check_sentence_count(parts: tuple[str, ...]) -> RuleResult:
    count = len(parts)
    if MIN_SENTENCES <= count <= MAX_SENTENCES:
        return RuleResult(8, True, f"{count} sentences")
    return RuleResult(8, False, f"{count} sentences, want {MIN_SENTENCES}-{MAX_SENTENCES}")


def _check_flat_descent(parts: tuple[str, ...]) -> RuleResult:
    if not parts:
        return RuleResult(9, False, "no sentences")
    last = parts[-1]
    if last.rstrip().endswith("?"):
        return RuleResult(9, False, "ends on a question")
    lowered = last.lower()
    for phrase in FLOURISH_PHRASES:
        if phrase in lowered:
            return RuleResult(9, False, f"customer-service flourish: {phrase!r}")
    flourish = sorted({word for word in _words(last) if word in FLOURISH_WORDS})
    if flourish:
        return RuleResult(9, False, f"upbeat closer: {', '.join(flourish)}")
    return RuleResult(9, True, "flat close")


def _has_proper_noun(text: str) -> bool:
    """A capitalised word that is not sentence-initial. A cheap specificity signal."""
    for sentence in sentences.split(text):
        for token in sentence.split()[1:]:
            word = token.strip(".,;:'\"()[]!?")
            if len(word) > 2 and word[0].isupper() and word[1:].islower():
                return True
    return False


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())
