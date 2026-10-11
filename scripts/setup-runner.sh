#!/usr/bin/env bash
# Prepare a Linux runner for rendering: CJK fonts, hard-edged (non-antialiased)
# text via fontconfig, and Playwright's headless Chromium.
# Usage: setup-runner.sh <inkage project dir>
set -euo pipefail
project="${1:?usage: setup-runner.sh <inkage project dir>}"

fonts="$HOME/.local/share/fonts/noto-cjk"
if ! compgen -G "$fonts/*.ttc" >/dev/null; then
  tmp="$(mktemp -d)"
  sudo apt-get update -qq
  (cd "$tmp" && apt-get download -qq fonts-noto-cjk)
  dpkg -x "$tmp"/fonts-noto-cjk_*.deb "$tmp/x"
  mkdir -p "$fonts"
  cp "$tmp"/x/usr/share/fonts/opentype/noto/NotoSansCJK-{Regular,Bold,Black}.ttc "$fonts/"
  rm -rf "$tmp"
fi

mkdir -p "$HOME/.config/fontconfig"
cat >"$HOME/.config/fontconfig/fonts.conf" <<'XML'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>~/.local/share/fonts</dir>
  <match target="font">
    <edit name="antialias" mode="assign"><bool>false</bool></edit>
    <edit name="hinting" mode="assign"><bool>true</bool></edit>
    <edit name="hintstyle" mode="assign"><const>hintfull</const></edit>
  </match>
</fontconfig>
XML
fc-cache -f >/dev/null
fc-list | grep -q "Noto Sans CJK SC" || { echo "Noto Sans CJK SC not visible to fontconfig" >&2; exit 1; }

uv run --frozen --project "$project" playwright install chromium --only-shell
