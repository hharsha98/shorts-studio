# voice-de: the German narrator (Thorsten)

A small local speech server for the German Shorts. It runs **Thorsten-Voice/Kokoro**, a German fine-tune of the 82-million-parameter
Kokoro text-to-speech model, in its own isolated Python environment, and speaks the same way VoiceStudio does
(`POST /v1/audio/speech`), so `studio/voice_take.py` can use it without special cases. VoiceStudio still does the
**transcription** (the per-line "did it say what the script says?" check); only the speech comes from here.

## Licences (checked on the model card, 2026-10-14)

| Part | Licence | Source |
|---|---|---|
| Model `Thorsten-Voice/Kokoro` (weights, voicepack, config) | **Apache-2.0** | model card front matter `license: apache-2.0`, and its "License" section |
| Training data, the Thorsten-Voice dataset | **CC0** (public domain) | model card: "Thorsten-Voice dataset (CC0 / public domain)" |
| Base model `hexgrad/Kokoro-82M` (architecture only, nothing is downloaded from it) | Apache-2.0 | model card |
| Code forks `semidark/kokoro`, `semidark/misaki` | Apache-2.0 | GitHub repository licence field |
| `espeak-ng` (pronunciation engine). The running server uses the copy bundled in the venv by the `espeakng-loader` wheel (libespeak-ng 1.52.0); `brew install espeak-ng` was done because the model card says so, but that Homebrew copy is installed and not loaded | GPL-3.0-or-later (either copy) | `brew info espeak-ng`; `lsof -p <server pid>` shows the loaded library |

Apache-2.0 and CC0 both allow commercial use of the audio; Apache-2.0 asks that the licence text and notices travel with
redistributed copies of the model files (this repository does not redistribute them: `voice-de/model/` is git-ignored).
No attribution is legally required for CC0 data, but credit is good manners: *voice by Thorsten-Voice (thorsten-voice.de),
model Thorsten-Voice/Kokoro on Hugging Face*.

## What was downloaded (approved list, nothing else)

| What | Size | Where |
|---|---|---|
| `brew install espeak-ng` (plus its one dependency `pcaudiolib`) | 26.5 MB + 0.2 MB installed (bottles) | `/opt/homebrew/Cellar/` |
| Python packages (95, exact versions in `requirements.txt`; torch is the biggest wheel, 121 MB) | about 170 MB of wheels to download, 890 MB installed | `voice-de/.venv/` |
| `model.pth` (default checkpoint, epoch 5) | 327,231,582 bytes | `voice-de/model/` |
| `voices/thorsten.pt` (the voicepack) | 523,450 bytes | `voice-de/model/voices/` |
| `config.json` | 2,351 bytes | `voice-de/model/` |

Model repo revision `734e593d320a3d876bede7020f773dfd481a0cc7`. SHA-256:
`model.pth` 36dde15c...59ce, `voices/thorsten.pt` 9d98b775...06d7, `config.json` 5abb01e2...c17f (full values: run `shasum -a 256`).
The other nine training checkpoints (`model_ep*.pth`, about 2.9 GB) were deliberately **not** downloaded.

The two GitHub forks are pinned to commits: `misaki` at `6d252a2e...` (the commit named on the model card) and `kokoro` at
`b96fef95...` (its latest commit when this was set up; the card only says `git+https://github.com/semidark/kokoro.git`).

## Rebuild from scratch

```bash
brew install espeak-ng
uv venv voice-de/.venv --python 3.12
uv pip install --python voice-de/.venv/bin/python -r voice-de/requirements.txt
# the three model files (revision above), for example with the venv's Python:
voice-de/.venv/bin/python -c "
from huggingface_hub import hf_hub_download
for f in ('config.json', 'voices/thorsten.pt', 'model.pth'):
    hf_hub_download('Thorsten-Voice/Kokoro', f, revision='734e593d320a3d876bede7020f773dfd481a0cc7', local_dir='voice-de/model')
"
```

(Why a separate environment: torch and friends are about 900 MB and must not touch the other projects' Python packages.)

## Use

```bash
voice-de/run.sh start    # starts the server on 127.0.0.1:3910 and waits until it answers
voice-de/run.sh status   # running? answering?
voice-de/run.sh stop
```

Then `python3 studio/make_video.py content/<id>/script.json` voices German scripts through it. If the server is not
running, the preflight stops with `start it: voice-de/run.sh start`. The log is `voice-de/server.log` (replaced at every start),
the process number `voice-de/server.pid`.

## How it behaves

* `POST /v1/audio/speech` with JSON `{"input", "voice": "thorsten", "response_format": "wav", "speed", "seed"}` returns
  `audio/wav` (24 kHz, mono, 16-bit). `GET /health` returns `{"status": "ok", "model": "thorsten-kokoro"}`. Listens on 127.0.0.1 only.
* The text is cut into sentences (the model card: "very long sentences may be truncated"), each sentence is voiced on its own and
  they are joined with 0.30 s of silence (0.35 s after a question or an ellipsis). `voice_take.py` finds the script-line
  boundaries in these silences.
* As the model card requires, the phoneme `ʏ` (short ü) is replaced with `y` before synthesis.
* **Deterministic:** the model's decoder draws random noise, so a fixed torch seed is set before every sentence. The same text always
  gives byte-identical audio and the request `seed` is ignored. Consequence: the pipeline makes **one** take for German
  (`"deterministic": true` in `studio/voices.json`) and never re-rolls seeds or re-voices single lines; a line that fails the voice
  check has to be **reworded**.
* Runs on CPU (about 7 s for a whole 57 s script on this Mac). `--device mps` exists but CPU is repeatable and fast enough.
* `speed` (0.5 to 2.0) is supported by the server but `studio/voices.json` does not send it, so the default pace is used.

## Tests

`python3 -m unittest discover -s studio/tests -t .` includes `studio/tests/test_voice_de.py`: the server's pure helpers and HTTP layer
(with a fake engine, no model needed), the routing per language, the deterministic one-take rule and the preflight messages.
