"""python cli.py run configs/c1_nochat.yaml --seed 1"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from swarm_canvas.judge import judge_run
from swarm_canvas.models import ModelConfig
from swarm_canvas.pilot import run_pilot
from swarm_canvas.runner import run_from_yaml
from swarm_canvas.score import load_run_target, score_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cli.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="play a condition from a YAML file")
    run_p.add_argument("config")
    run_p.add_argument("--seed", type=int)
    run_p.add_argument("--rounds", type=int)
    run_p.add_argument("--no-render", action="store_true")

    score_p = sub.add_parser("score", help="score an existing run directory")
    score_p.add_argument("run_dir")

    judge_p = sub.add_parser("judge", help="code play stages for an existing run")
    judge_p.add_argument("run_dir")
    judge_p.add_argument("--provider", default="heuristic")
    judge_p.add_argument("--model", default="")

    export_p = sub.add_parser("export", help="write a replay JSON for a finished run")
    export_p.add_argument("run_dir")
    export_p.add_argument("dest")

    pilot_p = sub.add_parser(
        "pilot", help="matched four-condition pilot; random smoke test unless --live"
    )
    pilot_p.add_argument("--output-dir", default="runs")
    pilot_p.add_argument("--live", action="store_true")
    pilot_p.add_argument("--model", default="")
    pilot_p.add_argument("--swarmchat-url", default="")
    pilot_p.add_argument("--token-file", default="")
    pilot_p.add_argument("--repeats", type=int, default=5)
    pilot_p.add_argument("--rounds", type=int, default=30)

    args = parser.parse_args(argv)
    if args.cmd == "pilot":
        print(
            run_pilot(
                output_root=Path(args.output_dir),
                live=args.live,
                model=args.model,
                swarmchat_url=args.swarmchat_url,
                token_file=args.token_file,
                repeats=args.repeats,
                rounds=args.rounds,
            )
        )
        return 0
    if args.cmd == "run":
        result = run_from_yaml(
            args.config,
            seed=args.seed,
            rounds=args.rounds,
            render=not args.no_render,
        )
        print(result.run_dir)
        return 0
    if args.cmd == "score":
        print(json.dumps(score_run(args.run_dir), indent=2))
        return 0
    if args.cmd == "judge":
        cfg = None
        if args.provider != "heuristic":
            cfg = ModelConfig(
                provider=args.provider, name=args.model, output_kind="judge"
            )
        print(json.dumps(judge_run(args.run_dir, cfg), indent=2))
        return 0
    if args.cmd == "export":
        _export(Path(args.run_dir), Path(args.dest))
        print(args.dest)
        return 0
    return 1


def _export(run_dir: Path, dest: Path) -> None:
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    frames = []
    for number in range(1, int(config["rounds"]) + 1):
        path = run_dir / "canvas" / f"round_{number:02d}.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        round_num = int(path.stem.split("_")[1])
        frames.append({"round": round_num, "cells": snapshot["cells"]})
    events = []
    for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            event = json.loads(line)
            if event.get("type") in {
                "paint",
                "message",
                "ack",
                "grant",
                "deny",
                "rename",
                "invalid",
                "over_budget",
            }:
                events.append(
                    {
                        "round": event.get("round"),
                        "type": event.get("type"),
                        "agent": event.get("agent"),
                        "cell": event.get("cell"),
                        "color": event.get("color"),
                        "applied": event.get("applied"),
                        "overwrote": event.get("overwrote"),
                        "text": event.get("text"),
                        "reason": event.get("reason"),
                    }
                )
    payload = {
        "run": config.get("run"),
        "seed": config.get("seed"),
        "condition": config.get("condition"),
        "rounds": config.get("rounds"),
        "final_hash": config.get("final_hash"),
        "target": load_run_target(run_dir, config),
        "frames": frames,
        "events": events,
        "scores": {
            "coverage": scores.get("coverage"),
            "target_accuracy": scores.get("target_accuracy"),
            "painted": scores.get("painted"),
            "overwrites": scores.get("overwrites"),
            "target_matches": scores.get("target_matches"),
        },
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
