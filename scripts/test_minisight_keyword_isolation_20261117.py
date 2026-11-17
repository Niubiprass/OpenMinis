#!/usr/bin/env python3
"""Fail-closed Mach-O isolation gate. No inference, audio, device or iOS execution.
Default: portable binary-behaviour fixtures. --artifact [DIR] verifies provenance;
--app APP verifies final embed/bindings. --require-native refuses missing Apple
nm/otool. --native-host-fixture runs ONLY a macOS mock dyld collision experiment.
"""
import argparse, hashlib, json, os, platform, plistlib, re, struct, subprocess
import sys, tempfile
from pathlib import Path
from minisight_vad_identity_20261117 import verify_vad_identity

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT/'src/ios/Packages/MiniSightKeywordRuntime/Artifacts'
INSTALL_NAME = '@rpath/SherpaOnnxC.framework/SherpaOnnxC'
VAD_NAME = '@rpath/RealTimeCutVADCXXLibrary.framework/RealTimeCutVADCXXLibrary'
SCHEMA = 2
API_VERSION = 28
ORT_BINARY_SHA = '45f514c9eeb397c1047af5e00050c8e84ecd37c75c7db12854bdef48e86b2be4'
ORT_HEADER_SHA = 'b69a133143c0da61782b2b02cc8a620d21ac139231fd211719776d10385135c1'
BRIDGE_NAME = '_SherpaOnnxMiniSightRuntimeIsCompatible'
BRIDGE_HEADER = '''#ifndef MINISIGHT_RUNTIME_ISOLATION_H
#define MINISIGHT_RUNTIME_ISOLATION_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Read-only preflight; no model, Ort::Env, singleton, allocation or audio. */
int32_t SherpaOnnxMiniSightRuntimeIsCompatible(void);
#ifdef __cplusplus
}
#endif
#endif
'''
BRIDGE_SOURCE = '''#include "minisight-runtime-isolation.h"
#include "onnxruntime_c_api.h"
#include <string.h>
_Static_assert(ORT_API_VERSION == 28, "Pinned ORT API drift");
__attribute__((visibility("default")))
int32_t SherpaOnnxMiniSightRuntimeIsCompatible(void) {
  const OrtApiBase *base = OrtGetApiBase();
  if (!base || !base->GetApi || !base->GetVersionString) return 0;
  const char *version = base->GetVersionString();
  const OrtApi *api = base->GetApi(ORT_API_VERSION);
  return version && strcmp(version, "1.28.2") == 0 && api && api->CreateEnv;
}
'''
MODULE = ('framework module SherpaOnnxC {\n'
          '  header "sherpa-onnx/c-api/c-api.h"\n'
          '  header "minisight-runtime-isolation.h"\n  export *\n}\n')


def require(ok, message):
    if not ok: raise RuntimeError(message)


def digest(data): return hashlib.sha256(data).hexdigest()


def cstring(data, offset, limit=None):
    limit = len(data) if limit is None else limit
    require(0 <= offset < limit <= len(data), 'bad string offset')
    end = data.find(b'\0', offset, limit)
    require(end >= 0, 'unterminated binary string')
    return data[offset:end].decode('utf-8'), end+1


def leb(data, offset, signed=False):
    value = shift = 0
    mask = (1 << 64)-1
    for _ in range(10):
        require(offset < len(data), 'truncated LEB128')
        b = data[offset]; offset += 1
        slice_value = b & 127
        if shift < 64:
            value = (value | ((slice_value << shift) & mask)) & mask
        shift += 7
        if not b & 128:
            if signed:
                if b & 64 and shift < 64: value = (value | ((~0 << shift) & mask)) & mask
                if value & (1 << 63): value -= 1 << 64
            return value, offset
    raise RuntimeError('oversize LEB128')


class Image:
    """Bounded parser; names are read from nlist/exports/fixups, never grep."""
    def __init__(self, data):
        self.data = data
        require(len(data) >= 32 and data[:4] == b'\xcf\xfa\xed\xfe', 'not thin MH_MAGIC_64 (archive/fat/object masquerade refused)')
        _, self.cpu, self.subtype, self.kind, ncmd, size, self.flags, _ = struct.unpack_from('<8I', data)
        require(32+size <= len(data) and ncmd <= size//8, 'bad Mach-O command bounds')
        self.commands = []; self.dependencies = []; self.install = None
        self.immutable_commands = []; self.uuid = None; self.signature = None; self.segment_names = []
        self.versions = []; self.sections = []; self.segments = []; self.file_sections = []
        self.symbols = []; self.exports = {}; self.imports = {}; self.weak_bind = []
        # Inventory remains compatible; actual writes and final slots are separate.
        self.binding_events = []; self.binding_slots = {}; self.binding_conflicts = set()
        self.chained_table = []
        pos = 32; table = None; dyld = None; trie = None; chains = None
        for _ in range(ncmd):
            cmd, length = struct.unpack_from('<II', data, pos)
            require(length >= 8 and length % 4 == 0 and pos+length <= 32+size, 'malformed Mach-O command')
            self.commands.append(cmd)
            raw_command = bytearray(data[pos:pos+length])
            if cmd == 0x1d:
                require(length == 16 and self.signature is None, 'bad code signature command')
                self.signature = struct.unpack_from('<II',data,pos+8)
                require(sum(self.signature) <= len(data), 'bad code signature range')
            else:
                if cmd == 0x19 and raw_command[8:24].rstrip(b'\0') == b'__LINKEDIT':
                    raw_command[32:40] = bytes(8); raw_command[48:56] = bytes(8)
                self.immutable_commands.append(bytes(raw_command).hex())
            if cmd == 0x1b:
                require(length == 24 and self.uuid is None, 'bad UUID command'); self.uuid = data[pos+8:pos+24].hex()
            if cmd in (0xc, 0x18|0x80000000, 0x1f|0x80000000, 0x20, 0x23|0x80000000, 0xd):
                require(length >= 24, 'short dylib command')
                nameoff = struct.unpack_from('<I', data, pos+8)[0]
                require(24 <= nameoff < length, 'bad dylib name offset')
                name = cstring(data, pos+nameoff, pos+length)[0]
                if cmd == 0xd: require(self.install is None, 'multiple dylib IDs'); self.install = name
                else: self.dependencies.append(name)
            elif cmd == 0x32:
                require(length >= 24, 'short build version')
                p, v = struct.unpack_from('<II', data, pos+8); self.versions.append((p, v))
            elif cmd == 0x25:
                require(length >= 16, 'short iPhoneOS version')
                self.versions.append((2, struct.unpack_from('<I', data, pos+8)[0]))
            elif cmd == 0x19:
                require(length >= 72, 'short segment')
                a, s, o, n = struct.unpack_from('<QQQQ', data, pos+24)
                maxprot,initprot = struct.unpack_from('<II',data,pos+56)
                require(o+n <= len(data), 'segment outside file')
                self.segments.append((a, s, o, n, maxprot, initprot))
                self.segment_names.append(data[pos+8:pos+24].rstrip(b'\0').decode())
                count = struct.unpack_from('<I', data, pos+64)[0]
                require(72+count*80 <= length, 'bad section count')
                for i in range(count):
                    q = pos+72+i*80; address,ss,fo = struct.unpack_from('<QQI',data,q+32)
                    self.sections.append((address,ss,fo))
                    sf = struct.unpack_from('<I',data,q+64)[0] & 255
                    if ss and sf not in (1,12,18):
                        require(fo+ss <= len(data), 'file-backed section outside binary')
                        self.file_sections.append({'segment':data[q+16:q+32].rstrip(b'\0').decode(),
                            'section':data[q:q+16].rstrip(b'\0').decode(),'size':ss,
                            'sha256':digest(data[fo:fo+ss])})
            elif cmd == 2:
                require(table is None and length >= 24, 'bad symtab')
                table = struct.unpack_from('<IIII', data, pos+8)
            elif cmd in (0x22, 0x22|0x80000000):
                require(length >= 48 and dyld is None, 'bad dyld info')
                dyld = struct.unpack_from('<10I', data, pos+8)
            elif cmd == 0x33|0x80000000:
                require(length >= 16 and trie is None, 'bad export command')
                trie = struct.unpack_from('<II', data, pos+8)
            elif cmd == 0x34|0x80000000:
                require(length >= 16 and chains is None, 'bad chained command')
                chains = struct.unpack_from('<II', data, pos+8)
            pos += length
        require(pos == 32+size, 'load command size disagreement')
        if table:
            sy, count, st, sl = table
            require(sy+count*16 <= len(data) and st+sl <= len(data), 'bad symbol table bounds')
            for i in range(count):
                si, ty, se, de, va = struct.unpack_from('<IBBHQ', data, sy+16*i)
                if ty & 0xe0: continue
                require(si < sl, 'bad nlist string index')
                name = cstring(data, st+si, st+sl)[0]
                self.symbols.append({'name':name, 'type':ty, 'section':se, 'desc':de, 'value':va})
                if ty & 1 and ty & 0xe == 0:
                    require(va == 0, 'common symbol in linked image')
                    self.add_import(name, de >> 8, 'nlist')
        if dyld:
            for index, source in ((2,'bind'), (4,'weak'), (6,'lazy')):
                off, length = dyld[index:index+2]
                if length: self.bind_stream(self.slice(off,length), source)
            if trie is None: trie = dyld[8:10]
        if trie and trie[1]: self.export_trie(self.slice(*trie))
        if chains and chains[1]: self.chained_imports(self.slice(*chains))

    def slice(self, offset, size):
        require(0 <= offset <= len(self.data) and 0 <= size <= len(self.data)-offset, 'binary range outside file')
        return self.data[offset:offset+size]

    def read_va(self, address, count):
        for a, s, o, n, _, _ in self.segments:
            if a <= address and address+count <= a+min(s,n): return self.slice(o+address-a, count)
        # Static archive MH_OBJECT uses sections rather than segment VM ranges.
        if self.kind == 1:
            for a, n, o in self.sections:
                if a <= address and address+count <= a+n: return self.slice(o+address-a, count)
        raise RuntimeError('unmapped virtual address '+hex(address))

    def add_import(self, name, ordinal, source):
        if ordinal in (-1,-2,-3): ordinal &= 255
        self.imports.setdefault(name, []).append((ordinal,source))

    @staticmethod
    def signed_bits(value, bits):
        return value-(1 << bits) if value & (1 << (bits-1)) else value

    @staticmethod
    def binding_target(row):
        # Source/weak-import flag do not change an otherwise identical target.
        return tuple(row.get(k) for k in ('width','bindtype','symbol','ordinal','effectiveaddend',
                     'loader_effectiveaddend','auth','key','diversity','addrdiv','rebase_target'))

    def binding_write(self, row):
        """Retain every actual write and the final non-overlapping slot state.
        A conflicting/partially-overlapping history is fail-closed for that
        function, rather than pretending dyld stream order proves resolution.
        System weak-coalescing inventory is not globally forbidden here.
        """
        vmaddress = row['vmaddress']; width = row['width']
        for previous_address in range(vmaddress-7,vmaddress+width):
            previous = self.binding_slots.get(previous_address)
            if previous is None or previous_address+previous['width'] <= vmaddress: continue
            if previous_address != vmaddress or self.binding_target(previous) != self.binding_target(row):
                self.binding_conflicts.update((previous_address,vmaddress))
            del self.binding_slots[previous_address]
        self.binding_events.append(row); self.binding_slots[vmaddress] = row

    def bind_stream(self, data, source):
        require(source in ('bind','weak','lazy'), 'unsupported bind stream source')
        pos = 0; ordinal = 0; name = None; segment = None; offset = 0; kind = 1; addend = 0; flags = 0
        def event():
            require(name and segment is not None and segment < len(self.segments), 'actual bind lacks symbol/segment')
            address,vmsize,fileoff,filesize,maxprot,initprot = self.segments[segment]; width = 8 if kind == 1 else 4
            require(vmsize >= width and offset <= vmsize-width,
                    'actual bind address outside VM segment: symbol='+str(name)+' source='+source+
                    ' segment='+str(segment)+' offset='+hex(offset)+' width='+str(width)+
                    ' vmSize='+hex(vmsize)+' fileSize='+hex(filesize)+' vmAddress='+hex(address+offset))
            if kind == 1:
                require(initprot & 2 and not initprot & 4,
                        'pointer bind segment must be writable/non-executable: symbol='+str(name))
            elif kind in (2,3):
                require(initprot & 4 and not initprot & 2,
                        'text bind segment must be executable/non-writable: symbol='+str(name))
            require(source != 'chained', 'chained bind cannot be zero-fill')
            file_backed = offset+width <= filesize
            self.binding_write({'position':address+offset,'vmaddress':address+offset,
                'file_offset':fileoff+offset,'file_backed':file_backed,'segment':segment,
                'offset':offset,'width':width,'bindtype':kind,'symbolflags':flags,'symbol':name,
                'ordinal':ordinal,'effectiveaddend':addend,'loader_effectiveaddend':addend,
                'tableaddend':0,'pointeraddend':addend,'auth':False,'pointerformat':None,'source':source})
            if source == 'weak': self.weak_bind.append(name)
            else: self.add_import(name,ordinal,source)
        while pos < len(data):
            byte = data[pos]; pos += 1; op, imm = byte & 0xf0, byte & 15
            if op == 0:
                if source != 'lazy': require(not any(data[pos:]), 'data after bind DONE'); break
                ordinal = 0; name = None; segment = None; offset = 0; kind = 1; addend = 0; flags = 0
            elif op == 0x10: ordinal = imm
            elif op == 0x20: ordinal,pos = leb(data,pos)
            elif op == 0x30: ordinal = imm-16 if imm else 0
            elif op == 0x40:
                require(not imm & ~3, 'unsupported bind symbol flags'); flags = imm; name,pos = cstring(data,pos)
            elif op == 0x50:
                require(imm in (1,2,3), 'unsupported bind type'); kind = imm
            elif op == 0x60: addend,pos = leb(data,pos,True)
            elif op == 0x70: segment = imm; offset,pos = leb(data,pos)
            elif op == 0x80:
                skip,pos = leb(data,pos); offset = (offset+skip) & ((1<<64)-1)
            elif op == 0x90: event(); offset = (offset+8) & ((1<<64)-1)
            elif op == 0xa0:
                event(); skip,pos = leb(data,pos); offset = (offset+8+skip) & ((1<<64)-1)
            elif op == 0xb0: event(); offset = (offset+8+imm*8) & ((1<<64)-1)
            elif op == 0xc0:
                count,pos = leb(data,pos); skip,pos = leb(data,pos)
                require(count <= len(self.data)//8, 'unbounded bind repetition')
                for _ in range(count): event(); offset = (offset+8+skip) & ((1<<64)-1)
            else: raise RuntimeError('unsupported/threaded bind opcode '+hex(op))

    def export_trie(self, data):
        visited = set()
        def walk(offset, prefix, depth):
            require(depth <= 256 and offset not in visited and len(visited) < 100000, 'cyclic/oversize export trie')
            visited.add(offset); size,pos = leb(data,offset); end = pos+size
            require(end <= len(data), 'bad export terminal')
            if size:
                flags,q = leb(data,pos)
                require(prefix and prefix not in self.exports, 'duplicate/empty export')
                self.exports[prefix] = flags
                if flags & 8: _,q = leb(data,q); _,q = cstring(data,q,end)
                else:
                    _,q = leb(data,q)
                    if flags & 16: _,q = leb(data,q)
                require(q == end, 'bad export terminal size')
            require(end < len(data), 'missing export children')
            count = data[end]; q = end+1
            for _ in range(count):
                edge,q = cstring(data,q); child,q = leb(data,q)
                require(edge, 'empty export edge'); walk(child,prefix+edge,depth+1)
        walk(0,'',0)

    def chained_imports(self, data):
        require(len(data) >= 28, 'short chained header')
        version,starts,imp,strings,count,fmt,symfmt = struct.unpack_from('<7I',data)
        require(version == 0 and symfmt == 0 and fmt in (1,2,3), 'unsupported chained fixups/import format')
        width = {1:4,2:8,3:16}[fmt]; table = []
        require(28 <= starts <= len(data)-4 and strings <= len(data) and 28 <= imp and imp+count*width <= strings, 'bad chained import bounds')
        for i in range(count):
            pos = imp+i*width
            if fmt in (1,2):
                row = struct.unpack_from('<I',data,pos)[0]; ordinal = row & 255; no = row >> 9
                if ordinal > 0xf0: ordinal -= 256 # Apple permits positive ordinals through 240.
                weak = (row >> 8) & 1
                addend = struct.unpack_from('<i',data,pos+4)[0] if fmt == 2 else 0
            else:
                row = struct.unpack_from('<Q',data,pos)[0]; ordinal = row & 65535; no = row >> 32
                require(not (row >> 17) & 0x7fff, 'nonzero chained import64 reserved bits')
                if ordinal > 0xfff0: ordinal -= 65536
                weak = (row >> 16) & 1; addend = struct.unpack_from('<q',data,pos+8)[0]
            require(strings+no < len(data), 'bad chained symbol name'); name = cstring(data,strings+no)[0]
            entry = {'symbol':name,'ordinal':ordinal,'symbolflags':weak,'tableaddend':addend,'tableformat':fmt}
            table.append(entry); self.chained_table.append(entry)
            self.add_import(name,ordinal,'chained-table') # defensive inventory, NOT actual binding
        number = struct.unpack_from('<I',data,starts)[0]
        require(number <= len(self.segments) and starts+4+number*4 <= len(data), 'bad starts_in_image segments')
        base = next((a-o for a,s,o,n,_,_ in self.segments if o == 0 and n),None)
        require(base is not None, 'chained image has no base segment')
        seen = set()
        for index in range(number):
            relative = struct.unpack_from('<I',data,starts+4+index*4)[0]
            if not relative: continue
            p = starts+relative
            require(p >= starts+4+number*4 and p+22 <= imp, 'short/overlapping chained starts segment')
            size,page,format,delta,maxvalid,pages = struct.unpack_from('<IHHQIH',data,p)
            require(size >= 22+pages*2 and not (size-22) % 2 and p+size <= imp and page in (4096,16384) and
                    format in (1,2,6,9,12) and maxvalid == 0, 'unsupported/bad chained pointer starts')
            address,vmsize,fileoff,filesize,_,_ = self.segments[index]
            require(address-base == delta and pages*page <= vmsize+page-1, 'chain starts mismatch segment VM/page count')
            entrycount = (size-22)//2
            for pi in range(pages):
                first = struct.unpack_from('<H',data,p+22+2*pi)[0]
                if first == 0xffff: continue
                offsets = []
                if first & 0x8000:
                    oi = first & 0x7fff; require(pages <= oi < entrycount, 'bad chained overflow index')
                    while True:
                        require(oi < entrycount, 'unterminated chain multi-start')
                        entry = struct.unpack_from('<H',data,p+22+2*oi)[0]; offsets.append(entry & 0x7fff); oi += 1
                        if entry & 0x8000: break
                else: offsets = [first]
                for initial in offsets:
                    local = pi*page+initial; require(initial < page, 'chain start outside page')
                    while True:
                        require(local+8 <= min(filesize,vmsize) and local//page == pi and
                                (local+7)//page == pi and local%4 == 0,
                                'chained fixup outside file-backed segment/page')
                        location = fileoff+local; require(location not in seen, 'duplicate/cyclic chained fixup'); seen.add(location)
                        pointer = struct.unpack_from('<Q',self.data,location)[0]
                        auth = False; authfields = {}; pointeraddend = loaderaddend = 0
                        if format in (2,6):
                            bound = pointer >> 63; nxt = (pointer >> 51) & 0xfff; ordinal_index = pointer & 0xffffff; stride = 4
                            if bound:
                                require(not (pointer >> 32) & 0x7ffff, 'nonzero PTR64 bind reserved bits')
                                rawaddend = (pointer >> 24) & 255
                                pointeraddend = self.signed_bits(rawaddend,8)
                                # fixup-chains.h says 0..255; dyld-955 Generic64 also
                                # zero-extends this byte. Preserve requested signed8 AND
                                # loader arithmetic: the gate must not accept cancellation
                                # that only reaches entry under one interpretation.
                                loaderaddend = rawaddend
                            else:
                                require(not (pointer >> 44) & 127, 'nonzero PTR64 rebase reserved bits')
                                target = (pointer & ((1 << 36)-1)) | (((pointer >> 36) & 255) << 56)
                                if format == 6: target += base
                        else:
                            bound = (pointer >> 62) & 1; auth = bool(pointer >> 63)
                            nxt = (pointer >> 51) & 0x7ff; stride = 8
                            bits = 24 if format == 12 else 16; ordinal_index = pointer & ((1 << bits)-1)
                            if bound:
                                require(not (pointer >> bits) & ((1 << (32-bits))-1), 'nonzero arm64e bind zero bits')
                                if auth:
                                    authfields = {'diversity':(pointer >> 32) & 65535,
                                                  'addrdiv':bool((pointer >> 48) & 1),'key':(pointer >> 49) & 3}
                                else: pointeraddend = loaderaddend = self.signed_bits((pointer >> 32) & 0x7ffff,19)
                            elif auth: target = base+(pointer & 0xffffffff)
                            else:
                                target = (pointer & ((1 << 43)-1)) | (((pointer >> 43) & 255) << 56)
                                if format != 1: target += base
                        record = {'position':address+local,'vmaddress':address+local,'file_offset':location,
                            'file_backed':True,'segment':index,'offset':local,
                            'width':8,'bindtype':1,'auth':auth,'pointerformat':format,'source':'chained',
                            'rawpointer':pointer,'next':nxt,'stride':stride,**authfields}
                        if bound:
                            require(ordinal_index < len(table), 'chained bound pointer import index out of bounds')
                            entry = table[ordinal_index]
                            record.update(entry,importindex=ordinal_index,pointeraddend=pointeraddend,
                                loader_pointeraddend=loaderaddend,
                                effectiveaddend=entry['tableaddend']+loaderaddend,
                                signed_effectiveaddend=entry['tableaddend']+pointeraddend,
                                loader_effectiveaddend=entry['tableaddend']+loaderaddend)
                            self.add_import(entry['symbol'],entry['ordinal'],'chained')
                        else: record.update(symbol=None,ordinal=None,symbolflags=0,rebase_target=target)
                        self.binding_write(record)
                        if not nxt: break
                        local += nxt*stride
                        require(len(seen) <= len(self.data)//4, 'unbounded chained pointer walk')

    def definition(self, name, private=False):
        rows = [s for s in self.symbols if s['name'] == name and s['type'] & 0xe == 0xe]
        require(len(rows) == 1, 'missing/ambiguous definition '+name)
        if private: require(not rows[0]['type'] & 1, 'internal symbol still global '+name)
        return rows[0]['value']

    def target(self, kind, exact=True):
        require(self.cpu == 0x0100000c and self.subtype & 0xffffff == 0 and self.kind == kind, 'wrong device arm64/filetype; MH_DYLIB required for runtime')
        require(self.versions and all(p == 2 and (not exact or v == 0x000f0500) for p,v in self.versions), 'not device iOS/minOS15.5')
        require(self.flags & 0x80 and not self.flags & 0x100, 'flat namespace / missing MH_TWOLEVEL')


def get_api_range(image, private=True):
    """Pinned ARM64 implementation: (uint32_t)(version-1) >= 28 -> reject.
    Decode actual compare/unsigned branch, not an nm name or version string.
    Fail closed if the fixed machine pattern changes; no full disassembly.
    """
    address = image.definition('__ZN7OrtApis6GetApiEj', private)
    sub,cmp,branch = struct.unpack('<III',image.read_va(address,12))
    require(sub & 0xffc003ff == 0x51000008 and (sub >> 10) & 0xfff == 1,
            'GetApi does not subtract one from w0 into w8')
    require(cmp & 0xffc003ff == 0x7100011f and branch & 0xff00001f == 0x54000002,
            'GetApi missing bounded unsigned rejection branch')
    supported = (cmp >> 10) & 0xfff
    require(supported == API_VERSION, 'GetApi supported version mismatch: '+str(supported))
    return {'minimumApi':1,'maximumApi':supported,'address':address,'first12Sha256':digest(image.read_va(address,12))}


def adrp_add_result(image, address):
    a,b,c = struct.unpack('<III',image.read_va(address,12))
    require(c == 0xd65f03c0, 'unexpected pinned pointer-return RET')
    imm = ((a >> 5) & 0x7ffff) << 2 | ((a >> 29) & 3)
    if imm & (1 << 20): imm -= 1 << 21
    if a & 0x9f00001f == 0x10000000 and b == 0xd503201f:
        return address+imm # Apple ld64 LOH_ARM64_ADRP_ADD -> ADR,NOP relaxation.
    require(a & 0x9f00001f == 0x90000000 and b & 0xffc003ff == 0x91000000,
            'unexpected pinned pointer-return implementation')
    return (address & ~4095)+(imm << 12)+((b >> 10) & 4095)


def framework_gate(image, expected=None):
    image.target(6)
    require(image.install == INSTALL_NAME, 'wrong framework LC_ID_DYLIB')
    require(image.exports and BRIDGE_NAME in image.exports, 'missing public preflight/export trie')
    require(all(re.fullmatch(r'_SherpaOnnx[A-Za-z0-9_]+', n) and f == 0 for n,f in image.exports.items()),
            'ORT/MLAS/C++/weak/reexport/non-function export leaks')
    if expected is not None: require(set(image.exports) == set(expected), 'export set differs from exact C API archive definitions plus bridge')
    public = {s['name'] for s in image.symbols if s['type'] & 1 and s['type'] & 0xe != 0}
    require(public == set(image.exports), 'nlist global definitions disagree with trie/private exports')
    require(not any(s['desc'] & 0x80 for s in image.symbols if s['name'] in public), 'weak global C API definition')
    local_definitions = {s['name'] for s in image.symbols if s['type'] & 0xe != 0}
    require(not any(re.search(r'Ort|ORT|Mlas|MLAS|onnxruntime',n) or n in local_definitions for n in image.weak_bind),
            'private ORT/MLAS/C++ definition participates in weak coalescing (system-only imports may be weak)')
    require(all(d.startswith(('/System/Library/Frameworks/','/usr/lib/')) for d in image.dependencies),
            'runtime links non-system image (VAD/ORT/reexport forbidden)')
    require(0x8000001f not in image.commands and 0x80000023 not in image.commands, 'reexport/upward dependency forbidden')
    for name, bindings in image.imports.items():
        require(not re.search(r'Ort|ORT|Mlas|MLAS|onnxruntime',name), 'ORT/MLAS imported from another image')
        require(all(1 <= ordinal <= len(image.dependencies) for ordinal,_ in bindings), 'special/dynamic_lookup import ordinal')
    base = image.definition('_OrtGetApiBase',True)
    api = image.definition('__ZN7OrtApis6GetApiEj',True)
    record = adrp_add_result(image,base)
    require(struct.unpack('<Q',image.read_va(record,8))[0] == api, 'OrtGetApiBase does not point to own GetApi (or unexpected chained rebases)')
    versionfn = image.definition('__ZN7OrtApis16GetVersionStringEv',True)
    require(struct.unpack('<Q',image.read_va(record+8,8))[0] == versionfn, 'ORT version getter not same-image')
    versionptr = adrp_add_result(image,versionfn)
    require(image.read_va(versionptr,7) == b'1.28.2\0', 'actual ORT runtime version mismatch')
    return get_api_range(image)


def binding_gate(image, symbol, expected):
    bindings = image.imports.get(symbol,[])
    require(bindings and all(1 <= o <= len(image.dependencies) and image.dependencies[o-1] == expected for o,_ in bindings),
            'wrong image/flat binding '+symbol)
    events = [r for r in image.binding_events if r['symbol'] == symbol]
    require(events, 'missing actual dyld bind/fixup '+symbol)
    require(all(r['vmaddress'] not in image.binding_conflicts for r in events),
            'conflicting/overlapping actual binding writes '+symbol)
    final = [r for r in image.binding_slots.values() if r['symbol'] == symbol]
    require(final, 'no final effective dyld binding '+symbol)
    require(all(r.get('file_backed',False) and r['source'] in ('bind','lazy','chained') and r['width'] == 8 and r['bindtype'] == 1 and
                r['effectiveaddend'] == 0 and r.get('signed_effectiveaddend',r['effectiveaddend']) == 0 for r in final),
            'actual binding is not zero-addend pointer/function entry '+symbol)
    require(all(1 <= r['ordinal'] <= len(image.dependencies) and image.dependencies[r['ordinal']-1] == expected for r in final),
            'wrong final image/flat binding '+symbol)
    require(all(not r['auth'] or r['key'] in (0,1) for r in final),
            'authenticated function binding uses a data key '+symbol)


def content_identity(image):
    """Allow codesign only: immutable commands/UUID, all code/data payloads,
    plus pre-signature LINKEDIT (exports/fixups/symbols). Never compare a whole
    __TEXT header containing mutable LC_CODE_SIGNATURE or whole signed SHA.
    """
    require(image.uuid is not None and image.segments, 'linked image UUID/segments missing')
    payloads = []
    for name,(address,vmsize,offset,size,_,_) in zip(image.segment_names,image.segments):
        begin,end = offset,offset+size
        if offset == 0 and size:
            section_offsets = [o for a,n,o in image.sections if o > 0 and offset <= o < end]
            require(section_offsets, 'header-bearing segment has no file section')
            begin = min(section_offsets)
        if name == '__LINKEDIT':
            if image.signature: end = min(end,image.signature[0])
            payload = image.slice(begin,end-begin).rstrip(b'\0')
        else: payload = image.slice(begin,end-begin)
        payloads.append({'name':name,'vmAddress':address,'fileOffset':offset,'payloadStart':begin,
                         'sha256':digest(payload),'payloadBytes':len(payload)})
    return {'cpu':image.cpu,'subtype':image.subtype,'filetype':image.kind,'flags':image.flags,
            'uuid':image.uuid,'commandsSha256':digest(json.dumps(image.immutable_commands,separators=(',',':')).encode()),
            'segments':payloads}


def app_gate(app, artifact=None, announce=True):
    require(app.is_dir() and app.suffix == '.app', '--app must be complete extracted .app directory, not only main binary')
    info = plistlib.loads((app/'Info.plist').read_bytes()); name = info['CFBundleExecutable']
    require(name and '/' not in name and name not in ('.','..'), 'unsafe executable name')
    main = Image((app/name).read_bytes()); main.target(2)
    fw = app/'Frameworks/SherpaOnnxC.framework/SherpaOnnxC'
    require(fw.is_file(), 'private dynamic Sherpa framework not embedded')
    runtime = Image(fw.read_bytes()); framework_gate(runtime)
    for symbol in (BRIDGE_NAME,'_SherpaOnnxCreateKeywordSpotter'):
        binding_gate(main,symbol,INSTALL_NAME)
    for symbol in main.imports:
        require(not re.search(r'Ort|ORT|Mlas|MLAS|onnxruntime',symbol), 'main App ORT binding forbidden (including VAD OrtGetApiBase)')
        if symbol.startswith('_SherpaOnnx'):
            require(symbol in runtime.exports, 'main imports nonexistent Sherpa C API export')
            binding_gate(main,symbol,INSTALL_NAME)
    require(not any(re.search(r'Ort|ORT|Mlas|MLAS|onnxruntime',s['name']) for s in main.symbols
                    if s['type'] & 1 and s['type'] & 0xe != 0), 'ORT statically forced into main App')
    vadpath = app/'Frameworks/RealTimeCutVADCXXLibrary.framework/RealTimeCutVADCXXLibrary'
    require(vadpath.is_file(), 'existing VAD image missing')
    vadbytes = vadpath.read_bytes()
    verify_vad_identity(vadbytes)
    vad = Image(vadbytes); vad.target(6,exact=False) # Preserve existing VAD minOS/bytes, not a rebuild.
    require(vad.install == VAD_NAME and '_OrtGetApiBase' in vad.exports, 'old VAD ORT export/image identity changed')
    vad.definition('_OrtGetApiBase')
    require('_OrtGetApiBase' not in vad.imports and not any(n.startswith('_SherpaOnnx') for n in vad.imports), 'old VAD ORT rebound/replaced')
    require(INSTALL_NAME in main.dependencies and VAD_NAME in main.dependencies, 'main missing both distinct runtime load commands')
    artifact = ARTIFACTS if artifact is None else artifact
    built_path = artifact/'SherpaOnnxC.xcframework/ios-arm64/SherpaOnnxC.framework/SherpaOnnxC'
    require(built_path.is_file(), 'final app requires verified built artifact, not only an embedded filename')
    built = Image(built_path.read_bytes())
    require(content_identity(runtime) == content_identity(built),
            'embedded runtime UUID/immutable commands/code/data/fixups differ from verified build (only signing may change)')
    if announce: print('PASS final app embed + actual Sherpa dyld ordinals + full signature-independent artifact/VAD identity; main imports no ORT')


def archive_members(data):
    if data[:4] == b'\xca\xfe\xba\xbe':
        require(len(data) >= 28 and struct.unpack_from('>I',data,4)[0] == 1, 'unexpected static FAT slices')
        cpu,sub,start,size,_ = struct.unpack_from('>5I',data,8)
        require(cpu == 0x0100000c and sub & 0xffffff == 0 and 28 <= start and start+size <= len(data), 'invalid static arm64 FAT bounds')
        data = data[start:start+size]
    require(data.startswith(b'!<arch>\n'), 'expected original static archive input')
    offset = 8; members = []
    while offset < len(data):
        require(offset+60 <= len(data), 'short ar header')
        header = data[offset:offset+60]; require(header[58:] == b'`\n', 'bad ar header')
        size = int(header[48:58]); name = header[:16].decode().strip(); start = offset+60
        require(start+size <= len(data), 'short ar member'); value = data[start:start+size]
        if name.startswith('#1/'):
            width = int(name[3:]); require(width <= len(value), 'bad ar extended name')
            name = value[:width].rstrip(b'\0').decode(); value = value[width:]
        if name not in ('/','//','/SYM64/') and not name.startswith('__.SYMDEF'):
            image = Image(value); require(image.kind == 1, 'non-MH_OBJECT archive member'); members.append(image)
        offset = start+size+(size & 1)
    require(members, 'empty static input archive')
    return members


def archive_exports(data):
    result = set()
    for image in archive_members(data):
        for s in image.symbols:
            if s['type'] & 1 and s['type'] & 0xe == 0xe and s['name'].startswith('_SherpaOnnx'):
                require(re.fullmatch(r'_SherpaOnnx[A-Za-z0-9_]+',s['name']) and not s['desc'] & 0x80, 'non-strong Sherpa C API definition')
                require(s['name'] not in result, 'duplicate Sherpa C API archive definition'); result.add(s['name'])
    require(result and BRIDGE_NAME not in result, 'unexpected upstream C API export inventory')
    return sorted(result | {BRIDGE_NAME})


def schema_gate(proof):
    require(proof.get('schema') == SCHEMA and proof.get('binaryKind') == 'private-dynamic-framework'
            and proof.get('installName') == INSTALL_NAME and proof.get('isolationProof') == 'Proof/dynamic-isolation.json',
            'old static schema/artifact or missing isolation proof')
    require(proof.get('ortApiVersion') == API_VERSION and proof.get('runtimeTested') is False
            and proof.get('releaseReady') is False, 'API version mismatch / dishonest runtime claim')


def link_map_gate(text, forced, libraries, bridge):
    objects = {}; live = {}; in_symbols = False
    for line in text.splitlines():
        if line.startswith('# Symbols:'): in_symbols = True; continue
        if line.startswith('# Dead Stripped Symbols:'): in_symbols = False
        row = re.match(r'^\[\s*(\d+)\]\s+(.+)$',line)
        if row: objects[int(row[1])] = row[2]
        if in_symbols:
            row = re.match(r'^0x[0-9A-Fa-f]+\s+0x[0-9A-Fa-f]+\s+\[\s*(\d+)\]\s+(\S+)\s*$',line)
            if row: live.setdefault(row[2],[]).append(int(row[1]))
    require(objects and live, 'native link map lacks actual input/symbol records')
    for archive,row in zip(forced[:-1],libraries):
        count = sum(p.startswith(archive+'(') or p == archive for p in objects.values())
        require(count == row['objects'], 'map does not force-load exact archive object closure '+row['name'])
    for symbol,archive in [('_OrtGetApiBase',forced[-1]),('__ZN7OrtApis6GetApiEj',forced[-1]),
                           ('__ZN7OrtApis16GetVersionStringEv',forced[-1]),
                           ('_SherpaOnnxCreateKeywordSpotter',next(p for p in forced if Path(p).name == 'libsherpa-onnx-c-api.a')),
                           (BRIDGE_NAME,bridge)]:
        owners = [objects.get(i,'') for i in live.get(symbol,[])]
        require(len(owners) == 1 and (owners[0] == archive or owners[0].startswith(archive+'(')),
                'native map symbol comes from wrong/missing archive '+symbol)


def isolation_proof_gate(artifact, proof):
    schema_gate(proof); folder = artifact/'Proof'
    capi = (folder/'c-api-input.a').read_bytes(); expected = archive_exports(capi)
    rows = json.loads((folder/'static-library-inputs.json').read_text())
    require(next(r['sha256'] for r in rows if r['name'] == 'libsherpa-onnx-c-api.a') == digest(capi), 'C API export source archive SHA mismatch')
    require((folder/'exported-symbols.txt').read_text() == ''.join(n+'\n' for n in expected), 'export list is not exact archive definitions + bridge')
    require((folder/'minisight-runtime-isolation.c').read_text() == BRIDGE_SOURCE and
            (folder/'minisight-runtime-isolation.h').read_text() == BRIDGE_HEADER, 'bridge implementation drift')
    fw = artifact/'SherpaOnnxC.xcframework/ios-arm64/SherpaOnnxC.framework'
    require((fw/'Headers/minisight-runtime-isolation.h').read_text() == BRIDGE_HEADER and
            (fw/'Modules/module.modulemap').read_text() == MODULE, 'preflight header/module not published')
    api_header = (folder/'onnxruntime_c_api.h').read_bytes()
    require(digest(api_header) == ORT_HEADER_SHA and re.search(rb'^#define ORT_API_VERSION 28$',api_header,re.M), 'pinned ORT API header/version mismatch')
    native = json.loads((folder/'ort-static-input.json').read_text())
    require(native['binarySha256'] == ORT_BINARY_SHA and native['headerSha256'] == ORT_HEADER_SHA and
            native['maximumApi'] == API_VERSION and native['minimumApi'] == 1, 'unproven pinned ORT static input/API dispatch')
    image = Image((fw/'SherpaOnnxC').read_bytes()); actual = framework_gate(image,expected)
    require(json.loads((folder/'signature-independent.json').read_text()) == content_identity(image), 'signature-independent build identity proof missing/drift')
    defined = {line.split()[-1] for line in (folder/'defined-symbols.txt').read_text().splitlines() if line.strip()}
    require(defined == set(expected), 'native global symbol proof leaks/misses exports')
    recorded = json.loads((folder/'dynamic-isolation.json').read_text())
    require(recorded == {'binarySha256':digest(image.data),'installName':INSTALL_NAME,'exports':expected,
                        'getApi':actual,'namespace':'two-level','runtimeTested':False}, 'dynamic isolation machine proof drift')
    link = json.loads((folder/'link.json').read_text())
    command = json.loads(link['frameworkCommand'])
    require('-dynamiclib' in command and '-Wl,-twolevel_namespace' in command and '-Wl,-undefined,error' in command and
            '-Wl,-no_weak_exports' in command and '-Wl,-no_fixup_chains' in command and
            '-Wl,-install_name,'+INSTALL_NAME in command and
            any(a.startswith('-Wl,-exported_symbols_list,') for a in command), 'missing strict private dynamic link options')
    require(not any('flat_namespace' in a or 'dynamic_lookup' in a or 'RealTimeCutVAD' in a for a in command), 'unsafe dynamic link command')
    require(link['privateOrtStaticClosure'] is True and link['run'] is False and link['linkedOrtVersion'] == '1.28.2', 'private ORT linkage proof missing')
    forced = [a.split('-Wl,-force_load,',1)[1] for a in command if a.startswith('-Wl,-force_load,')]
    require(len(forced) == 11 and [Path(a).name for a in forced[:-1]] == [r['name'] for r in rows] and
            Path(forced[-1]).name == 'onnxruntime', 'exact ten Sherpa archives plus private ORT must be force-loaded only inside dylib')
    require((folder/'framework-link-command.json').read_text() == link['frameworkCommand'], 'framework link command proof disagreement')
    bridges = [p for p in command if Path(p).name == 'minisight-runtime-isolation.o']
    require(len(bridges) == 1, 'same-image bridge object missing')
    link_map_gate((folder/'framework-link.map').read_text(),forced,rows,bridges[0])
    probe = Image((folder/'link-probe').read_bytes()); probe.target(2)
    for n in (BRIDGE_NAME,'_SherpaOnnxCreateKeywordSpotter'): binding_gate(probe,n,INSTALL_NAME)
    require(not any(re.search(r'Ort|ORT|Mlas|MLAS|onnxruntime',n) for n in probe.imports), 'link probe incorrectly exposes ORT')
    require(digest(probe.data) == link['probeSha256'], 'link probe bytes drift')
    print('PASS private MH_DYLIB, exact strong C exports, same-image GetApi(28)/1.28.2, probe dyld binding (NOT runtime)')


def native_tools():
    require(platform.system() == 'Darwin', '--require-native needs Apple macOS xcrun/nm/otool; iSH cannot satisfy it')
    for tool in ('clang','nm','otool'):
        subprocess.run(['xcrun','--find',tool],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)


def native_inspect(path):
    native_tools()
    header = subprocess.check_output(['xcrun','otool','-hv',str(path)],text=True)
    require('DYLIB' in header and 'TWOLEVEL' in header, 'native otool rejects dylib/twolevel')
    symbols = subprocess.check_output(['xcrun','nm','-gU',str(path)],text=True)
    names = {line.split()[-1] for line in symbols.splitlines() if line.strip()}
    image = Image(path.read_bytes()); require(names == set(image.exports), 'native nm / parsed exports disagree')
    print('PASS native Apple nm/otool cross-check (link inspection, not runtime)')


def uleb(value):
    result = bytearray()
    while True:
        b = value & 127; value >>= 7; result.append(b | (128 if value else 0))
        if not value: return bytes(result)


def fixture_trie(exports):
    leaves = [uleb(2)+uleb(flags)+uleb(160)+b'\0' for flags in exports.values()]
    # All terminal values fit one byte except address160; use actual length.
    leaves = []
    for flags in exports.values():
        terminal = uleb(flags)+uleb(160); leaves.append(uleb(len(terminal))+terminal+b'\0')
    offsets = [0]*len(leaves)
    for _ in range(10):
        root = b'\0'+bytes([len(exports)])+b''.join(n.encode()+b'\0'+uleb(o) for n,o in zip(exports,offsets))
        pos = len(root); updated = []
        for leaf in leaves: updated.append(pos); pos += len(leaf)
        if updated == offsets: return root+b''.join(leaves)
        offsets = updated
    raise RuntimeError('fixture trie offset convergence')


def fixture_image(kind=6, install=INSTALL_NAME, exports=None, imports=None, api=28, weak=False, minimum=0xf0500,
                  bind_bytes=None, chain_bytes=None, initprot=3, bss_size=0):
    """Structurally-built Mach-O fixture, never generated iOS machine code.
    ARM instructions are fixed integer test data; no compiler/toolchain used.
    """
    base = 0x100000000; start = base+4096
    exports = {BRIDGE_NAME:0,'_SherpaOnnxCreateKeywordSpotter':0} if exports is None else exports
    imports = {} if imports is None else imports
    deps = list(dict.fromkeys(imports.values()))
    def dylib(cmd,name):
        raw = name.encode()+b'\0'; size = (24+len(raw)+7)&~7
        return struct.pack('<6I',cmd,size,24,0,0,0)+raw+b'\0'*(size-24-len(raw))
    commands = [struct.pack('<6I',0x32,24,2,minimum,minimum,0),
                struct.pack('<II16s',0x1b,24,b'fixture-uuid-001')]
    if kind == 6: commands.append(dylib(0xd,install))
    commands += [dylib(0xc,n) for n in deps]
    code = bytearray(max(256,200+8*len(imports)))
    def pointer(offset,target):
        address = start+offset; pages = (target>>12)-(address>>12); imm = pages & ((1<<21)-1)
        adrp = 0x90000000 | ((imm & 3)<<29) | ((imm>>2)<<5)
        add = 0x91000000 | ((target & 4095)<<10)
        struct.pack_into('<3I',code,offset,adrp,add,0xd65f03c0)
    pointer(0,start+128); pointer(64,start+96)
    struct.pack_into('<3I',code,32,0x51000408,0x7100011f|(api<<10),0x540000c2)
    code[96:103] = b'1.28.2\0'; struct.pack_into('<2Q',code,128,start+32,start+64)
    rows = [('_OrtGetApiBase',0xe,1,0,start),('__ZN7OrtApis6GetApiEj',0xe,1,0,start+32),
            ('__ZN7OrtApis16GetVersionStringEv',0xe,1,0,start+64)]
    for n in exports:
        rows = [r for r in rows if r[0] != n]
        rows.append((n,0xf,1,0x80 if weak else 0,start if n == '_OrtGetApiBase' else start+160))
    for n,d in imports.items(): rows.append((n,1,0,(deps.index(d)+1)<<8,0))
    strings = bytearray(b'\0'); symbols = bytearray()
    for n,t,s,d,v in rows:
        index = len(strings); strings.extend(n.encode()+b'\0'); symbols.extend(struct.pack('<IBBHQ',index,t,s,d,v))
    bind = bytearray()
    for index,(n,d) in enumerate(imports.items()):
        ordinal = deps.index(d)+1
        bind.extend(b'\x20'+uleb(ordinal)+b'\x40'+n.encode()+b'\0\x51\x70'+uleb(4096+200+8*index)+b'\x90')
    bind.append(0)
    if bind_bytes is not None: bind = bytearray(bind_bytes)
    trie = fixture_trie(exports) if exports else b''
    symoff = 4096+len(code); stroff = symoff+len(symbols); bindoff = stroff+len(strings); trieoff = bindoff+len(bind)
    chainoff = trieoff+len(trie); total = chainoff+len(chain_bytes or b'')
    linkvm = 4096+symoff+bss_size
    segment = struct.pack('<II16sQQQQIIII',0x19,152,b'__DATA',base,symoff+bss_size,0,symoff,7,initprot,1,0)
    segment += struct.pack('<16s16sQQIIIIIIII',b'__data',b'__DATA',start,len(code),4096,2,0,0,0,0,0,0)
    linkedit = struct.pack('<II16sQQQQIIII',0x19,72,b'__LINKEDIT',base+linkvm,total-symoff,symoff,total-symoff,7,1,0,0)
    flags = 0x80 | (0x8000 if weak else 0)
    commands += [segment,linkedit,struct.pack('<6I',2,24,symoff,len(rows),stroff,len(strings)),
                 struct.pack('<12I',0x80000022,48,0,0,bindoff,len(bind),0,0,0,0,trieoff,len(trie))]
    if chain_bytes is not None: commands.append(struct.pack('<4I',0x80000034,16,chainoff,len(chain_bytes)))
    joined = b''.join(commands)
    header = struct.pack('<8I',0xfeedfacf,0x0100000c,0,kind,len(commands),len(joined),flags,0)+joined
    require(len(header) <= 4096, 'fixture header overflow')
    return header+b'\0'*(4096-len(header))+code+symbols+strings+bind+trie+(chain_bytes or b'')


def portable_fixtures():
    tests = 0
    # Apple MachOFile::read_uleb128 accumulates in uint64_t and truncates
    # bits shifted beyond bit 63, then continues consuming the encoded bytes.
    wrapped, end = leb(bytes([0xa8,0x9f,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x02]),0)
    require(wrapped == 0xfa8 and end == 10, 'ULEB64 did not match Apple loader wrap semantics')
    tests += 1
    def reject(label,action):
        nonlocal tests
        try: action()
        except (RuntimeError,FileNotFoundError,KeyError): tests += 1; return
        raise RuntimeError('negative binary fixture accepted: '+label)
    good = Image(fixture_image()); framework_gate(good); tests += 1
    support_weak = bytearray(fixture_image()); struct.pack_into('<I',support_weak,24,0x8080)
    framework_gate(Image(support_weak)); tests += 1 # Overall flag alone is not a private weak leak.
    relaxed = bytearray(fixture_image())
    for offset,delta in [(0,128),(64,32)]:
        adr = 0x10000000 | ((delta & 3)<<29) | ((delta>>2)<<5)
        struct.pack_into('<2I',relaxed,4096+offset,adr,0xd503201f)
    framework_gate(Image(relaxed)); tests += 1
    signed = bytearray(fixture_image()); ncmd,size = struct.unpack_from('<II',signed,16)
    signed[32+size:32+size+16] = struct.pack('<4I',0x1d,16,len(signed),32)
    struct.pack_into('<II',signed,16,ncmd+1,size+16)
    pos = 32
    for _ in range(ncmd):
        cmd,length = struct.unpack_from('<II',signed,pos)
        if cmd == 0x19 and signed[pos+8:pos+24].rstrip(b'\0') == b'__LINKEDIT':
            for delta in (32,48): struct.pack_into('<Q',signed,pos+delta,struct.unpack_from('<Q',signed,pos+delta)[0]+32)
        pos += length
    signed.extend(b'fixture-signature'.ljust(32,b'\0'))
    require(content_identity(Image(signed)) == content_identity(good), 'codesign-only fixture rejected'); tests += 1
    reject('MH_OBJECT disguised framework',lambda: framework_gate(Image(fixture_image(kind=1))))
    reject('ar disguised dylib',lambda: Image(b'!<arch>\n'+bytes(96)))
    reject('ORT export',lambda: framework_gate(Image(fixture_image(exports={BRIDGE_NAME:0,'_OrtGetApiBase':0}))))
    reject('MLAS export',lambda: framework_gate(Image(fixture_image(exports={BRIDGE_NAME:0,'_MlasGemm':0}))))
    reject('C++ export',lambda: framework_gate(Image(fixture_image(exports={BRIDGE_NAME:0,'__ZN3Ort3EnvC1Ev':0}))))
    reject('weak global',lambda: framework_gate(Image(fixture_image(weak=True))))
    reject('weak export trie',lambda: framework_gate(Image(fixture_image(exports={BRIDGE_NAME:4}))))
    reject('reexport trie',lambda: framework_gate(Image(fixture_image(exports={BRIDGE_NAME:16}))))
    reject('GetApi(28) bound to API20',lambda: framework_gate(Image(fixture_image(api=20))))
    reject('bad dylib ID',lambda: framework_gate(Image(fixture_image(install=VAD_NAME))))
    reject('runtime binds VAD ORT',lambda: framework_gate(Image(fixture_image(imports={'_OrtOther':VAD_NAME}))))
    flat = bytearray(fixture_image()); struct.pack_into('<I',flat,24,0)
    reject('flat namespace',lambda: framework_gate(Image(flat)))
    reject('old schema',lambda: schema_gate({'schema':1}))
    reject('missing proof',lambda: schema_gate({'schema':2,'binaryKind':'private-dynamic-framework','installName':INSTALL_NAME}))
    main = Image(fixture_image(kind=2,exports={},imports={BRIDGE_NAME:INSTALL_NAME,'_SherpaOnnxCreateKeywordSpotter':INSTALL_NAME}))
    binding_gate(main,BRIDGE_NAME,INSTALL_NAME); tests += 1
    bad = Image(fixture_image(kind=2,exports={},imports={BRIDGE_NAME:VAD_NAME}))
    reject('actual Sherpa ordinal points VAD',lambda: binding_gate(bad,BRIDGE_NAME,INSTALL_NAME))
    with tempfile.TemporaryDirectory(prefix='minisight-isolation-fixture-') as td:
        app = Path(td)/'Minis.app'; app.mkdir(); (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'Minis'}))
        imports = {BRIDGE_NAME:INSTALL_NAME,'_SherpaOnnxCreateKeywordSpotter':INSTALL_NAME,'_VadLegacy':VAD_NAME}
        (app/'Minis').write_bytes(fixture_image(kind=2,exports={},imports=imports))
        for n,data in [('SherpaOnnxC',fixture_image()),('RealTimeCutVADCXXLibrary',fixture_image(install=VAD_NAME,exports={'_OrtGetApiBase':0},api=20))]:
            folder = app/'Frameworks'/(n+'.framework'); folder.mkdir(parents=True); (folder/n).write_bytes(data)
        artifact = Path(td)/'artifact'
        built = artifact/'SherpaOnnxC.xcframework/ios-arm64/SherpaOnnxC.framework/SherpaOnnxC'
        built.parent.mkdir(parents=True); built.write_bytes(fixture_image())
        # This App is synthetic: mock only the pinned VAD verifier at its
        # dispatch seam, and still demand all fixture bytes remain unchanged.
        # Real VAD mutation/signing evidence runs in the separate B2 fixture.
        from unittest.mock import patch
        old_vad_bytes = (app/'Frameworks/RealTimeCutVADCXXLibrary.framework/RealTimeCutVADCXXLibrary').read_bytes()
        def synthetic_vad_check(value):
            require(value == old_vad_bytes, 'synthetic VAD bytes changed')
        def check():
            with patch(__name__+'.verify_vad_identity', side_effect=synthetic_vad_check) as verifier:
                app_gate(app,artifact,announce=False)
                verifier.assert_called_once_with(old_vad_bytes)
        check(); tests += 1
        (app/'Minis').write_bytes(fixture_image(kind=2,exports={},imports={**imports,'_OrtGetApiBase':VAD_NAME}))
        reject('main OrtGetApiBase binds VAD',check)
        (app/'Minis').write_bytes(fixture_image(kind=2,exports={},imports=imports))
        embedded = app/'Frameworks/SherpaOnnxC.framework/SherpaOnnxC'
        mutated = bytearray(fixture_image()); mutated[4096+200] ^= 1; embedded.write_bytes(mutated)
        reject('same exports/API12 bytes but altered other code',check)
        embedded.write_bytes(fixture_image())
        old_vad = app/'Frameworks/RealTimeCutVADCXXLibrary.framework/RealTimeCutVADCXXLibrary'
        changed = bytearray(old_vad.read_bytes()); changed[4096+200] ^= 1; old_vad.write_bytes(changed)
        reject('VAD same Ort symbol but altered bytes',check)
        embedded.unlink(); reject('missing dynamic embed',check)
    proto = fixture_image(kind=2,exports={},imports={BRIDGE_NAME:INSTALL_NAME},bind_bytes=b'\0')
    zero = Image(proto); zero.imports = {}
    zero.bind_stream(b'\x11\x40'+BRIDGE_NAME.encode()+b'\0\x70'+uleb(4096+200)+b'\xc0\0\0\0','bind')
    reject('DO_BIND count=0 is not actual binding',lambda: binding_gate(zero,BRIDGE_NAME,INSTALL_NAME))
    out = Image(proto); out.imports = {}
    reject('legacy bind outside VM segment',lambda: out.bind_stream(b'\x11\x40'+BRIDGE_NAME.encode()+b'\0\x70'+uleb(8192+8)+b'\x90\0','bind'))
    bss = bytearray(fixture_image(kind=2,exports={},imports={BRIDGE_NAME:INSTALL_NAME},
                                  bind_bytes=b'\0',bss_size=4096))
    bss_image = Image(bss); bss_image.imports = {}
    bss_stream = b'\x11\x40'+BRIDGE_NAME.encode()+b'\0\x51\x70'+uleb(len(proto)+272)+b'\x90\0'
    bss_image.bind_stream(bss_stream,'bind')
    bss_row = bss_image.binding_events[-1]
    require(not bss_row['file_backed'] and bss_row['offset'] == len(proto)+272 and
            bss_image.binding_slots[bss_row['vmaddress']] == bss_row,
            'legacy BSS bind not represented by real VM slot')
    try: binding_gate(bss_image,BRIDGE_NAME,INSTALL_NAME)
    except RuntimeError as error: require('zero-addend pointer/function entry' in str(error),'BSS bind failed for unrelated reason')
    else: raise RuntimeError('zero-fill slot falsely proves file-backed function entry')
    tests += 1
    print('PASS legacy VM-only BSS bind is inventoried but cannot prove file-backed function gate')
    unused = Image(proto); unused.imports = {}
    no_starts = struct.pack('<7I',0,28,32,36,1,1,0)+struct.pack('<II',0,1)+BRIDGE_NAME.encode()+b'\0'
    unused.chained_imports(no_starts)
    reject('unused chained import without starts cannot bind',lambda: binding_gate(unused,BRIDGE_NAME,INSTALL_NAME))
    chain = bytearray(proto); struct.pack_into('<Q',chain,4096+200,1<<63)
    real = Image(chain); real.imports = {}
    seg = struct.pack('<IHHQIH2H',26,4096,6,0,0,2,0xffff,200)
    starts = struct.pack('<3I',2,12,0)+seg; imp = 28+len(starts)
    fixups = struct.pack('<7I',0,28,imp,imp+4,1,1,0)+starts+struct.pack('<I',1)+BRIDGE_NAME.encode()+b'\0'
    real.chained_imports(fixups); binding_gate(real,BRIDGE_NAME,INSTALL_NAME); tests += 1
    badindex = bytearray(chain); struct.pack_into('<Q',badindex,4096+200,(1<<63)|1)
    reject('actual chain out-of-range import index',lambda: Image(badindex).chained_imports(fixups))
    # B1 checks execute the loader-data parser and gate, never string-search a
    # rejection. The return value is structured local evidence, not native proof.
    b1_results = []
    def b1_reject(label, action, reason):
        nonlocal tests
        try: action()
        except RuntimeError as error:
            require(reason in str(error), 'B1 negative failed for unrelated reason: '+label+': '+str(error))
            tests += 1; b1_results.append({'case':label,'result':'REJECTED','reason':str(error)}); return
        raise RuntimeError('B1 negative binary fixture accepted: '+label)
    def b1_accept(label, image, symbol=BRIDGE_NAME, expected=INSTALL_NAME):
        nonlocal tests
        binding_gate(image,symbol,expected); tests += 1
        b1_results.append({'case':label,'result':'ACCEPTED','slots':[
            r for r in image.binding_slots.values() if r['symbol'] == symbol]})
    def sleb(value):
        result = bytearray()
        while True:
            byte = value & 127; value >>= 7
            done = (value == 0 and not byte & 64) or (value == -1 and byte & 64)
            result.append(byte | (0 if done else 128))
            if done: return bytes(result)
    def legacy(symbol=BRIDGE_NAME, offset=200, addend=0, kind=1, flags=0, ordinal=1, opcode=b'\x90'):
        return (b'\x20'+uleb(ordinal)+bytes([0x40|flags])+symbol.encode()+b'\0'+bytes([0x50|kind,0x70])+
                uleb(4096+offset)+b'\x60'+sleb(addend)+opcode)
    def legacy_image(stream, imports=None, initprot=3):
        return Image(fixture_image(kind=2,exports={},imports={BRIDGE_NAME:INSTALL_NAME} if imports is None else imports,
                                   bind_bytes=stream+b'\0',initprot=initprot))
    def chain_image(format=6, tableformat=1, pointeraddend=0, tableaddend=0, auth=False,
                    key=0, weak=False, ordinal=1, index=0, reserved=0, tablereserved=0,
                    page_entries=(0xffff,200), slots=None, next_value=0, bind_bytes=b'\0', count=1):
        # Official dyld_chained_starts_in_segment and real on-disk payload.
        seg = struct.pack('<IHHQIH',22+2*len(page_entries),4096,format,0,0,2)+struct.pack('<'+'H'*len(page_entries),*page_entries)
        starts = struct.pack('<3I',2,12,0)+seg; imp = 28+len(starts)
        if tableformat in (1,2):
            row = struct.pack('<I',(ordinal & 255)|(int(weak)<<8))
            if tableformat == 2: row += struct.pack('<i',tableaddend)
        else: row = struct.pack('<Qq',(ordinal & 65535)|(int(weak)<<16)|tablereserved,tableaddend)
        payload = struct.pack('<7I',0,28,imp,imp+count*len(row),count,tableformat,0)+starts+row*count+BRIDGE_NAME.encode()+b'\0'
        if format in (2,6): pointer = (1<<63)|(next_value<<51)|((pointeraddend & 255)<<24)|index|reserved
        else:
            pointer = (1<<62)|(int(auth)<<63)|(next_value<<51)|index|reserved
            if auth: pointer |= (0x1234<<32)|(1<<48)|(key<<49)
            else: pointer |= (pointeraddend & 0x7ffff)<<32
        binary = bytearray(fixture_image(kind=2,exports={},imports={BRIDGE_NAME:INSTALL_NAME},bind_bytes=bind_bytes,chain_bytes=payload))
        for offset,value in ({200:pointer} if slots is None else slots).items(): struct.pack_into('<Q',binary,4096+offset,value)
        return Image(binary)
    b1_accept('B1 legacy legal zero-addend function entry',legacy_image(legacy()))
    wrapped_addend = bytes([0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x02])
    wrapped_stream = (b'\x20\x01\x40'+BRIDGE_NAME.encode()+b'\0\x51\x70'+uleb(0xfa8)+
                      b'\x80'+wrapped_addend+b'\x90')
    wrapped_image = legacy_image(wrapped_stream)
    require(wrapped_image.binding_events[-1]['offset'] == 0xfa8 and
            wrapped_image.binding_events[-1]['file_backed'],
            'legacy binding address addition differs from Apple uint64 semantics')
    b1_accept('B1 legacy DO_BIND actual stream wraps address additions as dyld uint64',wrapped_image)
    print('PASS B1 legacy DO_BIND actual stream wraps address additions as dyld uint64')
    for kind in (2,3):
        rx = Image(fixture_image(kind=2,exports={},imports={BRIDGE_NAME:INSTALL_NAME},
                                 bind_bytes=legacy(kind=kind)+b'\0',initprot=5))
        b1_reject('B1 legacy nonpointer bind type '+str(kind),lambda kind=kind,rx=rx: binding_gate(rx,BRIDGE_NAME,INSTALL_NAME),'function entry')
    for value in (4,-4):
        b1_reject('B1 legacy addend '+str(value),lambda value=value: binding_gate(legacy_image(legacy(addend=value)),BRIDGE_NAME,INSTALL_NAME),'function entry')
    both = {BRIDGE_NAME:INSTALL_NAME,'_SherpaOnnxCreateKeywordSpotter':INSTALL_NAME}
    independent = Image(fixture_image(kind=2,exports={},imports=both))
    require(set(independent.binding_slots) == {0x1000010c8,0x1000010d0}, 'fixture imports still alias one VM slot')
    binding_gate(independent,'_SherpaOnnxCreateKeywordSpotter',INSTALL_NAME)
    b1_accept('B1 fixture imports occupy independent legal slots',independent)
    overwrite = legacy_image(legacy()+legacy('_SherpaOnnxCreateKeywordSpotter'),both)
    b1_reject('B1 same-address different function overwrite',lambda: binding_gate(overwrite,BRIDGE_NAME,INSTALL_NAME),'conflicting/overlapping')
    b1_reject('B1 replacement function cannot validate conflicted slot',lambda: binding_gate(overwrite,'_SherpaOnnxCreateKeywordSpotter',INSTALL_NAME),'conflicting/overlapping')
    partial = legacy_image(legacy()+legacy('_SherpaOnnxCreateKeywordSpotter',offset=204,kind=1),both)
    b1_reject('B1 partial-width overlapping function write',lambda: binding_gate(partial,BRIDGE_NAME,INSTALL_NAME),'conflicting/overlapping')
    b1_accept('B1 identical target repeated at same slot',legacy_image(legacy()+legacy()))
    b1_accept('B1 identical target at independent slots',legacy_image(legacy()+legacy(offset=208)))
    lazy = Image(proto); lazy.bind_stream(legacy()+b'\0'+legacy()+b'\0','lazy')
    b1_accept('B1 lazy identical target repeated',lazy)
    b1_reject('B1 legacy zero-count has no effective bind',lambda: binding_gate(legacy_image(legacy(opcode=b'\xc0\0\0')),BRIDGE_NAME,INSTALL_NAME),'missing actual')
    b1_reject('B1 legacy special lookup ordinal',lambda: binding_gate(legacy_image(b'\x3e'+legacy()[2:]),BRIDGE_NAME,INSTALL_NAME),'wrong image')
    system = '/usr/lib/libSystem.B.dylib'
    weak_system = Image(fixture_image(imports={'_malloc':system},bind_bytes=legacy('_malloc',flags=1)+b'\0'))
    b1_accept('B1 normal system weak-import pointer',weak_system,'_malloc',system)
    weak_system.bind_stream(legacy('_malloc',ordinal=0)+b'\0','weak')
    framework_gate(weak_system); tests += 1
    b1_results.append({'case':'B1 system-only weak coalescing remains allowed','result':'ACCEPTED'})
    for format in (1,2,6,9,12):
        for tableformat in (1,2,3):
            b1_accept('B1 chain format '+str(format)+' table '+str(tableformat)+' legal zero',chain_image(format,tableformat))
        for value in (4,-4):
            image = chain_image(format,pointeraddend=value)
            require(image.binding_events[-1]['pointeraddend'] == value, 'incorrect signed pointer addend decoding')
            b1_reject('B1 chain format '+str(format)+' pointer addend '+str(value),lambda image=image: binding_gate(image,BRIDGE_NAME,INSTALL_NAME),'function entry')
        for tableformat,value in ((2,4),(3,4),(2,-2147483648),(3,-9223372036854775808)):
            image = chain_image(format,tableformat,tableaddend=value)
            require(image.chained_table[0]['tableaddend'] == value, 'incorrect signed table addend decoding')
            b1_reject('B1 chain format '+str(format)+' table '+str(tableformat)+' addend '+str(value),lambda image=image: binding_gate(image,BRIDGE_NAME,INSTALL_NAME),'function entry')
    for format in (1,9,12):
        auth_image = chain_image(format,auth=True)
        row = auth_image.binding_events[-1]
        require(row['pointeraddend'] == 0 and row['auth'] and row['diversity'] == 0x1234 and row['addrdiv'] and row['key'] == 0,
                'auth metadata was mistaken for pointer addend')
        b1_accept('B1 arm64e format '+str(format)+' authenticated zero entry',auth_image)
        b1_accept('B1 arm64e format '+str(format)+' signed19 plus table cancellation',chain_image(format,2,pointeraddend=-4,tableaddend=4))
        b1_reject('B1 arm64e format '+str(format)+' auth table addend +4',lambda format=format: binding_gate(chain_image(format,2,tableaddend=4,auth=True),BRIDGE_NAME,INSTALL_NAME),'function entry')
        b1_reject('B1 arm64e format '+str(format)+' function signed with data key',lambda format=format: binding_gate(chain_image(format,auth=True,key=2),BRIDGE_NAME,INSTALL_NAME),'data key')
        zero_bit = 24 if format == 12 else 16
        b1_reject('B1 arm64e format '+str(format)+' bind zero bits nonzero',lambda format=format,zero_bit=zero_bit: chain_image(format,reserved=1<<zero_bit),'zero bits')
        b1_reject('B1 arm64e format '+str(format)+' auth zero bits nonzero',lambda format=format,zero_bit=zero_bit: chain_image(format,auth=True,reserved=1<<zero_bit),'zero bits')
    for format in (2,6):
        b1_reject('B1 PTR64 format '+str(format)+' reserved bind bit',lambda format=format: chain_image(format,reserved=1<<32),'reserved bits')
        b1_reject('B1 PTR64 format '+str(format)+' reserved rebase bit',lambda format=format: chain_image(format,slots={200:1<<44}),'rebase reserved bits')
        b1_reject('B1 PTR64 format '+str(format)+' ambiguous signed8 cancellation',lambda format=format: binding_gate(chain_image(format,2,pointeraddend=-4,tableaddend=4),BRIDGE_NAME,INSTALL_NAME),'function entry')
    b1_reject('B1 table format3 reserved bits',lambda: chain_image(tableformat=3,tablereserved=1<<17),'import64 reserved bits')
    b1_accept('B1 chained weak import retains correct image',chain_image(weak=True))
    b1_reject('B1 chained special lookup ordinal',lambda: binding_gate(chain_image(ordinal=-2),BRIDGE_NAME,INSTALL_NAME),'wrong image')
    high_ordinal = chain_image(ordinal=128)
    require(high_ordinal.chained_table[0]['ordinal'] == 128, 'positive chained ordinal 128 decoded as negative')
    b1_reject('B1 positive ordinal128 still requires existing correct dylib',lambda: binding_gate(high_ordinal,BRIDGE_NAME,INSTALL_NAME),'wrong image')
    b1_reject('B1 chained import index out of range',lambda: chain_image(index=1),'index out of bounds')
    b1_reject('B1 count0 chained table has no bind target',lambda: chain_image(count=0),'index out of bounds')
    b1_reject('B1 no page starts leaves import unused',lambda: binding_gate(chain_image(page_entries=(0xffff,0xffff)),BRIDGE_NAME,INSTALL_NAME),'missing actual')
    b1_reject('B1 chain next escapes segment',lambda: chain_image(next_value=0xfff),'outside file-backed')
    b1_reject('B1 multi-start index out of bounds',lambda: chain_image(page_entries=(0xffff,0x8010)),'overflow index')
    b1_reject('B1 multi-start list unterminated',lambda: chain_image(page_entries=(0xffff,0x8002,200)),'unterminated')
    b1_reject('B1 multi-start duplicate slot',lambda: chain_image(page_entries=(0xffff,0x8002,200,0x8000|200)),'duplicate/cyclic')
    multi = chain_image(page_entries=(0xffff,0x8002,200,0x8000|208),slots={200:1<<63,208:1<<63})
    b1_accept('B1 valid multi-start independent equal targets',multi)
    walked = chain_image(next_value=2,slots={200:(1<<63)|(2<<51),208:1<<63})
    require(set(walked.binding_slots) == {0x1000010c8,0x1000010d0}, 'real chain did not walk next slot')
    b1_accept('B1 real PTR64 stride4 next walk',walked)
    for format in (1,9,12):
        walked = chain_image(format,slots={200:(1<<62)|(1<<51),208:1<<62})
        require(set(walked.binding_slots) == {0x1000010c8,0x1000010d0}, 'arm64e chain did not walk stride8')
        b1_accept('B1 real arm64e format '+str(format)+' stride8 next walk',walked)
    b1_accept('B1 identical legacy plus chained target',chain_image(bind_bytes=legacy()+b'\0'))
    rebase_overwrite = chain_image(bind_bytes=legacy()+b'\0',slots={200:160})
    b1_reject('B1 chained rebase overwrites legacy function slot',lambda: binding_gate(rebase_overwrite,BRIDGE_NAME,INSTALL_NAME),'conflicting/overlapping')
    print('PASS '+str(tests)+' portable Mach-O positive/negative behaviour fixtures (not native execution)')
    return {'portableCases':tests,'b1Cases':b1_results}


def native_host_fixture():
    native_tools()
    with tempfile.TemporaryDirectory(prefix='minisight-host-dyld-') as td:
        w = Path(td)
        header = '''#define ORT_API_VERSION 28
#ifdef __cplusplus
extern "C" {
#endif
typedef struct OrtApi { void (*CreateEnv)(void); } OrtApi;
typedef struct OrtApiBase { const OrtApi *(*GetApi)(unsigned); const char *(*GetVersionString)(void); } OrtApiBase;
const OrtApiBase *OrtGetApiBase(void);
#ifdef __cplusplus
}
#endif
'''
        (w/'onnxruntime_c_api.h').write_text(header)
        (w/'minisight-runtime-isolation.h').write_text(BRIDGE_HEADER)
        (w/'bridge.c').write_text(BRIDGE_SOURCE)
        (w/'mock.cc').write_text('''#include "onnxruntime_c_api.h"
// Same C++ weak inline + function-local singleton symbol names in both images.
namespace Ort { inline unsigned &Global() { static unsigned state = API_LIMIT; return state; } }
static unsigned envCalls = 0;
static void CreateEnv(void) { ++envCalls; }
static const OrtApi api = {CASE == 6 ? nullptr : CreateEnv};
static const OrtApi *GetApi(unsigned v) { return CASE == 1 ? nullptr : (v && v <= Ort::Global() ? &api : nullptr); }
static const char *GetVersion(void) { return CASE == 7 ? nullptr : (CASE == 5 ? "wrong" : VERSION); }
static const OrtApiBase base = {CASE == 3 ? nullptr : GetApi, CASE == 4 ? nullptr : GetVersion};
extern "C" const OrtApiBase *OrtGetApiBase(void) { return CASE == 2 ? nullptr : &base; }
extern "C" unsigned SHERPA_GET(void) { return envCalls ? 999 : Ort::Global(); }
''')
        (w/'exports').write_text(BRIDGE_NAME+'\n_SherpaOnnxMockApiVersion\n')
        (w/'main.c').write_text('''#include "onnxruntime_c_api.h"
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  if (argc != 5) return 90;
  void *a = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL), *b = dlopen(argv[2], RTLD_NOW | RTLD_GLOBAL);
  if (!a || !b) { fprintf(stderr, "%s\\n", dlerror()); return 91; }
  void *vad = atoi(argv[4]) == 0 ? a : b, *own = atoi(argv[4]) == 0 ? b : a;
  unsigned (*old)(void) = dlsym(vad, "LegacyVADApiVersion");
  unsigned (*fresh)(void) = dlsym(own, "SherpaOnnxMockApiVersion");
  int (*check)(void) = dlsym(own, "SherpaOnnxMiniSightRuntimeIsCompatible");
  const OrtApiBase *(*legacyBase)(void) = dlsym(vad, "OrtGetApiBase");
  if (!old || !fresh || !check || !legacyBase) return 92;
  unsigned before = fresh(); int result = check();
  int legacyRejects = legacyBase()->GetApi(28) == 0;
  printf("oldVAD=%u privateState=%u preflight=%d oldReject28=%d initCalls=0\\n", old(), fresh(), result, legacyRejects);
  return !(old() == 20 && fresh() == before && before == (unsigned)atoi(argv[3]+2) && legacyRejects && result == (argv[3][0]-'0'));
}
''')
        def run(command): subprocess.run(command,check=True) # compiler diagnostics preserved on error
        run(['xcrun','clang','-std=c11','-I'+td,'-c',str(w/'bridge.c'),'-o',str(w/'bridge.o')])
        common = ['xcrun','clang++','-std=c++17','-I'+td,'-dynamiclib',str(w/'mock.cc')]
        vad = w/'LegacyVAD.dylib'
        run(common+['-DAPI_LIMIT=20','-DCASE=0','-DVERSION="1.20.0"','-DSHERPA_GET=LegacyVADApiVersion',
                    '-Wl,-install_name,'+str(vad),'-o',str(vad)])
        host = w/'host'
        run(['xcrun','clang','-I'+td,str(w/'main.c'),'-o',str(host)])
        variants = [(0,28,1),(0,20,0)]+[(case,28,0) for case in range(1,8)]
        checks = 0
        for case,limit,expected in variants:
            own = w/('PrivateORT-'+str(case)+'-'+str(limit)+'.dylib')
            run(common+[str(w/'bridge.o'),'-DAPI_LIMIT='+str(limit),'-DCASE='+str(case),'-DVERSION="1.28.2"',
                        '-DSHERPA_GET=SherpaOnnxMockApiVersion','-Wl,-twolevel_namespace','-Wl,-undefined,error','-Wl,-no_weak_exports',
                        '-Wl,-exported_symbols_list,'+str(w/'exports'),'-Wl,-install_name,'+str(own),'-o',str(own)])
            native_inspect(own)
            for reverse in (False,True):
                # Separate process for each order; never reuse a previously loaded dyld image.
                first,second = (own,vad) if reverse else (vad,own)
                output = subprocess.check_output([str(host),str(first),str(second),str(expected)+':'+str(limit),str(int(reverse))],text=True)
                require('preflight='+str(expected) in output, 'native bridge false result')
                checks += 1
        print('PASS '+str(checks)+' macOS host-only real C bridge / C++ singleton / both dyld load-order mocks; no Env/model/audio calls (not iOS/real ORT runtime)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact',nargs='?',const=ARTIFACTS,type=Path)
    parser.add_argument('--app',type=Path)
    parser.add_argument('--require-native',action='store_true')
    parser.add_argument('--native-host-fixture',action='store_true')
    args = parser.parse_args()
    if args.app and args.artifact is None: args.artifact = ARTIFACTS
    if args.require_native: native_tools()
    if not args.artifact and not args.app and not args.native_host_fixture:
        portable_fixtures()
        if not args.require_native: print('SKIP native Apple nm/otool + host dyld: not requested; no iOS/runtime claim')
    if args.artifact:
        import test_minisight_keyword_provenance_20261116 as provenance
        provenance.ARTIFACTS = args.artifact.resolve()
        provenance.static_gate(); provenance.artifact_gate()
        if args.require_native: native_inspect(args.artifact/'SherpaOnnxC.xcframework/ios-arm64/SherpaOnnxC.framework/SherpaOnnxC')
    if args.app:
        app_gate(args.app.resolve(),args.artifact.resolve() if args.artifact else None)
        if args.require_native: native_inspect(args.app/'Frameworks/SherpaOnnxC.framework/SherpaOnnxC')
    if args.native_host_fixture: native_host_fixture()

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print('FAIL keyword isolation: '+str(e),file=sys.stderr); sys.exit(1)
