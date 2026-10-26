"""`memory add` never blocks: it supersedes an exact repeat and flags a near one."""

import pytest
from conftest import make_fact, read_jsonl, write_facts

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project

OLD = "f-20261001-0001"
BASE = ["--area", "deploy", "--basis", "seen", "--source", "commit:abc1234"]
NEAR_TEXT = "The cache must be warmed before the release job runs."
NEAR_VARIANT = "The cache must be warmed before the release job runs now."


def add(capsys, text, *extra):
    capsys.readouterr()
    code = main(["add", text, *BASE, *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def state(fid):
    return Memory.open(find_project(), None).states[fid]


def new_id(out):
    return next(w for w in out.split() if w.startswith("f-2026") and w != OLD).strip(";:.,")


def test_exact_repeat_supersedes_the_old_fact(mem, capsys):
    write_facts(mem, [make_fact(OLD, "Deploys need a clean tree.")])
    code, out, _ = add(capsys, "deploys need a CLEAN tree!")
    new = out.strip().split()[-1]
    assert code == 0 and OLD in out
    assert state(OLD)["status"] == "superseded" and state(OLD)["superseded_by"] == new
    assert state(new)["status"] == "active"
    changes = [r for r in read_jsonl(mem / "facts" / "main.jsonl") if r["type"] == "change"]
    assert changes[0]["reason"]


@pytest.mark.parametrize("extra", [{"pinned": True}, {"kind": "rule"}])
def test_exact_repeat_of_a_rule_or_pinned_fact_writes_nothing_and_succeeds(mem, capsys, extra):
    write_facts(mem, [make_fact(OLD, "Always run the tests.", **extra)])
    before = (mem / "facts" / "main.jsonl").read_bytes()
    args = ["--kind", "rule"] if extra.get("kind") == "rule" else []
    code, out, _ = add(capsys, "Always run the tests.", *args)
    assert code == 0 and OLD in out and "already exists" in out
    assert (mem / "facts" / "main.jsonl").read_bytes() == before


def test_near_repeat_is_written_with_a_similar_to_link(mem, capsys):
    write_facts(mem, [make_fact(OLD, NEAR_TEXT)])
    code, out, _ = add(capsys, NEAR_VARIANT)
    assert code == 0
    new = new_id(out)
    assert {"rel": "similar_to", "id": OLD} in state(new)["links"]
    assert state(OLD)["status"] == "active" and state(new)["status"] == "active"
    assert f"memory change {OLD} --status superseded --superseded-by {new}" in out


def test_supersedes_still_works_and_skips_the_check(mem, capsys):
    write_facts(mem, [make_fact(OLD, NEAR_TEXT)])
    code, out, _ = add(capsys, NEAR_VARIANT, "--supersedes", OLD)
    assert code == 0
    assert state(OLD)["status"] == "superseded"
    assert state(new_id(out))["links"] == []


def test_allow_similar_is_gone(mem, capsys):
    with pytest.raises(SystemExit):
        main(["add", "x", *BASE, "--allow-similar"])


def test_unrelated_text_is_added_without_a_link(mem, capsys):
    write_facts(mem, [make_fact(OLD, "Deploys need a clean tree.")])
    code, out, _ = add(capsys, "Fonts load from the CDN.")
    assert code == 0 and state(OLD)["status"] == "active"
    assert state(new_id(out))["links"] == []


def test_other_kind_or_scope_is_not_similar(mem, capsys):
    write_facts(mem, [make_fact(OLD, "Deploys need a clean tree.")])
    assert add(capsys, "Deploys need a clean tree.", "--kind", "trap")[0] == 0
    assert add(capsys, "Deploys need a clean tree.", "--short")[0] == 0
    assert state(OLD)["status"] == "active"


def test_ended_fact_is_not_similar(mem, capsys):
    write_facts(mem, [make_fact(OLD, "Deploys need a clean tree.")])
    assert main(["change", OLD, "--status", "wrong", "--reason", "Not true."]) == 0
    assert add(capsys, "Deploys need a clean tree.")[0] == 0


# A pair whose differing words hold a number or a negation is not similar at all.
RETRY = "Retry the failed upload job up to 3 times with a short delay"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (RETRY, RETRY.replace("3", "5")),
        (RETRY, RETRY.replace("a short", "no short")),
        (RETRY, RETRY.replace("Retry", "Never retry").replace("3 times", "3 times, ever")),
        (
            "Do retry the failed upload job up to three times with a short delay",
            "Don't retry the failed upload job up to three times with a short delay",
        ),
        (
            "Caching is enabled for the build step in the CI pipeline for all branches",
            "Caching is disabled for the build step in the CI pipeline for all branches",
        ),
    ],
)
def test_a_number_or_a_negation_in_the_difference_means_not_similar(mem, capsys, old, new):
    write_facts(mem, [make_fact(OLD, old)])
    code, out, _ = add(capsys, new)
    assert code == 0
    assert state(new_id(out))["links"] == []
    assert state(OLD)["status"] == "active"


def test_an_ordinary_difference_is_still_flagged(mem, capsys):
    write_facts(mem, [make_fact(OLD, RETRY)])
    _, out, _ = add(capsys, RETRY.replace("short", "brief"))
    assert {"rel": "similar_to", "id": OLD} in state(new_id(out))["links"]


# --- the rule and the instructions that tell an agent to look first ---------


def test_basic_and_dev_presets_carry_the_search_first_rule(repo):
    from cairnkit.presets import load_preset

    basic = {r.key: r for r in load_preset("basic").rules}
    assert "memory search" in basic["basic.search-first"].text
    assert "--supersedes" in basic["basic.search-first"].text
    assert "basic.search-first" in load_preset("dev").include_rules


def test_instructions_tell_the_agent_to_search_before_it_adds(capsys):
    from cairnkit.instructions import text

    block = text()
    assert "Look before you add" in block
    assert "flagged" in block and "--allow-similar" not in block
