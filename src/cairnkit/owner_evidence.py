"""What the owner said in a session, kept so that a `told` claim of an agent can be checked.

The data shape: one file for each session, `<memory>/.sessions/<id>.owner.json`, beside the session
state (see session.py), so the other hooks of a session do not read or write it.

    {"root": checkout path,
     "prompts": [{"at", "text"}],               # the newest PROMPTS_KEPT owner prompts
     "choices": [{"at", "kind", "text"}],      # answers to agent questions, this turn only
     "approval": {"at", "text"} | null}         # the question that this turn's "yes" answered

Each text is masked and cut. A new owner prompt starts a turn, so it clears the choices and the
approval of the turn before. The prompt hook writes it, and the hook after a tool adds the label
that the owner picked in an agent question. `memory add` reads it (`check_claim`).

The approval. When the owner's whole prompt is a short yes (see `is_approval`), the prompt hook
reads the agent's last message from the transcript that the payload names. Only the sentence that
ends that message counts, and only when it is a question: that is what the "yes" answers. The rest
of the message is often a report of what a tool or a page said, which the owner did not approve.
A tool step after the message, or a message that ends in no question, gives no approval.

How `memory add` finds its session. Claude Code, Codex and Grok put the session id in the shell of
the agent, and the hooks get the same id. For another agent, it takes the one session in this
checkout whose owner prompt is less than OPEN_SECONDS old. No session, or more than one, gives no
evidence, and the claim stays unconfirmed.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from cairnkit import plainfile
from cairnkit.memory import Memory
from cairnkit.secretscan import mask
from cairnkit.session import state_path, write_state
from cairnkit.signals import NOT_THE_OWNER
from cairnkit.told_match import (
    Evidence,
    best_match,
    choice_evidence,
    final_question,
    is_approval,
)

PROMPTS_KEPT = 12
PROMPT_CHARS = 1500
CHOICES_KEPT = 8
CHOICE_CHARS = 1000
PROPOSAL_CHARS = 1200
TAIL_BYTES = 512 * 1024
OPEN_SECONDS = 1800
# The variable in the agent's shell that holds the session id that its hooks get. Claude Code was
# read in a real shell. Codex and Grok are inferred from their names.
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "GROK_SESSION_ID")
QUESTION_TOOL = "AskUserQuestion"
FENCED = re.compile(r"```.*?(?:```|$)", re.DOTALL)
ANSWER_PAIR = re.compile(r'"([^"]*)"="([^"]*)"')
VIA = {
    "prompt": "words the owner typed in this session",
    "choice": "the option the owner picked in this turn",
    "approval": "the proposal the owner approved in this turn",
}


@dataclass(frozen=True)
class Verdict:
    bound: bool
    via: str  # a VIA value when bound, else why not


def evidence_path(memory: Memory, key: str) -> Path:
    state = state_path(memory, key)
    return state.with_name(state.stem + ".owner.json")


def _read(path: Path) -> dict:
    try:
        data = json.loads(plainfile.read_text(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _kept(memory: Memory, text: str, width: int) -> str:
    """The masked text, cut to width. The mask goes first, so no cut leaves part of a secret."""
    return mask(text[: width * 2], memory.env)[:width]


def _list(data: dict, name: str) -> list[dict]:
    rows = data.get(name)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def note_prompt(memory: Memory, key: str, agent: str, payload: dict) -> None:
    """Keep an owner prompt. For a short yes, keep the agent's question that it answered."""
    prompt = str(payload.get("prompt") or "")
    if not prompt.strip() or NOT_THE_OWNER.search(prompt):
        return
    path = evidence_path(memory, key)
    moment = time.time()
    own = FENCED.sub(" ", prompt).strip()  # a fenced block is a paste, not the owner's words
    prompts = _list(_read(path), "prompts")
    if own:
        prompts.append({"at": moment, "text": _kept(memory, own, PROMPT_CHARS)})
    approval = None
    if is_approval(prompt):
        message = last_agent_message(agent, payload.get("transcript_path"), prompt)
        question = final_question(message) if message else None
        if question:
            approval = {"at": moment, "text": _kept(memory, question, PROPOSAL_CHARS)}
    data = {
        "root": str(memory.project.root),
        "prompts": prompts[-PROMPTS_KEPT:],
        "choices": [],
        "approval": approval,
    }
    write_state(memory, path, data)


def _answers(response: object) -> dict[str, str]:
    """{question: answer} from the tool result: a dict with `answers`, or the text form."""
    if isinstance(response, dict) and isinstance(response.get("answers"), dict):
        return {str(q): str(a) for q, a in response["answers"].items()}
    if isinstance(response, str):
        return dict(ANSWER_PAIR.findall(response))
    return {}


def note_answer(memory: Memory, key: str, payload: dict) -> None:
    """Keep what the owner chose in an agent question (Claude Code's AskUserQuestion)."""
    if payload.get("tool_name") != QUESTION_TOOL:
        return
    tool_input = payload.get("tool_input")
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    answers = _answers(payload.get("tool_response"))
    found = []
    for item in questions if isinstance(questions, list) else []:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "")
        options = [opt for opt in item.get("options") or [] if isinstance(opt, dict)]
        labels = [str(opt.get("label") or "") for opt in options]
        evidence = choice_evidence(labels, answers.get(question, ""))
        if evidence:
            found.append(evidence)
    if not found:
        return
    path = evidence_path(memory, key)
    data = _read(path)
    data.setdefault("root", str(memory.project.root))
    moment = time.time()
    choices = _list(data, "choices") + [
        {
            "at": moment,
            "kind": item.kind,
            "text": _kept(memory, item.text, CHOICE_CHARS),
        }
        for item in found
    ]
    data["choices"] = choices[-CHOICES_KEPT:]
    write_state(memory, path, data)


def _tail_lines(path: str) -> list[str]:
    """The whole lines in the last TAIL_BYTES of a regular file, newest first."""
    fd = plainfile.open_fd(path)
    with os.fdopen(fd, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        start = max(0, size - TAIL_BYTES)
        fh.seek(start)
        lines = fh.read(TAIL_BYTES).decode("utf-8", "replace").splitlines()
    return list(reversed(lines[1:] if start else lines))


def _records(lines: list[str]):
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def _texts(content: object, kinds: tuple[str, ...]) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") in kinds
    ]


def _last_reply(turns, prompt: str) -> str | None:
    """The agent's last message before the owner's prompt, from (role, texts) newest first.

    The role is "agent", "owner" or "tool". The prompt itself may be in the transcript already. A
    tool step after the message gives None, because the message did not end the turn. Another
    owner prompt after it gives None too.
    """
    found: list[str] = []
    for role, texts in turns:
        if role == "agent" and texts:
            found = texts + found
        elif found:
            break
        elif role == "tool" or " ".join(texts).strip() != prompt.strip():
            return None
    return "\n".join(found).strip() or None


def _claude_turns(lines: list[str]):
    """Claude Code: `type: assistant` records hold text, tool_use or thinking blocks. A
    `type: user` record is a prompt, or a tool result. An `isMeta` record is text that the tool
    added. A thinking block is no step."""
    for record in _records(lines):
        kind, message = record.get("type"), record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if kind == "assistant" and _texts(content, ("tool_use", "server_tool_use")) != []:
            yield "tool", []
        elif kind == "assistant" and _texts(content, ("text",)):
            yield "agent", _texts(content, ("text",))
        elif kind == "user" and not record.get("isMeta"):
            if _texts(content, ("tool_result",)) or not _texts(content, ("text",)):
                yield "tool", []
            else:
                yield "owner", _texts(content, ("text",))


def _codex_turns(lines: list[str]):
    """Codex rollout: `response_item` records with a message `payload` and a role. A reasoning
    item is no step."""
    for record in _records(lines):
        payload = record.get("payload")
        if record.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        if payload.get("type") == "reasoning":
            continue
        if payload.get("type") != "message":
            yield "tool", []
        elif payload.get("role") == "assistant":
            yield "agent", _texts(payload.get("content"), ("output_text",))
        elif payload.get("role") == "user":
            texts = _texts(payload.get("content"), ("input_text",))
            if not any(text.lstrip().startswith("<") for text in texts):  # context the tool adds
                yield "owner", texts


# A tool whose transcript format is not here gives no proposal, so an approval confirms nothing.
READERS = {"claude": _claude_turns, "codex": _codex_turns}


def last_agent_message(agent: str, path: object, prompt: str) -> str | None:
    """The agent's message just before this prompt, from the end of the transcript, or None."""
    reader = READERS.get(agent)
    if reader is None or not isinstance(path, str) or not path or path.endswith(".zst"):
        return None
    try:
        return _last_reply(reader(_tail_lines(path)), prompt)
    except (OSError, ValueError):
        return None


def _session_file(memory: Memory) -> Path | None:
    """The evidence file of the session that runs this command. See the module text."""
    for name in SESSION_ENV:
        if os.environ.get(name):
            return evidence_path(memory, os.environ[name])
    folder = memory.dir / ".sessions"
    root, since = str(memory.project.root), time.time() - OPEN_SECONDS
    found = []
    for path in plainfile.files_in(memory.dir, folder, "*.owner.json"):
        with contextlib.suppress(OSError):
            if path.stat().st_mtime >= since and _read(path).get("root") == root:
                found.append(path)
    return found[0] if len(found) == 1 else None


def evidence(data: dict) -> list[Evidence]:
    items = [Evidence("prompt", str(row.get("text", ""))) for row in _list(data, "prompts")]
    items += [
        Evidence("choice" if row.get("kind") == "choice" else "prompt", str(row.get("text", "")))
        for row in _list(data, "choices")
    ]
    approval = data.get("approval")
    if isinstance(approval, dict):
        items.append(Evidence("approval", str(approval.get("text", ""))))
    return items


def check_claim(memory: Memory, text: str) -> Verdict:
    """Does a `told` claim of an agent match the owner's evidence of its session?"""
    path = _session_file(memory)
    data = _read(path) if path else {}
    if not data:
        return Verdict(False, "no owner prompt of this session was found")
    found = best_match(text, evidence(data))
    if found is None:
        return Verdict(False, "it is no copy of one sentence the owner said in this session")
    return Verdict(True, VIA[found.kind])
