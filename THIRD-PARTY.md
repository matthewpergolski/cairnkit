# Third-party software

cairnkit has no runtime dependencies. It uses only the Python standard
library. No third-party code is bundled in this repo or in the wheel.

Each entry says how its license was checked:

- **metadata**: read from the installed package metadata (`uv.lock` versions).
- **license file**: read from the project's license file on GitHub.
- **not verified**: taken from public listings, not checked here.

## Development dependencies

Installed by `uv sync` for tests and lint. They are not shipped.

| Package | Version in uv.lock | License | Source | Checked |
|---|---|---|---|---|
| pytest | 9.1.1 | MIT | https://github.com/pytest-dev/pytest | metadata |
| pluggy | 1.7.0 | MIT | https://github.com/pytest-dev/pluggy | metadata |
| iniconfig | 2.3.1 | MIT | https://github.com/pytest-dev/iniconfig | metadata |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging | metadata |
| Pygments | 2.21.0 | BSD-2-Clause | https://github.com/pygments/pygments | metadata |
| colorama (Windows only) | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama | license file (BSD text; clause count not verified) |
| ruff | 0.17.1 | MIT | https://github.com/astral-sh/ruff | metadata |

## Build dependencies

Used by `uv build` and `uv tool install`. They are not shipped.

| Package | Version | License | Source | Checked |
|---|---|---|---|---|
| hatchling | `>=1.26` (the build takes the newest; 1.32.4 was checked) | MIT | https://github.com/pypa/hatch | metadata |
| pathspec | from hatchling | MPL-2.0 | https://github.com/cpburnz/python-pathspec | metadata |
| trove-classifiers | from hatchling | Apache-2.0 | https://github.com/pypa/trove-classifiers | metadata |
| pluggy, packaging | from hatchling | see above | see above | metadata |

## Tools that you install yourself

cairnkit runs these. It does not ship them.

| Tool | License | Source | Checked |
|---|---|---|---|
| uv | MIT OR Apache-2.0 | https://github.com/astral-sh/uv | license file (MIT part) |
| git | GPL-2.0 | https://git-scm.com | not verified |
| Python | PSF-2.0 | https://www.python.org | not verified |

## Software that a command downloads

`memory skills install pstack` downloads the pstack agent skills when you run
it with `--yes`. They are not part of this repo. The command copies the
pstack `LICENSE` file next to the skills it installs.

| Software | License | Source | Checked |
|---|---|---|---|
| pstack (agent skills) | MIT | https://github.com/cursor/plugins/tree/main/pstack | license file (`pstack/LICENSE`) and `pstack/plugin.json` |
| Claude Code plugin marketplace `cursor/plugins` | see the repo | https://github.com/cursor/plugins | not verified: there is no license file at the repo root |

## CI

The GitHub Actions workflow uses these actions. They run on GitHub, not on
your computer.

| Action | License | Source | Checked |
|---|---|---|---|
| actions/checkout@v4 | MIT | https://github.com/actions/checkout | license file |
| astral-sh/setup-uv@v6 | MIT | https://github.com/astral-sh/setup-uv | license file |
