#!/usr/bin/env python3
"""Offline executable resource/transport projections + native production Swift gate.
Python projections are explicitly NOT Swift/ObjC runtime execution.
--require-native fails closed without macOS swiftc (no CI is dispatched).
"""
import argparse, hashlib, json, platform, re, shutil, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageChops
ROOT=Path(__file__).resolve().parents[1]; IOS=ROOT/'src/ios'; PLUGIN=ROOT.parent/'plugin/debs/MiniSight'
S=(IOS/'MiniSightSettings.swift').read_text(); C=(IOS/'MiniSightConfigStore.swift').read_text()
CAT=(IOS/'Agent/Chat/MiniSightCatalog.swift').read_text(); H=(IOS/'MiniSightDefaultAssets.swift').read_text()
KEY='minisight.actions.daily'
D=IOS/'Resources/MiniSightDefaults'

def extracted():
    keys=dict(re.findall(r'static let (\w+) = "(minisight\.[\w.]+)"',S))
    block=S.split('static let runtimeFields:',1)[1].split('static let all',1)[0]
    fields={keys[k]:v for k,v in re.findall(r'MiniSightSettingKey\.(\w+): "(\w+)"',block)}
    assert len(fields)==int(re.search(r'runtimeFields.count == (\d+)',S)[1])==53
    assert fields['minisight.keyboard.avoid']=='keyboardAvoidance'
    assert fields[KEY]=='dailyActionsEnabled'
    return keys, fields

def projected_transport():
    keys,fields=extracted()
    assert 'for (key, value) in initial where defaults.object(forKey: key) == nil' in S
    initial=S.split('static let initial:',1)[1].split('static func installDefaults',1)[0]
    bools={keys[k]:v=='true' for k,v in re.findall(r'MiniSightSettingKey\.(\w+): (true|false)',initial)}
    assert bools[KEY] is True
    assert bools['minisight.keyboard.avoid'] is False
    resources = [IOS/'MiniSightCore/MiniSightResources.m']
    if (PLUGIN/'MiniSightResources.m').is_file():
        resources.append(PLUGIN/'MiniSightResources.m')
    else:
        print('SKIP live sibling plugin parity on independent App checkout; App native defaults still required')
    for name in resources:
        mapping=dict(re.findall(r'@"(minisight\.[\w.]+)": @"(\w+)"',name.read_text().split('+ (NSDictionary<NSString *, id> *)mergedPreferences',1)[0]))
        assert mapping[KEY]=='dailyActionsEnabled'
        assert mapping['minisight.keyboard.avoid']=='keyboardAvoidance'
        def merge(prefs, snap):
            out=dict(prefs)
            for k,f in mapping.items():
                if snap.get(f) is not None: out[k]=snap[f]
            out.update({k:v for k,v in snap.get('preferences',{}).items() if k in mapping and v is not None})
            return out
        assert merge({KEY:True},{'dailyActionsEnabled':False})[KEY] is False
        assert merge({KEY:True},{'dailyActionsEnabled':True,'preferences':{KEY:False}})[KEY] is False
        assert merge({KEY:False},{'preferences':{'evil.key':True}})[KEY] is False
        assert 'evil.key' not in merge({}, {'preferences':{'evil.key':True}})
    with tempfile.TemporaryDirectory(prefix='minisight-settings-') as tmp:
        for explicit in [None,False,True]:
            stored={'minisight.activity':'off','minisight.music.motion':True,'minisight.music.lyrics':False,'minisight.pet.costume':'existing'}
            if explicit is not None: stored[KEY]=explicit
            for k,v in bools.items(): stored.setdefault(k,v)
            expected=True if explicit is None else explicit
            assert stored[KEY] is expected and stored['minisight.activity']=='off'
            raw={k:stored.get(k,'fixture') for k in fields}
            snapshot={'version':2,'preferences':raw,**{v:raw[k] for k,v in fields.items()}}
            file=Path(tmp)/'runtime.json'; stage=file.with_suffix('.tmp')
            stage.write_text(json.dumps(snapshot,sort_keys=True)); stage.replace(file)
            readback=json.loads(file.read_text()); assert readback==snapshot
            assert readback['dailyActionsEnabled'] is expected
            assert readback['preferences']['minisight.music.motion'] is True
            assert readback['preferences']['minisight.pet.costume']=='existing'
            readback['dailyActionsEnabled']=not expected
            assert readback!=snapshot  # corrupt readback must not acknowledge
    assert S.index('NSDictionary(dictionary: decoded).isEqual(to: values)') < S.index('CFNotificationCenterPostNotification(', S.index('enum MiniSightRuntimeSnapshot'))
    for t in ['@Published var dailyActionsEnabled: Bool','dailyActionsEnabled = MiniSightConfig.bool(MiniSightSettingKey.dailyActionsEnabled, true)','case MiniSightSettingKey.dailyActionsEnabled: return dailyActionsEnabled']:
        assert t in C
    print('PASS transport projections: default/false/true, both alias/canonical readers, readback corruption, old values independent')

def resources():
    p=json.loads((D/'PROVENANCE.json').read_text()); assert p['license']=='CC0-1.0' and not p['thirdPartyArt']
    assert sum(p['frameCounts'])==57
    for name,sha in p['files'].items(): assert hashlib.sha256((D/name).read_bytes()).hexdigest()==sha
    data=(D/'base-storage-atlas.png').read_bytes()
    assert hashlib.sha256(data).hexdigest()==re.search(r'static let sha256 = "([0-9a-f]+)"',H)[1]
    normal=Image.open(D/'base-preview-atlas.png').convert('RGBA'); storage=Image.open(D/'base-storage-atlas.png').convert('RGBA')
    assert normal.size==storage.size==(768,936)
    assert normal.tobytes()==storage.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
    for row,n in enumerate(p['frameCounts']):
        frames=[normal.crop((col*96,row*104,(col+1)*96,(row+1)*104)) for col in range(8)]
        assert all(f.getbbox() for f in frames[:n]) and all(not f.getbbox() for f in frames[n:])
        assert len({f.tobytes() for f in frames[:n]})>1
    assert 'withoutOverwriting' in CAT and 'fileExists(atPath: file.path)' in CAT
    assert 'guard (try? verifyAction(checked)) != nil else { continue }' in CAT
    with tempfile.TemporaryDirectory(prefix='minisight-defaults-') as tmp:
        root=Path(tmp)
        def seed():
            if any((root/n).exists() or (root/n).is_symlink() for n in ['pet.png','pet.json']): return False
            (root/'pet.png').write_bytes(data); (root/'pet.json').write_text('{"layoutVersion":3,"variants":1}')
            return True
        assert seed(); before={p.name:p.read_bytes() for p in root.iterdir()}; assert not seed()
        assert before=={p.name:p.read_bytes() for p in root.iterdir()}
        (root/'pet.png').write_bytes(b'broken-user-art'); (root/'pet.json').write_text('{old metadata')
        before={p.name:p.read_bytes() for p in root.iterdir()}; assert not seed()
        assert before=={p.name:p.read_bytes() for p in root.iterdir()}
        assert hashlib.sha256(b'broken-user-art').hexdigest()!=p['files']['base-storage-atlas.png']
    print('PASS actual PNG: 57 nonblank frames, nine animated rows, transparency, sha/orientation; seed-preservation/bad-art projection')

def native():
    if platform.system()!='Darwin' or not shutil.which('swiftc'): return False
    source=S.replace('import Combine\n','')
    source=source.replace('CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),\n                CFNotificationName("com.openminis.minisight.settings" as CFString), nil, nil, true)', 'recordVerifiedNotification(container: container)')
    support='''\nvar notifications = 0
func MSDiagEvent(_ a: String, _ b: String, _ c: String, _ d: [String: Any]) {}
func recordVerifiedNotification(container: URL) {
    let file = container.appendingPathComponent("Documents/MiniSight/runtime.json")
    precondition((try? Data(contentsOf: file)).isEmpty == false)
    notifications += 1
}
'''.replace('(try? Data(contentsOf: file)).isEmpty == false','((try? Data(contentsOf: file))?.isEmpty) == false')
    harness='''
let key = MiniSightSettingKey.dailyActionsEnabled
let keyboard = MiniSightSettingKey.keyboardAvoidance
let defaults = UserDefaults.standard
let previous = MiniSightConfig.all.reduce(into: [String: Any]()) { if let v = defaults.object(forKey: $1) { $0[$1] = v } }
defer { for k in MiniSightConfig.all { if let v = previous[k] { defaults.set(v, forKey: k) } else { defaults.removeObject(forKey: k) } } }
let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
defer { try? FileManager.default.removeItem(at: root) }
for value in [nil, false, true] as [Bool?] {
    defaults.removeObject(forKey: key)
    defaults.removeObject(forKey: keyboard)
    if let value = value { defaults.set(value, forKey: keyboard) }
    if let value = value { defaults.set(value, forKey: key) }
    defaults.set("off", forKey: MiniSightSettingKey.activity)
    MiniSightConfig.installDefaults()
    precondition(MiniSightConfig.bool(key, false) == (value ?? true))
    precondition(defaults.string(forKey: MiniSightSettingKey.activity) == "off")
    precondition(MiniSightRuntimeSnapshot.write(container: root))
    let data = try Data(contentsOf: root.appendingPathComponent("Documents/MiniSight/runtime.json"))
    let bag = try JSONSerialization.jsonObject(with: data) as! [String: Any]
    precondition((bag["dailyActionsEnabled"] as? Bool) == (value ?? true))
    precondition((bag["keyboardAvoidance"] as? Bool) == (value ?? false))
    precondition(((bag["preferences"] as! [String: Any])[keyboard] as? Bool) == (value ?? false))
    precondition(((bag["preferences"] as! [String: Any])[key] as? Bool) == (value ?? true))
}
precondition(notifications == 3)
precondition(!MiniSightRuntimeSnapshot.write(container: root, rawValues: [:]))
precondition(notifications == 3)
print("PASS native production defaults/snapshot/readback + notification spy")
'''
    with tempfile.TemporaryDirectory(prefix='minisight-native-') as tmp:
        file=Path(tmp)/'main.swift'; file.write_text(source+support+harness)
        exe=Path(tmp)/'test'; subprocess.run(['swiftc',str(file),'-o',str(exe)],check=True); subprocess.run([str(exe)],check=True)
    return True

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--require-native',action='store_true'); args=parser.parse_args()
    projected_transport(); resources()
    if not native():
        print('SKIP native Swift/Foundation execution: macOS swiftc unavailable; Python projections are not native proof')
        if args.require_native: raise SystemExit(2)
