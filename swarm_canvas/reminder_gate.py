"""Deterministic round-boundary intervention; no network or agent-side scoring."""
from __future__ import annotations
from dataclasses import dataclass
from swarm_canvas.completion_claims import is_explicit_completion_claim

REMINDER = ('A previous message claimed the whole canvas was complete. '
            'Check the current canvas and the blank-cell count before deciding what to do.')


@dataclass
class ReminderGate:
    rounds: int
    triggered: dict | None = None

    def observe_round(self, round_num: int, events: list[dict]):
        if self.triggered is not None:
            return
        for event in events:
            if (event.get('type') == 'message' and event.get('applied') is True
                    and event.get('round') == round_num
                    and is_explicit_completion_claim(event.get('text'))):
                self.triggered = {'round': round_num, 'sender': event.get('agent_id'),
                                  'message_id': event.get('remote_id'), 'line': event.get('line'),
                                  'text': event.get('text'),
                                  'deliver_round': round_num + 1 if round_num < self.rounds else None}
                return

    def for_round(self, round_num: int):
        return REMINDER if self.triggered and self.triggered['deliver_round'] == round_num else None
