"""Tests for studio/visuals.py: validation, panel planning and ffmpeg/remotion command builders.

Only pure functions are tested here (no Remotion, no ffmpeg), so the suite is fast.
The real render path is covered by `python3 studio/visuals.py --demo`.
"""

import os
import sys
import tempfile
import unittest

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
