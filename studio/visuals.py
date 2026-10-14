#!/usr/bin/env python3
"""Animated explainer panels for Shorts: render with Remotion, overlay with ffmpeg.

Public entry point (called by make_video.py):

    render_and_overlay(base_mp4, script, timings, out_mp4, work_dir) -> dict

For every script line that has a ``visual`` this renders one transparent 1080x1080
panel (Remotion composition "ShortsPanel", ProRes 4444 with alpha), then puts all
panels on the base video in ONE ffmpeg pass at x=0, y=160 (nothing below y=1250,
that area belongs to the captions).

The captions go through the same pass: with ``captions=...`` the one-word-at-a-time caption track
is rendered too (Remotion composition "WordCaptions", transparent 1080x560 ProRes 4444) and overlaid
at x=0, y=1300, so the video is re-encoded only once. The caption .mov is deleted afterwards.

The hook card too: with ``hook=...`` a two-line title card (Remotion composition "HookCard", transparent 1080x450)
sits over the first seconds at x=0, y=250: fully visible from frame 0 (it is the cover frame) until ``hook_end``,
then a 0.25 s fade-out. No panel may start before hook_end + 0.25 s (the fade is over) and no caption word may be drawn before hook_end.

Python standard library only. Run ``python3 studio/visuals.py --demo`` to build a
demo video, a contact sheet and one frame grab per panel type.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import captions as captionlib  # studio/captions.py: the hook card's text rules and timing (pure functions)

# --------------------------------------------------------------------------- constants

REMOTION_DIR = "/Users/harsha/MediaStudio/video"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

PANEL_X = 0
PANEL_Y = 160  # panel covers y 160..1240 of the 1080x1920 frame
PANEL_FPS = 30  # must match PANEL_FPS in ShortsPanel.tsx
MIN_PANEL_SECONDS = 2.0
PANEL_TAIL_SECONDS = 0.3  # panel stays a moment after the spoken line ends
MIN_CAPPED_SECONDS = 1.0  # never shrink a panel below this just to avoid overlap

# Limits from the shared script.json contract (counted in characters, so umlauts count once).
MAX_TITLE = 32
MAX_STEP = 22
MIN_STEPS, MAX_STEPS = 2, 5
MAX_STAT_VALUE = 10
MAX_STAT_LABEL = 40
MAX_HEADING = 12
MAX_SIDE_TEXT = 48

VISUAL_TYPES = ("flow", "stat", "compare")

# One-word-at-a-time caption track (Remotion composition "WordCaptions").
CAPTION_COMPOSITION = "WordCaptions"
CAPTION_X = 0
CAPTION_Y = 1300  # top of the caption box; make_video.CAPTION_BOX_TOP_Y must be the same (a unit test checks it)
CAPTION_W, CAPTION_H = 1080, 560  # canvas of the caption track; the frame below y=1300 has room for it (1300 + 560 < 1920)
CAPTION_FPS = 30  # must match CAPTION_FPS in WordCaptions.tsx
CAPTION_TAIL_SECONDS = 0.2  # the track runs this long after the last word (the overlay shows the video as it is after the track ends)

# Hook card (Remotion composition "HookCard"): two big lines in the top third of the frame.
HOOK_COMPOSITION = "HookCard"
HOOK_X = 0
HOOK_Y = 250  # top of the card's canvas; the canvas covers y 250..700
HOOK_W, HOOK_H = 1080, 450
HOOK_FPS = 30  # must match HOOK_FPS in HookCard.tsx
HOOK_FADE_SECONDS = captionlib.HOOK_FADE_SECONDS
HOOK_ACCENT_COLOR = "#FFB000"  # the same amber as the diagram panels


class VisualError(ValueError):
    """The script has a visual that breaks the contract. The message names line and field."""


# --------------------------------------------------------------------------- validation


def _check_text(value, path: str, max_len: int, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{path}: must be a string, got {type(value).__name__}")
        return
    text = value.strip()
    if not text:
        errors.append(f"{path}: must not be empty")
    elif len(text) > max_len:
        errors.append(f'{path}: {len(text)} characters, maximum is {max_len} ("{text}")')


def _check_side(side, path: str, errors: list[str]) -> None:
    if not isinstance(side, dict):
        errors.append(f"{path}: must be an object with heading and text")
        return
    _check_text(side.get("heading"), f"{path}.heading", MAX_HEADING, errors)
    _check_text(side.get("text"), f"{path}.text", MAX_SIDE_TEXT, errors)


def validate_visual(visual, line_index: int) -> list[str]:
    """Return a list of problems (empty list = valid). ``None`` means "no visual" and is valid."""
    if visual is None:
        return []
    base = f"lines[{line_index}].visual"
    if not isinstance(visual, dict):
        return [f"{base}: must be an object or null, got {type(visual).__name__}"]

    errors: list[str] = []
    vtype = visual.get("type")
    if vtype not in VISUAL_TYPES:
        return [f'{base}.type: must be one of {", ".join(VISUAL_TYPES)}, got {vtype!r}']

    if vtype == "flow":
        _check_text(visual.get("title"), f"{base}.title", MAX_TITLE, errors)
        steps = visual.get("steps")
        if not isinstance(steps, list):
            errors.append(f"{base}.steps: must be a list of {MIN_STEPS}-{MAX_STEPS} strings")
        else:
            if not MIN_STEPS <= len(steps) <= MAX_STEPS:
                errors.append(f"{base}.steps: {len(steps)} items, must have {MIN_STEPS}-{MAX_STEPS}")
            for i, step in enumerate(steps):
                _check_text(step, f"{base}.steps[{i}]", MAX_STEP, errors)
    elif vtype == "stat":
        _check_text(visual.get("value"), f"{base}.value", MAX_STAT_VALUE, errors)
        _check_text(visual.get("label"), f"{base}.label", MAX_STAT_LABEL, errors)
    else:  # compare
        _check_text(visual.get("title"), f"{base}.title", MAX_TITLE, errors)
        _check_side(visual.get("left"), f"{base}.left", errors)
        _check_side(visual.get("right"), f"{base}.right", errors)
    return errors


def validate_script_visuals(script: dict) -> list[str]:
    """Validate every visual in script["lines"]. Returns all problems found."""
    lines = script.get("lines")
    if not isinstance(lines, list):
        return ["lines: must be a list"]
    errors: list[str] = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            errors.append(f"lines[{i}]: must be an object")
            continue
        errors.extend(validate_visual(line.get("visual"), i))
    return errors


# --------------------------------------------------------------------------- planning (pure)


def _timing_for_line(timings: list[dict], line_index: int):
    """Find the timing entry of a line: by its "index" key, falling back to list position."""
    for pos, entry in enumerate(timings):
        if isinstance(entry, dict) and entry.get("index", pos) == line_index:
            return entry
    return None


def plan_panels(script: dict, timings: list[dict], video_duration: float | None = None) -> list[dict]:
    """Decide which panels to render and when they show.

    Each result: {"index", "visual", "start", "seconds", "end", "name"}.
    seconds = max(2.0, line length + 0.3). Panels share one spot on screen, so they
    never overlap: a panel always ends at the next panel's start (never later).
    If the next panel starts less than MIN_CAPPED_SECONDS after it, the EARLIER panel
    is dropped (a card that is up for under a second cannot be read); the later one
    wins, so a chain of very close panels leaves only the last. A panel is also
    shortened to the end of the video when at least 1 second is left.
    seconds is rounded to whole frames; end = start + seconds (capped panels round
    down, so they never reach into the next panel). Dropped lines are simply absent
    from the result (render_and_overlay warns about them).
    """
    errors = validate_script_visuals(script)
    if errors:
        raise VisualError("; ".join(errors))

    wanted = [(i, line["visual"]) for i, line in enumerate(script["lines"]) if line.get("visual")]
    plan: list[dict] = []
    for i, visual in wanted:
        entry = _timing_for_line(timings, i)
        if entry is None:
            raise VisualError(f"lines[{i}].visual: no timing entry for this line in timings")
        try:
            start = float(entry["start"])
            end = float(entry["end"])
        except (KeyError, TypeError, ValueError):
            raise VisualError(f"timings for lines[{i}]: need numeric start and end") from None
        if end < start:
            raise VisualError(f"timings for lines[{i}]: end ({end}) is before start ({start})")
        plan.append({"index": i, "visual": visual, "start": start, "seconds": max(MIN_PANEL_SECONDS, end - start + PANEL_TAIL_SECONDS)})

    plan.sort(key=lambda p: p["start"])

    # Walk backwards so the later panel wins: keep an earlier panel only if the
    # next KEPT panel starts at least MIN_CAPPED_SECONDS after it.
    eps = 1e-9
    kept: list[dict] = []
    for item in reversed(plan):
        if kept and kept[-1]["start"] - item["start"] < MIN_CAPPED_SECONDS - eps:
            continue
        kept.append(item)
    kept.reverse()

    for k, item in enumerate(kept):
        frames = max(1, round(item["seconds"] * PANEL_FPS))
        limits = []
        if k + 1 < len(kept):
            limits.append(kept[k + 1]["start"] - item["start"])  # always >= MIN_CAPPED_SECONDS here
        if video_duration is not None and video_duration - item["start"] >= MIN_CAPPED_SECONDS - eps:
            limits.append(video_duration - item["start"])
        for room in limits:
            # round DOWN to whole frames so a capped panel can never reach into the next one
            frames = min(frames, max(1, int(room * PANEL_FPS + 1e-6)))
        item["seconds"] = frames / PANEL_FPS
        item["end"] = item["start"] + item["seconds"]
        item["name"] = f"panel-{k + 1:02d}"
    return kept


def hook_panel_conflicts(plan: list[dict], hook_end: float) -> list[str]:
    """Planned panels that would start before the hook card is gone (empty list = fine): the card is fully visible until
    hook_end and fades out for HOOK_FADE_SECONDS after it, so a panel may start from hook_end + HOOK_FADE_SECONDS."""
    free_from = captionlib.hook_panel_free_from(hook_end)
    return [
        f"the panel for lines[{p['index']}] starts at {p['start']:.2f} s, but the hook card is on screen until {hook_end:.2f} s "
        f"and fades out until {free_from:.2f} s"
        for p in plan if p["start"] < free_from - 1e-6
    ]


def _num(x: float) -> str:
    """Compact, stable number for ffmpeg expressions (no scientific notation)."""
    text = f"{x:.3f}".rstrip("0").rstrip(".")
    return text if text else "0"


def build_filter_complex(panels: list[dict], x: int = PANEL_X, y: int = PANEL_Y, caption: bool = False, hook: bool = False) -> str:
    """ffmpeg -filter_complex for overlaying panels (input 0 = base, input k = panel k).

    Each panel's timestamps are shifted to its start time and the overlay is only
    enabled between start and end. With caption=True the caption track (input number len(panels)+1) is
    overlaid on top of everything at x=CAPTION_X, y=CAPTION_Y; it starts at 0 and runs as one transparent
    video, so it needs no enable window. With hook=True the hook card (the LAST input) is overlaid FIRST, right on
    the video (below the panels and the captions: no panel starts before the card is done, a panel that starts
    during its fade-out simply covers it), at x=HOOK_X, y=HOOK_Y; it also starts at 0 and needs no enable window.
    The final video stream is labelled [vout].
    """
    if not panels and not caption and not hook:
        raise ValueError("build_filter_complex needs at least one panel, a caption track or a hook card")
    parts: list[str] = []
    prev = "0:v"
    if hook:
        k = len(panels) + 1 + (1 if caption else 0)
        parts.append(f"[{k}:v]setpts=PTS-STARTPTS[hook]")
        parts.append(f"[{prev}][hook]overlay=x={HOOK_X}:y={HOOK_Y}:format=auto:eof_action=pass[vhook]")
        prev = "vhook"
    for k, panel in enumerate(panels, start=1):
        start, end = _num(panel["start"]), _num(panel["end"])
        parts.append(f"[{k}:v]setpts=PTS-STARTPTS+{start}/TB[p{k}]")
        out = f"v{k}"
        parts.append(
            f"[{prev}][p{k}]overlay=x={x}:y={y}:format=auto:eof_action=pass:"
            f"enable='between(t,{start},{end})'[{out}]"
        )
        prev = out
    if caption:
        k = len(panels) + 1
        parts.append(f"[{k}:v]setpts=PTS-STARTPTS[cap]")
        parts.append(f"[{prev}][cap]overlay=x={CAPTION_X}:y={CAPTION_Y}:format=auto:eof_action=pass[vcap]")
        prev = "vcap"
    parts.append(f"[{prev}]format=yuv420p[vout]")
    return ";".join(parts)


def build_ffmpeg_command(
    base_mp4: str,
    panel_files: list[str],
    panels: list[dict],
    out_mp4: str,
    duration: float | None = None,
    ffmpeg: str = FFMPEG,
    caption_file: str | None = None,
    hook_file: str | None = None,
) -> list[str]:
    """Full ffmpeg argv: one pass, all panels (and the caption track and the hook card, when given), x264 crf 18, audio copied."""
    if len(panel_files) != len(panels):
        raise ValueError("panel_files and panels must have the same length")
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", base_mp4]
    for path in panel_files:
        cmd += ["-i", path]
    if caption_file:
        cmd += ["-i", caption_file]
    if hook_file:
        cmd += ["-i", hook_file]  # the LAST input, see build_filter_complex
    cmd += [
        "-filter_complex", build_filter_complex(panels, caption=bool(caption_file), hook=bool(hook_file)),
        "-map", "[vout]", "-map", "0:a?",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
    ]
    if duration is not None:
        cmd += ["-t", _num(duration)]
    cmd.append(out_mp4)
    return cmd


def build_remotion_command(npx: str, props_json: str, out_mov: str, composition: str = "ShortsPanel") -> list[str]:
    """argv for rendering one transparent composition (ProRes 4444 with alpha): a panel, or the caption track."""
    return [
        npx, "remotion", "render", "src/index.ts", composition, out_mov,
        f"--props={props_json}",
        "--codec=prores", "--prores-profile=4444",
        "--pixel-format=yuva444p10le", "--image-format=png",
    ]


def build_caption_remotion_command(npx: str, props_json: str, out_mov: str) -> list[str]:
    """argv for rendering the whole caption track (composition WordCaptions)."""
    return build_remotion_command(npx, props_json, out_mov, composition=CAPTION_COMPOSITION)


def build_hook_remotion_command(npx: str, props_json: str, out_mov: str) -> list[str]:
    """argv for rendering the hook card (composition HookCard)."""
    return build_remotion_command(npx, props_json, out_mov, composition=HOOK_COMPOSITION)


# --------------------------------------------------------------------------- captions (pure)


def validate_captions(captions) -> list[str]:
    """Problems with the ``captions`` argument of render_and_overlay (empty list = valid).

    captions = {"words": [{"text", "start", "end", optional "font_size"}...], "font_size", "stroke_width", "box_height",
                optional "text_color" (#FFFFFF), "stroke_color" (#000000)}; times in seconds on the video's timeline.
    A word's own "font_size" (smaller than the base size) is for a word that would be too wide at the base size.
    """
    if not isinstance(captions, dict):
        return ["captions: must be an object with words, font_size, stroke_width and box_height"]
    errors: list[str] = []
    words = captions.get("words")
    if not isinstance(words, list) or not words:
        return ["captions.words: must be a non-empty list of {text, start, end}"]
    previous_end = 0.0
    for k, word in enumerate(words):
        where = f"captions.words[{k}]"
        if not isinstance(word, dict) or not isinstance(word.get("text"), str) or not word["text"].strip():
            errors.append(f"{where}: needs a non-empty text")
            continue
        try:
            start, end = float(word["start"]), float(word["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{where} ({word['text']!r}): needs numeric start and end")
            continue
        if not 0 <= start < end:
            errors.append(f"{where} ({word['text']!r}): needs 0 <= start < end, got {start} and {end}")
        elif start < previous_end - 1e-6:
            errors.append(f"{where} ({word['text']!r}): starts at {start} before the previous word ends ({previous_end})")
        previous_end = max(previous_end, end)
        own_size = word.get("font_size")  # optional: a word that is too wide at the base size gets its own, smaller size
        if own_size is not None and (isinstance(own_size, bool) or not isinstance(own_size, (int, float)) or own_size <= 0):
            errors.append(f"{where} ({word['text']!r}): font_size must be a positive number, got {own_size!r}")
    for key in ("font_size", "stroke_width", "box_height"):
        value = captions.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or (key == "stroke_width" and value < 1):
            errors.append(f"captions.{key}: must be a positive number, got {value!r}")
    if isinstance(captions.get("box_height"), (int, float)) and captions["box_height"] > CAPTION_H:
        errors.append(f"captions.box_height: {captions['box_height']} is taller than the caption canvas ({CAPTION_H})")
    return errors


def build_caption_props(captions: dict) -> dict:
    """The props (JSON) of the WordCaptions composition. The track is as long as the last word plus a short tail,
    rounded up to whole frames; the overlay shows the plain video after it."""
    words = []
    for w in captions["words"]:
        item = {"text": w["text"], "start": float(w["start"]), "end": float(w["end"])}
        if w.get("font_size") is not None:
            item["fontSize"] = int(w["font_size"])
        words.append(item)
    last = max(w["end"] for w in words)
    frames = math.ceil((last + CAPTION_TAIL_SECONDS) * CAPTION_FPS - 1e-9)
    return {
        "words": words,
        "fontSize": int(captions["font_size"]),
        "strokeWidth": int(captions["stroke_width"]),
        "boxHeight": int(captions["box_height"]),
        "textColor": captions.get("text_color", "#FFFFFF"),
        "strokeColor": captions.get("stroke_color", "#000000"),
        "seconds": frames / CAPTION_FPS,
    }


# --------------------------------------------------------------------------- hook card (pure)


def validate_hook(hook, captions: dict | None = None) -> list[str]:
    """Problems with the ``hook`` argument of render_and_overlay (empty list = valid).

    hook = {"line1", "line2", "accent", "font_size", "stroke_width", "hook_end"}: the text rules are captions.hook_problems;
    font_size and stroke_width are what make_video.pick_hook_style chose; hook_end is in seconds on the video's timeline.
    No caption word may start before hook_end (the captions are hidden under the card)."""
    problems = captionlib.hook_problems(hook)
    if not isinstance(hook, dict):
        return problems
    for key in ("font_size", "stroke_width", "hook_end"):
        value = hook.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            problems.append(f"hook.{key}: must be a positive number, got {value!r}")
    if not problems and captions is not None:
        early = [w["text"] for w in captions.get("words", []) if float(w["start"]) < hook["hook_end"] - 1e-6]
        if early:
            problems.append(f"captions would be drawn under the hook card (before {hook['hook_end']:.2f} s): {', '.join(map(repr, early[:5]))}")
    return problems


def hook_track_seconds(hook_end: float) -> float:
    """Length of the hook track: on screen until hook_end, then the fade-out, rounded up to whole frames."""
    return math.ceil((hook_end + HOOK_FADE_SECONDS) * HOOK_FPS - 1e-9) / HOOK_FPS


def build_hook_props(hook: dict) -> dict:
    """The props (JSON) of the HookCard composition."""
    return {
        "lines": captionlib.hook_segments(hook),
        "fontSize": int(hook["font_size"]),
        "strokeWidth": int(hook["stroke_width"]),
        "textColor": "#FFFFFF",
        "strokeColor": "#000000",
        "accentColor": HOOK_ACCENT_COLOR,
        "holdSeconds": float(hook["hook_end"]),
        "fadeSeconds": HOOK_FADE_SECONDS,
        "seconds": hook_track_seconds(float(hook["hook_end"])),
    }


# --------------------------------------------------------------------------- tools


def _tool_env() -> dict:
    env = dict(os.environ)
    extra = ["/opt/homebrew/bin", str(Path.home() / ".local" / "bin"), "/usr/local/bin"]
    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + extra)
    return env


def _find_tool(name: str, preferred: str | None = None) -> str:
    if preferred and os.access(preferred, os.X_OK):
        return preferred
    found = shutil.which(name, path=_tool_env()["PATH"])
    if not found:
        raise RuntimeError(f"could not find '{name}' (looked at {preferred or 'PATH'})")
    return found


def _tail(text: str, n: int = 25) -> str:
    return "\n".join((text or "").strip().splitlines()[-n:])


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 900, what: str = "command") -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=_tool_env(), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{what} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"{what} failed (exit {proc.returncode}):\n{_tail(proc.stderr or proc.stdout)}")
    return proc


def probe_duration(path: str) -> float | None:
    try:
        proc = _run(
            [_find_tool("ffprobe", FFPROBE), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            what="ffprobe",
        )
        return float(proc.stdout.strip())
    except (RuntimeError, ValueError):
        return None


_ALPHA_FORMAT = re.compile(r"(yuva|gbrap|rgba|argb|bgra|abgr|ya\d)")


def assert_has_alpha(path: str) -> None:
    """Fail loudly if a rendered panel lost its alpha channel (it would become a black square)."""
    proc = _run(
        [_find_tool("ffprobe", FFPROBE), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=pix_fmt", "-of", "default=nw=1:nk=1", path],
        what="ffprobe",
    )
    pix_fmt = proc.stdout.strip()
    if not _ALPHA_FORMAT.search(pix_fmt):
        raise RuntimeError(f"{path} has no alpha channel (pixel format {pix_fmt!r}); the overlay would hide the video")


# --------------------------------------------------------------------------- main API


def render_and_overlay(
    base_mp4: str, script: dict, timings: list[dict], out_mp4: str, work_dir: str, captions: dict | None = None,
    hook: dict | None = None,
) -> dict:
    """Render a panel for every line that has a visual (and the caption track, when given) and overlay them on base_mp4.

    ``captions`` (optional) is {"words": [{"text", "start", "end"}...], "font_size", "stroke_width", "box_height"};
    see validate_captions. The words are drawn one at a time by Remotion (composition WordCaptions) into ONE
    transparent track that is overlaid in the same ffmpeg pass as the panels, so the video is re-encoded once.

    ``hook`` (optional) is {"line1", "line2", "accent", "font_size", "stroke_width", "hook_end"}; see validate_hook. The card
    is drawn by Remotion (composition HookCard) and overlaid in the same pass. No panel may start before hook_end + the fade and no
    caption word may start before hook_end (the caller hides those words, see captions.hide_until).

    Returns {"panels": n, "render_seconds": s, "out": out_mp4} plus {"captions": {"words", "render_seconds"}}
    when captions were drawn and {"hook": {"seconds", "render_seconds"}} when a hook card was. Raises VisualError for a
    script/timings/captions/hook problem (before any rendering),
    RuntimeError if Remotion or ffmpeg fails (the work files are then kept for debugging).
    """
    if not os.path.isfile(base_mp4):
        raise FileNotFoundError(f"base video not found: {base_mp4}")
    lang = script.get("language", "en")
    if lang not in ("en", "de"):
        raise VisualError(f'language: must be "en" or "de", got {lang!r}')
    if captions is not None:
        caption_errors = validate_captions(captions)
        if caption_errors:
            raise VisualError("; ".join(caption_errors[:5]))
    if hook is not None:
        hook_errors = validate_hook(hook, captions)
        if hook_errors:
            raise VisualError("; ".join(hook_errors[:5]))

    duration = probe_duration(base_mp4)
    plan = plan_panels(script, timings, video_duration=duration)  # validates visuals first
    if hook is not None:
        conflicts = hook_panel_conflicts(plan, float(hook["hook_end"]))
        if conflicts:
            raise VisualError("; ".join(conflicts))
    dropped = [i for i, line in enumerate(script["lines"]) if line.get("visual") and i not in {p["index"] for p in plan}]
    if dropped:
        print(
            f"warning: visual on lines {dropped} skipped: the next visual starts less than "
            f"{MIN_CAPPED_SECONDS:g} s later, so the two cards would have overlapped",
            file=sys.stderr,
        )
    Path(out_mp4).parent.mkdir(parents=True, exist_ok=True)

    if not plan and captions is None and hook is None:
        if os.path.abspath(base_mp4) != os.path.abspath(out_mp4):
            shutil.copyfile(base_mp4, out_mp4)
        return {"panels": 0, "render_seconds": 0.0, "out": out_mp4}

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    npx = _find_tool("npx")

    t0 = time.monotonic()
    panel_files: list[str] = []
    scratch: list[Path] = []
    for item in plan:
        props_path = work / f"{item['name']}.json"
        mov_path = work / f"{item['name']}.mov"
        props_path.write_text(
            json.dumps({"visual": item["visual"], "seconds": item["seconds"], "lang": lang}, ensure_ascii=False),
            encoding="utf-8",
        )
        _run(
            build_remotion_command(npx, str(props_path), str(mov_path)),
            cwd=REMOTION_DIR,
            what=f"remotion render {item['name']} (lines[{item['index']}])",
        )
        if not mov_path.is_file():
            raise RuntimeError(f"remotion did not produce {mov_path}")
        assert_has_alpha(str(mov_path))
        panel_files.append(str(mov_path))
        scratch += [props_path, mov_path]
    render_seconds = time.monotonic() - t0

    caption_file = None
    caption_seconds = 0.0
    if captions is not None:
        t1 = time.monotonic()
        props_path = work / "captions.json"
        mov_path = work / "captions.mov"
        props_path.write_text(json.dumps(build_caption_props(captions), ensure_ascii=False), encoding="utf-8")
        _run(
            build_caption_remotion_command(npx, str(props_path), str(mov_path)),
            cwd=REMOTION_DIR,
            what=f"remotion render caption track ({len(captions['words'])} words)",
        )
        if not mov_path.is_file():
            raise RuntimeError(f"remotion did not produce {mov_path}")
        assert_has_alpha(str(mov_path))
        caption_file = str(mov_path)
        scratch += [props_path, mov_path]
        caption_seconds = time.monotonic() - t1

    hook_file = None
    hook_render_seconds = 0.0
    if hook is not None:
        t2 = time.monotonic()
        props_path = work / "hook.json"
        mov_path = work / "hook.mov"
        props_path.write_text(json.dumps(build_hook_props(hook), ensure_ascii=False), encoding="utf-8")
        _run(
            build_hook_remotion_command(npx, str(props_path), str(mov_path)),
            cwd=REMOTION_DIR,
            what="remotion render hook card",
        )
        if not mov_path.is_file():
            raise RuntimeError(f"remotion did not produce {mov_path}")
        assert_has_alpha(str(mov_path))
        hook_file = str(mov_path)
        scratch += [props_path, mov_path]
        hook_render_seconds = time.monotonic() - t2

    cmd = build_ffmpeg_command(
        base_mp4, panel_files, plan, out_mp4, duration=duration, ffmpeg=_find_tool("ffmpeg", FFMPEG),
        caption_file=caption_file, hook_file=hook_file,
    )
    _run(cmd, what="ffmpeg overlay")

    for path in scratch:  # the caption .mov is big (tens of MB): never leave it behind after a good run
        path.unlink(missing_ok=True)
    result = {"panels": len(plan), "render_seconds": round(render_seconds, 2), "out": out_mp4}
    if captions is not None:
        result["captions"] = {"words": len(captions["words"]), "render_seconds": round(caption_seconds, 2)}
    if hook is not None:
        result["hook"] = {"until": float(hook["hook_end"]), "seconds": hook_track_seconds(float(hook["hook_end"])),
                          "render_seconds": round(hook_render_seconds, 2)}
    return result


# --------------------------------------------------------------------------- demo

STUDIO_DIR = Path(__file__).resolve().parent

DEMO_SCRIPT = {
    "id": "_demo",
    "language": "de",
    "series": "Demo",
    "title": "Visual panel demo",
    "caption": "Demo of the three panel types.",
    "hashtags": ["#demo", "#test", "#panels"],
    "video_terms": ["demo", "test", "panel", "overlay"],
    "lines": [
        {
            "text": "German flow panel with long compound words.",
            "visual": {
                "type": "flow",
                "title": "So kühlt der Kühlschrank",
                "steps": [
                    "Kühlschrankkompressor",
                    "Wärmeübertragung",
                    "Verdampfer saugt Wärme",
                    "Gas dehnt sich aus",
                    "Innenraum wird kühl",
                ],
            },
        },
        {"text": "Stat panel.", "visual": {"type": "stat", "value": "-18 °C", "label": "Typical freezer temperature"}},
        {
            "text": "Compare panel.",
            "visual": {
                "type": "compare",
                "title": "Does cold air leave the fridge?",
                "left": {"heading": "Myth", "text": "Cold air flows out of the open door"},
                "right": {"heading": "Fact", "text": "Warm air flows in and heat is carried away"},
            },
        },
    ],
    "sources": [{"title": "a", "url": "https://example.com/a"}, {"title": "b", "url": "https://example.com/b"}],
}

DEMO_TIMINGS = [
    {"index": 0, "start": 0.5, "end": 4.5, "text": "flow"},
    {"index": 1, "start": 4.5, "end": 8.0, "text": "stat"},
    {"index": 2, "start": 8.0, "end": 12.0, "text": "compare"},
]


def _media_scripts_dir() -> Path:
    """Newest installed media-studio scripts folder (sorted by version number)."""
    root = Path.home() / ".claude" / "plugins" / "cache" / "media-studio-marketplace" / "media-studio"
    found = [p for p in root.glob("*/skills/media-studio/scripts") if p.is_dir()]
    if not found:
        raise RuntimeError(f"media-studio scripts not found under {root}")
    return max(found, key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.parents[2].name)))


def _make_demo_base(path: Path) -> None:
    """12 s 1080x1920 test video: testsrc2 + sine tone + a white bar (y 1500..1750) standing in for subtitles."""
    _run(
        [
            _find_tool("ffmpeg", FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=12",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=12",
            "-vf", "drawbox=x=0:y=1500:w=iw:h=250:color=white:t=fill",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "12", str(path),
        ],
        what="demo base video",
    )


def _grab_frame(video: Path, seconds: float, out_png: Path) -> None:
    _run(
        [_find_tool("ffmpeg", FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
         "-ss", _num(seconds), "-i", str(video), "-frames:v", "1", str(out_png)],
        what=f"frame grab {out_png.name}",
    )


def run_demo(out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir) if out_dir else STUDIO_DIR / "visuals-demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    demo_mp4 = out_dir / "demo.mp4"

    with tempfile.TemporaryDirectory(prefix="visuals-demo-") as tmp:
        base = Path(tmp) / "base.mp4"
        _make_demo_base(base)
        result = render_and_overlay(str(base), DEMO_SCRIPT, DEMO_TIMINGS, str(demo_mp4), str(Path(tmp) / "work"))

    plan = plan_panels(DEMO_SCRIPT, DEMO_TIMINGS, video_duration=12.0)
    frames = []
    for item in plan:
        kind = item["visual"]["type"]
        # middle of the panel (as asked) and a late frame where every step/card has appeared
        _grab_frame(demo_mp4, item["start"] + item["seconds"] / 2, out_dir / f"frame-{kind}.png")
        _grab_frame(demo_mp4, item["start"] + item["seconds"] * 0.8, out_dir / f"frame-{kind}-late.png")
        frames.append(f"frame-{kind}.png")

    sheet_png = out_dir / "sheet.png"
    _run(
        ["node", str(_media_scripts_dir() / "media.mjs"), "sheet", str(demo_mp4), str(sheet_png),
         "--every", "1", "--cols", "4", "--thumb", "270"],
        what="contact sheet",
    )
    return {**result, "sheet": str(sheet_png), "frames": [str(out_dir / f) for f in frames]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render and overlay animated explainer panels.")
    parser.add_argument("--demo", action="store_true", help="build studio/visuals-demo/ (demo.mp4, sheet.png, frame-*.png)")
    args = parser.parse_args(argv)
    if not args.demo:
        parser.print_help()
        return 2
    try:
        result = run_demo()
    except (VisualError, RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
