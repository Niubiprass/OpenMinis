#!/usr/bin/env python3
"""Real-source contracts and extracted production Swift fixtures, NOT UI validation.
--require-native rejects missing Darwin/app-hosted XCTest execution. No network/device/CI.
"""
from pathlib import Path
import argparse, hashlib, json, platform, shutil, subprocess, tempfile

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift'
C = ROOT / 'src/ios/Views/Chat/ChatMessageViews.swift'
p, c = P.read_text(), C.read_text()

def section(text, start, end):
    a = text.index(start)
    return text[a:text.index(end, a)]

state = section(c, 'struct InlineErrorCardExpansion: Equatable {', '\nfinal class InlineErrorCardState:')
shared = section(c, 'struct InlineErrorCardExpansion: Equatable {', '\n// MARK: - Context-menu preview')
footer = section(p, 'private struct BridgedAssistantFooterV3:', '\nprivate struct BridgedWholeMessageV3:')
inline = section(footer, '    private func reconcileErrorCard() {', '\n    private var resumeBanner:')
height = section(p, '        private func flushErrorCardHeights() {', '\n        // === Height Measurement Cache ===')
transaction = section(p, '        private func performHostingHeightChange(', '\n        private func flushThinkingShapeChanges()')
legacy = c[c.index('    private func inlineError(_ rawError: String)'):]
checks = []
def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

check('assistant default two lines and unlimited natural expanded text', all(x in inline for x in ['.lineLimit(expanded ? nil : 2)', '.fixedSize(horizontal: false, vertical: true)', 'Text(error).font(.caption).foregroundStyle(.red)']))
check('unchanged horizontal warning/text/retry composition', 'HStack(alignment: .center, spacing: 8)' in inline and 'HStack(spacing: 6)' in inline and 'exclamationmark.triangle.fill' in inline)
check('original card visuals', all(x in shared for x in ['.padding(10).frame(maxWidth: .infinity, alignment: .leading)', 'Color.red.opacity(0.12)', 'RoundedRectangle(cornerRadius: 10)']))
check('one tap and native context menu full copy', shared.count('.onTapGesture') == 1 and '.contextMenu(menuItems:' in shared and 'UIPasteboard.general.string = copyText' in shared)
check('retry is foreground sibling not parent gesture', '.allowsHitTesting(false)' in inline and 'errorCard.collapse()\n                    onRetry()' in inline and '.modifier(InlineErrorCardSurface(copyText: error)' in inline)
check('no simultaneous/extra long press or alternate UI', not any(x in shared + inline for x in ['.simultaneousGesture(', '.onLongPressGesture(', '.sheet(', 'ScrollView', 'chevron', 'View Full Error']))
check('raw message identity and retry/process reset', all(x in state for x in ['self.messageID != messageID', 'self.rawError != rawError', 'self.retryAttempt != retryAttempt', 'self.processing != processing', 'expanded = false']))
check('targeted complete cache roundtrip', all(x in height for x in ['.assistantFooter(mid)', 'noteIOS15HostingContentShape', 'consumeIOS15PendingStableShrink', 'clearCachedHeight()', 'invalidateHeight(at: ip.item, discardPrecalc: true)', 'layout.invalidateLayout()']))
check('no snapshot/reload/forced bottom on toggle', not any(x in height for x in ['applySnapshot', 'reloadData', 'scrollToBottom', 'setCachedHeight']))
check('anchor preserves input insets and smooth motion', all(x in transaction for x in ['preserveVisibleAnchor: Bool = false', '!preserveVisibleAnchor && scrollMode == .autoScrolling', 'adjustedContentInset.bottom', 'UIView.animate(withDuration: 0.2', 'UIAccessibility.isReduceMotionEnabled']))
check('pruned local state and VM reset', 'errorCardStates = errorCardStates.filter' in p and 'errorCardStates.removeAll()' in p and 'pendingErrorCardHeights.formIntersection(currentIds)' in p)
check('idle/settle consumer outside text throttle', 'flushErrorCardHeights()\n            // [T-thinking-collapse-blank]' in p)
check('legacy default eight lines/digest/selection/copy preserved', all(x in legacy for x in ['.lineLimit(8)', 'ProviderErrorDigest.composed(for: error)', '.textSelection(.enabled)', 'UIPasteboard.general.string = error']))
check('no secret IO in added state/surface', not any(x in shared for x in ['UserDefaults', 'Keychain', 'URLSession', 'FileManager', 'print(', 'AppLogger']))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--require-swift', action='store_true')
parser.add_argument('--require-native', action='store_true')
parser.add_argument('--emit-native', type=Path)
args = parser.parse_args()
report = {'portable_source_contracts': 'PASS', 'contracts': checks,
          'source_sha256': {str(x.relative_to(ROOT)): hashlib.sha256(x.read_bytes()).hexdigest() for x in [P,C]},
          'production_swift_state': 'NOT_RUN', 'native_ui': 'NOT_RUN',
          'limitations': ['Source contracts are not typecheck or gesture/layout validation.', 'App-hosted iOS XCTest fixture must be integrated/run on Darwin; no device/CI actions performed.']}
if args.emit_native:
    template = (ROOT / 'fixtures/error_card_inline_native_20261126.swift').read_text()
    output = template.replace('// INSERT_PRODUCTION_SHARED', shared).replace('// INSERT_PRODUCTION_INLINE', inline)
    args.emit_native.write_text(output)
    report['native_fixture_emitted'] = str(args.emit_native)
swift = shutil.which('swift')
if swift:
    fixture = (ROOT / 'fixtures/error_card_state_20261126.swift').read_text()
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / 'ErrorCardProduction.swift'
        src.write_text('import Foundation\n' + state + '\n' + fixture)
        subprocess.run([swift, str(src)], check=True)
    report['production_swift_state'] = 'PASS (extracted production struct; not UIKit)'
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
if args.require_swift and not swift:
    raise SystemExit('REQUIRED Swift execution unavailable; NOT RUN')
if args.require_native:
    raise SystemExit('REQUIRED native UIKit XCTest has NOT RUN. Emit the fixture, add it to an app-hosted iOS test target and run xcodebuild test on Darwin; portable checks cannot satisfy this gate.')
