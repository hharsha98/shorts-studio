#!/usr/bin/env python3
"""Render a company Short from a YAML config. No scene code changes for a new company.

  ~/.venvs/kokoro/bin/python make_company_short.py --company-config companies/_example.yaml --lang de

From the project directory. One config can hold one or two problems; each problem becomes its own
60–70 s vertical video. Proof, safety badges and the closing card are added by the template.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402
from template.assets import place  # noqa: E402
from template.compile import compile_problem, load_config, photo_map  # noqa: E402

ARTIFACTS = Path("/opt/cursor/artifacts")


def _slug(config: dict) -> str:
    company = config["company"]
    if company.get("slug"):
        return str(company["slug"])
    return str(company.get("domain", "company")).split("/")[0].replace(".", "-")


def _photos(config: dict, slug: str) -> dict[str, str]:
    out = {}
    for key, url in photo_map(config).items():
        ext = Path(url.split("?", 1)[0]).suffix.lower() or ".img"
        if ext == ".jpeg":
            ext = ".jpg"
        rel = place(url, f"companies/{slug}/{key}{ext}")
        if rel:
            out[key] = rel
        else:
            print(f"  no photo for '{key}' ({url}). The scene uses the drawn graphic, and the storyboard should say so.")
    return out


def _logo(config: dict, slug: str) -> str:
    url = config["company"].get("logo_url") or ""
    if not url:
        print("  no logo_url. The closing card has the words without a logo.")
        return ""
    ext = ".svg" if ".svg" in url.lower() else (Path(url.split("?", 1)[0]).suffix.lower() or ".img")
    rel = place(url, f"companies/{slug}/logo{ext}", kind="logo")
    if not rel:
        print("  logo could not be fetched. The closing card has the words without it.")
    return rel or ""


def render_problem(config: dict, problem: dict, index: int, lang: str, artifact: Path | None, force: bool) -> Path:
    slug = _slug(config)
    problem_slug = str(problem.get("slug") or f"problem-{index + 1}")
    photos = _photos(config, slug)
    logo = _logo(config, slug)
    compiled = compile_problem(config, problem, index, lang, photos, logo)
    dest = build.WORK / "companies" / slug / problem_slug / lang
    dest.mkdir(parents=True, exist_ok=True)
    name = f"{slug}/{problem_slug}/{lang}"

    t0 = time.perf_counter()
    timeline = build.voice_lines(name, lang, compiled["lines"], dest, force=force)
    voice_s = time.perf_counter() - t0
    props_path = build.props_for(
        name, lang, compiled["labels"], timeline, dest, voice=True, brand=compiled.get("brand"),
    )
    digest = hashlib.sha256(props_path.read_bytes()).hexdigest()[:16]
    final = dest / f"{slug}_{problem_slug}_{lang}.mp4"
    stamp_path = dest / "render.json"
    stamp = json.loads(stamp_path.read_text()) if stamp_path.exists() else {}
    if not force and stamp.get("props") == digest and final.exists():
        print(f"{name}: video unchanged, render skipped (last render {stamp.get('render_s', '?')} s)")
        out = final
    else:
        t1 = time.perf_counter()
        build.make_music(build.WORK / "music-pad.wav")
        build.render(f"{slug}/{problem_slug}", lang, props_path, dest / "video.mp4")
        build.mix_audio(dest / "narration.wav", timeline, build.WORK / "music-pad.wav", dest / "mix.wav")
        build.mux(dest / "video.mp4", dest / "mix.wav", final)
        render_s = time.perf_counter() - t1
        stamp_path.write_text(json.dumps({"props": digest, "render_s": round(render_s, 1), "voice_s": round(voice_s, 1)}))
        print(f"{name}: rendered in {render_s:.0f} s (voice {voice_s:.0f} s) -> {final}")
        out = final
    if artifact:
        artifact.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, artifact)
        print(f"  artifact {artifact}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company-config", required=True, type=Path)
    ap.add_argument("--lang", required=True, choices=["en", "de"])
    ap.add_argument("--problem", default=None, help="problem slug, when the config has two and only one should render")
    ap.add_argument("--artifact", type=Path, default=None, help="copy the mp4 here (one problem only)")
    ap.add_argument("--force", action="store_true", help="re-voice and re-render even when nothing changed")
    args = ap.parse_args(argv)
    config = load_config(args.company_config)
    chosen = config["problems"]
    if args.problem:
        chosen = [p for p in chosen if str(p.get("slug")) == args.problem]
        if not chosen:
            sys.exit(f"no problem with slug {args.problem!r}")
    if args.artifact and len(chosen) != 1:
        sys.exit("--artifact needs exactly one problem (pass --problem)")
    for problem in chosen:
        index = config["problems"].index(problem)
        render_problem(config, problem, index, args.lang, args.artifact, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
