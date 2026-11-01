#!/usr/bin/env python3
"""Run the production range algorithm against real macOS attributed strings.
AppKit NSFont substitutes UIKit UIFont solely for this host-side unit test.
This is not an iOS TextKit/device test.
"""
import os, shutil, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=(root/'src/ios/Views/Chat/SelectableMarkdownView.swift').read_text()
start=s.index('private static func prefixesEqualIgnoringFontSubstitution(')
end=s.index('/// Recursively collect `.image`',start)
function=s[start:end].replace('private static func','static func')
assert 'effectiveRange: &newRange' in function and 'effectiveRange: &oldRange' in function
checks=r'''
func check(_ condition: @autoclosure () -> Bool, _ name: String) { precondition(condition(), name) }
let f = NSFont.systemFont(ofSize: 15)
let changed = NSFont.systemFont(ofSize: 22)
let fresh = NSAttributedString(string: "abcdef", attributes: [.font:f, .foregroundColor:NSColor.black])
check(Probe.prefixesEqualIgnoringFontSubstitution(fresh,fresh), "equal")
let old = NSMutableAttributedString(attributedString:fresh)
old.addAttribute(.foregroundColor,value:NSColor.red,range:NSRange(location:3,length:3))
check(!Probe.prefixesEqualIgnoringFontSubstitution(fresh,old), "old internal color boundary")
check(!Probe.prefixesEqualIgnoringFontSubstitution(old,fresh), "new internal color boundary")
old.setAttributes([.font:f,.foregroundColor:NSColor.black.withAlphaComponent(0)],range:NSRange(location:3,length:3))
check(!Probe.prefixesEqualIgnoringFontSubstitution(fresh,old), "internal transparent text")
old.setAttributes([.font:changed,.foregroundColor:NSColor.black],range:NSRange(location:3,length:3))
check(!Probe.prefixesEqualIgnoringFontSubstitution(fresh,old), "internal font change")
old.addAttribute(Probe.nsOriginalFontKey,value:f,range:NSRange(location:3,length:3))
check(Probe.prefixesEqualIgnoringFontSubstitution(fresh,old), "fallback font allowed")
let cjk = NSAttributedString(string:"中文🙂e\u{301}",attributes:[.font:f,.foregroundColor:NSColor.black])
let cjkOld=NSMutableAttributedString(attributedString:cjk)
cjkOld.addAttributes([.font:changed,Probe.nsOriginalFontKey:f],range:NSRange(location:2,length:2))
check(Probe.prefixesEqualIgnoringFontSubstitution(cjk,cjkOld), "UTF16 emoji fallback")
cjkOld.addAttribute(.link,value:"https://example.invalid",range:NSRange(location:3,length:1))
check(!Probe.prefixesEqualIgnoringFontSubstitution(cjk,cjkOld), "internal link style")
check(Probe.prefixesEqualIgnoringFontSubstitution(NSAttributedString(string:""),NSAttributedString(string:"")), "empty")
check(!Probe.prefixesEqualIgnoringFontSubstitution(fresh,NSAttributedString(string:"abcdeg")), "text mismatch")
print("Production attributed-prefix algorithm tests: PASS (AppKit, not iOS)")
'''
if shutil.which('swift'):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/'PrefixTests.swift'
        p.write_text('import Foundation\nimport AppKit\ntypealias UIFont = NSFont\nstruct Probe { static let nsOriginalFontKey = NSAttributedString.Key("NSOriginalFont")\n'+function+'\n}\n'+checks)
        subprocess.run(['swift',str(p)],check=True)
else:
    if os.environ.get('V64R_REQUIRE_SWIFT')=='1': raise SystemExit('Swift required in CI')
    print('Attribute range source contracts: PASS; Swift execution deferred to macOS CI')
