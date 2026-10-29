---
id: architecture
title: "Package architecture"
kind: service
status: implemented
summary: "CLI entry points and the main cairnkit modules."
parent: cairnkit
sourceRevision: "b81d40fe1d94615beb0687e0daa341bb7a2010f6"
sources:
  - src/cairnkit/cli.py
  - src/cairnkit/init.py
  - src/cairnkit/memory.py
  - src/cairnkit/store.py
  - src/cairnkit/load.py
  - src/cairnkit/hooks_cmd.py
  - src/cairnkit/skills.py
  - src/cairnkit/tidy.py
  - src/cairnkit/update.py
diagramLinks: {}
---

# Package architecture

The `memory` / `cairnkit` CLI dispatches into small modules. Facts live outside the repo and are linked in as `memory-bank`.

```mermaid
flowchart TB
    CLI[cli] --> Commands[command modules]
    Commands --> init[init]
    Commands --> memory[memory]
    Commands --> store[store]
    Commands --> load[load]
    Commands --> hooks_cmd[hooks_cmd]
    Commands --> skills[skills]
    Commands --> tidy[tidy]
    Commands --> update[update]
    memory --> store
    load --> memory
```
