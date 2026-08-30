# Marvin — MVP Specification

An offline, always-on Marvin (the Paranoid Android) built from an Allwinner V821
audio front-end and a Raspberry Pi 5 inference brain. No cloud. No motion.
Mains powered.

Status: pre-build. Hardware confirmed, no code written yet.

---

## 1. What "done" looks like

The MVP is finished when this exact scenario works, unattended, from cold boot,
with the network disabled:

> You walk into the room. Nothing happens — no chime, no light show. You say
> **"Marvin."** Within a fraction of a second, in a flat, exhausted voice, he
> says *"...Oh. It's you."* You ask him what the weather is like. He tells you,
> at length, that he has no idea, that nobody ever tells him anything, and that
> he has a terrible pain in all the diodes down his left side. The whole reply
> is spoken in one continuous voice — you cannot hear the seam between the part
> he said immediately and the part he actually thought about.

Five properties that scenario is testing:

| # | Property | Measurable target |
|---|----------|-------------------|
| 1 | He answers *fast* | First audio out of the speaker <= **150 ms** after the wake word ends |
| 2 | He answers *himself* | Real reply begins <= **4.0 s** after end of your utterance, with no silence gap |
| 3 | He sounds *right* | >= 24/30 on the cadence eval set (see 6.4 / 9) |
| 4 | He is *offline* | Passes with WiFi disabled and no route to the internet |
| 5 | He *stays up* | 72 h soak, >= 200 interactions, zero manual restarts |

**Explicit non-goals for MVP.** No servos or motion. No battery. No display
beyond the two eye LEDs. No multi-turn memory beyond a rolling window. No
speaker identification. No wake-free conversation mode. No OTA updates. No STT
or TTS on the V821 — investigated and ruled out on memory grounds (see 3.3).

---

## 2. Hardware flow

### 2.1 Signal chain

```
                        +-----------------------------------------+
   sound --> MIC --I2S-->|  ALLWINNER V821  (64 MB, rv32, no NPU)  |
                        |                                         |
                        |  capture -> RNNoise -> AEC -> VAD       |
                        |                 |         ^             |
                        |                 v         | reference   |
                        |            wake word      |             |
                        |            cmd spotter    |             |
                        |                 |         |             |
                        |            mixer/ducker --+             |
                        |              ^        ^                 |
                        |    filler WAVs        | TTS PCM         |
                        |    (from TF)          |                 |
   camera --MIPI CSI--->|  presence detect      |                 |
                        |  eye LEDs (SPI)       |                 |
                        +--------+--------------+-----------------+
                                 |              |
                          I2S out|              |  USB 2.0 gadget
                                 v              |  (one cable:
                            DAC + AMP           |   power + data)
                                 |              |
                              SPEAKER           |
                                                |
                        +-----------------------v-----------------+
                        |  RASPBERRY PI 5 / 4 GB                  |
                        |                                         |
                        |  16 kHz PCM in --> whisper.cpp          |
                        |                       |                 |
                        |                       v                 |
                        |                  llama-server           |
                        |                  (Qwen2.5-1.5B Q4_K_M)  |
                        |                       | tokens          |
                        |                       v                 |
                        |                  sentence splitter      |
                        |                       |                 |
                        |                       v                 |
                        |                  Piper --> SoX chain    |
                        |                       |                 |
                        |                  22 kHz PCM out --------+--> back to V821
                        +-----------------------------------------+
```

**The one thing to notice:** audio never leaves the V821 in analogue form, and
the Pi never produces analogue audio. All playback — fillers and real speech
alike — exits through the V821's I2S DAC. The Pi 5's missing 3.5 mm jack is
therefore irrelevant, and the AEC reference signal lives on the same chip as the
capture path, which is exactly where you want it.

### 2.2 Power and cabling

One 27 W official USB-C PSU into the Pi. A single USB-A -> USB-C cable from the
Pi to the V821 carries both bus power and data. The V821 board draws well under
the port budget, and the official PSU lifts the peripheral current cap to 1.6 A.

Net result: **one wall plug, one internal cable.**

### 2.3 Bill of materials

| Part | Role | Notes | Approx. |
|------|------|-------|---------|
| Raspberry Pi 5 / 4 GB | Inference | *have* | — |
| V821 carrier board | Audio front-end | *have*, external I2S confirmed | — |
| I2S mic | Capture | *have*, wired | — |
| Speaker + I2S amp | Playback | *have*, wired | — |
| microSD (TF) for V821 | Rootfs + filler bank | 16 GB class 10 is plenty | ~$6 |
| NVMe SSD + underslung HAT | Pi storage, via PCIe FPC | Keeps 40-pin header free | ~$35 |
| Official Active Cooler | Pi thermals | ~10 mm tall | ~$5 |
| Official 27 W USB-C PSU | Power | Needed for the USB current budget | ~$12 |
| 2x APA102/SK9822 | Eyes | SPI, driven by V821 | ~$3 |
| USB-A -> USB-C cable, short | Interconnect | Power + data | ~$4 |
| PLA/PETG filament | Shell | *have* printer | ~$5 |

**Total new spend: ~$70.** The ReSpeaker HAT from the earlier revision is gone —
the V821 does its job better and frees the Pi's 40-pin header entirely.

**Out:** the Arduino UNO Q. The V821's MIPI CSI handles presence natively, which
was the UNO Q's last defensible role.

---

## 3. Division of labour

### 3.1 V821 — the fast path (always on)

Runs continuously at low power. Never sleeps.

- I2S capture at 16 kHz
- RNNoise denoise
- Acoustic echo cancellation, referenced against its own playback
- Voice activity detection, with barge-in (user speaks -> duck/stop playback)
- Wake word spotting
- Fixed-grammar command spotter, 20–50 phrases, resolved locally without ever
  waking the Pi ("be quiet", "go to sleep", "louder", "say that again")
- Filler-line playback from the TF card
- TTS PCM playback from the Pi, with a ~200 ms jitter buffer
- Camera presence detection
- Eye LED animation

### 3.2 Pi 5 — the slow path (idle until woken)

Three resident daemons, started at boot with weights `--mlock`ed so no model
ever pages in from disk on the critical path.

| Daemon | Model | RAM | Latency on Pi 5 |
|--------|-------|-----|-----------------|
| `whisper.cpp` server | `base.en` q5 | ~250 MB | ~0.6–0.9 s per 3 s utterance |
| `llama-server` | Qwen2.5-1.5B-Instruct Q4_K_M | ~1.3 GB | ~10–16 tok/s |
| `piper` | `en_GB-alan-medium` | ~80 MB | ~0.3x realtime |

Runs **Pi OS Lite**, not Desktop. Budget with headroom on 4 GB:

```
OS + services      ~400 MB
whisper.cpp        ~250 MB
llama (1.5B Q4)   ~1300 MB
piper + sox        ~120 MB
marvind            ~ 80 MB
                  ---------
                  ~2150 MB   ->  ~1.8 GB free
```

Llama-3.2-3B Q4_K_M (~2.1 GB, 4–9 tok/s) is a **post-MVP experiment**, not the
MVP target. It fits, but it eats the headroom and roughly halves token rate.

### 3.3 What the V821 deliberately does *not* do

STT and TTS were evaluated for the V821 and ruled out. The reason is structural,
not a matter of tuning:

- 64 MB of on-chip DDR2, not expandable
- After Tina Linux (~22 MB), WiFi stack (~6 MB), ISP buffers (~10 MB), audio DSP
  (~4 MB) and the wake-word runtime (~2 MB), roughly **20 MB is free**
- whisper-tiny int8 is ~40 MB of weights *before* activations — 2x over
- Piper's smallest voice is marginal on memory and hopeless on compute: no NPU
  is advertised on the V821 (unlike the V851s/V853 siblings), so it would be
  float matmul on a 1.2 GHz in-order rv32 core

The substitute is the filler bank plus the local command spotter, which covers
the latency problem on-board TTS was meant to solve — and covers it better,
because pre-rendered audio has *zero* synthesis latency.

---

## 4. The link between the boards

USB gadget mode over the single interconnect cable. Two logical planes.

### 4.1 Control plane — `g_serial`, CDC-ACM, newline-delimited ASCII

```
# V821 -> Pi
PRESENCE conf=0.82
WAKE conf=0.94 ts=1712...
AUDIO_BEGIN rate=16000 fmt=s16le
VAD_END dur_ms=3400
CMD phrase=be_quiet            # resolved locally, Pi never wakes
BARGE_IN                       # user started talking over playback

# Pi -> V821
PLAY filler=random len=short|long
SPEAK_BEGIN rate=22050 fmt=s16le
SPEAK_END
EYES state=idle|listening|thinking|speaking
SLEEP
ERROR code=... msg=...
```

Every line is one event, <= 120 bytes, ASCII, `\n` terminated. Unknown verbs are
logged and ignored — forward compatible in both directions.

### 4.2 Audio plane — `g_ether`, CDC-ECM/RNDIS, raw PCM over UDP

- **Uplink** (capture): 16 kHz mono s16le = 32 KB/s
- **Downlink** (speech): 22.05 kHz mono s16le = 44 KB/s

Both trivial for USB 2.0. UDP with a sequence number; a dropped packet becomes a
20 ms zero-fill rather than a stall. `g_audio` (UAC) is *not* used — it adds a
class-driver dependency for no benefit at these rates.

**This protocol is the project's most important seam.** Because it is narrow and
text-based, the entire Pi side can be developed and tested against
`tools/stub_frontend.py` — a script that fakes a V821 over a PTY, feeding WAV
files in and dumping PCM out. The Pi side never blocks on V821 bring-up.

---

## 5. Interaction timeline

The design premise: **perceived latency and actual latency are different
numbers, and only the first one matters.**

```
t=0ms      wake word ends
t+30ms     V821 wake detector fires
t+50ms     filler WAV starts playing from TF          <-- user hears Marvin here
t+55ms     WAKE crosses USB; Pi begins pre-fill
t+50..3400 user speaks; V821 denoises, streams PCM to Pi
t+3400     VAD_END
t+4200     whisper returns transcript
t+4500     llama first token
t+5400     first complete sentence emitted
t+5800     piper + sox render sentence 1
t+5850     PCM crosses USB; V821 crossfades filler -> speech
           ...remaining sentences stream continuously behind it
```

Actual think-time is ~2.5 s after you stop talking. Perceived latency is **50
ms**, because he started talking at t+50 and never stopped.

Three mechanisms make this work:

1. **Filler bank.** ~40 pre-rendered WAVs of Marvin stalling. Two length buckets
   — short (~2 s) and long (~5–6 s). If no `SPEAK_BEGIN` has arrived when a
   filler ends, the V821 chains a second one rather than falling silent.
2. **Sentence streaming.** The Pi pipes llama tokens into Piper at every
   sentence terminator instead of waiting for the full completion.
3. **Presence pre-warm.** The camera sees you arrive ~2 s before you speak.
   `PRESENCE` pre-fills the Pi's KV cache with the system prompt, removing
   prefill from the critical path entirely.

---

## 6. Personality

Personality fidelity is a first-class requirement, not decoration. It has three
independent implementations that must agree.

### 6.1 The nine cadence rules (system prompt)

1. Lead with the complaint, not the answer. The answer arrives second, and
   reluctantly.
2. Deploy the specific over the general — "the first ten million years were the
   worst", never "it was bad".
3. Undercut every achievement immediately after stating it.
4. Never exclaim. No exclamation marks, ever.
5. Use full stops where a comma would do. The pauses are the performance.
6. Refer to your own vast intelligence in the same tone you would use for a
   chronic illness.
7. Answer the question. He is depressed, not unhelpful. Withholding is out of
   character.
8. Two to four sentences, typically. Length is a resource; long is a choice.
9. End on a flat descent, not a flourish.

### 6.2 Punctuation as a prosody API

The system prompt instructs full stops for pauses and ellipses for trailing off,
and Piper honours both. `<sigh>` is emitted as a literal token, intercepted
before synthesis, and replaced with a real recorded sigh spliced into the PCM.

### 6.3 Voice chain

| Piper flag | Value | Effect |
|-----------|-------|--------|
| voice | `en_GB-alan-medium` | Base timbre |
| `--length_scale` | `1.20`–`1.35` | Slower delivery |
| `--noise_scale` | `0.45`–`0.55` | Flatter prosody |
| `--noise_w` | `0.6` | Less phoneme variation |
| `--sentence_silence` | `0.7`–`0.9` | Long inter-sentence pauses |

Post-chain:

```sh
sox in.wav out.wav \
  pitch -180 \
  tempo -s 0.94 \
  equalizer 300 1.2q +3 \
  equalizer 3400 2.0q -4 \
  lowpass 7000 \
  reverb 18 50 45 100 12 -2 \
  gain -n -2
```

The filler bank is rendered through the identical chain so the crossfade is
inaudible. This is a hard requirement, not a nicety — a timbre mismatch at the
seam destroys the whole illusion.

### 6.4 Eyes

Two APA102/SK9822 on SPI, driven by the V821. SPI is chosen over WS2812
deliberately: the Pi 5's RP1 southbridge breaks `rpi_ws281x`, and SPI has no
bit-timing requirements on either board.

| `EYES` state | Behaviour |
|--------------|-----------|
| `idle` | Very slow dim pulse, ~0.2 Hz |
| `listening` | Steady, slightly brighter |
| `thinking` | Slow irregular flicker |
| `speaking` | Low-amplitude modulation tracking the output envelope |

---

## 7. Repository layout

```
marvin/
├── MVP.md
├── README.md
├── pi/
│   ├── marvind/                 # orchestrator daemon (Python)
│   │   ├── main.py              # event loop, state machine
│   │   ├── link.py              # CDC-ACM protocol codec
│   │   ├── audio_io.py          # PCM ingest/egress over CDC-ECM
│   │   ├── stt.py               # whisper.cpp client
│   │   ├── brain.py             # llama-server client, context window
│   │   ├── voice.py             # sentence split -> piper -> sox
│   │   └── persona.py           # prompt assembly, <sigh> interception
│   ├── prompts/marvin.system.md
│   ├── models/                  # gguf / bin / onnx — gitignored
│   └── systemd/                 # marvind, llama, whisper, piper units
├── v821/
│   ├── marvin-fe/               # C daemon: capture, wake, VAD, mixer
│   ├── fillers/                 # 40 rendered WAVs + manifest.json
│   └── tina/                    # defconfig, dts overlay, build notes
├── tools/
│   ├── stub_frontend.py         # fakes the V821 over a PTY
│   ├── render_fillers.py        # regenerates the bank through the SoX chain
│   └── eval/cadence_eval.py     # 30-prompt scorer
└── enclosure/                   # OpenSCAD sources + exported STLs
```

Modules target 200–400 lines, 800 max. `marvind` is split by responsibility
rather than by type, so `link.py` and `audio_io.py` are the only files that know
the V821 exists.

---

## 8. Build order

Each phase has an **exit gate** — a demonstrable result. Do not start the next
phase until the gate passes.

### Phase 0 — Toolchain spike (timeboxed, runs in parallel)

Cross-compile a trivial C binary for the V821, get it onto the board, run it,
read its stdout over serial. Nothing else.

> **Gate:** hello-world runs on the V821 and you can see the output.
>
> **Timebox: two weekends.** If it fails, fall back to an $8 USB sound card on
> the Pi and the single-board architecture. This phase blocks nothing — phases
> 1–3 proceed regardless.

### Phase 1 — Pi brain against the stub

Build `tools/stub_frontend.py` first, then the whole Pi pipeline against it. No
V821 involvement whatsoever.

> **Gate:** feed a WAV in, get Marvin-voiced WAV out, end to end, offline.

### Phase 2 — Persona tuning

Write the system prompt, build the 30-prompt eval set, iterate the nine rules
and the SoX chain until the score clears threshold. Render the filler bank.

> **Gate:** >= 24/30 on the cadence eval; 40 fillers rendered and auditioned.

### Phase 3 — Latency

Sentence streaming, `--mlock`, resident daemons, KV pre-fill.

> **Gate:** <= 4.0 s from end-of-utterance to first real audio, measured, in the
> stub harness.

### Phase 4 — V821 front-end

Capture, RNNoise, AEC, VAD, wake word, filler playback, command spotter.
Requires Phase 0 to have passed.

> **Gate:** say the wake word, hear a filler in under 150 ms. Standalone — the
> Pi is not connected.

### Phase 5 — Integration

USB gadget up, replace the stub with the real board, tune the jitter buffer,
implement the crossfade and barge-in.

> **Gate:** the section 1 scenario, live.

### Phase 6 — Enclosure and soak

Print the shell, mount everything, 72 h soak test.

> **Gate:** 200+ interactions, zero manual restarts.

### Phase 7 — Post-MVP (not in scope)

Llama-3.2-3B evaluation. Speaker ID. Longer memory. Wake-free mode.

---

## 9. Testing

The stub front-end is what makes this testable without hardware in the loop.

| Layer | Approach |
|-------|----------|
| Unit | `link.py` protocol codec, sentence splitter, `<sigh>` interception, persona assembly. Pure functions, no I/O. |
| Integration | Full `marvind` against `stub_frontend.py` with recorded WAV fixtures. Asserts on transcript, reply shape, and output PCM duration. |
| Latency | Harness that timestamps each stage boundary and fails the build if p95 exceeds the section 1 targets. |
| Persona | `cadence_eval.py` — 30 fixed prompts, each scored against the nine rules, reported per-rule so regressions are attributable. |
| Soak | 72 h, scripted random interactions, monitoring RSS and restart count. |

Coverage target 80% on `pi/marvind/`. The V821 C daemon is tested by fixture
WAVs fed through the DSP chain offline, with the wake detector's false-accept
and false-reject rates measured over a recorded corpus.

---

## 10. Risk register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Tina Linux 5.0 / rv32 toolchain is a dead end | **High** | Phase 0 is timeboxed and parallel; the protocol seam means the Pi side never blocks; fallback is a USB sound card |
| Wake-word runtime will not fit or port to rv32 | Medium | Evaluate microWakeWord / openWakeWord-tiny early in Phase 0; fallback is running the detector on the Pi and using the V821 purely as an audio pipe |
| AEC insufficient — he hears himself | Medium | Reference signal is on-chip, which is the strong case; physical mic/speaker separation in the enclosure; barge-in threshold tuning |
| 1.5B model is too dim to be funny | Medium | Persona quality is prompt-dominated, not parameter-dominated; the Phase 2 gate catches it before hardware; 3B is the escape hatch |
| Filler/speech timbre mismatch at the crossfade | Medium | Render both through one identical SoX chain from one script; assert it in Phase 2 |
| Pi 5 thermal throttling under sustained inference | Low | Active Cooler; inference is bursty, not sustained |
| 4 GB is tight | Low | Budget in 3.2 leaves ~1.8 GB free; Pi OS Lite, not Desktop |

---

## 11. Open items

- [ ] Confirm the exact V821 carrier board model and pull its schematic
- [ ] Confirm I2S pin mapping, and whether mic and speaker share a bus or use
      separate ports — this decides whether capture-during-playback is truly
      full duplex, which AEC and barge-in both depend on
- [ ] Confirm the codec's sample-rate options — if 22.05 kHz playback is
      unavailable, resample to 16 or 48 kHz on the Pi before transmit
- [ ] Confirm the TF card is bootable on this carrier, or whether it is NOR-only
- [ ] Pick the wake word. "Marvin" is short and plosive-light, which is a
      slightly harder detection target than a two-syllable alternative
