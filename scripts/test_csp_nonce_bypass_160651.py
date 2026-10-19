#!/usr/bin/env python3
"""[T-csp-recovery] Guards on the CSP helpers after two failed repair attempts.

History, so this is not re-attempted blindly:
  1. loadHTMLString re-render — lost the page's security context, Discourse
     still hung.
  2. document-start <script> rebuild — fired on healthy sites (a "many scripts,
     little layout" heuristic cannot tell broken from legitimately empty) and
     made the page render its content twice.

Neither ships. What remains is inert: a diagnostic probe used for logging, and
a cancellation filter so our own navigation churn is not reported as a failure.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
SHARED = (ROOT / 'src/ios/Shared/CSPRecovery.swift').read_text()
LOGIN = (ROOT / 'src/ios/Views/Providers/ProviderInstancesView.swift').read_text()
PREVIEW = (ROOT / 'src/ios/Views/Chat/WebPreviewSheet.swift').read_text()
WEBAPP = (ROOT / 'src/ios/WebApp/WebAppWebViewController.swift').read_text()


class NoDangerousRepair(unittest.TestCase):
    def test_script_rebuild_is_gone(self):
        # It caused the double-render on new.j4.ccwu.cc.
        self.assertNotIn("scriptRebuildSource", SHARED)
        self.assertNotIn("installScriptRebuild", SHARED)
        for name, src in [('login', LOGIN), ('preview', PREVIEW), ('webapp', WEBAPP)]:
            with self.subTest(name):
                self.assertNotIn("installScriptRebuild", src)

    def test_no_document_replacement(self):
        # 注释里可以提历史，真正的调用不能有
        self.assertNotIn("webView.loadHTMLString(", SHARED)
        self.assertNotIn("repairIfStuck", SHARED)

    def test_heuristic_probe_is_gone(self):
        # It misjudged healthy pages; it must not come back without a real
        # signal (an explicit splash element), not a layout heuristic.
        self.assertNotIn("probeScript", SHARED)
        self.assertNotIn("visible <= 2", SHARED)


class SafeHelpers(unittest.TestCase):
    def test_diagnostic_never_shown_to_user(self):
        # A raw JSON blob in an alert is not an error message.
        self.assertNotIn("failedReason = info", LOGIN)
        self.assertIn("NSLog", LOGIN)

    def test_cancellation_is_ignored(self):
        self.assertIn("func isCancellation", SHARED)
        self.assertIn("NSURLErrorCancelled", SHARED)
        for name, src in [('login', LOGIN), ('preview', PREVIEW)]:
            with self.subTest(name):
                self.assertIn("CSPRecovery.isCancellation", src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
