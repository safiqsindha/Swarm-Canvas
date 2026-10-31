"""Real process interruption retains a verifiable checkpoint and does not resume."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from swarm_canvas.attempt_audit import inspect_attempt
from swarm_canvas.paths import ROOT


@pytest.mark.skipif(os.name != 'posix', reason='requires process groups and SIGKILL')
def test_hard_kill_preserves_last_completed_round(tmp_path):
    marker = tmp_path / 'checkpoint-ready'
    output = tmp_path / 'runs'
    code = '''
import os, signal, sys
from pathlib import Path
from swarm_canvas.runner import load_config, run_config
from swarm_canvas.paths import ROOT
cfg = load_config(ROOT / "configs/c2b_swarmchat.yaml")
cfg.update(rounds=3, output_dir=sys.argv[1])
class Painter:
    def __init__(self): self.handle = ''
    def act(self, observation): return {'messages': ['hello from ' + self.handle]}
agents = [Painter() for _ in range(4)]
def pause(progress):
    if progress['round'] == 2:
        Path(sys.argv[2]).write_text(progress["run"])
        os.kill(os.getpid(), signal.SIGSTOP)
run_config(cfg, render=False, agents=agents, on_round=pause)
'''
    process = subprocess.Popen([sys.executable, '-c', code, str(output), str(marker)],
                               cwd=ROOT, start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 45
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        assert marker.exists(), 'run did not reach round-two checkpoint'
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        path = output / marker.read_text()
        audit = inspect_attempt(path)
        assert audit['status'] == 'running'  # stale status must not imply process is alive
        assert audit['last_completed_round'] == 2 and audit['checkpoint_valid']
        assert audit['boundary_valid']
        cfg = json.loads((path / 'config.json').read_text())
        boundary = json.loads((path / cfg['boundary_state']).read_text())
        assert len(boundary['agents']) == 4 and boundary['round'] == 2
        assert boundary['swarmchat']['metadata']['transport'] == 'native_local'
        assert 'token' not in (path / cfg['boundary_state']).read_text().lower()
        from swarm_canvas.swarmchat_native import SwarmChatComms
        restored = SwarmChatComms(agent_ids=[f'slot-{i}' for i in range(4)],
                                  data_dir=path / 'swarmchat', recovery_state=boundary['swarmchat'])
        try:
            assert restored.channel_id == boundary['swarmchat']['metadata']['channel_id']
            shown = restored.inbox('slot-0', 3)
            assert len(shown) == 8
            assert any(line.agent == 'slot-0' and line.read_by for line in shown)
        finally:
            restored.close()
        (path / cfg['boundary_state']).write_text('{}')
        assert inspect_attempt(path)['boundary_valid'] is False
        assert len(list((path / 'canvas').glob('round_*.json'))) == 2
        assert json.loads((path / 'config.json').read_text())['run'] == path.name
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)
