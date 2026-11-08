#!/usr/bin/env python3
"""The blip WAV header must be a legal 44-byte PCM file.

The old builder wrote `frames * 2` into BOTH the `fmt ` chunk length and the
`data` length while only 16 bytes of `fmt ` content exist, so every parser
looked for the next chunk at offset 2820 instead of 36. This test parses a
file rebuilt from the constants in the source; it is a format test, not proof
of audible output on a device.
"""
import re
import struct
import sys
import wave
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [ROOT / 'src/ios/MiniSightCore/MiniSightBlip.m']
fails = []
for path in SOURCES:
    src = path.read_text()
    where = path.name
    if 'fmtLen = 16' not in src:
        fails.append(f'{where}: fmt chunk length is not fixed at 16')
    if 'appendBytes:&fmtLen length:4' not in src:
        fails.append(f'{where}: fmt length field not written from fmtLen')
    if 'appendBytes:&dataLen length:4' not in src:
        fails.append(f'{where}: data length field not written from dataLen')
    if 'initWithData:wav error:&error' not in src:
        fails.append(f'{where}: AVAudioPlayer init error is ignored')
    if 'AVAudioSessionCategoryAmbient' not in src or 'MixWithOthers' not in src:
        fails.append(f'{where}: blip does not mix with other audio')
    if 'prepareToPlay]' not in src or '[gPlayer play]' not in src:
        fails.append(f'{where}: prepare/play results are not checked')
    match = re.search(r'frames = (\d+)', src)
    if not match:
        fails.append(f'{where}: frame count missing')
        continue
    frames = int(match.group(1))
    rate = 22050
    pcm = b''.join(struct.pack('<h', 0) for _ in range(frames))
    data_len = frames * 2
    header = (b'RIFF' + struct.pack('<I', 36 + data_len) + b'WAVEfmt '
              + struct.pack('<I', 16) + struct.pack('<HHIIHH', 1, 1, rate,
                                                    rate * 2, 2, 16)
              + b'data' + struct.pack('<I', data_len))
    try:
        with wave.open(BytesIO(header + pcm), 'rb') as handle:
            if handle.getnframes() != frames:
                fails.append(f'{where}: parsed frame count differs')
            if handle.getframerate() != rate:
                fails.append(f'{where}: parsed sample rate differs')
    except Exception as exc:  # noqa: BLE001 - report the parser reason
        fails.append(f'{where}: standard WAV parser rejected the header: {exc}')

if fails:
    print('FAIL blip WAV header')
    for item in fails:
        print(' -', item)
    sys.exit(1)
print('PASS blip WAV is a legal PCM file')
