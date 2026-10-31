"""Round loop. One seed drives every shuffle. Invalid actions are logged and dropped."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

import yaml

from swarm_canvas.agents import LLMAgent, RandomAgent
from swarm_canvas.boundary_state import save_boundary
from swarm_canvas.assistance import configure as configure_assistance, instructions as assistance_instructions
from swarm_canvas.comms import DocLog, NoComms, SwarmChatComms
from swarm_canvas.engine import Canvas
from swarm_canvas.models import ModelConfig, validate_model_policy
from swarm_canvas.paths import ROOT
from swarm_canvas.prompts_render import prompt_hashes, render_system, render_turn
from swarm_canvas.render import write_canvas_files
from swarm_canvas.score import load_plate, score_run
from swarm_canvas.supplier import Supplier
from swarm_canvas.validate import Prepared, validate_action
from swarm_canvas.tracing import observation, trace_run, record_event


@dataclass
class Slot:
    index: int
    handle: str
    agent: object
    palette: list[str]
    scratchpad: str = ""
    model_cfg: ModelConfig | None = None

    @property
    def agent_id(self) -> str:
        return f"slot-{self.index}"


@dataclass
class RunResult:
    run_dir: Path
    run_id: str
    final_hash: str
    scores: dict = field(default_factory=dict)


def load_config(path: str | Path) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config is not a mapping: {path}")
    return raw


def run_from_yaml(
    path: str | Path,
    *,
    seed: int | None = None,
    rounds: int | None = None,
    output_root: Path | None = None,
    render: bool = True,
    agents: list | None = None,
) -> RunResult:
    cfg = load_config(path)
    if seed is not None:
        cfg["seed"] = seed
    if rounds is not None:
        cfg["rounds"] = rounds
    if output_root is not None:
        cfg["output_dir"] = str(output_root)
    return run_config(cfg, render=render, agents=agents)


def run_config(
    cfg: dict,
    *,
    render: bool = True,
    agents: list | None = None,
    on_round: Callable[[dict], None] | None = None,
) -> RunResult:
    """Allocate an isolated attempt; keep a failed manifest if execution aborts."""
    _validate_config(cfg, agents)
    run_code = str(cfg.get("run_code") or cfg["condition"])
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_code):
        raise ValueError(
            "run_code must contain only letters, digits, underscores or hyphens"
        )
    output_root = Path(cfg.get("output_dir") or ROOT / "runs")
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / f"{run_code}_s{int(cfg['seed'])}_{uuid4().hex}"
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = run_dir / "config.json"
    manifest.write_text(json.dumps({"run": run_dir.name, "status": "running"}) + "\n")
    try:
        with ExitStack() as resources:
            recorder, root = resources.enter_context(trace_run(run_dir, {
                "condition": cfg["condition"], "seed": int(cfg["seed"]),
                "rounds": int(cfg["rounds"]), "prompt_hashes": prompt_hashes(),
                "git_commit": _git_commit(), "task": _task(cfg)[0],
                "model_policy": "openrouter_free_only",
            }))
            result = _run_config(
                cfg,
                run_dir=run_dir,
                render=render,
                agents=agents,
                resources=resources,
                on_round=on_round,
            )
            root.update(output={"final_hash": result.final_hash, "scores": result.scores})
            (run_dir / "tracing.json").write_text(json.dumps({
                "mode": recorder.mode, "trace_id": recorder.trace_id,
                "session_id": result.run_id, "audit_file": "traces.jsonl",
                "delivery_verified": False,
            }, indent=2) + "\n")
            return result
    except Exception as exc:
        saved = json.loads(manifest.read_text())
        saved.update(status="failed", error_type=type(exc).__name__)
        manifest.write_text(json.dumps(saved, indent=2) + "\n")
        raise


def _validate_config(cfg: dict, agents: list | None) -> None:
    if int(cfg["rounds"]) < 1 or int(cfg.get("paint_budget_per_round", 8)) < 1:
        raise ValueError("rounds and paint budget must be positive")
    if cfg.get("grid", {"cols": 24, "rows": 16}) != {"cols": 24, "rows": 16}:
        raise ValueError("This version supports only the 24 by 16 grid")
    handles = cfg["agents"]["handles"]
    if not handles or len(set(handles)) != len(handles):
        raise ValueError("starting handles must be nonempty and unique")
    if int(cfg["agents"].get("count", len(handles))) != len(handles):
        raise ValueError("agents.count must match handles")
    if agents is not None and len(agents) != len(handles):
        raise ValueError("supplied agents must match handles")
    if cfg["agents"].get("type", "random") not in {"random", "llm"}:
        raise ValueError("agents.type must be random or llm")
    kind = cfg.get("comms", {}).get("kind", "none")
    if kind not in {"none", "doc_log", "swarmchat"}:
        raise ValueError("unknown communication kind")
    live = (
        cfg["agents"].get("type") == "llm"
        and agents is None
        and cfg.get("model", {}).get("provider") != "fake"
    ) or any(
        getattr(a, "model_cfg", None) and a.model_cfg.provider != "fake"
        for a in agents or []
    )
    if live:
        validate_model_policy(_model_config(cfg.get("model") or {}))
    for agent in agents or []:
        if getattr(agent, "model_cfg", None):
            validate_model_policy(agent.model_cfg)
    if kind == "swarmchat":
        comms_cfg = cfg.get("comms", {})
        backend = comms_cfg.get(
            "backend", "remote" if comms_cfg.get("server_url") else "local"
        )
        if backend not in {"local", "remote"}:
            raise ValueError("SwarmChat backend must be local or remote")
        if backend == "local" and comms_cfg.get("server_url"):
            raise ValueError("Local SwarmChat cannot use a remote server_url")
        if backend == "remote":
            if not comms_cfg.get("server_url"):
                raise ValueError("Remote SwarmChat requires comms.server_url")
            tokens = _read_tokens(comms_cfg.get("token_file"))
            for index, handle in enumerate(handles):
                token = tokens.get(f"slot-{index}", tokens.get(handle))
                if not token or token == "replace-me":
                    raise ValueError(
                        "Remote SwarmChat requires real tokens for every slot"
                    )
    _task(cfg)  # validate objective before allocating or calling models
    assistance, _ = configure_assistance(cfg)
    if assistance['assigned_territories'] and len(handles) > 24:
        raise ValueError('assigned territories require at most one agent per column')


def _task(cfg: dict) -> tuple[dict, list[str] | None]:
    task = dict(cfg.get("task") or {"mode": "free_creation"})
    mode = task.get("mode", "free_creation")
    if mode not in {"reconstruction", "free_creation"}:
        raise ValueError("task.mode must be reconstruction or free_creation")
    if mode == "free_creation":
        task['mode'] = mode
        goal = task.get("goal")
        if goal is not None and (not isinstance(goal, str) or not goal.strip() or len(goal) > 500):
            raise ValueError("free creation goal must be a nonempty string of at most 500 characters")
        if not isinstance(task.get("open_coordination", False), bool):
            raise ValueError("open_coordination must be a boolean")
        return task, None
    path = Path(task.get("target", "targets/sun_boat.txt"))
    if not path.is_absolute():
        path = ROOT / path
    plate = load_plate(path)
    if len(plate) != 16 or any(len(row) != 24 for row in plate):
        raise ValueError("target must be 24 columns by 16 rows")
    available = set(cfg["palette"]) | set(cfg.get("supplier", {}).get("catalog", []))
    if set("".join(plate)) - available:
        raise ValueError("target contains colors unavailable to painters")
    task["mode"] = mode
    task["sha256"] = hashlib.sha256(
        json.dumps(plate, separators=(",", ":")).encode()
    ).hexdigest()
    return task, plate


def _run_config(
    cfg: dict,
    *,
    run_dir: Path,
    resources: ExitStack,
    on_round: Callable[[dict], None] | None = None,
    render: bool = True,
    agents: list | None = None,
) -> RunResult:
    seed = int(cfg["seed"])
    rounds = int(cfg["rounds"])
    cols = int(cfg.get("grid", {}).get("cols", 24))
    rows = int(cfg.get("grid", {}).get("rows", 16))
    condition = str(cfg["condition"])
    run_id = run_dir.name
    task, plate = _task(cfg)
    assistance, assistance_target = configure_assistance(cfg)
    if assistance['assigned_territories'] and len(cfg['agents']['handles']) > cols:
        raise ValueError('assigned territories require at most one agent per column')
    if assistance_target is not None:
        (run_dir / 'assistance_reference.json').write_text(json.dumps(assistance_target) + '\n')
    if plate is not None:
        (run_dir / "target.json").write_text(json.dumps(plate) + "\n", encoding="utf-8")
    budget = int(cfg.get("paint_budget_per_round", 8))
    base_palette = [str(color) for color in cfg["palette"]]
    handles = [str(handle) for handle in cfg["agents"]["handles"]]
    kind = str(cfg.get("comms", {}).get("kind", "none"))
    comms_cfg = cfg.get("comms", {})
    comms_enabled = kind in {"doc_log", "swarmchat"}
    supplier_cfg = cfg.get("supplier", {})
    canvas_dir = run_dir / "canvas"
    scratch_dir = run_dir / "scratchpads"
    prompt_dir = run_dir / "prompts_rendered"
    canvas_dir.mkdir(exist_ok=True)
    scratch_dir.mkdir(exist_ok=True)
    prompt_dir.mkdir(exist_ok=True)

    log_path = run_dir / ("doc_log.txt" if comms_enabled else "unused_log.txt")
    comms = _build_comms(
        kind, comms_cfg, log_path if comms_enabled else None, run_dir, handles
    )
    if kind == "swarmchat":
        resources.callback(comms.close)
        (run_dir / "swarmchat.json").write_text(
            json.dumps(comms.metadata(), indent=2) + "\n"
        )
    if comms_enabled and log_path is not None:
        log_path.write_text(comms.render(), encoding="utf-8")
    supplier = Supplier(
        [str(color) for color in supplier_cfg.get("catalog", [])],
        swarm_budget=int(supplier_cfg.get("swarm_budget", 4)),
    )
    canvas = Canvas(cols=cols, rows=rows)
    model_cfg = _model_config(cfg.get("model") or {})
    slots = _build_slots(
        handles,
        cfg["agents"].get("type", "random"),
        seed,
        budget,
        base_palette,
        model_cfg,
        condition,
        kind,
        agents,
    )
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "run": run_id,
                "status": "running",
                "schema_version": 2,
                "seed": seed,
                "condition": condition,
                "rounds": rounds,
                "task": task,
                "model": _public_model(model_cfg),
                "comms": kind,
                "assistance": assistance,
            },
            indent=2,
        )
        + "\n"
    )
    uses_live_models = any(
        slot.model_cfg is not None and slot.model_cfg.provider != "fake"
        for slot in slots
    )
    rng = random.Random(seed)
    events_path = run_dir / "events.jsonl"
    pngs: list[Path] = []
    for slot in slots:
        if hasattr(slot.agent, "system_prompt"):
            slot.agent.system_prompt = render_system(
                slot.handle,
                " ".join(base_palette),
                condition,
                kind,
                agent_count=len(slots),
                paint_budget=budget,
                task_mode=task.get("mode", "free_creation"),
                agent_id=slot.agent_id,
                goal=task.get("goal"),
                open_coordination=task.get("open_coordination", False),
            )
    _write_system_prompts(
        prompt_dir,
        slots,
        base_palette,
        condition,
        kind,
        budget,
        task.get("mode", "free_creation"),
        task.get("goal"),
        task.get("open_coordination", False),
    )
    call_offsets = {slot.index: 0 for slot in slots}
    with events_path.open("w", encoding="utf-8") as events:
        for round_num in range(1, rounds + 1):
            with observation("process-round", metadata={"round": round_num}):
                _deliver(supplier, slots, round_num)
                observations = _observe(
                    slots,
                    comms,
                    canvas,
                    round_num,
                    rounds,
                    cols,
                    rows,
                    supplier,
                    run_id,
                    events,
                    comms_enabled,
                    prompt_dir,
                    plate if plate is not None else (assistance_target if assistance['reference_image'] else None),
                    budget,
                    assistance,
                    assistance_target,
                )
                actions = _act(
                    slots, observations, concurrent=cfg["agents"].get("type") == "llm"
                )
                _log_calls(slots, call_offsets, run_id, round_num, events)
                prepared = [
                    _prepare(
                        slot,
                        actions.get(slot.index),
                        round_num,
                        budget,
                        comms_enabled,
                        comms_cfg,
                        slots,
                    )
                    for slot in slots
                ]
                for slot, prep in zip(slots, prepared):
                    peer_lines = set(getattr(comms, 'native_read', {}).get(slot.agent_id, []))
                    violations = []
                    if assistance['require_messages'] and not prep.messages:
                        violations.append('required_message_missing')
                    if assistance['require_peer_acks'] and peer_lines and not (set(prep.acks) & peer_lines):
                        violations.append('required_peer_ack_missing')
                    for reason in violations:
                        _write(events, {'type': 'assistance_violation', 'reason': reason, 'run': run_id,
                                        'round': round_num, 'agent_id': slot.agent_id, 'applied': False})
                _resolve_renames(slots, prepared)
                _log_rejections(prepared, slots, run_id, round_num, events)
                if cfg.get("abort_on_model_failure", False) and any(
                    prep.parse_error or prep.failure_type for prep in prepared
                ):
                    raise RuntimeError(
                        "Model failure in round; development attempt aborted before further requests"
                    )
                comm_order = list(slots)
                rng.shuffle(comm_order)
                _communicate(
                    comm_order, prepared, comms, run_id, round_num, events, comms_enabled
                )
                _apply_renames(slots, prepared)
                _request_colors(comm_order, prepared, supplier, run_id, round_num, events)
                paint_order = list(slots)
                rng.shuffle(paint_order)
                _paint(canvas, paint_order, prepared, run_id, round_num, events)
                _scratch(slots, prepared, scratch_dir, round_num)
                if render:
                    pngs.append(
                        write_canvas_files(canvas, canvas_dir, f"round_{round_num:02d}")
                    )
                else:
                    snapshot = canvas.snapshot()
                    (canvas_dir / f"round_{round_num:02d}.json").write_text(
                        json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
                    )

                frame = canvas_dir / f"round_{round_num:02d}.json"
                checkpoint = json.loads((run_dir / 'config.json').read_text())
                checkpoint['last_completed_round'] = round_num
                checkpoint['checkpoint_frame'] = str(frame.relative_to(run_dir))
                checkpoint['checkpoint_sha256'] = hashlib.sha256(frame.read_bytes()).hexdigest()
                checkpoint['boundary_state'], checkpoint['boundary_sha256'] = save_boundary(
                    run_dir, round_num, canvas, slots, supplier, rng, comms, events)
                temporary = run_dir / 'config.json.tmp'
                temporary.write_text(json.dumps(checkpoint, indent=2) + '\n')
                os.replace(temporary, run_dir / 'config.json')

                if on_round is not None:
                    on_round(
                        {
                            "run": run_id,
                            "round": round_num,
                            "rounds": rounds,
                            "painted": len(canvas.cells),
                            "token_totals": _token_totals(slots),
                        }
                    )

    if render and pngs:
        from swarm_canvas.render import to_gif

        to_gif(pngs, run_dir / "timelapse.gif", fps=4)
    final_hash = hashlib.sha256(
        json.dumps(canvas.snapshot(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    config_out = {
        "run": run_id,
        "status": "completed",
        "schema_version": 2,
        "final_frame": f"canvas/round_{rounds:02d}.json",
        "task": task,
        "agents": [
            {
                "agent_id": slot.agent_id,
                "handle": slot.handle,
                "effective_model": _public_model(slot.model_cfg)
                if slot.model_cfg
                else None,
            }
            for slot in slots
        ],
        "paint_budget_per_agent": budget,
        "team_paint_budget_per_round": budget * len(slots),
        "agent_type": cfg["agents"].get("type", "random"),
        "uses_live_models": uses_live_models,
        "abort_on_model_failure": bool(cfg.get("abort_on_model_failure", False)),
        "condition": condition,
        "seed": seed,
        "rounds": rounds,
        "grid": {"cols": cols, "rows": rows},
        "model": {
            "provider": model_cfg.provider,
            "name": model_cfg.name,
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
            "reasoning_max_tokens": model_cfg.reasoning_max_tokens,
            "reasoning_enabled": model_cfg.reasoning_enabled,
            "output_kind": model_cfg.output_kind,
            "require_coordination_fields": model_cfg.require_coordination_fields,
            "paint_budget": budget,
            "policy": "openrouter_free_only",
        },
        "prompt_hashes": prompt_hashes(),
        "git_commit": _git_commit(),
        "token_totals": _token_totals(slots),
        "final_hash": final_hash,
        "comms": kind,
        "comms_settings": {
            k: comms_cfg[k]
            for k in (
                "messages_per_round",
                "max_chars",
                "inbox_context_lines",
                "acks_enabled",
            )
            if k in comms_cfg
        },
        "swarmchat_transport": comms.metadata()["transport"]
        if kind == "swarmchat"
        else None,
        "swarmchat": comms.metadata() if kind == "swarmchat" else None,
        "swarmchat_errors": len(getattr(comms, "remote_errors", [])),
        "assistance": assistance,
        "supplier": supplier_cfg,
    }
    (run_dir / "config.json").write_text(
        json.dumps(config_out, indent=2) + "\n", encoding="utf-8"
    )
    scores = score_run(run_dir)
    return RunResult(
        run_dir=run_dir, run_id=run_id, final_hash=final_hash, scores=scores
    )


def _build_comms(
    kind: str, comms_cfg: dict, log_path: Path | None, run_dir: Path, handles: list[str]
):
    shared = dict(
        messages_per_round=int(comms_cfg.get("messages_per_round", 2)),
        max_chars=int(comms_cfg.get("max_chars", 200)),
        inbox_context_lines=int(comms_cfg.get("inbox_context_lines", 20)),
        path=log_path,
    )
    if kind == "doc_log":
        return DocLog(**shared)
    if kind == "swarmchat":
        tokens = _read_tokens(comms_cfg.get("token_file"))
        mapped = {
            f"slot-{i}": tokens.get(f"slot-{i}", tokens.get(handle, ""))
            for i, handle in enumerate(handles)
        }
        return SwarmChatComms(
            agent_ids=list(mapped),
            server_url=str(comms_cfg.get("server_url") or ""),
            tokens=mapped,
            data_dir=run_dir / "swarmchat",
            channel_name=f"canvas-{run_dir.name[-32:]}",
            **shared,
        )
    return NoComms()


def _read_tokens(token_file) -> dict[str, str]:
    if not token_file:
        return {}
    path = Path(token_file)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if not str(key).startswith("#")
    }


def _model_config(model: dict) -> ModelConfig:
    responses = model.get("fake_responses")
    return ModelConfig(
        provider=str(model.get("provider") or "fake"),
        name=str(model.get("name") or ""),
        temperature=float(model.get("temperature", 0.7)),
        max_tokens=int(model.get("max_tokens", 600)),
        base_url=model.get("base_url"),
        api_key=model.get("api_key"),
        api_key_env=model.get("api_key_env"),
        reasoning_max_tokens=model.get("reasoning_max_tokens"),
        reasoning_enabled=model.get("reasoning_enabled"),
        require_coordination_fields=model.get("require_coordination_fields", False),
        output_kind=model.get("output_kind", "painter"),
        fake_responses=list(responses) if responses else None,
    )


def _build_slots(
    handles, agent_type, seed, budget, base_palette, model_cfg, condition, kind, agents
) -> list[Slot]:
    slots: list[Slot] = []
    for index, handle in enumerate(handles):
        if agents is not None:
            agent = agents[index]
            agent.handle = handle
        elif agent_type == "llm":
            palette_text = " ".join(base_palette)
            system = render_system(handle, palette_text, condition, kind)
            own_cfg = replace(
                model_cfg,
                paint_budget=budget,
                fake_responses=list(model_cfg.fake_responses)
                if model_cfg.fake_responses
                else None,
                usage={"calls": 0, "input_tokens": 0, "output_tokens": 0, "retries": 0},
                calls_log=[],
                call_records=[],
            )
            agent = LLMAgent(handle, own_cfg, system)
        else:
            agent = RandomAgent(handle, seed, index, paint_budget=budget)
            own_cfg = None
        slot = Slot(
            index=index,
            handle=handle,
            agent=agent,
            palette=list(base_palette),
            model_cfg=getattr(agent, "model_cfg", None),
        )
        slots.append(slot)
    return slots


def _deliver(supplier: Supplier, slots: list[Slot], round_num: int) -> None:
    by_id = {f"slot-{slot.index}": slot for slot in slots}
    for agent_id, colors in supplier.deliveries(round_num).items():
        slot = by_id[agent_id]
        for color in colors:
            if color not in slot.palette:
                slot.palette.append(color)


def _write_system_prompts(
    prompt_dir: Path,
    slots,
    base_palette,
    condition: str,
    kind: str,
    budget: int,
    task_mode: str,
    goal: str | None = None,
    open_coordination: bool = False,
) -> None:
    palette_text = " ".join(base_palette)
    for slot in slots:
        text = render_system(
            slot.handle,
            palette_text,
            condition,
            kind,
            agent_count=len(slots),
            paint_budget=budget,
            task_mode=task_mode,
            agent_id=slot.agent_id,
            goal=goal,
            open_coordination=open_coordination,
        )
        (prompt_dir / f"system_slot-{slot.index}.txt").write_text(
            text + "\n", encoding="utf-8"
        )


def _observe(
    slots,
    comms,
    canvas,
    round_num,
    rounds,
    cols,
    rows,
    supplier,
    run_id,
    events,
    comms_enabled,
    prompt_dir: Path,
    plate: list[str] | None,
    paint_budget: int,
    assistance: dict | None = None,
    assistance_target: list[str] | None = None,
):
    observations = {}
    if hasattr(comms, "begin_round"):
        comms.begin_round(round_num)
    canvas_text = canvas.to_text()
    remaining = max(0, supplier.swarm_budget - supplier.granted_total)
    for slot in slots:
        viewer = f"slot-{slot.index}"
        lines = comms.inbox(viewer, round_num)
        shown = [line.number for line in lines]
        native = list(getattr(comms, "native_read", {}).get(viewer, []))
        _write(
            events,
            {
                "run": run_id,
                "round": round_num,
                "agent": slot.handle,
                "agent_id": slot.agent_id,
                "type": "exposure",
                "lines": shown,
                "native_read": native,
                "native_messages": [
                    {
                        "line": line.number,
                        "remote_id": line.remote_id,
                        "read_by": line.read_by,
                    }
                    for line in lines
                    if line.remote_id
                ],
            },
        )
        formatted = [
            f"#{line.number} {line.agent}: {line.text}"
            + (
                f" [native read by: {', '.join(line.read_by) or 'nobody yet'}]"
                if line.read_by is not None
                else ""
            )
            for line in lines
        ]
        observations[slot.index] = render_turn(
            round_num=round_num,
            rounds=rounds,
            handle=slot.handle,
            agent_id=slot.agent_id,
            cols=cols,
            rows=rows,
            canvas=canvas_text,
            check=canvas.board_check(),
            palette=" ".join(slot.palette),
            budget=remaining,
            scratchpad=slot.scratchpad,
            inbox_lines=formatted,
            comms_enabled=comms_enabled,
            target=plate,
            paint_budget=paint_budget,
            catalog=" ".join(supplier.catalog),
        )
        if assistance:
            extra = assistance_instructions(assistance, assistance_target, canvas, slot.index,
                                            len(slots), slot.palette, paint_budget)
            if extra:
                observations[slot.index] += '\n\nOptional experimental assistance:\n' + extra
        (prompt_dir / f"round_{round_num:02d}_slot-{slot.index}.txt").write_text(
            observations[slot.index] + "\n", encoding="utf-8"
        )
    return observations


def _act(slots: list[Slot], observations: dict, concurrent: bool) -> dict:
    actions: dict[int, dict] = {}

    def call(slot: Slot):
        with observation("act-" + slot.agent_id, "agent", input=observations[slot.index],
                         metadata={"agent_id": slot.agent_id, "handle": slot.handle}) as turn:
            action = execute(slot)
            failed = any(action.get(k) for k in ("_api_error", "_agent_error", "_parse_error"))
            turn.update(output=action, level="ERROR" if failed else "DEFAULT")
            return action

    def execute(slot: Slot):
        agent = slot.agent
        if hasattr(agent, "palette"):
            agent.palette = list(slot.palette)
        agent.handle = slot.handle
        try:
            action = agent.act(observations[slot.index])
        except Exception as exc:
            return {"_agent_error": True, "_error_type": type(exc).__name__}
        if not isinstance(action, dict):
            return {"_parse_error": True, "_raw": str(action)[:500]}
        return action

    if concurrent and len(slots) > 1:
        with ThreadPoolExecutor(max_workers=len(slots)) as pool:
            futures = {slot.index: pool.submit(copy_context().run, call, slot) for slot in slots}
        for index, future in futures.items():
            actions[index] = future.result()
        return actions
    for slot in slots:
        actions[slot.index] = call(slot)
    return actions


def _prepare(
    slot, action, round_num, budget, comms_enabled, comms_cfg, slots
) -> Prepared:
    taken = {other.handle for other in slots if other.index != slot.index}
    max_messages = int(comms_cfg.get("messages_per_round", 2))
    max_chars = int(comms_cfg.get("max_chars", 200))
    return validate_action(
        handle=slot.handle,
        action=action,
        round_num=round_num,
        palette=slot.palette,
        paint_budget=budget,
        comms_enabled=comms_enabled,
        max_messages=max_messages,
        max_chars=max_chars,
        taken_handles=taken,
    )


def _log_rejections(prepared, slots, run_id, round_num, events) -> None:
    for slot, prep in zip(slots, prepared):
        if prep.failure_type:
            _write(
                events,
                {
                    "run": run_id,
                    "round": round_num,
                    "agent": slot.handle,
                    "agent_id": slot.agent_id,
                    "type": prep.failure_type,
                    **prep.failure_details,
                },
            )
        if prep.parse_error:
            event = {
                "run": run_id,
                "round": round_num,
                "agent": slot.handle,
                "agent_id": slot.agent_id,
                "type": "parse_error",
                "applied": False,
            }
            if prep.raw:
                event["raw"] = prep.raw
            _write(events, event)
        for item in prep.rejections:
            event = {
                "run": run_id,
                "round": round_num,
                "agent": slot.handle,
                "agent_id": slot.agent_id,
            }
            event.update(item)
            _write(events, event)
        if prep.passed:
            _write(
                events,
                {
                    "run": run_id,
                    "round": round_num,
                    "agent": slot.handle,
                    "agent_id": slot.agent_id,
                    "type": "pass",
                },
            )


def _communicate(
    order, prepared, comms, run_id, round_num, events, comms_enabled
) -> None:
    if not comms_enabled:
        return
    for slot in order:
        prep = prepared[slot.index]
        for text in prep.messages:
            number = comms.post(slot.agent_id, text, round_num)
            if number is None:
                _write(
                    events,
                    {
                        "run": run_id,
                        "round": round_num,
                        "agent": slot.handle,
                        "agent_id": slot.agent_id,
                        "type": "message",
                        "applied": False,
                        "reason": "cap",
                        "text": text[:80],
                    },
                )
            else:
                _write(
                    events,
                    {
                        "run": run_id,
                        "round": round_num,
                        "agent": slot.handle,
                        "agent_id": slot.agent_id,
                        "type": "message",
                        "applied": True,
                        "line": number,
                        "remote_id": next(
                            (
                                line.remote_id
                                for line in comms.lines
                                if line.number == number
                            ),
                            None,
                        ),
                        "text": text,
                    },
                )
        for line_no in dict.fromkeys(prep.acks):
            seen_lines = getattr(comms, "exposure", {}).get(slot.agent_id, [])
            number = (
                comms.ack(slot.agent_id, line_no, round_num)
                if line_no in seen_lines
                else 0
            )
            if not number:
                _write(
                    events,
                    {
                        "run": run_id,
                        "round": round_num,
                        "agent": slot.handle,
                        "agent_id": slot.agent_id,
                        "type": "ack",
                        "applied": False,
                        "reason": "missing_line",
                        "line": line_no,
                    },
                )
            else:
                _write(
                    events,
                    {
                        "run": run_id,
                        "round": round_num,
                        "agent": slot.handle,
                        "agent_id": slot.agent_id,
                        "type": "ack",
                        "applied": True,
                        "line": line_no,
                        "log_line": number,
                    },
                )


def _resolve_renames(slots, prepared) -> None:
    proposed = Counter(prep.rename_to for prep in prepared if prep.rename_to)
    for slot, prep in zip(slots, prepared):
        if prep.rename_to and proposed[prep.rename_to] > 1:
            name = prep.rename_to
            prep.rename_to = None
            prep.rejections = [
                e
                for e in prep.rejections
                if not (e.get("type") == "rename" and e.get("applied"))
            ]
            prep.rejections.append(
                {
                    "type": "rename",
                    "applied": False,
                    "reason": "simultaneous_name_collision",
                    "name": name,
                }
            )


def _log_calls(slots, offsets, run_id, round_num, events) -> None:
    for slot in slots:
        cfg = getattr(slot.agent, "model_cfg", None)
        if cfg is None:
            continue
        for record in cfg.call_records[offsets[slot.index] :]:
            _write(
                events,
                {
                    "type": "model_call",
                    "run": run_id,
                    "round": round_num,
                    "agent": slot.handle,
                    "agent_id": slot.agent_id,
                    **record,
                },
            )
        offsets[slot.index] = len(cfg.call_records)


def _apply_renames(slots, prepared) -> None:
    for slot, prep in zip(slots, prepared):
        if prep.rename_to:
            slot.handle = prep.rename_to
            slot.agent.handle = prep.rename_to


def _request_colors(order, prepared, supplier, run_id, round_num, events) -> None:
    for slot in order:
        prep = prepared[slot.index]
        for color in prep.requests:
            _write(
                events,
                {
                    "run": run_id,
                    "round": round_num,
                    "agent": slot.handle,
                    "agent_id": slot.agent_id,
                    "type": "request",
                    "color": color,
                },
            )
            decision = supplier.request(f"slot-{slot.index}", color, round_num)
            decision = dict(decision)
            decision["run"] = run_id
            decision["agent"] = slot.handle
            decision["agent_id"] = slot.agent_id
            decision["round"] = round_num
            _write(events, decision)


def _paint(canvas, order, prepared, run_id, round_num, events) -> None:
    paints = []
    for slot in order:
        for paint in prepared[slot.index].paints:
            paint.agent_id = slot.agent_id
            paint.agent = slot.handle
            paints.append(paint)
    paint_events = canvas.apply(paints, [slot.agent_id for slot in order])
    for event in paint_events:
        event["run"] = run_id
        event["round"] = round_num
        _write(events, event)


def _scratch(slots, prepared, scratch_dir: Path, round_num: int) -> None:
    current = {}
    for slot, prep in zip(slots, prepared):
        if prep.scratchpad is not None:
            slot.scratchpad = prep.scratchpad
            if hasattr(slot.agent, "scratchpad"):
                slot.agent.scratchpad = prep.scratchpad
        current[slot.agent_id] = {"handle": slot.handle, "scratchpad": slot.scratchpad}
        (scratch_dir / f"slot-{slot.index}.txt").write_text(
            slot.scratchpad, encoding="utf-8"
        )
    (scratch_dir / f"round_{round_num:02d}.json").write_text(
        json.dumps(current, indent=2) + "\n", encoding="utf-8"
    )


def _public_model(cfg: ModelConfig) -> dict:
    return {
        "provider": cfg.provider,
        "name": cfg.name,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "reasoning_max_tokens": cfg.reasoning_max_tokens,
        "reasoning_enabled": cfg.reasoning_enabled,
        "output_kind": cfg.output_kind,
        "paint_budget": cfg.paint_budget,
        "require_coordination_fields": cfg.require_coordination_fields,
    }


def _token_totals(slots: list[Slot]) -> dict:
    totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "retries": 0}
    seen = set()
    for slot in slots:
        cfg = getattr(slot.agent, "model_cfg", None)
        if cfg is None or id(cfg) in seen:
            continue
        seen.add(id(cfg))
        for key in totals:
            totals[key] += int(cfg.usage.get(key, 0))
    return totals


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _write(handle, event: dict) -> None:
    record_event(event)
    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    handle.flush()
