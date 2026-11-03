"""A busy memory for a project of some weeks: about 50 active facts, rules and a status note.

The shape follows one real project (counts per kind and area, text lengths, pinned facts, rules
with basis told, facts that searches looked up). All text is made up for this kit.
"""

from __future__ import annotations

T = "told"


def _fact(text, area, kind="fact", age=3, basis="seen", pinned=False) -> dict:
    """The fields of a `SeedFact`. It lives in `scenarios`, which reads this module."""
    return {
        "text": text,
        "area": area,
        "kind": kind,
        "age_days": age,
        "basis": basis,
        "pinned": pinned,
    }


# (fields, looked up) pairs. A lookup gives a fact a `use` score, as a search in a session does.
_FACTS: tuple[tuple[dict, bool], ...] = (
    (
        _fact(
            "Agents never push to main. Each change goes on a branch and a pull request, and the "
            "owner merges.",
            "process",
            "rule",
            9,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Commit messages use plain English in the imperative, one subject line under 72 "
            "characters, and no attribution to a tool.",
            "commits",
            "rule",
            9,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Run `make check` before each commit. It runs the linter, the type check and the unit "
            "tests, and a red check blocks the commit.",
            "process",
            "rule",
            8,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Never print or store a value from .env or from the secrets folder, also not in a log "
            "line or a test fixture. Use the name of the variable instead.",
            "secrets",
            "rule",
            8,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Each worktree of an agent lives under .claude/worktrees and gets removed after its "
            "branch is merged. Do not leave a worktree with uncommitted edits behind.",
            "worktrees",
            "rule",
            5,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Ask before a change to the database schema. A migration needs a down step and a dry "
            "run against the copy of last night's backup.",
            "database",
            "rule",
            4,
            T,
        ),
        False,
    ),
    (
        _fact(
            "The rota app is one Flask service with a Postgres database and a worker for mail. "
            "Volunteers sign up for kitchen shifts, and coordinators approve the swaps. The owner "
            "chose one service over a split API and front end, because one person runs it in the "
            "evenings and each extra part is one more thing to restart and to watch.",
            "rota",
            "decision",
            9,
            T,
            True,
        ),
        True,
    ),
    (
        _fact(
            "Production runs on one small VM behind Caddy. A deploy is a tag push, and the deploy "
            "job restarts the service with no downtime window. Staging is a second VM with the "
            "same setup and a copy of the data from the night before, with the mail addresses "
            "masked.",
            "deploy",
            "decision",
            9,
            T,
            True,
        ),
        True,
    ),
    (
        _fact(
            "The owner wants short answers: say what changed and what is left, then stop. No "
            "tables unless he asks for one, and no summary of each file that was read. When a "
            "choice is his, ask one clear question and wait, and do not guess an answer for him "
            "to correct later.",
            "process",
            "preference",
            8,
            T,
            True,
        ),
        False,
    ),
    (
        _fact(
            "Screens must work on an old phone at 360 pixels wide, because most volunteers sign up "
            "from a phone in the kitchen. Test each new screen at that width before a pull "
            "request. Buttons are at least 44 pixels high, and no text is smaller than 16 pixels, "
            "because many volunteers are older and read without glasses in the kitchen.",
            "design",
            "preference",
            7,
            T,
            True,
        ),
        True,
    ),
    (
        _fact(
            "The shift swap flow stays two steps: the volunteer asks, a coordinator approves. An "
            "automatic swap was tried in the spring and caused double bookings, so it is out. A "
            "coordinator can also move a volunteer to another shift with no request, and the app "
            "sends both people a mail.",
            "rota",
            "decision",
            7,
            T,
            True,
        ),
        True,
    ),
    (
        _fact(
            "Before a merge, read the whole diff against main, not only the last commit. Two bad "
            "merges came from a branch that had stale commits under a clean last commit.",
            "review",
            "rule",
            6,
            T,
            True,
        ),
        False,
    ),
    (
        _fact(
            "The test database resets only when the schema hash changes. After a manual edit of a "
            "fixture, run `make db-reset`, or the tests read the old rows and pass for the wrong "
            "reason.",
            "database",
            "trap",
            6,
            "seen",
            True,
        ),
        True,
    ),
    (
        _fact(
            "The deploy job fails with a cryptic 'unit not found' when the tag has a leading v. "
            "Tags are plain numbers such as 2026.10.3.",
            "deploy",
            "trap",
            8,
        ),
        True,
    ),
    (
        _fact(
            "Caddy caches the static bundle for a day. After a deploy that changes CSS, bump the "
            "asset version in config/assets.toml or phones keep the old styles.",
            "deploy",
            "trap",
            5,
        ),
        True,
    ),
    (
        _fact(
            "Staging shares the mail worker queue name with production unless MAIL_QUEUE is set. "
            "A staging test once sent real reminders to 40 volunteers.",
            "mail",
            "trap",
            7,
        ),
        True,
    ),
    (
        _fact(
            "The reminder mail goes out at 07:00 local time the day before a shift. The worker "
            "reads the time zone of each kitchen, not of the server.",
            "mail",
            "fact",
            6,
        ),
        True,
    ),
    (
        _fact(
            "Mail templates live in templates/mail and render with the same Jinja setup as the "
            "pages. A missing variable renders as empty text, with no error.",
            "templates",
            "trap",
            4,
        ),
        True,
    ),
    (
        _fact(
            "The page templates use one base layout with three blocks: head, main and foot. A new "
            "page extends base.html and never copies the header.",
            "templates",
            "decision",
            6,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Coordinators see a weekly grid of shifts, volunteers see a list. The two views share "
            "one query, and its filter for the role is the only difference.",
            "rota",
            "fact",
            5,
        ),
        True,
    ),
    (
        _fact(
            "A shift that starts before 06:00 counts for the day before in the weekly totals, "
            "because the night kitchen closes at 06:00. This is on purpose.",
            "rota",
            "decision",
            5,
            T,
        ),
        True,
    ),
    (
        _fact(
            "The weekly totals job and the swap approval both lock the shift row. Run them at "
            "different minutes, or a swap times out during the job.",
            "rota",
            "trap",
            4,
        ),
        True,
    ),
    (
        _fact(
            "Donations go through the payment provider's hosted page only. The app never sees a "
            "card number, and it stores only the receipt id and the amount.",
            "payments",
            "decision",
            8,
            T,
        ),
        True,
    ),
    (
        _fact(
            "The payment webhook can arrive twice for one donation. The handler keys on the "
            "receipt id, so a repeat is a no-op.",
            "payments",
            "fact",
            6,
        ),
        True,
    ),
    (
        _fact(
            "Refunds are manual in the provider's dashboard. The app shows a refunded donation "
            "after the next nightly sync, not at once.",
            "payments",
            "event",
            3,
        ),
        False,
    ),
    (
        _fact(
            "The colors and the type scale come from the kitchen's printed flyers. The owner "
            "chose the dark green header and the larger body text for older volunteers.",
            "design",
            "decision",
            7,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Icons are inline SVG from one sprite file. An icon font was dropped because it "
            "showed empty boxes on two older phones.",
            "design",
            "decision",
            4,
            T,
        ),
        True,
    ),
    (
        _fact(
            "GitHub Actions runs `make check` on each pull request and blocks a merge when it is "
            "red. The job caches the uv folder by the hash of uv.lock.",
            "github",
            "fact",
            8,
        ),
        True,
    ),
    (
        _fact(
            "A pull request description says why first, then what changed, then how it was "
            "tested. Screens get a phone screenshot.",
            "github",
            "decision",
            6,
            T,
        ),
        False,
    ),
    (
        _fact(
            "The CI job for screenshots is flaky on the first run after a cache miss. A rerun "
            "passes. Do not change the test for it.",
            "github",
            "trap",
            3,
        ),
        True,
    ),
    (
        _fact(
            "Dependabot pull requests for minor versions merge after a green check, with no "
            "review. Major versions wait for the owner.",
            "github",
            "decision",
            5,
            T,
        ),
        False,
    ),
    (
        _fact(
            "The branch protection on main was set to require one approval and a green check, so "
            "a direct push now fails for each account.",
            "github",
            "event",
            7,
        ),
        False,
    ),
    (
        _fact(
            "The release notes are written by hand in docs/releases.md from the merged pull "
            "requests. One line for each change that a volunteer or a coordinator would notice.",
            "release",
            "decision",
            6,
            T,
        ),
        True,
    ),
    (
        _fact(
            "Release 2026.10.3 went out with the new swap screen and the phone layout fixes. No "
            "rollback was needed.",
            "release",
            "event",
            4,
        ),
        False,
    ),
    (
        _fact(
            "A release waits until after the Sunday dinner shift, because most sign-ups for the "
            "next week happen on Sunday afternoon.",
            "release",
            "decision",
            5,
            T,
        ),
        True,
    ),
    (
        _fact(
            "The database runs on Postgres 16. The ORM is SQLAlchemy 2 with typed models, and "
            "each query sits in the repository module of its area.",
            "database",
            "fact",
            9,
        ),
        True,
    ),
    (
        _fact(
            "An index on shifts(kitchen_id, starts_at) made the weekly grid ten times faster. Keep "
            "it when the table changes.",
            "database",
            "lesson",
            5,
        ),
        True,
    ),
    (
        _fact(
            "The worker and the web service read the same .env file. A secret added for one must "
            "be in the deploy secrets of both, or the worker starts without it.",
            "secrets",
            "trap",
            6,
        ),
        True,
    ),
    (
        _fact(
            "The project uses Python 3.12 with uv. Run each tool with `uv run`, and add packages "
            "with `uv add`, never with pip.",
            "python",
            "decision",
            9,
            T,
        ),
        True,
    ),
    (
        _fact(
            "Type hints are required in new code, and the type check runs in strict mode for the "
            "rota and payments packages only.",
            "python",
            "decision",
            7,
            T,
        ),
        False,
    ),
    (
        _fact(
            "Two agents on two worktrees once edited the same migration file. Since then each "
            "migration gets its number at merge time, not at branch time.",
            "worktrees",
            "lesson",
            6,
        ),
        True,
    ),
    (
        _fact(
            "The feedback form at the foot of each page sends a mail to the coordinators' list. "
            "It has no account check, so it has a rate limit of five a minute.",
            "feedback",
            "fact",
            5,
        ),
        True,
    ),
    (
        _fact(
            "Feedback from the pilot kitchen: the sign-up button was too small and the date was "
            "hard to read. Both were fixed in the phone layout work.",
            "feedback",
            "event",
            4,
        ),
        False,
    ),
    (
        _fact(
            "The README covers setup and the make targets only. How-to pages for coordinators "
            "live in docs/guide and are written for people who do not code.",
            "docs",
            "decision",
            7,
            T,
        ),
        False,
    ),
    (
        _fact(
            "The coordinator guide got a page on swaps and a page on the weekly grid, with "
            "screenshots from a phone.",
            "docs",
            "event",
            3,
        ),
        False,
    ),
    (
        _fact(
            "The second kitchen joined the pilot this week. Its shifts start an hour earlier, and "
            "its coordinators asked for a printable grid.",
            "rota",
            "event",
            2,
        ),
        False,
    ),
    (
        _fact(
            "Open question for the owner: should the reminder mail go out 24 or 48 hours before a "
            "shift? He decides after the pilot week. Until then it stays at the day before.",
            "mail",
            "decision",
            3,
            T,
        ),
        True,
    ),
    (
        _fact(
            "The printable grid is a plain HTML page with a print style sheet, not a PDF. The "
            "owner chose this so that it needs no new package.",
            "rota",
            "decision",
            2,
            T,
        ),
        True,
    ),
    (
        _fact(
            "The swap approval mail now names both volunteers and the shift time. Coordinators "
            "asked for it after a mix-up.",
            "mail",
            "event",
            2,
        ),
        False,
    ),
    (
        _fact(
            "Kitchen time zones are stored per kitchen, and each date on a page shows in the time "
            "of the kitchen of that shift.",
            "rota",
            "decision",
            3,
            T,
        ),
        True,
    ),
    (
        _fact(
            "The worker restarts after each deploy, and mail that was due during the restart goes "
            "out at the next minute. No mail is lost.",
            "deploy",
            "fact",
            4,
        ),
        True,
    ),
    (
        _fact(
            "A new page gets a test that renders it at 360 pixels wide and checks that no element "
            "is wider than the screen.",
            "design",
            "decision",
            1,
            T,
        ),
        False,
    ),
)

FACTS: tuple[dict, ...] = tuple(fields for fields, _ in _FACTS)
LOOKED_UP: tuple[str, ...] = tuple(fields["text"] for fields, used in _FACTS if used)

# A line that goes on starts with two spaces, so that the source stays short. The note has none.
STATUS_NOTE = """# Status

Last updated by a session three days ago, after the release of 2026.10.3 and the first week of the
  pilot in the second kitchen.

## Now
- Phone layout work is merged and released in 2026.10.3. Two small fixes for the date picker on
  old Android phones are still open on branch date-picker-fix.
- The second kitchen joins the pilot. Its shifts start an hour earlier, and its coordinators want a
  printable grid for the wall of the kitchen.
- The printable grid for coordinators is in review on branch print-grid. It needs the print style
  sheet and a test at A4 size.
- The weekly totals job moved to minute 17 so that swaps do not time out. Watch the log of the job
  for one more week before the ticket closes.

## Next
- Finish the printable grid and its print style sheet.
- Add the kitchen time zone to the shift pages that still show server time.
- Write the coordinator guide page for the printable grid.
- Look at the slow sign-up page on the old phones of the pilot kitchen.
- Split the mail worker log by kitchen.

## Waiting on the owner
- Reminder lead time: 24 or 48 hours before a shift. After the pilot week.

## Done this month
- Shift swap screen with coordinator approval.
- Phone layout at 360 pixels for each page.
- Index on shifts by kitchen and start time.
- Feedback form with a rate limit.
- Donation receipts keyed on the receipt id.
- Hand-written release notes in docs/releases.md.
- Branch protection on main.
- Dependabot rule for minor versions.
- Inline SVG icons in place of the icon font.
- Base layout with head, main and foot blocks.
- Reminder mail in the time zone of each kitchen.
- The swap approval mail names both volunteers.
- Coordinator guide pages for swaps and the weekly grid.

## Notes
- The staging VM is small. Do not run the load test there.
- Screenshots in CI are flaky after a cache miss. A rerun passes.
- The old mirror for backups is slow on Mondays.
""".replace("\n  ", " ")


def seed(box) -> None:
    """The status note, and a lookup of some facts, so that they carry a `use` score."""
    if not box.build.has_memory:
        return
    notes = box.memory_dir / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "status.md").write_text(STATUS_NOTE, encoding="utf-8")
    for text in LOOKED_UP:
        done = box.memory_cmd("show", box.seed_ids[text])
        if done.returncode != 0:
            raise RuntimeError(f"memory show for a busy fact failed: {done.stderr[-200:]}")
