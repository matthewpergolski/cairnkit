"""Starting the command and building its parser must not import the whole package."""

import subprocess
import sys

HEAVY = (
    "cairnkit.hookrun",
    "cairnkit.autotidy",
    "cairnkit.memory",
    "cairnkit.load",
    "cairnkit.check",
    "cairnkit.skills",
    "cairnkit.update",
    "urllib.request",
    "tarfile",
)

SCRIPT = """
import sys
from cairnkit.cli import build_parser
build_parser()
print(",".join(name for name in {heavy!r} if name in sys.modules))
"""


def test_building_the_parser_imports_no_heavy_module():
    code = SCRIPT.format(heavy=HEAVY)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_agent_names_live_in_the_schema():
    from cairnkit import schema

    assert schema.AGENTS == ("claude", "codex", "cursor", "generic")
