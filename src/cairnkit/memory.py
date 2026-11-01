"""One opened memory: the folder, its settings, and its records."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.config import load_config
from cairnkit.envsecrets import EnvValues, read_env_values
from cairnkit.paths import Project, lost_memory, lost_note, resolve_memory_dir
from cairnkit.secretscan import (
    find_in_closed_fields,
    find_in_record,
    find_secrets,
    mask_closed_fields,
    mask_record,
)
from cairnkit.state import fold
from cairnkit.store import encode, fact_files, repaired_lines, scan

SHOWN_IDS = 5
ON_DISK = "Reads mask it, and it stays on disk until purged."
LEAVE_IT = (
    "Leave the fact. The file keeps the true word, the mask is harmless, and nothing more is "
    "needed. A rewrite cannot hold the word."
)


class MemoryMissing(Exception):
    """The memory folder does not exist."""


@dataclass
class SecretLine:
    """A line that no fact state covers, so only its place in the file can name it."""

    file: str
    line: int
    sha: str
    names: list[str]
    text: str

    @property
    def ref(self) -> str:
        return f"line-{self.sha}"


def _replace(fact_id: str) -> str:
    return (
        f'write a clean replacement with `memory add "TEXT" --supersedes {fact_id}`, then purge '
        f"the old record with `memory purge {fact_id} --reason secret --yes`"
    )


def listed(ids: list[str]) -> str:
    more = f" and {len(ids) - SHOWN_IDS} more" if len(ids) > SHOWN_IDS else ""
    return ", ".join(ids[:SHOWN_IDS]) + more


@dataclass
class Memory:
    project: Project
    dir: Path
    source: str
    config: dict = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    states: dict[str, dict] = field(default_factory=dict)
    # id -> what was found. `states` holds only the masked text, so no reader can print a value.
    masked: dict[str, list[str]] = field(default_factory=dict)
    secret_lines: list[SecretLine] = field(default_factory=list)
    env: EnvValues = field(default_factory=EnvValues)

    @classmethod
    def open(cls, project: Project, flag: str | None = None) -> Memory:
        memdir, source = resolve_memory_dir(project, flag)
        if not (memdir / "facts").is_dir():
            lost = lost_memory(project)
            if lost:
                raise MemoryMissing(lost_note(lost))
            raise MemoryMissing(f"no memory folder at {memdir} (from {source}); run `memory init`")
        memory = cls(project, memdir, source, load_config(memdir), env=read_env_values(project))
        memory.reload()
        return memory

    def reload(self) -> None:
        located, bad = scan(fact_files(self.dir))
        done = repaired_lines(located)
        self.records = [item.record for item in located]
        self.errors = [b.message for b in bad if (b.path.name, b.sha) not in done]
        self.secret_lines = []
        for item in bad:
            found = find_secrets(item.text, self.env)
            if found:
                self.secret_lines.append(
                    SecretLine(item.path.name, item.line, item.sha, found, item.text)
                )
        for item in located:
            rec = item.record
            found = find_in_closed_fields(rec)
            if rec.get("id") is None:
                found = found or find_in_record(rec, self.env)
            if found:
                text = str(rec.get("text") or rec.get("reason") or encode(rec))
                self.secret_lines.append(
                    SecretLine(item.path.name, item.line, item.sha, found, text)
                )
        self.states, self.masked = {}, {}
        for fact_id, state in fold(self.records).items():
            found = find_in_record(state, self.env)
            if found:
                self.masked[fact_id] = found
                state = mask_record(state, self.env)
            if find_in_closed_fields(state):
                state = mask_closed_fields(state)
            self.states[state["id"]] = state

    def writer_file(self, writer: str) -> Path:
        return self.dir / "facts" / f"{writer}.jsonl"

    def fact(self, fact_id: str) -> dict | None:
        state = self.states.get(fact_id)
        if state is None or state.get("status") == "purged":
            return None
        return state

    def only_plain(self, fact_id: str) -> bool:
        return self.env.only_plain(self.masked[fact_id])

    def secret_problem(self, fact_id: str) -> str:
        """One fact, for `check`, `show` and the stop. No line number, so it stays one notice."""
        state = self.states[fact_id]
        found = ", ".join(self.masked[fact_id])
        purge = f"memory purge {fact_id} --reason secret --yes"
        if state.get("status") != "active":
            return (
                f"{fact_id} is not active and holds a value that looks secret ({found}). {ON_DISK} "
                f"Read the rest with `memory show {fact_id}`, then run `{purge}`."
            )
        if self.only_plain(fact_id):
            return f"{fact_id} holds a word that a `.env` secret also uses ({found}). {LEAVE_IT}"
        return (
            f"{fact_id} holds a value that looks secret ({found}). {ON_DISK} "
            f"To end this, {_replace(fact_id)}. The new text needs no value."
        )

    def secret_line_problem(self, line: SecretLine) -> str:
        found = ", ".join(line.names)
        return (
            f"{line.file}:{line.line} holds a value that looks secret ({found}), and it is not a "
            f"fact that loads. It stays on disk until purged. Read the rest with `memory show "
            f"{line.ref}`, write again what is true, then run "
            f"`memory purge {line.ref} --reason secret --yes`."
        )

    def secret_notes(self) -> list[str]:
        """What `memory load` tells the agent: a few short lines, with no value."""
        active = [i for i in sorted(self.masked) if self.states[i].get("status") == "active"]
        ended = [i for i in sorted(self.masked) if i not in active]
        plain = [i for i in active if self.only_plain(i)]
        shaped = [i for i in active if i not in plain]
        notes = []
        if shaped:
            notes.append(
                f"{listed(shaped)}: holds a value that looks secret, shown as `[secret: ...]`. "
                f"For each ID, {_replace('ID')}. The new text needs no value."
            )
        if plain:
            notes.append(
                f"{listed(plain)}: holds a word that a `.env` secret also uses, shown as "
                f"`[secret: NAME]`. {LEAVE_IT}"
            )
        if ended:
            notes.append(
                f"{listed(ended)}: not active, and holds a value that looks secret. Read the rest "
                "with `memory show ID`, then run `memory purge ID --reason secret --yes`."
            )
        if self.secret_lines:
            refs = [line.ref for line in self.secret_lines]
            notes.append(
                f"{listed(refs)}: a damaged line holds a value that looks secret. Read the rest "
                "with `memory show ID`, write again what is true, then run "
                "`memory purge ID --reason secret --yes`."
            )
        return notes
