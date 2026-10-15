#!/usr/bin/env python3
"""English narrator: a tiny local speech server for Kokoro "af_heart" (US female; Kokoro-82M weights Apache-2.0).

Runs with VoiceStudio's own Python (it already has mlx-audio, misaki and the MLX libraries). Start it with voice-en/run.sh start.

  POST /v1/audio/speech   JSON {"input": "...", "voice": "af_heart", "response_format": "wav", "speed": 1.0, "seed": 1}
                          -> audio/wav bytes (24 kHz, mono, 16-bit PCM: the same format VoiceStudio sends)
  GET  /health            -> {"status": "ok", "model": "kokoro-en-af_heart"}

It speaks exactly like voice-de/server.py (the German narrator) and shares its code: the text is cut into sentences, every sentence
is voiced on its own, the pieces are joined with short pauses (0.30 s, 0.35 s after a question or an ellipsis), the request is
checked the same way. Only the model, the voice and the list of English abbreviations differ. One more thing is English-only: Kokoro
pads every piece with about 0.3 s of near-silence before and 0.5 s after (measured), which would make the gap between sentences
over a second instead of the planned 0.30 s, so the quiet at both ends of each piece is trimmed (trim_silence) before the pause is added.

The output is DETERMINISTIC: the same text always gives byte-identical audio, whatever else is in the request ("seed" in the
request is accepted but ignored). Two things make that true:
  * the model draws random noise while it makes the sound, so the MLX random seed is set before every sentence;
  * the GPU adds the overlapping sound frames together in a different order every run (an atomic scatter-add), which changes the
    last bit of a few samples. The one function that does this (the inverse STFT in mlx-audio's Kokoro) therefore runs on the CPU,
    where the order is fixed. The rest of the model still runs on the GPU, and nothing is slower.
The server checks this at start-up (it voices a sentence twice and compares) and refuses to start if the two differ.
A bad take cannot be fixed by trying another seed: reword the line.

Only the Python standard library is used outside KokoroEnglishEngine (the pure helpers are unit-tested without the model, in
studio/tests/test_voice_en.py). The server listens on 127.0.0.1 only. Nothing is ever downloaded: the model must already be in the
Hugging Face cache (VoiceStudio's Kokoro put it there), see find_model_dir().
"""

from __future__ import annotations

import argparse
import array
import importlib.util
import os
import signal
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_shared():
    """voice-de/server.py as a module: its sentence cutting, request checking, wav writing and HTTP layer are shared with this server.
    (The folder name has a hyphen, so it cannot be imported the normal way.) If it is loaded already, that copy is used."""
    loaded = sys.modules.get("voice_de_server")
    if loaded is not None:
        return loaded
    path = ROOT / "voice-de" / "server.py"
    spec = importlib.util.spec_from_file_location("voice_de_server", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["voice_de_server"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop("voice_de_server", None)
        raise
    return module


shared = load_shared()
RequestError = shared.RequestError

HOST = shared.HOST  # 127.0.0.1, never anything else: this server has no login
DEFAULT_PORT = 3911
SAMPLE_RATE = shared.SAMPLE_RATE
MODEL_NAME = "kokoro-en-af_heart"
VOICE_NAME = "af_heart"
SEED = 0  # MLX random seed set before every sentence (see the module docstring)

MODEL_REPO = "mlx-community/Kokoro-82M-bf16"  # only the name of the Hugging Face cache folder: nothing is downloaded
MODEL_FILES = ("config.json", "kokoro-v1_0.safetensors", f"voices/{VOICE_NAME}.safetensors")

# English abbreviations whose full stop does not end a sentence ("Mr. Smith"). Single letters ("e.g.", "U.S.", "a.m.") are handled by
# the shared rule in voice-de/server.py; decimals ("3.5") never split because a sentence ends only at a full stop followed by a space.
ABBREVIATIONS = frozenset({"mr", "mrs", "ms", "dr", "prof", "jr", "sr", "vs", "etc", "approx", "fig", "inc", "ltd", "co", "cf", "ca"})
ENGLISH = shared.Profile(MODEL_NAME, VOICE_NAME, ABBREVIATIONS, "KokoroEnglishVoice/1")

WARMUP_TEXT = "Your fridge is secretly a heater."

TRIM_LEVEL = 100  # a sample quieter than this (of 32767: about -50 dB) is silence at the edge of a piece ...
TRIM_KEEP_S = 0.03  # ... but this much quiet stays on each side so that soft starts and fading endings are not cut


# --------------------------------------------------------------------------------------
# The shared helpers with the English profile filled in (pure)
# --------------------------------------------------------------------------------------


def split_sentences(text: str) -> list[str]:
    return shared.split_sentences(text, ABBREVIATIONS)


def plan_pieces(text: str) -> list[tuple[str, float]]:
    return shared.plan_pieces(text, ABBREVIATIONS)


def parse_request(raw: bytes) -> dict:
    return shared.parse_request(raw, VOICE_NAME)


def make_server(engine, port: int = DEFAULT_PORT):
    """The server for `engine`, bound to 127.0.0.1 (port 0 = any free port, for tests)."""
    return shared.make_server(engine, port, ENGLISH)


def trim_silence(samples: array.array, sr: int = SAMPLE_RATE, level: int = TRIM_LEVEL, keep_s: float = TRIM_KEEP_S) -> array.array:
    """The piece without the near-silence Kokoro puts before and after the speech: everything before the first and after the last
    sample of at least `level` is cut, except `keep_s` seconds on each side. A piece that never gets that loud is returned as it is."""
    first = next((k for k, value in enumerate(samples) if abs(value) >= level), None)
    if first is None:
        return samples
    last = len(samples) - 1 - next(k for k, value in enumerate(reversed(samples)) if abs(value) >= level)
    keep = round(keep_s * sr)
    return samples[max(0, first - keep):last + 1 + keep]


# --------------------------------------------------------------------------------------
# Finding the model files (pure, no model needed)
# --------------------------------------------------------------------------------------


def hub_cache_dir() -> Path:
    """The Hugging Face cache folder (HF_HUB_CACHE, else HF_HOME/hub, else ~/.cache/huggingface/hub)."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    home = os.environ.get("HF_HOME")
    return (Path(home).expanduser() if home else Path.home() / ".cache" / "huggingface") / "hub"


def find_model_dir(hub_dir: Path | None = None) -> Path:
    """The newest cached snapshot of mlx-community/Kokoro-82M-bf16 that has the config, the weights and the af_heart voice.
    Raises FileNotFoundError with a plain-English reason (what is missing and where it comes from) when there is none."""
    hub_dir = hub_cache_dir() if hub_dir is None else hub_dir
    snapshots_dir = hub_dir / f"models--{MODEL_REPO.replace('/', '--')}" / "snapshots"
    snapshots = sorted((p for p in snapshots_dir.glob("*") if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True) if snapshots_dir.is_dir() else []
    if not snapshots:
        raise FileNotFoundError(f"The Kokoro model {MODEL_REPO} is not in the Hugging Face cache ({snapshots_dir} does not exist). "
                                "VoiceStudio puts it there when its Kokoro engine is installed; this server never downloads anything.")
    for snapshot in snapshots:
        if all((snapshot / name).is_file() for name in MODEL_FILES):
            return snapshot
    missing = [name for name in MODEL_FILES if not (snapshots[0] / name).is_file()]
    raise FileNotFoundError(f"The cached Kokoro model {snapshots[0]} is incomplete: missing {', '.join(missing)}. "
                            "Install or repair VoiceStudio's Kokoro engine; this server never downloads anything.")


# --------------------------------------------------------------------------------------
# The model (needs mlx-audio: only inside VoiceStudio's Python)
# --------------------------------------------------------------------------------------


def make_overlap_add_repeatable(istftnet, mx) -> None:
    """Run mlx-audio's inverse STFT on the CPU. On the GPU its overlap-add is a scatter-add whose order differs from run to run,
    which flips the last bit of a few samples, so the same text would not give the same bytes. On the CPU the order is fixed.
    Raises RuntimeError when mlx-audio no longer has the function (then determinism could not be promised)."""
    original = getattr(istftnet, "istft", None)
    if not callable(original):
        raise RuntimeError("mlx-audio's Kokoro code has no istft function any more, so this server cannot make its output repeatable. "
                           "voice-en/server.py needs an update for this mlx-audio version.")
    if getattr(original, "runs_on_cpu", False):
        return

    def istft_on_cpu(*args, **kwargs):
        with mx.stream(mx.cpu):
            return original(*args, **kwargs)

    istft_on_cpu.runs_on_cpu = True
    istftnet.istft = istft_on_cpu


class KokoroEnglishEngine:
    """Loads Kokoro once; speak() voices one piece of text with af_heart and gives 16-bit samples at 24 kHz (edges trimmed)."""

    def __init__(self, model_dir: Path):
        import mlx.core as mx
        import numpy as np
        from mlx_audio.tts.models.kokoro import istftnet
        from mlx_audio.tts.models.kokoro.pipeline import KokoroPipeline
        from mlx_audio.tts.utils import load_model

        self._mx, self._np = mx, np
        make_overlap_add_repeatable(istftnet, mx)
        # model_type given: the folder name is a hash, so mlx-audio could not guess the model from it
        model = load_model(Path(model_dir), model_type="kokoro")
        # repo_id is only used to look up voices by name; the voice is passed as a file path below, so nothing is looked up or downloaded
        self.pipeline = KokoroPipeline(lang_code="a", model=model, repo_id=MODEL_REPO)
        self.voice_path = str(Path(model_dir) / "voices" / f"{VOICE_NAME}.safetensors")

    def speak(self, piece: str, speed: float = 1.0) -> array.array:
        mx, np = self._mx, self._np
        mx.random.seed(SEED)  # the decoder draws random noise: a fixed seed makes the same text sound the same
        chunks = []
        for result in self.pipeline(piece.replace("\n", " "), voice=self.voice_path, speed=speed, split_pattern=None):
            if result.audio is not None:
                chunks.append(np.array(result.audio).reshape(-1))
        mx.clear_cache()
        if not chunks:
            return array.array("h")
        pcm = np.rint(np.clip(np.concatenate(chunks), -1.0, 1.0) * 32767.0).astype("<i2")
        return trim_silence(array.array("h", pcm.tobytes()))


# --------------------------------------------------------------------------------------
# Start-up
# --------------------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="English narrator, Kokoro af_heart (local speech server on 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default {DEFAULT_PORT})")
    parser.add_argument("--check", action="store_true", help="only look for the model files, say what is missing (if anything) and exit")
    args = parser.parse_args(argv)
    try:
        model_dir = find_model_dir()
    except FileNotFoundError as exc:
        print(exc, file=sys.stdout if args.check else sys.stderr, flush=True)
        return 1
    if args.check:
        print(f"The model files are there: {model_dir}")
        return 0
    started = time.time()
    engine = KokoroEnglishEngine(model_dir)
    first, second = engine.speak(WARMUP_TEXT), engine.speak(WARMUP_TEXT)  # also the warm-up: the first sentence is slower than the rest
    if not first or first != second:
        print("Cannot start: the same sentence voiced twice did not give identical audio, so the output would not be repeatable. "
              "Nothing is served. (mlx-audio or MLX may have changed: see make_overlap_add_repeatable in voice-en/server.py.)", file=sys.stderr, flush=True)
        return 1
    server = make_server(engine, args.port)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"ready: http://{HOST}:{args.port} (model {MODEL_NAME}, loaded in {time.time() - started:.1f} s, repeatable output checked)", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
