"""Unit tests for the English Kokoro voice: voice-en/server.py (its helpers and its HTTP layer with a fake engine, no model needed),
the pieces of voice-de/server.py it shares (still right for German), the routing in studio/voices.json, and the per-language
start hint in studio/make_video.py. The model itself is never loaded here; the running server is checked by hand (see voice-en/README.md).

Run from /Users/harsha/shorts-studio:
    python3 -m unittest discover -s studio/tests -t .
"""

import array
import contextlib
import http.client
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest import mock

STUDIO_DIR = Path(__file__).resolve().parent.parent
ROOT = STUDIO_DIR.parent
sys.path.insert(0, str(STUDIO_DIR))

import make_video as mv  # noqa: E402
import voice_take as vt  # noqa: E402
from studio.tests.test_voice_take import LINES, FakeVoice, TmpDirTest, tone  # noqa: E402

FULL = " ".join(LINES)
EN_URL = "http://127.0.0.1:3911"
EN_HINT = "voice-en/run.sh start"


def load_module(name: str, relative: str):
    """A file in a folder with a hyphen in its name, as a module (the normal import cannot do that)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


de = sys.modules.get("voice_de_server") or load_module("voice_de_server", "voice-de/server.py")
en = load_module("voice_en_server", "voice-en/server.py")


def request_body(**fields) -> bytes:
    return json.dumps(fields).encode("utf-8")


# --------------------------------------------------------------------------------------
# English sentence cutting
# --------------------------------------------------------------------------------------


class EnglishSentenceSplitTests(unittest.TestCase):
    def test_splits_at_full_stop_question_mark_exclamation_and_ellipsis(self):
        text = "That is one. Is that two? Three! And four... Five."
        self.assertEqual(en.split_sentences(text), ["That is one.", "Is that two?", "Three!", "And four...", "Five."])

    def test_e_g_does_not_split(self):
        self.assertEqual(en.split_sentences("Use a fan, e.g. a small one. It helps."), ["Use a fan, e.g. a small one.", "It helps."])
        self.assertEqual(en.split_sentences("Some metals, i.e. iron, rust. Gold does not."), ["Some metals, i.e. iron, rust.", "Gold does not."])

    def test_u_s_does_not_split(self):
        self.assertEqual(en.split_sentences("The U.S. economy grew. Then it fell."), ["The U.S. economy grew.", "Then it fell."])
        self.assertEqual(en.split_sentences("Made in the U.K. by hand. Nice."), ["Made in the U.K. by hand.", "Nice."])

    def test_titles_and_common_abbreviations_do_not_split(self):
        self.assertEqual(en.split_sentences("Mr. Smith left. Then Mrs. Jones came."), ["Mr. Smith left.", "Then Mrs. Jones came."])
        self.assertEqual(en.split_sentences("Dr. Lee and Prof. Kay agree. Fine."), ["Dr. Lee and Prof. Kay agree.", "Fine."])
        self.assertEqual(en.split_sentences("Cats, dogs, etc. are pets. Yes."), ["Cats, dogs, etc. are pets.", "Yes."])
        self.assertEqual(en.split_sentences("Cats vs. dogs is old. Next."), ["Cats vs. dogs is old.", "Next."])
        self.assertEqual(en.split_sentences("We meet at 5 p.m. tomorrow. Bring tea."), ["We meet at 5 p.m. tomorrow.", "Bring tea."])

    def test_decimal_numbers_and_prices_do_not_split(self):
        self.assertEqual(en.split_sentences("It is 3.5 degrees warmer. Fine."), ["It is 3.5 degrees warmer.", "Fine."])
        self.assertEqual(en.split_sentences("Pi is 3.14159 and tea costs $2.50 today. Done."), ["Pi is 3.14159 and tea costs $2.50 today.", "Done."])
        self.assertEqual(en.split_sentences("Version 2.0 is out."), ["Version 2.0 is out."])

    def test_a_sentence_ending_in_a_letter_still_splits(self):
        self.assertEqual(en.split_sentences("That is Vitamin C. Then comes D."), ["That is Vitamin C.", "Then comes D."])

    def test_a_sentence_ending_in_a_word_that_is_no_abbreviation_splits(self):
        self.assertEqual(en.split_sentences("Heat moves out. Cold stays in."), ["Heat moves out.", "Cold stays in."])

    def test_closing_quote_stays_with_its_sentence(self):
        self.assertEqual(en.split_sentences('He said, "No." Then he left.'), ['He said, "No."', "Then he left."])
        self.assertEqual(en.split_sentences("He said, “No.” Then he left."), ["He said, “No.”", "Then he left."])

    def test_line_breaks_and_double_spaces_become_single_spaces(self):
        self.assertEqual(en.split_sentences("One.\n\nTwo   three.\nFour."), ["One.", "Two three.", "Four."])

    def test_each_narrator_has_its_own_abbreviation_list(self):
        # German (the default of the shared helper) keeps "ca." and does not know "Mr."; English is the other way round
        self.assertEqual(de.split_sentences("Das sind ca. 5 Meter. Gut."), ["Das sind ca. 5 Meter.", "Gut."])
        self.assertEqual(de.split_sentences("Mr. Smith left. Gut."), ["Mr.", "Smith left.", "Gut."])
        self.assertEqual(en.split_sentences("Mr. Smith left. Good."), ["Mr. Smith left.", "Good."])
        self.assertNotIn("bzw", en.ABBREVIATIONS)
        self.assertNotIn("mr", de.ABBREVIATIONS)

    def test_the_real_english_scripts_split_into_their_lines_or_more(self):
        scripts = [p for p in sorted((ROOT / "content").glob("*/script.json")) if json.loads(p.read_text(encoding="utf-8")).get("language") == "en"]
        if not scripts:
            self.skipTest("no English scripts in content/")
        for path in scripts:
            lines = [line["text"].strip() for line in json.loads(path.read_text(encoding="utf-8"))["lines"]]
            sentences = en.split_sentences(" ".join(lines))
            self.assertGreaterEqual(len(sentences), len(lines), path.parent.name)
            self.assertEqual(" ".join(sentences), " ".join(lines), path.parent.name)  # nothing lost, nothing added
            self.assertTrue(all(len(s) <= de.MAX_PIECE_CHARS for s in sentences), path.parent.name)


class EnglishPiecePlanTests(unittest.TestCase):
    def test_pauses_are_the_german_ones_and_the_last_piece_has_none(self):
        plan = en.plan_pieces("One. Is that two? Three! Four...")
        self.assertEqual([p for p, _ in plan], ["One.", "Is that two?", "Three!", "Four..."])
        self.assertEqual([pause for _, pause in plan], [0.30, 0.35, 0.30, 0.0])

    def test_abbreviations_stay_inside_their_piece(self):
        self.assertEqual([p for p, _ in en.plan_pieces("Mr. Smith, e.g. a baker, left. Bye.")], ["Mr. Smith, e.g. a baker, left.", "Bye."])

    def test_the_pause_after_a_sentence_is_longer_than_voice_takes_silence_search(self):
        self.assertGreater(de.SENTENCE_PAUSE_S, vt.SILENCE_MIN_S)


class GermanIsStillGerman(unittest.TestCase):
    """The shared helpers got optional arguments; with none given they behave as before."""

    def test_german_defaults_for_splitting_and_planning(self):
        self.assertEqual(de.split_sentences("Es geht um Wellen, d. h. um Schall. Ende."), ["Es geht um Wellen, d. h. um Schall.", "Ende."])
        self.assertEqual([p for p, _ in de.plan_pieces("Eins. Ist das zwei? Drei!")], ["Eins.", "Ist das zwei?", "Drei!"])

    def test_german_request_check_takes_thorsten_only(self):
        self.assertEqual(de.parse_request(request_body(input="Hallo.", voice="thorsten"))["text"], "Hallo.")
        with self.assertRaises(de.RequestError) as caught:
            de.parse_request(request_body(input="Hallo.", voice="af_heart"))
        self.assertIn("thorsten", str(caught.exception))

    def test_german_profile_and_defaults(self):
        self.assertEqual(de.GERMAN, de.Profile("thorsten-kokoro", "thorsten", de.ABBREVIATIONS, "ThorstenVoice/1"))
        self.assertEqual((de.MODEL_NAME, de.VOICE_NAME, de.DEFAULT_PORT), ("thorsten-kokoro", "thorsten", 3910))

    def test_english_server_shares_the_german_code_and_the_same_audio_format(self):
        self.assertIs(en.shared, de)
        self.assertIs(en.RequestError, de.RequestError)
        self.assertEqual(en.SAMPLE_RATE, 24000)
        self.assertEqual((en.MODEL_NAME, en.VOICE_NAME, en.DEFAULT_PORT), ("kokoro-en-af_heart", "af_heart", 3911))
        self.assertEqual(en.ENGLISH.abbreviations, en.ABBREVIATIONS)
        self.assertEqual(en.HOST, "127.0.0.1")


# --------------------------------------------------------------------------------------
# The request check for the English voice
# --------------------------------------------------------------------------------------


class EnglishParseRequestTests(unittest.TestCase):
    def refused(self, raw: bytes):
        with self.assertRaises(en.RequestError) as caught:
            en.parse_request(raw)
        return caught.exception

    def test_af_heart_is_accepted_in_any_case_and_the_voice_may_be_left_out(self):
        for voice in ("af_heart", "AF_Heart", " af_heart ", "", None):
            self.assertEqual(en.parse_request(request_body(input="Hi.", voice=voice))["text"], "Hi.", voice)
        self.assertEqual(en.parse_request(request_body(input="Hi.")), {"text": "Hi.", "speed": 1.0, "seed": None})

    def test_full_request_like_voice_take_sends_it(self):
        body = request_body(input="Hi.", voice="af_heart", response_format="wav", seed=3, speed=1.1, instructions="ignored")
        self.assertEqual(en.parse_request(body), {"text": "Hi.", "speed": 1.1, "seed": 3})

    def test_other_voices_are_refused_and_the_error_names_the_english_one(self):
        for voice in ("thorsten", "Ryan", "am_michael", 5):
            error = self.refused(request_body(input="Hi.", voice=voice))
            self.assertEqual(error.status, 400, voice)
            self.assertIn("af_heart", str(error))
        self.assertNotIn("thorsten", str(self.refused(request_body(input="Hi.", voice="Ryan"))))

    def test_format_speed_and_text_checks_are_the_german_ones(self):
        self.assertEqual(self.refused(request_body(input="Hi.", response_format="mp3")).status, 400)
        self.assertEqual(self.refused(request_body(input="Hi.", speed=9)).status, 400)
        self.assertEqual(self.refused(request_body(input="… !")).status, 422)
        self.assertEqual(self.refused(request_body(input="a" * de.MAX_INPUT_CHARS)).status, 400)
        self.assertEqual(self.refused(b"{nope").status, 400)


# --------------------------------------------------------------------------------------
# The HTTP layer (shared code, English profile, fake engine)
# --------------------------------------------------------------------------------------


class FakeEngine:
    def __init__(self):
        self.calls = []

    def speak(self, piece, speed=1.0):
        self.calls.append(piece)
        return tone(0.2)


class HttpServer:
    """A server for `make` (a function that takes the fake engine) on a free port, stopped at cleanup."""

    def __init__(self, test: unittest.TestCase, make):
        self.engine = FakeEngine()
        self.server = make(self.engine)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        test.addCleanup(thread.join, 5)
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                conn.request(method, path, body=body, headers=headers or {})
                resp = conn.getresponse()
                return resp.status, resp.getheader("Content-Type"), resp.getheader("Server"), resp.read()
        finally:
            conn.close()

    def post(self, payload):
        return self.call("POST", "/v1/audio/speech", json.dumps(payload).encode(), {"Content-Type": "application/json"})


class HealthPerEngineTests(unittest.TestCase):
    def test_each_engine_reports_its_own_model_name(self):
        english = HttpServer(self, lambda engine: en.make_server(engine, 0))
        german = HttpServer(self, lambda engine: de.make_server(engine, 0))
        self.assertEqual(json.loads(english.call("GET", "/health")[3]), {"status": "ok", "model": "kokoro-en-af_heart"})
        self.assertEqual(json.loads(german.call("GET", "/health")[3]), {"status": "ok", "model": "thorsten-kokoro"})
        self.assertIn("Kokoro", english.call("GET", "/health")[2])
        self.assertIn("Thorsten", german.call("GET", "/health")[2])

    def test_the_english_server_listens_on_this_computer_only(self):
        server = en.make_server(FakeEngine(), 0)
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_address[0], "127.0.0.1")


class EnglishHttpTests(unittest.TestCase):
    def setUp(self):
        self.http = HttpServer(self, lambda engine: en.make_server(engine, 0))

    def test_speech_returns_a_wav_with_the_pause_between_sentences(self):
        status, ctype, _server, body = self.http.post({"input": "First one. Second one?", "voice": "af_heart", "response_format": "wav", "seed": 5})
        self.assertEqual((status, ctype), (200, "audio/wav"))
        with wave.open(io.BytesIO(body)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (24000, 1, 2))
            self.assertAlmostEqual(w.getnframes() / 24000, 0.2 + 0.30 + 0.2, places=3)
        self.assertEqual(self.http.engine.calls, ["First one.", "Second one?"])

    def test_the_english_abbreviations_reach_the_engine_as_one_piece(self):
        self.http.post({"input": "Mr. Smith, e.g. a baker, left. Bye."})
        self.assertEqual(self.http.engine.calls, ["Mr. Smith, e.g. a baker, left.", "Bye."])

    def test_the_german_voice_is_refused_by_the_english_server(self):
        status, ctype, _server, body = self.http.post({"input": "Hi.", "voice": "thorsten"})
        self.assertEqual((status, ctype), (400, "application/json"))
        self.assertIn("af_heart", json.loads(body)["error"])
        self.assertEqual(self.http.engine.calls, [])

    def test_the_english_voice_is_refused_by_the_german_server(self):
        german = HttpServer(self, lambda engine: de.make_server(engine, 0))
        status, _ctype, _server, body = german.post({"input": "Hallo.", "voice": "af_heart"})
        self.assertEqual(status, 400)
        self.assertIn("thorsten", json.loads(body)["error"])


# --------------------------------------------------------------------------------------
# Trimming the model's padding, repeatable overlap-add, finding the model
# --------------------------------------------------------------------------------------


def samples(*parts):
    """array('h') from (amplitude, seconds) parts at 24 kHz."""
    out = array.array("h")
    for amplitude, seconds in parts:
        out.extend([amplitude] * round(seconds * 24000))
    return out


class TrimSilenceTests(unittest.TestCase):
    def test_padding_before_and_after_the_speech_is_cut_but_a_little_quiet_stays(self):
        piece = samples((0, 0.30), (5, 0.20), (3000, 1.0), (8, 0.50))
        trimmed = en.trim_silence(piece)
        keep = round(en.TRIM_KEEP_S * 24000)
        self.assertEqual(len(trimmed), round(1.0 * 24000) + 2 * keep)
        self.assertEqual(trimmed[keep], 3000)  # the speech starts exactly `keep` samples in
        self.assertEqual(trimmed[-keep - 1], 3000)  # ... and ends `keep` samples before the end

    def test_quiet_inside_the_speech_is_kept(self):
        piece = samples((0, 0.3), (3000, 0.2), (0, 0.4), (3000, 0.2), (0, 0.3))
        trimmed = en.trim_silence(piece)
        keep = round(en.TRIM_KEEP_S * 24000)
        self.assertEqual(len(trimmed), round((0.2 + 0.4 + 0.2) * 24000) + 2 * keep)

    def test_a_piece_that_never_gets_loud_or_is_empty_is_returned_as_it_is(self):
        quiet = samples((5, 0.5))
        self.assertEqual(en.trim_silence(quiet), quiet)
        self.assertEqual(en.trim_silence(array.array("h")), array.array("h"))

    def test_nothing_is_cut_when_the_speech_runs_to_the_edges(self):
        loud = samples((3000, 0.5))
        self.assertEqual(en.trim_silence(loud), loud)

    def test_the_gap_between_two_trimmed_pieces_is_about_the_planned_pause(self):
        padded = samples((0, 0.30), (3000, 0.5), (4, 0.55))
        joined = de.join_pieces([en.trim_silence(padded), en.trim_silence(padded)], [de.SENTENCE_PAUSE_S, 0.0])
        keep = round(en.TRIM_KEEP_S * 24000)
        gap = 2 * keep + round(de.SENTENCE_PAUSE_S * 24000)
        first_speech_end = keep + round(0.5 * 24000)
        self.assertLess(max(abs(v) for v in joined[first_speech_end:first_speech_end + gap]), en.TRIM_LEVEL)
        self.assertLess(gap / 24000, 0.40)  # not the 1.1 s the untrimmed model output gave


class FakeMlx:
    cpu = "the-cpu"

    def __init__(self):
        self.entered = []

    def stream(self, device):
        outer = self

        class Context:
            def __enter__(self):
                outer.entered.append(device)

            def __exit__(self, *exc):
                return False

        return Context()


class RepeatableOverlapAddTests(unittest.TestCase):
    def test_istft_is_wrapped_to_run_on_the_cpu_stream(self):
        mx, calls = FakeMlx(), []
        istftnet = type("Module", (), {})()
        istftnet.istft = lambda *a, **kw: calls.append((a, kw)) or "audio"
        en.make_overlap_add_repeatable(istftnet, mx)
        self.assertEqual(istftnet.istft(1, 2, window="hann"), "audio")
        self.assertEqual(calls, [((1, 2), {"window": "hann"})])
        self.assertEqual(mx.entered, ["the-cpu"])

    def test_wrapping_twice_does_not_nest(self):
        mx = FakeMlx()
        istftnet = type("Module", (), {})()
        istftnet.istft = lambda *a, **kw: "audio"
        en.make_overlap_add_repeatable(istftnet, mx)
        first = istftnet.istft
        en.make_overlap_add_repeatable(istftnet, mx)
        self.assertIs(istftnet.istft, first)
        istftnet.istft()
        self.assertEqual(len(mx.entered), 1)

    def test_a_changed_mlx_audio_without_istft_stops_the_server_instead_of_losing_repeatability(self):
        with self.assertRaises(RuntimeError) as caught:
            en.make_overlap_add_repeatable(type("Module", (), {})(), FakeMlx())
        self.assertIn("istft", str(caught.exception))
        self.assertIn("repeatable", str(caught.exception))


class FindModelTests(TmpDirTest):
    def snapshot(self, name, files=en.MODEL_FILES, mtime=None):
        folder = self.tmp / "models--mlx-community--Kokoro-82M-bf16" / "snapshots" / name
        for relative in files:
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        if mtime is not None:
            os.utime(folder, (mtime, mtime))
        return folder

    def test_finds_the_complete_snapshot(self):
        folder = self.snapshot("abc123")
        self.assertEqual(en.find_model_dir(self.tmp), folder)

    def test_prefers_the_newest_complete_snapshot_and_skips_an_incomplete_newer_one(self):
        old = self.snapshot("old", mtime=1_000_000)
        self.snapshot("new-but-broken", files=("config.json",), mtime=2_000_000)
        self.assertEqual(en.find_model_dir(self.tmp), old)
        newest = self.snapshot("newest", mtime=3_000_000)
        self.assertEqual(en.find_model_dir(self.tmp), newest)

    def test_no_cache_says_where_the_model_comes_from(self):
        with self.assertRaises(FileNotFoundError) as caught:
            en.find_model_dir(self.tmp)
        message = str(caught.exception)
        self.assertIn("mlx-community/Kokoro-82M-bf16", message)
        self.assertIn("VoiceStudio", message)
        self.assertIn("never downloads", message)

    def test_an_incomplete_snapshot_names_the_missing_files(self):
        self.snapshot("partial", files=("config.json", "kokoro-v1_0.safetensors"))
        with self.assertRaises(FileNotFoundError) as caught:
            en.find_model_dir(self.tmp)
        self.assertIn("voices/af_heart.safetensors", str(caught.exception))
        self.assertNotIn("missing config.json", str(caught.exception))

    def test_the_cache_folder_follows_the_hugging_face_variables(self):
        with mock.patch.dict(os.environ, {"HF_HUB_CACHE": str(self.tmp / "hub")}):
            self.assertEqual(en.hub_cache_dir(), self.tmp / "hub")
        env = {key: value for key, value in os.environ.items() if key != "HF_HUB_CACHE"}
        env["HF_HOME"] = str(self.tmp / "hf")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(en.hub_cache_dir(), self.tmp / "hf" / "hub")


# --------------------------------------------------------------------------------------
# Files: run script, git-ignore
# --------------------------------------------------------------------------------------


class ServerFilesTests(unittest.TestCase):
    def test_run_script_is_valid_bash_and_executable(self):
        script = ROOT / "voice-en" / "run.sh"
        self.assertTrue(script.stat().st_mode & 0o100, "run.sh is not executable")
        self.assertEqual(subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True).returncode, 0)

    def test_run_script_explains_its_usage_for_an_unknown_word(self):
        proc = subprocess.run([str(ROOT / "voice-en" / "run.sh"), "bogus"], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        for word in ("start", "stop", "restart", "status"):
            self.assertIn(word, proc.stdout)

    def test_run_script_uses_the_port_of_the_server_and_of_voices_json_and_stays_offline(self):
        text = (ROOT / "voice-en" / "run.sh").read_text(encoding="utf-8")
        self.assertIn(f"PORT={en.DEFAULT_PORT}\n", text)
        self.assertIn("HF_HUB_OFFLINE=1", text)
        self.assertIn("VoiceStudio/runtime/project/.venv/bin/python", text)
        self.assertEqual(json.loads((STUDIO_DIR / "voices.json").read_text(encoding="utf-8"))["en"]["engine_url"], f"http://127.0.0.1:{en.DEFAULT_PORT}")

    def test_run_script_tells_what_is_missing_in_plain_english(self):
        text = (ROOT / "voice-en" / "run.sh").read_text(encoding="utf-8")
        self.assertIn("VoiceStudio must be installed", text)
        self.assertIn("Kokoro model files are missing", text)

    def test_pid_and_log_files_are_ignored_by_git(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for entry in ("voice-en/server.pid", "voice-en/server.log"):
            self.assertIn(entry, ignored)

    def test_the_readme_names_the_licences(self):
        text = (ROOT / "voice-en" / "README.md").read_text(encoding="utf-8")
        for word in ("Apache-2.0", "MIT", "espeak", "GPL", "VoiceStudio"):
            self.assertIn(word, text)


# --------------------------------------------------------------------------------------
# studio/voices.json routing
# --------------------------------------------------------------------------------------


class VoicesJsonRoutingTests(unittest.TestCase):
    def setUp(self):
        self.voices = json.loads((STUDIO_DIR / "voices.json").read_text(encoding="utf-8"))

    def test_english_uses_the_kokoro_engine_with_one_take(self):
        cfg = self.voices["en"]
        self.assertEqual(cfg["voice"], "af_heart")
        self.assertEqual(cfg["engine_url"], EN_URL)
        self.assertEqual(mv.voice_engine_url(cfg), EN_URL)
        self.assertIs(cfg["deterministic"], True)
        self.assertEqual(cfg["start_hint"], EN_HINT)
        self.assertEqual(cfg["max_ref_st"], 2.0)
        self.assertEqual(cfg["ref_sample"], "studio/voice-tests/en-kokoro-af_heart.wav")
        self.assertNotIn("instructions", cfg)  # an own engine gets none
        self.assertIsInstance(cfg["ref_f0_hz"], float)
        self.assertTrue(80 <= cfg["ref_f0_hz"] <= 300)

    def test_german_is_unchanged(self):
        self.assertEqual(self.voices["de"], {"voice": "thorsten", "engine_url": "http://127.0.0.1:3910", "deterministic": True,
                                             "ref_f0_hz": 160.8, "ref_sample": "studio/voice-tests/de-thorsten.wav"})

    def test_the_two_engines_use_two_ports(self):
        self.assertNotEqual(mv.voice_engine_url(self.voices["en"]), mv.voice_engine_url(self.voices["de"]))

    def test_the_note_says_what_changed(self):
        note = self.voices["_note"]
        self.assertIn("voice-en/run.sh start", note)
        self.assertIn("Kokoro af_heart", note)

    def test_the_reference_sample_exists_when_the_samples_folder_does(self):
        sample = ROOT / self.voices["en"]["ref_sample"]
        if not sample.parent.is_dir():
            self.skipTest("studio/voice-tests/ is not here (it is git-ignored)")
        self.assertTrue(sample.is_file(), f"{sample} is missing: voice the fridge text with voice-en/run.sh start and save it there")


class ReferenceSampleTests(TmpDirTest):
    """voice_take.py refs measures the file named by ref_sample (the English sample is not called en-af_heart.wav)."""

    def run_refs(self, voices):
        voices_file = self.tmp / "voices.json"
        voices_file.write_text(json.dumps(voices), encoding="utf-8")
        tests_dir = self.tmp / "voice-tests"
        tests_dir.mkdir()
        for name in ("en-kokoro-af_heart.wav", "de-thorsten.wav", "fr-amelie.wav"):
            (tests_dir / name).write_bytes(b"x")
        measured = []
        with mock.patch.object(vt, "measure_pitch_file", side_effect=lambda path: measured.append(path.name) or (123.46, 0)):
            vt.store_reference_pitches(voices_file, tests_dir, log=lambda m: None)
        return json.loads(voices_file.read_text(encoding="utf-8")), measured

    def test_the_named_sample_is_measured(self):
        voices, measured = self.run_refs({"_note": "x", "en": {"voice": "af_heart", "ref_sample": "studio/voice-tests/en-kokoro-af_heart.wav"}})
        self.assertEqual(measured, ["en-kokoro-af_heart.wav"])
        self.assertEqual(voices["en"]["ref_f0_hz"], 123.5)
        self.assertEqual(voices["en"]["ref_sample"], "studio/voice-tests/en-kokoro-af_heart.wav")
        self.assertEqual(voices["_note"], "x")

    def test_without_ref_sample_the_old_file_name_is_used(self):
        voices, measured = self.run_refs({"de": {"voice": "thorsten"}, "fr": {"voice": "amelie", "ref_sample": "  "}})
        self.assertEqual(measured, ["de-thorsten.wav", "fr-amelie.wav"])
        self.assertEqual(voices["de"]["ref_sample"], "studio/voice-tests/de-thorsten.wav")


# --------------------------------------------------------------------------------------
# make_video.py: the start hint per language
# --------------------------------------------------------------------------------------


class StartHintTests(TmpDirTest):
    def test_the_hint_comes_from_voices_json_else_from_the_language(self):
        self.assertEqual(mv.voice_start_hint({"start_hint": EN_HINT}, "en"), EN_HINT)
        self.assertEqual(mv.voice_start_hint({"start_hint": "  tools/go.sh  "}, "en"), "tools/go.sh")
        self.assertEqual(mv.voice_start_hint({}, "de"), "voice-de/run.sh start")
        self.assertEqual(mv.voice_start_hint({}, "en"), EN_HINT)
        for cfg in ({"start_hint": ""}, {"start_hint": "   "}, {"start_hint": 5}, {"start_hint": None}, None, "x"):
            self.assertEqual(mv.voice_start_hint(cfg, "en"), EN_HINT, cfg)

    def test_the_real_voices_json_gives_each_language_its_own_launcher(self):
        self.assertEqual(mv.configured_start_hint("en"), "voice-en/run.sh start")
        self.assertEqual(mv.configured_start_hint("de"), "voice-de/run.sh start")
        self.assertEqual(mv.configured_start_hint("fr"), "voice-fr/run.sh start")  # no entry: the default

    def test_a_missing_or_broken_voices_json_gives_the_default(self):
        broken = self.tmp / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        for path in (broken, self.tmp / "missing.json"):
            with mock.patch.object(mv, "VOICES_FILE", path):
                self.assertEqual(mv.configured_start_hint("en"), EN_HINT)

    def test_the_old_constant_is_gone(self):
        self.assertFalse(hasattr(mv, "ENGINE_START_HINT"))


class EnginePreflightTests(TmpDirTest):
    def run_check(self, language, answer, start_hint=None):
        def fake(url, path, timeout=10):
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(mv, "engine_get_json", side_effect=fake):
            try:
                return mv.check_voice_engine("http://127.0.0.1:3911", language, start_hint)
            except mv.GateError as exc:
                return exc

    def test_an_unreachable_english_engine_says_to_start_voice_en(self):
        error = self.run_check("en", urllib.error.URLError("Connection refused"), EN_HINT)
        self.assertIsInstance(error, mv.GateError)
        message = str(error)
        self.assertIn("The English voice engine", message)
        self.assertIn("start it: voice-en/run.sh start", message)
        self.assertNotIn("voice-de", message)

    def test_a_default_hint_follows_the_language(self):
        self.assertIn("start it: voice-en/run.sh start", str(self.run_check("en", urllib.error.URLError("refused"))))
        self.assertIn("start it: voice-de/run.sh start", str(self.run_check("de", urllib.error.URLError("refused"))))

    def test_an_engine_that_does_not_say_ok_gets_a_restart_hint_for_its_own_launcher(self):
        message = str(self.run_check("en", {"status": "loading"}, EN_HINT))
        self.assertIn("did not say ok", message)
        self.assertIn("Restart it (voice-en/run.sh stop, then voice-en/run.sh start)", message)
        german = str(self.run_check("de", {"model": "x"}, "voice-de/run.sh start"))
        self.assertIn("Restart it (voice-de/run.sh stop, then voice-de/run.sh start)", german)

    def test_a_hint_that_is_not_a_start_command_still_reads_sensibly(self):
        message = str(self.run_check("en", {"status": "down"}, "open the Engines app"))
        self.assertIn("Restart it (stop it, then open the Engines app)", message)

    def test_a_good_engine_answer_is_returned(self):
        self.assertEqual(self.run_check("en", {"status": "ok", "model": "kokoro-en-af_heart"}, EN_HINT), {"status": "ok", "model": "kokoro-en-af_heart"})

    def test_full_preflight_for_english_checks_the_engine_and_never_the_qwen_engine(self):
        asked = []

        def fake_http_get_json(path, timeout=10):
            asked.append(path)
            return {"/health": {"status": "ok"}, "/engines/tts": {"active": "omnivoice", "active_model": "x"}, "/engines/asr": {"active": "faster-whisper"}}[path]

        def fake_engine_get_json(url, path, timeout=10):
            asked.append(url + path)
            return {"status": "ok", "model": "kokoro-en-af_heart"}

        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        with mock.patch.object(mv, "http_get_json", side_effect=fake_http_get_json), mock.patch.object(mv, "engine_get_json", side_effect=fake_engine_get_json), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            result = mv.preflight_voice_services(ctx, "en")  # the real studio/voices.json: en has an engine_url
        self.assertEqual(result, {"tts": {"active": "kokoro-en-af_heart", "active_model": "kokoro-en-af_heart"}, "asr_model": "faster-whisper", "engine_url": EN_URL})
        self.assertEqual(asked, ["/health", EN_URL + "/health", "/engines/asr"])
        self.assertIn("English", out.getvalue())

    def test_unreachable_engine_in_the_full_preflight_names_the_launcher_of_its_own_language(self):
        for language, hint in (("en", "voice-en/run.sh start"), ("de", "voice-de/run.sh start")):
            ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
            with mock.patch.object(mv, "http_get_json", return_value={"status": "ok"}), \
                    mock.patch.object(mv, "engine_get_json", side_effect=urllib.error.URLError("Connection refused")), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(mv.GateError) as caught:
                    mv.preflight_voice_services(ctx, language)
            self.assertIn(f"start it: {hint}", str(caught.exception), language)


class StartHintCheckInPreflightTests(TmpDirTest):
    """step_preflight checks "start_hint" in voices.json next to engine_url. Stopped at pitch_command, like the max_ref_st tests."""

    STOP = "stopped after the voices.json checks"

    def preflight(self, **voice_extra):
        path = self.tmp / "voices.json"
        path.write_text(json.dumps({"en": {"voice": "af_heart", "engine_url": EN_URL, "deterministic": True, "ref_f0_hz": 212.6, **voice_extra}}), encoding="utf-8")
        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        ctx.script = {"id": "x", "language": "en", "lines": []}
        services = {"tts": {"active": "kokoro-en-af_heart", "active_model": "kokoro-en-af_heart"}, "asr_model": "faster-whisper", "engine_url": EN_URL}
        with mock.patch.object(mv, "VOICES_FILE", path), mock.patch.object(mv, "find_tool", return_value="/bin/true"), \
                mock.patch.object(mv, "pick_media_scripts_dir", return_value=self.tmp), \
                mock.patch.object(mv, "preflight_voice_services", return_value=services), \
                mock.patch.object(mv.voice_take, "pitch_command", side_effect=vt.VoiceTakeError(self.STOP)), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(mv.GateError) as caught:
                mv.step_preflight(ctx)
        return str(caught.exception)

    def test_a_text_or_no_key_passes(self):
        self.assertEqual(self.preflight(), self.STOP)
        self.assertEqual(self.preflight(start_hint=EN_HINT), self.STOP)

    def test_empty_or_non_text_hints_are_refused_in_plain_english(self):
        for value in ("", "   ", 5, True, None, ["voice-en/run.sh start"]):
            message = self.preflight(start_hint=value)
            self.assertNotEqual(message, self.STOP, value)
            self.assertIn('"en".start_hint must be the text that starts the engine', message)
            self.assertIn(f"(got {value!r})", message)
            self.assertIn("Remove the key", message)


class EnglishVoiceStepTests(TmpDirTest):
    """The voice step for English now goes through the engine: one take, no instructions probe, the engine's start hint."""

    def run_step(self, fake, setup):
        made = {}

        def factory(url, voice, asr_model, language, instructions="", **kw):
            made.update(url=url, voice=voice, language=language, instructions=instructions, kw=kw)
            return fake

        ctx = mv.Ctx(mv.parse_args(["content/x/script.json"]))
        ctx.script = {"id": "x", "language": "en", "lines": [{"text": t, "visual": None} for t in LINES]}
        ctx.work = self.tmp / "work" / "x"
        ctx.report["voice"] = {}
        with mock.patch.object(mv.voice_take, "VoiceStudioBackend", side_effect=factory), mock.patch.object(mv, "WORK_ROOT", self.tmp / "work"), \
                mock.patch.object(mv, "find_tool", return_value="/bin/true"), contextlib.redirect_stdout(io.StringIO()) as out:
            take = mv.step_voice(ctx, setup)
        return take, made, out.getvalue(), ctx

    def english_setup(self, **cfg):
        merged = {"voice": "af_heart", "engine_url": EN_URL, "deterministic": True, "start_hint": EN_HINT, "ref_f0_hz": 150.0, **cfg}
        return {"voice_cfg": merged, "ref_f0": 150.0, "asr_model": "asr1", "tts_model": "kokoro-en-af_heart", "engine_url": EN_URL}

    def test_english_speaks_through_its_engine_with_one_take_and_no_probe(self):
        fake = FakeVoice()
        _take, made, printed, ctx = self.run_step(fake, self.english_setup())
        self.assertEqual(made["kw"], {"ffmpeg": "/bin/true", "mpt_dir": mv.MPT_DIR, "engine_url": EN_URL, "engine_start_hint": EN_HINT})
        self.assertEqual(made["url"], mv.VOICESTUDIO_URL)  # transcription is still VoiceStudio
        self.assertEqual((made["voice"], made["language"], made["instructions"]), ("af_heart", "en", ""))
        self.assertEqual(fake.synth_calls, [(FULL, 1)])
        self.assertFalse((self.tmp / "work" / "_voice_probe.json").exists())
        self.assertIn("ONE take", printed)
        self.assertEqual(ctx.report["voice"]["mode"], "one take")

    def test_the_hint_defaults_to_the_languages_launcher(self):
        setup = self.english_setup()
        del setup["voice_cfg"]["start_hint"]
        _take, made, _printed, _ctx = self.run_step(FakeVoice(), setup)
        self.assertEqual(made["kw"]["engine_start_hint"], EN_HINT)


if __name__ == "__main__":
    unittest.main()
