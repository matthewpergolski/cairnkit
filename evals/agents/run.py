"""Run real agents against arms of cairnkit, and no memory. See README.md in this folder."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agent_eval import runner, sandbox, scoring  # noqa: E402
from agent_eval.agents import AGENTS  # noqa: E402
from agent_eval.scenarios import SCENARIOS, selected  # noqa: E402

ARM_LABEL = re.compile(r"[a-z0-9][a-z0-9._+-]*\Z")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=sorted(AGENTS), default="claude")
    parser.add_argument("--repeats", type=int, default=3, help="runs per scenario per build")
    parser.add_argument(
        "--scenario",
        action="append",
        help=f"one id or letter, repeatable. Ids: {', '.join(SCENARIOS)}",
    )
    parser.add_argument("--model", help="the model for the agent. Default: its small model")
    parser.add_argument("--fake-provider", action="store_true", help="no account and no cost")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and the cost shape")
    parser.add_argument(
        "--load-only", action="store_true", help="show what `memory load` holds. No agent runs"
    )
    parser.add_argument("--prod-ref", default=sandbox.PROD_REF)
    parser.add_argument("--dev-ref", default="HEAD", help="default: the current checkout")
    parser.add_argument(
        "--arm",
        action="append",
        default=[],
        metavar="LABEL=REF",
        help="one more memory arm from a git ref, repeatable",
    )
    parser.add_argument(
        "--skip-arm", action="append", default=[], metavar="LABEL", help="leave out one arm"
    )
    parser.add_argument("--out", type=Path, help="default: evals/agents/results/<time>-<agent>")
    parser.add_argument("--builds-dir", type=Path, help="default: a folder in the system temp dir")
    parser.add_argument("--timeout", type=float, default=300, help="seconds per agent session")
    parser.add_argument("--budget-usd", type=float, default=0.25, help="Claude: cap per session")
    parser.add_argument("--keep", action="store_true", help="keep the throwaway repos")
    parser.add_argument("--report", type=Path, help="rebuild the table from a result folder")
    return parser.parse_args(argv)


def repo_root() -> Path:
    done = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=HERE,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(done.stdout.strip())


def arm_refs(args: argparse.Namespace) -> dict[str, str | None]:
    """Label to git ref, in table order. A ref of None is the arm with no memory."""
    refs: dict[str, str | None] = {"dev": args.dev_ref, "prod": args.prod_ref}
    for item in args.arm:
        label, _, ref = item.partition("=")
        if not ref or not ARM_LABEL.match(label) or label in (*refs, scoring.NO_MEMORY):
            raise ValueError(f"--arm needs a new LABEL=REF, not {item!r}")
        refs[label] = ref
    refs[scoring.NO_MEMORY] = None
    unknown = set(args.skip_arm) - set(refs)
    if unknown:
        raise ValueError(f"--skip-arm names no arm: {', '.join(sorted(unknown))}")
    return {label: ref for label, ref in refs.items() if label not in args.skip_arm}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.report:
        rows = runner.read_rows(args.report)
        order = [s.id for s in SCENARIOS.values() if any(r["scenario"] == s.id for r in rows)]
        print(scoring.render_report(rows, order), end="")
        return 0

    agent = AGENTS[args.agent]
    model = args.model or agent.default_model
    out_dir = args.out or HERE / "results" / f"{runner.stamp()}-{agent.name}"
    try:
        refs = arm_refs(args)
        scenarios = selected(args.scenario, fake=args.fake_provider)
    except ValueError as exc:
        print(f"run.py: {exc}", file=sys.stderr)
        return 2
    options = runner.Options(
        agent=agent,
        scenarios=scenarios,
        repeats=args.repeats,
        out_dir=out_dir,
        fake=args.fake_provider,
        model=model,
        timeout=args.timeout,
        budget_usd=args.budget_usd,
        keep=args.keep,
    )
    if args.dry_run:
        print(runner.plan_text(options, refs), end="")
        return 0

    repo = repo_root()
    commits = {label: sandbox.resolve_commit(repo, ref) for label, ref in refs.items() if ref}
    if len(set(commits.values())) < len(commits):
        print(
            f"run.py: two arms are the same commit ({', '.join(commits)}), so a comparison means "
            "nothing. Run from a dev checkout, or pass --dev-ref.",
            file=sys.stderr,
        )
        return 2
    builds_dir = args.builds_dir or Path(tempfile.gettempdir()) / "cairnkit-agent-eval-builds"
    try:
        options.builds = runner.build_arms(repo, refs, builds_dir)
    except sandbox.SetupError as exc:
        print(f"run.py: could not build: {exc}", file=sys.stderr)
        return 2
    if args.load_only:
        print(runner.load_only(options), end="")
        return 0

    rows = runner.run_all(options)
    report = scoring.render_report(rows, [s.id for s in scenarios])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print()
    print(report, end="")
    print(f"\nResults: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
