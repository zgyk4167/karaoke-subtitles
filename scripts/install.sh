#!/usr/bin/env bash
# Install the tools karaoke-subtitles needs, then run `pipeline.py doctor`.
# Non-interactive and safe to re-run. Exit 3 if a step needs a human
# (for example, sudo asks for a password).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
OS=$(uname -s)

need_human() { echo "error: $1" >&2; echo "next: $2" >&2; exit 3; }

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
  SUDO="sudo"
else
  SUDO="ask"
fi

if [ "$OS" = "Darwin" ]; then
  command -v brew >/dev/null || need_human "Homebrew is not installed." "Ask the user to install it from https://brew.sh, then rerun this script."
  brew install ffmpeg fontconfig python yt-dlp
elif command -v apt-get >/dev/null; then
  PKGS="ffmpeg fontconfig python3 pipx curl"
  [ "$SUDO" = "ask" ] && need_human "Installing system packages needs sudo, and sudo asks for a password." "Ask the user to run: sudo apt-get install -y $PKGS"
  $SUDO apt-get update && $SUDO apt-get install -y $PKGS
elif command -v dnf >/dev/null; then
  PKGS="ffmpeg fontconfig python3 pipx curl"
  [ "$SUDO" = "ask" ] && need_human "Installing system packages needs sudo, and sudo asks for a password." "Ask the user to run: sudo dnf install -y $PKGS"
  $SUDO dnf install -y $PKGS
else
  echo "warning: unknown package manager; install ffmpeg (with libass and libx264), fontconfig and python3 yourself." >&2
fi

# yt-dlp on Linux: pipx, or a private venv. System pip is avoided because
# PEP 668 blocks it on recent Debian and Ubuntu.
if [ "$OS" != "Darwin" ]; then
  if command -v pipx >/dev/null; then
    pipx install yt-dlp >/dev/null 2>&1 || pipx upgrade yt-dlp
    pipx ensurepath >/dev/null 2>&1 || true
    export PATH="$HOME/.local/bin:$PATH"
  elif ! command -v yt-dlp >/dev/null; then
    python3 -m venv "$HOME/.local/share/yt-dlp-venv"
    "$HOME/.local/share/yt-dlp-venv/bin/pip" install -U yt-dlp
    mkdir -p "$HOME/.local/bin"
    ln -sf "$HOME/.local/share/yt-dlp-venv/bin/yt-dlp" "$HOME/.local/bin/yt-dlp"
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

# The font is bundled; download it only if it is missing.
FONT="$HERE/assets/fonts/NotoSansCJKsc-Bold.otf"
if [ ! -s "$FONT" ]; then
  mkdir -p "$HERE/assets/fonts"
  curl -fsSL -o "$FONT.part" https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf
  mv "$FONT.part" "$FONT"
fi

python3 "$HERE/scripts/pipeline.py" doctor
