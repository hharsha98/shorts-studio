#!/bin/bash
# One-time setup for rotpunkt-shorts on Linux: fonts, a Python venv for speech and checks, the Remotion packages and its browser.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${KOKORO_VENV:-$HOME/.venvs/kokoro}"

echo "== fonts (Be Vietnam Pro, SIL OFL)"
mkdir -p "$HERE/video/public/fonts"
for w in Regular Medium SemiBold Bold ExtraBold; do
  f="$HERE/video/public/fonts/BeVietnamPro-$w.ttf"
  [ -f "$f" ] || curl -sSfL -o "$f" "https://github.com/google/fonts/raw/main/ofl/bevietnampro/BeVietnamPro-$w.ttf"
done
[ -f "$HERE/video/public/fonts/OFL.txt" ] || curl -sSfL -o "$HERE/video/public/fonts/OFL.txt" "https://github.com/google/fonts/raw/main/ofl/bevietnampro/OFL.txt"

echo "== system packages (espeak-ng: Kokoro's fallback for unknown words; ffmpeg)"
if ! command -v espeak-ng >/dev/null || ! command -v ffmpeg >/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y -qq espeak-ng ffmpeg python3-venv
fi

echo "== Python venv at $VENV (torch CPU, kokoro, edge-tts, faster-whisper)"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
  "$VENV/bin/pip" install -q "kokoro>=0.9.4" soundfile edge-tts faster-whisper pyyaml
fi

echo "== Remotion (exact versions from package-lock.json) and its headless browser"
cd "$HERE/video"
npm ci --no-audit --no-fund
npx remotion browser ensure
echo "ready: $VENV/bin/python tools/build.py all"
