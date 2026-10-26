"""Starting the command and building its parser must not import the whole package."""

import subprocess
import sys

import pytest

from cairnkit.cli import AGENTS, build_parser

# The only package modules the parser may load. Any other import at the top of cli.py fails this.
LIGHT = ("cairnkit", "cairnkit.cli", "cairnkit.clock", "cairnkit.schema")

SCRIPT = """
import sys
from cairnkit.cli import build_parser
build_parser()
print(",".join(sorted(n for n in sys.modules if n == "cairnkit" or n.startswith("cairnkit."))))
print(",".join(n for n in ("urllib.request", "tarfile") if n in sys.modules))
"""


def test_building_the_parser_imports_only_light_modules():
    result = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    loaded, stdlib = result.stdout.splitlines()
    assert set(loaded.split(",")) <= set(LIGHT)
    assert stdlib == ""


def test_agent_choices():
    assert AGENTS == ("claude", "codex", "cursor", "generic")
    args = build_parser().parse_args(["hook", "stop", "--agent", "codex"])
    assert args.agent == "codex"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["hook", "stop", "--agent", "bogus"])
