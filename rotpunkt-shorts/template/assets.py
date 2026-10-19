"""Download a logo or a product image once, then reuse the file. Nothing here is committed."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "work" / "asset-cache"
PUBLIC = ROOT / "video" / "public"


def _ext(url: str, kind: str) -> str:
    path = url.split("?", 1)[0].lower()
    for ext in (".svg", ".webp", ".png", ".jpg", ".jpeg"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".svg" if kind == "logo" else ".img"


def fetch(url: str, kind: str = "image") -> Path | None:
    """Cached download. Returns None when the URL fails or the file is too small to be a real picture."""
    CACHE.mkdir(parents=True, exist_ok=True)
    ext = _ext(url, kind)
    dest = CACHE / f"{hashlib.sha256(url.encode()).hexdigest()[:20]}{ext}"
    if not dest.exists() or dest.stat().st_size < 400:
        proc = subprocess.run(
            ["curl", "-fsSL", "--retry", "3", "--max-time", "40", "-A", "Mozilla/5.0", "-o", str(dest), url],
            capture_output=True, text=True)
        if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 400:
            dest.unlink(missing_ok=True)
            print(f"  image not fetched, scene will use the drawn graphic instead: {url}", file=sys.stderr)
            return None
    if kind == "image" and dest.suffix != ".svg":
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "csv=p=0", str(dest)],
            capture_output=True, text=True)
        width = int(probe.stdout.strip() or "0")
        if width < 400:
            print(f"  image too small ({width}px), skipped: {url}", file=sys.stderr)
            return None
    return dest


def place(url: str, public_rel: str, kind: str = "image") -> str | None:
    """Copy a cached asset into the Remotion public folder. Returns the staticFile path, or None."""
    src = fetch(url, kind)
    if src is None:
        return None
    dest = PUBLIC / public_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.stat().st_size != src.stat().st_size:
        shutil.copyfile(src, dest)
    return public_rel.replace("\\", "/")
