#!/usr/bin/env python3
"""Local source/fixture checks; --require-native MUST run on macOS CI.
No device, network, build-project changes or CI dispatch. The native harness
compiles the REAL Catalog.swift (only UI thumbnail types are stubbed).
"""
import argparse, binascii, json, pathlib, platform, shutil, struct, subprocess, tempfile, zlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
CAT = ROOT / 'src/ios/Agent/Chat/MiniSightCatalog.swift'
UI = ROOT / 'src/ios/Views/Settings/MiniSightHomePage.swift'
FIX = ROOT / 'scripts/fixtures/minisight_action_import'

def png(w, h):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', binascii.crc32(name + data) & 0xffffffff)
    rows = b''.join(b'\0' + ((b'\xff\0\0\xff' if y < h//2 else b'\0\0\xff\xff') * w) for y in range(h))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')

def gif(w=96, h=117):
    result = b'GIF89a' + struct.pack('<HHBBB', w, h, 0xf0, 0, 0) + b'\xff\0\0\0\0\xff'
    for frame, delay in enumerate([4, 17]):
        codes = []
        for y in range(h):
            for x in range(w):
                codes += [4, int(y >= h//2) ^ frame]  # reset dictionary: fixed 3-bit codes
        codes += [5]
        acc = bits = 0
        compressed = bytearray()
        for code in codes:
            acc |= code << bits; bits += 3
            while bits >= 8:
                compressed.append(acc & 255); acc >>= 8; bits -= 8
        if bits: compressed.append(acc & 255)
        result += b'!\xf9\x04\0' + struct.pack('<H', delay) + b'\0\0'
        result += b',' + struct.pack('<HHHHB', 0, 0, w, h, 0) + b'\x02'
        for offset in range(0, len(compressed), 255):
            part = compressed[offset:offset+255]; result += bytes([len(part)]) + part
        result += b'\0'
    return result + b';'

def fixtures(dest):
    dest.mkdir(parents=True, exist_ok=True)
    (dest/'source.png').write_bytes(png(96, 117))
    (dest/'oversize.png').write_bytes(png(4097, 1))
    (dest/'idle.gif').write_bytes(gif())
    manifest = {'schema': 1, 'id': 'BE27E983-68DC-4D38-9755-13BBA99862A9', 'clips': [
        {'id': 'rest', 'role': 'idle', 'frames': [{'file':'idle.gif','index':0,'duration':0.04}, {'file':'idle.gif','index':1,'duration':0.17}]},
        {'id': 'daily-play', 'role':'idleAlt', 'category':'play', 'frames':[{'file':'source.png','index':0,'duration':0.2}]},
        {'id': 'touch', 'role':'tap', 'frames':[{'file':'source.png','index':0,'duration':0.2}]},
        {'id': 'music', 'role':'music', 'frames':[{'file':'idle.gif','index':1,'duration':0.3}]}]}
    (dest/'actions.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest

def static_checks():
    source = CAT.read_text(); ui = UI.read_text().split('struct MiniSightDownloadPage:',1)[1]
    baseline = subprocess.check_output(['git','show','82f9fb1:'+str(CAT.relative_to(ROOT))], cwd=ROOT, text=True)
    for begin,end in [('    static func prepare(', '    private static func verify('), ('    static func preview(', '    /// Records imported by')]:
        assert source.split(begin,1)[1].split(end,1)[0] == baseline.split(begin,1)[1].split(end,1)[0], begin+' changed'
    assert 'var actionPack: String? = nil' in source
    assert 'guard meta.actionPack == nil else { return nil }' in source
    helper = source.split('enum MiniSightActionImport {',1)[1].split('/// Cancellation is accepted',1)[0]
    for token in ['O_NOFOLLOW','openat(', 'NSFileCoordinator(', 'startAccessingSecurityScopedResource', 'stopAccessingSecurityScopedResource', 'kCGImagePropertyGIFUnclampedDelayTime', 'try decode(imageSource, frame: frame)', 'original-actions.json']:
        assert token in helper, token
    assert 'URLSession' not in helper and 'unzip' not in helper
    for token in ['contentTypes: [.folder], asCopy: false', 'importActionDirectory(', 'documentPickerWasCancelled', 'GIF']:
        assert token in ui, token
    assert 'try verifyAction(meta)' in source
    assert 'category: String? = nil' in source and '"micro", "play", "food", "seasonal", "social"' in source
    assert 'keys == ["id", "role", "frames"] || keys == ["id", "role", "frames", "category"]' in source
    assert 'pet.backup.json' in source.split('private static func collectActionPacks()',1)[1].split('private static func changed()',1)[0]
    print('PASS source guards; static prepare/preview byte-identical to 82f9fb1')

def native(directory):
    source = CAT.read_text()
    for module in ['Combine', 'SwiftUI', 'UIKit']:
        source = source.replace('import '+module+'\n', '')
    start = source.index('enum MiniSightPetPalette:')
    end = source.index('/// All full-image I/O', start)
    source = source[:start] + source[end:]
    support = '''\nimport CoreGraphics
struct UIImage {
    enum Orientation { case up }
    init(cgImage: CGImage, scale: CGFloat, orientation: Orientation) {}
    init?(data: Data) { return nil } // Wrapper unused by this native file/catalog test.
    var cgImage: CGImage? { nil }
}
enum MiniSightPetFile {
    static var directory: URL { URL(fileURLWithPath: CommandLine.arguments[1]).appendingPathComponent("documents", isDirectory: true) }
    static var url: URL { directory.appendingPathComponent("pet.png") }
}
'''
    defaults = (ROOT / 'src/ios/MiniSightDefaultAssets.swift').read_text().replace('import UIKit\n', '')
    # Bundle.main on a standalone native harness points at its executable dir.
    # Copy the ACTUAL bundled original artwork; no fake default bytes/parser.
    shutil.copytree(ROOT / 'src/ios/Resources/MiniSightDefaults', directory / 'MiniSightDefaults')
    path = directory/'main.swift'
    path.write_text(source + support + defaults + (FIX/'harness.swift').read_text())
    subprocess.run(['xcrun','--sdk','macosx','swiftc','-swift-version','5',str(path),'-o',str(directory/'test')], check=True)
    subprocess.run([str(directory/'test'),str(directory),str(FIX)], check=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--require-native', action='store_true'); p.add_argument('--generate-fixtures', action='store_true'); a = p.parse_args()
    if a.generate_fixtures: fixtures(FIX)
    static_checks()
    expected = json.loads((FIX/'actions.json').read_text())
    assert [f['duration'] for f in expected['clips'][0]['frames']] == [0.04, 0.17]
    assert (FIX/'source.png').read_bytes() == png(96,117)
    assert (FIX/'idle.gif').read_bytes() == gif()
    print('PASS deterministic synthetic PNG/GIF/JSON fixtures (not native decoding)')
    if platform.system() == 'Darwin' and shutil.which('xcrun'):
        with tempfile.TemporaryDirectory(prefix='minisight-action-test-') as t: native(pathlib.Path(t))
    elif a.require_native:
        raise SystemExit('FAIL: macOS + Xcode Swift required; native tests not executed')
    else:
        print('SKIP native ImageIO/catalog execution: requires macOS CI --require-native')
