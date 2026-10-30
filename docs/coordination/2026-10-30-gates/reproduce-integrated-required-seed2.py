import os,json
if not os.environ.get('OPENROUTER_API_KEY'):
 raise RuntimeError('Set OPENROUTER_API_KEY in the environment')
from swarm_canvas.coordination_check import CoordinationAgent
from swarm_canvas.runner import load_config,run_config,_model_config
from swarm_canvas.paths import ROOT
from swarm_canvas.request_budget import model_request_budget
import swarm_canvas.models as models
models._PAINTER_SCHEMA['required']=['messages','paints','acks']
class Agent(CoordinationAgent):
 def act(self,obs):
  from swarm_canvas.agents import LLMAgent
  note='Read the canvas and target and paint within your assigned columns. Your permanent slot column assignments are: slot-0 A-F, slot-1 G-L, slot-2 M-R, slot-3 S-X. Every turn output messages as an array containing one short string stating your assignment and intended work. When peer messages are visible, include acks as an array of their real line numbers. Return paints, messages and acks together in the JSON action object. Never invent line numbers.'
  action=LLMAgent.act(self,obs+'\n\n'+note);self.actions.append(action);return action
cfg=load_config(ROOT/'configs/free_smoke_nemotron.yaml');cfg.update(rounds=2,seed=2,run_code='integrated_required_seed2',abort_on_model_failure=True)
agents=[Agent(h,_model_config(cfg['model']),'') for h in cfg['agents']['handles']]
try:
 with model_request_budget(interval_seconds=3.5,max_requests=24) as budget:
  result=run_config(cfg,render=False,agents=agents,on_round=lambda x: print('ROUND',x['round'],flush=True))
 (result.run_dir/'gate_actions.json').write_text(json.dumps({f'slot-{i}':a.actions for i,a in enumerate(agents)},indent=2)+'\n')
 print('RESULT',result.run_dir,'requests',budget.requests,flush=True)
except Exception as e:
 print('FAILED',type(e).__name__,flush=True)
