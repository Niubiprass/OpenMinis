#!/usr/bin/env python3
"""Original geometric MiniSight fallback; no third-party art or audio."""
import hashlib, json, math
from pathlib import Path
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'src/ios/Resources/MiniSightDefaults'
COUNTS = [6,8,8,4,5,8,6,6,6]

def create():
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = Image.new('RGBA',(768,936))
    for row,n in enumerate(COUNTS):
        for col in range(n):
            im = Image.new('RGBA',(96,104)); d=ImageDraw.Draw(im)
            p=2*math.pi*col/n
            bob = round(2*math.sin(p)) if row != 4 else 0
            x,y=48,57+bob
            if row==4: y-=round(10*math.sin(math.pi*col/(n-1)))
            d.ellipse((20,91,76,97),fill=(70,110,130,45))
            d.ellipse((x-27,y-30,x+27,y+29),fill=(76,188,201,255),outline=(34,89,112,255),width=2)
            eyeY=y-4
            for ex in [x-10,x+10]:
                if row==5 or (row==0 and col==4): d.line((ex-3,eyeY,ex+3,eyeY),fill=(24,62,80,255),width=2)
                else: d.ellipse((ex-2,eyeY-3,ex+2,eyeY+2),fill=(24,62,80,255))
            d.arc((x-6,y+1,x+6,y+9),0,180,fill=(24,62,80,255),width=2)
            leg=round(4*math.sin(p)) if row in [1,2,7] else 0
            d.ellipse((x-20,y+22+leg,x-5,y+30+leg),fill=(34,89,112,255))
            d.ellipse((x+5,y+22-leg,x+20,y+30-leg),fill=(34,89,112,255))
            if row==3: d.line((x+22,y,x+34,y-15-col*2),fill=(34,89,112,255),width=5)
            if row==6: d.arc((x-10,y-14,x+10,y+5),185,350,fill=(34,89,112,255),width=2)
            if row==8: d.ellipse((x-24,y+3,x-17,y+8),fill=(255,182,145,255))
            sheet.alpha_composite(im,(col*96,row*104))
    sheet.save(OUT/'base-preview-atlas.png',optimize=True)
    # Existing App/companion loaders invert the entire stored sheet.
    sheet.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(OUT/'base-storage-atlas.png',optimize=True)
    sheet.crop((0,0,96,104)).save(OUT/'base-preview.png',optimize=True)
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.png')}
    obj={'schema':1,'title':'小团 · 原创基础角色','author':'OpenMinis local repair original geometric artwork','license':'CC0-1.0','thirdPartyArt':False,'frameCounts':COUNTS,'columns':8,'rows':9,'cellSize':[96,104],'actions':['idle/blink','step-right','step-left','simple-wave','hop','eyes-closed-rest','wake','drag-response','neutral-music-pose'],'notDepicted':['stretch','yawn','fall-specific-limb-animation'],'storageOrientation':'vertically inverted; existing loader flips once','files':files}
    (OUT/'PROVENANCE.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    (OUT/'LICENSE.txt').write_text('Original geometric artwork generated for this project. No third-party sprites, reference GIFs, trademarks or source package artwork were copied. To the extent permitted by law, the contributor dedicates this original artwork to the public domain under CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/). This dedication covers only this directory and generator output, not the 48-GIF user package or other project art.\n')
    print(json.dumps(files,indent=2))
if __name__=='__main__': create()
