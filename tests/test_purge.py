import json

from conftest import read_jsonl

from cairnkit.cli import main

SECRET = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def write_with_secret(mem):
    path = mem / "facts" / "main.jsonl"
    keep = {
        "type": "fact",
        "id": "f-20261001-aaaa",
        "kind": "fact",
        "text": "Keep me.",
        "area": "x",
        "happened_at": "2026-10-01",
        "learned_at": "2026-10-01T00:00:00+00:00",
        "source": "session:2026-10-01",
        "basis": "seen",
        "status": "active",
        "scope": "long",
        "writer": "main",
    }
    bad = {**keep, "id": "f-20261001-bbbb", "text": f"The token is {SECRET}."}
    change = {
        "type": "change",
        "id": "f-20261001-bbbb",
        "at": "2026-10-02T00:00:00+00:00",
        "reason": f"still {SECRET}",
        "writer": "main",
    }
    path.write_text("".join(json.dumps(r) + "\n" for r in (keep, bad, change)))
    return path


def test_check_flags_the_secret(mem, capsys):
    write_with_secret(mem)
    assert main(["check"]) == 1
    assert "secret" in capsys.readouterr().out.lower()


def test_purge_needs_yes(mem):
    path = write_with_secret(mem)
    before = path.read_bytes()
    assert main(["purge", "f-20261001-bbbb", "--reason", "secret"]) != 0
    assert path.read_bytes() == before


def test_purge_removes_content_and_leaves_tombstone(mem, capsys):
    path = write_with_secret(mem)
    assert main(["purge", "f-20261001-bbbb", "--reason", "secret", "--yes"]) == 0
    data = path.read_text()
    assert SECRET not in data
    recs = read_jsonl(path)
    assert recs[0]["id"] == "f-20261001-aaaa" and recs[0]["text"] == "Keep me."
    tomb = recs[-1]
    assert tomb["type"] == "tombstone" and tomb["id"] == "f-20261001-bbbb"
    assert tomb["reason"] == "secret" and "text" not in tomb
    assert len(recs) == 2
    capsys.readouterr()
    assert main(["check"]) == 0
    assert main(["show", "f-20261001-bbbb"]) == 0
    assert "purged" in capsys.readouterr().out
