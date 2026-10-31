"""Optional factual interface information, independent of task assistance."""
from __future__ import annotations

import json

COLOR_NAMES = {'S': 'light blue', 'W': 'dark blue', 'Y': 'yellow', 'B': 'brown',
               'w': 'off-white', 'P': 'pink', 'G': 'light green', 'K': 'black',
               'O': 'orange', 'R': 'red', 'Gy': 'gray', 'L': 'pale blue'}


def configure(cfg):
    raw = cfg.get('interface_feedback') or {}
    if not isinstance(raw, dict) or set(raw) - {'color_legend', 'action_results'}:
        raise ValueError('invalid interface feedback settings')
    if any(not isinstance(value, bool) for value in raw.values()):
        raise ValueError('interface feedback switches must be boolean')
    return {key: raw.get(key, False) for key in ('color_legend', 'action_results')}


def previous_results(events_path, round_num):
    if round_num < 2:
        return {}
    by_agent = {}
    for line in events_path.read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        if event.get('round') != round_num - 1 or not event.get('agent_id'):
            continue
        kind = event.get('type')
        if kind not in {'paint', 'invalid', 'over_budget', 'grant', 'deny'}:
            continue
        if kind == 'paint' and not event.get('applied'):
            continue
        item = {key: event[key] for key in ('type', 'cell', 'color', 'reason', 'delivers') if key in event}
        by_agent.setdefault(event['agent_id'], []).append(item)
    return by_agent


def instructions(settings, palette, catalog, results, round_num):
    lines = []
    if settings['color_legend']:
        codes = dict.fromkeys([*palette, *catalog])
        lines.append('COLOR LEGEND: ' + ', '.join(f'{code} = {COLOR_NAMES.get(code, "unknown")}' for code in codes))
    if settings['action_results']:
        if round_num == 1:
            lines.append('YOUR PREVIOUS-ROUND ACTION RESULTS: none (first round).')
        else:
            lines.append('YOUR PREVIOUS-ROUND ACTION RESULTS (applied paints and request decisions; '
                         'later painters may have changed a cell): ' + json.dumps(results, separators=(',', ':')))
    return '\n'.join(lines)
