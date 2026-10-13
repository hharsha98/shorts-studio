"""Unit tests for studio/make_video.py: only the pure helper functions (no network, no ffmpeg).

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import contextlib
import copy
import datetime
import io
import json
import math
import os
import sys
import tempfile
import time
import unicodedata
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import make_video as mv  # noqa: E402


def good_script():
    return {
        "id": "2026-10-14-en-fridge",
        "language": "en",
        "series": "How things work",
        "title": "How your fridge really works",
        "caption": "Your fridge moves heat out. Here is how.",
        "hashtags": ["#science", "#fridge", "#shorts"],
        "video_terms": ["refrigerator", "kitchen", "cooling", "heat pump"],
        "lines": [
            {"text": "Your fridge does not make cold.", "visual": None},
            {"text": "It moves heat out of the box.", "visual": {"type": "stat", "value": "-18 °C", "label": "Typical freezer"}},
        ],
        "sources": [
            {"title": "Refrigerator", "url": "https://en.wikipedia.org/wiki/Refrigerator"},
            {"title": "Vapor-compression", "url": "https://en.wikipedia.org/wiki/Vapor-compression_refrigeration"},
        ],
    }


def errors_of(script):
    return mv.validate_script(script)[0]


class ValidateScriptTests(unittest.TestCase):
    def test_good_script_passes_without_warnings(self):
        errors, warnings = mv.validate_script(good_script())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_not_an_object(self):
        self.assertTrue(errors_of([1, 2]))

    def test_each_required_field_is_reported_when_missing(self):
        for key in ("id", "language", "series", "title", "caption", "hashtags", "video_terms", "lines", "sources"):
            s = good_script()
            del s[key]
            self.assertTrue(any(key in e for e in errors_of(s)), key)

    def test_id_rules(self):
        for bad in ("Fridge", "has space", "../x", "a_b", "", "2026/10"):
            s = good_script()
            s["id"] = bad
            self.assertTrue(any(e.startswith("id ") for e in errors_of(s)), bad)
        for good in ("_test-en", "2026-10-14-de-kuehlschrank", "abc"):
            s = good_script()
            s["id"] = good
            self.assertEqual(errors_of(s), [], good)

    def test_language_must_be_en_or_de(self):
        s = good_script()
        s["language"] = "fr"
        self.assertTrue(any("language" in e for e in errors_of(s)))

    def test_title_limit_90(self):
        s = good_script()
        s["title"] = "x" * 90
        self.assertEqual(errors_of(s), [])
        s["title"] = "x" * 91
        self.assertTrue(any("title" in e for e in errors_of(s)))

    def test_long_caption_only_warns(self):
        s = good_script()
        s["caption"] = "One. Two. Three. Four."
        errors, warnings = mv.validate_script(s)
        self.assertEqual(errors, [])
        self.assertTrue(any("caption" in w for w in warnings))

    def test_hashtag_count_and_shape(self):
        s = good_script()
        s["hashtags"] = ["#a", "#b"]
        self.assertTrue(any("hashtags" in e for e in errors_of(s)))
        s["hashtags"] = ["#a"] * 9
        self.assertTrue(any("hashtags" in e for e in errors_of(s)))
        s["hashtags"] = ["#a", "#b", "c"]
        self.assertTrue(any("hashtags[2]" in e for e in errors_of(s)))

    def test_video_terms_count_and_characters(self):
        s = good_script()
        s["video_terms"] = ["a", "b", "c"]
        self.assertTrue(any("video_terms" in e for e in errors_of(s)))
        s["video_terms"] = ["term"] * 11
        self.assertTrue(any("video_terms" in e for e in errors_of(s)))
        for bad in ("Küche", "4k video", "a,b", "", "   ", "wow!"):
            s["video_terms"] = ["one", "two", "three", bad]
            self.assertTrue(any("video_terms[3]" in e for e in errors_of(s)), bad)
        s["video_terms"] = ["hot-air balloon", "ice cube", "Fridge", "x-ray machine"]
        self.assertEqual(errors_of(s), [])

    def test_line_text_rules(self):
        s = good_script()
        s["lines"][0]["text"] = "   "
        self.assertTrue(any("lines[0].text" in e for e in errors_of(s)))
        s["lines"][0]["text"] = "x" * 400
        self.assertEqual(errors_of(s), [])
        s["lines"][0]["text"] = "x" * 401
        self.assertTrue(any("lines[0].text" in e and "401" in e for e in errors_of(s)))
        s["lines"] = []
        self.assertTrue(any("lines" in e for e in errors_of(s)))
        s["lines"] = ["just a string"]
        self.assertTrue(any("lines[0]" in e for e in errors_of(s)))

    def test_digits_in_line_text_warn_but_do_not_fail(self):
        s = good_script()
        s["lines"][0]["text"] = "It is 18 degrees cold."
        errors, warnings = mv.validate_script(s)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("lines[0]", warnings[0])

    def test_sources_need_two_with_urls(self):
        s = good_script()
        s["sources"] = s["sources"][:1]
        self.assertTrue(any("sources" in e for e in errors_of(s)))
        s = good_script()
        s["sources"][1]["url"] = "ftp://nope"
        self.assertTrue(any("sources[1].url" in e for e in errors_of(s)))

    def test_source_urls_must_be_https_with_one_message(self):
        messages = set()
        for bad in ("http://example.com/a", "ftp://x", "https://", "https://a b", "example.com", "https://example.com/a\n", ""):
            s = good_script()
            s["sources"][0]["url"] = bad
            found = [e for e in errors_of(s) if e.startswith("sources[0].url")]
            self.assertEqual(len(found), 1, repr(bad))
            messages.add(found[0].split(" (got")[0])
        self.assertEqual(messages, {"sources[0].url must start with https:// and contain no spaces"})

    def test_trailing_newline_is_rejected_everywhere(self):
        s = good_script()
        s["id"] = "2026-10-14-en-fridge\n"
        self.assertTrue(any(e.startswith("id ") for e in errors_of(s)))
        s = good_script()
        s["video_terms"][0] = "refrigerator\n"
        self.assertTrue(any("video_terms[0]" in e for e in errors_of(s)))
        s = good_script()
        s["sources"][1]["url"] = "https://en.wikipedia.org/wiki/Refrigerator\n"
        self.assertTrue(any("sources[1].url" in e for e in errors_of(s)))
        s = good_script()
        s["hashtags"][0] = "#science\n"
        self.assertTrue(any("hashtags[0]" in e for e in errors_of(s)))

    def test_long_sentence_warns_but_does_not_fail(self):
        s = good_script()
        s["lines"][0]["text"] = ("word " * 28).strip() + "."  # 139 characters + dot = 140: allowed
        self.assertEqual(mv.validate_script(s)[1], [])
        s["lines"][0]["text"] = ("word " * 29).strip() + "."  # 145 characters
        errors, warnings = mv.validate_script(s)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("lines[0]", warnings[0])
        self.assertIn("140", warnings[0])

    def test_long_text_made_of_short_sentences_does_not_warn(self):
        s = good_script()
        s["lines"][0]["text"] = " ".join(["This is a short sentence."] * 8)  # 200+ characters in total
        self.assertEqual(mv.validate_script(s)[1], [])
        s = good_script()
        s["sources"][0]["title"] = ""
        self.assertTrue(any("sources[0].title" in e for e in errors_of(s)))

    # ---- visuals -------------------------------------------------------------------

    def visual_errors(self, visual):
        s = good_script()
        s["lines"][0]["visual"] = visual
        return errors_of(s)

    def test_flow_visual(self):
        ok = {"type": "flow", "title": "Heat path", "steps": ["Inside", "Pipe", "Coil"]}
        self.assertEqual(self.visual_errors(ok), [])
        self.assertTrue(self.visual_errors({**ok, "steps": ["only one"]}))
        self.assertTrue(self.visual_errors({**ok, "steps": ["a"] * 6}))
        self.assertTrue(self.visual_errors({**ok, "steps": ["a", "x" * 23]}))
        self.assertTrue(self.visual_errors({**ok, "title": "t" * 33}))
        self.assertEqual(self.visual_errors({**ok, "title": "t" * 32, "steps": ["x" * 22, "b"]}), [])

    def test_stat_visual(self):
        ok = {"type": "stat", "value": "-18 °C", "label": "Freezer"}
        self.assertEqual(self.visual_errors(ok), [])
        self.assertTrue(self.visual_errors({**ok, "value": "x" * 11}))
        self.assertTrue(self.visual_errors({**ok, "label": "x" * 41}))
        self.assertTrue(self.visual_errors({"type": "stat", "value": "5"}))

    def test_compare_visual(self):
        side = {"heading": "Old", "text": "Uses more power"}
        ok = {"type": "compare", "title": "Old vs new", "left": side, "right": side}
        self.assertEqual(self.visual_errors(ok), [])
        self.assertTrue(self.visual_errors({**ok, "left": {"heading": "h" * 13, "text": "t"}}))
        self.assertTrue(self.visual_errors({**ok, "right": {"heading": "h", "text": "t" * 49}}))
        broken = dict(ok)
        del broken["right"]
        self.assertTrue(self.visual_errors(broken))

    def test_unknown_or_non_object_visual(self):
        self.assertTrue(self.visual_errors({"type": "pie"}))
        self.assertTrue(self.visual_errors("stat"))
        self.assertEqual(self.visual_errors(None), [])


class WerTests(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(mv.word_error_rate("Your fridge moves heat.", "your fridge moves heat"), 0.0)

    def test_one_substitution_in_ten_words(self):
        ref = "one two three four five six seven eight nine ten"
        hyp = "one two three four five six seven eight nine tin"
        self.assertAlmostEqual(mv.word_error_rate(ref, hyp), 0.1)

    def test_deletion_and_insertion(self):
        self.assertAlmostEqual(mv.word_error_rate("a b c d", "a b d"), 0.25)
        self.assertAlmostEqual(mv.word_error_rate("a b c d", "a b x c d"), 0.25)

    def test_empty_reference(self):
        self.assertEqual(mv.word_error_rate("", ""), 0.0)
        self.assertEqual(mv.word_error_rate("...", "something"), 1.0)

    def test_everything_wrong_is_one(self):
        self.assertEqual(mv.word_error_rate("a b c", "x y z"), 1.0)

    def test_punctuation_and_case_are_ignored(self):
        self.assertEqual(mv.word_error_rate("Doesn't it?", "DOESN'T IT"), 0.0)
        self.assertEqual(mv.word_error_rate("Hello, world!", "hello world"), 0.0)

    def test_nfc_normalisation_for_umlauts(self):
        composed = "Kühlschrank für Wärme"
        decomposed = unicodedata.normalize("NFD", composed)
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(mv.word_error_rate(composed, decomposed), 0.0)

    def test_dash_equals_space(self):
        self.assertEqual(mv.word_error_rate("an ice-cold drink", "an ice cold drink"), 0.0)

    def test_threshold_depends_on_word_count(self):
        self.assertEqual(mv.wer_threshold("one two three four five"), 0.15)
        self.assertEqual(mv.wer_threshold("one two three four"), 0.34)
        self.assertEqual(mv.wer_threshold("Hi."), 0.34)

    def test_levenshtein(self):
        self.assertEqual(mv.levenshtein([], []), 0)
        self.assertEqual(mv.levenshtein(["a"], []), 1)
        self.assertEqual(mv.levenshtein(list("kitten"), list("sitting")), 3)

    def test_five_words_one_wrong_exceeds_limit(self):
        wer = mv.word_error_rate("one two three four five", "one two three four six")
        self.assertGreater(wer, mv.wer_threshold("one two three four five"))


class TimingsTests(unittest.TestCase):
    def test_gap_between_lines_only(self):
        t = mv.build_timings(["a", "b", "c"], [1.0, 2.0, 3.5])
        self.assertEqual([x["index"] for x in t], [0, 1, 2])
        self.assertEqual([x["start"] for x in t], [0.0, 1.25, 3.5])
        self.assertEqual([x["end"] for x in t], [1.0, 3.25, 7.0])
        self.assertEqual(t[2]["text"], "c")


class LengthGateTests(unittest.TestCase):
    def test_inside_range_including_edges(self):
        for d in (61.0, 68.0, 75.0):
            ok, msg = mv.length_gate(d, 150, 61, 75)
            self.assertTrue(ok, d)
            self.assertIn("inside", msg)

    def test_too_short_says_how_many_words_to_add(self):
        ok, msg = mv.length_gate(52.0, 130, 61, 75)  # 2.5 words/s, aim for 63 s -> 11 s * 2.5
        self.assertFalse(ok)
        self.assertIn("too short", msg)
        self.assertIn("52.0 s", msg)
        self.assertIn("130 words", msg)
        self.assertIn("2.50 words/s", msg)
        self.assertIn("Add about 28 words", msg)

    def test_too_long_says_how_many_words_to_remove(self):
        ok, msg = mv.length_gate(80.0, 200, 61, 75)  # aim for 73 s -> 7 s * 2.5
        self.assertFalse(ok)
        self.assertIn("too long", msg)
        self.assertIn("Remove about 18 words", msg)

    def test_zero_minimum_accepts_short_narration(self):
        ok, _ = mv.length_gate(16.2, 52, 0, 999)
        self.assertTrue(ok)

    def test_at_least_one_word_is_suggested(self):
        ok, msg = mv.length_gate(60.9, 150, 61, 75)
        self.assertFalse(ok)
        self.assertRegex(msg, r"Add about [1-9]\d* words")


SRT_GOOD = """1
00:00:00,000 --> 00:00:02,500
Your fridge does not make cold.

2
00:00:02,500 --> 00:00:05,000
It moves heat out
of the box.

3
00:00:05,100 --> 00:00:07,000
Last cue without trailing blank line
"""


class SrtTests(unittest.TestCase):
    def test_parse(self):
        cues = mv.parse_srt(SRT_GOOD)
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0]["start"], 0.0)
        self.assertEqual(cues[1]["start"], 2.5)
        self.assertEqual(cues[1]["end"], 5.0)
        self.assertEqual(cues[1]["text"], "It moves heat out of the box.")
        self.assertEqual(cues[2]["end"], 7.0)

    def test_parse_windows_line_endings(self):
        self.assertEqual(len(mv.parse_srt(SRT_GOOD.replace("\n", "\r\n"))), 3)

    def test_good_file_has_no_problems(self):
        self.assertEqual(mv.srt_problems(mv.parse_srt(SRT_GOOD)), [])

    def test_empty_file_is_a_problem(self):
        self.assertTrue(mv.srt_problems(mv.parse_srt("")))

    def test_zero_length_cue(self):
        bad = "1\n00:00:00,000 --> 00:00:00,000\nx\n\n2\n00:00:01,000 --> 00:00:02,000\ny\n"
        problems = mv.srt_problems(mv.parse_srt(bad))
        self.assertTrue(any("zero length" in p for p in problems))

    def test_overlapping_cues(self):
        bad = "1\n00:00:00,000 --> 00:00:03,000\nx\n\n2\n00:00:02,000 --> 00:00:04,000\ny\n"
        problems = mv.srt_problems(mv.parse_srt(bad))
        self.assertTrue(any("overlap" in p for p in problems))

    def test_non_increasing_start_times(self):
        bad = "1\n00:00:05,000 --> 00:00:06,000\nx\n\n2\n00:00:01,000 --> 00:00:02,000\ny\n"
        problems = mv.srt_problems(mv.parse_srt(bad))
        self.assertTrue(any("not after the previous cue" in p for p in problems))

    def test_issues_carry_the_start_second_and_match_the_problem_texts(self):
        cues = mv.parse_srt("1\n00:00:01,000 --> 00:00:01,000\nIt\n\n2\n00:00:01,000 --> 00:00:02,000\nmoves\n")
        issues = mv.srt_issues(cues)
        self.assertEqual([start for start, _ in issues], [1.0, 1.0])
        self.assertEqual([msg for _, msg in issues], mv.srt_problems(cues))

    def test_timing_hint_names_the_line_and_the_file_to_delete(self):
        timings = [{"index": 0, "start": 0.0, "end": 2.0}, {"index": 1, "start": 2.25, "end": 6.0}]
        self.assertEqual(mv.lines_at_seconds([2.14], timings), [0])  # a gap belongs to the line before it
        self.assertEqual(mv.lines_at_seconds([2.3, 5.0, 2.4], timings), [1])
        hint = mv.subtitle_timing_hint([2.14, 4.0], timings, Path("/w/id"))
        self.assertIn("line(s) 0, 1", hint)
        self.assertIn("/w/id/lines/00.json", hint)
        self.assertIn("/w/id/lines/01.json", hint)
        self.assertIn("running again will not help", hint)
        self.assertEqual(mv.subtitle_timing_hint([], timings, Path("/w/id")), "")

    def test_touching_cues_are_fine(self):
        ok = "1\n00:00:00,000 --> 00:00:01,000\nx\n\n2\n00:00:01,000 --> 00:00:02,000\ny\n"
        self.assertEqual(mv.srt_problems(mv.parse_srt(ok)), [])


class MptHelperTests(unittest.TestCase):
    def test_command_for_pexels(self):
        cmd = mv.build_mpt_command("/bin/uv", "Line one. Line two.", ["a b", "c"], Path("/w/narration.wav"), "T-ID")
        self.assertEqual(cmd[:4], ["/bin/uv", "run", "python", "cli.py"])
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-script"], "Line one. Line two.")
        self.assertEqual(pairs["--video-terms"], "a b,c")
        self.assertEqual(pairs["--custom-audio-file"], "/w/narration.wav")
        self.assertEqual(pairs["--bgm-type"], "none")
        self.assertEqual(pairs["--font-name"], "BeVietnamPro-Bold.ttf")
        self.assertEqual(pairs["--subtitle-position"], "custom")
        self.assertIn("--custom-position", pairs)
        self.assertTrue(0 < float(pairs["--custom-position"]) < 100)
        self.assertIn("--subtitle-enabled", cmd)
        self.assertIn("--no-subtitle-background-enabled", cmd)  # a background saved by the MPT WebUI must never apply
        self.assertNotIn("--subtitle-background-enabled", cmd)
        self.assertEqual(pairs["--subtitle-display-mode"], "word_by_word")
        self.assertEqual(pairs["--subtitle-animation"], "pop_spring")
        self.assertEqual(pairs["--font-size"], str(mv.CAPTION_FONT_MAX))
        self.assertEqual(pairs["--stroke-width"], str(mv.caption_stroke_width(mv.CAPTION_FONT_MAX)))
        self.assertEqual(pairs["--stroke-color"], "#000000")
        self.assertEqual(pairs["--text-fore-color"], "#FFFFFF")
        self.assertEqual(pairs["--video-aspect"], "9:16")
        self.assertEqual(pairs["--task-id"], "T-ID")
        self.assertNotIn("--video-source", cmd)
        self.assertNotIn("--video-materials", cmd)

    def test_command_for_local_materials(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/m/a.mp4"), Path("/m/b.mp4")])
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-source"], "local")
        self.assertEqual(pairs["--video-materials"], "/m/a.mp4,/m/b.mp4")

    def test_command_passes_the_footage_source(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", source="pixabay")
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-source"], "pixabay")
        self.assertNotIn("--video-materials", cmd)

    def test_local_materials_win_over_a_footage_source(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/m/a.mp4")], source="pexels")
        self.assertEqual(dict(zip(cmd[4:], cmd[5:]))["--video-source"], "local")
        self.assertEqual(cmd.count("--video-source"), 1)

    def test_pick_footage_source(self):
        self.assertEqual(mv.pick_footage_source({"pexels_api_keys": ["p"], "pixabay_api_keys": ["x"]}), "pexels")
        self.assertEqual(mv.pick_footage_source({"pexels_api_keys": [], "pixabay_api_keys": ["x"]}), "pixabay")
        self.assertEqual(mv.pick_footage_source({"pexels_api_keys": ["  "], "pixabay_api_keys": ["x"]}), "pixabay")  # blank key ignored
        self.assertIsNone(mv.pick_footage_source({"pexels_api_keys": [""], "pixabay_api_keys": []}))
        self.assertIsNone(mv.pick_footage_source({}))

    def test_command_takes_the_given_caption_size(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", font_size=90, stroke_width=7)
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--font-size"], "90")
        self.assertEqual(pairs["--stroke-width"], "7")

    def test_command_takes_the_given_caption_position(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", position_percent=74.57)
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--custom-position"], "74.57")

    def test_script_text_keeps_only_sentence_punctuation_in_sentence_mode(self):
        texts = ["Then a compressor squeezes it, and the heat escapes: that is why; it works.", "Is it cold? Yes!"]
        self.assertEqual(
            mv.mpt_script_text(texts, subtitle_mode="sentence"),
            "Then a compressor squeezes it and the heat escapes that is why it works. Is it cold? Yes!",
        )

    def test_script_text_is_kept_as_written_in_word_by_word_mode(self):
        # MPT's whisper path never reads the script in word_by_word mode (no subtitle.correct step)
        texts = ["Then a compressor squeezes it, and the heat escapes: that is why; it works.", "Is  it cold?\n Yes!"]
        self.assertEqual(
            mv.mpt_script_text(texts),
            "Then a compressor squeezes it, and the heat escapes: that is why; it works. Is it cold? Yes!",
        )
        self.assertEqual(mv.mpt_script_text(["First line", "Second line."]), "First line. Second line.")

    def test_script_text_adds_a_period_when_a_line_has_none(self):
        self.assertEqual(mv.mpt_script_text(["First line", "Second line."], subtitle_mode="sentence"), "First line. Second line.")

    def test_script_text_handles_dashes_ellipsis_and_number_commas(self):
        sentence = lambda t: mv.mpt_script_text([t], subtitle_mode="sentence")  # noqa: E731
        self.assertEqual(sentence("Wait … really – yes"), "Wait really yes.")
        self.assertEqual(sentence("It took 1,000 years, maybe."), "It took 1,000 years maybe.")
        self.assertEqual(sentence("An ice-cold drink."), "An ice-cold drink.")

    def test_script_text_has_no_comma_split_points(self):
        text = mv.mpt_script_text(["Dann presst ein Kompressor es zusammen, und die Wärme entweicht."], subtitle_mode="sentence")
        self.assertNotIn(",", text)
        self.assertEqual(text, "Dann presst ein Kompressor es zusammen und die Wärme entweicht.")

    def test_parse_result_takes_the_json_line_after_the_logs(self):
        payload = {"task_id": "abc", "result": {"videos": ["/v/final-1.mp4"], "subtitle_path": "/v/subtitle.srt", "warnings": None}}
        lines = ["2026-10-13 INFO | start CLI task", '{"not": "ours"}', json.dumps(payload), ""]
        self.assertEqual(mv.parse_mpt_result(lines), payload)

    def test_parse_result_none_when_missing(self):
        self.assertIsNone(mv.parse_mpt_result(["just logs", "{broken json", '{"result": 5}']))

    def test_strip_ansi(self):
        self.assertEqual(mv.strip_ansi("\x1b[32mINFO\x1b[0m hello"), "INFO hello")

    def test_notes_collect_mismatch_and_extra_lines(self):
        log = "\n".join([
            "\x1b[33mWARNING\x1b[0m | Mismatch - Script: hello, Subtitle: hullo",
            "INFO | Subtitle is correct",
            "WARNING | Extra script line: goodbye",
        ])
        notes = mv.collect_mpt_notes(log)
        self.assertEqual(len(notes), 2)
        self.assertIn("Mismatch - Script: hello", notes[0])
        self.assertNotIn("\x1b", notes[0])
        self.assertIn("Extra script line: goodbye", notes[1])

    def test_whisper_language_detection(self):
        log = "INFO | detected language: 'de', probability: 0.98"
        self.assertEqual(mv.detect_whisper_language(log), ("de", 0.98))
        self.assertIsNone(mv.detect_whisper_language("nothing here"))

    def test_whisper_language_check(self):
        ok, _ = mv.check_whisper_language("detected language: 'en', probability: 0.99", "en")
        self.assertTrue(ok)
        ok, msg = mv.check_whisper_language("detected language: 'de', probability: 0.97", "en")
        self.assertFalse(ok)
        self.assertIn("'de'", msg)
        ok, _ = mv.check_whisper_language("detected language: 'nl', probability: 0.31", "de")
        self.assertTrue(ok)  # unsure guess is not "clearly different"
        ok, _ = mv.check_whisper_language("no language line", "en")
        self.assertTrue(ok)

    def test_bgm_detection(self):
        self.assertEqual(mv.find_bgm_usage("INFO | combining video\nINFO | video saved: x.mp4", {"bgm_type": "", "bgm_file": ""}), [])
        self.assertTrue(mv.find_bgm_usage("INFO | using ./resource/songs/output000.mp3"))
        self.assertTrue(mv.find_bgm_usage("ERROR | failed to mix background music: type=random"))
        self.assertTrue(mv.find_bgm_usage("ok", {"bgm_type": "random"}))
        self.assertTrue(mv.find_bgm_usage("ok", {"bgm_type": "", "bgm_file": "/x/song.mp3"}))
        # our own "# command" header line must not count
        self.assertEqual(mv.find_bgm_usage("# uv run --bgm-file resource/songs/x.mp3"), [])


class CreditsTests(unittest.TestCase):
    def test_pexels_credit_line_format(self):
        recs = [{"provider": "pexels", "local_file": "a.mp4", "source_page": "https://www.pexels.com/video/a-1/",
                 "creator": {"id": "7", "name": "Jane Doe", "profile_page": "https://www.pexels.com/@jane"}}]
        lines, notes = mv.build_credits(recs)
        self.assertEqual(lines, ["Videos by Jane Doe on Pexels (pexels.com): https://www.pexels.com/video/a-1/"])
        self.assertEqual(notes, [])

    def test_missing_creator_falls_back_to_page_url_with_a_note(self):
        recs = [{"provider": "pexels", "local_file": "a.mp4", "source_page": "https://www.pexels.com/video/a-1/"}]
        lines, notes = mv.build_credits(recs)
        self.assertEqual(lines, ["Video on Pexels (pexels.com): https://www.pexels.com/video/a-1/"])
        self.assertTrue(any("no creator" in n for n in notes))

    def test_duplicates_and_local_are_dropped(self):
        rec = {"provider": "pexels", "source_page": "https://www.pexels.com/video/a-1/", "creator": {"name": "Jane"}}
        lines, _ = mv.build_credits([rec, dict(rec), {"provider": "local", "local_file": "x.mp4"}, {"provider": ""}])
        self.assertEqual(len(lines), 1)

    def test_only_used_providers_are_credited(self):
        recs = [
            {"provider": "pexels", "source_page": "https://www.pexels.com/video/a-1/", "creator": {"name": "Jane"}},
            {"provider": "pixabay", "source_page": "https://pixabay.com/videos/b-2/", "creator": {"name": "Max"}},
        ]
        lines, _ = mv.build_credits(recs)
        self.assertEqual(len(lines), 2)
        self.assertIn("Pixabay (pixabay.com)", lines[1])

    def test_no_records_no_credits(self):
        self.assertEqual(mv.build_credits([]), ([], []))
        self.assertEqual(mv.build_credits(None), ([], []))


class NamingAndCaptionTests(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(mv.slug_from_id("2026-10-14-en-fridge", "en"), "fridge")
        self.assertEqual(mv.slug_from_id("2026-10-14-de-kuehlschrank-und-mehr", "de"), "kuehlschrank-und-mehr")
        self.assertEqual(mv.slug_from_id("fridge", "en"), "fridge")
        self.assertEqual(mv.slug_from_id("en-fridge", "en"), "fridge")
        self.assertEqual(mv.slug_from_id("_test-en", "en"), "test-en")

    def test_review_folder_uses_date_from_id_else_today(self):
        today = datetime.date(2026, 10, 13)
        self.assertEqual(mv.review_folder_name({"id": "2026-10-14-en-fridge", "language": "en"}, today), "2026-10-14-en-fridge")
        self.assertEqual(mv.review_folder_name({"id": "2026-10-20-de-kuehlschrank", "language": "de"}, today), "2026-10-20-de-kuehlschrank")
        self.assertEqual(mv.review_folder_name({"id": "_test-en", "language": "en"}, today), "2026-10-13-en-test-en")
        self.assertEqual(mv.review_folder_name({"id": "2026-13-45-en-x", "language": "en"}, today), "2026-10-13-en-2026-13-45-en-x")

    def test_caption_layout_english(self):
        text = mv.build_caption(good_script(), ["Videos by Jane on Pexels (pexels.com): https://p/1"])
        expected = (
            "How your fridge really works\n\n"
            "Your fridge moves heat out. Here is how.\n\n"
            "#science #fridge #shorts\n\n"
            "AI voice. Script written with AI assistance and fact-checked.\n"
            "Videos by Jane on Pexels (pexels.com): https://p/1\n\n"
            "Sources:\n"
            "Refrigerator – https://en.wikipedia.org/wiki/Refrigerator\n"
            "Vapor-compression – https://en.wikipedia.org/wiki/Vapor-compression_refrigeration\n"
        )
        self.assertEqual(text, expected)

    def test_caption_german_without_credits(self):
        s = good_script()
        s["language"] = "de"
        text = mv.build_caption(s, [])
        self.assertIn("\n\nKI-Stimme. Skript mit KI-Unterstützung geschrieben und faktengeprüft.\n\nQuellen:\n", text)
        self.assertNotIn("Sources:", text)
        self.assertNotIn("Pexels", text)


class FinalChecksTests(unittest.TestCase):
    def results(self, info, min_seconds=61):
        return {name: (ok, detail) for name, ok, detail in mv.check_final_info(info, min_seconds)}

    def test_all_good(self):
        r = self.results({"duration": 65.0, "width": 1080, "height": 1920, "has_audio": True})
        self.assertTrue(all(ok for ok, _ in r.values()))

    def test_duration_tolerance_is_half_a_second(self):
        base = {"width": 1080, "height": 1920, "has_audio": True}
        self.assertTrue(self.results({**base, "duration": 60.5})["final duration"][0])
        self.assertFalse(self.results({**base, "duration": 60.4})["final duration"][0])

    def test_min_zero_skips_duration_check(self):
        r = self.results({"duration": 3.0, "width": 1080, "height": 1920, "has_audio": True}, min_seconds=0)
        self.assertTrue(r["final duration"][0])

    def test_wrong_size_and_missing_audio(self):
        r = self.results({"duration": 65.0, "width": 1920, "height": 1080, "has_audio": False})
        self.assertFalse(r["final size"][0])
        self.assertFalse(r["final audio"][0])


class MiscTests(unittest.TestCase):
    def test_tts_engine_check(self):
        good = {"active": "mlx-audio", "active_model": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit"}
        self.assertIsNone(mv.check_tts_engine(good))
        self.assertIn("MLX-Audio + Qwen3-TTS CustomVoice", mv.check_tts_engine({**good, "active": "omnivoice"}))
        self.assertTrue(mv.check_tts_engine({**good, "active_model": "mlx-community/Kokoro-82M"}))
        self.assertTrue(mv.check_tts_engine({"active": "mlx-audio", "active_model": None}))
        self.assertIsNone(mv.check_tts_engine({"active": "mlx-audio", "active_model": {"id": "Qwen3-TTS-12Hz-1.7B-CustomVoice"}}))

    def test_multipart_body(self):
        body, ctype = mv.build_multipart({"model": "m", "language": "de"}, "file", "a.wav", b"RIFFDATA", "audio/wav")
        boundary = ctype.split("boundary=")[1]
        self.assertTrue(ctype.startswith("multipart/form-data"))
        self.assertIn(b'name="model"\r\n\r\nm\r\n', body)
        self.assertIn(b'name="file"; filename="a.wav"', body)
        self.assertIn(b"RIFFDATA", body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_newest_media_scripts_dir_is_picked_by_version_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for version, has_speak in (("1.0.9", True), ("1.0.10", True), ("2.0.0", False)):
                folder = base / version / "skills" / "media-studio" / "scripts"
                folder.mkdir(parents=True)
                if has_speak:
                    (folder / "speak.mjs").write_text("//")
            picked = mv.pick_media_scripts_dir(base)
            self.assertEqual(picked.parents[2].name, "1.0.10")

    def test_missing_media_scripts_dir_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(mv.GateError):
                mv.pick_media_scripts_dir(Path(tmp))


FONT_FILE = Path(__file__).resolve().parents[2] / "MoneyPrinterTurbo" / "resource" / "fonts" / "BeVietnamPro-Bold.ttf"


class FormatSrtTests(unittest.TestCase):
    def test_round_trip_and_clean_separators(self):
        mpt_style = "1\n00:00:00,000 --> 00:00:00,240\nYour\n        \n2\n00:00:00,240 --> 00:01:01,520\nfridge\n        \n"
        cues = mv.parse_srt(mpt_style)
        text = mv.format_srt(cues)
        self.assertEqual(text, "1\n00:00:00,000 --> 00:00:00,240\nYour\n\n2\n00:00:00,240 --> 00:01:01,520\nfridge\n\n")
        self.assertEqual(mv.parse_srt(text), cues)
        self.assertNotIn("        ", text)

    def test_milliseconds_do_not_drift_or_overflow(self):
        text = mv.format_srt([{"start": 0.9996, "end": 3599.9999, "text": "x"}])
        self.assertIn("00:00:01,000 --> 01:00:00,000", text)


class SrtAccuracyTests(unittest.TestCase):
    def cues(self, *texts):
        return [{"index": k + 1, "start": k * 0.4, "end": k * 0.4 + 0.3, "text": t} for k, t in enumerate(texts)]

    def test_word_cues_match_the_script(self):
        script = ["Your fridge does not make cold.", "It moves heat out."]
        cues = self.cues("Your", "fridge", "does", "not", "make", "cold.", "It", "moves", "heat", "out.")
        ok, wer, msg, diffs = mv.check_srt_accuracy(cues, script)
        self.assertTrue(ok)
        self.assertEqual(wer, 0.0)
        self.assertEqual(diffs, [])
        self.assertIn("0.000", msg)

    def test_wer_above_limit_fails_and_lists_the_words(self):
        script = ["one two three four five six seven eight nine ten"]
        cues = self.cues("one", "two", "free", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven")  # 2 errors in 10
        ok, wer, msg, diffs = mv.check_srt_accuracy(cues, script)
        self.assertFalse(ok)
        self.assertAlmostEqual(wer, 0.2)
        self.assertIn('script "three" -> subtitle "free"', msg)
        self.assertIn('extra word(s) in the subtitle: "eleven"', msg)
        self.assertEqual(len(diffs), 2)

    def test_limit_is_inclusive_and_default_is_ten_percent(self):
        self.assertEqual(mv.SRT_WER_LIMIT, 0.10)
        script = ["one two three four five six seven eight nine ten"]
        cues = self.cues("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "tin")  # exactly 0.1
        ok, wer, _, _ = mv.check_srt_accuracy(cues, script)
        self.assertAlmostEqual(wer, 0.1)
        self.assertTrue(ok)

    def test_punctuation_case_and_dashes_do_not_count(self):
        ok, wer, _, _ = mv.check_srt_accuracy(self.cues("Noise", "cancelling", "Kühlschrank,"), ["Noise-cancelling kühlschrank"])
        self.assertTrue(ok)
        self.assertEqual(wer, 0.0)

    def test_no_cues_fails(self):
        ok, wer, _, _ = mv.check_srt_accuracy([], ["Some words here."])
        self.assertFalse(ok)
        self.assertEqual(wer, 1.0)

    def test_word_differences_shapes(self):
        self.assertEqual(mv.word_differences("a b c", "a b c"), [])
        self.assertEqual(mv.word_differences("a b c", "a c"), ['script word(s) missing in the subtitle: "b"'])
        self.assertEqual(mv.word_differences("a c", "a b c"), ['extra word(s) in the subtitle: "b"'])
        many = mv.word_differences(" ".join(["x"] * 3 * 40), " ".join(["x", "y", "z"] * 40), limit=5)
        self.assertEqual(len(many), 6)
        self.assertTrue(many[-1].startswith("... and "))

    def test_first_caption_problem(self):
        self.assertIsNone(mv.first_caption_problem([{"start": 0.3, "end": 0.6, "text": "x", "index": 1}]))
        self.assertIn("2.50 s", mv.first_caption_problem([{"start": 2.5, "end": 3.0, "text": "x", "index": 1}]))
        self.assertTrue(mv.first_caption_problem([]))


@unittest.skipUnless(FONT_FILE.is_file(), "MoneyPrinterTurbo font not found")
class CaptionStyleTests(unittest.TestCase):
    def test_font_measure_matches_known_widths(self):
        # Measured once with Pillow: the advance sum is within a few pixels of the ink width.
        measure = mv.FontMeasure(FONT_FILE.read_bytes())
        for word, pillow_px_at_100 in (("Kühlschrankkompressor", 1234), ("Flugzeugtriebwerken", 1078), ("refrigerant", 560)):
            width = measure.text_width(word, 100)
            self.assertAlmostEqual(width / pillow_px_at_100, 1.0, delta=0.01, msg=word)
        self.assertEqual(measure.text_width("", 100), 0)
        self.assertEqual(measure.line_height(100), 127)

    def test_long_german_word_forces_a_smaller_font_but_never_overflows(self):
        style = mv.pick_caption_style(["Der Flugzeugtriebwerken, sagt er."], FONT_FILE)
        self.assertEqual(style["widest_word"], "Flugzeugtriebwerken,")
        self.assertLess(style["font_size"], 100)
        self.assertLessEqual(style["widest_word_px"], mv.CAPTION_MAX_WORD_PX + 2)
        self.assertLessEqual(style["widest_word_px"], 1000)
        self.assertTrue(style["size_limited_by_word"])

    def test_short_words_get_the_maximum_size(self):
        style = mv.pick_caption_style(["Your fridge moves heat."], FONT_FILE)
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MAX)
        self.assertFalse(style["size_limited_by_word"])

    def test_even_an_absurd_word_stays_inside_the_limits(self):
        style = mv.pick_caption_style(["Donaudampfschifffahrtsgesellschaftskapitaensmuetze"], FONT_FILE)
        self.assertEqual(style["font_size"], mv.CAPTION_FONT_MIN)
        # the font cannot shrink any further, so this must be REPORTED, not silently cut in two on screen
        problem = mv.caption_word_problem(style)
        self.assertIsNotNone(problem)
        self.assertIn("Donaudampfschifffahrtsgesellschaftskapitaensmuetze", problem)
        self.assertIn("Split or hyphenate", problem)

    def test_german_compounds_that_used_to_pass_silently_are_reported(self):
        # 962 px and 983 px at the smallest size: both are wider than the limit
        for word in ("Lebensmittelverschwendung,", "Geschwindigkeitsbegrenzung."):
            style = mv.pick_caption_style([f"Das ist {word}"], FONT_FILE)
            self.assertEqual(style["font_size"], mv.CAPTION_FONT_MIN, word)
            self.assertIsNotNone(mv.caption_word_problem(style), word)

    def test_words_that_fit_are_not_reported(self):
        for text in ("Your fridge moves heat.", "Der Kühlschrankkompressor läuft.", "Flugzeugtriebwerken, sagt er."):
            style = mv.pick_caption_style([text], FONT_FILE)
            self.assertIsNone(mv.caption_word_problem(style), text)

    def test_captions_stay_below_the_diagram_panels(self):
        for text in ("Your fridge moves heat.", "Kühlschrankkompressor", "a"):
            style = mv.pick_caption_style([text], FONT_FILE)
            self.assertGreaterEqual(style["box_top_y"], mv.CAPTION_TOP_LIMIT_Y, text)
            self.assertAlmostEqual(style["box_top_y"], mv.CAPTION_BOX_TOP_Y, delta=1, msg=text)
            # ... and the whole box stays above the YouTube Shorts title/channel overlay
            self.assertLess(style["box_top_y"] + style["box_height"], 1600, text)

    def test_custom_position_puts_the_box_top_where_we_want_it_for_every_font_size(self):
        for size in (64, 90, 110, 120):
            stroke = mv.caption_stroke_width(size)
            height = mv.caption_box_height(size, stroke, math.ceil(1.27 * size))
            percent = mv.caption_position_percent(height)
            self.assertAlmostEqual(mv.caption_box_top_y(height, percent), mv.CAPTION_BOX_TOP_Y, delta=1, msg=size)

    def test_box_height_follows_mpts_formula(self):
        self.assertEqual(mv.caption_box_height(120, 10, 152), 152 + 42 + 30 + 20)

    def test_box_top_is_clamped_like_mpt_does(self):
        self.assertEqual(mv.caption_box_top_y(200, 0), 10)
        self.assertEqual(mv.caption_box_top_y(200, 100), 1920 - 200 - 10)

    def test_unreadable_font_falls_back_to_a_safe_estimate(self):
        style = mv.pick_caption_style(["Alltagstechnik, sagt er."], Path("/nonexistent/font.ttf"))
        self.assertIn("safe estimate", style["note"])
        self.assertLessEqual(style["widest_word_px"], mv.CAPTION_MAX_WORD_PX + 2)

    def test_stroke_scales_with_size(self):
        self.assertEqual(mv.caption_stroke_width(120), 10)
        self.assertEqual(mv.caption_stroke_width(64), 5)
        self.assertEqual(mv.caption_stroke_width(20), 3)


class RunStreamingTests(unittest.TestCase):
    """The timeout must stop the launcher AND what it started, and the output loop must end."""

    def test_normal_run_streams_lines_and_returns_exit_code(self):
        seen = []
        code, timed_out = mv.run_streaming([sys.executable, "-c", "print('a'); print('b'); import sys; sys.exit(3)"],
                                           None, None, 30, seen.append)
        self.assertEqual((code, timed_out), (3, False))
        self.assertEqual(seen, ["a", "b"])

    def test_timeout_kills_the_whole_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            # The launcher starts a grandchild that inherits the output pipe, like `uv` does for python/ffmpeg.
            code_text = (
                "import subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
                "print('started', flush=True)\n"
                "time.sleep(120)\n"
            )
            seen = []
            started = time.monotonic()
            code, timed_out = mv.run_streaming([sys.executable, "-c", code_text], None, None, 1.5, seen.append)
            elapsed = time.monotonic() - started
            self.assertTrue(timed_out)
            self.assertNotEqual(code, 0)
            self.assertLess(elapsed, 20, "the output loop must end soon after the timeout")
            self.assertEqual(seen, ["started"])
            grandchild = int(pid_file.read_text())
            for _ in range(50):  # give the system a moment to remove the killed process
                try:
                    os.kill(grandchild, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                os.kill(grandchild, 9)
                self.fail("the grandchild process survived the timeout")

    def test_missing_command_raises_oserror(self):
        with self.assertRaises(OSError):
            mv.run_streaming(["/nonexistent/program"], None, None, 5, lambda line: None)

    def test_interrupt_in_the_callback_kills_the_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "child.pid"
            code_text = (
                "import os, sys, time\n"
                f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
                "print('go', flush=True)\n"
                "time.sleep(120)\n"
            )

            def stop(line):
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                mv.run_streaming([sys.executable, "-c", code_text], None, None, 60, stop)
            pid = int(pid_file.read_text())
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                os.kill(pid, 9)
                self.fail("the child survived Ctrl-C")


class PreflightRobustnessTests(unittest.TestCase):
    def test_voicestudio_errors_become_plain_gate_errors(self):
        for exc in (urllib.error.URLError("refused"), ValueError("bad json"), OSError("reset"), mv.http.client.IncompleteRead(b"x")):
            with mock.patch.object(mv, "http_get_json", side_effect=exc):
                with self.assertRaises(mv.GateError) as ctx:
                    mv.voicestudio_info("/engines/tts", "which voice engine is active")
                self.assertIn("/engines/tts", str(ctx.exception))
                self.assertIn("VoiceStudio", str(ctx.exception))

    def test_non_object_answer_is_a_gate_error(self):
        with mock.patch.object(mv, "http_get_json", return_value=["not", "an", "object"]):
            with self.assertRaises(mv.GateError) as ctx:
                mv.voicestudio_info("/engines/asr", "which transcription engine is active")
        self.assertIn("unexpected", str(ctx.exception))

    def test_good_answer_passes_through(self):
        with mock.patch.object(mv, "http_get_json", return_value={"active": "x"}):
            self.assertEqual(mv.voicestudio_info("/engines/asr", "w"), {"active": "x"})

    def test_visuals_module_without_render_function_is_refused(self):
        fake = type(sys)("visuals")
        with mock.patch.dict(sys.modules, {"visuals": fake}):
            with self.assertRaises(mv.GateError) as ctx:
                mv.load_visuals_module([1, 2])
        self.assertIn("render_and_overlay", str(ctx.exception))
        self.assertIn("--no-visuals", str(ctx.exception))

    def test_visuals_module_with_render_function_is_accepted(self):
        fake = type(sys)("visuals")
        fake.render_and_overlay = lambda *a, **k: {}
        with mock.patch.dict(sys.modules, {"visuals": fake}):
            self.assertIs(mv.load_visuals_module([1]), fake)

    def test_missing_visuals_module_names_the_lines(self):
        with mock.patch.object(mv.importlib, "import_module", side_effect=ModuleNotFoundError("no", name="visuals")):
            with self.assertRaises(mv.GateError) as ctx:
                mv.load_visuals_module([3, 5])
        self.assertIn("lines 3, 5", str(ctx.exception))

    def test_broken_visuals_module_is_a_gate_error(self):
        with mock.patch.object(mv.importlib, "import_module", side_effect=SyntaxError("oops")):
            with self.assertRaises(mv.GateError) as ctx:
                mv.load_visuals_module([0])
        self.assertIn("could not be imported", str(ctx.exception))


class VoiceFailureMessageTests(unittest.TestCase):
    def test_no_audio_is_not_called_a_wording_problem(self):
        bad = [{"index": 2, "wer": None, "error": "speak.mjs made no audio in any of 3 attempts: connect ECONNREFUSED", "threshold": 0.15}]
        msg = mv.voice_failure_message(bad, 3)
        self.assertIn("VoiceStudio failed to make audio for line(s) 2", msg)
        self.assertIn("check VoiceStudio", msg)
        self.assertIn("ECONNREFUSED", msg)
        self.assertNotIn("Reword", msg)

    def test_mishearing_still_says_reword(self):
        bad = [{"index": 1, "wer": 0.5, "threshold": 0.15, "text": "script text", "heard": "other text"}]
        msg = mv.voice_failure_message(bad, 3)
        self.assertIn("Reword", msg)
        self.assertIn("script text", msg)
        self.assertIn("other text", msg)
        self.assertNotIn("failed to make audio", msg)

    def test_both_kinds_are_reported_separately(self):
        bad = [
            {"index": 0, "wer": None, "error": "boom", "threshold": 0.3},
            {"index": 4, "wer": 0.4, "threshold": 0.15, "text": "a", "heard": "b"},
        ]
        msg = mv.voice_failure_message(bad, 3)
        self.assertIn("failed to make audio for line(s) 0", msg)
        self.assertIn("1 line(s) are still not understood", msg)


class ReportPathTests(unittest.TestCase):
    def test_repoint_replaces_only_exact_matches_everywhere(self):
        report = {"a": "/w/sub.srt", "b": ["/w/sub.srt", "/w/other"], "c": {"d": "/w/sub.srt "}, "n": 5}
        out = mv.repoint_paths(report, {"/w/sub.srt": "/r/subtitles.srt"})
        self.assertEqual(out, {"a": "/r/subtitles.srt", "b": ["/r/subtitles.srt", "/w/other"], "c": {"d": "/w/sub.srt "}, "n": 5})
        self.assertEqual(report["a"], "/w/sub.srt")  # input untouched

    def test_deleted_paths_become_none_but_siblings_stay(self):
        report = {"narration": {"path": "/w/id/narration.wav"}, "log": "/w/id/mpt.log", "task": "/mpt/tasks/T/final-1.mp4",
                  "kept": "/review/x/final.mp4", "similar": "/w/id/narration.wav.bak", "text": "narration.wav is gone",
                  "clips": ["/mpt/tasks/T/a.mp4", "/keep/b.mp4"]}
        out = mv.drop_deleted_paths(report, ["/w/id/narration.wav", "/mpt/tasks/T"])
        self.assertEqual(out["clips"], ["/keep/b.mp4"])  # left out of lists
        self.assertIsNone(out["narration"]["path"])
        self.assertIsNone(out["task"])
        self.assertEqual(out["log"], "/w/id/mpt.log")
        self.assertEqual(out["kept"], "/review/x/final.mp4")
        self.assertEqual(out["similar"], "/w/id/narration.wav.bak")
        self.assertEqual(out["text"], "narration.wav is gone")


class OutputAndCleanupTests(unittest.TestCase):
    """step_output + step_cleanup on a fake tree: subtitles are kept, the report points at kept files."""

    def make_ctx(self, tmp: Path, keep_work: bool):
        args = mv.parse_args(["x.json"] + (["--keep-work"] if keep_work else []))
        ctx = mv.Ctx(args)
        ctx.script = good_script()
        ctx.work = tmp / "work" / ctx.script["id"]
        (ctx.work / "lines").mkdir(parents=True)
        for name in ("narration.wav", "timings.json", "mpt.log", "failed-report.json", "sheet.png", "final-visuals.mp4"):
            (ctx.work / name).write_text(name)
        task_dir = tmp / "mpt" / "storage" / "tasks" / "T1"
        task_dir.mkdir(parents=True)
        (task_dir / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:00,300\nHello\n        \n2\n00:00:00,300 --> 00:00:00,600\nworld\n        \n")
        (task_dir / "final-1.mp4").write_text("v")
        mpt = {"video": task_dir / "final-1.mp4", "subtitle": task_dir / "subtitle.srt", "task_dir": task_dir, "task_id": "T1"}
        ctx.report.update(
            narration={"path": str(ctx.work / "narration.wav"), "duration": 3.0},
            mpt={"log": str(ctx.work / "mpt.log"), "subtitle_path": str(mpt["subtitle"]), "video": str(mpt["video"])},
            visuals={"out": str(ctx.work / "final-visuals.mp4"), "panels": 1},
        )
        ctx.checks += [  # the sentences the real steps write (they contain paths)
            {"name": "narration joined", "ok": True, "detail": f"3.0 s, 2 lines, 0.25 s gaps; timings in {ctx.work / 'timings.json'}"},
            {"name": "MPT subtitle path", "ok": True, "detail": f"{mpt['subtitle']} (the result must contain a subtitle file)"},
            {"name": "MPT video", "ok": True, "detail": f"{mpt['video']}"},
            {"name": "visuals", "ok": True, "detail": f"1 visual line(s) rendered onto the video -> {ctx.work / 'final-visuals.mp4'}"},
            {"name": "contact sheet", "ok": True, "detail": str(ctx.work / "sheet.png")},
        ]
        return ctx, mpt

    def run_steps(self, keep_work):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx, mpt = self.make_ctx(tmp, keep_work)
            with mock.patch.object(mv, "REVIEW_ROOT", tmp / "review"), mock.patch.object(mv, "MPT_DIR", tmp / "mpt"), \
                    contextlib.redirect_stdout(io.StringIO()):
                folder = mv.step_output(ctx, ctx.work / "final-visuals.mp4", ctx.work / "sheet.png", ["credit"], mpt)
                after_output = json.loads((folder / "report.json").read_text(encoding="utf-8"))
                mv.step_cleanup(ctx, mpt, folder)
                after_cleanup = json.loads((folder / "report.json").read_text(encoding="utf-8"))
            return {"folder_files": sorted(p.name for p in folder.iterdir()), "srt": (folder / "subtitles.srt").read_text(),
                    "after_output": after_output, "after_cleanup": after_cleanup, "folder": str(folder),
                    "work_left": sorted(p.name for p in ctx.work.iterdir()), "task_dir_exists": mpt["task_dir"].exists(),
                    "work": str(ctx.work), "task_dir": str(mpt["task_dir"])}

    def test_subtitles_are_kept_and_report_points_at_kept_copies(self):
        r = self.run_steps(keep_work=False)
        self.assertEqual(r["folder_files"], ["caption.txt", "final.mp4", "report.json", "sheet.png", "subtitles.srt"])
        self.assertEqual(r["srt"], "1\n00:00:00,000 --> 00:00:00,300\nHello\n\n2\n00:00:00,300 --> 00:00:00,600\nworld\n\n")
        for report in (r["after_output"], r["after_cleanup"]):
            self.assertEqual(report["mpt"]["subtitle_path"], r["folder"] + "/subtitles.srt")
            self.assertEqual(report["visuals"]["out"], r["folder"] + "/final.mp4")
            self.assertEqual(report["outputs"]["subtitles"], r["folder"] + "/subtitles.srt")

    def test_cleanup_records_what_it_deleted_and_nulls_dead_paths(self):
        r = self.run_steps(keep_work=False)
        self.assertEqual(r["work_left"], ["mpt.log", "timings.json"])
        self.assertFalse(r["task_dir_exists"])
        cleanup = r["after_cleanup"]["cleanup"]
        self.assertTrue(cleanup["performed"])
        names = [Path(x).name for x in cleanup["removed"]]
        for expected in ("T1", "lines", "narration.wav", "sheet.png", "final-visuals.mp4", "failed-report.json"):
            self.assertIn(expected, names)
        self.assertNotIn("mpt.log", names)
        self.assertIsNone(r["after_cleanup"]["narration"]["path"])
        self.assertIsNone(r["after_cleanup"]["mpt"]["video"])
        self.assertTrue(r["after_cleanup"]["mpt"]["log"].endswith("mpt.log"))
        self.assertIsNotNone(r["after_output"]["narration"]["path"])  # before cleanup the file still existed

    @staticmethod
    def details(report):
        return {c["name"]: c["detail"] for c in report["checks"]}

    def test_check_sentences_point_at_the_kept_copies(self):
        r = self.run_steps(keep_work=False)
        folder = r["folder"]
        for report in (r["after_output"], r["after_cleanup"]):
            d = self.details(report)
            self.assertIn(f"{folder}/subtitles.srt", d["MPT subtitle path"])
            self.assertTrue(d["visuals"].endswith(f"-> {folder}/final.mp4"), d["visuals"])
            self.assertEqual(d["contact sheet"], f"{folder}/sheet.png")
            self.assertNotIn(r["task_dir"], d["MPT subtitle path"])

    def test_check_sentences_never_name_a_deleted_file_after_cleanup(self):
        r = self.run_steps(keep_work=False)
        d = self.details(r["after_cleanup"])
        self.assertEqual(d["MPT video"], "final-1.mp4 (deleted after the run)")
        self.assertIn(r["work"] + "/timings.json", d["narration joined"])  # a kept file keeps its full path
        for name, detail in d.items():
            self.assertNotIn(r["task_dir"], detail, name)
            for gone in ("narration.wav", "final-visuals.mp4"):
                self.assertNotIn(r["work"] + "/" + gone, detail, name)
        # before cleanup the temporary video still existed, so its path was still correct
        self.assertIn(r["task_dir"], self.details(r["after_output"])["MPT video"])

    def test_keep_work_deletes_nothing_and_says_so(self):
        r = self.run_steps(keep_work=True)
        self.assertTrue(r["task_dir_exists"])
        self.assertIn("narration.wav", r["work_left"])
        self.assertEqual(r["after_cleanup"]["cleanup"], {"performed": False, "reason": "--keep-work", "removed": []})
        self.assertTrue(r["after_cleanup"]["narration"]["path"].endswith("narration.wav"))


class TextRewriteTests(unittest.TestCase):
    def test_replace_in_strings_works_inside_sentences_and_prefers_the_longest_key(self):
        mapping = {"/w/a.mp4": "/review/final.mp4", "/w": "/other"}
        out = mv.replace_in_strings([{"detail": "ok -> /w/a.mp4 and /w/b", "n": 3}, "/w/a.mp4"], mapping)
        self.assertEqual(out, [{"detail": "ok -> /review/final.mp4 and /other/b", "n": 3}, "/review/final.mp4"])

    def test_mark_deleted_shortens_paths_inside_sentences(self):
        deleted = ["/m/tasks/T1", "/w/id/lines"]
        out = mv.mark_deleted_in_strings(
            ["/m/tasks/T1/final-1.mp4 ok, see /w/id/lines; keep /w/id/timings.json (and /m/tasks/T1)"], deleted)
        self.assertEqual(out, ["final-1.mp4 (deleted after the run) ok, see lines (deleted after the run); "
                               "keep /w/id/timings.json (and T1 (deleted after the run))"])

    def test_mark_deleted_leaves_similar_looking_text_alone(self):
        self.assertEqual(mv.mark_deleted_in_strings("narration.wav is gone", ["/w/id/narration.wav"]), "narration.wav is gone")


class SubtitleDifferenceWarningTests(unittest.TestCase):
    def test_no_differences_no_warning(self):
        self.assertIsNone(mv.subtitle_difference_warning([]))

    def test_every_differing_word_is_listed(self):
        diffs = ['script word(s) missing in the subtitle: "an"', 'script "zwängt" -> subtitle "zwingt"']
        text = mv.subtitle_difference_warning(diffs)
        self.assertIn("2 caption spot(s)", text)
        self.assertIn("zwingt", text)
        self.assertIn('missing in the subtitle: "an"', text)
        self.assertIn("final.mp4", text)

    def test_a_passing_comparison_with_a_misspelling_produces_the_warning(self):
        script = ["Der Druck zwängt das Gas durch die Kühlschlange und das hier ist ein langer Satz"]
        cues = [{"index": 1, "start": 0, "end": 1, "text": script[0].replace("zwängt", "zwingt")}]
        ok, wer, _msg, diffs = mv.check_srt_accuracy(cues, script)
        self.assertTrue(ok)  # below the 10 percent limit, so the gate lets it through ...
        self.assertIn("zwingt", mv.subtitle_difference_warning(diffs))  # ... but the user is told


class UnexpectedErrorTests(unittest.TestCase):
    def test_unexpected_exception_prints_plain_message_and_writes_failed_report(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            script_path = tmp / "script.json"
            script_path.write_text(json.dumps(good_script()), encoding="utf-8")
            err = io.StringIO()
            with mock.patch.object(mv, "WORK_ROOT", tmp / "work"), \
                    mock.patch.object(mv, "step_preflight", side_effect=KeyError("surprise")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = mv.main([str(script_path)])
            self.assertEqual(code, 1)
            text = err.getvalue()
            self.assertIn("FAILED (unexpected)", text)
            self.assertIn("KeyError", text)
            self.assertNotIn("Traceback", text)
            failed = tmp / "work" / "2026-10-14-en-fridge" / "failed-report.json"
            self.assertTrue(failed.is_file())
            data = json.loads(failed.read_text(encoding="utf-8"))
            self.assertFalse(data["ok"])
            self.assertIn("KeyError", data["error"])
            self.assertIn("Traceback", data["traceback"])

    def test_gate_errors_still_use_the_plain_failed_headline(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            script_path = tmp / "script.json"
            script_path.write_text(json.dumps(good_script()), encoding="utf-8")
            err = io.StringIO()
            with mock.patch.object(mv, "WORK_ROOT", tmp / "work"), \
                    mock.patch.object(mv, "step_preflight", side_effect=mv.GateError("VoiceStudio is off")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = mv.main([str(script_path)])
            self.assertEqual(code, 1)
            self.assertIn("FAILED: VoiceStudio is off", err.getvalue())
            self.assertTrue((tmp / "work" / "2026-10-14-en-fridge" / "failed-report.json").is_file())


class MainFailsLoudlyTests(unittest.TestCase):
    """These never reach the network: validation fails first."""

    def run_main(self, path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mv.main([str(path)])
        return code, err.getvalue()

    def test_missing_file(self):
        code, err = self.run_main("/nonexistent/script.json")
        self.assertEqual(code, 1)
        self.assertIn("FAILED", err)

    def test_invalid_script_lists_every_problem(self):
        bad = copy.deepcopy(good_script())
        bad["sources"] = []
        bad["video_terms"] = ["only", "three", "terms"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            code, err = self.run_main(path)
        self.assertEqual(code, 1)
        self.assertIn("sources", err)
        self.assertIn("video_terms", err)

    def test_not_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "script.json"
            path.write_text("{oops", encoding="utf-8")
            code, err = self.run_main(path)
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)


class SpellingTolerantLineCheckTests(unittest.TestCase):
    """Real cases from the 2026-10-14 noise-cancelling runs: spelling variants must pass, a mishearing must fail."""

    def passes(self, ref, heard):
        wer, cer = mv.word_error_rate(ref, heard), mv.char_error_rate(ref, heard)
        return mv.line_error_score(wer, cer, mv.wer_threshold(ref)) <= 1.0

    def test_hyphen_and_compound_variants_pass(self):
        self.assertTrue(self.passes("The whole loop runs nonstop, adjusting faster than you could ever notice.",
                                    "The whole loop runs non-stop, adjusting faster than you could ever notice."))
        self.assertTrue(self.passes("On the outside of each ear cup, a tiny microphone listens to the world around you.",
                                    "On the outside of each earcup, a tiny microphone listens to the world around you."))
        self.assertTrue(self.passes("Und der Transparenzmodus? Gleiche Mikrofone, aber statt den Schall umzudrehen, leiten sie ihn einfach weiter.",
                                    "Und der Transparenz-Modus? Gleiche Mikrofone aber statt den Schall umzudrehen, leiten sie ihn einfach weiter."))

    def test_char_error_rate_ignores_spaces_and_dashes(self):
        self.assertEqual(mv.char_error_rate("Zugrattern", "zu grattern"), 0.0)
        self.assertEqual(mv.char_error_rate("", ""), 0.0)
        self.assertEqual(mv.char_error_rate("", "x"), 1.0)

    def test_real_mishearing_still_fails(self):
        self.assertFalse(self.passes("Kopfhörer mit Noise Cancelling bekämpfen Lärm mit noch mehr Schall.",
                                     "Kopfhörer mit Neuskänzeling bekämpfen Lärm mit noch mehr Schall."))


class BrollValidationTests(unittest.TestCase):
    """script.json lines[].broll: optional English search phrase for the stock footage."""

    def check(self, value):
        s = good_script()
        s["lines"][1]["broll"] = value
        return mv.validate_script(s)

    def test_good_phrases_pass(self):
        for phrase in ("refrigerator interior", "ice cubes", "close-up", "ab", "x" * 40, "Copper Pipes"):
            errors, warnings = self.check(phrase)
            self.assertEqual((errors, warnings), ([], []), phrase)

    def test_broll_is_optional(self):
        self.assertEqual(mv.validate_script(good_script()), ([], []))
        self.assertEqual(self.check(None)[0], [])  # null = not set

    def test_bad_phrases_are_errors_naming_the_line(self):
        for bad in ("a", "", "   ", "x" * 41, "kühlschrank", "fridge 2", "fridge!", "fridge\n", 5, ["ice"], {"a": 1}, True):
            errors, _ = self.check(bad)
            self.assertEqual(len(errors), 1, repr(bad))
            self.assertIn("lines[1].broll", errors[0])

    def test_more_than_four_words_is_only_a_warning(self):
        errors, warnings = self.check("old white fridge door open")
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("lines[1].broll", warnings[0])


class FootageModeTests(unittest.TestCase):
    def test_auto_uses_own_footage_when_a_pixabay_key_is_set(self):
        self.assertEqual(mv.resolve_footage_mode("auto", False, True, "pixabay"), ("own", None))
        self.assertEqual(mv.resolve_footage_mode("auto", False, True, "pexels"), ("own", None))  # a Pexels key does not change that (yet)

    def test_auto_without_a_pixabay_key_keeps_the_old_behaviour(self):
        self.assertEqual(mv.resolve_footage_mode("auto", False, False, "pexels"), ("mpt", "pexels"))

    def test_mpt_is_the_old_behaviour_even_with_a_pixabay_key(self):
        self.assertEqual(mv.resolve_footage_mode("mpt", False, True, "pixabay"), ("mpt", "pixabay"))

    def test_local_materials_win_over_auto_and_mpt(self):
        self.assertEqual(mv.resolve_footage_mode("auto", True, True, "pixabay"), ("local", None))
        self.assertEqual(mv.resolve_footage_mode("mpt", True, True, "pixabay"), ("local", None))

    def test_own_with_local_materials_is_refused(self):
        with self.assertRaises(mv.GateError) as ctx:
            mv.resolve_footage_mode("own", True, True, "pixabay")
        self.assertIn("--local-materials", str(ctx.exception))

    def test_own_without_a_pixabay_key_says_what_to_do(self):
        with self.assertRaises(mv.GateError) as ctx:
            mv.resolve_footage_mode("own", False, False, "pexels")
        self.assertIn("pixabay_api_keys", str(ctx.exception))

    def test_no_key_at_all_is_the_old_plain_message(self):
        for requested in ("auto", "mpt"):
            with self.assertRaises(mv.GateError) as ctx:
                mv.resolve_footage_mode(requested, False, False, None)
            self.assertIn("No stock-footage API key", str(ctx.exception))

    def test_footage_flag(self):
        self.assertEqual(mv.parse_args(["s.json"]).footage, "auto")
        for mode in ("auto", "own", "mpt"):
            self.assertEqual(mv.parse_args(["s.json", "--footage", mode]).footage, mode)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mv.parse_args(["s.json", "--footage", "pexels"])

    def test_mpt_command_keeps_our_order_for_own_footage(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/w/broll.mp4")], fixed_order_seconds=72)
        pairs = dict(zip(cmd[4:], cmd[5:]))
        self.assertEqual(pairs["--video-source"], "local")
        self.assertEqual(pairs["--video-materials"], "/w/broll.mp4")
        self.assertEqual(pairs["--video-concat-mode"], "sequential")
        self.assertEqual(pairs["--video-transition-mode"], "none")
        self.assertEqual(pairs["--video-clip-duration"], "72")  # longer than the file, or MPT would keep only its first 5 s
        self.assertEqual(pairs["--video-clip-speed"], "1.0")

    def test_other_commands_do_not_get_the_fixed_order_flags(self):
        for cmd in (mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", [Path("/m/a.mp4")]),
                    mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", source="pixabay")):
            for flag in ("--video-concat-mode", "--video-transition-mode", "--video-clip-duration", "--video-clip-speed"):
                self.assertNotIn(flag, cmd)

    def test_fixed_order_flags_are_ignored_without_local_files(self):
        cmd = mv.build_mpt_command("uv", "x", ["t"], Path("/n.wav"), "id", source="pexels", fixed_order_seconds=72)
        self.assertNotIn("--video-clip-duration", cmd)


class OwnFootageStepTests(unittest.TestCase):
    KEY = "SECRETKEY-1234567890-abcdef"

    def make_ctx(self):
        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        ctx.script = good_script()
        ctx.work = Path("/nonexistent/work")
        return ctx

    def fake_result(self):
        return {
            "path": Path("/nonexistent/work/broll.mp4"), "segments": [{"start": 0.0, "end": 4.0, "phrase": "refrigerator", "line_indexes": [0]}],
            "credits": [{"provider": "pixabay", "id": 5, "user": "Ann", "page_url": "https://pixabay.com/videos/a-5/"}],
            "credit_lines": ["Video by Ann on Pixabay: https://pixabay.com/videos/a-5/"],
            "report": {"provider": "pixabay", "clips_used": 1, "downloads": 1, "clip_cache_hits": 0, "search_requests": 2, "search_cache_hits": 1,
                       "broll_seconds": 4.0, "credits": [],
                       "segments": [{"start": 0.0, "end": 4.0, "phrase": "refrigerator", "fallback": False, "searched_phrase": "refrigerator", "clip_id": 5}]},
        }

    def run_step(self, ctx, **patches):
        with mock.patch.object(mv, "find_tool", side_effect=lambda name: f"/bin/{name}"), \
                mock.patch.object(mv.footage, "load_pixabay_key", return_value=patches.get("key", self.KEY)), \
                mock.patch.object(mv.footage, "build_broll", **({"side_effect": patches["error"]} if "error" in patches else {"return_value": self.fake_result()})), \
                contextlib.redirect_stdout(io.StringIO()):
            return mv.step_own_footage(ctx, [{"index": 0, "start": 0.0, "end": 4.0}], 4.0)

    def test_report_gets_a_footage_section_without_the_key(self):
        ctx = self.make_ctx()
        result = self.run_step(ctx)
        self.assertEqual(result["credit_lines"], ["Video by Ann on Pixabay: https://pixabay.com/videos/a-5/"])
        self.assertEqual(ctx.report["footage"]["mode"], "own")
        self.assertEqual(ctx.report["footage"]["clips_used"], 1)
        self.assertNotIn(self.KEY, json.dumps(ctx.report))
        self.assertNotIn(self.KEY, json.dumps(ctx.checks))

    def test_a_fallback_search_is_a_warning(self):
        ctx = self.make_ctx()
        result = self.fake_result()
        result["report"]["segments"][0].update(fallback=True, searched_phrase="kitchen")
        with mock.patch.object(mv, "find_tool", side_effect=lambda name: f"/bin/{name}"), \
                mock.patch.object(mv.footage, "load_pixabay_key", return_value=self.KEY), \
                mock.patch.object(mv.footage, "build_broll", return_value=result), \
                contextlib.redirect_stdout(io.StringIO()):
            mv.step_own_footage(ctx, [], 4.0)
        self.assertTrue(any("refrigerator" in w and "kitchen" in w for w in ctx.warnings))

    def test_an_unrelated_stand_in_is_named_as_such_in_the_warning(self):
        for related, expect in ((True, False), (False, True)):
            ctx = self.make_ctx()
            result = self.fake_result()
            result["report"]["segments"][0].update(fallback=True, searched_phrase="kitchen", fallback_related=related)
            with mock.patch.object(mv, "find_tool", side_effect=lambda name: f"/bin/{name}"), \
                    mock.patch.object(mv.footage, "load_pixabay_key", return_value=self.KEY), \
                    mock.patch.object(mv.footage, "build_broll", return_value=result), \
                    contextlib.redirect_stdout(io.StringIO()):
                mv.step_own_footage(ctx, [], 4.0)
            self.assertEqual(any("NOT about the phrase" in w for w in ctx.warnings), expect)

    def test_footage_errors_become_plain_gate_errors(self):
        ctx = self.make_ctx()
        with self.assertRaises(mv.GateError) as raised:
            self.run_step(ctx, error=mv.footage.FootageError("No usable stock clip was found for line 3"))
        self.assertIn("Stock footage:", str(raised.exception))
        self.assertIn("line 3", str(raised.exception))

    def test_missing_key_is_a_plain_gate_error(self):
        with self.assertRaises(mv.GateError) as raised:
            self.run_step(self.make_ctx(), key=None)
        self.assertIn("pixabay_api_keys", str(raised.exception))

    def test_credits_are_exactly_the_clips_used(self):
        ctx = self.make_ctx()
        mpt = {"broll": self.fake_result()}
        with contextlib.redirect_stdout(io.StringIO()):
            lines = mv.step_credits(ctx, mpt, local=False)
        self.assertEqual(lines, ["Video by Ann on Pixabay: https://pixabay.com/videos/a-5/"])
        self.assertEqual(ctx.report["credits"]["lines"], lines)
        self.assertFalse(any("credited all" in n for n in ctx.report["credits"]["notes"]))
        caption = mv.build_caption(good_script(), lines)
        self.assertIn("Video by Ann on Pixabay: https://pixabay.com/videos/a-5/", caption)

    def test_order_check_passes_when_mpt_kept_our_pictures(self):
        ctx = self.make_ctx()
        ctx.report["footage"] = {"mode": "own"}
        frames = [{"seconds": 2.0, "diff": 3.1, "same": True}, {"seconds": 6.0, "diff": 5.2, "same": True}]
        with mock.patch.object(mv, "find_tool", return_value="/bin/ffmpeg"), mock.patch.object(mv.footage, "check_order", return_value=frames), \
                contextlib.redirect_stdout(io.StringIO()):
            mv.check_footage_order(ctx, Path("/w/mpt.mp4"), self.fake_result())
        self.assertEqual(ctx.report["footage"]["order_check"]["frames"], frames)
        self.assertTrue(ctx.checks[-1]["ok"])

    def test_order_check_fails_loudly_when_mpt_shuffled_or_looped(self):
        ctx = self.make_ctx()
        ctx.report["footage"] = {"mode": "own"}
        frames = [{"seconds": 2.0, "diff": 3.1, "same": True}, {"seconds": 6.0, "diff": 88.0, "same": False}]
        with mock.patch.object(mv, "find_tool", return_value="/bin/ffmpeg"), mock.patch.object(mv.footage, "check_order", return_value=frames), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(mv.GateError) as raised:
                mv.check_footage_order(ctx, Path("/w/mpt.mp4"), self.fake_result())
        self.assertIn("footage order kept failed", str(raised.exception))
        self.assertIn("6 s", str(raised.exception))

    def test_failure_output_never_shows_an_api_key_in_a_url(self):
        ctx = self.make_ctx()
        ctx.script = {}  # no id yet: nothing is written
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mv.fail(ctx, "FAILED", f"Pixabay broke: https://pixabay.com/api/videos/?key={self.KEY}&q=x")
        self.assertNotIn(self.KEY, err.getvalue())
        self.assertIn("key=***", err.getvalue())

    def test_failed_report_never_holds_an_api_key_in_a_url(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ctx = self.make_ctx()
            ctx.work = tmp
            with mock.patch.object(mv, "WORK_ROOT", tmp), contextlib.redirect_stderr(io.StringIO()):
                mv.fail(ctx, "FAILED", f"Pixabay broke: ?key={self.KEY}&q=x", extra={"traceback": f"Traceback ... ?key={self.KEY}&q=x"})
            self.assertNotIn(self.KEY, (tmp / "failed-report.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
