"""A local fake model endpoint. It records each request and answers with fixed text.

It speaks three wire formats, because the tools differ: OpenAI chat completions, OpenAI
responses and Anthropic messages. No request leaves the computer.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_REPLY = "FAKE-PROVIDER-READY"
HIDDEN_HEADERS = {"authorization", "x-api-key", "cookie"}


def _sse(events: list[tuple[str | None, dict | str]]) -> bytes:
    lines = []
    for name, data in events:
        if name:
            lines.append(f"event: {name}")
        lines.append(f"data: {data if isinstance(data, str) else json.dumps(data)}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode()


def chat_completion(model: str, text: str) -> dict:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def chat_stream(model: str, text: str) -> bytes:
    base = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": model}

    def chunk(delta: dict, finish: str | None = None, **extra) -> dict:
        choice = {"index": 0, "delta": delta, "finish_reason": finish}
        return {**base, "created": int(time.time()), "choices": [choice], **extra}

    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    return _sse(
        [
            (None, chunk({"role": "assistant", "content": ""})),
            (None, chunk({"content": text})),
            (None, chunk({}, "stop")),
            (None, {**base, "created": int(time.time()), "choices": [], "usage": usage}),
            (None, "[DONE]"),
        ]
    )


def responses_stream(model: str, text: str) -> bytes:
    item = {
        "id": "msg_fake",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    usage = {
        "input_tokens": 1,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 1,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 2,
    }
    base = {"id": "resp_fake", "object": "response", "model": model, "created_at": int(time.time())}
    partial = {**item, "status": "in_progress", "content": []}
    part = {"type": "output_text", "text": "", "annotations": []}
    done = {**base, "status": "completed", "output": [item], "usage": usage}
    events = [
        ("response.created", {"response": {**base, "status": "in_progress", "output": []}}),
        ("response.output_item.added", {"output_index": 0, "item": partial}),
        (
            "response.content_part.added",
            {"item_id": "msg_fake", "output_index": 0, "content_index": 0, "part": part},
        ),
        (
            "response.output_text.delta",
            {"item_id": "msg_fake", "output_index": 0, "content_index": 0, "delta": text},
        ),
        (
            "response.output_text.done",
            {"item_id": "msg_fake", "output_index": 0, "content_index": 0, "text": text},
        ),
        (
            "response.content_part.done",
            {
                "item_id": "msg_fake",
                "output_index": 0,
                "content_index": 0,
                "part": {**part, "text": text},
            },
        ),
        ("response.output_item.done", {"output_index": 0, "item": item}),
        ("response.completed", {"response": done}),
    ]
    return _sse([(name, {"type": name, **body}) for name, body in events])


def anthropic_message(model: str, text: str) -> dict:
    return {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def anthropic_stream(model: str, text: str) -> bytes:
    start = {**anthropic_message(model, text), "content": [], "stop_reason": None}
    events = [
        ("message_start", {"message": start}),
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"index": 0}),
        (
            "message_delta",
            {
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        ("message_stop", {}),
    ]
    return _sse([(name, {"type": name, **body}) for name, body in events])


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeProvider/1"

    def log_message(self, format, *args):
        return

    def _record(self, body: object) -> None:
        headers = {k.lower(): v for k, v in self.headers.items()}
        kept = {k: v for k, v in headers.items() if k not in HIDDEN_HEADERS}
        entry = {"method": self.command, "path": self.path, "headers": kept, "body": body}
        with self.server.lock, self.server.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _send(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, data: dict) -> None:
        self._send(json.dumps(data).encode(), "application/json")

    def _refuse(self, status: int) -> None:
        error = {"type": "authentication_error", "message": "invalid api key", "code": status}
        payload = json.dumps({"type": "error", "error": error}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._record(None)
        path = self.path.split("?")[0]
        if path.endswith("/models"):
            model = {"id": "fake-small", "object": "model", "owned_by": "fake", "created": 0}
            self._json({"object": "list", "data": [model], "models": [{"slug": "fake-small"}]})
            return
        self._json({})

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {"unparsed": raw.decode("utf-8", "replace")}
        self._record(body)
        if self.server.status:
            self._refuse(self.server.status)
            return
        path = self.path.split("?")[0]
        data = body if isinstance(body, dict) else {}
        model = str(data.get("model") or "fake-small")
        stream = bool(data.get("stream"))
        text = self.server.reply
        if path.endswith("/count_tokens"):
            self._json({"input_tokens": 1})
        elif path.endswith("/messages"):
            if stream:
                self._send(anthropic_stream(model, text), "text/event-stream")
            else:
                self._json(anthropic_message(model, text))
        elif path.endswith("/responses"):
            self._send(responses_stream(model, text), "text/event-stream")
        elif path.endswith("/chat/completions"):
            if stream:
                self._send(chat_stream(model, text), "text/event-stream")
            else:
                self._json(chat_completion(model, text))
        else:
            self._json({})


class FakeProvider:
    """A running server. Use it as a context manager. `url` has no trailing slash."""

    def __init__(
        self,
        log_path: Path,
        reply: str = DEFAULT_REPLY,
        port: int = 0,
        status: int | None = None,
    ):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.touch()
        self._server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self._server.daemon_threads = True
        self._server.log_path = self.log_path
        self._server.reply = reply
        self._server.status = status
        self._server.lock = threading.Lock()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FakeProvider:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def requests(self) -> list[dict]:
        return read_requests(self.log_path)


def read_requests(log_path: Path) -> list[dict]:
    rows = []
    for line in Path(log_path).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def model_requests(rows: list[dict]) -> list[dict]:
    """Only the requests that ask a model for text."""
    wanted = ("/messages", "/responses", "/chat/completions")
    return [
        row
        for row in rows
        if row.get("method") == "POST" and row.get("path", "").split("?")[0].endswith(wanted)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path, help="JSON Lines file for the requests")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--reply", default=DEFAULT_REPLY)
    args = parser.parse_args()
    with FakeProvider(args.log, args.reply, args.port) as provider:
        print(provider.url, flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
