#!/usr/bin/env python3
"""Full-group source wiring contracts only; portable behavior has separate runners."""
from pathlib import Path
import re,unittest
ROOT=Path(__file__).resolve().parents[1];IOS=ROOT/'src/ios';CORE=IOS/'MiniSightCore'
PLUGIN=ROOT.parent/'plugin/debs/MiniSight'

class CompleteWiring(unittest.TestCase):
 def test_version_and_no_fake_default_music(self):
  pet=(CORE/'MiniSightPet.m').read_text();client=(CORE/'MiniSightRhythmClient.m').read_text()
  self.assertIn('_rhythmFollowing = YES;',pet)
  self.assertIn('_effects.rhythmFollowing = YES;',pet)
  self.assertIn('pet.rhythmFollowing=YES;',client)
  self.assertIn('enabled = enabled && token > 0',client)
  self.assertLess(client.index('!MiniSightRhythmLiveTransportCompiled()'),client.index('_socket=socket('))
  self.assertIn('#define MINISIGHT_ENABLE_RHYTHM_TRANSPORT 0',client)
  self.assertIn('static let version = "0.8.59"',(IOS/'MiniSightHostAdapter.swift').read_text())
 def test_daily_switch_round_trip_and_two_host_application(self):
  s=(IOS/'MiniSightSettings.swift').read_text();c=(IOS/'MiniSightConfigStore.swift').read_text();ui=(IOS/'Views/Settings/MiniSightHomePage.swift').read_text();runtime=(IOS/'MiniSightInAppRuntime.swift').read_text()
  self.assertIn('static let dailyActionsEnabled = "minisight.actions.daily"',s)
  self.assertIn('MiniSightSettingKey.dailyActionsEnabled: true',s)
  self.assertIn('publish(MiniSightSettingKey.dailyActionsEnabled)',c)
  self.assertIn('Toggle("丰富日常动作"',ui)
  self.assertIn('@AppStorage("minisight.actions.daily") private var dailyActionsEnabled = true',runtime)
  self.assertEqual(runtime.count('pet.dailyActionsEnabled = parent.dailyActionsEnabled'),2)
  self.assertIn('实时节奏接收尚未启用',ui)
  self.assertIn('播放音乐时仍保留普通活动',ui)
  self.assertIn('本开关不会安装服务',ui)
  self.assertIn('开关开启且音乐在播时会请求本机系统输出分析',ui)
  self.assertIn('不读取麦克风、不外传音频，可能混入提示音',ui)
  log=(CORE/'MiniSightLog.m').read_text()
  allowed=log.split('@"setting":',1)[1].split('@"sensor":',1)[0]
  for key in ['minisight.actions.daily','minisight.music.lyrics','minisight.music.motion']:
   self.assertIn('@"'+key+'"',allowed)
 def test_app_render_only_default_and_generation_lifetime(self):
  s=(IOS/'MiniSightInAppRuntime.swift').read_text()
  self.assertIn('MiniSightAssetCatalog.io.async',s)
  self.assertLess(s.index('if force { _ = try? MiniSightAssetCatalog.snapshot() }'),s.index('let selection = force ||'))
  self.assertIn('image: MiniSightDefaultAssets.runtimeImage(), layout: 3',s)
  self.assertIn('variant: 0, manifest: nil',s)
  self.assertIn('MiniSightRhythmConfigurePet(pet, false, parent.musicToken)',s)
  self.assertIn('musicGeneration.rounded(.towardZero) == musicGeneration',s)
  self.assertIn('self.rhythmToken = 0',s)
 def test_measured_music_evidence_complete_host_chain_static_only(self):
  s=(IOS/'MiniSightInAppRuntime.swift').read_text()
  self.assertIn('@Published private(set) var hasPositionEvidence = false',s)
  self.assertIn('musicPositionEvidence: music.hasPositionEvidence',s)
  self.assertIn('let musicPositionEvidence: Bool',s)
  self.assertIn('value?["rhythmGeneration"] ?? value?["generation"]',s)
  self.assertIn('let positionEvidence = nextPlaying && snapshot.motionTime != nil &&',s)
  self.assertIn('MiniSightMusicSnapshot.flag(value?["progressAvailable"]) == true',s)
  self.assertIn('MiniSightMusicSnapshot.number(value?["motionRate"]) == 1',s)
  self.assertEqual(s.count('MiniSightRhythmConfigurePetWithPosition(pet, parent.musicPlaying, parent.musicToken,'),3)
  self.assertEqual(s.count('parent.musicPositionEvidence ? (parent.musicAnchor?.current ?? .nan) : .nan'),3)
  self.assertIn('MiniSightRhythmConfigurePet(pet, false, parent.musicToken)',s)
  self.assertIn('if !wanted { line = nil; playing = false; anchor = nil; rhythmToken = 0; hasPositionEvidence = false;',s)
  self.assertIn('if now - lastValidAt > 5 || now < lastValidAt - 1 { line = nil; playing = false; anchor = nil; rhythmToken = 0; hasPositionEvidence = false;',s)
  self.assertIn('self.rhythmToken = 0; self.hasPositionEvidence = false; self.evidence("music_stale"',s)
  self.assertIn('guard !inFlight else { return }',s)
  self.assertIn('Timer(timeInterval: 0.25, repeats: true)',s)
  evidence=s.split('let positionEvidence =',1)[1].split('if self.hasPositionEvidence',1)[0]
  self.assertNotIn('nextLine',evidence)
  self.assertNotIn('lyrics',evidence)
 def test_original_defaults_are_independent_of_user_assets(self):
  s=(IOS/'MiniSightDefaultAssets.swift').read_text();catalog=(IOS/'Agent/Chat/MiniSightCatalog.swift').read_text()
  self.assertIn('CC0',(IOS/'Resources/MiniSightDefaults/LICENSE.txt').read_text())
  self.assertNotIn('48-',s)
  stage=s.split('static func stageFallback',1)[1].split('/// Upright sheet',1)[0]
  self.assertNotIn('MiniSightPetFile.url',stage)
  self.assertIn('if old != data',stage)
  self.assertIn('DispatchQueue.main.async { MiniSightAssetCatalog.publishChange() }',stage)
  self.assertLess(stage.index('== data else'),stage.index('publishChange()'))
  self.assertIn('options: .withoutOverwriting',catalog)
 def test_actual_background_notification_cannot_drop_current_candidate(self):
  m=(CORE/'MiniSightMusicMonitor.m').read_text();f=(ROOT/'scripts/fixtures/minisight_music_monitor_20261116/runtime.m').read_text()
  self.assertIn('BOOL awaitPID = MSMusicUsePIDSource(MSMusicPID != NULL);',m)
  self.assertIn('_playerIdentified = !awaitPID && source.length > 0;',m)
  self.assertNotIn('BOOL awaitPID = !source && MSMusicPID && MSMusicMissingSource(reason);',m)
  self.assertIn('BOOL fallback = MSMusicUsePIDSource(MSMusicPID != NULL);',m)
  self.assertIn('BOOL identityOK = MSMusicReadSourceOK(MSMusicPID != NULL, _pidRead, [player isEqualToString:direct]);',m)
  self.assertIn('!MSMusicPIDMatches(self->_pidRead, pid, [player isEqual:lastPlayer])',m)
  self.assertNotIn('!source && _sourceFromPID && MSMusicPID',m)
  self.assertIn('first direct-loss notification retains only a hidden candidate',f)
  self.assertIn('background current PID restores verified same-track lyrics',f)
  self.assertIn('late old lookup cannot revive lyrics',f)
  for v in ['player_pid_nonpositive','pid_mapping_missing','pid_signature_rejected','pid_changed_during_sample']:
   for p in [CORE/'MiniSightLog.m',IOS/'Views/Settings/MiniSightSettingsView.swift',IOS/'MiniSightInAppRuntime.swift']:
    self.assertIn(v,p.read_text())
 def test_project_references_are_real_and_unique(self):
  s=(IOS/'Minis.xcodeproj/project.pbxproj').read_text()
  for n in ['MiniSightRhythmClient.m','MiniSightDefaultAssets.swift']:
   self.assertEqual(s.count('/* '+n+' in Sources */'),2,n)
  self.assertEqual(s.count('/* MiniSightDefaults in Resources */'),2)
  self.assertIn('path = Resources/MiniSightDefaults;',s)
  self.assertIn('MiniSightCore/MiniSightRhythmClient.h',(IOS/'MinisApp-Bridging-Header.h').read_text())
 def test_native_fixture_registers_actual_measured_input_case(self):
  f=(ROOT/'scripts/fixtures/minisight_effects_runtime_20261116/runtime.m').read_text()
  self.assertIn('{"measured-music-input-only", MeasuredMusicInputOnly}',f)
  self.assertIn('r.pet.rhythmFollowing && r.effects.rhythmFollowing',f)
  self.assertIn('strongBob>weakBob',f)
  self.assertIn('Explicit legacy-only regression',f)
 def test_sibling_plugin_preserves_layout_and_shared_sources(self):
  if not PLUGIN.is_dir(): self.skipTest('independent App CI has no sibling plugin; validated locally in both trees')
  for n in ['MiniSightMusicMonitor.m','MiniSightMusicPlayerABI.h','MiniSightPetEffects.m','MiniSightPetDailyPolicy.h','MiniSightRhythmClient.m','MiniSightLog.m']:
   self.assertEqual((CORE/n).read_bytes(),(PLUGIN/n).read_bytes(),n)
  t=(PLUGIN/'Tweak.xm').read_text();r=(PLUGIN/'MiniSightResources.m').read_text()
  self.assertIn('static NSString *const kMiniSightVersion   = @"0.8.60";',t)
  self.assertIn('gMiniSightPet.dailyActionsEnabled = MiniSightDailyActionsEnabled();',t)
  self.assertIn('if (gMiniSightUsingDefaultAtlas) return 3;',t)
  self.assertIn('MSAssetNeedsHostRebuild(resourcesFresh',t)
  self.assertIn('MSAtlasMetadataReadable(object)',r)
  self.assertIn('UIImage *atlas = !badMetadata && petPath ?',r)
  self.assertIn('!usingDefault && [petMeta[@"actionPack"] isKindOfClass:NSString.class]',r)
  self.assertIn('MiniSightRhythmConfigurePet(gMiniSightPet, NO, 0)',t)
if __name__=='__main__':unittest.main(verbosity=2)
