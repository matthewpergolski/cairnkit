# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-10-30

### Added

- Pull requests fail when the body is not one six-section STE copy; other repos
  can copy `scripts/check_pr_body.py` and `.github/workflows/pr-standards.yml` (#20).
- `scripts/pr_body.py` strips packaging, validates the body, and prefers
  `gh pr edit --body-file` (#20).
- `docs/pr-workflow.md` documents the short STE pull-request flow (#20).

### Changed

- `memory docs` inventories the project checkout (packages, entry points, README
  sections, import graph) instead of always describing cairnkit. Session and
  fact-lifecycle pages stay in cairnkit's own atlas only (#19).
- Review-gate needs dispositions and the current head sha; placeholder and
  duplicate-body checks are stricter (#20).

### Fixed

- `memory update` on a git URL detects a newer tagged release when no install
  commit is recorded (reads a `vX.Y.Z` tag at HEAD, else the highest remote
  release tag) (#19).

## [0.3.0] - 2026-10-30

### Added

- `memory docs` writes a Nessa Docs atlas under `docs/state` with no model and no network (#14).
- Auto propose and tidy on personal git hooks and long sessions, plus a loop breaker after three identical command failures (#15).
- Untracked rules blocks with one tracked `AGENTS.md` pointer line so clones stay usable without cairnkit (#15).
- `memory docs --check` reports drifted `docs/state` pages without writing; `verify.sh` runs it (#17).
- Post-merge prints one line when the atlas is stale so you can run `memory docs --force` (#17).
- `memory skills` installs every pstack skill with `--adopt` and shows installed versus available counts (#8).
- OpenCode, Pi, and Grok Build appear in pstack skills status and install (#13).
- Personal `pre-push` and `post-merge` hooks run gated auto-tidy after a push or a merge.
- `memory status` and `memory update` show the installed git ref and the upgrade delta.
- Faster CLI startup; CI also runs on Python 3.15 (#1).

### Changed

- Non-rule fact body cap is 2000 characters with an optional `summary`; rules stay at 400 (#15).
- Session and git hooks stay silent when `memory init` was never run (#15).
- Identity check accepts owner GitHub squash merges titled `(#N)` (#15).
- Every worktree gets its `memory-bank` link before hooks install or checks run.
- Personal git tidy hooks stay quiet and time-bounded (perl alarm; no hung watcher).
- Package version has one source: `src/cairnkit/__init__.py` (hatch dynamic).
- CI runs `verify.sh` and Linux e2e; pull requests check neutral identity and the six-section PR body.

## [0.2.0] - 2026-10-26

Baseline before the 0.3.0 work above.

[Unreleased]: https://github.com/matthewpergolski/cairnkit/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/matthewpergolski/cairnkit/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/matthewpergolski/cairnkit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/matthewpergolski/cairnkit/releases/tag/v0.2.0
