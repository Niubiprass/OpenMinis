#!/usr/bin/env python3
"""Regression locks for the 2026-11-07 App-side MiniSight repair. Static only."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / 'src/ios'
fails = []
def need(cond, what):
    if not cond: fails.append(what)
def read(p): return p.read_text()

# Confirmation: probe fallback, post before waiting, type-filtered result.
c = read(ROOT / 'Views/Settings/MiniSightConfirm.swift')
need('probeJailbreakPlugin(id:' in c and 'plugin_no_reply' in c, 'dead plugin falls back to modal')
need(c.index('Self.post(Self.note)') < c.index('while Date() < deadline'), 'notification posts before polling')
need('parts.count == 2' in c and 'parts[0] == Substring(id)' in c, 'result is filtered by request id')
need('no_visible_ack' in c and 'cancelPet(id' in c, 'missing pet ack falls back and cancels')

# Voice: installed independently of switch, acknowledged, final emitted first.
bridge = read(ROOT / 'MiniSightVoiceBridge.swift')
app = read(ROOT / 'MinisApp.swift')
need('MiniSightVoiceBridge.shared.install()' in app, 'voice bridge installed at launch')
need('self.emit(manager.recognizedText, final: true' in bridge and
     bridge.index('self.emit(manager.recognizedText, final: true') < bridge.index('self.listening = false'), 'final transcript emitted before state clear')
need('"starting"' in bridge and 'generation' in bridge, 'voice has startup ack and generation')
need('url.host == "minisight"' in app and 'url.path == "/voice"' in app, 'voice can wake a suspended App')
need('reason: "stopped"' in bridge or 'reason: "stopped"' in bridge.replace('"', '"'), 'pending start can be stopped')
need('empty_transcript' in bridge, 'empty final is explicit')

# Runtime snapshot: real 45-key transport, written before notification, launch repair.
settings = read(ROOT / 'MiniSightSettings.swift')
store = read(ROOT / 'MiniSightConfigStore.swift')
need('runtimeFields.count == 45' in settings, 'snapshot validates 45 keys')
need('values["preferences"] = canonical' in settings, 'snapshot has canonical preferences bag')
need(settings.index('data.write(to: url') < settings.index('CFNotificationCenterPostNotification'), 'snapshot writes before notify')
need('if !FileManager.default.fileExists' in store and 'writeSnapshot()' in store, 'launch repairs missing snapshot')
need('deliver(generation: publishGeneration' in store, 'publish uses real runtime delivery')

# Tool images must decode/JPEG off MainActor (the 29.9s IPS stack).
tools = read(ROOT / 'Agent/Chat/AIChatViewModel+ConcurrentTools.swift')
need('await AttachmentImageCodec.resizedJPEG' in tools, 'tool screenshot resize is off-main')
need('await AttachmentImageCodec.analyzeForRead' in tools, 'read_image decode is off-main')
need('toolImageData = Self.resizedImageData' not in tools, 'no sync tool image resize remains')
need('isReadOnlyShell' in tools and 'isReadOnlyShell' in read(ROOT / 'Views/Settings/PluginDevView.swift'), 'read-only commands bypass approval')
need('"git"' in read(ROOT / 'Views/Settings/PluginDevView.swift'), 'read-only classifier handles git')

# Attachment first-chip hit target is inside the chip.
chip = read(ROOT / 'Views/Chat/ChatInputBar.swift')
need('.frame(width: 26, height: 26)' in chip and '.contentShape(Circle())' in chip, 'remove badge has large hit target')
need(chip.count('removeBadge') >= 4, 'all chip kinds use same badge')
need('.offset(x: 4, y: -4)' not in chip, 'no badge outside chip bounds')

# Assets: background ImageIO, cancellation, explicit format, active selection.
home = read(ROOT / 'Views/Settings/MiniSightHomePage.swift')
cat = read(ROOT / 'Agent/Chat/MiniSightCatalog.swift')
need('MiniSightAssetOperation' in home and 'cancel()' in home, 'asset import cancellable')
need('MiniSightAssetDownload' in home, 'asset link uses bounded streamer')
need('ImportKind' in home and '.petdex8x9' in cat, 'single image vs 8x9 is explicit')
need('MiniSightAssetCatalog.activate' in home, 'catalog items can be activated')
need('MiniSightAssetCatalog.preview' in home or 'preview(at:' in home, 'header uses single-cell preview')
need('frame(width: 128, height: 139)' in home, 'header width is fixed, not the 2304pt atlas')
need('LazyVGrid' in home and 'variant: item.variant' in home, 'gallery selects individual pets')
need('width * 936 - height * 768' in cat and 'layoutVersion = 3' in cat, 'pack detection plus lossless single layout')
need('.petdex8x9' in cat and 'case auto' in cat, 'explicit pack and auto detection remain')
need('migrateLegacySingleImages()' not in cat, 'no destructive single-image migration')
need('decoded.width' in cat and 'canvasW' in cat, 'single image keeps its own resolution')
need('ImportKind.auto' in home, 'asset format defaults to auto detection')
need('gridLooksLikePets' in cat and 'packShaped' in cat, 'pack detection reads pixel layout, not the file extension')
need('uti == "public.png" || gridLooksLikePets(source)' in cat, 'a JPEG conversion of a real 8x9 sheet still auto-detects as pack')
need('migrateSingleToPack' in cat, 'a sheet already stored as single image is migrated back in place')
_w, _h = 1260, 1536
need(abs(_w * 936 - _h * 768) <= max(768 * 4, _h * 8), '1260x1536 re-encode stays inside the 12:13 tolerance')

# DSML tool calls: a relay that ships DeepSeek's text syntax must still run tools.
prov = read(ROOT / 'Providers/OpenAI/OpenAIAgentProvider.swift')
need('struct DSMLStreamFilter' in prov and 'flushDSML()' in prov, 'DSML calls are converted to real tool events')
need('<｜｜DSML｜｜ calls>' in prov and '</｜｜DSML｜｜ invoke>' in prov and '</｜｜DSML｜｜ parameter>' in prov, 'DSML grammar matches the observed wire format')
need('dsml.consume(text)' in prov, 'content deltas are filtered before display')

# Attachment chips must not live in purgeable Caches (2026-11-08 15:43).
proc = read(ROOT / 'Agent/Chat/AttachmentProcessing.swift')
vm = read(ROOT / 'Agent/Chat/AIChatViewModel.swift')
att = read(ROOT / 'Agent/Chat/AIChatViewModel+Attachments.swift')
need('applicationSupportDirectory' in proc and 'legacyCacheDirectory' in proc, 'staging survives a Caches purge')
need('applicationSupportDirectory' in att, 'new picks land in the durable staging dir')
need('legacyCacheDirectory' in vm and '个附件的文件已失效' in vm, 'send repairs or drops a chip whose bytes vanished')
need('stage=prepare.missing' in proc, 'processor skips one vanished file instead of failing the batch')
runtime = read(ROOT / 'MiniSightInAppRuntime.swift')
need('@AppStorage("minisight.dragResponse")' in runtime and 'dragGain' in runtime, 'in-app drag honours the response switch')
need('@AppStorage("minisight.petSound")' in runtime and 'MiniSightBlip.playIfEnabled' in runtime, 'in-app gestures honour the sound switch')
need('MiniSightBlip.h' in read(ROOT / 'MinisApp-Bridging-Header.h'), 'sound player is visible to Swift')

# Connection page: shared client, custom URL, saves before test.
ai = read(ROOT / 'Views/Settings/MiniSightAIPage.swift')
need('.custom' in ai and 'MiniSightSupplier.custom' in ai, 'custom URL preset')
need('URLSession' not in ai, 'test does not fork a network client')
need('guard saveConnection() else' in ai, 'test saves fields before sending')
need('parsed.host?.lowercased() != "api.anthropic.com"' in ai, 'native Anthropic is called out')

if fails:
    print('FAIL local repairs')
    for f in fails: print(' -', f)
    sys.exit(1)
print('PASS MiniSight App repair locks')
