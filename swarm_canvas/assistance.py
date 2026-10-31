"""Explicit, independently switchable experimental scaffolds."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from swarm_canvas.paths import ROOT
from swarm_canvas.score import load_plate

FLAGS = ('reference_image', 'assigned_territories', 'suggested_paints', 'require_messages', 'require_peer_acks')


def configure(cfg):
    raw = cfg.get('assistance') or {}
    if not isinstance(raw, dict) or set(raw) - {*FLAGS, 'reference_path'}:
        raise ValueError('assistance has unknown or invalid settings')
    reconstruction = cfg.get('task', {}).get('mode') == 'reconstruction'
    if reconstruction and raw.get('reference_image') is False:
        raise ValueError('reconstruction mode always exposes its target')
    settings = {name: raw.get(name, reconstruction if name == 'reference_image' else False) for name in FLAGS}
    if any(not isinstance(value, bool) for value in settings.values()):
        raise ValueError('assistance switches must be boolean')
    if (settings['require_messages'] or settings['require_peer_acks']) and cfg.get('comms', {}).get('kind') != 'swarmchat':
        raise ValueError('communication requirements require SwarmChat')
    target = None
    if settings['reference_image'] or settings['suggested_paints']:
        path = Path(raw.get('reference_path', cfg.get('task', {}).get('target', 'targets/sun_boat.txt')))
        if not path.is_absolute():
            path = ROOT / path
        target = load_plate(path)
        if len(target) != 16 or any(len(row) != 24 for row in target):
            raise ValueError('assistance reference must be 24 by 16')
        available = set(cfg['palette']) | set(cfg.get('supplier', {}).get('catalog', []))
        if set(''.join(target)) - available:
            raise ValueError('assistance reference contains unavailable colors')
        settings['reference_sha256'] = hashlib.sha256(json.dumps(target, separators=(',', ':')).encode()).hexdigest()
    elif 'reference_path' in raw:
        raise ValueError('reference_path requires reference_image or suggested_paints')
    return settings, target


def instructions(settings, target, canvas, slot_index, agent_count, palette, paint_budget):
    notes = []
    cols = canvas.cols
    start, end = slot_index * cols // agent_count, (slot_index + 1) * cols // agent_count
    if settings['assigned_territories']:
        notes.append(f'Your assigned territory is columns {chr(65 + start)} through {chr(64 + end)}; paint only there.')
    if settings['suggested_paints']:
        suggestions = []
        for row in range(canvas.rows):
            for col in range(start if settings['assigned_territories'] else 0, end if settings['assigned_territories'] else cols):
                color = target[row][col]
                current = canvas.cells.get((col, row))
                if color in palette and (current is None or current.color != color):
                    suggestions.append({'column': chr(65 + col), 'row': row + 1, 'color': color})
                    if len(suggestions) == paint_budget:
                        break
            if len(suggestions) == paint_budget:
                break
        notes.append('Suggested target-derived paints: ' + json.dumps(suggestions))
    if settings['require_messages']:
        notes.append('Include at least one nonempty message every turn.')
    if settings['require_peer_acks']:
        notes.append('When peer messages are visible, acknowledge at least one peer message by its actual line number.')
    return '\n'.join(notes)
