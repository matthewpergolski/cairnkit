#!/usr/bin/env bash
# Install a local pre-push hook that runs ./scripts/verify.sh.
# Keeps an existing cairnkit (or project-memory) marked block so the two chain.
# Optional: run once in a clone. Not shared; lives under .git/hooks/.
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

mapfile -t lines < <(strip_ours <"$hook")
if [[ ${#lines[@]} -eq 0 || ${lines[0]} != '#!'* ]]; then
  lines=('#!/bin/sh' "${lines[@]}")
fi

out=("${lines[0]}")
inserted=0
for ((i = 1; i < ${#lines[@]}; i++)); do
  out+=("${lines[i]}")
  if [[ ${lines[i]} == "$CAIRN_END" || ${lines[i]} == "$OLD_END" ]]; then
    while IFS= read -r vb; do
      out+=("$vb")
    done < <(verify_block)
    inserted=1
  fi
done
if [[ $inserted -eq 0 ]]; then
  # No cairnkit block: verify right after the shebang, then the rest.
  rebuilt=("${out[0]}")
  while IFS= read -r vb; do
    rebuilt+=("$vb")
  done < <(verify_block)
  if [[ ${#out[@]} -gt 1 ]]; then
    rebuilt+=("${out[@]:1}")
  fi
  out=("${rebuilt[@]}")
fi

printf '%s\n' "${out[@]}" >"$hook"
chmod +x "$hook"
echo "updated $hook"
