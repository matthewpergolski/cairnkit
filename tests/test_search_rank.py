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


def used_ids(mem):
    ids = set()
    for log in (mem / ".usage").glob("*.log") if (mem / ".usage").is_dir() else []:
        ids |= {line.split("\t")[1].strip() for line in log.read_text().splitlines() if line}
    return ids


def test_looking_up_an_id_finds_only_that_fact_and_counts_only_it_as_use(mem, capsys):
    seed(mem)
    _, out = run(capsys, "search", "f-20261001-0003")
    assert fact_ids(out) == ["f-20261001-0003"]
    assert used_ids(mem) == {"f-20261001-0003"}


def test_an_id_is_one_word_for_search_on_both_sides():
    from cairnkit import ranking

    assert ranking.query_terms("f-20261026-a053") == ["f-20261026-a053"]
    assert ranking.words("See f-20261026-a053, then f-20261026-a054.") == [
        "see",
        "f-20261026-a053",
        "then",
        "f-20261026-a054",
    ]


def test_a_loose_match_does_not_count_as_use(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Deploys use a manual approval step."),
            make_fact("f-20261001-0002", "Friday deploys are frozen. Friday means no release."),
            make_fact("f-20261001-0003", "Deploys run from the main branch."),
            make_fact("f-20261001-0004", "Friday lunch is at noon."),
        ],
    )
    run(capsys, "search", "Can we deploy on Friday?")
    assert used_ids(mem) == {"f-20261001-0002"}


def test_limit_and_more_line_work_with_ranked_hits(mem, capsys):
    seed(mem)
    _, out = run(capsys, "search", "email deploys backup prices", "--limit", "2")
    assert len(fact_ids(out)) == 2
    assert "2 more; use --limit" in out


def test_no_match_says_that_parts_of_words_were_tried(mem, capsys):
    seed(mem)
    _, out = run(capsys, "search", "kubernetes")
    assert "no match" in out and "whole words and word starts were tried" in out


def test_a_word_that_starts_a_longer_word_finds_it_when_no_whole_word_matches(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Production deployment needs a manual approval."),
            make_fact("f-20261001-0002", "Email retries use a cron job every 15 minutes."),
            make_fact("f-20261001-0003", "The configuration lives in environment variables."),
            make_fact("f-20261001-0004", "The check passed on the second run."),
        ],
    )
    for query, expected in (
        ("deploy", "f-20261001-0001"),
        ("config", "f-20261001-0003"),
        ("pass", "f-20261001-0004"),
    ):
        code, out = run(capsys, "search", query)
        assert code == 0 and fact_ids(out) == [expected], query
        assert "no whole-word match" in out and "start with" in out


def test_a_short_start_or_a_middle_of_a_word_does_not_match(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Email retries use a cron job every 15 minutes."),
            make_fact("f-20261001-0002", "The important step is the review."),
            make_fact("f-20261001-0003", "Production deployment needs approval."),
        ],
    )
    for query in ("retr", "port", "ploy", "oyo", "ret"):
        _, out = run(capsys, "search", query)
        assert "no match" in out, query


def test_the_part_of_word_note_comes_before_the_stored_notes_frame(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-0001", "Production deployment needs approval.")])
    _, out = run(capsys, "search", "deploy")
    lines = out.splitlines()
    note = next(i for i, line in enumerate(lines) if "no whole-word match" in line)
    frame = next(i for i, line in enumerate(lines) if line.startswith("Stored notes"))
    assert note < frame


def test_a_whole_word_match_means_no_prefix_search(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Deploys need a manual approval."),
            make_fact("f-20261001-0002", "Production deployment is on Fridays only."),
        ],
    )
    _, out = run(capsys, "search", "deploys")
    assert fact_ids(out) == ["f-20261001-0001"]
    assert "no whole-word match" not in out


def test_prefix_hits_rank_by_how_many_query_words_they_hold(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "The deployment pipeline is slow."),
            make_fact("f-20261001-0002", "The deployment pipeline runs the migrations first."),
            make_fact("f-20261001-0003", "Lunch is at noon."),
        ],
    )
    _, out = run(capsys, "search", "deploy migrat")
    assert fact_ids(out) == ["f-20261001-0002", "f-20261001-0001"]


def test_prefix_search_reads_notes_too(mem, capsys):
    path = mem / "notes" / "ops.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Rollbacks follow the deployment checklist.\n")
    _, out = run(capsys, "search", "deploy")
    assert "ops.md:1:" in out and "no whole-word match" in out
    assert "deployment" in out


def test_the_top_prefix_hit_counts_as_use_and_a_weak_one_does_not(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "The deployment pipeline runs the migrations first."),
            make_fact("f-20261001-0002", "The deployment pipeline is slow."),
        ],
    )
    run(capsys, "search", "deploy migrat")
    assert used_ids(mem) == {"f-20261001-0001"}


def test_strict_never_falls_back(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-0001", "Production deployment needs approval.")])
    _, out = run(capsys, "search", "deploy migrat", "--strict")
    assert "no match" in out and "no whole-word match" not in out
    _, out = run(capsys, "search", "deploy", "--strict")
    assert fact_ids(out) == ["f-20261001-0001"]


def test_strict_with_an_empty_query_still_lists_every_fact(mem, capsys):
    seed(mem)
    code, out = run(capsys, "search", "", "--strict")
    assert code == 0 and len(fact_ids(out)) == 4


def test_a_filler_pronoun_does_not_match_a_fact_on_its_own(mem, capsys):
    from cairnkit import ranking

    assert "them" not in ranking.query_terms("who sends them and how are failures retried?")
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001", "Confirmation emails are sent by a worker. Failures are retried."
            ),
            make_fact(
                "f-20261001-0002", "Dates are UTC. The UI converts them to the shop time zone."
            ),
        ],
    )
    _, out = run(capsys, "search", "emails: who sends them and how are failures retried?")
    assert fact_ids(out) == ["f-20261001-0001"]
    assert used_ids(mem) == {"f-20261001-0001"}


def test_a_hit_that_shares_no_word_with_the_top_hit_is_not_use(mem, capsys):
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001", "The zebra gate is red.", learned_at="2026-10-02T12:00:00+00:00"
            ),
            make_fact(
                "f-20261001-0002", "The yak gate is red.", learned_at="2026-10-01T12:00:00+00:00"
            ),
        ],
    )
    _, out = run(capsys, "search", "zebra yak")
    assert fact_ids(out) == ["f-20261001-0001", "f-20261001-0002"]  # both are shown
    assert used_ids(mem) == {"f-20261001-0001"}  # only the top one counts


def test_plurals_that_are_not_plurals_stay_as_they_are():
    from cairnkit import ranking

    for word in ("news", "series", "species"):
        assert ranking.stem(word) == word
    assert ranking.query_terms("new") != ranking.query_terms("news")


def test_odd_plurals_match_their_singular_both_ways(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Old movies are stored as files."),
            make_fact("f-20261001-0002", "The movie list is cached."),
            make_fact("f-20261001-0003", "All statuses end in a final state."),
            make_fact("f-20261001-0004", "Two buses run at night."),
            make_fact("f-20261001-0005", "Every cookie has an expiry."),
            make_fact("f-20261001-0006", "Cookies are set by the login page."),
            make_fact("f-20261001-0007", "The news feed is public."),
        ],
    )
    cases = {
        "movie": {"f-20261001-0001", "f-20261001-0002"},
        "movies": {"f-20261001-0001", "f-20261001-0002"},
        "status": {"f-20261001-0003"},
        "bus": {"f-20261001-0004"},
        "buses": {"f-20261001-0004"},
        "cookie": {"f-20261001-0005", "f-20261001-0006"},
        "cookies": {"f-20261001-0005", "f-20261001-0006"},
        "new": set(),
        "news": {"f-20261001-0007"},
    }
    for query, expected in cases.items():
        _, out = run(capsys, "search", query)
        assert set(fact_ids(out)) == expected, query


def test_with_all_the_use_gate_is_measured_against_the_best_active_hit(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "The cache is cleared at night."),
            make_fact("f-20261001-0002", "The cache stays warm."),
            make_fact("f-20261001-0003", "Another note about nothing."),
            {
                "type": "change",
                "id": "f-20261001-0001",
                "at": "2026-10-03T00:00:00+00:00",
                "status": "superseded",
                "superseded_by": "f-20261001-0002",
                "reason": "No more clearing.",
                "writer": "main",
            },
        ],
    )
    _, out = run(capsys, "search", "cache cleared night", "--all")
    assert set(fact_ids(out)) == {"f-20261001-0001", "f-20261001-0002"}
    assert used_ids(mem) == {"f-20261001-0002"}


def test_a_word_start_that_ends_in_s_is_not_cut_as_a_plural(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Pull requests are merged with squash and merge."),
            make_fact("f-20261001-0002", "Tests run with pytest."),
        ],
    )
    _, out = run(capsys, "search", "squas")
    assert fact_ids(out) == ["f-20261001-0001"]
    _, out = run(capsys, "search", "pytes")
    assert fact_ids(out) == ["f-20261001-0002"]


def test_a_plural_query_word_is_one_term_not_two(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "The movie list is cached."),
            make_fact("f-20261001-0002", "Old movies are stored as files."),
            make_fact("f-20261001-0003", "Prices are stored as integer cents."),
            make_fact("f-20261001-0004", "The nightly backup runs at night."),
        ],
    )
    _, out = run(capsys, "search", "movies cached")
    assert fact_ids(out)[0] == "f-20261001-0001"
    assert used_ids(mem) == {"f-20261001-0001"}  # a fact with only "movies" is not use


def test_a_word_counts_once_toward_the_length_of_a_text():
    from cairnkit import ranking

    one, two = ranking.bm25(["movies cached", "movies cached cached"], ["cached"])
    assert one > 0 and two > one  # a repeat adds score
    # the two forms of "movies" add no length
    plain, plural = ranking.bm25(["alpha movie beta", "alpha movies beta"], ["alpha"])
    assert plain == plural
