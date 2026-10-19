import Foundation
import WebKit

/// [T-csp-recovery] Shared recovery for pages that download their scripts but
/// never run them.
///
/// The concrete case: linux.do serves Discourse with
/// `Content-Security-Policy: script-src 'nonce-…' 'strict-dynamic'` while the
/// HTML that reaches an iOS 15 WKWebView carries `nonce=""` on every script
/// tag. `strict-dynamic` still needs a trusted root, so nothing executes: the
/// framework global stays undefined and the splash spins forever. Safari and
/// every WKWebView on iOS 15 are hit; Gecko-based browsers are not.
///
/// Scope, after two failed attempts:
///
/// The first idea — re-render a stuck page through `loadHTMLString` — lost the
/// page's security context, so Discourse still hung.
/// The second — rebuild blocked <script> tags at document start — fired on
/// healthy sites: a heuristic that looks for "many scripts, little layout"
/// cannot tell a broken page from a legitimately empty one, and re-creating
/// the tags made the site render its content twice.
///
/// So this file no longer tries to repair anything on its own. It keeps only
/// the two helpers that are safe everywhere: a diagnostic probe (logging) and
/// the cancellation filter. Fixing linux.do specifically needs a targeted
/// approach, not a blanket heuristic.
enum CSPRecovery {

    /// [T-csp-recovery-diag] Reports why a re-rendered page still did not
    /// boot. Surfaced in the login sheet so a screenshot is enough to tell
    /// an opaque-origin failure (no localStorage) from a blocked-CDN one
    /// (no scripts) without needing a Mac + Web Inspector.
    static let diagnosticScript = """
    (function(){
      function ls(){
        try { localStorage.setItem('__diag','1'); localStorage.removeItem('__diag'); return 'ok'; }
        catch(e) { return 'FAIL:' + (e && e.name ? e.name : 'unknown'); }
      }
      var s = document.getElementById('d-splash');
      return JSON.stringify({
        href: location.href,
        origin: location.origin,
        secure: window.isSecureContext,
        ready: document.readyState,
        scripts: document.scripts.length,
        discourse: typeof Discourse,
        ember: typeof Ember,
        cookieLen: (document.cookie || '').length,
        ls: ls(),
        splash: s ? getComputedStyle(s).display : 'none'
      });
    })()
    """

    /// Runs the diagnostic probe and hands the JSON back on the main queue.
    static func diagnose(_ webView: WKWebView,
                         completion: @escaping (String) -> Void) {
        webView.evaluateJavaScript(diagnosticScript) { result, error in
            if let error = error {
                completion("诊断失败: \(error.localizedDescription)")
            } else {
                completion((result as? String) ?? "无数据")
            }
        }
    }

    /// [T-csp-recovery-cancel] True for NSURLErrorCancelled. A WebView reports
    /// this whenever a navigation is superseded — including our own recovery
    /// work — and surfacing it as an error made a normal transition look
    /// broken.
    static func isCancellation(_ error: Error) -> Bool {
        let ns = error as NSError
        return ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled
    }

}
