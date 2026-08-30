#!/usr/bin/env python3
"""The Phase 2 gate: 30 fixed prompts scored against the nine cadence rules.

Two modes.

  generate  Run the prompts through llama-server, score what comes back, and
            write a JSON run plus a markdown audition sheet.
  score     Re-score a saved run, optionally merging hand-scored results for
            the three rules a machine cannot judge. No model needed.

The automatic score is a screen, not the gate. MVP.md wants >= 24/30, and that
number only means something once rules 1, 3 and 6 have been scored by ear.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "pi"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "eval"))

import rules  # noqa: E402
from marvind import persona  # noqa: E402
from marvind.brain import BrainError, generate  # noqa: E402
from marvind.config import BrainConfig  # noqa: E402

PROMPTS_PATH = Path(__file__).with_name("prompts.json")
GATE_THRESHOLD = 24
PASS_MARK, FAIL_MARK = "pass", "FAIL"


@dataclass(frozen=True)
class PromptRun:
    """One prompt, its reply, and the timings that came with it."""

    prompt_id: int
    category: str
    prompt: str
    reply: str
    first_token_s: float
    total_s: float


def load_prompts(path: Path, limit: int | None) -> tuple[dict, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read prompt set at {path}: {error}")
    prompts = tuple(data.get("prompts", ()))
    if not prompts:
        raise SystemExit(f"prompt set at {path} is empty")
    return prompts[:limit] if limit else prompts


def run_prompts(config: BrainConfig, prompts: tuple[dict, ...]) -> tuple[PromptRun, ...]:
    """Ask each prompt in a fresh context. Cadence is per-reply, not cumulative."""
    system_prompt = persona.load_system_prompt(config.system_prompt_path)
    conversation = persona.Conversation(max_turns=config.max_turns)
    runs: list[PromptRun] = []

    for entry in prompts:
        messages = persona.build_messages(system_prompt, conversation, entry["text"])
        try:
            reply = generate(config, messages)
        except BrainError as error:
            raise SystemExit(f"prompt {entry['id']} failed: {error}")
        runs.append(
            PromptRun(
                prompt_id=entry["id"],
                category=entry.get("category", "uncategorised"),
                prompt=entry["text"],
                reply=reply.text,
                first_token_s=reply.first_token_s,
                total_s=reply.total_s,
            )
        )
        print(f"  {entry['id']:>2}/{len(prompts)}  {reply.total_s:5.1f}s  {entry['text']}", flush=True)
    return tuple(runs)


def load_human_scores(path: Path | None) -> dict[int, dict[int, bool | None]]:
    """Read hand-scored rules, keyed by prompt id then rule id."""
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read human scores at {path}: {error}")
    return {
        int(prompt_id): {int(rule_id): value for rule_id, value in scores.items()}
        for prompt_id, scores in raw.get("scores", {}).items()
    }


def report(
    runs: tuple[PromptRun, ...],
    human: dict[int, dict[int, bool | None]],
) -> tuple[int, list[dict]]:
    """Print the per-prompt and per-rule tables. Returns pass count and rows."""
    rows: list[dict] = []
    failures_by_rule: Counter[int] = Counter()
    passed_count = 0

    print(f"\n{'id':>3}  {'verdict':<7}  {'failed rules':<22}  prompt")
    print("-" * 78)
    for run in runs:
        score = rules.score_reply(run.reply, human.get(run.prompt_id))
        failed = score.failed_rules
        failures_by_rule.update(failed)
        passed_count += score.passed
        verdict = PASS_MARK if score.passed else FAIL_MARK
        failed_text = ", ".join(str(rule_id) for rule_id in failed) or "-"
        print(f"{run.prompt_id:>3}  {verdict:<7}  {failed_text:<22}  {run.prompt}")
        rows.append(
            {
                "id": run.prompt_id,
                "category": run.category,
                "prompt": run.prompt,
                "reply": run.reply,
                "passed": score.passed,
                "failed_rules": list(failed),
                "human_scored": score.human_applicable,
                "first_token_s": round(run.first_token_s, 3),
                "total_s": round(run.total_s, 3),
                "details": {
                    result.rule_id: {"passed": result.passed, "detail": result.detail}
                    for result in score.results
                },
            }
        )

    print(f"\n{'rule':>4}  {'fails':>5}  description")
    print("-" * 78)
    for rule_id in sorted(rules.RULE_NAMES):
        marker = " (by hand)" if rule_id in rules.HUMAN_RULES else ""
        print(f"{rule_id:>4}  {failures_by_rule.get(rule_id, 0):>5}  {rules.RULE_NAMES[rule_id]}{marker}")

    return passed_count, rows


def write_audition(path: Path, rows: list[dict]) -> None:
    """Write the sheet a human reads aloud, plus a score template to fill in."""
    lines = [
        "# Cadence audition sheet",
        "",
        "Read each reply aloud in Marvin's voice. Score the three rules a machine",
        "cannot: 1 (lead with the complaint), 3 (undercut the achievement),",
        "6 (own intelligence as chronic illness). Use `null` where a rule does not apply.",
        "",
    ]
    for row in rows:
        lines += [
            f"## {row['id']}. {row['prompt']}",
            "",
            f"> {row['reply']}",
            "",
            f"auto: {'pass' if row['passed'] else 'FAIL'}"
            f"  failed: {row['failed_rules'] or '-'}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")

    template = {"scores": {str(row["id"]): {"1": None, "3": None, "6": None} for row in rows}}
    template_path = path.with_suffix(".human.json")
    template_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    print(f"\naudition sheet : {path}\nscore template : {template_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=BrainConfig().base_url, help="llama-server base URL")
    parser.add_argument("--prompts", type=Path, default=PROMPTS_PATH)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N prompts")
    parser.add_argument("--temperature", type=float, default=BrainConfig().temperature)
    parser.add_argument("--seed", type=int, default=BrainConfig().seed, help="pin for reproducibility")
    parser.add_argument("--out", type=Path, default=None, help="write the run as JSON")
    parser.add_argument("--audition", type=Path, default=None, help="write a markdown sheet for hand scoring")
    parser.add_argument("--human", type=Path, default=None, help="merge hand scores from this JSON")
    parser.add_argument("--score", type=Path, default=None, help="re-score a saved run, no model needed")
    return parser


def runs_from_file(path: Path) -> tuple[PromptRun, ...]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read run at {path}: {error}")
    return tuple(
        PromptRun(
            prompt_id=row["id"],
            category=row.get("category", "uncategorised"),
            prompt=row["prompt"],
            reply=row["reply"],
            first_token_s=row.get("first_token_s", 0.0),
            total_s=row.get("total_s", 0.0),
        )
        for row in data["results"]
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    human = load_human_scores(args.human)

    if args.score:
        runs = runs_from_file(args.score)
    else:
        config = BrainConfig(base_url=args.url, temperature=args.temperature, seed=args.seed)
        prompts = load_prompts(args.prompts, args.limit)
        print(f"running {len(prompts)} prompts against {config.base_url}")
        runs = run_prompts(config, prompts)

    passed, rows = report(runs, human)
    total = len(rows)
    hand_scored = sum(1 for row in rows if row["human_scored"])

    print("-" * 78)
    print(f"score: {passed}/{total}   gate: >= {GATE_THRESHOLD}/30")
    if hand_scored < total:
        print(
            f"note : {total - hand_scored} of {total} replies are auto-only. "
            "Rules 1, 3 and 6 are unscored, so this is a screen, not the gate."
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"passed": passed, "total": total, "results": rows}, indent=2),
            encoding="utf-8",
        )
        print(f"run written    : {args.out}")
    if args.audition:
        args.audition.parent.mkdir(parents=True, exist_ok=True)
        write_audition(args.audition, rows)

    return 0 if passed >= GATE_THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(main())
