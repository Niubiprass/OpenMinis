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
/// Two parts:
///
/// 1. `scriptRebuildSource` — a WKUserScript injected at document start. Native
///    injection is not subject to the page's CSP, and every <script> it
///    re-creates is trusted through `'strict-dynamic'`, so the tags that would
///    have been dropped are loaded anyway. The original navigation is kept, so
///    origin, cookies and referrer are exactly what the server sent.
///
/// 2. `probeScript` / `diagnose` — after the page settles, check whether it
///    ever laid itself out, and report why if it did not.
///
/// Deliberately NOT applied to the automation browser (BrowserUse): it drives
/// pages through the DOM, and swapping script elements would fight it.
enum CSPRecovery {

    /// [T-csp-script-rebuild] Injected at `.atDocumentStart`, i.e. before the
    /// page parses its own <script> tags. A WKUserScript is native injection
    /// and is NOT subject to the site's CSP, so this code always runs; every
    /// script it re-creates through `createElement` is then trusted thanks to
    /// `'strict-dynamic'`.
    ///
    /// Why this instead of re-rendering the whole document: `loadHTMLString`
    /// produces a document with no HTTP response, which changes its origin /
    /// security context. Discourse needs a normal secure origin (it writes
    /// localStorage during boot), so a re-rendered copy still hung on the
    /// splash. Rebuilding the tags keeps the original navigation — origin,
    /// cookies, referrer and CSP all stay exactly as the server sent them.
    static let scriptRebuildSource = """
    (function () {
      var handled = new WeakSet();
      function repair() {
        var list = document.getElementsByTagName('script');
        for (var i = 0; i < list.length; i++) {
          var s = list[i];
          if (handled.has(s)) continue;
          var nonce = s.getAttribute('nonce');
          if (nonce && nonce.length > 0) { handled.add(s); continue; }
          handled.add(s);
          var c = document.createElement('script');
          for (var j = 0; j < s.attributes.length; j++) {
            var a = s.attributes[j];
            if (a.name === 'nonce') continue;
            try { c.setAttribute(a.name, a.value); } catch (e) {}
          }
          if (!s.src && s.textContent) c.textContent = s.textContent;
          try { s.parentNode.replaceChild(c, s); } catch (e) {}
        }
      }
      var timer = setInterval(repair, 20);
      setTimeout(function () { clearInterval(timer); }, 20000);
    })();
    """

    /// Builds the configuration hook that installs `scriptRebuildSource`.
    static func installScriptRebuild(in config: WKWebViewConfiguration) {
        let script = WKUserScript(source: scriptRebuildSource,
                                  injectionTime: .atDocumentStart,
                                  forMainFrameOnly: false)
        config.userContentController.addUserScript(script)
    }

    /// Injected after `didFinish`. Returns `"stuck"` only when the page is
    /// visually empty yet carries a real script payload.
    ///
    /// Deliberately avoids measuring `innerText`: a stuck Discourse page still
    /// reports ~1.5 KB of hidden policy text, so text length is not a signal.
    /// Layout size is.
    static let probeScript = """
    (function(){
      var body = document.body;
      if (!body) return 'ok';
      var splash = document.getElementById('d-splash');
      if (splash && getComputedStyle(splash).display !== 'none'
          && typeof Discourse === 'undefined') return 'stuck';
      var scripts = document.getElementsByTagName('script').length;
      if (scripts < 5) return 'ok';
      if (document.images.length > 0) return 'ok';
      var nodes = body.querySelectorAll('div,main,section,article,nav,header');
      var visible = 0;
      for (var i = 0; i < nodes.length && i < 400; i++) {
        var r = nodes[i].getBoundingClientRect();
        if (r.width > 40 && r.height > 20) {
          visible++;
          if (visible > 8) return 'ok';
        }
      }
      return visible <= 2 ? 'stuck' : 'ok';
    })()
    """

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
