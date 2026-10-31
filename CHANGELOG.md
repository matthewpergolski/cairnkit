# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `memory update` strips a uv git pin (`?rev=`, `#<commit>`, or `@ref`),
  lists the clean remote, installs the newest release tag, and records
  `git+<url>@<tag>`. With no release tag it installs `HEAD` and records the
  clean URL. An older remote tag is not treated as an update. A 0.3.0
  tag-pinned install still needs a one-time `uv tool install` of the fixed
  release, because that binary cannot strip the pin.

### Changed

- `memory docs` inventries the project checkout (packages, entry points, README
  sections, import graph) instead of always describing cairnkit. Session and
  fact-lifecycle pages stay in cairnkit's own atlas only.

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

[Unreleased]: https://github.com/matthewpergolski/cairnkit/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/matthewpergolski/cairnkit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/matthewpergolski/cairnkit/releases/tag/v0.2.0
