"""The shared proof card must stay built-first and free of banned words."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from template.compile import SCENE_ORDER, compile_problem, load_config
from template.copy import FORBIDDEN, LINKS, PROOF

ROOT = Path(__file__).resolve().parent.parent


class CopyTests(unittest.TestCase):
    def test_proof_names_the_plant_and_not_an_internal_project(self) -> None:
        for lang, card in PROOF.items():
            blob = json.dumps(card, ensure_ascii=False).lower()
            self.assertIn("siemens ag, amberg", card["kicker"].lower(), lang)
            self.assertIn("rag", blob)
            self.assertIn("16", blob)
            self.assertIn("73", blob)
            for banned in ("mara", "siplace", "smt", "gehalt", "salary"):
                self.assertNotIn(banned, blob, f"{lang} contains {banned!r}")

    def test_closing_links_are_short(self) -> None:
        self.assertEqual(len(LINKS), 4)
        self.assertTrue(any("github.com/hharsha98" == x for x in LINKS))
        self.assertTrue(any("huggingface.co/hharsha" == x for x in LINKS))
        for href in LINKS:
            self.assertLessEqual(len(href), 40)

    def test_forbidden_covers_nda_and_salary(self) -> None:
        low = " ".join(FORBIDDEN)
        self.assertIn("mara", low)
        self.assertIn("siplace", low)
        self.assertIn("gehalt", low)
        self.assertIn("azure", low)

    def test_lak_de_is_facts_only_and_skips_illustrative_metrics(self) -> None:
        cfg = load_config(ROOT / "companies" / "lak.yaml")
        out = compile_problem(cfg, cfg["problems"][0], 0, "de", {}, "")
        scenes = [ln["scene"] for ln in out["lines"]]
        self.assertNotIn("metrics", scenes)
        self.assertNotIn("pilot", scenes)
        self.assertEqual(out["labels"]["pain"]["kind"], "scattered")
        self.assertEqual(out["labels"]["closing"]["role"], "Konzept von")
        self.assertEqual(out["labels"]["closing"]["name"], "Hanumanthu Harsha Vardhan")
        self.assertEqual(out["labels"]["top"]["topic"], "AI Engineer – Industrielle KI")
        self.assertEqual(out["labels"]["evidence"]["cards"][2]["gist"], "Pilot, nicht Fertigung")
        self.assertEqual(out["brand"]["accent"], "#B9A36A")
        self.assertNotIn("Beispielwerte", out["labels"]["closing"]["note"])
        self.assertEqual(out["labels"]["closing"]["links"], LINKS)
        blob = " ".join(ln["text"] for ln in out["lines"]).lower()
        blob += " " + json.dumps(out["labels"], ensure_ascii=False).lower()
        for banned in ("mara", "siplace", "smt", "azure", "job posting", "stellenanzeige",
                       "beispielwerte", "illustrative", "gehalt", "cefr"):
            self.assertNotIn(banned, blob, banned)
        self.assertIn("siemens", blob)
        self.assertIn("indiamart", blob)

    def test_scene_order_keeps_the_rotpunkt_evidence_slot(self) -> None:
        self.assertEqual(
            SCENE_ORDER,
            ["hook", "evidence", "pain", "idea", "arch", "metrics", "proof", "pilot", "closing"],
        )

    def test_example_keeps_concept_by_role(self) -> None:
        cfg = load_config(ROOT / "companies" / "_example.yaml")
        out = compile_problem(cfg, cfg["problems"][0], 0, "en", {}, "")
        self.assertEqual(out["labels"]["closing"]["role"], "Concept by")

    def test_lucanet_en_sets_role_and_avoids_banned_words(self) -> None:
        cfg = load_config(ROOT / "companies" / "lucanet.yaml")
        out = compile_problem(cfg, cfg["problems"][0], 0, "en", {}, "")
        self.assertEqual(out["labels"]["closing"]["role"], "AI Solutions Engineer")
        self.assertEqual(out["labels"]["closing"]["name"], "Hanumanthu Harsha Vardhan")
        self.assertEqual(out["brand"]["accent"], "#9728FF")
        blob = " ".join(ln["text"] for ln in out["lines"]).lower()
        blob += " " + json.dumps(out["labels"], ensure_ascii=False).lower()
        for banned in ("mara", "siplace", "smt", "azure", "job posting", "stellenanzeige"):
            self.assertNotIn(banned, blob, banned)


if __name__ == "__main__":
    unittest.main()
