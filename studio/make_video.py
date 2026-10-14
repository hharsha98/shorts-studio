#!/usr/bin/env python3
"""make_video.py - turn content/<id>/script.json into a review-ready YouTube Short.

Usage (from /Users/harsha/shorts-studio):
    python3 studio/make_video.py content/<id>/script.json [--local-materials DIR]
        [--min-seconds 61] [--max-seconds 75] [--keep-work] [--no-visuals]
        [--stage voice|all] [--footage auto|own|mpt]

What it does, in order (every gate fails LOUDLY: non-zero exit + a plain-English message):
     1. validate script.json against the contract
     2. preflight (VoiceStudio health + the right TTS engine, tools, MoneyPrinterTurbo config)
     3. voice every line with VoiceStudio, transcribe it back, check the word error rate
     4. join the lines (0.25 s gaps) into work/<id>/narration.wav + work/<id>/timings.json
     5. length gate (default 61-75 s)           <- --stage voice stops here
     6. captions and video:
        a. MoneyPrinterTurbo (MPT) runs once with --stop-at subtitle: Whisper hears the narration and writes one cue
           per word (the TIMING; its spelling is sometimes wrong). Word error rate gate: a voice-quality signal.
        b. studio/captions.py aligns those cues with the SCRIPT: one caption per script word, spelled exactly as in
           the script, timed from Whisper. Gate "captions match script".
        c. stock footage: studio/footage.py picks one Pixabay clip per script line (lines[].broll), cuts them to
           1080x1920 and joins them into work/<id>/broll.mp4 (--footage own, the default when a Pixabay key is set;
           --footage mpt lets MoneyPrinterTurbo search by itself)
        d. MPT builds the video from our B-roll and the narration WITHOUT captions (--no-subtitle-enabled)
     7. Remotion draws the captions (ONE word at a time, white with black outline, pop animation, top edge at y=1300:
        below the diagram panels, above the YouTube Shorts title/channel overlay) and, unless --no-visuals, the diagram
        panels; studio/visuals.py puts both on the video in ONE ffmpeg pass
     8. final checks (duration, 1080x1920, audio, caption timing) + contact sheet
     9. credits for the stock footage that was really used (own footage: exactly the clips in the video)
    10. review/<date>-<language>-<slug>/ : final.mp4, subtitles.srt (the corrected captions as readable phrases),
        captions-words.json (the per-word captions), sheet.png, caption.txt, report.json
    11. cleanup of the big temporary files (skipped with --keep-work); report.json records what was deleted

Python standard library only. The pure helper functions (validation, WER, SRT sanity,
length gate, credits, caption...) are unit-tested in studio/tests/test_make_video.py.
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import http.client
import importlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO_DIR = ROOT / "studio"
if str(STUDIO_DIR) not in sys.path:  # `import footage` must work however this file is started or imported
    sys.path.insert(0, str(STUDIO_DIR))
import footage  # noqa: E402  (studio/footage.py: our own stock-footage choice)
import captions as captionlib  # noqa: E402  (studio/captions.py: the script's words with Whisper's timing)
from captions import normalize_words  # noqa: E402,F401  (one normalisation for the WER and the caption alignment)
MPT_DIR = ROOT / "MoneyPrinterTurbo"
VOICES_FILE = STUDIO_DIR / "voices.json"
WORK_ROOT = ROOT / "work"
REVIEW_ROOT = ROOT / "review"

VOICESTUDIO_URL = os.environ.get("VOICESTUDIO_URL", "http://127.0.0.1:3900").rstrip("/")
REQUIRED_TTS_ENGINE = "mlx-audio"
REQUIRED_TTS_MODEL = "Qwen3-TTS-12Hz-1.7B-CustomVoice"

SAMPLE_RATE = 24000
GAP_SECONDS = 0.25
MAX_ATTEMPTS = 3
WER_LIMIT_LONG = 0.15  # lines with >= 5 words
WER_LIMIT_SHORT = 0.34  # shorter lines (one wrong word is a big share)
CER_LIMIT = 0.06  # letter error rate (spaces/dashes ignored); a line passes if its WER OR its CER is inside the limit
MPT_TIMEOUT_SECONDS = 45 * 60

# Caption style: ONE word at a time, big and bold, popping in (MoneyPrinterTurbo options).
SUBTITLE_FONT = "BeVietnamPro-Bold.ttf"
SUBTITLE_DISPLAY_MODE = "word_by_word"
SUBTITLE_ANIMATION = "pop_spring"
SUBTITLE_POSITION = "custom"  # "bottom" would put the captions under the YouTube Shorts title/channel overlay on phones
CAPTION_BOX_TOP_Y = 1300  # where the TOP edge of the caption box goes (the white letters start ~65 px lower)
SUBTITLE_TEXT_COLOR = "#FFFFFF"
SUBTITLE_STROKE_COLOR = "#000000"
CAPTION_MAX_WORD_PX = 860  # widest word incl. its punctuation; MPT wraps above 972 px and the pop overshoots by ~12%
CAPTION_FONT_MIN = 64
CAPTION_FONT_MAX = 120
CAPTION_TOP_LIMIT_Y = 1250  # diagram panels cover y 160-1240, captions must stay below this
FRAME_HEIGHT = 1920
SRT_WER_LIMIT = 0.10  # whole-script word error rate of the subtitle file against the script
LONG_SENTENCE_CHARS = 140

DISCLOSURE = {
    "en": "AI voice. Script written with AI assistance and fact-checked.",
    "de": "KI-Stimme. Skript mit KI-Unterstützung geschrieben und faktengeprüft.",
}
SOURCES_LABEL = {"en": "Sources:", "de": "Quellen:"}
LANGUAGES = ("en", "de")
KEPT_WORK_FILES = ("timings.json", "mpt.log", "mpt-subtitles.log")  # step_cleanup keeps these in work/<id>

FOOTAGE_MODES = ("auto", "own", "mpt")
BROLL_MIN_CHARS, BROLL_MAX_CHARS, BROLL_MAX_WORDS = 2, 40, 4
OWN_FOOTAGE_EXTRA_SECONDS = 5  # --video-clip-duration = narration + this: MPT must take our whole B-roll file as ONE clip
# Mean grey difference (0-255) between MPT's picture and our B-roll at the same second. Measured: the same shot
# scores 4-13 (fine-textured clips after two encodes reach ~13), a shuffled/looped shot 37+, an unrelated shot ~126.
ORDER_CHECK_LIMIT = 25.0

LOCAL_MATERIAL_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".bmp"}

PROVIDER_LABELS = {
    "pexels": ("Pexels", "pexels.com"),
    "pixabay": ("Pixabay", "pixabay.com"),
    "coverr": ("Coverr", "coverr.co"),
}


class GateError(Exception):
    """A gate failed. The message is shown to the user: say what is wrong and what to do."""


# --------------------------------------------------------------------------------------
# 1. Validation (pure)
# --------------------------------------------------------------------------------------

# Used with .fullmatch(): "$" would also accept a trailing newline, fullmatch does not.
ID_RE = re.compile(r"_?[a-z0-9][a-z0-9-]*")
TERM_RE = re.compile(r"(?=.*[A-Za-z])[A-Za-z -]+")
URL_RE = re.compile(r"https://\S+")
URL_MESSAGE = "must start with https:// and contain no spaces"
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")


def _is_str(value) -> bool:
    return isinstance(value, str)


def _check_text(value, where: str, errors: list[str], max_len: int | None = None) -> None:
    if not _is_str(value) or not value.strip():
        errors.append(f"{where} must be a non-empty text")
    elif max_len is not None and len(value) > max_len:
        errors.append(f"{where} is {len(value)} characters long; the limit is {max_len}")


def validate_visual(visual, where: str, errors: list[str]) -> None:
    """Check one VISUAL object (flow / stat / compare). Appends plain-English problems."""
    if not isinstance(visual, dict):
        errors.append(f"{where} must be null or an object with a \"type\"")
        return
    kind = visual.get("type")
    if kind == "flow":
        _check_text(visual.get("title"), f"{where}.title", errors, 32)
        steps = visual.get("steps")
        if not isinstance(steps, list) or not 2 <= len(steps) <= 5:
            errors.append(f"{where}.steps must be a list of 2 to 5 short texts")
        else:
            for k, step in enumerate(steps):
                _check_text(step, f"{where}.steps[{k}]", errors, 22)
    elif kind == "stat":
        _check_text(visual.get("value"), f"{where}.value", errors, 10)
        _check_text(visual.get("label"), f"{where}.label", errors, 40)
    elif kind == "compare":
        _check_text(visual.get("title"), f"{where}.title", errors, 32)
        for side in ("left", "right"):
            part = visual.get(side)
            if not isinstance(part, dict):
                errors.append(f"{where}.{side} must be an object with \"heading\" and \"text\"")
                continue
            _check_text(part.get("heading"), f"{where}.{side}.heading", errors, 12)
            _check_text(part.get("text"), f"{where}.{side}.text", errors, 48)
    else:
        errors.append(f"{where}.type must be \"flow\", \"stat\" or \"compare\" (got {kind!r})")


def validate_broll(value, where: str, errors: list[str], warnings: list[str]) -> None:
    """The optional stock-footage search phrase of a line: English, 2-40 characters, letters/spaces/hyphens only."""
    if not _is_str(value) or not BROLL_MIN_CHARS <= len(value) <= BROLL_MAX_CHARS or not TERM_RE.fullmatch(value):
        errors.append(
            f"{where} must be a short English search phrase of {BROLL_MIN_CHARS} to {BROLL_MAX_CHARS} characters "
            f"using only letters, spaces and hyphens, for example \"refrigerator interior\" (got {value!r})"
        )
    elif len(value.split()) > BROLL_MAX_WORDS:
        warnings.append(f"{where} has {len(value.split())} words; phrases of 1 to {BROLL_MAX_WORDS} words find far more footage")


def validate_script(data) -> tuple[list[str], list[str]]:
    """Validate a parsed script.json. Returns (errors, warnings); errors must be empty to go on."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["script.json must contain one JSON object"], warnings

    sid = data.get("id")
    if not _is_str(sid) or not ID_RE.fullmatch(sid):
        errors.append("id must use only lowercase letters, digits and \"-\" (a leading \"_\" is allowed for tests)")

    language = data.get("language")
    if language not in LANGUAGES:
        errors.append(f"language must be \"en\" or \"de\" (got {language!r})")

    _check_text(data.get("series"), "series", errors)
    _check_text(data.get("title"), "title", errors, 90)

    caption = data.get("caption")
    _check_text(caption, "caption", errors)
    if _is_str(caption) and len(re.findall(r"[.!?…]+(?:\s|$)", caption.strip())) > 3:
        warnings.append("caption looks longer than 3 sentences")

    tags = data.get("hashtags")
    if not isinstance(tags, list) or not 3 <= len(tags) <= 8:
        errors.append("hashtags must be a list of 3 to 8 items")
    else:
        for k, tag in enumerate(tags):
            if not _is_str(tag) or not re.fullmatch(r"#\S+", tag):
                errors.append(f"hashtags[{k}] must start with # and contain no spaces")

    terms = data.get("video_terms")
    if not isinstance(terms, list) or not 4 <= len(terms) <= 10:
        errors.append("video_terms must be a list of 4 to 10 English search terms")
    else:
        for k, term in enumerate(terms):
            if not _is_str(term) or not TERM_RE.fullmatch(term):
                errors.append(f"video_terms[{k}] must use only English letters, spaces and hyphens (got {term!r})")

    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        errors.append("lines must be a non-empty list")
    else:
        for k, line in enumerate(lines):
            where = f"lines[{k}]"
            if not isinstance(line, dict):
                errors.append(f"{where} must be an object with \"text\" and \"visual\"")
                continue
            _check_text(line.get("text"), f"{where}.text", errors, 400)
            text = line.get("text")
            if _is_str(text) and re.search(r"\d", text):
                warnings.append(f"{where}.text contains digits; write numbers as words so the voice reads them reliably")
            if _is_str(text):
                for sentence in SENTENCE_END_RE.split(text.strip()):
                    if len(sentence) > LONG_SENTENCE_CHARS:
                        warnings.append(
                            f"{where}.text has a sentence of {len(sentence)} characters (over {LONG_SENTENCE_CHARS}); "
                            f"long sentences sound rushed, consider splitting it: {sentence[:50]}..."
                        )
            if line.get("visual") is not None:
                validate_visual(line.get("visual"), f"{where}.visual", errors)
            if line.get("broll") is not None:
                validate_broll(line.get("broll"), f"{where}.broll", errors, warnings)

    sources = data.get("sources")
    if not isinstance(sources, list) or len(sources) < 2:
        errors.append("sources must list at least 2 sources, each with a title and an https:// url")
    else:
        for k, src in enumerate(sources):
            if not isinstance(src, dict):
                errors.append(f"sources[{k}] must be an object with \"title\" and \"url\"")
                continue
            _check_text(src.get("title"), f"sources[{k}].title", errors)
            url = src.get("url")
            if not _is_str(url) or not URL_RE.fullmatch(url):
                errors.append(f"sources[{k}].url {URL_MESSAGE} (got {url!r})")

    return errors, warnings


# --------------------------------------------------------------------------------------
# 3. Word error rate (pure)
# --------------------------------------------------------------------------------------


def levenshtein(a: list, b: list) -> int:
    """Edit distance between two sequences (here: lists of words)."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = normalize_words(reference)
    hyp = normalize_words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def wer_threshold(reference: str) -> float:
    return WER_LIMIT_LONG if len(normalize_words(reference)) >= 5 else WER_LIMIT_SHORT


def char_error_rate(reference: str, hypothesis: str) -> float:
    """Edit distance over the letters only (spaces, dashes and punctuation removed), so spelling variants such as
    'non-stop'/'nonstop', 'ear cup'/'earcup' or 'zu grattern'/'Zugrattern' count as equal. A real mishearing
    ('Noise Cancelling' heard as 'Neuskänzeling') still changes letters."""
    ref = "".join(normalize_words(reference))
    hyp = "".join(normalize_words(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(list(ref), list(hyp)) / len(ref)


def line_error_score(wer: float, cer: float, wer_limit: float) -> float:
    """<= 1.0 means the line passes: either the word check or the letter check is inside its limit."""
    return min(wer / wer_limit, cer / CER_LIMIT)


def word_differences(reference: str, hypothesis: str, limit: int = 30) -> list[str]:
    """Plain-English list of where the two texts differ (after the same normalisation as the WER)."""
    ref = normalize_words(reference)
    hyp = normalize_words(hypothesis)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        script_part, heard_part = " ".join(ref[i1:i2]), " ".join(hyp[j1:j2])
        if tag == "replace":
            out.append(f"script \"{script_part}\" -> subtitle \"{heard_part}\"")
        elif tag == "delete":
            out.append(f"script word(s) missing in the subtitle: \"{script_part}\"")
        else:
            out.append(f"extra word(s) in the subtitle: \"{heard_part}\"")
    if len(out) > limit:
        out = out[:limit] + [f"... and {len(out) - limit} more"]
    return out


# --------------------------------------------------------------------------------------
# 4/5. Timings and length gate (pure)
# --------------------------------------------------------------------------------------


def build_timings(texts: list[str], durations: list[float], gap: float = GAP_SECONDS) -> list[dict]:
    """Start/end seconds of each line on the final narration timeline (gap between lines only)."""
    timings = []
    cursor = 0.0
    for index, (text, duration) in enumerate(zip(texts, durations)):
        start = cursor
        end = start + duration
        timings.append({"index": index, "start": round(start, 3), "end": round(end, 3), "text": text})
        cursor = end + gap
    return timings


def length_gate(duration: float, words: int, min_s: float, max_s: float) -> tuple[bool, str]:
    """Is the narration inside [min_s, max_s]? The message says how many words to add or remove."""
    wps = words / duration if duration > 0 else 0.0
    if min_s <= duration <= max_s:
        return True, f"narration is {duration:.1f} s ({words} words, {wps:.2f} words/s), inside {min_s:g}-{max_s:g} s"
    middle = (min_s + max_s) / 2
    if duration < min_s:
        target = min(min_s + 2, middle)
        change = max(1, math.ceil((target - duration) * wps))
        return False, (
            f"Narration is too short: {duration:.1f} s, but it must be {min_s:g} to {max_s:g} s. "
            f"It has {words} words ({wps:.2f} words/s). Add about {change} words (aim for about {target:.0f} s)."
        )
    target = max(max_s - 2, middle)
    change = max(1, math.ceil((duration - target) * wps))
    return False, (
        f"Narration is too long: {duration:.1f} s, but it must be {min_s:g} to {max_s:g} s. "
        f"It has {words} words ({wps:.2f} words/s). Remove about {change} words (aim for about {target:.0f} s)."
    )


# --------------------------------------------------------------------------------------
# SRT sanity (pure)
# --------------------------------------------------------------------------------------

SRT_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def _srt_seconds(match: re.Match) -> float:
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[dict]:
    """Parse SRT text into [{"index", "start", "end", "text"}] (seconds)."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        rows = block.split("\n")
        for pos, row in enumerate(rows):
            if "-->" in row:
                found = list(SRT_TIME_RE.finditer(row))
                if len(found) >= 2:
                    cues.append(
                        {
                            "index": len(cues) + 1,
                            "start": _srt_seconds(found[0]),
                            "end": _srt_seconds(found[1]),
                            "text": " ".join(r.strip() for r in rows[pos + 1:]).strip(),
                        }
                    )
                break
    return cues


def _srt_stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_srt(cues: list[dict]) -> str:
    """Clean standard SRT: index, times, one text line, one EMPTY line (MPT pads its separator lines with spaces)."""
    return "".join(f"{k}\n{_srt_stamp(c['start'])} --> {_srt_stamp(c['end'])}\n{c['text']}\n\n" for k, c in enumerate(cues, 1))


def srt_issues(cues: list[dict]) -> list[tuple[float, str]]:
    """(start second, message) for zero-length cues, overlapping cues and non-increasing start times."""
    issues = []
    for k, cue in enumerate(cues):
        label = f"cue {cue['index']} ({cue['text'][:30]!r})"
        if cue["end"] - cue["start"] <= 0.0005:
            issues.append((cue["start"], f"{label} has zero length at {cue['start']:.3f} s"))
        if k > 0:
            prev = cues[k - 1]
            if cue["start"] <= prev["start"]:
                issues.append((cue["start"], f"{label} starts at {cue['start']:.3f} s, not after the previous cue ({prev['start']:.3f} s)"))
            if cue["start"] < prev["end"] - 0.001:
                issues.append((cue["start"], f"{label} starts at {cue['start']:.3f} s but the previous cue runs until {prev['end']:.3f} s (overlap)"))
    return issues


def srt_problems(cues: list[dict]) -> list[str]:
    """Zero-length cues, overlapping cues and non-increasing start times."""
    if not cues:
        return ["the subtitle file has no cues"]
    return [message for _start, message in srt_issues(cues)]


def lines_at_seconds(seconds: list[float], timings: list[dict]) -> list[int]:
    """Indexes of the script lines being spoken at these seconds (a moment inside a gap counts for the line before it)."""
    found = set()
    for t in seconds:
        spoken = [x["index"] for x in timings if x["start"] - 0.05 <= t <= x["end"] + 0.05]
        before = [x["index"] for x in timings if x["start"] <= t]
        pick = spoken[0] if spoken else (before[-1] if before else (timings[0]["index"] if timings else None))
        if pick is not None:
            found.add(pick)
    return sorted(found)


def subtitle_timing_hint(starts: list[float], timings: list[dict], work: Path) -> str:
    """What to do when Whisper gave a caption word no time of its own (the word would be missing on screen).

    Whisper always writes the same timestamps for the same audio, so running again changes nothing; the line has
    to be voiced again (the voice never says a line exactly the same way twice) or reworded.
    """
    lines = lines_at_seconds(starts, timings)
    if not lines:
        return ""
    files = ", ".join(str(work / "lines" / f"{k:02d}.json") for k in lines)
    numbers = ", ".join(str(k) for k in lines)
    return (
        f" Whisper gave a caption word no time of its own in line(s) {numbers}, so that word would be missing from the video. "
        f"The same narration always gets the same timing, so running again will not help. Delete {files} "
        "(the voice then says the line again, a little differently) and run again, or reword the line."
    )






def check_srt_accuracy(cues: list[dict], script_texts: list[str], limit: float = SRT_WER_LIMIT) -> tuple[bool, float, str, list[str]]:
    """Word error rate of ALL of Whisper's word cues together against the whole script.

    This is a VOICE-quality signal: if Whisper often hears something else than the script, the voice probably
    mispronounces those words. The captions themselves do not suffer (they show the script's own words, see
    studio/captions.py), but the listener does. Returns (ok, wer, message, differing words).
    """
    reference = " ".join(script_texts)
    heard = " ".join(c["text"] for c in cues)
    wer = word_error_rate(reference, heard)
    diffs = word_differences(reference, heard)
    if wer <= limit:
        return True, wer, f"word error rate {wer:.3f} (limit {limit:.2f}), {len(diffs)} differing spot(s) (fixed in the captions)", diffs
    shown = "\n      ".join(diffs)
    return False, wer, (
        f"Whisper does not hear the script in the narration: word error rate {wer:.3f} is above {limit:.2f}. "
        f"Whisper (inside MoneyPrinterTurbo) heard these differences:\n      {shown}\n"
        "  The voice probably says these words badly. Reword the lines that contain them (simpler words, numbers as words) and run again."
    ), diffs


def fixed_in_captions_note(diffs: list[str]) -> str | None:
    """A note that lists where Whisper heard something else than the script (the captions show the script's word), or None.

    Nothing wrong reaches the screen, but it tells the user which words the VOICE may say unclearly.
    """
    if not diffs:
        return None
    shown = "\n      ".join(diffs)
    return (f"fixed in captions: {len(diffs)} spot(s) where Whisper heard something else than the script. "
            f"The captions show the script's words; listen to these in the narration:\n      {shown}")


def first_caption_problem(cues: list[dict], limit_seconds: float = 1.0) -> str | None:
    """None when the first caption shows up within limit_seconds, else a short message."""
    if not cues:
        return "there are no captions"
    if cues[0]["start"] > limit_seconds:
        return f"the first caption only appears at {cues[0]['start']:.2f} s (it should start with the first spoken word, within {limit_seconds:g} s)"
    return None


# --------------------------------------------------------------------------------------
# 6. MoneyPrinterTurbo helpers (pure)
# --------------------------------------------------------------------------------------

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class FontMeasure:
    """Glyph widths of a TrueType font, read with the standard library (no Pillow).

    Used to pick a caption size so that the widest word of a script fits the screen. Kerning is ignored
    and the advance width includes the side bearings, so the answer is a little wider than the real ink.
    """

    def __init__(self, data: bytes):
        u16 = lambda off: struct.unpack_from(">H", data, off)[0]  # noqa: E731
        s16 = lambda off: struct.unpack_from(">h", data, off)[0]  # noqa: E731
        tables = {}
        for k in range(u16(4)):
            tag, _checksum, offset, _length = struct.unpack_from(">4sIII", data, 12 + 16 * k)
            tables[tag.decode("latin-1")] = offset
        self.units = u16(tables["head"] + 18)
        self.ascent = s16(tables["hhea"] + 4)
        self.descent = -s16(tables["hhea"] + 6)
        metric_count = u16(tables["hhea"] + 34)
        hmtx = tables["hmtx"]
        self._advances = [u16(hmtx + 4 * k) for k in range(metric_count)]
        cmap = tables["cmap"]
        self._cmap4 = None
        for k in range(u16(cmap + 2)):
            platform, encoding, offset = struct.unpack_from(">HHI", data, cmap + 4 + 8 * k)
            if (platform, encoding) in ((3, 1), (0, 3), (0, 4)) and u16(cmap + offset) == 4:
                self._cmap4 = cmap + offset
                break
        if self._cmap4 is None:
            raise ValueError("no Unicode (format 4) character map in the font")
        self._u16, self._s16 = u16, s16

    def _glyph(self, code: int) -> int:
        u16, base = self._u16, self._cmap4
        seg2 = u16(base + 6)
        ends, starts = base + 14, base + 16 + seg2
        deltas, ranges = starts + seg2, starts + 2 * seg2
        for k in range(seg2 // 2):
            if code > u16(ends + 2 * k):
                continue
            if code < u16(starts + 2 * k):
                return 0
            delta, range_offset = u16(deltas + 2 * k), u16(ranges + 2 * k)
            if range_offset == 0:
                return (code + delta) & 0xFFFF
            glyph = u16(ranges + 2 * k + range_offset + 2 * (code - u16(starts + 2 * k)))
            return (glyph + delta) & 0xFFFF if glyph else 0
        return 0

    def text_width(self, text: str, size: float) -> float:
        total = sum(self._advances[min(self._glyph(ord(ch)), len(self._advances) - 1)] for ch in text)
        return total * size / self.units

    def line_height(self, size: float) -> int:
        return math.ceil(self.ascent * size / self.units) + math.ceil(self.descent * size / self.units)


def caption_tokens(texts: list[str]) -> list[str]:
    """The words as Whisper will write them: split at spaces, punctuation stays attached ('Tag?', 'zusammen,')."""
    return sorted({token for text in texts for token in text.split()})


def caption_stroke_width(font_size: int) -> int:
    return max(3, round(font_size * 0.08))


def caption_box_height(font_size: int, stroke_width: int, line_height: int) -> int:
    """Height of MPT's one-line caption box (text + padding + line spacing + outline), as MPT computes it."""
    return line_height + int(font_size * 0.35) + int(font_size * 0.25) + int(stroke_width * 2)


def caption_position_percent(box_height: int) -> float:
    """The --custom-position value (percent from the top) that puts the TOP of a box this tall at CAPTION_BOX_TOP_Y.

    MPT places a custom caption at y = (frame height - box height) * percent / 100.
    """
    return round(100 * CAPTION_BOX_TOP_Y / (FRAME_HEIGHT - box_height), 2)


def caption_box_top_y(box_height: int, position_percent: float) -> int:
    """Where MPT really puts the TOP of the caption box for that percent (it keeps 10 px away from the frame edges)."""
    y = (FRAME_HEIGHT - box_height) * position_percent / 100
    return int(max(10, min(y, FRAME_HEIGHT - box_height - 10)))


def pick_caption_style(texts: list[str], font_path: Path) -> dict:
    """Biggest font size (<= CAPTION_FONT_MAX) at which the widest word of THIS script still fits.

    MPT wraps (cuts a word in two) above 90% of the frame width = 972 px, and the pop animation
    overshoots to about 112%, so CAPTION_MAX_WORD_PX leaves room for both.
    """
    tokens = caption_tokens(texts)
    try:
        measure = FontMeasure(font_path.read_bytes())
        per_px = {token: measure.text_width(token, 1000) / 1000 for token in tokens}
        height_of = measure.line_height
    except (OSError, ValueError, KeyError, struct.error) as exc:
        per_px = {token: 0.65 * len(token) for token in tokens}  # safe over-estimate if the font cannot be read
        height_of = lambda size: math.ceil(1.35 * size)  # noqa: E731
        note = f"font file could not be measured ({exc}); used a safe estimate"
    else:
        note = None
    widest = max(per_px, key=per_px.get) if per_px else ""
    em = per_px.get(widest, 0.0)
    fit = math.floor(CAPTION_MAX_WORD_PX / em) if em else CAPTION_FONT_MAX
    size = max(CAPTION_FONT_MIN, min(CAPTION_FONT_MAX, fit))
    stroke = caption_stroke_width(size)
    box_height = caption_box_height(size, stroke, height_of(size))
    percent = caption_position_percent(box_height)
    style = {
        "font": SUBTITLE_FONT, "font_size": size, "stroke_width": stroke,
        "widest_word": widest, "widest_word_px": round(em * size),
        "box_height": box_height, "position_percent": percent, "box_top_y": caption_box_top_y(box_height, percent),
        "size_limited_by_word": fit < CAPTION_FONT_MAX,
    }
    if note:
        style["note"] = note
    return style


def caption_word_problem(caption: dict) -> str | None:
    """None when the widest word fits on one caption line; else a plain message (the word would be cut in two)."""
    if caption["widest_word_px"] <= CAPTION_MAX_WORD_PX:
        return None
    return (
        f"The word {caption['widest_word']!r} is too long to show as one caption: it is about {caption['widest_word_px']} px wide "
        f"even at the smallest caption size ({CAPTION_FONT_MIN} px), and the limit is {CAPTION_MAX_WORD_PX} px, so it would be cut in two "
        "on screen. Split or hyphenate it in the script (for example 'Lebensmittel-Verschwendung'), or use a shorter word."
    )


def pick_footage_source(app_cfg: dict) -> str | None:
    """Stock-footage provider to download from: Pexels when its key is set, otherwise Pixabay, otherwise None.
    (Pexels paused new API keys in October 2026, so Pixabay is the usual fallback.)"""
    for name in ("pexels", "pixabay"):
        if any(str(key).strip() for key in app_cfg.get(f"{name}_api_keys") or []):
            return name
    return None


NO_FOOTAGE_KEY_MESSAGE = (
    "No stock-footage API key is set in MoneyPrinterTurbo/config.toml (under [app]). Only you can add one: "
    "pixabay_api_keys = [\"...\"] (free; the key is shown on pixabay.com/api/docs once you are logged in) "
    "or pexels_api_keys = [\"...\"] (pexels.com/api). Paste it in, then run this again. "
    "(To test without footage use --local-materials DIR.)"
)


def resolve_footage_mode(requested: str, has_local_materials: bool, has_pixabay_key: bool, mpt_source: str | None) -> tuple[str, str | None]:
    """Where the stock footage comes from. Returns (mode, MPT provider).

    local: --local-materials (your own files, nothing is searched)
    own:   studio/footage.py searches Pixabay and cuts the clips (needs a Pixabay key); this is what auto picks
    mpt:   MoneyPrinterTurbo searches by itself (the old behaviour; needs a Pexels or Pixabay key)"""
    if has_local_materials:
        if requested == "own":
            raise GateError("--footage own and --local-materials cannot be used together: local materials ARE your own footage. Leave one of them out.")
        return "local", None
    if requested == "own":
        if not has_pixabay_key:
            raise GateError("--footage own needs a Pixabay key in MoneyPrinterTurbo/config.toml (under [app]: pixabay_api_keys = [\"...\"]). "
                            "Only you can add one; the key is free on pixabay.com/api/docs once you are logged in.")
        return "own", None
    if requested == "auto" and has_pixabay_key:
        return "own", None
    if mpt_source is None:
        raise GateError(NO_FOOTAGE_KEY_MESSAGE)
    return "mpt", mpt_source


def build_mpt_command(uv: str, script_text: str, terms: list[str], narration: Path, task_id: str,
                      local_files: list[Path] | None = None, font_size: int = CAPTION_FONT_MAX,
                      stroke_width: int | None = None, position_percent: float | None = None,
                      source: str | None = None, fixed_order_seconds: int | None = None,
                      stop_at: str | None = None, burn_captions: bool = True) -> list[str]:
    """The `uv run python cli.py ...` command (run it with cwd = MoneyPrinterTurbo).

    Two kinds of run:
    - stop_at="subtitle": only Whisper's word timing is wanted (MPT stops after the subtitle stage, no footage, no
      video), so no footage options are added.
    - burn_captions=False (the video run): MPT builds the video WITHOUT captions (--no-subtitle-enabled, so it does
      not even run Whisper); our own captions are drawn later by Remotion (studio/visuals.py).

    fixed_order_seconds (own footage): the local material is ONE already-cut B-roll file, so MPT must play it once,
    from start to end, in our order: sequential mode, no transitions, normal speed, and a clip length longer than
    the file (MPT otherwise cuts every material into 5 s pieces and keeps only the first piece in sequential mode)."""
    if stroke_width is None:
        stroke_width = caption_stroke_width(font_size)
    if position_percent is None:  # safe over-estimate of the line height, like pick_caption_style's fallback
        position_percent = caption_position_percent(caption_box_height(font_size, stroke_width, math.ceil(1.35 * font_size)))
    cmd = [
        uv, "run", "python", "cli.py",
        "--video-script", script_text,
        "--video-terms", ",".join(terms),
        "--custom-audio-file", str(narration),
        "--bgm-type", "none",
    ]
    if burn_captions:
        cmd += [
            "--font-name", SUBTITLE_FONT,
            "--subtitle-enabled",
            "--no-subtitle-background-enabled",  # never let a background saved by the MPT WebUI shrink the room for a word
            "--subtitle-display-mode", SUBTITLE_DISPLAY_MODE,
            "--subtitle-animation", SUBTITLE_ANIMATION,
            "--subtitle-position", SUBTITLE_POSITION,
            "--custom-position", f"{position_percent:g}",
            "--font-size", str(int(font_size)),
            "--stroke-width", str(int(stroke_width)),
            "--stroke-color", SUBTITLE_STROKE_COLOR,
            "--text-fore-color", SUBTITLE_TEXT_COLOR,
        ]
    else:
        cmd += ["--no-subtitle-enabled"]
    cmd += [
        "--video-aspect", "9:16",
        "--task-id", task_id,
    ]
    if stop_at:
        cmd += ["--stop-at", stop_at]
    if stop_at == "subtitle":
        return cmd
    if local_files:
        cmd += ["--video-source", "local", "--video-materials", ",".join(str(p) for p in local_files)]
        if fixed_order_seconds:
            cmd += ["--video-concat-mode", "sequential", "--video-transition-mode", "none",
                    "--video-clip-duration", str(int(fixed_order_seconds)), "--video-clip-speed", "1.0"]
    elif source:
        cmd += ["--video-source", source]
    return cmd


def mpt_script_text(texts: list[str], subtitle_mode: str = SUBTITLE_DISPLAY_MODE) -> str:
    """The script text handed to MPT (its CLI insists on getting one).

    word_by_word (what we use): MPT's whisper path never looks at the script (the subtitle.correct step that
    matches Whisper cues against script pieces is skipped, and the narration is our own audio file), so the
    script goes in as it is written, commas and all; only line breaks/extra spaces are tidied and every line
    ends with sentence punctuation.

    sentence mode (kept for completeness, not used): MPT cuts the script into pieces at EVERY punctuation mark
    (also , ; :) and matches them against Whisper's cues. Whisper only writes a comma when it feels like it, so
    a script comma can leave MPT with more pieces than cues and a zero-length cue. Only . ! ? are kept then.
    Commas inside numbers (1,000) are left alone.
    """
    sentences = []
    for text in texts:
        if subtitle_mode != "word_by_word":
            text = re.sub(r"(?<!\d),|,(?!\d)", " ", text)
            text = re.sub(r"[;:、，；：…]", " ", text)
            text = re.sub(r"\s*[–—]\s*", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text and text[-1] not in ".!?":
            text += "."
        sentences.append(text)
    return " ".join(sentences)


def parse_mpt_result(log_lines: list[str]) -> dict | None:
    """cli.py prints ONE json line {"task_id": ..., "result": {...}} after its (stdout) log lines."""
    for line in reversed(log_lines):
        line = line.strip()
        if line.startswith("{") and '"result"' in line:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("result"), dict):
                return data
    return None


def collect_mpt_notes(log_text: str) -> list[str]:
    """Subtitle-alignment warnings worth showing in the report (not failures)."""
    notes = []
    for line in strip_ansi(log_text).splitlines():
        if "Mismatch - Script" in line or "Extra script line" in line:
            notes.append(line.strip()[:400])
    return notes


def detect_whisper_language(log_text: str) -> tuple[str, float] | None:
    found = re.findall(r"detected language: '([A-Za-z-]+)', probability: ([0-9.]+)", strip_ansi(log_text))
    if not found:
        return None
    code, prob = found[-1]
    return code.lower(), float(prob)


def check_whisper_language(log_text: str, expected: str) -> tuple[bool, str]:
    """Fail only when whisper clearly heard another language than the script's."""
    detected = detect_whisper_language(log_text)
    if detected is None:
        return True, "whisper did not print its detected language (could not compare)"
    code, prob = detected
    if code == expected:
        return True, f"whisper detected '{code}' (probability {prob:.2f})"
    if prob >= 0.5:
        return False, (
            f"Whisper heard language '{code}' (probability {prob:.2f}) but the script says '{expected}'. "
            "The narration is probably in the wrong language: check studio/voices.json and the line texts."
        )
    return True, f"whisper guessed '{code}' with low probability {prob:.2f}; script language is '{expected}'"


BGM_LOG_PATTERNS = (
    re.compile(r"resource[/\\]songs", re.I),
    re.compile(r"storage[/\\]bgm", re.I),
    re.compile(r"failed to mix background music", re.I),
    re.compile(r"\bbgm_file\b\s*[=:]\s*['\"]?[^\s'\",)]+\.(mp3|m4a|wav|flac|ogg)", re.I),
)


def find_bgm_usage(log_text: str, saved_params: dict | None = None) -> list[str]:
    """Anything that suggests MPT mixed in background music (we always want --bgm-type none)."""
    problems = []
    for line in strip_ansi(log_text).splitlines():
        if line.startswith("#"):  # our own header line with the command
            continue
        if any(p.search(line) for p in BGM_LOG_PATTERNS):
            problems.append(f"log mentions background music: {line.strip()[:200]}")
    if isinstance(saved_params, dict):
        if saved_params.get("bgm_type"):
            problems.append(f"MPT saved bgm_type={saved_params.get('bgm_type')!r} for this task")
        if saved_params.get("bgm_file"):
            problems.append(f"MPT saved bgm_file={saved_params.get('bgm_file')!r} for this task")
    return problems


def find_burned_captions(log_text: str, result: dict, saved_params: dict | None = None) -> list[str]:
    """Anything that suggests MPT's own video has captions burned in (we draw ours; two sets would double on screen)."""
    problems = []
    if isinstance(result, dict) and result.get("subtitle_path"):
        problems.append(f"MPT returned a subtitle file for the video run: {result.get('subtitle_path')}")
    if re.search(r"detected language: '", strip_ansi(log_text)):
        problems.append("Whisper ran inside the video run")
    if isinstance(saved_params, dict) and saved_params.get("subtitle_enabled") is not False:
        problems.append(f"MPT saved subtitle_enabled={saved_params.get('subtitle_enabled')!r} for this task")
    return problems


# --------------------------------------------------------------------------------------
# 8/9/10. Final checks, credits, naming, caption (pure)
# --------------------------------------------------------------------------------------


def check_final_info(info: dict, min_seconds: float) -> list[tuple[str, bool, str]]:
    """(name, ok, detail) for duration, size and audio of the final video's ffprobe summary."""
    results = []
    duration = info.get("duration") or 0.0
    if min_seconds > 0:
        ok = duration >= min_seconds - 0.5
        results.append(("final duration", ok, f"{duration:.1f} s (needs at least {min_seconds - 0.5:g} s)"))
    else:
        results.append(("final duration", True, f"{duration:.1f} s (minimum check skipped because --min-seconds is 0)"))
    size = (info.get("width"), info.get("height"))
    results.append(("final size", size == (1080, 1920), f"{size[0]}x{size[1]} (needs exactly 1080x1920)"))
    results.append(("final audio", bool(info.get("has_audio")), "audio stream present" if info.get("has_audio") else "no audio stream"))
    return results


def build_credits(material_sources: list[dict]) -> tuple[list[str], list[str]]:
    """Credit lines for downloaded stock clips + notes. Local materials need no credit."""
    lines: list[str] = []
    notes: list[str] = []
    seen: set[str] = set()
    for rec in material_sources or []:
        provider = str(rec.get("provider") or "").strip().lower()
        if not provider or provider == "local":
            continue
        label, domain = PROVIDER_LABELS.get(provider, (provider.title(), None))
        where = f"{label} ({domain})" if domain else label
        creator = str((rec.get("creator") or {}).get("name") or "").strip()
        page = str(rec.get("source_page") or "").strip()
        line = f"Videos by {creator} on {where}" if creator else f"Video on {where}"
        if page:
            line += f": {page}"
        if not creator:
            notes.append(f"{provider}: MPT recorded no creator name for {page or rec.get('local_file')}; credited with the page URL only")
        if not page:
            notes.append(f"{provider}: MPT recorded no page URL for {rec.get('local_file')}")
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return lines, notes


def _valid_date(text: str) -> bool:
    try:
        datetime.date.fromisoformat(text)
        return True
    except ValueError:
        return False


def slug_from_id(sid: str, language: str) -> str:
    """Drop a leading date and a leading language code ('2026-10-14-en-fridge' -> 'fridge')."""
    slug = sid
    m = DATE_PREFIX_RE.match(slug)
    if m and _valid_date(m.group(1)):
        slug = slug[m.end():]
    for code in (language, *LANGUAGES):
        if slug.startswith(code + "-"):
            slug = slug[len(code) + 1:]
            break
    slug = slug.lstrip("_-")
    return slug or "video"


def review_folder_name(script: dict, today: datetime.date) -> str:
    """<YYYY-MM-DD>-<language>-<slug>; the date is the one in the id, otherwise today's."""
    m = DATE_PREFIX_RE.match(script["id"])
    date = m.group(1) if m and _valid_date(m.group(1)) else today.isoformat()
    return f"{date}-{script['language']}-{slug_from_id(script['id'], script['language'])}"


def build_caption(script: dict, credits: list[str]) -> str:
    """caption.txt: title, caption, hashtags, disclosure + credits, then the sources."""
    language = script["language"]
    block = "\n".join([DISCLOSURE[language], *credits])
    sources = "\n".join(f"{s['title']} – {s['url']}" for s in script["sources"])
    return (
        f"{script['title']}\n\n{script['caption']}\n\n{' '.join(script['hashtags'])}\n\n"
        f"{block}\n\n{SOURCES_LABEL[language]}\n{sources}\n"
    )


def pick_media_scripts_dir(base: Path) -> Path:
    """Newest <base>/<version>/skills/media-studio/scripts (by version number)."""
    candidates = [p for p in base.glob("*/skills/media-studio/scripts") if (p / "speak.mjs").is_file()]
    if not candidates:
        raise GateError(f"The media-studio plugin scripts were not found under {base}. Run /media-studio:setup.")
    return max(candidates, key=lambda p: [int(n) for n in re.findall(r"\d+", p.parents[2].name)])


def check_tts_engine(info: dict) -> str | None:
    """None when VoiceStudio's active TTS is MLX-Audio + Qwen3-TTS CustomVoice, else the fix-it message."""
    model = info.get("active_model")
    model = model if isinstance(model, str) else json.dumps(model)
    if info.get("active") == REQUIRED_TTS_ENGINE and REQUIRED_TTS_MODEL in (model or ""):
        return None
    return (
        f"VoiceStudio switched engine (active: {info.get('active')!r}, model: {model!r}). "
        "In VoiceStudio select MLX-Audio + Qwen3-TTS CustomVoice, then run this again."
    )


def build_multipart(fields: dict, file_field: str, filename: str, data: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode() + data + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def repoint_paths(obj, mapping: dict):
    """Copy of obj (dicts/lists/strings) where every string equal to a key of `mapping` becomes mapping[key]."""
    if isinstance(obj, dict):
        return {k: repoint_paths(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [repoint_paths(v, mapping) for v in obj]
    if isinstance(obj, str) and obj in mapping:
        return mapping[obj]
    return obj


def replace_in_strings(obj, mapping: dict):
    """Copy of obj where every key of `mapping` is replaced by its value INSIDE every string (longest key first).

    repoint_paths only handles strings that are exactly a path; check details are sentences that contain one.
    """
    if isinstance(obj, dict):
        return {k: replace_in_strings(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_in_strings(v, mapping) for v in obj]
    if isinstance(obj, str):
        for old in sorted(mapping, key=len, reverse=True):
            obj = obj.replace(old, mapping[old])
        return obj
    return obj


def mark_deleted_in_strings(obj, deleted: list[str]):
    """Copy of obj where a deleted path (or a path inside a deleted folder) written inside a sentence is shortened
    to its file name plus ' (deleted after the run)', so no sentence points at a file that is gone."""
    if isinstance(obj, dict):
        return {k: mark_deleted_in_strings(v, deleted) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mark_deleted_in_strings(v, deleted) for v in obj]
    if isinstance(obj, str):
        for path in sorted(deleted, key=len, reverse=True):
            pattern = re.escape(path.rstrip(os.sep)) + r"(?:" + re.escape(os.sep) + r"[^\s,;)\"']+)*"
            obj = re.sub(pattern, lambda m: m.group(0).rstrip(os.sep).rsplit(os.sep, 1)[-1] + " (deleted after the run)", obj)
        return obj
    return obj


def _is_deleted(value, deleted: list[str]) -> bool:
    return isinstance(value, str) and any(value == d or value.startswith(d.rstrip(os.sep) + os.sep) for d in deleted)


def drop_deleted_paths(obj, deleted: list[str]):
    """Copy of obj without references to deleted files: such a string becomes None, or is left out of a list."""
    if isinstance(obj, dict):
        return {k: (None if _is_deleted(v, deleted) else drop_deleted_paths(v, deleted)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [drop_deleted_paths(v, deleted) for v in obj if not _is_deleted(v, deleted)]
    return obj


# --------------------------------------------------------------------------------------
# Tools (not pure: they touch the network, the disk and other programs)
# --------------------------------------------------------------------------------------


def find_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise GateError(f"The program '{name}' was not found on PATH. Install it (for example with Homebrew) and run this again.")
    return path


def run_cmd(cmd: list[str], timeout: float, what: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise GateError(f"{what} did not finish within {timeout:.0f} s and was stopped.")
    except OSError as exc:
        raise GateError(f"{what} could not be started: {exc}")


def kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the process AND everything it started (needs Popen(..., start_new_session=True): its pid is the group id)."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass  # the group is already gone
    try:
        proc.kill()
    except OSError:
        pass


def run_streaming(cmd: list[str], cwd: Path | None, env: dict | None, timeout: float, on_line) -> tuple[int, bool]:
    """Run cmd in its own process group; call on_line(text) for each output line (stdout+stderr).

    Returns (exit code, timed_out). After `timeout` seconds the whole group is killed (not only the launcher,
    like `uv`, whose children would otherwise keep running and keep the output pipe open). Ctrl-C kills the
    group too: it no longer shares our terminal's process group, so the terminal would not stop it.
    Raises OSError when the command cannot be started.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=env, start_new_session=True)
    timed_out = threading.Event()

    def stop() -> None:
        timed_out.set()
        kill_process_group(proc)

    timer = threading.Timer(timeout, stop)
    timer.daemon = True
    timer.start()
    try:
        for raw in proc.stdout:
            on_line(raw.rstrip("\n"))
        code = proc.wait()
    except BaseException:
        kill_process_group(proc)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        raise
    finally:
        timer.cancel()
        proc.stdout.close()
    return code, timed_out.is_set()


HTTP_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, ValueError)


def http_get_json(path: str, timeout: float = 10) -> dict:
    with urllib.request.urlopen(VOICESTUDIO_URL + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def voicestudio_info(path: str, what: str) -> dict:
    """GET a VoiceStudio status page; any trouble becomes a plain-English GateError."""
    try:
        info = http_get_json(path)
    except HTTP_ERRORS as exc:
        raise GateError(f"VoiceStudio could not tell {what} ({path}): {type(exc).__name__}: {exc}. "
                        "Is VoiceStudio still running? Start or restart it and run this again.")
    if not isinstance(info, dict):
        raise GateError(f"VoiceStudio answered {path} with something unexpected ({type(info).__name__}, not an object). "
                        "Restart VoiceStudio and run this again.")
    return info


def transcribe_wav(wav: Path, model: str, language: str | None) -> str:
    """Ask VoiceStudio to transcribe a wav; returns the text (one retry on network trouble)."""
    fields = {"model": model, "response_format": "json"}
    if language:
        fields["language"] = language
    body, ctype = build_multipart(fields, "file", wav.name, wav.read_bytes(), "audio/wav")
    last = None
    for _ in range(2):
        req = urllib.request.Request(VOICESTUDIO_URL + "/v1/audio/transcriptions", data=body, headers={"Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return str(json.loads(resp.read().decode("utf-8")).get("text", "")).strip()
        except HTTP_ERRORS as exc:
            last = exc
            time.sleep(1)
    raise GateError(f"VoiceStudio could not transcribe {wav.name}: {last}. Is VoiceStudio still running?")


def ffprobe_info(ffprobe: str, path: Path) -> dict:
    proc = run_cmd([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], 120, "ffprobe")
    if proc.returncode != 0:
        raise GateError(f"ffprobe could not read {path}: {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration": duration,
        "width": video.get("width") if video else None,
        "height": video.get("height") if video else None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "has_video": video is not None,
    }


# --------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------


class Ctx:
    """Everything one run needs, plus the report that gets written at the end."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.script: dict = {}
        self.script_path = Path(args.script).expanduser().resolve()
        self.work = WORK_ROOT
        self.media_dir: Path | None = None
        self.checks: list[dict] = []
        self.warnings: list[str] = []
        self.report: dict = {"inputs": {"script": str(self.script_path)}}
        self.started = time.time()
        self.removed_early: list[str] = []  # files deleted before the cleanup step (MPT's copies of local materials)

    def say(self, msg: str = "") -> None:
        print(msg, flush=True)

    def step(self, number: int, title: str) -> None:
        self.say(f"\n[{number}/11] {title}")

    def check(self, name: str, ok: bool, detail: str, fatal: bool = True) -> None:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        self.say(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
        if not ok and fatal:
            raise GateError(f"{name} failed: {detail}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.say(f"  [warn] {msg}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="make_video.py",
        description="Turn content/<id>/script.json into a review-ready Short (voice, MoneyPrinterTurbo video, checks, caption).",
    )
    p.add_argument("script", help="path to content/<id>/script.json")
    p.add_argument("--local-materials", metavar="DIR", help="use the video/image files in DIR instead of downloading stock footage (Pexels or Pixabay)")
    p.add_argument("--min-seconds", type=float, default=61.0, help="shortest allowed narration (default 61); 0 also skips the final minimum-duration check")
    p.add_argument("--max-seconds", type=float, default=75.0, help="longest allowed narration (default 75)")
    p.add_argument("--keep-work", action="store_true", help="keep work/<id> and MoneyPrinterTurbo's task folder for debugging")
    p.add_argument("--no-visuals", action="store_true", help="skip the diagram overlays (studio/visuals.py)")
    p.add_argument("--stage", choices=("voice", "all"), default="all", help="'voice' stops after the narration + length gate")
    p.add_argument("--footage", choices=FOOTAGE_MODES, default="auto",
                   help="where the stock footage comes from: 'own' = studio/footage.py picks and cuts Pixabay clips per line (needs a Pixabay key), "
                        "'mpt' = MoneyPrinterTurbo searches by itself (old behaviour), 'auto' (default) = own when a Pixabay key is set "
                        "and --local-materials is not used")
    args = p.parse_args(argv)
    if args.min_seconds < 0 or args.max_seconds <= 0 or args.min_seconds > args.max_seconds:
        p.error("--min-seconds must be >= 0 and not larger than --max-seconds")
    return args


def step_validate(ctx: Ctx) -> None:
    ctx.step(1, f"Validating {ctx.script_path}")
    if not ctx.script_path.is_file():
        raise GateError(f"script file not found: {ctx.script_path}")
    try:
        data = json.loads(ctx.script_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise GateError(f"{ctx.script_path} is not valid JSON: {exc}")
    errors, warnings = validate_script(data)
    for w in warnings:
        ctx.warn(w)
    if errors:
        shown = "\n    - ".join(errors)
        ctx.checks.append({"name": "script.json valid", "ok": False, "detail": errors})
        raise GateError(f"script.json does not match the contract. Fix these and run again:\n    - {shown}")
    ctx.script = data
    if ctx.script_path.parent.name != data["id"]:
        ctx.warn(f"the folder name '{ctx.script_path.parent.name}' differs from the script id '{data['id']}'")
    ctx.work = WORK_ROOT / data["id"]
    ctx.check("script.json valid", True, f"{len(data['lines'])} lines, {len(data['sources'])} sources, language {data['language']}")


def load_visuals_module(needed: list[int]):
    """Import studio/visuals.py and make sure render_and_overlay exists; plain GateError otherwise.

    `needed` = the lines that have a visual. visuals.py is needed even without any: it draws the captions.
    """
    if str(STUDIO_DIR) not in sys.path:
        sys.path.insert(0, str(STUDIO_DIR))
    what = ("lines " + ", ".join(map(str, needed)) + " have a visual and the captions are drawn by it") if needed else "it draws the captions"
    try:
        module = importlib.import_module("visuals")
    except ModuleNotFoundError as exc:
        if exc.name == "visuals":
            raise GateError(f"studio/visuals.py does not exist yet, but {what}. Build it first.")
        raise GateError(f"studio/visuals.py could not be imported (missing module {exc.name!r}).")
    except Exception as exc:  # a broken visuals.py must not crash the run with a raw traceback
        raise GateError(f"studio/visuals.py could not be imported: {type(exc).__name__}: {exc}. Fix it first ({what}).")
    if not callable(getattr(module, "render_and_overlay", None)):
        raise GateError(f"studio/visuals.py has no render_and_overlay function. Fix it first ({what}).")
    return module


def step_preflight(ctx: Ctx) -> dict:
    ctx.step(2, "Preflight")
    args, script = ctx.args, ctx.script
    for tool in ("ffmpeg", "ffprobe", "node", "uv"):
        find_tool(tool)
    ctx.media_dir = pick_media_scripts_dir(Path.home() / ".claude/plugins/cache/media-studio-marketplace/media-studio")
    ctx.check("tools", True, f"ffmpeg, ffprobe, node, uv found; media-studio scripts: {ctx.media_dir}")

    health = voicestudio_info("/health", "whether it is healthy")
    if str(health.get("status", "")).lower() != "ok":
        raise GateError(f"VoiceStudio /health did not say ok: {health}")
    tts = voicestudio_info("/engines/tts", "which voice engine is active")
    problem = check_tts_engine(tts)
    if problem:
        raise GateError(problem)
    asr = voicestudio_info("/engines/asr", "which transcription engine is active")
    asr_model = asr.get("active")
    if not asr_model:
        raise GateError("VoiceStudio has no active transcription engine (/engines/asr). Select one in VoiceStudio and run this again.")
    ctx.check("VoiceStudio", True, f"healthy; TTS {tts.get('active')} / {tts.get('active_model')}; transcription {asr_model}")

    if not VOICES_FILE.is_file():
        raise GateError(f"{VOICES_FILE} is missing (it holds the voice + delivery directions per language).")
    try:
        voices = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{VOICES_FILE} cannot be read as JSON ({exc}). Fix the file (it needs an \"en\" and a \"de\" entry) and run this again.")
    if not isinstance(voices, dict):
        raise GateError(f"{VOICES_FILE} must hold one JSON object with an \"en\" and a \"de\" entry.")
    voice_cfg = voices.get(script["language"])
    if not isinstance(voice_cfg, dict) or not voice_cfg.get("voice") or not voice_cfg.get("instructions"):
        raise GateError(f"studio/voices.json has no complete \"{script['language']}\" entry (it needs \"voice\" and \"instructions\").")

    cli = MPT_DIR / "cli.py"
    config = MPT_DIR / "config.toml"
    if not cli.is_file() or not config.is_file():
        raise GateError(f"MoneyPrinterTurbo is not set up: need {cli} and {config}.")
    try:
        cfg = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"MoneyPrinterTurbo/config.toml cannot be read: {exc}")
    app_cfg = cfg.get("app", {})
    if str(app_cfg.get("subtitle_provider", "")).strip().lower() != "whisper":
        raise GateError("MoneyPrinterTurbo/config.toml must have subtitle_provider = \"whisper\" under [app] (it makes subtitles from our narration).")
    font_path = MPT_DIR / "resource" / "fonts" / SUBTITLE_FONT
    if not font_path.is_file():
        raise GateError(f"The caption font {SUBTITLE_FONT} is missing: expected {font_path}.")
    local_files: list[Path] = []
    source: str | None = None  # MPT's stock-footage provider; stays None when --local-materials or own footage is used
    if args.local_materials:
        folder = Path(args.local_materials).expanduser().resolve()
        if not folder.is_dir():
            raise GateError(f"--local-materials folder not found: {folder}")
        local_files = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in LOCAL_MATERIAL_EXTENSIONS)
        if not local_files:
            raise GateError(f"--local-materials folder {folder} has no video or image files ({', '.join(sorted(LOCAL_MATERIAL_EXTENSIONS))}).")
        if any("," in str(f) for f in local_files):
            raise GateError("A local material file name contains a comma, which MPT cannot take. Rename it.")
        ctx.say(f"  local materials: {len(local_files)} files from {folder}")
    mode, source = resolve_footage_mode(args.footage, bool(args.local_materials),
                                        footage.pixabay_key_from_config(app_cfg) is not None, pick_footage_source(app_cfg))
    if mode == "own":
        ctx.say("  footage: own selection from Pixabay, one clip per script line (API key set, value not shown)")
    elif mode == "mpt":
        ctx.say(f"  footage source: {PROVIDER_LABELS[source][0]}, searched by MoneyPrinterTurbo itself (API key set, value not shown)")
        ctx.warn("MoneyPrinterTurbo picks the footage itself; it finds few portrait clips and often off-topic ones. Prefer --footage own.")

    needs_visuals = [k for k, line in enumerate(script["lines"]) if line.get("visual")]
    load_visuals_module(needs_visuals if not args.no_visuals else [])  # fail now, not after minutes of voice + video work
    ctx.say("  studio/visuals.py: render_and_overlay found (it draws the captions" + ("" if args.no_visuals or not needs_visuals else " and the diagram panels") + ")")

    caption = pick_caption_style([line["text"].strip() for line in script["lines"]], font_path)
    ctx.check("caption size", caption["box_top_y"] >= CAPTION_TOP_LIMIT_Y,
              f"{caption['font_size']} px, outline {caption['stroke_width']} px; widest word {caption['widest_word']!r} is about "
              f"{caption['widest_word_px']} px wide; caption top at y={caption['box_top_y']}, under the diagram area that ends at y={CAPTION_TOP_LIMIT_Y}")
    word_problem = caption_word_problem(caption)
    ctx.check("caption word fits", word_problem is None,
              word_problem or f"the widest word fits on one caption line ({caption['widest_word_px']} of {CAPTION_MAX_WORD_PX} px)")
    ctx.report["inputs"]["local_materials"] = [str(f) for f in local_files]
    ctx.report["captions"] = {"mode": SUBTITLE_DISPLAY_MODE, "animation": SUBTITLE_ANIMATION, "position": SUBTITLE_POSITION, **caption}
    ctx.report["voice"] = {
        "engine": tts.get("active"), "model": tts.get("active_model"), "voice": voice_cfg["voice"],
        "instructions": voice_cfg["instructions"], "transcription_engine": asr_model,
    }
    ctx.report["inputs"]["footage_source"] = {"local": "local", "own": "pixabay (own selection)"}.get(mode, source)
    ctx.report["inputs"]["footage_mode"] = mode
    ctx.report["footage"] = {"mode": mode, "provider": {"local": "local files", "own": "pixabay", "mpt": source}[mode]}
    return {"voice_cfg": voice_cfg, "asr_model": asr_model, "tts_model": str(tts.get("active_model")),
            "local_files": local_files, "caption": caption, "source": source, "footage": mode}


def speak_once(ctx: Ctx, text: str, out_wav: Path, voice_cfg: dict) -> None:
    """One speak.mjs call (always --voice and --instructions, never --language)."""
    txt = out_wav.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    cmd = ["node", str(ctx.media_dir / "speak.mjs"), str(out_wav), "--file", str(txt),
           "--voice", voice_cfg["voice"], "--instructions", voice_cfg["instructions"]]
    proc = run_cmd(cmd, 660, "speak.mjs")
    txt.unlink(missing_ok=True)
    if proc.returncode != 0 or not out_wav.is_file():
        raise RuntimeError((proc.stderr or proc.stdout or "speak.mjs failed").strip()[-400:])


def voice_one_line(ctx: Ctx, index: int, text: str, setup: dict) -> dict:
    lines_dir = ctx.work / "lines"
    wav = lines_dir / f"{index:02d}.wav"
    meta_path = lines_dir / f"{index:02d}.json"
    voice_cfg = setup["voice_cfg"]
    limit = wer_threshold(text)
    ident = {"text": text, "voice": voice_cfg["voice"], "instructions": voice_cfg["instructions"], "model": setup["tts_model"]}

    try:  # reuse a line that already passed with the same text/voice/model (after an earlier failed run)
        cached = json.loads(meta_path.read_text(encoding="utf-8"))
        if wav.is_file() and all(cached.get(k) == v for k, v in ident.items()) and cached.get("ok"):
            cached["reused"] = True
            return cached
    except (OSError, ValueError, KeyError):
        pass

    best = None
    attempts = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        candidate = lines_dir / f"{index:02d}.try{attempt}.wav"
        try:
            speak_once(ctx, text, candidate, voice_cfg)
            heard = transcribe_wav(candidate, setup["asr_model"], ctx.script["language"])
        except RuntimeError as exc:
            attempts.append({"attempt": attempt, "error": str(exc)})
            continue
        wer = word_error_rate(text, heard)
        cer = char_error_rate(text, heard)
        score = line_error_score(wer, cer, limit)
        attempts.append({"attempt": attempt, "wer": round(wer, 4), "cer": round(cer, 4), "heard": heard})
        if best is None or score < best["score"]:
            best = {"wer": wer, "cer": cer, "score": score, "heard": heard, "path": candidate}
        if score <= 1.0:
            break
    result = {**ident, "index": index, "threshold": limit, "words": len(text.split()), "attempts": attempts,
              "attempt_count": len(attempts), "reused": False}
    if best is None:
        last_error = next((a["error"] for a in reversed(attempts) if a.get("error")), "no error text")
        result.update(ok=False, wer=None, heard="", error=f"speak.mjs made no audio in any of {MAX_ATTEMPTS} attempts: {last_error}")
        return result
    shutil.copyfile(best["path"], wav)
    result.update(wer=round(best["wer"], 4), cer=round(best["cer"], 4), cer_limit=CER_LIMIT, heard=best["heard"],
                  ok=best["score"] <= 1.0)
    if result["ok"]:
        meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for leftover in lines_dir.glob(f"{index:02d}.try*.wav"):
        leftover.unlink(missing_ok=True)
    return result


def voice_failure_message(bad: list[dict], max_attempts: int) -> str:
    """Why lines failed. 'No audio at all' (speak.mjs/VoiceStudio broke) is NOT a wording problem."""
    no_audio = [r for r in bad if r.get("wer") is None]
    misheard = [r for r in bad if r.get("wer") is not None]
    parts = []
    if no_audio:
        numbers = ", ".join(str(r["index"]) for r in no_audio)
        parts.append(
            f"VoiceStudio failed to make audio for line(s) {numbers} ({max_attempts} attempts each). "
            "This is not a wording problem: check VoiceStudio (is the app running and the voice engine loaded?), then run again.\n"
            + "\n".join(f"    line {r['index']}: {r.get('error') or 'no error text'}" for r in no_audio)
        )
    if misheard:
        detail = "\n".join(
            f"    line {r['index']}: WER {r.get('wer')} > {r['threshold']}\n      script: {r['text']}\n      heard : {r.get('heard')}"
            for r in misheard
        )
        parts.append(
            f"{len(misheard)} line(s) are still not understood correctly after {max_attempts} attempts. "
            f"Reword them (shorter, simpler words, numbers as words) and run again:\n{detail}"
        )
    return "\n".join(parts)


def step_voice(ctx: Ctx, setup: dict) -> list[dict]:
    ctx.step(3, "Voicing each line and checking it by transcription")
    (ctx.work / "lines").mkdir(parents=True, exist_ok=True)
    results = []
    for index, line in enumerate(ctx.script["lines"]):
        text = line["text"].strip()
        res = voice_one_line(ctx, index, text, setup)
        results.append(res)
        shown = "n/a" if res.get("wer") is None else f"{res['wer']:.2f}"
        letters = "" if res.get("cer") is None else f", letters {res['cer']:.2f} (limit {CER_LIMIT:.2f})"
        tag = "ok" if res.get("ok") else "FAIL"
        extra = " (reused from an earlier run)" if res.get("reused") else f" after {res['attempt_count']} attempt(s)"
        ctx.say(f"  [{tag}] line {index}: WER {shown} (limit {res['threshold']:.2f}){letters}{extra}: {text[:60]}")
    ctx.report["voice"]["lines"] = results
    bad = [r for r in results if not r.get("ok")]
    if bad:
        ctx.checks.append({"name": "voice accuracy", "ok": False, "detail": [r["index"] for r in bad]})
        raise GateError(voice_failure_message(bad, MAX_ATTEMPTS))
    worst = max(r["wer"] for r in results)
    ctx.check("voice accuracy", True, f"all {len(results)} lines inside their WER limit (worst {worst:.2f})")
    return results


def step_join(ctx: Ctx, results: list[dict]) -> tuple[Path, list[dict], float]:
    ctx.step(4, "Joining the lines into one narration")
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    lines_dir = ctx.work / "lines"
    norm_files = []
    durations = []
    for r in results:
        src = lines_dir / f"{r['index']:02d}.wav"
        dst = lines_dir / f"{r['index']:02d}.norm.wav"
        proc = run_cmd([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ar", str(SAMPLE_RATE), "-ac", "1",
                        "-c:a", "pcm_s16le", str(dst)], 120, "ffmpeg (convert line)")
        if proc.returncode != 0:
            raise GateError(f"ffmpeg could not convert line {r['index']}: {proc.stderr.strip()[:300]}")
        norm_files.append(dst)
        durations.append(ffprobe_info(ffprobe, dst)["duration"])
    silence = lines_dir / "silence.wav"
    proc = run_cmd([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono",
                    "-t", str(GAP_SECONDS), "-c:a", "pcm_s16le", str(silence)], 60, "ffmpeg (silence)")
    if proc.returncode != 0:
        raise GateError(f"ffmpeg could not make the gap: {proc.stderr.strip()[:300]}")
    entries = []
    for k, f in enumerate(norm_files):
        if k:
            entries.append(silence)
        entries.append(f)
    listing = ctx.work / "concat.txt"
    listing.write_text("".join("file '{}'\n".format(str(e).replace("'", "'\\''")) for e in entries), encoding="utf-8")
    narration = ctx.work / "narration.wav"
    proc = run_cmd([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(narration)], 300, "ffmpeg (join)")
    if proc.returncode != 0:
        raise GateError(f"ffmpeg could not join the lines: {proc.stderr.strip()[:300]}")
    total = ffprobe_info(ffprobe, narration)["duration"]
    texts = [line["text"].strip() for line in ctx.script["lines"]]
    timings = build_timings(texts, durations)
    (ctx.work / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8")
    ctx.report["timings"] = timings
    ctx.report["narration"] = {"path": str(narration), "duration": round(total, 3), "line_durations": [round(d, 3) for d in durations]}
    ctx.check("narration joined", True, f"{total:.1f} s, {len(texts)} lines, {GAP_SECONDS} s gaps; timings in {ctx.work / 'timings.json'}")
    return narration, timings, total


def step_length(ctx: Ctx, total: float) -> None:
    ctx.step(5, "Length gate")
    words = sum(len(line["text"].split()) for line in ctx.script["lines"])
    ok, message = length_gate(total, words, ctx.args.min_seconds, ctx.args.max_seconds)
    ctx.report["narration"].update(words=words, words_per_second=round(words / total, 3) if total else 0)
    ctx.check("narration length", ok, message)


def snapshot_local_copies() -> set[str]:
    folder = MPT_DIR / "storage" / "local_videos"
    return set(os.listdir(folder)) if folder.is_dir() else set()


def remove_new_local_copies(before: set[str]) -> list[str]:
    """cli.py copies local materials into storage/local_videos as cli-material-*; remove the ones this run made."""
    folder = MPT_DIR / "storage" / "local_videos"
    removed = []
    if folder.is_dir():
        for name in sorted(set(os.listdir(folder)) - before):
            if name.startswith("cli-material-"):
                (folder / name).unlink(missing_ok=True)
                removed.append(str(folder / name))
    return removed


def step_own_footage(ctx: Ctx, timings: list[dict], total: float) -> dict:
    """Choose, download, cut and join the Pixabay clips (studio/footage.py) into work/<id>/broll.mp4."""
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    try:
        key = footage.load_pixabay_key(MPT_DIR / "config.toml")
        if not key:
            raise footage.FootageError("No Pixabay API key is set in MoneyPrinterTurbo/config.toml (under [app], pixabay_api_keys).")
        result = footage.build_broll(ctx.script, timings, total, ctx.work, key, ffmpeg, ffprobe, log=ctx.say)
    except footage.FootageError as exc:
        raise GateError(f"Stock footage: {exc}") from None
    report = result["report"]
    ctx.report["footage"] = {"mode": "own", **report}
    for seg in report["segments"]:
        if seg["fallback"]:
            related = seg.get("fallback_related", True)
            ctx.warn(f"footage: the phrase '{seg['phrase']}' ({seg['start']:.1f}-{seg['end']:.1f} s) found no usable clip, so the video term "
                     f"'{seg['searched_phrase']}' was used instead" + ("" if related else
                     " (a general picture that is NOT about the phrase: choose a phrase Pixabay covers, see the segment list in report.json)"))
    ctx.check("own footage", True,
              f"{len(report['segments'])} picture segments from {report['clips_used']} Pixabay clips ({report['downloads']} downloaded, "
              f"{report['clip_cache_hits']} reused from disk; {report['search_requests']} searches sent, {report['search_cache_hits']} from the 24 h cache) "
              f"-> {result['path']} ({report['broll_seconds']:.2f} s)")
    return result


def run_mpt_task(ctx: Ctx, cmd: list[str], log_path: Path, record: dict) -> tuple[list[str], dict]:
    """Run one MoneyPrinterTurbo cli.py command and return (log lines, its "result" JSON).

    The command and the log go to log_path. `record` is filled with task_id/log/exit_code BEFORE any failure is
    raised, so a failed run still shows up in the partial report. Any trouble (cannot start, timeout, non-zero
    exit, no result JSON) becomes a plain GateError.
    """
    lines: list[str] = []
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    with open(log_path, "w", encoding="utf-8", buffering=1) as log:
        log.write("# " + " ".join(shlex.quote(c) for c in cmd) + "\n")
        last_ping = time.time()

        def on_line(raw: str) -> None:
            nonlocal last_ping
            line = strip_ansi(raw)
            lines.append(line)
            log.write(line + "\n")
            if time.time() - last_ping > 30:
                ctx.say(f"    ... MPT working: {line[:110]}")
                last_ping = time.time()

        try:
            code, timed_out = run_streaming(cmd, MPT_DIR, env, MPT_TIMEOUT_SECONDS, on_line)
        except OSError as exc:
            raise GateError(f"MoneyPrinterTurbo could not be started: {exc}")
    record.update(log=str(log_path), exit_code=code)
    if timed_out:
        raise GateError(f"MoneyPrinterTurbo did not finish within {MPT_TIMEOUT_SECONDS // 60} minutes, so it and everything it started was stopped. "
                        f"Full log: {log_path}")
    if code != 0:
        tail = "\n    ".join(l for l in lines[-12:] if l.strip())
        raise GateError(f"MoneyPrinterTurbo failed (exit code {code}). Last log lines:\n    {tail}\n  Full log: {log_path}")
    parsed = parse_mpt_result(lines)
    if parsed is None:
        raise GateError(f"MoneyPrinterTurbo finished but printed no result JSON. See {log_path}")
    return lines, parsed["result"]


def step_whisper_timing(ctx: Ctx, narration: Path, setup: dict, script_text: str, script_texts: list[str]) -> dict:
    """MoneyPrinterTurbo with --stop-at subtitle: Whisper hears our narration and writes one cue per word.

    Only the TIMING of these cues is used for the captions (their spelling is sometimes wrong). The word error
    rate against the script stays a gate as a signal for the quality of the VOICE.
    """
    ctx.say("  a) Whisper timing: MoneyPrinterTurbo --stop-at subtitle (no footage, no video)")
    caption = setup["caption"]
    task_id = str(uuid.uuid4())
    cmd = build_mpt_command(find_tool("uv"), script_text, ctx.script["video_terms"], narration.resolve(), task_id,
                            font_size=caption["font_size"], stroke_width=caption["stroke_width"],
                            position_percent=caption["position_percent"], stop_at="subtitle")
    log_path = ctx.work / "mpt-subtitles.log"
    task_dir = MPT_DIR / "storage" / "tasks" / task_id
    ctx.say(f"    task id {task_id}; log: {log_path}")
    record: dict = {"task_id": task_id}
    ctx.report["mpt"] = {"subtitle_run": record}
    lines, result = run_mpt_task(ctx, cmd, log_path, record)
    log_text = "\n".join(lines)
    subtitle_path = result.get("subtitle_path")
    record["subtitle_path"] = subtitle_path
    ctx.check("MPT subtitle path", bool(subtitle_path) and Path(subtitle_path).is_file(),
              f"{subtitle_path or 'none'} (the Whisper run must write a subtitle file)")
    ok, detail = check_whisper_language(log_text, ctx.script["language"])
    ctx.check("whisper language", ok, detail)

    cues = parse_srt(Path(subtitle_path).read_text(encoding="utf-8"))
    sub_ok, sub_wer, sub_detail, sub_diffs = check_srt_accuracy(cues, script_texts)
    raw_problems = srt_problems(cues)  # information only: the captions are rebuilt from the script, these cannot reach the screen
    ctx.report["srt"] = {"cues": len(cues), "wer": round(sub_wer, 4), "wer_limit": SRT_WER_LIMIT, "differences": sub_diffs,
                         "whisper_timing_problems": raw_problems}
    ctx.check("whisper vs script", sub_ok, sub_detail)
    detected = detect_whisper_language(log_text) or (None, None)
    ctx.report["mpt"].update(notes=collect_mpt_notes(log_text), whisper={"language": detected[0], "probability": detected[1]})
    return {"cues": cues, "subtitle_path": Path(subtitle_path), "task_dir": task_dir, "task_id": task_id,
            "log_text": log_text, "differences": sub_diffs, "wer": sub_wer}


def step_captions(ctx: Ctx, whisper: dict, setup: dict, total: float) -> dict:
    """One caption per SCRIPT word (exactly as written), timed from Whisper's cues (studio/captions.py).

    Gates: "captions match script" (fatal: the words that will be drawn ARE the script's words), the timing rules
    of captions.caption_problems (fatal), the first caption near the start (a warning).
    """
    ctx.say("  b) Captions: the script's words with Whisper's timing")
    texts = [line["text"].strip() for line in ctx.script["lines"]]
    try:
        words = captionlib.align_words(whisper["cues"], texts, end_limit=total)
    except captionlib.CaptionError as exc:
        raise GateError(f"Could not build the captions from the script and Whisper's timing: {exc}") from None
    ok, detail = captionlib.captions_match_script([w["text"] for w in words], texts)
    ctx.check("captions match script", ok, detail)
    stats = captionlib.alignment_stats(words)
    ctx.say(f"    timing: {stats['heard']} words have their own Whisper time, {stats['spread']} share a block of time, "
            f"{stats['interpolated']} were placed between their neighbours")
    guessed = captionlib.guessed_warning(stats)
    if guessed:
        ctx.warn(guessed)
    problems = captionlib.caption_problems(words, total)
    ctx.check("caption timing", not problems,
              f"{len(words)} caption words, in order, none overlapping, each at least {captionlib.MIN_WORD_SECONDS:g} s, "
              f"all inside the {total:.1f} s narration" if not problems else "; ".join(problems[:6]))
    late = first_caption_problem(words)
    if late:
        ctx.warn(late)
    else:
        ctx.check("captions from the start", True, f"first caption at {words[0]['start']:.2f} s")
    note = fixed_in_captions_note(whisper["differences"])
    if note:
        ctx.say(f"  {note}")
    phrases = captionlib.group_phrases(words, end_limit=total)
    style = setup["caption"]
    ctx.report["captions"].update(
        renderer="Remotion composition WordCaptions (our own captions: the script's words, Whisper's timing)",
        script_words=len(words), alignment=stats, fixed_in_captions=whisper["differences"], phrases=len(phrases),
    )
    return {"words": words, "phrases": phrases, "stats": stats,
            "style": {"font_size": style["font_size"], "stroke_width": style["stroke_width"], "box_height": style["box_height"]}}


def step_mpt(ctx: Ctx, narration: Path, setup: dict, timings: list[dict] | None = None, total: float | None = None) -> dict:
    ctx.step(6, "Whisper timing, captions from the script, stock footage and the MoneyPrinterTurbo video (no captions)")
    script_texts = [line["text"].strip() for line in ctx.script["lines"]]
    script_text = mpt_script_text(script_texts)
    if total is None:
        raise GateError("The captions need the narration length (internal error: step_mpt was called without it).")

    whisper = step_whisper_timing(ctx, narration, setup, script_text, script_texts)
    captions = step_captions(ctx, whisper, setup, total)

    broll = None
    if setup.get("footage") == "own":
        if timings is None:
            raise GateError("Own footage needs the narration timings (internal error: step_mpt was called without them).")
        broll = step_own_footage(ctx, timings, total)
    local_files = [broll["path"].resolve()] if broll else setup["local_files"]

    ctx.say("  d) MoneyPrinterTurbo video WITHOUT captions (our captions are drawn in step 7)")
    task_id = str(uuid.uuid4())
    cmd = build_mpt_command(find_tool("uv"), script_text, ctx.script["video_terms"], narration.resolve(), task_id, local_files,
                            source=setup.get("source"), burn_captions=False,
                            fixed_order_seconds=math.ceil(total) + OWN_FOOTAGE_EXTRA_SECONDS if broll else None)
    log_path = ctx.work / "mpt.log"
    task_dir = MPT_DIR / "storage" / "tasks" / task_id
    ctx.say(f"    task id {task_id}; log: {log_path}")
    before = snapshot_local_copies()
    ctx.report["mpt"].update(task_id=task_id, script_text=script_text)  # keeps the "subtitle_run" entry of the Whisper run
    try:
        lines, result = run_mpt_task(ctx, cmd, log_path, ctx.report["mpt"])
    finally:
        ctx.removed_early += remove_new_local_copies(before)
    log_text = "\n".join(lines)
    notes = collect_mpt_notes(log_text) + (ctx.report["mpt"].get("notes") or [])

    mpt_warnings = result.get("warnings")
    ctx.check("MPT result warnings", not mpt_warnings, "none" if not mpt_warnings else f"MPT reported warnings: {mpt_warnings}")

    saved_params = None
    try:
        saved_params = json.loads((task_dir / "script.json").read_text(encoding="utf-8")).get("params")
    except (OSError, ValueError):
        ctx.warn("could not read MPT's saved task params to double-check the no-music and no-captions settings")
    bgm = find_bgm_usage(log_text + "\n" + whisper["log_text"], saved_params)
    ctx.check("no background music", not bgm, "MPT mixed no music" if not bgm else "; ".join(bgm))

    burned = find_burned_captions(log_text, result, saved_params)
    ctx.check("no burned-in captions", not burned,
              "MPT's video has no captions (ours are added in step 7)" if not burned else "; ".join(burned))

    videos = result.get("videos") or []
    video = Path(videos[0]) if videos else None
    ctx.check("MPT video", bool(video) and video.is_file(), f"{video}" if video else "MPT returned no video file")
    if broll:
        check_footage_order(ctx, video, broll)
    ctx.report["mpt"].update(
        notes=notes, video=str(video), warnings=mpt_warnings or [],
        audio_duration=result.get("audio_duration"), materials=result.get("materials"),
    )
    if notes:
        ctx.say(f"  {len(notes)} subtitle alignment note(s) recorded in the report")
    return {"video": video, "task_dir": task_dir, "task_id": task_id, "broll": broll, "captions": captions,
            "extra_task_dirs": [whisper["task_dir"]]}


def check_footage_order(ctx: Ctx, video: Path, broll: dict) -> None:
    """MPT must play our B-roll once, in our order (no shuffling, no looping): compare MPT's picture with broll.mp4
    in the middle of every segment. A different picture means MPT did not keep the order, and the video is wrong."""
    try:
        results = footage.check_order(find_tool("ffmpeg"), video, broll["path"], footage.middle_times(broll["segments"]), ORDER_CHECK_LIMIT)
    except footage.FootageError as exc:
        raise GateError(f"Could not compare MPT's video with the B-roll: {exc}") from None
    bad = [r for r in results if not r["same"]]
    ctx.report["footage"]["order_check"] = {"limit": ORDER_CHECK_LIMIT, "frames": results}
    worst = max(r["diff"] for r in results)
    detail = (f"MPT's picture matches our B-roll at all {len(results)} checked seconds (largest grey difference {worst:.1f} of {ORDER_CHECK_LIMIT:g})"
              if not bad else
              f"MPT's picture differs from our B-roll at {len(bad)} of {len(results)} checked seconds "
              f"({', '.join(f'{r['seconds']:g} s: {r['diff']:.0f}' for r in bad[:6])}; limit {ORDER_CHECK_LIMIT:g}). "
              "MoneyPrinterTurbo shuffled, looped or re-timed the footage; see mpt.log")
    ctx.check("footage order kept", not bad, detail)


def step_visuals(ctx: Ctx, mpt: dict, timings: list[dict]) -> Path:
    """Captions (always) and diagram panels (unless --no-visuals): Remotion draws them, ONE ffmpeg pass puts them on the video."""
    ctx.step(7, "Captions and diagram overlays")
    needed = [k for k, line in enumerate(ctx.script["lines"]) if line.get("visual")]
    panels_off = ctx.args.no_visuals or not needed
    script = ctx.script
    if panels_off:
        why = "--no-visuals" if ctx.args.no_visuals else "no line has a visual"
        script = {**ctx.script, "lines": [{**line, "visual": None} for line in ctx.script["lines"]]}
    module = load_visuals_module(needed)
    caption_data = mpt["captions"]
    style = caption_data["style"]
    caption_args = {
        "words": [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in caption_data["words"]],
        "font_size": style["font_size"], "stroke_width": style["stroke_width"], "box_height": style["box_height"],
        "text_color": SUBTITLE_TEXT_COLOR, "stroke_color": SUBTITLE_STROKE_COLOR,
    }
    ok, detail = captionlib.captions_match_script([w["text"] for w in caption_args["words"]], [line["text"].strip() for line in ctx.script["lines"]])
    ctx.check("captions match script (as drawn)", ok, detail)  # what is handed to Remotion, one last time
    out = ctx.work / "final-visuals.mp4"
    work_dir = ctx.work / "visuals"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        info = module.render_and_overlay(str(mpt["video"]), script, timings, str(out), str(work_dir), captions=caption_args)
    except Exception as exc:  # the overlay code is another module: report any crash plainly
        raise GateError(f"visuals.render_and_overlay failed: {type(exc).__name__}: {exc}")
    if not out.is_file():
        raise GateError(f"visuals.render_and_overlay returned but {out} was not written.")
    ctx.report["visuals"] = info if isinstance(info, dict) else {"result": str(info)}
    if panels_off:
        ctx.report["visuals"]["skipped"] = why
    panels = len(needed) if not panels_off else 0
    ctx.check("visuals", True, f"{len(caption_data['words'])} caption words" + (f" and {panels} visual line(s)" if panels else "") +
              f" rendered onto the video in one ffmpeg pass -> {out}")
    return out


def step_final_checks(ctx: Ctx, final_video: Path, mpt: dict, total: float) -> Path:
    ctx.step(8, "Final checks and contact sheet")
    ffprobe = find_tool("ffprobe")
    info = ffprobe_info(ffprobe, final_video)
    for name, ok, detail in check_final_info(info, ctx.args.min_seconds):
        ctx.check(name, ok, detail)
    if abs(info["duration"] - total) > 1.5:
        ctx.warn(f"final video ({info['duration']:.1f} s) differs from the narration ({total:.1f} s) by more than 1.5 s")
    words = mpt["captions"]["words"]
    problems = captionlib.caption_problems(words, total)
    ctx.check("subtitle timing", not problems,
              f"{len(words)} caption words, none overlapping or out of order, all inside the narration" if not problems else "; ".join(problems[:6]))
    mpt_video_duration = info["duration"] if mpt["video"] == final_video else ffprobe_info(ffprobe, mpt["video"])["duration"]
    ctx.report["durations"] = {"narration": round(total, 3), "mpt_video": round(mpt_video_duration, 3), "final": round(info["duration"], 3)}
    ctx.report["captions"]["timing_problems"] = problems
    sheet = ctx.work / "sheet.png"
    proc = run_cmd(["node", str(ctx.media_dir / "media.mjs"), "sheet", str(final_video), str(sheet)], 300, "media.mjs sheet")
    if proc.returncode != 0 or not sheet.is_file():
        raise GateError(f"Contact sheet failed: {(proc.stderr or proc.stdout).strip()[-300:]} (browser missing? run /media-studio:setup)")
    ctx.check("contact sheet", True, str(sheet))
    return sheet


def step_credits(ctx: Ctx, mpt: dict, local: bool) -> list[str]:
    ctx.step(9, "Credits")
    if mpt.get("broll"):  # own footage: we know exactly which clips are in the video
        lines = list(mpt["broll"]["credit_lines"])
        notes = [f"credited exactly the {len(lines)} Pixabay clip(s) cut into the video (chosen by studio/footage.py)"]
        ctx.check("credits", bool(lines), f"{len(lines)} credit line(s), one per clip used")
        for n in notes:
            ctx.say(f"  note: {n}")
        ctx.report["credits"] = {"lines": lines, "notes": notes}
        return lines
    if local:
        ctx.check("credits", True, "local materials: no credits needed")
        ctx.report["credits"] = {"lines": [], "notes": ["local materials: no credits"]}
        return []
    try:
        records = json.loads((mpt["task_dir"] / "script.json").read_text(encoding="utf-8")).get("material_sources") or []
    except (OSError, ValueError) as exc:
        raise GateError(f"Could not read MPT's clip records ({mpt['task_dir'] / 'script.json'}): {exc}. Credits cannot be built.")
    lines, notes = build_credits(records)
    if not lines:
        raise GateError("MPT recorded no downloaded clips, so there are no credits to write. Check mpt.log.")
    notes.append(f"credited all {len(records)} clip(s) MPT downloaded (MPT does not record which of them reached the final cut)")
    ctx.check("credits", True, f"{len(lines)} credit line(s) from {len(records)} downloaded clip(s)")
    for n in notes:
        ctx.say(f"  note: {n}")
    ctx.report["credits"] = {"lines": lines, "notes": notes}
    return lines


def write_report(ctx: Ctx, path: Path, ok: bool, error: str | None = None) -> None:
    report = {
        "ok": ok,
        "error": error,
        "script_id": ctx.script.get("id"),
        "language": ctx.script.get("language"),
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "seconds_taken": round(time.time() - ctx.started),
        "settings": {"min_seconds": ctx.args.min_seconds, "max_seconds": ctx.args.max_seconds, "stage": ctx.args.stage,
                     "no_visuals": ctx.args.no_visuals, "local_materials": bool(ctx.args.local_materials),
                     "footage": ctx.args.footage},
        "checks": ctx.checks,
        "warnings": ctx.warnings,
        **ctx.report,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def step_output(ctx: Ctx, final_video: Path, sheet: Path, credits: list[str], mpt: dict) -> Path:
    ctx.step(10, "Writing the review folder")
    folder = REVIEW_ROOT / review_folder_name(ctx.script, datetime.date.today())
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(final_video, folder / "final.mp4")
    captions = mpt["captions"]
    # YouTube accepts SRT uploads: the CORRECTED captions (the script's words) as readable phrases, not Whisper's raw words
    (folder / "subtitles.srt").write_text(format_srt(captions["phrases"]), encoding="utf-8")
    (folder / "captions-words.json").write_text(json.dumps(captions["words"], ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(sheet, folder / "sheet.png")
    (folder / "caption.txt").write_text(build_caption(ctx.script, credits), encoding="utf-8")
    # From here on the report points at the kept copies, not at the temporary files that cleanup deletes.
    kept = {
        str(final_video): str(folder / "final.mp4"),
        str(sheet): str(folder / "sheet.png"),
    }
    ctx.report = repoint_paths(ctx.report, kept)
    ctx.checks = replace_in_strings(ctx.checks, kept)  # also the paths written inside the check sentences
    ctx.report["outputs"] = {
        "review_dir": str(folder),
        "final": str(folder / "final.mp4"),
        "subtitles": str(folder / "subtitles.srt"),
        "captions_words": str(folder / "captions-words.json"),
        "sheet": str(folder / "sheet.png"),
        "caption": str(folder / "caption.txt"),
        "report": str(folder / "report.json"),
    }
    write_report(ctx, folder / "report.json", ok=True)
    ctx.say(f"  wrote {folder}/ (final.mp4, subtitles.srt, captions-words.json, sheet.png, caption.txt, report.json)")
    return folder


def step_cleanup(ctx: Ctx, mpt: dict, folder: Path) -> None:
    ctx.step(11, "Cleanup")
    report_path = folder / "report.json"
    if ctx.args.keep_work:
        ctx.say(f"  --keep-work: leaving {ctx.work} and MPT's task folder in place")
        ctx.report = drop_deleted_paths(ctx.report, ctx.removed_early)
        ctx.checks = mark_deleted_in_strings(ctx.checks, ctx.removed_early)
        ctx.report["cleanup"] = {"performed": False, "reason": "--keep-work", "removed": list(ctx.removed_early)}
        write_report(ctx, report_path, ok=True)
        return
    removed: list[str] = list(ctx.removed_early)
    for task_dir in [mpt["task_dir"], *mpt.get("extra_task_dirs", [])]:  # the video run and the Whisper timing run
        if task_dir.parent == MPT_DIR / "storage" / "tasks" and task_dir.is_dir():
            shutil.rmtree(task_dir, ignore_errors=True)
            removed.append(str(task_dir))
    for item in sorted(ctx.work.iterdir()):
        if item.name in KEPT_WORK_FILES:
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
        removed.append(str(item))
    # No path in the report may point at something that no longer exists.
    ctx.report = drop_deleted_paths(ctx.report, removed)
    ctx.checks = mark_deleted_in_strings(ctx.checks, removed)
    ctx.report["cleanup"] = {
        "performed": True,
        "removed": removed,
        "kept": [*(str(ctx.work / name) for name in KEPT_WORK_FILES if (ctx.work / name).exists()), str(folder)],
        "note": "paths in this report that pointed at removed files are null (or left out of lists); the review folder keeps final.mp4, subtitles.srt, captions-words.json, sheet.png, caption.txt. "
                "In the sentences of checks[].detail a removed file is shown as '<file name> (deleted after the run)'",
    }
    write_report(ctx, report_path, ok=True)
    ctx.say(f"  removed MPT's task folders and the big files in {ctx.work} (kept timings.json and the MPT logs); list recorded in report.json")


def fail(ctx: Ctx, headline: str, message: str, extra: dict | None = None) -> int:
    """Print the failure in plain English and, once the script id is known, write work/<id>/failed-report.json."""
    message = footage.mask_secret(message)  # belt and braces: an API key in a URL must never reach the screen or a file
    print(f"\n{headline}: {message}", file=sys.stderr, flush=True)
    if ctx.script.get("id"):
        failed = ctx.work / "failed-report.json"
        try:
            ctx.report.update({k: footage.mask_secret(v) if isinstance(v, str) else v for k, v in (extra or {}).items()})
            write_report(ctx, failed, ok=False, error=message)
            print(f"(partial report: {failed}; work files kept in {ctx.work})", file=sys.stderr)
        except OSError:
            pass
    return 1


def run(args: argparse.Namespace) -> int:
    ctx = Ctx(args)
    try:
        step_validate(ctx)
        setup = step_preflight(ctx)
        results = step_voice(ctx, setup)
        narration, timings, total = step_join(ctx, results)
        step_length(ctx, total)
        if args.stage == "voice":
            ctx.say(f"\nStage 'voice' done. Narration: {narration} ({total:.1f} s). Timings: {ctx.work / 'timings.json'}")
            return 0
        mpt = step_mpt(ctx, narration, setup, timings, total)
        final_video = step_visuals(ctx, mpt, timings)
        sheet = step_final_checks(ctx, final_video, mpt, total)
        credits = step_credits(ctx, mpt, local=bool(setup["local_files"]))
        folder = step_output(ctx, final_video, sheet, credits, mpt)
        step_cleanup(ctx, mpt, folder)
        ctx.say(f"\nDONE in {time.time() - ctx.started:.0f} s. Review: {folder}")
        for w in ctx.warnings:
            ctx.say(f"  warning: {w}")
        return 0
    except GateError as exc:
        return fail(ctx, "FAILED", str(exc))
    except Exception as exc:  # a bug or something nobody planned for: still no raw traceback for the user
        return fail(
            ctx, "FAILED (unexpected)",
            f"{type(exc).__name__}: {exc}. This is a problem in the tool itself, not in your script. "
            "The technical details are in the failed-report.json mentioned below; send them to whoever maintains make_video.py.",
            extra={"traceback": traceback.format_exc()},
        )


def main(argv=None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
