"""Metrics from a finished run. The scoring plate is read only here."""

from __future__ import annotations

import json
from pathlib import Path

from swarm_canvas.engine import cell_name
from swarm_canvas.paths import TARGETS


def load_plate(path: Path | None = None) -> list[str]:
    plate_path = path or (TARGETS / "sun_boat.txt")
    lines = [line.rstrip("\n") for line in plate_path.read_text(encoding="utf-8").splitlines()]
    if not lines:
        raise ValueError(f"empty plate: {plate_path}")
    width = len(lines[0])
    if any(len(line) != width for line in lines):
        raise ValueError(f"plate rows differ in width: {plate_path}")
    return lines


def score_run(run_dir: str | Path, plate_path: Path | None = None) -> dict:
    run_dir = Path(run_dir)
    plate = load_plate(plate_path)
    rows = len(plate)
    cols = len(plate[0])
    events = _read_events(run_dir / "events.jsonl")
    final = _final_snapshot(run_dir)
    painted = {(item["cell"]): item for item in final.get("cells", [])}
    matches = 0
    for row in range(rows):
        for col in range(cols):
            name = cell_name(col, row)
            expected = plate[row][col]
            got = painted.get(name)
            if got and got["color"] == expected:
                matches += 1
    total = rows * cols
    counts: dict[str, int] = {}
    per_agent: dict[str, dict] = {}

    def bucket(agent: str) -> dict:
        return per_agent.setdefault(
            agent, {"paints": 0, "messages": 0, "acks": 0, "requests": 0}
        )

    for event in events:
        kind = event.get("type")
        counts[kind] = counts.get(kind, 0) + 1
        agent = str(event.get("agent") or "")
        if kind == "paint" and event.get("applied"):
            bucket(agent)["paints"] += 1
        elif kind == "message" and event.get("applied"):
            bucket(agent)["messages"] += 1
        elif kind == "ack" and event.get("applied"):
            bucket(agent)["acks"] += 1
        elif kind == "request":
            bucket(agent)["requests"] += 1

    colors = sorted({item["color"] for item in painted.values()})
    scores = {
        "run": json.loads((run_dir / "config.json").read_text(encoding="utf-8")).get("run")
        if (run_dir / "config.json").is_file()
        else run_dir.name,
        "cells": total,
        "painted": len(painted),
        "coverage": round(len(painted) / total, 4) if total else 0,
        "target_matches": matches,
        "target_accuracy": round(matches / total, 4) if total else 0,
        "colors_used": colors,
        "overwrites": sum(1 for event in events if event.get("type") == "paint" and event.get("overwrote")),
        "invalid": counts.get("invalid", 0),
        "over_budget": counts.get("over_budget", 0),
        "messages": sum(1 for event in events if event.get("type") == "message" and event.get("applied")),
        "acks": sum(1 for event in events if event.get("type") == "ack" and event.get("applied")),
        "grants": counts.get("grant", 0),
        "denies": counts.get("deny", 0),
        "passes": counts.get("pass", 0),
        "parse_errors": counts.get("parse_error", 0),
        "per_agent": per_agent,
        "final_hash": json.loads((run_dir / "config.json").read_text(encoding="utf-8")).get("final_hash")
        if (run_dir / "config.json").is_file()
        else None,
    }
    (run_dir / "scores.json").write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    return scores


def _read_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _final_snapshot(run_dir: Path) -> dict:
    frames = sorted((run_dir / "canvas").glob("round_*.json"))
    if not frames:
        return {"cells": []}
    return json.loads(frames[-1].read_text(encoding="utf-8"))
