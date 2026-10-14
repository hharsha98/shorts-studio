#!/usr/bin/env python3
"""Captions that show the SCRIPT's words with Whisper's timing.

Whisper (inside MoneyPrinterTurbo) hears the narration and writes one cue per word with a start and an end time.
It sometimes writes the wrong word ("rift" for "Trifft", "30er" for "Dreißiger"), but its timing is good.
The script is always right about the words. This module puts the two together:

    align_words(srt_cues, script_lines) -> one cue per SCRIPT word, shown exactly as written in the script
                                           (punctuation attached), timed from Whisper's cues
    group_phrases(words)                -> readable phrases for a YouTube .srt upload
    captions_match_script(words, lines) -> the gate: the caption words ARE the script words, nothing else
    hide_until(words, seconds)          -> the words that may be drawn while the hook card is NOT on screen
    hook_*                              -> the hook card's text rules and timing (the card itself is drawn by studio/visuals.py)

Everything here is a pure function (Python standard library only, no files, no network), so it is unit-tested in
studio/tests/test_captions.py. The words are drawn into the video by Remotion (studio/visuals.py).
"""

from __future__ import annotations

import difflib
import statistics
import unicodedata

MIN_WORD_SECONDS = 0.08  # a caption word stays on screen at least this long (2 frames at 30 fps)
GUESSED_WARN_SHARE = 0.10  # warn when more than this share of the words got their time by spreading/interpolating
FALLBACK_SECONDS_PER_CHAR = 0.07  # only used for missing words when no word at all could be matched

PHRASE_MAX_CHARS = 42  # one YouTube subtitle line
PHRASE_PAUSE_SECONDS = 0.35  # a pause this long ends a phrase
PHRASE_SOFT_MIN_CHARS = 18  # after a comma a phrase may end once it is this long
PHRASE_MIN_CUT_CHARS = 8  # a phrase that is too long is cut at an earlier comma only if the part before it is at least this long
PHRASE_MIN_SECONDS = 1.0  # a phrase is shown at least this long (as far as the next phrase allows)
SENTENCE_ENDINGS = ".!?…"
CLAUSE_ENDINGS = ",;:–—"
CLOSING_MARKS = "\"'”’»«“„)]}"

TIMING_HEARD = "heard"  # the word has its own Whisper timestamps (heard correctly, or heard as a different word)
TIMING_SPREAD = "spread"  # shares a block of Whisper time with other script words (split proportional to length)
TIMING_INTERPOLATED = "interpolated"  # Whisper heard nothing for this word; its time was found between its neighbours
_RANK = {TIMING_HEARD: 0, TIMING_SPREAD: 1, TIMING_INTERPOLATED: 2}


class CaptionError(ValueError):
    """The captions cannot be built or break a rule. The message says what is wrong."""


# --------------------------------------------------------------------------------------
# Words (the same normalisation the word error rate uses)
# --------------------------------------------------------------------------------------


def normalize_words(text: str) -> list[str]:
    """Lowercase, NFC, dashes become spaces, other punctuation/symbols are dropped, split to words."""
    text = unicodedata.normalize("NFC", text or "").lower()
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Pd" or ch == "/":
            out.append(" ")
        elif cat[0] in ("P", "S"):
            continue
        else:
            out.append(ch)
    return "".join(out).split()


def script_words(script_lines: list[str]) -> list[str]:
    """Every space-separated piece of the script, exactly as written (punctuation attached)."""
    return " ".join(script_lines).split()


def script_units(script_lines: list[str]) -> list[str]:
    """The words a viewer reads, one per caption: the script's pieces, as written.

    A piece with no letter or digit at all (a lone dash or "&") is not a word; it is shown together with the word
    before it ("Tom &"), or with the word after it when it comes first. Joined with a space, the units still split
    into exactly the script's pieces, which is what the "captions match script" gate checks.
    """
    units: list[str] = []
    carry: list[str] = []
    for piece in script_words(script_lines):
        if normalize_words(piece):
            units.append(" ".join([*carry, piece]))
            carry = []
        elif units:
            units[-1] += " " + piece
        else:
            carry.append(piece)
    return units


def captions_match_script(caption_texts: list[str], script_lines: list[str], skip: int = 0) -> tuple[bool, str]:
    """The gate: the caption words, joined, are the script's words, exactly (case, umlauts and punctuation included).

    skip: the number of script words at the very start that are NOT drawn on purpose (they are spoken while the hook card
    is on screen, see hide_until); the captions must then be exactly the script's words after those."""
    shown = " ".join(caption_texts).split()
    wanted = script_words(script_lines)[skip:]
    if shown == wanted:
        under_hook = f" (the first {skip} are spoken under the hook card and not drawn)" if skip else ""
        return True, f"all {len(wanted)} caption words are exactly the script's words, in order{under_hook}"
    for k, (a, b) in enumerate(zip(shown, wanted)):
        if a != b:
            return False, f"caption word {k + 1} is {a!r} but the script says {b!r}"
    return False, f"the captions have {len(shown)} words but the script has {len(wanted)}" + (f" (after skipping the first {skip})" if skip else "")


# --------------------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------------------


def _heard_tokens(srt_cues: list[dict]) -> list[tuple[str, float, float]]:
    """Whisper's words as (normalised word, start, end). A cue that holds several words ("non-stop") shares its time."""
    tokens: list[tuple[str, float, float]] = []
    for cue in srt_cues:
        words = normalize_words(str(cue.get("text", "")))
        if not words:
            continue
        start = float(cue["start"])
        end = max(float(cue["end"]), start)
        total = sum(len(w) for w in words)
        cursor = start
        for w in words:
            part = (end - start) * len(w) / total
            tokens.append((w, cursor, cursor + part))
            cursor += part
    return tokens


def _spread(span_start: float, span_end: float, weights: list[int]) -> list[tuple[float, float]]:
    """Cut [span_start, span_end] into pieces proportional to weights."""
    total = sum(weights)
    out = []
    cursor = span_start
    for k, w in enumerate(weights):
        end = span_end if k == len(weights) - 1 else cursor + (span_end - span_start) * w / total
        out.append((cursor, end))
        cursor = end
    return out


def _speech_rate(tokens: list[tuple[str, float, float]]) -> float:
    """Typical seconds per letter of the words Whisper heard (the median, so a long pause cannot skew it)."""
    rates = [(end - start) / len(word) for word, start, end in tokens if end - start > 0.02 and word]
    return statistics.median(rates) if rates else FALLBACK_SECONDS_PER_CHAR


def _slack(times: list, index: int | None) -> float:
    """How many seconds the word at `index` can give to a neighbour that needs room (half of what it has over 2x the minimum)."""
    if index is None or times[index] is None:
        return 0.0
    start, end = times[index]
    return max(0.0, (end - start) - 2 * MIN_WORD_SECONDS) * 0.5


def _fill_missing(times: list, weights: list[int], low: float, high: float, rate: float) -> None:
    """Give every script token that Whisper did not hear a time, in the gap between its neighbours.

    The gap is used as it is when it is about the right size. A gap that is too small (Whisper stretched its words
    over the missing one) borrows time from the two neighbours; a gap that is far too big (a long pause) is
    trimmed to a natural length and centred.
    """
    n = len(times)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = i - 1 if i > 0 else None
        right = j if j < n else None
        gap_start = times[left][1] if left is not None else low
        gap_end = times[right][0] if right is not None else high
        gap = max(0.0, gap_end - gap_start)
        run = weights[i:j]
        need = max(len(run) * MIN_WORD_SECONDS, sum(run) * rate)
        if gap < need:
            give_left, give_right = _slack(times, left), _slack(times, right)
            take = min(need - gap, give_left + give_right)
            if take > 0:
                share_left = take * give_left / (give_left + give_right)
                share_right = take - share_left
                if left is not None and share_left > 0:
                    times[left] = (times[left][0], times[left][1] - share_left)
                if right is not None and share_right > 0:
                    times[right] = (times[right][0] + share_right, times[right][1])
                gap_start -= share_left
                gap_end += share_right
        elif gap > 1.5 * need:
            middle = (gap_start + gap_end) / 2
            gap_start, gap_end = middle - 0.75 * need, middle + 0.75 * need
        for k, piece in enumerate(_spread(gap_start, max(gap_end, gap_start), run)):
            times[i + k] = piece
        i = j


def _enforce(starts: list[int], ends: list[int], low: int, high: int, minimum: int) -> None:
    """Make the cues valid, in whole milliseconds: inside [low, high], each at least `minimum` long, strictly in
    order, never overlapping. A cue that is too short is stretched, the cues after it are pushed later; if that
    runs past `high` they are pulled back from the end."""
    n = len(starts)
    if n * minimum > high - low:
        raise CaptionError(
            f"{n} caption words need at least {n * minimum} ms but the narration is only {high - low} ms long"
        )
    previous_end = low
    for i in range(n):
        start = max(min(starts[i], high), previous_end)
        end = max(min(ends[i], high), start + minimum)
        starts[i], ends[i] = start, end
        previous_end = end
    next_start = high
    for i in range(n - 1, -1, -1):
        end = min(ends[i], next_start)
        start = min(starts[i], end - minimum)
        starts[i], ends[i] = start, end
        next_start = start


def caption_problems(words: list[dict], end_limit: float, minimum: float = MIN_WORD_SECONDS) -> list[str]:
    """Every rule the caption cues must keep; an empty list means they are valid. Used as the gate AND as the
    self-check inside align_words (the rules: in order, never overlapping, strictly increasing starts, each at
    least `minimum` long, everything inside [0, end_limit])."""
    problems = []
    eps = 1e-6
    for k, word in enumerate(words):
        label = f"caption word {k + 1} ({word['text']!r})"
        start, end = word["start"], word["end"]
        if start < -eps:
            problems.append(f"{label} starts before the narration ({start:.3f} s)")
        if end > end_limit + eps:
            problems.append(f"{label} ends at {end:.3f} s, after the narration ends ({end_limit:.3f} s)")
        if end - start < minimum - eps:
            problems.append(f"{label} is only {end - start:.3f} s long (minimum {minimum:g} s)")
        if k:
            before = words[k - 1]
            if start <= before["start"] + eps:
                problems.append(f"{label} starts at {start:.3f} s, not after the previous word ({before['start']:.3f} s)")
            if start < before["end"] - eps:
                problems.append(f"{label} starts at {start:.3f} s but the previous word runs until {before['end']:.3f} s (overlap)")
    return problems


def align_words(srt_cues: list[dict], script_lines: list[str], end_limit: float | None = None) -> list[dict]:
    """One cue per SCRIPT word, shown exactly as the script writes it, timed from Whisper's word cues.

    srt_cues: [{"start", "end", "text"}] in seconds, one per word Whisper heard (parse_srt output).
    script_lines: the script's line texts.
    end_limit: end of the narration in seconds (default: the end of Whisper's last cue).
    Returns [{"text", "start", "end", "timing"}] with timing = "heard" | "spread" | "interpolated".

    The two word lists are compared after the same normalisation as the word error rate (lowercase, no
    punctuation, dashes split a word):
      equal      the script word takes Whisper's time.
      replace    same number of words (a misheard word): each takes its own Whisper word's time. Different
                 numbers ("Dreißigerjahren" heard as "30er Jahren", "non-stop" heard as "nonstop"): the whole
                 block of time is shared by the script words, in proportion to their length.
      missing    Whisper did not hear the script word: it gets time in the gap between its neighbours
                 (borrowing a little from them when the gap is too small).
      extra      Whisper heard a word that is not in the script: it is dropped and its time goes to the
                 neighbouring words.
    Raises CaptionError when the result would break a rule (see caption_problems).
    """
    units = script_units(script_lines)
    if not units:
        return []
    heard = _heard_tokens(srt_cues)
    if end_limit is None:
        end_limit = max((float(c["end"]) for c in srt_cues), default=None)
        if end_limit is None:
            raise CaptionError("cannot time the captions: Whisper wrote no words and the narration length is unknown")
    low, high = 0.0, float(end_limit)

    tokens: list[tuple[str, int]] = [(w, u) for u, text in enumerate(units) for w in normalize_words(text)]
    count = len(tokens)
    times: list = [None] * count  # (start, end) per script token
    how: list = [TIMING_INTERPOLATED] * count
    extras: list[tuple[int, int, int]] = []  # (index of the script token after it, first heard index, last heard index + 1)

    matcher = difflib.SequenceMatcher(a=[w for w, _u in tokens], b=[w for w, _s, _e in heard], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (heard[j1 + k][1], heard[j1 + k][2])
                how[i1 + k] = TIMING_HEARD
        elif tag == "replace":
            pieces = _spread(heard[j1][1], heard[j2 - 1][2], [max(1, len(tokens[i][0])) for i in range(i1, i2)])
            one_word = len({tokens[i][1] for i in range(i1, i2)}) == 1  # a split compound / digits: the word's span is exact
            for k, piece in enumerate(pieces):
                times[i1 + k] = piece
                how[i1 + k] = TIMING_HEARD if one_word else TIMING_SPREAD
        elif tag == "insert":
            extras.append((i1, j1, j2))
        # "delete": the tokens stay None and are filled below

    rate = _speech_rate(heard)
    weights = [max(1, len(w)) for w, _u in tokens]

    if all(t is None for t in times):  # Whisper gave us nothing to hold on to: spread over the whole narration
        for k, piece in enumerate(_spread(low, high, weights)):
            times[k] = piece
    else:
        for after, j1, j2 in extras:  # drop the extra words, give their time to the neighbours
            first, last = heard[j1][1], heard[j2 - 1][2]
            middle = (first + last) / 2
            before_i, after_i = after - 1, after
            if before_i >= 0 and times[before_i] is not None and after_i < count and times[after_i] is not None:
                times[before_i] = (times[before_i][0], max(times[before_i][1], middle))
                times[after_i] = (min(times[after_i][0], middle), times[after_i][1])
            elif before_i >= 0 and times[before_i] is not None:
                times[before_i] = (times[before_i][0], max(times[before_i][1], last))
            elif after_i < count and times[after_i] is not None:
                times[after_i] = (min(times[after_i][0], first), times[after_i][1])
        _fill_missing(times, weights, low, high, rate)

    starts: list[int] = []
    ends: list[int] = []
    timing: list[str] = []
    for u in range(len(units)):
        members = [k for k, (_w, unit) in enumerate(tokens) if unit == u]
        starts.append(round(min(times[k][0] for k in members) * 1000))
        ends.append(round(max(times[k][1] for k in members) * 1000))
        timing.append(max((how[k] for k in members), key=_RANK.__getitem__))

    high_ms = int(high * 1000 + 1e-6)
    _enforce(starts, ends, round(low * 1000), high_ms, round(MIN_WORD_SECONDS * 1000))
    words = [
        {"text": units[u], "start": starts[u] / 1000, "end": ends[u] / 1000, "timing": timing[u]} for u in range(len(units))
    ]
    problems = caption_problems(words, high)
    if problems:
        raise CaptionError("the aligned captions break a rule: " + "; ".join(problems[:5]))
    ok, detail = captions_match_script([w["text"] for w in words], script_lines)
    if not ok:  # cannot happen (the text comes from the script); this keeps it that way
        raise CaptionError(detail)
    return words


def alignment_stats(words: list[dict]) -> dict:
    """How the words got their time. "guessed" = spread + interpolated: timed by arithmetic, not by Whisper."""
    total = len(words)
    heard = sum(1 for w in words if w.get("timing") == TIMING_HEARD)
    spread = sum(1 for w in words if w.get("timing") == TIMING_SPREAD)
    interpolated = sum(1 for w in words if w.get("timing") == TIMING_INTERPOLATED)
    guessed = spread + interpolated
    return {
        "words": total,
        "heard": heard,
        "spread": spread,
        "interpolated": interpolated,
        "guessed": guessed,
        "guessed_share": round(guessed / total, 4) if total else 0.0,
    }


def guessed_warning(stats: dict) -> str | None:
    """A warning when more than 10% of the words were timed by spreading or interpolating, else None."""
    if stats["words"] and stats["guessed_share"] > GUESSED_WARN_SHARE:
        return (
            f"{stats['guessed']} of {stats['words']} caption words ({stats['guessed_share'] * 100:.1f}%) got their time by "
            f"spreading or interpolating ({stats['spread']} spread, {stats['interpolated']} interpolated), more than "
            f"{GUESSED_WARN_SHARE * 100:.0f}%: Whisper heard those parts badly, so look at them in the video"
        )
    return None


# --------------------------------------------------------------------------------------
# Hook card: text rules, timing, and hiding the captions underneath it (pure)
# --------------------------------------------------------------------------------------

HOOK_LINE1_MAX = 26  # characters
HOOK_LINE2_MAX = 30
HOOK_MIN_SECONDS = 2.5  # the hook card stays at least this long ...
HOOK_MAX_SECONDS = 3.5  # ... and never longer than this, however long line 0 is
HOOK_FADE_SECONDS = 0.25  # it fades out over this long AFTER hook_end


def _accent_key(text: str) -> str:
    """A word for comparing: lowercase, no punctuation ('Why?' and 'why' are the same; dashes become spaces)."""
    return " ".join(normalize_words(text))


def accent_token(line: str, accent: str) -> int | None:
    """Index of the first space-separated piece of `line` that is the accent word (case and punctuation ignored), or None."""
    key = _accent_key(accent)
    if not key:
        return None
    for k, piece in enumerate(str(line).split()):
        if _accent_key(piece) == key:
            return k
    return None


def hook_problems(hook) -> list[str]:
    """Plain-English problems with the script's "hook" object (empty list = fine). It is two short lines for the title card
    that sits over the first seconds of the video, plus one accent word that is drawn in the accent colour."""
    if not isinstance(hook, dict):
        return ['hook must be an object like {"line1": "...", "line2": "...", "accent": "..."}']
    problems = []
    for key, limit in (("line1", HOOK_LINE1_MAX), ("line2", HOOK_LINE2_MAX)):
        value = hook.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"hook.{key} must be a non-empty text")
        elif len(value.strip()) > limit:
            problems.append(f"hook.{key} is {len(value.strip())} characters long; the limit is {limit}")
    accent = hook.get("accent")
    if not isinstance(accent, str) or not accent.strip():
        problems.append("hook.accent must be one word of line1 or line2")
    elif len(accent.split()) != 1:
        problems.append(f"hook.accent must be ONE word (got {accent!r})")
    elif not problems and accent_token(hook["line1"], accent) is None and accent_token(hook["line2"], accent) is None:
        problems.append(f"hook.accent {accent!r} is not a word of hook.line1 or hook.line2")
    return problems


def hook_lines(hook: dict) -> list[str]:
    return [hook["line1"].strip(), hook["line2"].strip()]


def hook_segments(hook: dict) -> list[list[dict]]:
    """The two lines as runs of text for the card: [[{"text", "accent"}...] per line]. The accent word (its first occurrence,
    line 1 before line 2; punctuation stuck to it is coloured too) is its own run; the spaces around it stay with the plain runs."""
    lines = hook_lines(hook)
    found = None
    for number, line in enumerate(lines):
        index = accent_token(line, hook["accent"])
        if index is not None:
            found = (number, index)
            break
    out = []
    for number, line in enumerate(lines):
        pieces = line.split()
        if found is None or found[0] != number:
            out.append([{"text": " ".join(pieces), "accent": False}])
            continue
        i = found[1]
        runs = []
        if i > 0:
            runs.append({"text": " ".join(pieces[:i]) + " ", "accent": False})
        runs.append({"text": pieces[i], "accent": True})
        if i < len(pieces) - 1:
            runs.append({"text": " " + " ".join(pieces[i + 1:]), "accent": False})
        out.append(runs)
    return out


def hook_end_seconds(timings: list[dict]) -> float:
    """When the hook card is fully faded in place and starts to fade out: the end of line 0, but at least HOOK_MIN_SECONDS and
    at most HOOK_MAX_SECONDS. (The fade-out then takes HOOK_FADE_SECONDS more.)"""
    if not timings:
        raise CaptionError("cannot time the hook card: there are no line timings")
    first = next((t for t in timings if isinstance(t, dict) and t.get("index", 0) == 0), timings[0])
    return round(min(HOOK_MAX_SECONDS, max(HOOK_MIN_SECONDS, float(first["end"]))), 3)


def hook_panel_free_from(hook_end: float) -> float:
    """The first second at which a diagram panel may start: the hook card has finished fading out (hook_end + HOOK_FADE_SECONDS).
    A panel that starts while the card is still fading would be drawn over the half-transparent card."""
    return hook_end + HOOK_FADE_SECONDS


def hook_panel_problems(lines: list[dict], timings: list[dict], hook_end: float) -> list[str]:
    """Diagram panels may not start before the hook card is gone (line 0 can have none; the card covers the same area): not at
    hook_end, when the card begins to fade out, but only from hook_end + HOOK_FADE_SECONDS, when the fade is over."""
    problems = []
    free_from = hook_panel_free_from(hook_end)
    for index, line in enumerate(lines):
        if not (isinstance(line, dict) and line.get("visual")):
            continue
        entry = next((t for t in timings if isinstance(t, dict) and t.get("index", None) == index), None)
        if index == 0:
            problems.append("line 0 has a visual, but the hook card is on screen at the start: remove the visual from line 0")
        elif entry is not None and float(entry["start"]) < free_from - 1e-6:
            problems.append(
                f"line {index} has a visual that would start at {float(entry['start']):.2f} s, but the hook card is on screen until "
                f"{hook_end:.2f} s and fades out until {free_from:.2f} s: "
                f"move that visual to a later line (or make lines 0-{index} longer)")
    return problems


def hide_until(words: list[dict], hook_end: float, minimum: float = MIN_WORD_SECONDS) -> tuple[list[dict], int]:
    """The caption words that may be drawn while a hook card covers 0 .. hook_end.

    A word that ends by hook_end is not drawn; a word that is still being spoken at hook_end is drawn from hook_end on
    (dropped when less than `minimum` of it is left). Returns (words to draw, number of script words not drawn at the start)
    so the caller can check the rest against the script (captions_match_script(skip=...))."""
    shown = []
    hidden_pieces = 0
    for word in words:
        if word["end"] <= hook_end + 1e-6:
            hidden_pieces += len(word["text"].split())
        elif word["start"] < hook_end - 1e-6:
            if word["end"] - hook_end >= minimum - 1e-6:
                shown.append({**word, "start": hook_end})
            else:
                hidden_pieces += len(word["text"].split())
        else:
            shown.append(dict(word))
    return shown, hidden_pieces


# --------------------------------------------------------------------------------------
# Phrases for the YouTube .srt
# --------------------------------------------------------------------------------------


def _ends_with(text: str, marks: str) -> bool:
    bare = text.rstrip(CLOSING_MARKS)
    return bool(bare) and bare[-1] in marks


def _comma_cut(current: list[dict], word: dict, max_chars: int) -> int:
    """Where to end the phrase `current` when `word` does not fit any more: the number of words to keep, or 0.

    The last word inside the phrase that ends with a comma/semicolon/colon, if what is left over plus `word` fits
    on one line and the part kept is at least PHRASE_MIN_CUT_CHARS long."""
    for cut in range(len(current) - 1, 0, -1):
        if not _ends_with(current[cut - 1]["text"], CLAUSE_ENDINGS):
            continue
        kept = len(" ".join(w["text"] for w in current[:cut]))
        rest = len(" ".join(w["text"] for w in current[cut:] + [word]))
        if kept >= PHRASE_MIN_CUT_CHARS and rest <= max_chars:
            return cut
    return 0


def group_phrases(
    words: list[dict],
    max_chars: int = PHRASE_MAX_CHARS,
    pause: float = PHRASE_PAUSE_SECONDS,
    min_seconds: float = PHRASE_MIN_SECONDS,
    end_limit: float | None = None,
) -> list[dict]:
    """Readable subtitle phrases from the per-word cues: [{"start", "end", "text"}], one line each.

    A phrase ends after a sentence ending (. ! ? …), at a pause of `pause` seconds or more between two words,
    after a comma/semicolon/colon once it is PHRASE_SOFT_MIN_CHARS long, and before the word that would make it longer
    than `max_chars` (then at an earlier comma if there is one, so a single word is not left alone). It starts with its first word and ends with its last; a phrase shorter than `min_seconds` is
    kept on screen a little longer as far as the next phrase (or `end_limit`) allows. Phrases never overlap.
    """
    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if current:
            before_len = len(" ".join(w["text"] for w in current))
            joined = before_len + 1 + len(word["text"])
            last = current[-1]
            natural_end = (
                _ends_with(last["text"], SENTENCE_ENDINGS)
                or word["start"] - last["end"] >= pause - 1e-9
                or (_ends_with(last["text"], CLAUSE_ENDINGS) and before_len >= PHRASE_SOFT_MIN_CHARS)
            )
            if joined > max_chars and not natural_end:
                # Too long: rather end the phrase at an earlier comma than leave one word alone on the next line.
                cut = _comma_cut(current, word, max_chars)
                if cut:
                    groups.append(current[:cut])
                    current = current[cut:]
                    before_len = len(" ".join(w["text"] for w in current))
                    joined = before_len + 1 + len(word["text"])
            if natural_end or joined > max_chars:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)

    phrases = []
    for k, group in enumerate(groups):
        start, end = group[0]["start"], group[-1]["end"]
        room = groups[k + 1][0]["start"] if k + 1 < len(groups) else end_limit
        if end - start < min_seconds:
            want = start + min_seconds
            end = max(end, min(want, room) if room is not None else want)
        phrases.append({"start": round(start, 3), "end": round(end, 3), "text": " ".join(w["text"] for w in group)})
    return phrases
