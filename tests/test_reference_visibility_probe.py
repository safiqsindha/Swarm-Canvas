from experiments.reference_visibility_probe import ProbeAgent
from swarm_canvas.agents import LLMAgent


def test_leader_alone_receives_reference_and_cannot_paint(monkeypatch):
    seen = []
    def pretend(self, prompt):
        seen.append(prompt)
        return {'paints': [{'cell': 'A1', 'color': 'S'}], 'requests': ['O'], 'messages': ['go']}
    monkeypatch.setattr(LLMAgent, 'act', pretend)
    leader = ProbeAgent('lead', None, 'leader_visible', 0, 'PRIVATE GRID')
    follower = ProbeAgent('other', None, 'leader_visible', 1, 'PRIVATE GRID')
    result = leader.act('board')
    follower.act('board')
    assert 'PRIVATE GRID' in seen[0] and 'PRIVATE GRID' not in seen[1]
    assert 'paints' not in result and 'requests' not in result and result['messages'] == ['go']
    assert leader.suppressed[0]['removed']['paints'][0]['cell'] == 'A1'


def test_preview_is_only_directly_available_before_painting(monkeypatch):
    seen = []
    monkeypatch.setattr(LLMAgent, 'act', lambda self, prompt: seen.append(prompt) or {})
    painter = ProbeAgent('painter', None, 'preview_once', 0, 'PRIVATE GRID')
    painter.preview_notes = 'my own sketch'
    painter.act('board one')
    painter.act('board two')
    assert 'my own sketch' in seen[0] and 'my own sketch' not in seen[1]
    assert all('PRIVATE GRID' not in prompt for prompt in seen)
