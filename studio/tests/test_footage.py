"""Unit tests for studio/footage.py. Nothing here touches the network or runs ffmpeg: every network call is
replaced by a fake, and a guard makes any real urlopen call fail the test.

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import hashlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import footage as ft  # noqa: E402

FAKE_KEY = "TESTKEY0123456789abcdefTESTKEY01"  # not a real key


def no_network(*_args, **_kwargs):
    raise AssertionError("a test tried to use the real network")


class NoNetworkTestCase(unittest.TestCase):
    def setUp(self):
        for target in (mock.patch.object(urllib.request, "urlopen", no_network), mock.patch.object(ft, "default_urlopen", no_network)):
            target.start()
            self.addCleanup(target.stop)


# ---- hit builders (shape of a Pixabay /api/videos/ answer) ------------------------------------------------


def renditions(sizes):
    out = {}
    for name, (w, h) in zip(("large", "medium", "small", "tiny"), sizes):
        out[name] = {"url": f"https://cdn.example/{name}.mp4" if w else "", "width": w, "height": h, "size": 1000 if w else 0}
    return out


LANDSCAPE_4K = [(3840, 2160), (2560, 1440), (1920, 1080), (1280, 720)]
LANDSCAPE_HD = [(1920, 1080), (1280, 720), (960, 540), (640, 360)]
PORTRAIT_HD = [(1080, 1920), (720, 1280), (540, 960), (360, 640)]
PORTRAIT_4K = [(2160, 3840), (1080, 1920), (720, 1280), (540, 960)]


def make_hit(clip_id, sizes, tags="refrigerator, kitchen, food", duration=20, user="someone"):
    return {"id": clip_id, "pageURL": f"https://pixabay.com/videos/clip-{clip_id}/", "tags": tags, "duration": duration,
            "user": user, "user_id": 1, "videos": renditions(sizes)}


def seg(start, end, phrase="refrigerator", indexes=(0,)):
    return {"start": start, "end": end, "phrase": phrase, "line_indexes": list(indexes)}


def search_from(table):
    """A fake search(query, page=1) that answers from a dict {query: [hits]} or {(query, page): [hits]} for later pages
    (unknown queries find nothing)."""
    calls = []

    def search(query, page=1):
        calls.append(query if page == 1 else (query, page))
        return table.get(query if page == 1 else (query, page), [])
    search.calls = calls
    return search


def timings_for(durations, gap=0.25):
    out, cursor = [], 0.0
    for i, d in enumerate(durations):
        out.append({"index": i, "start": round(cursor, 3), "end": round(cursor + d, 3), "text": f"line {i}"})
        cursor += d + gap
    return out


def lines_for(phrases):
    return [{"text": f"line {i}", "visual": None, **({"broll": p} if p else {})} for i, p in enumerate(phrases)]


# ---- 1. plan_segments --------------------------------------------------------------------------------------


class PlanSegmentsTests(unittest.TestCase):
    TERMS = ["alpha", "beta", "gamma", "delta"]

    def assert_tiles(self, segments, end):
        self.assertEqual(segments[0]["start"], 0.0)
        for a, b in zip(segments, segments[1:]):
            self.assertEqual(a["end"], b["start"], "gap or overlap between segments")
        self.assertEqual(segments[-1]["end"], round(end, 3))
        for s in segments:
            self.assertGreater(s["end"], s["start"])

    def test_one_segment_per_line_tiling_without_gaps(self):
        timings = timings_for([4.0, 5.0, 3.5])
        segs = ft.plan_segments(timings, lines_for(["a one", "b two", "c three"]), self.TERMS)
        self.assertEqual([s["phrase"] for s in segs], ["a one", "b two", "c three"])
        self.assert_tiles(segs, timings[-1]["end"])
        # the 0.25 s pause belongs to the line before it: a picture changes exactly when the next line starts
        self.assertEqual(segs[0]["end"], timings[1]["start"])
        self.assertEqual([s["line_indexes"] for s in segs], [[0], [1], [2]])

    def test_segments_have_exactly_the_documented_keys(self):
        segs = ft.plan_segments(timings_for([4.0]), lines_for(["a one"]), self.TERMS)
        self.assertEqual(set(segs[0]), {"start", "end", "phrase", "line_indexes"})

    def test_last_segment_ends_at_the_real_narration_length(self):
        timings = timings_for([4.0, 5.0])
        segs = ft.plan_segments(timings, lines_for(["a one", "b two"]), self.TERMS, end=9.4)
        self.assertEqual(segs[-1]["end"], 9.4)
        self.assert_tiles(segs, 9.4)

    def test_neighbouring_lines_with_the_same_phrase_merge(self):
        segs = ft.plan_segments(timings_for([2.0, 2.5, 3.0]), lines_for(["Ice Cubes", "ice  cubes", "kitchen"]), self.TERMS)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["line_indexes"], [0, 1])
        self.assertEqual(segs[0]["start"], 0.0)
        self.assertEqual(segs[0]["end"], segs[1]["start"])

    def test_the_same_phrase_far_apart_is_not_merged(self):
        segs = ft.plan_segments(timings_for([3.0, 3.0, 3.0]), lines_for(["kitchen", "ice", "kitchen"]), self.TERMS)
        self.assertEqual([s["phrase"] for s in segs], ["kitchen", "ice", "kitchen"])

    def test_lines_without_broll_reuse_the_previous_phrase(self):
        segs = ft.plan_segments(timings_for([1.5, 1.5, 1.5]), lines_for(["ice", None, None]), self.TERMS)
        self.assertEqual(len(segs), 1)  # all three lines carry the phrase 'ice' and merge (5.0 s: no cutting)
        self.assertEqual(segs[0]["line_indexes"], [0, 1, 2])

    def test_leading_lines_without_broll_cycle_through_video_terms(self):
        self.assertEqual(ft.resolve_phrases(lines_for([None, None, "ice", None]), self.TERMS), ["alpha", "beta", "ice", "ice"])
        self.assertEqual(ft.resolve_phrases(lines_for([None] * 6), ["x one", "y two"]), ["x one", "y two", "x one", "y two", "x one", "y two"])

    def test_no_broll_and_no_terms_is_a_plain_error(self):
        with self.assertRaises(ft.FootageError):
            ft.resolve_phrases(lines_for([None]), [])

    def test_segment_up_to_six_seconds_is_not_split(self):
        self.assertEqual(len(ft.plan_segments(timings_for([6.0]), lines_for(["ice"]), self.TERMS)), 1)

    def test_long_segment_is_split_into_pieces_of_three_to_five_seconds(self):
        for length in (6.01, 7.5, 10.0, 12.3, 16.0, 31.7):
            segs = ft.plan_segments(timings_for([length]), lines_for(["ice"]), self.TERMS)
            self.assertGreaterEqual(len(segs), 2, length)
            self.assert_tiles(segs, length)
            for s in segs:
                piece = s["end"] - s["start"]
                self.assertTrue(2.99 <= piece <= 5.01, f"{length}: piece of {piece}")
            self.assertTrue(all(s["phrase"] == "ice" and s["line_indexes"] == [0] for s in segs))

    def test_merged_lines_are_split_together_and_keep_their_line_numbers(self):
        segs = ft.plan_segments(timings_for([3.0, 4.0, 5.0]), lines_for(["ice", "ice", "ice"]), self.TERMS)  # one 12.5 s segment
        self.assertEqual(len(segs), 3)
        self.assertEqual([s["line_indexes"] for s in segs], [[0, 1], [1, 2], [2]])  # a piece lists every line it overlaps
        self.assert_tiles(segs, 12.5)

    def test_timings_and_lines_must_match(self):
        with self.assertRaises(ft.FootageError):
            ft.plan_segments(timings_for([3.0, 3.0]), lines_for(["a"]), self.TERMS)
        with self.assertRaises(ft.FootageError):
            ft.plan_segments([], [], self.TERMS)

    def test_real_fridge_like_timings_tile_exactly(self):
        durations = [4.86, 4.04, 4.52, 6.11, 4.28, 4.13, 5.15, 4.22, 6.2, 5.2, 5.98, 4.96, 3.5]
        timings = timings_for(durations)
        segs = ft.plan_segments(timings, lines_for([f"phrase {i}" for i in range(13)]), self.TERMS)
        self.assert_tiles(segs, timings[-1]["end"])
        self.assertEqual(sum(ft.frame_counts(segs)), math.ceil((timings[-1]["end"] + ft.BROLL_TAIL_SECONDS) * ft.FPS - 1e-9))


# ---- 2/3. words, relevance and the choice of clips ---------------------------------------------------------


class WordTests(unittest.TestCase):
    def test_phrase_words_drop_small_words_and_use_singular(self):
        self.assertEqual(ft.phrase_words("food in refrigerator"), ["food", "refrigerator"])
        self.assertEqual(ft.phrase_words("Copper Pipes"), ["copper", "pipe"])
        self.assertEqual(ft.phrase_words("frost ice crystals"), ["frost", "ice", "crystal"])
        self.assertEqual(ft.phrase_words("close-up"), ["close"])  # 'up' is a stop word

    def test_fridge_and_refrigerator_are_the_same_word(self):
        self.assertEqual(ft.phrase_words("fridge"), ft.phrase_words("refrigerator"))

    def test_query_variants_add_the_specific_words_alone(self):
        self.assertEqual(ft.query_variants("kitchen interior"), ["kitchen interior", "kitchen"])  # 'interior' is generic
        self.assertEqual(ft.query_variants("copper pipes"), ["copper pipes", "copper", "pipe"])
        self.assertEqual(ft.query_variants("headphones"), ["headphones"])

    def test_relevance_needs_a_specific_word(self):
        words = ft.phrase_words("kitchen interior")
        self.assertFalse(ft.relevance(words, {"tags": "church, interior, architecture"})[1])
        self.assertTrue(ft.relevance(words, {"tags": "kitchen, home"})[1])
        matched, ok = ft.relevance(words, {"tags": "Kitchen, Interior"})
        self.assertTrue(ok)
        self.assertEqual(matched, ["kitchen", "interior"])

    def test_long_phrases_need_half_of_their_specific_words(self):
        words = ft.phrase_words("air conditioner coils")
        self.assertFalse(ft.relevance(words, {"tags": "air, wind"})[1])
        self.assertTrue(ft.relevance(words, {"tags": "air, conditioner"})[1])

    def test_two_word_phrases_need_both_specific_words(self):
        words = ft.phrase_words("pressure gauge")
        self.assertFalse(ft.relevance(words, {"tags": "clouds, weather, low pressure"})[1])  # weather, not a gauge
        self.assertFalse(ft.relevance(ft.phrase_words("vacuum cleaner"), {"tags": "desert, vacuum, sand"})[1])
        self.assertTrue(ft.relevance(words, {"tags": "pressure, gauge, meter"})[1])
        self.assertTrue(ft.relevance(ft.phrase_words("copper pipes"), {"tags": "copper, pipe, plumbing"})[1])

    def test_a_phrase_made_only_of_generic_words_needs_all_of_them(self):
        words = ft.phrase_words("hot day")
        self.assertFalse(ft.relevance(words, {"tags": "day, sunrise"})[1])
        self.assertTrue(ft.relevance(words, {"tags": "day, hot"})[1])

    def test_blocked_tags(self):
        for tag in ("logo", "Brand", "texts", "sign", "advertisement", "billboard", "label", "packaging", "package", "generated", "midjourney"):
            self.assertIsNotNone(ft.blocked_tag({"tags": f"kitchen, {tag}, food"}), tag)
        self.assertIsNone(ft.blocked_tag({"tags": "kitchen, design, assign"}))  # whole words only


class BrandProneTagTests(unittest.TestCase):
    def test_vehicles_and_product_footage_are_brand_prone(self):
        for tags in ("watch, mechanical, gears", "pocket watch, clockwork", "jet ski, sport, coast", "summer, car", "sports cars, road", "motorcycle, ride", "boats, sea", "buying guides, home",
                     "kitchen, product reviews", "unboxing, box", "Jet Skis, beach"):
            self.assertIsNotNone(ft.brand_prone_tag({"tags": tags}), tags)

    def test_tags_are_compared_as_whole_tags(self):
        for tags in ("watchtower, castle", "ski jump, snow", "carpet, floor", "jet, airplane", "cardboard, box", "boating license"):
            self.assertIsNone(ft.brand_prone_tag({"tags": tags}), tags)

    def test_the_tag_is_returned_as_written(self):
        self.assertEqual(ft.brand_prone_tag({"tags": "summer, Jet Ski, sea"}), "Jet Ski")

    def test_a_phrase_about_the_thing_may_use_it(self):
        self.assertIsNone(ft.brand_prone_tag({"tags": "engine, car"}, ft.phrase_words("car engine")))
        self.assertIsNotNone(ft.brand_prone_tag({"tags": "engine, car"}, ft.phrase_words("engine")))

    def test_flames_and_cooking_mislead_as_a_stand_in(self):
        for tag in ("flame", "fire", "stove", "frying", "cooking", "wok", "burner", "barbecue"):
            self.assertIsNotNone(ft.misleading_fallback_tag({"tags": f"kitchen, {tag}"}), tag)
        self.assertIsNone(ft.misleading_fallback_tag({"tags": "kitchen, ice, frost"}))
        self.assertIsNone(ft.misleading_fallback_tag({"tags": "kitchen, flame"}, ft.phrase_words("gas flame")))


class BlackBarTests(unittest.TestCase):
    BOX = {"x": 313, "y": 0, "w": 1214, "h": 2160}

    def test_cropdetect_output_is_parsed(self):
        text = "[Parsed_cropdetect_1 @ 0x1] x1:0 w:1214 h:2160 crop=1214:2160:0:0\n[Parsed_cropdetect_1 @ 0x1] w:1214 h:2024 crop=1214:2024:0:68\n"
        self.assertEqual(ft.parse_cropdetect(text), (1214, 2024))  # the last line counts
        self.assertIsNone(ft.parse_cropdetect(""))
        self.assertIsNone(ft.parse_cropdetect(None))
        self.assertIsNone(ft.parse_cropdetect("no crop here"))

    def test_bars_are_found_when_the_picture_is_smaller_than_the_crop(self):
        self.assertFalse(ft.has_black_bars(self.BOX, (1214, 2160)))
        self.assertFalse(ft.has_black_bars(self.BOX, (1214, 2158)))  # a thin line does not matter
        self.assertTrue(ft.has_black_bars(self.BOX, (1214, 2024)))  # letterbox: 6 % of the height
        self.assertTrue(ft.has_black_bars(self.BOX, (1100, 2160)))  # bars at the sides
        self.assertFalse(ft.has_black_bars(self.BOX, None))  # unknown: do not refuse

    def test_command_looks_at_the_part_that_will_be_used(self):
        cmd = ft.bars_command("ffmpeg", Path("/c/x.mp4"), 1.5, 4.25, self.BOX)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "1.500")
        self.assertEqual(cmd[cmd.index("-t") + 1], "4.25")
        vf = cmd[cmd.index("-vf") + 1]
        self.assertTrue(vf.startswith("crop=1214:2160:313:0,cropdetect="))
        self.assertIn("reset=0", vf)
        self.assertEqual(cmd[-3:], ["-f", "null", "-"])


class SharpnessTests(unittest.TestCase):
    def test_crop_box_of_common_sizes(self):
        self.assertEqual(ft.crop_box(3840, 2160), {"x": 1312, "y": 0, "w": 1214, "h": 2160})
        self.assertEqual(ft.crop_box(1080, 1920), {"x": 0, "y": 0, "w": 1080, "h": 1920})
        self.assertEqual(ft.crop_box(2160, 3840), {"x": 0, "y": 0, "w": 2160, "h": 3840})
        self.assertEqual(ft.crop_box(1920, 1080), {"x": 656, "y": 0, "w": 606, "h": 1080})
        self.assertEqual(ft.crop_box(1080, 2400), {"x": 0, "y": 240, "w": 1080, "h": 1920})  # taller than 9:16: trim top and bottom

    def test_crop_box_numbers_are_even_and_inside_the_picture(self):
        for w, h in ((3840, 2160), (4096, 2160), (1441, 2497), (2560, 1440), (1080, 1921)):
            box = ft.crop_box(w, h)
            self.assertTrue(all(v % 2 == 0 for v in box.values()), box)
            self.assertLessEqual(box["x"] + box["w"], w)
            self.assertLessEqual(box["y"] + box["h"], h)

    def test_only_sharp_crops_pass(self):
        self.assertTrue(ft.sharp_enough(1080, 1920))
        self.assertTrue(ft.sharp_enough(2160, 3840))
        self.assertTrue(ft.sharp_enough(3840, 2160))  # crop 1214 wide
        self.assertTrue(ft.sharp_enough(4096, 2160))
        self.assertFalse(ft.sharp_enough(1920, 1080))  # crop 606 wide: a 1.8x enlargement
        self.assertFalse(ft.sharp_enough(2560, 1440))
        self.assertFalse(ft.sharp_enough(720, 1280))
        self.assertFalse(ft.sharp_enough(1080, 1350))  # portrait, but only 4:5

    def test_orientation(self):
        self.assertEqual(ft.orientation(1080, 1920), "portrait")
        self.assertEqual(ft.orientation(3840, 2160), "landscape")
        self.assertEqual(ft.orientation(1000, 1000), "landscape")


class RankHitsTests(unittest.TestCase):
    def rank(self, hits, phrase="refrigerator", need=5.0, used=None):
        entries = [{"hit": h, "query": phrase, "rank": i} for i, h in enumerate(hits)]
        return ft.rank_hits(entries, phrase, need, used or set())

    def test_portrait_beats_4k_landscape_when_equally_relevant(self):
        cands, _ = self.rank([make_hit(1, LANDSCAPE_4K), make_hit(2, PORTRAIT_HD)])
        self.assertEqual([c["id"] for c in cands], [2, 1])
        self.assertEqual(cands[0]["orientation"], "portrait")
        self.assertEqual(cands[1]["orientation"], "landscape")
        self.assertEqual(cands[1]["rendition"], "large")  # the 3840x2160 rendition is the only sharp one

    def test_small_landscape_is_rejected(self):
        cands, refused = self.rank([make_hit(1, LANDSCAPE_HD)])
        self.assertEqual(cands, [])
        self.assertEqual(refused, {"picture too small for a sharp 9:16 crop": 1})

    def test_small_portrait_is_rejected(self):
        cands, _ = self.rank([make_hit(1, [(720, 1280), (540, 960), (360, 640), (270, 480)])])
        self.assertEqual(cands, [])

    def test_the_smallest_sharp_rendition_is_taken(self):
        cands, _ = self.rank([make_hit(1, PORTRAIT_4K)])
        self.assertEqual((cands[0]["rendition"], cands[0]["width"], cands[0]["height"]), ("medium", 1080, 1920))

    def test_renditions_without_size_or_url_are_skipped(self):
        broken_large = renditions(LANDSCAPE_4K)
        broken_large["large"] = {"url": "", "width": 0, "height": 0, "size": 0}  # Pixabay sometimes sends an empty 'large'
        cands, _ = self.rank([{**make_hit(1, LANDSCAPE_4K), "videos": broken_large}])
        self.assertEqual(cands, [])  # the remaining renditions are too small
        no_url = renditions(LANDSCAPE_4K)
        no_url["large"]["url"] = None
        self.assertEqual(ft.rendition_options({"videos": no_url})[0]["name"], "tiny")
        self.assertNotIn("large", [o["name"] for o in ft.rendition_options({"videos": no_url})])
        self.assertEqual(len(ft.rendition_options({"videos": renditions(LANDSCAPE_4K)})), 4)
        self.assertEqual(ft.rendition_options({"videos": "nonsense"}), [])
        self.assertEqual(ft.rendition_options({}), [])

    def test_blocked_tags_are_skipped(self):
        cands, refused = self.rank([make_hit(1, PORTRAIT_HD, tags="refrigerator, logo"), make_hit(2, PORTRAIT_HD, tags="refrigerator, Billboard"),
                                    make_hit(3, PORTRAIT_HD)])
        self.assertEqual([c["id"] for c in cands], [3])
        self.assertEqual(sum(refused.values()), 2)

    def test_clip_must_be_half_a_second_longer_than_the_segment(self):
        cands, refused = self.rank([make_hit(1, PORTRAIT_HD, duration=5), make_hit(2, PORTRAIT_HD, duration=6)], need=5.0 + ft.EXTRA_CLIP_SECONDS)
        self.assertEqual([c["id"] for c in cands], [2])
        self.assertEqual(refused, {"too short": 1})

    def test_used_clips_are_not_offered_again(self):
        cands, refused = self.rank([make_hit(1, PORTRAIT_HD), make_hit(2, PORTRAIT_HD)], used={1})
        self.assertEqual([c["id"] for c in cands], [2])
        self.assertEqual(refused, {"already used in this video": 1})

    def test_more_matching_words_beat_portrait(self):
        both = make_hit(1, LANDSCAPE_4K, tags="kitchen, interior")
        one = make_hit(2, PORTRAIT_HD, tags="kitchen")  # 'interior' is generic: one match is enough, two are better
        cands, _ = self.rank([one, both], phrase="kitchen interior")
        self.assertEqual([c["id"] for c in cands], [1, 2])

    def test_an_uploader_who_is_not_in_the_video_yet_comes_first(self):
        series_1 = {**make_hit(1, PORTRAIT_HD), "user_id": 7}
        series_2 = {**make_hit(2, PORTRAIT_HD), "user_id": 7}
        other = {**make_hit(3, PORTRAIT_HD), "user_id": 8}
        entries = [{"hit": h, "query": "refrigerator", "rank": i} for i, h in enumerate([series_1, series_2, other])]
        self.assertEqual([c["id"] for c in ft.rank_hits(entries, "refrigerator", 5.0, set())[0]], [1, 2, 3])
        self.assertEqual([c["id"] for c in ft.rank_hits(entries, "refrigerator", 5.0, {1}, None, {7})[0]], [3, 2])

    def test_an_unused_uploader_comes_before_more_matching_words(self):
        repeat = {**make_hit(1, PORTRAIT_HD, tags="kitchen, interior"), "user_id": 7}  # two matching words, uploader already in the video
        fresh = {**make_hit(2, PORTRAIT_HD, tags="kitchen"), "user_id": 8}  # one matching word, a new uploader
        entries = [{"hit": h, "query": "kitchen interior", "rank": i} for i, h in enumerate([repeat, fresh])]
        self.assertEqual([c["id"] for c in ft.rank_hits(entries, "kitchen interior", 5.0, set())[0]], [1, 2])
        self.assertEqual([c["id"] for c in ft.rank_hits(entries, "kitchen interior", 5.0, set(), None, {7})[0]], [2, 1])

    def test_a_repeat_uploader_is_still_used_when_nothing_else_fits(self):
        only = {**make_hit(1, PORTRAIT_HD), "user_id": 7}
        entries = [{"hit": only, "query": "refrigerator", "rank": 0}]
        self.assertEqual([c["id"] for c in ft.rank_hits(entries, "refrigerator", 5.0, set(), None, {7})[0]], [1])

    def test_brand_prone_hits_are_refused(self):
        jet_ski = make_hit(1, LANDSCAPE_4K, tags="hot, summer, jet ski, sport, beach")
        review = make_hit(2, LANDSCAPE_4K, tags="kitchen, appliances, buying guides, product reviews")
        fine = make_hit(3, LANDSCAPE_4K, tags="hot, summer, beach")
        cands, refused = self.rank([jet_ski, fine], phrase="hot summer")
        self.assertEqual([c["id"] for c in cands], [3])
        self.assertEqual(refused, {"tag 'jet ski' (usually shows a brand)": 1})
        cands, refused = self.rank([review], phrase="kitchen appliances")
        self.assertEqual(cands, [])
        self.assertIn("tag 'buying guides' (usually shows a brand)", refused)

    def test_brand_prone_hits_pass_when_the_phrase_is_about_them(self):
        car = make_hit(1, LANDSCAPE_4K, tags="car, engine")
        self.assertEqual([c["id"] for c in self.rank([car], phrase="car engine")[0]], [1])

    def test_fallback_refuses_flames_and_cooking(self):
        flame = make_hit(1, LANDSCAPE_4K, tags="kitchen, stove, gas, flame, heat")
        calm = make_hit(2, LANDSCAPE_4K, tags="kitchen, interior, cabinet")
        entries = [{"hit": h, "query": "kitchen", "rank": i} for i, h in enumerate([flame, calm])]
        cands, refused = ft.rank_hits(entries, "kitchen", 5.0, set(), fallback_for="vacuum cleaner")
        self.assertEqual([c["id"] for c in cands], [2])
        self.assertEqual(refused, {"tag 'flame' (misleading as a stand-in)": 1})
        self.assertEqual([c["id"] for c in ft.rank_hits(entries, "kitchen", 5.0, set())[0]], [1, 2])  # the phrase's own search: not applied
        gas_flame = [{"hit": make_hit(3, LANDSCAPE_4K, tags="kitchen, gas, flame, heat"), "query": "kitchen", "rank": 0}]
        self.assertEqual([c["id"] for c in ft.rank_hits(gas_flame, "kitchen", 5.0, set(), fallback_for="gas flame")[0]], [3])  # the line is about a flame

    def test_tags_nearer_the_front_beat_portrait(self):
        late = make_hit(1, PORTRAIT_HD, tags="trees, forest, nature, fog, desert")  # mentions the desert as its 5th tag
        early = make_hit(2, LANDSCAPE_4K, tags="desert, dunes, sand")
        cands, _ = self.rank([late, early], phrase="desert")
        self.assertEqual([c["id"] for c in cands], [2, 1])
        self.assertEqual([c["position"] for c in cands], [0, 4])

    def test_equal_tag_positions_still_prefer_portrait(self):
        cands, _ = self.rank([make_hit(1, LANDSCAPE_4K, tags="desert, sand"), make_hit(2, PORTRAIT_HD, tags="desert, dunes")], phrase="desert")
        self.assertEqual([c["id"] for c in cands], [2, 1])

    def test_tag_position_adds_up_the_first_tag_of_every_word(self):
        hit = {"tags": "water, sea, river, drops, nature"}
        self.assertEqual(ft.tag_position(hit, ["water", "drop"]), 0 + 3)
        self.assertEqual(ft.tag_position(hit, ["desert"]), 5)  # not there: behind every tag
        self.assertEqual(ft.tag_position({"tags": ""}, ["water"]), 0)

    def test_reviewed_blocklist_is_respected(self):
        entries = [{"hit": make_hit(1, PORTRAIT_HD), "query": "refrigerator", "rank": 0}, {"hit": make_hit(2, PORTRAIT_HD), "query": "refrigerator", "rank": 1}]
        cands, refused = ft.rank_hits(entries, "refrigerator", 5.0, set(), {"1": "a sign is visible"})
        self.assertEqual([c["id"] for c in cands], [2])
        self.assertEqual(refused, {"on the reviewed blocklist": 1})

    def test_ai_generated_pictures_are_skipped(self):
        cands, refused = self.rank([make_hit(1, PORTRAIT_HD, tags="refrigerator, ai generated, interior")])
        self.assertEqual(cands, [])
        self.assertEqual(sum(refused.values()), 1)

    def test_pixabay_order_breaks_ties(self):
        cands, _ = self.rank([make_hit(5, PORTRAIT_HD), make_hit(3, PORTRAIT_HD), make_hit(9, PORTRAIT_HD)])
        self.assertEqual([c["id"] for c in cands], [5, 3, 9])

    def test_irrelevant_clips_are_refused(self):
        cands, refused = self.rank([make_hit(1, PORTRAIT_HD, tags="church, interior")], phrase="kitchen interior")
        self.assertEqual(cands, [])
        self.assertEqual(refused, {"tags do not match the phrase": 1})

    def test_reason_is_recorded(self):
        cands, _ = self.rank([make_hit(1, LANDSCAPE_4K)])
        for part in ("landscape", "3840x2160", "'large'", "crop 1214x2160", "20 s long", "refrigerator"):
            self.assertIn(part, cands[0]["reason"])
        self.assertEqual(cands[0]["crop"], {"x": 1312, "y": 0, "w": 1214, "h": 2160})
        self.assertEqual(cands[0]["user"], "someone")
        self.assertEqual(cands[0]["page_url"], "https://pixabay.com/videos/clip-1/")


class ChooseClipsTests(unittest.TestCase):
    TERMS = ["kitchen", "ice cubes"]

    def test_no_clip_is_used_twice_in_one_video(self):
        search = search_from({"refrigerator": [make_hit(1, PORTRAIT_HD), make_hit(2, PORTRAIT_HD), make_hit(3, PORTRAIT_HD)]})
        chosen = ft.choose_clips([seg(0, 4), seg(4, 8), seg(8, 12)], self.TERMS, search)
        self.assertEqual([c["id"] for c in chosen], [1, 2, 3])

    def test_falls_back_to_the_video_terms(self):
        search = search_from({"refrigerator": [make_hit(1, LANDSCAPE_HD)], "kitchen": [make_hit(7, PORTRAIT_HD, tags="kitchen")]})
        chosen = ft.choose_clips([seg(0, 4)], self.TERMS, search)
        self.assertEqual(chosen[0]["id"], 7)
        self.assertTrue(chosen[0]["fallback"])
        self.assertEqual(chosen[0]["phrase_searched"], "kitchen")

    def test_fallback_terms_start_at_a_different_term_for_every_segment(self):
        search = search_from({"kitchen": [make_hit(1, PORTRAIT_HD, tags="kitchen"), make_hit(2, PORTRAIT_HD, tags="kitchen")],
                              "ice cubes": [make_hit(3, PORTRAIT_HD, tags="ice, cube"), make_hit(4, PORTRAIT_HD, tags="ice, cube")]})
        chosen = ft.choose_clips([seg(0, 4, "nothing found"), seg(4, 8, "still nothing")], self.TERMS, search)
        self.assertEqual([c["phrase_searched"] for c in chosen], ["kitchen", "ice cubes"])

    def test_fallback_terms_that_share_a_word_with_the_phrase_come_first(self):
        terms = ["kitchen", "open fridge", "ice cubes"]
        self.assertEqual(ft.fallback_terms("refrigerator interior", terms, 0), ["open fridge", "kitchen", "ice cubes"])
        self.assertEqual(ft.fallback_terms("copper pipes", terms, 1), ["open fridge", "ice cubes", "kitchen"])  # nothing shared: rotation by segment
        self.assertEqual(ft.fallback_terms("anything", [], 0), [])
        self.assertEqual(ft.fallback_terms("open day", ["open fridge", "kitchen"], 0), ["open fridge", "kitchen"])  # a generic word ('open') is not shared

    def test_a_related_term_is_tried_before_the_rotation_and_marked_related(self):
        search = search_from({"kitchen": [make_hit(1, PORTRAIT_HD, tags="kitchen")], "ice cubes": [make_hit(2, PORTRAIT_HD, tags="ice, cube")]})
        chosen = ft.choose_clips([seg(0, 4, "ice crystals")], ["kitchen", "ice cubes"], search)
        self.assertEqual((chosen[0]["id"], chosen[0]["phrase_searched"], chosen[0]["fallback_related"]), (2, "ice cubes", True))

    def test_an_unrelated_stand_in_is_marked_and_logged(self):
        search = search_from({"kitchen": [make_hit(1, PORTRAIT_HD, tags="kitchen")]})
        messages = []
        chosen = ft.choose_clips([seg(0, 4, "copper pipes")], ["kitchen"], search, log=messages.append)
        self.assertEqual((chosen[0]["fallback"], chosen[0]["fallback_related"]), (True, False))
        self.assertIn("NOT related", messages[0])

    def test_the_own_phrase_counts_as_related(self):
        chosen = ft.choose_clips([seg(0, 4)], self.TERMS, search_from({"refrigerator": [make_hit(1, PORTRAIT_HD)]}))
        self.assertTrue(chosen[0]["fallback_related"])

    def test_the_fallback_never_shows_flames_or_cooking(self):
        search = search_from({"kitchen": [make_hit(1, PORTRAIT_HD, tags="kitchen, flame, stove"), make_hit(2, PORTRAIT_HD, tags="kitchen, cabinet")]})
        self.assertEqual(ft.choose_clips([seg(0, 4, "vacuum cleaner")], ["kitchen"], search)[0]["id"], 2)

    def test_the_last_picture_must_cover_the_tail_past_the_narration(self):
        long_enough = 4.0 + ft.BROLL_TAIL_SECONDS + ft.EXTRA_CLIP_SECONDS
        search = search_from({"refrigerator": [make_hit(1, PORTRAIT_HD, duration=long_enough - 0.1), make_hit(2, PORTRAIT_HD, duration=long_enough)]})
        self.assertEqual(ft.choose_clips([seg(0, 4)], self.TERMS, search)[0]["id"], 2)  # a single (= last) segment
        search = search_from({"refrigerator": [make_hit(1, PORTRAIT_HD, duration=long_enough - 0.1), make_hit(2, PORTRAIT_HD, duration=long_enough)]})
        self.assertEqual(ft.choose_clips([seg(0, 4), seg(4, 8)], self.TERMS, search)[0]["id"], 1)  # a segment that is not the last needs no tail

    def test_a_next_page_is_only_asked_for_variants_whose_page_was_full(self):
        full_page = [make_hit(100 + i, LANDSCAPE_HD, tags="kitchen") for i in range(ft.PER_PAGE)]  # 50 hits, none sharp enough
        search = search_from({"kitchen interior": [make_hit(99, LANDSCAPE_HD, tags="kitchen, interior")],  # a short answer: no page 2
                              "kitchen": full_page, ("kitchen", 2): [make_hit(1, PORTRAIT_HD, tags="kitchen")]})
        chosen = ft.choose_clips([seg(0, 4, "kitchen interior")], ["x term"], search)
        self.assertEqual(chosen[0]["id"], 1)
        self.assertEqual(search.calls, ["kitchen interior", "kitchen", ("kitchen", 2)])

    def test_no_fallback_flag_when_the_own_phrase_works(self):
        chosen = ft.choose_clips([seg(0, 4)], self.TERMS, search_from({"refrigerator": [make_hit(1, PORTRAIT_HD)]}))
        self.assertFalse(chosen[0]["fallback"])

    def test_failure_names_the_line_and_the_phrase(self):
        lines = [{"text": "Then a compressor squeezes the gas, which makes it hotter."}]
        with self.assertRaises(ft.FootageError) as ctx:
            ft.choose_clips([seg(25.1, 29.4, "pressure gauge", [0])], self.TERMS, search_from({}), lines=lines)
        message = str(ctx.exception)
        self.assertIn("line 0", message)
        self.assertIn("Then a compressor", message)
        self.assertIn("pressure gauge", message)
        self.assertIn("broll", message)

    def test_failure_says_why_hits_were_refused(self):
        search = search_from({"refrigerator": [make_hit(1, LANDSCAPE_HD), make_hit(2, PORTRAIT_HD, duration=2)]})
        with self.assertRaises(ft.FootageError) as ctx:
            ft.choose_clips([seg(0, 4)], ["kitchen"], search)
        self.assertIn("too short", str(ctx.exception))
        self.assertIn("too small", str(ctx.exception))

    def test_search_also_tries_the_single_words(self):
        search = search_from({"kitchen interior": [make_hit(1, PORTRAIT_HD, tags="church, interior")], "kitchen": [make_hit(2, PORTRAIT_HD, tags="kitchen")]})
        chosen = ft.choose_clips([seg(0, 4, "kitchen interior")], ["x term"], search)
        self.assertEqual(chosen[0]["id"], 2)
        self.assertEqual(search.calls[:2], ["kitchen interior", "kitchen"])

    def test_accept_can_refuse_a_candidate(self):
        search = search_from({"refrigerator": [make_hit(1, PORTRAIT_HD), make_hit(2, PORTRAIT_HD)]})
        seen = []

        def accept(cand, segment):
            seen.append(cand["id"])
            return cand["id"] != 1

        chosen = ft.choose_clips([seg(0, 4)], self.TERMS, search, accept=accept)
        self.assertEqual(seen, [1, 2])
        self.assertEqual(chosen[0]["id"], 2)

    def test_a_longer_segment_needs_a_longer_clip(self):
        search = search_from({"refrigerator": [make_hit(1, PORTRAIT_HD, duration=5), make_hit(2, PORTRAIT_HD, duration=9)]})
        self.assertEqual(ft.choose_clips([seg(0, 5.0)], self.TERMS, search)[0]["id"], 2)  # needs 5.5 s

    def test_next_result_page_is_only_asked_for_when_the_first_was_full_and_nothing_fitted(self):
        full_page = [make_hit(100 + i, LANDSCAPE_HD, tags="refrigerator") for i in range(ft.PER_PAGE)]  # 50 hits, none sharp enough
        search = search_from({"refrigerator": full_page, ("refrigerator", 2): [make_hit(1, PORTRAIT_HD)]})
        chosen = ft.choose_clips([seg(0, 4)], ["kitchen"], search)
        self.assertEqual(chosen[0]["id"], 1)
        self.assertEqual(search.calls, ["refrigerator", ("refrigerator", 2)])
        short_page = search_from({"refrigerator": [make_hit(2, LANDSCAPE_HD)]})  # not a full page: there is no page 2
        with self.assertRaises(ft.FootageError):
            ft.choose_clips([seg(0, 4)], ["kitchen"], short_page)
        self.assertNotIn(("refrigerator", 2), short_page.calls)

    def test_never_more_than_three_pages_per_phrase(self):
        full_page = [make_hit(100 + i, LANDSCAPE_HD, tags="refrigerator") for i in range(ft.PER_PAGE)]
        search = search_from({"refrigerator": full_page, ("refrigerator", 2): full_page, ("refrigerator", 3): full_page, ("refrigerator", 4): full_page})
        with self.assertRaises(ft.FootageError):
            ft.choose_clips([seg(0, 4)], ["kitchen"], search)
        self.assertEqual([c for c in search.calls if isinstance(c, tuple)], [("refrigerator", 2), ("refrigerator", 3)])

    def test_choose_clips_spreads_the_clips_over_uploaders(self):
        hits = [{**make_hit(i, PORTRAIT_HD), "user_id": 7 if i < 3 else 8} for i in (1, 2, 3, 4)]
        chosen = ft.choose_clips([seg(0, 4), seg(4, 8), seg(8, 12)], self.TERMS, search_from({"refrigerator": hits}))
        self.assertEqual([c["id"] for c in chosen], [1, 3, 2])  # clip 3 is by a second uploader and jumps the queue

    def test_choose_clips_passes_the_blocklist_on(self):
        search = search_from({"refrigerator": [make_hit(1, PORTRAIT_HD), make_hit(2, PORTRAIT_HD)]})
        chosen = ft.choose_clips([seg(0, 4)], self.TERMS, search, blocklist={"1": "logo on the fridge"})
        self.assertEqual(chosen[0]["id"], 2)

    def test_records_the_segment_index(self):
        search = search_from({"refrigerator": [make_hit(1, PORTRAIT_HD), make_hit(2, PORTRAIT_HD)]})
        self.assertEqual([c["segment"] for c in ft.choose_clips([seg(0, 4), seg(4, 8)], self.TERMS, search)], [0, 1])


class SmallPureFunctionTests(unittest.TestCase):
    def test_pick_offset(self):
        self.assertEqual(ft.pick_offset(12.0, 4.0), 4.0)  # long clip: the middle
        self.assertEqual(ft.pick_offset(5.0, 4.0), 0.5)  # short clip: 0.5 s in
        self.assertEqual(ft.pick_offset(4.4, 4.0), 0.2)  # barely long enough: stay clear of the end
        self.assertEqual(ft.pick_offset(3.0, 4.0), 0.0)

    def test_frame_counts_do_not_drift(self):
        segs = ft.plan_segments(timings_for([4.86, 4.04, 4.52, 6.11]), lines_for(["a", "b", "c", "d"]), ["x"])
        counts = ft.frame_counts(segs)
        self.assertEqual(sum(counts), math.ceil((segs[-1]["end"] + ft.BROLL_TAIL_SECONDS) * ft.FPS - 1e-9))
        self.assertGreaterEqual(sum(counts) / 30, segs[-1]["end"] + ft.MIN_TAIL_SECONDS)  # MoneyPrinterTurbo wants audio + 0.1 s: no looping
        for k, one in enumerate(segs):
            self.assertAlmostEqual(sum(counts[:k]) / 30, one["start"], delta=0.02)

    def test_credits_one_per_clip_in_order(self):
        chosen = [{"id": 5, "user": "Ann", "page_url": "https://pixabay.com/videos/a-5/"},
                  {"id": 9, "user": "Bob", "page_url": "https://pixabay.com/videos/b-9/"},
                  {"id": 5, "user": "Ann", "page_url": "https://pixabay.com/videos/a-5/"}]
        credits = ft.clip_credits(chosen)
        self.assertEqual(credits, [{"provider": "pixabay", "id": 5, "user": "Ann", "page_url": "https://pixabay.com/videos/a-5/"},
                                   {"provider": "pixabay", "id": 9, "user": "Bob", "page_url": "https://pixabay.com/videos/b-9/"}])
        self.assertEqual(ft.credit_line(credits[0]), "Video by Ann on Pixabay: https://pixabay.com/videos/a-5/")

    def test_credit_line_without_a_user_or_page(self):
        self.assertEqual(ft.credit_line({"user": "", "page_url": "https://pixabay.com/videos/a-5/"}), "Video on Pixabay: https://pixabay.com/videos/a-5/")
        self.assertEqual(ft.credit_line({"user": "Ann", "page_url": ""}), "Video by Ann on Pixabay")


class FfmpegArgumentTests(unittest.TestCase):
    def test_segment_command_crops_scales_and_limits_the_length(self):
        cmd = ft.segment_command("/bin/ffmpeg", Path("/c/in.mp4"), 4.0, 129, ft.crop_box(3840, 2160), Path("/w/seg-00.mp4"))
        self.assertEqual(cmd[0], "/bin/ffmpeg")
        pairs = dict(zip(cmd, cmd[1:]))
        self.assertEqual(pairs["-ss"], "4.000")
        self.assertEqual(pairs["-i"], "/c/in.mp4")
        self.assertEqual(pairs["-frames:v"], "129")
        self.assertEqual(pairs["-r"], "30")
        self.assertEqual(pairs["-c:v"], "libx264")
        self.assertEqual(pairs["-pix_fmt"], "yuv420p")
        self.assertIn("-an", cmd)  # no audio
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))  # seek before the input
        vf = pairs["-vf"]
        self.assertIn("crop=1214:2160:1312:0", vf)
        self.assertIn("scale=1080:1920", vf)
        self.assertIn("fps=30", vf)
        self.assertLess(vf.index("crop="), vf.index("scale="))
        self.assertEqual(cmd[-1], "/w/seg-00.mp4")

    def test_portrait_clip_is_not_cropped_at_all(self):
        cmd = ft.segment_command("ffmpeg", Path("a.mp4"), 0.5, 90, ft.crop_box(1080, 1920), Path("o.mp4"))
        self.assertIn("crop=1080:1920:0:0", dict(zip(cmd, cmd[1:]))["-vf"])

    def test_concat_command_and_listing(self):
        cmd = ft.concat_command("ffmpeg", Path("/w/list.txt"), Path("/w/broll.mp4"))
        self.assertEqual(cmd[cmd.index("-f") + 1], "concat")
        self.assertEqual(cmd[cmd.index("-c") + 1], "copy")
        self.assertEqual(ft.concat_listing([Path("/w/a.mp4"), Path("/w/it's.mp4")]), "file '/w/a.mp4'\nfile '/w/it'\\''s.mp4'\n")


# ---- 2. Pixabay client: cache, key masking, errors ---------------------------------------------------------


class FakeResponse:
    def __init__(self, payload):
        self._body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self, *_):
        body, self._body = self._body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeNet:
    """Records the requested URLs and answers from a list of responses / exceptions (the last one repeats)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.urls = []

    def __call__(self, req, timeout):
        self.urls.append(req.full_url)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)


ANSWER = {"total": 1, "totalHits": 1, "hits": [make_hit(11, PORTRAIT_HD)]}


class PixabayClientTests(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "cache"
        self.clock = [1_000_000.0]
        self.sleeps = []

    def client(self, net):
        return ft.PixabayClient(FAKE_KEY, cache_dir=self.cache, urlopen=net, now=lambda: self.clock[0], sleep=self.sleeps.append)

    def test_request_has_the_documented_parameters(self):
        net = FakeNet(ANSWER)
        self.assertEqual(self.client(net).search("Open  Refrigerator"), ANSWER["hits"])
        query = urllib.parse.parse_qs(urllib.parse.urlparse(net.urls[0]).query)
        self.assertTrue(net.urls[0].startswith("https://pixabay.com/api/videos/?"))
        self.assertEqual(query["q"], ["open refrigerator"])
        self.assertEqual(query["per_page"], ["50"])
        self.assertEqual(query["safesearch"], ["true"])
        self.assertEqual(query["video_type"], ["film"])
        self.assertEqual(query["key"], [FAKE_KEY])

    def test_cache_file_is_named_after_the_query_without_the_key(self):
        client = self.client(FakeNet(ANSWER))
        client.search("ice cubes")
        expected = hashlib.sha256(b"per_page=50&q=ice+cubes&safesearch=true&video_type=film").hexdigest() + ".json"
        self.assertEqual([p.name for p in self.cache.iterdir()], [expected])
        self.assertEqual(client.cache_path("ICE  cubes").name, expected)  # same query after tidying
        for p in self.cache.iterdir():
            self.assertNotIn(FAKE_KEY, p.name)
            self.assertNotIn(FAKE_KEY, p.read_text(encoding="utf-8"))

    def test_second_search_is_answered_from_the_cache(self):
        net = FakeNet(ANSWER)
        client = self.client(net)
        client.search("kitchen")
        self.clock[0] += 3600
        self.assertEqual(client.search("kitchen"), ANSWER["hits"])
        self.assertEqual(len(net.urls), 1)
        self.assertEqual((client.requests, client.cache_hits), (1, 1))
        client2 = self.client(net)  # a new run reads the same cache
        client2.search("kitchen")
        self.assertEqual((len(net.urls), client2.cache_hits), (1, 1))

    def test_cache_expires_after_24_hours(self):
        net = FakeNet(ANSWER)
        client = self.client(net)
        client.search("kitchen")
        self.clock[0] += 24 * 3600 - 60
        client.search("kitchen")
        self.assertEqual(len(net.urls), 1)
        self.clock[0] += 120
        client.search("kitchen")
        self.assertEqual(len(net.urls), 2)

    def test_a_broken_cache_file_is_ignored(self):
        net = FakeNet(ANSWER)
        client = self.client(net)
        self.cache.mkdir(parents=True)
        client.cache_path("kitchen").write_text("{not json", encoding="utf-8")
        self.assertEqual(client.search("kitchen"), ANSWER["hits"])
        self.assertEqual(len(net.urls), 1)

    def test_http_error_message_never_contains_the_key(self):
        err = urllib.error.HTTPError(f"https://pixabay.com/api/videos/?key={FAKE_KEY}&q=x", 400, "Bad Request", {}, io.BytesIO(b"[ERROR 400] key invalid"))
        with self.assertRaises(ft.FootageError) as ctx:
            self.client(FakeNet(err)).search("x")
        self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertIn("HTTP 400", str(ctx.exception))
        self.assertIn("config.toml", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)  # the original error (which carries the URL) is not chained

    def test_connection_errors_never_contain_the_key(self):
        for exc in (urllib.error.URLError(f"failed for https://pixabay.com/api/videos/?key={FAKE_KEY}&q=x"), OSError(f"reset {FAKE_KEY}")):
            with self.assertRaises(ft.FootageError) as ctx:
                self.client(FakeNet(exc)).search("x")
            self.assertNotIn(FAKE_KEY, str(ctx.exception))
            self.assertIn("internet", str(ctx.exception))

    def test_a_page_beyond_the_last_one_is_just_empty(self):
        err = urllib.error.HTTPError("https://pixabay.com/api/videos/?key=zzz", 400, "Bad Request", {}, io.BytesIO(b'[ERROR 400] "page" is out of valid range.'))
        net = FakeNet(err)
        self.assertEqual(self.client(net).search("kitchen", page=3), [])
        with self.assertRaises(ft.FootageError):  # on page 1 the same answer is a real error
            self.client(net).search("kitchen")

    def test_a_page_beyond_the_last_one_is_remembered(self):
        err = urllib.error.HTTPError("https://pixabay.com/api/videos/?key=zzz", 400, "Bad Request", {}, io.BytesIO(b'[ERROR 400] "page" is out of valid range.'))
        net = FakeNet(err)
        self.assertEqual(self.client(net).search("kitchen", page=2), [])
        self.assertEqual(len(net.urls), 1)
        later = self.client(net)  # the next run does not ask again
        self.assertEqual(later.search("kitchen", page=2), [])
        self.assertEqual((len(net.urls), later.cache_hits), (1, 1))
        self.clock[0] += 24 * 3600 + 60  # ... until the 24 hour cache has expired
        self.client(net).search("kitchen", page=2)
        self.assertEqual(len(net.urls), 2)

    def test_cache_writing_leaves_no_temporary_files_and_uses_unique_names(self):
        net = FakeNet(ANSWER)
        client = self.client(net)
        self.cache.mkdir(parents=True)
        decoy = client.cache_path("kitchen").with_suffix(".tmp")  # the old fixed temporary name
        decoy.write_text("another run is writing here", encoding="utf-8")
        client.search("kitchen")
        self.assertEqual(decoy.read_text(encoding="utf-8"), "another run is writing here")
        self.assertEqual(sorted(p.suffix for p in self.cache.iterdir()), [".json", ".tmp"])  # the answer + the decoy, nothing else

    def test_rate_limit_answer_waits_and_retries(self):
        limited = urllib.error.HTTPError("https://pixabay.com/api/videos/?key=zzz", 429, "Too Many Requests", {}, io.BytesIO(b""))
        net = FakeNet(limited, ANSWER)
        self.assertEqual(self.client(net).search("x"), ANSWER["hits"])
        self.assertEqual(len(net.urls), 2)
        self.assertEqual(self.sleeps, [20])

    def test_rate_limit_that_never_clears_is_a_plain_error(self):
        limited = urllib.error.HTTPError("https://pixabay.com/api/videos/?key=zzz", 429, "Too Many Requests", {}, io.BytesIO(b""))
        with self.assertRaises(ft.FootageError) as ctx:
            self.client(FakeNet(limited)).search("x")
        self.assertIn("429", str(ctx.exception))
        self.assertNotIn("zzz", str(ctx.exception))

    def test_answer_without_hits_is_a_plain_error(self):
        for body in (b"not json", json.dumps({"hits": "no"}).encode(), json.dumps({"total": 0}).encode()):
            with self.assertRaises(ft.FootageError) as ctx:
                self.client(FakeNet(body)).search("x")
            self.assertIn("unexpected", str(ctx.exception))
        self.assertFalse(self.cache.exists() and any(self.cache.iterdir()))  # nothing broken is cached

    def test_never_more_than_ninety_requests_a_minute(self):
        client = self.client(FakeNet(ANSWER))
        client._sent = [self.clock[0] - 10 + i * 0.01 for i in range(ft.REQUESTS_PER_MINUTE)]
        client.search("fresh query")
        self.assertEqual(len(self.sleeps), 1)
        self.assertGreater(self.sleeps[0], 40)

    def test_a_key_is_required(self):
        with self.assertRaises(ft.FootageError):
            ft.PixabayClient("")


class SecretTests(unittest.TestCase):
    def test_mask_secret_hides_key_parameters_and_the_key_itself(self):
        masked = ft.mask_secret(f"GET https://pixabay.com/api/videos/?key={FAKE_KEY}&q=cats failed; key={FAKE_KEY}")
        self.assertNotIn(FAKE_KEY, masked)
        self.assertIn("key=***&q=cats", masked)
        self.assertEqual(ft.mask_secret(f"oops {FAKE_KEY} oops", FAKE_KEY), "oops *** oops")
        self.assertEqual(ft.mask_secret("nothing to hide"), "nothing to hide")

    def test_client_repr_hides_the_key(self):
        client = ft.PixabayClient(FAKE_KEY, cache_dir=Path("/nonexistent"))
        self.assertNotIn(FAKE_KEY, repr(client))
        self.assertNotIn(FAKE_KEY, str(client))

    def test_key_is_read_from_config(self):
        self.assertEqual(ft.pixabay_key_from_config({"pixabay_api_keys": ["  ", " abc "]}), "abc")
        self.assertIsNone(ft.pixabay_key_from_config({"pixabay_api_keys": []}))
        self.assertIsNone(ft.pixabay_key_from_config({}))
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text('[app]\npixabay_api_keys = ["k-123"]\n', encoding="utf-8")
            self.assertEqual(ft.load_pixabay_key(cfg), "k-123")
            cfg.write_text("[app]\npixabay_api_keys = []\n", encoding="utf-8")
            self.assertIsNone(ft.load_pixabay_key(cfg))
            cfg.write_text("not = [valid", encoding="utf-8")
            with self.assertRaises(ft.FootageError):
                ft.load_pixabay_key(cfg)
            with self.assertRaises(ft.FootageError):
                ft.load_pixabay_key(Path(tmp) / "missing.toml")


class BlocklistFileTests(unittest.TestCase):
    def test_missing_file_is_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ft.load_clip_blocklist(Path(tmp) / "none.json"), {})

    def test_file_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            path.write_text('{"pixabay": {"141854": "a sign", "7": "logo"}}', encoding="utf-8")
            self.assertEqual(ft.load_clip_blocklist(path), {"141854": "a sign", "7": "logo"})

    def test_broken_file_is_a_plain_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            for text in ("{nope", "[1, 2]", '{"pixabay": ["1"]}'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ft.FootageError):
                    ft.load_clip_blocklist(path)

    def test_the_real_blocklist_file_is_valid(self):
        blocklist = ft.load_clip_blocklist()
        self.assertIn("141854", blocklist)
        self.assertIn("99435", blocklist)  # a jet ski with 'SEADOO' on it
        self.assertIn("204582", blocklist)  # a watch movement stamped 'MIYOTA' 


class DownloadTests(NoNetworkTestCase):
    def test_download_writes_the_file_in_one_piece(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "clips" / "x.mp4"
            ft.download_file("https://cdn.example/x.mp4", dest, lambda req, timeout: FakeResponse(b"VIDEO" * 100))
            self.assertEqual(dest.read_bytes(), b"VIDEO" * 100)
            self.assertFalse(dest.with_name("x.mp4.part").exists())

    def test_failed_or_oversized_or_empty_downloads_leave_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.mp4"
            with self.assertRaises(ft.FootageError):
                ft.download_file("https://cdn.example/x.mp4", dest, FakeNet(urllib.error.URLError("down")))
            with self.assertRaises(ft.FootageError):
                ft.download_file("https://cdn.example/x.mp4", dest, lambda req, timeout: FakeResponse(b""))
            with self.assertRaises(ft.FootageError):
                ft.download_file("https://cdn.example/x.mp4", dest, lambda req, timeout: FakeResponse(b"x" * 100), max_bytes=10)
            self.assertEqual(list(Path(tmp).iterdir()), [])


    def test_a_download_has_its_own_temporary_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.mp4"
            decoy = Path(tmp) / "x.mp4.part"  # what the old fixed name was: another run's download must be left alone
            decoy.write_bytes(b"OTHER RUN")
            seen = []

            def opener(req, timeout):
                seen.append(sorted(p.name for p in Path(tmp).iterdir()))
                return FakeResponse(b"VIDEO")

            ft.download_file("https://cdn.example/x.mp4", dest, opener)
            self.assertEqual(dest.read_bytes(), b"VIDEO")
            self.assertEqual(decoy.read_bytes(), b"OTHER RUN")
            self.assertEqual(len(seen[0]), 2)  # the decoy + this download's own file
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["x.mp4", "x.mp4.part"])

    def test_a_download_has_a_total_time_limit(self):
        class Slow:
            def __init__(self):
                self.calls = 0

            def read(self, *_):
                self.calls += 1
                return b"x" * 10

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        ticks = iter(range(0, 10_000, 100))  # every call of the clock is 100 s later
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.mp4"
            with self.assertRaises(ft.FootageError) as ctx:
                ft.download_file("https://cdn.example/x.mp4", dest, lambda req, timeout: Slow(), max_seconds=250, clock=lambda: next(ticks))
            self.assertIn("longer than 250 s", str(ctx.exception))
            self.assertEqual(list(Path(tmp).iterdir()), [])


class PruneClipsTests(unittest.TestCase):
    NOW = 2_000_000_000.0
    DAY = 24 * 3600

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def make(self, name, size=100, age_days=0.0, age_seconds=None):
        path = self.dir / name
        path.write_bytes(b"x" * size)
        age = age_seconds if age_seconds is not None else age_days * self.DAY
        os.utime(path, (self.NOW - age, self.NOW - age))
        return path

    def prune(self, keep=(), **kw):
        return ft.prune_clips(self.dir, set(keep), now=lambda: self.NOW, **kw)

    def test_old_clips_go_and_fresh_ones_stay(self):
        old, fresh = self.make("pixabay-1-large.mp4", age_days=40), self.make("pixabay-2-large.mp4", age_days=2)
        self.assertEqual(self.prune(max_age_seconds=30 * self.DAY), [old.name])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_the_clips_of_this_video_are_never_deleted(self):
        used = self.make("pixabay-1-large.mp4", size=500, age_days=400)
        self.assertEqual(self.prune(keep=[used], max_bytes=1, max_age_seconds=self.DAY), [])
        self.assertTrue(used.exists())

    def test_above_the_size_limit_the_least_recently_used_go_first(self):
        oldest = self.make("pixabay-1-large.mp4", size=100, age_days=3)
        middle = self.make("pixabay-2-large.mp4", size=100, age_days=2)
        newest = self.make("pixabay-3-large.mp4", size=100, age_days=1)
        used = self.make("pixabay-4-large.mp4", size=100, age_days=9)
        deleted = self.prune(keep=[used], max_bytes=250, max_age_seconds=30 * self.DAY)
        self.assertEqual(deleted, [oldest.name, middle.name])  # 400 bytes -> 200: stops as soon as it fits
        self.assertTrue(newest.exists() and used.exists())

    def test_leftover_temporary_files_go_when_they_are_old(self):
        stale = self.make("pixabay-1-large.mp4.abc123.part", age_seconds=2 * ft.STALE_TEMP_SECONDS)
        running = self.make("pixabay-2-large.mp4.def456.part", age_seconds=60)  # a download that is happening right now
        self.assertEqual(self.prune(), [stale.name])
        self.assertTrue(running.exists())

    def test_other_files_and_a_missing_folder_are_left_alone(self):
        note = self.make("notes.txt", age_days=900)
        self.assertEqual(self.prune(max_bytes=0, max_age_seconds=1), [])
        self.assertTrue(note.exists())
        self.assertEqual(ft.prune_clips(self.dir / "missing", set()), [])

    def test_touch_clip_marks_a_clip_as_used_now(self):
        path = self.make("pixabay-1-large.mp4", age_days=40)
        ft.touch_clip(path, now=lambda: self.NOW)
        self.assertEqual(int(path.stat().st_mtime), int(self.NOW))
        self.assertEqual(self.prune(max_age_seconds=30 * self.DAY), [])


# ---- frame comparison ----------------------------------------------------------------------------------------


class OrderCheckTests(unittest.TestCase):
    SIZE = ft.SIGNATURE_W * ft.SIGNATURE_H

    def test_mean_abs_diff(self):
        self.assertEqual(ft.mean_abs_diff(b"\x00\x00", b"\x00\x00"), 0)
        self.assertEqual(ft.mean_abs_diff(b"\x00\x0a", b"\x0a\x00"), 10)
        self.assertEqual(ft.mean_abs_diff(b"", b""), 255.0)
        self.assertEqual(ft.mean_abs_diff(b"\x00", b"\x00\x00"), 255.0)

    def fake_run(self, pictures):
        def run(cmd, capture_output=True, timeout=None, **_):
            video = cmd[cmd.index("-i") + 1]
            t = float(cmd[cmd.index("-ss") + 1])
            return mock.Mock(returncode=0, stdout=pictures[(video, round(t, 1))], stderr=b"")
        return run

    def test_same_pictures_pass_and_different_pictures_are_flagged(self):
        pictures = {("mpt.mp4", 2.0): bytes([100]) * self.SIZE, ("broll.mp4", 2.0): bytes([104]) * self.SIZE,  # re-encoding noise
                    ("mpt.mp4", 6.0): bytes([20]) * self.SIZE, ("broll.mp4", 6.0): bytes([220]) * self.SIZE}  # a different clip
        results = ft.check_order("ffmpeg", Path("mpt.mp4"), Path("broll.mp4"), [2.0, 6.0], limit=20, run=self.fake_run(pictures))
        self.assertEqual([r["same"] for r in results], [True, False])
        self.assertEqual(results[0]["diff"], 4.0)

    def test_unreadable_frame_is_a_plain_error(self):
        run = lambda cmd, **_: mock.Mock(returncode=1, stdout=b"", stderr=b"boom")  # noqa: E731
        with self.assertRaises(ft.FootageError):
            ft.frame_signature("ffmpeg", Path("x.mp4"), 1.0, run)

    def test_middle_times(self):
        self.assertEqual(ft.middle_times([seg(0, 4), seg(4, 9.5)]), [2.0, 6.75])


# ---- the whole runner with fakes -----------------------------------------------------------------------------


class BuildBrollTests(NoNetworkTestCase):
    """build_broll with a fake Pixabay, a fake downloader and fake ffmpeg/ffprobe: checks the wiring, not the pictures."""

    SIZES = {1: (1080, 1920), 2: (3840, 2160), 3: (1080, 1920), 4: (3840, 2160)}  # what ffprobe "sees" in each downloaded clip

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.script = {"id": "t", "video_terms": ["kitchen", "ice cubes", "coils", "pipes"],
                       "lines": [{"text": "one", "broll": "refrigerator"}, {"text": "two", "broll": "ice cubes"}, {"text": "three", "broll": "ice cubes"}]}
        self.timings = timings_for([4.0, 4.0, 4.0])
        self.total = self.timings[-1]["end"]  # 12.5 s: segments are 0-4.25 (refrigerator) and 4.25-12.5 (ice cubes, cut in two pieces)
        self.downloads = []
        self.commands = []
        self.probe_override = None
        self.bars = {}  # clip id (text) -> (width, height) of the picture that cropdetect finds
        self.bar_checks = []
        self.bars_returncode = 0
        self.SIZES = dict(self.SIZES)  # tests change sizes: never touch the shared class dict

    def urlopen(self, req, timeout):
        self.downloads.append(req.full_url)
        return FakeResponse(b"CLIPDATA")

    def probe_answer(self, name):
        if name == "broll.mp4":
            return 1080, 1920, math.ceil((self.total + ft.BROLL_TAIL_SECONDS) * 30 - 1e-9) / 30
        return (*self.SIZES[int(name.split("-")[1])], 30.0)

    def fake_tool(self, cmd, capture_output=True, text=False, timeout=None, **_):
        self.commands.append(cmd)
        if "ffprobe" in cmd[0]:
            name = Path(cmd[-1]).name
            override = self.probe_override(name) if self.probe_override else None
            if override is not None:
                return override
            w, h, d = self.probe_answer(name)
            return mock.Mock(returncode=0, stderr="", stdout=json.dumps({"streams": [{"codec_type": "video", "width": w, "height": h}], "format": {"duration": str(d)}}))
        if any("cropdetect" in part for part in cmd):  # the black-bar check: by default the whole crop is picture
            self.bar_checks.append(Path(cmd[cmd.index("-i") + 1]).name)
            vf = cmd[cmd.index("-vf") + 1]
            box_w, box_h = (int(x) for x in vf.split("crop=")[1].split(",")[0].split(":")[:2])
            w, h = self.bars.get(Path(cmd[cmd.index("-i") + 1]).name.split("-")[1], (box_w, box_h))
            return mock.Mock(returncode=self.bars_returncode, stderr=f"[Parsed_cropdetect_1 @ 0x1] x1:0 w:{w} h:{h} crop={w}:{h}:0:0\n", stdout="")
        Path(cmd[-1]).write_bytes(b"OUT")  # ffmpeg writes its last argument
        return mock.Mock(returncode=0, stderr="", stdout="")

    def build(self, table):
        client = ft.PixabayClient(FAKE_KEY, cache_dir=self.tmp / "cache", urlopen=no_network)
        client.search = search_from(table)  # no network: answers come straight from the table
        return ft.build_broll(self.script, self.timings, self.total, self.tmp / "work", FAKE_KEY, "ffmpeg", "ffprobe", log=lambda m: None,
                              client=client, clips_dir=self.tmp / "clips", urlopen=self.urlopen, run=self.fake_tool)

    def table(self):
        return {
            "refrigerator": [make_hit(1, PORTRAIT_HD, user="Ann")],
            "ice cubes": [make_hit(2, LANDSCAPE_4K, tags="ice, cube", user="Bob"), make_hit(3, PORTRAIT_HD, tags="ice, cube", user="Cy")],
        }

    def test_builds_the_file_credits_and_report(self):
        result = self.build(self.table())
        self.assertEqual(result["path"], self.tmp / "work" / "broll.mp4")
        self.assertTrue(result["path"].is_file())
        self.assertEqual(len(result["segments"]), 3)
        report = result["report"]
        self.assertEqual(report["provider"], "pixabay")
        self.assertEqual((report["downloads"], report["clips_used"]), (3, 3))
        self.assertEqual([s["clip_id"] for s in report["segments"]], [1, 3, 2])  # portrait first, then the 4K landscape
        last = report["segments"][2]
        for field in ("phrase", "clip_id", "orientation", "rendition", "source_size", "crop_source_size", "reason", "start", "end"):
            self.assertIn(field, last)
        self.assertEqual((last["orientation"], last["source_size"], last["crop_source_size"]), ("landscape", "3840x2160", "1214x2160"))
        self.assertEqual(report["segments"][1]["crop_source_size"], "1080x1920")
        self.assertEqual(report["unrelated_fallbacks"], 0)
        self.assertEqual(result["credit_lines"], ["Video by Ann on Pixabay: https://pixabay.com/videos/clip-1/",
                                                  "Video by Cy on Pixabay: https://pixabay.com/videos/clip-3/",
                                                  "Video by Bob on Pixabay: https://pixabay.com/videos/clip-2/"])
        self.assertEqual(set(result["credits"][0]), {"provider", "id", "user", "page_url"})
        self.assertNotIn(FAKE_KEY, json.dumps(report))
        self.assertEqual(len(self.downloads), 3)

    def test_clips_already_on_disk_are_reused_not_downloaded_again(self):
        self.build(self.table())
        self.downloads.clear()
        report = self.build(self.table())["report"]
        self.assertEqual(self.downloads, [])
        self.assertEqual((report["downloads"], report["clip_cache_hits"]), (0, 3))

    def test_segments_are_cut_to_exact_frame_counts(self):
        self.build(self.table())
        frames = [int(c[c.index("-frames:v") + 1]) for c in self.commands if "-frames:v" in c]
        self.assertEqual(len(frames), 3)
        self.assertEqual(sum(frames), math.ceil((self.total + ft.BROLL_TAIL_SECONDS) * 30 - 1e-9))
        self.assertGreaterEqual(sum(frames) / 30, self.total + ft.MIN_TAIL_SECONDS)  # longer than the narration: MPT never loops it

    def test_a_file_that_is_not_what_was_listed_is_replaced_by_the_next_candidate(self):
        table = self.table()
        table["ice cubes"] = [make_hit(2, LANDSCAPE_4K, tags="ice, cube"), make_hit(3, PORTRAIT_HD, tags="ice, cube"), make_hit(4, LANDSCAPE_4K, tags="ice, cube")]
        self.SIZES[2] = (640, 360)  # the listing promised 4K, the file is tiny
        report = self.build(table)["report"]
        self.assertEqual([s["clip_id"] for s in report["segments"]], [1, 3, 4])
        self.assertEqual(report["downloads"], 4)

    def test_download_budget_is_segments_plus_a_small_margin(self):
        self.probe_override = lambda name: mock.Mock(returncode=1, stderr="invalid data", stdout="") if name.startswith("pixabay-") else None  # every file is broken
        table = {"refrigerator": [make_hit(i, PORTRAIT_HD) for i in range(1, 30)]}
        with self.assertRaises(ft.FootageError) as ctx:
            self.build(table)
        self.assertEqual(len(self.downloads), 3 + ft.DOWNLOAD_MARGIN)
        self.assertIn("downloads", str(ctx.exception))

    def test_no_clip_for_a_line_is_a_plain_error(self):
        with self.assertRaises(ft.FootageError) as ctx:
            self.build({"refrigerator": [make_hit(1, PORTRAIT_HD)]})
        self.assertIn("ice cubes", str(ctx.exception))
        self.assertIn("line 1", str(ctx.exception))

    def test_a_clip_with_black_bars_is_replaced_by_the_next_candidate(self):
        table = self.table()
        table["ice cubes"] = [make_hit(2, LANDSCAPE_4K, tags="ice, cube"), make_hit(3, PORTRAIT_HD, tags="ice, cube"), make_hit(4, LANDSCAPE_4K, tags="ice, cube")]
        self.SIZES[4] = (3840, 2160)
        self.bars["2"] = (1214, 2024)  # 6% of the height is a black bar
        messages = []
        client = ft.PixabayClient(FAKE_KEY, cache_dir=self.tmp / "cache", urlopen=no_network)
        client.search = search_from(table)
        result = ft.build_broll(self.script, self.timings, self.total, self.tmp / "work", FAKE_KEY, "ffmpeg", "ffprobe", log=messages.append,
                                client=client, clips_dir=self.tmp / "clips", urlopen=self.urlopen, run=self.fake_tool)
        self.assertEqual([s["clip_id"] for s in result["report"]["segments"]], [1, 3, 4])
        self.assertTrue(any("black bars" in m and "pixabay 2" in m for m in messages))

    def test_a_clip_whose_bars_cannot_be_measured_is_not_refused(self):
        self.bars_returncode = 1
        report = self.build(self.table())["report"]
        self.assertEqual([s["clip_id"] for s in report["segments"]], [1, 3, 2])

    def test_a_clip_that_was_found_unusable_is_not_downloaded_or_checked_again(self):
        table = {"refrigerator": [make_hit(1, PORTRAIT_HD)], "ice cubes": [make_hit(2, LANDSCAPE_4K, tags="ice, cube"), make_hit(3, PORTRAIT_HD, tags="ice, cube"), make_hit(4, LANDSCAPE_4K, tags="ice, cube")]}
        self.SIZES[4] = (3840, 2160)
        self.bars["2"] = (1214, 2024)  # black bars: refused for the first 'ice cubes' piece, and not looked at again for the second
        report = self.build(table)["report"]
        self.assertEqual([s["clip_id"] for s in report["segments"]], [1, 3, 4])
        self.assertEqual(sum(1 for url in self.downloads if url.endswith("/large.mp4")), 4)  # clips 1, 2, 3, 4: clip 2 once
        self.assertEqual(self.bar_checks.count("pixabay-2-large.mp4"), 1)

    def test_every_chosen_clip_is_checked_for_bars(self):
        self.build(self.table())
        self.assertEqual(sorted(set(self.bar_checks)), ["pixabay-1-large.mp4", "pixabay-2-large.mp4", "pixabay-3-large.mp4"])

    def test_the_picture_runs_past_the_narration_so_mpt_never_loops_it(self):
        result = self.build(self.table())
        self.assertGreaterEqual(result["report"]["broll_seconds"], self.total + ft.MIN_TAIL_SECONDS)

    def test_a_file_that_is_as_short_as_the_narration_is_refused(self):
        self.probe_override = lambda name: mock.Mock(returncode=0, stderr="", stdout=json.dumps(
            {"streams": [{"codec_type": "video", "width": 1080, "height": 1920}], "format": {"duration": str(self.total)}})) if name == "broll.mp4" else None
        with self.assertRaises(ft.FootageError) as ctx:
            self.build(self.table())
        self.assertIn("should be", str(ctx.exception))

    def test_old_unused_clips_are_pruned_and_reported(self):
        clips = self.tmp / "clips"
        clips.mkdir()
        stale = clips / "pixabay-999-large.mp4"
        stale.write_bytes(b"old")
        os.utime(stale, (1, 1))  # 1970
        report = self.build(self.table())["report"]
        self.assertFalse(stale.exists())
        self.assertEqual(report["pruned_clips"], ["pixabay-999-large.mp4"])
        self.assertEqual(len(list(clips.glob("pixabay-*.mp4"))), 3)  # the clips of this video stay

    def test_a_reused_clip_is_marked_as_used_now(self):
        self.build(self.table())
        clip = next((self.tmp / "clips").glob("pixabay-1-*.mp4"))
        os.utime(clip, (1, 1))
        self.build(self.table())
        self.assertGreater(clip.stat().st_mtime, 1_000_000)

    def unrelated_table(self):
        table = self.table()
        table["ice cubes"] = []
        table["kitchen"] = [make_hit(5, PORTRAIT_HD, tags="kitchen, interior"), make_hit(6, PORTRAIT_HD, tags="kitchen, cabinet")]
        self.SIZES.update({5: (1080, 1920), 6: (1080, 1920)})
        return table

    def test_too_many_unrelated_stand_in_pictures_are_a_plain_error(self):
        with self.assertRaises(ft.FootageError) as ctx:
            self.build(self.unrelated_table())  # 2 of the 3 segments would show a kitchen for 'ice cubes'
        message = str(ctx.exception)
        self.assertIn("2 of 3", message)
        self.assertIn("'ice cubes'", message)
        self.assertIn("broll", message)

    def test_a_unrelated_stand_in_within_the_limit_is_only_counted(self):
        with mock.patch.object(ft, "MAX_UNRELATED_SHARE", 1.0):
            report = self.build(self.unrelated_table())["report"]
        self.assertEqual(report["unrelated_fallbacks"], 2)  # both 'ice cubes' pieces got a kitchen picture
        self.assertTrue(all(s["fallback"] and not s["fallback_related"] for s in report["segments"][1:]))

    def test_wrong_final_length_is_refused(self):
        self.probe_override = lambda name: mock.Mock(returncode=0, stderr="", stdout=json.dumps(
            {"streams": [{"codec_type": "video", "width": 1080, "height": 1920}], "format": {"duration": str(self.total + 1)}})) if name == "broll.mp4" else None
        with self.assertRaises(ft.FootageError) as ctx:
            self.build(self.table())
        self.assertIn("long", str(ctx.exception))

    def test_wrong_final_size_is_refused(self):
        self.probe_override = lambda name: mock.Mock(returncode=0, stderr="", stdout=json.dumps(
            {"streams": [{"codec_type": "video", "width": 1920, "height": 1080}], "format": {"duration": str(self.total + ft.BROLL_TAIL_SECONDS)}})) if name == "broll.mp4" else None
        with self.assertRaises(ft.FootageError):
            self.build(self.table())


if __name__ == "__main__":
    unittest.main()
