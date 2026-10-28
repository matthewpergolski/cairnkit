#!/usr/bin/env bash
# Install a local pre-push hook that runs ./scripts/verify.sh.
# Keeps an existing cairnkit (or project-memory) marked block so the two chain.
# Optional: run once in a clone. Not shared; lives under .git/hooks/.
# Compatible with bash 3.2 (macOS /bin/bash).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

START='# >>> cairnkit-verify >>>'
END='# <<< cairnkit-verify <<<'
CAIRN_END='# <<< cairnkit <<<'
OLD_END='# <<< project-memory <<<'

hooks="$(git rev-parse --path-format=absolute --git-path hooks)"
hook="$hooks/pre-push"
mkdir -p "$hooks"

verify_block() {
  printf '%s\n' "$START" './scripts/verify.sh || exit 1' "$END"
}

# Drop our marked block if present.
strip_ours() {
  awk -v s="$START" -v e="$END" '
    $0 == s { skip = 1; next }
    skip && $0 == e { skip = 0; next }
    skip { next }
    { print }
  '
}

if [[ ! -f $hook ]]; then
  {
    printf '%s\n' '#!/bin/sh'
    verify_block
  } >"$hook"
  chmod +x "$hook"
  echo "wrote $hook"
  exit 0
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
strip_ours <"$hook" >"$tmp"

# Ensure a shebang on line 1.
first="$(head -n 1 "$tmp")"
if [[ $first != '#!'* ]]; then
  { printf '%s\n' '#!/bin/sh'; cat "$tmp"; } >"$tmp.new"
  mv "$tmp.new" "$tmp"
fi

out="$(mktemp)"
trap 'rm -f "$tmp" "$out"' EXIT
inserted=0
{
  IFS= read -r line || true
  printf '%s\n' "$line"
  while IFS= read -r line || [[ -n $line ]]; do
    printf '%s\n' "$line"
    if [[ $line == "$CAIRN_END" || $line == "$OLD_END" ]]; then
      verify_block
      inserted=1
    fi
  done
} <"$tmp" >"$out"

if [[ $inserted -eq 0 ]]; then
  # No cairnkit block: verify right after the shebang, then the rest.
  {
    IFS= read -r line || true
    printf '%s\n' "$line"
    verify_block
    cat
  } <"$out" >"$tmp"
  mv "$tmp" "$out"
fi

mv "$out" "$hook"
chmod +x "$hook"
echo "updated $hook"
