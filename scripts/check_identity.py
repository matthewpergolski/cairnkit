#!/usr/bin/env python3
"""Fail when a commit range is not under the neutral cairnkit identity.

Allowed identity (author, committer, and Co-authored-by / Signed-off-by):

  cairnkit contributors <cairnkit@users.noreply.github.com>

Also fails when a commit's added lines introduce a personal-looking email
address other than that neutral address. Generic placeholders such as
git@github.com and *@example.* are allowed in file text. Paths under
tests/ are skipped for the file-text scan so fixtures may use synthetic
addresses; author, committer, and trailers are still checked on every commit.

On push checks only, `--allow-github-squash --owner LOGIN` also accepts a
GitHub UI squash merge: committer `GitHub <noreply@github.com>`, author
email the owner's `users.noreply.github.com` address, subject ending in
`(#N)`. Trailers on that commit must still be the neutral identity.

On a pull request, `--check-simulated-squash` builds that squash shape from
the PR title, number, and body and runs the push-mode check so a bad
squash fails before it lands on main.

Usage:
  python3 scripts/check_identity.py [BASE..HEAD]
  python3 scripts/check_identity.py origin/main..HEAD
  python3 scripts/check_identity.py --allow-github-squash --owner LOGIN BASE..HEAD
  python3 scripts/check_identity.py --check-simulated-squash --owner LOGIN \
    --pr-number N --title TITLE [--body-file PATH]

Exit 0 when clean, 1 when problems are found, 2 on usage/git errors.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_NAME = "cairnkit contributors"
ALLOWED_EMAIL = "cairnkit@users.noreply.github.com"
ALLOWED = f"{ALLOWED_NAME} <{ALLOWED_EMAIL}>"

# GitHub's squash-merge committer. Author is the person who pressed Merge.
GITHUB_COMMITTER_NAME = "GitHub"
GITHUB_COMMITTER_EMAIL = "noreply@github.com"
_SQUASH_SUBJECT = re.compile(r".*\(#\d+\)\s*$")
_OWNER_NOREPLY = re.compile(
    r"^(?:(?P<id>\d+)\+)?(?P<login>[A-Za-z0-9-]+)@users\.noreply\.github\.com$",
    re.I,
)

# Placeholders that docs and tests may show. Not a personal inbox.
_GENERIC_EMAIL = re.compile(
    r"^(?:"
    r"git@github\.com|"
    r"[A-Za-z0-9._%+\-]+@example\.(?:com|org|net|invalid)"
    r")$",
    re.I,
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_TRAILER = re.compile(
    r"^(Co-authored-by|Signed-off-by):\s*(.+?)\s*$",
    re.I | re.M,
)
_TRAILER_VALUE = re.compile(r"^(.+?)\s*<([^>]+)>\s*$")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def identity_ok(name: str, email: str) -> bool:
    return name == ALLOWED_NAME and email.lower() == ALLOWED_EMAIL.lower()


def email_ok_in_text(email: str) -> bool:
    """True when an address may appear in added file lines."""
    low = email.lower()
    if low == ALLOWED_EMAIL.lower():
        return True
    return bool(_GENERIC_EMAIL.match(email))


def author_is_owner(email: str, owner: str) -> bool:
    """True when email is the GitHub noreply address for `owner`."""
    match = _OWNER_NOREPLY.match(email.strip())
    if not match:
        return False
    return match.group("login").lower() == owner.strip().lower()


def is_github_squash_merge(
    email: str,
    committer: str,
    cemail: str,
    body: str,
    owner: str,
) -> bool:
    """True for a GitHub UI squash merge of PR #N by `owner`.

    Committer is GitHub; author email is the owner's users.noreply address;
    the subject ends with `(#N)`.
    """
    if not owner:
        return False
    subject = body.split("\n", 1)[0].rstrip()
    return (
        committer == GITHUB_COMMITTER_NAME
        and cemail.lower() == GITHUB_COMMITTER_EMAIL
        and author_is_owner(email, owner)
        and bool(_SQUASH_SUBJECT.match(subject))
    )


def _parse_trailer_value(value: str) -> tuple[str, str] | None:
    match = _TRAILER_VALUE.match(value.strip())
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def check_commit(
    sha: str,
    author: str,
    email: str,
    committer: str,
    cemail: str,
    body: str,
    *,
    allow_github_squash: bool = False,
    owner: str | None = None,
) -> list[str]:
    """Return problem lines for one commit's identity and trailers.

    With `allow_github_squash` and `owner`, a GitHub squash-merge commit may
    use the owner as author and GitHub as committer. Trailers still must be
    the neutral cairnkit identity (no AI attribution).
    """
    errors: list[str] = []
    short = sha[:7]
    squash = allow_github_squash and is_github_squash_merge(
        email, committer, cemail, body, owner or ""
    )
    if not squash:
        if not identity_ok(author, email):
            errors.append(f"{short}: author {author} <{email}> (want {ALLOWED})")
        if not identity_ok(committer, cemail):
            errors.append(f"{short}: committer {committer} <{cemail}> (want {ALLOWED})")
    for match in _TRAILER.finditer(body):
        kind, value = match.group(1), match.group(2)
        parsed = _parse_trailer_value(value)
        if parsed is None:
            errors.append(f"{short}: {kind} has no Name <email>: {value!r}")
            continue
        name, addr = parsed
        if not identity_ok(name, addr):
            errors.append(f"{short}: {kind} {name} <{addr}> (want {ALLOWED})")
    return errors


def check_added_text(sha: str, path: str, text: str) -> list[str]:
    """Return problems for personal-looking emails in added lines."""
    errors: list[str] = []
    short = sha[:7]
    for line in text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for addr in _EMAIL.findall(line):
            if not email_ok_in_text(addr):
                errors.append(
                    f"{short}: added {path} has {addr} (only {ALLOWED_EMAIL} or generic examples)"
                )
    return errors


def check_range(
    repo: Path | str,
    rev_range: str,
    *,
    allow_github_squash: bool = False,
    owner: str | None = None,
) -> list[str]:
    """Check every commit in rev_range. Return problem lines (empty when clean)."""
    root = Path(repo)
    listed = _run(root, "rev-list", rev_range)
    if listed.returncode != 0:
        detail = listed.stderr.strip() or listed.stdout.strip()
        return [f"git rev-list failed for {rev_range!r}: {detail}"]
    shas = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    errors: list[str] = []
    for sha in shas:
        meta = _run(
            root,
            "show",
            "-s",
            "--format=%an%n%ae%n%cn%n%ce%n%B",
            sha,
        )
        if meta.returncode != 0:
            errors.append(f"{sha[:7]}: git show failed")
            continue
        parts = meta.stdout.split("\n", 4)
        if len(parts) < 5:
            errors.append(f"{sha[:7]}: could not parse commit metadata")
            continue
        author, email, committer, cemail, body = parts
        errors += check_commit(
            sha,
            author,
            email,
            committer,
            cemail,
            body,
            allow_github_squash=allow_github_squash,
            owner=owner,
        )
        diff = _run(root, "show", "--format=", "--unified=0", sha)
        if diff.returncode != 0:
            errors.append(f"{sha[:7]}: git show diff failed")
            continue
        path = ""
        chunk: list[str] = []
        for line in diff.stdout.splitlines():
            if line.startswith("diff --git "):
                if path and chunk and not _skip_file_email_scan(path):
                    errors += check_added_text(sha, path, "\n".join(chunk))
                chunk = []
                # diff --git a/path b/path
                bits = line.split(" b/", 1)
                path = bits[1] if len(bits) == 2 else line
            elif line.startswith("+++ "):
                continue
            else:
                chunk.append(line)
        if path and chunk and not _skip_file_email_scan(path):
            errors += check_added_text(sha, path, "\n".join(chunk))
    return errors


def _skip_file_email_scan(path: str) -> bool:
    """True when added-line email rules do not apply (test fixtures)."""
    norm = path.replace("\\", "/").lstrip("./")
    return norm == "tests" or norm.startswith("tests/")


def owner_noreply_email(owner: str, *, github_id: str | None = None) -> str:
    """The users.noreply.github.com address for a login (optional numeric id)."""
    login = owner.strip()
    if github_id:
        return f"{github_id}+{login}@users.noreply.github.com"
    return f"{login}@users.noreply.github.com"


def simulate_github_squash(
    repo: Path | str,
    *,
    owner: str,
    pr_number: int,
    title: str,
    body: str,
    author_name: str | None = None,
    author_email: str | None = None,
    tree_ish: str = "HEAD",
    parent: str | None = None,
) -> str:
    """Create a dangling commit shaped like a GitHub squash merge. Return its SHA.

    Author is the repo owner (noreply). Committer is GitHub. Subject is
    ``{title} (#{pr_number})``. Does not update any branch ref.
    """
    root = Path(repo)
    email = author_email or owner_noreply_email(owner)
    name = author_name or owner
    subject = f"{title.rstrip()} (#{int(pr_number)})"
    message = subject if not body.strip() else f"{subject}\n\n{body.lstrip()}"
    tree = _run(root, "rev-parse", f"{tree_ish}^{{tree}}")
    if tree.returncode != 0:
        raise RuntimeError(tree.stderr.strip() or "rev-parse tree failed")
    parent_sha = parent
    if parent_sha is None:
        head = _run(root, "rev-parse", tree_ish)
        if head.returncode != 0:
            raise RuntimeError(head.stderr.strip() or "rev-parse HEAD failed")
        parent_sha = head.stdout.strip()
    env = {
        **dict(__import__("os").environ),
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": GITHUB_COMMITTER_NAME,
        "GIT_COMMITTER_EMAIL": GITHUB_COMMITTER_EMAIL,
    }
    made = subprocess.run(
        ["git", "commit-tree", tree.stdout.strip(), "-p", parent_sha],
        cwd=root,
        input=message,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if made.returncode != 0:
        raise RuntimeError(made.stderr.strip() or "commit-tree failed")
    return made.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "range",
        nargs="?",
        default="origin/main..HEAD",
        help="git revision range (default: origin/main..HEAD)",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="git repository path (default: .)",
    )
    parser.add_argument(
        "--allow-github-squash",
        action="store_true",
        help="accept GitHub squash merges by --owner (push checks only)",
    )
    parser.add_argument(
        "--owner",
        default="",
        help="GitHub login of the repo owner (with --allow-github-squash)",
    )
    parser.add_argument(
        "--check-simulated-squash",
        action="store_true",
        help="build a fake GitHub squash for a PR and run the push-mode check",
    )
    parser.add_argument("--pr-number", type=int, default=0, help="PR number for --check-simulated-squash")
    parser.add_argument("--title", default="", help="PR title for --check-simulated-squash")
    parser.add_argument(
        "--body-file",
        default="",
        help="file with the PR body (for --check-simulated-squash)",
    )
    parser.add_argument(
        "--author-name",
        default="",
        help="squash author name (default: --owner)",
    )
    parser.add_argument(
        "--author-email",
        default="",
        help="squash author email (default: owner@users.noreply.github.com)",
    )
    parser.add_argument(
        "--tree-ish",
        default="HEAD",
        help="tree for the simulated squash (default: HEAD)",
    )
    parser.add_argument(
        "--parent",
        default="",
        help="parent commit of the simulated squash (default: tree-ish)",
    )
    args = parser.parse_args(argv)
    owner = args.owner or None
    root = Path(args.repo)

    if args.check_simulated_squash:
        if not owner or not args.pr_number or not args.title:
            print(
                "error: --check-simulated-squash needs --owner, --pr-number, and --title",
                file=sys.stderr,
            )
            return 2
        body = ""
        if args.body_file:
            try:
                body = Path(args.body_file).read_text(encoding="utf-8")
            except OSError as exc:
                print(f"error: cannot read --body-file: {exc}", file=sys.stderr)
                return 2
        try:
            sha = simulate_github_squash(
                root,
                owner=owner,
                pr_number=args.pr_number,
                title=args.title,
                body=body,
                author_name=args.author_name or None,
                author_email=args.author_email or None,
                tree_ish=args.tree_ish,
                parent=args.parent or None,
            )
        except RuntimeError as exc:
            print(f"error: simulate squash failed: {exc}", file=sys.stderr)
            return 2
        rev = f"{sha}^!"
        problems = check_range(root, rev, allow_github_squash=True, owner=owner)
        if not problems:
            print(f"identity: ok (simulated squash {sha[:7]} for #{args.pr_number})")
            return 0
        print(
            f"identity: {len(problems)} problem(s) in simulated squash for #{args.pr_number}",
            file=sys.stderr,
        )
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        print(
            "Fix: remove AI trailers from the PR body, or use the neutral identity "
            f"({ALLOWED}) on branch commits.",
            file=sys.stderr,
        )
        return 1

    if args.allow_github_squash and not owner:
        print("error: --allow-github-squash needs --owner LOGIN", file=sys.stderr)
        return 2
    problems = check_range(
        root,
        args.range,
        allow_github_squash=args.allow_github_squash,
        owner=owner,
    )
    if not problems:
        print(f"identity: ok ({args.range})")
        return 0
    print(f"identity: {len(problems)} problem(s) in {args.range}", file=sys.stderr)
    for line in problems:
        print(f"error: {line}", file=sys.stderr)
    print(f"Fix: use {ALLOWED} for author, committer, and trailers.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
