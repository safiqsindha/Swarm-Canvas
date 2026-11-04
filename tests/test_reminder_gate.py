from swarm_canvas.reminder_gate import REMINDER, ReminderGate

def test_only_applied_whole_canvas_claim_delivers_next_round_once():
    gate = ReminderGate(rounds=24)
    gate.observe_round(1, [{'type':'message','round':1,'applied':False,'text':'The canvas is complete.'}])
    assert gate.triggered is None
    event = {'type':'message','round':2,'applied':True,'agent_id':'slot-1','remote_id':'m',
             'line':3,'text':'The canvas is complete.'}
    gate.observe_round(2, [event])
    assert gate.for_round(2) is None and gate.for_round(3) == REMINDER
    gate.observe_round(3, [{**event,'round':3}])
    assert gate.triggered['round'] == 2 and gate.for_round(4) is None

def test_final_round_claim_cannot_be_delivered():
    gate = ReminderGate(rounds=24)
    gate.observe_round(24, [{'type':'message','round':24,'applied':True,'text':'The canvas is complete.'}])
    assert gate.triggered and gate.triggered['deliver_round'] is None

def test_condition_uses_flushed_messages_and_logs_delivery(tmp_path, monkeypatch):
    import json
    from experiments.study_condition import StudyAgent, finish_round
    from experiments.retained_notes_probe import ProbeAgent
    from swarm_canvas.models import ModelConfig
    gate = ReminderGate(rounds=3)
    event = {'type':'message','round':1,'applied':True,'agent_id':'slot-0',
             'text':'The canvas is complete.','remote_id':'r1','line':1}
    (tmp_path/'events.jsonl').write_text(json.dumps(event)+'\n')
    audit=tmp_path/'reminder.jsonl'
    finish_round(gate,tmp_path,1,audit)
    captured=[]
    def fake_act(self, observation):
        captured.append(observation); self.turn += 1; return {}
    monkeypatch.setattr(ProbeAgent,'act',fake_act)
    agent=StudyAgent('a',ModelConfig(provider='fake'), 'preview_once', 0, '', gate=gate,audit_path=audit)
    agent.turn=1
    agent.act('base')
    agent.act('base')
    assert captured == ['base\n\n'+REMINDER, 'base']
    records=[json.loads(line) for line in audit.read_text().splitlines()]
    assert [r['type'] for r in records] == ['reminder_trigger','reminder_delivery']
