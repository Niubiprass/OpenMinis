#!/usr/bin/env python3
"""CI-only receipt from the actual zipped IPA; never installs or runs the App."""
import pathlib,zipfile,tempfile,plistlib,hashlib,struct,math,json,subprocess,sys

def need(v,m):
 if not v:raise ValueError(m)
def run(*args):return subprocess.run(args,check=True,text=True,capture_output=True).stdout
def version(v):return '.'.join(str(x) for x in (v>>16,(v>>8)&255,v&255))
def pages(data):
 need(len(data)>32,'truncated Mach-O');magic,cpu,sub,kind,ncmds,sz,flags,res=struct.unpack_from('<8I',data);need(magic==0xfeedfacf and cpu==0x100000c and kind in (2,6),'unexpected Mach-O type')
 pos=32;limit=32+sz;need(limit<=len(data),'load commands bounds');build=[];sig=None;uuid=None
 for _ in range(ncmds):
  cmd,n=struct.unpack_from('<II',data,pos);need(n>=8 and pos+n<=limit,'bad load command')
  if cmd==0x32:pl,m,s,t=struct.unpack_from('<4I',data,pos+8);build.append({'platform':pl,'minOS':version(m),'SDK':version(s)})
  if cmd==0x25:m,s=struct.unpack_from('<II',data,pos+8);build.append({'platform':2,'minOS':version(m),'SDK':version(s)})
  if cmd==0x1b:uuid=data[pos+8:pos+24].hex()
  if cmd==0x1d:need(sig is None,'multiple signatures');sig=struct.unpack_from('<II',data,pos+8)
  pos+=n
 need(pos==limit and build and sig,'missing build/signature');at,cap=sig;need(at+cap<=len(data),'signature bounds');raw=data[at:at+cap];sm,l,count=struct.unpack_from('>3I',raw);need(sm==0xfade0cc0 and 12+8*count<=l<=len(raw),'superblob bounds');blobs={}
 for i in range(count):
  slot,o=struct.unpack_from('>2I',raw,12+8*i);need(o+8<=l and slot not in blobs,'blob index');bm,n=struct.unpack_from('>2I',raw,o);need(n>=8 and o+n<=l,'blob range');blobs[slot]=(bm,raw[o:o+n])
 rows=[]
 for slot,(bm,cd) in blobs.items():
  if bm!=0xfade0c02:continue
  need(len(cd)>=44,'short CodeDirectory');_,clen,ver,fl,hoff,io,ns,nc,climit=struct.unpack_from('>9I',cd);hs,ht,pl,shift=struct.unpack_from('>4B',cd,36)
  if ver>=0x20300:
   need(len(cd)>=64,'short new directory');large=struct.unpack_from('>Q',cd,56)[0]
   if large:climit=large
  need(0<climit<=at and ht in (1,2,3,4) and shift<=30,'code/hash parameters');alg={1:'sha1',2:'sha256',3:'sha256',4:'sha384'}[ht];need(hs=={1:20,2:32,3:20,4:48}[ht],'hash size');ps=(1<<shift) if shift else climit
  need(nc==math.ceil(climit/ps) and hoff>=ns*hs and hoff+nc*hs<=len(cd),'code slots')
  for i in range(nc):need(hashlib.new(alg,data[i*ps:min(climit,(i+1)*ps)]).digest()[:hs]==cd[hoff+i*hs:hoff+(i+1)*hs],f'code page {i} rejected')
  checked=[];external=[]
  for i in range(1,ns+1):
   h=cd[hoff-i*hs:hoff-(i-1)*hs]
   if not any(h):continue
   if i in blobs:need(hashlib.new(alg,blobs[i][1]).digest()[:hs]==h,'internal special slot');checked.append(i)
   else:external.append(i)
  need(io<len(cd),'identifier range');rows.append({'slot':slot,'hash':alg,'codePages':nc,'pageSize':ps,'codeLimit':climit,'codePagesVerified':True,'internalSpecialSlots':checked,'externalSlotsCodesignVerifies':external})
 need(rows,'no directory');return {'architecture':'arm64e' if sub&0xffffff==2 else 'arm64','type':kind,'uuid':uuid,'build':build,'codeDirectories':rows}

def slices(raw):
 if raw[:4]==b'\xcf\xfa\xed\xfe':return [raw]
 need(raw[:4] in (b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'),'unsupported fat image');is64=raw[:4]==b'\xca\xfe\xba\xbf';n=struct.unpack_from('>I',raw,4)[0];need(n<=8,'fat count');out=[]
 for i in range(n):
  if is64:cpu,sub,at,sz,al,res=struct.unpack_from('>IIQQII',raw,8+32*i)
  else:cpu,sub,at,sz,al=struct.unpack_from('>5I',raw,8+20*i)
  need(at+sz<=len(raw) and cpu==0x100000c,'fat range/unsupported architecture');out.append(raw[at:at+sz])
 return out

ipa=pathlib.Path(sys.argv[1]);out=pathlib.Path(sys.argv[2]);expected=sys.argv[3];sha=hashlib.sha256(ipa.read_bytes()).hexdigest();images=[];neg=[]
with zipfile.ZipFile(ipa) as z:
 need(z.testzip() is None,'IPA CRC failed');names=z.namelist();need(len(names)==len(set(names)),'duplicate IPA entry');need(all(not n.startswith('/') and '..' not in pathlib.PurePosixPath(n).parts for n in names),'unsafe IPA paths')
 with tempfile.TemporaryDirectory(prefix='lyrics-ipa-verify-') as tmp:
  z.extractall(tmp);app=pathlib.Path(tmp)/'Payload/Minis.app';info=plistlib.loads((app/'Info.plist').read_bytes());need(info['CFBundleIdentifier']=='com.openminis.app' and info['CFBundleShortVersionString']=='1.16' and str(info['MinisBuildNumber'])==expected,'App identity/version mismatch');need(info['MinimumOSVersion']=='15.5','main minOS')
  run('codesign','--verify','--deep','--strict',str(app));ent=plistlib.loads(subprocess.run(['codesign','-d','--entitlements',':-',str(app)],check=True,capture_output=True).stdout);source_ent=plistlib.loads(pathlib.Path('src/ios/Minis.entitlements').read_bytes());need(ent==source_ent,'App entitlements differ from source');need('group.com.openminis.app' in ent.get('com.apple.security.application-groups',[]),'missing group')
  for f in sorted(app.rglob('*')):
   if not f.is_file() or f.is_symlink():continue
   with f.open('rb') as stream:magic=stream.read(4)
   if magic not in (b'\xcf\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'):continue
   raw=f.read_bytes();relative=f.relative_to(app).as_posix();runs=run('xcrun','vtool','-show-build',str(f));rows=[]
   for data in slices(raw):
    rows.append(pages(data));first=bytearray(data);first[4096 if len(first)>4096 else 31]^=1
    try:pages(first)
    except (ValueError,struct.error) as e:need('code page' in str(e),'tamper did not reach signature check');neg.append({'image':relative,'rejected':str(e)})
    else:raise ValueError('tampered code page survived')
   for row in rows:
    for b in row['build']:
     need(b['platform']==2,'non-iOS image');minimum=tuple(int(v) for v in b['minOS'].split('.'))
     if relative=='Frameworks/RealTimeCutVADCXXLibrary.framework/RealTimeCutVADCXXLibrary':need(minimum==(15,6,0),'unexpected VAD baseline')
     else:need(minimum<=(15,5,0),'incompatible image')
   images.append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'slices':rows,'vtool':runs})
  need(any(x['path']==info['CFBundleExecutable'] for x in images),'main not verified')
result={'ipa':ipa.name,'bytes':ipa.stat().st_size,'sha256':sha,'commit':run('git','rev-parse','HEAD').strip(),'info':{k:info.get(k) for k in ['CFBundleIdentifier','CFBundleExecutable','CFBundleShortVersionString','CFBundleVersion','MinisBuildNumber','MinimumOSVersion']},'CRC':'PASS','codesign_deep_strict':'PASS','entitlements_exact_source':True,'images':images,'tampered_codepages_rejected':neg,'known_VAD_exception':'original prebuilt minOS15.6 retained; iOS15.5 voice/load unverified','device_tested':False}
out.write_text(json.dumps(result,indent=2)+'\n');print('ACTUAL IPA VERIFIED',expected,len(images),'Mach-O',sha,'no install/device')
