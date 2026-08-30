# Marvin

An offline, always-on Marvin (the Paranoid Android). See [MVP.md](MVP.md) for
the full specification.

## Current state

The **LLM path only**: system prompt, rolling context window, `<sigh>`
interception, sentence streaming, and the Phase 2 cadence eval. STT (whisper),
TTS (Piper), the SoX voice chain and the V821 front-end are not built yet.

```
pi/marvind/
  config.py      immutable, validated settings; MARVIN_* env overrides
  persona.py     Persona (prompt + few-shots), rolling window, <sigh> interception
  sentences.py   streaming sentence splitter (pure, no I/O)
  brain.py       llama-server client over stdlib HTTP + SSE
pi/prompts/
  marvin.system.md      the nine cadence rules and formatting constraints
  marvin.examples.json  few-shot turns, replayed as real user/assistant messages
tools/
  chat.py            terminal REPL, streams sentence by sentence
  eval/rules.py      deterministic checks for 6 of the 9 rules
  eval/prompts.json  the 30 fixed prompts
  eval/cadence_eval.py
```

Runtime dependencies: **none**. Standard library only, so the Pi image stays
small and the daemon has nothing to page in. `requirements-dev.txt` covers the
test rig and the Colab model fetch.

## Test it on Colab

Open `notebooks/marvin_llm_colab.ipynb`. It builds llama.cpp (CPU-only, on
purpose), fetches Qwen2.5-1.5B-Instruct Q4_K_M, runs the suite, and drives the
cadence eval.

Colab is a Phase 1/2 rig. **It cannot measure latency** — different silicon, so
the timings printed are instrumentation, not results. Section 1's targets are
only meaningful on the Pi 5.

## Locally

```sh
python -m pytest tests/                    # no model server needed
bash scripts/colab_setup.sh                # build llama-server, fetch the model
bash scripts/run_server.sh                 # start it, wait for /health
python tools/chat.py                       # talk to him
python tools/eval/cadence_eval.py --seed 42 --out runs/latest.json --audition runs/latest.md
python tools/eval/cadence_eval.py --score runs/latest.json --human runs/latest.human.json
```

## The cadence eval

MVP.md's Phase 2 gate is >= 24/30. Six of the nine rules are checked
mechanically. Rules 1 (lead with the complaint), 3 (undercut the achievement)
and 6 (own intelligence as chronic illness) need an ear, so `--audition` writes
a sheet to read aloud plus a JSON template. Until that is filled in and passed
back with `--human`, the printed score is a **screen, not the gate**, and the
harness says so.

Failures are reported per rule, not as a single number, so a regression is
attributable to the rule that caused it.

Pin `--seed` whenever two runs are meant to be comparable.
