#!/usr/bin/env python3
"""Fill the generated parts of STORYBOARD.md from scripts/*.json and work/<short>/<lang>/timeline.json.

The markdown keeps hand-written sections; only the blocks between <!-- AUTO:<short>:<part> --> and <!-- /AUTO --> are replaced:
  <part> = scenes (scene timings EN/DE with the on-screen content), en / de (narration with timecodes).
Run it after tools/build.py has voiced the scripts:  python3 tools/storyboard.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "STORYBOARD.md"

SCENE_NAMES = {
    "hook": "Hook (cover, frame 0)",
    "evidence": "Evidence: quotes from the postings",
    "pain": "The problem",
    "idea": "The idea",
    "arch": "Architecture, built step by step",
    "metrics": "Pilot targets (stamped ILLUSTRATIVE)",
    "proof": "Built before (REAL RESULT, from the CV)",
    "pilot": "A first pilot",
    "closing": "Closing card",
}


def tc(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def on_screen(labels: dict, key: str) -> str:
    L = labels
    if key == "hook":
        return " / ".join("".join(r["text"] for r in line) for line in L["hook"]["lines"]) + f" — {L['hook']['sub']}"
    if key == "evidence":
        return "; ".join(f"{c['role']}: {c['quote']}" for c in L["evidence"]["cards"])
    if key == "pain":
        p = L["pain"]
        extra = {"ruleOfTen": lambda: " · ".join(f"{c} {m}" for c, m in zip(p["columns"], p["multipliers"])),
                 "scattered": lambda: f"{p['center']} ← " + " · ".join(p["tiles"]),
                 "bottleneck": lambda: " · ".join(p["chips"]) + f"; {p['experts']} ← {p['flow']} ← {p['newcomers']}"}[p["kind"]]()
        return f"{p['title']}: {extra}"
    if key == "idea":
        return f"{L['idea']['kicker']}: {L['idea']['title']} ({L['idea']['sub']})"
    if key == "arch":
        nodes = " → ".join(n["title"] for n in L["arch"]["nodes"])
        return f"{nodes}; badges: " + " · ".join(b["text"] for b in L["arch"]["badges"])
    if key == "metrics":
        m = L["metrics"]
        items = "; ".join(f"{i['label']}: {i['before']} → {i['after']} {i['unit']}".strip() for i in m["items"])
        return f"[{m['stamp']}] {items} — {m['footnote']}"
    if key == "proof":
        p = L["proof"]
        return f"[{p['badge']}] {p['title']}: " + "; ".join(f"{f['value']} {f['label']}" for f in p["facts"]) + f" — {p['source']}"
    if key == "pilot":
        return f"{L['pilot']['title']}: " + " · ".join(L["pilot"]["items"])
    if key == "closing":
        c = L["closing"]
        return f"{c['name']} — {c['role']} — {c['link']} ({c['note']} · {c['voiceNote']})"
    return ""


def scene_windows(timeline: dict) -> list[tuple[str, float, float]]:
    out: list[list] = []
    for ln in timeline["lines"]:
        if out and out[-1][0] == ln["scene"]:
            continue
        out.append([ln["scene"], ln["start"] if out else 0.0, 0.0])
    for a, b in zip(out, out[1:]):
        a[2] = b[1]
    out[-1][2] = timeline["totalSeconds"]
    return [tuple(x) for x in out]


def scenes_block(short: str) -> str:
    script = json.loads((ROOT / "scripts" / f"{short}.json").read_text())
    tl = {lang: json.loads((ROOT / "work" / short / lang / "timeline.json").read_text()) for lang in ("en", "de")}
    win = {lang: {k: (s, e) for k, s, e in scene_windows(tl[lang])} for lang in ("en", "de")}
    rows = ["| # | Scene | EN | DE | On screen (EN labels; DE uses the German labels) |", "|---|---|---|---|---|"]
    for i, (key, _, _) in enumerate(scene_windows(tl["en"]), 1):
        en, de = win["en"][key], win["de"][key]
        rows.append(f"| {i} | {SCENE_NAMES[key]} | {tc(en[0])}–{tc(en[1])} | {tc(de[0])}–{tc(de[1])} | {on_screen(script['en']['labels'], key)} |")
    rows.append("")
    rows.append(f"Length: **EN {tl['en']['totalSeconds']:.1f} s**, **DE {tl['de']['totalSeconds']:.1f} s** (narration plus a {tl['en']['totalSeconds'] - tl['en']['audioSeconds']:.1f} s hold on the closing card).")
    return "\n".join(rows)


def script_block(short: str, lang: str) -> str:
    tl = json.loads((ROOT / "work" / short / lang / "timeline.json").read_text())
    lines = []
    for ln in tl["lines"]:
        lines.append(f"{ln['i'] + 1}. `{tc(ln['start'])}–{tc(ln['end'])}` *({ln['scene']})* {ln['text']}")
    words = sum(len(ln["words"]) for ln in tl["lines"])
    lines.append("")
    lines.append(f"{words} words, {tl['audioSeconds']:.1f} s of narration. Voice: `{tl['engine']}`.")
    return "\n".join(lines)


def main() -> int:
    text = DOC.read_text(encoding="utf-8")

    def fill(m: re.Match) -> str:
        short, part = m.group(1), m.group(2)
        body = scenes_block(short) if part == "scenes" else script_block(short, part)
        return f"<!-- AUTO:{short}:{part} -->\n{body}\n<!-- /AUTO -->"

    new = re.sub(r"<!-- AUTO:(short\d):(scenes|en|de) -->.*?<!-- /AUTO -->", fill, text, flags=re.S)
    DOC.write_text(new, encoding="utf-8")
    print(f"updated {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
