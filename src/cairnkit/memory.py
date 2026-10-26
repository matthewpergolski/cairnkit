"""One opened memory: the folder, its settings, and its records."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.config import load_config
from cairnkit.paths import Project, resolve_memory_dir
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

    @classmethod
    def open(cls, project: Project, flag: str | None = None) -> Memory:
        memdir, source = resolve_memory_dir(project, flag)
        if not (memdir / "facts").is_dir():
            raise MemoryMissing(f"no memory folder at {memdir} (from {source}); run `memory init`")
        memory = cls(project, memdir, source, load_config(memdir))
        memory.reload()
        return memory

    def reload(self) -> None:
        self.records, self.errors = read_records(fact_files(self.dir))
        self.states = fold(self.records)

    def writer_file(self, writer: str) -> Path:
        return self.dir / "facts" / f"{writer}.jsonl"

    def fact(self, fact_id: str) -> dict | None:
        state = self.states.get(fact_id)
        if state is None or state.get("status") == "purged":
            return None
        return state
