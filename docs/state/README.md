---
id: cairnkit
title: cairnkit
kind: system
status: implemented
summary: "A private, dated memory for any project. It lives outside the repo and is linked in."
parent: null
sourceRevision: "77c91544166de303f015b80b6b368b8c10a9e43f"
sources:
  - README.md
  - pyproject.toml
  - src/cairnkit/cli.py
diagramLinks:
  MemorySession: agent-session
  FactStore: fact-lifecycle
  Package: architecture
---

# cairnkit

A private, dated memory for any project. It lives outside the repo and is linked in.

This atlas was written by `memory docs`. Open the project folder in [Nessa Docs](https://github.com/nessalabs/nessa-docs) to browse the diagrams. Boxes with a + open a deeper page.

The root `sourceRevision` is the git commit inventoried for this system map. It is not a claim that every child page was behavior-reviewed at that commit. Child template pages omit `sourceRevision`.

```mermaid
flowchart LR
    Person[You and agents]
    Package[cairnkit package]
    MemorySession[Memory session]
    FactStore[Fact store]
    Person --> Package
    Package --> MemorySession
    Person --> MemorySession
    MemorySession --> FactStore
    subgraph Layout[Top-level layout]
        benchmarks[benchmarks]
        scripts[scripts]
        src[src]
        tests[tests]
    end
```
