"""Paired study intervention and round-boundary audit, independent of transport."""
from __future__ import annotations
import json
import threading
from pathlib import Path
from experiments.retained_notes_probe import ProbeAgent
from swarm_canvas.reminder_gate import ReminderGate

_lock = threading.Lock()

class StudyAgent(ProbeAgent):
    def __init__(self, *args, gate: ReminderGate | None, audit_path: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate, self.audit_path = gate, Path(audit_path)

    def act(self, observation):
        round_num = self.turn + 1
        message = self.gate.for_round(round_num) if self.gate else None
        if message:
            observation += '\n\n' + message
            with _lock, self.audit_path.open('a', encoding='utf-8') as out:
                out.write(json.dumps({'type':'reminder_delivery', 'round':round_num,
                    'agent_index':self.index, 'text':message})+'\n')
                out.flush()
        return super().act(observation)


def finish_round(gate: ReminderGate, run_dir: Path, round_num: int, audit_path: Path):
    """Call once after the runner has flushed the round's native-message events."""
    before = gate.triggered
    events = [json.loads(line) for line in (Path(run_dir)/'events.jsonl').read_text().splitlines() if line.strip()]
    gate.observe_round(round_num, events)
    if before is None and gate.triggered is not None:
        with _lock, Path(audit_path).open('a', encoding='utf-8') as out:
            out.write(json.dumps({'type':'reminder_trigger', **gate.triggered})+'\n')
            out.flush()
