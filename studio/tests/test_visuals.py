"""Tests for studio/visuals.py: validation, panel planning and ffmpeg/remotion command builders.

Only pure functions are tested here (no Remotion, no ffmpeg), so the suite is fast.
The real render path is covered by `python3 studio/visuals.py --demo`.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import visuals  # noqa: E402


def flow(title="How it works", steps=None):
    return {"type": "flow", "title": title, "steps": steps or ["One", "Two", "Three"]}


def stat(value="-18 °C", label="Freezer temperature"):
    return {"type": "stat", "value": value, "label": label}


def compare(**over):
    v = {
        "type": "compare",
        "title": "Myth or fact?",
        "left": {"heading": "Myth", "text": "Cold flows out"},
        "right": {"heading": "Fact", "text": "Heat flows in"},
    }
    v.update(over)
    return v


def script_with(*visuals_, language="en"):
    return {"language": language, "lines": [{"text": f"line {i}", "visual": v} for i, v in enumerate(visuals_)]}


def timings_for(*spans):
    return [{"index": i, "start": s, "end": e, "text": f"line {i}"} for i, (s, e) in enumerate(spans)]


class ValidateVisualTests(unittest.TestCase):
    def test_none_is_valid(self):
        self.assertEqual(visuals.validate_visual(None, 0), [])

    def test_valid_examples(self):
        for v in (flow(), stat(), compare()):
            self.assertEqual(visuals.validate_visual(v, 3), [], v)

    def test_limits_are_inclusive(self):
        ok = [
            flow(title="x" * 32, steps=["y" * 22] * 5),
            stat(value="1" * 10, label="z" * 40),
            compare(
                title="t" * 32,
                left={"heading": "h" * 12, "text": "a" * 48},
                right={"heading": "h" * 12, "text": "b" * 48},
            ),
        ]
        for v in ok:
            self.assertEqual(visuals.validate_visual(v, 0), [], v["type"])

    def test_umlauts_count_as_one_character(self):
        v = flow(steps=["ä" * 22, "ö" * 22])
        self.assertEqual(visuals.validate_visual(v, 0), [])
        v = flow(steps=["ä" * 23, "ö"])
        errs = visuals.validate_visual(v, 0)
        self.assertEqual(len(errs), 1)
        self.assertIn("lines[0].visual.steps[0]", errs[0])

    def test_error_names_line_and_field(self):
        errs = visuals.validate_visual(flow(title="x" * 33), 7)
        self.assertEqual(len(errs), 1)
        self.assertIn("lines[7].visual.title", errs[0])
        self.assertIn("33", errs[0])
        self.assertIn("32", errs[0])

    def test_flow_step_count(self):
        for steps in (["only one"], ["a", "b", "c", "d", "e", "f"]):
            errs = visuals.validate_visual(flow(steps=steps), 2)
            self.assertTrue(any("lines[2].visual.steps" in e and "2-5" in e for e in errs), steps)

    def test_flow_empty_steps_rejected(self):
        # an empty list is falsy, so build the dict by hand instead of through flow()
        errs = visuals.validate_visual({"type": "flow", "title": "t", "steps": []}, 2)
        self.assertTrue(any("lines[2].visual.steps" in e and "2-5" in e for e in errs))

    def test_flow_steps_must_be_list_of_strings(self):
        self.assertTrue(visuals.validate_visual({"type": "flow", "title": "t", "steps": "abc"}, 0))
        errs = visuals.validate_visual(flow(steps=["ok", 5]), 1)
        self.assertTrue(any("lines[1].visual.steps[1]" in e for e in errs))

    def test_stat_fields(self):
        errs = visuals.validate_visual(stat(value="12345678901", label="y" * 41), 4)
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("lines[4].visual.value" in e for e in errs))
        self.assertTrue(any("lines[4].visual.label" in e for e in errs))

    def test_compare_nested_fields(self):
        v = compare(
            left={"heading": "h" * 13, "text": "ok"},
            right={"heading": "ok", "text": "t" * 49},
        )
        errs = visuals.validate_visual(v, 5)
        self.assertTrue(any("lines[5].visual.left.heading" in e for e in errs))
        self.assertTrue(any("lines[5].visual.right.text" in e for e in errs))

    def test_compare_missing_side(self):
        v = compare()
        del v["right"]
        errs = visuals.validate_visual(v, 1)
        self.assertEqual(len(errs), 1)
        self.assertIn("lines[1].visual.right", errs[0])

    def test_empty_and_blank_strings_rejected(self):
        errs = visuals.validate_visual(stat(value="   ", label=""), 0)
        self.assertEqual(len(errs), 2)
        self.assertTrue(all("must not be empty" in e for e in errs))

    def test_unknown_type_and_wrong_shape(self):
        errs = visuals.validate_visual({"type": "pie"}, 6)
        self.assertIn("lines[6].visual.type", errs[0])
        errs = visuals.validate_visual("flow", 6)
        self.assertIn("lines[6].visual", errs[0])

    def test_validate_script_collects_all_lines(self):
        script = script_with(flow(title="x" * 40), None, stat(value=""))
        errs = visuals.validate_script_visuals(script)
        self.assertTrue(any("lines[0]" in e for e in errs))
        self.assertTrue(any("lines[2]" in e for e in errs))
        self.assertFalse(any("lines[1]" in e for e in errs))


class PlanPanelsTests(unittest.TestCase):
    def test_skips_lines_without_visual(self):
        script = script_with(None, stat(), None)
        plan = visuals.plan_panels(script, timings_for((0, 3), (3, 6), (6, 9)))
        self.assertEqual([p["index"] for p in plan], [1])

    def test_seconds_formula(self):
        # long line: end - start + 0.3 ; short line: at least 2.0
        script = script_with(stat(), None, stat())
        plan = visuals.plan_panels(script, timings_for((1.0, 5.0), (5.0, 6.0), (20.0, 20.5)))
        self.assertAlmostEqual(plan[0]["seconds"], 4.3, places=1)
        self.assertEqual(plan[0]["start"], 1.0)
        self.assertAlmostEqual(plan[1]["seconds"], 2.0, places=2)

    def test_seconds_rounded_to_whole_frames(self):
        plan = visuals.plan_panels(script_with(stat()), timings_for((0, 3.21)))
        frames = plan[0]["seconds"] * visuals.PANEL_FPS
        self.assertAlmostEqual(frames, round(frames), places=6)
        self.assertAlmostEqual(plan[0]["end"], plan[0]["start"] + plan[0]["seconds"])

    def test_capped_by_next_panel_start(self):
        script = script_with(flow(), stat(), compare())
        plan = visuals.plan_panels(script, timings_for((0.5, 4.5), (4.5, 8.0), (8.0, 12.0)))
        self.assertAlmostEqual(plan[0]["end"], 4.5, places=3)
        self.assertAlmostEqual(plan[1]["end"], 8.0, places=3)
        # last one is not capped without a video duration: 4.0 + 0.3
        self.assertAlmostEqual(plan[2]["seconds"], 4.3, places=1)

    def test_capped_by_video_duration(self):
        script = script_with(flow(), stat(), compare())
        plan = visuals.plan_panels(script, timings_for((0.5, 4.5), (4.5, 8.0), (8.0, 12.0)), video_duration=12.0)
        self.assertAlmostEqual(plan[2]["end"], 12.0, places=3)

    def test_never_shrinks_a_kept_panel_below_one_second(self):
        # next panel starts exactly 1.0 s later: the first panel is kept, at exactly 1 s
        script = script_with(stat(), stat())
        plan = visuals.plan_panels(script, timings_for((0.0, 0.4), (1.0, 3.0)))
        self.assertEqual([p["index"] for p in plan], [0, 1])
        self.assertAlmostEqual(plan[0]["seconds"], 1.0, places=3)
        self.assertAlmostEqual(plan[0]["end"], 1.0, places=3)

    def test_panels_closer_than_one_second_do_not_stack(self):
        # lines 0.8 s apart, both with a visual: the earlier card would be up for < 1 s,
        # so it is dropped instead of being drawn on top of the later one
        script = script_with(stat(), stat())
        plan = visuals.plan_panels(script, timings_for((0.0, 0.6), (0.8, 3.0)))
        self.assertEqual([p["index"] for p in plan], [1])
        self.assertEqual(plan[0]["name"], "panel-01")

    def test_chain_of_close_panels_keeps_only_the_last(self):
        script = script_with(stat(), stat(), stat())
        plan = visuals.plan_panels(script, timings_for((0.0, 0.3), (0.4, 0.7), (0.9, 3.0)))
        self.assertEqual([p["index"] for p in plan], [2])

    def test_close_pair_does_not_hurt_a_distant_earlier_panel(self):
        # panel 0 is far from the close pair (1, 2); once 1 is dropped, 0 ends at 2's start
        script = script_with(stat(), stat(), stat())
        plan = visuals.plan_panels(script, timings_for((0.0, 5.5), (5.2, 5.5), (5.6, 9.0)))
        self.assertEqual([p["index"] for p in plan], [0, 2])
        self.assertAlmostEqual(plan[0]["end"], 5.6, places=2)

    def test_planned_panels_never_overlap_in_time(self):
        spans = [(0.0, 0.5), (0.7, 1.5), (3.0, 3.4), (3.9, 7.0), (7.04, 9.3), (9.5, 10.2), (11.0, 14.0)]
        script = script_with(*[stat() for _ in spans])
        plan = visuals.plan_panels(script, timings_for(*spans), video_duration=14.0)
        self.assertGreaterEqual(len(plan), 2)
        for a, b in zip(plan, plan[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9, (a["index"], b["index"]))
            self.assertGreaterEqual(a["seconds"], visuals.MIN_CAPPED_SECONDS - 1e-9)

    def test_names_are_numbered_in_time_order(self):
        script = script_with(stat(), stat(), stat())
        plan = visuals.plan_panels(script, timings_for((0, 3), (3, 6), (6, 9)))
        self.assertEqual([p["name"] for p in plan], ["panel-01", "panel-02", "panel-03"])

    def test_timings_matched_by_index_key(self):
        script = script_with(None, stat())
        timings = [{"index": 1, "start": 2.0, "end": 5.0}, {"index": 0, "start": 0.0, "end": 2.0}]
        plan = visuals.plan_panels(script, timings)
        self.assertEqual(plan[0]["start"], 2.0)

    def test_missing_timing_names_the_line(self):
        script = script_with(stat(), stat())
        with self.assertRaises(visuals.VisualError) as ctx:
            visuals.plan_panels(script, timings_for((0, 3)))
        self.assertIn("lines[1]", str(ctx.exception))

    def test_end_before_start_rejected(self):
        with self.assertRaises(visuals.VisualError) as ctx:
            visuals.plan_panels(script_with(stat()), timings_for((5, 3)))
        self.assertIn("lines[0]", str(ctx.exception))

    def test_invalid_visual_rejected_with_line_and_field(self):
        script = script_with(stat(), flow(steps=["only"]))
        with self.assertRaises(visuals.VisualError) as ctx:
            visuals.plan_panels(script, timings_for((0, 3), (3, 6)))
        self.assertIn("lines[1].visual.steps", str(ctx.exception))


class FilterBuilderTests(unittest.TestCase):
    def panels(self):
        return [{"start": 0.5, "end": 4.5}, {"start": 4.5, "end": 8.0}, {"start": 8.0, "end": 12.0}]

    def test_requires_panels(self):
        with self.assertRaises(ValueError):
            visuals.build_filter_complex([])

    def test_single_panel_exact(self):
        graph = visuals.build_filter_complex([{"start": 1.5, "end": 5.0}])
        self.assertEqual(
            graph,
            "[1:v]setpts=PTS-STARTPTS+1.5/TB[p1];"
            "[0:v][p1]overlay=x=0:y=160:format=auto:eof_action=pass:enable='between(t,1.5,5)'[v1];"
            "[v1]format=yuv420p[vout]",
        )

    def test_three_panels_chain_in_order(self):
        graph = visuals.build_filter_complex(self.panels())
        self.assertEqual(graph.count("overlay="), 3)
        self.assertIn("[0:v][p1]overlay", graph)
        self.assertIn("[v1][p2]overlay", graph)
        self.assertIn("[v2][p3]overlay", graph)
        self.assertTrue(graph.endswith("[v3]format=yuv420p[vout]"))
        for start, end in ((0.5, 4.5), (4.5, 8), (8, 12)):
            self.assertIn(f"enable='between(t,{start:g},{end:g})'", graph)
        self.assertIn("setpts=PTS-STARTPTS+8/TB", graph)

    def test_position_is_x0_y160_and_panels_stay_above_1250(self):
        graph = visuals.build_filter_complex(self.panels())
        self.assertEqual(graph.count("x=0:y=160"), 3)
        self.assertLessEqual(visuals.PANEL_Y + 1080, 1250)

    def test_numbers_have_no_float_noise(self):
        graph = visuals.build_filter_complex([{"start": 0.1 + 0.2, "end": 4.499999999}])
        self.assertIn("between(t,0.3,4.5)", graph)
        self.assertNotIn("e-", graph)


class CommandBuilderTests(unittest.TestCase):
    def test_ffmpeg_command(self):
        panels = [{"start": 0.5, "end": 4.5}, {"start": 4.5, "end": 8.0}]
        cmd = visuals.build_ffmpeg_command("base.mp4", ["a.mov", "b.mov"], panels, "out.mp4", duration=12.0, ffmpeg="ffmpeg")
        self.assertEqual(cmd[0], "ffmpeg")
        # inputs in order: base first, then panels
        inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
        self.assertEqual(inputs, ["base.mp4", "a.mov", "b.mov"])
        joined = " ".join(cmd)
        for needle in ("-c:v libx264", "-crf 18", "-preset medium", "-pix_fmt yuv420p", "-c:a copy", "-movflags +faststart", "-map [vout]", "-map 0:a?", "-t 12"):
            self.assertIn(needle, joined)
        self.assertEqual(cmd[-1], "out.mp4")
        self.assertEqual(cmd[cmd.index("-filter_complex") + 1], visuals.build_filter_complex(panels))

    def test_ffmpeg_command_without_duration_has_no_t(self):
        cmd = visuals.build_ffmpeg_command("b.mp4", ["a.mov"], [{"start": 0, "end": 2}], "o.mp4", ffmpeg="ffmpeg")
        self.assertNotIn("-t", cmd)

    def test_ffmpeg_command_length_mismatch(self):
        with self.assertRaises(ValueError):
            visuals.build_ffmpeg_command("b.mp4", ["a.mov", "c.mov"], [{"start": 0, "end": 2}], "o.mp4")

    def test_remotion_command(self):
        cmd = visuals.build_remotion_command("npx", "/w/panel-01.json", "/w/panel-01.mov")
        self.assertEqual(cmd[:6], ["npx", "remotion", "render", "src/index.ts", "ShortsPanel", "/w/panel-01.mov"])
        for flag in ("--props=/w/panel-01.json", "--codec=prores", "--prores-profile=4444", "--pixel-format=yuva444p10le", "--image-format=png"):
            self.assertIn(flag, cmd)


def touch(path):
    with open(path, "wb") as f:
        f.write(b"x")


def words_for(*items):
    return [{"text": t, "start": s, "end": e} for t, s, e in items]


def caption_args(**over):
    args = {"words": words_for(("Hallo", 0.0, 0.5), ("Welt.", 0.5, 1.0)), "font_size": 69, "stroke_width": 6, "box_height": 141}
    args.update(over)
    return args


class CaptionFilterTests(unittest.TestCase):
    def test_caption_only(self):
        graph = visuals.build_filter_complex([], caption=True)
        self.assertEqual(
            graph,
            "[1:v]setpts=PTS-STARTPTS[cap];"
            "[0:v][cap]overlay=x=0:y=1300:format=auto:eof_action=pass[vcap];"
            "[vcap]format=yuv420p[vout]",
        )

    def test_panels_first_then_the_caption_track_on_top_as_the_last_input(self):
        graph = visuals.build_filter_complex([{"start": 0.5, "end": 4.5}, {"start": 4.5, "end": 8.0}], caption=True)
        self.assertEqual(
            graph,
            "[1:v]setpts=PTS-STARTPTS+0.5/TB[p1];"
            "[0:v][p1]overlay=x=0:y=160:format=auto:eof_action=pass:enable='between(t,0.5,4.5)'[v1];"
            "[2:v]setpts=PTS-STARTPTS+4.5/TB[p2];"
            "[v1][p2]overlay=x=0:y=160:format=auto:eof_action=pass:enable='between(t,4.5,8)'[v2];"
            "[3:v]setpts=PTS-STARTPTS[cap];"
            "[v2][cap]overlay=x=0:y=1300:format=auto:eof_action=pass[vcap];"
            "[vcap]format=yuv420p[vout]",
        )

    def test_without_the_caption_flag_the_graph_is_what_it_always_was(self):
        panels = [{"start": 1.5, "end": 5.0}]
        self.assertEqual(visuals.build_filter_complex(panels), visuals.build_filter_complex(panels, caption=False))
        self.assertNotIn("cap", visuals.build_filter_complex(panels))

    def test_nothing_to_overlay_is_an_error(self):
        with self.assertRaises(ValueError):
            visuals.build_filter_complex([], caption=False)

    def test_captions_sit_below_the_panels(self):
        self.assertGreater(visuals.CAPTION_Y, visuals.PANEL_Y + 1080)  # no overlap with the diagram area
        self.assertGreater(visuals.CAPTION_Y, 1250)
        self.assertLessEqual(visuals.CAPTION_Y + visuals.CAPTION_H, 1920)

    def test_ffmpeg_command_with_a_caption_track(self):
        panels = [{"start": 0.5, "end": 4.5}]
        cmd = visuals.build_ffmpeg_command("base.mp4", ["a.mov"], panels, "out.mp4", duration=12.0, ffmpeg="ffmpeg", caption_file="cap.mov")
        inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
        self.assertEqual(inputs, ["base.mp4", "a.mov", "cap.mov"])  # base, panels, caption track last
        self.assertEqual(cmd[cmd.index("-filter_complex") + 1], visuals.build_filter_complex(panels, caption=True))
        joined = " ".join(cmd)
        for needle in ("-c:v libx264", "-crf 18", "-map [vout]", "-map 0:a?", "-c:a copy", "-t 12"):
            self.assertIn(needle, joined)
        self.assertEqual(cmd.count("-filter_complex"), 1)  # ONE pass: the video is encoded once
        self.assertEqual(cmd[-1], "out.mp4")

    def test_ffmpeg_command_with_only_a_caption_track(self):
        cmd = visuals.build_ffmpeg_command("base.mp4", [], [], "out.mp4", ffmpeg="ffmpeg", caption_file="cap.mov")
        inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
        self.assertEqual(inputs, ["base.mp4", "cap.mov"])
        self.assertIn("[1:v]setpts=PTS-STARTPTS[cap]", cmd[cmd.index("-filter_complex") + 1])

    def test_ffmpeg_command_without_a_caption_track_is_unchanged(self):
        panels = [{"start": 0.5, "end": 4.5}]
        cmd = visuals.build_ffmpeg_command("base.mp4", ["a.mov"], panels, "out.mp4", duration=12.0, ffmpeg="ffmpeg")
        self.assertEqual([cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"], ["base.mp4", "a.mov"])
        self.assertEqual(cmd[cmd.index("-filter_complex") + 1], visuals.build_filter_complex(panels))

    def test_caption_remotion_command(self):
        cmd = visuals.build_caption_remotion_command("npx", "/w/captions.json", "/w/captions.mov")
        self.assertEqual(cmd[:6], ["npx", "remotion", "render", "src/index.ts", "WordCaptions", "/w/captions.mov"])
        for flag in ("--props=/w/captions.json", "--codec=prores", "--prores-profile=4444", "--pixel-format=yuva444p10le", "--image-format=png"):
            self.assertIn(flag, cmd)

    def test_panel_command_is_unchanged(self):
        cmd = visuals.build_remotion_command("npx", "/w/p.json", "/w/p.mov")
        self.assertEqual(cmd[4], "ShortsPanel")


class CaptionPropsTests(unittest.TestCase):
    def test_valid_captions(self):
        self.assertEqual(visuals.validate_captions(caption_args()), [])
        self.assertEqual(visuals.validate_captions(caption_args(text_color="#FFFFFF", stroke_color="#000000")), [])

    def test_the_shape_is_checked(self):
        self.assertTrue(visuals.validate_captions(None))
        self.assertTrue(visuals.validate_captions([]))
        self.assertIn("captions.words", visuals.validate_captions(caption_args(words=[]))[0])
        self.assertIn("captions.words", visuals.validate_captions(caption_args(words="x"))[0])
        self.assertTrue(visuals.validate_captions(caption_args(words=["x"])))
        self.assertTrue(visuals.validate_captions(caption_args(words=[{"text": "  ", "start": 0, "end": 1}])))

    def test_times_are_checked(self):
        self.assertTrue(visuals.validate_captions(caption_args(words=words_for(("a", 0.5, 0.5)))))  # zero length
        self.assertTrue(visuals.validate_captions(caption_args(words=words_for(("a", -0.1, 0.5)))))
        self.assertTrue(visuals.validate_captions(caption_args(words=[{"text": "a", "start": "x", "end": 1}])))
        self.assertTrue(visuals.validate_captions(caption_args(words=[{"text": "a", "start": 0}])))
        overlap = visuals.validate_captions(caption_args(words=words_for(("a", 0.0, 0.6), ("b", 0.5, 1.0))))
        self.assertTrue(any("before the previous word ends" in e for e in overlap))

    def test_sizes_are_checked(self):
        for key in ("font_size", "stroke_width", "box_height"):
            self.assertTrue(visuals.validate_captions(caption_args(**{key: 0})), key)
            self.assertTrue(visuals.validate_captions(caption_args(**{key: "big"})), key)
            self.assertTrue(visuals.validate_captions(caption_args(**{key: True})), key)
        self.assertTrue(visuals.validate_captions(caption_args(box_height=visuals.CAPTION_H + 1)))
        self.assertEqual(visuals.validate_captions(caption_args(box_height=visuals.CAPTION_H)), [])

    def test_props_for_remotion(self):
        props = visuals.build_caption_props(caption_args(words=[{"text": "Hallo", "start": 0.0, "end": 0.5, "timing": "heard"}, {"text": "Welt.", "start": 0.5, "end": 1.0}]))
        self.assertEqual(props["words"], [{"text": "Hallo", "start": 0.0, "end": 0.5}, {"text": "Welt.", "start": 0.5, "end": 1.0}])  # no extra keys
        self.assertEqual((props["fontSize"], props["strokeWidth"], props["boxHeight"]), (69, 6, 141))
        self.assertEqual((props["textColor"], props["strokeColor"]), ("#FFFFFF", "#000000"))
        json.dumps(props, ensure_ascii=False)  # plain data

    def test_the_track_is_as_long_as_the_last_word_plus_a_tail_in_whole_frames(self):
        props = visuals.build_caption_props(caption_args(words=words_for(("a", 0.0, 1.0))))
        self.assertAlmostEqual(props["seconds"], 36 / visuals.CAPTION_FPS)  # 1.0 s + 0.2 s tail = 36 frames
        props = visuals.build_caption_props(caption_args(words=words_for(("a", 0.0, 71.8))))
        self.assertEqual(round(props["seconds"] * visuals.CAPTION_FPS), 2160)  # 72.0 s
        self.assertEqual(props["seconds"] * visuals.CAPTION_FPS, round(props["seconds"] * visuals.CAPTION_FPS))

    def test_colours_can_be_given(self):
        props = visuals.build_caption_props(caption_args(text_color="#FFEE00", stroke_color="#111111"))
        self.assertEqual((props["textColor"], props["strokeColor"]), ("#FFEE00", "#111111"))

    def test_umlauts_survive_json(self):
        props = visuals.build_caption_props(caption_args(words=words_for(("Geräuschunterdrückung,", 0.0, 1.0))))
        self.assertIn("Geräuschunterdrückung,", json.dumps(props, ensure_ascii=False))


class RenderWithCaptionsTests(unittest.TestCase):
    """render_and_overlay with the Remotion/ffmpeg calls replaced by fakes (no rendering)."""

    def run_overlay(self, tmp, script, timings, captions, fail_ffmpeg=False):
        base = os.path.join(tmp, "base.mp4")
        with open(base, "wb") as f:
            f.write(b"not really a video")
        out = os.path.join(tmp, "out.mp4")
        work = os.path.join(tmp, "work")
        calls = []

        def fake_run(cmd, cwd=None, timeout=900, what="command"):
            calls.append({"cmd": list(cmd), "cwd": cwd, "what": what})
            if cmd[0] == "npx":
                with open(cmd[5], "wb") as f:
                    f.write(b"x" * 1000)  # the .mov Remotion would have written
            else:
                if fail_ffmpeg:
                    raise RuntimeError("ffmpeg failed")
                with open(cmd[-1], "wb") as f:
                    f.write(b"final")
            return None

        with mock.patch.object(visuals, "_run", side_effect=fake_run), mock.patch.object(visuals, "assert_has_alpha"), \
                mock.patch.object(visuals, "probe_duration", return_value=12.0), \
                mock.patch.object(visuals, "_find_tool", side_effect=lambda name, preferred=None: name):
            try:
                result = visuals.render_and_overlay(base, script, timings, out, work, captions=captions)
            except RuntimeError:
                result = None
        return result, calls, work, out

    def test_captions_only_are_rendered_and_overlaid_in_one_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, calls, work, out = self.run_overlay(tmp, script_with(None, None), timings_for((0, 2), (2, 4)), caption_args())
            self.assertEqual(result["panels"], 0)
            self.assertEqual(result["captions"]["words"], 2)
            kinds = [("remotion" if c["cmd"][0] == "npx" else "ffmpeg") for c in calls]
            self.assertEqual(kinds, ["remotion", "ffmpeg"])
            self.assertEqual(calls[0]["cmd"][4], "WordCaptions")
            self.assertEqual(calls[0]["cwd"], visuals.REMOTION_DIR)
            ffmpeg = calls[1]["cmd"]
            self.assertEqual([ffmpeg[i + 1] for i, a in enumerate(ffmpeg) if a == "-i"], [os.path.join(tmp, "base.mp4"), os.path.join(work, "captions.mov")])
            self.assertIn("overlay=x=0:y=1300", ffmpeg[ffmpeg.index("-filter_complex") + 1])
            with open(out, "rb") as f:
                self.assertEqual(f.read(), b"final")  # captions are not skipped just because there are no panels

    def test_panels_and_captions_share_one_ffmpeg_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, calls, work, _out = self.run_overlay(tmp, script_with(stat(), None), timings_for((0, 3), (3, 6)), caption_args())
            kinds = [c["cmd"][4] if c["cmd"][0] == "npx" else "ffmpeg" for c in calls]
            self.assertEqual(kinds, ["ShortsPanel", "WordCaptions", "ffmpeg"])
            self.assertEqual(sum(1 for c in calls if c["cmd"][0] != "npx"), 1)  # exactly one ffmpeg run: one re-encode
            ffmpeg = calls[-1]["cmd"]
            inputs = [ffmpeg[i + 1] for i, a in enumerate(ffmpeg) if a == "-i"]
            self.assertEqual([os.path.basename(p) for p in inputs], ["base.mp4", "panel-01.mov", "captions.mov"])
            self.assertEqual((result["panels"], result["captions"]["words"]), (1, 2))

    def test_the_caption_props_file_holds_the_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = {}

            def fake_run(cmd, cwd=None, timeout=900, what="command"):
                if cmd[0] == "npx":
                    if cmd[4] == "WordCaptions":
                        with open(cmd[6].split("=", 1)[1], encoding="utf-8") as f:  # --props=<file>
                            seen["props"] = json.load(f)
                    touch(cmd[5])
                else:
                    touch(cmd[-1])

            base = os.path.join(tmp, "base.mp4")
            touch(base)
            with mock.patch.object(visuals, "_run", side_effect=fake_run), mock.patch.object(visuals, "assert_has_alpha"), \
                    mock.patch.object(visuals, "probe_duration", return_value=5.0), \
                    mock.patch.object(visuals, "_find_tool", side_effect=lambda name, preferred=None: name):
                visuals.render_and_overlay(base, script_with(None), timings_for((0, 2)), os.path.join(tmp, "o.mp4"), os.path.join(tmp, "w"),
                                           captions=caption_args(words=words_for(("Geräusch,", 0.0, 0.5))))
            self.assertEqual(seen["props"]["words"], [{"text": "Geräusch,", "start": 0.0, "end": 0.5}])
            self.assertEqual(seen["props"]["fontSize"], 69)

    def test_the_big_caption_mov_is_deleted_after_a_good_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            _result, _calls, work, _out = self.run_overlay(tmp, script_with(stat()), timings_for((0, 3)), caption_args())
            self.assertEqual(sorted(os.listdir(work)), [])  # no .mov, no props json

    def test_the_mov_is_kept_for_debugging_when_ffmpeg_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _calls, work, _out = self.run_overlay(tmp, script_with(None), timings_for((0, 2)), caption_args(), fail_ffmpeg=True)
            self.assertIsNone(result)
            self.assertIn("captions.mov", os.listdir(work))

    def test_invalid_captions_fail_before_any_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "base.mp4")
            touch(base)
            with self.assertRaises(visuals.VisualError) as ctx:
                visuals.render_and_overlay(base, script_with(None), timings_for((0, 2)), os.path.join(tmp, "o.mp4"), os.path.join(tmp, "w"),
                                           captions=caption_args(words=[]))
            self.assertIn("captions.words", str(ctx.exception))
            self.assertFalse(os.path.exists(os.path.join(tmp, "w")))

    def test_without_captions_and_panels_the_base_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "base.mp4")
            touch(base)
            out = os.path.join(tmp, "o.mp4")
            result = visuals.render_and_overlay(base, script_with(None), timings_for((0, 2)), out, os.path.join(tmp, "w"), captions=None)
            self.assertEqual(result["panels"], 0)
            self.assertNotIn("captions", result)
            self.assertTrue(os.path.exists(out))


class RenderAndOverlayGuardTests(unittest.TestCase):
    """Paths that must work without Remotion or ffmpeg rendering."""

    def make_base(self, tmp):
        base = os.path.join(tmp, "base.mp4")
        with open(base, "wb") as f:
            f.write(b"not really a video")
        return base

    def test_missing_base_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                visuals.render_and_overlay(os.path.join(tmp, "nope.mp4"), script_with(None), [], os.path.join(tmp, "o.mp4"), tmp)

    def test_invalid_visual_fails_before_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.make_base(tmp)
            script = script_with(stat(value="x" * 11))
            with self.assertRaises(visuals.VisualError) as ctx:
                visuals.render_and_overlay(base, script, timings_for((0, 3)), os.path.join(tmp, "o.mp4"), os.path.join(tmp, "work"))
            self.assertIn("lines[0].visual.value", str(ctx.exception))
            self.assertFalse(os.path.exists(os.path.join(tmp, "work")))

    def test_bad_language_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.make_base(tmp)
            with self.assertRaises(visuals.VisualError):
                visuals.render_and_overlay(base, script_with(None, language="fr"), [], os.path.join(tmp, "o.mp4"), tmp)

    def test_no_visuals_copies_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self.make_base(tmp)
            out = os.path.join(tmp, "sub", "out.mp4")
            result = visuals.render_and_overlay(base, script_with(None, None), timings_for((0, 2), (2, 4)), out, os.path.join(tmp, "work"))
            self.assertEqual(result, {"panels": 0, "render_seconds": 0.0, "out": out})
            with open(out, "rb") as f:
                self.assertEqual(f.read(), b"not really a video")


if __name__ == "__main__":
    unittest.main()
