---
id: architecture
title: "Package architecture"
kind: service
status: implemented
summary: "CLI entry points and the main cairnkit modules."
parent: cairnkit
sources:
  - src/cairnkit/adapters.py
  - src/cairnkit/autogate.py
  - src/cairnkit/autotidy.py
  - src/cairnkit/candidates.py
  - src/cairnkit/candidates_cmd.py
  - src/cairnkit/check.py
  - src/cairnkit/cli.py
  - src/cairnkit/clock.py
  - src/cairnkit/config.py
  - src/cairnkit/detect.py
  - src/cairnkit/discover.py
  - src/cairnkit/docs_cmd.py
  - src/cairnkit/docs_inventory.py
  - src/cairnkit/docs_modules.py
  - src/cairnkit/docs_pages_cairnkit.py
  - src/cairnkit/docs_pages_generic.py
  - src/cairnkit/followups.py
  - src/cairnkit/githook.py
  - src/cairnkit/harness_local.py
  - src/cairnkit/hookrun.py
  - src/cairnkit/hooks_cmd.py
  - src/cairnkit/hygiene.py
  - src/cairnkit/ignore.py
  - src/cairnkit/init.py
  - src/cairnkit/install_source.py
  - src/cairnkit/instruction_files.py
  - src/cairnkit/instructions.py
  - src/cairnkit/load.py
  - src/cairnkit/loopbreak.py
  - src/cairnkit/markers.py
  - src/cairnkit/memory.py
  - src/cairnkit/migrate.py
  - src/cairnkit/migrate_refs.py
  - src/cairnkit/paths.py
  - src/cairnkit/pending.py
  - src/cairnkit/presets.py
  - src/cairnkit/progress.py
  - src/cairnkit/propose.py
  - src/cairnkit/ranking.py
  - src/cairnkit/reading.py
  - src/cairnkit/refresh.py
  - src/cairnkit/rules.py
  - src/cairnkit/rules_target.py
  - src/cairnkit/scenarios.py
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

The `memory` / `cairnkit` CLI dispatches into command modules. Shared helpers sit under library modules. Facts live outside the repo and are linked in as `memory-bank`.

```mermaid
flowchart TB
    CLI[cli] --> Commands[command modules]
    CLI --> Library[library modules]
    Commands --> autotidy[autotidy]
    Commands --> check[check]
    Commands --> docs_cmd[docs_cmd]
    Commands --> followups[followups]
    Commands --> hookrun[hookrun]
    Commands --> hooks_cmd[hooks_cmd]
    Commands --> init[init]
    Commands --> instructions[instructions]
    Commands --> load[load]
    Commands --> migrate[migrate]
    Commands --> migrate_refs[migrate_refs]
    Commands --> presets[presets]
    Commands --> reading[reading]
    Commands --> refresh[refresh]
    Commands --> skills[skills]
    Commands --> tidy[tidy]
    Commands --> update[update]
    Commands --> writing[writing]
    Library --> adapters[adapters]
    Library --> autogate[autogate]
    Library --> candidates[candidates]
    Library --> candidates_cmd[candidates_cmd]
    Library --> clock[clock]
    Library --> config[config]
    Library --> detect[detect]
    Library --> discover[discover]
    Library --> docs_inventory[docs_inventory]
    Library --> docs_modules[docs_modules]
    Library --> docs_pages_cairnkit[docs_pages_cairnkit]
    Library --> docs_pages_generic[docs_pages_generic]
    Library --> githook[githook]
    Library --> harness_local[harness_local]
    Library --> hygiene[hygiene]
    Library --> ignore[ignore]
    Library --> install_source[install_source]
    Library --> instruction_files[instruction_files]
    Library --> loopbreak[loopbreak]
    Library --> markers[markers]
    Library --> memory[memory]
    Library --> paths[paths]
    Library --> pending[pending]
    Library --> progress[progress]
    Library --> propose[propose]
    Library --> ranking[ranking]
    Library --> rules[rules]
    Library --> rules_target[rules_target]
    Library --> scenarios[scenarios]
    Library --> schema[schema]
    Library --> secretscan[secretscan]
    Library --> selection[selection]
    Library --> session[session]
    Library --> similar[similar]
    Library --> state[state]
    Library --> store[store]
    Library --> usage[usage]
    memory --> store
    load --> memory
```
