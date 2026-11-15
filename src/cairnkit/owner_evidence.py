"""What the owner said in a session, kept so that a `told` claim of an agent can be checked.

The data shape: one file for each session, `<memory>/.sessions/<id>.owner.json`, beside the session
state (see session.py), so the other hooks of a session do not read or write it.

    {"root": checkout path,
     "agent": the agent tool of the session,
     "ids": [the session ids that the hooks saw, newest last],
     "transcripts": [the transcript paths of the session, at most TRANSCRIPTS_KEPT, newest last],
     "prompts": [{"at", "text"}],                # the newest PROMPTS_KEPT owner prompts
     "choices": [{"at", "kind", "text", "answer"}],  # answers to agent questions, this turn only
     "approval": {"at", "text", "prompt"} | null}  # the question that this turn's "yes" answered

A prompt keeps only what the owner typed (`signals.owner_typed`): a paste, a quoted line, a
side agent's note and a quoted sentence are someone else's words. A free answer to an agent
question is cleaned the same way. The proof cleans the transcript's prompts the same way. Each
text is masked as a whole, then cut. A prompt with words that the owner typed starts a turn, so
it clears the choices and the approval of the turn before, also when its words are kept as no
evidence because they name a command of this tool; a prompt with none leaves them. The
prompt hook writes it, and the hook after a tool adds the label that the owner picked in an agent
question. `memory add` reads it (`check_claim`), and so does `memory change` when an agent ends a
fact that a person stated (`names_ids`).

The approval. When the owner's whole prompt is a short yes (see `is_approval`), the prompt hook
reads the agent's last message from the transcript that the payload names. Only the sentence that
ends that message counts, and only when it is a question: that is what the "yes" answers. The rest
of the message is often a report of what a tool or a page said, which the owner did not approve.
A tool step after the message, or a message that ends in no question, gives no approval.

The transcript proves the evidence. Any process of the same user can pipe a payload into
`memory hook prompt`, so for a tool whose transcript cairnkit reads (READERS), `check_claim`
counts a prompt only when the transcript holds it as an owner prompt, an approval only when it
holds the "yes" and the question, and an answer only when the result of an agent question
holds it. A message that the owner typed while the agent worked is an owner prompt too: Claude
Code runs the prompt hook for it between tool calls, and records it as a queued attachment
(`_typed_queued`). It reads the transcript when the claim is checked, not in the prompt hook,
because the tool may write the prompt to the transcript after the hook runs. The first prompt of
a session fixes its transcript path, and a prompt that names another path is not kept. Only a
session start of the same session (a resume, a compaction, a clear or a fork) adds a new path,
because the tool may write a resumed session to a new file. The proof reads the newest path and
the one before it. A transcript that cannot be read proves nothing. For another tool there is no
transcript to read, so its evidence counts as kept: that is a known limit. A forger can still
write a fake transcript, or the evidence file itself; the before-shell hook (forgery.py) refuses
those commands in the agent's shell.

How `memory add` finds its session (`_session_file`). Claude Code, Codex and Grok put a session id
in the shell of the agent (SESSION_ENV). The hooks keep each id that they see for a session: the
payload's id, and the id in the hook's own environment. A session file is the agent's own when one
of its ids is in the agent's shell. A file is open when its newest owner prompt is less than
OPEN_SECONDS old. The claim takes, in this order: the one own file that is open; else the one own
file; else, only when the session has no own file at all, the one open file of this checkout. No
file, or a choice between two, gives no evidence, and the claim stays unconfirmed.

The open file of this checkout is the fallback for an agent with no id in its shell (Cursor, Pi,
OpenCode). A session that kept evidence never borrows another session's words, also when it has
been quiet for a while; after a resume the hooks record the shell's id as an alias, so the own
file is still found. What a claim binds is only what the owner typed in that session, and for a
tool in READERS that session's transcript must prove it.
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
from cairnkit.ranking import ID
from cairnkit.secretscan import mask
from cairnkit.session import state_path, write_state
from cairnkit.signals import owner_typed, starts_a_turn
from cairnkit.told_match import (
    NOT,
    Evidence,
    best_match,
    choice_evidence,
    final_question,
    is_approval,
    join_labels,
    only_approval,
    sentences,
    states_a_rule,
    stem,
    tokens,
)

PROMPTS_KEPT = 12
PROMPT_CHARS = 1500
CHOICES_KEPT = 8
CHOICE_CHARS = 1000
PROPOSAL_CHARS = 1200
TAIL_BYTES = 512 * 1024
# The proof reads the end of the transcript. Older owner words are unproven, so they confirm
# nothing, which is the safe side; a told add stays fast in a long session.
PROOF_BYTES = 4 * 1024 * 1024
PROOF_AGENT_TEXTS = 20
OPEN_SECONDS = 1800
TRANSCRIPTS_KEPT = 2
IDS_KEPT = 8
# The variable that holds the session id in the agent's shell, for each tool. Claude Code sets it
# for each shell command and each hook from the current session (read in its binary, 2.1.319).
# Codex and Grok are inferred from their names.
AGENT_ENV = {
    "claude": "CLAUDE_CODE_SESSION_ID",
    "codex": "CODEX_THREAD_ID",
    "grok": "GROK_SESSION_ID",
}
SESSION_ENV = tuple(AGENT_ENV.values())
QUESTION_TOOL = "AskUserQuestion"
ANSWER_PAIR = re.compile(r'"([^"]*)"="([^"]*)"')
# How the tool result text that the model reads holds an answer: a pick, and the words that the
# owner typed instead of a pick (Claude Code 2.1.325; "They also wrote" in a follow-up round).
ANSWER_FORMS = ('="{}"', "The user responded: {}", 'They also wrote: "{}"')
RESPONDED = "The user responded: "
# The result text of a dialog that closed while the owner was away (Claude Code 2.1.325).
AWAY = ("the user may be away from keyboard", "Before going idle the user had selected: ")
VIA = {
    "prompt": "words the owner typed in this session",
    "choice": "the option the owner picked in this turn",
    "approval": "the proposal the owner approved in this turn",
}


APPROVAL_ONLY = (
    'its words are only a reply such as "yes" or "ok", which says nothing to a later reader'
)


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
    """The masked text, cut to width. The whole text is masked before the cut, so no cut leaves
    part of a secret: a raw cut first could split a value, and its first half would not look
    secret to the mask."""
    return mask(text, memory.env)[:width]


def _list(data: dict, name: str) -> list[dict]:
    rows = data.get(name)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _ids(data: dict, key: str, agent: str) -> list[str]:
    """The session ids kept, with the payload's id and the id in this hook's environment."""
    found = _strings(data, "ids")
    name = AGENT_ENV.get(agent)
    found += [key, *([os.environ[name]] if name and os.environ.get(name) else [])]
    return list(dict.fromkeys(found))[-IDS_KEPT:]


def _strings(data: dict, name: str) -> list[str]:
    items = data.get(name)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, str) and item]


def _transcripts(data: dict) -> list[str]:
    return _strings(data, "transcripts")


def note_start(memory: Memory, key: str, agent: str, payload: dict) -> None:
    """A session resumes, is compacted, cleared or forked. When it has evidence, keep its ids, and
    make the transcript that the payload names the newest one of the session. A session with no
    evidence gets its transcript from its first prompt."""
    path = evidence_path(memory, key)
    data = _read(path)
    if not data:
        return
    known = _transcripts(data)
    transcript = str(payload.get("transcript_path") or "")
    if transcript:
        known = [item for item in known if item != transcript] + [transcript]
    data.update(
        root=str(memory.project.root),
        agent=agent,
        ids=_ids(data, key, agent),
        transcripts=known[-TRANSCRIPTS_KEPT:],
    )
    write_state(memory, path, data)


def note_prompt(memory: Memory, key: str, agent: str, payload: dict) -> None:
    """Keep an owner prompt. For a short yes, keep the agent's question that it answered.

    A prompt with words that the owner typed starts a turn (`starts_a_turn`), so it ends the
    choices and the approval of the turn before, also when it names a command of this tool and
    so keeps nothing of its own. A prompt with none (a task notification, a side agent's note, a
    `memory check` line, a paste) keeps nothing and leaves the turn open: Claude Code gives such
    prompts to the agent in the middle of the owner's turn, also while a dialog is open.
    """
    prompt = str(payload.get("prompt") or "")
    path = evidence_path(memory, key)
    old = _read(path)
    transcript = str(payload.get("transcript_path") or "") or None
    known = _transcripts(old)
    if known and transcript not in known:
        return  # a prompt from another transcript is no prompt of this session
    moment = time.time()
    own = _own_words(memory, prompt)
    turn = starts_a_turn(prompt)
    prompts = _list(old, "prompts")
    if own:
        prompts.append({"at": moment, "text": own})
    approval = None
    if own and is_approval(prompt):
        message = last_agent_message(agent, transcript, prompt)
        question = final_question(message) if message else None
        if question:
            text = _kept(memory, question, PROPOSAL_CHARS)
            approval = {"at": moment, "text": text, "prompt": own}
    data = {
        "root": str(memory.project.root),
        "agent": agent,
        "ids": _ids(old, key, agent),
        "transcripts": known or ([transcript] if transcript else []),
        "prompts": prompts[-PROMPTS_KEPT:],
        "choices": [] if turn else _list(old, "choices"),
        "approval": approval if turn else old.get("approval"),
    }
    write_state(memory, path, data)


def _own_words(memory: Memory, prompt: str) -> str:
    """The prompt as it is kept: only what the owner typed, masked, cut."""
    own = owner_typed(prompt)
    return _kept(memory, own, PROMPT_CHARS) if own else ""


def _holder(value: object, depth: int = 3) -> dict | None:
    """The dict that holds a dict `answers`: the value, or a dict nested in it."""
    if isinstance(value, dict):
        if isinstance(value.get("answers"), dict):
            return value
        value = list(value.values())
    for child in value if depth and isinstance(value, list) else []:
        if (found := _holder(child, depth - 1)) is not None:
            return found
    return None


def _reply(value: object) -> str:
    """One answer. A list of labels is joined as Claude Code joins a multi-select."""
    if isinstance(value, list):
        return join_labels([item for item in value if isinstance(item, str)])
    return value if isinstance(value, str) else ""


def _answers(*sources: object) -> dict[str, str]:
    """{question: answer} from the tool input and the tool result. A later source wins.

    Claude Code (2.1.325) gives the tool's data `{questions, answers, ...}` as the result, and
    the input holds the answers that the dialog collected. A result can also be text, or a list
    of text blocks, with `"question"="answer"` pairs: the text that the model reads.
    """
    found: dict[str, str] = {}
    for source in sources:
        holder = _holder(source)
        if holder is not None:
            found.update({str(q): _reply(a) for q, a in holder["answers"].items()})
        else:
            for text in _texts(source, ("text",)):
                found.update(ANSWER_PAIR.findall(text))
    return {question: reply for question, reply in found.items() if reply.strip()}


def _response(*sources: object) -> str:
    """The words that the owner typed in the dialog instead of a pick: `response` in the tool
    input or data, or the result text "The user responded: ..." that the model reads. A later
    source wins."""
    found = ""
    for source in sources:
        holder = _holder(source) or source
        if isinstance(holder, dict) and isinstance(holder.get("response"), str):
            found = holder["response"]
        for text in _texts(source, ("text",)):
            if text.startswith(RESPONDED):
                found = text[len(RESPONDED) :]
    return found.strip()


def note_answer(memory: Memory, key: str, payload: dict) -> None:
    """Keep what the owner chose in an agent question (Claude Code's AskUserQuestion).

    A dialog that closed while the owner was away (`afkTimeoutMs`, or a result text of AWAY)
    and a question that Claude Code marks as `unanswered` keep nothing: the owner gave no answer,
    and the text in `answers` is then the tool's.
    """
    if payload.get("tool_name") != QUESTION_TOOL:
        return
    tool_input = payload.get("tool_input")
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    result = _holder(payload.get("tool_response")) or {}
    texts = _texts(payload.get("tool_response"), ("text",))
    if result.get("afkTimeoutMs") or any(mark in text for text in texts for mark in AWAY):
        return
    notes = result.get("annotations")
    notes = notes if isinstance(notes, dict) else {}
    answers = _answers(tool_input, payload.get("tool_response"))
    found = []
    for item in questions if isinstance(questions, list) else []:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "")
        note = notes.get(question)
        if isinstance(note, dict) and note.get("unanswered"):
            continue
        options = item.get("options")
        options = (
            [opt for opt in options if isinstance(opt, dict)] if isinstance(options, list) else []
        )
        labels = [str(opt.get("label") or "") for opt in options]
        reply = answers.get(question, "")
        evidence = choice_evidence(labels, reply)
        if evidence and evidence.kind == "prompt":
            evidence = Evidence("prompt", owner_typed(evidence.text, veto=False))
        if evidence and evidence.text:
            found.append((evidence, reply))
    response = _response(tool_input, payload.get("tool_response"))
    if typed := owner_typed(response, veto=False):
        found.append((Evidence("prompt", typed), response))
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
            "answer": _kept(memory, reply, CHOICE_CHARS),
        }
        for item, reply in found
    ]
    data["choices"] = choices[-CHOICES_KEPT:]
    write_state(memory, path, data)


def _tail_lines(path: str, width: int = TAIL_BYTES) -> list[str]:
    """The whole lines in the last `width` bytes of a regular file, newest first."""
    fd = plainfile.open_fd(path)
    with os.fdopen(fd, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        start = max(0, size - width)
        fh.seek(start)
        lines = fh.read(width).decode("utf-8", "replace").splitlines()
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


def _results(content: object, ids: set[str]) -> list[str]:
    """The text of each tool result block of a tool use in `ids`."""
    found = []
    for block in content if isinstance(content, list) else []:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_result"
            and block.get("tool_use_id") in ids
        ):
            inner = block.get("content")
            found += [inner] if isinstance(inner, str) else _texts(inner, ("text",))
    return found


# Marks of a queued message that no person typed in this session (Claude Code 2.1.325).
NOT_TYPED_QUEUED = (
    "isMeta",
    "textNotTyped",
    "promptRewritten",
    "verifiedSlackHumanTurn",
    "fromConnector",
    "forwardedIntent",
)


def _typed_queued(attachment: object) -> bool:
    """A message that the owner typed while the agent worked. Claude Code gives it to the agent
    between tool calls and records it as `{"type": "queued_command", "prompt": text or blocks,
    "commandMode": "prompt", "origin": {"kind": "human"}}`. Claude Code itself counts a queued
    message as a human turn only with that origin. Another origin, or none, is another sender: a
    peer agent, a task or a channel."""
    if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
        return False
    origin = attachment.get("origin")
    human = isinstance(origin, dict) and origin.get("kind") == "human"
    return (
        human
        and attachment.get("commandMode") == "prompt"
        and not any(attachment.get(name) for name in NOT_TYPED_QUEUED)
    )


def _content(record: dict) -> object:
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _claude_turns(lines: list[str]):
    """Claude Code: `type: assistant` records hold text, tool_use or thinking blocks. A
    `type: user` record is a prompt, or a tool result. An `isMeta` record is text that the tool
    added. A thinking block is no step. A message that the owner typed during a turn is a
    `type: attachment` record (`_typed_queued`). A tool step gives the text of a result only
    for an agent question (QUESTION_TOOL), matched by the id of its tool use."""
    records = [(record, _content(record)) for record in _records(lines)]
    asked = {
        str(block.get("id"))
        for record, content in records
        if record.get("type") == "assistant" and isinstance(content, list)
        for block in content
        if isinstance(block, dict) and block.get("name") == QUESTION_TOOL
    }
    for record, content in records:
        kind = record.get("type")
        if kind == "assistant" and _texts(content, ("tool_use", "server_tool_use")) != []:
            yield "tool", []
        elif kind == "assistant" and _texts(content, ("text",)):
            yield "agent", _texts(content, ("text",))
        elif kind == "user" and not record.get("isMeta"):
            if _texts(content, ("tool_result",)) != [] or not _texts(content, ("text",)):
                yield "tool", _results(content, asked)
            else:
                yield "owner", _texts(content, ("text",))
        elif kind == "attachment" and not record.get("isMeta"):
            attachment = record.get("attachment")
            if _typed_queued(attachment):
                yield "owner", _texts(attachment.get("prompt"), ("text",))


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


def _last_prompt(data: dict) -> float:
    times = [row.get("at") for row in _list(data, "prompts")]
    return max((at for at in times if isinstance(at, (int, float))), default=0.0)


def _session_file(memory: Memory) -> Path | None:
    """The evidence file of the session that runs this command. See the module text."""
    ids = {os.environ[name] for name in SESSION_ENV if os.environ.get(name)}
    named = {evidence_path(memory, item) for item in ids}
    root, since = str(memory.project.root), time.time() - OPEN_SECONDS
    own, own_open, here_open = [], [], []
    for path in plainfile.files_in(memory.dir, memory.dir / ".sessions", "*.owner.json"):
        with contextlib.suppress(OSError):
            data = _read(path)
            fresh = _last_prompt(data) >= since
            if path in named or ids & set(_strings(data, "ids")):
                own.append(path)
                own_open += [path] if fresh else []
            if fresh and data.get("root") == root:
                here_open.append(path)
    # Another open session of the checkout counts only when this session kept no evidence at
    # all: a quiet own session must not borrow another session's words.
    found = own_open or own or here_open
    return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class Seen:
    """What the transcript holds, masked and cut as the evidence is."""

    owner: frozenset[str]  # owner prompts
    agent: tuple[str, ...]  # agent messages
    tool: tuple[str, ...]  # the results of agent questions


def transcript_seen(memory: Memory, data: dict) -> Seen | None:
    """What the session's transcripts hold, newest first, or None when none can be read."""
    reader = READERS.get(str(data.get("agent")))
    turns, read = [], False
    for path in reversed(_transcripts(data)):
        if reader is None or path.endswith(".zst"):
            continue
        with contextlib.suppress(OSError, ValueError):
            turns += list(reader(_tail_lines(path, PROOF_BYTES)))
            read = True
    if not read:
        return None
    texts = {role: [text for r, texts in turns if r == role for text in texts] for role in
             ("owner", "agent", "tool")}  # fmt: skip
    return Seen(
        frozenset(_own_words(memory, text) for text in texts["owner"]),
        tuple(
            mask(text, memory.env) for text in texts["agent"][:PROOF_AGENT_TEXTS]
        ),  # newest first
        tuple(
            mask(text, memory.env)
            for text in texts["tool"]
            if any(form.partition("{}")[0] in text for form in ANSWER_FORMS)
        ),
    )


def evidence(data: dict, seen: Seen | None = None) -> list[Evidence]:
    """The evidence of the session, oldest first by the time that the owner gave it. With
    `seen`, only what the transcript holds."""

    def held(row: dict) -> bool:
        if seen is None:
            return True
        answer = str(row.get("answer") or "")
        forms = [form.format(answer) for form in ANSWER_FORMS]
        return bool(answer) and any(form in text for text in seen.tool for form in forms)

    rows = [
        (row, Evidence("prompt", str(row.get("text", ""))))
        for row in _list(data, "prompts")
        if seen is None or str(row.get("text", "")) in seen.owner
    ]
    rows += [
        (
            row,
            Evidence(
                "choice" if row.get("kind") == "choice" else "prompt", str(row.get("text", ""))
            ),
        )
        for row in _list(data, "choices")
        if held(row)
    ]
    approval = data.get("approval")
    if isinstance(approval, dict) and (
        seen is None
        or (
            approval.get("prompt") in seen.owner
            and any(str(approval.get("text")) in text for text in seen.agent)
        )
    ):
        rows.append((approval, Evidence("approval", str(approval.get("text", "")))))
    rows.sort(key=lambda pair: at if isinstance(at := pair[0].get("at"), (int, float)) else 0.0)
    return [item for _, item in rows]


def _session_evidence(memory: Memory) -> list[Evidence] | Verdict:
    """The proven evidence of the session that runs this command, or a Verdict that says why
    there is none."""
    path = _session_file(memory)
    data = _read(path) if path else {}
    if not data or not data.get("agent"):
        return Verdict(False, "no owner prompt of this session was found")
    seen = None
    if data["agent"] in READERS:
        seen = transcript_seen(memory, data)
        if seen is None:
            return Verdict(False, "the transcript of this session could not be read")
    return evidence(data, seen)


def check_claim(memory: Memory, text: str) -> Verdict:
    """Does a `told` claim of an agent match the owner's evidence of its session?"""
    if only_approval(text):
        return Verdict(False, APPROVAL_ONLY)
    items = _session_evidence(memory)
    if isinstance(items, Verdict):
        return items
    found = best_match(text, items)
    if found is None:
        return Verdict(False, "it is no copy of one sentence the owner said in this session")
    return Verdict(True, VIA[found.kind])


# A sentence with one of these words keeps the fact, or makes its end wait for something.
_KEEP_TEXT = "keep stay retain stop skip avoid refuse except unless until without if"
_KEEPS = frozenset([NOT, *map(stem, _KEEP_TEXT.split())])
# A later sentence of the same prompt with one of these words takes an end back: "Wait, don't."
_TAKES_BACK = _KEEPS | {*map(stem, ["wait", "cancel", "hold", "scratch"])}
# A request in the form of a question: "Can you end ID?", "Please end ID?". Only the ids follow
# the verb, so "Can you end the note in ID?" asks for no end. "Will you" and "would you" often ask
# about the agent's plan, so they do not count.
_END_REQUEST = re.compile(
    rf"(?i)(?:(?:can|could) you(?: please)?|please) (?:end|expire|forget|drop|remove)"
    rf" {ID}(?:(?:,? and|,) {ID})*(?:,? please)?\?*"
)


def names_ids(memory: Memory, ids: list[str]) -> Verdict:
    """Does the owner's own evidence of this session hold each id, so that an agent may end
    the fact that a person stated?

    Only a sentence that the owner typed (a prompt, or an answer that is no option) or the
    closing question that the owner approved with a short yes in this turn counts, with the
    transcript proof of `check_claim`. The id must be in that sentence itself: words that only
    share a word with the fact name nothing. The newest such sentence decides, so "Keep ID" after
    "End ID" keeps it. A sentence with a word of _KEEPS ("Do not end ID") keeps the fact, and so
    does a later sentence of the same prompt with a word of _TAKES_BACK ("End ID. Wait, don't."),
    with no id or another one. A question that the owner typed ("Should we end ID?") counts for
    nothing, unless it is a request of _END_REQUEST ("Can you end ID?").
    """
    items = _session_evidence(memory)
    if isinstance(items, Verdict):
        return items
    kinds = []
    for fact_id in ids:
        newest = None  # the kind of the evidence of the newest sentence, or "keep"
        for item in items:  # oldest first
            if item.kind not in ("prompt", "approval"):
                continue
            ended_here = False
            for sentence in sentences(item.text):
                keys = {key for key, _ in tokens(sentence)}
                if fact_id not in re.findall(ID, sentence.lower()):
                    if ended_here and keys & _TAKES_BACK:
                        newest, ended_here = "keep", False
                    continue
                if keys & _KEEPS:
                    newest, ended_here = "keep", False
                elif (
                    item.kind == "approval"
                    or states_a_rule(sentence)
                    or _END_REQUEST.fullmatch(" ".join(sentence.split()))
                ):
                    newest, ended_here = item.kind, True
        if newest is None:
            return Verdict(
                False,
                f"no sentence that the owner typed or approved in this session holds {fact_id}",
            )
        if newest == "keep":
            return Verdict(False, f"the newest sentence of the owner with {fact_id} keeps it")
        kinds.append(newest)
    return Verdict(True, " and ".join(VIA[kind] for kind in dict.fromkeys(kinds)))
