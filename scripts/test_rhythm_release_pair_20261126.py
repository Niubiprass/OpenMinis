#!/usr/bin/env python3
"""Checks existing App compile wiring only; never invokes xcodebuild or audio."""
from pathlib import Path
import json,re,shlex
R=Path(__file__).resolve().parents[1]
w=(R/'.github/workflows/openminis-app.yml').read_text()
c=R/'src/ios/Configs'
config=(c/'MiniSightRhythm.xcconfig').read_text()
assert re.search(r'^MINISIGHT_RHYTHM_PAIR\s*=\s*0$',config,re.M),'default must remain source-only'
for name in ['ProviderCustomization.xcconfig','ProviderCustomization.xcconfig.example']:
 assert '#include "MiniSightRhythm.xcconfig"' in (c/name).read_text(),name
assert 'GCC_PREPROCESSOR_DEFINITIONS = $(inherited)' in config
macros=['MINISIGHT_ENABLE_RHYTHM_CAPTURE','MINISIGHT_ENABLE_RHYTHM_TRANSPORT','MINISIGHT_RHYTHM_LIVE_BUILD']
for m in macros:assert m+'=$(MINISIGHT_RHYTHM_PAIR)' in config,m
# Tokenize the actual multi-line xcodebuild command, not an unrelated env block.
command=re.search(r'(?m)^\s+xcodebuild -project src/ios/Minis.xcodeproj.*?tee build-v64r.log',w,re.S)
assert command,'actual existing compile command missing'
args=shlex.split(command.group().replace('\\\n',' '))
assert args[0]=='xcodebuild' and 'MINISIGHT_RHYTHM_PAIR=1' in args
assert 'CODE_SIGNING_ALLOWED=NO' in args and 'build' in args
for mode in ['0','1']:
 resolved=config.replace('$(MINISIGHT_RHYTHM_PAIR)',mode)
 assert all(m+'='+mode in resolved for m in macros)
# PBX stays untouched: both configurations already inherit this exact config.
pbx=(R/'src/ios/Minis.xcodeproj/project.pbxproj').read_text()
assert pbx.count('baseConfigurationReference = AC0000001 /* ProviderCustomization.xcconfig */;')==2
assert pbx.count('"$(inherited)"')>=2
client=(R/'src/ios/MiniSightCore/MiniSightRhythmClient.m').read_text()
assert '(!MINISIGHT_ENABLE_RHYTHM_CAPTURE || !MINISIGHT_RHYTHM_LIVE_BUILD)' in client
assert 'LIVE_transport_requires_paired_capture_and_explicit_LIVE_build' in client
# Preserve the unique release path and its strict final byte/receipt gates.
for marker in ['codesign --verify --deep --strict','scripts/ci_verify_lyrics_ipa.py','scripts/app_release.py prepare','scripts/app_release.py resume','scripts/app_release.py publish','continue-on-error: false','steps.source_gate.outcome','scripts/test_single_app_workflow.py']:
 assert marker in w,marker
print(json.dumps({'status':'PASS','scope':'SOURCE_ONLY','default_pair':0,'future_ci_compile_pair':1,'capture_transport_live_build':[1,1,1],'new_plugin_and_service_required':True,'service_identity_must_be_finalized_before_paired_ci':True,'source0_is_not_live':True,'xcodebuild_executed':False,'device_validated':False}))
