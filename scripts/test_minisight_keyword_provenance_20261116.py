#!/usr/bin/env python3
"""Static source gate; --prepare/--finalize are GitHub macOS CI ONLY.
--artifact is fail-closed and portable: no compiler, inference or microphone.
"""
import argparse, hashlib, json, os, platform, plistlib, re, shutil, stat, struct
import subprocess, sys, tarfile, urllib.request, zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'src/ios/Packages/MiniSightKeywordRuntime'
ARTIFACTS = PACKAGE / 'Artifacts'
LICENSES = ROOT / 'src/ios/Resources/MiniSightWake/Licenses'
COMMIT = 'af2d8d81dbfa61c4cea4c568da78f3982edca005'
SOURCE_URL = 'https://codeload.github.com/k2-fsa/sherpa-onnx/tar.gz/' + COMMIT
SOURCE_SHA = 'afcafe3c34bc2f15a363ad791fa1644a69bf0977a58c1b4f617468976c2faeb5'
SOURCE_SIZE = 11932226
ORT_URL = 'https://github.com/csukuangfj/onnxruntime-libs/releases/download/v1.28.2/onnxruntime-ios-static-xcframework-1.28.2.xcframework.zip'
ORT_SHA = '2c2299acbb461d26d4bac4bc85985d40e7c7177ed6072703ae0846d88b0b4599'
ORT_SIZE = 33821118
HEADER_SHA = '5698f38ba09ad2bdf085c56a6cbbd7741acf15e25f4ce5c7097b9702cadf437f'
MODULE = 'framework module SherpaOnnxC {\n  header "sherpa-onnx/c-api/c-api.h"\n  export *\n}\n'
# name, effective CMake owner, version, URL, SHA256. Main CMAKE_MODULE_PATH
# precedes nested decoder/kaldifst modules: Eigen 5.0.1 / OpenFST July, NOT
# decoder's standalone Eigen 3.4.0 / OpenFST April declarations.
DEPS = [
 ('kaldi_native_fbank','source/cmake/kaldi-native-fbank.cmake','1.22.4','https://github.com/csukuangfj/kaldi-native-fbank/archive/refs/tags/v1.22.4.tar.gz','257fea639585ca6ee00860493bb9d7ab32488b8a5407ffe434c1f361ea545fae'),
 ('utf8proc','source/cmake/utf8proc.cmake','2.12.0','https://github.com/JuliaStrings/utf8proc/archive/refs/tags/v2.12.0.tar.gz','f564011d38b2888d583d510b08e69ffa15aa117155db1b9b49ef1dfe1fa25111'),
 ('kaldi_decoder','source/cmake/kaldi-decoder.cmake','0.3.0','https://github.com/k2-fsa/kaldi-decoder/archive/refs/tags/v0.3.0.tar.gz','b9f34cfb4fd3b1344100eead79ef4d37aa15962274b9e3056de345021f76a1b0'),
 ('kissfft','deps/kaldi_native_fbank/cmake/kissfft.cmake','febd4caeed32e33ad8b2e0bb5ea77542c40f18ec','https://github.com/mborgerding/kissfft/archive/febd4caeed32e33ad8b2e0bb5ea77542c40f18ec.zip','497103e664168ebe39580b757adbe616f6cf85a16572af581ca7bc42d0ab13fd'),
 ('kaldifst','deps/kaldi_decoder/cmake/kaldifst.cmake','1.8.0','https://github.com/k2-fsa/kaldifst/archive/refs/tags/v1.8.0.tar.gz','3f247b7e5a2409071202f5e2bc6200060f66728c0a3443c03923ad2723e040b3'),
 ('openfst','source/cmake/openfst.cmake','1.8.5-2026-07-09','https://github.com/csukuangfj/openfst/archive/refs/tags/v1.8.5-2026-07-09.tar.gz','2ff712a32952fcb01d351121a6bc8ccf4fdc6b2aa06ce8df2b3095dedd518c0e'),
 ('eigen','source/cmake/eigen.cmake','5.0.1','https://gitlab.com/libeigen/eigen/-/archive/5.0.1/eigen-5.0.1.tar.gz','e9c326dc8c05cd1e044c71f30f1b2e34a6161a3b6ecf445d56b53ff1669e3dec'),
 ('simple-sentencepiece','source/cmake/simple-sentencepiece.cmake','0.7','https://github.com/pkufool/simple-sentencepiece/archive/refs/tags/v0.7.tar.gz','1748a822060a35baa9f6609f84efc8eb54dc0e74b9ece3d82367b7119fdc75af'),
 ('json','source/cmake/json.cmake','3.12.0','https://github.com/nlohmann/json/archive/refs/tags/v3.12.0.tar.gz','4b92eb0c06d10683f7447ce9406cb97cd4b453be18d7279320f7b2f025c10187'),
]
LIBRARIES = ['libkaldi-native-fbank-core.a','libkissfft-float.a','libsherpa-onnx-c-api.a',
 'libsherpa-onnx-core.a','libsherpa-onnx-fstfar.a','libssentencepiece_core.a',
 'libutf8proc.a','libsherpa-onnx-fst.a','libsherpa-onnx-kaldifst-core.a','libkaldi-decoder-core.a']
FUNCTIONS = ['SherpaOnnxCreateKeywordSpotter','SherpaOnnxDestroyKeywordSpotter',
 'SherpaOnnxCreateKeywordStream','SherpaOnnxDestroyOnlineStream',
 'SherpaOnnxOnlineStreamAcceptWaveform','SherpaOnnxIsKeywordStreamReady',
 'SherpaOnnxDecodeKeywordStream','SherpaOnnxGetKeywordResult',
 'SherpaOnnxDestroyKeywordResult','SherpaOnnxResetKeywordStream']
# Two non-build Go examples in the exact pinned archive point at the author's
# Mac. Never materialize those absolute links on the runner. Preserve the full
# original archive/manifest and disclose the omissions in build proof; no C/C++
# or covered dependency source is omitted or rewritten.
OMITTED_EXAMPLE_LINKS = {
 'scripts/go/_internal/vad-spoken-language-identification/main.go':
 '/Users/fangjun/open-source/sherpa-onnx/go-api-examples/vad-spoken-language-identification/main.go',
 'scripts/go/_internal/vad-spoken-language-identification/run.sh':
 '/Users/fangjun/open-source/sherpa-onnx/go-api-examples/vad-spoken-language-identification/run.sh',
}


def require(ok, message):
    if not ok: raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def ci_only():
    require(platform.system() == 'Darwin' and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('CI') == 'true', 'build inputs/finalization require GitHub macOS CI')


def safe_path(name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts and '\\' not in name, 'unsafe archive path')
    return p


def archive_rows(archive):
    """Original files only; preserves symlinks, rejects devices and traversal."""
    rows = {}; total = 0
    if str(archive).endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                safe_path(m.filename)
                total += m.file_size
                require(total <= 300*1024*1024, 'expanded archive exceeds budget')
                if m.is_dir(): continue
                data = z.read(m)
                if stat.S_ISLNK(m.external_attr >> 16):
                    rows[m.filename] = {'link': data.decode()}
                else: rows[m.filename] = {'sha256': hashlib.sha256(data).hexdigest()}
    else:
        with tarfile.open(archive, 'r:gz') as t:
            for m in t:
                safe_path(m.name)
                total += m.size
                require(total <= 300*1024*1024, 'expanded archive exceeds budget')
                if m.isdir(): continue
                if m.issym(): rows[m.name] = {'link': m.linkname}
                elif m.isfile(): rows[m.name] = {'sha256': hashlib.sha256(t.extractfile(m).read()).hexdigest()}
                else: raise RuntimeError('unsupported source archive member '+m.name)
    require(rows, 'empty source archive')
    roots = {PurePosixPath(p).parts[0] for p in rows}
    require(len(roots) == 1, 'source must have one archive root')
    prefix = next(iter(roots))+'/'
    return {p[len(prefix):]: row for p, row in rows.items()}


def extract_source(archive, dest):
    rows = archive_rows(archive)
    if dest.exists(): shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if str(archive).endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            prefix = next(n for n in z.namelist() if not n.endswith('/')).split('/')[0]+'/'
            for name, row in rows.items():
                if 'link' in row: continue
                p = dest/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(z.read(prefix+name))
    else:
        with tarfile.open(archive) as t:
            prefix = next(m.name for m in t if m.isfile()).split('/')[0]+'/'
            for name, row in rows.items():
                if 'link' in row: continue
                p = dest/name; p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(t.extractfile(prefix+name).read())
                p.chmod(t.getmember(prefix+name).mode & 0o777)
    for name, row in rows.items():
        if 'link' not in row: continue
        p = dest/name; p.parent.mkdir(parents=True, exist_ok=True)
        target = (p.parent/row['link']).resolve()
        if not target.is_relative_to(dest.resolve()):
            require(OMITTED_EXAMPLE_LINKS.get(name) == row['link'] and sha(archive) == SOURCE_SHA,
                    'unsafe source symlink: '+name)
            continue # Pinned, unused Go example only; NEVER follow or rewrite it.
        p.symlink_to(row['link'])
    return rows


def download(url, dest, digest, limit, size=None):
    if dest.is_file() and (size is None or dest.stat().st_size == size) and sha(dest) == digest:
        require(dest.stat().st_size <= limit, 'cached download exceeds budget'); return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix+'.part')
    for attempt in range(3):
        try:
            count = 0; h = hashlib.sha256()
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'MiniSight-pinned-source-CI'}), timeout=90) as r, part.open('wb') as f:
                while True:
                    b = r.read(131072)
                    if not b: break
                    count += len(b); require(count <= limit, 'download exceeds fixed budget')
                    f.write(b); h.update(b)
            require(h.hexdigest() == digest and (size is None or size == count), 'archive SHA/size mismatch')
            part.replace(dest); return
        except Exception:
            part.unlink(missing_ok=True)
            if attempt == 2: raise


def cmake_pin(path, name, url, digest):
    text = path.read_text()
    require(re.search(r'set\('+re.escape(name)+r'_URL\s+"'+re.escape(url)+r'"\)', text), 'CMake URL drift: '+name)
    require(re.search(r'set\('+re.escape(name)+r'_HASH\s+"SHA256='+digest+r'"\)', text), 'CMake hash drift: '+name)
    return sha(path)


def prepare(work):
    ci_only(); work.mkdir(parents=True, exist_ok=True)
    budget = 50*1024*1024
    archive = work/'downloads'/('sherpa-'+COMMIT+'.tar.gz')
    download(SOURCE_URL, archive, SOURCE_SHA, budget, SOURCE_SIZE); budget -= archive.stat().st_size
    trees = {'sherpa': extract_source(archive, work/'source')}
    require(sha(work/'source/sherpa-onnx/c-api/c-api.h') == HEADER_SHA, 'fixed C API header drift')
    records = [{'name':'sherpa','version':'2.0.1','commit':COMMIT,'url':SOURCE_URL,'sha256':SOURCE_SHA,
                'archive':str(archive),'source':str(work/'source')}]
    for name, owner, version, url, digest in DEPS:
        owner_sha = cmake_pin(work/owner, name, url, digest)
        ext = '.zip' if url.endswith('.zip') else '.tar.gz'
        archive = work/'downloads'/(name+'-'+version+ext)
        download(url, archive, digest, budget); budget -= archive.stat().st_size
        trees[name] = extract_source(archive, work/'deps'/name)
        records.append({'name':name,'version':version,'url':url,'sha256':digest,'archive':str(archive),
                        'source':str(work/'deps'/name),'cmakeOwner':owner,'cmakeOwnerSha256':owner_sha})
    ort = work/'downloads/onnxruntime-1.28.2.zip'
    download(ORT_URL, ort, ORT_SHA, ORT_SIZE, ORT_SIZE)
    dest = work/'ort'
    if dest.exists(): shutil.rmtree(dest)
    with zipfile.ZipFile(ort) as z:
        for m in z.infolist():
            safe_path(m.filename); require(not stat.S_ISLNK(m.external_attr >> 16), 'ORT archive symlink')
        require(sum(m.file_size for m in z.infolist()) < 300*1024*1024, 'ORT expansion budget')
        z.extractall(dest)
    frameworks = list(dest.glob('*.xcframework/ios-arm64/onnxruntime.framework'))
    require(len(frameworks) == 1, 'ORT device arm64 framework not unique')
    fw = frameworks[0]
    macho_archive(fw/'onnxruntime', exact=False)
    records.append({'name':'onnxruntime','version':'1.28.2','url':ORT_URL,'sha256':ORT_SHA,
                    'archive':str(ort),'framework':str(fw)})
    write_json(work/'inputs.json', {'records':records,'trees':trees,'sourceBytes':50*1024*1024-budget})
    init = ['set(FETCHCONTENT_FULLY_DISCONNECTED ON CACHE BOOL "" FORCE)',
            'set(JSON_BuildTests OFF CACHE BOOL "" FORCE)', 'set(JSON_Install OFF CACHE BOOL "" FORCE)',
            'set(BUILD_TESTING OFF CACHE BOOL "" FORCE)',
            'set(CMAKE_PROJECT_INCLUDE "'+str(work/'audit.cmake')+'" CACHE FILEPATH "" FORCE)']
    for name, *_ in DEPS:
        init.append('set(FETCHCONTENT_SOURCE_DIR_'+name.upper()+' "'+str(work/'deps'/name)+'" CACHE PATH "" FORCE)')
    (work/'inputs.cmake').write_text('\n'.join(init)+'\n')
    (work/'audit.cmake').write_text('''if(PROJECT_NAME STREQUAL "sherpa-onnx")
  function(minisight_observe_inputs)
    get_directory_property(v DIRECTORY "${Eigen3_SOURCE_DIR}" DEFINITION EIGEN_VERSION_NUMBER)
    get_directory_property(vs DIRECTORY "${Eigen3_SOURCE_DIR}" DEFINITION EIGEN_VERSION_STRING)
    set(MINISIGHT_EIGEN_CMAKE_VERSION_STRING "${vs}" CACHE STRING "Observed upstream version string" FORCE)
    if(NOT v STREQUAL "5.0.1")
      message(FATAL_ERROR "MiniSight actual Eigen version is not 5.0.1: ${v}")
    endif()
    set(MINISIGHT_EIGEN_VERSION "${v}" CACHE STRING "Observed Eigen CMake scope" FORCE)
    set(MINISIGHT_EIGEN_SOURCE_DIR "${Eigen3_SOURCE_DIR}" CACHE PATH "Observed source" FORCE)
    get_target_property(core_links sherpa-onnx-core LINK_LIBRARIES)
    get_target_property(c_api_links sherpa-onnx-c-api LINK_LIBRARIES)
    file(WRITE "${CMAKE_BINARY_DIR}/observed-links.txt" "C_API=${c_api_links}\\nCORE=${core_links}\\n")
  endfunction()
  cmake_language(DEFER CALL minisight_observe_inputs)
endif()
''')
    print('Prepared pinned sources: '+str(50*1024*1024-budget)+' bytes (ORT separate '+str(ORT_SIZE)+')')


def macho_object(data, exact):
    require(len(data) >= 32 and struct.unpack_from('<I', data)[0] == 0xfeedfacf, 'not 64-bit little-endian Mach-O')
    _, cpu, subtype, kind, ncmds, sizeofcmds, *_ = struct.unpack_from('<8I', data)
    require(cpu == 0x0100000c and subtype & 0x00ffffff == 0 and kind in (1, 2), 'not device arm64 Mach-O')
    offset = 32; versions = []
    require(offset+sizeofcmds <= len(data), 'truncated Mach-O commands')
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, offset)
        require(size >= 8 and offset+size <= 32+sizeofcmds, 'bad Mach-O command')
        if cmd == 0x32:
            plat, minimum = struct.unpack_from('<II', data, offset+8)
            require(plat == 2, 'non-iPhoneOS object'); versions.append(minimum)
        elif cmd == 0x25: versions.append(struct.unpack_from('<I', data, offset+8)[0])
        offset += size
    target = (15 << 16) | (5 << 8)
    require(versions and all(v == target if exact else v <= target for v in versions), 'wrong deployment target')
    return len(versions)


def macho_archive(path, exact=True):
    data = Path(path).read_bytes()
    # The pinned ORT device binary is a one-slice FAT wrapper around an ar
    # archive, not a plain ar file. Parse and validate its declared arm64 slice
    # before inspecting every member; never infer simulator/device from a name.
    if data[:4] in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
        wide = data[:4] == b'\xca\xfe\xba\xbf'
        require(len(data) >= 8, 'truncated universal archive')
        architectures = struct.unpack_from('>I', data, 4)[0]
        require(architectures == 1, 'unexpected universal archive slices')
        size = 32 if wide else 20
        require(len(data) >= 8 + size, 'truncated universal archive header')
        if wide:
            cpu, subtype, start, length, alignment, reserved = struct.unpack_from('>IIQQII', data, 8)
        else:
            cpu, subtype, start, length, alignment = struct.unpack_from('>IIIII', data, 8)
        require(cpu == 0x0100000c and subtype & 0x00ffffff == 0,
                'universal archive is not arm64')
        require(start >= 8+size and length > 0 and start+length <= len(data), 'bad universal archive bounds')
        data = data[start:start+length]
    require(data.startswith(b'!<arch>\n'), 'not static archive')
    offset = 8; count = 0
    while offset < len(data):
        require(offset+60 <= len(data), 'truncated ar header')
        header = data[offset:offset+60]; require(header[58:60] == b'`\n', 'invalid ar header')
        size = int(header[48:58]); name = header[:16].decode().strip(); start = offset+60
        member = data[start:start+size]; require(len(member) == size, 'truncated ar member')
        if name.startswith('#1/'):
            width = int(name[3:]); name = member[:width].rstrip(b'\0').decode(); member = member[width:]
        if name not in ('/', '//', '/SYM64/') and not name.startswith('__.SYMDEF'):
            macho_object(member, exact); count += 1
        offset = start+size+(size & 1)
    require(count > 0, 'no Mach-O objects in archive')
    return count


def cache_values(path):
    result = {}
    for line in path.read_text().splitlines():
        m = re.match(r'([^/#][^:]*):[^=]+=(.*)', line)
        if m: result[m[1]] = m[2]
    return result


def bundle_sources(eigen_rows, json_rows):
    for version, digest in [('5.0.1', dict((r[0],r[4]) for r in DEPS)['eigen']),
                            ('3.4.0','8586084f71f9bde545ee7fa6d00288b264a2b7ac3607b974e54d13e7162c1c72')]:
        p = LICENSES/'CorrespondingSource'/('eigen-'+version+'.tar.gz')
        require(p.is_file() and sha(p) == digest, 'bundled complete Eigen source SHA: '+version)
        if version == '5.0.1': require(archive_rows(p) == eigen_rows, 'bundled actual Eigen source differs')
    p = LICENSES/'CorrespondingSource/json-3.12.0-headers-and-license.zip'
    require(p.is_file(), 'bundled JSON covered source missing')
    with zipfile.ZipFile(p) as z:
        files = {m.filename: hashlib.sha256(z.read(m)).hexdigest() for m in z.infolist() if not m.is_dir()}
    for name, row in json_rows.items():
        if not name.startswith('include/nlohmann/'): continue
        require(any(p.endswith('/'+name) or p == name for p, h in files.items() if h == row['sha256']), 'bundled JSON header differs: '+name)
    require('Mozilla Public License' in (LICENSES/'ort-ThirdPartyNotices.txt').read_text(), 'preserve ORT upstream Eigen MPL text')
    require((LICENSES/'Closure/NOTICE.md').is_file(), 'preserve original closure notice')


def finalize(work):
    ci_only(); inputs = json.loads((work/'inputs.json').read_text()); cache = cache_values(work/'build/CMakeCache.txt')
    require(cache.get('CMAKE_SYSTEM_NAME') == 'iOS' and cache.get('CMAKE_OSX_ARCHITECTURES') == 'arm64'
            and cache.get('CMAKE_OSX_DEPLOYMENT_TARGET') == '15.5', 'actual CMake platform drift')
    require(cache.get('MINISIGHT_EIGEN_VERSION') == '5.0.1', 'actual CMake Eigen version not observed')
    eigen_source = Path(cache['MINISIGHT_EIGEN_SOURCE_DIR']).resolve()
    require(eigen_source == (work/'deps/eigen').resolve(), 'Eigen source override not effective')
    for option in ['BUILD_SHARED_LIBS','SHERPA_ONNX_ENABLE_PYTHON','SHERPA_ONNX_ENABLE_BINARY',
                   'SHERPA_ONNX_BUILD_C_API_EXAMPLES','SHERPA_ONNX_ENABLE_TESTS','SHERPA_ONNX_ENABLE_CHECK',
                   'SHERPA_ONNX_ENABLE_TTS','SHERPA_ONNX_ENABLE_SPEAKER_DIARIZATION',
                   'SHERPA_ONNX_ENABLE_JNI','SHERPA_ONNX_ENABLE_PORTAUDIO','SHERPA_ONNX_ENABLE_WEBSOCKET']:
        require(cache.get(option) == 'OFF', 'actual CMake option drift: '+option)
    require(cache.get('SHERPA_ONNX_ENABLE_C_API') == 'ON', 'C API disabled')
    trees = inputs['trees']; proofs = {}; dependency_headers = {}
    deps_text = subprocess.check_output(['ninja','-C',str(work/'build'),'-t','deps'], text=True)
    used = {line.strip() for line in deps_text.splitlines() if line.startswith('    ')}
    for record in inputs['records']:
        name = record['name']
        if name == 'onnxruntime': continue
        src = Path(record['source']); original = trees[name]; headers = {}; omitted = {}
        for rel, row in original.items():
            p = src/rel
            if name == 'sherpa' and row.get('link') == OMITTED_EXAMPLE_LINKS.get(rel) and 'link' in row:
                require(not p.exists() and not p.is_symlink(), 'omitted example was materialized: '+rel)
                omitted[rel] = row['link']
            elif 'link' in row: require(p.is_symlink() and os.readlink(p) == row['link'], 'modified source link: '+name+'/'+rel)
            else:
                require(p.is_file() and sha(p) == row['sha256'], 'modified original source: '+name+'/'+rel)
                if p.suffix in ('.h','.hpp','.hxx') or rel.startswith('Eigen/'):
                    headers[rel] = row['sha256']
        actual = {}
        for value in used:
            p = Path(value)
            if not p.is_absolute(): p = work/'build'/p
            if not p.resolve().is_relative_to(src.resolve()) or not p.is_file(): continue
            rel = str(p.resolve().relative_to(src.resolve()))
            require(rel in original and original[rel].get('sha256') == sha(p), 'unproven compiled dependency header: '+rel)
            actual[rel] = sha(p)
        proofs[name] = {'source':str(src),'rootSha256':hashlib.sha256(canonical(original)).hexdigest(),
                        'unmodifiedOriginalFiles':True,'originalFileCount':len(original),
                        'omittedNonBuildSymlinks':omitted,
                        'headersSha256':headers,'compiledHeadersSha256':actual}
        dependency_headers[name] = actual
    require(dependency_headers['eigen'] and dependency_headers['json'], 'Ninja actual Eigen/JSON header trace missing')
    bundle_sources(trees['eigen'], trees['json'])
    binary = ARTIFACTS/'SherpaOnnxC.xcframework/ios-arm64/SherpaOnnxC.framework/SherpaOnnxC'
    require(binary.is_file(), 'built framework binary missing')
    count = macho_archive(binary)
    symbols = subprocess.check_output(['xcrun','nm','-gU',str(binary)], text=True)
    for name in FUNCTIONS: require(re.search(r'\b_'+name+r'$', symbols, re.M), 'missing required C API '+name)
    probe = work/'link-probe'; macho_object(probe.read_bytes(), exact=True)
    commands = (work/'build/compile_commands.json').read_text()
    for rel in OMITTED_EXAMPLE_LINKS:
        require(rel not in commands, 'omitted example selected as a build input: '+rel)
    require(str(eigen_source) in commands and 'SHERPA_ONNX_ENABLE_TTS=0' in commands
            and 'SHERPA_ONNX_ENABLE_SPEAKER_DIARIZATION=0' in commands, 'compile flags/headers not effective')
    proof_dir = ARTIFACTS/'Proof'; proof_dir.mkdir(parents=True, exist_ok=True)
    sources = ARTIFACTS/'CorrespondingSource'; sources.mkdir(parents=True, exist_ok=True)
    native_inputs = ARTIFACTS/'Inputs'; native_inputs.mkdir(parents=True, exist_ok=True)
    public_records = []
    for record in inputs['records']:
        copy = dict(record); archive = Path(copy.pop('archive'))
        target = (native_inputs if record['name'] == 'onnxruntime' else sources)/archive.name
        shutil.copy2(archive, target); copy['archive'] = str(target.relative_to(ARTIFACTS)); public_records.append(copy)
    library_proof = [{'name':name, 'sha256':sha(work/'build/lib'/name),
                      'objects':macho_archive(work/'build/lib'/name)} for name in LIBRARIES]
    require(sum(row['objects'] for row in library_proof) == count, 'merged static object closure differs')
    write_json(proof_dir/'static-library-inputs.json', library_proof)
    write_json(proof_dir/'source-trees.json', trees); write_json(proof_dir/'headers.json', proofs)
    for name, path in [('CMakeCache.txt',work/'build/CMakeCache.txt'),('compile_commands.json',work/'build/compile_commands.json'),
                       ('observed-links.txt',work/'build/observed-links.txt'),('cmake-trace.jsonl',work/'cmake-trace.jsonl')]:
        shutil.copy2(path, proof_dir/name)
    (proof_dir/'defined-symbols.txt').write_text(symbols)
    write_json(proof_dir/'link.json', {'forceLoadAllSherpaObjects':True,'linkedOrtVersion':'1.28.2',
                'probeSha256':sha(probe),'run':False,'command':(work/'link-command.json').read_text()})
    files = {str(p.relative_to(ARTIFACTS)):sha(p) for p in ARTIFACTS.rglob('*') if p.is_file() and p.name != 'provenance.json'}
    proof = {'schema':1,'status':'ci_build_verified','correspondenceVerified':True,
        'runtimeTested':False,'releaseReady':False,'buildIdentity':(work/'identity.json').read_text(),
        'sourceCommit':COMMIT,'sourceArchiveSha256':SOURCE_SHA,'ortArchiveSha256':ORT_SHA,
        'sourceBytes':inputs['sourceBytes'],'eigenVersion':cache['MINISIGHT_EIGEN_VERSION'],
        'eigenCmakeVersionString':cache['MINISIGHT_EIGEN_CMAKE_VERSION_STRING'],'eigenSource':str(eigen_source),
        'originalSourceRootSha256':proofs['sherpa']['rootSha256'],'cApiHeaderSha256':HEADER_SHA,
        'target':{'platform':'iOS','architecture':'arm64','minimumOS':'15.5','objects':count},
        'staticLibraries':LIBRARIES,'inputs':public_records,'filesSha256':files}
    artifact_gate(candidate=proof)
    write_json(ARTIFACTS/'provenance.json', proof) # Commit ready evidence LAST, after every gate.
    print('PASS CI native build/link and pristine source/header correspondence; runtime/release remain unverified')


def artifact_gate(identity=None, candidate=None):
    p = ARTIFACTS/'provenance.json'
    if candidate is None: require(p.is_file(), 'CI artifact/provenance missing: run controlled rebuild first')
    proof = candidate if candidate is not None else json.loads(p.read_text())
    require(proof.get('schema') == 1 and proof.get('status') == 'ci_build_verified'
            and proof.get('correspondenceVerified') is True, 'unverified build provenance')
    require(proof['sourceCommit'] == COMMIT and proof['sourceArchiveSha256'] == SOURCE_SHA
            and proof['ortArchiveSha256'] == ORT_SHA and proof['eigenVersion'] == '5.0.1', 'artifact pin drift')
    require(proof['staticLibraries'] == LIBRARIES and proof['cApiHeaderSha256'] == HEADER_SHA, 'archive/header drift')
    require(proof['runtimeTested'] is False and proof['releaseReady'] is False, 'static build cannot prove runtime/release')
    if identity is not None: require(proof['buildIdentity'] == identity.read_text(), 'cache identity changed')
    files = {str(p.relative_to(ARTIFACTS)):sha(p) for p in ARTIFACTS.rglob('*') if p.is_file() and p.name != 'provenance.json'}
    require(files == proof['filesSha256'], 'artifact or proof file SHA mismatch')
    xc = ARTIFACTS/'SherpaOnnxC.xcframework'
    info = plistlib.loads((xc/'Info.plist').read_bytes())['AvailableLibraries']
    require(len(info) == 1 and info[0]['LibraryIdentifier'] == 'ios-arm64'
            and info[0]['SupportedArchitectures'] == ['arm64'] and info[0]['SupportedPlatform'] == 'ios'
            and not info[0].get('SupportedPlatformVariant'), 'device-only XCFramework layout drift')
    fw = xc/'ios-arm64/SherpaOnnxC.framework'
    require((fw/'Modules/module.modulemap').read_text() == MODULE, 'SherpaOnnxC module changed')
    require(sha(fw/'Headers/sherpa-onnx/c-api/c-api.h') == HEADER_SHA, 'public C API header changed')
    require(plistlib.loads((fw/'Info.plist').read_bytes())['MinimumOSVersion'] == '15.5', 'framework minOS drift')
    require(macho_archive(fw/'SherpaOnnxC') == proof['target']['objects'], 'native object count drift')
    trees = json.loads((ARTIFACTS/'Proof/source-trees.json').read_text())
    headers = json.loads((ARTIFACTS/'Proof/headers.json').read_text())
    expected = {'sherpa':SOURCE_SHA,'onnxruntime':ORT_SHA, **{r[0]:r[4] for r in DEPS}}
    require({r['name'] for r in proof['inputs']} == set(expected), 'input inventory drift')
    for row in proof['inputs']:
        name = row['name']; require(row['sha256'] == expected[name], 'input pin '+name)
        archive = ARTIFACTS/safe_path(row['archive'])
        require(sha(archive) == expected[name], 'corresponding archive SHA '+name)
        if name == 'onnxruntime': continue
        require(archive_rows(archive) == trees[name], 'original source manifest drift '+name)
        root_hash = hashlib.sha256(canonical(trees[name])).hexdigest()
        require(root_hash == headers[name]['rootSha256'] and headers[name]['unmodifiedOriginalFiles'] is True,
                'unproven pristine source root '+name)
        omissions = headers[name].get('omittedNonBuildSymlinks', {})
        require(omissions == (OMITTED_EXAMPLE_LINKS if name == 'sherpa' else {}),
                'unexpected non-build source omissions: '+name)
        for path, digest in headers[name]['compiledHeadersSha256'].items():
            require(path not in omissions and trees[name].get(path, {}).get('sha256') == digest,
                    'compiled header SHA '+name+'/'+path)
    require(headers['eigen']['compiledHeadersSha256'] and headers['json']['compiledHeadersSha256'], 'missing actual dependency-header trace')
    require(headers['sherpa']['rootSha256'] == proof['originalSourceRootSha256'], 'root proof binding drift')
    bundle_sources(trees['eigen'], trees['json'])
    cache = cache_values(ARTIFACTS/'Proof/CMakeCache.txt')
    require(cache.get('MINISIGHT_EIGEN_VERSION') == proof['eigenVersion']
            and cache.get('MINISIGHT_EIGEN_SOURCE_DIR') == proof['eigenSource']
            and cache.get('MINISIGHT_EIGEN_CMAKE_VERSION_STRING') == proof['eigenCmakeVersionString'], 'actual CMake observation missing')
    require(proof['sourceBytes'] <= 50*1024*1024, 'source download budget drift')
    library_proof = json.loads((ARTIFACTS/'Proof/static-library-inputs.json').read_text())
    require([r['name'] for r in library_proof] == LIBRARIES
            and sum(r['objects'] for r in library_proof) == proof['target']['objects']
            and all(re.fullmatch('[0-9a-f]{64}', r['sha256']) for r in library_proof), 'exact ten-library input proof missing')
    trace = (ARTIFACTS/'Proof/cmake-trace.jsonl').read_text()
    require('/source/cmake/eigen.cmake' in trace and '5.0.1' in trace
            and '/source/cmake/openfst.cmake' in trace, 'effective CMake module selection not recorded')
    link = json.loads((ARTIFACTS/'Proof/link.json').read_text())
    require(link['forceLoadAllSherpaObjects'] is True and link['run'] is False and link['linkedOrtVersion'] == '1.28.2', 'native static link proof missing')
    symbols = (ARTIFACTS/'Proof/defined-symbols.txt').read_text()
    for name in FUNCTIONS: require(re.search(r'\b_'+name+r'$', symbols, re.M), 'C API symbol missing '+name)
    print('PASS artifact SHA, device arm64/minOS15.5, C API and pristine Eigen/JSON source correspondence')


def static_gate():
    package = (PACKAGE/'Package.swift').read_text(); version = (PACKAGE/'Sources/Version.swift').read_text()
    require('name: "SherpaOnnxC", path: "Artifacts/SherpaOnnxC.xcframework"' in package, 'Sherpa must be local controlled artifact')
    require('sherpa-onnx-v2.0.1-ios-static.xcframework.zip' not in package, 'remote prebuilt Sherpa still selected')
    require(ORT_URL in package and ORT_SHA in package and COMMIT in version, 'fixed ORT/source marker drift')
    script = ROOT/'scripts/build_minisight_keyword_runtime_20261116.sh'
    text = script.read_text()
    for token in ['GITHUB_ACTIONS', 'Darwin', '-DCMAKE_SYSTEM_NAME=iOS', '-DCMAKE_OSX_ARCHITECTURES=arm64',
                  '-DCMAKE_OSX_DEPLOYMENT_TARGET=15.5', '--target sherpa-onnx-c-api', '-create-xcframework',
                  '--prepare', '--finalize', '-force_load', '--cache-valid']:
        require(token in text, 'build contract missing '+token)
    require('libsherpa-onnx-cxx-api.a' not in LIBRARIES and len(LIBRARIES) == 10, 'exact official archive closure drift')
    for name in FUNCTIONS: require(name in (ROOT/'src/ios/MiniSightWakeEngine.swift').read_text(), 'engine C API contract drift')
    for name in ['../escape','/absolute','a\\b']:
        try: safe_path(name)
        except RuntimeError: pass
        else: raise RuntimeError('unsafe archive path accepted')
    example = Path('/tmp/minisight-source-fixture')/'downloads'/('sherpa-'+COMMIT+'.tar.gz')
    require(example.name == 'sherpa-'+COMMIT+'.tar.gz', 'download path construction changed')
    print('PASS controlled rebuild source contracts (static only; no build/run performed)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', type=Path); parser.add_argument('--finalize', type=Path)
    parser.add_argument('--artifact', action='store_true'); parser.add_argument('--cache-valid', type=Path)
    parser.add_argument('--upstream-static', type=Path)
    args = parser.parse_args()
    if args.prepare: prepare(args.prepare.resolve()); return
    if args.finalize: finalize(args.finalize.resolve()); return
    static_gate()
    if args.upstream_static:
        s = args.upstream_static
        require(sha(s/'sherpa-onnx/c-api/c-api.h') == HEADER_SHA, 'inspected upstream header drift')
        for name, owner, _, url, digest in DEPS:
            if owner.startswith('source/'): cmake_pin(s/owner[7:], name, url, digest)
        print('PASS inspected fixed upstream CMake hashes/URLs')
    if args.artifact or args.cache_valid: artifact_gate(args.cache_valid)
    elif not (ARTIFACTS/'provenance.json').is_file(): print('NOT_BUILT: correspondence/release gate still closed until authorized GitHub CI')

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print('FAIL keyword provenance: '+str(e), file=sys.stderr); sys.exit(1)
