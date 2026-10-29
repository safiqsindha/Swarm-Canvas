"""Round loop. One seed drives every shuffle. Invalid actions are logged and dropped."""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from swarm_canvas.agents import LLMAgent, RandomAgent
from swarm_canvas.comms import DocLog, NoComms, SwarmChatComms
from swarm_canvas.engine import Canvas
from swarm_canvas.models import ModelConfig
from swarm_canvas.paths import ROOT
from swarm_canvas.prompts_render import prompt_hashes, render_system, render_turn
from swarm_canvas.render import write_canvas_files
from swarm_canvas.score import score_run
from swarm_canvas.supplier import Supplier
from swarm_canvas.validate import Prepared, validate_action


@dataclass
class Slot:
    index: int
    handle: str
    agent: object
    palette: list[str]
    scratchpad: str = ""
    model_cfg: ModelConfig | None = None


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


def run_config(cfg: dict, *, render: bool = True, agents: list | None = None) -> RunResult:
    seed = int(cfg["seed"])
    rounds = int(cfg["rounds"])
    cols = int(cfg.get("grid", {}).get("cols", 24))
    rows = int(cfg.get("grid", {}).get("rows", 16))
    condition = str(cfg["condition"])
    run_code = str(cfg.get("run_code") or condition)
    run_id = f"{run_code}_s{seed}"
    budget = int(cfg.get("paint_budget_per_round", 8))
    base_palette = [str(color) for color in cfg["palette"]]
    handles = [str(handle) for handle in cfg["agents"]["handles"]]
    kind = str(cfg.get("comms", {}).get("kind", "none"))
    comms_cfg = cfg.get("comms", {})
    comms_enabled = kind in {"doc_log", "swarmchat"}
    supplier_cfg = cfg.get("supplier", {})
    output_root = Path(cfg.get("output_dir") or ROOT / "runs")
    if not output_root.is_absolute():
        output_root = ROOT / output_root
    run_dir = output_root / run_id
    if output_root != ROOT / "runs" and Path(cfg.get("output_dir", "")).is_absolute():
        run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    canvas_dir = run_dir / "canvas"
    scratch_dir = run_dir / "scratchpads"
    prompt_dir = run_dir / "prompts_rendered"
    canvas_dir.mkdir(exist_ok=True)
    scratch_dir.mkdir(exist_ok=True)
    prompt_dir.mkdir(exist_ok=True)

    log_path = run_dir / ("doc_log.txt" if comms_enabled else "unused_log.txt")
    comms = _build_comms(kind, comms_cfg, log_path if comms_enabled else None)
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
    rng = random.Random(seed)
    events_path = run_dir / "events.jsonl"
    pngs: list[Path] = []
    _write_system_prompts(prompt_dir, slots, base_palette, condition, kind)
    with events_path.open("w", encoding="utf-8") as events:
        for round_num in range(1, rounds + 1):
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
            )
            actions = _act(slots, observations, concurrent=cfg["agents"].get("type") == "llm")
            prepared = [
                _prepare(slot, actions.get(slot.index), round_num, budget, comms_enabled, comms_cfg, slots)
                for slot in slots
            ]
            _log_rejections(prepared, slots, run_id, round_num, events)
            comm_order = list(slots)
            rng.shuffle(comm_order)
            _communicate(comm_order, prepared, comms, run_id, round_num, events, comms_enabled)
            _apply_renames(slots, prepared)
            _request_colors(comm_order, prepared, supplier, run_id, round_num, events)
            paint_order = list(slots)
            rng.shuffle(paint_order)
            _paint(canvas, paint_order, prepared, run_id, round_num, events)
            _scratch(slots, prepared, scratch_dir, round_num)
            if render:
                pngs.append(write_canvas_files(canvas, canvas_dir, f"round_{round_num:02d}"))
            else:
                snapshot = canvas.snapshot()
                (canvas_dir / f"round_{round_num:02d}.json").write_text(
                    json.dumps(snapshot, indent=2) + "\n", encoding="utf-8"
                )

    if render and pngs:
        from swarm_canvas.render import to_gif

        to_gif(pngs, run_dir / "timelapse.gif", fps=4)
    final_hash = hashlib.sha256(
        json.dumps(canvas.snapshot(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    config_out = {
        "run": run_id,
        "condition": condition,
        "seed": seed,
        "rounds": rounds,
        "grid": {"cols": cols, "rows": rows},
        "model": {
            "provider": model_cfg.provider,
            "name": model_cfg.name,
            "temperature": model_cfg.temperature,
            "max_tokens": model_cfg.max_tokens,
        },
        "prompt_hashes": prompt_hashes(),
        "git_commit": _git_commit(),
        "token_totals": _token_totals(slots),
        "final_hash": final_hash,
        "comms": kind,
    }
    (run_dir / "config.json").write_text(json.dumps(config_out, indent=2) + "\n", encoding="utf-8")
    scores = score_run(run_dir)
    return RunResult(run_dir=run_dir, run_id=run_id, final_hash=final_hash, scores=scores)


def _build_comms(kind: str, comms_cfg: dict, log_path: Path | None):
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
        return SwarmChatComms(
            server_url=str(comms_cfg.get("server_url") or ""),
            tokens=tokens,
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
    return {str(key): str(value) for key, value in data.items() if not str(key).startswith("#")}


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
            own_cfg = ModelConfig(
                provider=model_cfg.provider,
                name=model_cfg.name,
                temperature=model_cfg.temperature,
                max_tokens=model_cfg.max_tokens,
                base_url=model_cfg.base_url,
                api_key=model_cfg.api_key,
                api_key_env=model_cfg.api_key_env,
                fake_responses=list(model_cfg.fake_responses) if model_cfg.fake_responses else None,
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


def _write_system_prompts(prompt_dir: Path, slots, base_palette, condition: str, kind: str) -> None:
    palette_text = " ".join(base_palette)
    for slot in slots:
        text = render_system(slot.handle, palette_text, condition, kind)
        (prompt_dir / f"system_slot-{slot.index}.txt").write_text(text + "\n", encoding="utf-8")


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
):
    observations = {}
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
                "type": "exposure",
                "lines": shown,
                "native_read": native,
            },
        )
        formatted = [f"#{line.number} {line.agent}: {line.text}" for line in lines]
        observations[slot.index] = render_turn(
            round_num=round_num,
            rounds=rounds,
            handle=slot.handle,
            cols=cols,
            rows=rows,
            canvas=canvas_text,
            check=canvas.board_check(),
            palette=" ".join(slot.palette),
            budget=remaining,
            scratchpad=slot.scratchpad,
            inbox_lines=formatted,
            comms_enabled=comms_enabled,
        )
        (prompt_dir / f"round_{round_num:02d}_slot-{slot.index}.txt").write_text(
            observations[slot.index] + "\n", encoding="utf-8"
        )
    return observations


def _act(slots: list[Slot], observations: dict, concurrent: bool) -> dict:
    actions: dict[int, dict] = {}

    def call(slot: Slot):
        agent = slot.agent
        if hasattr(agent, "palette"):
            agent.palette = list(slot.palette)
        agent.handle = slot.handle
        try:
            action = agent.act(observations[slot.index])
        except Exception as exc:
            return {"_parse_error": True, "_raw": str(exc)[:500]}
        if not isinstance(action, dict):
            return {"_parse_error": True, "_raw": str(action)[:500]}
        return action

    if concurrent and len(slots) > 1:
        with ThreadPoolExecutor(max_workers=len(slots)) as pool:
            futures = {slot.index: pool.submit(call, slot) for slot in slots}
        for index, future in futures.items():
            actions[index] = future.result()
        return actions
    for slot in slots:
        actions[slot.index] = call(slot)
    return actions


def _prepare(slot, action, round_num, budget, comms_enabled, comms_cfg, slots) -> Prepared:
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
        if prep.parse_error:
            _write(
                events,
                {
                    "run": run_id,
                    "round": round_num,
                    "agent": slot.handle,
                    "type": "parse_error",
                    "applied": False,
                },
            )
        for item in prep.rejections:
            event = {"run": run_id, "round": round_num, "agent": slot.handle}
            event.update(item)
            _write(events, event)
        if prep.passed:
            _write(
                events,
                {"run": run_id, "round": round_num, "agent": slot.handle, "type": "pass"},
            )


def _communicate(order, prepared, comms, run_id, round_num, events, comms_enabled) -> None:
    if not comms_enabled:
        return
    for slot in order:
        prep = prepared[slot.index]
        for text in prep.messages:
            number = comms.post(slot.handle, text, round_num)
            if number is None:
                _write(
                    events,
                    {
                        "run": run_id,
                        "round": round_num,
                        "agent": slot.handle,
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
                        "type": "message",
                        "applied": True,
                        "line": number,
                        "text": text,
                    },
                )
        for line_no in prep.acks:
            number = comms.ack(slot.handle, line_no, round_num)
            if not number:
                _write(
                    events,
                    {
                        "run": run_id,
                        "round": round_num,
                        "agent": slot.handle,
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
                        "type": "ack",
                        "applied": True,
                        "line": line_no,
                        "log_line": number,
                    },
                )


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
                    "type": "request",
                    "color": color,
                },
            )
            decision = supplier.request(f"slot-{slot.index}", color, round_num)
            decision = dict(decision)
            decision["run"] = run_id
            decision["agent"] = slot.handle
            decision["round"] = round_num
            _write(events, decision)


def _paint(canvas, order, prepared, run_id, round_num, events) -> None:
    paints = []
    for slot in order:
        paints.extend(prepared[slot.index].paints)
    paint_events = canvas.apply(paints, [slot.handle for slot in order])
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
        current[slot.handle] = slot.scratchpad
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in slot.handle) or "painter"
        (scratch_dir / f"slot-{slot.index}.txt").write_text(slot.scratchpad, encoding="utf-8")
        (scratch_dir / f"{safe}.txt").write_text(slot.scratchpad, encoding="utf-8")
    (scratch_dir / f"round_{round_num:02d}.json").write_text(
        json.dumps(current, indent=2) + "\n", encoding="utf-8"
    )


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
    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
