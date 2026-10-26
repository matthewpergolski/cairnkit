#!/usr/bin/env bash
# End-to-end run in a throwaway git repo with one worktree.
# Usage: scripts/e2e.sh   (uses `uv run memory` from this checkout)
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
memory() { uv run --project "$here" -q memory "$@"; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
step() { printf '\n== %s\n' "$*"; }

cd "$tmp" && mkdir app && cd app
git init -q -b main && git config user.name e2e && git config user.email e2e@example.invalid
echo ".worktrees/" > .gitignore && echo "app" > README.md
git add -A && git commit -qm init
git worktree add -q -b feature-email .worktrees/feature-email

step "init (dry run, then real, then again)"
memory init --dry-run
memory init --preset commits
memory init --preset commits
ls -l memory-bank .worktrees/feature-email/memory-bank | awk '{print $9, $10, $11}'

step "add 3 facts"
a=$(memory add "Mail goes out through a queue." --kind decision --area email \
  --basis seen --source session:2026-10-22 | awk '/^added/ {print $2}')
b=$(memory add "Never clear the dev database without a look first." --kind trap \
  --area database --basis seen --source session:2026-10-22 --pinned | awk '/^added/ {print $2}')
cd .worktrees/feature-email
c=$(memory add "Retry test is flaky here." --short --until-merged --area email \
  --basis seen --source session:2026-10-22 | awk '/^added/ {print $2}')
cd "$tmp/app"
echo "$a $b $c"

step "change one (supersede $a)"
d=$(memory add "Mail goes out through a cron job." --kind decision --area email \
  --basis seen --source commit:abc1234 --supersedes "$a" --reason "The queue lost jobs." \
  | awk '/^added/ {print $2}')
echo "$d"
[ -n "$a" ] && [ -n "$b" ] && [ -n "$c" ] && [ -n "$d" ] || { echo "FAIL: a fact id is missing"; exit 1; }
memory show "$a" | grep -q superseded || { echo "FAIL: $a not superseded"; exit 1; }
memory change "$b" --link "related:$d"

step "load (main)"
memory load
step "load (worktree)"
(cd .worktrees/feature-email && memory load)
step "search --all queue"
memory search queue --all
step "show $a"
memory show "$a"
step "check"
memory check

step "hooks install (generic + pre-commit + local commit-msg guard)"
memory hooks install --agent generic --commit-msg-guard
memory hooks install --agent generic --commit-msg-guard | tail -1

step "the guarded default rule is now enforced; add an enforced rule of our own"
memory add "No print calls in src." --kind rule --area code --basis told \
  --source person:owner --enforced-by lint:ruff:T201 >/dev/null
memory load | sed -n '/^## Enforced rules/,/^## Long-term/p'
memory check --advisory | grep -v '^memory check'

step "session hooks (generic): start, work, stop reminds once"
echo '{}' | memory hook session-start | tail -3
echo "x = 1" > work.py
echo '{}' | memory hook stop && echo "stop: no reminder" || echo "stop: exit $? (reminder shown above)"
echo '{}' | memory hook stop && echo "stop again: quiet (same work)"
rm work.py

step "pre-commit refuses a commit that stages the link"
git add -f memory-bank
if git commit -qm "try to commit the link" 2>err.txt; then echo "FAIL: link committed"; exit 1; fi
cat err.txt; rm err.txt
git reset -q

step "commit-msg guard refuses AI attribution"
echo y > y.txt && git add y.txt
if printf 'Add y\n\nCo-authored-by: Claude <noreply@example.com>\n' | git commit -q -F - 2>err.txt
then echo "FAIL: trailer accepted"; exit 1; fi
cat err.txt; rm err.txt
git commit -qm "Add y" && echo "plain commit: ok"

step "git: nothing from the memory to commit"
git add -A
git status --porcelain
git diff --cached --name-only | grep -q memory-bank && { echo "FAIL: link staged"; exit 1; }
(cd .worktrees/feature-email && git add -A && git status --porcelain)
git check-ignore -v memory-bank .memory-path || true
ls ../app.memory/facts

step "merge feature-email: its short-term fact expires (computed, not rewritten)"
before=$(wc -c < ../app.memory/facts/feature-email.jsonl)
(cd .worktrees/feature-email && echo x > f.txt && git add f.txt && git commit -qm work)
git merge -q --no-edit feature-email
(cd .worktrees/feature-email && memory load | grep -c "Retry test" || true)
memory search flaky --all
after=$(wc -c < ../app.memory/facts/feature-email.jsonl)
[ "$before" = "$after" ] && echo "fact file unchanged ($after bytes)"
step "plain folder (no git): a subfolder finds the project; init there is refused"
mkdir -p "$tmp/plain/sub/deep" && cd "$tmp/plain"
memory init --no-default-rules | tail -1
cd sub/deep
memory add "Written from a subfolder." --area notes --basis seen \
  --source session:2026-10-23 >/dev/null
memory load | grep "Written from a subfolder"
ls -d "$tmp"/*.memory | xargs -n1 basename   # app.memory and plain.memory only
if memory init 2>err.txt; then echo "FAIL: second init in a subfolder"; exit 1; fi
head -1 err.txt; rm err.txt
[ ! -e "$tmp/plain/sub/deep/memory-bank" ] && echo "no second memory"
if memory add "x" --area notes --basis seen --source session:2026-10-23 --until-merged 2>err.txt
then echo "FAIL: --until-merged accepted outside git"; exit 1; fi
cat err.txt; rm err.txt
step "rule presets: dev has no tool rules; a preset file adds ruff, enforced once git runs it"
mkdir -p "$tmp/tool/.githooks" && cd "$tmp/tool"
git init -q -b main && git config user.name e2e && git config user.email e2e@example.invalid
printf '[project]\nname = "tool"\n\n[tool.ruff]\nline-length = 100\n' > pyproject.toml
printf '#!/bin/sh\nuv run ruff check .\n' > .githooks/pre-push && chmod +x .githooks/pre-push
memory preset show dev --detect | grep -E "dev\.(verify|lockfile)"
memory init --preset dev > /dev/null
tools="$here/tests/fixtures/tools_preset.toml"
memory preset add --file "$tools" --dry-run | grep "tools\.ruff: advisory"  # git does not run .githooks yet
git config core.hooksPath .githooks
memory preset add --file "$tools" | grep "tools\.ruff: enforced"
memory load --budget 1 | grep -A1 "## Enforced rules"
memory check --strict

step "rules block: local goes to CLAUDE.local.md, shared goes to CLAUDE.md with an AGENTS.md pointer"
mkdir -p "$tmp/rules" && cd "$tmp/rules"
git init -q -b main && git config user.name e2e && git config user.email e2e@example.invalid
memory init --no-default-rules > /dev/null
memory init --write-instructions --dry-run | grep -E "^(found|would)"
memory init --write-instructions | grep -E "^(found|created)"
[ -f CLAUDE.local.md ] && [ ! -e AGENTS.local.md ] && git check-ignore -q CLAUDE.local.md
memory instructions --write-instructions=shared | grep -E "^(found|created)"
grep -q "cairnkit:start" CLAUDE.md && ! grep -q "cairnkit:start" AGENTS.md && grep -q "CLAUDE.md" AGENTS.md
memory instructions --write-instructions=shared | grep -q "unchanged"
[ "$(cat CLAUDE.md AGENTS.md CLAUDE.local.md | grep -c 'cairnkit:start')" = 2 ] && echo "one block per file"

echo "e2e: ok"
