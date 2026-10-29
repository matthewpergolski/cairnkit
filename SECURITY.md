# Security

## Report a problem

Do not open a public issue for a security problem.

Report it privately with a GitHub security advisory:
<https://github.com/matthewpergolski/cairnkit/security/advisories/new>.
Give the version (`cairnkit --version`), the steps, and what you saw.

The advisory link works only when private vulnerability reporting is turned
on in the repository settings. If the link does not work, open a public issue
that asks for a private channel. Put no details of the problem in that issue.

You get an answer when the report is read. A fix is released on `main`.
`memory update` installs it.

## Scope

These parts are the most important to report:

- A secret that `memory check` or `memory add` does not find.
- A way for `memory purge` to leave the purged text on disk.
- A hook or a block that writes into a file that git tracks without a
  person asking for it.
- A stored note that the tool prints as an instruction instead of data.
- `memory update` installing code that is not the checked commit.

## What the tool does not do

- It sends no fact to any service. These are the only uses of the network:
  - The update check (session start, `memory status`, `memory update
    --check`): `git ls-remote` on the git URL you installed from. A local
    folder is read with local git only.
  - `memory update`: fetches the checked commit from that git URL. Its
    `uv build` can download build tools from PyPI.
  - The pstack skills check (session start, `memory check`, `memory init`,
    `memory migrate`, `memory skills status`): reads `pstack/plugin.json`
    from `github.com/cursor/plugins`, at most once a day (once an hour after
    a failure). It runs only when Claude Code, Codex, Cursor, OpenCode, Pi or
    Grok Build is found on the computer. `skills_check = false` in
    `config.toml` turns it off, except in `memory skills status`, which you
    run on purpose.
  - `memory skills install pstack --yes`: reads `pstack/plugin.json`, runs
    `git clone` of `github.com/cursor/plugins`, and for Claude Code runs
    `claude plugin marketplace add` and `claude plugin install`.
- It stores facts as plain text in a folder outside the repo. It does not
  encrypt them. Keep secrets out of facts. `memory purge` removes one that got
  in.
