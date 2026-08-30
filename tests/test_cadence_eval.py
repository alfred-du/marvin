"""The eval harness end to end, in score mode, with no model server."""

from __future__ import annotations

import json

import pytest

import cadence_eval


def write_run(path, rows):
    path.write_text(json.dumps({"passed": 0, "total": len(rows), "results": rows}), encoding="utf-8")


IN_CHARACTER = (
    "I have no idea. Nobody ever tells me anything, and the window is on the "
    "other side of the room. It is probably raining. It usually is."
)


def test_score_mode_reads_a_saved_run_and_reports_a_pass(tmp_path, capsys):
    # Arrange
    run = tmp_path / "run.json"
    write_run(run, [{"id": 1, "prompt": "What's the weather like?", "reply": IN_CHARACTER}])

    # Act
    exit_code = cadence_eval.main(["--score", str(run)])

    # Assert: one prompt cannot clear a gate of 24, but it must score as a pass.
    output = capsys.readouterr().out
    assert "score: 1/1" in output
    assert exit_code == 1


def test_score_mode_flags_that_the_run_is_auto_only(tmp_path, capsys):
    run = tmp_path / "run.json"
    write_run(run, [{"id": 1, "prompt": "hello", "reply": IN_CHARACTER}])
    cadence_eval.main(["--score", str(run)])
    assert "screen, not the gate" in capsys.readouterr().out


def test_human_scores_are_merged_in_score_mode(tmp_path, capsys):
    run = tmp_path / "run.json"
    write_run(run, [{"id": 1, "prompt": "hello", "reply": IN_CHARACTER}])
    human = tmp_path / "human.json"
    human.write_text(json.dumps({"scores": {"1": {"1": False, "3": False, "6": None}}}))

    cadence_eval.main(["--score", str(run), "--human", str(human)])

    output = capsys.readouterr().out
    assert "score: 0/1" in output
    assert "screen, not the gate" not in output


def test_audition_writes_a_sheet_and_a_score_template(tmp_path):
    run = tmp_path / "run.json"
    write_run(run, [{"id": 1, "prompt": "What's the weather like?", "reply": IN_CHARACTER}])
    sheet = tmp_path / "sheets" / "audition.md"

    cadence_eval.main(["--score", str(run), "--audition", str(sheet)])

    assert "What's the weather like?" in sheet.read_text()
    template = json.loads(sheet.with_suffix(".human.json").read_text())
    assert template["scores"]["1"] == {"1": None, "3": None, "6": None}


def test_out_writes_the_scored_run_as_json(tmp_path):
    run = tmp_path / "run.json"
    write_run(run, [{"id": 1, "prompt": "hello", "reply": IN_CHARACTER}])
    out = tmp_path / "out" / "scored.json"

    cadence_eval.main(["--score", str(run), "--out", str(out)])

    written = json.loads(out.read_text())
    assert written["results"][0]["passed"] is True
    assert 8 in {int(k) for k in written["results"][0]["details"]}


def test_the_shipped_prompt_set_has_thirty_uniquely_numbered_prompts():
    prompts = cadence_eval.load_prompts(cadence_eval.PROMPTS_PATH, None)
    assert len(prompts) == 30
    assert len({entry["id"] for entry in prompts}) == 30


def test_limit_truncates_the_prompt_set():
    assert len(cadence_eval.load_prompts(cadence_eval.PROMPTS_PATH, 5)) == 5


def test_a_missing_prompt_set_fails_loudly(tmp_path):
    with pytest.raises(SystemExit):
        cadence_eval.load_prompts(tmp_path / "absent.json", None)
