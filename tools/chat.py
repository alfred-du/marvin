#!/usr/bin/env python3
"""Talk to Marvin from the terminal, one sentence at a time as he produces them.

The rolling context window is live here, unlike the cadence eval, so this is
where you find out whether he stays in character across a conversation.

The timings printed are the real stage boundaries, but on anything other than a
Pi 5 they are meaningless as targets. They exist so the instrumentation seam is
built before Phase 3 needs it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pi"))

from marvind import persona  # noqa: E402
from marvind.brain import BrainError, stream_sentences, wait_for_server  # noqa: E402
from marvind.config import BrainConfig  # noqa: E402

EXIT_WORDS = frozenset({"quit", "exit", ":q"})
RESET_WORDS = frozenset({"reset", ":r"})


def say(config: BrainConfig, marvin: persona.Persona, conversation: persona.Conversation, text: str) -> str:
    """Stream one reply, printing each sentence the moment it completes."""
    messages = persona.build_messages(marvin, conversation, text)
    started = time.perf_counter()
    first_sentence_s = 0.0
    spoken: list[str] = []

    print("marvin> ", end="", flush=True)
    for sentence in stream_sentences(config, messages):
        if not first_sentence_s:
            first_sentence_s = time.perf_counter() - started
        rendered = persona.render_segments(persona.intercept_sighs(sentence))
        print(rendered, end=" ", flush=True)
        spoken.append(sentence)

    total = time.perf_counter() - started
    print(f"\n        [first sentence {first_sentence_s:.2f}s, total {total:.2f}s]\n")
    return " ".join(spoken)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=BrainConfig().base_url)
    parser.add_argument("--temperature", type=float, default=BrainConfig().temperature)
    parser.add_argument("--once", default=None, help="say one thing, print the reply, exit")
    args = parser.parse_args(argv)

    config = BrainConfig(base_url=args.url, temperature=args.temperature)
    try:
        wait_for_server(config, timeout_s=60.0)
        marvin = persona.load_persona(config.system_prompt_path, config.examples_path)
    except (BrainError, persona.PersonaError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    conversation = persona.Conversation(max_turns=config.max_turns)

    if args.once:
        reply = say(config, marvin, conversation, args.once)
        return 0 if reply else 1

    print("Marvin is listening. 'reset' clears the window, 'quit' leaves.\n")
    while True:
        try:
            text = input("you   > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            return 0
        if text.lower() in RESET_WORDS:
            conversation = conversation.cleared()
            print("        [context cleared]\n")
            continue
        try:
            reply = say(config, marvin, conversation, text)
        except BrainError as error:
            print(f"\nerror: {error}", file=sys.stderr)
            continue
        conversation = conversation.with_exchange(text, reply)


if __name__ == "__main__":
    raise SystemExit(main())
