# voice-en: the English narrator (Kokoro "af_heart")

A small local speech server for the English Shorts. It runs **Kokoro**, an 82-million-parameter text-to-speech model, with the
voice **af_heart** (US female), and speaks the same way VoiceStudio and the German server do (`POST /v1/audio/speech`), so
`studio/voice_take.py` uses it without special cases. VoiceStudio still does the **transcription** (the per-line "did it say what the
script says?" check); only the speech comes from here.

**Why it exists:** English used to be voiced by VoiceStudio's Qwen3-TTS voice "Ryan", whose pitch comes from a random seed
(98 to 239 Hz across seeds), so finished English videos sounded like different people. Kokoro with a fixed voice says the same text
the same way every time, like the German narrator (`voice-de/`).

**It borrows two things from VoiceStudio and installs nothing:** VoiceStudio's Python (it already has `mlx-audio`, `misaki` and the MLX
libraries) and the Kokoro model VoiceStudio cached in `~/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16/`.
`run.sh` sets `HF_HUB_OFFLINE=1`, so nothing is ever downloaded. If VoiceStudio is not installed or its Kokoro model is missing,
`run.sh start` says which, in plain words, and stops.

## Use

```bash
voice-en/run.sh start     # starts the server on 127.0.0.1:3911 and waits until it answers (about 5 s)
voice-en/run.sh status    # running? answering?
voice-en/run.sh stop
voice-en/run.sh restart
```

Then `python3 studio/make_video.py content/<id>/script.json` voices English scripts through it. If the server is not running, the
preflight stops with `start it: voice-en/run.sh start` (the text comes from `"start_hint"` in `studio/voices.json`). The log is
`voice-en/server.log` (replaced at every start), the process number `voice-en/server.pid`; both are git-ignored.

## How it behaves

* `POST /v1/audio/speech` with JSON `{"input", "voice": "af_heart", "response_format": "wav", "speed", "seed"}` returns `audio/wav`
  (24 kHz, mono, 16-bit). `GET /health` returns `{"status": "ok", "model": "kokoro-en-af_heart"}`. Listens on 127.0.0.1 only.
* It shares its code with the German server: `voice-en/server.py` loads `voice-de/server.py` for the sentence cutting, the request
  checks (size limits, one request at a time) and the HTTP layer. Only the model, the voice name and the English abbreviation list
  ("Mr.", "e.g.", "U.S.", "etc." do not end a sentence; neither do decimals like 3.5) are English. Because of that, **voice-de must stay
  where it is**. An abbreviation the rule does not know (for example "Ph.D." or "U.S.A.") can cause one extra pause.
* The text is cut into sentences, each sentence is voiced on its own, and they are joined with 0.30 s of silence (0.35 s after a
  question or an ellipsis). Kokoro pads every sentence with about 0.3 s of near-silence before and 0.5 s after the speech, which
  would make the gaps over a second, so that padding is trimmed (keeping 0.03 s) before the pause is added.
* **Deterministic:** the same text always gives byte-identical audio, and the request `seed` is ignored. Two things are needed:
  1. the model draws random noise, so the MLX random seed is set before every sentence;
  2. on the GPU, mlx-audio's inverse STFT adds overlapping sound frames with an atomic scatter-add whose order changes from run to run.
     That flips the last bit of a few samples (measured: every one of 8 repeats differed, by at most 6e-8 in a range of +-1).
     The server runs that one function on the CPU, where the order is fixed; the rest of the model stays on the GPU and the speed is
     the same (about 1 s for a 10 s narration).

  At start-up the server voices one sentence twice and compares; if they differ (for example after a VoiceStudio update changed
  mlx-audio) it refuses to start and says so in `server.log`. Consequence for the pipeline: English now makes **one** take
  (`"deterministic": true` in `studio/voices.json`), never re-rolls seeds or patches single lines; a line that fails the voice check has
  to be **reworded**.
* `speed` (0.5 to 2.0) is supported, but `studio/voices.json` does not send it.
* Check it by hand: POST the same text twice and compare the bytes (the fridge sample `studio/voice-tests/en-kokoro-af_heart.wav`, which
  `ref_f0_hz` in `studio/voices.json` was measured from, was made this way).

## Licences (checked on this Mac, 2026-10-15)

| Part | Licence | Source |
|---|---|---|
| Kokoro-82M weights `kokoro-v1_0.safetensors` and the voicepacks (`af_heart`), as converted by `mlx-community/Kokoro-82M-bf16` | **Apache-2.0** | the Kokoro-82M / mlx-community model cards (the local cache holds no card, so this was not re-read here) |
| `mlx-audio` 0.5.0 (the code that runs the model) and `mlx` 0.32.1 | **MIT** | `METADATA` of the installed packages |
| `misaki` 0.9.4 (text to phonemes) | **Apache-2.0** | `METADATA` |
| `spaCy` 3.8.15 and its model `en_core_web_sm` 3.8.0 (misaki uses them to tag words) | **MIT** | `METADATA` |
| `num2words` 0.5.14 (misaki spells out numbers with it) | **LGPL** | `METADATA` |
| `espeak-ng` 1.52.0 and `phonemizer-fork` 3.3.2: misaki's **fallback** for words missing from its dictionary | **GPL-3.0-or-later** | `METADATA` of phonemizer-fork; the library file is `espeakng_loader/libespeak-ng.1.52.0.dylib` |

About espeak-ng: it is **loaded** by this server (`lsof` on the running process shows copies of VoiceStudio's bundled
`espeakng_loader/libespeak-ng.dylib`, not the Homebrew one) and **used** only for words misaki does not know (for example invented
brand names). It runs as a separate library inside VoiceStudio's Python, which already ships it; this repository contains and
redistributes none of these packages (the server is plain Python that imports them). The GPL covers that software, not the audio it
helps to make. If the videos ever have to be shipped together with the software, ask again; the safe way is to keep these packages in
VoiceStudio's environment and not copy them anywhere.

Apache-2.0 and MIT both allow commercial use of the audio. Credit is good manners: *voice af_heart from Kokoro-82M by hexgrad, run with
mlx-audio*.

## Tests

`python3 -m unittest discover -s studio/tests -t .` includes `studio/tests/test_voice_en.py`: English sentence cutting (abbreviations,
decimals), the request check, the HTTP layer with a fake engine (no model needed), the silence trimming, the repeatable-overlap-add wrapper,
the model-file search, the `voices.json` routing and the per-language start hint. The shared helpers in `voice-de/server.py` are covered
by `studio/tests/test_voice_de.py` too, so a change there is checked for both languages.
