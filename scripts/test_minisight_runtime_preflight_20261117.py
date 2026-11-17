#!/usr/bin/env python3
"""Actual production makeSpotter excerpt with C API mocks; never starts audio.
Tests sequencing/error cleanup, not ONNX inference or iOS/device execution.
"""
import argparse, platform, shutil, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'src/ios/MiniSightWakeEngine.swift'
GUARD='guard SherpaOnnxMiniSightRuntimeIsCompatible() == 1 else { throw Failure.runtime }'

def excerpt(text):
    start=text.index('    private func makeSpotter(')
    opening=text.index('{',start);depth=1;pos=opening+1
    while depth:
        depth += (text[pos]=='{')-(text[pos]=='}');pos+=1
    return text[start:pos]

SUPPORT=r'''
import Foundation
struct Feature { var sample_rate: Int32 = 0; var feature_dim: Int32 = 0 }
struct Transducer { var encoder: UnsafePointer<CChar>?; var decoder: UnsafePointer<CChar>?; var joiner: UnsafePointer<CChar>? }
struct Model { var transducer = Transducer(); var tokens: UnsafePointer<CChar>?; var num_threads: Int32 = 0; var provider: UnsafePointer<CChar>?; var debug: Int32 = 0 }
struct SherpaOnnxKeywordSpotterConfig { var feat_config=Feature(); var model_config=Model(); var max_active_paths: Int32=0; var num_trailing_blanks: Int32=0; var keywords_score: Float=0; var keywords_threshold: Float=0; var keywords_buf: UnsafePointer<CChar>?; var keywords_buf_size: Int32=0 }
enum MiniSightWakeAssets { struct Files { let encoder=URL(fileURLWithPath:"/e"); let decoder=URL(fileURLWithPath:"/d"); let joiner=URL(fileURLWithPath:"/j"); let tokens=URL(fileURLWithPath:"/t") } }
var compatible: Int32=0
var modelWorks=true
var streamWorks=true
var checks=0
var models=0
var streams=0
var destroyed=0
var sequence=[String]()
func SherpaOnnxMiniSightRuntimeIsCompatible() -> Int32 { checks+=1;sequence.append("preflight");return compatible }
func SherpaOnnxCreateKeywordSpotter(_ c: UnsafePointer<SherpaOnnxKeywordSpotterConfig>) -> OpaquePointer? {
    models+=1;sequence.append("model")
    let x=c.pointee
    precondition(x.feat_config.sample_rate==16000 && x.feat_config.feature_dim==80)
    precondition(x.model_config.num_threads==1 && x.model_config.debug==0)
    precondition(String(cString:x.model_config.provider!)=="cpu")
    precondition(String(cString:x.model_config.transducer.encoder!)=="/e")
    precondition(String(cString:x.keywords_buf!)=="ni hao @minisight" && x.keywords_buf_size==17)
    return modelWorks ? OpaquePointer(bitPattern:0x100) : nil
}
func SherpaOnnxCreateKeywordStream(_ p: OpaquePointer) -> OpaquePointer? { streams+=1;sequence.append("stream");precondition(p==OpaquePointer(bitPattern:0x100));return streamWorks ? OpaquePointer(bitPattern:0x200) : nil }
func SherpaOnnxDestroyKeywordSpotter(_ p: OpaquePointer) { destroyed+=1;precondition(p==OpaquePointer(bitPattern:0x100)) }
func reset(_ api: Int32,_ model: Bool=true,_ stream: Bool=true) {compatible=api;modelWorks=model;streamWorks=stream;checks=0;models=0;streams=0;destroyed=0;sequence=[]}
final class MiniSightWakeEngine {
    enum Failure: Error {case runtime, model}
'''
EXERCISE=r'''
    func exercise() throws {
        let f=MiniSightWakeAssets.Files()
        reset(0)
        do { _=try makeSpotter(files:f,definition:"ni hao @minisight");preconditionFailure("incompatible API accepted") }
        catch Failure.runtime { } catch { preconditionFailure("wrong incompatibility error") }
        precondition(checks==1 && models==0 && streams==0 && destroyed==0 && sequence==["preflight"])
        reset(1,false)
        do { _=try makeSpotter(files:f,definition:"ni hao @minisight");preconditionFailure("failed model accepted") }
        catch Failure.model { }
        precondition(checks==1 && models==1 && streams==0 && destroyed==0 && sequence==["preflight","model"])
        reset(1,true,false)
        do { _=try makeSpotter(files:f,definition:"ni hao @minisight");preconditionFailure("failed stream accepted") }
        catch Failure.model { }
        precondition(checks==1 && models==1 && streams==1 && destroyed==1 && sequence==["preflight","model","stream"])
        reset(1)
        let h=try makeSpotter(files:f,definition:"ni hao @minisight")
        precondition(h.spotter==OpaquePointer(bitPattern:0x100) && h.stream==OpaquePointer(bitPattern:0x200))
        precondition(checks==1 && models==1 && streams==1 && destroyed==0 && sequence==["preflight","model","stream"])
        print("PASS actual makeSpotter: incompatibility blocks constructor, compatible success, model failure, stream failure cleanup; no audio")
    }
}
try MiniSightWakeEngine().exercise()
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--require-native',action='store_true');args=parser.parse_args()
    source=ENGINE.read_text();method=excerpt(source)
    assert GUARD in method and method.index(GUARD)<method.index('withCString')<method.index('SherpaOnnxCreateKeywordSpotter')
    assert 'case .runtime:' in source and '.failure(error)' in source
    assert 'import onnxruntime' not in source
    print('PASS production preflight source order/error delivery; constructor parameters preserved')
    if platform.system()!='Darwin' or not shutil.which('xcrun'):
        print('FAIL native Swift REQUIRED: no Apple toolchain' if args.require_native else 'SKIP native Swift: no Apple toolchain; no runtime/device proof')
        return 1 if args.require_native else 0
    sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
    compiler=subprocess.check_output(['xcrun','--find','swiftc'],text=True).strip()
    with tempfile.TemporaryDirectory(prefix='ms-runtime-preflight-') as tmp:
        folder=Path(tmp)
        variants=[('production',method,True),('missing_preflight',method.replace(GUARD,'',1),False),('wrong_error',method.replace('throw Failure.runtime','throw Failure.model',1),False)]
        for name,body,accepted in variants:
            file=folder/(name+'.swift');binary=folder/name
            file.write_text(SUPPORT+body+EXERCISE)
            subprocess.run([compiler,'-swift-version','5','-sdk',sdk,str(file),'-o',str(binary)],check=True,timeout=120)
            result=subprocess.run([str(binary)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
            if accepted:
                assert result.returncode==0, result.stderr[-1600:];print(result.stdout.strip())
            else:
                assert result.returncode!=0, 'behavior mutation unexpectedly passed: '+name
                print('PASS rejected behavior mutation:',name)
    return 0
if __name__=='__main__':raise SystemExit(main())
