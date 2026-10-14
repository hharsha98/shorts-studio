#!/usr/bin/env python3
"""footage.py - choose, download and cut the stock footage (B-roll) for one Short. Pixabay only for now.

Why this exists: MoneyPrinterTurbo's own Pixabay search keeps only PORTRAIT clips that are at least 1080 px wide,
so it finds 0-10 clips per search term and fills the video with off-topic footage. Here we take over the footage
choice: one clip per line of the script (script.json lines[].broll), picked for relevance and sharpness, cut to
exactly 1080x1920 and joined into ONE file (work/<id>/broll.mp4) as long as the narration. make_video.py then hands
that file to MoneyPrinterTurbo as its only "local material".

What happens, in order:
    1. plan_segments    one picture segment per line (same search phrase on neighbouring lines = one segment,
                        segments longer than 6 s are cut into 3-5 s pieces so the picture changes regularly)
    2. PixabayClient    searches Pixabay (answers are cached for 24 hours, the API rules ask for that)
    3. choose_clips     for every segment the best clip that was not used yet: long enough, relevant (its tags
                        mention the phrase), sharp enough for a 9:16 crop, no logo/text/brand tags, nothing that
                        usually carries a brand (jet ski, car, boat, product review...), a clip a person rejected
                        (studio/footage_blocklist.json), and preferably an uploader that is not in the video yet.
                        When a phrase finds nothing, a video term is used as a stand-in: terms that share a word with
                        the phrase first, never flame/cooking pictures, and the report says when it is unrelated.
                        The FIRST picture (on screen at 0 s, behind the hook card, and the cover image) must show the
                        video's topic: a clip whose first 8 tags contain the script's "topic_noun" (searched directly
                        when line 0's own phrase does not deliver one; no such clip = a plain error naming the noun).
    4. download         only the chosen renditions, once, into work/_clips/ (reused by later runs; clips unused for
                        30 days, or the least recently used ones above 3 GB, are deleted again at the end)
    5. render + join    centre crop to 9:16, scale to 1080x1920, 30 fps, no audio, exact length per segment;
                        broll.mp4 runs 0.25 s PAST the narration (MoneyPrinterTurbo wants audio + 0.1 s and would
                        otherwise loop the whole B-roll)
    6. credits + report which clips were used, why, and the "Video by <user> on Pixabay: <page>" lines

SECRETS: the Pixabay key is read from MoneyPrinterTurbo/config.toml at run time (load_pixabay_key). It must never
be printed, logged or written anywhere. Pixabay wants it as a URL parameter, so every message that could contain
the URL goes through mask_secret() ("key=***"). Cache file names are hashes of the query WITHOUT the key.

Python standard library only. The pure functions are unit-tested in studio/tests/test_footage.py (no network).

    python3 studio/footage.py plan content/<id>/script.json      # shows which clips WOULD be used (searches only)
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK_ROOT = ROOT / "work"
CACHE_DIR = WORK_ROOT / "_pixabay_cache"
CLIPS_DIR = WORK_ROOT / "_clips"
MPT_CONFIG = ROOT / "MoneyPrinterTurbo" / "config.toml"

PIXABAY_URL = "https://pixabay.com/api/videos/"
USER_AGENT = "shorts-studio/1.0 (personal YouTube Shorts tool)"
CACHE_SECONDS = 24 * 3600  # the Pixabay API rules: "requests must be cached for 24 hours"
PER_PAGE = 50
REQUESTS_PER_MINUTE = 90  # the API allows 100 per 60 s; stay clearly under it

FRAME_W, FRAME_H, FPS = 1080, 1920, 30
MAX_SEGMENT_SECONDS = 6.0  # longer segments are cut into pieces
PIECE_TARGET_SECONDS = 5.0  # ... of about 3-5 s
EXTRA_CLIP_SECONDS = 0.5  # a clip must be this much longer than the segment it fills
MAX_UNRELATED_SHARE = 0.25  # at most this share of the segments may show a stand-in picture that is not about their line
BARS_MIN_SHARE = 0.98  # the picture inside black bars (letterbox) must fill at least this share of the crop's height and width
BARS_MAX_SAMPLE_SECONDS = 6.0  # how much of a clip is checked for black bars (the part that will be used)
MIN_CROP_WIDTH = 1080  # the 9:16 crop taken from the source must be at least this wide, or it would be upscaled (blurry)
MAX_CLIP_BYTES = 200 * 1024 * 1024
LEAD_TAGS = 8  # Pixabay lists the most fitting tags first: the phrase must show up among the first few
MAX_PAGES = 3  # search result pages looked at per phrase (50 hits each) before the next fallback phrase is tried
DOWNLOAD_MARGIN = 4  # downloads allowed beyond one per segment (a bad file has to be replaced)
BROLL_TAIL_SECONDS = 0.25  # broll.mp4 runs this much PAST the narration: MoneyPrinterTurbo wants audio + 0.1 s, and a
#                            file that is shorter makes it loop the whole B-roll (wasted work and a misleading warning)
LENGTH_TOLERANCE = 0.05  # broll.mp4 may differ from narration + BROLL_TAIL_SECONDS by this many seconds
MIN_TAIL_SECONDS = 0.15  # ... and must be at least this much longer than the narration, whatever the tolerance
DOWNLOAD_MAX_SECONDS = 300  # one clip download may take this long in total (the read timeout only limits a single stall)
CLIPS_MAX_BYTES = 3 * 1024 * 1024 * 1024  # work/_clips is a cache: above this the least recently used clips are deleted
CLIPS_MAX_AGE_SECONDS = 30 * 24 * 3600  # ... and clips not used for this long
STALE_TEMP_SECONDS = 3600  # leftover *.part download files older than this are removed

BLOCKED_TAGS = ("logo", "brand", "text", "sign", "advertisement", "billboard", "label", "packaging")
BLOCKED_TAGS_EXTRA = ("package", "branded", "signage", "advertising",  # same idea, other spellings
                      "generated", "midjourney")  # computer or AI generated pictures: not real footage, and YouTube wants those disclosed
# Footage of products and vehicles almost always shows a brand name on the object itself (a jet ski with "SEADOO" on it,
# a watch movement stamped "MIYOTA", "product review" and "buying guide" clips are made to advertise). Tags are matched as whole tags, so 'jet ski' does not
# block 'ski jump'. A phrase that is ABOUT such a thing ('car engine') may use it: a person then reviews the result.
BRAND_PRONE_TAGS = ("jet ski", "car", "automobile", "motorcycle", "motorbike", "boat", "watch", "wristwatch", "product review", "buying guide", "unboxing")
# Pictures that mislead when they only stand in for a line (the "fallback" search with a general video term): open flames
# and cooking pictures during a talk about cold, for example. Not applied when the line's own phrase is about that.
MISLEADING_FALLBACK_TAGS = ("flame", "fire", "burn", "burner", "stove", "burning", "fry", "fried", "frying", "cook", "cooking", "wok", "grill", "barbecue", "bbq", "smoke")
STOP_WORDS = {"a", "an", "the", "in", "on", "of", "at", "to", "with", "and", "for", "from", "by", "into", "over", "up", "off"}
# Words that fit many unrelated clips ("open", "interior", "day"). A clip must match at least one OTHER word of the
# phrase, otherwise "kitchen interior" would accept any church interior.
GENERIC_WORDS = {
    "open", "close", "closeup", "inside", "outside", "interior", "exterior", "view", "background", "abstract", "slow",
    "motion", "person", "people", "man", "woman", "hot", "cold", "day", "night", "old", "new", "big", "small", "large",
    "top", "aerial", "time", "lapse", "footage", "video", "wearing", "walking", "using", "front", "back", "light",
}
SYNONYMS = {"fridge": "refrigerator", "earphone": "headphone", "headset": "headphone", "smartphone": "phone", "cellphone": "phone",
            "skis": "ski"}  # the plural rule keeps words ending in -is


BLOCKLIST_FILE = ROOT / "studio" / "footage_blocklist.json"  # clips a human saw and rejected: {"pixabay": {"<id>": "why"}}


def load_clip_blocklist(path: Path = BLOCKLIST_FILE) -> dict[str, str]:
    """{clip id (text): reason} of clips that were reviewed by eye and must never be used (a logo, a sign, text that the
    tags do not reveal). A missing file means an empty list; a broken file is a plain error, never silently ignored."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise FootageError(f"{path} cannot be read ({type(exc).__name__}). It must look like {{\"pixabay\": {{\"12345\": \"why\"}}}}; fix or remove it.") from None
    clips = data.get("pixabay") if isinstance(data, dict) else None
    if not isinstance(clips, dict):
        raise FootageError(f"{path} must look like {{\"pixabay\": {{\"12345\": \"why\"}}}}.")
    return {str(k): str(v) for k, v in clips.items()}


class FootageError(Exception):
    """Something about the footage went wrong. The message is shown to the user: say what is wrong and what to do."""


# --------------------------------------------------------------------------------------
# Secrets (the key is read at run time, never printed)
# --------------------------------------------------------------------------------------


def pixabay_key_from_config(app_cfg: dict) -> str | None:
    """First non-blank key of [app] pixabay_api_keys, or None."""
    for key in (app_cfg or {}).get("pixabay_api_keys") or []:
        if str(key).strip():
            return str(key).strip()
    return None


def load_pixabay_key(config_path: Path = MPT_CONFIG) -> str | None:
    """Read the key from MoneyPrinterTurbo/config.toml. Returns None when there is none; never prints it."""
    try:
        cfg = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FootageError(f"MoneyPrinterTurbo/config.toml cannot be read ({type(exc).__name__}). Check the file and run this again.") from None
    return pixabay_key_from_config(cfg.get("app", {}))


def mask_secret(text, key: str | None = None) -> str:
    """Hide the API key in any text (a URL with key=..., or the key itself)."""
    out = re.sub(r"(?i)(\bkey=)[^&\s'\"<>]+", r"\1***", str(text))
    if key:
        out = out.replace(key, "***")
    return out


def make_ssl_context() -> ssl.SSLContext:
    """TLS with certificate checking. The python.org build on macOS ships without root certificates until
    'Install Certificates.command' was run, so fall back to the system bundle then. Checking is never switched off."""
    paths = ssl.get_default_verify_paths()
    have_default = os.environ.get("SSL_CERT_FILE") or (paths.openssl_cafile and os.path.isfile(paths.openssl_cafile))
    if not have_default:
        for candidate in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem", "/usr/local/etc/openssl@3/cert.pem"):
            if os.path.isfile(candidate):
                return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


def default_urlopen(req, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=make_ssl_context())


# --------------------------------------------------------------------------------------
# 1. Segments (pure)
# --------------------------------------------------------------------------------------


def normalize_phrase(phrase) -> str:
    return " ".join(str(phrase).lower().split())


def resolve_phrases(lines: list[dict], video_terms: list[str]) -> list[str]:
    """One search phrase per line: the line's own "broll"; else the previous line's phrase. Lines at the very start
    that have none (before the first "broll") cycle through video_terms."""
    terms = [" ".join(t.split()) for t in (video_terms or []) if isinstance(t, str) and t.split()]
    phrases: list[str] = []
    seen_explicit = False
    cycled = 0
    for line in lines:
        raw = line.get("broll") if isinstance(line, dict) else None
        if isinstance(raw, str) and raw.strip():
            phrase = " ".join(raw.split())
            seen_explicit = True
        elif seen_explicit:
            phrase = phrases[-1]
        else:
            if not terms:
                raise FootageError("A line has no \"broll\" phrase and the script has no video_terms to fall back on.")
            phrase = terms[cycled % len(terms)]
            cycled += 1
        phrases.append(phrase)
    return phrases


def split_piece_bounds(start: float, end: float) -> list[float]:
    """Boundaries of a segment: unchanged up to 6 s, otherwise equal pieces of 3-5 s."""
    length = end - start
    if length <= MAX_SEGMENT_SECONDS:
        return [start, end]
    pieces = math.ceil(length / PIECE_TARGET_SECONDS)
    bounds = [start]
    for k in range(1, pieces):
        bounds.append(round(start + length * k / pieces, 3))
    bounds.append(end)
    return bounds


def plan_segments(timings: list[dict], lines: list[dict], video_terms: list[str], end: float | None = None) -> list[dict]:
    """[{start, end, phrase, line_indexes}] that tile 0 .. narration end exactly (no gap, no overlap).

    One segment per line; neighbouring lines with the same phrase become one segment; a segment longer than 6 s is
    cut into 3-5 s pieces. A line's picture starts when the line starts, so the 0.25 s pause after a line belongs to
    that line's picture. `end` (the real narration length) replaces the last line's end when given."""
    if not timings or len(timings) != len(lines):
        raise FootageError(f"Footage planning needs one timing per script line (got {len(timings or [])} timings for {len(lines)} lines).")
    phrases = resolve_phrases(lines, video_terms)
    last_end = round(float(end if end is not None else timings[-1]["end"]), 3)
    spans = []
    for i in range(len(timings)):
        a = 0.0 if i == 0 else round(float(timings[i]["start"]), 3)
        b = round(float(timings[i + 1]["start"]), 3) if i + 1 < len(timings) else last_end
        spans.append((a, b))

    merged: list[dict] = []
    for i, (a, b) in enumerate(spans):
        if merged and normalize_phrase(merged[-1]["phrase"]) == normalize_phrase(phrases[i]):
            merged[-1]["end"] = b
            merged[-1]["lines"].append((i, a, b))
        else:
            merged.append({"start": a, "end": b, "phrase": phrases[i], "lines": [(i, a, b)]})

    segments: list[dict] = []
    for seg in merged:
        bounds = split_piece_bounds(seg["start"], seg["end"])
        for k in range(len(bounds) - 1):
            lo, hi = bounds[k], bounds[k + 1]
            indexes = [i for i, a, b in seg["lines"] if a < hi - 1e-6 and b > lo + 1e-6]
            segments.append({"start": lo, "end": hi, "phrase": seg["phrase"], "line_indexes": indexes})
    return segments


# --------------------------------------------------------------------------------------
# 2. Words, relevance and the choice of a clip (pure)
# --------------------------------------------------------------------------------------


def stem(word: str) -> str:
    """Crude singular form so 'pipes' matches 'pipe'. Used on both sides of every comparison."""
    w = word.lower()
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes")):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    return SYNONYMS.get(w, w)


def phrase_words(phrase: str) -> list[str]:
    """Meaningful words of a search phrase, as stems, without duplicates ('food in refrigerator' -> food, refrigerator)."""
    words = []
    for raw in re.split(r"[^a-z0-9]+", str(phrase).lower()):
        if len(raw) < 2 or raw in STOP_WORDS:
            continue
        w = stem(raw)
        if w not in words:
            words.append(w)
    return words


GENERIC_STEMS = {stem(w) for w in GENERIC_WORDS}
BLOCKED_STEMS = {stem(w) for w in BLOCKED_TAGS + BLOCKED_TAGS_EXTRA}


def specific_words(words: list[str]) -> list[str]:
    return [w for w in words if w not in GENERIC_STEMS]


def tag_words(hit: dict) -> set[str]:
    """All words of a hit's tags, as stems."""
    tags = hit.get("tags") if isinstance(hit, dict) else ""
    return {stem(w) for w in re.split(r"[^a-z0-9]+", str(tags or "").lower()) if len(w) >= 2}


def lead_tag_words(hit: dict) -> set[str]:
    """Words of the first LEAD_TAGS tags only (the tags that say what the clip is mainly about), as stems."""
    tags = [t for t in str(hit.get("tags") or "").split(",") if t.strip()] if isinstance(hit, dict) else []
    return {stem(w) for t in tags[:LEAD_TAGS] for w in re.split(r"[^a-z0-9]+", t.lower()) if len(w) >= 2}


def tag_position(hit: dict, words: list[str]) -> int:
    """How far back in the tag list the given words first appear (added up; 0 = all of them are the very first tag).
    Pixabay lists the tags that describe a clip best first, so a clip tagged 'desert, dunes, sand' shows a desert more
    surely than one tagged 'trees, forest, nature, fog, desert'."""
    tags = [t for t in str(hit.get("tags") or "").split(",") if t.strip()] if isinstance(hit, dict) else []
    sets = [{stem(w) for w in re.split(r"[^a-z0-9]+", t.lower()) if len(w) >= 2} for t in tags]
    return sum(next((i for i, found in enumerate(sets) if w in found), len(tags)) for w in words)


def blocked_tag(hit: dict) -> str | None:
    """The first tag word that suggests logos, text or brands (None if the hit is fine)."""
    for w in sorted(tag_words(hit)):
        if w in BLOCKED_STEMS:
            return w
    return None


def _stem_sequence(text: str) -> tuple[str, ...]:
    return tuple(stem(w) for w in re.split(r"[^a-z0-9]+", str(text).lower()) if len(w) >= 2)


BRAND_PRONE_SEQUENCES = [_stem_sequence(t) for t in BRAND_PRONE_TAGS]
MISLEADING_FALLBACK_STEMS = {stem(w) for w in MISLEADING_FALLBACK_TAGS}


def _contains_sequence(words: tuple[str, ...], wanted: tuple[str, ...]) -> bool:
    n = len(wanted)
    return n > 0 and any(words[i:i + n] == wanted for i in range(len(words) - n + 1))


def brand_prone_tag(hit: dict, phrase_words_: list[str] | None = None) -> str | None:
    """The first TAG (as written) that names something that usually carries a brand: a jet ski, a car, a boat, a
    product review. Tags are compared as whole tags (word by word, singular form), so 'jet ski' does not catch 'ski jump'.
    A thing that the search phrase itself is about is allowed ('car engine' may show a car)."""
    own = set(phrase_words_ or [])
    tags = [t for t in str(hit.get("tags") or "").split(",") if t.strip()] if isinstance(hit, dict) else []
    for tag in tags:
        words = _stem_sequence(tag)
        for wanted in BRAND_PRONE_SEQUENCES:
            if _contains_sequence(words, wanted) and not own & set(wanted):
                return tag.strip()
    return None


def misleading_fallback_tag(hit: dict, phrase_words_: list[str] | None = None) -> str | None:
    """A tag word (flame, cooking...) that makes a hit a bad stand-in for an unrelated line; None when it is fine or
    when the line's own phrase is about that."""
    own = set(phrase_words_ or [])
    for w in sorted(tag_words(hit)):
        if w in MISLEADING_FALLBACK_STEMS and w not in own:
            return w
    return None


def required_matches(words: list[str]) -> int:
    """How many SPECIFIC phrase words the tags must contain: all of them for phrases of up to two words ('pressure gauge'
    must not accept a clip that is only tagged 'low pressure' = weather), all but one for longer phrases."""
    n = len(specific_words(words) or words)
    return n if n <= 2 else n - 1


def relevance(words: list[str], hit: dict) -> tuple[list[str], bool]:
    """(phrase words found in the hit's tags, is it relevant?). Relevant = enough SPECIFIC phrase words are in the
    tags (see required_matches; generic words like 'open' or 'interior' do not count, unless every word is generic)
    AND at least one of them is among the first few tags, so a clip that mentions 'summer' as its 11th tag
    (it shows the sea) does not count as a 'hot summer day' clip."""
    have = tag_words(hit)
    matched = [w for w in words if w in have]
    specific = specific_words(words) or words
    enough = sum(1 for w in specific if w in have) >= required_matches(words)
    lead = lead_tag_words(hit)
    return matched, enough and any(w in lead for w in specific)


def query_variants(phrase: str) -> list[str]:
    """What to search for. Pixabay's search is loose for several words (it returns clips that match only one of them,
    and the real matches can sit beyond the first 50), so also search each specific word on its own."""
    words = phrase_words(phrase)
    variants = [normalize_phrase(phrase)]
    if len(words) > 1:
        for w in specific_words(words):
            if w not in variants:
                variants.append(w)
    return variants


def crop_box(width: int, height: int) -> dict:
    """The biggest centred 9:16 box inside a width x height picture, with even numbers: {x, y, w, h}."""
    if width * FRAME_H >= height * FRAME_W:  # as wide as 9:16 or wider: use the full height
        cw, ch = height * FRAME_W // FRAME_H, height
    else:  # taller than 9:16: use the full width
        cw, ch = width, width * FRAME_H // FRAME_W
    cw -= cw % 2
    ch -= ch % 2
    x = (width - cw) // 2
    y = (height - ch) // 2
    return {"x": x - x % 2, "y": y - y % 2, "w": cw, "h": ch}


def sharp_enough(width: int, height: int) -> bool:
    """Is a centre 9:16 crop at least 1080 px wide (so scaling it to 1080x1920 never enlarges it)?"""
    return crop_box(width, height)["w"] >= MIN_CROP_WIDTH


def bars_command(ffmpeg: str, clip: Path, offset: float, seconds: float, box: dict) -> list[str]:
    """ffmpeg command that reports (on stderr) the area of the 9:16 crop that is not black: the part of the clip that will
    really be used, `seconds` long, starting `offset` s in. reset=0 keeps the widest area seen in any frame."""
    vf = f"crop={box['w']}:{box['h']}:{box['x']}:{box['y']},cropdetect=limit=24:round=2:reset=0"
    return [ffmpeg, "-hide_banner", "-nostats", "-ss", f"{offset:.3f}", "-i", str(clip), "-t", f"{seconds:.2f}", "-an", "-vf", vf, "-f", "null", "-"]


def parse_cropdetect(text: str) -> tuple[int, int] | None:
    """(width, height) of the last 'crop=W:H:X:Y' line that ffmpeg's cropdetect printed, or None."""
    found = re.findall(r"crop=(\d+):(\d+):\d+:\d+", str(text or ""))
    return (int(found[-1][0]), int(found[-1][1])) if found else None


def has_black_bars(box: dict, detected: tuple[int, int] | None) -> bool:
    """Does the clip show black bars (letterbox) inside the 9:16 crop? Unknown (None) counts as no."""
    if not detected:
        return False
    return detected[0] < box["w"] * BARS_MIN_SHARE or detected[1] < box["h"] * BARS_MIN_SHARE


def orientation(width: int, height: int) -> str:
    return "portrait" if height > width else "landscape"


def _int_dim(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def rendition_options(hit: dict) -> list[dict]:
    """The renditions of a hit that can be used at all (url present, size known), smallest picture first."""
    options = []
    videos = hit.get("videos") if isinstance(hit, dict) else None
    for name, info in (videos.items() if isinstance(videos, dict) else []):
        if not isinstance(info, dict):
            continue
        url = info.get("url")
        width, height = _int_dim(info.get("width")), _int_dim(info.get("height"))
        if not isinstance(url, str) or not url.strip() or not width or not height:
            continue
        size = _int_dim(info.get("size"))
        if size > MAX_CLIP_BYTES:
            continue
        options.append({"name": name, "url": url, "width": width, "height": height, "size": size})
    return sorted(options, key=lambda o: (o["width"] * o["height"], o["name"]))


def collect_hits(phrase: str, search, page: int = 1, only: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Search for the phrase (and its single words), merge the answers: ([{hit, query, rank}] in discovery order,
    full) where `full` lists the search variants whose answer was a full page, so only those can have a next page.
    Page 1 calls search(query); later pages call search(query, page). `only`: ask just these variants (the ones that
    were full on the previous page); None asks all of them."""
    seen: set = set()
    entries = []
    full: list[str] = []
    for query in query_variants(phrase):
        if only is not None and query not in only:
            continue
        hits = (search(query) if page == 1 else search(query, page)) or []
        if len(hits) >= PER_PAGE:
            full.append(query)
        for rank, hit in enumerate(hits):
            if not isinstance(hit, dict) or hit.get("id") in seen:
                continue
            seen.add(hit.get("id"))
            entries.append({"hit": hit, "query": query, "rank": rank + (page - 1) * PER_PAGE})
    return entries, full


def rank_hits(entries: list[dict], phrase: str, need_seconds: float, used_ids: set, blocklist: dict | None = None,
              used_users: set | None = None, fallback_for: str | None = None) -> tuple[list[dict], dict]:
    """Usable clips for a segment, best first, and a count of why the others were refused.

    A clip is usable when it was not used yet, it is not on the reviewed blocklist, its tags are not blocked (logo/text
    words, or things that usually carry a brand: jet ski, car, boat, product review...), its tags match the phrase, it
    lasts at least `need_seconds`, and one of its renditions gives a sharp 9:16 crop. Best = an uploader that is not in
    the video yet (`used_users`: one uploader often posts a whole series of near-identical clips, and a repeat would show
    the same shot twice), then most phrase words in the tags, then the phrase words nearest the front of the tag list
    (tag_position: the best description comes first), then PORTRAIT before landscape (a portrait clip needs no
    crop), then Pixabay's own order. Of the renditions that are sharp enough the smallest picture is taken (smaller download).

    fallback_for: the line's OWN phrase when `phrase` is only a general video term standing in for it; flame/cooking
    pictures are then refused (they mislead), unless the line's own phrase is about that."""
    words = phrase_words(phrase)
    own_words = phrase_words(fallback_for) if fallback_for else words
    refused: dict[str, int] = {}

    def refuse(reason: str) -> None:
        refused[reason] = refused.get(reason, 0) + 1

    candidates = []
    for entry in entries:
        hit = entry["hit"]
        clip_id = hit.get("id")
        if clip_id is None:
            refuse("has no id")
            continue
        if clip_id in used_ids:
            refuse("already used in this video")
            continue
        if blocklist and str(clip_id) in blocklist:
            refuse("on the reviewed blocklist")
            continue
        bad = blocked_tag(hit)
        if bad:
            refuse(f"tag '{bad}' (logo/text/brand risk)")
            continue
        brand = brand_prone_tag(hit, own_words)
        if brand:
            refuse(f"tag '{brand}' (usually shows a brand)")
            continue
        if fallback_for:
            misleading = misleading_fallback_tag(hit, own_words)
            if misleading:
                refuse(f"tag '{misleading}' (misleading as a stand-in)")
                continue
        matched, relevant = relevance(words, hit)
        if not relevant:
            refuse("tags do not match the phrase")
            continue
        try:
            duration = float(hit.get("duration"))
        except (TypeError, ValueError):
            duration = 0.0
        if duration < need_seconds:
            refuse("too short")
            continue
        options = rendition_options(hit)
        if not options:
            refuse("no usable rendition")
            continue
        sharp = [o for o in options if sharp_enough(o["width"], o["height"])]
        if not sharp:
            refuse("picture too small for a sharp 9:16 crop")
            continue
        chosen = sharp[0]
        kind = orientation(chosen["width"], chosen["height"])
        box = crop_box(chosen["width"], chosen["height"])
        candidates.append({
            "id": clip_id,
            "rendition": chosen["name"],
            "url": chosen["url"],
            "width": chosen["width"],
            "height": chosen["height"],
            "size": chosen["size"],
            "orientation": kind,
            "duration": duration,
            "user": str(hit.get("user") or "").strip(),
            "user_id": hit.get("user_id"),
            "page_url": str(hit.get("pageURL") or "").strip(),
            "tags": str(hit.get("tags") or ""),
            "matched": matched,
            "position": tag_position(hit, matched),
            "crop": box,
            "found_by": entry["query"],
            "rank": entry["rank"],
            "reason": (
                f"{kind} {chosen['width']}x{chosen['height']} ('{chosen['name']}' rendition, crop {box['w']}x{box['h']}), "
                f"{duration:g} s long for {need_seconds - EXTRA_CLIP_SECONDS:.1f} s needed, tags match {matched} of {words}, "
                f"hit {entry['rank'] + 1} for search '{entry['query']}'"
            ),
        })
    seen_users = used_users or set()
    candidates.sort(key=lambda c: (1 if c["user_id"] in seen_users else 0, -len(c["matched"]), c["position"],
                                   0 if c["orientation"] == "portrait" else 1, c["rank"]))
    return candidates, refused


def line_label(segment: dict, lines: list[dict] | None) -> str:
    indexes = segment.get("line_indexes") or []
    if not indexes:
        return "a line"
    which = f"line {indexes[0]}" if len(indexes) == 1 else f"lines {indexes[0]}-{indexes[-1]}"
    if lines and 0 <= indexes[0] < len(lines):
        text = str(lines[indexes[0]].get("text", "")).strip()
        if text:
            which += f" (\"{text[:40]}{'...' if len(text) > 40 else ''}\")"
    return which


def shares_word(phrase: str, other: str) -> bool:
    """Do two search phrases have a SPECIFIC word in common ('open' or 'interior' alone do not count)?"""
    mine = phrase_words(phrase)
    return bool(set(specific_words(mine) or mine) & set(specific_words(phrase_words(other)) or phrase_words(other)))


def topic_noun_for(script: dict) -> tuple[str, bool]:
    """(the noun that must be on screen at 0 s, is it the default?). The script's own "topic_noun" (English, for example
    "refrigerator"); without one the first video term ("video_terms"[0]) is used."""
    noun = script.get("topic_noun") if isinstance(script, dict) else None
    if isinstance(noun, str) and noun.split():
        return " ".join(noun.split()), False
    for term in (script.get("video_terms") if isinstance(script, dict) else None) or []:
        if isinstance(term, str) and term.split():
            return " ".join(term.split()), True
    return "", True


def tags_show_topic(tags, noun: str) -> bool:
    """Do the FIRST LEAD_TAGS tags of a clip name the topic? Every specific word of the noun must be among the words of those
    tags, as a stem, so a plural or singular ('microwaves'/'microwave') and a synonym ('fridge'/'refrigerator') count too."""
    words = phrase_words(noun)
    need = specific_words(words) or words
    return bool(need) and set(need) <= lead_tag_words({"tags": tags})


def fallback_terms(phrase: str, terms: list[str], index: int) -> list[str]:
    """The video terms to try when the phrase itself finds nothing, best stand-in first: terms that share a word with
    the phrase ('refrigerator interior' -> 'refrigerator'), then the others, starting at a different term for every
    segment so the stand-ins vary."""
    rotated = [terms[(index + j) % len(terms)] for j in range(len(terms))] if terms else []
    related = [t for t in rotated if shares_word(phrase, t)]
    return related + [t for t in rotated if t not in related]


def choose_clips(segments: list[dict], video_terms: list[str], search, accept=None, lines: list[dict] | None = None, log=None,
                 blocklist: dict | None = None, topic_noun: str | None = None) -> list[dict]:
    """For every segment the best clip not used before. Returns one record per segment: the candidate dict plus
    "segment", "phrase_searched", "fallback" (True when the segment's own phrase found nothing and a video_term did)
    and "fallback_related" (that video term shares a word with the phrase; False = a general stand-in picture).

    search(query) -> list of Pixabay hits. accept(candidate, segment) -> bool is an optional last check (the runner
    downloads the file here and refuses a broken one); a refused candidate is skipped and the next one is tried.
    A phrase without a usable clip retries with the video_terms (related terms first, see fallback_terms); flame and
    cooking pictures are refused there. Another page of results is only asked for the search variants whose previous
    page was full.
    blocklist: {clip id: reason} of clips a person rejected after looking at them (load_clip_blocklist).
    topic_noun: the FIRST segment (on screen at 0 s) must use a clip whose first LEAD_TAGS tags show this noun (tags_show_topic).
    The segment's own phrase is tried first; when it delivers no such clip the noun itself is searched (such a pick is not a
    "fallback": it is exactly what the first picture is for); then the video terms, with the same condition. No clip at all
    is a plain FootageError that names the noun."""
    used: set = set()
    used_users: set = set()
    chosen: list[dict] = []
    terms = [" ".join(t.split()) for t in (video_terms or []) if isinstance(t, str) and t.split()]
    for index, seg in enumerate(segments):
        tail = BROLL_TAIL_SECONDS if index == len(segments) - 1 else 0.0  # the last picture runs a little past the narration
        need = (seg["end"] - seg["start"]) + tail + EXTRA_CLIP_SECONDS
        attempts = [seg["phrase"]]
        need_topic = bool(topic_noun) and index == 0
        if need_topic and normalize_phrase(topic_noun) != normalize_phrase(seg["phrase"]):
            attempts.append(topic_noun)
        for term in fallback_terms(seg["phrase"], terms, index):
            if normalize_phrase(term) not in {normalize_phrase(a) for a in attempts}:
                attempts.append(term)
        pick = None
        summaries = []
        for phrase in attempts:
            looked_at = 0
            refused_total: dict[str, int] = {}
            topic_search = need_topic and phrase == topic_noun and phrase != seg["phrase"]
            is_fallback = phrase != seg["phrase"] and not topic_search
            active = None  # search variants to ask on the next page (None = all)
            for page in range(1, MAX_PAGES + 1):
                entries, active = collect_hits(phrase, search, page, only=active)
                looked_at += len(entries)
                candidates, refused = rank_hits(entries, phrase, need, used, blocklist, used_users,
                                                fallback_for=seg["phrase"] if is_fallback else None)
                for reason, n in refused.items():
                    refused_total[reason] = refused_total.get(reason, 0) + n
                for cand in candidates:
                    if need_topic and not tags_show_topic(cand["tags"], topic_noun):
                        refused_total["the first tags do not show the topic"] = refused_total.get("the first tags do not show the topic", 0) + 1
                        continue
                    if accept is None or accept(cand, seg):
                        pick = {**cand, "segment": index, "phrase_searched": phrase, "fallback": is_fallback,
                                "fallback_related": shares_word(seg["phrase"], phrase) if is_fallback else True}
                        if need_topic:
                            pick["topic_noun"] = topic_noun
                            pick["topic_search"] = topic_search
                        break
                if pick or not active:
                    break
            if pick:
                break
            why = ", ".join(f"{n} {r}" for r, n in sorted(refused_total.items(), key=lambda kv: -kv[1])) or "no hits at all"
            summaries.append(f"'{phrase}': {looked_at} hits ({why})")
        if pick is None and need_topic:
            own_searches = 1 if normalize_phrase(topic_noun) == normalize_phrase(seg["phrase"]) else 2  # the phrase, and the noun when it is another word
            raise FootageError(
                f"No usable stock clip shows the topic '{topic_noun}' for the first seconds of the video ({line_label(seg, lines)}): "
                f"Pixabay has no clip that lists '{topic_noun}' among its first {LEAD_TAGS} tags and is also at least {need:.1f} s long "
                "and sharp when cropped to 9:16 (a landscape clip needs 4K for that: its 9:16 centre crop must be at least "
                f"{MIN_CROP_WIDTH} px wide). Searched: " + "; ".join(summaries[:own_searches]) + (" (the video terms were tried too)" if len(summaries) > own_searches else "") + ". "
                "Set \"topic_noun\" in script.json to another English word that Pixabay uses for the same thing "
                "(for example 'oven' instead of 'microwave'), or change line 0's \"broll\" phrase, and run again."
            )
        if pick is None:
            raise FootageError(
                f"No usable stock clip was found for {line_label(seg, lines)}, search phrase '{seg['phrase']}' "
                f"({seg['start']:.1f}-{seg['end']:.1f} s of the video, needs a clip of at least {need:.1f} s that is sharp when cropped to 9:16). "
                "Searched: " + "; ".join(summaries) + ". "
                "Change this line's \"broll\" phrase in script.json to a more common picture (one or two plain words, "
                "for example 'kitchen' or 'ice cubes') and run again."
            )
        used.add(pick["id"])
        if pick.get("user_id") is not None:
            used_users.add(pick["user_id"])
        chosen.append(pick)
        if log:
            note = ""
            if pick["fallback"]:
                note = f" [fallback search '{pick['phrase_searched']}'" + ("" if pick["fallback_related"] else ", NOT related to the phrase") + "]"
            elif pick.get("topic_search"):
                note = f" [topic search '{pick['phrase_searched']}': line 0's own phrase had no clip showing the topic]"
            if pick.get("topic_noun"):
                note += f" [topic '{pick['topic_noun']}' is among the first {LEAD_TAGS} tags]"
            log(f"  segment {index + 1}/{len(segments)} {seg['start']:.1f}-{seg['end']:.1f} s '{seg['phrase']}' -> "
                f"pixabay {pick['id']}: {pick['reason']}" + note)
    return chosen


def pick_offset(duration: float, segment_length: float) -> float:
    """Where in the clip to start (seconds): 0.5 s in, or the middle when the clip is much longer than the segment."""
    slack = max(0.0, duration - segment_length)
    if slack >= 3.0:
        return round(slack / 2, 3)
    return round(min(0.5, slack / 2), 3)


def frame_counts(segments: list[dict]) -> list[int]:
    """Frames per segment so that the pieces add up to the whole narration without drift
    (boundaries are rounded once, not piece by piece). The last boundary rounds UP and lies BROLL_TAIL_SECONDS past the
    narration, so the picture never ends early and MoneyPrinterTurbo (which wants audio + 0.1 s) never has to loop it."""
    bounds = [round(seg["start"] * FPS) for seg in segments] + [math.ceil((segments[-1]["end"] + BROLL_TAIL_SECONDS) * FPS - 1e-9)]
    counts = [bounds[k + 1] - bounds[k] for k in range(len(segments))]
    if any(c < 1 for c in counts):
        raise FootageError("A footage segment is shorter than one video frame; the narration timings look wrong.")
    return counts


# --------------------------------------------------------------------------------------
# Credits (pure)
# --------------------------------------------------------------------------------------


def clip_credits(chosen: list[dict]) -> list[dict]:
    """One {provider, id, user, page_url} per clip really used, in order of first use."""
    seen: set = set()
    credits = []
    for rec in chosen:
        if rec["id"] in seen:
            continue
        seen.add(rec["id"])
        credits.append({"provider": "pixabay", "id": rec["id"], "user": rec.get("user", ""), "page_url": rec.get("page_url", "")})
    return credits


def credit_line(credit: dict) -> str:
    user = str(credit.get("user") or "").strip()
    page = str(credit.get("page_url") or "").strip()
    line = f"Video by {user} on Pixabay" if user else "Video on Pixabay"
    return f"{line}: {page}" if page else line


# --------------------------------------------------------------------------------------
# ffmpeg command lines (pure)
# --------------------------------------------------------------------------------------


def segment_command(ffmpeg: str, clip: Path, offset: float, frames: int, box: dict, out: Path) -> list[str]:
    """Cut `frames` frames from `clip` (starting `offset` s in), centre crop to 9:16, scale to 1080x1920, 30 fps, no audio."""
    vf = (
        f"fps={FPS},crop={box['w']}:{box['h']}:{box['x']}:{box['y']},"
        f"scale={FRAME_W}:{FRAME_H}:flags=lanczos,setsar=1,format=yuv420p"
    )
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{offset:.3f}", "-i", str(clip), "-an",
        "-vf", vf, "-frames:v", str(int(frames)), "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out),
    ]


def concat_command(ffmpeg: str, listing: Path, out: Path) -> list[str]:
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", "-movflags", "+faststart", str(out)]


def concat_listing(files: list[Path]) -> str:
    return "".join("file '{}'\n".format(str(f).replace("'", "'\\''")) for f in files)


# --------------------------------------------------------------------------------------
# Pixabay (network; every network call can be replaced in tests)
# --------------------------------------------------------------------------------------


class PixabayClient:
    """Searches the Pixabay video API with a 24 hour on-disk cache. The key is kept private: repr() hides it, every
    error text goes through mask_secret()."""

    def __init__(self, api_key: str, cache_dir: Path = CACHE_DIR, urlopen=None, now=time.time, sleep=time.sleep):
        if not api_key:
            raise FootageError("No Pixabay API key is set in MoneyPrinterTurbo/config.toml (under [app], pixabay_api_keys).")
        self._key = api_key
        self.cache_dir = Path(cache_dir)
        self._urlopen = urlopen or default_urlopen
        self._now = now
        self._sleep = sleep
        self._sent: list[float] = []
        self.requests = 0
        self.cache_hits = 0

    def __repr__(self) -> str:
        return "PixabayClient(key=***)"

    def _mask(self, text) -> str:
        return mask_secret(text, self._key)

    @staticmethod
    def canonical_query(phrase: str, page: int = 1) -> str:
        """The query WITHOUT the key. Its sha256 names the cache file."""
        params = {"q": normalize_phrase(phrase), "per_page": PER_PAGE, "safesearch": "true", "video_type": "film"}
        if page != 1:
            params["page"] = page
        return urllib.parse.urlencode(sorted(params.items()))

    def cache_path(self, phrase: str, page: int = 1) -> Path:
        digest = hashlib.sha256(self.canonical_query(phrase, page).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, path: Path) -> list[dict] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if self._now() - float(data["ts"]) < CACHE_SECONDS and isinstance(data["response"]["hits"], list):
                return data["response"]["hits"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _throttle(self) -> None:
        now = self._now()
        self._sent = [t for t in self._sent if now - t < 60]
        if len(self._sent) >= REQUESTS_PER_MINUTE:
            self._sleep(max(0.0, 60 - (now - self._sent[0])) + 0.5)
            self._sent = [t for t in self._sent if self._now() - t < 60]
        self._sent.append(self._now())

    def search(self, phrase: str, page: int = 1) -> list[dict]:
        """Hits (a list of dicts) for the phrase; from the cache when the answer is younger than 24 hours."""
        path = self.cache_path(phrase, page)
        cached = self._read_cache(path)
        if cached is not None:
            self.cache_hits += 1
            return cached
        query = self.canonical_query(phrase, page)
        url = f"{PIXABAY_URL}?key={urllib.parse.quote(self._key)}&{query}"
        shown = normalize_phrase(phrase)
        body = None
        for attempt in range(3):
            self._throttle()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                with self._urlopen(req, 30) as resp:
                    body = resp.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 400 and page > 1:  # a page beyond the last one: Pixabay answers "out of valid range"
                    self._write_cache(path, query, {"hits": []})  # remember it, or every later run asks again
                    return []
                if exc.code == 429 and attempt < 2:
                    self._sleep(20)
                    continue
                hint = (" Check the key in MoneyPrinterTurbo/config.toml (pixabay_api_keys)." if exc.code in (400, 401, 403)
                        else " Wait a minute and run this again." if exc.code == 429 else "")
                raise FootageError(self._mask(f"Pixabay refused the search for '{shown}' (HTTP {exc.code}).{hint}")) from None
            except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
                raise FootageError(self._mask(
                    f"Pixabay could not be reached for the search '{shown}' ({type(exc).__name__}: {exc}). "
                    "Check the internet connection and run this again.")) from None
        try:
            data = json.loads(body.decode("utf-8"))
            hits = data["hits"]
            if not isinstance(hits, list):
                raise TypeError("hits is not a list")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise FootageError(f"Pixabay answered the search '{shown}' with something unexpected (no list of hits). Run this again later.") from None
        self._write_cache(path, query, data)
        return hits

    def _write_cache(self, path: Path, query: str, data: dict) -> None:
        """Write the answer through a temporary file with its own name (two runs at the same time never share one)."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.cache_dir, prefix=path.stem + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(json.dumps({"ts": self._now(), "query": query, "response": data}, ensure_ascii=False))
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def download_file(url: str, dest: Path, urlopen=None, max_bytes: int = MAX_CLIP_BYTES, timeout: float = 60,
                  max_seconds: float = DOWNLOAD_MAX_SECONDS, clock=time.monotonic) -> None:
    """Download url to dest through a temporary file next to it (own name for every call, so a broken or parallel
    download never looks like a finished one). `timeout` limits a single stall, `max_seconds` the whole download."""
    opener = urlopen or default_urlopen
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, part_name = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".part")
    part = Path(part_name)
    try:
        total = 0
        started = clock()
        with os.fdopen(fd, "wb") as out:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with opener(req, timeout) as resp:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise FootageError(f"A clip is bigger than {max_bytes // (1 << 20)} MB; skipped.")
                    if clock() - started > max_seconds:
                        raise FootageError(f"A clip download took longer than {max_seconds:.0f} s and was stopped.")
                    out.write(chunk)
        if total == 0:
            raise FootageError("A downloaded clip was empty.")
        os.replace(part, dest)
    except FootageError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        part.unlink(missing_ok=True)
        raise FootageError(mask_secret(f"A clip download failed ({type(exc).__name__}: {exc}).")) from None
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def prune_clips(clips_dir: Path, keep: set, max_bytes: int = CLIPS_MAX_BYTES, max_age_seconds: float = CLIPS_MAX_AGE_SECONDS,
                now=time.time) -> list[str]:
    """work/_clips is only a cache of downloads: delete clips nobody used for `max_age_seconds`, then the least recently
    used ones until the folder is below `max_bytes`, and leftover temporary *.part files. Files in `keep` (the clips of
    the video just made) are never touched. A file's modification time is its 'last used' time (see touch_clip).
    Returns the names deleted."""
    clips_dir = Path(clips_dir)
    deleted: list[str] = []
    if not clips_dir.is_dir():
        return deleted
    keep_names = {Path(k).name for k in keep}
    current = now()
    candidates = []  # (last used, size, path) of clips that may be deleted
    total = 0  # size of all clips, kept ones included
    for entry in clips_dir.iterdir():
        try:
            info = entry.stat()
        except OSError:
            continue
        if not entry.is_file():
            continue
        if entry.name.endswith(".part"):
            if current - info.st_mtime > STALE_TEMP_SECONDS:
                entry.unlink(missing_ok=True)
                deleted.append(entry.name)
        elif entry.name.endswith(".mp4"):
            total += info.st_size
            if entry.name not in keep_names:
                candidates.append((info.st_mtime, info.st_size, entry))
    for mtime, size, entry in sorted(candidates, key=lambda c: c[0]):  # least recently used first
        if current - mtime > max_age_seconds or total > max_bytes:
            entry.unlink(missing_ok=True)
            deleted.append(entry.name)
            total -= size
    return deleted


def touch_clip(path: Path, now=time.time) -> None:
    """Mark a clip as used just now (prune_clips deletes the longest unused first)."""
    try:
        os.utime(path, (now(), now()))
    except OSError:
        pass



# --------------------------------------------------------------------------------------
# ffprobe / ffmpeg runners
# --------------------------------------------------------------------------------------


def probe_video(ffprobe: str, path: Path, run=subprocess.run) -> dict:
    """{width, height, duration} as the picture is DISPLAYED (a clip stored sideways is swapped). Raises FootageError."""
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FootageError(f"ffprobe could not be run on {Path(path).name}: {type(exc).__name__}") from None
    if proc.returncode != 0:
        raise FootageError(f"ffprobe could not read {Path(path).name}: {proc.stderr.strip()[:200]}")
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError:
        raise FootageError(f"ffprobe gave unreadable output for {Path(path).name}.") from None
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise FootageError(f"{Path(path).name} has no video stream.")
    width, height = _int_dim(video.get("width")), _int_dim(video.get("height"))
    rotation = 0
    try:
        rotation = int(float((video.get("tags") or {}).get("rotate", 0)))
    except (TypeError, ValueError):
        pass
    for side in video.get("side_data_list") or []:
        if "rotation" in side:
            try:
                rotation = int(float(side["rotation"]))
            except (TypeError, ValueError):
                pass
    if abs(rotation) % 180 == 90:
        width, height = height, width
    try:
        duration = float((data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        try:
            duration = float(video.get("duration"))
        except (TypeError, ValueError):
            duration = 0.0
    if not width or not height or duration <= 0:
        raise FootageError(f"{Path(path).name} has no readable size or length.")
    return {"width": width, "height": height, "duration": duration}


def run_ffmpeg(cmd: list[str], what: str, timeout: float = 600, run=subprocess.run) -> None:
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise FootageError(f"{what} did not finish within {timeout:.0f} s and was stopped.") from None
    except OSError as exc:
        raise FootageError(f"{what} could not be started: {exc}") from None
    if proc.returncode != 0:
        raise FootageError(f"{what} failed: {(proc.stderr or proc.stdout or '').strip()[-300:]}")


# --------------------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------------------


def clip_path(clips_dir: Path, cand: dict) -> Path:
    return Path(clips_dir) / f"pixabay-{cand['id']}-{cand['rendition']}.mp4"


def build_broll(script: dict, timings: list[dict], total: float, work_dir: Path, api_key: str, ffmpeg: str, ffprobe: str,
                log=print, client: PixabayClient | None = None, clips_dir: Path = CLIPS_DIR, urlopen=None, run=subprocess.run) -> dict:
    """Plan, search, choose, download, cut and join. Returns
    {"path": work_dir/broll.mp4, "segments": [...], "credits": [...], "credit_lines": [...], "report": {...}}.
    Raises FootageError (plain-English message) on any problem."""
    work_dir, clips_dir = Path(work_dir), Path(clips_dir)
    lines = script["lines"]
    segments = plan_segments(timings, lines, script["video_terms"], end=total)
    log(f"  footage plan: {len(segments)} picture segments for {len(lines)} lines")
    client = client or PixabayClient(api_key, urlopen=urlopen)
    stats = {"downloads": 0, "clip_cache_hits": 0}
    probes: dict = {}
    rejected: set = set()  # clips that turned out to be unusable themselves: never downloaded or checked a second time
    max_downloads = len(segments) + DOWNLOAD_MARGIN

    def accept(cand: dict, seg: dict) -> bool:
        """Download (or reuse) the file and check what we really got; False = take the next candidate."""
        if cand["id"] in rejected:
            return False
        path = clip_path(clips_dir, cand)
        info = None
        if path.is_file():
            try:
                info = probe_video(ffprobe, path, run)
                stats["clip_cache_hits"] += 1
                touch_clip(path)
            except FootageError:
                path.unlink(missing_ok=True)
        if info is None:
            if stats["downloads"] >= max_downloads:
                raise FootageError(
                    f"Stopped after {stats['downloads']} clip downloads for {len(segments)} segments: too many clips turned out to be unusable. "
                    "Check the internet connection, or change some \"broll\" phrases, and run again.")
            stats["downloads"] += 1
            try:
                download_file(cand["url"], path, urlopen)
                info = probe_video(ffprobe, path, run)
            except FootageError as exc:
                path.unlink(missing_ok=True)
                rejected.add(cand["id"])
                log(f"  skipped pixabay {cand['id']}: {exc}")
                return False
        length = seg["end"] - seg["start"] + (BROLL_TAIL_SECONDS if seg is segments[-1] else 0.0)
        if not sharp_enough(info["width"], info["height"]):
            rejected.add(cand["id"])
            log(f"  skipped pixabay {cand['id']}: the file is {info['width']}x{info['height']}, too small for a sharp 9:16 crop (not as listed)")
            return False
        if info["duration"] < length + 0.3:  # only too short for THIS segment: a shorter segment may still use it
            log(f"  skipped pixabay {cand['id']}: the file lasts {info['duration']:.1f} s, this segment needs {length + 0.3:.1f} s (not as listed)")
            return False
        box = crop_box(info["width"], info["height"])
        try:
            sample = run(bars_command(ffmpeg, path, pick_offset(info["duration"], length), min(length, BARS_MAX_SAMPLE_SECONDS), box),
                         capture_output=True, text=True, timeout=180)
            detected = parse_cropdetect(sample.stderr) if sample.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            detected = None  # cannot check: do not refuse a clip for that
        if has_black_bars(box, detected):
            rejected.add(cand["id"])
            log(f"  skipped pixabay {cand['id']}: black bars inside the picture (only {detected[0]}x{detected[1]} of {box['w']}x{box['h']} is picture)")
            return False
        probes[cand["id"]] = info
        return True

    topic_noun, topic_default = topic_noun_for(script)
    chosen = choose_clips(segments, script["video_terms"], client.search, accept=accept, lines=lines, log=log, blocklist=load_clip_blocklist(),
                          topic_noun=topic_noun or None)
    unrelated = [(seg, rec) for seg, rec in zip(segments, chosen) if rec["fallback"] and not rec["fallback_related"]]
    if len(unrelated) > MAX_UNRELATED_SHARE * len(segments):
        shown = "; ".join(f"{line_label(seg, lines)} '{seg['phrase']}'" for seg, _ in unrelated[:6])
        raise FootageError(
            f"{len(unrelated)} of {len(segments)} picture segments found nothing for their own phrase and would show a general stand-in picture "
            f"that is not about their line ({shown}). Pixabay has little footage for these phrases. Change those lines' \"broll\" phrases in "
            "script.json to pictures Pixabay has plenty of (water, ice, snow, sky, cities, nature, plain everyday objects; machines "
            "and appliances are rare) and run again.")

    seg_dir = work_dir / "broll"
    seg_dir.mkdir(parents=True, exist_ok=True)
    counts = frame_counts(segments)
    files = []
    report_segments = []
    for k, (seg, rec, frames) in enumerate(zip(segments, chosen, counts)):
        info = probes[rec["id"]]
        box = crop_box(info["width"], info["height"])
        offset = pick_offset(info["duration"], frames / FPS)
        out = seg_dir / f"seg-{k:02d}.mp4"
        run_ffmpeg(segment_command(ffmpeg, clip_path(clips_dir, rec), offset, frames, box, out), f"ffmpeg (cut segment {k})", run=run)
        files.append(out)
        report_segments.append({
            "start": seg["start"], "end": seg["end"], "phrase": seg["phrase"], "line_indexes": seg["line_indexes"],
            "clip_id": rec["id"], "orientation": orientation(info["width"], info["height"]), "rendition": rec["rendition"],
            "source_size": f"{info['width']}x{info['height']}", "crop_source_size": f"{box['w']}x{box['h']}",
            "clip_seconds": round(info["duration"], 2), "offset": offset, "frames": frames,
            "searched_phrase": rec["phrase_searched"], "fallback": rec["fallback"],
            "fallback_related": rec["fallback_related"], "reason": rec["reason"],
        })
    listing = work_dir / "broll-concat.txt"
    listing.write_text(concat_listing(files), encoding="utf-8")
    final = work_dir / "broll.mp4"
    run_ffmpeg(concat_command(ffmpeg, listing, final), "ffmpeg (join segments)", run=run)
    info = probe_video(ffprobe, final, run)
    if (info["width"], info["height"]) != (FRAME_W, FRAME_H):
        raise FootageError(f"The joined footage is {info['width']}x{info['height']}, not {FRAME_W}x{FRAME_H}.")
    wanted = sum(counts) / FPS  # the narration + BROLL_TAIL_SECONDS, rounded up to whole frames
    if abs(info["duration"] - wanted) > LENGTH_TOLERANCE or info["duration"] < total + MIN_TAIL_SECONDS:
        raise FootageError(f"The joined footage is {info['duration']:.2f} s long but should be {wanted:.2f} s "
                           f"(narration {total:.2f} s + at least {MIN_TAIL_SECONDS} s; allowed difference {LENGTH_TOLERANCE} s).")
    credits = clip_credits(chosen)
    pruned = prune_clips(clips_dir, {clip_path(clips_dir, rec) for rec in chosen})
    report = {
        "provider": "pixabay",
        "segments": report_segments,
        "clips_used": len(credits),
        "downloads": stats["downloads"],
        "clip_cache_hits": stats["clip_cache_hits"],
        "search_requests": client.requests,
        "search_cache_hits": client.cache_hits,
        "broll_seconds": round(info["duration"], 3),
        "unrelated_fallbacks": sum(1 for r in report_segments if r["fallback"] and not r["fallback_related"]),
        "pruned_clips": pruned,
        "credits": credits,
    }
    if topic_noun:
        first_pick = chosen[0]
        lead = sorted(lead_tag_words({"tags": first_pick["tags"]}))
        report["topic"] = {
            "noun": topic_noun, "noun_is_default": topic_default, "clip_id": first_pick["id"],
            "searched_phrase": first_pick["phrase_searched"], "found_by_topic_search": bool(first_pick.get("topic_search")),
            "first_tags": [t.strip() for t in first_pick["tags"].split(",") if t.strip()][:LEAD_TAGS],
            "lead_tag_words": lead, "ok": tags_show_topic(first_pick["tags"], topic_noun),
        }
    return {"path": final, "segments": segments, "credits": credits, "credit_lines": [credit_line(c) for c in credits], "report": report}


# --------------------------------------------------------------------------------------
# Is MoneyPrinterTurbo's result still in OUR order? (frame comparison)
# --------------------------------------------------------------------------------------

SIGNATURE_W, SIGNATURE_H = 54, 60
SIGNATURE_CROP = "crop=1080:1200:0:0"  # only the top part: the burned-in captions start below y=1300


def mean_abs_diff(a: bytes, b: bytes) -> float:
    """Average difference (0-255) between two equally long grey pictures; 255 when they cannot be compared."""
    if not a or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def band_signature(ffmpeg: str, video: Path, seconds: float, crop: str, width: int, height: int, run=subprocess.run) -> bytes:
    """A tiny grey picture (width x height) of the part of the frame at `seconds` that the ffmpeg crop filter `crop` selects."""
    cmd = [ffmpeg, "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(video), "-frames:v", "1",
           "-vf", f"{crop},scale={width}:{height}:flags=area,format=gray", "-f", "rawvideo", "-"]
    try:
        proc = run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FootageError(f"ffmpeg could not read a frame of {Path(video).name}: {type(exc).__name__}") from None
    if proc.returncode != 0 or len(proc.stdout) != width * height:
        raise FootageError(f"ffmpeg could not read a frame of {Path(video).name} at {seconds:.1f} s.")
    return proc.stdout


def frame_signature(ffmpeg: str, video: Path, seconds: float, run=subprocess.run) -> bytes:
    """A tiny grey picture of the top part of the frame at `seconds`."""
    return band_signature(ffmpeg, video, seconds, SIGNATURE_CROP, SIGNATURE_W, SIGNATURE_H, run)


def check_order(ffmpeg: str, assembled: Path, broll: Path, times: list[float], limit: float = 20.0, run=subprocess.run) -> list[dict]:
    """Compare the assembled video with broll.mp4 at the given seconds. [{seconds, diff, same}]: same = the picture
    is the one we cut (mean grey difference below `limit`)."""
    results = []
    for t in times:
        diff = mean_abs_diff(frame_signature(ffmpeg, assembled, t, run), frame_signature(ffmpeg, broll, t, run))
        results.append({"seconds": round(t, 2), "diff": round(diff, 2), "same": diff < limit})
    return results


def middle_times(segments: list[dict]) -> list[float]:
    return [round((s["start"] + s["end"]) / 2, 3) for s in segments]


# --------------------------------------------------------------------------------------
# Command line: show the plan without downloading anything
# --------------------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="footage.py", description="Show which Pixabay clips would be used for a script (searches only, no downloads).")
    parser.add_argument("command", choices=("plan",))
    parser.add_argument("script", help="content/<id>/script.json")
    parser.add_argument("--timings", help="work/<id>/timings.json (default: work/<script id>/timings.json)")
    args = parser.parse_args(argv)
    client = None
    try:
        script = json.loads(Path(args.script).read_text(encoding="utf-8"))
        timings_path = Path(args.timings) if args.timings else WORK_ROOT / script["id"] / "timings.json"
        timings = json.loads(timings_path.read_text(encoding="utf-8"))
        key = load_pixabay_key()
        if not key:
            raise FootageError("No Pixabay API key in MoneyPrinterTurbo/config.toml.")
        segments = plan_segments(timings, script["lines"], script["video_terms"])
        client = PixabayClient(key)
        choose_clips(segments, script["video_terms"], client.search, lines=script["lines"], log=print, blocklist=load_clip_blocklist(),
                     topic_noun=topic_noun_for(script)[0] or None)
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAILED: {type(exc).__name__}: {mask_secret(exc)}", file=sys.stderr)
        return 1
    except FootageError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"({client.requests} searches sent, {client.cache_hits} answered from the cache)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
