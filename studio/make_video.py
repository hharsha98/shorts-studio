#!/usr/bin/env python3
"""make_video.py - turn content/<id>/script.json into a review-ready YouTube Short.

Usage (from /Users/harsha/shorts-studio):
    python3 studio/make_video.py content/<id>/script.json [--local-materials DIR]
        [--min-seconds 45] [--max-seconds 75] [--keep-work] [--no-visuals]
        [--stage voice|all] [--footage auto|own|mpt] [--voice-seed N] [--no-voice-cache]

What it does, in order (every gate fails LOUDLY: non-zero exit + a plain-English message):
     1. validate script.json against the contract
     2. preflight (VoiceStudio health + transcription engine; for a language that VoiceStudio speaks, its TTS engine too; for a
        language with its own "engine_url" in studio/voices.json (German: voice-de/run.sh start, English: voice-en/run.sh start) that engine's /health; tools,
        MoneyPrinterTurbo config)
     3. voice the WHOLE script in ONE VoiceStudio request (studio/voice_take.py), find the line boundaries in the take,
        shorten pauses over 0.45 s to 0.35 s, check every line by transcription (word/letter error rate; a number Whisper
        writes as digits equals the spoken number word, see studio/number_words.py), patch a failed line alone, and
        accept the take only if pitch and loudness are steady from line to line and close to the channel's reference
        voice (a take that is not steady is re-rolled with the next seed, up to 6 times; an engine marked "deterministic" in
        voices.json makes ONE take: a failing line is reported to be reworded, nothing is re-rolled or patched)
     4. write work/<id>/narration.wav + work/<id>/timings.json (first/last sound of every line)
     5. length gate (default 45-75 s)           <- --stage voice stops here
     6. captions and video:
        a. MoneyPrinterTurbo (MPT) runs once with --stop-at subtitle: Whisper hears the narration and writes one cue
           per word (the TIMING; its spelling is sometimes wrong). Word error rate gate: a voice-quality signal
           (numbers compared as one <num>, like the per-line check).
        b. studio/captions.py aligns those cues with the SCRIPT: one caption per script word, spelled exactly as in
           the script, timed from Whisper. Gate "captions match script".
        c. stock footage: studio/footage.py picks one Pixabay clip per script line (lines[].broll), cuts them to
           1080x1920 and joins them into work/<id>/broll.mp4 (--footage own, the default when a Pixabay key is set;
           --footage mpt lets MoneyPrinterTurbo search by itself)
        d. MPT builds the video from our B-roll and the narration WITHOUT captions (--no-subtitle-enabled)
     7. Remotion draws the captions (ONE word at a time, white with black outline, pop animation, top edge at y=1300:
        below the diagram panels, above the YouTube Shorts title/channel overlay), the hook card (script "hook": two big
        lines in the top third, on screen from frame 0 until the end of line 0 (2.5 to 3.5 s), then a 0.25 s fade; the
        captions are hidden while it is up) and, unless --no-visuals, the diagram panels; studio/visuals.py puts all of
        them on the video in ONE ffmpeg pass. Last, the audio is finished: high-pass, gentle compressor and two-pass
        loudnorm to -14 LUFS / -1.5 dBTP (video stream copied), then measured
     8. final checks (duration, 1080x1920, audio, caption timing, hook visible at 0 s) + contact sheet + cover.jpg (frame 0.0 s)
     9. credits for the stock footage that was really used (own footage: exactly the clips in the video)
    10. review/<date>-<language>-<slug>/ : final.mp4, cover.jpg (the first frame, for the TikTok/Instagram/YouTube cover),
        subtitles.srt (the corrected captions as readable phrases), captions-words.json (the per-word captions), sheet.png,
        caption.txt, report.json
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
import voice_take  # noqa: E402  (studio/voice_take.py: the whole script in one take, steadiness gate, patching, cache)
from captions import normalize_words  # noqa: E402,F401  (one normalisation for the WER and the caption alignment)
import number_words  # noqa: E402  (studio/number_words.py: "thirty" and "30" are the same <num> in the VOICE checks, nowhere else)
MPT_DIR = ROOT / "MoneyPrinterTurbo"
VOICES_FILE = STUDIO_DIR / "voices.json"
WORK_ROOT = ROOT / "work"
REVIEW_ROOT = ROOT / "review"

VOICESTUDIO_URL = os.environ.get("VOICESTUDIO_URL", "http://127.0.0.1:3900").rstrip("/")
REQUIRED_TTS_ENGINE = "mlx-audio"
REQUIRED_TTS_MODEL = "Qwen3-TTS-12Hz-1.7B-CustomVoice"
# A language with its own speech engine (studio/voices.json "engine_url") is started with its "start_hint", default voice-<language>/run.sh start
LANGUAGE_NAMES = {"en": "English", "de": "German"}

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
CAPTION_BASE_PERCENTILE = 0.9  # the base size fits the word that is wider than 90% of all words; the wider 10% get their OWN smaller size
HOOK_MAX_WIDTH_PX = 1000  # the widest hook line plus its outline must fit into this
HOOK_FONT_MAX = 132
HOOK_FONT_TARGET = 96  # big enough to be read in a glance; below this the hook still shows but gets a warning
HOOK_FONT_MIN = 64  # below this the card would be too small to work as a hook: the run stops and says which line to shorten
HOOK_STROKE_SHARE = 0.095  # outline width as a share of the font size (the dark outline that keeps white letters readable on any footage)
HOOK_BAND_CROP = "crop=1080:450:0:250"  # where the hook card sits (studio/visuals.py HOOK_Y/HOOK_H; a unit test keeps them equal)
HOOK_SEEN_LIMIT = 6.0  # mean grey difference (0-255) between the finished video and the footage underneath it inside that band:
#                        re-encoding noise is below 3, a card full of white letters with a dark outline is far above this
TITLE_MAX = 70  # YouTube title: longer titles are cut off in the Shorts feed
PINNED_COMMENT_MAX = 150  # TikTok comments are limited to 150 characters
COVER_QUALITY = "3"  # ffmpeg -q:v for the cover JPEG (2 = best ... 31 = worst); 3 is about JPEG quality 90
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
    _check_text(data.get("title"), "title", errors, TITLE_MAX)

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

    if data.get("hook") is not None:
        errors.extend(captionlib.hook_problems(data["hook"]))
        if isinstance(lines, list) and lines and isinstance(lines[0], dict) and lines[0].get("visual"):
            errors.append("lines[0].visual must be empty when the script has a hook: the hook card is on screen over the first seconds "
                          "and no diagram panel may start before it is done and faded out (put the visual on a later line)")
    topic_noun = data.get("topic_noun")
    if topic_noun is not None:
        validate_broll(topic_noun, "topic_noun", errors, warnings)
    pinned = data.get("pinned_comment")
    if pinned is not None:
        _check_text(pinned, "pinned_comment", errors, PINNED_COMMENT_MAX)

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


# The four helpers below split the texts into words with `words`. The default is the caption normalisation; the voice-quality
# checks (grade_line, check_srt_accuracy) pass number_words.spoken_words, which also turns every run of number tokens
# ("thirty", "30", "20,000", "40", "siebenundsiebzig") into one "<num>" on both sides: the voice said the number, Whisper
# only wrote it with digits (the unit next to it stays a word, in one standard spelling). Captions never use that, they show
# the script's own words.


def word_error_rate(reference: str, hypothesis: str, words=normalize_words) -> float:
    ref = words(reference)
    hyp = words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def wer_threshold(reference: str, words=normalize_words) -> float:
    """The word-error limit of a line: the long-line limit from 5 words on. grade_line counts the words of the script line as it
    is written (normalize_words), NOT after the numbers are collapsed: a line must not get the lenient short-line limit
    only because "two thousand" became one <num>."""
    return WER_LIMIT_LONG if len(words(reference)) >= 5 else WER_LIMIT_SHORT


def char_error_rate(reference: str, hypothesis: str, words=normalize_words) -> float:
    """Edit distance over the letters only (spaces, dashes and punctuation removed), so spelling variants such as
    'non-stop'/'nonstop', 'ear cup'/'earcup' or 'zu grattern'/'Zugrattern' count as equal. A real mishearing
    ('Noise Cancelling' heard as 'Neuskänzeling') still changes letters."""
    ref = "".join(words(reference))
    hyp = "".join(words(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(list(ref), list(hyp)) / len(ref)


def line_error_score(wer: float, cer: float, wer_limit: float) -> float:
    """<= 1.0 means the line passes: either the word check or the letter check is inside its limit."""
    return min(wer / wer_limit, cer / CER_LIMIT)


def grade_line(text: str, heard: str) -> dict:
    """The per-line voice check: the line passes when its word error rate OR its letter error rate is inside its limit.
    Numbers are compared as one "<num>" per run on both sides (studio/number_words.py), so "twenty thousand" heard as "20,000"
    is not an error; the unit next to a number stays a word (km vs kilometers is the same, seconds vs minutes is not).
    studio/voice_take.py calls this on every line it cuts out of the take and on every patch candidate."""
    words = number_words.spoken_words
    limit = wer_threshold(text)  # the band comes from the written words, the error rates from the collapsed ones
    wer, cer = word_error_rate(text, heard, words), char_error_rate(text, heard, words)
    score = line_error_score(wer, cer, limit)
    return {"wer": round(wer, 4), "cer": round(cer, 4), "threshold": limit, "cer_limit": CER_LIMIT, "score": round(score, 4),
            "ok": score <= 1.0, "words": len(text.split())}


def voice_accuracy_detail(lines: list[dict], patched: int = 0) -> str:
    """The sentence of the 'voice accuracy' check. A line passes on its combined word/letter score (grade_line), so a line can
    have more word errors than its word limit and still pass because its letter errors are small. Say so plainly: the report
    must not read "all inside their WER limit (worst 0.31)" when the limit is 0.15. Lines that passed that way are named so a
    person can listen to them before upload."""
    worst = max(g["wer"] for g in lines)
    text = f"all {len(lines)} lines pass the voice check (combined word/letter score; worst word error {worst:.2f})"
    close = [g["index"] for g in lines if g["wer"] > g["threshold"]]
    if close:
        text += (f"; line(s) {', '.join(str(i) for i in close)} have more word errors than the word limit and pass only because "
                 f"their letter errors are small: listen to them before upload")
    if patched:
        text += f"; {patched} line(s) patched"
    return text


def word_differences(reference: str, hypothesis: str, limit: int = 30, words=normalize_words) -> list[str]:
    """Plain-English list of where the two texts differ (after the same normalisation as the WER)."""
    ref = words(reference)
    hyp = words(hypothesis)
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
# 4/5. Length gate (pure; the line timings come out of studio/voice_take.py)
# --------------------------------------------------------------------------------------


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
    studio/captions.py), but the listener does. Numbers count as one "<num>" per run on both sides (studio/number_words.py):
    Whisper writes "20,000" where the script says "twenty thousand", and the voice said it right. Returns (ok, wer, message,
    differing words).
    """
    reference = " ".join(script_texts)
    heard = " ".join(c["text"] for c in cues)
    words = number_words.spoken_words
    wer = word_error_rate(reference, heard, words)
    diffs = word_differences(reference, heard, words=words)
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


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile: the smallest value that is at least as big as `share` of all the values (0 for an empty list)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))]


def measure_texts(texts: list[str], font_path: Path) -> tuple[dict, object, str | None]:
    """({text: width in em (a font size of 1 px)}, line_height(size) function, note). Without a readable font: a safe over-estimate."""
    try:
        measure = FontMeasure(font_path.read_bytes())
        return {t: measure.text_width(t, 1000) / 1000 for t in texts}, measure.line_height, None
    except (OSError, ValueError, KeyError, struct.error) as exc:
        return ({t: 0.65 * len(t) for t in texts}, lambda size: math.ceil(1.35 * size),  # noqa: E731
                f"font file could not be measured ({exc}); used a safe estimate")


def pick_caption_style(texts: list[str], font_path: Path) -> dict:
    """The caption size of THIS script: a base size for most words and a smaller size of their own for the few wider ones.

    Base size = the biggest size (<= CAPTION_FONT_MAX) at which the word that is wider than 90% of all the script's words
    (CAPTION_BASE_PERCENTILE, counted word by word as the viewer sees them) still fits. A word that is wider than the limit
    at that size gets its own smaller size (`word_sizes`, never below CAPTION_FONT_MIN): ONE long word never shrinks the
    whole video. MPT wrapped (cut a word in two) above 90% of the frame width = 972 px, and the pop animation
    overshoots to about 112%, so CAPTION_MAX_WORD_PX leaves room for both.
    """
    units = captionlib.script_units(texts)  # one caption word each, exactly as drawn
    per_px, height_of, note = measure_texts(sorted(set(units)), font_path)
    p90 = percentile([per_px[u] for u in units], CAPTION_BASE_PERCENTILE)
    fit = math.floor(CAPTION_MAX_WORD_PX / p90) if p90 else CAPTION_FONT_MAX
    size = max(CAPTION_FONT_MIN, min(CAPTION_FONT_MAX, fit))
    word_sizes = {}
    for unit, em in per_px.items():
        if em * size > CAPTION_MAX_WORD_PX:
            own = max(CAPTION_FONT_MIN, math.floor(CAPTION_MAX_WORD_PX / em))
            if own < size:
                word_sizes[unit] = own
    drawn_px = {unit: em * word_sizes.get(unit, size) for unit, em in per_px.items()}  # width of every word as it will be drawn
    widest = max(drawn_px, key=drawn_px.get) if drawn_px else ""
    stroke = caption_stroke_width(size)
    box_height = caption_box_height(size, stroke, height_of(size))
    percent = caption_position_percent(box_height)
    style = {
        "font": SUBTITLE_FONT, "font_size": size, "stroke_width": stroke,
        "widest_word": widest, "widest_word_px": round(drawn_px.get(widest, 0.0)),
        "p90_word_px": round(p90 * size), "base_percentile": CAPTION_BASE_PERCENTILE,
        "word_sizes": dict(sorted(word_sizes.items())),
        "box_height": box_height, "position_percent": percent, "box_top_y": caption_box_top_y(box_height, percent),
        "size_limited_by_word": fit < CAPTION_FONT_MAX,
    }
    if note:
        style["note"] = note
    return style


def caption_word_problem(caption: dict) -> str | None:
    """None when every word fits on one caption line (at its own size); else a plain message (the word would be cut in two)."""
    if caption["widest_word_px"] <= CAPTION_MAX_WORD_PX:
        return None
    return (
        f"The word {caption['widest_word']!r} is too long to show as one caption: it is about {caption['widest_word_px']} px wide "
        f"even at the smallest caption size ({CAPTION_FONT_MIN} px), and the limit is {CAPTION_MAX_WORD_PX} px, so it would be cut in two "
        "on screen. Split or hyphenate it in the script (for example 'Lebensmittel-Verschwendung'), or use a shorter word."
    )


def caption_size_summary(caption: dict) -> str:
    """One sentence for the check line: base size, how many words have their own size, the widest word."""
    own = caption.get("word_sizes") or {}
    shrunk = (f"; {len(own)} word(s) wider than {CAPTION_MAX_WORD_PX} px at that size get their own smaller size "
              f"({', '.join(f'{w!r} {n} px' for w, n in list(own.items())[:4])}{', ...' if len(own) > 4 else ''})") if own else ""
    return (f"{caption['font_size']} px for most words (fits the word wider than {int(caption.get('base_percentile', 1) * 100)}% of all words, "
            f"{caption.get('p90_word_px', '?')} px wide), outline {caption['stroke_width']} px{shrunk}; widest word {caption['widest_word']!r} "
            f"is about {caption['widest_word_px']} px wide on screen")


def hook_stroke_width(font_size: int) -> int:
    return max(4, round(font_size * HOOK_STROKE_SHARE))


def pick_hook_style(hook: dict, font_path: Path) -> dict:
    """Font size and outline of the hook card: ONE size for both lines, the biggest (<= HOOK_FONT_MAX) at which the wider line
    plus its two outlines fits HOOK_MAX_WIDTH_PX. `too_small` = even that is below HOOK_FONT_MIN (see hook_size_problem)."""
    lines = captionlib.hook_lines(hook)
    per_px, _height, note = measure_texts(lines, font_path)
    widest = max(lines, key=lambda line: per_px[line])
    em = per_px[widest]
    fit = math.floor(HOOK_MAX_WIDTH_PX / (em + 2 * HOOK_STROKE_SHARE)) if em else HOOK_FONT_MAX
    size = max(1, min(HOOK_FONT_MAX, fit))
    while size > 1 and em * size + 2 * hook_stroke_width(size) > HOOK_MAX_WIDTH_PX:  # the outline is rounded up: make sure it still fits
        size -= 1
    stroke = hook_stroke_width(size)
    style = {
        "font_size": size, "stroke_width": stroke, "widest_line": widest, "widest_px": round(em * size + 2 * stroke),
        "line_px": [round(per_px[line] * size + 2 * stroke) for line in lines], "limit_px": HOOK_MAX_WIDTH_PX,
        "target_size": HOOK_FONT_TARGET, "below_target": size < HOOK_FONT_TARGET, "too_small": size < HOOK_FONT_MIN,
        "characters_for_target": math.floor(len(widest) * (HOOK_MAX_WIDTH_PX / HOOK_FONT_TARGET - 2 * HOOK_STROKE_SHARE) / em) if em else None,
    }
    if note:
        style["note"] = note
    return style


def hook_size_problem(style: dict) -> str | None:
    """None when the hook text can be shown big enough; else a plain message that names the line to shorten."""
    if not style["too_small"]:
        return None
    return (f"The hook line {style['widest_line']!r} is too long for a big title card: it would need letters of only {style['font_size']} px "
            f"to fit the {style['limit_px']} px width, and the smallest allowed size is {HOOK_FONT_MIN} px. Shorten it "
            f"(about {style['characters_for_target']} characters of this kind fit at {style['target_size']} px).")


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


# Final audio: a gentle speech chain, then two-pass EBU R128 loudnorm. Platforms normalise loudness themselves; arriving at
# -14 LUFS with a true peak below -1 dBTP stops them from turning a quiet narration up or squashing a loud one.
LOUDNESS_TARGET_LUFS = -14.0
LOUDNESS_TRUE_PEAK_TARGETS = (-1.5, -2.5)  # the second one is the retry when the AAC encode pushes the first above the limit
LOUDNESS_LRA = 11
LOUDNESS_TOLERANCE_LU = 1.0  # integrated loudness must land within +-1 LU of the target
LOUDNESS_MAX_TRUE_PEAK = -1.0
SPEECH_CHAIN = "highpass=f=70,acompressor=threshold=0.1:ratio=2.5:attack=5:release=90:knee=4:makeup=1.5"
LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def parse_loudnorm_json(stderr_text: str) -> dict | None:
    """The measurement block that ffmpeg's loudnorm filter prints (print_format=json) as floats, or None if there is none.
    Keys: input_i (LUFS), input_tp (dBTP), input_lra (LU), input_thresh, target_offset."""
    found = LOUDNORM_JSON_RE.findall(strip_ansi(stderr_text or ""))
    if not found:
        return None
    try:
        raw = json.loads(found[-1])
        return {key: float(raw[key]) for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (ValueError, KeyError, TypeError):
        return None


def loudnorm_filter(true_peak: float, measured: dict | None = None) -> str:
    """The -af chain: speech chain + loudnorm. Without `measured` it is the analysis pass (prints JSON); with the first
    pass's numbers it is the second pass (linear=true: one fixed gain, no pumping)."""
    base = f"loudnorm=I={LOUDNESS_TARGET_LUFS:g}:TP={true_peak:g}:LRA={LOUDNESS_LRA}"
    if measured is None:
        return f"{SPEECH_CHAIN},{base}:print_format=json"
    return (f"{SPEECH_CHAIN},{base}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true")


def loudness_analysis_filter() -> str:
    """Measure a finished file as it is (no speech chain in front, it would change what is measured)."""
    return f"loudnorm=I={LOUDNESS_TARGET_LUFS:g}:TP={LOUDNESS_TRUE_PEAK_TARGETS[0]:g}:LRA={LOUDNESS_LRA}:print_format=json"


def loudness_problems(measured: dict) -> list[str]:
    """Why a measured file (parse_loudnorm_json of its analysis) misses the target; empty when it is inside both limits."""
    problems = []
    if not math.isfinite(measured["input_i"]) or abs(measured["input_i"] - LOUDNESS_TARGET_LUFS) > LOUDNESS_TOLERANCE_LU:
        problems.append(f"integrated loudness {measured['input_i']:.1f} LUFS is not within {LOUDNESS_TOLERANCE_LU:g} LU of {LOUDNESS_TARGET_LUFS:g} LUFS")
    if not measured["input_tp"] <= LOUDNESS_MAX_TRUE_PEAK:
        problems.append(f"true peak {measured['input_tp']:.1f} dBTP is above {LOUDNESS_MAX_TRUE_PEAK:g} dBTP")
    return problems


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


def voice_engine_url(voice_cfg) -> str | None:
    """The address of the language's OWN speech engine (studio/voices.json "engine_url"), or None when VoiceStudio voices it.
    VoiceStudio still does the transcription (the per-line voice check) for every language."""
    url = voice_cfg.get("engine_url") if isinstance(voice_cfg, dict) else None
    if isinstance(url, str) and url.strip().lower().startswith(("http://", "https://")):
        return url.strip().rstrip("/")
    return None


def configured_engine_url(language: str) -> str | None:
    """voice_engine_url for a language, read leniently: a missing or broken voices.json gives None here (step_preflight
    explains that problem in plain words a moment later)."""
    try:
        voices = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return voice_engine_url(voices.get(language)) if isinstance(voices, dict) else None


def voice_start_hint(voice_cfg, language: str) -> str:
    """How to start the language's own speech engine: the "start_hint" text in studio/voices.json, else voice-<language>/run.sh start."""
    hint = voice_cfg.get("start_hint") if isinstance(voice_cfg, dict) else None
    if isinstance(hint, str) and hint.strip():
        return hint.strip()
    return f"voice-{language}/run.sh start"


def configured_start_hint(language: str) -> str:
    """voice_start_hint for a language, read leniently like configured_engine_url (a missing or broken voices.json gives the default)."""
    try:
        voices = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        voices = None
    return voice_start_hint(voices.get(language) if isinstance(voices, dict) else None, language)


def engine_get_json(url: str, path: str, timeout: float = 10) -> dict:
    with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_voice_engine(url: str, language: str, start_hint: str | None = None) -> dict:
    """GET <url>/health of a language's own speech engine (voice-de/server.py, voice-en/server.py). Returns its answer; a missing or
    unhealthy engine becomes a plain-English GateError that says how to start it (`start_hint`, default voice-<language>/run.sh start)."""
    name = LANGUAGE_NAMES.get(language, language)
    start_hint = start_hint or f"voice-{language}/run.sh start"
    stop_hint = start_hint[:-len("start")] + "stop" if start_hint.endswith(" start") else "stop it"
    try:
        info = engine_get_json(url, "/health")
    except HTTP_ERRORS as exc:
        raise GateError(f"The {name} voice engine at {url} is not reachable ({type(exc).__name__}: {exc}). It is a separate program "
                        f"that must be running: start it: {start_hint}, then run this again.") from None
    if not isinstance(info, dict) or str(info.get("status", "")).lower() != "ok":
        raise GateError(f"The {name} voice engine at {url} did not say ok on /health (it said {info!r}). "
                        f"Restart it ({stop_hint}, then {start_hint}) and run this again.")
    return info


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
        self.hook_style: dict | None = None  # font size / outline of the hook card (step_preflight; None = the script has no hook)
        self.hook_end: float | None = None  # when the hook card starts to fade out (step_hook; None = no hook)
        self.cover: Path | None = None  # work/<id>/cover.jpg, the first frame of the final video (step_final_checks)

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
    p.add_argument("--min-seconds", type=float, default=45.0,
                   help="shortest allowed narration in seconds (default 45). Shorts do not have to reach 60 s: TikTok's 60-second rule "
                        "(for its creator rewards) only matters after 10,000 followers. 0 also skips the final minimum-duration check")
    p.add_argument("--max-seconds", type=float, default=75.0, help="longest allowed narration in seconds (default 75)")
    p.add_argument("--keep-work", action="store_true", help="keep work/<id> and MoneyPrinterTurbo's task folder for debugging")
    p.add_argument("--no-visuals", action="store_true", help="skip the diagram overlays (studio/visuals.py)")
    p.add_argument("--stage", choices=("voice", "all"), default="all", help="'voice' stops after the narration + length gate")
    p.add_argument("--footage", choices=FOOTAGE_MODES, default="auto",
                   help="where the stock footage comes from: 'own' = studio/footage.py picks and cuts Pixabay clips per line (needs a Pixabay key), "
                        "'mpt' = MoneyPrinterTurbo searches by itself (old behaviour), 'auto' (default) = own when a Pixabay key is set "
                        "and --local-materials is not used")
    p.add_argument("--voice-seed", type=int, default=None, metavar="N",
                   help="first seed to try for the one-take voice (default: 'seed' in studio/voices.json, else 1). The pitch register of a take "
                        "comes from its seed; a take that is not steady is re-rolled with the next seed, 6 takes at most. "
                        "Use a higher N when all 6 seeds were rejected; the take accepted that way is remembered for the script")
    p.add_argument("--no-voice-cache", action="store_true",
                   help="do not reuse (or store) accepted takes in work/_voice_cache; voice the script again")
    args = p.parse_args(argv)
    if args.min_seconds < 0 or args.max_seconds <= 0 or args.min_seconds > args.max_seconds:
        p.error("--min-seconds must be >= 0 and not larger than --max-seconds")
    if args.voice_seed is not None and args.voice_seed < 0:
        p.error("--voice-seed must be 0 or larger")
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


def preflight_voice_services(ctx: Ctx, language: str) -> dict:
    """VoiceStudio must be healthy and have a transcription engine: the per-line voice check uses it for EVERY language.
    Who SPEAKS the language decides the rest: VoiceStudio itself (its TTS engine must be MLX-Audio + Qwen3-TTS CustomVoice), or
    the language's own engine (studio/voices.json "engine_url": its /health must answer; VoiceStudio's TTS engine does not matter).
    Returns {"tts": {"active", "active_model"}, "asr_model", "engine_url" (None when VoiceStudio speaks)}."""
    health = voicestudio_info("/health", "whether it is healthy")
    if str(health.get("status", "")).lower() != "ok":
        raise GateError(f"VoiceStudio /health did not say ok: {health}")
    engine_url = configured_engine_url(language)
    if engine_url:
        engine = check_voice_engine(engine_url, language, configured_start_hint(language))
        model = str(engine.get("model") or "unknown")
        tts = {"active": model, "active_model": model}
    else:
        tts = voicestudio_info("/engines/tts", "which voice engine is active")
        problem = check_tts_engine(tts)
        if problem:
            raise GateError(problem)
    asr = voicestudio_info("/engines/asr", "which transcription engine is active")
    asr_model = asr.get("active")
    if not asr_model:
        raise GateError("VoiceStudio has no active transcription engine (/engines/asr). Select one in VoiceStudio and run this again.")
    if engine_url:
        name = LANGUAGE_NAMES.get(language, language)
        ctx.check("VoiceStudio", True, f"healthy; transcription {asr_model} (it only checks the {name} voice here, it does not speak it)")
        ctx.check("voice engine", True, f"{tts['active']} at {engine_url} answers /health (it speaks {name}; VoiceStudio's own TTS engine is not used)")
    else:
        ctx.check("VoiceStudio", True, f"healthy; TTS {tts.get('active')} / {tts.get('active_model')}; transcription {asr_model}")
    return {"tts": tts, "asr_model": asr_model, "engine_url": engine_url}


def step_preflight(ctx: Ctx) -> dict:
    ctx.step(2, "Preflight")
    args, script = ctx.args, ctx.script
    for tool in ("ffmpeg", "ffprobe", "node", "uv"):
        find_tool(tool)
    ctx.media_dir = pick_media_scripts_dir(Path.home() / ".claude/plugins/cache/media-studio-marketplace/media-studio")
    ctx.check("tools", True, f"ffmpeg, ffprobe, node, uv found; media-studio scripts: {ctx.media_dir}")

    services = preflight_voice_services(ctx, script["language"])
    tts, asr_model, engine_url = services["tts"], services["asr_model"], services["engine_url"]

    if not VOICES_FILE.is_file():
        raise GateError(f"{VOICES_FILE} is missing (it holds the voice + delivery directions per language).")
    try:
        voices = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateError(f"{VOICES_FILE} cannot be read as JSON ({exc}). Fix the file (it needs an \"en\" and a \"de\" entry) and run this again.")
    if not isinstance(voices, dict):
        raise GateError(f"{VOICES_FILE} must hold one JSON object with an \"en\" and a \"de\" entry.")
    voice_cfg = voices.get(script["language"])
    if not isinstance(voice_cfg, dict) or not voice_cfg.get("voice"):
        raise GateError(f"studio/voices.json has no complete \"{script['language']}\" entry (it needs a \"voice\"; the \"instructions\" text is "
                        "optional because this engine ignores it).")
    ref_f0 = voice_cfg.get("ref_f0_hz")
    if ref_f0 is not None and (isinstance(ref_f0, bool) or not isinstance(ref_f0, (int, float)) or ref_f0 <= 0):
        raise GateError(f"studio/voices.json: \"{script['language']}\".ref_f0_hz must be a positive number of Hz (got {ref_f0!r}). "
                        "Run `python3 studio/voice_take.py refs` to measure it from the voice sample.")
    max_ref_st = voice_cfg.get("max_ref_st")  # how far (semitones) a take may be from ref_f0_hz; missing = the default of voice_take.py
    if max_ref_st is not None and (isinstance(max_ref_st, bool) or not isinstance(max_ref_st, (int, float)) or not math.isfinite(max_ref_st) or max_ref_st <= 0):
        raise GateError(f"studio/voices.json: \"{script['language']}\".max_ref_st must be a positive number of semitones (got {max_ref_st!r}). "
                        "Use a number like 2.0 (a smaller number keeps the narrator closer to the reference voice), or remove the key.")
    if "engine_url" in voice_cfg and voice_engine_url(voice_cfg) is None:
        raise GateError(f"studio/voices.json: \"{script['language']}\".engine_url must be an address like http://127.0.0.1:3910 "
                        f"(got {voice_cfg['engine_url']!r}). Remove the key to let VoiceStudio speak this language.")
    if "start_hint" in voice_cfg and not (isinstance(voice_cfg["start_hint"], str) and voice_cfg["start_hint"].strip()):
        raise GateError(f"studio/voices.json: \"{script['language']}\".start_hint must be the text that starts the engine, like voice-{script['language']}/run.sh start "
                        f"(got {voice_cfg['start_hint']!r}). Remove the key to use that default.")
    if "deterministic" in voice_cfg and not isinstance(voice_cfg["deterministic"], bool):
        raise GateError(f"studio/voices.json: \"{script['language']}\".deterministic must be true or false (got {voice_cfg['deterministic']!r}).")
    if ref_f0 is None:
        ctx.warn(f"studio/voices.json has no ref_f0_hz for \"{script['language']}\", so the take is not compared with the channel's reference voice. "
                 "Run `python3 studio/voice_take.py refs` to measure it from studio/voice-tests/.")
    try:
        voice_take.pitch_command(MPT_DIR)  # pitch needs numpy, which only MoneyPrinterTurbo's virtual environment has
    except voice_take.VoiceTakeError as exc:
        raise GateError(str(exc)) from None

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
              f"{caption_size_summary(caption)}; caption top at y={caption['box_top_y']}, under the diagram area that ends at y={CAPTION_TOP_LIMIT_Y}")
    word_problem = caption_word_problem(caption)
    ctx.check("caption word fits", word_problem is None,
              word_problem or f"the widest word fits on one caption line ({caption['widest_word_px']} of {CAPTION_MAX_WORD_PX} px)")
    if script.get("hook"):
        hook_style = pick_hook_style(script["hook"], font_path)
        hook_problem = hook_size_problem(hook_style)
        ctx.check("hook size", hook_problem is None,
                  hook_problem or f"hook card letters {hook_style['font_size']} px, outline {hook_style['stroke_width']} px; widest line "
                                  f"{hook_style['widest_line']!r} is {hook_style['widest_px']} of {hook_style['limit_px']} px wide")
        if hook_style["below_target"]:
            ctx.warn(f"hook text is only {hook_style['font_size']} px tall (target {HOOK_FONT_TARGET}+): the line {hook_style['widest_line']!r} is long. "
                     f"About {hook_style['characters_for_target']} characters per line would give {HOOK_FONT_TARGET} px letters.")
        ctx.hook_style = hook_style
        ctx.report["hook"] = {"line1": script["hook"]["line1"], "line2": script["hook"]["line2"], "accent": script["hook"]["accent"], **hook_style}
    topic_noun, topic_default = footage.topic_noun_for(script)
    ctx.report["inputs"]["topic_noun"] = {"noun": topic_noun, "default": topic_default}
    ctx.report["inputs"]["local_materials"] = [str(f) for f in local_files]
    ctx.report["captions"] = {"mode": SUBTITLE_DISPLAY_MODE, "animation": SUBTITLE_ANIMATION, "position": SUBTITLE_POSITION, **caption}
    ctx.report["voice"] = {
        "engine": tts.get("active"), "model": tts.get("active_model"), "voice": voice_cfg["voice"],
        "instructions": voice_cfg.get("instructions"), "ref_f0_hz": ref_f0, "max_ref_st": max_ref_st, "transcription_engine": asr_model,
        "engine_url": engine_url, "deterministic": bool(voice_cfg.get("deterministic")),
    }
    ctx.report["inputs"]["footage_source"] = {"local": "local", "own": "pixabay (own selection)"}.get(mode, source)
    ctx.report["inputs"]["footage_mode"] = mode
    ctx.report["footage"] = {"mode": mode, "provider": {"local": "local files", "own": "pixabay", "mpt": source}[mode]}
    return {"voice_cfg": voice_cfg, "ref_f0": ref_f0, "max_ref_st": max_ref_st, "asr_model": asr_model, "tts_model": str(tts.get("active_model")),
            "engine_url": engine_url, "local_files": local_files, "caption": caption, "source": source, "footage": mode}


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


def step_voice(ctx: Ctx, setup: dict) -> dict:
    """Step 3: the whole script in ONE take (studio/voice_take.py): one request, line boundaries snapped to real silences,
    long pauses shortened, every line checked by transcription, failed lines patched, the take's pitch and loudness gated."""
    ctx.step(3, "Voicing the whole script in one take and checking it")
    texts = [line["text"].strip() for line in ctx.script["lines"]]
    cfg, language = setup["voice_cfg"], ctx.script["language"]
    engine_url = setup.get("engine_url")  # the language's own speech engine (voices.json "engine_url"); None = VoiceStudio speaks
    deterministic = bool(cfg.get("deterministic"))  # same text = same audio: one take, no seed re-rolls, no line patching
    instructions = "" if engine_url else (cfg.get("instructions") or "")  # an own engine gets no delivery text
    own_engine = {"engine_url": engine_url, "engine_start_hint": voice_start_hint(cfg, language)} if engine_url else {}
    backend = voice_take.VoiceStudioBackend(VOICESTUDIO_URL, cfg["voice"], setup["asr_model"], language, instructions,
                                            ffmpeg=find_tool("ffmpeg"), mpt_dir=MPT_DIR, **own_engine)
    seed = ctx.args.voice_seed if ctx.args.voice_seed is not None else int(cfg.get("seed", 1))
    ctx.work.mkdir(parents=True, exist_ok=True)
    try:
        if deterministic:
            ctx.say(f"  voice engine {setup['tts_model']}: identical text gives identical audio, so ONE take is made; no seed re-rolls, "
                    "no re-voicing of single lines (a failing line must be reworded)"
                    + ("; --voice-seed changes nothing here" if ctx.args.voice_seed is not None else ""))
            probe = {"voice": cfg["voice"], "model": setup["tts_model"], "instructions_ignored": True, "deterministic": True}
        else:
            probe = voice_take.probe_instructions(backend, cfg["voice"], setup["tts_model"], WORK_ROOT / "_voice_probe.json", instructions, log=ctx.say)
        take = voice_take.produce_narration(
            texts, backend=backend, grade=grade_line, voice=cfg["voice"], model=setup["tts_model"], asr_model=setup["asr_model"],
            ref_f0=setup.get("ref_f0"), max_ref_st=setup.get("max_ref_st"), work_dir=ctx.work, cache_root=WORK_ROOT / "_voice_cache", start_seed=seed,
            instructions_in_key="" if probe.get("instructions_ignored") is True else instructions,
            use_cache=not ctx.args.no_voice_cache, deterministic=deterministic, log=ctx.say)
    except voice_take.VoiceTakeError as exc:
        ctx.report["voice"].update(mode="one take", start_seed=seed, attempts=getattr(exc, "attempts", None))
        ctx.checks.append({"name": "voice take", "ok": False, "detail": str(exc)})
        raise GateError(str(exc)) from None
    lines, gate = take["lines"], take["continuity"]
    for g in lines:
        extra = f", patched with seed {g['patched_seed']}" if g.get("patched_seed") else ""
        loudness = "n/a" if g.get("loudness_db") is None else f"{g['loudness_db']:.1f} dB"
        ctx.say(f"  [ok] line {g['index']}: WER {g['wer']:.2f} (limit {g['threshold']:.2f}), letters {g['cer']:.2f} (limit {CER_LIMIT:.2f})"
                f", pitch {g['f0_hz']:.0f} Hz, loudness {loudness}{extra}: {g['text'][:50]}")
    ctx.report["voice"].update(
        mode="one take", seed=take["seed"], start_seed=seed, instructions_ignored=probe.get("instructions_ignored"),
        attempts=take["attempts"], cache=take["cache"], lines=lines, patches=take["patches"], continuity=gate,
        take={"raw_seconds": take["raw_seconds"], "boundaries_snapped": f"{sum(take['snapped'])}/{len(take['snapped'])}",
              "pauses_shortened": take["pauses_shortened"], "pause_seconds_saved": take["pause_seconds_saved"],
              "pause_rule": f"silences over {voice_take.PAUSE_MAX_S:g} s shortened to {voice_take.PAUSE_TARGET_S:g} s"})
    bad = [g for g in lines if not g.get("ok")]  # voice_take only returns takes whose lines all pass; checked again here
    if bad:
        ctx.checks.append({"name": "voice accuracy", "ok": False, "detail": [g["index"] for g in bad]})
        raise GateError(voice_failure_message(bad, voice_take.PATCH_SEEDS))
    ctx.check("voice accuracy", True, voice_accuracy_detail(lines, len(take["patches"])))
    reference = (f"; reference voice {gate['ref_f0_hz']:.0f} Hz ({gate['ref_offset_st']:+.1f} st)" if gate.get("ref_f0_hz") else "")
    ctx.check("voice continuity", gate["ok"],
              f"seed {take['seed']}: take median {gate['take_median_hz']} Hz, spread {gate['sd_st']} st, farthest line {gate['max_line_offset_st']} st, "
              f"largest neighbour jump {gate['max_adjacent_jump_st']} st / {gate['max_adjacent_jump_db']} dB{reference}"
              if gate["ok"] else "; ".join(gate["reasons"]))
    return take


def step_join(ctx: Ctx, take: dict) -> tuple[Path, list[dict], float]:
    """Step 4: the take's narration is already work/<id>/narration.wav; write timings.json and the narration part of the report."""
    ctx.step(4, "Narration and line timings")
    narration, timings = take["narration"], take["timings"]
    total = ffprobe_info(find_tool("ffprobe"), narration)["duration"]
    (ctx.work / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8")
    bounds, sr = take["bounds"], take["sr"]
    ctx.report["timings"] = timings
    ctx.report["narration"] = {"path": str(narration), "duration": round(total, 3), "mode": "one take",
                               "line_durations": [round((b - a) / sr, 3) for a, b in zip(bounds, bounds[1:])]}
    ctx.check("narration ready", True, f"{total:.1f} s, {len(timings)} lines (seed {take['seed']}); timings = first to last sound of each line, "
                                      f"in {ctx.work / 'timings.json'}")
    return narration, timings, total


def step_length(ctx: Ctx, total: float) -> None:
    ctx.step(5, "Length gate")
    words = sum(len(line["text"].split()) for line in ctx.script["lines"])
    ok, message = length_gate(total, words, ctx.args.min_seconds, ctx.args.max_seconds)
    ctx.report["narration"].update(words=words, words_per_second=round(words / total, 3) if total else 0)
    ctx.check("narration length", ok, message)


def step_hook(ctx: Ctx, timings: list[dict]) -> float | None:
    """The hook card's timing, once the line timings are known: it is on screen from 0 until hook_end = the end of line 0, but at
    least 2.5 s and at most 3.5 s, then fades out for 0.25 s. No diagram panel may start before hook_end + 0.25 s (the card sits in
    the same area and is still on screen, half see-through, while it fades), and the captions are not drawn before hook_end.
    Returns hook_end, or None when the script has no hook."""
    hook = ctx.script.get("hook")
    if not hook:
        ctx.hook_end = None
        return None
    try:
        hook_end = captionlib.hook_end_seconds(timings)
    except captionlib.CaptionError as exc:
        raise GateError(f"The hook card cannot be timed: {exc}") from None
    lines = ctx.script["lines"]
    if ctx.args.no_visuals:  # the panels are not drawn at all, so they cannot collide with the card
        lines = [{**line, "visual": None} for line in lines]
    problems = captionlib.hook_panel_problems(lines, timings, hook_end)
    ctx.hook_end = hook_end
    ctx.report.setdefault("hook", {}).update(
        hook_end=hook_end, fade_seconds=captionlib.HOOK_FADE_SECONDS, line0_end=round(float(timings[0]["end"]), 3),
        panels_free_from=round(captionlib.hook_panel_free_from(hook_end), 3),
        card_visible=f"0.00-{hook_end + captionlib.HOOK_FADE_SECONDS:.2f} s (fully visible until {hook_end:.2f} s)")
    ctx.check("hook timing", not problems,
              f"hook card fully visible from 0.00 s until {hook_end:.2f} s (line 0 ends at {float(timings[0]['end']):.2f} s; "
              f"at least {captionlib.HOOK_MIN_SECONDS:g} s, at most {captionlib.HOOK_MAX_SECONDS:g} s), then a {captionlib.HOOK_FADE_SECONDS:g} s fade-out; "
              f"the captions start after {hook_end:.2f} s and no diagram panel starts before {captionlib.hook_panel_free_from(hook_end):.2f} s "
              "(the fade is over)" if not problems else "; ".join(problems))
    return hook_end


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
    topic = report.get("topic")
    if topic:
        ctx.check("topic on screen at 0 s", topic["ok"],
                  f"the first picture (pixabay {topic['clip_id']}, on screen from 0.0 s) lists '{topic['noun']}' among its first {footage.LEAD_TAGS} tags: "
                  f"{', '.join(topic['first_tags'])}"
                  + (" (the noun was searched directly because line 0's own phrase found no such clip)" if topic["found_by_topic_search"] else "")
                  + (" [the noun is the script's first video term: set \"topic_noun\" to choose it yourself]" if topic["noun_is_default"] else ""))
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
            "style": {"font_size": style["font_size"], "stroke_width": style["stroke_width"], "box_height": style["box_height"],
                      "word_sizes": dict(style.get("word_sizes") or {})}}


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
    else:
        ctx.warn("topic on screen at 0 s was NOT checked: that check needs --footage own (the first picture of local or MoneyPrinterTurbo footage "
                 "is not chosen by studio/footage.py). Look at the first frame yourself.")
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


def caption_payload(words: list[dict], word_sizes: dict, base_size: int) -> list[dict]:
    """The words as Remotion gets them: text and time, plus the word's OWN font size when it is smaller than the base size."""
    out = []
    for w in words:
        item = {"text": w["text"], "start": w["start"], "end": w["end"]}
        own = word_sizes.get(w["text"])
        if own is not None and own < base_size:
            item["font_size"] = own
        out.append(item)
    return out


def step_visuals(ctx: Ctx, mpt: dict, timings: list[dict]) -> Path:
    """Captions (always), the hook card (when the script has a hook) and diagram panels (unless --no-visuals): Remotion draws
    them, ONE ffmpeg pass puts them on the video. While the hook card is up the captions are not drawn."""
    ctx.step(7, "Captions, hook card, diagram overlays and loudness")
    needed = [k for k, line in enumerate(ctx.script["lines"]) if line.get("visual")]
    panels_off = ctx.args.no_visuals or not needed
    script = ctx.script
    if panels_off:
        why = "--no-visuals" if ctx.args.no_visuals else "no line has a visual"
        script = {**ctx.script, "lines": [{**line, "visual": None} for line in ctx.script["lines"]]}
    module = load_visuals_module(needed)
    caption_data = mpt["captions"]
    style = caption_data["style"]
    script_texts = [line["text"].strip() for line in ctx.script["lines"]]
    drawn, hidden_pieces = caption_data["words"], 0
    hook_args = None
    if ctx.hook_end is not None and ctx.hook_style is not None and ctx.script.get("hook"):
        drawn, hidden_pieces = captionlib.hide_until(caption_data["words"], ctx.hook_end)
        hook_args = {**{k: ctx.script["hook"][k] for k in ("line1", "line2", "accent")},
                     "font_size": ctx.hook_style["font_size"], "stroke_width": ctx.hook_style["stroke_width"], "hook_end": ctx.hook_end}
        hidden_words = len(caption_data["words"]) - len(drawn)  # the hidden words are always the first ones
        started_late = sum(1 for before, after in zip(caption_data["words"][hidden_words:], drawn) if after["start"] - before["start"] > 1e-9)
        ctx.report.setdefault("captions", {})["hidden_under_hook"] = {
            "until": ctx.hook_end, "words_hidden": hidden_words, "words_started_late": started_late, "script_words_not_drawn": hidden_pieces}
        ctx.say(f"  hook card until {ctx.hook_end:.2f} s: {hidden_words} caption word(s) are not drawn under it"
                + (f", {started_late} one(s) start when it ends" if started_late else ""))
    caption_args = {
        "words": caption_payload(drawn, style.get("word_sizes") or {}, style["font_size"]),
        "font_size": style["font_size"], "stroke_width": style["stroke_width"], "box_height": style["box_height"],
        "text_color": SUBTITLE_TEXT_COLOR, "stroke_color": SUBTITLE_STROKE_COLOR,
    }
    own_sizes = sum(1 for w in caption_args["words"] if "font_size" in w)
    ok, detail = captionlib.captions_match_script([w["text"] for w in caption_args["words"]], script_texts, skip=hidden_pieces)
    ctx.check("captions match script (as drawn)", ok, detail)  # what is handed to Remotion, one last time
    out = ctx.work / "final-visuals.mp4"
    work_dir = ctx.work / "visuals"
    work_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {"captions": caption_args}
    if hook_args:
        kwargs["hook"] = hook_args
    try:
        info = module.render_and_overlay(str(mpt["video"]), script, timings, str(out), str(work_dir), **kwargs)
    except Exception as exc:  # the overlay code is another module: report any crash plainly
        raise GateError(f"visuals.render_and_overlay failed: {type(exc).__name__}: {exc}")
    if not out.is_file():
        raise GateError(f"visuals.render_and_overlay returned but {out} was not written.")
    ctx.report["visuals"] = info if isinstance(info, dict) else {"result": str(info)}
    if panels_off:
        ctx.report["visuals"]["skipped"] = why
    panels = len(needed) if not panels_off else 0
    ctx.check("visuals", True, f"{len(caption_args['words'])} caption words" + (f" ({own_sizes} with their own smaller size)" if own_sizes else "")
              + (" and the hook card" if hook_args else "") + (f" and {panels} visual line(s)" if panels else "") +
              f" rendered onto the video in one ffmpeg pass -> {out}")
    return out


def measure_loudness(ffmpeg: str, path: Path, audio_filter: str) -> dict:
    proc = run_cmd([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", audio_filter, "-f", "null", "-"], 900, "ffmpeg (loudness measurement)")
    found = parse_loudnorm_json(proc.stderr)
    if proc.returncode != 0 or found is None:
        raise GateError(f"ffmpeg could not measure the loudness of {path.name}: {proc.stderr.strip()[-300:]}")
    return found


def step_loudness(ctx: Ctx, video: Path) -> Path:
    """The last thing done to the picture-and-sound file: speech chain + two-pass loudnorm to -14 LUFS / -1.5 dBTP, video stream
    copied (not re-encoded), audio AAC 192k at 48 kHz; then the OUTPUT is measured and must be -14 +-1 LUFS with a true peak
    of at most -1 dBTP (one retry with a lower true-peak target when the AAC encode overshoots)."""
    ffmpeg = find_tool("ffmpeg")
    out = ctx.work / "final-loudness.mp4"
    tries = []
    for true_peak in LOUDNESS_TRUE_PEAK_TARGETS:
        first = measure_loudness(ffmpeg, video, loudnorm_filter(true_peak))
        proc = run_cmd([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-map", "0:v:0", "-map", "0:a:0",
                        "-c:v", "copy", "-af", loudnorm_filter(true_peak, first), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                        "-movflags", "+faststart", str(out)], 1800, "ffmpeg (loudness)")
        if proc.returncode != 0 or not out.is_file():
            raise GateError(f"ffmpeg could not finish the loudness step: {proc.stderr.strip()[-300:]}")
        after = measure_loudness(ffmpeg, out, loudness_analysis_filter())
        problems = loudness_problems(after)
        tries.append({"true_peak_target": true_peak, "measured_before": first, "problems": problems,
                      "measured_after": {"integrated_lufs": after["input_i"], "true_peak_dbtp": after["input_tp"], "lra": after["input_lra"]}})
        if not problems:
            break
    final = tries[-1]
    ctx.report["loudness"] = {
        "target_lufs": LOUDNESS_TARGET_LUFS, "true_peak_target_dbtp": final["true_peak_target"], "speech_chain": SPEECH_CHAIN,
        "video": "copied, not re-encoded", "audio": "aac 192k, 48 kHz", "measured_before": final["measured_before"],
        "integrated_lufs": final["measured_after"]["integrated_lufs"], "true_peak_dbtp": final["measured_after"]["true_peak_dbtp"],
        "lra": final["measured_after"]["lra"], "ok": not final["problems"], "tries": tries,
    }
    after = final["measured_after"]
    ctx.check("final loudness", not final["problems"],
              f"{after['integrated_lufs']:.1f} LUFS (target {LOUDNESS_TARGET_LUFS:g} +-{LOUDNESS_TOLERANCE_LU:g}), true peak {after['true_peak_dbtp']:.1f} dBTP "
              f"(limit {LOUDNESS_MAX_TRUE_PEAK:g}), loudness range {after['lra']:.1f} LU"
              + ("" if not final["problems"] else "; " + "; ".join(final["problems"])))
    return out


def cover_command(ffmpeg: str, video: Path, out: Path) -> list[str]:
    """ffmpeg command that saves the frame at 0.0 s of the finished video as a JPEG (the cover for TikTok, Instagram and YouTube)."""
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", "0", "-i", str(video), "-frames:v", "1", "-q:v", COVER_QUALITY, str(out)]


def write_cover(ffmpeg: str, video: Path, out: Path) -> dict:
    """Write the cover and return its ffprobe summary; a plain GateError when ffmpeg cannot do it."""
    proc = run_cmd(cover_command(ffmpeg, video, out), 120, "ffmpeg (cover frame)")
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise GateError(f"The cover frame could not be saved: {proc.stderr.strip()[-300:]}")
    return ffprobe_info(find_tool("ffprobe"), out)


def hook_visibility(ffmpeg: str, final: Path, base: Path, hook_end: float, limit: float = HOOK_SEEN_LIMIT) -> list[dict]:
    """Is the hook card really in the finished video? Compare the card's band (HOOK_BAND_CROP) of the finished video with the same band
    of the video WITHOUT overlays (MoneyPrinterTurbo's), at 0.0 s (the cover frame) and just before the card fades out.
    [{seconds, diff, seen}]; seen = the two differ by at least `limit` (mean grey difference 0-255)."""
    results = []
    for t in (0.0, round(max(0.0, hook_end - 0.1), 3)):
        a = footage.band_signature(ffmpeg, final, t, HOOK_BAND_CROP, 108, 45)
        b = footage.band_signature(ffmpeg, base, t, HOOK_BAND_CROP, 108, 45)
        diff = footage.mean_abs_diff(a, b)
        results.append({"seconds": t, "diff": round(diff, 2), "seen": diff >= limit})
    return results


def publish_info(script: dict, final_seconds: float | None) -> dict:
    """What the upload pack needs besides caption.txt: the YouTube title, the comment to pin, the hook text and the runtime."""
    hook = script.get("hook")
    return {
        "youtube_title": script["title"], "title_length": len(script["title"]), "title_limit": TITLE_MAX,
        "pinned_comment": script.get("pinned_comment"),
        "hook": {k: hook[k] for k in ("line1", "line2", "accent")} if hook else None,
        "topic_noun": footage.topic_noun_for(script)[0] or None,
        "runtime_seconds": final_seconds,
    }


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
    ffmpeg = find_tool("ffmpeg")
    cover = ctx.work / "cover.jpg"
    cover_info = write_cover(ffmpeg, final_video, cover)
    size = (cover_info.get("width"), cover_info.get("height"))
    ctx.report["cover"] = {"path": str(cover), "frame_seconds": 0.0, "size": f"{size[0]}x{size[1]}", "jpeg_quality": "about 90 (ffmpeg -q:v " + COVER_QUALITY + ")"}
    ctx.check("cover frame", size == (1080, 1920), f"cover.jpg = the frame at 0.0 s of the final video, {size[0]}x{size[1]} (needs exactly 1080x1920)"
              + (" - it shows the hook card" if ctx.hook_end is not None else ""))
    ctx.cover = cover
    if ctx.hook_end is not None:
        seen = hook_visibility(ffmpeg, final_video, mpt["video"], ctx.hook_end)
        ctx.report.setdefault("hook", {})["visibility_check"] = {"band": HOOK_BAND_CROP, "limit": HOOK_SEEN_LIMIT, "frames": seen}
        ctx.check("hook visible at 0 s", all(r["seen"] for r in seen),
                  "the hook card is in the picture at " + " and ".join(f"{r['seconds']:g} s" for r in seen) +
                  f" (difference to the footage underneath {', '.join(str(r['diff']) for r in seen)} of at least {HOOK_SEEN_LIMIT:g})"
                  if all(r["seen"] for r in seen) else
                  "the hook card is NOT visible where it should be: " + ", ".join(f"{r['seconds']:g} s (difference {r['diff']}, needs {HOOK_SEEN_LIMIT:g})" for r in seen if not r["seen"]))
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
                     "footage": ctx.args.footage, "voice_seed": ctx.args.voice_seed, "voice_cache": not ctx.args.no_voice_cache},
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
    if ctx.cover is not None and ctx.cover.is_file():
        shutil.copyfile(ctx.cover, folder / "cover.jpg")
        kept[str(ctx.cover)] = str(folder / "cover.jpg")
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
    if ctx.cover is not None and ctx.cover.is_file():
        ctx.report["outputs"]["cover"] = str(folder / "cover.jpg")
    ctx.report["publish"] = publish_info(ctx.script, (ctx.report.get("durations") or {}).get("final"))
    write_report(ctx, folder / "report.json", ok=True)
    ctx.say(f"  wrote {folder}/ (final.mp4, {'cover.jpg, ' if ctx.report['outputs'].get('cover') else ''}subtitles.srt, captions-words.json, sheet.png, caption.txt, report.json)")
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
        "note": "paths in this report that pointed at removed files are null (or left out of lists); the review folder keeps final.mp4, cover.jpg, subtitles.srt, captions-words.json, sheet.png, caption.txt. "
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
        take = step_voice(ctx, setup)
        narration, timings, total = step_join(ctx, take)
        step_length(ctx, total)
        step_hook(ctx, timings)
        if args.stage == "voice":
            ctx.say(f"\nStage 'voice' done. Narration: {narration} ({total:.1f} s). Timings: {ctx.work / 'timings.json'}")
            return 0
        mpt = step_mpt(ctx, narration, setup, timings, total)
        final_video = step_loudness(ctx, step_visuals(ctx, mpt, timings))
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
