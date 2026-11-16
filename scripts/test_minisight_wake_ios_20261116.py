#!/usr/bin/env python3
"""Future authorized Apple CI only: fixed binary headers + real iOS typecheck.
This does not link/run the downloaded native engine or start a microphone.
"""
import hashlib, json, platform, shutil, stat, subprocess, sys, tempfile, urllib.request, zipfile
from pathlib import Path, PurePosixPath
ROOT=Path(__file__).resolve().parents[1];IOS=ROOT/'src/ios'
PINS=[
    ('sherpa','https://github.com/k2-fsa/sherpa-onnx/releases/download/xcframework/sherpa-onnx-v2.0.1-ios-static.xcframework.zip',16349037,'88aa569f71b7903e0bbdfbe6e2e114b3b95862b1ef0759eea3024f82926d7374'),
    ('ort','https://github.com/csukuangfj/onnxruntime-libs/releases/download/v1.28.2/onnxruntime-ios-static-xcframework-1.28.2.xcframework.zip',33821118,'2c2299acbb461d26d4bac4bc85985d40e7c7177ed6072703ae0846d88b0b4599')
]
def download(pin, folder):
    name,url,size,sha=pin;target=folder/(name+'.zip')
    if target.is_file() and target.stat().st_size==size and hashlib.sha256(target.read_bytes()).hexdigest()==sha:
        return target
    part=target.with_suffix('.part')
    request=urllib.request.Request(url,headers={'User-Agent':'MiniSight-native-CI/0.8.43'})
    count=0;digest=hashlib.sha256()
    with urllib.request.urlopen(request,timeout=60) as response,part.open('wb') as output:
        while True:
            chunk=response.read(128*1024)
            if not chunk:break
            count+=len(chunk)
            if count>size:raise RuntimeError('fixed archive oversized: '+name)
            digest.update(chunk);output.write(chunk)
    if count!=size or digest.hexdigest()!=sha:raise RuntimeError('fixed archive SHA/size mismatch: '+name)
    part.replace(target);return target

def safe_extract(path,destination):
    with zipfile.ZipFile(path) as z:
        total=0
        for row in z.infolist():
            p=PurePosixPath(row.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in row.filename or stat.S_ISLNK(row.external_attr>>16):
                raise RuntimeError('unsafe XCFramework archive path')
            total+=row.file_size
            if total>300*1024*1024 or row.file_size>100*1024*1024:raise RuntimeError('XCFramework extraction limit')
        bad=z.testzip()
        if bad:raise RuntimeError('XCFramework CRC mismatch')
        z.extractall(destination)

def typecheck():
    if platform.system()!='Darwin' or not shutil.which('xcrun'):
        raise RuntimeError('iOS typecheck REQUIRED: no Apple toolchain; not run on iSH')
    compiler=subprocess.check_output(['xcrun','--find','swiftc'],text=True).strip()
    sdk=subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
    if not Path(sdk).is_dir():raise RuntimeError('Apple iPhoneOS SDK unavailable')
    cache=Path(tempfile.gettempdir())/'minisight-wake-fixed-headers-20261116';cache.mkdir(parents=True,exist_ok=True)
    controlled = IOS/'Packages/MiniSightKeywordRuntime/Artifacts/SherpaOnnxC.xcframework/ios-arm64/SherpaOnnxC.framework'
    if not controlled.is_dir(): raise RuntimeError('controlled Sherpa artifact unavailable before iOS typecheck')
    from test_minisight_keyword_provenance_20261116 import artifact_gate
    artifact_gate()
    frameworks=['-F',str(controlled.parent)]
    # Only ORT is fetched from the separately pinned remote archive. Do not
    # typecheck against a different prebuilt Sherpa than the one we will ship.
    for pin in [p for p in PINS if p[0] == 'ort']:
        archive=download(pin,cache);destination=cache/pin[0]
        marker=destination/'.verified-sha'
        if not marker.is_file() or marker.read_text()!=pin[3]:
            destination.mkdir(parents=True,exist_ok=True)
            safe_extract(archive,destination);marker.write_text(pin[3])
        found=list(destination.glob('*.xcframework/ios-arm64/*.framework'))
        if len(found)!=1:raise RuntimeError('device arm64 framework missing: '+pin[0])
        frameworks+=['-F',str(found[0].parent)]
    files=[IOS/('MiniSightWake'+x+'.swift') for x in ['Name','Policy','Assets','Engine','AudioPulse','Remote','Controller']]
    files += [IOS/'Views/Settings/MiniSightWakePage.swift',ROOT/'scripts/fixtures/minisight_wake_20261116/ios_support.swift']
    with tempfile.TemporaryDirectory(prefix='ms-wake-typecheck-') as d:
        bridge=Path(d)/'bridge.h'
        bridge.write_text('#import "MiniSightChatPanel.h"\n')
        args=[compiler,'-swift-version','5','-target','arm64-apple-ios15.5','-sdk',sdk,
              '-I',str(IOS/'MiniSightCore'),'-import-objc-header',str(bridge),*frameworks,
              '-typecheck',*[str(f) for f in files]]
        subprocess.run(args,check=True,timeout=180)
    print('PASS production wake C API/AVFoundation/UIKit/SwiftUI typecheck, target iOS15.5; no link/audio/device run')
if __name__=='__main__':
    try:typecheck()
    except (RuntimeError,OSError,subprocess.SubprocessError) as error:
        print('FAIL '+str(error),file=sys.stderr);sys.exit(1)
