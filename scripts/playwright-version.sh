#!/usr/bin/env bash
# Print the Playwright version pinned in uv.lock (cache key for its browser download).
# Usage: playwright-version.sh <uv.lock>
set -euo pipefail
version="$(grep -A1 '^name = "playwright"$' "${1:?usage: playwright-version.sh <uv.lock>}" | sed -n 's/^version = "\(.*\)"$/\1/p')"
[[ -n "$version" ]] || { echo "playwright not found in $1" >&2; exit 1; }
echo "$version"
