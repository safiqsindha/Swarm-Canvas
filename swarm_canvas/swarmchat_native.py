"""Native SwarmChat 0.1.0 transport, with isolated private channels per attempt.

The run log is an audit copy. Inboxes always come from the actual server.
"""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from swarmchat import __version__
from swarmchat.client import Client, ClientError
from swarmchat.config import load
from swarmchat.server import make_server, save_read_positions

from swarm_canvas.channel_types import Line


class SwarmChatError(RuntimeError):
    """A native transport or protocol failure invalidates the attempt."""


class SwarmChatComms:
    def __init__(
        self,
        *,
        agent_ids: list[str],
        server_url: str = "",
        tokens: dict[str, str] | None = None,
        data_dir: Path | None = None,
        channel_name: str | None = None,
        messages_per_round: int = 2,
        max_chars: int = 200,
        inbox_context_lines: int = 20,
        path: Path | None = None,
    ):
        if not agent_ids or len(set(agent_ids)) != len(agent_ids):
            raise ValueError("SwarmChat needs unique permanent agent IDs")
        self.agent_ids = list(agent_ids)
        self.messages_per_round = messages_per_round
        self.max_chars = max_chars
        self.inbox_context_lines = inbox_context_lines
        self.path = path
        self.exposure: dict[str, list[int]] = {}
        self.native_read: dict[str, list[int]] = {}
        self.remote_errors: list[dict] = []
        self.required = True
        self.local = not server_url
        self.clients: dict[str, Client] = {}
        self._users: dict[str, str] = {}
        self._lines: dict[int, Line] = {}
        self._rounds: dict[str, int] = {}
        self._counts: dict[tuple[str, int], int] = {}
        self._watermark: dict[str, int] = {}
        self._round_views: dict[str, list[dict]] = {}
        self._active_round: int | None = None
        self._server = self._store = self._thread = None
        self._saver = self._stop_saver = None
        self._closed = False
        try:
            if self.local:
                if data_dir is None:
                    raise ValueError(
                        "Local SwarmChat requires an isolated data directory"
                    )
                self.server_url, tokens = self._start_local(data_dir)
            else:
                parsed = urlsplit(server_url)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.path not in {"", "/"}
                    or parsed.username
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError("SwarmChat URL must be an http(s) server origin")
                self.server_url = server_url.rstrip("/")
            # Explicit tokens prevent Client from falling back to an ambient login.
            if any(
                not (tokens or {}).get(a) or tokens[a] == "replace-me"
                for a in self.agent_ids
            ):
                raise ValueError(
                    "A real SwarmChat token is required for every permanent slot"
                )
            response = httpx.get(
                f"{self.server_url}/v1/health", timeout=5, trust_env=False
            )
            response.raise_for_status()
            health = response.json()
            if health.get("name") != "swarmchat" or health.get("version") != "0.1.0":
                raise SwarmChatError(
                    "Expected the verified SwarmChat 0.1.0 server protocol"
                )
            self.server_version = health["version"]
            for agent in self.agent_ids:
                self.clients[agent] = Client(self.server_url, tokens[agent])
                user = self._call(agent, "whoami")["user"]["id"]
                if user in self._users.values():
                    raise SwarmChatError(
                        "Every painter must authenticate as a different SwarmChat user"
                    )
                self._users[agent] = user
            self._agents = {user: agent for agent, user in self._users.items()}
            creator = self.agent_ids[0]
            channel = self._call(
                creator,
                "channel_create",
                name=channel_name or f"canvas-{uuid4().hex}",
                members=list(self._users.values()),
                public=False,
            )["chat"]
            self.channel_id, self.channel_name = channel["id"], channel["name"]
            for agent in self.agent_ids:
                info = self._call(agent, "chat_info", chat=self.channel_id)["chat"]
                if info["public"] or {m["id"] for m in info["members"]} != set(
                    self._users.values()
                ):
                    raise SwarmChatError(
                        "The run channel must be private and contain only its painters"
                    )
        except BaseException:
            self.close()
            raise

    def _start_local(self, data_dir: Path) -> tuple[str, dict[str, str]]:
        data_dir = Path(data_dir)
        self._server, self._store = make_server(
            load(data=str(data_dir), host="127.0.0.1", port=0, max_connections=64)
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self._thread.start()
        self._stop_saver = threading.Event()
        self._saver = threading.Thread(
            target=save_read_positions,
            args=(self._store, self._stop_saver),
            daemon=True,
        )
        self._saver.start()
        admin = Client(self._server.url, (data_dir / "admin.token").read_text().strip())
        try:
            tokens = {
                agent: admin.user_add(id=agent, name=agent)["token"]
                for agent in self.agent_ids
            }
        finally:
            admin.close()
        return self._server.url, tokens

    def _call(self, agent: str, method: str, **kwargs) -> dict:
        try:
            return getattr(self.clients[agent], method)(**kwargs)
        except (ClientError, OSError) as exc:
            status = getattr(exc, "status", 0)
            self.remote_errors.append({"operation": method, "http_status": status})
            raise SwarmChatError(
                f"SwarmChat {method} failed (HTTP {status}); attempt is invalid"
            ) from None

    def _line(self, message: dict, round_num: int) -> Line:
        if (
            message.get("chat") != self.channel_id
            or message.get("from") not in self._agents
        ):
            raise SwarmChatError(
                "Message is outside this run's native channel or participant set"
            )
        seq = message["seq"]
        if (
            not isinstance(seq, int)
            or isinstance(seq, bool)
            or seq < 1
            or not isinstance(message.get("text"), str)
        ):
            raise SwarmChatError("Malformed native message")
        line = Line(
            seq,
            self._agents[message["from"]],
            message["text"],
            self._rounds.get(message["id"], round_num),
            "message",
            remote_id=message["id"],
            read_by=[self._agents[u["id"]] for u in message["read_by"]]
            if "read_by" in message
            else None,
        )
        self._lines[seq] = line
        return line

    @property
    def lines(self) -> list[Line]:
        return [self._lines[n] for n in sorted(self._lines)]

    def render(self) -> str:
        return "".join(
            f"{line.number} [r{line.round} {line.agent}] {line.text}\n"
            for line in self.lines
        )

    def _save_log(self):
        if self.path is not None:
            self.path.write_text(self.render(), encoding="utf-8")

    def begin_round(self, round_num: int) -> None:
        """Freeze every native view before advancing any server read position."""
        if self._active_round == round_num:
            return
        views = {
            agent: self._call(
                agent,
                "read",
                chat=self.channel_id,
                **{"all": True},
                peek=True,
                limit=1_000_000,
            )["messages"]
            for agent in self.agent_ids
        }
        self._round_views = views
        self._active_round = round_num

    def inbox(self, agent: str, round: int) -> list[Line]:
        self.begin_round(round)
        messages = self._round_views[agent]
        last = self._watermark.get(agent, 0)
        fresh = [m for m in messages if m["seq"] > last]
        recent = (
            messages[-self.inbox_context_lines :] if self.inbox_context_lines else []
        )
        merged = {m["seq"]: m for m in [*recent, *fresh]}
        shown = [merged[n] for n in sorted(merged)]
        lines = [self._line(m, max(0, round - 1)) for m in shown]
        if shown:
            result = self._call(
                agent, "mark_messages_read", messages=shown, chat=self.channel_id
            )
            if not result or result.get("ok") is not True:
                raise SwarmChatError("The server did not confirm native read positions")
        numbers = [line.number for line in lines]
        self.exposure[agent] = numbers
        self.native_read[agent] = [
            line.number for line in lines if line.agent != agent
        ]  # native receipts concern other senders
        self._watermark[agent] = max((m["seq"] for m in messages), default=0)
        self._save_log()
        return lines

    def post(self, agent: str, text: str, round: int) -> int | None:
        key = agent, round
        if self._counts.get(key, 0) >= self.messages_per_round:
            return None
        result = self._call(
            agent, "send", chat=self.channel_id, text=text[: self.max_chars]
        )
        message = result["message"]
        self._rounds[message["id"]] = round
        line = self._line(message, round)
        self._counts[key] = self._counts.get(key, 0) + 1
        self._save_log()
        return line.number

    def ack(self, agent: str, line: int, round: int) -> int:
        if isinstance(line, bool) or line not in self.exposure.get(agent, []):
            return 0
        item = self._lines[line]
        result = self._call(
            agent,
            "mark_messages_read",
            messages=[{"chat": self.channel_id, "seq": item.number}],
            chat=self.channel_id,
        )
        if not result or result.get("ok") is not True:
            raise SwarmChatError("The server did not confirm the native acknowledgment")
        return line

    def metadata(self) -> dict:
        return {
            "transport": "native_local" if self.local else "native_remote",
            "client_version": __version__,
            "server_version": self.server_version,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "private": True,
            "users": dict(self._users),
        }

    def close(self):
        if self._closed:
            return
        self._closed = True
        for client in self.clients.values():
            client.close()
        if self._server is not None:
            if self._thread is not None and self._thread.is_alive():
                self._server.shutdown()
                self._thread.join(timeout=5)
            self._server.server_close()
        if self._stop_saver is not None:
            self._stop_saver.set()
            self._saver.join(timeout=5)
        if self._store is not None:
            self._store.close()
