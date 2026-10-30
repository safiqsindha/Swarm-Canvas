import os, json, tempfile
from pathlib import Path
if not os.environ.get('OPENROUTER_API_KEY'):
 raise RuntimeError('Set OPENROUTER_API_KEY in the environment')
from swarm_canvas.models import ModelConfig,call_model
from swarm_canvas.agents import parse_model_json
from swarm_canvas.comms import SwarmChatComms
from swarm_canvas.request_budget import model_request_budget
from uuid import uuid4
p=Path('runs')/('coordination_paint_gate_'+uuid4().hex); p.mkdir(parents=True)
cfg=ModelConfig(provider='openrouter',name='nvidia/nemotron-3.5-super-vl:free',temperature=0,max_tokens=400,reasoning_enabled=False,output_kind='painter')
agents=['slot-0','slot-1']; expected={'slot-0':'A-L','slot-1':'M-X'}; records=[]
try:
 with tempfile.TemporaryDirectory() as d:
  chat=SwarmChatComms(agent_ids=agents,data_dir=Path(d))
  try:
   with model_request_budget(interval_seconds=3.5,max_requests=8):
    for rnd in (1,2):
     chat.begin_round(rnd)
     views={a:chat.inbox(a,rnd) for a in agents}
     for a in agents:
      peer=agents[1] if a==agents[0] else agents[0]
      lines=[{'number':x.number,'sender':x.agent,'text':x.text} for x in views[a] if x.agent==peer]
      prompt=f'You are {a}. Your assigned columns are {expected[a]}. Your partner is {peer}. '
      if rnd==1: prompt+='Return JSON with a messages array containing one short message claiming your assigned columns, and no other fields.'
      else: prompt+=f'Here are actual messages from your partner: {json.dumps(lines)}. Return JSON with messages containing one short message confirming your assigned columns and acks containing the integer line number of your partner message. Do not invent line numbers.'
      prompt += ' Also include a paints array with exactly one object: column '+('A' if a == 'slot-0' else 'M')+', row 1, color S. Return both the communication and paint fields.'
      raw=call_model([{'role':'system','content':'Follow the instructions. Output only a JSON object.'},{'role':'user','content':prompt}],cfg)
      data=parse_model_json(raw) or {}
      posts=[]; acknowledgments=[]
      for message in data.get('messages',[])[:1]:
       if isinstance(message,str): posts.append(chat.post(a,message,rnd))
      for line in data.get('acks',[])[:1]:
       if isinstance(line,int): acknowledgments.append(chat.ack(a,line,rnd))
      records.append({'round':rnd,'agent':a,'input':prompt,'response':raw,'peer_lines':lines,'post_ids':posts,'ack_ids':acknowledgments})
  finally: chat.close()
 (p/'gate.json').write_text(json.dumps({'records':records,'calls':cfg.call_records},indent=2)+'\n')
 print('RESULT',p)
except Exception as e:
 (p/'gate.json').write_text(json.dumps({'records':records,'calls':cfg.call_records,'error_type':type(e).__name__},indent=2)+'\n')
 print('FAILED',p,type(e).__name__)
