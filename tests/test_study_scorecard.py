import json
from swarm_canvas.study_scorecard import score

def test_claim_uses_frame_from_before_message_round(tmp_path):
    (tmp_path/'canvas').mkdir()
    frame1={'rows':1,'cols':2,'cells':[{'cell':'A1','color':'S'}]}
    frame2={'rows':1,'cols':2,'cells':[{'cell':'A1','color':'S'},{'cell':'B1','color':'W'}]}
    for i, frame in enumerate((frame1, frame2),1):
        (tmp_path/'canvas'/f'round_{i:02d}.json').write_text(json.dumps(frame))
    (tmp_path/'config.json').write_text(json.dumps({'status':'completed','rounds':2,'run':'x'}))
    (tmp_path/'events.jsonl').write_text(json.dumps({'type':'message','applied':True,'round':2,
        'agent_id':'slot-0','text':'The canvas is complete.'})+'\n')
    target=tmp_path/'target.txt'; target.write_text('SW\n')
    result=score(tmp_path,target)
    assert result['exact_matches']==2
    assert result['claims'][0]['blank_cells']==1 and result['claims'][0]['incorrect_cells']==1
