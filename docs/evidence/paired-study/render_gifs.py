"""Render the six retained paired-study runs (requires Pillow).

Usage: python docs/evidence/paired-study/render_gifs.py /path/to/batch
The batch directory contains manifest.json and the retained run directories.
"""
import json
import re
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(sys.argv[1])
OUT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / 'manifest.json').read_text())
runs = {}
for attempt in manifest['attempts']:
    if attempt['status'] != 'completed':
        continue
    run = Path(attempt['result']['run_dir'])
    local = ROOT / run.parent.name / run.name
    assert local.is_dir(), local
    runs[(attempt['arm'], attempt['seed'])] = local
assert len(runs) == 6
colors = {'S':(126,200,227),'W':(18,72,140),'Y':(244,208,63),'B':(122,78,40),'w':(246,244,238),'P':(255,45,149),'G':(126,217,87),'K':(18,18,18),'O':(232,122,36),'R':(196,40,48),'Gy':(138,138,138),'L':(166,214,236)}
blank=(232,228,218)
fontpath='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
boldpath='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
def font(size,bold=False): return ImageFont.truetype(boldpath if bold else fontpath,size)
def snapshot(run, n):
    data=json.loads((run/'canvas'/f'round_{n:02}.json').read_text())
    assert (data['cols'],data['rows'])==(24,16)
    canvas=Image.new('RGB',(24,16),blank)
    for item in data['cells']:
        m=re.fullmatch(r'([A-X])(\d+)',item['cell']); assert m
        canvas.putpixel((ord(m[1])-65,int(m[2])-1),colors[item['color']])
    return canvas,384-len(data['cells'])
def place(im, canvas, x, y, scale):
    im.paste(canvas.resize((24*scale,16*scale),Image.Resampling.NEAREST),(x,y))
def save(frames,durations,path):
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=durations,loop=0,optimize=True,disposal=2)
    with Image.open(path) as check:
        assert check.n_frames==len(frames), (path,check.n_frames,len(frames))
    print(path, path.stat().st_size, 'bytes',len(frames),'frames')

# Claim was sent in round 12; the decision used the end-of-round-11 snapshot.
frames=[]; durations=[]
for n in range(1,25):
    canvas, blanks=snapshot(runs['baseline',13],n)
    im=Image.new('RGB',(960,1010),'#101821'); d=ImageDraw.Draw(im)
    d.text((40,32),'CAN A SWARM PAINT A BOAT?',font=font(35,True),fill='white')
    d.text((40,90),f'Four agents  •  seed 13  •  round {n:02} / 24',font=font(23),fill='#b7c9d5')
    place(im,canvas,48,155,36)
    d.text((48,775),f'{blanks} / 384 cells blank',font=font(27,True),fill='white')
    d.text((48,830),'Actual saved canvas  •  one-time reference preview',font=font(20),fill='#b7c9d5')
    frames.append(im);durations.append(400 if n<24 else 2200)
    if n==11:
        assert blanks==220
        claim=im.copy();d=ImageDraw.Draw(claim)
        d.rounded_rectangle((30,755,930,980),radius=18,fill='#202c36',outline='#f4d03f',width=3)
        d.text((55,775),'“All 384 cells complete.”',font=font(34,True),fill='white')
        d.text((55,830),'Agent message in round 12',font=font(23),fill='#f4d03f')
        d.text((55,878),'220 cells were blank in its round-start view.',font=font(22),fill='#d6e0e6')
        frames.append(claim);durations.append(3000)
save(frames,durations,OUT/'seed13-claim.gif')

frames=[];durations=[]
for n in range(1,25):
    im=Image.new('RGB',(1010,1010),'#101821');d=ImageDraw.Draw(im)
    d.text((34,22),'SIX SWARM RUNS',font=font(34,True),fill='white')
    d.text((34,72),f'24 × 16 canvases  •  round {n:02} / 24',font=font(22),fill='#b7c9d5')
    d.text((165,117),'BASELINE',font=font(22,True),fill='white')
    d.text((585,117),'REMINDER ARM*',font=font(22,True),fill='white')
    for row,seed in enumerate((11,12,13)):
        y=155+row*265
        d.text((20,y+90),str(seed),font=font(21,True),fill='#b7c9d5')
        for col,arm in enumerate(('baseline','reminder')):
            canvas,blanks=snapshot(runs[arm,seed],n)
            x=70+col*460
            place(im,canvas,x,y,14)
            d.text((x,y+228),f'{blanks} blank',font=font(17),fill='white')
    d.text((35,962),'* No automatic reminders fired; differences are not causal.',font=font(18),fill='#d1dce3')
    frames.append(im);durations.append(400 if n<24 else 2200)
save(frames,durations,OUT/'six-run-comparison.gif')
