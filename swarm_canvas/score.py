"""Objective-aligned metrics from immutable completed runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from swarm_canvas.engine import cell_name
from swarm_canvas.paths import TARGETS


def load_plate(path: Path | None = None) -> list[str]:
    plate_path = path or (TARGETS / "sun_boat.txt")
    lines = plate_path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0] or any(len(line) != len(lines[0]) for line in lines):
        raise ValueError(f"target must be a nonempty rectangle: {plate_path}")
    return lines


def load_run_target(run_dir: Path, config: dict) -> list[str] | None:
    if config.get("task", {}).get("mode") == "free_creation":
        return None
    path = run_dir / "target.json"
    if path.is_file():
        plate = json.loads(path.read_text())
        digest = hashlib.sha256(
            json.dumps(plate, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != config.get("task", {}).get("sha256"):
            raise ValueError("run target hash mismatch")
        return plate
    if config.get("schema_version", 1) >= 2:
        raise ValueError("reconstruction run is missing its saved target")
    return load_plate()  # legacy runs only


def score_run(run_dir: str | Path, plate_path: Path | None = None) -> dict:
    run_dir = Path(run_dir)
    config = json.loads((run_dir / "config.json").read_text())
    if config.get("status", "completed") != "completed":
        raise ValueError("Only completed runs may be scored")
    if plate_path is not None and config.get("schema_version", 1) >= 2:
        raise ValueError(
            "New runs must use their saved target, not a scoring-time override"
        )
    plate = load_plate(plate_path) if plate_path else load_run_target(run_dir, config)
    final = _final_snapshot(run_dir)
    rows, cols = final["rows"], final["cols"]
    total = rows * cols
    expected = (
        {cell_name(c, r): plate[r][c] for r in range(rows) for c in range(cols)}
        if plate
        else {}
    )
    painted = {item["cell"]: item for item in final.get("cells", [])}
    matches = (
        sum(item["color"] == expected.get(cell) for cell, item in painted.items())
        if plate
        else None
    )
    events = _read_events(run_dir / "events.jsonl")
    counts: dict[str, int] = {}
    per_agent: dict[str, dict] = {}
    replay: dict[str, str] = {}
    destroyed = redundant = paint_count = 0
    input_tokens = output_tokens = 0
    reached = None
    accuracy_by_round = []
    by_round: dict[int, list[dict]] = {}
    for event in events:
        by_round.setdefault(int(event.get("round", 0)), []).append(event)
        kind = event.get("type")
        counts[kind] = counts.get(kind, 0) + 1
        identity = str(event.get("agent_id") or event.get("agent") or "")
        metric = {
            "paint": "paints",
            "message": "messages",
            "ack": "acks",
            "request": "requests",
        }.get(kind)
        if metric and (kind == "request" or event.get("applied")):
            bucket = per_agent.setdefault(
                identity, {"paints": 0, "messages": 0, "acks": 0, "requests": 0}
            )
            bucket[metric] += 1
    for number in range(1, int(config["rounds"]) + 1):
        for event in by_round.get(number, []):
            if event.get("type") == "model_call" and event.get("status") == "ok":
                input_tokens += int(event.get("input_tokens", 0))
                output_tokens += int(event.get("output_tokens", 0))
            if event.get("type") != "paint" or not event.get("applied"):
                continue
            cell, color = event["cell"], event["color"]
            previous = replay.get(cell)
            redundant += previous == color
            if plate and previous == expected[cell] and color != expected[cell]:
                destroyed += 1
            replay[cell] = color
            paint_count += 1
        if plate:
            accuracy = (
                sum(color == expected[cell] for cell, color in replay.items()) / total
            )
            accuracy_by_round.append({"round": number, "accuracy": round(accuracy, 6)})
            if reached is None and accuracy >= 0.9:
                reached = {
                    "round": number,
                    "paints": paint_count,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
    calls = [e for e in events if e.get("type") == "model_call"]
    successful = [e for e in calls if e.get("status") == "ok"]
    costs = [e.get("cost_usd") for e in successful]
    live = config.get("uses_live_models", config.get("agent_type") == "llm")
    scores = {
        "run": config.get("run", run_dir.name),
        "task_mode": config.get("task", {}).get("mode", "legacy"),
        "cells": total,
        "painted": len(painted),
        "coverage": round(len(painted) / total, 4),
        "target_matches": matches,
        "target_accuracy": round(matches / total, 4) if matches is not None else None,
        "colors_used": sorted({item["color"] for item in painted.values()}),
        "overwrites": sum(
            bool(e.get("overwrote")) for e in events if e.get("type") == "paint"
        ),
        "correct_cells_destroyed": destroyed if plate else None,
        "redundant_paints": redundant,
        "accuracy_by_round": accuracy_by_round,
        "threshold_90": reached,
        "paints": paint_count,
        "invalid": counts.get("invalid", 0),
        "over_budget": counts.get("over_budget", 0),
        "messages": sum(
            e.get("type") == "message" and bool(e.get("applied")) for e in events
        ),
        "acks": sum(e.get("type") == "ack" and bool(e.get("applied")) for e in events),
        "grants": counts.get("grant", 0),
        "denies": counts.get("deny", 0),
        "passes": counts.get("pass", 0),
        "parse_errors": counts.get("parse_error", 0),
        "api_errors": counts.get("api_error", 0),
        "agent_errors": counts.get("agent_error", 0),
        "token_totals": config.get("token_totals", {}),
        "observed_models": sorted(
            {e["served_model"] for e in successful if e.get("served_model")}
        ),
        "model_metadata_complete": not live
        or (bool(successful) and all(e.get("served_model") for e in successful)),
        "cost_usd": sum(costs)
        if costs and all(isinstance(c, (int, float)) for c in costs)
        else (0 if not live else None),
        "per_agent": per_agent,
        "final_hash": config.get("final_hash"),
        "reliability_ok": not any(
            counts.get(k, 0) for k in ("api_error", "agent_error", "parse_error")
        ),
    }
    (run_dir / "scores.json").write_text(json.dumps(scores, indent=2) + "\n")
    return scores


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _final_snapshot(run_dir: Path) -> dict:
    config = json.loads((run_dir / "config.json").read_text())
    if config.get("schema_version", 1) >= 2:
        frame = run_dir / config["final_frame"]
        if (
            frame.resolve()
            != (
                run_dir / "canvas" / f"round_{int(config['rounds']):02d}.json"
            ).resolve()
        ):
            raise ValueError("manifest final frame does not match configured rounds")
    else:
        frames = list((run_dir / "canvas").glob("round_*.json"))
        if not frames:
            raise ValueError("no canvas frames")
        frame = max(frames, key=lambda p: int(p.stem.split("_")[1]))
    snapshot = json.loads(frame.read_text())
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if config.get("final_hash") and digest != config["final_hash"]:
        raise ValueError("final frame hash mismatch")
    return snapshot
