# How to open a cairnkit pull request

Short STE flow. Do these steps in order.

## Why bodies get duplicated

Cloud agent `gh` often returns HTTP 403 on PR body edits. Threads then use
ManagePullRequest. That tool wraps the description once:

```text
<!-- CURSOR_AGENT_PR_BODY_BEGIN -->
…six sections…
<!-- CURSOR_AGENT_PR_BODY_END -->
<div>…cursor.com Open in Web / Open in Cursor footer…</div>
```

If someone pastes the six sections again outside that wrap, GitHub shows two
copies. That is the failure mode this workflow prevents.

## Option A (chosen): one canonical copy inside the markers

`scripts/check_pr_body.py` and `scripts/pr_body.py` treat the text between a
single `CURSOR_AGENT_PR_BODY_BEGIN` / `END` pair as the body. A cursor.com
footer after `END` is packaging. It is not a second copy.

The check fails when:

- required headings appear both inside and outside the markers
- more than one BEGIN/END pair wraps the body

Markers alone do not fail. A single footer alone does not fail.

On any later replace, strip markers and footer first. Validate the clean
six-section text. Set that clean text once. If ManagePullRequest wraps it
again, you still have one copy inside the markers.

## 1. Write the full body first

Write the six sections before you open the PR:

1. TL;DR
2. How it works (with a mermaid diagram)
3. Summary
4. Files changed
5. How to test (Unit / Smoke / End-to-end)
6. Review

Do not leave Pending, TBD, TODO, or "paste the body" notes.

Save the body in a file. Keep a copy at `docs/pr-<n>-clean-body.md` in the
Project store after the number is known.

## 2. Open or set the body once

Prefer:

```bash
PR_HEAD_SHA=$(git rev-parse HEAD) python3 scripts/pr_body.py set --pr N --file PATH
```

That runs `gh pr edit N --body-file` for a full replace.

If `gh` returns 403, paste the clean six-section body once through
ManagePullRequest. Do not paste a second copy. The tool will add markers and
the cursor.com footer around that one body.

## 3. Check locally

```bash
PR_HEAD_SHA=$(git rev-parse HEAD) python3 scripts/pr_body.py check PATH
# or against a live dump:
PR_HEAD_SHA=$(git rev-parse HEAD) python3 scripts/check_pr_body.py PATH
```

## 4. Start independent review before you wait on CI

Start the independent review as soon as the PR exists.

Do not wait for the CI matrix before review.

Do not call the PR ready until review finishes.

## 5. Replace only the Review section

After review, keep the first five sections.

Replace only `## Review` with fixed / accepted / rejected findings.

Name the current head sha (short form is ok).

Set the body again with `scripts/pr_body.py set` (or one ManagePullRequest
paste of the clean file if `gh` is 403).

## 6. Ready means the gates pass

Copyable gate: `.github/workflows/pr-standards.yml` runs
`scripts/check_pr_body.py`.

Cairnkit-only gates: identity and review-gate in `.github/workflows/ci.yml`.

review-gate requires a Review at the current head sha.

Do not merge from the agent. Matthew lands by fast-forward.
