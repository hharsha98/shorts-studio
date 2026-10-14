"""Tests for studio/upload_pack.py: what the weekly upload page shows for every video (title, description, cover,
pinned comment, hook, runtime). Everything runs on fake review folders in a temporary directory; no ffmpeg.

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import upload_pack as up  # noqa: E402

CAPTION = (
    "Why Is Microwave Food Still Cold in the Middle?\n\n"
    "Microwaves heat only the outer few centimeters.\n\n"
    "#howthingswork #microwave #physics\n\n"
    "AI voice. Script written with AI assistance and fact-checked.\n"
    "Video by Ann on Pixabay (pixabay.com): https://pixabay.com/videos/a-5/\n\n"
    "Sources:\n"
    "U.S. FDA: Microwave Ovens – https://www.fda.gov/x\n"
)
HOOK = {"line1": "Hot outside.", "line2": "Frozen inside. Why?", "accent": "Frozen"}
PINNED = "Do you stir halfway, or are you team lava-and-ice? 👇"


def make_folder(root: Path, name="2026-10-14-en-microwave", report=None, caption=CAPTION, cover=True):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "final.mp4").write_bytes(b"v")
    (folder / "caption.txt").write_text(caption, encoding="utf-8")
    if cover:
        (folder / "cover.jpg").write_bytes(b"j")
    base = {
        "ok": True, "checks": [{"name": "voice accuracy", "ok": True, "detail": "x"}], "durations": {"narration": 58.0, "final": 58.4},
        "publish": {"youtube_title": "Why Is Microwave Food Still Cold in the Middle?", "pinned_comment": PINNED, "hook": HOOK,
                    "runtime_seconds": 58.4, "topic_noun": "microwave"},
    }
    base.update(report or {})
    (folder / "report.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    return folder


class SplitCaptionTests(unittest.TestCase):
    def test_title_is_the_first_line_and_the_description_is_the_rest(self):
        title, description = up.split_caption(CAPTION)
        self.assertEqual(title, "Why Is Microwave Food Still Cold in the Middle?")
        self.assertTrue(description.startswith("Microwaves heat only"))
        self.assertTrue(description.endswith("https://www.fda.gov/x"))
        self.assertNotIn(title, description)

    def test_a_caption_with_only_a_title(self):
        self.assertEqual(up.split_caption("Just a title\n"), ("Just a title", ""))

    def test_clock(self):
        self.assertEqual(up.clock(58.4), "0:58")
        self.assertEqual(up.clock(72.0), "1:12")
        self.assertEqual(up.clock(3599.6), "60:00")
        self.assertEqual(up.clock(None), "?")


class ReadInfoTests(unittest.TestCase):
    def test_everything_comes_from_the_review_folder(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = make_folder(Path(raw))
            info = up.read_info(folder)
        self.assertEqual(info["title"], "Why Is Microwave Food Still Cold in the Middle?")
        self.assertEqual(info["pinned_comment"], PINNED)
        self.assertEqual(info["hook"], HOOK)
        self.assertEqual(info["seconds"], 58.4)
        self.assertEqual(info["lang"], "en")
        self.assertEqual(info["cover"], folder / "cover.jpg")
        self.assertEqual(info["failed"], [])
        self.assertTrue(info["description"].startswith("Microwaves heat only"))

    def test_a_missing_cover_is_none(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertIsNone(up.read_info(make_folder(Path(raw), cover=False))["cover"])

    def test_failed_checks_are_listed(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = make_folder(Path(raw), report={"checks": [{"name": "voice accuracy", "ok": True}, {"name": "hook visible at 0 s", "ok": False}]})
            self.assertEqual(up.read_info(folder)["failed"], ["hook visible at 0 s"])

    def test_german_folders(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(up.read_info(make_folder(Path(raw), "2026-10-14-de-mikrowelle"))["lang"], "de")

    def test_an_older_folder_without_publish_asks_the_script_named_in_its_report(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = root / "script.json"
            script.write_text(json.dumps({"title": "Old title", "pinned_comment": "Old comment?", "hook": HOOK}), encoding="utf-8")
            folder = make_folder(root / "review", report={"publish": None, "inputs": {"script": str(script)}})
            info = up.read_info(folder)
        self.assertEqual((info["title"], info["pinned_comment"], info["hook"]), ("Old title", "Old comment?", HOOK))

    def test_an_older_folder_whose_script_is_gone_still_works_from_caption_txt(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = make_folder(Path(raw), report={"publish": None, "inputs": {"script": "/nonexistent/script.json"}})
            info = up.read_info(folder)
        self.assertEqual(info["title"], "Why Is Microwave Food Still Cold in the Middle?")  # the first line of caption.txt
        self.assertIsNone(info["pinned_comment"])
        self.assertIsNone(info["hook"])
        self.assertEqual(info["seconds"], 58.4)


class FormatEntryTests(unittest.TestCase):
    def entry(self, **over):
        with tempfile.TemporaryDirectory() as raw:
            info = up.read_info(make_folder(Path(raw)))
            info.update(over)
            return up.format_entry(info, "Day 1"), info

    def test_the_title_the_description_the_cover_the_comment_the_hook_and_the_runtime_are_there(self):
        text, info = self.entry()
        self.assertIn("### Day 1 · 🇬🇧 English · Why Is Microwave Food Still Cold in the Middle?", text)
        self.assertIn("**Runtime:** 0:58 (58 s)", text)
        self.assertIn('"Hot outside." / "Frozen inside. Why?" (accent: Frozen)', text)
        self.assertIn(f"`{info['folder'] / 'final.mp4'}`", text)
        self.assertIn(f"`{info['folder'] / 'cover.jpg'}`", text)
        self.assertIn(PINNED, text)
        self.assertIn("**Pin this comment:**", text)
        self.assertIn("Microwaves heat only the outer few centimeters.", text)  # the description
        self.assertIn("✅ all checks passed", text)

    def test_the_title_has_its_own_block_with_its_length(self):
        text, _ = self.entry()
        self.assertIn("**YouTube title** (47 of 70 characters)", text)
        self.assertIn("```text\nWhy Is Microwave Food Still Cold in the Middle?\n```", text)

    def test_the_description_block_does_not_repeat_the_title(self):
        text, info = self.entry()
        description_block = text.split("**Description**")[1].split("```text\n")[1].split("\n```")[0]
        self.assertEqual(description_block, info["description"])
        self.assertNotIn("Why Is Microwave Food", description_block)

    def test_a_title_over_70_characters_is_flagged(self):
        text, _ = self.entry(title="x" * 75)
        self.assertIn("(75 of 70 characters)", text)
        self.assertIn("5 too many", text)
        self.assertNotIn("too many", self.entry()[0])

    def test_the_ai_label_checklist_is_kept(self):
        text, _ = self.entry()
        self.assertIn('answer "Altered or synthetic content"', text)
        self.assertIn('switch on **"AI-generated content"**', text)  # TikTok
        self.assertIn('switch on **"Add AI label"**', text)  # Instagram
        self.assertIn("subtitles.srt", text)
        self.assertIn("**Schedule**", text)

    def test_no_hook_and_no_comment_are_said_plainly(self):
        text, _ = self.entry(hook=None, pinned_comment=None)
        self.assertIn("none (this video has no hook card)", text)
        self.assertIn('add "pinned_comment" to the script', text)

    def test_a_missing_cover_says_how_to_get_one(self):
        text, _ = self.entry(cover=None)
        self.assertIn("**Cover:** missing", text)

    def test_failed_checks_show_up(self):
        text, _ = self.entry(failed=["hook visible at 0 s", "voice accuracy"])
        self.assertIn("❌ failed checks: hook visible at 0 s, voice accuracy", text)

    def test_an_unknown_runtime_is_a_question_mark(self):
        text, _ = self.entry(seconds=None)
        self.assertIn("**Runtime:** ? (? s)", text)

    def test_german_entries_use_the_german_flag(self):
        text, _ = self.entry(lang="de")
        self.assertIn("🇩🇪 Deutsch", text)


class FormatPackTests(unittest.TestCase):
    def test_total_runtime_and_the_language_sections(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            en1 = up.read_info(make_folder(root, "2026-10-14-en-microwave"))
            en2 = up.read_info(make_folder(root, "2026-10-14-en-fridge", report={"durations": {"final": 61.0}}))
            de1 = up.read_info(make_folder(root, "2026-10-14-de-mikrowelle", report={"durations": {"final": 60.0}}))
            text = up.format_pack("2026-10-14", [("en", en1), ("en", en2), ("de", de1)])
        self.assertIn("# Upload pack for the week of 2026-10-14", text)
        self.assertIn("**Total runtime of the 3 videos: 2:59 (179 s)**", text)  # 58.4 + 61 + 60 = 179.4 s
        self.assertLess(text.index("## 🇬🇧 English"), text.index("## 🇩🇪 Deutsch"))
        self.assertEqual(text.count("### Day 1"), 2)  # the first of each language
        self.assertIn("### Day 3 · 🇬🇧 English", text)

    def test_one_video_is_not_called_videos(self):
        with tempfile.TemporaryDirectory() as raw:
            text = up.format_pack("2026-10-14", [("en", up.read_info(make_folder(Path(raw))))])
        self.assertIn("**Total runtime of the 1 video: 0:58 (58 s)**", text)

    def test_a_video_without_a_runtime_is_counted_as_unknown(self):
        with tempfile.TemporaryDirectory() as raw:
            info = up.read_info(make_folder(Path(raw)))
            info["seconds"] = None
            text = up.format_pack("2026-10-14", [("en", info)])
        self.assertIn("plus 1 video(s) whose runtime is unknown", text)


class MainTests(unittest.TestCase):
    def run_main(self, review: Path, argv):
        out = io.StringIO()
        with mock.patch.object(up, "REVIEW", review), mock.patch.object(up, "make_preview", side_effect=lambda f: f / "preview-phone.mp4"), \
                mock.patch.object(sys, "argv", ["upload_pack.py", *argv]), contextlib.redirect_stdout(out):
            code = up.main()
        return code, out.getvalue()

    def test_the_pack_is_written_for_the_week(self):
        with tempfile.TemporaryDirectory() as raw:
            review = Path(raw)
            make_folder(review, "2026-10-14-en-microwave")
            make_folder(review, "2026-10-14-de-mikrowelle")
            make_folder(review, "2026-10-21-en-other")  # another week
            code, printed = self.run_main(review, ["2026-10-14"])
            text = (review / "UPLOAD-PACK-2026-10-14.md").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("(2 videos)", printed)
        self.assertEqual(text.count("**Pin this comment:**"), 2)
        self.assertNotIn("other", text)

    def test_no_videos_is_a_plain_message(self):
        with tempfile.TemporaryDirectory() as raw:
            code, printed = self.run_main(Path(raw), ["2026-10-14"])
        self.assertEqual(code, 1)
        self.assertIn("No finished videos", printed)

    def test_no_argument_prints_the_help(self):
        with tempfile.TemporaryDirectory() as raw:
            code, printed = self.run_main(Path(raw), [])
        self.assertEqual(code, 1)
        self.assertIn("upload_pack.py", printed)


if __name__ == "__main__":
    unittest.main()
