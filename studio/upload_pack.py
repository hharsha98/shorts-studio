#!/usr/bin/env python3
"""Make the weekly upload pack: one Markdown page listing every finished video of a week, ready to post.

    python3 studio/upload_pack.py 2026-10-14

Reads review/<prefix>-*/ (final.mp4, cover.jpg, caption.txt, subtitles.srt, report.json), makes a small
preview-phone.mp4 next to each final.mp4 (for watching on a phone; never upload the preview),
and writes review/UPLOAD-PACK-<prefix>.md. Standard library only.

Per video the page shows: the runtime, the hook text that is on screen at the start, the file to upload, the cover
image (the first frame of the video), the YouTube TITLE (the first line of caption.txt, at most 70 characters), the
DESCRIPTION (the rest of caption.txt), the comment to pin (script field "pinned_comment") and the AI-label checklist.
At the top: the total runtime of all videos. The title, the comment and the hook come from report.json ("publish"),
which make_video.py writes; an older review folder falls back to the script file named in its report.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "review"
FLAGS = {"en": "🇬🇧 English", "de": "🇩🇪 Deutsch"}
POST_DAYS = ["Day 1", "Day 3", "Day 5"]  # three posts per language per week, every other day
TITLE_LIMIT = 70  # longer YouTube titles are cut off in the Shorts feed


def make_preview(folder: Path) -> Path:
    final, preview = folder / "final.mp4", folder / "preview-phone.mp4"
    if not preview.exists() or preview.stat().st_mtime < final.stat().st_mtime:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(final), "-vf", "scale=720:1280",
                        "-c:v", "libx264", "-crf", "26", "-preset", "medium", "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart", str(preview)], check=True)
    return preview


def split_caption(caption: str) -> tuple[str, str]:
    """caption.txt = title, a blank line, then everything else. Returns (title, description)."""
    text = caption.strip()
    title, _, rest = text.partition("\n")
    return title.strip(), rest.strip()


def clock(seconds) -> str:
    """72.4 -> '1:12' (minutes:seconds); '?' when the runtime is unknown."""
    if not isinstance(seconds, (int, float)):
        return "?"
    whole = round(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def _script_of(report: dict) -> dict:
    """The script file named in an (older) report, or {} when it cannot be read."""
    path = ((report.get("inputs") or {}).get("script")) if isinstance(report, dict) else None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_info(folder: Path) -> dict:
    """Everything one video's entry shows, read from its review folder."""
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    caption = (folder / "caption.txt").read_text(encoding="utf-8")
    caption_title, description = split_caption(caption)
    publish = report.get("publish") or {}
    script = {} if publish else _script_of(report)  # older folders: ask the script itself
    hook = publish.get("hook") if publish else script.get("hook")
    pinned = publish.get("pinned_comment") if publish else script.get("pinned_comment")
    cover = folder / "cover.jpg"
    return {
        "folder": folder,
        "lang": "de" if "-de-" in folder.name else "en",
        "title": (publish.get("youtube_title") or script.get("title") or caption_title),
        "description": description,
        "hook": hook if isinstance(hook, dict) else None,
        "pinned_comment": pinned if isinstance(pinned, str) and pinned.strip() else None,
        "seconds": (report.get("durations") or {}).get("final") or publish.get("runtime_seconds"),
        "cover": cover if cover.is_file() else None,
        "failed": [c["name"] for c in report.get("checks", []) if not c.get("ok")],
    }


def format_entry(info: dict, day: str) -> str:
    """The Markdown block of one video (pure: everything it needs is in `info`, see read_info)."""
    folder = info["folder"]
    title = info["title"]
    status = "✅ all checks passed" if not info["failed"] else f"❌ failed checks: {', '.join(info['failed'])}"
    hook = info.get("hook")
    hook_text = f"\"{hook['line1']}\" / \"{hook['line2']}\" (accent: {hook['accent']})" if hook else "none (this video has no hook card)"
    cover = (f"`{info['cover']}` (the frame at 0.0 s, 1080x1920): use it as the cover image where the app lets you pick one "
             "(TikTok: Edit cover → upload from album, Instagram: Edit cover → add from camera roll)"
             if info.get("cover") else "missing: run make_video.py again to get cover.jpg (or pick the first frame in the app)")
    length_note = "" if len(title) <= TITLE_LIMIT else f" ⚠️ **{len(title) - TITLE_LIMIT} too many: shorten the title in the script**"
    pinned = (f"`{info['pinned_comment']}`  \n  Post it yourself right after publishing, then pin it (long-press the comment → Pin)."
              if info.get("pinned_comment") else "none written: add \"pinned_comment\" to the script, or skip it")
    seconds = info["seconds"]
    return f"""
### {day} · {FLAGS[info['lang']]} · {title}
- **Runtime:** {clock(seconds)} ({round(seconds) if isinstance(seconds, (int, float)) else '?'} s)
- **Hook on screen at the start:** {hook_text}
- **Upload this file:** `{folder / 'final.mp4'}` · phone preview: `{folder / 'preview-phone.mp4'}`
- **Cover:** {cover}
- **Status:** {status}
- **YouTube title** ({len(title)} of {TITLE_LIMIT} characters){length_note}:

```text
{title}
```

- **Description** (everything below the title in caption.txt: hashtags, AI disclosure, credits, sources):

```text
{info['description']}
```

- **Pin this comment:** {pinned}
- **YouTube:** paste the title and the description above, answer "Altered or synthetic content" by YouTube's criteria
  (a generic AI narrator over unaltered stock clips is usually "No"; the caption already says "AI voice"),
  optionally upload `subtitles.srt` as subtitles, then **Schedule**.
- **TikTok:** paste the title, a blank line, then the description; switch on **"AI-generated content"** (more options), schedule.
- **Instagram:** paste the title, a blank line, then the description; switch on **"Add AI label"** (advanced settings), schedule.
"""


def format_pack(prefix: str, entries: list[tuple[str, dict]]) -> str:
    """The whole page. entries = [(language, info)] in posting order; the languages are shown as separate sections."""
    infos = [info for _lang, info in entries]
    total = sum(i["seconds"] for i in infos if isinstance(i["seconds"], (int, float)))
    unknown = sum(1 for i in infos if not isinstance(i["seconds"], (int, float)))
    parts = [f"# Upload pack for the week of {prefix}\n",
             "Watch each video first (the phone preview is fine). Post only what you approve. "
             "Each video goes to YouTube Shorts, TikTok and Instagram Reels on the same day, using each app's scheduler.\n",
             f"\n**Total runtime of the {len(infos)} video{'' if len(infos) == 1 else 's'}: {clock(total)} ({round(total)} s)**"
             + (f" (plus {unknown} video(s) whose runtime is unknown)" if unknown else "") + "\n"]
    for lang in ("en", "de"):
        mine = [info for l, info in entries if l == lang]
        if mine:
            parts.append(f"\n## {FLAGS[lang]}\n")
        for day, info in zip(POST_DAYS * 3, mine):
            parts.append(format_entry(info, day))
    return "".join(parts)


def main() -> int:
    # One or more dates: `upload_pack.py 2026-10-20 2026-10-22 2026-10-24` makes ONE pack for a week whose videos are
    # dated on different days; the pack is named after the first date.
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    prefixes = sys.argv[1:]
    prefix = prefixes[0]
    folders = sorted({f for p in prefixes for f in REVIEW.glob(f"{p}-*") if (f / "final.mp4").is_file()})
    if not folders:
        print(f"No finished videos in {REVIEW} starting with {', '.join(p + '-' for p in prefixes)}")
        return 1
    entries = []
    for lang in ("en", "de"):
        for folder in (f for f in folders if f"-{lang}-" in f.name):
            make_preview(folder)
            entries.append((lang, read_info(folder)))
    out = REVIEW / f"UPLOAD-PACK-{prefix}.md"
    out.write_text(format_pack(prefix, entries), encoding="utf-8")
    print(f"wrote {out} ({len(folders)} videos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
