#!/usr/bin/env python3
"""Fetch a job advert and a company site, then write a draft company config.

  ~/.venvs/kokoro/bin/python prepare_company.py <job_url> --company-site https://example.com

Downloads the logo and up to six images into the asset cache, and writes companies/<slug>.yaml
with the pictures filled in and the story left as TODOs. The scenes, the MARA proof and the closing
card are already wired, so filling the TODOs needs no code changes.

One compact LLM call is made only when OPENAI_API_KEY or ANTHROPIC_API_KEY is set. Otherwise the
draft is a skeleton and the fetched text is saved next to it for whoever fills the story in.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from template.assets import fetch  # noqa: E402

MAX_IMAGES = 6
SKIP_IN_URL = ("logo", "icon", "sprite", "favicon", "pixel", "tracking", "badge", "social", "facebook", "instagram", "linkedin")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.chunks: list[str] = []
        self.title = ""
        self._in_title = False
        self.images: list[str] = []
        self.og: list[str] = []
        self.svgs: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v or "" for k, v in attrs}
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "title":
            self._in_title = True
        src = a.get("src") or a.get("data-src") or ""
        if tag == "img" and src:
            self.images.append(src)
        if tag == "meta" and a.get("property") == "og:image" and a.get("content"):
            self.og.append(a["content"])
        if tag in ("img", "a", "link", "use") and ".svg" in src.lower():
            self.svgs.append(src)
        if tag == "link" and "icon" not in a.get("rel", "") and ".svg" in a.get("href", "").lower():
            self.svgs.append(a["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip and data.strip():
            self.chunks.append(data.strip())


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as res:
        return res.read().decode("utf-8", "replace")


def _abs(base: str, src: str) -> str:
    return urljoin(base, src)


def _slug(site: str, title: str) -> str:
    host = urlparse(site).netloc.replace("www.", "") if site else ""
    raw = host or title or "company"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:40] or "company"


def _pick_images(page: _Page, base: str) -> tuple[str, list[str]]:
    logo = ""
    for src in page.svgs:
        if "logo" in src.lower():
            logo = _abs(base, src)
            break
    seen, photos = set(), []
    for src in page.og + page.images:
        url = _abs(base, src)
        low = url.lower().split("?", 1)[0]
        if any(bad in low for bad in SKIP_IN_URL) or low in seen:
            continue
        if not low.endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        seen.add(low)
        if fetch(url) is not None:
            photos.append(url)
        if len(photos) >= MAX_IMAGES:
            break
    return logo, photos


def _skeleton(slug: str, name: str, domain: str, logo: str, photos: list[str], job_url: str) -> str:
    images = "\n".join(f"    photo{i}: {url}" for i, url in enumerate(photos, 1)) or "    {}"
    logo_line = logo or ""
    return f"""# Draft for {name or slug}. Fill every TODO. Proof, badges and the closing card are added automatically.
# Job advert: {job_url}
# Do not mention the job posting in the narration or on screen. The idea is his own.
version: 1
company:
  slug: {slug}
  name: {name or "TODO company name"}
  domain: {domain or "TODO.example"}
  logo_url: {logo_line}
  images:
{images}

problems:
  - slug: problem-1
    title: {{en: "TODO", de: "TODO"}}
    hook:
      icon: order
      image: photo1
      sub: {{en: "TODO one line under the title", de: "TODO"}}
      en: [["TODO hook line"], ["TODO second line"]]
      de: [["TODO"], ["TODO"]]
    pain:
      image: photo2
      title: {{en: "TODO what hurts", de: "TODO"}}
      chips:
        en: ["TODO", "TODO", "TODO"]
        de: ["TODO", "TODO", "TODO"]
      columns:
        en: ["At the desk", "In production", "At the customer"]
        de: ["Am Schreibtisch", "In der Fertigung", "Beim Kunden"]
    idea:
      icon: agent
      image: photo1
      title: {{en: "TODO the assistant", de: "TODO"}}
      sub: {{en: "TODO", de: "TODO"}}
    steps:
      - {{id: inputs, icon: inbox, title: {{en: "TODO input", de: "TODO"}}, sub: {{en: "TODO", de: "TODO"}}}}
      - {{id: agent, icon: agent, link: both, title: {{en: "AI agent (LLM)", de: "KI-Agent (LLM)"}}, sub: {{en: "TODO", de: "TODO"}}}}
      - {{id: rules, icon: db, title: {{en: "Your documents (RAG)", de: "Ihre Unterlagen (RAG)"}}, sub: {{en: "TODO", de: "TODO"}}}}
      - {{id: out, icon: factory, title: {{en: "Checked result", de: "Geprüftes Ergebnis"}}, sub: {{en: "a person decides", de: "ein Mensch entscheidet"}}}}
    before_after:
      - {{label: {{en: "TODO minutes", de: "TODO Minuten"}}, before: 20, after: 5, unit: {{en: min, de: "Min."}}}}
    narration:
      en:
        - {{scene: hook, text: "TODO."}}
        - {{scene: pain, text: "TODO.", cues: {{pain.chips: TODO}}}}
        - {{scene: idea, text: "One idea: TODO."}}
        - {{scene: arch, text: "TODO.", cues: {{arch.inputs: TODO}}}}
        - {{scene: metrics, text: "Illustrative targets: TODO."}}
      de:
        - {{scene: hook, text: "TODO."}}
        - {{scene: pain, text: "TODO."}}
        - {{scene: idea, text: "Eine Idee: TODO."}}
        - {{scene: arch, text: "TODO."}}
        - {{scene: metrics, text: "Beispielhafte Ziele: TODO."}}
"""


def _llm_fill(skeleton: str, jd_text: str) -> str | None:
    """One short call. Returns rewritten YAML, or None when no key is set."""
    brief = jd_text[:6000]
    prompt = (
        "Fill the TODOs in this YAML for a 60 second job-application video. "
        "Use only problems implied by the job text. 1 or 2 problems. "
        "Never mention the job posting. Numbers for the company are examples and must stay modest. "
        "Keep the YAML schema. Return only YAML.\n\nJOB:\n" + brief + "\n\nYAML:\n" + skeleton
    )
    if os.environ.get("OPENAI_API_KEY"):
        body = json.dumps({"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as res:
            data = json.loads(res.read().decode())
        return data["choices"][0]["message"]["content"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        body = json.dumps({
            "model": "claude-3-5-haiku-latest", "max_tokens": 2500,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as res:
            data = json.loads(res.read().decode())
        return data["content"][0]["text"]
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job_url")
    ap.add_argument("--company-site", default="")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--slug", default="")
    args = ap.parse_args(argv)
    print(f"fetching job: {args.job_url}")
    job_html = _get(args.job_url)
    job = _Page()
    job.feed(job_html)
    site = args.company_site
    page = job
    if site:
        print(f"fetching site: {site}")
        site_html = _get(site)
        page = _Page()
        page.feed(site_html)
    base = site or args.job_url
    logo, photos = _pick_images(page, base)
    host = urlparse(base).netloc.replace("www.", "")
    slug = args.slug or _slug(site or args.job_url, job.title)
    name = re.sub(r"\s+", " ", job.title).strip()[:80]
    yaml_text = _skeleton(slug, name, host, logo, photos, args.job_url)
    filled = _llm_fill(yaml_text, "\n".join(job.chunks)[:8000])
    if filled:
        yaml_text = filled
        print("story filled with one LLM call")
    else:
        print("no OPENAI_API_KEY or ANTHROPIC_API_KEY. Wrote a skeleton. The job text is saved beside it.")
    out = args.out or (ROOT / "companies" / f"{slug}.yaml")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml_text, encoding="utf-8")
    notes = out.with_suffix(".research.txt")
    notes.write_text(f"URL: {args.job_url}\nSITE: {site}\nTITLE: {job.title}\n\n" + "\n".join(job.chunks)[:20000], encoding="utf-8")
    print(f"draft {out}")
    print(f"job text {notes}")
    print(f"logo {logo or '(none)'}  images {len(photos)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
