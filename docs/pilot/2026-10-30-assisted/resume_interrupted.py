import os,getpass,json
from pathlib import Path
os.environ['OPENROUTER_API_KEY']=getpass.getpass('OpenRouter API key: ')
import httpx
from swarm_canvas.larger_pilot import verify_readiness,preflight,source_hashes
from swarm_canvas.readiness_check import run
from swarm_canvas.request_budget import model_request_budget
root=Path('runs/larger_pilot_f7185a1dda584c34a27e85c7f0078971').resolve()
original=json.loads((root/'pilot.json').read_text())
if original['status']!='interrupted' or original['inference_attempts_upper_bound']!=98: raise RuntimeError('unexpected original status')
if source_hashes()!=original['source_sha256']: raise RuntimeError('source differs from original pilot')
verify_readiness()
cap=original['max_inference_attempts']-original['inference_attempts_upper_bound']
with httpx.Client(timeout=20) as client: quota=preflight(client,os.environ.get('OPENROUTER_API_KEY'),cap)
path=root/'resume.json'
if path.exists(): raise RuntimeError('resume manifest already exists')
plan={'status':'running','purpose':'resume_after_environment_interruption','original_attempts_upper_bound':98,'max_additional_attempts':cap,'preflight':quota,'seeds':[8,9],'runs':[]}
def save(): path.write_text(json.dumps(plan,indent=2)+'\n')
save()
with model_request_budget(interval_seconds=3.5,max_requests=cap) as budget:
 try:
  for seed in (8,9):
   if source_hashes()!=original['source_sha256']:raise RuntimeError('source changed')
   result,summary=run(seed=seed,rounds=12,output_root=root,assist=True,shared_budget=budget)
   plan['runs'].append({'run_dir':str(result.run_dir),'summary':summary});save()
   if not summary['passed'] or not summary['task_scores']['model_metadata_complete'] or summary['task_scores']['observed_models']!=[original['model']]:raise RuntimeError('readiness or model gate failed')
  plan['status']='completed'
 except Exception as exc:
  plan.update(status='failed',error_type=type(exc).__name__);raise
 finally:
  plan['additional_attempts']=budget.requests;save()
print('RESUMED',path)
