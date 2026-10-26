"""`memory search` ranks by words, not by an all-words match."""

from conftest import make_fact, write_facts

from cairnkit.cli import main


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    return code, capsys.readouterr().out


def fact_ids(out):
    """The ids of the fact lines of a search, in the order shown."""
    found = []
    for line in out.splitlines():
        if line.startswith("- [f-"):
            found.append(line[3 : line.index("]")])
    return found


def seed(mem):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Email retries use a cron job every 15 minutes."),
            make_fact("f-20261001-0002", "Production deploys use a manual approval step."),
            make_fact("f-20261001-0003", "The nightly backup runs at 02:00 and keeps 14 days."),
            make_fact("f-20261001-0004", "Prices are stored as integer cents, never as floats."),
        ],
    )


def test_question_with_filler_words_finds_the_note_first(mem, capsys):
    seed(mem)
    code, out = run(capsys, "search", "How are email retries handled again?")
    assert code == 0
    assert fact_ids(out)[0] == "f-20261001-0001"


def test_note_that_matches_only_some_words_is_returned(mem, capsys):
    seed(mem)
    code, out = run(capsys, "search", "email kubernetes")
    assert code == 0 and "no match" not in out
    assert fact_ids(out) == ["f-20261001-0001"]


def test_rare_words_outweigh_common_ones(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "The service restarts the service and the service logs."),
            make_fact("f-20261001-0002", "The service reads the config file."),
            make_fact("f-20261001-0003", "Alerts go to the pager. The service stays quiet."),
            make_fact("f-20261001-0004", "The service has a health check."),
        ],
    )
    code, out = run(capsys, "search", "service pager outage")
    assert code == 0
    assert fact_ids(out)[0] == "f-20261001-0003"


def test_plural_and_ies_forms_match(mem, capsys):
    seed(mem)
    _, out = run(capsys, "search", "How do we retry the emails?")
    assert fact_ids(out)[0] == "f-20261001-0001"


def test_order_is_the_same_on_every_run(mem, capsys):
    same = "The cache is cleared at night."
    write_facts(
        mem,
        [
            make_fact("f-20261001-0003", same),
            make_fact("f-20261001-0001", same),
            make_fact("f-20261001-0002", same),
        ],
    )
    _, first = run(capsys, "search", "cache night")
    _, second = run(capsys, "search", "cache night")
    assert first == second
    assert fact_ids(first) == ["f-20261001-0001", "f-20261001-0002", "f-20261001-0003"]


def test_equal_scores_show_the_newer_fact_first(mem, capsys):
    same = "The cache is cleared at night."
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", same, learned_at="2026-10-01T12:00:00+00:00"),
            make_fact("f-20261001-0002", same, learned_at="2026-10-05T12:00:00+00:00"),
        ],
    )
    _, out = run(capsys, "search", "cache")
    assert fact_ids(out) == ["f-20261001-0002", "f-20261001-0001"]


def test_empty_query_says_so(mem, capsys):
    seed(mem)
    for query in ("", "   ", "?!"):
        code, out = run(capsys, "search", query)
        assert code == 1
        assert "no searchable words" in out


def test_a_query_of_only_filler_words_searches_them_as_they_are(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-0001", "Do the thing at the start.")])
    code, out = run(capsys, "search", "the")
    assert code == 0
    assert fact_ids(out) == ["f-20261001-0001"]


def test_ended_facts_stay_out_unless_all(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "We tried a queue for email retries."),
            make_fact("f-20261001-0002", "Email retries use a cron job."),
            {
                "type": "change",
                "id": "f-20261001-0001",
                "at": "2026-10-03T00:00:00+00:00",
                "status": "superseded",
                "superseded_by": "f-20261001-0002",
                "reason": "The queue lost jobs on restart.",
                "writer": "main",
            },
        ],
    )
    _, active = run(capsys, "search", "What did we decide about email retries?")
    assert fact_ids(active) == ["f-20261001-0002"]
    _, everything = run(capsys, "search", "What did we decide about email retries?", "--all")
    assert set(fact_ids(everything)) == {"f-20261001-0001", "f-20261001-0002"}
    assert "[superseded: The queue lost jobs on restart.]" in everything


def test_strict_keeps_the_old_every_word_match(mem, capsys):
    seed(mem)
    _, out = run(capsys, "search", "email kubernetes", "--strict")
    assert "no match" in out
    _, out = run(capsys, "search", "retr", "--strict")
    assert fact_ids(out) == ["f-20261001-0001"]
    _, out = run(capsys, "search", "How are email retries handled again?", "--strict")
    assert "no match" in out


def test_note_lines_with_more_query_words_come_first(mem, capsys):
    path = mem / "notes" / "ops.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Backups run at night.\nThe nightly backup is copied off site.\n")
    _, out = run(capsys, "search", "Where is the nightly backup copied?")
    lines = [line for line in out.splitlines() if "notes/ops.md" in line]
    assert "ops.md:2:" in lines[0]
    assert "ops.md:1:" in lines[1]


def test_a_long_note_line_is_cut_around_the_match(mem, capsys):
    path = mem / "notes" / "long.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("word " * 60 + "needle " + "word " * 60 + "\n")
    _, out = run(capsys, "search", "needle")
    line = next(line for line in out.splitlines() if "notes/long.md" in line)
    assert "needle" in line and len(line) < 160
