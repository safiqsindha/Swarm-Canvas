"""NoComms (C0, C1), DocLog (C2a), and SwarmChatComms (C2b)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx


@dataclass
class Line:
    number: int
    agent: str
    text: str
    round: int
    kind: str


class Comms(Protocol):
    def post(self, agent: str, text: str, round: int) -> int | None: ...

    def ack(self, agent: str, line: int, round: int) -> int: ...

    def inbox(self, agent: str, round: int) -> list[Line]: ...


@dataclass
class _LogBook:
    """Append-only numbered log shared by DocLog and the local SwarmChat mirror."""

    messages_per_round: int = 2
    max_chars: int = 200
    inbox_context_lines: int = 20
    path: Path | None = None
    lines: list[Line] = field(default_factory=list)
    exposure: dict[str, list[int]] = field(default_factory=dict)
    native_read: dict[str, list[int]] = field(default_factory=dict)
    _counts: dict[tuple[str, int], int] = field(default_factory=dict)
    _watermark: dict[str, int] = field(default_factory=dict)

    def post(self, agent: str, text: str, round: int) -> int | None:
        key = (agent, round)
        used = self._counts.get(key, 0)
        if used >= self.messages_per_round:
            return None
        self._counts[key] = used + 1
        return self._append(agent, text[: self.max_chars], round, "message")

    def ack(self, agent: str, line: int, round: int) -> int:
        if not isinstance(line, int) or isinstance(line, bool):
            return 0
        if line < 1 or line > len(self.lines):
            return 0
        text = f"✓ {agent} read #{line}"
        return self._append(agent, text, round, "ack")

    def inbox(self, agent: str, round: int) -> list[Line]:
        del round  # the watermark, not the round number, decides what is new
        last = self._watermark.get(agent, 0)
        fresh = [line for line in self.lines if line.number > last]
        context = self.lines[-self.inbox_context_lines :] if self.inbox_context_lines else []
        merged = {line.number: line for line in context}
        for line in fresh:
            merged[line.number] = line
        shown = [merged[number] for number in sorted(merged)]
        self._watermark[agent] = self.lines[-1].number if self.lines else 0
        numbers = [line.number for line in shown]
        self.exposure[agent] = numbers
        self.native_read[agent] = list(numbers)
        return shown

    def render(self) -> str:
        rows = [f"{line.number} [r{line.round} {line.agent}] {line.text}" for line in self.lines]
        return ("\n".join(rows) + "\n") if rows else ""

    def _append(self, agent: str, text: str, round: int, kind: str) -> int:
        number = len(self.lines) + 1
        self.lines.append(Line(number, agent, text, round, kind))
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(self.render(), encoding="utf-8")
        return number


class NoComms:
    """C0 and C1. Posts and acks are ignored. Inbox is always empty."""

    def __init__(self):
        self.exposure: dict[str, list[int]] = {}
        self.native_read: dict[str, list[int]] = {}
        self.lines: list[Line] = []

    def post(self, agent: str, text: str, round: int) -> int | None:
        del agent, text, round
        return None

    def ack(self, agent: str, line: int, round: int) -> int:
        del agent, line, round
        return 0

    def inbox(self, agent: str, round: int) -> list[Line]:
        del round
        self.exposure[agent] = []
        self.native_read[agent] = []
        return []


class DocLog(_LogBook):
    """C2a. In-memory log mirrored to doc_log.txt. Acks do not use the note cap."""


class SwarmChatComms(_LogBook):
    """C2b. Local log plus an optional HTTP mirror.

    The engine still enforces the note cap and round boundaries. When
    `server_url` is unset or the server errors, the local log stands and the
    run continues. Native read state is recorded on inbox().
    """

    def __init__(
        self,
        server_url: str = "",
        tokens: dict[str, str] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.server_url = (server_url or "").rstrip("/")
        self.tokens = dict(tokens or {})
        self.remote_errors: list[str] = []

    def post(self, agent: str, text: str, round: int) -> int | None:
        number = super().post(agent, text, round)
        if number is not None:
            self._mirror(agent, text, round, "message")
        return number

    def ack(self, agent: str, line: int, round: int) -> int:
        number = super().ack(agent, line, round)
        if number:
            self._mirror(agent, f"✓ {agent} read #{line}", round, "ack")
        return number

    def _mirror(self, agent: str, text: str, round: int, kind: str) -> None:
        if not self.server_url:
            return
        token = self.tokens.get(agent, "")
        url = f"{self.server_url}/channels/canvas/messages"
        try:
            response = httpx.post(
                url,
                json={"agent": agent, "text": text, "round": round, "kind": kind},
                headers={"Authorization": f"Bearer {token}"} if token else {},
                timeout=5.0,
            )
            response.raise_for_status()
        except Exception as exc:  # fail soft: the local log already holds the line
            self.remote_errors.append(f"{type(exc).__name__}: {exc}")
