---
id: agent-session
title: "Agent session"
kind: flow
status: implemented
summary: "How an agent session loads facts, works, and stops."
parent: cairnkit
sources:
  - src/cairnkit/hookrun.py
  - src/cairnkit/load.py
diagramLinks: {}
---

# Agent session

A session starts with a hook that loads standing facts, then the agent works against the checkout, then a stop hook can tidy.

```mermaid
flowchart TD
    Start[Session start hook] --> Load[memory load]
    Load --> Work[Agent work in the checkout]
    Work --> Add[memory add or change]
    Work --> Search[memory search]
    Add --> Stop[Session stop hook]
    Search --> Stop
```
