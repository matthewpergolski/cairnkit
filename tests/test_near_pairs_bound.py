"""The similar-pair task is a short list that an agent can finish, at any size of memory."""

import io
import json
import os

import pytest
from conftest import make_fact, write_facts

from cairnkit import followups, similar
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.similar import differ_on_purpose

TASK = "proposals/tidy-followups.md"
NUMBERED = "Service node {i} handles queue traffic for region east on port 8080"
LONG = (
    f"{NUMBERED} and it restarts after a config change because the deploy tool writes the unit "
    "file first then signals the supervisor which reloads every worker in the pool at once"
)


def fid(number):
    return f"f-20261001-{number:04x}"


def seed(mem, count, shape=NUMBERED, start=0):
    write_facts(mem, [make_fact(fid(i), shape.format(i=i)) for i in range(start, start + count)])


def opened():
    return Memory.open(find_project(), None)


def session_start(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s", "source": "s"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize(
    ("a", "b", "apart"),
    [
        ("port 8080 on host", "port 9090 on host", True),
        ("retry 3 times wait 5 s", "retry 4 times wait 6 s", True),
        ("the staging database uses replicas", "the production database uses replicas", True),
        ("run the job", "run the job now", False),
        ("do run the job", "do not run the job", False),
        ("one two three four", "four three two one", False),
        ("one two three four", "one two five six", False),
    ],
)
def test_a_swapped_word_or_a_number_is_a_difference_on_purpose(a, b, apart):
    assert differ_on_purpose(similar.analyze(a), similar.analyze(b)) is apart


@pytest.mark.parametrize("count", [30, 300, 2000])
@pytest.mark.parametrize("shape", [NUMBERED, LONG], ids=["normal", "long"])
def test_facts_that_differ_by_a_number_are_no_task(mem, capsys, monkeypatch, count, shape):
    seed(mem, count, shape)
    out = session_start(capsys, monkeypatch)
    assert not (mem / TASK).exists()
    assert "Tidy follow-up" not in out
    assert followups.open_pairs(opened()) == []


def test_memory_add_of_a_numbered_fact_makes_no_task(mem, capsys):
    for number in (1, 2, 3):
        text = NUMBERED.format(i=number)
        assert main(["add", text, "--basis", "seen", "--source", "s:1"]) == 0
    assert not (mem / TASK).exists()


def test_a_real_pair_among_many_numbered_facts_is_found(mem):
    seed(mem, 2000)
    twin = "The release job warms the cache from the migration file in the build step"
    write_facts(
        mem,
        [
            make_fact("f-20200101-0001", twin),
            make_fact("f-20200101-0002", f"{twin} today"),
            make_fact("f-20200101-0003", NUMBERED.format(i="seven") + " today"),
            make_fact("f-20200101-0004", NUMBERED.format(i="seven") + " today now always"),
        ],
    )
    found = {frozenset((a["id"], b["id"])) for a, b, _, _ in followups.open_pairs(opened())}
    assert frozenset(("f-20200101-0001", "f-20200101-0002")) in found


def test_the_list_stops_at_the_limit_with_the_likeliest_repeats_first(mem, capsys):
    facts = []
    for n in range(30):
        words = f"alpha{n} beta{n} gamma{n} delta{n} epsilon{n} zeta{n} eta{n} theta{n} iota{n}"
        facts += [make_fact(fid(2 * n), words), make_fact(fid(2 * n + 1), f"{words} added{n}")]
    twice = "kappa lambda mu nu xi omicron pi rho sigma"
    facts += [make_fact(fid(900), twice), make_fact(fid(901), twice.upper())]
    write_facts(mem, facts)
    pairs = followups.open_pairs(opened())
    assert len(pairs) == followups.MAX_PAIRS
    assert {pairs[0][0]["id"], pairs[0][1]["id"]} == {fid(900), fid(901)}
    assert [pair[2] for pair in pairs] == sorted((pair[2] for pair in pairs), reverse=True)
    main(["tidy"])
    out = capsys.readouterr().out
    text = (mem / TASK).read_text()
    assert text.startswith(f"# Tidy follow-up (pending): {followups.MAX_PAIRS} pair(s)")
    assert text.count("- Older:") == followups.MAX_PAIRS
    assert len(text) < 16_000
    assert f"stops at {followups.MAX_PAIRS}" in text
    assert f"Open similar pairs: {followups.MAX_PAIRS}" in out and "stops at" in out


def test_settling_a_pair_brings_the_next_one(mem):
    facts = []
    for n in range(25):
        words = f"alpha{n} beta{n} gamma{n} delta{n} epsilon{n} zeta{n} eta{n} theta{n} iota{n}"
        facts += [make_fact(fid(2 * n), words), make_fact(fid(2 * n + 1), f"{words} added{n}")]
    write_facts(mem, facts)
    first = followups.open_pairs(opened())
    older, newer = first[0][:2]
    reason = "Both hold."
    assert main(["change", newer["id"], "--link", f"related:{older['id']}", "--reason", reason]) == 0
    second = followups.open_pairs(opened())
    assert len(second) == followups.MAX_PAIRS
    assert (older["id"], newer["id"]) not in [(a["id"], b["id"]) for a, b, _, _ in second]


def test_an_unrelated_write_does_not_touch_the_task_file(mem):
    words = "alpha beta gamma delta epsilon zeta eta theta iota"
    write_facts(mem, [make_fact(fid(1), words), make_fact(fid(2), f"{words} kappa")])
    memory = opened()
    followups.refresh(memory)
    path = mem / TASK
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert main(["add", "Something else entirely.", "--basis", "seen", "--source", "s:1"]) == 0
    assert path.stat().st_mtime_ns == 1_000_000_000


def test_a_scan_with_no_time_keeps_the_task_it_could_not_check(mem, monkeypatch):
    words = "alpha beta gamma delta epsilon zeta eta theta iota"
    write_facts(mem, [make_fact(fid(1), words), make_fact(fid(2), f"{words} kappa")])
    memory = opened()
    followups.refresh(memory)
    path = mem / TASK
    before = path.read_text()
    monkeypatch.setattr(followups, "SCAN_SECONDS", -1.0)
    followups.refresh(memory)
    assert path.read_text() == before


def test_a_count_from_an_older_file_past_the_limit_is_not_said(mem):
    path = mem / TASK
    path.parent.mkdir(exist_ok=True)
    path.write_text("# Tidy follow-up (pending): 200000 pair(s)\n")
    assert followups.pending_line(opened()) is None


def test_a_group_of_few_words_stays_inside_the_comparison_limit(monkeypatch):
    calls = []
    real = similar.similarity

    def counted(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(similar, "similarity", counted)
    words = {fid(i): {"a", "b", "c", "d", "e", "f", "g", str(i)} for i in range(5000)}
    similar.similar_pairs(words)
    assert len(calls) <= similar.MAX_COMPARISONS
