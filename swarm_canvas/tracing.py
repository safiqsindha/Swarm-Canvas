"""Run-scoped, redacted JSONL audit plus optional Langfuse SDK/Broadcast export."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

_current = ContextVar("canvas_trace", default=None)
_parent = ContextVar("canvas_span", default=None)
_sensitive = re.compile(r"^(authorization|api[_-]?key|.*secret.*|.*access[_-]?token|token|tokens|password)$", re.I)
_key_pattern = re.compile(r"\b(?:sk-or-v1-|sk-lf-|pk-lf-)[A-Za-z0-9_-]+")


class Observation:
    def __init__(self, recorder, name, kind, fields):
        self.recorder = recorder
        self.id = uuid4().hex[:16]
        self.parent_id = _parent.get()
        self.fields = dict(name=name, as_type=kind, **fields)
        self.sdk = None

    def update(self, **fields):
        # Merge metadata so usage/response updates cannot discard request context.
        if "metadata" in fields:
            fields["metadata"] = {**self.fields.get("metadata", {}), **fields["metadata"]}
        self.fields.update(fields)
        if self.sdk is not None:
            self.recorder.safe_sdk(lambda: self.sdk.update(**self.recorder.mask(fields)))


class Recorder:
    def __init__(self, path: Path, run_id: str, mode: str, client=None, resume=False):
        self.run_id, self.mode, self.client = run_id, mode, client
        self.trace_id = json.loads(path.read_text().splitlines()[0])['trace_id'] if resume else uuid4().hex
        self.lock = threading.RLock()
        self.secrets = set()
        for key, value in os.environ.items():
            if re.search(r"KEY|TOKEN|SECRET|PASSWORD", key) and len(value) >= 8:
                self.secrets.add(value)
        self.file = path.open("a" if resume else "x", encoding="utf-8")
        self.export_errors = 0

    def mask(self, value):
        if isinstance(value, dict):
            return {str(k): "[REDACTED]" if _sensitive.match(str(k)) else self.mask(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.mask(v) for v in value]
        if isinstance(value, str):
            with self.lock:
                for secret in self.secrets:
                    value = value.replace(secret, "[REDACTED]")
            return _key_pattern.sub("[REDACTED]", value)
        return value

    def write(self, data):
        with self.lock:
            self.file.write(json.dumps(self.mask({"trace_id": self.trace_id, "session_id": self.run_id, **data}), ensure_ascii=False, default=str) + "\n")
            self.file.flush()

    def safe_sdk(self, fn):
        try:
            return fn()
        except Exception as exc:
            self.export_errors += 1
            self.write({"event": "export_error", "error_type": type(exc).__name__})
            return None

    @contextmanager
    def observation(self, name, kind="span", **fields):
        obs = Observation(self, name, kind, fields)
        started = time.monotonic()
        manager = None
        if self.client is not None:
            manager = self.safe_sdk(lambda: self.client.start_as_current_observation(
                **self.mask(obs.fields),
                trace_context={"trace_id": self.trace_id, **({"parent_span_id": obs.parent_id} if obs.parent_id else {})},
            ))
            if manager is not None:
                obs.sdk = self.safe_sdk(manager.__enter__)
                if obs.sdk is not None:
                    obs.id = obs.sdk.id
        token = _parent.set(obs.id)
        self.write({"event": "start", "id": obs.id, "parent_id": obs.parent_id, **obs.fields})
        try:
            yield obs
        except BaseException as exc:
            obs.update(level="ERROR", status_message=type(exc).__name__)
            raise
        finally:
            self.write({"event": "end", "id": obs.id, "parent_id": obs.parent_id,
                        "duration_seconds": time.monotonic() - started, **obs.fields})
            _parent.reset(token)
            if manager is not None and obs.sdk is not None:
                # Do not give SDK exception auto-capture access to unredacted messages.
                self.safe_sdk(lambda: manager.__exit__(None, None, None))


@contextmanager
def trace_run(run_dir, metadata, *, resume=False):
    """Auto uses SDK with complete credentials; otherwise existing account Broadcast."""
    mode = os.getenv("SWARM_CANVAS_TRACING", "auto").lower()
    if mode not in {"auto", "local", "broadcast", "langfuse"}:
        raise ValueError("SWARM_CANVAS_TRACING must be auto, local, broadcast or langfuse")
    host = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")
    ready = all([os.getenv("LANGFUSE_PUBLIC_KEY"), os.getenv("LANGFUSE_SECRET_KEY"), host])
    if mode == "auto":
        mode = "langfuse" if ready else "broadcast"
    if mode == "langfuse" and not ready:
        raise ValueError("Langfuse requires LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL")
    client = None
    attributes = nullcontext()
    if mode == "langfuse":
        # Load only after environment configuration; never pass configs/keys as span input.
        from langfuse import Langfuse, propagate_attributes
        client = Langfuse(base_url=host, environment="development", sample_rate=1.0)
        attributes = propagate_attributes(session_id=run_dir.name, tags=["swarm-canvas", "free-only", str(metadata["condition"])])
    recorder = Recorder(run_dir / "traces.jsonl", run_dir.name, mode, client, resume=resume)
    token = _current.set(recorder)
    try:
        with attributes, recorder.observation("run-canvas", input={k: metadata[k] for k in ("condition", "seed", "rounds")}, metadata=metadata) as root:
            yield recorder, root
    finally:
        if client is not None:
            recorder.safe_sdk(client.flush)
        recorder.write({"event": "export_summary", "mode": mode, "export_errors": recorder.export_errors,
                        "delivery_verified": False})
        _current.reset(token)
        recorder.file.close()


@contextmanager
def observation(name, kind="span", **fields):
    recorder = _current.get()
    if recorder is None:
        yield Observation(None, name, kind, fields)
    else:
        with recorder.observation(name, kind, **fields) as obs:
            yield obs


def broadcast_context(generation):
    recorder = _current.get()
    if recorder is None or recorder.mode != "broadcast":
        return {}
    # Broadcast owns generation export in this mode. SDK export is disabled to avoid duplicates.
    return {"session_id": recorder.run_id, "trace": {
        "trace_id": recorder.trace_id, "trace_name": "run-canvas",
        "generation_name": "generate-painter-action",
        "local_observation_id": generation.id, "run_id": recorder.run_id,
        "environment": "development", "model_policy": "openrouter_free_only",
    }}


def register_secret(secret):
    recorder = _current.get()
    if recorder and secret:
        with recorder.lock:
            recorder.secrets.add(secret)


def record_event(event):
    if _current.get() is None:
        return
    kind = "tool" if event.get("type") in {"message", "ack", "paint", "request", "grant"} else "span"
    with observation("apply-" + str(event.get("type", "event")), kind, input=event, metadata={k: event[k] for k in ("round", "agent_id") if k in event}) as obs:
        obs.update(output=event)
