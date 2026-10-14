#!/usr/bin/env python3
"""Make the weekly upload pack: one Markdown page listing every finished video of a week, ready to post.

    python3 studio/upload_pack.py 2026-10-14

Reads review/<prefix>-*/ (final.mp4, caption.txt, subtitles.srt, report.json), makes a small
preview-phone.mp4 next to each final.mp4 (for watching on a phone; never upload the preview),
and writes review/UPLOAD-PACK-<prefix>.md. Standard library only.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "review"
FLAGS = {"en": "🇬🇧 English", "de": "🇩🇪 Deutsch"}
POST_DAYS = ["Day 1", "Day 3", "Day 5"]  # three posts per language per week, every other day


def make_preview(folder: Path) -> Path:
    final, preview = folder / "final.mp4", folder / "preview-phone.mp4"
    if not preview.exists() or preview.stat().st_mtime < final.stat().st_mtime:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(final), "-vf", "scale=720:1280",
                        "-c:v", "libx264", "-crf", "26", "-preset", "medium", "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart", str(preview)], check=True)
    return preview


def video_entry(folder: Path, day: str) -> str:
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    failed = [c["name"] for c in report.get("checks", []) if not c.get("ok")]
    caption = (folder / "caption.txt").read_text(encoding="utf-8").strip()
    title = caption.splitlines()[0]
    seconds = report.get("durations", {}).get("final")
    lang = "de" if "-de-" in folder.name else "en"
    status = "✅ all checks passed" if not failed else f"❌ failed checks: {', '.join(failed)}"
    return f"""
### {day} · {FLAGS[lang]} · {title}
- **Upload this file:** `{folder / 'final.mp4'}` ({seconds:.0f} s) · phone preview: `{folder / 'preview-phone.mp4'}`
- **Status:** {status}
- **YouTube:** paste the text below as title + description, answer "Altered or synthetic content" by YouTube's criteria
  (a generic AI narrator over unaltered stock clips is usually "No"; the caption already says "AI voice"),
  optionally upload `subtitles.srt` as subtitles, then **Schedule**.
- **TikTok:** paste the caption, switch on **"AI-generated content"** (more options), schedule.
- **Instagram:** paste the caption, switch on **"Add AI label"** (advanced settings), schedule.

```text
{caption}
```
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    prefix = sys.argv[1]
    folders = sorted(f for f in REVIEW.glob(f"{prefix}-*") if (f / "final.mp4").is_file())
    if not folders:
        print(f"No finished videos in {REVIEW} starting with {prefix}-")
        return 1
    parts = [f"# Upload pack for the week of {prefix}\n",
             "Watch each video first (the phone preview is fine). Post only what you approve. "
             "Each video goes to YouTube Shorts, TikTok and Instagram Reels on the same day, using each app's scheduler.\n"]
    for lang in ("en", "de"):
        mine = [f for f in folders if f"-{lang}-" in f.name]
        if mine:
            parts.append(f"\n## {FLAGS[lang]}\n")
        for day, folder in zip(POST_DAYS * 3, mine):
            make_preview(folder)
            parts.append(video_entry(folder, day))
    out = REVIEW / f"UPLOAD-PACK-{prefix}.md"
    out.write_text("".join(parts), encoding="utf-8")
    print(f"wrote {out} ({len(folders)} videos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
