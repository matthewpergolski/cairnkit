---
id: architecture
title: "Package architecture"
kind: service
status: implemented
summary: "CLI entry points and the main cairnkit modules."
parent: cairnkit
sources:
  - src/cairnkit/adapters.py
  - src/cairnkit/autotidy.py
  - src/cairnkit/candidates.py
  - src/cairnkit/check.py
  - src/cairnkit/cli.py
  - src/cairnkit/clock.py
  - src/cairnkit/config.py
  - src/cairnkit/detect.py
  - src/cairnkit/docs_cmd.py
  - src/cairnkit/followups.py
  - src/cairnkit/githook.py
  - src/cairnkit/hookrun.py
  - src/cairnkit/hooks_cmd.py
  - src/cairnkit/ignore.py
  - src/cairnkit/init.py
  - src/cairnkit/install_source.py
  - src/cairnkit/instruction_files.py
  - src/cairnkit/instructions.py
  - src/cairnkit/load.py
  - src/cairnkit/markers.py
  - src/cairnkit/memory.py
  - src/cairnkit/migrate.py
  - src/cairnkit/migrate_refs.py
  - src/cairnkit/paths.py
  - src/cairnkit/presets.py
  - src/cairnkit/progress.py
  - src/cairnkit/ranking.py
  - src/cairnkit/reading.py
  - src/cairnkit/refresh.py
  - src/cairnkit/rules.py
  - src/cairnkit/rules_target.py
  - src/cairnkit/schema.py
  - src/cairnkit/secretscan.py
  - src/cairnkit/selection.py
  - src/cairnkit/session.py
  - src/cairnkit/similar.py
  - src/cairnkit/skills.py
  - src/cairnkit/state.py
  - src/cairnkit/store.py
  - src/cairnkit/tidy.py
  - src/cairnkit/update.py
  - src/cairnkit/usage.py
  - src/cairnkit/writing.py
diagramLinks: {}
---

# Package architecture

The `memory` / `cairnkit` CLI dispatches into small modules. Facts live outside the repo and are linked in as `memory-bank`.

```mermaid
flowchart TB
    CLI[cli] --> Commands[command modules]
    Commands --> adapters[adapters]
    Commands --> autotidy[autotidy]
    Commands --> candidates[candidates]
    Commands --> check[check]
    Commands --> clock[clock]
    Commands --> config[config]
    Commands --> detect[detect]
    Commands --> docs_cmd[docs_cmd]
    Commands --> followups[followups]
    Commands --> githook[githook]
    Commands --> hookrun[hookrun]
    Commands --> hooks_cmd[hooks_cmd]
    Commands --> ignore[ignore]
    Commands --> init[init]
    Commands --> install_source[install_source]
    Commands --> instruction_files[instruction_files]
    Commands --> instructions[instructions]
    Commands --> load[load]
    Commands --> markers[markers]
    Commands --> memory[memory]
    Commands --> migrate[migrate]
    Commands --> migrate_refs[migrate_refs]
    Commands --> paths[paths]
    Commands --> presets[presets]
    Commands --> progress[progress]
    Commands --> ranking[ranking]
    Commands --> reading[reading]
    Commands --> refresh[refresh]
    Commands --> rules[rules]
    Commands --> rules_target[rules_target]
    Commands --> schema[schema]
    Commands --> secretscan[secretscan]
    Commands --> selection[selection]
    Commands --> session[session]
    Commands --> similar[similar]
    Commands --> skills[skills]
    Commands --> state[state]
    Commands --> store[store]
    Commands --> tidy[tidy]
    Commands --> update[update]
    Commands --> usage[usage]
    Commands --> writing[writing]
    memory --> store
    load --> memory
```
