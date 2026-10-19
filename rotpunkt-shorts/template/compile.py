"""Turn a company YAML config into the script dict the Remotion Short already renders.

A new company needs only the YAML. Scene components, the Siemens proof card, safety badges and the closing card
are filled in here. Nothing in video/src has to change.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from template.copy import (
    ARCH_TITLE, AUTHOR, BADGES, CLOSING_LINE, CONCEPT, CREDIT, FORBIDDEN, FOR_LINE, GITHUB,
    METRICS_CHROME, NOT_OFFICIAL, PILOT_CHROME, PROOF, VOICE_NOTE,
)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCENE_ORDER = ["hook", "pain", "idea", "arch", "metrics", "proof", "pilot", "closing"]
STEP_ICONS = ["inbox", "agent", "db", "shield", "factory"]


class ConfigError(SystemExit):
    pass


def load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "company" not in data or "problems" not in data:
        raise ConfigError(f"{path}: need a 'company' block and a 'problems' list")
    problems = data["problems"]
    if not isinstance(problems, list) or not 1 <= len(problems) <= 2:
        raise ConfigError(f"{path}: 'problems' must be a list of 1 or 2 problems")
    return data


def text(value, lang: str, where: str) -> str:
    """A string, or {en, de}. The same string may be used for both languages."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict) and isinstance(value.get(lang), str) and value[lang].strip():
        return value[lang].strip()
    raise ConfigError(f"{where}: need text for '{lang}'")


def lines_of(value, lang: str, where: str) -> list[list[dict]]:
    """Hook lines. Each line is a string or a list of strings and {text, accent} runs."""
    if not isinstance(value, dict) or lang not in value:
        raise ConfigError(f"{where}: need hook lines for '{lang}'")
    raw = value[lang]
    if isinstance(raw, dict):
        raw = raw.get("lines")
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{where}: hook.{lang} must be a list of lines")
    out = []
    for i, line in enumerate(raw):
        runs = [line] if isinstance(line, str) else line
        parsed = []
        for run in runs:
            if isinstance(run, str):
                parsed.append({"text": run})
            elif isinstance(run, dict) and "text" in run:
                parsed.append({"text": str(run["text"]), "accent": bool(run.get("accent", False))})
            else:
                raise ConfigError(f"{where}: hook line {i + 1} has a run that is not text")
        out.append(parsed)
    return out


def _reject_forbidden(blob: str, where: str) -> None:
    low = blob.lower()
    hit = [w for w in FORBIDDEN if w in low]
    if hit:
        raise ConfigError(f"{where}: remove {hit[0]!r}. The Short is his own idea, not a reference to a job advert, and it has no 'AI idea sketch' label.")


def compile_problem(config: dict, problem: dict, index: int, lang: str, photos: dict[str, str], logo: str) -> dict:
    """One language of one problem: narration lines plus every on-screen label."""
    company = config["company"]
    name = text(company.get("name"), lang, "company.name")
    domain = text(company.get("domain"), lang, "company.domain")
    slug = str(problem.get("slug") or f"problem-{index + 1}")
    title = text(problem.get("title"), lang, f"{slug}.title")
    n = len(config["problems"])
    badge = f"{index + 1}/{n}" if n > 1 else "1"

    hook = problem.get("hook") or {}
    hook_lines = lines_of(hook, lang, f"{slug}.hook")
    hook_sub = text(hook.get("sub") if isinstance(hook, dict) else None, lang, f"{slug}.hook.sub") if isinstance(hook, dict) and hook.get("sub") else ""
    if isinstance(hook, dict) and isinstance(hook.get(lang), dict) and hook[lang].get("sub"):
        hook_sub = hook[lang]["sub"].strip()
    if not hook_sub and isinstance(hook, dict) and isinstance(hook.get("sub"), (str, dict)):
        hook_sub = text(hook["sub"], lang, f"{slug}.hook.sub")

    pain = problem.get("pain") or {}
    pain_title = text(pain.get("title"), lang, f"{slug}.pain.title")
    chips = _str_list(pain.get("chips"), lang, f"{slug}.pain.chips")
    columns = _str_list(pain.get("columns"), lang, f"{slug}.pain.columns")
    if len(chips) != 3 or len(columns) != 3:
        raise ConfigError(f"{slug}.pain: chips and columns need exactly 3 entries each ({lang})")
    pain_note = text(pain.get("note"), lang, f"{slug}.pain.note") if pain.get("note") else (
        "Rule of ten: a general quality principle, not company data" if lang == "en"
        else "Zehnerregel: allgemeines Qualitätsprinzip, keine Unternehmensdaten")

    idea = problem.get("idea") or {}
    idea_title = text(idea.get("title"), lang, f"{slug}.idea.title")
    idea_sub = text(idea.get("sub"), lang, f"{slug}.idea.sub") if idea.get("sub") else ""
    kicker = text(idea.get("kicker"), lang, f"{slug}.idea.kicker") if idea.get("kicker") else ("One idea" if lang == "en" else "Eine Idee")

    steps = problem.get("steps") or []
    if not 3 <= len(steps) <= 5:
        raise ConfigError(f"{slug}.steps: need 3 to 5 diagram nodes")
    nodes = []
    for i, step in enumerate(steps):
        sid = str(step.get("id") or f"step{i + 1}")
        nodes.append({
            "id": sid,
            "icon": step.get("icon") or STEP_ICONS[min(i, len(STEP_ICONS) - 1)],
            "title": text(step.get("title"), lang, f"{slug}.steps[{i}].title"),
            "sub": text(step.get("sub"), lang, f"{slug}.steps[{i}].sub") if step.get("sub") else "",
            "link": step.get("link") or ("arrow" if i < len(steps) - 1 else None),
        })
        if nodes[-1]["link"] is None:
            nodes[-1].pop("link")

    items = problem.get("before_after") or []
    if not 1 <= len(items) <= 2:
        raise ConfigError(f"{slug}.before_after: need 1 or 2 rows")
    metric_items = []
    for i, item in enumerate(items):
        metric_items.append({
            "label": text(item.get("label"), lang, f"{slug}.before_after[{i}].label"),
            "before": item["before"],
            "after": item["after"],
            "unit": text(item.get("unit"), lang, f"{slug}.before_after[{i}].unit") if item.get("unit") else "",
        })

    pilot_items = _str_list(problem["pilot"], lang, f"{slug}.pilot") if problem.get("pilot") else []

    narration = _narration(problem, lang, slug, pilot_items)
    labels = {
        "credit": CREDIT[lang].format(domain=domain),
        "top": {"badge": badge, "topic": title, "right": ""},
        "hook": {
            "icon": (hook.get("icon") if isinstance(hook, dict) else None) or "order",
            "lines": hook_lines,
            "sub": hook_sub,
            **(_photo(photos, hook.get("image") if isinstance(hook, dict) else None)),
            **({"status": text(hook.get("status"), lang, f"{slug}.hook.status")} if isinstance(hook, dict) and hook.get("status") else {}),
        },
        "pain": {
            "kind": "ruleOfTen",
            "title": pain_title,
            "chips": chips,
            "columns": columns,
            "multipliers": ["×1", "×10", "×100"],
            "note": pain_note,
            **(_photo(photos, pain.get("image"))),
        },
        "idea": {
            "icon": idea.get("icon") or "agent",
            "kicker": kicker,
            "title": idea_title,
            "sub": idea_sub,
            **(_photo(photos, idea.get("image"))),
        },
        "arch": {"title": text(problem.get("arch_title"), lang, f"{slug}.arch_title") if problem.get("arch_title") else ARCH_TITLE[lang],
                 "nodes": nodes, "badges": BADGES[lang]},
        "metrics": {**METRICS_CHROME[lang], "items": metric_items},
        "proof": {k: v for k, v in PROOF[lang].items() if k not in ("line", "cue")},
        "closing": {
            "name": AUTHOR,
            "role": CONCEPT[lang],
            "forLine": FOR_LINE[lang].format(name=name),
            "logo": logo,
            "link": GITHUB,
            "series": title,
            "note": NOT_OFFICIAL[lang].format(name=name),
            "voiceNote": VOICE_NOTE[lang],
            **({"logoPlate": "light"} if str(company.get("logo_plate") or "") == "light" else {}),
        },
    }
    if pilot_items:
        labels["pilot"] = {**PILOT_CHROME[lang], "items": pilot_items}
    blob = " ".join(ln["text"] for ln in narration) + " " + hook_sub + " " + title
    _reject_forbidden(blob, f"{slug}/{lang}")
    return {"lines": narration, "labels": labels}


def _photo(photos: dict, key) -> dict:
    """Attach a fetched photo. A named image that failed to download falls back to the drawn scene."""
    if key and key in photos:
        return {"photo": photos[key]}
    return {}


def _str_list(value, lang: str, where: str) -> list[str]:
    if isinstance(value, dict):
        value = value.get(lang)
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise ConfigError(f"{where}: need a list of strings for '{lang}'")
    return [x.strip() for x in value]


def _narration(problem: dict, lang: str, slug: str, pilot_items: list[str]) -> list[dict]:
    raw = (problem.get("narration") or {}).get(lang)
    if not isinstance(raw, list) or len(raw) < 4:
        raise ConfigError(f"{slug}.narration.{lang}: need the spoken lines (at least hook, pain, idea, architecture)")
    lines = []
    for i, ln in enumerate(raw):
        if not isinstance(ln, dict) or "scene" not in ln or "text" not in ln:
            raise ConfigError(f"{slug}.narration.{lang}[{i}]: need scene and text")
        if ln["scene"] not in SCENE_ORDER:
            raise ConfigError(f"{slug}.narration.{lang}[{i}]: unknown scene {ln['scene']!r}")
        item = {"scene": ln["scene"], "text": str(ln["text"]).strip()}
        if ln.get("say"):
            item["say"] = str(ln["say"]).strip()
        if ln.get("cues"):
            item["cues"] = {str(k): str(v) for k, v in ln["cues"].items()}
        lines.append(item)
    have = {ln["scene"] for ln in lines}
    for needed in ("hook", "pain", "idea", "arch", "metrics"):
        if needed not in have:
            raise ConfigError(f"{slug}.narration.{lang}: missing a '{needed}' line")
    if pilot_items and "pilot" not in have:
        raise ConfigError(f"{slug}.narration.{lang}: pilot items are set, so add a 'pilot' line")
    if "proof" not in have:
        item = {"scene": "proof", "text": PROOF[lang]["line"], "cues": {"proof": PROOF[lang]["cue"]}}
        if PROOF[lang].get("say"):
            item["say"] = PROOF[lang]["say"]
        lines.append(item)
    if "closing" not in have:
        lines.append({"scene": "closing", "text": CLOSING_LINE[lang]})
    # Proof and closing stay last, in that order, whatever order the author listed the middle in.
    rank = {name: i for i, name in enumerate(SCENE_ORDER)}
    lines.sort(key=lambda ln: rank[ln["scene"]])
    return lines


def photo_map(config: dict) -> dict[str, str]:
    images = config["company"].get("images") or {}
    if not isinstance(images, dict) or not images:
        raise ConfigError("company.images: need named image URLs, for example hook: https://…")
    return {str(k): str(v) for k, v in images.items()}
