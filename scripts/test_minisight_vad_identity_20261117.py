#!/usr/bin/env python3
"""Linux default: real read-only VAD +/- controls, no checker or iOS build.
--require-native additionally requires actual macOS ditto/codesign operations.
Artificial signatures are structurally signed fixtures, never Apple PASS.
"""
import argparse
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

import minisight_vad_identity_20261117 as v

EVIDENCE = pathlib.Path('/var/minis/shared/openminis/local-reviews/wake-ort-crash-20261117')
SECTION_SHA = '42d2d5b9c82fe81fc9a7650854572b5f7c012311b7b6109bade9844ee9e52558'


def commands(data):
    pos = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<2I', data, pos)
        yield pos, cmd, size
        pos += size


def section_inventory(data):
    records = []
    for pos, cmd, size in commands(data):
        if cmd != v.SEGMENT:
            continue
        for index in range(struct.unpack_from('<I', data, pos + 64)[0]):
            q = pos + 72 + 80 * index
            count, off = struct.unpack_from('<QI', data, q + 40)
            kind = struct.unpack_from('<I', data, q + 64)[0] & 255
            if count and kind not in (1, 12, 18):
                records.append(dict(segment=data[q + 16:q + 32].rstrip(b'\0').decode(),
                                    section=data[q:q + 16].rstrip(b'\0').decode(), size=count,
                                    sha256=v.sha(data[off:off + count])))
    return records


def unsigned_copy(data):
    identity = v.loader_identity(data)
    raw = [data[p:p + s] for p, c, s in commands(data) if c != v.SIGNATURE]
    out = bytearray(data[:identity['immutableEnd']])
    table = b''.join(raw); old_end = 32 + struct.unpack_from('<I', data, 20)[0]
    out[32:old_end] = table + bytes(old_end - 32 - len(table))
    struct.pack_into('<2I', out, 16, len(raw), len(table))
    for pos, cmd, _ in commands(out):
        if cmd == v.SEGMENT and out[pos + 8:pos + 24].rstrip(b'\0') == b'__LINKEDIT':
            off = struct.unpack_from('<Q', out, pos + 40)[0]
            struct.pack_into('<Q', out, pos + 48, len(out) - off)
            struct.pack_into('<Q', out, pos + 32, v.align(len(out) - off, 16384))
    return out


def artificial_sign(data, identifier, extra=0):
    """CodeDirectory v0x20100, SHA256 page hashes, ad-hoc flags, SuperBlob.

    Appends a replacement signature, updates/adds LC_CODE_SIGNATURE, and adjusts
    LINKEDIT file/vmsize. This is not just an unsigned-byte equality test.
    """
    identity = v.loader_identity(data); cutoff = identity['immutableEnd']
    out = bytearray(data[:cutoff]); signature_pos = None
    for pos, cmd, _ in commands(out):
        if cmd == v.SIGNATURE:
            signature_pos = pos
    if signature_pos is None:
        count, size = struct.unpack_from('<2I', out, 16)
        signature_pos = 32 + size
        assert not any(out[signature_pos:signature_pos + 16])
        struct.pack_into('<2I', out, signature_pos, v.SIGNATURE, 16)
        struct.pack_into('<2I', out, 16, count + 1, size + 16)
    ident = identifier.encode() + b'\0'
    slots = (cutoff + 4095) // 4096
    hash_offset = v.align(48 + len(ident), 16)
    cd_length = hash_offset + slots * 32
    total = 20 + cd_length; allocation = v.align(total, 16) + extra
    struct.pack_into('<2I', out, signature_pos + 8, cutoff, allocation)
    for pos, cmd, _ in commands(out):
        if cmd == v.SEGMENT and out[pos + 8:pos + 24].rstrip(b'\0') == b'__LINKEDIT':
            off = struct.unpack_from('<Q', out, pos + 40)[0]
            struct.pack_into('<Q', out, pos + 48, cutoff + allocation - off)
            struct.pack_into('<Q', out, pos + 32, v.align(cutoff + allocation - off, 16384))
    header = struct.pack('>9I4B2I', 0xfade0c02, cd_length, 0x20100, 2, hash_offset, 48,
                         0, slots, cutoff, 32, 2, 0, 12, 0, 0)
    hashes = b''.join(bytes.fromhex(v.sha(out[p:min(p + 4096, cutoff)])) for p in range(0, cutoff, 4096))
    cd = header + ident + bytes(hash_offset - 48 - len(ident)) + hashes
    sig = struct.pack('>5I', 0xfade0cc0, total, 1, 0, 20) + cd
    return out + sig + bytes(allocation - total)


def export_terminal(data, wanted):
    off = next(struct.unpack_from('<I', data, p + 8)[0] for p, c, _ in commands(data) if c == 0x80000033)
    blob = data[off:]; stack = [(0, '')]
    while stack:
        node, name = stack.pop(); length, pos = v.uleb(blob, node, len(blob)); end = pos + length
        if name == wanted:
            _, address_pos = v.uleb(blob, pos, end)
            return off + pos, off + address_pos
        q = end + 1
        for _ in range(blob[end]):
            suffix, q = v.cstr(blob, q, len(blob)); child, q = v.uleb(blob, q, len(blob))
            stack.append((child, name + suffix))
    raise AssertionError('export missing')


def actual_chained_slots(data, wanted='_malloc'):
    """Walk this real image's format6 chain, not unused import-table inventory."""
    base = next(struct.unpack_from('<I', data, p + 8)[0] for p, c, _ in commands(data) if c == 0x80000034)
    _, starts, imports, symbols, count, fmt, compression = struct.unpack_from('<7I', data, base)
    assert fmt == 3 and compression == 0
    names = []
    for index in range(count):
        word, addend = struct.unpack_from('<Qq', data, base + imports + index * 16)
        name, _ = v.cstr(data, base + symbols + (word >> 32), len(data))
        ordinal = word & 65535; ordinal = ordinal - 65536 if ordinal & 32768 else ordinal
        names.append((name, ordinal, addend))
    malloc = []; rebases = []; seen = set()
    starts += base
    segments = [p for p, c, _ in commands(data) if c == v.SEGMENT]
    for seg_index in range(struct.unpack_from('<I', data, starts)[0]):
        relative = struct.unpack_from('<I', data, starts + 4 + 4 * seg_index)[0]
        if not relative:
            continue
        s = starts + relative
        size, page_size, pointer_format, seg_offset, _, pages = struct.unpack_from('<IHHQIH', data, s)
        assert pointer_format == 6
        seg = segments[seg_index]; vm, _, fileoff, filesize = struct.unpack_from('<4Q', data, seg + 24)
        assert vm == seg_offset
        for page in range(pages):
            first = struct.unpack_from('<H', data, s + 22 + 2 * page)[0]
            if first == 65535:
                continue
            assert first < 32768, 'real fixture unexpectedly uses multi-start page'
            rel = page * page_size + first
            while True:
                assert rel + 8 <= filesize and fileoff + rel not in seen
                seen.add(fileoff + rel); word = struct.unpack_from('<Q', data, fileoff + rel)[0]
                if word >> 63:
                    index = word & 0xffffff; name, ordinal, table_addend = names[index]
                    addend = (word >> 24) & 255; addend -= 256 if addend & 128 else 0
                    if name == wanted:
                        malloc.append(dict(fileOffset=fileoff + rel, ordinal=ordinal,
                                           importIndex=index, effectiveAddend=table_addend + addend))
                else:
                    rebases.append(fileoff + rel)
                delta = (word >> 51) & 4095
                if not delta:
                    break
                next_rel = rel + delta * 4
                assert next_rel // page_size == rel // page_size
                rel = next_rel
    assert malloc and rebases
    return malloc, rebases


def native_apple(data, cases, required):
    tools = ('/usr/bin/ditto', '/usr/bin/codesign')
    if sys.platform != 'darwin' or not all(pathlib.Path(p).is_file() for p in tools):
        cases.append(dict(name='apple-copy-codesign-resign', status='SKIP', reason='macOS ditto/codesign unavailable'))
        print('SKIP Apple copy/codesign/re-sign (not PASS)')
        if required:
            print('FAIL native REQUIRED: Apple macOS ditto/codesign unavailable')
        return False
    def layout(value):
        result = dict(fileSha256=v.sha(value), signature=None, linkedit=None, symtabAndDyldCommands={})
        for p, c, n in commands(value):
            if c == v.SIGNATURE:
                result['signature'] = list(struct.unpack_from('<2I', value, p + 8))
            if c == v.SEGMENT and value[p + 8:p + 24].rstrip(b'\0') == b'__LINKEDIT':
                result['linkedit'] = list(struct.unpack_from('<4Q', value, p + 24))
            if c in (2, 0xb, 0x22, 0x80000022, 0x80000033, 0x80000034):
                result['symtabAndDyldCommands'][hex(c)] = value[p:p + n].hex()
        return result
    cases.append(dict(name='apple-input-layout', status='INFO', layout=layout(data)))
    with tempfile.TemporaryDirectory(prefix='b2-vad-apple-') as folder:
        source = pathlib.Path(folder) / 'source'
        copied = pathlib.Path(folder) / 'copied'
        source.write_bytes(data)
        def run(*args):
            return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        run(tools[0], str(source), str(copied))
        print('INFO APPLE VAD stage=ditto-copy layout='+json.dumps(layout(copied.read_bytes()),sort_keys=True))
        copied_id = v.verify_vad_identity(copied.read_bytes())
        cases.append(dict(name='apple-ditto-copy', status='PASS', identity=copied_id,
                          layout=layout(copied.read_bytes())))
        # The Release build gate intentionally runs before the final bundle
        # signing pass, so the input may be unsigned or have a stale signature.
        # Seed a known-valid ad-hoc signature before exercising removal.
        run(tools[1], '--force', '--sign', '-', '--timestamp=none', '--identifier', 'b2.vad.seed', str(copied))
        run(tools[1], '--verify', '--strict', str(copied))
        print('INFO APPLE VAD stage=seed-signed layout='+json.dumps(layout(copied.read_bytes()),sort_keys=True))
        seed_id = v.verify_vad_identity(copied.read_bytes())
        cases.append(dict(name='apple-seed-valid-signature', status='PASS', identity=seed_id,
                          layout=layout(copied.read_bytes())))
        run(tools[1], '--remove-signature', str(copied))
        print('INFO APPLE VAD stage=signature-removed layout='+json.dumps(layout(copied.read_bytes()),sort_keys=True))
        removed_id = v.verify_vad_identity(copied.read_bytes())
        cases.append(dict(name='apple-remove-signature', status='PASS', identity=removed_id,
                          layout=layout(copied.read_bytes())))
        for label in ('b2.vad.adhoc', 'b2.vad.resign.changed.identifier'):
            run(tools[1], '--force', '--sign', '-', '--timestamp=none', '--identifier', label, str(copied))
            run(tools[1], '--verify', '--strict', str(copied))
            signed = v.verify_vad_identity(copied.read_bytes())
            detail = run(tools[1], '-d', '--verbose=0', str(copied))
            identity_line = next((line.strip() for line in (detail.stdout + detail.stderr).splitlines() if 'Identifier=' in line), '')
            assert ('Identifier=' + label) in identity_line, 'unexpected Apple ad-hoc signature identifier'
            assert signed['uuid'] == '67b203bff9a332989482b6e4458f4d49', 'Apple re-sign changed Mach-O UUID'
            cases.append(dict(name=label, status='PASS', signerIdentifier=label, layout=layout(copied.read_bytes())))
    print('PASS Apple VAD copy/remove/re-sign fixed identity: 5 cases')
    return True


def portable_checks(cases):
    """Source gate has no App/VAD dependency: synthetic bytes cannot be baseline."""
    raw = v.BASELINE.read_bytes(); baseline = json.loads(raw)
    assert v.sha(raw) == v.BASELINE_SHA256 and baseline['sourceSha256'] == v.SOURCE_SHA256
    assert baseline['schema'] == v.SCHEMA and baseline['identity']['exports']['count'] == 3115
    assert baseline['identity']['uuid'] == '67b203bff9a332989482b6e4458f4d49'
    cases.append(dict(name='portable-pinned-baseline-selfcheck', status='PASS'))

    def segment(name, address, off, size, sections=b'', protections=3):
        return struct.pack('<2I16s4Q4I', v.SEGMENT, 72 + len(sections), name.encode(),
                           address, v.align(size, 4096), off, size, protections, protections,
                           len(sections) // 80, 0) + sections
    def dylib(name, cmd):
        text = name.encode() + b'\0'; size = v.align(24 + len(text), 8)
        return struct.pack('<6I', cmd, size, 24, 1, 65536, 65536) + text + bytes(size - 24 - len(text))
    section = struct.pack('<16s16s2Q8I', b'__text', b'__TEXT', 1024, 16, 1024, 2, 0, 0, 0x80000400, 0, 0, 0)
    rebase = b'\x11\x21\x08\x51\0'
    bind = b'\x11\x40_malloc\0\x51\x71\0\x60\0\x90\0'
    root = b'\0\1_OrtGetApiBase\0'
    trie = root + bytes([len(root) + 1]) + b'\x03\0\x80\x08\0'
    trie += bytes(v.align(8192 + len(rebase) + len(bind) + len(trie), 16) - 8192 - len(rebase) - len(bind) - len(trie))
    payload = rebase + bind + trie; exportoff = 8192 + len(rebase) + len(bind)
    table = b''.join((segment('__TEXT', 0, 0, 4096, section, 5), segment('__DATA', 4096, 4096, 4096),
                      segment('__LINKEDIT', 8192, 8192, len(payload), protections=1),
                      dylib(baseline['identity']['install']['name'], 0xd), dylib('/usr/lib/libSystem.B.dylib', 0xc),
                      struct.pack('<2I16s', 0x1b, 24, bytes.fromhex(baseline['identity']['uuid'])),
                      struct.pack('<12I', 0x80000022, 48, 8192, len(rebase), 8192 + len(rebase), len(bind),
                                  0, 0, 0, 0, exportoff, len(trie))))
    fixture = bytearray(8192) + payload
    fixture[:32] = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 6, 7, len(table), 0x85, 0)
    fixture[32:32 + len(table)] = table
    fixture[1024:1040] = b'0123456789abcdef'
    struct.pack_into('<Q', fixture, 4104, 1024)
    expected = v.loader_identity(fixture)
    signed = artificial_sign(fixture, 'portable.signature.one')
    grown = artificial_sign(signed, 'portable.signature.two', 32768)
    assert v.sha(signed) != v.sha(grown) and len(signed) != len(grown)
    assert v.loader_identity(signed) == v.loader_identity(grown) == expected
    cases.append(dict(name='portable-structured-signature-replace-grow-and-add-command', status='PASS'))
    assert v.loader_identity(unsigned_copy(signed)) == expected
    cases.append(dict(name='portable-structured-signature-remove', status='PASS'))
    try:
        v.verify_vad_identity(signed)
    except v.IdentityError:
        cases.append(dict(name='portable-synthetic-cannot-self-select-trusted-baseline', status='PASS', expected='REJECT'))
    else:
        raise AssertionError('synthetic fixture became trusted VAD')
    for name, offset in (('code', 1024), ('dependency', fixture.find(b'libSystem')), ('rebase-opcode', 8192),
                         ('bind-opcode', 8192 + len(rebase)), ('fixup-pointer-target', 4104),
                         ('export-target', exportoff + len(root) + 3), ('LINKEDIT-terminal-byte', len(fixture) - 1)):
        bad = bytearray(signed); bad[offset] ^= 1
        try:
            actual = v.loader_identity(bad)
        except v.IdentityError:
            pass
        else:
            assert actual != expected, name
        cases.append(dict(name='portable-immutable-' + name, status='PASS', expected='REJECT'))
    sigcmd = next(p for p, c, _ in commands(signed) if c == v.SIGNATURE)
    bad = bytearray(signed); struct.pack_into('<I', bad, sigcmd + 8, len(fixture) - 16)
    try:
        v.loader_identity(bad)
    except v.IdentityError:
        cases.append(dict(name='portable-signature-cutoff-cannot-hide-LINKEDIT', status='PASS', expected='REJECT'))
    else:
        raise AssertionError('early signature cutoff accepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vad', type=pathlib.Path, help='explicit exact build316 input; missing explicit path fails')
    parser.add_argument('--portable-only', action='store_true', help='source-gate selfcheck without real App/VAD')
    parser.add_argument('--require-native', action='store_true')
    parser.add_argument('--native-apple', action='store_true')
    parser.add_argument('--json-output', type=pathlib.Path)
    args = parser.parse_args()
    cases = []; portable_checks(cases)
    path = args.vad or EVIDENCE / 'RealTimeCutVADCXXLibrary'
    if args.portable_only or not path.is_file():
        assert args.vad is None and not (args.portable_only and args.require_native), 'explicit VAD/native input unavailable'
        cases.extend((dict(name='real-VAD-evidence-matrix', status='SKIP', reason='no VAD input in source gate'),
                      dict(name='apple-copy-codesign-resign', status='SKIP', reason='no real VAD/Apple input')))
        result = dict(status='required_apple_missing' if args.require_native else 'portable_without_real_vad',
                      sourceSha256=None, expectedSourceSha256=v.SOURCE_SHA256,
                      baselineSha256=v.sha(v.BASELINE.read_bytes()), cases=cases)
        if args.json_output:
            args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        print('PASS', sum(c['status'] == 'PASS' for c in cases), 'portable source cases; SKIP real VAD and Apple (not PASS)')
        return 1 if args.require_native else 0
    data = path.read_bytes()
    if args.require_native and (sys.platform != 'darwin' or not pathlib.Path('/usr/bin/ditto').is_file() or not pathlib.Path('/usr/bin/codesign').is_file()):
        # First establish that the requested real input is the pinned identity,
        # then fail quickly without repeating the exhaustive mutation matrix.
        v.verify_vad_identity(data)
        print('FAIL native REQUIRED: Apple macOS ditto/codesign unavailable', file=sys.stderr)
        return 1
    if v.sha(data) != v.SOURCE_SHA256 and (args.require_native or args.native_apple):
        # Package step can supply a copied/unsigned/re-signed old VAD. It must
        # match the FIXED loader baseline before any Apple operation happens.
        v.verify_vad_identity(data)
        cases.append(dict(name='package-input-fixed-loader-identity', status='PASS'))
        cases.append(dict(name='exact-original-evidence-mutation-matrix', status='SKIP', reason='input is a signature variant, not original evidence bytes'))
        apple_ok = native_apple(data, cases, args.require_native)
        result = dict(status='apple_fixture_verified' if apple_ok and sys.platform == 'darwin' else 'required_apple_missing' if not apple_ok else 'local_portable_only',
                      sourceSha256=v.sha(data), expectedSourceSha256=v.SOURCE_SHA256,
                      baselineSha256=v.sha(v.BASELINE.read_bytes()), cases=cases)
        if args.json_output:
            args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        assert v.sha(path.read_bytes()) == v.sha(data)
        print('PASS package input identity; Apple status is separate')
        return 0 if apple_ok else 1
    assert v.sha(data) == v.SOURCE_SHA256, 'forensic controls require the exact original, never an attack-selected baseline'
    def positive(name, value):
        assert v.verify_vad_identity(value) == v.loader_identity(data), name
        cases.append(dict(name=name, status='PASS', expected='ACCEPT'))
    def negative(name, value, preserve_sections=False):
        if preserve_sections:
            assert section_inventory(value) == section_inventory(data), name + ' changed a section'
        try:
            v.verify_vad_identity(value)
        except v.IdentityError as exc:
            cases.append(dict(name=name, status='PASS', expected='REJECT', rejection=str(exc)))
        else:
            raise AssertionError(name + ' falsely accepted')
    def change(offset, mask):
        mutant = bytearray(data); mutant[offset] ^= mask; return mutant

    section_path = v.BASELINE.parent / 'vad-preserved-sections.json'
    assert v.sha(section_path.read_bytes()) == SECTION_SHA
    assert section_inventory(data) == json.loads(section_path.read_text())['sections']
    cases.append(dict(name='original-section-baseline-unchanged-18', status='PASS'))
    with tempfile.TemporaryDirectory(prefix='b2-vad-copy-') as folder:
        copy = pathlib.Path(folder) / 'VAD'
        shutil.copyfile(path, copy)
        positive('real-original-copy', copy.read_bytes())
    identity = v.loader_identity(data)
    assert identity['uuid'] == '67b203bff9a332989482b6e4458f4d49'
    assert identity['versionCommands'] == ['32000000200000000200000000060f0000041200010000000300000001048f04']
    assert identity['exports']['count'] == 3115 and identity['exports']['OrtGetApiBase']['address'] == 10761684
    cases.append(dict(name='real-cpu-UUID-minOS15.6-full-export-target', status='PASS'))
    positive('artificial-signature-replacement', artificial_sign(data, 'b2.synthetic.replace'))
    grown = artificial_sign(data, 'b2.synthetic.grown', 262144)
    assert len(grown) > len(data)
    positive('artificial-signature-growth-file-and-vm-size', grown)
    removed = unsigned_copy(data)
    positive('artificial-signature-removed', removed)
    positive('artificial-add-LC_CODE_SIGNATURE-in-zero-padding', artificial_sign(removed, 'b2.synthetic.add'))
    sigoff = next(struct.unpack_from('<I', data, p + 8)[0] for p, c, _ in commands(data) if c == v.SIGNATURE)
    positive('opaque-signature-byte-change', change(sigoff + 100, 1))

    dependency = data.find(b'/usr/lib/libc++.1.dylib\0'); assert dependency == 2536
    bad = bytearray(data); bad[dependency:dependency + len(b'/usr/lib/libc++.1.dylib\0')] = b'/usr/lib/libBad.1.dylib\0'
    assert len(bad) == len(data)
    negative('real-libc++-to-libBad-LC_LOAD', bad, True)
    malloc, rebases = actual_chained_slots(data)
    bad = data.replace(b'_malloc\0', b'_calloc\0'); assert data.count(b'_malloc\0') == 3
    calloc, _ = actual_chained_slots(bad, '_calloc')
    assert all(slot in calloc for slot in malloc) and malloc[0]['ordinal'] == 4 and malloc[0]['effectiveAddend'] == 0
    negative('real-all-malloc-to-calloc-actual-import-chain', bad, True)
    flag_pos, target_pos = export_terminal(data, '_OrtGetApiBase'); assert target_pos == 17288424
    bad = change(target_pos, 4)
    assert v.loader_identity(bad)['exports']['OrtGetApiBase']['address'] == 10761680
    negative('real-OrtGetApiBase-export-target-minus4', bad, True)
    negative('code-one-byte', change(identity['payloadStart'], 1))
    negative('export-full-flags-weak-bit', change(flag_pos, 4), True)
    loads = [data[p:p + s] for p, c, s in commands(data) if c == 0xc]
    swapped = bytearray(data); table = []; index = 0
    for p, c, s in commands(data):
        if c == 0xc:
            table.append(loads[1] if index == 0 else loads[0] if index == 1 else loads[index]); index += 1
        else:
            table.append(data[p:p + s])
    table = b''.join(table); swapped[32:32 + len(table)] = table
    negative('dependency-order-real-ordinal-topology', swapped, True)
    load = next(p for p, c, _ in commands(data) if c == 0xc)
    negative('dependency-current-version', change(load + 16, 1), True)
    linkcmd = next(p for p, c, _ in commands(data) if c == v.SEGMENT and data[p + 8:p + 24].rstrip(b'\0') == b'__LINKEDIT')
    bad = bytearray(data); old_vm = struct.unpack_from('<Q', bad, linkcmd + 24)[0]
    struct.pack_into('<Q', bad, linkcmd + 24, old_vm + 16384)
    negative('segment-VM-mapping', bad, True)
    link_vm_bad=bytearray(data); link_cmd=next(p for p,c,_ in commands(link_vm_bad) if c==v.SEGMENT and link_vm_bad[p+8:p+24].rstrip(b'\0')==b'__LINKEDIT')
    struct.pack_into('<Q',link_vm_bad,link_cmd+32,700000)
    negative('LINKEDIT-arbitrary-VM-size-not-baseline-or-page-aligned',link_vm_bad,True)
    text = next(p for p, c, _ in commands(data) if c == v.SEGMENT)
    negative('segment-initial-protection', change(text + 60, 2), True)
    build = next(p for p, c, _ in commands(data) if c == 0x32)
    negative('minOS-command-byte', change(build + 12, 1), True)
    negative('actual-chained-pointer-effective-addend', change(malloc[0]['fileOffset'] + 3, 1))
    negative('actual-chained-pointer-next-topology', change(malloc[0]['fileOffset'] + 6, 8))
    negative('actual-rebase-pointer-target', change(rebases[0], 4))
    chain = next(struct.unpack_from('<I', data, p + 8)[0] for p, c, _ in commands(data) if c == 0x80000034)
    imports = struct.unpack_from('<I', data, chain + 8)[0]
    negative('actual-format3-import-table-addend', change(chain + imports + 16 * malloc[0]['importIndex'] + 8, 4), True)
    negative('non-signature-LINKEDIT-final-byte-not-rstrip', change(identity['immutableEnd'] - 1, 1), True)
    sigcmd = next(p for p, c, _ in commands(data) if c == v.SIGNATURE)
    bad = bytearray(data)
    struct.pack_into('<2I', bad, sigcmd + 8, sigoff - 16, len(data) - sigoff + 16)
    negative('signature-cutoff-cannot-hide-16-LINKEDIT-bytes', bad, True)
    symtab = next(p for p, c, _ in commands(data) if c == 2)
    negative('local-strip-table-size-change-not-supported', change(symtab + 12, 1), True)

    # Independent complete terminal semantics, including non-regular exports.
    for label, terminal, expected in (
        ('regular', b'\x00\x20', {'flags': 0, 'address': 32, 'targetVMAddress': 4128}),
        ('weak-TLS', b'\x05\x20', {'flags': 5, 'kind': 1, 'targetVMAddress': 4128}),
        ('absolute', b'\x02\x20', {'flags': 2, 'targetVMAddress': 32}),
        ('reexport', b'\x08\x02_alias\0', {'flags': 8, 'reexportOrdinal': 2, 'importName': '_alias'}),
        ('stub-resolver', b'\x10\x20\x30', {'flags': 16, 'address': 32, 'resolver': 48, 'resolverVMAddress': 4144})):
        blob = b'\0\1_x\0\6' + bytes([len(terminal)]) + terminal + b'\0'
        record = v.decode_exports(blob, 4096)[0]
        assert all(record[k] == value for k, value in expected.items())
        cases.append(dict(name='complete-export-' + label, status='PASS'))
    apple_ok = native_apple(data, cases, args.require_native) if args.native_apple or args.require_native else True
    if not args.native_apple and not args.require_native:
        cases.append(dict(name='apple-copy-codesign-resign', status='SKIP', reason='not requested; no Apple evidence'))
        print('SKIP Apple copy/codesign/re-sign (not PASS)')
    native_requested = args.native_apple or args.require_native
    result_status = ('apple_fixture_verified' if apple_ok else 'required_apple_missing') if native_requested else 'local_portable_only'
    result = dict(status=result_status,
                  sourceSha256=v.sha(data), baselineSha256=v.sha(v.BASELINE.read_bytes()),
                  cases=cases, actualMallocBindings=malloc, actualRebaseCount=len(rebases))
    if args.json_output:
        args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print('PASS', sum(c['status'] == 'PASS' for c in cases), 'portable/actual cases; Apple status is separate')
    assert v.sha(path.read_bytes()) == v.SOURCE_SHA256
    return 0 if apple_ok else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, v.IdentityError, OSError, subprocess.SubprocessError) as exc:
        print('FAIL B2 VAD:', str(exc), file=sys.stderr)
        raise SystemExit(1)
