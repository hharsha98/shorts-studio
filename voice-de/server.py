#!/usr/bin/env python3
"""Thorsten German narrator: a tiny local speech server (Thorsten-Voice/Kokoro, Apache-2.0).

Runs INSIDE voice-de/.venv (that is where torch and kokoro live). Start it with voice-de/run.sh start.

  POST /v1/audio/speech   JSON {"input": "...", "voice": "thorsten", "response_format": "wav", "speed": 1.0, "seed": 1}
                          -> audio/wav bytes (24 kHz, mono, 16-bit PCM: the same format VoiceStudio sends)
  GET  /health            -> {"status": "ok", "model": "thorsten-kokoro"}

How the model is used (from the model card, https://huggingface.co/Thorsten-Voice/Kokoro):
  * KModel + KPipeline(lang_code="d"), the voicepack voices/thorsten.pt passed as a tensor, sample rate 24000;
  * the German phonemiser can print the short u-umlaut sign "ʏ", which the model does not know: it is replaced with "y";
  * "very long sentences may be truncated; splitting text on sentence boundaries is recommended": so the text is cut
    into sentences here, every sentence is voiced on its own, and the pieces are joined with short pauses.

The output is DETERMINISTIC: the model draws a little random noise while it makes the sound, so a fixed torch seed is
set before every sentence. The same text always gives the same audio, whatever else is in the request ("seed" in the
request is accepted but ignored). That also means a bad take cannot be fixed by trying another seed: reword the line.

Only the Python standard library is used outside ThorstenEngine (the pure helpers are unit-tested without the model, in
studio/tests/test_voice_de.py). The server listens on 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import array
import io
import json
import math
import re
import signal
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_DIR = HERE / "model"

HOST = "127.0.0.1"  # never anything else: this server has no login
DEFAULT_PORT = 3910
MODEL_NAME = "thorsten-kokoro"
VOICE_NAME = "thorsten"
SAMPLE_RATE = 24000
SEED = 0  # torch seed set before every sentence (see the module docstring)

MAX_INPUT_CHARS = 4096  # like VoiceStudio: the whole script must be SHORTER than this
MAX_BODY_BYTES = 64 * 1024  # 4095 characters can grow to ~25 KB once JSON escapes them
SPEED_MIN, SPEED_MAX = 0.5, 2.0

MAX_PIECE_CHARS = 220  # a sentence longer than this is cut at a comma (the model's limit is ~510 phonemes, about 400 letters)
SENTENCE_PAUSE_S = 0.30  # silence after a sentence ...
SENTENCE_PAUSE_LONG_S = 0.35  # ... after a question or an ellipsis
PHRASE_PAUSE_S = 0.12  # silence where a long sentence was cut at a comma


# --------------------------------------------------------------------------------------
# Cutting the text into pieces (pure)
# --------------------------------------------------------------------------------------

_SENTENCE_END = re.compile(r"""[.!?…]+["'“”‘’«»)\]]*(?=\s|$)""")  # a closing quote or bracket stays with its sentence (German: “ and « too)
# German abbreviations that end in a full stop without ending the sentence ("ca. 5 Meter")
ABBREVIATIONS = frozenset({"ca", "bzw", "usw", "etc", "dr", "nr", "prof", "ggf", "vgl", "evtl", "inkl", "str", "sog"})
_WORD_BEFORE = re.compile(r"([^\W\d_]+)$")
_SINGLE_LETTER_THEN_STOP = re.compile(r"^\s*[^\W\d_]\.(\s|$)")
_ENDS_WITH_LETTER_STOP = re.compile(r"(^|\s)[^\W\d_]\.\s*$")


def _is_abbreviation(text: str, stop_at: int) -> bool:
    """Is the full stop at text[stop_at] part of an abbreviation ("ca.", "z. B.", "d. h."), not the end of a sentence?"""
    if text[stop_at] != "." or text[stop_at + 1:stop_at + 2] in {".", "!", "?", "…"}:
        return False
    found = _WORD_BEFORE.search(text[:stop_at])
    if not found:
        return False
    word = found.group(1).lower()
    if word in ABBREVIATIONS:
        return True
    if len(word) == 1:  # "z. B.": the first part is followed by another letter + stop, the second part follows one
        return bool(_SINGLE_LETTER_THEN_STOP.match(text[stop_at + 1:])
                    or _ENDS_WITH_LETTER_STOP.search(text[:stop_at - 1]))
    return False


def split_sentences(text: str) -> list[str]:
    """The text as a list of sentences (a sentence ends at . ! ? or an ellipsis followed by a space or the end)."""
    text = " ".join(text.split())  # line breaks and runs of spaces become one space
    sentences: list[str] = []
    start = 0
    for found in _SENTENCE_END.finditer(text):
        if _is_abbreviation(text, found.start()):
            continue
        piece = text[start:found.end()].strip()
        if piece:
            sentences.append(piece)
        start = found.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def split_long(sentence: str, limit: int = MAX_PIECE_CHARS) -> list[str]:
    """A sentence of at most `limit` characters stays whole; a longer one is cut (again and again) at the comma / semicolon /
    colon / dash nearest its middle, else at the space nearest its middle, else after `limit` characters."""
    if len(sentence) <= limit:
        return [sentence]
    middle = len(sentence) / 2
    cuts = [m.end() for m in re.finditer(r"[,;:–—-]\s+", sentence)]
    cuts = [c for c in cuts if 0 < c < len(sentence)]
    if not cuts:
        cuts = [m.end() for m in re.finditer(r"\s+", sentence)]
        cuts = [c for c in cuts if 0 < c < len(sentence)]
    cut = min(cuts, key=lambda c: abs(c - middle)) if cuts else limit
    left, right = sentence[:cut].strip(), sentence[cut:].strip()
    if not left or not right:
        return [sentence[:limit], *split_long(sentence[limit:], limit)]
    return [*split_long(left, limit), *split_long(right, limit)]


def speakable(piece: str) -> bool:
    """Does the piece hold at least one letter or digit (a lone "…" or "-" cannot be voiced)?"""
    return any(ch.isalnum() for ch in piece)


def plan_pieces(text: str) -> list[tuple[str, float]]:
    """[(piece of text, seconds of silence after it)]: every sentence (cut at commas when it is long) with its pause.
    The last piece has no pause after it."""
    plan: list[tuple[str, float]] = []
    for sentence in split_sentences(text):
        parts = [p for p in split_long(sentence) if speakable(p)]
        long_pause = sentence.rstrip("\"'“”‘’«»)] ").endswith(("?", "…"))
        for k, part in enumerate(parts):
            last = k == len(parts) - 1
            plan.append((part, (SENTENCE_PAUSE_LONG_S if long_pause else SENTENCE_PAUSE_S) if last else PHRASE_PAUSE_S))
    if plan:
        plan[-1] = (plan[-1][0], 0.0)
    return plan


# --------------------------------------------------------------------------------------
# Request checking and the wav file (pure)
# --------------------------------------------------------------------------------------


class RequestError(Exception):
    """A request the server refuses: .status is the HTTP status, str(error) is a plain-English reason."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RequestError(400, f'"{name}" must be a number.')
    if not low <= value <= high:
        raise RequestError(400, f'"{name}" must be between {low:g} and {high:g} (got {value:g}).')
    return float(value)


def parse_request(raw: bytes) -> dict:
    """Check a POST /v1/audio/speech body. Returns {"text", "speed", "seed"} or raises RequestError.

    Like VoiceStudio's endpoint: "input" is required, "voice" and "response_format" are optional but must name what this
    server can do (the voice "thorsten", the format "wav"); other fields (model, instructions, ...) are ignored. "seed" must
    be a whole number when it is given, and is ignored (the output is deterministic)."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise RequestError(400, "The request body is not valid JSON (UTF-8).") from None
    if not isinstance(body, dict):
        raise RequestError(400, 'The request body must be one JSON object like {"input": "Hallo."}.')
    text = body.get("input")
    if not isinstance(text, str) or not text.strip():
        raise RequestError(400, '"input" must be the text to speak (a non-empty string).')
    if len(text) >= MAX_INPUT_CHARS:
        raise RequestError(400, f'"input" has {len(text)} characters, but this server takes fewer than {MAX_INPUT_CHARS} in one request.')
    voice = body.get("voice")
    if voice not in (None, "") and (not isinstance(voice, str) or voice.strip().lower() != VOICE_NAME):
        raise RequestError(400, f'This server has one voice, "{VOICE_NAME}" (the request asked for {voice!r}).')
    fmt = body.get("response_format")
    if fmt is not None and (not isinstance(fmt, str) or fmt.strip().lower() != "wav"):
        raise RequestError(400, f'Only "wav" can be sent back (the request asked for {fmt!r}).')
    speed = 1.0 if body.get("speed") is None else _number(body["speed"], "speed", SPEED_MIN, SPEED_MAX)
    seed = body.get("seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise RequestError(400, '"seed" must be a whole number when it is given.')
    if not any(speakable(p) for p in split_sentences(text)):
        raise RequestError(422, '"input" has nothing to say (no letters or digits).')
    return {"text": text, "speed": speed, "seed": seed}


def silence(seconds: float, sr: int = SAMPLE_RATE) -> array.array:
    return array.array("h", bytes(2 * max(0, round(seconds * sr))))


def join_pieces(audio: list[array.array], pauses: list[float], sr: int = SAMPLE_RATE) -> array.array:
    """The pieces one after the other; pauses[k] seconds of digital silence follow piece k (the last pause is not used)."""
    out = array.array("h")
    for k, piece in enumerate(audio):
        out += piece
        if k < len(audio) - 1:
            out += silence(pauses[k], sr)
    return out


def wav_bytes(samples: array.array, sr: int = SAMPLE_RATE) -> bytes:
    """A mono 16-bit PCM wav file."""
    pcm = array.array("h", samples)
    if sys.byteorder == "big":
        pcm.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synthesize(engine, text: str, speed: float = 1.0) -> tuple[array.array, int]:
    """(samples, number of pieces) for the whole text: engine.speak(piece, speed) per piece, joined with the planned pauses."""
    plan = plan_pieces(text)
    audio = [engine.speak(piece, speed) for piece, _pause in plan]
    return join_pieces(audio, [pause for _piece, pause in plan]), len(plan)


# --------------------------------------------------------------------------------------
# The model (needs torch + kokoro: only inside voice-de/.venv)
# --------------------------------------------------------------------------------------


class ThorstenEngine:
    """Loads the Thorsten model once; speak() voices one piece of text and gives 16-bit samples at 24 kHz."""

    def __init__(self, model_dir: Path = MODEL_DIR, device: str = "cpu"):
        import numpy as np
        import torch
        from kokoro import KModel, KPipeline
        from loguru import logger

        logger.remove()  # kokoro logs its whole config at DEBUG level
        logger.add(sys.stderr, level="WARNING")
        self._np, self._torch = np, torch
        config, weights, voicepack = model_dir / "config.json", model_dir / "model.pth", model_dir / "voices" / "thorsten.pt"
        for needed in (config, weights, voicepack):
            if not needed.is_file():
                raise FileNotFoundError(f"{needed} is missing. See voice-de/README.md for the three files the model needs.")
        # repo_id only names the architecture: with config + model given, nothing is downloaded
        kmodel = KModel(repo_id="hexgrad/Kokoro-82M", config=str(config), model=str(weights)).to(device).eval()
        self.pipeline = KPipeline(lang_code="d", repo_id="hexgrad/Kokoro-82M", model=kmodel)
        original_g2p = self.pipeline.g2p
        # model card: the German phonemiser can print "ʏ" (short u-umlaut), the model only knows "y"
        self.pipeline.g2p = lambda text: (lambda ps, tokens: (ps.replace("ʏ", "y"), tokens))(*original_g2p(text))
        self.voice = torch.load(voicepack, map_location="cpu", weights_only=True)
        self.device = device

    def speak(self, piece: str, speed: float = 1.0) -> array.array:
        np, torch = self._np, self._torch
        torch.manual_seed(SEED)  # the decoder draws random noise: a fixed seed makes the same text sound the same
        chunks = []
        with torch.no_grad():
            for _graphemes, _phonemes, audio in self.pipeline(piece.replace("\n", " "), voice=self.voice, speed=speed, split_pattern=None):
                if audio is not None:
                    chunks.append(audio.detach().cpu().numpy())
        if not chunks:
            return array.array("h")
        pcm = (np.clip(np.concatenate(chunks), -1.0, 1.0) * 32767.0).astype("<i2")
        return array.array("h", pcm.tobytes())


# --------------------------------------------------------------------------------------
# The HTTP server
# --------------------------------------------------------------------------------------


def make_handler(engine, lock: threading.Lock):
    """The request handler class. `engine` needs speak(piece, speed) -> array('h'); one request voices at a time (lock)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "ThorstenVoice/1"

        def log_message(self, fmt, *args):  # one line per request on stderr (voice-de/server.log); never the text itself
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} {self.address_string()} {fmt % args}\n")
            sys.stderr.flush()

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

        def _refuse(self, status: int, message: str) -> None:
            self._send_json(status, {"error": message})

        def do_GET(self):  # noqa: N802 (the name is fixed by http.server)
            if self.path.split("?")[0] == "/health":
                self._send_json(200, {"status": "ok", "model": MODEL_NAME})
            else:
                self._refuse(404, f"Nothing here: {self.path}. This server has GET /health and POST /v1/audio/speech.")

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0] != "/v1/audio/speech":
                self._refuse(404, f"Nothing here: {self.path}. This server has GET /health and POST /v1/audio/speech.")
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self._refuse(415, "Send the request as JSON (Content-Type: application/json).")
                return
            length = self.headers.get("Content-Length")
            if length is None:
                self._refuse(411, "The request needs a Content-Length.")
                return
            try:
                size = int(length)
            except ValueError:
                size = -1
            if size < 0:
                self._refuse(400, "The Content-Length is not a number.")
                return
            if size > MAX_BODY_BYTES:
                self._refuse(413, f"The request is {size} bytes; the limit is {MAX_BODY_BYTES}.")
                return
            try:
                request = parse_request(self.rfile.read(size))
            except RequestError as exc:
                self._refuse(exc.status, str(exc))
                return
            started = time.time()
            try:
                with lock:
                    samples, pieces = synthesize(engine, request["text"], request["speed"])
            except Exception as exc:  # the model broke on this text: say so, keep serving
                import traceback
                traceback.print_exc()
                self._refuse(500, f"The voice engine failed on this text: {type(exc).__name__}: {exc}")
                return
            if not samples:
                self._refuse(422, "The voice engine made no audio for this text.")
                return
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} voiced {len(request['text'])} characters in {pieces} piece(s): "
                             f"{len(samples) / SAMPLE_RATE:.1f} s of audio in {time.time() - started:.1f} s\n")
            self._send(200, wav_bytes(samples), "audio/wav")

    return Handler


def make_server(engine, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """The server for `engine`, bound to 127.0.0.1 (port 0 = any free port, for tests)."""
    server = ThreadingHTTPServer((HOST, port), make_handler(engine, threading.Lock()))
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Thorsten German narrator (local speech server on 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port to listen on (default {DEFAULT_PORT})")
    parser.add_argument("--device", default="cpu", help="where the model runs: cpu (default, fast enough and repeatable) or mps")
    args = parser.parse_args(argv)
    started = time.time()
    engine = ThorstenEngine(device=args.device)
    engine.speak("Hallo, hier spricht Thorsten.")  # warm-up: the first sentence is slower than the rest
    server = make_server(engine, args.port)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    print(f"ready: http://{HOST}:{args.port} (model {MODEL_NAME}, device {args.device}, loaded in {time.time() - started:.1f} s)", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
