# Rule presets

A rule preset is a named set of rule facts. `memory init --preset NAME` adds
the rules of one or more presets to the memory. After that, they are facts like any other.
Every session loads them first.

## The presets

| Preset | Rules | For |
|---|---|---|
| `commits` | 3 | No AI attribution in commits, pull requests or docs. |
| `basic` | 8 | An agent that reads and talks about the files in a folder. The folder does not need code or git. |
| `dev` | 16 or 17 | A codebase. It holds `commits`, 6 of the `basic` rules and 7 rules for code. It adds 1 lock file rule when the project needs it. |
| `none` | 0 | No rule facts. The default. Same as `--no-default-rules`. |

Run `memory preset list` to see them, and `memory preset show NAME` to read
each rule.

The `dev` preset holds only generic rules: checks, tests, small diffs, git
and secrets. It has no rule for one tool. A rule such as "use uv" is an
instruction for one toolchain. It belongs in the project's or template's
`AGENTS.md`, or in a preset file that the project owns (see
[Presets from a file](#presets-from-a-file)). See
[layering.md](layering.md#built).

Older versions of `dev` had 5 rules for single tools: `dev.uv`, `dev.ruff`,
`dev.bun`, `dev.biome` and `dev.pins`. A memory that holds them keeps them.
`memory preset add dev` does not remove them. To remove one, end it (see
below). A preset file can hold the same rules under its own keys. Then
`memory preset add --file` skips each rule that has the same text as an old
one.

## Use a preset

- A new memory: `memory init --preset dev`.
- Stack presets: `memory init --preset basic --preset dev`. Each rule is
  added once.
- An existing memory: `memory preset add dev`. It adds only the rules that
  are not there yet.
- Look first: add `--dry-run` to either command. It changes nothing.
- Plain `memory init` adds no rule facts. The rules about memory itself ship
  inside the tool. To add the commit rules, run `memory preset add commits`.

`memory preset add` never adds a rule again:

- when the memory holds it (the same `preset_rule` key), or
- when a person ended it (`wrong`, `expired` or `superseded`), or
- when a rule with the same text is already there, for example one that a
  person wrote. Case, spaces and a last period do not count.

To remove a preset rule from one project, end it:
`memory change ID --status wrong --reason "Not for this project."`.

## Presets from a file

A project can keep its own rules in a preset file, for example the rules
for its tools. The file uses the same format as the built-in presets (see
[The file format](#the-file-format)). The file can be in any folder.
Usually it is in the project repo, and git tracks it.

- Add its rules: `memory preset add --file PATH`.
- Look first: `memory preset add --file PATH --dry-run`. It changes
  nothing and prints each rule.
- Add a preset and a file together:
  `memory preset add dev --file PATH`.
- Add more than one file: repeat `--file`.

The rules become normal rule facts. The same rules as above apply:
`memory preset add --file` adds each rule once, never adds an ended rule
again, and skips a rule with the same text. Run it again after you change
the file. It adds only the new rules.

Three more rules apply to a preset file:

- All keys have the same prefix, for example `tmpl.uv` and `tmpl.ruff`.
  The prefix is the preset name. Each rule gets `source: preset:<prefix>`.
- The prefix cannot be the name of a built-in preset (`commits`, `basic`,
  `dev`, `none`).
- The tool refuses an unknown field, an unknown detection name, a text
  that looks like a secret, a text of more than 400 characters and an
  `enforced_by` that is not `<type>:<value>`.

When the file is not valid, the command prints one error line and changes
nothing. Example:

```
error: preset file agents/preset.toml: rule tmpl.uv needs text
```

`memory preset list` shows only the built-in presets. The tool does not
look for preset files. It reads only the file that you name. After you add
the rules, `memory load` prints them with the other rules.

## Detection in the dev preset

One `dev` rule applies only to some projects. `memory init --preset dev`
looks for its files in the project folder and one folder below it. It never
changes a file there.

| Rule | Added when the project has |
|---|---|
| `dev.lockfile` | `package-lock.json`, `pnpm-lock.yaml` or `yarn.lock`, and no Bun lock file |

### Enforced or advisory

A preset rule can name a check (`enforced_by`) and the finding that shows
the check runs (`enforce_when`). See [The file format](#the-file-format).
The shipped presets have no such rule now. The tool decides like this.

A config file does not make a rule enforced. A rule with
`enforced_by = "lint:ruff"` and `enforce_when = "ruff-run"` gets
`enforced_by: lint:ruff` only when CI or a git hook that git runs calls the
check.

A CI file always counts: `.github/workflows/*.yml` and `.gitlab-ci.yml`.

A hook file counts only when git runs it:

- An executable file in the git hooks folder. That is `.git/hooks/`, or the
  folder that `core.hooksPath` names, relative to the repo root. In a
  worktree, the tool asks git for the folder. A `.sample` file, or a file
  without the executable bit, does not count.
- `.githooks/*` counts only when `core.hooksPath` is `.githooks`.
- `.pre-commit-config.yaml` counts only when the pre-commit shim is in the
  git hooks folder (`pre-commit install` puts it there).
- `lefthook.yml` counts only when a lefthook shim is in the git hooks
  folder (`lefthook install` puts it there).
- `.husky/*` counts only when `core.hooksPath` is `.husky/_`, which Husky
  sets.

Outside git, no hook counts. CI still counts.

A check that only an idle hook runs leaves the rule advisory. The line says
why, for example:

```
  + example.ruff: advisory (ruff config in pyproject.toml; found in .githooks/pre-push, but core.hooksPath is not set, so git does not run it)
```

It also follows one step: a script that such a file names (for example
`tools/check.py`), and a `package.json` script that it runs (for example
`bun run lint`). A script that only a person runs, such as
`scripts/verify.sh`, does not count.

Each rule line says why. Example, with `core.hooksPath` set to `.githooks`:

```
  + example.ruff: enforced by lint:ruff (ruff config in pyproject.toml; run by .githooks/pre-push -> tools/check.py)
  + dev.lockfile: advisory (package-lock.json)
```

To see this for a project before you add anything:
`memory preset show dev --detect`.

The tool checks only when it adds the rule. It does not mark a rule again
later. When you add CI, or set `core.hooksPath`, or install a hook after
init, run `memory change ID --enforced-by TYPE:VALUE`.

## Rules and the word budget

`memory load` prints every active rule, outside the word budget. So a long
rule set costs context in every session. `memory check` prints a note when
the active rules hold more than 500 words. Keep presets lean: merge rules,
or end the ones that do not apply.

## The file format

Each built-in preset is one TOML file in `src/cairnkit/preset_data/`.
A preset file of your own uses the same format:

```toml
summary = "One line for `memory preset list`."
includes = ["commits"]                     # all rules of these presets
include_rules = ["basic.files"]            # single rules of other presets

[[rule]]
key = "example.ruff"                       # <preset>.<name>, never reused
area = "python"
tags = ["python", "ruff", "lint"]
text = "Python code must pass `ruff check`."
when = "ruff"                              # optional: a detection name
enforced_by = "lint:ruff"                  # optional
enforce_when = "ruff-run"                  # required with enforced_by
```

The `example` preset is not shipped. It only shows the fields. `key`,
`area` and `text` are required.

Detection names: `uv`, `ruff`, `ruff-run`, `bun`, `other-lockfile`, `biome`,
`biome-run`, `pins`. The shipped presets use only `other-lockfile`. A preset
file can use all of them. For example, a rule with `when = "uv"` is added
only to a project that uses uv.
