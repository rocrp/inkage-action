#!/usr/bin/env bash
# Composite-action entry: run `inkage run`, keep the Site when a Source fails
# at runtime (exit 3), abort on anything else (config error, crash).
set -euo pipefail
: "${GITHUB_ACTION_PATH:?}" "${GITHUB_OUTPUT:?}"

args=(run --config "$INKAGE_CONFIG" --site-url "$INKAGE_SITE_URL" --out "$INKAGE_OUT")
[[ -n "$INKAGE_SOURCES_DIR" ]] && args+=(--sources-dir "$INKAGE_SOURCES_DIR")
fonts_dir="$INKAGE_FONTS_DIR"
[[ -z "$fonts_dir" && -d fonts ]] && fonts_dir=fonts
[[ -n "$fonts_dir" ]] && args+=(--fonts-dir "$fonts_dir")

set +e
uv run --frozen --project "$GITHUB_ACTION_PATH" inkage "${args[@]}"
code=$?
set -e
case "$code" in
  0) failed=false ;;
  3) failed=true ;;
  *) exit "$code" ;;
esac
# Earliest next_due across Frames (RFC 3339 UTC); empty when no Frame has one.
next_due=$(jq -r '[.frames[].next_due | select(. != null)] | min // empty' "$INKAGE_OUT/manifest.json")
{
  echo "dist=$INKAGE_OUT"
  echo "failed=$failed"
  echo "next_due=$next_due"
} >>"$GITHUB_OUTPUT"
