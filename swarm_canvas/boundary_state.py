"""Serializable end-of-round evidence. It is not an instruction to replay a round."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def save_boundary(run_dir, round_num, canvas, slots, supplier, rng, comms, events):
    """Capture runtime state without model API keys, SwarmChat tokens or provider headers."""
    events.flush()
    agents = []
    for slot in slots:
        item = {'agent_id': slot.agent_id, 'handle': slot.handle, 'palette': list(slot.palette),
                'scratchpad': slot.scratchpad}
        agent_rng = getattr(slot.agent, 'rng', None)
        if agent_rng is not None:
            item['random_state'] = agent_rng.getstate()
        model_cfg = getattr(slot.agent, 'model_cfg', None)
        if model_cfg is not None:
            item['model_usage'] = dict(model_cfg.usage)
        agents.append(item)
    held = {agent: sorted(colors) for agent, colors in supplier.held.items()}
    pending = {str(round_id): groups for round_id, groups in supplier._arriving.items()}
    chat = {'transport': 'none'}
    if getattr(comms, 'local', False) and hasattr(comms, 'checkpoint_state'):
        chat = comms.checkpoint_state()
    elif hasattr(comms, 'metadata'):
        chat = {'metadata': comms.metadata(),
                'watermarks': dict(getattr(comms, '_watermark', {})),
                'message_rounds': dict(getattr(comms, '_rounds', {})),
                'counts': [{'agent_id': a, 'round': r, 'count': n}
                           for (a, r), n in getattr(comms, '_counts', {}).items()]}
    frame = canvas.snapshot()
    offset = events.tell()
    event_hash = hashlib.sha256((Path(run_dir) / 'events.jsonl').read_bytes()[:offset]).hexdigest()
    from swarm_canvas.request_budget import budget_checkpoint
    data = {'schema_version': 1, 'round': round_num, 'canvas': frame,
            'budget': budget_checkpoint(),
            'events_offset': offset, 'events_sha256': event_hash, 'rng_state': rng.getstate(),
            'agents': agents, 'supplier': {'catalog': supplier.catalog,
              'swarm_budget': supplier.swarm_budget, 'granted_total': supplier.granted_total,
              'held': held, 'arriving': pending}, 'swarmchat': chat,
            'continuation_supported': False}
    path = Path(run_dir) / f'boundary_{round_num:02d}.json'
    tmp = path.with_suffix('.json.tmp')
    # Scratchpads and message metadata may be sensitive, so restrict local permissions.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(data, out, separators=(',', ':'))
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    return path.name, hashlib.sha256(path.read_bytes()).hexdigest()


def validate_boundary(run_dir, config):
    base = Path(run_dir).resolve()
    name = config.get('boundary_state')
    if not name or Path(name).name != name:
        return False
    path = (base / name).resolve()
    if path.parent != base or not path.is_file():
        return False
    if hashlib.sha256(path.read_bytes()).hexdigest() != config.get('boundary_sha256'):
        return False
    try:
        state = json.loads(path.read_text())
        frame = json.loads((base / config['checkpoint_frame']).read_text())
        event_bytes = (base / 'events.jsonl').read_bytes()
        offset = state['events_offset']
        return (state['schema_version'] == 1 and state['round'] == config['last_completed_round']
                and state['canvas'] == frame and isinstance(offset, int) and 0 <= offset <= len(event_bytes)
                and hashlib.sha256(event_bytes[:offset]).hexdigest() == state['events_sha256'])
    except (KeyError, TypeError, ValueError, OSError):
        return False


def restore_core(run_dir):
    """Restore canvas, scheduler RNG and supplier from a verified boundary.

    This is deliberately not a run-resume API: native channel and agent clients,
    partial-round side effects, provider requests and the global budget are not restored.
    """
    import random
    from swarm_canvas.engine import Canvas, CellState, parse_cell
    from swarm_canvas.supplier import Supplier

    base = Path(run_dir).resolve()
    config = json.loads((base / 'config.json').read_text())
    if not validate_boundary(base, config):
        raise ValueError('boundary integrity validation failed')
    state = json.loads((base / config['boundary_state']).read_text())
    snapshot = state['canvas']
    canvas = Canvas(cols=snapshot['cols'], rows=snapshot['rows'])
    for item in snapshot['cells']:
        pos = parse_cell(item['cell'], canvas.cols, canvas.rows)
        if pos is None or pos in canvas.cells:
            raise ValueError('invalid or duplicate canvas cell in boundary')
        canvas.cells[pos] = CellState(color=item['color'], handle=item.get('handle'), agent_id=item.get('agent_id'))
    if canvas.snapshot() != snapshot:
        raise ValueError('canvas restore is not identical')
    def as_tuple(value):
        return tuple(as_tuple(item) for item in value) if isinstance(value, list) else value
    rng = random.Random()
    rng.setstate(as_tuple(state['rng_state']))
    supplier_data = state['supplier']
    supplier = Supplier(supplier_data['catalog'], swarm_budget=supplier_data['swarm_budget'])
    supplier.granted_total = supplier_data['granted_total']
    supplier.held = {agent: set(colors) for agent, colors in supplier_data['held'].items()}
    supplier._arriving = {int(number): groups for number, groups in supplier_data['arriving'].items()}
    return {'round': state['round'], 'canvas': canvas, 'rng': rng, 'supplier': supplier,
            'agents': state['agents'], 'swarmchat_metadata': state['swarmchat'],
            'continuation_supported': False}
