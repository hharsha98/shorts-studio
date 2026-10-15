#!/usr/bin/env python3
"""voice_take.py - the narration as ONE take, with a steadiness gate, pacing and per-line repair.

Why: the voice engine (Qwen3-TTS CustomVoice in VoiceStudio) picks a random pitch register for every request. Voicing
each script line on its own gave lines up to 14 semitones apart (the same narrator suddenly sounding like somebody
else). Voicing the WHOLE script in one request keeps one register; the audio expert measured no big jumps and 97-99%
word accuracy (work/_expert/audio/). The engine also ignores the "instructions" text of studio/voices.json (same seed
+ other instructions = byte-identical audio), so the SEED is the only dial: a bad take is re-rolled with the next seed.

What produce_narration() does (every number below is a module constant):
  1. voice the whole script in one request (seed S), transcribe it with word timestamps (VoiceStudio / Whisper)
  2. map the words to the script lines (studio/captions.py align_words) and put each line boundary in the middle of the
     longest real silence (>= 120 ms below -42 dBFS) within +-0.35 s of where the words say the boundary is
  3. pacing: every silence longer than 0.45 s is shortened to 0.35 s (cut in the middle, 15 ms fades)
  4. cut the lines; each cut goes through the SAME per-line word/letter error gate as before (make_video's grade_line)
  5. patch loop: a line that fails is voiced alone with seeds 1..6; the first candidate that passes the voice check AND
     has a median pitch within 2 semitones of its neighbours is loudness-matched and spliced into the line's own
     silence. Six failed seeds, or more than 3 failed lines: the whole take is dropped
  6. take continuity gate: per-line median pitch (YIN, voice_pitch.py in MoneyPrinterTurbo's numpy venv) and loudness
     (RMS of the active frames). Accepted only if every line is within 5 st of the take's median, the line medians
     have a spread (SD) <= 2 st, no two neighbouring lines differ by more than 3 st or 3 dB, and the take's median is
     within 3 st of the channel's reference voice (ref_f0_hz in voices.json: the sample the user listened to)
  7. a rejected take is re-rolled with the next seed (up to 6 whole takes), then the run fails in plain words
  8. the accepted take is cached by (script LINES, voice, model, seed): the same script is instant the next time. The key
     holds the list of lines, not the joined text, because a take is cut at the line boundaries: moving a boundary without
     changing a word must voice again. A pointer file remembers which seed was accepted for a script, so a take found with
     --voice-seed 7 is still reused when the next run starts at seed 1 and every seed there was rejected earlier

Engines: VoiceStudio always does the TRANSCRIPTION. The speech comes from VoiceStudio too, unless studio/voices.json gives the
language an "engine_url": then only the speech request goes there (the German Thorsten voice in voice-de/, same POST
/v1/audio/speech interface). An engine marked "deterministic" says the same text the same way every time, so a seed re-roll or a
re-voiced line would only repeat it: such a script gets ONE take, no patch loop, and a failing line is reported with what was
heard, so the line can be reworded.

Python standard library only (plus the voice_pitch.py subprocess for pitch). The pure parts (silence search, boundary
snapping, pause shortening, the gate maths, the patch rule, cache keys) are unit-tested in studio/tests/test_voice_take.py
with a fake VoiceStudio.

Command line:  python3 studio/voice_take.py refs    measure studio/voice-tests/<lang>-<voice>.wav, store ref_f0_hz in voices.json
"""

from __future__ import annotations

import array
import datetime
import hashlib
import http.client
import json
import math
import shutil
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parent
ROOT = STUDIO_DIR.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))
import captions as captionlib  # noqa: E402  (the script's words with Whisper's timing)

VOICES_FILE = STUDIO_DIR / "voices.json"
MPT_DIR = ROOT / "MoneyPrinterTurbo"
PITCH_SCRIPT = STUDIO_DIR / "voice_pitch.py"
VOICE_TESTS_DIR = STUDIO_DIR / "voice-tests"

SAMPLE_RATE = 24000
INPUT_MAX_CHARS = 4096  # VoiceStudio refuses longer text; the whole script must be SHORTER than this
FRAME_HOP_S = 0.010  # energy frames: 40 ms windows every 10 ms
SILENCE_FLOOR_DB = -42.0  # a frame below this is silence
SILENCE_MIN_S = 0.12  # a silence must last this long to count
SNAP_SLACK_S = 0.35  # a line boundary may move this far to reach a silence
MIN_LINE_S = 0.05
ACTIVE_FLOOR_DB = -45.0  # frames below this do not count towards a line's loudness

PAUSE_MAX_S = 0.45  # a silence longer than this is shortened ...
PAUSE_TARGET_S = 0.35  # ... to this
FADE_S = 0.015

# Limits target the problem the user heard: octave-sized register flips between sentences (7-14 st measured in v1).
# Natural sentence intonation (question vs statement) moves 3-4 st, so 3.0 rejected most good takes (2026-10-14 batch:
# 8 of 12 scripts failed on single 3.0-3.8 st steps); 4.0 still blocks every flip measured in v1.
MAX_LINE_OFFSET_ST = 5.0  # every line's median pitch vs the take's median
MAX_SD_ST = 2.5  # spread of the line medians
MAX_JUMP_DB = 3.5  # neighbouring lines, loudness
MAX_JUMP_ST = 4.0  # neighbouring lines, pitch
MAX_REF_ST = 4.0  # take median vs the channel's reference voice (takes also land an octave low, ~100 Hz: still rejected)
PATCH_NEIGHBOUR_ST = 2.0
PATCH_SEEDS = 6
PATCH_GAIN_CAP_DB = 6.0
MAX_PATCH_LINES = 3  # more failed lines than this: re-roll the whole take instead
MAX_TAKES = 12  # ~1 min per take; a good take usually appears within 12 seeds
GATE_VERSION = 3  # bump when a rule above (or the per-line voice check, make_video.grade_line) changes: earlier "rejected" verdicts are
# then forgotten. 2: numbers are compared as one "<num>" per run (studio/number_words.py), so digit-vs-word rejections are retried
# 3: limits relaxed to natural intonation (see above)
CACHE_VERSION = 2  # 2: the key is made from the list of lines (1 hashed the joined text)

PROBE_TEXT = "A short probe sentence about a fridge."
PROBE_OTHER_INSTRUCTIONS = "Shout every word, very fast and angry."


class VoiceTakeError(Exception):
    """Something the user must hear about in plain words (VoiceStudio down, no steady take found, ...)."""


class TakeRejected(Exception):
    """This one take (seed) is not good enough; the message says why. The caller re-rolls with the next seed.
    `lines` (optional) holds the lines that failed the voice check: [{"index", "text", "heard", "wer", "cer", "threshold"}]."""

    def __init__(self, message: str, lines: list[dict] | None = None):
        super().__init__(message)
        self.lines = lines or []


# --------------------------------------------------------------------------------------
# Audio basics (pure, standard library)
# --------------------------------------------------------------------------------------


def read_wav(path) -> tuple[array.array, int]:
    """(16-bit samples, sample rate) of a PCM wav; several channels are averaged."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise VoiceTakeError(f"{path} is not a 16-bit wav file.")
        channels, sr = w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    if channels > 1:
        columns = [samples[c::channels] for c in range(channels)]
        samples = array.array("h", (sum(vals) // channels for vals in zip(*columns)))
    return samples, sr


def write_wav(path, samples: array.array, sr: int = SAMPLE_RATE) -> None:
    out = array.array("h", samples)
    if sys.byteorder == "big":
        out.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(out.tobytes())


class Framing:
    """Energy frames: 40 ms windows every 10 ms. Frame k covers samples [k*hop, k*hop + win)."""

    def __init__(self, sr: int = SAMPLE_RATE):
        self.sr = sr
        self.hop = round(sr * FRAME_HOP_S)
        self.win = 4 * self.hop

    def centre(self, k: int) -> float:
        return (k * self.hop + self.win / 2) / self.sr

    def frame_range(self, lo: float, hi: float, count: int) -> range:
        """Indexes of the frames whose centre lies in [lo, hi)."""
        first = max(0, math.ceil((lo * self.sr - self.win / 2) / self.hop))
        last = min(count, math.ceil((hi * self.sr - self.win / 2) / self.hop))
        return range(first, max(first, last))


def frame_db(samples: array.array, fr: Framing) -> list[float]:
    """Level of every frame in dBFS (10*log10 of the mean square, so a full-scale square wave is 0 dB)."""
    blocks = len(samples) // fr.hop
    energy = [math.sumprod(chunk, chunk) for chunk in (samples[b * fr.hop:(b + 1) * fr.hop] for b in range(blocks))]
    scale = fr.win * 32768.0 ** 2
    return [10 * math.log10((energy[k] + energy[k + 1] + energy[k + 2] + energy[k + 3]) / scale + 1e-24)
            for k in range(max(0, blocks - 3))]


def find_silences(db: list[float], fr: Framing, floor: float = SILENCE_FLOOR_DB, min_len: float = SILENCE_MIN_S) -> list[tuple[float, float]]:
    """(start, end) seconds of every run of quiet frames that lasts at least min_len (inside the truly quiet audio)."""
    runs, start = [], None
    for k, level in enumerate([*db, 1e9]):
        quiet = level < floor
        if quiet and start is None:
            start = k
        elif not quiet and start is not None:
            if (k - start) * fr.hop / fr.sr >= min_len:
                runs.append((fr.centre(start), fr.centre(k)))
            start = None
    return runs


def speech_extent(db: list[float], fr: Framing, lo: float, hi: float, floor: float = SILENCE_FLOOR_DB) -> tuple[float, float] | None:
    """(first sound, last sound) in seconds inside [lo, hi), or None when that stretch is silent."""
    voiced = [k for k in fr.frame_range(lo, hi, len(db)) if db[k] > floor]
    if not voiced:
        return None
    return max(lo, voiced[0] * fr.hop / fr.sr), min(hi, (voiced[-1] * fr.hop + fr.win) / fr.sr)


def active_loudness(db: list[float], fr: Framing, lo: float, hi: float, floor: float = ACTIVE_FLOOR_DB) -> float | None:
    """Loudness in dB of the sound in [lo, hi): the power average of the frames above the floor (None if there are none)."""
    levels = [db[k] for k in fr.frame_range(lo, hi, len(db)) if db[k] > floor]
    if not levels:
        return None
    return 10 * math.log10(sum(10 ** (v / 10) for v in levels) / len(levels))


def apply_gain(samples: array.array, gain_db: float) -> array.array:
    g = 10 ** (gain_db / 20)
    return array.array("h", (max(-32768, min(32767, round(s * g))) for s in samples))


def silence(seconds: float, sr: int = SAMPLE_RATE) -> array.array:
    return array.array("h", bytes(2 * max(0, round(seconds * sr))))


def _faded(piece: array.array, n: int, fade_in: bool, fade_out: bool) -> array.array:
    out = array.array("h", piece)
    n = min(n, len(out) // 2)
    for i in range(n):
        if fade_in:
            out[i] = int(out[i] * (i / n))
        if fade_out:
            out[len(out) - 1 - i] = int(out[len(out) - 1 - i] * (i / n))
    return out


# --------------------------------------------------------------------------------------
# Boundaries, pacing (pure)
# --------------------------------------------------------------------------------------


def snap_boundary(prev_end: float, next_start: float, silences: list[tuple[float, float]],
                  slack: float = SNAP_SLACK_S) -> tuple[float, bool]:
    """Where to cut between two lines: the middle of the LONGEST silence that touches the window
    [prev_end - slack, next_start + slack]. (time, True) when snapped, otherwise (midpoint of the two words, False)."""
    found = [s for s in silences if s[1] > prev_end - slack and s[0] < next_start + slack]
    if not found:
        return (prev_end + next_start) / 2, False
    centre = (prev_end + next_start) / 2
    a, b = max(found, key=lambda s: (round(s[1] - s[0], 3), -abs((s[0] + s[1]) / 2 - centre)))  # longest; a tie: nearest the gap
    return (a + b) / 2, True


def _distance_to_gap(silence: tuple[float, float], gap: tuple[float, float]) -> float:
    """How far the middle of a silence lies from a gap between two lines (0 when it is inside the gap)."""
    mid = (silence[0] + silence[1]) / 2
    lo, hi = min(gap), max(gap)
    return max(lo - mid, mid - hi, 0.0)


def plan_cuts(spans: list[tuple[float, float]], silences: list[tuple[float, float]], total: float,
              slack: float = SNAP_SLACK_S) -> tuple[list[float], list[bool]]:
    """One cut between every two neighbouring lines (n-1 of them), always increasing and inside the take.

    Every silence may serve only ONE boundary: the one whose gap (last word of a line to first word of the next) it lies
    nearest to. Without that, a very short line (1-3 words) sits between two silences that both reach into the window of
    both its boundaries, and both cuts land in the same silence, which empties that line."""
    gaps = [(spans[i][1], spans[i + 1][0]) for i in range(len(spans) - 1)]
    owned: list[list[tuple[float, float]]] = [[] for _ in gaps]
    for sil in silences:
        if gaps:
            owned[min(range(len(gaps)), key=lambda g: _distance_to_gap(sil, gaps[g]))].append(sil)
    cuts, snapped = [], []
    for i in range(len(spans) - 1):
        t, ok = snap_boundary(gaps[i][0], gaps[i][1], owned[i], slack)
        low = (cuts[-1] if cuts else 0.0) + MIN_LINE_S
        t = min(max(t, low), total - MIN_LINE_S * (len(spans) - 1 - i))
        cuts.append(t)
        snapped.append(ok)
    return cuts, snapped


def shorten_pauses(samples: array.array, sr: int, silences: list[tuple[float, float]], max_pause: float = PAUSE_MAX_S,
                   target: float = PAUSE_TARGET_S, fade: float = FADE_S) -> tuple[array.array, list[tuple[float, float]]]:
    """Cut the middle out of every silence longer than max_pause so that target seconds of it remain.

    Returns (new samples, the removed stretches as (start, end) seconds on the OLD timeline). The two pieces next to a
    removed stretch get a 15 ms fade so the splice cannot click."""
    half = target / 2
    removed: list[tuple[int, int]] = []
    for a, b in silences:
        if b - a > max_pause:
            ka, kb = round((a + half) * sr), round((b - half) * sr)
            if kb > ka and (not removed or ka >= removed[-1][1]):
                removed.append((ka, kb))
    if not removed:
        return array.array("h", samples), []
    n_fade = max(1, round(fade * sr))
    edges = [0]
    for ka, kb in removed:
        edges += [ka, kb]
    edges.append(len(samples))
    pieces = list(zip(edges[0::2], edges[1::2]))  # (0, ka1), (kb1, ka2), ..., (kbN, end)
    out = array.array("h")
    for p, (s, e) in enumerate(pieces):
        out += _faded(samples[s:e], n_fade, fade_in=p > 0, fade_out=p < len(pieces) - 1)
    return out, [(ka / sr, kb / sr) for ka, kb in removed]


def remap_time(t: float, removed: list[tuple[float, float]]) -> float:
    """Where the old time t lies after the removed stretches are gone (a time inside one lands where it was cut)."""
    shift = 0.0
    for a, b in removed:
        if t <= a:
            break
        shift += min(t, b) - a
    return t - shift


def line_spans_from_words(aligned: list[dict], texts: list[str]) -> list[tuple[float, float]]:
    """(first word start, last word end) of every script line from the aligned caption words.

    A caption unit is one or more space-separated script pieces (a lone dash joins its neighbour); it belongs to the line
    that holds its first piece."""
    owner = [i for i, text in enumerate(texts) for _ in text.split()]
    first: dict[int, float] = {}
    last: dict[int, float] = {}
    piece = 0
    for unit in aligned:
        if piece >= len(owner):
            break
        line = owner[piece]
        piece += len(unit["text"].split())
        first.setdefault(line, unit["start"])
        last[line] = unit["end"]
    missing = [i for i in range(len(texts)) if i not in first]
    if missing:
        raise TakeRejected(f"no spoken words were found for line(s) {', '.join(map(str, missing))}")
    return [(first[i], last[i]) for i in range(len(texts))]


# --------------------------------------------------------------------------------------
# The gates (pure)
# --------------------------------------------------------------------------------------


def semitones(f_hz: float, ref_hz: float) -> float:
    return 12 * math.log2(f_hz / ref_hz)


def continuity_gate(f0s: list, loud_db: list, ref_f0: float | None = None, *, max_line_st: float = MAX_LINE_OFFSET_ST,
                    max_sd_st: float = MAX_SD_ST, max_jump_db: float = MAX_JUMP_DB, max_jump_st: float = MAX_JUMP_ST,
                    max_ref_st: float = MAX_REF_ST) -> dict:
    """Is this take steady enough? f0s / loud_db hold one value per line (None = could not be measured).

    Pass only if all of these hold:  every line within max_line_st of the take median; the SD of the line medians
    <= max_sd_st; every neighbour pair within max_jump_st (pitch) and max_jump_db (loudness); the take median within
    max_ref_st of ref_f0 (when given). Returns the numbers and a plain-English reason for every broken rule."""
    reasons: list[str] = []
    missing = [i for i, f in enumerate(f0s) if not f]
    if missing:
        reasons.append(f"the pitch of line(s) {', '.join(map(str, missing))} could not be measured")
    voiced = [f for f in f0s if f]
    result: dict = {"lines": len(f0s), "ref_f0_hz": ref_f0}
    if not voiced:
        return {**result, "ok": False, "reasons": reasons or ["there is no measurable pitch"]}
    med = statistics.median(voiced)
    offsets = [semitones(f, med) if f else None for f in f0s]
    worst = max(abs(o) for o in offsets if o is not None)
    sd = statistics.pstdev([o for o in offsets if o is not None])
    jumps_st = [abs(semitones(b, a)) for a, b in zip(f0s, f0s[1:]) if a and b]
    jumps_db = [abs(b - a) for a, b in zip(loud_db, loud_db[1:]) if a is not None and b is not None]
    result.update(take_median_hz=round(med, 1), line_offsets_st=[None if o is None else round(o, 2) for o in offsets],
                  max_line_offset_st=round(worst, 2), sd_st=round(sd, 2),
                  max_adjacent_jump_st=round(max(jumps_st, default=0.0), 2), max_adjacent_jump_db=round(max(jumps_db, default=0.0), 2),
                  adjacent_jumps_st=[round(j, 2) for j in jumps_st], adjacent_jumps_db=[round(j, 2) for j in jumps_db])
    for i, o in enumerate(offsets):
        if o is not None and abs(o) > max_line_st:
            reasons.append(f"line {i} is {o:+.1f} semitones from the take's median pitch (limit {max_line_st:g})")
    if sd > max_sd_st:
        reasons.append(f"the line pitches spread by {sd:.1f} semitones (SD; limit {max_sd_st:g})")
    for i, (a, b) in enumerate(zip(f0s, f0s[1:])):
        if a and b and abs(semitones(b, a)) > max_jump_st:
            reasons.append(f"pitch jumps {semitones(b, a):+.1f} semitones from line {i} to line {i + 1} (limit {max_jump_st:g})")
    for i, (a, b) in enumerate(zip(loud_db, loud_db[1:])):
        if a is not None and b is not None and abs(b - a) > max_jump_db:
            reasons.append(f"loudness jumps {b - a:+.1f} dB from line {i} to line {i + 1} (limit {max_jump_db:g})")
    if ref_f0:
        off = semitones(med, ref_f0)
        result["ref_offset_st"] = round(off, 2)
        if abs(off) > max_ref_st:
            reasons.append(f"the take's median pitch {med:.0f} Hz is {off:+.1f} semitones from the channel's reference voice "
                           f"({ref_f0:.0f} Hz; limit {max_ref_st:g}): the voice came out in another register")
    return {**result, "ok": not reasons, "reasons": reasons}


def patch_target_f0(neighbour_f0s: list) -> float | None:
    values = [f for f in neighbour_f0s if f]
    return statistics.median(values) if values else None


def patch_accepts(voice_ok: bool, candidate_f0: float | None, neighbour_f0s: list, tolerance_st: float = PATCH_NEIGHBOUR_ST) -> bool:
    """A re-voiced line is taken when it passes the voice check AND its median pitch is within tolerance_st semitones of the
    median of its neighbours (a line with no measurable neighbour only has to pass the voice check)."""
    if not voice_ok or not candidate_f0:
        return False
    target = patch_target_f0(neighbour_f0s)
    return target is None or abs(semitones(candidate_f0, target)) <= tolerance_st


def patch_gain_db(candidate_db: float | None, neighbour_dbs: list, cap: float = PATCH_GAIN_CAP_DB) -> float:
    """Gain that brings a patched line to the average loudness of its neighbours (limited to +-cap dB)."""
    values = [v for v in neighbour_dbs if v is not None]
    if candidate_db is None or not values:
        return 0.0
    return max(-cap, min(cap, sum(values) / len(values) - candidate_db))


# --------------------------------------------------------------------------------------
# The cache (by script lines, voice, model, seed)
# --------------------------------------------------------------------------------------


def _lines_list(lines) -> list[str]:
    return [lines] if isinstance(lines, str) else [str(t) for t in lines]


def script_key(lines, voice: str, model: str, instructions: str = "") -> str:
    """Stable name of a script as it is voiced (every seed shares it). It is made from the LIST of lines: a take is cut at
    the line boundaries, so the same words split in other lines are another script. `instructions` only goes in when the
    engine really listens to them (it does not today)."""
    payload = json.dumps([CACHE_VERSION, _lines_list(lines), voice, model, instructions], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def cache_key(lines, voice: str, model: str, seed: int, instructions: str = "") -> str:
    """Stable name of one take: the script's lines + voice + model + seed."""
    payload = json.dumps([CACHE_VERSION, _lines_list(lines), voice, model, int(seed), instructions], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def cache_dir_for(cache_root: Path, key: str, seed: int) -> Path:
    return Path(cache_root) / f"{key}-s{seed}"


def load_cached_take(cache_root: Path, key: str, seed: int, ref_f0: float | None, texts: list[str] | None = None) -> dict | None:
    """The accepted take stored for this key, or None. The stored numbers are judged again with TODAY's gate rules.

    With `texts` (the current script lines) the stored take must hold exactly these lines, in this split: a take is cut at
    line boundaries, so the same number of lines with other text, or other line count, is a miss."""
    folder = cache_dir_for(cache_root, key, seed)
    try:
        meta = json.loads((folder / "take.json").read_text(encoding="utf-8"))
        if meta.get("cache_version") != CACHE_VERSION or not (folder / "narration.wav").is_file():
            return None
        lines = meta["lines"]
        if not all(line.get("ok") for line in lines):
            return None
        if texts is not None and ([line["text"] for line in lines] != list(texts) or len(meta["bounds"]) != len(texts) + 1):
            return None
        gate = continuity_gate([line["f0_hz"] for line in lines], [line["loudness_db"] for line in lines], ref_f0)
        if not gate["ok"]:
            return None
        return {**meta, "folder": folder, "continuity": gate}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def accepted_pointer(cache_root: Path, skey: str) -> int | None:
    """The seed whose take was accepted last for this script (any seed range), or None."""
    try:
        seed = json.loads((Path(cache_root) / f"{skey}-accepted.json").read_text(encoding="utf-8"))["seed"]
        return seed if isinstance(seed, int) and not isinstance(seed, bool) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store_accepted_pointer(cache_root: Path, skey: str, seed: int) -> None:
    Path(cache_root).mkdir(parents=True, exist_ok=True)
    (Path(cache_root) / f"{skey}-accepted.json").write_text(json.dumps({"seed": int(seed)}), encoding="utf-8")


def rejected_before(cache_root: Path, key: str, seed: int, asr_model: str) -> str | None:
    """The reason this seed was rejected earlier (with the same gate rules and the same transcription engine), or None."""
    try:
        meta = json.loads((cache_dir_for(cache_root, key, seed) / "rejected.json").read_text(encoding="utf-8"))
        if meta.get("gate_version") == GATE_VERSION and meta.get("asr_model") == asr_model:
            return str(meta["reason"])
    except (OSError, ValueError, KeyError):
        pass
    return None


def store_rejection(cache_root: Path, key: str, seed: int, asr_model: str, reason: str) -> None:
    folder = cache_dir_for(cache_root, key, seed)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "rejected.json").write_text(
        json.dumps({"gate_version": GATE_VERSION, "asr_model": asr_model, "reason": reason}, ensure_ascii=False, indent=2), encoding="utf-8")


def store_take(cache_root: Path, key: str, seed: int, narration: Path, meta: dict) -> Path:
    folder = cache_dir_for(cache_root, key, seed)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(narration, folder / "narration.wav")
    (folder / "rejected.json").unlink(missing_ok=True)
    meta = {**meta, "cache_version": CACHE_VERSION, "gate_version": GATE_VERSION,
            "stored_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    (folder / "take.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


# --------------------------------------------------------------------------------------
# VoiceStudio (network) and the pitch subprocess
# --------------------------------------------------------------------------------------

HTTP_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, ValueError)


def build_multipart(fields: dict, filename: str, data: bytes) -> tuple[bytes, str]:
    """multipart/form-data body; a field may hold a list (sent as the same field several times)."""
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        for item in (value if isinstance(value, list) else [value]):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{item}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def pitch_command(mpt_dir: Path = MPT_DIR) -> tuple[list[str], Path | None]:
    """(argv start, cwd) that runs a Python with numpy: MoneyPrinterTurbo's venv, else `uv run python` inside MoneyPrinterTurbo."""
    venv_python = Path(mpt_dir) / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return [str(venv_python)], None
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "python"], Path(mpt_dir)
    raise VoiceTakeError("Pitch measurement needs numpy, which only MoneyPrinterTurbo's virtual environment has "
                         f"(expected {venv_python}, or the `uv` program). Set MoneyPrinterTurbo up first.")


def measure_pitch_file(wav: Path, spans: list[tuple[float, float]] | None = None, mpt_dir: Path = MPT_DIR) -> list[float | None]:
    """Median pitch (Hz) per [start, end] span of a wav (the whole file when spans is None), via voice_pitch.py."""
    argv, cwd = pitch_command(mpt_dir)
    cmd = [*argv, str(PITCH_SCRIPT), str(wav)]
    if spans is not None:
        cmd += ["--spans", json.dumps([[round(a, 4), round(b, 4)] for a, b in spans])]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VoiceTakeError(f"The pitch measurement (studio/voice_pitch.py in MoneyPrinterTurbo's Python) could not run: {exc}") from None
    try:
        return [seg["f0_med"] for seg in json.loads(proc.stdout.strip().splitlines()[-1])["segments"]]
    except (ValueError, IndexError, KeyError):
        raise VoiceTakeError("The pitch measurement (studio/voice_pitch.py in MoneyPrinterTurbo's Python) did not work: "
                             + (proc.stderr or proc.stdout or "no output").strip()[-300:]) from None


class VoiceStudioBackend:
    """Everything the take needs from the outside world: speech, transcription, pitch. Tests replace this class."""

    def __init__(self, url: str, voice: str, asr_model: str, language: str, instructions: str = "",
                 ffmpeg: str = "ffmpeg", mpt_dir: Path = MPT_DIR, *, engine_url: str | None = None, engine_start_hint: str = ""):
        """`url` is VoiceStudio: it ALWAYS does the transcription. The speech comes from VoiceStudio too, unless `engine_url` names
        another engine with the same POST /v1/audio/speech interface (the German Thorsten voice): then only synth() goes there."""
        self.url, self.voice, self.asr_model, self.language = url.rstrip("/"), voice, asr_model, language
        self.instructions, self.ffmpeg, self.mpt_dir = instructions, ffmpeg, mpt_dir
        self.engine_url = engine_url.rstrip("/") if engine_url else None
        self.engine_start_hint = engine_start_hint

    def _request(self, path: str, data: bytes, content_type: str, timeout: float, what: str, *, engine: tuple | None = None) -> bytes:
        """POST to VoiceStudio, or to `engine` = (name for messages, base url, what to try when it is not running)."""
        name, base, advice = engine or ("VoiceStudio", self.url, "Is VoiceStudio still running? Start or restart it and run this again.")
        last: Exception | None = None
        for _attempt in range(2):
            req = urllib.request.Request(base + path, data=data, headers={"Content-Type": content_type})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                raise VoiceTakeError(f"{name} refused {what} (HTTP {exc.code}): {detail}") from None
            except HTTP_ERRORS as exc:
                last = exc
                time.sleep(2)
        raise VoiceTakeError(f"{name} could not do {what}: {type(last).__name__}: {last}. {advice}")

    def synth(self, text: str, seed: int, instructions: str | None = None) -> bytes:
        """wav bytes of `text` in one request. instructions=None uses the configured text, "" sends none."""
        body = {"input": text, "voice": self.voice, "response_format": "wav", "seed": int(seed)}
        used = self.instructions if instructions is None else instructions
        if used:
            body["instructions"] = used
        payload = json.dumps(body).encode("utf-8")
        if self.engine_url:
            name = f"The voice engine at {self.engine_url}"
            advice = f"Is it still running? Start it: {self.engine_start_hint or 'start the engine'}, then run this again."
            audio = self._request("/v1/audio/speech", payload, "application/json", 1800, "to voice the text",
                                  engine=(name, self.engine_url, advice))
        else:
            audio = self._request("/v1/audio/speech", payload, "application/json", 1800, "to voice the text")
            name = "VoiceStudio"
        if len(audio) < 100:
            raise VoiceTakeError(f"{name} sent back no audio ({audio[:200]!r}).")
        return audio

    def to_standard_wav(self, path: Path) -> None:
        """Make sure a wav file is 24 kHz, mono, 16-bit (the engine says so, but a convert costs nothing if it ever changes)."""
        with wave.open(str(path), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SAMPLE_RATE, 1, 2):
                return
        tmp = path.with_suffix(".conv.wav")
        proc = subprocess.run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ar", str(SAMPLE_RATE),
                               "-ac", "1", "-c:a", "pcm_s16le", str(tmp)], capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise VoiceTakeError(f"ffmpeg could not convert {path.name}: {proc.stderr.strip()[:300]}")
        tmp.replace(path)

    def _transcribe(self, wav: Path, fields: dict) -> dict:
        body, ctype = build_multipart({"model": self.asr_model, "language": self.language, **fields}, wav.name, wav.read_bytes())
        raw = self._request("/v1/audio/transcriptions", body, ctype, 600, f"to transcribe {wav.name}")
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise VoiceTakeError(f"VoiceStudio answered the transcription of {wav.name} with something that is not JSON.") from None

    def transcribe_text(self, wav: Path) -> str:
        return str(self._transcribe(wav, {"response_format": "json"}).get("text", "")).strip()

    def transcribe_words(self, wav: Path) -> list[dict]:
        """[{"start", "end", "text"}] one per heard word (VoiceStudio verbose_json with word timestamps)."""
        data = self._transcribe(wav, {"response_format": "verbose_json", "timestamp_granularities[]": ["word", "segment"]})
        words = data.get("words")
        if not words:
            raise VoiceTakeError("VoiceStudio's transcription gave no word timestamps (the active transcription engine must support "
                                 "response_format=verbose_json with word timing, like faster-whisper). Select such an engine and run again.")
        return [{"start": float(w["start"]), "end": float(w["end"]), "text": str(w.get("word", w.get("text", ""))).strip()} for w in words]

    def measure_pitch(self, wav: Path, spans: list[tuple[float, float]]) -> list[float | None]:
        return measure_pitch_file(wav, spans, self.mpt_dir)


# --------------------------------------------------------------------------------------
# One-time probe: does this engine listen to the "instructions" text?
# --------------------------------------------------------------------------------------


def probe_key(voice: str, model: str) -> str:
    return f"{voice}|{model}"


def read_probe_file(cache_file: Path) -> dict[str, dict]:
    """The remembered probe answers, one entry per "voice|model" (the first file format held a single voice and is converted)."""
    try:
        known = json.loads(Path(cache_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(known, dict):
        return {}
    if "voice" in known and "model" in known:
        known = {probe_key(known["voice"], known["model"]): known}
    return {k: v for k, v in known.items() if isinstance(v, dict)}


def probe_instructions(backend, voice: str, model: str, cache_file: Path, instructions: str, log=print) -> dict:
    """voices.json carries delivery directions ("instructions"), but this engine ignores them (measured 2026-10-14: same seed +
    other instructions = byte-identical audio). Check once per voice/model and remember every answer in cache_file, so
    switching between the English and the German voice does not run the probe (3 voice requests) again."""
    entries = read_probe_file(cache_file)
    known = entries.get(probe_key(voice, model))
    if known:
        return known
    a = hashlib.sha256(backend.synth(PROBE_TEXT, 1, instructions)).hexdigest()
    again = hashlib.sha256(backend.synth(PROBE_TEXT, 1, instructions)).hexdigest()
    other = hashlib.sha256(backend.synth(PROBE_TEXT, 1, PROBE_OTHER_INSTRUCTIONS)).hexdigest()
    result: dict = {"voice": voice, "model": model, "checked_at": datetime.date.today().isoformat()}
    if a != again:
        result.update(instructions_ignored=None, note="the engine gives different audio for the same seed, so the probe cannot tell")
        log("  voice probe: the engine is not repeatable for one seed; cannot tell whether it listens to the instructions text in voices.json")
    elif a == other:
        result.update(instructions_ignored=True)
        log("  voice probe: this engine IGNORES the instructions text in voices.json (same seed + other instructions = identical audio); "
            "pitch and delivery come from the seed")
    else:
        result.update(instructions_ignored=False)
        log("  voice probe: this engine DOES change the audio with the instructions text in voices.json")
    entries[probe_key(voice, model)] = result
    try:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_file).write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


# --------------------------------------------------------------------------------------
# Building and checking one take
# --------------------------------------------------------------------------------------


def _concat(segments: list[array.array]) -> array.array:
    out = array.array("h")
    for seg in segments:
        out += seg
    return out


def _spans(segments: list[array.array], sr: int) -> list[tuple[float, float]]:
    spans, cursor = [], 0
    for seg in segments:
        spans.append((cursor / sr, (cursor + len(seg)) / sr))
        cursor += len(seg)
    return spans


def _save_audio(backend, data: bytes, path: Path) -> tuple[array.array, int]:
    path.write_bytes(data)
    if hasattr(backend, "to_standard_wav"):
        backend.to_standard_wav(path)
    return read_wav(path)


def build_segments(texts: list[str], seed: int, backend, folder: Path, log) -> dict:
    """Steps 1-3: voice the whole script, find the line boundaries, shorten long pauses, cut into one segment per line."""
    folder.mkdir(parents=True, exist_ok=True)
    full = " ".join(texts)
    started = time.time()
    raw_path = folder / "take-raw.wav"
    samples, sr = _save_audio(backend, backend.synth(full, seed), raw_path)
    total = len(samples) / sr
    log(f"  take seed {seed}: the whole script ({len(full)} characters) voiced in one request: {total:.1f} s of audio, {time.time() - started:.0f} s to make")
    cues = backend.transcribe_words(raw_path)
    try:
        aligned = captionlib.align_words(cues, texts, end_limit=total)
    except captionlib.CaptionError as exc:
        raise TakeRejected(f"the words of the take could not be matched to the script: {exc}") from None
    spans = line_spans_from_words(aligned, texts)
    fr = Framing(sr)
    silences = find_silences(frame_db(samples, fr), fr)
    cuts, snapped = plan_cuts(spans, silences, total)
    paced, removed = shorten_pauses(samples, sr, silences)
    bounds = [0, *(round(remap_time(c, removed) * sr) for c in cuts), len(paced)]
    if any(b <= a for a, b in zip(bounds, bounds[1:])):
        raise TakeRejected("two line boundaries ended up on the same spot after the pacing step")
    saved = sum(b - a for a, b in removed)
    log(f"  take seed {seed}: {sum(snapped)}/{len(snapped)} line boundaries sit in a real silence; "
        f"{len(removed)} long pause(s) shortened to {PAUSE_TARGET_S:g} s (saved {saved:.1f} s)")
    return {"segments": [paced[a:b] for a, b in zip(bounds, bounds[1:])], "sr": sr, "raw_seconds": round(total, 2), "snapped": snapped,
            "pauses_shortened": len(removed), "pause_seconds_saved": round(saved, 2)}


def grade_segments(texts: list[str], segments: list[array.array], sr: int, backend, grade, folder: Path) -> dict[int, dict]:
    """The per-line voice check: each cut is transcribed on its own and graded (grade = make_video.grade_line)."""
    out = {}
    for i, text in enumerate(texts):
        path = folder / f"line{i:02d}.wav"
        write_wav(path, segments[i], sr)
        heard = backend.transcribe_text(path)
        out[i] = {"index": i, "text": text, "heard": heard, **grade(text, heard)}
    return out


def measure_segments(segments: list[array.array], sr: int, backend, folder: Path) -> tuple[list, list]:
    """Join the segments and measure every line: (median pitch per line in Hz, loudness per line in dB)."""
    narration = _concat(segments)
    path = folder / "narration-take.wav"
    write_wav(path, narration, sr)
    spans = _spans(segments, sr)
    f0s = backend.measure_pitch(path, spans)
    fr = Framing(sr)
    db = frame_db(narration, fr)
    return f0s, [active_loudness(db, fr, a, b) for a, b in spans]


def line_pads(segment: array.array, sr: int) -> tuple[float, float]:
    """Silence before and after the sound of a segment (what a re-voiced line has to keep around it)."""
    fr = Framing(sr)
    extent = speech_extent(frame_db(segment, fr), fr, 0.0, len(segment) / sr)
    if extent is None:
        return PAUSE_TARGET_S / 2, PAUSE_TARGET_S / 2
    return extent[0], len(segment) / sr - extent[1]


def try_patch(i: int, text: str, segments: list[array.array], sr: int, f0s: list, loud: list, backend, grade,
              folder: Path, patch_cache: dict, log) -> dict | None:
    """Re-voice line i alone with seeds 1..PATCH_SEEDS; the first candidate that passes the voice check and sits within
    PATCH_NEIGHBOUR_ST of its neighbours' pitch is loudness-matched and spliced in (the old silence around the line is kept)."""
    near = [j for j in (i - 1, i + 1) if 0 <= j < len(segments)]
    near_f0, near_db = [f0s[j] for j in near], [loud[j] for j in near]
    fr = Framing(sr)
    for seed in range(1, PATCH_SEEDS + 1):
        if (text, seed) not in patch_cache:  # the same line with the same seed sounds the same in every take: ask only once
            path = folder / f"patch{i:02d}-s{seed}.wav"
            samples, _sr = _save_audio(backend, backend.synth(text, seed), path)
            heard = backend.transcribe_text(path)
            verdict = grade(text, heard)
            f0 = backend.measure_pitch(path, [(0.0, len(samples) / sr)])[0] if verdict["ok"] else None
            patch_cache[(text, seed)] = {"samples": samples, "verdict": verdict, "heard": heard, "f0": f0}
        cand = patch_cache[(text, seed)]
        if not patch_accepts(cand["verdict"]["ok"], cand["f0"], near_f0):
            why = "voice check failed" if not cand["verdict"]["ok"] else f"pitch {cand['f0']:.0f} Hz is off its neighbours"
            log(f"    patch line {i}: seed {seed} not usable ({why})")
            continue
        db = frame_db(cand["samples"], fr)
        length = len(cand["samples"]) / sr
        extent = speech_extent(db, fr, 0.0, length)
        if extent is None:
            continue
        speech = cand["samples"][round(max(0.0, extent[0] - 0.02) * sr):round(min(length, extent[1] + 0.02) * sr)]
        gain = patch_gain_db(active_loudness(db, fr, 0.0, length), near_db)
        speech = _faded(apply_gain(speech, gain), max(1, round(FADE_S * sr)), True, True)
        lead, tail = line_pads(segments[i], sr)
        segments[i] = silence(lead, sr) + speech + silence(tail, sr)
        log(f"    patch line {i}: seed {seed} accepted (pitch {cand['f0']:.0f} Hz, gain {gain:+.1f} dB)")
        return {"line": i, "seed": seed, "f0_hz": cand["f0"], "gain_db": round(gain, 2), "grade": cand["verdict"], "heard": cand["heard"]}
    return None


def evaluate_take(texts: list[str], seed: int, backend, grade, ref_f0: float | None, folder: Path, patch_cache: dict, log,
                  patch: bool = True) -> dict:
    """Build the take for one seed and run every gate. Returns the accepted take, or raises TakeRejected(reason).

    patch=False (a deterministic engine): a line that fails the voice check is NOT re-voiced with other seeds, because the
    engine would say it the same way again; the take is rejected with the failing lines attached (TakeRejected.lines)."""
    built = build_segments(texts, seed, backend, folder, log)
    segments, sr = built["segments"], built["sr"]
    graded = grade_segments(texts, segments, sr, backend, grade, folder)
    patches: list[dict] = []
    bad = [i for i, g in graded.items() if not g["ok"]]
    if bad and not patch:
        raise TakeRejected(f"{len(bad)} line(s) fail the voice check: line(s) {', '.join(map(str, bad))}",
                           lines=[{k: graded[i].get(k) for k in ("index", "text", "heard", "wer", "cer", "threshold", "cer_limit")} for i in bad])
    if len(bad) > MAX_PATCH_LINES:
        raise TakeRejected(f"{len(bad)} lines fail the voice check (more than {MAX_PATCH_LINES}, too many to patch): lines {', '.join(map(str, bad))}")
    f0s, loud = measure_segments(segments, sr, backend, folder)
    if bad:
        log(f"  take seed {seed}: line(s) {', '.join(map(str, bad))} fail the voice check; patching them one by one")
    for i in bad:
        done = try_patch(i, texts[i], segments, sr, f0s, loud, backend, grade, folder, patch_cache, log)
        if done is None:
            raise TakeRejected(f"line {i} fails the voice check and no patch worked in {PATCH_SEEDS} seeds "
                               f"(script: {texts[i][:70]!r}; heard: {graded[i]['heard'][:70]!r})")
        patches.append(done)
        graded[i] = {**graded[i], **done["grade"], "heard": done["heard"], "patched_seed": done["seed"]}
        f0s, loud = measure_segments(segments, sr, backend, folder)  # the next patch sees the repaired neighbour
    lines = [{**graded[i], "f0_hz": f0s[i], "loudness_db": None if loud[i] is None else round(loud[i], 2),
              "patched_seed": graded[i].get("patched_seed")} for i in range(len(texts))]
    gate = continuity_gate(f0s, loud, ref_f0)
    log(f"  take seed {seed}: median pitch per line (Hz): {' '.join('-' if f is None else f'{f:.0f}' for f in f0s)}")
    if not gate["ok"]:
        raise TakeRejected("; ".join(gate["reasons"]))
    return {"seed": seed, "segments": segments, "sr": sr, "lines": lines, "continuity": gate, "patches": patches,
            "raw_seconds": built["raw_seconds"], "snapped": built["snapped"], "pauses_shortened": built["pauses_shortened"],
            "pause_seconds_saved": built["pause_seconds_saved"]}


def line_timings(texts: list[str], narration: array.array, sr: int, bounds: list[int]) -> list[dict]:
    """[{index, start, end, text}] where start/end are the first and last sound of each line on the narration timeline."""
    fr = Framing(sr)
    db = frame_db(narration, fr)
    out = []
    for i, text in enumerate(texts):
        extent = speech_extent(db, fr, bounds[i] / sr, bounds[i + 1] / sr)
        if extent is None:
            raise VoiceTakeError(f"Line {i} came out silent in the narration. Run again (or reword the line).")
        out.append({"index": i, "start": round(extent[0], 3), "end": round(extent[1], 3), "text": text})
    return out


def no_steady_take_message(attempts: list[dict], first_seed: int) -> str:
    why = "\n".join(f"    seed {a['seed']}: {a['reason']}" for a in attempts)
    last = attempts[-1]["seed"] if attempts else first_seed
    return (f"No take of the whole script was both accurate and steady in {len(attempts)} tries (seeds {first_seed}-{last}). "
            f"Why each take was rejected:\n{why}\n"
            f"  The voice engine decides pitch and loudness itself. If every take fails on the same line, reword that line (simpler words, "
            f"numbers and symbols as plain words the transcription also writes that way). Otherwise try new seeds with "
            f"--voice-seed {last + 1} (earlier seeds are remembered and skipped; a take accepted that way is remembered for this script, "
            f"so later runs without the flag reuse it).")


def deterministic_failure_message(attempt: dict, lines: list[dict]) -> str:
    """Plain words for a take that failed with an engine that says the same text the same way every time."""
    head = ("This voice engine gives identical audio for identical text, so there is nothing to re-roll: the script was voiced ONCE and "
            "that take was not accepted. No other seeds were tried and no line was re-voiced (they would sound exactly the same).\n")
    if lines:
        detail = "\n".join(
            f"    line {g['index']}: {g['text']}\n      heard: {g['heard']}\n"
            f"      word errors {g['wer']:.2f} (limit {g['threshold']:.2f}), letter errors {g['cer']:.2f} (limit {g.get('cer_limit') or 0:.2f})"
            for g in lines)
        return (f"{head}  {len(lines)} line(s) were not understood by the transcription. Reword them (simpler words, numbers written as "
                f"words, fewer foreign or invented words) and run again:\n{detail}")
    return f"{head}  Why: {attempt['reason']}\n  Reword the line(s) that cause it (shorter sentences, plainer words) and run again."


def produce_narration(texts: list[str], *, backend, grade, voice: str, model: str, asr_model: str, ref_f0: float | None,
                      work_dir: Path, cache_root: Path, start_seed: int = 1, instructions_in_key: str = "",
                      use_cache: bool = True, max_takes: int = MAX_TAKES, deterministic: bool = False, log=print) -> dict:
    """The whole thing: the accepted one-take narration of `texts` (see the module docstring).

    Writes work_dir/narration.wav and returns a dict with narration (that path), duration, timings ([{index, start, end,
    text}] as make_video's timings.json wants them), lines (per-line check, pitch, loudness), continuity (the gate
    numbers), seed, patches, attempts, cache ({hit, key, folder}) ...
    deterministic=True (an engine that gives identical audio for identical text, like the German Thorsten voice): exactly ONE
    take, no seed re-rolls, no line patching (a seed changes nothing), and a rejection is not remembered (the engine may be
    fixed or changed later); a failing line is reported with what was heard, so the line can be reworded.
    Raises VoiceTakeError when the voice engine fails or no take passes."""
    clean = [t.strip() for t in texts]
    full = " ".join(clean)
    if len(full) >= INPUT_MAX_CHARS:
        raise VoiceTakeError(f"The whole script is {len(full)} characters long, but VoiceStudio takes fewer than {INPUT_MAX_CHARS} in one request. "
                             "Shorten the script (a Short needs about 1100 characters).")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    if deterministic:
        max_takes = 1  # the same text sounds the same with every seed: a second take would be a copy of the first
    remember_rejections = use_cache and not deterministic
    seeds = [start_seed + k for k in range(max_takes)]
    keys = {s: cache_key(clean, voice, model, s, instructions_in_key) for s in seeds}  # made from the LINES, not the joined text
    skey = script_key(clean, voice, model, instructions_in_key)
    final_path = work_dir / "narration.wav"

    def finish(take: dict, hit: bool, attempts: list[dict], key: str, folder: Path) -> dict:
        narration, sr = read_wav(final_path)
        return {"narration": final_path, "duration": len(narration) / sr, "sr": sr,
                "timings": line_timings(clean, narration, sr, take["bounds"]), "bounds": take["bounds"], "lines": take["lines"],
                "continuity": take["continuity"], "seed": take["seed"], "patches": take["patches"], "attempts": attempts,
                "raw_seconds": take["raw_seconds"], "snapped": take["snapped"], "pauses_shortened": take["pauses_shortened"],
                "pause_seconds_saved": take["pause_seconds_saved"], "cache": {"hit": hit, "key": key, "folder": str(folder)}}

    if use_cache:
        for s in seeds:
            hit = load_cached_take(cache_root, keys[s], s, ref_f0, clean)
            if hit:
                shutil.copyfile(hit["folder"] / "narration.wav", final_path)
                log(f"  voice cache: the accepted take (seed {s}) of this exact script is reused, no voicing needed")
                earlier = hit.get("attempts") or [{"seed": s, "accepted": True, "reason": "steady"}]  # the tries of the run that made it
                return finish(hit, True, earlier, keys[s], hit["folder"])

    attempts: list[dict] = []
    patch_cache: dict = {}
    for s in seeds:
        if remember_rejections:
            earlier = rejected_before(cache_root, keys[s], s, asr_model)
            if earlier:
                log(f"  take seed {s}: skipped, it was rejected in an earlier run ({earlier[:120]})")
                attempts.append({"seed": s, "accepted": False, "reason": f"{earlier} (remembered from an earlier run)"})
                continue
        try:
            take = evaluate_take(clean, s, backend, grade, ref_f0, work_dir / f"take-s{s}", patch_cache, log, patch=not deterministic)
        except TakeRejected as why:
            log(f"  take seed {s}: REJECTED: {why}")
            attempts.append({"seed": s, "accepted": False, "reason": str(why)})
            if remember_rejections:
                store_rejection(cache_root, keys[s], s, asr_model, str(why))
            if deterministic:
                failure = VoiceTakeError(deterministic_failure_message(attempts[-1], why.lines))
                failure.attempts = attempts
                raise failure
            continue
        write_wav(final_path, _concat(take["segments"]), take["sr"])
        take["bounds"] = [0]
        for seg in take["segments"]:
            take["bounds"].append(take["bounds"][-1] + len(seg))
        attempts.append({"seed": s, "accepted": True, "reason": "steady"})
        gate = take["continuity"]
        log(f"  take seed {s}: ACCEPTED (median pitch {gate['take_median_hz']} Hz, spread {gate['sd_st']} st, "
            f"largest neighbour jump {gate['max_adjacent_jump_st']} st / {gate['max_adjacent_jump_db']} dB)")
        meta = {"seed": s, "voice": voice, "model": model, "sr": take["sr"], "bounds": take["bounds"], "lines": take["lines"],
                "patches": take["patches"], "raw_seconds": take["raw_seconds"], "snapped": take["snapped"],
                "pauses_shortened": take["pauses_shortened"], "pause_seconds_saved": take["pause_seconds_saved"], "continuity": gate,
                "attempts": attempts}
        folder = store_take(cache_root, keys[s], s, final_path, meta) if use_cache else work_dir
        if use_cache:
            store_accepted_pointer(cache_root, skey, s)
        return finish(take, False, attempts, keys[s], folder)
    if use_cache:
        # Every seed of this range was rejected (now or earlier). This exact script may still have an accepted take from
        # another seed range, e.g. one found with --voice-seed 7 after seeds 1-6 failed: use it instead of failing.
        pointed = accepted_pointer(cache_root, skey)
        if pointed is not None and pointed not in seeds:
            hit = load_cached_take(cache_root, cache_key(clean, voice, model, pointed, instructions_in_key), pointed, ref_f0, clean)
            if hit:
                shutil.copyfile(hit["folder"] / "narration.wav", final_path)
                log(f"  voice cache: seeds {seeds[0]}-{seeds[-1]} gave no steady take, but this exact script has an accepted take "
                    f"from an earlier run (seed {pointed}): reused, no voicing needed")
                earlier = hit.get("attempts") or [{"seed": pointed, "accepted": True, "reason": "steady"}]
                return finish(hit, True, attempts + earlier, cache_key(clean, voice, model, pointed, instructions_in_key), hit["folder"])
    failure = VoiceTakeError(no_steady_take_message(attempts, start_seed))
    failure.attempts = attempts  # make_video writes them into the (partial) report
    raise failure


def format_line_table(lines: list[dict]) -> str:
    """Per-line pitch / loudness table for the console."""
    rows = ["  line   pitch Hz   loudness dB   WER    note"]
    for g in lines:
        f0, db = g.get("f0_hz"), g.get("loudness_db")
        note = f"patched with seed {g['patched_seed']}" if g.get("patched_seed") else ""
        rows.append(f"  {g['index']:>4}   {'-' if f0 is None else f'{f0:>8.1f}'}   {'-' if db is None else f'{db:>11.1f}'}   {g.get('wer', 0):.2f}   {note}")
    return "\n".join(rows)


# --------------------------------------------------------------------------------------
# Command line: measure the reference voices
# --------------------------------------------------------------------------------------


def store_reference_pitches(voices_file: Path = VOICES_FILE, tests_dir: Path = VOICE_TESTS_DIR, log=print) -> None:
    """For every language in voices.json: measure studio/voice-tests/<lang>-<voice>.wav (the sample the user listened to) and
    store ref_f0_hz (+ ref_sample) next to the voice."""
    voices = json.loads(voices_file.read_text(encoding="utf-8"))
    for lang, cfg in voices.items():
        if lang.startswith("_") or not isinstance(cfg, dict):
            continue
        sample = tests_dir / f"{lang}-{cfg['voice']}.wav"
        if not sample.is_file():
            log(f"  {lang}: sample {sample} not found, skipped")
            continue
        f0 = measure_pitch_file(sample)[0]
        cfg["ref_f0_hz"] = round(f0, 1)
        cfg["ref_sample"] = f"studio/voice-tests/{sample.name}"
        log(f"  {lang}: {sample.name} median pitch {f0:.1f} Hz")
    voices_file.write_text(json.dumps(voices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["refs"]:
        store_reference_pitches()
        return 0
    print("usage: python3 studio/voice_take.py refs   (measure the voice-test samples and store ref_f0_hz in studio/voices.json)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
