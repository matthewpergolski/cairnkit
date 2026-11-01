"""One opened memory: the folder, its settings, and its records."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.config import load_config
from cairnkit.envsecrets import EnvValues, read_env_values
from cairnkit.paths import Project, lost_memory, lost_note, resolve_memory_dir
from cairnkit.secretscan import find_in_record
from cairnkit.state import fold
from cairnkit.store import fact_files, read_records


class MemoryMissing(Exception):
    """The memory folder does not exist."""


@dataclass
class Memory:
    project: Project
    dir: Path
    source: str
    config: dict = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    states: dict[str, dict] = field(default_factory=dict)
    # id -> what was found. These facts are not in `states`, so no reader can print their text.
    withheld: dict[str, list[str]] = field(default_factory=dict)
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
        self.records, self.errors = read_records(fact_files(self.dir))
        self.states, self.withheld = {}, {}
        for fact_id, state in fold(self.records).items():
            found = None if state.get("status") == "purged" else find_in_record(state, self.env)
            if found:
                self.withheld[fact_id] = found
            else:
                self.states[fact_id] = state

    def writer_file(self, writer: str) -> Path:
        return self.dir / "facts" / f"{writer}.jsonl"

    def fact(self, fact_id: str) -> dict | None:
        state = self.states.get(fact_id)
        if state is None or state.get("status") == "purged":
            return None
        return state

    def withheld_note(self, fact_id: str) -> str:
        """What the agent reads in place of the text of a withheld fact."""
        found = ", ".join(self.withheld[fact_id])
        return (
            f"{fact_id}: text withheld: looks like a secret ({found}). "
            f"Remove it now: memory purge {fact_id} --reason secret --yes"
        )
