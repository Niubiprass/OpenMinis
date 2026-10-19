#!/usr/bin/env python3
"""[T-csp-recovery] Contract tests for the shared blank-page recovery.

The problem: some sites (Discourse/linux.do is the one we hit) serve
`Content-Security-Policy: script-src 'nonce-…' 'strict-dynamic'` while the
HTML reaching an iOS 15 WKWebView carries `nonce=""` on every script tag.
`strict-dynamic` still needs a trusted root, so nothing runs, the framework
global stays undefined, and the splash spins forever.

The fix re-renders the page's own DOM through `loadHTMLString`, which has no
HTTP response and therefore no CSP header.

These are source contracts only — behaviour needs a device.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
SHARED = (ROOT / 'src/ios/Shared/CSPRecovery.swift').read_text()
LOGIN = (ROOT / 'src/ios/Views/Providers/ProviderInstancesView.swift').read_text()
PREVIEW = (ROOT / 'src/ios/Views/Chat/WebPreviewSheet.swift').read_text()
WEBAPP = (ROOT / 'src/ios/WebApp/WebAppWebViewController.swift').read_text()
PBX = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()


class SharedComponent(unittest.TestCase):
    def test_rebuilds_scripts_at_document_start(self):
        # Native injection is not subject to the page CSP; createElement-made
        # scripts are trusted through 'strict-dynamic'.
        self.assertIn("scriptRebuildSource", SHARED)
        self.assertIn("injectionTime: .atDocumentStart", SHARED)
        self.assertIn("createElement('script')", SHARED)
        self.assertIn("installScriptRebuild", SHARED)

    def test_keeps_original_navigation(self):
        # Re-rendering via loadHTMLString changed the security context and left
        # Discourse stuck; the rebuild path must not do that.
        self.assertNotIn("loadHTMLString(", SHARED)
        self.assertNotIn("repairIfStuck", SHARED)

    def test_probe_is_framework_agnostic(self):
        # Discourse-specific hint first, then a generic "scripts present but
        # nothing laid out" test so Vue/React sites are covered too.
        self.assertIn("d-splash", SHARED)
        self.assertIn("getElementsByTagName('script')", SHARED)
        self.assertIn("getBoundingClientRect()", SHARED)

    def test_does_not_use_inner_text_as_the_signal(self):
        # A stuck Discourse page still reports ~1.5 KB of hidden policy text,
        # so text length would mask the failure.
        self.assertNotIn("innerText.length", SHARED)

    def test_registered_in_project(self):
        self.assertIn("CSPRecovery.swift", PBX)
        self.assertGreaterEqual(PBX.count("CSPRecovery.swift"), 4)


class Wiring(unittest.TestCase):
    def test_provider_login_uses_it(self):
        self.assertIn("CSPRecovery.installScriptRebuild(in: config)", LOGIN)
        # The old per-site implementation must be gone.
        self.assertNotIn("repairIfSplashStuck", LOGIN)

    def test_chat_web_preview_uses_it(self):
        self.assertIn("CSPRecovery.installScriptRebuild(in: config)", PREVIEW)
        # The old post-hoc repair path is gone: recovery happens in the config hook.
        self.assertNotIn("repairIfStuck", PREVIEW)

    def test_webapp_uses_it(self):
        self.assertIn("CSPRecovery.installScriptRebuild(in: cfg)", WEBAPP)
        self.assertNotIn("repairIfStuck", WEBAPP)

    def test_all_call_sites_install_the_hook(self):
        for name, src in [('login', LOGIN), ('preview', PREVIEW), ('webapp', WEBAPP)]:
            with self.subTest(name):
                self.assertIn("installScriptRebuild", src)

    def test_automation_browser_is_not_wired(self):
        # BrowserUse drives pages programmatically; re-rendering would throw
        # away the DOM state it depends on.
        manager = (ROOT / 'src/ios/Agent/BrowserUse/BrowserUseManager.swift').read_text()
        self.assertNotIn("installScriptRebuild", manager)


class NoDeadEscapeHatch(unittest.TestCase):
    def test_external_browser_button_is_gone(self):
        # It could never help: cookies do not cross the iOS sandbox boundary,
        # so opening the site in Reynard/Safari changed nothing that the app
        # could read. The user pointed this out; the button is removed.
        self.assertNotIn("UIApplication.shared.open(url)", LOGIN)
        self.assertNotIn("用外部浏览器打开", LOGIN)


if __name__ == '__main__':
    unittest.main(verbosity=2)
