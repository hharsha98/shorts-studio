#!/usr/bin/env python3
"""Scan a company YAML plus compiled labels and voice lines for banned words.

  ~/.venvs/kokoro/bin/python tools/banned_word_check.py companies/sportradar.yaml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from template.compile import compile_problem, load_config, photo_map  # noqa: E402
from template.copy import FORBIDDEN  # noqa: E402

# Extra terms the application Shorts must never show or say.
EXTRA = (
    "siplace",
    "smt-maschine",
    "smt maschine",
    "smt-maschinen",
    "smt machines",
    r"\bsmt\b",
    "gehalt",
    "salary",
    "sprachniveau",
    "deutschkenntnisse",
    r"\bcefr\b",
    "german level",
    "german cefr",
    "azure",
    "12-agent",
    "12 agents",
    "12 llm agents",
)


def _walk(obj) -> str:
    if isinstance(obj, str):
        return obj + "\n"
    if isinstance(obj, dict):
        return "".join(_walk(v) for v in obj.values())
    if isinstance(obj, list):
        return "".join(_walk(v) for v in obj)
    return ""


def _hits(blob: str) -> list[str]:
    low = blob.lower()
    found = []
    for raw in list(FORBIDDEN) + list(EXTRA):
        if raw.startswith(r"\b") or any(ch in raw for ch in r".*+?[]()"):
            if re.search(raw, low, flags=re.I):
                found.append(raw)
        elif raw.lower() in low:
            found.append(raw)
    return sorted(set(found))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("config", type=Path)
    args = ap.parse_args(argv)
    config = load_config(args.config)
    yaml_text = args.config.read_text(encoding="utf-8")
    yaml_hits = _hits(yaml_text)
    compiled_hits: list[str] = []
    scenes: list[str] = []
    for i, problem in enumerate(config["problems"]):
        for lang in ("en", "de"):
            compiled = compile_problem(config, problem, i, lang, photos={}, logo="")
            blob = _walk(compiled["labels"]) + _walk(compiled["lines"])
            compiled_hits.extend(_hits(blob))
            scenes.append(f"{problem.get('slug')}/{lang}: " + ", ".join(ln["scene"] for ln in compiled["lines"]))
    all_hits = sorted(set(yaml_hits + compiled_hits))
    report = {
        "config": str(args.config),
        "yaml_hits": yaml_hits,
        "compiled_hits": sorted(set(compiled_hits)),
        "scenes": scenes,
        "pass": not all_hits,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if all_hits:
        print(f"FAIL: banned words {all_hits}", file=sys.stderr)
        return 1
    print("PASS: no banned words in YAML, labels, or voice lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
