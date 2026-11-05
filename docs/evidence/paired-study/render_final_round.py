from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import json
D=Path('docs/evidence/paired-study'); data=json.loads((D/'canvas-data.json').read_text()); run=next(x for x in data['runs'] if x['seed']==13 and x['arm']=='reminder'); palette={'S':(126,200,227),'W':(18,72,140),'Y':(244,208,63),'B':(122,78,40),'w':(246,244,238),'P':(255,45,149),'G':(126,217,87),'K':(18,18,18),'O':(232,122,36),'R':(196,40,48),'Gy':(138,138,138),'L':(166,214,236),'.':(232,228,218)}; fonts='/usr/share/fonts/truetype/dejavu/'; f=lambda n,b=False:ImageFont.truetype(fonts+('DejaVuSans-Bold.ttf' if b else 'DejaVuSans.ttf'),n)
frames=[];duration=[]
for i,grid in enumerate(run['frames'],1):
 im=Image.new('RGB',(960,1050),'#101821'); d=ImageDraw.Draw(im);d.text((40,30),'FOUR AGENTS PAINT A BOAT',font=f(34,True),fill='white');d.text((40,83),f'Actual saved canvas  •  round {i:02} / 24',font=f(23),fill='#b7c9d5')
 canvas=Image.new('RGB',(24,16));
 for y,row in enumerate(grid):
  for x,c in enumerate(row):canvas.putpixel((x,y),palette[c])
 im.paste(canvas.resize((864,576),Image.Resampling.NEAREST),(48,140));blank=sum(c=='.' for row in grid for c in row)
 if i==24:
  assert blank==251
  d.rounded_rectangle((35,750,925,1010),radius=20,fill='#202c36',outline='#f4d03f',width=3)
  d.text((58,775),'251 / 384 cells still blank',font=f(32,True),fill='white');d.text((58,830),'All 4 agents said it should be complete.',font=f(24),fill='#f4d03f');d.text((58,875),'32 / 32 proposed paints repeated',font=f(23),fill='#d6e0e6');d.text((58,910),'colors already present at round start.',font=f(23),fill='#d6e0e6');d.text((58,965),'One run  •  reminder enabled, never triggered',font=f(18),fill='#b7c9d5')
 else:
  d.text((48,755),f'{blank} / 384 cells blank',font=f(29,True),fill='white');d.text((48,815),'Four agents  •  seed 13  •  one-time preview',font=f(21),fill='#b7c9d5')
 frames.append(im);duration.append(350 if i<24 else 4500)
frames[0].save(D/'seed13-final-round.gif',save_all=True,append_images=frames[1:],duration=duration,loop=0,optimize=True,disposal=2)
with Image.open(D/'seed13-final-round.gif') as check:assert check.n_frames==24;print('GIF',check.size,check.n_frames,(D/'seed13-final-round.gif').stat().st_size)
