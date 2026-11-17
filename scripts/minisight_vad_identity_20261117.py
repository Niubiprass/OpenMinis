#!/usr/bin/env python3
"""Pinned VAD loader identity; stdlib only, independent of the isolation Image.

Only LC_CODE_SIGNATURE, zero reserved command padding, and the signature-driven
__LINKEDIT file/vm sizes may differ. No strip/table-reordering exception exists.
All remaining commands and every byte through the *referenced* LINKEDIT end
(including gaps, nlists, exports, fixup opcodes, starts/imports and pointer words)
are locked. Signature dataoff is NOT used to choose the immutable hash cutoff.
Export trie terminals are independently decoded in full, not a symbol inventory.
This checks identity, not signature authenticity; Apple codesign verifies that.
"""
import hashlib
import json
import pathlib
import struct

SOURCE_SHA256 = '664bcfc9be9280db493d3c28fa67ff8beebab63f22787dd992037aebb297410f'
BASELINE_SHA256 = '6bedabc71b689910bb12918561483ee3edd26c74507809c25d7571cb8d310aac'
BASELINE_LINKEDIT_VM_SIZE = 622592
BASELINE = pathlib.Path(__file__).resolve().parent / 'fixtures/minisight_runtime_isolation_20261117/vad-loader-identity.json'
SCHEMA = 'minisight-vad-loader-identity-v1'
SEGMENT = 0x19
SIGNATURE = 0x1d
LINKEDIT_DATA = {0x1e, 0x26, 0x29, 0x2b, 0x2e, 0x80000033, 0x80000034, 0x36, 0x37, 0x38}
DYLIB = {0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023, 0xd}


class IdentityError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise IdentityError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def align(value, page):
    return (value + page - 1) // page * page


def cstr(data, start, end):
    need(0 <= start < end <= len(data), 'string bounds')
    stop = data.find(b'\0', start, end)
    need(stop >= start, 'unterminated string')
    try:
        return data[start:stop].decode('utf-8'), stop + 1
    except UnicodeDecodeError as exc:
        raise IdentityError('non-UTF8 loader string') from exc


def uleb(data, pos, end):
    value = 0
    for index in range(10):
        need(pos < end, 'truncated export ULEB')
        byte = data[pos]; pos += 1
        need(index < 9 or byte < 2, 'overflow export ULEB')
        value |= (byte & 127) << (7 * index)
        if not byte & 128:
            return value, pos
    raise IdentityError('overflow export ULEB')


def decode_exports(blob, image_base):
    """Return every terminal's flags, kind, target, reexport and resolver.

    Addresses are image offsets except EXPORT_SYMBOL_FLAGS_KIND_ABSOLUTE.
    Trie topology and all unvisited bytes are additionally locked by raw hashes.
    """
    records = {}; stack = [(0, '', frozenset())]; visits = 0
    while stack:
        node, name, ancestors = stack.pop(); visits += 1
        need(visits <= 1000000 and node not in ancestors and node < len(blob), 'export trie cycle/bounds')
        need(len(name) <= 16384, 'unbounded export name')
        terminal_size, pos = uleb(blob, node, len(blob))
        end = pos + terminal_size
        need(end < len(blob), 'export terminal bounds')
        if terminal_size:
            need(name and name not in records, 'empty/duplicate export')
            flags, q = uleb(blob, pos, end)
            kind = flags & 3
            need(kind != 3, 'reserved export kind')
            record = {'name': name, 'flags': flags, 'kind': kind}
            if flags & 8:
                ordinal, q = uleb(blob, q, end)
                imported, q = cstr(blob, q, end)
                record.update(reexportOrdinal=ordinal, importName=imported or name)
            else:
                address, q = uleb(blob, q, end)
                record.update(address=address, targetVMAddress=address if kind == 2 else image_base + address)
                if flags & 16:
                    resolver, q = uleb(blob, q, end)
                    record.update(resolver=resolver, resolverVMAddress=image_base + resolver)
            need(q == end, 'unparsed export terminal payload')
            records[name] = record
        count = blob[end]; pos = end + 1
        children = []
        for _ in range(count):
            suffix, pos = cstr(blob, pos, len(blob))
            need(suffix, 'empty export edge')
            child, pos = uleb(blob, pos, len(blob))
            children.append((child, name + suffix, ancestors | {node}))
        stack.extend(reversed(children))
    return [records[name] for name in sorted(records)]


def validate_signature(data, offset, size):
    """Bounded SuperBlob envelope only. Never claim cryptographic validation."""
    need(size >= 12 and offset + size == len(data), 'signature is not the bounded file suffix')
    magic, length, count = struct.unpack_from('>3I', data, offset)
    need(magic == 0xfade0cc0 and 12 + count * 8 <= length <= size, 'bad signature SuperBlob')
    intervals = []; types = set()
    for index in range(count):
        kind, child = struct.unpack_from('>2I', data, offset + 12 + index * 8)
        need(kind not in types and child >= 12 + count * 8 and child + 8 <= length, 'bad signature index')
        types.add(kind)
        magic, child_size = struct.unpack_from('>2I', data, offset + child)
        need(child_size >= 8 and child + child_size <= length, 'bad signature child')
        if kind == 0:
            need(magic == 0xfade0c02, 'signature has no CodeDirectory')
        intervals.append((child, child + child_size))
    intervals.sort()
    need(0 in types and all(a[1] <= b[0] for a, b in zip(intervals, intervals[1:])), 'overlapping signature children')
    # datasize is the whole mutable allocation, not only SuperBlob.length.
    # The genuine signed build316 has nonzero leftover allocation bytes.


def loader_identity(data):
    """Pure bytes -> canonical identity. Not an accepting baseline override API."""
    need(isinstance(data, (bytes, bytearray)), 'expected Mach-O bytes')
    need(len(data) >= 32 and data[:4] == b'\xcf\xfa\xed\xfe', 'expected thin little-endian Mach-O64')
    header = struct.unpack_from('<8I', data)
    _, cpu, subtype, kind, ncmd, size, flags, reserved = header
    need(cpu == 0x100000c and subtype == 0 and kind == 6 and reserved == 0, 'expected original arm64 dylib header')
    need(32 + size <= len(data) and ncmd <= size // 8, 'load command bounds')
    commands = []; segments = []; dependencies = []; versions = []; references = []
    sig = None; uuid = None; install = None; export = None; first_payload = None
    pos = 32
    for _ in range(ncmd):
        need(pos + 8 <= 32 + size, 'truncated command')
        cmd, length = struct.unpack_from('<2I', data, pos)
        need(length >= 8 and length % 8 == 0 and pos + length <= 32 + size, 'command size')
        raw = bytearray(data[pos:pos + length])
        if cmd == SIGNATURE:
            need(length == 16 and sig is None, 'duplicate/malformed signature command')
            sig = struct.unpack_from('<2I', raw, 8)
        else:
            commands.append(raw)
        if cmd == SEGMENT:
            need(length >= 72, 'short segment')
            name = bytes(raw[8:24]).rstrip(b'\0').decode('ascii')
            address, vm_size, offset, file_size, maximum, initial, count, segflags = struct.unpack_from('<4Q4I', raw, 24)
            need(length == 72 + count * 80 and offset + file_size <= len(data) and file_size <= vm_size, 'segment bounds')
            segment = dict(name=name, vmAddress=address, vmSize=vm_size, fileOffset=offset,
                           fileSize=file_size, maxProtection=maximum, initialProtection=initial, flags=segflags)
            segments.append(segment)
            for index in range(count):
                q = 72 + 80 * index
                a, s, f = struct.unpack_from('<QQI', raw, q + 32)
                stype = struct.unpack_from('<I', raw, q + 64)[0] & 255
                need(address <= a and a + s <= address + vm_size, 'section VM bounds')
                if s and stype not in (1, 12, 18):
                    need(offset <= f and f + s <= offset + file_size, 'section file bounds')
                    first_payload = f if first_payload is None else min(first_payload, f)
            if name == '__LINKEDIT':
                need(count == 0, 'LINKEDIT sections unsupported')
        elif cmd in DYLIB:
            need(length >= 24, 'short dylib command')
            nameoff, timestamp, current, compatibility = struct.unpack_from('<4I', raw, 8)
            need(24 <= nameoff < length, 'dylib name offset')
            name, _ = cstr(raw, nameoff, length)
            record = dict(command=cmd, name=name, timestamp=timestamp, currentVersion=current, compatibilityVersion=compatibility)
            if cmd == 0xd:
                need(install is None, 'duplicate install name'); install = record
            else:
                dependencies.append(record)
        elif cmd == 0x1b:
            need(length == 24 and uuid is None, 'UUID command'); uuid = bytes(raw[8:24]).hex()
        elif cmd in (0x24, 0x25, 0x2f, 0x30, 0x32):
            versions.append(bytes(raw).hex())
        pos += length
    need(pos == 32 + size and uuid and install, 'incomplete command table/UUID/install name')
    need(first_payload is not None and pos <= first_payload and not any(data[pos:first_payload]), 'nonzero/resized reserved header padding')
    link = [s for s in segments if s['name'] == '__LINKEDIT']
    need(len(link) == 1 and segments[-1] is link[0], 'expected final unique LINKEDIT')
    link = link[0]
    need(link['fileSize'] + link['fileOffset'] == len(data), 'LINKEDIT must end at EOF')
    link_file_page4 = align(link['fileSize'],4096); link_file_page16 = align(link['fileSize'],16384)
    # The segment header describes the full on-disk __LINKEDIT size, including
    # the current code-signature allocation. Verify that mapping first. The
    # canonical identity below trims only the validated signature suffix and
    # derives its normalized VM size from the immutable referenced payload.
    full_page4=align(link['fileSize'],4096); full_page16=align(link['fileSize'],16384)
    allowed_vm_sizes = {full_page4,full_page16,BASELINE_LINKEDIT_VM_SIZE}
    need(link['vmSize'] in allowed_vm_sizes,
         'LINKEDIT VM size outside aligned/signed-baseline cases: vmSize='+hex(link['vmSize'])+
         ' fileSize='+hex(link['fileSize'])+' aligned4k='+hex(full_page4)+
         ' aligned16k='+hex(full_page16)+' signedBaselineVm='+hex(BASELINE_LINKEDIT_VM_SIZE)+
         ' vmAddr='+hex(link['vmAddress'])+' fileOffset='+hex(link['fileOffset'])+
         ' fileEnd='+hex(link['fileOffset']+link['fileSize'])+' signature='+str(sig)+
         ' bytes='+str(len(data)))
    ranges = sorted((s['fileOffset'], s['fileOffset'] + s['fileSize']) for s in segments if s['fileSize'])
    need(all(a[1] <= b[0] for a, b in zip(ranges, ranges[1:])), 'overlapping file segments')
    vmranges = sorted((s['vmAddress'], s['vmAddress'] + s['vmSize']) for s in segments if s['vmSize'])
    need(all(a[1] <= b[0] for a, b in zip(vmranges, vmranges[1:])), 'overlapping VM segments')

    def reference(label, offset, count):
        if not count:
            return
        need(link['fileOffset'] <= offset and offset + count <= len(data), 'LINKEDIT reference bounds: ' + label)
        references.append(dict(label=label, offset=offset, bytes=count, sha256=sha(data[offset:offset + count])))

    for raw in commands:
        cmd, length = struct.unpack_from('<2I', raw)
        if cmd in LINKEDIT_DATA:
            need(length == 16, 'linkedit_data command size')
            off, count = struct.unpack_from('<2I', raw, 8)
            reference(hex(cmd), off, count)
            if cmd == 0x80000033:
                need(export is None, 'multiple export tries'); export = (off, count)
        elif cmd == 2:
            need(length == 24, 'symtab size')
            off, count, strings, string_bytes = struct.unpack_from('<4I', raw, 8)
            reference('nlist64', off, count * 16); reference('strings', strings, string_bytes)
        elif cmd == 0xb:
            need(length == 80, 'dysymtab size')
            values = struct.unpack_from('<18I', raw, 8)
            for index, width, label in ((6, 8, 'toc'), (8, 56, 'modules64'), (10, 4, 'extrefs'),
                                         (12, 4, 'indirect-symbols'), (14, 8, 'extrel'), (16, 8, 'locrel')):
                reference(label, values[index], values[index + 1] * width)
        elif cmd in (0x22, 0x80000022):
            need(length == 48, 'dyld_info size')
            values = struct.unpack_from('<10I', raw, 8)
            for index, label in enumerate(('rebase', 'bind', 'weak-bind', 'lazy-bind', 'exports')):
                reference(label, values[2 * index], values[2 * index + 1])
            if values[9]:
                candidate = tuple(values[8:10])
                need(export is None or export == candidate, 'disagreeing export commands'); export = candidate
        elif cmd == 0x16:
            need(length == 16, 'twolevel hints size')
            off, count = struct.unpack_from('<2I', raw, 8); reference('twolevel-hints', off, count * 4)
        elif cmd == 0x31:
            need(length == 40, 'note size')
            off, count = struct.unpack_from('<2Q', raw, 24); reference('note', off, count)

    need(references and export and export[1], 'missing referenced LINKEDIT/export trie')
    immutable_end = max(r['offset'] + r['bytes'] for r in references)
    suffix_start = sig[0] if sig and sig[1] else len(data)
    if sig and not sig[1]:
        need(sig[0] == 0, 'nonempty zero-sized signature offset')
    need(immutable_end <= suffix_start <= align(immutable_end, 16), 'signature cutoff hides/adds non-signature LINKEDIT')
    need(not any(data[immutable_end:suffix_start]), 'nonzero signature alignment gap')
    if sig and sig[1]:
        validate_signature(data, *sig)
    need(first_payload < link['fileOffset'] < immutable_end, 'payload ordering')
    for raw in commands:
        if struct.unpack_from('<I', raw)[0] == SEGMENT and bytes(raw[8:24]).rstrip(b'\0') == b'__LINKEDIT':
            struct.pack_into('<Q', raw, 32, align(immutable_end - link['fileOffset'], 16384))
            struct.pack_into('<Q', raw, 48, immutable_end - link['fileOffset'])
    link['fileSize'] = immutable_end - link['fileOffset']
    link['vmSize'] = align(link['fileSize'], 16384)
    exports = decode_exports(data[export[0]:export[0] + export[1]], segments[0]['vmAddress'])
    ort = [entry for entry in exports if entry['name'] == '_OrtGetApiBase']
    need(len(ort) == 1, 'missing/duplicate OrtGetApiBase export')
    return dict(schema=SCHEMA, header=dict(cpu=cpu, subtype=subtype, filetype=kind, flags=flags, reserved=reserved),
                uuid=uuid, install=install, dependencies=dependencies, versionCommands=versions,
                commandsSha256=sha(canonical([bytes(raw).hex() for raw in commands])),
                segments=segments, payloadStart=first_payload, immutableEnd=immutable_end,
                immutablePayloadSha256=sha(data[first_payload:immutable_end]),
                linkeditSha256=sha(data[link['fileOffset']:immutable_end]), linkeditReferences=references,
                exports=dict(count=len(exports), sha256=sha(canonical(exports)), OrtGetApiBase=ort[0]))


def verify_vad_identity(data):
    """Accept only the checked-in, SHA-pinned old VAD identity; return identity.

    No user baseline path or attack-selected identity parameter is accepted.
    Runtime exceptions propagate so app_gate fails closed.
    """
    raw = BASELINE.read_bytes()
    need(sha(raw) == BASELINE_SHA256, 'VAD loader baseline SHA changed')
    record = json.loads(raw)
    need(record.get('schema') == SCHEMA and record.get('sourceSha256') == SOURCE_SHA256, 'VAD baseline provenance changed')
    actual = loader_identity(data)
    need(actual == record['identity'], 'old VAD immutable loader identity changed (only signing allowed)')
    return actual
